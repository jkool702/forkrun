# LLM Tokenization Study: The Niche, Measured (W-PY25)

Command: `python3 python/benchmarks/bench_tokenize.py --docs 20000
--trials 3 --csv results/tokenize.csv` (+ a `--min-words 500
--max-words 800` big-doc run for the crossover).
Hardware: 28c Intel i9-7940X. Engine v3.5.2, forkrun 0.16.0,
Python 3.14. Ray 2.58, Polars 1.44.2, HF datasets 5.0.1.
Date: 2026-09-21. Corpus: seeded synthetic documents (50–500
words, Zipf-like mix) + sidecar .vocab (30k entries, single
source of truth — every system loads the same file).

## Verdict up front

The predicted 10× did NOT materialize — and the real story is
more interesting:

- **forkrun C plugin wins, modestly: 127k vs 118k docs/s
  (1.1× Executor) at 282 tok/doc, growing to 1.8× (58k vs
  39k) at 662 tok/doc.** The per-token compute advantage is
  real (~0.02µs C vs ~0.2µs Python per token), but per-document
  fixed costs (JSON parse, framing, transport, claim/ack) dilute
  it. The C advantage grows with the compute fraction — it does
  not jump 10× anywhere measured.
- **Polars cannot express this workload.** Its optimizer sees an
  opaque Python UDF (`map_batches`, serial here) and stops
  helping: 15k docs/s ≈ serial Python. This confirms the
  boundary analysis — but the forkrun side of the boundary pays
  1.1–1.8×, not 10×.
- **Document size flips the Python ranking.** Small docs:
  Executor wins (dispatch efficiency). Big docs (662 tok):
  forkrun Python (32k) beats Pool (31k) and closes on Executor
  (39k) — zero-copy mmap transport vs pickling shows up as
  records grow.
- **Ray (13k) and HF Datasets (32k) trail badly** at this scale:
  pandas/Arrow conversion + scheduling dominate 20k-doc runs.

## Standard corpus (20k docs, ~282 tok/doc, 8-system sweep best)

| System           | Docs/s | Tokens/s | Notes                        |
|------------------|--------|----------|------------------------------|
| forkrun C plugin | 127k   | 35.8M    | frozen ABI, exact JSON equality |
| Executor         | 118k   | 33.3M    | best pure Python             |
| Pool             | 110k   | 31.1M    |                              |
| forkrun Python   | 78k    | 22.1M    | order=index                  |
| HF Datasets      | 32k    | 9.0M     | batched map, in-memory       |
| Polars map_batches | 15k  | 4.2M     | serial Python UDF (verified: POLARS_MAX_THREADS=1 matches default) |
| Ray Data         | 13k    | 3.7M     | pandas batches + 3s startup  |
| Serial Python    | 12k    | 3.4M     |                              |

Per-worker shape (plugin): 33k(1w) → 60k(2w) → 97k(4w) →
131k(8w, peak) → 130k(14w) → 84k(28w, oversubscribed).
forkrun Python tracks ~60% of that curve. All counts validated
(20000/20000 everywhere); plugin outputs validated by exact
parsed-JSON equality vs Python on clean AND malformed corpora
(diversity uses round-half-even reproduced exactly, including a
double-rounding fix — see plugins/tokenize_plugin.c).

## Big-doc corpus (10k docs, ~662 tok/doc, 8 workers)

| System           | Docs/s | Tokens/s |
|------------------|--------|----------|
| forkrun C plugin | 58k    | 38.1M    |
| Executor         | 39k    | 25.8M    |
| forkrun Python   | 32k    | 21.5M    |
| Pool             | 31k    | 20.5M    |
| HF Datasets      | 17k    | 11.1M    |
| Polars map_batches | 7k   | 4.7M     |
| Serial           | 6k     | 4.0M     |
| Ray Data         | 2k     | 1.4M     |

Compute fraction up → C advantage up (1.1× → 1.8×), and
zero-copy transport starts beating pickle (forkrun Python
passes Pool). Extrapolation, not measurement: the advantage
keeps growing with tokens/doc, bounded above by the per-token
compute ratio (~10×) as fixed costs vanish.

## What this means (honest)

- The "unambiguous niche" exists but is quantitative, not
  qualitative: forkrun+C is the fastest measured system for
  tokenization (both doc sizes), with fault isolation no other
  leader has (W-PY24: survives crash-once; Pool dies, Ray
  recovers completely via task retry).
- The 10× prediction failed because it modeled per-token cost
  only. Real batches carry JSON parsing (~30% of serial time),
  output framing, and transport — Amdahl's law for the
  fixed-cost floor. Anyone citing per-token microbenchmarks
  without the pipeline around them is making the same error.
- Polars-native is N/A (inexpressible); Polars-UDF == serial.
  If your workload fits columnar expressions, use Polars
  (2.4M/s on the ML medium workload). If it needs per-record
  branching + hash lookup + variable output, this table is
  your comparison.
- Caveats: fixed per-round run order (relative order robust,
  absolutes ±20%); RSS parent-peak only; 20k/10k-doc probes,
  not TB-scale; default knobs except worker sweep (Ray default
  batching, HF batch_size=1000).
