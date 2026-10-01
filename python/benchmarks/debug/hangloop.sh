#!/bin/bash
for i in $(seq 1 15); do
  FORKRUN_DEBUG_PUMP=1 timeout 30 python3 /tmp/onehung.py > /tmp/hl_out.txt 2>/tmp/hl_err.txt
  rc=$?
  if [ $rc -ne 0 ]; then echo "HUNG iter $i"; P=$(grep -oP '^P \K[0-9]+' /tmp/hl_out.txt); echo "parent=$P"; tail -n 1 /tmp/hl_err.txt; exit 42; fi
  echo "iter $i ok"
done
echo ALLDONE
