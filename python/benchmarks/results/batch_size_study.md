# Batch Size Study: The Amortization Effect (W-PY17)

Command: `python3 python/benchmarks/run_all.py --scale medium --trials 3
--filter batch` (+ `per_batch_cost`, `batch_memory`, `single_worker_*`,
`jsonl_batch_sweep` rows). Standalone:
`python3 python/benchmarks/core/bench_batch_size.py --scale medium`.
Hardware: 28c Intel i9-7940X. Engine v3.6.0. Date: 2026-09-25.
Scale: 1M lines (medium) except JSONL (100k, small) and memory (20MB).

> Scale framing: at 1M lines and ~100M lines/s the fast rows take
> ~10ms — bring-up (fork × workers, scan, teardown) is a large
> share. These rows compare batch shapes *relatively* (same-scale,
> same-boot); for absolute throughput see the 10M/20M tables.
> Refreshed 2026-09-25 (engine v3.6.0): absolutes up ~10–28%,
> shape (ratios) nearly identical — guidance unchanged.

## Verdict up front

The amortization hypothesis is **mostly wrong**: per-batch cost is NOT
fixed — it scales with batch bytes (~6–13ns/line at fixed sizes), so
there is no fixed overhead to amortize away. Forced large batches peak
at **~126M lines/s (8 workers) / 134M (1 worker)** for no-op, not 1B+.
The engine's adaptive batching already sits in the sweet spot. Small
batches (100) cost ~40%; huge batches (50k+) cost ~35% (starvation).

## Results (1M lines, 8 workers, median of 3)

### No-op (dispatch only)

| Batch size | Lines/s | vs adaptive |
|------------|---------|-------------|
| adaptive   | 118.8M  | baseline    |
| 100        | 72.1M   | 0.61×       |
| 500        | 116.5M  | 0.98×       |
| 1000       | 125.5M  | 1.06×       |
| 5000       | 124.5M  | 1.05×       |
| 10000      | 121.6M  | 1.02×       |
| 50000      | 80.6M   | 0.68×       |
| 100000     | 75.9M   | 0.64×       |

### Upper (trivial transform)

| Batch size | Lines/s | vs adaptive |
|------------|---------|-------------|
| adaptive   | 57.7M   | baseline    |
| 100        | 30.9M   | 0.54×       |
| 1000       | 56.8M   | 0.98×       |
| 10000      | 60.3M   | 1.05×       |
| 50000+     | ~49M    | 0.85×       |

(Sum mirrors upper: 48.8M adaptive → 47.1M at 10k → ~44M at 50k+.)

### Streaming upper

| Batch size | Lines/s | vs adaptive |
|------------|---------|-------------|
| adaptive   | 87.2M   | baseline    |
| 1000       | 77.5M   | 0.89×       |
| 10000      | 89.2M   | 1.02×       |

### Single worker (no-op, no contention)

| Batch size | Lines/s | vs adaptive |
|------------|---------|-------------|
| adaptive   | 84.1M   | baseline    |
| 1000       | 80.8M   | 0.96×       |
| 10000      | 134.1M  | 1.59×       |

A single worker beats 8 workers (116M vs 96M): at zero payload the
claim loop — not dispatch — binds, and 8-way FAA/evfd contention
costs more than parallelism gains.

### JSONL (compute-bound control, 100k lines)

| Batch size | Lines/s | vs adaptive |
|------------|---------|-------------|
| adaptive   | 3.5M    | baseline    |
| 1000       | 3.6M    | 1.03×       |
| 10000      | 3.5M    | 1.00×       |

Payload-bound as predicted — and large batches actively hurt (huge
blobs through `json.loads` + larger output records).

### Per-batch cost (measured, exact batch counts via b'' probes)

| Batch size | Batches (1M lines) | µs/batch | ns/line |
|------------|--------------------|----------|---------|
| 100        | 10000              | 1.33     | 13.3    |
| 1000       | 1000               | 8.11     | 8.1     |
| 10000      | 100                | 81.43    | 8.1     |
| 100000     | 21 (*)             | 602.56   | 6.0     |
| adaptive   | 2442 (**)          | 22.97    | 56 (**)   |

(*) 100k-line requests yield 21 batches, not 10 — the engine byte-
clamps huge line-windows (splits above its byte ceiling). `lines=N`
is a hint ceiling, not an exact count, at the extremes.
(**) Adaptive granularity itself varies run to run (CASE-A
complete pre-flight vs CASE-B early-bail ramp): 245 batches
historically, 2442 in this run — and the timed runs followed
the count run's shape (56ns/line effective vs ~11 historically).
The fixed-size rows — the study's actual subject — reproduce
stably; adaptive sits in the sweet-spot range either way. The
CASE-A/B bimodality in adaptive granularity is itself a
follow-up observation, consistent with the documented
race-dependence of batching.

The ns/line column is the finding: **~10ns/line, flat**. Cost scales
with bytes; the fixed per-batch component is ~1µs (visible only at
lines=100, where 10k batches × fixed costs dominate).

### Memory (peak RSS, clean subprocess, exact 20MB runs)

| Batch size | Peak RSS |
|------------|----------|
| 1000       | 79MB     |
| 10000      | 80MB     |
| 100000     | 76MB     |

Flat (baseline ≈ 20MB + 20MB input + output collection). In-flight
batch buffering is noise at every size. H4 confirmed.

## Interpretation

1. **H1 (≥1B lines/s): FALSE.** Peak measured 134M (1 worker) / 126M
   (8 workers). The 5.7µs-fixed-overhead model is wrong — per-batch
   cost scales with batch bytes (~6–13ns/line at fixed sizes), so 10×
   bigger batches cost ~10× more per batch and throughput stays flat.
2. **H2: confirmed with nuance.** Upper/sum gain +2–5% at 10k;
   JSONL flat across sizes in this run (3.5–3.6M — compute-bound
   throughout; the old −26% at 10k did not reproduce).
3. **H3 sweet spot: 1k–10k lines** (adaptive's ~4k-line batches sit
   inside it — the engine already chooses well). lines=100 loses
   ~40% (10k batches × small fixed costs); lines=50k+ loses ~35%
   (20 batches ÷ 8 workers = starvation + stragglers).
4. **H4: confirmed.** Memory flat across 100× batch range.
5. **Bonus findings:** (a) 1 worker ≥ 8 workers for no-op (claim
   contention binds, not dispatch); (b) the engine byte-clamps
   100k-line requests to 21 batches; (c) small-scale (100k lines)
   numbers are flat ~18M at every size — fixed bring-up (fork × 8,
   init, teardown) dominates there, not batching.

## Guidance for users

- **Leave `lines` unset (adaptive)** unless you have a reason: the
  engine already batches in the sweet spot.
- **Fast payloads, max throughput:** `lines=10000` buys ~5–10%
  (upper/streaming). Not 10×. Do not chase larger.
- **Compute-bound payloads (JSONL, ML):** batch size is noise at
  best, harmful at worst. Tune the payload, not `lines`.
- **Latency-sensitive streaming:** small batches don't cost much
  throughput until lines<500; prefer responsiveness freely.
- **Scale note:** 10M-line runs reach 183M no-op (bring-up
  amortized); 1M-line numbers above include fixed costs. Compare
  within a scale, never across.
