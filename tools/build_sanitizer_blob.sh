#!/usr/bin/env bash
# Build one sanitizer (or normal) instrumented forkrun_ring .so.
#
# Usage: tools/build_sanitizer_blob.sh MODE ARCH OUT
#   MODE: normal | tsan | asan-ubsan
#   ARCH: x86-64-v2 | x86-64-v3 | x86-64-v4 (or native)
#   OUT:  output .so path
#
# Single source of truth for sanitizer build flags. The release workflow
# keeps its own (unsanitized) inline build; this script is the shared
# implementation used by the sanitizer-validation workflow and by local
# reproduction. It does NOT touch forkrun_ring.c or any frozen file.
set -euo pipefail

MODE="${1:?mode required (normal|tsan|asan-ubsan)}"
ARCH="${2:?arch required (x86-64-v2|v3|v4)}"
OUT="${3:?output path required}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
META="$ROOT/META"
FR_VERSION="unknown"
if [[ -f "$META" ]]; then
  FR_VERSION="$(grep -E '^VERSION:' "$META" | sed -E 's/^VERSION:[ \t]*//')"
fi

case "$MODE" in
  normal)      : ;;
  tsan)        : ;;
  asan-ubsan)  : ;;
  *) echo "unknown mode: $MODE" >&2; exit 2 ;;
esac

case "$ARCH" in
  x86-64-v2) MARCH="-march=x86-64-v2" ;;
  x86-64-v3) MARCH="-march=x86-64-v3" ;;
  x86-64-v4) MARCH="-march=x86-64-v4" ;;
  native)     MARCH="-march=native -mtune=native" ;;
  *) echo "unknown arch: $ARCH" >&2; exit 2 ;;
esac

INCLUDES="-I/usr/include/bash -I/usr/include/bash/include -I/usr/include/bash/builtins"

case "$MODE" in
  normal)
    OPT_FLAGS="-O3 -flto=auto -fno-strict-aliasing -fno-semantic-interposition -fomit-frame-pointer -fno-math-errno -ftree-loop-im -ftree-loop-ivcanon -fPIC"
    WARN_FLAGS="-DNDEBUG -Wall -Wextra"
    LINK_FLAGS="-Wl,-O1 -Wl,--as-needed -Wl,-Bsymbolic"
    DEPS=""
    ;;
  tsan)
    OPT_FLAGS="-Og -g -fno-omit-frame-pointer -fsanitize=thread -fno-strict-aliasing -fno-semantic-interposition -fno-math-errno -ftree-loop-im -ftree-loop-ivcanon -fPIC"
    WARN_FLAGS="-DNDEBUG -Wall -Wextra"
    LINK_FLAGS=""
    DEPS="libtsan"
    ;;
  asan-ubsan)
    OPT_FLAGS="-Og -g -fno-omit-frame-pointer -fsanitize=address,undefined -fno-strict-aliasing -fno-semantic-interposition -fno-math-errno -ftree-loop-im -ftree-loop-ivcanon -fPIC"
    WARN_FLAGS="-Wall -Wextra"
    LINK_FLAGS=""
    DEPS="libasan libubsan"
    ;;
esac

echo "MODE=$MODE ARCH=$ARCH OUT=$OUT FR_VERSION=${FR_VERSION}" >&2

# shellcheck disable=SC2086
gcc "$ROOT/forkrun_ring.c" \
  $OPT_FLAGS $WARN_FLAGS $LINK_FLAGS $INCLUDES \
  -DSHELL -DHAVE_CONFIG_H \
  "-DBUILD_OS=\"Linux\"" \
  "-DFORKRUN_RING_VERSION=\"${FR_VERSION}\"" \
  "-DBUILD_ARCH=\"$ARCH\"" \
  -shared $MARCH -o "$OUT" \
  -ldl -lrt

echo "built: $OUT" >&2
file "$OUT" >&2