#!/usr/bin/env bash
# epyc/51_bench_core.sh — the core Python engine suite at 10M lines.
#
#   bash epyc/51_bench_core.sh
#
#   python3 python/benchmarks/run_all.py --scale large --trials 5
#
# 44 registered benchmarks over core/ (throughput, memory, fault, baselines,
# splice, c_drain, batch_size, streaming_ingest) plus ml/bench_niches and
# ml/bench_numa. This is the suite whose canonical record is
# results/large.csv (10M lines, median of 5, 28c i9-7940X, engine v3.6.0) —
# i.e. RELEASE_v3.6.0.md §7.
#
# It does NOT cover the AI/ML matrix, tokenize, or stage0; those are separate
# entry points and are stages 40-44.
#
# WORKER CAP. Ten modules in core/ and ml/ hardcode
#     return min(8, os.cpu_count() or 4)
# which on this box would measure 8-way parallelism. epyc/10_setup.sh rewrites
# that to min($FORKRUN_BENCH_WORKERS_MAX, ...). If setup was skipped or the
# patch did not apply, this stage will silently produce 8-worker numbers; the
# check below makes that loud rather than quiet.
#
# SCALE. --scale large is 10M lines. That is the maximum bench_harness.SCALES
# offers, and it is where the committed large.csv sits, so it is the only
# directly comparable choice. 10M is well past the ~30 ms bring-up cliff, so
# these are steady-state numbers.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

OUTD="$EPYC_OUT/20_benchmarks/core"
SCALE="${EPYC_CORE_SCALE:-large}"
TRIALS="${EPYC_CORE_TRIALS:-5}"
FILTER="${EPYC_CORE_FILTER:-}"

mkdir -p "$OUTD"
cd "$EPYC_ROOT" || die "no repo root"

banner "51 core engine suite — --scale $SCALE --trials $TRIALS"

# ------------------------------------------------- verify the worker patch ----
banner "51a verify the benchmark worker cap was raised"
PATCHED=0
for f in python/benchmarks/core/bench_throughput.py python/benchmarks/ml/bench_niches.py; do
    if grep -q 'FORKRUN_BENCH_WORKERS_MAX' "$f" 2>/dev/null; then
        PATCHED=$((PATCHED + 1))
    else
        warn "$f still has the hardcoded min(8, ...) cap"
    fi
done
if [ "$PATCHED" -lt 2 ]; then
    err "worker-cap patch missing — these numbers would be 8-worker results."
    err "Re-run: bash epyc/10_setup.sh   (it applies the patch in step 10f)"
    exit 1
fi
log "worker cap patch confirmed on the sampled modules; cap=$EPYC_WORKERS_MAX"
python3 -c "
import os
os.environ.setdefault('FORKRUN_BENCH_WORKERS_MAX', '$EPYC_WORKERS_MAX')
import sys; sys.path.insert(0, 'python/benchmarks')
from core.bench_throughput import _nworkers
n = _nworkers()
print('  core.bench_throughput._nworkers() =', n)
sys.exit(0 if n > 8 else 1)
" || { err "_nworkers() still returns <= 8"; exit 1; }

python3 -c "import forkrun,sys; sys.exit(0 if forkrun.__engine_version__!='unknown' else 1)" \
    || die "forkrun engine not loaded — run epyc/10_setup.sh"

# --------------------------------------------------------------------- run ----
CSV="$OUTD/core_${SCALE}.csv"
RC=0
if deadline_ok 7200; then
    ARGS=(--scale "$SCALE" --trials "$TRIALS" --csv "$CSV")
    [ -n "$FILTER" ] && ARGS+=(--filter "$FILTER")
    banner "51b running $( [ -n "$FILTER" ] && echo "filter=$FILTER" || echo 'all 44 benchmarks' )"
    if run_logged "$OUTD/core_${SCALE}.log" "core-$SCALE" \
        python3 python/benchmarks/run_all.py "${ARGS[@]}"; then
        log "core suite done"
    else
        err "core suite returned non-zero — see $OUTD/core_${SCALE}.log"
        RC=1
    fi
else
    stage_skip "51_bench_core" "deadline"
    exit 0
fi

# ---------------------------------------------------------------- validate ----
banner "51c results"
if [ -f "$CSV" ]; then
    {
        echo "# core suite results — $SCALE, median of $TRIALS"
        echo
        echo "## all rows (cpu_pct = -1 means CPU% was not sampled for that row;"
        echo "## only headline rows sample it — that is intentional, not zero)"
        echo
        python3 - "$CSV" <<'PY'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
w = max((len(r.get("name","")) for r in rows), default=10)
print(f"{'name':<{w}}  {'rate (lines/s)':>16}  {'rss_mb':>8}  {'cpu%':>6}  mode")
print("-" * (w + 50))
for r in rows:
    print(f"{r.get('name',''):<{w}}  {r.get('lines_per_s',''):>16}  "
          f"{r.get('rss_mb',''):>8}  {r.get('cpu_pct',''):>6}  {r.get('mode','')}")
print(f"\nrows: {len(rows)}")
PY
    } | tee "$OUTD/core_${SCALE}.md"
else
    err "no CSV produced at $CSV"
    RC=1
fi

banner "51 core suite COMPLETE"
log "csv: $CSV"
exit $RC
