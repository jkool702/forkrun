# Stage 0 campaign report — fake NUMA (numa=fake=4) — NOT real-NUMA evidence

- campaign: `stage0-final-38bda5ac`
- source: `38bda5ac2e5127ade192d017b9985c222d8965b1`
- source worktree: CLEAN
- trials requested: 3
- spec inventory: file-light20m-n1-w14, file-light20m-nauto-w14, file-light20m-nauto-w14-plugin, file-light20m-nauto-w4, pipe-light20m-nauto-w14, plugin-light60m-nauto-w14, smoke-light-100k-nauto

## Verdict (spec §8)

**INCONCLUSIVE for real-NUMA benefit — fake NUMA**

- The host reports fake NUMA (numa=fake=4) — NOT real-NUMA evidence. Spec §8 forbids converting fake-NUMA evidence into a Go decision.
- The rehearsal validates the harness and the ablation instrumentation; it does not establish real-NUMA placement or real-NUMA scaling.

## Baseline cases (median of trials)

| case | spec | trials ok | rec/s (median) | spread % | map s | process s | tree cores | ingest-thread cores (global) | ingest attribution | ingest phase s | diag samples |
|---|---|---|---|---|---|---|---|---|---|---|---|
| file-light20m-n1-w14 | w14 n1 udf | 3/3 | 16211464 | 1.7 | 1.23 | 3.59 | 1.93 | 0.99 | direct | 0.475 | 6 |
| file-light20m-nauto-w14 | w14 nauto udf | 3/3 | 24681972 | 3.7 | 0.81 | 3.63 | 2.56 | 0.90 | direct | 0.728 | 108 |
| file-light20m-nauto-w14-plugin | w14 nauto plugin | 3/3 | 27366616 | 1.0 | 0.73 | 0.80 | 7.12 | 0.99 | direct | 0.567 | 87 |
| file-light20m-nauto-w4 | w4 nauto udf | 3/3 | 22737502 | 5.5 | 0.88 | 3.64 | 2.14 | 0.71 | direct | 0.799 | 120 |
| pipe-light20m-nauto-w14 | w14 nauto udf | 3/3 | 20006994 | 1.4 | 1.00 | 3.74 | 2.56 | 0.99 | direct | 0.826 | 126 |
| plugin-light60m-nauto-w14 | w14 nauto plugin | 3/3 | 32630625 | 1.4 | 1.84 | 1.95 | 8.74 | 0.99 | direct | 1.690 | 256 |
| smoke-light-100k-nauto | w4 nauto udf | 3/3 | 3595349 | 39.8 | 0.03 | 0.11 | 0.67 | 0.99 | direct | 0.004 | 3 |

`map s` is the child's `forkrun.map()` timer; `process s` is the outer process wall, which also contains the harness's post-run exactness accounting. The ingest-thread CPU figure is GLOBAL to the ingest stage and is reported in cores. When a direct record exists, the denominator is that ingest phase's measured duration (the honest basis for "about one core while ingesting"); otherwise it falls back to the comm-sampled figure over the map timer. `direct` is the ingest task's own `CLOCK_THREAD_CPUTIME_ID` record (Python spill, or the C NUMA ingest FINAL); `comm-sampled` is the 20 ms per-task delta keyed by `comm`, which is a cross-check and can miss a short phase. `ingest phase s` is the measured duration of that direct ingest window. Tree cores are the sum of all task CPU deltas over the run divided by wall, not a peak snapshot.

## Per-node queue telemetry (STAGE0_DIAG, spec §4.3)

Raw timestamped samples (per node chunk head/tail, batch read/write, dequeue counter, waiter gauge) are retained in each trial's `stderr.log`; the tables aggregate them per trial and never join one trial's end to the next trial's start.

### Batch queue: scanner -> worker (`b`, `c`, `a`)

| case | samples | duration s | nodes | nonempty per node | all-empty | longest all-empty ms | published/s (raw write_idx) | claimed/s (raw read_idx) | c/s (cross-check) | supply gap/s (claims-pub) | gated ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| file-light20m-n1-w14 | 9 | 0.44 | 0 | n0:1.00 | 0.00 | 0 | 11618.1 | 7637.9 | 7637.9 | -3980.2 | - |
| file-light20m-nauto-w14 | 111 | 0.73 | 0,1,2,3 | n0:0.96; n1:0.95; n2:0.97; n3:0.97 | 0.00 | 0 | 8481.4 | 8382.8 | 8382.8 | -98.7 | 64 |
| file-light20m-nauto-w14-plugin | 90 | 0.57 | 0,1,2,3 | n0:0.38; n1:0.33; n2:0.61; n3:0.56 | 0.00 | 0 | 10944.2 | 10940.7 | 10940.7 | -3.5 | 0 |
| file-light20m-nauto-w4 | 123 | 0.80 | 0,1,2,3 | n0:1.00; n1:1.00; n2:1.00; n3:1.00 | 0.00 | 0 | 8216.6 | 8156.7 | 8156.7 | -59.9 | 229 |
| pipe-light20m-nauto-w14 | 129 | 0.83 | 0,1,2,3 | n0:0.03; n1:0.01; n2:0.03; n3:0.07 | 0.60 | 140 | 10534.3 | 10533.9 | 10533.5 | -0.4 | 1 |
| plugin-light60m-nauto-w14 | 259 | 1.69 | 0,1,2,3 | n0:0.44; n1:0.41; n2:0.52; n3:0.52 | 0.00 | 0 | 10366.8 | 10365.6 | 10365.6 | -1.2 | 0 |
| smoke-light-100k-nauto | 6 | 0.00 | 0,1,2,3 | n0:0.33; n1:0.33; n2:0.33; n3:0.00 | 0.67 | 4 | 19884.5 | 3367.5 | 3367.5 | -16517.0 | 0 |

### Chunk queue: ingest -> indexer (`q`, `i`)

| case | samples | nodes | chunk published/s | chunk consumed/s | all-empty | longest all-empty ms | indexer waiters max | empty-with-waiters | gated ms |
|---|---|---|---|---|---|---|---|---|---|
| file-light20m-n1-w14 | 0 | - | NOT MEASURABLE (no ingest/indexer path on this source) | - | - | - | - | - | - |
| file-light20m-nauto-w14 | 111 | 0,1,2,3 | 1603.4 | 1598.8 | 0.03 | 20 | 1 | 1.00 | 64 |
| file-light20m-nauto-w14-plugin | 90 | 0,1,2,3 | 2033.6 | 2031.9 | 0.13 | 20 | 1 | 1.00 | 0 |
| file-light20m-nauto-w4 | 123 | 0,1,2,3 | 1456.4 | 1440.9 | 0.00 | 0 | 1 | 1.00 | 229 |
| pipe-light20m-nauto-w14 | 129 | 0,1,2,3 | 7494.1 | 7492.9 | 0.04 | 20 | 1 | 1.00 | 1 |
| plugin-light60m-nauto-w14 | 259 | 0,1,2,3 | 2052.5 | 2051.9 | 0.08 | 40 | 1 | 1.00 | 0 |
| smoke-light-100k-nauto | 6 | 0,1,2,3 | 2886.5 | 962.2 | 0.00 | 0 | 1 | 1.00 | 0 |

### Per-node detail

| case | node | nonempty | longest empty ms | published/s | claimed/s | c/s | supply gap/s | gap batches | endpoint-persistent claimed/s | intervals | c-mismatch intervals | counter regressions |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| file-light20m-n1-w14 | n0 | 1.00 | 0 | 11618.1 | 7637.9 | 7637.9 | -3980.2 | -5232 | 0.0 | 3 | 0 | - |
| file-light20m-nauto-w14 | n0 | 0.96 | 20 | 2531.2 | 2509.6 | 2509.6 | -21.7 | -47 | 2272.4 | 98 | 2 | - |
| file-light20m-nauto-w14 | n1 | 0.95 | 40 | 2334.3 | 2309.9 | 2309.9 | -24.4 | -53 | 2198.9 | 100 | 0 | - |
| file-light20m-nauto-w14 | n2 | 0.97 | 40 | 1884.3 | 1857.0 | 1857.0 | -27.2 | -59 | 1742.2 | 102 | 0 | - |
| file-light20m-nauto-w14 | n3 | 0.97 | 20 | 1731.6 | 1706.2 | 1706.2 | -25.4 | -55 | 1690.1 | 102 | 0 | - |
| file-light20m-nauto-w14-plugin | n0 | 0.38 | 180 | 3030.2 | 3030.2 | 3030.2 | +0.0 | 0 | 2975.0 | 12 | 0 | - |
| file-light20m-nauto-w14-plugin | n1 | 0.33 | 280 | 2703.3 | 2703.3 | 2703.3 | +0.0 | 0 | 2528.6 | 10 | 0 | - |
| file-light20m-nauto-w14-plugin | n2 | 0.61 | 120 | 2663.5 | 2660.0 | 2660.0 | -3.5 | -6 | 2693.0 | 33 | 0 | - |
| file-light20m-nauto-w14-plugin | n3 | 0.56 | 100 | 2547.1 | 2547.1 | 2547.1 | +0.0 | 0 | 2634.1 | 30 | 2 | - |
| file-light20m-nauto-w4 | n0 | 1.00 | 0 | 2044.4 | 2029.3 | 2029.3 | -15.1 | -36 | 1712.3 | 117 | 0 | - |
| file-light20m-nauto-w4 | n1 | 1.00 | 0 | 2031.4 | 2016.4 | 2016.4 | -15.1 | -36 | 1808.1 | 117 | 0 | - |
| file-light20m-nauto-w4 | n2 | 1.00 | 0 | 2178.5 | 2162.1 | 2162.1 | -16.3 | -39 | 1844.7 | 117 | 0 | - |
| file-light20m-nauto-w4 | n3 | 1.00 | 0 | 1962.3 | 1948.9 | 1948.9 | -13.4 | -32 | 1856.7 | 117 | 0 | - |
| pipe-light20m-nauto-w14 | n0 | 0.03 | 825 | 3224.9 | 3224.9 | 3224.9 | +0.0 | 0 | - | 0 | 28 | - |
| pipe-light20m-nauto-w14 | n1 | 0.01 | 825 | 2285.5 | 2285.5 | 2285.1 | +0.0 | 0 | - | 0 | 35 | - |
| pipe-light20m-nauto-w14 | n2 | 0.03 | 825 | 2165.7 | 2165.7 | 2165.7 | +0.0 | 0 | 1703.4 | 2 | 16 | - |
| pipe-light20m-nauto-w14 | n3 | 0.07 | 586 | 2858.2 | 2857.8 | 2857.8 | -0.4 | -1 | 1999.6 | 2 | 14 | - |
| plugin-light60m-nauto-w14 | n0 | 0.44 | 160 | 2669.9 | 2669.9 | 2669.9 | +0.0 | 0 | 2612.9 | 37 | 0 | - |
| plugin-light60m-nauto-w14 | n1 | 0.41 | 140 | 2565.1 | 2564.7 | 2564.7 | -0.4 | -2 | 2599.3 | 36 | 0 | - |
| plugin-light60m-nauto-w14 | n2 | 0.52 | 140 | 2565.7 | 2565.3 | 2565.3 | -0.4 | -2 | 2571.2 | 59 | 4 | - |
| plugin-light60m-nauto-w14 | n3 | 0.52 | 130 | 2566.1 | 2565.7 | 2565.7 | -0.4 | -2 | 2588.0 | 64 | 0 | - |
| smoke-light-100k-nauto | n0 | 0.33 | 4 | 160.4 | 80.2 | 80.2 | -80.2 | -1 | - | 0 | 0 | - |
| smoke-light-100k-nauto | n1 | 0.33 | 4 | 80.2 | 0.0 | 0.0 | -80.2 | -1 | - | 0 | 0 | - |
| smoke-light-100k-nauto | n2 | 0.33 | 4 | 19644.0 | 3287.4 | 3287.4 | -16356.6 | -204 | - | 0 | 0 | - |
| smoke-light-100k-nauto | n3 | 0.00 | 5 | 0.0 | 0.0 | 0.0 | +0.0 | 0 | - | 0 | 0 | - |

`published/s` is the RAW `write_idx` delta (batches the scanner published); `claimed/s` is the RAW `read_idx` delta (batches workers claimed); depth (`write_idx - read_idx`) is used ONLY for occupancy. `c/s` is `total_lines_consumed`, incremented once per successful claim: it is a cross-check on the claim position, and intervals where `c` and `read_idx` disagree are counted rather than reconciled. A counter regression is counted and excluded from the rate; it is never silently treated as zero work.

`supply gap/s` is computed PER NODE over the intervals where that node's publication and claim counters are both valid: a positive value means worker claims exceeded scanner publication on that node over those intervals, i.e. a scanner-side supply deficit relative to worker demand (workers drew down previously queued work). It is NOT evidence by itself that the downstream stage is the limiter; the q/i timeline decides whether the scanner was starved for input or unable to process available input. It is not an aggregate rate compared against the fastest node, so one node's surplus cannot hide another's deficit.

The chunk queue uses the opposite pair order: `q` is (`chunk_queue_head`, `chunk_queue_tail`), where head is the ingest publication counter and tail is the scanner/indexer claim counter. `chunk published/s` and `chunk consumed/s` are the raw head and tail deltas respectively. Batch groups (`b`/`c`/`a`) are emitted by both the UMA scanner and the NUMA C ingest; `q`/`i` are owned by src=ingest only.

`endpoint-persistent claimed/s` uses intervals where that node's batch queue was non-empty at BOTH sampled ends. This is an endpoint-persistent estimate, not proof that the queue never emptied between two 20 ms samples; a queue that dips and refills between samples is counted as continuously available here.

`gated_ms` is the ingest backlog-gated wait accumulated by the engine sampler (ingest source only). `q`/`i` are reported only when the source has an ingest->indexer path; the UMA scanner has no indexer, so those fields are reported as NOT MEASURABLE, never as zero.

## Time-correlated same-interval evidence

The NUMA C ingest emits `q`, `i`, `b`, `c`, `a`, `cpu_ns` and `t_us` on ONE CLOCK_MONOTONIC origin. Observations are consumed in ORIGINAL order; each timestamp is validated against the immediately preceding observation, and a missing, malformed, duplicate or decreasing timestamp breaks the timeline so no interval is constructed across it. Consecutive valid observations form one timeline per trial, and the predicates below are evaluated on the SAME per-node interval. Trial-level co-occurrence is never treated as correlation. All elapsed-time math uses `t_us`; `t_ms` is human-readable only.

Predicates: **ingest->indexer starvation** = the node's chunk queue is empty at both sampled endpoints and its indexer waiter gauge is positive in the same interval. **Scanner->worker starvation** = the batch queue is empty at both endpoints and workers are waiting in the same interval while upstream input is available (nonzero chunk depth or no indexer waiters). **Global ingest-thread CPU saturation** = the emitting ingest thread's `delta(cpu_ns)/delta(t_us)` is inside the declared near-one-core reading band in the same interval. This is ONE global measurement per interval, evaluated alongside each node's queue evidence; it is not an independently measured per-node CPU value. **Supply deficit** = raw `read_idx` delta exceeds raw `write_idx` delta on the node in the same interval (worker claims exceed scanner publication). **GO interval** requires all of these together, with the batch queue draining or empty and no backlog-gated ingest wait. **Mixed** means ingest starvation and upstream-available scanner/worker starvation occur in different intervals of the same trial: ambiguous, not "scanner starvation absent".

Excluded observations/intervals are counted, never bridged: missing or malformed timestamps, duplicate or decreasing timestamps, missing or regressed `cpu_ns`, missing per-node groups, or a counter regression removes the affected interval(s) from every predicate. `attribution_complete` is false whenever any relevant observation or interval was excluded.

Per-trial predicate columns are summed over nodes (node-intervals); `intervals` and `duration s` are timeline intervals. The per-node table below gives the same counts for each node. The `GO ingest-thread CPU cores (global)` column is the shared global ingest-thread CPU measured over that node's GO intervals, not a per-node CPU measurement.

| case | trial | intervals | duration s | ingest-starved node-iv | global-CPU-sat starved node-iv | scanner-starved node-iv | source-limited node-iv | backpressure node-iv | GO node-iv | GO s | GO deficit/s | GO ingest-thread CPU cores (global) | excluded |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| file-light20m-n1-w14 | - | 0 | - | NOT AVAILABLE (no src=ingest timeline) | - | - | - | - | - | - | - | - | - |
| file-light20m-nauto-w14 | 1 | 36 | 0.73 | 20 | 17 | 2 | 0 | 64 | 0 | 0.00 | - | - | 0 |
| file-light20m-nauto-w14 | 2 | 37 | 0.73 | 24 | 21 | 1 | 0 | 68 | 0 | 0.00 | - | - | 0 |
| file-light20m-nauto-w14 | 3 | 35 | 0.71 | 14 | 14 | 2 | 0 | 60 | 0 | 0.00 | - | - | 0 |
| file-light20m-nauto-w14-plugin | 1 | 28 | 0.54 | 70 | 70 | 19 | 0 | 0 | 9 | 0.16 | 91.1 | 0.99 | 0 |
| file-light20m-nauto-w14-plugin | 2 | 29 | 0.57 | 68 | 68 | 21 | 0 | 0 | 14 | 0.27 | 82.7 | 0.98 | 0 |
| file-light20m-nauto-w14-plugin | 3 | 30 | 0.60 | 77 | 77 | 26 | 0 | 0 | 16 | 0.32 | 69.2 | 0.99 | 0 |
| file-light20m-nauto-w4 | 1 | 40 | 0.80 | 0 | 0 | 0 | 0 | 156 | 0 | 0.00 | - | - | 0 |
| file-light20m-nauto-w4 | 2 | 41 | 0.82 | 1 | 1 | 0 | 0 | 156 | 0 | 0.00 | - | - | 0 |
| file-light20m-nauto-w4 | 3 | 39 | 0.77 | 3 | 3 | 0 | 0 | 148 | 0 | 0.00 | - | - | 0 |
| pipe-light20m-nauto-w14 | 1 | 42 | 0.83 | 99 | 99 | 61 | 0 | 0 | 9 | 0.18 | 50.0 | 0.99 | 0 |
| pipe-light20m-nauto-w14 | 2 | 42 | 0.83 | 99 | 99 | 59 | 0 | 4 | 15 | 0.30 | 56.7 | 0.99 | 0 |
| pipe-light20m-nauto-w14 | 3 | 42 | 0.83 | 92 | 92 | 57 | 0 | 8 | 13 | 0.26 | 50.0 | 0.99 | 0 |
| plugin-light60m-nauto-w14 | 1 | 86 | 1.72 | 191 | 191 | 56 | 0 | 0 | 54 | 1.08 | 73.1 | 0.99 | 0 |
| plugin-light60m-nauto-w14 | 2 | 85 | 1.69 | 197 | 197 | 59 | 0 | 0 | 47 | 0.94 | 74.7 | 0.99 | 0 |
| plugin-light60m-nauto-w14 | 3 | 85 | 1.69 | 202 | 202 | 66 | 0 | 0 | 36 | 0.72 | 73.7 | 0.99 | 0 |
| smoke-light-100k-nauto | 1 | 1 | 0.00 | 1 | 1 | 1 | 0 | 0 | 0 | 0.00 | - | - | 0 |
| smoke-light-100k-nauto | 2 | 1 | 0.00 | 0 | 0 | 4 | 0 | 0 | 0 | 0.00 | - | - | 0 |
| smoke-light-100k-nauto | 3 | 1 | 0.00 | 0 | 0 | 4 | 0 | 0 | 0 | 0.00 | - | - | 0 |

### Per-node same-interval detail

| case | node | intervals | ingest starved | global-CPU-sat starved | scanner starved | source limited | worker waits | supply-gap intervals | GO intervals | GO s | GO deficit/s | GO ingest-thread CPU cores (global) | chunk pub/s | chunk cons/s | batch pub/s | batch claim/s | counter regressions | c-mismatch intervals |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| file-light20m-nauto-w14 | n0 | 108 | 15 | 14 | 0 | 0 | 8 | 43 | 0 | 0.00 | - | - | 444.5 | 443.6 | 2531.2 | 2509.6 | 0 | 2 |
| file-light20m-nauto-w14 | n1 | 108 | 17 | 13 | 4 | 0 | 8 | 50 | 0 | 0.00 | - | - | 441.8 | 440.9 | 2334.3 | 2309.9 | 0 | 0 |
| file-light20m-nauto-w14 | n2 | 108 | 14 | 13 | 0 | 0 | 4 | 50 | 0 | 0.00 | - | - | 365.7 | 364.8 | 1884.3 | 1857.0 | 0 | 0 |
| file-light20m-nauto-w14 | n3 | 108 | 12 | 12 | 1 | 0 | 4 | 44 | 0 | 0.00 | - | - | 351.4 | 349.6 | 1731.6 | 1706.2 | 0 | 0 |
| file-light20m-nauto-w14-plugin | n0 | 87 | 43 | 43 | 21 | 0 | 73 | 24 | 7 | 0.14 | 50.1 | 0.99 | 509.4 | 507.7 | 3030.2 | 3030.2 | 0 | 0 |
| file-light20m-nauto-w14-plugin | n1 | 87 | 51 | 51 | 24 | 0 | 72 | 19 | 11 | 0.22 | 50.4 | 0.99 | 509.4 | 509.4 | 2703.3 | 2703.3 | 0 | 0 |
| file-light20m-nauto-w14-plugin | n2 | 87 | 63 | 63 | 7 | 0 | 53 | 22 | 10 | 0.20 | 95.0 | 0.99 | 504.2 | 504.2 | 2663.5 | 2660.0 | 0 | 0 |
| file-light20m-nauto-w14-plugin | n3 | 87 | 58 | 58 | 14 | 0 | 55 | 23 | 11 | 0.19 | 115.6 | 0.98 | 510.6 | 510.6 | 2547.1 | 2547.1 | 0 | 2 |
| file-light20m-nauto-w4 | n0 | 120 | 1 | 1 | 0 | 0 | 0 | 37 | 0 | 0.00 | - | - | 344.3 | 340.5 | 2044.4 | 2029.3 | 0 | 0 |
| file-light20m-nauto-w4 | n1 | 120 | 1 | 1 | 0 | 0 | 0 | 49 | 0 | 0.00 | - | - | 365.7 | 361.5 | 2031.4 | 2016.4 | 0 | 0 |
| file-light20m-nauto-w4 | n2 | 120 | 1 | 1 | 0 | 0 | 0 | 51 | 0 | 0.00 | - | - | 370.7 | 366.9 | 2178.5 | 2162.1 | 0 | 0 |
| file-light20m-nauto-w4 | n3 | 120 | 1 | 1 | 0 | 0 | 0 | 51 | 0 | 0.00 | - | - | 375.7 | 371.9 | 1962.3 | 1948.9 | 0 | 0 |
| pipe-light20m-nauto-w14 | n0 | 126 | 70 | 70 | 47 | 0 | 126 | 15 | 11 | 0.22 | 59.1 | 0.99 | 1881.3 | 1880.5 | 3224.9 | 3224.9 | 0 | 28 |
| pipe-light20m-nauto-w14 | n1 | 126 | 90 | 90 | 27 | 0 | 125 | 18 | 14 | 0.28 | 50.0 | 0.99 | 1884.5 | 1884.5 | 2285.5 | 2285.5 | 0 | 35 |
| pipe-light20m-nauto-w14 | n2 | 126 | 65 | 65 | 53 | 0 | 124 | 8 | 5 | 0.10 | 50.1 | 0.99 | 1863.5 | 1863.1 | 2165.7 | 2165.7 | 0 | 16 |
| pipe-light20m-nauto-w14 | n3 | 126 | 65 | 65 | 50 | 0 | 118 | 12 | 7 | 0.14 | 49.8 | 0.99 | 1864.8 | 1864.8 | 2858.2 | 2857.8 | 0 | 14 |
| plugin-light60m-nauto-w14 | n0 | 256 | 139 | 139 | 48 | 0 | 212 | 76 | 34 | 0.68 | 50.1 | 0.99 | 512.4 | 512.4 | 2669.9 | 2669.9 | 0 | 0 |
| plugin-light60m-nauto-w14 | n1 | 256 | 147 | 147 | 55 | 0 | 219 | 67 | 34 | 0.68 | 50.0 | 0.99 | 513.2 | 513.0 | 2565.1 | 2564.7 | 0 | 0 |
| plugin-light60m-nauto-w14 | n2 | 256 | 154 | 154 | 35 | 0 | 186 | 85 | 37 | 0.74 | 97.6 | 0.99 | 513.2 | 513.2 | 2565.7 | 2565.3 | 0 | 4 |
| plugin-light60m-nauto-w14 | n3 | 256 | 150 | 150 | 43 | 0 | 183 | 75 | 32 | 0.64 | 96.7 | 0.99 | 513.6 | 513.2 | 2566.1 | 2565.7 | 0 | 0 |
| smoke-light-100k-nauto | n0 | 3 | 0 | 0 | 2 | 0 | 2 | 0 | 0 | 0.00 | - | - | 721.6 | 160.4 | 160.4 | 80.2 | 0 | 0 |
| smoke-light-100k-nauto | n1 | 3 | 0 | 0 | 2 | 0 | 3 | 0 | 0 | 0.00 | - | - | 641.4 | 240.5 | 80.2 | 0.0 | 0 | 0 |
| smoke-light-100k-nauto | n2 | 3 | 1 | 1 | 2 | 0 | 2 | 0 | 0 | 0.00 | - | - | 801.8 | 481.1 | 19644.0 | 3287.4 | 0 | 0 |
| smoke-light-100k-nauto | n3 | 3 | 0 | 0 | 3 | 0 | 3 | 0 | 0 | 0.00 | - | - | 721.6 | 80.2 | 0.0 | 0.0 | 0 | 0 |

`GO deficit/s` is the per-trial or per-node supply deficit measured ONLY over GO intervals, so it is not netted against intervals with a surplus. The verdict requires every trial to have GO intervals, the weakest trial's GO deficit rate to exceed the full trial-to-trial spread of those rates, complete attribution (zero exclusions), no source-limited intervals, no upstream-available scanner/worker starvation, and no mixed trial. The endpoint-sampling caveat applies: two samples 20 ms apart cannot prove the queue was continuously empty between them.

## Demand classification (spec §4.3/§8)

| case | same-interval supply gap | ingest->indexer starvation | scanner->worker starvation | workers saturated | source-limited | ingest backpressure | correlated GO case | GO trials | GO node-iv | GO deficit/s min/median/max; spread | excluded |
|---|---|---|---|---|---|---|---|---|---|---|---|
| file-light20m-n1-w14 | no | no | ? | yes | ? | no | no | 0 | 0 | not measured | 0 |
| file-light20m-nauto-w14 | yes | yes | yes | no | no | yes | no | 0 | 0 | not measured | 0 |
| file-light20m-nauto-w14-plugin | yes | yes | yes | no | no | no | no | 3 | 39 | min/median/max 69.2/82.7/91.1 batches/s; spread 21.8 | 0 |
| file-light20m-nauto-w4 | yes | yes | no | no | no | yes | no | 0 | 0 | not measured | 0 |
| pipe-light20m-nauto-w14 | yes | yes | yes | no | no | yes | no | 3 | 37 | min/median/max 50.0/50.0/56.7 batches/s; spread 6.7 | 0 |
| plugin-light60m-nauto-w14 | yes | yes | yes | no | no | no | no | 3 | 137 | min/median/max 73.1/73.7/74.7 batches/s; spread 1.6 | 0 |
| smoke-light-100k-nauto | no | yes | yes | no | no | no | no | 0 | 0 | not measured | 0 |

`?` means the quantity is not measurable on this source path, not that it is absent. `same-interval supply gap` means at least one per-node interval had worker claims above scanner publication; it is not an aggregate trial rate. `correlated GO case` is the full case-level predicate (every trial, complete attribution, no mixed trial, no source-limited interval, no upstream-available scanner/worker starvation, and a deficit larger than the trial-to-trial spread); `GO node-iv` counts the individual intervals that meet the conditions, so a case can have GO intervals without being a GO case. A supply gap is attributed to centralized ingestion only when the SAME per-node interval shows ingest->indexer starvation, the global ingest-thread CPU near one core, workers waiting, and the batch queue draining (spec §4.2); an empty chunk queue with indexer waiters while the global ingest-thread CPU is well below one core is classified source-limited. A positive `claims - publications` is a scanner-side supply deficit relative to worker demand, not by itself evidence that downstream is the limiter; q/i decides whether the scanner lacked input or could not process available input.

## 2×2 affinity/policy ablation (spec §6)

Node arguments: X (affinity) = 0, Y (policy) = 1; X CPUs=[0, 1, 2, 3, 4, 5, 6, 7], Y CPUs=[0, 1, 2, 3, 4, 5, 6, 7]; fake_numa=numa=fake=4.

| cell/form | requested mode | effective mode | effective mask | affinity | first-touch cpu | pages by node | unknown | placement | mincore | read-touch |
|---|---|---|---|---|---|---|---|---|---|---|
| A/map-fault | MPOL_DEFAULT (0) | MPOL_DEFAULT | [] | cpu=None rc=None | 11 | {'0': 2048} | 0 | True | 2048/2048 | n/a (None pages) |
| A/write-path | MPOL_DEFAULT (0) | MPOL_DEFAULT | [] | cpu=None rc=None | 16 | {'1': 768, '2': 1280} | 0 | True | 2048/2048 | stable (None pages) |
| B/map-fault | MPOL_DEFAULT (0) | MPOL_DEFAULT | [] | cpu=0 rc=0 | 0 | {'0': 1981, '1': 67} | 0 | True | 2048/2048 | n/a (None pages) |
| B/write-path | MPOL_DEFAULT (0) | MPOL_DEFAULT | [] | cpu=0 rc=0 | 0 | {'0': 512, '1': 1280, '2': 256} | 0 | True | 2048/2048 | stable (None pages) |
| C/map-fault | MPOL_BIND (2) | MPOL_BIND | [1] | cpu=None rc=None | 26 | {'1': 2048} | 0 | True | 2048/2048 | n/a (None pages) |
| C/write-path | MPOL_BIND (2) | MPOL_BIND | [1] | cpu=None rc=None | 2 | {'1': 2048} | 0 | True | 2048/2048 | stable (None pages) |
| D/map-fault | MPOL_BIND (2) | MPOL_BIND | [1] | cpu=0 rc=0 | 0 | {'1': 2048} | 0 | True | 2048/2048 | n/a (None pages) |
| D/write-path | MPOL_BIND (2) | MPOL_BIND | [1] | cpu=0 rc=0 | 0 | {'1': 2048} | 0 | True | 2048/2048 | stable (None pages) |

Ablation validity: PASS

Write-path residency: pre-touch `move_pages` statuses are [-2]; post-touch statuses are real node ids and `numa_maps` gains N-fields. Raw per-page statuses are preserved in the JSON. The read-touch stability check re-queries EVERY page of the measured range after the full range was read-touched; unstable pages are 0.

On this fake topology every CPU is listed on every node, so the affinity arm cannot be distinguished from the policy arm by CPU placement. The C/D result shows that the corrected `MPOL_BIND` request is effective; it does not establish physical affinity behavior.

## Provenance

- git:  @ 38bda5ac2e5127ade192d017b9985c222d8965b1 (dirty=False)
- source worktree: CLEAN (reported SHA identifies the source)
- kernel: 7.1.10-200.numa_emu.fc44.x86_64 | fake-numa: numa=fake=4
- CPU topology: node0=0-27, node1=0-27, node2=0-27, node3=0-27
- shmem THP: [always] within_size advise never deny force
- governors: ['powersave'] | SMT: {'thread_siblings': 'unknown'}
- cpuset: None | memory.max: None
- build hashes: frun.bash=fdf5fcf30905, _forkrun_cleanroom=7d0644fc39bb, _fr_udf.cpython-314-x86_64-linux-gnu.so=9c69deeb8176, libforkrun_python.so=9dd9bad00e5b
- campaign env: `env/env-before.json` / `env/env-after.json`
- before/after drift: none

## Baseline identity (4.7 vs 5.0)

- baseline-60m-plugin-w14: 4.7 median 31766227.2 rec/s, 5.0 median 30007759.5 rec/s (delta -5.5%)

Interleaved paired runs of the same child payload, corpus, worker count, and stage0 harness; only python/forkrun differs. The 4.7 engine has no STAGE0_DIAG sampler, so its trials are marked incomplete by the harness; throughput comes from the same child_report timer and is still comparable. The 5.0 diagnostic sampler is observational only.

## One-page decision summary

**Is the central ingest the limiter?** NOT DECIDABLE on this fake-NUMA host. The per-node queue, global ingest-thread CPU, and worker-waiter metrics are present, but spec §8 requires physical multi-node evidence; this rehearsal returns Inconclusive by rule.

**Is placement born-local?** The corrected ablation shows that `MPOL_BIND` is requested with mode 2, is effective, and places destination pages on the bound node in both materialization forms. Because every CPU is listed on every fake node, this validates the instrumentation and the policy path, not physical born-local behavior.

**What remains?** Rental execution of this exact campaign on physical multi-node hardware, with `--node-x/--node-y` set to distinct physical nodes, then the §8 verdict from the same report generator.
