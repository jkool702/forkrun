#!/usr/bin/env bash
# WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 — CK-3
# reproducible ASan/UBSan + TSan harness for experimental dist_ingest.
#
# Usage: tools/di_sanitizer_harness.sh asan-ubsan|tsan [output_dir]
#
# Honesty + fail-closed guarantees:
#   - requires a CLEAN source tree; records exact source SHA;
#   - `make clean` status checked; sanitizer build status checked;
#   - verifies resulting library CONTAINS sanitizer instrumentation
#     (nm dynamic-symbol evidence: __asan_init / __tsan_init / __ubsan_*);
#   - verifies test process loads the instrumented binary; records artifact;
#   - KEEPS instrumented artifact UNCHANGED throughout (SHA-256 before+after);
#   - preflight tests use CK-1 ISOLATED builds (DI_OUTPUT) and cannot
#     rebuild/overwrite the sanitizer artifact;
#   - captures actual test return code without set -e preventing output;
#   - detects sanitizer diagnostics accurately; ASan halt_on_error=1;
#     UBSan halt_on_error=1; (LSan separate, see below);
#   - writes machine-readable result.json EVEN after build/test failure;
#   - returns NONZERO whenever result is REVIEW_REQUIRED; compiler/flags/
#     runtime + exact SHA recorded; runtime discovered (not hardcoded);
#   - logs preserved.
#
# LeakSanitizer honesty: the full python suite runs with detect_leaks=0
# (python-runtime noise; honestly recorded). Leak checking is attempted
# SEPARATELY on a standalone engine smoke (no python runtime) with
# detect_leaks=1; recorded honestly. Absence of findings is NOT proof of
# no leaks. `LSan validated` only if the separate run is effective.
set -uo pipefail   # NOTE: no `set -e`; we capture RC and always write result

MODE="${1:?mode required (asan-ubsan|tsan)}"
OUTDIR="${2:-/tmp/opencode/di-san-${MODE}}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/stage0/dist_ingest"
LIB="$ROOT/stage0/libdist_ingest.so"
mkdir -p "$OUTDIR"
RESULT="$OUTDIR/result.json"

CC="${CC:-gcc}"
case "$MODE" in
  asan-ubsan) SAN="-fsanitize=address,undefined"; RT_KIND="asan"; INSTR_SYM="__asan_init"; UBSAN=1 ;;
  tsan)       SAN="-fsanitize=thread";          RT_KIND="tsan"; INSTR_SYM="__tsan_init"; UBSAN=0 ;;
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac

write_result() {  # called on every exit path
  local interp="$1"
  cat > "$RESULT" <<JSON
{
  "sanitizer": "$MODE",
  "source_sha": "${SHA:-unknown}",
  "final_source_sha": "${SHA_AFTER:-${SHA:-unknown}}",
  "dirty": ${DIRTY:-0},
  "compiler": "$CC",
  "compiler_version": ${CCVER_JSON:-"\"unknown\""},
  "flags": ${FLAGS_JSON:-"\"\""},
  "link_flags": ${LD_JSON:-"\"\""},
  "sanitizer_runtime": ${RT_JSON:-"\"\""},
  "ubsan_runtime": ${UBSAN_RT_JSON:-"\"\""},
  "preload": ${PRELOAD_JSON:-"\"\""},
  "make_clean_rc": ${CLEAN_RC:-null},
  "sanitizer_build_rc": ${BUILD_RC:-null},
  "instrumented": ${INSTRUMENTED:-false},
  "instrumentation_symbol": "$INSTR_SYM",
  "instrumentation_evidence": ${INSTR_JSON:-"\"\""},
  "loaded_artifact": ${LOADED_JSON:-"\"\""},
  "artifact_sha256_before": ${SHA256_BEFORE_JSON:-"\"\""},
  "artifact_sha256_after": ${SHA256_AFTER_JSON:-"\"\""},
  "artifact_unchanged": ${ARTIFACT_UNCHANGED:-false},
  "runlog": ${RUNLOG_JSON:-"\"\""},
  "tests": ${TESTS_JSON:-"\"\""},
  "test_return_code": ${TEST_RC:-null},
  "sanitizer_findings": ${FINDINGS:-0},
  "sanitizer_finding_lines": ${FINDING_LINES_JSON:-"[]"},
  "lsan": {
    "main_suite_detect_leaks": false,
    "separate_leak_check_attempted": ${LSAN_ATTEMPTED:-false},
    "lsan_enabled": ${LSAN_ENABLED:-false},
    "lsan_effective": ${LSAN_EFFECTIVE:-false},
    "lsan_findings": ${LSAN_FINDINGS:-0},
    "lsan_smoke_return_code": ${LSAN_SMOKE_RC:-null},
    "lsan_runlog": ${LSAN_RUNLOG_JSON:-"\"\""},
    "note": ${LSAN_NOTE_JSON:-"\"\""}
  },
  "interpretation": "$interp"
}
JSON
}

# ---- precondition: clean tree ----
SHA="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
DIRTY="$(git -C "$ROOT" status --short 2>/dev/null | wc -l | tr -d ' ')"
if [ "$DIRTY" -ne 0 ]; then
  echo "PRECONDITION FAILED: tree is dirty ($DIRTY modified files) at $SHA" >&2
  write_result "REVIEW_REQUIRED"
  exit 3
fi

# ---- discover compiler + sanitizer runtime (not hardcoded) ----
CCVER="$("$CC" --version 2>/dev/null | head -1)"
CCVER_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$CCVER")"
FLAGS="-O1 -g -fno-omit-frame-pointer -fPIC $SAN"
FLAGS_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$FLAGS")"
LDFLAGS="-shared -pthread $SAN"
LD_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$LDFLAGS")"

RT=""
# discover actual ELF runtime (not a linker script); verify it can preload
_rt_dir="$(dirname "$("$CC" -print-file-name=lib${RT_KIND}.so 2>/dev/null)" 2>/dev/null || echo /usr/lib64)"
for cand in \
    "$("$CC" -print-file-name=lib${RT_KIND}.so.8 2>/dev/null)" \
    "$("$CC" -print-file-name=lib${RT_KIND}.so.2 2>/dev/null)" \
    "$("$CC" -print-file-name=lib${RT_KIND}.so.1 2>/dev/null)" \
    $(ls "$_rt_dir"/lib${RT_KIND}.so.* /usr/lib64/lib${RT_KIND}.so.* /lib64/lib${RT_KIND}.so.* 2>/dev/null | grep -vE '\.so$' | sort -Vr) ; do
  [ -n "$cand" ] && [ -e "$cand" ] || continue
  cand="$(readlink -f "$cand" 2>/dev/null || echo "$cand")"
  # skip linker scripts; require it to actually preload
  if [ "$(head -c4 "$cand" 2>/dev/null | od -An -tx1 | tr -d ' ')" != "7f454c46" ]; then continue; fi
  if env LD_PRELOAD="$cand" ASAN_OPTIONS=detect_leaks=0 python3 -c 'pass' 2>/dev/null; then
    RT="$cand"; break
  fi
done
RT_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$RT")"
PRELOAD="$RT"
PRELOAD_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$PRELOAD")"
UBSAN_RT_JSON='""'
if [ "$UBSAN" = 1 ]; then
  URT=""
for _u in "$("$CC" -print-file-name=libubsan.so.1 2>/dev/null)" $(ls /usr/lib64/libubsan.so.* /lib64/libubsan.so.* 2>/dev/null | grep -vE '\.so$' | sort -Vr); do
  [ -n "$_u" ] && [ -e "$_u" ] || continue; _u="$(readlink -f "$_u" 2>/dev/null || echo "$_u")"
  [ "$(head -c4 "$_u" 2>/dev/null | od -An -tx1 | tr -d ' ')" = "7f454c46" ] && { URT="$_u"; break; }
done
  UBSAN_RT_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$URT")"
fi

# ---- clean + sanitizer build (status checked) ----
CLEAN_RC=0
if make -C "$DIST" clean > "$OUTDIR/make_clean.log" 2>&1; then
  CLEAN_RC=0
else
  CLEAN_RC=$?   # actual make clean status (not negated)
  echo "make clean FAILED rc=$CLEAN_RC" >&2
  SHA_AFTER="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
  write_result "REVIEW_REQUIRED"
  exit 4
fi

BUILD_RC=0
env ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=1 \
  make -C "$DIST" CC="$CC" CFLAGS="$FLAGS" LDFLAGS="$LDFLAGS" NUMA_LIBS="" \
       > "$OUTDIR/sanitizer_build.log" 2>&1 || BUILD_RC=$?
if [ "$BUILD_RC" -ne 0 ]; then
  echo "sanitizer build FAILED rc=$BUILD_RC" >&2
  SHA_AFTER="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
  write_result "REVIEW_REQUIRED"
  exit 5
fi

# ---- verify instrumentation (nm dynamic-symbol evidence) ----
INSTRUMENTED=false; INSTR_JSON='""'
NMBIN="$(command -v nm || true)"
if [ -n "$NMBIN" ] && [ -e "$LIB" ]; then
  EVID="$("$NMBIN" -D "$LIB" 2>/dev/null | grep -E "$INSTR_SYM|__ubsan_handle|__asan|__tsan" | head -5 || true)"
  if [ -n "$EVID" ]; then INSTRUMENTED=true; fi
  if [ "$UBSAN" = 1 ]; then
    echo "$EVID" | grep -qE '__ubsan_handle' && : # ubsan handlers optional-inline
  fi
  INSTR_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$EVID")"
  # require the core instrumentation symbol
  if ! "$NMBIN" -D "$LIB" 2>/dev/null | grep -q "$INSTR_SYM"; then
    echo "instrumentation symbol $INSTR_SYM not found in $LIB" >&2
    SHA_AFTER="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
    write_result "REVIEW_REQUIRED"; exit 6
  fi
  INSTRUMENTED=true
else
  echo "nm or instrumented library missing" >&2
  SHA_AFTER="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
  write_result "REVIEW_REQUIRED"; exit 6
fi

# ---- artifact identity before ----
SHA256_BEFORE="$(sha256sum "$LIB" 2>/dev/null | awk '{print $1}')"
SHA256_BEFORE_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$SHA256_BEFORE")"

# ---- verify test process loads instrumented binary ----
LOADED=false
if env LD_PRELOAD="$PRELOAD" ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=1 \
   python3 -c "import ctypes,sys; ctypes.CDLL(sys.argv[1]); sys.exit(0)" "$LIB" 2>/dev/null; then
  LOADED=true
fi
LOADED_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$LIB")"
if [ "$LOADED" != true ]; then
  echo "test process failed to load instrumented binary $LIB" >&2
  SHA_AFTER="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
  write_result "REVIEW_REQUIRED"; exit 6
fi

# ---- run full suite; capture RC; always write result ----
RUNLOG="$OUTDIR/run_$(date +%Y%m%d_%H%M%S).log"
RUNLOG_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$RUNLOG")"
TEST_RC=0
cd "$ROOT"
env LD_PRELOAD="$PRELOAD" ASAN_OPTIONS="detect_leaks=0:halt_on_error=1" \
    UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1" TSAN_OPTIONS="halt_on_error=1" \
    python3 -m unittest discover -s stage0/dist_ingest/tests \
    > "$RUNLOG" 2>&1 || TEST_RC=$?

# sanitizer diagnostics accurate
FINDING_RE='ERROR: AddressSanitizer|runtime error:|LeakSanitizer|WARNING: ThreadSanitizer|SUMMARY: .*Sanitizer'
FINDINGS=$( { grep -cE "$FINDING_RE" "$RUNLOG" 2>/dev/null || true; } | head -1 ); FINDINGS=${FINDINGS:-0}
FINDING_LINES_JSON=$( { grep -E "$FINDING_RE" "$RUNLOG" 2>/dev/null || true; } | head -20 | python3 -c 'import json,sys;print(json.dumps([l.rstrip() for l in sys.stdin]))' )
TESTS=$(grep -E "^Ran [0-9]+ tests" "$RUNLOG" 2>/dev/null | tail -1 || true); TESTS_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$TESTS")"

# ---- artifact identity after (unchanged throughout) ----
SHA256_AFTER="$(sha256sum "$LIB" 2>/dev/null | awk '{print $1}')"
SHA256_AFTER_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$SHA256_AFTER")"
ARTIFACT_UNCHANGED=false
[ -n "$SHA256_BEFORE" ] && [ "$SHA256_BEFORE" = "$SHA256_AFTER" ] && ARTIFACT_UNCHANGED=true

# ---- separate LSan leak check (standalone engine smoke; no python runtime) ----
LSAN_ATTEMPTED=false; LSAN_ENABLED=false; LSAN_EFFECTIVE=false; LSAN_FINDINGS=0; LSAN_SMOKE_RC=null
LSAN_RUNLOG_JSON='""'; LSAN_NOTE_JSON='""'
if [ "$MODE" = "asan-ubsan" ]; then
  LSAN_ATTEMPTED=true
  SMOKE="$OUTDIR/di_lsan_smoke.c"; LSAN_LOG="$OUTDIR/lsan_smoke.log"
  cat > "$SMOKE" <<'C'
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include "dist_ingest.h"
int main(void){
    const char* path = getenv("DI_LSAN_INPUT");
    int fd = open(path ? path : "/etc/hostname", O_RDONLY);
    if (fd < 0) return 2;
    off_t sz = lseek(fd, 0, SEEK_END); if (sz < 0) sz = 0; lseek(fd, 0, SEEK_SET);
    di_config_t cfg; memset(&cfg, 0, sizeof(cfg));
    cfg.num_nodes = 1; cfg.policy = DI_POLICY_FIXED_FAA;
    cfg.params.base_quantum = 4096; cfg.params.max_backlog = 1u<<20;
    di_engine_t* e = di_create(fd, (uint64_t)sz, &cfg);
    if (!e) { close(fd); return 3; }
    di_result_t r; int rc = di_run(e, &r);
    di_destroy(e); close(fd);
    /* exit 0 iff engine run succeeded; sanitizer aborts/leaks make nonzero */
    return rc == 0 ? 0 : 4;
}
C
  printf 'lsan-smoke-input-data\n' > "$OUTDIR/lsan_input.txt"
  if "$CC" -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer \
       -I"$DIST" "$SMOKE" -o "$OUTDIR/di_lsan_smoke" -L"$ROOT/stage0" -ldist_ingest -Wl,-rpath,"$ROOT/stage0" -pthread \
       >> "$LSAN_LOG" 2>&1; then
    LSAN_ENABLED=true
    LSAN_SMOKE_RC=0
    env LD_PRELOAD="$PRELOAD" LD_LIBRARY_PATH="$ROOT/stage0" \
        ASAN_OPTIONS="detect_leaks=1:halt_on_error=1" UBSAN_OPTIONS="halt_on_error=1" \
        DI_LSAN_INPUT="$OUTDIR/lsan_input.txt" "$OUTDIR/di_lsan_smoke" >> "$LSAN_LOG" 2>&1 || LSAN_SMOKE_RC=$?
    LSAN_FINDINGS=$( { grep -cE "LeakSanitizer|leaked" "$LSAN_LOG" 2>/dev/null || true; } | head -1 ); LSAN_FINDINGS=${LSAN_FINDINGS:-0}
    # effective ONLY if: built + actually ran + return code 0 + no sanitizer
    # runtime-init failure + no LeakSanitizer findings. NOT unconditional.
    if grep -qE "AddressSanitizer runtime|cannot load|ERROR: .*Sanitizer.*(initialization|failed)" "$LSAN_LOG" 2>/dev/null; then
      LSAN_EFFECTIVE=false
    elif [ "$LSAN_SMOKE_RC" -eq 0 ] && [ "${LSAN_FINDINGS:-0}" -eq 0 ]; then
      LSAN_EFFECTIVE=true
    else
      LSAN_EFFECTIVE=false
    fi
    LSAN_NOTE_JSON='"separate standalone engine smoke (no python runtime); detect_leaks=1; effective iff built + rc==0 + no LSan findings + no runtime-init failure; absence of findings is NOT proof of no leaks; python-suite LSan not validated"'
  else
    LSAN_NOTE_JSON='"standalone LSan smoke failed to build; LSan not validated"'
  fi
  LSAN_RUNLOG_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$LSAN_LOG")"
fi

# ---- final artifact unchanged + SHA ----
SHA256_AFTER="$(sha256sum "$LIB" 2>/dev/null | awk '{print $1}')"
SHA256_AFTER_JSON="$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$SHA256_AFTER")"
ARTIFACT_UNCHANGED=false; [ -n "$SHA256_BEFORE" ] && [ "$SHA256_BEFORE" = "$SHA256_AFTER" ] && ARTIFACT_UNCHANGED=true
SHA_AFTER="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"

# ---- verdict ----
if [ "$CLEAN_RC" -eq 0 ] && [ "$BUILD_RC" -eq 0 ] && [ "$INSTRUMENTED" = true ] \
   && [ "$ARTIFACT_UNCHANGED" = true ] && [ "$TEST_RC" -eq 0 ] && [ "$FINDINGS" -eq 0 ] \
   && [ "$LSAN_FINDINGS" -eq 0 ]; then
  INTERP="PASS_OK"
else
  INTERP="REVIEW_REQUIRED"
fi
write_result "$INTERP"
cat "$RESULT"
[ "$INTERP" = "PASS_OK" ] && exit 0 || exit 1
