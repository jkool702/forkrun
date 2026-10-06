#!/usr/bin/env bash
# The 16 light cells (plugin/udf x default/max x view/bytes x file/pipe)
# at 20M records. Same nesting and TRIALS as stream_driver.sh; only the
# variant is restricted to light and the corpus is swapped for the 20M one.
# STALL_FORK_AFTER is left unset, so the default (0.0) is what runs.
cd /tmp/opencode/mlbench
unset FR_BENCH_SKIP FR_BENCH_WORKERS FR_STALL_FORK_AFTER
export FR_BENCH_CORPUS=/tmp/light_20M.jsonl
export FR_BENCH_EXPECT=20000000
OUT=/tmp/opencode/mlbench/light_20M.log
: > "$OUT"
for p in plugin udf; do
  for c in default max; do
    for o in view bytes; do
      for s in file pipe; do
        echo "-- light $p $c $o $s" >> "$OUT"
        python3 cell_var.py light "$p" "$c" "$o" "$s" auto >> "$OUT" 2>&1 \
          || echo "   CELL FAILED" >> "$OUT"
      done
    done
  done
done
echo "LIGHT20M DONE" >> "$OUT"
