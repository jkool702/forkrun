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
        mapping_id = o.get("mapping_id") or o.get("mapping_variant") or "legacy"
        mpath = os.path.join(args.campaign, o.get("manifest", ""))
        rec = {"scenario": scen, "candidate": cand, "mapping_id": mapping_id,
               "mapping_profile": o.get("mapping_profile"),
               "trial": o.get("trial"), "status": o.get("status"),
               "manifest_path": mpath, "invalid": False,
               # C2 correction: campaign outcome classification is authoritative, even if manifest is failed/missing/unreadable.
               "trial_class": (o.get("trial_class") or "performance"),
               "placement_sampling": (o.get("placement_sampling") or "off"),
               "linked_performance_trial": o.get("linked_performance_trial")}

        def mark_invalid(reason):
            rec["invalid"] = True
            rec.setdefault("invalid_reasons", []).append(reason)
            invalid.append(rec)

        # C3 defaults for early-invalid records
        rec["parameter_set_id"] = o.get("parameter_set_id") or "pset__default"
        rec["cache_precondition_policy"] = o.get("cache_precondition_policy") or "best_effort_os_cache"
        rec["min_duration_seconds"] = o.get("min_duration_seconds")
        rec["workload_id"] = o.get("workload_id") or scen

        if o.get("status") != "ok" or not os.path.isfile(mpath):
            mark_invalid("trial status %s or missing manifest" % o.get("status"))
            groups[(scen, rec.get("mapping_id") or "legacy", rec.get("parameter_set_id") or "pset__default", cand)].append(rec)
            continue

        try:
            m = load_json(mpath)
        except Exception as e:
            mark_invalid("manifest unreadable: %s" % e)
            groups[(scen, rec.get("mapping_id") or "legacy", rec.get("parameter_set_id") or "pset__default", cand)].append(rec)
            continue

        rec["manifest"] = m
        rec["complete"] = bool(m.get("complete", False))
        rec["incomplete_reasons_manifest"] = m.get("incomplete_reasons", [])
        rec["wall_s_harness"] = m.get("wall_s")
        rec["map_s"] = m.get("map_s")
        cr = m.get("child_report") or {}
        rec["bytes"] = cr.get("completed_bytes")
        rec["rec_per_s"] = cr.get("rec_per_s")
        spec = m.get("spec") or {}
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
            # C2: trial class / measurement integrity / linkage (outcome classification authoritative)
            mi = dr.get("measurement_integrity") or {}
            _outcome_tc = (o.get("trial_class") or None)
            if not _outcome_tc:
                rec["trial_class"] = dr.get("trial_class") or safe_get(dr, "comparability", "trial_class") or spec.get("trial_class") or rec.get("trial_class") or "performance"
            _outcome_ps = (o.get("placement_sampling") or None)
            if not _outcome_ps:
                rec["placement_sampling"] = mi.get("placement_sampling") or safe_get(dr, "comparability", "placement_sampling") or spec.get("placement_sampling") or rec.get("placement_sampling") or "off"
            if rec.get("linked_performance_trial") is None:
                rec["linked_performance_trial"] = dr.get("linked_performance_trial") or mi.get("linked_performance_trial") or spec.get("linked_performance_trial")
            rec["timing_tainted_by_in_run_sampling"] = mi.get("timing_tainted_by_in_run_sampling")
            # mapping identity/provenance (checkpoint 1)
            mp = dr.get("mapping_provenance") or {}
            if rec.get("mapping_id") in (None, "legacy"):
                rec["mapping_id"] = mp.get("mapping_variant") or mp.get("mapping_profile") or rec.get("mapping_id") or "legacy"
            rec["mapping_profile"] = rec.get("mapping_profile") or mp.get("mapping_profile")
            rec["mapping_variant"] = mp.get("mapping_variant")
            rec["logical_to_physical"] = mp.get("logical_to_physical") or safe_get(dr, "topology", "logical_to_physical")
            rec["spans_sockets"] = mp.get("spans_sockets")
        else:
            rec["dist"] = None
            rec["is_dist_engine"] = False
            # Outcome classification remains authoritative; refine from spec only if outcome omitted.
            if not (o.get("trial_class") or None):
                rec["trial_class"] = spec.get("trial_class") or rec.get("trial_class") or "performance"
            if not (o.get("placement_sampling") or None):
                rec["placement_sampling"] = spec.get("placement_sampling") or rec.get("placement_sampling") or "off"
            if rec.get("linked_performance_trial") is None:
                rec["linked_performance_trial"] = spec.get("linked_performance_trial")
            rec["timing_tainted_by_in_run_sampling"] = None
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
            if rec.get("mapping_id") in (None, "legacy"):
                rec["mapping_id"] = spec.get("mapping_variant") or spec.get("mapping_id") or rec.get("mapping_id") or "legacy"

        # C3 attributable axes (separate concerns)
        spec = (m.get("spec") or {}) if isinstance(m, dict) else {}
        dr3 = rec.get("dist") or {}
        rec["parameter_set_id"] = (o.get("parameter_set_id") or spec.get("parameter_set_id") or
                                   safe_get(spec, "parameter_set", "parameter_set_id") or
                                   safe_get(dr3, "comparability", "parameter_set_id") or "pset__default")
        rec["parameter_set"] = (o.get("parameter_set") or spec.get("parameter_set") or
                                safe_get(dr3, "comparability", "parameter_set") or None)
        rec["cache_precondition_policy"] = (o.get("cache_precondition_policy") or spec.get("cache_precondition_policy") or
                                             spec.get("cache_policy") or (m.get("cache_precondition") or {}).get("requested_policy") or
                                             "best_effort_os_cache")
        rec["cache_precondition"] = m.get("cache_precondition") if isinstance(m, dict) else None
        rec["min_duration_seconds"] = o.get("min_duration_seconds") if o.get("min_duration_seconds") is not None else spec.get("min_duration_seconds")
        rec["duration_qualification"] = m.get("duration_qualification") if isinstance(m, dict) else None
        rec["duration_aggregate"] = m.get("duration_aggregate") if isinstance(m, dict) else None
        # C3-corrections-2: repeated trials report the QUALIFIED AGGREGATE
        # measurement; pass 1 stays as provenance. Explicitly distinguish
        # aggregate from individual-pass metrics, and never silently fall
        # back to a misleading aggregate when it is invalid/excluded.
        dq = rec["duration_qualification"]
        agg = rec["duration_aggregate"] or {}
        rec["duration_stop_reason"] = dq.get("stop_reason") if isinstance(dq, dict) else None
        rec["qualified_duration_passes"] = (dq.get("pass_count")
                                            if isinstance(dq, dict) and dq.get("repetition_used")
                                            else None)
        rec["accumulated_duration_s"] = (dq.get("accumulated_effective_wall_seconds")
                                         if isinstance(dq, dict) else None)
        rec["duration_failed_passes"] = ([p.get("pass") for p in (dq.get("passes") or [])
                                          if isinstance(p, dict)
                                          and p.get("duration_contributes") is False]
                                         if isinstance(dq, dict) else [])
        rec["duration_excluded_passes"] = agg.get("excluded_passes") or []
        rec["aggregate_invalid_reasons"] = agg.get("aggregate_invalid_reasons") or []
        if isinstance(dq, dict) and dq.get("repetition_used"):
            if agg.get("aggregate_valid"):
                rec["throughput_bps"] = agg.get("aggregate_throughput_bps")
                rec["engine_wall_s"] = agg.get("aggregate_engine_wall_seconds")
                rec["reservations"] = agg.get("aggregate_reservations")
                rec["aggregate_consumed_bytes"] = agg.get("aggregate_consumed_bytes")
                rec["aggregate_scanned_bytes"] = agg.get("aggregate_scanned_bytes")
                rec["aggregate_scan_equals_consumed"] = agg.get("aggregate_scan_equals_consumed")
            else:
                # Invalid/unknown aggregate is reported explicitly; do not
                # reuse a pass-1 value as a misleading qualified result.
                rec["throughput_bps"] = None
                rec["engine_wall_s"] = None
                rec["reservations"] = None
        rec["workload_id"] = o.get("workload_id") or spec.get("workload_id") or scen

        if not rec.get("complete", False):
            mark_invalid("incomplete: %s" % rec.get("incomplete_reasons_manifest"))

        groups[(scen, rec.get("mapping_id") or "legacy", rec.get("parameter_set_id") or "pset__default", cand)].append(rec)

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
                 "`unknown` is distinct from `false`. `manifest.complete`/functional correctness is not all-validity. "
                 "Headline performance medians use performance-valid trials only; full-byte-scan and `none` results are not combined into one comparable summary. "
                 "C2: performance trials (`placement_sampling=off`, trial_class=performance) are isolated from in-run move_pages sampling overhead; "
                 "placement-validation experiments (`placement_sampling=on`, trial_class=placement_validation) are distinct, linked experiments and must not be mixed into performance headline statistics.")
    lines.append("")

    # C3: grouping includes parameter_set_id to keep sweep axes attributable.
    scenarios = sorted({k[0] for k in groups.keys()})
    mappings = sorted({k[1] for k in groups.keys()})
    parameter_sets = sorted({k[2] for k in groups.keys()})
    candidates = ["centralized_ingest", "fixed_faa", "local_adaptive", "relative_adaptive", "production_ref", "control"]

    if camp.get("unsupported_mappings"):
        lines.append("## Unsupported mappings (reported explicitly; not run)")
        lines.append("")
        for um in camp.get("unsupported_mappings") or []:
            lines.append("- profile=%s variant=%s nodes=%s scenarios=%s reason=%s" % (
                um.get("mapping_profile"), um.get("mapping_variant"), um.get("logical_node_count"),
                um.get("applies_to_scenarios"), um.get("reason")))
        lines.append("")

    # C3 axis provenance
    c3_axes = camp.get("sweep_axes") or (camp.get("campaign_config") or {}).get("sweep_axes") or []
    c3_cache = camp.get("cache_precondition_policy") or (camp.get("campaign_config") or {}).get("cache_precondition_policy")
    c3_min_dur = camp.get("min_duration_seconds") if camp.get("min_duration_seconds") is not None else (camp.get("campaign_config") or {}).get("min_duration_seconds")
    if c3_axes or c3_cache or c3_min_dur is not None or len(parameter_sets) > 1:
        lines.append("## C3 experimental axes (attributable; do not mix across axes)")
        lines.append("")
        lines.append("- **Parameter sweep axes:** %s" % (", ".join(c3_axes) if c3_axes else "(none)"))
        lines.append("- **Parameter sets:** %s" % ", ".join(parameter_sets))
        lines.append("- **Cache precondition policy (campaign requested):** %s" % (c3_cache or "n/a"))
        lines.append("- **Min duration qualification (seconds):** %s" % (c3_min_dur if c3_min_dur is not None else "n/a"))
        # Actual cache-precondition outcomes/fallbacks are per-trial facts; surface them.
        cp_recs = [r for recs in groups.values() for r in recs if isinstance(r.get("cache_precondition"), dict)]
        if cp_recs:
            achieved = sum(1 for r in cp_recs if r.get("cache_precondition", {}).get("achieved") is True)
            priv_attempted = sum(1 for r in cp_recs if r.get("cache_precondition", {}).get("privileged_action_attempted") is True)
            priv_ok = sum(1 for r in cp_recs if r.get("cache_precondition", {}).get("privileged_action_succeeded") is True)
            fallback_n = sum(1 for r in cp_recs if r.get("cache_precondition", {}).get("fallback"))
            lines.append("- **Cache precondition outcomes (per-trial):** achieved=%d/%d, privileged_attempted=%d, privileged_succeeded=%d, fallback=%d" % (
                achieved, len(cp_recs), priv_attempted, priv_ok, fallback_n))
            if fallback_n:
                lines.append("- **Cache precondition warning:** some trials recorded fallback; see per-trial `cache_precondition` details (do not assume privileged cold-cache control).")
        lines.append("")

    lines.append("## Comparative summary (headline performance medians from performance-valid trials only)")
    lines.append("")
    header = ("| scenario | mapping | param set | candidate | attempted | func complete | perf valid | numa-place valid | "
              "throughput (MB/s) | engine wall s | harness wall s | reservations | kernel | scanned/consumed | notes |")
    sep = "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|"
    lines.append(header); lines.append(sep)
    for scen in scenarios:
        for map_id in mappings:
            for pset_id in parameter_sets:
                for cand in candidates:
                    recs = groups.get((scen, map_id, pset_id, cand), [])
                    if not recs:
                        continue
                    total = len(recs)
                    # C2: placement-validation experiments are distinct from performance trials and
                    # must not be mixed into performance headline statistics.
                    perf_class_recs = [r for r in recs if (r.get("trial_class") or "performance") == "performance"]
                    placement_class_recs = [r for r in recs if (r.get("trial_class") or "performance") == "placement_validation"]
                    # complete/functionally correct trials (readable, complete, functionally correct)
                    func_valids = [r for r in perf_class_recs if (not r.get("invalid")) and r.get("correct_functional") is True and r.get("complete") is True]
                    # performance-valid trials only for headline performance stats
                    perf_valids = [r for r in func_valids if r.get("v_perf") is True]
                    numa_true = sum(1 for r in func_valids if r.get("v_numa_placement") is True)

                    def med(key, src):
                        vals = [r.get(key) for r in src if r.get(key) is not None]
                        return statistics.median(vals) if vals else None

                    kernels_func = sorted({str(r.get("consumer_kernel")) for r in func_valids if r.get("consumer_kernel") is not None})
                    kernels_perf = sorted({str(r.get("consumer_kernel")) for r in perf_valids if r.get("consumer_kernel") is not None})
                    kernel = ",".join(kernels_func) if kernels_func else "n/a"
                    mixed_kernel_func = len(kernels_func) > 1
                    mixed_kernel_perf = len(kernels_perf) > 1
                    # do not combine full-scan and no-kernel into one comparable campaign summary
                    noncomparable_kernel_mix = (("full_byte_scan" in kernels_func and "none" in kernels_func) or
                                                ("full_byte_scan" in kernels_perf and "none" in kernels_perf))

                    perf_for_medians = [] if noncomparable_kernel_mix else perf_valids
                    thr = med("throughput_bps", perf_for_medians)
                    thr_mb = (thr / 1e6) if thr else None
                    wall = med("engine_wall_s", perf_for_medians)
                    hwall = med("harness_wall_s", func_valids)  # diagnostic harness duration
                    resv = med("reservations", perf_for_medians)

                    scan_s = "n/a"
                    if not noncomparable_kernel_mix and perf_for_medians:
                        scan_vals = [r.get("scan_bytes") for r in perf_for_medians if r.get("scan_bytes") is not None]
                        cons_vals = [((r.get("dist") or {}).get("total_consumed")) for r in perf_for_medians if r.get("dist")]
                        if scan_vals or cons_vals:
                            s_med = int(statistics.median([v for v in scan_vals if v is not None])) if any(v is not None for v in scan_vals) else "n/a"
                            c_med = int(statistics.median([v for v in cons_vals if v is not None])) if any(v is not None for v in cons_vals) else "n/a"
                            scan_s = "%s/%s" % (s_med, c_med)
                    elif func_valids and not noncomparable_kernel_mix:
                        # show evidence context from functionally-correct trials even if no perf-valid headline medians
                        scan_vals = [r.get("scan_bytes") for r in func_valids if r.get("scan_bytes") is not None]
                        cons_vals = [((r.get("dist") or {}).get("total_consumed")) for r in func_valids if r.get("dist")]
                        if scan_vals or cons_vals:
                            s_med = int(statistics.median([v for v in scan_vals if v is not None])) if any(v is not None for v in scan_vals) else "n/a"
                            c_med = int(statistics.median([v for v in cons_vals if v is not None])) if any(v is not None for v in cons_vals) else "n/a"
                            scan_s = "%s/%s" % (s_med, c_med)

                    notes = []
                    bad = len(perf_class_recs) - len([r for r in perf_class_recs if not r.get("invalid")])
                    if bad:
                        notes.append("invalid/incomplete=%d" % bad)
                    if len(func_valids) == 0:
                        notes.append("no-functionally-valid-trials")
                    if len(perf_valids) == 0:
                        if noncomparable_kernel_mix:
                            notes.append("no-comparable-perf-headline (kernel mix)")
                        else:
                            notes.append("no-performance-valid-trials")
                    if noncomparable_kernel_mix:
                        notes.append("mixed-kernels-not-comparable")
                    perf_invalid_or_unknown = [r for r in func_valids if r.get("v_perf") is not True]
                    if perf_invalid_or_unknown:
                        notes.append("func-but-perf-invalid/unknown=%d" % len(perf_invalid_or_unknown))
                    if placement_class_recs:
                        notes.append("placement-validation=%d(distinct,excluded)" % len(placement_class_recs))
                    # C3: duration qualification visibility
                    dq_vals = [r.get("duration_qualification") for r in func_valids if isinstance(r.get("duration_qualification"), dict)]
                    if dq_vals and any(v.get("target_seconds") is not None for v in dq_vals):
                        unmet = [v for v in dq_vals if v.get("meets_target") is False]
                        if unmet:
                            notes.append("duration-unqualified=%d" % len(unmet))
                    # C3-corrections-2: repeated-trial facts across the
                    # group (aggregate validity, failed/excluded passes).
                    rep_trials = [r for r in func_valids if r.get("qualified_duration_passes")]
                    if rep_trials:
                        notes.append("duration-repeated(trials=%d)" % len(rep_trials))
                    failed_trials = [r for r in func_valids if r.get("duration_failed_passes")]
                    if failed_trials:
                        notes.append("duration-failed-passes(trials=%s)" %
                                     ",".join(str(r.get("trial")) for r in failed_trials))
                    agg_invalid = [r for r in func_valids if r.get("aggregate_invalid_reasons")]
                    if agg_invalid:
                        notes.append("duration-aggregate-invalid(trials=%d)" % len(agg_invalid))
                    excl_trials = [r for r in func_valids if r.get("duration_excluded_passes")]
                    if excl_trials:
                        notes.append("duration-aggregate-excluded(trials=%s)" %
                                     ",".join(str(r.get("trial")) for r in excl_trials))
                    lines.append("| %s | %s | %s | %s | %d | %d | %d | %d | %s | %s | %s | %s | %s | %s | %s |" % (
                        scen, map_id, pset_id, cand, len(perf_class_recs), len(func_valids), len(perf_valids), numa_true,
                        fmt(thr_mb), fmt(wall), fmt(hwall), fmt(resv, 0), kernel, scan_s, "; ".join(notes)))
    lines.append("")

    # C2: placement-validation experiments reported separately (distinct, linked)
    placement_trials = [r for recs in groups.values() for r in recs if (r.get("trial_class") or "performance") == "placement_validation"]
    if placement_trials:
        lines.append("## Placement-validation experiments (distinct from performance trials; not mixed into headline statistics)")
        lines.append("")
        lines.append("| scenario | mapping | param set | candidate | trial | linked perf trial | placement sampling | complete | func correct | placement observed | numa placement | notes |")
        lines.append("|---|---|---|---|---:|---|---|---|---|---|---|---|")
        for r in sorted(placement_trials, key=lambda x: (str(x.get("scenario") or ""), str(x.get("mapping_id") or ""), str(x.get("parameter_set_id") or ""), str(x.get("candidate") or ""), int(x.get("trial") or 0))):
            pnotes = []
            if r.get("invalid"):
                pnotes.extend([str(x) for x in (r.get("invalid_reasons") or ["invalid"])])
            if r.get("timing_tainted_by_in_run_sampling"):
                pnotes.append("timing-tainted-by-sampling")
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                r.get("scenario"), r.get("mapping_id"), r.get("parameter_set_id") or "pset__default", r.get("candidate"), fmt(r.get("trial")),
                r.get("linked_performance_trial") or "n/a", r.get("placement_sampling") or "n/a",
                fmt_tri(r.get("complete")), fmt_tri(r.get("v_functional")),
                fmt_tri(r.get("v_placement_obs")), fmt_tri(r.get("v_numa_placement")),
                "; ".join(pnotes) if pnotes else ""))
        lines.append("")

    lines.append("## Dist-candidate validity and workload evidence (per trial)")
    lines.append("")
    for scen in scenarios:
        for map_id in mappings:
            for pset_id in parameter_sets:
                for cand in candidates:
                    if cand in ("control", "production_ref"):
                        continue
                    recs = groups.get((scen, map_id, pset_id, cand), [])
                    if not recs:
                        continue
                    lines.append("### %s / %s / %s / %s (attempted=%d)" % (scen, map_id, pset_id, cand, len(recs)))
                    lines.append("")
                    for r in recs:
                        dr = r.get("dist")
                        if not dr:
                            lines.append("- trial %s: invalid=%s reasons=%s" % (r.get("trial"), r.get("invalid"), r.get("invalid_reasons")))
                            continue
                        lines.append("- trial %s (class=%s, placement_sampling=%s, linked=%s): complete=%s invalid=%s kernel=%s scanned=%s consumed=%s scan_ok=%s "
                                     "engine_wall=%.6fs harness_wall=%s valid[func=%s perf=%s affinity=%s mempolicy=%s placement_obs=%s numa=%s] "
                                     "correct=%s overlap=%s lost=%s dup=%s reservations=%s rc=%s" % (
                            r.get("trial"), r.get("trial_class"), r.get("placement_sampling"), r.get("linked_performance_trial") or "n/a",
                            r.get("complete"), r.get("invalid"),
                            r.get("consumer_kernel"), r.get("scan_bytes"), dr.get("total_consumed"), fmt_tri(r.get("scan_equals_consumed")),
                            float(dr.get("wall_seconds") or 0.0), fmt(r.get("harness_wall_s")),
                            fmt_tri(r.get("v_functional")), fmt_tri(r.get("v_perf")), fmt_tri(r.get("v_affinity")),
                            fmt_tri(r.get("v_mempolicy")), fmt_tri(r.get("v_placement_obs")), fmt_tri(r.get("v_numa_placement")),
                            dr.get("correct"), dr.get("overlap_detected"), dr.get("lost_detected"), dr.get("duplicate_detected"),
                            dr.get("reservations_total"), dr.get("rc")))
                        mpv = dr.get("mapping_provenance") or {}
                        if mpv:
                            lines.append("  - mapping: profile=%s variant=%s phys=%s spans_sockets=%s affinity_verified=%s" % (
                                mpv.get("mapping_profile"), mpv.get("mapping_variant"), mpv.get("logical_to_physical"),
                                mpv.get("spans_sockets"), fmt_tri(mpv.get("all_requested_affinity_roles_verified"))))
                        cp = r.get("cache_precondition")
                        if isinstance(cp, dict):
                            lines.append("  - cache_precondition: requested=%s achieved=%s privileged_attempted=%s privileged_succeeded=%s fallback=%s" % (
                                cp.get("requested_policy"), fmt_tri(cp.get("achieved")),
                                fmt_tri(cp.get("privileged_action_attempted")), fmt_tri(cp.get("privileged_action_succeeded")),
                                cp.get("fallback") or "n/a"))
                        dq = r.get("duration_qualification")
                        if isinstance(dq, dict):
                            lines.append("  - duration_qualification: target=%s effective=%s accumulated=%s passes=%s meets_target=%s repetition_used=%s capped=%s stop_reason=%s" % (
                                fmt(dq.get("target_seconds")), fmt(dq.get("effective_wall_seconds")),
                                fmt(dq.get("accumulated_effective_wall_seconds")), dq.get("pass_count"),
                                fmt_tri(dq.get("meets_target")), fmt_tri(dq.get("repetition_used")),
                                fmt_tri(dq.get("repetition_capped")), fmt_tri(dq.get("stop_reason"))))
                            agg = dq.get("duration_aggregate") or {}
                            lines.append("  - duration_aggregate: contributing=%s engine_wall=%s consumed=%s scanned=%s scan_eq_consumed=%s reservations=%s throughput_bps=%s valid=%s invalid_reasons=%s" % (
                                agg.get("contributing_passes"), fmt(agg.get("aggregate_engine_wall_seconds")),
                                fmt(agg.get("aggregate_consumed_bytes")), fmt(agg.get("aggregate_scanned_bytes")),
                                fmt_tri(agg.get("aggregate_scan_equals_consumed")), fmt(agg.get("aggregate_reservations")),
                                fmt(agg.get("aggregate_throughput_bps")), fmt_tri(agg.get("aggregate_valid")),
                                agg.get("aggregate_invalid_reasons") or []))
                            for pp in dq.get("passes", []):
                                lines.append("  -   duration_pass: pass=%s initial=%s status=%s qualified=%s contributes=%s wall=%s consumed=%s scanned=%s res=%s perf_validity=%s cache_compatible=%s failure=%s" % (
                                    pp.get("pass"), fmt_tri(pp.get("is_initial_pass")), pp.get("status"),
                                    fmt_tri(pp.get("qualified")), fmt_tri(pp.get("duration_contributes")),
                                    fmt(pp.get("engine_wall_seconds")), fmt(pp.get("total_consumed")),
                                    fmt(pp.get("total_consumer_bytes_scanned")), fmt(pp.get("reservations_total")),
                                    fmt_tri(pp.get("performance_validity")), fmt_tri(pp.get("cache_compatible")),
                                    pp.get("failure_reason")))
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
            lines.append("- %s / %s / %s trial %s: %s (%s)" % (
                r.get("scenario"), r.get("mapping_id"), r.get("candidate"), r.get("trial"),
                "; ".join([str(x) for x in reasons]), r.get("manifest_path")))
    lines.append("")

    lines.append("## Interpretation notes")
    lines.append("")
    lines.append("- **Correctness first:** overlap/loss/dup or incorrect totals invalidate functional correctness.")
    lines.append("- **Comparable set:** centralized_ingest vs fixed_faa/local_adaptive/relative_adaptive share the same dist_ingest engine, consumers, work units, measurement boundaries, and (per block) consumer kernel/params.")
    lines.append("- **Timing:** dist-engine comparative wall time is `DIST_RESULT.wall_seconds`; harness duration is separate/diagnostic.")
    lines.append("- **Headline performance:** throughput/engine wall-time/reservation medians use performance-valid trials only (not false/unknown performance validity). Functionally-correct but performance-invalid/unknown trials are retained in detailed evidence with raw throughput and validity reasons; `unknown` != `false`.")
    lines.append("- **Measurement integrity (C2):** performance trials run with `placement_sampling=off` (no in-run move_pages sampling overhead). Placement-validation experiments run with `placement_sampling=on` as distinct, linked trials (timing tainted by sampling) and are excluded from performance headline statistics.")
    lines.append("- **Workload comparability:** full-byte-scan and no-kernel (`none`) results are not combined into one comparable performance summary.")
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
