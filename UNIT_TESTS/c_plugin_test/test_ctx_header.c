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
