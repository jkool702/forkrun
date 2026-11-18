# Physical-NUMA Rental Recipe — Distributed Ingestion Prototype (Corrected)

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

### Placement/affinity/policy (strict/verified for NUMA conclusions)

- Resolve and record topology and logical→physical node mapping (sparse IDs allowed). Use `--phys-nodes` for explicit selection when appropriate; it must be compatible with scenario node counts (no silent incompatible application).
- For NUMA-performance/placement conclusions, request CPU affinity and memory policy and use `--strict-affinity` and/or `--strict-mbind` so runs fail when required affinity or mbind policy application cannot be established. **Strictness controls enforcement/abort, not factual validity reporting.**
- Validity/reporting is factual and tri-state: affinity, memory-policy application, placement observed, and overall NUMA-placement are reported independently (`true`/`false`/`null` = unknown/unrequested/not established). Failed or unknown NUMA evidence must not be promoted to success.
- **`mbind(MPOL_PREFERRED)` syscall success is not physical placement proof.** Placement is observation-based and reported separately (unknown remains unknown).
- Record kernel cmdline, CPU governor/frequency info where available, THP/mempolicy, and any cpuset/cgroup restrictions.

Verify corpus hashes and input immutability for timed trials.

## One-command campaign invocation

### Verified strict physical-NUMA characterization example (recommended for decision-grade runs)

From a clean checkout at the measured commit on real (non-fake) multi-node hardware:

```bash
TRIALS=3 bash stage0/dist_ingest/run_dist_campaign.sh \
  --out stage0/dist_ingest/runs/<campaign-id> \
  --campaign-id <campaign-id> \
  --candidates centralized_ingest,fixed_faa,local_adaptive,relative_adaptive \
  --consumer-kernel full_byte_scan \
  --strict-affinity \
  --strict-mbind
```

This explicitly records/wires `consumer_kernel=full_byte_scan` (default, memory-touch, scan-byte evidenced) and strict affinity/memory-policy enforcement for every comparable dist-engine candidate spec in each comparison block. If required strict settings cannot be established, trials fail (no silent fallback to non-strict).

### Local quick-smoke (non-strict, labeled; not for physical-NUMA decisions)

```bash
bash stage0/dist_ingest/run_dist_campaign.sh \
  --quick \
  --out stage0/dist_ingest/runs/<campaign-id> \
  --campaign-id <campaign-id> \
  --candidates centralized_ingest,fixed_faa,local_adaptive,relative_adaptive \
  --trials 1
```

Quick-smoke defaults are not decision-grade for NUMA placement/performance conclusions and must be labeled accordingly by reports/validity dimensions.

### Options

- `--quick` small local smoke (not for physical-NUMA decisions).
- `--scenarios <csv>` / `--candidates <csv>` to subset.
- `--trials N` (>=3 recommended for decisive cases).
- `--seed SEED` deterministic random seed for reproducible candidate/scenario ordering.
- `--shuffle-scenarios` randomize scenario-block order (reproducible by seed).
- `--cache-policy TEXT` explicit cache/warm-up assumption recorded in manifest.
- `--consumer-kernel full_byte_scan|none` workload kernel (default `full_byte_scan`; explicitly written per comparable candidate spec). `none` is diagnostic opt-out only, not the default comparison workload.
- `--strict-affinity` / `--strict-mbind` strict enforcement (abort on required failure); recorded in specs/manifests/campaign config and reported alongside factual validity.
- `--phys-nodes LIST` explicit physical NUMA node ids (documented; must be compatible with scenario node counts).

**Randomization/fairness:** candidate order is shuffled within each (scenario,trial) block using the recorded seed; actual execution order and plan are recorded in `campaign-manifest.json`/`execution-order.jsonl`/`execution-plan.json`. Re-running into an existing case/trial directory does not overwrite earlier raw evidence.

**Cache assumptions:** by default recorded as best-effort OS cache (no privileged cold-cache control). Do not claim cache-controlled comparisons unless cache state was actually controlled.

## Expected runtime and disk

- **Quick smoke:** ~1–5 minutes, < 300 MB.
- **Full local/default file campaign (4 dist-engine candidates × default scenarios × trials):** estimate **30–90 minutes** on typical hardware (calibrate with `--quick`). Budget margin for physical-NUMA runs.
- **Disk:** corpora + per-trial manifests/logs/JSON. Reserve >= 20 GiB.

## Artifact collection

Retain the entire campaign directory:
- `campaign-manifest.json`, `execution-order.jsonl`, `execution-plan.json`, `report.md`
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
- **Workload evidence:** default comparison workload is `full_byte_scan` (memory-touch) with per-node/aggregate `consumer_bytes_scanned` evidence reported; `none` runs must not be confused with default comparisons.
- **Timing:** dist-engine authoritative wall time is `DIST_RESULT.wall_seconds`; harness/manifest duration is separate and diagnostic.
- **Reference only:** `production_ref`/forkrun uses a different execution model (not apples-to-apples).
- **Validity is multi-dimensional (factual, tri-state):** functional correctness, performance-measurement, affinity, memory-policy application, placement observed, and overall NUMA-placement are separate dimensions (`true`/`false`/`null`). A trial may be valid for one purpose and invalid/unknown for another. `unknown` is distinct from `false`. `manifest.complete`/functional correctness is not all-validity.
- **Affinity:** role requirements depend on actual topology (`centralized_ingest`: single ingestor on central node + all consumers; other ingestor roles N/A). `--no-pin` means affinity not verified.
- **Memory policy vs placement:** mbind requested/succeeded/failed counts and factual application validity are distinct from observed placement; `MPOL_PREFERRED` success is not physical placement proof.
- **Telemetry:** `DIST_RESULT` is authoritative for dist-engine measurements; no fabricated STAGE0 time-series samples emitted for dist candidates.
- **Correctness first:** overlap/loss/dup, wrong totals, or input mutation invalidate functional correctness.
- **Not proven here:** fake/local NUMA does not establish physical CPU/memory locality, remote-memory penalties, multi-socket scaling, or production end-to-end speedup. Hugepage-success accounting is not proven on hosts without hugepage availability.
- Pipe ingestion excluded from dist-candidate bake-off (see `PIPE_INGESTION.md`).
