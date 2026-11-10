#!/usr/bin/env bash
# Stage 0 campaign loop: run every spec N times inside ONE isolated,
# uniquely identified campaign directory.
#
# A campaign is immutable: the output directory must not already hold
# artifacts. The report consumes exactly the campaign manifest written
# here; stale trials from an earlier invocation cannot be mistaken for
# this one because they live in a different directory and carry a
# different campaign_id.
#
# Exit contract (work order §2.3/§7): keeps running independent trials
# after a failure (a failed trial never blocks the rest of the matrix),
# but finishes NON-ZERO with the exact failed case/trial list. The
# campaign manifest records the spec inventory, expected trial count,
# every outcome, and the environment-manifest references.
#
# FORKRUN_DIAG_QUEUE is forced to 1 for every trial: the per-node queue
# telemetry is REQUIRED evidence, not an operator memory test.
set -u
cd "$(dirname "$0")/.."

usage() {
  cat <<'EOF'
usage: run_campaign.sh [options]

  --out DIR            campaign directory (must be absent/empty)
  --campaign-id ID     unique id recorded in every trial
  --trials N           trials per spec (default $TRIALS or 3)
  --spec FILE          run this spec (repeatable); default stage0/specs/*.json
  --env-before PATH    environment manifest captured before trials
  --env-after PATH     environment manifest captured after trials
  --source-sha SHA     source identity (default: git rev-parse HEAD)
EOF
}

TRIALS=${TRIALS:-3}
OUT=""
CAMPAIGN_ID=""
ENV_BEFORE=""
ENV_AFTER=""
SOURCE_SHA=""
declare -a SPEC_FILES=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --out) OUT=${2:?--out needs a value}; shift 2 ;;
    --campaign-id) CAMPAIGN_ID=${2:?--campaign-id needs a value}; shift 2 ;;
    --trials) TRIALS=${2:?--trials needs a value}; shift 2 ;;
    --spec) SPEC_FILES+=("${2:?--spec needs a value}"); shift 2 ;;
    --env-before) ENV_BEFORE=${2:?--env-before needs a value}; shift 2 ;;
    --env-after) ENV_AFTER=${2:?--env-after needs a value}; shift 2 ;;
    --source-sha) SOURCE_SHA=${2:?--source-sha needs a value}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "campaign: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$TRIALS" in
  ''|*[!0-9]*) echo "campaign: --trials must be a positive integer" >&2
               exit 2 ;;
esac
if [ "$TRIALS" -lt 1 ]; then
  echo "campaign: --trials must be >= 1" >&2
  exit 2
fi

if [ -z "$SOURCE_SHA" ]; then
  SOURCE_SHA=$(git rev-parse HEAD) || {
    echo "campaign: cannot resolve git HEAD" >&2; exit 2; }
fi
if [ -z "$CAMPAIGN_ID" ]; then
  CAMPAIGN_ID="$(date -u +%Y%m%dT%H%M%SZ)-${SOURCE_SHA:0:12}-$$"
fi
if [ -z "$OUT" ]; then
  OUT="stage0/runs/$CAMPAIGN_ID"
fi

# Immutability: never mix this invocation's artifacts with a previous one.
if [ -e "$OUT" ]; then
  if [ ! -d "$OUT" ]; then
    echo "campaign: output path exists and is not a directory: $OUT" >&2
    exit 2
  fi
  if [ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    echo "campaign: output directory is not empty: $OUT" >&2
    echo "campaign: campaigns are immutable; choose a new --out/--campaign-id" >&2
    exit 2
  fi
else
  mkdir -p "$OUT" || exit 1
fi
mkdir -p "$OUT/cases" "$OUT/env" || exit 1

# Required evidence: the engine sampler is gated on this variable.
export FORKRUN_DIAG_QUEUE=1

if [ "${#SPEC_FILES[@]}" -eq 0 ]; then
  shopt -s nullglob
  SPEC_FILES=(stage0/specs/*.json)
  shopt -u nullglob
fi
if [ "${#SPEC_FILES[@]}" -eq 0 ]; then
  echo "campaign: no specs matched stage0/specs/*.json" >&2
  exit 2
fi
# Deterministic order independent of directory enumeration.
IFS=$'\n' SPEC_FILES=($(printf '%s\n' "${SPEC_FILES[@]}" | LC_ALL=C sort))
unset IFS

if [ -z "$ENV_BEFORE" ]; then
  ENV_BEFORE="$OUT/env/env-before.json"
fi
if [ -z "$ENV_AFTER" ]; then
  ENV_AFTER="$OUT/env/env-after.json"
fi
if [ ! -f "$ENV_BEFORE" ]; then
  python3 stage0/env_capture.py --out "$ENV_BEFORE" --run-id "$CAMPAIGN_ID" \
    || { echo "campaign: env-before capture failed" >&2; exit 1; }
fi

OUTCOMES="$OUT/.outcomes.tsv"
: > "$OUTCOMES" || exit 1

# Validate the spec inventory and write the manifest in its RUNNING
# state before any trial starts. A crashed campaign is therefore
# visibly incomplete (no outcomes) and the report rejects it.
SPEC_ARGS=()
for spec in "${SPEC_FILES[@]}"; do
  SPEC_ARGS+=(--spec "$spec")
done
python3 stage0/campaign_manifest.py start \
  --out "$OUT" --campaign-id "$CAMPAIGN_ID" --source-sha "$SOURCE_SHA" \
  --trials "$TRIALS" --env-before "$ENV_BEFORE" --env-after "$ENV_AFTER" \
  "${SPEC_ARGS[@]}" \
  || { echo "campaign: spec inventory/manifest start failed" >&2; exit 2; }

FAILURES=()
for spec in "${SPEC_FILES[@]}"; do
  id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["id"])' "$spec") \
    || { echo "campaign: cannot read spec id from $spec" >&2; exit 2; }
  for t in $(seq 1 "$TRIALS"); do
    out="$OUT/cases/$id/trial$t"
    mkdir -p "$out" || exit 1
    if python3 stage0/run_case.py --spec "$spec" --out "$out" \
         --campaign-id "$CAMPAIGN_ID" --trial "$t" \
         --source-sha "$SOURCE_SHA"; then
      status=ok
    else
      status=failed
      FAILURES+=("$id trial$t")
      echo "TRIAL FAILED: $id trial$t (see $out/manifest.json)" >&2
    fi
    printf '%s\t%s\t%s\t%s\n' "$id" "$t" "$status" \
      "cases/$id/trial$t/manifest.json" >> "$OUTCOMES" || exit 1
  done
done

python3 stage0/env_capture.py --out "$ENV_AFTER" --run-id "$CAMPAIGN_ID" \
  || { echo "campaign: env-after capture failed" >&2; exit 1; }

python3 stage0/campaign_manifest.py finish \
  --out "$OUT" --outcomes "$OUTCOMES" \
  || { echo "campaign: manifest finish failed" >&2; exit 1; }

if [ "${#FAILURES[@]}" -gt 0 ]; then
  echo "campaign: ${#FAILURES[@]} trial(s) failed:" >&2
  printf '  - %s\n' "${FAILURES[@]}" >&2
  echo "campaign: manifest: $OUT/campaign-manifest.json" >&2
  exit 1
fi
echo "campaign complete: $CAMPAIGN_ID ($OUT)"
