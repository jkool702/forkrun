#!/bin/bash
# =============================================================================
# forkrun v3.2.2 - C Plugin Rigorous Test Suite
# =============================================================================

set -o pipefail

UNIT_TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="${UNIT_TESTS_DIR}/c_plugin_test"
FRUN_SCRIPT="${UNIT_TESTS_DIR}/../frun.bash"
HEADER="${UNIT_TESTS_DIR}/../ring_loadables/forkrun_plugin.h"

mkdir -p "$TEST_DIR"
cd "$TEST_DIR"

echo "=== forkrun v3.2.2 C Plugin Rigorous Test Suite ==="

# Source frun
. "$FRUN_SCRIPT"

if [ ! -f "$HEADER" ]; then
    echo "ERROR: Cannot find forkrun_plugin.h at $HEADER"
    exit 1
fi
cp "$HEADER" forkrun_plugin.h

# ====================== Compile Plugins ======================
echo "Compiling Native Plugins..."

# 1. Echo Plugin: Strictly prints what it receives
cat > plugin_echo.c << 'EOF'
#include <stdio.h>
int plugin_echo(int argc, char **argv) {
    for (int i = 0; i < argc; i++) printf("%s\n", argv[i]);
    return 0;
}
EOF

# 2. Context Math Plugin: Prints the byte length of each batch
cat > plugin_ctx_math.c << 'EOF'
#include <stdio.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 1;

int plugin_ctx_math(int argc, char **argv, void *ctx_ptr) {
    struct forkrun_ctx *ctx = (struct forkrun_ctx *)ctx_ptr;
    printf("%lu\n", ctx->batch_byte_length);
    return 0;
}
EOF

# 3. Poison/Retry Plugin: Intentionally fails the first time it sees batch #7
cat > plugin_poison.c << 'EOF'
#include <stdio.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 1;

int plugin_poison(int argc, char **argv, void *ctx_ptr) {
    struct forkrun_ctx *ctx = (struct forkrun_ctx *)ctx_ptr;

    // Simulate a segfault/crash on batch index 7, ONLY on the first attempt
    if (ctx->batch_index == 7 && ctx->num_kills == 0) {
        return 1; // Trigger failure!
    }

    // On retry (num_kills > 0) or normal batches, process normally
    for (int i = 0; i < argc; i++) printf("%s\n", argv[i]);
    return 0;
}
EOF

gcc -O3 -shared -fPIC -I. plugin_echo.c -o plugin_echo.so
gcc -O3 -shared -fPIC -I. plugin_ctx_math.c -o plugin_ctx_math.so
gcc -O3 -shared -fPIC -I. plugin_poison.c -o plugin_poison.so

# ====================== Generate Test Data ======================
echo "Generating Deterministic Test Inputs..."
seq 1 1000000 > input_1M.txt

# Create a variable length file via awk (much faster and more reliable than find /usr)
awk 'BEGIN { for(i=1;i<=500000;i++) {
    s="DATA-"; for(j=0;j<i%50;j++) s=s"X"; print s "-" i
}}' > input_var.txt

FILE_1M_BYTES=$(stat -c %s input_1M.txt)
FILE_VAR_BYTES=$(stat -c %s input_var.txt)

# ====================== Test Assertions ======================

echo "------------------------------------------------------"
echo "TEST 1: Ordered Data Integrity (-k + Basic Echo)"
# The output must exactly match the input file
frun -k -C ./plugin_echo.so:plugin_echo < input_1M.txt > out_1.txt
if cmp -s input_1M.txt out_1.txt; then
    echo "✓ Passed: Output perfectly matches input (Zero Data Loss)"
else
    echo "✗ FAILED: Data corruption in basic echo plugin"
    exit 1
fi

echo "------------------------------------------------------"
echo "TEST 2: Context Math & Byte Accountability"
# Sum of all batch_byte_length fields must equal the exact file size
frun -k -C ./plugin_ctx_math.so:plugin_ctx_math < input_var.txt > out_math.txt
# Sum the integers printed by the plugin
TOTAL_BYTES=$(awk '{s+=$1} END {print s}' out_math.txt)

if [ "$TOTAL_BYTES" -eq "$FILE_VAR_BYTES" ]; then
    echo "✓ Passed: Context batch_byte_length accurately tracks all $TOTAL_BYTES bytes"
else
    echo "✗ FAILED: Byte sum mismatch! Expected $FILE_VAR_BYTES, Got $TOTAL_BYTES"
    exit 1
fi

echo "------------------------------------------------------"
echo "TEST 3: Fault Injection & Retry Semantics (-E)"
# We use the poison plugin. It returns '1' on batch 7, triggering a worker death.
# With -E (Retry active), forkrun should respawn the worker, pass num_kills=1,
# and the plugin will succeed. Final output MUST still be perfectly ordered.
frun -k -E -C ./plugin_poison.so:plugin_poison < input_1M.txt > out_poison.txt
if cmp -s input_1M.txt out_poison.txt; then
    echo "✓ Passed: Poisoned batch successfully recovered and ordered exactly-once"
else
    echo "✗ FAILED: Data loss or sequence corruption during fault recovery"
    exit 1
fi

echo "------------------------------------------------------"
echo "=== All C Plugin Rigorous Tests Completed Successfully ==="
rm -f out_*.txt input_*.txt
