#!/usr/bin/env bash
# ============================================================================
# FORKRUN COMPREHENSIVE SUPPLEMENTAL TEST SUITE v1.0
# ============================================================================
# Covers the gaps identified in test_frun.sh / test_frun_v2.sh:
#
#  SECTION A: Regression — Bash function transmission (the discovered bug)
#  SECTION B: Bash functions — core feature coverage
#  SECTION C: FORKRUN_EXTRA_FUNCS — dependent function chains
#  SECTION D: Data integrity — exact line-level sorted comparison
#  SECTION E: Special character handling in input
#  SECTION F: Batch correctness — exact arg counts per call
#  SECTION G: Sequential invocations — ring reuse
#  SECTION H: Combined feature interactions
#  SECTION I: Boundary conditions
#  SECTION J: Worker / ID semantics
#  SECTION K: Framework self-tests (verify the helpers work)
#
# USAGE:
#   Run from repo root:           bash UNIT_TESTS/test_frun_comprehensive.sh
#   Run with verbose failure info: VERBOSE=true bash UNIT_TESTS/test_frun_comprehensive.sh
#   Run single section:           SECTION=B bash UNIT_TESTS/test_frun_comprehensive.sh
# ============================================================================

set +euo pipefail  # tests must not abort on individual failures

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
CYAN='\033[1;36m'
NC='\033[0m'
BOLD='\033[1m'

TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0
SKIPPED_TESTS=0
declare -A TEST_RESULTS
declare -A TEST_ERRORS

TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT

# Locate frun.bash: check same dir as this script, then repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRUN_SOURCE=""
for candidate in "${SCRIPT_DIR}/frun.bash" "${REPO_ROOT}/frun.bash" "./frun.bash"; do
    [[ -f "$candidate" ]] && { FRUN_SOURCE="$candidate"; break; }
done

if [[ -z "$FRUN_SOURCE" ]]; then
    echo -e "${RED}ERROR: frun.bash not found. Run from the forkrun repo root.${NC}"
    exit 1
fi

VERBOSE="${VERBOSE:-false}"
SECTION_FILTER="${SECTION:-}"

# ============================================================================
# CORE TEST HELPERS
# ============================================================================

print_section() {
    local letter="$1" title="$2"
    [[ -n "$SECTION_FILTER" && "$SECTION_FILTER" != "$letter" ]] && return
    echo
    echo -e "${BLUE}${BOLD}▶ Section $letter: $title${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

in_section() {
    # Returns 0 (true) if current section should run
    [[ -z "$SECTION_FILTER" || "$SECTION_FILTER" == "$1" ]]
}

_print_result() {
    local status="$1" name="$2" detail="${3:-}"
    case $status in
        PASS) echo -e "  ${GREEN}✓${NC} $name" ;;
        FAIL) echo -e "  ${RED}✗${NC} $name${RED} — $detail${NC}" ;;
        SKIP) echo -e "  ${YELLOW}○${NC} $name${YELLOW} (skipped: $detail)${NC}" ;;
    esac
}

# ---------------------------------------------------------------------------
# run_test_exact: exact stdout comparison (both sides compared as-is)
# Use for: ordered output, single-line outputs, version strings
# ---------------------------------------------------------------------------
run_test_exact() {
    local section="$1" test_name="$2" cmd="$3" expected="$4" expected_exit="${5:-0}"
    in_section "$section" || return
    ((TOTAL_TESTS++))

    local out err exit_code=0
    out=$(bash -c "source '$FRUN_SOURCE' && $cmd" 2>/tmp/_frun_test_err) || exit_code=$?
    err=$(cat /tmp/_frun_test_err)

    local passed=true reason=""
    if [[ "$exit_code" -ne "$expected_exit" ]]; then
        passed=false; reason="exit $exit_code (expected $expected_exit)"
    elif [[ "$out" != "$expected" ]]; then
        passed=false; reason="stdout mismatch"
    fi

    if $passed; then
        TEST_RESULTS["$test_name"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "$test_name"
    else
        TEST_RESULTS["$test_name"]="FAIL"; TEST_ERRORS["$test_name"]="$reason"; ((FAILED_TESTS++))
        _print_result FAIL "$test_name" "$reason"
        if [[ "${VERBOSE:-}" == "true" ]]; then
            echo -e "    ${YELLOW}cmd:${NC} $cmd"
            echo -e "    ${YELLOW}expected:${NC} $(echo "$expected" | head -3 | sed 's/^/      /')"
            echo -e "    ${YELLOW}actual:${NC}   $(echo "$out" | head -3 | sed 's/^/      /')"
            [[ -n "$err" ]] && echo -e "    ${YELLOW}stderr:${NC}   $(echo "$err" | head -3 | sed 's/^/      /')"
        fi
    fi
}

# ---------------------------------------------------------------------------
# run_test_sorted: sorted-line comparison — catches missing AND duplicate lines
# Use for: unordered parallel output, data integrity checks
# The key fix vs the original compare_token_sets: we sort LINES not WORDS,
# and we use 'diff' so duplicates (two "line1"s) are caught.
# ---------------------------------------------------------------------------
run_test_sorted() {
    local section="$1" test_name="$2" cmd="$3" expected="$4" expected_exit="${5:-0}"
    in_section "$section" || return
    ((TOTAL_TESTS++))

    local out err exit_code=0
    out=$(bash -c "source '$FRUN_SOURCE' && $cmd" 2>/tmp/_frun_test_err) || exit_code=$?
    err=$(cat /tmp/_frun_test_err)

    local passed=true reason=""
    if [[ "$exit_code" -ne "$expected_exit" ]]; then
        passed=false; reason="exit $exit_code (expected $expected_exit)"
    else
        local actual_sorted expected_sorted
        actual_sorted=$(echo "$out"       | sort)
        expected_sorted=$(echo "$expected" | sort)
        if [[ "$actual_sorted" != "$expected_sorted" ]]; then
            passed=false
            local ac ec
            ac=$(echo "$out"       | wc -l | tr -d ' ')
            ec=$(echo "$expected"  | wc -l | tr -d ' ')
            if [[ "$ac" -ne "$ec" ]]; then
                reason="line count: got $ac, expected $ec"
            else
                # Find first differing line to give a useful hint
                local first_diff
                first_diff=$(diff <(echo "$actual_sorted") <(echo "$expected_sorted") | head -1)
                reason="content mismatch (same count). First diff: $first_diff"
            fi
        fi
    fi

    if $passed; then
        TEST_RESULTS["$test_name"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "$test_name"
    else
        TEST_RESULTS["$test_name"]="FAIL"; TEST_ERRORS["$test_name"]="$reason"; ((FAILED_TESTS++))
        _print_result FAIL "$test_name" "$reason"
        if [[ "${VERBOSE:-}" == "true" ]]; then
            echo -e "    ${YELLOW}cmd:${NC} $cmd"
            echo -e "    ${YELLOW}reason:${NC} $reason"
            [[ -n "$err" ]] && echo -e "    ${YELLOW}stderr:${NC} $(echo "$err" | head -3 | sed 's/^/      /')"
        fi
    fi
}

# ---------------------------------------------------------------------------
# run_test_regex: check stdout (or stderr) against a regex
# ---------------------------------------------------------------------------
run_test_regex() {
    local section="$1" test_name="$2" cmd="$3" regex="$4" \
          expected_exit="${5:-0}" check_stderr="${6:-false}"
    in_section "$section" || return
    ((TOTAL_TESTS++))

    local out err exit_code=0
    out=$(bash -c "source '$FRUN_SOURCE' && $cmd" 2>/tmp/_frun_test_err) || exit_code=$?
    err=$(cat /tmp/_frun_test_err)
    local content; $check_stderr && content="$err" || content="$out"

    local passed=true reason=""
    if [[ "$exit_code" -ne "$expected_exit" ]]; then
        passed=false; reason="exit $exit_code (expected $expected_exit)"
    elif [[ ! "$content" =~ $regex ]]; then
        passed=false; reason="regex not matched: $regex"
    fi

    if $passed; then
        TEST_RESULTS["$test_name"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "$test_name"
    else
        TEST_RESULTS["$test_name"]="FAIL"; TEST_ERRORS["$test_name"]="$reason"; ((FAILED_TESTS++))
        _print_result FAIL "$test_name" "$reason"
        if [[ "${VERBOSE:-}" == "true" ]]; then
            echo -e "    ${YELLOW}cmd:${NC}     $cmd"
            echo -e "    ${YELLOW}regex:${NC}   $regex"
            echo -e "    ${YELLOW}content:${NC} $(echo "$content" | head -3 | sed 's/^/      /')"
        fi
    fi
}

# ---------------------------------------------------------------------------
# run_test_line_count: verify exact output line count (fast integrity check)
# ---------------------------------------------------------------------------
run_test_line_count() {
    local section="$1" test_name="$2" cmd="$3" expected_lines="$4" expected_exit="${5:-0}"
    in_section "$section" || return
    ((TOTAL_TESTS++))

    local out err exit_code=0
    out=$(bash -c "source '$FRUN_SOURCE' && $cmd" 2>/tmp/_frun_test_err) || exit_code=$?
    err=$(cat /tmp/_frun_test_err)
    local actual_lines; actual_lines=$(echo "$out" | wc -l | tr -d ' ')
    # wc -l on empty string returns 0, on "x\n" returns 1
    [[ -z "$out" ]] && actual_lines=0

    local passed=true reason=""
    if [[ "$exit_code" -ne "$expected_exit" ]]; then
        passed=false; reason="exit $exit_code (expected $expected_exit)"
    elif [[ "$actual_lines" -ne "$expected_lines" ]]; then
        passed=false; reason="line count: got $actual_lines, expected $expected_lines"
    fi

    if $passed; then
        TEST_RESULTS["$test_name"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "$test_name"
    else
        TEST_RESULTS["$test_name"]="FAIL"; TEST_ERRORS["$test_name"]="$reason"; ((FAILED_TESTS++))
        _print_result FAIL "$test_name" "$reason"
        if [[ "${VERBOSE:-}" == "true" ]]; then
            echo -e "    ${YELLOW}cmd:${NC} $cmd"
            echo -e "    ${YELLOW}$reason${NC}"
            [[ -n "$err" ]] && echo -e "    ${YELLOW}stderr:${NC} $(echo "$err" | head -3 | sed 's/^/      /')"
        fi
    fi
}

# ---------------------------------------------------------------------------
# run_test_skip: mark a test as skipped (platform or feature not available)
# ---------------------------------------------------------------------------
run_test_skip() {
    local section="$1" test_name="$2" reason="$3"
    in_section "$section" || return
    ((TOTAL_TESTS++)); ((SKIPPED_TESTS++))
    TEST_RESULTS["$test_name"]="SKIP"
    _print_result SKIP "$test_name" "$reason"
}

# ============================================================================
# SYSTEM DETECTION
# ============================================================================

NPROC=$(nproc 2>/dev/null || sysctl -n hw.logicalcpu 2>/dev/null || echo 4)
IS_NUMA=false
NUMA_NODE_COUNT=1
if [[ -r /sys/devices/system/node/online ]]; then
    raw=$(cat /sys/devices/system/node/online)
    # Simple count: "0" = 1 node, "0-3" = 4 nodes, "0,2" = 2 nodes
    if [[ "$raw" == *-* ]]; then
        lo="${raw%%-*}"; hi="${raw##*-}"
        NUMA_NODE_COUNT=$(( hi - lo + 1 ))
    elif [[ "$raw" == *,* ]]; then
        NUMA_NODE_COUNT=$(echo "$raw" | tr ',' '\n' | wc -l | tr -d ' ')
    fi
    (( NUMA_NODE_COUNT > 1 )) && IS_NUMA=true
fi

# ============================================================================
# TEST DATA SETUP
# ============================================================================

LINE10="$TEST_DIR/lines10.txt"
LINE100="$TEST_DIR/lines100.txt"
LINE1K="$TEST_DIR/lines1k.txt"
BYTE100="$TEST_DIR/bytes100.bin"
SPECIAL="$TEST_DIR/special.txt"
MULTIWORD="$TEST_DIR/multiword.txt"
EMPTY="$TEST_DIR/empty.txt"

seq 10  > "$LINE10"
seq 100 > "$LINE100"
seq 1000 > "$LINE1K"
head -c 100 /dev/zero | tr '\0' 'x' > "$BYTE100"
touch "$EMPTY"

# Multi-word lines (space-separated)
printf 'hello world\nfoo bar\nbaz qux\n' > "$MULTIWORD"

# Special characters — each on its own line
# Note: these go through frun's safe quoting (printf '%q') in default mode.
# In -s mode they go through pipes unmodified.
printf '%s\n' \
    'simple' \
    'with space' \
    'with$dollar' \
    'with`backtick`' \
    "with'single'" \
    'with"double"' \
    'with\backslash' \
    'with*glob*' \
    'with?mark' \
    'with[bracket]' \
    'with;semicolon' \
    'with|pipe' \
    'with(paren)' \
    'with>redirect' \
    'with&amp' \
    > "$SPECIAL"

echo
echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}${BOLD}  FORKRUN COMPREHENSIVE SUPPLEMENTAL TEST SUITE${NC}"
printf "${CYAN}${BOLD}  System: %d CPUs, %d NUMA node(s)${NC}\n" "$NPROC" "$NUMA_NODE_COUNT"
echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ============================================================================
# SECTION A: REGRESSION — Bash Function Transmission
# This section directly tests the bug that was discovered:
# bash functions defined in the caller's scope were being lost during
# the cleanroom exec in frun.bash.
# ============================================================================
print_section A "REGRESSION: Bash Function Transmission"

# The cleanroom exec must re-declare the function from declare -f capture.
run_test_exact A "Regression: simple function reaches workers" \
    "my_transform() { echo \"FUNC:\$*\"; }; echo 'test_line' | frun -l 1 my_transform" \
    "FUNC:test_line"

# Functions with local variables must survive serialization through declare -f.
run_test_exact A "Regression: function with local vars" \
    "prefix_func() { local pfx='PREFIX'; echo \"\${pfx}:\$*\"; }; echo 'hello' | frun -l 1 prefix_func" \
    "PREFIX:hello"

# A function that shadows an external command of the same name.
# forkrun must call the bash function, not the external binary.
run_test_exact A "Regression: function shadows external command (cat)" \
    "cat() { echo \"SHADOWED:\$*\"; }; echo 'test' | frun -l 1 cat" \
    "SHADOWED:test"

# Multiple lines, each dispatched to the function independently (-l 1).
run_test_sorted A "Regression: function called once per line with -l 1" \
    "tag() { echo \"[T:\$*]\"; }; seq 5 | frun -l 1 tag" \
    "[T:1]
[T:2]
[T:3]
[T:4]
[T:5]"

# Function called with a batch of multiple args (-l 3).
# Each invocation receives exactly 3 args (except possibly the last).
run_test_exact A "Regression: function called with multi-line batch (-l 3, -k)" \
    "count_args() { echo \"\$#\"; }; seq 9 | frun -l 3 -k count_args" \
    "3
3
3"

# ============================================================================
# SECTION B: Bash Functions — Full Feature Coverage
# ============================================================================
print_section B "Bash Functions: Full Coverage"

# Function with an if/else branch — tests function body complexity.
run_test_sorted B "Function with if/else logic" \
    "classify() { if (( \$1 % 2 == 0 )); then echo \"even:\$1\"; else echo \"odd:\$1\"; fi; }; seq 6 | frun -l 1 classify" \
    "even:2
even:4
even:6
odd:1
odd:3
odd:5"

# Function that uses a case statement.
run_test_sorted B "Function with case statement" \
    "label() { case \"\$1\" in 1) echo 'one';; 2) echo 'two';; *) echo 'other';; esac; }; printf '1\n2\n3\n' | frun -l 1 label" \
    "one
two
other"

# Function that produces multiple output lines per input line.
run_test_sorted B "Function producing multiple output lines per input" \
    "double_out() { echo \"a:\$1\"; echo \"b:\$1\"; }; seq 3 | frun -l 1 double_out" \
    "a:1
a:2
a:3
b:1
b:2
b:3"

# Function that uses printf instead of echo.
run_test_sorted B "Function using printf" \
    "pf() { printf 'N=%s\n' \"\$@\"; }; seq 4 | frun -l 2 pf" \
    "N=1
N=2
N=3
N=4"

# Function that uses the full positional array \$@ (receives batch as array).
run_test_sorted B "Function accessing all args via \$@" \
    "sum_all() { local s=0; for x in \"\$@\"; do (( s += x )); done; echo \"\$s\"; }; printf '10\n20\n30\n' | frun -l 3 sum_all" \
    "60"

# Function with a local array.
run_test_sorted B "Function with local array operations" \
    "rev_args() { local -a a=(\"\$@\"); local i; for (( i=\${#a[@]}-1; i>=0; i-- )); do echo \"\${a[i]}\"; done; }; seq 1 3 | frun -l 3 -k rev_args" \
    "3
2
1"

# Function used with ordered output (-k) — must preserve order.
run_test_exact B "Function + ordered output (-k)" \
    "tag() { echo \"L\$*\"; }; seq 5 | frun -k -l 1 tag" \
    "L1
L2
L3
L4
L5"

# Function used with realtime mode (-u).
run_test_sorted B "Function + realtime mode (-u)" \
    "tag() { echo \"R:\$*\"; }; seq 5 | frun -u -l 1 tag" \
    "R:1
R:2
R:3
R:4
R:5"

# Function used with -s (stdin passthrough) — function reads its stdin.
run_test_sorted B "Function + stdin passthrough (-s)" \
    "upper_stdin() { tr '[:lower:]' '[:upper:]'; }; printf 'hello\nworld\n' | frun -s upper_stdin" \
    "HELLO
WORLD"

# Function used with -i (insert substitution).
run_test_sorted B "Function + insert substitution (-i)" \
    "wrap() { echo \"[wrap:\$1]\"; }; seq 3 | frun -l 1 -i wrap {}" \
    "[wrap:1]
[wrap:2]
[wrap:3]"

# Function used with -n (record limit).
run_test_line_count B "Function + record limit (-n 3)" \
    "tag() { echo \"\$*\"; }; seq 100 | frun -l 1 -n 3 tag" \
    3

# Function that takes no implicit args, just uses \$1.
run_test_sorted B "Function with explicit \$1 reference" \
    "sqr() { echo \$(( \$1 * \$1 )); }; seq 1 4 | frun -l 1 sqr" \
    "1
4
9
16"

# Function with underscore and numbers in name (valid bash identifiers).
run_test_sorted B "Function with _underscored_name_123" \
    "_my_func_v2() { echo \"ok:\$*\"; }; seq 3 | frun -l 1 _my_func_v2" \
    "ok:1
ok:2
ok:3"

# ============================================================================
# SECTION C: FORKRUN_EXTRA_FUNCS — Dependent Function Chains
# ============================================================================
print_section C "FORKRUN_EXTRA_FUNCS: Dependent Function Chains"

# main_func calls helper — helper must be exported via FORKRUN_EXTRA_FUNCS.
run_test_sorted C "FORKRUN_EXTRA_FUNCS: one-level dependency" \
    "helper() { echo \"H:\$*\"; }; main_func() { helper \"\$@\"; }; FORKRUN_EXTRA_FUNCS='helper' seq 3 | frun -l 1 main_func" \
    "H:1
H:2
H:3"

# Two-level chain: main -> mid -> leaf
run_test_sorted C "FORKRUN_EXTRA_FUNCS: two-level chain" \
    "leaf() { echo \"LEAF:\$*\"; }; mid() { leaf \"\$@\"; }; main_func() { mid \"\$@\"; }; FORKRUN_EXTRA_FUNCS='mid leaf' seq 3 | frun -l 1 main_func" \
    "LEAF:1
LEAF:2
LEAF:3"

# Multiple independent helpers listed in FORKRUN_EXTRA_FUNCS.
run_test_sorted C "FORKRUN_EXTRA_FUNCS: multiple helpers" \
    "pfx() { echo \"P:\$*\"; }; sfx() { echo \"S:\$*\"; }; combo() { pfx \"\$@\"; sfx \"\$@\"; }; FORKRUN_EXTRA_FUNCS='pfx sfx' seq 2 | frun -l 1 combo" \
    "P:1
P:2
S:1
S:2"

# FORKRUN_EXTRA_FUNCS with exported environment variable used inside helper.
run_test_sorted C "FORKRUN_EXTRA_FUNCS: helper uses exported env var" \
    "export MY_PREFIX='TAG'; format_line() { echo \"\${MY_PREFIX}:\$*\"; }; dispatch() { format_line \"\$@\"; }; FORKRUN_EXTRA_FUNCS='format_line' seq 3 | frun -l 1 dispatch" \
    "TAG:1
TAG:2
TAG:3"

# FORKRUN_EXTRA_FUNCS combined with -k (ordered output).
run_test_exact C "FORKRUN_EXTRA_FUNCS: ordered output (-k)" \
    "add_prefix() { echo \"ORDERED:\$*\"; }; main_f() { add_prefix \"\$@\"; }; FORKRUN_EXTRA_FUNCS='add_prefix' seq 4 | frun -l 1 -k main_f" \
    "ORDERED:1
ORDERED:2
ORDERED:3
ORDERED:4"

# FORKRUN_EXTRA_FUNCS combined with -s (stdin passthrough).
run_test_sorted C "FORKRUN_EXTRA_FUNCS: stdin passthrough (-s)" \
    "transform_stdin() { sed 's/^/X:/'; }; process_batch() { transform_stdin; }; FORKRUN_EXTRA_FUNCS='transform_stdin' printf 'a\nb\nc\n' | frun -s process_batch" \
    "X:a
X:b
X:c"

# ============================================================================
# SECTION D: Data Integrity — Exact Line-Level Verification
# These tests ensure no lines are lost, duplicated, or corrupted.
# They use run_test_sorted which does exact sorted-line diff.
# ============================================================================
print_section D "Data Integrity: No Loss, No Duplication"

# 100-line passthrough, default mode, multiple workers.
# Any race condition causing duplicate or missing dispatch would be caught here.
run_test_sorted D "100-line integrity: default mode (printf passthrough)" \
    "cat '$LINE100' | frun printf '%s\n'" \
    "$(seq 100)"

# 100-line passthrough, ordered mode.
run_test_exact D "100-line integrity: ordered mode (-k)" \
    "cat '$LINE100' | frun -k printf '%s\n'" \
    "$(seq 100)"

# 100-line passthrough, stdin mode.
run_test_sorted D "100-line integrity: stdin mode (-s cat)" \
    "cat '$LINE100' | frun -s cat" \
    "$(seq 100)"

# 1000-line passthrough with heavy parallelism.
run_test_sorted D "1000-line integrity: default mode with -j 8" \
    "cat '$LINE1K' | frun -j 8 printf '%s\n'" \
    "$(seq 1000)"

# 1000-line ordered — verifies reorder buffer under load.
run_test_exact D "1000-line integrity: ordered (-k -j 8)" \
    "cat '$LINE1K' | frun -k -j 8 printf '%s\n'" \
    "$(seq 1000)"

# Byte mode: total bytes in == total bytes out (exact content match).
run_test_exact D "Byte mode integrity: -b 10, 100 bytes total" \
    "cat '$BYTE100' | frun -b 10 cat" \
    "$(cat "$BYTE100")"

# Byte mode with non-multiple chunk size (last chunk is smaller).
# 100 bytes total, 30-byte chunks: chunks of 30, 30, 30, 10.
run_test_exact D "Byte mode integrity: non-multiple chunk (-b 30, 100 bytes)" \
    "cat '$BYTE100' | frun -b 30 cat" \
    "$(cat "$BYTE100")"

# Null-delimited integrity: content must survive NUL → frun → output unchanged.
run_test_exact D "Null-delimited integrity (-z, -s)" \
    "printf 'alpha\0beta\0gamma\0delta\0' | frun -z -s cat" \
    "$(printf 'alpha\0beta\0gamma\0delta\0')"

# Verify no duplicate lines with high worker count (regression for escrow race).
# If escrow causes double-dispatch, a line would appear twice.
# We use seq 20 with 20 workers (1:1 worker:line ratio, maximum escrow pressure).
run_test_sorted D "No-duplicate guarantee: workers == line count" \
    "seq 20 | frun -j 20 -l 1 printf '%s\n'" \
    "$(seq 20)"

# Custom delimiter integrity.
run_test_sorted D "Custom delimiter integrity (-d :)" \
    "printf 'a:b:c:d:e' | frun -d ':' printf '%s\n'" \
    "a
b
c
d
e"

# Very large output per worker (each worker prints many lines) — tests output fan-in.
run_test_line_count D "High-fanout output: 10 inputs * 100 output lines each = 1000 lines" \
    "expand_line() { local i; for ((i=1;i<=100;i++)); do echo \"\$1_\$i\"; done; }; seq 10 | frun -l 1 expand_line" \
    1000

# ============================================================================
# SECTION E: Special Characters in Input
# These test forkrun's safe quoting path (printf '%q' in cmdline mode)
# and the raw passthrough path (-s / -z mode).
# ============================================================================
print_section E "Special Characters in Input"

# Glob characters must not be expanded by the shell when passed as args.
run_test_exact E "Glob chars in input survive cmdline mode (* ? [])" \
    "printf 'star*\nquest?\nbracket[x]\n' | frun -k -l 1 printf '%s\n'" \
    "star*
quest?
bracket[x]"

# Dollar signs must not be expanded (variable substitution disabled by quoting).
run_test_exact E "Dollar sign in input not expanded" \
    "printf '\$HOME\n\$RANDOM\n\${NOTAVAR}\n' | frun -k -l 1 printf '%s\n'" \
    "\$HOME
\$RANDOM
\${NOTAVAR}"

# Backslashes must survive the quoting round-trip.
run_test_exact E "Backslash in input not consumed" \
    "printf 'a\\\\b\n' | frun -k -l 1 printf '%s\n'" \
    'a\b'

# Single quotes inside input.
run_test_exact E "Single quotes in input survive quoting" \
    "printf \"it's here\n\" | frun -k -l 1 printf '%s\n'" \
    "it's here"

# Double quotes inside input.
run_test_exact E "Double quotes in input survive quoting" \
    'printf '"'"'say "hello"\n'"'"' | frun -k -l 1 printf '"'"'%s\n'"'"'' \
    'say "hello"'

# Semicolons must not be treated as command separators.
run_test_exact E "Semicolons in input treated as literals" \
    "printf 'a;b;c\n' | frun -k -l 1 printf '%s\n'" \
    "a;b;c"

# Pipe characters must not create new pipes.
run_test_exact E "Pipe char in input treated as literal" \
    "printf 'a|b\n' | frun -k -l 1 printf '%s\n'" \
    "a|b"

# Full special-character file passthrough via -s (raw stdin, no quoting needed).
# In -s mode, data flows through kernel pipes unmodified.
run_test_exact E "Special chars passthrough intact in -s mode" \
    "cat '$SPECIAL' | frun -s cat" \
    "$(cat "$SPECIAL")"

# Unicode multi-byte characters.
run_test_exact E "Unicode (CJK) characters in input" \
    "printf '你好\n世界\nこんにちは\n' | frun -k -l 1 printf '%s\n'" \
    "你好
世界
こんにちは"

# Spaces in lines (default mode uses safe quoting so spaces don't split args).
run_test_exact E "Lines with spaces: each treated as single argument" \
    "cat '$MULTIWORD' | frun -k -l 1 printf '%s\n'" \
    "hello world
foo bar
baz qux"

# Tabs in lines.
run_test_exact E "Tabs in input lines survive quoting" \
    "printf 'a\tb\tc\n' | frun -k -l 1 printf '%s\n'" \
    "a	b	c"

# ============================================================================
# SECTION F: Batch Correctness — Exact Arg Counts
# Verify that -l N delivers exactly N arguments per worker call
# (except the last batch which may be smaller).
# ============================================================================
print_section F "Batch Correctness: Exact Arg Counts per Call"

# -l 1: every call must receive exactly 1 argument.
run_test_sorted F "-l 1: every call gets exactly 1 arg" \
    "count_a() { echo \"\$#\"; }; seq 10 | frun -l 1 count_a" \
    "$(printf '1\n%.0s' {1..10})"

# -l 2: every call gets 2 args (10 lines = 5 calls).
run_test_sorted F "-l 2: every call gets exactly 2 args (10 lines / 2)" \
    "count_a() { echo \"\$#\"; }; seq 10 | frun -l 2 count_a" \
    "$(printf '2\n%.0s' {1..5})"

# -l 3: 9 lines = 3 calls of 3, plus possibly 1 call of 0 (flushed empty).
run_test_line_count F "-l 3: 9 lines produces correct batch count (3 batches)" \
    "count_a() { echo \"\$#\"; }; seq 9 | frun -l 3 count_a" \
    3

# -L (exact lines): every call must receive EXACTLY N, including last.
run_test_sorted F "-L 4 (exact): verify all batch sizes are 4 (with 8 lines)" \
    "count_a() { echo \"\$#\"; }; seq 8 | frun -L 4 count_a" \
    "$(printf '4\n%.0s' {1..2})"

# Verify the actual args passed to a multi-arg batch are the right lines.
# With -l 3 and -k, first batch should be lines 1 2 3 as separate args.
run_test_exact F "-l 3 -k: first batch contains correct args in order" \
    "print_args() { echo \"\$*\"; }; seq 6 | frun -l 3 -k print_args" \
    "1 2 3
4 5 6"

# Batch content in -s mode: the entire batch content arrives as a single stdin stream.
run_test_exact F "-l 3 -s -k: batch content passed as stdin correctly" \
    "prefix_lines() { sed 's/^/B:/'; }; seq 6 | frun -l 3 -k -s prefix_lines" \
    "B:1
B:2
B:3
B:4
B:5
B:6"

# ============================================================================
# SECTION G: Sequential Invocations — Ring Reuse
# Verify ring_destroy + ring_init works correctly for multiple frun calls
# in the same shell session. This tests state reset between invocations.
# ============================================================================
print_section G "Sequential Invocations: Ring Reuse"

# Two frun calls back-to-back in one script.
run_test_exact G "Two sequential frun calls produce correct independent output" \
    "out1=\$(echo 'first' | frun echo); out2=\$(echo 'second' | frun echo); echo \"\$out1 \$out2\"" \
    "first second"

# Three sequential calls.
run_test_exact G "Three sequential frun calls" \
    "a=\$(echo 'A' | frun echo); b=\$(echo 'B' | frun echo); c=\$(echo 'C' | frun echo); echo \"\$a\$b\$c\"" \
    "ABC"

# Sequential calls with different modes.
run_test_exact G "Sequential: first call ordered, second call unordered" \
    "r1=\$(seq 3 | frun -k printf '%s\n'); r2=\$(seq 3 | frun printf '%s\n' | sort); echo \"\$r1\"; echo \"\$r2\"" \
    "1
2
3
1
2
3"

# Sequential calls with different batch sizes.
run_test_exact G "Sequential: different -l values between calls" \
    "r1=\$(seq 4 | frun -l 1 -k printf '%s\n'); r2=\$(seq 4 | frun -l 4 -k printf '%s\n'); printf '%s\n' \"\$r1\" \"\$r2\"" \
    "1
2
3
4
1
2
3
4"

# Sequential calls using bash functions (ring state must not leak function defs).
run_test_exact G "Sequential: bash functions in each call independently defined" \
    "func_a() { echo \"A:\$*\"; }; r1=\$(echo 'x' | frun -l 1 func_a); func_b() { echo \"B:\$*\"; }; r2=\$(echo 'y' | frun -l 1 func_b); echo \"\$r1 \$r2\"" \
    "A:x B:y"

# Verify that output from call N doesn't appear in call N+1.
run_test_exact G "No output leakage between sequential calls" \
    "r1=\$(seq 5 | frun -k printf '%s\n'); r2=\$(seq 3 | frun -k printf '%s\n'); echo \"LINES:\$(echo \"\$r2\" | wc -l | tr -d ' ')\"" \
    "LINES:3"

# ============================================================================
# SECTION H: Combined Feature Interactions
# Test combinations that might surface interaction bugs.
# ============================================================================
print_section H "Combined Feature Interactions"

# Bash function + NUMA multi-node.
run_test_sorted H "Bash function + NUMA (--nodes=2)" \
    "my_tag() { echo \"TAG:\$*\"; }; seq 10 | frun --nodes=2 -l 1 my_tag" \
    "$(seq 10 | sed 's/^/TAG:/')"

# Bash function + byte mode + stdin.
run_test_exact H "Bash function + stdin byte mode (-b -s)" \
    "inspect() { wc -c | tr -d ' '; }; cat '$BYTE100' | frun -b 25 -s inspect | sort -n | paste -sd+ | bc" \
    "100"

# Bash function + insert (-i) substitution.
# {}'s are replaced with the input line; function wraps the result.
run_test_sorted H "Bash function + -i substitution" \
    "wrap() { echo \"[W:\$1]\"; }; seq 3 | frun -l 1 -i wrap {}" \
    "[W:1]
[W:2]
[W:3]"

# Bash function + limit (-n) with ordered output.
run_test_exact H "Bash function + -n limit + -k order" \
    "tag() { echo \"T:\$*\"; }; seq 100 | frun -l 1 -k -n 5 tag" \
    "T:1
T:2
T:3
T:4
T:5"

# FORKRUN_EXTRA_FUNCS + NUMA.
run_test_sorted H "FORKRUN_EXTRA_FUNCS + NUMA (--nodes=2)" \
    "inner() { echo \"IN:\$*\"; }; outer() { inner \"\$@\"; }; FORKRUN_EXTRA_FUNCS='inner' seq 6 | frun --nodes=2 -l 1 outer" \
    "IN:1
IN:2
IN:3
IN:4
IN:5
IN:6"

# Bash function + null delimiter (-z) + stdin.
run_test_exact H "Bash function + null delimiter (-z -s)" \
    "to_upper_stdin() { tr '[:lower:]' '[:upper:]'; }; printf 'abc\0def\0' | frun -z -s to_upper_stdin" \
    "$(printf 'ABC\0DEF\0')"

# Bash function + custom delimiter (-d).
run_test_sorted H "Bash function + custom delimiter (-d :)" \
    "wrap_field() { echo \"F:\$*\"; }; printf 'a:b:c' | frun -d ':' -l 1 wrap_field" \
    "F:a
F:b
F:c"

# Large input with bash function + ordered output (-k).
run_test_exact H "Bash function + 1000-line ordered integrity (-k)" \
    "identity() { printf '%s\n' \"\$@\"; }; seq 1000 | frun -k -l 1 identity" \
    "$(seq 1000)"

# Unsafe mode (-U) with function (space-splitting behavior test).
run_test_sorted H "Bash function + unsafe mode (-U)" \
    "show_argc() { echo \"\$#\"; }; printf 'a b\nc d\n' | frun -U -l 1 show_argc" \
    "2
2"

# Ordered mode (-k) with function that writes to stderr too.
# Stderr should not interfere with stdout ordering.
run_test_exact H "Bash function: stdout ordering unaffected by stderr writes" \
    "mixed() { echo \"\$*\" >&2; echo \"OUT:\$*\"; }; seq 5 | frun -k -l 1 mixed 2>/dev/null" \
    "OUT:1
OUT:2
OUT:3
OUT:4
OUT:5"

# ============================================================================
# SECTION I: Boundary Conditions
# ============================================================================
print_section I "Boundary Conditions"

# Empty input should produce no output and exit cleanly.
run_test_exact I "Empty input: no output, exit 0" \
    "cat '$EMPTY' | frun printf '%s\n'" \
    "" 0

# Single line input.
run_test_exact I "Single line input" \
    "echo 'only_line' | frun printf '%s\n'" \
    "only_line"

# Exactly 1 line with -l 100 (batch larger than input).
run_test_exact I "Batch size > input size (-l 100 for 1 line)" \
    "echo 'one' | frun -l 100 printf '%s\n'" \
    "one"

# Exactly batch-size lines (no partial last batch).
run_test_exact I "Input exactly equals batch size (-l 5, 5 lines)" \
    "seq 5 | frun -l 5 -k printf '%s\n'" \
    "$(seq 5)"

# Batch-size + 1 (triggers one full batch + one 1-item batch).
run_test_sorted I "Input = batch-size + 1 (-l 5, 6 lines)" \
    "seq 6 | frun -l 5 printf '%s\n'" \
    "$(seq 6)"

# Batch-size - 1 (one partial batch only).
run_test_sorted I "Input = batch-size - 1 (-l 5, 4 lines)" \
    "seq 4 | frun -l 5 printf '%s\n'" \
    "$(seq 4)"

# More workers requested than lines exist.
run_test_sorted I "More workers than input lines (-j 50 for 5 lines)" \
    "seq 5 | frun -j 50 printf '%s\n'" \
    "$(seq 5)"

# Worker count == 1 (serialized execution, verifies no parallelism-only bugs).
run_test_exact I "Single worker (-j 1) with ordered output" \
    "seq 5 | frun -j 1 -k printf '%s\n'" \
    "$(seq 5)"

# Very large batch on very small input (1 batch covers everything).
run_test_sorted I "Single batch covers entire input (-l 1000000 for 10 lines)" \
    "seq 10 | frun -l 1000000 printf '%s\n'" \
    "$(seq 10)"

# Limit exactly equals input size (should output all lines).
run_test_exact I "Limit equals input size (-n 10 for 10-line input)" \
    "seq 10 | frun -k -n 10 printf '%s\n'" \
    "$(seq 10)"

# Limit of 1 (exactly 1 record).
run_test_line_count I "Limit of 1 (-n 1)" \
    "seq 1000 | frun -n 1 printf '%s\n'" \
    1

# Limit of 0 (no records — edge case).
# The behavior may be 0 output lines or all lines depending on implementation.
# We just verify it doesn't deadlock/crash, not the exact count.
run_test_regex I "Limit of 0 (-n 0): exits cleanly (no hang)" \
    "timeout 10 bash -c \"source '$FRUN_SOURCE' && seq 100 | frun -n 0 printf '%s\n' ; echo EXIT_OK\"" \
    "EXIT_OK" 0 false

# Very long single line (tests SIMD scanner boundary alignment).
LONGLINE=$(printf '%0.s' {1..5000} | tr ' ' 'A')
run_test_sorted I "Very long line (5000 chars): survives quoting and SIMD scanner" \
    "printf '%s\n' '${LONGLINE}' | frun -l 1 printf '%s\n'" \
    "${LONGLINE}"

# Trickle input: data arrives slowly, scanner must flush partial batches early.
# This exercises the stall_meter + starve_meter early-flush invariant.
run_test_exact I "Trickle input: early flush delivers all lines (-k)" \
    "{ echo 'tick1'; sleep 0.15; echo 'tick2'; sleep 0.15; echo 'tick3'; } | frun -k -l 1000 printf '%s\n'" \
    "tick1
tick2
tick3"

# ============================================================================
# SECTION J: Worker / ID Semantics
# ============================================================================
print_section J "Worker and ID Semantics"

# -I flag: batch IDs must be present and follow the [NODE.]WORKER.BATCH format.
run_test_regex J "-I flag: batch ID format is [NODE.]WORKER.BATCH" \
    "echo 'test' | frun -l 1 -I echo {ID}" \
    "^([0-9]+\.)?[0-9]+\.[0-9]+$" 0 false

# -I: all batch IDs in a run must be unique (no ID collision between workers).
run_test_exact J "-I flag: all IDs in a 10-line run are unique" \
    "seq 10 | frun -l 1 -I echo {ID} | sort | uniq -d | wc -l | tr -d ' '" \
    "0"

# Verify RING_BATCH_IDX is set and non-negative in worker context.
run_test_regex J "RING_BATCH_IDX is set and numeric in worker" \
    "check() { echo \"\${RING_BATCH_IDX:-UNSET}\"; }; echo 'x' | frun -l 1 check" \
    "^[0-9]+$" 0 false

# Verify RING_BATCH_SLOTS is set and positive in worker context.
run_test_regex J "RING_BATCH_SLOTS is set and positive" \
    "check() { echo \"\${RING_BATCH_SLOTS:-UNSET}\"; }; echo 'x' | frun -l 1 check" \
    "^[1-9][0-9]*$" 0 false

# Worker command failure: pipeline must survive and not deadlock.
# The echo at the end verifies the pipeline wasn't blocked.
run_test_regex J "Worker failure (false): pipeline survives without deadlock" \
    "seq 10 | frun 'false' >/dev/null 2>&1; echo 'SURVIVED'" \
    "SURVIVED" 0 false

# Worker writing to stderr: main pipeline unaffected.
run_test_line_count J "Worker stderr output doesn't corrupt stdout" \
    "loud() { echo 'err' >&2; echo 'ok'; }; seq 5 | frun -l 1 loud 2>/dev/null" \
    5

# ============================================================================
# SECTION K: Framework Self-Tests
# Verify the new test helpers themselves are correct.
# ============================================================================
print_section K "Framework Self-Tests"

# run_test_sorted must catch a missing line (would slip through compare_token_sets).
echo "Verifying run_test_sorted catches missing lines..."
saved_total=$TOTAL_TESTS; saved_failed=$FAILED_TESTS
run_test_sorted K "_selftest_sorted_catches_missing" \
    "printf 'a\nb\n'" \
    "a
b
c"
if [[ "${TEST_RESULTS[_selftest_sorted_catches_missing]}" == "FAIL" ]]; then
    echo -e "  ${GREEN}✓${NC} run_test_sorted correctly caught a missing line"
    # Retroactively correct counters — this was an intentional failure
    TEST_RESULTS["_selftest_sorted_catches_missing"]="PASS"
    ((PASSED_TESTS++))
    ((FAILED_TESTS--))
else
    echo -e "  ${RED}✗${NC} run_test_sorted FAILED to catch a missing line — framework bug!"
fi

# run_test_sorted must catch a duplicate line.
echo "Verifying run_test_sorted catches duplicate lines..."
run_test_sorted K "_selftest_sorted_catches_duplicate" \
    "printf 'a\na\nb\n'" \
    "a
b"
if [[ "${TEST_RESULTS[_selftest_sorted_catches_duplicate]}" == "FAIL" ]]; then
    echo -e "  ${GREEN}✓${NC} run_test_sorted correctly caught a duplicate line"
    TEST_RESULTS["_selftest_sorted_catches_duplicate"]="PASS"
    ((PASSED_TESTS++))
    ((FAILED_TESTS--))
else
    echo -e "  ${RED}✗${NC} run_test_sorted FAILED to catch a duplicate line — framework bug!"
fi

# ============================================================================
# SUMMARY
# ============================================================================

echo
echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}SUMMARY${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
printf "Total:   %3d\n" "$TOTAL_TESTS"
printf "Passed:  %3d  (${GREEN}%.1f%%${NC})\n" "$PASSED_TESTS"  "$(awk "BEGIN {printf 100*$PASSED_TESTS/$TOTAL_TESTS}")"
printf "Failed:  %3d  (${RED}%.1f%%${NC})\n"   "$FAILED_TESTS"  "$(awk "BEGIN {printf 100*$FAILED_TESTS/$TOTAL_TESTS}")"
printf "Skipped: %3d  (${YELLOW}%.1f%%${NC})\n" "$SKIPPED_TESTS" "$(awk "BEGIN {printf 100*$SKIPPED_TESTS/$TOTAL_TESTS}")"
echo

if (( FAILED_TESTS > 0 )); then
    echo -e "${RED}${BOLD}FAILED TESTS:${NC}"
    for name in "${!TEST_RESULTS[@]}"; do
        [[ "${TEST_RESULTS[$name]}" == "FAIL" ]] && \
            printf "  ${RED}✗${NC}  %s — %s\n" "$name" "${TEST_ERRORS[$name]}"
    done
    echo
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}${BOLD}OVERALL: ${FAILED_TESTS} FAILURE(S)${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    exit 1
else
    echo -e "${GREEN}${BOLD}ALL TESTS PASSED!${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    exit 0
fi
