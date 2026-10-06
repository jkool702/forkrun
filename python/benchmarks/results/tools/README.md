# Benchmark tooling used for the v3.6.1 cycle

These are the scripts behind the numbers quoted in
`python/benchmarks/results/RELEASE_v3.6.0.md` and `DOCS/CHANGELOG.md`.
They are kept because the conclusions they produced are not
re-derivable from the results files alone — in particular the pre-flight
regression was found by *bisecting commits*, and the evidence for that is
the scripts, not the final table.

They were written against a scratch layout (`/tmp/opencode/mlbench` for
the corpora and cell runner, `/tmp/opencode` for logs). That is recorded
rather than parameterised, so treat the paths as what they were.

## What each one does

| script | purpose |
|---|---|
| `gate.sh` | Runs the full test suite twice, cleanroom OFF then ON, into `/tmp/opencode/g{1,1on}.txt`. The gate for any change here. |
| `cmp_cells.py` | Compares two 48-cell logs cell by cell (throughput ratio, worst/best, `n_out` mismatch detection). Usage: `cmp_cells.py <baseline.log> <new.log>`. |
| `cell_var.py` | `stream_cells.py` with the forkrun source directory taken from `$FORKRUN_SRC`, so a benchmark can be pointed at a worktree build. That is what makes the bisect possible. |
| `measure.sh <ref> [cell]` | Builds `<ref>` in a throwaway git worktree and times one discriminating cell twice. The unit of the bisect. |
| `bisect.sh` | Binary-searches `97f096f8..HEAD` for the commit that costs throughput, using a 1197 MB/s decision boundary (midway between the two measured endpoints). |
| `fixedcost.sh` | Times light/medium/heavy absolute seconds at two refs, to show the regression was *fixed* per-run overhead rather than proportional. |
| `baserun.sh`, `recheck.sh` | The A/B discipline: run a cell set against the current build and against a baseline worktree build, twice each, on the same day. Establishes that a difference is real before chasing it. |
| `light20m.sh` | The 16-cell `light` grid at 20M records. |
| `slowprod.py` | Slow-producer harness. Reproduces the bimodal-run problem and, with the scanner instrumented, reports the pre-flight window. |

## Restoring the benchmark environment after a ramdisk reboot

`/tmp` and `/mnt/ramdisk` are tmpfs here, so the corpora and the built
plugin fixtures do **not** survive a reboot. Everything needed to rebuild
them is in this repo:

```bash
# 1. substrate + python package
make -f Makefile.substrate python-substrate

# 2. plugin fixtures (sources are tracked)
python3 - <<'PY'
import sys; sys.path.insert(0, 'python/benchmarks')
from bench_ml_pipeline import build_ml_plugin
for v in ("light", "medium", "heavy"):
    print(build_ml_plugin(v, "/tmp/opencode/mlbench"))
PY

# 3. corpora — ml_data_gen.generate_data is seeded (SEED = 42), so these
#    reproduce the published files BYTE FOR BYTE. Note the record COUNTS:
#      light  5,000,000 lines = 532,711,015 B
#      medium 5,000,000 lines = 2,347,403,909 B
#      heavy  5,000,000 lines = 6,720,381,299 B  (first 5M lines of the
#                                                 PRE-EXISTING heavy_20M)
python3 - <<'PY'
import sys; sys.path.insert(0, 'python/benchmarks/ml')
from ml_data_gen import generate_data
for variant, n in (("light", 5_000_000), ("medium", 5_000_000)):
    generate_data("numa1/ml/%s_5M.jsonl" % variant, n, variant)
PY
head -n 5000000 numa1/ml/heavy_20M.jsonl > numa1/ml/heavy_5M.jsonl
```

**Gotcha that cost two full sweeps: never take a record count from
`cell.py`'s `expect`, or from a results table.** Those are
EXPECTED-OUTPUT totals, not file record counts:

| source                      | says         | actual records |
|-----------------------------|--------------|----------------|
| `stream_cells.py` CORPORA  | 4997892 med  | 5,000,000      |
| `numa_5m_study.md`          | 4997982 hv   | 5,000,000      |

Feeding those to `generate_data` / `head -n` produces a corpus ~1 MB
short with the *same line count*, and then every medium/heavy cell fails
the exactness guard short by ~2,000 records. That reads exactly like
silent data loss and is not -- I chased it as far as suspecting the
poison relay before checking byte size. The tells that it is the corpus
and not the code: the shortfall is identical across `plugin` and `udf`
payloads, and it appears with `poisoned=0` and no warnings at all.

**Always verify by byte size against the published figure**, never by
line count alone:

```python
import os
for n, want in (("light", 532711015), ("medium", 2347403909),
                ("heavy", 6720381299)):
    p = "numa1/ml/%s_5M.jsonl" % n
    got = os.path.getsize(p)
    print("%-7s %d  want %d  %s" % (n, got, want,
                                    "OK" if got == want else "MISMATCH"))
```

The 20M light corpus used for the corrected light column is the 5M file
concatenated four times — 2,130,844,060 bytes, which is exactly the 2.13 GB
the release table quotes:

```bash
cd /mnt/ramdisk/numa1/ml
cat light_5M.jsonl light_5M.jsonl light_5M.jsonl light_5M.jsonl \
    > /tmp/light_20M.jsonl      # 20,000,000 records
```

Note this repeats record IDs 4×. That is fine for throughput (identical
bytes, and the cell runner asserts exactly 20,000,000 records out, so
nothing is being de-duplicated), but it is not equivalent to a natively
generated 20M file if a payload ever keys off `eid` uniqueness.

`cell.py` is `python/benchmarks/results/stream_cells.py` — the same file,
copied to `/tmp/opencode/mlbench/cell.py`. `stream_driver.sh` next to it
drives the full 48-cell grid, one fresh process per cell.
