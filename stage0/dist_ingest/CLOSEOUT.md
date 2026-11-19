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

## C1.8 Correction checkpoint — `WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-C1-CORRECTIONS-1` (pre-C2)

**Purpose:** narrow correction to C1 campaign plan-generation semantics and `cross_socket_spread` meaning before checkpoint 2. Preserves C1 topology inventory/mapping model/interfaces and prior commits; no architecture redesign, no physical rental, no production adoption.

- **Branch:** `NEW/REFACTOR5.1`
- **Starting HEAD (correction):** `f6906bff1acea559129521e5dae1ddcdfdd55626` (C1 committed)
- **Frozen production files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched)
- **C files changed:** **none**. No sanitizer rerun required for this correction.

### CLI → execution-plan propagation and candidate/plan validation (`stage0/dist_ingest/run_dist_campaign.sh`)

- The embedded plan-generation/preflight Python now receives the actual shell/CLI values **explicitly** as positional arguments for trials, candidate filter, seed, and scenario-order shuffling (`TRIALS`, `CAND_FILTER`, `SEED`, `SHUFFLE_SCENARIOS`) instead of reading ambient `DIST_*` environment values. `--plan-only` and a real campaign with identical arguments therefore generate/use the **same** selected plan.
- Candidate selection is validated before build and before timed-trial manifests: candidate list must be nonempty (including empty/malformed elements rejected), every requested candidate must be recognized (dist-engine candidates plus `centralized`/control/reference aliases accepted by the campaign), and duplicate candidate IDs are rejected. Invalid selection fails before timed-trial manifests. (`--candidates` now accepts an explicit empty argument value so empty selection is rejected by campaign validation rather than mis-parsed by shell option handling.)
- Requested/executed plan parameters are recorded in provenance/plan artifacts: `prevalidation.json` and `execution-plan.json` include `trials`, `candidates`, `seed`, `shuffle_scenarios`/randomization fields consistent with the validated plan; `execution-plan.json` remains the authoritative block plan used by execution.

### Genuine `cross_socket_spread` semantics (`stage0/dist_ingest/topology.py`)

- `cross_socket_spread` is supported only when socket membership is known and unambiguous for the selected usable nodes, at least two distinct sockets exist among the available usable nodes, the logical node count is >= 2, and the selected mapping actually contains nodes from at least two distinct sockets. A logical node count of 1 cannot qualify.
- Unsupported cases are reported with a clear reason and are never substituted with an intra-socket mapping; `spans_sockets` agrees with the support decision. Intended behavior preserved on NPS1/NPS2/NPS4 systems; single-socket multi-NUMA/fake-NUMA (one physical socket) and unknown/ambiguous socket membership do not produce supported cross-socket mappings.

### Usable-node validation consolidation and fixture determinism (`stage0/dist_ingest/run_dist.py`, `stage0/dist_ingest/topology.py`)

- Automatic usable-node evaluation is consolidated in `run_dist._verified_usable_nodes()` and shared by `resolve_topology()` and `resolve_mapping_plan()` so both paths use the same authoritative usability rules for online nodes, allowed memory-node membership, per-node memory presence/known state, per-node CPU-list validity, and effective allowed-CPU availability (no second, subtly different usable-node definition).
- CPU-affinity discovery is injectable for deterministic synthetic topology tests via an explicit `sched_getaffinity` callback threaded through `discover_topology_inventory()` / `_allowed_cpus()` / `resolve_topology()` / `resolve_mapping_plan()` and the topology discovery path. Real-host runs preserve actual `os.sched_getaffinity()` verification/behavior. Concrete mappings still pass through the existing authoritative topology-validation path (`resolve_topology()` explicit-mapping validation) before being marked supported.
- `--mapping-profiles auto` preserves the **legacy** first-N-usable-nodes selection and is **not** a substitute for topology-aware experimental coverage. **Physical-NUMA rental must use an explicit topology-aware mapping-profile selection (normally `--mapping-profiles matrix`) rather than silently relying on legacy `auto`.** Legacy default behavior is unchanged; see `RENTAL_RECIPE.md`.

### Regression/topology tests and validation

- `stage0/dist_ingest/tests/test_benchmark_semantics.py`: added `TestCampaignPlanSemanticsC1Corrections` covering `--quick` = 1 trial/case, `--trials 5`, `--candidates fixed_faa` plans/executes only `fixed_faa`, unknown candidate rejected before timed-trial manifests, empty candidate list rejected, specified seed recorded and reproducible candidate order, `--shuffle-scenarios` actually shuffles scenario/mapping-block order by seed, and `--plan-only` vs real campaign agreement on the selected plan (including plan/provenance fields).
- `stage0/dist_ingest/tests/test_mapping_matrix.py`: added/updated deterministic topology tests for single-socket multi-NUMA and fake-NUMA-several-nodes-one-socket `cross_socket_spread` unsupported, NPS1 two-node cross-socket supported/spanning, NPS4 four-node cross-socket supported/spans both sockets, logical-count-1 cross-socket unsupported, and unknown/ambiguous socket membership never producing a supported cross-socket mapping; synthetic tests use injectable affinity discovery for host-independent determinism.
- **Exact validation (this correction, local/fake-NUMA host):**
  - `python3 -m unittest discover -s stage0/dist_ingest/tests -v` → **186/186 OK** (26.666s)
  - `python3 -m unittest stage0.tests.test_stage0` → **81/81 OK** (16.005s)
  - `python3 -m unittest python.tests.test_numa_drain_guard` → **7/7 OK** (0.000s)
  - `python3 -m unittest python.tests.test_numa` → **36 tests, OK (skipped=1)** (3.322s)
- These validate driver/CLI-plan/topology/mapping/usability/provenance behavior only; they do **not** establish physical NUMA locality or scaling.

### Remaining limitations (C1 correction scope)

- No checkpoint 2–5 work performed (placement-sampling/isolation, sweeps/workloads/duration qualification, env/telemetry/reporting/calibration, EPYC orchestration/rehearsal). No `RENTAL_READINESS.md` yet; final WO-1 validations/sanitizers/stress pending later checkpoints.
- No physical multi-node NUMA validation; local/fake-NUMA results are not evidence of physical locality/scaling/remote-memory penalties. `mbind(MPOL_PREFERRED)` syscall success and placement sampling observations are not physical placement proof; `unknown` remains `unknown`.
- Legacy `--mapping-profiles auto` default behavior unchanged (documented as legacy/non-topology-aware); physical-rental invocation guidance requires explicit topology-aware profile selection.
- **Stopped for independent review after this correction checkpoint. Do not start checkpoint 2. No physical rental. No production adoption.**

## C1.9 Final correction — `WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-C1-FINAL-CHECK-2` (pre-C2)

**Purpose:** final C1 correction for campaign preflight empty-plan handling and topology-test determinism before checkpoint 2. Preserves existing C1 implementation and prior commits; no architecture redesign, no physical rental, no production adoption.

- **Branch:** `NEW/REFACTOR5.1`
- **Starting HEAD (correction):** `d7137f09f82d57ea99b147dabf68412f915d7a2b`
- **Frozen production files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched)
- **C files changed:** **none**. No sanitizer rerun required.

### Empty executable-plan rejection and partial-matrix behavior (`stage0/dist_ingest/run_dist_campaign.sh`)

- A campaign with zero executable `(scenario, mapping, candidate)` cases now fails preflight before build, corpus generation, or timed-trial setup. The reason is recorded in `prevalidation.json` (`status=failed`, explicit error); no successful `execution-plan.json`/`.run_plan.tsv` and no successful campaign completion manifest are produced. `--plan-only` also returns nonzero for an entirely non-executable plan.
- Partial topology support in matrix mode is preserved: supported `(scenario, mapping)` cases remain executable while unsupported mappings/scenarios are explicitly identified with reasons and recorded in prevalidation/plan provenance; only an entirely empty executable plan (or another existing hard preflight failure) is fatal.
- Deterministic synthetic-root campaign preflight support added via `DIST_SYSFS_ROOT`/`DIST_PROC_ROOT` (defaults preserve real-host behavior) to enable fixture-driven campaign tests.

### Injected affinity discovery propagation (`stage0/dist_ingest/run_dist.py`)

- `resolve_mapping_plan()` now passes `sched_getaffinity` to the final concrete-mapping `resolve_topology()` validation call (in addition to existing propagation), so inventory discovery, usable-node determination, mapping selection, and final concrete mapping validation all honor the same injected fixture inputs (`sysfs_root`, `proc_root`, `sched_getaffinity`) where applicable. Real-host affinity verification is unchanged.

### Tests and validation

- `stage0/dist_ingest/tests/test_benchmark_semantics.py`: deterministic campaign tests for zero usable nodes with inventory available (rejected), zero supported mapping variants for all selected cases (rejected), partially supported matrix running supported cases while recording unsupported ones, empty-plan rejection before timed-trial manifests, and plan-only vs real-campaign behavior.
- `stage0/dist_ingest/tests/test_mapping_matrix.py`: deterministic test proving synthetic `resolve_mapping_plan()` success/failure follows the injected affinity/topology fixture regardless of actual host CPU affinity.
- **Exact validation (this correction, local/fake-NUMA host):**
  - `python3 -m unittest discover -s stage0/dist_ingest/tests -v` → **190/190 OK** (28.081s)
  - `python3 -m unittest stage0.tests.test_stage0` → **81/81 OK** (16.292s)
  - `python3 -m unittest python.tests.test_numa_drain_guard` → **7/7 OK** (0.000s)
  - `python3 -m unittest python.tests.test_numa` → **36 tests, OK (skipped=1)** (3.466s)
- These validate driver/preflight/topology/mapping/usability/provenance behavior only; they do **not** establish physical NUMA locality or scaling.

### Remaining limitations (unchanged)

- No checkpoint 2–5 work performed; no `RENTAL_READINESS.md`; full WO-1 validations/sanitizers/stress pending later checkpoints. No physical multi-node NUMA validation. No physical rental. No production adoption.
- **Stopped for independent review after this final C1 correction. Do not start checkpoint 2 until reviewed.**

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
