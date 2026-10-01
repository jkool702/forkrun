#!/bin/bash
TEST_DIR=/tmp/m9only
FRUN_SOURCE=/mnt/ramdisk/forkrun/frun.bash
TOTAL_TESTS=0; PASSED_TESTS=0; FAILED_TESTS=0; SKIPPED_TESTS=0
declare -A TEST_RESULTS TEST_ERRORS
in_section() { return 0; }
_print_result() { echo "RESULT $1 $2 $3"; }
rm -rf "$TEST_DIR"; mkdir -p "$TEST_DIR"
# M9: Resume preserves FORKRUN_EXTRA_VARS
# ============================================================================
if in_section M; then
    ((TOTAL_TESTS++))
    _MD="$TEST_DIR/resume_M9"; mkdir -p "$_MD"
    seq 1000 > "$_MD/input.txt"; rm -f "$_MD/.forkrun_resume"

    cat > "$_MD/funcs.sh" << 'FUNCEOF'
label_func() {
    for a in "$@"; do
            for ((j=0;j<2000;j++)); do :; done  # W-PY28: stretch runtime for size-gated HUP (worker deaths now recover instead of aborting)
            printf '%s\n' "${MY_LABEL}:${a}"
    done
}
FUNCEOF

    bash -c "cd '$_MD'; source '$FRUN_SOURCE'; source funcs.sh; rm -f .hup_ready; cat input.txt | FORKRUN_EXTRA_FUNCS='label_func' FORKRUN_EXTRA_VARS='MY_LABEL' FORKRUN_TEST_CLEANROOM_PIDFILE='.hup_ready' frun -k -l 1 label_func > output1.txt 2>err1.txt & _hup_pid=\$!; for _i in \$(seq 1 100); do [[ -s .hup_ready ]] && break; sleep 0.2; done; _THRESH=100; for _j in \$(seq 1 500); do _sz=\$(stat -c %s output1.txt 2>/dev/null || echo 0); (( _sz >= _THRESH )) && break; sleep 0.2; done; kill -HUP \$(cat .hup_ready); wait \$_hup_pid; true" \
        > /dev/null 2>&1

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
echo M9ONLY-DONE