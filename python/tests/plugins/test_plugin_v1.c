/* python/tests/plugins/test_plugin_v1.c — v1 frozen-ABI fixtures (W-PY13).
 *
 * TEST-ONLY fixture (compiled at test time by test_v1_fast.py; never
 * shipped). Unlike test_plugin.c (the v0 72-byte fr_py_plugin_ctx
 * convention), this uses the REAL frozen engine ABI directly:
 *   #include "ring_loadables/forkrun_plugin.h"  (128-byte forkrun_ctx)
 * so a bash -C plugin works from Python v1 unchanged and vice versa.
 *
 * Contract exercised:
 * - The plugin opts into dialect 2 + FLAG_RAW via forkrun_use_ctx, so the
 *   shim delivers the borrowed window in ctx->reserved[0] (valid for the
 *   call only) with fd_in/batch_offset as the pread fallback identity.
 * - Output goes to STDOUT (fd 1), which the shim redirects into a capture
 *   memfd and frames into the worker's output memfd. This is the same
 *   stdout-capture contract bash -C relies on.
 * - A second entry point (process_argv) ignores the ctx window and uses
 *   argv, proving the non-RAW tokenized path through the same .so.
 * - always_fail returns nonzero for the poison-path lock-in.
 */

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "../../../ring_loadables/forkrun_plugin.h"

_Static_assert(sizeof(struct forkrun_ctx) == 128,
               "frozen ABI size drifted");

/* Dialect 2 + RAW window delivery. */
int forkrun_use_ctx = FORKRUN_CTX_ENABLE | FORKRUN_CTX_FLAG_RAW;

/* Uppercase via the borrowed RAW window; stdout is the output channel.
 * Efficient form (block transform + one fwrite): the per-byte fputc form
 * measures stdio locking, not dispatch. */
int process_v1(int argc, char **argv, const struct forkrun_ctx *ctx) {
    const char *in;
    char *buf;
    uint64_t n, i;
    size_t w;
    (void)argc;
    (void)argv;
    if (ctx == NULL)
        return -1;
    if (ctx->version < 2)
        return -1;
    n = ctx->batch_byte_length;
    if (n == 0)
        return 0; /* empty batch: success, no output */
    in = (const char *)(uintptr_t)ctx->reserved[0];
    if (in == NULL)
        return -1;
    buf = (char *)malloc(n > 0 ? n : 1);
    if (buf == NULL)
        return -2;
    for (i = 0; i < n; i++) {
        char c = in[i];
        buf[i] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : c;
    }
    w = fwrite(buf, 1, n, stdout);
    free(buf);
    if (w != n)
        return -2;
    if (fflush(stdout) != 0)
        return -2;
    return 0;
}

/* Identity check: proves batch_index/num_kills arrive through the real
 * ctx (writes "idx=<batch_index> kills=<num_kills>\n" to stdout). */
int identify_v1(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc;
    (void)argv;
    if (ctx == NULL)
        return -1;
    printf("idx=%llu kills=%u\n",
           (unsigned long long)ctx->batch_index, ctx->num_kills);
    if (fflush(stdout) != 0)
        return -2;
    return 0;
}

/* Always fails (poison-path lock-in for the v1 dispatch). */
int always_fail_v1(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc;
    (void)argv;
    (void)ctx;
    return 42;
}

/* ---- W-CR5: process-DEATH fixtures (distinct from always_fail_v1) ----
 *
 * always_fail_v1 returns 42: an ordinary failure the engine retries and
 * poisons. These instead KILL the worker outright, which is the case
 * external review flagged as untested: the launcher exits non-zero,
 * Python falls back and RE-RUNS THE WHOLE JOB, so any plugin with side
 * effects performs them at least twice.
 *
 * die_once_v1 appends a marker per invocation and SIGKILLs itself on
 * the first call only. After the rerun the marker file therefore holds
 * TWO entries for the batch that succeeded the first time -- which is
 * the at-least-once semantics, made observable rather than asserted.
 *
 * kill_path lets the test aim at a specific invocation.
 */
#include <signal.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

static void _append_marker(const char *tag) {
    const char *p = getenv("FORKRUN_TEST_SIDE_EFFECT_FILE");
    if (!p || !*p)
        return;
    FILE *f = fopen(p, "a");
    if (!f)
        return;
    fprintf(f, "%s\n", tag);
    fclose(f);
}

int die_once_v1(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    _append_marker("die_once");
    /* One-shot: a marker file makes the kill happen exactly once, so a
     * rerun of the job completes normally. */
    const char *k = getenv("FORKRUN_TEST_DIE_FILE");
    if (k && *k) {
        FILE *f = fopen(k, "r");
        if (!f) {
            f = fopen(k, "w");
            if (f) fclose(f);
            raise(SIGKILL);
        }
        fclose(f);
    } else {
        static int once = 0;
        if (!once) { once = 1; raise(SIGKILL); }
    }
    return 0;
}

/* Always dies. Used to show the cleanroom's fallback still returns
 * CORRECT BYTES even though the job cannot complete under the
 * cleanroom -- i.e. the rerun is what saves it. */
int die_always_v1(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv; (void)ctx;
    _append_marker("die_always");
    raise(SIGKILL);
    return 0;
}

/* Pure side effect, never dies: proves the rerun duplicates work. */
int count_only_v1(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    _append_marker("count");
    return 0;
}
