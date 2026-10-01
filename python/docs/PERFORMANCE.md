# forkrun Performance (what to expect)

Same-boot measured, 28 workers, 5M records, `order="index"`
(full tables: `python/benchmarks/results/numa_5m_study.md`
and `RELEASE_v3.6.0.md`). Your box will differ; relative
order is the robust reading. All rows below are steady
state (5M+ records / 500k+ docs — bring-up amortized); see
the release table for the 20k–50k startup-latency
microbenchmarks and why they read lower.

## Throughput (records/s)

| Workload (size) | C plugin | Python UDF | Executor | Pool |
|---|---|---|---|---|
| Light (508MB) | 6.5M | 1.7M | 1.7M | 1.5M |
| Medium (2.2GB) | 2.3M | 730k | 755k | 757k |
| Heavy (6.4GB) | 670k | 95k | 93k | 92k |
| Tokenize (500k docs) | 305k docs/s | 139k | 168k | 160k |

forkrun cells re-measured 2026-09-25 (engine v3.6.0, UMA,
28w, exact totals); Executor/Pool cells are W-PY29-era and
stable (those codebases didn't change — same standing:
Python UDF at Executor parity, C plugin 2–4× the best
UDF). absolutes carry ±10–20% run variance; relative order
is the robust reading.

forkrun C wins 2.8–7.6×; forkrun Python runs at
`ProcessPoolExecutor` parity. Cost model (profiled):
~73% of cycles sit in payload work (e.g. `snprintf`
formatting), <1% in the framework — make the payload
faster before touching anything else.

## Release numbers (v3.6.0, UMA, exact counts)

28 workers, median-of-3 + warmup, `order="index"`, 5M
records (20M row: 20M). `nodes=1` vs `@4` (4 forced logical
nodes over 1 socket — the multi-node pipeline leg available
on UMA). Rate is on valid records; `total` == input records
on every row (filtered records emit blanks — medium drops
2,108 and heavy 2,018 to quality gates, visible as
total−valid).

| test | type | nodes | M rec/s | time (s) | total (exact) | valid |
|---|---|---|---|---|---|---|
| light | C-plugin | 1 | 6.52 | 0.77 | 5000000 | 5000000 |
| light | C-plugin | @4 | 4.74 | 1.05 | 5000000 | 5000000 |
| medium | C-plugin | 1 | 2.29 | 2.18 | 5000000 | 4997892 |
| medium | C-plugin | @4 | 1.80 | 2.78 | 5000000 | 4997892 |
| heavy | C-plugin | 1 | 0.67 | 7.47 | 5000000 | 4997982 |
| heavy | C-plugin | @4 | 0.58 | 8.56 | 5000000 | 4997982 |
| medium-20M | C-plugin | 1 | 2.39 | 8.36 | 20000000 | 19991640 |
| medium-20M | C-plugin | @4 | 1.82 | 10.97 | 20000000 | 19991640 |
| light | python | 1 | 1.35 | 3.70 | 5000000 | 5000000 |
| light | python | @4 | 1.09 | 4.59 | 5000000 | 5000000 |
| medium | python | 1 | 0.67 | 7.48 | 5000000 | 4997892 |
| medium | python | @4 | 0.59 | 8.52 | 5000000 | 4997892 |

## Scaling shape

- Medium C: 361k (1w) → 965k (4w) → 1.6M (14w) → 1.7M
  (28w). Python plateaus 14→28w (oversubscription, not a
  framework cliff). No scaling cliffs anywhere.
- `lines=1k–10k` is the sweet spot (adaptive already
  chooses inside it). `lines=100` loses ~40% (per-batch
  costs dominate); `lines=50k+` loses ~35% (starvation:
  too few batches per worker).
- Multi-node pipeline cost (`@4` forced over 1 socket,
  v3.6.0 table above): light 6.52M→4.74M, medium
  2.29M→1.80M, heavy 0.67M→0.58M (0.73–0.87×). On
  single-socket, UMA is simpler and slightly faster; on
  real multi-socket, NUMA adds born-local memory wins.
- 20M inputs hold the ratios (medium C 2.39M→1.82M) —
  steady-state, no degradation with size.

## Memory

- `map()`: output-sized parent (it collects everything —
  inherent, not a leak).
- `stream()`: flat. 10MB in with 5× amplification and a
  1ms/batch consumer: +0MB parent RSS (backpressure holds
  only the in-flight window).
- `streaming=True`: bounded ingress (reaper hole-punches
  acked prefixes) at ~2–3× CPU — the TB-scale capability
  price, not a default.

## How to benchmark your workload

```bash
python3 python/benchmarks/ml/bench_numa_5m.py \
  --records 1000000 --variants medium --workers 28 \
  --trials 2 --tmpdir /tmp/mybench --csv out.csv
```

Generate once, reuse the `--tmpdir`. Compare same-boot
(medians, warmup included by the harness). For quick
batch-shape checks: `python/benchmarks/ml/diag_batch.py`.
