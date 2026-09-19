/* forkrun_plugin.h — ABI v2 (frozen at forkrun v3.5.0) */
#ifndef FORKRUN_PLUGIN_H
#define FORKRUN_PLUGIN_H

#include <stdint.h>

/* --- forkrun_use_ctx encoding (single exported request symbol) ---
 *   bits 0-7   : ABI dialect (1 = legacy ctx, 2 = current; bit31 must stay 0)
 *   bits 8-30  : optional behavior flags, negotiated per-engine
 *   bit  31    : MUST be zero (forkrun_use_ctx is a signed int; 1u<<31
 *                would make the value implementation-defined/negative)
 * Rules:
 *   - Engine masks dialect via (unsigned)v & 0xFF; unknown dialect => legacy
 *     2-arg dispatch (never guess). Unknown flags on a KNOWN dialect never
 *     cause legacy fallback; they are simply not granted.
 *   - Plugins must test ctx->version with >=, never ==.
 *   - Plugins check per-flag: (ctx->flags_granted & FLAG) != 0, and MUST
 *     implement the ungranted fallback path.
 *   - Flag bits are permanent once shipped; never recycle a retired number.
 */
#define FORKRUN_CTX_ENABLE          2u
#define FORKRUN_CTX_VERSION_MASK    0xFFu
#define FORKRUN_CTX_FLAG_RAW        (1u << 8)   /* v3.5.1: skip tokenization */

/* --- Behavior-flag registry ---
 * To add a flag:
 *   1. Allocate the next bit in definition order; NEVER reuse a retired
 *      number (bits are cheap, collisions are forever).
 *   2. Decide: pure behavior (no new state), or does it need a field?
 *      Fields come from reserved[] at a FIXED offset, populated only when
 *      the flag is granted, zero otherwise.
 *   3. Add the bit to ENGINE_KNOWN_FLAGS (engine-side only) when semantics
 *      ship -- NOT before. Engines that know no flags grant nothing.
 *   4. Plugins check per-flag and implement the ungranted fallback.
 * Changing the calling convention is a new DIALECT, not a flag.
 */

struct forkrun_ctx {
    uint64_t batch_index;       /*   0 : global batch sequence number      */
    uint64_t batch_offset;      /*   8 : byte offset in the shared memfd   */
    uint64_t batch_byte_length; /*  16 : batch length in bytes             */
    uint32_t version;           /*  24 : dialect the engine filled FOR YOU */
    uint32_t worker_id;         /*  28 : RING_WID                          */
    uint32_t node_id;           /*  32 : NUMA node id                      */
    uint32_t num_kills;         /*  36 : retry count for this batch        */
    union {
        uint64_t numa_batch_id; /*  40 : v2: packed (major<<22|minor)      */
        struct {                /*        v1: truncated 32-bit major/minor */
            uint32_t numa_major;
            uint32_t numa_minor;
        };
    };
    int32_t  fd_in;             /*  48 : read-only fd of the shared memfd  */
    char     delimiter;         /*  52 : record delimiter                  */
    uint8_t  cfg_state[4];      /*  53 : [0]=cfg_w [1]=cfg_l [2]=cfg_b
                                          [3]=flags(SH_STDIN|SH_BMODE)    */
    /* ---- v2 extension zone (append-only forever) ---- */
    uint32_t batch_lines;       /*  60 : records in batch; 0 = undefined
                                          (-b byte mode)                   */
    uint32_t struct_size;       /*  64 : sizeof(struct) as built by THIS
                                          engine; guard tail-field reads   */
    uint32_t worker_incarn;     /*  68 : respawn generation of this worker */
    uint32_t flags_granted;     /*  72 : req & ENGINE_KNOWN_FLAGS; dialect
                                          >= 2 only; else 0                */
    uint32_t reserved32;        /*  76 : zero; alignment                   */
    /*  80 : v3 fields land here; zero in v2, except:
     *        reserved[0] is `data` when FLAG_RAW is granted: a borrowed
     *        `const void *` to the batch's bytes in shared memory
     *        ([batch_offset, batch_offset + batch_byte_length)), valid
     *        for the duration of the callback only. Zero when FLAG_RAW
     *        is not granted. reserved[1..5] remain zero.
     *        Layout unchanged: this is documentation, not an ABI change. */
    uint64_t reserved[6];
};                              /* total: 128 bytes = one engine CACHE_LINE */

#endif /* FORKRUN_PLUGIN_H */
