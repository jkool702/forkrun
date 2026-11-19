# WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-AND-EXPERIMENT-COMPLETION-1 — Checkpoint 1 (C1)

**Work order:** `WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-AND-EXPERIMENT-COMPLETION-1`, checkpoint 1: physical topology discovery + per-scenario mapping matrix.  
**Supplements/preserves:** all prior preserved checkpoints/history on `NEW/REFACTOR5.1` through `43a127244e53d9c6f6e31380087bd90a091605dd` (`WO-NUMA-DIST-INGEST-CAMPAIGN-PREFLIGHT-FINAL-CLEANUP-4`). No architecture expansion; no physical rental; no production adoption.

**Status:** C1 implemented and validated on this local/fake-NUMA host. **No physical-NUMA hardware rented. No production files modified.**

## C1.1 Repository state

- **Branch:** `NEW/REFACTOR5.1`
- **Starting HEAD (before C1 edits):** `43a127244e53d9c6f6e31380087bd90a091605dd` (verified)
- **Frozen production files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched)
- **C files changed:** **none** (no sanitizer rerun required for C1)

## C1.2 Topology discovery (reusable)

- Added `stage0/dist_ingest/topology.py`: sysfs/proc-root-configurable topology inventory (online/sparse node IDs, allowed mem/CPU/cpuset, per-node CPU/mem info, node→socket/package, full NUMA distance matrix and nearest intra/cross-socket distances, CPU/core/thread counts). Unknown/unavailable facts are reported explicitly (never guessed).
- Integrated with `run_dist.resolve_topology()` without duplicating CPU/memory usability validation: `resolve_topology()` remains the authoritative usability/validation path and consumes inventory facts via patchable helpers; configurable `sysfs_root`/`proc_root` supported for testing and deterministic fixtures.

## C1.3 Mapping profiles and per-scenario matrix

- Mapping profiles: `cross_socket_spread`, `intra_socket` (socket-qualified concrete variants), `all_nodes`, `explicit` (and legacy `auto`). Topology-aware (not numeric-ID-based). Unsupported mappings are returned/reported explicitly with reasons and never substituted.
- `run_dist.resolve_mapping_plan()` resolves concrete mapping variants and validates each concrete mapping through the same explicit-mapping `resolve_topology()` authority trials use.
- Campaign preflight/planning (`stage0/dist_ingest/run_dist_campaign.sh`): `--mapping-profiles` (including `matrix`/`all`), per-scenario concrete mapping expansion (mixed logical node counts supported in profile/matrix mode), `--plan-only/--dry-run`, complete-plan preflight validates every concrete mapping before timed trials, and case identity includes mapping identity.
- Backward-compatible explicit global override preserved: `--phys-nodes` validates raw list shape in campaign preflight, requires selected scenarios to share one logical node count, validates via `resolve_topology()` with trial-equivalent semantics, and records `physical_node_mapping.explicit_mapping_validated`, `resolved_logical_to_physical`, `explicit_physical_node_ids`, `explicit_selected_node_count` with host-usable fields distinct.

## C1.4 Mapping identity and provenance

- `run_dist.py` emits `mapping_provenance` in `DIST_RESULT` (mapping profile/variant, logical→physical, node→socket, per-node CPU/allowed/pinning lists, pairwise NUMA distances, spans-sockets, affinity-verified/unknown facts as available).
- `stage0/run_case.py` forwards dist-ingest mapping/root fields (`phys_nodes`, `mapping_profile`, `mapping_variant`, `sysfs_root`, `proc_root`) into specs/runs.
- `run_dist_campaign.sh` propagates the same resolved mapping (`phys_nodes`) to every trial of a case and records mapping plan/provenance in `prevalidation.json`, `execution-plan.json`, and campaign manifest.
- `stage0/dist_ingest/report_dist.py` is mapping-aware (grouping/reporting do not mix mappings; unsupported mappings reported explicitly) while remaining legacy-compatible for prior trial records.

## C1.5 Tests (C1)

- Added `stage0/dist_ingest/tests/test_mapping_matrix.py` (deterministic synthetic topologies): NPS1/2/4 inventory, sparse IDs, no-mem/empty-cpulist nodes, restricted cpusets/mems, missing/invalid distances, ambiguous node→socket, cross_socket_spread/intra_socket/all_nodes selection, NPS4 4-node cross-socket spans sockets (not all socket 0), NPS1 rejects unsupported 4/8-node mappings, and concrete mapping plan validation via `resolve_topology()`.
- Existing `stage0/dist_ingest/tests/test_topology_resolution.py` and `stage0/dist_ingest/tests/test_benchmark_semantics.py` contracts preserved (including explicit-mapping/whitespace compatibility).

## C1.6 Validation (checkpoint 1)

- Focused: `test_mapping_matrix` (13), `test_topology_resolution` (23), and previously-failing explicit-mapping semantics tests (`test_explicit_mapping_valid_sparse_physical_ids_succeeds`, `test_explicit_phys_nodes_whitespace_around_valid_ids_allowed`) — all OK.
- Full dist-ingest suite: `python3 -m unittest discover -s stage0/dist_ingest/tests -v` → **172/172 OK** (local/fake-NUMA host). These validate driver/topology/mapping/planning/provenance behavior only; they do **not** establish physical NUMA locality or scaling.
- C1 smoke: `run_dist_campaign.sh --plan-only` (auto and `--mapping-profiles matrix`) produced resolved mapping plans and reported unsupported mappings explicitly without substitution.

## C1.7 Remaining work (WO-1, not yet done)

- Checkpoint 2: placement-sampling modes/isolation and measurement integrity.
- Checkpoint 3: parameter sweeps, workload expansion, duration qualification, cache policies.
- Checkpoint 4: environment/telemetry/reporting improvements, binary provenance, calibration utility.
- Checkpoint 5: EPYC stage/orchestration integration and final rehearsal.
- Full WO-1 required validations/sanitizers/stress and creation/update of `RENTAL_READINESS.md` (and final `CLOSEOUT.md`/`RENTAL_RECIPE.md`/EPYC docs) remain pending subsequent checkpoints. **No physical rental. No production adoption.**

---

# WO-NUMA-DIST-INGEST-CAMPAIGN-PREFLIGHT-FINAL-CLEANUP-4 — Closeout

**Work order:** `WO-NUMA-DIST-INGEST-CAMPAIGN-PREFLIGHT-FINAL-CLEANUP-4` (final CLI-input and provenance consistency cleanup).  
**Supplements/preserves:** `WO-NUMA-DIST-INGEST-CAMPAIGN-PREFLIGHT-CLOSEOUT-3` (`d894151f`) and all prior preserved checkpoints/history. No architecture or prototype expansion.

**Status:** cleanup implemented and validated on this host. **No physical-NUMA hardware rented. No production adoption started.**

## 1. Repository state

- **Branch:** `NEW/REFACTOR5.1`
- **Starting/expected HEAD (before this correction):** `d894151fc479e5a86c7543f119a41e924c30af16` (verified)
- **Pre-edit worktree:** clean (verified)
- **Final HEAD (this checkpoint):** see commit recorded for `dist-ingest: apply WO-NUMA-DIST-INGEST-CAMPAIGN-PREFLIGHT-FINAL-CLEANUP-4`
- **Working-tree status at closeout:** clean after commit/push (intended)
- **Frozen production files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched; verified)
- **C files changed:** **none**. No C changes; sanitizer rerun not required.

## 2. P2 — Malformed explicit physical-node lists rejected

- **Correction (`stage0/dist_ingest/run_dist_campaign.sh`):** raw `--phys-nodes` string is validated in campaign preflight **before invoking `run_dist.resolve_topology()`**. Rejected (leading/trailing/consecutive commas, empty elements, non-integer elements): e.g. `0,,1`, `0,1,`, `,0,1`, empty/space-only elements, `0,a`. Ordinary whitespace around valid integer IDs remains allowed.
- `resolve_topology()` remains the authority for actual topology and usability validation (duplicate/online/mems/memory/CPU/allowed-CPU/establishment checks unchanged in its role).
- Malformed input rejected before build/trial setup; no timed-trial manifests produced.

## 3. P2 — Quick/profile behavior and effective-profile provenance

- **Preferred consistent behavior implemented:** `--profile nodes2 --quick` and `--profile nodes4 --quick` are **rejected** with an explicit explanation that those profiles describe the non-quick scenario set (use `--profile full --quick` or select quick-compatible scenarios explicitly).
- **`--profile full --quick` supported:** requested/effective profile metadata and `profile_quick` unambiguously describe the resulting quick scenario selection (`scenario_profile_requested=full`, `scenario_profile_effective=full_quick`, `profile_quick=true`, selected scenarios = quick set).
- All three profile names covered in quick-mode tests (`nodes2` rejected, `nodes4` rejected, `full` supported/unambiguous).

## 4. P2 — Duplicate scenario IDs and prevalidation/execution-plan consistency

- **Preferred behavior implemented:** explicit selections containing duplicate scenario IDs are **rejected** with a clear preflight diagnostic before timed trials.
- `prevalidation.json`, `campaign-manifest.json`, and the actual execution plan therefore agree on the selected scenario set (no duplicated selections silently represented as distinct scenarios; rejection prevents inconsistency).

## 5. Validation

- **C changes:** none. Sanitizer rerun not required.
- **Normal suites:**
  - `python3 -m unittest discover -s stage0/dist_ingest/tests -v` → **159/159 OK** (22.897s)
  - `python3 -m unittest stage0.tests.test_stage0` → **81/81 OK** (16.154s)
  - `python3 -m unittest python.tests.test_numa_drain_guard` → **7/7 OK**

Local/fake-NUMA tests validate driver and CLI-input/topology-handling/provenance behavior only; they do **not** establish physical NUMA locality or scaling.

## 6. Remaining limitations

- No physical multi-node NUMA validation; local/fake-NUMA results are not evidence of physical locality/scaling/remote-memory penalties.
- Complete successful-prevalidation listing of the full non-quick default set not end-to-end recordable on this 4-usable-node host because `nodes8` is correctly rejected before timed trials (full-set selection validated via CLI behavior).
- `mbind(MPOL_PREFERRED)` syscall success and placement sampling observations are not physical placement proof; `unknown` remains `unknown`.
- Hugepage-success accounting not proven on this host.
- No C changes; ASan/UBSan/TSan not rerun (no leak-sanitizer claim).
- Pipe ingestion excluded from dist-candidate bake-off.
- Synthetic consumer not equivalent to production worker pipeline.

## 7. Confirmation / stop condition

- Malformed explicit physical-node lists rejected before `resolve_topology()`/build/trials; quick/profile semantics and effective-profile provenance are unambiguous and consistent; duplicate scenario IDs rejected and prevalidation/provenance/execution-plan remain consistent.
- **No physical-NUMA hardware rented. No production code changed. No further architecture or prototype expansion.**
- **Stopped for review** at this checkpoint.
