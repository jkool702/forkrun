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
