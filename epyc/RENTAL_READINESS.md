# RENTAL-DAY REHEARSAL STATUS — distributed-ingest experiment

Status of the rental-day workflow rehearsal (`epyc/RENTAL_DAY_WORKFLOW.md`,
WO-NUMA-ONE-SHOT-RENTAL-PREPARATION, §9.5) on the rehearsal host.

**Host note:** this rehearsal box is **not** physical rental hardware:
`numa=fake=4` (all CPUs on NUMA node 0; 4 logical nodes). This rehearsal
validates the workflow MECHANICS, not physical NUMA behavior or performance.
Physical-NUMA validation is a rental requirement, not a rehearsal deliverable.

Rehearsal date: 2026-11-23.

| # | Step | Artifact | Status |
|---|---|---|---|
| 1 | source verify | `campaign-manifest.json` (`source_sha`) | rehearsal: `45` stage rehearsal on `WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-C4-C5-CORRECTIONS-3 @ 9798f96d1ddc8c3b265c5f0bdfee82385ff52322` — campaign `source_sha` == `env-before.json` git.head_sha == corrected SHA, `git.dirty == false` (rehearsal rehearsal, epyc/rehearsal_rehearsal_45.sh) |
| 2 | topology verify | `00_environment/PREFLIGHT.txt`, `epyc.env` | rehearsal: `numa=fake=4` (fake, not physical) |
| 3 | env capture | `env-before-1.json` | rehearsal: OK (stage0/env_capture.py, C4.3+C4.5) |
| 4 | hardware calibration | `numa_calibration.json` | rehearsal: OK (stage0/numa_calibrate.py, C4.6; local 13–14 GB/s on this box) |
| 5 | production refs (41) | `20_benchmarks/numa5m/*` | **NOT run** (vacuous on fake-NUMA; not a rehearsal deliverable — rental requirement) |
| 6 | dist campaign (45) | `21_bench_dist_ingest/dist_ingest_campaign/` | rehearsal: OK — 4 candidates (fixed_faa, local_adaptive, relative_adaptive, centralized_ingest), 1 trial each, complete=True; report.md + campaign-manifest.json + drift-report.json + binary-provenance.json + build logs written |
| 7 | placement trials | `dist_ingest_campaign_placement/` | rehearsal: not exercised end-to-end (campaign feature present; placement validation runs are a rental/CI item) |
| 8 | drift assessment | `env-after-1.json` + `env/drift-report.json` | rehearsal: `campaign_valid=True` (0 critical) |
| 9 | report generation | `21_bench_dist_ingest/dist_ingest_report.md` + campaign `report.md` | rehearsal: OK — the 45 stage rehearsal wrote `dist_ingest_report.md` (via `report_dist.py`) and the campaign wrote its own `report.md` |
| 10 | collect + publish | `90_collect` + `98_publish.sh` | not run (rental mechanics; rehearsal harness not on rental) |

## Rehearsal evidence

- `45_bench_dist_ingest.sh` rehearsal rehearsal (clean checkout of corrected
  commit `6886defed99139910ff87fcf6e9b6a9c80060471` in worktree
  `/tmp/opencode/wt-corrections`; stage ran with
  `EPYC_OUT=/tmp/opencode/epyc-reh2/out`; the branch tip (`deecdc64`) is
  tree-identical to the rehearsaled corrected commit — the rehearsaled
  code is the tip's code):
  `/tmp/opencode/epyc-reh2/out/21_bench_dist_ingest/dist_ingest_campaign/`
  — `campaign-manifest.json` (`source_sha == env-before.json` git.head_sha
  == `6886defe…`, `dirty == false`; drift_assessment=valid, drift_invalidated=false,
  all_ok=true; 4 outcomes), `report.md` (headline medians present — drift
  valid), `dist_ingest_report.md` (stage report, written), `env/{env-before,env-after}.json`,
  `env/drift-report.json` (campaign_valid=True, 0 critical),
  `env/binary-provenance.json`, `env/build/{dist_ingest,python-substrate}.log`,
  4 candidate trials (all `complete=True`).
- Plan-only dry-run rehearsal: `run_dist_campaign.sh --plan-only` →
  `dist-campaign plan-only complete` (exit 0).
- Calibration rehearsal: `numa_calibrate.py --size-mb 32 --samples 3` →
  wrote `stage0/numa_calibrate.py` report (local read ~13 GB/s).
  Corrected-commit rehearsal (`/tmp/opencode/epyc-reh2/out/21_bench_dist_ingest/numa_calibration.json`):
  JSON parses (the P1.1 integration check passed; 45 stage COMPLETE rc=0).
- Drift rehearsal: `env_drift.py` reports `campaign_valid=True` for the
  rehearsal campaign's env pair.
- **Corrections-3 rehearsal rehearsal** (`epyc/rehearsal_rehearsal_45.sh`,
  run from clean worktree `/tmp/opencode/wt-corrections-3` @ `9798f96d…`,
  `EPYC_OUT=/tmp/opencode/epyc-reh3/out`, exit 0): 45-stage rehearsal OK;
  plan-only rehearsal (topology discovery + mapping-matrix generation +
  mapping compatibility validation) OK; rehearsal campaign OK
  (asymmetric-ingestor scenarios: `slow_ingestor_one`,
  `slow_ingestor_stall_recover`, `slow_ingestor_fast_consumer`,
  `slow_ingestor_slow_consumer`; paired placement experiments; repeated
  passes; randomized candidate order; per-trial provenance:
  mapping_provenance + duration_qualification + ingestor_controls);
  provenance reconciliation (campaign source_sha == env-before.json
  git.head_sha == `9798f96d…`, git.dirty == false, drift_assessment=valid);
  artifact collection/indexing (`90_collect`) OK.

## Known limitations of this rehearsal

- Fake NUMA (`numa=fake=4`) — all measurements are single-socket/fake;
  none are physical-NUMA validation.
- Placement-validation campaign rehearsal not exercised end-to-end.
- `98_publish.sh` rehearsal not run (needs a rental with git access).
- Production reference (41) not run.

## Open rental items (not rehearsal deliverables)

- Physical NUMA validation and rental.
- Confirm `41_bench_numa5m` topology gate passes (it refuses fake-NUMA).
