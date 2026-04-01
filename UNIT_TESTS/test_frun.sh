#!/usr/bin/env bash
# ============================================================================
# FORKRUN COMPREHENSIVE TEST SUITE
# ============================================================================
# This script tests all major modes, flags, and edge cases of forkrun.
# It runs each test in a clean subshell, compares outputs, and reports results.
# Tests are self-verifying with clear PASS/FAIL indicators.
# ============================================================================

#set -euo pipefail

# Color codes for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
CYAN='\033[1;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Test counters (global)
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0
SKIPPED_TESTS=0

# Test results storage (for summary)
declare -A TEST_RESULTS
declare -A TEST_ERRORS

# Temporary directory for test artifacts
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT

# Path to frun.bash (assume script is in same directory as test suite)
FRUN_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/frun.bash"
if [[ ! -f "$FRUN_SOURCE" ]]; then
  echo -e "${RED}ERROR: frun.bash not found at $FRUN_SOURCE${NC}"
  echo "Please run this test suite from the forkrun repository root."
  exit 1
fi

# ============================================================================
# TEST UTILITY FUNCTIONS
# ============================================================================

# Print test progress header
print_header() {
  echo
  echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${CYAN}${BOLD}  FORKRUN TEST SUITE${NC}"
  echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Print test section header
print_section() {
  echo
  echo -e "${BLUE}${BOLD}▶ $1${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Print test result line
print_test_result() {
  local status=$1
  local name="$2"
  local detail="$3"

  case $status in
    PASS) echo -e "  ${GREEN}✓${NC} $name" ;;
    FAIL) echo -e "  ${RED}✗${NC} $name${RED} $detail${NC}" ;;
    SKIP) echo -e "  ${YELLOW}○${NC} $name${YELLOW} (skipped: $detail)${NC}" ;;
  esac
}

# Run a single test and record result
# Usage: run_test <test_name> <command> <expected_output> [expected_exit=0]
# Run a single test and record result
# Usage: run_test <test_name> <command> <expected_output> [expected_exit=0]
run_test() {
  local test_name="$1"
  local cmd="$2"
  local expected_output="$3"
  local expected_exit="${4:-0}"

  ((TOTAL_TESTS++))

  # Create temp files for this test
  local stdout_file stderr_file
  stdout_file=$(mktemp)
  stderr_file=$(mktemp)

  # Run the test in a clean subshell
  local exit_code
  if bash -c "source '$FRUN_SOURCE' && $cmd" >"$stdout_file" 2>"$stderr_file"; then
    exit_code=0
  else
    exit_code=$?
  fi

  local stdout_content stderr_content
  stdout_content=$(cat "$stdout_file")
  stderr_content=$(cat "$stderr_file")

  # Detect if ordered mode is enabled
  local has_order=false
  if [[ "$cmd" =~ -(k|-ordered|-(keep|keep-order)) ]]; then
    has_order=true
  fi

  # Normalize output if not using ordered mode
  local compare_actual="$stdout_content"
  local compare_expected="$expected_output"

  if ! $has_order; then
    compare_actual=$(echo "$stdout_content" | sort -V)
    compare_expected=$(echo "$expected_output" | sort -V)
  fi

  # Compare results
  local passed=true
  local fail_reason=""

  if [[ "$exit_code" -ne "$expected_exit" ]]; then
    passed=false
    fail_reason="exit $exit_code (expected $expected_exit)"
  elif [[ "$compare_actual" != "$compare_expected" ]]; then
    passed=false
    fail_reason="stdout mismatch"
  fi

  # Record result
  if $passed; then
    TEST_RESULTS["$test_name"]="PASS"
    ((PASSED_TESTS++))
    print_test_result "PASS" "$test_name"
  else
    TEST_RESULTS["$test_name"]="FAIL"
    TEST_ERRORS["$test_name"]="$fail_reason"
    ((FAILED_TESTS++))
    print_test_result "FAIL" "$test_name" "$fail_reason"

    # Show detailed failure on first failure if verbose or failure
    if [[ "${CI:-}" != "true" ]]; then
      echo -e "    ${YELLOW}Command:${NC} $cmd"
      # Show the non-normalized diffs to help debugging
      echo -e "    ${YELLOW}Expected stdout:${NC}"
      echo "      $(echo "$expected_output" | sed 's/^/        /')"
      echo -e "    ${YELLOW}Actual stdout:${NC}"
      echo "      $(echo "$stdout_content" | sed 's/^/        /')"
      [[ -n "$stderr_content" ]] && {
        echo -e "    ${YELLOW}Stderr:${NC}"
        echo "      $(echo "$stderr_content" | sed 's/^/        /')"
      }
    fi
  fi

  rm -f "$stdout_file" "$stderr_file"
}

# Run a test that checks regex pattern on every line of stdout
# Usage: run_test_regex <test_name> <command> <line_regex> [expected_exit=0]
run_test_regex() {
  local test_name="$1"
  local cmd="$2"
  local line_regex="$3"
  local expected_exit="${4:-0}"

  ((TOTAL_TESTS++))

  local stdout_file stderr_file
  stdout_file=$(mktemp)
  stderr_file=$(mktemp)

  local exit_code
  if bash -c "source '$FRUN_SOURCE' && $cmd" >"$stdout_file" 2>"$stderr_file"; then
    exit_code=0
  else
    exit_code=$?
  fi

  local stdout_content
  stdout_content=$(cat "$stdout_file")
  local stderr_content
  stderr_content=$(cat "$stderr_file")

  local passed=true
  local fail_reason=""

  if [[ "$exit_code" -ne "$expected_exit" ]]; then
    passed=false
    fail_reason="exit $exit_code (expected $expected_exit)"
  else
    # Check every line matches regex
    local line_num=0
    while IFS= read -r line; do
      ((line_num++))
      if [[ ! "$line" =~ $line_regex ]]; then
        passed=false
        fail_reason="line $line_num does not match regex: '$line'"
        break
      fi
    done <<< "$stdout_content"
  fi

  if $passed; then
    TEST_RESULTS["$test_name"]="PASS"
    ((PASSED_TESTS++))
    print_test_result "PASS" "$test_name"
  else
    TEST_RESULTS["$test_name"]="FAIL"
    TEST_ERRORS["$test_name"]="$fail_reason"
    ((FAILED_TESTS++))
    print_test_result "FAIL" "$test_name" "$fail_reason"

    if [[ "${CI:-}" != "true" ]]; then
      echo -e "    ${YELLOW}Command:${NC} $cmd"
      echo -e "    ${YELLOW}Regex:${NC} $line_regex"
      [[ -n "$stderr_content" ]] && {
        echo -e "    ${YELLOW}Stderr:${NC}"
        echo "      $(echo "$stderr_content" | sed 's/^/        /')"
      }
    fi
  fi

  rm -f "$stdout_file" "$stderr_file"
}

# Test that a command produces specific stderr
# Usage: run_test_stderr <test_name> <command> <expected_stderr> [expected_exit=0]
run_test_stderr() {
  local test_name="$1"
  local cmd="$2"
  local expected_stderr="$3"
  local expected_exit="${4:-0}"

  ((TOTAL_TESTS++))

  local stdout_file stderr_file
  stdout_file=$(mktemp)
  stderr_file=$(mktemp)

  local exit_code
  if bash -c "source '$FRUN_SOURCE' && $cmd" >"$stdout_file" 2>"$stderr_file"; then
    exit_code=0
  else
    exit_code=$?
  fi

  local stdout_content stderr_content
  stdout_content=$(cat "$stdout_file")
  stderr_content=$(cat "$stderr_file")

  local passed=true
  local fail_reason=""

  if [[ "$exit_code" -ne "$expected_exit" ]]; then
    passed=false
    fail_reason="exit $exit_code (expected $expected_exit)"
  elif [[ "$stderr_content" != "$expected_stderr" ]]; then
    passed=false
    fail_reason="stderr mismatch"
  fi

  if $passed; then
    TEST_RESULTS["$test_name"]="PASS"
    ((PASSED_TESTS++))
    print_test_result "PASS" "$test_name"
  else
    TEST_RESULTS["$test_name"]="FAIL"
    TEST_ERRORS["$test_name"]="$fail_reason"
    ((FAILED_TESTS++))
    print_test_result "FAIL" "$test_name" "$fail_reason"

    if [[ "${CI:-}" != "true" ]]; then
      echo -e "    ${YELLOW}Command:${NC} $cmd"
      if [[ "$stderr_content" != "$expected_stderr" ]]; then
        echo -e "    ${YELLOW}Expected stderr:${NC}"
        echo "      $(echo "$expected_stderr" | sed 's/^/        /')"
        echo -e "    ${YELLOW}Actual stderr:${NC}"
        echo "      $(echo "$stderr_content" | sed 's/^/        /')"
      fi
    fi
  fi

  rm -f "$stdout_file" "$stderr_file"
}

# Skip a test with reason
skip_test() {
  local test_name="$1"
  local reason="$2"

  ((TOTAL_TESTS++))
  ((SKIPPED_TESTS++))
  TEST_RESULTS["$test_name"]="SKIP"
  print_test_result "SKIP" "$test_name" "$reason"
}

# ============================================================================
# TEST DATA SETUP
# ============================================================================

# Create test input files
LINE_INPUT="$TEST_DIR/lines.txt"
BYTE_INPUT="$TEST_DIR/bytes.bin"
DELIM_INPUT="$TEST_DIR/delim.txt"
NULL_INPUT="$TEST_DIR/null.bin"
SPACE_INPUT="$TEST_DIR/spaces.txt"
MIXED_INPUT="$TEST_DIR/mixed.txt"

# Generate test data
echo -e "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10" > "$LINE_INPUT"
head -c 100 /dev/zero | tr '\0' 'a' > "$BYTE_INPUT"
printf 'field1:field2:field3\nfield4:field5:field6\n' > "$DELIM_INPUT"
printf 'a\0b\0c\0d\0' > "$NULL_INPUT"
printf 'a b\nc d\ne f\n' > "$SPACE_INPUT"
printf 'αβγ\nδεζ\nηθι\n' > "$MIXED_INPUT"  # Unicode lines

# ============================================================================
# CORE MODE TESTS
# ============================================================================

print_section "Core Modes (Default, Ordered, Realtime)"

# Test 1: Default mode (buffered, unordered)
run_test "Default mode" \
  "cat '$LINE_INPUT' | frun printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 2: Ordered mode (-k)
run_test "Ordered mode (-k)" \
  "cat '$LINE_INPUT' | frun -k printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 3: Realtime mode (-u)
run_test "Realtime mode (-u)" \
  "cat '$LINE_INPUT' | frun -u printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 4: Buffered ordered (explicit)
run_test "Buffered ordered (--buffered -k)" \
  "cat '$LINE_INPUT' | frun --buffered -k printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# ============================================================================
# INPUT HANDLING MODES
# ============================================================================

print_section "Input Handling (stdin, bytes, delimiters)"

# Test 5: Stdin mode (-s)
run_test "Stdin mode (-s)" \
  "cat '$LINE_INPUT' | frun -s cat" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 6: Byte mode (-b)
run_test "Byte mode (-b 10)" \
  "cat '$BYTE_INPUT' | frun -b 10 cat" \
  "$(cat "$BYTE_INPUT")" \
  0

# Test 7: Byte mode with larger chunks
run_test "Byte mode (-b 50)" \
  "cat '$BYTE_INPUT' | frun -b 50 cat" \
  "$(cat "$BYTE_INPUT")" \
  0

# Test 8: Custom delimiter (-d :)
run_test "Custom delimiter (-d :)" \
  "cat '$DELIM_INPUT' | frun -d ':' printf \"%s\\n\"" \
  "field1
field2
field3
field4
field5
field6" \
  0

# Test 9: Null delimiter (-z)
run_test "Null delimiter (-z)" \
  "cat '$NULL_INPUT' | frun -z printf \"%s\\n\"" \
  "a
b
c
d" \
  0

# Test 10: Unicode support (delimiter default)
run_test "Unicode support" \
  "cat '$MIXED_INPUT' | frun printf \"%s\\n\"" \
  "αβγ
δεζ
ηθι" \
  0

# ============================================================================
# BATCH CONTROL
# ============================================================================

print_section "Batch Size Control (lines, bytes, exact)"

# Test 11: Fixed batch size (-l 2)
run_test "Fixed batch size (-l 2)" \
  "cat '$LINE_INPUT' | frun -l 2 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 12: Batch size range (-l 1:5)
run_test "Batch size range (-l 1:5)" \
  "cat '$LINE_INPUT' | frun -l 1:5 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 13: Exact lines (-L 3)
run_test "Exact lines (-L 3)" \
  "cat '$LINE_INPUT' | frun -L 3 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 14: Exact lines with limit (-L 4 -n 8)
run_test "Exact lines with limit (-L 4 -n 8)" \
  "cat '$LINE_INPUT' | frun -k -L 4 -n 8 printf \"%s\\n\"" \
  "$(seq 1 8)" \
  0

# ============================================================================
# WORKER SCALING
# ============================================================================

print_section "Worker Scaling (-j)"

# Test 15: Fixed workers (-j 2)
run_test "Fixed workers (-j 2)" \
  "cat '$LINE_INPUT' | frun -j 2 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 16: Worker range (-j 1:4)
run_test "Worker range (-j 1:4)" \
  "cat '$LINE_INPUT' | frun -j 1:4 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 17: Oversubscribe (--nodes=@2)
run_test "Oversubscribe (--nodes=@2)" \
  "cat '$LINE_INPUT' | frun --nodes=@2 -j 4 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# ============================================================================
# LIMITS & TIMEOUTS
# ============================================================================

print_section "Limits and Timeouts"

# Test 18: Record limit (-n 5)
run_test "Record limit (-n 5)" \
  "cat '$LINE_INPUT' | frun -k -n 5 printf \"%s\\n\"" \
  "$(head -n5 "$LINE_INPUT" )" \
  0

# Test 19: Limit with unordered (still should only output 5 lines)
run_test "Limit with unordered (-n 5)" \
  "cat '$LINE_INPUT' | frun -n 5 printf \"%s\\n\"" \
  "$(head -n5 "$LINE_INPUT"  | sort -V)" \
  0

# Test 20: Timeout (--timeout 100000) - note: this is hard to test deterministically
# We'll just test that the flag is accepted and doesn't break
run_test "Timeout flag accepted (--timeout 50000)" \
  "cat '$LINE_INPUT' | frun --timeout 50000 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 21: Greedy mode (--greedy) - timeout=0
run_test "Greedy mode (--greedy)" \
  "cat '$LINE_INPUT' | frun --greedy printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# ============================================================================
# STRING SUBSTITUTION
# ============================================================================

print_section "String Substitution (-i, -I)"

# Test 22: Insert mode (-i)
run_test "Insert mode (-i)" \
  "cat '$LINE_INPUT' | frun -i echo ARG:{}" \
  "$(cat "$LINE_INPUT" | sed 's/^/ARG:/')" \
  0

# Test 23: Insert ID mode (-I) - check format
run_test_regex "Insert ID mode (-I)" \
  "cat '$LINE_INPUT' | frun -I echo {ID}" \
  "^[0-9]+(\.[0-9]+){1,2}$" \
  0

# Test 24: Insert with custom command
run_test "Insert with custom command (-i)" \
  "cat '$LINE_INPUT' | frun -i printf \"[%s]\\n\" \"{}\"" \
  "$(cat "$LINE_INPUT" | sed 's/^/\[/;s/$/\]/')" \
  0

# ============================================================================
# QUOTING & UNSAFE MODE
# ============================================================================

print_section "Quoting and Unsafe Mode"

# Test 25: Default (safe) quoting with spaces
run_test "Safe quoting with spaces" \
  "cat '$SPACE_INPUT' | frun printf \"%s\\n\"" \
  "a b
c d
e f" \
  0

# Test 26: Unsafe mode (-U)
# In unsafe mode, arguments are passed unquoted. With spaces, this causes word splitting.
# The output will have each word on a separate line (due to how bash splits).
run_test "Unsafe mode (-U) with spaces" \
  "cat '$SPACE_INPUT' | frun -U printf \"%s\\n\"" \
  "a
b
c
d
e
f" \
  0

# Test 27: Safe mode explicit (+U)
run_test "Explicit safe mode (+U)" \
  "cat '$SPACE_INPUT' | frun +U printf \"%s\\n\"" \
  "a b
c d
e f" \
  0

# ============================================================================
# OUTPUT MODES COMBINATIONS
# ============================================================================

print_section "Output Mode Combinations"

# Test 28: Stdin + ordered
run_test "Stdin + ordered (-s -k)" \
  "cat '$LINE_INPUT' | frun -s -k cat" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 29: Byte mode + realtime
run_test "Byte + realtime (-b 10 -u)" \
  "cat '$BYTE_INPUT' | frun -b 10 -u cat" \
  "$(cat "$BYTE_INPUT")" \
  0

# Test 30: Byte + ordered
run_test "Byte + ordered (-b 50 -k)" \
  "cat '$BYTE_INPUT' | frun -b 50 -k cat" \
  "$(cat "$BYTE_INPUT")" \
  0

# Test 31: Exact lines + stdin
run_test "Exact lines + stdin (-L 3 -s)" \
  "cat '$LINE_INPUT' | frun -L 3 -s cat" \
  "$(cat "$LINE_INPUT")" \
  0

# ============================================================================
# NUMA TOPOLOGY
# ============================================================================

print_section "NUMA Topology"

# Test 32: Auto NUMA (default)
run_test "Auto NUMA (--nodes=auto)" \
  "cat '$LINE_INPUT' | frun --nodes=auto printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 33: Explicit node list (if multiple nodes exist)
# On single-node systems, this will map to node 0 only. Still valid.
run_test "Explicit nodes (--nodes=0)" \
  "cat '$LINE_INPUT' | frun --nodes=0 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 34: Multi-node (if available)
# This will work even on single-node (maps to node 0)
run_test "Multi-node (--nodes=2)" \
  "cat '$LINE_INPUT' | frun --nodes=2 -j 4 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 35: Exact lines with NUMA (should downgrade to -l)
# Expected: warning on stderr, normal output
run_test_stderr "Exact lines with NUMA (downgrade warning)" \
  "cat '$LINE_INPUT' | frun --nodes=2 -L 3 printf \"%s\\n\"" \
  "cannot guarantee exactly" \
  0

# ============================================================================
# SPECIAL FLAGS
# ============================================================================

print_section "Special Flags"

# Test 36: Dry run (-N)
expected_dry=$(cat "$LINE_INPUT" | sed 's/^/printf '\''%s\\n'\'' /;s/$/ \\"$@\\"/' | sed "s/'/\\\\'/g")
# Simplify: for dry run, we expect to see the command echoed. This is approximate.
run_test "Dry run (-N)" \
  "cat '$LINE_INPUT' | frun -N printf \"%s\\n\"" \
  "" \
  0
# Note: Dry run output is complex; we skip detailed check. Just ensure exit 0.

# Test 37: Version (-V)
run_test "Version (-V)" \
  "frun -V" \
  "forkrun v3.0.1" \
  0

# Test 38: Help (--help)
run_test "Help (--help)" \
  "frun --help" \
  "USAGE:" \
  0

# Test 39: Verbose flag (-v)
run_test_stderr "Verbose flag (-v)" \
  "cat '$LINE_INPUT' | frun -v printf \"%s\\n\"" \
  "SPAWNED" \
  0

# Test 40: Stats flag (--stats) - only prints in NUMA mode, so skip or check empty
run_test "Stats flag (--stats) UMA" \
  "cat '$LINE_INPUT' | frun --stats printf \"%s\\n\"" \
  "" \
  0

# ============================================================================
# EDGE CASES & ERROR CONDITIONS
# ============================================================================

print_section "Edge Cases"

# Test 41: Empty input
EMPTY_INPUT="$TEST_DIR/empty.txt"
touch "$EMPTY_INPUT"
run_test "Empty input" \
  "cat '$EMPTY_INPUT' | frun printf \"%s\\n\"" \
  "" \
  0

# Test 42: Single line input
SINGLE_LINE="$TEST_DIR/single.txt"
echo "only_line" > "$SINGLE_LINE"
run_test "Single line input" \
  "cat '$SINGLE_LINE' | frun printf \"%s\\n\"" \
  "only_line" \
  0

# Test 43: Large batch size (larger than input)
run_test "Batch larger than input (-l 100)" \
  "cat '$LINE_INPUT' | frun -l 100 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 44: Workers > lines (-j 20)
run_test "More workers than lines (-j 20)" \
  "cat '$LINE_INPUT' | frun -j 20 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 45: Backspace and control characters (if supported)
CTRL_INPUT="$TEST_DIR/ctrl.txt"
printf 'a\tb\nc\td\n' > "$CTRL_INPUT"
run_test "Tab characters" \
  "cat '$CTRL_INPUT' | frun printf \"%s\\n\"" \
  "a	b
c	d" \
  0

# ============================================================================
# COMPLEX COMBINATIONS
# ============================================================================

print_section "Complex Flag Combinations"

# Test 46: Multiple flags: -s -k -n 5
run_test "Combination: -s -k -n 5" \
  "cat '$LINE_INPUT' | frun -s -k -n 5 cat" \
  "$(head -n5 "$LINE_INPUT")" \
  0

# Test 47: Multiple flags: -b 20 -u -j 2
run_test "Combination: -b 20 -u -j 2" \
  "cat '$BYTE_INPUT' | frun -b 20 -u -j 2 cat" \
  "$(cat "$BYTE_INPUT")" \
  0

# Test 48: Multiple flags: --nodes=2 -j 4 -l 2 -k
run_test "Combination: --nodes=2 -j 4 -l 2 -k" \
  "cat '$LINE_INPUT' | frun --nodes=2 -j 4 -l 2 -k printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 49: Multiple flags: -L 2 --timeout 100000 -v
run_test "Combination: -L 2 --timeout 100000 -v" \
  "cat '$LINE_INPUT' | frun -L 2 --timeout 100000 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 50: Multiple flags: -b 33 --nodes=auto -s
run_test "Combination: -b 33 --nodes=auto -s" \
  "cat '$BYTE_INPUT' | frun -b 33 --nodes=auto -s cat" \
  "$(cat "$BYTE_INPUT")" \
  0

# ============================================================================
# PERFORMANCE STRESS TESTS (shorter versions)
# ============================================================================

print_section "Performance & Stress (Quick Checks)"

# Create larger input (1000 lines)
LARGE_INPUT="$TEST_DIR/large.txt"
seq 1 1000 > "$LARGE_INPUT"

# Test 51: Large input with default settings
run_test "Large input (1000 lines) default" \
  "cat '$LARGE_INPUT' | frun printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT"00 | sort -V)" \
  0

# Test 52: Large input with -j 8
run_test "Large input with -j 8" \
  "cat '$LARGE_INPUT' | frun -j 8 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT"00 | sort -V)" \
  0

# Test 53: Large input with -b 1k
LARGE_BYTE_INPUT="$TEST_DIR/large_byte.bin"
head -c 10000 /dev/zero | tr '\0' 'x' > "$LARGE_BYTE_INPUT"
run_test "Large byte input (10k) -b 1024" \
  "cat '$LARGE_BYTE_INPUT' | frun -b 1024 cat" \
  "$(cat "$LARGE_BYTE_INPUT")" \
  0

# ============================================================================
# DEPRECATED/ALIAS FLAGS
# ============================================================================

print_section "Alias Flags"

# Test 54: --atomic (same as --buffered)
run_test "Alias: --atomic (buffered)" \
  "cat '$LINE_INPUT' | frun --atomic printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 55: --keep-order (same as -k)
run_test "Alias: --keep-order" \
  "cat '$LINE_INPUT' | frun --keep-order printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# Test 56: --unbuffered (same as -u)
run_test "Alias: --unbuffered" \
  "cat '$LINE_INPUT' | frun --unbuffered printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")" \
  0

# ============================================================================
# FINAL SUMMARY
# ============================================================================

print_header

echo -e "${BOLD}TEST SUMMARY${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
printf "Total:  %3d\n" "$TOTAL_TESTS"
printf "Passed: %3d (${GREEN}%3.1f%%${NC})\n" "$PASSED_TESTS" "$(awk "BEGIN {printf 100*$PASSED_TESTS/$TOTAL_TESTS}")"
printf "Failed: %3d (${RED}%3.1f%%${NC})\n" "$FAILED_TESTS" "$(awk "BEGIN {printf 100*$FAILED_TESTS/$TOTAL_TESTS}")"
printf "Skipped: %3d (${YELLOW}%3.1f%%${NC})\n" "$SKIPPED_TESTS" "$(awk "BEGIN {printf 100*$SKIPPED_TESTS/$TOTAL_TESTS}")"
echo

if (( FAILED_TESTS > 0 )); then
  echo -e "${RED}${BOLD}FAILED TESTS:${NC}"
  for test in "${!TEST_RESULTS[@]}"; do
    if [[ "${TEST_RESULTS[$test]}" == "FAIL" ]]; then
      echo "  - $test: ${TEST_ERRORS[$test]}"
    fi
  done
  echo
  echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${RED}OVERALL: ${FAILED_TESTS} FAILURE(S)${NC}"
  echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  exit 1
else
  echo -e "${GREEN}${BOLD}ALL TESTS PASSED!${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  exit 0
fi
