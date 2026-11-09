#!/usr/bin/env python3
"""Stage 0 §6: the 2×2 CPU-affinity × task-memory-policy ablation.

Each cell runs in a FRESH CHILD PROCESS (policy/affinity can never leak
between cells). Per cell:
  A  unpinned/default + MPOL_DEFAULT          (baseline)
  B  pinned to node X + MPOL_DEFAULT          (affinity only)
  C  unpinned/default + MPOL_BIND node Y      (policy only)
  D  pinned to node X + MPOL_BIND node Y, X != Y (conflicting controls)

Records, per cell: requested AND effective state (sched_getaffinity /
get_mempolicy queried immediately before first touch), the actual CPU
executing the first-touch operation (sched_getcpu), every syscall
return code, and actual destination-page residency via move_pages()
plus /proc/<pid>/numa_maps (secondary, dual-evidence agreement).
Two materialization forms are covered separately (work order §2.1):
  map-fault  : first touch through a MAP_SHARED mapping (explicit
               write fault into the mapped range)
  write-path : os.write() into the memfd fd (the current production
               materializer's shape: sendfile/write under the task's
               mempolicy, no mapping)
Results from the two forms are labelled so synthetic-mapping results
are never generalized to the write path without evidence.

Usage: ablation_2x2.py [--cells A,B,C,D] [--forms map-fault,write-path]
       [--size-bytes N] [--node-x X] [--node-y Y] [--json PATH]
"""

import argparse
import ctypes
import json
import os
import statistics as _st

_MEMPOL_DEFAULT = 0
_MEMPOL_BIND = 2  # MPOL_PREFERRED is 1; MPOL_BIND is 2 (numaif.h)
MPAQ_NA = 0xFF


def _node_cpus(node):
    path = "/sys/devices/system/node/node%d/cpulist" % node
    try:
        with open(path, encoding="ascii") as fh:
            spec = fh.read().strip()
    except OSError:
        return None
    cpus = []
    for part in spec.split(","):
        if "-" in part:
            lo, _, hi = part.partition("-")
            cpus.extend(range(int(lo), int(hi) + 1))
        elif part:
            cpus.append(int(part))
    return cpus


def _allowed_cpus():
    try:
        return sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return list(range(os.cpu_count() or 0))


def _pick_cpu(node, allowed):
    cands = _node_cpus(node) or []
    both = [c for c in cands if c in allowed]
    if not both:
        raise RuntimeError(
            "no CPU of node %d is in the process cpuset (allowed=%s)" %
            (node, allowed[:8]))
    return both[0]


def _shim():
    import os as _os
    import ctypes as _ct
    p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                      "libstage0.so")
    lib = _ct.CDLL(p, use_errno=True)
    lib.stage0_query_nodes.restype = ctypes.c_int
    lib.stage0_query_nodes.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
    lib.stage0_apply_affinity.restype = ctypes.c_int
    lib.stage0_apply_affinity.argtypes = [
        ctypes.c_void_p, ctypes.c_long]  # const int* cpus, ncpus
    lib.stage0_get_affinity.restype = ctypes.c_int
    lib.stage0_get_affinity.argtypes = [ctypes.c_void_p]
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
    return lib


def _residency(addrs):
    shim = _shim()
    out = []
    for addr in addrs:
        pages = (ctypes.c_void_p * 1)(addr)
        status = (ctypes.c_int * 1)(0)
        r = shim.stage0_query_nodes(pages, status, 1)
        if r != 0:
            errno = ctypes.get_errno()
            if errno in (1, 38, 22):
                return None  # query method unavailable
            out.append(None)
            continue
        # status semantics: >=0 node index; -1 query error; -2 page not
        # present. write()-instantiated shmem pages return -2 for every
        # page even when mapped — so move_pages is NOT a viable
        # residency source for the write-path; /proc/<pid>/numa_maps is.
        out.append(status[0] if status[0] >= 0 else None)
    return out


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
                            node = int(node_s)
                            pages = int(pages_s)
                        except ValueError:
                            continue
                        if pages:
                            counts[node] = counts.get(node, 0) + pages
    except OSError:
        return {}
    return counts


def _effective():
    shim = _shim()
    cpus_buf = (ctypes.c_int * 4096)()
    n = shim.stage0_get_affinity(cpus_buf)
    eff_cpus = sorted(cpus_buf[i] for i in range(n)) if n > 0 else None
    mode_buf = ctypes.c_int()
    mask = (ctypes.c_ulong * 64)(0)
    gm = shim.stage0_get_mempolicy(ctypes.byref(mode_buf), mask, 64)
    return {
        "affinity_cpus": eff_cpus,
        "mempolicy_mode": mode_buf.value if gm == 0 else None,
        "mempolicy_mask": mask[0] if gm == 0 else None,
        "get_mempolicy_rc": gm,
    }


def _run_one_cell(cell, form, size_bytes, node_x, node_y, pagesize):
    """Executed INSIDE the fresh child process — one cell, one form."""
    import mmap as _mmap
    shim = _shim()
    allowed = _allowed_cpus()
    # --- establish requested state -------------------------------
    affinity_rec = {"cpu": None, "set_rc": None}
    policy_rec = {"policy": "DEFAULT", "set_rc": None, "node": None}
    if cell == "A":
        affinity_rec = {"cpu": "default", "set_rc": 0}
        policy_rec = {"policy": "DEFAULT", "set_rc": 0, "node": None}
    elif cell == "B":
        cpu = _pick_cpu(node_x, allowed)
        cpus = (ctypes.c_int * 1)(cpu)
        rc = shim.stage0_apply_affinity(cpus, 1)
        affinity_rec = {"cpu": cpu, "set_rc": rc}
        policy_rec = {"policy": "DEFAULT",
                      "set_rc": shim.stage0_set_mempolicy(0, 0, None),
                      "node": None}
    elif cell == "C":
        affinity_rec = {"cpu": "default", "set_rc": 0}
        nodes = (ctypes.c_ulong * 1)(1 << node_y)
        rc = shim.stage0_set_mempolicy(1, 8, nodes)
        policy_rec = {"policy": "BIND", "node": node_y, "set_rc": rc}
    elif cell == "D":
        cpu = _pick_cpu(node_y, allowed)
        cpus = (ctypes.c_int * 1)(cpu)
        rc1 = shim.stage0_apply_affinity(cpus, 1)
        nodes = (ctypes.c_ulong * 1)(1 << node_x)
        rc2 = shim.stage0_set_mempolicy(1, 8, nodes)
        affinity_rec = {"cpu": cpu, "set_rc": rc1}
        policy_rec = {"policy": "BIND", "node": node_x, "set_rc": rc2}
    else:
        raise ValueError(cell)

    # --- capture EFFECTIVE state immediately before first touch --
    effective = _effective()
    establish_ok = (
        (affinity_rec["set_rc"] in (None, 0)) and
        (policy_rec["set_rc"] == 0))
    if not establish_ok:
        return {"cell": cell, "form": form, "valid": False,
                "reason": "requested state could not be established",
                "affinity_requested": affinity_rec,
                "policy_requested": policy_rec, "effective": effective}

    # --- fresh destination range (sparse, uninstantiated) --------
    fd = os.memfd_create("stage0_ablation_%s_%s" % (cell, form), 0)
    os.ftruncate(fd, size_bytes)
    npages = max(1, size_bytes // pagesize)

    if form == "map-fault":
        mm = _mmap.mmap(fd, size_bytes, flags=_mmap.MAP_SHARED)
        addr0 = ctypes.addressof(ctypes.c_char.from_buffer(mm, 0))
        addrs = [addr0 + i * pagesize for i in range(npages)]
        cpu_at_touch = None
        for addr in addrs:  # explicit write fault into the mapping
            ctypes.string_at(addr, 1)
            if cpu_at_touch is None:
                cpu_at_touch = shim.stage0_sched_getcpu()
        residency = _residency(addrs)
        numamap = _numamap_counts(os.getpid(), "stage0_ablation_%s_%s"
                                  % (cell, form))
        mm.close()
    elif form == "write-path":
        # The production materializer's shape: write() into the memfd
        # under the task's mempolicy (sendfile/write in the engine).
        # Residency evidence differs from map-fault (measured on this
        # box, both with and without MBIND): move_pages() returns the
        # -2 "page not present" status for EVERY write()-instantiated
        # page, and /proc/<pid>/numa_maps carries no N-fields for the
        # VMA, either — writes instantiate pages against the inode, not
        # the VMA. The working evidence pair is: mincore() residency
        # bits (page present?) + `numastat -p` per-node process totals
        # sampled before/after (which node absorbed the pages).
        import subprocess as _sp
        def numastat_totals(pid):
            try:
                r = _sp.run(["numastat", "-p", str(pid)],
                            capture_output=True, text=True, timeout=30)
                vals = {}
                for line in r.stdout.splitlines():
                    # "Private  3.18  0.00 ..." rows carry per-node MB.
                    parts = line.split()
                    if not parts:
                        continue
                    if parts[0].lower() in ("private", "total",
                                             "shared", "stack"):
                        vals[parts[0]] = [float(x) for x in parts[1:5]]
                return vals
            except (OSError, ValueError, subprocess.SubprocessError):
                return {}
        before = numastat_totals(os.getpid())
        buf = b"\x01" * 65536
        cpu_at_touch = None
        for off in range(0, size_bytes, len(buf)):
            n = os.write(fd, buf)
            if cpu_at_touch is None:
                cpu_at_touch = shim.stage0_sched_getcpu()
            if n != len(buf):
                raise RuntimeError("short write at offset %d" % off)
        after = numastat_totals(os.getpid())
        node_delta = {}
        for row in ("Private", "Total"):
            if row in after and row in before:
                for k in range(min(len(after[row]), len(before[row]))):
                    d = after[row][k] - before[row][k]
                    if abs(d) > 1e-9:
                        node_delta[k] = round(d, 3)
        # mincore residency bits over a fresh mapping (pages must be
        # present for the measurement to mean anything)
        mm = _mmap.mmap(fd, size_bytes, flags=_mmap.MAP_SHARED)
        addr0 = ctypes.addressof(ctypes.c_char.from_buffer(mm, 0))
        vec = (ctypes.c_ubyte * npages)()
        mr = shim.stage0_mincore(addr0, size_bytes, vec)
        resident = sum(1 for b in vec if b & 1) if mr == 0 else -1
        residency = "numastat-delta+mincore"
        numamap = {}
        mm.close()
        result = {"cell": cell, "form": form, "valid": True,
                  "affinity_requested": affinity_rec,
                  "policy_requested": policy_rec,
                  "effective": effective,
                  "cpu_at_first_touch": cpu_at_touch,
                  "pages_total": npages,
                  "pages_by_node": {},
                  "pages_unknown": 0,
                  "pagesize": pagesize,
                  "numamap_counts": numamap,
                  "mincore_resident_pages": resident,
                  "numastat_delta_mb": node_delta,
                  "residency_method": residency,
                  "move_pages_note": ("returns -2 (page not present) "
                                      "for every write()-instantiated "
                                      "page; not usable for this form"),
                  "object_measured": ("destination memfd; write() into "
                                      "the fd (production sendfile/write "
                                      "shape); residency via mincore + "
                                      "numastat -p deltas")}
        os.close(fd)
        return result
    else:
        raise ValueError(form)
    os.close(fd)

    by_node = {}
    unknown = 0
    for node in residency or []:
        if node is None:
            unknown += 1
        else:
            by_node[node] = by_node.get(node, 0) + 1
    return {"cell": cell, "form": form, "valid": True,
            "affinity_requested": affinity_rec,
            "policy_requested": policy_rec,
            "effective": effective,
            "cpu_at_first_touch": cpu_at_touch,
            "pages_total": npages,
            "pages_by_node": by_node,
            "pages_unknown": unknown,
            "pagesize": pagesize,
            "numamap_counts": numamap,
            "object_measured": ("destination memfd; map-fault touches via "
                                "MAP_SHARED mapping, write-path via "
                                "write(2) into the fd (production "
                                "sendfile/write shape without the copy)")
            if form == "write-path" else
            ("destination memfd; first touch through MAP_SHARED mapping "
             "(write fault); staging buffer NOT present in this ablation")}


def _child_main():
    import argparse, json, os as _os
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", required=True)
    ap.add_argument("--form", required=True)
    ap.add_argument("--size-bytes", type=int, default=8 << 20)
    args = ap.parse_args()
    pagesize = _os.sysconf("SC_PAGE_SIZE")
    r = _run_one_cell(args.cell, args.form, args.size_bytes,
                      1, 2, pagesize)
    print("CELLJSON " + json.dumps(r, sort_keys=True))
    return 0


def _run_cells(cells, forms, size_bytes, node_x, node_y, timeout=120):
    """Driver: one fresh child process per (cell, form)."""
    import subprocess
    results = []
    for cell in cells:
        for form in forms:
            cmd = [sys_path(), os.path.abspath(__file__), "--cell", cell,
                   "--form", form, "--size-bytes", str(size_bytes)]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout)
            per_cell = None
            for line in proc.stdout.splitlines():
                if line.startswith("CELLJSON "):
                    per_cell = json.loads(line[len("CELLJSON "):])
                    break
            if per_cell is None:
                per_cell = {"cell": cell, "form": form, "valid": False,
                            "reason": "child failed",
                            "rc": proc.returncode,
                            "stderr_tail": proc.stderr[-1500:]}
            per_cell["child_rc"] = proc.returncode
            results.append(per_cell)
            print("cell %s/%s: valid=%s by_node=%s unknown=%d" % (
                cell, form, per_cell.get("valid"),
                per_cell.get("pages_by_node"), per_cell.get("pages_unknown", -1)))
    return results


def sys_path():
    return sys.executable


def main():
    global sys
    import sys
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cells", default="A,B,C,D")
    ap.add_argument("--forms", default="map-fault,write-path")
    ap.add_argument("--size-bytes", type=int, default=8 << 20)
    ap.add_argument("--node-x", type=int, default=1)
    ap.add_argument("--node-y", type=int, default=2)
    ap.add_argument("--json", default=None)
    ap.add_argument("--cell", default=None)   # internal child mode
    ap.add_argument("--form", default=None)
    args = ap.parse_args()
    if args.cell:
        return _child_main()
    cells = [c.strip() for c in args.cells.split(",") if c.strip()]
    forms = [f.strip() for f in args.forms.split(",") if f.strip()]
    if args.node_x == args.node_y:
        raise SystemExit("node X must differ from node Y (spec §6 cell D)")
    if not (0 < args.size_bytes < (1 << 31)):
        raise SystemExit("size_bytes out of range")
    results = _run_cells(cells, forms, args.size_bytes,
                         args.node_x, args.node_y)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"results": results}, fh, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
