/* W-CLEANROOM launcher — integrated orchestration (NEW/REFACTOR3.5).
 *
 * Mirrors frun's cleanroom for the Python frontend. Python dlopens the
 * substrate into the USER's process, so its workers fork from whatever
 * that process holds; fork() copies the page table per child, so a
 * bloated parent costs ~45ms/fork against ~0.07ms here. frun avoids
 * this by exec'ing into a cleanroom BEFORE ring_init; we do the same,
 * which is also why no engine state has to survive the exec -- the
 * launcher calls fr_py_init itself, in its own small address space.
 *
 * Scope: MATERIALIZED source + C plugin, which is the path with the
 * largest absolute numbers and the most to gain. Streaming needs the
 * ingest child and the reactor's incremental worker spawn, which is
 * follow-on work.
 *
 * The sequence below is a transliteration of the Python path:
 *   run.py::_new_output_memfds / make_pipe / fork_workers
 *   run.py::_fork_ingest_helpers  (fallow + scan children)
 *   run.py::_fork_drain           (fr_py_drain_loop child)
 * with fork+scrub+call+_exit replaced by fork+call+_exit, since this
 * process has no unrelated descriptors to scrub.
 *
 * Build: gcc -O2 -o forkrun_cleanroom forkrun_cleanroom.c -ldl
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <dirent.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

typedef int (*fn_init)(int lines, int bytes);
typedef int (*fn_worker_plugin_loop)(int wid, const char *path,
                                     const char *func_name,
                                     int ingress_fd, int out_fd,
                                     int signal_fd, int fallow_fd,
                                     int order_fd, int trap_ack_fd,
                                     int wincarn, int retry_limit,
                                     int on_error);
typedef int (*fn_scan)(int fd);
typedef int (*fn_ingest_done)(void);
typedef int (*fn_ingest_data_post)(void);
typedef int (*fn_fallow_loop)(int fallow_r, int memfd);
typedef void (*fn_abort_fn)(void);
static fn_abort_fn p_abort;
typedef int (*fn_recover)(int wid, int incarnation, int output_fd,
                         int exit_code);
typedef int (*fn_abort_reason_fn)(void);
typedef unsigned int (*fn_poisoned_count)(void);
static fn_poisoned_count p_poisoned;
static fn_recover p_recover;
static fn_abort_reason_fn p_abort_reason;

typedef int (*fn_drain_loop)(int signal_r, const int *out_fds,
                             int num_workers, int results_fd, int mode);

struct opts {
    const char *so_path;
    const char *plugin_path;
    const char *plugin_func;
    int workers;
    int lines;
    int bytes;
    int source_fd;
    int result_fd;      /* launcher writes framed results here */
    int stats_fd;       /* launcher writes the poison/counter record */
    int drain_mode;
    int retry_limit;
    int on_error;
    int respawn_cap;
    int verbose;
    int fork_only;
};

static int fr_memfd_create(const char *name) {
    return (int)syscall(__NR_memfd_create, name, 0);
}

static void die(const char *what) {
    fprintf(stderr, "forkrun-cleanroom: %s: %s\n", what, strerror(errno));
    _exit(70);
}

static void *sym(void *h, const char *n) {
    void *p = dlsym(h, n);
    if (!p) { fprintf(stderr, "forkrun-cleanroom: missing %s\n", n); _exit(69); }
    return p;
}

static long now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long)ts.tv_sec * 1000000000L + ts.tv_nsec;
}

static long rss_kb(void) {
    FILE *f = fopen("/proc/self/status", "r");
    if (!f) return -1;
    char l[256]; long kb = -1;
    while (fgets(l, sizeof l, f))
        if (!strncmp(l, "VmRSS:", 6)) { kb = strtol(l + 6, NULL, 10); break; }
    fclose(f);
    return kb;
}

/* Close every descriptor except those in `keep`.
 *
 * Python's fork helpers call scrub_fds(keep) before entering the C
 * loop. Without the equivalent here each worker inherits every OTHER
 * worker's out_fd and the shared signal write end, which is both an
 * fd-leak and -- because the drain tracks liveness through those
 * descriptors -- a correctness hazard.
 */
static void scrub_closem_others(const int *keep, int nkeep) {
    for (int fd = 3; fd < 1024; fd++) {
        int keepit = 0;
        for (int i = 0; i < nkeep; i++)
            if (keep[i] == fd) { keepit = 1; break; }
        if (!keepit)
            close(fd);
    }
}

static void raise_fd_limit(void) {
    struct rlimit rl;
    if (getrlimit(RLIMIT_NOFILE, &rl) == 0 && rl.rlim_cur != rl.rlim_max) {
        rl.rlim_cur = rl.rlim_max;
        (void)setrlimit(RLIMIT_NOFILE, &rl);
    }
}

/* Every launcher child dies with the launcher.
 *
 * The Python streaming path kills the launcher on abandonment and waits
 * only for it. Without an explicit parent-death relationship the
 * launcher's descendants -- spill, fallow, scanner, drain and every
 * worker -- survive and unwind only "eventually", by noticing a closed
 * pipe. That is emergent behaviour, not ownership: it leaks fds and CPU
 * and accumulates in a long-lived service. */
static void die_with_parent(void) {
    prctl(PR_SET_PDEATHSIG, SIGKILL);
}

/* Snapshot the open fd set. run.py computes engine_fds the same way:
 * diff the fds around fr_py_init. That set is what every child must
 * KEEP -- see scrub_closem_others below, which is the subtle part. */
static int snap_fds(int *out, int max) {
    int n = 0;
    DIR *d = opendir("/proc/self/fd");
    if (!d) return 0;
    /* opendir() itself holds an fd, and that fd appears in the listing.
     * Left in, it (a) becomes a bogus "engine fd" in the diff and
     * (b) worse, it makes the pre/post diff unreliable so the real
     * eventfds are dropped from the keep-set -- which is exactly what
     * happened: workers were scrubbing away the ring data/EOF eventfds
     * and then spinning at 100% CPU on POLLNVAL. Exclude it. */
    int self = dirfd(d);
    struct dirent *e;
    while ((e = readdir(d)) != NULL && n < max) {
        int v = atoi(e->d_name);
        if (v > 2 && v != self) out[n++] = v;
    }
    closedir(d);
    return n;
}

#define MAX_TRACK_FDS 64

/* Worker-death cause from a waitpid status (D-PORT3 parity with
 * _reactor._death_cause). Signal deaths map to the shell 128+signo
 * convention rather than collapsing to 1, so the true cause survives
 * into forensics; the C recovery core only branches on ==0. */
static int death_cause(int status) {
    if (WIFEXITED(status))
        return WEXITSTATUS(status);
    if (WIFSIGNALED(status))
        return 128 + WTERMSIG(status);
    return 1; /* stopped/continued: generic crash */
}

/* Fork one worker on `wid`. Split out so the supervision loop can
 * respawn onto the SAME wid -- bash does (frun.bash: _respawn_wid=$wID),
 * which keeps the wid -> out_fd -> ring binding stable across
 * generations. Takes the pointer the parent already resolved: dlopen
 * after fork is a classic post-fork hazard. */
static pid_t spawn_wid(int wid, int memfd, int out_fd, int sig_w,
                       int fall_w, fn_worker_plugin_loop wloop,
                       const char *path, const char *func,
                       int retry_limit, int on_error,
                       const int *engine_fd, int n_engine) {
    pid_t p = fork();
    if (p < 0)
        return -1;
    if (p == 0) {
        die_with_parent();
        int keep[4 + MAX_TRACK_FDS];
        keep[0] = memfd; keep[1] = out_fd;
        keep[2] = sig_w;  keep[3] = fall_w;
        /* KEEP THE ENGINE'S OWN FDS. Scrubbing them away looks tidy
         * and is catastrophic: do_lockfree_claim 3-way-polls the ring
         * data and EOF eventfds, and with those descriptors closed
         * poll returns POLLNVAL *immediately* on every call. The 100ms
         * timeout never engages and the worker spins at 100% CPU
         * forever instead of blocking. It only shows up when the ring
         * is momentarily inconsistent -- which is exactly the state a
         * respawn creates -- so it hides completely in normal runs. */
        for (int i = 0; i < n_engine; i++)
            keep[4 + i] = engine_fd[i];
        scrub_closem_others(keep, 4 + n_engine);
        if (!wloop) _exit(70);
        int rc = wloop(wid, path, func, memfd, out_fd, sig_w, fall_w,
                       -1, -1, 0, retry_limit, on_error);
        _exit(rc == 0 ? 0 : 1);
    }
    return p;
}

int main(int argc, char **argv) {
    struct opts o;
    memset(&o, 0, sizeof o);
    o.workers = 1; o.source_fd = -1; o.result_fd = -1; o.stats_fd = -1;
    o.drain_mode = 0; o.retry_limit = 3; o.on_error = 0;
    o.respawn_cap = 64;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--so") && i + 1 < argc)        o.so_path = argv[++i];
        else if (!strcmp(argv[i], "--plugin") && i + 1 < argc) o.plugin_path = argv[++i];
        else if (!strcmp(argv[i], "--func") && i + 1 < argc) o.plugin_func = argv[++i];
        else if (!strcmp(argv[i], "--workers") && i + 1 < argc) o.workers = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--lines") && i + 1 < argc)  o.lines = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--bytes") && i + 1 < argc)  o.bytes = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--src") && i + 1 < argc)   o.source_fd = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--result") && i + 1 < argc) o.result_fd = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--stats-fd") && i + 1 < argc) o.stats_fd = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--drain-mode") && i + 1 < argc) o.drain_mode = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--retry") && i + 1 < argc) o.retry_limit = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--on-error") && i + 1 < argc) o.on_error = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--respawn-cap") && i + 1 < argc) o.respawn_cap = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--verbose"))                o.verbose = 1;
        else if (!strcmp(argv[i], "--fork-only"))             o.fork_only = 1;
        else { fprintf(stderr, "forkrun-cleanroom: bad arg %s\n", argv[i]); return 64; }
    }
    if (!o.so_path || o.source_fd < 0 || !o.plugin_path) {
        fprintf(stderr, "forkrun-cleanroom: --so --src --plugin required\n");
        return 64;
    }
    if (o.workers < 1) o.workers = 1;

    /* Refuse a plugin the engine will NOT drive through the ctx
     * protocol. forkrun_use_ctx is the single capability-negotiation
     * symbol (forkrun_ring.c: forkrun_worker_plugin_loop dlsyms it);
     * without it the engine falls back to the legacy ARGV/stdout route,
     * and the launcher's output channel is a per-worker MEMFD, not that
     * worker's stdout. So such a plugin produces no bytes the launcher
     * can collect -- and the run still exits 0.
     *
     * That combination is the worst possible failure: a
     * successful-looking run that silently returns an empty result
     * set, with no fallback triggered because nothing "failed". Widening
     * the cleanroom envelope is what exposed it -- nine existing plugin
     * tests had been silently taking the in-process path, and started
     * returning b"" the moment the launcher was allowed to serve them.
     *
     * Checking here, before any fork, fails fast and cheap. Exiting
     * non-zero is deliberate: run.py treats that as "launcher
     * unavailable for this call", warns, and falls back to the
     * in-process path, which handles these plugins correctly. The
     * in-process path is slower and CORRECT, which beats fast and
     * empty.
     *
     * dlopen is RTLD_LOCAL and closed immediately; the engine does its
     * own dlopen later and this handle is only a probe.
     */
    {
        void *ph = dlopen(o.plugin_path, RTLD_NOW | RTLD_LOCAL);
        if (!ph) {
            fprintf(stderr, "forkrun-cleanroom: dlopen plugin: %s\n",
                    dlerror());
            return 69;
        }
        int *use_ctx = (int *)dlsym(ph, "forkrun_use_ctx");
        unsigned ver = use_ctx ? (unsigned)*use_ctx : 0u;
        dlclose(ph);
        if ((ver & 0x3u) != 1u && (ver & 0x3u) != 2u) {
            fprintf(stderr,
                    "forkrun-cleanroom: plugin %s exports no "
                    "forkrun_use_ctx (dialect v1/v2 ctx protocol); it "
                    "would be driven via the legacy stdout route, whose "
                    "output the launcher cannot collect. Refusing rather "
                    "than returning an empty result set -- use the "
                    "in-process path for this plugin.\n",
                    o.plugin_path);
            return 78;
        }
    }
    raise_fd_limit();

    void *h = dlopen(o.so_path, RTLD_NOW | RTLD_LOCAL);
    if (!h) { fprintf(stderr, "forkrun-cleanroom: dlopen: %s\n", dlerror()); return 69; }
    fn_init                p_init  = (fn_init)                sym(h, "fr_py_init");
    fn_worker_plugin_loop  p_wloop = (fn_worker_plugin_loop)  sym(h, "fr_py_worker_plugin_loop");
    fn_scan                p_scan  = (fn_scan)                sym(h, "fr_py_scan");
    fn_ingest_done         p_idone = (fn_ingest_done)         sym(h, "fr_py_ingest_done");
    fn_ingest_data_post    p_ipost = (fn_ingest_data_post)    sym(h, "fr_py_ingest_data_post");
    fn_fallow_loop         p_fall  = (fn_fallow_loop)         sym(h, "fr_py_fallow_loop");
    fn_drain_loop          p_drain = (fn_drain_loop)          sym(h, "fr_py_drain_loop");
    p_recover              = (fn_recover)              sym(h, "fr_py_recover_worker");
    p_abort                = (fn_abort_fn)             sym(h, "fr_py_abort");
    p_abort_reason         = (fn_abort_reason_fn)     sym(h, "fr_py_abort_reason");
    p_poisoned             = (fn_poisoned_count)      sym(h, "fr_py_poisoned_count");
    p_abort                = (fn_abort_fn)               sym(h, "fr_py_abort");

    /* Init HERE, after exec. This is the whole point: the state mapping
     * is created in this small address space and inherited by every
     * child forked below. Nothing had to cross the exec boundary. */
    /* fds opened BY fr_py_init -- the ring data/EOF eventfds, escrow,
     * etc. Every child must keep these. Snapshot the set by diffing
     * across the call, exactly as run.py derives ctx["engine_fds"]. */
    int pre_fd[MAX_TRACK_FDS], post_fd[MAX_TRACK_FDS];
    int npre = snap_fds(pre_fd, MAX_TRACK_FDS);
    if (p_init(o.lines, o.bytes) != 0) {
        fprintf(stderr, "forkrun-cleanroom: fr_py_init failed\n");
        return 71;
    }
    int npost = snap_fds(post_fd, MAX_TRACK_FDS);
    if (o.verbose)
        fprintf(stderr, "INIT_FDS pre=%d post=%d\n", npre, npost);
    int engine_fd[MAX_TRACK_FDS];
    int n_engine = 0;
    if (n_engine == 0 && npost == 0)
        fprintf(stderr, "forkrun-cleanroom: WARNING fd snapshot empty; "
                "children will scrub the engine's eventfds\n");
    for (int i = 0; i < npost; i++) {
        int seen = 0;
        for (int j = 0; j < npre; j++)
            if (post_fd[i] == pre_fd[j]) { seen = 1; break; }
        if (!seen) engine_fd[n_engine++] = post_fd[i];
    }

    /* Spill the source into the ingress memfd, poking the eventfd per
     * chunk exactly as the Python spill does, so the scanner's
     * pre-flight blocks instead of spin-sleeping. */
    int memfd = fr_memfd_create("fr_cr_ingress");
    if (memfd < 0) die("memfd_create(ingress)");

    /* W-CR2: spill in a CHILD so it OVERLAPS the scan.
     *
     * This used to run inline: read the whole source into the ingress
     * memfd, then scan it. Two consequences, both bad:
     *
     *  - It cannot be live. For an unbounded/streaming source the
     *    launcher would sit in read() until EOF and never emit a
     *    single result, which is not streaming, it is a stall.
     *  - It costs a full extra pass over the corpus before any work
     *    starts. Measured end-to-end at 28 workers on light_5M, that
     *    was 672.9 ms in-process vs 738.9 ms here -- a 9% regression,
     *    because the Python path overlaps spill with scan using a
     *    forked UMA ingest child and this did not.
     *
     * Forking the spill fixes both: the scanner starts reading the
     * ingress memfd while it is still filling, and the engine's
     * documented ingest->scanner EOF protocol (EOF_PROTOCOL.md §5:
     * ingest_complete plus a forced final pread) handles the tail.
     * The eventfd poke per chunk stays -- that is what makes the
     * scanner's pre-flight block instead of spin-sleeping.
     */
    pid_t spill_pid = fork();
    if (spill_pid < 0) die("fork(spill)");
    if (spill_pid == 0) {
        die_with_parent();
        int keep[2] = {o.source_fd, memfd};
        scrub_closem_others(keep, 2);
        static char sbuf[1 << 20];
        unsigned long long soff = 0;
        for (;;) {
            ssize_t n = read(o.source_fd, sbuf, sizeof sbuf);
            if (n < 0) {
                if (errno == EINTR) continue;
                /* Tell the ENGINE, not just ourselves. Otherwise the
                 * scanner and workers wait on an ingest that will never
                 * finish, and the launcher joins spill_pid only LAST. */
                if (p_abort) p_abort();
                _exit(1);
            }
            if (n == 0) break;
            ssize_t w = pwrite(memfd, sbuf, (size_t)n, (off_t)soff);
            if (w != n) {
                if (p_abort) p_abort();
                _exit(1);
            }
            soff += (unsigned long long)n;
            p_ipost();
        }
        _exit(p_idone() == 0 ? 0 : 1);
    }
    close(o.source_fd);      /* only the spill child reads the source */

    int *out_fds = calloc((size_t)o.workers, sizeof(int));
    if (!out_fds) die("calloc(out_fds)");
    for (int i = 0; i < o.workers; i++) {
        char nm[48];
        snprintf(nm, sizeof nm, "fr_cr_out_%d", i);
        out_fds[i] = fr_memfd_create(nm);
        if (out_fds[i] < 0) die("memfd_create(out)");
    }

    /* ONE shared signal pipe, matching run.py: workers write, the
     * drain reads. W-PY15 resizes it to 1MB so workers can run ahead. */
    int sigp[2];
    if (pipe(sigp) != 0) die("pipe(signal)");
    {
        /* F_SETPIPE_SZ = 1031; best effort, exactly as the Python side. */
        (void)fcntl(sigp[1], 1031, 1 << 20);
    }
    int fallp[2];
    if (pipe(fallp) != 0) die("pipe(fallow)");

    pid_t *pids = calloc((size_t)o.workers, sizeof(pid_t));
    if (!pids) die("calloc(pids)");
    int *incarn = calloc((size_t)o.workers, sizeof(int));
    if (!incarn) die("calloc(incarn)");
    int live = 0;
    int spill_done = 0;

    long t0 = now_ns();

    /* fallow reaper child */
    pid_t fallow_pid = fork();
    if (fallow_pid < 0) die("fork(fallow)");
    if (fallow_pid == 0) {
        die_with_parent();
        int keep[2] = {fallp[0], memfd};
        scrub_closem_others(keep, 2);
        _exit(p_fall(fallp[0], memfd) == 0 ? 0 : 1);
    }

    /* workers */
    for (int i = 0; i < o.workers; i++) {
        pid_t p = spawn_wid(i, memfd, out_fds[i], sigp[1], fallp[1],
                            p_wloop, o.plugin_path, o.plugin_func,
                            o.retry_limit, o.on_error,
                            engine_fd, n_engine);
        if (p < 0) die("fork(worker)");
        pids[i] = p;
        live++;
    }
    /* Keep a SPARE of the write ends for respawns, exactly as run.py's
     * spare_signal_w does, then drop the originals so EOF still means
     * "every worker is gone". Dropping them unconditionally (as this
     * once did) made every respawn inherit a CLOSED fd: the new worker
     * signalled to EBADF and the drain blocked on the signal pipe
     * forever. The spare is closed LAST, after the supervision loop. */
    int spare_sig = dup(sigp[1]);
    int spare_fall = dup(fallp[1]);
    if (spare_sig < 0 || spare_fall < 0) die("dup(signal/fallow)");
    close(sigp[1]);
    close(fallp[1]);

    /* scanner child: pre-flight, ramp, publish */
    pid_t scan_pid = fork();
    if (scan_pid < 0) die("fork(scan)");
    if (scan_pid == 0) {
        die_with_parent();
        int keep[1] = {memfd};
        scrub_closem_others(keep, 1);
        _exit(p_scan(memfd) == 0 ? 0 : 1);
    }

    long t1 = now_ns();

    if (o.fork_only) {
        printf("CLEANROOM workers=%d fork_ms=%.3f per_fork_ms=%.4f rss_kb=%ld\n",
               o.workers, (t1 - t0) / 1e6, (double)(t1 - t0) / 1e6 / o.workers,
               rss_kb());
        for (int i = 0; i < o.workers; i++) (void)waitpid(pids[i], NULL, WNOHANG);
        (void)waitpid(scan_pid, NULL, WNOHANG);
        (void)waitpid(fallow_pid, NULL, WNOHANG);
        fflush(stdout);
        _exit(0);
    }

    /* drain child: move worker output memfds -> result fd */
    pid_t drain_pid = fork();
    if (drain_pid < 0) die("fork(drain)");
    if (drain_pid == 0) {
        die_with_parent();
        int n = o.workers + 2;
        int *keep = calloc((size_t)n, sizeof(int));
        if (!keep) _exit(70);
        keep[0] = sigp[0]; keep[1] = o.result_fd;
        for (int i = 0; i < o.workers; i++) keep[i + 2] = out_fds[i];
        scrub_closem_others(keep, n);
        free(keep);
        _exit(p_drain(sigp[0], out_fds, o.workers, o.result_fd, o.drain_mode));
    }
    close(sigp[0]);

    int alive = o.workers + 2;   /* workers + scan + fallow (+drain) */
    (void)alive;
    int bad = 0;

    /* ---- W-CR4: supervision with recovery (bash reactor parity) ----
     *
     * This used to wait on each worker in turn and set bad=1 if it
     * exited non-zero, so a dead worker's CLAIMED-BUT-UNACKED ring slot
     * was never reclaimed. The remaining workers then see
     * read_idx < write_idx and block waiting for work nobody will ever
     * consume: a SIGKILLed worker HANGS the run. That is the whole
     * reason the cleanroom could not serve orchestrator=True.
     *
     * bash does not have this problem, and the reason is not that bash
     * has a different poll: frun.bash's supervision loop calls
     * `ring_recover_worker` on EVERY death, which reclaims the in-flight
     * batch from the dead worker's WorkerTxn record (IDLE -> CLAIMING ->
     * CLAIMED -> COMMITTING -> IDLE). The C state machine is the sole
     * classification authority.
     *
     * `ring_poll` cannot be reused here: its only output channel is
     * bind_variable("POLL_EVENT", ...), and in any non-bash build
     * bind_variable is a STUB (substratestubs.c:22) that discards name
     * and value, with no getter. So the event classification is done
     * here, and the POLICY mirrors _reactor.py -- which is the right
     * reference, because bash and _reactor.py are equivalent: both
     * defer to the same ring_recover_worker_core and neither uses the
     * pre-W-PY28 trap-ACK grace on a current substrate.
     *
     * Return codes, identical in both:
     *   0 RECOVERED / 1 NO_BATCH / 3 ALREADY_DONE -> respawn same wid
     *   2 NORMAL_EXIT (EOF drain or teardown)     -> no respawn
     *   4 RACE_DETECTED (died mid-transaction)   -> abort
     *   5 recovery failed (orphan revert/escrow)  -> abort
     */
    while (live > 0 && !bad) {
        int st = 0;
        pid_t p = waitpid(-1, &st, 0);
        if (p < 0) {
            if (errno == EINTR)
                continue;
            break;
        }
        /* The spill child must be watched even though it is not a
         * worker. If it dies abnormally the engine never learns the
         * ingest FAILED -- SIGKILL is uncatchable, so the child cannot
         * call fr_py_abort() itself -- and the scanner plus every worker
         * then wait on an ingest that will never complete. That is a
         * HANG, and it is the sharpest form of the spill-lifecycle
         * hazard. The launcher is the only party that can still act,
         * so it converts the death into an engine abort here.
         *
         * A spill child that exits 0 has simply reached source EOF,
         * which is the normal path and must NOT abort anything. */
        if (p == spill_pid) {
            spill_done = 1;
            if (!(WIFEXITED(st) && WEXITSTATUS(st) == 0)) {
                fprintf(stderr, "forkrun-cleanroom: spill child died "
                        "(status %d) -- aborting the engine\n",
                        death_cause(st));
                if (p_abort) p_abort();
                bad = 1;
                break;
            }
            continue;
        }
        int wid = -1;
        for (int i = 0; i < o.workers; i++)
            if (pids[i] == p) { wid = i; break; }
        if (wid < 0) {
            /* A helper death is NOT a neutral event. Both references
             * treat it as fatal: bash's ring_poll watches the scanner
             * and fallow death pipes alongside the worker ones, and
             * run.py's _watch_pipeline says outright "Fallow death
             * (WNOHANG) is fatal; indexer/scanner/ingest deaths
             * classify via their death pipes".
             *
             * Ignoring them here is what produced the last hang: a
             * SIGKILLed SCANNER exits without finalizing, so the EOF
             * evfd is never written, and every worker then polls the
             * ring forever waiting for work that cannot arrive. The
             * supervisor must convert a helper death into an engine
             * abort, because the engine cannot notice it itself.
             *
             * The SCANNER is the important one: its finalization (the
             * EOF evfd blast) is what releases every blocked worker. */
            /* The DRAIN is in the same class and for a stronger
             * reason: without it no output can be delivered at all, and
             * there is nothing to recover INTO -- the launcher cannot
             * re-drain from inside itself once the child is gone. The
             * launcher exits 0 with zero bytes in that case, which is
             * the worst possible outcome: a successful-looking run that
             * silently produced nothing. */
            int helper_death = (p == scan_pid || p == fallow_pid ||
                                p == drain_pid);
            if (helper_death &&
                !(WIFEXITED(st) && WEXITSTATUS(st) == 0)) {
                fprintf(stderr, "forkrun-cleanroom: %s child died "
                        "(status %d) -- aborting the engine\n",
                        p == scan_pid ? "scanner"
                        : p == fallow_pid ? "fallow" : "drain",
                        death_cause(st));
                if (p_abort) p_abort();
                bad = 1;
                break;
            }
            continue;               /* drain, and clean helper exits */
        }
        live--;
        int rc = p_recover ? p_recover(wid, incarn[wid], out_fds[wid],
                                       death_cause(st))
                           : 5;    /* no core -> cannot vouch for it */
        if (rc == 2)
            continue;               /* NORMAL_EXIT: drained to EOF */
        if (rc == 4 || rc == 5) {
            fprintf(stderr, "forkrun-cleanroom: worker %d recovery rc=%d "
                    "(status %d)\n", wid, rc, death_cause(st));
            bad = 1;
            break;
        }
        /* The engine's own abort state gates the respawn. bash gets
         * this free -- its poll loop returns ABORT on emergency_abort.
         * This loop has no poll, so without the check an
         * on_error="fail-fast" worker is respawned FOREVER: it aborts,
         * recover says "recovered", we fork it again, and the run hangs
         * instead of raising. Caught by test_fail_fast_raises_both. */
        if (p_abort_reason && p_abort_reason() != 0) {
            fprintf(stderr, "forkrun-cleanroom: engine abort (reason %d) "
                    "after worker %d -- not respawning\n",
                    p_abort_reason(), wid);
            bad = 1;
            break;
        }
        /* Backstop for a respawn loop the abort flag does not cover.
         * fr_config_t.respawn_cap is unlimited in the Python reactor,
         * which is safe there because it polls; here the cap is the
         * only thing bounding an unbounded fork loop. */
        if (o.respawn_cap >= 0 && incarn[wid] >= o.respawn_cap) {
            fprintf(stderr, "forkrun-cleanroom: worker %d hit respawn cap "
                    "(%d) -- aborting\n", wid, o.respawn_cap);
            bad = 1;
            break;
        }
        incarn[wid]++;
        int rs = dup(spare_sig), rf = dup(spare_fall);
        if (rs < 0 || rf < 0) { bad = 1; break; }
        pid_t np = spawn_wid(wid, memfd, out_fds[wid], rs, rf, p_wloop,
                             o.plugin_path, o.plugin_func,
                             o.retry_limit, o.on_error,
                             engine_fd, n_engine);
        /* The child inherited its own copy of rs/rf; the launcher's must
         * be dropped or every respawn PERMANENTLY holds the signal and
         * fallow pipe write ends open. That is precisely what the drain
         * and the fallow reaper are waiting for: both block until EOF,
         * and EOF means "every worker is gone". One leaked dup per
         * respawn and neither ever sees it, so the run HANGS after the
         * supervision loop has already finished cleanly. */
        close(rs);
        close(rf);
        if (np < 0) { bad = 1; break; }
        pids[wid] = np;
        live++;
        if (o.verbose)
            fprintf(stderr, "RESPAWN wid=%d incarn=%d rc=%d\n", wid,
                    incarn[wid], rc);
    }
    if (o.verbose)
        fprintf(stderr, "LOOP_DONE live=%d bad=%d spill_done=%d\n", live,
                bad, spill_done);
    if (bad)
        for (int i = 0; i < o.workers; i++)
            if (pids[i] > 0) (void)kill(pids[i], SIGKILL);
    /* Spare closed LAST: while it is open no signal-pipe EOF can be
     * seen, which is what keeps the drain alive across respawns. */
    close(spare_sig);
    close(spare_fall);
    { int st; if (waitpid(scan_pid, &st, 0) > 0 &&
          !(WIFEXITED(st) && WEXITSTATUS(st) == 0)) bad = 1; }
    { int st; if (waitpid(fallow_pid, &st, 0) > 0 &&
          !(WIFEXITED(st) && WEXITSTATUS(st) == 0)) bad = 1; }
    { int st; if (waitpid(drain_pid, &st, 0) > 0 &&
          !(WIFEXITED(st) && WEXITSTATUS(st) == 0)) bad = 1; }
    /* The spill child exits only at source EOF, which for a streaming
     * source is the producer finishing. Join it LAST and treat a
     * failure as fatal: if the spill died early the scanner saw a
     * truncated corpus, and silently returning short output is exactly
     * the class of bug this project refuses. */
    { int st; if (waitpid(spill_pid, &st, 0) > 0 &&
          !(WIFEXITED(st) && WEXITSTATUS(st) == 0)) bad = 1; }

    if (o.verbose)
        fprintf(stderr, "PHASE spawn_to_scanner=%.2fms rss_kb=%ld bad=%d\n",
                (t1 - t0) / 1e6, rss_kb(), bad);
    /* Emit the counter record LAST, after every worker has been joined,
     * so the count is final. This is the channel that lets the launcher
     * serve strict_poison and return_stats instead of declining them.
     *
     * It works because g_state (which holds poisoned_count) lives in
     * SHARED memory -- fr_py_init mmaps it MAP_SHARED precisely so that
     * forked children share it -- so the atomic increment a worker makes
     * on its way to poisoning a batch is visible here in the parent. A
     * plain global would have given a per-process copy and a silent
     * zero.
     *
     * Layout (little-endian, fixed):
     *   u32 version (=1)
     *   u32 poisoned
     *   u32 pad     (reserved; keeps the record 8-byte aligned)
     *   u32 pad
     * Written on a best-effort basis: a failed stats write must not
     * change the run's exit status. The reader treats a short/absent
     * record as "no counts available" and declines rather than
     * reporting a plausible-looking zero. */
    if (o.stats_fd >= 0) {
        uint32_t rec[4] = {1u, 0u, 0u, 0u};
        rec[1] = p_poisoned ? p_poisoned() : 0u;
        size_t off = 0;
        while (off < sizeof rec) {
            ssize_t w = write(o.stats_fd, (const char *)rec + off,
                              sizeof rec - off);
            if (w <= 0) {
                if (w < 0 && errno == EINTR) continue;
                break;
            }
            off += (size_t)w;
        }
    }
    return bad ? 1 : 0;
}