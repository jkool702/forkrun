# WO-NUMA-DIST-INGEST-CORRECTIONS-AND-VALIDATION-2 — Closeout Report

**Work order:** `WO-NUMA-DIST-INGEST-CORRECTIONS-AND-VALIDATION-2` (corrective and validation; not a rewrite).  
**Status:** corrective implementation, Section 5 comparable benchmark harness, and validation completed on this host through the committed checkpoints below. **No physical-NUMA hardware rented. No production adoption claimed.**

## 1. Repository state

- **Branch:** `NEW/REFACTOR5.1`
- **Starting baseline (prototype suite):** `419c0ce1cdd57e06168ba2d91c0d1400e79489e6` (preserved)
- **Corrective checkpoints (this WO lineage, pushed):**
  - `7e3a4d08` — `dist-ingest: apply WO-NUMA-DIST-INGEST-CORRECTIONS-AND-VALIDATION-2 sections 1-4 (checkpoint)`
  - `f9bc3541` — `dist-ingest: apply WO-NUMA-DIST-INGEST-CORRECTIONS-AND-VALIDATION-2 Addendum A checkpoint`
  - `b542dc6d` — `dist-ingest: apply WO-NUMA-DIST-INGEST-ADDENDUM-A-CLOSEOUT-1 checkpoint` (Addendum A closeout accepted)
  - `68d3efcb` — `dist-ingest: section 5 comparable engine benchmark and centralized baseline` (Section 5 comparability/benchmark)
- **Final HEAD (this closeout):** to be recorded by the final commit created with this closeout (see git history).
- **Working-tree status at closeout:** clean after final commit/push (intended).
- **Frozen files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched).
- **Isolation:** experimental changes confined to `stage0/dist_ingest/` plus necessary, backward-compatible Stage 0 integration (`stage0/run_case.py`, dist campaign/report/docs); production ingestion/frontend behavior unchanged.

### Files in scope (key)

- `stage0/dist_ingest/dist_ingest.{h,c}`, `stage0/libdist_ingest.so` (gitignored build artifact)
- `stage0/dist_ingest/run_dist.py`, `run_dist_campaign.sh`, `report_dist.py`
- `stage0/dist_ingest/tests/{test_dist_ingest.py,test_addendum_a.py,test_topology_resolution.py,test_corrections_s2_s4.py,test_corrections_s3.py}`
- `stage0/dist_ingest/{RENTAL_RECIPE.md,CLOSEOUT.md,PIPE_INGESTION.md}`
- `stage0/run_case.py`

## 2. Defect resolution (by work-order section)

### Section 1 (P0) — Real NUMA topology, CPU affinity, and memory placement
- **Original defect:** runner did not wire real topology/CPU lists/phys nodes to engine; no effective affinity/placement establishment or verification.
- **Correction:** topology resolution/provenance in `run_dist.py` (online nodes, per-node CPUs/memory, allowed CPU/mem sets, cpuset/cgroup restrictions respected where discoverable, logical→physical mapping, explicit `--phys-nodes`, duplicate/insufficient/invalid rejection, strict validation of unknown topology facts). Properly typed/lifetime-safe ctypes topology structures. Per-role CPU affinity (ingestor/consumer) pinned to configured physical-node CPU sets with pthread return-code handling, set/query/verification and matched/effective reporting; strict-affinity failure marking. Memory placement via `mbind(MPOL_PREFERRED)` on configured physical node before first touch where applicable, with syscall success/error recorded (not physical-placement proof), strict-mbind mode, and independent placement sampling (`move_pages`) with unknown/permission-denied preserved as unknown. Dynamic/safe CPU-mask sizing and kernel-mask probing (Addendum A closeout).
- **Regression tests/evidence:** `tests/test_topology_resolution.py` (sparse IDs, restricted/missing/malformed CPU/mem/online info, explicit selection failures, `--no-pin` documented uncertainty), `tests/test_addendum_a.py` affinity/CPU-mask/probe/inject tests, placement/validity helper tests.
- **Result:** implemented and tested on host fixtures/fake-local environment. **Physical placement/locality not proven on this host.**

### Section 2 (P0) — Effective-backlog accounting
- **Original defect:** consumer dequeue dropped `published_backlog` before completion, inflating apparent headroom.
- **Correction:** three-part accounting per node: `effective_backlog = published_backlog + consumer_inflight_backlog + outstanding_reservation_backlog`. Lifecycle: admit(reserve outstanding) → FAA reserve → read outstanding → publish (outstanding→published) → dequeue (published→consumer_inflight) → completion/release (consumer_inflight removed). Headroom increases only after buffer release. Peer headroom published after relevant transitions; admission authoritative; one-outstanding-per-node invariant enforced; overflow-safe summation.
- **Regression tests:** `tests/test_corrections_s2_s4.py` (dequeue-before-completion does not reduce effective backlog; headroom after release; max effective bounded), debug accounting helpers; stress cases in `test_dist_ingest.py`.
- **Result:** corrected and regression-tested.

### Section 3 (P0) — Partial-read and EOF handling
- **Original defect:** single `pread`/limited retry treated short reads as final/complete in ways that could gap coverage.
- **Correction:** robust positioned-read loop handling `EINTR`, positive partial reads, genuine zero-byte EOF, permanent I/O errors, offset/length/`SSIZE_MAX`/`off_t` conversion guards, and overflow checks. File treated as immutable for campaign trials with metadata captured to detect obvious changes; truncation/change marks run incomplete/invalid rather than silently accepting gaps. Requested/assigned/read/published byte accounting kept distinct; exact non-overlapping coverage verified over expected file range.
- **Regression tests:** `tests/test_corrections_s3.py` (repeated EINTR/partial fills, premature EOF, truncation detection, final partial reservation, multi-ingestor coverage invariants) with engine-local seams/helpers.
- **Result:** corrected and regression-tested (seam-assisted where syscall fault injection required).

### Section 4 (P0) — Allocation ownership, alignment, and deallocation
- **Original defect:** allocator mismatch (`mmap`/`posix_memalign` fallback with `munmap`/`free` confusion risk), 2 MiB virtual alignment not guaranteed, hugepage reporting conflated.
- **Correction:** explicit allocation ownership (original mapping base/len recorded; matching `munmap` deallocation), 2 MiB-aligned usable buffers/mappings for requested alignment, overflow-checked allocation sizing, single deallocation per allocation across success/failure/shutdown paths. Hugepage reporting separated: requested, mapping obtained, ordinary fallback, observed backing where available/unknown.
- **Regression tests:** alignment/ownership/lifecycle tests (`test_dist_ingest.py`, `test_corrections_s2_s4.py`, `test_addendum_a.py` hugepage-accounting relationships; alignment helper).
- **Result:** corrected and regression-tested. Hugepage-success accounting not proven on this host.

### Section 5 (P0) — Meaningful and comparable consumer workloads / benchmark separation
- **Original defect:** synthetic consumers did not touch memory; control vs dist candidates were not comparable (different execution/measurement models).
- **Correction:** 
  - **Common-engine architectural comparison (same engine/consumers/work units/measurement):** added in-engine **`centralized_ingest`** (policy 4) baseline — single ingestor reserves/reads and round-robin dispatches to all node queues — sharing the same experimental engine, per-node consumers/queues, allocation/read/publication machinery, work units, and `di_run` measurement boundaries with `fixed_faa`, `local_adaptive`, `relative_adaptive`.
  - **Deterministic memory-touching consumer kernel:** default full byte-scan (volatile-sunk accumulation, not optimized away) identical across common-engine candidates; configurable rate-limited/stall behavior retained for backpressure tests; kernel/params reported in provenance/comparability metadata.
  - **Timing/measurement:** engine wall, ingest/read/publish/claim/consume wait components, per-ingestor/per-consumer CPU (direct thread CPU deltas) exposed; identical boundaries across common-engine candidates.
  - **Production forkrun reference:** retained as **separate reference only** (`production_ref`); explicitly not apples-to-apples with dist-engine candidates and not used for direct speedup claims against them.
- **Regression tests/evidence:** `test_dist_ingest.py` centralized correctness/CLI cases and randomized stress including policy 4; campaign smoke runs (`centralized_ingest` vs `fixed_faa`) correct and comparable.
- **Result:** implemented and locally validated. Not evidence of production end-to-end speedup.

### Section 6 (P1) — Placement measurement and reporting
- **Correction:** per-node reporting includes requested physical node, affinity role results (requested/set/query/matched/error, strict failures, effective-verified summary), memory-policy requested/success/failure/error (and aliases), placement sampling totals and breakdown (local-on-target/remote-other/unknown, sampled vs total addressable, per-allocation sample limit/spacing, sampling complete/partial/unavailable/not-performed), hugepage requested/obtained/fallback/observed, and explicit semantics. **Separate validity classifications:** `functional_correctness`, `performance_measurement`, `numa_placement` (tri-state/explicit) alongside detailed compat fields; `correct` retained as functional correctness (not a collapse of all dimensions). Unknown/incomplete placement does not become verified.
- **Result:** strengthened and reported; observation-based (not physical proof).

### Section 7 (P1) — Campaign randomization and execution fairness
- **Correction:** `run_dist_campaign.sh` shuffles candidate order within each (scenario,trial) comparison block using a recorded deterministic seed; optional reproducible scenario-block shuffle (`--shuffle-scenarios`); actual execution order and plan recorded (`campaign-manifest.json` schema v2, `execution-order.jsonl`, `execution-plan.json`); cache/warm-up assumption explicitly recorded (`--cache-policy`, default best-effort/uncontrolled with limitation stated). Re-running into existing case/trial evidence does not overwrite `manifest.json`. Configurations/corpora identical within comparison blocks.
- **Result:** implemented; reproducibility/smoke verified.

### Section 8 (P1) — Synthetic telemetry separation
- **Correction:** `DIST_RESULT` is authoritative for dist-engine measurements. `run_dist.py` no longer emits fabricated `STAGE0_DIAG` time-series snapshots; emits distinct `STAGE0_DIST_SUMMARY` label. `stage0/run_case.py` treats dist-engine candidates complete via their own result payload/functional validation (not fabricated Stage 0 diagnostic samples), preserving original semantics for production Stage 0 paths. Per-ingestor CPU measured directly per thread; aggregate ingest CPU is the sum of distinct ingestor-thread CPU deltas (centralized mode records one ingestor, no duplication into other nodes).
- **Result:** implemented.

### Section 9 (P1) — Arithmetic, admission, and configuration validation
- **Correction:** overflow guards for policy claim multiplication and defensive cursor-advance check; config normalization/validation (quantum/backlog defaults, `max_reservation` clamped to `max_backlog`, invalid base cases rejected); admission preserves `want <= headroom` and max-backlog invariant; quantum-multiple sizing enforced consistently (alignment intent honored). Relative policy continues to use sum of peer headrooms (128-bit intermediates) with configurable rounding. Policy arithmetic tests (including single-node/zero-peer/relative/caps) retained/extended.
- **Result:** audited and hardened (targeted); extreme `SSIZE_MAX`/`off_t` paths not exhaustively exercised through every boundary as a standalone ABI case beyond guards and existing tests.

### Section 10 (P1) — Failure, shutdown, and ownership paths
- **Correction/audit:** reservation rollback and buffer ownership enforced on allocation/read/publish failures and stop paths; queue-push failure frees chunk and rolls back outstanding; di_create partial-init/create-fail cleanup; thread create/join/stop wakeups; di_destroy drains queued chunks/frees recs after joined run. Result not marked correct on early stop/unresolved/inconsistent totals. Fault-injection seams/tests cover push failure, partial create, read/EOF/truncation/error paths, shutdown with queued/in-flight work.
- **Result:** audited with targeted fault-injection coverage; thread-creation failure not directly injected.

### Section 11 — Validation
- **Dist-ingest suite (normal):** **86/86 OK** (`python3 -m unittest discover -s stage0/dist_ingest/tests`).
- **Stage 0 regression:** **81/81 OK** (`python3 -m unittest stage0.tests.test_stage0`).
- **Targeted existing:** **7/7 OK** (`python3 -m unittest python.tests.test_numa_drain_guard`).
- **ASan + UBSan runtime (actual instrumented runs, dist-ingest suite):** **86/86 OK**. Build: `gcc -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined ...` (gcc 16.2.1). Run: `LD_PRELOAD=/lib64/libasan.so.8:/lib64/libubsan.so.1 ASAN_OPTIONS=detect_leaks=0:halt_on_error=1:allocator_may_return_null=1 UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1` → OK, exit 0. **Note:** `detect_leaks=0` (not a leak-sanitizer pass).
- **TSan runtime (actual instrumented run, dist-ingest suite):** **86/86 OK**. Build: `gcc -O1 -g -fno-omit-frame-pointer -fsanitize=thread ...`. Run: `LD_PRELOAD=/lib64/libtsan.so.2 TSAN_OPTIONS=halt_on_error=1:history_size=7` → OK, exit 0.
- **Concurrency/stress:** randomized engine stress (sizes/nodes/quanta/backlogs/policies including centralized, consumer modes), backpressure/stall-recovery, exact coverage and backlog-bound checks in covered cases; randomized seeds recorded in tests where applicable.
- **Campaign smoke (comparable set):** quick randomized campaigns completed successfully (e.g. `centralized_ingest` vs `fixed_faa`, seed recorded, all trials correct, report generated).
- **Fake-NUMA limitations:** fake/local NUMA used for exercising behavior/topology handling; **not** evidence of physical CPU/memory locality, remote-memory penalties, multi-socket scaling, or real hugepage distribution.

### Section 12 — Physical-NUMA campaign readiness
- **Updated:** `RENTAL_RECIPE.md` (comparable dist-engine set, strict preflight/placement-affinity verification, randomization/seed/cache/validity semantics, artifact/interpretation guidance), `PIPE_INGESTION.md` retained (pipe excluded from dist bake-off), `CLOSEOUT.md` (this report), campaign/report comparability labeling and provenance.
- **Campaign capability:** `run_dist_campaign.sh` runs comparable dist-engine candidates with recorded seed/order/cache policy, manifests/reports, and raw artifacts; supports `production_ref` only as separate reference.
- **Hardware rental:** **not performed**.

## 3. NUMA topology and placement

- **Discovery/mapping:** online/allowed CPU/mem sets and per-node CPU/memory facts resolved with uncertainty handling; logical→physical mapping explicit; duplicate/sparse/invalid/insufficient cases rejected or reported per mode; `--no-pin` documents unverified affinity facts without claiming verified topology.
- **Affinity:** per-role (ingestor/consumer) pthread affinity set/query/verify with direct error codes; dynamic/probed CPU-mask sizing; strict-affinity semantics.
- **Memory policy:** `mbind(MPOL_PREFERRED)` requested per configured physical node (before first touch where applicable), syscall outcome recorded separately from observed placement; strict-mbind enforces policy-application success (not physical guarantee).
- **Placement sampling:** independent `move_pages`-based sampling with per-allocation limit/spacing/complete-partial reporting and tri-state observation validity (`true`/`false`/`null`); unknown/permission-denied not counted as local/remote.
- **Hugepages:** requested/obtained/fallback/observed distinguished; optional; success not proven on this host.

## 4. Backlog and reservation correctness

- **Effective backlog:** `published_backlog + consumer_inflight_backlog + outstanding_reservation_backlog` (overflow-safe), updated at each lifecycle transition, never admitted above `max_backlog` by policy/admission; peer headroom advisory.
- **Reservation lifecycle:** admit → FAA reserve → read (outstanding) → publish (outstanding→published) → consume dequeue (published→inflight) → complete/release (inflight removed); one outstanding per node. Failures/stop produce rollback or explicit invalid/incomplete outcomes.
- **Read/EOF:** robust `pread` handling, distinct requested/assigned/read/published accounting, exact coverage verification, input-mutation detection.
- **Ownership/deallocation:** explicit mapping ownership with matching `munmap`; single final disposition per reservation/allocation in covered paths.

## 5. Comparative campaign

- **Common-engine set (apples-to-apples):** `centralized_ingest`, `fixed_faa`, `local_adaptive`, `relative_adaptive` — same `dist_ingest` engine, simulated per-node consumers, byte-range chunk work units, deterministic memory-touch consumer kernel (default), and identical measurement boundaries.
- **Production reference:** `production_ref` (existing forkrun) reported separately, different model, no direct speedup ratio claimed against dist-engine candidates.
- **Randomization/provenance:** recorded seed, per-block candidate order, optional scenario shuffle, execution plan/log, cache-policy assumption, source SHA/spec/provenance fields.
- **Validity:** functional, performance-measurement, and NUMA-placement tracked separately; incomplete/invalid trials identified.

## 6. Known limitations / caveats

- No physical multi-node NUMA validation in this environment; fake/local NUMA results are **not** evidence of physical locality/scaling/remote penalties.
- `mbind(MPOL_PREFERRED)` success and placement sampling observations are **not** proof of physical placement; unknown observations remain unknown.
- Hugepage-success accounting not proven on this host.
- Extreme `SSIZE_MAX`/`off_t` boundary cases not exhaustively exercised through every internal path; guards present.
- ASan validation used `detect_leaks=0` (no leak-sanitizer claim).
- Pipe ingestion excluded from dist-candidate bake-off.
- Consumer workload is a representative deterministic memory-touch kernel in the experimental engine, not the production scanner/worker pipeline; do not claim production end-to-end speedup from synthetic/common-engine comparisons.

## 7. Readiness assessment

**CONDITIONALLY READY (for physical-NUMA characterization of the experimental ingestion architecture)**

- **Rationale:** topology/affinity/placement wiring and semantics corrected and reported with explicit uncertainty/validity separation; effective-backlog/read/allocation/shutdown correctness addressed with regression and sanitizer runtime coverage (ASan+UBSan+TSan, dist suite); a comparable common-engine benchmark (centralized baseline vs distributed policies) is established with deterministic consumer kernel, separated telemetry/provenance, and reproducible randomized campaign mechanics.
- **Not sufficient to claim:** production adoption readiness, production end-to-end speedup, or physical-NUMA locality/scaling conclusions.
- **Prerequisites for decision-grade physical results:** clean measured commit on real (non-fake) multi-node hardware, >=3 trials, verified strict affinity/memory-policy/placement evidence per preflight, recorded topology/kernel/governor/cache assumptions, and interpretation within the documented validity/comparability limits.

**Final instruction honored:** priority given to real topology/placement, correct backlog/read/allocation behavior, meaningful comparable workloads, campaign validity/reproducibility, and runtime validation before declaring physical-rental readiness.
