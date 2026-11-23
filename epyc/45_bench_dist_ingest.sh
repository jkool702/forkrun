#!/usr/bin/env bash
# epyc/45_bench_dist_ingest.sh — experimental distributed-ingest campaign.
#
#   bash epyc/45_bench_dist_ingest.sh
#
# Runs the experimental dist-ingest campaign (stage0/dist_ingest/run_dist_campaign.sh)
# on the rental host after the hardware preflight and setup, per master WO
# (WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-AND-EXPERIMENT-COMPLETION-1, section 9.1):
# integrated into the existing EPYC rental workflow, with the new stage's own
# immutable output directory and report.
#
# What it records:
#   - the dist-ingest campaign directory ($EPYC_OUT/21_bench_dist_ingest/
#     dist_ingest_campaign/ — immutable output, campaign-manifest.json + report.md);
#   - NUMA hardware calibration (stage 8): standalone, diagnostic only —
#     NOT part of dist-ingest candidate throughput statistics
#     (stage0/numa_calibrate.py);
#   - production-reference separation (WO 9.2): production NUMA results
#     (stage 41_bench_numa5m) are recorded separately and are NOT combined
#     with dist-ingest candidate results;
#   - environment drift assessment (WO 7.2): env-before/env-after +
#     drift-report.json from stage0/env_drift.py.
#
# Safe rental supervision (WO 9.3): the stage requires the measured source
# tree to remain immutable during execution. It documents the same boundary
# the general supervision harness enforces; if a new dist-ingest source is
# needed mid-campaign, stop and re-run with a new source SHA and a new
# campaign.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

OUTD="$EPYC_OUT/21_bench_dist_ingest"
mkdir -p "$OUTD"
cd "$EPYC_ROOT" || die "no repo root"

banner "45 bench_dist_ingest — experimental distributed-ingest"

# --- production-reference separation (WO 9.2) ------------------------------
log "production-reference separation: production NUMA results (stage 41_bench_numa5m)"
log "  are recorded separately; they are NOT combined with dist-ingest results here."
for f in 20_benchmarks/numa5m/numa5m_part_a.csv \
         20_benchmarks/numa5m/numa5m_part_b.csv \
         20_benchmarks/numa5m/numa5m_part_c_light.csv; do
    [ -f "$EPYC_OUT/$f" ] && log "  present: $f"
done

# --- hardware calibration (WO 8) -------------------------------------------
CALIB_RC=0
if deadline_ok 600; then
    # P1.1: the calibration log and the calibration JSON artifact have
    # separate paths (run_logged appends log output to its logfile).
    run_logged "$OUTD/numa_calibration.log" "numa-calibration" \
        python3 stage0/numa_calibrate.py \
            --out "$OUTD/numa_calibration.json" \
            --samples "${EPYC_NUMA_CALIB_SAMPLES:-3}" \
            --size-mb "${EPYC_NUMA_CALIB_SIZE_MB:-32}" || \
        log "numa-calibration produced no report (continuing; diagnostic-only stage)"
    # P1.1 (integration check): the calibration JSON artifact must parse
    # after the stage runs (WO review finding 1).
    if [ -f "$OUTD/numa_calibration.json" ]; then
        python3 - "$OUTD/numa_calibration.json" >/dev/null <<'PY' || CALIB_RC=1
import json, sys
with open(sys.argv[1]) as f:
    json.load(f)
PY
        [ "$CALIB_RC" -eq 0 ] || { err "numa_calibration.json is not valid JSON (WO review finding 1)"; }
    fi
else
    stage_skip "45_bench_dist_ingest_calib" "deadline"
fi

# --- the dist-ingest campaign itself ---------------------------------------
CAMP="$OUTD/dist_ingest_campaign"
mkdir -p "$CAMP"
banner "45 bench_dist_ingest — dist campaign (stage0/dist_ingest/run_dist_campaign.sh)"
CAMP_ID="epyc-rental-$(date -u +%Y%m%dT%H%M%S)"
RC=0
run_logged "$OUTD/dist_ingest_campaign.log" "dist-ingest-campaign" \
    bash stage0/dist_ingest/run_dist_campaign.sh \
        --out "$CAMP" --campaign-id "$CAMP_ID" \
        --scenarios "${EPYC_DIST_SCENARIOS:-small}" \
        --candidates "${EPYC_DIST_CANDIDATES:-fixed_faa,local_adaptive,relative_adaptive,centralized_ingest}" \
        --trials "${EPYC_DIST_TRIALS:-1}" \
        --seed "epyc-${CAMP_ID}" || RC=$?
[ -f "$CAMP/campaign-manifest.json" ] && log "campaign manifest: $CAMP/campaign-manifest.json"
[ -f "$CAMP/report.md" ] && log "campaign report: $CAMP/report.md"

# The stage assumes production-reference results (stage 41_bench_numa5m)
# were recorded separately (WO 9.2): if 41 has not run, run it first
# (`bash epyc/41_bench_numa5m.sh`).

# The stage's own report: dist_ingest_report.md (WO 9.1: the new stage
# retains its own immutable output directory and report). P2.7/P2.10:
# report-generation failure affects the final status.
banner "45 bench_dist_ingest — dist report"
if require_campaign_manifest "$CAMP" "$RC"; then
    run_logged "$OUTD/dist_ingest_report.log" "dist-ingest-report" \
        python3 stage0/dist_ingest/report_dist.py \
            --campaign "$CAMP" --out "$OUTD/dist_ingest_report.md" \
            || { RC=1; warn "dist-ingest report generation failed (see $OUTD/dist_ingest_report.log)"; }
    [ -f "$OUTD/dist_ingest_report.md" ] && log "stage report: $OUTD/dist_ingest_report.md" || RC=1
else
    [ "$RC" -eq 0 ] && RC=1
fi
[ "$RC" -eq 0 ] && [ "$CALIB_RC" -ne 0 ] && RC=1

banner "45 bench_dist_ingest COMPLETE"
exit $RC
