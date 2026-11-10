#!/usr/bin/env python3
"""Stage 0 §6: the 2×2 CPU-affinity × task-memory-policy ablation.

Each cell runs in a FRESH CHILD PROCESS (policy/affinity can never leak
between cells). Per cell:
  A  unpinned/default + MPOL_DEFAULT              (baseline)
  B  pinned to node X + MPOL_DEFAULT              (affinity only)
  C  unpinned/default + MPOL_BIND to node Y       (policy only)
  D  pinned to node X + MPOL_BIND to node Y       (conflicting controls)

Node argument semantics (WO-STAGE0-REHEARSAL-CORRECTIONS-3 §2.3):
  --node-x = the AFFINITY node: B and D pin a CPU of this node. It must
             have at least one CPU allowed by the process cpuset.
  --node-y = the POLICY node:   C and D bind MPOL_BIND to this node. It
             only needs online memory: on a real host a policy-only node
             may legitimately have no CPU in this process's cpuset.
  X and Y must differ. When omitted, the lowest-numbered distinct pair
  of online memory nodes is used, with X required to have an allowed CPU
  and Y only required to be online with memory.

Every cell records the symbolic AND numeric requested policy mode, the
effective mode/mask from get_mempolicy(), sched_getaffinity(), the CPU
executing the first touch, every syscall return code and errno, and
actual destination-page residency. A cell whose effective state does
not match the requested state is INVALID.

Two materialization forms are measured separately:
  map-fault  : first touch is an explicit one-byte WRITE through a
               MAP_SHARED mapping, then move_pages + numa_maps.
  write-path : write() into the memfd (production materializer shape),
               then MAP_SHARED + read-touch every page, then move_pages
               + numa_maps + mincore. Raw per-page statuses are kept.
               Stability is checked over the FULL measured range: every
               page's status after the read-touch must equal its status
               before it, and the unstable count is recorded.

Usage: ablation_2x2.py [--cells A,B,C,D] [--forms map-fault,write-path]
       [--size-bytes N] [--node-x X] [--node-y Y] [--json PATH]
"""

import argparse
import ctypes
import errno as _errno
import json
import mmap as _mmap
import os
import signal
import subprocess
import sys
import time

_MEMPOL_DEFAULT = 0
_MEMPOL_PREFERRED = 1
_MEMPOL_BIND = 2
_MEMPOL_NAMES = {
    0: "MPOL_DEFAULT",
    1: "MPOL_PREFERRED",
    2: "MPOL_BIND",
    3: "MPOL_INTERLEAVE",
    4: "MPOL_WEIGHTED_INTERLEAVE",
    5: "MPOL_LOCAL",
    6: "MPOL_PREFERRED_MANY",
}
_WORD_BITS = ctypes.sizeof(ctypes.c_ulong) * 8
_SHIMMED = None


def _shim():
    global _SHIMMED
    if _SHIMMED is not None:
        return _SHIMMED
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "libstage0.so")
    lib = ctypes.CDLL(path, use_errno=True)
    lib.stage0_query_nodes.restype = ctypes.c_int
    lib.stage0_query_nodes.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
    lib.stage0_apply_affinity.restype = ctypes.c_int
    lib.stage0_apply_affinity.argtypes = [ctypes.c_void_p, ctypes.c_long]
    lib.stage0_get_affinity.restype = ctypes.c_int
    lib.stage0_get_affinity.argtypes = [ctypes.c_void_p, ctypes.c_long]
    lib.stage0_set_mempolicy.restype = ctypes.c_int
    lib.stage0_set_mempolicy.argtypes = [
        ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p]
    lib.stage0_get_mempolicy.restype = ctypes.c_int
    lib.stage0_get_mempolicy.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    lib.stage0_sched_getcpu.restype = ctypes.c_int
    lib.stage0_sched_getcpu.argtypes = []
    lib.stage0_mincore.restype = ctypes.c_int
    lib.stage0_mincore.argtypes = [
        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    _SHIMMED = lib
    return lib


def _parse_list(spec):
    """Parse a kernel range list ('0-3,8') into ints."""
    out = []
    for part in (spec or "").strip().split(","):
        if not part:
            continue
        if "-" in part:
            lo, _, hi = part.partition("-")
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def _online_nodes():
    path = "/sys/devices/system/node/online"
    try:
        with open(path, encoding="ascii") as fh:
            return _parse_list(fh.read())
    except OSError:
        return []


def _node_cpus(node):
    path = "/sys/devices/system/node/node%d/cpulist" % node
    try:
        with open(path, encoding="ascii") as fh:
            return _parse_list(fh.read())
    except OSError:
        return []


def _node_mem_total_kb(node):
    path = "/sys/devices/system/node/node%d/meminfo" % node
    try:
        with open(path, encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith("Node %d MemTotal:" % node):
                    return int(line.split()[3])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _node_mem_free_kb(node):
    path = "/sys/devices/system/node/node%d/meminfo" % node
    try:
        with open(path, encoding="ascii", errors="replace") as fh:
            for line in fh:
                if line.startswith("Node %d MemFree:" % node):
                    return int(line.split()[3])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _allowed_cpus():
    try:
        return sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return list(range(os.cpu_count() or 0))


def _validate_node(node, role, require_allowed_cpu):
    if node not in _online_nodes():
        raise SystemExit("node %s=%d is not online (online=%s)" % (
            role, node, _online_nodes()))
    if _node_mem_total_kb(node) <= 0:
        raise SystemExit("node %s=%d has no memory" % (role, node))
    cpus = _node_cpus(node)
    if require_allowed_cpu:
        allowed = _allowed_cpus()
        if not any(c in allowed for c in cpus):
            raise SystemExit(
                "node %s=%d has no CPU in the process cpuset (node cpus=%s, "
                "allowed=%s)" % (role, node, cpus[:8], allowed[:8]))
    return cpus


def _select_nodes(node_x, node_y):
    """Resolve and validate (affinity node X, policy node Y).

    X must have an allowed CPU (B/D pin to it). Y is a POLICY node and
    only needs online memory: MPOL_BIND places pages there without
    requiring a CPU there, and on a real host the cpuset may exclude
    node Y's CPUs entirely.
    """
    allowed = _allowed_cpus()
    memory_nodes = [n for n in _online_nodes()
                    if _node_mem_total_kb(n) > 0]
    affinity_nodes = [n for n in memory_nodes
                      if any(c in allowed for c in _node_cpus(n))]
    if not affinity_nodes:
        raise SystemExit(
            "need at least one online memory node with a CPU in the "
            "process cpuset for the affinity arm; online memory nodes=%s "
            "allowed=%s" % (memory_nodes, allowed[:8]))
    if node_x is None and node_y is None:
        x = affinity_nodes[0]
        y = next((n for n in memory_nodes if n != x), None)
        if y is None:
            raise SystemExit("need a second online memory node distinct "
                             "from x=%d" % x)
    elif node_x is None:
        y = int(node_y)
        _validate_node(y, "y", require_allowed_cpu=False)
        x = next((n for n in affinity_nodes if n != y), None)
        if x is None:
            raise SystemExit("no affinity node with an allowed CPU distinct "
                             "from y=%d" % y)
    elif node_y is None:
        x = int(node_x)
        _validate_node(x, "x", require_allowed_cpu=True)
        y = next((n for n in memory_nodes if n != x), None)
        if y is None:
            raise SystemExit("no online memory node distinct from x=%d" % x)
    else:
        x, y = int(node_x), int(node_y)
        _validate_node(x, "x", require_allowed_cpu=True)
        _validate_node(y, "y", require_allowed_cpu=False)
    if x == y:
        raise SystemExit("node X (%d) must differ from node Y (%d)" % (x, y))
    return {
        "x": x,
        "y": y,
        "x_cpus": _node_cpus(x),
        "y_cpus": _node_cpus(y),
        "x_mem_total_kb": _node_mem_total_kb(x),
        "y_mem_total_kb": _node_mem_total_kb(y),
        "x_mem_free_kb": _node_mem_free_kb(x),
        "y_mem_free_kb": _node_mem_free_kb(y),
        "online_nodes": _online_nodes(),
        "allowed_cpus": allowed,
        "fake_numa": _fake_numa(),
    }


def _fake_numa():
    try:
        with open("/proc/cmdline", encoding="ascii", errors="replace") as fh:
            cmd = fh.read()
    except OSError:
        return None
    for token in cmd.split():
        if token.startswith("numa=fake="):
            return token
    return False


def _pick_cpu(node, allowed):
    cands = [c for c in _node_cpus(node) if c in allowed]
    if not cands:
        raise RuntimeError("no allowed CPU on node %d" % node)
    return cands[0]


def _mask_layout(node_ids):
    """Words and maxnode (bits) sized from the highest selected node id."""
    highest = max(node_ids) if node_ids else 0
    words = max(1, highest // _WORD_BITS + 1)
    return words, words * _WORD_BITS


def _mask_for(nodes, words):
    mask = (ctypes.c_ulong * words)()
    for node in nodes:
        mask[node // _WORD_BITS] |= 1 << (node % _WORD_BITS)
    return mask


def _mask_nodes(mask, words, maxnode):
    out = []
    for bit in range(maxnode):
        if mask[bit // _WORD_BITS] >> (bit % _WORD_BITS) & 1:
            out.append(bit)
    return out


def _effective(maxnode, words):
    lib = _shim()
    mode = ctypes.c_int(-1)
    mask = (ctypes.c_ulong * words)()
    ctypes.set_errno(0)
    rc = lib.stage0_get_mempolicy(ctypes.byref(mode), mask, maxnode)
    err = ctypes.get_errno()
    cpus_buf = (ctypes.c_int * 4096)()
    n = lib.stage0_get_affinity(cpus_buf, 4096)
    aff = sorted(cpus_buf[i] for i in range(n)) if n > 0 else None
    return {
        "mempolicy_mode": mode.value if rc == 0 else None,
        "mempolicy_mode_symbolic": _MEMPOL_NAMES.get(mode.value, "UNKNOWN")
        if rc == 0 else None,
        "mempolicy_mask_nodes": _mask_nodes(mask, words, maxnode)
        if rc == 0 else None,
        "mempolicy_mask_words": [int(mask[i]) for i in range(words)]
        if rc == 0 else None,
        "get_mempolicy_rc": rc,
        "get_mempolicy_errno": err if rc != 0 else 0,
        "affinity_cpus": aff,
    }


def _set_policy(mode, nodes, words, maxnode):
    lib = _shim()
    ctypes.set_errno(0)
    if mode == _MEMPOL_DEFAULT:
        rc = lib.stage0_set_mempolicy(_MEMPOL_DEFAULT, 0, None)
    else:
        mask = _mask_for(nodes, words)
        rc = lib.stage0_set_mempolicy(mode, maxnode, mask)
    err = ctypes.get_errno()
    return {
        "mode_numeric": mode,
        "mode_symbolic": _MEMPOL_NAMES.get(mode, "UNKNOWN"),
        "nodes": list(nodes),
        "maxnode_bits": maxnode,
        "set_rc": rc,
        "set_errno": err if rc != 0 else 0,
    }


def _apply_affinity(cpu):
    lib = _shim()
    cpus = (ctypes.c_int * 1)(cpu)
    ctypes.set_errno(0)
    rc = lib.stage0_apply_affinity(cpus, 1)
    err = ctypes.get_errno()
    return {"mode": "pinned", "cpu": cpu, "set_rc": rc,
            "set_errno": err if rc != 0 else 0}


def _query_nodes(addrs):
    lib = _shim()
    count = len(addrs)
    pages = (ctypes.c_void_p * count)(*addrs)
    status = (ctypes.c_int * count)(*([-999] * count))
    ctypes.set_errno(0)
    rc = lib.stage0_query_nodes(pages, status, count)
    err = ctypes.get_errno()
    return {"rc": rc, "errno": err if rc != 0 else 0,
            "statuses": [int(s) for s in status]}


def _numamap_counts(pid, needle):
    counts = {}
    try:
        with open("/proc/%d/numa_maps" % pid, encoding="utf-8",
                  errors="replace") as fh:
            for line in fh:
                if needle not in line:
                    continue
                for token in line.split():
                    if token.startswith("N") and "=" in token:
                        try:
                            node_s, _, pages_s = token[1:].partition("=")
                            node, pages = int(node_s), int(pages_s)
                        except ValueError:
                            continue
                        if pages:
                            counts[node] = counts.get(node, 0) + pages
    except OSError:
        return {}
    return counts


def _mincore(addr0, size_bytes, npages):
    lib = _shim()
    vec = (ctypes.c_ubyte * npages)()
    ctypes.set_errno(0)
    rc = lib.stage0_mincore(addr0, size_bytes, vec)
    err = ctypes.get_errno()
    resident = sum(1 for b in vec if b & 1) if rc == 0 else None
    return {"rc": rc, "errno": err if rc != 0 else 0,
            "resident_pages": resident, "total_pages": npages}


def _placement(statuses):
    by_node = {}
    negative = {}
    for status in statuses:
        if status >= 0:
            by_node[status] = by_node.get(status, 0) + 1
        else:
            negative[status] = negative.get(status, 0) + 1
    return by_node, negative


def _touch_write(addr):
    """Explicit one-byte WRITE fault (the map-fault contract)."""
    ctypes.c_ubyte.from_address(addr).value = 0x5A


def _touch_read(addr):
    """Read-touch only: establishes the PTE without modifying data."""
    return ctypes.c_ubyte.from_address(addr).value


def _run_one_cell(cell, form, size_bytes, node_x, node_y, pagesize):
    """Executed INSIDE the fresh child process — one cell, one form."""
    lib = _shim()
    allowed = _allowed_cpus()
    words, maxnode = _mask_layout([node_x, node_y])

    affinity_requested = {"mode": "default", "cpu": None, "set_rc": None,
                          "set_errno": 0}
    if cell in ("B", "D"):
        cpu = _pick_cpu(node_x, allowed)
        affinity_requested = _apply_affinity(cpu)
    else:
        cpu = None

    if cell in ("A", "B"):
        policy_requested = _set_policy(_MEMPOL_DEFAULT, [], words, maxnode)
    elif cell in ("C", "D"):
        policy_requested = _set_policy(_MEMPOL_BIND, [node_y], words, maxnode)
    else:
        raise ValueError(cell)

    effective = _effective(maxnode, words)
    checks = {
        "affinity_ok": True,
        "policy_ok": True,
        "checked_before_first_touch": True,
    }
    if cell in ("B", "D"):
        checks["affinity_ok"] = (
            effective["affinity_cpus"] == [cpu])
    if cell in ("A", "B"):
        checks["policy_ok"] = (
            effective["mempolicy_mode"] == _MEMPOL_DEFAULT)
    else:
        checks["policy_ok"] = (
            effective["mempolicy_mode"] == _MEMPOL_BIND
            and effective["mempolicy_mask_nodes"] == [node_y])

    establish_ok = (policy_requested["set_rc"] == 0
                    and affinity_requested["set_rc"] in (None, 0)
                    and checks["affinity_ok"] and checks["policy_ok"])
    if not establish_ok:
        return {
            "cell": cell, "form": form, "valid": False,
            "invalid_reason": "requested state was not established/verified",
            "affinity_requested": affinity_requested,
            "policy_requested": policy_requested,
            "effective": effective,
            "verification": checks,
            "pagesize": pagesize,
            "pages_total": max(1, size_bytes // pagesize),
        }

    fd = os.memfd_create("stage0_ablation_%s_%s" % (cell, form), 0)
    os.ftruncate(fd, size_bytes)
    npages = max(1, size_bytes // pagesize)
    name = "stage0_ablation_%s_%s" % (cell, form)

    try:
        cpu_at_touch = None
        read_touch_statuses = None
        if form == "map-fault":
            mm = _mmap.mmap(fd, size_bytes, flags=_mmap.MAP_SHARED)
            addr0 = ctypes.addressof(ctypes.c_char.from_buffer(mm, 0))
            addrs = [addr0 + i * pagesize for i in range(npages)]
            numamap_pre = _numamap_counts(os.getpid(), name)
            move_pre = _query_nodes(addrs)
            for i, addr in enumerate(addrs):
                _touch_write(addr)  # explicit one-byte WRITE fault
                if i == 0:
                    cpu_at_touch = lib.stage0_sched_getcpu()
            touched = npages
            touch_kind = "write"
        elif form == "write-path":
            # Production materializer's shape: write() into the memfd
            # under the task's mempolicy. Then map the ALREADY-POPULATED
            # range MAP_SHARED and read-touch it (no writes here).
            buf = b"\x01" * 65536
            off = 0
            while off < size_bytes:
                n = os.write(fd, buf[:min(len(buf), size_bytes - off)])
                if n <= 0:
                    raise RuntimeError("short write at offset %d" % off)
                off += n
                if cpu_at_touch is None:
                    cpu_at_touch = lib.stage0_sched_getcpu()
            mm = _mmap.mmap(fd, size_bytes, flags=_mmap.MAP_SHARED)
            addr0 = ctypes.addressof(ctypes.c_char.from_buffer(mm, 0))
            addrs = [addr0 + i * pagesize for i in range(npages)]
            numamap_pre = _numamap_counts(os.getpid(), name)
            move_pre = _query_nodes(addrs)
            # Record each page's placement immediately after its own first
            # read-touch, in batches, then re-query EVERY page after the
            # full range has been read-touched. A difference means the
            # rest of the range's read-touch moved that page. (Querying
            # before the first touch is not valid: an un-faulted page has
            # no observable placement yet, so it would report -ENOENT and
            # every page would look "unstable" for the wrong reason.)
            read_touch_statuses = []
            for start in range(0, npages, 64):
                batch = addrs[start:start + 64]
                for addr in batch:
                    _touch_read(addr)  # establish PTEs, do not modify data
                read_touch_statuses.extend(
                    _query_nodes(batch)["statuses"])
            touched = npages
            touch_kind = "read"
        else:
            raise ValueError(form)

        move_post = _query_nodes(addrs)
        numamap_post = _numamap_counts(os.getpid(), name)
        mincore = _mincore(addr0, size_bytes, npages)
        by_node, negative = _placement(move_post["statuses"])
        placement_measured = bool(by_node) and move_post["rc"] == 0
        changed = (bool(numamap_pre) and bool(numamap_post)
                   and numamap_pre != numamap_post)
        if form == "write-path":
            # Full-range stability: every page's status recorded just
            # after its first read-touch is compared with its status
            # after the whole range was read-touched.
            unstable = sum(
                1 for before, after in zip(read_touch_statuses,
                                           move_post["statuses"])
                if before != after)
            read_touch_stable = (unstable == 0)
        else:
            read_touch_statuses = None
            read_touch_stable = None
            unstable = None
        mm.close()
    finally:
        os.close(fd)

    return {
        "cell": cell,
        "form": form,
        "valid": True,
        "invalid_reason": None,
        "affinity_requested": affinity_requested,
        "policy_requested": policy_requested,
        "effective": effective,
        "verification": checks,
        "cpu_at_first_touch": cpu_at_touch,
        "pages_total": npages,
        "pagesize": pagesize,
        "pages_by_node": by_node,
        "pages_unknown": sum(negative.values()),
        "pages_negative_status_counts": {str(k): v
                                         for k, v in sorted(negative.items())},
        "placement_measured": placement_measured,
        "move_pages_pre": move_pre,
        "move_pages_post": move_post,
        "mincore": mincore,
        "numamap_pre": numamap_pre,
        "numamap_post": numamap_post,
        "numamap_changed_by_touch": changed,
        "first_page_after_first_touch": (
            read_touch_statuses[0] if read_touch_statuses else None),
        "first_page_after_full_touch": move_post["statuses"][0],
        "read_touch_statuses_after_first_touch": read_touch_statuses,
        "read_touch_stable": read_touch_stable,
        "read_touch_unstable_pages": unstable,
        "read_touch_range_pages": npages if form == "write-path" else None,
        "touch": {"kind": touch_kind, "pages_touched": touched},
        "object_measured": (
            "destination memfd; explicit one-byte write faults through a "
            "MAP_SHARED mapping; staging buffer NOT present"
            if form == "map-fault" else
            "destination memfd; write(2) into the fd (production "
            "materializer shape), then MAP_SHARED read-touch; the "
            "read-touch does not modify the data"),
    }


def _child_main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--form", required=True)
    ap.add_argument("--size-bytes", type=int, default=8 << 20)
    ap.add_argument("--node-x", type=int, required=True)
    ap.add_argument("--node-y", type=int, required=True)
    args = ap.parse_args()
    pagesize = os.sysconf("SC_PAGE_SIZE")
    result = _run_one_cell(args.cell, args.form, args.size_bytes,
                           args.node_x, args.node_y, pagesize)
    print("CELLJSON " + json.dumps(result, sort_keys=True))
    return 0


def _run_cells(cells, forms, size_bytes, nodes, timeout=180):
    results = []
    for cell in cells:
        for form in forms:
            cmd = [sys.executable, os.path.abspath(__file__),
                   "--cell", cell, "--form", form,
                   "--size-bytes", str(size_bytes),
                   "--node-x", str(nodes["x"]), "--node-y", str(nodes["y"])]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True,
                                    start_new_session=True)
            timed_out = False
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                try:
                    out, err = proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    out, err = "", ""
            per_cell = None
            for line in (out or "").splitlines():
                if line.startswith("CELLJSON "):
                    per_cell = json.loads(line[len("CELLJSON "):])
                    break
            if per_cell is None:
                per_cell = {"cell": cell, "form": form, "valid": False,
                            "invalid_reason": "child produced no CELLJSON",
                            "child_rc": proc.returncode,
                            "timed_out": timed_out,
                            "stderr_tail": (err or "")[-1500:]}
            per_cell["child_rc"] = proc.returncode
            per_cell["child_timed_out"] = timed_out
            results.append(per_cell)
            print("cell %s/%s: valid=%s placement=%s by_node=%s "
                  "unknown=%d" % (
                      cell, form, per_cell.get("valid"),
                      per_cell.get("placement_measured"),
                      per_cell.get("pages_by_node"),
                      per_cell.get("pages_unknown", -1)))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cells", default="A,B,C,D")
    ap.add_argument("--forms", default="map-fault,write-path")
    ap.add_argument("--size-bytes", type=int, default=8 << 20)
    ap.add_argument("--node-x", type=int, default=None,
                    help="affinity node for B/D (default: auto)")
    ap.add_argument("--node-y", type=int, default=None,
                    help="MPOL_BIND node for C/D (default: auto)")
    ap.add_argument("--campaign-id", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--cell", default=None)   # internal child mode
    ap.add_argument("--form", default=None)
    args = ap.parse_args()
    if args.cell:
        return _child_main()
    cells = [c.strip() for c in args.cells.split(",") if c.strip()]
    forms = [f.strip() for f in args.forms.split(",") if f.strip()]
    if not (0 < args.size_bytes < (1 << 31)):
        raise SystemExit("size_bytes out of range")
    nodes = _select_nodes(args.node_x, args.node_y)
    results = _run_cells(cells, forms, args.size_bytes, nodes)
    doc = {
        "schema": "stage0-ablation/2",
        "campaign_id": args.campaign_id,
        "generated_epoch": time.time(),
        "generated_monotonic": time.monotonic(),
        "size_bytes": args.size_bytes,
        "pagesize": os.sysconf("SC_PAGE_SIZE"),
        "nodes": nodes,
        "cells": cells,
        "forms": forms,
        "results": results,
        "all_valid": all(r.get("valid") for r in results),
        "all_placement_measured": all(r.get("placement_measured")
                                      for r in results),
    }
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)),
                    exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, sort_keys=True)
    return 0 if doc["all_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
