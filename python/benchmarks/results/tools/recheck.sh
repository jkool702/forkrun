#!/usr/bin/env bash
# Re-measure the worst cells plus a control that moved the OTHER way.
# Two independent passes each: if a cell does not reproduce, the first
# sweep's number was noise, not a regression.
cd /tmp/opencode/mlbench
unset FR_BENCH_SKIP FR_BENCH_WORKERS
: > /tmp/opencode/mlbench/recheck.log
for pass in 1 2; do
  for c in "light plugin default view file" \
           "light plugin max bytes pipe" \
           "light plugin max view file" \
           "light plugin default view pipe" \
           "light plugin max view pipe" \
           "medium plugin default view pipe"; do
    echo "PASS$pass $c" >> /tmp/opencode/mlbench/recheck.log
    python3 cell.py $c auto >> /tmp/opencode/mlbench/recheck.log 2>&1
  done
done
echo RECHECK_DONE >> /tmp/opencode/mlbench/recheck.log
