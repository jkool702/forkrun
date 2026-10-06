#!/usr/bin/env bash
# Same 6 outlier cells, run against the 97f096f8 (10-02) build in a worktree.
cd /tmp/opencode/mlbench
unset FR_BENCH_SKIP FR_BENCH_WORKERS
: > /tmp/opencode/mlbench/baserun.log
for pass in 1 2; do
  for c in "light plugin default view file" \
           "light plugin max bytes pipe" \
           "light plugin max view file" \
           "light plugin default view pipe" \
           "light plugin max view pipe" \
           "medium plugin default view pipe"; do
    echo "PASS$pass $c" >> /tmp/opencode/mlbench/baserun.log
    python3 cell_base.py $c auto >> /tmp/opencode/mlbench/baserun.log 2>&1
  done
done
echo BASERUN_DONE >> /tmp/opencode/mlbench/baserun.log
