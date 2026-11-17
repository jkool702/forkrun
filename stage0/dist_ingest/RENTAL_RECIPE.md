# Physical-NUMA Rental Recipe — Distributed Ingestion Prototype Bake-off

**Purpose:** run one physical multi-node NUMA campaign to compare the existing centralized control against `fixed_faa`, `local_adaptive`, and `relative_adaptive` using the prepared prototype suite. No rental is performed by this repository.

## Prerequisites (hardware / kernel / NUMA)

- Physical machine with **>= 2 NUMA nodes** with memory and CPUs on each node (not `numa=fake`). Verify:
  - `numactl -H` shows multiple nodes with CPUs and memory.
  - `cat /sys/devices/system/node/online` lists >= 2 nodes.
  - Kernel cmdline does **not** include `numa=fake=`.
- Linux with `libnuma` userspace (`numactl`, headers/runtime as needed), standard build tools (`gcc`, `make`, `python3`, `git`).
- Sufficient RAM for corpora and concurrent buffers (recommend >= 32 GiB for default scenarios; more for large-node-count runs).
- Sufficient disk for corpora + raw artifacts (recommend >= 20 GiB free; large corpora dominate).
- Ability to set CPU/memory affinity/policy (`numactl`, cpusets) and observe `/proc`, `/sys`.

## Preflight (before timing the campaign)

```bash
set -euo pipefail
git rev-parse HEAD
git status --porcelain  # must be clean for reportable runs
numactl -H
cat /sys/devices/system/node/online
grep . /proc/cmdline
python3 --version; gcc --version
```

Build prerequisites:
```bash
make -f Makefile.substrate python-substrate
(cd stage0/dist_ingest && make)
# optional: build stage0 shims/tools used by existing campaign pieces
gcc -O2 -shared -fPIC -o stage0/libstage0.so stage0/residency_shim.c -lnuma || true
```

Environment capture:
```bash
python3 stage0/env_capture.py --out /tmp/env-pre.json --run-id preflight
```

Confirm placement/affinity for the run (pin the campaign process as desired, e.g. `numactl --cpunodebind=... --membind=...` or leave default but record policy). Record THP/governor settings.

## One-command campaign invocation

From a clean checkout at the measured commit:

```bash
TRIALS=3 bash stage0/dist_ingest/run_dist_campaign.sh \
  --out stage0/dist_ingest/runs/<campaign-id> \
  --campaign-id <campaign-id>
```

Options:
- `--quick` for a short local smoke (not for physical-NUMA decisions).
- `--scenarios <csv>` / `--candidates <csv>` to subset.
- `--trials N` (>=3 recommended for decisive cases).

The driver: builds dist lib, captures env, generates corpora, runs all selected scenarios × candidates × trials (interleaved by loop order), keeps raw manifests/logs/results, writes `campaign-manifest.json` and `report.md`, and exits non-zero if any trial fails (while recording all outcomes).

## Expected runtime and disk

- **Quick smoke:** ~1–3 minutes, < 200 MB (small corpora, few cases).
- **Full local/default file campaign:** depends on host and corpus sizes (default large corpus 256 MiB in non-quick mode × 12 scenarios × 4 candidates × trials). Estimate **20–60 minutes** on a typical dev host; on rental hardware allow **30–90 minutes** plus margin. Run a quick pass first to calibrate: `--quick`.
- **Disk:** corpora (hundreds of MB default) + per-trial manifests/logs/JSON (tens to hundreds of MB). Reserve >= 20 GiB.

Increase corpus sizes or trial counts only with corresponding runtime/disk budget adjustments.

## Artifact collection

Retain the entire campaign directory:
- `campaign-manifest.json`, `report.md`
- `env/env-before.json`, `env/env-after.json`
- `cases/<case>/trialN/manifest.json`, `stderr.log`, `stdout.log`, `spec.json`
- `corpora/*` (or record hashes if regenerated identically)

Copy off the host before teardown:
```bash
tar czf dist-campaign-artifacts.tgz stage0/dist_ingest/runs/<campaign-id>
```

## Recovery / retry

- Campaign directories are immutable (non-empty dirs refused). On failure, inspect `report.md`, failed trial manifests/logs, and `campaign-manifest.json`.
- Rerun into a **new** `--out/--campaign-id`. Do not edit prior artifacts.
- If a single scenario/candidate is flaky, rerun it with `--scenarios`/`--candidates` into a new directory and record separately.
- If build/env issues occur, fix on a clean checkout/commit, record the new SHA, and rerun.

## Interpretation

- `report.md` provides per-scenario medians, correctness, throughput, CPU, backlog/placement summaries, and invalid/incomplete flags.
- **Valid decision requires:** correct results (no overlap/loss/dup, exact totals), complete trials, comparable workload definitions, and measurements on **physical** (non-fake) NUMA. Fake-NUMA or local-only runs are for validation/readiness, not scaling conclusions.
- Pipe ingestion is excluded for dist candidates in the initial bake-off (see `PIPE_INGESTION.md`).
- Prefer simpler policies when benefits are not measurable; retain centralized control if competitive.
