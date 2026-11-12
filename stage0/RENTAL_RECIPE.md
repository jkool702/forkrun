# Stage 0 — rental execution recipe

Purpose: run the **validated Stage 0 campaign** on **physical multi-node
NUMA hardware** and answer the spec §8 Go / No-Go / Inconclusive gate
(companion blueprint: `numa_ingestion_blueprint` Stage 0/§21).

The whole campaign is ONE command. The driver performs the clean-source
check, build, corpus identity check, environment capture, all trials,
the 8-cell ablation, the ablation validity gate, environment re-capture,
and report generation. Do not assemble the steps by hand and do not
spend rental time debugging the harness.

## 1. Preconditions

- A **clean checkout** of the exact commit to be measured. The driver
  refuses a dirty tree (a SHA alone does not identify dirty changes).
  For a non-reportable rehearsal only, `--allow-dirty` exists; a report
  generated from a dirty tree is rejected by the report validator.
- `git`, `make`, `gcc`, Python 3, and `libnuma` headers
  (`numa.h`, `-lnuma`) installed.
- Enough disk for the corpora and raw artifacts: the standard corpora
  are ~12 MB + 2.3 GB + 7.3 GB, and each campaign retains every raw
  trial log. A 20M-record trial can produce tens of MB of stderr when
  `FORKRUN_DIAG_QUEUE=1`.
- Physical multi-node memory: `/sys/devices/system/node/online` lists at
  least two online nodes with memory, and the kernel is **not** booted
  with `numa=fake=`. The report records `kernel.fake_numa` and refuses
  to convert fake-NUMA evidence into a Go decision.
- Two distinct nodes for the ablation: `--node-x` must have a CPU in
  the process cpuset (the affinity arm pins to it); `--node-y` needs
  only online memory (the policy arm `MPOL_BIND`s pages there and may
  legitimately be CPU-less in a cpuset).

## 2. The one command

From the repository root of the clean checkout:

```bash
TRIALS=3 bash stage0/run_all_campaign.sh
```

Defaults:

- campaign id: UTC timestamp + source SHA prefix + PID
- run directory: `stage0/runs/<campaign-id>/`
- report: `<run-dir>/report.md`, also copied to
  `stage0/reports/stage0-report.md` (publish is ON by default)
- specs: every `stage0/specs/*.json`
- ablation nodes: auto-selected from the online memory nodes

Useful options (all available as CLI flags; `ABLATION_NODE_X` /
`ABLATION_NODE_Y` are the environment equivalents for the node choice):

| option | meaning |
|---|---|
| `--run-dir DIR` | campaign directory (must be absent or empty) |
| `--campaign-id ID` | campaign identity recorded in every manifest |
| `--report-out PATH` | report path (default `<run-dir>/report.md`) |
| `--no-publish` | do not copy the report to `stage0/reports/` |
| `--node-x N` | affinity node for ablation cells B/D |
| `--node-y N` | `MPOL_BIND` node for ablation cells C/D |
| `--spec FILE` | run this spec (repeatable) instead of the inventory |
| `--no-corpus` | do not build/verify corpora (prebuilt inputs only) |
| `--trials N` | trials per spec (default `$TRIALS` or 3) |
| `--allow-dirty` | rehearsal only; a dirty campaign is not reportable |

Environment variables understood by the driver:

- `TRIALS` — default trial count (3).
- `SOURCE_SHA` — if set, must equal `git rev-parse HEAD`.
- `CAMPAIGN_ID`, `RUN_DIR`, `REPORT_OUT` — environment equivalents of
  the flags.
- `ABLATION_NODE_X`, `ABLATION_NODE_Y` — ablation node selection.
- `BASELINE_COMPARE=/path/to/baseline-compare.json` — optional 4.7-vs-5.0
  comparison section in the report.
- `STAGE0_VERIFY_CORPUS=0` — skip the sha256 re-hash of existing
  corpora (not recommended; the default verifies the manifest hash).

Example with an explicit campaign identity and node placement:

```bash
TRIALS=3 bash stage0/run_all_campaign.sh \
  --campaign-id rental-$(date -u +%Y%m%dT%H%M%SZ) \
  --run-dir stage0/runs/rental-$(date -u +%Y%m%dT%H%M%SZ) \
  --node-x 0 --node-y 1 \
  --report-out stage0/runs/rental-report.md
```

`FORKRUN_DIAG_QUEUE` is **forced to 1** by the driver and again by
`run_campaign.sh`, overriding any inherited value (including `0`).
Per-node queue telemetry is mandatory evidence, not an operator memory
test. The campaign manifest records `"forkrun_diag_queue": "1"`.

## 3. Corpus inventory and identity

The driver regenerates only when a `.manifest.json` disagrees, and by
default re-hashes existing files before reuse.

| corpus | records | bytes | sha256 |
|---|---:|---:|---|
| `stage0/corpus/light_100k.txt` | 100,000 | 11,888,890 | `36aed6a414ce4e84138d0549b9eaab9160bb22531918ba6d95b91a994da696a7` |
| `stage0/corpus/light_20m.txt` | 20,000,000 | 2,428,888,890 | `82737fb737805f32675518edcbfc7bafe5bc70154a710db1138d37083c49a59a` |
| `stage0/corpus/light_60m.txt` | 60,000,000 | 7,308,888,890 | `3f9ed18160f77c3a7bb4d86eb5cdfda3265481c80b5d1a004ccad5a994f8c5eb` |

Hashes are recorded in `stage0/corpus/<name>.manifest.json`; the driver
prints the reused or regenerated identity. If the rental host cannot
store 7.3 GB, stage the corpora on a local filesystem and run with
`--no-corpus` only after verifying the manifests yourself.

The inventory is 20M file and pipe cases plus a 60M plugin case:

| spec | input | workers | nodes | mode |
|---|---|---:|---|---|
| `file-light20m-n1-w14` | 20M | 14 | `1` (UMA control) | udf |
| `file-light20m-nauto-w14` | 20M | 14 | `auto` | udf |
| `file-light20m-nauto-w14-plugin` | 20M | 14 | `auto` | plugin |
| `file-light20m-nauto-w4` | 20M | 4 | `auto` | udf |
| `pipe-light20m-nauto-w14` | 20M (pipe) | 14 | `auto` | udf |
| `plugin-light60m-nauto-w14` | 60M | 14 | `auto` | plugin |
| `smoke-light-100k-nauto` | 100k | 4 | `auto` | udf |

The UMA `nodes: "1"` case has no ingest→indexer path. It is reported but
is **not** used for the centralized-ingest Go/No-Go decision.

## 4. What the driver does

1. Resolve `HEAD`, enforce the clean-source rule, export
   `FORKRUN_DIAG_QUEUE=1`, and create one immutable run directory.
2. Build `python-substrate`, the `udf` loadable, `stage0/libstage0.so`,
   and `stage0/ml_plugin_light.so`.
3. Verify or regenerate the corpora and their manifests.
4. Capture `env/env-before.json`.
5. Run every spec × `TRIALS` through `run_campaign.sh`.
6. Run the 2×2 ablation (8 rows: cells A/B/C/D × `map-fault` /
   `write-path`) and validate it with the same report module the report
   uses.
7. Capture `env/env-after.json`, generate the report, and optionally
   publish it to `stage0/reports/stage0-report.md`.

Every step is required. A failure aborts non-zero and names the step's
log path; the campaign does not silently skip a failed trial.

## 5. The evidence the report must contain

- `STAGE0_DIAG` / `STAGE0_FINAL src=ingest` records with `q`, `i`, `b`,
  `c`, `a`, `cpu_ns`, and `t_us` on one `CLOCK_MONOTONIC` timeline per
  trial. `q` is `(published, claimed)`, `b` is
  `(read_idx, write_idx)`, `c` cross-checks claims, `i` is the indexer
  waiter gauge, and `a` is the worker waiter pair.
- Interval math in **microseconds** (`t_us`); `t_ms` is human-readable
  only. Observations are consumed in their original order and each
  timestamp is validated against the immediately preceding observation.
  A missing, malformed, duplicate or decreasing timestamp **breaks the
  timeline**, so no interval is constructed across it. A missing or
  regressed `cpu_ns`, missing per-node group, or counter regression
  **excludes** the interval and is counted; it is never bridged.
- Same-interval predicates: ingest→indexer starvation (empty chunk
  queue + indexer waiters), scanner→worker starvation (empty batch
  queue + waiting workers + upstream input available), global
  ingest-thread CPU saturation in the same starvation intervals, and
  worker claims exceeding scanner publication in the same interval.
  `cpu_ns` is the emitting ingest thread's own CPU: ONE global
  measurement per interval, evaluated alongside each node's queue
  evidence. It is not an independently measured per-node CPU value;
  the per-node GO CPU columns report the shared global ingest-thread
  CPU over that node's GO intervals.
- Per-trial and per-node interval counts, durations, rates, exclusions,
  and the trial-to-trial spread. A GO verdict requires every trial to
  have GO intervals, complete attribution, no mixed trial, no
  source-limited interval, no upstream-available scanner starvation,
  and the weakest trial's GO deficit rate to exceed the full
  trial-to-trial spread. If the deficit is not distinguishable from
  variation, the verdict is INCONCLUSIVE; there is no arbitrary
  percentage threshold.
- Direct global C-ingest-thread CPU attribution: the trial manifest
  must say `ingest_cpu_attribution: "direct"` with
  `ingest_cpu_direct_source: "c-ingest-final (CLOCK_THREAD_CPUTIME_ID)"`
  and a positive `ingest_phase_s`. Comm-sampled `/proc` attribution is
  a different basis and must not be mixed with the direct delta.
- The 8 ablation rows with raw `move_pages()` statuses, per-node page
  accounting, `mincore` residency, and read-touch stability. A row that
  cannot measure placement is invalid, not zero.

A positive `claims - publications` is a **scanner-side supply deficit
relative to worker demand** (workers drew down previously queued work),
not by itself evidence that downstream is the limiter. The `q`/`i`
timeline decides whether the scanner lacked input or could not process
available input.

## 6. Report gate and raw retention

`stage0/report.py` exits **0** for any valid campaign, including a valid
INCONCLUSIVE or NO-GO verdict. It exits **2** for an invalid campaign
(missing/malformed manifests, dirty environment manifests, environment
drift, topology drift, stale campaign id, failed trials, invalid
ablation). The one-command driver treats a nonzero report exit as a
failed campaign.

On a fake-NUMA host the verdict is always
`INCONCLUSIVE for real-NUMA benefit — fake NUMA`, even when every queue
and CPU metric is present. That is the spec §8 rule, not a harness
failure.

Retain the entire run directory beside the report:

```
stage0/runs/<campaign-id>/
  campaign-manifest.json
  cases/<spec-id>/trial<N>/manifest.json
  cases/<spec-id>/trial<N>/stdout.log
  cases/<spec-id>/trial<N>/stderr.log
  ablation/ablation.json
  env/env-before.json
  env/env-after.json
  report.md
```

Campaigns are immutable: use a fresh `--run-dir`/`--campaign-id` for
every run and never edit old evidence. `stage0/corpus/`, `stage0/runs/`,
and `stage0/raw/` are gitignored; copy the generated report to
`stage0/reports/stage0-report.md` only through the driver (or
`--report-out`), never by hand-editing numbers.

## 7. Physical multi-node requirements and placement caveats

- **Fake NUMA cannot decide.** `numa=fake=N` gives each CPU a presence
  on every fake node, so the per-node queue and global ingest-thread
  CPU metrics validate the instrumentation but cannot establish
  physical placement or scaling. The report says so explicitly.
- Confirm the topology before spending trials:
  `numactl -H`, `cat /sys/devices/system/node/online`, and the
  `kernel.fake_numa` / `kernel.fake_numa_spec` fields in
  `env/env-before.json`.
- Set `--node-x` and `--node-y` to **distinct physical nodes**. Node X
  must have a CPU in the process cpuset; node Y only needs memory.
- Do not change kernel, firmware, THP setting, CPU governor, or memory
  policy between the before/after captures. Any intentional change is a
  separate labelled experiment; the report rejects environment drift.
- The 8 MB ablation validates the policy path and page accounting. It is
  not a throughput benchmark. Production write-path pages may be
  invisible to `move_pages()` (`-2` per page) and `numa_maps`; the
  report's page-accounting gate requires raw statuses and `mincore`
  consistency, and an unmeasured row is invalid rather than zero.
- A decisive throughput case must run at least 2 seconds and have at
  least 3 completed trials. The 20M/60M inventory is sized for that on
  current hardware; if a faster rental host drops a case below 2 s,
  enlarge the corpus rather than lowering the rule.

## 8. Local fake-NUMA rehearsal (already done)

The committed report at `stage0/reports/stage0-report.md` is generated
from campaign `stage0-final-38bda5ac` at source SHA
`38bda5ac2e5127ade192d017b9985c222d8965b1`, run from a clean checkout
on the development host (fake NUMA, `numa=fake=4`). It exercises the
real C-ingest sampler, the same-interval correlated evidence, the 8-row
ablation, and the report gate, and returns INCONCLUSIVE by rule. It is a
harness validation, **not** real-NUMA evidence.

Reproduce the local shape with:

```bash
TRIALS=3 bash stage0/run_all_campaign.sh \
  --campaign-id local-rehearsal \
  --run-dir stage0/runs/local-rehearsal \
  --no-publish
```

The rental run is the same command on physical multi-node hardware with
`--node-x`/`--node-y` set to distinct physical nodes.
