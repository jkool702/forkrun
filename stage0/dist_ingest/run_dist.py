#!/usr/bin/env python3
"""Run experimental distributed-ingestion candidates and emit metrics.

Isolated harness for dist-ingest prototype. Does NOT modify frozen production
ring engine. Addendum A: per-role affinity, separated mbind policy vs observed
placement, topology uncertainty/duplicate-node validation, explicit provenance.
"""

import argparse
import ctypes
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
LIB_PATH = os.path.join(os.path.dirname(HERE), "libdist_ingest.so")


def _file_sha256(path):
    """Authoritative binary hash (master WO 7.3: the exact binary used by
    every dist trial)."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


LIBDIST_INGEST_SHA256 = _file_sha256(LIB_PATH)

DI_MAX_NODES = 64

DI_POLICY_FIXED_FAA = 1
DI_POLICY_LOCAL_ADAPTIVE = 2
DI_POLICY_RELATIVE_ADAPTIVE = 3
DI_POLICY_CENTRALIZED_INGEST = 4

POLICY_MAP = {
    "fixed_faa": DI_POLICY_FIXED_FAA,
    "local_adaptive": DI_POLICY_LOCAL_ADAPTIVE,
    "relative_adaptive": DI_POLICY_RELATIVE_ADAPTIVE,
    # Section 5: in-engine centralized control baseline (same engine/consumers/
    # work units/measurement boundaries as distributed candidates).
    "centralized_ingest": DI_POLICY_CENTRALIZED_INGEST,
    "centralized": DI_POLICY_CENTRALIZED_INGEST,
}

CONSUMER_MODE = {
    "equal": 0,
    "slow": 1,
    "fast": 2,
    "stall": 3,
}

# §5.2: per-node ingestor workload control modes (mirror of dist_ingest.h).
INGESTOR_MODE = {
    "off": 0,
    "delay_per_claim": 1,
    "delay_after_read": 2,
    "stall_then_recover": 3,
    "rate_limit": 4,
}
INGESTOR_PHASE = {
    0: "off",
    1: "delay_per_claim",
    2: "delay_after_read_before_publish",
    3: "stall_then_recover",
    4: "rate_limit",
}
# §2: placement sampling modes: off=performance-isolated, on=bounded
# (in-run move_pages sampling for placement-validation), full=exhaustive.
PLACEMENT_SAMPLING_MODE = {"off": 0, "on": 1, "full": 2}


def _per_node_list(spec, n, name_map=None):
    """Parse a comma list of per-node values. Fail-closed: malformed specs,
    unknown mode names (with name_map), or excess/negative entries raise
    ValueError instead of silently defaulting to zero."""
    if n is None or n < 0:
        raise ValueError("bad node count for per-node list: %r" % (n,))
    parts = []
    if spec is None or str(spec).strip() == "":
        parts = []
    else:
        s = str(spec).strip()
        parts = [p.strip() for p in s.split(",")]
    out = []
    for i in range(n):
        s = parts[i] if i < len(parts) else ""
        if s in ("", "-", "None"):
            out.append(0)
            continue
        if name_map is not None:
            if s not in name_map:
                raise ValueError("unknown name %r in per-node list" % (s,))
            v = name_map[s]
        else:
            try:
                v = int(s)
            except ValueError:
                raise ValueError("malformed integer %r in per-node list" % (s,))
            if v < 0:
                raise ValueError("negative value %r in per-node list" % (s,))
        out.append(v)
    nonempty = [p for p in parts if p not in ("", "-")]
    if len(nonempty) > n:
        raise ValueError("per-node list has %d entries but only %d nodes" % (len(nonempty), n))
    return out


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
        ("consumer_kernel", ctypes.c_int),
        ("placement_sampling", ctypes.c_int),
    ]


class DiConsumerCfg(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("bytes_per_sec", ctypes.c_uint64),
        ("stall_ms", ctypes.c_uint64),
    ]


class DiIngestorCfg(ctypes.Structure):
    """§5.2: per-node ingestor workload controls (mirror of dist_ingest.h
    di_ingestor_cfg_t)."""
    _fields_ = [
        ("mode", ctypes.c_int),          # 0=off,1=delay_per_claim,2=delay_after_read,3=stall_then_recover,4=rate_limit
        ("delay_ns", ctypes.c_uint64),
        ("stall_ms", ctypes.c_uint64),
        ("rate_bps", ctypes.c_uint64),
    ]


class DiAffinityRole(ctypes.Structure):
    _fields_ = [
        ("requested", ctypes.c_int),
        ("set_applied", ctypes.c_int),
        ("query_succeeded", ctypes.c_int),
        ("matched", ctypes.c_int),
        ("error", ctypes.c_int),
        ("strict_failed", ctypes.c_int),
    ]


class DiNodeMetrics(ctypes.Structure):
    _fields_ = [
        ("reservations", ctypes.c_uint64),
        ("bytes_reserved_req", ctypes.c_uint64),
        ("bytes_assigned", ctypes.c_uint64),
        ("bytes_read", ctypes.c_uint64),
        ("bytes_published", ctypes.c_uint64),
        ("bytes_consumed", ctypes.c_uint64),
        ("consumer_bytes_scanned", ctypes.c_uint64),
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
        ("placement_total_addressable_pages", ctypes.c_uint64),
        ("placement_sampled_pages", ctypes.c_uint64),
        ("placement_sample_limit", ctypes.c_uint64),
        ("placement_sample_spacing", ctypes.c_uint64),
        ("placement_sample_target_match_pages", ctypes.c_uint64),
        ("placement_sample_other_node_pages", ctypes.c_uint64),
        ("placement_sample_unknown_pages", ctypes.c_uint64),
        ("placement_sampling_unavailable", ctypes.c_int),
        ("placement_sampling_not_performed", ctypes.c_int),
        ("hugepage_map_requested_bytes", ctypes.c_uint64),
        ("hugepage_map_obtained_bytes", ctypes.c_uint64),
        ("hugepage_fallback_bytes", ctypes.c_uint64),
        ("hugepage_observed_kb", ctypes.c_uint64),
        ("alloc_bytes", ctypes.c_uint64),
        ("ingest_cpu_ns", ctypes.c_uint64),
        ("consumer_cpu_ns", ctypes.c_uint64),
        ("res_hist", ctypes.c_uint64 * 20),
        ("affinity_ingestor", DiAffinityRole),
        ("affinity_consumer", DiAffinityRole),
        # §5.2: ingestor workload control evidence (observed, per node).
        ("ingestor_mode", ctypes.c_int),
        ("ingestor_delay_ns", ctypes.c_uint64),
        ("ingestor_stall_fired", ctypes.c_uint64),
        ("ingestor_rate_throttled_ns", ctypes.c_uint64),
        ("mbind_policy_requested", ctypes.c_int),
        ("mbind_policy_applied", ctypes.c_int),
        ("mbind_error", ctypes.c_int),
        ("mbind_requested_count", ctypes.c_uint64),
        ("mbind_success_count", ctypes.c_uint64),
        ("mbind_failure_count", ctypes.c_uint64),
        ("strict_mbind_failed", ctypes.c_int),
        ("strict_affinity_failed", ctypes.c_int),
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
        ("total_consumer_bytes_scanned", ctypes.c_uint64),
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
        ("ingestors", ctypes.POINTER(DiIngestorCfg)),
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


def affinity_role_to_dict(r):
    return {
        "requested": bool(r.requested),
        "set_applied": bool(r.set_applied),
        "query_succeeded": bool(r.query_succeeded),
        "matched": bool(r.matched),
        "error": int(r.error),
        "strict_failed": bool(r.strict_failed),
    }


def node_metrics_to_dict(m, idx, requested_phys_node=None, policy=None):
    # placement_sample_all_matched is a narrow summary: all sampled pages observed on
    # preferred/target node. It does NOT imply every page in allocation was examined and
    # does NOT imply mbind syscall success/failure by itself.
    sampled = int(m.placement_sampled_pages)
    total_pages = int(m.placement_total_addressable_pages)
    limit = int(m.placement_sample_limit)
    all_sampled_match = (
        sampled > 0 and
        int(m.placement_sample_target_match_pages) == sampled and
        int(m.placement_sample_other_node_pages) == 0 and
        int(m.placement_sample_unknown_pages) == 0
    )
    sampling_complete = bool(sampled > 0 and total_pages > 0 and sampled >= total_pages)
    sampling_partial = bool(sampled > 0 and total_pages > sampled)

    mbind_req_c = int(getattr(m, "mbind_requested_count", 0))
    mbind_suc_c = int(getattr(m, "mbind_success_count", 0))
    mbind_fail_c = int(getattr(m, "mbind_failure_count", 0))
    mbind_requested = bool(m.mbind_policy_requested) or mbind_req_c > 0
    # compatibility: all requested operations succeeded (and >=1 requested)
    mbind_all_ok = bool(mbind_requested and mbind_fail_c == 0 and (mbind_suc_c > 0 or bool(m.mbind_policy_applied)))

    # Role applicability by actual topology/architecture (not by thread existence alone).
    # centralized_ingest: single ingestor on central node (node 0) + all consumers.
    # distributed: ingestor+consumer per configured logical node.
    ingestor_required = True
    if policy == DI_POLICY_CENTRALIZED_INGEST:
        ingestor_required = (idx == 0)
    consumer_required = True

    ing = affinity_role_to_dict(m.affinity_ingestor)
    con = affinity_role_to_dict(m.affinity_consumer)
    ing["required"] = bool(ingestor_required)
    ing["applicable"] = bool(ingestor_required)
    con["required"] = bool(consumer_required)
    con["applicable"] = bool(consumer_required)

    def _role_verified(rdict, required):
        if not required:
            return None  # N/A
        if not rdict["requested"]:
            return None  # not requested => cannot be established/verified
        ok = bool(rdict["set_applied"] and rdict["query_succeeded"] and rdict["matched"])
        return True if ok else False

    ing_v = _role_verified(ing, ingestor_required)
    con_v = _role_verified(con, consumer_required)

    return {
        "node": idx,
        "requested_physical_node": requested_phys_node,
        # §5.2: observed ingestor-workload evidence for this node.
        "ingestor_controls": {
            "mode": int(m.ingestor_mode),
            "phase": INGESTOR_PHASE.get(int(m.ingestor_mode), "off"),
            "delay_ns": int(m.ingestor_delay_ns),
            "stall_fired": int(m.ingestor_stall_fired),
            "rate_throttled_ns": int(m.ingestor_rate_throttled_ns),
        },
        "reservations": m.reservations,
        "bytes_reserved_req": m.bytes_reserved_req,
        "bytes_assigned": m.bytes_assigned,
        "bytes_read": m.bytes_read,
        "bytes_published": m.bytes_published,
        "bytes_consumed": m.bytes_consumed,
        "consumer_bytes_scanned": int(getattr(m, "consumer_bytes_scanned", 0)),
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
        "placement": {
            "requested_physical_node": requested_phys_node,
            "total_addressable_pages": total_pages,
            "sampled_pages": sampled,
            "sample_limit_per_allocation": limit,
            "sample_spacing_pages": int(m.placement_sample_spacing),
            "local_pages_on_target_node": int(m.placement_sample_target_match_pages),
            "remote_pages_other_node": int(m.placement_sample_other_node_pages),
            "unknown_pages": int(m.placement_sample_unknown_pages),
            # backward-compatible aliases
            "sample_target_match_pages": int(m.placement_sample_target_match_pages),
            "sample_other_node_pages": int(m.placement_sample_other_node_pages),
            "sample_unknown_pages": int(m.placement_sample_unknown_pages),
            "sampling_unavailable": bool(m.placement_sampling_unavailable),
            "sampling_not_performed": bool(m.placement_sampling_not_performed),
            "sampling_complete": sampling_complete,
            "sampling_partial": sampling_partial,
            "all_sampled_on_target_node": bool(all_sampled_match),
        },
        "memory_policy": {
            "requested": bool(mbind_requested),
            "requested_count": mbind_req_c,
            "success_count": mbind_suc_c,
            "failure_count": mbind_fail_c,
            "success": bool(mbind_all_ok),
            "failure": bool(mbind_fail_c > 0),
            "all_requested_succeeded": bool(mbind_all_ok),
            "error": int(m.mbind_error),
            # aliases (compatibility: all requested succeeded, not merely any)
            "mbind_policy_requested": bool(mbind_requested),
            "mbind_policy_applied": bool(mbind_all_ok),
            "mbind_error": int(m.mbind_error),
            "strict_mbind_failed": bool(m.strict_mbind_failed),
        },
        "affinity": {
            "requested_physical_node": requested_phys_node,
            "ingestor": ing,
            "consumer": con,
            "ingestor_verified": ing_v,
            "consumer_verified": con_v,
            "effective_verified": _affinity_effective_verified_node(ing, ing_v, con, con_v),
            "strict_affinity_failed": bool(m.strict_affinity_failed),
        },
        "hugepages": {
            "requested_bytes": int(m.hugepage_map_requested_bytes),
            "mapping_obtained_bytes": int(m.hugepage_map_obtained_bytes),
            "ordinary_fallback_bytes": int(m.hugepage_fallback_bytes),
            "observed_huge_kb": int(m.hugepage_observed_kb),
            "observed_available": bool(int(m.hugepage_observed_kb) > 0),
        },
        # aliases preserved
        "hugepage_map_requested_bytes": m.hugepage_map_requested_bytes,
        "hugepage_map_obtained_bytes": m.hugepage_map_obtained_bytes,
        "hugepage_fallback_bytes": m.hugepage_fallback_bytes,
        "hugepage_observed_kb": m.hugepage_observed_kb,
        "alloc_bytes": m.alloc_bytes,
        "ingest_cpu_ns": m.ingest_cpu_ns,
        "consumer_cpu_ns": m.consumer_cpu_ns,
        "res_hist": list(m.res_hist),
        "last_error": int(m.last_error),
    }


def emit_stage0_lines(res, policy_name):
    """Section 8: emit a distinctly labeled distributed-ingest summary.
    Do NOT emit fabricated STAGE0_DIAG time-series samples; DIST_RESULT is the
    authoritative source for experimental dist-engine measurements."""
    t_ms = int(res.wall_seconds * 1000)
    total_cpu = res.ingest_cpu_ns
    q_parts = []
    b_parts = []
    for i in range(res.num_nodes):
        nm = res.nodes[i]
        q_parts.append("n%d:%d,%d" % (i, nm.chunks_published, nm.chunks_consumed))
        b_parts.append("n%d:%d,%d" % (i, nm.current_outstanding, nm.current_published_backlog))
    line = ("STAGE0_DIST_SUMMARY src=dist-ingest t_ms=%d t_us=%d moved=%d major=0 tgt=%d "
            "lim=0 gated_ms=0 cpu_ns=%d q=%s b=%s policy=%s"
            % (t_ms, int(res.wall_seconds * 1e6), res.total_consumed, res.num_nodes - 1,
               total_cpu, ";".join(q_parts), ";".join(b_parts), policy_name))
    print(line, file=sys.stderr)


try:
    from . import topology as _topology_mod  # type: ignore
except Exception:  # pragma: no cover
    try:
        import topology as _topology_mod  # type: ignore
    except Exception:
        _topology_mod = None


def _parse_id_list(raw):
    if _topology_mod is not None:
        vals, ok = _topology_mod.parse_id_list(raw)
        return vals if ok else None
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
                return None  # malformed
            if end >= start:
                out.extend(range(start, end + 1))
            else:
                return None
        else:
            try:
                out.append(int(part))
            except ValueError:
                return None
    return out


def _read_first(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _status_list(field, proc_root="/proc"):
    """Return (values_or_none, known). known=False => unreadable/missing/ambiguous."""
    raw = _read_first(os.path.join(proc_root, "self", "status"))
    if raw is None:
        return None, False
    for line in raw.splitlines():
        if line.startswith(field + ":"):
            rest = line.split(":", 1)[1].strip()
            if rest == "":
                return None, False
            parsed = _parse_id_list(rest)
            if parsed is None:
                return None, False
            return parsed, True
    return None, False


def _allowed_cpus(proc_root="/proc", sched_getaffinity=None):
    sga = sched_getaffinity or os.sched_getaffinity
    try:
        return sorted(sga(0)), True
    except Exception:
        vals, known = _status_list("Cpus_allowed_list", proc_root=proc_root)
        return (sorted(vals) if known and vals is not None else []), known


def _allowed_mems(proc_root="/proc"):
    vals, known = _status_list("Mems_allowed_list", proc_root=proc_root)
    return (sorted(vals) if known and vals is not None else []), known


def _online_nodes(sysfs_root="/sys"):
    raw = _read_first(os.path.join(sysfs_root, "devices", "system", "node", "online"))
    if raw is None:
        return [0], False
    nodes = _parse_id_list(raw)
    if nodes is None:
        return [0], False
    return (nodes or [0]), True


def _node_cpus(node_id, sysfs_root="/sys"):
    raw = _read_first(os.path.join(sysfs_root, "devices", "system", "node", "node%d" % node_id, "cpulist"))
    if raw is None:
        return [], False
    parsed = _parse_id_list(raw)
    if parsed is None:
        return [], False
    return parsed, True


def _node_mem_state(node_id, sysfs_root="/sys"):
    """Return 'has', 'none', or 'unknown' (missing/unparsable)."""
    mi = _read_first(os.path.join(sysfs_root, "devices", "system", "node", "node%d" % node_id, "meminfo"))
    if mi is None:
        return "unknown"
    for line in mi.splitlines():
        if line.startswith("Node %d MemTotal:" % node_id):
            parts = line.split()
            if len(parts) >= 4:
                try:
                    return "has" if int(parts[3]) > 0 else "none"
                except ValueError:
                    return "unknown"
    # meminfo exists but MemTotal unparsable/unexpected
    return "unknown"


def discover_topology_inventory(sysfs_root="/sys", proc_root="/proc", sched_getaffinity=None):
    """Reusable topology inventory (facts). Uses run_dist readers for patchability.

    sched_getaffinity: injectable CPU-affinity discovery callback for deterministic
    synthetic topology tests. Defaults to os.sched_getaffinity for real-host runs.
    """
    if _topology_mod is None:
        return None
    sga = sched_getaffinity or os.sched_getaffinity
    def _sga(_pid):
        return sga(0)
    return _topology_mod.discover_topology(
        sysfs_root=sysfs_root,
        proc_root=proc_root,
        read_first=_read_first,
        sched_getaffinity=_sga,
    )


def _inventory_topology_info(inv, base_info):
    if not inv:
        return base_info
    info = dict(base_info)
    info["inventory"] = inv
    info["node_to_socket"] = inv.get("node_to_socket")
    info["distance"] = inv.get("distance")
    info["cpu_topology_summary"] = inv.get("cpu_topology")
    info["effective_process_cpuset"] = inv.get("effective_process_cpuset")
    info["inventory_unknowns"] = inv.get("unknowns")
    return info


def _verified_usable_nodes(online, online_known, mems_known, allowed_mems_set,
                            cpus_known, allowed_cpus_set, sysfs_root="/sys"):
    """Authoritative automatic usability evaluation for verified node selection.

    Returns (usable, node_states, scan_nodes) where usable is a list of
    (nid, cpus) in scan order for nodes that pass all verified-usability checks.
    node_states records per-node usability/reason/memory state for scanned nodes.
    """
    usable = []
    node_states = {}
    if online_known:
        scan_nodes = list(online)
    else:
        # unknown online-node info: cannot produce verified selection; record state
        scan_nodes = list(online) if online else []
    for nid in scan_nodes:
        if not online_known:
            ok, cpus, reason = False, [], "online_unknown"
        elif not mems_known:
            ok, cpus, reason = False, [], "mems_allowed_unknown"
        elif nid not in allowed_mems_set:
            ok, cpus, reason = False, [], "mem_not_allowed"
        else:
            mstate = _node_mem_state(nid, sysfs_root=sysfs_root)
            if mstate == "none":
                ok, cpus, reason = False, [], "no_memory"
            elif mstate == "unknown":
                ok, cpus, reason = False, [], "memory_unknown"
            else:
                cpus_raw, cpu_list_known = _node_cpus(nid, sysfs_root=sysfs_root)
                if not cpu_list_known:
                    ok, cpus, reason = False, [], "cpu_unknown"
                elif not cpus_raw:
                    ok, cpus, reason = False, [], "cpu_empty"
                elif not cpus_known:
                    ok, cpus, reason = False, [], "cpus_allowed_unknown"
                else:
                    cpus_f = [c for c in cpus_raw if c in allowed_cpus_set]
                    if not cpus_f:
                        ok, cpus, reason = False, [], "no_allowed_cpus_on_node"
                    else:
                        ok, cpus, reason = True, cpus_f, "ok"
        node_states[nid] = {"usable_auto": ok, "reason": reason, "mem_state": _node_mem_state(nid, sysfs_root=sysfs_root)}
        if ok:
            usable.append((nid, cpus))
    return usable, node_states, scan_nodes


def resolve_topology(requested_nodes, phys_nodes_spec=None, no_pin=False,
                     sysfs_root="/sys", proc_root="/proc", mapping_profile=None,
                     sched_getaffinity=None):
    """Return (logical_to_phys, per_node_cpus, topology_info, errors).

    Authoritative CPU/memory usability validation for dist-ingest runs.
    Unknown online-node information must not produce a verified physical-node
    selection; unknown allowed-CPU information must not be treated as an
    unrestricted CPU set. --no-pin permits a documented less-restrictive path
    (CPU affinity/pinning facts not required/verified) but does NOT verify
    unknown topology; memory/online/mems-allowed facts still must be
    established unless explicitly stated otherwise.

    mapping_profile: when set for automatic selection (no phys_nodes_spec),
    selects from verified usable nodes using topology-aware mapping
    (cross_socket_spread, intra_socket, all_nodes). intra_socket requires a
    socket-qualified variant via mapping_profile="intra_socket:socketN" or
    resolve_mapping_plan().
    """
    errors = []
    inv = discover_topology_inventory(sysfs_root=sysfs_root, proc_root=proc_root, sched_getaffinity=sched_getaffinity)
    allowed_cpus, cpus_known = _allowed_cpus(proc_root=proc_root, sched_getaffinity=sched_getaffinity)
    allowed_cpus_set = set(allowed_cpus)
    allowed_mems, mems_known = _allowed_mems(proc_root=proc_root)
    allowed_mems_set = set(allowed_mems)
    online, online_known = _online_nodes(sysfs_root=sysfs_root)

    usable, node_states, _scan_nodes = _verified_usable_nodes(
        online, online_known, mems_known, allowed_mems_set, cpus_known, allowed_cpus_set, sysfs_root=sysfs_root)

    if phys_nodes_spec:
        try:
            explicit = [int(x) for x in phys_nodes_spec.split(",") if x.strip() != ""]
        except ValueError:
            return [], [], {}, ["invalid --phys-nodes: %r" % (phys_nodes_spec,)]
        # §5: reject duplicates
        seen = set()
        for nid in explicit:
            if nid in seen:
                errors.append("duplicate physical node id in --phys-nodes: %d" % nid)
            seen.add(nid)
        if errors:
            info = {"mode": "explicit", "explicit": explicit, "requested_nodes": requested_nodes,
                    "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
                    "online_known": online_known, "node_states": node_states}
            return [], [], _inventory_topology_info(inv, info), errors
        # validate each explicit node - must be fully validated, no silent uncertainty
        logical_to_phys = []
        per_node_cpus = []
        for nid in explicit:
            if not online_known:
                errors.append("physical node %d cannot be validated: online-node information unknown" % nid)
                continue
            if nid not in online:
                errors.append("physical node %d not online/known" % nid)
                continue
            if not mems_known:
                errors.append("physical node %d cannot be validated: Mems_allowed unknown" % nid)
                continue
            if nid not in allowed_mems_set:
                errors.append("physical node %d not in allowed mems" % nid)
                continue
            mstate = _node_mem_state(nid, sysfs_root=sysfs_root)
            if mstate == "unknown":
                errors.append("physical node %d cannot be validated: memory information missing/unparsable" % nid)
                continue
            if mstate == "none":
                errors.append("physical node %d has no memory" % nid)
                continue
            cpus, cpu_list_known = _node_cpus(nid, sysfs_root=sysfs_root)
            if not cpu_list_known:
                errors.append("physical node %d cpu list missing/unparsable" % nid)
                continue
            if not no_pin:
                # pinning requested: allowed-CPU info must be known and CPUs valid
                if not cpus_known:
                    errors.append("physical node %d cannot be validated for pinning: Cpus_allowed_list unknown" % nid)
                    continue
                cpus = [c for c in cpus if c in allowed_cpus_set]
                if not cpus:
                    errors.append("physical node %d has no allowed CPUs for pinning" % nid)
                    continue
            else:
                # --no-pin: CPU affinity/pinning not required; do not treat unknown
                # Cpus_allowed_list as unrestricted/verified, but allow selection
                # without verified pinning CPU set. Record uncertainty in info.
                if cpus_known and allowed_cpus_set:
                    # still useful to report filtered view, but not required
                    filtered = [c for c in cpus if c in allowed_cpus_set]
                    cpus = filtered if filtered else cpus
            logical_to_phys.append(nid)
            per_node_cpus.append(cpus if (not no_pin or cpus) else [])
        info = {"mode": "explicit", "online": online, "online_known": online_known,
                "allowed_cpus_count": len(allowed_cpus), "cpus_allowed_known": cpus_known,
                "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
                "usable_nodes_auto": [n for n, _ in usable],
                "logical_to_physical": logical_to_phys, "node_states": node_states,
                "explicit": explicit, "no_pin": bool(no_pin),
                "mapping_profile": mapping_profile or "explicit",
                "topology_verified": (online_known and mems_known and (cpus_known or no_pin) and len(errors) == 0),
                "topology_facts_established": {
                    "online_nodes": bool(online_known),
                    "mems_allowed": bool(mems_known),
                    "cpus_allowed": bool(cpus_known),
                    "per_node_memory": True,  # checked per selected node when successful
                    "per_node_cpulist": True,  # checked per selected node when successful
                    "cpu_affinity_verified": bool(cpus_known and not no_pin),
                },
                "topology_unknowns": [k for k, v in {
                    "online_nodes": not online_known,
                    "mems_allowed": not mems_known,
                    "cpus_allowed": not cpus_known,
                }.items() if v]}
        if errors:
            return [], [], _inventory_topology_info(inv, info), errors
        if requested_nodes and requested_nodes != len(logical_to_phys):
            errors.append("requested --nodes %d but --phys-nodes selects %d node(s)" % (requested_nodes, len(logical_to_phys)))
            return [], [], _inventory_topology_info(inv, info), errors
        # Under --no-pin, do not label unknown CPU-allowance topology as verified affinity.
        if no_pin and not cpus_known:
            info["topology_verified"] = False
        return logical_to_phys, per_node_cpus, _inventory_topology_info(inv, info), []

    # automatic selection requires fully verified topology for a verified selection
    if not online_known:
        info = {"mode": "auto", "requested_nodes": max(1, requested_nodes), "online": online,
                "online_known": False, "allowed_cpus_count": len(allowed_cpus),
                "cpus_allowed_known": cpus_known, "mems_allowed_known": mems_known,
                "mems_allowed": allowed_mems, "usable_nodes_auto": [],
                "node_states": node_states, "logical_to_physical": [],
                "mapping_profile": mapping_profile or "auto",
                "topology_verified": False,
                "topology_unknowns": ["online_nodes"] + ([k for k, v in {"mems_allowed": not mems_known, "cpus_allowed": not cpus_known}.items() if v])}
        return [], [], _inventory_topology_info(inv, info), [
            "online-node information unknown; cannot produce a verified physical-node selection"
        ]
    n = max(1, requested_nodes)
    usable_ids = [nid for nid, _ in usable]
    usable_cpu_map = {nid: cpus for nid, cpus in usable}

    # Topology-aware mapping profiles (auto mode). Explicit concrete mapping is
    # always validated through this same function via phys_nodes_spec.
    selected_ids = None
    profile_used = mapping_profile or "auto"
    if mapping_profile and mapping_profile not in ("auto", "default"):
        if _topology_mod is None or inv is None:
            info = {"mode": "auto", "requested_nodes": n, "online": online, "online_known": online_known,
                    "allowed_cpus_count": len(allowed_cpus), "cpus_allowed_known": cpus_known,
                    "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
                    "usable_nodes_auto": usable_ids, "node_states": node_states,
                    "logical_to_physical": [], "mapping_profile": mapping_profile,
                    "topology_verified": False}
            return [], [], _inventory_topology_info(inv, info), [
                "topology inventory unavailable; cannot resolve mapping profile %r" % (mapping_profile,)
            ]
        # intra_socket must be socket-qualified for a single concrete selection.
        req_profiles = [mapping_profile]
        variants = _topology_mod.select_mapping_profiles(inv, n, usable_ids, requested_profiles=req_profiles)
        if mapping_profile == "intra_socket":
            # ambiguous for single resolution; caller must use resolve_mapping_plan/select concrete variant.
            supported = [v for v in variants if v.get("supported")]
            if len(supported) == 1:
                selected_ids = list(supported[0].get("logical_to_physical") or [])
                profile_used = supported[0].get("variant") or mapping_profile
            else:
                reasons = [v.get("reason") for v in variants if v.get("reason")]
                info = {"mode": "auto", "requested_nodes": n, "online": online, "online_known": online_known,
                        "allowed_cpus_count": len(allowed_cpus), "cpus_allowed_known": cpus_known,
                        "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
                        "usable_nodes_auto": usable_ids, "node_states": node_states,
                        "logical_to_physical": [], "mapping_profile": mapping_profile,
                        "mapping_variants": variants, "topology_verified": False}
                if not supported:
                    return [], [], _inventory_topology_info(inv, info), [
                        "mapping profile intra_socket unsupported for %d node(s): %s" % (n, "; ".join([r for r in reasons if r]) or "no suitable socket")
                    ]
                return [], [], _inventory_topology_info(inv, info), [
                    "mapping profile intra_socket is ambiguous (multiple sockets supported); specify a socket-qualified variant (e.g. intra_socket:socket0)"
                ]
        else:
            v = variants[0] if variants else None
            if not v or not v.get("supported"):
                reason = (v or {}).get("reason") or "unsupported mapping profile"
                info = {"mode": "auto", "requested_nodes": n, "online": online, "online_known": online_known,
                        "allowed_cpus_count": len(allowed_cpus), "cpus_allowed_known": cpus_known,
                        "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
                        "usable_nodes_auto": usable_ids, "node_states": node_states,
                        "logical_to_physical": [], "mapping_profile": mapping_profile,
                        "mapping_variants": variants, "topology_verified": False}
                return [], [], _inventory_topology_info(inv, info), [
                    "mapping profile %s unsupported for %d node(s): %s" % (mapping_profile, n, reason)
                ]
            selected_ids = list(v.get("logical_to_physical") or [])
            profile_used = v.get("variant") or mapping_profile
    else:
        # legacy/default automatic selection: first N verified usable nodes.
        if len(usable) < n:
            reasons = {nid: st["reason"] for nid, st in node_states.items() if not st["usable_auto"]}
            info = {"mode": "auto", "requested_nodes": n, "online": online, "online_known": online_known,
                    "allowed_cpus_count": len(allowed_cpus), "cpus_allowed_known": cpus_known,
                    "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
                    "usable_nodes_auto": usable_ids, "node_states": node_states,
                    "logical_to_physical": [], "mapping_profile": profile_used,
                    "topology_verified": False}
            return [], [], _inventory_topology_info(inv, info), [
                "insufficient verified usable NUMA nodes: requested %d, have %d usable (%s); excluded/uncertain=%s" %
                (n, len(usable), usable_ids, reasons)
            ]
        selected_ids = usable_ids[:n]

    if selected_ids is None or len(selected_ids) != n:
        info = {"mode": "auto", "requested_nodes": n, "online": online, "online_known": online_known,
                "allowed_cpus_count": len(allowed_cpus), "cpus_allowed_known": cpus_known,
                "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
                "usable_nodes_auto": usable_ids, "node_states": node_states,
                "logical_to_physical": [], "mapping_profile": profile_used,
                "topology_verified": False}
        return [], [], _inventory_topology_info(inv, info), [
            "could not resolve %d-node mapping (profile=%s)" % (n, profile_used)
        ]

    # Reuse verified usable-node CPU sets (same validation authority).
    per_node_cpus = [list(usable_cpu_map[nid]) for nid in selected_ids if nid in usable_cpu_map]
    if len(per_node_cpus) != len(selected_ids):
        info = {"mode": "auto", "requested_nodes": n, "online": online, "online_known": online_known,
                "allowed_cpus_count": len(allowed_cpus), "cpus_allowed_known": cpus_known,
                "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
                "usable_nodes_auto": usable_ids, "node_states": node_states,
                "logical_to_physical": [], "mapping_profile": profile_used,
                "topology_verified": False}
        return [], [], _inventory_topology_info(inv, info), [
            "resolved mapping contains node(s) not in verified usable set: %s" % (selected_ids,)
        ]

    info = {"mode": "auto", "online": online, "online_known": online_known,
            "allowed_cpus_count": len(allowed_cpus), "cpus_allowed_known": cpus_known,
            "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
            "usable_nodes_auto": usable_ids,
            "logical_to_physical": list(selected_ids), "node_states": node_states,
            "topology_verified": True, "no_pin": bool(no_pin),
            "mapping_profile": profile_used,
            "requested_nodes": n}
    return list(selected_ids), per_node_cpus, _inventory_topology_info(inv, info), []


def resolve_mapping_plan(requested_nodes, profiles=None, phys_nodes_spec=None, no_pin=False,
                         sysfs_root="/sys", proc_root="/proc", sched_getaffinity=None):
    """Resolve concrete mapping variants for planning/preflight.

    Returns (variants, inventory, errors). Each variant includes support/reason
    and, when supported, a fully validated concrete mapping (validated via the
    same explicit-mapping path as trials).
    """
    if _topology_mod is None:
        return [], None, ["topology module unavailable"]
    inv = discover_topology_inventory(sysfs_root=sysfs_root, proc_root=proc_root, sched_getaffinity=sched_getaffinity)
    if profiles is None:
        profiles = ["cross_socket_spread", "intra_socket", "all_nodes"]
    errors = []

    if phys_nodes_spec:
        # Explicit concrete mapping (single variant). Validate via resolve_topology.
        l2p, cpus, info, terr = resolve_topology(
            requested_nodes, phys_nodes_spec=phys_nodes_spec, no_pin=no_pin,
            sysfs_root=sysfs_root, proc_root=proc_root, sched_getaffinity=sched_getaffinity)
        variant = {
            "profile": "explicit",
            "variant": "explicit",
            "logical_node_count": len(l2p) if l2p else requested_nodes,
            "logical_to_physical": l2p,
            "supported": len(terr) == 0 and bool(l2p),
            "reason": "; ".join(terr) if terr else None,
            "per_node_cpus": cpus,
            "topology_info": info,
            "mapping_provenance": _topology_mod.build_mapping_provenance(
                inv or {}, "explicit", "explicit", l2p, cpus, no_pin, info) if l2p else None,
        }
        if terr:
            errors.extend(terr)
        return [variant], inv, errors

    # Auto/profile-based: derive verified usable set using the same authoritative
    # usability rules as resolve_topology() (no duplicated usable-node logic).
    online, online_known = _online_nodes(sysfs_root=sysfs_root)
    allowed_cpus, cpus_known = _allowed_cpus(proc_root=proc_root, sched_getaffinity=sched_getaffinity)
    allowed_cpus_set = set(allowed_cpus)
    allowed_mems, mems_known = _allowed_mems(proc_root=proc_root)
    allowed_mems_set = set(allowed_mems)
    usable, _node_states, _scan_nodes = _verified_usable_nodes(
        online, online_known, mems_known, allowed_mems_set, cpus_known, allowed_cpus_set, sysfs_root=sysfs_root)
    usable_ids = [nid for nid, _ in usable]
    usable_cpu_map = {nid: cpus for nid, cpus in usable}

    n = max(1, requested_nodes)
    candidates = _topology_mod.select_mapping_profiles(inv or {}, n, usable_ids, requested_profiles=profiles)
    out = []
    for cand in candidates:
        if not cand.get("supported"):
            out.append({**cand, "per_node_cpus": [], "topology_info": None, "mapping_provenance": None})
            continue
        phys = list(cand.get("logical_to_physical") or [])
        spec = ",".join(str(x) for x in phys)
        # Validate concrete mapping with the SAME authority/path trials use.
        l2p, cpus, info, terr = resolve_topology(
            n, phys_nodes_spec=spec, no_pin=no_pin, sysfs_root=sysfs_root, proc_root=proc_root,
            sched_getaffinity=sched_getaffinity)
        supported = (len(terr) == 0 and l2p == phys)
        reason = cand.get("reason")
        if terr:
            reason = "; ".join(terr)
        prov = _topology_mod.build_mapping_provenance(inv or {}, cand.get("profile"), cand.get("variant"), l2p or phys, cpus or [usable_cpu_map.get(x, []) for x in phys], no_pin, info)
        out.append({
            **cand,
            "logical_to_physical": l2p or phys,
            "supported": supported,
            "reason": reason,
            "per_node_cpus": cpus or [list(usable_cpu_map.get(x, [])) for x in phys],
            "topology_info": info,
            "mapping_provenance": prov,
            "validation_errors": terr,
        })
    return out, inv, errors


def build_ctypes_topology(logical_to_phys, per_node_cpus):
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



def _placement_observed_all_sampled_on_target(nodes_out):
    """Tri-state physical-placement observation validity (Addendum A closeout).
    true: all relevant nodes sampled, all sampled pages classifiable, every sampled matched target.
    false: at least one sampled page observed on a different node.
    null: sampling incomplete/unavailable/not performed or unknown page results, with no observed mismatch.
    """
    if not nodes_out:
        return None
    saw_mismatch = False
    saw_unknown = False
    for nd in nodes_out:
        pl = nd.get("placement", {})
        if int(pl.get("sample_other_node_pages", 0) or 0) > 0:
            saw_mismatch = True
        sampled = int(pl.get("sampled_pages", 0) or 0)
        if (pl.get("sampling_unavailable") or pl.get("sampling_not_performed") or
                int(pl.get("sample_unknown_pages", 0) or 0) > 0 or sampled == 0):
            saw_unknown = True
    if saw_mismatch:
        return False
    if saw_unknown:
        return None
    return True


def _affinity_role_factual(rdict, required):
    """Factual tri-state for one role (independent of strict enforcement).
    required=False => N/A (None). required=True: requested+applied+queried+matched => True;
    requested but failed/not matched => False; not requested => None (cannot be established)."""
    if not required:
        return None
    if not rdict.get("requested"):
        return None
    ok = bool(rdict.get("set_applied") and rdict.get("query_succeeded") and rdict.get("matched"))
    return True if ok else False


def _affinity_effective_verified_node(ing, ing_v, con, con_v):
    """Per-node tri-state effective affinity verification over applicable required roles.
    true: every applicable required role requested, applied, queried, and matched.
    false: any applicable required role requested but failed/unqueried/unmatched.
    null: any applicable required role unknown/unrequested and none failed.
    Roles with required=false are not applicable and must not force unknown.
    Empty set of applicable required roles => not applicable/unknown (null)."""
    roles = []
    if ing.get("required", False):
        roles.append(ing_v)
    if con.get("required", False):
        roles.append(con_v)
    if not roles:
        return None
    saw_false = False
    saw_unknown = False
    for v in roles:
        if v is False:
            saw_false = True
        elif v is None:
            saw_unknown = True
        # True: ok
    if saw_false:
        return False
    if saw_unknown:
        return None
    return True


def _affinity_valid_factual(nodes_out):
    """Factual tri-state affinity validity independent of --strict-affinity.
    Evaluated only over roles required by actual topology/architecture.
    true: all required requested roles successfully applied, queried, matched.
    false: at least one required requested role failed or did not match.
    null: required affinity not requested or cannot be established (and no required failure)."""
    if not nodes_out:
        return None
    saw_false = False
    saw_unknown = False
    saw_verified = False
    for nd in nodes_out:
        aff = nd.get("affinity", {})
        for role_name in ("ingestor", "consumer"):
            r = aff.get(role_name, {})
            v = _affinity_role_factual(r, bool(r.get("required", False)))
            if v is False:
                saw_false = True
            elif v is True:
                saw_verified = True
            elif bool(r.get("required", False)):
                # required but unknown/unrequested
                saw_unknown = True
    if saw_false:
        return False
    if saw_unknown:
        return None
    if saw_verified:
        return True
    return None


def _memory_policy_valid_factual(nodes_out):
    """Factual tri-state memory-policy application validity independent of --strict-mbind.
    true: >=1 policy application required and every requested application succeeded.
    false: >=1 requested application failed.
    null: no policy application requested or cannot be established."""
    if not nodes_out:
        return None
    total_req = 0
    total_fail = 0
    for nd in nodes_out:
        mp = nd.get("memory_policy", {})
        req = int(mp.get("requested_count", 0) or 0)
        fail = int(mp.get("failure_count", 0) or 0)
        # fall back to booleans if counts absent
        if req == 0 and mp.get("requested"):
            req = 1
            if mp.get("failure") or (mp.get("requested") and not mp.get("all_requested_succeeded", mp.get("success"))):
                fail = 1
        total_req += req
        total_fail += fail
    if total_req <= 0:
        return None
    if total_fail > 0:
        return False
    return True


def _scan_evidence_valid(consumer_kernel_name, total_consumer_bytes_scanned, total_consumed):
    """Tri-state scan-evidence validity for performance measurement.
    full_byte_scan: true if scan bytes accounted and equal consumed; false if
    accounted but not equal/incomplete; null if missing/indeterminate.
    none: true if scanned bytes are zero; false if nonzero; null if missing/indeterminate."""
    if total_consumer_bytes_scanned is None or total_consumed is None:
        return None
    try:
        scanned = int(total_consumer_bytes_scanned)
        consumed = int(total_consumed)
    except (TypeError, ValueError):
        return None
    if consumer_kernel_name == "full_byte_scan":
        return scanned == consumed
    # none (or explicit no-kernel): scanned bytes must be zero
    return scanned == 0


def _placement_sampling_mode_name(mode):
    # C2: 0=off/performance-isolated, 1=on/bounded in-run placement-validation;
    # §2: 2=full/exhaustive diagnostics.
    try:
        m = int(mode)
    except Exception:
        m = 0
    if m == 1:
        return "on"
    if m == 2:
        return "full"
    return "off"


def _trial_class_for_sampling(placement_sampling_mode):
    return "placement_validation" if _placement_sampling_mode_name(placement_sampling_mode) in ("on", "full") else "performance"


def _performance_measurement_valid(functional_correct, affinity_valid, consumer_kernel_name, total_consumer_bytes_scanned, total_consumed,
                                   placement_sampling_mode=0):
    """Factual tri-state performance-measurement validity.
    Requires functional correctness, verified affinity, evidenced consumer workload,
    and measurement integrity (in-run placement sampling off). Independent failures
    (functional false, affinity false, scan evidence false, sampling-tainted timing)
    => false. Missing/indeterminate scan evidence => unknown unless another
    independent failure already makes it false."""
    if not functional_correct:
        return False
    if affinity_valid is False:
        return False
    # C2/§2: in-run move_pages sampling imposes treatment-dependent overhead on the timed
    # candidate; placement-validation experiments (on/full) are not clean performance
    # measurements.
    if _placement_sampling_mode_name(placement_sampling_mode) in ("on", "full"):
        return False
    scan_ok = _scan_evidence_valid(consumer_kernel_name, total_consumer_bytes_scanned, total_consumed)
    if scan_ok is False:
        return False
    if affinity_valid is True and scan_ok is True:
        return True
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", default="fixed_faa", choices=sorted(POLICY_MAP.keys()))
    ap.add_argument("--input", required=True)
    ap.add_argument("--nodes", type=int, default=2)
    ap.add_argument("--phys-nodes", default=None,
                    help="explicit physical NUMA node ids, comma-separated (logical order); duplicates rejected")
    ap.add_argument("--mapping-profile", default=None,
                    help="topology-aware mapping profile for automatic selection (cross_socket_spread, intra_socket:socketN, all_nodes) or provenance label")
    ap.add_argument("--mapping-variant", default=None,
                    help="mapping variant identifier for provenance/reporting")
    ap.add_argument("--sysfs-root", default="/sys", help="sysfs root for topology discovery (testing)")
    ap.add_argument("--proc-root", default="/proc", help="proc root for topology discovery (testing)")
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
    ap.add_argument("--strict-mbind", action="store_true",
                    help="strict enforcement of successful mbind policy application (not hard physical placement guarantee)")
    ap.add_argument("--no-pin", action="store_true")
    ap.add_argument("--consumer-mode", default="fast", choices=sorted(CONSUMER_MODE.keys()))
    ap.add_argument("--consumer-bps", type=int, default=0)
    ap.add_argument("--consumer-stall-ms", type=int, default=0)
    ap.add_argument("--slow-node", type=int, default=-1)
    ap.add_argument("--slow-mode", default=None, choices=sorted(CONSUMER_MODE.keys()))
    ap.add_argument("--slow-bps", type=int, default=0)
    ap.add_argument("--slow-stall-ms", type=int, default=0)
    ap.add_argument("--consumer-kernel", default="full_byte_scan",
                    choices=["full_byte_scan", "none"],
                    help="deterministic consumer kernel: full_byte_scan (default, memory-touch) or none (explicit opt-out)")
    ap.add_argument("--placement-sampling", default="off", choices=["off", "on", "full"],
                    help="in-run placement sampling mode: off (default, performance-isolated; no move_pages overhead in timed path) "
                         "or on (bounded placement-validation experiment; incurs treatment-dependent overhead and is not a clean "
                         "performance measurement) or full (exhaustive sampling for diagnostics, also not a clean performance measurement)")
    ap.add_argument("--ingestor-modes-per-node", default=None,
                    help="§5.2: per-node ingestor workload control modes, comma list per node index: "
                         + "|".join(sorted(INGESTOR_MODE)) + " (default off)")
    ap.add_argument("--ingestor-delay-ns-per-node", default=None,
                    help="§5.2: per-node delay_ns for modes delay_per_claim/delay_after_read (comma list)")
    ap.add_argument("--ingestor-stall-ms-per-node", default=None,
                    help="§5.2: per-node stall_ms for mode stall_then_recover (comma list)")
    ap.add_argument("--ingestor-rate-bps-per-node", default=None,
                    help="§5.2: per-node rate_bps for mode rate_limit (comma list)")
    ap.add_argument("--trial-class", default=None, choices=["performance", "placement_validation"],
                    help="explicit trial/experiment class label (defaults from --placement-sampling: off->performance, on->placement_validation)")
    ap.add_argument("--linked-performance-trial", default=None,
                    help="identifier of the corresponding performance trial for a placement-validation experiment (provenance/linkage)")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    # §5.2/§2 preflight (fail-closed): malformed ingestor-workload lists,
    # unknown mode names, negative/excess values, and missing/invalid
    # placement-sampling params are rejected before any timed trial runs.
    try:
        _per_node_list(args.ingestor_modes_per_node, args.nodes, INGESTOR_MODE)
        _per_node_list(args.ingestor_delay_ns_per_node, args.nodes)
        _per_node_list(args.ingestor_stall_ms_per_node, args.nodes)
        _per_node_list(args.ingestor_rate_bps_per_node, args.nodes)
    except ValueError as exc:
        raise SystemExit("run_dist preflight rejected malformed ingestor-workload spec: %s" % exc)

    placement_sampling_mode = PLACEMENT_SAMPLING_MODE.get(getattr(args, "placement_sampling", "off"), 0)
    placement_sampling_name = _placement_sampling_mode_name(placement_sampling_mode)
    expected_trial_class = _trial_class_for_sampling(placement_sampling_mode)
    if args.trial_class is not None and args.trial_class != expected_trial_class:
        raise SystemExit(
            "inconsistent placement sampling/trial class: placement_sampling=%s requires trial_class=%s (got %s)"
            % (placement_sampling_name, expected_trial_class, args.trial_class))
    trial_class = expected_trial_class
    linked_performance_trial = getattr(args, "linked_performance_trial", None)

    path = args.input
    if not os.path.isabs(path):
        path = os.path.join(REPO, path)
    st = os.stat(path)
    fd = os.open(path, os.O_RDONLY)

    lib = load_lib()
    policy = POLICY_MAP[args.candidate]

    _map_profile = args.mapping_profile
    if args.phys_nodes and not _map_profile:
        _map_profile = "explicit"
    logical_to_phys, per_node_cpus, topo_info, topo_errors = resolve_topology(
        args.nodes, args.phys_nodes, no_pin=bool(args.no_pin),
        sysfs_root=args.sysfs_root, proc_root=args.proc_root,
        mapping_profile=(None if args.phys_nodes else _map_profile))
    if topo_errors:
        os.close(fd)
        raise SystemExit("topology resolution failed: " + "; ".join(topo_errors))
    n = len(logical_to_phys)
    if n < 1 or n > DI_MAX_NODES:
        os.close(fd)
        raise SystemExit("invalid resolved node count %d" % n)
    _mapping_variant = args.mapping_variant or topo_info.get("mapping_profile") or _map_profile or ("explicit" if args.phys_nodes else "auto")

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
    params.consumer_kernel = 1 if args.consumer_kernel == "full_byte_scan" else 0
    params.placement_sampling = placement_sampling_mode

    cons_arr = (DiConsumerCfg * n)()
    for i in range(n):
        cons_arr[i].mode = CONSUMER_MODE[args.consumer_mode]
        cons_arr[i].bytes_per_sec = args.consumer_bps
        cons_arr[i].stall_ms = args.consumer_stall_ms
    if 0 <= args.slow_node < n and args.slow_mode:
        cons_arr[args.slow_node].mode = CONSUMER_MODE[args.slow_mode]
        cons_arr[args.slow_node].bytes_per_sec = args.slow_bps
        cons_arr[args.slow_node].stall_ms = args.slow_stall_ms

    # §5.2: per-node ingestor workload controls (off by default).
    ing_modes = _per_node_list(args.ingestor_modes_per_node, n, INGESTOR_MODE)
    ing_delays = _per_node_list(args.ingestor_delay_ns_per_node, n)
    ing_stalls = _per_node_list(args.ingestor_stall_ms_per_node, n)
    ing_rates = _per_node_list(args.ingestor_rate_bps_per_node, n)
    ing_arr = (DiIngestorCfg * n)()
    for i in range(n):
        ing_arr[i].mode = ing_modes[i]
        ing_arr[i].delay_ns = ing_delays[i]
        ing_arr[i].stall_ms = ing_stalls[i]
        ing_arr[i].rate_bps = ing_rates[i]

    topo_keepalive = None
    cfg = DiConfig()
    cfg.num_nodes = n
    cfg.policy = policy
    cfg.params = params
    cfg.consumers = ctypes.cast(cons_arr, ctypes.POINTER(DiConsumerCfg))
    cfg.ingestors = ctypes.cast(ing_arr, ctypes.POINTER(DiIngestorCfg))
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
        raise SystemExit("di_create failed (invalid config or allocation failure)")

    res = DiResult()
    t0 = time.monotonic()
    rc = lib.di_run(eng, ctypes.byref(res))
    elapsed = time.monotonic() - t0
    lib.di_destroy(eng)
    os.close(fd)

    if rc != 0:
        print("DIST_ERROR rc=%d" % rc, file=sys.stderr)

    emit_stage0_lines(res, args.candidate)

    nodes_out = [node_metrics_to_dict(res.nodes[i], i, logical_to_phys[i] if i < len(logical_to_phys) else None, policy=policy) for i in range(res.num_nodes)]
    functional_correct = (rc == 0 and not res.overlap_detected and not res.duplicate_detected and not res.lost_detected
                          and not res.input_changed and res.total_consumed == st.st_size)
    affinity_valid = _affinity_valid_factual(nodes_out)
    placement_policy_valid = _memory_policy_valid_factual(nodes_out)
    placement_obs = _placement_observed_all_sampled_on_target(nodes_out)
    consumer_kernel_name = "full_byte_scan" if params.consumer_kernel == 1 else "none"
    _total_scanned = getattr(res, "total_consumer_bytes_scanned", None)
    _total_consumed_res = getattr(res, "total_consumed", None)
    performance_measurement_valid = _performance_measurement_valid(
        functional_correct, affinity_valid, consumer_kernel_name, _total_scanned, _total_consumed_res,
        placement_sampling_mode=placement_sampling_mode)

    # Overall NUMA-placement validity (tri-state, factual; strict flags affect enforcement, not truth):
    # true requires successful required policy application (true), verified required affinity (true),
    # and positive placement observations (true). Observed mismatch => false. Otherwise unknown.
    if placement_obs is False:
        numa_placement_valid = False
    elif (placement_obs is True and placement_policy_valid is True and affinity_valid is True):
        numa_placement_valid = True
    elif (affinity_valid is False or placement_policy_valid is False):
        numa_placement_valid = False
    else:
        numa_placement_valid = None

    engine_model = "dist_ingest_experimental"
    # consumer_kernel_name, _total_scanned, _total_consumed_res computed above for validity
    scan_ev_ok = _scan_evidence_valid(consumer_kernel_name, _total_scanned, _total_consumed_res)
    comparability = {
        "engine": engine_model,
        "consumers": "simulated_per_node (dist_ingest)",
        "work_units": "byte-range reservations/chunks",
        "measurement_boundaries": "di_run wall + per-node ingest/consumer CPU/backlog/reservation metrics",
        "centralized_baseline": bool(res.policy == DI_POLICY_CENTRALIZED_INGEST),
        "consumer_kernel": consumer_kernel_name,
        "consumer_kernel_id": int(params.consumer_kernel),
        "placement_sampling": placement_sampling_name,
        "placement_sampling_mode": int(placement_sampling_mode),
        "trial_class": trial_class,
        "note": "Comparable only among dist_ingest_experimental candidates run with same consumers/work units/measurement boundaries and identical consumer kernel/params. "
                "Performance trials (placement_sampling=off) are performance-isolated; placement-validation trials (placement_sampling=on) incur in-run move_pages overhead and must not be mixed into performance headline statistics. "
                "Production forkrun results, if any, are separate reference only.",
    }
    _inv = topo_info.get("inventory") if isinstance(topo_info, dict) else None
    if _inv is None and _topology_mod is not None:
        try:
            _inv = discover_topology_inventory(sysfs_root=args.sysfs_root, proc_root=args.proc_root)
        except Exception:
            _inv = None
    _map_profile_out = _map_profile or topo_info.get("mapping_profile") or ("explicit" if args.phys_nodes else "auto")
    if _topology_mod is not None and _inv is not None:
        try:
            mapping_provenance = _topology_mod.build_mapping_provenance(
                _inv, _map_profile_out, _mapping_variant, logical_to_phys,
                per_node_cpus, bool(args.no_pin), topo_info, affinity_valid=affinity_valid)
        except Exception:
            mapping_provenance = {
                "mapping_profile": _map_profile_out,
                "mapping_variant": _mapping_variant,
                "logical_to_physical": logical_to_phys,
                "logical_to_physical_map": {str(i): nid for i, nid in enumerate(logical_to_phys)},
                "numa_node_to_socket": {},
                "per_node_cpu_lists": {},
                "pairwise_numa_distances": {"complete": False, "pairs": {}},
                "spans_sockets": None,
                "all_requested_affinity_roles_verified": affinity_valid,
                "topology_facts_unavailable": list((topo_info or {}).get("topology_unknowns") or []),
                "provenance_error": "mapping_provenance_build_failed",
            }
    else:
        mapping_provenance = {
            "mapping_profile": _map_profile_out,
            "mapping_variant": _mapping_variant,
            "logical_to_physical": logical_to_phys,
            "logical_to_physical_map": {str(i): nid for i, nid in enumerate(logical_to_phys)},
            "numa_node_to_socket": {},
            "per_node_cpu_lists": {str(nid): {"logical_node_index": i, "physical_node": nid,
                                  "selected_cpus_for_pinning": list(per_node_cpus[i]) if i < len(per_node_cpus) else [],
                                  "pinning_requested": not bool(args.no_pin)}
                                   for i, nid in enumerate(logical_to_phys)},
            "pairwise_numa_distances": {"complete": False, "pairs": {}},
            "spans_sockets": None,
            "all_requested_affinity_roles_verified": affinity_valid,
            "topology_facts_unavailable": list((topo_info or {}).get("topology_unknowns") or ["inventory_unavailable"]),
            "no_pin": bool(args.no_pin),
        }
    out = {
        "candidate": args.candidate,
        "engine_model": engine_model,
        "trial_class": trial_class,
        "measurement_integrity": {
            "placement_sampling": placement_sampling_name,
            "placement_sampling_mode": int(placement_sampling_mode),
            "timing_tainted_by_in_run_sampling": bool(placement_sampling_name == "on"),
            "performance_isolated": bool(placement_sampling_name == "off"),
            "linked_performance_trial": linked_performance_trial,
        },
        "linked_performance_trial": linked_performance_trial,
        "comparability": comparability,
        "policy": res.policy,
        "num_nodes": res.num_nodes,
        "input": args.input,
        "file_size": st.st_size,
        "rc": rc,
        "wall_seconds": res.wall_seconds,
        "elapsed_s": elapsed,
        "libdist_ingest_sha256": LIBDIST_INGEST_SHA256,
        "total_reserved_req": res.total_reserved_req,
        "total_assigned": res.total_assigned,
        "total_read": res.total_read,
        "total_published": res.total_published,
        "total_consumed": res.total_consumed,
        "total_consumer_bytes_scanned": int(_total_scanned) if _total_scanned is not None else 0,
        "reservations_total": res.reservations_total,
        "overlap_detected": bool(res.overlap_detected),
        "duplicate_detected": bool(res.duplicate_detected),
        "lost_detected": bool(res.lost_detected),
        "input_changed": bool(res.input_changed),
        "ingest_cpu_ns": res.ingest_cpu_ns,
        "consumer_cpu_ns": res.consumer_cpu_ns,
        "res_hist": list(res.res_hist),
        "nodes": nodes_out,
        # §5.2: ingestor workload-control provenance. "config_per_node" is
        # the requested control surface; the observed evidence lives in each
        # node entry's "ingestor_controls".
        "ingestor_controls": {
            "config_per_node": [
                {"node": i, "mode": ing_modes[i],
                 "phase": INGESTOR_PHASE[ing_modes[i]],
                 "delay_ns": int(ing_delays[i]),
                 "stall_ms": int(ing_stalls[i]),
                 "rate_bps": int(ing_rates[i])}
                for i in range(n)],
            "disabled_by_default": all(m == 0 for m in ing_modes),
        },
        "consumer_kernel": {
            "name": consumer_kernel_name,
            "id": int(params.consumer_kernel),
            "params": {
                "consumer_mode_arg": args.consumer_mode,
                "consumer_bps": int(args.consumer_bps),
                "consumer_stall_ms": int(args.consumer_stall_ms),
            },
            "scan_bytes_evidence": {
                "total_consumer_bytes_scanned": int(_total_scanned) if _total_scanned is not None else None,
                "total_consumed": int(_total_consumed_res) if _total_consumed_res is not None else None,
                "scan_equals_consumed": scan_ev_ok,
            },
        },
        "topology": {
            **topo_info,
            "requested_nodes_arg": args.nodes,
            "phys_nodes_arg": args.phys_nodes,
            "pinning": "disabled" if args.no_pin else "requested",
            "strict_affinity": bool(args.strict_affinity),
            "strict_mbind": bool(args.strict_mbind),
            "per_node_cpus": per_node_cpus,
        },
        "mapping_provenance": mapping_provenance,
        "placement_semantics": {
            "mbind_policy": "MPOL_PREFERRED requested; mbind_policy_applied reflects syscall success only, not physical placement proof",
            "mbind_policy_applied_meaning": "compatibility field: true only when >=1 policy application requested and every requested application succeeded (not merely any)",
            "strict_mbind_meaning": "strict enforcement of successful policy application (mbind syscall), not hard physical placement guarantee; strictness controls abort/enforcement, not factual validity reporting",
            "strict_affinity_meaning": "strictness controls abort/enforcement, not factual validity reporting",
            "placement_sampling": "observed page placement sampled independently of mbind result; all_sampled_on_target_node means all sampled pages observed on target node only (not all pages examined). sample_limit and sample_spacing_pages are per-allocation sampling parameters recorded per node (spacing reflects the last allocation sampled, not an aggregate over all samples).",
            "placement_sampling_mode_meaning": "C2: off=performance-isolated (no in-run move_pages sampling; placement observation not performed; timed measurement not tainted by sampling). on=placement-validation experiment (in-run move_pages sampling enabled; timing tainted and must not be mixed with performance headline statistics).",
            "preferred_mismatch_is_not_syscall_failure": True,
            "placement_observed_all_sampled_on_target_meaning": "tri-state: true=all relevant nodes sampled, all sampled pages classifiable, every sampled page matched target; false=at least one sampled page observed on a different node; null=sampling incomplete/unavailable/not performed or included unknown page results with no observed mismatch",
            "affinity_validity_meaning": "tri-state factual: true=all required requested roles set/query/matched; false=any required requested role failed/not matched; null=required affinity not requested or cannot be established",
            "memory_policy_validity_meaning": "tri-state factual: true=>=1 requested and every requested application succeeded; false=>=1 requested application failed; null=no policy application requested or cannot be established",
            "numa_placement_validity_meaning": "tri-state: true requires successful required policy application, verified required affinity, and positive placement observations; false on observed mismatch or required affinity/policy failure evidence; null otherwise",
            "performance_measurement_integrity": "performance trials must run with placement_sampling=off; placement-validation trials (placement_sampling=on) are distinct experiments and are not performance-valid measurements",
        },
        "validity": {
            "functional_correctness": functional_correct,
            "performance_measurement": performance_measurement_valid,
            "affinity": affinity_valid,
            "memory_policy_application": placement_policy_valid,
            "placement_observed": placement_obs,
            "numa_placement": numa_placement_valid,
            # detailed/compat fields
            "functional_correct": functional_correct,
            "affinity_valid": affinity_valid,
            "placement_policy_valid": placement_policy_valid,
            "placement_valid": placement_policy_valid,
            "placement_observed_all_sampled_on_target": placement_obs,
        },
        "correct": functional_correct,
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
    print("DIST_RESULT " + json.dumps(out, sort_keys=True), file=sys.stderr)
    child = {
        "elapsed_s": res.wall_seconds if res.wall_seconds > 0 else elapsed,
        "completed_bytes": res.total_consumed,
        "completed_records": res.total_consumed,
        "rec_per_s": (res.total_consumed / res.wall_seconds) if res.wall_seconds > 0 else 0,
        "completed_output_bytes_per_s": (res.total_consumed / res.wall_seconds) if res.wall_seconds > 0 else 0,
    }
    print("CHILD_DONE " + json.dumps(child))
    return 0 if out["correct"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
