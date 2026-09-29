#!/usr/bin/env bash
# ============================================================================
# FORKRUN SECURITY + INPUT-GATE TEST SUITE (W-REL6 Wave 1)
# ============================================================================
# Covers the four verified Wave-1 findings with lock-in tests:
#   S-series (1.1): resume provenance gate fires in BOTH invocation forms
#                   (bare `frun --resume FILE` and `--resume FILE` with
#                   extra args). Previously all three layers sat inside
#                   `if (( $# == 1 ))` and any extra argument skipped them.
#   O-series (1.2): leading-zero numerics (-j 00, -j 08, ...) fail closed
#                   instead of silent data loss / mid-pipeline octal abort.
#   C-series (1.3): crash message emits --resume BEFORE the command; the
#                   emitted instruction is followed verbatim and the
#                   resumed output is byte-exact.
#   R-series (1.4): no RETURN-trap leak into the caller after frun exits.
#
# Repetition counts per the work order: S x10, O x5, R x5, C x1 (each C
# iteration needs a fresh crash; M4 covers resume correctness broadly).
# No /dev/tty is required: reject paths assert the no-TTY fail-closed
# abort, accept paths use clean files or FORKRUN_TRUST_RESUME=1.
# ============================================================================

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
declare -A TEST_RESULTS
declare -A TEST_ERRORS

TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT

FRUN_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/frun.bash"
if [[ ! -f "$FRUN_SOURCE" ]]; then
  echo -e "${RED}ERROR: frun.bash not found at $FRUN_SOURCE${NC}"
  exit 1
fi

pass() { TEST_RESULTS["$1"]="PASS"; ((PASSED_TESTS++)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() { TEST_RESULTS["$1"]="FAIL"; TEST_ERRORS["$1"]="$2"; ((FAILED_TESTS++)); echo -e "  ${RED}✗${NC} $1${RED} $2${NC}"; }

echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}${BOLD}  FORKRUN SECURITY + INPUT-GATE SUITE (W-REL6)${NC}"
echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ---------------------------------------------------------------- fixtures --
printf 'line1\nline2\nline3\n' > "$TEST_DIR/in.txt"

# Synthetic checkpoint with valid coordinate keys, world-writable.
printf 'FORKRUN_RESUME_HORIZON=1\nFORKRUN_RESUME_STDOUT_BYTES=6\n' > "$TEST_DIR/ck.bad"
chmod 666 "$TEST_DIR/ck.bad"

# Same content, owner-only perms (accepted).
# NOTE: resume-from-start coordinates (HORIZON=0/STDOUT_BYTES=0), so the
# accept runs below can assert byte-exact full output. ck.bad keeps
# nonzero coordinates to prove the gate fires before any engine use.
printf 'FORKRUN_RESUME_HORIZON=0\nFORKRUN_RESUME_STDOUT_BYTES=0\n' > "$TEST_DIR/ck.good"
chmod 600 "$TEST_DIR/ck.good"

# Bare-form fixtures carry ORIG_ARGS like real checkpoints (a bare resume
# with no restorable command has no defined completion; the gate decision
# is what these assert). ck.real0600 is accepted, ck.real0666 is not.
cat > "$TEST_DIR/ck.real0600" <<'CKEOF'
FORKRUN_RESUME_HORIZON=0
FORKRUN_RESUME_STDOUT_BYTES=0
declare -a FORKRUN_ORIG_ARGS=([0]="-j1" [1]="-l1" [2]="printf" [3]="%s\n")
CKEOF
chmod 600 "$TEST_DIR/ck.real0600"
cp "$TEST_DIR/ck.real0600" "$TEST_DIR/ck.real0666"
chmod 666 "$TEST_DIR/ck.real0666"

# ------------------------------------------------- S1: bare + bad -> reject --
echo -e "${BLUE}${BOLD}▶ S1: bare --resume on world-writable checkpoint is rejected (x10)${NC}"
for i in $(seq 1 10); do
  ((TOTAL_TESTS++))
  out=$(bash -c "source '$FRUN_SOURCE'; frun --resume '$TEST_DIR/ck.bad' < '$TEST_DIR/in.txt' >/dev/null 2>'$TEST_DIR/e.txt'; echo \$?" 2>/dev/null)
  if [[ "$out" == "1" ]] && grep -q "SECURITY" "$TEST_DIR/e.txt" && grep -q "group/world-writable" "$TEST_DIR/e.txt"; then
    pass "S1[$i]: bare world-writable rejected rc=1 SECURITY"
  else
    fail "S1[$i]: bare world-writable rejected rc=1 SECURITY" "rc=$out stderr=$(head -c 200 "$TEST_DIR/e.txt")"
  fi
done

# -------------------------------------------- S2: with-args + bad -> reject --
echo -e "${BLUE}${BOLD}▶ S2: --resume + args on world-writable checkpoint is rejected (x10)${NC}"
for i in $(seq 1 10); do
  ((TOTAL_TESTS++))
  out=$(bash -c "source '$FRUN_SOURCE'; printf 'a\nb\nc\n' | frun --resume '$TEST_DIR/ck.bad' -j2 -l2 printf '%s\n' >/dev/null 2>'$TEST_DIR/e.txt'; echo \$?" 2>/dev/null)
  if [[ "$out" == "1" ]] && grep -q "SECURITY" "$TEST_DIR/e.txt" && grep -q "group/world-writable" "$TEST_DIR/e.txt"; then
    pass "S2[$i]: with-args world-writable rejected rc=1 SECURITY"
  else
    fail "S2[$i]: with-args world-writable rejected rc=1 SECURITY" "rc=$out stderr=$(head -c 200 "$TEST_DIR/e.txt")"
  fi
done

# --------------------------------------------- S3: with-args + good -> accept --
echo -e "${BLUE}${BOLD}▶ S3: --resume + args on owned checkpoint runs correctly (x10)${NC}"
for i in $(seq 1 10); do
  ((TOTAL_TESTS++))
  out=$(bash -c "source '$FRUN_SOURCE'; frun --resume '$TEST_DIR/ck.good' -j2 -l2 printf '%s\n' < '$TEST_DIR/in.txt' 2>'$TEST_DIR/e.txt'; echo \"rc=\$?\"" 2>/dev/null)
  rc=$(grep -oP '^rc=\K[0-9]+' <<<"$out" | tail -1)
  body=$(grep -v '^rc=' <<<"$out")
  # NOTE: -j2 without -k is unordered; compare sorted.
  if [[ "$rc" == "0" ]] && [[ "$(sort <<<"$body")" == "$(sort "$TEST_DIR/in.txt")" ]] && ! grep -q "SECURITY" "$TEST_DIR/e.txt"; then
    pass "S3[$i]: with-args owned checkpoint accepted, output exact"
  else
    fail "S3[$i]: with-args owned checkpoint accepted, output exact" "rc=$rc body=$(head -c 120 <<<"$body")"
  fi
done

# --------------------------------------- S4: with-args + bad + TRUST -> accept --
echo -e "${BLUE}${BOLD}▶ S4: FORKRUN_TRUST_RESUME=1 overrides the with-args gate (x10)${NC}"
for i in $(seq 1 10); do
  ((TOTAL_TESTS++))
  out=$(bash -c "source '$FRUN_SOURCE'; FORKRUN_TRUST_RESUME=1 frun --resume '$TEST_DIR/ck.bad' -j2 -l2 printf '%s\n' < '$TEST_DIR/in.txt' 2>'$TEST_DIR/e.txt'; echo \"rc=\$?\"" 2>/dev/null)
  rc=$(grep -oP '^rc=\K[0-9]+' <<<"$out" | tail -1)
  if [[ "$rc" == "0" ]] && ! grep -q "SECURITY" "$TEST_DIR/e.txt"; then
    pass "S4[$i]: TRUST=1 with-args override runs rc=0"
  else
    fail "S4[$i]: TRUST=1 with-args override runs rc=0" "rc=$rc stderr=$(head -c 200 "$TEST_DIR/e.txt")"
  fi
done

# --------------------------------------------- S5: bare + good(ORIG_ARGS) -> accept --
echo -e "${BLUE}${BOLD}▶ S5: bare --resume on owned checkpoint passes the gate (x10)${NC}"
for i in $(seq 1 10); do
  ((TOTAL_TESTS++))
  out=$(bash -c "source '$FRUN_SOURCE'; frun --resume '$TEST_DIR/ck.real0600' < '$TEST_DIR/in.txt' >/dev/null 2>'$TEST_DIR/e.txt'; echo \$?" 2>/dev/null)
  if [[ "$out" == "0" ]] && ! grep -q "SECURITY" "$TEST_DIR/e.txt" && ! grep -q "ABORT" "$TEST_DIR/e.txt"; then
    pass "S5[$i]: bare owned checkpoint passes gate rc=0"
  else
    fail "S5[$i]: bare owned checkpoint passes gate rc=0" "rc=$out stderr=$(head -c 200 "$TEST_DIR/e.txt")"
  fi
done

# --------------------------------------- S6: bare + bad(ORIG_ARGS) + TRUST -> accept --
echo -e "${BLUE}${BOLD}▶ S6: FORKRUN_TRUST_RESUME=1 overrides the bare gate (x10)${NC}"
for i in $(seq 1 10); do
  ((TOTAL_TESTS++))
  out=$(bash -c "source '$FRUN_SOURCE'; FORKRUN_TRUST_RESUME=1 frun --resume '$TEST_DIR/ck.real0666' < '$TEST_DIR/in.txt' >/dev/null 2>'$TEST_DIR/e.txt'; echo \$?" 2>/dev/null)
  if [[ "$out" == "0" ]] && ! grep -q "SECURITY" "$TEST_DIR/e.txt"; then
    pass "S6[$i]: TRUST=1 bare override runs rc=0"
  else
    fail "S6[$i]: TRUST=1 bare override runs rc=0" "rc=$out stderr=$(head -c 200 "$TEST_DIR/e.txt")"
  fi
done

# --------------------------------------- S7: bare + bad(ORIG_ARGS), no trust -> reject --
echo -e "${BLUE}${BOLD}▶ S7: bare --resume on world-writable checkpoint w/ ORIG_ARGS is rejected (x10)${NC}"
for i in $(seq 1 10); do
  ((TOTAL_TESTS++))
  out=$(bash -c "source '$FRUN_SOURCE'; frun --resume '$TEST_DIR/ck.real0666' < '$TEST_DIR/in.txt' >/dev/null 2>'$TEST_DIR/e.txt'; echo \$?" 2>/dev/null)
  if [[ "$out" == "1" ]] && grep -q "SECURITY" "$TEST_DIR/e.txt"; then
    pass "S7[$i]: bare world-writable w/ ORIG_ARGS rejected rc=1 SECURITY"
  else
    fail "S7[$i]: bare world-writable w/ ORIG_ARGS rejected rc=1 SECURITY" "rc=$out stderr=$(head -c 200 "$TEST_DIR/e.txt")"
  fi
done

# ------------------------------------------------- O: leading-zero refusal --
echo -e "${BLUE}${BOLD}▶ O: leading-zero numerics fail closed with a clear error (x5 each)${NC}"
_O_SPECS=("-j 00" "-j 000" "-j 010" "-j 08" "-l 08")
_O_IDX=0
for spec in "${_O_SPECS[@]}"; do
  ((_O_IDX++))
  for i in $(seq 1 5); do
    ((TOTAL_TESTS++))
    out=$(bash -c "source '$FRUN_SOURCE'; printf 'a\nb\n' | frun $spec printf '%s\n' >'$TEST_DIR/o.txt' 2>'$TEST_DIR/e.txt'; echo \"rc=\$? lines=\$(wc -l < '$TEST_DIR/o.txt')\"" 2>/dev/null)
    if [[ "$out" == "rc=1 lines=0" ]] && grep -q "leading zeros are refused" "$TEST_DIR/e.txt"; then
      pass "O${_O_IDX}[$i]: '$spec' refused rc=1, no output"
    else
      fail "O${_O_IDX}[$i]: '$spec' refused rc=1, no output" "got=$out stderr=$(head -c 160 "$TEST_DIR/e.txt")"
    fi
  done
done

# ------------------------------------------------- R: RETURN-trap hygiene --
echo -e "${BLUE}${BOLD}▶ R: no RETURN-trap leak after frun exits (x5)${NC}"
printf 'myhelper() { :; }\n' > "$TEST_DIR/lib.sh"
for i in $(seq 1 5); do
  ((TOTAL_TESTS++))
  out=$(bash -c "
    set -u
    source '$FRUN_SOURCE'
    frun -j1 printf '%s\n' < '$TEST_DIR/in.txt' >'$TEST_DIR/r.txt' 2>'$TEST_DIR/e.txt'
    echo \"frun-rc=\$?\"
    trap -p RETURN
    source '$TEST_DIR/lib.sh' 2>'$TEST_DIR/e2.txt'
    echo \"source-rc=\$?\"
    myhelper
    echo \"helper-rc=\$?\"
  " 2>&1)
  if grep -q "frun-rc=0" <<<"$out" && grep -q "source-rc=0" <<<"$out" && grep -q "helper-rc=0" <<<"$out" \
     && ! grep -q "trap -- .*RETURN" <<<"$out" && ! grep -q "unbound variable" "$TEST_DIR/e2.txt" \
     && [[ "$(cat "$TEST_DIR/r.txt")" == "$(cat "$TEST_DIR/in.txt")" ]]; then
    pass "R[$i]: trap clean, sourcing under set -u survives, output exact"
  else
    fail "R[$i]: trap clean, sourcing under set -u survives, output exact" "got=$(head -c 300 <<<"$out")"
  fi
done

# ------------------------------------------------- C: crash instruction ----
echo -e "${BLUE}${BOLD}▶ C: crash message instruction, followed verbatim, resumes exactly (x1)${NC}"
((TOTAL_TESTS++))
_CMD="$TEST_DIR/crash"; mkdir -p "$_CMD"
seq 1000 > "$_CMD/input.txt"; rm -f "$_CMD/.forkrun_resume" "$_CMD/.hup_ready"
cat > "$_CMD/funcs.sh" <<'FUNCEOF'
crash_func() {
    for a in "$@"; do
            for ((j=0;j<2000;j++)); do :; done
            printf '%s\n' "$a"
    done
}
FUNCEOF
bash -c "
  cd '$_CMD'
  source '$FRUN_SOURCE'
  source funcs.sh
  rm -f .hup_ready
  cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' FORKRUN_TEST_CLEANROOM_PIDFILE='.hup_ready' frun -k -l 1 crash_func > output1.txt 2>err1.txt &
  _hp=\$!
  for _i in \$(seq 1 100); do [[ -s .hup_ready ]] && break; sleep 0.2; done
  for _j in \$(seq 1 500); do _sz=\$(stat -c %s output1.txt 2>/dev/null || echo 0); (( _sz >= 100 )) && break; sleep 0.2; done
  kill -HUP \$(cat .hup_ready)
  wait \$_hp
  true
" >/dev/null 2>&1
if [[ -f "$_CMD/.forkrun_resume" ]]; then
  _HINT=$(grep -oP '^\s+frun --resume .*$' "$_CMD/err1.txt" | sed 's/^ *//')
  _BYTES=$(grep -oP 'truncate your output file to exactly \K[0-9]+' "$_CMD/err1.txt" || echo "")
  if [[ -n "$_HINT" ]] && [[ "$_HINT" == frun\ --resume\ * ]] && [[ -n "$_BYTES" ]] && (( _BYTES > 0 )); then
    head -c "$_BYTES" "$_CMD/output1.txt" > "$_CMD/output1_trunc.txt"
    mv "$_CMD/output1_trunc.txt" "$_CMD/output1.txt"
    # Follow the emitted instruction verbatim (stdin re-fed as in M4).
    bash -c "
      cd '$_CMD'
      source '$FRUN_SOURCE'
      source funcs.sh
      cat input.txt | FORKRUN_EXTRA_FUNCS='crash_func' $_HINT > output2.txt 2>err2.txt
      echo \$?
    " > "$_CMD/resume_rc.txt" 2>&1
    cat "$_CMD/output1.txt" "$_CMD/output2.txt" > "$_CMD/combined.txt"
    if [[ "$(cat "$_CMD/resume_rc.txt")" == "0" ]] && diff -q <(seq 1000) "$_CMD/combined.txt" >/dev/null 2>&1; then
      pass "C[1]: verbatim hint resumes to byte-exact output"
    else
      fail "C[1]: verbatim hint resumes to byte-exact output" "resume-rc=$(cat "$_CMD/resume_rc.txt") hint=[$_HINT]"
    fi
  else
    fail "C[1]: verbatim hint resumes to byte-exact output" "no parseable pre-command hint (hint=[$_HINT] bytes=[$_BYTES])"
  fi
else
  fail "C[1]: verbatim hint resumes to byte-exact output" "crash produced no checkpoint"
fi

# ------------------------------------------------------------------ summary --
echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}TEST SUMMARY${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
printf "Total:  %3d\n" "$TOTAL_TESTS"
printf "Passed: %3d\n" "$PASSED_TESTS"
printf "Failed: %3d\n" "$FAILED_TESTS"
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
