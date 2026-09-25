5M RECORDS, STEADY STATE (best of 8/14/28 workers, W-PY29):

┌────────────────────────────────────────────────────────────────────┐
│  ML PIPELINE (sustained throughput, records/sec)                   │
├──────────────────────┬──────────┬──────────┬───────────────────────┤
│ System               │ Light    │ Medium   │ Heavy                 │
│                      │ (508MB)  │ (2.2GB)  │ (6.4GB)               │
├──────────────────────┼──────────┼──────────┼───────────────────────┤
│ forkrun C plugin     │ 6,490k   │ 1,622k   │ 611k                  │
│ Executor             │ 1,641k   │   797k   │  94k                  │
│ Pool                 │ 1,598k   │   757k   │  94k                  │
│ forkrun Python       │ 1,611k   │   652k   │  89k                  │
│ Ray                  │   250k   │   184k   │  56k                  │
│ HF Datasets          │   120k   │    90k   │  44k                  │
├──────────────────────┼──────────┼──────────┼───────────────────────┤
│ forkrun C advantage  │  4.0×    │  2.0×    │  6.5×                 │
└──────────────────────┴──────────┴──────────┴───────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│  TOKENIZE (500k docs, sustained)                                   │
├──────────────────────┬──────────────────────┬──────────────────────┤
│ System               │ Docs/sec             │ Tokens/sec           │
├──────────────────────┼──────────────────────┼──────────────────────┤
│ forkrun C plugin     │ 346,055              │ 97.7M                │
│ Executor             │ 167,156              │ 47.2M                │
│ Pool                 │ 160,907              │ 45.4M                │
│ forkrun Python       │ 146,025              │ 41.2M                │
│ HF Datasets          │  51,025              │ 14.4M                │
│ Ray                  │  32,096              │  9.1M                │
│ Polars UDF           │  15,382              │  4.3M                │
├──────────────────────┼──────────────────────┼──────────────────────┤
│ forkrun C advantage  │ 2.1×                 │ 2.1×                 │
└──────────────────────┴──────────────────────┴──────────────────────┘

FORKRUN C PLUGIN WINS ALL FOUR UDF WORKLOADS OUTRIGHT.
NO SCALING DEFECTS. NO CLIFFS. NO DIPS.

┌────────────────────────────────────────────────────────────────────┐
│  FAULT INJECTION (W-PY29): medium 5M, lines=100, order=index,      │
│  Python payload, median of 2 (+warmup). Core dumps disabled        │
│  (RLIMIT_CORE=0 — systemd-coredump spends ~10s per SEGV writing    │
│  multi-GB memfd mappings; environmental, not forkrun).             │
├──────────────┬──────────┬──────────┬──────────┬────────┬───────────┤
│ Mode         │ 8w rec/s │ 14w rec/s│ 28w rec/s│ Deaths │ Output    │
│              │          │          │          │(8/14/28│           │
├──────────────┼──────────┼──────────┼──────────┼────────┼───────────┤
│ clean        │  414k    │  604k    │  606k    │  0     │ exact     │
│ burst SIGKILL│  404k    │  558k    │  482k    │ 8/14/28│ exact     │
│ sustained    │  411k    │  582k    │  556k    │ 4/8/15 │ exact     │
│ segv-once    │  403k    │  594k    │  571k    │ 1 each │ exact     │
│ poison       │  408k    │  603k    │  585k    │  0     │ exact-1   │
└──────────────┴──────────┴──────────┴──────────┴────────┴───────────┘

W-PY29 fault reading:
- Every fault mode is byte-exact vs clean (all 50k batches). The old
  "dead batch LOST, output truncated at hole" semantics are gone:
  parent-side WorkerTxn recovery (revert + escrow kills+1 + respawn)
  re-executes the orphan exactly once.
- Poison (batch 25000 fails every attempt): killed 3 times, then
  poison-skipped — zero worker deaths, pipeline completes with
  exactly that batch absent (`exact-1`), at ~clean throughput (3
  wasted payload executions are invisible at 50k batches).
- Recovery tax is single-digit % for realistic death counts: burst
  of W simultaneous SIGKILLs costs 2-8% at 8/14w; a lone SIGSEGV
  costs ~0-3% (noise floor ~±5% at 2 trials). 28-worker burst of 28
  simultaneous deaths (respawn storm) costs ~20% — still exact.
- Sustained ~1 death per 350k records costs ~40ms/death (fork +
  re-claim + rework + re-ack), ~8% at 28w.
- Respawn cap (3/slot) bounds genuine crash loops into a loud abort;
  all schedules above stay far below it by construction.

┌────────────────────────────────────────────────────────────────────┐
│  FAULT x4 SCALE (W-PY29 follow-up): same kill counts, 20M records  │
│  (200k batches), 28 workers. Question: is recovery cost a fixed   │
│  per-death price (relative drop shrinks 4x) or scale-proportional? │
├──────────────┬──────────┬──────────┬────────┬────────┬─────────────┤
│ Mode         │ 5M rec/s │ 20M rec/s│ 5M +s  │ 20M +s │ Deaths      │
├──────────────┼──────────┼──────────┼────────┼────────┼─────────────┤
│ clean        │  606k    │  653k    │   —    │   —    │  0          │
│ burst SIGKILL│  482k    │  574k    │ +2.2s  │ +4.2s  │ 28 (head)   │
│ burst-tail   │   —      │  570k    │   —    │ +4.5s  │ 28 (tail)   │
│ sustained    │  556k    │  592k    │ +0.6s  │ +2.0s  │ 15          │
│ segv-head/tail│ 571k    │  633k    │ +0.6s  │ +1.0s  │ 1           │
└──────────────┴──────────┴──────────┴────────┴────────┴─────────────┘
(death counts identical across scales by construction; all exact.)

Answer: NEITHER pure model holds — the 1/4-relative-drop hypothesis
is falsified for burst (relative drop shrank only ~40%, 20.6%→12.1%),
but so is a purely proportional model (absolute drops shrank ~35%:
124k→79k). The data fits a two-component cost per death: a FIXED
term (~50-80ms: death-pipe detection, revert, escrow, fork, rework)
plus a DATA-SCALE term (~10-14ms/GB). Head-vs-tail bursts are
identical, so it is NOT orderer hole-backlog — the leading suspect
for the scale term is process teardown/fork page-table work on the
parent's full input+output mappings (~2x input bytes mapped), which
grows linearly with data size and is paid per respawn. Follow-up:
verify via fork-latency microbenchmark; reduce by shrinking parent
mappings (e.g., fallow-punch output memfds harder) if it matters.

W-PY29 note: forkrun rows re-measured post-hardening (median of 3,
order=index, workers 8/14/28 on the same 28c box class; per-worker
table below). Non-forkrun rows unchanged (W-PY29 touches only the
forkrun engine/worker paths). The C-plugin gains (light +20%,
tokenize +35%) are consistent with the per-batch lseek removal on
the claim path; Python rows are within run variance (light -3%,
medium -3%, heavy identical, tokenize +9%).

Per-worker W-PY29 numbers (records/sec, 5M records):

| Mode            │ Light 8w │ Light 14w │ Light 28w │
│ forkrun Python  │   974k   │  1,591k   │  1,611k   │
│ forkrun C       │ 3,891k   │  6,299k   │  6,490k   │

| Mode            │ Med 8w │ Med 14w │ Med 28w │ Heavy 8w │ Heavy 14w │ Heavy 28w │
│ forkrun Python  │  418k  │   630k  │   652k  │   51k    │    83k    │    89k    │
│ forkrun C       │  983k  │ 1,322k  │ 1,622k  │  359k    │   516k    │   611k    |

Per-worker tokenize (500k docs, 282.2 avg tok/doc):

| Mode            │ 8w docs/s │ 14w docs/s │ 28w docs/s │ 28w tok/s │
│ forkrun Python  │   85,742  │   135,524  │   146,025  │   41.2M   │
│ forkrun C       │  212,805  │   304,696  │   346,055  │   97.7M   │

┌────────────────────────────────────────────────────────────────────┐
│  MEDIUM + yyjson (W-PY31): 5M records, order=index                  │
├──────────────┬──────────┬──────────┬──────────┬─────────────────────┤
│ Plugin       │ 8w       │ 14w      │ 28w      │ Batch-size sweep 28w│
├──────────────┼──────────┼──────────┼──────────┼─────────────────────┤
│ scalar C     │ 1,117k   │ 1,533k   │ 1,664k   │ l100: 1002k         │
│ yyjson C     │ 1,473k   │ 1,891k   │ 1,875k   │ l100: 1067k         │
│ delta        │ +32%     │ +23%     │ +13%     │ l1000: 1643k/1990k  │
│              │          │          │          │ l5000: 1644k/1960k  │
└──────────────┴──────────┴──────────┴──────────┴─────────────────────┘

Reading: yyjson wins everywhere parsing matters (+20% at lines≥1000),
but both plateau at ~2M/s — at lines=100 (50k batches) the two are
within 7%, i.e. the ceiling is framework per-batch cost, not JSON
parsing. The 3,500k target (and Polars' 2,936k) is falsified as
stated for a parser-only swap; closing it needs framework
batch-throughput work (future, engine stays frozen). Output is
byte-identical (7-test lock-in); keep yyjson as the medium default.

┌────────────────────────────────────────────────────────────────────┐
│  MEDIUM + single-pass (W-PY32): 5M records, order=index            │
├──────────────┬──────────┬──────────┬──────────┬─────────────────────┤
│ Plugin       │ 8w       │ 14w      │ 28w      │ vs obj-get          │
├──────────────┼──────────┼──────────┼──────────┼─────────────────────┤
│ scalar C     │ 1,117k   │ 1,533k   │ 1,664k   │ —                   │
│ yyjson obj   │ 1,473k   │ 1,891k   │ 1,875k   │ —                   │
│ yyjson spass │ 1,602k   │ 2,023k   │ 2,077k   │ +9% / +7% / +11%    │
└──────────────┴──────────┴──────────┴──────────┴─────────────────────┘

Reading: single-pass + exact fast formatter buy a real +7-11% (and
+25-43% over scalar), but the ~2M/s plateau does not move — the work
order's bottleneck table (extraction 55% of a 7.4µs record) is
incompatible with the measured batch-size response, where per-record
cost balloons from ~14µs (lines=1000) to ~28µs (lines=100) for BOTH
implementations. Parser work is now diminishing returns; the
remaining ceiling is framework per-batch cost. The 2.6x/4.9M
projection is falsified. Keep single-pass as the medium default
(free, byte-exact, 3-test lock-in).

┌────────────────────────────────────────────────────────────────────┐
│  SPAWN C-loop vs Python loop (W-PY33): 1M medium, `tr a-z A-Z`      │
├──────────────┬──────────┬──────────┬──────────┬─────────────────────┤
│ Loop         │ 8w       │ 14w      │ 28w      │ lines=100           │
├──────────────┼──────────┼──────────┼──────────┼─────────────────────┤
│ Python loop  │ 1,629k   │ 1,792k   │ 1,358k   │ 656k / 783k         │
│ C loop       │ 1,679k   │ 1,800k   │ 1,324k   │ 682k / 790k         │
└──────────────┴──────────┴──────────┴──────────┴─────────────────────┘

Reading: parity (±4%) at every worker count and batch size. The
Python loop's v1 fast path (fr_py_exec_spawn + fr_py_complete, 2
ctypes calls) had already removed per-batch Python cost; both paths
pay identical `tr` execution (~300µs+/batch), so the projected
350µs-per-batch saving never existed. The C loop's value is
architectural (one engine-owned claim→spawn→signal→ack path under
WorkerTxn recovery), not throughput. 256KB batches complete
identically — no deadlock, as the capture-memfd design guarantees.

┌────────────────────────────────────────────────────────────────────┐
│  NUMA fake-4 STEADY STATE (W-PY35): 5M records, 28 workers,        │
│  order=index, same-boot UMA baseline, numa=fake=4 boot             │
├──────────────┬──────────┬──────────┬──────────┬────────────────────┤
│ forkrun C    │ UMA 1    │ @2       │ @4(auto) │ NUMA/UMA           │
├──────────────┼──────────┼──────────┼──────────┼────────────────────┤
│ light 508MB  │ 5.8M     │ 5.4M     │ 5.6M     │ 0.93-0.97          │
│ medium 2.2GB │ 1.7M     │ 1.9M     │ 2.1M     │ 1.12-1.24          │
│ heavy 6.4GB  │ 552k     │ 709k     │ 710k     │ 1.28-1.29          │
├──────────────┼──────────┼──────────┼──────────┼────────────────────┤
│ Python light │ 1.6M     │ —        │ 1.6M     │ 1.00               │
│ Python med   │ 655k     │ —        │ 712k     │ 1.09               │
│ Python heavy │ 88k      │ —        │ 90k      │ 1.02               │
├──────────────┼──────────┼──────────┼──────────┼────────────────────┤
│ tok C 500k   │ 317k d/s │ —        │ 342k     │ 1.08 (2.2× Exec)   │
│ tok Py 500k  │ 140k d/s │ —        │ 148k     │ ~1.04              │
│ spawn py 1M  │ 1.6M     │ —        │ 1.2M     │ 0.75               │
│ spawn C 1M   │ 1.6M     │ —        │ gate     │ UMA-only by design │
└──────────────┴──────────┴──────────┴──────────┴────────────────────┘
Competitors same boot 28w: light Ex 1.7M / Pool 1.5M; medium Ex
755k / Pool 757k; heavy Ex 93k / Pool 92k; tokenize Ex 158k /
Pool 157k. forkrun C NUMA advantage: 3.3× / 2.8× / 7.6× /
2.2× (tok). Sweep 1M medium monotonic both topologies (C:
361k→1.7M UMA, auto matches from 4w; Python plateaus 14→28w
both). Stream+@2 slow-consumer: 1M/1M lines, +0MB RSS.

Reading: no NUMA software tax at steady state on fake hardware
(W-PY36 corrected the first hypothesis offered here: the win is
pipeline overlap — UMA serializes ~0.9s spill+scan while NUMA
overlaps ingest/index/scan with compute — not contention
relief; per-instruction efficiency is worse on NUMA
everywhere). Only spawn regresses
(0.75×, spawn-cost dominated). Output record-multisets proven
exactly equal UMA vs NUMA at 5M (light 5.0M/5.0M, medium
4997892/4997892 = Pool/Executor counts); naive line counts
read low on NUMA because blobs don't newline-terminate
(junction artifact, <0.1% — the runner's 99% threshold
separates it from genuine 25%+ topology shortfall). Full
tables: `python/benchmarks/results/numa_5m_study.md`. Runner:
`python/benchmarks/ml/bench_numa_5m.py`.

┌────────────────────────────────────────────────────────────────────┐
│  NUMA fake-4 at 20M (W-PY35 follow-up): same harness, 28 workers   │
├──────────────┬──────────┬──────────┬─────────┬─────────────────────┤
│ forkrun      │ UMA 1    │ @4(auto) │ ratio   │ vs 5M ratio         │
├──────────────┼──────────┼──────────┼─────────┼─────────────────────┤
│ light C      │ 4.6M     │ 5.5M     │ 1.20×   │ was 0.97×           │
│ medium C     │ 1.4M     │ 1.8M     │ 1.29×   │ was 1.24×           │
│ heavy C      │ 545k     │ 730k     │ 1.34×   │ was 1.29×           │
│ light Py     │ 1.5M     │ 1.6M     │ 1.07×   │ was 1.00×           │
│ medium Py    │ 595k     │ 701k     │ 1.18×   │ was 1.09×           │
│ heavy Py     │ 87k      │ 90k      │ 1.03×   │ was 1.02×           │
└──────────────┴──────────┴──────────┴─────────┴─────────────────────┘
Reading: scales as hoped — ratios hold or strengthen at 4× data.
Absolutes drift ~15-20% on both topologies over the long matrix
while NUMA holds (light 5.6M→5.5M vs UMA 5.8M→4.6M): the longer
the run, the more UMA's serialized spill+scan costs it (W-PY36:
the win is pipeline overlap, not contention relief — NUMA is
worse on every micro metric and wins via more aggregate
parallelism). CSV:
`python/benchmarks/results/numa_20m.csv`, inputs at `/tmp/numa20m`.
