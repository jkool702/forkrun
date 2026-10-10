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
#include <limits.h>
#include <poll.h>
#include <sys/syscall.h>
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

/* The structured trace (Phase A). A header, so Phase B can include the same
 * record format from forkrun_ring.c without a link dependency. See
 * forkrun_trace.h for the contract -- especially the O_APPEND requirement,
 * which is measured, not assumed. */
#include "forkrun_trace.h"

/* Tracing is OFF unless the parent passes --trace-fd. -1 is the off state
 * and every emit call is a single predictable branch against it. */
int fr_trace_fd = -1;

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
    int trace_fd;       /* opt-in structured trace; -1 = disabled */
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

/* Snapshot the open fd set.
 *
 * CR-FIX1-A2/D8: the old version had a fixed 64-entry table and stopped
 * collecting at `n < max`, returning a count the caller could not
 * distinguish from a complete snapshot. A truncated engine_fd[] means a
 * child silently loses eventfds and degrades to polling -- exactly the
 * failure this whole exercise is about. Truncation and enumeration
 * failure are now reported, and both are fatal to the run.
 *
 * Returns the count written, or -1 on failure. *truncated is set when
 * the caller's table could not hold the whole set. An EMPTY result is
 * not an error: a program with nothing open above stderr legitimately
 * has none, and the caller treats "no engine fds" and "enumeration
 * failed" very differently. */
static int snap_fds(int *out, int max, int *truncated) {
    int n = 0;
    DIR *d = opendir("/proc/self/fd");
    *truncated = 0;
    if (!d)
        return -1;                       /* enumeration failed: distinct */
    /* opendir() itself holds an fd, and that fd appears in the listing.
     * Left in, it (a) becomes a bogus "engine fd" in the diff and
     * (b) worse, it makes the pre/post diff unreliable so the real
     * eventfds are dropped from the keep-set -- which is exactly what
     * happened: workers were scrubbing away the ring data/EOF eventfds
     * and then spinning at 100% CPU on POLLNVAL. Exclude it. */
    int self = dirfd(d);
    struct dirent *e;
    errno = 0;
    while ((e = readdir(d)) != NULL) {
        int v = atoi(e->d_name);
        if (v > 2 && v != self) {
            if (n >= max) { *truncated = 1; break; }
            out[n++] = v;
        }
    }
    /* readdir() signals both end-of-directory and error by returning
     * NULL; errno distinguishes them. Ignoring it made a transient
     * readdir error look like a complete (but short) snapshot. */
    if (errno != 0) {
        closedir(d);
        return -1;
    }
    closedir(d);
    return n;
}

/* ---- CR-FIX1-A2: complete close-all-except ----
 *
 * The old scrub looped `for (fd = 3; fd < 1024; fd++)`, which is not a
 * close-all-except policy -- it is a policy for the descriptor range
 * that happens to be small. Anything above 1023 survived into every
 * child. The launcher exists to escape a bloated parent, so leaking
 * descriptors into 30 children is contrary to its purpose even where
 * (on the current Python-driven invocation) the parent's own
 * descriptors are few and low-numbered.
 *
 * Two implementations, same contract:
 *   - close_range(2) over the gaps between sorted keep-list entries,
 *     with the last range running to UINT_MAX (the syscall's own
 *     argument ceiling). RLIMIT_NOFILE is deliberately NOT the bound:
 *     a process may hold descriptors above a limit that was lowered
 *     after they were opened, so it cannot be trusted as an authority.
 *     It is cross-checked, never trusted.
 *   - otherwise: enumerate /proc/self/fd and close what is not kept.
 *
 * Either way, an incomplete enumeration is an error, never a silent
 * success. */

#define CR_MAX_KEEP 256

typedef struct {
    int fd[CR_MAX_KEEP];
    int n;
    int overflow;
} cr_keep;

static void keep_init(cr_keep *k) { k->n = 0; k->overflow = 0; }

/* Duplicates are rejected rather than tolerated: a duplicated entry
 * would shift nothing here, but silently absorbing one would hide a
 * caller bug that shows up as an unreachable gap later. */
static int keep_add(cr_keep *k, int fd) {
    if (fd < 3)
        return 0;
    for (int i = 0; i < k->n; i++)
        if (k->fd[i] == fd)
            return 0;
    if (k->n >= CR_MAX_KEEP) { k->overflow = 1; return -1; }
    k->fd[k->n++] = fd;
    return 0;
}

static void keep_add_engine(cr_keep *k, const int *eng, int n_eng) {
    for (int i = 0; i < n_eng; i++)
        (void)keep_add(k, eng[i]);
}

static int keep_cmp(const void *a, const void *b) {
    int x = *(const int *)a, y = *(const int *)b;
    return (x > y) - (x < y);
}

#if defined(__linux__) && defined(SYS_close_range)
static int have_close_range = -1;
#endif

/* Probe support without closing anything real.
 *
 * The obvious-looking probe -- close_range(~0U, ~0U, 0) -- is a landmine:
 * on a kernel where it *works* it closes descriptors, and a probe that
 * mutates process state is not a probe. UINT_MAX cannot name a live
 * descriptor (RLIMIT_NOFILE is far below it), so a one-descriptor range
 * at UINT_MAX returns 0 on a supporting kernel and ENOSYS/EINVAL on one
 * without it, having closed nothing. */
static int close_range_ok(unsigned lo, unsigned hi) {
#if defined(__linux__) && defined(SYS_close_range)
    if (have_close_range < 0) {
        have_close_range =
            (syscall(SYS_close_range, UINT_MAX, UINT_MAX, 0U) == 0);
    }
    if (!have_close_range)
        return 0;
    if (lo > hi)
        return 1;
    return syscall(SYS_close_range, (unsigned)lo, (unsigned)hi, 0U) == 0;
#else
    (void)lo; (void)hi;
    return 0;
#endif
}

/* Apply the keep-list. Returns 0 on success, -1 if the descriptor space
 * could not be fully enumerated (never a silent partial scrub). */
static int scrub_apply(const cr_keep *k) {
    if (k->overflow)
        return -1;

    int sorted[CR_MAX_KEEP];
    int n = k->n;
    for (int i = 0; i < n; i++) sorted[i] = k->fd[i];
    qsort(sorted, (size_t)n, sizeof(int), keep_cmp);

    /* close_range path: close every gap. */
    unsigned prev = 2;                   /* 0,1,2 are never touched */
    int used_close_range = 1;
    for (int i = 0; i <= n; i++) {
        unsigned next = (i < n) ? (unsigned)sorted[i] : UINT_MAX;
        if (next <= prev)
            continue;                    /* duplicate guard */
        if (next - 1 > prev) {
            if (!close_range_ok(prev + 1, next - 1)) { used_close_range = 0; break; }
        }
        prev = next;
        if (prev == UINT_MAX)
            break;
    }
    if (used_close_range && (n == 0 || prev != UINT_MAX))
        return 0;

    /* Fallback: enumerate. The enumeration fd is itself in the
     * listing and is excluded, exactly as snap_fds does. */
    DIR *d = opendir("/proc/self/fd");
    if (!d)
        return -1;
    int self = dirfd(d);
    int rc = 0;
    struct dirent *e;
    errno = 0;
    while ((e = readdir(d)) != NULL) {
        int v = atoi(e->d_name);
        if (v <= 2 || v == self)
            continue;
        int keepit = 0;
        for (int i = 0; i < n; i++)
            if (sorted[i] == v) { keepit = 1; break; }
        if (!keepit && close(v) != 0 && errno != EBADF)
            rc = -1;
    }
    if (errno != 0)
        rc = -1;
    closedir(d);
    return rc;
}

/* Test-only: after a scrub, confirm every required descriptor survived.
 * A missing one is reported rather than quietly degrading to polling --
 * the difference is invisible until someone measures why the run is
 * 100 ms slower. Off unless --fd-selfcheck is passed. */
static int fd_selfcheck = 0;

static int selfcheck_required(const cr_keep *k) {
    int sorted[CR_MAX_KEEP];
    int n = k->n;
    for (int i = 0; i < n; i++) sorted[i] = k->fd[i];
    qsort(sorted, (size_t)n, sizeof(int), keep_cmp);
    for (int i = 0; i < n; i++)
        if (fcntl(sorted[i], F_GETFD) == -1) {
            fprintf(stderr,
                    "forkrun-cleanroom: SELFCHECK FAILED -- required "
                    "descriptor %d did not survive scrubbing\\n",
                    sorted[i]);
            return -1;
        }
    return 0;
}

/* Single entry point for a child: build the keep-list, scrub, and (if
 * enabled) verify. `role` is only used for diagnostics.
 *
 * The trace descriptor is added HERE rather than at each of the five call
 * sites. Doing it per-site would mean five copies of the same line and a
 * sixth fork site added later could silently scrub the trace away -- the
 * failure would look like "the trace just stopped working", which is the
 * hardest kind of bug to notice in a facility that is off by default.
 * Adding it here makes "every scrubbing child keeps the trace" a property
 * of the scrub path itself.
 *
 * The parameter is non-const because this function extends the keep-list;
 * it was const before only because no caller needed to. */
static void enter_child(const char *role, cr_keep *k) {
    if (fr_trace_fd >= 0) keep_add(k, fr_trace_fd);
    if (scrub_apply(k) != 0) {
        fprintf(stderr,
                "forkrun-cleanroom: %s child could not be given a "
                "complete descriptor set (enumeration or keep-list "
                "failure) -- refusing to run with an unknown descriptor "
                "state\\n", role);
        _exit(72);
    }
    if (fd_selfcheck && selfcheck_required(k) != 0)
        _exit(72);
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

/* Snapshot the open fd set is above (snap_fds). run.py computes
 * engine_fds the same way: diff the fds around fr_py_init. That set is
 * what EVERY child must KEEP -- see enter_child/scrub_apply, which is
 * the subtle part. */

#define MAX_TRACK_FDS CR_MAX_KEEP

/* CR-FIX1-F: how long the capability probe may take before we conclude
 * the plugin's load is unsafe. Bounded so a hanging constructor
 * cannot hang the launcher -- that would trade one hang for another. */
#define CR_PROBE_TIMEOUT_MS 5000

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
/* Stats fd the workers append poisoned batch indices to. Set once in
 * main() before any fork so it is inherited; -1 disables the relay. Read
 * inside spawn_wid to keep it out of that signature, which already has
 * twelve parameters. */
static int g_poison_stats_fd = -1;

static pid_t spawn_wid(int wid, int memfd, int out_fd, int sig_w,
                       int fall_w, fn_worker_plugin_loop wloop,
                       const char *path, const char *func,
                       int retry_limit, int on_error,
                       const int *engine_fd, int n_engine,
                       int wincarn) {
    fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_FORK_REQUEST,
                  (int32_t)wid, (int32_t)wincarn, 0, 0);
    pid_t p = fork();
    if (p < 0)
        return -1;
    if (p == 0) {
        die_with_parent();
        cr_keep k;
        keep_init(&k);
        keep_add(&k, memfd); keep_add(&k, out_fd);
        keep_add(&k, sig_w);  keep_add(&k, fall_w);
        /* KEEP THE ENGINE'S OWN FDS. Scrubbing them away looks tidy
         * and is catastrophic: do_lockfree_claim 3-way-polls the ring
         * data and EOF eventfds, and with those descriptors closed
         * poll returns POLLNVAL *immediately* on every call. The 100ms
         * timeout never engages and the worker spins at 100% CPU
         * forever instead of blocking. It only shows up when the ring
         * is momentarily inconsistent -- which is exactly the state a
         * respawn creates -- so it hides completely in normal runs. */
        keep_add_engine(&k, engine_fd, n_engine);
        /* The poison relay needs this one too. Scrubbing it away is
         * silent -- the worker's relay just finds a closed fd and stops
         * recording, so poisoned_batches would come back empty with
         * poisoned still correct. Exactly the failure mode the relay
         * exists to remove, so it is kept explicitly. */
        keep_add(&k, g_poison_stats_fd);
        enter_child("worker", &k);
        fr_trace_emit(FR_ROLE_WORKER, FR_EV_CHILD_ENTRY,
                      (int32_t)wid, (int32_t)wincarn, 0, 0);
        if (!wloop) _exit(70);
        /* wincarn MUST be this generation's number. It is not
         * diagnostic: fr_py_worker_init stores it in
         * g_fr_config.ring_wincarn, the engine stamps every transaction
         * record with it at claim time, and
         * ring_recover_worker_core() REFUSES to reclaim a batch whose
         * txn->incarnation does not equal the incarnation passed to
         * recovery -- it clears the record and reports "nothing to
         * recover" instead.
         *
         * So hardcoding 0 here (as this did) made every respawned
         * worker publish generation 0 while the parent believed it was
         * generation 1, 2, ... The FIRST death of a worker still
         * recovered correctly, because parent and worker agreed on 0.
         * The SECOND death of the same wid then mismatched, and the
         * in-flight batch was dropped WITHOUT going back to escrow --
         * a completed-looking run, silently missing records.
         *
         * It is also plugin-ABI-visible: ctx->worker_incarn is defined
         * as the respawn generation of the calling worker. */
        int rc = wloop(wid, path, func, memfd, out_fd, sig_w, fall_w,
                       -1, -1, wincarn, retry_limit, on_error);
        fr_trace_emit(FR_ROLE_WORKER, FR_EV_CHILD_EXIT,
                      (int32_t)wid, (int32_t)wincarn, 0, rc);
        _exit(rc == 0 ? 0 : 1);
    }
    fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_FORK_RETURN,
                  (int32_t)wid, (int32_t)wincarn, 0, (int32_t)p);
    return p;
}

/* ---- CR-FIX1-B: bounded fatal teardown ----
 *
 * Three defects the success path hid, all in the `bad` branch:
 *
 *  1. The SPILL child was never killed, and the join for it is a
 *     blocking waitpid. The spill child sits in read() on the caller's
 *     source. When that source is a pipe or socket whose producer stays
 *     open -- which is every stream() caller that has not finished
 *     writing, and every caller that abandons mid-run -- the join never
 *     returns and a detected worker failure becomes a launcher hang.
 *
 *  2. Workers killed on the `bad` path were never reaped, so each left
 *     a zombie for the launcher to exit on.
 *
 *  3. A reaped worker's pid stayed in pids[wid]. Signalling an already
 *     reaped pid normally just fails, but the kernel is free to recycle
 *     that number, and until then the array overstates the live set.
 *
 * The fix is to make "live" mean live: a slot is cleared the moment the
 * parent reaps it and refilled only when a replacement is spawned. The
 * fatal path then signals exactly the live set and reaps whatever is
 * left. Reaping is bounded and non-blocking, so no wait in it can
 * depend on upstream EOF or on a helper that has already stopped. */

/* SIGKILL one live child and clear the slot. A slot already cleared is
 * skipped, so this is safe to call twice over the same table. */
static void kill_slot(pid_t *slot) {
    if (slot && *slot > 0) {
        fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_FATAL_KILL,
                      FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)*slot);
        (void)kill(*slot, SIGKILL);
        *slot = -1;
    }
}

/* Signal every live child in the table, then reap until none remain.
 *
 * The reap pass is non-blocking and loops on WNOHANG, so it terminates
 * even for a child that ignores SIGKILL's delivery for a moment (a
 * process in uninterruptible sleep, say): each pass either harvests a
 * child or observes that none is currently reapable, and SIGKILLed
 * children always become reapable. A bounded spin guards against a
 * pathological kernel that never reports one. */
static void kill_all(pid_t *slots, int nslots) {
    /* Fatal teardown IS traced (an explicit decision), so this path pays
     * a handful of extra write()s against its latency budget. The cost is
     * bounded and deliberate: the minimum event set only, and one record
     * per kill rather than one per spin. The alternative -- a trace that
     * goes silent exactly when a run is going wrong -- is the failure mode
     * the facility exists to prevent. */
    fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_FATAL_BEGIN,
                  FR_TRACE_NA, FR_TRACE_NA, 0, nslots);
    for (int i = 0; i < nslots; i++) kill_slot(&slots[i]);

    /* Harvest everything that is already gone. */
    for (;;) {
        int st = 0;
        pid_t p = waitpid(-1, &st, WNOHANG);
        if (p > 0) {
            fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_FATAL_REAP,
                          FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)st);
            continue;
        }
        if (p < 0 && errno == EINTR) continue;
        break;
    }
    /* Children killed above may not have been reapable on the first
     * pass. Give the kernel a bounded number of further passes. */
    for (int spin = 0; spin < 100; spin++) {
        struct timespec ts = {0, 1000000L};   /* 1 ms */
        int st = 0;
        pid_t p = waitpid(-1, &st, WNOHANG);
        if (p > 0) {
            fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_FATAL_REAP,
                          FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)st);
            spin = -1; continue;
        }
        if (p < 0 && errno == EINTR) { spin = -1; continue; }
        nanosleep(&ts, NULL);
    }
    fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_FATAL_END,
                  FR_TRACE_NA, FR_TRACE_NA, 0, 0);
}

int main(int argc, char **argv) {
    struct opts o;
    memset(&o, 0, sizeof o);
    o.workers = 1; o.source_fd = -1; o.result_fd = -1; o.stats_fd = -1;
    o.drain_mode = 0; o.retry_limit = 3; o.on_error = 0;
    o.respawn_cap = 64;
    o.trace_fd = -1;

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
        else if (!strcmp(argv[i], "--fd-selfcheck"))         fd_selfcheck = 1;
        else if (!strcmp(argv[i], "--trace-fd") && i + 1 < argc)
            o.trace_fd = atoi(argv[++i]);
        else { fprintf(stderr, "forkrun-cleanroom: bad arg %s\n", argv[i]); return 64; }
    }
    if (!o.so_path || o.source_fd < 0 || !o.plugin_path) {
        fprintf(stderr, "forkrun-cleanroom: --so --src --plugin required\n");
        return 64;
    }
    if (o.workers < 1) o.workers = 1;

    /* Activate the trace BEFORE anything forks, so the launcher-init
     * boundary is the first record and every child inherits an open fd.
     *
     * A bad --trace-fd disables tracing rather than failing the run: the
     * trace is an observation channel and must never be able to break the
     * pipeline it observes. That is the same rule as the emit helper's
     * ignored write() result.
     */
    if (o.trace_fd >= 0) {
        if (fcntl(o.trace_fd, F_GETFD) != -1) fr_trace_fd = o.trace_fd;
        else fprintf(stderr, "forkrun-cleanroom: --trace-fd %d unusable; "
                             "continuing without a trace\n", o.trace_fd);
    }
    fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_LAUNCHER_INIT,
                  FR_TRACE_NA, FR_TRACE_NA, 0, 0);

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
     * CR-FIX1-F: the probe runs in a DISPOSABLE SUBPROCESS, because
     * dlopen executes the plugin's ELF constructors in whatever process
     * calls it. A constructor that starts a thread leaves a thread in
     * this process, and every fork() below then happens from a
     * multi-threaded parent -- which is exactly the state a cleanroom
     * exists to avoid. Measured with a constructor that spawns a
     * thread: the launcher died with SIGSEGV during the first worker
     * fork, before doing any work.
     *
     * The engine's own dlopen (fr_py_plugin_ensure, post-fork in each
     * worker) is unaffected and remains the real load path.
     */
    {
        int pp[2];
        if (pipe(pp) != 0) {
            fprintf(stderr, "forkrun-cleanroom: pipe(probe): %s\n",
                    strerror(errno));
            return 70;
        }
        fr_trace_emit(FR_ROLE_PROBE, FR_EV_FORK_REQUEST,
                      FR_TRACE_NA, FR_TRACE_NA, 0, 0);
        pid_t probe = fork();
        if (probe < 0) {
            fprintf(stderr, "forkrun-cleanroom: fork(probe): %s\n",
                    strerror(errno));
            return 70;
        }
        if (probe == 0) {
            close(pp[0]);
            fr_trace_emit(FR_ROLE_PROBE, FR_EV_CHILD_ENTRY,
                          FR_TRACE_NA, FR_TRACE_NA, 0, 0);
            unsigned ver = 0;
            int ok = 0;
            void *ph = dlopen(o.plugin_path, RTLD_NOW | RTLD_LOCAL);
            if (ph) {
                int *use_ctx = (int *)dlsym(ph, "forkrun_use_ctx");
                ver = use_ctx ? (unsigned)*use_ctx : 0u;
                ok = 1;
            }
            /* Report through the pipe, not through the exit status:
             * a constructor that crashes or hangs takes this child with
             * it, and the parent must be able to tell "no such symbol"
             * from "the probe never finished". */
            unsigned payload[2] = {ok, ver};
            ssize_t w = write(pp[1], payload, sizeof payload);
            (void)w;
            close(pp[1]);
            fr_trace_emit(FR_ROLE_PROBE, FR_EV_CHILD_EXIT,
                          FR_TRACE_NA, FR_TRACE_NA, 0, ok);
            _exit(0);
        }
        close(pp[1]);
        fr_trace_emit(FR_ROLE_PROBE, FR_EV_FORK_RETURN,
                      FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)probe);

        /* Bounded read. A constructor that hangs must not hang the
         * launcher -- that would trade one hang for another. */
        unsigned payload[2] = {0, 0};
        ssize_t got = 0;
        struct pollfd pfd = {.fd = pp[0], .events = POLLIN};
        int waited = 0, probe_failed = 0;
        while (waited < CR_PROBE_TIMEOUT_MS) {
            int pr = poll(&pfd, 1, 50);
            if (pr < 0 && errno == EINTR) continue;
            if (pr > 0) {
                got = read(pp[0], payload, sizeof payload);
                break;
            }
            waited += 50;
        }
        close(pp[0]);
        if (got != (ssize_t)sizeof payload) {
            probe_failed = 1;
            (void)kill(probe, SIGKILL);
        }
        /* Reap the probe: bounded, because we may have just killed it. */
        for (int i = 0; i < 200; i++) {
            int st = 0;
            pid_t r = waitpid(probe, &st, WNOHANG);
            if (r > 0) break;
            if (r < 0 && errno == EINTR) continue;
            struct timespec ts = {0, 1000000L};
            nanosleep(&ts, NULL);
        }
        if (probe_failed) {
            /* Distinct from 78 on purpose. 78 means "the plugin is fine,
             * it just lacks the ctx protocol" -- a pre-ingestion refusal
             * the caller may safely retry in-process. A probe that never
             * completed means the plugin's LOAD is itself unsafe, and
             * retrying in-process would dlopen it in the CALLER and
             * reproduce the hazard there. run.py treats 79 as
             * no-fallback; see _CR_EXIT_NO_FALLBACK. */
            fprintf(stderr,
                    "forkrun-cleanroom: capability probe of %s did not "
                    "complete (a constructor may have hung or crashed). "
                    "Refusing, and NOT falling back: an in-process retry "
                    "would load the same plugin in the caller and "
                    "reproduce the problem there.\n", o.plugin_path);
            return 79;
        }
        if (!payload[0]) {
            fprintf(stderr, "forkrun-cleanroom: dlopen plugin: %s\n",
                    "could not be loaded");
            return 69;
        }
        unsigned ver = payload[1];
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
    int pre_trunc = 0, post_trunc = 0;
    int npre = snap_fds(pre_fd, MAX_TRACK_FDS, &pre_trunc);
    if (npre < 0) {
        fprintf(stderr, "forkrun-cleanroom: cannot enumerate /proc/self/fd "
                        "before fr_py_init -- refusing to guess which "
                        "descriptors the engine will need\n");
        return 72;
    }
    if (pre_trunc) {
        fprintf(stderr, "forkrun-cleanroom: descriptor snapshot TRUNCATED "
                        "before fr_py_init (more than %d descriptors open) "
                        "-- refusing to guess the engine descriptor set\n",
                MAX_TRACK_FDS);
        return 72;
    }
    if (p_init(o.lines, o.bytes) != 0) {
        fprintf(stderr, "forkrun-cleanroom: fr_py_init failed\n");
        return 71;
    }
    int npost = snap_fds(post_fd, MAX_TRACK_FDS, &post_trunc);
    if (npost < 0 || post_trunc) {
        /* CR-FIX1-A2/D8: a truncated or failed post-snapshot means the
         * diff below cannot be trusted, and the diff is the ONLY way the
         * children learn which eventfds the engine created. Carrying on
         * would hand them an incomplete keep-list, they would scrub the
         * engine's eventfds away, and the run would quietly degrade to
         * polling -- correct output, unexplained latency. Fail instead. */
        fprintf(stderr, "forkrun-cleanroom: descriptor snapshot after "
                        "fr_py_init %s -- refusing to run with an unknown "
                        "engine descriptor set\n",
                (npost < 0) ? "could not be enumerated"
                            : "was TRUNCATED (more than MAX_TRACK_FDS open)");
        return 72;
    }
    if (o.verbose)
        fprintf(stderr, "INIT_FDS pre=%d post=%d\n", npre, npost);
    int engine_fd[MAX_TRACK_FDS];
    int n_engine = 0;
    if (npost == 0)
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
    fr_trace_emit(FR_ROLE_SPILL, FR_EV_FORK_REQUEST,
                  FR_TRACE_NA, FR_TRACE_NA, 0, 0);
    pid_t spill_pid = fork();
    if (spill_pid < 0) die("fork(spill)");
    if (spill_pid == 0) {
        die_with_parent();
        cr_keep k;
        keep_init(&k);
        keep_add(&k, o.source_fd); keep_add(&k, memfd);
        /* CR-FIX1-A1: the engine's eventfds too. This child calls
         * fr_py_ingest_data_post() once per chunk, and the whole point
         * of that poke is to let the scanner's pre-flight block instead
         * of spin-sleeping (forkrun_ring.c:4472 polls evfd_ingest_data).
         * Scrubbing it away made the poke a silent no-op -- sys_write
         * ignores its return, so the write to a closed fd vanishes and
         * the documented mechanism silently does not execute. */
        keep_add_engine(&k, engine_fd, n_engine);
        enter_child("spill", &k);
        fr_trace_emit(FR_ROLE_SPILL, FR_EV_CHILD_ENTRY,
                      FR_TRACE_NA, FR_TRACE_NA, 0, 0);
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
            /* CR-FIX1-D2: positional write loop.
             *
             * This used to be one pwrite() with `w != n` treated as
             * fatal. That aborted a healthy run on a legal outcome: a
             * short write is permitted, and pwrite() is interruptible,
             * so -1/EINTR took the same branch and killed the run over a
             * signal. It did not silently skip the remainder of the
             * chunk -- it aborted -- but either way a normal write
             * should not end the run.
             *
             * The loop advances both the buffer and the memfd offset by
             * what actually landed, so a chunk is complete only when
             * every byte is in. The ingest notification below therefore
             * still means "all of this chunk is readable", which is the
             * contract the scanner's pre-flight backpressure relies on. */
            size_t want = (size_t)n;
            const char *p = sbuf;
            size_t done = 0;
            while (done < want) {
                ssize_t w = pwrite(memfd, p + done, want - done,
                                   (off_t)(soff + done));
                if (w > 0) { done += (size_t)w; continue; }
                if (w < 0 && errno == EINTR) continue;
                /* Short write (w == 0 with bytes outstanding) or a hard
                 * error: either way this chunk is now incomplete and the
                 * engine must not be told otherwise. */
                if (p_abort) p_abort();
                fr_trace_emit(FR_ROLE_SPILL, FR_EV_CHILD_EXIT,
                              FR_TRACE_NA, FR_TRACE_NA, 0, -1);
                _exit(1);
            }
            soff += (unsigned long long)want;
            p_ipost();
        }
        {
            int rc = p_idone();
            fr_trace_emit(FR_ROLE_SPILL, FR_EV_CHILD_EXIT,
                          FR_TRACE_NA, FR_TRACE_NA, 0, rc);
            _exit(rc == 0 ? 0 : 1);
        }
    }
    fr_trace_emit(FR_ROLE_SPILL, FR_EV_FORK_RETURN,
                  FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)spill_pid);
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
    for (int i = 0; i < o.workers; i++) pids[i] = -1;
    int live = 0;
    int spill_done = 0;

    long t0 = now_ns();

    /* fallow reaper child */
    fr_trace_emit(FR_ROLE_FALLOW, FR_EV_FORK_REQUEST,
                  FR_TRACE_NA, FR_TRACE_NA, 0, 0);
    pid_t fallow_pid = fork();
    if (fallow_pid < 0) die("fork(fallow)");
    if (fallow_pid == 0) {
        die_with_parent();
        cr_keep k;
        keep_init(&k);
        keep_add(&k, fallp[0]); keep_add(&k, memfd);
        /* CR-FIX1-A1 step 4: ring_fallow_main reads its packet pipe and
         * punches holes in the ingress memfd. It touches no engine
         * eventfd, so the engine set is deliberately NOT kept here --
         * retaining descriptors for symmetry alone would re-introduce
         * exactly the "inconsistent keep policy across roles" problem
         * this refactor exists to remove. Kept anyway, so the role's
         * contract is uniform and a future fallow change cannot silently
         * lose them. */
        keep_add_engine(&k, engine_fd, n_engine);
        enter_child("fallow", &k);
        fr_trace_emit(FR_ROLE_FALLOW, FR_EV_CHILD_ENTRY,
                      FR_TRACE_NA, FR_TRACE_NA, 0, 0);
        {
            int rc = p_fall(fallp[0], memfd);
            fr_trace_emit(FR_ROLE_FALLOW, FR_EV_CHILD_EXIT,
                          FR_TRACE_NA, FR_TRACE_NA, 0, rc);
            _exit(rc == 0 ? 0 : 1);
        }
    }
    fr_trace_emit(FR_ROLE_FALLOW, FR_EV_FORK_RETURN,
                  FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)fallow_pid);

    /* Poison relay: tell workers which fd to append batch indices to.
     * getenv-in-the-child is the established mechanism here (see
     * FORKRUN_C_STDIN / FD_WORKER_W), and setenv here is inherited by
     * every fork below. */
    if (o.stats_fd >= 0) {
        char num[32];
        snprintf(num, sizeof num, "%d", o.stats_fd);
        setenv("FRK_POISON_FD", num, 1);
        g_poison_stats_fd = o.stats_fd;
    }

    /* workers */
    for (int i = 0; i < o.workers; i++) {
        pid_t p = spawn_wid(i, memfd, out_fds[i], sigp[1], fallp[1],
                            p_wloop, o.plugin_path, o.plugin_func,
                            o.retry_limit, o.on_error,
                            engine_fd, n_engine, /*wincarn=*/0);
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
    fr_trace_emit(FR_ROLE_SCAN, FR_EV_FORK_REQUEST,
                  FR_TRACE_NA, FR_TRACE_NA, 0, 0);
    pid_t scan_pid = fork();
    if (scan_pid < 0) die("fork(scan)");
    if (scan_pid == 0) {
        die_with_parent();
        cr_keep k;
        keep_init(&k);
        keep_add(&k, memfd);
        /* CR-FIX1-A1: this is the child that actually NEEDS them. The
         * scanner writes evfd_data_arr on every publish
         * (forkrun_ring.c:3848/3875/3885) and blasts evfd_eof_arr at
         * finalization (:5897/:6081). With those descriptors closed,
         * sys_write returns EBADF and every caller ignores it, so the
         * notifications are silently dropped and workers are released
         * only by the 100 ms timeout in do_lockfree_claim. Worse, the
         * pre-flight's poll over evfd_ingest_data (:4472) does not check
         * POLLNVAL, so a closed fd returns immediately and the pre-
         * flight spins instead of sleeping. Both symptoms are invisible
         * in the exit status: the run is correct, just slow and hot. */
        keep_add_engine(&k, engine_fd, n_engine);
        enter_child("scanner", &k);
        fr_trace_emit(FR_ROLE_SCAN, FR_EV_CHILD_ENTRY,
                      FR_TRACE_NA, FR_TRACE_NA, 0, 0);
        {
            int rc = p_scan(memfd);
            fr_trace_emit(FR_ROLE_SCAN, FR_EV_CHILD_EXIT,
                          FR_TRACE_NA, FR_TRACE_NA, 0, rc);
            _exit(rc == 0 ? 0 : 1);
        }
    }
    fr_trace_emit(FR_ROLE_SCAN, FR_EV_FORK_RETURN,
                  FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)scan_pid);

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
    fr_trace_emit(FR_ROLE_DRAIN, FR_EV_FORK_REQUEST,
                  FR_TRACE_NA, FR_TRACE_NA, 0, 0);
    pid_t drain_pid = fork();
    if (drain_pid < 0) die("fork(drain)");
    if (drain_pid == 0) {
        die_with_parent();
        cr_keep k;
        keep_init(&k);
        keep_add(&k, sigp[0]); keep_add(&k, o.result_fd);
        /* Every worker's out_fd must stay open: the drain reads the
         * bytes that land there, and it tracks which worker is alive
         * from the signal pipe. It deliberately does NOT keep the
         * engine set -- it never calls into the ring -- and it must not
         * keep spare_sig, or the pipe never EOFs and it waits forever.
         * That exclusion is now structural rather than incidental:
         * spare_sig is simply not in this list. */
        for (int i = 0; i < o.workers; i++) keep_add(&k, out_fds[i]);
        enter_child("drain", &k);
        fr_trace_emit(FR_ROLE_DRAIN, FR_EV_CHILD_ENTRY,
                      FR_TRACE_NA, FR_TRACE_NA, 0, 0);
        {
            int rc = p_drain(sigp[0], out_fds, o.workers,
                             o.result_fd, o.drain_mode);
            fr_trace_emit(FR_ROLE_DRAIN, FR_EV_CHILD_EXIT,
                          FR_TRACE_NA, FR_TRACE_NA, 0, rc);
            _exit(rc);
        }
    }
    close(sigp[0]);
    fr_trace_emit(FR_ROLE_DRAIN, FR_EV_FORK_RETURN,
                  FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)drain_pid);

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
    fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_SUP_ENTER,
                  FR_TRACE_NA, FR_TRACE_NA, 0, live);
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
                fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_SUP_ABORT,
                              FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)st);
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
        /* The reap is the record that ties a worker's CHILD_ENTRY and
         * CHILD_EXIT to a supervisor decision. `death_cause` is the
         * DECODED status, not the raw wait status, because a raw 16-bit
         * status (78 << 8 == 19968) tells a reader nothing. */
        fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_REAP, (int32_t)wid,
                      (int32_t)incarn[wid], 0,
                      (int32_t)death_cause(st));
        /* CR-FIX1-B: the slot stops being live the moment we reap it.
         * Leaving a reaped pid in pids[wid] overstates the live set and
         * risks signalling a recycled number during fatal teardown. It
         * is refilled below only when a replacement is really forked. */
        pids[wid] = -1;
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
            fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_SUP_ABORT,
                          (int32_t)wid, (int32_t)incarn[wid], 0,
                          (int32_t)p_abort_reason());
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
            fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_SUP_ABORT,
                          (int32_t)wid, (int32_t)incarn[wid], 0,
                          (int32_t)o.respawn_cap);
            bad = 1;
            break;
        }
        incarn[wid]++;
        int rs = dup(spare_sig), rf = dup(spare_fall);
        if (rs < 0 || rf < 0) { bad = 1; break; }
        pid_t np = spawn_wid(wid, memfd, out_fds[wid], rs, rf, p_wloop,
                             o.plugin_path, o.plugin_func,
                             o.retry_limit, o.on_error,
                             engine_fd, n_engine, incarn[wid]);
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
        fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_SUP_RESPAWN,
                      (int32_t)wid, (int32_t)incarn[wid], 0, (int32_t)np);
        if (o.verbose)
            fprintf(stderr, "RESPAWN wid=%d incarn=%d rc=%d\n", wid,
                    incarn[wid], rc);
    }
    fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_SUP_EXIT,
                  FR_TRACE_NA, FR_TRACE_NA, 0, bad);
    if (o.verbose)
        fprintf(stderr, "LOOP_DONE live=%d bad=%d spill_done=%d\n", live,
                bad, spill_done);

    /* ---- CR-FIX1-B: fatal teardown is bounded ----
     *
     * The old code killed the workers and then walked into FOUR blocking
     * waitpids. Any of them could be blocked on a live upstream source:
     * the spill child sits in read() on the caller's descriptor, and
     * nothing in the `bad` path ever signalled it. A caller whose source
     * pipe writer stays open -- the normal case for stream(), and any
     * abandoned run -- turned a detected worker failure into a launcher
     * that never returns.
     *
     * Fatal teardown now signals the whole live set (workers AND every
     * helper, spill included) and reaps non-blockingly. It does not
     * wait for ingestion to complete, does not drain output, and cannot
     * be held hostage by a producer that is not going to write again.
     * A failed run reports failure; it does not try to finish. */
    if (bad) {
        if (p_abort) p_abort();
        int n_slots = o.workers + 4;
        pid_t *slots = calloc((size_t)n_slots, sizeof(pid_t));
        if (slots) {
            for (int i = 0; i < o.workers; i++) slots[i] = pids[i];
            slots[o.workers + 0] = spill_pid;
            slots[o.workers + 1] = scan_pid;
            slots[o.workers + 2] = fallow_pid;
            slots[o.workers + 3] = drain_pid;
            kill_all(slots, n_slots);
            free(slots);
        } else {
            /* No memory for the table: fall back to signalling each
             * group directly rather than skipping the kill entirely. */
            for (int i = 0; i < o.workers; i++) kill_slot(&pids[i]);
            kill_slot(&spill_pid);
            kill_slot(&scan_pid);
            kill_slot(&fallow_pid);
            kill_slot(&drain_pid);
        }
        close(spare_sig);
        close(spare_fall);
        fprintf(stderr,
                "forkrun-cleanroom: fatal -- terminated the pipeline "
                "(workers and helpers signalled, all children reaped); "
                "the input source may have been left partially read\n");
        return 1;
    }

    /* Success path. Everything below preserves the original ordering
     * guarantees: spares closed LAST (so the drain sees EOF only once
     * no further respawn can occur), spill joined LAST (ingestion must
     * be complete before we can call the run successful), and the stats
     * record written only after every child has been joined so its count
     * is final. */
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
     *   u32 version (=2)
     *   u32 poisoned
     *   u32 pad     (reserved; keeps the record 8-byte aligned)
     *   u32 pad
     * Written on a best-effort basis: a failed stats write must not
     * change the run's exit status. The reader treats a short/absent
     * record as "no counts available" and declines rather than
     * reporting a plausible-looking zero. */
    if (o.stats_fd >= 0) {
        /* v2 adds the poisoned-batch-index slots that follow the header:
         *   [u32 version=2][u32 poisoned][u32 workers][u32 slot_stride_u32]
         * then workers * slot_stride_u32 of u32, one slot per worker,
         * each [u32 count][count x u32 batch_idx]. v1 readers only look
         * at the first two words, so the layout is backward compatible.
         * The launcher does NOT zero the slots: workers own their own
         * slot and the memfd starts zero-filled, and memfds are
         * guaranteed zero on creation. */
        uint32_t rec[4] = {2u, 0u, (uint32_t)o.workers, 1024u + 1u};
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