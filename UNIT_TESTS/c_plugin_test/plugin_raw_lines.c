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
