# Dist-ingest scenario specs

The primary one-command comparative driver is:

`bash stage0/dist_ingest/run_dist_campaign.sh [--out DIR] [--trials N] [--scenarios ...] [--candidates ...]`

It generates deterministic file corpora and per-case specs on the fly under the
campaign output directory (immutable), covering the required file-ingestion
scenarios: equal/slow/fast/asymmetric consumers, temporary stall+recovery,
varying node counts, large sequential file, small/tiny/boundary cases, and
backpressure/near-saturation.

Candidates:
- `control` — existing centralized forkrun path (run via `stage0/run_case.py`)
- `fixed_faa` — experimental fixed-size FAA
- `local_adaptive` — experimental local-headroom adaptive FAA
- `relative_adaptive` — experimental relative-headroom adaptive FAA

Pipe ingestion is excluded from the initial distributed-candidate bake-off (see
`../PIPE_INGESTION.md`). Individual ad-hoc specs can also be run directly with
`stage0/run_case.py` by setting `ingest_candidate` to a dist policy.
