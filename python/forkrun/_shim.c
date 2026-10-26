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

/* Poison-index relay: appends a poisoned batch index to the per-worker
 * slot on the fd named by $FRK_POISON_FD. Defined BELOW, but declared
 * here because ring.c (included next) calls it from its own poison
 * site -- the two poison sites are one translation unit, and this
 * file is also the generator's source of truth for fr_py_* symbols,
 * so the definition has to live here. */
/* unsigned int, not uint32_t: <stdint.h> is included AFTER the ring
 * include below, so uint32_t is not yet a type name at this point --
 * and the declaration has to precede the include for ring.c's own poison
 * site to see it. The definition below uses uint32_t, which is the same
 * type. */
void fr_py_poison_relay(unsigned int batch_idx);

#include "../../forkrun_ring.c"

/* W-PY14: <sys/uio.h> for writev (fr_py_emit). Included AFTER the engine
 * (the FIRST-directive rule above is preserved): the engine's FTM block
 * already ran, and writev is POSIX — no feature-test dependency. */
#include <sys/uio.h>

void fr_py_poison_relay(uint32_t batch_idx) {
    /* The fd is RE-READ on every call, deliberately, with no caching.
     *
     * It used to be cached in a __thread variable ("g_poison_fd"), which
     * is wrong now that a Python parent owns the transport: the parent
     * can call fr_py_claim() itself (python/tests/test_exactly_once.py
     * drives a batch to its retry limit that way), and the first such call
     * with $FRK_POISON_FD unset cached -1 FOREVER in that thread. Every
     * worker forked afterwards inherited the -1 through fork(), so the
     * relay was permanently dead for the rest of the process -- a correct
     * poisoned count beside a permanently empty index list, i.e. exactly
     * the TD-09 symptom, reintroduced by the fix that was meant to close
     * it. It only showed up in the full suite, never in isolation.
     *
     * The cache bought nothing worth having: this function runs at most
     * once per POISONED batch, which is a terminal event, so a getenv per
     * call is not on any hot path. The cleanroom launcher still works
     * unchanged -- it execs a fresh process per run, so it never shared
     * a cache across runs either.
     */
    const char *e = getenv("FRK_POISON_FD");
    int g_poison_fd = (e && e[0]) ? atoi(e) : -1;
    if (g_poison_fd < 0)
        return;
    const unsigned wid = g_fr_config.ring_wid;
    if (wid >= 4096u)
        return;
    /* The header size is READ FROM THE REGION, not hardcoded.
     *
     * It used to be a literal 4 (v2's four u32 words). When stats v3
     * appended a fifth word the writer was left behind, and the two
     * sides disagreed by exactly one word: the relay placed each worker's
     * slot at the v2 offset while the reader walked the v3 one. Nothing
     * raised -- poisoned_batches just came back as a plausible-looking
     * WRONG list ([0, 5] instead of [2, 5]), which is the worst possible
     * failure for a poisoned-batch index. A literal here is a shared
     * constant across two files with no compiler to connect them, so it
     * is derived from the version word the header actually carries:
     *
     *     v1/v2 -> 4 u32 header      v3 -> 5 u32 header
     *
     * An unknown/short version falls back to 4, the pre-v3 layout, so a
     * malformed header degrades to the old behaviour instead of writing
     * indices into the wrong place. Slot is [count][idx...] with a fixed
     * capacity. */
    uint32_t hdr_ver = 0;
    if (pread(g_poison_fd, &hdr_ver, sizeof hdr_ver, 0) !=
        (ssize_t)sizeof hdr_ver)
        hdr_ver = 0;
    const uint32_t hdr_u32 = (hdr_ver >= 3u) ? 5u : 4u;
    const off_t slot =
        (off_t)(hdr_u32 + (size_t)wid * (FR_POISON_SLOT_U32 + 1)) * 4;
    uint32_t n = 0;
    if (pread(g_poison_fd, &n, sizeof n, slot) != (ssize_t)sizeof n)
        return;
    if (n >= FR_POISON_SLOT_U32)
        return;                      /* bounded: drop, never grow */
    uint32_t buf[1];
    buf[0] = batch_idx;
    if (pwrite(g_poison_fd, buf, sizeof buf,
               slot + (off_t)(1 + n) * 4) != (ssize_t)sizeof buf)
        return;
    n++;
    /* Publish the count last: a reader that sees n must see the indices. */
    (void)!pwrite(g_poison_fd, &n, sizeof n, slot);
}


/* Forward: publish-mark epoch reset (defined with the marks below). */
static void fr_py_data_hwm_reset(void);

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

/* W-PY28: worker-local output fd for transaction publication.
 * W-PY29: publication now snapshots the TLS worker_output_end cursor
 * (initialized by fr_py_ack_init), so this naming is vestigial — kept
 * for API compatibility (workers still set it; nothing reads it).
 * Declared here (before first use in fr_py_worker_init) because C
 * demands it. */
static __thread int fr_py_txn_out_fd = -1;

/* C0.7: worker-local count of DATA frames written for the CURRENT
 * transaction but not yet committed.
 *
 * This is deliberately NOT the shared counter. Writing a frame does not
 * commit it: if the worker dies before acknowledgement, recovery
 * truncates the output (ring_revert_output) and the retry writes again.
 * Counting at write time therefore overcounts every recovered run --
 * measured 2 writes : 1 committed record at one death, 4 : 1 at three.
 *
 * So emitters bump THIS, and the value is transferred to the shared
 * per-node field only in fr_py_ack_core, after every acknowledgement
 * side effect has succeeded and immediately before worker_txn_clear()
 * publishes TXN_IDLE. fr_py_recover_worker discards it on the RECOVERED
 * branch, so a rolled-back attempt contributes nothing.
 *
 * Thread-local, like fr_py_txn_out_fd, so concurrent workers on one node
 * never contend here; the only shared write is the commit flush. */
static __thread uint64_t fr_py_txn_pending_data = 0;

/* C0.7 accounting switch.
 *
 * Reads ONE env var and applies it to BOTH halves of the feature: the
 * per-emitter pending increment AND the commit-time flush. They cannot be
 * separated, and that is deliberate.
 *
 * Separating them would be a false-pass factory. With the flush disabled
 * and the certificate still active, the counter reads 0 while the parent
 * collects its frames, so every correct run would fail. With the
 * accounting disabled and the certificate silently skipped, every run
 * would "pass" with nothing measured. One switch, both behaviours,
 * means the only two reachable states are "measured and checked" and
 * "not attempted at all".
 *
 * Default ON. The cost when on is one thread-local increment per DATA
 * frame plus one relaxed fetch_add per committed batch -- measured below
 * the noise floor of the ordered workload. Turning it off exists for
 * operators who want that back on hot C-emitter paths such as
 * order="none", and it costs the certificate, which the docs must say
 * plainly. Inert unless the variable is set to 0. */
static int fr_c07_enabled(void)
{
    static int cached = -1;
    if (cached < 0) {
        const char *v = getenv("FORKRUN_C07_COUNT");
        cached = !(v && v[0] && strcmp(v, "0") == 0);
    }
    return cached;
}

/* Set the worker-local output fd for W-PY28 transaction records.
 * Call once post-fork, post-init (idempotent; -1 disarms). */
int fr_py_set_output_fd(int fd) {
    fr_py_txn_out_fd = fd;
    return 0;
}

/* W-PY28: sync the ack offset for a (possibly respawned) worker.
 * ring_ack_init_main's shim twin: last_ack_offset = SEEK_CUR so the
 * next OrderPacket spans only this generation's appends. Without it
 * a respawned ordered worker's first packet would cover the whole
 * file (TLS starts 0), duplicating everything downstream. Fresh
 * workers are a no-op (fresh memfd offset is already 0). Assigns
 * only on lseek success (a pipe fd must never install -1).
 * W-REL5-D (D2 coherence): adopt the fd + mode too -- the ack core
 * resets the offset on fd change, so an init-sync that leaves the
 * cached fd behind manufactures a spurious change and zeroes the
 * just-synced offset (test_invariant_gate §6/§9 caught it).
  * W-PY29: also initializes the output cursor (one lseek per worker,
  * shared with the offset sync above — no extra syscall). */
int fr_py_ack_init(int fd) {
    if (fd >= 0) {
        off_t pos = lseek(fd, 0, SEEK_CUR);
        if (pos != (off_t)-1)
            last_ack_offset = pos;
        ack_cached_target_fd = fd;
        struct stat st;
        ack_cached_mode =
            (fstat(fd, &st) == 0 && S_ISREG(st.st_mode)) ? 1 : 2;
    }
    worker_txn_init_output_cursor(fd);
    return 0;
}

/* W-PY29: manual output-cursor advance for emit paths that bypass
 * fr_py_emit (Python v0 direct-write path in _worker.py). The caller
 * passes the TOTAL record bytes just made durable (framing +
 * payload); the cursor moves only on complete emits. Best-effort,
 * never fails (returns 0 always so workers never branch on it). */
int fr_py_output_advanced(uint64_t nbytes) {
    worker_output_end += (off_t)nbytes;
    return 0;
}

/* Initialize the substrate for one UMA node. lines/bytes are mutually
 * exclusive (0 = default adaptive). Returns the engine rc (0 ok, 1 fail). */
int fr_py_init(int lines, int bytes) {
    char a0[] = "ring_init";
    if (lines < 0 || bytes < 0)
        return 1;
    if (lines > 0 && bytes > 0)
        return 1;
    /* New epoch for the publish high-water marks (W-PY21). */
    fr_py_data_hwm_reset();
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
int fr_py_ingest_data_post(void) {
    /* W-PREFLIGHT: announce "more bytes have landed in the ingress
     * memfd", and NOTHING more.
     *
     * The pre-flight scan (core_scanner_loop, the usleep(100) branch)
     * waits for the ingest to deliver the next chunk. Bash's
     * ring_copy_main signals evfd_ingest_data after each chunk
     * (forkrun_ring.c:8279) so that wait can block instead of spin.
     * The Python spill was os.read/os.pwrite and never signalled, which
     * is why Python spun ~10k times in 5 s where Bash slept 78 times.
     *
     * DELIBERATELY does NOT touch state[0].ingest_complete. That flag
     * is the scanner's EOF gate, and a previous attempt (W-GATE2) got
     * this wrong by letting ring_copy_main own it: ring_copy_main sets
     * it UNCONDITIONALLY on the way out, including after an early
     * break, so it means "my loop ended", not "input drained". Trusting
     * it cost 9,839 records. This function asserts only the one thing
     * that is unconditionally true at the call site -- bytes were just
     * written -- so it cannot manufacture a premature EOF.
     *
     * Returns 0 on success, 1 if the eventfd is unavailable (caller
     * keeps working; the pre-flight just falls back to its timeout).
     */
    if (evfd_ingest_data < 0)
        return 1;
    uint64_t v = 1;
    ssize_t _w = sys_write(evfd_ingest_data, &v, 8);
    return (_w == 8) ? 0 : 1;
}

int fr_py_ingest_done(void) {
    if (!state)
        return 1;
    __atomic_store_n(&state[0].ingest_complete, 1, __ATOMIC_RELEASE);
    return 0;
}

/* Bind the LOGICAL node the next fr_py_worker_init call will use.
 *
 * -1 clears the binding, which restores the historical behaviour: the
 * node argument of fr_py_worker_init decides. The binding exists so the
 * multi-node launcher can select a ring without a second copy of the
 * worker loop body (the parity test requires the three modes to share
 * one lifecycle, and a duplicate body would be a fourth place for a fix
 * to miss). */
static int g_fr_bound_node = -1;

void fr_py_worker_bind_node(int node_id) {
    g_fr_bound_node = node_id;
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
    /* A bound node (the multi-node launcher's selector) OVERRIDES the
     * argument, and is range-checked exactly as the argument is. */
    if (g_fr_bound_node >= 0)
        node_id = g_fr_bound_node;
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
    /* W-PY28: fresh generation — drop any inherited output-fd naming
     * (fork inherits the value; the worker re-arms it explicitly via
     * fr_py_set_output_fd or the C loops below). */
fr_py_txn_out_fd = -1;
    /* C0.7: same reasoning for the pending DATA count. It is thread-local
     * and survives fork, so a value inherited by a fresh generation
     * would be flushed into the NEW run's shared counter and report
     * frames nobody committed in it. This is the W-PY28 hazard applied
     * to the counter: it surfaced as a test that failed only when run
     * after another that left a pending value behind, and passed alone.
     * A fresh generation must carry neither name nor count. */
    fr_py_txn_pending_data = 0;
    /* W-PY30: per-worker coredump defaults (dumps off; generous hard
     * preserved for final-attempt arming; small-dump filter). */
    worker_coredump_startup();

    if (g_fr_config.ring_node_id >= 0)
        my_numa_node = g_fr_config.ring_node_id;
    else
        my_numa_node = 0;
    if (my_numa_node >= (int)global_num_nodes)
        my_numa_node = 0;
    /* W-PY21: worker self-pinning (mirrors ring_worker inc exactly:
     * pin when multi-node OR explicit map, via the engine's own
     * logical→physical map; best-effort, never fatal — UMA paths
     * never reach here, so UMA behavior is unchanged). */
    if ((global_num_nodes > 1 || g_explicit_pinning) &&
        g_logical_to_phys_map)
        pin_to_numa_node(
            g_logical_to_phys_map[my_numa_node]);
    __atomic_fetch_add(&state[my_numa_node].active_workers, 1,
                       __ATOMIC_SEQ_CST);
    return 0;
}

/* Claim one batch (blocking). Publishes TLS (worker_last_*, tls_batch_*)
 * exactly like ring_claim_main, decides poisoned from g_fr_config.retry_limit
 * (incl. the once-only poisoned_count increment and halt checks), fills
 * *out. Returns 0 success, 2 EOF, 1 failure/abort. Never touches bash
 * variables. */

/* W-PY31: WAITING is the "no ticket yet" phase of a claim.
 *
 * `TXN_CLAIMING` is the claim-without-publish window: the ticket may
 * have been issued, so recovery must abort rather than guess.  The
 * original shim bracketed the WHOLE blocking `do_lockfree_claim` with
 * that state.  A worker waiting for the first batch (or for a slow
 * producer) therefore sat in CLAIMING for an unbounded time, and a
 * death there -- an OOM kill, an operator kill, the supervision test's
 * immediate-kill injection -- was misclassified as an unattributable
 * ticket.  Measured: 47/100 slot-pressure runs aborted with recovery
 * rc=4 while no batch was in flight at all.
 *
 * WAITING is deliberately a shim-side value: the engine is frozen, and
 * its recovery core knows only 0..3.  fr_py_recover_worker() translates
 * WAITING to IDLE before delegating, which is exactly the truth -- no
 * ticket has been issued.  All Python and cleanroom worker loops call
 * fr_py_claim(), so they share this phase; the bash worker retains the
 * engine's original bracketing and is unaffected.
 *
 * Do not collapse WAITING into IDLE: the state is what lets recovery
 * distinguish "waiting" from the CLAIMING window it must still abort on.
 */
#define TXN_WAITING 4u

static inline void worker_txn_begin_wait(int wid) {
    if (!g_state || wid < 0 || wid >= MAX_TXN_WORKERS) return;
    __atomic_store_n(&g_state->worker_txn[wid].state, TXN_WAITING,
                     __ATOMIC_RELEASE);
}

/* Block until a claim attempt has a reason to be retried.  The claim
 * DECISION stays in do_lockfree_claim(); this only mirrors its wait set
 * (data eventfd, escrow pipe, EOF eventfd) so an idle worker sleeps in
 * poll() instead of spinning.  The transaction is in WAITING here, so a
 * death during this wait is recoverable. */
static int fr_py_claim_wait_poll(void) {
    int node = (my_numa_node >= 0) ? my_numa_node : 0;
    struct pollfd pfds[3];
    int pr;

    pfds[0].fd = evfd_data_arr ? evfd_data_arr[node] : -1;
    pfds[0].events = POLLIN;
    pfds[0].revents = 0;
    pfds[1].fd = (fd_escrow_r && fd_escrow_r[node] >= 0)
                     ? fd_escrow_r[node] : -1;
    pfds[1].events = POLLIN;
    pfds[1].revents = 0;
    pfds[2].fd = evfd_eof_arr ? evfd_eof_arr[node] : -1;
    pfds[2].events = POLLIN;
    pfds[2].revents = 0;

    do {
        pr = poll(pfds, 3, 100);
    } while (pr < 0 && errno == EINTR);
    if (pr <= 0)
        return 0;

    /* Drain the eventfds this helper owns.  The escrow pipe is left
     * untouched: do_lockfree_claim() is its sole reader and must see
     * the packet. */
    if (pfds[0].fd >= 0 && (pfds[0].revents & POLLIN)) {
        uint64_t v;
        while (sys_read(pfds[0].fd, &v, 8) > 0) {
        }
    }
    if (pfds[2].fd >= 0 && (pfds[2].revents & POLLIN)) {
        uint64_t v;
        while (sys_read(pfds[2].fd, &v, 8) > 0) {
        }
    }
    return 0;
}

int fr_py_claim(fr_py_batch_t *out) {
    struct WorkerBatchState batch;
    int rc;
    int waiting = 0;

    if (!out)
        return 1;
    if (my_numa_node == -1) {
        my_numa_node = 0;
        if (my_numa_node >= (int)global_num_nodes)
            my_numa_node = 0;
    }
    for (;;) {
        /* W-PY29: IDLE → CLAIMING immediately before a NON-BLOCKING
         * claim.  The ticket can only be issued by this call, so the
         * window stays bounded; the wait itself is WAITING. */
        worker_txn_begin_claim(g_fr_config.ring_wid);
        /* W-PY29 adversarial test hook: FORKRUN_TEST_DIE_AT_CLAIM=1 makes
         * the worker SIGKILL itself inside the claim-without-publish
         * window (deterministic race injection). Inert unless the env var
         * is set. Deliberately uncached: the value is read fresh so
         * forked children observe the post-fork environment (a cached
         * "unset" inherited across fork would disarm the hook) and
         * set/del cycles across tests behave. Cost is one getenv per
         * claim (~tens of ns, invisible next to batch work). */
        if (getenv("FORKRUN_TEST_DIE_AT_CLAIM") != NULL)
            raise(SIGKILL);
        rc = do_lockfree_claim(&batch, false);
        if (rc == 0)
            break;

        /* No ticket was issued (or the engine failed/aborted). */
        worker_txn_abort_claim(g_fr_config.ring_wid);
        if (rc != 1)
            goto claim_done;
        if (atomic_load_relaxed(&state[0].emergency_abort)) {
            rc = 1;
            goto claim_done;
        }

        worker_txn_begin_wait(g_fr_config.ring_wid);
        /* W-PY31 adversarial hook: die while WAITING (no ticket).  The
         * unit test pins that recovery classifies this as NO_BATCH, not
         * RACE_DETECTED.  Inert unless set. */
        if (getenv("FORKRUN_TEST_DIE_AT_WAIT") != NULL)
            raise(SIGKILL);
        if (!waiting) {
            int node = (my_numa_node >= 0) ? my_numa_node : 0;
            __atomic_fetch_add(&state[node].active_waiters, 1,
                               __ATOMIC_SEQ_CST);
            is_waiting_on_ring = true;
            waiting = 1;
        }
        (void)fr_py_claim_wait_poll();
        if (atomic_load_relaxed(&state[0].emergency_abort)) {
            worker_txn_abort_claim(g_fr_config.ring_wid);
            rc = 1;
            goto claim_done;
        }
    }
    if (waiting) {
        cleanup_waiter_state();
        waiting = 0;
    }
    /* fall through: batch is ours and the transaction is CLAIMING */

claim_done:
    if (waiting)
        cleanup_waiter_state();
    if (rc != 0) {
        /* EOF/abort: no batch acquired — CLAIMING → IDLE. */
        worker_txn_abort_claim(g_fr_config.ring_wid);
        return rc;
    }

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
            if (limit < 0) {
                /* UNBOUNDED RETRY. A negative limit means "never declared
                 * poisoned" (bash -E parity, frun.bash:448), so the poison
                 * branch below is skipped entirely and the batch is
                 * retried forever.
                 *
                 * That is the intended semantics -- but it was SILENT:
                 * measured, a permanently failing batch under
                 * FORKRUN_RETRY_LIMIT=-1 ran past a 45s timeout with no
                 * stdout, no stderr and no diagnostic. A user who set -1
                 * meaning "absorb transient failures" instead got an
                 * indistinguishable hang, with no hint that the retry
                 * budget was unbounded rather than merely large.
                 *
                 * Warn at each power of ten: escalating rather than
                 * periodic. A fixed interval is wrong here because retry
                 * cost varies by orders of magnitude between workloads --
                 * at 1ms a "every 100" warning emits tens of thousands of
                 * lines over an overnight hang, which is its own
                 * undebuggable condition. Powers of ten cap the output at
                 * O(log n) per batch however long it runs, while still
                 * showing the growth rate. */
                uint32_t k = batch.num_kills;
                if (k == 10u || k == 100u || k == 1000u || k == 10000u ||
                    k == 100000u || k == 1000000u) {
                    fprintf(stderr,
                            "forkrun [WARN]: batch %llu has been retried "
                            "%lu times and retry_limit is negative "
                            "(--unbounded); it will never be poisoned.\n"
                            "         If this is unexpected, set "
                            "FORKRUN_RETRY_LIMIT to a non-negative value "
                            "to bound retries.\n",
                            (unsigned long long)batch.batch_idx,
                            (unsigned long)k);
                    fflush(stderr);
                }
            }
            if (limit >= 0 && batch.num_kills >= (uint32_t)limit) {
                uint32_t poison_threshold =
                    (limit > 0) ? (uint32_t)limit : 1;
                poisoned = 1;
                if (batch.num_kills == poison_threshold && g_state) {
                    uint32_t total_poisoned = __atomic_add_fetch(
                        &g_state->poisoned_count, 1, __ATOMIC_RELAXED);
                    /* Relay the index to the parent. The count alone
                     * already crosses via shared g_state; the index has
                     * no shared home, so it goes out on the stats memfd.
                     * This is the site the CLEANROOM reaches --
                     * fr_py_worker_plugin_loop lives here, not in the
                     * ring's own loop -- which is why the ring.c call
                     * alone produced an empty poisoned_batches with a
                     * correct poisoned count. */
                    fr_py_poison_relay((uint32_t)batch.batch_idx);
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
        /* W-PY30: arm coredumps iff this is the final allowed attempt
         * (same condition as ring_claim_main — poisoned/fresh/limit<0
         * return inside with no syscall). */
        worker_coredump_arm_if_final(batch.num_kills, poisoned,
                                     g_fr_config.retry_limit);
    }
    /* W-PY29: CLAIMING → CLAIMED first-thing after the claim lands
     * (same placement rule as ring_claim_main — every instruction
     * before the publish widens the claim-without-publish race).
     * Python workers bypass ring_claim_main, so the shim publishes
     * here; the poison accounting above is part of the claim (not
     * "before" it) — the record carries the final num_kills the
     * parent must increment from. Syscall-free (TLS cursor). */
    worker_txn_publish(g_fr_config.ring_wid, &batch);
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

    /* W-PY30: this batch's execution is over (soft failure → retry
     * via escrow) — disarm a final-attempt coredump so it cannot leak
     * into the worker's subsequent batches. No-op unless armed. */
    worker_coredump_disarm();
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
            /* W-REL2/R14b: clear on successful deposit, mirroring
             * ring_ack_main's worker_last_cnt = 0. Without this a
             * second deposit without an intervening claim re-sends
             * the same batch (double-deposit → duplicate output);
             * the engine side never had this bug. */
            worker_last_cnt = 0;
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

/* Read-only abort-reason accessor (D-PORT2): the exact byte
 * ring_abort_reason_main exposes to Bash (0 unset, 1 downstream
 * SIGPIPE/close, 2 internal fault), via the same ACQUIRE load.
 * Additive surface only — no engine logic touched (W-PY22
 * fr_py_resume_snapshot precedent: shim reads, engine frozen).
 * Returns -1 with no live engine (distinguishes "no engine" from
 * "no abort", which Bash reports as EXECUTION_FAILURE). */
int fr_py_abort_reason(void) {
    if (!g_state)
        return -1;
    return (int)__atomic_load_n(&g_state->abort_reason, __ATOMIC_ACQUIRE);
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
/* DECISION-02 section 5.1 -- TYPED terminal dispositions.
 *
 * Every published batch reaches exactly one of these. The field is
 * EXPLICIT rather than inferred from `len` because `len == 0` is already
 * spoken for: fr_py_emit's v0 contract (and test_v1_emit.py) define a
 * zero-length payload as a real empty result. Overloading it for "this
 * batch completed with no result" would collapse a tested distinction
 * between None and b"".
 *
 *   DATA      - completed with a result. `len` may legitimately be 0.
 *   NO_RESULT - completed successfully with no result (payload returned
 *               None). This is the case that previously emitted NOTHING,
 *               leaving the parent unable to tell "produced nothing" from
 *               "has not arrived yet" -- the ambiguity that made ordered
 *               streaming stall.
 *
 * SKIPPED and POISONED are NOT emitted on this channel: those batches are
 * never emitted at all, so the worker has no emit site for them. The parent
 * learns their INDICES from the poison relay on the stats channel, which is
 * available after the join. See the note in run.py.
 */
#define FR_DISP_DATA      0u
#define FR_DISP_NO_RESULT 1u
/* DECISION-02 5.1: the four terminal dispositions. Every PUBLISHED batch
 * reaches exactly one. SKIPPED and POISONED carry no payload -- their
 * entire content is that the batch reached a terminal state which is NOT
 * a success, so an ordered consumer can advance the prefix past it
 * without that advance implying success. A missing payload implies
 * neither success nor poison. */
#define FR_DISP_SKIPPED   2u
#define FR_DISP_POISONED  3u

struct fr_py_record_hdr {
    uint64_t batch_idx;
    uint64_t len;
    uint32_t disposition;
    uint32_t reserved;      /* explicit tail; keeps the struct 8-aligned */
};

/* DECISION-02: the on-wire record footprint. Every rollback-frontier
 * advance MUST use this, never a literal 16. The frontier is what
 * recovery truncates the output fd back to, so a site that still said
 * "16 + len" under-counted by the 8 bytes the disposition added -- and
 * rollback would then leave 8 bytes of stale output behind for EVERY
 * record. That is silent data corruption on the retry path, which is
 * exactly what the exactly-once invariant forbids. */
#define FR_PY_RECORD_FOOTPRINT(payload_len) \
    (sizeof(struct fr_py_record_hdr) + (payload_len))

/* Write one keyed "bytes are visible" signal. Defined below, declared
 * here because the disposition emitter (earlier in this file) needs it. */

/* STAGE0 TEST-ONLY: drain-forward handshake.
 *
 * A fault-injection test that sleeps "long enough" for the drain proves
 * nothing: it cannot distinguish "the drain forwarded, then the worker
 * died" from "the drain never ran, so the test never exercised the
 * window at all". That ambiguity already cost one wrong conclusion in
 * this codebase.
 *
 * When FORKRUN_TEST_DRAIN_ACK_FIFO names a FIFO, the drain writes
 * (worker, cursor) after EVERY wakeup it processes -- including wakeups
 * that legitimately forward nothing -- so a test can wait for proof that
 * the drain was awake and acting at a precise moment.
 *
 * The write end is opened O_NONBLOCK: with no reader the open fails with
 * ENXIO and the ack is skipped, so this is inert by default and changes
 * no production path. */
static void fr_drain_test_ack(uint64_t wid, uint64_t cursor)
{
    const char *path = getenv("FORKRUN_TEST_DRAIN_ACK_FIFO");
    uint64_t rec[2];
    int fd;

    if (path == NULL || *path == 0)
        return;
    fd = open(path, O_WRONLY | O_NONBLOCK);
    if (fd < 0)
        return;                 /* no reader: nobody is testing */
    rec[0] = wid;
    rec[1] = cursor;
    (void)!write(fd, rec, sizeof(rec));
    close(fd);
}

/* STAGE0 TEST-ONLY: block until the drain confirms it processed a wakeup
 * for this worker, so an injected death provably happens AFTER the drain
 * had its chance. Bounded, so a broken build fails the test rather than
 * hanging it. */
static void fr_drain_test_wait_ack(uint64_t wid)
{
    const char *path = getenv("FORKRUN_TEST_DRAIN_ACK_FIFO");
    uint64_t rec[2];
    int fd, spins;

    if (path == NULL || *path == 0)
        return;
    fd = open(path, O_RDONLY | O_NONBLOCK);
    if (fd < 0)
        return;
    for (spins = 0; spins < 3000; spins++) {
        ssize_t n = read(fd, rec, sizeof(rec));
        if (n == (ssize_t)sizeof(rec)) {
            if (rec[0] == wid) {
                close(fd);
                return;
            }
            continue;
        }
        usleep(1000);
    }
    close(fd);
    /* The handshake was requested and never completed. Abort rather than
     * fall through and die anyway: silently timing out would make the
     * test indistinguishable from one where the drain never ran, which
     * is precisely the vacuous case the handshake exists to rule out. */
    {
        static const char msg[] =
            "forkrun: FORKRUN_TEST_DRAIN_ACK_FIFO set but no drain ack\n";
        ssize_t ignored = write(2, msg, sizeof(msg) - 1);
        (void)ignored;
        _exit(97);
    }
}

static int fr_py_signal_write(int signal_fd, uint64_t wid,
                              uint64_t batch_idx);
int fr_py_notify_committed(int signal_fd, int out_fd, uint64_t wid);

/* Fault injection for the exactly-once tests: SIGKILL this worker
 * after its record is framed but before it acks.
 *
 * That window is the only one where a rollback is both POSSIBLE and
 * NECESSARY: the transaction is still CLAIMED and an orphan sits in the
 * output fd. The pre-existing hooks cannot reach it --
 * DIE_AT_CLAIM fires before any output exists, and DIE_AT_COMMIT fires
 * after worker_txn_begin_commit, leaving the transaction COMMITTING,
 * which recovery reports as RACE_DETECTED rather than guessing.
 *
 * FORKRUN_TEST_DIE_BEFORE_ACK=n kills on the n-th attempt in THIS
 * process. Counting per process is what makes it usable under
 * supervision: a respawned generation starts over, so each generation
 * supplies exactly one more death to survive, rather than every worker
 * dying on its first action forever until the respawn cap aborts the
 * run. Inert unless the variable is set.
 *
 * FORKRUN_TEST_DIE_AFTER_DRAIN_MS=ms widens that same window: sleep ms
 * after the record is signalled but before raising, so the drain has
 * demonstrably forwarded the record downstream BEFORE the worker dies.
 * Without it, whether the drain got there first is a scheduler race, so
 * a passing test proves less than it appears to -- the uncommitted record
 * can only be rolled back if it is still in the worker's memfd. */
static void fr_py_maybe_die_before_ack(int wid, int signal_fd)
{
    const char *n = getenv("FORKRUN_TEST_DIE_BEFORE_ACK");
    if (n != NULL && *n) {
        static unsigned seq = 0;
        unsigned want = (unsigned)atoi(n);
        seq++;

        /* STAGE0 one-shot variant. The attempt counter above is a
         * per-process static, so after a respawn it starts over and the
         * first-attempt death repeats in EVERY generation until the batch
         * poisons. That makes it impossible to observe the case that
         * matters most for content correctness: attempt 1 dies, attempt
         * 2 SUCCEEDS with different bytes, and the caller must receive
         * attempt 2's payload.
         *
         * With FORKRUN_TEST_DIE_BEFORE_ACK_ONCE naming a path, the death
         * fires only if that file does not yet exist, and creates it when
         * it fires. The file outlives the process, so exactly one
         * attempt in the whole run dies and recovery gets to succeed. */
        if (seq == want) {
            const char *once = getenv("FORKRUN_TEST_DIE_BEFORE_ACK_ONCE");
            if (once != NULL && *once) {
                int seen = open(once, O_RDONLY);
                if (seen >= 0) {
                    close(seen);
                    return;         /* already fired once; let this run */
                }
                {
                    int mk = open(once, O_WRONLY | O_CREAT | O_EXCL, 0600);
                    if (mk < 0)
                        return;     /* lost the race; do not double-fire */
                    close(mk);
                }
            }
            /* STAGE0 handshake: wake the drain with frontier 0, which
             * EXCLUDES the record just written uncommitted. If the
             * protocol is correct the drain wakes, sees nothing
             * committed to move, and confirms -- proving it was awake
             * and declined to publish without ever being told the
             * uncommitted record exists. */
            if (getenv("FORKRUN_TEST_DRAIN_ACK_FIFO") != NULL)
                (void)fr_py_signal_write(signal_fd, (uint64_t)wid, 0);
            const char *d = getenv("FORKRUN_TEST_DIE_AFTER_DRAIN_MS");
            if (d != NULL && *d) {
                unsigned long ms = strtoul(d, NULL, 10);
                if (ms)
                    usleep((useconds_t)(ms * 1000));
            }
            /* Prefer a real handshake over a sleep: wait until the
             * drain confirms it processed a wakeup for this worker, so
             * the death provably happens AFTER the drain had its chance
             * rather than merely probably after. */
            if (getenv("FORKRUN_TEST_DRAIN_ACK_FIFO") != NULL)
                fr_drain_test_wait_ack((uint64_t)wid);
            raise(SIGKILL);
        }
    }
}

/* Fault injection: SIGKILL this worker AFTER its payload record has been
 * written AND signalled, but BEFORE the ack.
 *
 * This is the interval the before-ack hook cannot reach, and it is the
 * one that matters. fr_py_emit_record_buf writes a DATA record WITHOUT
 * signalling; the signal happens later, inside fr_py_complete. The
 * before-ack hook sits between those two points, so under it a DATA
 * record is never signalled, the drain never learns of it, and a DATA
 * record is never forwarded -- which means a test driven by that hook
 * exercises ONLY the disposition path and silently proves nothing about
 * DATA publication, however many POISONED records it forwards.
 *
 * Gated on signal_fd >= 0, i.e. wherever a completion WILL notify the
 * drain. Gating on payload length was wrong: the UDF and plugin loops
 * write their record themselves and then complete with data=NULL, so a
 * length gate left the hook unreachable there and those runs passed
 * without any fault being injected at all.
 *
 * Honours FORKRUN_TEST_DIE_AFTER_DRAIN_MS to let the drain forward the
 * record first, which is what makes the publication/commit window real
 * rather than theoretical. */
static void fr_py_maybe_die_before_notify(int signal_fd,
                                              int out_fd, int wid)
{
    const char *n = getenv("FORKRUN_TEST_DIE_BEFORE_NOTIFY");
    if (n != NULL && *n && signal_fd >= 0) {
        static unsigned seq = 0;
        unsigned want = (unsigned)atoi(n);
        seq++;
        if (want && seq == want) {
            const char *d = getenv("FORKRUN_TEST_DIE_AFTER_DRAIN_MS");
            if (d != NULL && *d) {
                unsigned long ms = strtoul(d, NULL, 10);
                if (ms)
                    usleep((useconds_t)(ms * 1000));
            }
            /* STAGE0 handshake, NON-PUBLISHING.
             *
             * This hook used to publish the record's real frontier and
             * wait for the drain to forward it. That proved an ordinary
             * notification works -- the opposite of what this interval
             * is for. A lost-notification test that sends the
             * notification cannot fail when the notification is lost.
             *
             * Instead, wake the drain with frontier 0, which is at or
             * below the PREVIOUS committed boundary and so excludes the
             * record just committed. The drain wakes, has nothing new to
             * move, and acknowledges. That proves it is alive and
             * processing while being told nothing about this record.
             *
             * The worker then dies having sent no notification that
             * reaches this record's bytes, so the supervisor's synthetic
             * post-recovery wakeup is the ONLY path that can deliver it. */
            if (getenv("FORKRUN_TEST_DRAIN_ACK_FIFO") != NULL) {
                const char *m = getenv("FORKRUN_TEST_DIE_BEFORE_NOTIFY_MARK");
                if (m != NULL && *m) {
                    int mf = open(m, O_WRONLY | O_CREAT | O_APPEND, 0600);
                    if (mf >= 0) {
                        ssize_t ig = write(mf, "N\n", 2);
                        (void)ig;
                        close(mf);
                    }
                }
                (void)fr_py_signal_write(signal_fd, (uint64_t)wid, 0);
                fr_drain_test_wait_ack((uint64_t)wid);
            }
            raise(SIGKILL);
        }
    }
}

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

    /* DECISION-02: a completed batch ALWAYS gets a record now.
     *
     * This used to `return 0` on src_len == 0, under the comment "v0
     * parity: empty output emits no record (None)". The parity claim was
     * wrong: fr_py_emit's documented v0 contract and test_v1_emit.py both
     * say a zero-length payload IS emitted. The early return therefore
     * matched only the None case and silently dropped a legitimate empty
     * result.
     *
     * Now the disposition distinguishes them explicitly: src_len == 0 is
     * NO_RESULT, and a real empty DATA result is carried as DATA with
     * len == 0.
     *
     * NOTE (comment-only clarification, no behaviour change): the
     * sentence above describes what the DISPOSITION FIELD can express,
     * NOT what this function emits. THIS FUNCTION INFERS, and therefore
     * can never produce an empty DATA frame -- it has no other input to
     * infer from. Empty DATA is reachable only through
     * fr_py_emit_record_buf (explicit disposition) or fr_py_emit.
     *
     * That inference is deliberate and correct for this function's
     * callers. Two are the stdout-CAPTURE paths (cap_fd,
     * fstat on the capture file); a third is the sendfile-unavailable
     * fallback inside fr_py_worker_splice_loop. (An earlier draft of
     * this comment said "exactly two callers" and was wrong -- the
     * splice fallback is a third. See also the splice fast path, which
     * frames DATA inline and therefore bypasses this function entirely.)
     *
     * UDF results must NOT come through here: a UDF returning None and a
     * UDF returning b"" would produce identical records. They go through
     * fr_py_emit_record_buf, which takes the disposition from the actual
     * Python return value. See also fr_py_emit_record_buf's own header
     * comment, which states the same rule. */
    woff = lseek(out_fd, 0, SEEK_END);
    if (woff == (off_t)-1)
        return -1;
    hdr.batch_idx = batch_idx;
    hdr.len = src_len;
    hdr.disposition = (src_len == 0) ? FR_DISP_NO_RESULT : FR_DISP_DATA;
    hdr.reserved = 0;
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

    /* W-PY29: the COMPLETE record is durable -- header AND body.
     *
     * Advanced HERE, not by the caller, and unconditionally. Two caller
     * shapes got this wrong:
     *   - one advanced only `if (cap_len > 0)` while this framer ALWAYS
     *     writes a header, so a zero-payload NO_RESULT record left the
     *     rollback frontier behind. Recovery then truncated to a stale
     *     output_start and destroyed an already-committed terminal
     *     record -- which the drain's cursor had already moved past.
     *   - one skipped the emit entirely on cap_len == 0, so a successful
     *     command with empty stdout produced NO terminal record at all,
     *     and an ordered consumer waited forever on a batch that had in
     *     fact finished.
     *
     * Making the framer responsible removes the whole class: a caller
     * cannot forget an advance it no longer performs. */
    worker_txn_advance_output(-1, FR_PY_RECORD_FOOTPRINT(src_len));
    /* C0.7: count only the DATA case. src_len == 0 is a NO_RESULT
     * terminal record, which the parent framer filters and which must
     * never appear on either side of the completeness comparison --
     * those records exist so an ordered consumer does not wait forever
     * on a batch that finished with no output. */
    if (src_len > 0)
        if (fr_c07_enabled())
            fr_py_txn_pending_data++;
    return 0;
}

/* Emit a record whose payload is already in memory, with an EXPLICIT
 * disposition.
 *
 * fr_py_emit_record cannot be used for a UDF result for two reasons: its
 * payload comes from a src_fd, and it infers NO_RESULT from src_len == 0.
 * Both are wrong here. The UDF's bytes are in a malloc'd buffer, and --
 * far more importantly -- inferring the disposition from length is
 * precisely the conflation DECISION-02 exists to remove: a UDF returning
 * b"" and a UDF returning None would produce identical records.
 *
 * The disposition is therefore passed in by the caller, which got it
 * from the helper's own return code, which got it from the actual Python
 * return value. */
static int fr_py_emit_record_buf(int out_fd, uint64_t batch_idx,
                                 const char *data, uint64_t len,
                                 uint32_t disposition) {
    struct fr_py_record_hdr hdr;

    if (lseek(out_fd, 0, SEEK_END) == (off_t)-1)
        return -1;
    hdr.batch_idx = batch_idx;
    hdr.len = len;
    hdr.disposition = disposition;
    hdr.reserved = 0;
    if (fr_py_write_all(out_fd, &hdr, sizeof(hdr)) != 0)
        return -1;
    if (len > 0 && data) {
        if (fr_py_write_all(out_fd, data, (size_t)len) != 0)
            return -1;
    }
    worker_txn_advance_output(0, FR_PY_RECORD_FOOTPRINT(len));
    /* C0.7: the disposition is EXPLICIT here, unlike fr_py_emit_record
     * which infers it from length. Count only DATA; SKIPPED/POISONED/
     * NO_RESULT are control records the parent filters. A zero-length
     * DATA (a UDF returning b"") is a real frame and IS counted. */
    if (disposition == FR_DISP_DATA)
        if (fr_c07_enabled())
            fr_py_txn_pending_data++;
    return 0;
}


/* Emit a terminal control disposition for a batch that produced no
 * payload: SKIPPED (on_error=skip) or POISONED (retry limit reached).
 *
 * EXPORTED, not static: the worker loops call it in-process, but the
 * exactly-once proof has to exercise the REAL emitter rather than
 * re-implement the write in a test. A test that hand-rolls the record
 * would skip the frontier advance -- the very thing that makes rollback
 * remove the record -- and would pass while the shipped path leaked a
 * duplicate on every retry.
 *
 * DECISION-02 5.1. Before this those two outcomes were indistinguishable
 * from a worker that died: no record at all, so the parent's only
 * evidence was the poison counter, and an ordered consumer could not
 * advance the prefix -- the batch looked like a hole and the consumer
 * waited for a record that was never coming.
 *
 * Zero payload BY DESIGN. An empty DATA record instead would make poison
 * indistinguishable from a UDF that legitimately returned b"", which is
 * exactly the conflation the disposition exists to remove.
 *
 * The frontier advance matters as much as the write: the record is part
 * of the batch's output transaction, so a death before the ack rolls it
 * back with everything else and the retry re-emits it. Emitting outside
 * the transaction would leak a disposition for a batch about to run
 * again. */
int fr_py_emit_disposition(int out_fd, int signal_fd, uint64_t wid,
                           uint64_t batch_idx, uint32_t disposition)
{
    /* STAGE0: WRITE ONLY -- no signal.
     *
     * This used to write and then signal immediately, which is the
     * publication/commit race: the drain could forward an uncommitted
     * disposition, and recovery's rollback could not retract it. An
     * ordered consumer that advanced its prefix on a forwarded SKIPPED
     * could later see the retried attempt's DATA for a batch it had
     * already closed.
     *
     * The caller MUST now follow up with a post-commit notification
     * (fr_py_complete with the real signal descriptor, or
     * fr_py_notify_committed) once the disposition's transaction has
     * committed. A silent ack would commit POISONED/SKIPPED and tell
     * nobody, and an ordered consumer would wait forever on a batch that
     * has in fact finished.
     *
     * signal_fd is retained for ABI stability and deliberately unused. */
    (void)signal_fd;
    (void)wid;
    if (fr_py_emit_record_buf(out_fd, batch_idx, NULL, 0, disposition) != 0)
        return -1;
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
                    /* NOTE (W-REL1/R4): SPLICE_F_MOVE here is NOT the
                     * ingress hazard removed below — the source is a
                     * PIPE (no page cache, nothing fallow punches),
                     * and cap_fd is never hole-punched. Only
                     * memfd-source splices race PUNCH_HOLE. */
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
                    /* NO SPLICE_F_MOVE here, ever (W-REL1/R4): it asks
                     * the kernel to detach pages from the tmpfs page
                     * cache, and when the fallow reaper concurrently
                     * calls fallocate(PUNCH_HOLE) on this same ingress
                     * memfd the two paths deadlock in a kernel-level
                     * lock inversion on the inode/page locks. The
                     * engine removed both splice flags at
                     * forkrun_ring.c:~7800 with exactly this
                     * post-mortem; flags=0 copies pages instead of
                     * moving them (noise at 1MB batches — the spawn
                     * benchmark cannot tell). Do not re-add without
                     * re-reading that post-mortem. */
                    ssize_t n = splice(ingress_fd, &splice_off, stdin_pipe[1],
                                       NULL, want, 0);
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
            /* STAGE0: emitted unconditionally. cap_len == 0 is a real
             * completed batch with no output, and it gets a NO_RESULT
             * terminal record -- without one, an ordered consumer waits
             * forever on a batch that has finished. The frontier advance
             * lives inside the framer. */
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
 *
 * W-PY26: the body lives in fr_py_plugin_invoke (static, no dlopen)
 * so the C worker loop reuses it per batch without duplicating the
 * ctx/capture/emit logic. fr_py_plugin_call is ensure + invoke.
 */
static int fr_py_plugin_invoke(int ingress_fd, int out_fd,
                               uint64_t batch_off, uint64_t batch_len,
                               uint64_t batch_idx, uint32_t line_count,
                               uint32_t num_kills, int wid, int wincarn) {
    int rc;
    int is_raw;
    struct forkrun_ctx ctx;
    size_t batch_argc = 0;
    int cap_fd = -1;
    int saved_stdout = -1;
    int cb_ret = 0;
    struct stat st;
    uint64_t cap_len = 0;

    if (ingress_fd < 0 || out_fd < 0)
        return -1;
    if (!fr_py_plugin_handle)
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
    /* STAGE0: emitted unconditionally on success, so an empty-stdout
     * command still gets its NO_RESULT terminal record. The frontier
     * advance lives inside the framer. */
    if (cb_ret == 0) {
        if (fr_py_emit_record(out_fd, batch_idx, cap_fd, 0, cap_len) != 0)
            return -1;
    }

    /* ring_call truncation rule: nonzero → &0xFF, never silent 0. */
    if (cb_ret == 0)
        return 0;
    {
        int truncated = cb_ret & 0xFF;
        return (truncated == 0) ? 1 : truncated;
    }
}

int fr_py_plugin_call(const char *path, const char *func_name,
                      int ingress_fd, int out_fd, uint64_t batch_off,
                      uint64_t batch_len, uint64_t batch_idx,
                      uint32_t line_count, uint32_t num_kills, int wid,
                      int wincarn) {
    int rc;

    if (!path || !func_name || ingress_fd < 0 || out_fd < 0)
        return -1;
    rc = fr_py_plugin_ensure(path, func_name);
    if (rc != 0)
        return -2;
    return fr_py_plugin_invoke(ingress_fd, out_fd, batch_off, batch_len,
                               batch_idx, line_count, num_kills,
                               wid, wincarn);
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

/* W-PY16/W-PY21: published-DATA-batch high-water marks (worker
 * fork timing). File-static so both init entry points can reset
 * them: a new init is a new epoch (see fr_py_data_hwm_reset).
 * The w<hwm self-reset at poll time stays as a second defense. */
static uint64_t fr_py_data_hwm = 0;
static uint64_t fr_py_data_hwm_node[512] = {0};

/* The publish marks are per-RUN state. Resetting them at init —
 * not only on the w<hwm heuristic at poll time — is load-bearing:
 * a fast pipeline can publish its whole run before the parent's
 * first poll, and a stale mark would then swallow every publish
 * into its shadow (zero observed forever → workers never fork →
 * publish anomaly). Both init entry points call this. */
static void fr_py_data_hwm_reset(void) {
    int i;
    fr_py_data_hwm = 0;
    for (i = 0; i < 512; i++)
        fr_py_data_hwm_node[i] = 0;
}

/* W-PY16: count of published DATA batches (for worker fork timing).
 *
 * The scanner's pre-flight BAILS when a worker is already waiting
 * (active_waiters > 0 → CASE B → phase 1), and entering phase 1 with
 * already-complete input publishes nothing (workers then see instant
 * EOF: silent data loss). So the parent must not fork workers during
 * pre-flight. Pre-flight completion is unobservable directly, but
 * publishing only happens in the main loop (post-pre-flight) — hence
 * this query: cumulative DATA batches published (a batch counts when
 * lines>0, or byte-length>0 for byte-mode's 0-means-undefined).
 * The zero-length EOF sentinel never counts. A high-water mark makes
 * repeated polls amortized O(total).
 *
 * Python must read this ONLY through here (never raw MAP_SHARED
 * coordination words — the fences live in C).
 */

uint64_t fr_py_data_ready(void) {
    uint64_t found = 0;
    uint64_t w;

    if (!state)
        return 0;
    w = __atomic_load_n(&state[0].write_idx, __ATOMIC_ACQUIRE);
    if (w < fr_py_data_hwm)
        fr_py_data_hwm = 0; /* new run: scanner reset the indices */
    while (fr_py_data_hwm < w) {
        uint64_t slot = fr_py_data_hwm & RING_MASK;
        uint32_t lines = state[0].lines_ring[slot];
        uint64_t off = state[0].offset_ring[slot];
        uint64_t end = state[0].end_ring[slot];
        if (lines > 0 || end > off)
            found++;
        fr_py_data_hwm++;
    }
    return found;
}

/* Write one keyed "bytes are visible" signal (wid, batch_idx).
 *
 * fr_py_drain_loop blocks on this and only ever inspects the worker id
 * it names -- so a record written WITHOUT a signal is never moved to the
 * results stream, however correct it is in the worker's memfd. */
/* STAGE0: signal payload is (worker, COMMITTED FRONTIER), not
 * (worker, batch_idx).
 *
 * The frontier is an ABSOLUTE byte offset into the worker's output
 * memfd, taken only after the batch has committed (worker_txn_clear's
 * TXN_IDLE release store). The drain forwards at most up to it, so no
 * wakeup can ever publish bytes belonging to a transaction that is still
 * CLAIMED or COMMITTING -- which is the publication/commit race this
 * replaces.
 *
 * Offsets are absolute and monotonic for the lifetime of the memfd.
 * out_fds[] is created once by the launcher and REUSED across worker
 * generations, so the drain's per-worker cursor is persistent and must
 * never be reset on respawn. */
static int fr_py_signal_write(int signal_fd, uint64_t wid, uint64_t frontier)
{
    uint64_t sig[2];
    const char *sp;
    size_t sleft;

    if (signal_fd < 0)
        return 0;
    sig[0] = wid;
    sig[1] = frontier;
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

/* STAGE0: post-commit notification.
 *
 * Called ONLY after the acknowledgement has succeeded, i.e. after the
 * transaction has committed (worker_txn_clear -> TXN_IDLE). Publishes
 * the committed frontier so the drain can forward exactly that far.
 *
 * The frontier is read with SEEK_END: every byte below it belongs to a
 * committed transaction, because uncommitted output is truncated back to
 * output_start by recovery before this worker can reach here again.
 *
 * Returns a DISTINCT code (-4) for "committed but not notified",
 * separate from every pre-commit failure code. A caller that treats all
 * nonzero returns as "worker died, retry the batch" would otherwise
 * re-execute work the engine has already committed -- introducing a
 * duplicate execution bug inside the fix for the publication race.
 *
 * -4 means: TXN_IDLE was already stored, the batch IS committed, and the
 * drain has not been told. Permitted responses are recovery notification
 * or aborting the run without claiming success. NEVER a plain retry.
 *
 * EXPORTED, not static: publication is now a separate step from emit, so
 * a test that hand-rolled "write then signal" would not be exercising the
 * shipped boundary. fr_py_emit_disposition is exported for the same
 * reason. */
#define FR_PY_ERR_NOTIFY (-4)

int fr_py_notify_committed(int signal_fd, int out_fd, uint64_t wid)
{
    off_t frontier;
    int rc;

    if (signal_fd < 0)
        return 0;         /* no notification requested: nothing to do */

    /* STAGE0 fault injection: fail the notification once per process,
     * AFTER the commit. This is the interval where a batch is committed
     * but the drain was never told, and it is the one case where a
     * caller mishandling the return value re-executes committed work --
     * a duplicate-execution bug introduced by the fix itself. The
     * recovery state machine must classify the worker's death as IDLE
     * ("committed, nothing in flight") and NOT retry the batch.
     *
     * Inert unless the variable is set. */
    {
        const char *f = getenv("FORKRUN_TEST_NOTIFY_FAIL_ONCE");
        if (f != NULL && *f) {
            static int fired = 0;
            if (!fired) {
                fired = 1;
                /* Leave positive evidence the fault fired. A test that
                 * cannot tell whether it injected anything is the exact
                 * vacuous shape that produced a wrong conclusion earlier
                 * in this work. */
                {
                    const char *m = getenv("FORKRUN_TEST_NOTIFY_FAIL_MARK");
                    if (m != NULL && *m) {
                        int mf = open(m, O_WRONLY | O_CREAT | O_APPEND, 0600);
                        if (mf >= 0) {
                            ssize_t ig = write(mf, "F\n", 2);
                            (void)ig;
                            close(mf);
                        }
                    }
                }
                return FR_PY_ERR_NOTIFY;   /* committed, unnotified */
            }
        }
    }
    /* Every failure below is POST-COMMIT: the transaction is already
     * TXN_IDLE, so each is "committed, unnotified" and must be reported
     * as FR_PY_ERR_NOTIFY. Returning a plain -1 would let it be confused
     * with a pre-commit failure, and a caller that retries on those would
     * re-execute committed work. */
    if (out_fd < 0)
        return FR_PY_ERR_NOTIFY;

    /* STAGE0 TEST-ONLY: exercise the REAL signal-write failure instead of
     * a synthetic return. Closing only THIS process's duplicate of
     * signal_fd makes write() fail with EBADF while the drain and the
     * launcher's spare writer stay open -- so the supervisor can still
     * send its synthetic recovery wakeup, which is the entire point of
     * the case. Nothing is killed here; the real notifier runs and fails
     * on its own.
     *
     * Inert unless the variable is set. */
    if (getenv("FORKRUN_TEST_CLOSE_SIGNAL_FD") != NULL) {
        const char *m = getenv("FORKRUN_TEST_NOTIFY_FAIL_MARK");
        if (m != NULL && *m) {
            int mf = open(m, O_WRONLY | O_CREAT | O_APPEND, 0600);
            if (mf >= 0) {
                ssize_t ig = write(mf, "C\n", 2);
                (void)ig;
                close(mf);
            }
        }
        close(signal_fd);
    }

    frontier = lseek(out_fd, 0, SEEK_END);
    if (frontier == (off_t)-1)
        return FR_PY_ERR_NOTIFY;
    rc = fr_py_signal_write(signal_fd, wid, (uint64_t)frontier);
    if (rc != 0)
        return FR_PY_ERR_NOTIFY;
    return 0;
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

    if (data != NULL && out_fd >= 0) {
        hdr.batch_idx = batch_idx;
        /* This path is reached only when data != NULL, and its contract
         * already treats a zero-length payload as a REAL empty result
         * (test_v1_emit.py). So it is always DATA -- never NO_RESULT,
         * which would be the case the caller signals by passing NULL and
         * therefore not reaching here at all. */
        hdr.disposition = FR_DISP_DATA;
        hdr.reserved = 0;
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
                    /* W-REL5-D (D4): with niov == 1 (header-only emit)
                     * there is no iov[1] -- copying it reads
                     * uninitialized stack on every zero-length emit.
                     * Mark done instead. (A bare `break` here would
                     * leave niov == 1 with len 0, and the outer loop
                     * would writev a zero-length iovec, observe n == 0
                     * and wrongly return -1 for a successful b""
                     * emit -- test_v1_emit pins the None-vs-b""
                     * distinction.) */
                    if (niov == 1) {
                        niov = 0;
                        break;
                    }
                    iov[0] = iov[1];
                    niov--;
                }
            }
        }
        /* W-PY29: the COMPLETE record (header framing + payload) is
         * durable — advance the rollback frontier. Partial writes
         * return -1 above before reaching here. */
        worker_txn_advance_output((int)wid, FR_PY_RECORD_FOOTPRINT(data_len));
        /* C0.7: one DATA frame is now durable, but NOT committed. Count
         * it against the pending total only; fr_py_ack_core transfers it
         * to the shared field after the ack side effects succeed and
         * just before worker_txn_clear publishes TXN_IDLE. Reached only
         * for data != NULL, so a null emission -- which writes no record
         * at all -- contributes nothing. A zero-length b"" DOES reach
         * here and IS a real DATA frame. */
        if (fr_c07_enabled())
            fr_py_txn_pending_data++;
    }

    /* STAGE0: NO signal here.
     *
     * This used to signal the drain as soon as the bytes were written,
     * which let an UNCOMMITTED record be forwarded: the drain acted on a
     * wakeup alone and forwarded everything up to the memfd's current
     * size, so a record written before its ack could be published and
     * then could not be retracted when recovery rolled it back. A
     * poisoned batch could therefore return the abandoned attempt's DATA
     * while the run reported success.
     *
     * Publication is now strictly post-commit. The caller signals via
     * fr_py_notify_committed() after the ack succeeds, carrying the
     * committed frontier. signal_fd is retained for ABI stability and is
     * deliberately unused here. */
    (void)signal_fd;
    return 0;
}

/* Flush C stdio before ack/deposit points in the splice loop (it has
 * no Python streams of its own; fflush(NULL) also protects buffered
 * output from any plugin sharing the worker). */
static void _flush_for_splice(void) {
    fflush(NULL);
}

/* =====================================================================
 * W-PY18: C splice worker loop — bash -b/-s parity (no payload case).
 *
 * Runs the WHOLE worker loop in C: claim → move bytes ingress→output
 * → signal → ack, until EOF. Zero Python objects, zero ctypes calls,
 * zero Python function calls per batch. The "payload" is kernel data
 * movement (passthrough), which is what makes this mode fast.
 *
 * Built ONLY on tested primitives (deviations from the W-PY18 sketch,
 * whose do_ack_current_batch/do_ack_with_fallow don't exist):
 * - fr_py_claim (TLS publishing, poison detection + counting),
 * - fr_py_ack (fallow/disarm) and fr_py_escrow_deposit (retry).
 * Error semantics mirror _worker.py: poisoned → warn + ack + skip;
 * output failure → escrow (kills+1, retry) like a payload error;
 * signal EPIPE → fatal (infrastructure); claim abort → fatal.
 * on_error policies are NOT consulted (retry-always, documented).
 *
 * Body movement is sendfile(out, ingress, &off, len) — kernel-level,
 * file→file, no pipe staging (the sketch's splice(2) needs an
 * intermediate pipe per batch; sendfile doesn't). Falls back to
 * fr_py_emit_record's pread/write copy when sendfile is unavailable.
 * Framing is identical to the v0 emitter ([idx][len][bytes]) so the
 * parent parses untouched. Every byte appended is final (W-PY13
 * append-once rule for the concurrent streaming reader): on ANY
 * output failure the partial record is truncated before escrow.
 *
 * Returns 0 drained-to-EOF, 1 claim failure/abort, 2 signal failure.
 * The Python child maps nonzero → worker exit 1 → parent RuntimeError.
 * ===================================================================== */
int fr_py_worker_splice_loop(int wid, int ingress_fd, int out_fd,
                             int signal_fd, int fallow_fd) {
    fr_py_batch_t claimed;
    int rc;

    if (ingress_fd < 0 || out_fd < 0)
        return 1;
    /* W-PY28: name the output fd for transaction publication + sync
     * the ack offset (respawned generations append to a reused fd). */
    fr_py_txn_out_fd = out_fd;
    fr_py_ack_init(out_fd);
    while (1) {
        off_t end = (off_t)-1;
        /* STAGE0: set when the sendfile sub-path fell back to the
         * framer, which then owns the frontier advance. */
        int via_framer = 0;
        off_t woff;
        uint64_t left;

        rc = fr_py_claim(&claimed);
        if (rc == 2)
            return 0; /* EOF: drained */
        if (rc != 0)
            return 1; /* abort/failure */

        if (claimed.poisoned) {
            fprintf(stderr,
                    "forkrun [WARN]: Skipping poisoned batch %llu "
                    "(killed %u times).\n",
                    (unsigned long long)claimed.batch_idx,
                    claimed.num_kills);
            /* DECISION-02: terminal POISONED disposition, emitted
             * BEFORE the ack, so a death in between rolls it back
             * with the rest of the batch. */
            if (fr_py_emit_disposition(out_fd, signal_fd, (uint64_t)wid,
                                       claimed.batch_idx,
                                       FR_DISP_POISONED) != 0)
                return 1;
            /* STAGE0: notify AFTER the ack. This branch uses fr_py_ack
             * rather than fr_py_complete, so a scan keyed on
             * fr_py_complete would not have found it -- which is exactly
             * how the splice POISONED path shipped without a notify
             * while the DATA path beside it was migrated. A committed
             * POISONED record that is never announced leaves the
             * consumer missing a terminal outcome. */
            if (fr_py_ack(fallow_fd, -1) != 0)
                return 1;
            if (fr_py_notify_committed(signal_fd, out_fd,
                                      (uint64_t)wid) != 0)
                return 2; /* committed, unnotified: must not be retried */
            continue;
        }

        if (claimed.length == 0) {
            /* EOF sentinel slot: ack but never emit (bash REPLY rule). */
            if (fr_py_ack(fallow_fd, -1) != 0)
                return 1;
            continue;
        }

        /* Frame + move the body: header first (true length up front
         * — parseable at every prefix), then sendfile streaming at
         * the end, then signal ("record bytes are visible"), then
         * ack (releases the batch). */
        {
            struct fr_py_record_hdr hdr;
            hdr.batch_idx = claimed.batch_idx;
            hdr.len = claimed.length;
            /* DECISION-02: set disposition/reserved EXPLICITLY. Leaving
             * them unset makes the record carry uninitialized stack bytes,
             * which the reader then treats as a control disposition and
             * drops -- so every record from this path vanished and splice
             * mode returned empty output. This is the same defect as the
             * uint64_t/4-byte mismatch in the parser, in the other
             * direction: an unset field on the wire is undefined. */
            hdr.disposition = FR_DISP_DATA;
            hdr.reserved = 0;
            end = lseek(out_fd, 0, SEEK_END);
            if (end == (off_t)-1)
                goto payload_error;
            if (fr_py_write_all(out_fd, &hdr, sizeof(hdr)) != 0)
                goto payload_error;
            woff = (off_t)claimed.offset;
            left = claimed.length;
            while (left > 0) {
                size_t want =
                    left > (1 << 20) ? (1 << 20) : (size_t)left;
                ssize_t n = sendfile(out_fd, ingress_fd, &woff, want);
                if (n < 0) {
                    if (errno == EINTR)
                        continue;
                    /* sendfile unavailable for this pair — rewind
                     * past the header and use the whole-record copy
                     * helper instead. */
                    if (ftruncate(out_fd, end) != 0)
                        goto payload_error;
                    if (fr_py_emit_record(out_fd, claimed.batch_idx,
                                          ingress_fd, claimed.offset,
                                          claimed.length) != 0)
                        goto payload_error;
                    /* The framer advanced the frontier itself (STAGE0);
                     * suppress the sendfile sub-path's advance below so
                     * it is not counted twice. */
                    via_framer = 1;
                    break;
                }
                if (n == 0)
                    goto payload_error; /* short: retry, don't emit */
                left -= (uint64_t)n;
            }
            /* The sendfile sub-path framed its own header inline, so it
             * advances here. The fr_py_emit_record fallback advances
             * inside the framer since STAGE0 -- advancing again would
             * double-count and leave the frontier pointing PAST the real
             * end of the memfd, which is worse than the stale-frontier
             * bug it replaced. */
            if (!via_framer)
                worker_txn_advance_output(wid,
                                          FR_PY_RECORD_FOOTPRINT(claimed.length));
        }

        /* STAGE0: no signal here.
         *
         * Splice used to hand-roll its own signal carrying the BATCH
         * INDEX, written BEFORE the ack. Both parts are wrong now: it
         * published uncommitted bytes (the race Stage 0 removes), and a
         * batch index is meaningless to a drain that bounds forwarding by
         * the committed FRONTIER -- it silently forwarded almost nothing,
         * so the C drain returned an empty stream.
         *
         * Splice acknowledges below and publishes through
         * fr_notify_committed afterwards, like every other emitter. This
         * is a THIRD emitting path that a fr_py_emit /
         * fr_py_emit_disposition audit would not have listed, because it
         * calls neither. */
        /* Splice's success path: record framed and committed above.
         * Hooked here because splice does not call fr_py_complete, and
         * the other two fr_py_ack sites in this loop are the
         * poison/sentinel branches. Splice is excluded from the loop
         * parity test by design (it moves bytes rather than invoking
         * user code), so a loop-local hook cannot desynchronise it. */
        fr_py_maybe_die_before_ack((int)wid, signal_fd);

        if (fr_py_ack(fallow_fd, -1) != 0)
            return 1;
        if (fr_py_notify_committed(signal_fd, out_fd, (uint64_t)wid) != 0)
            return 2; /* EPIPE: parent gone -- fatal */
        continue;


    payload_error:
        /* Output failure rides escrow like a payload error (bash -E):
         * truncate any partial record (append-once rule), no ack (the
         * deposit arms the retry), same-process retry on re-claim. */
        if (end != (off_t)-1)
            (void)ftruncate(out_fd, end);
        _flush_for_splice();
        fr_py_escrow_deposit(claimed.num_kills + 1);
        continue;
    }
}

/* =====================================================================
 * W-PY18 addendum: zero-copy ingest + raw window.
 *
 * fr_py_copy_range: single-shot kernel copy src[src_off, +len) to
 *   dst[dst_off, +len) — copy_file_range, then sendfile, else -1 so
 *   the caller falls back to a pread/pwrite loop. EXPLICIT offsets
 *   both sides (never touches fd positions: the W-PY16 lesson — the
 *   scanner seeds its base from the shared SEEK_CUR). Returns bytes
 *   copied (>0, possibly short), 0 for len==0 / EOF at src_off, -1
 *   on any failure (caller retries via userspace copy). Same
 *   method order as the engine's ingest probe (copy_file_range →
 *   sendfile → read/write), minus its bounce buffer (the Python
 *   fallback owns its chunk).
 *
 * fr_py_get_raw_window: borrowed pointer into the ingress memfd for
 *   [offset, offset+length) via the engine's TLS-cached MAP_SHARED
 *   mapping (the same ring_call FLAG_RAW mechanism the v1 plugin
 *   path uses internally — this only EXPOSES the pointer to Python).
 *   NULL on failure. Lifetime: valid until the worker's next remap
 *   (streaming growth) or exit; unacked windows are never punched.
 *   Materialized workers map once, so the window is stable for the run
 *   there.
 *   W-REL5-D (D14): the old trailing clause here ("hole reads
 *   zero-fill regardless") was TRUE for read()/pread and FALSE for
 *   this MAP_SHARED window (and the plugin RAW window): accessing a
 *   punched range through a live mapping faults SIGBUS instead of
 *   returning zeroes. The safety argument is therefore
 *   invariant-based, not mechanical: fallow punches only behind the
 *   acked contiguous prefix, so a live (unacked) window's pages are
 *   intact -- the same guarantee the C RAW tier documents -- plus the
 *   standing rule that views die at payload return (batch.copy() to
 *   persist). No mechanical re-validation is attempted: mincore races
 *   the punch (TOCTOU), mlock does not pin punched pages, and a
 *   SIGBUS-handler/longjmp recovery is too risky inside workers.
 *   A use-after-ack/punch window access is a contract violation, not
 *   a handled error.
 * ===================================================================== */
int64_t fr_py_copy_range(int src_fd, uint64_t src_off, int dst_fd,
                         uint64_t dst_off, uint64_t length) {
    loff_t in_off;
    loff_t out_off;
    size_t want;
    ssize_t n;

    if (src_fd < 0 || dst_fd < 0)
        return -1;
    if (length == 0)
        return 0;
    want = (size_t)(length > (1 << 20) ? (1 << 20) : length);
    in_off = (loff_t)src_off;
    out_off = (loff_t)dst_off;
    n = copy_file_range(src_fd, &in_off, dst_fd, &out_off, want, 0);
    if (n > 0)
        return (int64_t)n;
    if (n == 0)
        return 0; /* EOF at src_off */
    if (errno != EINTR) {
        /* Unsupported pair (EXDEV/EINVAL/ENOSYS/EPERM...) or hard
         * error: one sendfile attempt, then punt to userspace. */
        in_off = (loff_t)src_off;
        n = sendfile(dst_fd, src_fd, &in_off, want);
        if (n > 0)
            return (int64_t)n;
        if (n == 0)
            return 0;
        return -1;
    }
    return -1; /* EINTR with zero progress: caller retries/loops */
}

void *fr_py_get_raw_window(int fd, uint64_t offset, uint64_t length) {
    if (fd < 0 || length == 0)
        return NULL;
    if (ring_call_ensure_ingress_map(fd, offset, (size_t)length) != 0)
        return NULL;
    if (tls_ingress_map == NULL)
        return NULL;
    return (char *)tls_ingress_map + offset;
}

/* =====================================================================
 * W-PY19: reactor orchestration support — orderer, order-pipe setup,
 * and spawn-aware scan. Engine frozen: these only CALL existing
 * engine entry points (ring_order_main, core_scanner_loop) or fill
 * g_fr_config, exactly like the existing fr_py_* wrappers above.
 * ===================================================================== */

/* Set the worker-local order-pipe fd for ordered acks (W-PY19).
 *
 * fr_py_worker_init hardcodes fd_order_pipe=-1 (unordered default).
 * The reactor's C-orderer path sets it post-fork, pre-claim: the
 * worker's first fr_py_ack(target_fd) then emits an OrderPacket to
 * this pipe (the engine's ack_cached_order_pipe picks it up from
 * g_fr_config on first use — TLS cache starts -1 in the forked
 * child, so setting the config before the first ack is sufficient).
 * Returns 0 ok, 1 when no substrate state exists. */
int fr_py_set_order_pipe(int fd) {
    if (!state || !g_state)
        return 1;
    g_fr_config.fd_order_pipe = fd;
    return 0;
}

/* Spawn-aware scan (W-PY19 dynamic scaling).
 *
 * Same as fr_py_scan but forwards the scanner's spawn requests
 * ("count\n" UMA / "node:count\n" NUMA, one per line) to spawn_w:
 * the reactor's spawn pipe. Pass -1 to disarm (plain fr_py_scan
 * behavior). Returns the engine rc. Runs in a forked scanner child
 * (blocking), never in the reactor parent thread. */
int fr_py_scan_with_spawn(int fd, int spawn_w) {
    return core_scanner_loop(fd, 0, spawn_w, 1, false);
}

/* C-level orderer (W-PY19, bash ring_order subshell equivalent).
 *
 * Runs the engine's ring_order_main in the CALLING process — fork an
 * orderer child first, then call this there and os._exit(rc):
 *   reads OrderPackets from order_pipe_r until EOF (every worker
 *   write end + the parent's copy closed), reorders via min-heap,
 *   emits ordered bytes to stdout (dup2'd to output_fd when it
 *   differs from 1), then returns the engine rc (0 clean).
 *
 * Transport contract (bash memfd mode): workers append keyed records
 * ([batch_idx u64][len u64][bytes], the v0.5 emitter framing) to
 * their own parent-created output memfds and ack with
 * fr_py_ack(fallow_w, out_fd) so each ack's OrderPacket names the
 * record's (fd, off, len); the orderer emits records in batch_idx
 * order, so the parent parses its stdout exactly like today — only
 * the ORDERING moved from Python reassembly into C. unordered != 0
 * selects pass-through mode; numa is accepted and forwarded but v0
 * runs UMA (0). output_fd < 0 leaves stdout untouched.
 * Returns the engine rc (0 clean, 1 failure/abort). */
int fr_py_orderer(int order_pipe_r, int output_fd,
                  int unordered_mode, int numa_mode) {
    char a0[] = "ring_order";
    char a1[32];
    char a2[] = "memfd";
    char a3[] = "unordered";
    char a4[] = "numa";
    char *argv[6];
    int argc = 0;

    if (order_pipe_r < 0)
        return 1;
    argv[argc++] = a0;
    snprintf(a1, sizeof(a1), "%d", order_pipe_r);
    argv[argc++] = a1;
    argv[argc++] = a2;
    if (unordered_mode)
        argv[argc++] = a3;
    if (numa_mode)
        argv[argc++] = a4;
    argv[argc] = NULL;

    if (output_fd >= 0 && output_fd != 1) {
        if (dup2(output_fd, 1) < 0)
            return 1;
        if (output_fd != 1)
            close(output_fd);
    }
    return ring_order_main(argc, argv);
}

/* =====================================================================
 * W-PY21: NUMA multi-node pipeline. Engine frozen: these only CALL
 * existing engine entry points with argv vectors, exactly like the
 * fr_py_* wrappers above. All run in forked children (blocking),
 * never in the reactor parent.
 * ===================================================================== */

/* NUMA-aware init (W-PY21). Same lines/bytes contract as fr_py_init,
 * plus the logical topology: num_nodes > 1 forwards --numa-map
 * (comma-separated physical IDs, e.g. "0,1") to ring_init_main,
 * which creates per-node rings, eventfds, escrow pipes and steal
 * thresholds. num_nodes <= 1 (or empty/NULL map) behaves exactly
 * like fr_py_init. Caps at the engine's 512 meta_ring ceiling.
 * Returns the engine rc (0 ok, 1 fail). */
int fr_py_init_numa(int lines, int bytes, int num_nodes,
                    const char *numa_map) {
    char a0[] = "ring_init";
    char a1[64];
    char a2[4096];
    char *argv[4];
    int argc = 0;

    if (lines < 0 || bytes < 0)
        return 1;
    if (lines > 0 && bytes > 0)
        return 1;
    if (num_nodes < 1 || num_nodes > 512)
        return 1;
    /* New epoch for the publish high-water marks (W-PY21). */
    fr_py_data_hwm_reset();
    argv[argc++] = a0;
    if (lines > 0) {
        snprintf(a1, sizeof(a1), "--lines=%d", lines);
        argv[argc++] = a1;
    } else if (bytes > 0) {
        snprintf(a1, sizeof(a1), "--bytes=%d", bytes);
        argv[argc++] = a1;
    }
    if (num_nodes > 1 && numa_map && numa_map[0]) {
        snprintf(a2, sizeof(a2), "--numa-map=%s", numa_map);
        argv[argc++] = a2;
    }
    argv[argc] = NULL;
    return ring_init_main(argc, argv);
}

/* NUMA ingest (W-PY21): born-local data distributor.
 * ring_numa_ingest <infd> <outfd> <nodes>: reads the SOURCE (not a
 * pre-spill — placement happens here, per chunk, via MPOL_BIND),
 * writes the shared ingress memfd, publishes ChunkMeta and signals
 * per-node indexers; EOF propagates internally via ingest_eof
 * (no fr_py_ingest_done gate needed). The usage string's 4th
 * [ordered] slot is vestigial (the engine never reads argv[4]).
 * Returns the engine rc. */
int fr_py_numa_ingest(int infd, int outfd, int num_nodes) {
    char a0[] = "ring_numa_ingest";
    char a1[32], a2[32], a3[32];
    char *argv[5];

    if (infd < 0 || outfd < 0 || num_nodes < 1 || num_nodes > 512)
        return 1;
    argv[0] = a0;
    snprintf(a1, sizeof(a1), "%d", infd);
    argv[1] = a1;
    snprintf(a2, sizeof(a2), "%d", outfd);
    argv[2] = a2;
    snprintf(a3, sizeof(a3), "%d", num_nodes);
    argv[3] = a3;
    argv[4] = NULL;
    return ring_numa_ingest_main(4, argv);
}

/* Per-node NUMA indexer (W-PY21): ring_indexer_numa <memfd> <node>.
 * Self-pins to the node's physical CPUs inside the engine.
 * Returns the engine rc. */
int fr_py_indexer_numa(int memfd, int node_id) {
    char a0[] = "ring_indexer_numa";
    char a1[32], a2[32];
    char *argv[3];

    /* W-REL5-D (D12): node_id indexes state[]/evfd (512 ceiling, like
     * fr_py_init_numa's num_nodes bound) -- the old < 0-only check let
     * huge ids through to engine-side indexing. */
    if (memfd < 0 || node_id < 0 || node_id >= 512)
        return 1;
    argv[0] = a0;
    snprintf(a1, sizeof(a1), "%d", memfd);
    argv[1] = a1;
    snprintf(a2, sizeof(a2), "%d", node_id);
    argv[2] = a2;
    return ring_indexer_numa_main(3, argv);
}

/* Per-node NUMA scanner (W-PY21):
 * ring_numa_scanner <memfd> <node_id> <spawn_fd> <nodes>.
 * Distance-charged stealing when starved; spawn_fd -1 disarms
 * spawn requests (the Python ingest keeps publish-gated fork
 * timing — pre-flight bail avoidance, same rule as W-PY19).
 * Returns the engine rc. */
int fr_py_numa_scanner(int memfd, int node_id, int fd_spawn,
                       int num_nodes) {
    char a0[] = "ring_numa_scanner";
    char a1[32], a2[32], a3[32], a4[32];
    char *argv[6];

    /* W-REL5-D (D12): same 512 ceiling as the indexer/init sites. */
    if (memfd < 0 || node_id < 0 || node_id >= 512 || num_nodes < 1 ||
        num_nodes > 512)
        return 1;
    argv[0] = a0;
    snprintf(a1, sizeof(a1), "%d", memfd);
    argv[1] = a1;
    snprintf(a2, sizeof(a2), "%d", node_id);
    argv[2] = a2;
    snprintf(a3, sizeof(a3), "%d", fd_spawn);
    argv[3] = a3;
    snprintf(a4, sizeof(a4), "%d", num_nodes);
    argv[4] = a4;
    argv[5] = NULL;
    return ring_numa_scanner_main(6, argv);
}

/* Physical fallow, NUMA mode (W-PY21): ring_fallow_phys <PIPE> <FILE>.
 * Reads PhysPackets {off, len} (NUMA ack path writes physical
 * offsets, not IndexPackets). One process for all nodes.
 * Returns the engine rc (0 clean at pipe EOF). */
int fr_py_fallow_phys(int fd_in, int fd_file) {
    char a0[] = "ring_fallow_phys";
    char a1[32], a2[32];
    char *argv[3];

    if (fd_in < 0 || fd_file < 0)
        return 1;
    argv[0] = a0;
    snprintf(a1, sizeof(a1), "%d", fd_in);
    argv[1] = a1;
    snprintf(a2, sizeof(a2), "%d", fd_file);
    argv[2] = a2;
    return ring_fallow_phys_main(3, argv);
}

/* W-PYZEROCOPY: read-only mapping of a whole result stream, for the
 * parent-side collect.
 *
 * The collect is the parent's serial tail: every result byte has to
 * reach the orchestrator, and doing that with bytes objects means one
 * kernel->user copy for the stream PLUS one memcpy per record. Handing
 * the caller memoryview slices over a mapping removes the second copy
 * entirely, which is the same hand-a-reference shape bash's orderer uses
 * (it passes (fd, offset, len) and lets the kernel move bytes only if
 * the consumer reads them -- forkrun_ring.c:7520).
 *
 * Why this is in C and not Python's mmap: mmap.mmap(fd, ...) dups the
 * descriptor, and that dup is released only when the mmap object is
 * collected -- i.e. when the CALLER drops the records. Holding a result
 * list would hold an extra descriptor for the life of the list, which
 * is what test_concurrent's fd-stability gate and test_v1_fast's child
 * fd hygiene forbid. A mapping made here holds the file, not a
 * descriptor number, so nothing extra shows up in /proc/self/fd.
 *
 * Lifetime is the caller's problem and is delicate: the address is raw,
 * so the Python side wraps it in a ctypes array and attaches a
 * weakref.finalize that calls fr_py_unmap. Every memoryview slice
 * references that array, so the mapping cannot be torn down while a
 * record is alive -- touching a record after munmap is SIGSEGV, not an
 * exception. fr_py_unmap is idempotent-safe to call only once, which is
 * what finalize guarantees.
 *
 * PROT_READ only: a write through the mapping faults rather than
 * corrupting another record's bytes. */
/* MADV_POPULATE_READ landed in Linux 5.14; fall back to the older
 * WILLNEED hint where the build host's headers predate it. Both are
 * advisory -- correctness never depends on either. */
#ifndef MADV_POPULATE_READ
#define MADV_POPULATE_READ MADV_WILLNEED
#endif

int fr_py_map_readonly(int fd, uint64_t length, uint64_t *out_addr) {
    if (fd < 0 || length == 0 || !out_addr)
        return EINVAL;
    void *p = mmap(NULL, (size_t)length, PROT_READ, MAP_SHARED, fd, 0);
    if (p == MAP_FAILED)
        return errno ? errno : ENOMEM;
    /* Prefault. Without this the copy cost does not go away, it just
     * moves from the kernel's bulk copy into per-page faults paid
     * lazily by the parent's own loop -- measured SLOWER than a plain
     * pread for the 28 per-worker memfds (~98k faults for 386MB), and
     * slower still than pread even for the single orderer file. Populate
     * up front, in the kernel, where transparent huge pages can batch
     * it. Both hints are advisory: if neither is supported we simply
     * fault in on demand, which is correct, only slower. */
    (void)madvise(p, (size_t)length, MADV_POPULATE_READ);
    (void)madvise(p, (size_t)length, MADV_HUGEPAGE);
    *out_addr = (uint64_t)(uintptr_t)p;
    return 0;
}

void fr_py_unmap(uint64_t addr, uint64_t length) {
    if (addr && length)
        munmap((void *)(uintptr_t)addr, (size_t)length);
}

/* W-PYFORKGATE: NON-DESTRUCTIVE published-minus-consumed backlog for one
 * NUMA node's DATA ring.
 *
 * fr_py_data_ready_node above is deliberately consume-once: it walks
 * write_idx forward from a private high-water mark and returns only the
 * batches NEW since the previous call, because the fork gate uses it as a
 * one-shot "did anything publish yet" edge. That makes it unusable as a
 * level gauge — a caller that reads it and then decides its threshold was
 * not met has already discarded the evidence, and can never satisfy the
 * threshold on a later call.
 *
 * The fork gate needs a level: it must hold workers back until each node
 * has published enough backlog to keep them fed (see the gate loop in
 * run.py). This reads the two indices directly and never mutates them, so
 * it can be polled as often as the caller likes. write_idx only advances
 * over real DATA slots (the scanner publishes the zero-length EOF
 * sentinel separately), so no zero-length filtering is needed here. */
uint64_t fr_py_backlog_node(int node) {
    uint64_t w, r;

    if (!state || node < 0 || node >= 512 ||
        node >= (int)global_num_nodes)
        return 0;
    w = __atomic_load_n(&state[node].write_idx, __ATOMIC_ACQUIRE);
    r = __atomic_load_n(&state[node].read_idx, __ATOMIC_ACQUIRE);
    return (w > r) ? (w - r) : 0;
}

/* Per-node published-DATA-batch count (W-PY21 fork timing). Same contract as fr_py_data_ready but for one NUMA node's ring:
 * cumulative DATA batches (lines>0, or byte-length>0 for byte
 * mode's 0-means-undefined); the zero-length EOF sentinel never
 * counts. Python reads coordination words ONLY through here. */
uint64_t fr_py_data_ready_node(int node) {
    uint64_t found = 0;
    uint64_t w;

    if (!state || node < 0 || node >= 512 ||
        node >= (int)global_num_nodes)
        return 0;
    w = __atomic_load_n(&state[node].write_idx, __ATOMIC_ACQUIRE);
    if (w < fr_py_data_hwm_node[node])
        fr_py_data_hwm_node[node] = 0; /* second defense (see above) */
    while (fr_py_data_hwm_node[node] < w) {
        uint64_t slot = fr_py_data_hwm_node[node] & RING_MASK;
        uint32_t lines = state[node].lines_ring[slot];
        uint64_t off = state[node].offset_ring[slot];
        uint64_t end = state[node].end_ring[slot];
        if (lines > 0 || end > off)
            found++;
        fr_py_data_hwm_node[node]++;
    }
    return found;
}

/* NUMA ingest-EOF-posted query (W-PY21 helper classification).
 *
 * Returns 1 once the ingest published end-of-input
 * (g_state->ingest_eof_idx != ~0, the same sentinel the indexers
 * themselves watch), else 0. Monotonic within a run; reset by
 * init (see ring_init_main). Lets the parent tell "pipeline
 * helper exited before EOF was even posted" (tail-loss anomaly —
 * fatal) from "helper exited after EOF posted while the ingest
 * process is still flushing" (normal teardown ordering — the
 * ingest waits for chunk_done before exiting, so it is routinely
 * the LAST to be reaped). Process-exit ordering alone cannot
 * distinguish the two. Python reads this ONLY through here. */
int fr_py_ingest_eof_posted(void) {
    if (!g_state)
        return 0;
    return __atomic_load_n(&g_state->ingest_eof_idx,
                           __ATOMIC_ACQUIRE) != ~(uint64_t)0 ? 1 : 0;
}

/* =====================================================================
 * W-EXP-2 step C follow-up: PER-NODE completion evidence.
 *
 * The global ingest-EOF marker is NOT a per-node completion signal. It
 * says the source was consumed; it says nothing about whether a given
 * node's indexer consumed the chunks published for THAT node, or
 * whether that node's scanner finished publishing its final ring
 * state. A helper that exits cleanly after the global marker but before
 * its own work is done has left its node short, and treating that as
 * healthy turns a lost chunk into a hang.
 *
 * The two conditions are read straight out of the engine's own
 * publication protocol:
 *
 *   INDEXER -- ring_indexer_numa_main (forkrun_ring.c:3701) exits
 *   successfully when the global EOF is posted AND its node's
 *   chunk_queue_head has not moved past the chunk it last took. Each
 *   indexed chunk advances that node's chunk_ready_head
 *   (forkrun_ring.c:3833). So the node is fully indexed exactly when
 *   chunk_ready_head has caught up with chunk_queue_head -- and only
 *   then can the global marker mean "no more chunks are coming".
 *
 *   SCANNER -- ring_numa_scanner_main publishes the node's final
 *   write_idx and THEN sets scanner_finished
 *   (forkrun_ring.c:5913-5914), with the EOF evfd blasted only after
 *   that. scanner_finished is therefore the node's own completion
 *   state, published after its final ring state.
 *
 * Both accessors are READ-ONLY. Returns 1 = complete, 0 = not
 * complete, -1 = no verdict (bad node, no engine state). A -1 is
 * never read as "complete": the supervisor treats an unavailable
 * verdict as an absent one.
 * ===================================================================== */
int fr_py_node_index_complete(int node) {
    if (!g_state || !state || node < 0 || node >= (int)global_num_nodes)
        return -1;
    /* The global marker first: without it the node could still receive
     * another chunk, so a caught-up frontier proves nothing. */
    if (__atomic_load_n(&g_state->ingest_eof_idx, __ATOMIC_ACQUIRE)
        == ~(uint64_t)0)
        return 0;
    {
        uint64_t head = __atomic_load_n(&state[node].chunk_queue_head,
                                        __ATOMIC_ACQUIRE);
        uint64_t ready = __atomic_load_n(&state[node].chunk_ready_head,
                                         __ATOMIC_ACQUIRE);
        return ready >= head ? 1 : 0;
    }
}

int fr_py_node_scan_complete(int node) {
    if (!g_state || !state || node < 0 || node >= (int)global_num_nodes)
        return -1;
    return __atomic_load_n(&state[node].scanner_finished,
                           __ATOMIC_ACQUIRE) ? 1 : 0;
}

/* F-NUMA1 diagnostic snapshot (env-gated consumer in run.py; read-only).
 *
 * Per-node completion state for the NUMA drain-verification audit:
 * out[0] = write_idx (published slots, acquire), out[1] = read_idx
 * (claimed slots, acquire), out[2] = scanner_finished (acquire),
 * out[3] = chunk_queue_head (relaxed: chunks published by ingest),
 * out[4] = chunk_queue_tail (relaxed: chunks consumed by indexer).
 * Returns 0 ok, -1 bad node or no engine state. Pure loads — no
 * mutation, no fences touched, no publish path altered. The Python
 * parent calls this AFTER reactor_run (workers done) and BEFORE
 * teardown destroys the engine; indices are monotonic and finished
 * is sticky, so the window is stable. Never on a hot path (once per
 * node per run, behind FORKRUN_DIAG_NUMA1=1 or the drain guard). */
/* C0.7: committed-DATA-frame snapshot, for the ordered completeness
 * certificate.
 *
 * Deliberately a SEPARATE entry point rather than a 7th element of
 * fr_py_diag_node: existing callers allocate exactly six, so enlarging
 * that array would overrun their buffers.
 *
 * *out = committed DATA frames for `node`; returns 0 ok, -1 bad node or
 * no engine state.
 *
 * CALLER MUST HAVE PRODUCER QUIESCENCE. This returns a relaxed load,
 * which is the right pairing for the writers' relaxed fetch_add, but no
 * memory ordering can substitute for the lifecycle guarantee: a worker
 * that has not yet reached its commit point will contribute nothing, and
 * that is indistinguishable from a worker that committed nothing. Read
 * it after the reactor has joined workers, before teardown.
 *
 * This is not the generic "complete frame" statistic, which includes
 * non-DATA dispositions the parent framer filters. */
/* W-EXP-2 Phase A: is the committed-frame counter LIVE for this process?
 *
 * Exists because "zero frames were committed" and "counting is switched
 * off" are otherwise indistinguishable from outside, and the difference
 * decides whether a certificate means anything. With counting disabled by
 * FORKRUN_C07_COUNT=0 the counter never increments, so a launcher that
 * read it without asking would see 0 while real DATA frames existed -- and
 * a certificate comparing that against collected records would fail every
 * COMPLETE run. The caller must treat a disabled counter as "no verdict",
 * never as zero.
 */
int fr_py_c07_counting_enabled(void) { return fr_c07_enabled(); }

int fr_py_committed_data_frames(int node, uint64_t *out) {
    if (!out || !state || node < 0 || node >= (int)global_num_nodes)
        return -1;
    *out = __atomic_load_n(&state[node].committed_data_frames,
                           __ATOMIC_RELAXED);
    return 0;
}

int fr_py_diag_node(int node, uint64_t *out) {
    if (!out || !state || !g_state || node < 0 ||
        node >= (int)global_num_nodes)
        return -1;
    out[0] = __atomic_load_n(&state[node].write_idx, __ATOMIC_ACQUIRE);
    out[1] = __atomic_load_n(&state[node].read_idx, __ATOMIC_ACQUIRE);
    out[2] = __atomic_load_n(&state[node].scanner_finished,
                             __ATOMIC_ACQUIRE);
    out[3] = __atomic_load_n(&state[node].chunk_queue_head,
                             __ATOMIC_RELAXED);
    out[4] = __atomic_load_n(&state[node].chunk_queue_tail,
                             __ATOMIC_RELAXED);
    /* out[5]: tail-emptiness for the F-NUMA1 drain guard. 1 when every
     * slot in [read_idx, write_idx) is empty (lines==0 and end==off —
     * the EOF sentinel / zero-length tail the claim loop ack-silents
     * and the fork gate never counts in data_ready). 0 when any slot
     * carries payload bytes. A node whose only unclaimed work is an
     * empty tail lost nothing: small-scale nodes that receive no DATA
     * (sentinel-only) never fork workers (helpers-done exits before
     * the stall fallback) with complete output. The guard treats
     * tail_all_empty as vacuous, never a violation. Bounded scan:
     * the range cannot exceed the ring shield (RING_SIZE/2) plus the
     * in-flight publish window; abort-open (0) on absurd ranges. */
    {
        uint64_t r = out[1], w = out[0];
        int all_empty = 1;
        if (w < r || w - r > (RING_SIZE / 2 + 1024))
            all_empty = 0;
        else {
            uint64_t i;
            for (i = r; i < w; i++) {
                uint64_t slot = i & RING_MASK;
                uint32_t lines = state[node].lines_ring[slot];
                uint64_t off = state[node].offset_ring[slot];
                uint64_t end = state[node].end_ring[slot];
                if (lines > 0 || end > off) {
                    all_empty = 0;
                    break;
                }
            }
        }
        out[5] = (uint64_t)all_empty;
    }
    return 0;
}

/* =====================================================================
 * W-PY21-A: C drain process — data/control path separation.
 *
 * Runs in a forked child (never in the reactor parent). Replaces the
 * Python parent's per-result drain work (select + signal unpack +
 * pread + parse) with a tight C loop: blocking 16-byte signal reads
 * ((wid, batch_idx), indices only — the W-PY6 signal contract),
 * pread of newly arrived bytes from that worker's output memfd
 * (pread, never read/lseek — the fd description is SHARED with the
 * writing worker), and append of those bytes VERBATIM to the results
 * destination. Framing is untouched (keyed [idx][len][bytes] records
 * pass through opaquely), so the parent parses exactly as before —
 * only the byte movement moved into C.
 *
 * Per-worker offsets are monotonic append cursors: a respawned wid
 * reuses the same memfd and only appends, so generation changes
 * need no handling. A worker that dies mid-record leaves a short
 * tail the parent drops at parse (same rule as the Python drain).
 *
 * Two destinations selected by drain_mode:
 *   0 = results memfd (map/run: parent reads once at end).
 *   1 = pipe write end (stream: parent reads incrementally; a full
 *       pipe blocks the drain → workers block on signal write →
 *       claims stop — the hydraulic backpressure loop extended
 *       through the drain).
 *
 * Returns 0 drained-to-EOF, 1 bad arguments/allocation failure,
 * 2 signal-pipe read error, 3 short signal (framing), 4 results
 * write failure, 5 EPIPE on the results pipe (parent abandoned the
 * stream — the child exits; the parent reaps it in teardown).
 * ===================================================================== */

static ssize_t fr_py_read_full(int fd, void *buf, size_t count) {
    char *p = (char *)buf;
    size_t left = count;
    while (left > 0) {
        ssize_t n = read(fd, p, left);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        if (n == 0)
            return (ssize_t)(count - left); /* EOF: partial count */
        p += n;
        left -= (size_t)n;
    }
    return (ssize_t)count;
}

static int fr_py_write_full(int fd, const void *buf, size_t count) {
    const char *p = (const char *)buf;
    size_t left = count;
    while (left > 0) {
        ssize_t n = write(fd, p, left);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            return -1; /* caller maps EPIPE vs other errno */
        }
        if (n == 0)
            return -1;
        p += n;
        left -= (size_t)n;
    }
    return 0;
}

int fr_py_drain_loop(int signal_r, const int *out_fds, int num_workers,
                     int results_fd, int drain_mode) {
    uint64_t *offsets;
    int rc = 0;
    unsigned punch_streak = 0;

    if (signal_r < 0 || !out_fds || num_workers <= 0 ||
        num_workers > 4096 || results_fd < 0 ||
        (drain_mode != 0 && drain_mode != 1))
        return 1;
    offsets = (uint64_t *)calloc((size_t)num_workers, sizeof(uint64_t));
    if (!offsets)
        return 1;

    while (1) {
        uint64_t sig[2];
        ssize_t n;
        uint64_t wid;
        uint64_t frontier;
        struct stat st;
        uint64_t size, offset;
        char buf[65536];

        /* 1. Notification (blocking): (worker, committed frontier). The
         * frontier is the exclusive upper bound this worker has committed
         * output to; it is NOT a record count and makes no claim that the
         * memfd holds nothing beyond it. */
        n = fr_py_read_full(signal_r, sig, sizeof(sig));
        if (n == 0)
            break; /* EOF: every write end closed — drained */
        if (n < 0) {
            rc = 2;
            break;
        }
        if (n != (ssize_t)sizeof(sig)) {
            rc = 3; /* short signal: never from a 16B atomic write */
            break;
        }
        wid = sig[0];
        if (wid >= (uint64_t)num_workers)
            continue; /* defensive: our own workers never send this */

        /* STAGE0: sig[1] is the COMMITTED FRONTIER -- an absolute offset
         * into this worker's output memfd -- not a batch index. Forward
         * at most that far.
         *
         * The old code ignored sig[1] and forwarded to the memfd's
         * current SIZE. That is what let an uncommitted record be
         * published: bytes written before a batch's ack were in the
         * memfd, so any wakeup for that worker forwarded them, and the
         * rollback could not retract what had already been copied out and
         * punched.
         *
         * Offsets are monotonic for the life of the memfd, which is
         * reused across worker generations, so the cursor is deliberately
         * NOT reset on respawn. */
        frontier = sig[1];

        /* 2. Newly COMMITTED bytes in this worker's memfd. */
        if (fstat(out_fds[wid], &st) != 0)
            continue; /* memfd went away: nothing to move, keep going */
        size = (uint64_t)st.st_size;
        offset = offsets[wid];
        if (frontier <= offset) {
            /* Awake and processing, but nothing committed to move. The
             * handshake still fires: proving the drain SAW this wakeup
             * and declined to forward is exactly what makes the safety
             * test non-vacuous. */
            fr_drain_test_ack(wid, offset);
            continue;
        }
        if (frontier > size)
            frontier = size; /* clamp: never read past the memfd */
        if (frontier <= offset)
            continue;
        /* The record loop below is bounded by `size`; retarget it at the
         * committed frontier so every bound check downstream inherits the
         * commit guarantee rather than the raw memfd size. */
        size = frontier;

        /* 3. Move whole RECORDS, never a partial one.
         *
         * W-STREAMDRAIN. This used to copy the raw byte range
         * [offset, size) verbatim. That is wrong: `size` is a snapshot
         * of a memfd a worker is still appending to, so the range can
         * end mid-record. This drain CONCATENATES every worker's bytes
         * into one results stream, so a partial record from worker A
         * followed by worker B's bytes is unrecoverable -- the single
         * shared parser reads B's header as A's payload continuation,
         * desyncs permanently, and strands the remainder as an
         * unparseable tail. Measured: drain copied 19402 bytes, the
         * consumer parsed 20 records and discarded a 7328-byte tail,
         * silently returning ~40% of the output short.
         *
         * So: read the 16-byte record header, and copy the record only
         * once all 16 + len bytes are present. A partial trailing
         * record is left for the next signal, when the worker has
         * finished writing it. This mirrors what the Python drain
         * already does per worker (per_worker[wid] = [offset, tail]).
         *
         * Bounded 64KB chunks keep this loop's own RSS flat no matter
         * how far behind it gets. */
        while (size - offset >= sizeof(struct fr_py_record_hdr)) {
            struct fr_py_record_hdr hdr;
            uint64_t need, done;
            ssize_t h = pread(out_fds[wid], &hdr, sizeof(hdr),
                              (off_t)offset);
            if (h != (ssize_t)sizeof(hdr))
                break; /* transient; next signal re-drives us */
            /* A corrupt/garbage length must not spin us forever or ask
             * for an absurd allocation; treat as end-of-records for
             * this worker rather than trusting it. */
            if (hdr.len > ((uint64_t)1 << 40)) {
                /* A garbage length used to `break` out of this loop with
                 * offset unmoved, so every later signal re-read the same
                 * impossible header and broke again: the worker was
                 * stranded silently and the drain still returned rc=0, so
                 * the caller could not tell output had been dropped. Fail
                 * the drain instead. */
                rc = 4;
                goto drain_done;
            }
            need = sizeof(hdr) + hdr.len;
            if (size - offset < need)
                break; /* partial trailing record: wait for the rest */
            for (done = 0; done < need;) {
                size_t want = (need - done) > sizeof(buf)
                                  ? sizeof(buf) : (size_t)(need - done);
                ssize_t r = pread(out_fds[wid], buf, want,
                                  (off_t)(offset + done));
                if (r < 0) {
                    if (errno == EINTR)
                        continue;
                    /* Once bytes of THIS record are in results_fd the
                     * stream is committed: a partial record must never be
                     * followed by another worker's bytes, because the
                     * single shared parser would read the next header as
                     * payload and desync permanently. Abandoning here
                     * with offset unmoved was worse than it looked -- the
                     * chunk we already copied and PUNCHED is gone from
                     * out_fds[wid], so re-reading the header on the next
                     * signal returned zeros, and the record was then
                     * re-emitted as a zero-length one. Fail loudly. */
                    rc = 4;
                    goto drain_done;
                }
                if (r == 0) {
                    /* Same reasoning: we are mid-record with bytes
                     * already emitted. There is no per-worker tail buffer
                     * on this path to complete it -- that is the whole
                     * reason this function only ever emits whole records
                     * -- so advancing offset here would resume the next
                     * signal in the middle of a record. */
                    rc = 4;
                    goto drain_done;
                }
                if (fr_py_write_full(results_fd, buf, (size_t)r) != 0) {
                    if (drain_mode == 1 && errno == EPIPE)
                        rc = 5; /* abandoned stream: parent went away */
                    else
                        rc = 4;
                    goto drain_done;
                }
                done += (uint64_t)r;
                /* W-DRAINHOLE: bash's ring_order punches a hole in the
                 * per-worker OUTPUT memfd once it has moved a chunk out
                 * (the same fallocate the ingress path uses). Python had
                 * the per-worker output memfds and the moving cursor but
                 * not the punch, so those pages stayed in the working set
                 * and the kernel had to discover they were dead -- 64KB
                 * preads were measuring ~15ms each, which is reclaim cost
                 * and not I/O. Explicit holes remove them from the working
                 * set instead.
                 *
                 * Safe here PRECISELY because this loop COPIES into
                 * results_fd: the consumer holds bytes from a pipe, never a
                 * reference into out_fds[wid], so nothing can be looking at
                 * the range we are about to free. If this loop ever hands
                 * out mappings instead of copying, this punch becomes
                 * use-after-free and MUST go -- same class as the
                 * splice/SPLICE_F_MOVE lock inversion noted above, so read
                 * that post-mortem before changing either side.
                 *
                 * fallocate_punch_checked warns once per failure streak and
                 * never advances past a range it could not free. */
                (void)fallocate_punch_checked(
                    out_fds[wid], (off_t)(offset + done - (uint64_t)r),
                    (off_t)r, &punch_streak, "drain-output-memfd");
            }
            offset += need;
        }
        /* Save this worker's cursor. This used to be the `worker_done`
         * label, which the three mid-record failure paths above used to
         * jump to; they now fail the drain instead, so nothing branches
         * here any more and the label only drew -Wunused-label. */
        offsets[wid] = offset;
        fr_drain_test_ack(wid, offset);
    }

drain_done:
    free(offsets);
    return rc;
}

/* =====================================================================
 * W-PY21-B: frontend datapath consolidation — batch commit primitive,
 * C-level sequential spill, and C-level descriptor parsing. Engine
 * frozen: these only ADD new fr_py_* entry points. fr_py_ack_core is
 * a verbatim port of ring_ack_main's body with direct int parameters
 * (no argc/argv, no snprintf, no atoi); behavior is identical,
 * including the worker_last_cnt == 0 bash-env fallback branch.
 * fr_py_complete composes fr_py_emit + fr_py_ack_direct (no logic
 * duplicated). fr_py_spill_sequential covers the non-seekable
 * sources copy_file_range cannot. fr_py_parse_descriptors produces
 * a descriptor table (Python still materializes result objects).
 * ===================================================================== */

/* Shared ack core: fallow packet + order packet + worker_last_cnt
 * reset, with SIGPIPE shielding. Returns EXECUTION_SUCCESS (0) or
 * EXECUTION_FAILURE (1) — same codes as ring_ack_main. */
static int fr_py_ack_core(int fallow_fd, int target_fd) {
    struct sigaction sa_ign, sa_old;
    struct OrderPacket op = {0};
    struct SharedState *local_state;
    uint64_t my_idx;

    if (!state || !g_state)
        return EXECUTION_FAILURE;
    /* W-PY30: batch execution is over — disarm a final-attempt
     * coredump (no-op unless armed). */
    worker_coredump_disarm();
    /* W-PY29: CLAIMED → COMMITTING before any ack side effect
     * (fallow/order packets) goes out — pairs with worker_txn_clear
     * below. Defensive: no-ops when no transaction is active. */
    worker_txn_begin_commit(g_fr_config.ring_wid);
    /* W-PY29 adversarial test hook: FORKRUN_TEST_DIE_AT_COMMIT=1 makes
     * the worker SIGKILL itself inside the ack→clear window
     * (deterministic race injection). Inert unless set; read fresh
     * per ack (see DIE_AT_CLAIM note on fork inheritance).
     *
     * It fires on EVERY ack, which is correct for a race-window probe
     * but unusable under launcher supervision: every worker would die
     * on its first ack forever, and the run would exhaust the respawn
     * cap before anything completed. A counted variant was tried and
     * removed -- see P1-3 section 14 for why the launcher-level
     * exactly-once test is still open. */
    if (getenv("FORKRUN_TEST_DIE_AT_COMMIT") != NULL)
        raise(SIGKILL);
    sa_ign.sa_handler = SIG_IGN;
    sigemptyset(&sa_ign.sa_mask);
    sa_ign.sa_flags = 0;
    sigaction(SIGPIPE, &sa_ign, &sa_old);

    local_state = (my_numa_node != -1 &&
                   my_numa_node < (int)global_num_nodes)
                      ? &state[my_numa_node]
                      : &state[0];

    if (worker_last_cnt > 0) {
        my_idx = worker_last_idx;
        if (local_state && local_state->numa_enabled) {
            op.major_idx = worker_last_major;
            op.minor_idx = worker_last_minor;
            op.cnt = worker_last_cnt;
        } else {
            op.major_idx = worker_last_idx;
            op.minor_idx = 0;
            op.cnt = worker_last_cnt;
        }
    } else {
        const char *s_slots = get_string_value("RING_BATCH_SLOTS");
        const char *s_batch_idx = get_string_value("RING_BATCH_IDX");
        if (!s_slots || !s_batch_idx) {
            sigaction(SIGPIPE, &sa_old, NULL);
            return EXECUTION_FAILURE;
        }
        op.cnt = (uint32_t)atoi(s_slots);
        if (local_state && local_state->numa_enabled) {
            const char *s_maj = get_string_value("RING_MAJOR");
            const char *s_min = get_string_value("RING_MINOR");
            if (!s_maj || !s_min) {
                sigaction(SIGPIPE, &sa_old, NULL);
                return EXECUTION_FAILURE;
            }
            op.major_idx = (uint64_t)strtoull(s_maj, NULL, 10);
            op.minor_idx = (uint32_t)atoi(s_min);
            my_idx = (uint64_t)atoll(s_batch_idx);
        } else {
            op.major_idx = (uint64_t)strtoull(s_batch_idx, NULL, 10);
            op.minor_idx = 0;
            my_idx = op.major_idx;
        }
    }

    if (fallow_fd > 0) {
        if (local_state && local_state->numa_enabled) {
            uint64_t start =
                local_state->offset_ring[my_idx & RING_MASK];
            uint64_t end =
                local_state->end_ring[(my_idx + op.cnt - 1) & RING_MASK];
            struct PhysPacket pp = {.off = start, .len = end - start};
            if (robust_pipe_write(fallow_fd, &pp, sizeof(pp)) < 0) {
                pull_fire_alarm_reason(2);
                sigaction(SIGPIPE, &sa_old, NULL);
                return EXECUTION_FAILURE;
            }
        } else {
            struct IndexPacket ip = {.idx = op.major_idx, .cnt = op.cnt};
            if (robust_pipe_write(fallow_fd, &ip, sizeof(ip)) < 0) {
                pull_fire_alarm_reason(2);
                sigaction(SIGPIPE, &sa_old, NULL);
                return EXECUTION_FAILURE;
            }
        }
    }

    {
        uint64_t in_start = local_state->offset_ring[my_idx & RING_MASK];
        uint64_t in_end =
            local_state->end_ring[(my_idx + op.cnt - 1) & RING_MASK];
        op.in_off = in_start;
        op.in_len = in_end - in_start;
    }

    if (target_fd > 0) {
        if (target_fd != ack_cached_target_fd) {
            ack_cached_target_fd = target_fd;
            /* W-REL5-D (D2 twin): reset the offset with the mode (see
             * forkrun_ring.c) -- otherwise a cross-file curr can wrap
             * the sendfile length. Coherent with fr_py_ack_init
             * adopting the trio: a proper init-sync never trips this. */
            last_ack_offset = 0;
            struct stat st;
            ack_cached_mode =
                (fstat(target_fd, &st) == 0 && S_ISREG(st.st_mode)) ? 1 : 2;
        }
        if (ack_cached_mode == 1) {
            if (ack_cached_order_pipe < 0) {
                if (g_fr_config.fd_order_pipe >= 0)
                    ack_cached_order_pipe = g_fr_config.fd_order_pipe;
            }
            if (ack_cached_order_pipe < 0) {
                builtin_error(
                    "forkrun: FD_ORDER_PIPE unset during ordered ack");
                pull_fire_alarm_reason(2);
                sigaction(SIGPIPE, &sa_old, NULL);
                return EXECUTION_FAILURE;
            }
            if (ack_cached_order_pipe >= 0) {
                int fd_pipe = ack_cached_order_pipe;
                off_t curr = lseek(target_fd, 0, SEEK_CUR);
                if (curr == (off_t)-1) {
                    sigaction(SIGPIPE, &sa_old, NULL);
                    return EXECUTION_FAILURE;
                }
                op.fd = target_fd;
                op.off = (uint64_t)last_ack_offset;
                op.len = (uint64_t)(curr - last_ack_offset);
                if (robust_pipe_write(fd_pipe, &op, sizeof(op)) < 0) {
                    pull_fire_alarm_reason(2);
                    sigaction(SIGPIPE, &sa_old, NULL);
                    return EXECUTION_FAILURE;
                }
                last_ack_offset = curr;
                /* W-PY29: reuse curr for the rollback frontier (zero
                 * new syscalls). Self-healing: corrects any drift
                 * between emit-time advances and the live end. */
                worker_output_end = curr;
            }
        } else {
            if (robust_pipe_write(target_fd, &op, sizeof(op)) < 0) {
                pull_fire_alarm_reason(2);
                sigaction(SIGPIPE, &sa_old, NULL);
                return EXECUTION_FAILURE;
            }
        }
    }

    worker_last_cnt = 0;

    /* C0.7: COMMIT-SCOPED FLUSH. Transfer the pending DATA count into the
     * shared per-node total HERE, and the placement is load-bearing.
     *
     * Every acknowledgement side effect above has already succeeded
     * (the fallow packet and any order packet are on their pipes), so a
     * failure before this point returns without the batch being
     * committed and without the count moving.
     *
     * It must be BEFORE worker_txn_clear(), which is the store that
     * publishes TXN_IDLE. A worker that dies in the gap leaves an
     * ambiguous commit -- output written, count moved, TXN_IDLE not
     * published. The engine fails such a run rather than recovering it,
     * which is the correct outcome: a run accepted as successful must
     * never hold committed output whose count is missing.
     *
     * Flushing AFTER the TXN_IDLE store would invert that: a death in
     * the gap would leave committed output that is never counted, and
     * the certificate would report a clean run having lost a frame --
     * precisely the silent false success this counter exists to prevent.
     *
     * __atomic_fetch_add, not a store: several workers share a node's
     * cache line, so a plain store would lose updates. */
    if (fr_py_txn_pending_data && fr_c07_enabled()) {
        uint32_t _sn = g_fr_config.ring_node_id < 0
                           ? UINT32_MAX
                           : (uint32_t)g_fr_config.ring_node_id;
        if (_sn < global_num_nodes) {
            __atomic_fetch_add(&state[_sn].committed_data_frames,
                               fr_py_txn_pending_data, __ATOMIC_RELAXED);
        }
        fr_py_txn_pending_data = 0;
    }

    /* W-PY29: COMMITTING → IDLE (pairs with the begin_commit above).
     * Runs after every ack side effect is on its pipe, so TXN_IDLE
     * means fully committed. */
    worker_txn_clear(g_fr_config.ring_wid);

    sigaction(SIGPIPE, &sa_old, NULL);
    return EXECUTION_SUCCESS;
}

/* W-PY21-B.a: direct ack — identical to fr_py_ack (ring_ack_main)
 * minus the snprintf/argv/atoi round-trip. Saves ~150ns per batch
 * (measured, no-state short-circuit). */
int fr_py_ack_direct(int fallow_fd, int target_fd) {
    return fr_py_ack_core(fallow_fd, target_fd);
}

/* W-PY21-B.b: batch commit primitive — a thin composition of two
 * already-tested primitives (NOT a duplication of their logic):
 *   fr_py_emit (output writev + 16B signal) + fr_py_ack_direct
 *   (fallow packet + order packet + worker_last_cnt reset).
 *
 * Ordering invariants (identical to the old emit-then-ack path):
 *   1. output (header + data) to out_fd      [fr_py_emit]
 *   2. signal (wid + batch_idx) to signal_fd [fr_py_emit]
 *   3. fallow packet + 4. order packet + 5. worker_last_cnt reset
 *      [fr_py_ack_direct]
 *
 * The ack TARGET is derived exactly like the worker's old order_tgt:
 * target = out_fd when ordered (g_fr_config.fd_order_pipe >= 0, set
 * at worker init via fr_py_set_order_pipe), else -1 (disarm). There
 * is deliberately NO order-fd parameter — the order pipe lives in
 * the worker config, and the output memfd names the OrderPacket's
 * (fd, off, len), same as fr_py_ack(fallow_w, out_fd) always did.
 *
 * Output semantics are fr_py_emit's exactly (data == NULL or
 * out_fd < 0 means no output). The caller flushes Python-level
 * buffered streams BEFORE this call (flush-before-ack invariant);
 * C stdio is covered by fr_py_emit's path (fflush at the call
 * sites that redirect fd 1).
 *
 * Returns fr_py_emit's code (0 ok, -1 output failure, -2 signal
 * failure: EPIPE = parent abandoned the stream -> fatal, v0
 * parity) or -3 on ack failure. On output/signal failure the ack
 * is skipped (failure rides escrow, never ack — v0 parity).
 */
int fr_py_complete(int signal_fd, uint64_t wid, uint64_t batch_idx,
                   int fallow_fd, int out_fd,
                   const char *data, uint64_t data_len) {
    int rc;
    int target;

    rc = fr_py_emit(out_fd, signal_fd, wid, batch_idx, data, data_len);
    if (rc != 0)
        return rc;
    target = (g_fr_config.fd_order_pipe >= 0 && out_fd >= 0) ? out_fd : -1;
    if (fr_py_ack_direct(fallow_fd, target) != EXECUTION_SUCCESS)
        return -3;

    /* STAGE0: notify AFTER the commit.
     *
     * fr_py_ack_direct returns only after worker_txn_clear() has stored
     * TXN_IDLE, and every fallow/order packet is already on its pipe at
     * that point. That store -- not this function's return -- is the
     * commit linearization point: a worker can die between the store and
     * the return, and that batch IS committed.
     *
     * Publication therefore happens strictly after commit, so a record
     * the drain forwards always belongs to a transaction the engine
     * kept. */
    fr_py_maybe_die_before_notify(signal_fd, out_fd, (int)wid);
    return fr_py_notify_committed(signal_fd, out_fd, wid);
    return 0;
}

/* W-PY21-B.d: C sequential copy for non-seekable sources.
 *
 * For pipes and sockets copy_file_range may not work (the existing
 * fr_py_copy_range covers seekable sources and the parent tries it
 * first). This is the fallback: C read -> C write instead of
 * Python os.read -> Python os.write per chunk. Bytes are identical;
 * only the per-chunk interpreter overhead moves into C.
 * max_bytes == 0 means no limit. Returns bytes copied, or -1
 * (errno preserved) on read/write failure. */
int64_t fr_py_spill_sequential(int src_fd, int dst_fd,
                               uint64_t max_bytes) {
    char buf[65536];
    uint64_t total = 0;

    if (src_fd < 0 || dst_fd < 0)
        return -1;
    while (max_bytes == 0 || total < max_bytes) {
        size_t to_read = sizeof(buf);
        ssize_t r;

        if (max_bytes != 0 && max_bytes - total < to_read)
            to_read = (size_t)(max_bytes - total);
        r = read(src_fd, buf, to_read);
        if (r < 0) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        if (r == 0)
            break; /* EOF */
        {
            size_t written = 0;
            while (written < (size_t)r) {
                ssize_t w = write(dst_fd, buf + written,
                                  (size_t)r - written);
                if (w < 0) {
                    if (errno == EINTR)
                        continue;
                    if (errno == EAGAIN || errno == EWOULDBLOCK) {
                        struct pollfd pfd;
                        pfd.fd = dst_fd;
                        pfd.events = POLLOUT;
                        poll(&pfd, 1, -1);
                        continue;
                    }
                    return -1;
                }
                written += (size_t)w;
            }
        }
        total += (uint64_t)r;
    }
    return (int64_t)total;
}

/* W-PY21-B.e: C-level record parsing -> descriptor table.
 *
 * Input framing (v0 emitter, shared with run.py:_HDR "<QQ"):
 *   [batch_idx u64 LE][len u64 LE][len data bytes] x N.
 * A short header or short body ends the parse (a worker that died
 * mid-record leaves a truncated tail — dropped by the caller, the
 * same rule as _parse_records).
 *
 * This produces a descriptor table, NOT Python objects: C parses
 * the framing (unpack + bounds checks + offset arithmetic per
 * record), and the Python parent materializes result objects by
 * slicing input[off:off+len] from the known boundaries. The input
 * buffer is NOT copied — descriptors reference into it.
 *
 * Returns the number of descriptors written, or -1 on bad
 * arguments. Stops at max_descriptors (the caller grows the array
 * and retries — records are >= 16 bytes, so len/16 always bounds
 * the count and the retry terminates).
 */
struct fr_py_record_desc {
    uint64_t batch_idx;
    uint64_t offset; /* byte offset of the data in the input buffer */
    uint64_t length; /* length of the data */
};

int64_t fr_py_parse_descriptors(const char *input, uint64_t input_len,
                                struct fr_py_record_desc *descriptors,
                                uint64_t max_descriptors) {
    uint64_t off = 0;
    uint64_t count = 0;

    if (!input && input_len > 0)
        return -1;
    if (!descriptors && max_descriptors > 0)
        return -1;
    /* W-REL5-D (D5): off/data_len are framing-controlled u64s -- `off +
     * data_len > input_len` wraps on huge data_len and skips the
     * truncation break (bogus giant descriptor -> caller-side OOB).
     * Subtraction form cannot wrap (off <= input_len is the loop
     * invariant: 0 at entry, off+HDR+data_len <= input_len preserved).
     *
     * DECISION-02: the stride is now sizeof(struct fr_py_record_hdr) (24),
     * not 16 -- the header carries an explicit disposition. The
     * disposition is deliberately NOT surfaced in the descriptor array:
     * it carries batch_idx/offset/length for slicing, and adding a field
     * there would change a second ABI for no gain. Control dispositions
     * are SKIPPED below rather than surfaced, which keeps this path
     * result-for-result identical to the Python splitter. */
    while (count < max_descriptors && off <= input_len &&
           input_len - off >= (uint64_t)sizeof(struct fr_py_record_hdr)) {
        uint64_t batch_idx, data_len;
        /* uint32_t, NOT uint64_t: the memcpy below fills 4 bytes, so a
         * wider variable leaves the top half UNINITIALIZED. That garbage
         * then compares unequal to FR_DISP_DATA and silently skips every
         * record -- which is what it did: the C fast path returned zero
         * descriptors for every input, and because the garbage came from
         * the stack it even looked nondeterministic (a large zeroed
         * buffer happened to make it work). */
        uint32_t disposition;

        memcpy(&batch_idx, input + off, 8);
        memcpy(&data_len, input + off + 8, 8);
        memcpy(&disposition, input + off + 16, 4);
        off += (uint64_t)sizeof(struct fr_py_record_hdr);
        if (data_len > input_len - off)
            break; /* truncated record — stop here */
        /* DECISION-02: skip control dispositions, exactly as the Python
         * splitter does. Without this the C fast path returns MORE
         * records than _split_records for the same blob, so map() would
         * yield a spurious b"" for a UDF that returned None — and only
         * when FORKRUN_C_PARSE=1, i.e. a divergence no default test
         * would catch. The descriptor array still needs no new field. */
        if (disposition != (uint32_t)FR_DISP_DATA) {
            off += data_len;
            continue;
        }
        descriptors[count].batch_idx = batch_idx;
        descriptors[count].offset = off;
        descriptors[count].length = data_len;
        count++;
        off += data_len;
    }
    return (int64_t)count;
}

/* =====================================================================
 * W-PY22: engine-committed output recovery — structured resume
 * snapshot without stdout redirection. Engine frozen: these only ADD
 * new fr_py_* entry points that read/write the existing resume
 * ledger (g_state resume_* fields, written by TRACK_COMPLETED_BATCH
 * in ring_order_main, read by the scanner's is_resume block and
 * ring_dump_resume_main). All coordinates are BYTES on the Universal
 * Coordinate Plane (horizon = contiguous committed input offset;
 * jagged = out-of-order committed intervals beyond it) — never
 * batch numbers.
 * ===================================================================== */

/* Caller-provided interval (layout-identical to the engine's struct
 * IntervalNode {uint64_t s; uint64_t e;} — 16 bytes, same order;
 * ctypes binds positionally, so field order is load-bearing). */
struct FrPyInterval {
    uint64_t start;
    uint64_t end;
};

/* Snapshot the engine's resume ledger via out-parameters.
 *
 * Takes the same seqlock-protected snapshot ring_dump_resume_main
 * takes internally. The reader protocol is copied EXACTLY:
 *   ACQUIRE seq1 -> RELAXED data -> fence(ACQUIRE) -> ACQUIRE seq2,
 *   retry while odd or mismatched.
 * The ACQUIRE fence before seq2 is LOAD-BEARING (closes window c:
 * without it seq2 may be satisfied before the data loads and a torn
 * snapshot is accepted — x86-TSO hides this; ARM does not). Do NOT
 * simplify or weaken any of these orderings.
 *
 * Caller provides the jagged array (avoids malloc ownership across
 * the ctypes boundary); max_jagged == 0 is a count query (no array
 * needed, *count_out receives the true ledger count). Otherwise
 * *count_out receives the actual interval count clamped to
 * max_jagged (caller grows the array and retries when clamped).
 * The horizon-0 fallow fallback mirrors ring_dump_resume_main
 * (bash-checkpoint interchangeability).
 *
 * Returns 0 ok, -1 engine not initialized, -2 bad out-pointers.
 */
int fr_py_resume_snapshot(uint64_t *horizon, uint64_t *stdout_bytes,
                          struct FrPyInterval *jagged,
                          uint32_t *count_out, uint32_t max_jagged) {
    uint32_t seq1, seq2;
    uint64_t snap_horizon, snap_bytes;
    uint32_t snap_count, n, i;
    struct IntervalNode snap_jagged[1024];

    if (!g_state)
        return -1;
    if (!horizon || !stdout_bytes || !count_out)
        return -2;
    if (max_jagged > 0 && !jagged)
        return -2;

    do {
        seq1 = __atomic_load_n(&g_state->resume_seq, __ATOMIC_ACQUIRE);
        snap_horizon = __atomic_load_n(&g_state->resume_horizon,
                                       __ATOMIC_RELAXED);
        snap_bytes = __atomic_load_n(&g_state->resume_stdout_bytes,
                                     __ATOMIC_RELAXED);
        snap_count = __atomic_load_n(&g_state->resume_jagged_count,
                                     __ATOMIC_RELAXED);
        if (snap_count > 1024)
            snap_count = 1024;
        for (i = 0; i < snap_count; i++) {
            snap_jagged[i].s = __atomic_load_n(
                &g_state->resume_jagged[i].s, __ATOMIC_RELAXED);
            snap_jagged[i].e = __atomic_load_n(
                &g_state->resume_jagged[i].e, __ATOMIC_RELAXED);
        }
        /* LoadLoad: pin the RELAXED data loads above this fence
         * (reader-pair window c). Load-bearing — do not delete. */
        __atomic_thread_fence(__ATOMIC_ACQUIRE);
        seq2 = __atomic_load_n(&g_state->resume_seq, __ATOMIC_ACQUIRE);
    } while (seq1 != seq2 || (seq1 & 1));

    if (snap_horizon == 0) {
        /* ring_dump_resume_main fallback for -u mode: the fallow
         * reaper's contiguous prefix when the orderer ledger has
         * nothing (a C-orderer path never lands here with real
         * progress, but bash-format checkpoints must round-trip). */
        uint64_t fh = __atomic_load_n(&g_state->fallow_horizon_bytes,
                                      __ATOMIC_RELAXED);
        if (fh > 0)
            snap_horizon = fh;
    }

    *horizon = snap_horizon;
    *stdout_bytes = snap_bytes;
    if (max_jagged == 0) {
        /* Count query (no array): report the true ledger count so
         * the caller can size one exact array. */
        *count_out = snap_count;
        return 0;
    }
    n = (snap_count < max_jagged) ? snap_count : max_jagged;
    for (i = 0; i < n; i++) {
        jagged[i].start = snap_jagged[i].s;
        jagged[i].end = snap_jagged[i].e;
    }
    *count_out = n;
    return 0;
}

/* Set resume state for a new run (call after fr_py_init, before the
 * scan/worker forks). The scanner suppresses already-committed byte
 * intervals; the C orderer bootstraps its tracker from this state
 * (multi-resume is cumulative, not delta). Plain stores + qsort —
 * identical to ring_set_resume_main minus the argv parsing (same
 * e > s filter, same cmp_interval order).
 *
 * Returns 0 ok, -1 engine not initialized, -2 count > 1024.
 */
int fr_py_set_resume_state(uint64_t horizon, uint64_t stdout_bytes,
                           const struct FrPyInterval *jagged,
                           uint32_t jagged_count) {
    uint32_t n = 0;
    uint32_t i;

    if (!g_state)
        return -1;
    if (jagged_count > 1024)
        return -2;
    if (jagged_count > 0 && !jagged)
        return -2;

    g_state->is_resume_mode = 1;
    g_state->resume_horizon = horizon;
    g_state->resume_stdout_bytes = stdout_bytes;
    for (i = 0; i < jagged_count; i++) {
        /* e > s filter (ring_set_resume_main parity — degenerate
         * intervals never enter the ledger). */
        if (jagged[i].end > jagged[i].start) {
            g_state->resume_jagged[n].s = jagged[i].start;
            g_state->resume_jagged[n].e = jagged[i].end;
            n++;
        }
    }
    g_state->resume_jagged_count = n;
    /* Scanner expects sorted (ring_set_resume_main parity). */
    qsort(g_state->resume_jagged, n, sizeof(struct IntervalNode),
          cmp_interval);
    return 0;
}

/* Resume-mode query (1 active, 0 otherwise, incl. no engine). */
int fr_py_is_resume_mode(void) {
    if (!g_state)
        return 0;
    return g_state->is_resume_mode ? 1 : 0;
}

/* =====================================================================
 * W-PY28: parent-side universal recovery — typed wrapper over the
 * engine core (no argv marshalling). The reactor calls this when ANY
 * worker dies for ANY reason; return codes are the core's 0..5
 * (RECOVERED / NO_BATCH / NORMAL_EXIT / ALREADY_DONE / RACE /
 * FATAL). The core is static to the shared TU, so this thin
 * non-static wrapper is what ctypes binds. Direct call, zero
 * marshalling overhead.
 * ===================================================================== */
int fr_py_recover_worker(int wid, int incarnation, int output_fd,
                         int exit_code) {
    /* W-PY31: a worker killed while WAITING issued no ticket.  Translate
     * the shim-only phase to IDLE before the frozen core sees it, so the
     * death is classified "no batch in flight" (respawn, or normal EOF)
     * instead of RACE_DETECTED.  The worker is reaped by the caller, so
     * no live worker can still be transitioning out of WAITING here. */
    if (g_state && wid >= 0 && wid < MAX_TXN_WORKERS) {
        uint32_t st = __atomic_load_n(&g_state->worker_txn[wid].state,
                                      __ATOMIC_ACQUIRE);
        if (st == TXN_WAITING)
            __atomic_store_n(&g_state->worker_txn[wid].state, TXN_IDLE,
                             __ATOMIC_RELEASE);
    }
    int rc = ring_recover_worker_core(wid, incarnation, output_fd,
                                      exit_code);

    /* Re-sync the worker's output cursor after a rollback.
     *
     * ring_recover_worker_core truncates output_fd back to
     * txn->output_start but does NOT move the TLS `worker_output_end`
     * cursor, which is what the NEXT claim snapshots as the new batch's
     * rollback frontier. After a truncation that cursor is stale: it
     * still holds the pre-truncation position, so the next batch's
     * output_start is larger than the real file size -- and the
     * engine's "never grow a file by truncating" guard
     * (st_size >= output_start) then REFUSES the next rollback.
     *
     * Consequence, measured: only the FIRST recovery in a worker
     * session actually rolled anything back. Every later one returned
     * RECOVERED while leaving its orphan in the stream, so a worker
     * that died twice produced DUPLICATE batch records -- and a
     * duplicate desynchronises every batch after it, which is worse
     * than losing one.
     *
     * This is a pre-existing defect, reproducible at HEAD (verified by
     * stashing: `git stash && make python-substrate` shows the same
     * [0,1,2,2,3,4,4,5] output). It is fixed here rather than in
     * ring_recover_worker_core because forkrun_ring.c is FROZEN and
     * _shim.c textually includes it, so this translation unit can see
     * the TLS cursor directly. The fix is a cursor resync, not a change
     * to the engine's state machine or its recovery decisions.
     *
     * Only on RECOVERED (rc 0): that is the branch that truncated. Any
     * other return means the engine declined to roll back, and moving
     * the cursor would then be a lie about where output ends. */
    if (rc == 0 && output_fd >= 0) {
        (void)worker_txn_init_output_cursor(output_fd);
        /* C0.7: the truncated frames are uncommitted, so their pending
         * count is discarded and never reaches the shared field. The
         * retry accumulates afresh and is added once at ITS commit.
         *
         * Scope, stated honestly: this runs in the SUPERVISING process,
         * so it clears this process's thread-local value -- it does not
         * and cannot reach into the dead worker's TLS, which is gone.
         * That is sufficient because the supervisor's pending count is
         * required to be zero: nothing emits here, so a value observed
         * now would be inherited by a future fork. The in-process
         * harness (same process emits, then recovers) therefore
         * exercises a different situation than a real worker death, and
         * the process-level test is the one that establishes the real
         * behaviour. */
        if (fr_c07_enabled())
            fr_py_txn_pending_data = 0;
    }
    return rc;
}

/* =====================================================================
 * W-PY26: C worker loop for plugin mode — zero Python per batch.
 *
 * The plugin equivalent of fr_py_worker_splice_loop: owns the ENTIRE
 * batch lifecycle in C (claim → plugin → signal → ack). No ctypes,
 * no GIL, no Python objects per batch. Matches bash's architecture
 * (C worker, C callback, C loop).
 *
 * Built ONLY on tested primitives (same doctrine as the splice
 * loop — deviations from the W-PY26 sketch, whose fixed_argv /
 * raw-funcptr / hand-rolled mmap bypass the frozen ABI):
 * - fr_py_claim (TLS publishing, poison detection + counting),
 * - fr_py_plugin_invoke (the exact ctx/capture/emit body
 *   fr_py_plugin_call uses — tokenized argv via do_tokenize, RAW
 *   window via ring_call_ensure_ingress_map, stdout capture into
 *   the reused memfd, framing via fr_py_emit_record),
 * - fr_py_complete (signal + fallow + order + ack in one call),
 * - fr_py_escrow_deposit (retry), fr_py_abort (fail-fast).
 *
 * Sketch deviations (deliberate, frozen-ABI-driven):
 * - (path, func_name) strings, NOT a raw function pointer: the
 *   child dlopens itself post-fork via fr_py_plugin_ensure (same
 *   fork-safety rule as _plugin.load_plugin — dlopen without
 *   calling is fork-safe; a parent-handle pointer would dangle on
 *   dlclose and entangle refcounts across fork).
 * - No fixed_argv: argv comes from do_tokenize inside the invoke
 *   helper, exactly like ring_call_main (fixed args would bypass
 *   batch delivery for non-RAW plugins).
 * - No hand-rolled ingress mmap: the invoke helper uses the
 *   engine's TLS-cached mapping (RAW) / pread fallback (fd_in).
 * - on_error is honored (0 retry / 1 skip / 2 fail-fast), mirroring
 *   _worker.py; the splice loop's retry-always rule does NOT apply
 *   here because plugin failures are payload errors.
 *
 * Params:
 *   wid/ingress_fd/out_fd/signal_fd/fallow_fd as in the splice loop.
 *   order_fd: order-pipe write end (-1 disarms; when >= 0 acks
 *     target out_fd so the C orderer gets contiguous packets).
 *   trap_ack_fd: poison "P:idx:kills" lines (-1 disarms).
 *   wincarn: respawn generation for fr_py_worker_init lineage.
 *   retry_limit: poison threshold (mirrors engine default 3).
 *   on_error: 0 retry (escrow) / 1 skip (ack) / 2 fail-fast (abort).
 *
 * Returns 0 drained-to-EOF, 1 claim/ack failure or fail-fast abort,
 * 2 signal failure (EPIPE = parent gone — fatal, v0 parity). The
 * Python child maps nonzero → worker exit 1 → parent RuntimeError.
 * Poisoned batches warn + notify + ack-silent (never escrowed);
 * zero-length sentinels ack-silent (M1 invariant, never executed).
 * ===================================================================== */
int fr_py_worker_plugin_loop(int wid, const char *path,
                             const char *func_name, int ingress_fd,
                             int out_fd, int signal_fd, int fallow_fd,
                             int order_fd, int trap_ack_fd, int wincarn,
                             int retry_limit, int on_error) {
    fr_py_batch_t claimed;
    int rc;

    if (!path || !func_name || ingress_fd < 0 || out_fd < 0)
        return 1;
    if (on_error < 0 || on_error > 2)
        return 1;
    if (fr_py_worker_init(wid, 0, wincarn, retry_limit, 0) != 0)
        return 1;
    if (order_fd >= 0)
        g_fr_config.fd_order_pipe = order_fd;
    /* W-PY28: name the output fd for transaction publication + sync
     * the ack offset (respawned generations append to a reused fd). */
    fr_py_txn_out_fd = out_fd;
    fr_py_ack_init(out_fd);
    if (fr_py_plugin_ensure(path, func_name) != 0)
        return 1;

    while (1) {
        rc = fr_py_claim(&claimed);
        if (rc == 2)
            return 0; /* EOF: drained */
        if (rc != 0)
            return 1; /* abort/failure */

        if (claimed.poisoned) {
            char pbuf[64];
            int plen;
            fprintf(stderr,
                    "forkrun [WARN]: Skipping poisoned batch %llu "
                    "(killed %u times).\n",
                    (unsigned long long)claimed.batch_idx,
                    claimed.num_kills);
            if (trap_ack_fd >= 0) {
                plen = snprintf(pbuf, sizeof(pbuf), "P:%llu:%u\n",
                                (unsigned long long)claimed.batch_idx,
                                claimed.num_kills);
                if (plen > 0)
                    (void)robust_pipe_write(trap_ack_fd, pbuf,
                                            (size_t)plen);
            }
            /* Ack-silent (no signal — v0 parity) but ordered: the
             * C orderer still expects its contiguous packet. */
            /* DECISION-02: terminal POISONED disposition, emitted
             * BEFORE the ack, so a death in between rolls it back
             * with the rest of the batch. */
            if (fr_py_emit_disposition(out_fd, signal_fd, (uint64_t)wid,
                                       claimed.batch_idx,
                                       FR_DISP_POISONED) != 0)
                return 1;
            /* STAGE0: notify AFTER the ack, with the real signal fd.
             * A POISONED/SKIPPED record is a real committed record, so
             * it must be announced; a silent ack would commit it and
             * tell nobody, stranding any ordered consumer waiting on
             * that batch's terminal outcome. The fallow/order ack
             * semantics are unchanged. */
            rc = fr_py_complete(signal_fd, (uint64_t)wid, claimed.batch_idx,
                                fallow_fd, out_fd, NULL, 0);
            if (rc != 0)
                return 1;
            continue;
        }

        if (claimed.length == 0) {
            /* EOF sentinel slot: ack but never emit (bash REPLY rule). */
            rc = fr_py_complete(-1, (uint64_t)wid, claimed.batch_idx,
                                fallow_fd, out_fd, NULL, 0);
            if (rc != 0)
                return 1;
            continue;
        }

        rc = fr_py_plugin_invoke(ingress_fd, out_fd, claimed.offset,
                                 claimed.length, claimed.batch_idx,
                                 claimed.lines, claimed.num_kills,
                                 wid, wincarn);
        if (rc == 0) {
            /* Success: record already framed by the invoke — signal
             * + fallow + order + ack in one call (no output: data
             * NULL skips the writev, signal still honored). */
            /* Fault injection (exactly-once tests): this batch's record IS
             * framed -- the invoke wrote it -- and the ack below has NOT
             * happened. That is the orphan window recovery must handle.
             *
             * Placed at the success site rather than inside
             * fr_py_complete because "success" cannot be identified by the
             * signal argument: the in-process map() executor runs the
             * signal pipe DISARMED (-1) on the success path as well, since
             * there is no drain there, so a signal_fd >= 0 gate fires
             * under the launcher but never for a plain map() call.
             * Structural placement also keeps the injected death out of
             * the poison/skip and sentinel branches, where firing meant a
             * poisoned batch could never be skipped. */
            fr_py_maybe_die_before_ack((int)wid, signal_fd);

            rc = fr_py_complete(signal_fd, (uint64_t)wid,
                                claimed.batch_idx, fallow_fd, out_fd,
                                NULL, 0);
            if (rc == 0)
                continue;
            if (rc == -2)
                return 2; /* signal EPIPE: parent gone — fatal */
            return 1; /* -1 output (unreachable: no output) / -3 ack */
        }

        /* --- failure path (bash -E analogue, _worker.py parity) --- */
        if (on_error == 1) {
            /* DECISION-02: terminal SKIPPED disposition. Emitted
             * before the ack, inside the transaction, so a death
             * in between rolls it back and the retry re-emits it. */
            if (fr_py_emit_disposition(out_fd, signal_fd, (uint64_t)wid,
                                      claimed.batch_idx,
                                      FR_DISP_SKIPPED) != 0)
                return 1;
            /* skip: ack-silent like poison (no signal — nothing emitted). */
            /* STAGE0: notify AFTER the ack, with the real signal fd.
             * A POISONED/SKIPPED record is a real committed record, so
             * it must be announced; a silent ack would commit it and
             * tell nobody, stranding any ordered consumer waiting on
             * that batch's terminal outcome. The fallow/order ack
             * semantics are unchanged. */
            rc = fr_py_complete(signal_fd, (uint64_t)wid, claimed.batch_idx,
                                fallow_fd, out_fd, NULL, 0);
            if (rc != 0)
                return 1;
            continue;
        }
        if (on_error == 2) {
            fflush(NULL);
            fr_py_abort();
            return 1;
        }
        /* Default retry: escrow with kills+1, no ack (the next claim
         * overwrites the armed TLS). Same-process retry on re-claim;
         * poison threshold converts loops into skips above. */
        fflush(NULL);
        fr_py_escrow_deposit(claimed.num_kills + 1);
        continue;
    }
}

/* Node-taking plugin loop (W-EXP-2 step C).
 *
 * The loop body is NOT duplicated: it lives in fr_py_worker_plugin_loop,
 * and this entry point runs it with the node bound first. The three
 * worker modes share one lifecycle (poison skip, zero-length sentinel,
 * the whole on_error ladder) and the parity test enforces that; a
 * fourth copy of the body would be a fourth place for a fix to miss.
 *
 * The node is applied by setting the ring node id BEFORE the loop's own
 * fr_py_worker_init call, which then reads it. node_id < 0 is refused:
 * the launcher's own validation already rejects a bad topology, and an
 * unbound worker would silently claim the wrong ring.
 *
 * 0 IS NOT INTERCHANGEABLE WITH -1 for the node: fr_py_worker_init maps
 * a node_id < 0 to ring_node_id = -1, and the C0.7 commit counter is
 * attributed BY ring_node_id, so with -1 it is skipped entirely and
 * every run reports ZERO committed DATA frames. */
int fr_py_worker_plugin_loop_numa(int wid, const char *path,
                                  const char *func_name, int ingress_fd,
                                  int out_fd, int signal_fd, int fallow_fd,
                                  int order_fd, int trap_ack_fd,
                                  int wincarn, int retry_limit,
                                  int on_error, int node_id) {
    if (node_id < 0)
        return 1;
    fr_py_worker_bind_node(node_id);
    int rc = fr_py_worker_plugin_loop(wid, path, func_name, ingress_fd,
                                      out_fd, signal_fd, fallow_fd,
                                      order_fd, trap_ack_fd, wincarn,
                                      retry_limit, on_error);
    fr_py_worker_bind_node(-1);
    return rc;
}


/* =====================================================================
 * P1-3: Python UDF worker loop (DECISION-01 Option A, external review
 * GO WITH AMENDMENTS).
 *
 * The FIFTH execution-mode loop. splice / plugin / spawn / fallow all
 * share one shape -- claim, poison/sentinel handling, invoke, then
 * fr_py_complete / fr_py_escrow_deposit / fr_py_abort -- and differ only
 * in the invoke body. A UDF is a fifth invoke body, not a plugin
 * variant: a plugin takes a tokenized argv and returns whatever it
 * wrote to stdout, a UDF takes one bytes object and returns bytes, None,
 * or an error. Forcing both through one interface would mean parameters
 * that are meaningless for one of them.
 *
 * SIGNATURE IS DELIBERATELY IDENTICAL to fr_py_worker_plugin_loop, with
 * `path`/`func_name` reinterpreted as `module`/`attr`. That keeps
 * spawn_wid() completely untouched: the launcher passes a different
 * function pointer and different strings. Twelve parameters is already
 * too many to grow.
 *
 * The interpreter is NOT initialised here. The launcher dlopens the
 * helper and calls fr_udf_init() BEFORE forking; workers inherit the
 * initialised interpreter (measured 6.8-11.3x faster than per-worker
 * init). The bound function pointers below are likewise inherited.
 * ===================================================================== */

/* Mirror of the helper's fr_udf.h entry points. Declared here rather
 * than included: the shim must NOT link libpython, and the helper is a
 * separate per-minor object loaded with dlopen. Only these three
 * symbols are needed; the rest of the API (flags, diagnostics, fork
 * hooks) is called by the launcher itself. */
/* Mirrors fr_udf.h's FR_UDF_* status codes. The shim deliberately does
 * NOT include fr_udf.h: including it would drag Python.h into a
 * translation unit that must never link libpython. These are the only
 * two values the loop branches on, and the test suite pins them against
 * the real header via the probe. */
enum { FR_UDF_OK = 0, FR_UDF_NO_RESULT = 1, FR_UDF_ERR = -1 };

typedef int (*fr_udf_call_fn)(const char *module, const char *attr,
                              const char *input, size_t len,
                              char **out, size_t *out_len);
typedef void (*fr_udf_free_fn)(char *buf);

static fr_udf_call_fn g_udf_call = NULL;
static fr_udf_free_fn  g_udf_free = NULL;

/* Bound by the launcher in main() before any fork. Returns 0 on
 * success. Must be called before the workers start; the pointers are
 * inherited by every worker. */
int fr_py_udf_bind(fr_udf_call_fn call_fn, fr_udf_free_fn free_fn)
{
    if (!call_fn || !free_fn)
        return -1;
    g_udf_call = call_fn;
    g_udf_free = free_fn;
    return 0;
}

/* ---- the UDF invoke body ----
 *
 * Read the claimed batch window, hand it to the UDF, frame whatever
 * comes back. Returns 0 on success (including a None result), non-zero
 * on failure so the caller's on_error policy applies.
 *
 * Return codes mirror fr_py_plugin_invoke so the loop treats them
 * identically: -1 bad fd, -2 helper not bound, -3 read/mapping failure,
 * -4 the UDF itself failed. */
static int fr_py_udf_invoke(int ingress_fd, int out_fd,
                            uint64_t batch_off, uint64_t batch_len,
                            uint64_t batch_idx,
                            const char *module, const char *attr)
{
    if (ingress_fd < 0 || out_fd < 0)
        return -1;
    if (!g_udf_call || !g_udf_free)
        return -2;
    if (!module || !attr)
        return -2;

    /* No static buffer: it would cap batch size. malloc per batch is
     * what the spawn loop already does with its capture staging. */
    char *in = NULL;
    if (batch_len > 0) {
        if (ring_call_ensure_ingress_map(ingress_fd, batch_off,
                                         (size_t)batch_len) != 0)
            return -3;
        const char *base = (const char *)tls_ingress_map + batch_off;
        in = (char *)malloc((size_t)batch_len);
        if (!in)
            return -3;
        memcpy(in, base, (size_t)batch_len);
    }

    char *out = NULL;
    size_t out_len = 0;
    int rc = g_udf_call(module, attr, in ? in : "", (size_t)batch_len,
                        &out, &out_len);
    free(in);
    if (rc < 0)
        return -4;              /* UDF raised / could not be resolved */

    /* DECISION-02: None and b"" are different answers and must stay so.
     * A None result emits a NO_RESULT record -- a terminal disposition
     * carrying no payload -- so the parent can advance past it. An empty
     * result emits a DATA record with len 0. Collapsing either into the
     * other is the bug this protocol exists to prevent.
     *
     * fr_py_emit_record infers NO_RESULT from src_len == 0, which is
     * why the None case is signalled by a zero-length READ that still
     * writes a disposition-bearing header: see fr_py_emit_record's
     * contract. */
    uint32_t disp = (rc == FR_UDF_NO_RESULT) ? FR_DISP_NO_RESULT
                                            : FR_DISP_DATA;
    int frc = fr_py_emit_record_buf(out_fd, batch_idx,
                                    rc == FR_UDF_NO_RESULT ? NULL : out,
                                    rc == FR_UDF_NO_RESULT ? 0 : out_len,
                                    disp);
    if (out)
        g_udf_free(out);

    return frc == 0 ? 0 : -3;
}

/* ---- the fifth worker loop ----
 *
 * Same lifecycle as the other modes, reusing the same primitives. No
 * separate retry, ack, or poison policy: that is the whole point of
 * keeping the shape identical, and it is what the parity tests hold us
 * to. */
int fr_py_worker_udf_loop(int wid, const char *module, const char *attr,
                          int ingress_fd, int out_fd, int signal_fd,
                          int fallow_fd, int order_fd, int trap_ack_fd,
                          int wincarn, int retry_limit, int on_error) {
    fr_py_batch_t claimed;
    int rc;

    if (!module || !attr || ingress_fd < 0 || out_fd < 0)
        return 1;
    if (on_error < 0 || on_error > 2)
        return 1;
    if (fr_py_worker_init(wid, 0, wincarn, retry_limit, 0) != 0)
        return 1;
    if (order_fd >= 0)
        g_fr_config.fd_order_pipe = order_fd;
    fr_py_txn_out_fd = out_fd;
    fr_py_ack_init(out_fd);

    while (1) {
        rc = fr_py_claim(&claimed);
        if (rc == 2)
            return 0; /* EOF: drained */
        if (rc != 0)
            return 1; /* abort/failure */

        if (claimed.poisoned) {
            char pbuf[64];
            int plen;
            fprintf(stderr,
                    "forkrun [WARN]: Skipping poisoned batch %llu "
                    "(killed %u times).\n",
                    (unsigned long long)claimed.batch_idx,
                    claimed.num_kills);
            if (trap_ack_fd >= 0) {
                plen = snprintf(pbuf, sizeof pbuf, "P:%llu:%u\n",
                                (unsigned long long)claimed.batch_idx,
                                claimed.num_kills);
                if (plen > 0)
                    (void)robust_pipe_write(trap_ack_fd, pbuf,
                                            (size_t)plen);
            }
            /* DECISION-02: terminal POISONED disposition, emitted
             * BEFORE the ack, so a death in between rolls it back
             * with the rest of the batch. */
            if (fr_py_emit_disposition(out_fd, signal_fd, (uint64_t)wid,
                                       claimed.batch_idx,
                                       FR_DISP_POISONED) != 0)
                return 1;
            /* STAGE0: notify AFTER the ack, with the real signal fd.
             * A POISONED/SKIPPED record is a real committed record, so
             * it must be announced; a silent ack would commit it and
             * tell nobody, stranding any ordered consumer waiting on
             * that batch's terminal outcome. The fallow/order ack
             * semantics are unchanged. */
            rc = fr_py_complete(signal_fd, (uint64_t)wid, claimed.batch_idx,
                                fallow_fd, out_fd, NULL, 0);
            if (rc != 0)
                return 1;
            continue;
        }

        if (claimed.length == 0) {
            /* EOF sentinel slot: ack but never emit (bash REPLY rule). */
            rc = fr_py_complete(-1, (uint64_t)wid, claimed.batch_idx,
                                fallow_fd, out_fd, NULL, 0);
            if (rc != 0)
                return 1;
            continue;
        }

        rc = fr_py_udf_invoke(ingress_fd, out_fd, claimed.offset,
                              claimed.length, claimed.batch_idx,
                              module, attr);
        if (rc == 0) {
            /* Fault injection (exactly-once tests): this batch's record IS
             * framed -- the invoke wrote it -- and the ack below has NOT
             * happened. That is the orphan window recovery must handle.
             *
             * Placed at the success site rather than inside
             * fr_py_complete because "success" cannot be identified by the
             * signal argument: the in-process map() executor runs the
             * signal pipe DISARMED (-1) on the success path as well, since
             * there is no drain there, so a signal_fd >= 0 gate fires
             * under the launcher but never for a plain map() call.
             * Structural placement also keeps the injected death out of
             * the poison/skip and sentinel branches, where firing meant a
             * poisoned batch could never be skipped. */
            fr_py_maybe_die_before_ack((int)wid, signal_fd);

            rc = fr_py_complete(signal_fd, (uint64_t)wid,
                                claimed.batch_idx, fallow_fd, out_fd,
                                NULL, 0);
            if (rc == 0)
                continue;
            if (rc == -2)
                return 2; /* signal EPIPE: parent gone -- fatal */
            return 1;
        }

        /* --- failure path: the existing on_error policy, unchanged --- */
        if (on_error == 1) {
            /* DECISION-02: terminal SKIPPED disposition. Emitted
             * before the ack, inside the transaction, so a death
             * in between rolls it back and the retry re-emits it. */
            if (fr_py_emit_disposition(out_fd, signal_fd, (uint64_t)wid,
                                      claimed.batch_idx,
                                      FR_DISP_SKIPPED) != 0)
                return 1;
            /* STAGE0: notify AFTER the ack, with the real signal fd.
             * A POISONED/SKIPPED record is a real committed record, so
             * it must be announced; a silent ack would commit it and
             * tell nobody, stranding any ordered consumer waiting on
             * that batch's terminal outcome. The fallow/order ack
             * semantics are unchanged. */
            rc = fr_py_complete(signal_fd, (uint64_t)wid, claimed.batch_idx,
                                fallow_fd, out_fd, NULL, 0);
            if (rc != 0)
                return 1;
            continue;
        }
        if (on_error == 2) {
            fflush(NULL);
            fr_py_abort();
            return 1;
        }
        fflush(NULL);
        fr_py_escrow_deposit(claimed.num_kills + 1);
        continue;
    }
}

/* =====================================================================
 * W-PY33: C worker loop for spawn mode — zero Python per batch.
 *
 * The spawn analogue of fr_py_worker_plugin_loop: owns the ENTIRE
 * batch lifecycle in C (claim → posix_spawnp → signal → ack). Built
 * only on tested primitives:
 * - fr_py_claim (TLS publishing, poison detection + counting),
 * - fr_py_exec_spawn (concurrent stdin/stdout pump, capture-memfd
 *   staging, framed emit — the exact body the Python worker loop
 *   calls per batch),
 * - fr_py_complete (signal + fallow + order + ack in one call),
 * - fr_py_escrow_deposit (retry), fr_py_abort (fail-fast).
 *
 * Sketch deviations (deliberate, frozen-ABI-driven):
 * - Output is CAPTURED then framed (fr_py_exec_spawn's capture
 *   memfd + fr_py_emit_record), NOT written direct-to-out_fd: the
 *   v0 emitter contract needs [idx][len] framing with the true
 *   length up front, which is unknowable until the child exits.
 *   Direct append would emit unparseable bytes (and the old
 *   placeholder-backfill race the capture design fixed). The
 *   deadlock the sketch fears does not exist here: stdout staging
 *   is a memfd (never blocks), and stdin/stdout pump concurrently
 *   under poll() inside fr_py_exec_spawn.
 * - Claims go through fr_py_claim (NOT raw do_lockfree_claim): the
 *   W-PY29 TXN hooks, poison counting, and halt checks live there.
 *   No static output buffer (that would cap batch size).
 * - Order target is derived (fr_py_complete), not forced: unordered
 *   runs disarm the target exactly like the Python worker loop.
 * - Poison batches warn + trap-notify + ack-silent, on_error is
 *   honored (0 retry / 1 skip / 2 fail-fast), wincarn/node lineage
 *   preserved — all mirroring _worker.py and the plugin loop.
 *
 * Params:
 *   wid/ingress_fd/out_fd/signal_fd/fallow_fd as in the other loops.
 *   argv/argc: command vector (argv[argc] must be NULL — enforced
 *     by fr_py_exec_spawn; the caller marshals fork-inherited
 *     strings into a pointer array, same rule as _worker's argv_c).
 *   order_fd: order-pipe write end (-1 disarms).
 *   trap_ack_fd: poison "P:idx:kills" lines (-1 disarms).
 *   wincarn: respawn generation for fr_py_worker_init lineage.
 *   retry_limit: poison threshold (mirrors engine default 3).
 *   on_error: 0 retry (escrow) / 1 skip (ack) / 2 fail-fast (abort).
 *
 * Returns 0 drained-to-EOF, 1 claim/ack failure or fail-fast abort,
 * 2 signal failure (EPIPE = parent gone — fatal, v0 parity). The
 * Python child maps nonzero → worker exit 1 → parent RuntimeError.
 * Poisoned batches warn + notify + ack-silent (never escrowed);
 * zero-length sentinels ack-silent (M1 invariant, never executed).
 * ===================================================================== */
int fr_py_worker_spawn_loop(int wid, char **argv, int argc,
                            int ingress_fd, int out_fd, int signal_fd,
                            int fallow_fd, int order_fd, int trap_ack_fd,
                            int wincarn, int retry_limit, int on_error) {
    fr_py_batch_t claimed;
    int rc;

    if (!argv || argc <= 0 || ingress_fd < 0 || out_fd < 0)
        return 1;
    if (on_error < 0 || on_error > 2)
        return 1;
    if (fr_py_worker_init(wid, 0, wincarn, retry_limit, 0) != 0)
        return 1;
    if (order_fd >= 0)
        g_fr_config.fd_order_pipe = order_fd;
    /* W-PY28: name the output fd for transaction publication + sync
     * the ack offset (respawned generations append to a reused fd). */
    fr_py_txn_out_fd = out_fd;
    fr_py_ack_init(out_fd);

    while (1) {
        rc = fr_py_claim(&claimed);
        if (rc == 2)
            return 0; /* EOF: drained */
        if (rc != 0)
            return 1; /* abort/failure */

        if (claimed.poisoned) {
            char pbuf[64];
            int plen;
            fprintf(stderr,
                    "forkrun [WARN]: Skipping poisoned batch %llu "
                    "(killed %u times).\n",
                    (unsigned long long)claimed.batch_idx,
                    claimed.num_kills);
            if (trap_ack_fd >= 0) {
                plen = snprintf(pbuf, sizeof(pbuf), "P:%llu:%u\n",
                                (unsigned long long)claimed.batch_idx,
                                claimed.num_kills);
                if (plen > 0)
                    (void)robust_pipe_write(trap_ack_fd, pbuf,
                                            (size_t)plen);
            }
            /* Ack-silent (no signal — v0 parity) but ordered: the
             * C orderer still expects its contiguous packet. */
            /* DECISION-02: terminal POISONED disposition, emitted
             * BEFORE the ack, so a death in between rolls it back
             * with the rest of the batch. */
            if (fr_py_emit_disposition(out_fd, signal_fd, (uint64_t)wid,
                                       claimed.batch_idx,
                                       FR_DISP_POISONED) != 0)
                return 1;
            /* STAGE0: notify AFTER the ack, with the real signal fd.
             * A POISONED/SKIPPED record is a real committed record, so
             * it must be announced; a silent ack would commit it and
             * tell nobody, stranding any ordered consumer waiting on
             * that batch's terminal outcome. The fallow/order ack
             * semantics are unchanged. */
            rc = fr_py_complete(signal_fd, (uint64_t)wid, claimed.batch_idx,
                                fallow_fd, out_fd, NULL, 0);
            if (rc != 0)
                return 1;
            continue;
        }

        if (claimed.length == 0) {
            /* EOF sentinel slot: ack but never emit (bash REPLY rule). */
            rc = fr_py_complete(-1, (uint64_t)wid, claimed.batch_idx,
                                fallow_fd, out_fd, NULL, 0);
            if (rc != 0)
                return 1;
            continue;
        }

        rc = fr_py_exec_spawn(argv, argc, claimed.offset,
                              claimed.length, ingress_fd, out_fd,
                              claimed.batch_idx);
        if (rc == 0) {
            /* Success: record already framed by the exec — signal
             * + fallow + order + ack in one call (no output: data
             * NULL skips the writev, signal still honored). */
            /* Fault injection (exactly-once tests): this batch's record IS
             * framed -- the invoke wrote it -- and the ack below has NOT
             * happened. That is the orphan window recovery must handle.
             *
             * Placed at the success site rather than inside
             * fr_py_complete because "success" cannot be identified by the
             * signal argument: the in-process map() executor runs the
             * signal pipe DISARMED (-1) on the success path as well, since
             * there is no drain there, so a signal_fd >= 0 gate fires
             * under the launcher but never for a plain map() call.
             * Structural placement also keeps the injected death out of
             * the poison/skip and sentinel branches, where firing meant a
             * poisoned batch could never be skipped. */
            fr_py_maybe_die_before_ack((int)wid, signal_fd);

            rc = fr_py_complete(signal_fd, (uint64_t)wid,
                                claimed.batch_idx, fallow_fd, out_fd,
                                NULL, 0);
            if (rc == 0)
                continue;
            if (rc == -2)
                return 2; /* signal EPIPE: parent gone — fatal */
            return 1; /* -1 output (unreachable: no output) / -3 ack */
        }
        if (rc < 0)
            return 1; /* pipe/spawn/wait/output infra failure */

        /* --- failure path (command exit code; _worker.py parity) --- */
        if (on_error == 1) {
            /* DECISION-02: terminal SKIPPED disposition. Emitted
             * before the ack, inside the transaction, so a death
             * in between rolls it back and the retry re-emits it. */
            if (fr_py_emit_disposition(out_fd, signal_fd, (uint64_t)wid,
                                      claimed.batch_idx,
                                      FR_DISP_SKIPPED) != 0)
                return 1;
            /* skip: ack (order target derived, no signal — v0 parity). */
            /* STAGE0: notify AFTER the ack, with the real signal fd.
             * A POISONED/SKIPPED record is a real committed record, so
             * it must be announced; a silent ack would commit it and
             * tell nobody, stranding any ordered consumer waiting on
             * that batch's terminal outcome. The fallow/order ack
             * semantics are unchanged. */
            rc = fr_py_complete(signal_fd, (uint64_t)wid, claimed.batch_idx,
                                fallow_fd, out_fd, NULL, 0);
            if (rc != 0)
                return 1;
            continue;
        }
        if (on_error == 2) {
            fflush(NULL);
            fr_py_abort();
            return 1;
        }
        /* Default retry: escrow with kills+1, no ack (the next claim
         * overwrites the armed TLS). Same-process retry on re-claim;
         * poison threshold converts loops into skips above. */
        fflush(NULL);
        fr_py_escrow_deposit(claimed.num_kills + 1);
        continue;
    }
}
