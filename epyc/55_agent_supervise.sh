#!/usr/bin/env bash
# epyc/55_agent_supervise.sh — run the harness under opencode supervision.
#
#   bash epyc/55_agent_supervise.sh --hours 12
#   bash epyc/55_agent_supervise.sh --hours 12 --max-triage 4
#
# WHAT THIS IS. epyc/run_all.sh remains the orchestrator. This wrapper does not
# reimplement its ordering, deadline logic or resume behaviour; it runs it, and
# consults an opencode instance when a stage fails. The agent is the exception
# handler, never the sequencer.
#
# WHY. On a rental you are billed while you sleep. A stage that dies on a missing
# package or a stale substrate build would otherwise waste hours of paid time
# waiting for a human. An agent can fix that in a minute — and the harness's own
# gates keep it honest, because it cannot relax a validator, forge a stage
# marker, or delete a failing log without that showing up in the collection step.
#
# THE BOUNDARIES are declared in three independent places, on purpose:
#   1. epyc/AGENT_PROMPT.md   — what the agent is told its job and limits are
#   2. epyc/opencode.json     — what the harness will physically let it edit
#   3. epyc/10_setup.sh       — a SHA-256 manifest of integrity-critical files,
#                               re-verified by 90_collect.sh
# One of them can fail without the experiment being compromised.
#
# SESSION CONTINUITY. The first triage opens a session; every later triage
# continues it, so the agent remembers what it already tried instead of
# rediscovering the same dead end every twenty minutes.
#
# This script degrades safely: with --no-agent, or if opencode is missing or
# unauthenticated, it simply runs the harness unattended and says so.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
# Tolerant load: on a fresh box epyc/env/epyc.env does not exist yet because
# 00_preflight.sh has not run. The supervisor only needs $EPYC_OUT/$EPYC_STATE
# for its own logging, so bootstrap those and re-load the full env after the
# harness has run preflight.
load_env_if_present

PROMPT="$EPYC_DIR/AGENT_PROMPT.md"
OC_CONFIG="$EPYC_DIR/opencode.json"
AGENT_LOG_DIR="$EPYC_OUT/05_agent"
AGENT_TRANSCRIPT="$EPYC_OUT/AGENT_FINDINGS.md"
AGENT_LOG="$AGENT_LOG_DIR/agent.log"

# ------------------------------------------------------------- arguments ----
HOURS=""
MAX_TRIAGE="${EPYC_MAX_TRIAGE:-3}"      # total agent consultations, not per-stage
MAX_PER_STAGE=1                          # fix attempts for any single stage
USE_AGENT=1
RUN_ARGS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --hours)       HOURS="$2"; shift 2 ;;
        --max-triage)  MAX_TRIAGE="$2"; shift 2 ;;
        --no-agent)    USE_AGENT=0; shift ;;
        --from|--skip|--only) RUN_ARGS+=("$1" "$2"); shift 2 ;;
        -h|--help)
            cat <<EOF
usage: bash epyc/55_agent_supervise.sh [--hours N] [--max-triage N] [--no-agent]
                                       [--from STAGE] [--skip A,B]

  --hours N        wall-clock budget handed to run_all.sh (default: none)
  --max-triage N   total agent consultations (default 3)
  --no-agent       do not invoke opencode at all; just run the harness
EOF
            exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done
[ -n "$HOURS" ] && RUN_ARGS+=(--hours "$HOURS")

mkdir -p "$AGENT_LOG_DIR"
: >"$AGENT_TRANSCRIPT"
cat >"$AGENT_TRANSCRIPT" <<EOF
# Agent findings — EPYC rental

Append-only. Written by the opencode supervisor
(\`epyc/55_agent_supervise.sh\`) and by the agent itself.

| time (UTC) | stage | what happened |
|---|---|---|
| $(date -u '+%FT%TZ') | supervisor | started; budget=${HOURS:-none}h; max-triage=$MAX_TRIAGE; agent=$USE_AGENT |
EOF

# ------------------------------------------------------- agent preflight ----
AGENT_OK=0
SESSION_ID=""
MODEL="${EPYC_AGENT_MODEL:-opencode/space-bunny-free}"

check_agent() {
    banner "supervisor: agent preflight"
    # opencode inherits TMPDIR. The harness exports TMPDIR=$EPYC_TMPDIR, which
    # lives on the multi-GB dataset store — opencode will try to mkdir its own
    # scratch there and die with an opaque "EACCES: permission denied, mkdir
    # '/mnt/epyc_data'". It is also simply wrong for the agent to share scratch
    # with a benchmark that may be writing tens of GB of temp files. Give it a
    # small private directory.
    AGENT_TMP="$EPYC_OUT/05_agent/tmp"
    mkdir -p "$AGENT_TMP" 2>/dev/null || AGENT_TMP="$(mktemp -d)"
    export TMPDIR="$AGENT_TMP"

    if [ "$USE_AGENT" -eq 0 ]; then
        warn "--no-agent given; running the harness unattended"
        return 1
    fi
    if ! command -v opencode >/dev/null 2>&1; then
        warn "opencode not found on PATH — running the harness unattended."
        warn "  (10_setup.sh installs it; if you skipped setup, the run still completes,"
        warn "   it just will not self-triage failures. Re-run 10_setup.sh to fix.)"
        return 1
    fi
    log "opencode: $(opencode --version 2>/dev/null)"
    [ -f "$PROMPT" ]    || { warn "missing $PROMPT"; return 1; }
    [ -f "$OC_CONFIG" ] || { warn "missing $OC_CONFIG"; return 1; }

    if ! opencode auth list >/dev/null 2>&1; then
        warn "opencode is not usable from this shell — running the harness unattended."
        warn "  Diagnose with:  opencode --version ; opencode auth list"
        warn "  If --version prints something other than a version number (for"
        warn "  example EACCES), the cause is usually TMPDIR: opencode inherits"
        warn "  \$TMPDIR from the harness, which points at the multi-GB dataset"
        warn "  store. The supervisor overrides it, but a manual opencode call"
        warn "  inside a sourced env will not."
        warn "  Then:  opencode auth login"
        return 1
    fi

    # The model is configurable because the catalogue changes; verify the one we
    # are about to use actually exists rather than failing 20 minutes into a run.
    if ! opencode models 2>/dev/null | grep -qxF "$MODEL"; then
        warn "model '$MODEL' is not in the opencode catalogue."
        warn "  Available space/bunny models:"
        opencode models 2>/dev/null | grep -i 'space\|bunny' | sed 's/^/    /' >&2
        warn "  Re-run with: EPYC_AGENT_MODEL=opencode/<id> bash $0 ${RUN_ARGS[*]}"
        return 1
    fi
    log "model: $MODEL (verified present)"
    AGENT_OK=1
    return 0
}
check_agent

# Evidence extraction.
#
# The agent runs with --dir $EPYC_ROOT and external_directory is DENIED in
# epyc/opencode.json, which is the right boundary — but the stage logs live in
# $EPYC_OUT (a separate big disk, outside the checkout). Handing the agent a
# path it cannot open makes it fail silently with an auto-rejected permission
# request, which is exactly the "agent did nothing and you find out at 3am"
# failure this whole mechanism exists to prevent.
#
# So: inline the evidence in the prompt, bounded in size. The agent gets what it
# needs to reason, and the permission boundary stays tight. Paths are still named
# so it can ask for more context if it wants to escalate to a human.
stage_evidence() { # <stage> <logfile> -> bounded excerpt on stdout
    local stage="$1" logf="$2"
    local MAXLINES="${EPYC_AGENT_EVIDENCE_LINES:-120}"
    local MAXBYTES="${EPYC_AGENT_EVIDENCE_BYTES:-48000}"
    echo "### Evidence: $stage"
    if [ -n "$logf" ] && [ -f "$logf" ]; then
        echo "\$ $logf  (last $MAXLINES lines)"
        echo '```'
        tail -n "$MAXLINES" "$logf" 2>/dev/null | head -c "$MAXBYTES"
        echo
        echo '```'
    else
        echo "(no log found for this stage)"
    fi
    # Any sibling logs from the same stage directory are usually where the real
    # cause is (the harness writes one log per sub-step).
    local dir
    dir=$(dirname "${logf:-$EPYC_OUT}")
    if [ -d "$dir" ]; then
        local other
        for other in "$dir"/*.log; do
            [ -f "$other" ] || continue
            [ "$other" = "$logf" ] && continue
            echo
            echo "### Also in $(basename "$dir"): $(basename "$other")"
            echo '```'
            tail -n 20 "$other" 2>/dev/null | head -c 4000
            echo
            echo '```'
        done
    fi
}

# ------------------------------------------------------------- the agent ----
# ask_agent <stage> <logfile> [extra context...]
#
# Continues one session across the whole night.
ask_agent() {
    local stage="$1" stage_log="$2"; shift 2
    [ "$AGENT_OK" -eq 1 ] || return 1
    # The harness has now run 00_preflight/10_setup, so the real environment
    # (venv python, dataset paths, node topology) is available to both us and
    # the agent. Pick it up if we started before it existed.
    if [ ! -d "$EPYC_VENV" ] && [ -f "$EPYC_ENV_FILE" ]; then
        log "reloading environment now that preflight has written it"
        load_env
    fi
    if [ "$TRIAGE_COUNT" -ge "$MAX_TRIAGE" ]; then
        warn "triage budget exhausted ($MAX_TRIAGE consultations used); not consulting the agent for $stage"
        return 1
    fi
    TRIAGE_COUNT=$((TRIAGE_COUNT + 1))

    local evidence sess_args
    evidence=$(stage_evidence "$stage" "$stage_log")
    sess_args=()
    [ -n "$SESSION_ID" ] && sess_args=(-s "$SESSION_ID")

    log "consulting opencode for $stage (session=${SESSION_ID:-new}, $(printf '%s' "$evidence" | wc -c) bytes of evidence)"
    {
        cat <<EOF
Supervisor consultation $(printf '%02d' "$TRIAGE_COUNT") of $MAX_TRIAGE.

## Where things are

You are running with your working directory set to the forkrun checkout, and
you can read everything inside it. Use these absolute paths:

- checkout          $EPYC_ROOT
- results, logs, CSVs, audits   $EPYC_OUT
- stage markers     $EPYC_STATE
- recorded topology $EPYC_ENV_FILE
- findings file     $AGENT_TRANSCRIPT
- dataset store     $EPYC_DATA   <-- deliberately NOT readable by you (see brief §2)

## Stage: $stage — marked failed by the harness

$evidence

## Current stage state

$(ls -1 "$EPYC_STATE" 2>/dev/null | sed 's/^/  /' || echo "  (no markers yet)")

## Recorded machine topology (from epyc.env)

$(grep -E '^EPYC_(NODES|NUMA_SHAPE|NODES_ONLINE|DIST_|THRESH_|NODE_SOCKETS|SOCKETS|PHYS|NPROC|WORKERS_MAX)=' "$EPYC_ENV_FILE" 2>/dev/null | sed 's/^EPYC_/  /' || echo "  (unavailable)")

$( [ $# -gt 0 ] && printf '## Notes from the supervisor\n\n%s\n' "$*"; )

## What to do

Your operating brief is in \`epyc/AGENT_PROMPT.md\` and is loaded
automatically. Read it and follow it — especially section 2 (what you may do),
section 3 (what you must NOT do) and section 4 (the decision procedure).

Work within the levels: diagnose from the evidence above, fix only what is
shallow and unambiguous, and escalate everything else by APPENDING to
\`$AGENT_TRANSCRIPT\`. Do not attempt to make a stage pass by weakening a check.

When you have finished (fixed, escalated, or concluded the stage is hopeless),
reply with a two-line summary: the disposition (FIXED / ESCALATED / SKIPPED)
and one sentence of why. Do not start long-running benchmark stages yourself —
the supervisor drives those.
EOF
    } >"$AGENT_LOG_DIR/prompt_${TRIAGE_COUNT}_${stage}.md"

    local jf="$AGENT_LOG_DIR/triage_${TRIAGE_COUNT}_${stage}.jsonl"
    local brief="$AGENT_LOG_DIR/prompt_${TRIAGE_COUNT}_${stage}.md"
    local t0 rc
    t0=$(date +%s)
    # Pass the brief as the positional message rather than with -f. Two reasons,
    # both learned the hard way: opencode requires a message (a bare -f exits 1
    # with "You must provide a message or a command"), and -f is variadic, so
    # `-f brief.md "message"` makes opencode try to open the message string as a
    # second file and fail with "File not found: <message>". The brief file is
    # still written, so the exact prompt is auditable after the fact.
    timeout "${EPYC_AGENT_TIMEOUT:-1800}" \
        opencode run --format json \
            --dir "$EPYC_ROOT" \
            --model "$MODEL" \
            --title "epyc-rental: $stage failure triage" \
            "${sess_args[@]}" \
            "$(cat "$brief")" \
        >"$jf" 2>>"$AGENT_LOG"
    rc=$?
    printf '### triage %d for %s: rc=%d in %ds -> %s\n' \
        "$TRIAGE_COUNT" "$stage" "$rc" "$(( $(date +%s) - t0 ))" "$jf" >>"$AGENT_LOG"

    # A non-zero rc, or a session with no text output, means the agent never
    # actually did anything. Say so loudly rather than letting it read as a
    # triage that happened.
    local said_something
    said_something=$(python3 - "$jf" <<'PY' 2>/dev/null
import json, sys
n = 0
for line in open(sys.argv[1], errors="ignore"):
    try:
        o = json.loads(line)
    except Exception:
        continue
    if o.get("type") == "text" and (o.get("text") or "").strip():
        n += 1
print(n)
PY
)
    if [ "${said_something:-0}" -eq 0 ] 2>/dev/null; then
        warn "the agent produced no text for $stage (rc=$rc) — treat as NOT triaged."
        warn "  Common cause: an auto-rejected permission request (see $AGENT_LOG)."
        warn "  Evidence was inlined at $AGENT_LOG_DIR/prompt_${TRIAGE_COUNT}_${stage}.md"
    fi

    # Persist the session id so the next consultation continues the same memory.
    SESSION_ID=$(python3 - "$jf" <<'PY' 2>/dev/null || true
import json, sys
for line in open(sys.argv[1], errors="ignore"):
    line = line.strip()
    if not line:
        continue
    try:
        o = json.loads(line)
    except Exception:
        continue
    sid = o.get("sessionID")
    if sid:
        print(sid)
        break
PY
)
    [ -n "$SESSION_ID" ] && log "agent session: $SESSION_ID"

    # Surface the agent's own words, which is the only place its reasoning lands
    # in a form a human can audit quickly.
    python3 - "$jf" >>"$AGENT_LOG" 2>/dev/null <<'PY' || true
import json, sys
for line in open(sys.argv[1], errors="ignore"):
    try:
        o = json.loads(line)
    except Exception:
        continue
    if o.get("type") == "text" and o.get("text", "").strip():
        print("    " + o["text"].strip().replace("\n", "\n    "))
PY

    {
        printf '| %s | %s | agent consultation %d (rc=%d, text-blocks=%s); transcript `%s` |\n' \
            "$(date -u '+%FT%TZ')" "$stage" "$TRIAGE_COUNT" "$rc" "${said_something:-0}" \
            "$(basename "$jf")"
    } >>"$AGENT_TRANSCRIPT"
    return 0
}

# ------------------------------------------------------------ orchestration --
TRIAGE_COUNT=0
RETRYED_STAGES=""

stage_failed() { [ -f "$EPYC_STATE/$1.fail" ]; }
stage_done()   { [ -f "$EPYC_STATE/$1.done" ]; }
already_retried() { case " $RETRYED_STAGES " in *" $1 "*) return 0 ;; esac; return 1; }

banner "agent-supervised run"
log "prompt    : $PROMPT"
log "config    : $OC_CONFIG"
log "agent     : $([ "$AGENT_OK" -eq 1 ] && echo "enabled ($MODEL)" || echo 'DISABLED — unattended')"
log "max triage: $MAX_TRIAGE consultation(s), $MAX_PER_STAGE fix attempt per stage"

# --- pass 1: the harness does the work --------------------------------------
# run_all.sh returns 0 even when individual stages fail (by design: a failed
# benchmark is recorded and stepped over), so we inspect the marker files
# afterwards rather than trusting its exit status.
if [ ${#RUN_ARGS[@]} -gt 0 ]; then
    log "invoking: run_all.sh ${RUN_ARGS[*]}"
else
    log "invoking: run_all.sh"
fi
bash "$EPYC_DIR/run_all.sh" ${RUN_ARGS[@]+"${RUN_ARGS[@]}"}
RUN_RC=$?
log "run_all.sh returned rc=$RUN_RC"

# Re-bind our own output paths. At startup epyc.env may not have existed, so
# EPYC_OUT was the bootstrap default; 00_preflight may have chosen a different
# directory, and run_all.sh migrates its ledgers. If we did not follow, the
# agent would be told to append findings to a path the collector never reads —
# a silently misplaced audit trail, which is the one artefact a human actually
# looks at in the morning.
rebind_outputs() {
    local bootstrap_out="$EPYC_OUT"
    local bootstrap_transcript="$AGENT_TRANSCRIPT"
    # shellcheck disable=SC1090
    [ -f "$EPYC_ENV_FILE" ] && . "$EPYC_ENV_FILE"
    if [ "$EPYC_OUT" != "$bootstrap_out" ]; then
        log "output dir relocated $bootstrap_out -> $EPYC_OUT (supervisor following)"
        mkdir -p "$EPYC_OUT/05_agent"
        for f in AGENT_FINDINGS.md; do
            [ -f "$bootstrap_out/$f" ] && mv -f "$bootstrap_out/$f" "$EPYC_OUT/$f"
        done
        [ -d "$bootstrap_out/05_agent" ] && cp -r "$bootstrap_out/05_agent/." "$EPYC_OUT/05_agent/" 2>/dev/null
        AGENT_LOG_DIR="$EPYC_OUT/05_agent"
        AGENT_TRANSCRIPT="$EPYC_OUT/AGENT_FINDINGS.md"
        AGENT_LOG="$AGENT_LOG_DIR/agent.log"
        log "  findings now at $AGENT_TRANSCRIPT"
    fi
}
rebind_outputs
: >>"$AGENT_TRANSCRIPT"

# --- triage loop ------------------------------------------------------------
# One pass is usually enough. The loop exists so that a fixed prerequisite (a
# rebuilt substrate, an installed package) can unblock the stages that were
# downstream of it.
pass=1
while :; do
    FAILED=""
    for m in "$EPYC_STATE"/*.fail; do
        [ -e "$m" ] || continue
        FAILED="$FAILED $(basename "$m" .fail)"
    done
    [ -n "$FAILED" ] || break

    banner "supervisor: $pass triage pass — failed stages:$FAILED"

    if [ "$AGENT_OK" -ne 1 ]; then
        warn "no agent available; recording the failures and stopping triage"
        {
            echo
            echo "## Unattended failures (no agent available)"
            for s in $FAILED; do
                echo "- \`$s\` — see \`$EPYC_OUT/\` for its log"
            done
        } >>"$AGENT_TRANSCRIPT"
        break
    fi

    if [ "$TRIAGE_COUNT" -ge "$MAX_TRIAGE" ]; then
        warn "triage budget exhausted; recording remaining failures"
        {
            echo
            echo "## Remaining failures (triage budget exhausted at $TRIAGE_COUNT)"
            for s in $FAILED; do
                echo "- \`$s\` — NOT triaged; see its log under \`$EPYC_OUT/\`"
            done
        } >>"$AGENT_TRANSCRIPT"
        break
    fi

    for s in $FAILED; do
        # Never re-consult on a stage already marked done, and never exceed the
        # per-stage attempt cap. This is the guard against the 6-hour retry loop.
        stage_done "$s" && { log "$s is now .done — clearing its .fail marker"; rm -f "$EPYC_STATE/$s.fail"; continue; }
        if already_retried "$s"; then
            warn "$s already had $MAX_PER_STAGE attempt(s); leaving it failed for the operator"
            {
                echo
                echo "## \`$s\` exhausted its $MAX_PER_STAGE fix attempt(s) — left failed"
                echo "Operator attention required. Log under \`$EPYC_OUT/\`."
            } >>"$AGENT_TRANSCRIPT"
            continue
        fi

        # Find the stage's most recent log to hand the agent.
        logf=$(find "$EPYC_OUT" -name "*.log" -newer "$EPYC_STATE/$s.fail" 2>/dev/null | head -1)
        [ -n "$logf" ] || logf=$(find "$EPYC_OUT" -path "*${s#*_}*" -name "*.log" 2>/dev/null | tail -1)
        [ -n "$logf" ] || logf="$EPYC_OUT/$(echo "$s" | sed 's/^[0-9]*_//').log"

        # How many fix attempts has this stage already had? Note: `grep -c`
        # prints 0 AND exits 1 when there are no matches, so the familiar
        # `$(grep -c ... || echo 0)` idiom emits two lines and poisons any
        # arithmetic. Count with a plain loop instead.
        attempts=0
        for r in $RETRYED_STAGES; do
            [ "$r" = "$s" ] && attempts=$((attempts + 1))
        done

        ask_agent "$s" "$logf" \
            "This is fix attempt $((attempts + 1)) of $MAX_PER_STAGE for this stage."
        RETRIED_STAGES="$RETRYED_STAGES $s"
    done

    # Re-drive the harness. Prerequisites are forced, so a fixed substrate or an
    # installed package will re-run and unblock whatever was waiting on it.
    pass=$((pass + 1))
    if [ "$pass" -gt $((MAX_TRIAGE + 2)) ]; then
        warn "pass limit reached; stopping"
        break
    fi
    banner "supervisor: re-running the harness (pass $pass)"
    bash "$EPYC_DIR/run_all.sh" ${RUN_ARGS[@]+"${RUN_ARGS[@]}"}
    log "run_all.sh returned rc=$?"
done

# --- epilogue ---------------------------------------------------------------
{
    echo
    echo "## Supervisor epilogue — $(date -u '+%FT%TZ')"
    echo
    echo "- agent consultations used: $TRIAGE_COUNT of $MAX_TRIAGE"
    [ -n "$SESSION_ID" ] && echo "- opencode session: \`$SESSION_ID\` (export with \`opencode export $SESSION_ID\`)"
    echo
    echo "### Stage outcomes"
    for m in "$EPYC_STATE"/*.done; do
        [ -e "$m" ] || continue
        printf -- '- PASS `%s`\n' "$(basename "$m" .done)"
    done
    for m in "$EPYC_STATE"/*.fail; do
        [ -e "$m" ] || continue
        printf -- '- **FAIL `%s`**\n' "$(basename "$m" .fail)"
    done
    for m in "$EPYC_STATE"/*.skip; do
        [ -e "$m" ] || continue
        printf -- '- SKIP `%s` — %s\n' "$(basename "$m" .skip)" "$(cat "$m.why" 2>/dev/null)"
    done
} >>"$AGENT_TRANSCRIPT"

# Always collect, even on failure — a partial rental still deserves a full,
# honest record, and the collection step is what verifies the integrity manifest.
banner "supervisor: collecting"
bash "$EPYC_DIR/90_collect.sh"
COLLECT_RC=$?

banner "SUPERVISED RUN COMPLETE"
log "findings : $AGENT_TRANSCRIPT"
log "agent log: $AGENT_LOG"
log "results  : $EPYC_OUT"
echo
grep -E '^\| `?[0-9]' "$AGENT_TRANSCRIPT" | tail -20 || true
echo
[ "$COLLECT_RC" -eq 0 ] || warn "90_collect.sh returned rc=$COLLECT_RC — read $EPYC_OUT/00_environment/COLLECTION_SUMMARY.txt"
exit 0
