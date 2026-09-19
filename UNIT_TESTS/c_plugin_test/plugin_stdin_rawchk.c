#include <stdint.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;
int plugin_stdin_rawchk(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    if (!(ctx->flags_granted & FORKRUN_CTX_FLAG_RAW)) return 99;
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
