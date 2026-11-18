#!/usr/bin/env python3
"""Run experimental distributed-ingestion candidates and emit metrics.

Isolated harness for dist-ingest prototype. Does NOT modify frozen production
ring engine. Addendum A: per-role affinity, separated mbind policy vs observed
placement, topology uncertainty/duplicate-node validation, explicit provenance.
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
    ]


class DiConsumerCfg(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("bytes_per_sec", ctypes.c_uint64),
        ("stall_ms", ctypes.c_uint64),
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
            "effective_verified": bool(
                (ing_v is not False) and (con_v is not False) and (ing_v is True or con_v is True or (ing_v is None and con_v is None))
            ),
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


def _status_list(field):
    """Return (values_or_none, known). known=False => unreadable/missing/ambiguous."""
    raw = _read_first("/proc/self/status")
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


def _allowed_cpus():
    try:
        return sorted(os.sched_getaffinity(0)), True
    except Exception:
        vals, known = _status_list("Cpus_allowed_list")
        return (sorted(vals) if known and vals is not None else []), known


def _allowed_mems():
    vals, known = _status_list("Mems_allowed_list")
    return (sorted(vals) if known and vals is not None else []), known


def _online_nodes():
    raw = _read_first("/sys/devices/system/node/online")
    if raw is None:
        return [0], False
    nodes = _parse_id_list(raw)
    if nodes is None:
        return [0], False
    return (nodes or [0]), True


def _node_cpus(node_id):
    raw = _read_first("/sys/devices/system/node/node%d/cpulist" % node_id)
    if raw is None:
        return [], False
    parsed = _parse_id_list(raw)
    if parsed is None:
        return [], False
    return parsed, True


def _node_mem_state(node_id):
    """Return 'has', 'none', or 'unknown' (missing/unparsable)."""
    mi = _read_first("/sys/devices/system/node/node%d/meminfo" % node_id)
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


def resolve_topology(requested_nodes, phys_nodes_spec=None, no_pin=False):
    """Return (logical_to_phys, per_node_cpus, topology_info, errors).

    Closeout §2: unknown online-node information must not produce a verified
    physical-node selection; unknown allowed-CPU information must not be treated
    as an unrestricted CPU set. --no-pin permits a documented less-restrictive
    path (CPU affinity/pinning facts not required/verified) but does NOT verify
    unknown topology; memory/online/mems-allowed facts still must be established
    unless explicitly stated otherwise.
    """
    errors = []
    allowed_cpus, cpus_known = _allowed_cpus()
    allowed_cpus_set = set(allowed_cpus)
    allowed_mems, mems_known = _allowed_mems()
    allowed_mems_set = set(allowed_mems)
    online, online_known = _online_nodes()

    def node_usable_auto(nid):
        # online/mems/memory must be established; CPU affinity facts may be
        # relaxed only in the explicit --no-pin sense (auto still requires a
        # verified usable CPU set for node selection unless we cannot establish
        # anything). Unknown allowed-CPU info must not be treated as unrestricted.
        if not online_known:
            return False, [], "online_unknown"
        if not mems_known:
            return False, [], "mems_allowed_unknown"
        if nid not in allowed_mems_set:
            return False, [], "mem_not_allowed"
        mstate = _node_mem_state(nid)
        if mstate == "none":
            return False, [], "no_memory"
        if mstate == "unknown":
            return False, [], "memory_unknown"
        cpus, cpu_list_known = _node_cpus(nid)
        if not cpu_list_known:
            return False, [], "cpu_unknown"
        if not cpus:
            return False, [], "cpu_empty"
        # allowed-CPU set must be known to be treated as a restriction; unknown
        # allowed-CPU info must not be treated as unrestricted.
        if not cpus_known:
            return False, [], "cpus_allowed_unknown"
        cpus = [c for c in cpus if c in allowed_cpus_set]
        if not cpus:
            return False, [], "no_allowed_cpus_on_node"
        return True, cpus, "ok"

    usable = []
    node_states = {}
    if online_known:
        scan_nodes = online
    else:
        # unknown online-node info: cannot produce verified selection; record state
        scan_nodes = list(online) if online else []
    for nid in scan_nodes:
        ok, cpus, reason = node_usable_auto(nid)
        node_states[nid] = {"usable_auto": ok, "reason": reason, "mem_state": _node_mem_state(nid)}
        if ok:
            usable.append((nid, cpus))

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
            return [], [], {"mode": "explicit", "explicit": explicit, "requested_nodes": requested_nodes,
                            "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
                            "online_known": online_known, "node_states": node_states}, errors
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
            mstate = _node_mem_state(nid)
            if mstate == "unknown":
                errors.append("physical node %d cannot be validated: memory information missing/unparsable" % nid)
                continue
            if mstate == "none":
                errors.append("physical node %d has no memory" % nid)
                continue
            cpus, cpu_list_known = _node_cpus(nid)
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
                "usable_nodes_auto": [n for n,_ in usable],
                "logical_to_physical": logical_to_phys, "node_states": node_states,
                "explicit": explicit, "no_pin": bool(no_pin),
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
            return [], [], info, errors
        if requested_nodes and requested_nodes != len(logical_to_phys):
            errors.append("requested --nodes %d but --phys-nodes selects %d node(s)" % (requested_nodes, len(logical_to_phys)))
            return [], [], info, errors
        # Under --no-pin, do not label unknown CPU-allowance topology as verified affinity.
        if no_pin and not cpus_known:
            info["topology_verified"] = False
        return logical_to_phys, per_node_cpus, info, []

    # automatic selection requires fully verified topology for a verified selection
    if not online_known:
        return [], [], {"mode": "auto", "requested_nodes": max(1, requested_nodes), "online": online,
                        "online_known": False, "allowed_cpus_count": len(allowed_cpus),
                        "cpus_allowed_known": cpus_known, "mems_allowed_known": mems_known,
                        "mems_allowed": allowed_mems, "usable_nodes_auto": [],
                        "node_states": node_states, "logical_to_physical": [],
                        "topology_verified": False,
                        "topology_unknowns": ["online_nodes"] + ([k for k,v in {"mems_allowed":not mems_known,"cpus_allowed":not cpus_known}.items() if v])}, [
            "online-node information unknown; cannot produce a verified physical-node selection"
        ]
    n = max(1, requested_nodes)
    if len(usable) < n:
        reasons = {nid: st["reason"] for nid, st in node_states.items() if not st["usable_auto"]}
        return [], [], {"mode": "auto", "requested_nodes": n, "online": online, "online_known": online_known,
                        "allowed_cpus_count": len(allowed_cpus), "cpus_allowed_known": cpus_known,
                        "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
                        "usable_nodes_auto": [nid for nid,_ in usable],
                        "node_states": node_states, "logical_to_physical": [],
                        "topology_verified": False}, [
            "insufficient verified usable NUMA nodes: requested %d, have %d usable (%s); excluded/uncertain=%s" %
            (n, len(usable), [nid for nid,_ in usable], reasons)
        ]
    picked = usable[:n]
    logical_to_phys = [nid for nid, _ in picked]
    per_node_cpus = [cpus for _, cpus in picked]
    info = {"mode": "auto", "online": online, "online_known": online_known,
            "allowed_cpus_count": len(allowed_cpus), "cpus_allowed_known": cpus_known,
            "mems_allowed_known": mems_known, "mems_allowed": allowed_mems,
            "usable_nodes_auto": [nid for nid,_ in usable],
            "logical_to_physical": logical_to_phys, "node_states": node_states,
            "topology_verified": True, "no_pin": bool(no_pin)}
    return logical_to_phys, per_node_cpus, info, []


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


def _performance_measurement_valid(functional_correct, affinity_valid):
    # Useful for performance comparison only when functionally correct and affinity
    # is factually verified. Unknown/unverified affinity => not verified (unknown).
    if not functional_correct:
        return False
    if affinity_valid is True:
        return True
    if affinity_valid is False:
        return False
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", default="fixed_faa", choices=sorted(POLICY_MAP.keys()))
    ap.add_argument("--input", required=True)
    ap.add_argument("--nodes", type=int, default=2)
    ap.add_argument("--phys-nodes", default=None,
                    help="explicit physical NUMA node ids, comma-separated (logical order); duplicates rejected")
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
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    path = args.input
    if not os.path.isabs(path):
        path = os.path.join(REPO, path)
    st = os.stat(path)
    fd = os.open(path, os.O_RDONLY)

    lib = load_lib()
    policy = POLICY_MAP[args.candidate]

    logical_to_phys, per_node_cpus, topo_info, topo_errors = resolve_topology(args.nodes, args.phys_nodes, no_pin=bool(args.no_pin))
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
    params.consumer_kernel = 1 if args.consumer_kernel == "full_byte_scan" else 0

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
    performance_measurement_valid = _performance_measurement_valid(functional_correct, affinity_valid)

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
    consumer_kernel_name = "full_byte_scan" if params.consumer_kernel == 1 else "none"
    comparability = {
        "engine": engine_model,
        "consumers": "simulated_per_node (dist_ingest)",
        "work_units": "byte-range reservations/chunks",
        "measurement_boundaries": "di_run wall + per-node ingest/consumer CPU/backlog/reservation metrics",
        "centralized_baseline": bool(res.policy == DI_POLICY_CENTRALIZED_INGEST),
        "consumer_kernel": consumer_kernel_name,
        "consumer_kernel_id": int(params.consumer_kernel),
        "note": "Comparable only among dist_ingest_experimental candidates run with same consumers/work units/measurement boundaries and identical consumer kernel/params. Production forkrun results, if any, are separate reference only.",
    }
    out = {
        "candidate": args.candidate,
        "engine_model": engine_model,
        "comparability": comparability,
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
        "total_consumer_bytes_scanned": int(getattr(res, "total_consumer_bytes_scanned", 0)),
        "reservations_total": res.reservations_total,
        "overlap_detected": bool(res.overlap_detected),
        "duplicate_detected": bool(res.duplicate_detected),
        "lost_detected": bool(res.lost_detected),
        "input_changed": bool(res.input_changed),
        "ingest_cpu_ns": res.ingest_cpu_ns,
        "consumer_cpu_ns": res.consumer_cpu_ns,
        "res_hist": list(res.res_hist),
        "nodes": nodes_out,
        "consumer_kernel": {
            "name": consumer_kernel_name,
            "id": int(params.consumer_kernel),
            "params": {
                "consumer_mode_arg": args.consumer_mode,
                "consumer_bps": int(args.consumer_bps),
                "consumer_stall_ms": int(args.consumer_stall_ms),
            },
            "scan_bytes_evidence": {
                "total_consumer_bytes_scanned": int(getattr(res, "total_consumer_bytes_scanned", 0)),
                "total_consumed": int(res.total_consumed),
                "scan_equals_consumed": bool(int(getattr(res, "total_consumer_bytes_scanned", 0)) == int(res.total_consumed)) if consumer_kernel_name == "full_byte_scan" else bool(int(getattr(res, "total_consumer_bytes_scanned", 0)) == 0),
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
        "placement_semantics": {
            "mbind_policy": "MPOL_PREFERRED requested; mbind_policy_applied reflects syscall success only, not physical placement proof",
            "mbind_policy_applied_meaning": "compatibility field: true only when >=1 policy application requested and every requested application succeeded (not merely any)",
            "strict_mbind_meaning": "strict enforcement of successful policy application (mbind syscall), not hard physical placement guarantee; strictness controls abort/enforcement, not factual validity reporting",
            "strict_affinity_meaning": "strictness controls abort/enforcement, not factual validity reporting",
            "placement_sampling": "observed page placement sampled independently of mbind result; all_sampled_on_target_node means all sampled pages observed on target node only (not all pages examined). sample_limit and sample_spacing_pages are per-allocation sampling parameters recorded per node (spacing reflects the last allocation sampled, not an aggregate over all samples).",
            "preferred_mismatch_is_not_syscall_failure": True,
            "placement_observed_all_sampled_on_target_meaning": "tri-state: true=all relevant nodes sampled, all sampled pages classifiable, every sampled page matched target; false=at least one sampled page observed on a different node; null=sampling incomplete/unavailable/not performed or included unknown page results with no observed mismatch",
            "affinity_validity_meaning": "tri-state factual: true=all required requested roles set/query/matched; false=any required requested role failed/not matched; null=required affinity not requested or cannot be established",
            "memory_policy_validity_meaning": "tri-state factual: true=>=1 requested and every requested application succeeded; false=>=1 requested application failed; null=no policy application requested or cannot be established",
            "numa_placement_validity_meaning": "tri-state: true requires successful required policy application, verified required affinity, and positive placement observations; false on observed mismatch or required affinity/policy failure evidence; null otherwise",
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
