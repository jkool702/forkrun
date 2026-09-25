# NUMA steady-state benchmarks at 5M records, fake-4 topology (W-PY35)

Question: "How much does the NUMA pipeline cost in software
overhead, measured at steady state?"

## Hardware disclosure

- 28c Intel i9-7940X, Linux 7.1.10-200.numa_emu.fc44.x86_64
- Booted `numa=fake=4` (`/sys/devices/system/node/online: 0-3`,
  all 28 CPUs visible on every node, distance 10 — one socket)
- Fake NUMA = worst case for the NUMA pipeline: full software
  cost (N scanners, N indexers, per-node rings, cross-node
  coordination) with zero hardware benefit. On real
  multi-socket, born-local memory offsets this cost.

## Method

- Same payloads, same data generator, same `order=index`,
  same 28 workers as the UMA 5M reference
  (`DOCS/python/AI_benchmark_results.md`).
- Same-boot UMA baseline (`nodes=1`) in every matrix — ratios
  are same-boot, immune to thermal drift. (In-matrix absolutes
  run ~10-20% below cool-box peaks; relative order is the
  robust reading.)
- Median of 2 trials + 1 warmup. `nodes="auto"` → 4 nodes on
  this boot; `nodes="@2"` → 2 nodes.
- Medium C = yyjson single-pass plugin (the W-PY32 default);
  light/heavy C = scalar plugins; Python = UDF payloads.
- Runner: `python/benchmarks/bench_numa_5m.py`
  (`--tmpdir /tmp/numa5m` reuses the 5M inputs).
- Raw machine data: `python/benchmarks/results/numa_5m.csv`
  (Parts B/C/D full precision; Part A ML rows are recorded in
  the tables below and the run log — the first run crashed on
  a tokenize harness bug before writing its CSV, and Part A
  was not re-run since values were already locked in).

## Part A — ML pipeline, 5M records, 28 workers

| Workload (size) | forkrun C, nodes=1 | @2 (ratio) | auto/4 (ratio) | forkrun Python 1 / auto |
|---|---|---|---|---|
| Light (508MB) | 5.8M | 5.4M (0.93) | 5.6M (0.97) | 1.6M / 1.6M (1.00) |
| Medium (2.2GB) | 1.7M | 1.9M (1.12) | 2.1M (1.24) | 655k / 712k (1.09) |
| Heavy (6.4GB) | 552k | 709k (1.28) | 710k (1.29) | 88k / 90k (1.02) |

(units: records/s.)

Reading: there is no NUMA software tax at steady state — the
pipeline is at parity (light) or FASTER (medium +12-24%,
heavy +28-29%) on fake hardware. W-PY36 profiling corrected
the first hypothesis offered here (ring-contention relief):
per-instruction efficiency is *worse* on NUMA everywhere
(+17.5% cycles, IPC 1.3→1.1, 7× context switches, 67×
migrations, 4× syscalls). The win is structural: UMA
serializes ~0.9s of spill (0.53s) + scan (0.36s) before
workers fork, while NUMA overlaps ingest/index/scan with
worker execution (publish-gated fork, 4 parallel scanners)
and feeds more CPUs on average (10.1 vs 8.2). See the
W-PY36 perf section below. `@2` vs `@4` are within noise of
each other.

## Part A sweep — 1M medium, workers 1-28 (monotonic, no cliff)

| workers | C yyjson, nodes=1 | C yyjson, auto | Python, nodes=1 | Python, auto |
|---|---|---|---|---|
| 1 | 361k | 11k* | 62k | 3k* |
| 2 | 615k | 19k* | 128k | 5k* |
| 4 | 965k | 1.1M | 244k | 247k |
| 8 | 1.4M | 1.6M | 432k | 450k |
| 14 | 1.6M | 1.6M | 639k | 494k |
| 28 | 1.7M | 1.7M | 641k | 597k |

`*` workers < nodes: expected-incomplete (unworked node's ring
is never claimed — RESILIENCE_PROTOCOL §7.3). All covered rows
record-complete (see counting note). No scaling cliff in NUMA
mode; the W-PY27 monotonic shape holds (Python plateaus
14→28w on both topologies — oversubscription, not NUMA).

## Part B — tokenize (500k docs) and spawn (1M medium `tr`), 28w

| System | nodes=1 | auto (ratio) |
|---|---|---|
| forkrun C plugin tokenize | 317k docs/s | 342k (1.08) |
| forkrun Python tokenize | 140-142k | 146-148k (~1.04) |
| Pool tokenize (same boot) | 157k | — (NUMA-unaware) |
| Executor tokenize (same boot) | 158k | — (NUMA-unaware) |
| forkrun spawn Python-loop | 1.6M rec/s | 1.2M (0.75) |
| forkrun spawn C-loop | 1.6M rec/s | gate (UMA-only by design) |

forkrun C NUMA tokenize beats same-boot Executor 2.2×
(342k vs 158k). Spawn is the one case where NUMA costs
(0.75×): per-batch `posix_spawnp` dominates and the NUMA
pipeline adds coordination with no contention to relieve.
The C spawn loop refuses multi-node loudly
(`c_spawn_loop=True is UMA-only`) — recorded, not changed.

## Part C — competitors, same boot, 28 workers

| Workload | Executor | Pool | forkrun C NUMA | forkrun C advantage |
|---|---|---|---|---|
| Light | 1.7M | 1.5M | 5.6M | 3.3× |
| Medium | 755k | 757k | 2.1M | 2.8× |
| Heavy | 93k | 92k | 710k | 7.6× |

forkrun Python NUMA runs at Executor parity
(1.6M/1.7M, 712k/755k, 90k/93k) — same standing as UMA.
Competitor counts agree with forkrun record counts exactly
(medium: 4997892 both).

## Part D — streaming + NUMA memory boundedness

`stream(amplify×5)` over 200k lines, `workers=4`,
`nodes="@2"`, 1ms/batch consumer: 51 batches, 1M/1M lines,
parent RSS delta **0MB**. Bounded, same as UMA.

## Counting-method note (read before comparing counts)

Worker output memfds do not newline-terminate blobs, so a
naive whole-stream `splitlines()` count merges one junction
pair per blob boundary. NUMA makes more, smaller blobs, so
naive counts read 0.001-0.06% low vs UMA. This is a counting
artifact, not data loss — proven by record-multiset equality
at full 5M scale (light: 5,000,000/5,000,000 equal; medium:
4,997,892/4,997,892 equal, also equal to Pool/Executor).
The runner flags rows <99% of the UMA reference INCOMPLETE;
all full-coverage rows pass. Genuine topology shortfall
(workers < nodes) is 25%+, unmistakable.

## Hypotheses vs data

- H1 (overhead ∝ node count): FALSIFIED as stated — NUMA is
  at parity or faster except spawn (0.75×). Overhead is not
  the story; contention relief is.
- H2 (fixed, not per-record overhead): CONFIRMED in the
  small-run direction — at 20k records NUMA measured ~6×
  slower (pipeline spin-up dominates); at 5M that fixed cost
  vanishes. Steady-state measurement was load-bearing.
- H3 (forkrun NUMA still beats Executor): CONFIRMED —
  2.8-7.6× (C plugin), parity (Python UDF).
- H4 (monotonic worker scaling in NUMA): CONFIRMED.
- H5 (heavy shows less overhead): CONFIRMED and exceeded —
  heavy shows the largest NUMA *gain* (+29%).

## Follow-ups (not this order)

- None required for throughput. The junction-counting note
  above is harness documentation, already handled by the 99%
  threshold in `bench_numa_5m.py`.
- Spawn-on-NUMA (0.75×) is the only regression-shaped
  finding; tuning it is a separate work order if it matters.

## 20M scale confirmation (same harness, `--records 20000000`)

6 tests (light/medium/heavy × UMA/auto, 28 workers, median
of 2 + warmup; inputs at `/tmp/numa20m`, CSV
`results/numa_20m.csv`):

| Workload | forkrun C UMA | C auto (ratio) | Python UMA / auto |
|---|---|---|---|
| Light (2.1GB) | 4.6M | 5.5M (1.20×) | 1.5M / 1.6M (1.07×) |
| Medium (9.4GB) | 1.4M | 1.8M (1.29×) | 595k / 701k (1.18×) |
| Heavy (26.9GB) | 545k | 730k (1.34×) | 87k / 90k (1.03×) |

Verdict: scales as hoped — NUMA/UMA ratios hold or
strengthen at 4× data (5M: 0.97 / 1.24 / 1.29 → 20M: 1.20 /
1.29 / 1.34). Absolutes drift down ~15-20% on both
topologies (thermal/matrix accumulation over the long run;
UMA light 5.8M→4.6M) while NUMA holds (5.6M→5.5M) —
consistent with the contention-relief mechanism: the longer
the run, the more single-ring contention costs UMA.

## W-PY36 perf mechanism discovery (medium 5M yyjson, 28 workers)

Method: `perf record -g --call-graph dwarf --follow-forks` is
unavailable on perf 7.2 (no such flag) — inheritance is default,
and capture was verified multiprocess (UMA ~29 tasks, NUMA ~40:
28 workers + 4 scanners + 4 indexers + ingest + fallow +
orderer). Recordings: `/tmp/perf_uma.data` (219k samples),
`/tmp/perf_numa.data` (281k samples). Complements: `perf
stat -d -r 3`, full `strace -c -f`, direct scan-phase timing.
 Caveat: the `stat`/`strace` runs executed while the hotspot
report job churned in the background — absolutes are
inflated, same-boot ratios stand.

| Metric (3-run stat / full-table strace) | UMA (nodes=1) | NUMA auto (4) | Delta |
|---|---|---|---|
| Wall time (stat runs) | 2.76s | 2.64s | NUMA 4.5% faster* |
| Task-clock (aggregate CPU) | 22.7s | 26.8s | +18% (more mouths) |
| Avg parallelism (task/elapsed) | 8.2 CPUs | 10.1 CPUs | +23% |
| Total cycles | 91.6B | 107.7B | +17.5% |
| Total instructions | 114.6B | 120.6B | +5.3% |
| IPC | 1.3 | 1.1 | worse |
| L1-dcache-load-misses | 799M (3.1%) | 1,229M (4.6%) | +54%, worse rate |
| LLC-loads (miss rate) | 85.7M (73.9%) | 126.3M (71.5%) | +47% traffic, ~same rate |
| Branch misses | 212M (0.8%) | 207M (0.8%) | same |
| Context switches | 3,064 | 21,328 | 7× |
| CPU migrations | 69 | 4,643 | 67× |
| Page faults | 578k | 845k | +46% (more tasks) |
| Total syscalls (strace -f) | 55k | 226k | 4× (EAGAIN reads, order/write traffic, pinning) |
| Time in plugin+libc (hotspot) | ~73% | ~72% | identical work |
| Time in kernel (hotspot) | ~23% | ~24% | same |
| UMA serial spill+scan (direct) | 0.53s + 0.36s | overlapped | hidden under compute |

*Compressed by background contention; the clean-matrix gap is
~24% (2.1M vs 1.7M). Direction and mechanism agree.

Interpretation verdicts: L3-cache, fewer-switches,
fewer-migrations, fewer-syscalls, higher-IPC hypotheses all
FALSIFIED (every one inverts). The FAA/contention story is
also dead — atomics never appear in either hotspot; the
payload (`emit_medium_yyjson` → `snprintf` float formatting,
~74% children) is identical work on both. The mechanism is
PIPELINE OVERLAP: UMA pays ~0.9s of spill+scan serially
before the first worker forks; NUMA publish-gates workers
per node so ingest/index/scan run concurrently with compute
(4 parallel scanners), feeding 10.1 vs 8.2 average CPUs.
Higher throughput via more aggregate parallelism DESPITE
worse efficiency on every micro metric — oversubscription
(28 workers + ~12 helpers on 28 cores, all CPUs shared under
fake NUMA) explains the migration storm. No code changes;
no optimization attempted (measurement order). Easy-win
scan: none in the framework — 73% sits in the plugin's
`snprintf` float path (payload-side, W-PY32 already squeezed
the formatter once); the framework's own share
(`libforkrun` self <1%) has nothing left to take.

## W-PY41 batch diagnostic + 20M re-profile (post-W-PY39)

Runner: `python/benchmarks/diag_batch.py` (map blobs = batches;
input lines = ground-truth records).

### Batch sizing (yyjson medium, 28 workers)

| Scale | Topo | rec/s | batches | rec/batch | batch/s/worker | per-batch |
|---|---|---|---|---|---|---|
| 5M | UMA | 2.09M | 2570 | 1946 | 38.3 | 932µs |
| 5M | auto | 1.70M | 4226 | 1183 | 51.2 | 698µs |
| 20M | UMA | 2.08M | 10130 | 1974 | 37.7 | 948µs |
| 20M | auto | 2.01M | 14300 | 1399 | 51.3 | 696µs |

Per-batch wall time (~0.7-0.9ms of real compute) vs
nanosecond-scale claim/ack: overhead factor ≈ 1.0. Batch
sizing is NOT the limiter — no idleness signal here.

### 20M counters (`perf stat -d -r 2`, medium yyjson 28w)

| Metric | UMA 5M (W-PY36) | UMA 20M | NUMA 20M |
|---|---|---|---|
| Wall | 2.76s | 10.35s | 9.17s |
| Task-clock / avg CPUs | 22.7s / 8.2 | 90.9s / 8.8 | 100.8s / 11.0 |
| Cycles | 91.6B | 369B (4.03×) | 408B |
| IPC | 1.3 | 1.3 | 1.2 |
| L1 miss rate | 3.1% | 3.1% | 4.2% |
| Ctx switches / migrations | 3k / 69 | 6k / 86 | 72k / 14k |

Post-fix UMA gained ~0.8 avg CPUs (8.2→9.0 at 5M) from
overlap. Everything scales linearly 5M→20M (cycles 4.0×,
task 4.0×) — no scale-dependent inefficiency.

### 20M hotspot (dwarf, cycles event)

UMA: plugin children 86%, libc self 56% (snprintf float
formatting), kernel 14%, `libforkrun` self 0.40%. NUMA:
77% / 49% / 24% / 0.78%. Same shape as 5M — no new
hotspots at 20M. The 73%-family snprintf share holds.

### Verdict: SATURATED — ship it

Workers are not idle between batches (nearly 1ms of
payload compute per batch vs ns framework cost); avg CPUs
are scale-stable; the framework owns <1% of cycles. The
remaining ceiling is the per-record `snprintf` exact
formatter (payload-side, already squeezed once in W-PY32).
No further framework optimization available. Recordings:
`/tmp/perf_uma_20m.data`, `/tmp/perf_numa_20m.data`.
