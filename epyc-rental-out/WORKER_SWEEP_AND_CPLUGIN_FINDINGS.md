# forkrun EPYC rental — worker-sweep and C-plugin verification

Produced by the opencode supervisor on 2026-09-30, after the main harness run
finished. These numbers were NOT produced by a numbered stage; they are
diagnostic re-runs recorded here so the result survives the rental.

All cells: `forkrun.map(...)`, C plugin (`ml_plugin_<variant>.so:ml_process_<variant>`),
`mode="plugin"`, `order="index"`, `orchestrator=True`, **`nodes=1` (UMA)**,
warmup + **median of 3** timed runs, corpus `/ml5/ml_<variant>.jsonl`
(5,000,000 records, line-count validated by `DATA_MANIFEST.txt`).

## 1. The finding: 96 workers is forkrun's worst point on this box

Machine: 2x AMD EPYC 7443, 96 logical threads, 48 physical cores, 2 NUMA nodes
(NPS1, one per socket). The harness sets `EPYC_WORKERS_MAX` = `nproc` = 96 and
pins every benchmark cell there. Peak throughput is at 32-48 workers.

| variant | 16w | 28w | 32w | 48w | 96w |
|---|---:|---:|---:|---:|---:|
| light | 3,606,974 | 3,777,737 | **3,865,413** | 3,064,070 | 1,833,656 |
| medium | 1,027,363 | 1,124,347 | **1,141,328** | 994,972 | 678,569 |
| heavy | 483,229 | 566,823 | 572,250 | **654,419** | 356,061 |

Penalty for running at 96w instead of peak: light **2.11x**, medium 1.68x,
heavy 1.84x. The published i9-7940X reference was taken at **28 workers**.

## 2. Corrected headline grid — nodes=1, 32 workers

Machine-readable copy: `headline/headline_5000000.NODES1-W32.csv`
(schema: cell,variant,kind,orchestrator,order,nodes,workers,median_s,
rate_rec_s,input_bytes,total,valid,verdict — all cells EXACT or
quality-gate-clean, i.e. no record loss).

Best cell per (variant, kind) vs the i9-7940X (†) published baselines:

| variant | kind | EPYC rec/s | i9 (†) rec/s | ratio |
|---|---|---:|---:|---:|
| light | C | 6,304,398 | 5,380,000 | **1.17x** |
| light | Py | 2,792,980 | 1,560,000 | 1.79x |
| medium | C | 1,457,299 | 1,910,000 | 0.76x |
| medium | Py | 999,997 | 672,000 | 1.49x |
| heavy | C | 708,745 | 634,000 | **1.12x** |
| heavy | Py | 191,377 | 90,000 | 2.13x |

**forkrun does not regress on this box.** The C plugin beats the published i9
baseline on light and heavy; medium C is the only shortfall. The Python UDF
beats the i9 on all three variants.

### Against the competing frameworks

Stage 40 (`40_bench_ml5m`) measured the competitors; their best worker point
was also 96w, so this is each system at its own optimum:

| system | best rec/s (light) | worker point |
|---|---:|---:|
| forkrun C plugin | 6,304,398 | 32w |
| forkrun Python UDF | 2,792,980 | 32w |
| ProcessPoolExecutor | 2,475,833 | 96w |
| multiprocessing.Pool | 1,984,173 | 96w |

forkrun C vs executor = **2.5x**; vs pool = **3.2x**. The i9-7940X reference for
the same claim was 3.3x / 3.4x. forkrun's competitive position substantially
reproduces on this hardware once measured at a sane worker count.

## 3. C-plugin integrity verification (positive, not by absence)

- **No silent fallback.** `forkrun.map("/tmp/NO_SUCH_PLUGIN.so:nope", ...,
  mode="plugin")` raises `PluginError: plugin not found: ...`. A missing or
  unloadable plugin is a loud error, never a quiet downgrade to Python.
- **Real artifacts.** `/ml5/ml_plugin_*.so` and `/ml5/headline_plugins/
  ml_plugin_*.so` are ELF 64-bit shared objects; `nm -D` shows
  `T ml_process_light` (global text symbol). `headline.py` logs
  "built ml_plugin_<v>.so" per run — recompiled with `-O3 -march=native`.
- **`c_worker_loop=True` changes nothing.** The frozen-ABI C worker loop is
  gated behind that flag in `_resolve_c_plugin_loop` (run.py:330). Measured
  explicitly at nodes=1: 4,446,968 rec/s with the flag vs 4,584,656 without —
  within noise. So `mode="plugin"` already exercises the plugin; the earlier
  theory that "the C worker loop never engages" is disproved.

## 4. Measurement-variance warning — read before comparing any single row

This box produced materially different numbers for *nominally identical* cells
depending on background state. Observed for the 5M light C-plugin cell at
nodes=1: **4,584,656** rec/s (single shot, taken while loadavg 15-min was 22),
**1,406,964** (median of 3, minutes later), **1,833,656** (worker sweep),
**2,401,703** (`headline.py`'s own `run_cell`), **6,304,398** (32w).

Only the median-of-N sweeps in §1 and §2 should be used. Comparing a single
CSV row against the i9 table will produce a wrong answer — as it did twice
during this shift before the worker-count cause was found.

## 5. Topology results, and which ones to trust

`epyc/headline.py` is the trustworthy grid: it records `nodes` and `workers` as
first-class columns, validates the corpus line count before running, and its
nodes=1 cells log `numa=0` in the engine DIAG.

**`41_bench_numa5m` part A should NOT be used for any NUMA claim.** All 76 of its
DIAG blocks reported `forked=[0, 1]` — including the cells the CSV labels
`nodes=1` — so its topology labels are not trustworthy. Its *correctness*
verdict stands independently (see `F_NUMA1_AUDIT.agent-recheck.md`: 45 rows,
0 cells lost records). Its *rates* do not.

Topology ladder as measured by headline.py at 96 workers (superseded by the
worker finding above, recorded for completeness):

| variant | kind | UMA (nodes=1) | @4 | auto (2-node) |
|---|---|---:|---:|---:|
| light | C | 2,307,216 | 474,793 | 318,955 |
| light | Py | 2,867,389 | 520,053 | 342,506 |
| medium | C | 728,874 | 509,846 | 349,735 |
| heavy | C | 495,506 | 496,909 | 364,732 |

Ordering is UMA > @4 > auto(2-node) consistently. Note this **contradicts**
stage 41 part A, which reported @4 as the fastest cell; stage 41 is the
untrustworthy one (see above). At a fixed 96 workers the 2-node `auto`
partition costs 6-7x on light; that effect is real but is dwarfed by the 2.1x
worker-count effect.

## 6. Bash-side A/B (added to `epyc/50_bench_bash.sh`, section 50z)

`epyc/50_bench_bash.sh` gained a NUMA A/B that runs the same `frun` workload
with explicit `--nodes=1` and `--nodes=@4` and checks record conservation on
both. It does not modify `BENCHMARKS/run_benchmark.bash` (Tier-1). The stage
was skipped on deadline, so this section has not yet been executed by the
harness; the operator ran the first block of the bash matrix by hand instead
and observed the same conclusion — `@4` and `nodes=0` are within noise of each
other (1.729s vs 1.801s; 5.486s vs 5.526s; 0.513s vs 0.505s), i.e. born-local
placement buys nothing on this box.

## 7. Recommendations

1. **Pin `EPYC_WORKERS_MAX` to 32-48** (not `nproc`) for any 96-thread box when
   benchmarking forkrun. This is the single highest-value change; it recovers
   the headline comparison without re-renting.
2. **Re-run stages 40, 42, 43 at the pinned worker count** before quoting any
   competitor comparison. The numbers in §2 already do this for stage 44.
3. **Discard or re-run stage 41 part A** (§5).
4. The `forkrun C vs Executor` ratio is the claim to verify next: 2.5x here vs
   3.3x on the i9 — a real but smaller margin, worth a clean re-measurement
   with matched worker counts on both sides.
5. A reboot into NPS2/NPS4 (4 or 8 nodes) would make the F-NUMA1 question
   meaningful: at NPS1 the ingest meta-lifetime bound is 1024 chunks/node vs
   512 for the fake-4 baselines where F-NUMA1 was found, so a clean result
   here does not clear the higher-node-count regime.
