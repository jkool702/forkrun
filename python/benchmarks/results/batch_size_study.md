# Batch Size Study: The Amortization Effect (W-PY17)

Command: `python3 python/benchmarks/run_all.py --scale medium --trials 3
--filter batch` (+ `per_batch_cost`, `batch_memory`, `single_worker_*`,
`jsonl_batch_sweep` rows). Standalone:
`python3 python/benchmarks/core/bench_batch_size.py --scale medium`.
Hardware: 28c Intel i9-7940X. Engine v3.5.2. Date: 2026-09-20.
Scale: 1M lines (medium) except JSONL (100k, small) and memory (20MB).

## Verdict up front

The amortization hypothesis is **mostly wrong**: per-batch cost is NOT
fixed — it scales with batch bytes (~10ns/line across all sizes), so
there is no fixed overhead to amortize away. Forced large batches peak
at **~96M lines/s (8 workers) / 116M (1 worker)** for no-op, not 1B+.
The engine's adaptive batching already sits in the sweet spot. Small
batches (100) cost ~40%; huge batches (50k+) cost ~35% (starvation).

## Results (1M lines, 8 workers, median of 3)

### No-op (dispatch only)

| Batch size | Lines/s | vs adaptive |
|------------|---------|-------------|
| adaptive   | 92.5M   | baseline    |
| 100        | 56.7M   | 0.61×       |
| 500        | 89.3M   | 0.97×       |
| 1000       | 95.9M   | 1.04×       |
| 5000       | 91.9M   | 0.99×       |
| 10000      | 92.5M   | 1.00×       |
| 50000      | 63.3M   | 0.68×       |
| 100000     | 61.5M   | 0.66×       |

### Upper (trivial transform)

| Batch size | Lines/s | vs adaptive |
|------------|---------|-------------|
| adaptive   | 51.4M   | baseline    |
| 100        | 29.2M   | 0.57×       |
| 1000       | 50.2M   | 0.98×       |
| 10000      | 56.1M   | 1.09×       |
| 50000+     | ~41M    | 0.80×       |

(Sum mirrors upper: 43.2M adaptive → 44.9M at 10k → ~34M at 50k+.)

### Streaming upper

| Batch size | Lines/s | vs adaptive |
|------------|---------|-------------|
| adaptive   | 68.1M   | baseline    |
| 1000       | 67.8M   | 1.00×       |
| 10000      | 76.7M   | 1.13×       |

### Single worker (no-op, no contention)

| Batch size | Lines/s | vs adaptive |
|------------|---------|-------------|
| adaptive   | 92.3M   | baseline    |
| 1000       | 73.6M   | 0.80×       |
| 10000      | 116.6M  | 1.26×       |

A single worker beats 8 workers (116M vs 96M): at zero payload the
claim loop — not dispatch — binds, and 8-way FAA/evfd contention
costs more than parallelism gains.

### JSONL (compute-bound control, 100k lines)

| Batch size | Lines/s | vs adaptive |
|------------|---------|-------------|
| adaptive   | 2.7M    | baseline    |
| 1000       | 2.9M    | 1.07×       |
| 10000      | 2.0M    | 0.74×       |

Payload-bound as predicted — and large batches actively hurt (huge
blobs through `json.loads` + larger output records).

### Per-batch cost (measured, exact batch counts via b'' probes)

| Batch size | Batches (1M lines) | µs/batch | ns/line |
|------------|--------------------|----------|---------|
| 100        | 10000              | 1.77     | 17.7    |
| 1000       | 1000               | 11.50    | 11.5    |
| 10000      | 100                | 110.31   | 11.0    |
| 100000     | 21 (*)             | 753.31   | 7.5     |
| adaptive   | 245                | 46.24    | ~11     |

(*) 100k-line requests yield 21 batches, not 10 — the engine byte-
clamps huge line-windows (splits above its byte ceiling). `lines=N`
is a hint ceiling, not an exact count, at the extremes.

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

1. **H1 (≥1B lines/s): FALSE.** Peak measured 116M (1 worker) / 96M
   (8 workers). The 5.7µs-fixed-overhead model is wrong — per-batch
   cost is ~10ns/line at every size, so 10× bigger batches cost 10×
   more per batch and throughput stays flat.
2. **H2: confirmed with nuance.** Upper/sum gain +4–9% at 10k;
   JSONL regresses −26% at 10k (payload-bound, large blobs hurt).
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
