#!/usr/bin/env bash
# epyc/rehearsal_rehearsal_45.sh — corrections-3 rehearsal rehearsal (WO-NUMA-
# ONE-SHOT-RENTAL-PREPARATION §11): exercise the full rental-readiness
# rehearsal checklist on a clean checkout of the corrected commit.
#
# Must be run from the worktree of the final corrected commit, with a
# rehearsal env (epyc/env/epyc.env). Exercises:
#   1. 45-stage rehearsal (the C5-style rehearsal of the new workflow).
#   2. Plan-only rehearsal output (topology discovery, mapping-matrix
#      generation, mapping compatibility validation).
#   3. Rehearsal campaign: asymmetric-ingestor scenarios (§5), performance
#      mode with placement sampling disabled (default), paired placement
#      experiments (§2), repeated passes + minimum-duration qualification
#      (§3), parameter sweep plan generation (§4), randomized candidate
#      order (§11), per-trial provenance (mapping_provenance).
#   4. Provenance reconciliation: campaign source_sha == env-before
#      git.head_sha == corrected SHA, git.dirty == false.
#   5. Artifact collection/indexing (90_collect).
#
# Outputs under $EPYC_OUT (/tmp/opencode/epyc-reh3/out for corrections-3).
set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

fail=0
check() { # $1=name, $2=rc
    if [ "$2" -eq 0 ]; then log "PASS: $1"; else err "FAIL: $1 (rc=$2)"; fail=$((fail + 1)); fi
}

# --- 1. 45 stage rehearsal --------------------------------------------------
# The campaign requires its output dir to be empty/absent (pre-existing
# contract), so clean it before each rehearsal rehearsal run.
rm -rf "$EPYC_OUT/21_bench_dist_ingest/dist_ingest_campaign"
bash epyc/45_bench_dist_ingest.sh > "$EPYC_OUT/45_stage_rehearsal.log" 2>&1
check "45 stage rehearsal" $?

# --- 2. plan-only rehearsal (mapping matrix + plan output) ------------------
rm -rf "$EPYC_OUT/plan_only_campaign"
bash stage0/dist_ingest/run_dist_campaign.sh --plan-only --mapping-profiles matrix \
    --out "$EPYC_OUT/plan_only_campaign" --campaign-id rehearsal-reh3-plan \
    --scenarios slow_ingestor_one --trials 1 > "$EPYC_OUT/plan_only.log" 2>&1
rc=$?
check "plan-only rehearsal (RC)" $rc
if [ $rc -eq 0 ]; then
    grep -q "prevalidation ok" "$EPYC_OUT/plan_only.log" && log "PASS: plan-only rehearsal output (topology discovery + mapping compatibility validated)" || { err "FAIL: plan-only rehearsal log lacks prevalidation output"; fail=$((fail + 1)); }
    [ -f "$EPYC_OUT/plan_only_campaign/prevalidation.json" ] && log "PASS: plan-only prevalidation.json written" || { err "FAIL: missing prevalidation.json"; fail=$((fail + 1)); }
    [ -f "$EPYC_OUT/plan_only_campaign/execution-plan.json" ] && log "PASS: plan-only execution-plan.json (mapping matrix generated)" || { err "FAIL: missing execution-plan.json"; fail=$((fail + 1)); }
fi

# --- 2b. parameter sweep plan generation (§4) --------------------------------
rm -rf "$EPYC_OUT/sweep_plan_only_campaign"
bash stage0/dist_ingest/run_dist_campaign.sh --plan-only \
    --out "$EPYC_OUT/sweep_plan_only_campaign" --campaign-id rehearsal-reh3-sweep \
    --scenarios small --trials 1 --seed rehearsal-reh3-seed \
    --sweep-base-quantum "2097152,4194304" --sweep-max-backlog "67108864,134217728" \
    > "$EPYC_OUT/sweep_plan_only.log" 2>&1
check "parameter sweep plan generation (RC)" $?
python3 - "$EPYC_OUT/sweep_plan_only_campaign/prevalidation.json" <<'PY'
import json, sys
pv = json.load(open(sys.argv[1]))
axes = pv.get("sweep_axes") or []
psets = pv.get("parameter_sets") or []
assert axes, "no sweep axes recorded"
assert any(p.get("base_quantum") in (2097152, 4194304) for p in psets), "expected swept base_quantum in parameter sets"
print("PASS: parameter sweep plan generation (sweep_axes + parameter_sets recorded)")
PY
check "parameter sweep plan generation (evidence)" $?

# --- 3. rehearsal campaign: §5 asymmetric ingestors + §2 paired + §3 repeats + §4 sweeps + §11 random order ------------------
rm -rf "$EPYC_OUT/rehearsal_campaign"; mkdir -p "$EPYC_OUT/rehearsal_campaign"
bash stage0/dist_ingest/run_dist_campaign.sh \
    --out "$EPYC_OUT/rehearsal_campaign" --campaign-id rehearsal-reh3-asym \
    --scenarios slow_ingestor_one,slow_ingestor_stall_recover,slow_ingestor_fast_consumer,slow_ingestor_slow_consumer \
    --candidates fixed_faa --trials 1 --seed rehearsal-reh3-seed \
    --placement-experiments paired --min-duration-seconds 2 --shuffle-scenarios \
    > "$EPYC_OUT/rehearsal_campaign.log" 2>&1
check "rehearsal campaign (RC)" $?

# --- 4. provenance reconciliation (corrected-commit source provenance) ------
python3 - "$EPYC_OUT/rehearsal_campaign" "$(git rev-parse HEAD)" <<'PY'
import os
import json, os, sys
camp_dir, sha = sys.argv[1], sys.argv[2]
manifest = json.load(open(camp_dir + "/campaign-manifest.json"))
assert manifest.get("source_sha") == sha, "campaign source_sha != corrected SHA: %s" % manifest.get("source_sha")
env_before = json.load(open(camp_dir + "/env/env-before.json"))
assert env_before["git"]["head_sha"] == sha, "env-before head_sha != corrected SHA"
assert env_before["git"]["dirty"] is False, "env-before dirty != false: %s" % env_before["git"].get("dirty_paths")
assert manifest.get("drift_assessment") == "valid", manifest.get("drift_assessment")
assert manifest.get("drift_invalidated") is False
print("PASS: provenance reconciliation (campaign source_sha == env-before git.head_sha == %s, git.dirty == false, drift_assessment=valid)" % sha[:12])
PY
check "provenance reconciliation" $?

# --- 4b. rehearsal campaign evidence: ingestor controls + provenance + duration qualification ------------------
python3 - "$EPYC_OUT/rehearsal_campaign" <<'PY'
import json, os, sys
camp_dir = sys.argv[1]
seen = {}
for root, dirs, files in os.walk(camp_dir + "/cases"):
    if "manifest.json" not in files:
        continue
    m = json.load(open(os.path.join(root, "manifest.json")))
    case_id = os.path.basename(os.path.dirname(root))
    sid = case_id.split("__")[0]
    dr = m.get("dist_result")
    if not dr:
        continue
    for nd in dr.get("nodes", []):
        assert "ingestor_controls" in nd, "missing ingestor_controls in %s" % case_id
    assert "mapping_provenance" in (m.get("dist_result") or {}), "missing mapping_provenance in %s" % case_id
    assert "duration_qualification" in m, "missing duration_qualification in %s" % case_id
    if sid == "slow_ingestor_one":
        ic0 = dr["nodes"][0]["ingestor_controls"]
        assert ic0["mode"] == 1 and ic0["delay_ns"] > 0, (sid, ic0)
        seen[sid] = ic0["mode"]
    elif sid == "slow_ingestor_stall_recover":
        ic0 = dr["nodes"][0]["ingestor_controls"]
        assert ic0["mode"] == 3 and ic0["stall_fired"] >= 1, (sid, ic0)
        seen[sid] = ic0["mode"]
assert "slow_ingestor_one" in seen and "slow_ingestor_stall_recover" in seen, seen
print("PASS: asymmetric-ingestor evidence (slow_ingestor_one mode=%s, slow_ingestor_stall_recover mode=%s), per-trial provenance + duration qualification recorded" % (seen.get("slow_ingestor_one"), seen.get("slow_ingestor_stall_recover")))
PY
check "rehearsal campaign evidence" $?

# --- 5. artifact collection/indexing ----------------------------------------
bash epyc/90_collect.sh > "$EPYC_OUT/90_collect.log" 2>&1
check "90_collect (RC)" $?
[ -f "$EPYC_OUT/ENVIRONMENT.md" ] && log "PASS: ENVIRONMENT.md written by 90_collect" || { err "FAIL: ENVIRONMENT.md missing"; fail=$((fail + 1)); }

if [ "$fail" -eq 0 ]; then
    log "rehearsal rehearsal (corrections-3): ALL PASS"
else
    err "rehearsal rehearsal (corrections-3): $fail FAILURE(S)"
fi
exit "$fail"
