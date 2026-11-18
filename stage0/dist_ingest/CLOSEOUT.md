# WO-NUMA-DIST-INGEST-CAMPAIGN-PREFLIGHT-CLOSEOUT-3 — Closeout

**Work order:** `WO-NUMA-DIST-INGEST-CAMPAIGN-PREFLIGHT-CLOSEOUT-3` (final narrow rental-driver correctness checkpoint).  
**Supplements/preserves:** `WO-NUMA-DIST-INGEST-RENTAL-READINESS-CLOSEOUT-2` (`a4311c75`) and all prior preserved checkpoints/history (`419c0ce1`, `7e3a4d08`, `f9bc3541`, `b542dc6d`, `68d3efcb`, `f5fd2691`, `dd19397d`, `a4311c75`). Does **not** reopen/redesign ingestion engine, benchmark semantics, or NUMA architecture.

**Status:** WO-3 corrections implemented and validated on this host. **No physical-NUMA hardware rented. No production adoption started.**

## 1. Repository state

- **Branch:** `NEW/REFACTOR5.1`
- **Starting/expected HEAD (before this correction):** `a4311c755a6fa168f31b941be35415976998004a` (verified)
- **Pre-edit worktree:** clean (verified)
- **Final HEAD (this checkpoint):** see commit recorded for `dist-ingest: apply WO-NUMA-DIST-INGEST-CAMPAIGN-PREFLIGHT-CLOSEOUT-3`
- **Working-tree status at closeout:** clean after commit/push (intended)
- **Frozen production files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched; verified)
- **C sources changed:** **none** (no C changes expected; none made). Sanitizer reruns not required/applicable.
- **Isolation:** changes confined to experimental `stage0/dist_ingest/` campaign driver, tests, and docs.

## 2. P1 — Explicit physical-node mapping validated during campaign preflight

- **Correction (`stage0/dist_ingest/run_dist_campaign.sh`):** explicit `--phys-nodes` preflight no longer checks only list/count shape. It now validates the **actual explicit mapping** using the existing `run_dist.resolve_topology()` implementation (no duplicated validation rules).
- **Validation scope:** after confirming all selected scenarios share one logical node count (single explicit list restriction), preflight validates that selected logical node count once against the same `phys_nodes` mapping string and **same pinning semantics as trials** (`no_pin=False`, matching default runner behavior). Validation occurs **before build, corpus generation, or timed-trial execution**.
- **Rejected before timed-trial setup (no candidate trial launched):** malformed physical-node lists; duplicate physical node IDs; offline/unknown physical node IDs; nodes outside the allowed memory-node set; nodes with no memory or indeterminate memory information; missing/unparsable node CPU lists; nodes without allowed CPUs when pinning is required; and any mapping for which `resolve_topology()` cannot establish the requested topology (including its full topology-establishment checks).
- **Same mapping guaranteed:** the mapping accepted by preflight is the same explicit `phys_nodes` string passed to every trial spec/runner (no alternate interpretation).
- **Provenance concepts kept distinct:** actual usable nodes discovered on the host (`host_usable_nodes`, `host_usable_node_count`, `available_usable_nodes` = host-discovered count, **not** `len(--phys-nodes)`), explicit physical-node IDs / explicit selected node count, and selected scenario logical node counts recorded separately. `physical_node_mapping` records mode, validated explicit IDs, validation status, and resolved logical-to-physical mapping when established.

## 3. P2 — Unknown scenario IDs rejected

- **Correction:** when `--scenarios` is explicitly supplied, every requested ID is compared against scenario definitions available for the selected campaign mode (quick/non-quick). Unknown IDs are rejected **before timed trials**, even when other requested IDs are valid (e.g. `--scenarios equal,typo` fails; `equal` is not silently run alone). Valid filtering behavior and documented profile selections preserved.

## 4. P2 — Profile provenance and actual profile selection

- **CLI-tested profile selection:** `--profile nodes2`, `--profile nodes4`, and `--profile full` exercised through the command-line interface.
  - `--profile nodes2` (non-quick) selects exactly `nodes2,small,tiny`.
  - `--profile nodes4` (non-quick) selects the documented nodes4 set.
  - `--profile full` (CLI) selects the full default non-quick set (on this 4-usable-node host this is correctly rejected before timed trials due to `nodes8` incompatibility, evidencing `nodes8`/full-set selection; complete successful-prevalidation listing of the full non-quick set is not observable on this host because the incompatibility is correctly caught pre-trial).
  - `--profile full --quick` selects all quick scenarios (CLI, recorded).
- **Corrected provenance semantics:** records `scenario_profile_requested`, `scenario_profile_effective`, and `scenario_profile_overridden` (plus backward-compatible `scenario_profile` reflecting effective selection). When explicit `--scenarios` overrides a requested profile, requested profile is preserved but effective selection/profile is marked `custom` (requested profile not represented as effective). When default selection is chosen without explicit profile/scenarios, effective selection recorded accurately (`full` for non-quick default-all path by implementation; `quick_default` recorded/verified for quick default selection on this host). `scenarios_filter_explicit` recorded.

## 5. Deterministic regression tests added/updated

In `stage0/dist_ingest/tests/test_benchmark_semantics.py` (`TestCampaignScenarioValidation`), covering required cases (all verify invalid configuration rejected **before timed-trial manifests** where applicable):
1. Duplicate explicit physical-node IDs rejected during campaign preflight, before trial manifests.
2. Explicit ID not online/usable rejected during campaign preflight, before trial manifests.
3. Explicit mapping with valid sparse physical IDs succeeds when topology allows it (validated mapping, distinct host-vs-explicit provenance).
4. Explicit mapping still rejects mixed logical node counts.
5. Unknown scenario ID mixed with valid IDs rejected.
6. Actual `--profile nodes2` selects exactly `nodes2,small,tiny` in non-quick scenario set (CLI).
7. Actual `--profile nodes4` selects documented nodes4 set (CLI).
8. Actual `--profile full` selects full default set (CLI; evidenced via selected `nodes8` incompatibility on 4-node host) and `--profile full --quick` selects all quick scenarios.
9. Explicit scenario override represented accurately in provenance (requested vs effective/custom, not misattributed).
10. Default selection has accurate effective-profile provenance (quick default recorded/verified; non-quick default-full path implemented).

Existing campaign/provenance tests updated for corrected semantics (host usable nodes distinct from explicit selection; effective/custom profile when scenarios explicit).

## 6. Validation

- **C changes:** none. Frozen production files untouched. Sanitizer reruns unnecessary.
- **Normal suites:**
  - `python3 -m unittest discover -s stage0/dist_ingest/tests -v` → **153/153 OK**
  - `python3 -m unittest stage0.tests.test_stage0` → **81/81 OK**
  - `python3 -m unittest python.tests.test_numa_drain_guard` → **7/7 OK**

Local/fake-NUMA tests validate driver and topology-handling behavior only; they do **not** establish physical NUMA locality or scaling.

## 7. Remaining limitations

- No physical multi-node NUMA validation; fake/local results and local topology-handling tests are **not** evidence of physical locality/scaling/remote-memory penalties.
- Full non-quick default-set successful prevalidation/provenance recording could not be end-to-end exercised on this 4-usable-node host because `nodes8` is correctly rejected before timed trials (selection intent validated via CLI rejection/provenance logic).
- `mbind(MPOL_PREFERRED)` syscall success and placement sampling observations are not physical placement proof; `unknown` remains `unknown`.
- Hugepage-success accounting not proven on this host.
- No C changes in WO-3; ASan/UBSan/TSan not rerun (no leak-sanitizer claim).
- Pipe ingestion excluded from dist-candidate bake-off.
- Synthetic consumer not equivalent to production worker pipeline.

## 8. Confirmation / stop condition

- Campaign preflight validates the **actual explicit mapping** that trials will use (via `run_dist.resolve_topology`, same semantics); unknown scenario names cannot silently disappear; and profile provenance describes the actual selected scenarios (requested vs effective).
- **No physical-NUMA rental or production adoption started. No production code changed. No further architecture workstream begun.**
- **Stopped for review** at this checkpoint.
