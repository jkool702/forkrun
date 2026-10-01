# forkrun vs Alternatives

Same-boot measured (28 workers, 5M records — full tables in
`python/benchmarks/results/numa_5m_study.md`). No strawmen:
each system runs its idiomatic best.

## Headline (medium, 2.2GB)

| System | records/s | Notes |
|---|---|---|
| forkrun C plugin | 2,023k–2,300k | yyjson single-pass, frozen ABI |
| forkrun Python UDF | 652k–703k | arbitrary Python, same code as Pool's |
| ProcessPoolExecutor | 755k | pickled chunks, `workers*4` fan-out |
| mp.Pool | 757k | same shape as Executor |
| Ray Data | 184k | pandas batches, task overhead dominates |
| HF Datasets | 90k | `from_text` + batched map |
| Polars (native exprs) | 2,200k | different language — medium-only shapes |

## When to use what

- **forkrun C plugin:** per-record CPU dominates and you can
  write C. Nothing in Python touches it (2–7×).
- **forkrun Python UDF vs Pool/Executor:** parity
  performance, different tradeoffs — forkrun adds
  zero-copy batching (no pickling), crash recovery with
  respawn (Pool hangs on worker death), streaming with
  bounded memory, and NUMA topology. Pool/Executor add
  generality (arbitrary task graphs, not just maps).
- **Ray / HF Datasets:** cluster scale-out and ecosystem
  (datasets, pandas interop) at 3–8× the per-node cost.
  Right choice past one box, wrong choice inside it.
- **Polars/DuckDB native:** unbeatable where your transform
  is natively expressible; the heavy UDF (arbitrary Python
  per record) is exactly what they can't express — which
  is the point of the comparison.

## Honest limitations of forkrun

- Single box (no cluster story — that's Ray's home game).
- Map/stream/sweep shapes only (no task graphs).
- Linux only.
- Crash recovery covers workers; orchestrator death is
  checkpoint-and-resume, not transparent.
- Realtime (unbuffered stdout) delivery is at-least-once.
