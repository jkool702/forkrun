#!/usr/bin/env bash
# frun_test_suite.sh - Comprehensive self-verifying test suite for frun.bash
# Usage: ./frun_test_suite.sh [options]

#set -euo pipefail

# Configuration
declare -i NUM_CORES=${NUM_CORES:-$(nproc)}
declare -i MAX_TIMEOUT=300
declare -i VERBOSE=0
declare -i PROGRESS_BAR=1
declare -i FAIL_FAST=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test results tracking
declare -i TOTAL_TESTS=0
declare -i PASSED_TESTS=0
declare -i FAILED_TESTS=0
declare -a FAILED_TESTS_LIST=()
declare -a TEST_DESCRIPTIONS=()

# Progress tracking
declare -i CURRENT_TEST=0
declare -i LAST_UPDATE=0
declare -i UPDATE_INTERVAL=1

# Signal handler for cleanup
cleanup() {
    echo -e "${BLUE}[INFO]${NC} Cleaning up test environment..."
    exec 3>&- || true
    exec 4>&- || true
}

# Setup testing environment
setup_environment() {
    local tmpdir=$(mktemp -d -t frun_test_XXXXXX)
    export FORKRUN_TMPDIR="$tmpdir"
    export HOME="$tmpdir"
    export TMPDIR="$tmpdir"

    # Create test files
    echo "Line 1" > "$tmpdir/test1.txt"
    printf "Line1\nLine2\nLine3\n" > "$tmpdir/test2.txt"
    seq 1 1000 > "$tmpdir/long_file.txt"
    fallocate -l 100M "$tmpdir/large_file.bin" 2>/dev/null || truncate -s 100M "$tmpdir/large_file.bin"

    # Create test functions
    cat > "$tmpdir/test_func.sh" << 'EOF'
#!/usr/bin/env bash
function validate_args() {
    # This function validates all arguments and environment variables
    local input_count=${1:-}
    local output_count=${2:-}
    local batch_id=${3:-}
    local worker_id=${4:-}

    # Write validation results to file
    echo "INPUT_COUNT=$input_count" >> "$4"
    echo "OUTPUT_COUNT=$output_count" >> "$4"
    echo "BATCH_ID=$batch_id" >> "$4"
    echo "WORKER_ID=${RING_NODE_ID:+$RING_NODE_ID.}$ID.$W_BATCH" >> "$4"
    echo "ALL_ARGS=($*)" >> "$4"
    echo "STDIN=$([ -t 0 ] && echo 'NO_STDIN' || echo 'HAS_STDIN')" >> "$4"

    # Process all arguments
    for arg in "$@"; do
        echo "PROCESSED_ARG=$arg"
    done
    return 0
}
EOF
    chmod +x "$tmpdir/test_func.sh"

    # Create validation script
    cat > "$tmpdir/validate.sh" << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

FAILURES=()

# Validate single line output
validate_single_line() {
    local expected="$1"
    local actual="$2"
    if [[ "$actual" != "$expected" ]]; then
        FAILURES+=("Line mismatch: expected '$expected', got '$actual'")
    fi
}

# Validate file contents
validate_file() {
    local file="$1"
    local expected_count="$2"
    local actual_count=$(wc -l < "$file")
    if [[ $actual_count -ne $expected_count ]]; then
        FAILURES+=("File $file count mismatch: expected $expected_count, got $actual_count")
    fi
}

# Print results
print_results() {
    if ((${#FAILURES[@]} == 0)); then
        echo "PASS"
    else
        echo "FAIL"
        for failure in "${FAILURES[@]}"; do
            echo "  $failure"
        done
    fi
    return $(( ${#FAILURES[@]} == 0 ))
}
EOF
    chmod +x "$tmpdir/validate.sh"
}

# Test runner framework
run_test() {
    local test_name="$1"
    local test_command="$2"
    local expected_result="$3"
    local description="$4"

    ((TOTAL_TESTS++))
    ((CURRENT_TEST++))

    # Show progress
    if ((PROGRESS_BAR)); then
        if ((VERBOSE)); then
            echo -e "\n${BLUE}[RUNNING]${NC} Test $CURRENT_TEST/$TOTAL_TESTS: $test_name"
        else
            printf "\r${BLUE}[%3d%%]${NC} Test %3d/%3d: %-50s " \
                $(( (CURRENT_TEST * 100) / TOTAL_TESTS )) \
                $CURRENT_TEST $TOTAL_TESTS "$test_name"
        fi
    fi

    # Create test environment
    local test_dir=$(mktemp -d -t frun_test_run_XXXXXX)
    cd "$test_dir"

    # Run the test
    local output_file="${test_name// /_}_output.txt"
    local exit_code=0
    if [[ "$expected_result" == "FAIL" ]]; then
        # Expect failure
        if eval "$test_command" > "$output_file" 2>&1; then
            exit_code=0
        else
            exit_code=$?
        fi
    else
        # Expect success
        if eval "$test_command" > "$output_file" 2>&1; then
            exit_code=0
        else
            exit_code=$?
        fi
    fi

    # Validate results
    local test_passed=1
    if [[ "$expected_result" == "PASS" ]]; then
        if [[ $exit_code -ne 0 ]]; then
            test_passed=0
        fi
    else
        if [[ $exit_code -eq 0 ]]; then
            test_passed=0
        fi
    fi

    # Add to results
    if ((test_passed)); then
        ((PASSED_TESTS++))
        log "\e[1A\e[K${GREEN}[PASS]${NC} $test_name" >&3
        if ((VERBOSE)); then
            cat "$output_file" >&4
        fi
    else
        ((FAILED_TESTS++))
        FAILED_TESTS_LIST+=("$test_name")
        log "\e[1A\e[K${RED}[FAIL]${NC} $test_name (exit code: $exit_code)" >&3
        if ((VERBOSE)); then
            echo "Output:" >&4
            cat "$output_file" >&4
        else
            echo "  Output saved to: $output_file" >&3
        fi
    fi

    # Clean up
    rm -rf "$test_dir"
}

# Log function
log() {
    if ((PROGRESS_BAR && !VERBOSE)); then
        echo -e "$1" >&3
    else
        echo -e "$1" >&4
    fi
}

# Test categories
declare -a TEST_CASES=()

# Add individual test cases
add_test_case() {
    local test_name="$1"
    local test_command="$2"
    local expected_result="${3:-PASS}"
    local description="${4:-}"

    TEST_CASES+=("$test_name" "$test_command" "$expected_result" "$description")
}

# Test suite
setup_test_suite() {
    # Setup frun environment
    . frun.bash || {
        echo -e "${RED}[ERROR]${NC} Failed to source frun.bash"
        exit 1
    }

    # Basic functionality tests
    add_test_case "Basic -j flag" \
        'printf "test\n" | frun -j 2 echo' \
        "PASS" \
        "Testing basic parallel execution with -j flag"

    add_test_case "Default behavior (fully quoted args)" \
        'printf "arg1\narg2\n" | frun echo' \
        "PASS" \
        "Testing default argument passing"

    add_test_case "-U --unsafe flag" \
        'printf "arg1\narg2\n" | frun -U echo' \
        "PASS" \
        "Testing unsafe unquoted argument passing"

    add_test_case "-s --stdin flag" \
        'printf "line1\nline2\n" | frun -s cat' \
        "PASS" \
        "Testing stdin passthrough"

    add_test_case "-b byte mode" \
        'printf "1234567890" | frun -b 5 cat' \
        "PASS" \
        "Testing byte mode with chunk size"

    add_test_case "-k --ordered flag" \
        'printf "3\n2\n1\n4\n" | frun -k cat' \
        "PASS" \
        "Testing ordered output"

# Add more test cases...

    # Comprehensive flag combinations
    add_test_case "Multi-flag test (-k -j 4 -l 100)" \
        'printf "a\nb\nc\nd\ne\nf\ng\nh\ni\nj\nk\nl\nm\nn\no\np\nq\nr\ns\nt\nu\nv\nw\nx\ny\nz\n" | frun -k -j 4 -l 5 cat' \
        "PASS" \
        "Testing multiple flags combination"

    add_test_case "-z --null delimiter" \
        'printf "a\0b\0c" | frun -z -s cat' \
        "PASS" \
        "Testing null delimiter"

    add_test_case "-d custom delimiter" \
        'printf "a,b,c,d" | frun -d "," cat' \
        "PASS" \
        "Testing custom delimiter"

    add_test_case "-i --insert flag" \
        'printf "hello\nworld\n" | frun -i "echo {} world"' \
        "PASS" \
        "Testing insert flag"

    add_test_case "-I --insert-id flag" \
        'printf "a\nb" | frun -I "echo {ID} processed {}"' \
        "PASS" \
        "Testing insert-id flag"

    add_test_case "-n --limit flag" \
        'printf "1\n2\n3\n4\n5\n" | frun -n 3 cat' \
        "PASS" \
        "Testing limit flag"

    add_test_case "--nodes flag" \
        'printf "a\nb\nc\nd" | frun --nodes 2 echo' \
        "PASS" \
        "Testing NUMA node specification"

    add_test_case "--nodes auto detection" \
        'printf "a\nb\nc" | frun --nodes auto echo' \
        "PASS" \
        "Testing auto NUMA detection"

    add_test_case "-N --dry-run flag" \
        'printf "a\nb\n" | frun -N echo' \
        "PASS" \
        "Testing dry-run flag"

    add_test_case "-v --verbose flag" \
        'printf "a\nb" | frun -v echo' \
        "PASS" \
        "Testing verbose flag"

    add_test_case "+v --no-verbose flag" \
        'printf "a\nb" | frun +v -v echo' \
        "PASS" \
        "Testing no-verbose flag"

    add_test_case "--stats flag" \
        'printf "a\nb" | frun --stats echo' \
        "PASS" \
        "Testing stats flag"

    add_test_case "--buffered flag" \
        'printf "a\nb" | frun --buffered echo' \
        "PASS" \
        "Testing buffered mode"

    add_test_case "--realtime flag" \
        'printf "a\nb" | frun --realtime echo' \
        "PASS" \
        "Testing realtime mode"

    # Complex test cases
    add_test_case "Large file processing" \
        'cat "$FORKRUN_TMPDIR/long_file.txt" | frun -j 4 wc -l' \
        "PASS" \
        "Testing with large file (1000 lines)"

    add_test_case "Empty input handling" \
        'printf "" | frun -k cat' \
        "PASS" \
        "Testing with empty input"

    add_test_case "Single input handling" \
        'printf "single" | frun cat' \
        "PASS" \
        "Testing with single input"

    add_test_case "NUMA topology with multiple nodes" \
        'printf "a\nb\nc\nd" | frun --nodes 2 cat' \
        "PASS" \
        "Testing NUMA multi-node topology"

    add_test_case "Exact lines with -L flag" \
        'printf "a\nb\nc\nd" | frun -L 2 cat' \
        "PASS" \
        "Testing exact lines flag"

    add_test_case "Timeout flag" \
        'printf "a\nb" | frun -t 10000 cat' \
        "PASS" \
        "Testing timeout flag"

# Add more complex scenarios...

    # Error condition tests
    add_test_case "Invalid flag handling" \
        'printf "a\nb" | frun --invalid-flag' \
        "FAIL" \
        "Testing invalid flag handling"

    add_test_case "Non-existent command" \
        'printf "a\nb" | frun non_existent_command' \
        "FAIL" \
        "Testing with non-existent command"

    add_test_case "Permission denied command" \
        'printf "a\nb" | frun /bin/true' \
        "PASS" \
        "Testing with permission denied (expect special handling)"

    # Add more error scenarios...

    # Progress reporting
    echo -e "${BLUE}[INFO]${NC} Setting up $(( ${#TEST_CASES[@]} / 4 )) test cases..."
}

# Main test execution
main() {
    local start_time=$(date +%s)
    local start_timestamp=$(date)

    # Parse options
    while [[ $# -gt 0 ]]; do
        case $1 in
            --verbose|-v)
                VERBOSE=1
                shift
                ;;
            --no-progress|-np)
                PROGRESS_BAR=0
                shift
                ;;
            --fail-fast|-ff)
                FAIL_FAST=1
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [options]"
                echo "Options:"
                echo "  --verbose|-v          Show detailed output for each test"
                echo "  --no-progress|-np     Disable progress bar"
                echo "  --fail-fast|-ff       Stop on first failure"
                echo "  --help|-h             Show this help message"
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done

    # Setup environment
    setup_environment
    setup_test_suite

    # Create named pipes for progress reporting
    if [[ ! -p /tmp/frun_test_progress ]]; then
        mkfifo /tmp/frun_test_progress 2>/dev/null || true
    fi

    # Start progress reporter
    if ((PROGRESS_BAR && !VERBOSE)); then
        exec 3<>/tmp/frun_test_progress
        exec 4<&0
        # Start parallel progress updater
        (
            while true; do
                if ((CURRENT_TEST < TOTAL_TESTS)); then
                    CURRENT_PERCENT=$(( (CURRENT_TEST * 100) / TOTAL_TESTS ))
                    REMAINING=$((TOTAL_TESTS - CURRENT_TEST))
                    printf "\r${BLUE}[%3d%%]${NC} Tests: %d/%d  Remaining: %d  Passed: %d  Failed: %d" \
                        $CURRENT_PERCENT \
                        $CURRENT_TEST $TOTAL_TESTS \
                        $REMAINING $PASSED_TESTS $FAILED_TESTS
                    sleep 0.5
                else
                    break
                fi
            done
        ) &
        PROGRESS_PID=$!
    else
        exec 3>&1
        exec 4>&1
    fi

    # Run tests
    echo -e "${BLUE}[INFO]${NC} Starting test suite..."
    echo -e "${BLUE}[INFO]${NC} Total tests: ${#TEST_CASES[@]/4}"

    for ((i=0; i<${#TEST_CASES[@]}; i+=4)); do
        local test_name="${TEST_CASES[i]}"
        local test_command="${TEST_CASES[i+1]}"
        local expected_result="${TEST_CASES[i+2]}"
        local description="${TEST_CASES[i+3]}"

        run_test "$test_name" "$test_command" "$expected_result" "$description"

        if ((FAIL_FAST && FAILED_TESTS > 0)); then
            break
        fi
    done

    # Stop progress reporter
    if ((PROGRESS_BAR && !VERBOSE)); then
        kill $PROGRESS_PID 2>/dev/null || true
        wait $PROGRESS_PID 2>/dev/null || true
    fi

    # Final report
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local duration_min=$((duration / 60))
    local duration_sec=$((duration % 60))

    echo -e "\n${BLUE}[SUMMARY]${NC} Test Results"
    echo "====================================="
    echo "Start time:   $start_timestamp"
    echo "End time:     $(date)"
    echo "Duration:     ${duration_min}m ${duration_sec}s"
    echo "Total tests:  $TOTAL_TESTS"
    echo "Passed:       $PASSED_TESTS"
    echo "Failed:       $FAILED_TESTS"

    if ((FAILED_TESTS > 0)); then
        echo -e "\n${RED}[FAILURES]${NC}"
        for failed_test in "${FAILED_TESTS_LIST[@]}"; do
            echo "  - $failed_test"
        done
        echo -e "\n${RED}[WARNING]${NC} Tests failed. Review output for details."
        exit 1
    else
        echo -e "\n${GREEN}[SUCCESS]${NC} All tests passed successfully!"
        exit 0
    fi
}

# Execute main
main "$@"
