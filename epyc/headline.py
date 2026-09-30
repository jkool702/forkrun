#!/usr/bin/env python3
"""epyc/headline.py — the (dagger)/(max) pinned headline grid on real NUMA.

Reproduces the cell schema of
``python/benchmarks/results/headline_2026-09-29.csv`` so the rental's numbers
can be diffed directly against the published ones:

    cell,variant,kind,orchestrator,order,workers,median_s,rate_rec_s,
    input_bytes,total,valid,verdict

with two additions this harness needs:

    nodes       the NUMA topology the cell ran under (the reference file has no
                such column because every reference cell was UMA at 28 workers)
    seconds     spelled out alongside median_s so a reader never has to divide

Why this script exists at all
-----------------------------
The W-REL1/R1 default flip (2026-09-27) made the reactor the default, so
omitting ``orchestrator`` now yields a (†) cell — crash recovery, C-orderer
transit — where the pre-flip baselines were (max) legacy fail-fast cells.
``spotcheck_post_wrel6.md`` §9 issues a standing order about this: *EPYC
comparisons must pin ``orchestrator`` explicitly on both sides.* The stock
benchmark scripts do not pin it, so nothing they emit is directly comparable to
RELEASE_v3.6.0.md §0. This runner pins both sides.

Cells
-----
  kind=C    mode="plugin",   payload "<tmpdir>/ml_plugin_<v>.so:ml_process_<v>"
  kind=Py   mode="python",   payload ml_payload.forkrun_payload_<v>
  (dagger)  orchestrator=True,  order="index"   (reactor, recovers worker death)
  (max)     orchestrator=False, order="none"    (legacy ceiling, no recovery)

Neither configuration is "the right one". (†) is the shipping default and the
only one that survives a SIGKILL; (max) is the throughput ceiling. Quoting one
without the other is the apples-to-oranges problem §9 warns about.

known total/valid split (quality gate drops, identical on both configurations)
    light  5000000 / 5000000
    medium 5000000 / 4997892   (2108 dropped: duration_ms < 100, unknown event_type)
    heavy  5000000 / 4997982   (2018 dropped)
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import statistics
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(REPO, "python"),
          os.path.join(REPO, "python", "benchmarks"),
          os.path.join(REPO, "python", "benchmarks", "ml")):
    if p not in sys.path:
        sys.path.insert(0, p)

VARIANTS = ("light", "medium", "heavy")

# Quality-gate drop fraction, measured at 5M records (RELEASE_v3.6.0.md §0):
#   light  5000000 -> 5000000   (0 dropped)
#   medium 5000000 -> 4997892   (2108 dropped: duration_ms < 100, unknown event_type)
#   heavy  5000000 -> 4997982   (2018 dropped)
# These are fractions of the corpus, not absolute counts, so they scale. The
# payloads draw from a seeded RNG whose stream is identical at every scale, so
# the drop *rate* is genuinely scale-invariant (5M is a prefix of 20M).
DROP_FRACTION = {"light": 0.0, "medium": 2108 / 5_000_000, "heavy": 2018 / 5_000_000}
# Tolerance for calling a short cell a real loss. The true gate drop is ~0.04%;
# F-NUMA1 loses ~25% and a dead node returns 100% short. 2% separates them by
# more than an order of magnitude in both directions, so it cannot false-positive
# on the gate and cannot miss a real loss.
LOSS_TOLERANCE = 0.02

# (label, orchestrator, order)
CONFIGS = (
    ("true-idx", True, "index"),     # (dagger) reactor default, ordered
    ("false-none", False, "none"),   # (max)    legacy fail-fast, unordered
)


def build_plugin(variant: str, workdir: str) -> str:
    """Compile the benchmark's C plugin for `variant`. -march=native, so this
    must happen ON the rental box (the lab .so is a different microarch)."""
    src = os.path.join(REPO, "python", "benchmarks", "ml", "plugins",
                       f"ml_plugin_{variant}.c")
    out = os.path.join(workdir, f"ml_plugin_{variant}.so")
    if os.path.exists(out) and os.path.getmtime(out) > os.path.getmtime(src):
        return out
    if shutil.which("gcc") is None:
        raise RuntimeError("need gcc to build the C plugin")
    cmd = ["gcc", "-O3", "-shared", "-fPIC", "-march=native",
           "-I", os.path.join(REPO, "ring_loadables"),
           "-o", out, src, "-lm"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"plugin build failed for {variant}:\n{r.stderr[-3000:]}")
    print(f"  built {os.path.basename(out)}", file=sys.stderr)
    return out


def count_valid(blobs) -> tuple[int, int]:
    """Return (total_newlines, non_empty_segments).

    The payload emits one newline-terminated segment per INPUT line — a
    record dropped by the quality gate becomes a bare b"\\n", not nothing. So
    the newline count is the input count; the count of non-empty segments is
    the number of records that survived. That second number is what the
    reference file calls `valid`.
    """
    total = 0
    valid = 0
    for b in blobs:
        if not b:
            continue
        total += b.count(b"\n")
        for seg in b.split(b"\n"):
            if seg.strip():
                valid += 1
    return total, valid


def expected_valid(variant: str, total: int) -> int:
    """Records that should survive the quality gate, at any corpus size."""
    return int(round(total * (1.0 - DROP_FRACTION.get(variant, 0.0))))


def classify(variant: str, total: int, valid: int) -> str:
    """Verdict for a completed cell.

    The engine's contract is that every input record is processed exactly once
    and emitted, EXCEPT records the payload's own quality gate drops. So:
      valid == total            -> nothing dropped at all
      valid ~= expected         -> the gate dropped what it always drops
      valid << expected         -> DATA LOSS (F-NUMA1, or a stalled node)
      valid == 0                -> empty output; always a finding
    """
    exp = expected_valid(variant, total)
    if total <= 0:
        return "NO-OUTPUT"
    if valid == 0:
        return "EMPTY-OUTPUT"
    if valid < int(exp * (1.0 - LOSS_TOLERANCE)):
        return f"LOSS({100.0 * (exp - valid) / exp:.1f}%)"
    if valid >= total:
        return "EXACT"
    dropped = total - valid
    if dropped == 0:
        return "EXACT"
    return f"ok(quality-gate,-{dropped})"


def run_cell(variant, kind, cfg_label, orchestrator, order, workers, nodes,
             path, so, trials, warmup):
    import forkrun

    if kind == "C":
        payload = f"{so}:ml_process_{variant}"
        mode = "plugin"
    else:
        # forkrun_payload_<variant> all share the (Batch) -> bytes signature;
        # import the one for THIS variant rather than indexing a dict so a typo
        # fails loudly here instead of silently measuring the wrong payload.
        if variant == "light":
            from ml_payload import forkrun_payload_light as payload
        elif variant == "medium":
            from ml_payload import forkrun_payload_medium as payload
        elif variant == "heavy":
            from ml_payload import forkrun_payload_heavy as payload
        else:
            raise ValueError(f"unknown variant {variant!r}")
        mode = "python"

    def once():
        return forkrun.map(payload, path, mode=mode, workers=workers,
                           order=order, orchestrator=orchestrator, nodes=nodes)

    # Warmup. The first call pays fork costs, and the reference methodology is
    # "median-of-3 + warmup", so the warm call is deliberate and untimed.
    # --warmup N is honoured for real: benchmark scripts get reused months
    # later with assumptions baked into their CLI, and a flag that silently
    # ignores its own argument is worse than no flag.
    warm_total = warm_valid = 0
    for i in range(max(0, warmup)):
        try:
            warm_total, warm_valid = count_valid(once())
        except Exception as e:  # noqa: BLE001
            return dict(median_s="", rate_rec_s="", total="", valid="",
                        verdict=f"WARMUP-{i + 1}-ERROR:{type(e).__name__}:{str(e)[:120]}")
    if warmup > 0:
        total, valid = warm_total, warm_valid

    times = []
    for _ in range(max(1, trials)):
        t0 = time.perf_counter()
        try:
            blobs = once()
        except Exception as e:  # noqa: BLE001
            return dict(median_s="", rate_rec_s="", total=total, valid=valid,
                        verdict=f"ERROR:{type(e).__name__}:{str(e)[:120]}")
        times.append(time.perf_counter() - t0)
        total, valid = count_valid(blobs)

    med = statistics.median(times)
    rate = total / med if med > 0 else 0.0
    return dict(median_s=f"{med:.5f}", rate_rec_s=f"{rate:.1f}",
                total=total, valid=valid, verdict=classify(variant, total, valid))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", type=int, default=5_000_000)
    ap.add_argument("--variants", default="light,medium,heavy")
    ap.add_argument("--nodes", default="1,auto",
                    help="comma list: 1 (UMA), auto (boot topology), @N (forced logical)")
    ap.add_argument("--workers", type=int, default=0, help="0 = os.cpu_count()")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=1,
                    help="untimed warmup passes per cell before the timed ones "
                         "(default 1, matching the reference methodology)")
    ap.add_argument("--tmpdir", required=True)
    ap.add_argument("--csv", required=True)
    args = ap.parse_args()

    import forkrun

    workers = args.workers or (os.cpu_count() or 8)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    nodes_list = [n.strip() for n in args.nodes.split(",") if n.strip()]
    workdir = os.path.join(args.tmpdir, "headline_plugins")
    os.makedirs(workdir, exist_ok=True)

    print(f"# headline grid — {args.records} records, {workers} workers, "
          f"nodes={nodes_list}, trials={args.trials}+{args.warmup} warmup",
          file=sys.stderr)
    print(f"# forkrun {forkrun.__version__} engine {forkrun.__engine_version__}",
          file=sys.stderr)
    print(f"# python {sys.version.split()[0]}", file=sys.stderr)
    try:
        from forkrun._numa import detect_numa_nodes
        print(f"# online NUMA nodes: {detect_numa_nodes()}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"# could not detect NUMA nodes: {e}", file=sys.stderr)

    rows = []
    # (max) cells LAST. The legacy fork-and-wait path is the W-P0LEGACY
    # regression class (a bounded helper join that SIGKILLs the scanner on long
    # runs); running it last means a regression costs us the cheap cells last,
    # not first.
    order = [("C", "true-idx", True, "index"), ("Py", "true-idx", True, "index"),
             ("C", "false-none", False, "none"), ("Py", "false-none", False, "none")]

    for nodes in nodes_list:
        for variant in variants:
            path = os.path.join(args.tmpdir, f"ml_{variant}.jsonl")
            if not os.path.exists(path):
                print(f"!! missing {path} — skipping {variant}", file=sys.stderr)
                continue
            nlines = sum(1 for _ in open(path, "rb"))
            if nlines != args.records:
                print(f"!! {path} has {nlines} lines, expected {args.records} — "
                      f"refusing (stale-data trap)", file=sys.stderr)
                return 2
            in_bytes = os.path.getsize(path)
            so = build_plugin(variant, workdir)

            for kind, cfg_label, orch, ordr in order:
                cell = f"{kind}-{cfg_label}-{variant}"
                print(f"  {cell}  nodes={nodes}", file=sys.stderr, flush=True)
                t0 = time.time()
                r = run_cell(variant, kind, cfg_label, orch, ordr, workers,
                             nodes, path, so, args.trials, args.warmup)
                print(f"    -> {r['verdict']}  {r['rate_rec_s']} rec/s "
                      f"({time.time()-t0:.1f}s wall)", file=sys.stderr, flush=True)
                rows.append({
                    "cell": cell, "variant": variant, "kind": kind,
                    "orchestrator": orch, "order": ordr, "nodes": nodes,
                    "workers": workers, "median_s": r["median_s"],
                    "rate_rec_s": r["rate_rec_s"], "input_bytes": in_bytes,
                    "total": r["total"], "valid": r["valid"],
                    "verdict": r["verdict"],
                })

    cols = ["cell", "variant", "kind", "orchestrator", "order", "nodes",
            "workers", "median_s", "rate_rec_s", "input_bytes", "total",
            "valid", "verdict"]
    os.makedirs(os.path.dirname(os.path.abspath(args.csv)), exist_ok=True)
    with open(args.csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {args.csv} ({len(rows)} cells)", file=sys.stderr)

    # Human table.
    print(f"\n{'cell':<28}{'nodes':<7}{'median_s':>10}{'M rec/s':>10}  verdict")
    print("-" * 78)
    for r in rows:
        try:
            rate = float(r["rate_rec_s"]) / 1e6
            rs = f"{rate:10.2f}"
        except (TypeError, ValueError):
            rs = f"{'-':>10}"
        print(f"{r['cell']:<28}{r['nodes']:<7}{str(r['median_s']):>10}{rs:>10}  {r['verdict']}")

    bad = [r for r in rows if re.search(r"LOSS|EMPTY|ERROR", str(r["verdict"]))]
    if bad:
        print(f"\n{len(bad)} cell(s) flagged:",
              file=sys.stderr)
        for r in bad:
            print(f"  {r['cell']} nodes={r['nodes']}: {r['verdict']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
