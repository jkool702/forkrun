// forkrun_plugin.h
#ifndef FORKRUN_PLUGIN_H
#define FORKRUN_PLUGIN_H

#include <stdint.h>

// Opt-in flag: define this in exactly ONE of your C files to receive the context
// int forkrun_use_ctx = 1;

struct forkrun_ctx {
    uint64_t batch_index;       // global batch sequence number
    uint64_t batch_offset;      // byte offset in input stream
    uint64_t batch_byte_length; // length of current batch in bytes
    uint32_t version;           // struct version, currently 1
    uint32_t worker_id;         // internal worker ID
    uint32_t node_id;           // NUMA node ID
    uint32_t num_kills;         // retry count for this batch (if failure recovery active)
    uint32_t numa_major;        // NUMA major sequence (0 if not NUMA)
    uint32_t numa_minor;        // NUMA minor sequence (0 if not NUMA)
    int32_t  fd_in;             // input memfd file descriptor
    char     delimiter;         // batch delimiter character
    uint8_t  cfg_state[3];      // global configuration state
};


/* === FUNCTION DEFINITION TEMPLATES ===
 *
 * 1. Standard Fast Path (2-arg):
 *    int my_func(int argc, char **argv) { ... }
 *
 * 2. Context-Aware Path (3-arg):
 *    int forkrun_use_ctx = 1;
 *    int my_func(int argc, char **argv, const struct forkrun_ctx *ctx) { ... }
 */

#endif // FORKRUN_PLUGIN_H
