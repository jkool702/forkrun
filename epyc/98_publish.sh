#!/usr/bin/env bash
# epyc/98_publish.sh — commit and push benchmark results to a results branch.
#
#   bash epyc/98_publish.sh [--label "stage 41_bench_numa5m"] [--dry-run]
#
# WHY THIS IS A SCRIPT AND NOT AN AGENT INSTRUCTION. The agent is good at
# diagnosing a stage failure and bad at remembering to do bookkeeping at 4am,
# and a half-remembered publish means a lost night of metered compute. So the
# harness calls this automatically after every benchmark stage, and the agent is
# additionally told to run it after any fix or re-run it performs. Both paths
# converge on the same script; neither depends on the other.
#
# WHAT GETS COMMITTED. Only $EPYC_OUT — logs, CSVs, markdown reports, audits,
# the integrity manifest, the agent's findings. Never the datasets (~56 GB), the
# venv, the substrate, the machine-local epyc/env/epyc.env, or the stage markers:
# those are per-machine state, and the last two in particular would make the
# results branch depend on which box produced it.
#
# THE INTEGRITY ANGLE. Each publish commit records the git SHA of the code that
# produced the results AND the SHA-256 of the integrity manifest taken at setup
# time. That matters because the results branch is the tamper-evident record: if
# the agent ever modified a Tier-1 file mid-run, the manifest committed alongside
# the results is the pre-tamper hash, so `git log -p` on the results branch
# shows the change even if the working tree no longer does.
#
# The results go to a DEDICATED BRANCH, never the code branch. That is what keeps
# a runaway agent from landing harness edits in NEW/REFACTOR2.12, and it leaves
# the operator to review and merge results at their leisure.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env_if_present

RESULTS_BRANCH="${EPYC_RESULTS_BRANCH:-epyc-rental-results}"
REMOTE="${EPYC_GIT_REMOTE:-origin}"
LABEL=""
DRY=0
MAXFILE_MB="${EPYC_PUBLISH_MAXFILE_MB:-20}"

while [ $# -gt 0 ]; do
    case "$1" in
        --label)   LABEL="$2"; shift 2 ;;
        --dry-run) DRY=1; shift ;;
        -h|--help)
            sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done
[ -n "$LABEL" ] || LABEL="results snapshot"

logf() { printf '%s  [publish] %s\n' "$(date -u '+%FT%TZ')" "$*" >&2; }

# ------------------------------------------------------------ preconditions --
[ -d "$EPYC_ROOT/.git" ] || { logf "not a git checkout ($EPYC_ROOT) — skipping"; exit 0; }
[ -d "$EPYC_OUT" ]      || { logf "no results dir yet ($EPYC_OUT) — skipping"; exit 0; }

# Results must live inside the checkout so the commit cannot reach outside it.
# If someone pointed EPYC_OUT at a separate big disk, mirror it into the repo
# rather than committing from an arbitrary path.
STAGE_DIR="$EPYC_ROOT/epyc-rental-out"
if [ "$(cd "$EPYC_OUT" 2>/dev/null && pwd -P)" != "$(cd "$STAGE_DIR" 2>/dev/null && pwd -P || echo "$STAGE_DIR")" ]; then
    logf "EPYC_OUT is outside the checkout — mirroring into $STAGE_DIR"
    [ "$DRY" -eq 1 ] || { mkdir -p "$STAGE_DIR"; cp -a "$EPYC_OUT/." "$STAGE_DIR/"; }
    PUBLISH_DIR="$STAGE_DIR"
else
    PUBLISH_DIR="$EPYC_OUT"
fi

# git identity. Do not invent one silently on a machine that has one configured.
if ! git -C "$EPYC_ROOT" config user.email >/dev/null 2>&1; then
    logf "git user.email is not set — cannot commit"
    logf "  set it with:  git -C $EPYC_ROOT config user.email 'you@example.com'"
    logf "                 git -C $EPYC_ROOT config user.name  'Your Name'"
    exit 1
fi
GIT_EMAIL=$(git -C "$EPYC_ROOT" config user.email)

# ---------------------------------------------------------------- size guard --
# A stray multi-GB log would make the push fail halfway and leave a mess. Find
# anything oversized BEFORE staging, and refuse to add it.
TOOBIG=$(find "$PUBLISH_DIR" -type f -size +"${MAXFILE_MB}"M 2>/dev/null | head -20)
SKIPPED_BIG=0
if [ -n "$TOOBIG" ]; then
    SKIPPED_BIG=$(printf '%s\n' "$TOOBIG" | grep -c .)
    logf "refusing to stage $SKIPPED_BIG file(s) larger than ${MAXFILE_MB} MB:"
    printf '%s\n' "$TOOBIG" | while read -r f; do
        logf "    $(du -h "$f" 2>/dev/null | cut -f1)  ${f#"$EPYC_ROOT"/}"
    done
    logf "  add a per-file exclude to .gitignore, or raise EPYC_PUBLISH_MAXFILE_MB"
fi

# ------------------------------------------------------------------ assemble --
# Stage into a THROWAWAY INDEX, not the real one. This does two things: it
# guarantees that nothing the agent or the operator happened to have staged is
# swept into a results commit, and it lets the commit be created WITHOUT moving
# the current branch (see below).
ADD_PATHS=(-- "$PUBLISH_DIR")
if [ "$SKIPPED_BIG" -gt 0 ]; then
    while read -r f; do
        ADD_PATHS+=(--exclude="$(basename "$f")")
    done <<<"$TOOBIG"
fi

[ "$DRY" -eq 1 ] && { logf "DRY RUN — would stage and commit $PUBLISH_DIR to '$RESULTS_BRANCH'"; exit 0; }

cd "$EPYC_ROOT" || exit 1

TMPIDX=$(mktemp)
trap 'rm -f "$TMPIDX"' EXIT
export GIT_INDEX_FILE="$TMPIDX"

# Start the throwaway index from the current tree so the results branch is a
# full, coherent snapshot of the code that produced the results, plus them.
git read-tree HEAD 2>/dev/null || git read-tree --empty
git add "${ADD_PATHS[@]}" 2>/dev/null

# Idempotency, checked the CORRECT way. "Did anything get staged?" compares the
# index against HEAD, and HEAD never contains the results — so that check
# reports a change on every single call and the run would accumulate a dozen
# empty commits. The meaningful question is whether the resulting TREE differs
# from the tree the results branch already points at.
TREE=$(git write-tree)
PREV=$(git rev-parse --verify -q "refs/heads/$RESULTS_BRANCH" 2>/dev/null || echo "")
if [ -n "$PREV" ]; then
    PREV_TREE=$(git rev-parse -q --verify "refs/heads/$RESULTS_BRANCH^{tree}" 2>/dev/null || echo "")
    if [ -n "$PREV_TREE" ] && [ "$PREV_TREE" = "$TREE" ]; then
        logf "nothing new for '$LABEL' (results tree unchanged) — no commit"
        exit 0
    fi
else
    PREV=$(git rev-parse HEAD)
fi
NFILES=$(git ls-files -- "$PUBLISH_DIR" | wc -l | tr -d ' ')

# ------------------------------------------------------------- provenance ----
CODE_SHA=$(git rev-parse HEAD)
CODE_DESC=$(git log -1 --pretty=%s 2>/dev/null | cut -c1-70)
ENGINE=$(awk '/^VERSION:/{print $2}' "$EPYC_ROOT/META" 2>/dev/null || echo unknown)
INTEG_HASH="none"
if [ -f "$PUBLISH_DIR/INTEGRITY.sha256" ]; then
    INTEG_HASH=$(sha256sum "$PUBLISH_DIR/INTEGRITY.sha256" | cut -d' ' -f1)
fi
TOPO="unknown"
# shellcheck disable=SC1090
[ -f "$EPYC_ENV_FILE" ] && . "$EPYC_ENV_FILE" 2>/dev/null
[ -n "${EPYC_NUMA_SHAPE:-}" ] && TOPO="$EPYC_NUMA_SHAPE / ${EPYC_NODES:-?} node(s) / ${EPYC_SOCKETS:-?} socket(s)"

MSG=$(cat <<EOF
publish: $LABEL

forkrun engine   : $ENGINE
code SHA         : $CODE_SHA
code subject     : $CODE_DESC
topology         : $TOPO
integrity sha256 : $INTEG_HASH
files            : $NFILES
published by     : epyc/98_publish.sh ($GIT_EMAIL)
published at     : $(date -u '+%FT%TZ')

Published to the '$RESULTS_BRANCH' branch, never to the code branch. The
integrity sha256 above is the SHA-256 of INTEGRITY.sha256 as written by
epyc/10_setup.sh before any benchmark ran. If a Tier-1 file (the validator,
the product, or the benchmark sources) was modified during the run, this hash
is the pre-modification anchor and 'git log -p' on this branch shows the diff.
EOF
)

# ------------------------------------------------------------- commit safely --
# Built with plumbing on purpose. A normal `git commit` MOVES THE CURRENT BRANCH,
# and this script runs up to a dozen times in a night — which would walk the
# operator's checked-out code branch (and its local ref) forward with a dozen
# results commits. Worse, a later `git push` of HEAD would then put them on the
# code branch.
#
#   read-tree HEAD      -> throwaway index = the current code tree
#   write-tree          -> the tree with results added
#   commit-tree         -> a commit object, with no ref moved
#   update-ref          -> point ONLY the results branch at it
#
# The result: HEAD never moves, the working tree is never touched, the real
# index is never touched, and a plain `git push` of the code branch can never
# carry results. Successive publishes chain onto the results branch's own tip,
# so its history is linear in publication order.
PARENT="$PREV"
COMMIT=$(printf '%s' "$MSG" | git commit-tree "$TREE" -p "$PARENT")
git update-ref "refs/heads/$RESULTS_BRANCH" "$COMMIT"
logf "committed $NFILES file(s) to $RESULTS_BRANCH: ${PARENT:0:9} -> ${COMMIT:0:9}"

unset GIT_INDEX_FILE
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" = "$RESULTS_BRANCH" ]; then
    warn "the results branch is currently CHECKED OUT ($CURRENT_BRANCH)."
    warn "  That should not happen while the harness is running. Continuing, but a"
    warn "  'git push' of HEAD would target the results branch."
fi
HEAD_NOW=$(git rev-parse HEAD)
[ "$HEAD_NOW" = "$CODE_SHA" ] || warn "HEAD moved during publish ($CODE_SHA -> $HEAD_NOW) — investigate"

# --------------------------------------------------------------------- push --
git push -q "$REMOTE" "refs/heads/$RESULTS_BRANCH:refs/heads/$RESULTS_BRANCH"
PUSH_RC=$?
if [ "$PUSH_RC" -ne 0 ]; then
    err "push to $REMOTE/$RESULTS_BRANCH FAILED (rc=$PUSH_RC)"
    err "  The results are safe on disk AND committed locally on '$RESULTS_BRANCH'."
    err "  Nothing was lost and the code branch is untouched."
    err "  Most likely an auth problem. Diagnose with:"
    err "      git -C $EPYC_ROOT push --dry-run $REMOTE refs/heads/$RESULTS_BRANCH"
    err "  For SSH:   ssh -T git@github.com"
    err "  For HTTPS: a PAT with 'repo' scope, cached by 'git credential approve'."
    err "  Then re-run:  bash epyc/98_publish.sh --label '$LABEL'"
    err "  (it is idempotent — an unchanged results dir is a no-op, so retry freely)"
    exit $PUSH_RC
fi
logf "pushed to $REMOTE/$RESULTS_BRANCH"
logf "  review with:  git fetch $REMOTE && git log --oneline $REMOTE/$RESULTS_BRANCH"
exit 0
