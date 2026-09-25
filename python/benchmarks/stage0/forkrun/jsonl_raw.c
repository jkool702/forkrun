/* Stage 0 forkrun side: JSONL validation via the raw window (zero-copy).
 * Scans the borrowed window for '\n', validates each line minimally, and
 * writes the window verbatim. Output contract: byte-identical to input.
 * The argv-vs-raw delta is the copy-vs-zero-copy localization signal. */
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;

int jsonl_parse_raw(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    if (!(ctx->flags_granted & FORKRUN_CTX_FLAG_RAW)) return 99;
    const char *data = (const char *)(uintptr_t)ctx->reserved[0];
    size_t len = (size_t)ctx->batch_byte_length;
    size_t rec = 0;
    for (size_t i = 0; i < len; i++) {
        if (data[i] == '\n') {
            if (rec < 2 || data[i - rec] != '{' || data[i - 1] != '}')
                return 1;
            rec = 0;
        } else {
            if (rec == 0 && data[i] != '{') return 1;
            rec++;
        }
    }
    size_t off = 0;
    while (off < len) {
        ssize_t w = write(STDOUT_FILENO, data + off, len - off);
        if (w <= 0) return 1;
        off += (size_t)w;
    }
    return 0;
}
