#!/usr/bin/env bash
# WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — CK-3: reproducible ASan/UBSan
# and TSan harnesses for the experimental dist_ingest engine.
#
# Usage: tools/di_sanitizer_harness.sh asan-ubsan|tsan [output_dir]
#
# Guarantees (review fix 2):
#   - Captures RC without set -e short-circuiting the result write.
#   - Requires a clean tree (dirty=0) at the tested source_sha.
#   - Result.json written even on failure, with exit_code + findings.
#   - LeakSanitizer diagnostics counted in sanitizer_findings.
#   - Does NOT rebuild libdist_ingest.so via di_preflight (the suite's
#     mandatory-build probes would clobber the instrumented artifact).
set -uo pipefail

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
SHA="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)"
DIRTY="$(git -C "$ROOT" status --short 2>/dev/null | wc -l | tr -d ' ')"
if [ "$DIRTY" -ne 0 ]; then
  echo "PRECONDITION FAILED: tree is dirty ($DIRTY modified files) at $SHA" >&2
  exit 3
fi

make -C "$DIST" clean >/dev/null 2>&1
# Build with sanitizers. detect_leaks=0 on the BUILD makes `make` not exit
# nonzero (LSan fires at gcc exit on some hosts).
env ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=0 \
  make -C "$DIST" CC=gcc CFLAGS="-O1 -g -fno-omit-frame-pointer -fPIC $SAN" \
       LDFLAGS="-shared -pthread $SAN" NUMA_LIBS="" >/dev/null 2>&1 || true

RUNLOG="$OUTDIR/run_$(date +%Y%m%d_%H%M%S).log"
cd "$ROOT"
RC=0
env LD_PRELOAD="$PRELOAD" ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=0 \
    python3 -m unittest discover -s stage0/dist_ingest/tests \
    > "$RUNLOG" 2>&1 || RC=$?

# Findings: AddressSanitizer/UBSan + LSan + TSan (explicit sets)
FINDINGS=$( { grep -cE "ERROR: AddressSanitizer|runtime error:|LeakSanitizer|WARNING: ThreadSanitizer" "$RUNLOG" || true; } | head -1)
TESTS=$(grep -E "^Ran [0-9]+ tests" "$RUNLOG" | tail -1)
RC_VALID=$([ -s "$RUNLOG" ] && echo 1 || echo 0)
cat > "$OUTDIR/result.json" <<EOF
{
  "sanitizer": "$MODE",
  "source_sha": "$SHA",
  "dirty": $DIRTY,
  "runlog": "$RUNLOG",
  "tests": "$TESTS",
  "sanitizer_findings": ${FINDINGS:-0},
  "exit_code": $RC,
  "runlog_nonempty": $RC_VALID,
  "interpretation": "$( [ "$RC" -eq 0 ] && [ "${FINDINGS:-0}" -eq 0 ] && echo PASS_OK || echo REVIEW_REQUIRED )"
}
EOF
cat "$OUTDIR/result.json"
exit 0
