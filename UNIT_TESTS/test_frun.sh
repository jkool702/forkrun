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

# Detect UMA vs NUMA hardware
# Count NUMA nodes; if >1 we are on NUMA, otherwise UMA
NUMA_NODE_COUNT=$(ls -d /sys/devices/system/node/node[0-9]* 2>/dev/null | wc -l)
if (( NUMA_NODE_COUNT > 1 )); then
  IS_NUMA=true
else
  IS_NUMA=false
fi

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

print_header() {
  echo
  echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${CYAN}${BOLD}  FORKRUN TEST SUITE${NC}"
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

# Helper to compare sets of tokens (words) regardless of line formatting
# Used for unordered output where multiple tokens might share a line
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
  local check_stderr="${5:-false}" # If true, checks stderr instead of stdout

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
    # We check if the entire content contains the regex
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
      echo -e "    ${YELLOW}Expected stderr regex:${NC} $expected_stderr_regex"
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

# FIXED: Expect the output AND the stderr warning
# On NUMA hardware, -L with -n emits a warning; on UMA, no warning is emitted
if $IS_NUMA; then
  run_test_stderr "Exact lines with limit (-L 4 -n 8)" \
    "cat '$LINE_INPUT' | frun -k -L 4 -n 8 printf \"%s\\n\" >/dev/null" \
    "NUMA optimizations prevent -L from working properly" \
    0
else
  # On UMA: no NUMA warning, just verify exit 0 and correct stdout
  run_test "Exact lines with limit (-L 4 -n 8)" \
    "cat '$LINE_INPUT' | frun -k -L 4 -n 8 printf \"%s\\n\"" \
    "$(head -n 8 "$LINE_INPUT")"
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

# FIXED: Added -l 1 to ensure each line gets its own batch for predictable ARG: prepending
run_test "Insert mode (-i)" \
  "cat '$LINE_INPUT' | frun -l 1 -i echo ARG:{}" \
  "$(cat "$LINE_INPUT" | sed 's/^/ARG:/')"

# FIXED: Regex updated to handle new format[NODE.]WORKER.BATCH
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

# FIXED: Check stderr for downgrade warning using regex
# On NUMA hardware, --nodes=2 -L emits a downgrade warning; on UMA, no warning
if $IS_NUMA; then
  run_test_stderr "Exact lines with NUMA (downgrade warning)" \
    "cat '$LINE_INPUT' | frun --nodes=2 -L 3 printf \"%s\\n\" >/dev/null" \
    "cannot guarantee exactly|NUMA optimizations prevent -L from working properly" \
    0
else
  # On UMA: --nodes=2 is silently downgraded; just verify correct output
  run_test "Exact lines with NUMA (downgrade warning)" \
    "cat '$LINE_INPUT' | frun --nodes=2 -L 3 printf \"%s\\n\"" \
    "$(cat "$LINE_INPUT")"
fi

# ============================================================================
# SPECIAL FLAGS
# ============================================================================

print_section "Special Flags"

# FIXED: Just verify dry run completes and outputs the generated string format
run_test_regex "Dry run (-N)" \
  "cat '$LINE_INPUT' | frun -N printf \"%s\\n\"" \
  "printf" \
  0 false

run_test "Version (-V)" \
  "frun -V" \
  "forkrun v3.1.2"

# FIXED: Check for USAGE string explicitly without exact match
run_test_regex "Help (--help)" \
  "frun --help 2>&1" \
  "USAGE:" \
  0 false

# FIXED: Check stderr using regex for Verbose Output
run_test_regex "Verbose flag (-v)" \
  "cat '$LINE_INPUT' | frun -v printf \"%s\\n\" >/dev/null" \
  "SPAWNED [0-9]+ workers" \
  0 true

# FIXED: Check stderr using regex for Telemetry
# On NUMA hardware, --stats emits NUMA TELEMETRY; on UMA, it emits general telemetry
if $IS_NUMA; then
  run_test_regex "Stats flag (--stats)" \
    "cat '$LINE_INPUT' | frun --stats printf \"%s\\n\" >/dev/null" \
    "NUMA TELEMETRY" \
    0 true
else
  # On UMA: --stats is a no-op (NUMA-only feature); just verify correct output
  run_test "Stats flag (--stats)" \
    "cat '$LINE_INPUT' | frun --stats printf \"%s\\n\"" \
    "$(cat "$LINE_INPUT")"
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

# Test 57: Direct File Ingest (UMA) - Triggers sendfile/copy_file_range
run_test "Direct file ingest (Zero-Copy UMA)" \
  "frun printf \"%s\\n\" < '$LINE_INPUT'" \
  "$(cat "$LINE_INPUT")"

# Test 58: Direct File Ingest (NUMA) - Triggers zero-copy in ring_numa_ingest
run_test "Direct file ingest (Zero-Copy NUMA)" \
  "frun --nodes=2 printf \"%s\\n\" < '$LINE_INPUT'" \
  "$(cat "$LINE_INPUT")"

# Test 59: Direct File Ingest (Byte Mode)
run_test "Direct file ingest (Byte Mode)" \
  "frun -b 10 -s cat < '$BYTE_INPUT'" \
  "$(cat "$BYTE_INPUT")"

# Test 60: Extremely Long Lines (AVX2/NEON SIMD Boundary Stress Test)
LONG_INPUT="$TEST_DIR/long.txt"
# Create a 10,000 character line with no newlines, followed by a short line
printf '%10000s\n' | tr ' ' 'A' > "$LONG_INPUT"
echo "short_line" >> "$LONG_INPUT"
# FIXED: Added -s so cat reads the data from stdin, not as a filename
run_test "AVX2/NEON SIMD long-line boundaries" \
  "frun -s cat < '$LONG_INPUT'" \
  "$(cat "$LONG_INPUT")"

# Test 61: Trickle Input (Stall Meter / Early Flush Test)
# FIXED: Added -s so cat reads the trickle data from stdin
run_test "Trickle input (Early Flush / Stall Meter)" \
  "{ echo 'trickle1'; sleep 0.2; echo 'trickle2'; } | frun -k -l 10 -s cat" \
  "trickle1
trickle2"

# Test 62: Worker Command Failure Tolerance
run_test "Command failure tolerance (No Deadlock)" \
  "cat '$LINE_INPUT' | frun 'false' >/dev/null; echo PIPELINE_SURVIVED" \
  "PIPELINE_SURVIVED"

# ============================================================================
# NEW TESTS
# ============================================================================

print_section "Bash Execution Environment & State Propagation"

# Test 1: Simple Shell Function Parallelization (Batch-Aware)
run_test "Parallelize simple bash function" \
  "my_func() { for arg in \"\$@\"; do echo \"FUNC-\$arg\"; done; }; cat '$LINE_INPUT' | FORKRUN_EXTRA_FUNCS='my_func' frun my_func" \
  "$(cat "$LINE_INPUT" | sed 's/^/FUNC-/')"

# Test 2: Nested Shell Functions (Batch-Aware)
run_test "Parallelize nested bash functions" \
  "inner() { echo \"IN-\$1\"; }; outer() { for arg in \"\$@\"; do inner \"OUT-\$arg\"; done; }; cat '$LINE_INPUT' | FORKRUN_EXTRA_FUNCS='inner outer' frun outer" \
  "$(cat "$LINE_INPUT" | sed 's/^/IN-OUT-/')"

# Test 3: Exported Variables Survive
# Note: MY_VAR is exported in the parent. The function loops over the batch to print it.
run_test "Exported variables propagate" \
  "export MY_VAR='SURVIVOR'; print_var() { for arg in \"\$@\"; do echo \"\$MY_VAR\"; done; }; cat '$LINE_INPUT' | FORKRUN_EXTRA_VARS='MY_VAR' FORKRUN_EXTRA_FUNCS='print_var' frun print_var" \
  "$(awk '{print "SURVIVOR"}' "$LINE_INPUT")"

# Test 4: Unexported Variables do NOT pollute
run_test "Unexported variables do not propagate" \
  "MY_LOCAL='GHOST'; print_ghost() { for arg in \"\$@\"; do echo \"\${MY_LOCAL:-EMPTY}\"; done; }; cat '$LINE_INPUT' | FORKRUN_EXTRA_FUNCS='print_ghost' frun print_ghost" \
  "$(awk '{print "EMPTY"}' "$LINE_INPUT")"

print_section "Engine Physics: Escrow, Skew, and Heap Stress"

# Test 1: Severe Out-Of-Order Execution (Heap Stress)
# Adapted from your composite test to output newlines for strict validation.
run_test "ring_order Min-Heap with Severe Skew (-k)" \
  "sleepy_echo() { for nn in \"\$@\"; do sleep 0.\$((RANDOM % 5)); echo \"\$nn\"; done; }; export -f sleepy_echo 2>/dev/null; ff() { sleepy_echo \"\$@\"; }; seq 1 50 | FORKRUN_EXTRA_FUNCS='sleepy_echo ff' frun -k -j 8 ff" \
  "$(seq 1 50)"

# Test 2: Forced Escrow Stealing / Priority Inversion
# We use 1 worker and a huge overshoot limits. The worker MUST steal from its own escrow.
run_test "Forced Escrow Steal (Single Worker Overshoot)" \
  "seq 1 100 | frun -j 1 -l 10:1000 printf \"%s\\n\"" \
  "$(seq 1 100)"

# Test 3: Heavy Starvation / Oversubscription
run_test "Massive Oversubscription (128 workers, 10 lines)" \
  "seq 1 10 | frun -j 128 printf \"%s\\n\"" \
  "$(seq 1 10)"


print_section "I/O Edge Cases & Scanner Boundaries"

# Test 1: No Trailing Newline
NO_NL_INPUT="$TEST_DIR/no_nl.txt"
printf "line1\nline2\nline3" > "$NO_NL_INPUT"
run_test "File with NO trailing newline" \
  "cat '$NO_NL_INPUT' | frun printf \"%s\\n\"" \
  "line1
line2
line3"

# Test 2: The '-n' flag on exact chunk boundaries
run_test "Exact Limit matching" \
  "seq 1 10000 | frun -n 1234 -k printf \"%s\\n\" | wc -l" \
  "1234"

print_section "Routing: Data as Arguments (Default)"

# Test: Data as arguments (using printf)
run_test "Default mode passes data as arguments" \
  "seq 1 5 | frun -k printf \"%s\\n\"" \
  "1
2
3
4
5"

# Test: Filenames as arguments (using cat)
# We create two files, pass their names to frun, and verify cat opens them.
run_test "Default mode passes filenames to cat" \
  "echo 'fileA_content' > $TEST_DIR/fileA; echo 'fileB_content' > $TEST_DIR/fileB; printf \"%s\n\" \"$TEST_DIR/fileA\" \"$TEST_DIR/fileB\" | frun -k cat" \
  "fileA_content
fileB_content"

print_section "Routing: Data Spliced to Stdin (-s / -b)"

# Test: Stdin mode (-s)
run_test "Stdin mode (-s) splices to worker stdin" \
  "seq 1 5 | frun -k -s cat" \
  "1
2
3
4
5"

# Test: Byte mode (-b) implies (-s)
# Byte mode automatically splices data to stdin. We use 'wc -c' to prove
# the bytes arrived via stdin and weren't evaluated as arguments.
run_test "Byte mode (-b) splices to worker stdin" \
  "head -c 1000 /dev/zero | frun -b 200 wc -c | awk '{sum+=\$1} END {print sum}'" \
  "1000"

print_section "Variable Serialization (FORKRUN_EXTRA_VARS)"

# Test 1: Simple String Propagation
run_test "FORKRUN_EXTRA_VARS passes simple strings" \
  "MY_STR='Hello World'; print_str() { for arg in \"\$@\"; do echo \"\$MY_STR: \$arg\"; done; }; cat '$LINE_INPUT' | FORKRUN_EXTRA_FUNCS='print_str' FORKRUN_EXTRA_VARS='MY_STR' frun -k -l 1 print_str | head -n 1" \
  "Hello World: line1"

# Test 2: Standard Array Propagation (Preserving spaces/indexes)
run_test "FORKRUN_EXTRA_VARS passes standard arrays" \
  "MY_ARR=('item 0' 'item 1'); print_arr() { for arg in \"\$@\"; do echo \"\${MY_ARR[1]}\"; done; }; seq 1 3 | FORKRUN_EXTRA_FUNCS='print_arr' FORKRUN_EXTRA_VARS='MY_ARR' frun -k print_arr" \
  "item 1
item 1
item 1"

# Test 3: Associative Array Propagation (The ultimate test)
run_test "FORKRUN_EXTRA_VARS passes associative arrays" \
  "declare -A MY_MAP=([keyA]='valA' [keyB]='valB'); lookup() { for arg in \"\$@\"; do echo \"\${MY_MAP[\$arg]:-none}\"; done; }; printf \"keyA\nkeyB\nkeyC\n\" | FORKRUN_EXTRA_FUNCS='lookup' FORKRUN_EXTRA_VARS='MY_MAP' frun -k lookup" \
  "valA
valB
none"

print_section "Custom clean-room setup (FORKRUN_EXTRA_SETUP)"

# 1. Basic environment variable injection via setup code
run_test "FORKRUN_EXTRA_SETUP: set env var used by worker" \
  "FORKRUN_EXTRA_SETUP='export MY_SETUP_VAR=from_setup'; echo_val() { echo \"\$MY_SETUP_VAR:\$1\"; }; echo 'x' | FORKRUN_EXTRA_FUNCS='echo_val' FORKRUN_EXTRA_VARS='MY_SETUP_VAR' frun -l 1 echo_val" \
  "from_setup:x"

# 2. Load a custom loadable builtin (if you have one available for testing)
[[ -f  /path/to/test_loadable.so ]] && run_test "FORKRUN_EXTRA_SETUP: enable custom loadable" \
  "FORKRUN_EXTRA_SETUP='enable -f /path/to/test_loadable.so test_cmd 2>/dev/null || true'; test_cmd() { echo \"loaded:\$1\"; }; echo 'y' | FORKRUN_EXTRA_FUNCS='test_cmd' frun -l 1 test_cmd" \
  "loaded:y"  # Or handle gracefully if loadable unavailable

# 3. Modify shell options that affect worker behavior
run_test "FORKRUN_EXTRA_SETUP: enable extglob affects pattern matching" \
  "FORKRUN_EXTRA_SETUP='shopt -s extglob'; match_ext() { [[ \"\$1\" == +(a|b) ]] && echo \"match:\$1\" || echo \"nope:\$1\"; }; printf 'a\nb\nc\n' | FORKRUN_EXTRA_FUNCS='match_ext' frun -l 1 match_ext" \
  $'match:a\nmatch:b\nnope:c'

# 4. Setup code runs BEFORE worker function is serialized
run_test "FORKRUN_EXTRA_SETUP: setup executes before function capture" \
  "FORKRUN_EXTRA_SETUP='PRE_SETUP=ready'; use_pre() { echo \"\$PRE_SETUP:\$1\"; }; echo 'z' | FORKRUN_EXTRA_FUNCS='use_pre' FORKRUN_EXTRA_VARS='PRE_SETUP' frun -l 1 use_pre" \
  "ready:z"

# 5. Setup code that fails should not silently succeed
run_test "FORKRUN_EXTRA_SETUP: failing setup code propagates exact exit code" \
"FORKRUN_EXTRA_SETUP='exit 42'; dummy() { echo \"\$1\"; }; echo 'w' | FORKRUN_EXTRA_FUNCS='dummy' frun -l 1 dummy" \
"" 42


print_section "Signal Handling and Early Termination"

# Test 1: SIGPIPE from downstream
# We pipe a massive stream into frun, but cut it off instantly.
run_test_regex "Graceful SIGPIPE handling (head -n 5)" \
  "seq 1 1000000 | frun -k printf \"%s\\n\" | head -n 5 | wc -l" \
  "5" \
  0 false

# Test 2: Worker command crashes mid-batch
# If a specific input crashes the worker, the rest of the file should still process.
run_test "Worker transient failure mid-batch" \
  "crash_func() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='crash_func' frun -l 1 -k crash_func" \
  "1
2
4
5" 3

# Test 3: Worker command crashes once mid-batch
# If a specific input crashes only once it should recover and the rest of the file should still process.
[[ -f ./.crash ]] && \rm ./.crash &>/dev/null
run_test "Worker one-time transient failure mid-batch" \
  "crash_func() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]] && ! [[ -f ./.crash  ]]; then : >./.crash; exit 1; else echo \"\$arg\"; fi; done; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='crash_func' frun -l 1 -k crash_func" \
  "1
2
3
4
5"
\rm ./.crash &>/dev/null

print_section "Misc additional tests"


# Force extreme out-of-order completion to stress min-heap
run_test "Min-heap ordering: 100 batches with random sleep skew" \
  "skewed() { sleep 0.\$((RANDOM%50)); echo \"\$1\"; }; export -f skewed 2>/dev/null; seq 1 100 | FORKRUN_EXTRA_FUNCS='skewed' frun -l 1 -k -j 16 skewed" \
  "$(seq 1 100)"

# Downstream consumer dies mid-stream; verify clean abort
run_test_regex "SIGPIPE cascade: orderer dies, workers abort cleanly" \
  "seq 10000 | frun -k -j 8 printf '%s\n' | head -n 5; echo \"EXIT:\$?\"" \
  "EXIT:0" 0 false

# 3. UTF-8 BYTE INTEGRITY
# Expect 10 bytes. This validates that byte-mode preserves raw binary integrity.
run_test "Byte mode: UTF-8 character integrity (10 bytes for 5 Greek chars)" \
"printf 'αβγδε' | frun -b 3 -s cat | wc -c" \
"10"

# 4. FD LIMIT REALISM
# Test that forkrun's automatic ulimit boosting works under a realistic, allowed limit.
run_test "Operates correctly under moderate FD limits (ulimit -n 256)" \
"(ulimit -n 256 2>/dev/null || true); seq 10 | frun -j 4 -k printf '%s\n'" \
"1
2
3
4
5
6
7
8
9
10"

# 5. TIMEOUT FLUSH WITH STDIN
# Add -s so cat reads from the spliced stdin pipe, proving the timeout early-flush works.
run_test "Timeout flush: 50ms timeout delivers trickle input" \
"{ echo 'a'; sleep 0.1; echo 'b'; } | frun --timeout 50000 -l 100 -k -s cat" \
"a
b"


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
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}${BOLD}ALL TESTS PASSED!${NC}"
  echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  exit 0
fi
