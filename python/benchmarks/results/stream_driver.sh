#!/usr/bin/env bash
# Drive cell.py across the grid, one fresh process per cell, strictly
# sequential -- never two benchmark jobs at once on this box.
set -u
cd /tmp/opencode/mlbench
OUT="${1:-/tmp/opencode/mlbench/cells.log}"
: > "$OUT"
for v in light medium heavy; do
  for p in plugin udf; do
    for c in default max; do
      for o in view bytes; do
        for s in file pipe; do
          echo "-- $v $p $c $o $s" >> "$OUT"
          python3 cell.py "$v" "$p" "$c" "$o" "$s" >> "$OUT" 2>&1 \
            || echo "   CELL FAILED" >> "$OUT"
        done
      done
    done
  done
done
echo "DRIVER DONE" >> "$OUT"