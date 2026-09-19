/* python/forkrun/_shim.c — Python-facing substrate shim (W-PY1, Stage 4 Phase 1).
 *
 * Textually includes ../../forkrun_ring.c so this TU sees the engine's
 * static state (g_state/state, g_fr_config, my_numa_node, worker_last_*,
 * tls_batch_*, escrow pipes) and static helpers (do_lockfree_claim,
 * ring_init_main, ring_ack_main, ring_destroy_main, core_scanner_loop,
 * ring_call_ensure_ingress_map, pull_fire_alarm, robust_pipe_write).
 * forkrun_ring.c itself is UNMODIFIED — this file only ADDS new non-static
 * fr_py_* entry points that ctypes can dlsym. No bash in the path: callers
 * pass plain ints/fds, never WORD_LISTs or shell variables.
 *
 * Canonical order is preserved: this #include is the FIRST directive in the
 * TU (before any system/libc header of our own) so the engine's FTM block
 * (_GNU_SOURCE et al) still precedes the first libc include. Do not add
 * #includes above it.
 *
 * v0 scope: single-node UMA only (node 0). NUMA/multi-node, ordered output,
 * resume, and the C emitter are Stage 5/6. ack(-1,-1) is a deliberate
 * no-op disarm (no fallow/order pipes in v0): it computes the input window
 * from TLS and clears worker_last_cnt.
 */

#include "../../forkrun_ring.c"

/* Python-facing claim out-param. Identity fields mirror fr_state_t /
 * WorkerBatchState widths (batch_idx u64, major u64, minor/slots/num_kills/
 * poisoned u32); offset/length/lines carry the payload byte window which
 * fr_state_t deliberately excludes. Keep field order stable — ctypes binds
 * positionally. */
typedef struct fr_py_batch {
    uint64_t batch_idx;
    uint32_t slots;
    uint32_t lines;
    uint32_t num_kills;
    uint32_t poisoned;
    uint64_t offset;
    uint64_t length;
    uint64_t major;
    uint32_t minor;
} fr_py_batch_t;

/* Version string for the ctypes smoke check. FORKRUN_RING_VERSION has static
 * storage duration (string literal) — safe to return the pointer. */
const char *fr_py_version(void) {
    return FORKRUN_RING_VERSION;
}

/* Initialize the substrate for one UMA node. lines/bytes are mutually
 * exclusive (0 = default adaptive). Returns the engine rc (0 ok, 1 fail). */
int fr_py_init(int lines, int bytes) {
    if (lines < 0 || bytes < 0)
        return 1;
    if (lines > 0 && bytes > 0)
        return 1;
    char a0[] = "ring_init";
    char a1[64];
    char *argv[3];
    int argc = 1;
    argv[0] = a0;
    if (lines > 0) {
        snprintf(a1, sizeof(a1), "--lines=%d", lines);
        argv[argc++] = a1;
    } else if (bytes > 0) {
        snprintf(a1, sizeof(a1), "--bytes=%d", bytes);
        argv[argc++] = a1;
    }
    return ring_init_main(argc, argv);
}

/* Tear down substrate state (parent only; children os._exit without this). */
int fr_py_destroy(void) {
    char a0[] = "ring_destroy";
    char *argv[1];
    argv[0] = a0;
    return ring_destroy_main(1, argv);
}

/* Synchronously scan fd (memfd with input bytes, offset at 0) on node 0.
 * Publishes all slots and sets scanner_finished. Caller lseeks fd to 0
 * first AND calls fr_py_ingest_done() after the last byte is written:
 * the scanner treats ingest_complete as its EOF gate (pread returning 0
 * with ingest_complete clear means "wait for more", not EOF).
 * Returns engine rc. */
int fr_py_scan(int fd) {
    return core_scanner_loop(fd, 0, -1, 1, false);
}

/* Signal end of input (UMA): the scanner's EOF gate. Call after writing
 * the last byte to the ingress memfd and before fr_py_scan(). Mirrors
 * ring_ingest (which the bash pipeline calls when its copy finishes). */
int fr_py_ingest_done(void) {
    if (!state)
        return 1;
    __atomic_store_n(&state[0].ingest_complete, 1, __ATOMIC_RELEASE);
    return 0;
}

/* Initialize worker-local state in the CALLING process (call post-fork).
 * Fills g_fr_config directly — no env vars, no bash. Mirrors the
 * ring_worker inc fill point plus node resolution and active_workers
 * accounting. wid: worker slot id; node_id: -1 = auto (UMA: 0);
 * wincarn: respawn generation (v0: 0); retry_limit: poison threshold
 * (v0: 3, <0 = infinite); debug: 0/1. Returns 0 ok, 1 fail. */
int fr_py_worker_init(int wid, int node_id, int wincarn, int retry_limit,
                      int debug) {
    if (!state || !g_state)
        return 1;
    g_fr_config.ring_wid = wid;
    if (node_id >= 0 && node_id < (int)global_num_nodes)
        g_fr_config.ring_node_id = node_id;
    else
        g_fr_config.ring_node_id = -1;
    g_fr_config.ring_wincarn = wincarn;
    g_fr_config.fd_order_pipe = -1;
    g_fr_config.retry_limit = retry_limit;
    g_fr_config.debug = debug ? 1 : 0;
    g_fr_config.trap_ack_grace_ms = FR_TRAP_ACK_GRACE_MS_DEFAULT;
    g_fr_config.respawn_cap = -1;
    g_fr_config.spawn_ceiling = -1;
    g_fr_config_filled = true;
    g_debug = g_fr_config.debug;

    if (g_fr_config.ring_node_id >= 0)
        my_numa_node = g_fr_config.ring_node_id;
    else
        my_numa_node = 0;
    if (my_numa_node >= (int)global_num_nodes)
        my_numa_node = 0;
    __atomic_fetch_add(&state[my_numa_node].active_workers, 1,
                       __ATOMIC_SEQ_CST);
    return 0;
}

/* Claim one batch (blocking). Publishes TLS (worker_last_*, tls_batch_*)
 * exactly like ring_claim_main, decides poisoned from g_fr_config.retry_limit
 * (incl. the once-only poisoned_count increment and halt checks), fills
 * *out. Returns 0 success, 2 EOF, 1 failure/abort. Never touches bash
 * variables. */
int fr_py_claim(fr_py_batch_t *out) {
    struct WorkerBatchState batch;
    int rc;

    if (!out)
        return 1;
    if (my_numa_node == -1) {
        my_numa_node = 0;
        if (my_numa_node >= (int)global_num_nodes)
            my_numa_node = 0;
    }
    rc = do_lockfree_claim(&batch, true);
    if (rc != 0)
        return rc;

    worker_last_idx = batch.batch_idx;
    worker_last_cnt = batch.slots;
    worker_last_num_kills = batch.num_kills;
    worker_last_major = batch.major;
    worker_last_minor = batch.minor;
    tls_batch_lines = batch.lines;
    tls_batch_offset = (off_t)batch.offset;

    {
        uint32_t poisoned = 0;
        if (batch.num_kills > 0) {
            int limit = g_fr_config.retry_limit;
            if (limit >= 0 && batch.num_kills >= (uint32_t)limit) {
                uint32_t poison_threshold =
                    (limit > 0) ? (uint32_t)limit : 1;
                poisoned = 1;
                if (batch.num_kills == poison_threshold && g_state) {
                    uint32_t total_poisoned = __atomic_add_fetch(
                        &g_state->poisoned_count, 1, __ATOMIC_RELAXED);
                    uint32_t h_cnt = state ? state[0].cfg_halt_count : 0;
                    uint32_t h_pct = state ? state[0].cfg_halt_pct : 0;
                    if (h_cnt > 0 && total_poisoned >= h_cnt) {
                        fprintf(stderr,
                                "forkrun [ABORT]: Halt condition met (%u failed batches). Triggering emergency abort.\n",
                                total_poisoned);
                        pull_fire_alarm();
                    }
                    if (h_pct > 0) {
                        uint64_t total_unique_batches = 0;
                        for (uint32_t i = 0; i < global_num_nodes; i++) {
                            total_unique_batches +=
                                __atomic_load_n(&state[i].read_idx,
                                                __ATOMIC_RELAXED);
                        }
                        if (total_unique_batches >= 100) {
                            uint32_t current_pct =
                                (uint32_t)(((uint64_t)total_poisoned * 100) /
                                           total_unique_batches);
                            if (current_pct >= h_pct) {
                                fprintf(stderr,
                                        "forkrun [ABORT]: Halt condition met (%u%% failed batches). Triggering emergency abort.\n",
                                        h_pct);
                                pull_fire_alarm();
                            }
                        } else {
                            if (total_poisoned >= h_pct) {
                                fprintf(stderr,
                                        "forkrun [ABORT]: Halt condition met (%u failed batches early in run). Triggering emergency abort.\n",
                                        total_poisoned);
                                pull_fire_alarm();
                            }
                        }
                    }
                }
            }
        }
        out->batch_idx = batch.batch_idx;
        out->slots = batch.slots;
        out->lines = batch.lines;
        out->num_kills = batch.num_kills;
        out->poisoned = poisoned;
        out->offset = batch.offset;
        out->length = batch.length;
        out->major = batch.major;
        out->minor = batch.minor;
    }
    return 0;
}

/* Ack the in-flight batch (uses the TLS published by fr_py_claim).
 * v0 calls fr_py_ack(-1, -1): skips fallow/order writes, disarms
 * worker_last_cnt. Returns engine rc. */
int fr_py_ack(int fallow_fd, int target_fd) {
    char a0[] = "ring_ack";
    char a1[32];
    char a2[32];
    char *argv[3];
    snprintf(a1, sizeof(a1), "%d", fallow_fd);
    snprintf(a2, sizeof(a2), "%d", target_fd);
    argv[0] = a0;
    argv[1] = a1;
    argv[2] = a2;
    return ring_ack_main(3, argv);
}

/* Deposit the in-flight batch into escrow with kill count kills
 * (caller passes claimed num_kills + 1, matching the bash EXIT-trap
 * RING_NUM_KILLS++ convention). No-op when nothing is in flight.
 * Returns 0 ok, 1 pipe failure. */
int fr_py_escrow_deposit(unsigned int kills) {
    int node;
    struct EscrowPacket ep;

    if (worker_last_cnt == 0)
        return 0;
    node = my_numa_node;
    if (node < 0 || node >= (int)global_num_nodes)
        node = 0;
    ep.idx = worker_last_idx;
    ep.cnt = worker_last_cnt;
    ep.num_kills = (uint32_t)kills;
    ep._pad = 0;
    if (fd_escrow_w && fd_escrow_w[node] >= 0) {
        if (robust_pipe_write(fd_escrow_w[node], &ep, sizeof(ep)) ==
            (ssize_t)sizeof(ep)) {
            __atomic_store_n(&state[node].escrow_pending, 1,
                             __ATOMIC_RELEASE);
            return 0;
        }
        return 1;
    }
    return 0;
}

/* Raise the global emergency abort (fail-fast path). Workers blocked in
 * claim observe EXECUTION_FAILURE via the eof blast. */
int fr_py_abort(void) {
    pull_fire_alarm();
    return 0;
}

/* Number of batches that crossed the poison threshold (parent-side
 * diagnostic: g_state is MAP_SHARED, so the parent observes worker
 * increments without IPC). */
unsigned int fr_py_poisoned_count(void) {
    if (!g_state)
        return 0;
    return __atomic_load_n(&g_state->poisoned_count, __ATOMIC_RELAXED);
}
