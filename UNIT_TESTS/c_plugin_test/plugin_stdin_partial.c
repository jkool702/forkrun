#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 2;
int plugin_stdin_partial(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    size_t len = (size_t)ctx->batch_byte_length;
    size_t cap = len < 100 ? len : 100;
    size_t got = 0;
    char buf[100];
    while (got < cap) {
        ssize_t n = read(STDIN_FILENO, buf + got, cap - got);
        if (n < 0) return 1;
        if (n == 0) break;
        got += (size_t)n;
    }
    printf("%lu/%lu\n", (unsigned long)got, (unsigned long)len);
    return 0;
}
