#!/usr/bin/env bash
# Binary-search 97f096f8..NEW/REFACTOR3.9 for the commit that costs the
# light-plugin cells ~13%. Boundary 1197 MB/s sits midway between the two
# endpoints (1286 vs 1109) and well outside this cell's ~1% spread.
cd /mnt/ramdisk/forkrun || exit 1
GOOD=97f096f8
LIST=$(git rev-list --reverse 97f096f8..NEW/REFACTOR3.9)
N=$(echo "$LIST" | wc -l)
lo=0; hi=$((N-1))
echo "bisecting $N commits, boundary 1197 MB/s"
while [ $lo -lt $hi ]; do
  mid=$(( (lo + hi) / 2 ))
  REF=$(echo "$LIST" | sed -n "$((mid+1))p")
  SUBJ=$(git log -1 --format=%s "$REF" | cut -c1-60)
  R=$(/tmp/opencode/measure.sh "$REF")
  set -- $R
  if [ $# -lt 2 ]; then
    echo "[$mid/$N] $REF SKIP ($R)"; lo=$((mid+1)); continue
  fi
  # use the better (higher) of the two passes to avoid a false "slow"
  BEST=$(python3 -c "print(max($1,$2))")
  VERDICT=$(python3 -c "print('GOOD' if $BEST>=1197 else 'BAD')")
  echo "[$mid/$N] $VERDICT $BEST MB/s  ${REF:0:8}  $SUBJ"
  if [ "$VERDICT" = GOOD ]; then lo=$((mid+1)); else hi=$mid; fi
done
echo "=== first BAD commit ==="
git log -1 --format="%h %ad %s" --date=format:"%m-%d %H:%M" $(echo "$LIST" | sed -n "$((lo+1))p") | cat
git log -1 --format="%b" $(echo "$LIST" | sed -n "$((lo+1))p") | head -20
