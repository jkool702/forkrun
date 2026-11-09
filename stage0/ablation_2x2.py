#!/usr/bin/env python3
"""Stage 0 §6: the 2×2 CPU-affinity × task-memory-policy ablation.

Each cell uses a FRESH, previously-uninstantiated memfd range; the
policy/affinity change is made before the measured first touch;
destination-page residency is queried immediately afterward (move_pages
query mode; /proc/self/numa_maps as secondary). Cases:

  A  unpinned / MPOL_DEFAULT           (baseline)
  B  pinned to node X / MPOL_DEFAULT   (affinity only)
  C  unpinned / MPOL_BIND node Y       (policy only)
  D  pinned to X / MPOL_BIND node Y, X != Y  (conflicting controls)

State clearly which memory object is measured: both the staging buffer
(sender-mapped) and the destination memfd are reported.

Usage: ablation_2x2.py [--cells A,B,C,D] [--size-bytes N]
       [--json PATH]
"""

import ctypes
import json
import os
import sys

_MEMPOL_DEFAULT = 0
_MEMPOL_BIND = 1
MPAQ_NA = 0xFF


def _libc():
    """glibc (not the main program). Asserts the sched symbols exist at
    load, so a missing symbol is a loud campaign error rather than a
    late AttributeError. NOTE: set_mempolicy is NOT in libc (libnuma
    owns it) — the shim handles it."""
    lib = ctypes.CDLL("libc.so.6", use_errno=True)
    for sym in ("sched_setaffinity", "sched_getaffinity"):
        if not hasattr(lib, sym):
            raise RuntimeError(
                "libc.so.6 lacks %s — the 2x2 ablation cannot run on "
                "this toolchain" % sym)
    return lib


def _cpu_count():
    return os.cpu_count() or 1


def _shim():
    """The typed wrappers (ctypes marshalling of the syscall prototypes
    proved unreliable via libc.syscall(); also set_mempolicy is NOT in
    libc — it lives in libnuma — so one shim serves all of it).
    See residency_shim.c."""
    import os as _os
    import ctypes as _ct
    p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                      "libstage0.so")
    lib = _ct.CDLL(p, use_errno=True)
    lib.stage0_query_nodes.restype = ctypes.c_int
    lib.stage0_query_nodes.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
    lib.stage0_sched_setaffinity.restype = ctypes.c_int
    lib.stage0_sched_setaffinity.argtypes = [
        ctypes.c_long, ctypes.c_ulong, ctypes.c_void_p]
    lib.stage0_set_mempolicy.restype = ctypes.c_int
    lib.stage0_set_mempolicy.argtypes = [
        ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p]
    return lib


def residency_mempolicy_nodes(addrs, pagesize):
    """move_pages(query) per page -> list of node or None (MPAQ_NA)."""
    libc = _libc()
    shim = _shim()
    out = []
    for addr in addrs:
        pages = (ctypes.c_void_p * 1)(ctypes.c_void_p(addr))
        status = (ctypes.c_int * 1)(0)
        r = shim.stage0_query_nodes(pages, status, 1)
        if r != 0:
            errno = ctypes.get_errno()
            if errno in (1, 38, 22):  # EPERM, ENOSYS, EINVAL
                return None
            out.append(None)
            continue
        out.append(status[0] if status[0] != -1 else None)
    return out


def residency_numamap(needle):
    """Parse /proc/self/numa_maps lines containing needle -> node counts.

    Format per line:
      addr page_index node(counts as 'N<index>=<pages>' tokens)...
    e.g. '7f.. default file=/path mapped=1 active=0
    N0=1024 N1=0 ...'
    The needle must be a substring of the VMA's file= field.
    """
    counts = {}
    try:
        with open("/proc/self/numa_maps", encoding="utf-8",
                  errors="replace") as fh:
            for line in fh:
                if needle not in line:
                    continue
                parts = line.split()
                addr = parts[0] if parts else ""
                for token in parts:
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


def set_affinity(cpu):
    """Pin the calling thread to one CPU. 8-byte mask; fine for <64
    CPUs (dev i9: 28). Returns the sched_setaffinity() return code."""
    buf = (ctypes.c_byte * 8)()
    buf[cpu // 8] = (1 << (cpu % 8))
    return _shim().stage0_sched_setaffinity(0, 8, buf)


def set_policy(policy, node=None):
    if policy == _MEMPOL_BIND:
        nodes = (ctypes.c_ulong * 1)(1 << node)
        return _shim().stage0_set_mempolicy(policy, 8, nodes)
    return _shim().stage0_set_mempolicy(policy, 0, None)


def run_cell(cell, size_bytes, node_x, node_y, pagesize):
    """Returns the measured dict for one cell. Caller must have NOT
    touched the destination range; we create it fresh here."""
    import mmap as _mmap
    affinity_cpu = None
    policy_rec = {"policy": "DEFAULT", "set_rc": None, "node": None}
    affinity_rec = {"cpu": None, "set_rc": None}

    if cell == "A":
        pass
    elif cell == "B":
        affinity_cpu = node_x * 7 if node_x else 0  # first cpu of node X
        affinity_rec = {"cpu": affinity_cpu,
                        "set_rc": set_affinity(affinity_cpu)}
        policy_rec = {"policy": "DEFAULT",
                      "set_rc": set_policy(_MEMPOL_DEFAULT), "node": None}
    elif cell == "C":
        policy_rec = {"policy": "BIND", "node": node_y,
                      "set_rc": set_policy(_MEMPOL_BIND, node_y)}
    elif cell == "D":
        affinity_cpu = node_y * 7 if node_y else 0  # pinned to X=node_y
        affinity_rec = {"cpu": affinity_cpu,
                        "set_rc": set_affinity(affinity_cpu)}
        policy_rec = {"policy": "BIND", "node": node_x,
                      "set_rc": set_policy(_MEMPOL_BIND, node_x)}
    else:
        raise ValueError(cell)

    # Fresh memfd, destination range guaranteed uninstantiated.
    fd = os.memfd_create("stage0_ablation_%s" % cell, 0)
    os.ftruncate(fd, size_bytes)  # logical size; still sparse (uninstantiated)
    # First touch goes through a mapping; ftruncate leaves it sparse.
    mm = _mmap.mmap(fd, size_bytes, flags=_mmap.MAP_SHARED)
    npages = size_bytes // pagesize
    addrs = [ctypes.addressof(ctypes.c_char.from_buffer(mm, i * pagesize))
             for i in range(npages)]
    # FIRST TOUCH: single-threaded, post policy/affinity change.
    for addr in addrs:
        ctypes.string_at(addr, 1)
    residency = residency_mempolicy_nodes(addrs, pagesize)
    numamap = residency_numamap("stage0_ablation_%s" % cell)
    mm.close()
    os.close(fd)
    # restore default policy for subsequent cells
    set_policy(_MEMPOL_DEFAULT)
    by_node = {}
    unknown = 0
    for node in residency or []:
        if node is None:
            unknown += 1
        else:
            by_node[node] = by_node.get(node, 0) + 1
    return {
        "cell": cell,
        "affinity": affinity_rec,
        "policy": policy_rec,
        "pages_total": npages,
        "pages_by_node": by_node,
        "pages_unknown": unknown,
        "pagesize": pagesize,
        "numamap_counts": numamap,
        "measurement": ("move_pages(query) per destination-memfd page; "
                        "numa_maps as secondary").replace("\n", " "),
        "object_measured": "destination memfd (first touch through "
                           "MAP_SHARED mapping; no staging buffer in "
                           "this ablation)",
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cells", default="A,B,C,D")
    ap.add_argument("--size-bytes", type=int, default=8 << 20)
    ap.add_argument("--node-x", type=int, default=1)
    ap.add_argument("--node-y", type=int, default=2)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    import os as _os
    pagesize = _os.sysconf("SC_PAGE_SIZE") if hasattr(_os, "sysconf") \
        else 4096
    results = []
    for cell in [c.strip() for c in args.cells.split(",") if c.strip()]:
        r = run_cell(cell, args.size_bytes, args.node_x, args.node_y,
                     pagesize)
        results.append(r)
        print("cell %s: pages=%d by_node=%s unknown=%d" % (
            cell, r["pages_total"], r["pages_by_node"],
            r["pages_unknown"]))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"results": results}, fh, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
