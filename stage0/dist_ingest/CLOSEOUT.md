# WO-NUMA-DIST-INGEST-BENCHMARK-SEMANTICS-AND-RENTAL-DRIVER-CORRECTIONS-1 — Closeout Report

**Work order:** `WO-NUMA-DIST-INGEST-BENCHMARK-SEMANTICS-AND-RENTAL-DRIVER-CORRECTIONS-1` (focused post-closeout correction checkpoint).  
**Supplements:** completed `WO-NUMA-DIST-INGEST-CORRECTIONS-AND-VALIDATION-2` (Sections 1–14, preserved). Does **not** replace prior work, invalidate checkpoint history, or reimplement the ingestion architecture.  
**Status:** corrections implemented, validated, and committed on this host. **No physical-NUMA hardware rented. No production adoption started. No pipe-ingestion work or NUMA-ingest redesign started.**

## 1. Repository state

- **Branch:** `NEW/REFACTOR5.1`
- **Starting/expected HEAD (before this correction):** `f5fd2691c07bf6eeccdd7ce91f5c3c1cb64a3e2e` (verified)
- **Prior preserved checkpoints:** `419c0ce1`, `7e3a4d08`, `f9bc3541`, `b542dc6d`, `68d3efcb`, `f5fd2691` (all preserved/pushed lineage)
- **Final HEAD (this checkpoint):** see commit recorded for `dist-ingest: apply WO-NUMA-DIST-INGEST-BENCHMARK-SEMANTICS-AND-RENTAL-DRIVER-CORRECTIONS-1`
- **Working-tree status at closeout:** clean after commit/push (intended)
- **Frozen production files modified:** **none** (`forkrun_ring.c`, `forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c` untouched; verified)
- **Isolation:** changes confined to `stage0/dist_ingest/` and necessary Stage 0 runner/report integration (`stage0/run_case.py`); production ingestion/frontend behavior unchanged.

### Files changed in this correction

- `stage0/dist_ingest/dist_ingest.h`, `stage0/dist_ingest/dist_ingest.c` (consumer kernel execution/accounting, mbind per-attempt requested/succeeded/failed accounting and compatibility semantics, result/metric fields)
- `stage0/dist_ingest/run_dist.py` (kernel CLI/default/wiring/provenance, scan-byte evidence, factual tri-state affinity/memory-policy/combined validity independent of strictness, topology-aware required role accounting, struct mirrors)
- `stage0/dist_ingest/run_dist_campaign.sh` (explicit `--consumer-kernel`, `--strict-affinity`, `--strict-mbind`, `--phys-nodes`; explicit per-candidate spec fields; campaign manifest config recording)
- `stage0/run_case.py` (forward `consumer_kernel` and strict/phys options to runner)
- `stage0/dist_ingest/report_dist.py` (dist-engine authoritative `DIST_RESULT.wall_seconds`, harness wall separate; `valid/total` counts all attempted trials including failed/missing/unreadable; separate validity dimensions with `unknown` distinct from `false`; consumer-kernel/scan evidence surfaced)
- `stage0/dist_ingest/tests/*` ctypes struct sync + new deterministic tests: `tests/test_benchmark_semantics.py`, `tests/test_report_dist.py`
- `stage0/dist_ingest/CLOSEOUT.md`, `stage0/dist_ingest/RENTAL_RECIPE.md` (final verified semantics)

## 2. P0 — Consumer memory-touching kernel enabled, wired, and evidenced

- **Finding addressed:** C scanned only when `consumer_kernel == 1`, but runner/campaign never set it (zero-initialized => none), so the claimed default full byte-scan was not executed in normal runs.
- **Correction:** normal runner and campaign now use **`full_byte_scan` by default** with explicit opt-out **`none`** (`--consumer-kernel full_byte_scan|none`). Wired end-to-end: `run_dist.py` arg parsing + `DiPolicyParams.consumer_kernel`, C engine scan execution, `run_case.py` spec→runner forwarding, `run_dist_campaign.sh` options and **explicit per-comparable-candidate spec field** (no undocumented default reliance), `DIST_RESULT`/`comparability`/`consumer_kernel` provenance and scan evidence, and `report_dist.py` display.
- **C API/header semantics clarified:** zero-initialized `consumer_kernel` means `0` (none) at C API level; runner/campaign default is `1` (`full_byte_scan`) and callers must set explicitly.
- **Evidence of execution:** per-node and aggregate `consumer_bytes_scanned` metrics (C engine, copied in results). `full_byte_scan`: each successfully consumed chunk scanned exactly once and scan count increases by chunk length; on functionally correct complete run aggregate scanned bytes == aggregate consumed bytes (verified). `none`: scanned bytes remain zero (verified). Not inferred from CPU time alone.
- **Comparability:** campaign writes the same selected kernel/params for `centralized_ingest`, `fixed_faa`, `local_adaptive`, `relative_adaptive` in each comparison block.
- **Tests:** runner default selects `full_byte_scan`; explicit `none` disables scan; full scan reports exact consumed bytes and per-node equality for all four common-engine policies; `none` reports zero for all policies; provenance identifies actual kernel; campaign-generated specs explicitly include selected kernel and strict options; end-to-end campaign smoke verifies kernel reaches C engine via scan-byte evidence in manifests/dist results (not just CLI acceptance).

## 3. P0 — Affinity validity factual, topology-aware, independent of strictness

- **Finding addressed:** prior validity depended on strict mode in ways that could report true despite requested failures in non-strict mode.
- **Correction:** factual tri-state affinity validity computed **independently of `--strict-affinity`** (strictness controls enforcement/abort, not truth):
  - **`true`:** all required, requested role results successfully applied, queried, and matched.
  - **`false`:** at least one required requested role failed or did not match.
  - **`null`:** required affinity not requested or cannot be established.
- **Per-role reporting:** requested, set applied, query succeeded, matched, error, strict failure/enforcement consequence; role applicability/requirement by actual topology.
- **Topology/architecture role requirements:** distributed policies (`fixed_faa`, `local_adaptive`, `relative_adaptive`) require ingestor + consumer per configured logical node. `centralized_ingest` requires its single ingestor (central/selected node, node 0) + all configured consumers; other nodes' nonexistent ingestor roles are **not applicable** (not failures). `--no-pin` does not claim verified affinity (factual result `null` where roles not requested). Strict affinity still aborts/fails run on required failure; non-strict may complete but factual affinity remains false/unknown as appropriate.
- **Tests:** helper-level factual tri-state and independence from strictness; no-pin => unknown; centralized vs distributed role requirements; engine-level affinity failure in strict mode aborts/fails run with factual false; engine-level affinity failure in non-strict mode reports factual false.

## 4. P0 — Memory-policy (mbind) validity factual per-attempt accounting

- **Finding addressed:** prior booleans could not represent mixed requested outcomes and non-strict validity could hide failures.
- **Correction (C engine):** per-node per-attempt tracking across all allocation attempts where policy requested: `mbind_requested_count`, `mbind_success_count`, `mbind_failure_count`; actual error information preserved (not erased by later success). Compatibility fields: `mbind_policy_requested` = any requested; `mbind_policy_applied` = **all requested applications succeeded and >=1 requested** (not merely any).
- **Factual validity (independent of `--strict-mbind`):**
  - **`true`:** >=1 policy application required/requested and every requested application succeeded.
  - **`false`:** >=1 requested application failed.
  - **`null`:** no policy application requested or cannot be established.
- **Semantics preserved:** `mbind` syscall application is distinct from observed physical placement and from `MPOL_PREFERRED` mismatch (preferred success not physical locality proof). Strict mbind controls enforcement/abort, not factual reporting.
- **Tests:** no-request case (engine direct), all-success/mixed/all-failed/no-request factual helpers, strict and non-strict produce identical factual validity classifications.

## 5. P0 — Combined validity classifications

- **Separate dimensions (tri-state where applicable):** functional correctness, performance-measurement, affinity, memory-policy application, placement observed, overall NUMA-placement. `unknown` distinct from `false`; strict flags affect enforcement only.
- **Rules applied:** requested affinity failure must not yield `affinity_valid=true`; requested mbind failure must not yield memory-policy validity true; unknown/unrequested affinity or policy not promoted to verified; observed placement mismatch remains false; `numa_placement=true` requires verified required affinity, successful required policy application, and positive placement observations. Field meanings documented in `DIST_RESULT.placement_semantics`/validity.
- **Report:** does not equate `manifest.complete`/functional correctness with all validity; surfaces per-dimension validity and supports different conclusions per trial.

## 6. P0 — Strict physical-NUMA campaign configuration

- **Campaign driver:** `run_dist_campaign.sh` exposes `--strict-affinity`, `--strict-mbind`, `--consumer-kernel`, and documented `--phys-nodes` selection. Explicit per-comparable-candidate spec records strict/kernel/phys settings; `run_case.py` forwards to `run_dist.py`; settings recorded in specs, manifests/`DIST_RESULT` provenance, campaign manifest config, and report. Identical per comparison block. No silent fallback from requested strict settings (strict failures surface as trial/run failures or invalidity per enforcement/validity semantics).
- **Phys-node note:** explicit physical-node mapping must be compatible with scenario node counts; incompatible application is not silently applied (runner/topology validation rejects).
- **Recipe:** `RENTAL_RECIPE.md` updated with verified strict one-command example and labeling (local quick-smoke may remain non-strict but labeled).

## 7. P1 — Report timing and trial denominators

- **Dist-engine wall time:** comparative/report uses `DIST_RESULT.wall_seconds` as authoritative engine wall time; outer harness duration (`manifest.wall_s`) retained separately/diagnostic. Production references continue to use their existing timing source (not combined into purportedly comparable field).
- **Valid/total denominators:** every attempted candidate/trial represented in relevant group regardless of status or manifest availability (failed, missing manifest, unreadable manifest, incomplete included); denominator counts attempted trials, not only readable successful manifests.
- **Tests:** successful complete, failed, missing manifest, unreadable manifest, incomplete, and mixture cases covered (`tests/test_report_dist.py`).

## 8. P1 — Report validity dimensions and workload evidence

- **Surfaced (dist trials):** functional correctness, performance-measurement, affinity, memory-policy application, placement observed, overall NUMA-placement; `unknown` shown distinctly from `false`. Consumer kernel configuration and scan-byte evidence included so measured workload is visible.

## 9. Documentation and schema/provenance

- **Updated:** `CLOSEOUT.md`, `RENTAL_RECIPE.md` (final verified execution path, strict campaign command, actual validity semantics). `DIST_RESULT`/campaign schema fields extended with factual validity dimensions, mbind counts, consumer kernel/scan evidence, and campaign config recording (backward-compatible aliases retained where applicable).

## 10. Validation

- **Normal suites (this checkout, rebuilt .so):**
  - `python3 -m unittest discover -s stage0/dist_ingest/tests -v` → **114/114 OK**
  - `python3 -m unittest stage0.tests.test_stage0` → **81/81 OK**
  - `python3 -m unittest python.tests.test_numa_drain_guard` → **7/7 OK**
- **ASan + UBSan runtime (instrumented dist-ingest suite):** **114/114 OK**
  - Build: `gcc -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -fPIC -shared -o stage0/libdist_ingest.so stage0/dist_ingest/dist_ingest.c -lpthread -lm -lnuma` (gcc 16.2.1)
  - Run: `LD_PRELOAD=/lib64/libasan.so.8:/lib64/libubsan.so.1 ASAN_OPTIONS=detect_leaks=0:halt_on_error=1:allocator_may_return_null=1 UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1 python3 -m unittest discover -s stage0/dist_ingest/tests -v` → OK, exit 0
  - **Note:** `detect_leaks=0` (not a leak-sanitizer pass)
- **TSan runtime (instrumented dist-ingest suite):** **114/114 OK**
  - Build: `gcc -O1 -g -fno-omit-frame-pointer -fsanitize=thread -fPIC -shared -o stage0/libdist_ingest.so stage0/dist_ingest/dist_ingest.c -lpthread -lm -lnuma` (gcc 16.2.1)
  - Run: `LD_PRELOAD=/lib64/libtsan.so.2 TSAN_OPTIONS=halt_on_error=1:history_size=7 python3 -m unittest discover -s stage0/dist_ingest/tests -v` → OK, exit 0
- **Added deterministic coverage:** active/inactive consumer kernels and all four common-engine policies with exact scan-byte evidence; affinity factual validity (helpers, no-pin/unrequested, centralized vs distributed roles, strict abort with factual false, non-strict factual false); mbind no-request/all-success/mixed/all-failed factual helpers and strict/non-strict identical factual classification; combined validity constraints; campaign explicit kernel/strict spec forwarding and end-to-end kernel-reaching-C-engine smoke; report timing boundaries, failed/missing/unreadable/incomplete denominators, per-dimension validity with unknown distinct from false.

## 11. Scope boundaries (honored)

- No redo of centralized-ingest architecture; no replacement of existing common-engine design.
- No modification of frozen production files.
- No pipe-ingestion candidates, no production adoption, no NUMA-ingest redesign, no physical-NUMA rental.
- No weakening/removal of existing validation.
- Synthetic consumer not claimed equivalent to production worker pipeline.
- `MPOL_PREFERRED` success not claimed as physical locality proof.

## 12. Remaining limitations

- No physical multi-node NUMA validation; fake/local results not evidence of physical locality/scaling/remote penalties.
- `mbind(MPOL_PREFERRED)` syscall success and placement sampling observations are not physical placement proof; unknown remains unknown.
- Hugepage-success accounting not proven on this host.
- ASan validation used `detect_leaks=0` (no leak-sanitizer claim).
- Extreme `SSIZE_MAX`/`off_t` boundary cases not exhaustively exercised end-to-end beyond guards/tests.
- Pipe ingestion excluded from dist-candidate bake-off.

## 13. Readiness / confirmation

- **Physical-NUMA campaign driver readiness (for planned rental characterization):** campaign now executes the claimed workload by default with scan-byte proof, and validity/reporting machinery does not promote failed/unknown NUMA evidence to success. **Conditionally ready** for physical-NUMA characterization subject to preflight/strict settings on real (non-fake) multi-node hardware and documented validity/comparability limits.
- **Not implied:** production adoption readiness or production end-to-end speedup.
- **Confirmation:** no physical-NUMA rental or production adoption was started.
