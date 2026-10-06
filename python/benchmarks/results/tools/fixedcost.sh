#!/usr/bin/env bash
# If the regression is a FIXED per-run delay, the absolute delta in seconds
# is roughly the same for light/medium/heavy while the RATIO varies with
# payload size. Measure both endpoints across the three payloads.
set -u
for REF in 97f096f8 c55a2714; do
  WT=/tmp/opencode/fc_$REF
  cd /mnt/ramdisk/forkrun && git worktree add -f "$WT" "$REF" >/dev/null 2>&1
  ( cd "$WT" && timeout 1200 make -f Makefile.substrate python-substrate ) >/dev/null 2>&1
  cd /tmp/opencode/mlbench && unset FR_BENCH_SKIP FR_BENCH_WORKERS
  for v in light medium heavy; do
    S=$(FORKRUN_SRC="$WT/python" python3 cell_var.py $v plugin default view file auto 2>/dev/null | awk '/^RESULT/{print $8}')
    echo "$REF $v $S"
  done
  cd /mnt/ramdisk/forkrun && git worktree remove --force "$WT" >/dev/null 2>&1
done
