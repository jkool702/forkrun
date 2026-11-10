#!/usr/bin/env bash
# Stage 0 ONE-COMMAND campaign driver (work order §4/§7/§10):
#   build prerequisites -> corpus identity -> env-before -> campaign
#   -> 2x2 ablation -> ablation validity gate -> env-after -> report.
#
# Every step is required; none is silently skipped. A failure in any
# step aborts non-zero with the step's log path. The campaign lives in
# ONE unique directory under stage0/runs/<campaign-id>/ and the report
# consumes exactly that campaign's manifest.
#
# FORKRUN_DIAG_QUEUE is forced to 1 here and again in run_campaign.sh:
# per-node queue telemetry is mandatory evidence for every case.
set -euo pipefail
cd "$(dirname "$0")/.."

fail() { echo "stage0-run-all: FAILED at: $*" >&2; exit 1; }

export FORKRUN_DIAG_QUEUE=1
TRIALS=${TRIALS:-3}
SOURCE_SHA=${SOURCE_SHA:-$(git rev-parse HEAD)}
CAMPAIGN_ID=${CAMPAIGN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-${SOURCE_SHA:0:12}-$$}
RUN_DIR=${RUN_DIR:-stage0/runs/$CAMPAIGN_ID}

if [ -e "$RUN_DIR" ]; then
  if [ ! -d "$RUN_DIR" ] || \
     [ -n "$(find "$RUN_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    fail "run directory is not empty: $RUN_DIR (campaigns are immutable)"
  fi
fi
mkdir -p "$RUN_DIR/env" "$RUN_DIR/ablation" || fail "create $RUN_DIR"

echo "=== [1/7] build prerequisites (substrate + shim + plugin)"
make -f Makefile.substrate python-substrate udf || fail "substrate build"
gcc -O2 -shared -fPIC -o stage0/libstage0.so stage0/residency_shim.c -lnuma \
  || fail "residency shim build"
gcc -O3 -shared -fPIC -march=native -I ring_loadables \
  -o stage0/ml_plugin_light.so \
  python/benchmarks/ml/plugins/ml_plugin_light.c -lm \
  || fail "ml_plugin_light build"

echo "=== [2/7] corpus identity (regenerate only when the manifest disagrees)"
ensure_corpus() {
  local records=$1 variant=$2 path=$3 rc=0
  python3 - "$records" "$variant" "$path" "${STAGE0_VERIFY_CORPUS:-1}" <<'PYEOF' || rc=$?
import hashlib
import json
import os
import sys

records = int(sys.argv[1])
variant = sys.argv[2]
path = sys.argv[3]
verify = sys.argv[4] != "0"
manifest = path + ".manifest.json"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


doc = None
if os.path.isfile(path) and os.path.isfile(manifest):
    try:
        with open(manifest, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        doc = None

if doc is not None:
    same = (doc.get("records") == records
            and doc.get("variant") == variant
            and doc.get("bytes") == os.path.getsize(path))
    if same and verify:
        same = sha256(path) == doc.get("sha256")
    if same:
        print("corpus reuse: %s (%d records, %d bytes, sha256=%s)"
              % (path, records, doc["bytes"], str(doc.get("sha256"))[:16]))
        sys.exit(0)
    print("corpus mismatch: %s -- regenerating" % path)
sys.exit(3)
PYEOF
  if [ "$rc" -eq 0 ]; then return 0; fi
  if [ "$rc" -ne 3 ]; then fail "corpus verification: $path"; fi
  python3 stage0/make_corpus.py --records "$records" --variant "$variant" \
    --out "$path" || fail "corpus build: $path"
}
ensure_corpus 100000 light stage0/corpus/light_100k.txt
ensure_corpus 20000000 light stage0/corpus/light_20m.txt
ensure_corpus 60000000 light stage0/corpus/light_60m.txt

echo "=== [3/7] environment-before capture"
python3 stage0/env_capture.py --out "$RUN_DIR/env/env-before.json" \
  --run-id "$CAMPAIGN_ID" || fail "env-before capture"

echo "=== [4/7] campaign (TRIALS=$TRIALS per spec, id=$CAMPAIGN_ID)"
TRIALS="$TRIALS" bash stage0/run_campaign.sh \
  --out "$RUN_DIR" --campaign-id "$CAMPAIGN_ID" \
  --trials "$TRIALS" --source-sha "$SOURCE_SHA" \
  --env-before "$RUN_DIR/env/env-before.json" \
  --env-after "$RUN_DIR/env/env-after.json" \
  || fail "campaign had failed trials (see $RUN_DIR/campaign-manifest.json)"

echo "=== [5/7] 2x2 affinity/policy ablation"
ABLATION_ARGS=(--cells A,B,C,D --forms map-fault,write-path
  --campaign-id "$CAMPAIGN_ID" --json "$RUN_DIR/ablation/ablation.json")
if [ -n "${ABLATION_NODE_X:-}" ]; then
  ABLATION_ARGS+=(--node-x "$ABLATION_NODE_X")
fi
if [ -n "${ABLATION_NODE_Y:-}" ]; then
  ABLATION_ARGS+=(--node-y "$ABLATION_NODE_Y")
fi
python3 stage0/ablation_2x2.py "${ABLATION_ARGS[@]}" || fail "ablation"

echo "=== [6/7] ablation validity gate + environment-after capture"
if ! python3 - "$RUN_DIR/ablation/ablation.json" "$CAMPAIGN_ID" <<'PYEOF'
import json
import sys

sys.path.insert(0, "stage0")
import report  # noqa: E402

with open(sys.argv[1], encoding="utf-8") as fh:
    doc = json.load(fh)
ok, problems = report.ablation_ok(doc, sys.argv[2])
if not ok:
    for problem in problems:
        print("ablation: " + problem, file=sys.stderr)
    raise SystemExit(1)
print("ablation validity: PASS")
PYEOF
then
  fail "ablation validity gate"
fi
python3 stage0/env_capture.py --out "$RUN_DIR/env/env-after.json" \
  --run-id "$CAMPAIGN_ID" || fail "env-after capture"

echo "=== [7/7] report"
REPORT_ARGS=(--campaign "$RUN_DIR/campaign-manifest.json"
  --ablation "$RUN_DIR/ablation/ablation.json"
  --env-before "$RUN_DIR/env/env-before.json"
  --env-after "$RUN_DIR/env/env-after.json"
  --out "$RUN_DIR/report.md")
if [ -n "${BASELINE_COMPARE:-}" ]; then
  REPORT_ARGS+=(--baseline-compare "$BASELINE_COMPARE")
fi
python3 stage0/report.py "${REPORT_ARGS[@]}" || fail "report generation"
cp "$RUN_DIR/report.md" stage0/reports/stage0-report.md \
  || fail "copy report to stage0/reports/stage0-report.md"

echo "=== stage0 campaign complete"
echo "campaign id : $CAMPAIGN_ID"
echo "run dir     : $RUN_DIR"
echo "report      : stage0/reports/stage0-report.md"
echo "artifacts   : $RUN_DIR/campaign-manifest.json"
echo "              $RUN_DIR/ablation/ablation.json"
echo "              $RUN_DIR/env/env-before.json"
echo "              $RUN_DIR/env/env-after.json"
ls -lh stage0/reports/stage0-report.md
