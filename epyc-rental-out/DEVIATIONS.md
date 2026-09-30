# Deviations from the published reference

**Every published forkrun number in this repo was measured on ONE box:**
28c Intel i9-7940X, single socket, **1 NUMA node**, distance 10, 28 workers,
Fedora, glibc 2.43, Python 3.14.7, gcc 16.2, kernel 7.1.x, THP
`enabled=always` + `shmem_enabled=always`.

This rental differs on ten axes at once. **No percentage in these results is a
regression measurement**; each is a new hardware data point.

| # | axis | reference | this box | effect |
|---|---|---|---|---|
| 1 | sockets | 1 | 2 | the whole point of the run |
| 2 | NUMA nodes | 1 | 2 | `nodes=auto` resolves to 2 here, 1 there. Shape: NPS1. Meta-ring bound 2048/2 = 1024 chunks/node vs 512 under fake-4 — **a clean result here does not rule out F-NUMA1 at higher node counts** |
| 3 | SLIT distance | uniform 10 | 32/32 (intra/cross) | reference charged every pair threshold 2; here it is 4 intra-socket and 4 cross-socket, so "fake-4 is a worst case" does not transfer cleanly |
| 4 | physical cores | 14 | 48 | memory bandwidth and L3 scale together |
| 5 | logical CPUs | 28 | 96 | worker sweeps are on a different curve |
| 6 | worker count | 28 | 96 | per-worker share of the machine differs |
| 7 | userland | Fedora (glibc 2.43 / py 3.14.7 / gcc 16.2) | 26.04 (glibc 2.43 / py 3.14.4 / gcc 15) | libc memcpy, allocator, compiler codegen |
| 8 | compiler | gcc 16.2 | gcc 15 | plugin codegen (`-march=native` on Zen3 vs Skylake-X) |
| 9 | 20M competitor coverage | n/a | Ray + HF omitted at 20M | intentional; repo convention is competitors-at-5M |
| 10 | topology shape | n/a (single node) | NPS1 | real multi-socket: YES |

## Reading the node variants

`nodes=1,@2,@4,auto` resolves through `_numa.py:119-136`, which maps `@N` to
`[online[i % len(online)] for i in range(N)]`. What the rungs MEAN depends on
this box's node count, so read it from the table above rather than assuming:

**On NPS2/NPS4 (>= 4 nodes)** — a genuine locality ladder, because Linux numbers
nodes socket-first:

| spec | selects | locality level |
|---|---|---|
| `1` | one logical node | UMA — no NUMA pipeline at all |
| `@2` | physicals 0,1 | **both inside socket 0** |
| `@4` | physicals 0,1,2,3 | **all four CCDs of socket 0, still one socket** |
| `auto` | every physical | spans both sockets |

Read `@2`/`@4` there as *intra-socket*, never as a socket count.

**On NPS1 (2 nodes)** — the ladder collapses, because there is only one node per
socket to divide up:

| spec | selects | locality level |
|---|---|---|
| `1` | one logical node | UMA |
| `@2` | physicals 0,1 | == `auto` (both sockets); redundant, kept for parity |
| `@4` | 2 logical nodes per socket | tests per-node ring overhead at 2x the node count |
| `auto` | physicals 0,1 | **one node per socket — the primary experiment** |

So the primary contrast on an NPS1 box is UMA vs `auto`: born-local placement
across a real socket link at distance 32. That is the cleanest
possible form of the question.

## Deliberate methodology decisions

1. **Ray + HuggingFace Datasets omitted from the 20M stage.** Matches
   RELEASE_v3.6.0.md §0/§2, where competitors are measured at 5M and 20M is
   forkrun-only. Blocking is done with `epyc/blockmods/sitecustomize.py` so the
   absence is recorded, not silent.

2. **Benchmark worker cap raised from 8 to 96.** Ten modules in
   `python/benchmarks/{core,ml}/` hardcode `min(8, cpu_count)`. On a
   96-thread box that measures 8-way parallelism. 10_setup.sh rewrites
   it to honour $FORKRUN_BENCH_WORKERS_MAX. (On the reference box the 8 *was*
   the effective cap, so the reference numbers are not invalidated — but they
   are not reproduced either.)

3. **(\*) Worker sweeps are >= the node count.** `bench_numa_5m.py` with
   `workers < nodes` returns INCOMPLETE and is pathologically slow (measured
   ~2,500 s for one 1M cell under fake-4), because an unworked node's
   born-local ring is never claimed (INVARIANTS.md §17).

4. **The bash matrix is single-shot.** `run_benchmark.bash` runs each
   configuration exactly once: no warmup, no repetition, no outlier rejection.
   The Python suite is median-of-5 with a warmup. Treat bash numbers as
   indicative and Python numbers as the defensible ones.

5. **Separate `--tmpdir` per ML scale.** `bench_ml_pipeline.py` reuses
   `<tmpdir>/ml_<variant>.jsonl` on existence alone and the filename carries
   no record count, so a 5M directory reused for a 20M run silently measures 5M
   and reports 4x-inflated rates. Every stage asserts the line count first.

6. **The comprehensive suite runs last and un-timeboxed.** It is the longest
   suite in the repo and the least performance-critical, so a slow box costs the
   least valuable hours by putting it here.

## What was NOT done

- The bash matrix was run **unmodified** at whatever size `EPYC_BASH_BENCH_REDUCED`
  selected. Its 216-config product and 1s inter-config cooldown are as-is repo
  behaviour.
- No sanitizer (ASan/UBSan/TSan) matrix. MAINTAINERS.md §5 requires one on
  frozen code, and it cannot be mixed with timing data in the same session.
- No NPS-mode BIOS change was attempted. Whatever the box booted with is what
  was measured.
- `bench_scaling.py` (the 1,2,4,8,14,28 scaling study) was not run: its sweep
  is hardcoded to the reference box's topology and is not in `run_all.py`'s
  registry.

See `epyc-rental-out/DEVIATIONS_worker_cap.txt` for the exact patch.
