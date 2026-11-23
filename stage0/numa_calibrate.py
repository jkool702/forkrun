#!/usr/bin/env python3
"""NUMA hardware calibration utility (master WO 8).

Characterizes the rental host independently of the distributed-ingest
prototype. Measures (where possible):

- Local memory read bandwidth per NUMA node.
- Local memory copy bandwidth per NUMA node.
- Remote memory read bandwidth between node pairs.
- Remote memory copy bandwidth for representative node pairs.
- Observed CPU affinity.
- Requested and observed memory placement.
- Measurement duration and variance.

Method: pinned threads (sched_setaffinity) and explicit memory placement
(numa_alloc_onnode). Placement is verified by reading back pages with
move_pages() -- a successful mbind() is NOT accepted as placement proof.

This is diagnostic context only: results are NOT included in dist-ingest
candidate throughput statistics.

Usage:
  python3 stage0/numa_calibrate.py --out <path> [--samples N] [--size-mb N]
"""

import argparse
import ctypes
import ctypes.util
import json
import math
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

_libnuma = None


def _numa():
    global _libnuma
    if _libnuma is None:
        _libnuma = ctypes.CDLL(ctypes.util.find_library("numa") or "libnuma.so.1")
        _libnuma.numa_alloc_onnode.restype = ctypes.c_void_p
        _libnuma.numa_alloc_onnode.argtypes = [ctypes.c_size_t, ctypes.c_int]
        _libnuma.numa_free.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        _libnuma.numa_run_on_node.argtypes = [ctypes.c_int]
        _libnuma.numa_set_membind.argtypes = [ctypes.c_void_p]
        _libnuma.numa_set_membind.restype = ctypes.c_int
        _libnuma.move_pages.argtypes = [ctypes.c_int, ctypes.c_ulong,
                                        ctypes.POINTER(ctypes.c_void_p),
                                        ctypes.POINTER(ctypes.c_int),
                                        ctypes.POINTER(ctypes.c_int),
                                        ctypes.c_int]
        _libnuma.move_pages.restype = ctypes.c_int
    return _libnuma


def _nodes_and_cpus():
    """Discover NUMA nodes and one usable CPU per node (dynamic)."""
    sys.path.insert(0, HERE)
    import env_capture
    topo = env_capture.cpu_topology()
    nodes = []
    for name in sorted(topo.get("nodes", {}).keys()):
        node_id = int(name.replace("node", "") or 0)
        cpulist = topo["nodes"][name].get("cpulist", "")
        cpu = _first_cpu(cpulist)
        nodes.append({"node_id": node_id, "node_name": name,
                      "cpu": cpu, "cpulist": cpulist})
    nodes.sort(key=lambda n: n["node_id"])
    return nodes


def _first_cpu(cpulist):
    """First CPU id in a Linux cpulist string ("0-13,30" style)."""
    for part in (cpulist or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                return int(a)
            except ValueError:
                continue
        try:
            return int(part)
        except ValueError:
            continue
    return None


def _alloc(size, node):
    """Allocate+fault a buffer on `node` (numa_alloc_onnode). Returns
    (address:int, error:str|None)."""
    if node is None:
        return None, "no CPU/node selected for requested placement"
    lib = _numa()
    if lib.numa_available() < 0:
        return None, "NUMA not available on this host"
    ptr = lib.numa_alloc_onnode(size, node)
    if not ptr:
        return None, "numa_alloc_onnode(%d) returned NULL" % node
    # Fault pages in (write the whole range).
    ctypes.memset(ptr, 0, size)
    return ptr, None


def _free(ptr, size):
    if ptr:
        _numa().numa_free(ptr, size)


def _observed_placement(ptr, size):
    """Observed per-node page counts via move_pages (the existing
    observation mechanism; NOT a mbind()-success proxy).

    Returns {"pages_by_node": {...}, "error": None} or
    {"pages_by_node": None, "error": "..."} on failure.
    """
    if not ptr:
        return {"pages_by_node": None, "error": "no buffer address"}
    lib = _numa()
    npages = (size + 4095) // 4096
    if npages <= 0:
        return {"pages_by_node": {}, "error": None}
    page_arr = (ctypes.c_void_p * npages)()
    for i in range(npages):
        page_arr[i] = ptr + i * 4096
    status = (ctypes.c_int * npages)()
    rc = lib.move_pages(0, npages, page_arr, None, status, 0)
    if rc != 0:
        return {"pages_by_node": None, "error": "move_pages rc=%d" % rc}
    counts = {}
    for i in range(npages):
        node = status[i]
        if node is not None and node >= 0:
            key = "node%d" % node
        elif node is not None:
            key = "other_status_%d" % node
        else:
            key = "not_present"
        counts[key] = counts.get(key, 0) + 1
    return {"pages_by_node": counts, "error": None}


def _summ(times_ns, size):
    if not times_ns:
        return {"gbps": None, "duration_s": 0.0, "mean_s": None}
    secs = [t / 1e9 for t in times_ns]
    mean = statistics.mean(secs)
    gbps = (size / mean) / 1e9 if mean > 0 else None
    return {
        "gbps": gbps,
        "duration_s": sum(secs),
        "mean_s": mean,
        "min_s": min(secs),
        "max_s": max(secs),
        "stddev_s": (statistics.stdev(secs) if len(secs) > 1 else 0.0),
        "samples": len(secs),
    }


def _bench(dst_ptr, src_ptr, size, samples, warmup=3):
    """Sequential memmove dst<-src, samples times (the read/copy benchmark
    shape: reads src, writes dst). Returns _summ timing stats."""
    for _ in range(warmup):
        ctypes.memmove(dst_ptr, src_ptr, size)
    times = []
    for _ in range(samples):
        t0 = time.perf_counter_ns()
        ctypes.memmove(dst_ptr, src_ptr, size)
        times.append(time.perf_counter_ns() - t0)
    return _summ(times, size)


def _run_measurements(nodes, buffers, sink, buf2, size, n,
                      bench_fn, pin_fn, place_fn):
    """Run all local + remote read/copy benchmarks with per-measurement
    evidence (WO review: distinguish local vs remote buffer selection and
    exercise pinning/placement failures).

    bench_fn(dst_ptr, src_ptr, size, samples) -> timing stats (_bench).
    pin_fn(cpu) -> {"observed": [...]|None, "error": str|None}.
    place_fn(ptr, size) -> {"pages_by_node": {...}|None, "error": str|None}.

    Returns {measurement_name: {node/pair_key: result_dict}}, where each
    result has the _bench stats plus:
      - observed_cpu_affinity (list|None): the pinned affinity observed
        during this measurement (per-measurement evidence).
      - pin_error (str|None); invalid_pinning (bool).
      - placement: {label: {"pages_by_node": {...}|None, "error": str|None}}
        — verified placement of every buffer used by the measurement.
      - placement_error (str|None); invalid_placement (bool).
    """
    measurements = {}

    def _meas(dst_ptr, src_ptr, pin_result, placement_ptrs):
        res = dict(bench_fn(dst_ptr, src_ptr, size, n))
        pin_result = pin_result or {}
        res["observed_cpu_affinity"] = pin_result.get("observed")
        res["pin_error"] = pin_result.get("error")
        res["invalid_pinning"] = bool(res["pin_error"])
        placement = {}
        placement_error = None
        for label, ptr in placement_ptrs:
            placement[label] = place_fn(ptr, size)
            if placement[label].get("error"):
                placement_error = placement_error or placement[label]["error"]
        res["placement"] = placement
        res["placement_error"] = placement_error
        res["invalid_placement"] = bool(placement_error)
        return res

    # Local read + copy per node (pinned to the node).
    for nd in nodes:
        node = nd["node_id"]
        pin = pin_fn(nd["cpu"])
        b1, sk = buffers.get(node), sink.get(node)
        b2 = buf2.get(node)
        if b1 and sk:
            measurements.setdefault("read_local", {})[nd["node_name"]] = \
                _meas(sk, b1, pin, [("buffers", b1), ("sink", sk)])
        if b1 and b2:
            measurements.setdefault("copy_local", {})[nd["node_name"]] = \
                _meas(b2, b1, pin, [("buffers", b1), ("buf2", b2)])

    # Remote read + copy between node pairs (WO review: remote copy reads
    # A (local to the thread) and writes B's buffer; dst is on the pair
    # node B).
    for a in nodes:
        for b in nodes:
            if a["node_id"] == b["node_id"]:
                continue
            if not (buffers.get(a["node_id"]) and buffers.get(b["node_id"])
                    and sink.get(b["node_id"]) and buf2.get(b["node_id"])):
                continue
            key = "%s->%s" % (a["node_name"], b["node_name"])
            # read_remote[A->B]: thread pinned to B, read A's buffer into
            # B's sink (remote read from A observed while on B).
            measurements.setdefault("read_remote", {})[key] = \
                _meas(sink[b["node_id"]], buffers[a["node_id"]],
                      pin_fn(b["cpu"]),
                      [("buffers", buffers[a["node_id"]]),
                       ("sink", sink[b["node_id"]])])
            # copy_remote[A->B]: thread pinned to A, copy A's buffer into
            # B's buf2 (remote copy: dst on B is remote from thread A).
            measurements.setdefault("copy_remote", {})[key] = \
                _meas(buf2[b["node_id"]], buffers[a["node_id"]],
                      pin_fn(a["cpu"]),
                      [("buffers", buffers[a["node_id"]]),
                       ("buf2", buf2[b["node_id"]])])
    return measurements


def _pin(cpu):
    """Pin the thread to `cpu`; return evidence.

    Returns {"observed": [cpu...], "error": None} when the pin succeeded, or
    {"observed": None, "error": "..."} on failure. Evidence is recorded
    per measurement (WO review: affinity evidence per result, failures
    marked invalid).
    """
    if cpu is None:
        return {"observed": None, "error": "no CPU selected for requested placement"}
    try:
        os.sched_setaffinity(0, {cpu})
        observed = sorted(os.sched_getaffinity(0))
        if cpu not in observed:
            return {"observed": observed,
                    "error": "sched_setaffinity(%s) did not take effect (observed %s)"
                             % (cpu, observed)}
        return {"observed": observed, "error": None}
    except OSError as exc:
        return {"observed": None, "error": "pin error: %s" % exc}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True,
                    help="output JSON path")
    ap.add_argument("--samples", type=int, default=3,
                    help="benchmark samples per measurement")
    ap.add_argument("--size-mb", type=int, default=32,
                    help="benchmark buffer size in MiB")
    args = ap.parse_args()

    nodes = _nodes_and_cpus()
    size = args.size_mb * (1 << 20)
    n = args.samples

    requested_affinity = sorted(os.sched_getaffinity(0))

    # Allocate buffers per node (explicit placement):
    #   buffers[N] - read source, sink[N] - read destination,
    #   buf2[N]    - copy destination.
    buffers, sink, buf2 = {}, {}, {}
    errors = {}
    for nd in nodes:
        for store in (buffers, sink, buf2):
            ptr, err = _alloc(size, nd["node_id"])
            if ptr is None:
                errors.setdefault(nd["node_name"], []).append(
                    "buffer alloc: %s" % err)
            store[nd["node_id"]] = ptr

    _u = os.uname()
    report = {
        "schema": "stage0-numa-calibrate",
        "host": {
            "uname": {"sysname": _u.sysname, "nodename": _u.nodename,
                      "release": _u.release, "version": _u.version,
                      "machine": _u.machine},
            "topology_nodes": [nd["node_name"] for nd in nodes],
        },
        "requested": {
            "cpu_affinity": requested_affinity,
            "buffer_size_bytes": size,
            "samples": n,
        },
        "measurements": {},
        "observed": {
            "cpu_affinity_during_pinned": None,
            "memory_placement": {},
        },
        "errors": errors,
        "note": "Diagnostic context only; not included in dist-ingest candidate throughput statistics.",
    }

    # Run all measurements with per-measurement evidence:
    #   observed_cpu_affinity (list|None), pin_error, invalid_pinning,
    #   placement (verified per buffer), invalid_placement.
    report["measurements"] = _run_measurements(
        nodes, buffers, sink, buf2, size, n,
        bench_fn=_bench, pin_fn=_pin, place_fn=_observed_placement)

    # Observed placement: move_pages-verified per buffer.
    for node in nodes:
        if buffers.get(node["node_id"]):
            report["observed"]["memory_placement"][node["node_name"]] = \
                _observed_placement(buffers[node["node_id"]], size)

    # Requested placement (explicit, via numa_alloc_onnode).
    report["requested_memory_placement"] = {
        nd["node_name"]: "numa_alloc_onnode(%d)" % nd["node_id"] for nd in nodes}

    # Restore affinity.
    try:
        os.sched_setaffinity(0, set(requested_affinity))
    except OSError:
        pass

    for ptr in list(buffers.values()) + list(buf2.values()) + list(sink.values()):
        _free(ptr, size)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
