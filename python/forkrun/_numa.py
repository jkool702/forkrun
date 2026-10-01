"""NUMA topology detection, CPU pinning, worker distribution (W-PY21).

Reads the system's NUMA topology from /sys and builds the
logical-to-physical node mapping the engine consumes via
--numa-map. Pure frontend: no engine changes.

Accepted nodes= forms (run/map/stream):
  None / "auto": all online nodes (single-socket → UMA, unchanged)
  1 / "1":      force UMA (single ring, current behavior)
  N (int>1):    first N online physical nodes
  "N":          same as int N
  "0,1,2":      explicit online physical node list
  "@N":         N logical nodes cycling through online physicals
                (fake multi-node on single-socket, like bash @N)

Pinning mirrors the engine's pin_to_numa_node (sched_setaffinity to
the physical node's cpulist, best-effort). The shim's
fr_py_worker_init pins workers itself via the same rule; this
module's pin_to_node covers pipeline children and tests.
"""

from __future__ import annotations

import os

# Engine meta_ring ceiling: --nodes=@N above 512 is rejected by init.
MAX_LOGICAL_NODES = 512


def _parse_id_list(raw):
    """Parse a Linux cpulist/nodelist ("0-3,8,10-11") into [ints]."""
    out = []
    for part in raw.strip().split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, _, end_s = part.partition("-")
            try:
                start, end = int(start_s), int(end_s)
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


def detect_numa_nodes():
    """Online physical NUMA node IDs (e.g. [0, 1]). [0] when unknown."""
    try:
        with open("/sys/devices/system/node/online") as fh:
            raw = fh.read()
    except OSError:
        return [0]
    nodes = _parse_id_list(raw)
    return nodes or [0]


def get_node_cpus(node_id):
    """CPU IDs for one physical node ([] when unknown)."""
    path = "/sys/devices/system/node/node%d/cpulist" % (node_id,)
    try:
        with open(path) as fh:
            raw = fh.read()
    except OSError:
        return []
    return _parse_id_list(raw)


def build_numa_map(nodes_spec):
    """Resolve nodes= into (numa_map_str, num_nodes, node_cpus).

    numa_map_str: comma-separated physical IDs for --numa-map
      ("" when UMA — the caller then skips the flag entirely).
    num_nodes: logical node count (1 = UMA).
    node_cpus: per-logical-node CPU lists (physical cpulists;
      possibly shared/empty on fake topologies — pinning is
      best-effort and never gates correctness).
    Raises ValueError on malformed/unknown specs.
    """
    if nodes_spec is None or nodes_spec == "auto":
        online = detect_numa_nodes()
        if len(online) <= 1:
            return "", 1, [get_node_cpus(online[0])]
        return (",".join(str(n) for n in online), len(online),
                [get_node_cpus(n) for n in online])
    if isinstance(nodes_spec, bool):
        raise ValueError(
            "nodes must be 'auto'/1/N/'0,1'/'@N', got %r" % (nodes_spec,))
    if isinstance(nodes_spec, int):
        if nodes_spec < 1:
            raise ValueError(
                "nodes must be >= 1, got %r" % (nodes_spec,))
        if nodes_spec == 1:
            return "", 1, [get_node_cpus(detect_numa_nodes()[0])]
        online = detect_numa_nodes()
        if nodes_spec > MAX_LOGICAL_NODES:
            raise ValueError(
                "nodes above %d is not supported (meta_ring "
                "capacity); got %r" % (MAX_LOGICAL_NODES, nodes_spec))
        # First N online physicals; fewer online than asked is a
        # loud error (silently running UMA after nodes=4 was
        # requested would be a benchmarking lie).
        if nodes_spec > len(online):
            raise ValueError(
                "nodes=%d requested but only %d NUMA node(s) online "
                "(%s) — use '@%d' to force logical nodes for testing"
                % (nodes_spec, len(online), online, nodes_spec))
        picked = online[:nodes_spec]
        return (",".join(str(n) for n in picked), len(picked),
                [get_node_cpus(n) for n in picked])
    if isinstance(nodes_spec, str):
        s = nodes_spec.strip()
        if s.startswith("@"):
            try:
                n = int(s[1:])
            except ValueError:
                raise ValueError(
                    "nodes '@N' needs an integer N, got %r"
                    % (nodes_spec,))
            if n < 1 or n > MAX_LOGICAL_NODES:
                raise ValueError(
                    "nodes '@N' needs 1 <= N <= %d, got %r"
                    % (MAX_LOGICAL_NODES, nodes_spec))
            if n == 1:
                return "", 1, [get_node_cpus(
                    detect_numa_nodes()[0])]
            online = detect_numa_nodes()
            picked = [online[i % len(online)] for i in range(n)]
            return (",".join(str(x) for x in picked), n,
                    [get_node_cpus(x) for x in picked])
        if "," in s:
            try:
                picked = [int(x) for x in s.split(",")]
            except ValueError:
                raise ValueError(
                    "nodes explicit list must be physical IDs like "
                    "'0,1', got %r" % (nodes_spec,))
            if not picked:
                raise ValueError(
                    "nodes explicit list is empty: %r" % (nodes_spec,))
            online = detect_numa_nodes()
            for node in picked:
                if node not in online:
                    raise ValueError(
                        "NUMA node %d is not online (online: %s)"
                        % (node, online))
            if len(picked) == 1:
                return "", 1, [get_node_cpus(picked[0])]
            return (",".join(str(x) for x in picked), len(picked),
                    [get_node_cpus(x) for x in picked])
        try:
            return build_numa_map(int(s))
        except ValueError:
            raise ValueError(
                "nodes must be 'auto'/1/N/'0,1'/'@N', got %r"
                % (nodes_spec,))
    raise ValueError(
        "nodes must be 'auto'/1/N/'0,1'/'@N', got %r" % (nodes_spec,))


def pin_to_node(node_cpus):
    """Pin THIS process to a node's CPUs (best-effort).

    Returns True when the affinity stuck, False otherwise (empty
    list, missing syscall, restricted container). Never raises —
    callers treat False as "unpinned, still correct".
    """
    if not node_cpus:
        return False
    try:
        os.sched_setaffinity(0, set(int(c) for c in node_cpus
                                    if int(c) >= 0))
    except (OSError, AttributeError, ValueError, OverflowError):
        return False
    try:
        return bool(set(os.sched_getaffinity(0)) & set(node_cpus))
    except (OSError, AttributeError):
        return True


def distribute_workers(total_workers, num_nodes):
    """Round-robin (node, count) distribution (skips empty nodes)."""
    if total_workers < 1:
        raise ValueError(
            "total_workers must be >= 1, got %r" % (total_workers,))
    if num_nodes <= 1:
        return [(0, total_workers)]
    base, rem = divmod(total_workers, num_nodes)
    return [(node, base + (1 if node < rem else 0))
            for node in range(num_nodes)
            if base + (1 if node < rem else 0) > 0]


def wid_to_node(total_workers, num_nodes):
    """wid → node assignment list (len == total_workers).

    Contiguous per-node blocks with round-robin counts: node n owns
    wids [base(n), base(n)+count(n)). A respawned wid keeps its
    node's output memfd, death pipe lineage, and claim ring, so the
    mapping must be stable for the run — derived once from
    distribute_workers, never recomputed mid-run.
    """
    mapping = []
    for node, count in distribute_workers(total_workers, num_nodes):
        mapping.extend([node] * count)
    return mapping


__all__ = ["MAX_LOGICAL_NODES", "detect_numa_nodes", "get_node_cpus",
           "build_numa_map", "pin_to_node", "distribute_workers",
           "wid_to_node"]
