#!/bin/bash
# =============================================================================
# forkrun v3.5.2 - Worker Config Struct Lock-in Tests (T-CONFIG-1..4)
# W-STAGE1: the engine consumes fr_config_t (filled once at ring_worker inc)
# instead of per-call bash-surface reads; WorkerBatchState fields match
# fr_state_t. Behavior is unchanged by construction — these tests lock the
# CONTRACT the struct now carries: ctx identity, retry-limit override,
# ordered-mode transport, worker-local isolation.
#
# Invocation: standalone script (bash UNIT_TESTS/test_c_plugins_config.sh),
# NOT sourced into the comprehensive suite — direct frun calls are safe
# here (the test_c_plugins_rigorous.sh precedent).
#
# Engine selection: by default the suite drives the frun.bash-embedded blob
# (correct once CI rebuilds post-W-STAGE1). To exercise a locally built
# engine before the rebuild, export FORKRUN_TEST_LOCAL_SO=/path/to/.so —
# all builtins are then re-enabled from it after sourcing frun.bash.
# =============================================================================

set -o pipefail

UNIT_TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="${UNIT_TESTS_DIR}/c_plugin_test"
FRUN_SCRIPT="${UNIT_TESTS_DIR}/../frun.bash"
HEADER="${UNIT_TESTS_DIR}/../ring_loadables/forkrun_plugin.h"

mkdir -p "$TEST_DIR"
cd "$TEST_DIR"

echo "=== forkrun v3.5.2 Worker Config Struct Tests (T-CONFIG-1..4) ==="

# Source frun
. "$FRUN_SCRIPT"

# Optional local-engine override (pre-rebuild verification). enable -f with
# the FULL builtin list keeps all engine state in the one .so — never a mix
# of embedded + local (split state would fork globals/TLS across two images).
if [ -n "${FORKRUN_TEST_LOCAL_SO:-}" ]; then
    [ -f "$FORKRUN_TEST_LOCAL_SO" ] || { echo "ERROR: FORKRUN_TEST_LOCAL_SO missing: $FORKRUN_TEST_LOCAL_SO"; exit 1; }
    # shellcheck disable=SC2046
    enable -f "$FORKRUN_TEST_LOCAL_SO" $(ring_list) || { echo "ERROR: local engine override failed"; exit 1; }
    echo "engine override: $FORKRUN_TEST_LOCAL_SO ($(ring_version -V 2>/dev/null || ring_version | head -1))"
fi

if [ ! -f "$HEADER" ]; then
    echo "ERROR: Cannot find forkrun_plugin.h at $HEADER"
    exit 1
fi
cp "$HEADER" forkrun_plugin.h

# ====================== Compile CONFIG plugins ======================
echo "Compiling CONFIG plugins..."

# T-CONFIG-1/4: ctx identity — echoes batch lines on stdout, reports
# "wid incarn node" per batch on stderr. wid/incarn arrive via the struct
# path (ring_worker inc fill -> ring_call ctx population).
cat > plugin_cfg_ident.c << 'EOF'
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2;

int plugin_cfg_ident(int argc, char **argv, const struct forkrun_ctx *ctx) {
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
    fprintf(stderr, "CTX %u %u %u\n",
            ctx->worker_id, ctx->worker_incarn, ctx->node_id);
    return 0;
}
EOF

# T-CONFIG-2: marker poison — any batch containing the MARKER line fails
# unconditionally, so that batch rides escrow -> retry -> poison at the
# configured limit. All other batches echo normally.
cat > plugin_cfg_marker.c << 'EOF'
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 1;

int plugin_cfg_marker(int argc, char **argv, void *ctx_ptr) {
    (void)ctx_ptr;
    for (int i = 0; i < argc; i++) {
        if (strcmp(argv[i], "MARKER") == 0) return 1;
    }
    for (int i = 0; i < argc; i++) printf("%s\n", argv[i]);
    return 0;
}
EOF

gcc -O3 -shared -fPIC -I. plugin_cfg_ident.c -o plugin_cfg_ident.so
gcc -O3 -shared -fPIC -I. plugin_cfg_marker.c -o plugin_cfg_marker.so

echo "✓ CONFIG plugins compiled successfully."

# ====================== Test data ======================
echo "Generating test inputs..."
seq 50000 > input_cfg_50k.txt
{ seq 10000; echo MARKER; seq 10001 20000; } > input_cfg_marker.txt

fail() {
    echo "✗ FAILED: $1"
    exit 1
}

echo "------------------------------------------------------"
echo "T-CONFIG-1: ctx worker_id/incarn through the struct (ordered, byte-exact)"
frun -k -j 4 -C ./plugin_cfg_ident.so:plugin_cfg_ident < input_cfg_50k.txt > out_cfg_1.txt 2> err_cfg_1.txt \
    || fail "frun rc != 0 (T-CONFIG-1)"
cmp -s input_cfg_50k.txt out_cfg_1.txt \
    || fail "output not byte-exact (T-CONFIG-1)"
grep -q "^CTX " err_cfg_1.txt \
    || fail "no CTX identity lines observed (T-CONFIG-1)"
# wid/incarn are u32 ctx fields: an unfilled struct would surface here as
# 4294967295 (-1) or garbage; incarn is 0 on first spawn (no respawns here).
awk '$1 != "CTX" || $2 > 1024 || $3 != 0 { print "BAD CTX LINE: " $0; exit 1 }' err_cfg_1.txt \
    || fail "ctx identity out of range (T-CONFIG-1)"
echo "✓ Passed: plugin ctx identity sane (wid in range, incarn 0), output exact"

echo "------------------------------------------------------"
echo "T-CONFIG-2a: retry limit override via struct (FORKRUN_RETRY_LIMIT=2)"
FORKRUN_RETRY_LIMIT=2 frun -k -E -C ./plugin_cfg_marker.so:plugin_cfg_marker < input_cfg_marker.txt > out_cfg_2a.txt 2> err_cfg_2a.txt
rc=$?
[ "$rc" -eq 3 ] || fail "expected rc=3 (poison), got rc=$rc (T-CONFIG-2a)"
grep -q "Skipping poisoned batch .* (killed 2 times)" err_cfg_2a.txt \
    || fail "expected poison at exactly 2 kills (T-CONFIG-2a); saw: $(grep -h 'Skipping poisoned' err_cfg_2a.txt | head -2)"
echo "✓ Passed: struct carried the limit-2 override (poisoned after 2 kills)"

echo "------------------------------------------------------"
echo "T-CONFIG-2b: retry limit zero poisons on first failure (FORKRUN_RETRY_LIMIT=0)"
FORKRUN_RETRY_LIMIT=0 frun -k -E -C ./plugin_cfg_marker.so:plugin_cfg_marker < input_cfg_marker.txt > out_cfg_2b.txt 2> err_cfg_2b.txt
rc=$?
[ "$rc" -eq 3 ] || fail "expected rc=3 (poison), got rc=$rc (T-CONFIG-2b)"
grep -q "Skipping poisoned batch .* (killed 1 times)" err_cfg_2b.txt \
    || fail "expected poison at 1 kill with limit 0 (T-CONFIG-2b); saw: $(grep -h 'Skipping poisoned' err_cfg_2b.txt | head -2)"
echo "✓ Passed: limit-0 override honored (poisoned on first failure)"

echo "------------------------------------------------------"
echo "T-CONFIG-2c: default limit still 3 (control — no override)"
frun -k -E -C ./plugin_cfg_marker.so:plugin_cfg_marker < input_cfg_marker.txt > out_cfg_2c.txt 2> err_cfg_2c.txt
rc=$?
[ "$rc" -eq 3 ] || fail "expected rc=3 (poison), got rc=$rc (T-CONFIG-2c)"
grep -q "Skipping poisoned batch .* (killed 3 times)" err_cfg_2c.txt \
    || fail "expected default poison at 3 kills (T-CONFIG-2c); saw: $(grep -h 'Skipping poisoned' err_cfg_2c.txt | head -2)"
echo "✓ Passed: unset limit keeps the historical default-3 behavior"

echo "------------------------------------------------------"
echo "T-CONFIG-3: ordered-mode ack through the struct (byte-exact, -k)"
frun -k -j 4 -C ./plugin_cfg_ident.so:plugin_cfg_ident < input_cfg_50k.txt > out_cfg_3.txt 2> err_cfg_3.txt \
    || fail "frun rc != 0 (T-CONFIG-3)"
cmp -s input_cfg_50k.txt out_cfg_3.txt \
    || fail "ordered output not byte-exact (T-CONFIG-3)"
echo "✓ Passed: order-pipe fd from struct, output exactly-once in order"

echo "------------------------------------------------------"
echo "T-CONFIG-4: config isolation across workers (distinct worker_id)"
# -j 4 forces four workers over 50k lines: several batches per worker, so
# the CTX lines must show multiple distinct wids — all small. A struct
# accidentally placed in shared (not worker-local) storage would collapse
# every line onto one wid.
frun -k -j 4 -C ./plugin_cfg_ident.so:plugin_cfg_ident < input_cfg_50k.txt > out_cfg_4.txt 2> err_cfg_4.txt \
    || fail "frun rc != 0 (T-CONFIG-4)"
cmp -s input_cfg_50k.txt out_cfg_4.txt \
    || fail "output not byte-exact (T-CONFIG-4)"
nwid=$(awk '$1 == "CTX" { print $2 }' err_cfg_4.txt | sort -u | wc -l)
[ "$nwid" -ge 2 ] || fail "expected >= 2 distinct worker_id values, got $nwid (T-CONFIG-4)"
awk '$1 == "CTX" && $2 <= 1024 { next } { print "BAD CTX LINE: " $0; exit 1 }' err_cfg_4.txt \
    || fail "worker_id out of range (T-CONFIG-4)"
echo "✓ Passed: $nwid distinct worker_id values — struct is worker-local"

echo "------------------------------------------------------"
echo "=== All Worker Config Struct Tests Passed (T-CONFIG-1..4) ==="
rm -f out_cfg_*.txt err_cfg_*.txt input_cfg_*.txt
