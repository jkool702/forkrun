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

## Known instrumentation gaps to close during the rental

1. Ingest-thread CPU attribution: engine threads are unnamed in
   `/proc/<tid>/comm`; tree-wide CPU cannot isolate the centralized
   ingest thread. A `prctl(PR_SET_NAME)` hint (or equivalent) is the
   least-invasive fix. (The rehearsal's first-order screen therefore
   relies on tree CPU + queue occupancy; the ingest-only rate is NOT
   isolated in these cells.)
2. Scanner-queue occupancy telemetry: no ring-level queue depth is
   exposed to the harness; the queue-nonempty-interval demand method
   needs a small observational diagnostic.
3. Plugin-cell corpus: at 20M light records the C plugin finishes in
   <1 s, so the cell is bring-up-dominated; use a larger corpus for
   the rental if steady-state plugin throughput is a desired output.
