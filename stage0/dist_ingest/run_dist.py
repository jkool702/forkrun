#!/usr/bin/env python3
"""Run experimental distributed-ingestion candidates and emit metrics.

This is the isolated harness for WO-NUMA-DISTRIBUTED-INGEST-PROTOTYPE-SUITE-1.
It runs one candidate over a regular file (file-first; pipe experimental
support is separate/deferred) and prints:
  - STAGE0_DIAG/STAGE0_FINAL-compatible queue/backlog summary lines (best-effort)
  - DIST_RESULT <json> with full metrics/provenance
  - CHILD_DONE <json> compatible with stage0/run_case.py

It does NOT modify or depend on the frozen production ring engine.
"""

import argparse
import ctypes
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
LIB_PATH = os.path.join(os.path.dirname(HERE), "libdist_ingest.so")

DI_MAX_NODES = 64

DI_POLICY_FIXED_FAA = 1
DI_POLICY_LOCAL_ADAPTIVE = 2
DI_POLICY_RELATIVE_ADAPTIVE = 3

POLICY_MAP = {
    "fixed_faa": DI_POLICY_FIXED_FAA,
    "local_adaptive": DI_POLICY_LOCAL_ADAPTIVE,
    "relative_adaptive": DI_POLICY_RELATIVE_ADAPTIVE,
}

CONSUMER_MODE = {
    "equal": 0,
    "slow": 1,
    "fast": 2,
    "stall": 3,
}


class DiPolicyParams(ctypes.Structure):
    _fields_ = [
        ("base_quantum", ctypes.c_uint64),
        ("max_reservation", ctypes.c_uint64),
        ("max_backlog", ctypes.c_uint64),
        ("rel_min_claim", ctypes.c_uint64),
        ("rel_max_claim_quanta", ctypes.c_uint64),
        ("relative_rounding", ctypes.c_int),
        ("local_max_claim_quanta", ctypes.c_uint64),
        ("align_reservations", ctypes.c_int),
        ("prefer_hugepage", ctypes.c_int),
        ("strict_affinity", ctypes.c_int),
        ("strict_mbind", ctypes.c_int),
        ("one_outstanding_per_node", ctypes.c_int),
        ("enable_peer_headroom", ctypes.c_int),
    ]


class DiConsumerCfg(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("bytes_per_sec", ctypes.c_uint64),
        ("stall_ms", ctypes.c_uint64),
    ]


class DiNodeMetrics(ctypes.Structure):
    _fields_ = [
        ("reservations", ctypes.c_uint64),
        ("bytes_reserved_req", ctypes.c_uint64),
        ("bytes_assigned", ctypes.c_uint64),
        ("bytes_read", ctypes.c_uint64),
        ("bytes_published", ctypes.c_uint64),
        ("bytes_consumed", ctypes.c_uint64),
        ("chunks_published", ctypes.c_uint64),
        ("chunks_consumed", ctypes.c_uint64),
        ("zero_claims", ctypes.c_uint64),
        ("claim_wait_ns", ctypes.c_uint64),
        ("read_wait_ns", ctypes.c_uint64),
        ("publish_wait_ns", ctypes.c_uint64),
        ("consume_wait_ns", ctypes.c_uint64),
        ("current_published_backlog", ctypes.c_uint64),
        ("current_consumer_inflight_backlog", ctypes.c_uint64),
        ("current_outstanding", ctypes.c_uint64),
        ("current_effective_backlog", ctypes.c_uint64),
        ("max_published_backlog", ctypes.c_uint64),
        ("max_consumer_inflight_backlog", ctypes.c_uint64),
        ("max_effective_backlog", ctypes.c_uint64),
        ("peer_observe_ns", ctypes.c_uint64),
        ("peer_observe_count", ctypes.c_uint64),
        ("placement_samples", ctypes.c_uint64),
        ("placement_sample_cap", ctypes.c_uint64),
        ("local_pages", ctypes.c_uint64),
        ("remote_pages", ctypes.c_uint64),
        ("unknown_pages", ctypes.c_uint64),
        ("hugepage_map_requested_bytes", ctypes.c_uint64),
        ("hugepage_map_obtained_bytes", ctypes.c_uint64),
        ("hugepage_fallback_bytes", ctypes.c_uint64),
        ("hugepage_observed_kb", ctypes.c_uint64),
        ("alloc_bytes", ctypes.c_uint64),
        ("ingest_cpu_ns", ctypes.c_uint64),
        ("consumer_cpu_ns", ctypes.c_uint64),
        ("res_hist", ctypes.c_uint64 * 20),
        ("affinity_requested", ctypes.c_int),
        ("affinity_applied", ctypes.c_int),
        ("affinity_verified", ctypes.c_int),
        ("affinity_error", ctypes.c_int),
        ("mbind_requested", ctypes.c_int),
        ("mbind_applied", ctypes.c_int),
        ("mbind_error", ctypes.c_int),
        ("placement_strict_failed", ctypes.c_int),
        ("last_error", ctypes.c_int),
    ]


class DiResult(ctypes.Structure):
    _fields_ = [
        ("total_bytes", ctypes.c_uint64),
        ("total_reserved_req", ctypes.c_uint64),
        ("total_assigned", ctypes.c_uint64),
        ("total_read", ctypes.c_uint64),
        ("total_published", ctypes.c_uint64),
        ("total_consumed", ctypes.c_uint64),
        ("reservations_total", ctypes.c_uint64),
        ("eof_offset", ctypes.c_uint64),
        ("overlap_detected", ctypes.c_int),
        ("duplicate_detected", ctypes.c_int),
        ("lost_detected", ctypes.c_int),
        ("input_changed", ctypes.c_int),
        ("wall_seconds", ctypes.c_double),
        ("ingest_cpu_ns", ctypes.c_uint64),
        ("consumer_cpu_ns", ctypes.c_uint64),
        ("num_nodes", ctypes.c_int),
        ("policy", ctypes.c_int),
        ("nodes", DiNodeMetrics * DI_MAX_NODES),
        ("res_hist", ctypes.c_uint64 * 20),
    ]


class DiConfig(ctypes.Structure):
    _fields_ = [
        ("num_nodes", ctypes.c_int),
        ("policy", ctypes.c_int),
        ("params", DiPolicyParams),
        ("consumers", ctypes.POINTER(DiConsumerCfg)),
        ("cpu_lists", ctypes.c_void_p),
        ("cpu_counts", ctypes.c_void_p),
        ("phys_nodes", ctypes.c_void_p),
    ]


def load_lib():
    if not os.path.isfile(LIB_PATH):
        raise SystemExit("dist-ingest library missing: %s (build stage0/dist_ingest)" % LIB_PATH)
    lib = ctypes.CDLL(LIB_PATH)
    lib.di_create.argtypes = [ctypes.c_int, ctypes.c_uint64, ctypes.POINTER(DiConfig)]
    lib.di_create.restype = ctypes.c_void_p
    lib.di_destroy.argtypes = [ctypes.c_void_p]
    lib.di_destroy.restype = None
    lib.di_run.argtypes = [ctypes.c_void_p, ctypes.POINTER(DiResult)]
    lib.di_run.restype = ctypes.c_int
    return lib


def node_metrics_to_dict(m, idx):
    return {
        "node": idx,
        "reservations": m.reservations,
        "bytes_reserved_req": m.bytes_reserved_req,
        "bytes_assigned": m.bytes_assigned,
        "bytes_read": m.bytes_read,
        "bytes_published": m.bytes_published,
        "bytes_consumed": m.bytes_consumed,
        "chunks_published": m.chunks_published,
        "chunks_consumed": m.chunks_consumed,
        "zero_claims": m.zero_claims,
        "claim_wait_ns": m.claim_wait_ns,
        "read_wait_ns": m.read_wait_ns,
        "publish_wait_ns": m.publish_wait_ns,
        "consume_wait_ns": m.consume_wait_ns,
        "current_published_backlog": m.current_published_backlog,
        "current_consumer_inflight_backlog": m.current_consumer_inflight_backlog,
        "current_outstanding": m.current_outstanding,
        "current_effective_backlog": m.current_effective_backlog,
        "max_published_backlog": m.max_published_backlog,
        "max_consumer_inflight_backlog": m.max_consumer_inflight_backlog,
        "max_effective_backlog": m.max_effective_backlog,
        "peer_observe_ns": m.peer_observe_ns,
        "peer_observe_count": m.peer_observe_count,
        "placement_samples": m.placement_samples,
        "placement_sample_cap": m.placement_sample_cap,
        "local_pages": m.local_pages,
        "remote_pages": m.remote_pages,
        "unknown_pages": m.unknown_pages,
        "hugepage_map_requested_bytes": m.hugepage_map_requested_bytes,
        "hugepage_map_obtained_bytes": m.hugepage_map_obtained_bytes,
        "hugepage_fallback_bytes": m.hugepage_fallback_bytes,
        "hugepage_observed_kb": m.hugepage_observed_kb,
        "alloc_bytes": m.alloc_bytes,
        "ingest_cpu_ns": m.ingest_cpu_ns,
        "consumer_cpu_ns": m.consumer_cpu_ns,
        "res_hist": list(m.res_hist),
        "affinity_requested": m.affinity_requested,
        "affinity_applied": m.affinity_applied,
        "affinity_verified": m.affinity_verified,
        "affinity_error": m.affinity_error,
        "mbind_requested": m.mbind_requested,
        "mbind_applied": m.mbind_applied,
        "mbind_error": m.mbind_error,
        "placement_strict_failed": m.placement_strict_failed,
        "last_error": m.last_error,
    }


def emit_stage0_lines(res, policy_name):
    # Best-effort telemetry in STAGE0_* form so existing parsers can pick up
    # queue/backlog presence. These are experimental-ingest measurements, not
    # ring engine internals.
    t_ms = int(res.wall_seconds * 1000)
    total_cpu = res.ingest_cpu_ns
    q_parts = []
    b_parts = []
    for i in range(res.num_nodes):
        nm = res.nodes[i]
        # q: published chunks, consumed chunks (ingest->queue proxy)
        q_parts.append("n%d:%d,%d" % (i, nm.chunks_published, nm.chunks_consumed))
        # b: outstanding/published backlog bytes snapshot
        b_parts.append("n%d:%d,%d" % (i, nm.current_outstanding, nm.current_published_backlog))
    line = ("STAGE0_FINAL src=dist-ingest t_ms=%d t_us=%d moved=%d major=0 tgt=%d "
            "lim=0 gated_ms=0 cpu_ns=%d q=%s b=%s policy=%s"
            % (t_ms, int(res.wall_seconds * 1e6), res.total_consumed, res.num_nodes - 1,
               total_cpu, ";".join(q_parts), ";".join(b_parts), policy_name))
    print(line, file=sys.stderr)
    # A synthetic DIAG line to satisfy queue_present heuristics when needed.
    print(line.replace("STAGE0_FINAL", "STAGE0_DIAG", 1), file=sys.stderr)


def _parse_id_list(raw):
    out = []
    for part in (raw or "").strip().split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                start, end = int(a), int(b)
            except ValueError:
                continue
            if end >= start:
                out.extend(range(start, end + 1))
        else:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return out


def _read_first(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _allowed_cpus():
    # Respect actual process allowed CPU set (cpuset/cgroup/sched affinity).
    try:
        return sorted(os.sched_getaffinity(0))
    except Exception:
        pass
    raw = _read_first("/proc/self/status") or ""
    for line in raw.splitlines():
        if line.startswith("Cpus_allowed_list:"):
            return _parse_id_list(line.split(":", 1)[1])
    return []


def _allowed_mems():
    raw = _read_first("/proc/self/status") or ""
    for line in raw.splitlines():
        if line.startswith("Mems_allowed_list:"):
            return _parse_id_list(line.split(":", 1)[1])
    return []


def _online_nodes():
    raw = _read_first("/sys/devices/system/node/online")
    if raw is None:
        return [0]
    nodes = _parse_id_list(raw)
    return nodes or [0]


def _node_cpus(node_id):
    raw = _read_first("/sys/devices/system/node/node%d/cpulist" % node_id)
    return _parse_id_list(raw) if raw is not None else []


def _node_has_memory(node_id):
    mi = _read_first("/sys/devices/system/node/node%d/meminfo" % node_id)
    if mi is None:
        return False
    for line in mi.splitlines():
        if line.startswith("Node %d MemTotal:" % node_id):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    return int(parts[3]) > 0
                except ValueError:
                    return False
    # if meminfo exists but format unexpected, be conservative
    return True


def resolve_topology(requested_nodes, phys_nodes_spec=None):
    """Return (logical_to_phys, per_node_cpus, topology_info, errors).

    logical_to_phys: list[int] length requested_nodes (or fewer impossible -> errors)
    per_node_cpus: list[list[int]] filtered to allowed CPUs
    """
    errors = []
    allowed_cpus = set(_allowed_cpus())
    allowed_mems = set(_allowed_mems())
    online = _online_nodes()
    # usable physical nodes: online, in allowed mems (if known), have memory
    usable = []
    for nid in online:
        if allowed_mems and nid not in allowed_mems:
            continue
        if not _node_has_memory(nid):
            continue
        # need at least one allowed CPU on node for affinity/pinning usefulness
        cpus = [c for c in _node_cpus(nid) if (not allowed_cpus or c in allowed_cpus)]
        if not cpus:
            continue
        usable.append((nid, cpus))

    if phys_nodes_spec:
        # explicit physical node list in order
        try:
            explicit = [int(x) for x in phys_nodes_spec.split(",") if x.strip() != ""]
        except ValueError:
            return [], [], {}, ["invalid --phys-nodes: %r" % (phys_nodes_spec,)]
        phys_to_cpus = {nid: cpus for nid, cpus in usable}
        logical_to_phys = []
        per_node_cpus = []
        for nid in explicit:
            if nid not in phys_to_cpus:
                errors.append("physical node %d not usable (online/allowed/memory/cpu)" % nid)
                continue
            logical_to_phys.append(nid)
            per_node_cpus.append(phys_to_cpus[nid])
        if errors:
            return [], [], {"requested_nodes": requested_nodes, "online": online,
                            "allowed_cpus": sorted(allowed_cpus), "allowed_mems": sorted(allowed_mems),
                            "usable": usable, "explicit": explicit}, errors
        # if requested_nodes differs, honor explicit list length but must be >=1
        if requested_nodes and requested_nodes != len(logical_to_phys):
            errors.append("requested --nodes %d but --phys-nodes selects %d node(s)" % (requested_nodes, len(logical_to_phys)))
            return [], [], {"requested_nodes": requested_nodes, "explicit": explicit}, errors
        info = {"mode": "explicit", "online": online, "allowed_cpus_count": len(allowed_cpus),
                "allowed_mems": sorted(allowed_mems), "usable_nodes": [n for n,_ in usable],
                "logical_to_physical": logical_to_phys}
        return logical_to_phys, per_node_cpus, info, []

    # automatic selection of usable nodes
    n = max(1, requested_nodes)
    if len(usable) < n:
        return [], [], {"requested_nodes": n, "online": online, "allowed_cpus_count": len(allowed_cpus),
                        "allowed_mems": sorted(allowed_mems), "usable_nodes": [nid for nid,_ in usable]}, [
            "insufficient usable NUMA nodes: requested %d, have %d usable (%s)" % (n, len(usable), [nid for nid,_ in usable])
        ]
    picked = usable[:n]
    logical_to_phys = [nid for nid, _ in picked]
    per_node_cpus = [cpus for _, cpus in picked]
    info = {"mode": "auto", "online": online, "allowed_cpus_count": len(allowed_cpus),
            "allowed_mems": sorted(allowed_mems), "usable_nodes": [nid for nid,_ in usable],
            "logical_to_physical": logical_to_phys}
    return logical_to_phys, per_node_cpus, info, []


def build_ctypes_topology(logical_to_phys, per_node_cpus):
    """Return (phys_nodes_arr, cpu_counts_arr, cpu_list_arrays, cpu_list_ptrs, keepalive) lifetime-safe."""
    n = len(logical_to_phys)
    PhysArr = ctypes.c_int * n
    phys_nodes_arr = PhysArr(*[int(x) for x in logical_to_phys])
    CountsArr = ctypes.c_int * n
    cpu_counts_arr = CountsArr(*[len(c) for c in per_node_cpus])
    cpu_list_arrays = []
    for cpus in per_node_cpus:
        A = ctypes.c_int * (len(cpus) if cpus else 1)
        if cpus:
            cpu_list_arrays.append(A(*[int(c) for c in cpus]))
        else:
            cpu_list_arrays.append(A(0))
    PtrArr = ctypes.POINTER(ctypes.c_int) * n
    cpu_list_ptrs = PtrArr(*[ctypes.cast(a, ctypes.POINTER(ctypes.c_int)) for a in cpu_list_arrays])
    keepalive = (phys_nodes_arr, cpu_counts_arr, cpu_list_arrays, cpu_list_ptrs)
    return phys_nodes_arr, cpu_counts_arr, cpu_list_ptrs, keepalive


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", default="fixed_faa",
                    choices=sorted(POLICY_MAP.keys()),
                    help="distributed ingestion policy")
    ap.add_argument("--input", required=True)
    ap.add_argument("--nodes", type=int, default=2)
    ap.add_argument("--phys-nodes", default=None,
                    help="explicit physical NUMA node ids, comma-separated (logical order)")
    ap.add_argument("--base-quantum", type=int, default=2 * 1024 * 1024)
    ap.add_argument("--max-backlog", type=int, default=64 * 1024 * 1024)
    ap.add_argument("--max-reservation", type=int, default=0)
    ap.add_argument("--relative-rounding", type=int, default=1, choices=[0, 1, 2])
    ap.add_argument("--local-max-claim-quanta", type=int, default=0)
    ap.add_argument("--rel-min-claim", type=int, default=0)
    ap.add_argument("--rel-max-claim-quanta", type=int, default=0)
    ap.add_argument("--prefer-hugepage", action="store_true")
    ap.add_argument("--no-align", action="store_true")
    ap.add_argument("--strict-affinity", action="store_true")
    ap.add_argument("--strict-mbind", action="store_true")
    ap.add_argument("--no-pin", action="store_true",
                    help="intentionally unpinned run (do not pass cpu lists)")
    ap.add_argument("--consumer-mode", default="fast",
                    choices=sorted(CONSUMER_MODE.keys()))
    ap.add_argument("--consumer-bps", type=int, default=0)
    ap.add_argument("--consumer-stall-ms", type=int, default=0)
    ap.add_argument("--slow-node", type=int, default=-1,
                    help="node index to make slow/stalled for scenarios")
    ap.add_argument("--slow-mode", default=None, choices=sorted(CONSUMER_MODE.keys()))
    ap.add_argument("--slow-bps", type=int, default=0)
    ap.add_argument("--slow-stall-ms", type=int, default=0)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    path = args.input
    if not os.path.isabs(path):
        path = os.path.join(REPO, path)
    st = os.stat(path)
    fd = os.open(path, os.O_RDONLY)

    lib = load_lib()
    policy = POLICY_MAP[args.candidate]

    # Topology resolution and wiring (S1 corrective).
    logical_to_phys, per_node_cpus, topo_info, topo_errors = resolve_topology(args.nodes, args.phys_nodes)
    if topo_errors:
        os.close(fd)
        raise SystemExit("topology resolution failed: " + "; ".join(topo_errors))
    n = len(logical_to_phys)
    if n < 1 or n > DI_MAX_NODES:
        os.close(fd)
        raise SystemExit("invalid resolved node count %d" % n)

    params = DiPolicyParams()
    params.base_quantum = args.base_quantum
    params.max_reservation = args.max_reservation
    params.max_backlog = args.max_backlog
    params.rel_min_claim = args.rel_min_claim
    params.rel_max_claim_quanta = args.rel_max_claim_quanta
    params.relative_rounding = args.relative_rounding
    params.local_max_claim_quanta = args.local_max_claim_quanta
    params.align_reservations = 0 if args.no_align else 1
    params.prefer_hugepage = 1 if args.prefer_hugepage else 0
    params.strict_affinity = 1 if args.strict_affinity else 0
    params.strict_mbind = 1 if args.strict_mbind else 0
    params.one_outstanding_per_node = 1
    params.enable_peer_headroom = 1

    cons_arr = (DiConsumerCfg * n)()
    for i in range(n):
        cons_arr[i].mode = CONSUMER_MODE[args.consumer_mode]
        cons_arr[i].bytes_per_sec = args.consumer_bps
        cons_arr[i].stall_ms = args.consumer_stall_ms
    if 0 <= args.slow_node < n and args.slow_mode:
        cons_arr[args.slow_node].mode = CONSUMER_MODE[args.slow_mode]
        cons_arr[args.slow_node].bytes_per_sec = args.slow_bps
        cons_arr[args.slow_node].stall_ms = args.slow_stall_ms

    topo_keepalive = None
    cfg = DiConfig()
    cfg.num_nodes = n
    cfg.policy = policy
    cfg.params = params
    cfg.consumers = ctypes.cast(cons_arr, ctypes.POINTER(DiConsumerCfg))
    # lifetime-safe topology wiring
    phys_arr, counts_arr, cpu_ptrs, topo_keepalive = build_ctypes_topology(logical_to_phys, per_node_cpus)
    cfg.phys_nodes = ctypes.cast(phys_arr, ctypes.c_void_p)
    if args.no_pin:
        cfg.cpu_lists = None
        cfg.cpu_counts = None
    else:
        cfg.cpu_counts = ctypes.cast(counts_arr, ctypes.c_void_p)
        cfg.cpu_lists = ctypes.cast(cpu_ptrs, ctypes.c_void_p)

    eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
    if not eng:
        os.close(fd)
        raise SystemExit("di_create failed")

    res = DiResult()
    t0 = time.monotonic()
    rc = lib.di_run(eng, ctypes.byref(res))
    elapsed = time.monotonic() - t0
    lib.di_destroy(eng)
    os.close(fd)

    if rc != 0:
        print("DIST_ERROR rc=%d" % rc, file=sys.stderr)

    emit_stage0_lines(res, args.candidate)

    # validity signals (S1/S6 groundwork)
    affinity_ok = True
    placement_ok = True
    for i in range(res.num_nodes):
        nm = res.nodes[i]
        if args.strict_affinity and (not nm.affinity_verified or nm.placement_strict_failed):
            affinity_ok = False
        if args.strict_mbind and (nm.mbind_requested and not nm.mbind_applied or nm.placement_strict_failed):
            placement_ok = False
        if nm.placement_strict_failed:
            placement_ok = False
    out = {
        "candidate": args.candidate,
        "policy": res.policy,
        "num_nodes": res.num_nodes,
        "input": args.input,
        "file_size": st.st_size,
        "rc": rc,
        "wall_seconds": res.wall_seconds,
        "elapsed_s": elapsed,
        "total_reserved_req": res.total_reserved_req,
        "total_assigned": res.total_assigned,
        "total_read": res.total_read,
        "total_published": res.total_published,
        "total_consumed": res.total_consumed,
        "reservations_total": res.reservations_total,
        "overlap_detected": bool(res.overlap_detected),
        "duplicate_detected": bool(res.duplicate_detected),
        "lost_detected": bool(res.lost_detected),
        "input_changed": bool(res.input_changed),
        "ingest_cpu_ns": res.ingest_cpu_ns,
        "consumer_cpu_ns": res.consumer_cpu_ns,
        "res_hist": list(res.res_hist),
        "nodes": [node_metrics_to_dict(res.nodes[i], i) for i in range(res.num_nodes)],
        "topology": {
            **topo_info,
            "requested_nodes_arg": args.nodes,
            "phys_nodes_arg": args.phys_nodes,
            "pinning": "disabled" if args.no_pin else "requested",
            "strict_affinity": bool(args.strict_affinity),
            "strict_mbind": bool(args.strict_mbind),
            "per_node_cpus": per_node_cpus,
        },
        "validity": {
            "functional_correct": (rc == 0 and not res.overlap_detected and not res.duplicate_detected and not res.lost_detected
                                   and not res.input_changed and res.total_consumed == st.st_size),
            "affinity_valid": affinity_ok,
            "placement_valid": placement_ok,
        },
        "correct": (rc == 0 and not res.overlap_detected and not res.duplicate_detected and not res.lost_detected
                    and not res.input_changed and res.total_consumed == st.st_size),
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
    print("DIST_RESULT " + json.dumps(out, sort_keys=True), file=sys.stderr)
    # CHILD_DONE for stage0/run_case.py compatibility (treat consumed bytes as output/records proxy)
    child = {
        "elapsed_s": res.wall_seconds if res.wall_seconds > 0 else elapsed,
        "completed_bytes": res.total_consumed,
        "completed_records": res.total_consumed,  # byte-stream proxy
        "rec_per_s": (res.total_consumed / res.wall_seconds) if res.wall_seconds > 0 else 0,
        "completed_output_bytes_per_s": (res.total_consumed / res.wall_seconds) if res.wall_seconds > 0 else 0,
    }
    print("CHILD_DONE " + json.dumps(child))
    return 0 if out["correct"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
