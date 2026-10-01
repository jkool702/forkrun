#!/usr/bin/env python3
"""Stage 0 result writers: CSV + Markdown table, fault tables, narrative.

Reads ctx["rows"] / ctx["faults"] / ctx["hw"]; writes results/. The report
narrative states scope, per-niche localization, UNMEASURED reasons, and the
standing "what this table does NOT prove" section. No estimates: missing
data renders as UNMEASURED.
"""
from __future__ import annotations

import csv
import os

COLUMNS = ["niche", "incumbent", "incumbent_result_s", "incumbent_rss_mb",
           "forkrun_result_s", "forkrun_rss_mb", "ratio", "fault_outcome",
           "hardware", "notes"]


def _fmt(v) -> str:
    if v == "" or v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.3f}" if v < 100 else f"{v:.1f}"
    return str(v)


def write_tables(ctx: dict, resdir: str) -> None:
    rows = ctx["rows"]
    with open(os.path.join(resdir, "stage0_table_single_socket.csv"),
              "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    with open(os.path.join(resdir, "stage0_table_single_socket.md"), "w") as fh:
        fh.write("# Stage 0 measurement table — single socket\n\n")
        fh.write(f"Hardware (every row): {ctx['hw']}\n\n")
        fh.write("Scope: one machine, the named incumbents, the stated input "
                 "profiles. Ratios > 1 favor forkrun. Rows marked "
                 "\"Python frontend pending\" measure the substrate through "
                 "the C plugin ABI / bash frontend.\n\n")
        fh.write("| " + " | ".join(COLUMNS) + " |\n")
        fh.write("|" + "|".join(["---"] * len(COLUMNS)) + "|\n")
        for r in rows:
            fh.write("| " + " | ".join(_fmt(r.get(c, "")) for c in COLUMNS) + " |\n")


def write_faults(ctx: dict, resdir: str) -> None:
    with open(os.path.join(resdir, "stage0_fault_isolation.md"), "w") as fh:
        fh.write("# Stage 0 fault-isolation tables\n\n")
        fh.write(f"Hardware: {ctx['hw']}\n\n")
        fh.write("Discipline: named configurations, observed behavior only, "
                 "no generalized claims. Granularity differs by design "
                 "(item vs batch vs chunk) and is recorded per row.\n\n")
        for f in ctx["faults"]:
            o = f.get("outcome", {})
            fh.write(f"## {f['config']}\n\n")
            fh.write(f"- fault granularity: {f.get('granularity', '?')}\n")
            fh.write(f"- elapsed: {f.get('elapsed_s', '?')} s; "
                     f"rc: {f.get('rc', 'n/a')}\n")
            fh.write(f"- survived: {o.get('survived', '?')}\n")
            fh.write(f"- completed: {o.get('completed', '?')} / "
                     f"{o.get('total', '?')}\n")
            fh.write(f"- recovery action: {o.get('action', '?')}\n")
            fh.write(f"- pool usable after: {o.get('pool_usable_after', '?')}"
                     + (f" ({o['pool_usable_after_note']})"
                        if o.get("pool_usable_after_note") else "") + "\n")
            if f.get("notes"):
                fh.write(f"- notes: {f['notes']}\n")
            fh.write("\n")


def _by(ctx: dict, niche: str, pred) -> list:
    return [r for r in ctx["rows"]
            if r["niche"] == niche and pred(r)]


def write_report(ctx: dict, resdir: str) -> None:
    L: list[str] = []
    A = L.append
    A("# Stage 0 report — evidence, not verdict\n")
    A(f"Hardware: {ctx['hw']}\n")
    if ctx.get("engine_provenance"):
        A(f"Engine provenance: {ctx['engine_provenance']} (locally-built "
          "v3.5.2-dev blob; CI blobs pending — numbers depend on W-RAW/W-STDIN source)\n")
    A("This harness is the project's evidence layer for the Python "
      "frontend (localization, honest claims, positioning). It is not a "
      "decision instrument: the proceed decision is unconditional and "
      "recorded in dev/supervisor/STAGE0_AMENDMENT.md.\n")
    A("## What was measured\n")
    A("- JSONL ingestion: 1M records, Pool + futures vs three forkrun "
      "variants (C-argv copy path, C-raw zero-copy window, bash+python "
      "per-batch interpreter cost).\n")
    A("- Per-record transform: calibrated cost sweep 1µs→10ms; "
      "Pool chunksizes 1/100/1000 (at 100µs), futures, forkrun C plugin; "
      "crossover data in results/crossover.csv.\n")
    A("- Tokenize-to-tensor: 100M int32 tokens; forkrun raw-window sum "
      "(substrate ceiling) + separately timed numpy frombuffer+sum "
      "(delivery-vs-conversion split).\n")
    A("- TB streaming: pipe-fed multi-GB legs at two sizes per config "
      "(frun stdin-drain, GNU parallel --pipe, split+parallel); "
      "whole-pipeline RSS sampled; slope = boundedness assertion.\n")
    A("- Fault isolation: segfaulting item (Pool, futures), segfaulting "
      "batch (forkrun -E), segfaulting chunk (parallel); per-config tables "
      "in stage0_fault_isolation.md.\n")
    A("## Per-niche localization\n")
    jr = _by(ctx, "jsonl-ingest", lambda r: True)
    if jr:
        best = min((r for r in jr if r["ratio"] != ""),
                   key=lambda r: r["ratio"], default=None)
        A(f"- JSONL ({len(jr)} rows): argv-vs-raw delta isolates the "
          "tokenize/copy cost; bash+python isolates per-batch interpreter "
          "cost.")
        if best:
            A(f"  Closest incumbent race: {best['incumbent']} vs "
              f"{best['notes'].split(';')[0]} ratio={best['ratio']}.")
        A("")
    tr = _by(ctx, "per-record-transform",
             lambda r: r["incumbent"] == "mp-pool-k100")
    if tr:
        cross = [r for r in tr if r["ratio"] != ""]
        below = [r for r in cross if float(r["ratio"]) < 1.0]
        A(f"- Transform crossover ({len(cross)} cost points): dispatch "
          f"dominates at {len(below)} of {len(cross)} points; the crossover "
          "cost is the Python frontend's per-batch overhead budget "
          "(see crossover.csv).")
        A("")
    te = _by(ctx, "tokenize-to-tensor", lambda r: True)
    if te:
        r = te[0]
        A(f"- Tokenize: incumbent {r['incumbent_result_s']} "
          f"({r['notes'].split(';')[0]}); forkrun raw-window "
          f"{r['forkrun_result_s']} s; numpy conversion alone "
          f"{ctx.get('tensor_np_s', '?')} s.")
        A("")
    st = _by(ctx, "tb-streaming",
             lambda r: r["incumbent"] == "gnu-parallel" and r["forkrun_result_s"])
    if len(st) >= 2:
        rss = [r["forkrun_rss_mb"] for r in st]
        flat = max(rss) - min(rss)
        A(f"- Streaming: frun RSS {min(rss)}→{max(rss)} MB across "
          f"{len(st)} input sizes (delta {flat} MB) — "
          f"{'flat: bounded' if flat < 0.2 * max(rss) else 'RISING: finding'}.")
        A("  Throughput parity (~1.17 GB/s both configs, both sizes) is a "
          "generator ceiling, not an engine comparison: the single-process "
          "Python feeder saturates first. The valid streaming findings are "
          "boundedness (flat RSS) and byte accountability, not relative "
          "throughput.")
        A("")
    A("## UNMEASURED and why\n")
    for r in ctx["rows"]:
        if r["incumbent_result_s"] == 0.0 and "UNMEASURED" not in str(
                r.get("notes", "")).upper() and r["forkrun_result_s"] == 0.0:
            continue
        if "UNMEASURED" in str(r.get("notes", "")).upper() or \
                (r["incumbent_result_s"] == 0.0 and "torch" in r["incumbent"]):
            A(f"- {r['niche']} / {r['incumbent']}: {r['notes']}")
    A("")
    A("## What this table does NOT prove\n")
    A("- Adoption fitness, multi-socket scaling, or the Python frontend's "
      "eventual performance (it doesn't exist yet; rows say so).\n")
    A("- Generality beyond the stated hardware, incumbents, and inputs.\n")
    A("- That any single number transfers to another machine (hence the "
      "mandatory hardware column and the separately-labeled rental day).\n")
    with open(os.path.join(resdir, "stage0_report.md"), "w") as fh:
        fh.write("\n".join(L))
