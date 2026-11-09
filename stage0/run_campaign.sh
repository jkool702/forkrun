#!/usr/bin/env bash
# Stage 0 campaign loop: run each spec N times, keep every manifest.
#
# Exit contract (work order §2.3): keeps running independent trials
# after a failure (a failed trial never blocks the rest of the matrix),
# but finishes NON-ZERO with the exact failed case/trial list if any
# required trial failed. A campaign-level manifest records the
# requested trial count and every outcome.
set -u
cd "$(dirname "$0")/.."
TRIALS=${TRIALS:-3}
MANIFEST=${MANIFEST:-stage0/runs/campaign-manifest.json}
mkdir -p "$(dirname "$MANIFEST")"

shopt -s nullglob
specs=(stage0/specs/*.json)
shopt -u nullglob
if [ "${#specs[@]}" -eq 0 ]; then
  echo "campaign: no specs matched stage0/specs/*.json" >&2
  exit 2
fi

FAILURES=()
declare -a OUTCOMES
for spec in "${specs[@]}"; do
  id=$(basename "$spec" .json)
  for t in $(seq 1 "$TRIALS"); do
    out="stage0/runs/${id}/trial${t}"
    if python3 stage0/run_case.py --spec "$spec" --out "$out"; then
      OUTCOMES+=("$id/trial$t ok")
    else
      echo "TRIAL FAILED: $id trial$t (see $out/manifest.json)" >&2
      FAILURES+=("$id trial$t")
      OUTCOMES+=("$id/trial$t FAILED")
    fi
  done
done

python3 - "$MANIFEST" "${TRIALS}" "${OUTCOMES[@]}" <<'PYEOF'
import json, sys, time
manifest_path, trials = sys.argv[1], int(sys.argv[2])
outcomes = sys.argv[3:]
fails = [o for o in outcomes if o.endswith(" FAILED")]
doc = {"schema": "stage0-campaign/1", "trials_requested": trials,
       "finished_monotonic": time.monotonic(),
       "finished_epoch": time.time(), "outcomes": outcomes,
       "failures": fails, "all_ok": not fails}
with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2, sort_keys=True)
PYEOF

if [ "${#FAILURES[@]}" -gt 0 ]; then
  echo "campaign: ${#FAILURES[@]} trial(s) failed:" >&2
  printf '  - %s\n' "${FAILURES[@]}" >&2
  exit 1
fi
echo "campaign complete (all trials ok)"
