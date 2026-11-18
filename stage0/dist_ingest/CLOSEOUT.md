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
