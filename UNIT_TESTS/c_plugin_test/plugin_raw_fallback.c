#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;

int plugin_raw_fallback(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if ((ctx->flags_granted & FORKRUN_CTX_FLAG_RAW)) {
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
    /* argv fallback (old-engine path) */
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
    return 0;
}
