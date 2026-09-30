#!/usr/bin/env bash
# epyc/30_utest_bash_fast.sh — the fast bash correctness suites.
#
#   bash epyc/30_utest_bash_fast.sh
#
# Deliberately NOT using UNIT_TESTS/test_all.sh. That script has no `set -e`
# and no exit-code aggregation, so its status is that of the LAST suite alone
# (test_frun_security.sh) — a totally broken C-plugin build still exits 0. It
# also omits the three newest suites (raw, stdin, config). We call every suite
# ourselves and aggregate.
#
# Every suite runs in the FOREGROUND. This is a hard requirement, not a style
# choice: a backgrounded shell starts with SIGINT ignored, bash cannot
# un-ignore an entry-ignored signal, and the ignore inherits down to frun — so
# backgrounded signal tests silently no-op instead of testing (see the
# M1a comment in .github/workflows/bash-suite.yml and PRIMER §4.3).

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

OUTD="$EPYC_OUT/10_utests/bash_fast"
mkdir -p "$OUTD"
cd "$EPYC_ROOT/UNIT_TESTS" || die "no UNIT_TESTS dir"

RC=0

# The bash suites resolve frun.bash relative to their own directory, and
# UNIT_TESTS/frun.bash is a symlink to ../frun.bash. No override needed.
SUITES=(
    "test_frun.sh"
    "test_frun_security.sh"
    "test_c_plugins.sh"
    "test_c_plugins_v2.sh"
    "test_c_plugins_rigorous.sh"
    "test_c_plugins_raw.sh"
    "test_c_plugins_stdin.sh"
    "test_c_plugins_config.sh"
)

banner "30 bash correctness suites (${#SUITES[@]} suites, foreground)"

for s in "${SUITES[@]}"; do
    if [ ! -f "$s" ]; then
        err "$s not found — skipping"
        RC=1
        continue
    fi
    banner "30 :: $s"
    if run_logged "$OUTD/$s.log" "$s" bash "./$s"; then
        report_tally "$OUTD/$s.log" "$s"
    else
        err "$s FAILED (rc != 0) — see $OUTD/$s.log"
        report_tally "$OUTD/$s.log" "$s"
        RC=1
    fi
done

# --- version pin check -------------------------------------------------------
# test_frun.sh and test_frun_comprehensive.sh both hard-require the literal
# string "forkrun v3.6.0" and FATAL-abort otherwise. If this rental was staged
# from a tree whose META moved, every suite would die on a version check and we
# would bill hours diagnosing a non-problem.
META_V=$(awk '/^VERSION:/{print $2}' "$EPYC_ROOT/META" 2>/dev/null)
RING_V=$(bash -c 'source "'"$EPYC_ROOT"'/frun.bash" 2>/dev/null && ring_version' 2>/dev/null)
FRUN_V=$(bash -c 'source "'"$EPYC_ROOT"'/frun.bash" 2>/dev/null && frun -V' 2>/dev/null)
{
    echo "META VERSION      : ${META_V:-?}"
    echo "ring_version      : ${RING_V:-?}"
    echo "frun -V           : ${FRUN_V:-?}"
} | tee -a "$EPYC_OUT/00_environment/engine_version.txt"
log "engine reports: $RING_V / $FRUN_V (META says ${META_V:-?})"

# --- summary -----------------------------------------------------------------
{
    echo
    echo "=== bash fast-suite tallies ==="
    cat "$EPYC_OUT/TEST_TALLIES.txt" 2>/dev/null
} | tee -a "$OUTD/summary.txt"

# Count failing suites. `grep -c` PRINTS the count but EXITS 1 when there are
# no matches, so the `$(grep -c ... || echo 0)` idiom emits two lines ("0" and
# "0") and poisons any arithmetic on the result. Inside a command substitution
# the non-zero exit is harmless — just do not append a fallback.
FAILED_SUITES=$(grep -c 'FAILED' "$OUTD/summary.txt" 2>/dev/null)
FAILED_SUITES=${FAILED_SUITES:-0}
case "$FAILED_SUITES" in (*[!0-9]*|"") FAILED_SUITES=0 ;; esac
log "suites reporting a failure: $FAILED_SUITES"
if [ "$RC" -ne 0 ]; then
    banner "30 bash suites COMPLETED WITH FAILURES (rc=$RC)"
    err "grep for '✗' / 'FAILED' in $OUTD/*.log"
    exit 1
fi
banner "30 bash suites ALL GREEN"
exit 0
