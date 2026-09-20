/* Stage 0 engine-capability probes (compiled at harness time).
 * probe_raw_live: v2 + FLAG_RAW; returns 0 iff the engine grants RAW.
 * probe_stdin_live: ctx-less echo; the harness runs it with -s and checks
 * byte-exactness. rc distinguishes live (0) from legacy (!=0). */
#include <stdint.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 2 | FORKRUN_CTX_FLAG_RAW;

int probe_raw_live(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    if (ctx->version >= 2 && (ctx->flags_granted & FORKRUN_CTX_FLAG_RAW))
        return 0;
    return 99;
}
