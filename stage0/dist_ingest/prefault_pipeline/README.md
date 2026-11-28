# WO-NUMA-PIPELINED-MADV-POPULATE-WRITE-STAGE0 — prefault pipeline prototype

**Standalone, experimental, NOT production.** Does NOT modify or integrate
`stage0/dist_ingest/dist_ingest.c`/`dist_ingest.h`, the existing FAA/backlog
claiming, production Bash/Python frontends, or frozen production files.
Independently buildable; isolated from the existing engine.

## Question
Can a bounded pipeline of speculative destination-slot reservations +
node-local `MADV_POPULATE_WRITE` workers move memory materialization out
of the critical path of NUMA ingest — converting otherwise-idle input-wait
time into useful memory preparation — improving effective ingest
throughput? (Not theoretical `memcpy`/memory bandwidth.)

## Architecture (bounded ring; one shared memfd MAP_SHARED)
Separate: reserve future destination ≠ materialize backing ≠ receive
stdin ≠ `memcpy` into prepared destination ≠ publish ≠ consume ≠ reclaim
+ reprepare. **Reservation is not a claim on input.** No advancing input
offset on reservation; no nonexistent data published; no input accounting
on reservation. Separate reserved/preparing accounting vs actual
received/published.

- `memfd_create` + `ftruncate` + `mmap(PROT_READ|PROT_WRITE, MAP_SHARED)`.
- One shared mapping; slots page-aligned; 2 MiB slots default; configurable.
- **Guaranteed alignment**: oversize reserve then carve + `munmap` slack;
  validated (`map_base_alignment`); not assumed; 2 MiB slot ≠ 2 MiB hugepage
  (actual `move_pages` observation; THP shmem recorded; not claimed).
- Total backing bounded `num_nodes × slots_per_node × slot_size` (+ staging
  + bookkeeping, reported); no unbounded future; overflow/dims rejected;
  sparse physical node IDs; not `0..N-1`.
- Prep worker: pin to allowed CPU on node; **per-thread `set_mempolicy`
  (`SYS_set_mempolicy`, `MPOL_BIND` then `MPOL_PREFERRED`) on the CALLING
  thread** (thread doing `MADV_POPULATE_WRITE`); **+ `mbind` slot range**
  (defense in depth; **not a substitute**); shmem semantics documented;
  failed affinity/policy = explicit failure. Worker reserves→`MADV_POPULATE_
  WRITE`→READY only after full success. **Pipeline reader never prepares.**
- Round-robin prepared-slot assignment across nodes; skipping no-ready
  nodes; no new adaptive scheduler.
- **Slot state machine** `FREE→RESERVED→PREPARING→READY→ASSIGNED→COPYING→
  PUBLISHED→CONSUMED→RECLAIMING→FREE`; checked transitions; **generation**
  rejects stale completions; lazy/serial skip PREPARING explicitly; not
  recycled before consumer + reclamation.

## Input (actual stdin; ordered; not file pread)
Single ordered reader; hold ≤1 assigned slot while waiting; preallocated
per-node **staging** (prepared, policy known); `poll()`/`ppoll` input-wait;
partial reads until full/EOF; EINTR; read error; premature/empty EOF;
**empty final read NOT published**; assign actual global offset + valid len
ONLY after bytes received; **explicit `memcpy` staging→dest (NOT
read-into-dest)**; publish after copy; exactly-once ordered accounting.
Distinguish input-idle (reader blocked on stdin) vs prepared-slot
starvation/backpressure (reader waiting for READY slot).
Identical staging + copy-thread affinity across modes.

## Reclamation (same lifecycle all modes)
Consumer validates (bytes checksum + ordering + no dup/gap/overlap +
generation + no publish-before-copy + not recycled before consumer) →
ack → `CONSUMED→RECLAIMING` → `fallocate(FALLOC_FL_PUNCH_HOLE|
FALLOC_FL_KEEP_SIZE)` on slot → verify rc → `FREE` + generation++ →
reprepare. **No silent fallback; capability failure stops.** Optional
consumer delay. Works when input >> ring capacity; many wraps.

## Modes (same mapping/ring/staging/reader/consumer/reclamation; only prep differs)
- `lazy`: reserve; NO `MADV_POPULATE_WRITE`; genuinely lazy; copy → normal
  first-write faults during `memcpy`.
- `serial_madvise`: ingest thread pins + sets policy + `MADV_POPULATE_
  WRITE` synchronously; then input + copy; time included in e2e.
- `pipeline_madvise`: independent node-local workers reserve + populate
  future slots; reader leases only READY; reader idle→prepare overlap;
  reclaim→reprepare; reader not preparing.

## Measurements (machine-readable JSON + Markdown)
e2e wall + B/s + slots + per-node bytes/slots + validity; prep ops/bytes/
per-node time/throughput/latency(min,med,p95,max via campaign)/errno/
awaiting/ready/max-avg lookahead; **overlap**: input-wait vs slot-wait
separate; prep-worker busy; **summed worker-time overlapping input-wait +
union wall-clock any-worker-active** (not worker-sec=wall-sec);
prep-completed-while-blocked; no-prepared count; writer backpressure;
**`prepared_destination_bytes/total_received`** (byte counts only after
successful `MADV_POPULATE_WRITE` before copy); ready-before-assign vs
ready-after-arrival; time-waiting-for-prepared; copied prepared vs lazy;
memcpy wall/per-slot/throughput; **thread minor/major faults around copy
(RUSAGE_THREAD)**; **`move_pages()` placement sampling** (sample count,
per-node, unknown, errors, target, distinguishable, NOT in timed region);
shmem THP + map stats. `madvise()==0` ≠ proven placement/throughput.

## Failure injection seams (`--seam`)
`no-worker-create`, `affinity`, `mempolicy`, `madvise`, `partial-prep`,
`punch-hole`, `consumer`, `read`, `read-eintr`, `eintr`, `empty-eof`,
`shutdown-prep`, `shutdown-reader-input`, `shutdown-reader-slot`,
`stale-gen`. No failed/partial prep → READY; no publish before copy; no
recycle before consumer+reclaim; no stale-gen effect; shutdown joins all;
no deadlock/unbounded; truthful result; no silent drop/dup; no silent
reclaim fallback.

## Build
```bash
make -C stage0/dist_ingest/prefault_pipeline clean
make -C stage0/dist_ingest/prefault_pipeline          # strict diagnostics
make -C stage0/dist_ingest/prefault_pipeline asan-ubsan   # isolated -asan
make -C stage0/dist_ingest/prefault_pipeline tsan         # isolated -tsan
```
Strict `-Wall -Wextra -Wpedantic -Wshadow -Wconversion`; separate
isolated sanitizer artifacts (don't clobber `all`).

## Tests
```bash
python3 -m unittest stage0.dist_ingest.prefault_pipeline.tests.test_prefault_pipeline
```
39 tests: correctness, ordering, no dup/gap/overlap, no premature reuse,
no stale gen, no publish-before-copy, empty/small/exact/partial final,
many wraps, partial reads, EINTR, burst/gap, sparse multi-node,
consumer delay, lazy/serial/pipeline, reclamation, all failure seams,
config validation, state machine.

## Benchmark campaign (A/B/C; identical params; deterministic input+schedule)
```bash
make -C stage0/dist_ingest/prefault_pipeline
python3 stage0/dist_ingest/prefault_pipeline/benchmarks/prefault_bench.py \
    --bin stage0/dist_ingest/prefault_pipeline/prefault_pipeline \
    --out /tmp/prefault-campaign --total-bytes 67108864 --slot-size 2097152 \
    --slots-per-node 2 --workers-per-node 1 \
    --schedules continuous,burst-gap,bursty-variable --burst-size 262144 --gap 0.002 \
    --reps 5 --order randomize [--nodes 0,1,2,3] [--placement-sampling] [--consumer-delay-ns N]
```
Actual stdin/pipe; same deterministic bytes + arrival schedule per mode;
multi-rep; **randomize/alternate order**; raw JSON + stderr logs +
campaign.json + summary.md; total > ring capacity (many generations);
no improvement threshold. Sample `sample_campaign/`.

## Physical-NUMA rental campaign (no source changes; runtime params only)
```bash
make -C stage0/dist_ingest/prefault_pipeline
# discover nodes on the rented machine, then run identical A/B/C:
python3 stage0/dist_ingest/prefault_pipeline/benchmarks/prefault_bench.py \
    --bin stage0/dist_ingest/prefault_pipeline/prefault_pipeline \
    --out "$OUT" --total-bytes N --slot-size 2097152 \
    --slots-per-node D --workers-per-node W \
    --nodes "$SPARSE_NODE_LIST" \   # e.g. 0,4 or 1,3 ; CPU affinity handled by worker pinning
    --schedules continuous,burst-gap,bursty-variable --gap G --burst-size B \
    --reps 7 --order randomize --placement-sampling
```
Vary ONLY runtime params (node list, CPU affinity [worker pinning + per-
thread policy], slot depth, input schedule, test size). No source
modifications. Answer questions in CLOSEOUT. **Not production-adopted;
Gate 1 unsigned; no rental authorized by this work order; physical-NUMA
not claimed.**

## Sanitizers
See `SANITIZER_EVIDENCE.md`. NOT claiming existing dist_ingest sanitizer
evidence covers this prototype.
