#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;

int plugin_raw_fixed(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if (!(ctx->flags_granted & FORKRUN_CTX_FLAG_RAW)) return 99;
    if (argc != 2) return 2;
    if (strcmp(argv[0], "--mode") != 0) return 2;
    if (strcmp(argv[1], "fast") != 0) return 2;
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
