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

## C2 — Placement-sampling isolation and measurement integrity (checkpoint 2, pre-C3)

**Work order:** `WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-AND-EXPERIMENT-COMPLETION-1`, checkpoint 2.  
**Purpose:** isolate placement sampling from timed performance measurement so `move_pages()` sampling does not impose treatment-dependent overhead on the timed candidate being evaluated; keep placement validation as a distinct, linked experiment; do not expand into parameter sweeps or workload changes. Preserves C1/C1-correction behavior and prior commits; no architecture redesign, no physical rental, no production adoption.

- **Branch:** `NEW/REFACTOR5.1`
- **Starting HEAD (C2):** `da78449bbda7173e2055e6c77637c12bc5d25501` (C1 final correction, reviewed/closed)
- **Frozen production files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched)
- **Experimental C changed:** `stage0/dist_ingest/dist_ingest.c`, `stage0/dist_ingest/dist_ingest.h` only (isolated dist-ingest prototype; not production ABI/frozen engine). `stage0/libdist_ingest.so` rebuilt.
- **Sanitizers:** no frozen production C changes; no sanitizer rerun required for this checkpoint.

### Placement-sampling mode and measurement integrity (experimental engine)

- Added `di_policy_params_t.placement_sampling` (`stage0/dist_ingest/dist_ingest.h/.c`): `0` = **off** (performance-isolated default), `1` = **on** (placement-validation experiment).
- When `placement_sampling==0`, `di_sample_placement()` performs **no in-run `move_pages`/sampling work** in the timed path and reports sampling not performed (`placement_sampled_pages==0`, `placement_sampling_not_performed` set for nodes); performance-isolated trials do not incur treatment-dependent sampling overhead.
- When `placement_sampling==1`, in-run `move_pages` sampling runs as before for placement-validation experiments (timing is tainted by sampling overhead and must not be treated as a clean performance measurement).

### Trial classes, validity, and provenance (`run_dist.py`)

- CLI: `--placement-sampling {off,on}` (default `off`), `--trial-class {performance,placement_validation}` (defaults from placement sampling mode), `--linked-performance-trial <id/path>` for placement-validation provenance/linkage.
- `DIST_RESULT` now records `trial_class`, `measurement_integrity` (`placement_sampling`, mode, `performance_isolated`, `timing_tainted_by_in_run_sampling`, linked performance trial), `linked_performance_trial`, and comparability/placement-semantics notes distinguishing performance-isolated vs placement-validation experiments.
- Performance-measurement validity (`validity.performance_measurement`) is **false** when in-run placement sampling is enabled (`placement_sampling=on`), in addition to existing functional/affinity/scan-evidence requirements. Placement observations remain reported separately; `placement_observed`/NUMA-placement validity are not conflated with performance-measurement validity.

### Campaign, case runner, and reporting

- `stage0/run_case.py`: forwards `placement_sampling`, `trial_class`, and `linked_performance_trial` to `run_dist.py`.
- `stage0/dist_ingest/run_dist_campaign.sh`: `--placement-experiments off|paired` (default `off`). Performance trials for dist-ingest candidates run with `placement_sampling=off` (`trial_class=performance`). `paired` runs an additional linked placement-validation experiment per performance trial (`placement_sampling=on`, `trial_class=placement_validation`, distinct case id `...__placement_validation`, linked to the corresponding performance trial manifest). Plan/prevalidation/execution-plan/outcomes/campaign manifest record placement-experiment mode, trial class, placement sampling mode, and linkage.
- `stage0/dist_ingest/report_dist.py`: separates performance and placement-validation trial classes; headline/summary performance medians and performance-valid denominators use **performance-class, performance-valid trials only** (placement-validation experiments excluded). Placement-validation experiments are reported in a distinct section with linkage and timing-taint/provenance; they are not mixed into performance headline statistics.

### Tests (C2)

- Updated ctypes `DiPolicyParams` mirrors in dist-ingest tests to include `placement_sampling`; updated `test_addendum_a.py` placement-sampling case to explicitly enable in-run sampling for placement-validation behavior.
- Added deterministic C2 coverage in `stage0/dist_ingest/tests/test_benchmark_semantics.py` (`TestCheckpoint2PlacementSamplingIsolation`): engine-level performance mode (`placement_sampling=0`) performs no in-run sampling (`sampled_pages==0`, `sampling_not_performed` set) across policies; placement-validation mode (`placement_sampling=1`) performs in-run sampling when available; performance-measurement validity is false when sampling-tainted; `run_dist.py` default is performance-isolated and placement-validation CLI runs are distinct/linked/tainted/non-performance-valid.
- Added deterministic reporting coverage in `stage0/dist_ingest/tests/test_report_dist.py` (`TestCheckpoint2PlacementSamplingReporting`): placement-validation trials are excluded from headline performance stats and reported separately with linkage/timing-taint notes.
- Existing report-dist assertions adjusted only where required by the C2-compatible summary format (performance-class denominators/notes) while preserving intent.

### Validation (checkpoint 2, local/fake-NUMA host)

- **Exact validation:**
  - `python3 -m unittest discover -s stage0/dist_ingest/tests -v` → **196/196 OK** (28.172s)
  - `python3 -m unittest stage0.tests.test_stage0` → **81/81 OK** (16.414s)
  - `python3 -m unittest python.tests.test_numa_drain_guard` → **7/7 OK** (0.000s)
  - `python3 -m unittest python.tests.test_numa` → **36 tests, OK (skipped=1)** (3.340s)
- Targeted C2 smoke checks: performance-isolated default `run_dist.py` reports `trial_class=performance`, `placement_sampling=off`, `sampled_pages=0`, `sampling_not_performed=true`; placement-validation `run_dist.py --placement-sampling on --linked-performance-trial ...` reports `trial_class=placement_validation`, `placement_sampling=on`, linked trial, `timing_tainted_by_in_run_sampling=true`, `validity.performance_measurement=false`, and in-run sampling performed when available.
- These validate driver/harness/reporting/measurement-integrity behavior only on this local/fake-NUMA host; they do **not** establish physical NUMA locality, placement, or scaling.

### Remaining limitations (C2 scope)

- No checkpoint 3–5 work performed (parameter sweeps, workload expansion, duration qualification, cache policies; environment/telemetry/reporting improvements, binary provenance, calibration utility; EPYC stage/orchestration integration and final rehearsal). No `RENTAL_READINESS.md` yet; full WO-1 validations/sanitizers/stress pending later checkpoints.
- No physical multi-node NUMA validation/rental; local/fake-NUMA results are not evidence of physical locality/scaling/remote-memory penalties. `mbind(MPOL_PREFERRED)` syscall success and placement sampling observations are not physical placement proof; `unknown` remains `unknown`.
- `placement_sampling` defaults to off for performance-isolated measurement; placement-validation experiments are observational diagnostics and remain timing-tainted by in-run sampling (not suitable for headline performance comparison).
- **Stopped for independent review after this C2 checkpoint. Do not start checkpoint 3. No physical rental. No production adoption.**

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


---

# WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-C2-CORRECTIONS-1 — Closeout

**Work order:** `WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-C2-CORRECTIONS-1` (C2 measurement-integrity and experiment-planning corrections).  
**Builds on:** C2 checkpoint `6d5d12333511ec1c4b0af469049e5ecb8bb49fc1` (`dist-ingest: checkpoint 2 placement-sampling isolation and measurement integrity`) on `NEW/REFACTOR5.1` (local HEAD and `origin/NEW/REFACTOR5.1` both verified at correction start).  
**Reviewer-reported C2 SHA mismatch:** `6d5d123356f65d0c11392c4f50bf206e1c26953f` could not be resolved; actual C2/start HEAD reported above (history not rewritten).

**Status:** correction implemented and validated on this local/fake-NUMA host. **No physical-NUMA hardware rented. No production adoption started. No C3 work started.**

## 1. Repository state

- **Branch:** `NEW/REFACTOR5.1`
- **Starting HEAD (before this correction):** `6d5d12333511ec1c4b0af469049e5ecb8bb49fc1` (verified; same as `origin/NEW/REFACTOR5.1` at start)
- **Final HEAD (this correction checkpoint):** see commit recorded for this correction
- **Remote tracking state at closeout:** `origin/NEW/REFACTOR5.1` updated to this correction commit (after push)
- **Working-tree status at closeout:** clean after commit/push of intended source/test/doc changes only (generated/untracked build artifacts not committed)
- **Frozen production files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched; verified)

## 2. Corrected hot path (P1) — `stage0/dist_ingest/dist_ingest.c`, `dist_ingest.h`

- Allocation/reservation path no longer dispatches `di_sample_placement()` at all when placement sampling is disabled: call site guarded on `eng->P.placement_sampling != 0`. Once-per-node `placement_sampling_not_performed` initialization at engine creation retained.
- `placement_sampling` validated as binary `0|1` at the C engine boundary in `di_create()` (invalid values rejected).
- Sampling-on behavior/placement-validation metrics preserved.
- Test-only dispatch counter/seam added (`di_test_reset_placement_sample_calls` / `di_test_get_placement_sample_calls`), incremented only on sampler invocation; no permanent per-allocation instrumentation on the performance path. Seam-based tests prove sampling-off performs no sampler dispatch per allocation and sampling-on dispatches with preserved sampling behavior/metrics.

## 3. Complete paired planning and execution (P1) — `stage0/dist_ingest/run_dist_campaign.sh`

- `--placement-experiments` validated as exactly `off` or `paired` before build/corpus/trial setup (invalid values rejected with no successful execution plan/prevalidation and no corpus setup).
- Requested/effective placement-experiments mode and placement-validation run count recorded in `prevalidation.json` and `execution-plan.json`; plan-only output reports placement-validation run count.
- For `paired`, every planned placement-validation run is represented explicitly in `execution-plan.json` (`planned_experiments`, per-block planned experiments) and in authoritative `.run_experiments.tsv`: scenario/mapping identity, candidate, trial, distinct PV case id, `trial_class=placement_validation`, `placement_sampling=on`, and linked performance-trial manifest path. Expected/planned PV run counts included.
- Actual campaign executes exactly the paired runs represented by the explicit plan (`.run_experiments.tsv`); no runtime-only expansion. Plan-only and real paired execution agree on identities/links/counts.
- Production-reference candidates remain separated and excluded from distributed-engine placement experiments.

## 4. Report failure classification (P1) — `stage0/dist_ingest/report_dist.py`

- `trial_class`, `placement_sampling`, and `linked_performance_trial` populated from campaign outcome immediately when creating report records (authoritative). Successful manifest data may refine but does not erase outcome classification when outcome provides it.
- Failed/missing/unreadable placement-validation runs remain classified as placement-validation records (not promoted to performance class), do not enter performance-class attempt/functional-completion denominators, and remain visible with class/linkage in placement-validation/invalid reporting.
- Minor structural fix: per-trial node/invalid-detail emission kept within per-record processing so records with missing/unreadable dist manifests do not break report generation.

## 5. CLI/result consistency (P2) — `stage0/dist_ingest/run_dist.py`

- `placement_sampling=off` ⇔ `trial_class=performance` and `placement_sampling=on` ⇔ `trial_class=placement_validation` enforced before engine create/run when `--trial-class` is provided; contradictions rejected with no engine execution/result emission.
- Matching combinations remain valid; emitted `DIST_RESULT` has internally consistent sampling mode, trial class, and measurement-integrity/performance-validity fields.

## 6. Test cleanup and coverage (P2 / corrections)

- Exactly one `TestCheckpoint2PlacementSamplingIsolation` in `stage0/dist_ingest/tests/test_benchmark_semantics.py` and one `TestCheckpoint2PlacementSamplingReporting` in `stage0/dist_ingest/tests/test_report_dist.py`; `if __name__ == "__main__": unittest.main()` consolidated to bottom of each module. Unrelated historical tests not altered.
- Added correction coverage: C seam-based no-dispatch (perf-off) and dispatch-on (placement-validation) tests, binary `placement_sampling` rejection at C boundary, `run_dist.py` contradiction-before-execution and matching-combination consistency tests, failed/missing/unreadable placement-validation report classification tests, and campaign tests for invalid `--placement-experiments` rejection before build/corpus/trials, plan-only off/paired explicit planning/counts/identities/links with production-reference exclusion, and real paired campaign executing exactly planned pairs.

## 7. Validation

- **Rebuild:** `cd stage0/dist_ingest && make` (normal build path) → `make: Nothing to be done for 'all'.` / up-to-date shared library rebuilt earlier in correction (`stage0/libdist_ingest.so`, untracked, **not committed**).
- **Required suites (exact):**
  - `python3 -m unittest discover -s stage0/dist_ingest/tests -v` → **206/206 OK** (29.868s)
  - `python3 -m unittest stage0.tests.test_stage0` → **81/81 OK** (16.264s)
  - `python3 -m unittest python.tests.test_numa_drain_guard` → **7/7 OK** (0.000s)
  - `python3 -m unittest python.tests.test_numa` → **36 tests, OK (skipped=1)** (3.313s)
- **Relevant C2 engine/campaign smokes (passed):** consolidated `TestCheckpoint2PlacementSamplingIsolation` (10 tests, including seam/no-dispatch/dispatch-on/binary-boundary/run_dist consistency) via `python3 -m unittest ... -v`; consolidated `TestCheckpoint2PlacementSamplingReporting` (2 tests) via `python3 -m unittest ... -v`; `TestCheckpoint2PlacementSamplingCampaignCorrections` plan-only off/paired + invalid rejection + real paired execution (4 tests) via `python3 -m unittest ... -v`.
- **Direct module runs / consolidated guard discovery:** `python3 stage0/dist_ingest/tests/test_report_dist.py` → **10/10 OK** (all classes discovered, including consolidated C2 reporting tests). `__main__` guards consolidated to exactly one at the bottom of each affected module (`test_benchmark_semantics.py`, `test_report_dist.py`); consolidated C2 tests discovered by unittest module/class execution as above. (Final guard cleanup recorded in C2-FINAL-CLEANUP-1 checkpoint.)
- **Scope hygiene:** no frozen production files or production sources modified; no generated/untracked build artifacts committed (`stage0/libdist_ingest.so` remains untracked). ASan/UBSan coverage **not rerun** for this correction (no sanitizer coverage implied).

## 8. Remaining limitations / stop condition

- C3–C5 work not started (parameter sweeps/workload expansion/duration-cache work, reporting improvements/binary provenance/calibration, EPYC stage/orchestration/rehearsal, `RENTAL_READINESS.md` as applicable later). No physical multi-node NUMA validation/rental; local/fake-NUMA results are not evidence of physical locality/scaling/remote-memory penalties.
- `mbind(MPOL_PREFERRED)` syscall success and placement sampling observations are not physical placement proof; `unknown` remains `unknown`. Placement-validation experiments remain timing-tainted and distinct from performance measurements.
- **Explicit confirmation:** no C3 work, no physical rental, no production adoption. **Stopped for independent review after this correction checkpoint.**

## WO-NUMA-ONE-SHOT-RENTAL-PREPARATION C3 checkpoint

**Purpose:** add parameter sweeps, duration qualification, workload expansion, and cache-preconditioning policy as separate attributable experimental axes in the experimental `stage0/dist_ingest/*` harness/reporting/tests/docs. No C4/C5, no physical rental, no production adoption.

**Status:** C3 implemented and validated on this local/fake-NUMA host. **No physical-NUMA hardware rented. No production adoption started. No C4/C5 work started.**

### Repository state

- **Branch:** `NEW/REFACTOR5.1`
- **Starting HEAD (before this C3 checkpoint):** `8b66c10ee089c9d49b66c8515f3a41873a3ed8d4` (C2 final cleanup, accepted; `origin/NEW/REFACTOR5.1` at C3 start)
- **Final HEAD (this C3 checkpoint):** see commit recorded for this C3 checkpoint
- **Frozen production files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched)

### C3 axes (separate, attributable)

1. **Parameter sweeps (attributable parameter sets).** `run_dist_campaign.sh` accepts `--sweep-base-quantum`, `--sweep-max-backlog`, `--sweep-max-reservation` (comma-separated positive integer lists). The cartesian product forms explicit `parameter_sets` with stable `parameter_set_id` values and `sweep_axes` provenance recorded in `prevalidation.json`, `execution-plan.json`, `campaign-manifest.json`, `.run_experiments.tsv`, and per-outcome/per-manifest spec fields. Default (no sweep) produces `pset__default` with empty `sweep_axes`, preserving backward-compatible behavior. Parameter sets are carried through case ids/suffixes so results are not mixed across parameter sets.

2. **Duration qualification (separate factual axis, with repetition).** `run_dist_campaign.sh` accepts `--min-duration-seconds N` (finite, >= 0; `nan/inf` rejected). `stage0/run_case.py` records `duration_qualification` in `manifest.json` with `target_seconds`, effective/accumulated wall seconds, pass count, per-pass summaries, `repetition_used/capped/error`, factual `meets_target`/`qualified`, and a `duration_aggregate`. When a finite target is not met by the first pass, the harness repeats the same dist-engine measurement (bounded caps) until accumulated effective duration meets the target or the cap is reached; qualification is based on accumulated measured duration, not a post-run label alone. Report surfaces duration qualification details and duration-unqualified counts without mixing axes.

   C3-corrections-2 (P1/P2, per independent review): a pass contributes to accumulated effective duration only when ALL qualification conditions hold (not timed out; process rc 0; parseable `DIST_RESULT`; `DIST_RESULT.rc` 0; `correct` true; engine `wall_seconds` present/finite/valid) — via the single authoritative decision `_dist_pass_qualified` (`stage0/run_case.py`). Failed or timed-out passes contribute nothing (harness wall time is never substituted). The first pass's `complete` derives from this authoritative decision, not a pre-determination default. Repetition has its own wall-clock budget (`min_duration_repetition_budget_s`, default `max(30, 10*target)`), a pass-count cap, and per-pass timeout `min(case timeout, remaining budget)`; the wall-clock budget is recalculated AFTER each pass's cache preconditioning. An initially cache-incompatible pass stops repetition even when it already reached the target. The loop stops after the first unsuccessful repeated pass. Cache preconditioning is applied per pass (outside the timed interval) via `_cache_precondition`; passes with materially different actual cache treatment are not silently combined into one composite (conservative `cache_precondition_compatible` rule). A separate `duration_aggregate` manifest field carries the coherent composite measurement: `T_agg = sum T_i`, `B_agg = sum B_i` (consumed bytes), `throughput_agg = B_agg/T_agg`, scanned bytes summed per-pass with scan-equals-consumed checked per pass and across the aggregate, and reservations summed; aggregate validity requires every contributing pass to independently satisfy performance-validity requirements (unknown/invalid is never silently promoted). Report (`stage0/dist_ingest/report_dist.py`) uses the composite for repeated trials' headline throughput/wall/reservations and headline scan/consumed, uses the aggregate validity for the perf-valid headline count, displays accumulated duration and pass count, identifies failed/excluded passes and stop reasons, preserves pass-1 as provenance, and reports invalid aggregates explicitly.

3. **Workload expansion (attributable workload/scenario axis).** Non-quick campaign scenarios expanded with `medium_seq` (`corpora/medium.bin`, 16MiB), `chunkstress` (large corpus, small backlog/quantum stress), and `boundary_small_backlog` (boundary corpus, small backlog). Scenarios remain explicitly selectable via `--scenarios`; `workload_id` is recorded in plan/outcomes/manifests for attribution.

4. **Cache-preconditioning policy (separate factual policy axis).** `run_dist_campaign.sh` accepts `--cache-precondition-policy` with enum `best_effort_os_cache` (default), `warm_repeat`, `drop_caches_if_privileged`; invalid values rejected before execution. `stage0/run_case.py` applies/records `_cache_precondition()` factually in `manifest.json` (`requested_policy`, actions, achieved, privileged attempted/succeeded, fallback, notes). `drop_caches_if_privileged` records actual success/failure and fallback; no privileged cold-cache control is claimed unless the action succeeded. Report surfaces per-trial cache-precondition outcomes/fallbacks and campaign-level outcome summary.

### Reporting / attribution safeguards

- `stage0/dist_ingest/report_dist.py` groups comparative summary and per-trial detail by `(scenario, mapping, parameter_set_id, candidate)`, adds `param set` column, and includes C3 axis provenance. Placement-validation and invalid-trial sections include parameter-set attribution. Existing report tests with exact old row strings were updated to preserve intent for the new attributable column.
- `.run_experiments.tsv` uses unit-separator (`0x1f`) delimiter to preserve empty C3 fields (bash tab IFS collapses empty fields); tests check existence and plan/manifest content.

### Validation (exact)

- `python3 -m unittest discover -s stage0/dist_ingest/tests -v` → **219/219 OK** (34.163s)
- `python3 -m unittest stage0.tests.test_stage0` → **81/81 OK** (16.486s)
- `python3 -m unittest python.tests.test_numa_drain_guard` → **7/7 OK** (0.000s)
- `python3 -m unittest python.tests.test_numa` → **36 tests, OK (skipped=1)** (3.420s)
- C3 focused tests added in `stage0/dist_ingest/tests/test_benchmark_semantics.py` (`TestC3AttributableAxes`, 13 tests) covering default no-sweep, sweep attribution/no-mixing, duration qualification recording, invalid policy/min-duration rejection, workload expansion selection, cache-precondition factual behavior, and report parameter-set grouping. Report tests updated for C3 attributable columns while preserving C2 semantics.

### C3 correction (independent review)

- **P1 duration qualification (C3-corrections-2):** `--min-duration-seconds` requires finite >= 0 (`nan/inf/-inf`/malformed rejected in campaign prevalidation; `stage0/run_case.py` also defends against invalid targets bypassing prevalidation). A dist-engine pass qualifies only when the six conditions in WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-C3-CORRECTIONS-2 §2 hold (process success, not timed out, valid parseable `DIST_RESULT`, dist rc 0, functional correctness, valid engine `wall_seconds`) — single authoritative decision `_dist_pass_qualified`; no harness-wall fallback. Failed/timed-out passes contribute no duration; the initial pass's `complete` derives from the authoritative decision. Manifest records `duration_qualification` (target, effective/accumulated wall, passes, repetition_used/capped/error, stop_reason, meets_target/qualified) and `duration_aggregate` (contributing passes, T/B/scanned/reservations aggregates, throughput_agg, aggregate_valid, invalid reasons). Repetition: bounded by pass-count cap + `min_duration_repetition_budget_s` (default `max(30, 10*target)`), per-pass timeout `min(case timeout, remaining budget)`, stops after first unsuccessful pass, timeout contributes nothing. Process-group cleanup: SIGTERM → grace → SIGKILL escalation, direct-child reap, group-gone verification, recorded in per-pass `cleanup`. Report uses the composite for repeated trials and reports invalid/excluded aggregates explicitly.
- **P2 cache outcomes in report:** report includes per-trial cache-precondition requested/achieved/privileged/fallback details and campaign-level outcome/fallback summary.
- **P2 runtime tests:** added real multi-parameter-set campaign test (distinct parameter sets flow through runtime TSV parser to specs/manifests/outcomes/report rows), meaningful duration qualification pass/fail tests, non-finite duration rejection tests, and report cache-outcome surfacing test.
- **Validation (C3 correction):** dist-ingest 219/219 OK; stage0 81/81 OK; numa_drain_guard 7/7 OK; numa 36 OK (skipped=1).

### Limitations / explicit stop

- No C4/C5 work performed (environment/telemetry/reporting improvements beyond C3 attribution, binary provenance, calibration utility, EPYC stage/orchestration integration, rehearsal, `RENTAL_READINESS.md` finalization as later-scope items). No physical multi-node NUMA validation/rental; local/fake-NUMA results are not evidence of physical locality/scaling/remote-memory penalties.
- C3 parameter sweeps/qualification/workload/cache axes are experimental harness/reporting controls; they do not change production forkrun behavior. `drop_caches_if_privileged` is factual and may fall back; it is not a guaranteed cold-cache control.
- **Explicit confirmation:** no C4/C5, no physical rental, no production adoption. **Stopped for independent review after this C3 checkpoint.**

## Corrections-3 closeout (branch `WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-C4-C5-CORRECTIONS-3`)

Base: corrections-2 tip `3e6a924e` + this closeout commit. Spec: WO-external review
(authoritative-independent reviewer) of corrections-2:

- **P1 — wrong-node placement accepted as valid:** fixed — `_observed_placement` records
  expected_node + observed pages_on_expected + unsuccessful_pages; `_meas` marks
  invalid_placement on wrong-node/missing/unsuccessful placement; failed query vs wrong
  node recorded distinctly. (Previous test certified a misplaced destination as valid.)
- **P2 — backlog label:** `report_dist` now prints `max_*_backlog_by_node` and
  `max_*_backlog_sum_of_node_maxima` explicitly.
- **P2 — missing campaign manifest:** `require_campaign_manifest` (epyc/lib.sh) — campaign
  exiting 0 without manifest → stage exit 1; campaign exit preserved.

plus WO-internal §11 rehearsal rehearsal (corrections-3 base):

- **§5.2 per-node ingestor workload controls** — engine (`di_ingestor_cfg_t`,
  `di_node.ing_cfg`, `di_ingestor_sleep_ns`, ingest-path hooks), `run_dist.py`
  (`DiIngestorCfg` + `--ingestor-*-per-node` + provenance), `run_case.py` spec plumbing,
  campaign scenario-line `pn` field + 4 asymmetric-ingestor scenarios
  (`slow_ingestor_one/stall_recover/fast_consumer/slow_consumer`). Modes:
  `off` (default), `delay_per_claim`, `delay_after_read`, `stall_then_recover`,
  `rate_limit`. Observed evidence + per-node provenance in DIST_RESULT.
- **§2 placement_sampling=2 (full)** — exhaustive sampling for diagnostics;
  `--placement-experiments off|paired|full`; placement-validation experiments in
  'full' mode record placement_sampling=2 + trial_class=placement_validation.
- **§10.2 sanitizers:** `stage0/dist_ingest/SANITIZER_EVIDENCE.md` — ASan+UBSan:
  254 tests OK, 0 reports; TSan: 254 tests OK, 0 warnings.
- **epyc/rehearsal_rehearsal_45.sh** — §11 rehearsal rehearsal (45-stage + plan-only +
  campaign + 90_collect + provenance reconciliation).

Validation: `TestIngestorWorkloadControls` (6) + `TestCampaignWiring` (4) +
`test_placement_experiments_full_mode_emits_full_sampling` (2 new campaign tests in
`TestCampaignWiring`) + `test_engine_placement_sampling_modes_and_rejection` +
`NONQUICK_NODES4` update; mirror struct updates (5 test files) for the new
`DiNodeMetrics`/`DiConfig` fields. Suites: 254 dist-ingest, 101 stage0, 7 drain-guard,
36 numa (skip=1). Sanitizer re-runs: 254 + 254.

Full closeout: `stage0/dist_ingest/RENTAL_READINESS.md` (WO §12, 20 items).

## Corrected corrections-1/2 acceptance

External reviewers' earlier findings (corrections-1 review: P1–P2; corrections-2
review: 3 findings) remain addressed by corrections-3:
- corrections-1 review P1 (wrong-node placement) — now fixed by corrections-3 §5.2 +
  corrections-2 work.
- corrections-2 review findings — remain fixed by corrections-2 (per external review
  acceptance of corrections-2).

**Stopped for independent review after corrections-3 reporting.**

## Corrections-4 closeout (WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-C4-C5-CORRECTIONS-4)

Corrections-4 against `60a699e2e38e976932d0e7c2b70abdfbd1f3c870`, tip
`423e7e77` (final code commit `3d023d66`; `4b5297bb` is doc-only over it —
`git diff 3d023d66 423e7e77 -- stage0/` is empty; 2026-11-24):

- **Fix 1 — rate-limit error path** (P1): moved the §5.2 rate-limit sleep
  after the `rr<0`/`act<assigned` error checks with overflow-safe
  `unsigned __int128` arithmetic (`dist_ingest.c::di_ingest_step`);
  regression test `TestIngestorWorkloadControls.test_rate_limit_error_path_terminates_promptly`
  (pread_seam-injected error, prompt termination asserted).
- **Fix 2 — `placement_sampling=2` exhaustive** (P1):
  `di_sample_placement` mode 2 now samples every addressable page
  (heap-allocated `idxs`, `malloc` fallback, all free paths covered);
  `dist_ingest.h` updated; engine test
  `TestPlacementSamplingModes` (`sampled == total_addressable_pages` on a
  >1024-page corpus, mode 1 keeps 1024-page bound).
- **Fix 3 — sanitizer evidence rerun** (P1, corrected): ASan+UBSan and TSan
  rerun on tip `423e7e77`: **Ran 259 tests — OK, 0 findings both**
  (2026-11-24); `SANITIZER_EVIDENCE.md` records both SHAs (corrections-3
  `60a699e2`, corrections-4 `3d023d66`; tip `423e7e77` is doc-only over it).
  `SANITIZER_EVIDENCE.md` records the exact tested SHA, clean tree,
  build + results (0 findings both).
- **Fix 4 — fail-closed ingestor-workload preflight** (P2):
  `run_dist._per_node_list` strict (unknown names, malformed ints,
  negative/excess entries raise ValueError); `run_dist.main()` preflight
  on all four §5.2 lists (exit 2); campaign→run_dist path covered.
  Tests: `test_malformed_ingestor_args_fail_preflight` +
  `TestCampaignWiring.test_ingestor_workload_controls_fail_closed_end_to_end`.

**Corrections-4 rehearsal rehearsal:** `epyc/rehearsal_rehearsal_45.sh`
rerun on the main tree @ `3d023d66` — exit 0, all 3 PASS lines (sweep plan,
provenance reconciliation: `source_sha` == `env-before` git.head_sha,
git.dirty == false, asymmetric-ingestor evidence). Rehearsal date
2026-11-24.

**Final status after corrections-4:** no rental, no physical NUMA
validation, no production files modified — unchanged from corrections-3.
