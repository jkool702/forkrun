# Rental-day workflow — distributed-ingest experiment (WO-NUMA-ONE-SHOT-RENTAL-PREPARATION, §9.5)

Exact, reproducible sequence for the rental day of the distributed-ingest
experiment. Each step is a named artifact; `RENTAL_READINESS.md` (this repo)
records what was actually executed on the rehearsal host.

The rental entry point is:

```bash
bash epyc/55_agent_supervise.sh --hours 12   # or: bash epyc/run_all.sh --only 00_preflight,10_setup,41_bench_numa5m,45_bench_dist_ingest
```

The `41_bench_numa5m` stage is part of the full selection: step 2 identifies
its F-NUMA1 topology sanity gate as the final gate for physical-topology
claims and step 5 calls for production-reference measurements. If you run
the shortcut WITHOUT `41_bench_numa5m`, the dist-ingest stage (45) still runs,
but the production-reference separation (WO 9.2) is not established — run
`bash epyc/41_bench_numa5m.sh` separately first if you intend to compare
against the production pipeline.

## Step 1 — Checkout and source verification

```bash
git fetch origin && git checkout <branch> && git rev-parse HEAD
# compare against the campaign's expected source SHA (immutable source tree)
```

- The measured tree must be **immutable during the campaign** (WO 9.3): no
  edits to `forkrun_ring.c`, `dist_ingest.c/.h`, policy code, topology
  selection, benchmark definitions, or report validity rules while trials
  run. Any needed change: stop, re-commit, re-hash, restart with a new
  campaign.
- `epyc/10_setup.sh` writes `INTEGRITY.sha256`; `epyc/90_collect.sh`
  re-verifies it as `INTEGRITY_AUDIT.md`.
- Record the checkout SHA in `campaign-manifest.json` (`source_sha`).

## Step 2 — Physical topology and bare-metal verification

```bash
cat epyc-rental-out/00_environment/PREFLIGHT.txt
```

- Confirm real multi-socket topology, NUMA distances (SLIT), THP state, and
  `numa_balancing` are as planned. `epyc/00_preflight.sh` writes
  `epyc-rental-out/00_environment/epyc.env` (the authoritative recorded
  topology: `EPYC_NODES`, `EPYC_NUMA_SHAPE`, `EPYC_NODE_SOCKETS`,
  `EPYC_DIST_*`, `EPYC_THRESH_*`, ...).
- The `41_bench_numa5m` F-NUMA1 topology sanity gate is the final gate for
  physical-topology claims (fake-NUMA does not pass it).

## Step 3 — Environment capture

```bash
python3 stage0/env_capture.py --repo . --out epyc-rental-out/env/env-before-1.json --run-id rental-1
```

(On a rental, the harness stages capture before/after; standalone capture
is for spot checks and for the drift utility below.)

## Step 4 — Hardware calibration (WO 8)

```bash
python3 stage0/numa_calibrate.py --out epyc-rental-out/21_bench_dist_ingest/numa_calibration.json --samples 5 --size-mb 64
```

Diagnostic only: **not** included in dist-ingest throughput statistics.
Placement is read back with `move_pages()`; `mbind()` success is not used
as placement proof.

## Step 5 — Production Stage 0 reference measurements

```bash
bash epyc/41_bench_numa5m.sh      # production NUMA study (THE experiment)
```

Production results are **recorded separately** from dist-ingest results
(WO 9.2): the dist-ingest stage (45) and its reports never combine them.
Record their location: `epyc-rental-out/20_benchmarks/numa5m/`.

## Step 6 — Distributed-ingest performance campaign

```bash
bash epyc/45_bench_dist_ingest.sh
# or explicitly:
bash stage0/dist_ingest/run_dist_campaign.sh --quick --out epyc-rental-out/21_bench_dist_ingest/dist_ingest_campaign \
    --campaign-id rental-day-1 --scenarios small --candidates fixed_faa,local_adaptive,relative_adaptive,centralized_ingest --trials 1 --seed rental-day-1
```

The campaign runs the experimental dist-ingest campaign and writes its
immutable output dir (`campaign-manifest.json`, `report.md`, `cases/`,
`env/`, `drift-report.json`, build logs). It also runs the drift check
(WO 7.2) after `env-after`: critical drift invalidates the campaign.

## Step 7 — Distributed-ingest placement-validation campaign (WO 2/C2)

```bash
bash stage0/dist_ingest/run_dist_campaign.sh --quick --out epyc-rental-out/21_bench_dist_ingest/dist_ingest_campaign_placement \
    --campaign-id rental-day-1-pv --scenarios small --candidates fixed_faa --trials 1 --seed rental-day-1-pv \
    --placement-experiments paired
```

Placement-validation trials are distinct, linked experiments — excluded
from performance headline statistics. (The campaign accepts
`--placement-experiments off|paired`; `1` is invalid.)

## Step 8 — Environment re-capture and drift assessment (WO 7.2)

```bash
python3 stage0/env_capture.py --repo . --out epyc-rental-out/env/env-after-1.json --run-id rental-1
python3 stage0/env_drift.py --before epyc-rental-out/env/env-before-1.json --after epyc-rental-out/env/env-after-1.json --out epyc-rental-out/env/drift-report.json
```

Critical drift must invalidate the campaign — see `drift-report.json`
(`campaign_valid` field) and the campaign manifest's `drift_invalidated`.

## Step 9 — Final report generation

```bash
python3 stage0/dist_ingest/report_dist.py --campaign epyc-rental-out/21_bench_dist_ingest/dist_ingest_campaign --out epyc-rental-out/21_bench_dist_ingest/dist_ingest_report.md
```

The report distinguishes aggregate from individual-pass metrics for
repeated trials, reports invalid aggregates explicitly, and identifies
failed/excluded passes.

## Step 10 — Artifact collection and verification

```bash
bash epyc/90_collect.sh          # bundles + ENVIRONMENT.md + DEVIATIONS.md + INTEGRITY_AUDIT.md
bash epyc/98_publish.sh --label rental-day-1   # publish to the results branch
```

Verify: `INTEGRITY_AUDIT.md` verdict; `drift-report.json`; all campaign
manifests; both reports (dist-ingest + production).

## Artifacts per step (summary table)

| # | Step | Artifact |
|---|---|---|
| 1 | source verify | `campaign-manifest.json` (`source_sha`) |
| 2 | topology verify | `epyc-rental-out/00_environment/PREFLIGHT.txt`, `epyc.env` |
| 3 | env capture | `env-before-1.json` |
| 4 | calibration | `21_bench_dist_ingest/numa_calibration.json` |
| 5 | production refs | `20_benchmarks/numa5m/*.csv` (stage 41) |
| 6 | dist campaign | `21_bench_dist_ingest/dist_ingest_campaign/` + `dist_ingest_report.md` |
| 7 | placement trials | `dist_ingest_campaign_placement/` |
| 8 | drift | `env-after-1.json` + `env/drift-report.json` |
| 9 | report | `21_bench_dist_ingest/dist_ingest_report.md` |
| 10 | collect/verify | `90_collect` outputs + `98_publish.sh` |
