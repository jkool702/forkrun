#include <stdio.h>
#include <stdint.h>

int forkrun_use_ctx = 1;

struct forkrun_ctx {
    uint64_t batch_index;
    uint64_t batch_offset;
    uint64_t batch_byte_length;
    uint32_t version;
    uint32_t worker_id;
    uint32_t node_id;
    uint32_t num_kills;
    uint32_t numa_major;
    uint32_t numa_minor;
    int32_t  fd_in;
    char     delimiter;
    char     _pad[3];
};

int test_ctx_naked(int argc, char **argv, const struct forkrun_ctx *ctx) {
    if (ctx && ctx->version >= 1) {
        printf("CTX_NAKED: batch=%lu worker=%u node=%u retries=%u bytes=%lu\n",
               ctx->batch_index, ctx->worker_id, ctx->node_id, ctx->num_kills,
               ctx->batch_byte_length);
    }
    return 0;
}
