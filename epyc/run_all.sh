#!/usr/bin/env bash
# epyc/run_all.sh — the orchestrator.
#
#   bash epyc/run_all.sh --hours 12
#   bash epyc/run_all.sh --only 41_bench_numa5m
#   bash epyc/run_all.sh --from 40_bench_ml5m
#   bash epyc/run_all.sh --skip 60_utest_bash_full
#
# Ordering principle: **most-valuable-and-unique first, most-reproducible last.**
# Stage 41/43 (real-NUMA) can only ever be measured on this box. Stages 50
# (bash matrix) and 51 (core suite) reproduce artifacts that already exist for
# the i9-7940X, so they are the right things to sacrifice when the clock wins.
#
# Data generation (stage 20) is launched in the BACKGROUND at the start of the
# test stages and awaited before the first stage that needs it. It is ~40 min of
# single-threaded generation on a 96-thread box; serialising it would bill that
# time twice.
#
# Each stage is resumable via a marker in epyc/state/, so re-running after a
# crash or a timeout picks up where it stopped rather than redoing hours.
#
# Deadline: --hours N / --deadline ISO8601 sets a wall-clock cut-off. Before
# starting a stage the orchestrator compares its estimate against the remaining
# budget and SKIPS (recording why) rather than starting something that will be
# billed but not finished.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"

# ----------------------------------------------------------------- args ------
HOURS=""
MINUTES=""
DEADLINE_ISO=""
ONLY=""
FROM=""
declare -a SKIP=()

usage() {
    cat <<'EOF'
usage: bash epyc/run_all.sh [options]

  --hours N            stop starting new stages after N hours from now
                       (fractional allowed: --hours 0.75 == 45 min)
  --minutes N          same, in minutes (--hours takes precedence if both given)
  --deadline ISO8601   absolute stop time, e.g. 2026-09-30T18:00:00Z
  --only NAME[,NAME]   run only these stages
  --from NAME          start at this stage and continue
  --skip NAME[,NAME]   skip these stages
  --list               list stages in execution order and exit
  -h|--help            this text

00_preflight and 10_setup are always run: everything downstream sources
epyc/env/epyc.env, which preflight writes, and needs the substrate setup builds.
Set EPYC_FORCE_NO_SETUP=1 to opt out.

Stages (in order):
  00_preflight            detect topology, record environment, go/no-go
  10_setup                deps, tuning, build substrate, verify both frontends
  -- background: 20_datagen (runs under the test stages) --
  30_utest_bash_fast      3 behavioural suites + 6 C-plugin suites
  31_utest_python         644 python tests (x2) + IDL/shim freshness gates
  -- await: 20_datagen --
  40_bench_ml5m           AI/ML @ 5M, all competing systems  (THE headline)
  41_bench_numa5m         real multi-socket NUMA study        (THE experiment)
  42_bench_tokenize       LLM tokenize @ 2M docs, 8 systems
  43_bench_ml20m          AI/ML @ 20M, forkrun only
  44_bench_headline       (dagger)/(max) pinned grid vs the published CSV
  50_bench_bash           bash matrix + parallel/xargs baselines + sweeps
  51_bench_core           core python suite @ 10M lines
  60_utest_bash_full      test_frun_comprehensive.sh (264, un-timeboxed)
  90_collect              bundle + ENVIRONMENT.md + DEVIATIONS.md
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --hours)     HOURS="$2"; shift 2 ;;
        --minutes)   MINUTES="$2"; shift 2 ;;
        --deadline)  DEADLINE_ISO="$2"; shift 2 ;;
        --only)      ONLY="$2"; shift 2 ;;
        --from)      FROM="$2"; shift 2 ;;
        --skip)      IFS=',' read -r -a SKIP <<<"$2"; shift 2 ;;
        --list)      sed -n '/^Stages (in order):/,/^EOF/p' "$0" | sed '1d;$d'; exit 0 ;;
        -h|--help)   usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage; exit 2 ;;
    esac
done

# Convert a possibly-fractional duration to whole seconds. bash arithmetic is
# integer-only, so `--hours 0.6` (36 min) would otherwise fail with
# "invalid arithmetic operator" and then cascade into an unbound-variable abort
# further down. awk does the decimal multiply; we then insist on a positive
# integer number of seconds.
to_seconds() { # <value> <unit-seconds>
    awk -v v="${1:-0}" -v u="$2" 'BEGIN {
        n = v * u
        if (n <= 0) { print 0; exit }
        printf "%d", n
    }'
}

# ----------------------------------------------------------------- stages ----
# name|script|estimate_seconds|needs_data
# 20_datagen is in this table so run_stage can resolve it when it has to run
# INLINE, but the main loop skips it: under a normal run it is launched in the
# background at stage 30 and awaited before the first stage that needs data, so
# that ~40 min of generation overlaps the unit-test stages instead of being
# serialised after them.
STAGES=(
    "00_preflight|00_preflight.sh|120|no"
    "10_setup|10_setup.sh|1800|no"
    "20_datagen|20_datagen.sh|5400|self"
    "30_utest_bash_fast|30_utest_bash_fast.sh|3600|no"
    "31_utest_python|31_utest_python.sh|3600|no"
    "40_bench_ml5m|40_bench_ml5m.sh|18000|yes"
    "41_bench_numa5m|41_bench_numa5m.sh|10800|yes"
    "42_bench_tokenize|42_bench_tokenize.sh|14400|yes"
    "43_bench_ml20m|43_bench_ml20m.sh|14400|yes"
    "44_bench_headline|44_bench_headline.sh|5400|yes"
    "50_bench_bash|50_bench_bash.sh|10800|no"
    "51_bench_core|51_bench_core.sh|7200|yes"
    "60_utest_bash_full|60_utest_bash_full.sh|10800|no"
    "90_collect|90_collect.sh|600|no"
)

in_list() { # needle haystack-comma
    case ",$2," in *",$1,"*) return 0 ;; esac
    return 1
}

want_stage() { # name -> 0/1
    [ -n "${SKIPPED_ALL:-}" ] && return 1
    # --skip always wins, so that `--only a,b --skip b` does what it reads like
    # rather than silently ignoring the skip because --only returned first.
    for s in ${SKIP[@]+"${SKIP[@]}"}; do
        [ "$s" = "$1" ] && return 1
    done
    if [ -n "${ONLY:-}" ]; then in_list "$1" "$ONLY" && return 0; return 1; fi
    if [ -n "${FROM:-}" ]; then
        local seen=0
        for st in "${STAGES[@]}"; do
            [ "${st%%|*}" = "$FROM" ] && seen=1
            [ "$seen" = 1 ] && [ "${st%%|*}" = "$1" ] && return 0
        done
        return 1
    fi
    return 0
}

# ----------------------------------------------------------------- start -----
mkdir -p "$EPYC_STATE"
START_EPOCH=$(date +%s)
BUDGET_S=0
if [ -n "$HOURS" ]; then
    BUDGET_S=$(to_seconds "$HOURS" 3600)
    [ "$BUDGET_S" -gt 0 ] || die "--hours '$HOURS' is not a positive number"
elif [ -n "$MINUTES" ]; then
    BUDGET_S=$(to_seconds "$MINUTES" 60)
    [ "$BUDGET_S" -gt 0 ] || die "--minutes '$MINUTES' is not a positive number"
fi

if [ "$BUDGET_S" -gt 0 ]; then
    EPYC_DEADLINE_EPOCH=$(( START_EPOCH + BUDGET_S ))
    EPYC_DEADLINE_ISO=$(date -u -d "@$EPYC_DEADLINE_EPOCH" '+%Y-%m-%dT%H:%M:%SZ')
elif [ -n "$DEADLINE_ISO" ]; then
    EPYC_DEADLINE_EPOCH=$(date -u -d "$DEADLINE_ISO" +%s 2>/dev/null) \
        || die "could not parse --deadline '$DEADLINE_ISO' (want e.g. 2026-09-30T18:00:00Z)"
    [ "$EPYC_DEADLINE_EPOCH" -gt 0 ] || die "--deadline '$DEADLINE_ISO' is not a future time"
    BUDGET_S=$(( EPYC_DEADLINE_EPOCH - START_EPOCH ))
else
    EPYC_DEADLINE_EPOCH=""
    EPYC_DEADLINE_ISO=""
    BUDGET_S=0
fi
export EPYC_DEADLINE_EPOCH

banner "forkrun EPYC rental harness"
log "started       : $(date -u '+%FT%TZ')"
if [ -n "$EPYC_DEADLINE_EPOCH" ]; then
    log "deadline      : $EPYC_DEADLINE_ISO (${HOURS:+$HOURS h}${MINUTES:+${HOURS:+, }$MINUTES min}${BUDGET_S:+, in $((BUDGET_S / 60)) min} from now)"
else
    log "deadline      : none — stages will run to completion"
fi
log "stages        : ${#STAGES[@]}"
[ -n "$ONLY" ] && log "only          : $ONLY"
[ -n "$FROM" ] && log "from          : $FROM"
[ ${#SKIP[@]} -gt 0 ] && log "skip          : ${SKIP[*]}"

# ---------------------------------------------------- background data gen ----
DATAGEN_PID=""
DATAGEN_T0=""
launch_datagen() {
    [ -n "$DATAGEN_PID" ] && return 0
    if stage_is_done 20_datagen; then
        log "20_datagen already complete — not relaunching"
        return 0
    fi
    if [ ! -f "$EPYC_DIR/env/epyc.env" ]; then
        warn "20_datagen: no epyc.env yet; will run inline when reached"
        return 0
    fi
    log "launching 20_datagen in the BACKGROUND (runs under the test stages)"
    DATAGEN_T0=$(date +%s)
    (
        bash "$EPYC_DIR/20_datagen.sh"
        echo $? > "$EPYC_STATE/20_datagen.rc"
    ) >"$EPYC_OUT/03_datagen_background.log" 2>&1 &
    DATAGEN_PID=$!
    log "  pid $DATAGEN_PID, log $EPYC_OUT/03_datagen_background.log"
    return 0
}

await_datagen() {
    # Check completion FIRST. On a resume, DATAGEN_PID is empty and there is no
    # .rc file, so without this the "not backgrounded" branch below would fire
    # once per needs-data stage and re-log the same resume line six times.
    if stage_is_done 20_datagen; then
        return 0
    fi
    if [ -z "$DATAGEN_PID" ] && [ ! -f "$EPYC_STATE/20_datagen.rc" ]; then
        # Never launched in the background (e.g. --only on a bench stage).
        log "running 20_datagen inline (it was not backgrounded)"
        run_stage 20_datagen
        return $?
    fi
    log "awaiting 20_datagen (pid $DATAGEN_PID) — the next stage needs its data"
    local waited=0
    while [ -n "$DATAGEN_PID" ] && kill -0 "$DATAGEN_PID" 2>/dev/null; do
        sleep 30
        waited=$((waited + 30))
        if [ $((waited % 600)) -eq 0 ]; then
            log "  20_datagen still running (${waited}s elapsed)"
        fi
    done
    wait "$DATAGEN_PID" 2>/dev/null
    local rc
    rc=$(cat "$EPYC_STATE/20_datagen.rc" 2>/dev/null || echo 1)
    rm -f "$EPYC_STATE/20_datagen.rc"
    if [ "$rc" -eq 0 ]; then
        stage_finish 20_datagen 0 "${DATAGEN_T0:-$(date +%s)}"
        log "20_datagen complete"
    else
        stage_finish 20_datagen "$rc" "${DATAGEN_T0:-$(date +%s)}"
        err "20_datagen FAILED (rc=$rc) — benchmarks needing data may refuse to run"
        err "  see $EPYC_OUT/03_datagen/DATA_MANIFEST.txt"
    fi
    return 0
}

# ------------------------------------------------------------------ runner ---
run_stage() {
    local name="$1"
    local script="" est=0 line
    for line in "${STAGES[@]}"; do
        [ "${line%%|*}" = "$name" ] || continue
        script="${line#*|}"; script="${script%%|*}"
        est="${line#*|*|}"; est="${est%%|*}"
    done
    if [ -z "$script" ]; then
        err "run_stage: '$name' is not in the STAGES table (typo?)"
        return 1
    fi
    if [ ! -f "$EPYC_DIR/$script" ]; then
        err "missing stage script $EPYC_DIR/$script"
        return 1
    fi

    if stage_is_done "$name"; then
        log "stage $name already done — skipping (resume)"
        return 0
    fi

    if [ -n "${EPYC_DEADLINE_EPOCH:-}" ]; then
        local remaining=$(( EPYC_DEADLINE_EPOCH - $(date +%s) ))
        if [ "$remaining" -le 0 ]; then
            stage_skip "$name" "deadline $EPYC_DEADLINE_ISO reached"
            return 0
        fi
        if [ "$est" -gt "$remaining" ]; then
            stage_skip "$name" "deadline: estimate ${est}s > remaining ${remaining}s"
            return 0
        fi
    fi

    banner "STAGE $name  (est ${est}s)"
    local t0
    t0=$(date +%s)
    bash "$EPYC_DIR/$script"
    local rc=$?
    stage_finish "$name" "$rc" "$t0"
    return $rc
}

# ------------------------------------------------------------------- main ----
for line in "${STAGES[@]}"; do
    IFS='|' read -r name script est needs <<<"$line"

    # 20_datagen is driven by launch_datagen/await_datagen, not by the main
    # loop, so that it can run in the background under the unit-test stages.
    # It is only invoked from here when it could not be backgrounded.
    [ "$name" = "20_datagen" ] && continue

    # 00_preflight and 10_setup are FORCED. Everything downstream sources
    # epyc/env/epyc.env (which preflight writes) and needs the substrate that
    # setup builds, so `--only 41_bench_numa5m` is only meaningful if both run
    # first. run_stage still honours a .done marker, so a resume does not
    # repeat them. Only an explicit EPYC_FORCE_NO_SETUP=1 opts out.
    case "$name" in
        00_preflight|10_setup)
            if [ -n "${ONLY:-}" ] || [ ${#SKIP[@]} -gt 0 ] || [ -n "${FROM:-}" ]; then
                if [ "${EPYC_FORCE_NO_SETUP:-0}" = "1" ]; then
                    warn "EPYC_FORCE_NO_SETUP=1 — skipping prerequisite $name"
                    continue
                fi
                log "stage $name is a prerequisite; running it despite the selection"
            fi
            run_stage "$name" || die "prerequisite stage $name failed — stopping"
            # Every stage sources this. If it is missing, the prerequisite was
            # resumed-from-done but the env file was never written (or was
            # cleaned up) — fail with something actionable rather than a bare
            # "EPYC_VENV: unbound variable" 15 lines later.
            [ -f "$EPYC_DIR/env/epyc.env" ] || die \
"missing $EPYC_DIR/env/epyc.env after stage $name.
 00_preflight.sh writes it; 10_setup.sh's validation depends on it. Either the
 stage was marked .done from an earlier run whose env was removed, or preflight
 did not run. Force it with:
     rm -f $EPYC_DIR/state/00_preflight.* $EPYC_DIR/state/10_setup.*
     bash epyc/run_all.sh --only $name"
            # Preflight may have chosen a different output dir than the
            # bootstrap default; carry the ledgers over so the timing record is
            # not split across two directories.
            BOOTSTRAP_OUT="$EPYC_OUT"
            # shellcheck disable=SC1090
            . "$EPYC_DIR/env/epyc.env"
            if [ "$EPYC_OUT" != "$BOOTSTRAP_OUT" ]; then
                mkdir -p "$EPYC_OUT"
                for lf in CMD_TIMINGS.tsv STAGE_TIMINGS.tsv TEST_TALLIES.txt; do
                    [ -f "$BOOTSTRAP_OUT/$lf" ] && mv -f "$BOOTSTRAP_OUT/$lf" "$EPYC_OUT/$lf"
                done
                log "output dir relocated $BOOTSTRAP_OUT -> $EPYC_OUT (ledgers migrated)"
            fi
            mkdir -p "$EPYC_OUT" "$EPYC_STATE" "$EPYC_TMPDIR"
            export PATH="$EPYC_VENV/bin:$PATH"
            export PYTHONPATH="$EPYC_ROOT/python${PYTHONPATH:+:$PYTHONPATH}"
            export FORKRUN_LIB="$EPYC_ROOT/python/forkrun/libforkrun_python.so"
            export TMPDIR="$EPYC_TMPDIR"
            export HF_DATASETS_CACHE="$EPYC_DATA/hf_cache" HF_HOME="$EPYC_DATA/hf_home"
            export RAY_DISABLE_IMPORT_WARNING=1 FORKRUN_DIAG_NUMA1=1
            export FORKRUN_BENCH_WORKERS_MAX="$EPYC_WORKERS_MAX"
            continue
            ;;
    esac

    want_stage "$name" || { log "stage $name not selected — skipping"; continue; }

    # Kick off data generation as soon as the setup is behind us, so it runs
    # underneath the two test stages.
    if [ "$name" = "30_utest_bash_fast" ]; then
        launch_datagen
    fi

    # Everything that needs data must wait for it.
    if [ "$needs" = "yes" ]; then
        await_datagen
    fi

    run_stage "$name" || warn "stage $name finished non-zero (rc=$?)"
done

# Safety net: if we exited the loop with generation still running, let it finish
# so the manifest exists (it is only a few minutes at that point).
if [ -n "$DATAGEN_PID" ] && kill -0 "$DATAGEN_PID" 2>/dev/null; then
    log "waiting for the in-flight 20_datagen to finish so the manifest is written"
    wait "$DATAGEN_PID" 2>/dev/null
fi

banner "RUN COMPLETE"
log "total wall clock: $(( ($(date +%s) - START_EPOCH) / 60 )) minutes"
if [ -f "$EPYC_OUT/RUN_REPORT.txt" ]; then
    echo
    cat "$EPYC_OUT/RUN_REPORT.txt"
fi
echo
echo "  Results: $EPYC_OUT"
echo "  Summary: $EPYC_OUT/00_environment/COLLECTION_SUMMARY.txt"
echo
exit 0
