#!/usr/bin/env bash
# Stage 0 ONE-COMMAND campaign driver (work order §2.3):
#   build prerequisites -> env-before capture -> campaign ->
#   ablation -> env-after capture -> report.
#
# Every step is required; none is silently skipped. A failure in any
# step aborts with non-zero and the step's log path.
set -euo pipefail
cd "$(dirname "$0")/.."

fail() { echo "stage0-run-all: FAILED at: $*" >&2; exit 1; }

echo "=== [1/5] build prerequisites (substrate + helpers + shim)"
make -f Makefile.substrate python-substrate udf || fail "substrate build"
gcc -O2 -shared -fPIC -o stage0/libstage0.so stage0/residency_shim.c -lnuma \
  || fail "residency shim build"
python3 stage0/make_corpus.py --records 100000 --variant light \
  --out stage0/corpus/light_100k.txt || fail "corpus: light_100k"
python3 stage0/make_corpus.py --records 20000000 --variant light \
  --out stage0/corpus/light_20m.txt || fail "corpus: light_20m"
python3 stage0/make_corpus.py --records 60000000 --variant light \
  --out stage0/corpus/light_60m.txt || fail "corpus: light_60m"

echo "=== [2/5] environment-before capture"
python3 stage0/env_capture.py --out stage0/runs/env-before.json \
  || fail "env-before capture"

echo "=== [3/5] campaign (TRIALS=${TRIALS:-3} per spec)"
TRIALS=${TRIALS:-3} bash stage0/run_campaign.sh \
  || fail "campaign had failed trials (see stage0/runs/campaign-manifest.json)"

echo "=== [4/5] ablation + environment-after capture"
python3 stage0/ablation_2x2.py --cells A,B,C,D --forms map-fault,write-path \
  --json stage0/raw/ablation.json || fail "ablation"
python3 stage0/env_capture.py --out stage0/runs/env-after.json \
  || fail "env-after capture"

echo "=== [5/5] report"
python3 stage0/report.py --runs stage0/runs --ablation stage0/raw/ablation.json \
  --env stage0/runs/env-before.json --out stage0/reports/stage0-report.md \
  || fail "report generation"

echo "=== stage0 campaign complete"
ls -lh stage0/reports/stage0-report.md
