#!/bin/bash
# =============================================================================
# forkrun v3.5.2 - C Plugin Stdin Delivery Lock-in Tests (T-STDIN-1..9)
# W-STDIN: -C + (-s | -b) feeds the batch on the plugin's fd 0 (EOF framed);
# FLAG_RAW still wins (precedence). Plugins compile at test time against
# ring_loadables/forkrun_plugin.h. Requires a v3.5.2+ engine. Byte-exact
# legs use -k. NOTE on CLI grammar: frun flag parsing stops at the first
# positional, so -s/-k/-b/-E/-j precede `-C so:fn --fixed args` (same rule
# as the D1 fixed-args test in test_c_plugins_rigorous.sh).
# =============================================================================

set -o pipefail

UNIT_TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR="${UNIT_TESTS_DIR}/c_plugin_test"
FRUN_SCRIPT="${UNIT_TESTS_DIR}/../frun.bash"
HEADER="${UNIT_TESTS_DIR}/../ring_loadables/forkrun_plugin.h"

mkdir -p "$TEST_DIR"
cd "$TEST_DIR"

echo "=== forkrun v3.5.2 C Plugin Stdin Delivery Tests (T-STDIN-1..9) ==="

# Source frun
. "$FRUN_SCRIPT"

if [ ! -f "$HEADER" ]; then
    echo "ERROR: Cannot find forkrun_plugin.h at $HEADER"
    exit 1
fi
cp "$HEADER" forkrun_plugin.h

fail() {
    echo "✗ FAILED: $1"
    exit 1
}

# ====================== Compile stdin plugins ======================
echo "Compiling stdin plugins..."

# T-STDIN-1: v1 read-to-EOF (2-arg signature, no ctx at all).
cat > plugin_stdin_v1.c << 'EOF'
#include <unistd.h>
#include <sys/types.h>
int plugin_stdin_v1(int argc, char **argv) {
    (void)argc; (void)argv;
    char buf[65536];
    for (;;) {
        ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
        if (n < 0) return 1;
        if (n == 0) break;
        size_t off = 0;
        while (off < (size_t)n) {
            ssize_t w = write(STDOUT_FILENO, buf + off, (size_t)n - off);
            if (w <= 0) return 1;
            off += (size_t)w;
        }
    }
    return 0;
}
EOF

# T-STDIN-2/4/7/9: v2 length-bounded read.
cat > plugin_stdin_v2.c << 'EOF'
#include <stdint.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 2;
int plugin_stdin_v2(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    size_t want = (size_t)ctx->batch_byte_length;
    size_t got = 0;
    char buf[65536];
    while (got < want) {
        ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
        if (n < 0) return 1;
        if (n == 0) return 1; /* EOF early = infrastructure failure */
        size_t off = 0;
        while (off < (size_t)n) {
            ssize_t w = write(STDOUT_FILENO, buf + off, (size_t)n - off);
            if (w <= 0) return 1;
            off += (size_t)w;
        }
        got += (size_t)n;
    }
    return 0;
}
EOF

# T-STDIN-3: partial consumption — reads up to 100 bytes, returns without
# draining; reports read/total per batch. Short tail batches (< 100 bytes)
# are drained fully and report got/len equally.
cat > plugin_stdin_partial.c << 'EOF'
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 2;
int plugin_stdin_partial(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    size_t len = (size_t)ctx->batch_byte_length;
    size_t cap = len < 100 ? len : 100;
    size_t got = 0;
    char buf[100];
    while (got < cap) {
        ssize_t n = read(STDIN_FILENO, buf + got, cap - got);
        if (n < 0) return 1;
        if (n == 0) break;
        got += (size_t)n;
    }
    printf("%lu/%lu\n", (unsigned long)got, (unsigned long)len);
    return 0;
}
EOF

# T-STDIN-5: feeder SIGKILL mid-feed, self-injected once per worker process
# (num_kills == 0): the feeder is this process's child (PPid == getpid()),
# found via /proc. Killed batch short-reads and returns 1 (escrow/retry);
# retries drain normally. RETRY markers on stderr prove the fault landed.
cat > plugin_stdin_killfeed.c << 'EOF'
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <signal.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 2;
static void kill_feeder_child(void) {
    pid_t me = getpid();
    DIR *d = opendir("/proc");
    if (!d) return;
    struct dirent *e;
    while ((e = readdir(d)) != NULL) {
        pid_t pid = (pid_t)atoi(e->d_name);
        if (pid <= 1 || pid == me) continue;
        char path[64];
        snprintf(path, sizeof(path), "/proc/%d/stat", (int)pid);
        FILE *f = fopen(path, "r");
        if (!f) continue;
        char buf[1024];
        size_t n = fread(buf, 1, sizeof(buf) - 1, f);
        fclose(f);
        if (n == 0) continue;
        buf[n] = '\0';
        char *rp = strrchr(buf, ')');
        if (!rp) continue;
        int ppid = 0;
        if (sscanf(rp + 1, " %*c %d", &ppid) != 1) continue;
        if (ppid == (int)me) {
            if (kill(pid, SIGKILL) == 0)
                fprintf(stderr, "INJECT ok\n");
        }
    }
    closedir(d);
}
int plugin_stdin_killfeed(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    if (ctx->num_kills == 0) {
        kill_feeder_child();
    } else {
        fprintf(stderr, "RETRY batch=%lu kills=%u\n",
                (unsigned long)ctx->batch_index, ctx->num_kills);
    }
    size_t want = (size_t)ctx->batch_byte_length;
    size_t got = 0;
    char buf[65536];
    while (got < want) {
        ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
        if (n < 0) return 1;
        if (n == 0) return 1;
        size_t off = 0;
        while (off < (size_t)n) {
            ssize_t w = write(STDOUT_FILENO, buf + off, (size_t)n - off);
            if (w <= 0) return 1;
            off += (size_t)w;
        }
        got += (size_t)n;
    }
    return 0;
}
EOF

# T-STDIN-6: worker SIGKILL with a live feeder child. Sleeps inside the
# callback on one batch (feeder blocked mid-feed); the test kills this
# pid. Expect violent-death semantics (FATAL + checkpoint + rc != 0, no
# hang) — the orphaned feeder must EPIPE-exit, not mask the death pipe.
cat > plugin_stdin_sleepy.c << 'EOF'
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 2;
int plugin_stdin_sleepy(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    if (ctx->batch_index == 3 && ctx->num_kills == 0) {
        FILE *f = fopen("victim_batch3.pid", "w");
        if (f) { fprintf(f, "%d\n", (int)getpid()); fclose(f); }
        sleep(60);
    }
    size_t want = (size_t)ctx->batch_byte_length;
    size_t got = 0;
    char buf[65536];
    while (got < want) {
        ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
        if (n < 0) return 1;
        if (n == 0) return 1;
        size_t off = 0;
        while (off < (size_t)n) {
            ssize_t w = write(STDOUT_FILENO, buf + off, (size_t)n - off);
            if (w <= 0) return 1;
            off += (size_t)w;
        }
        got += (size_t)n;
    }
    return 0;
}
EOF

# T-STDIN-8: RAW override — FLAG_RAW plugin invoked with -s must get the
# window, never a stdin feed.
cat > plugin_stdin_rawchk.c << 'EOF'
#include <stdint.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;
int plugin_stdin_rawchk(int argc, char **argv, const struct forkrun_ctx *ctx) {
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

# T-STDIN-9: fixed args ride argv while data rides stdin.
cat > plugin_stdin_fixed.c << 'EOF'
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 2;
int plugin_stdin_fixed(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if (argc != 1) return 2;
    if (strcmp(argv[0], "--flag") != 0) return 2;
    size_t want = (size_t)ctx->batch_byte_length;
    size_t got = 0;
    char buf[65536];
    while (got < want) {
        ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
        if (n < 0) return 1;
        if (n == 0) return 1;
        size_t off = 0;
        while (off < (size_t)n) {
            ssize_t w = write(STDOUT_FILENO, buf + off, (size_t)n - off);
            if (w <= 0) return 1;
            off += (size_t)w;
        }
        got += (size_t)n;
    }
    return 0;
}
EOF

gcc -O3 -shared -fPIC -I. plugin_stdin_v1.c -o plugin_stdin_v1.so \
    || fail "compile plugin_stdin_v1"
gcc -O3 -shared -fPIC -I. plugin_stdin_v2.c -o plugin_stdin_v2.so \
    || fail "compile plugin_stdin_v2"
gcc -O3 -shared -fPIC -I. plugin_stdin_partial.c -o plugin_stdin_partial.so \
    || fail "compile plugin_stdin_partial"
gcc -O3 -shared -fPIC -I. plugin_stdin_killfeed.c -o plugin_stdin_killfeed.so \
    || fail "compile plugin_stdin_killfeed"
gcc -O3 -shared -fPIC -I. plugin_stdin_sleepy.c -o plugin_stdin_sleepy.so \
    || fail "compile plugin_stdin_sleepy"
gcc -O3 -shared -fPIC -I. plugin_stdin_rawchk.c -o plugin_stdin_rawchk.so \
    || fail "compile plugin_stdin_rawchk"
gcc -O3 -shared -fPIC -I. plugin_stdin_fixed.c -o plugin_stdin_fixed.so \
    || fail "compile plugin_stdin_fixed"

echo "✓ Stdin plugins compiled successfully."

# ====================== Test data ======================
echo "Generating test inputs..."
seq 10000 > input_stdin_10k.txt
seq 20000 > input_stdin_20k.txt
awk 'BEGIN{for(i=0;i<300000;i++) print "LARGE-BATCH-LINE-PAYLOAD-" i "-xxxxxxxxxxxx"}' \
    > input_stdin_large.txt
head -c 12582912 /dev/zero | tr '\0' 'A' > input_stdin_12M_A.txt
head -c 3000000 /dev/urandom > input_stdin_bin3M.dat

echo "------------------------------------------------------"
echo "T-STDIN-1: read-to-EOF conformance, v1 2-arg plugin (10k lines)"
frun -k -C ./plugin_stdin_v1.so:plugin_stdin_v1 -s < input_stdin_10k.txt > out_stdin_1.txt \
    || fail "frun rc != 0 (T-STDIN-1)"
cmp -s input_stdin_10k.txt out_stdin_1.txt \
    || fail "output not byte-exact (T-STDIN-1)"
echo "✓ Passed: pipe delivery + EOF framing, no argv data"

echo "------------------------------------------------------"
echo "T-STDIN-2: length-bounded read, v2 plugin (10k lines)"
frun -k -C ./plugin_stdin_v2.so:plugin_stdin_v2 -s < input_stdin_10k.txt > out_stdin_2.txt \
    || fail "frun rc != 0 (T-STDIN-2)"
cmp -s input_stdin_10k.txt out_stdin_2.txt \
    || fail "output not byte-exact (T-STDIN-2)"
echo "✓ Passed: ctx batch_byte_length accurate in stdin mode"

echo "------------------------------------------------------"
echo "T-STDIN-3a: partial consumption, line mode (-l 200, 20k lines)"
frun -k -l 200 -C ./plugin_stdin_partial.so:plugin_stdin_partial -s \
    < input_stdin_20k.txt > out_stdin_3a.txt \
    || fail "frun rc != 0 (T-STDIN-3a)"
[ "$(wc -l < out_stdin_3a.txt | tr -d ' ')" -ge 5 ] \
    || fail "too few batches to exercise discard (T-STDIN-3a)"
awk -F/ '{ want = ($2 > 100 ? 100 : $2); if ($1 != want) { print "DRIFT line " NR ": " $0; exit 1 } s += $2 } END { if (s != '"$(stat -c %s input_stdin_20k.txt)"') { print "BYTE SHORTFALL: " s; exit 1 } }' \
    out_stdin_3a.txt \
    || fail "read != min(100, len) — drift or corruption (T-STDIN-3a)"
echo "✓ Passed: unconsumed remainder discarded, no drift"

echo "------------------------------------------------------"
echo "T-STDIN-3b: partial consumption, large-tier discard (-b 2M, 12MB)"
frun -k -C ./plugin_stdin_partial.so:plugin_stdin_partial -s -b 2M \
    < input_stdin_12M_A.txt > out_stdin_3b.txt \
    || fail "frun rc != 0 (T-STDIN-3b)"
# Chunking-agnostic accountability: every batch exceeded the 100-byte
# partial read (fork-tier EPIPE discard each time) and the batch lengths
# sum to the input size (every byte delivered exactly once).
[ "$(wc -l < out_stdin_3b.txt | tr -d ' ')" -ge 6 ] \
    || fail "too few batches to exercise discard (T-STDIN-3b)"
awk -F/ '$1 != 100 || $2 <= 100 { print "BAD line " NR ": " $0; exit 1 } { s += $2 } END { if (s != '"$(stat -c %s input_stdin_12M_A.txt)"') { print "BYTE SHORTFALL: " s; exit 1 } }' \
    out_stdin_3b.txt \
    || fail "EPIPE-discard path broken (T-STDIN-3b)"
echo "✓ Passed: forked-feeder EPIPE discard, batch completes rc 0"

echo "------------------------------------------------------"
echo "T-STDIN-4: large batch concurrent feed (-b 4M, ~13MB)"
frun -k -b 4M -C ./plugin_stdin_v1.so:plugin_stdin_v1 -s \
    < input_stdin_large.txt > out_stdin_4.txt \
    || fail "frun rc != 0 (T-STDIN-4)"
cmp -s input_stdin_large.txt out_stdin_4.txt \
    || fail "output not byte-exact (T-STDIN-4)"
echo "✓ Passed: forked feed + SIGCHLD shield, feed/read overlap exact"

echo "------------------------------------------------------"
echo "T-STDIN-5: feeder SIGKILL mid-feed -> escrow -> retry (-E -b 4M)"
frun -k -E -b 4M -C ./plugin_stdin_killfeed.so:plugin_stdin_killfeed -s \
    < input_stdin_large.txt > out_stdin_5.txt 2> err_stdin_5.txt \
    || fail "frun rc != 0 (T-STDIN-5)"
cmp -s input_stdin_large.txt out_stdin_5.txt \
    || fail "output not byte-exact after retry (T-STDIN-5)"
grep -q "RETRY" err_stdin_5.txt \
    || fail "no RETRY marker — fault never landed, test vacuous (T-STDIN-5)"
echo "✓ Passed: feeder death reads as EOF-short, batch retried to success"

echo "------------------------------------------------------"
echo "T-STDIN-6: worker SIGKILL with live feeder child (violent death)"
rm -f victim_batch3.pid .forkrun_resume
frun -k -j 4 -E -b 4M -C ./plugin_stdin_sleepy.so:plugin_stdin_sleepy -s \
    < input_stdin_large.txt > out_stdin_6.txt 2> err_stdin_6.txt &
FRPID=$!
VIC=""
for _ in $(seq 1 60); do
    [ -f victim_batch3.pid ] && { VIC=$(cat victim_batch3.pid); break; }
    sleep 0.5
done
[ -n "$VIC" ] || { kill "$FRPID" 2>/dev/null; fail "victim batch never started (T-STDIN-6)"; }
kill -9 "$VIC"
# Bounded wait: hang here means the orphan masked the death pipe.
ALIVE=1
for _ in $(seq 1 180); do
    kill -0 "$FRPID" 2>/dev/null || { ALIVE=0; break; }
    sleep 0.5
done
if [ "$ALIVE" -eq 1 ]; then
    kill -9 "$FRPID" 2>/dev/null
    fail "pipeline hung after worker kill — orphan masked death pipe? (T-STDIN-6)"
fi
wait "$FRPID"
RC=$?
[ "$RC" -ne 0 ] || fail "expected non-zero rc on violent worker death (T-STDIN-6)"
grep -q "137" err_stdin_6.txt \
    || fail "worker 137 death not observed (T-STDIN-6)"
grep -qi "FATAL" err_stdin_6.txt \
    || fail "expected FATAL abort path (T-STDIN-6)"
[ -f .forkrun_resume ] \
    || fail "expected checkpoint file (T-STDIN-6)"
echo "✓ Passed: death detected unmasked (137), FATAL + checkpoint, no hang"

echo "------------------------------------------------------"
echo "T-STDIN-7: -b binary with NULs (3MB urandom, byte-exact incl NULs)"
frun -k -b 1M -C ./plugin_stdin_v1.so:plugin_stdin_v1 -s \
    < input_stdin_bin3M.dat > out_stdin_7.dat \
    || fail "frun rc != 0 (T-STDIN-7)"
cmp -s input_stdin_bin3M.dat out_stdin_7.dat \
    || fail "binary output differs incl NULs (T-STDIN-7)"
echo "✓ Passed: byte-transparent pipe, NUL-truncation gap closed"

echo "------------------------------------------------------"
echo "T-STDIN-8: RAW override — FLAG_RAW plugin with -s gets the window"
frun -k -C ./plugin_stdin_rawchk.so:plugin_stdin_rawchk -s \
    < input_stdin_10k.txt > out_stdin_8.txt 2> err_stdin_8.txt \
    || fail "frun rc != 0 (T-STDIN-8)"
cmp -s input_stdin_10k.txt out_stdin_8.txt \
    || fail "output not byte-exact (T-STDIN-8)"
if grep -q "FLAG_RAW" err_stdin_8.txt; then
    fail "unexpected FLAG_RAW warning with v2 raw plugin (T-STDIN-8)"
fi
echo "✓ Passed: precedence holds, no stdin feed, no warning, no hang"

echo "------------------------------------------------------"
echo "T-STDIN-9: fixed args ride argv while data rides stdin"
frun -k -s -C ./plugin_stdin_fixed.so:plugin_stdin_fixed --flag \
    < input_stdin_10k.txt > out_stdin_9.txt \
    || fail "frun rc != 0 (T-STDIN-9; fixed args not argc=1/--flag)"
cmp -s input_stdin_10k.txt out_stdin_9.txt \
    || fail "output not byte-exact (T-STDIN-9)"
echo "✓ Passed: argv has fixed args only, batch arrives on fd 0"

echo "------------------------------------------------------"
echo "=== All Stdin Delivery Tests Passed (T-STDIN-1..9) ==="
rm -f out_stdin_*.txt out_stdin_*.dat err_stdin_*.txt input_stdin_*.txt \
    input_stdin_*.dat victim_batch3.pid .forkrun_resume \
    plugin_stdin_*.c plugin_stdin_*.so
