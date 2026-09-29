#!/usr/bin/env bash
# epyc/42_bench_tokenize.sh — LLM tokenization matrix at 2,000,000 documents.
#
#   bash epyc/42_bench_tokenize.sh
#
# Reproduces RELEASE_v3.6.0.md §5 on real NUMA. That section's steady-state
# numbers are 500k and 1M docs; the 20k study is explicitly retired to
# "startup-latency microbenchmark" status because at ~200 ms total, bring-up
# dominates and the rank order wobbles with box state.
#
# 2M docs is the largest corpus the recorded 2M spot-check used
# (spotcheck_post_wrel6.md: C 316.0k docs/s vs Executor 157.8k = 2.00x), so
# 2M is directly comparable to that cell and comfortably past the regime where
# fixed bring-up matters.
#
# All 8 systems run: serial, multiprocessing.Pool, ProcessPoolExecutor,
# forkrun Python UDF, forkrun C plugin, HF Datasets, Ray Data, Polars
# map_batches. Availability is probed by import, so a missing framework drops
# out of the CSV silently — the probe output below is the record of what was
# actually measured.
#
# Cost note: Ray is ~14x slower than the C plugin here and runs 2 executions
# per worker point, so it dominates the stage. Polars is a serial UDF
# (POLARS_MAX_THREADS=1 matches the default per tokenize_study.md) and is
# likewise slow but runs once.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

OUTD="$EPYC_OUT/20_benchmarks/tokenize"
TOK="$EPYC_DATA/tok2M"
DOCS="${EPYC_TOKENIZE_DOCS:-2000000}"
SWEEP="${EPYC_SWEEP_TOK:-$EPYC_SWEEP_FAST}"
TRIALS="${EPYC_TRIALS:-3}"

mkdir -p "$OUTD"
cd "$EPYC_ROOT" || die "no repo root"

banner "42 tokenize @ ${DOCS} docs — 8-system matrix"
log "tmpdir : $TOK"
log "sweep  : $SWEEP"
log "trials : $TRIALS"

# ---------------------------------------------------------------- guardrails --
CORPUS="$TOK/tok_corpus.jsonl"
VOCAB="$CORPUS.vocab"
[ -f "$CORPUS" ] || die "missing $CORPUS — run epyc/20_datagen.sh"
[ -f "$VOCAB" ] || die "missing $VOCAB sidecar — run epyc/20_datagen.sh"
# The .vocab is the single source of truth shared by every system; if it is
# absent the C plugin falls back to its internal construction and the
# "plugin outputs exact-JSON-equal vs Python" claim is not being tested.
n=$(wc -l <"$CORPUS")
[ "$n" = "$DOCS" ] || die "$CORPUS has $n docs, expected $DOCS (the runner reuses tok_corpus.jsonl on existence alone)"
log "ok corpus: $n docs, $(human "$(stat -c %s "$CORPUS")")"
log "ok vocab : $(wc -l <"$VOCAB") entries, $(human "$(stat -c %s "$VOCAB")")"

banner "42a framework availability probe"
{
    echo "# tokenize framework probe (recorded $(date -u '+%FT%TZ'))"
    python3 - <<'PY'
import importlib
for key, mod in (("ray", "ray"), ("polars", "polars"), ("duckdb", "duckdb"),
                 ("hf_datasets", "datasets"), ("pandas", "pandas")):
    try:
        m = importlib.import_module(mod)
        print(f"  {key:<12} PRESENT  {getattr(m, '__version__', '?')}")
    except Exception as e:
        print(f"  {key:<12} ABSENT   ({type(e).__name__}) — its rows will be OMITTED from the CSV")
PY
    echo
    echo "NOTE: bench_tokenize.py probes and versions duckdb but never benchmarks it."
    echo "      The 8 measured systems are: serial, pool, executor, forkrun-python,"
    echo "      forkrun-C-plugin, hf_datasets, ray, polars."
} | tee "$OUTD/FRAMEWORKS.txt"

python3 -c "import forkrun,sys; sys.exit(0 if forkrun.__engine_version__!='unknown' else 1)" \
    || die "forkrun engine not loaded — run epyc/10_setup.sh"

# --------------------------------------------------------------------- run ----
RC=0
if deadline_ok 14400; then
    banner "42b running the matrix (this is the long one: Ray dominates)"
    if run_logged "$OUTD/bench_tokenize.log" "tokenize-$DOCS" \
        python3 python/benchmarks/tokenize/bench_tokenize.py \
            --docs "$DOCS" \
            --workers "$SWEEP" \
            --trials "$TRIALS" \
            --tmpdir "$TOK" \
            --csv "$OUTD/tokenize_${DOCS}.csv"; then
        log "tokenize matrix done"
    else
        err "tokenize FAILED — see $OUTD/bench_tokenize.log"
        RC=1
    fi
else
    stage_skip "42_bench_tokenize" "deadline"
    exit 0
fi

# ---------------------------------------------------------------- validate ----
banner "42c validate"
VAL="$OUTD/validation.md"
if python3 "$EPYC_DIR/validate_cells.py" \
        --csv "$OUTD/tokenize_${DOCS}.csv" \
        --records "$DOCS" \
        --title "42 — tokenize @ ${DOCS} docs, 8 systems" \
        --context "Every system should complete the full corpus. The recorded 2M
spot-check (spotcheck_post_wrel6.md) had plugin 2000000/2000000 and executor
2000000/2000000, with plugin output exact-JSON-equal to the Python UDF.
Tokenize has no quality gate, so the expected count equals the corpus size." \
        --out "$VAL"; then
    log "validation clean"
else
    err "VALIDATION FOUND SILENT LOSS — see $VAL"
    RC=1
fi

# Best-per-system summary, the shape §5 is written in.
banner "42d best per system"
python3 - "$OUTD/tokenize_${DOCS}.csv" <<'PY' | tee "$OUTD/BEST.md"
import csv, sys
from collections import defaultdict
rows = list(csv.DictReader(open(sys.argv[1])))
best = defaultdict(float)
for r in rows:
    sysname = r.get("mode") or r.get("name", "?")
    try:
        rate = float(r.get("lines_per_s") or 0)
    except ValueError:
        continue
    best[sysname] = max(best[sysname], rate)
print("| system | best docs/s |")
print("|---|---:|")
for k, v in sorted(best.items(), key=lambda kv: -kv[1]):
    print(f"| {k} | {v:,.0f} |")
PY

banner "42 tokenize COMPLETE"
log "csv: $OUTD/tokenize_${DOCS}.csv"
[ "$RC" -eq 0 ] || warn "see $OUTD/bench_tokenize.log"
exit $RC
