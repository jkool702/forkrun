#include <stdio.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 1 | FORKRUN_CTX_FLAG_RAW;

int plugin_raw_v1(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)ctx;
    for (int i = 0; i < argc; i++) printf("%s\n", argv[i]);
    return 0;
}
