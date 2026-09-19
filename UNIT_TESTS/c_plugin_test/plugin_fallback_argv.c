#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

#define FLAG_UNKNOWN (1u << 9)

int forkrun_use_ctx = 2 | FLAG_UNKNOWN;

int plugin_fallback_argv(int argc, char **argv, const struct forkrun_ctx *ctx) {
    /* The engine must not grant an unknown flag; take the argv fallback. */
    if ((ctx->flags_granted & FLAG_UNKNOWN)) return 99;
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
