#!/usr/bin/env python3
"""epyc/validate_cells.py — one place where "did this cell lose records?" lives.

Every benchmark harness reports throughput per row, and a row whose throughput
is computed over fewer output records than the input contained is not a fast
row, it is a WRONG row. On a multi-node topology that failure mode is silent:
the run returns 0, prints a plausible rate, and leaves a checkpoint behind.

This is the F-NUMA1 signature, and it is the single most valuable thing a
multi-node rental can detect. It appeared at 4 nodes on heavy-20M as a run that
returned ~25% of its records with no error (RELEASE_v3.6.0.md §2, NOTE†).

Why a shared module
-------------------
The three benchmark harnesses report the same fact in three different shapes:

  bench_ml_pipeline / bench_tokenize
      columns: name,mode,path,lines_per_s,rss_mb,cpu_pct,notes,hardware
      count lives in the free-text notes as "out=4997892" or "out=5000000/5000000"

  bench_numa_5m
      columns: cell,variant,kind,nodes,workers,total,valid,...
      counts are first-class columns

  raw bash benchmark output
      no counts at all — only a per-run line count and CPU utilisation

Three copies of the loss arithmetic is three chances to get the threshold wrong,
and a validator that never fires is worse than no validator (the repo's own
principle: "a comparator that always passes is worse than none"). So the
arithmetic lives here, once, and every stage calls this.

The arithmetic
--------------
Each payload's quality gate drops a fixed FRACTION of the corpus, not a fixed
count. Measured at 5M (RELEASE_v3.6.0.md §0):

    light  5000000 -> 5000000    0.0%      (no gate)
    medium 5000000 -> 4997892    0.0422%   (duration_ms < 100, unknown event_type)
    heavy  5000000 -> 4997982    0.0404%

ml_data_gen seeds a fresh Random(42) per call, so a 5M corpus is an exact prefix
of a 20M corpus and the drop RATE is scale-invariant. Fractions are therefore
correct at any --records value; absolute counts are not.

Tolerance is 2%: the true gate drop is ~0.04%, F-NUMA1 loses ~25%, and a
stalled node returns 100% short. 2% sits more than an order of magnitude from
both, so it cannot false-positive on the gate and cannot miss a real loss.
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys

# Quality-gate drop fraction per variant, measured at 5M records.
DROP_FRACTION = {
    "light": 0.0,
    "medium": 2108 / 5_000_000,
    "heavy": 2018 / 5_000_000,
}
# Variants not in the table (e.g. "spawn", "tokenize", "transform") gate nothing
# measurable here, so treat them as exact.
DEFAULT_DROP = 0.0
LOSS_TOLERANCE = 0.02

_OUT_RE = re.compile(r"out=(\d+)(?:\s*/\s*(\d+))?")


def drop_fraction(variant: str | None) -> float:
    if not variant:
        return DEFAULT_DROP
    for v, frac in DROP_FRACTION.items():
        if v in variant:
            return frac
    return DEFAULT_DROP


def expected_valid(variant: str | None, total: int) -> int:
    return int(round(total * (1.0 - drop_fraction(variant))))


def classify(variant: str | None, total: int, valid: int) -> tuple[str, bool]:
    """Return (verdict, is_loss).

    The engine's contract is that every input record is processed exactly once
    and emitted, EXCEPT records the payload's own quality gate drops. So:
      valid == total        -> nothing dropped
      valid ~= expected     -> the gate dropped what it always drops
      valid << expected     -> DATA LOSS
      valid == 0            -> empty output, always a finding
    """
    if total <= 0:
        return "NO-COUNTS", False
    if valid == 0:
        return "EMPTY-OUTPUT", True
    exp = expected_valid(variant, total)
    if valid < int(exp * (1.0 - LOSS_TOLERANCE)):
        return f"LOSS({100.0 * (exp - valid) / exp:.1f}%)", True
    if valid >= total:
        return "EXACT", False
    return f"ok(gate,-{total - valid})", False


def _variant_of(*fields: str) -> str | None:
    for f in fields:
        if f:
            low = f.lower()
            for v in DROP_FRACTION:
                if v in low:
                    return v
    return None


def extract(path: str, row: dict, default_total: int | None = None):
    """Return (name, variant, total, valid, expected) for one row of any harness.

    Handles both shapes:
      * first-class total/valid columns          (bench_numa_5m, headline grid)
      * free-text "out=VALID/TOTAL" in the notes (bench_ml_pipeline, bench_tokenize)

    The notes form is emitted as ``"out=%d/%d" % (n_out, n_records)`` — see
    bench_ml_pipeline.py:244 — so the FIRST number is the output count and the
    second is the input count. Some rows omit the second half entirely (the
    native legs: "out=49974"), in which case the corpus size has to come from
    --records or the row cannot be loss-checked at all.
    """
    name = row.get("cell") or row.get("name") or "?"
    variant = _variant_of(name, row.get("variant"), row.get("mode"), row.get("test"))

    total = valid = None

    # 1. first-class columns win
    for k in ("total", "total_records", "input_records", "n_records"):
        v = row.get(k)
        if v not in (None, ""):
            try:
                total = int(str(v).replace(",", ""))
            except ValueError:
                pass
            break
    for k in ("valid", "valid_records", "out_records"):
        v = row.get(k)
        if v not in (None, ""):
            try:
                valid = int(str(v).replace(",", ""))
            except ValueError:
                pass
            break

    # 2. fall back to the free-text note
    if valid is None or total is None:
        m = _OUT_RE.search(row.get("notes", "") or "")
        if m:
            if valid is None:
                valid = int(m.group(1))          # n_out  (FIRST)
            if total is None:
                total = int(m.group(2)) if m.group(2) else default_total

    if total is None:
        return name, variant, None, None, 0
    return name, variant, total, valid, expected_valid(variant, total)


def rate_of(row: dict) -> str:
    for k in ("rate_rec_s", "lines_per_s", "docs_per_s", "rate"):
        v = row.get(k)
        if v not in (None, ""):
            try:
                return f"{float(v):,.0f}"
            except ValueError:
                return str(v)
    return "?"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--csv", action="append", default=[],
                    help="CSV path or glob (repeatable)")
    ap.add_argument("--records", type=int, default=None,
                    help="corpus size, for rows whose note omits the total "
                         "(the native legs emit a bare 'out=N')")
    ap.add_argument("--out", help="write a markdown report here")
    ap.add_argument("--title", default="cell validation")
    ap.add_argument("--context", default="",
                    help="extra markdown paragraph printed above the table")
    ap.add_argument("--fail-on-loss", action="store_true", default=True)
    ap.add_argument("--no-fail-on-loss", dest="fail_on_loss", action="store_false")
    ap.add_argument("--require-counts", action="store_true",
                    help="treat a row with no input/output cardinality as a "
                         "FAILURE, not merely 'unknown'. Use for the NUMA "
                         "experiment: a throughput cell that cannot be "
                         "independently checked for record conservation is an "
                         "invalid experiment, not a passing one. The repo's own "
                         "rule applies — a validator that cannot fail is worse "
                         "than no validator.")
    args = ap.parse_args()

    paths: list[str] = []
    for p in args.csv:
        paths.extend(sorted(glob.glob(p)) or [p])

    lines: list[str] = []
    n_rows = 0
    n_loss = 0
    n_nocount = 0
    losses: list[tuple[str, str, str]] = []
    unvalidated: list[tuple[str, str]] = []

    for path in paths:
        if not os.path.exists(path):
            lines.append(f"\n> **{os.path.basename(path)}: file not found — skipped**\n")
            continue
        try:
            rows = list(csv.DictReader(open(path)))
        except Exception as e:  # noqa: BLE001
            lines.append(f"\n> **{os.path.basename(path)}: unreadable ({e})**\n")
            continue
        if not rows:
            lines.append(f"\n> **{os.path.basename(path)}: no rows**\n")
            continue

        base = os.path.basename(path)
        lines.append(f"\n## {base}  ({len(rows)} rows)\n")
        lines.append("| cell | total | valid | expected | rate | verdict |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for r in rows:
            name, variant, total, valid, exp = extract(path, r, args.records)
            n_rows += 1
            if total is None or valid is None:
                n_nocount += 1
                why = "no count reported" if total is None else "count but no total (pass --records)"
                unvalidated.append((base, f"{name} ({why})"))
                verdict = f"**UNVALIDATED ({why})**" if args.require_counts else f"({why})"
                lines.append(f"| {name} | ? | ? | ? | {rate_of(r)} | {verdict} |")
                continue
            verdict, is_loss = classify(variant, total, valid)
            if is_loss:
                n_loss += 1
                losses.append((base, name, verdict))
                verdict = f"**{verdict}**"
            lines.append(f"| {name} | {total:,} | {valid:,} | {exp:,} | {rate_of(r)} | {verdict} |")

    hdr = [f"# {args.title}", ""]
    if args.context:
        hdr += [args.context, ""]
    hdr += [
        f"**rows examined: {n_rows}** | "
        f"**cells with real loss: {n_loss}** | "
        f"cells with no cardinality (unvalidated): {n_nocount}"
        + ("  **(treated as FAILURE)**" if args.require_counts else ""),
        "",
    ]
    body = "\n".join(lines)
    tail = ""
    if n_loss:
        tail = (
            "\n\n> ## Do not trust the throughput numbers in this run\n"
            "> At least one cell returned fewer records than it consumed. That is the\n"
            "> F-NUMA1 signature (a stalled node's ChunkMeta slot recycled by a meta-ring\n"
            "> lap), not a slow run. Re-run the affected cell in isolation before quoting\n"
            "> any rate, and report it upstream — this is a product finding.\n"
            + "\n".join(f"> - `{b}` / `{n}`: {v}" for b, n, v in losses)
            + "\n"
        )
    elif unvalidated:
        tail = (
            f"\n\nNo cell lost records, but **{n_nocount} cell(s) reported no input/output "
            "cardinality** and therefore could not be checked for conservation:\n"
            + "\n".join(f"> - `{b}` / `{n}`" for b, n in unvalidated)
            + "\n\nTheir throughput numbers are UNVALIDATED: nothing rules out a silent\n"
            "> record loss in them. Run the cell again in a mode that reports counts.\n"
        )
    else:
        tail = (
            "\n\nAll cells with reported counts returned within the documented\n"
            "quality-gate drop. No silent loss detected.\n"
        )

    report = "\n".join(hdr) + body + tail
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(report)
    print(report)

    failed = (n_loss and args.fail_on_loss) or (n_nocount and args.require_counts)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
