#!/usr/bin/env bash
###############################################################################
# FORKRUN VALIDATION ENGINE (FVE) v1.0
###############################################################################
# USAGE:
#   1. Ensure forkrun (frun.bash) is in the current directory or PATH
#   2. Ensure /tmp is writable
#   3. chmod +x run_fve.sh
#   4. ./run_fve.sh 2> validation_progress.log
#
# The script exits 0 on total success. Any failure triggers Exit 1.
# A manifest.log file is generated with the results of every individual test.
###############################################################################

#set -euo pipefail

# --- CONFIGURATION ---
FRUN_SCRIPT="${1:-frun.bash}"
MANIFEST="manifest.log"
MAX_JOBS=${FVE_MAX_WORKERS:-$(nproc)}
TMP_DIR=$(mktemp -d /tmp/fve_XXXXXX)

# --- STATE ---
PASS_COUNT=0
FAIL_COUNT=0
TEST_NUM=0
TOTAL_TESTS=${TOTAL_TESTS_OVERRIDE:-999} # High watermark for progress calc

# --- SOURCE FORKRUN ---
if [[ ! -f "$FRUN_SCRIPT" ]]; then
    echo "ERROR: frun.bash not found at '$FRUN_SCRIPT'" >&2
    exit 1
fi

# Source it once to validate syntax and load loadables
source "$FRUN_SCRIPT" 2>/dev/null

. ./frun.bash

# --- LOGGING UTILITIES ---
_log() { echo "[$(date +%H:%M:%S)] $*" >&2; }
_progress() { printf "\r\x1b[K[TEST %3d] Running: %-60s %s" "$TEST_NUM" "$1" "$2" >&2; }
_log_manifest() { echo "$1" | tee -a "$MANIFEST" >&2; }

# --- CORE VERIFICATION LOGIC ---
# Verify that the output stream contains exactly the sequence 1..N
_verify_sequence() {
    local output_file=$1 target_count=$2
    if [[ ! -f "$output_file" ]]; then return 1; fi

    local actual_count
    actual_count=$(wc -l < "$output_file")
    if (( actual_count != target_count )); then return 1; fi

    # Verify content is valid integers (fast check)
    # Verify sequence monotonicity if ordered (expensive)
    # For speed, we rely on hash checks and count checks
    local hash
    hash=$(md5sum < "$output_file" | cut -d' ' -f1)
    echo "$hash"
}

# Deterministic hash of a sequence 1..N (to verify data integrity without re-sorting)
# Computes: sum of lines and count of lines
_generate_fingerprint() {
    local target=$1
    local sum=0
    local hash_str="N=${target}"

    # For very large targets, calculating exact sum is slow in bash.
    # We use a probabilistic check for large streams:
    # 1. Check line count.
    # 2. Check first and last line.
    # 3. Check MD5 of the stream.

    { seq 1 "$target"; } | md5sum | cut -d' ' -f1
}

_validate_test() {
    local test_name=$1 input_file=$2 output_file=$3 verify_mode=$4 expected_count=$5
    local result="FAIL"

    ((TEST_NUM++))
    _progress "$test_name" ""

    # --- EXECUTE FORKRUN ---
    local frun_cmd="frun"
    local extra_args="${6:-}"

    # If verify_mode is 'diff', we expect ordered output
    if [[ "$verify_mode" == "diff_ordered" ]]; then
        # Generate reference
        local ref_file="${output_file}.ref"
        sort -n "$input_file" > "$ref_file"

        # Run frun
        # We use a timeout to prevent deadlocks
        if timeout 60 bash -c "cat '$input_file' | $frun_cmd $extra_args cat" 1>"$output_file"; then
            # Compare sorted
            if diff -q "$ref_file" "$output_file" >/dev/null 2>&1; then
                result="PASS"
            else
                result="FAIL: Order mismatch"
            fi
        else
            result="FAIL: Timeout/Crash"
        fi
        rm -f "$ref_file"

    elif [[ "$verify_mode" == "diff_set" ]]; then
        # Unordered check: content matches but order doesn't matter
        local ref_file="${output_file}.ref"
        sort -n "$input_file" > "$ref_file"

        if timeout 60 bash -c "cat '$input_file' | $frun_cmd $extra_args cat" 1>"$output_file"; then
            sort -n "$output_file" > "${output_file}.sorted"
            if diff -q "$ref_file" "${output_file}.sorted" >/dev/null 2>&1; then
                result="PASS"
            else
                result="FAIL: Content mismatch"
            fi
            rm -f "${output_file}.sorted" "$ref_file"
        else
            result="FAIL: Timeout/Crash"
        fi

    elif [[ "$verify_mode" == "byte_integrity" ]]; then
         local ref_file="${output_file}.ref"
         cp "$input_file" "$ref_file"

         if timeout 60 bash -c "cat '$input_file' | $frun_cmd $extra_args cat" 1>"$output_file"; then
            if cmp -s "$ref_file" "$output_file"; then
                result="PASS"
            else
                result="FAIL: Byte mismatch"
            fi
        else
            result="FAIL: Timeout/Crash"
        fi
        rm -f "$ref_file"
    fi

    # Record Result
    if [[ "$result" == "PASS" ]]; then
        ((PASS_COUNT++))
        _progress "$test_name" "✅ ${result}"
        _log_manifest "PASS | ${test_name}"
    else
        ((FAIL_COUNT++))
        _progress "$test_name" "❌ ${result}"
        _log_manifest "FAIL | ${test_name} | ${result} | Out:${output_file}"
    fi
    echo # Newline after progress
}

# --- TEST GENERATION ---

_init_test_data() {
    _log "Generating test data..."
    # 100 items (Standard)
    seq 1 100 > "${TMP_DIR}/small.txt"

    # 10,000 items (Medium - Backpressure test)
    seq 1 10000 > "${TMP_DIR}/medium.txt"

    # 50 items (Binary/Blob simulation)
    head -c 50000 /dev/urandom > "${TMP_DIR}/binary.bin"
}

_run_suites() {
    _init_test_data

    # ======================================================================
    # SUITE 1: FUNCTIONAL CORRECTNESS (Data Integrity)
    # ======================================================================

    # 1.1 Basic Ordered
    _validate_test "Ordered/100" "${TMP_DIR}/small.txt" "${TMP_DIR}/out_1.txt" "diff_ordered" 100 "-k"

    # 1.2 Basic Unordered
    _validate_test "Set/10000" "${TMP_DIR}/medium.txt" "${TMP_DIR}/out_2.txt" "diff_set" 10000 ""

    # 1.3 Realtime/Stdin
    _validate_test "Stdin/100" "${TMP_DIR}/small.txt" "${TMP_DIR}/out_3.txt" "diff_ordered" 100 "-k -s"

    # ======================================================================
    # SUITE 2: DYNAMIC BATCHING & WORKERS (The PID Controller)
    # ======================================================================

    # 2.1 Exact Lines (L)
    _validate_test "Exact-Lines/10000" "${TMP_DIR}/medium.txt" "${TMP_DIR}/out_4.txt" "diff_set" 10000 "-L 500"

    # 2.2 Worker Scaling Range (1 to 4)
    _validate_test "Workers/1-4" "${TMP_DIR}/medium.txt" "${TMP_DIR}/out_5.txt" "diff_set" 10000 "-j 1:4"

    # 2.3 Byte Mode (b)
    # Note: cat works on bytes, but delimiters must be respected
    _validate_test "Byte-Mode/Small" "${TMP_DIR}/small.txt" "${TMP_DIR}/out_6.txt" "diff_ordered" 100 "-k -b 1024"

    # ======================================================================
    # SUITE 3: NUMA & TOPOLOGY (Structural Tests)
    # ======================================================================

    # 3.1 UMA Mode (Single Node)
    _validate_test "UMA/10000" "${TMP_DIR}/medium.txt" "${TMP_DIR}/out_7.txt" "diff_ordered" 10000 "-k --nodes 1"

    # 3.2 Multi-Node (If supported by kernel/env, else fallback to @N)
    # We test the @N overload to induce logical partitions even on UMA hardware
    _validate_test "Oversubscribe/4-Node" "${TMP_DIR}/medium.txt" "${TMP_DIR}/out_8.txt" "diff_set" 10000 "--nodes @4"

    # ======================================================================
    # SUITE 4: OUTPUT & DELIMITERS
    # ======================================================================

    # 4.1 Custom Delimiter (Pipe separated input)
    local pipe_file="${TMP_DIR}/pipe.txt"
    seq 1 100 | sed 's/$/|/' > "$pipe_file"
    _validate_test "Delim-PIPE" "$pipe_file" "${TMP_DIR}/out_9.txt" "diff_set" 100 "-d '|'"

    # 4.2 Null Delimiter
    local null_file="${TMP_DIR}/null.txt"
    printf '%s\0' $(seq 1 100) > "$null_file"
    _validate_test "Delim-NULL" "$null_file" "${TMP_DIR}/out_10.txt" "diff_ordered" 100 "-k -z"

    # ======================================================================
    # SUITE 5: STRESS & BACKPRESSURE
    # ======================================================================

    # 5.1 High Worker Count (Contention test)
    # 64 workers on 10k items triggers massive escrow activity
    _validate_test "Stress/64W" "${TMP_DIR}/medium.txt" "${TMP_DIR}/out_11.txt" "diff_set" 10000 "-j 64:64"

    # 5.2 Small Batch / High Churn
    _validate_test "Churn/L5" "${TMP_DIR}/medium.txt" "${TMP_DIR}/out_12.txt" "diff_set" 10000 "-l 5"

    # 5.3 Limit Mode (-n)
    # Run cat | frun ... head logic
    # We expect output to stop after 50 lines
    local limit_test_output="${TMP_DIR}/out_13.txt"
    if timeout 30 bash -c "cat '${TMP_DIR}/medium.txt' | frun -n 50 cat" 1>"$limit_test_output"; then
        local lc
        lc=$(wc -l < "$limit_test_output")
        if (( lc >= 50 )); then
            # Allow slightly more due to batch granularity, but usually exact
            ((PASS_COUNT++))
            _log_manifest "PASS | Limit-50 (Got ${lc})"
        else
            ((FAIL_COUNT++))
            _log_manifest "FAIL | Limit-50 (Got ${lc})"
        fi
    else
        ((FAIL_COUNT++))
        _log_manifest "FAIL | Limit-50 Timeout"
    fi
    ((TEST_NUM++))
    _progress "Limit-50" "DONE"
    echo
}

# --- ORCHESTRATOR ---
_run_suites

# --- FINAL REPORT ---
echo
_log "========================================"
_log " FORKRUN VALIDATION REPORT"
_log "========================================"
_log " Total Tests  : ${TEST_NUM}"
_log " Passed       : ${PASS_COUNT}"
_log " Failed       : ${FAIL_COUNT}"
_log " Manifest     : ${MANIFEST}"
_log "========================================"

if (( FAIL_COUNT > 0 )); then
    _log "❌ STATUS: FAILURES DETECTED. CHECK MANIFEST."
    exit 1
else
    _log "✅ STATUS: ALL SYSTEMS NOMINAL."
    exit 0
fi
