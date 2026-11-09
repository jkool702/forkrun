# Stage 0 — rental execution recipe

Purpose: execute the already-validated rehearsal campaign on **real,
multi-node NUMA hardware** and answer the §8 Go / No-Go / Inconclusive
gate (companion blueprint: `numa_ingestion_blueprint` Stage 0/§21).

This is the spec's §7.2 path: the scripts must run as-is; do not spend
rental time debugging the harness.

## Pre-flight (local, already done on the dev i9)

- [x] Rehearsal report at `stage0/reports/stage0-report.md` (fake NUMA)
- [x] Harness: `stage0/run_case.py` (one spec → trials → manifests),
      `stage0/run_campaign.sh` (loop), `stage0/report.py` (aggregate),
      `stage0/ablation_2x2.py` (+ `stage0/residency_shim.c` →
      `libstage0.so`), `stage0/env_capture.py`
- [x] Corpora: `stage0/corpus/light_20m.txt` (2.4 GB, 20M records,
      sha256 recorded in `.manifest.json`) and `light_5m.txt`

## On the rental host

1. Clone `NEW/REFACTOR5.0` at the recorded SHA; `make -f
   Makefile.substrate python-substrate udf`; place `stage0/` as-is.
2. Record environment before and after the run set:
   `python3 stage0/env_capture.py --out stage0/runs/env-rental.json`
3. Regenerate corpora if the host lacks them
   (`make_corpus.py --records 20000000 --variant light ...`) and
   verify the sha256 matches the rehearsal manifest.
4. Run the same matrix (3 trials each):
   `TRIALS=3 bash stage0/run_campaign.sh`
   plus the ablation: `python3 stage0/ablation_2x2.py --cells A,B,C,D
   --json stage0/raw/ablation.json`
5. Regenerate the report with the rental artifacts and classify
   per spec §8. **Do not change kernel/firmware/THP/governor between
   baseline scenarios**; any intentional change is a separate labelled
   experiment.

## Hard requirements for a valid Go/No-Go

- Physical multi-node topology (not `numa=fake=`).
- Downstream-demand estimate per spec §3 (queue-nonempty intervals)
  **or** the least-invasive ingest-thread/queue diagnostic (§4.3) —
  without one of these, the verdict is Inconclusive by definition.
- Placement residency measured before downstream contamination, with
  the §12.5 contamination controls.
- All raw logs + manifests + env captures retained beside the report.

## Instrumentation status (post-rehearsal: what remains, what was fixed)

1. **Baseline**: `forkrun_ring.c` blob is identical on `main`,
   `NEW/REFACTOR4.7`, and `NEW/REFACTOR5.0` (blob-verified
   2026-11-08), so the engine behavior is the same everywhere.
   `python/forkrun/run.py` differs between 4.7 and 5.0 (release work:
   346+/166−); the campaign ran the **released run.py** (REFACTOR5.0 ==
   main for that file). If a re-run against the 4.7 baseline is
   required by policy, rerun after checking out 4.7 — specs and
   harness are branch-agnostic.
2. **Ingest-thread CPU attribution: RESOLVED.** The engine names its
   ingest task `fr-ingest` (prctl, STAGE0 instrumentation commit); the
   harness attributes per-TID comm into `ingest_cpu_sec` per run.
3. **Queue occupancy demand: RESOLVED via sampler.** The
   `FORKRUN_DIAG_QUEUE` stderr sampler emits per-node head/tail at
   ~20 ms; `report.py` derives nonempty-fraction/empty-streak inputs
   to the spec §3 demand estimate. **The rental must run with
   `FORKRUN_DIAG_QUEUE=1`** for demand data.
4. **Write-path residency attribution: OPEN.** Production
   write()-based materialization pages are invisible to both
   `move_pages()` (-2 per page) and `numa_maps` (no N-fields) —
   measured on the rehearsal host. The rental's placement gate for the
   write form needs a node-level method (e.g. sysfs node-meminfo
   deltas or a tuned accounting source), developed on the rental host.
5. **Plugin steady state**: 60M corpus runs ≥2 s (this box ~2.0–3.0 s);
   use a larger corpus on the rental if sustained plugin throughput
   is a required output.
