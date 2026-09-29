#!/usr/bin/env bash
# epyc/43_bench_ml20m.sh — 20M-record steady state, forkrun only.
#
#   bash epyc/43_bench_ml20m.sh
#
# Why forkrun-only at 20M: that is the repo's own convention, not a shortcut we
# invented. RELEASE_v3.6.0.md §0 (headline table) measures every competing
# system at 5M and §2's 20M rows are exclusively forkrun C-plugin / Python UDF
# / spawn, with the note that "competitor rows keep their original dates (those
# codebases didn't change)". Re-running Ray and HF at 20M would cost ~4.5 h and
# prove nothing the 5M matrix does not.
#
# Ray and HF are blocked for this stage only, via
# epyc/blockmods/sitecustomize.py on PYTHONPATH. The runner's framework probe
# takes its not-installed branch, so their legs are omitted from the CSV
# *explicitly* rather than silently missing. Nothing is uninstalled, so stage
# 42 and 40 keep their Ray/HF rows.
#
# heavy-20M is the highest-risk cell in the entire harness. The input is ~26.9 GB,
# it materialises into a shmem memfd of the same size, and the output orderer
# collects ~6.1 GB in the parent. It is also the exact workload on which F-NUMA1
# surfaced as ~25% silent loss at 4 nodes. This box has 256 GB and 8 nodes.
# --variants is therefore run one variant per invocation so a loss event is
# contained and attributable.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

OUTD="$EPYC_OUT/20_benchmarks/ml20m"
ML20="$EPYC_DATA/ml20"
RECORDS=20000000
SWEEP="${EPYC_SWEEP_FAST}"
WMAX="$EPYC_WORKERS_MAX"
TRIALS="${EPYC_TRIALS:-3}"
VARIANTS="${EPYC_ML20_VARIANTS:-light medium heavy}"

mkdir -p "$OUTD"
cd "$EPYC_ROOT" || die "no repo root"

banner "43 ML pipeline @ ${RECORDS} records — forkrun only (Ray/HF blocked)"
log "tmpdir : $ML20"
log "sweep  : $SWEEP"
log "variants: $VARIANTS"

# Block Ray + HF for this stage only.
export EPYC_BLOCK_MODULES="ray,datasets"
export PYTHONPATH="$EPYC_DIR/blockmods:$EPYC_ROOT/python${PYTHONPATH:+:$PYTHONPATH}"

banner "43a confirm the block took effect"
{
    echo "# expecting ray and datasets to be UNIMPORTABLE in this stage"
    python3 - <<'PY'
import importlib
for m in ("ray", "datasets", "polars", "duckdb", "numpy", "forkrun"):
    try:
        mod = importlib.import_module(m)
        print(f"  {m:<10} IMPORTABLE   {getattr(mod, '__version__', '?')}")
    except ImportError as e:
        print(f"  {m:<10} blocked/absent ({e})")
PY
} | tee "$OUTD/BLOCKED_FRAMEWORKS.txt"

# ---------------------------------------------------------------- guardrails --
AVAIL=$(df -B1 --output=avail "$EPYC_DATA" | tail -1 | tr -d ' ')
if [ "$AVAIL" -lt 40000000000 ]; then
    warn "only $(human "$AVAIL") free on $EPYC_DATA — the 20M set needs ~38 GB"
    die "refusing to start: a full disk mid-run costs more rental time than stopping now"
fi

for v in $VARIANTS; do
    f="$ML20/ml_${v}.jsonl"
    [ -f "$f" ] || die "missing $f — run epyc/20_datagen.sh"
    n=$(wc -l <"$f")
    [ "$n" = "$RECORDS" ] || die "$f has $n lines, expected $RECORDS"
    log "ok $(basename "$f") : $n lines, $(human "$(stat -c %s "$f")")"
done

# RAM headroom for the forkrun legs: input memfd ~= file size, plus collected
# output in the parent. heavy-20M is ~27 GB in + ~6 GB out.
MEMAVAIL=$(awk '/^MemAvailable:/{print $2*1024}' /proc/meminfo)
log "MemAvailable: $(human "$MEMAVAIL")"
for v in $VARIANTS; do
    sz=$(stat -c %s "$ML20/ml_${v}.jsonl")
    # ~1.6x file size is a safe peak estimate (memfd + output + indexer read-ahead)
    need=$(( sz * 16 / 10 ))
    if [ "$MEMAVAIL" -lt "$need" ]; then
        err "variant $v may OOM: needs ~$(human "$need"), have $(human "$MEMAVAIL")"
    else
        log "variant $v headroom ok: needs ~$(human "$need")"
    fi
done

python3 -c "import forkrun,sys; sys.exit(0 if forkrun.__engine_version__!='unknown' else 1)" \
    || die "forkrun engine not loaded — run epyc/10_setup.sh"

# --------------------------------------------------------------------- run ----
RC=0
for v in $VARIANTS; do
    if ! deadline_ok 10800; then
        stage_skip "43_bench_ml20m_$v" "deadline"
        break
    fi
    banner "43b variant=$v @ ${RECORDS} records (forkrun only, Ray/HF blocked)"
    if run_logged "$OUTD/bench_${v}.log" "ml20m-$v" \
        python3 python/benchmarks/ml/bench_ml_pipeline.py \
            --records "$RECORDS" \
            --variants "$v" \
            --workers "$SWEEP" \
            --trials "$TRIALS" \
            --no-fault \
            --tmpdir "$ML20" \
            --csv "$OUTD/ml20m_${v}.csv"; then
        log "variant $v done"
    else
        err "variant $v FAILED — see $OUTD/bench_${v}.log"
        # The W-P0LEGACY regression class presents as
        #   RuntimeError: forkrun: scan failed (status 9)
        # i.e. SIGKILL of a bounded helper join, not a hang. Distinguish that
        # from a genuine hang so triage does not guess.
        if grep -qE 'scan failed \(status 9\)|status 9' "$OUTD/bench_${v}.log" 2>/dev/null; then
            err "  -> signature matches the W-P0LEGACY helper-join SIGKILL class"
            err "     (fixed at e0081ef2, present at HEAD). Report upstream, do not retry blindly."
        fi
        RC=1
    fi
done

# ---------------------------------------------------------------- validate ----
banner "43c validate — the F-NUMA1 question at $EPYC_NODES nodes and 20M records"
# Shared loss arithmetic (epyc/validate_cells.py): the quality gate drops a
# FRACTION of the corpus, not a count, so this is correct at any --records.
AUDIT="$OUTD/validation.md"
if python3 "$EPYC_DIR/validate_cells.py" \
        --csv "$OUTD"/ml20m_*.csv \
        --records "$RECORDS" \
        --title "43 — ML pipeline @ ${RECORDS} records, forkrun only, $EPYC_NODES NUMA nodes" \
        --context "Expected valid counts at ${RECORDS} records (RELEASE_v3.6.0.md §2, exact on both UMA and @4 at 4 nodes):
light 20000000 | medium 19991640 | heavy 19991658.

F-NUMA1 is the risk: a stalled node's ChunkMeta slot recycled by a meta-ring lap
makes a run return ~25% of its records with no error. It was found at 4 nodes on
heavy-20M. This box has $EPYC_NODES nodes, so the meta-lifetime bound is
$(( 2048 / EPYC_NODES )) chunks/node vs 512 there — the tightest configuration the
engine has ever run under." \
        --out "$AUDIT"; then
    log "no cell lost records at $EPYC_NODES nodes / $RECORDS records"
else
    err "SILENT DATA LOSS detected at $EPYC_NODES nodes / $RECORDS records"
    err "See $AUDIT. This is the most valuable output this rental could produce."
    err "Treat every throughput number in this stage as untrusted until the"
    err "affected cell is re-run in isolation."
    RC=1
fi

banner "43 ml20m COMPLETE"
log "CSVs in $OUTD ; audit: $AUDIT"
exit $RC
