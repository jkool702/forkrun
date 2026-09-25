# Stage 0 evidence harness (`python/benchmarks/stage0/`)

The project's evidence layer for the Python frontend: localization numbers,
honest-claims tables, and per-niche positioning — **not a decision
instrument** (the proceed decision is unconditional; see
`dev/supervisor/STAGE0_AMENDMENT.md`).

## Run

```bash
bash python/benchmarks/stage0/run_stage0.sh
# or: nohup bash python/benchmarks/stage0/run_stage0.sh >/tmp/s0.out 2>&1 &
# poll: tail python/benchmarks/stage0/results/progress.log
```

## Layout

- `run_stage0.sh` — one-command entry point.
- `run_stage0.py` — orchestration helpers (subprocess legs, whole-tree RSS
  sampler, `/usr/bin/time -v` cross-check, hardware label).
- `s0legs.py` — measurement legs per niche + fault isolation.
- `report.py` — CSV/Markdown tables, fault tables, narrative report.
- `gen_inputs.py` / `gen_stream.py` — seeded deterministic generators
  (JSONL 1M, int32 tokens 100M, transform lines 10M, endless pipe stream).
- `incumbents/` — one self-contained script per incumbent; each prints a
  single JSON summary line (`bench_common.py` contract). The torch leg
  emits UNMEASURED when torch/tensorflow are absent.
- `forkrun/` — C plugins compiled at harness time (substrate-ceiling legs).
- `ffi_spike.py` — Stage 2 ctypes spike: FFI boundary cost (null floor,
  claim-shaped/claim-ptr calls, MAP_SHARED memoryview window, Python fixed
  cost) against a purpose-built probe micro-library; writes
  `results/ffi_spike.json` and appends the `ffi-boundary` table row.
- `rental/run_rental.sh` — portable rental-day runner (documented, not yet
  executed).
- `inputs/` (gitignored, regenerable), `work/` (gitignored scratch),
  `logs/` (gitignored raw leg logs), `results/` (committed tables+report).

## Scope honesty

Rows the Python frontend can't fill yet are marked "substrate via C
plugin / bash — Python frontend pending." UNMEASURED rows carry reasons.
The table proves throughput/RSS/fault behavior on the stated hardware and
inputs; it does not prove adoption fitness, multi-socket scaling, or the
Python frontend's eventual performance.
