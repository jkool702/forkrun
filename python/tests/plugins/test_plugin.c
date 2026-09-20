/* python/tests/plugins/test_plugin.c — v0 Python-side C-callback fixtures.
 *
 * TEST-ONLY fixture (compiled at test time by test_plugin.py; never
 * shipped). Deliberately does NOT use ring_loadables/forkrun_plugin.h:
 * the v0 Python plugin convention (struct fr_py_plugin_ctx, explicit
 * in/out buffers) is distinct from the frozen engine ABI (128-byte
 * struct forkrun_ctx driven by ring_call). See _plugin.py's ABI HONESTY
 * NOTICE. v1 unifies the tiers through ring_call.
 *
 * Canonical layout (pinned both sides — C _Static_asserts here, ctypes
 * offset asserts in test_plugin.py::TestPluginLayout):
 */
#include <stddef.h>
#include <stdint.h>

struct fr_py_plugin_ctx {
    const void *data;      /*  0 */
    uint64_t data_len;     /*  8 */
    uint64_t batch_idx;    /* 16 */
    uint32_t flags;        /* 24 */
    uint32_t _pad0;        /* 28: explicit pad, never implicit alignment */
    void *out_buf;         /* 32 */
    uint64_t out_len;      /* 40 */
    uint64_t out_written;  /* 48 */
    uint64_t line_count;   /* 56 */
    void *user_data;       /* 64 */
}; /* total 72 */

_Static_assert(sizeof(struct fr_py_plugin_ctx) == 72,
               "fr_py_plugin_ctx size drifted");
_Static_assert(offsetof(struct fr_py_plugin_ctx, data) == 0,
               "data offset drifted");
_Static_assert(offsetof(struct fr_py_plugin_ctx, data_len) == 8,
               "data_len offset drifted");
_Static_assert(offsetof(struct fr_py_plugin_ctx, batch_idx) == 16,
               "batch_idx offset drifted");
_Static_assert(offsetof(struct fr_py_plugin_ctx, flags) == 24,
               "flags offset drifted");
_Static_assert(offsetof(struct fr_py_plugin_ctx, out_buf) == 32,
               "out_buf offset drifted");
_Static_assert(offsetof(struct fr_py_plugin_ctx, out_len) == 40,
               "out_len offset drifted");
_Static_assert(offsetof(struct fr_py_plugin_ctx, out_written) == 48,
               "out_written offset drifted");
_Static_assert(offsetof(struct fr_py_plugin_ctx, line_count) == 56,
               "line_count offset drifted");
_Static_assert(offsetof(struct fr_py_plugin_ctx, user_data) == 64,
               "user_data offset drifted");

/* Uppercases the input (tr a-z A-Z equivalent). Returns 0, or -2 when
 * the input exceeds the output buffer (v0 fixed 1MB exercises this). */
int process(struct fr_py_plugin_ctx *ctx) {
    uint64_t i, n;

    if (ctx == NULL || ctx->data == NULL || ctx->out_buf == NULL)
        return -1;
    n = ctx->data_len;
    if (n > ctx->out_len)
        return -2;
    {
        const char *in = (const char *)ctx->data;
        char *out = (char *)ctx->out_buf;
        for (i = 0; i < n; i++) {
            char c = in[i];
            out[i] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : c;
        }
    }
    ctx->out_written = n;
    return 0;
}

/* Writes "idx=<batch_idx>\n" — lets tests verify the ctx identity the
 * worker populated (batch_idx per batch). */
int identify(struct fr_py_plugin_ctx *ctx) {
    char tmp[32];
    int len = 0;
    uint64_t v;
    char rev[20];
    int nd = 0, i;

    if (ctx == NULL || ctx->out_buf == NULL)
        return -1;
    v = ctx->batch_idx;
    if (v == 0) {
        rev[nd++] = '0';
    } else {
        while (v > 0) {
            rev[nd++] = (char)('0' + (v % 10));
            v /= 10;
        }
    }
    tmp[0] = 'i';
    tmp[1] = 'd';
    tmp[2] = 'x';
    tmp[3] = '=';
    len = 4;
    for (i = nd - 1; i >= 0; i--)
        tmp[len++] = rev[i];
    tmp[len++] = '\n';
    if ((uint64_t)len > ctx->out_len)
        return -2;
    {
        char *out = (char *)ctx->out_buf;
        for (i = 0; i < len; i++)
            out[i] = tmp[i];
    }
    ctx->out_written = (uint64_t)len;
    return 0;
}

/* Always fails (poison-path lock-in). */
int always_fail(struct fr_py_plugin_ctx *ctx) {
    (void)ctx;
    return 42;
}
