# Physical-NUMA Rental Recipe — Distributed Ingestion Prototype (Corrected, Rental-Ready Closeout)

**Purpose:** run one physical multi-node NUMA campaign to compare **comparable dist-engine candidates** (in-engine centralized control baseline and distributed policies) using the corrected prototype suite. No rental is performed by this repository.

## Comparable candidates (same engine/consumers/work units/measurement)

Run these on the **same experimental `dist_ingest` engine** with identical simulated per-node consumers, byte-range reservation/chunk work units, `di_run` measurement boundaries, and **identical consumer kernel/params** per comparison block:

- `centralized_ingest` — in-engine centralized control baseline (single ingestor distributes to all node queues)
- `fixed_faa` — distributed per-node FAA claiming (fixed quantum)
- `local_adaptive` — distributed per-node claiming (local headroom)
- `relative_adaptive` — distributed per-node claiming (relative headroom)

`production_ref` (existing forkrun pipeline), if run, is a **separate reference only** and must **not** be compared apples-to-apples to dist-engine candidates (different execution/measurement model).

## Prerequisites (hardware / kernel / NUMA)

- Physical machine with **>= 2 NUMA nodes** with memory and CPUs on each node (**not** `numa=fake`). Verify:
  - `numactl -H` shows multiple nodes with CPUs and memory.
  - `cat /sys/devices/system/node/online` lists >= 2 nodes.
  - Kernel cmdline does **not** include `numa=fake=`.
- Linux with `libnuma` userspace/runtime as needed, standard build tools (`gcc`, `make`, `python3`, `git`).
- Sufficient RAM for corpora and concurrent buffers (recommend >= 32 GiB for default scenarios; more for large-node-count runs).
- Sufficient disk for corpora + raw artifacts (recommend >= 20 GiB free).
- Ability to set/verify CPU/memory affinity/policy and observe `/proc`, `/sys`.

## Preflight (required before reportable/decision-grade runs)

```bash
set -euo pipefail
git rev-parse HEAD
git status --porcelain  # must be clean for reportable runs
numactl -H
cat /sys/devices/system/node/online
grep . /proc/cmdline
python3 --version; gcc --version
```

Build:
```bash
make -f Makefile.substrate python-substrate || true
(cd stage0/dist_ingest && make)
```

Environment capture:
```bash
python3 stage0/env_capture.py --out /tmp/env-pre.json --run-id preflight
```

## Scenario profiles, minimum node counts, and topology compatibility

The campaign driver validates selected scenario IDs and node counts against topology/mapping **before executing timed trials**. If `--scenarios` is explicitly supplied, unknown scenario IDs and duplicate scenario IDs are rejected before timed trials (even when other requested IDs are valid), and prevalidation/provenance/execution-plan agree on the selected scenario set. Candidate selection (`--candidates`) is likewise validated before build/timed-trial manifests (nonempty, recognized, no duplicates); `--trials`/`--seed`/`--shuffle-scenarios` are part of the validated execution plan and `--plan-only` reports the same plan an actual campaign would execute. If a selected scenario cannot be satisfied by the selected hardware/mapping, the campaign fails before timed trials with a clear diagnostic (it must not begin a campaign containing scenarios the selected hardware cannot support, and unsupported scenarios are never marked successful).

**Mapping-profile selection for physical NUMA:** `--mapping-profiles auto` preserves the **legacy** first-N-usable-nodes selection and is **not** topology-aware experimental coverage. For physical-NUMA rental/decision-grade runs, use an explicit topology-aware mapping-profile selection — normally `--mapping-profiles matrix` (or an explicit topology-aware profile subset such as `cross_socket_spread,intra_socket,all_nodes`) — so concrete mappings are topology-derived, validated, and recorded with mapping provenance. Do not silently rely on legacy `auto` for physical-NUMA experimental coverage. Unsupported mappings are reported explicitly and never substituted.

### Documented executable profiles (default/non-quick scenario set)

| Profile | Minimum usable NUMA nodes | Scenarios (logical node counts) | Exact `--scenarios` invocation |
|---|---:|---|---|
| **2-node** (`nodes2`) | 2 | `nodes2`(2), `small`(2), `tiny`(2) | `--scenarios nodes2,small,tiny` |
| **4-node** (`nodes4`) | 4 | four-node + compatible two-node: `equal`(4), `slow_one`(4), `fast_one`(4), `asymmetric`(4), `stall_recover`(4), `nodes2`(2), `large_seq`(4), `small`(2), `tiny`(2), `boundary`(4), `backpressure`(4); excludes `nodes8` | `--scenarios equal,slow_one,fast_one,asymmetric,stall_recover,nodes2,large_seq,small,tiny,boundary,backpressure` |
| **Full** (`full`) | 8 | default full scenario set (includes `nodes8`(8)), subject to topology validation | `--scenarios equal,slow_one,fast_one,asymmetric,stall_recover,nodes2,nodes8,large_seq,small,tiny,boundary,backpressure` (or omit `--scenarios` to select all default scenarios) |

Convenience: `--profile nodes2|nodes4|full` sets the corresponding scenario selection unless `--scenarios` is explicitly provided.

### `--phys-nodes` compatibility rules (explicit physical-node mapping)

- `--phys-nodes <comma-separated-ids>` selects explicit physical NUMA nodes in logical order. A **single `--phys-nodes` list cannot map scenarios having different logical-node counts**.
- **Explicit mappings are validated during preflight using `run_dist.resolve_topology()` with the same mapping and pinning semantics as trials** (not just count/list-shape checks). Raw list syntax is validated first: leading/trailing/consecutive commas, empty elements, and non-integer elements are rejected before build/trial setup (ordinary whitespace around valid integer IDs is allowed). Topology validation then rejects duplicate IDs, offline/unknown IDs, nodes outside allowed memory-node set, no/indeterminate memory, missing/unparsable CPU lists, nodes without allowed CPUs when pinning is required, and any mapping `resolve_topology()` cannot establish.
- **Explicit-mapping campaigns are restricted to scenarios whose logical node count equals the number of nodes in `--phys-nodes`.** If any selected scenario's node count does not match, the campaign is rejected **before timed trials** with a clear diagnostic.
- Therefore, a mixed-count profile (e.g. the 4-node profile contains 2-node and 4-node scenarios) **cannot** be run with one explicit `--phys-nodes` list. To use explicit mapping, select only scenarios with a matching node count (e.g. only 4-node scenarios with `--phys-nodes` of length 4, or only 2-node scenarios with length 2), or use **automatic topology selection** (no `--phys-nodes`).
- **Automatic topology selection** may support the default mixed-count campaign/profile when enough usable nodes exist (each selected scenario's node count must be <= available usable nodes discovered on the host); the driver validates this before timed trials.
- Campaign provenance records (distinct concepts): requested vs effective scenario profile/selection (explicit `--scenarios` override recorded as custom, not as requested profile), actual usable nodes discovered on the host, explicit physical-node IDs/selection count, selected scenario logical node counts, selected scenarios, and physical-node mapping/validation details.

## Exact campaign examples

### 2 usable NUMA nodes (2-node profile)

```bash
TRIALS=3 bash stage0/dist_ingest/run_dist_campaign.sh \
  --out stage0/dist_ingest/runs/<campaign-id-2n> \
  --campaign-id <campaign-id-2n> \
  --scenarios nodes2,small,tiny \
  --mapping-profiles matrix \
  --candidates centralized_ingest,fixed_faa,local_adaptive,relative_adaptive \
  --consumer-kernel full_byte_scan \
  --strict-affinity \
  --strict-mbind
```

### 4 usable NUMA nodes (4-node profile, automatic mixed-count selection)

```bash
TRIALS=3 bash stage0/dist_ingest/run_dist_campaign.sh \
  --out stage0/dist_ingest/runs/<campaign-id-4n> \
  --campaign-id <campaign-id-4n> \
  --scenarios equal,slow_one,fast_one,asymmetric,stall_recover,nodes2,large_seq,small,tiny,boundary,backpressure \
  --mapping-profiles matrix \
  --candidates centralized_ingest,fixed_faa,local_adaptive,relative_adaptive \
  --consumer-kernel full_byte_scan \
  --strict-affinity \
  --strict-mbind
```

If using explicit `--phys-nodes` on a 4-node host, select only scenarios whose node count matches the list length (example: 4-node scenarios with 4 explicit nodes). Explicit `--phys-nodes` provides a concrete physical mapping (validated via the authoritative topology path); mapping-profile matrix expansion is not used in that explicit-mapping form:

```bash
TRIALS=3 bash stage0/dist_ingest/run_dist_campaign.sh \
  --out stage0/dist_ingest/runs/<campaign-id-4n-explicit> \
  --campaign-id <campaign-id-4n-explicit> \
  --scenarios equal,slow_one,fast_one,asymmetric,stall_recover,large_seq,boundary,backpressure \
  --candidates centralized_ingest,fixed_faa,local_adaptive,relative_adaptive \
  --consumer-kernel full_byte_scan \
  --strict-affinity \
  --strict-mbind \
  --phys-nodes <id0>,<id1>,<id2>,<id3>
```

### 8 or more usable NUMA nodes (full profile)

```bash
TRIALS=3 bash stage0/dist_ingest/run_dist_campaign.sh \
  --out stage0/dist_ingest/runs/<campaign-id-full> \
  --campaign-id <campaign-id-full> \
  --mapping-profiles matrix \
  --candidates centralized_ingest,fixed_faa,local_adaptive,relative_adaptive \
  --consumer-kernel full_byte_scan \
  --strict-affinity \
  --strict-mbind
```

(Full profile includes `nodes8` and runs subject to topology validation; on hosts with fewer than 8 usable nodes, select a compatible profile/scenario set instead.)

### Local quick-smoke (non-strict, labeled; not a documented rental profile and not for physical-NUMA decisions)

```bash
bash stage0/dist_ingest/run_dist_campaign.sh \
  --quick \
  --out stage0/dist_ingest/runs/<campaign-id-quick> \
  --campaign-id <campaign-id-quick> \
  --candidates centralized_ingest,fixed_faa,local_adaptive,relative_adaptive \
  --trials 1
```

Quick-smoke defaults/scenario subset are not decision-grade for NUMA placement/performance conclusions and must be labeled accordingly.

## Placement/affinity/policy (strict/verified for NUMA conclusions)

- Resolve and record topology and logical→physical node mapping (sparse IDs allowed). Use `--phys-nodes` only when compatible with every selected scenario's node count (see compatibility rules above).
- For NUMA-performance/placement conclusions, request CPU affinity and memory policy and use `--strict-affinity` and/or `--strict-mbind` so runs fail when required affinity or mbind policy application cannot be established. **Strictness controls enforcement/abort, not factual validity reporting.**
- Validity/reporting is factual and tri-state. Failed or unknown NUMA evidence must not be promoted to success.
- **`mbind(MPOL_PREFERRED)` syscall success is not physical placement proof.** Placement is observation-based and reported separately (unknown remains unknown).
- Record kernel cmdline, CPU governor/frequency info where available, THP/mempolicy, and any cpuset/cgroup restrictions.

Verify corpus hashes and input immutability for timed trials.

## Validity semantics (corrected)

### Per-node affinity effective verification (tri-state, corrected)

`affinity.effective_verified` is tri-state over **applicable, required roles**:
- `true`: every applicable, required role is requested, applied, queried, and matched.
- `false`: at least one applicable, required role was requested but failed, could not be queried, or did not match.
- `null` (unknown/not applicable): at least one applicable, required role is unknown/unrequested and none failed; or the set of applicable required roles is empty (not applicable).
- Roles with `required=false` are not applicable and must not make the result unknown.

Architecture-specific required roles:
- **Distributed candidates:** ingestor and consumer on each configured node.
- **Centralized ingestion:** the single ingestor on node 0 and each configured consumer. Other nodes' ingestor roles are not applicable.

`--no-pin` means required affinity is not requested/verified (unknown), not true. No field may claim affinity verification when a required role is unknown.

Run-level factual affinity validity remains tri-state and independent of strict enforcement (strictness controls abort/enforcement, not truth).

### Performance-valid vs functionally-correct trials

- **Functionally correct:** run completed without overlap/loss/dup/input mutation and totals/rc indicate correctness as defined by the engine/result.
- **Performance-measurement valid (factual, tri-state):** requires functional correctness and evidenced consumer workload and required affinity/perf evidence as applicable.
  - `full_byte_scan`: scan-byte evidence must be accounted and `scan_equals_consumed` must be true for performance validity to be true; a false/incomplete scan result makes performance validity false; missing/indeterminate scan evidence makes performance validity unknown unless another independent failure already makes it false.
  - `none`: explicit diagnostic opt-out (not the default comparison workload). Scanned bytes must be zero for evidence-valid `none`; nonzero scanned bytes make performance validity false; missing evidence makes it unknown unless another independent failure makes it false. `none` results must not be combined with full-byte-scan results into one comparable campaign summary.
- **Headline performance reporting:** throughput, engine wall-time, and other performance summary medians use **performance-valid trials only** (trials with false or unknown performance validity are excluded from headline performance statistics). Functionally-correct but performance-invalid/unknown trials are retained in the detailed report with raw throughput and validity reasons and must not be discarded. If there are no performance-valid trials, the report makes this obvious and does not silently substitute functional correctness.
- **Separate counts:** attempted trials, complete/functionally correct trials, performance-valid trials, and NUMA-placement-valid trials are reported separately.

### Other validity dimensions (factual, tri-state)

Functional correctness, performance-measurement, affinity, memory-policy application, placement observed, and overall NUMA-placement are separate dimensions (`true`/`false`/`null`). `unknown` is distinct from `false`. `manifest.complete`/functional correctness is not all-validity.

## Campaign options

- `--quick` small local smoke (not for physical-NUMA decisions; not a documented rental profile).
- `--profile nodes2|nodes4|full` convenience scenario profile (sets `--scenarios` unless explicit). `--profile nodes2/nodes4` describe the non-quick scenario set and are rejected with `--quick`; `--profile full --quick` is supported and provenance records requested/effective profile and `profile_quick` unambiguously for the resulting quick selection.
- `--mapping-profiles <csv|matrix|all>` mapping-profile selection (e.g. `cross_socket_spread,intra_socket,all_nodes`, or `matrix`/`all` to expand topology-aware coverage per scenario). **Physical-NUMA rental must use an explicit topology-aware selection, normally `--mapping-profiles matrix`.** `--mapping-profiles auto` is legacy first-N-usable-nodes selection (not topology-aware experimental coverage) and must not be the silent default for physical-NUMA experimental coverage.
- `--scenarios <csv>` / `--candidates <csv>` to subset (explicit `--scenarios` rejects unknown and duplicate IDs before timed trials; candidates are validated before build/timed-trial manifests as nonempty, recognized, and non-duplicate).
- `--trials N` (>=3 recommended for decisive cases).
- `--seed SEED` deterministic random seed for reproducible candidate/scenario ordering.
- `--shuffle-scenarios` randomize scenario/mapping-block order (reproducible by seed).
- `--cache-policy TEXT` legacy explicit cache/warm-up assumption recorded in manifest (prefer `--cache-precondition-policy`).
- `--cache-precondition-policy best_effort_os_cache|warm_repeat|drop_caches_if_privileged` C3 attributable cache-preconditioning policy. Actions/outcomes/fallbacks are recorded factually per case and surfaced in report; `drop_caches_if_privileged` records success/failure and does not claim cold-cache control unless it succeeded.
- `--min-duration-seconds N` C3 duration-qualification target (seconds, finite >= 0). The harness repeats short dist-engine measurements (bounded) until accumulated effective duration meets target or cap is reached; recorded factually per trial as a separate axis (`meets_target`, passes, accumulated). C3-corrections-2: qualification uses the single authoritative decision `_dist_pass_qualified` (process success, not timed out, valid parseable `DIST_RESULT`, dist rc 0, `correct` true, valid engine `wall_seconds`) — failed/timed-out passes contribute nothing and harness wall time is not substituted; per-pass records carry full evidence (rc, timeout, `DIST_RESULT`, functional correctness, performance validity, wall, consumed/scanned bytes, reservations, cache outcome, cleanup). Repetition is bounded by pass-count cap and `min_duration_repetition_budget_s` (default `max(30, 10*target)`), per-pass timeout `min(case timeout, remaining budget)`, and stops after the first unsuccessful pass. Cache preconditioning is applied per pass with recorded outcomes; materially different cache treatments are not silently combined (conservative compatibility rule). `duration_aggregate` (T/B/scan/reservations sums, throughput_agg, validity) is recorded separately; report uses it for repeated trials (headline throughput/wall/reservations/scan-consumed and perf-valid eligibility; pass 1 stays provenance) and reports invalid aggregates explicitly. The wall-clock budget is recalculated after each pass's cache preconditioning, and an initially cache-incompatible pass stops repetition even when it already reached the target.
- `--sweep-base-quantum LIST` / `--sweep-max-backlog LIST` / `--sweep-max-reservation LIST` C3 parameter sweeps (comma-separated positive integers). Cartesian-product parameter sets are planned/executed/reported as attributable `parameter_set_id` values; do not mix results across parameter sets.
- `--consumer-kernel full_byte_scan|none` workload kernel (default `full_byte_scan`; explicitly written per comparable candidate spec).
- `--strict-affinity` / `--strict-mbind` strict enforcement (abort on required failure); recorded in specs/manifests/campaign config and reported alongside factual validity.
- `--phys-nodes LIST` explicit physical NUMA node ids; must be compatible with every selected scenario's logical node count (count match required) or the campaign is rejected before timed trials.

**Randomization/fairness:** candidate order is shuffled within each (scenario,mapping,parameter-set,trial) block using the recorded seed; actual execution order and plan are recorded in `campaign-manifest.json`/`execution-order.jsonl`/`execution-plan.json`. Re-running into an existing case/trial directory does not overwrite earlier raw evidence.

**Cache assumptions:** default policy is `best_effort_os_cache` (no privileged cold-cache control). `warm_repeat` performs factual pre-measurement reads. `drop_caches_if_privileged` attempts a privileged drop and records factual fallback when unavailable. Do not claim cache-controlled comparisons unless cache state was actually controlled.

## Expected runtime and disk

- **Quick smoke:** ~1–5 minutes, < 300 MB.
- **Full/default campaigns:** estimate **30–90 minutes** on typical hardware (calibrate with `--quick`); profile and host-dependent. Budget margin for physical-NUMA runs.
- **Disk:** corpora + per-trial manifests/logs/JSON. Reserve >= 20 GiB.

## Artifact collection

Retain the entire campaign directory:
- `campaign-manifest.json`, `execution-order.jsonl`, `execution-plan.json`, `prevalidation.json`, `report.md`
- `env/env-before.json`, `env/env-after.json`
- `cases/<case>/trialN/manifest.json`, `stderr.log`, `stdout.log`, `spec.json`, `dist-result.json` (when emitted)
- `corpora/*` (or record hashes)

Copy off the host before teardown:
```bash
tar czf dist-campaign-artifacts.tgz stage0/dist_ingest/runs/<campaign-id>
```

## Recovery / retry

- Campaign directories should be treated as immutable evidence. If a case/trial directory already contains `manifest.json`, the driver skips it to avoid overwriting raw evidence.
- Rerun into a **new** `--out/--campaign-id` for clean comparative blocks; record the new SHA/seed.
- Inspect `report.md`, failed trial manifests/logs, and `campaign-manifest.json` for invalid/incomplete flags and per-dimension validity.

## Interpretation

- **Comparable set:** `centralized_ingest` vs `fixed_faa`/`local_adaptive`/`relative_adaptive` on the same dist_ingest engine/consumers/work units/measurement boundaries with identical consumer kernel/params per comparison block.
- **Workload evidence:** default comparison workload is `full_byte_scan` (memory-touch) with scan-byte evidence reported; `none` runs must not be confused with or combined into default comparisons.
- **Timing:** dist-engine authoritative wall time is `DIST_RESULT.wall_seconds`; harness/manifest duration is separate and diagnostic.
- **Reference only:** `production_ref`/forkrun uses a different execution model (not apples-to-apples).
- **Validity is multi-dimensional (factual, tri-state):** performance-valid vs functionally-correct are distinct; headline performance medians exclude false/unknown performance validity. `unknown` is distinct from `false`.
- **Affinity:** per-node `effective_verified` is tri-state over applicable required roles (unknown required role is never reported as verified). Role requirements depend on actual topology (`centralized_ingest`: single ingestor on central node + all consumers; other ingestor roles N/A).
- **Memory policy vs placement:** mbind requested/succeeded/failed counts and factual application validity are distinct from observed placement; `MPOL_PREFERRED` success is not physical placement proof.
- **Telemetry:** `DIST_RESULT` is authoritative for dist-engine measurements.
- **Correctness first:** overlap/loss/dup, wrong totals, or input mutation invalidate functional correctness.
- **Not proven here:** fake/local NUMA does not establish physical CPU/memory locality, remote-memory penalties, multi-socket scaling, or production end-to-end speedup. Hugepage-success accounting is not proven on hosts without hugepage availability.
- Pipe ingestion excluded from dist-candidate bake-off (see `PIPE_INGESTION.md`).
