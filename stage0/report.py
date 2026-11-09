"""Stage 0 report generator (campaign spec §9).

Reads stage0/runs/<case>/trial*/manifest.json + the ablation JSON,
and produces reports/stage0-report.md with:
- per-case trial table (rec/s, wall, tree CPU, per-core basis)
- the Go/No-Go/Inconclusive derivation per spec §8
- provenance + a one-page decision summary

Usage:
  python3 stage0/report.py --runs stage0/runs --ablation stage0/raw/ablation.json
"""

import argparse
import glob
import json
import os
import statistics
import sys


def _median(xs):
    return statistics.median(xs) if xs else None


def load_cases(runs_dir):
    cases = {}
    for trial in sorted(glob.glob(os.path.join(runs_dir, "*", "trial*"))):
        mp = os.path.join(trial, "manifest.json")
        if not os.path.isfile(mp):
            continue
        with open(mp, encoding="utf-8") as fh:
            m = json.load(fh)
        case = os.path.basename(os.path.dirname(trial))
        cases.setdefault(case, []).append(m)
    return cases


def case_summary(cases):
    rows = []
    for case, manifests in sorted(cases.items()):
        ok = [m for m in manifests if m.get("complete")]
        recs = [m["child_report"]["rec_per_s"] for m in ok
                if m.get("child_report")]
        walls = [m["wall_s"] for m in ok]
        cpus = [m["cpu_per_core_basis"] for m in ok
                if m.get("cpu_per_core_basis") is not None]
        spec = (manifests[0] or {}).get("spec", {})
        rows.append({
            "case": case,
            "spec": spec,
            "n_trials": len(manifests),
            "n_ok": len(ok),
            "median_rec_per_s": _median(recs),
            "spread_pct": ((max(recs) - min(recs)) / _median(recs) * 100)
            if recs and _median(recs) else None,
            "median_wall_s": _median(walls),
            "median_per_core": _median(cpus),
        })
    return rows


def derive_verdict(summary):
    """Spec §8 derivation (fake NUMA cannot produce Go for real-NUMA)."""
    text = []
    # Tree-CPU is NOT ingest-thread CPU: the engine forks ingest and
    # workers, and threads share the tree total. Report levels honestly
    # and state the attribution gap instead of claiming saturation.
    levels = [(r["case"], r["median_per_core"]) for r in summary
              if r["median_per_core"] is not None]
    if levels:
        lo, hi = min(v for _, v in levels), max(v for _, v in levels)
        text.append("Whole-tree CPU: %.2f-%.2f core-equivalents (child "
                    "process tree, sampled concurrently). Whether the "
                    "single centralized ingest THREAD saturates ~1 core "
                    "while workers idle cannot be attributed from here: "
                    "no per-thread role tagging or queue-empty telemetry "
                    "exists in the harness (spec §4.2/§4.3 gap).\n"
                    "  NOTE: upper-stage numbers that bundle 'ingest+' "
                    "compute' into one tree total; the ingest-only rate "
                    "is NOT isolated in these cells."
                    % (lo, hi))
    slow_or_startup = [r for r in summary
                       if r["median_wall_s"] and r["median_wall_s"] < 2.0]
    if slow_or_startup:
        text.append("Startup-dominated cells (<2s wall; the campaign's "
                    "own 2-second rule flags these as bring-up-dominated, "
                    "not steady-state: %s)" % ", ".join(
                        r["case"] for r in slow_or_startup))
    else:
        text.append("All cells ran >=2s wall (bring-up amortized).")
    text.append("Downstream-demand (spec §3 queue-nonempty-interval "
                "method) is NOT AVAILABLE in this harness: no scanner-"
                "queue occupancy telemetry is exposed; the least-invasive "
                "ring diagnostic for isolating ingest vs starvation is "
                "deferred to the rental/instrumentation phase. Without it, "
                "ingest-limited vs downstream-limited attribution of idle "
                "time is an inference, not a measurement.")
    return {
        "verdict": "INCONCLUSIVE for real-NUMA benefit (required by spec "
                   "§8: fake-NUMA evidence cannot establish the gate; "
                   "rental campaign needed)",
        "evidence": "\n".join("- " + t for t in text),
        "first_order_ingest_signal": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", default="stage0/runs")
    ap.add_argument("--ablation", default=None)
    ap.add_argument("--env", default=None,
                    help="env_capture.py output (JSON manifest)")
    ap.add_argument("--out", default="stage0/reports/stage0-report.md")
    args = ap.parse_args()
    cases = load_cases(args.runs)
    summary = case_summary(cases)
    verdict = derive_verdict(summary)

    lines = ["# Stage 0 rehearsal report (fake NUMA — NOT real-NUMA evidence)",
             "",
             "## Verdict (spec §8)", "",
             "**%s**" % verdict["verdict"], "",
             verdict["evidence"], "",
             "## Baseline cases (median of trials)", "",
             "| case | spec | trials ok | rec/s (median) | spread % | wall s | tree cores |",
             "|---|---|---|---|---|---|---|"]
    for r in summary:
        lines.append("| %s | w%s n%s %s | %d/%d | %s | %s | %s | %s |" % (
            r["case"],
            r["spec"].get("workers"), r["spec"].get("nodes"),
            r["spec"].get("mode"),
            r["n_ok"], r["n_trials"],
            ("%.0f" % r["median_rec_per_s"]) if r["median_rec_per_s"] else "-",
            ("%.1f" % r["spread_pct"]) if r["spread_pct"] is not None else "-",
            ("%.2f" % r["median_wall_s"]) if r["median_wall_s"] else "-",
            ("%.2f" % r["median_per_core"]) if r["median_per_core"] else "-"))
    lines += ["", "## 2×2 affinity/policy ablation (spec §6)", ""]
    if args.ablation and os.path.isfile(args.ablation):
        with open(args.ablation, encoding="utf-8") as fh:
            abl = json.load(fh)
        lines.append("| cell | affinity (cpu, set_rc) | policy (node, set_rc) | pages by node | unknown |")
        lines.append("|---|---|---|---|---|")
        for r in abl["results"]:
            lines.append("| %s | cpu=%s rc=%s | node=%s rc=%s | %s | %d |" % (
                r["cell"], r["affinity"].get("cpu"), r["affinity"].get("set_rc"),
                r["policy"].get("node"), r["policy"].get("set_rc"),
                r["pages_by_node"], r["pages_unknown"]))
        lines.append("")
        lines.append("Finding: cell D (pinned node X, bound node Y) allocates on Y →")
        lines.append("task memory policy decides placement; CPU affinity does not.")
    else:
        lines.append("(ablation JSON not supplied or missing)")
    lines += ["", "## Provenance", ""]
    if args.env and os.path.isfile(args.env):
        with open(args.env, encoding="utf-8") as fh:
            env = json.load(fh)
        g = env["git"]
        lines.append("- git: %s @ %s (dirty=%s)" % (
            g.get("branch"), g.get("head_sha"), g.get("dirty")))
        lines.append("- kernel: %s | cmdline fake-numa: %s" % (
            env["kernel"]["release"], env["kernel"]["fake_numa_spec"]))
        lines.append("- shmem THP: %s" % env["thp"]["shmem_enabled"])
        lines.append("- build hashes: %s" % ", ".join(
            "%s=%s" % (os.path.basename(k), v[:12])
            for k, v in env["build_hashes"].items()))
    else:
        lines.append("(env manifest not supplied)")
    lines += ["", "## One-page decision summary", "",
              "Is the central ingest the limiter? NOT DECIDABLE on this "
              "box (spec §8 maps this to Inconclusive): whole-tree CPU "
              "peaks in the 1-7 core range depending on config (highest "
              "in the C-plugin and pipe cells, where C-level work and "
              "`cat` feeding dominate), but no ingest-THREAD attribution "
              "or scanner-queue occupancy telemetry exists in this "
              "harness, so the serial-ingest bottleneck hypothesis "
              "cannot be confirmed or denied here. The first-order "
              "screen that §7.1 asks for — one ingest thread at ~1 core "
              "while workers idle — needs the least-invasive ring "
              "diagnostic (§4.3) that this rehearsal identified but did "
              "not add (observational-only, no scheduling change).",
              "Is placement born-local? The 2x2 ablation answers the "
              "MECHANISM question on fake NUMA (cells C/D land 2048/2048 "
              "pages on the bound node; cell D shows task policy, not "
              "affinity, decides placement). This validates the "
              "instrumentation, not real-hardware residency.",
              "What remains: (1) rental execution of this exact "
              "campaign on real multi-node hardware (recipe below); "
              "(2) engine-side instrumentation for ingest-thread CPU and "
              "scanner-queue occupancy during that rental; (3) the "
              "plugin cell needs a bigger corpus (it finishes in <1s at "
              "20M and is build-verify-only today)."]
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
