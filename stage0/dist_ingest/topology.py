"""Reusable physical NUMA topology discovery and mapping selection.

This module is the authoritative source for topology *facts* and mapping
selection. CPU/memory *usability validation* for dist-ingest runs remains in
``run_dist.resolve_topology()`` (which consumes this inventory); validation
rules must not be duplicated here.

All discovery accepts configurable roots so deterministic synthetic topology
fixtures can be exercised without touching the host sysfs/proc trees.
"""

from __future__ import annotations

import errno
import glob
import os
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


def _default_read_first(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def parse_id_list(raw: Optional[str]) -> Tuple[Optional[List[int]], bool]:
    """Parse a Linux cpulist/nodelist string.

    Returns (values, ok). ok=False means unreadable/missing/malformed.
    Empty/whitespace-only input is treated as an empty list (ok=True).
    """
    if raw is None:
        return None, False
    text = raw.strip()
    if text == "":
        return [], True
    out: List[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            return None, False
        if "-" in part:
            a, _, b = part.partition("-")
            if a == "" or b == "" or "-" in b:
                return None, False
            try:
                start, end = int(a), int(b)
            except ValueError:
                return None, False
            if end < start:
                return None, False
            out.extend(range(start, end + 1))
        else:
            try:
                out.append(int(part))
            except ValueError:
                return None, False
    return out, True


def _parse_status_list(proc_status: Optional[str], field: str) -> Tuple[Optional[List[int]], bool]:
    if proc_status is None:
        return None, False
    prefix = field + ":"
    for line in proc_status.splitlines():
        if line.startswith(prefix):
            rest = line.split(":", 1)[1].strip()
            if rest == "":
                return None, False
            return parse_id_list(rest)
    return None, False


def _int_or_none(text: Optional[str]) -> Optional[int]:
    if text is None:
        return None
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def _read_int_file(path: str, read_first=_default_read_first) -> Optional[int]:
    raw = read_first(path)
    return _int_or_none(raw)


def _unique_sorted(values: Iterable[int]) -> List[int]:
    return sorted(set(int(v) for v in values))


def discover_topology(
    sysfs_root: str = "/sys",
    proc_root: str = "/proc",
    read_first: Optional[Callable[[str], Optional[str]]] = None,
    sched_getaffinity: Optional[Callable[[int], Iterable[int]]] = None,
) -> Dict[str, Any]:
    """Discover a physical NUMA topology inventory.

    Unknown/unavailable facts are reported explicitly (never guessed).
    """
    rf = read_first or _default_read_first
    sga = sched_getaffinity
    if sga is None:
        def _sga(_pid: int) -> Iterable[int]:
            return os.sched_getaffinity(0)
        sga = _sga

    node_base = os.path.join(sysfs_root, "devices", "system", "node")
    cpu_base = os.path.join(sysfs_root, "devices", "system", "cpu")

    online_raw = rf(os.path.join(node_base, "online"))
    online_ids, online_known = parse_id_list(online_raw)
    online_ids = _unique_sorted(online_ids or []) if online_known else []

    proc_status = rf(os.path.join(proc_root, "self", "status"))
    cpus_allowed_list, cpus_allowed_known = _parse_status_list(proc_status, "Cpus_allowed_list")
    mems_allowed_list, mems_allowed_known = _parse_status_list(proc_status, "Mems_allowed_list")
    cpus_allowed_list = _unique_sorted(cpus_allowed_list or []) if cpus_allowed_known else []
    mems_allowed_list = _unique_sorted(mems_allowed_list or []) if mems_allowed_known else []

    # Effective process affinity (runtime). sched_getaffinity may fail; keep
    # Cpus_allowed_list as the process cpuset fact and record affinity separately.
    affinity_cpus: List[int] = []
    affinity_known = False
    affinity_error: Optional[str] = None
    try:
        affinity_cpus = _unique_sorted(list(sga(0)))
        affinity_known = True
    except Exception as exc:  # pragma: no cover - exercised via injectable hook
        affinity_error = type(exc).__name__

    # CPU/core/thread topology from sysfs cpu topology.
    cpu_ids_raw = []
    for name in sorted(glob.glob(os.path.join(cpu_base, "cpu[0-9]*"))):
        m = re.match(r"^cpu(\d+)$", os.path.basename(name))
        if m:
            cpu_ids_raw.append(int(m.group(1)))
    cpu_ids = _unique_sorted(cpu_ids_raw)
    cpu_topology: Dict[int, Dict[str, Any]] = {}
    pkg_core_pairs = set()
    sockets_seen = set()
    for cid in cpu_ids:
        tdir = os.path.join(cpu_base, "cpu%d" % cid, "topology")
        pkg = _read_int_file(os.path.join(tdir, "physical_package_id"), rf)
        core = _read_int_file(os.path.join(tdir, "core_id"), rf)
        cpu_topology[cid] = {
            "cpu": cid,
            "physical_package_id": pkg,
            "core_id": core,
            "physical_package_known": pkg is not None,
            "core_id_known": core is not None,
        }
        if pkg is not None:
            sockets_seen.add(pkg)
        if pkg is not None and core is not None:
            pkg_core_pairs.add((pkg, core))

    cpu_count_logical = len(cpu_ids)
    cpu_count_physical_cores = len(pkg_core_pairs) if pkg_core_pairs else None
    threads_per_core: Optional[int] = None
    if cpu_count_physical_cores and cpu_count_physical_cores > 0 and cpu_count_logical % cpu_count_physical_cores == 0:
        threads_per_core = cpu_count_logical // cpu_count_physical_cores

    nodes: Dict[int, Dict[str, Any]] = {}
    scan_nodes = online_ids if online_known else []
    for nid in scan_nodes:
        ndir = os.path.join(node_base, "node%d" % nid)
        cpulist_raw = rf(os.path.join(ndir, "cpulist"))
        node_cpus, node_cpus_known = parse_id_list(cpulist_raw)
        node_cpus = _unique_sorted(node_cpus or []) if node_cpus_known else []

        meminfo_raw = rf(os.path.join(ndir, "meminfo"))
        mem_total_kb: Optional[int] = None
        mem_free_kb: Optional[int] = None
        meminfo_present = meminfo_raw is not None
        meminfo_parsed = False
        if meminfo_raw is not None:
            for line in meminfo_raw.splitlines():
                if line.startswith("Node %d MemTotal:" % nid):
                    parts = line.split()
                    if len(parts) >= 4:
                        mem_total_kb = _int_or_none(parts[3])
                elif line.startswith("Node %d MemFree:" % nid):
                    parts = line.split()
                    if len(parts) >= 4:
                        mem_free_kb = _int_or_none(parts[3])
            meminfo_parsed = mem_total_kb is not None
        if mem_total_kb is None:
            mem_state = "unknown"
        elif mem_total_kb > 0:
            mem_state = "has"
        else:
            mem_state = "none"

        # Node -> socket/package mapping from CPUs on this node.
        socket_ids: List[int] = []
        socket_ids_known = False
        socket_ambiguous = False
        socket_unknown_reason: Optional[str] = None
        if not node_cpus_known:
            socket_unknown_reason = "node_cpulist_unknown"
        elif not node_cpus:
            socket_unknown_reason = "node_cpulist_empty"
        else:
            seen_pkgs = set()
            any_unknown = False
            for c in node_cpus:
                info = cpu_topology.get(c)
                if info is None or info.get("physical_package_id") is None:
                    any_unknown = True
                else:
                    seen_pkgs.add(int(info["physical_package_id"]))
            if any_unknown or not seen_pkgs:
                socket_unknown_reason = "cpu_package_unknown"
            else:
                socket_ids = sorted(seen_pkgs)
                socket_ids_known = True
                socket_ambiguous = len(socket_ids) > 1

        # Effective allowed CPUs for this node (intersection with process allowed
        # CPUs when known) - reported as a fact, not a usability decision.
        effective_allowed_cpus: Optional[List[int]] = None
        effective_allowed_cpus_known = False
        if node_cpus_known and cpus_allowed_known:
            allowed_set = set(cpus_allowed_list)
            effective_allowed_cpus = [c for c in node_cpus if c in allowed_set]
            effective_allowed_cpus_known = True
        elif not node_cpus_known:
            effective_allowed_cpus = None
        elif not cpus_allowed_known:
            effective_allowed_cpus = None

        nodes[nid] = {
            "node": nid,
            "online": True,
            "cpulist_raw": cpulist_raw,
            "cpus": node_cpus,
            "cpus_known": node_cpus_known,
            "cpu_count": len(node_cpus) if node_cpus_known else None,
            "meminfo_present": meminfo_present,
            "meminfo_parsed": meminfo_parsed,
            "mem_total_kb": mem_total_kb,
            "mem_free_kb": mem_free_kb,
            "mem_state": mem_state,
            "socket_ids": socket_ids if socket_ids_known else [],
            "socket_ids_known": socket_ids_known,
            "socket_ambiguous": socket_ambiguous,
            "socket_id": socket_ids[0] if (socket_ids_known and not socket_ambiguous) else None,
            "socket_unknown_reason": socket_unknown_reason,
            "effective_allowed_cpus": effective_allowed_cpus,
            "effective_allowed_cpus_known": effective_allowed_cpus_known,
        }

    # Distance matrix: ordered by online node IDs.
    ordered_nodes = list(online_ids)
    distance_matrix: List[List[Optional[int]]] = []
    distance_rows: Dict[int, Dict[str, Any]] = {}
    distance_matrix_complete = False
    distance_matrix_known = bool(online_known)
    if online_known:
        all_ok = True
        for src in ordered_nodes:
            row_raw = rf(os.path.join(node_base, "node%d" % src, "distance"))
            row_vals: Optional[List[int]] = None
            row_ok = False
            row_reason: Optional[str] = None
            if row_raw is None:
                row_reason = "missing"
            else:
                tokens = row_raw.strip().split()
                if len(tokens) != len(ordered_nodes):
                    row_reason = "length_mismatch"
                else:
                    try:
                        row_vals = [int(t) for t in tokens]
                        row_ok = True
                    except ValueError:
                        row_reason = "non_integer"
            if row_ok and row_vals is not None:
                distance_matrix.append(row_vals)
                distance_rows[src] = {"known": True, "values": row_vals, "reason": None}
            else:
                all_ok = False
                distance_matrix.append([None] * len(ordered_nodes))
                distance_rows[src] = {"known": False, "values": None, "reason": row_reason}
        distance_matrix_complete = all_ok and len(ordered_nodes) > 0
    else:
        distance_matrix_known = False

    # Nearest intra-socket / cross-socket distances derived from matrix + sockets.
    nearest_intra_socket_distance: Optional[int] = None
    nearest_cross_socket_distance: Optional[int] = None
    nearest_other_distance: Optional[int] = None
    distance_unknown_reasons: List[str] = []
    if not online_known:
        distance_unknown_reasons.append("online_nodes_unknown")
    elif not distance_matrix_complete:
        distance_unknown_reasons.append("distance_matrix_incomplete")
    else:
        # classify node sockets; ambiguous/unknown sockets prevent reliable split
        node_to_socket: Dict[int, Optional[int]] = {}
        any_ambiguous = False
        for nid in ordered_nodes:
            nd = nodes.get(nid, {})
            if nd.get("socket_ids_known") and not nd.get("socket_ambiguous"):
                node_to_socket[nid] = nd.get("socket_id")
            else:
                node_to_socket[nid] = None
                any_ambiguous = True
        idx = {nid: i for i, nid in enumerate(ordered_nodes)}
        intra_vals: List[int] = []
        cross_vals: List[int] = []
        other_vals: List[int] = []
        for a in ordered_nodes:
            for b in ordered_nodes:
                if a == b:
                    continue
                d = distance_matrix[idx[a]][idx[b]]
                if d is None:
                    continue
                other_vals.append(int(d))
                sa = node_to_socket.get(a)
                sb = node_to_socket.get(b)
                if sa is None or sb is None:
                    continue
                if sa == sb:
                    intra_vals.append(int(d))
                else:
                    cross_vals.append(int(d))
        if other_vals:
            nearest_other_distance = min(other_vals)
        if intra_vals:
            nearest_intra_socket_distance = min(intra_vals)
        if cross_vals:
            nearest_cross_socket_distance = min(cross_vals)
        # If sockets ambiguous, report that split may be incomplete/unknown.
        if any_ambiguous:
            distance_unknown_reasons.append("node_socket_ambiguous_or_unknown")

    unknowns: List[str] = []
    if not online_known:
        unknowns.append("online_nodes")
    if not mems_allowed_known:
        unknowns.append("mems_allowed")
    if not cpus_allowed_known:
        unknowns.append("cpus_allowed")
    if not affinity_known:
        unknowns.append("process_affinity")
    if not distance_matrix_complete:
        unknowns.append("distance_matrix")
    # per-node unknown facts
    for nid in ordered_nodes:
        nd = nodes.get(nid, {})
        if not nd.get("cpus_known"):
            unknowns.append("node%d.cpulist" % nid)
        if nd.get("mem_state") == "unknown":
            unknowns.append("node%d.memory" % nid)
        if not nd.get("socket_ids_known") or nd.get("socket_ambiguous"):
            unknowns.append("node%d.socket" % nid)

    inventory = {
        "sysfs_root": sysfs_root,
        "proc_root": proc_root,
        "online_nodes": ordered_nodes,
        "online_known": online_known,
        "online_raw": online_raw,
        "allowed_mem_nodes": mems_allowed_list,
        "allowed_mem_nodes_known": mems_allowed_known,
        "allowed_mem_nodes_raw": _parse_status_list(proc_status, "Mems_allowed_list")[0] if mems_allowed_known else None,
        "allowed_cpus": cpus_allowed_list,
        "allowed_cpus_known": cpus_allowed_known,
        "effective_process_cpuset": {
            "cpus_allowed_list": cpus_allowed_list if cpus_allowed_known else None,
            "cpus_allowed_list_known": cpus_allowed_known,
            "mems_allowed_list": mems_allowed_list if mems_allowed_known else None,
            "mems_allowed_list_known": mems_allowed_known,
            "affinity_cpus": affinity_cpus if affinity_known else None,
            "affinity_known": affinity_known,
            "affinity_error": affinity_error,
        },
        "nodes": nodes,
        "node_to_socket": {
            nid: {
                "socket_id": nodes[nid].get("socket_id"),
                "socket_ids": nodes[nid].get("socket_ids"),
                "known": bool(nodes[nid].get("socket_ids_known") and not nodes[nid].get("socket_ambiguous")),
                "ambiguous": bool(nodes[nid].get("socket_ambiguous")),
                "reason": nodes[nid].get("socket_unknown_reason"),
            }
            for nid in ordered_nodes
        },
        "distance": {
            "ordered_node_ids": ordered_nodes,
            "matrix": distance_matrix,
            "rows": distance_rows,
            "complete": distance_matrix_complete,
            "known": distance_matrix_known,
            "nearest_other_distance": nearest_other_distance,
            "nearest_intra_socket_distance": nearest_intra_socket_distance,
            "nearest_cross_socket_distance": nearest_cross_socket_distance,
            "unknown_reasons": distance_unknown_reasons,
        },
        "cpu_topology": {
            "logical_cpu_count": cpu_count_logical,
            "physical_core_count": cpu_count_physical_cores,
            "threads_per_core": threads_per_core,
            "socket_ids": sorted(sockets_seen),
            "socket_count": len(sockets_seen) if sockets_seen else None,
            "cpus": cpu_topology,
        },
        "unknowns": sorted(set(unknowns)),
    }
    return inventory


def _pairwise_distances(inv: Dict[str, Any], node_ids: Sequence[int]) -> Dict[str, Any]:
    dist = inv.get("distance", {})
    ordered = list(dist.get("ordered_node_ids") or [])
    matrix = dist.get("matrix") or []
    idx = {nid: i for i, nid in enumerate(ordered)}
    pairs = {}
    complete = bool(dist.get("complete")) and all(n in idx for n in node_ids)
    for i, a in enumerate(node_ids):
        for b in node_ids[i + 1:]:
            if not complete:
                pairs["%d-%d" % (a, b)] = None
            else:
                pairs["%d-%d" % (a, b)] = matrix[idx[a]][idx[b]]
    return {"complete": complete, "pairs": pairs}


def _mapping_spans_sockets(inv: Dict[str, Any], node_ids: Sequence[int]) -> Optional[bool]:
    sockets = set()
    for nid in node_ids:
        nd = (inv.get("nodes") or {}).get(nid)
        if not nd:
            return None
        if not nd.get("socket_ids_known") or nd.get("socket_ambiguous"):
            return None
        sockets.add(nd.get("socket_id"))
    if not sockets:
        return None
    return len(sockets) > 1


def _group_by_socket(inv: Dict[str, Any], usable_nodes: Sequence[int]) -> Tuple[Optional[Dict[int, List[int]]], Optional[str]]:
    groups: Dict[int, List[int]] = {}
    for nid in usable_nodes:
        nd = (inv.get("nodes") or {}).get(nid)
        if not nd or not nd.get("socket_ids_known") or nd.get("socket_ambiguous"):
            return None, "node %d has unknown/ambiguous socket membership" % nid
        sid = nd.get("socket_id")
        groups.setdefault(int(sid), []).append(int(nid))
    for sid in groups:
        groups[sid] = sorted(groups[sid])
    return dict(sorted(groups.items())), None


def _spread_across_sockets(socket_groups: Dict[int, List[int]], count: int) -> Optional[List[int]]:
    """Deterministic cross-socket spread: maximize sockets used, balance counts."""
    if count <= 0:
        return []
    sockets = sorted(socket_groups.keys())
    available = sum(len(socket_groups[s]) for s in sockets)
    if count > available:
        return None
    # Prefer using as many sockets as possible for the requested count.
    # Assign 1 per socket in round-robin over sockets (sorted) while possible,
    # which maximizes spread; continue round-robin for remaining slots.
    offsets = {s: 0 for s in sockets}
    chosen: List[int] = []
    # First pass: try to touch every socket if count >= number of sockets.
    order = list(sockets)
    # Round-robin by socket order, picking next available node on that socket.
    progressed = True
    while len(chosen) < count and progressed:
        progressed = False
        for s in order:
            if len(chosen) >= count:
                break
            if offsets[s] < len(socket_groups[s]):
                chosen.append(socket_groups[s][offsets[s]])
                offsets[s] += 1
                progressed = True
    if len(chosen) != count:
        return None
    # Keep deterministic logical order by socket distribution? Preserve pick order
    # grouped by socket would be confusing; better return in a stable order that
    # reflects spread: interleaved by socket assignment order is fine/deterministic.
    return chosen


def select_mapping_profiles(
    inv: Dict[str, Any],
    logical_node_count: int,
    usable_nodes: Sequence[int],
    requested_profiles: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Return concrete mapping variants for requested profiles.

    Each result: {profile, variant, logical_to_physical, supported, reason,
    spans_sockets, node_to_socket, pairwise_distances, ...}
    Unsupported profiles are returned with supported=False (never substituted).
    """
    if requested_profiles is None:
        requested_profiles = ["cross_socket_spread", "intra_socket", "all_nodes"]
    usable = [int(n) for n in usable_nodes]
    results: List[Dict[str, Any]] = []

    def _base(profile: str, variant: Optional[str] = None):
        return {
            "profile": profile,
            "variant": variant,
            "logical_node_count": logical_node_count,
            "logical_to_physical": [],
            "supported": False,
            "reason": None,
        }

    for profile in requested_profiles:
        if profile == "explicit":
            # explicit is resolved elsewhere with user-supplied mapping
            r = _base("explicit", "explicit")
            r["reason"] = "explicit profile requires user-supplied mapping"
            results.append(r)
            continue

        if profile == "all_nodes":
            r = _base("all_nodes", "all_nodes")
            if logical_node_count != len(usable):
                r["reason"] = "all_nodes requires logical_node_count == usable_node_count (%d != %d)" % (logical_node_count, len(usable))
            elif logical_node_count < 1:
                r["reason"] = "all_nodes requires logical_node_count >= 1"
            else:
                r["supported"] = True
                r["logical_to_physical"] = list(usable)
            results.append(r)
            continue

        if profile == "cross_socket_spread":
            r = _base("cross_socket_spread", "cross_socket_spread")
            groups, gerr = _group_by_socket(inv, usable)
            if gerr:
                r["reason"] = "cannot compute cross_socket_spread: %s" % gerr
            elif logical_node_count < 1:
                r["reason"] = "logical_node_count must be >= 1"
            elif logical_node_count > len(usable):
                r["reason"] = "insufficient usable nodes (%d < %d)" % (len(usable), logical_node_count)
            else:
                chosen = _spread_across_sockets(groups or {}, logical_node_count)
                if chosen is None:
                    r["reason"] = "cannot spread %d nodes across available sockets" % logical_node_count
                else:
                    r["supported"] = True
                    r["logical_to_physical"] = chosen
            results.append(r)
            continue

        if profile == "intra_socket":
            groups, gerr = _group_by_socket(inv, usable)
            if gerr:
                results.append({**_base("intra_socket", "intra_socket"), "reason": "cannot compute intra_socket: %s" % gerr})
                continue
            if logical_node_count < 2:
                results.append({**_base("intra_socket", "intra_socket"), "reason": "intra_socket requires logical_node_count >= 2"})
                continue
            any_supported = False
            for sid in sorted((groups or {}).keys()):
                nodes_on = groups[sid]
                variant = "intra_socket:socket%d" % sid
                r = _base("intra_socket", variant)
                r["socket_id"] = sid
                if len(nodes_on) < logical_node_count:
                    r["reason"] = "socket %d has %d usable node(s), need %d" % (sid, len(nodes_on), logical_node_count)
                else:
                    r["supported"] = True
                    r["logical_to_physical"] = list(nodes_on[:logical_node_count])
                    any_supported = True
                results.append(r)
            if not (groups or {}):
                results.append({**_base("intra_socket", "intra_socket"), "reason": "no socket groups available"})
            elif not any_supported and not any(x.get("profile") == "intra_socket" for x in results):
                # shouldn't happen, but keep explicit
                results.append({**_base("intra_socket", "intra_socket"), "reason": "no socket has enough usable nodes"})
            continue

        results.append({**_base(profile, profile), "reason": "unknown mapping profile: %s" % profile})

    # Enrich supported mappings with provenance facts.
    for r in results:
        phys = r.get("logical_to_physical") or []
        if r.get("supported") and phys:
            r["spans_sockets"] = _mapping_spans_sockets(inv, phys)
            r["node_to_socket"] = {nid: (inv.get("nodes") or {}).get(nid, {}).get("socket_id") for nid in phys}
            r["pairwise_distances"] = _pairwise_distances(inv, phys)
        else:
            r["spans_sockets"] = None
            r["node_to_socket"] = {}
            r["pairwise_distances"] = {"complete": False, "pairs": {}}
    return results


def mapping_case_id_component(profile: str, variant: Optional[str], logical_to_physical: Sequence[int]) -> str:
    """Stable mapping identity component for case identity/reporting."""
    phys = ",".join(str(int(x)) for x in logical_to_physical)
    base = variant or profile or "mapping"
    # sanitize for filenames/case ids
    safe = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(base))
    return "%s[%s]" % (safe, phys)


def build_mapping_provenance(
    inv: Dict[str, Any],
    profile: str,
    variant: Optional[str],
    logical_to_physical: Sequence[int],
    per_node_cpus: Sequence[Sequence[int]],
    no_pin: bool,
    resolved_topology_info: Optional[Dict[str, Any]] = None,
    affinity_valid: Any = None,
) -> Dict[str, Any]:
    """Per-trial mapping provenance (checkpoint 1 contract)."""
    phys = [int(x) for x in logical_to_physical]
    node_sock = {}
    node_cpu_info = {}
    for i, nid in enumerate(phys):
        nd = (inv.get("nodes") or {}).get(nid, {})
        allowed_eff = nd.get("effective_allowed_cpus")
        if allowed_eff is None and nd.get("cpus_known") and (inv.get("effective_process_cpuset") or {}).get("cpus_allowed_list_known"):
            # best-effort derivation when not precomputed
            allowed_set = set((inv.get("effective_process_cpuset") or {}).get("cpus_allowed_list") or [])
            if nd.get("cpus"):
                allowed_eff = [c for c in nd.get("cpus") if c in allowed_set]
        node_sock[nid] = {
            "socket_id": nd.get("socket_id"),
            "socket_ids": nd.get("socket_ids"),
            "known": bool(nd.get("socket_ids_known") and not nd.get("socket_ambiguous")),
            "ambiguous": bool(nd.get("socket_ambiguous")),
        }
        node_cpu_info[str(nid)] = {
            "logical_node_index": i,
            "physical_node": nid,
            "node_cpus": nd.get("cpus") if nd.get("cpus_known") else None,
            "node_cpus_known": bool(nd.get("cpus_known")),
            "effective_allowed_cpus": allowed_eff,
            "effective_allowed_cpus_known": bool(nd.get("effective_allowed_cpus_known") or (allowed_eff is not None)),
            "selected_cpus_for_pinning": list(per_node_cpus[i]) if i < len(per_node_cpus) else [],
            "pinning_requested": not bool(no_pin),
        }
    tinfo = resolved_topology_info or {}
    topo_unknowns = list(tinfo.get("topology_unknowns") or inv.get("unknowns") or [])
    return {
        "mapping_profile": profile,
        "mapping_variant": variant,
        "logical_to_physical": phys,
        "logical_to_physical_map": {str(i): nid for i, nid in enumerate(phys)},
        "numa_node_to_socket": node_sock,
        "per_node_cpu_lists": node_cpu_info,
        "pairwise_numa_distances": _pairwise_distances(inv, phys),
        "spans_sockets": _mapping_spans_sockets(inv, phys),
        "all_requested_affinity_roles_verified": affinity_valid,  # populated/updated by caller when known
        "topology_facts_unavailable": sorted(set(topo_unknowns)),
        "topology_unknowns": sorted(set(topo_unknowns)),
        "inventory_unknowns": list(inv.get("unknowns") or []),
        "no_pin": bool(no_pin),
    }
