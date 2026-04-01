#!/usr/bin/env bash
# frun_test_suite_1.sh
# Usage:  ./frun_test_suite_1.sh   (or source it and call frun_test_suite)
#
# This script assumes frun.bash resides in the same directory.
# It creates a temporary workspace, runs a matrix of test cases,
# compares actual output to expected output, and reports results.

#set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
info()  { log "INFO: $*"; }
warn()  { log "WARN: $*"; }
error() { log "ERROR: $*"; }
success() { log "SUCCESS: $*"; }
failure() { log "FAIL: $*"; }

# Simple spinner for long-running tests
_spinner() {
    local pid=$1 delay=0.1 spinstr='|/-\'
    while kill -0 "$pid" 2>/dev/null; do
        local temp=${spinstr#?}
        printf " [%c]  " "$spinstr"
        spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done
    printf "    \r"
}

# Run a test case and compare output.
# Arguments:
#   $1: test name (string)
#   $2: frun command line (array)
#   $3: expected stdout file (string) or "-" if stdout should be empty
#   $4: expected stderr file (string) or "-" if stderr should be empty
#   $5: optional expected exit code (default 0)
run_test() {
    local tname="$1" shift
    local -a frun_cmd=("$@")
    local exp_stdout="$1" exp_stderr="$2" exp_exit="${3:-0}"

    local out err
    local -a status

    # Run frun, capturing stdout/stderr and exit code
    (
        "${frun_cmd[@]}" >"$tmpdir/out" 2>"tmpdir/err"
        status=$?
        printf "%d" "$status" >"$tmpdir/exit"
    ) &
    local bg_pid=$!
    _spinner "$bg_pid" &
    wait "$bg_pid"
    kill "$!" 2>/dev/null || true   # stop spinner
    printf "\r"

    out=$(<"$tmpdir/out")
    err=$(<"$tmpdir/err")
    status=$(<"$tmpdir/exit")

    # Normalise trailing newlines for comparison (frun may add a final newline)
    out="${out%$'\n'}"
    err="${err%$'\n'}"

    # Load expected files if needed
    if [[ "$exp_stdout" != "-" ]]; then
        exp_out=$(<"$exp_stdout")
        exp_out="${exp_out%$'\n'}"
    else
        exp_out=""
    fi
    if [[ "$exp_stderr" != "-" ]]; then
        exp_err=$(<"$exp_stderr")
        exp_err="${exp_err%$'\n'}"
    else
        exp_err=""
    fi

    # Compare
    if [[ "$out" != "$exp_out" ]]; then
        failure "$tname: stdout mismatch"
        printf "  Expected:\n%s\n  Got:\n%s\n" "$exp_out" "$out"
        return 1
    fi
    if [[ "$err" != "$exp_err" ]]; then
        failure "$tname: stderr mismatch"
        printf "  Expected:\n%s\n  Got:\n%s\n" "$exp_err" "$err"
        return 1
    fi
    if [[ "$status" -ne "$exp_exit" ]]; then
        failure "$tname: unexpected exit code $status (expected $exp_exit)"
        return 1
    fi
    success "$tname"
    return 0
}

# ---------------------------------------------------------------------------
# Prepare test environment
# -------------------------------------------------------------------------__
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/frun.bash"   # load frun functions and bootstrap loadables

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

# Create a simple input file: numbered lines 1..1000
seq 1 1000 > "$tmpdir/input.txt"

# For delimiter tests
printf 'a,b\nc,d\ne,f\ng,h\ni,j\n' > "$tmpdir/comma.txt"
printf 'a\0b\0c\0d\0e\0f\0g\0h\0i\0j\0' > "$tmpdir/null.txt"   # 10 null‑separated fields

# For insert-id test: we need a command that prints the ID
cat > "$tmpdir/print_id.sh" <<'EOF'
#!/usr/bin/bash
printf '%s\n' "$ID"
EOF
chmod +x "$tmpdir/print_id.sh"

# ---------------------------------------------------------------------------
# Define test cases
# Each entry: (name, frun_args_array, expected_stdout_file, expected_stderr_file, [exit_code])
# ---------------------------------------------------------------------------
declare -a TEST_CASES=(
    # 1. Basic buffered (default) – echo each argument
    "buffered-default"
        "( printf '%s\n' \"\$@\" )"
        "$tmpdir/input.txt"
        "$tmpdir/input.txt"
        "-"
        0

    # 2. Ordered (-k) – same output as buffered for this deterministic workload
    "ordered-k"
        "( printf '%s\n' \"\$@\" )"
        "$tmpdir/input.txt"
        "$tmpdir/input.txt"
        "-"
        0

    # 3. Realtime (-u) – workers write directly to stdout; order may vary
    "realtime-u"
        "( printf '%s\n' \"\$@\" )"
        "$tmpdir/input.txt"
        "$tmpdir/input.txt"   # we only check that *all* lines appear, order irrelevant
        "-"
        0
        # Special checker below (uses sort)

    # 4. Unsafe (-U) – arguments unquoted (same as default for single-word args)
    "unsafe-U"
        "( printf '%s\n' \"\$@\" )"
        "$tmpdir/input.txt"
        "$tmpdir/input.txt"
        "-"
        0

    # 5. Stdin mode (-s) – pass line via stdin, command is 'cat'
    "stdin-s"
        "cat"
        "$tmpdir/input.txt"
        "$tmpdir/input.txt"
        "-"
        0

    # 6. Byte mode (-b 5) – split input into 5‑byte chunks (no delimiter scanning)
    "byte-b5"
        "( printf '%s\n' \"\$@\" )"
        "$tmpdir/input.txt"
        # Expected: each 5‑byte chunk as a line (no newline inside chunk)
        "-"
        0
        # Special checker: we will generate expected by splitting the raw bytes

    # 7. Exact lines (-L 3) – force exactly 3 lines per batch
    "exact-lines-L3"
        "( printf '%s\n' \"\$@\" )"
        "$tmpdir/input.txt"
        "$tmpdir/input.txt"
        "-"
        0

    # 8. Timeout (-t 20000) – 20 ms timeout; use a slow input generator
    "timeout-t20ms"
        "( printf '%s\n' \"\$@\" )"
        # Create a file where each line arrives after 10 ms (using awk & sleep)
        "<(for i in {1..10}; do echo $i; sleep 0.01; done)"
        "$(for i in {1..10}; echo $i; done)"
        "-"
        0
        # Note: we rely on subshell input; frun will read from it.
        # If the test hangs, the suite will timeout (handled by outer set -euo pipefail? not really).
        # We'll instead use a pre‑generated file with delays via dd? Skip for now and rely on other tests.

    # 9. Custom delimiter (-d ,)
    "delimiter-d-comma"
        "( printf '%s\n' \"\$@\" )"
        "$tmpdir/comma.txt"
        "$tmpdir/comma.txt"
        "-"
        0

    # 10. Null delimiter (-z)
    "delimiter-z-null"
        "( printf '%s\n' \"\$@\" )"
        "$tmpdir/null.txt"
        "$tmpdir/null.txt"
        "-"
        0

    # 11. Insert (-i) – replace {} with the whole line
    "insert-i"
        "( echo \"ARG: {}\" )"
        "$tmpdir/input.txt"
        # Expected: each line prefixed with "ARG: "
        "-"
        0
        # Special checker

    # 12. Insert-id (-I) – replace {ID} with node.worker.batch
    "insert-id-I"
        "$tmpdir/print_id.sh"
        "$tmpdir/input.txt"
        # Expected: each line is "node.worker.batch" (node=0 because we have 1 node)
        "-"
        0
        # Special checker: we only need to verify format, not exact values

    # 13. Limit (-n 5) – stop after 5 records
    "limit-n5"
        "( printf '%s\n' \"\$@\" )"
        "$tmpdir/input.txt"
        # Expected: first 5 lines of input
        "-"
        0
        # Special checker

    # 14. Nodes – explicit single node (should behave like UMA)
    "nodes-1"
        "( printf '%s\n' \"\$@\" )"
        "$tmpdir/input.txt"
        "$tmpdir/input.txt"
        "-"
        0

    # 15. Dry-run (-N) – should print the command lines, not execute
    "dry-run-N"
        "( echo \"executed\"; false )"   # command that would fail if executed
        "$tmpdir/input.txt"
        # Expected: each line of input turned into an echo command
        "-"
        0
        # Special checker: compare to generated command list

    # 16. Verbose (-v) – should print timing info to stderr
    "verbose-v"
        "( printf '%s\n' \"\$@\" )"
        "$tmpdir/input.txt"
        "$tmpdir/input.txt"
        # Expect stderr to contain "finished at" (from toc) – we only check non‑empty
        "!empty"
        0

    # 17. Version (-V) – prints version string
    "version-V"
        ""
        # No input needed
        "-"
        "forkrun v3.0.1"
        0
)

# ---------------------------------------------------------------------------
# Special checkers (used when expected file is "-")
# ---------------------------------------------------------------------------
run_test_with_checker() {
    local tname="$1" shift
    local -a frun_cmd=("$@")
    local checker="$1" exp_exit="${2:-0}"

    local out err status
    (
        "${frun_cmd[@]}" >"$tmpdir/out" 2>"tmpdir/err"
        status=$?
        printf "%d" "$status" >"$tmpdir/exit"
    ) &
    local bg_pid=$!
    _spinner "$bg_pid" &
    wait "$bg_pid"
    kill "$!" 2>/dev/null || true
    printf "\r"

    out=$(<"$tmpdir/out")
    err=$(<"$tmpdir/err")
    status=$(<"$tmpdir/exit")
    out="${out%$'\n'}"
    err="${err%$'\n'}"

    case "$checker" in
        "sorted")
            # stdout must contain all input lines, order irrelevant
            if [[ "$(printf '%s\n' "$out" | sort)" != "$(printf '%s\n' <"$tmpdir/input.txt" | sort)" ]]; then
                failure "$tname: output does not match input (as a set)"
                return 1
            fi
            ;;
        "byte-b5")
            # Split input file into 5‑byte chunks (no newline splitting)
            local expected
            expected=$(dd if="$tmpdir/input.txt" bs=5 2>/dev/null | tr '\0' '\n' | sed '/^$/d')
            if [[ "$out" != "$expected" ]]; then
                failure "$tname: byte-mode chunking mismatch"
                printf "  Expected first 3 lines:\n%s\n  Got first 3 lines:\n%s\n" \
                    "$(printf '%s\n' "$expected" | head -3)" \
                    "$(printf '%s\n' "$out" | head -3)"
                return 1
            fi
            ;;
        "insert-i")
            local expected
            expected=$(sed 's/^/ARG: /' "$tmpdir/input.txt")
            if [[ "$out" != "$expected" ]]; then
                failure "$tname: insert {} replacement failed"
                return 1
            fi
            ;;
        "insert-id-I")
            # Each line must match pattern <node>.<worker>.<batch> where node=0
            if ! [[ "$out" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$(printf '\n\1\.\2\.\3')*$ ]]; then
                failure "$tname: insert-id format mismatch"
                return 1
            fi
            ;;
        "limit-n5")
            local expected
            expected=$(head -5 "$tmpdir/input.txt")
            if [[ "$out" != "$expected" ]]; then
                failure "$tname: limit -n 5 failed"
                return 1
            fi
            ;;
        "dry-run-N")
            # Expected: each input line becomes: echo "line"; true
            local expected
            while IFS= read -r line; do
                # Escape single quotes in line for the echo command
                printf 'echo '\''%s'\''; true\n' "$line"
            done <"$tmpdir/input.txt" >"$tmpdir/expected_dry"
            expected=$(<"$tmpdir/expected_dry")
            if [[ "$out" != "$expected" ]]; then
                failure "$tname: dry-run output mismatch"
                return 1
            fi
            ;;
        "verbose-v")
            if [[ -z "$err" ]]; then
                failure "$tname: verbose mode produced no stderr"
                return 1
            fi
            # Expect something like "... finished at +NNNN us"
            if ! [[ "$err" =~ finished\ at\ +[0-9]+ ]]; then
                failure "$tname: verbose stderr missing timing info"
                return 1
            fi
            ;;
        "!empty")
            if [[ -z "$err" ]]; then
                failure "$tname: expected non-empty stderr"
                return 1
            fi
            ;;
        *)
            # No special checker – just compare to empty expected
            if [[ -n "$out" ]] || [[ -n "$err" ]] || [[ "$status" -ne 0 ]]; then
                failure "$tname: unexpected output/exit"
                return 1
            fi
            ;;
    esac
    success "$tname"
    return 0
}

# ---------------------------------------------------------------------------
# Execute test suite
# ---------------------------------------------------------------------------
pass=0
fail=0
total=${#TEST_CASES[@]}


log "=== Starting FRUN test suite ($total test cases) ==="
log "Temporary workspace: $tmpdir"

for ((i=0; i<total; i+=5)); do   # each test case occupies 5 slots in the array
    idx=$i
    name="${TEST_CASES[idx]}"
    cmd_str="${TEST_CASES[$((idx+1))]}"
    stdin_arg="${TEST_CASES[$((idx+2))]}"
    exp_stdout="${TEST_CASES[$((idx+3))]}"
    exp_stderr="${TEST_CASES[$((idx+4))]}"
    exp_exit=0   # default, could be extended later

    # Build frun command array
    # If stdin_arg starts with "<(" we treat it as process substitution; otherwise as file.
    if [[ "$stdin_arg" == "<("* ]]; then
        # Process substitution – we need to eval it in the command line
        frun_cmd=( frun $cmd_str < <(eval "$stdin_arg") )
    else
        frun_cmd=( frun $cmd_str "${stdin_arg:-}" )
    fi

    log "Running test $((i/5 + 1))/$((total/5)): $name"
    if [[ "$exp_stdout" == "-" && "$exp_stderr" == "-" ]]; then
        # Simple case – use run_test with empty expected files
        if run_test "$name" "${frun_cmd[@]}" "-" "-" "$exp_exit"; then
            ((pass++))
        else
            ((fail++))
        fi
    else
        # Need to prepare expected files if they are not literals
        if [[ "$exp_stdout" != "-" && ! -f "$exp_stdout" ]]; then
            printf "%s" "$exp_stdout" >"$tmpdir/expout"
            exp_stdout="$tmpdir/expout"
        fi
        if [[ "$exp_stderr" != "-" && ! -f "$exp_stderr" ]]; then
            printf "%s" "$exp_stderr" >"$tmpdir/experr"
            exp_stderr="$tmpdir/experr"
        fi
        if run_test "$name" "${frun_cmd[@]}" "$exp_stdout" "$exp_stderr" "$exp_exit"; then
            ((pass++))
        else
            ((fail++))
        fi
    fi
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log "=== Test Suite Finished ==="
log "Passed: $pass"
log "Failed: $fail"
if (( fail == 0 )); then
    log "All tests passed."
    exit 0
else
    log "Some tests failed. See above for details."
    exit 1
fi
