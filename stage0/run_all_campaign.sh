#!/usr/bin/env bash
# Stage 0 ONE-COMMAND campaign driver (work order §4/§7/§10):
#   clean-source check -> build prerequisites -> corpus identity ->
#   env-before -> campaign -> 2x2 ablation -> ablation validity gate ->
#   env-after -> report.
#
# Every step is required; none is silently skipped. A failure in any
# step aborts non-zero with the step's log path. The campaign lives in
# ONE unique directory under stage0/runs/<campaign-id>/ and the report
# consumes exactly that campaign's manifest.
#
# FORKRUN_DIAG_QUEUE is forced to 1 here and again in run_campaign.sh:
# per-node queue telemetry is mandatory evidence for every case.
#
# Production invocation (from a CLEAN checkout):
#   TRIALS=3 bash stage0/run_all_campaign.sh
#
# Test/CI invocation (small spec, pre-made corpus, no report publish):
#   TRIALS=1 bash stage0/run_all_campaign.sh \
#       --spec stage0/tests/tiny.json --no-corpus --allow-dirty \
#       --run-dir /tmp/stage0-run --no-publish
set -euo pipefail
cd "$(dirname "$0")/.."

fail() { echo "stage0-run-all: FAILED at: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
usage: run_all_campaign.sh [options]

  --spec FILE          run this spec (repeatable); default stage0/specs/*.json
  --no-corpus          do not build/verify the standard corpora
  --trials N           trials per spec (default $TRIALS or 3)
  --campaign-id ID     campaign identity (default: UTC time + source sha + pid)
  --run-dir DIR        campaign directory (default stage0/runs/<campaign-id>)
  --report-out PATH    report path (default <run-dir>/report.md)
  --no-publish         do not copy the report to stage0/reports/
  --node-x N           ablation affinity node (default: ABLATION_NODE_X or auto)
  --node-y N           ablation MPOL_BIND node (default: ABLATION_NODE_Y or auto)
  --allow-dirty        permit a dirty source tree (test/rehearsal only; the
                       report validator still refuses dirty env manifests)
  -h, --help           show this help
EOF
}

TRIALS=${TRIALS:-3}
SOURCE_SHA=${SOURCE_SHA:-}
CAMPAIGN_ID=${CAMPAIGN_ID:-}
RUN_DIR=${RUN_DIR:-}
REPORT_OUT=${REPORT_OUT:-}
PUBLISH=1
ALLOW_DIRTY=0
NO_CORPUS=0
NODE_X=${ABLATION_NODE_X:-}
NODE_Y=${ABLATION_NODE_Y:-}
declare -a SPEC_FILES=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --spec) SPEC_FILES+=("${2:?--spec needs a value}"); shift 2 ;;
    --no-corpus) NO_CORPUS=1; shift ;;
    --trials) TRIALS=${2:?--trials needs a value}; shift 2 ;;
    --campaign-id) CAMPAIGN_ID=${2:?--campaign-id needs a value}; shift 2 ;;
    --run-dir) RUN_DIR=${2:?--run-dir needs a value}; shift 2 ;;
    --report-out) REPORT_OUT=${2:?--report-out needs a value}; shift 2 ;;
    --no-publish) PUBLISH=0; shift ;;
    --node-x) NODE_X=${2:?--node-x needs a value}; shift 2 ;;
    --node-y) NODE_Y=${2:?--node-y needs a value}; shift 2 ;;
    --allow-dirty) ALLOW_DIRTY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "stage0-run-all: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$TRIALS" in
  ''|*[!0-9]*) fail "--trials must be a positive integer" ;;
esac
[ "$TRIALS" -ge 1 ] || fail "--trials must be >= 1"

# ---------------------------------------------------------------------------
# Source identity. A campaign is only interpretable against the exact
# clean commit it ran from: a SHA alone does not identify dirty changes.
# ---------------------------------------------------------------------------
HEAD_SHA=$(git rev-parse HEAD) || fail "cannot resolve git HEAD"
if [ -z "$SOURCE_SHA" ]; then
  SOURCE_SHA=$HEAD_SHA
elif [ "$SOURCE_SHA" != "$HEAD_SHA" ]; then
  fail "SOURCE_SHA=$SOURCE_SHA does not match checked-out HEAD=$HEAD_SHA"
fi
if [ "$ALLOW_DIRTY" -eq 0 ]; then
  DIRTY=$(git status --porcelain) || fail "git status"
  if [ -n "$DIRTY" ]; then
    echo "$DIRTY" >&2
    fail "source tree is dirty; commit the exact source or pass \
--allow-dirty for a non-reportable rehearsal"
  fi
fi

export FORKRUN_DIAG_QUEUE=1
if [ -z "$CAMPAIGN_ID" ]; then
  CAMPAIGN_ID="$(date -u +%Y%m%dT%H%M%SZ)-${SOURCE_SHA:0:12}-$$"
fi
if [ -z "$RUN_DIR" ]; then
  RUN_DIR="stage0/runs/$CAMPAIGN_ID"
fi
if [ -z "$REPORT_OUT" ]; then
  REPORT_OUT="$RUN_DIR/report.md"
fi

if [ -e "$RUN_DIR" ]; then
  if [ ! -d "$RUN_DIR" ] || \
     [ -n "$(find "$RUN_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    fail "run directory is not empty: $RUN_DIR (campaigns are immutable)"
  fi
fi
mkdir -p "$RUN_DIR/env" || fail "create $RUN_DIR/env"

if [ "${#SPEC_FILES[@]}" -eq 0 ]; then
  shopt -s nullglob
  SPEC_FILES=(stage0/specs/*.json)
  shopt -u nullglob
fi
[ "${#SPEC_FILES[@]}" -gt 0 ] || fail "no specs matched stage0/specs/*.json"
IFS=$'\n' SPEC_FILES=($(printf '%s\n' "${SPEC_FILES[@]}" | LC_ALL=C sort))
unset IFS

echo "=== [1/7] build prerequisites (substrate + shim + plugin)"
make -f Makefile.substrate python-substrate udf || fail "substrate build"
gcc -O2 -shared -fPIC -o stage0/libstage0.so stage0/residency_shim.c -lnuma \
  || fail "residency shim build"
gcc -O3 -shared -fPIC -march=native -I ring_loadables \
  -o stage0/ml_plugin_light.so \
  python/benchmarks/ml/plugins/ml_plugin_light.c -lm \
  || fail "ml_plugin_light build"

if [ "$NO_CORPUS" -eq 0 ]; then
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
else
  echo "=== [2/7] corpus identity skipped (--no-corpus)"
fi

echo "=== [3/7] environment-before capture"
python3 stage0/env_capture.py --out "$RUN_DIR/env/env-before.json" \
  --run-id "$CAMPAIGN_ID" || fail "env-before capture"

echo "=== [4/7] campaign (TRIALS=$TRIALS per spec, id=$CAMPAIGN_ID)"
CAMPAIGN_ARGS=(--out "$RUN_DIR" --campaign-id "$CAMPAIGN_ID"
  --trials "$TRIALS" --source-sha "$SOURCE_SHA"
  --env-before "$RUN_DIR/env/env-before.json"
  --env-after "$RUN_DIR/env/env-after.json")
for spec in "${SPEC_FILES[@]}"; do
  CAMPAIGN_ARGS+=(--spec "$spec")
done
TRIALS="$TRIALS" bash stage0/run_campaign.sh "${CAMPAIGN_ARGS[@]}" \
  || fail "campaign had failed trials (see $RUN_DIR/campaign-manifest.json)"

echo "=== [5/7] 2x2 affinity/policy ablation"
ABLATION_ARGS=(--cells A,B,C,D --forms map-fault,write-path
  --campaign-id "$CAMPAIGN_ID" --json "$RUN_DIR/ablation/ablation.json")
if [ -n "$NODE_X" ]; then
  ABLATION_ARGS+=(--node-x "$NODE_X")
fi
if [ -n "$NODE_Y" ]; then
  ABLATION_ARGS+=(--node-y "$NODE_Y")
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
  --out "$REPORT_OUT")
if [ -n "${BASELINE_COMPARE:-}" ]; then
  REPORT_ARGS+=(--baseline-compare "$BASELINE_COMPARE")
fi
python3 stage0/report.py "${REPORT_ARGS[@]}" || fail "report generation"
if [ "$PUBLISH" -eq 1 ]; then
  cp "$REPORT_OUT" stage0/reports/stage0-report.md \
    || fail "copy report to stage0/reports/stage0-report.md"
fi

echo "=== stage0 campaign complete"
echo "campaign id : $CAMPAIGN_ID"
echo "source sha  : $SOURCE_SHA"
echo "run dir     : $RUN_DIR"
echo "report      : $REPORT_OUT"
if [ "$PUBLISH" -eq 1 ]; then
  echo "published   : stage0/reports/stage0-report.md"
fi
echo "artifacts   : $RUN_DIR/campaign-manifest.json"
echo "              $RUN_DIR/ablation/ablation.json"
echo "              $RUN_DIR/env/env-before.json"
echo "              $RUN_DIR/env/env-after.json"
ls -lh "$REPORT_OUT"
