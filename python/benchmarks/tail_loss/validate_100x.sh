#!/bin/bash
# W-STREAMDRAIN/W-CR2 validation on branch 3.7. 100 runs per config.
# Two families, because they cover DIFFERENT code:
#   mapx.py  "stream"     -> in-process streaming (orchestrator=True,
#                            outside the cleanroom envelope). Regression
#                            cover for the two tail-loss fixes.
#   crstream.py "cr_stream"-> the LAUNCHER (orchestrator=False + CR=1).
#                            This is where the W-CR2 forked-spill change
#                            lives, and it had NO sustained-load coverage
#                            before this run.
OUT=/tmp/opencode/repro/validate2.txt
: > $OUT
cd /tmp/opencode/repro
echo "== in-process streaming (regression) ==" >> $OUT
for CFG in "4 1 1" "4 4 1" "2 4 1" "8 4 1" "4 4 0" "4 1 0"; do
  set -- $CFG; ok=0; bad=0
  for i in $(seq 1 100); do
    R=$(K=stream W=$1 ND=$2 timeout 200 python3 mapx.py 2>/dev/null | sed 's/.*lines=\([0-9]*\).*/\1/')
    if [ "$R" = "2000" ]; then ok=$((ok+1)); else bad=$((bad+1)); echo "  ip w=$1 n=$2 cd=$3 iter=$i lines=$R" >> $OUT; fi
  done
  echo "in-process  workers=$1 nodes=$2 c_drain=$3 : $ok/100 exact, $bad SHORT" >> $OUT
done
echo "== cleanroom streaming (launcher, W-CR2 path) ==" >> $OUT
for W in 2 4 8 16; do
  ok=0; bad=0
  for i in $(seq 1 100); do
    R=$(K=cr_stream W=$W ND=1 N=2000 timeout 200 python3 crstream.py 2>/dev/null | sed 's/.*bytes=\([0-9]*\).*/\1/')
    if [ "$R" = "2000" ]; then ok=$((ok+1)); else bad=$((bad+1)); echo "  cr w=$W n=1 iter=$i bytes=$R" >> $OUT; fi
  done
  echo "cleanroom   workers=$W nodes=1 stream    : $ok/100 exact, $bad SHORT" >> $OUT
done
echo ALLDONE >> $OUT
