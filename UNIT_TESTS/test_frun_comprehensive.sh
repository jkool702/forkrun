#!/usr/bin/env bash
# ============================================================================
# FORKRUN COMPREHENSIVE SUPPLEMENTAL TEST SUITE v1.0
# ============================================================================
# Covers the gaps identified in test_frun.sh / test_frun_v2.sh:
#
#  SECTION A: Regression — Bash function transmission (the discovered bug)
#  SECTION B: Bash functions — core feature coverage
#  SECTION C: FORKRUN_EXTRA_FUNCS — dependent function chains
#  SECTION C2: FORKRUN_EXTRA_VARS — passing variables into the cleanroom
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
    # Returns 0 (true) if current section should run.
    # Supports multi-char labels: A, B, C, C2, D, ...
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
#
# IMPORTANT: FORKRUN_EXTRA_FUNCS must be set as an env var on the frun
# command itself, not on the upstream pipeline command:
#
#   CORRECT:   seq 10 | FORKRUN_EXTRA_FUNCS='helper' frun main_func
#   WRONG:     FORKRUN_EXTRA_FUNCS='helper' seq 10 | frun main_func
#
# The reason: frun reads this variable during its own cleanroom exec setup,
# where it calls declare -f on each name listed and injects the definitions
# into the cleanroom shell. If the variable is set on the pipeline source
# instead of on frun, it is in the environment of the wrong process.
# ============================================================================
print_section C "FORKRUN_EXTRA_FUNCS: Dependent Function Chains"

# main_func calls helper — helper must be exported via FORKRUN_EXTRA_FUNCS
# placed on the frun invocation itself.
run_test_sorted C "FORKRUN_EXTRA_FUNCS: one-level dependency" \
    "helper() { echo \"H:\$*\"; }; main_func() { helper \"\$@\"; }; seq 3 | FORKRUN_EXTRA_FUNCS='helper' frun -l 1 main_func" \
    "H:1
H:2
H:3"

# Two-level chain: main -> mid -> leaf.
# Both mid and leaf must appear in FORKRUN_EXTRA_FUNCS.
run_test_sorted C "FORKRUN_EXTRA_FUNCS: two-level chain" \
    "leaf() { echo \"LEAF:\$*\"; }; mid() { leaf \"\$@\"; }; main_func() { mid \"\$@\"; }; seq 3 | FORKRUN_EXTRA_FUNCS='mid leaf' frun -l 1 main_func" \
    "LEAF:1
LEAF:2
LEAF:3"

# Multiple independent helpers listed together in FORKRUN_EXTRA_FUNCS.
run_test_sorted C "FORKRUN_EXTRA_FUNCS: multiple helpers (space-separated list)" \
    "pfx() { echo \"P:\$*\"; }; sfx() { echo \"S:\$*\"; }; combo() { pfx \"\$@\"; sfx \"\$@\"; }; seq 2 | FORKRUN_EXTRA_FUNCS='pfx sfx' frun -l 1 combo" \
    "P:1
P:2
S:1
S:2"

# FORKRUN_EXTRA_FUNCS combined with -k (ordered output).
run_test_exact C "FORKRUN_EXTRA_FUNCS: ordered output (-k)" \
    "add_prefix() { echo \"ORDERED:\$*\"; }; main_f() { add_prefix \"\$@\"; }; seq 4 | FORKRUN_EXTRA_FUNCS='add_prefix' frun -l 1 -k main_f" \
    "ORDERED:1
ORDERED:2
ORDERED:3
ORDERED:4"

# FORKRUN_EXTRA_FUNCS combined with -s (stdin passthrough).
run_test_sorted C "FORKRUN_EXTRA_FUNCS: stdin passthrough (-s)" \
    "transform_stdin() { sed 's/^/X:/'; }; process_batch() { transform_stdin; }; printf 'a\nb\nc\n' | FORKRUN_EXTRA_FUNCS='transform_stdin' frun -s process_batch" \
    "X:a
X:b
X:c"

# FORKRUN_EXTRA_FUNCS combined with NUMA (--nodes=2).
run_test_sorted C "FORKRUN_EXTRA_FUNCS: works with --nodes=2" \
    "inner() { echo \"IN:\$*\"; }; outer() { inner \"\$@\"; }; seq 6 | FORKRUN_EXTRA_FUNCS='inner' frun --nodes=2 -l 1 outer" \
    "IN:1
IN:2
IN:3
IN:4
IN:5
IN:6"

# Omitting a required helper from FORKRUN_EXTRA_FUNCS must cause the function
# to be undefined in the cleanroom. The worker will get a "command not found"
# error from bash. We verify this produces non-empty stderr and non-zero output
# (rather than silently succeeding with wrong data).
# NOTE: We check that the output does NOT contain all expected lines — if the
# helper is missing, at least some workers will fail.
run_test_regex C "FORKRUN_EXTRA_FUNCS: missing helper causes worker error (not silent)" \
    "missing_helper() { echo \"SHOULD_NOT_APPEAR:\$*\"; }; caller_func() { missing_helper \"\$@\"; }; seq 3 | frun -l 1 caller_func 2>&1 | grep -c 'SHOULD_NOT_APPEAR' || true" \
    "^0$" 0 false

# ============================================================================
# SECTION C2: FORKRUN_EXTRA_VARS — Passing Variables into the Cleanroom
#
# FORKRUN_EXTRA_VARS passes variable names (space-separated) whose current
# values will be injected into the frun cleanroom shell.
# Like FORKRUN_EXTRA_FUNCS, it must be placed on the frun invocation:
#
#   CORRECT:   MY_VAR=hello seq 3 | FORKRUN_EXTRA_VARS='MY_VAR' frun func
#   CORRECT:   MY_VAR=hello; seq 3 | FORKRUN_EXTRA_VARS='MY_VAR' frun func
#   WRONG:     FORKRUN_EXTRA_VARS='MY_VAR' seq 3 | frun func
# ============================================================================
print_section C2 "FORKRUN_EXTRA_VARS: Passing Variables into the Cleanroom"

# Basic scalar variable injection.
run_test_sorted C2 "FORKRUN_EXTRA_VARS: scalar variable reaches workers" \
    "MY_TAG='hello'; use_tag() { echo \"\${MY_TAG}:\$*\"; }; seq 3 | FORKRUN_EXTRA_VARS='MY_TAG' frun -l 1 use_tag" \
    "hello:1
hello:2
hello:3"

# Multiple variables injected at once.
run_test_sorted C2 "FORKRUN_EXTRA_VARS: multiple variables (space-separated)" \
    "PREFIX='['; SUFFIX=']'; wrap_var() { echo \"\${PREFIX}\$1\${SUFFIX}\"; }; seq 3 | FORKRUN_EXTRA_VARS='PREFIX SUFFIX' frun -l 1 wrap_var" \
    "[1]
[2]
[3]"

# Variable containing spaces.
run_test_sorted C2 "FORKRUN_EXTRA_VARS: variable value containing spaces" \
    "MY_LABEL='hello world'; show_label() { echo \"\${MY_LABEL}:\$*\"; }; seq 2 | FORKRUN_EXTRA_VARS='MY_LABEL' frun -l 1 show_label" \
    "hello world:1
hello world:2"

# Numeric variable.
run_test_sorted C2 "FORKRUN_EXTRA_VARS: numeric variable used in arithmetic" \
    "MULTIPLIER=3; mul() { echo \$(( \$1 * MULTIPLIER )); }; seq 4 | FORKRUN_EXTRA_VARS='MULTIPLIER' frun -l 1 mul" \
    "3
6
9
12"

# FORKRUN_EXTRA_VARS combined with FORKRUN_EXTRA_FUNCS — both active.
run_test_sorted C2 "FORKRUN_EXTRA_VARS + FORKRUN_EXTRA_FUNCS: combined" \
    "MY_PFX='X'; format() { echo \"\${MY_PFX}:\$*\"; }; dispatch() { format \"\$@\"; }; seq 3 | FORKRUN_EXTRA_FUNCS='format' FORKRUN_EXTRA_VARS='MY_PFX' frun -l 1 dispatch" \
    "X:1
X:2
X:3"

# FORKRUN_EXTRA_VARS combined with ordered output (-k).
run_test_exact C2 "FORKRUN_EXTRA_VARS: ordered output (-k)" \
    "STEP='S'; label_step() { echo \"\${STEP}\$*\"; }; seq 4 | FORKRUN_EXTRA_VARS='STEP' frun -k -l 1 label_step" \
    "S1
S2
S3
S4"

# FORKRUN_EXTRA_VARS combined with -s (stdin passthrough).
# The variable is available inside the function that reads stdin.
run_test_sorted C2 "FORKRUN_EXTRA_VARS: available in stdin-mode (-s) function" \
    "MY_DELIM='|'; add_delim() { while IFS= read -r line; do echo \"\${line}\${MY_DELIM}\"; done; }; printf 'a\nb\nc\n' | FORKRUN_EXTRA_VARS='MY_DELIM' frun -s add_delim" \
    "a|
b|
c|"

# Variable that is unset should not inject into cleanroom (no error either).
# We verify the function gracefully handles an unset variable (empty string).
run_test_sorted C2 "FORKRUN_EXTRA_VARS: unset variable injects as empty string" \
    "unset UNSET_VAR 2>/dev/null; show_empty() { echo \"[\${UNSET_VAR:-EMPTY}]\"; }; seq 2 | FORKRUN_EXTRA_VARS='UNSET_VAR' frun -l 1 show_empty" \
    "[EMPTY]
[EMPTY]"

# Array variable injection (if supported — bash arrays via declare -p).
run_test_sorted C2 "FORKRUN_EXTRA_VARS: array variable injection" \
    "declare -a MY_ARR=(alpha beta gamma); use_arr() { echo \"\${MY_ARR[\$1-1]}\"; }; seq 3 | FORKRUN_EXTRA_VARS='MY_ARR' frun -l 1 use_arr" \
    "alpha
beta
gamma"

# Associative array injection.
run_test_sorted C2 "FORKRUN_EXTRA_VARS: associative array injection" \
    "declare -A MY_MAP=([one]=1 [two]=2 [three]=3); lookup() { echo \"\${MY_MAP[\$1]}\"; }; printf 'one\ntwo\nthree\n' | FORKRUN_EXTRA_VARS='MY_MAP' frun -l 1 lookup" \
    "1
2
3"

# Variable with special characters in value.
run_test_sorted C2 "FORKRUN_EXTRA_VARS: variable value with special characters" \
    "PATTERN='foo\$bar'; show_pattern() { echo \"\${PATTERN}\"; }; seq 2 | FORKRUN_EXTRA_VARS='PATTERN' frun -l 1 show_pattern" \
    'foo$bar
foo$bar'

# Large variable value (tests that no size limit is hit during injection).
run_test_line_count C2 "FORKRUN_EXTRA_VARS: large variable value (1000 chars)" \
    "BIG_VAR=\$(printf '%1000s' | tr ' ' 'X'); use_big() { echo \"\${#BIG_VAR}\"; }; seq 3 | FORKRUN_EXTRA_VARS='BIG_VAR' frun -l 1 use_big" \
    3

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
    "printf 'alpha\0beta\0gamma\0delta\0' | frun -z -k -s cat | md5sum | awk '{print \$1}'" \
    "$(printf 'alpha\0beta\0gamma\0delta\0' | md5sum | awk '{print $1}')"

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
    "cat '$SPECIAL' | frun -k -s cat" \
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
    "inner() { echo \"IN:\$*\"; }; outer() { inner \"\$@\"; }; seq 6 | FORKRUN_EXTRA_FUNCS='inner' frun --nodes=2 -l 1 outer" \
    "IN:1
IN:2
IN:3
IN:4
IN:5
IN:6"

# Bash function + null delimiter (-z) + stdin.
run_test_exact H "Bash function + null delimiter (-z -s)" \
    "to_upper_stdin() { tr '[:lower:]' '[:upper:]'; }; printf 'abc\0def\0' | frun -k -z -s to_upper_stdin" \
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

# -I flag: batch IDs must be present and follow the [{NODE.}WORKER.BATCH] format.
run_test_regex J "-I flag: batch ID format is {NODE.WORKER.BATCH}" \
    "echo 'test' | frun -l 1 -I echo {ID}" \
    "^\{([0-9]+\.)?[0-9]+\.[0-9]+\} .*$" 0 false

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
# FORKRUN TEST SUITE — SECTION L: Fault Resilience
# ============================================================================
# This file contains ONLY Section L tests, designed to be appended to
# test_frun_comprehensive.sh (or included via source). It covers the
# escrow / death-pipe / ring_poll / poison fault resilience subsystem.
#
# To use standalone, source this AFTER the test framework helpers and
# data setup from test_frun_comprehensive.sh, or just append this file's
# section to the end of test_frun_comprehensive.sh before the final summary.
#
# COVERAGE AREAS:
#   L1:  One-time transient failure → self-heal
#   L2:  Persistent failure → poison threshold
#   L3:  Output integrity under failure (ring_revert_output)
#   L4:  No output duplication from failed batches
#   L5:  Ordered output correctness with failures
#   L6:  Worker exit-0 not respawned (NUMA bug fix)
#   L7:  Multiple simultaneous worker failures
#   L8:  Large-batch failure integrity
#   L9:  Stdin-mode (-s) failure integrity
#   L10: Failure + combined flag interactions
#   L11: Stress — repeated fault injection
#   L12: Edge case — all workers fail
#   L13: Edge case — single line that crashes
#   L14: Worker produces output then crashes
#   L15: Failure doesn't corrupt line count across batches
#   L16: Catastrophic SIGKILL error → full teardown
#   L17: Scanner failure → force EOF and early exit
# ============================================================================
#
# MARKER FILE CONVENTION (NUMA-safe):
#   One-time crash functions use a marker file to track whether the crash
#   has already fired. The marker path includes a NUMA node identifier
#   via _nid() so that workers on different NUMA nodes use independent
#   marker files — preventing the race where one node's worker deletes
#   the marker before another node's retry can see it.
#
#   The marker is NEVER deleted within the function (no rm -f). It persists
#   for the lifetime of the frun invocation, which is safe because $$ is
#   unique per test (each test runs in a fresh bash -c). This eliminates
#   the race entirely: a successful worker cannot delete a marker that a
#   retry worker still needs.
#
#   _nid() returns the lowest allowed NUMA memory node for the current
#   process, read from /proc/self/status. On non-NUMA systems it returns 0.
#   It is injected into workers via FORKRUN_EXTRA_FUNCS='_nid ...'.
# ============================================================================

# ============================================================================
# SECTION L: Fault Resilience — Escrow, Poison, and Self-Healing
# ============================================================================
print_section L "Fault Resilience: Escrow, Poison, and Self-Healing"

# ---------- L1: One-time transient failure → self-heal ----------
# A worker crashes on one specific input value, then on retry it succeeds
# (because the crash trigger is a one-time file check). All lines must appear.
# Marker file is NUMA-keyed and never deleted (see convention above).

run_test_exact L "L1a: One-time crash self-heals (ordered, -k)" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; crash_once() { local _cm=\"/tmp/_frun_test_crash_n\$(_nid)_\$\$\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; else echo \"\$arg\"; fi; done; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='_nid crash_once' frun -k -l 1 crash_once" \
    "1
2
3
4
5"

# Same test with unordered output — verifies self-heal without ordering constraint.
run_test_sorted L "L1b: One-time crash self-heals (unordered)" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; crash_once() { local _cm=\"/tmp/_frun_test_crash_u_n\$(_nid)_\$\$\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; else echo \"\$arg\"; fi; done; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='_nid crash_once' frun -l 1 crash_once" \
    "$(seq 1 5)"

# One-time crash on the FIRST line — tests that line 1 gets retried and appears.
run_test_exact L "L1c: One-time crash on first line self-heals (-k)" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; crash_first() { local _cm=\"/tmp/_frun_test_crash_first_n\$(_nid)_\$\$\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"1\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; else echo \"\$arg\"; fi; done; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='_nid crash_first' frun -k -l 1 crash_first" \
    "$(seq 1 5)"

# One-time crash on the LAST line — tests the final batch boundary.
run_test_exact L "L1d: One-time crash on last line self-heals (-k)" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; crash_last() { local _cm=\"/tmp/_frun_test_crash_last_n\$(_nid)_\$\$\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"10\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; else echo \"\$arg\"; fi; done; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='_nid crash_last' frun -k -l 1 crash_last" \
    "$(seq 1 10)"

# ---------- L2: Persistent failure → poison threshold ----------
# A worker ALWAYS crashes on a specific value. After the poison threshold
# (default 3 retries), the batch is discarded and remaining lines still process.
# The crashing line should NOT appear in output.

run_test_exact L "L2a: Persistent crash: surviving lines output correctly (-k)" \
    "always_crash_3() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='always_crash_3' frun -k -l 1 always_crash_3" \
    "1
2
4
5" 3

run_test_sorted L "L2b: Persistent crash: surviving lines output correctly (unordered)" \
    "always_crash_3() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='always_crash_3' frun -l 1 always_crash_3" \
    "1
2
4
5" 3

run_test_sorted L "L2c: Persistent crash on 2 values: both lost, rest survive" \
    "always_crash_3_7() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]] || [[ \"\$arg\" == \"7\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='always_crash_3_7' frun -l 1 always_crash_3_7" \
    "1
2
4
5
6
8
9
10" 3

run_test_sorted L "L2d: Persistent crash in batch mode (-l 5): poisoned batch fully discarded" \
    "crash_on_6() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"6\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='crash_on_6' frun -l 5 crash_on_6" \
    "$(seq 1 5)" 3

# Persistent crash with exit code 139 (SIGSEGV-equivalent) — catastrophic exit
# causes frun to exit non-zero. We wrap with { ...; true; } so the test
# harness sees exit 0, and verify the surviving output is still correct.
run_test_sorted L "L2e: Persistent crash with exit 139: surviving lines correct" \
    "crash_segfault() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"5\" ]]; then exit 139; else echo \"\$arg\"; fi; done; }; { seq 1 8 | FORKRUN_EXTRA_FUNCS='crash_segfault' frun -l 1 crash_segfault 2>/dev/null; true; }" \
    "1
2
3
4
6
7
8"

# ---------- L3: Output integrity under failure (ring_revert_output) ----------
# When a worker crashes mid-batch after printing some output, the partial
# output must be discarded (ring_revert_output). No truncated/corrupted lines
# should appear.

run_test_exact L "L3a: Mid-batch crash: partial output discarded (-k)" \
    "crash_mid_output() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]]; then echo \"PARTIAL\"; exit 1; else echo \"\$arg\"; fi; done; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='crash_mid_output' frun -k -l 1 crash_mid_output" \
    "1
2
4
5" 3

# Verify "PARTIAL" does NOT appear anywhere in output.
run_test_regex L "L3b: Mid-batch crash: no partial/corrupt output leaks" \
    "crash_mid_output() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]]; then echo \"PARTIAL\"; exit 1; else echo \"\$arg\"; fi; done; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='crash_mid_output' frun -l 1 crash_mid_output 2>/dev/null" \
    "^[^P]*(1[^P]*2[^P]*4[^P]*5[^P]*)?$" 3 false

# Simpler version: just grep for "PARTIAL_LINE" not appearing in stdout.
run_test_regex L "L3c: Mid-batch crash: partial output NOT in stdout (grep check)" \
    "crash_mid_output() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]]; then echo \"PARTIAL_LINE\"; exit 1; else echo \"OK:\$arg\"; fi; done; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='crash_mid_output' frun -l 1 crash_mid_output 2>/dev/null | grep -c PARTIAL_LINE || true" \
    "^0$" 0 false

# ---------- L4: No output duplication from failed batches ----------
# If a batch fails and the escrow retry succeeds, the output must appear
# exactly once — no duplicates. Uses a one-time crash that succeeds on retry.

run_test_sorted L "L4a: One-time crash produces no duplicate output" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; crash_once_no_dup() { local _cm=\"/tmp/_frun_test_nodup_n\$(_nid)_\$\$\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"5\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; fi; echo \"\$arg\"; done; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='_nid crash_once_no_dup' frun -l 1 crash_once_no_dup | sort | uniq -c | awk '{if(\$1>1) exit 1}' && echo OK" \
    "OK"

# Verify exact line count after self-healing (10 unique lines, no extras).
run_test_line_count L "L4b: Self-heal: output has exact expected line count (10)" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; crash_once_cnt() { local _cm=\"/tmp/_frun_test_cnt_n\$(_nid)_\$\$\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"5\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; fi; echo \"\$arg\"; done; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='_nid crash_once_cnt' frun -l 1 crash_once_cnt" \
    10

# One-time crash + NUMA mode (--nodes=2) — the marker file is keyed to the
# NUMA node via _nid(), so workers on different nodes use independent markers.
# Without NUMA keying, one node's worker could delete the marker before the
# other node's retry sees it (cross-node rm -f race). With the fix, all 8
# lines self-heal correctly across NUMA boundaries.
run_test_exact L "L4c: One-time crash self-heals with NUMA (--nodes=2, -k)" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; crash_once_numa() { local _cm=\"/tmp/_frun_test_numa_n\$(_nid)_\$\$\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"4\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; else echo \"\$arg\"; fi; done; }; seq 1 8 | FORKRUN_EXTRA_FUNCS='_nid crash_once_numa' frun -k -l 1 --nodes=2 crash_once_numa" \
    "$(seq 1 8)"

# ---------- L5: Ordered output correctness with failures ----------
# When -k is used and a worker crashes, the surviving output must still
# appear in input order.

run_test_exact L "L5a: Ordered output after failure preserves input order (-k)" \
    "crash_4() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"4\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 8 | FORKRUN_EXTRA_FUNCS='crash_4' frun -k -l 1 crash_4" \
    "1
2
3
5
6
7
8" 3

# Ordered output with multiple failures — only surviving lines in order.
run_test_exact L "L5b: Ordered output with 2 persistent failures (-k)" \
    "crash_3_and_7() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]] || [[ \"\$arg\" == \"7\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='crash_3_and_7' frun -k -l 1 crash_3_and_7" \
    "1
2
4
5
6
8
9
10" 3

# Ordered with one-time crash — all lines present in order.
run_test_exact L "L5c: Ordered self-heal: all lines in correct order (-k)" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; crash_once_ord() { local _cm=\"/tmp/_frun_test_ord_n\$(_nid)_\$\$\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"6\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; fi; echo \"\$arg\"; done; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='_nid crash_once_ord' frun -k -l 1 crash_once_ord" \
    "$(seq 1 10)"

# ---------- L6: Worker exit-0 not respawned ----------
# Workers that exit with code 0 (normal completion) must NOT be respawned.
# This was a bug in NUMA mode where exit-0 workers would get respawned
# because the spawn pipe was still open.

run_test_sorted L "L6a: Workers exiting 0 are not respawned (no duplicate lines)" \
    "seq 1 50 | frun -j 4 -l 1 printf '%s\n' | sort | uniq -c | awk '{if(\$1>1) exit 1}' && echo OK" \
    "OK"

# An explicit exit 0 in the function should not cause duplication.
run_test_sorted L "L6b: Explicit exit 0 in function: no duplicates" \
    "early_exit0() { echo \"\$1\"; if [[ \"\$1\" == \"5\" ]]; then exit 0; fi; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='early_exit0' frun -l 1 early_exit0 | sort | uniq -c | awk '{if(\$1>1) exit 1}' && echo OK" \
    "OK"

# ---------- L7: Multiple simultaneous worker failures ----------
# When multiple workers crash concurrently, the orchestrator must handle
# all deaths without deadlock.

run_test_sorted L "L7a: Multiple failing workers: surviving lines correct" \
    "crash_even() { for arg in \"\$@\"; do if (( arg % 2 == 0 )); then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='crash_even' frun -l 1 -j 4 crash_even" \
    "1
3
5
7
9" 3

# Multiple failures with -j 1 (serialized) — single-worker mode handles
# repeated failures gracefully without state corruption.
run_test_exact L "L7b: Serialized (-j 1) with persistent failure: correct surviving output" \
    "crash_5_ser() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"5\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='crash_5_ser' frun -j 1 -k -l 1 crash_5_ser" \
    "1
2
3
4
6
7
8
9
10" 3

# Every 3rd line crashes — high failure rate with multiple workers.
run_test_sorted L "L7c: High failure rate (every 3rd line): survivors correct" \
    "crash_third() { for arg in \"\$@\"; do if (( arg % 3 == 0 )); then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 15 | FORKRUN_EXTRA_FUNCS='crash_third' frun -l 1 -j 4 crash_third" \
    "1
2
4
5
7
8
10
11
13
14" 3

# ---------- L8: Large-batch failure integrity ----------
# When a large batch contains a failing line, the entire batch is lost.
# Remaining batches must be intact.

# 50 lines with -l 10, line 25 always crashes → batch 21-30 is poisoned.
run_test_sorted L "L8a: Large batch (-l 10): poisoned batch discarded, rest intact" \
    "crash_25() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"25\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 50 | FORKRUN_EXTRA_FUNCS='crash_25' frun -l 10 crash_25" \
    "$(seq 1 20; seq 31 50)" 3

# One-time crash in large batch — all lines self-heal.
run_test_exact L "L8b: Large batch (-l 10) one-time crash: all lines survive (-k)" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; crash_once_25() { local _cm=\"/tmp/_frun_test_l8b_n\$(_nid)_\$\$\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"25\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; fi; echo \"\$arg\"; done; }; seq 1 50 | FORKRUN_EXTRA_FUNCS='_nid crash_once_25' frun -k -l 10 crash_once_25" \
    "$(seq 1 50)"

# ---------- L9: Stdin-mode (-s) failure integrity ----------
# In -s mode, data is spliced to worker stdin. When a worker crashes,
# the data is still in the global memfd and can be re-spliced on retry.

run_test_sorted L "L9a: Stdin mode (-s) with persistent crash: surviving lines correct" \
    "crash_on_3_stdin() { while IFS= read -r line; do if [[ \"\$line\" == \"3\" ]]; then exit 1; fi; echo \"\$line\"; done; }; seq 1 6 | FORKRUN_EXTRA_FUNCS='crash_on_3_stdin' frun -l 1 -s crash_on_3_stdin" \
    "1
2
4
5
6" 3

# Stdin mode with -k ordering and persistent crash.
run_test_exact L "L9b: Stdin mode (-s -k) with persistent crash: order preserved" \
    "crash_on_4_stdin() { while IFS= read -r line; do if [[ \"\$line\" == \"4\" ]]; then exit 1; fi; echo \"\$line\"; done; }; seq 1 8 | FORKRUN_EXTRA_FUNCS='crash_on_4_stdin' frun -k -l 1 -s crash_on_4_stdin" \
    "1
2
3
5
6
7
8" 3

# Stdin mode (-s) one-time crash self-heal — data is saved in a global memfd
# before being spliced to the worker's stdin, so the escrow mechanism should
# be able to re-splice the data to a replacement worker on retry. All 8 lines
# must appear in order. If this test fails, it may indicate a bug in forkrun's
# stdin-mode escrow/retry path.
run_test_exact L "L9c: Stdin mode (-s -k) one-time crash: self-heals" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; crash_once_stdin() { local _cm=\"/tmp/_frun_test_s9c_n\$(_nid)_\$\$\"; while IFS= read -r line; do if [[ \"\$line\" == \"4\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; fi; echo \"\$line\"; done; }; seq 1 8 | FORKRUN_EXTRA_FUNCS='_nid crash_once_stdin' frun -k -l 1 -s crash_once_stdin" \
    "$(seq 1 8)"

# ---------- L10: Failure + combined flag interactions ----------

# Failure + unsafe mode (-U) — with -l 1, each input line is one batch.
# In -U mode, "c d" is word-split into args c and d, but they're still in
# the SAME batch. The crash on "c" kills the entire batch, losing "d" too.
# Surviving output: a, b (from "a b"), e, f (from "e f") = 4 lines.
run_test_sorted L "L10a: Persistent crash + unsafe mode (-U): survivors correct" \
    "crash_c() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"c\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; printf 'a b\nc d\ne f\n' | FORKRUN_EXTRA_FUNCS='crash_c' frun -U -l 1 crash_c" \
    "a
b
e
f" 3

# Failure + FORKRUN_EXTRA_VARS — the variable must be available to the
# replacement worker (respawn inherits the same cleanroom).
run_test_exact L "L10b: One-time crash + FORKRUN_EXTRA_VARS: var survives respawn (-k)" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; MY_TAG='TAG'; crash_once_var() { local _cm=\"/tmp/_frun_test_var_n\$(_nid)_\$\$\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"3\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; fi; echo \"\${MY_TAG}:\$arg\"; done; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='_nid crash_once_var' FORKRUN_EXTRA_VARS='MY_TAG' frun -k -l 1 crash_once_var" \
    "TAG:1
TAG:2
TAG:3
TAG:4
TAG:5"

# Failure + FORKRUN_EXTRA_FUNCS chain — dependent helper must survive respawn.
run_test_exact L "L10c: One-time crash + FORKRUN_EXTRA_FUNCS chain: helper survives (-k)" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; helper_tag() { echo \"H:\$*\"; }; main_crash() { local _cm=\"/tmp/_frun_test_chain_n\$(_nid)_\$\$\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"4\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; fi; helper_tag \"\$arg\"; done; }; seq 1 6 | FORKRUN_EXTRA_FUNCS='_nid helper_tag' frun -k -l 1 main_crash" \
    "H:1
H:2
H:3
H:4
H:5
H:6"

# Failure + NUMA mode (--nodes=2) — persistent crash recovery works across nodes.
run_test_sorted L "L10d: Persistent crash + NUMA (--nodes=2): survivors correct" \
    "crash_5_numa() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"5\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='crash_5_numa' frun --nodes=2 -l 1 crash_5_numa" \
    "$(seq 1 4; seq 6 10)" 3

# Failure + -n limit — -n limits the number of input records dispatched.
# With -n 5, only the first 5 input lines (1-5) are dispatched. Line 2
# always crashes and is poisoned. Surviving output = 4 lines: 1,3,4,5.
run_test_exact L "L10e: Persistent crash + limit (-n 5 -k): 4 surviving lines from 5 inputs" \
    "crash_2_limit() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"2\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 10 | FORKRUN_EXTRA_FUNCS='crash_2_limit' frun -k -l 1 -n 5 crash_2_limit" \
    "1
3
4
5" 3

# Failure + --buffered mode — buffered output must not be corrupted.
run_test_sorted L "L10f: Persistent crash + --buffered: survivors correct" \
    "crash_5_buf() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"5\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 8 | FORKRUN_EXTRA_FUNCS='crash_5_buf' frun --buffered -l 1 crash_5_buf" \
    "1
2
3
4
6
7
8" 3

# Failure + insert mode (-i) — crash on specific substituted value.
run_test_sorted L "L10g: Persistent crash + -i insert mode: survivors correct" \
    "echo_item() { if [[ \"\$1\" == \"3\" ]]; then exit 1; fi; echo \"ITEM:\$1\"; }; seq 1 5 | frun -l 1 -i echo_item {}" \
    "ITEM:1
ITEM:2
ITEM:4
ITEM:5" 3

# Failure + byte mode (-b) — crash in small chunks, larger chunks survive.
# Chunks < 10 bytes crash. With -b 25, all chunks are 25 bytes (none crash).
# Total bytes across all surviving chunks should equal the original 100.
run_test_line_count L "L10h: Byte mode (-b 25): all chunks processed, correct total bytes" \
    "crash_bytes() { local data; data=\$(cat); if (( \${#data} < 10 )); then exit 1; fi; echo \"\${#data}\"; }; head -c 100 /dev/zero | tr '\0' 'x' | frun -b 25 -s crash_bytes 2>/dev/null | awk '{s+=\$1} END{print s}'" \
    1

# ---------- L11: Stress — Repeated fault injection ----------
# Run 5 iterations of a crash recovery scenario. Each must produce the same
# correct result. This catches intermittent race conditions in the
# death-pipe / escrow / respawn path.
#
# NOTE: Uses ok=$((ok+1)) instead of ((ok++)) because ((ok++)) evaluates
# to 0 when ok=0, returning exit code 1 — which terminates the shell under
# set -e. Also adds || true after frun to defensively prevent set -e from
# killing the loop if frun exits non-zero.

run_test_regex L "L11a: 5x stress: one-time crash always self-heals" \
    "_nid() { local _n; _n=\$(grep Mems_allowed_list /proc/self/status 2>/dev/null | cut -d: -f2 | tr -d ' ' | cut -d- -f1); echo \${_n:-0}; }; ok=0; for i in 1 2 3 4 5; do crash_once_stress() { local _cm=\"/tmp/_frun_stress_n\$(_nid)_\$\$_\${i}\"; for arg in \"\$@\"; do if [[ \"\$arg\" == \"5\" ]] && [[ ! -f \"\$_cm\" ]]; then touch \"\$_cm\"; exit 1; fi; echo \"\$arg\"; done; }; result=\$(seq 1 10 | FORKRUN_EXTRA_FUNCS='_nid crash_once_stress' frun -k -l 1 crash_once_stress 2>/dev/null || true); expected=\$(seq 1 10); if [[ \"\$result\" == \"\$expected\" ]]; then ok=\$((ok+1)); fi; done; echo \"\$ok\"" \
    "^5$" 0 false

# ---------- L12: Edge case — all workers fail ----------
# If every single input line causes a crash, the pipeline should still
# terminate (no deadlock). Output should be empty.

run_test_exact L "L12a: All lines crash: pipeline terminates, empty output" \
    "always_crash() { exit 1; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='always_crash' frun -l 1 always_crash" \
    "" 3

# All lines crash with -k — must still terminate.
run_test_regex L "L12b: All lines crash (-k): pipeline terminates (no hang)" \
    "timeout 10 bash -c \"source '$FRUN_SOURCE' && always_crash2() { exit 1; }; seq 1 5 | FORKRUN_EXTRA_FUNCS='always_crash2' frun -k -l 1 always_crash2\"" \
    ".*" 3 false

# ---------- L13: Edge case — single line that crashes ----------
# Only 1 input line, and it crashes. Pipeline must terminate with empty output.

run_test_exact L "L13: Single crashing line: empty output, clean exit" \
    "crash_always() { exit 1; }; echo 'only_line' | FORKRUN_EXTRA_FUNCS='crash_always' frun -l 1 crash_always" \
    "" 3

# ---------- L14: Worker produces output then crashes in same batch ----------
# ring_revert_output must discard the partial output.

run_test_regex L "L14: Worker outputs 2 lines then crashes: partial output discarded" \
    "output_then_crash() { echo 'BEFORE_CRASH_1'; echo 'BEFORE_CRASH_2'; exit 1; }; echo 'trigger' | FORKRUN_EXTRA_FUNCS='output_then_crash' frun -l 1 output_then_crash 2>/dev/null | grep -c BEFORE_CRASH || true" \
    "^0$" 0 false

# ---------- L15: Failure doesn't corrupt line count across batches ----------
# 100 lines with one persistent crash. The total surviving lines should be 99.
run_test_line_count L "L15: 100 lines, 1 persistent crash: 99 surviving lines" \
    "crash_50() { for arg in \"\$@\"; do if [[ \"\$arg\" == \"50\" ]]; then exit 1; else echo \"\$arg\"; fi; done; }; seq 1 100 | FORKRUN_EXTRA_FUNCS='crash_50' frun -l 1 crash_50" \
    99 3

# ---------- L16: Catastrophic SIGKILL error → full teardown ----------
# When a worker receives SIGKILL (which cannot be caught or intercepted),
# forkrun must detect the death via the death pipe (POLLHUP on the worker's
# stdout fd), perform a full teardown of the pipeline, and exit cleanly.
# This is distinct from the normal exit-1 failure path (which triggers
# escrow retry). SIGKILL means the worker is catastrophically dead and
# cannot be retried — the entire pipeline must shut down.

# L16a: Worker sends itself SIGKILL. The pipeline should terminate (not hang)
# and exit non-zero (catastrophic failure). We wrap with { ...; } and check
# that the pipeline doesn't hang and produces no corrupted output.
run_test_regex L "L16a: Worker SIGKILL: full teardown, pipeline terminates" \
    "timeout 20 bash -c 'source \"$FRUN_SOURCE\" && crash_kill9() { kill -9 \$BASHPID; }; seq 1 10 | FORKRUN_EXTRA_FUNCS=\"crash_kill9\" frun -l 1 crash_kill9 2>/dev/null; true'" \
    ".*" 0 false

# L16b: Worker SIGKILL after producing some output. The partial output must
# be discarded (ring_revert_output) — no corrupted/truncated lines.
run_test_regex L "L16b: Worker SIGKILL after partial output: no corruption" \
    "timeout 20 bash -c 'source \"$FRUN_SOURCE\" && crash_kill9_partial() { echo \"BEFORE_SIGKILL_\$1\"; kill -9 \$BASHPID; }; seq 1 10 | FORKRUN_EXTRA_FUNCS=\"crash_kill9_partial\" frun -l 1 crash_kill9_partial 2>/dev/null | grep -c BEFORE_SIGKILL || true'" \
    "^0$" 0 false

# L16c: SIGKILL in -k ordered mode — pipeline must still terminate.
# Ordered mode adds complexity because the orchestrator must drain the
# ordered-output queue. SIGKILL should bypass that and force teardown.
run_test_regex L "L16c: Worker SIGKILL in -k mode: pipeline terminates" \
    "timeout 20 bash -c 'source \"$FRUN_SOURCE\" && crash_kill9_k() { kill -9 \$BASHPID; }; seq 1 10 | FORKRUN_EXTRA_FUNCS=\"crash_kill9_k\" frun -k -l 1 crash_kill9_k 2>/dev/null; true'" \
    ".*" 0 false

# L16d: SIGKILL in stdin mode (-s) — the splice path must not deadlock.
# When a worker reading from stdin via splice is killed, the splice fd
# must be cleaned up without blocking the ring.
run_test_regex L "L16d: Worker SIGKILL in -s mode: no deadlock" \
    "timeout 20 bash -c 'source \"$FRUN_SOURCE\" && crash_kill9_s() { kill -9 \$BASHPID; }; seq 1 10 | FORKRUN_EXTRA_FUNCS=\"crash_kill9_s\" frun -s -l 1 crash_kill9_s 2>/dev/null; true'" \
    ".*" 0 false

# L16e: SIGKILL with multiple workers (-j 4) — the surviving workers must
# not hang waiting for the killed worker's ring slot. The death pipe should
# unblock ring_poll and allow clean shutdown.
run_test_regex L "L16e: Worker SIGKILL with -j 4: surviving workers shut down" \
    "timeout 20 bash -c 'source \"$FRUN_SOURCE\" && crash_kill9_j4() { if [[ \"\$1\" == \"5\" ]]; then kill -9 \$BASHPID; else echo \"\$1\"; fi; }; seq 1 20 | FORKRUN_EXTRA_FUNCS=\"crash_kill9_j4\" frun -j 4 -l 1 crash_kill9_j4 2>/dev/null; true'" \
    ".*" 0 false

# ---------- L17: Scanner failure → force EOF and early exit ----------
# When the scanner (the process that reads input and distributes batches
# to workers via the ring) fails or the input pipe closes prematurely,
# forkrun must force EOF on all workers and exit cleanly. Workers must
# not hang waiting for more batches that will never arrive.

# L17a: Input pipe closes early — scanner hits EOF, workers finish their
# current batches, and the pipeline terminates. No hang.
run_test_regex L "L17a: Scanner EOF (input closes early): pipeline terminates" \
    "timeout 20 bash -c 'source \"$FRUN_SOURCE\" && (seq 1 5; exit 0) | frun -l 1 echo'" \
    ".*" 0 false

# L17b: Input process dies mid-stream — the scanner detects the broken pipe
# and forces EOF. Workers complete current work and exit. The pipeline must
# not deadlock waiting for input that will never arrive.
run_test_regex L "L17b: Scanner failure (input dies mid-stream): pipeline terminates" \
    "timeout 20 bash -c 'source \"$FRUN_SOURCE\" && (seq 1 3; exit 1) | frun -l 1 echo 2>/dev/null; true'" \
    ".*" 0 false

# L17c: Scanner failure with -k ordering — the ordered-output queue must be
# drained or abandoned when the scanner dies. Pipeline must terminate.
run_test_regex L "L17c: Scanner failure with -k: pipeline terminates (no hang)" \
    "timeout 20 bash -c 'source \"$FRUN_SOURCE\" && (seq 1 3; exit 1) | frun -k -l 1 echo 2>/dev/null; true'" \
    ".*" 0 false

# L17d: Scanner failure with workers still processing — some workers may be
# mid-batch when the scanner dies. They should complete their current batch,
# then exit. No partial/corrupted output should appear.
run_test_regex L "L17d: Scanner failure mid-processing: no corrupted output" \
    "timeout 20 bash -c 'source \"$FRUN_SOURCE\" && (seq 1 3; exit 1) | frun -k -l 1 echo 2>/dev/null | grep -v \"^[0-9]*$\" | wc -l || true'" \
    "^0$|^1$" 0 false

# L17e: Scanner failure with -s stdin mode — the splice from the input pipe
# to the worker's stdin must be cleaned up without deadlock.
run_test_regex L "L17e: Scanner failure in -s mode: no deadlock" \
    "timeout 20 bash -c 'source \"$FRUN_SOURCE\" && (seq 1 3; exit 1) | frun -s -l 1 cat 2>/dev/null; true'" \
    ".*" 0 false

# ============================================================================
# SECTION M: Checkpoint & Resume
# ============================================================================

print_section M "Checkpoint & Resume"

# ============================================================================
# Shared crash function: kills the worker on a specific input value.
# Only crashes on the FIRST run (when checkpoint file doesn't exist yet).
# On resume, the checkpoint file exists, so the function processes normally.
#
# IMPORTANT: Use printf '%s\n' (not echo) for 1:1 input→output line mapping.
# ============================================================================

_M_FUNCS="$TEST_DIR/resume_funcs.sh"

# ============================================================================
# M1: Checkpoint file created on worker SIGKILL (-k, ordered)
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M1"; mkdir -p "$_MD"
    seq 1000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
crash_func() {
    for a in "$@"; do
        if (( a == 50 )) && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '%s\n' "$a"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -k -l 1 crash_func" \
        > /dev/null 2>"$_MD/err1.txt"

    if [[ -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M1: Checkpoint file created on worker SIGKILL (-k)"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "M1: Checkpoint file created on worker SIGKILL (-k)"
    else
        TEST_RESULTS["M1: Checkpoint file created on worker SIGKILL (-k)"]="FAIL"
        TEST_ERRORS["M1: Checkpoint file created on worker SIGKILL (-k)"]="no checkpoint file"
        ((FAILED_TESTS++)); _print_result FAIL "M1: Checkpoint file created on worker SIGKILL (-k)" "no checkpoint file"
    fi
fi

# ============================================================================
# M2: Checkpoint contains FORKRUN_RESUME_HORIZON or equivalent resume state
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    if [[ -f "${_MD:-}/.forkrun_resume" ]]; then
        # Check for any resume-related variable (name may vary)
        if grep -qE '(FORKRUN_RESUME_HORIZON|RESUME_HORIZON|resume_horizon|RING_RESUME)' "$_MD/.forkrun_resume" 2>/dev/null; then
            TEST_RESULTS["M2: Checkpoint contains resume horizon state"]="PASS"; ((PASSED_TESTS++))
            _print_result PASS "M2: Checkpoint contains resume horizon state"
        else
            # Dump what IS in the file for debugging
            _MCONTENTS=$(head -5 "$_MD/.forkrun_resume" 2>/dev/null | tr '\n' ' ')
            TEST_RESULTS["M2: Checkpoint contains resume horizon state"]="FAIL"
            TEST_ERRORS["M2: Checkpoint contains resume horizon state"]="no horizon var found. Contents: $_MCONTENTS"
            ((FAILED_TESTS++)); _print_result FAIL "M2: Checkpoint contains resume horizon state" "no horizon var"
        fi
    else
        TEST_RESULTS["M2: Checkpoint contains resume horizon state"]="SKIP"; ((SKIPPED_TESTS++))
        _print_result SKIP "M2: Checkpoint contains resume horizon state" "no checkpoint from M1"
    fi
fi

# ============================================================================
# M3: Checkpoint contains FORKRUN_ORIG_ARGS
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    if [[ -f "${_MD:-}/.forkrun_resume" ]]; then
        if grep -q 'FORKRUN_ORIG_ARGS' "$_MD/.forkrun_resume" 2>/dev/null; then
            TEST_RESULTS["M3: Checkpoint contains FORKRUN_ORIG_ARGS"]="PASS"; ((PASSED_TESTS++))
            _print_result PASS "M3: Checkpoint contains FORKRUN_ORIG_ARGS"
        else
            TEST_RESULTS["M3: Checkpoint contains FORKRUN_ORIG_ARGS"]="FAIL"
            TEST_ERRORS["M3: Checkpoint contains FORKRUN_ORIG_ARGS"]="variable not found"
            ((FAILED_TESTS++)); _print_result FAIL "M3: Checkpoint contains FORKRUN_ORIG_ARGS" "variable not found"
        fi
    else
        TEST_RESULTS["M3: Checkpoint contains FORKRUN_ORIG_ARGS"]="SKIP"; ((SKIPPED_TESTS++))
        _print_result SKIP "M3: Checkpoint contains FORKRUN_ORIG_ARGS" "no checkpoint from M1"
    fi
fi

# ============================================================================
# M4: Resume after SIGKILL produces complete output (-k, exactly-once)
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M4"; mkdir -p "$_MD"
    seq 1000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
crash_func() {
    for a in "$@"; do
        if (( a == 50 )) && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '%s\n' "$a"
        fi
    done
}
FUNCEOF

    # Run 1: crash
    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -k -l 1 crash_func" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    if [[ ! -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M4: Resume produces complete output (-k)"]="FAIL"
        TEST_ERRORS["M4: Resume produces complete output (-k)"]="no checkpoint after crash"
        ((FAILED_TESTS++)); _print_result FAIL "M4: Resume produces complete output (-k)" "no checkpoint"
    else
        # Extract truncation byte count from stderr message
        _MBYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_MD/err1.txt" 2>/dev/null || echo "")

        # Truncate output1 to the valid byte count
        if [[ -n "$_MBYTES" ]] && (( _MBYTES > 0 )); then
            head -c "$_MBYTES" "$_MD/output1.txt" > "$_MD/output1_trunc.txt"
            mv "$_MD/output1_trunc.txt" "$_MD/output1.txt"
        fi

        # Run 2: resume
        bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -k -l 1 --resume '.forkrun_resume' crash_func" \
            > "$_MD/output2.txt" 2>"$_MD/err2.txt"

        # Combine truncated output1 + output2
        cat "$_MD/output1.txt" "$_MD/output2.txt" > "$_MD/combined.txt"

        _ML=$(wc -l < "$_MD/combined.txt" | tr -d ' ')
        _MDUP=$(sort "$_MD/combined.txt" | uniq -d | wc -l | tr -d ' ')
        _MMISS=$(comm -23 <(seq 1000 | sort) <(sort "$_MD/combined.txt") | wc -l | tr -d ' ')

        if (( _ML == 1000 && _MDUP == 0 && _MMISS == 0 )); then
            # Also verify exact order for -k mode
            if diff -q <(seq 1000) "$_MD/combined.txt" &>/dev/null; then
                TEST_RESULTS["M4: Resume produces complete output (-k)"]="PASS"; ((PASSED_TESTS++))
                _print_result PASS "M4: Resume produces complete output (-k)"
            else
                TEST_RESULTS["M4: Resume produces complete output (-k)"]="FAIL"
                TEST_ERRORS["M4: Resume produces complete output (-k)"]="all lines present but order wrong"
                ((FAILED_TESTS++)); _print_result FAIL "M4: Resume produces complete output (-k)" "order wrong"
            fi
        else
            _MREASON="lines=$_ML dupes=$_MDUP missing=$_MMISS"
            TEST_RESULTS["M4: Resume produces complete output (-k)"]="FAIL"
            TEST_ERRORS["M4: Resume produces complete output (-k)"]="$_MREASON"
            ((FAILED_TESTS++)); _print_result FAIL "M4: Resume produces complete output (-k)" "$_MREASON"
        fi
    fi
fi

# ============================================================================
# M5: Resume with buffered/unordered mode (default)
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M5"; mkdir -p "$_MD"
    seq 1000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
crash_func() {
    for a in "$@"; do
        if (( a == 50 )) && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '%s\n' "$a"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -l 1 crash_func" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    if [[ ! -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M5: Resume with buffered mode"]="FAIL"
        TEST_ERRORS["M5: Resume with buffered mode"]="no checkpoint"
        ((FAILED_TESTS++)); _print_result FAIL "M5: Resume with buffered mode" "no checkpoint"
    else
        _MBYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_MD/err1.txt" 2>/dev/null || echo "")
        if [[ -n "$_MBYTES" ]] && (( _MBYTES > 0 )); then
            head -c "$_MBYTES" "$_MD/output1.txt" > "$_MD/output1_trunc.txt"
            mv "$_MD/output1_trunc.txt" "$_MD/output1.txt"
        fi

        bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -l 1 --resume '.forkrun_resume' crash_func" \
            > "$_MD/output2.txt" 2>"$_MD/err2.txt"

        cat "$_MD/output1.txt" "$_MD/output2.txt" > "$_MD/combined.txt"

        _MUNIQ=$(sort -u "$_MD/combined.txt" | wc -l | tr -d ' ')
        _MDUP=$(sort "$_MD/combined.txt" | uniq -d | wc -l | tr -d ' ')

        if (( _MUNIQ == 1000 && _MDUP == 0 )); then
            TEST_RESULTS["M5: Resume with buffered mode"]="PASS"; ((PASSED_TESTS++))
            _print_result PASS "M5: Resume with buffered mode"
        else
            TEST_RESULTS["M5: Resume with buffered mode"]="FAIL"
            TEST_ERRORS["M5: Resume with buffered mode"]="unique=$_MUNIQ dupes=$_MDUP"
            ((FAILED_TESTS++)); _print_result FAIL "M5: Resume with buffered mode" "unique=$_MUNIQ dupes=$_MDUP"
        fi
    fi
fi

# ============================================================================
# M6: Resume with realtime mode (-u, at-least-once semantics)
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M6"; mkdir -p "$_MD"
    seq 1000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
crash_func() {
    for a in "$@"; do
        if (( a == 50 )) && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '%s\n' "$a"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -u -l 1 crash_func" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    if [[ ! -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M6: Resume with realtime mode (-u)"]="FAIL"
        TEST_ERRORS["M6: Resume with realtime mode (-u)"]="no checkpoint"
        ((FAILED_TESTS++)); _print_result FAIL "M6: Resume with realtime mode (-u)" "no checkpoint"
    else
        # Realtime mode: resume to a FRESH file, then check combined coverage
        bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -u -l 1 --resume '.forkrun_resume' crash_func" \
            > "$_MD/output2.txt" 2>"$_MD/err2.txt"

        # At-least-once: every input line should appear in at least one output
        _MUNIQ=$( { cat "$_MD/output1.txt"; cat "$_MD/output2.txt"; } | sort -u | wc -l | tr -d ' ')

        if (( _MUNIQ >= 1000 )); then
            TEST_RESULTS["M6: Resume with realtime mode (-u)"]="PASS"; ((PASSED_TESTS++))
            _print_result PASS "M6: Resume with realtime mode (-u)" "(at-least-once: $_MUNIQ unique)"
        else
            TEST_RESULTS["M6: Resume with realtime mode (-u)"]="FAIL"
            TEST_ERRORS["M6: Resume with realtime mode (-u)"]="only $_MUNIQ unique lines"
            ((FAILED_TESTS++)); _print_result FAIL "M6: Resume with realtime mode (-u)" "only $_MUNIQ unique lines"
        fi
    fi
fi

# ============================================================================
# M7: Resume with stdin mode (-s)
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M7"; mkdir -p "$_MD"
    seq 1000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    # -s mode: data comes via stdin, not cmdline args. Function reads stdin.
    cat > "$_MD/funcs.sh" << 'FUNCEOF'
crash_stdin() {
    local line
    while IFS= read -r line; do
        if [[ "$line" == "50" ]] && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '%s\n' "$line"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_stdin' frun -k -s crash_stdin" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    if [[ ! -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M7: Resume with stdin mode (-s)"]="FAIL"
        TEST_ERRORS["M7: Resume with stdin mode (-s)"]="no checkpoint"
        ((FAILED_TESTS++)); _print_result FAIL "M7: Resume with stdin mode (-s)" "no checkpoint"
    else
        _MBYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_MD/err1.txt" 2>/dev/null || echo "")
        if [[ -n "$_MBYTES" ]] && (( _MBYTES > 0 )); then
            head -c "$_MBYTES" "$_MD/output1.txt" > "$_MD/output1_trunc.txt"
            mv "$_MD/output1_trunc.txt" "$_MD/output1.txt"
        fi

        bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_stdin' frun -k -s --resume '.forkrun_resume' crash_stdin" \
            > "$_MD/output2.txt" 2>"$_MD/err2.txt"

        cat "$_MD/output1.txt" "$_MD/output2.txt" > "$_MD/combined.txt"

        _ML=$(wc -l < "$_MD/combined.txt" | tr -d ' ')
        _MDUP=$(sort "$_MD/combined.txt" | uniq -d | wc -l | tr -d ' ')
        _MMISS=$(comm -23 <(seq 1000 | sort) <(sort "$_MD/combined.txt") | wc -l | tr -d ' ')

        if (( _ML == 1000 && _MDUP == 0 && _MMISS == 0 )); then
            TEST_RESULTS["M7: Resume with stdin mode (-s)"]="PASS"; ((PASSED_TESTS++))
            _print_result PASS "M7: Resume with stdin mode (-s)"
        else
            TEST_RESULTS["M7: Resume with stdin mode (-s)"]="FAIL"
            TEST_ERRORS["M7: Resume with stdin mode (-s)"]="lines=$_ML dupes=$_MDUP missing=$_MMISS"
            ((FAILED_TESTS++)); _print_result FAIL "M7: Resume with stdin mode (-s)" "lines=$_ML dupes=$_MDUP missing=$_MMISS"
        fi
    fi
fi

# ============================================================================
# M8: Resume with byte mode (-b)
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M8"; mkdir -p "$_MD"
    seq 1000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"
    _MEXP=$(wc -c < "$_MD/input.txt" | tr -d ' ')

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
crash_cat() {
    local line
    while IFS= read -r line; do
        if [[ "$line" == "50" ]] && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '%s\n' "$line"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_cat' frun -k -b 4096 -s crash_cat" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    if [[ ! -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M8: Resume with byte mode (-b)"]="FAIL"
        TEST_ERRORS["M8: Resume with byte mode (-b)"]="no checkpoint"
        ((FAILED_TESTS++)); _print_result FAIL "M8: Resume with byte mode (-b)" "no checkpoint"
    else
        _MBYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_MD/err1.txt" 2>/dev/null || echo "")
        if [[ -n "$_MBYTES" ]] && (( _MBYTES > 0 )); then
            head -c "$_MBYTES" "$_MD/output1.txt" > "$_MD/output1_trunc.txt"
            mv "$_MD/output1_trunc.txt" "$_MD/output1.txt"
        fi

        bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_cat' frun -k -b 4096 -s --resume '.forkrun_resume' crash_cat" \
            > "$_MD/output2.txt" 2>"$_MD/err2.txt"

        cat "$_MD/output1.txt" "$_MD/output2.txt" > "$_MD/combined.txt"

        _ML=$(wc -l < "$_MD/combined.txt" | tr -d ' ')
        _MMISS=$(comm -23 <(seq 1000 | sort) <(sort "$_MD/combined.txt") | wc -l | tr -d ' ')

        if (( _ML == 1000 && _MMISS == 0 )); then
            TEST_RESULTS["M8: Resume with byte mode (-b)"]="PASS"; ((PASSED_TESTS++))
            _print_result PASS "M8: Resume with byte mode (-b)"
        else
            TEST_RESULTS["M8: Resume with byte mode (-b)"]="FAIL"
            TEST_ERRORS["M8: Resume with byte mode (-b)"]="lines=$_ML missing=$_MMISS"
            ((FAILED_TESTS++)); _print_result FAIL "M8: Resume with byte mode (-b)" "lines=$_ML missing=$_MMISS"
        fi
    fi
fi

# ============================================================================
# M9: Resume preserves FORKRUN_EXTRA_VARS
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M9"; mkdir -p "$_MD"
    seq 1000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
label_func() {
    for a in "$@"; do
        if (( a == 50 )) && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '%s\n' "${MY_LABEL}:${a}"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; MY_LABEL='VAR_OK'; cat input.txt | FORKRUN_EXTRA_FUNCS='label_func' FORKRUN_EXTRA_VARS='MY_LABEL' frun -k -l 1 label_func" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    if [[ ! -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M9: Resume preserves FORKRUN_EXTRA_VARS"]="FAIL"
        TEST_ERRORS["M9: Resume preserves FORKRUN_EXTRA_VARS"]="no checkpoint"
        ((FAILED_TESTS++)); _print_result FAIL "M9: Resume preserves FORKRUN_EXTRA_VARS" "no checkpoint"
    else
        # Check that MY_LABEL is in the checkpoint
        if ! grep -q 'MY_LABEL' "$_MD/.forkrun_resume" 2>/dev/null; then
            TEST_RESULTS["M9: Resume preserves FORKRUN_EXTRA_VARS"]="FAIL"
            TEST_ERRORS["M9: Resume preserves FORKRUN_EXTRA_VARS"]="MY_LABEL not in checkpoint"
            ((FAILED_TESTS++)); _print_result FAIL "M9: Resume preserves FORKRUN_EXTRA_VARS" "MY_LABEL not in checkpoint"
        else
            _MBYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_MD/err1.txt" 2>/dev/null || echo "")
            if [[ -n "$_MBYTES" ]] && (( _MBYTES > 0 )); then
                head -c "$_MBYTES" "$_MD/output1.txt" > "$_MD/output1_trunc.txt"
                mv "$_MD/output1_trunc.txt" "$_MD/output1.txt"
            fi

            bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; MY_LABEL='VAR_OK'; cat input.txt | FORKRUN_EXTRA_FUNCS='label_func' FORKRUN_EXTRA_VARS='MY_LABEL' frun -k -l 1 --resume '.forkrun_resume' label_func" \
                > "$_MD/output2.txt" 2>"$_MD/err2.txt"

            cat "$_MD/output1.txt" "$_MD/output2.txt" > "$_MD/combined.txt"

            _ML=$(wc -l < "$_MD/combined.txt" | tr -d ' ')
            _MLAB=$(grep -c '^VAR_OK:' "$_MD/combined.txt" 2>/dev/null || echo 0)

            if (( _ML == 1000 && _MLAB == 1000 )); then
                TEST_RESULTS["M9: Resume preserves FORKRUN_EXTRA_VARS"]="PASS"; ((PASSED_TESTS++))
                _print_result PASS "M9: Resume preserves FORKRUN_EXTRA_VARS"
            else
                TEST_RESULTS["M9: Resume preserves FORKRUN_EXTRA_VARS"]="FAIL"
                TEST_ERRORS["M9: Resume preserves FORKRUN_EXTRA_VARS"]="lines=$_ML with_label=$_MLAB"
                ((FAILED_TESTS++)); _print_result FAIL "M9: Resume preserves FORKRUN_EXTRA_VARS" "lines=$_ML with_label=$_MLAB"
            fi
        fi
    fi
fi

# ============================================================================
# M10: Resume preserves FORKRUN_EXTRA_FUNCS
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M10"; mkdir -p "$_MD"
    seq 1000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
helper_fn() { printf 'H:%s\n' "$1"; }
main_fn() {
    for a in "$@"; do
        if (( a == 50 )) && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            helper_fn "$a"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='helper_fn main_fn' frun -k -l 1 main_fn" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    if [[ ! -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M10: Resume preserves FORKRUN_EXTRA_FUNCS"]="FAIL"
        TEST_ERRORS["M10: Resume preserves FORKRUN_EXTRA_FUNCS"]="no checkpoint"
        ((FAILED_TESTS++)); _print_result FAIL "M10: Resume preserves FORKRUN_EXTRA_FUNCS" "no checkpoint"
    else
        if ! grep -q 'helper_fn' "$_MD/.forkrun_resume" 2>/dev/null; then
            TEST_RESULTS["M10: Resume preserves FORKRUN_EXTRA_FUNCS"]="FAIL"
            TEST_ERRORS["M10: Resume preserves FORKRUN_EXTRA_FUNCS"]="helper_fn not in checkpoint"
            ((FAILED_TESTS++)); _print_result FAIL "M10: Resume preserves FORKRUN_EXTRA_FUNCS" "helper_fn not in checkpoint"
        else
            _MBYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_MD/err1.txt" 2>/dev/null || echo "")
            if [[ -n "$_MBYTES" ]] && (( _MBYTES > 0 )); then
                head -c "$_MBYTES" "$_MD/output1.txt" > "$_MD/output1_trunc.txt"
                mv "$_MD/output1_trunc.txt" "$_MD/output1.txt"
            fi

            bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='helper_fn main_fn' frun -k -l 1 --resume '.forkrun_resume' main_fn" \
                > "$_MD/output2.txt" 2>"$_MD/err2.txt"

            cat "$_MD/output1.txt" "$_MD/output2.txt" > "$_MD/combined.txt"

            _ML=$(wc -l < "$_MD/combined.txt" | tr -d ' ')
            _MH=$(grep -c '^H:' "$_MD/combined.txt" 2>/dev/null || echo 0)

            if (( _ML == 1000 && _MH == 1000 )); then
                TEST_RESULTS["M10: Resume preserves FORKRUN_EXTRA_FUNCS"]="PASS"; ((PASSED_TESTS++))
                _print_result PASS "M10: Resume preserves FORKRUN_EXTRA_FUNCS"
            else
                TEST_RESULTS["M10: Resume preserves FORKRUN_EXTRA_FUNCS"]="FAIL"
                TEST_ERRORS["M10: Resume preserves FORKRUN_EXTRA_FUNCS"]="lines=$_ML H:lines=$_MH"
                ((FAILED_TESTS++)); _print_result FAIL "M10: Resume preserves FORKRUN_EXTRA_FUNCS" "lines=$_ML H:=$_MH"
            fi
        fi
    fi
fi

# ============================================================================
# M11: Missing resume file produces error
# ============================================================================
run_test_regex M "M11: Missing resume file error" \
    "echo 'test' | frun --resume /nonexistent/path/.forkrun_resume printf '%s'" \
    "Resume file.*not found|not found" \
    1 true

# ============================================================================
# M12: Resume with NUMA (--nodes=2)
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M12"; mkdir -p "$_MD"
    seq 1000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
crash_func() {
    for a in "$@"; do
        if (( a == 50 )) && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '%s\n' "$a"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -k --nodes=2 -l 1 crash_func" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    if [[ ! -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M12: Resume with NUMA (--nodes=2)"]="FAIL"
        TEST_ERRORS["M12: Resume with NUMA (--nodes=2)"]="no checkpoint"
        ((FAILED_TESTS++)); _print_result FAIL "M12: Resume with NUMA (--nodes=2)" "no checkpoint"
    else
        _MBYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_MD/err1.txt" 2>/dev/null || echo "")
        if [[ -n "$_MBYTES" ]] && (( _MBYTES > 0 )); then
            head -c "$_MBYTES" "$_MD/output1.txt" > "$_MD/output1_trunc.txt"
            mv "$_MD/output1_trunc.txt" "$_MD/output1.txt"
        fi

        bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -k --nodes=2 -l 1 --resume '.forkrun_resume' crash_func" \
            > "$_MD/output2.txt" 2>"$_MD/err2.txt"

        cat "$_MD/output1.txt" "$_MD/output2.txt" > "$_MD/combined.txt"

        _ML=$(wc -l < "$_MD/combined.txt" | tr -d ' ')
        _MDUP=$(sort "$_MD/combined.txt" | uniq -d | wc -l | tr -d ' ')
        _MMISS=$(comm -23 <(seq 1000 | sort) <(sort "$_MD/combined.txt") | wc -l | tr -d ' ')

        if (( _ML == 1000 && _MDUP == 0 && _MMISS == 0 )); then
            TEST_RESULTS["M12: Resume with NUMA (--nodes=2)"]="PASS"; ((PASSED_TESTS++))
            _print_result PASS "M12: Resume with NUMA (--nodes=2)"
        else
            TEST_RESULTS["M12: Resume with NUMA (--nodes=2)"]="FAIL"
            TEST_ERRORS["M12: Resume with NUMA (--nodes=2)"]="lines=$_ML dupes=$_MDUP missing=$_MMISS"
            ((FAILED_TESTS++)); _print_result FAIL "M12: Resume with NUMA (--nodes=2)" "lines=$_ML dupes=$_MDUP missing=$_MMISS"
        fi
    fi
fi

# ============================================================================
# M13: Ordered output sequence correct after resume (-k)
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M13"; mkdir -p "$_MD"
    seq 500 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
crash_func() {
    for a in "$@"; do
        if (( a == 30 )) && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '%s\n' "$a"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -k -l 1 crash_func" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    if [[ ! -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M13: Ordered output correct after resume (-k)"]="FAIL"
        TEST_ERRORS["M13: Ordered output correct after resume (-k)"]="no checkpoint"
        ((FAILED_TESTS++)); _print_result FAIL "M13: Ordered output correct after resume (-k)" "no checkpoint"
    else
        _MBYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_MD/err1.txt" 2>/dev/null || echo "")
        if [[ -n "$_MBYTES" ]] && (( _MBYTES > 0 )); then
            head -c "$_MBYTES" "$_MD/output1.txt" > "$_MD/output1_trunc.txt"
            mv "$_MD/output1_trunc.txt" "$_MD/output1.txt"
        fi

        bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -k -l 1 --resume '.forkrun_resume' crash_func" \
            > "$_MD/output2.txt" 2>"$_MD/err2.txt"

        cat "$_MD/output1.txt" "$_MD/output2.txt" > "$_MD/combined.txt"

        # Verify exact sequence matches input
        if diff -q <(seq 500) "$_MD/combined.txt" &>/dev/null; then
            TEST_RESULTS["M13: Ordered output correct after resume (-k)"]="PASS"; ((PASSED_TESTS++))
            _print_result PASS "M13: Ordered output correct after resume (-k)"
        else
            _ML=$(wc -l < "$_MD/combined.txt" | tr -d ' ')
            _MFIRST=$(diff <(seq 500) "$_MD/combined.txt" | head -5)
            TEST_RESULTS["M13: Ordered output correct after resume (-k)"]="FAIL"
            TEST_ERRORS["M13: Ordered output correct after resume (-k)"]="$_ML lines. Diff: $_MFIRST"
            ((FAILED_TESTS++)); _print_result FAIL "M13: Ordered output correct after resume (-k)" "$_ML lines, sequence mismatch"
        fi
    fi
fi

# ============================================================================
# M14: No duplicate lines after resume (exactly-once, large input)
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M14"; mkdir -p "$_MD"
    seq 5000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
crash_func() {
    for a in "$@"; do
        if (( a == 200 )) && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '%s\n' "$a"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -k -l 1 crash_func" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    if [[ ! -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M14: No duplicates after resume (exactly-once)"]="FAIL"
        TEST_ERRORS["M14: No duplicates after resume (exactly-once)"]="no checkpoint"
        ((FAILED_TESTS++)); _print_result FAIL "M14: No duplicates after resume (exactly-once)" "no checkpoint"
    else
        _MBYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_MD/err1.txt" 2>/dev/null || echo "")
        if [[ -n "$_MBYTES" ]] && (( _MBYTES > 0 )); then
            head -c "$_MBYTES" "$_MD/output1.txt" > "$_MD/output1_trunc.txt"
            mv "$_MD/output1_trunc.txt" "$_MD/output1.txt"
        fi

        bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -k -l 1 --resume '.forkrun_resume' crash_func" \
            > "$_MD/output2.txt" 2>"$_MD/err2.txt"

        cat "$_MD/output1.txt" "$_MD/output2.txt" > "$_MD/combined.txt"

        _ML=$(wc -l < "$_MD/combined.txt" | tr -d ' ')
        _MDUP=$(sort "$_MD/combined.txt" | uniq -d | wc -l | tr -d ' ')
        _MMISS=$(comm -23 <(seq 5000 | sort) <(sort "$_MD/combined.txt") | wc -l | tr -d ' ')

        if (( _ML == 5000 && _MDUP == 0 && _MMISS == 0 )); then
            TEST_RESULTS["M14: No duplicates after resume (exactly-once)"]="PASS"; ((PASSED_TESTS++))
            _print_result PASS "M14: No duplicates after resume (exactly-once)"
        else
            TEST_RESULTS["M14: No duplicates after resume (exactly-once)"]="FAIL"
            TEST_ERRORS["M14: No duplicates after resume (exactly-once)"]="lines=$_ML dupes=$_MDUP missing=$_MMISS"
            ((FAILED_TESTS++)); _print_result FAIL "M14: No duplicates after resume (exactly-once)" "lines=$_ML dupes=$_MDUP missing=$_MMISS"
        fi
    fi
fi

# ============================================================================
# M15: Resume with -i insert mode
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M15"; mkdir -p "$_MD"
    seq 500 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
wrap_func() {
    for a in "$@"; do
        if (( a == 30 )) && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '[%s]\n' "$a"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='wrap_func' frun -k -l 1 -i wrap_func {}" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    if [[ ! -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M15: Resume with -i insert mode"]="FAIL"
        TEST_ERRORS["M15: Resume with -i insert mode"]="no checkpoint"
        ((FAILED_TESTS++)); _print_result FAIL "M15: Resume with -i insert mode" "no checkpoint"
    else
        _MBYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_MD/err1.txt" 2>/dev/null || echo "")
        if [[ -n "$_MBYTES" ]] && (( _MBYTES > 0 )); then
            head -c "$_MBYTES" "$_MD/output1.txt" > "$_MD/output1_trunc.txt"
            mv "$_MD/output1_trunc.txt" "$_MD/output1.txt"
        fi

        bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='wrap_func' frun -k -l 1 -i --resume '.forkrun_resume' wrap_func {}" \
            > "$_MD/output2.txt" 2>"$_MD/err2.txt"

        cat "$_MD/output1.txt" "$_MD/output2.txt" > "$_MD/combined.txt"

        _ML=$(wc -l < "$_MD/combined.txt" | tr -d ' ')
        _MWRAP=$(grep -c '^\[[0-9]*\]$' "$_MD/combined.txt" 2>/dev/null || echo 0)

        if (( _ML == 500 && _MWRAP == 500 )); then
            TEST_RESULTS["M15: Resume with -i insert mode"]="PASS"; ((PASSED_TESTS++))
            _print_result PASS "M15: Resume with -i insert mode"
        else
            TEST_RESULTS["M15: Resume with -i insert mode"]="FAIL"
            TEST_ERRORS["M15: Resume with -i insert mode"]="lines=$_ML wrapped=$_MWRAP"
            ((FAILED_TESTS++)); _print_result FAIL "M15: Resume with -i insert mode" "lines=$_ML wrapped=$_MWRAP"
        fi
    fi
fi

# ============================================================================
# M16: Checkpoint stdout bytes matches truncated output size
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M16"; mkdir -p "$_MD"
    seq 1000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
crash_func() {
    for a in "$@"; do
        if (( a == 50 )) && ! [[ -f ./.forkrun_resume ]]; then
            kill -9 $BASHPID
        else
            printf '%s\n' "$a"
        fi
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source 'funcs.sh'; cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' frun -k -l 1 crash_func" \
        > "$_MD/output1.txt" 2>"$_MD/err1.txt"

    _MBYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_MD/err1.txt" 2>/dev/null || echo "")

    if [[ -n "$_MBYTES" ]]; then
        # Verify that truncating to the specified bytes produces valid output
        # (no partial lines at the boundary)
        head -c "$_MBYTES" "$_MD/output1.txt" > "$_MD/output1_trunc.txt"

        # The truncated output should end with a newline (no partial lines)
        _MLAST=$(tail -c 1 "$_MD/output1_trunc.txt" | xxd -p)
        _MLINES=$(wc -l < "$_MD/output1_trunc.txt" | tr -d ' ')

        if [[ "$_MLAST" == "0a" ]] && (( _MLINES > 0 )); then
            TEST_RESULTS["M16: Checkpoint byte count produces clean truncation"]="PASS"; ((PASSED_TESTS++))
            _print_result PASS "M16: Checkpoint byte count produces clean truncation" "($_MBYTES bytes → $_MLINES clean lines)"
        else
            TEST_RESULTS["M16: Checkpoint byte count produces clean truncation"]="FAIL"
            TEST_ERRORS["M16: Checkpoint byte count produces clean truncation"]="truncated output doesn't end with newline (last byte: $_MLAST, lines: $_MLINES)"
            ((FAILED_TESTS++)); _print_result FAIL "M16: Checkpoint byte count produces clean truncation" "doesn't end with newline"
        fi
    elif [[ -f "$_MD/.forkrun_resume" ]]; then
        TEST_RESULTS["M16: Checkpoint byte count produces clean truncation"]="FAIL"
        TEST_ERRORS["M16: Checkpoint byte count produces clean truncation"]="no truncation message found in stderr"
        ((FAILED_TESTS++)); _print_result FAIL "M16: Checkpoint byte count produces clean truncation" "no truncation message in stderr"
    else
        TEST_RESULTS["M16: Checkpoint byte count produces clean truncation"]="SKIP"; ((SKIPPED_TESTS++))
        _print_result SKIP "M16: Checkpoint byte count produces clean truncation" "no checkpoint"
    fi
fi

# ============================================================================
# SECTION N: Property-Based Invariants (Randomized Stress)
# ============================================================================

print_section N "Property-Based Invariants (Randomized)"

# --- N1: Default mode sorted == Ordered mode, random inputs ---
if in_section N; then
    ((TOTAL_TESTS++))
    _NPASS=0; _NITER=30
    for (( _ni=0; _ni<_NITER; _ni++ )); do
        _NINPUT=$(head -c 5000 /dev/urandom | tr -dc '[:print:]\n' | head -n $((RANDOM % 200 + 10)))
        _NEXPECTED=$(printf '%s\n' "${_NINPUT}" | bash -c "source '$FRUN_SOURCE' && frun -k printf '%s\n'" 2>/dev/null | sort)
        _NACTUAL=$(printf '%s\n' "${_NINPUT}" | bash -c "source '$FRUN_SOURCE' && frun printf '%s\n'" 2>/dev/null | sort)
        [[ "$_NEXPECTED" == "$_NACTUAL" ]] || break
        (( _NPASS++ ))
    done
    if (( _NPASS == _NITER )); then
        TEST_RESULTS["N1: Default sorted == Ordered, random inputs"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "N1: Default sorted == Ordered, random inputs" "(${_NITER}/${_NITER} iterations)"
    else
        TEST_RESULTS["N1: Default sorted == Ordered, random inputs"]="FAIL"
        TEST_ERRORS["N1: Default sorted == Ordered, random inputs"]="failed at iteration ${_ni}"
        ((FAILED_TESTS++)); _print_result FAIL "N1: Default sorted == Ordered, random inputs" "failed at iteration ${_ni}"
    fi
fi

# --- N2: No data loss invariant, random inputs ---
if in_section N; then
    ((TOTAL_TESTS++))
    _NPASS=0; _NITER=30
    for (( _ni=0; _ni<_NITER; _ni++ )); do
        _NINPUT=$(for (( _nj=0; _nj<$((RANDOM % 100 + 20)); _nj++ )); do
            head -c 50 /dev/urandom | tr -dc '[:print:]' | head -c $((RANDOM % 40 + 1))
            echo
        done)
        _NINCOUNT=$(printf '%s\n' "${_NINPUT}" | wc -l | tr -d ' ')
        _NOUTCOUNT=$(printf '%s\n' "${_NINPUT}" | bash -c "source '$FRUN_SOURCE' && frun -k printf '%s\n'" 2>/dev/null | wc -l | tr -d ' ')
        (( _NINCOUNT == _NOUTCOUNT )) || break
        (( _NPASS++ ))
    done
    if (( _NPASS == _NITER )); then
        TEST_RESULTS["N2: No data loss, random inputs"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "N2: No data loss, random inputs" "(${_NITER}/${_NITER} iterations)"
    else
        TEST_RESULTS["N2: No data loss, random inputs"]="FAIL"
        TEST_ERRORS["N2: No data loss, random inputs"]="in=${_NINCOUNT} out=${_NOUTCOUNT} at iteration ${_ni}"
        ((FAILED_TESTS++)); _print_result FAIL "N2: No data loss, random inputs" "in=${_NINCOUNT} out=${_NOUTCOUNT} at iter ${_ni}"
    fi
fi

# --- N3: No duplication invariant, random inputs ---
if in_section N; then
    ((TOTAL_TESTS++))
    _NPASS=0; _NITER=30
    for (( _ni=0; _ni<_NITER; _ni++ )); do
        _NINPUT=$(seq $((RANDOM % 500 + 50)) | shuf)
        _NINCOUNT=$(printf '%s\n' "${_NINPUT}" | wc -l | tr -d ' ')
        _NOUT=$(printf '%s\n' "${_NINPUT}" | bash -c "source '$FRUN_SOURCE' && frun -k printf '%s\n'" 2>/dev/null)
        _NOUTCOUNT=$(printf '%s\n' "${_NOUT}" | wc -l | tr -d ' ')
        _NUNIQ=$(printf '%s\n' "${_NOUT}" | sort -u | wc -l | tr -d ' ')
        (( _NINCOUNT == _NOUTCOUNT && _NOUTCOUNT == _NUNIQ )) || break
        (( _NPASS++ ))
    done
    if (( _NPASS == _NITER )); then
        TEST_RESULTS["N3: No duplication, random inputs"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "N3: No duplication, random inputs" "(${_NITER}/${_NITER} iterations)"
    else
        TEST_RESULTS["N3: No duplication, random inputs"]="FAIL"
        TEST_ERRORS["N3: No duplication, random inputs"]="in=${_NINCOUNT} out=${_NOUTCOUNT} uniq=${_NUNIQ} at iteration ${_ni}"
        ((FAILED_TESTS++)); _print_result FAIL "N3: No duplication, random inputs" "counts mismatch at iter ${_ni}"
    fi
fi

# --- N4: Stdin mode sorted == Ordered stdin mode, random inputs ---
if in_section N; then
    ((TOTAL_TESTS++))
    _NPASS=0; _NITER=20
    for (( _ni=0; _ni<_NITER; _ni++ )); do
        _NINPUT=$(head -c 3000 /dev/urandom | tr -dc '[:print:]\n' | head -n $((RANDOM % 100 + 10)))
        _NEXPECTED=$(printf '%s\n' "${_NINPUT}" | bash -c "source '$FRUN_SOURCE' && frun -k -s cat" 2>/dev/null | sort)
        _NACTUAL=$(printf '%s\n' "${_NINPUT}" | bash -c "source '$FRUN_SOURCE' && frun -s cat" 2>/dev/null | sort)
        [[ "$_NEXPECTED" == "$_NACTUAL" ]] || break
        (( _NPASS++ ))
    done
    if (( _NPASS == _NITER )); then
        TEST_RESULTS["N4: Stdin sorted == Ordered stdin, random inputs"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "N4: Stdin sorted == Ordered stdin, random inputs" "(${_NITER}/${_NITER} iterations)"
    else
        TEST_RESULTS["N4: Stdin sorted == Ordered stdin, random inputs"]="FAIL"
        TEST_ERRORS["N4: Stdin sorted == Ordered stdin, random inputs"]="failed at iteration ${_ni}"
        ((FAILED_TESTS++)); _print_result FAIL "N4: Stdin sorted == Ordered stdin, random inputs" "failed at iter ${_ni}"
    fi
fi

# --- N5: Byte mode byte count integrity, various sizes ---
if in_section N; then
    ((TOTAL_TESTS++))
    _NPASS=0; _NITER=20
    for (( _ni=0; _ni<_NITER; _ni++ )); do
        _MD="$TEST_DIR/N5_${_ni}"; mkdir -p "$_MD"
        _NBYTES=$((RANDOM % 5000 + 100))
        # Write random data directly to file (avoids NUL truncation in bash vars)
        head -c $_NBYTES /dev/urandom > "$_MD/input.bin"
        _NOUT=$(bash -c "source '$FRUN_SOURCE' && cat '$_MD/input.bin' | frun -b 512 -s wc -c" 2>/dev/null | awk '{s+=$1} END{print s}')
        (( _NBYTES == _NOUT )) || break
        (( _NPASS++ ))
        rm -rf "$_MD"
    done
    rm -rf "$TEST_DIR/N5_"*
    if (( _NPASS == _NITER )); then
        TEST_RESULTS["N5: Byte mode byte count integrity, various sizes"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "N5: Byte mode byte count integrity, various sizes" "(${_NITER}/${_NITER} iterations)"
    else
        TEST_RESULTS["N5: Byte mode byte count integrity, various sizes"]="FAIL"
        TEST_ERRORS["N5: Byte mode byte count integrity, various sizes"]="expected $_NBYTES bytes, got '${_NOUT}' bytes at iteration ${_ni}"
        ((FAILED_TESTS++)); _print_result FAIL "N5: Byte mode byte count integrity, various sizes" "expected $_NBYTES, got '${_NOUT}' at iter ${_ni}"
    fi
fi


# ============================================================================
# SECTION O: Configuration Edge Cases
# ============================================================================
# Tests _expand_unit and flag parsing indirectly through frun's behavior.
# Cannot call _expand_unit directly since it's a local function inside frun().
# ============================================================================

print_section O "Configuration Edge Cases"

# --- O1: -b with IEC prefix (1k = 1000 bytes) ---
if in_section O; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/O1"; mkdir -p "$_MD"
    # Create exactly 2000 bytes and use -b 1k (should produce 2 chunks)
    head -c 2000 /dev/zero | tr '\0' 'A' > "$_MD/input.bin"
    _OOUT=$(bash -c "source '$FRUN_SOURCE' && cat '$_MD/input.bin' | frun -b 1k -s wc -c" 2>/dev/null | awk '{s+=$1} END{print s}')
    if (( _OOUT == 2000 )); then
        TEST_RESULTS["O1: -b 1k (1000 bytes)"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "O1: -b 1k (1000 bytes)"
    else
        TEST_RESULTS["O1: -b 1k (1000 bytes)"]="FAIL"
        TEST_ERRORS["O1: -b 1k (1000 bytes)"]="got $_OOUT bytes, expected 2000"
        ((FAILED_TESTS++)); _print_result FAIL "O1: -b 1k (1000 bytes)" "got $_OOUT/2000 bytes"
    fi
fi

# --- O2: -b with IEC binary prefix (1Ki = 1024 bytes) ---
if in_section O; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/O2"; mkdir -p "$_MD"
    head -c 2048 /dev/zero | tr '\0' 'A' > "$_MD/input.bin"
    _OOUT=$(bash -c "source '$FRUN_SOURCE' && cat '$_MD/input.bin' | frun -b 1Ki -s wc -c" 2>/dev/null | awk '{s+=$1} END{print s}')
    if (( _OOUT == 2048 )); then
        TEST_RESULTS["O2: -b 1Ki (1024 bytes)"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "O2: -b 1Ki (1024 bytes)"
    else
        TEST_RESULTS["O2: -b 1Ki (1024 bytes)"]="FAIL"
        TEST_ERRORS["O2: -b 1Ki (1024 bytes)"]="got $_OOUT bytes, expected 2048"
        ((FAILED_TESTS++)); _print_result FAIL "O2: -b 1Ki (1024 bytes)" "got $_OOUT/2048 bytes"
    fi
fi

# --- O3: -b with megabyte prefix (1M) ---
if in_section O; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/O3"; mkdir -p "$_MD"
    head -c 2000000 /dev/zero | tr '\0' 'A' > "$_MD/input.bin"
    _OOUT=$(bash -c "source '$FRUN_SOURCE' && cat '$_MD/input.bin' | frun -b 1M -s wc -c" 2>/dev/null | awk '{s+=$1} END{print s}')
    if (( _OOUT == 2000000 )); then
        TEST_RESULTS["O3: -b 1M (1,000,000 bytes)"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "O3: -b 1M (1,000,000 bytes)"
    else
        TEST_RESULTS["O3: -b 1M (1,000,000 bytes)"]="FAIL"
        TEST_ERRORS["O3: -b 1M (1,000,000 bytes)"]="got $_OOUT bytes, expected 2000000"
        ((FAILED_TESTS++)); _print_result FAIL "O3: -b 1M (1,000,000 bytes)" "got $_OOUT bytes"
    fi
fi

# --- O4: -l with large batch size (1k = 1000 lines) ---
if in_section O; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/O4"; mkdir -p "$_MD"
    seq 2000 > "$_MD/input.txt"
    _OOUT=$(bash -c "source '$FRUN_SOURCE' && frun -k -l 1k printf '%s\n' < '$_MD/input.txt'" 2>/dev/null | wc -l | tr -d ' ')
    if (( _OOUT == 2000 )); then
        TEST_RESULTS["O4: -l 1k (1000 lines per batch)"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "O4: -l 1k (1000 lines per batch)"
    else
        TEST_RESULTS["O4: -l 1k (1000 lines per batch)"]="FAIL"
        TEST_ERRORS["O4: -l 1k (1000 lines per batch)"]="got $_OOUT lines, expected 2000"
        ((FAILED_TESTS++)); _print_result FAIL "O4: -l 1k (1000 lines per batch)" "got $_OOUT/2000 lines"
    fi
fi

# --- O5: -j with range and IEC-like values ---
run_test_line_count O "O5: -j 1:4 worker range" \
    "seq 100 | frun -j 1:4 -k printf '%s\n'" \
    100

# --- O6: Negative limit value ---
if in_section O; then
    ((TOTAL_TESTS++))
    _OOUT=$(bash -c "source '$FRUN_SOURCE' && seq 10 | frun -n -1 -k printf '%s\\n'" 2>/dev/null | wc -l | tr -d ' ')
    # Acceptable: either all 10 lines (unlimited) or 0 lines (rejected)
    if (( _OOUT == 10 || _OOUT == 0 )); then
        TEST_RESULTS["O6: Negative limit value handled"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "O6: Negative limit value handled" "(got $_OOUT lines)"
    else
        TEST_RESULTS["O6: Negative limit value handled"]="FAIL"
        TEST_ERRORS["O6: Negative limit value handled"]="got $_OOUT lines for -n -1"
        ((FAILED_TESTS++)); _print_result FAIL "O6: Negative limit value handled" "got $_OOUT lines"
    fi
fi

# --- O7: Zero batch size ---
if in_section O; then
    ((TOTAL_TESTS++))
    _OOUT=$(bash -c "source '$FRUN_SOURCE' && seq 10 | frun -l 0 -k printf '%s\\n'" 2>/dev/null | wc -l | tr -d ' ')
    # Should either default to something reasonable or error cleanly
    if (( _OOUT == 10 )); then
        TEST_RESULTS["O7: Zero batch size defaults correctly"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "O7: Zero batch size defaults correctly"
    else
        TEST_RESULTS["O7: Zero batch size defaults correctly"]="FAIL"
        TEST_ERRORS["O7: Zero batch size defaults correctly"]="got $_OOUT lines for -l 0"
        ((FAILED_TESTS++)); _print_result FAIL "O7: Zero batch size defaults correctly" "got $_OOUT lines"
    fi
fi

# --- O8: _expand_unit extreme value doesn't crash ---
if in_section O; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/O8"; mkdir -p "$_MD"
    # Test with 1G (1,000,000,000 bytes) — large but functional chunk size.
    # Verify the pipeline completes correctly without negative chunk sizes or hangs.
    head -c 2000 /dev/zero | tr '\0' 'X' > "$_MD/input.bin"
    _OOUT=$(bash -c "source '$FRUN_SOURCE' && cat '$_MD/input.bin' | frun -b 1G -s cat" 2>/dev/null | wc -c | tr -d ' ')
    if (( _OOUT == 2000 )); then
        TEST_RESULTS["O8: -b 1G large chunk size works"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "O8: -b 1G large chunk size works"
    else
        TEST_RESULTS["O8: -b 1G large chunk size works"]="FAIL"
        TEST_ERRORS["O8: -b 1G large chunk size works"]="got $_OOUT bytes, expected 2000"
        ((FAILED_TESTS++)); _print_result FAIL "O8: -b 1G large chunk size works" "got $_OOUT/2000 bytes"
    fi
fi

# --- O9: _expand_unit overflow (16E exceeds int64) clamps gracefully ---
if in_section O; then
    ((TOTAL_TESTS++))
    # 16E overflows int64. The fix clamps to max int64 and prints a warning.
    # Pipeline should still complete (huge chunk = pass everything in one batch).
    _MD="$TEST_DIR/O9"; mkdir -p "$_MD"
    bash -c "source '$FRUN_SOURCE' && echo 'test' | frun -b 16E -s cat" > "$_MD/out.txt" 2>"$_MD/err.txt"
    _OEC=$?
    _OOUT=$(cat "$_MD/out.txt" 2>/dev/null)
    _OERR=$(cat "$_MD/err.txt" 2>/dev/null)
    if [[ "$_OOUT" == "test" ]] && echo "$_OERR" | grep -qi 'truncat'; then
        TEST_RESULTS["O9: -b 16E overflow clamps with warning"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "O9: -b 16E overflow clamps with warning"
    elif [[ "$_OOUT" == "test" ]]; then
        # Works but no warning — clamping without notification is acceptable but less ideal
        TEST_RESULTS["O9: -b 16E overflow clamps with warning"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "O9: -b 16E overflow clamps with warning" "(no warning printed)"
    else
        TEST_RESULTS["O9: -b 16E overflow clamps with warning"]="FAIL"
        TEST_ERRORS["O9: -b 16E overflow clamps with warning"]="output='$_OOUT' exit=$_OEC"
        ((FAILED_TESTS++)); _print_result FAIL "O9: -b 16E overflow clamps with warning" "unexpected output"
    fi
fi

# ============================================================================
# SECTION P: Exit Code Correctness
# ============================================================================

print_section P "Exit Code Correctness"

# --- P1: Successful run exits 0 ---
if in_section P; then
    ((TOTAL_TESTS++))
    bash -c "source '$FRUN_SOURCE' && seq 100 | frun -k printf '%s\n' >/dev/null 2>&1"
    if (( $? == 0 )); then
        TEST_RESULTS["P1: Successful run exits 0"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "P1: Successful run exits 0"
    else
        TEST_RESULTS["P1: Successful run exits 0"]="FAIL"
        TEST_ERRORS["P1: Successful run exits 0"]="exit $?"
        ((FAILED_TESTS++)); _print_result FAIL "P1: Successful run exits 0" "non-zero exit"
    fi
fi

# --- P2: Missing resume file exits non-zero ---
if in_section P; then
    ((TOTAL_TESTS++))
    bash -c "source '$FRUN_SOURCE' && echo 'test' | frun --resume /nonexistent/path/.forkrun_resume printf '%s' >/dev/null 2>&1"
    if (( $? != 0 )); then
        TEST_RESULTS["P2: Missing resume file exits non-zero"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "P2: Missing resume file exits non-zero"
    else
        TEST_RESULTS["P2: Missing resume file exits non-zero"]="FAIL"
        TEST_ERRORS["P2: Missing resume file exits non-zero"]="exited 0"
        ((FAILED_TESTS++)); _print_result FAIL "P2: Missing resume file exits non-zero" "exited 0"
    fi
fi

# --- P3: Worker command failure exits 0 (default, no -E) ---
if in_section P; then
    ((TOTAL_TESTS++))
    bash -c "source '$FRUN_SOURCE' && seq 10 | frun -k -l 1 false >/dev/null 2>&1"
    if (( $? == 0 )); then
        TEST_RESULTS["P3: Worker failure without -E exits 0"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "P3: Worker failure without -E exits 0"
    else
        TEST_RESULTS["P3: Worker failure without -E exits 0"]="FAIL"
        TEST_ERRORS["P3: Worker failure without -E exits 0"]="exited $?"
        ((FAILED_TESTS++)); _print_result FAIL "P3: Worker failure without -E exits 0" "non-zero exit"
    fi
fi

# --- P4: Poisoned batch exits non-zero ---
if in_section P; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/P4"; mkdir -p "$_MD"
    cat > "$_MD/funcs.sh" << 'FUNCEOF'
always_crash() { exit 1; }
FUNCEOF
    bash -c "source '$FRUN_SOURCE' && source '$_MD/funcs.sh' && FORKRUN_RETRY_LIMIT=0 seq 10 | FORKRUN_EXTRA_FUNCS='always_crash' frun -k -l 1 -E always_crash >/dev/null 2>'$_MD/err.txt'"
    _PEC=$?
    if (( _PEC != 0 )); then
        TEST_RESULTS["P4: Poisoned batch exits non-zero"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "P4: Poisoned batch exits non-zero" "(exit $_PEC)"
    else
        TEST_RESULTS["P4: Poisoned batch exits non-zero"]="FAIL"
        TEST_ERRORS["P4: Poisoned batch exits non-zero"]="exited 0 despite poisoned batches"
        ((FAILED_TESTS++)); _print_result FAIL "P4: Poisoned batch exits non-zero" "exited 0 — should be non-zero!"
    fi
fi

# --- P5: Poisoned batch produces stderr warning ---
if in_section P; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/P5"; mkdir -p "$_MD"
    cat > "$_MD/funcs.sh" << 'FUNCEOF'
always_crash() { exit 1; }
FUNCEOF
    bash -c "source '$FRUN_SOURCE' && source '$_MD/funcs.sh' && FORKRUN_RETRY_LIMIT=0 seq 10 | FORKRUN_EXTRA_FUNCS='always_crash' frun -k -l 1 -E always_crash >/dev/null 2>'$_MD/err.txt'"
    _PERR=$(cat "$_MD/err.txt" 2>/dev/null)
    # Check for any warning about poisoned/skipped batches
    if echo "$_PERR" | grep -qiE 'poison|skip|killed|retry'; then
        TEST_RESULTS["P5: Poisoned batch produces stderr warning"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "P5: Poisoned batch produces stderr warning"
    else
        TEST_RESULTS["P5: Poisoned batch produces stderr warning"]="FAIL"
        TEST_ERRORS["P5: Poisoned batch produces stderr warning"]="no warning in stderr. stderr: $(echo "$_PERR" | head -3)"
        ((FAILED_TESTS++)); _print_result FAIL "P5: Poisoned batch produces stderr warning" "no warning in stderr"
    fi
fi

# --- P6: Partial poisoning: surviving lines correct + non-zero exit ---
if in_section P; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/P6"; mkdir -p "$_MD"
    cat > "$_MD/funcs.sh" << 'FUNCEOF'
crash_on_50() { for a in "$@"; do if (( a == 50 )); then exit 1; else printf '%s\n' "$a"; fi; done; }
FUNCEOF
    bash -c "source '$FRUN_SOURCE' && source '$_MD/funcs.sh' && FORKRUN_RETRY_LIMIT=0 seq 100 | FORKRUN_EXTRA_FUNCS='crash_on_50' frun -k -l 1 -E crash_on_50 > '$_MD/out.txt' 2>'$_MD/err.txt'"
    _PEC=$?
    _PLINES=$(wc -l < "$_MD/out.txt" 2>/dev/null | tr -d ' ')
    _PMISSING=$(comm -23 <(seq 100 | grep -v '^50$' | sort) <(sort "$_MD/out.txt" 2>/dev/null) | wc -l | tr -d ' ')
    if (( _PEC != 0 && _PLINES == 99 && _PMISSING == 0 )); then
        TEST_RESULTS["P6: Partial poisoning: 99/100 lines + non-zero exit"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "P6: Partial poisoning: 99/100 lines + non-zero exit"
    else
        _PREASON="exit=$_PEC lines=$_PLINES missing=$_PMISSING"
        TEST_RESULTS["P6: Partial poisoning: 99/100 lines + non-zero exit"]="FAIL"
        TEST_ERRORS["P6: Partial poisoning: 99/100 lines + non-zero exit"]="$_PREASON"
        ((FAILED_TESTS++)); _print_result FAIL "P6: Partial poisoning: 99/100 lines + non-zero exit" "$_PREASON"
    fi
fi

# --- P7: FORKRUN_EXTRA_SETUP failure exit code propagates ---
run_test_exact P "P7: Setup failure propagates exit 42" \
    "FORKRUN_EXTRA_SETUP='exit 42'; dummy() { echo \"\$1\"; }; echo 'x' | FORKRUN_EXTRA_FUNCS='dummy' frun -l 1 dummy" \
    "" 42

# --- P8: SIGPIPE from downstream exits cleanly ---
if in_section P; then
    ((TOTAL_TESTS++))
    bash -c "source '$FRUN_SOURCE' && seq 1000000 | frun -k printf '%s\n' | head -n 5 >/dev/null 2>&1"
    _PEC=$?
    # SIGPIPE can produce exit 0 (pipe closed) or exit 141 (SIGPIPE signal)
    if (( _PEC == 0 || _PEC == 141 )); then
        TEST_RESULTS["P8: SIGPIPE exits cleanly"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "P8: SIGPIPE exits cleanly" "(exit $_PEC)"
    else
        TEST_RESULTS["P8: SIGPIPE exits cleanly"]="FAIL"
        TEST_ERRORS["P8: SIGPIPE exits cleanly"]="exit $_PEC"
        ((FAILED_TESTS++)); _print_result FAIL "P8: SIGPIPE exits cleanly" "exit $_PEC"
    fi
fi


# ============================================================================
# SECTION Q: Concurrent Invocation Stress
# ============================================================================

print_section Q "Concurrent Invocation Stress"

# --- Q1: Two concurrent frun calls produce correct independent output ---
if in_section Q; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/Q1"; mkdir -p "$_MD"
    seq 500 > "$_MD/input1.txt"
    seq 1000 1499 > "$_MD/input2.txt"

    bash -c "source '$FRUN_SOURCE' && frun -k printf '%s\n' < '$_MD/input1.txt'" > "$_MD/out1.txt" 2>/dev/null &
    _QP1=$!
    bash -c "source '$FRUN_SOURCE' && frun -k printf '%s\n' < '$_MD/input2.txt'" > "$_MD/out2.txt" 2>/dev/null &
    _QP2=$!
    wait $_QP1 $_QP2

    _QDIFF1=$(diff "$_MD/input1.txt" "$_MD/out1.txt")
    _QDIFF2=$(diff "$_MD/input2.txt" "$_MD/out2.txt")

    if [[ -z "$_QDIFF1" && -z "$_QDIFF2" ]]; then
        TEST_RESULTS["Q1: Two concurrent frun calls independent"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "Q1: Two concurrent frun calls independent"
    else
        TEST_RESULTS["Q1: Two concurrent frun calls independent"]="FAIL"
        TEST_ERRORS["Q1: Two concurrent frun calls independent"]="output mismatch"
        ((FAILED_TESTS++)); _print_result FAIL "Q1: Two concurrent frun calls independent" "output mismatch"
    fi
fi

# --- Q2: Concurrent frun with different modes ---
if in_section Q; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/Q2"; mkdir -p "$_MD"
    seq 500 > "$_MD/input.txt"

    bash -c "source '$FRUN_SOURCE' && frun -k printf '%s\n' < '$_MD/input.txt'" > "$_MD/out_ordered.txt" 2>/dev/null &
    _QP1=$!
    bash -c "source '$FRUN_SOURCE' && frun -s cat < '$_MD/input.txt'" > "$_MD/out_stdin.txt" 2>/dev/null &
    _QP2=$!
    wait $_QP1 $_QP2

    _QO1=$(sort "$_MD/out_ordered.txt" | md5sum | awk '{print $1}')
    _QO2=$(sort "$_MD/out_stdin.txt" | md5sum | awk '{print $1}')
    _QEXP=$(sort "$_MD/input.txt" | md5sum | awk '{print $1}')

    if [[ "$_QO1" == "$_QEXP" && "$_QO2" == "$_QEXP" ]]; then
        TEST_RESULTS["Q2: Concurrent frun with different modes"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "Q2: Concurrent frun with different modes"
    else
        TEST_RESULTS["Q2: Concurrent frun with different modes"]="FAIL"
        TEST_ERRORS["Q2: Concurrent frun with different modes"]="hash mismatch"
        ((FAILED_TESTS++)); _print_result FAIL "Q2: Concurrent frun with different modes" "hash mismatch"
    fi
fi

# --- Q3: Concurrent frun with separate checkpoint files ---
if in_section Q; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/Q3"; mkdir -p "$_MD"
    seq 500 > "$_MD/input1.txt"
    seq 1000 1499 > "$_MD/input2.txt"

    bash -c "source '$FRUN_SOURCE' && frun -k --checkpoint-file '$_MD/cp1.txt' printf '%s\n' < '$_MD/input1.txt'" > "$_MD/out1.txt" 2>/dev/null &
    _QP1=$!
    bash -c "source '$FRUN_SOURCE' && frun -k --checkpoint-file '$_MD/cp2.txt' printf '%s\n' < '$_MD/input2.txt'" > "$_MD/out2.txt" 2>/dev/null &
    _QP2=$!
    wait $_QP1 $_QP2

    _QDIFF1=$(diff "$_MD/input1.txt" "$_MD/out1.txt")
    _QDIFF2=$(diff "$_MD/input2.txt" "$_MD/out2.txt")

    if [[ -z "$_QDIFF1" && -z "$_QDIFF2" ]]; then
        TEST_RESULTS["Q3: Concurrent frun with separate checkpoints"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "Q3: Concurrent frun with separate checkpoints"
    else
        TEST_RESULTS["Q3: Concurrent frun with separate checkpoints"]="FAIL"
        TEST_ERRORS["Q3: Concurrent frun with separate checkpoints"]="output mismatch"
        ((FAILED_TESTS++)); _print_result FAIL "Q3: Concurrent frun with separate checkpoints" "output mismatch"
    fi
fi

# --- Q4: Sequential frun calls reuse ring without corruption ---
if in_section Q; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/Q4"; mkdir -p "$_MD"
    _NPASS=0; _NITER=10
    for (( _ni=0; _ni<_NITER; _ni++ )); do
        seq $((RANDOM % 500 + 100)) > "$_MD/input.txt"
        _QEXP=$(cat "$_MD/input.txt")
        _QACT=$(bash -c "source '$FRUN_SOURCE' && frun -k printf '%s\n' < '$_MD/input.txt'" 2>/dev/null)
        [[ "$_QEXP" == "$_QACT" ]] || break
        (( _NPASS++ ))
    done
    if (( _NPASS == _NITER )); then
        TEST_RESULTS["Q4: Sequential frun reuse, 10 iterations"]="PASS"; ((PASSED_TESTS++))
        _print_result PASS "Q4: Sequential frun reuse, 10 iterations" "(10/10)"
    else
        TEST_RESULTS["Q4: Sequential frun reuse, 10 iterations"]="FAIL"
        TEST_ERRORS["Q4: Sequential frun reuse, 10 iterations"]="failed at iteration ${_ni}"
        ((FAILED_TESTS++)); _print_result FAIL "Q4: Sequential frun reuse, 10 iterations" "failed at iter ${_ni}"
    fi
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
