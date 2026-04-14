#!/usr/bin/bash
# ============================================================================
# FORKRUN SUPPLEMENTAL BENCHMARKS
# ============================================================================
# This file adds benchmark sections that are absent from run_benchmark.bash:
#
#   SECTION 1: Bash Function Throughput
#   SECTION 2: FORKRUN_EXTRA_FUNCS Overhead vs Plain Functions
#   SECTION 3: Batch Size Sweep (-l 1 → -l max): tuning sensitivity
#   SECTION 4: Worker Count Sweep (-j 1 → -j nproc*2)
#   SECTION 5: Latency Benchmark (small inputs, dispatch overhead matters)
#   SECTION 6: Startup Overhead (100-line input, ring init cost)
#   SECTION 7: NUMA Topology Variants (NUMA systems only)
#   SECTION 8: Long-Line Throughput (SIMD scanner boundary stress)
#   SECTION 9: Byte-Mode Throughput (-b chunk sweep, no delimiters)
#
# USAGE:
#   Append to run_benchmark.bash, or run standalone:
#     . frun.bash && bash BENCHMARKS/run_benchmark_functions.bash | tee benchmark_functions.out
#
# The getCPU / toc helpers below are self-contained clones of what
# run_benchmark.bash uses so this file can be sourced independently.
# If run_benchmark.bash's helpers are already in scope, these are no-ops.
# ============================================================================

{
(
(

# Source frun — try common locations
shopt -s globstar extglob
for _frun_candidate in ./frun.bash ../frun.bash frun.bash; do
    [[ -f "$_frun_candidate" ]] && { . "$_frun_candidate"; break; }
done
type -t frun &>/dev/null || { echo "ERROR: frun.bash not found."; exit 1; }

# ---------------------------------------------------------------------------
# Self-contained helpers (skip if already defined by run_benchmark.bash)
# ---------------------------------------------------------------------------
type -t getCPU &>/dev/null || {
getCPU() {
    local t_real t_user t_sys cpu
    {
        until [[ ${t_real} ]]; do read -r -u $fd_time _ t_real; done
        read -r -u $fd_time _ t_user
        read -r -u $fd_time _ t_sys
    } {fd_time}<./.time
    t_real=${t_real//[.s:]/}
    t_user=${t_user//[.s:]/}
    t_sys=${t_sys//[.s:]/}
    t_real0=$(( 60000 * 10#0${t_real%m*} + 10#0${t_real#*m} ))
    (( t_real0 > 0 )) || t_real0=1
    cpu=$(( 1000 * ( 60000 * ( 10#0${t_user%m*} + 10#0${t_sys%m*} ) + 10#0${t_user#*m} + 10#0${t_sys#*m} ) / t_real0 ))
    printf '\nCPU UTILIZATION: %d.%03d / %d\n' "$(( cpu / 1000 ))" "$(( cpu % 1000 ))" "$(nproc)"
    printf '\n-----------------------------------------\n'
    exec {fd_time}<&-
}
}

# ---------------------------------------------------------------------------
# Setup test files if not already present
# ---------------------------------------------------------------------------
fLines=10000000   # 10M lines — fast enough to run alongside main benchmarks

[[ -f ./f_bench ]] || seq $fLines > f_bench

# A file with long lines (tests SIMD scanner under high per-line byte cost)
[[ -f ./f_longlines ]] || {
    python3 -c "
import sys
for i in range(100000):
    sys.stdout.write('A' * 200 + '\n')
" > f_longlines 2>/dev/null || \
    awk 'BEGIN { for(i=1;i<=100000;i++) { printf("%200s\n",i) } }' > f_longlines
}

# A binary-ish file for byte-mode benchmarks (avoid newlines)
[[ -f ./f_bytes ]] || {
    head -c 104857600 /dev/zero | tr '\0' 'x' > f_bytes  # 100 MB of 'x'
}

declare -i K=${K:-0}   # continue from K if run after main benchmark

# ---------------------------------------------------------------------------
# Bash functions used in benchmarks
# ---------------------------------------------------------------------------

# Minimal function — measures pure dispatch overhead above the ':' no-op
_bench_noop_func() { :; }

# Lightweight transformation — printf (similar to the built-in echo tests
# but goes through bash function dispatch)
_bench_printf_func() { printf '%s\n' "$@"; }

# Function with one local variable and a conditional — represents a
# realistic "check and process" workload
_bench_classify_func() {
    local v="$1"
    if (( v % 2 == 0 )); then
        printf 'even:%s\n' "$v"
    else
        printf 'odd:%s\n' "$v"
    fi
}

# Function calling a helper via FORKRUN_EXTRA_FUNCS
_bench_helper_inner() { printf '%s\n' "$@"; }
_bench_dispatch_outer() { _bench_helper_inner "$@"; }

# ============================================================================
# SECTION 1: Bash Function Throughput
# Compare: ':' (external no-op), bash function no-op, bash function printf
# This directly measures the function-transmission overhead introduced by
# declare -f capture + cleanroom re-eval.
# ============================================================================

echo
echo '================================================================'
echo 'SECTION 1: BASH FUNCTION THROUGHPUT (vs built-ins and external cmds)'
echo '================================================================'
sleep 0.1

for Fk in f_bench; do
    # Note: '-s' mode is intentionally excluded from this section.
    # In -s mode frun pipes batch bytes directly to the command's stdin.
    # The ':' builtin never reads stdin, so every splice immediately gets
    # EPIPE — producing garbage timing results. '-s' throughput is measured
    # separately in Section 8 via the stdin-passthrough ('cat') benchmark.
    for mode_flags in '' '-k'; do
        for cmd_desc in \
            ':                 :' \
            '_bench_noop_func  _bench_noop_func' \
            '_bench_printf_func _bench_printf_func' \
            '_bench_classify_func _bench_classify_func'
        do
            cmd="${cmd_desc%%  *}"
            desc="${cmd_desc##*  }"

            ((K++))
            echo
            echo "($K): [func-throughput] time { frun $mode_flags $desc <$Fk >/dev/null; }"
            { time { frun $mode_flags $cmd <$Fk >/dev/null 2>&$fd2; }; } \
                2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
            getCPU

            ((K++))
            echo
            echo "($K): [func-throughput] time { cat $Fk | frun $mode_flags $desc >/dev/null; }"
            { time { cat $Fk | frun $mode_flags $cmd >/dev/null 2>&$fd2; }; } \
                2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
            getCPU
        done
    done
done

# ============================================================================
# SECTION 2: FORKRUN_EXTRA_FUNCS Overhead
# Measure the cost of one extra declare -f capture + re-eval in the cleanroom
# vs a plain function call.
# ============================================================================

echo
echo '================================================================'
echo 'SECTION 2: FORKRUN_EXTRA_FUNCS OVERHEAD'
echo 'Measures cost of dependent-function chain vs direct function dispatch'
echo '================================================================'
sleep 0.1

for Fk in f_bench; do
    ((K++))
    echo
    echo "($K): [extra-funcs] plain function (baseline)"
    { time { frun _bench_printf_func <$Fk >/dev/null 2>&$fd2; }; } \
        2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
    getCPU

    ((K++))
    echo
    echo "($K): [extra-funcs] outer calls inner via FORKRUN_EXTRA_FUNCS"
    { time { FORKRUN_EXTRA_FUNCS='_bench_helper_inner' frun _bench_dispatch_outer <$Fk >/dev/null 2>&$fd2; }; } \
        2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
    getCPU
done

# ============================================================================
# SECTION 3: Batch Size Sweep
# Sweeps -l from 1 to the default max to find the throughput cliff
# and the optimal operating point. This directly informs the PID
# controller's Lmax and ramp parameters.
# ============================================================================

echo
echo '================================================================'
echo 'SECTION 3: BATCH SIZE SWEEP'
echo 'Lines/sec as a function of -l N. Identifies the throughput cliff.'
echo '================================================================'
sleep 0.1

for Fk in f_bench; do
    for L in 1 2 4 8 16 32 64 128 256 512 1024 2048 4096; do
        ((K++))
        echo
        echo "($K): [batch-sweep] time { frun -l $L : <$Fk >/dev/null; }"
        { time { frun -l $L : <$Fk >/dev/null 2>&$fd2; }; } \
            2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
        getCPU

        # Also measure with a bash function at this batch size
        ((K++))
        echo
        echo "($K): [batch-sweep] time { frun -l $L _bench_printf_func <$Fk >/dev/null; }"
        { time { frun -l $L _bench_printf_func <$Fk >/dev/null 2>&$fd2; }; } \
            2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
        getCPU
    done
done

# ============================================================================
# SECTION 4: Worker Count Sweep
# Measures throughput as -j scales from 1 to 2*nproc.
# Helps identify the saturation point and any over-subscription penalty.
# ============================================================================

echo
echo '================================================================'
echo 'SECTION 4: WORKER COUNT SWEEP'
echo 'Lines/sec as a function of -j N. Identifies the saturation point.'
echo '================================================================'
sleep 0.1

NPROC=$(nproc)
for Fk in f_bench; do
    for J in 1 2 4 $(( NPROC / 4 )) $(( NPROC / 2 )) $NPROC $(( NPROC * 2 )); do
        (( J < 1 )) && continue
        ((K++))
        echo
        echo "($K): [worker-sweep] time { frun -j $J : <$Fk >/dev/null; }"
        { time { frun -j $J : <$Fk >/dev/null 2>&$fd2; }; } \
            2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
        getCPU

        ((K++))
        echo
        echo "($K): [worker-sweep] time { frun -j $J _bench_printf_func <$Fk >/dev/null; }"
        { time { frun -j $J _bench_printf_func <$Fk >/dev/null 2>&$fd2; }; } \
            2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
        getCPU
    done
done

# ============================================================================
# SECTION 5: Latency Benchmark (Small Inputs)
# For very small N, dispatch overhead and startup cost dominate.
# This tests the regime where latency matters more than throughput
# (e.g., an interactive shell tool, a small validation pipeline).
# ============================================================================

echo
echo '================================================================'
echo 'SECTION 5: LATENCY BENCHMARK (small N)'
echo 'Total wall time for N=1..10000. Isolates dispatch overhead.'
echo '================================================================'
sleep 0.1

for N in 1 2 5 10 20 50 100 200 500 1000 2000 5000 10000; do
    ((K++))
    echo
    echo "($K): [latency] N=$N: time { seq $N | frun : >/dev/null; }"
    { time { seq $N | frun : >/dev/null 2>&$fd2; }; } \
        2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
    getCPU

    ((K++))
    echo
    echo "($K): [latency-func] N=$N: time { seq $N | frun _bench_noop_func >/dev/null; }"
    { time { seq $N | frun _bench_noop_func >/dev/null 2>&$fd2; }; } \
        2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
    getCPU
done

# ============================================================================
# SECTION 6: Startup / First-Result Overhead
# Measures total wall time for a minimal but real input (100 lines).
# echo 'x' | frun is too small to time reliably — the process-start noise
# dominates and results are not reproducible. 100 lines keeps the data
# phase negligible while giving the ring/scanner a real cycle to complete.
# ============================================================================

echo
echo '================================================================'
echo 'SECTION 6: STARTUP / FIRST-RESULT OVERHEAD (100-line input)'
echo 'Time from first stdin byte to last stdout byte. Reflects init cost.'
echo '================================================================'
sleep 0.1

# Generate a tiny file once — avoids seq startup time being included in the
# benchmark itself.
[[ -f ./f_small ]] || seq 100 > f_small

for cmd_desc in \
    ':                 :' \
    '_bench_noop_func  _bench_noop_func' \
    '_bench_printf_func _bench_printf_func' \
    'echo              echo'; do
    cmd="${cmd_desc%%  *}"
    desc="${cmd_desc##*  }"

    ((K++))
    echo
    echo "($K): [startup] time { frun $desc <f_small >/dev/null; }"
    { time { frun $cmd <f_small >/dev/null 2>&$fd2; }; } \
        2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
    getCPU
done

# ============================================================================
# SECTION 7: NUMA Topology Variants (only if NUMA nodes > 1)
# ============================================================================

NUMA_NODES=$(cat /sys/devices/system/node/online 2>/dev/null || echo "0")
if [[ "$NUMA_NODES" == *-* || "$NUMA_NODES" == *,* ]]; then
    echo
    echo '================================================================'
    echo 'SECTION 7: NUMA TOPOLOGY VARIANTS'
    echo '================================================================'
    sleep 0.1

    for Fk in f_bench; do
        for numa_flag in '--nodes=auto' '--nodes=1' '--nodes=2' '--nodes=@2' '--nodes=@4'; do
            ((K++))
            echo
            echo "($K): [numa-topo] time { frun $numa_flag : <$Fk >/dev/null; }"
            { time { frun $numa_flag : <$Fk >/dev/null 2>&$fd2; }; } \
                2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
            getCPU

            ((K++))
            echo
            echo "($K): [numa-topo] time { frun $numa_flag _bench_printf_func <$Fk >/dev/null; }"
            { time { frun $numa_flag _bench_printf_func <$Fk >/dev/null 2>&$fd2; }; } \
                2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
            getCPU
        done
    done
fi

# ============================================================================
# SECTION 8: Long-Line Throughput (SIMD Scanner Boundary Stress)
# Long lines mean fewer newlines per 32-byte AVX2 chunk — tests the
# "hits < remaining → skip entire chunk" hot path in scan_batch_avx2.
# ============================================================================

echo
echo '================================================================'
echo 'SECTION 8: LONG-LINE THROUGHPUT (SIMD scanner stress)'
echo 'Each line is 200 chars. Tests scanner boundary efficiency.'
echo '================================================================'
sleep 0.1

for Fk in f_longlines; do
    for cmd in ':' '_bench_printf_func'; do
        for mode_flags in '' '-s'; do
            [[ "$mode_flags" == '-s' && "$cmd" != ':' ]] && continue
            ((K++))
            echo
            echo "($K): [longlines] time { frun $mode_flags $cmd <$Fk >/dev/null; }"
            { time { frun $mode_flags $cmd <$Fk >/dev/null 2>&$fd2; }; } \
                2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
            getCPU
        done
    done
done

# ============================================================================
# SECTION 9: Byte-Mode Throughput (-b / -s)
# f_bytes has NO newlines — frun in line mode would treat it as one
# enormous batch. This section uses byte-mode (-b N) where frun splits
# on fixed byte boundaries instead of delimiter scanning.
# Sweep chunk sizes from 4K to 1M to find the splice throughput peak.
# ============================================================================

echo
echo '================================================================'
echo 'SECTION 9: BYTE-MODE THROUGHPUT (-b chunk sweep on f_bytes)'
echo 'No newlines in input. Tests fixed-size chunk dispatch path.'
echo '================================================================'
sleep 0.1

for chunk in 4096 16384 65536 262144 524288 1048576; do
    ((K++))
    echo
    echo "($K): [byte-mode] time { frun -b $chunk -s cat <f_bytes >/dev/null; }"
    { time { frun -b $chunk -s cat <f_bytes >/dev/null 2>&$fd2; }; } \
        2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
    getCPU

    ((K++))
    echo
    echo "($K): [byte-mode] time { frun -b $chunk -s : <f_bytes >/dev/null; }"
    { time { frun -b $chunk -s : <f_bytes >/dev/null 2>&$fd2; }; } \
        2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
    getCPU
done

# ============================================================================
# INPUT FILE STATS
# ============================================================================
printf '\n\n-----------------------------\nBENCHMARK INPUT FILE STATS\n\n'
for f in f_bench f_longlines f_bytes f_small; do
    [[ -f "$f" ]] || continue
    printf 'NAME: %s\nSIZE: %s bytes\nLINE COUNT: %s lines\n\n' \
        "$f" \
        "$(du -d 0 -b "$f" 2>/dev/null | sed -E 's/[ \t].*//' || wc -c <"$f")" \
        "$(wc -l < "$f")"
done

# Cleanup temporary files created by this script
\rm -f ./.time f_small

) {fd1}>&1 {fd2}>&2
)
} 2>&1 | tee benchmark_functions.out
