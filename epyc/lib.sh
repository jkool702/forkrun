#!/usr/bin/env bash
# epyc/lib.sh — shared plumbing for the real-NUMA (EPYC) validation harness.
#
# Sourced by every stage script. Not executable on its own.
#
# Provides: logging, stage state/resume, wall-clock deadline accounting,
# run_logged(), and small helpers. Deliberately does NOT set -e: a failing
# benchmark must be recorded and stepped over, not abort the rental.

# shellcheck shell=bash

# ---------------------------------------------------------------- locations --
EPYC_DIR="${EPYC_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
EPYC_ROOT="${EPYC_ROOT:-$(cd "$EPYC_DIR/.." && pwd)}"
EPYC_ENV_FILE="$EPYC_DIR/env/epyc.env"
EPYC_STATE="${EPYC_STATE:-$EPYC_DIR/state}"
# Bootstrap output dir so stage_finish/load_env have a valid target BEFORE
# epyc.env exists. 00_preflight.sh may pick a different one (it takes an
# argument); run_all.sh migrates the ledgers if it does.
EPYC_OUT="${EPYC_OUT:-$EPYC_ROOT/epyc-rental-out}"

# ------------------------------------------------------------------- output --
_ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

log()  { printf '%s  %s\n' "$(_ts)" "$*" >&2; }
warn() { printf '%s  WARN  %s\n' "$(_ts)" "$*" >&2; }
err()  { printf '%s  ERROR %s\n' "$(_ts)" "$*" >&2; }
die()  { err "$*"; exit 1; }

banner() {
    printf '\n%s\n' "================================================================" >&2
    printf '%s\n'   "  $*" >&2
    printf '%s\n\n' "================================================================" >&2
}

# ------------------------------------------------------------------- stages --
# Each stage records a marker here so `run_all.sh` can resume. Markers are:
#   <stage>.done   stage completed with rc 0
#   <stage>.fail   stage ran but failed (rc != 0)
#   <stage>.skip   stage skipped (deadline / --skip)
stage_marker() { printf '%s/%s.%s' "$EPYC_STATE" "$1" "$2"; }

stage_is_done() { [ -f "$(stage_marker "$1" done)" ]; }

stage_skip() {
    warn "stage $1 SKIPPED ($2)"
    : > "$(stage_marker "$1" skip)"
    printf '%s\n' "$2" > "$(stage_marker "$1" skip).why"
}

stage_clear() { rm -f "$EPYC_STATE/$1".{done,fail,skip} "$EPYC_STATE/$1".skip.why; }

# Record the outcome of a stage, and append a line to the timing ledger.
stage_finish() {
    local name="$1" rc="$2" t0="$3"
    local dt=$(( $(date +%s) - t0 ))
    mkdir -p "$EPYC_OUT" "$EPYC_STATE"
    if [ "$rc" -eq 0 ]; then
        : > "$(stage_marker "$name" done)"
        log "stage $name OK (${dt}s)"
    else
        : > "$(stage_marker "$name" fail)"
        err "stage $name FAILED rc=$rc (${dt}s)"
    fi
    printf '%s\t%s\t%s\n' "$name" "$rc" "$dt" >> "$EPYC_OUT/STAGE_TIMINGS.tsv"
    return 0
}

# ------------------------------------------------------------------ loading --
load_env() {
    if [ ! -f "$EPYC_ENV_FILE" ]; then
        die "missing $EPYC_ENV_FILE — run epyc/00_preflight.sh first"
    fi
    # shellcheck disable=SC1090
    . "$EPYC_ENV_FILE"
    mkdir -p "$EPYC_OUT" "$EPYC_STATE" "$EPYC_TMPDIR"
    export PATH="$EPYC_VENV/bin:$PATH"
    export PYTHONPATH="$EPYC_ROOT/python${PYTHONPATH:+:$PYTHONPATH}"
    export FORKRUN_LIB="$EPYC_ROOT/python/forkrun/libforkrun_python.so"
    export TMPDIR="$EPYC_TMPDIR"
    # Trailing-slash-safe join, so a data dir of "/" does not produce "//hf_cache".
    export HF_DATASETS_CACHE="${EPYC_HF_CACHE:-${EPYC_DATA%/}/hf_cache}"
    export HF_HOME="${EPYC_HF_HOME:-${EPYC_DATA%/}/hf_home}"
    export RAY_DISABLE_IMPORT_WARNING=1
    export FORKRUN_DIAG_NUMA1=1
    return 0
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

# load_env_if_present — for components that run BEFORE the harness has created
# epyc.env. 55_agent_supervise.sh needs $EPYC_OUT/$EPYC_STATE for its own
# bookkeeping at startup, but on a fresh box 00_preflight.sh has not run yet, so
# a hard load_env would abort it and the whole run would never start. Bootstrap
# the locations, skip everything that needs the venv, and let the caller re-load
# later (load_env is idempotent).
load_env_if_present() {
    mkdir -p "$EPYC_OUT" "$EPYC_STATE" 2>/dev/null || true
    if [ -f "$EPYC_ENV_FILE" ]; then
        load_env
    else
        log "epyc.env not present yet (preflight has not run); using bootstrap paths"
        log "  EPYC_OUT=$EPYC_OUT"
        log "  The harness will create it at stage 00_preflight."
    fi
    return 0
}

# --------------------------------------------------------------- running ----
# Return 0 if the caller had errexit on, 1 otherwise. Every stage script here
# runs with `set -uo pipefail` and deliberately WITHOUT -e (a failing benchmark
# must be recorded and stepped over, not abort the rental), so run_logged must
# not turn -e on as a side effect. `set -e` in a subshell-cleared function would
# do exactly that and silently kill the caller mid-stage.
_errexit_was_on() { case "$-" in *e*) return 0 ;; *) return 1 ;; esac; }

# run_logged <logfile> <label> [--] <cmd...>
#   The `--` is optional (accepted for readability at call sites that pass a
#   long command); it is only skipped if it is actually there.
#   Streams output to the logfile AND stderr, stamps start/end, records rc and
#   duration into the timing ledger, and never aborts on failure.
run_logged() {
    local logfile="$1" label="$2"
    if [ "${3:-}" = "--" ]; then shift 3; else shift 2; fi
    local t0 t1 rc
    local had_e=0
    _errexit_was_on && had_e=1
    if [ $# -eq 0 ]; then
        err "run_logged: no command given for '$label'"
        return 2
    fi
    mkdir -p "$(dirname "$logfile")"
    t0=$(date +%s)
    log "START $label"
    {
        printf '### %s\n' "$label"
        printf '### %s\n### cmd: %s\n\n' "$(_ts)" "$*"
    } >"$logfile"
    "$@" 2>&1 | tee -a "$logfile"
    rc=${PIPESTATUS[0]}
    t1=$(date +%s)
    {
        printf '\n### rc=%d  elapsed=%ds  finished=%s\n' "$rc" "$((t1 - t0))" "$(_ts)"
    } >>"$logfile"
    printf '%s\t%s\t%s\n' "$label" "$rc" "$((t1 - t0))" >> "$EPYC_OUT/CMD_TIMINGS.tsv"
    log "END   $label rc=$rc ($((t1 - t0))s)"
    [ "$had_e" -eq 1 ] && set -e
    return $rc
}

# Same as run_logged but for a bash -c string (needed for the fd-redirect
# trickery in BENCHMARKS/run_benchmark.bash).
run_bash_logged() {
    local logfile="$1" label="$2" script="$3"
    local t0 t1 rc
    local had_e=0
    _errexit_was_on && had_e=1
    mkdir -p "$(dirname "$logfile")"
    t0=$(date +%s)
    log "START $label"
    {
        printf '### %s\n### %s\n### bash -c %s\n\n' "$label" "$(_ts)" "$script"
    } >"$logfile"
    bash -c "$script" 2>&1 | tee -a "$logfile"
    rc=${PIPESTATUS[0]}
    t1=$(date +%s)
    {
        printf '\n### rc=%d  elapsed=%ds  finished=%s\n' "$rc" "$((t1 - t0))" "$(_ts)"
    } >>"$logfile"
    printf '%s\t%s\t%s\n' "$label" "$rc" "$((t1 - t0))" >> "$EPYC_OUT/CMD_TIMINGS.tsv"
    log "END   $label rc=$rc ($((t1 - t0))s)"
    [ "$had_e" -eq 1 ] && set -e
    return $rc
}

# ------------------------------------------------------------- deadline ------
# deadline_ok <estimated_seconds>
#   Returns 0 (and prints the remaining budget) if the estimate plausibly fits
#   before EPYC_DEADLINE_EPOCH. Stages call this BEFORE starting so we never
#   pay for half of a long run.
deadline_ok() {
    local need="${1:-0}"
    if [ -z "${EPYC_DEADLINE_EPOCH:-}" ]; then
        echo "no deadline set"
        return 0
    fi
    local now remaining
    now=$(date +%s)
    remaining=$(( EPYC_DEADLINE_EPOCH - now ))
    if [ "$remaining" -le 0 ]; then
        echo "DEADLINE PASSED (${remaining}s)"
        return 1
    fi
    if [ "$need" -gt 0 ] && [ "$need" -gt "$remaining" ]; then
        echo "INSIDE deadline but estimate ${need}s > remaining ${remaining}s"
        return 1
    fi
    echo "$(( remaining / 60 ))m remaining"
    return 0
}

# ------------------------------------------------------------------ misc ----
# Report a suite's self-reported tally, e.g. "Total: 91 / Passed: 91 (100.0%)"
report_tally() {
    local logfile="$1" name="$2"
    if [ -f "$logfile" ]; then
        local line
        line=$(grep -aoE 'Total: +[0-9]+ */ *Passed: +[0-9]+[^)]*\)?|ALL TESTS PASSED!|OVERALL: [0-9]+ FAILURE' "$logfile" | tail -3 | tr '\n' ' ')
        printf '%-34s %s\n' "$name" "${line:-<no tally found>}" >> "$EPYC_OUT/TEST_TALLIES.txt"
    else
        printf '%-34s %s\n' "$name" "<no log>" >> "$EPYC_OUT/TEST_TALLIES.txt"
    fi
}

human() { # bytes -> human
    local b="${1:-0}"
    numfmt --to=iec-i --suffix=B "$b" 2>/dev/null || awk -v b="$b" 'BEGIN{split("B KB MB GB TB",u," ");i=1;while(b>=1024&&i<5){b/=1024;i++}printf "%.2f %s\n",b,u[i]}'
}
