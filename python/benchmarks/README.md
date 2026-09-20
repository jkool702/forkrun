# forkrun Python benchmarks (W-PY11)

Measurement infrastructure for "how fast is the Python frontend?"
Honest numbers per mode, per output path, per workload — plus RSS
boundedness, fault overhead, baselines, and Stage 0 niches.

## Run

```bash
make -f Makefile.substrate python-substrate   # required: builds the .so
python3 python/benchmarks/run_all.py                      # medium (1M), 5 trials
python3 python/benchmarks/run_all.py --scale small --trials 2   # smoke (~1 min)
python3 python/benchmarks/run_all.py --scale large --trials 5   # 10M, manual
python3 python/benchmarks/run_all.py --filter throughput        # subset
python3 python/benchmarks/run_all.py --list                     # inventory
python3 python/benchmarks/run_all.py --csv /tmp/pybench.csv     # + CSV
make -f Makefile.substrate bench                               # medium, 3 trials
```

## What each file measures

- `bench_harness.py` — timing (median+N warm-up), RSS, deterministic
  inputs, hardware disclosure, table/CSV. Unit-tested in
  `python/tests/test_bench.py`.
- `bench_throughput.py` — lines/sec per mode × workload × output path:
  python no-op (claim/ack floor) / transform / compute; spawn cat/tr;
  plugin ctypes; stream-vs-map, ordered-vs-unordered, batch-size sweep.
- `bench_memory.py` — subprocess-isolated ru_maxrss peaks: flat across
  4x stream (no output), output-sized under map, slow-consumer streaming
  bound, 5x amplification.
- `bench_fault.py` — healthy vs 10% deterministic failures (retry+poison
  overhead) vs 100% (all poison, must complete).
- `bench_baselines.py` — serial Python and `multiprocessing.Pool`
  context rows (mp intentionally at small scale: per-line pickling would
  blow the time budget and prove nothing new).
- `bench_niches.py` — Stage 0 workloads: JSONL ingestion, filter+
  transform, aggregation. (`batch.data` is a memoryview — payloads copy
  to bytes first; the copy is part of the measured path.)

## Reading the table

- `Lines/s` uses the input line count over wall time (fork+scan+claims
  included — honest end-to-end, not steady-state cherry-picking).
- `Peak RSS` is in-process `ru_maxrss` except in `bench_memory.py`,
  where subprocess peaks isolate each leg.
- Every row carries the hardware string; numbers transfer across
  machines only qualitatively.

## First numbers (i9-7940X 28c, 1M lines, median of 5)

| Benchmark | Lines/s | Note |
|---|---|---|
| Python no-op (run/map/stream) | ~102M | claim/ack/emitter floor |
| Python upper / sum | 52M / 45M | realistic per-batch work |
| Plugin upper (ctypes) | 43M | near-Python speed |
| Spawn cat / tr | ~14.6M | batches amortize subprocess |
| stream vs map | 0.70x | stream is *faster* (no collect) |
| ordered vs unordered | 1.01x | reassembly ~free |
| Serial upper / mp.Pool | 10.4M / 2.2M | context rows |
| forkrun vs baselines | 4.6x / 12.6x | vs serial / Pool |
| JSONL / filter / aggregation | 3.4M / 24.6M / 37.5M | Stage 0 niches |
| RSS flat (1→8MB, no output) | +0MB | bounded |
| RSS slow-consumer stream (50MB out) | 61MB peak | window, not output |

Fault-rate note: 10%-failure runs report *higher* lines/s than healthy
(the metric counts input lines while poisoned batches skip payload
work). The number is honest; read it as "no collapse under faults,"
not "faults are faster."

## Known limitations (v0)

- Input is materialized into a memfd (bounded inputs; TB-scale needs
  streaming ingest). No-op rates reflect claim/ack + fork overhead.
- Spawn mode is `subprocess`-bound (~1-5ms/batch) by design.
- `multiprocessing.Pool` baseline intentionally small-scale.
- No NUMA legs, no aarch64 legs, no GNU-parallel comparison (that's the
  bash matrix's job). Median-of-N, not confidence intervals.
