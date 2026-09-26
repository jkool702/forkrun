# forkrun Complete Benchmark Results (v3.6.0 release)

> **How to read this file:** §2/§5/§7 are steady-state numbers
> (5M+ records / 500k+ docs — bring-up amortized). §4 and the
> 20k-doc rows are **startup-latency microbenchmarks**: at
> 20–50k records and ~1M rec/s the whole run takes 20–50ms,
> so fork+scan+teardown dominate; their rank order is
> meaningful, their absolutes understate sustained throughput
> — always read them alongside a steady-state section.
> forkrun rows re-measured 2026-09-25 (engine v3.6.0);
> competitor rows keep their original dates (those codebases
> didn't change).

Consolidated from every study in `python/benchmarks/results/`,
`DOCS/python/AI_benchmark_results.md`, the main README (bash
engine), and fresh re-runs on 2026-09-25. Hardware throughout:
28c Intel i9-7940X unless noted. **Freshest forkrun numbers are
listed first in each section**; older rows are kept where they
carry data the re-runs didn't (competitors, sweeps, fault modes).

Conventions: M = million records (or lines/docs as labeled) per
second. `nodes=1` = UMA; `@N`/`auto` = multi-node pipeline
(fake-4 boot) or forced-logical (`@4` on UMA).

---

## 1. Bash engine (`frun`) vs GNU Parallel — main README, 100M+ lines

| Workload | forkrun | GNU Parallel | Speedup | Notes |
|---|---|---|---|---|
| Max batch external (`-l 1:-1 /bin/true`) | **191.4 M lines/s** | ~58 k | **~3300×** | zero-copy `vfork` fast path |
| Default external binary (`/bin/true`) | **86.9 M lines/s** | ~58 k | **~1500×** | bypasses Bash AST |
| Bash builtin (`:`, quoted args) | **25.0 M lines/s** | ~58 k | **~430×** | standard array mode |
| Ordered output (`-k`, external) | **86.9 M lines/s** | 57 k | **~1520×** | ordering ~zero overhead |
| External `printf '%s\n'` (I/O heavy) | **52.6 M lines/s** | ~58 k | **~900×** | formatting + output |
| `-s` stdin passthrough (no-op) | **1.04 B lines/s** | 6.05 M (`--pipe`) | **~172×** | `splice()` streaming |
| `-b 512k` byte batches (no-op) | **2.51 B lines/s** | 6.02 M (`--pipe`) | **~417×** | kernel-limited |
| CPU utilization (aggregate, 396 mixed benchmarks) | **~90%** (95–99% sustained default/external) | 9.6% total, 6% useful | — | no central dispatcher |
| Born-local NUMA placement | 0.0–0.2% cross-socket (file ingest) | — | — | fake-4 figures are worst case |

Typical shell-builtin range 50–400×; microbenchmark extremes
(`/bin/true`) reach ~1500–3300×. ≥1B-line runs show 30–50% higher
peaks (fixed ~30ms bring-up amortized).

## 2. Python ML pipeline, 5M/20M records, 28 workers — FRESH 2026-09-25 (UMA + forced `@4`, terminated framing, exact totals)

> Steady-state table. For the startup-latency micro view (50k
> records), see §4 — same rank order, lower absolutes.

| test | type | nodes | M rec/s | time (s) | total (exact) | valid |
|---|---|---|---|---|---|---|
| light | C-plugin | 1 | 6.67 | 0.75 | 5000000 | 5000000 |
| light | C-plugin | @4 | 4.76 | 1.05 | 5000000 | 5000000 |
| medium | C-plugin | 1 | 2.35 | 2.13 | 5000000 | 4997892 |
| medium | C-plugin | @4 | 1.83 | 2.73 | 5000000 | 4997892 |
| heavy | C-plugin | 1 | 0.70 | 7.12 | 5000000 | 4997982 |
| heavy | C-plugin | @4 | 0.59 | 8.43 | 5000000 | 4997982 |
| light-20M | C-plugin | 1 | 6.18 | 3.24 | 20000000 | 20000000 |
| light-20M | C-plugin | @4 | 5.46 | 3.66 | 20000000 | 20000000 |
| medium-20M | C-plugin | 1 | 2.49 | 8.04 | 20000000 | 19991640 |
| medium-20M | C-plugin | @4 | 1.90 | 10.53 | 20000000 | 19991640 |
| heavy-20M | C-plugin | 1 | 0.69 | 28.84 | 20000000 | 19991658 |
| heavy-20M | C-plugin | @4 | ~0.76 | ~26 | 20000000 | 19991658 |
| light | python | 1 | 1.48 | 3.38 | 5000000 | 5000000 |
| light | python | @4 | 1.17 | 4.28 | 5000000 | 5000000 |
| medium | python | 1 | 0.71 | 7.02 | 5000000 | 4997892 |
| medium | python | @4 | 0.61 | 8.24 | 5000000 | 4997892 |
| medium | spawn (`tr`) | 1 | 1.59 | 3.14 | 5000000 | — |
| medium | spawn (`tr`) | @4 | 1.22 | 4.09 | 5000000 | — |

Medium/heavy `total−valid` = quality-gate drops (2,108 / 2,018
at 5M; 8,360 / 8,342 at 20M), identical both topologies.
Method: median-of-3 + warmup, `order="index"`; medium C =
yyjson single-pass plugin.

NOTE (heavy-20M `@4`, 26.9GB): 2 of ~10 runs returned silently
with ~25% of records (≈ one node's share) and no error; all
other runs exact. Suspected per-node worker-fork gating under
slow-draining huge rings on forced-logical topology — flagged
for dedicated diagnosis, not a counting artifact (valid≈total
in every run). `nodes=1` stable 5/5.

## 3. Python ML pipeline vs best-of-the-best — W-PY29 era (same box class, best of 8/14/28w; competitors NOT re-run since)

| System | Light 5M | Medium 5M | Heavy 5M |
|---|---|---|---|
| forkrun C plugin | **6.61M** | **2.37M** | **718k** |
| ProcessPoolExecutor | 1.64M | 797k | 94k |
| multiprocessing.Pool | 1.60M | 757k | 94k |
| forkrun Python UDF | 1.74M | 730k | 95k |
| Ray Data | 250k | 184k | 56k |
| HF Datasets | 120k | 90k | 44k |
| Polars native (medium only) | — | **2.20M** | — |
| DuckDB native (medium only) | — | 189k | — |
| forkrun C advantage (vs best UDF) | **4.0×** | **3.0×** | **7.6×** |

forkrun cells re-measured 2026-09-25 (engine v3.6.0; per-worker
sweep 8/14/28w in §10 of `AI_benchmark_results.md`); competitor
cells are W-PY29-era and stable.

Per-worker shape (5M): light C 3.9M (8w) → 6.3M (14w) → 6.5M
(28w); medium C 983k → 1.32M → 1.62M; heavy C 359k → 516k →
611k. Python UDF at Executor parity on all variants.
Natively-expressible work goes to Polars (4.4× best UDF);
DuckDB loses to forkrun-UDF. Fault injection: forkrun
survives truncated (4887-record clean prefix, respawn works,
signal death skips escrow — parent-side replay flagged
follow-up); Ray recovers completely (task retry); Pool hangs
(TimeoutError, no retry). Recovery tax single-digit % (burst
28×SIGKILL ~20% at 28w; lone SIGSEGV ~0–3%).
(`DOCS/python/AI_benchmark_results.md`, engine v3.5.2+W-PY29.)

## 4. Python ML pipeline, 50k records — STARTUP-LATENCY MICROBENCHMARK (W-PY24 scale)

At 50k records and ~1M rec/s the whole run takes ~50ms:
bring-up (fork + scan + teardown) dominates, so these rows
measure startup latency plus throughput, NOT steady state.
Rank order is meaningful; absolutes understate sustained
throughput — always read alongside §2 (5M steady state).

| System | Light | Medium | Heavy |
|---|---|---|---|
| Serial Python | 147k | 63k | 6.4k |
| mp.Pool (best) | 856k | 457k | 84k |
| ProcessPoolExecutor | 1023k | 551k | 84k |
| HF Datasets | 81k | 62k | 33k |
| forkrun Python | 580k | 293k | 68k |
| forkrun C plugin | 1047k | 481k | 216k |
| Ray Data | 43k | 38k | 17k |

forkrun Python at 60–75% of Executor; heavy/compute-bound
compresses the field. (`ml_pipeline_study.md`.)

## 5. Tokenize (LLM) — FRESH (UMA, 28w; 500k docs + 1M docs steady state)

| System | 500k Docs/s | 500k Tokens/s | 1M Docs/s |
|---|---|---|---|
| forkrun C plugin | **304.5k** | **85.9M** | **344k** |
| Executor | 167.6k | 47.3M | 168k |
| Pool | 159.9k | 45.1M | 165k |
| forkrun Python | 138.8k | 39.2M | 152k |
| HF Datasets | 50.5k | 14.0M | — (too slow at 1M) |
| Ray Data | 27.2k | 7.7M | — (too slow at 1M) |
| Polars map_batches | 14.9k | 4.2M | — |
| Serial Python | 12.1k | 3.4M | — |

All complete at both scales (500000/500000, 1000000/1000000);
plugin outputs exact-JSON-equal vs Python. 20k-doc study
retired to microbenchmark status (see `tokenize_study.md`):
at ~200ms total, bring-up dominates and ranks wobble with
box state. Big-doc crossover (662 tok/doc, 8w): C 58k (1.5×
Executor 39k), Python 32k > Pool 31k. (`tokenize_study.md`,
`tokenize.csv`.)

## 6. NUMA steady state, fake-4 boot — W-PY35 era (same-boot UMA baselines)

> Post-W-PY39 addendum lives in `numa_5m_study.md` — the
> "NUMA faster than UMA" verdict below predates the forked
> materialized scanner (+35% UMA). Current code leads on UMA
> single-socket (see §2); fake-4 NUMA ratios below stand as
> topology findings. Do not cite the UMA absolutes or ratios
> below as current.

| Workload | C nodes=1 | @2 | auto/4 | Python 1 / auto |
|---|---|---|---|---|
| Light 5M (508MB) | 5.8M | 5.4M (0.93) | 5.6M (0.97) | 1.6M / 1.6M |
| Medium 5M (2.2GB) | 1.7M | 1.9M (1.12) | 2.1M (1.24) | 655k / 712k |
| Heavy 5M (6.4GB) | 552k | 709k (1.28) | 710k (1.29) | 88k / 90k |
| Light 20M | 4.6M | — | 5.5M (1.20) | 1.5M / 1.6M |
| Medium 20M | 1.4M | — | 1.8M (1.29) | 595k / 701k |
| Heavy 20M | 545k | — | 730k (1.34) | 87k / 90k |
| Tokenize 500k C | 317k d/s | — | 342k (1.08, 2.2× Exec) | 140k / 148k |
| Spawn 1M (`tr`) | 1.6M | — | 1.2M (0.75) | C-loop gate (UMA-only) |

No NUMA software tax at steady state on worst-case fake
hardware (parity → +29%); spawn is the lone regression
(0.75×, spawn-cost dominated). Mechanism (W-PY36, perf +
strace): NUMA wins via pipeline overlap (10.1 vs 8.2 avg
CPUs), DESPITE worse efficiency everywhere (+17.5% cycles,
IPC 1.3→1.1, 7× ctx switches, 67× migrations). Framework
self <1% of cycles; ~73% sits in payload `snprintf` float
formatting. Post-W-PY39 UMA (+35% forked-scanner overlap)
compresses these ratios — see §2 fresh UMA-first numbers.
Worker sweep 1–28w monotonic both topologies; streaming +
`@2` slow consumer bounded (+0MB RSS). (`numa_5m_study.md`,
`numa_5m.csv`, `numa_20m.csv`.)

## 7. Python core engine, 10M lines — FRESH (engine v3.6.0)

| Workload | Rate | Notes |
|---|---|---|
| Python no-op (run/map/stream) | 198M / 196M / 191M | overhead-bound at 10M |
| Python transform (upper) | 69M (7.2× serial 9.6M) | parent-collect bound |
| Python compute (sum) | 58M | — |
| C plugin callback (ctypes / v1 loop) | 58M / 54M | — |
| Spawn external (`cat`/`tr`, v0+v1) | 27.4M / 27.3M | subprocess-bound |
| JSONL ingestion | 3.6M rec/s | payload-bound |
| Filter + transform / Aggregation | 31M / 52M | — |
| stream() vs map() | 1.8× faster | drain overlaps produce |
| ordered vs unordered | 1.11–1.34× | reassembly grows w/ batches |
| Pool baseline | 2.0M upper | per-line pickling; forkrun ~23× |

No-op/upper/sum up ~8–10% over v3.5.2; spawn nearly doubled
(15M→27M, C spawn-loop/v1 fast paths). Memory: +0MB
discard/streaming-flat; output-sized under `map()`;
slow-consumer stream window-bounded. (`large.md`,
`large.csv`.)

## 8. Batch sizing, 1M lines/8w — FRESH (relative shapes; ~10ms rows carry bring-up share)

| Batch | No-op | Upper | Stream upper |
|---|---|---|---|
| adaptive (~4k) | 118.8M | 57.7M | 87.2M |
| 100 | 72.1M (0.61×) | 30.9M | — |
| 1k–10k | 117–126M | 51–62M | 78–89M |
| 50k+ | ~76–81M (starvation) | ~49M | — |
| 1 worker adaptive/10k | 84.1M / 134.1M | — | — |

Per-batch cost ~10ns/line at every size (no fixed overhead
to amortize); peaks 96M (8w) / 116M (1w) — not 1B+.
`lines=100` loses ~40%, `lines=50k+` ~35%. JSONL regresses
at 10k (payload-bound). Memory flat 76–80MB across 100×
range. (`batch_size_study.md`.)

## 9. Splice / byte modes, 1M–10M lines — FRESH

| Mode | 1M | 10M (130MB) |
|---|---|---|
| `lines=1000` Python | 121.1M | 168M |
| `bytes=64K–4M` Python | ~126–133M (1.10×) | ~175–190M (~1.1×) |
| `mode="splice"` | 57–61M | 70–80M (≈ passthrough) |
| Splice stream | 81.2M | **91.7M** (pipelined drain) |
| Python passthrough | 62.1M | 73.4M |

Ceiling: sendfile ~4.4GB/s + parent parse ~3GB/s cap this
box at ~230M for `map()`; 2B needs ~26GB/s end to end.
(`splice_study.md`.)

## 10. Plugin generations, medium 5M (W-PY31/32 era — parser-relative deltas stand; absolutes superseded by §2 fresh 2.35M yyjson-spass 28w UMA)

| Plugin | 8w | 14w | 28w |
|---|---|---|---|
| scalar C | 1,117k | 1,533k | 1,664k |
| yyjson C | 1,473k (+32%) | 1,891k (+23%) | 1,875k (+13%) |
| yyjson single-pass | 1,602k (+9%) | 2,023k (+7%) | 2,077k (+11%) |

Parser swaps cap at ~2M/s (framework per-batch cost binds,
not parsing); kept as defaults (free, byte-exact).
Spawn C-loop ≡ Python loop (±4% — architectural value, not
speed). (`AI_benchmark_results.md` W-PY31–33.)

## Supersession log (what replaces what)

- §2 fresh UMA + `@4` rows (2026-09-25, v3.6.0) supersede all
  older UMA absolutes (W-PY35 `numa_5m_study` Part A UMA column,
  `PERFORMANCE.md` pre-refresh table, `AI_benchmark_results`
  pre-refresh forkrun cells).
- 20k-doc / 50k-record studies are startup-latency
  microbenchmarks by the scale rule above — cited for rank
  order and crossover analyses, never for throughput claims.
- Fake-4 NUMA ratios (§6) stand (topology finding).
- §5 fresh 500k + new 1M-doc tokenize supersede the 20k-doc
  study for scale; its big-doc crossover (1.1×→1.8×) still
  stands.
- W-PY24 50k competitor matrix (§4) stands (competitors not
  re-run; forkrun rows re-measured faster in §2).
- Counting note (§6 Part-D text) is retired by terminated
  framing: totals now exact, no junction artifact.
- Known open item (not a counting artifact): heavy-20M `@4`
  returned silently partial (~25%, one node's share) in 2 of
  ~10 runs with no error; `nodes=1` stable. Flagged for
  dedicated per-node fork-gate diagnosis.
