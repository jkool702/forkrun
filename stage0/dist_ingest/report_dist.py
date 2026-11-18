#!/usr/bin/env python3
"""Comparative report for distributed-ingest prototype campaign.

Reads campaign-manifest.json + per-trial manifests under a campaign dir and
produces a Markdown comparison. Marks invalid/incomplete/inconclusive trials
explicitly. Separates validity dimensions. Does not claim real NUMA performance.
"""

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fmt(x, digits=3):
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, float):
        return ("%.*f" % (digits, x))
    return str(x)


def safe_get(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def fmt_tri(v):
    """Format tri-state (True/False/None) distinctly."""
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "unknown"
    return str(v)


def safe_validity(dr, key, fallback_key=None):
    v = (dr or {}).get("validity", {})
    if key in v:
        return v.get(key)
    if fallback_key and fallback_key in v:
        return v.get(fallback_key)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", required=True, help="campaign directory")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    camp = load_json(os.path.join(args.campaign, "campaign-manifest.json"))
    outcomes = camp.get("outcomes", [])

    groups = defaultdict(list)
    invalid = []
    for o in outcomes:
        scen = o.get("scenario") or o.get("case", "").split("__")[0]
        cand = o.get("candidate") or (o.get("case", "").split("__")[-1] if "__" in o.get("case", "") else "unknown")
        mpath = os.path.join(args.campaign, o.get("manifest", ""))
        rec = {"scenario": scen, "candidate": cand, "trial": o.get("trial"), "status": o.get("status"),
               "manifest_path": mpath, "invalid": False}

        def mark_invalid(reason):
            rec["invalid"] = True
            rec.setdefault("invalid_reasons", []).append(reason)
            invalid.append(rec)

        if o.get("status") != "ok" or not os.path.isfile(mpath):
            mark_invalid("trial status %s or missing manifest" % o.get("status"))
            groups[(scen, cand)].append(rec)
            continue

        try:
            m = load_json(mpath)
        except Exception as e:
            mark_invalid("manifest unreadable: %s" % e)
            groups[(scen, cand)].append(rec)
            continue

        rec["manifest"] = m
        rec["complete"] = bool(m.get("complete", False))
        rec["incomplete_reasons_manifest"] = m.get("incomplete_reasons", [])
        rec["wall_s_harness"] = m.get("wall_s")
        rec["map_s"] = m.get("map_s")
        cr = m.get("child_report") or {}
        rec["bytes"] = cr.get("completed_bytes")
        rec["rec_per_s"] = cr.get("rec_per_s")
        dr = m.get("dist_result")
        if dr:
            rec["dist"] = dr
            rec["is_dist_engine"] = True
            # Dist-engine authoritative wall time is DIST_RESULT.wall_seconds.
            rec["engine_wall_s"] = dr.get("wall_seconds")
            rec["harness_wall_s"] = m.get("wall_s")
            rec["correct_functional"] = bool(dr.get("correct"))
            rec["throughput_bps"] = (dr.get("total_consumed", 0) / dr.get("wall_seconds", 1e9)) if dr.get("wall_seconds") else None
            rec["reservations"] = dr.get("reservations_total")
            rec["ingest_cpu_ns"] = dr.get("ingest_cpu_ns")
            rec["consumer_kernel"] = safe_get(dr, "consumer_kernel", "name", default=(safe_get(dr, "comparability", "consumer_kernel")))
            scan_ev = safe_get(dr, "consumer_kernel", "scan_bytes_evidence", default={}) or {}
            rec["scan_bytes"] = scan_ev.get("total_consumer_bytes_scanned", dr.get("total_consumer_bytes_scanned"))
            rec["scan_equals_consumed"] = scan_ev.get("scan_equals_consumed")
            rec["v_functional"] = safe_validity(dr, "functional_correctness", "functional_correct")
            rec["v_perf"] = safe_validity(dr, "performance_measurement")
            rec["v_affinity"] = safe_validity(dr, "affinity", "affinity_valid")
            rec["v_mempolicy"] = safe_validity(dr, "memory_policy_application", "placement_policy_valid")
            rec["v_placement_obs"] = safe_validity(dr, "placement_observed", "placement_observed_all_sampled_on_target")
            rec["v_numa_placement"] = safe_validity(dr, "numa_placement")
        else:
            rec["dist"] = None
            rec["is_dist_engine"] = False
            rec["engine_wall_s"] = rec.get("map_s") or rec.get("wall_s_harness")
            rec["harness_wall_s"] = m.get("wall_s")
            rec["correct_functional"] = bool(rec.get("complete", False))
            b = rec.get("bytes") or 0
            ws = rec.get("map_s") or rec.get("wall_s_harness") or 0
            rec["throughput_bps"] = (b / ws) if ws else None
            rec["ingest_cpu_sec"] = m.get("ingest_cpu_sec")
            rec["v_functional"] = rec.get("complete", False)
            rec["v_perf"] = None
            rec["v_affinity"] = None
            rec["v_mempolicy"] = None
            rec["v_placement_obs"] = None
            rec["v_numa_placement"] = None

        if not rec.get("complete", False):
            mark_invalid("incomplete: %s" % rec.get("incomplete_reasons_manifest"))

        groups[(scen, cand)].append(rec)

    lines = []
    lines.append("# Distributed Ingestion Prototype — Comparative Campaign Report")
    lines.append("")
    lines.append("**Campaign:** `%s`  " % camp.get("campaign_id"))
    lines.append("**Source SHA:** `%s`  " % camp.get("source_sha"))
    lines.append("**Schema:** `%s`  " % camp.get("schema"))
    lines.append("**All trials OK:** %s" % camp.get("all_ok"))
    ccfg = camp.get("campaign_config") or {}
    if ccfg:
        lines.append("**Consumer kernel (campaign):** %s  " % ccfg.get("consumer_kernel"))
        lines.append("**Strict affinity (campaign):** %s  " % ccfg.get("strict_affinity"))
        lines.append("**Strict mbind (campaign):** %s  " % ccfg.get("strict_mbind"))
        if ccfg.get("phys_nodes"):
            lines.append("**Explicit phys nodes (campaign):** %s  " % ccfg.get("phys_nodes"))
    lines.append("")
    lines.append("> NOTE (Section 5 comparability): Dist-engine candidates "
                 "(`centralized_ingest`, `fixed_faa`, `local_adaptive`, `relative_adaptive`) run on the "
                 "SAME experimental engine, consumer implementation, work units, and measurement boundaries "
                 "and are the apples-to-apples comparison set for ingestion architecture. "
                 "Dist-engine authoritative wall time is `DIST_RESULT.wall_seconds` (harness/manifest duration separate). "
                 "`production_ref`/forkrun results, if present, use a different execution model and are "
                 "**reference only** (not apples-to-apples with dist_ingest). Fake/local NUMA results are "
                 "NOT evidence of real NUMA scalability or memory locality.")
    lines.append("")
    lines.append("> Validity dimensions are separate: functional correctness, performance-measurement, affinity, "
                 "memory-policy application, observed placement, and overall NUMA-placement. "
                 "`unknown` is distinct from `false`. `manifest.complete`/functional correctness is not all-validity.")
    lines.append("")

    scenarios = sorted({s for s, c in groups.keys()})
    candidates = ["centralized_ingest", "fixed_faa", "local_adaptive", "relative_adaptive", "production_ref", "control"]

    lines.append("## Comparative summary (median of functionally-correct complete trials)")
    lines.append("")
    header = ("| scenario | candidate | valid/total | func ok | perf valid | numa-place valid | "
              "throughput (MB/s) | engine wall s | harness wall s | reservations | kernel | scanned/consumed | notes |")
    sep = "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|"
    lines.append(header); lines.append(sep)
    for scen in scenarios:
        for cand in candidates:
            recs = groups.get((scen, cand), [])
            if not recs:
                continue
            total = len(recs)
            # "valid" for this summary: attempted trial that is complete, readable, and functionally correct
            func_valids = [r for r in recs if (not r.get("invalid")) and r.get("correct_functional") is True and r.get("complete") is True]

            def med(key, src=func_valids):
                vals = [r.get(key) for r in src if r.get(key) is not None]
                return statistics.median(vals) if vals else None

            thr = med("throughput_bps")
            thr_mb = (thr / 1e6) if thr else None
            wall = med("engine_wall_s")
            hwall = med("harness_wall_s")
            resv = med("reservations")
            kernels = sorted({str(r.get("consumer_kernel")) for r in func_valids if r.get("consumer_kernel") is not None})
            kernel = ",".join(kernels) if kernels else "n/a"
            scan_vals = [r.get("scan_bytes") for r in func_valids if r.get("scan_bytes") is not None]
            cons_vals = [((r.get("dist") or {}).get("total_consumed")) for r in func_valids if r.get("dist")]
            scan_s = "n/a"
            if scan_vals and cons_vals:
                scan_s = "%s/%s" % (int(statistics.median([v for v in scan_vals if v is not None])) if scan_vals else "n/a",
                                    int(statistics.median([v for v in cons_vals if v is not None])) if cons_vals else "n/a")
            perf_true = sum(1 for r in func_valids if r.get("v_perf") is True)
            numa_true = sum(1 for r in func_valids if r.get("v_numa_placement") is True)
            notes = []
            bad = total - len([r for r in recs if not r.get("invalid")])
            if bad:
                notes.append("failed/invalid/incomplete=%d" % bad)
            if len(func_valids) == 0:
                notes.append("NO FUNCTIONALLY-VALID TRIALS")
            lines.append("| %s | %s | %d/%d | %d/%d | %d/%d | %d/%d | %s | %s | %s | %s | %s | %s | %s |" % (
                scen, cand, len(func_valids), total, len(func_valids), total, perf_true, len(func_valids),
                numa_true, len(func_valids), fmt(thr_mb), fmt(wall), fmt(hwall), fmt(resv, 0), kernel, scan_s, "; ".join(notes)))
    lines.append("")

    lines.append("## Dist-candidate validity and workload evidence (per trial)")
    lines.append("")
    for scen in scenarios:
        for cand in candidates:
            if cand in ("control", "production_ref"):
                continue
            recs = groups.get((scen, cand), [])
            if not recs:
                continue
            lines.append("### %s / %s (attempted=%d)" % (scen, cand, len(recs)))
            lines.append("")
            for r in recs:
                dr = r.get("dist")
                if not dr:
                    lines.append("- trial %s: invalid=%s reasons=%s" % (r.get("trial"), r.get("invalid"), r.get("invalid_reasons")))
                    continue
                lines.append("- trial %s: complete=%s invalid=%s kernel=%s scanned=%s consumed=%s scan_ok=%s "
                             "engine_wall=%.6fs harness_wall=%s valid[func=%s perf=%s affinity=%s mempolicy=%s placement_obs=%s numa=%s] "
                             "correct=%s overlap=%s lost=%s dup=%s reservations=%s rc=%s" % (
                    r.get("trial"), r.get("complete"), r.get("invalid"),
                    r.get("consumer_kernel"), r.get("scan_bytes"), dr.get("total_consumed"), fmt_tri(r.get("scan_equals_consumed")),
                    float(dr.get("wall_seconds") or 0.0), fmt(r.get("harness_wall_s")),
                    fmt_tri(r.get("v_functional")), fmt_tri(r.get("v_perf")), fmt_tri(r.get("v_affinity")),
                    fmt_tri(r.get("v_mempolicy")), fmt_tri(r.get("v_placement_obs")), fmt_tri(r.get("v_numa_placement")),
                    dr.get("correct"), dr.get("overlap_detected"), dr.get("lost_detected"), dr.get("duplicate_detected"),
                    dr.get("reservations_total"), dr.get("rc")))
                for n in dr.get("nodes", []):
                    pl = n.get("placement", {})
                    mp = n.get("memory_policy", {})
                    aff = n.get("affinity", {})
                    ing = aff.get("ingestor", {})
                    con = aff.get("consumer", {})
                    lines.append(
                        "  - node %d: scanned=%s consumed=%s pub=%s max_eff=%s "
                        "aff[ing req=%s app=%s ok=%s matched=%s applicable=%s | con req=%s app=%s ok=%s matched=%s] "
                        "mbind[req_c=%s ok_c=%s fail_c=%s err=%s all_ok=%s] "
                        "place[target=%s other=%s unknown=%s sampled=%s]" % (
                            n.get("node"), n.get("consumer_bytes_scanned"), n.get("bytes_consumed"),
                            n.get("bytes_published"), n.get("max_effective_backlog"),
                            ing.get("requested"), ing.get("set_applied"), ing.get("query_succeeded"), ing.get("matched"), ing.get("applicable"),
                            con.get("requested"), con.get("set_applied"), con.get("query_succeeded"), con.get("matched"),
                            mp.get("requested_count"), mp.get("success_count"), mp.get("failure_count"), mp.get("error"), mp.get("all_requested_succeeded"),
                            pl.get("local_pages_on_target_node", pl.get("sample_target_match_pages")),
                            pl.get("remote_pages_other_node", pl.get("sample_other_node_pages")),
                            pl.get("unknown_pages", pl.get("sample_unknown_pages")),
                            pl.get("sampled_pages")))
                if r.get("invalid_reasons"):
                    lines.append("  - invalid reasons: %s" % r.get("invalid_reasons"))
            lines.append("")

    lines.append("## Invalid / incomplete / failed / unreadable / missing trials")
    lines.append("")
    if not invalid:
        lines.append("None.")
    else:
        for r in invalid:
            reasons = r.get("invalid_reasons") or [r.get("invalid_reason", "invalid")]
            lines.append("- %s / %s trial %s: %s (%s)" % (
                r.get("scenario"), r.get("candidate"), r.get("trial"),
                "; ".join([str(x) for x in reasons]), r.get("manifest_path")))
    lines.append("")

    lines.append("## Interpretation notes")
    lines.append("")
    lines.append("- **Correctness first:** overlap/loss/dup or incorrect totals invalidate functional correctness.")
    lines.append("- **Comparable set:** centralized_ingest vs fixed_faa/local_adaptive/relative_adaptive share the same dist_ingest engine, consumers, work units, measurement boundaries, and (per block) consumer kernel/params.")
    lines.append("- **Timing:** dist-engine comparative wall time is `DIST_RESULT.wall_seconds`; harness duration is separate/diagnostic.")
    lines.append("- **Validity separation:** a trial may be functionally correct but have unknown/false placement; do not promote failed/unknown NUMA evidence to success. `unknown` != `false`.")
    lines.append("- **Production reference:** production_ref/control is separate reference only (not apples-to-apples).")
    lines.append("- **Fake/local NUMA:** not evidence of physical locality/scalability. `MPOL_PREFERRED` success is not physical placement proof.")
    lines.append("")

    verdict = "INCONCLUSIVE (local/fake-NUMA prototype campaign)"
    if not camp.get("all_ok"):
        verdict = "INCONCLUSIVE — campaign has failures/invalid trials"
    lines.append("**Overall verdict (local):** %s" % verdict)
    lines.append("")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
