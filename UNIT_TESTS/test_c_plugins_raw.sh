#!/bin/bash
# =============================================================================
# forkrun v3.5.2 - C Plugin RAW Window Delivery Lock-in Tests (T-RAW-1..7)
# W-RAW: FLAG_RAW grants a borrowed zero-copy window in ctx->reserved[0].
# Plugins are compiled at test time against ring_loadables/forkrun_plugin.h.
# Requires an engine with FLAG_RAW live (v3.5.2+). Byte-exactness uses -k.
# =============================================================================

set -o pipefail

UNIT_TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="${UNIT_TESTS_DIR}/c_plugin_test"
FRUN_SCRIPT="${UNIT_TESTS_DIR}/../frun.bash"
HEADER="${UNIT_TESTS_DIR}/../ring_loadables/forkrun_plugin.h"

mkdir -p "$TEST_DIR"
cd "$TEST_DIR"

echo "=== forkrun v3.5.2 C Plugin RAW Window Delivery Tests (T-RAW-1..7) ==="

# Source frun
. "$FRUN_SCRIPT"

if [ ! -f "$HEADER" ]; then
    echo "ERROR: Cannot find forkrun_plugin.h at $HEADER"
    exit 1
fi
cp "$HEADER" forkrun_plugin.h

# ====================== Compile RAW plugins ======================
echo "Compiling RAW plugins..."

# T-RAW-1/5/7: raw echo — reads the borrowed window verbatim, fails if ungranted.
cat > plugin_raw_echo.c << 'EOF'
#include <stdint.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;

int plugin_raw_echo(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    if (!(ctx->flags_granted & FORKRUN_CTX_FLAG_RAW)) return 99;
    const char *data = (const char *)(uintptr_t)ctx->reserved[0];
    size_t len = (size_t)ctx->batch_byte_length;
    size_t off = 0;
    while (off < len) {
        ssize_t w = write(STDOUT_FILENO, data + off, len - off);
        if (w <= 0) return 1;
        off += (size_t)w;
    }
    return 0;
}
EOF

# T-RAW-2a: raw + argv fallback (docs pattern). Fails closed if ungranted here.
cat > plugin_raw_fallback.c << 'EOF'
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;

int plugin_raw_fallback(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if ((ctx->flags_granted & FORKRUN_CTX_FLAG_RAW)) {
        const char *data = (const char *)(uintptr_t)ctx->reserved[0];
        size_t len = (size_t)ctx->batch_byte_length;
        size_t off = 0;
        while (off < len) {
            ssize_t w = write(STDOUT_FILENO, data + off, len - off);
            if (w <= 0) return 1;
            off += (size_t)w;
        }
        return 0;
    }
    /* argv fallback (old-engine path) */
    for (int i = 0; i < argc; i++) {
        size_t n = strlen(argv[i]);
        size_t off = 0;
        while (off < n) {
            ssize_t w = write(STDOUT_FILENO, argv[i] + off, n - off);
            if (w <= 0) return 1;
            off += (size_t)w;
        }
        if (write(STDOUT_FILENO, "\n", 1) != 1) return 1;
    }
    return 0;
}
EOF

# T-RAW-2b: unknown-flag fallback simulation — requests a bit the engine has
# not made live, must observe it ungranted and take the argv path.
cat > plugin_fallback_argv.c << 'EOF'
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

#define FLAG_UNKNOWN (1u << 9)

int forkrun_use_ctx = 2 | FLAG_UNKNOWN;

int plugin_fallback_argv(int argc, char **argv, const struct forkrun_ctx *ctx) {
    /* The engine must not grant an unknown flag; take the argv fallback. */
    if ((ctx->flags_granted & FLAG_UNKNOWN)) return 99;
    for (int i = 0; i < argc; i++) {
        size_t n = strlen(argv[i]);
        size_t off = 0;
        while (off < n) {
            ssize_t w = write(STDOUT_FILENO, argv[i] + off, n - off);
            if (w <= 0) return 1;
            off += (size_t)w;
        }
        if (write(STDOUT_FILENO, "\n", 1) != 1) return 1;
    }
    return 0;
}
EOF

# T-RAW-3: delimiter/line-count metadata check.
cat > plugin_raw_lines.c << 'EOF'
#include <stdint.h>
#include <stdio.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;

int plugin_raw_lines(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    if (!(ctx->flags_granted & FORKRUN_CTX_FLAG_RAW)) return 99;
    const char *data = (const char *)(uintptr_t)ctx->reserved[0];
    size_t len = (size_t)ctx->batch_byte_length;
    char delim = ctx->delimiter;
    uint32_t counted = 0;
    for (size_t i = 0; i < len; i++) {
        if (data[i] == delim) counted++;
    }
    /* batch_lines is 0 (undefined) in -b byte mode; these tests run line mode. */
    printf("%u %u\n", counted, ctx->batch_lines);
    return 0;
}
EOF

# T-RAW-4: fixed args preserved alongside the window.
cat > plugin_raw_fixed.c << 'EOF'
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;

int plugin_raw_fixed(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if (!(ctx->flags_granted & FORKRUN_CTX_FLAG_RAW)) return 99;
    if (argc != 2) return 2;
    if (strcmp(argv[0], "--mode") != 0) return 2;
    if (strcmp(argv[1], "fast") != 0) return 2;
    const char *data = (const char *)(uintptr_t)ctx->reserved[0];
    size_t len = (size_t)ctx->batch_byte_length;
    size_t off = 0;
    while (off < len) {
        ssize_t w = write(STDOUT_FILENO, data + off, len - off);
        if (w <= 0) return 1;
        off += (size_t)w;
    }
    return 0;
}
EOF

# T-RAW-6: v1 dialect requesting RAW — must get argv + dlopen warning.
cat > plugin_raw_v1.c << 'EOF'
#include <stdio.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 1 | FORKRUN_CTX_FLAG_RAW;

int plugin_raw_v1(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)ctx;
    for (int i = 0; i < argc; i++) printf("%s\n", argv[i]);
    return 0;
}
EOF

gcc -O3 -shared -fPIC -I. plugin_raw_echo.c -o plugin_raw_echo.so
gcc -O3 -shared -fPIC -I. plugin_raw_fallback.c -o plugin_raw_fallback.so
gcc -O3 -shared -fPIC -I. plugin_fallback_argv.c -o plugin_fallback_argv.so
gcc -O3 -shared -fPIC -I. plugin_raw_lines.c -o plugin_raw_lines.so
gcc -O3 -shared -fPIC -I. plugin_raw_fixed.c -o plugin_raw_fixed.so
gcc -O3 -shared -fPIC -I. plugin_raw_v1.c -o plugin_raw_v1.so

echo "✓ RAW plugins compiled successfully."

# ====================== Test data ======================
echo "Generating test inputs..."
seq 10000 > input_raw_10k.txt
seq 200000 > input_raw_200k.txt

fail() {
    echo "✗ FAILED: $1"
    exit 1
}

echo "------------------------------------------------------"
echo "T-RAW-1: basic window read (10k lines, byte-exact)"
frun -k -C ./plugin_raw_echo.so:plugin_raw_echo < input_raw_10k.txt > out_raw_1.txt \
    || fail "frun rc != 0 (T-RAW-1)"
cmp -s input_raw_10k.txt out_raw_1.txt \
    || fail "output not byte-exact (T-RAW-1)"
echo "✓ Passed: grant negotiation + window population + pointer/length correct"

echo "------------------------------------------------------"
echo "T-RAW-2a: v2 plugin with argv fallback takes the raw path"
frun -k -C ./plugin_raw_fallback.so:plugin_raw_fallback < input_raw_10k.txt > out_raw_2a.txt \
    || fail "frun rc != 0 (T-RAW-2a)"
cmp -s input_raw_10k.txt out_raw_2a.txt \
    || fail "output not byte-exact (T-RAW-2a)"
echo "✓ Passed: raw path taken when granted"

echo "------------------------------------------------------"
echo "T-RAW-2b: unknown-flag fallback takes the argv path"
frun -k -C ./plugin_fallback_argv.so:plugin_fallback_argv < input_raw_10k.txt > out_raw_2b.txt \
    || fail "frun rc != 0 (T-RAW-2b)"
cmp -s input_raw_10k.txt out_raw_2b.txt \
    || fail "output not byte-exact (T-RAW-2b)"
echo "✓ Passed: argv fallback byte-exact when flag ungranted"

echo "------------------------------------------------------"
echo "T-RAW-3: batch_lines and delimiter metadata in ctx"
frun -k -C ./plugin_raw_lines.so:plugin_raw_lines < input_raw_10k.txt > out_raw_3.txt \
    || fail "frun rc != 0 (T-RAW-3)"
[ -s out_raw_3.txt ] || fail "no batches observed (T-RAW-3)"
awk '$1 != $2 { print "MISMATCH line " NR ": counted=" $1 " batch_lines=" $2; exit 1 }' out_raw_3.txt \
    || fail "delimiter count != batch_lines (T-RAW-3)"
echo "✓ Passed: delimiter scan matches batch_lines in every batch"

echo "------------------------------------------------------"
echo "T-RAW-4: fixed args preserved (--mode fast + window)"
frun -k -C ./plugin_raw_fixed.so:plugin_raw_fixed --mode fast < input_raw_10k.txt > out_raw_4.txt \
    || fail "frun rc != 0 (T-RAW-4; fixed args not delivered as argc=2)"
cmp -s input_raw_10k.txt out_raw_4.txt \
    || fail "output not byte-exact (T-RAW-4)"
echo "✓ Passed: argv has fixed args only, batch arrives via window"

echo "------------------------------------------------------"
echo "T-RAW-5: multi-batch window advancement (200k lines)"
frun -k -C ./plugin_raw_echo.so:plugin_raw_echo < input_raw_200k.txt > out_raw_5.txt \
    || fail "frun rc != 0 (T-RAW-5)"
cmp -s input_raw_200k.txt out_raw_5.txt \
    || fail "output not byte-exact across batches (T-RAW-5)"
echo "✓ Passed: mapping grows via mremap without mid-callback invalidation"

echo "------------------------------------------------------"
echo "T-RAW-6: v1 + RAW request warns and falls back to argv"
frun -k -C ./plugin_raw_v1.so:plugin_raw_v1 < input_raw_10k.txt > out_raw_6.txt 2> err_raw_6.txt \
    || fail "frun rc != 0 (T-RAW-6)"
cmp -s input_raw_10k.txt out_raw_6.txt \
    || fail "output not byte-exact (T-RAW-6)"
grep -q "FLAG_RAW" err_raw_6.txt \
    || fail "expected FLAG_RAW v1 warning on stderr (T-RAW-6)"
echo "✓ Passed: dlopen warning emitted, argv delivery correct"

echo "------------------------------------------------------"
echo "T-RAW-7: RAW overrides -s (window, not stdin feed)"
frun -k -C ./plugin_raw_echo.so:plugin_raw_echo -s < input_raw_10k.txt > out_raw_7.txt 2> err_raw_7.txt \
    || fail "frun rc != 0 (T-RAW-7)"
cmp -s input_raw_10k.txt out_raw_7.txt \
    || fail "output not byte-exact (T-RAW-7)"
if grep -q "FLAG_RAW" err_raw_7.txt; then
    fail "unexpected FLAG_RAW warning with v2 raw plugin (T-RAW-7)"
fi
echo "✓ Passed: -s does not divert or break raw window delivery"
echo "  (precedence lock-in: RAW wins over the W-STDIN stdin feed.
   W-STDIN must keep this test green unchanged.)"

echo "------------------------------------------------------"
echo "=== All RAW Window Delivery Tests Passed (T-RAW-1..7) ==="
rm -f out_raw_*.txt err_raw_*.txt input_raw_*.txt
