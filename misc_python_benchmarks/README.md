# misc_python_benchmarks

Ad-hoc benchmark / probe / smoke scripts collected from `/tmp` (Sep 2026
sessions), curated so they can plausibly be re-run. These are NOT part of
the supported suite (`python/benchmarks/`, `UNIT_TESTS/`): they are frozen
as-found (only copied, never modernized), with original absolute paths and
quirks intact. Expect bit-rot — check the per-script notes before running.

## How to re-run

Most scripts assume **repo root as CWD** (they do
`sys.path.insert(0, 'python')`; a few use the absolute
`/mnt/ramdisk/forkrun/python` — adjust if your checkout lives elsewhere):

```bash
cd /mnt/ramdisk/forkrun   # or wherever this repo lives
python3 misc_python_benchmarks/throughput/ab.py v1 200000
```

Many scripts need input data that lived in `/tmp` and is NOT archived
(it was gigabytes). Regenerate first:
- `data_gen/bigdoc_gen*.py` produce tokenize corpora.
- Most `throughput/` + `streaming/` scripts read `/tmp/bm.txt`,
  `/tmp/big.txt`, `/tmp/t10M.txt` (plain line files — recreate with
  `seq`); `arm*.py` need `/tmp/w21b_{lines,small}.txt`; `*_order*.py`,
  `ml_none.py`, `fault_*`, `idx*_test.py`, `pf_nocrasch.py`,
  `plugin_fault_test.py`, `ray_fault.py` need `/tmp/mldata/ml_*.jsonl`
  (see `python/benchmarks/ml_data_gen.py`).
- Tokenize scripts need `/tmp/tok.jsonl` + `/tmp/tok.jsonl.vocab`
  (see `python/benchmarks/tokenize_data_gen.py`) and set
  `FORKRUN_VOCAB_PATH`; several build throwaway `.so` files in /tmp.
- `resume/` + `smoke_resume*` scripts need `/tmp/res_src.txt` (and
  generate their own `.ckpt` files).

## Layout

| Dir | Contents |
|---|---|
| `session_w29/` | Sep-23 W-PY29 drivers — known-good, recently run. `bench_w29.py` (5M ML + 500k tokenize, 2 forkrun modes, workers 8/14/28: `python3 …/bench_w29.py <tmpdir>`), `bench_w29_fault.py` (fault-injection tax: `python3 … <records> [modes] [workers] [trials]`, needs the medium input or generates it), `segv_probe.py` / `segv_stack.py` (single-SEGV recovery probes). |
| `throughput/` | Worker sweeps + rec/s microbenchmarks (`ab.py`, `arm*.py`, `bench_w21b.py`, `sweep_*.py`, `xlong_sweep.py`, `ml_*` comparisons). |
| `tokenize/` | Tokenizer benchmarks and pool-debug probes (`bigdoc_bench.py`, `tok_speed.py`, `pooldbg*.py`, `polars_probe.py`, `sweep_tok_long.py`). |
| `fault_recovery/` | Crash/poison/segfault experiments (`fault_*.py`, `idx*_test.py`, `plugin_fault_test.py`, `ray_fault.py`, `sabotage.py`, `w19_kill.py`, `w19_segv.py`, `pf_nocrasch.py`). |
| `smoke/` | Correctness spot-checks (`catch*.py`, `estress.py`, `smoke_diff/full/save.py`, `bisect_old.py`). |
| `streaming/` | Streaming-ingest, splice, RSS, hang-repro and phase-timing probes (largest dir; many need `/tmp/bm.txt` or `/tmp/w19_smoke.txt`). |
| `validation/` | Python-vs-C-plugin equality checks (`validate_*.py`, `find_ld.py`, `diag_mal.py`). |
| `data_gen/` | Corpus generators (`bigdoc_gen*.py`). |
| `debug_probes/` | ctypes-level engine probes (`dbg*.py`, `ndbg.py`, `fdtrace.py`, `ml_diag/min/forkonly.py`, `hangloop.sh`, …). Expect these to be the most bit-rotted (they poke at internals). |
| `resume/` | Checkpoint/resume experiments (`abort_only.py`, `diag_*.py`, `forensic.py`, `smoke_resume*.py`, `xlong_resume.py`, `m9only.sh`). |
| `shell_helpers/` | Tiny bash helpers from the W-PY29/30 sessions: `failonce.sh` (fail-once frun payload), `coretest.sh` (crash-counter payload), `filtercheck.sh` (print own coredump_filter). |

## Deliberately NOT archived

- Multi-GB inputs (`/tmp/big.txt`, `/tmp/fr_bench_*.txt`, `*.jsonl` corpora) — regenerate.
- Run logs/traces (`*.log`, `*_err.txt`, `drain_trace*.txt`, `hookdbg.txt`).
- `w29*/tmp*` temp dirs (markers, generated payload modules).
- Repo-surgery scripts (test renumbering, M4-block transplants, bisect
  harnesses) — single-use, tied to already-landed edits.

## Known environment quirks (verified, not caused by archiving)

- This box defaults `multiprocessing` to **forkserver**: scripts with a
  bare top-level `Pool(...)` and no `if __name__ == "__main__"` guard
  (e.g. `throughput/ml_poolonly.py`) fail identically from `/tmp` and
  from here. Run those with a fork start method or add the guard.
- Spot-checked 2026-09-23: `throughput/arm1.py` runs clean from here
  (needs its input generated, e.g. `seq 1 200 > /tmp/w21b_small.txt`);
  `session_w29/*` drivers were the live W-PY29 harnesses.
