#!/usr/bin/env bash
# epyc/44_bench_headline.sh — the (dagger)/(max) pinned headline grid.
#
#   bash epyc/44_bench_headline.sh
#
# The single most directly comparable artifact this rental will produce: it
# emits the exact cell schema of python/benchmarks/results/headline_2026-09-29.csv
# so it can be diffed cell-for-cell against the published 28-worker UMA numbers.
#
# Runs both NUMA topologies so the born-local question is answered inside the
# same grid (nodes=1 vs nodes=auto). Order (dagger) cells are run before
# (max) cells; see headline.py for why (max) goes last.
#
# Cheap: 12 cells per topology, forkrun only, ~10 min per topology at 5M.
# Values 1 and auto rather than a bare int > 1 on purpose — _numa.py raises
# ValueError for an int above the online node count ("silently running UMA
# after nodes=N was requested would be a benchmarking lie").

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

OUTD="$EPYC_OUT/20_benchmarks/headline"
ML5="$EPYC_DATA/ml5"
RECORDS="${EPYC_HEADLINE_RECORDS:-5000000}"
WMAX="$EPYC_WORKERS_MAX"
TRIALS="${EPYC_TRIALS:-3}"
NODES="1,auto"

mkdir -p "$OUTD"
cd "$EPYC_ROOT" || die "no repo root"

banner "44 headline grid — (dagger) reactor vs (max) unordered ceiling"
log "records : $RECORDS"
log "workers : $WMAX"
log "nodes   : $NODES"
log "trials  : $TRIALS (+1 warmup per cell)"

for v in light medium heavy; do
    f="$ML5/ml_${v}.jsonl"
    [ -f "$f" ] || die "missing $f — run epyc/20_datagen.sh"
done

RC=0
if deadline_ok 5400; then
    if run_logged "$OUTD/headline.log" "headline-$RECORDS" \
        python3 epyc/headline.py \
            --records "$RECORDS" \
            --variants light,medium,heavy \
            --nodes "$NODES" \
            --workers "$WMAX" \
            --trials "$TRIALS" \
            --tmpdir "$ML5" \
            --csv "$OUTD/headline_${RECORDS}.csv"; then
        log "headline grid done"
    else
        err "headline grid returned non-zero — see $OUTD/headline.log"
        RC=1
    fi
else
    stage_skip "44_bench_headline" "deadline"
    exit 0
fi

# ------------------------------------------------------------- comparison ----
# Diff against the published reference. A delta-vs-reference on a different
# machine, topology and worker count is not a regression — the script says so
# in the output rather than letting someone quote the percentages.
CMP="$OUTD/VS_REFERENCE.md"
{
    echo "# headline grid vs python/benchmarks/results/headline_2026-09-29.csv"
    echo
    echo "Reference: 28c Intel i9-7940X, **UMA (1 node)**, 28 workers, median-of-3+warmup,"
    echo "bench_ml_pipeline.py harness, engine v3.6.0. Every published number in"
    echo "RELEASE_v3.6.0.md derives from that box."
    echo
    echo "This run: $EPYC_PHYS physical cores / $EPYC_NPROC threads, **$EPYC_NODES NUMA nodes**,"
    echo "$WMAX workers, $EPYC_MODEL_NAME, python $EPYC_PYTHON_VERSION, gcc $EPYC_GCC_VERSION."
    echo
    echo "> **The percentages below are NOT a regression measurement.** Eight axes"
    echo "> differ at once: socket count, NUMA node count, node distance (10 ->"
    echo "> $EPYC_XNODE_DIST), physical cores (14 -> $EPYC_PHYS), logical CPUs (28 -> $EPYC_NPROC),"
    echo "> worker count (28 -> $WMAX), userland (Fedora 7.1 kernel / glibc 2.43 /"
    echo "> python 3.14 vs Ubuntu $EPYC_DISTRO_ID), and MTU-free SMT behaviour. Read them as"
    echo "> *what this hardware does*, then compare against your own re-run of the"
    echo "> reference config on this box (\`EPYC_WORKERS_MAX=28\`, nodes=1)."
    echo
    python3 - "$OUTD/headline_${RECORDS}.csv" \
              "$EPYC_ROOT/python/benchmarks/results/headline_2026-09-29.csv" <<'PY'
import csv, sys
ref_path, new_path = sys.argv[2], sys.argv[1]
ref = {r["cell"]: r for r in csv.DictReader(open(ref_path))}
new = list(csv.DictReader(open(new_path)))

def f(r, k):
    try: return float(r[k])
    except (ValueError, TypeError, KeyError): return None

print("| cell | nodes | ref rec/s (28w UMA) | this rec/s | ratio | verdict |")
print("|---|---:|---:|---:|---:|---|")
for r in new:
    cell, nodes = r["cell"], r.get("nodes", "?")
    a = f(ref.get(cell, {}), "rate_rec_s")
    b = f(r, "rate_rec_s")
    ratio = f"{b/a:.2f}x" if a and b else "—"
    v = r.get("verdict", "")
    # Only compare like-for-like: the reference has no `nodes` column at all.
    cmpnote = "EXACT" if v == "EXACT" else v
    print(f"| {cell} | {nodes} | {a:,.0f} | {b:,.0f} | {ratio} | {cmpnote} |"
          if a and b else
          f"| {cell} | {nodes} | {a or 0:,.0f} | {b or 0:,.0f} | {ratio} | {cmpnote} |")
print()
print("Reference `valid` counts (the quality-gate split): light 5000000, medium 4997892, heavy 4997982.")
print("Any row whose verdict is not EXACT/ok(quality-gate) is a correctness finding, not a perf result.")
PY
} | tee "$CMP"

banner "44 headline grid COMPLETE"
log "csv: $OUTD/headline_${RECORDS}.csv"
log "comparison: $CMP"
exit $RC
