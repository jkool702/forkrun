#!/usr/bin/env python3
"""Comparative report for distributed-ingest prototype campaign.

Reads campaign-manifest.json + per-trial manifests under a campaign dir and
produces a Markdown comparison of control/fixed_faa/local_adaptive/relative_adaptive.
Marks invalid/incomplete/inconclusive trials explicitly. Does not claim real
NUMA performance.
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


def safe_get(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def fmt(x, digits=3):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return ("%.*f" % (digits, x))
    return str(x)


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
        cand = o.get("candidate") or (o.get("case", "").split("__")[-1] if "__" in o.get("case","") else "unknown")
        mpath = os.path.join(args.campaign, o.get("manifest", ""))
        rec = {"scenario": scen, "candidate": cand, "trial": o.get("trial"), "status": o.get("status"),
               "manifest_path": mpath}
        if o.get("status") != "ok" or not os.path.isfile(mpath):
            rec["invalid"] = True
            rec["invalid_reason"] = "trial status %s or missing manifest" % o.get("status")
            invalid.append(rec)
        else:
            try:
                m = load_json(mpath)
            except Exception as e:
                rec["invalid"] = True
                rec["invalid_reason"] = "manifest unreadable: %s" % e
                invalid.append(rec)
                groups[(scen, cand)].append(rec)
                continue
            rec["manifest"] = m
            rec["complete"] = m.get("complete", False)
            rec["incomplete_reasons"] = m.get("incomplete_reasons", [])
            rec["wall_s"] = m.get("wall_s")
            rec["map_s"] = m.get("map_s")
            cr = m.get("child_report") or {}
            rec["bytes"] = cr.get("completed_bytes")
            rec["rec_per_s"] = cr.get("rec_per_s")
            dr = m.get("dist_result")
            if dr:
                rec["dist"] = dr
                rec["correct"] = dr.get("correct")
                rec["throughput_bps"] = (dr.get("total_consumed", 0) / dr.get("wall_seconds", 1e9)) if dr.get("wall_seconds") else None
                rec["reservations"] = dr.get("reservations_total")
                rec["ingest_cpu_ns"] = dr.get("ingest_cpu_ns")
            else:
                rec["dist"] = None
                rec["correct"] = rec["complete"]
                b = rec["bytes"] or 0
                ws = rec.get("map_s") or rec.get("wall_s") or 0
                rec["throughput_bps"] = (b / ws) if ws else None
                rec["ingest_cpu_sec"] = m.get("ingest_cpu_sec")
            if not rec.get("complete", False):
                rec["invalid"] = True
                rec["invalid_reason"] = "incomplete: %s" % rec.get("incomplete_reasons")
                invalid.append(rec)
        groups[(scen, cand)].append(rec)

    lines = []
    lines.append("# Distributed Ingestion Prototype — Comparative Campaign Report")
    lines.append("")
    lines.append("**Campaign:** `%s`  " % camp.get("campaign_id"))
    lines.append("**Source SHA:** `%s`  " % camp.get("source_sha"))
    lines.append("**Schema:** `%s`  " % camp.get("schema"))
    lines.append("**All trials OK:** %s" % camp.get("all_ok"))
    lines.append("")
    lines.append("> NOTE: This campaign exercises experimental prototypes in an isolated harness. "
                 "Fake/local NUMA results are NOT evidence of real NUMA scalability or memory locality. "
                 "Control (existing forkrun path) and dist-engine candidates are measured through "
                 "different execution models; compare within the stated model and treat cross-model "
                 "comparisons as indicative, not definitive.")
    lines.append("")

    scenarios = sorted({s for s, c in groups.keys()})
    candidates = ["control", "fixed_faa", "local_adaptive", "relative_adaptive"]
    lines.append("## Comparative summary (median of valid trials)")
    lines.append("")
    header = "| scenario | candidate | valid/total | correct | throughput (MB/s) | wall s | reservations | ingest CPU s | notes |"
    sep = "|---|---|---:|---:|---:|---:|---:|---:|---|"
    lines.append(header); lines.append(sep)
    for scen in scenarios:
        for cand in candidates:
            recs = groups.get((scen, cand), [])
            if not recs:
                continue
            valids = [r for r in recs if not r.get("invalid")]
            total = len(recs)
            def med(key):
                vals = [r.get(key) for r in valids if r.get(key) is not None]
                return statistics.median(vals) if vals else None
            thr = med("throughput_bps")
            thr_mb = (thr / 1e6) if thr else None
            wall = med("wall_s") or med("map_s")
            resv = med("reservations")
            cpu_vals = []
            for r in valids:
                if r.get("dist"):
                    if r["dist"].get("ingest_cpu_ns") is not None:
                        cpu_vals.append(r["dist"]["ingest_cpu_ns"] / 1e9)
                elif r.get("ingest_cpu_sec") is not None:
                    cpu_vals.append(r.get("ingest_cpu_sec"))
            cpu = statistics.median(cpu_vals) if cpu_vals else None
            correct_n = sum(1 for r in valids if r.get("correct"))
            notes = []
            if len(valids) != total:
                notes.append("invalid/incomplete present")
            if len(valids) == 0:
                notes.append("NO VALID TRIALS")
            lines.append("| %s | %s | %d/%d | %d/%d | %s | %s | %s | %s | %s |" % (
                scen, cand, len(valids), total, correct_n, len(valids),
                fmt(thr_mb), fmt(wall), fmt(resv, 0), fmt(cpu), "; ".join(notes)))
    lines.append("")

    lines.append("## Dist-candidate details (per valid trial aggregate)")
    lines.append("")
    for scen in scenarios:
        for cand in candidates:
            if cand == "control":
                continue
            recs = [r for r in groups.get((scen,cand),[]) if not r.get("invalid") and r.get("dist")]
            if not recs:
                continue
            lines.append("### %s / %s" % (scen, cand))
            lines.append("")
            for r in recs:
                dr = r["dist"]
                lines.append("- trial %s: correct=%s consumed=%d/%d overlap=%s lost=%s dup=%s wall=%.4fs "
                             "res=%d zero_claims_total=%d" % (
                    r.get("trial"), dr.get("correct"), dr.get("total_consumed",0), dr.get("file_size",0),
                    dr.get("overlap_detected"), dr.get("lost_detected"), dr.get("duplicate_detected"),
                    dr.get("wall_seconds",0), dr.get("reservations_total",0),
                    sum(n.get("zero_claims",0) for n in dr.get("nodes",[]))))
                for n in dr.get("nodes",[]):
                    pl = n.get("placement", {})
                    mp = n.get("memory_policy", {})
                    aff = n.get("affinity", {})
                    lines.append("  - node %d: pub=%d cons=%d max_eff_backlog=%d max_pub_backlog=%d "
                                 "peer_obs=%d target_match_pages=%s other_pages=%s unknown_pages=%s "
                                 "mbind_applied=%s strict_affinity_failed=%s huge_observed_kb=%s err=%s" % (
                        n.get("node"), n.get("bytes_published"), n.get("bytes_consumed"),
                        n.get("max_effective_backlog"), n.get("max_published_backlog"),
                        n.get("peer_observe_count"),
                        pl.get("sample_target_match_pages"), pl.get("sample_other_node_pages"),
                        pl.get("sample_unknown_pages"),
                        mp.get("mbind_policy_applied"), aff.get("strict_affinity_failed"),
                        n.get("hugepage_observed_kb"), n.get("last_error")))
            lines.append("")

    lines.append("## Invalid / incomplete / failed trials")
    lines.append("")
    if not invalid:
        lines.append("None.")
    else:
        for r in invalid:
            lines.append("- %s / %s trial %s: %s (%s)" % (
                r.get("scenario"), r.get("candidate"), r.get("trial"),
                r.get("invalid_reason","invalid"), r.get("manifest_path")))
    lines.append("")

    lines.append("## Interpretation notes")
    lines.append("")
    lines.append("- **Correctness first:** any candidate with overlap/loss/dup or incorrect totals is not viable regardless of speed.")
    lines.append("- **Control vs dist:** control uses the existing forkrun pipeline; dist candidates use the isolated experimental ingestion engine with simulated consumers. Differences in execution model limit direct comparability.")
    lines.append("- **Fake/local NUMA:** placement and locality numbers are best-effort observations on this host; they do not establish physical multi-socket behavior.")
    lines.append("- **Pipe ingestion:** out of initial bake-off for dist candidates unless explicitly enabled and validated; file ingestion is the primary target.")
    lines.append("- **Decision:** prefer simpler policy if performance/correctness/locality are equivalent. Retain centralized control if competitive. No production adoption implied.")
    lines.append("")
    verdict = "INCONCLUSIVE (local/fake-NUMA prototype campaign)"
    if not camp.get("all_ok"):
        verdict = "INCONCLUSIVE — campaign has failures/invalid trials"
    lines.append("**Overall verdict (local):** %s" % verdict)
    lines.append("")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
