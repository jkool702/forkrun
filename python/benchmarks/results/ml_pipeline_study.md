# ML Pipeline Study: Best-of-the-Best Comparison (W-PY24)

Command: `python3 python/benchmarks/ml/bench_ml_pipeline.py --records 50000
--trials 3 --csv results/ml_pipeline.csv` (fault section included).
Hardware: 28c Intel i9-7940X. Engine v3.5.2, forkrun 0.16.0, Python 3.14.
Ray 2.58, Polars 1.44.2, DuckDB 1.5.5, HF datasets 5.0.1, pyarrow 25.0.1.
Date: 2026-09-21. Data: synthetic recommendation-system-style JSONL
(see `ml_data_gen.py` — seeded, deterministic; distributions are
synthetic assumptions, not production data).

## Verdict up front

No single winner — the workload decides, exactly as designed:

- **Natively-expressible work belongs to native engines — sometimes.**
  Polars does 2.4M records/s on the medium workload (4.4× the best
  Python-UDF system). But DuckDB does 189k — SLOWER than forkrun's
  293k UDF path. Native ≠ automatically faster; engine overhead
  (here: JSON shredding) can dominate.
- **forkrun's C plugin is a tier of its own.** Same logical
  workload, hand-rolled C field extraction through the frozen ABI
  (zero Python per batch): light 1124k (beats Executor outright),
  medium 493k (85% of Executor, beats Pool), heavy 215k (2.5× the
  best Python system — the C tokenizer demolishes the Python one).
  It does not catch Polars on expressible work (5× gap stands).
- **Arbitrary-Python UDFs belong to process pools — by a modest
  margin.** ProcessPoolExecutor wins light (1037k) and medium
  (577k); `multiprocessing.Pool` is second; forkrun Python runs at
  60–75% of the executor. The heavy variant compresses the field
  (84k vs 84k vs 68k) — payload-bound, as predicted.
- **Fault isolation: Ray recovers completely, forkrun survives
  truncated, Pool dies.** Crash-once SIGSEGV + transients, all
  faults proven fired: Ray survives with full output (transparent
  task retry); forkrun survives with output truncated at the lost
  batch (worker respawn works, but signal death skips escrow, and
  the C orderer stalls at the head hole — see below); Pool hangs
  and dies (TimeoutError — no retry exists).

## Throughput (50k records/variant, worker sweep best)

Sizes: light 5.1MB (~120B/rec), medium 22.4MB (~460B/rec),
heavy 64.0MB (~1.3KB/rec). All UDF systems run the IDENTICAL
transformation (`ml_payload.py`); native systems use their own
expression language (medium only).

| System               | Light    | Medium   | Heavy    | Medium native |
|----------------------|----------|----------|----------|---------------|
| Serial Python        | 147k     | 63k      | 6.4k     | —             |
| mp.Pool (best)       | 856k     | 457k     | 84k      | —             |
| ProcessPoolExecutor  | 1023k    | 551k     | 84k      | —             |
| HF Datasets num_proc | 81k      | 62k      | 33k      | —             |
| forkrun map (Python) | 580k     | 293k     | 68k      | —             |
| forkrun map (C plugin)| 1047k   | 481k     | 216k     | —             |
| Ray Data             | 43k      | 38k      | 17k      | —             |
| Polars native        | —        | —        | —        | 2200k         |
| DuckDB native        | —        | —        | —        | 189k          |

(units: records/s; best of worker sweep 1,2,4,8,14,28.)

Per-worker shape (medium): forkrun Python scales 62k(1w) →
293k(14w) → 199k(28w, oversubscribed); Pool/Executor scale
similarly and peak at 14–28w. The C plugin tracks ~1.6× higher
(157k → 481k at 8w) but fades faster past peak (367k at 14w,
189k at 28w — smaller per-batch work units contend sooner).
Plugin wins light outright and leads heavy 2.5×. All systems
agree on output counts (validated 49974/50000 medium, 49979/50000
heavy — quality filter + clean data; fault data validated
separately). Plugin outputs additionally validated by JSON-value
equality vs the Python path on clean AND 5%-malformed data (light
is byte-identical; medium/heavy match on all fields with floats
epsilon-compared, except heavy `fh` — Python SipHash is
per-process randomized, C chains FNV-1a by design).

## Fault injection (crash-once, 8 workers, 5% malformed)

| System   | Survived | Output          | Mechanism               |
|----------|----------|-----------------|-------------------------|
| forkrun (Python) | yes | 4887 records | respawn; output truncated at hole |
| forkrun (C plugin) | yes | 4887 records | same hole semantics (deterministic match) |
| Ray Data | yes      | count=49525     | task retry (transparent, complete) |
| Pool     | no       | TimeoutError    | worker death hangs map; no retry exists |

"Crash once": SIGSEGV at batch idx 5 + transients at idx 6–10,
every fault proven fired via marker files (an earlier revision
used random indices that sometimes never executed — a vacuous
pass; the runner now asserts firing). Transients recover
completely via escrow retry in both forkrun modes. The SIGSEGV
batch itself is LOST (signal death skips escrow deposit, and
there is no parent-side replay): the C orderer stalls at the
head hole, so the pipeline SURVIVES (exit 0, no hang) with
output truncated to the clean prefix before the hole (verified:
4887 records byte-equal to the ground-truth prefix). Ray
re-executes the dead task and delivers complete output. Pool
cannot recover by construction. The missing piece for forkrun —
parent-side replay of death-hole batches — is flagged as
follow-up work, not implemented here.

## Follow-up measurements (same box, isolated)

- forkrun medium 14w in isolation: ~500k (vs 293k in-matrix).
  The matrix runs systems back-to-back per round (pool, executor,
  HF, forkrun — forkrun last), so in-matrix numbers carry
  accumulated thermal/cache state; relative order is the robust
  reading, absolute rates are ~20–50% below cool-box peaks.
- forkrun `order=none` vs `order=index`: no measurable difference
  (light 1148k vs 1218k, medium 506k vs 518k, heavy 79k vs 81k —
  noise). The C orderer is not the UDF gap; the gap is the
  per-batch Python loop + Batch construction + memfd framing
  against Pool's tight chunk loop (hypothesis, not yet profiled).
- Start-method note: this box defaults to `forkserver`
  (Python 3.14); all benchmark drivers are `__main__`-guarded.
  An early A/B script without the guard died spuriously — not a
  product finding.

## Caveats (read before citing)

- Fixed run order per sweep round may understate later systems
  (see follow-up above); ranking is robust, absolutes are not.
- RSS is parent-process peak only (worker/subprocess memory not
  attributed per system).
- 50k records is a medium-scale probe, not TB-scale; Ray/HF
  trade-offs differ at scale (unmeasured).
- Ray uses default batching/pandas conversion; HF uses
  `batch_size=1000`, in-memory map. Documented knobs, not tuned
  per system beyond worker count.
- Native comparison covers the medium variant only — the heavy
  UDF (tokenize/stem/hash) is deliberately inexpressible
  natively, which is the comparison's point.
