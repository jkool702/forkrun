# W-EXECTYPES Completion Report — Executor + Native-C Control Row

**Branch:** `NEW/REFACTOR2.12` @ `8f7550a4` (+ this order's commits).
**Gates:** harness sanity 6/6 green before any quoted measurement; all cells
exact-totals; environment echoed; **zero product changes** (`python/forkrun/`,
engine, `frun.bash` untouched — verified by `git status`). No tag, no push.

## Cells (median-of-3 + warmup, 28 workers, all totals exact)

| Cell | Median (trials) | Rate | Verdict |
|---|---|---|---|
| EXEC-C light fine (~4k-line, 1221 tasks) | 0.663s (0.688, 0.623, 0.663) | **7.54M/s** | ok, 5M/5M |
| EXEC-C light coarse (~100k-line, 50 tasks) | 0.701s | 7.13M/s | ok-secondary |
| EXEC-C medium fine | 1.563s (1.600, 1.525, 1.563) | **3.20M/s** | ok, 5M/5M |
| EXEC-C medium coarse | 2.047s | 2.44M/s | ok-secondary |
| EXEC-C heavy-20M fine (4883 tasks) | 19.312s (19.429, 19.312, 19.281) | **1.04M/s** | ok-20M-scale, 20M/20M |

## Decomposition (the row's purpose, explicit prose)

- *Payload dividend* (Exec-C ÷ Exec-Py): light **4.6×**, medium **4.0×**,
  heavy **~11×** (scale-mismatched: Py row at 5M, C row at 20M).
- *Architecture dividend* (forkrun-C(max) ÷ Exec-C): light **0.89×**, medium
  **0.73×**, heavy **~0.66×** — Executor wins all three primary cells at
  matched (~4k-line = forkrun default batch, verified in code) granularity.
  Vs (†): 0.71× / 0.60× / ~0.62×.

## Pre-registered-outcome honesty note

The order pre-registered Exec-C "likely between Executor-Python and
forkrun-C on light" with "a real chance it wins the light cell", plus a
possible coarse-chunking flip. As measured: Exec-C won **all three** cells
(light +13% over (max), medium +37%, heavy-20M ~+50% over same-scale refs),
and fine beat coarse on both workloads (no flip — 50 tasks/28 workers leaves
a 28+22 straggler wave). No re-rolls; the table ships these numbers with the
§0-drafted release framing (pool competitive on pre-chunked C light work;
forkrun's advantage is zero-copy-without-prechunking, recovery, ordering,
NUMA). Same-boot caveat applies across the 09-25/29 → 09-30 freeze boundary
(thermal-state uncertainty on absolutes; ratios carry it too).

## What this does NOT prove

Single reasonable Executor-ctypes configuration (two granularities), not an
exhaustively tuned optimum in either direction; output-transport asymmetry
(pickle-back vs memfd/orderer) is part of each honest path; heavy payload
dividend mixes scales; Python-UDF rows untouched by this control; 25.7 GB
heavy parent peak is `map`-iterator output buffering (documented, no swap
pressure, trials ±0.4%).

## Addendum (same day): setup-inclusive correction

Review question: was the range pre-computation inside the timed region? No —
untimed setup (0.7s / 0.9s / 7.9s in-session) while forkrun's scan runs timed.
Corrected effective rates: light **3.67M/s**, medium **2.03M/s**, heavy-20M
**735k/s** (arithmetic on recorded numbers, no re-measurement; setup
re-measured post-hoc warm-cache at 0.655/0.895/5.475s as sensitivity bound).
Revised verdict: forkrun-C(max) leads light (1.83×) and medium (1.15×);
Executor leads heavy narrowly (~0.94× inverted); vs (†): 1.47× / 0.94× /
~0.87×. The table, footnote, results file (§3/§4/§6/§7), and CSV twin
(`setup_s` + `eff_rate_rec_s` columns, blank on frozen rows) all carry the
correction. Note: my first pass at the two coarse CSV values was arithmetically
wrong (caught by recomputation before commit: 3842725.0 / 1696473.7).

## Files

- `python/benchmarks/ml/bench_exectypes.py` (harness, `--sanity` green:
  task-types, lazy-load marker==task set, parent-clean, totals+framing,
  JSON well-formedness, 2.8 MB forkrun-byte-identity)
- `python/benchmarks/results/exectypes_2026-09-30.md` (full record)
- `python/benchmarks/results/headline_2026-09-30.csv` (successor twin:
  frozen 12 + 5 `EXEC-C-*`)
- `python/benchmarks/results/RELEASE_v3.6.0.md` §0 (new ‡ row + 3rd speedup
  row + footnote + supersession log)

## Incidents

1. Sanity lazy-load gate initially asserted all 28 workers load — failed
   (11/40 fast tasks; idle workers never scheduled). Root cause: gate
   over-strict, not harness — replaced with exact
   task-pid-set == marker-pid-set assertion (deterministic, stronger claim).
2. `_RETURN_PID` global never reached workers: python 3.14 defaults to
   **forkserver**. Fixed by passing `want_pid` per-task; recorded as a
   methodology strength (truly post-spawn loads; same default as the frozen
   Executor rows).
3. No halt-and-report triggers: nothing observed casts doubt on forkrun's
   frozen numbers; the control's direction (executor wins C-cells) is
   consistent with per-batch orchestration cost dominating at C payload
   speeds, not with any forkrun measurement error.
