#!/usr/bin/env python3
"""Environment/topology drift detection (master WO 7.2).

Compares two env_capture.py manifests (before/after) and flags changes in
the fields the master WO lists as drift-relevant:

- Kernel and command line
- NUMA node inventory
- Node-to-socket mapping
- Distance matrix
- Allowed CPU/memory sets
- CPU governor/frequency configuration
- THP settings
- NUMA balancing
- Cgroup CPU/memory limits
- Input storage identity

Design (single authoritative decision):
- `_drifts_from(before, after)` is the single authoritative drift decision.
  It compares manifest fields and returns drift records
  ({field, label, critical, before, after}).
- `summarize(drifts)` gives the campaign-level verdict
  ({critical, noncritical, campaign_valid}).
- `main()` writes a machine-readable drift report and exits non-zero when
  any critical drift is present (campaign invalidation).

Critical drift must invalidate the campaign (the affected performance
comparisons are not silently aggregated under different system
configurations). Non-critical drift (e.g. input missing at before, present
at after — corpus generation timing) is recorded but does not invalidate.

Raw manifests are preserved by env_capture; this module preserves the
machine-readable drift report.
"""

import argparse
import json
import os
import sys


def _get(m, *keys):
    d = m
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _fmt(v):
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True)
    return v


# (manifest path tuple, label, critical, note). All master-WO 7.2 fields are
# treated as critical unless explicitly marked otherwise.
_DRIFT_FIELDS = [
    # Kernel and command line.
    (("kernel", "cmdline"), "kernel cmdline", True,
     "kernel command line (affects all measurements)"),
    # NUMA node inventory.
    (("cpu_topology", "node_online_list"), "NUMA node inventory (online list)", True,
     "online NUMA node set changed"),
    (("cpu_topology", "nodes"), "NUMA node inventory (per-node)", True,
     "NUMA node inventory (cpulist/cpumap/meminfo/numastat) changed"),
    (("cpu_topology", "cpus"), "CPU inventory (lscpu -p)", True,
     "CPU inventory changed"),
    # Node-to-socket mapping.
    (("cpu_extra", "node_to_socket"), "node-to-socket mapping", True,
     "node-to-socket mapping changed"),
    # Distance matrix.
    (("cpu_extra", "node_distances"), "distance matrix", True,
     "NUMA distance matrix changed"),
    # Allowed CPU/memory sets.
    (("process", "affinity"), "allowed CPUs (process affinity)", True,
     "allowed CPU set changed"),
    (("process", "mems_allowed_list"), "allowed memory nodes", True,
     "allowed memory-node set changed"),
    # CPU governor/frequency configuration.
    (("cpu_extra", "governors"), "CPU governor configuration", True,
     "CPU governor changed"),
    (("cpu_extra", "lscpu_key"), "CPU model/frequency (lscpu)", True,
     "CPU model/frequency attributes changed"),
    # THP settings.
    (("thp", "enabled"), "THP enabled", True,
     "transparent-hugepage 'enabled' state changed"),
    (("thp", "shmem_enabled"), "THP shmem state", True,
     "transparent-hugepage shmem state changed"),
    (("thp", "defrag"), "THP defrag state", True,
     "transparent-hugepage defrag state changed"),
    # NUMA balancing and scan delay (master WO 7.1/7.2).
    (("cpu_extra", "numa_balancing"), "NUMA balancing", True,
     "kernel.numa_balancing changed"),
    (("cpu_extra", "numa_scan_delay"), "NUMA scan delay setting", True,
     "kernel.numa_scan_delay changed"),
    # Cgroup CPU/memory limits.
    (("cgroup", "cpuset_cpus"), "cgroup cpuset cpus", True,
     "cgroup CPU set changed"),
    (("cgroup", "cpuset_mems"), "cgroup cpuset memory nodes", True,
     "cgroup memory-node set changed"),
    (("cgroup", "cpu_max"), "cgroup CPU limit", True,
     "cgroup cpu.max changed"),
    (("cgroup", "memory_max"), "cgroup memory limit", True,
     "cgroup memory.max changed"),
    # Input storage identity.
    (("storage_details", "input_realpath"), "input storage identity (realpath)", True,
     "campaign input file identity changed"),
    (("storage_details", "input_device"), "input storage identity (device)", True,
     "campaign input device id changed"),
    (("storage_details", "input_size_bytes"), "input storage identity (size)", True,
     "campaign input size changed"),
    (("storage_details", "input_mtime"), "input storage identity (mtime)", True,
     "campaign input mtime changed"),
    # Informational: missing->present transitions for the input file.
    (("storage_details", "input_missing"), "input availability during campaign", False,
     "input storage availability changed between captures (campaign setup timing)"),
]


def _meminfo_capacity(meminfo):
    """Extract configuration-relevant meminfo lines (capacity, not
    volatile runtime telemetry: MemFree/MemUsed/Active/Inactive...)."""
    if not isinstance(meminfo, str):
        return meminfo
    keep = []
    for line in meminfo.splitlines():
        s = line.strip()
        if s.startswith("Node") and "MemTotal:" in s:
            keep.append(s)
        elif s.startswith("HugePages_"):
            keep.append(s)
    return "\n".join(keep)


def _normalize_value(field_path, value):
    """Normalize a manifest value for comparison (volatile fields excluded)."""
    if field_path == "cpu_topology.nodes" and isinstance(value, dict):
        out = {}
        for name, node in value.items():
            if isinstance(node, dict):
                n = dict(node)
                # Free/used/active memory and runtime counters change
                # during every campaign; compare capacity only.
                n["meminfo"] = _meminfo_capacity(n.get("meminfo"))
                n.pop("numastat", None)
                out[name] = n
        return out
    return value


def _drift_changed(keys, b, a):
    """Did field `keys` change between before/after? Authoritative check."""
    if b == a:
        return False
    if keys[-1] == "input_missing":
        # Missing->present (or present->missing): the corpus is generated
        # after env-before, so this transition is campaign setup timing,
        # not performance-affecting drift. Informational only.
        return True
    if b is None or a is None:
        # Not comparable (absent on one side): no drift.
        return False
    return True


def _drifts_from(before, after):
    """AUTHORITATIVE drift decision: changed fields between two env manifests.

    Returns a list of drift records sorted by field path:
    {"field", "label", "critical", "before", "after", "note"}.
    """
    drifts = []
    for keys, label, critical, note in _DRIFT_FIELDS:
        b = _normalize_value(".".join(keys), _get(before, *keys))
        a = _normalize_value(".".join(keys), _get(after, *keys))
        if not _drift_changed(keys, b, a):
            continue
        drifts.append({
            "field": ".".join(keys),
            "label": label,
            "critical": bool(critical),
            "before": _fmt(b),
            "after": _fmt(a),
            "note": note,
        })
    return drifts


def summarize(drifts):
    """Campaign-level verdict from the authoritative drift decision."""
    critical = [d for d in drifts if d.get("critical")]
    noncritical = [d for d in drifts if not d.get("critical")]
    return {
        "critical": critical,
        "noncritical": noncritical,
        "campaign_valid": not critical,
        "drift_count": len(drifts),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", required=True, help="env-before.json path")
    ap.add_argument("--after", required=True, help="env-after.json path")
    ap.add_argument("--out", required=True, help="drift-report.json path")
    args = ap.parse_args()
    with open(args.before, encoding="utf-8") as fh:
        before = json.load(fh)
    with open(args.after, encoding="utf-8") as fh:
        after = json.load(fh)
    drifts = _drifts_from(before, after)
    summary = summarize(drifts)
    report = {
        "schema": "stage0-drift/1",
        "before_manifest": os.path.abspath(args.before),
        "after_manifest": os.path.abspath(args.after),
        "drifts": drifts,
        "critical_drift_count": len(summary["critical"]),
        "noncritical_drift_count": len(summary["noncritical"]),
        "campaign_valid": summary["campaign_valid"],
    }
    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    print("drift report: %s (critical=%d, valid=%s)" % (
        args.out, report["critical_drift_count"], report["campaign_valid"]))
    return 0 if report["campaign_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
