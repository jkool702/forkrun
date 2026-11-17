# WO-NUMA-DISTRIBUTED-INGEST-PROTOTYPE-SUITE-1 — Closeout Report

## Repository state

- **Starting branch:** `NEW/REFACTOR5.1` (work order noted 5.0; 5.1 confirmed and used)
- **Starting HEAD:** `74fb41988fdd51665a21394b3613cc495d65a90b` ("stage0: reject invalid timestamps without bridging; scope CPU as global")
- **Final HEAD:** see commit(s) created by this work order (recorded at push time).
- **Working-tree status at closeout:** intended to be clean after commit of prototype suite artifacts (excluding gitignored run outputs/corpora/built `.so`).
- **Files added/changed (prototype scope, isolated):**
  - `stage0/NUMA_DISTRIBUTED_INGEST_PHASE0.md` — Phase 0 architecture investigation + plan
  - `stage0/dist_ingest/dist_ingest.h`, `dist_ingest.c`, `Makefile` — common experimental engine + policies (builds `stage0/libdist_ingest.so`, gitignored)
  - `stage0/dist_ingest/run_dist.py` — ctypes runner/metrics emitter
  - `stage0/dist_ingest/run_dist_campaign.sh` — one-command comparative campaign driver
  - `stage0/dist_ingest/report_dist.py` — comparative report generator
  - `stage0/dist_ingest/tests/test_dist_ingest.py` — correctness/policy/stress/CLI tests
  - `stage0/dist_ingest/PIPE_INGESTION.md`, `RENTAL_RECIPE.md`, `CLOSEOUT.md`
  - `stage0/run_case.py` — extended to run dist candidates when `spec.ingest_candidate` is set (existing behavior preserved for non-dist specs)
  - `.gitignore` — ignore `stage0/dist_ingest/runs/` and `stage0/libdist_ingest.so`
- **Frozen files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched).

## Architecture

- **Common experimental engine (`stage0/dist_ingest/dist_ingest.{h,c}`):** isolated C library (pthreads, `pread`, atomics) implementing, for regular files: a global 64-bit FAA byte cursor (`next_offset`, `__atomic_fetch_add`), **one exclusive ingestor thread per configured logical node**, per-node consumers, and per-node chunk queues.
- **Reservation/publication flow:** per-node admission check (authoritative local) on `effective_backlog = published_backlog + outstanding_bytes` against `max_backlog` with **one outstanding reservation per node** enforced; policy computes `want` (quantum-multiple bytes) → outstanding accounted → FAA reserves `[start,start+want)` → `pread` into a locally allocated/aligned buffer (mmap, best-effort `mbind(MPOL_PREFERRED)` when phys node known, best-effort hugepage map when requested) → short read adjusts outstanding → reservation recorded → chunk published (outstanding→published backlog) → consumer drains and releases. EOF/empty reads handled; stop/error paths roll back outstanding and wake peers.
- **Backlog/outstanding accounting:** `published_backlog` updated under per-node mutex on publish/consume; `outstanding` tracked across admit/read/publish/adjust; `peer_headroom` published as an advisory atomic (`max_backlog - effective`) for relative policy observation. `effective_backlog` never admitted above `max_backlog`; metrics track current/max published/effective and waits/zero-claims.
- **Claim policies (single engine, policy-specific decision only):**
  - **Fixed FAA:** claim 1 base quantum when headroom >= quantum, else 0.
  - **Local-headroom adaptive:** claim `floor(M_local/quantum)` quanta, capped by configured/local capacity.
  - **Relative-headroom adaptive:** `R_i` via integer arithmetic over `M_i` and `S_i=sum_{j!=i} M_j` (`K*M_i/S_i` with configurable floor/nearest/ceil rounding), capped; `S_i==0` falls back to local capacity, `K==0` (single node) behaves like local, `M_i==0` yields 0; 128-bit intermediates avoid overflow. Peer headrooms read as advisory atomics; local admission remains authoritative.
- **Memory/placement:** 2 MiB-aligned reservation quantum (configurable) and 2 MiB-aligned buffer allocations/mappings; best-effort `MAP_HUGETLB` and `mbind`; best-effort placement sampling via `move_pages` (sampled pages classified local/remote/unknown). Hugepages not required for correctness.
- **Isolation:** no changes to frozen engine/shim ABI or production ingestion; experimental path invoked only via `run_dist.py`/dist specs. Control candidate in campaign can still run the existing forkrun path through `stage0/run_case.py`.
- **Pipe ingestion:** not applied to FAA file-offset model; file-first. See `PIPE_INGESTION.md` (out of initial bake-off).

## Policy details

- **Formulas:** `M_i = max_backlog - effective_i`. Fixed: 1 quantum if `M_i>=q`. Local: `min(floor(M_i/q), capq)` quanta. Relative: `q_i = round_mode(K*M_i/S_i)` quanta for `K=n-1>0,S_i>0`, else local fallback; `q_i=0` if below `rel_min_claim` when configured; clamped by `capq`, `M_i`, and `max_reservation`.
- **Rounding/thresholds:** `relative_rounding` 0=floor,1=nearest,2=ceil; `rel_min_claim`, `rel_max_claim_quanta`, `local_max_claim_quanta`, `max_reservation`, `base_quantum` configurable.
- **Safety:** admission rejects if `outstanding>0` (one-in-flight invariant) or `want > max_backlog-effective`; claims reduced to fit headroom/caps; FAA past EOF undoes outstanding; short reads adjust outstanding to actual bytes.

## Validation

- **Dist unit/correctness/stress tests:** `stage0/dist_ingest/tests/test_dist_ingest.py` — **15 tests passed** locally (policy arithmetic incl. single-node/zero-peer/relative cases; correctness for empty, small, boundary sizes ±1 around quantum/4K/1M/2M, single-node, 4-node racing, slow-consumer backpressure with `max_effective_backlog <= max_backlog`, stall+recovery, randomized stress over sizes/nodes/quanta/backlogs/policies, CLI smoke). Build: `cd stage0/dist_ingest && make`.
- **Sanitizers/tooling:** ASan+UBSan build of `libdist_ingest.so` compiles successfully (`gcc -O1 -g -fsanitize=address,undefined ...`); runtime preload in this environment was not fully exercised beyond build/load attempt (documented limitation). No TSAN run recorded.
- **Stage 0 harness regression:** `python3 -m unittest stage0.tests.test_stage0` — **81 tests passed** (after `run_case.py` extension preserving existing behavior).
- **Targeted existing tests:** `python3 -m unittest python.tests.test_numa_drain_guard` — **7 tests passed**.
- **Local comparative campaign (quick):** `bash stage0/dist_ingest/run_dist_campaign.sh --quick --out stage0/dist_ingest/runs/quick-smoke --campaign-id quick-smoke` — **16/16 trials ok** (4 scenarios × 4 candidates × 1), report generated, all dist trials correct (no overlap/loss/dup, exact totals). Artifacts removed after inspection; runs are gitignored.
- **Correctness invariants demonstrated (local/fake NUMA):** no overlapping reservations, no missing/duplicate bytes for covered cases, EOF/partial-final/short-boundary handling, single outstanding per node, effective backlog bounded by admission limit, concurrent multi-node reservations, consumer stalls/recovery, no deadlocks observed in tested runs.
- **Limitations:** fake/local NUMA only (no physical multi-socket validation or real locality proof); placement/hugepage backing is best-effort and host-dependent; control vs dist execution models differ (comparisons indicative); pipe ingestion deferred; dist queue is an experimental measurement queue (not the frozen engine’s chunk/batch ABI); no claim that `numa=fake` predicts physical scaling.

## Campaign readiness

- **One-command driver:** `bash stage0/dist_ingest/run_dist_campaign.sh [--out DIR] [--campaign-id ID] [--trials N] [--quick] [--scenarios LIST] [--candidates LIST]`
  - Candidates: `control,fixed_faa,local_adaptive,relative_adaptive` (default all).
  - Scenarios (non-quick default): `equal, slow_one, fast_one, asymmetric, stall_recover, nodes2, nodes8, large_seq, small, tiny, boundary, backpressure` (file-first; covers equal/slow/fast/asymmetric consumers, temporary stall+recovery, varying node counts, large sequential, small/boundary, backpressure). Quick mode runs a subset on smaller corpora.
  - Trials: configurable (`--trials`, default 3). Deterministic corpora generated per campaign dir; immutable output; raw manifests/logs/JSON retained; `report.md` generated.
- **Metrics collected:** per-trial wall/throughput/bytes, correctness (overlap/loss/dup, totals), reservations/counts and size histogram, per-node bytes published/consumed, current/max published & effective backlog, zero-claim/wait times, peer-observation counts/time, ingest/consumer CPU (thread CPU ns), placement page classification and hugepage-kb (best-effort), provenance (SHA, config, env manifests). Unavailable measurements not fabricated.
- **Rental recipe:** `stage0/dist_ingest/RENTAL_RECIPE.md` (preflight, topology/affinity/policy, invocation, runtime/disk estimates, artifacts, recovery, interpretation).
- **Expected physical-NUMA rental duration (estimate):** quick calibration ~5–10 min; full default campaign (3 trials, default scenarios/candidates on 256 MiB file corpus) **~30–90 minutes** depending on hardware, plus setup/collection margin. Budget **2 hours** for a safe single-session run including preflight and artifact transfer.

## Honest assessment

**CONDITIONALLY READY**

**Why:** the prototype suite is implemented in isolation with a common engine and three pluggable FAA policies, locally correct across targeted/stress cases, integrated into a one-command comparative campaign with reporting/provenance and a physical-NUMA rental recipe. A quick local campaign completed successfully (all trials correct).

**Remaining prerequisites / caveats before treating a physical-NUMA rental as decision-grade:**
1. **Physical multi-node validation not yet performed** (no real NUMA hardware in this environment). Run the prepared campaign on actual multi-socket NUMA with recorded topology/affinity/mempolicy and >=3 trials.
2. **Control comparability:** dist candidates and the existing control run through different execution models/metrics paths; refine equivalence (same downstream work/measurement basis) if the initial physical results are ambiguous.
3. **Sanitizer depth:** ASan/UBSan build verified to compile; full sanitizer runtime passes (ASan/TSAN where appropriate) not completed.
4. **Scenario breadth/perf scale:** default corpora sized for practicality; for decisive throughput scaling (>2s steady-state per case on fast rental hosts) increase corpus sizes and confirm runtime budget.
5. **Pipe ingestion:** excluded from bake-off; implement per `PIPE_INGESTION.md` if pipe comparison is required.
6. **Topology/affinity integration:** dist runner currently uses best-effort placement hints but does not yet accept/force explicit per-node CPU/memory binding arguments from specs as comprehensively as the production path; add if physical runs require strict pinning control.

A single physical-NUMA rental session can produce a **meaningful initial architectural comparison** using this suite, provided preflight/topology/affinity are recorded and results are interpreted with the above caveats.
