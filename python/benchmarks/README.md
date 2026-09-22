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
- `ml_data_gen.py` / `ml_payload.py` / `ml_native.py` /
  `bench_ml_pipeline.py` — W-PY24 real-world ML pipeline benchmark:
  synthetic recommendation-event JSONL (light/medium/heavy) with the
  IDENTICAL Python transformation across forkrun, Ray Data, HF
  Datasets, Pool, Executor, and serial, plus native Polars/DuckDB
  expressions and crash-once fault injection. Needs
  `pip install ray polars duckdb datasets` (each skips cleanly if
  absent). Run:
  `python3 python/benchmarks/bench_ml_pipeline.py --records 50000
  --trials 3` (~30 min full matrix). Full write-up with verdicts:
  `results/ml_pipeline_study.md`.
- `plugins/ml_plugin_{light,medium,heavy}.c` — W-PY24 C plugins for
  the same ML workloads through the frozen ABI (dialect-2 +
  FLAG_RAW borrowed window, stdout capture): `gcc -O3 -shared
  -fPIC -march=native -I ring_loadables -o ml_plugin_X.so
  ml_plugin_X.c -lm`, then
  `forkrun.map("ml_plugin_X.so:ml_process_X", path, mode="plugin")`.
  Validated by JSON-value equality vs the Python path (light is
  byte-identical). `ml_plugin_fault.c` is the crash-once fault
  injector (FR_FAULT_MARKER/FR_FAULT_IDX env).
- `tokenize_data_gen.py` / `tokenize_payload.py` /
  `plugins/tokenize_plugin.c` / `bench_tokenize.py` — W-PY25 LLM
  tokenization benchmark: synthetic corpus (50–500 words/doc) +
  30k shared vocabulary, identical tokenizer rules in Python and
  C (suffix table/order, UNK, quality filters), 8-system matrix
  (serial/Pool/Executor/HF/Ray/forkrun-Python/forkrun-C/Polars
  map_batches). Run:
  `python3 python/benchmarks/bench_tokenize.py --docs 20000
  --trials 3` (~15 min). Write-up with verdicts:
  `results/tokenize_study.md` (+ `--min-words/--max-words` for
  the big-doc crossover).

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
