# forkrun Performance (what to expect)

Same-boot measured, 28 workers, 5M records, `order="index"`
(full tables: `python/benchmarks/results/numa_5m_study.md`).
Your box will differ; relative order is the robust reading.

## Throughput (records/s)

| Workload (size) | C plugin | Python UDF | Executor | Pool |
|---|---|---|---|---|
| Light (508MB) | 5.8M | 1.6M | 1.7M | 1.5M |
| Medium (2.2GB) | 2.3M | 703k | 755k | 757k |
| Heavy (6.4GB) | 710k | 90k | 93k | 92k |
| Tokenize (500k docs) | 342k docs/s | 148k | 158k | 157k |

forkrun C wins 2.8–7.6×; forkrun Python runs at
`ProcessPoolExecutor` parity. Cost model (profiled):
~73% of cycles sit in payload work (e.g. `snprintf`
formatting), <1% in the framework — make the payload
faster before touching anything else.

## Scaling shape

- Medium C: 361k (1w) → 965k (4w) → 1.6M (14w) → 1.7M
  (28w). Python plateaus 14→28w (oversubscription, not a
  framework cliff). No scaling cliffs anywhere.
- `lines=1k–10k` is the sweet spot (adaptive already
  chooses inside it). `lines=100` loses ~40% (per-batch
  costs dominate); `lines=50k+` loses ~35% (starvation:
  too few batches per worker).
- UMA vs NUMA (fake-4, worst case for NUMA): light
  5.8M→5.6M, medium 2.3M→2.1M, heavy 710k→710k. On
  single-socket, UMA is simpler and slightly faster; on
  real multi-socket, NUMA adds born-local memory wins.
- 20M inputs hold the ratios (1.20×/1.29×/1.34× NUMA/UMA
  on C) — steady-state, no degradation with size.

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
python3 python/benchmarks/bench_numa_5m.py \
  --records 1000000 --variants medium --workers 28 \
  --trials 2 --tmpdir /tmp/mybench --csv out.csv
```

Generate once, reuse the `--tmpdir`. Compare same-boot
(medians, warmup included by the harness). For quick
batch-shape checks: `python/benchmarks/diag_batch.py`.
