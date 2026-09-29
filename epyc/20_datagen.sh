#!/usr/bin/env bash
# epyc/20_datagen.sh — generate every input dataset, in parallel, up front.
#
#   bash epyc/20_datagen.sh
#
# Two reasons this is a separate stage:
#  1. run_all.sh launches it in the BACKGROUND and lets it run underneath the
#     unit-test stages, so ~40 min of pure generation is not billed twice.
#  2. bench_ml_pipeline.py reuses <tmpdir>/ml_<variant>.jsonl on *existence
#     alone* — the filename carries no record count. Reusing a 5M tmpdir for a
#     20M run silently measures 5M and reports 4x-inflated rates. Each scale
#     therefore gets its own directory, and this script stages the exact
#     filenames the runners look for.
#
# Everything is deterministic (ml_data_gen.SEED=42, tokenize SEED=2024,
# stage0 SEED=20260919), so a re-run reproduces byte-identical files.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

GENLOG="$EPYC_OUT/03_datagen"
mkdir -p "$GENLOG" "$EPYC_DATA"

ML5="$EPYC_DATA/ml5"
ML20="$EPYC_DATA/ml20"
TOK="$EPYC_DATA/tok2M"
NUMA5="$EPYC_DATA/numa5"
S0="$EPYC_ROOT/python/benchmarks/stage0/inputs"

RECORDS_5M=5000000
RECORDS_20M=20000000
TOKENIZE_DOCS=2000000
BENCH_LINES=100000000

banner "20 data generation"
log "data root: $EPYC_DATA"
df -h "$EPYC_DATA" | tail -1 | tee -a "$GENLOG/df.txt"

for d in "$ML5" "$ML20" "$TOK" "$NUMA5"; do mkdir -p "$d"; done

PY="$EPYC_VENV/bin/python"

# gen_ml <outdir> <variant> <records>
#   Writes <outdir>/ml_<variant>.jsonl with malformed_pct=0 (the runner's
#   default, so rates are comparable to the published baselines).
gen_ml() {
    local outdir="$1" variant="$2" recs="$3"
    local out="$outdir/ml_${variant}.jsonl"
    if [ -f "$out" ] && [ "$(wc -l <"$out")" = "$recs" ]; then
        log "have $out ($(wc -l <"$out") lines)"
        return 0
    fi
    log "generating $out : $recs records, variant=$variant, malformed=0.0%"
    "$PY" -c "
import sys
sys.path.insert(0, '$EPYC_ROOT/python/benchmarks/ml')
from ml_data_gen import generate_data
generate_data('$out', $recs, variant='$variant')
print('done', '$out')
" 2>&1 | tee -a "$GENLOG/gen_ml_$(basename "$outdir")_${variant}.log"
    local got
    got=$(wc -l <"$out")
    if [ "$got" != "$recs" ]; then
        err "LINE COUNT MISMATCH for $out: got $got want $recs"
        return 1
    fi
    return 0
}

# gen_fault <outdir> <records>
#   The fault corpus is medium at the same record count but 5% malformed, and
#   bench_ml_pipeline.py looks for it at the literal path <tmpdir>/ml_fault.jsonl
#   (line 905). It is NOT a prefix of ml_medium.jsonl: malformed_pct changes rng
#   consumption, so it needs its own file and must never touch ml_medium.jsonl.
gen_fault() {
    local outdir="$1" recs="$2"
    local out="$outdir/ml_fault.jsonl"
    if [ -f "$out" ] && [ "$(wc -l <"$out")" = "$recs" ]; then
        log "have $out ($(wc -l <"$out") lines)"
        return 0
    fi
    log "generating $out : $recs records, variant=medium, malformed=5.0%"
    "$PY" -c "
import sys
sys.path.insert(0, '$EPYC_ROOT/python/benchmarks/ml')
from ml_data_gen import generate_data
generate_data('$out', $recs, variant='medium', malformed_pct=5.0)
print('done', '$out')
" 2>&1 | tee -a "$GENLOG/gen_fault.log"
    local got
    got=$(wc -l <"$out")
    if [ "$got" != "$recs" ]; then
        err "LINE COUNT MISMATCH for $out: got $got want $recs"
        return 1
    fi
    return 0
}

# ------------------------------------------------------------- parallel gen --
banner "20a launching generators (background, one core each)"

# 5M set — consumed by stage 40 (competitor matrix) and stage 41 (numa study).
gen_ml "$ML5" light  "$RECORDS_5M" >"$GENLOG/j_5m_light.log"  2>&1 & P1=$!
gen_ml "$ML5" medium "$RECORDS_5M" >"$GENLOG/j_5m_medium.log" 2>&1 & P2=$!
gen_ml "$ML5" heavy  "$RECORDS_5M" >"$GENLOG/j_5m_heavy.log"  2>&1 & P3=$!
gen_fault "$ML5"     "$RECORDS_5M" >"$GENLOG/j_5m_fault.log"  2>&1 & P4=$!

# 20M set — stage 43 (forkrun-only steady state). Largest single file is
# heavy 20M at ~26.9 GB.
gen_ml "$ML20" light  "$RECORDS_20M" >"$GENLOG/j_20m_light.log"  2>&1 & P5=$!
gen_ml "$ML20" medium "$RECORDS_20M" >"$GENLOG/j_20m_medium.log" 2>&1 & P6=$!
gen_ml "$ML20" heavy  "$RECORDS_20M" >"$GENLOG/j_20m_heavy.log"  2>&1 & P7=$!

# Tokenize corpus + shared .vocab sidecar.
(
    out="$TOK/tok_corpus.jsonl"
    if [ -f "$out" ] && [ -f "$out.vocab" ] && [ "$(wc -l <"$out")" = "$TOKENIZE_DOCS" ]; then
        log "have $out"
    else
        log "generating $out : $TOKENIZE_DOCS docs (~3.9 GB)"
        "$PY" -c "
import sys
sys.path.insert(0, '$EPYC_ROOT/python/benchmarks/tokenize')
from tokenize_data_gen import generate_corpus
generate_corpus('$out', $TOKENIZE_DOCS)
print('done', '$out')
" 2>&1 | tee -a "$GENLOG/gen_tokenize.log"
    fi
) >"$GENLOG/j_tokenize.log" 2>&1 & P8=$!

# Stage0 inputs (1M JSONL + 400 MB int32 tensor + 10M lines + sha256 manifest).
(
    "$PY" "$EPYC_ROOT/python/benchmarks/stage0/gen_inputs.py" --out "$S0"
) >"$GENLOG/j_stage0.log" 2>&1 & P9=$!

# Bash-benchmark inputs. run_benchmark.bash generates these itself if absent;
# doing it now puts them in page cache and overlaps the cost.
#   f1 = 100M blank lines (100 MB)   f2 = seq 100M (889 MB)   f3 = find paths
(
    cd "$EPYC_ROOT/BENCHMARKS" || exit 1
    [ -f ./f1 ] || { log "generating BENCHMARKS/f1 ($BENCH_LINES blank lines)"; yes $'\n' | head -n "$BENCH_LINES" >f1; }
    [ -f ./f2 ] || { log "generating BENCHMARKS/f2 (seq $BENCH_LINES)"; seq "$BENCH_LINES" >f2; }
    [ -f ./f3 ] || { log "generating BENCHMARKS/f3 (find /usr /etc /opt /var /home)"; find /usr /etc /opt /var /home -type f >f3 2>/dev/null; }
    log "bash benchmark inputs: $(ls -la f1 f2 f3 2>/dev/null | wc -l) files ready"
) >"$GENLOG/j_bashinputs.log" 2>&1 & P10=$!

banner "20b waiting for generators"
log "10 jobs in flight (each single-threaded; machine has $EPYC_NPROC logical CPUs)"

RC=0
for p in P1 P2 P3 P4 P5 P6 P7 P8 P9 P10; do
    eval "pid=\$$p"
    if wait "$pid"; then :; else
        err "generator job $p (pid $pid) FAILED — see $GENLOG/j_*.log"
        RC=1
    fi
done

# -------------------------------------------------- derived files for numa5 --
banner "20c staging bench_numa_5m's expected filenames"
# bench_numa_5m.py looks for, inside --tmpdir:
#     ml_<variant>_<records>.jsonl     (line 285)
#     ml_medium_1M.jsonl               (line 348, the scaling-sweep corpus)
#     spawn_1M.jsonl                   (line 405, an independent 1M medium file)
#     tok_<docs>.jsonl (+ .vocab)      (line 373)
# The ml_* files are byte-identical to the ml5 set, so hardlink rather than
# regenerate. ml_medium_1M / spawn_1M are the 1M-record prefix of the 5M medium
# file (ml_data_gen seeds a fresh Random(42) per call, so 1M is an exact prefix
# of 5M) — take it with head instead of a 90-second regen.
link_or_copy() {
    local src="$1" dst="$2"
    [ -f "$src" ] || { err "missing source for hardlink: $src"; return 1; }
    rm -f "$dst"
    if ln "$src" "$dst" 2>/dev/null; then
        log "hardlink $(basename "$dst")"
    else
        log "hardlink failed (cross-device?) — copying $(basename "$dst")"
        cp --reflink=auto "$src" "$dst" || return 1
    fi
    return 0
}
for v in light medium heavy; do
    link_or_copy "$ML5/ml_${v}.jsonl" "$NUMA5/ml_${v}_${RECORDS_5M}.jsonl"
done
link_or_copy "$TOK/tok_corpus.jsonl"          "$NUMA5/tok_${TOKENIZE_DOCS}.jsonl"
link_or_copy "$TOK/tok_corpus.jsonl.vocab"    "$NUMA5/tok_${TOKENIZE_DOCS}.jsonl.vocab"
if [ ! -f "$NUMA5/ml_medium_1M.jsonl" ]; then
    log "extracting the 1M-record medium prefix (head -n 1000000)"
    head -n 1000000 "$ML5/ml_medium.jsonl" >"$NUMA5/ml_medium_1M.jsonl"
fi
# spawn_1M.jsonl is generated identically to ml_medium_1M.jsonl
# (generate_data(path, 1_000_000, "medium"), lines 405-408) — same bytes.
link_or_copy "$NUMA5/ml_medium_1M.jsonl" "$NUMA5/spawn_1M.jsonl"

# ------------------------------------------------------------------ manifest --
banner "20d manifest (line counts + sha256)"
MAN="$EPYC_OUT/03_datagen/DATA_MANIFEST.txt"
{
    echo "# forkrun EPYC rental — generated dataset manifest"
    echo "# generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "# determinism: ml_data_gen.SEED=42  tokenize_data_gen.SEED=2024  stage0.SEED=20260919"
    echo
    printf '%-12s %18s %14s  %s\n' "dir" "bytes" "lines" "file"
} >"$MAN"

manifest_one() {
    local f="$1" want_lines="${2:-}"
    [ -f "$f" ] || { printf '%-12s %18s %14s  %s\n' "<MISSING>" - - "${f#$EPYC_DATA/}" >>"$MAN"; return 1; }
    local sz ln sha
    sz=$(stat -c %s "$f")
    ln=$(wc -l <"$f")
    sha=$(sha256sum "$f" | cut -c1-16)
    printf '%-12s %18s %14s  %s  sha256:%s\n' \
        "$(basename "$(dirname "$f")")" "$sz" "$ln" "$(basename "$f")" "$sha" >>"$MAN"
    if [ -n "$want_lines" ] && [ "$ln" != "$want_lines" ]; then
        err "LINE COUNT MISMATCH ${f}: got $ln want $want_lines"
        return 1
    fi
    return 0
}

VFAIL=0
for v in light medium heavy; do
    manifest_one "$ML5/ml_${v}.jsonl"  "$RECORDS_5M"   || VFAIL=1
done
manifest_one "$ML5/ml_fault.jsonl"         "$RECORDS_5M"   || VFAIL=1
for v in light medium heavy; do
    manifest_one "$ML20/ml_${v}.jsonl" "$RECORDS_20M"  || VFAIL=1
done
manifest_one "$TOK/tok_corpus.jsonl"        "$TOKENIZE_DOCS" || VFAIL=1
manifest_one "$TOK/tok_corpus.jsonl.vocab"  ""             || VFAIL=1
for v in light medium heavy; do
    manifest_one "$NUMA5/ml_${v}_${RECORDS_5M}.jsonl" "$RECORDS_5M" || VFAIL=1
done
manifest_one "$NUMA5/ml_medium_1M.jsonl"    "1000000"      || VFAIL=1
manifest_one "$NUMA5/spawn_1M.jsonl"        "1000000"      || VFAIL=1
manifest_one "$NUMA5/tok_${TOKENIZE_DOCS}.jsonl" "$TOKENIZE_DOCS" || VFAIL=1
manifest_one "$S0/transform_10M.txt"        "10000000"     || VFAIL=1
for f in "$EPYC_ROOT/BENCHMARKS/f1" "$EPYC_ROOT/BENCHMARKS/f2" "$EPYC_ROOT/BENCHMARKS/f3"; do
    manifest_one "$f" "" || VFAIL=1
done

{ echo; echo "totals:"; echo "  $(df -h "$EPYC_DATA" | tail -1)"; } >>"$MAN"
cat "$MAN" | tee -a "$GENLOG/manifest.log"

if [ "$RC" -ne 0 ] || [ "$VFAIL" -ne 0 ]; then
    banner "20 data generation INCOMPLETE"
    err "generator failures: $RC   manifest validation failures: $VFAIL"
    warn "stages that need the missing data will refuse to run; see $MAN"
    exit 1
fi

banner "20 data generation COMPLETE"
log "total on $EPYC_DATA: $(du -sh "$EPYC_DATA" 2>/dev/null | cut -f1)"
exit 0
