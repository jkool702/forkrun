#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 2;
int plugin_stdin_fixed(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if (argc != 1) return 2;
    if (strcmp(argv[0], "--flag") != 0) return 2;
    size_t want = (size_t)ctx->batch_byte_length;
    size_t got = 0;
    char buf[65536];
    while (got < want) {
        ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
        if (n < 0) return 1;
        if (n == 0) return 1;
        size_t off = 0;
        while (off < (size_t)n) {
            ssize_t w = write(STDOUT_FILENO, buf + off, (size_t)n - off);
            if (w <= 0) return 1;
            off += (size_t)w;
        }
        got += (size_t)n;
    }
    return 0;
}
