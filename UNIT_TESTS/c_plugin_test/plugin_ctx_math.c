#include <stdio.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 1;

int plugin_ctx_math(int argc, char **argv, void *ctx_ptr) {
    struct forkrun_ctx *ctx = (struct forkrun_ctx *)ctx_ptr;
    printf("%lu\n", ctx->batch_byte_length);
    return 0;
}
