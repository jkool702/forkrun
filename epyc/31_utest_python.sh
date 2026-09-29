#!/usr/bin/env bash
# epyc/31_utest_python.sh — the Python test suite + generator freshness gates.
#
#   bash epyc/31_utest_python.sh
#
# `make -f Makefile.substrate check` is the repo's only Make target that runs
# tests (canary + `unittest discover -s python/tests`, 65 modules / 644 tests).
#
# Known pre-existing failures (dev/supervisor/FAKE4_REVERIFY.md §5): exactly
# three, all traceable to a suite-order signal-disposition flake —
#   test_death_cause_mapping  (suite-order signal disposition)
#   its test_claim_taxonomy cascade
#   test_release_check_passes (runs the suite inline, same flake)
# Anything beyond those three is a real finding for this box.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

OUTD="$EPYC_OUT/10_utests/python"
mkdir -p "$OUTD"
cd "$EPYC_ROOT" || die "no repo root"

RC=0
KNOWN=0

banner "31a substrate canary"
run_logged "$OUTD/canary.log" "canary" make -f Makefile.substrate canary || { err "canary failed"; RC=1; }

banner "31b python test suite (65 modules / 644 tests)"
# Run the suite twice. FAKE4_REVERIFY ran it twice to distinguish real failures
# from order-dependent flakes; doing the same here is cheap (~4 min) and is the
# only way to tell a genuine 96-core finding from noise.
for pass in 1 2; do
    banner "31b pass $pass/2"
    if run_logged "$OUTD/suite_pass${pass}.log" "python-suite-pass${pass}" \
        python3 -m unittest discover -s python/tests -v; then
        log "pass $pass: all green"
    else
        err "pass $pass: failures present (see $OUTD/suite_pass${pass}.log)"
        RC=1
    fi
done

banner "31c failure triage"
TRIAGE="$OUTD/triage.txt"
{
    echo "# python suite failure triage"
    echo
    echo "## Known pre-existing (FAKE4_REVERIFY.md §5) — NOT findings for this box:"
    echo "  - test_death_cause_mapping  (suite-order signal-disposition flake)"
    echo "  - test_claim_taxonomy        (cascade from the above)"
    echo "  - test_release_check_passes  (runs the suite inline, same flake)"
    echo
    for pass in 1 2; do
        echo "## pass $pass — FAILED/ERROR test ids"
        grep -aoE '^(FAIL|ERROR): [A-Za-z0-9_.]+ \([A-Za-z0-9_.]+\)' "$OUTD/suite_pass${pass}.log" \
            | sort -u || echo "  (none)"
        echo
    done
    echo "## tails"
    for pass in 1 2; do
        echo "--- pass $pass tail"
        tail -25 "$OUTD/suite_pass${pass}.log"
        echo
    done
} | tee "$TRIAGE"

# Count the distinct failing test ids across both passes.
FAILS=$(grep -ahoE '^(FAIL|ERROR): [A-Za-z0-9_.]+' "$OUTD"/suite_pass*.log 2>/dev/null \
        | sed -E 's/^(FAIL|ERROR): //' | sort -u)
NF=$(printf '%s\n' "$FAILS" | grep -c . || true)
KNOWNIDS=$'test_death_cause_mapping\ntest_claim_taxonomy\ntest_release_check_passes'
UNKNOWN=$(printf '%s\n' "$FAILS" | while IFS= read -r t; do
    [ -n "$t" ] || continue
    if printf '%s\n' "$KNOWNIDS" | grep -qx "$t"; then continue; fi
    echo "$t"
done)
NUNKNOWN=$(printf '%s\n' "$UNKNOWN" | grep -c . || true)

log "distinct failing test ids: $NF   outside the known set: $NUNKNOWN"
if [ "$NUNKNOWN" -gt 0 ]; then
    err "$NUNKNOWN failing test(s) outside the known pre-existing set:"
    printf '%s\n' "$UNKNOWN" | sed 's/^/    /' >&2
    RC=1
fi

banner "31d generated-header freshness + schema gates"
# These are the CI-gated IDL/shim checks (idl-check.yml, shim-check.yml).
for g in gen_idl gen_shim; do
    if run_logged "$OUTD/${g}_check.log" "${g}--check" python3 "tools/${g}.py" --check; then
        log "$g --check OK"
    else
        err "$g --check FAILED (committed generated artifacts are stale)"
        RC=1
    fi
done
if run_logged "$OUTD/test_idl.log" "tools/test_idl.py" python3 tools/test_idl.py -v; then
    log "test_idl.py OK"
else
    err "test_idl.py FAILED"
    RC=1
fi
if run_logged "$OUTD/test_shim_abi.log" "test_shim_abi.py" \
        python3 python/tests/test_shim_abi.py -v; then
    log "test_shim_abi.py OK"
else
    err "test_shim_abi.py FAILED"
    RC=1
fi

banner "31e canary version-floor gate"
if run_logged "$OUTD/canary_versions.log" "check_canary_versions" \
        python3 tools/check_canary_versions.py; then
    log "bash version floor gate OK"
else
    err "check_canary_versions.py FAILED"
    RC=1
fi

if [ "$RC" -ne 0 ]; then
    banner "31 python tests COMPLETED WITH FINDINGS"
    warn "triage: $TRIAGE"
    exit 1
fi
banner "31 python tests ALL GREEN (modulo known flakes: $(printf '%s' "$FAILS" | tr '\n' ' '))"
exit 0
