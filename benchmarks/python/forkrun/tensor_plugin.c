/* Stage 0 forkrun side: token stream sum via the raw window.
 * Interprets the borrowed window as LE int32 tokens, sums as int64, prints
 * the sum. Output contract: decimal sum + newline (harness compares across
 * legs). This is the substrate-ceiling payload-delivery path that
 * Batch.data will formalize; the numpy frombuffer conversion is timed
 * separately in the harness (delivery vs conversion split). */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;

int tensor_sum_raw(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    if (!(ctx->flags_granted & FORKRUN_CTX_FLAG_RAW)) return 99;
    const unsigned char *data = (const unsigned char *)(uintptr_t)ctx->reserved[0];
    size_t len = (size_t)ctx->batch_byte_length;
    int64_t sum = 0;
    for (size_t i = 0; i + 4 <= len; i += 4) {
        int32_t v;
        memcpy(&v, data + i, 4);
        sum += v;
    }
    printf("%lld\n", (long long)sum);
    return 0;
}
