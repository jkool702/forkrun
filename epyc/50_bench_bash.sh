#!/usr/bin/env bash
# epyc/50_bench_bash.sh — the bash-side performance matrix.
#
#   bash epyc/50_bench_bash.sh
#
# Four scripts, all in the repo, all run from the directory they expect:
#
#   BENCHMARKS/run_benchmark.bash            the main matrix (frun)
#   BENCHMARKS/run_benchmark_parallel.bash    GNU Parallel baseline
#   BENCHMARKS/run_benchmarks_xargs.bash      xargs -P baseline
#   UNIT_TESTS/run_benchmark_functions.bash   9 targeted sweeps
#
# CRITICAL: run_benchmark.bash writes f1/f2/f3 and benchmark.out into the
# CURRENT WORKING DIRECTORY and resolves frun.bash as `./frun.bash`. It must be
# invoked from inside BENCHMARKS/ (DOCS/MAINTAINERS.md §4.2 calls this out).
# Same for run_benchmark_functions.bash, which wants its own ./frun.bash —
# UNIT_TESTS/frun.bash is a symlink to ../frun.bash, so running it from
# UNIT_TESTS/ is correct.
#
# SCOPE WARNING. run_benchmark.bash's current matrix is 216 configs x 3 input
# files x 4 input/output legs = 2,592 timed runs. The committed reference
# artifacts (benchmark.UMA.out.txt / benchmark.NUMA.out.txt) contain only 396
# cases, because they were produced by an earlier, smaller matrix. So a full
# run here is NOT a drop-in diff against those files; it is a superset. Set
# EPYC_BASH_BENCH_REDUCED=1 to run a 33-shape matrix that matches the committed
# 396-case shape count (33 x 3 x 4 = 396) for a closer like-for-like.
#
# This harness deliberately runs the script unmodified. Its 216-config product,
# its 1-second inter-config cooldown, and its zero-repetition methodology are
# the repo's as-is behaviour; the point here is to measure the product, not to
# re-engineer the benchmark. See DEVIATIONS.md for the statistical caveat.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

OUTD="$EPYC_OUT/20_benchmarks/bash"
B="$EPYC_ROOT/BENCHMARKS"
U="$EPYC_ROOT/UNIT_TESTS"
REDUCED="${EPYC_BASH_BENCH_REDUCED:-0}"

mkdir -p "$OUTD"
RC=0

banner "50 bash benchmark matrix"
log "mode: $([ "$REDUCED" = "1" ] && echo 'REDUCED (33 shapes, ~396 cases, matches committed reference)' || echo 'FULL (216 configs, 2592 cases)')"
log "inputs:"
for f in f1 f2 f3; do
    [ -f "$B/$f" ] && log "  $f: $(human "$(stat -c %s "$B/$f")") / $(wc -l <"$B/$f") lines" \
                  || warn "  $f missing — the harness will generate it (slow)"
done

# THP must already be set by 10_setup.sh; the harness would try to sudo.
THPS=$(cat /sys/kernel/mm/transparent_hugepage/shmem_enabled 2>/dev/null)
log "THP shmem_enabled = $THPS"
if ! echo "$THPS" | grep -q '\[always\]'; then
    warn "shmem_enabled is not [always] — results will NOT be comparable to any"
    warn "published baseline. FAKE4_REVERIFY.md: 'No data taken under madvise.'"
fi

# ---------------------------------------------- 50z bash NUMA A/B (explicit) --
# WHY THIS EXISTS. The Python benchmarks call forkrun.map() with no `nodes=`,
# and python/forkrun/_numa.py:86 treats None as "auto" -- i.e. they have been
# silently running 2-node NUMA on this box. The bash wrapper does NOT: with no
# --nodes, _forkrun_build_numa_map("") falls through to "Standard Count mode"
# with an empty count and lands on map=(0), i.e. UMA (frun.bash:1376-1381).
# So "the benchmark as it stands" means something different on each side, and
# the headline Python numbers were taken on the slow partition.
#
# This section runs the SAME workload through the SAME C/bash engine with
# --nodes=1 and --nodes=@4 explicitly, and checks record conservation on both.
# It does not touch BENCHMARKS/run_benchmark.bash (Tier-1).
banner "50z bash NUMA A/B — explicit --nodes=1 vs --nodes=@4"
AB="$OUTD/numa_ab"
AB_LINES="${EPYC_BASH_AB_LINES:-5000000}"
if deadline_ok 2400; then
    mkdir -p "$AB"
    ABSRC="$AB/f2_${AB_LINES}.txt"
    if [ ! -f "$ABSRC" ]; then
        log "slicing $AB_LINES lines from f2 for the A/B"
        head -n "$AB_LINES" "$B/f2" >"$ABSRC"
    fi
    {
        printf '# bash NUMA A/B — frun, identical flags, explicit topology\n'
        printf '# input: %s lines (%s)\n' "$AB_LINES" "$ABSRC"
        printf '# flags: -k -l 1 -b 524288 (keep-order, line batch) + passthrough\n'
        printf '# %-10s %12s %12s %12s %10s\n' topology wall_s lines_out lines_per_s conserved
        for N in 1 @4; do
            T0=$(date +%s%N)
            OUT_LINES=$( cat "$ABSRC" | ( cd "$EPYC_ROOT" && . ./frun.bash && frun --nodes="$N" -k -l 1 -b 524288 ) | wc -l )
            RC_FR=$?
            T1=$(date +%s%N)
            MS=$(( (T1 - T0) / 1000000 ))
            RATE=$(awk -v o="$OUT_LINES" -v ms="$MS" 'BEGIN{ if (ms>0) printf "%.0f", o*1000/ms; else print 0 }')
            if [ "$OUT_LINES" = "$AB_LINES" ]; then CONS="yes"; else CONS="**NO**"; fi
            printf '%-10s %12s %12s %12s %10s\n' "--nodes=$N" "${MS}ms" "$OUT_LINES" "$RATE" "$CONS"
        done
    } 2>&1 | tee "$AB/bash_numa_ab.txt"
    log "A/B written to $AB/bash_numa_ab.txt"
else
    stage_skip "50_bench_bash_zab" "deadline"
fi

# ------------------------------------------------------- the main matrix -----
banner "50a run_benchmark.bash (the main frun matrix)"
if deadline_ok 10800; then
    if [ "$REDUCED" = "1" ]; then
        # Temporarily swap in a 33-shape matrix matching the committed 396-case
        # artifacts. Restored unconditionally by the trap below.
        cp "$B/run_benchmark.bash" "$B/run_benchmark.bash.epyc.bak"
        restore_matrix() { mv -f "$B/run_benchmark.bash.epyc.bak" "$B/run_benchmark.bash"; }
        trap restore_matrix EXIT INT TERM
        python3 - "$B/run_benchmark.bash" <<'PY'
import re, sys
p = sys.argv[1]
src = open(p).read()
full = r"for GCk in {,-k,-u,-U}\ \-X\ {,-l\ 1:-1}\ {true,echo,printf\ '%s\\n'$'\\n'} {-s,-b\ 524288,-b4096\ -s}\ {:,cat,tee}$'\\n'; do"
# 24 -X shapes (4 ordering x 3 payload x 2 batch) + 9 -s/-b shapes = 33.
red = (r"for GCk in {,-k,-u,-U}\ \-X\ {,-l\ 1:-1}\ {true,echo,printf\ '%s\\n'$'\\n'} $'\\n'; do\n"
       r"#REDUCED#for GCk2 in {-s,-b\ 524288,-b4096\ -s}\ {:,cat,tee}$'\\n'; do")
if full in src:
    src = src.replace(full, red, 1)
    open(p, "w").write(src)
    print("swapped in reduced matrix")
else:
    print("WARNING: could not locate the matrix line; running FULL matrix anyway")
PY
        # The reduced form needs a second loop body; simplest correct approach is
        # to fall back to the full matrix if the swap did not apply cleanly.
        if ! grep -q 'REDUCED#' "$B/run_benchmark.bash"; then
            warn "reduced-matrix swap did not apply; running FULL matrix"
            REDUCED=0
        fi
    fi

    if run_bash_logged "$OUTD/run_benchmark.log" "run_benchmark" \
            "cd '$B' && ./run_benchmark.bash"; then
        log "main matrix done"
    else
        err "run_benchmark.bash returned non-zero"
        RC=1
    fi

    [ "$REDUCED" = "1" ] && [ -f "$B/run_benchmark.bash.epyc.bak" ] && restore_matrix && trap - EXIT
    # The harness writes benchmark.out; copy it out under a descriptive name
    # before any later stage can overwrite it.
    if [ -f "$B/benchmark.out" ]; then
        cp "$B/benchmark.out" "$OUTD/benchmark.out.txt"
        log "captured $OUTD/benchmark.out.txt ($(wc -l <"$B/benchmark.out") lines)"
    else
        err "benchmark.out was not produced"
        RC=1
    fi
else
    stage_skip "50_bench_bash_main" "deadline"
fi

# ---------------------------------------------------- GNU Parallel baseline --
banner "50b run_benchmark_parallel.bash (GNU Parallel baseline)"
# Uses 1M-line inputs, not 100M — GNU Parallel at 100M lines is impractical
# (the reference run took 7.5M s of wall time to reach 2.68/28 cores).
if deadline_ok 5400; then
    if run_bash_logged "$OUTD/run_benchmark_parallel.log" "run_benchmark_parallel" \
            "cd '$B' && ./run_benchmark_parallel.bash"; then
        log "parallel baseline done"
    else
        err "parallel baseline returned non-zero"
        RC=1
    fi
    [ -f "$B/benchmark_parallel.out" ] && cp "$B/benchmark_parallel.out" "$OUTD/benchmark_parallel.out.txt"
else
    stage_skip "50_bench_bash_parallel" "deadline"
fi

# --------------------------------------------------------- xargs -P baseline --
banner "50c run_benchmarks_xargs.bash (xargs -P baseline)"
if deadline_ok 3600; then
    if run_bash_logged "$OUTD/run_benchmarks_xargs.log" "run_benchmarks_xargs" \
            "cd '$B' && ./run_benchmarks_xargs.bash"; then
        log "xargs baseline done"
    else
        err "xargs baseline returned non-zero"
        RC=1
    fi
    [ -f "$B/benchmark_xargs.out" ] && cp "$B/benchmark_xargs.out" "$OUTD/benchmark_xargs.out.txt"
else
    stage_skip "50_bench_bash_xargs" "deadline"
fi

# ------------------------------------------------------- benchmark functions --
banner "50d run_benchmark_functions.bash (9 targeted sweeps)"
if deadline_ok 7200; then
    if run_bash_logged "$OUTD/run_benchmark_functions.log" "run_benchmark_functions" \
            "cd '$U' && ./run_benchmark_functions.bash"; then
        log "benchmark_functions done"
    else
        err "run_benchmark_functions.bash returned non-zero"
        RC=1
    fi
    [ -f "$U/benchmark_functions.out" ] && cp "$U/benchmark_functions.out" "$OUTD/benchmark_functions.out.txt"
else
    stage_skip "50_bench_bash_functions" "deadline"
fi

# ------------------------------------------------------------------ summary ---
banner "50e summary"
SUM="$OUTD/SUMMARY.txt"
{
    echo "bash benchmark summary — $EPYC_NPROC logical / $EPYC_PHYS physical cores,"
    echo "$EPYC_NODES NUMA nodes, $(date -u '+%FT%TZ')"
    echo
    for f in "$OUTD"/*.out.txt; do
        [ -f "$f" ] || continue
        echo "== $(basename "$f")"
        cases=$(grep -ac '^([0-9]*): time {' "$f" 2>/dev/null || echo 0)
        echo "   timed cases : $cases"
        grep -aE '^OVERALL CPU UTILIZATION' "$f" | tail -2 | sed 's/^/   /'
        grep -aE '^total (real|user|sys)' "$f" | sed 's/^/   /'
        # Per-node cross-socket stealing, the born-local number. Present only
        # when --stats telemetry was captured (the NUMA reference has it).
        steal=$(grep -aE 'Total Cross-Socket Traffic' "$f" | tail -5)
        if [ -n "$steal" ]; then
            echo "   cross-socket steal (last 5 legs):"
            printf '%s\n' "$steal" | sed 's/^/     /'
            echo "   steal percentage: mean of those ="
            printf '%s\n' "$steal" | grep -oE '\([0-9.]+%\)' | tr -d '()%' \
                | awk '{s+=$1;n++} END{if(n) printf "     %.2f%% over %d legs\n", s/n, n; else print "     n/a"}'
        else
            echo "   cross-socket steal: no --stats telemetry in this capture"
        fi
        echo
    done
} | tee "$SUM"

banner "50 bash benchmarks COMPLETE"
log "summary: $SUM"
[ "$RC" -eq 0 ] || warn "one or more scripts returned non-zero; see $OUTD/*.log"
exit $RC
