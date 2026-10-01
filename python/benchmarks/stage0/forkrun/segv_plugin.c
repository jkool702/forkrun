/* Stage 0 fault harness: forkrun side. SIGSEGVs on the marked BATCH.
 * Fixed args: --mark <batch_index>. On the marked batch (first attempt
 * only) raises SIGSEGV in-process (worker dies 139 -> escrow/retry path).
 * Otherwise drains stdin to stdout verbatim (stdin delivery; run with -s).
 * Granularity note: incumbents fault on a marked ITEM, forkrun on a marked
 * BATCH — the tables record this asymmetry, no adjustment is made. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2;

int segv_marked(int argc, char **argv, const struct forkrun_ctx *ctx) {
    long mark = -1;
    for (int i = 0; i + 1 < argc; i++) {
        if (strcmp(argv[i], "--mark") == 0) { mark = atol(argv[i + 1]); break; }
    }
    if (mark >= 0 && (long)ctx->batch_index == mark && ctx->num_kills == 0) {
        fprintf(stderr, "FAULT-INJECT segv batch=%ld\n", mark);
        raise(SIGSEGV);
        _exit(139);
    }
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
