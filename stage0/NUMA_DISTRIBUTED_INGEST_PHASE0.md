# WO-NUMA-DISTRIBUTED-INGEST-PROTOTYPE-SUITE-1 — Phase 0 Architecture & Plan

**Status:** investigation complete (local); implementation proceeds on `NEW/REFACTOR5.1`.
**Starting HEAD (verified):** `74fb41988fdd51665a21394b3613cc495d65a90b` (branch `NEW/REFACTOR5.1`, clean tree).
**Scope note:** this document answers Phase 0 items 1–10 and records the concrete implementation plan. Frozen files (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c`) are not modified.

## 1. Current ingestion architecture (actual)

### 1.1 Entry points and orchestration

- **Python NUMA executor (blocking):** `python/forkrun/run.py:_execute_numa_locked` (~11906). It builds/initializes the engine, creates an empty ingress memfd, forks the NUMA pipeline, forks workers per node after a publish/backlog gate, runs the reactor, collects, and joins helpers.
- **Pipeline fork:** `python/forkrun/run.py:_numa_fork_pipeline` (~11440). Forks, in order:
  - 1× `fallow-phys` child: `fr_py_fallow_phys(fallow_r, memfd)` → engine `ring_fallow_phys_main` (consumes `PhysPacket{off,len}` and punch-holes reclaimed ranges; `forkrun_ring.c` ~ring_fallow_phys_main, tail end of scanner/order/fallow region).
  - N× indexers (one per logical node): `fr_py_indexer_numa(memfd, node)` → `ring_indexer_numa_main` (self-pins to node physical CPUs).
  - N× scanners (one per logical node): `fr_py_numa_scanner(memfd, node, fd_spawn, num_nodes)` → `ring_numa_scanner_main` → `core_scanner_loop(..., is_numa=true)`. A spawn pipe is armed (W-PYSPAWNWIRE) so scanners can request workers as backlog appears; Python parks a spare write end.
  - 1× ingest child: `fr_py_numa_ingest(src_fd, memfd, num_nodes)` → `ring_numa_ingest_main` (owns the source; no pre-spill).
- **Shim wrappers:** `python/forkrun/_shim.c` `fr_py_init_numa` (~), `fr_py_numa_ingest` (3687), `fr_py_indexer_numa` (3708), `fr_py_numa_scanner` (3732), `fr_py_fallow_phys` (3759). All build argv and call existing `ring_*_main` entry points inside the same TU that `#include`s `forkrun_ring.c`.
- **Bindings:** `python/forkrun/_bindings.py` exposes the above `fr_py_*` symbols (ctypes). `fr_py_init_numa(lines, bytes, num_nodes, numa_map)` forwards `--numa-map=<phys ids>` to `ring_init_main`.
- **Topology/mapping:** `python/forkrun/_numa.py` resolves `nodes=` to `(numa_map_str, num_nodes, node_cpus)`; `wid_to_node`/`distribute_workers` give stable contiguous per-node worker blocks.

### 1.2 Shared state, queues, and publication (engine)

Defined in `forkrun_ring.c` (engine TU; read-only for this work):

- **`GlobalState g_state`** (single shared mapping): `ingest_publish_idx` / `ingest_eof_idx` (cache-line aligned), abort/reason, resume/checkpoint fields, `poisoned_count`, `limit_cutoff_major`, per-worker `worker_txn[MAX_TXN_WORKERS]`, and `meta_ring[META_RING_SIZE]` (`META_RING_SIZE=4096`). `ChunkMeta` holds `{raw_offset, raw_length, target_node, major_id, actual_end, cum_lines}` with readiness flags (`FLAG_META_READY`, `FLAG_CUM_READY`).
- **`SharedState state[num_nodes]`** (per logical node, mmap/calloc sized by `global_num_nodes`): per-node chunk/index progress and queues — `chunk_queue_head/tail` (published/claimed chunk majors ring), `chunk_ready_head`, `chunk_queue[META_RING_SIZE]`, indexer/scanner progress markers (`indexer_major`, `scan_claim_major`), batch rings (`read_idx/write_idx`, `offset_ring/end_ring/major_ring/minor_ring/lines_ring[RING_SIZE]`), `active_waiters/workers`, `indexer_waiters/meta_waiters`, `ingest_complete`, `scanner_finished`, `emergency_abort`, `escrow_pending`, steal thresholds, `chunk_buffer_limit`, counters, and `committed_data_frames`.
- **Signalling:** eventfds/arrays (data/ingest/indexer/meta/eof/chunk-done/ingest-eof as used by loops) wake waiters; `WAIT_FOR_META_READY` / cum-line waits coordinate publication.
- **Chunk publication (ingest):** `ring_numa_ingest_main` (~3196) chooses a target node, gates on per-node unclaimed chunk backlog (`chunk_queue_head - chunk_queue_tail < current_buffer_limit`) and on a meta-lifetime bound (frontier pinned within `META_RING_SIZE/2` of oldest unread/unfinished work via `indexer_major`/`scan_claim_major`), transfers bytes into the shared ingress memfd (method selected: copy_file_range/sendfile/read-write; MPOL_BIND applied when node changes and numa enabled), fills `ChunkMeta` for `current_major`, appends major to `chunk_queue`, advances `chunk_queue_head` and `g_state->ingest_publish_idx` (release), increments `stats_chunks_assigned`, and wakes indexer waiters. EOF publishes a zero-length sentinel chunk and sets `ingest_eof_idx`.
- **Indexing/scanning:** indexers consume published chunk majors and make chunks ready for scanners; scanners claim chunk slots (`chunk_queue_tail` fetch_add / claim flow), publish batch slots into per-node batch rings (`write_idx`, offset/end/major/minor/lines rings) and wake workers; workers claim batches (`read_idx` fetch_add in claim path) and ack/commit.

### 1.3 Where the key things happen today (answers)

1. **Input offsets allocated:** centralized in `ring_numa_ingest_main` — `current_offset` advanced by bytes moved per chunk (`current_offset += n`), `current_major` increments per published chunk; ingest decides the byte range and target node.
2. **How chunks are read:** ingest reads the source fd into the shared outfd/memfd using `copy_file_range`/`sendfile` or a bounce-buffer `read`+`write` loop (selected per run; NUMA+multi-node forces read/write path) at `chunk_size` granularity (adaptive: sized from file/node count, aligned to batch/byte-mode constraints; geometric accumulation ramp `accum_target`).
3. **How buffers allocated/populated:** a single shared ingress memfd (created by Python, passed as outfd) is the destination; ingest places pages local via `set_mempolicy(MPOL_BIND, nodemask, ...)` when switching target (syscall `__NR_set_mempolicy`, best-effort) and writes into it; bounce buffer `mmap`'d at `chunk_size` for read/write mode.
4. **How published to downstream consumers:** `ChunkMeta` in `g_state->meta_ring[major & mask]` + major enqueued on per-node `chunk_queue` with `chunk_queue_head` release-store; `ingest_publish_idx` release-store; indexer/scanner coordination via `chunk_ready_head`, `indexer_major`, `scan_claim_major`, meta/cum readiness flags and eventfds. Batch-level publication to workers is via per-node batch rings advanced by scanners.
5. **Backlog representation/measurement:** per-node chunk backlog is `chunk_queue_head - chunk_queue_tail` (published minus claimed chunks), gated against `current_buffer_limit` (dynamic, 4..128, IIR/steal-feedback tuned). Per-node batch backlog is `write_idx - read_idx`. `fr_py_backlog_node` / `fr_py_data_ready_node` expose non-destructive/destructive views for Python gates; `fr_py_diag_node` snapshots node state (used by drain audit and Stage 0 telemetry `STAGE0_DIAG/FINAL`).
6. **NUMA locality established:** `MPOL_BIND` in ingest on target-node switch (when enabled), per-node indexer/scanner pinning to physical CPUs, per-node rings/state, and distance-charged stealing in scanners when starved. Fake-NUMA (`@N`) maps logical nodes onto physicals cyclically.
7. **Synchronization for safe shutdown/EOF:** `ingest_eof_idx`/`ingest_complete`/`evfd_ingest_eof`, per-node `scanner_finished`, `chunk_queue` sentinel semantics, `emergency_abort`/`abort_reason`, meta-lifetime bound to prevent slot recycle races (F-NUMA1), scanner/indexer claim/readiness ordering, and Python-side helper death watches/join discipline.
8. **Reusable without modification:** topology resolution (`python/forkrun/_numa.py`), Stage 0 env/corpus/manifest/ablation/report machinery and telemetry formats (`STAGE0_DIAG/FINAL`), existing `fr_py_diag_node`/backlog/data-ready/readiness conventions, generic per-process/tree sampling in `stage0/run_case.py`, fd/scrub/pipe/reactor primitives and test harness patterns, and (conceptually) the downstream chunk/batch consumption model — provided the experimental path emits compatible evidence and does not require changing frozen ABI/engine.
9. **Experimental components needing new interfaces:** a userspace/isolated experimental ingest module exposing (a) a global byte-range reservation cursor, (b) per-node admission/backlog+outstanding accounting, (c) pluggable claim-size policy callbacks, (d) chunk read+local-destination allocation+publication into an experimental queue compatible with measurement, (e) peer-headroom publication/observation, (f) policy/parameter selection and metrics hooks callable from a campaign child process, and (g) a way to run candidates side-by-side without touching production `ring_numa_ingest_main`.
10. **Smallest practical isolation boundary:** a **self-contained experimental C library + thin Python ctypes wrapper** (new files under `stage0/dist_ingest/`, e.g. `dist_ingest.c`/`.h` built to `stage0/libdist_ingest.so`) implementing reservation, per-node ingest threads, local memfd/buffer placement, an experimental chunk queue, and metrics — driven by a dedicated Python runner path (separate from `fr_py_numa_ingest`) and selected via Stage 0 spec fields (e.g. `ingest_candidate`/policy params). This avoids modifying frozen engine/shim ABI, keeps production path byte-for-byte intact, and reuses Stage 0 campaign/reporting by extending spec/manifest/metrics schemas.

### 1.4 Existing FAA / contention points observed

- `atomic_fetch_add` / `__atomic_fetch_add` used broadly (claim tickets, queue heads/tails, counters). Scanner/worker batch claiming is FAA on per-node indices; ingest is currently **centralized** (one process chooses target and advances offset) rather than per-node contending on a global input cursor. Chunk queue publication is per-node ring head advance; global publish/eof indices are single-writer from ingest.

## 2. Critical design question — ingestors per node

- **Current architecture:** one NUMA ingest process total (`ring_numa_ingest_main`) distributes across all nodes; indexers/scanners are one per node. There is **no existing per-node exclusive ingestor thread pool**.
- **Decision for prototype:** implement **exactly one exclusive ingestor thread per configured logical NUMA node** in the experimental engine. Rationale: matches "per node may independently reserve", makes per-node effective-backlog authoritative without intra-node contention, and keeps outstanding-reservation accounting to **one in-flight reservation per node** (simplest correct invariant).
- **If this invariant is relaxed later:** admission MUST subtract `outstanding_reserved_bytes` (and/or count) per node from `max_backlog` before deciding; multiple threads per node would require per-node atomic outstanding accounting and a reservation ticket lifecycle to prevent double-admission against stale backlog. The prototype will enforce and assert the single-ingestor-per-node invariant; any future change must introduce explicit accounting before enabling >1 ingestor/node.

## 3. Concrete implementation plan

### Isolation & build
- New directory: `stage0/dist_ingest/` containing `dist_ingest.h`, `dist_ingest.c` (common engine + policies + metrics), `policies.h/.c` or inline single-source policy module (one authoritative claim-policy implementation per policy, dispatched by enum/id), built as `stage0/libdist_ingest.so` via a small Make rule/script (gcc, `-O2 -pthread -lnuma` as available, no dependency on frozen engine objects).
- Python harness: `stage0/dist_ingest/run_dist.py` (ctypes bindings, runs a candidate over a file, emits JSON metrics/stderr telemetry compatible with Stage 0 parsing) and/or integration hooks in `stage0/run_case.py` behind a new spec field (e.g. `ingest_candidate: control|fixed_faa|local_adaptive|relative_adaptive` plus policy params). **Production `python/forkrun/*` behavior unchanged**; experimental path is opt-in by spec.
- Downstream model: for a fair ingest comparison the experimental engine will (1) reserve/read into node-local buffers, (2) publish chunk descriptors to per-node queues consumable by lightweight experimental scanner/consumer threads (or a compatible drain) that record consumption/backlog timings, reusing Stage 0 queue-telemetry line shapes where practical. No frozen `forkrun_ring.c` data structures are modified.

### Phase 1 — common engine (single source of truth)
- Global atomic byte cursor `next_offset` (64-bit FAA / `__atomic_fetch_add`) over `[0, file_size)`.
- Per-node state: `effective_backlog`, `outstanding_bytes`, published/consumed counters, local destination ring/memfd, placement info, timings, error flags.
- Lifecycle (exactly one accounting effect per transition): admit (reserve outstanding) → FAA reserve `(start,len_req)` → pread → local store placed → publish → consume/release; on failure/EOF/short read roll back outstanding correctly.
- Admission: `effective_backlog = published_backlog + outstanding_bytes` must never exceed `max_backlog`; one outstanding reservation per node.
- Configurable: chunk/base quantum (default 2 MiB), max backlog, max reservation, node count/map/affinity.

### Phase 2 — policies (pluggable over common engine)
- **Control:** run existing centralized production path via current Stage 0 runner semantics (baseline) — no new engine behavior, used for comparison.
- **Fixed FAA:** claim `min(quantum, headroom, remaining)` when headroom >= quantum (or configured), 2 MiB aligned reservations where feasible, EOF partial allowed.
- **Local-headroom adaptive:** `M_local = max_backlog - effective_local_backlog`; claim `f(M_local)` quanta (configurable mapping, e.g. floor(M_local/base_quantum) capped), zero allowed.
- **Relative-headroom adaptive:** publish advisory per-node headroom atomics; compute `M_i`, `S_i=sum(M_j,j!=i)`, `K=others`; integer arithmetic with configurable rounding/thresholds: e.g. `target = clamp(round_k(M_i, avg_nonlocal_or_policy), 0, cap_quanta)` where `R_i ≈ M_i/avg(M_other)`; handle `S_i==0`, `K==0`, `M_i==0`, caps, overflow-safe 64-bit intermediates. One authoritative policy function per policy.

### Phase 3 — hugepage/alignment investigation
- Align reservation offsets to quantum; allocate local destination buffers/mappings with 2 MiB alignment where possible (`mmap`/`memfd` + `posix_memalign`/hugepage hints as feasible), record requested vs observed placement/backing (parse `/proc/self/numa_maps`, `mincore`/THP indicators where observable, move_pages/status sampling as in ablation shim patterns) without requiring hugepages for correctness.

### Phase 4 — pipe ingestion
- **File ingestion first.** Pipes: kernel read serialized by a single reader thread handing byte ranges/buffers to per-node publication paths preserving ordering where required; do not apply global FAA file-offset claiming to non-seekable streams. If safe adapter cannot be completed, keep pipes explicitly out of bake-off and document exact remaining work.

### Phase 5 — campaign & instrumentation
- Extend `stage0/run_case.py` spec handling to accept `ingest_candidate`/policy params and invoke the experimental runner for non-control candidates while preserving existing behavior for current specs.
- Emit/record: bytes/records, per-node throughput & CPU/time, reservation counts/rates & size distribution, wait times (capacity/input), published/outstanding/effective backlog series, max backlog, unable-to-claim/zero-claim, peer-observation cost, placement/local-vs-remote and hugepage backing where measurable, correctness counters (exact-once, no overlap), full provenance (SHA, params, kernel/topology/affinity/policy). Reuse `STAGE0_*` lines where compatible; never fabricate unavailable metrics (mark unavailable).
- Workload scenarios (10): equal/slow/fast/asymmetric consumers, temporary stalls+recovery, unequal ingest costs (where feasible), varying node counts, large sequential file, small/short-final/empty/boundary cases, backpressure/near-saturation — encoded as spec variants/parameters.

### Phase 6 — testing
- Unit tests: policy arithmetic (R_i, zero/overflow/rounding/caps, single-node), reservation accounting, queue invariants.
- Concurrency/stress (fake NUMA, pthreads): racing reservations no overlap/no loss/dup, short reads/EOF/partial final, outstanding vs published backlog observability (injected delays), stalls/recovery, shutdown/error paths, no deadlock/stranded reservations.
- Run existing relevant suites (`python -m unittest discover -s python/tests -p 'test_*.py'` subset/targeted + stage0 tests) to confirm no production regressions; record results.

### Phase 7 — bake-off readiness & closeout
- `stage0/run_dist_campaign.sh` (or extend `run_all_campaign.sh` with a mode/flag): one command running control + 3 policies across scenarios/trials, interleaved/randomized order, immutable output dir, raw artifacts retained, comparative report generated, invalid/incomplete/inconclusive clearly marked.
- `stage0/RENTAL_RECIPE_DISTRIBUTED_INGEST.md`: hardware/kernel/NUMA/affinity/mempolicy preflight, exact invocation, runtime/disk estimate, artifact collection, retry/interpretation.
- Closeout report in `stage0/DIST_INGEST_CLOSEOUT.md` with required sections and readiness classification.

## 4. Soundness / risks noted

- Experimental path must not depend on frozen engine internals or alter production semantics; correctness proven locally (fake NUMA) is necessary but not sufficient for physical-NUMA claims.
- `pread` concurrency on a shared fd is safe for positioned reads but source/consumer behavior under stalls must be validated; publication/consumption queues need careful memory ordering.
- Comparable end-to-end measurement requires the same downstream work model across candidates; any mismatch will be documented as a limitation.
- Pipe FAA-on-offset is unsafe; treated separately per Phase 4.

**Proceeding with implementation (Phases 1–7) under this isolation boundary.**
