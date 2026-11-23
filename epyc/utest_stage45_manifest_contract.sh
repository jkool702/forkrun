#!/usr/bin/env bash
# epyc/utest_stage45_manifest_contract.sh — contract test for the 45 stage's
# campaign-manifest requirement: the campaign manifest is a declared
# deliverable, so a stub campaign command that exits 0 without producing
# campaign-manifest.json is a stage failure — independently of the campaign
# command's exit status.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
. ./epyc/lib.sh

fails=0

check_rc() { # $1=expect(0/1) $2=cmdname ...
    local expect="$1"; shift
    local name="$1"; shift
    "$@" >/dev/null 2>&1
    local rc=$?
    if [ "$rc" -eq "$expect" ]; then
        log "PASS: $name"
    else
        err "FAIL: $name — expected rc=$expect, got rc=$rc"
        fails=$((fails + 1))
    fi
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
d="$tmp/case1"
mkdir -p "$d"

# Stub campaign: exits 0 without producing the manifest -> stage fails.
check_rc 1 "campaign exits 0 without manifest -> require_campaign_manifest fails" \
    require_campaign_manifest "$d" 0
# Stub campaign: nonzero exit without manifest -> still fails.
check_rc 1 "campaign exits 3 without manifest -> require_campaign_manifest fails" \
    require_campaign_manifest "$d" 3
# Manifest produced (stub campaign wrote campaign-manifest.json) -> passes.
touch "$d/campaign-manifest.json"
check_rc 0 "campaign exits 0 with manifest -> require_campaign_manifest passes" \
    require_campaign_manifest "$d" 0
check_rc 0 "campaign exits 2 with manifest -> require_campaign_manifest passes" \
    require_campaign_manifest "$d" 2
rm -f "$d/campaign-manifest.json"

if [ "$fails" -eq 0 ]; then
    log "utest_stage45_manifest_contract: ALL PASS"
else
    err "utest_stage45_manifest_contract: $fails FAILURE(S)"
fi
exit "$fails"
