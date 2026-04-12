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
# DETECT SYSTEM TOPOLOGY (NUMA vs UMA)
# ============================================================================
IS_NUMA=false
NUMA_CHECK=$(bash -c "source '$FRUN_SOURCE' && echo 'test' | frun --nodes=auto --stats cat 2>&1" || true)
if [[ "$NUMA_CHECK" =~ "NUMA TELEMETRY" ]]; then
  IS_NUMA=true
fi

# ============================================================================
# TEST UTILITY FUNCTIONS
# ============================================================================

print_header() {
  echo
  echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${CYAN}${BOLD}  FORKRUN TEST SUITE${NC}"
  if $IS_NUMA; then
      echo -e "${CYAN}${BOLD}  Detected Topology: NUMA${NC}"
  else
      echo -e "${CYAN}${BOLD}  Detected Topology: UMA${NC}"
  fi
  echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_section() {
  echo
  echo -e "${BLUE}${BOLD}▶ $1${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

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

compare_token_sets() {
    local actual="$1"
    local expected="$2"
    
    local actual_sorted=$(echo "$actual" | tr -s ' \t\n' '\n' | sort)
    local expected_sorted=$(echo "$expected" | tr -s ' \t\n' '\n' | sort)
    
    if [[ "$actual_sorted" == "$expected_sorted" ]]; then
        return 0
    else
        return 1
    fi
}

run_test() {
  local test_name="$1"
  local cmd="$2"
  local expected_output="$3"
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

  local has_order=false
  if [[ "$cmd" =~ -(k|-ordered|-(keep|keep-order)) ]]; then
    has_order=true
  fi

  local passed=true
  local fail_reason=""

  if [[ "$exit_code" -ne "$expected_exit" ]]; then
    passed=false
    fail_reason="exit $exit_code (expected $expected_exit)"
  else
      if $has_order; then
          if [[ "$stdout_content" != "$expected_output" ]]; then
              passed=false
              fail_reason="stdout mismatch (ordered)"
          fi
      else
          if ! compare_token_sets "$stdout_content" "$expected_output"; then
              passed=false
              fail_reason="stdout token set mismatch (unordered)"
          fi
      fi
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
      echo -e "    ${YELLOW}Expected tokens:${NC}"
      echo "      $(echo "$expected_output" | tr -s ' \t\n' ' ' | head -c 100)..."
      echo -e "    ${YELLOW}Actual tokens:${NC}"
      echo "      $(echo "$stdout_content" | tr -s ' \t\n' ' ' | head -c 100)..."
      [[ -n "$stderr_content" ]] && {
        echo -e "    ${YELLOW}Stderr:${NC}"
        echo "      $(echo "$stderr_content" | sed 's/^/        /')"
      }
    fi
  fi

  rm -f "$stdout_file" "$stderr_file"
}

run_test_regex() {
  local test_name="$1"
  local cmd="$2"
  local line_regex="$3"
  local expected_exit="${4:-0}"
  local check_stderr="${5:-false}"

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

  local content
  if $check_stderr; then
      content=$(cat "$stderr_file")
  else
      content=$(cat "$stdout_file")
  fi

  local passed=true
  local fail_reason=""

  if [[ "$exit_code" -ne "$expected_exit" ]]; then
    passed=false
    fail_reason="exit $exit_code (expected $expected_exit)"
  else
    if [[ ! "$content" =~ $line_regex ]]; then
        passed=false
        fail_reason="content does not match regex: '$line_regex'"
    fi
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
      echo -e "    ${YELLOW}Actual Content:${NC}"
      echo "      $(echo "$content" | sed 's/^/        /')"
    fi
  fi

  rm -f "$stdout_file" "$stderr_file"
}

run_test_stderr() {
  local test_name="$1"
  local cmd="$2"
  local expected_stderr_regex="$3"
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
  elif [[ -z "$expected_stderr_regex" ]]; then
    if [[ -n "$stderr_content" ]]; then
        passed=false
        fail_reason="expected empty stderr, got content"
    fi
  elif [[ ! "$stderr_content" =~ $expected_stderr_regex ]]; then
    passed=false
    fail_reason="stderr regex mismatch"
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
      echo -e "    ${YELLOW}Expected stderr regex:${NC} ${expected_stderr_regex:-<EMPTY>}"
      echo -e "    ${YELLOW}Actual stderr:${NC}"
      echo "      $(echo "$stderr_content" | sed 's/^/        /')"
    fi
  fi

  rm -f "$stdout_file" "$stderr_file"
}

# ============================================================================
# TEST DATA SETUP
# ============================================================================

LINE_INPUT="$TEST_DIR/lines.txt"
BYTE_INPUT="$TEST_DIR/bytes.bin"
DELIM_INPUT="$TEST_DIR/delim.txt"
NULL_INPUT="$TEST_DIR/null.bin"
SPACE_INPUT="$TEST_DIR/spaces.txt"
MIXED_INPUT="$TEST_DIR/mixed.txt"

echo -e "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10" > "$LINE_INPUT"
head -c 100 /dev/zero | tr '\0' 'a' > "$BYTE_INPUT"
printf 'field1:field2:field3\nfield4:field5:field6\n' > "$DELIM_INPUT"
printf 'a\0b\0c\0d\0' > "$NULL_INPUT"
printf 'a b\nc d\ne f\n' > "$SPACE_INPUT"
printf 'αβγ\nδεζ\nηθι\n' > "$MIXED_INPUT"

# ============================================================================
# CORE MODE TESTS
# ============================================================================

print_section "Core Modes (Default, Ordered, Realtime)"

run_test "Default mode" \
  "cat '$LINE_INPUT' | frun printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Ordered mode (-k)" \
  "cat '$LINE_INPUT' | frun -k printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Realtime mode (-u)" \
  "cat '$LINE_INPUT' | frun -u printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Buffered ordered (--buffered -k)" \
  "cat '$LINE_INPUT' | frun --buffered -k printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

# ============================================================================
# INPUT HANDLING MODES
# ============================================================================

print_section "Input Handling (stdin, bytes, delimiters)"

run_test "Stdin mode (-s)" \
  "cat '$LINE_INPUT' | frun -s cat" \
  "$(cat "$LINE_INPUT")"

run_test "Byte mode (-b 10)" \
  "cat '$BYTE_INPUT' | frun -b 10 cat" \
  "$(cat "$BYTE_INPUT")"

run_test "Byte mode (-b 50)" \
  "cat '$BYTE_INPUT' | frun -b 50 cat" \
  "$(cat "$BYTE_INPUT")"

run_test "Custom delimiter (-d :)" \
  "cat '$DELIM_INPUT' | frun -d ':' printf \"%s\\n\"" \
  "field1
field2
field3
field4
field5
field6"

run_test "Null delimiter (-z)" \
  "cat '$NULL_INPUT' | frun -z printf \"%s\\n\"" \
  "a
b
c
d"

run_test "Unicode support" \
  "cat '$MIXED_INPUT' | frun printf \"%s\\n\"" \
  "αβγ
δεζ
ηθι"

# ============================================================================
# BATCH CONTROL
# ============================================================================

print_section "Batch Size Control (lines, bytes, exact)"

run_test "Fixed batch size (-l 2)" \
  "cat '$LINE_INPUT' | frun -l 2 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Batch size range (-l 1:5)" \
  "cat '$LINE_INPUT' | frun -l 1:5 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Exact lines (-L 3)" \
  "cat '$LINE_INPUT' | frun -L 3 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

if $IS_NUMA; then
  run_test_stderr "Exact lines with limit (-L 4 -n 8)" \
    "cat '$LINE_INPUT' | frun -k -L 4 -n 8 printf \"%s\\n\" >/dev/null" \
    "NUMA optimizations prevent -L from working properly"
else
  run_test "Exact lines with limit (-L 4 -n 8)" \
    "cat '$LINE_INPUT' | frun -k -L 4 -n 8 printf \"%s\\n\"" \
    "$(seq 1 8)"
fi

# ============================================================================
# WORKER SCALING
# ============================================================================

print_section "Worker Scaling (-j)"

run_test "Fixed workers (-j 2)" \
  "cat '$LINE_INPUT' | frun -j 2 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Worker range (-j 1:4)" \
  "cat '$LINE_INPUT' | frun -j 1:4 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Oversubscribe (--nodes=@2)" \
  "cat '$LINE_INPUT' | frun --nodes=@2 -j 4 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

# ============================================================================
# LIMITS & TIMEOUTS
# ============================================================================

print_section "Limits and Timeouts"

run_test "Record limit (-n 5)" \
  "cat '$LINE_INPUT' | frun -k -n 5 printf \"%s\\n\"" \
  "$(head -n5 "$LINE_INPUT" )"

run_test "Limit with unordered (-n 5)" \
  "cat '$LINE_INPUT' | frun -n 5 printf \"%s\\n\"" \
  "$(head -n5 "$LINE_INPUT")"

run_test "Timeout flag accepted (--timeout 50000)" \
  "cat '$LINE_INPUT' | frun --timeout 50000 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

# ============================================================================
# STRING SUBSTITUTION
# ============================================================================

print_section "String Substitution (-i, -I)"

run_test "Insert mode (-i)" \
  "cat '$LINE_INPUT' | frun -l 1 -i echo ARG:{}" \
  "$(cat "$LINE_INPUT" | sed 's/^/ARG:/')"

run_test_regex "Insert ID mode (-I)" \
  "cat '$LINE_INPUT' | frun -I echo {ID} | head -n1" \
  "([0-9]+\.)?[0-9]+\.[0-9]+" \
  0 false

run_test "Insert with custom command (-i)" \
  "cat '$LINE_INPUT' | frun -l 1 -i printf \"[%s]\\n\" \"{}\"" \
  "$(cat "$LINE_INPUT" | sed 's/^/\[/;s/$/\]/')"

# ============================================================================
# QUOTING & UNSAFE MODE
# ============================================================================

print_section "Quoting and Unsafe Mode"

run_test "Safe quoting with spaces" \
  "cat '$SPACE_INPUT' | frun printf \"%s\\n\"" \
  "a b
c d
e f"

run_test "Unsafe mode (-U) with spaces" \
  "cat '$SPACE_INPUT' | frun -U printf \"%s\\n\"" \
  "a
b
c
d
e
f"

run_test "Explicit safe mode (+U)" \
  "cat '$SPACE_INPUT' | frun +U printf \"%s\\n\"" \
  "a b
c d
e f"

# ============================================================================
# OUTPUT MODES COMBINATIONS
# ============================================================================

print_section "Output Mode Combinations"

run_test "Stdin + ordered (-s -k)" \
  "cat '$LINE_INPUT' | frun -s -k cat" \
  "$(cat "$LINE_INPUT")"

run_test "Byte + realtime (-b 10 -u)" \
  "cat '$BYTE_INPUT' | frun -b 10 -u cat" \
  "$(cat "$BYTE_INPUT")"

run_test "Byte + ordered (-b 50 -k)" \
  "cat '$BYTE_INPUT' | frun -b 50 -k cat" \
  "$(cat "$BYTE_INPUT")"

run_test "Exact lines + stdin (-L 3 -s)" \
  "cat '$LINE_INPUT' | frun -L 3 -s cat" \
  "$(cat "$LINE_INPUT")"

# ============================================================================
# NUMA TOPOLOGY
# ============================================================================

print_section "NUMA Topology"

run_test "Auto NUMA (--nodes=auto)" \
  "cat '$LINE_INPUT' | frun --nodes=auto printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Explicit nodes (--nodes=0)" \
  "cat '$LINE_INPUT' | frun --nodes=0 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Multi-node (--nodes=2)" \
  "cat '$LINE_INPUT' | frun --nodes=2 -j 4 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

if $IS_NUMA; then
  run_test_stderr "Exact lines with NUMA (downgrade warning)" \
    "cat '$LINE_INPUT' | frun --nodes=2 -L 3 printf \"%s\\n\" >/dev/null" \
    "cannot guarantee exactly|NUMA optimizations prevent -L from working properly"
else
  run_test "Exact lines with NUMA (no warning in UMA)" \
    "cat '$LINE_INPUT' | frun --nodes=2 -L 3 printf \"%s\\n\"" \
    "$(cat "$LINE_INPUT")"
fi

# ============================================================================
# SPECIAL FLAGS
# ============================================================================

print_section "Special Flags"

run_test_regex "Dry run (-N)" \
  "cat '$LINE_INPUT' | frun -N printf \"%s\\n\"" \
  "printf" \
  0 false

run_test "Version (-V)" \
  "frun -V" \
  "forkrun v3.0.2"

run_test_regex "Help (--help)" \
  "frun --help 2>&1" \
  "USAGE:" \
  0 false

run_test_regex "Verbose flag (-v)" \
  "cat '$LINE_INPUT' | frun -v printf \"%s\\n\" >/dev/null" \
  "SPAWNED [0-9]+ workers" \
  0 true

if $IS_NUMA; then
  run_test_regex "Stats flag (--stats) NUMA" \
    "cat '$LINE_INPUT' | frun --stats printf \"%s\\n\" >/dev/null" \
    "NUMA TELEMETRY" \
    0 true
else
  run_test_stderr "Stats flag (--stats) UMA" \
    "cat '$LINE_INPUT' | frun --stats printf \"%s\\n\" >/dev/null" \
    ""
fi

# ============================================================================
# EDGE CASES & ERROR CONDITIONS
# ============================================================================

print_section "Edge Cases"

EMPTY_INPUT="$TEST_DIR/empty.txt"
touch "$EMPTY_INPUT"
run_test "Empty input" \
  "cat '$EMPTY_INPUT' | frun printf \"%s\\n\"" \
  ""

SINGLE_LINE="$TEST_DIR/single.txt"
echo "only_line" > "$SINGLE_LINE"
run_test "Single line input" \
  "cat '$SINGLE_LINE' | frun printf \"%s\\n\"" \
  "only_line"

run_test "Batch larger than input (-l 100)" \
  "cat '$LINE_INPUT' | frun -l 100 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "More workers than lines (-j 20)" \
  "cat '$LINE_INPUT' | frun -j 20 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

CTRL_INPUT="$TEST_DIR/ctrl.txt"
printf 'a\tb\nc\td\n' > "$CTRL_INPUT"
run_test "Tab characters" \
  "cat '$CTRL_INPUT' | frun printf \"%s\\n\"" \
  "a	b
c	d"

# ============================================================================
# COMPLEX COMBINATIONS
# ============================================================================

print_section "Complex Flag Combinations"

run_test "Combination: -s -k -n 5" \
  "cat '$LINE_INPUT' | frun -s -k -n 5 cat" \
  "$(head -n5 "$LINE_INPUT")"

run_test "Combination: -b 20 -u -j 2" \
  "cat '$BYTE_INPUT' | frun -b 20 -u -j 2 cat" \
  "$(cat "$BYTE_INPUT")"

run_test "Combination: --nodes=2 -j 4 -l 2 -k" \
  "cat '$LINE_INPUT' | frun --nodes=2 -j 4 -l 2 -k printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Combination: -L 2 --timeout 100000 -v" \
  "cat '$LINE_INPUT' | frun -L 2 --timeout 100000 printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Combination: -b 33 --nodes=auto -s" \
  "cat '$BYTE_INPUT' | frun -b 33 --nodes=auto -s cat" \
  "$(cat "$BYTE_INPUT")"

# ============================================================================
# PERFORMANCE STRESS TESTS (shorter versions)
# ============================================================================

print_section "Performance & Stress (Quick Checks)"

LARGE_INPUT="$TEST_DIR/large.txt"
seq 1 1000 > "$LARGE_INPUT"

run_test "Large input (1000 lines) default" \
  "cat '$LARGE_INPUT' | frun printf \"%s\\n\"" \
  "$(cat "$LARGE_INPUT")"

run_test "Large input with -j 8" \
  "cat '$LARGE_INPUT' | frun -j 8 printf \"%s\\n\"" \
  "$(cat "$LARGE_INPUT")"

LARGE_BYTE_INPUT="$TEST_DIR/large_byte.bin"
head -c 10000 /dev/zero | tr '\0' 'x' > "$LARGE_BYTE_INPUT"
run_test "Large byte input (10k) -b 1024" \
  "cat '$LARGE_BYTE_INPUT' | frun -b 1024 cat" \
  "$(cat "$LARGE_BYTE_INPUT")"

# ============================================================================
# DEPRECATED/ALIAS FLAGS
# ============================================================================

print_section "Alias Flags"

run_test "Alias: --atomic (buffered)" \
  "cat '$LINE_INPUT' | frun --atomic printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Alias: --keep-order" \
  "cat '$LINE_INPUT' | frun --keep-order printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

run_test "Alias: --unbuffered" \
  "cat '$LINE_INPUT' | frun --unbuffered printf \"%s\\n\"" \
  "$(cat "$LINE_INPUT")"

# ============================================================================
# DEEP ARCHITECTURE & INTERNAL ENGINE TESTS
# ============================================================================

print_section "Deep Architecture (Zero-Copy, Trickle, SIMD)"

run_test "Direct file ingest (Zero-Copy UMA)" \
  "frun printf \"%s\\n\" < '$LINE_INPUT'" \
  "$(cat "$LINE_INPUT")"

run_test "Direct file ingest (Zero-Copy NUMA)" \
  "frun --nodes=2 printf \"%s\\n\" < '$LINE_INPUT'" \
  "$(cat "$LINE_INPUT")"

run_test "Direct file ingest (Byte Mode)" \
  "frun -b 10 -s cat < '$BYTE_INPUT'" \
  "$(cat "$BYTE_INPUT")"

LONG_INPUT="$TEST_DIR/long.txt"
printf '%10000s\n' | tr ' ' 'A' > "$LONG_INPUT"
echo "short_line" >> "$LONG_INPUT"
run_test "AVX2/NEON SIMD long-line boundaries" \
  "frun -s cat < '$LONG_INPUT'" \
  "$(cat "$LONG_INPUT")"

run_test "Trickle input (Early Flush / Stall Meter)" \
  "{ echo 'trickle1'; sleep 0.2; echo 'trickle2'; } | frun -k -l 10 -s cat" \
  "trickle1
trickle2"

run_test "Command failure tolerance (No Deadlock)" \
  "cat '$LINE_INPUT' | frun 'false' >/dev/null; echo PIPELINE_SURVIVED" \
  "PIPELINE_SURVIVED"

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
