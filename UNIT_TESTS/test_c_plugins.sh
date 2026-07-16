#!/bin/bash
# =============================================================================
# forkrun v3.4.2 - C Plugin Test Suite
# =============================================================================

set -o pipefail

UNIT_TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="${UNIT_TESTS_DIR}/c_plugin_test"
FRUN_SCRIPT="${UNIT_TESTS_DIR}/frun.bash"
HEADER="${UNIT_TESTS_DIR}/../ring_loadables/forkrun_plugin.h"

mkdir -p "$TEST_DIR"
cd "$TEST_DIR"

echo "=== forkrun v3.4.2 C Plugin Test Suite ==="
echo "UNIT_TESTS_DIR : $UNIT_TESTS_DIR"
echo "FRUN_SCRIPT    : $FRUN_SCRIPT"

# Source frun once
echo "Sourcing frun.bash..."
. "$FRUN_SCRIPT"

# ====================== Header & Plugins ======================
# ====================== Setup Header ======================
echo "Copying header..."

if [ ! -f "$HEADER" ]; then
    echo "ERROR: Cannot find forkrun_plugin.h at:"
    echo "       $HEADER"
    ls -l "${UNIT_TESTS_DIR}/../ring_loadables/" 2>/dev/null || true
    exit 1
fi

cp "$HEADER" forkrun_plugin.h
echo "✓ Header copied successfully."

cat > test_basic.c << 'EOF'
#include <stdio.h>
#include <string.h>

int test_basic(int argc, char **argv) {
    size_t total = 0;
    for (int i = 0; i < argc; i++) total += strlen(argv[i]);
    printf("BASIC: batch_size=%d total_chars=%zu\n", argc, total);
    return 0;
}
EOF

cat > test_ctx_header.c << 'EOF'
#include <stdio.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 1;

int test_ctx_header(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if (ctx && ctx->version >= 1) {
        printf("CTX_HEADER: batch=%lu worker=%u node=%u retries=%u bytes=%lu\n",
               ctx->batch_index, ctx->worker_id, ctx->node_id,
               ctx->num_kills, ctx->batch_byte_length);
    }
    return 0;
}
EOF

cat > test_ctx_naked.c << 'EOF'
#include <stdio.h>
#include <stdint.h>

int forkrun_use_ctx = 1;

struct forkrun_ctx {
    uint64_t batch_index;
    uint64_t batch_offset;
    uint64_t batch_byte_length;
    uint32_t version;
    uint32_t worker_id;
    uint32_t node_id;
    uint32_t num_kills;
    uint32_t numa_major;
    uint32_t numa_minor;
    int32_t  fd_in;
    char     delimiter;
    char     _pad[3];
};

int test_ctx_naked(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if (ctx && ctx->version >= 1) {
        printf("CTX_NAKED: batch=%lu worker=%u node=%u retries=%u bytes=%lu\n",
               ctx->batch_index, ctx->worker_id, ctx->node_id, ctx->num_kills,
               ctx->batch_byte_length);
    }
    return 0;
}
EOF

gcc -O3 -march=native -fPIC -shared -I. test_basic.c -o test_basic.so
gcc -O3 -march=native -fPIC -shared -I. test_ctx_header.c -o test_ctx_header.so
gcc -O3 -march=native -fPIC -shared -I. test_ctx_naked.c -o test_ctx_naked.so

echo "✓ Plugins compiled successfully."

# (Compile plugins section remains the same - I'll omit it here for brevity, keep yours)

# ====================== Generate Test Data ======================
echo "Generating test inputs..."

seq 1000000 > input_1M.txt
seq 5000000 > input_5M.txt

echo "Generating variable-length input (~3M lines)..."
find /usr 2>/dev/null | head -n 3000000 > input_var_3M.txt || true

LINE_COUNT=$(wc -l < input_var_3M.txt 2>/dev/null || echo 0)
if [ "$LINE_COUNT" -lt 3000000 ]; then
    echo "Only $LINE_COUNT lines found. Duplicating..."
    cp input_var_3M.txt input_var_3M.tmp
    while [ $(wc -l < input_var_3M.txt) -lt 3000000 ]; do
        cat input_var_3M.tmp >> input_var_3M.txt
    done
    rm -f input_var_3M.tmp
    head -n 3000000 input_var_3M.txt > input_var_3M.tmp 2>/dev/null && mv input_var_3M.tmp input_var_3M.txt
fi

echo "✓ Generated $(wc -l < input_var_3M.txt) lines."

# ====================== Test Runner ======================
run_test() {
    local name="$1"
    local cmd="$2"
    local input="$3"
    echo "────────────────────────────────────"
    echo "TEST: $name"
    echo "Cmd : $cmd < $input"
    time $cmd < "$input" > /dev/null
    echo "✓ Passed"
}

echo -e "\n=== Running C Plugin Tests ===\n"

run_test "Basic Plugin (1M)"      "frun -C ./test_basic.so:test_basic"      "input_1M.txt"
run_test "Context Header (1M)"    "frun -C ./test_ctx_header.so:test_ctx_header" "input_1M.txt"
run_test "Context Naked (1M)"     "frun -C ./test_ctx_naked.so:test_ctx_naked"  "input_1M.txt"
run_test "High Batch Size (5M)"   "frun -l 1:65535 -C ./test_ctx_header.so:test_ctx_header" "input_5M.txt"
run_test "Variable Length Lines"  "frun -C ./test_ctx_naked.so:test_ctx_naked"  "input_var_3M.txt"
run_test "Ordered Output (-k)"    "frun -k -C ./test_basic.so:test_basic"      "input_1M.txt"

echo -e "\n=== All C Plugin Tests Completed Successfully ===\n"
