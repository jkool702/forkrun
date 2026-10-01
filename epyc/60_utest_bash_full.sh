#!/usr/bin/env bash
# epyc/60_utest_bash_full.sh — test_frun_comprehensive.sh, un-timeboxed.
#
#   bash epyc/60_utest_bash_full.sh
#
# 264 tests across 21 lettered sections, including the chaos paths:
#   L  Fault resilience: escrow, poison, self-healing
#   M  Checkpoint & resume (the largest section, ~1100 lines)
#   T13 a 3-second background loop SIGKILLing ~30% of worker subshells
#   R14 symlink-planting against the checkpoint publisher
#   Q  concurrent invocation stress
#
# This is the longest-running suite in the repo (CI allows 120 minutes and marks
# it continue-on-error over known timing flakes: C-drain framing,
# reactor-ingest multiset, T10b, M8 HUP-window). It is deliberately scheduled
# LAST so that a slow box costs us the least valuable hours, and deliberately
# NOT time-boxed per the owner's instruction: a truncated checkpoint/resume
# section is worth nothing.
#
# FOREGROUND. Same hard requirement as the fast suites — a backgrounded shell
# inherits SIGINT-ignored down into frun, so backgrounded signal tests silently
# no-op (M1a).
#
# It also serves as a final "was the box still healthy at hour N" signal: if the
# last thing that runs on the rental goes green, nothing the benchmarks did
# earlier destabilised the machine.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

OUTD="$EPYC_OUT/10_utests/bash_full"
mkdir -p "$OUTD"
cd "$EPYC_ROOT/UNIT_TESTS" || die "no UNIT_TESTS dir"

banner "60 test_frun_comprehensive.sh (264 tests, un-timeboxed, foreground)"
log "CI gives this suite a 120-minute timeout and marks it advisory over known"
log "timing flakes (C-drain framing, reactor-ingest multiset, T10b, M8 HUP-window)."
log "A red here is triaged, not necessarily a defect on this hardware."

# Make sure the engine is definitely present before spending an hour on it.
bash -c 'source "'"$EPYC_ROOT"'/frun.bash" && ring_version >/dev/null' \
    || die "frun.bash did not load — run epyc/10_setup.sh"

if run_logged "$OUTD/comprehensive.log" "test_frun_comprehensive" bash ./test_frun_comprehensive.sh; then
    RC=0
else
    RC=$?
fi

banner "60 comprehensive suite analysis"
TRIAGE="$OUTD/triage.md"
{
    echo "# test_frun_comprehensive.sh triage — $EPYC_NPROC logical / $EPYC_PHYS physical cores,"
    echo "# $EPYC_NODES NUMA nodes, $(date -u '+%FT%TZ')"
    echo
    echo "Reference run (dev/supervisor/FAKE4_REVERIFY.md §4): **264/264 rc=0** on a"
    echo "28-thread i9-7940X booted \`numa=fake=4\` (4 nodes, distance 10)."
    echo "That is the shape of comparison available: not a rate, a pass/fail count."
    echo
    echo "**Known timing-sensitive tests** (named in .github/workflows/bash-suite.yml):"
    echo "  C-drain framing | reactor-ingest multiset | T10b | M8 HUP-window"
    echo "  A red in exactly these is expected noise, not a hardware finding."
    echo
    echo "## self-reported tally"
    grep -aE 'Total:|Passed:|Failed:|Skipped:|ALL TESTS PASSED|OVERALL' "$OUTD/comprehensive.log" | tail -8 | sed 's/^/  /'
    echo
    echo "## failed test names (from the FAILED TESTS block, if any)"
    if grep -aq 'FAILED TESTS' "$OUTD/comprehensive.log"; then
        sed -n '/FAILED TESTS/,/OVERALL/p' "$OUTD/comprehensive.log" | sed 's/^/  /'
    else
        echo "  (no FAILED TESTS block — the suite reported success)"
    fi
    echo
    echo "## section tallies"
    for sec in A B C C2 D E F G H I J K L M N O P Q R T T2; do
        pass=$(grep -acE "▶ .*\b$sec\b.*" "$OUTD/comprehensive.log" 2>/dev/null || true)
        [ -n "$pass" ] && printf '  section %-3s appeared in %s banner line(s)\n' "$sec" "$pass"
    done
    echo
    echo "## failure signature scan"
    for sig in 'drain-audit' 'mismatch' 'INCOMPLETE' 'lost' 'duplicate' 'scan failed (status 9)' 'checkpoint'; do
        n=$(grep -aic "$sig" "$OUTD/comprehensive.log" 2>/dev/null || echo 0)
        [ "$n" != "0" ] && printf '  %-26s %s occurrence(s)\n' "$sig" "$n"
    done
    echo "  (drain-audit and 'scan failed (status 9)' are the two signatures that"
    echo "   would indicate a real multi-node finding rather than test noise)"
} | tee "$TRIAGE"

if [ "$RC" -ne 0 ]; then
    banner "60 comprehensive suite FAILED (rc=$RC)"
    warn "triage: $TRIAGE"
    warn "If the only reds are the four known timing flakes above, this is expected."
    warn "If a drain-audit or checkpoint/scan warning appears, that is a REAL"
    warn "finding at $EPYC_NODES nodes — report it upstream and keep the box."
    exit 1
fi

banner "60 comprehensive suite GREEN"
log "triage: $TRIAGE"
exit 0
