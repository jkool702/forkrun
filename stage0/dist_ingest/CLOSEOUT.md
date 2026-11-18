# WO-NUMA-DIST-INGEST-RENTAL-READINESS-CLOSEOUT-2 — Closeout

**Work order:** `WO-NUMA-DIST-INGEST-RENTAL-READINESS-CLOSEOUT-2` (focused post-closeout correction checkpoint).  
**Supplements/preserves:** `WO-NUMA-DIST-INGEST-BENCHMARK-SEMANTICS-AND-RENTAL-DRIVER-CORRECTIONS-1` (`dd19397d`) and all prior preserved checkpoints (`419c0ce1`, `7e3a4d08`, `f9bc3541`, `b542dc6d`, `68d3efcb`, `f5fd2691`, `dd19397d`) and their documented behavior. Does **not** replace prior work, invalidate checkpoint history, or reimplement the ingestion architecture.

**Status:** WO-2 corrections implemented and validated on this host. **No physical-NUMA hardware rented. No production adoption started. No pipe-ingestion work or NUMA-ingest redesign started.**

## 1. Repository state

- **Branch:** `NEW/REFACTOR5.1`
- **Starting/expected HEAD (before this correction):** `dd19397d12204523f51c9443671f0acdc99e40a3` (verified)
- **Prior preserved checkpoints:** `419c0ce1`, `7e3a4d08`, `f9bc3541`, `b542dc6d`, `68d3efcb`, `f5fd2691`, `dd19397d` (all preserved/pushed lineage)
- **Final HEAD (this checkpoint):** see commit recorded for `dist-ingest: apply WO-NUMA-DIST-INGEST-RENTAL-READINESS-CLOSEOUT-2`
- **Working-tree status at closeout:** clean after commit/push (intended)
- **Frozen production files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched; verified)
- **Isolation:** changes confined to experimental `stage0/dist_ingest/` and necessary Stage 0 runner/report/integration (`stage0/run_case.py` for campaign provenance compatibility as needed is unchanged except not required; no C/frozen production changes). No C source changes in this WO.

## 2. P1 — Per-node affinity effective-verification semantics (corrected)

- **Finding addressed:** `affinity.effective_verified` was boolean and could describe unknown required affinity as verified.
- **Correction (`stage0/dist_ingest/run_dist.py`):** `affinity.effective_verified` is now **tri-state over applicable, required roles**:
  - `true`: every applicable, required role is requested, applied, queried, and matched.
  - `false`: at least one applicable, required role was requested but failed, could not be queried, or did not match.
  - `null`: at least one applicable, required role is unknown/unrequested and none failed.
  - Roles with `required=false` are not applicable and must not make the result unknown.
  - Empty set of applicable required roles => not applicable/unknown (`null`), not verified.
- **Architecture-specific requirements preserved:** distributed candidates require ingestor + consumer per configured node; centralized ingestion requires the single ingestor on node 0 + each configured consumer (other nodes' ingestor roles not applicable).
- **Run-level factual affinity validity:** unchanged in semantics (`_affinity_valid_factual` remains tri-state factual and independent of strict enforcement) except no defect found.
- **Compatibility/reporting:** no field claims affinity verification when a required role is unknown (per-node `effective_verified` is `null` in such cases; `--no-pin` yields unknown, not true).
- **Tests added/covered:** both roles unknown; one verified and one unknown; one failed and one verified; both verified; centralized node 0 with both required roles; centralized nonzero node with ingestor not applicable and consumer verified (and unknown-consumer case); empty applicable-required set unknown; requested-but-unqueried treated as failed/false; `--no-pin` produces unknown not true (runtime).

## 3. P1 — Performance-measurement validity includes consumer-workload evidence

- **Finding addressed:** performance validity did not require evidenced consumer-kernel execution/scan results.
- **Correction (`stage0/dist_ingest/run_dist.py`):** factual tri-state performance-measurement validity now requires functional correctness, verified affinity, and evidenced consumer workload:
  - **`full_byte_scan`:** `scan_equals_consumed` must be true for performance-measurement validity to be true. A false/incomplete scan result makes performance validity false. Missing or indeterminate scan evidence makes performance validity unknown unless another independent failure already makes it false.
  - **`none`:** scanned bytes must be zero for valid evidence; nonzero scanned bytes make performance validity false; missing/indeterminate evidence makes performance validity unknown unless another independent failure already makes it false. Explicit `none` workload label preserved; `none` results must not be combined with full-byte-scan results into one comparable campaign summary.
- **Strict flags:** `--strict-affinity` and `--strict-mbind` continue to control enforcement only; they do not alter factual validity.
- **Report aggregation (`stage0/dist_ingest/report_dist.py`):** separate counts reported for attempted trials, complete/functionally correct trials, performance-valid trials, and NUMA-placement-valid trials. **Headline comparative throughput, engine wall-time, and other performance summary medians use performance-valid trials only** (no false/unknown performance validity in headline performance statistics). Functionally-correct but performance-invalid/unknown trials are retained in the detailed report with raw throughput and validity reasons (not discarded). The report makes it obvious when there are **no performance-valid trials** and does not silently substitute functional correctness for performance validity. Mixed `full_byte_scan`/`none` kernel results are not combined into one comparable performance summary.
- **Tests added/covered:** helper-level scan-evidence and performance-validity cases (full scan matching/incomplete/unavailable evidence, none zero/nonzero/unavailable, independent-failure precedence); report aggregation tests for performance-valid-only headline medians, no-performance-valid-trials obvious, functional-but-performance-invalid/unknown trials retained with raw evidence, and mixed full-scan/no-kernel not comparable.

## 4. P1 — Campaign scenario profiles and topology compatibility

- **Finding addressed:** default full campaign included mixed 2/4/8-node scenarios while minimum preflight/topology assumptions were unclear and a single explicit `--phys-nodes` list could not map differing logical node counts.
- **Documented executable profiles (default/non-quick):**
  - **2 usable NUMA nodes (`nodes2`)**: scenarios configured for two nodes `nodes2,small,tiny` (exact `--scenarios nodes2,small,tiny`).
  - **4 usable NUMA nodes (`nodes4`)**: four-node scenarios plus compatible two-node scenarios, excluding `nodes8` (exact `--scenarios equal,slow_one,fast_one,asymmetric,stall_recover,nodes2,large_seq,small,tiny,boundary,backpressure`).
  - **8+ usable NUMA nodes (`full`)**: default full scenario set may run subject to topology validation (includes `nodes8`).
- **Driver behavior (`stage0/dist_ingest/run_dist_campaign.sh`):** validates selected scenario node counts against topology **before executing timed trials**. Incompatible selected scenarios fail before timed trials with a clear diagnostic (campaign does not begin and no timed trials are executed; unsupported scenarios are never marked successful). `--profile nodes2|nodes4|full` convenience supported.
- **Explicit `--phys-nodes` compatibility:** a single explicit list cannot map scenarios with different logical-node counts. Explicit-mapping campaigns are restricted to scenarios whose logical node count equals the number of nodes in `--phys-nodes`; incompatible selections are rejected before timed trials. Automatic topology selection may support mixed-count campaigns/profiles when enough usable nodes exist (each selected scenario validated against available usable nodes before timed trials).
- **Provenance:** records scenario profile, available usable nodes, selected scenarios (with node counts), and physical-node mapping (mode/list/note) in `prevalidation.json` and `campaign-manifest.json` (schema bumped to `dist-campaign/4` for added provenance fields; backward-compatible readers unaffected).
- **Tests added/covered:** incompatible scenario rejected before timed trials (no campaign-manifest/cases produced), explicit `--phys-nodes` count mismatch rejected before timed trials, provenance recorded in quick campaign artifacts. Local/fake-NUMA validation here is configuration/topology-handling only, **not physical-NUMA evidence**.

## 5. Documentation

- **`stage0/dist_ingest/RENTAL_RECIPE.md`:** updated with minimum node count per profile, exact 2-node/4-node/full campaign examples, explicit `--phys-nodes` compatibility rules, performance-valid vs functionally-correct trial semantics, and corrected per-node affinity tri-state semantics.
- **`stage0/dist_ingest/CLOSEOUT.md`:** updated to reflect final WO-2 behavior (this document).

## 6. Validation

- **No C changes in WO-2:** frozen production files untouched and no `stage0/dist_ingest` C sources modified; `libdist_ingest.so` rebuild not required by this WO (existing artifact reused).
- **Normal suites (this checkout):**
  - `python3 -m unittest discover -s stage0/dist_ingest/tests -v` → **143/143 OK**
  - `python3 -m unittest stage0.tests.test_stage0` → **81/81 OK**
  - `python3 -m unittest python.tests.test_numa_drain_guard` → **7/7 OK**
- **ASan/UBSan/TSan runtime:** no C changes in this WO; applicable sanitizer runtime tests not rerun against modified C. Normal regression suites executed as required. (Prior `dd19397d` closeout recorded ASan+UBSan and TSan passes on the unchanged C engine for WO-1 corrections.)

Counts recorded above. No C changes in WO-2; ASan/UBSan/TSan not rerun (normal suites run).

## 7. Scope boundaries (honored)

- No redo of centralized-ingest architecture; no replacement of existing common-engine design.
- No modification of frozen production files.
- No pipe-ingestion candidates, no production adoption, no NUMA-ingest redesign, no physical-NUMA rental.
- No weakening/removal of existing validation.
- Synthetic consumer not claimed equivalent to production worker pipeline.
- `MPOL_PREFERRED` success not claimed as physical locality proof.

## 8. Remaining limitations

- No physical multi-node NUMA validation; fake/local results and local topology-handling tests are not evidence of physical locality/scaling/remote penalties.
- `mbind(MPOL_PREFERRED)` syscall success and placement sampling observations are not physical placement proof; unknown remains unknown.
- Hugepage-success accounting not proven on this host.
- No C changes in WO-2 so ASan/UBSan/TSan were not rerun as part of this correction (no modified C); leak-sanitizer not claimed.
- Extreme `SSIZE_MAX`/`off_t` boundary cases not exhaustively exercised end-to-end beyond guards/tests.
- Pipe ingestion excluded from dist-candidate bake-off.

## 9. Readiness / confirmation

- **Physical-NUMA campaign driver readiness (for planned rental characterization):** corrected for WO-2 P1 issues - per-node affinity effective verification is tri-state and never claims unknown as verified, performance validity requires evidenced consumer workload and headline performance reporting uses performance-valid trials only, and the rental driver validates scenario/topology/explicit-mapping compatibility before timed trials and records provenance. **Conditionally ready** for physical-NUMA characterization subject to preflight/strict settings on real (non-fake) multi-node hardware and documented validity/comparability limits.
- **Not implied:** production adoption readiness or production end-to-end speedup.
- **Confirmation:** no physical-NUMA rental or production adoption was started.
