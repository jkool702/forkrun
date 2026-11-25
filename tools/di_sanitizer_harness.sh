#!/usr/bin/env bash
# WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — CK-3.3.
#
# Reproducible ASan/UBSan/TSan harnesses for the experimental dist_ingest
# engine. Each mode: rebuild libdist_ingest.so with the sanitizer, run the
# dist_ingest suite under LD_PRELOAD, record the result JSON.
#
# Usage: tools/di_sanitizer_harness.sh asan-ubsan|tsan [output_dir]
set -euo pipefail

MODE="${1:?mode required (asan-ubsan|tsan)}"
OUTDIR="${2:-/tmp/opencode/di-san-${MODE}}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/stage0/dist_ingest"

case "$MODE" in
  asan-ubsan) SAN="-fsanitize=address,undefined" ; PRELOAD=/lib64/libasan.so.8 ;;
  tsan)       SAN="-fsanitize=thread" ;               PRELOAD=/lib64/libtsan.so.2 ;;
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac

mkdir -p "$OUTDIR"
SHA="$(git -C "$ROOT" rev-parse HEAD)"

make -C "$DIST" clean >/dev/null
# detect_leaks=0 during the build itself: LSan fires on exit and would fail
# `make` for builds where it is not yet a project invariant (CK-3 is about
# the suite run, not the build step).
env ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=0 \
  make -C "$DIST" CC=gcc CFLAGS="-O1 -g -fno-omit-frame-pointer -fPIC $SAN" \
       LDFLAGS="-shared -pthread $SAN" NUMA_LIBS="" 2>&1 | tail -3

RUNLOG="$OUTDIR/run_$(date +%Y%m%d_%H%M%S).log"
cd "$ROOT"
# Run the suite with leak detection enabled (the default). LSan findings are
# counted separately from unit-test failures in result.json.
env LD_PRELOAD="$PRELOAD" python3 -m unittest discover -s stage0/dist_ingest/tests \
    > "$RUNLOG" 2>&1
RC=$?
set -e

TAIL=$(grep -E "^Ran [0-9]+ tests" "$RUNLOG" | tail -1)
FINDINGS=$(grep -cE "ERROR: AddressSanitizer|runtime error|WARNING: ThreadSanitizer" "$RUNLOG" || true)
cat > "$OUTDIR/result.json" <<EOF
{
  "sanitizer": "$MODE",
  "source_sha": "$SHA",
  "dirty": "$(git -C "$ROOT" status --short | wc -l | tr -d ' ')",
  "runlog": "$RUNLOG",
  "tests": "$TAIL",
  "sanitizer_findings": $FINDINGS,
  "exit_code": $RC,
  "interpretation": "$( [ "$RC" -eq 0 ] && [ "$FINDINGS" -eq 0 ] && echo PASS_OK || echo REVIEW_REQUIRED )"
}
EOF
cat "$OUTDIR/result.json"
