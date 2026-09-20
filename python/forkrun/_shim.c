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

/* W-PY14: <sys/uio.h> for writev (fr_py_emit). Included AFTER the engine
 * (the FIRST-directive rule above is preserved): the engine's FTM block
 * already ran, and writev is POSIX — no feature-test dependency. */
#include <sys/uio.h>

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

/* =====================================================================
 * W-PY13 v1 fast paths: C-level spawn & plugin dispatch.
 *
 * Both wrap engine machinery visible in this TU (posix_spawnp/splice
 * patterns from ring_exec_splice_main, dlopen/negotiation + RAW window
 * delivery from ring_call_main). No engine code is modified.
 *
 * DESIGN NOTES (where this deviates from the W-PY13 sketches — the
 * sketches simplified; this follows the frozen sources):
 * - Plugin callback signature is the REAL one from forkrun_ring.c:
 *   int (*)(int argc, char **argv, const struct forkrun_ctx *ctx)
 *   (legacy: int (*)(int argc, char **argv)). There is no out_fd or
 *   dialect field — output is captured stdout, negotiation rides
 *   forkrun_use_ctx / version / flags_granted per
 *   ring_loadables/forkrun_plugin.h (128B struct forkrun_ctx).
 * - The ctx is filled exactly like ring_call_main fills tls_fctx
 *   (worker identity from g_fr_config, UMA numa_batch_id derivation,
 *   RAW window via ring_call_ensure_ingress_map, reserved zeroing).
 * - Spawn pumps stdin/stdout CONCURRENTLY under poll() (a filter that
 *   writes stdout before consuming all stdin would deadlock a
 *   write-then-read sequence). SIGPIPE is ignored around the pump
 *   (the ring_exec_splice pattern: early-child-exit reads as EPIPE).
 * - Record framing ([batch_idx u64][len u64] + body, the v0.5 emitter
 *   contract in run.py:_HDR) happens HERE so the Python worker never
 *   needs the output length up front. Spawn streams the body with a
 *   placeholder header + backfill (single-owner fd: worker i writes
 *   fd i only — no concurrent appenders). Plugin output is captured
 *   to a memfd first (in-process stdout redirect must be deadlock-free
 *   for outputs larger than any pipe), then emitted with one helper.
 *
 * Return conventions:
 *   spawn:  0 ok | >0 command exit code (retryable via escrow) |
 *           128+sig (shell convention, mirrors ring_exec) | <0 infra
 *           (-1 pipe/setup, -2 spawn, -3 wait/output failure).
 *   plugin: 0 ok | >0 plugin return code truncated like ring_call
 *           (retryable) | <0 infra (-1 setup/capture, -2 dlopen/dlsym,
 *           -3 tokenize/map failure).
 * ===================================================================== */

/* Little-endian 16-byte emitter header shared with run.py:_HDR. */
struct fr_py_record_hdr {
    uint64_t batch_idx;
    uint64_t len;
};

/* Full-write loop (regular files / memfds: no SIGPIPE, short writes only
 * on EINTR/error). Returns 0 ok, -1 on failure. */
static int fr_py_write_all(int fd, const void *buf, size_t count) {
    const char *p = (const char *)buf;
    size_t left = count;
    while (left > 0) {
        ssize_t n = write(fd, p, left);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        if (n == 0)
            return -1;
        p += n;
        left -= (size_t)n;
    }
    return 0;
}

/* Append one framed record copying [src_off, src_off+src_len) from a
 * memfd/file into the worker-owned out_fd. Returns 0 ok, -1 on failure. */
static int fr_py_emit_record(int out_fd, uint64_t batch_idx, int src_fd,
                             uint64_t src_off, uint64_t src_len) {
    struct fr_py_record_hdr hdr;
    char buf[1 << 20];
    uint64_t left;
    off_t woff;

    if (src_len == 0)
        return 0; /* v0 parity: empty output emits no record (None). */
    woff = lseek(out_fd, 0, SEEK_END);
    if (woff == (off_t)-1)
        return -1;
    hdr.batch_idx = batch_idx;
    hdr.len = src_len;
    if (fr_py_write_all(out_fd, &hdr, sizeof(hdr)) != 0)
        return -1;
    left = src_len;
    while (left > 0) {
        size_t want = left > sizeof(buf) ? sizeof(buf) : (size_t)left;
        ssize_t n = pread(src_fd, buf, want, (off_t)(src_off + src_len - left));
        if (n <= 0) {
            if (n < 0 && errno == EINTR)
                continue;
            return -1;
        }
        if (fr_py_write_all(out_fd, buf, (size_t)n) != 0)
            return -1;
        left -= (uint64_t)n;
    }
    return 0;
}

/* Set a fd nonblocking. Returns 0 ok, -1 on failure. */
static int fr_py_nonblock(int fd) {
    int fl = fcntl(fd, F_GETFL, 0);
    if (fl < 0)
        return -1;
    return fcntl(fd, F_SETFL, fl | O_NONBLOCK);
}

/* Per-worker capture-memfd reuse (spawn + plugin stdout staging).
 * One memfd per purpose, truncated+rewound per batch: saves a
 * memfd_create/close pair per batch (~1us) with no lifetime risk (the
 * fd never leaves this worker; contents are emitted before reuse). */
static int fr_py_spawn_cap = -1;
static int fr_py_plugin_cap = -1;

static int fr_py_cap_rewind(int *slot, const char *name) {
    if (*slot < 0) {
        *slot = memfd_create(name, MFD_CLOEXEC);
        if (*slot < 0)
            return -1;
    } else if (ftruncate(*slot, 0) != 0 || lseek(*slot, 0, SEEK_SET) != 0) {
        close(*slot);
        *slot = -1;
        return -1;
    }
    return *slot;
}

/* W-PY13.a: C-level spawn fast path (posix_spawnp + concurrent pump).
 *
 * argv: NULL-terminated arg vector (argv[0] is the command); argc is a
 *   redundancy check (argv[argc] must be NULL). in_off/in_len name the
 *   input window in ingress_fd (zero-copy splice source). The command's
 *   stdout is framed into out_fd tagged with batch_idx.
 */
int fr_py_exec_spawn(char **argv, int argc, uint64_t in_off, uint64_t in_len,
                     int ingress_fd, int out_fd, uint64_t batch_idx) {
    int stdin_pipe[2] = {-1, -1};
    int stdout_pipe[2] = {-1, -1};
    posix_spawn_file_actions_t actions;
    sigset_t block, old;
    struct sigaction sa_ign, sa_oldpipe;
    int have_oldpipe = 0;
    pid_t pid;
    int spawn_rc;
    int cap_fd = -1;
    off_t splice_off;
    uint64_t in_left;
    int stdin_closed = 0;
    int stdout_eof = 0;
    int feed_eof = 0; /* child stopped reading (EPIPE): stop feeding */
    int status = 0;
    pid_t waited = -1;

    if (!argv || argc <= 0 || !argv[0] || ingress_fd < 0 || out_fd < 0)
        return -1;
    if (argv[argc] != NULL)
        return -1;

#if defined(O_CLOEXEC)
    if (pipe2(stdin_pipe, O_CLOEXEC) != 0)
        return -1;
    if (pipe2(stdout_pipe, O_CLOEXEC) != 0) {
        close(stdin_pipe[0]);
        close(stdin_pipe[1]);
        return -1;
    }
#else
    if (pipe(stdin_pipe) != 0)
        return -1;
    if (pipe(stdout_pipe) != 0) {
        close(stdin_pipe[0]);
        close(stdin_pipe[1]);
        return -1;
    }
    fcntl(stdin_pipe[0], F_SETFD, FD_CLOEXEC);
    fcntl(stdin_pipe[1], F_SETFD, FD_CLOEXEC);
    fcntl(stdout_pipe[0], F_SETFD, FD_CLOEXEC);
    fcntl(stdout_pipe[1], F_SETFD, FD_CLOEXEC);
#endif
    /* Best-effort 1MB pipe buffers (the ring_exec_splice pattern). */
    fcntl(stdin_pipe[1], F_SETPIPE_SZ, 1048576);
    fcntl(stdout_pipe[1], F_SETPIPE_SZ, 1048576);

    if (fr_py_nonblock(stdin_pipe[1]) != 0 || fr_py_nonblock(stdout_pipe[0]) != 0) {
        close(stdin_pipe[0]);
        close(stdin_pipe[1]);
        close(stdout_pipe[0]);
        close(stdout_pipe[1]);
        return -1;
    }

    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions, stdin_pipe[0], STDIN_FILENO);
    posix_spawn_file_actions_adddup2(&actions, stdout_pipe[1], STDOUT_FILENO);
    posix_spawn_file_actions_addclose(&actions, stdin_pipe[1]);
    posix_spawn_file_actions_addclose(&actions, stdout_pipe[0]);
    if (ingress_fd > 2)
        posix_spawn_file_actions_addclose(&actions, ingress_fd);
    if (out_fd > 2 && out_fd != ingress_fd)
        posix_spawn_file_actions_addclose(&actions, out_fd);

    /* Shield against a SIGCHLD reaper (the ring_exec pattern verbatim:
     * block around fork, own waitpid, restore after). */
    sigemptyset(&block);
    sigaddset(&block, SIGCHLD);
    sigprocmask(SIG_BLOCK, &block, &old);

    spawn_rc = posix_spawnp(&pid, argv[0], &actions, NULL, argv, environ);

    posix_spawn_file_actions_destroy(&actions);

    /* Parent owns: stdin_w (feed), stdout_r (drain). */
    close(stdin_pipe[0]);
    close(stdout_pipe[1]);
    stdin_pipe[0] = -1;
    stdout_pipe[1] = -1;

    if (spawn_rc != 0) {
        sigprocmask(SIG_SETMASK, &old, NULL);
        close(stdin_pipe[1]);
        close(stdout_pipe[0]);
        /* Shell conventions, retryable (bash -E parity): the command spec
         * is user payload, not infrastructure — "not found / not usable"
         * poisons through escrow like any nonzero exit (v0 parity: v0's
         * FileNotFoundError rode retry-then-poison). Anything else
         * (EAGAIN/ENOMEM-class resource failure inside spawn itself) is
         * infrastructure: fatal. */
        if (spawn_rc == ENOENT || spawn_rc == ENOTDIR)
            return 127;
        if (spawn_rc == EACCES || spawn_rc == ELOOP)
            return 126;
        return -2;
    }

    /* Stage stdout in a per-batch capture memfd, then frame once with
     * fr_py_emit_record. NEVER append a partial record to out_fd: the v1
     * streaming parent preads these memfds CONCURRENTLY, and every byte
     * visible there must be final — an in-place placeholder + backfill
     * loses whole batches (the parent may already have consumed the
     * placeholder header into its split tail; the backfilled length never
     * reaches it, so the record is held "incomplete" until EOF and
     * silently dropped). Header-then-body, true length up front, one
     * append: parseable at every prefix, by construction. Failed batches
     * leave zero trace (no truncation bookkeeping at all). */
    cap_fd = fr_py_cap_rewind(&fr_py_spawn_cap, "forkrun_spawnout");
    if (cap_fd < 0) {
        sigprocmask(SIG_SETMASK, &old, NULL);
        close(stdin_pipe[1]);
        close(stdout_pipe[0]);
        return -1;
    }

    /* Ignore SIGPIPE around the pump (early child exit reads as EPIPE,
     * never as a signal — the ring_exec_splice rule). */
    memset(&sa_ign, 0, sizeof(sa_ign));
    sa_ign.sa_handler = SIG_IGN;
    sigemptyset(&sa_ign.sa_mask);
    if (sigaction(SIGPIPE, &sa_ign, &sa_oldpipe) == 0)
        have_oldpipe = 1;

    splice_off = (off_t)in_off;
    in_left = in_len;
    if (in_left == 0) {
        close(stdin_pipe[1]);
        stdin_pipe[1] = -1;
        stdin_closed = 1;
    }
    while (!stdout_eof) {
        struct pollfd pfds[2];
        int nfds = 0;
        int pr;
        if (!stdin_closed) {
            pfds[nfds].fd = stdin_pipe[1];
            pfds[nfds].events = POLLOUT;
            pfds[nfds].revents = 0;
            nfds++;
        }
        pfds[nfds].fd = stdout_pipe[0];
        pfds[nfds].events = POLLIN;
        pfds[nfds].revents = 0;
        nfds++;
        pr = poll(pfds, (nfds_t)nfds, -1);
        if (pr < 0) {
            if (errno == EINTR)
                continue;
            break;
        }
        /* Drain stdout first (frees pipe capacity for the child) —
         * into the capture memfd (never out_fd directly: see above). */
        {
            short rev = 0;
            int i;
            for (i = 0; i < nfds; i++) {
                if (pfds[i].fd == stdout_pipe[0])
                    rev = pfds[i].revents;
            }
            if (rev & (POLLIN | POLLHUP)) {
                while (1) {
                    ssize_t n = splice(stdout_pipe[0], NULL, cap_fd, NULL,
                                       1 << 20, SPLICE_F_MOVE);
                    if (n < 0) {
                        if (errno == EINTR)
                            continue;
                        if (errno == EAGAIN)
                            break;
                        break; /* error: stop draining; wait+status decides */
                    }
                    if (n == 0) {
                        stdout_eof = 1;
                        break;
                    }
                }
            } else if (rev & (POLLERR | POLLNVAL)) {
                stdout_eof = 1;
            }
        }
        /* Feed stdin (zero-copy splice from the ingress memfd). */
        if (!stdin_closed && in_left > 0 && !feed_eof) {
            short rev = 0;
            int i;
            for (i = 0; i < nfds; i++) {
                if (pfds[i].fd == stdin_pipe[1])
                    rev = pfds[i].revents;
            }
            if (rev & POLLOUT) {
                while (in_left > 0) {
                    size_t want = in_left > (1 << 20) ? (1 << 20) : (size_t)in_left;
                    ssize_t n = splice(ingress_fd, &splice_off, stdin_pipe[1],
                                       NULL, want, SPLICE_F_MOVE);
                    if (n < 0) {
                        if (errno == EINTR)
                            continue;
                        if (errno == EAGAIN)
                            break;
                        /* EPIPE (child exited early) or hard error: stop
                         * feeding for good (no spin), keep draining. */
                        feed_eof = 1;
                        break;
                    }
                    if (n == 0) {
                        /* Past memfd EOF: infra fault, stop feeding. */
                        feed_eof = 1;
                        break;
                    }
                    in_left -= (uint64_t)n;
                    if (n < (ssize_t)want)
                        break; /* pipe full: repoll */
                }
                if (in_left == 0 || feed_eof) {
                    close(stdin_pipe[1]);
                    stdin_pipe[1] = -1;
                    stdin_closed = 1;
                }
            } else if (rev & (POLLERR | POLLNVAL | POLLHUP)) {
                /* Child gone: EOF it, keep draining stdout. */
                close(stdin_pipe[1]);
                stdin_pipe[1] = -1;
                stdin_closed = 1;
            }
        }
        /* Both directions settled but no EOF yet: keep polling stdout
         * only — the loop exits on stdout_eof. */
    }
    if (stdin_pipe[1] >= 0) {
        close(stdin_pipe[1]);
        stdin_pipe[1] = -1;
    }
    if (stdout_pipe[0] >= 0) {
        close(stdout_pipe[0]);
        stdout_pipe[0] = -1;
    }
    if (have_oldpipe)
        sigaction(SIGPIPE, &sa_oldpipe, NULL);

    while ((waited = waitpid(pid, &status, 0)) == -1) {
        if (errno == EINTR)
            continue;
        /* ECHILD or other non-EINTR failure: the child is lost (never
         * kill — PID-reuse hazard, the ring_exec rule). */
        break;
    }
    sigprocmask(SIG_SETMASK, &old, NULL);
    if (waited != pid) {
        return -3;
    }

    if (WIFEXITED(status)) {
        int code = WEXITSTATUS(status);
        if (code == 0) {
            struct stat st;
            uint64_t cap_len = 0;
            int erc = 0;
            if (fstat(cap_fd, &st) == 0 && st.st_size > 0)
                cap_len = (uint64_t)st.st_size;
            /* fr_py_emit_record with len 0 emits nothing (v0 parity:
             * empty output is no record, not an empty record). */
            if (fr_py_emit_record(out_fd, batch_idx, cap_fd, 0, cap_len) != 0)
                erc = -3;
            return erc;
        }
        return code; /* retryable command failure */
    }
    if (WIFSIGNALED(status)) {
        return 128 + WTERMSIG(status);
    }
    return -3;
}

/* W-PY13.b: per-worker plugin handle cache (shim-private — deliberately
 * NOT the engine's tls_dl_handle/tls_callback set, which is coupled to
 * ring_call_main's argv/STDIN-tier lifecycle; Python workers never run
 * ring_call_main, so sharing that state would entangle two lifecycles). */
static void *fr_py_plugin_handle = NULL;
static forkrun_cb_ctx_t fr_py_plugin_ctx_fn = NULL;
static forkrun_cb_t fr_py_plugin_legacy_fn = NULL;
static int fr_py_plugin_use_ctx = 0;
static unsigned fr_py_plugin_flags = 0;
static char fr_py_plugin_path[4096] = {0};
static char fr_py_plugin_func[1024] = {0};

static void fr_py_plugin_cache_reset(void) {
    if (fr_py_plugin_handle) {
        dlclose(fr_py_plugin_handle);
        fr_py_plugin_handle = NULL;
    }
    fr_py_plugin_ctx_fn = NULL;
    fr_py_plugin_legacy_fn = NULL;
    fr_py_plugin_use_ctx = 0;
    fr_py_plugin_flags = 0;
    fr_py_plugin_path[0] = '\0';
    fr_py_plugin_func[0] = '\0';
}

/* Bind (path, func): dlopen + forkrun_use_ctx negotiation, mirroring
 * ring_call_main §1 (dialect 1/2 → ctx dispatch; else legacy 2-arg).
 * Returns 0 bound, -2 on load/symbol failure. */
static int fr_py_plugin_ensure(const char *path, const char *func_name) {
    void *h;
    int *has_ctx;
    unsigned req = 0, ver = 0;

    if (!path || !path[0] || !func_name || !func_name[0])
        return -2;
    if (fr_py_plugin_handle && strcmp(fr_py_plugin_path, path) == 0 &&
        strcmp(fr_py_plugin_func, func_name) == 0)
        return 0;
    fr_py_plugin_cache_reset();
    h = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!h)
        return -2;
    has_ctx = (int *)dlsym(h, "forkrun_use_ctx");
    if (has_ctx)
        req = (unsigned)*has_ctx;
    ver = req & FORKRUN_CTX_VERSION_MASK;
    if (ver == 1 || ver == 2) {
        forkrun_cb_ctx_t fn = (forkrun_cb_ctx_t)dlsym(h, func_name);
        if (!fn) {
            dlclose(h);
            return -2;
        }
        fr_py_plugin_ctx_fn = fn;
        fr_py_plugin_use_ctx = (int)ver;
        if (ver >= 2)
            fr_py_plugin_flags = req & ENGINE_KNOWN_FLAGS;
        else
            fr_py_plugin_flags = 0;
    } else {
        forkrun_cb_t fn = (forkrun_cb_t)dlsym(h, func_name);
        if (!fn) {
            dlclose(h);
            return -2;
        }
        fr_py_plugin_legacy_fn = fn;
        fr_py_plugin_use_ctx = 0;
        fr_py_plugin_flags = 0;
    }
    fr_py_plugin_handle = h;
    snprintf(fr_py_plugin_path, sizeof(fr_py_plugin_path), "%s", path);
    snprintf(fr_py_plugin_func, sizeof(fr_py_plugin_func), "%s", func_name);
    return 0;
}

/* W-PY13.b: C-level plugin fast path through the frozen ABI.
 *
 * Fills struct forkrun_ctx exactly like ring_call_main fills tls_fctx,
 * captures the plugin's stdout into a memfd (deadlock-free for outputs
 * larger than any pipe), and frames it into out_fd tagged with batch_idx.
 * Input is zero-copy: RAW plugins read the borrowed window
 * (reserved[0]); all plugins can pread fd_in at batch_offset.
 */
int fr_py_plugin_call(const char *path, const char *func_name,
                      int ingress_fd, int out_fd, uint64_t batch_off,
                      uint64_t batch_len, uint64_t batch_idx,
                      uint32_t line_count, uint32_t num_kills, int wid,
                      int wincarn) {
    int rc;
    int is_raw;
    struct forkrun_ctx ctx;
    size_t batch_argc = 0;
    int cap_fd = -1;
    int saved_stdout = -1;
    int cb_ret = 0;
    struct stat st;
    uint64_t cap_len = 0;

    if (!path || !func_name || ingress_fd < 0 || out_fd < 0)
        return -1;
    rc = fr_py_plugin_ensure(path, func_name);
    if (rc != 0)
        return -2;

    memset(&ctx, 0, sizeof(ctx));
    ctx.version = (uint32_t)fr_py_plugin_use_ctx;
    ctx.struct_size = (uint32_t)sizeof(struct forkrun_ctx);
    ctx.worker_id = (uint32_t)(wid >= 0 ? wid : 0);
    ctx.worker_incarn = (uint32_t)(wincarn >= 0 ? wincarn : 0);
    ctx.node_id = (uint32_t)(my_numa_node >= 0 ? my_numa_node : 0);
    ctx.fd_in = ingress_fd;
    ctx.delimiter = '\n';
    ctx.cfg_state[0] = (uint8_t)(cfg_state & 0xFF);
    ctx.cfg_state[1] = (uint8_t)((cfg_state >> 8) & 0xFF);
    ctx.cfg_state[2] = (uint8_t)((cfg_state >> 16) & 0xFF);
    ctx.cfg_state[3] = (uint8_t)((cfg_state >> 24) & 0xFF);
    ctx.batch_index = batch_idx;
    ctx.batch_offset = batch_off;
    ctx.batch_byte_length = batch_len;
    ctx.batch_lines = line_count;
    ctx.num_kills = num_kills;
    /* UMA v0 derivation (the ring_call_main UMA branch): pack the 64-bit
     * claim index into (major, minor) the way the engine does. */
    ctx.numa_batch_id =
        FR_PACK_KEY(batch_idx >> FR_MINOR_BITS, batch_idx & FR_MINOR_MASK);
    ctx.flags_granted =
        (fr_py_plugin_use_ctx >= 2) ? fr_py_plugin_flags : 0;

    is_raw = (fr_py_plugin_use_ctx >= 2) &&
             ((fr_py_plugin_flags & FORKRUN_CTX_FLAG_RAW) != 0);

    /* Build argv for non-RAW delivery (tokenize into tls_argv exactly
     * like ring_call_main; RAW skips tokenization entirely). */
    if (fr_py_plugin_ctx_fn && !is_raw) {
        off_t saved_off = tls_batch_offset;
        tls_batch_offset = (off_t)batch_off;
        if (tls_argv_cap < 1024) {
            tls_argv_cap = 1024;
            tls_argv = realloc(tls_argv, tls_argv_cap * sizeof(char *));
            if (!tls_argv) {
                tls_argv_cap = 0;
                tls_batch_offset = saved_off;
                return -3;
            }
        }
        rc = do_tokenize(ingress_fd, (size_t)batch_len, (off_t)batch_off,
                         '\n', NULL, 0, &batch_argc);
        tls_batch_offset = saved_off;
        if (rc != 0)
            return -3;
        tls_argv[batch_argc] = NULL;
    } else if (fr_py_plugin_legacy_fn) {
        off_t saved_off = tls_batch_offset;
        tls_batch_offset = (off_t)batch_off;
        if (tls_argv_cap < 1024) {
            tls_argv_cap = 1024;
            tls_argv = realloc(tls_argv, tls_argv_cap * sizeof(char *));
            if (!tls_argv) {
                tls_argv_cap = 0;
                tls_batch_offset = saved_off;
                return -3;
            }
        }
        rc = do_tokenize(ingress_fd, (size_t)batch_len, (off_t)batch_off,
                         '\n', NULL, 0, &batch_argc);
        tls_batch_offset = saved_off;
        if (rc != 0)
            return -3;
        tls_argv[batch_argc] = NULL;
    }
    if (is_raw) {
        if (batch_len == 0) {
            ctx.reserved[0] = 0;
        } else {
            rc = ring_call_ensure_ingress_map(ingress_fd, batch_off,
                                              (size_t)batch_len);
            if (rc != 0)
                return -3;
            ctx.reserved[0] =
                (uint64_t)(uintptr_t)((const char *)tls_ingress_map +
                                      batch_off);
        }
    }

    /* Capture stdout into the reused memfd (grows without bound: no
     * pipe deadlock for large plugin outputs). */
    cap_fd = fr_py_cap_rewind(&fr_py_plugin_cap, "forkrun_plugout");
    if (cap_fd < 0)
        return -1;
    fflush(NULL); /* keep earlier C-stdio out of the capture */
    saved_stdout = dup(STDOUT_FILENO);
    if (saved_stdout < 0) {
        return -1;
    }
    if (dup2(cap_fd, STDOUT_FILENO) < 0) {
        close(saved_stdout);
        return -1;
    }
    if (fr_py_plugin_ctx_fn)
        cb_ret = fr_py_plugin_ctx_fn((int)batch_argc, tls_argv, &ctx);
    else
        cb_ret = fr_py_plugin_legacy_fn((int)batch_argc, tls_argv);
    fflush(NULL); /* push the plugin's stdio into the capture */
    dup2(saved_stdout, STDOUT_FILENO);
    close(saved_stdout);
    saved_stdout = -1;

    if (fstat(cap_fd, &st) == 0 && st.st_size > 0)
        cap_len = (uint64_t)st.st_size;
    if (cb_ret == 0 && cap_len > 0) {
        if (fr_py_emit_record(out_fd, batch_idx, cap_fd, 0, cap_len) != 0) {
            return -1;
        }
    }

    /* ring_call truncation rule: nonzero → &0xFF, never silent 0. */
    if (cb_ret == 0)
        return 0;
    {
        int truncated = cb_ret & 0xFF;
        return (truncated == 0) ? 1 : truncated;
    }
}

/* =====================================================================
 * W-PY16: streaming ingest support — fallow reaper entry point.
 *
 * Two deliberate NON-additions (documented so nobody "completes" them):
 *
 * 1. There is deliberately NO fr_py_ingest_begin/chunk/end API. The
 *    scanner (core_scanner_loop) keeps its publish state in stack
 *    locals and RESETS write_idx/read_idx per invocation — calling it
 *    once per chunk would republish every batch from zero and corrupt
 *    the claim plane. The correct topology is the bash one: fork ONE
 *    long-lived scanner child running the EXISTING fr_py_scan
 *    concurrently with the parent's spill. The loop already handles
 *    incremental arrival (pread returns 0 with ingest_complete clear
 *    means "wait for more", not EOF — the usleep(100) path), and
 *    batching adapts to whatever prefix is available. No new scanner
 *    API exists or is needed.
 *
 * 2. Concurrency alone does NOT bound memory: without hole-punching
 *    the ingress memfd grows to the full input size no matter how
 *    incrementally it is written. Boundedness comes from fallow —
 *    punching holes behind the contiguous acked prefix — which the
 *    Python path has always disarmed (ack(-1,-1)). This function
 *    enables it: a fallow child runs the engine's OWN ring_fallow_main
 *    (logical/IndexPacket UMA arm — the exact packet shape the UMA
 *    ack path writes via robust_pipe_write), tracking the contiguous
 *    prefix with its interval heap and punching via end_ring. Direct
 *    call, same TU, zero engine changes.
 *
 * Parent orchestration (run.py): create fallow pipe pre-fork → fork
 * fallow child (this function, exits 0 at pipe EOF) → fork scanner
 * child (fr_py_scan, exits at ingest gate) → fork workers (ack with
 * the fallow write end) → spill chunks → fr_py_ingest_done → drain →
 * close fallow_w (reaper EOF) → reap all. Workers acking into a dead
 * reaper get EPIPE → fire alarm → worker exit 1 (bash A2 semantics).
 * ===================================================================== */

/* Run the fallow reaper: read IndexPackets from pipe_r, punch holes in
 * memfd behind the contiguous acked prefix. Blocks until pipe EOF (all
 * worker write ends + the parent's copy closed), then returns the
 * engine rc (0 clean). Never returns on success to a caller that
 * should continue — the fallow child calls this then os._exit(rc). */
int fr_py_fallow_loop(int pipe_r, int memfd) {
    char a0[] = "ring_fallow";
    char a1[32];
    char a2[32];
    char *argv[3];

    if (pipe_r < 0 || memfd < 0)
        return 1;
    snprintf(a1, sizeof(a1), "%d", pipe_r);
    snprintf(a2, sizeof(a2), "%d", memfd);
    argv[0] = a0;
    argv[1] = a1;
    argv[2] = a2;
    return ring_fallow_main(3, argv);
}

/* =====================================================================
 * W-PY14: C-level output emit (fr_py_emit).
 *
 * Replaces four Python operations per batch (coerce + header write +
 * data write + signal write) with one ctypes call: writev() puts the
 * 16-byte [batch_idx u64][length u64] header and the payload bytes into
 * the worker-owned output memfd in ONE syscall (scatter/gather, no
 * copy), then a single 16-byte (wid, batch_idx) signal goes to the pipe.
 *
 * Semantics (v0 parity, verified by test_v1_emit.py):
 * - data == NULL → no record (payload returned None), signal only.
 * - data != NULL, len == 0 → header with len 0 IS written (payload
 *   returned b"" — v0 emits an empty record; None-vs-b"" preserved).
 * - out_fd < 0 → output skipped (discard mode), signal still honored.
 * - signal_fd < 0 → signal skipped (map/run: parent reads post-waitpid;
 *   saves the signal syscall on the most common path).
 * - Every byte appended is final (the W-PY13 append-once rule: the
 *   concurrent streaming reader must never observe mutable framing).
 *
 * Returns 0 ok, -1 output write failure, -2 signal write failure
 * (EPIPE = parent abandoned the stream → fatal worker exit, v0 parity).
 * ===================================================================== */
int fr_py_emit(int out_fd, int signal_fd, uint64_t wid, uint64_t batch_idx,
               const char *data, uint64_t data_len) {
    struct fr_py_record_hdr hdr;
    struct iovec iov[2];
    int niov;
    uint64_t sig[2];
    const char *sp;
    size_t sleft;

    if (data != NULL && out_fd >= 0) {
        hdr.batch_idx = batch_idx;
        hdr.len = data_len;
        iov[0].iov_base = &hdr;
        iov[0].iov_len = sizeof(hdr);
        niov = 1;
        if (data_len > 0) {
            iov[1].iov_base = (void *)data; /* writev takes void* */
            iov[1].iov_len = (size_t)data_len;
            niov = 2;
        }
        /* Full-write loop (memfd writes are effectively whole; the loop
         * is free insurance — same shape as fr_py_write_all). */
        while (niov > 0) {
            ssize_t n = writev(out_fd, iov, niov);
            if (n < 0) {
                if (errno == EINTR)
                    continue;
                return -1;
            }
            if (n == 0)
                return -1;
            {
                ssize_t left = n;
                int i;
                for (i = 0; i < niov && left > 0; i++) {
                    if ((size_t)left >= iov[i].iov_len) {
                        left -= (ssize_t)iov[i].iov_len;
                        iov[i].iov_len = 0;
                    } else {
                        iov[i].iov_base = (char *)iov[i].iov_base + left;
                        iov[i].iov_len -= (size_t)left;
                        left = 0;
                    }
                }
                while (niov > 0 && iov[0].iov_len == 0) {
                    iov[0] = iov[1];
                    niov--;
                }
            }
        }
    }

    if (signal_fd < 0)
        return 0;
    sig[0] = wid;
    sig[1] = batch_idx;
    sp = (const char *)sig;
    sleft = sizeof(sig);
    while (sleft > 0) {
        ssize_t n = write(signal_fd, sp, sleft);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            return -2;
        }
        if (n == 0)
            return -2;
        sp += n;
        sleft -= (size_t)n;
    }
    return 0;
}
