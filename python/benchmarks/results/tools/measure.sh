#!/usr/bin/env bash
# measure.sh <ref> : build <ref> in a worktree and time one discriminating cell.
# Prints just the MB/s so a bisect can read it. Two passes, lower median:
# this cell's within-session spread is ~1%, so one pass is not enough to
# separate a 2% step but is plenty to see the 13% one.
set -u
REF="$1"; CELL="${2:-light plugin default view file}"
WT="/tmp/opencode/wt_$REF"
cd /mnt/ramdisk/forkrun || exit 1
git worktree add -f "$WT" "$REF" >/dev/null 2>&1 || { echo "WORKTREE_FAIL"; exit 1; }
( cd "$WT" && timeout 1200 make -f Makefile.substrate python-substrate ) >/dev/null 2>&1
[ -f "$WT/python/forkrun/libforkrun_python.so" ] || { echo "BUILD_FAIL"; git worktree remove --force "$WT" >/dev/null 2>&1; exit 1; }
cd /tmp/opencode/mlbench || exit 1
unset FR_BENCH_SKIP FR_BENCH_WORKERS
A=$(FORKRUN_SRC="$WT/python" python3 cell_var.py $CELL auto 2>/dev/null | awk '/^RESULT/{print $9}')
B=$(FORKRUN_SRC="$WT/python" python3 cell_var.py $CELL auto 2>/dev/null | awk '/^RESULT/{print $9}')
cd /mnt/ramdisk/forkrun && git worktree remove --force "$WT" >/dev/null 2>&1
echo "$A $B"
