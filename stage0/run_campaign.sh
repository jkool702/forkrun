#!/usr/bin/env bash
# Stage 0 campaign loop: run each spec N times, keep every manifest.
set -u
cd "$(dirname "$0")/.."
TRIALS=${TRIALS:-3}
for spec in stage0/specs/*.json; do
  id=$(basename "$spec" .json)
  for t in $(seq 1 "$TRIALS"); do
    out="stage0/runs/${id}/trial${t}"
    python3 stage0/run_case.py --spec "$spec" --out "$out" \
      || echo "TRIAL FAILED: $id trial$t (see $out/manifest.json)"
  done
done
echo "campaign complete"
