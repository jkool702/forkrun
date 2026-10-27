# forkrun vs Alternatives

Same-boot measured (28 workers, 5M records — full tables in
`python/benchmarks/results/numa_5m_study.md`). No strawmen:
each system runs its idiomatic best.

## Headline (medium, 2.2GB)

> **Note on the competitor rows in this table.** They are older than
> the rest of this file and come from a different study
> (`numa_5m_study.md`), so their absolute numbers should not be mixed
> with the forkrun rows here -- that is the error this note exists to
> prevent. The current, like-for-like figures, measured with static file
> partitioning (the standard Python idiom), are in
> `python/benchmarks/results/RELEASE_v3.6.0.md` section 0: medium
> `ProcessPoolExecutor` 778k and `multiprocessing.Pool` 775k. Batching on
> the fly would make both faster and is available to them; it is
> deliberately not quoted, because on-the-fly batching is one of the
> things forkrun does automatically -- and on a stream the competitors
> are forced into it and still lose by 3.94-10.76x.
> this note exists to prevent. For a single-study, like-for-like table
> see `python/benchmarks/results/RELEASE_v3.6.0.md` §0.

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
