#!/usr/bin/env bash
# epyc/40_bench_ml5m.sh — the 5M-record AI/ML matrix, ALL competing systems.
#
#   bash epyc/40_bench_ml5m.sh
#
# This is the artifact that reproduces RELEASE_v3.6.0.md §0 (the headline HN
# table) on real multi-socket NUMA. Competitors at 5M matches the repo's own
# convention: §0/§2 measure competitors at 5M and reserve 20M for forkrun.
#
# Structure: one invocation PER VARIANT, not one big invocation. Two reasons.
#   - bench_ml_pipeline.py writes --csv only at the very end of main(); a crash
#     in the expensive heavy leg would otherwise discard the light and medium
#     tables too.
#   - a crash in `heavy` (which is where the 20GB+ memfd and the multi-hour
#     competitor legs live) then cannot take the cheap cells with it.
# Fault injection runs as its own --fault-only invocation so it is not
# repeated once per variant.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

OUTD="$EPYC_OUT/20_benchmarks/ml5m"
ML5="$EPYC_DATA/ml5"
RECORDS=5000000
SWEEP="${EPYC_SWEEP_FAST}"
WMAX="$EPYC_WORKERS_MAX"
TRIALS="${EPYC_TRIALS:-3}"

mkdir -p "$OUTD"
cd "$EPYC_ROOT" || die "no repo root"

banner "40 ML pipeline @ ${RECORDS} records — full competitor matrix"
log "tmpdir : $ML5"
log "sweep  : $SWEEP  (cell worker max: $WMAX)"
log "trials : $TRIALS  (harness adds 1 warmup + 1 counting run per leg)"

# ---------------------------------------------------------------- guardrails --
# Refuse to run against a dataset that is not the size we asked for. The
# runner's own existence-only check would happily measure the wrong file.
for v in light medium heavy; do
    f="$ML5/ml_${v}.jsonl"
    if [ ! -f "$f" ]; then
        die "missing $f — run epyc/20_datagen.sh first"
    fi
    n=$(wc -l <"$f")
    if [ "$n" != "$RECORDS" ]; then
        die "$f has $n lines, expected $RECORDS. This is exactly the trap in
     bench_ml_pipeline.py: it reuses <tmpdir>/ml_<variant>.jsonl on existence
     alone, so a stale file would be measured while rates are reported as if
     the requested scale. Refusing to run."
    fi
    log "ok $f : $n lines, $(human "$(stat -c %s "$f")")"
done

# Report which competitor frameworks are actually importable, and pin that
# fact into the results. A missing framework makes its legs vanish from the
# CSV *silently* (only ray and hf_datasets print a note), so a reader who does
# not see this line will assume the row was measured.
banner "40a competitor availability probe"
{
    echo "# competitor framework probe (recorded $(date -u '+%FT%TZ'))"
    python3 - <<'PY'
import importlib
probe = [("ray", "ray"), ("polars", "polars"), ("duckdb", "duckdb"),
         ("hf_datasets", "datasets"), ("pandas", "pandas")]
for key, mod in probe:
    try:
        m = importlib.import_module(mod)
        print(f"  {key:<12} PRESENT  {getattr(m, '__version__', '?')}")
    except Exception as e:
        print(f"  {key:<12} ABSENT   ({type(e).__name__}) — its legs will be OMITTED from the CSV")
PY
} | tee "$OUTD/FRAMEWORKS.txt"

python3 -c "import forkrun, sys; sys.exit(0 if forkrun.__engine_version__ != 'unknown' else 1)" \
    || die "forkrun engine not loaded (FORKRUN_LIB missing) — run epyc/10_setup.sh"

# ------------------------------------------------------------------ variants --
RC=0
for v in light medium heavy; do
    if ! deadline_ok 5400; then
        stage_skip "40_bench_ml5m" "deadline: not starting variant=$v"
        break
    fi
    banner "40b variant=$v  (${RECORDS} records, sweep $SWEEP)"
    if run_logged "$OUTD/bench_${v}.log" "ml5m-$v" \
        python3 python/benchmarks/ml/bench_ml_pipeline.py \
            --records "$RECORDS" \
            --variants "$v" \
            --workers "$SWEEP" \
            --trials "$TRIALS" \
            --no-fault \
            --tmpdir "$ML5" \
            --csv "$OUTD/ml5m_${v}.csv"; then
        log "variant $v done -> $OUTD/ml5m_${v}.csv"
    else
        err "variant $v FAILED — see $OUTD/bench_${v}.log"
        RC=1
    fi
done

# ------------------------------------------------------------ fault injection --
banner "40c fault injection (crash-once SIGSEGV + transient errors)"
# Recorded reference rows are labelled -8w; run at a scale-appropriate worker
# count so the escrow/retry path is actually stressed on 96 cores.
if deadline_ok 2400; then
    if run_logged "$OUTD/bench_fault.log" "ml5m-fault" \
        python3 python/benchmarks/ml/bench_ml_pipeline.py \
            --records "$RECORDS" \
            --fault-only \
            --fault-workers "$WMAX" \
            --tmpdir "$ML5" \
            --csv "$OUTD/ml5m_fault.csv"; then
        log "fault injection done"
    else
        err "fault-injection run FAILED — see $OUTD/bench_fault.log"
        RC=1
    fi
else
    stage_skip "40_bench_ml5m_fault" "deadline"
fi

# ----------------------------------------------------------------- validation --
banner "40d validate totals"
# The harness reports lines_per_s but no time column, and a rate is only
# meaningful if the whole corpus was processed. Loss arithmetic lives in
# epyc/validate_cells.py so all four benchmark stages agree on the threshold.
VAL="$OUTD/validation.md"
if python3 "$EPYC_DIR/validate_cells.py" \
        --csv "$OUTD"/ml5m_*.csv \
        --records "$RECORDS" \
        --title "40 — ML pipeline @ ${RECORDS} records, all competitors" \
        --context "Expected valid counts at ${RECORDS} records (RELEASE_v3.6.0.md §0):
light 5000000 | medium 4997892 (quality-gate drops 2108) | heavy 4997982 (drops 2018).
serial and the native legs emit \`out=N/TOTAL\` with equal halves — they do not gate." \
        --out "$VAL"; then
    log "validation clean"
else
    err "VALIDATION FOUND SILENT LOSS — see $VAL"
    RC=1
fi

banner "40 ml5m COMPLETE"
log "CSVs in $OUTD"
log "framework availability: $OUTD/FRAMEWORKS.txt"
log "validation:            $OUTD/validation.txt"
[ "$RC" -eq 0 ] || warn "one or more variants failed; partial CSVs retained"
exit $RC
