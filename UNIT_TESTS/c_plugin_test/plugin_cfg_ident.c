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
