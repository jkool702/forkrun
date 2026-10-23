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
#include "forkrun_udf_version.h"
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

/* Stage 3: the live child tables, reachable from the termination
 * handler below.
 *
 * The launcher had NO SIGTERM/SIGINT handler, so the default
 * disposition killed it immediately: no teardown ran, no process group
 * was signalled, and every command descendant of every worker was
 * ABANDONED. That contradicts the documented Option A guarantee, which
 * covers launcher teardown and parent abandonment. The handler restores
 * it. */
static pid_t *g_worker_pids;
static int g_worker_count;
static pid_t g_helper_pids[8];
static int g_helper_count;
static volatile sig_atomic_t g_terminating;

static void fr_on_terminate(int sig) {
    /* Only async-signal-safe calls here. kill() and _exit() qualify;
     * fprintf and waitpid do not, so the warning is a raw write and the
     * children are signalled rather than reaped -- they are killed, and
     * the kernel reparents anything that outlives us.
     *
     * kill(-pgid) goes FIRST so descendants die even though this
     * process is about to stop existing. */
    static const char msg[] =
        "forkrun-cleanroom: terminated -- killing worker process groups\n";
    ssize_t ignored;
    for (int i = 0; i < g_worker_count; i++) {
        if (g_worker_pids[i] > 0) {
            (void)kill(-g_worker_pids[i], SIGKILL);
            (void)kill(g_worker_pids[i], SIGKILL);
        }
    }
    for (int i = 0; i < g_helper_count; i++) {
        if (g_helper_pids[i] > 0)
            (void)kill(g_helper_pids[i], SIGKILL);
    }
    ignored = write(2, msg, sizeof(msg) - 1);
    (void)ignored;
    g_terminating = 1;
    _exit(128 + sig);
}

typedef int (*fn_init)(int lines, int bytes);
typedef int (*fn_worker_plugin_loop)(int wid, const char *path,
                                     const char *func_name,
                                     int ingress_fd, int out_fd,
                                     int signal_fd, int fallow_fd,
                                     int order_fd, int trap_ack_fd,
                                     int wincarn, int retry_limit,
                                     int on_error);
/* Spawn's entry point takes an argv VECTOR, not two strings:
 *   spawn : (wid, char **argv, int argc, ingress, out, sig, fallow,
 *            order, trap, wincarn, retry, on_error)
 *   plugin: (wid, const char *path, const char *func, ingress, out, ...)
 *   udf   : (wid, const char *module, const char *attr, ingress, ...)
 *
 * Same arity, INCOMPATIBLE types at positions 2 and 3. Casting spawn's
 * symbol to the plugin callback type is undefined behaviour: it would
 * pass a char** and an int where two const char* are expected, and on
 * any sane ABI the callee would read the argv POINTER as a string.
 *
 * So the loops are never invoked through one type. A worker descriptor
 * names the mode and carries that mode's own arguments, and a
 * dispatcher calls the matching prototype. */
typedef int (*fn_worker_spawn_loop)(int wid, char **argv, int argc,
                                    int ingress_fd, int out_fd,
                                    int signal_fd, int fallow_fd,
                                    int order_fd, int trap_ack_fd,
                                    int wincarn, int retry_limit,
                                    int on_error);

typedef enum {
    WK_PLUGIN = 0,
    WK_UDF,
    WK_SPAWN
} worker_kind;

/* Mode-specific worker invocation. Carries exactly the arguments that
 * mode's prototype declares, so no call site can pass the wrong shape. */
typedef struct {
    worker_kind kind;
    const char *a;          /* WK_PLUGIN: path,  WK_UDF: module */
    const char *b;          /* WK_PLUGIN: func,  WK_UDF: attr   */
    char **argv;            /* WK_SPAWN: NULL-terminated vector  */
    int argc;               /* WK_SPAWN: element count          */
} worker_desc;

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
/* W-EXP-2 Phase A: committed DATA-frame count, per logical node.
 * Returns 0 on success, -1 for a bad node or no engine state. */
typedef int (*fn_committed_frames)(int node, uint64_t *out);
static fn_committed_frames p_committed;
/* W-EXP-2 Phase A: is that counter live at all? Without asking, a counter
 * disabled by FORKRUN_C07_COUNT=0 reads as "zero frames committed" and the
 * certificate would fail every complete run. */
typedef int (*fn_c07_enabled_fn)(void);
static fn_c07_enabled_fn p_c07_enabled;
static fn_recover p_recover;
static fn_abort_reason_fn p_abort_reason;

typedef int (*fn_drain_loop)(int signal_r, const int *out_fds,
                             int num_workers, int results_fd, int mode);
/* W-EXP-2 step C: NUMA entry points already exported by the substrate
 * (see _shim.c). The launcher resolves them only when --nodes > 1 and
 * refuses to start if one is missing. */
typedef int (*fn_init_numa)(int lines, int bytes, int num_nodes,
                            const char *numa_map);
typedef int (*fn_numa_ingest)(int infd, int outfd, int num_nodes);
typedef int (*fn_indexer_numa)(int memfd, int node);
typedef int (*fn_numa_scanner)(int memfd, int node, int spawn_fd,
                               int num_nodes);
typedef int (*fn_fallow_phys)(int fd_in, int fd_file);
typedef int (*fn_orderer)(int order_r, int output_fd, int unordered,
                          int numa);
typedef int (*fn_eof_posted)(void);
static fn_eof_posted p_eof_posted;   /* engine-backed ingest completion */
typedef int (*fn_node_complete)(int node);
static fn_node_complete p_index_complete;  /* per-node indexing frontier */
static fn_node_complete p_scan_complete;   /* per-node scanner finalization */
typedef int (*fn_worker_plugin_loop_numa)(int wid, const char *path,
        const char *func_name, int ingress_fd, int out_fd, int signal_fd,
        int fallow_fd, int order_fd, int trap_ack_fd, int wincarn,
        int retry_limit, int on_error, int node_id);

struct opts {
    const char *so_path;
    const char *plugin_path;
    /* WK_SPAWN command vector, kept as DISTINCT argv elements. Never
     * assembled with shell-word parsing: a newline is a legal character
     * inside a single argument, and any newline-delimited encoding would
     * be ambiguous against one. */
    char **spawn_argv;
    int spawn_argc;
    int spawn_argv_cap;
    const char *plugin_func;
    const char *udf_helper;   /* per-minor _fr_udf*.so (P1-3) */
    const char *udf_module;
    const char *udf_attr;
    const char *udf_roots;    /* space-separated, from the interpreter */
    /* DECLARED caller major.minor, from the wrapper's sys.version_info.
     * A declaration, not an authenticated identity: after exec the
     * launcher cannot know which interpreter started it. Required for
     * UDF mode; see setup_udf_helper's version gate. */
    const char *caller_version;
    const char *libpython_path;
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
    int supervise;      /* 1 = recover+respawn, 0 = fail-fast (DECISION-03) */
    int num_nodes;      /* 1 = UMA; >1 selects the NUMA pipeline */
    const char *numa_map;   /* comma-separated physical IDs, --nodes long */
    int order_index;    /* run the C orderer (NUMA only) */
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

/* The keep-list is a per-child descriptor set, and the DRAIN child must
 * hold one output descriptor PER WORKER. The old fixed 256 therefore
 * capped the launcher at ~250 workers -- silently, and as a confusing
 * "child could not be given a complete descriptor set" failure in the
 * middle of startup.
 *
 * The bound is now derived from the ENGINE's own worker ceiling
 * (MAX_TXN_WORKERS = 1024 in forkrun_ring.c:1535): a worker id at or
 * above that is rejected by the engine itself, so a larger keep-list
 * would only describe configurations the engine cannot run. The
 * headroom covers the other descriptors a child keeps (engine eventfds,
 * the signal/fallow/order pipes, the source and result descriptors).
 *
 * A configuration above this is refused BEFORE any fork, with the
 * count it would have needed -- never discovered halfway through
 * startup. */
#define CR_MAX_KEEP (1024 + 64)

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

/* =====================================================================
 * P1-3: UDF helper lifecycle -- loaded and INITIALISED BEFORE any fork.
 *
 * The launcher is the only process that may hold the interpreter: the
 * helper cannot be loaded into a process that already runs Python, and
 * the Python parent is out of scope by construction (the launcher is
 * exec'd). Workers inherit the initialised interpreter by fork, which
 * measures 6.8-11.3x faster than initialising per worker on CPython
 * 3.14.7 with a single-threaded launcher.
 *
 * That last clause is the whole safety argument, and the launcher can
 * BREAK it: dlopen() runs the object's ELF constructors, and a
 * constructor that starts a thread makes every subsequent fork()
 * multi-threaded. That is not hypothetical -- CR-FIX1-F documents the
 * launcher dying with SIGSEGV during the first worker fork because of
 * exactly this, in the plugin path.
 *
 * So loading the helper is guarded twice:
 *   1. a disposable probe subprocess dlopens it first, exactly as the
 *      plugin path does, so a constructor that crashes or hangs does not
 *      take the launcher down;
 *   2. AFTER loading for real, the launcher reads its own thread count
 *      and REFUSES to continue if it is no longer single-threaded.
 *      A pre-fork interpreter initialised from a multi-threaded parent
 *      is the exact state the cleanroom exists to prevent, so we fail
 *      closed rather than hope.
 * ===================================================================== */

static void *g_udf_handle = NULL;
static int   g_udf_ready  = 0;
static void *g_so_handle  = NULL;   /* substrate, for fr_py_udf_bind */

/* Bound helper entry points, resolved once before any fork. */
typedef int  (*fn_udf_init)(const char *const *, int);
typedef int  (*fn_udf_before_fork)(void);
typedef int  (*fn_udf_after_fork_parent)(void);
typedef int  (*fn_udf_after_fork_child)(void);
typedef int  (*fn_udf_hooks_avail)(void);
typedef int  (*fn_udf_bind)(void *, void *);

static fn_udf_before_fork       g_before_fork = NULL;
static fn_udf_after_fork_parent g_after_parent = NULL;
static fn_udf_after_fork_child  g_after_child  = NULL;

/* How many threads does THIS process have? Read from /proc/self/status
 * because there is no portable alternative, and fail closed if it cannot
 * be read -- an unknown thread count is not evidence of a safe one. */
static int self_thread_count(void)
{
    FILE *f = fopen("/proc/self/status", "r");
    if (!f) return -1;
    char line[256];
    int n = -1;
    while (fgets(line, sizeof line, f)) {
        if (strncmp(line, "Threads:", 8) == 0) {
            n = atoi(line + 8);
            break;
        }
    }
    fclose(f);
    return n;
}

/* THE fork site. Every fork in this launcher goes through here.
 *
 * Once the interpreter is up, a fork must be choreographed or the child
 * can deadlock on internal locks when it calls back into Python. Keeping
 * this in one function is the point: the external review was explicit
 * that an individual call site must not be able to forget, and there are
 * seven fork sites here.
 *
 * The parent hook runs on the FAILURE path too -- PyOS_BeforeFork()
 * already took locks that must be released.
 *
 * Before the interpreter exists this is a plain fork(), which is what
 * every non-UDF run does. */
static pid_t fr_fork(void)
{
    if (!g_udf_ready)
        return fork();

    if (g_before_fork && g_before_fork() != 0)
        return -1;                  /* fail closed, do not fork */
    pid_t p = fork();
    if (p == 0) {
        /* CHILD. Must run before any Python call here, and must NOT be
         * paired with the parent hook -- running the parent hook in the
         * child unlocks a mutex the child hook owns, and CPython aborts
         * with "PyMutex_Unlock: unlocking mutex that is not locked". */
        if (g_after_child) g_after_child();
        return 0;
    }
    if (g_after_parent) g_after_parent();   /* parent only, incl. p < 0 */
    return p;
}

/* Stats fd the workers append poisoned batch indices to. Set once in
 * main() before any fork so it is inherited; -1 disables the relay. Read
 * inside spawn_wid to keep it out of that signature, which already has
 * twelve parameters. */
static int g_poison_stats_fd = -1;


/* Load, bind and INITIALISE the UDF helper. Must run before any fork.
 *
 * Returns 0 on success. On failure returns non-zero and the caller
 * treats the cleanroom as unavailable for this call -- run.py warns and
 * falls back to the in-process path, which is slower and CORRECT. Fast
 * and empty is the failure mode this avoids.
 *
 * Roots: derived from the INTERPRETER's own site configuration by
 * run.py and handed to us on stdin-free argv. site_import is 0 for
 * isolation, which drops EVERY site root including the system one, so a
 * UDF whose dependency chain spans roots (adjustText -> numpy -> a third
 * root) needs all of them passed explicitly. Never hardcoded here. */
/* UDF helper setup outcomes. These are REFUSALS, distinct from "the run
 * failed": each is decided before the spill child is forked, so the
 * caller may still fall back to in-process execution. 80 and 81 are
 * classified pre-ingestion in run.py (_CR_EXIT_PRE_INGEST) and are
 * deliberately NOT in _CR_EXIT_NO_FALLBACK -- we CAN establish that
 * declining them is safe, which is what distinguishes them from 79
 * ("the C plugin probe failed such that loading it in the CALLER would
 * be unsafe"). */
/* Bound on the UDF probe. Generous enough that a slow disk does not trip
 * it, short enough that a wedged constructor is not a hang. */
#ifndef UDF_PROBE_TIMEOUT_MS
#define UDF_PROBE_TIMEOUT_MS 5000
#endif
/* poll() slice and reap budget, in milliseconds. */
#ifndef UDF_PROBE_SLICE_MS
#define UDF_PROBE_SLICE_MS 50
#endif
#ifndef UDF_PROBE_REAP_SLICES
#define UDF_PROBE_REAP_SLICES 200   /* 200 x 1ms = 200ms */
#endif

#define UDF_SETUP_OK          0
#define UDF_SETUP_GENERIC    -1   /* maps to the pre-existing 71 path */
#define UDF_SETUP_VERIFY     80   /* mismatch, or version unverifiable */
#define UDF_SETUP_INVALID    82   /* bad/missing --caller-version */
#define UDF_SETUP_PROBE_HANG 81   /* bounded probe expired */

/* Probe -> parent report. Fixed size, written in one shot. */
struct udf_probe_result {
    int32_t  status;     /* 0 ok, 1 dlopen failed, 2 version symbol absent */
    int32_t  pad;
    struct fr_udf_version version;   /* typed fields: no packing to get wrong */
};

/* Monotonic milliseconds. The probe deadline is stated in wall-clock
 * terms, so it must be measured with a clock that cannot jump.
 *
 * A counter incremented only on poll() timeout is NOT a deadline: an
 * EINTR storm or a slow trickle of report bytes advances it too slowly,
 * and elapsed time can exceed the configured bound without the counter
 * reaching it. */
static long long udf_monotonic_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000LL + (long long)(ts.tv_nsec / 1000000L);
}

/* Bounded reap, used after EVERY kill. An earlier version killed and
 * returned without reaping again, so the claim that cleanup always
 * reaps the child was broader than the code. */
static int udf_reap_bounded(pid_t p)
{
    for (int i = 0; i < UDF_PROBE_REAP_SLICES; i++) {
        int st = 0;
        pid_t r = waitpid(p, &st, WNOHANG);
        if (r > 0) return 1;
        if (r < 0) {
            if (errno == EINTR) continue;
            if (errno == ECHILD) return 1;   /* already reaped elsewhere */
            return 0;
        }
        struct timespec ts = {0, 1000000L};
        nanosleep(&ts, NULL);
    }
    return 0;
}

/* Strict MAJOR.MINOR grammar.
 *
 * sscanf("%d.%d") is NOT a strict parser: "3.14garbage" and "3.14.1" both
 * yield two integers and leave trailing text unexamined, which is not the
 * contract R2 specifies. This accepts digits, exactly one dot, digits,
 * and requires the string to END there. It also bounds the accumulator,
 * so a long digit run cannot overflow the int it is stored in. */
static int parse_caller_version(const char *s, int *maj, int *min)
{
    const char *p = s;
    long ma = 0, mi = 0;
    if (!s || !*s) return -1;
    while (*p >= '0' && *p <= '9') {
        ma = ma * 10 + (*p - '0');
        if (ma > 999) return -1;
        p++;
    }
    if (ma == 0 || *p != '.') return -1;
    p++;
    if (!(*p >= '0' && *p <= '9')) return -1;   /* "3." is not 3.something */
    while (*p >= '0' && *p <= '9') {
        mi = mi * 10 + (*p - '0');
        if (mi > 999) return -1;
        p++;
    }
    if (*p != '\0') return -1;      /* strict: nothing may follow */
    *maj = (int)ma; *min = (int)mi;
    return 0;
}

/* Bounded wait for the probe's report, then SIGKILL and a bounded reap.
 *
 * Mirrors the plugin probe's shape (deadline, SIGKILL, WNOHANG reap)
 * because the previous UDF probe used a BLOCKING read and an UNTIMED
 * waitpid: a constructor that hung hung the launcher forever. Since the
 * version check must query the library, that hang is on the critical path
 * of a safety decision and cannot be tolerated.
 *
 * THE FIRST VERSION OF THIS FUNCTION HAD THE SAME BUG IT WAS WRITTEN TO
 * FIX. It did a blocking read() and consulted waited_ms only AFTER, so a
 * constructor that never wrote a byte left the parent parked inside
 * read() with the deadline never reached -- the timer and the SIGKILL
 * were unreachable code. Exit 81 was wired up and could not happen.
 *
 * So: poll() with a monotonic deadline and accumulate partial reports,
 * which is the only way to bound a read that may never complete. The
 * The reap has its OWN bounded budget (UDF_PROBE_REAP_SLICES), not the
 * same deadline: a completed report's child may need a moment to finish
 * _exit, and folding that into the deadline would fail healthy probes.
 * So the total is bounded -- deadline PLUS at most two reap budgets --
 * and the 5s figure is the report deadline alone.
 *
 * Returns 0 only when a complete report arrived AND the child was
 * reaped. Returns -1 on timeout or a truncated report. */
/* Probe outcomes. DISTINGUISHED on purpose: a single "failed" collapsed
 * deadline expiry and an early child death into the same exit 81 with a
 * "TIMED OUT" message, so a constructor that CRASHED reported as a
 * timeout. Still fail-closed, but it misstated what happened and made
 * 81 meaningless as a timeout signal.
 *
 *   UDF_PROBE_OK      complete report, child reaped
 *   UDF_PROBE_TIMEOUT the deadline expired with the report incomplete
 *   UDF_PROBE_FAILED  the child died or closed early without reporting
 *   UDF_PROBE_STUCK   a complete report whose child would not reap */
#define UDF_PROBE_OK      0
#define UDF_PROBE_TIMEOUT (-1)
#define UDF_PROBE_FAILED  (-2)
#define UDF_PROBE_STUCK   (-3)

static int udf_probe_await(int fd, pid_t probe,
                           struct udf_probe_result *out)
{
    size_t got = 0;
    int complete = 0;
    int timed_out = 0;
    /* ABSOLUTE deadline, re-derived before every poll. Bounding the
     * loop by elapsed wall-clock rather than by "how many times poll
     * timed out" is what makes the guarantee independent of partial
     * reads and signal interruptions. */
    const long long deadline =
        udf_monotonic_ms() + (long long)UDF_PROBE_TIMEOUT_MS;

    while (got < sizeof *out) {
        long long now = udf_monotonic_ms();
        if (now >= deadline) { timed_out = 1; break; }
        int remain = (int)(deadline - now);
        if (remain > UDF_PROBE_SLICE_MS) remain = UDF_PROBE_SLICE_MS;

        struct pollfd pf;
        pf.fd = fd; pf.events = POLLIN; pf.revents = 0;
        int pr = poll(&pf, 1, remain);
        if (pr < 0) {
            if (errno == EINTR) continue;   /* deadline re-checked above */
            break;
        }
        if (pr == 0) continue;              /* slice expired, not the bound */
        if (pf.revents & (POLLIN | POLLHUP)) {
            ssize_t r = read(fd, (char *)out + got, sizeof *out - got);
            if (r > 0) { got += (size_t)r; continue; }
            if (r < 0 && errno == EINTR) continue;
            break;                          /* EOF or error: truncated */
        }
        if (pf.revents & (POLLERR | POLLNVAL)) break;
    }
    if (got == sizeof *out) complete = 1;

    /* A complete report does not mean the child has exited -- it writes,
     * then _exit -- so reap before deciding anything. */
    if (complete && udf_reap_bounded(probe))
        return UDF_PROBE_OK;

    /* Incomplete report: the child is either wedged (deadline expired) or
     * already gone. Kill FIRST on a confirmed timeout rather than spending
     * a reap interval waiting for a child that is known not to have
     * finished -- the previous order waited, then killed. */
    if (timed_out) (void)kill(probe, SIGKILL);
    if (!udf_reap_bounded(probe)) {
        (void)kill(probe, SIGKILL);
        /* RETAIN the second result. It used to be discarded and the
         * "cleanup NOT confirmed" line printed unconditionally, so a
         * child that DID reap after the kill was still reported as
         * unreaped -- a diagnostic contradicting the code that produced
         * it, in the very path this was meant to make accurate. */
        if (!udf_reap_bounded(probe)) {
            fprintf(stderr, "forkrun-cleanroom: UDF probe child %ld did not "
                            "reap after SIGKILL; continuing (cleanup NOT "
                            "confirmed)\n", (long)probe);
        }
    }
    return complete ? UDF_PROBE_STUCK
                    : (timed_out ? UDF_PROBE_TIMEOUT : UDF_PROBE_FAILED);
}

/* Resolve a symbol and confirm the HELPER ITSELF owns it.
 *
 * dlsym(handle, name) searches the opened object AND its automatically
 * loaded dependencies, not just the object. So a helper missing the
 * stamp could in principle be accepted if one of its dependencies
 * happened to export a same-named symbol -- and, more generally, any of
 * the other fr_udf_* symbols resolved by cast below would be called
 * through whatever signature the found definition actually has.
 *
 * Every one of them now goes through here, not just the version stamp.
 *
 * dladdr() reports the ELF object that DEFINES a function, which lets
 * the launcher check that the definition came from the file it chose.
 * A transitive match is treated as absent: fail closed.
 *
 * This is a robustness measure, not a fix for a demonstrated defect --
 * the other symbols have unchanged signatures, so a helper built from
 * the same tree is unaffected. It is here because the helper is
 * buildable by hand (`make -f Makefile.substrate udf-lib`), so a
 * hand-built third-party helper is a real scenario rather than a
 * hypothetical one. */
static void *sym_owned_by(void *handle, const char *name,
                          const char *helper_path)
{
    void *p = dlsym(handle, name);
    if (!p) return NULL;
    Dl_info info;
    if (dladdr(p, &info) == 0 || !info.dli_fname) {
        fprintf(stderr, "forkrun-cleanroom: cannot attribute %s to an ELF "
                        "object; refusing to use it\n", name);
        return NULL;
    }
    /* Compare the basename: the dependency path is recorded by the loader
     * and may be an absolute path we do not have. */
    const char *got = strrchr(info.dli_fname, '/');
    got = got ? got + 1 : info.dli_fname;
    const char *want = strrchr(helper_path, '/');
    want = want ? want + 1 : helper_path;
    if (strcmp(got, want) != 0) {
        fprintf(stderr, "forkrun-cleanroom: %s resolves into %s, not into "
                        "the helper %s; refusing to call through a foreign "
                        "definition\n", name, got, want);
        return NULL;
    }
    return p;
}

static int setup_udf_helper(const char *helper_path, const char *roots_spec,
                            const char *caller_version, int source_fd,
                            const char *libpython_path)
{
    void *hu;
    fn_udf_init init_fn;
    fn_udf_hooks_avail hooks_avail;
    fn_udf_bind bind_fn;
    void *call_fn, *free_fn;

    if (!helper_path || !*helper_path)
        return UDF_SETUP_GENERIC;

    /* Validate the declaration BEFORE the probe.
     *
     * The probe dlopen()s the helper, which runs its ELF constructors.
     * Parsing after it means a malformed declaration executes
     * third-party code before being rejected -- and a helper that then
     * fails to load reports 71 or 81 instead of the promised 80. An
     * argument the launcher can check in microseconds should never be
     * gated behind loading untrusted code.
     *
     * 82 rather than 80: an invalid DECLARATION is a caller bug, not a
     * property of the helper. Conflating them meant an internal
     * programming error would permanently blacklist a perfectly good
     * artifact in the Python-side negative cache. */
    int caller_maj = 0, caller_min = 0;
    if (parse_caller_version(caller_version, &caller_maj, &caller_min) != 0) {
        fprintf(stderr, "forkrun-cleanroom: UDF mode requires "
                        "--caller-version=MAJOR.MINOR with nothing after it "
                        "(got %s); the launcher cannot infer the caller "
                        "after exec.\n",
                caller_version ? caller_version : "(absent)");
        return UDF_SETUP_INVALID;
    }

    /* auditwheel strips the helper's libpython DT_NEEDED (manylinux policy),
     * so pre-load libpython with RTLD_GLOBAL before ANY dlopen of the helper
     * (including the disposable probe, which uses RTLD_LOCAL and needs the
     * global symbols to resolve). Without this, the probe fails and the UDF
     * route falls back to in-process Python, which the acceptance harness
     * must not accept. */
    {
        /* Prefer an explicitly provided libpython path (from the Python
         * frontend's sysconfig), falling back to name-based resolution. */
        void *_lh = NULL;
        char _lp[512];
        if (libpython_path && libpython_path[0]) {
            _lh = dlopen(libpython_path, RTLD_NOW | RTLD_GLOBAL);
            if (!_lh) {
                fprintf(stderr, "forkrun-cleanroom: dlopen libpython (%s): %s\n",
                        libpython_path, dlerror());
                return UDF_SETUP_GENERIC;
            }
        } else {
            snprintf(_lp, sizeof(_lp), "libpython%d.%d.so.1.0",
                     caller_maj, caller_min);
            _lh = dlopen(_lp, RTLD_NOW | RTLD_GLOBAL);
            if (!_lh) {
                snprintf(_lp, sizeof(_lp), "libpython%d.%d.so",
                         caller_maj, caller_min);
                _lh = dlopen(_lp, RTLD_NOW | RTLD_GLOBAL);
            }
            if (!_lh) {
                fprintf(stderr, "forkrun-cleanroom: dlopen libpython (%s): %s\n",
                        _lp, dlerror());
                return UDF_SETUP_GENERIC;
            }
        }
    }

    /* (1) Disposable probe first, mirroring the plugin path: dlopen
     * runs ELF constructors, and a constructor that crashes or hangs
     * must not take the launcher with it.
     *
     * The probe now also REPORTS THE HELPER'S BUILD VERSION, because the
     * version has to be read out of the loaded object and dlopen is how
     * that happens -- so the version query is inside the probe, where a
     * hang is already bounded.
     *
     * The probe child closes the source descriptor BEFORE dlopen. fork()
     * shares the open-file-description offset, so a constructor that read
     * the inherited descriptor would advance the caller's visible offset
     * even though forkrun's spill child never started. The unchanged-
     * offset guarantee we make to callers is about OUR ingestion, and
     * this keeps a third-party constructor from silently breaking it.
     * stdin is closed too when it aliases the source. */
    struct fr_udf_version helper_version = { 0, 0 };
    {
        int pp[2];
        if (pipe(pp) != 0)
            return UDF_SETUP_GENERIC;
        pid_t probe = fr_fork();
        if (probe < 0) { close(pp[0]); close(pp[1]); return UDF_SETUP_GENERIC; }
        if (probe == 0) {
            close(pp[0]);
            /* Drop our reach to the caller's data BEFORE anything from the
             * helper can run. */
            if (source_fd >= 0 && source_fd != pp[1]) {
                close(source_fd);
                source_fd = -1;
            }
            if (source_fd != 0) close(0);
            struct udf_probe_result r;
            r.status = 1; r.pad = 0;
            r.version.major = 0; r.version.minor = 0;
            void *ph = dlopen(helper_path, RTLD_NOW | RTLD_LOCAL);
            if (ph) {
                fr_udf_built_version_fn vf =
                    (fr_udf_built_version_fn)
                    sym_owned_by(ph, FR_UDF_BUILT_VERSION_SYMBOL,
                                 helper_path);
                if (vf) { r.status = 0; r.version.major = 0;
                          r.version.minor = 0; vf(&r.version); }
                else     { r.status = 2; }
            }
            ssize_t w = write(pp[1], &r, sizeof r);
            (void)w;
            close(pp[1]);
            _exit(0);
        }
        close(pp[1]);
        struct udf_probe_result r;
        memset(&r, 0, sizeof r);
        int rc = udf_probe_await(pp[0], probe, &r);
        close(pp[0]);
        if (rc == UDF_PROBE_TIMEOUT) {
            fprintf(stderr, "forkrun-cleanroom: UDF helper probe TIMED OUT "
                            "after %d ms (%s); a helper ELF constructor is "
                            "not returning\n",
                    UDF_PROBE_TIMEOUT_MS, helper_path);
            return UDF_SETUP_PROBE_HANG;
        }
        if (rc != UDF_PROBE_OK) {
            /* NOT a timeout: the probe child died, closed the pipe, or
             * reported incompletely. Saying "TIMED OUT" here would make
             * exit 81 meaningless -- a constructor that CRASHES reports
             * here, immediately, and would otherwise be indistinguishable
             * from one that hangs. */
            fprintf(stderr, "forkrun-cleanroom: UDF helper probe did not "
                            "complete (%s): %s\n", helper_path,
                    rc == UDF_PROBE_STUCK
                        ? "report arrived but the probe child would not reap"
                        : "probe child exited or closed the pipe before "
                          "reporting");
            return UDF_SETUP_GENERIC;
        }
        if (r.status == 1) {
            fprintf(stderr, "forkrun-cleanroom: UDF helper probe failed to "
                            "load (%s)\n", helper_path);
            return UDF_SETUP_GENERIC;
        }
        if (r.status == 2) {
            /* Fail closed. An older helper with no version symbol cannot
             * be shown to match the caller, and "probably fine" is not a
             * basis for initialising an interpreter. */
            fprintf(stderr, "forkrun-cleanroom: UDF helper (%s) exports no "
                            "%s; its CPython compatibility CANNOT BE "
                            "VERIFIED. Refusing. (A helper built against "
                            "the older, differently-typed symbol is also "
                            "refused here, by name.)\n",
                    helper_path, FR_UDF_BUILT_VERSION_SYMBOL);
            return UDF_SETUP_VERIFY;
        }
        helper_version = r.version;
    }

    /* (1b) Version gate. DECLARED, not authenticated: after exec the
     * launcher cannot identify the interpreter that started it, so this
     * establishes only that the helper matches the version the caller
     * declared. The Python wrapper fills that in from sys.version_info
     * and nothing else.
     *
     * major and minor are compared SEPARATELY as integers. No bit
     * packing: an earlier version packed the caller as major<<16|minor
     * and extracted the helper as (hex>>16)&0xffff, which is
     * major<<8|minor, so a MATCHING 3.14/3.14 pair compared unequal and
     * refused every correct call. */
    {
        if (helper_version.major != caller_maj ||
            helper_version.minor != caller_min) {
            fprintf(stderr, "forkrun-cleanroom: UDF helper (%s) was built "
                            "against CPython %d.%d but the caller declared "
                            "%d.%d; refusing to initialise an interpreter "
                            "across the mismatch\n",
                    helper_path, helper_version.major, helper_version.minor,
                    caller_maj, caller_min);
            return UDF_SETUP_VERIFY;
        }
    }

    /* (2) Load for real.
     *
     * RTLD_GLOBAL, deliberately, and this is a LOADER POLICY rather than
     * an accident:
     *
     * The helper is a CPython-linked shared object, so it DEPENDS on
     * libpython. Since CPython 3.8 on Unix, extension modules no longer
     * link libpython directly -- they resolve libpython's symbols
     * (PyFloat_Type and friends) out of the global namespace at load
     * time. CPython's own embedding guidance is explicit: when Python
     * is embedded, libpython must be loaded with RTLD_GLOBAL, not
     * RTLD_LOCAL.
     *
     * With RTLD_LOCAL here, libpython's symbols stayed out of the
     * global namespace, so the interpreter this launcher initialises
     * could not load ANY extension module:
     *
     *     ImportError: .../lib-dynload/math...so:
     *                  undefined symbol: PyFloat_Type
     *
     * Two consequences, and the second is the more dangerous one
     * because it is SILENT:
     *
     *   1. A UDF that imports math / re / numpy returned ZERO records
     *      and NO exception -- every batch poisoned, with nothing
     *      naming the cause in the caller's visible output.
     *   2. json still imported, but WITHOUT its C accelerator, so
     *      json.loads ran 13.19us instead of 2.88us -- 4.6x slower,
     *      with no diagnostic at all.
     *
     * Loading the helper with RTLD_GLOBAL puts libpython (its
     * dependency) into the global namespace, which is what the
     * extension modules need.
     *
     * SCOPE. The wider symbol scope is confined to this launcher's own
     * address space. The launcher is a separate, exec'd process; the
     * caller's Python process is untouched. The helper's exported
     * symbols are all prefixed fr_udf_* (15 of them, verified with
     * `nm -D --defined-only`), so the added collision surface is
     * negligible -- and symbol visibility is NOT treated as a security
     * boundary here: the boundary is the separate process, the
     * interpreter's isolated config, and the explicit root allowlist.
     *
     * The DISPOSABLE PROBE at the dlopen above keeps RTLD_LOCAL: it is
     * a throwaway child whose only job is to prove the artifact loads.
     */
    /* libpython already pre-loaded above (RTLD_GLOBAL) before the probe,
     * so it is available in the global namespace for this dlopen. */
    hu = dlopen(helper_path, RTLD_NOW | RTLD_GLOBAL);
    if (!hu) {
        fprintf(stderr, "forkrun-cleanroom: dlopen UDF helper: %s\n",
                dlerror());
        return UDF_SETUP_GENERIC;
    }

    /* (2b) Re-verify against the handle we will ACTUALLY initialise
     * with, not just the probe handle. The probe already loaded the same
     * path, so this is normally redundant -- which is the point: it costs
     * one dlsym and closes the gap between "what we probed" and "what we
     * execute". */
    {
        fr_udf_built_version_fn vf =
            (fr_udf_built_version_fn)
            sym_owned_by(hu, FR_UDF_BUILT_VERSION_SYMBOL, helper_path);
        if (!vf) {
            fprintf(stderr, "forkrun-cleanroom: UDF helper (%s) lost %s "
                            "between probe and load\n",
                    helper_path, FR_UDF_BUILT_VERSION_SYMBOL);
            return UDF_SETUP_VERIFY;
        }
        struct fr_udf_version live = { 0, 0 };
        vf(&live);
        if (live.major != helper_version.major ||
            live.minor != helper_version.minor) {
            fprintf(stderr, "forkrun-cleanroom: UDF helper (%s) reported "
                            "%d.%d on probe but %d.%d on load; refusing\n",
                    helper_path, helper_version.major, helper_version.minor,
                    live.major, live.minor);
            return UDF_SETUP_VERIFY;
        }
    }

    /* (3) THE GUARD. dlopen just ran this library's ELF constructors,
     * which may have started a thread. If this process is no longer
     * single-threaded, the pre-fork initialisation below would create an
     * interpreter in exactly the state the cleanroom exists to prevent.
     * Fail closed: an unreadable thread count is not a safe one. */
    int nthreads = self_thread_count();
    if (nthreads != 1) {
        fprintf(stderr, "forkrun-cleanroom: refusing UDF mode -- this "
                        "process has %s%d thread(s) after loading the "
                        "helper; pre-fork interpreter init requires "
                        "exactly 1.\n",
                nthreads < 0 ? "an unknown number of " : "", 
                nthreads < 0 ? 0 : nthreads);
        return UDF_SETUP_GENERIC;
    }

    /* Every helper symbol is ownership-checked, not merely looked up.
     * A bare dlsym() returns a match from the helper OR from anything it
     * pulled in, so a dependency exporting a same-named symbol would be
     * called in place of ours -- with our caller's arguments and no
     * diagnostic. FR_UDF_BUILT_VERSION_SYMBOL below already worked this
     * way; the same reasoning covers the rest, and the helper is
     * hand-buildable, so a third-party helper is a real scenario. */
    init_fn     = (fn_udf_init)      sym_owned_by(hu, "fr_udf_init", helper_path);
    hooks_avail = (fn_udf_hooks_avail) sym_owned_by(hu, "fr_udf_fork_hooks_available", helper_path);
    call_fn     = sym_owned_by(hu, "fr_udf_call", helper_path);
    free_fn     = sym_owned_by(hu, "fr_udf_free", helper_path);
    g_before_fork = (fn_udf_before_fork) sym_owned_by(hu, "fr_udf_before_fork", helper_path);
    g_after_parent = (fn_udf_after_fork_parent) sym_owned_by(hu, "fr_udf_after_fork_parent", helper_path);
    g_after_child  = (fn_udf_after_fork_child)  sym_owned_by(hu, "fr_udf_after_fork_child", helper_path);
    if (!init_fn || !call_fn || !free_fn || !hooks_avail) {
        fprintf(stderr, "forkrun-cleanroom: UDF helper is missing required "
                        "symbols\n");
        return UDF_SETUP_GENERIC;
    }
    if (!hooks_avail()) {
        fprintf(stderr, "forkrun-cleanroom: this CPython has no fork hooks "
                        "(HAVE_FORK); refusing pre-fork interpreter init\n");
        return UDF_SETUP_GENERIC;
    }

    /* (4) Initialise, in the launcher, before any fork. Roots come from
     * the interpreter's own site configuration (space-separated). */
    const char *roots[16];
    int nroots = 0;
    if (roots_spec && *roots_spec) {
        char buf[4096];
        snprintf(buf, sizeof buf, "%s", roots_spec);
        for (char *tok = strtok(buf, " "); tok && nroots < 16;
             tok = strtok(NULL, " "))
            if (*tok) roots[nroots++] = tok;
    }
    if (init_fn(roots, nroots) != 0) {
        const char *msg = (const char *)sym_owned_by(hu, "fr_udf_last_error", helper_path);
        fprintf(stderr, "forkrun-cleanroom: fr_udf_init failed: %s\n",
                msg ? msg : "(no detail)");
        return UDF_SETUP_GENERIC;
    }

    /* (5) Hand the loop its two entry points. The shim must not link
     * libpython, so it cannot resolve these itself; binding here means
     * both the pointers and the initialised interpreter are inherited by
     * every worker through plain fork. */
    bind_fn = (fn_udf_bind) sym(g_so_handle, "fr_py_udf_bind");
    if (!bind_fn || bind_fn(call_fn, free_fn) != 0) {
        fprintf(stderr, "forkrun-cleanroom: fr_py_udf_bind failed\n");
        return UDF_SETUP_GENERIC;
    }

    g_udf_handle = hu;
    g_udf_ready  = 1;
    return 0;
}



/* Invoke a worker loop through ITS OWN prototype.
 *
 * The switch is the whole point: each arm calls the signature that
 * mode actually declares. A single cast-and-call would compile and
 * produce nonsense at runtime, which is the failure this replaces. */
/* Validate a worker descriptor BEFORE anything is executed.
 *
 * Argument transport rules (Stage 3):
 *   - arguments stay distinct argv elements, never re-parsed;
 *   - newlines are legal inside an element, so no line-based encoding;
 *   - NUL cannot be represented in a POSIX argv element at all, so it is
 *     rejected here rather than silently truncating the command.
 *
 * Runs before the first fork and before the source is read, so an
 * unusable command cannot consume input and then fail. */
static int fr_validate_worker_desc(const worker_desc *d) {
    if (d == NULL)
        return UDF_SETUP_GENERIC;
    if (d->kind == WK_SPAWN) {
        if (d->argv == NULL || d->argc <= 0)
            return UDF_SETUP_GENERIC;
        if (d->argv[d->argc] != NULL)
            return UDF_SETUP_GENERIC;               /* must be NULL-terminated */
        for (int i = 0; i < d->argc; i++) {
            if (d->argv[i] == NULL)
                return UDF_SETUP_GENERIC;
        }
        /* NUL needs no check HERE and cannot be: a C string is
         * NUL-terminated by definition, so an embedded NUL is not
         * representable and would have truncated the argument before it
         * ever reached this function. The rejection therefore happens at
         * the point user input becomes an argv element -- run.py, before
         * the vector is built and before any input is read. Checking for
         * it again at this layer would be theatre. */
    } else {
        if (d->a == NULL || d->b == NULL)
            return UDF_SETUP_GENERIC;
    }
    return 0;
}

static int fr_run_worker(const worker_desc *d,
                         fn_worker_plugin_loop p_wloop,
                         fn_worker_spawn_loop s_wloop,
                         fn_worker_plugin_loop_numa p_wnuma,
                         int wid, int ingress_fd, int out_fd,
                         int signal_fd, int fallow_fd, int order_fd,
                         int trap_ack_fd,
                         int wincarn, int retry_limit, int on_error,
                         int node) {
    switch (d->kind) {
    case WK_SPAWN:
        if (!s_wloop)
            return UDF_SETUP_GENERIC;
        return s_wloop(wid, d->argv, d->argc, ingress_fd, out_fd,
                       signal_fd, fallow_fd, -1, trap_ack_fd,
                       wincarn, retry_limit, on_error);
    case WK_UDF:
        if (!p_wloop)
            return UDF_SETUP_GENERIC;
        return p_wloop(wid, d->a, d->b, ingress_fd, out_fd, signal_fd,
                       fallow_fd, -1, trap_ack_fd, wincarn, retry_limit,
                       on_error);
    case WK_PLUGIN:
    default:
        if (p_wnuma != NULL && node >= 0)
            return p_wnuma(wid, d->a, d->b, ingress_fd, out_fd,
                           signal_fd, fallow_fd, order_fd, trap_ack_fd,
                           wincarn, retry_limit, on_error, node);
        if (!p_wloop)
            return UDF_SETUP_GENERIC;
        return p_wloop(wid, d->a, d->b, ingress_fd, out_fd, signal_fd,
                       fallow_fd, order_fd, trap_ack_fd, wincarn,
                       retry_limit, on_error);
    }
}

/* =====================================================================
 * W-EXP-2 step B: typed supervision substrate (experimental, opt-in).
 *
 * The supervisor historically knew ONE kind of child: a worker. It
 * reaped by pid, and every non-worker was an untyped "helper death is
 * fatal" check against three pids. That model cannot carry the NUMA
 * route, where indexer, scanner, fallow, ingest and orderer exist as
 * separate processes with DIFFERENT recovery policies, and a worker's
 * identity is (wid, incarnation, logical node), not a pid.
 *
 * This registry is that model. It is INERT unless
 * FORKRUN_SUPERVISE_TYPED=1 is set; the production cleanroom path is
 * byte-for-byte unchanged when the variable is absent.
 *
 * Exit-gate rules encoded here:
 *  1. Every family has an explicit policy; there is no default role.
 *  2. A death note is acted on only when (role, pid, incarnation)
 *     matches the CURRENT registered generation. A stale note is
 *     logged and dropped -- it must never reach a replacement. Creating
 *     a death pipe is not supervision; reconciling its identity against
 *     the registry is.
 *  3. Workers stay recoverable and respawn onto the SAME wid and
 *     logical node with incarnation+1. Helpers are NOT recoverable:
 *     re-forking one would resume with a different pipeline generation
 *     and no re-execution capability, which W-EXP-2 forbids inventing.
 *  4. Teardown is bounded by SUP_REAP_BUDGET_MS and reports leftovers.
 *
 * Only ONE helper process exists in this step: the sentinel forked by
 * sup_fork_helper(). Wiring the real pipeline helpers through this
 * registry is step C, after the harness in
 * python/tests/test_supervision_substrate.py proves the transitions.
 * ===================================================================== */

enum sup_role {
    SUP_ROLE_WORKER = 0,
    SUP_ROLE_ORDERER,
    SUP_ROLE_INDEXER,
    SUP_ROLE_SCANNER,
    SUP_ROLE_FALLOW,
    SUP_ROLE_INGEST,
    SUP_ROLE_DRAIN,
    SUP_ROLE__COUNT
};

/* Exit status zero is NOT proof that a helper finished its pipeline
 * work. Each role declares when a clean exit is expected:
 *
 *   EOF       clean exit is a normal terminal condition at any stage
 *             (ingest: source EOF).
 *   TEARDOWN  clean exit is expected only after the supervisor has begun
 *             its completion phase (`g_sup_stopping`). Before that, an
 *             exit 0 is an unexpected early exit and is FATAL.
 *   NEVER     the role is worker-style: clean exit means the generation
 *             completed its work and the recoverable branch owns it.
 *
 * The pre-C choice for orderer/indexer/scanner is deliberately the strict
 * TEARDOWN window. Their legitimate completion happens before teardown,
 * but the launcher cannot yet prove the completion stage for them; Step C
 * must add the per-role completion handshake (EOF published / orderer
 * input closed) BEFORE relaxing those windows. Encoding the strict rule
 * now means a mismatched clean exit fails loudly instead of passing on
 * exit status alone. */
enum sup_clean_window {
    SUP_CLEAN_NEVER = 0,
    SUP_CLEAN_AT_EOF,
    /* The per-node families: the GLOBAL ingest-EOF marker is not their
     * completion signal. An indexer's node must have consumed every
     * chunk published for it, and a scanner's node must have published
     * its final ring state. */
    SUP_CLEAN_AT_NODE_COMPLETE,
    SUP_CLEAN_AT_TEARDOWN
};

struct sup_policy {
    const char *name;
    int recoverable;    /* 1: supervisor owns recovery and respawn      */
    int node_scoped;    /* 1: identity carries a logical NUMA node      */
    enum sup_clean_window clean;
};

static const char *sup_clean_name(enum sup_clean_window w) {
    switch (w) {
    case SUP_CLEAN_AT_EOF:      return "eof";
    case SUP_CLEAN_AT_NODE_COMPLETE: return "node-complete";
    case SUP_CLEAN_AT_TEARDOWN: return "teardown";
    default:                    return "never";
    }
}

static const struct sup_policy g_sup_policy[SUP_ROLE__COUNT] = {
    [SUP_ROLE_WORKER]  = { "worker",  1, 1, SUP_CLEAN_NEVER },
    [SUP_ROLE_ORDERER] = { "orderer", 0, 0, SUP_CLEAN_AT_TEARDOWN },
    /* Step C follow-up: indexer/scanner complete on their OWN node's
     * state, not on the global ingest-EOF marker. The marker says the
     * SOURCE was consumed; it does not say this node's indexer consumed
     * its chunks, nor that this node's scanner published its final
     * ring state. A clean exit with the marker set but the node short
     * is a lost chunk, and treating it as healthy turns it into a
     * hang. */
    [SUP_ROLE_INDEXER] = { "indexer", 0, 0, SUP_CLEAN_AT_NODE_COMPLETE },
    [SUP_ROLE_SCANNER] = { "scanner", 0, 0, SUP_CLEAN_AT_NODE_COMPLETE },
    [SUP_ROLE_FALLOW]  = { "fallow",  0, 0, SUP_CLEAN_AT_TEARDOWN },
    [SUP_ROLE_INGEST]  = { "ingest",  0, 0, SUP_CLEAN_AT_EOF },
    [SUP_ROLE_DRAIN]   = { "drain",   0, 0, SUP_CLEAN_AT_TEARDOWN },
};

/* Explicit supported ceiling. The registry itself is sized from the
 * requested topology (workers + helpers); this only bounds absurd
 * requests before anything is forked. 512 workers + 2*nodes helpers is
 * well inside it for the engine's 512-node ceiling. */
#define SUP_MAX_PROCS_HARD 8192
#define SUP_NOTE_MAGIC    0x53555042u   /* "SUPB" */
#define SUP_REAP_BUDGET_MS 2000
/* A clean exit is only expected when the child also published the
 * completion event its role ends on. The flag rides the same note as
 * the death identity, so it is checked against the CURRENT registered
 * (role, pid, incarnation) -- a stale process cannot assert completion
 * for its replacement.
 *
 * This is a TEST MODEL for Step B. Step C must connect real ingest
 * completion to the engine's EOF condition (fr_py_ingest_eof_posted),
 * not to a child's self-report or to launcher teardown. */
#define SUP_NOTE_COMPLETE 0x1u

struct sup_note {
    uint32_t magic;
    uint32_t role;
    int32_t  pid;
    int32_t  rc;
    uint32_t incarnation;
    uint32_t flags;         /* SUP_NOTE_COMPLETE when completion happened */
};

struct sup_proc {
    int active;
    enum sup_role role;
    int wid;                /* worker slot, -1 for helpers */
    int logical_node;       /* worker node, -1 for whole-run helpers */
    pid_t pid;
    unsigned incarnation;
    int note_fd;            /* death-note read end; helpers only */
    int exit_known;
    int exit_rc;
    int completion_evidence;
};

static int g_sup_on;
static int g_sup_bad;
static int g_sup_stopping;
static int g_sup_max;
static int g_sup_ctl_w = -1;
static struct sup_proc *g_sup;
static int g_sup_n;

/* force: NUMA cannot be supervised by the flat pid table, so the typed
 * registry is mandatory there regardless of the opt-in hook. UMA keeps
 * the hook (production byte-for-byte unchanged). required: exact number
 * of entries this configuration can register. */
static void sup_init(int force, int required) {
    const char *on = getenv("FORKRUN_SUPERVISE_TYPED");
    g_sup_on = force || (on != NULL && on[0] != '\0' &&
                         strcmp(on, "0") != 0);
    if (!g_sup_on)
        return;
    g_sup_n = 0;
    g_sup_bad = 0;
    g_sup_max = required;
    /* Test-only cap on NEW slot allocations. It can only LOWER the
     * configured bound; values outside [2, required] are ignored. */
    {
        const char *cap = getenv("FORKRUN_TEST_SUP_MAX");
        if (cap != NULL) {
            long v = strtol(cap, NULL, 10);
            if (v >= 2 && v <= required)
                g_sup_max = (int)v;
        }
    }
    g_sup = calloc((size_t)g_sup_max, sizeof *g_sup);
    if (!g_sup)
        die("calloc(supervision registry)");
    fprintf(stderr, "forkrun-sup: capacity entries=%d required=%d\n",
            g_sup_max, required);
    for (int r = 0; r < SUP_ROLE__COUNT; r++)
        fprintf(stderr,
                "forkrun-sup: policy role=%s recoverable=%d node_scoped=%d "
                "clean_window=%s\n",
                g_sup_policy[r].name, g_sup_policy[r].recoverable,
                g_sup_policy[r].node_scoped,
                sup_clean_name(g_sup_policy[r].clean));
}

static struct sup_proc *sup_find_pid(pid_t pid) {
    for (int i = 0; i < g_sup_n; i++)
        if (g_sup[i].active && g_sup[i].pid == pid)
            return &g_sup[i];
    return NULL;
}

static void sup_retire(struct sup_proc *e) {
    if (e->note_fd >= 0) {
        close(e->note_fd);
        e->note_fd = -1;
    }
    e->active = 0;
}

/* Strict identity reconciliation, shared by the pipe path and by the
 * harness's stale-note injection. Returns 1 only for the generation
 * that is registered RIGHT NOW. */
static int sup_reconcile_note(const struct sup_note *n) {
    struct sup_proc *e = sup_find_pid(n->pid);
    const char *cur = e ? g_sup_policy[e->role].name : "none";
    if (!e || e->role != (enum sup_role)n->role ||
        e->incarnation != n->incarnation) {
        fprintf(stderr,
                "forkrun-sup: stale note role=%s pid=%d incarnation=%u "
                "(current role=%s pid=%d incarnation=%u) -- ignored\n",
                n->role < SUP_ROLE__COUNT ? g_sup_policy[n->role].name : "?",
                (int)n->pid, n->incarnation, cur,
                e ? (int)e->pid : -1, e ? e->incarnation : 0u);
        return 0;
    }
    e->exit_known = 1;
    e->exit_rc = n->rc;
    if (n->flags & SUP_NOTE_COMPLETE)
        e->completion_evidence = 1;
    return 1;
}

/* The engine-backed completion evidence for ONE helper.
 *
 * Each role has its OWN condition, and the per-node families are
 * keyed to the node they were registered under:
 *
 *   ingest   -- the global ingest-EOF marker (the source was consumed).
 *   indexer  -- this node's chunk frontier has caught up with the
 *               chunks published for it, AND the global marker is set
 *               (so no further chunk can arrive).
 *   scanner  -- this node's scanner_finished flag, published after its
 *               final ring state.
 *
 * A -1 from an accessor means "no verdict", and is never read as
 * "complete": an unavailable verdict is an absent one.
 *
 * The test-only hook can withhold evidence, which models the case the
 * evidence exists to catch: a helper that exited cleanly while its own
 * work was unfinished. It can only WITHHOLD -- never manufacture. */
static int sup_completion_evidence(struct sup_proc *e) {
    if (getenv("FORKRUN_TEST_NO_EOF_EVIDENCE") != NULL)
        return 0;
    switch (e->role) {
    case SUP_ROLE_INGEST:
        return p_eof_posted != NULL && p_eof_posted() == 1;
    case SUP_ROLE_INDEXER:
        return p_index_complete != NULL
               && p_index_complete(e->logical_node) == 1;
    case SUP_ROLE_SCANNER:
        return p_scan_complete != NULL
               && p_scan_complete(e->logical_node) == 1;
    default:
        return 0;
    }
}

/* Apply the family policy. Helpers are fatal when they die abnormally;
 * a clean helper exit is treated as normal completion (scanner EOF is
 * the reference case) and is left to the caller's join. */
static int sup_apply_policy(struct sup_proc *e, int status, int have_status) {
    const struct sup_policy *pol = &g_sup_policy[e->role];
    int clean = have_status
        ? (WIFEXITED(status) && WEXITSTATUS(status) == 0)
        : (e->exit_known && e->exit_rc == 0);
    /* Exit 0 is acceptable only with evidence for the role's declared
     * terminus. An EOF role must have published its completion event;
     * a teardown role must be exiting after teardown began. Status zero
     * alone proves neither. Workers are outside this rule: their clean
     * exit is normal completion owned by the recoverable branch. */
    /* Engine-backed completion for the real EOF families. The note flag
     * remains the sentinel's TEST MODEL; a real ingest/indexer/scanner
     * has no note pipe, so its acceptance is decided by the engine's
     * ingest_eof sentinel, exactly as the in-process reactor does
     * (_watch_numa_pipeline). Exit status alone is never evidence. */
    if ((pol->clean == SUP_CLEAN_AT_EOF
         || pol->clean == SUP_CLEAN_AT_NODE_COMPLETE)
        && !e->completion_evidence && sup_completion_evidence(e))
        e->completion_evidence = 1;
    int acceptable;
    if (pol->clean == SUP_CLEAN_AT_EOF
        || pol->clean == SUP_CLEAN_AT_NODE_COMPLETE)
        acceptable = clean && e->completion_evidence;
    else if (pol->clean == SUP_CLEAN_AT_TEARDOWN)
        acceptable = clean && g_sup_stopping;
    else
        acceptable = clean;
    fprintf(stderr,
            "forkrun-sup: death role=%s wid=%d node=%d pid=%d incarnation=%u "
            "status=%d class=%s recoverable=%d clean_window=%s evidence=%d\n",
            pol->name, e->wid, e->logical_node, (int)e->pid, e->incarnation,
            have_status ? death_cause(status) : e->exit_rc,
            clean ? "clean" : "abnormal", pol->recoverable,
            sup_clean_name(pol->clean), e->completion_evidence);
    /* NEVER-role clean exits are already acceptable above, so only a
     * helper that missed its evidence/window can reach this. */
    if (clean && !acceptable) {
        if (pol->clean == SUP_CLEAN_AT_NODE_COMPLETE)
            fprintf(stderr,
                    "forkrun-sup: role=%s node=%d exited 0 without "
                    "node-completion evidence -- treating as abnormal\n",
                    pol->name, e->logical_node);
        else if (pol->clean == SUP_CLEAN_AT_EOF && e->role == SUP_ROLE_INGEST)
            fprintf(stderr,
                    "forkrun-sup: role=%s exited 0 without ingest-completion "
                    "evidence -- treating as abnormal\n", pol->name);
        else if (pol->clean == SUP_CLEAN_AT_EOF)
            fprintf(stderr,
                    "forkrun-sup: role=%s exited 0 without completion "
                    "evidence (ingest EOF was never posted) -- treating as "
                    "abnormal\n", pol->name);
        else
            fprintf(stderr,
                    "forkrun-sup: role=%s exited 0 before its completion "
                    "window (%s) -- treating as abnormal\n",
                    pol->name, sup_clean_name(pol->clean));
    }
    if (pol->recoverable || acceptable)
        return 0;
    fprintf(stderr,
            "forkrun-sup: role=%s is not recoverable -- aborting the run\n",
            pol->name);
    if (p_abort)
        p_abort();
    g_sup_bad = 1;
    return 1;
}

/* Register a real helper family. note_fd < 0 means the family has no
 * death-note channel: waitpid() plus the engine evidence is the
 * authority, which is why the identity is still (role, pid). Helper
 * entries are never reused (respawn applies only to workers). */
static void sup_register_helper(enum sup_role role, pid_t pid, int node,
                                int note_fd) {
    struct sup_proc *e;
    if (!g_sup_on)
        return;
    if (g_sup_n >= g_sup_max) {
        /* Exact sizing runs before any fork; reaching this is an
         * internal bookkeeping error, not a user configuration. */
        fprintf(stderr, "forkrun-sup: internal error: capacity %d "
                        "exhausted registering role=%s\n",
                g_sup_max, g_sup_policy[role].name);
        die("supervision registry full");
    }
    e = &g_sup[g_sup_n++];
    memset(e, 0, sizeof *e);
    e->active = 1;
    e->role = role;
    e->wid = -1;
    e->logical_node = node;
    e->pid = pid;
    e->incarnation = 0;
    e->note_fd = note_fd;
    fprintf(stderr,
            "forkrun-sup: register role=%s wid=-1 node=%d pid=%d "
            "incarnation=0\n", g_sup_policy[role].name, node, (int)pid);
}

static void sup_register_worker(int wid, unsigned incarnation, pid_t pid,
                                int node) {
    struct sup_proc *e = NULL;
    if (!g_sup_on)
        return;
    /* One CURRENT entry per worker slot, reused across generations.
     * A respawn must not consume a new slot: with 512 workers the
     * registry would otherwise exhaust on the eighth respawn overall.
     * Only worker entries are eligible for this reuse, so a helper
     * registration can never be overwritten. */
    for (int i = 0; i < g_sup_n; i++)
        if (g_sup[i].role == SUP_ROLE_WORKER && g_sup[i].wid == wid)
            e = &g_sup[i];
    if (!e) {
        if (g_sup_n >= g_sup_max)
            die("supervision registry full");
        e = &g_sup[g_sup_n++];
        memset(e, 0, sizeof *e);
        e->active = 1;
        e->role = SUP_ROLE_WORKER;
        e->wid = wid;
        e->note_fd = -1;
    } else if (e->active) {
        /* A live generation must be reaped and retired before its slot
         * is reused. Silently overwriting one would hide a bookkeeping
         * bug and lose the old generation's identity. */
        fprintf(stderr,
                "forkrun-sup: internal error: wid=%d still registered "
                "(pid=%d) at respawn -- refusing to overwrite\n",
                wid, (int)e->pid);
        die("supervision re-registered a live worker");
    } else {
        fprintf(stderr,
                "forkrun-sup: reuse role=worker wid=%d slot=%d "
                "generation=%u\n",
                wid, (int)(e - g_sup), incarnation);
    }
    e->active = 1;
    e->pid = pid;
    e->incarnation = incarnation;
    e->logical_node = node;
    e->exit_known = 0;
    e->exit_rc = 0;
    e->completion_evidence = 0;
    fprintf(stderr,
            "forkrun-sup: register role=worker wid=%d node=%d pid=%d "
            "incarnation=%u\n", wid, node, (int)pid, incarnation);
}

/* Reconcile a worker reap against the registry. The wait status is the
 * authority for reaping; this only records whether the identity the
 * supervisor believed in is the one that actually died. */
static void sup_reconcile_worker_reap(int wid, pid_t pid,
                                      unsigned incarnation, int status) {
    struct sup_proc *e;
    if (!g_sup_on)
        return;
    e = sup_find_pid(pid);
    if (!e || e->role != SUP_ROLE_WORKER || e->wid != wid ||
        e->incarnation != incarnation) {
        fprintf(stderr,
                "forkrun-sup: stale worker reap wid=%d pid=%d incarnation=%u "
                "-- ignored\n", wid, (int)pid, incarnation);
        return;
    }
    (void)sup_apply_policy(e, status, 1);
    sup_retire(e);
}

/* Read and reconcile one helper's death channel. A note that does not
 * match the current generation is dropped (never applied to a
 * replacement); EOF without a note means the child died without a
 * statement, and waitpid alone classifies it. */
/* Consume a pending note without reaping. Safe to call after the
 * catch-all waitpid has already reaped the child: the pipe write
 * happened-before the exit, so the data is still readable. */
static int sup_take_note(struct sup_proc *e) {
    struct pollfd pf;
    struct sup_note n;
    ssize_t r;
    int pr;

    if (!e->active || e->note_fd < 0)
        return 0;
    pf.fd = e->note_fd;
    pf.events = POLLIN;
    pf.revents = 0;
    pr = poll(&pf, 1, 0);
    if (pr <= 0 || !(pf.revents & (POLLIN | POLLHUP | POLLERR)))
        return 0;
    r = read(e->note_fd, &n, sizeof n);
    if (r == (ssize_t)sizeof n && n.magic == SUP_NOTE_MAGIC)
        (void)sup_reconcile_note(&n);
    return 1;
}

static int sup_process_note(struct sup_proc *e, int block_ms) {
    struct pollfd pf;
    int pr, st = 0;
    pid_t w;

    if (!e->active || e->note_fd < 0)
        return 0;
    pf.fd = e->note_fd;
    pf.events = POLLIN;
    pf.revents = 0;
    pr = poll(&pf, 1, block_ms);
    if (pr <= 0)
        return 0;
    if (!(pf.revents & (POLLIN | POLLHUP | POLLERR)))
        return 0;
    (void)sup_take_note(e);
    w = waitpid(e->pid, &st, WNOHANG);
    if (w == e->pid) {
        (void)sup_apply_policy(e, st, 1);
        sup_retire(e);
        return 1;
    }
    if (w < 0 && errno == ECHILD)
        return 1;               /* reaped by the catch-all waitpid */
    /* Waitability lags the write-end close by microseconds; yield
     * rather than spin on the still-readable EOF. */
    usleep(1000);
    return 1;
}

static int sup_sweep(void) {
    int did = 0;
    if (!g_sup_on)
        return 0;
    for (int i = 0; i < g_sup_n; i++)
        if (g_sup[i].active)
            did |= sup_process_note(&g_sup[i], 0);
    return did;
}

/* Block briefly on the registered death channels. The hook-mode
 * supervision loop uses this when waitpid(-1, WNOHANG) found nothing,
 * so a helper death is acted on without waiting for an unrelated
 * worker to move. */
static int sup_wait_note(int ms) {
    if (!g_sup_on)
        return 0;
    for (int i = 0; i < g_sup_n; i++)
        if (g_sup[i].active && g_sup[i].note_fd >= 0)
            return sup_process_note(&g_sup[i], ms);
    usleep((useconds_t)ms * 1000u);
    return 0;
}

/* The sentinel helper is the only pipeline helper the launcher forks in
 * this step. It is a REAL process registered under a real policy
 * (INGEST): SIGKILL produces pipe EOF and no note, which the parent
 * must classify as an abnormal, non-recoverable family death. It exits
 * cleanly only when the launcher closes the control pipe at teardown,
 * which also proves descriptor ownership: if any worker had inherited
 * the write end, the sentinel would never see EOF. */
/* TEST-ONLY: make a per-node helper exit 0 as soon as the GLOBAL
 * ingest-EOF marker is published, while its own node is still short.
 *
 * This is the dangerous shape the policy has to reject: the source is
 * consumed, the helper exits cleanly, and the node's work is NOT done.
 * The child prints the state it observed, so the test can PROVE the
 * setup (marker set, node incomplete) instead of assuming it.
 *
 * The hook names one (role, node) pair, so the OTHER node's helpers
 * run normally and the run has a real reference to compare against.
 * Inert unless the variable is set. */
static int sup_early_clean_for(const char *role, int node) {
    const char *spec = getenv("FORKRUN_TEST_EARLY_CLEAN");
    char want[64];
    if (!spec || !spec[0])
        return 0;
    snprintf(want, sizeof want, "%s:%d", role, node);
    return strcmp(spec, want) == 0;
}

/* Wait (bounded) for the global ingest-EOF marker, then report the
 * observed state and exit 0 WITHOUT doing this node's work. */
static void sup_early_clean_exit(const char *role, int node) {
    int eof = 0;
    int complete = -1;
    for (int i = 0; i < 5000; i++) {
        if (p_eof_posted && p_eof_posted() == 1) { eof = 1; break; }
        usleep(1000);
    }
    if (role && strcmp(role, "indexer") == 0 && p_index_complete)
        complete = p_index_complete(node);
    else if (role && strcmp(role, "scanner") == 0 && p_scan_complete)
        complete = p_scan_complete(node);
    fprintf(stderr,
            "forkrun-sup: early-clean role=%s node=%d eof_posted=%d "
            "node_complete=%d\n", role, node, eof, complete);
    fflush(stderr);
    _exit(0);
}

static void sup_sentinel_child(int ctl_r, int note_w, unsigned incarnation,
                               enum sup_role role, int early_clean) {
    struct sup_note n;
    char c;
    die_with_parent();
    cr_keep k;
    keep_init(&k);
    keep_add(&k, ctl_r);
    keep_add(&k, note_w);
    enter_child("sup-helper", &k);
    if (early_clean) {
        /* Test-only: an exit 0 OUTSIDE the role's completion window.
         * The parent must classify this as abnormal despite the status,
         * which is the policy distinction the review asked to encode. */
        usleep(100000);
    } else {
        for (;;) {
            ssize_t rd = read(ctl_r, &c, 1);
            if (rd < 0 && errno == EINTR)
                continue;
            break;
        }
    }
    memset(&n, 0, sizeof n);
    n.magic = SUP_NOTE_MAGIC;
    n.role = (uint32_t)role;
    n.pid = (int32_t)getpid();
    n.rc = 0;
    n.incarnation = incarnation;
    /* Modeled ingest completion: the control pipe is this helper's
     * source, so its EOF is the completion event. `early_clean` models
     * a process that exits 0 WITHOUT that event -- the case the
     * supervisor must reject. Step C replaces this self-report with
     * engine-backed EOF evidence. */
    n.flags = early_clean ? 0u : (uint32_t)SUP_NOTE_COMPLETE;
    (void)write(note_w, &n, sizeof n);
    _exit(0);
}

static enum sup_role sup_role_from_name(const char *name) {
    for (int r = 0; r < SUP_ROLE__COUNT; r++)
        if (strcmp(name, g_sup_policy[r].name) == 0)
            return (enum sup_role)r;
    return SUP_ROLE_INGEST;
}

static void sup_fork_helper(void) {
    int ctl[2], note[2];
    pid_t p;
    struct sup_proc *e;
    enum sup_role role = SUP_ROLE_INGEST;
    int early_clean = 0;
    const char *role_env = getenv("FORKRUN_TEST_HELPER_ROLE");

    if (!g_sup_on)
        return;
    if (role_env != NULL)
        role = sup_role_from_name(role_env);
    early_clean = getenv("FORKRUN_TEST_HELPER_EXIT_CLEAN_EARLY") != NULL;
    if (pipe2(ctl, O_CLOEXEC) != 0)
        die("pipe2(sup ctl)");
    if (pipe2(note, O_CLOEXEC) != 0)
        die("pipe2(sup note)");
    p = fork();
    if (p < 0)
        die("fork(sup helper)");
    if (p == 0) {
        close(ctl[1]);
        close(note[0]);
        sup_sentinel_child(ctl[0], note[1], 0, role, early_clean);
        _exit(127);
    }
    close(ctl[0]);
    close(note[1]);
    g_sup_ctl_w = ctl[1];
    if (g_sup_n >= g_sup_max)
        die("supervision registry full");
    e = &g_sup[g_sup_n++];
    memset(e, 0, sizeof *e);
    e->active = 1;
    e->role = role;
    e->wid = -1;
    e->logical_node = -1;
    e->pid = p;
    e->incarnation = 0;
    e->note_fd = note[0];
    fprintf(stderr,
            "forkrun-sup: register role=%s wid=-1 node=-1 pid=%d "
            "incarnation=0\n", g_sup_policy[role].name, (int)p);
}

static int sup_helper_active(void) {
    for (int i = 0; i < g_sup_n; i++)
        if (g_sup[i].active && g_sup[i].role != SUP_ROLE_WORKER)
            return 1;
    return 0;
}

/* Bounded, one-shot guillotine for helper families. Workers are owned
 * by kill_all(); this only addresses the registry's helpers. Reports
 * leftovers rather than waiting forever. */
static void sup_guillotine(void) {
    long t0;
    int signalled = 0, reaped = 0;
    if (!g_sup_on)
        return;
    g_sup_stopping = 1;
    if (g_sup_ctl_w >= 0) {
        close(g_sup_ctl_w);
        g_sup_ctl_w = -1;
    }
    for (int i = 0; i < g_sup_n; i++)
        if (g_sup[i].active && g_sup[i].role != SUP_ROLE_WORKER) {
            (void)kill(g_sup[i].pid, SIGKILL);
            signalled++;
        }
    t0 = now_ns();
    for (int round = 0; round < SUP_REAP_BUDGET_MS / 10; round++) {
        int live = 0;
        for (int i = 0; i < g_sup_n; i++) {
            struct sup_proc *e = &g_sup[i];
            int st = 0;
            pid_t w;
            if (!e->active || e->role == SUP_ROLE_WORKER)
                continue;
            w = waitpid(e->pid, &st, WNOHANG);
            if (w == e->pid || (w < 0 && errno == ECHILD)) {
                sup_retire(e);
                reaped++;
            } else {
                live++;
            }
        }
        if (!live)
            break;
        usleep(10000);
    }
    fprintf(stderr,
            "forkrun-sup: guillotine signalled=%d reaped=%d leftover=%d "
            "ms=%.1f\n", signalled, reaped, sup_helper_active(),
            (double)(now_ns() - t0) / 1e6);
}

/* Success-path helper stop: close the control channel, wait for the
 * sentinel's clean exit and note within the budget, and fall back to
 * the guillotine if it will not go. A helper that refuses to exit is a
 * descriptor-ownership bug, so it is reported as fatal for the run. */
static int sup_stop_helpers(void) {
    if (!g_sup_on)
        return 0;
    g_sup_stopping = 1;
    if (g_sup_ctl_w >= 0) {
        close(g_sup_ctl_w);
        g_sup_ctl_w = -1;
    }
    for (int round = 0; round < SUP_REAP_BUDGET_MS / 10; round++) {
        if (!sup_helper_active())
            return 0;
        (void)sup_sweep();
        if (!sup_helper_active())
            return 0;
        usleep(10000);
    }
    fprintf(stderr,
            "forkrun-sup: helper survived control EOF past the reap budget "
            "-- guillotine\n");
    sup_guillotine();
    return sup_helper_active() ? -1 : 0;
}

/* Join one registered helper and apply its policy if the supervision
 * loop had not already reaped it. ECHILD therefore means "already
 * classified"; a fatal classification would have taken the bad path. */
static void sup_join_helper(pid_t pid, int *bad) {
    int st = 0;
    pid_t w;
    struct sup_proc *e;
    if (pid <= 0)
        return;
    w = waitpid(pid, &st, 0);
    if (w != pid) {
        if (w < 0 && errno == ECHILD)
            return;
        *bad = 1;
        return;
    }
    e = sup_find_pid(pid);
    if (e) {
        if (sup_apply_policy(e, st, 1))
            *bad = 1;
        sup_retire(e);
    } else if (!(WIFEXITED(st) && WEXITSTATUS(st) == 0)) {
        *bad = 1;
    }
}

static pid_t spawn_wid(int wid, int memfd, int out_fd, int sig_w,
                       int fall_w, int order_w,
                       fn_worker_plugin_loop wloop,
                       fn_worker_plugin_loop_numa wnuma,
                       fn_worker_spawn_loop s_wloop,
                       const worker_desc *desc,
                       int retry_limit, int on_error,
                       const int *engine_fd, int n_engine,
                       int wincarn, int node) {
    fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_FORK_REQUEST,
                  (int32_t)wid, (int32_t)wincarn, 0, 0);
    pid_t p = fr_fork();
    if (p < 0)
        return UDF_SETUP_GENERIC;
    if (p == 0) {
        /* Stage 3: the worker becomes a PROCESS GROUP LEADER, so the
         * launcher can signal the whole group on worker death. A SIGKILLed
         * worker whose command had spawned children would otherwise leave
         * them orphaned and running.
         *
         * Option A contract: cleanup covers the command and descendants
         * that REMAIN in this group. A descendant that calls setsid() or
         * otherwise leaves is explicitly outside the guarantee -- a
         * subreaper would make such a process waitable but would not kill
         * it, so promising universal descendant cleanup would be a lie.
         * That boundary is tested rather than left implied. */
        setpgid(0, 0);
        die_with_parent();
        cr_keep k;
        keep_init(&k);
        keep_add(&k, memfd); keep_add(&k, out_fd);
        keep_add(&k, sig_w);  keep_add(&k, fall_w);
        if (order_w >= 0) keep_add(&k, order_w);
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
        if (!desc) _exit(70);
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
        int rc = fr_run_worker(desc, wloop, s_wloop, wnuma, wid,
                               memfd, out_fd, sig_w, fall_w, order_w,
                               -1, wincarn, retry_limit, on_error, node);
        if (rc < 0)
            _exit(70);   /* no loop for this mode -- infrastructure */
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

/* Stage 3: kill a WORKER's whole process group, not just the worker.
 *
 * Workers call setpgid(0,0) in the child, so pgid == worker pid and the
 * negative-pid form addresses exactly this worker's descendants.
 *
 * Applied ONLY to worker slots. The spill, scanner, fallow and drain
 * children are NOT group leaders, and signalling -pid for one of those
 * would target whatever group happens to carry that id -- a different,
 * unrelated process tree. So this is deliberately a separate function
 * from kill_slot() rather than a flag on it.
 *
 * Orphan scenario this prevents: the worker's command forks a long-lived
 * child, then the worker is SIGKILLed. The child is reparented and keeps
 * running, and nothing in the run can ever observe it again. */
static void kill_worker_group(pid_t pid) {
    if (pid > 0) {
        fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_FATAL_KILL,
                      FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)pid);
        /* Group first: descendants must die even if the leader has
         * already exited and been reaped, since kill(-pgid) still works
         * while the group has members.
         *
         * Takes the pid BY VALUE on purpose. It previously took the slot
         * pointer, and the supervision loop cleared pids[wid] = -1 as
         * soon as it reaped the worker -- BEFORE calling this. The
         * helper's own guard then refused to act, so the group signal was
         * a silent no-op in both the fail-fast and recovery branches and
         * the command's child survived a worker death the supervisor had
         * already observed. Passing the value makes the ordering
         * mistake impossible rather than merely unlikely. */
        (void)kill(-pid, SIGKILL);
        (void)kill(pid, SIGKILL);
    }
}

/* Reap every child that has already exited, without waiting for one
 * that has not. The fatal path needs this AFTER it has signalled the
 * workers: a SIGKILLed worker is reapable a moment later, and exiting
 * before reaping leaves it as a zombie that outlives the launcher --
 * a "descendant survived the run" observation for a process that was
 * in fact already dead.
 *
 * Bounded by construction: the loop gives up after a fixed number of
 * passes and never blocks, so a child wedged in uninterruptible sleep
 * cannot hold the teardown open. */
static void reap_all_bounded(void) {
    for (int spin = 0; spin < 200; spin++) {
        int st = 0;
        pid_t p = waitpid(-1, &st, WNOHANG);
        if (p > 0)
            continue;
        if (p < 0 && errno == EINTR)
            continue;
        {
            struct timespec ts = {0, 1000000L};   /* 1 ms */
            nanosleep(&ts, NULL);
        }
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

        /* STAGE0: synthetic post-recovery drain notification.
 *
 * A worker can commit its batch and die before notifying the drain. That
 * batch IS committed (TXN_IDLE is stored before the notification), but
 * without a wakeup the drain never learns the record is there, so a
 * committed result is stranded forever -- a completeness failure that
 * looks exactly like a clean, short run.
 *
 * After recovery has resolved any rollback, the worker's memfd holds only
 * committed bytes, so its size is a valid committed frontier and the
 * drain can be told to forward up to it.
 *
 * Called ONLY for nonfatal, non-ambiguous outcomes:
 *   rc 0 RECOVERED   rollback truncated the memfd to output_start
 *   rc 1 NO_BATCH    transaction was IDLE; nothing in flight
 *   rc 2 NORMAL_EXIT transaction was IDLE; drained to EOF
 * rc 4 (CLAIMING/COMMITTING, ambiguous) and rc 5 (FATAL) do NOT truncate
 * and are already fatal to the run, so they must never be treated as a
 * committed frontier -- and rc 3 (ALREADY_DONE) does not truncate either,
 * so the conservative choice is to skip it. Publishing a frontier above
 * the committed boundary is precisely the defect Stage 0 removes, so a
 * doubtful case must stay silent rather than guess. */
static int fr_wake_drain_committed(int sig_w, int wid, int out_fd)
{
    uint64_t sig[2];
    off_t frontier;
    size_t left;
    const char *p;

    if (sig_w < 0 || out_fd < 0 || wid < 0)
        return UDF_SETUP_GENERIC;
    frontier = lseek(out_fd, 0, SEEK_END);
    if (frontier == (off_t)-1)
        return UDF_SETUP_GENERIC;
    sig[0] = (uint64_t)wid;
    sig[1] = (uint64_t)frontier;
    p = (const char *)sig;
    left = sizeof(sig);
    while (left > 0) {
        ssize_t n = write(sig_w, p, left);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            return UDF_SETUP_GENERIC;
        }
        if (n == 0)
            return UDF_SETUP_GENERIC;
        p += n;
        left -= (size_t)n;
    }
    return 0;
}

/* =====================================================================
 * TEST-ONLY entry-descriptor probe (F6 Stage 3, condition C4).
 *
 * COMPILE-TIME GUARDED AND OFF BY DEFAULT. The normal launcher build
 * defines nothing, so this code does not exist in the shipped binary:
 * there is no new flag to pass, no new behaviour, and no measurable cost.
 * Only the test build adds -DFORKRUN_ENTRY_FD_PROBE.
 *
 * WHY IT EXISTS. `--fd-selfcheck` runs inside enter_child(), AFTER exec,
 * and only checks that descriptors on the launcher's own keep-list
 * survived the launcher's own scrub. That is the wrong moment for the
 * question "which descriptors was the launcher HANDED", which is exactly
 * what a posix_spawn backend must reproduce. This probe answers it at
 * main() entry, before the launcher touches anything.
 *
 * WHAT IT DOES NOT DO. It never reads or prints the environment: no
 * getenv, no environ walk, nothing that could carry a secret into the
 * report. It reports only descriptor number, the kernel's own readlink
 * of that descriptor, and whether FD_CLOEXEC is set on it. The output
 * path arrives as a command-line argument, not an environment variable,
 * so enabling the probe cannot perturb what it measures.
 * ===================================================================== */
#ifdef FORKRUN_ENTRY_FD_PROBE
static int entry_fd_probe(const char *out_path, const struct opts *o) {
    char line[4096], tgt[PATH_MAX + 1], path[64];
    int fd = open(out_path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return -1;
    dprintf(fd, "# entry descriptor set at main() entry\n");
    dprintf(fd, "# argv --src=%d --result=%d --stats-fd=%d trace=%d\n",
            o->source_fd, o->result_fd, o->stats_fd, o->trace_fd);
    for (int i = 0; i < 4096; i++) {
        int fl = fcntl(i, F_GETFD);
        if (fl == -1) continue;
        snprintf(path, sizeof path, "/proc/self/fd/%d", i);
        ssize_t m = readlink(path, tgt, sizeof tgt - 1);
        if (m < 0) m = 0;
        tgt[m] = '\0';
        dprintf(fd, "FD %d cloexec=%d target=%s\n",
                i, (fl & FD_CLOEXEC) ? 1 : 0, tgt);
    }
    dprintf(fd, "FD -- end\n");
    /* The poison relay fd is reported as the NUMBER the launcher will
     * export, without printing its value: the point is that it equals
     * --stats-fd, which is a relationship, not a secret. */
    dprintf(fd, "POISON_FD_EQUALS_STATS_FD %d\n",
            (o->stats_fd >= 0) ? 1 : 0);
    close(fd);
    return 0;
}
#endif /* FORKRUN_ENTRY_FD_PROBE */

int main(int argc, char **argv) {
    struct opts o;
    memset(&o, 0, sizeof o);
    o.workers = 1; o.source_fd = -1; o.result_fd = -1; o.stats_fd = -1;
    o.drain_mode = 0; o.retry_limit = 3; o.on_error = 0;
    o.respawn_cap = 64;
    o.trace_fd = -1;
    o.supervise = 1;   /* recovering is the historical behaviour */
    o.num_nodes = 1;

#ifdef FORKRUN_ENTRY_FD_PROBE
    /* The parser rejects unrecognised arguments with exit 64, so the
     * probe flag has to be recognised INSIDE the loop rather than after
     * it. Recording the path and acting on it once parsing completes is
     * what makes the report describe a FULLY POPULATED opts -- an early
     * hook would report o.stats_fd == -1 and could not show the
     * poison/stats relationship this probe exists to establish. */
    const char *entry_probe_path = NULL;
#endif

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--so") && i + 1 < argc)        o.so_path = argv[++i];
        else if (!strcmp(argv[i], "--plugin") && i + 1 < argc) o.plugin_path = argv[++i];
        else if (!strcmp(argv[i], "--spawn-argv") && i + 1 < argc) {
            /* Each element stays a distinct argv entry: collected in
             * order into one contiguous vector, never joined and never
             * re-parsed. */
            int cap = o.spawn_argv_cap;
            if (o.spawn_argc + 1 >= cap) {
                cap = cap ? cap * 2 : 8;
                char **grown = realloc(o.spawn_argv,
                                       (size_t)(cap + 1) * sizeof(char *));
                if (!grown) die("realloc(spawn argv)");
                o.spawn_argv = grown;
                o.spawn_argv_cap = cap;
            }
            o.spawn_argv[o.spawn_argc++] = argv[++i];
        }
        else if (!strcmp(argv[i], "--func") && i + 1 < argc) o.plugin_func = argv[++i];
        else if (!strcmp(argv[i], "--udf-helper") && i + 1 < argc) o.udf_helper = argv[++i];
        else if (!strcmp(argv[i], "--udf") && i + 1 < argc) o.udf_module = argv[++i];
        else if (!strcmp(argv[i], "--udf-attr") && i + 1 < argc) o.udf_attr = argv[++i];
        else if (!strcmp(argv[i], "--udf-roots") && i + 1 < argc) o.udf_roots = argv[++i];
        else if (!strncmp(argv[i], "--caller-version=", 17))
            o.caller_version = argv[i] + 17;
        else if (!strcmp(argv[i], "--caller-version") && i + 1 < argc)
            o.caller_version = argv[++i];
        else if (!strcmp(argv[i], "--libpython") && i + 1 < argc)
            o.libpython_path = argv[++i];
        else if (!strncmp(argv[i], "--libpython=", 12))
            o.libpython_path = argv[i] + 12;
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
        else if (!strcmp(argv[i], "--nodes") && i + 1 < argc)
            o.num_nodes = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--numa-map") && i + 1 < argc)
            o.numa_map = argv[++i];
        else if (!strcmp(argv[i], "--order") && i + 1 < argc) {
            const char *m = argv[++i];
            if (!strcmp(m, "none"))       o.order_index = 0;
            else if (!strcmp(m, "index")) o.order_index = 1;
            else { fprintf(stderr, "forkrun-cleanroom: --order must be "
                            "none|index, got %s\n", m); return 64; }
        }
        else if (!strcmp(argv[i], "--supervise") && i + 1 < argc) {
            const char *m = argv[++i];
            if (!strcmp(m, "recover"))        o.supervise = 1;
            else if (!strcmp(m, "fail-fast")) o.supervise = 0;
            else { fprintf(stderr, "forkrun-cleanroom: --supervise must be "
                            "recover|fail-fast, got %s\n", m); return 64; }
        }
#ifdef FORKRUN_ENTRY_FD_PROBE
        else if (!strcmp(argv[i], "--entry-fd-probe") && i + 1 < argc)
            entry_probe_path = argv[++i];
#endif
        else { fprintf(stderr, "forkrun-cleanroom: bad arg %s\n", argv[i]); return 64; }
    }
#ifdef FORKRUN_ENTRY_FD_PROBE
    /* Record the entry descriptor state, then exit without doing any
     * launcher work. Argument parsing above only READS argv, so the
     * descriptors are still exactly as the parent left them. */
    if (entry_probe_path) return entry_fd_probe(entry_probe_path, &o) == 0 ? 0 : 65;
#endif
    if (!o.so_path || o.source_fd < 0) {
        fprintf(stderr, "forkrun-cleanroom: --so --src required\n");
        return 64;
    }
    /* The execution mode is selected by exactly one of three shapes:
     * a C plugin (two strings), a Python UDF (two strings), or a spawn
     * command vector (an argv list). Stage 3 added the third, and it
     * deliberately does NOT reuse the plugin's two-string shape -- that
     * is the whole reason for the worker descriptor. */
    if (!o.plugin_path && !o.udf_module && o.spawn_argc <= 0) {
        fprintf(stderr, "forkrun-cleanroom: one of --plugin, --udf or "
                "--spawn-argv required\n");
        return 64;
    }
    /* Exactly one mode: mixing them would leave the descriptor's union
     * ambiguous, and silently preferring one would run a command the
     * caller did not ask for. */
    {
        int modes = (o.plugin_path != NULL) + (o.udf_module != NULL)
                  + (o.spawn_argc > 0);
        if (modes > 1) {
            fprintf(stderr, "forkrun-cleanroom: --plugin, --udf and "
                    "--spawn-argv are mutually exclusive\n");
            return 64;
        }
    }
    if (o.udf_helper && !o.udf_module) {
        fprintf(stderr, "forkrun-cleanroom: --udf-helper needs --udf\n");
        return 64;
    }
    if (o.plugin_path && o.udf_module) {
        fprintf(stderr, "forkrun-cleanroom: --plugin and --udf are "
                        "mutually exclusive\n");
        return 64;
    }
    if (o.workers < 1) o.workers = 1;

    /* W-EXP-2 step C topology validation. Everything here is checked
     * BEFORE the engine is initialised or any process is forked: a
     * configuration the launcher cannot honour must cost no input. */
    if (o.num_nodes < 1 || o.num_nodes > 512) {
        fprintf(stderr, "forkrun-cleanroom: --nodes must be 1..512, got %d\n",
                o.num_nodes);
        return 64;
    }
    if (o.num_nodes > 1) {
        /* NUMA workers are plugin workers: the node-taking loop exists
         * for that envelope. UDF (W-EXP-1.5) and spawn NUMA are not
         * wired, and silently running them as node 0 would be a lie. */
        if (!o.plugin_path) {
            fprintf(stderr, "forkrun-cleanroom: --nodes > 1 currently "
                            "requires --plugin/--func (no UDF/spawn NUMA)\n");
            return 64;
        }
        if (o.fork_only) {
            fprintf(stderr, "forkrun-cleanroom: --fork-only is UMA-only\n");
            return 64;
        }
        if (!o.numa_map || !o.numa_map[0]) {
            fprintf(stderr, "forkrun-cleanroom: --nodes %d requires "
                            "--numa-map\n", o.num_nodes);
            return 64;
        }
        {
            int entries = 1, digits = 0, bad = 0;
            for (const char *q = o.numa_map; ; q++) {
                if (*q == ',' || *q == '\0') {
                    if (digits == 0) { bad = 1; break; }
                    digits = 0;
                    if (*q == '\0') break;
                    entries++;
                } else if (*q >= '0' && *q <= '9') {
                    if (++digits > 6) { bad = 1; break; }
                } else { bad = 1; break; }
            }
            if (bad || entries != o.num_nodes) {
                fprintf(stderr, "forkrun-cleanroom: --numa-map must hold "
                                "%d comma-separated physical node ids\n",
                        o.num_nodes);
                return 64;
            }
        }
    } else if (o.order_index) {
        fprintf(stderr, "forkrun-cleanroom: --order index requires "
                        "--nodes > 1\n");
        return 64;
    }
    /* The registry is sized from the configuration BEFORE any fork.
     * The target topology is 512 workers + 4 indexers + 4 scanners +
     * fallow + ingest + orderer = 523 entries, so a fixed 520 array
     * would fail halfway through startup. Exact sizing makes that
     * impossible; the hard ceiling is an explicit supported limit
     * rejected up front, never discovered after the pipeline started. */
    {
        int required;
        if (o.num_nodes <= 1) {
            required = o.workers + 1;          /* workers + sentinel */
        } else {
            required = o.workers + o.num_nodes * 2 + 3;
        }
        if (required > SUP_MAX_PROCS_HARD) {
            fprintf(stderr, "forkrun-cleanroom: configuration needs %d "
                            "supervision entries (workers=%d nodes=%d); "
                            "the supported ceiling is %d -- refusing before "
                            "startup\n", required, o.workers, o.num_nodes,
                    SUP_MAX_PROCS_HARD);
            return 66;
        }
        /* The plan is reported BEFORE the worker ceiling is applied, so
         * the sizing model is observable on a configuration that is
         * refused for another reason -- with no process forked at all.
         * A test can then pin the formula exactly instead of only at
         * scale. */
        sup_init(o.num_nodes > 1, required);
        /* The worker ceiling is the ENGINE's (MAX_TXN_WORKERS in
         * forkrun_ring.c): a worker id at or above it is rejected by
         * the engine, so accepting more workers here would only produce
         * a configuration that cannot run. Refused up front, with the
         * count, rather than discovered by a child mid-startup. */
        if (o.workers > 1024) {
            fprintf(stderr, "forkrun-cleanroom: workers=%d exceeds the "
                            "engine's worker ceiling (1024) -- refusing "
                            "before startup\n", o.workers);
            return 64;
        }
    }

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
     *
     * P1-3: skipped entirely in UDF mode. This probe is about the C
     * plugin ABI (does it export forkrun_use_ctx?), which a Python UDF
     * has no concept of; running it with no --plugin would reject the
     * run for a dialect problem that cannot occur. The UDF helper gets
     * its own probe inside setup_udf_helper().
     */
    /* The capability probe applies to a PLUGIN only. It was guarded by
     * "not a UDF", which let a spawn invocation fall through into
     * dlopen(NULL) -- the launcher would have probed a library named
     * "(null)". Now guarded on the plugin actually being present. */
    if (!o.udf_module && o.plugin_path) {
        int pp[2];
        if (pipe(pp) != 0) {
            fprintf(stderr, "forkrun-cleanroom: pipe(probe): %s\n",
                    strerror(errno));
            return 70;
        }
        fr_trace_emit(FR_ROLE_PROBE, FR_EV_FORK_REQUEST,
                      FR_TRACE_NA, FR_TRACE_NA, 0, 0);
        pid_t probe = fr_fork();
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
    g_so_handle = h;
    fn_init                p_init  = (fn_init)                sym(h, "fr_py_init");
    fn_worker_plugin_loop  p_wloop = (fn_worker_plugin_loop)  sym(h, "fr_py_worker_plugin_loop");
    /* The UDF loop takes the SAME argument list as the plugin loop --
     * (path, func_name) reinterpreted as (module, attr) -- so spawn_wid
     * needs no new parameter and the respawn path stays identical. */
    fn_worker_plugin_loop  u_wloop = o.udf_module
        ? (fn_worker_plugin_loop) sym(h, "fr_py_worker_udf_loop") : NULL;
    /* Resolved as its OWN type, never cast to the plugin callback. */
    fn_worker_spawn_loop   s_wloop = o.spawn_argc > 0
        ? (fn_worker_spawn_loop) sym(h, "fr_py_worker_spawn_loop") : NULL;
    fn_scan                p_scan  = (fn_scan)                sym(h, "fr_py_scan");
    fn_ingest_done         p_idone = (fn_ingest_done)         sym(h, "fr_py_ingest_done");
    fn_ingest_data_post    p_ipost = (fn_ingest_data_post)    sym(h, "fr_py_ingest_data_post");
    fn_fallow_loop         p_fall  = (fn_fallow_loop)         sym(h, "fr_py_fallow_loop");
    fn_drain_loop          p_drain = (fn_drain_loop)          sym(h, "fr_py_drain_loop");
    p_recover              = (fn_recover)              sym(h, "fr_py_recover_worker");
    p_abort                = (fn_abort_fn)             sym(h, "fr_py_abort");
    p_abort_reason         = (fn_abort_reason_fn)     sym(h, "fr_py_abort_reason");
    p_poisoned             = (fn_poisoned_count)      sym(h, "fr_py_poisoned_count");
    /* W-EXP-2 Phase A: OPTIONAL. Resolved with dlsym, not sym(), because a
     * missing accessor must mean "no certificate verdict available", not a
     * hard launch failure and certainly not a fabricated zero. A substrate
     * without it simply declines to certify; one WITH it certifies. */
    p_committed = (fn_committed_frames) dlsym(h, "fr_py_committed_data_frames");
    p_c07_enabled = (fn_c07_enabled_fn) dlsym(h, "fr_py_c07_counting_enabled");
    p_abort                = (fn_abort_fn)               sym(h, "fr_py_abort");

    /* W-EXP-2 step C: NUMA entry points. Resolved only for a multi-node
     * run, and REQUIRED there -- falling back to the UMA symbols after
     * --nodes 2 was accepted would run the wrong pipeline with no
     * observable difference in the command line. */
    fn_init_numa         p_init_numa = NULL;
    fn_numa_ingest       p_numa_ingest = NULL;
    fn_indexer_numa      p_indexer = NULL;
    fn_numa_scanner      p_nscanner = NULL;
    fn_fallow_phys       p_fphys = NULL;
    fn_orderer           p_orderer = NULL;
    fn_worker_plugin_loop_numa p_wnuma = NULL;
    int numa = (o.num_nodes > 1);
    if (numa) {
        p_init_numa  = (fn_init_numa)  sym(h, "fr_py_init_numa");
        p_numa_ingest= (fn_numa_ingest)sym(h, "fr_py_numa_ingest");
        p_indexer    = (fn_indexer_numa)sym(h, "fr_py_indexer_numa");
        p_nscanner   = (fn_numa_scanner)sym(h, "fr_py_numa_scanner");
        p_fphys      = (fn_fallow_phys) sym(h, "fr_py_fallow_phys");
        p_orderer    = (fn_orderer)     sym(h, "fr_py_orderer");
        p_wnuma      = (fn_worker_plugin_loop_numa)
                           sym(h, "fr_py_worker_plugin_loop_numa");
        p_eof_posted = (fn_eof_posted)  sym(h, "fr_py_ingest_eof_posted");
        p_index_complete = (fn_node_complete)
                           sym(h, "fr_py_node_index_complete");
        p_scan_complete = (fn_node_complete)
                          sym(h, "fr_py_node_scan_complete");
        if (!p_nscanner || !p_eof_posted || !p_wnuma
            || !p_index_complete || !p_scan_complete) {
            fprintf(stderr, "forkrun-cleanroom: substrate lacks the "
                            "node-taking worker loop or the per-node "
                            "completion evidence -- refusing the NUMA "
                            "route\n");
            return 69;
        }
    }

    /* ---- P1-3: UDF mode ----
     *
     * Load and INITIALISE the interpreter here, before any fork. This is
     * deliberately BEFORE fr_py_init rather than after: the interpreter
     * and the engine are independent, and every fork below inherits
     * both.
     *
     * On failure we return non-zero. run.py treats a non-zero launcher
     * exit as "unavailable for this call", warns, and falls back to the
     * in-process path -- slower and CORRECT, which beats fast and
     * empty. */
    if (o.udf_module) {
        if (!o.udf_helper) {
            fprintf(stderr, "forkrun-cleanroom: --udf needs --udf-helper\n");
            return 64;
        }
        if (!u_wloop) {
            fprintf(stderr, "forkrun-cleanroom: substrate lacks "
                            "fr_py_worker_udf_loop\n");
            return 69;
        }
        {
            int urc = setup_udf_helper(o.udf_helper, o.udf_roots,
                                       o.caller_version, o.source_fd,
                                       o.libpython_path);
            if (urc == UDF_SETUP_VERIFY)      return 80;
            if (urc == UDF_SETUP_INVALID)     return 82;
            if (urc == UDF_SETUP_PROBE_HANG)  return 81;
            if (urc != UDF_SETUP_OK)           return 71;
        }
        /* The loop reinterprets its two strings; nothing else changes. */
        p_wloop = u_wloop;
        o.plugin_path  = o.udf_module;
        o.plugin_func  = o.udf_attr;
    }

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
    {
        int irc = numa
            ? p_init_numa(o.lines, o.bytes, o.num_nodes, o.numa_map)
            : p_init(o.lines, o.bytes);
        if (irc != 0) {
            fprintf(stderr, "forkrun-cleanroom: fr_py_init%s failed\n",
                    numa ? "_numa" : "");
            return 71;
        }
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
    pid_t spill_pid = -1;
    if (!numa) {
    spill_pid = fr_fork();
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
    } else {
        /* NUMA: the ingest OWNS the source and performs placement per
         * chunk. ring_numa_ingest publishes ChunkMeta and propagates
         * EOF internally (ingest_eof), so the launcher must NOT call
         * fr_py_ingest_done. Its clean exit is accepted only after the
         * engine reports EOF posted (sup policy + p_eof_posted). */
        spill_pid = fr_fork();
        if (spill_pid < 0) die("fork(ingest)");
        if (spill_pid == 0) {
            die_with_parent();
            cr_keep k;
            keep_init(&k);
            keep_add(&k, o.source_fd); keep_add(&k, memfd);
            keep_add_engine(&k, engine_fd, n_engine);
            enter_child("ingest", &k);
            {
                int rc = p_numa_ingest(o.source_fd, memfd, o.num_nodes);
                fr_trace_emit(FR_ROLE_SPILL, FR_EV_CHILD_EXIT,
                              FR_TRACE_NA, FR_TRACE_NA, 0, rc);
                _exit(rc == 0 ? 0 : 1);
            }
        }
        fr_trace_emit(FR_ROLE_SPILL, FR_EV_FORK_RETURN,
                      FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)spill_pid);
        sup_register_helper(SUP_ROLE_INGEST, spill_pid, -1, -1);
    }
    close(o.source_fd);      /* only the ingest/spill child reads it */

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
    /* Ordered NUMA collection uses the engine's C orderer; workers ack
     * OrderPackets to orderp[1] instead of signalling the drain. */
    int orderp[2] = {-1, -1};
    if (numa && o.order_index) {
        if (pipe(orderp) != 0) die("pipe(order)");
        (void)fcntl(orderp[1], 1031, 4096);
    }

    pid_t *pids = calloc((size_t)o.workers, sizeof(pid_t));
    if (!pids) die("calloc(pids)");
    int *incarn = calloc((size_t)o.workers, sizeof(int));
    if (!incarn) die("calloc(incarn)");
    for (int i = 0; i < o.workers; i++) pids[i] = -1;
    int live = 0;
    int spill_done = 0;
    /* Same mapping as _numa.wid_to_node: contiguous per-node blocks,
     * round-robin counts. Stable for the run so a respawn keeps its
     * node (and therefore its claim ring and output memfd). */
    int *wid_node = calloc((size_t)o.workers, sizeof(int));
    if (!wid_node) die("calloc(wid_node)");
    {
        int base = o.workers / (numa ? o.num_nodes : 1);
        int rem = o.workers % (numa ? o.num_nodes : 1);
        int at = 0;
        for (int nd = 0; nd < (numa ? o.num_nodes : 1); nd++) {
            int cnt = base + (nd < rem ? 1 : 0);
            for (int k = 0; k < cnt; k++) wid_node[at++] = nd;
        }
    }

    long t0 = now_ns();

    /* fallow reaper child */
    fr_trace_emit(FR_ROLE_FALLOW, FR_EV_FORK_REQUEST,
                  FR_TRACE_NA, FR_TRACE_NA, 0, 0);
    pid_t fallow_pid = -1;
    if (!numa) {
    fallow_pid = fr_fork();
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
    } else {
        fallow_pid = fr_fork();
        if (fallow_pid < 0) die("fork(fallow-phys)");
        if (fallow_pid == 0) {
            die_with_parent();
            cr_keep k;
            keep_init(&k);
            keep_add(&k, fallp[0]); keep_add(&k, memfd);
            keep_add_engine(&k, engine_fd, n_engine);
            enter_child("fallow-phys", &k);
            {
                int rc = p_fphys(fallp[0], memfd);
                fr_trace_emit(FR_ROLE_FALLOW, FR_EV_CHILD_EXIT,
                              FR_TRACE_NA, FR_TRACE_NA, 0, rc);
                _exit(rc == 0 ? 0 : 1);
            }
        }
        fr_trace_emit(FR_ROLE_FALLOW, FR_EV_FORK_RETURN,
                      FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)fallow_pid);
        sup_register_helper(SUP_ROLE_FALLOW, fallow_pid, -1, -1);
    }

    pid_t *idx_pids = NULL;
    pid_t *scan_pids = NULL;
    if (numa) {
        idx_pids = calloc((size_t)o.num_nodes, sizeof(pid_t));
        scan_pids = calloc((size_t)o.num_nodes, sizeof(pid_t));
        if (!idx_pids || !scan_pids) die("calloc(numa helper pids)");
        for (int node = 0; node < o.num_nodes; node++) {
            pid_t ip = fr_fork();
            if (ip < 0) die("fork(indexer)");
            if (ip == 0) {
                die_with_parent();
                cr_keep k;
                keep_init(&k);
                keep_add(&k, memfd);
                keep_add_engine(&k, engine_fd, n_engine);
                enter_child("indexer", &k);
                if (sup_early_clean_for("indexer", node))
                    sup_early_clean_exit("indexer", node);
                _exit(p_indexer(memfd, node) == 0 ? 0 : 1);
            }
            idx_pids[node] = ip;
            sup_register_helper(SUP_ROLE_INDEXER, ip, node, -1);
        }
        for (int node = 0; node < o.num_nodes; node++) {
            pid_t sp = fr_fork();
            if (sp < 0) die("fork(numa-scanner)");
            if (sp == 0) {
                die_with_parent();
                cr_keep k;
                keep_init(&k);
                keep_add(&k, memfd);
                keep_add_engine(&k, engine_fd, n_engine);
                enter_child("numa-scanner", &k);
                if (sup_early_clean_for("scanner", node))
                    sup_early_clean_exit("scanner", node);
                /* spawn_fd = -1: the launcher forks its full worker
                 * complement up front, so it cannot service dynamic
                 * spawn requests. Disarming is the engine's documented
                 * way to run a plain scan. */
                _exit(p_nscanner(memfd, node, -1, o.num_nodes) == 0
                          ? 0 : 1);
            }
            scan_pids[node] = sp;
            sup_register_helper(SUP_ROLE_SCANNER, sp, node, -1);
        }
    }

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

    /* NULL-terminate the collected vector. posix_spawnp and the worker's
     * own argv walk both rely on the terminator, and the descriptor
     * validator checks for it rather than assuming it. */
    if (o.spawn_argv != NULL) {
        if (o.spawn_argc >= o.spawn_argv_cap)
            die("spawn argv capacity");
        o.spawn_argv[o.spawn_argc] = NULL;
    }

    /* The worker descriptor names the mode and carries that mode's own
     * arguments. Validated BEFORE any worker is forked and before the
     * source is read, so an unusable command vector cannot consume
     * input and then fail. */
    worker_desc wd;
    memset(&wd, 0, sizeof wd);
    if (o.spawn_argc > 0) {
        wd.kind = WK_SPAWN;
        wd.argv = o.spawn_argv;
        wd.argc = o.spawn_argc;
    } else if (o.udf_module) {
        wd.kind = WK_UDF;
        wd.a = o.udf_module;
        wd.b = o.udf_attr;
    } else {
        wd.kind = WK_PLUGIN;
        wd.a = o.plugin_path;
        wd.b = o.plugin_func;
    }
    if (fr_validate_worker_desc(&wd) != 0) {
        die("invalid worker arguments");
    }

    /* W-EXP-2 step B/A: the sentinel is the UMA typed-mode test model.
     * A NUMA run has real ingest/indexer/scanner/fallow families, so it
     * registers those instead (and the registry is mandatory). */
    if (!numa)
        sup_fork_helper();

    /* workers */
    for (int i = 0; i < o.workers; i++) {
        pid_t p = spawn_wid(i, memfd, out_fds[i],
                            (numa && o.order_index) ? -1 : sigp[1],
                            fallp[1],
                            (numa && o.order_index) ? orderp[1] : -1,
                            p_wloop, numa ? p_wnuma : NULL, s_wloop, &wd,
                            o.retry_limit, o.on_error,
                            engine_fd, n_engine, /*wincarn=*/0,
                            wid_node[i]);
        if (p < 0) die("fork(worker)");
        pids[i] = p;
        live++;
        sup_register_worker(i, 0, p, wid_node[i]);
    }
    /* Keep a SPARE of the write ends for respawns, exactly as run.py's
     * spare_signal_w does, then drop the originals so EOF still means
     * "every worker is gone". Dropping them unconditionally (as this
     * once did) made every respawn inherit a CLOSED fd: the new worker
     * signalled to EBADF and the drain blocked on the signal pipe
     * forever. The spare is closed LAST, after the supervision loop. */
    /* Stage 3: terminate cleanly enough to honour the process-group
     * guarantee. Installed AFTER the worker table exists so the handler
     * can see it. */
    {
        struct sigaction sa_term;
        memset(&sa_term, 0, sizeof sa_term);
        sa_term.sa_handler = fr_on_terminate;
        sigemptyset(&sa_term.sa_mask);
        (void)sigaction(SIGTERM, &sa_term, NULL);
        (void)sigaction(SIGINT, &sa_term, NULL);
        g_worker_pids = pids;
        g_worker_count = o.workers;
    }

    /* Stage 3: terminate cleanly enough to honour the process-group
     * guarantee. Installed after the worker table exists so the handler
     * can see it. Without it SIGTERM killed the launcher on the default
     * disposition: no teardown, no group signal, and every command
     * descendant abandoned -- contradicting the documented guarantee. */
    {
        struct sigaction sa_term;
        memset(&sa_term, 0, sizeof sa_term);
        sa_term.sa_handler = fr_on_terminate;
        sigemptyset(&sa_term.sa_mask);
        (void)sigaction(SIGTERM, &sa_term, NULL);
        (void)sigaction(SIGINT, &sa_term, NULL);
        g_worker_pids = pids;
        g_worker_count = o.workers;
    }

    int spare_sig = dup(sigp[1]);
    int spare_fall = dup(fallp[1]);
    int spare_order = (numa && o.order_index) ? dup(orderp[1]) : -1;
    if (spare_sig < 0 || spare_fall < 0 ||
        ((numa && o.order_index) && spare_order < 0))
        die("dup(signal/fallow/order)");
    close(sigp[1]);
    close(fallp[1]);
    if (numa && o.order_index)
        close(orderp[1]);

    /* scanner child: pre-flight, ramp, publish */
    fr_trace_emit(FR_ROLE_SCAN, FR_EV_FORK_REQUEST,
                  FR_TRACE_NA, FR_TRACE_NA, 0, 0);
    pid_t scan_pid = -1;
    if (!numa) {
    scan_pid = fr_fork();
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

    /* drain child: move worker output memfds -> result fd.
     * In ordered NUMA mode the C orderer plays this role instead. */
    fr_trace_emit(FR_ROLE_DRAIN, FR_EV_FORK_REQUEST,
                  FR_TRACE_NA, FR_TRACE_NA, 0, 0);
    pid_t drain_pid = -1;
    pid_t order_pid = -1;
    if (!(numa && o.order_index)) {
    drain_pid = fr_fork();
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
    if (numa)
        sup_register_helper(SUP_ROLE_DRAIN, drain_pid, -1, -1);
    } else {
        /* C orderer: writes the globally ordered stream straight to the
         * result fd. It needs every worker output memfd (it reads the
         * payloads named by the OrderPackets) and the engine fds. */
        order_pid = fr_fork();
        if (order_pid < 0) die("fork(orderer)");
        if (order_pid == 0) {
            die_with_parent();
            cr_keep k;
            keep_init(&k);
            keep_add(&k, orderp[0]); keep_add(&k, o.result_fd);
            for (int i = 0; i < o.workers; i++) keep_add(&k, out_fds[i]);
            keep_add_engine(&k, engine_fd, n_engine);
            enter_child("orderer", &k);
            {
                int rc = p_orderer(orderp[0], o.result_fd, 0, 1);
                fr_trace_emit(FR_ROLE_DRAIN, FR_EV_CHILD_EXIT,
                              FR_TRACE_NA, FR_TRACE_NA, 0, rc);
                _exit(rc == 0 ? 0 : 1);
            }
        }
        close(orderp[0]);
        sup_register_helper(SUP_ROLE_ORDERER, order_pid, -1, -1);
        fr_trace_emit(FR_ROLE_DRAIN, FR_EV_FORK_RETURN,
                      FR_TRACE_NA, FR_TRACE_NA, 0, (int32_t)order_pid);
    }

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
        pid_t p;
        if (g_sup_on) {
            (void)sup_sweep();
            if (g_sup_bad) { bad = 1; break; }
            p = waitpid(-1, &st, WNOHANG);
            if (p == 0) {
                /* A short slice keeps note service prompt without
                 * delaying worker reaping: this poll is the only point
                 * at which a worker death waits. 50 ms made every
                 * respawn cost a scheduling quantum (the slot-pressure
                 * regression measured ~28 s for 560 respawns). */
                (void)sup_wait_note(10);
                if (g_sup_bad) { bad = 1; break; }
                continue;
            }
        } else {
            p = waitpid(-1, &st, 0);
        }
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
        if (!numa && p == spill_pid) {
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
            if (g_sup_on) {
                struct sup_proc *se = sup_find_pid(p);
                if (se && se->role != SUP_ROLE_WORKER) {
                    /* The catch-all waitpid can win the race with the
                     * note reader; the write happened-before the exit,
                     * so read it now or completion evidence is lost. */
                    (void)sup_take_note(se);
                    if (sup_apply_policy(se, st, 1))
                        bad = 1;
                    sup_retire(se);
                    if (bad)
                        break;
                    continue;
                }
            }
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
        /* Keep the reaped generation's pid. The slot must stop being
         * live (a reaped pid in pids[wid] overstates the live set and
         * risks signalling a recycled number), but the process GROUP is
         * still addressable as long as any descendant is alive -- and
         * that surviving descendant is exactly what must be killed. */
        pid_t dead_wid = pids[wid];
        pids[wid] = -1;
        sup_reconcile_worker_reap(wid, dead_wid,
                                  (unsigned)incarn[wid], st);
        /* DECISION-03 section 7.3 -- the worker-exit POLICY.
         *
         * The fail-fast branch RETURNS before the recovery call is ever
         * reached. That ordering is the whole point: "fail-fast must never
         * recover" is enforced by control flow rather than by a boolean
         * guarding a call, so there is no branch to get wrong in a later
         * edit. test_fail_fast_never_recovers asserts p_recover is not
         * entered under this policy.
         */
        if (!o.supervise) {
            /* A worker that finished its work exits 0; that is completion,
             * not death, and must not abort the run. Only an ABNORMAL exit
             * is a death.
             *
             * This classification is deliberately made from the raw wait
             * status rather than by calling p_recover, because the point of
             * the fail-fast policy is that it never reaches the recovery
             * capability at all. Getting it from p_recover would have been
             * the easy way and would have put recovery back on the path
             * this policy exists to keep off it.
             */
            int completed_normally = WIFEXITED(st) && WEXITSTATUS(st) == 0;
            if (completed_normally)
                continue;           /* drained to EOF; keep going */
            /* No recovery, no respawn, immediate abort (DECISION-03 7.4b).
             * The worker died; its in-flight batch is abandoned rather than
             * reclaimed and re-executed by a replacement, which is the whole
             * point for a side-effecting payload. */
            /* STAGE3: a dead worker generation takes its command
             * descendants with it, even on the fail-fast path where no
             * recovery follows. Otherwise a long-lived grandchild would
             * outlive the run that started it. */
            kill_worker_group(dead_wid);
            fprintf(stderr, "forkrun-cleanroom: worker %d died (status %d) "
                    "under fail-fast supervision -- not recovering, "
                    "aborting\n", wid, death_cause(st));
            fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_SUP_ABORT,
                          (int32_t)wid, (int32_t)incarn[wid], 0,
                          (int32_t)death_cause(st));
            bad = 1;
            break;
        }
        /* STAGE3: the dead generation's process group goes with it,
         * BEFORE recovery and respawn.
         *
         * The group survives the worker's death as long as any descendant
         * is still in it, and kill(-pgid) reaches those members even
         * though the leader is already gone -- which is exactly the case
         * that matters, because the orphan IS the surviving member.
         *
         * Ordering matters: this must precede the respawn, or the new
         * generation's pid could be mistaken for the old group. */
        kill_worker_group(dead_wid);

        int rc = p_recover ? p_recover(wid, incarn[wid], out_fds[wid],
                                       death_cause(st))
                           : 5;    /* no core -> cannot vouch for it */

        /* STAGE0 TEST-ONLY: simulate the synthetic wakeup being
         * undeliverable by closing the supervisor's spare signal writer
         * just before recovery. spare_sig is otherwise held open for the
         * whole supervision loop, which is what makes the real
         * fail-closed path safe; closing it here forces the failure that
         * path exists to catch, so the abort can be tested rather than
         * assumed. Inert unless the variable is set. */
        if (getenv("FORKRUN_TEST_BREAK_DRAIN_WAKEUP") != NULL &&
            spare_sig >= 0) {
            close(spare_sig);
            spare_sig = -1;
        }

        /* STAGE0: notify the drain of anything committed that its
         * notification may have lost. This must happen BEFORE the early
         * continues below -- a NORMAL_EXIT classification in particular
         * used to skip straight past, silently stranding a committed
         * record. Only nonfatal, non-ambiguous rc values are woken for;
         * see fr_wake_drain_committed. */
        if ((rc == 0 || rc == 1 || rc == 2) &&
            fr_wake_drain_committed(spare_sig, wid, out_fds[wid]) != 0) {
            /* STAGE0: fail CLOSED.
             *
             * This worker committed output whose ordinary notification was
             * lost, and the synthetic wakeup is the only remaining way to
             * deliver it. If the wakeup cannot be sent, the run cannot
             * deliver its committed results -- continuing would report
             * success with records the caller never receives, which is the
             * exact failure the completeness invariant exists to prevent.
             *
             * Safe to abort on, rather than risk aborting legitimate runs:
             * spare_sig stays open for the whole supervision loop ("spare
             * closed LAST ... keeps the drain alive across respawns"), so
             * the signal pipe cannot reach EOF and this write cannot fail
             * because the drain already finished. Verified on clean runs
             * and on runs with injected worker deaths; both succeed.
             *
             * Ambiguous outcomes (rc 3, 4, 5) are deliberately not woken
             * for: their output state is not a trustworthy committed
             * frontier, and rc 4/5 are already fatal below. */
            fprintf(stderr, "forkrun-cleanroom: worker %d committed output "
                    "but the post-recovery drain wakeup failed -- aborting "
                    "rather than dropping committed records\n", wid);
            fr_trace_emit(FR_ROLE_LAUNCHER, FR_EV_SUP_ABORT,
                          (int32_t)wid, (int32_t)incarn[wid], 0, 0);
            bad = 1;
            break;
        }

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
        int ro = (spare_order >= 0) ? dup(spare_order) : -1;
        if (rs < 0 || rf < 0 || (spare_order >= 0 && ro < 0)) {
            bad = 1; break;
        }
        pid_t np = spawn_wid(wid, memfd, out_fds[wid],
                             (numa && o.order_index) ? -1 : rs, rf,
                             ro, p_wloop, numa ? p_wnuma : NULL, s_wloop,
                             &wd,
                             o.retry_limit, o.on_error,
                             engine_fd, n_engine, incarn[wid],
                             wid_node[wid]);
        /* The child inherited its own copy of rs/rf; the launcher's must
         * be dropped or every respawn PERMANENTLY holds the signal and
         * fallow pipe write ends open. That is precisely what the drain
         * and the fallow reaper are waiting for: both block until EOF,
         * and EOF means "every worker is gone". One leaked dup per
         * respawn and neither ever sees it, so the run HANGS after the
         * supervision loop has already finished cleanly. */
        close(rs);
        close(rf);
        if (ro >= 0) close(ro);
        if (np < 0) { bad = 1; break; }
        pids[wid] = np;
        live++;
        if (g_sup_on) {
            unsigned prev_inc = (unsigned)incarn[wid] - 1u;
            sup_register_worker(wid, (unsigned)incarn[wid], np,
                                wid_node[wid]);
            if (getenv("FORKRUN_TEST_STALE_NOTE_AFTER_RESPAWN") != NULL) {
                /* Two stale shapes, both of which must be dropped:
                 * the retired pid, and the CURRENT pid carrying the
                 * previous incarnation. The second one is the reason
                 * the incarnation is part of the identity -- pid reuse
                 * alone cannot reject it. */
                struct sup_note old_pid = {
                    SUP_NOTE_MAGIC, (uint32_t)SUP_ROLE_WORKER,
                    (int32_t)dead_wid, 137, prev_inc, 0
                };
                struct sup_note old_gen = {
                    SUP_NOTE_MAGIC, (uint32_t)SUP_ROLE_WORKER,
                    (int32_t)np, 137, prev_inc, 0
                };
                int rejected;
                (void)sup_reconcile_note(&old_pid);
                rejected = !sup_reconcile_note(&old_gen);
                fprintf(stderr,
                        "forkrun-sup: stale-check role=worker wid=%d pid=%d "
                        "given_incarnation=%u current_incarnation=%u "
                        "rejected=%d\n",
                        wid, (int)np, prev_inc, (unsigned)incarn[wid],
                        rejected);
            }
        }
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
        sup_guillotine();
        if (numa) {
            /* Helpers are registered and were signalled by the
             * guillotine; only workers need the process-group kill. */
            for (int i = 0; i < o.workers; i++) {
                pid_t _p = pids[i]; pids[i] = -1;
                kill_worker_group(_p);
            }
            /* Reap what the kills just terminated. Without this the
             * launcher exits on top of its own dead workers, and they
             * are still observable as processes after it is gone. */
            reap_all_bounded();
            close(spare_sig);
            close(spare_fall);
            if (spare_order >= 0) close(spare_order);
            fprintf(stderr,
                    "forkrun-cleanroom: fatal -- terminated the NUMA "
                    "pipeline (workers and registered helpers signalled, "
                    "all children reaped); the input source may have been "
                    "left partially read\n");
            return 1;
        }
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
            /* Workers go by GROUP so a command's children die with the
             * worker; the helpers below are not group leaders and must
             * never be signalled by negative pid. */
            for (int i = 0; i < o.workers; i++) {
                pid_t _p = pids[i]; pids[i] = -1;
                kill_worker_group(_p);
            }
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
    if (numa) {
        /* Teardown begins: the orderer/fallow clean windows open only
         * now, and every write end of their pipes is closed above.
         * Join the consumer first (orderer/drain), then the producers,
         * and the ingest LAST -- it is routinely the last to flush, and
         * its clean exit is only acceptable after ingest EOF was
         * posted (enforced by sup_apply_policy via p_eof_posted). */
        g_sup_stopping = 1;
        if (spare_order >= 0) close(spare_order);
        if (order_pid > 0)
            sup_join_helper(order_pid, &bad);
        else if (drain_pid > 0)
            sup_join_helper(drain_pid, &bad);
        for (int node = 0; node < o.num_nodes; node++)
            sup_join_helper(scan_pids[node], &bad);
        for (int node = 0; node < o.num_nodes; node++)
            sup_join_helper(idx_pids[node], &bad);
        sup_join_helper(fallow_pid, &bad);
        sup_join_helper(spill_pid, &bad);
        if (p_eof_posted && p_eof_posted() != 1) {
            fprintf(stderr, "forkrun-cleanroom: ingest EOF was never "
                            "posted -- refusing to report success\n");
            bad = 1;
        }
    } else {
    if (g_sup_on && sup_stop_helpers() != 0)
        bad = 1;
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
    }

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
     *   u32 version (=3)
     *   u32 poisoned
     *   u32 workers                  (v2)
     *   u32 slot_stride_u32          (v2)
     *   u32 committed_data_frames    (v3; UINT32_MAX = not available)
     *
     * v3 fills a word that v2 reserved. It carries the count of
     * COMMITTED DATA frames summed over every logical node, which is the
     * one number the parent cannot derive on its own and therefore the
     * only basis on which it can refuse to certify a short result.
     *
     * WHY IT IS SAFE TO READ HERE, ACROSS THE EXEC BOUNDARY. The counter
     * lives in struct SharedState, which fr_py_init() mmaps
     * MAP_SHARED|MAP_ANONYMOUS FRESH for every invocation. The workers
     * this launcher forks share that mapping with the launcher, and the
     * launcher called fr_py_init() itself, so the region starts
     * zero-filled for THIS invocation only. There is no previous run's
     * counter to subtract and no baseline bookkeeping to get wrong --
     * which is strictly better isolation than the in-process path gets,
     * and the reason this can be emitted as an absolute count.
     *
     * QUESCENCE. The accessor is a relaxed load, which is the right
     * pairing for the writers' relaxed fetch_add, but ordering cannot
     * substitute for the lifecycle fact. Every worker has been joined by
     * this point, so a worker that has not reached its commit point
     * cannot still be about to. Read any earlier and a not-yet-committed
     * batch is indistinguishable from one that committed nothing.
     *
     * UINT32_MAX MEANS "NO VERDICT", NEVER ZERO. If the accessor is
     * absent (an older substrate), or a node read fails, or the sum would
     * not fit, the field is the sentinel and the parent declines to
     * certify. Inventing a zero there would produce a run that fails on a
     * complete result, or passes on a truncated one -- both worse than
     * declining.
     *
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
        /* v3 APPENDS a word; it does not reuse one. All four v2 words are
         * load-bearing -- [2] is the worker count and [3] is the slot
         * stride, both of which the reader uses to walk the per-worker
         * poisoned-index slots -- so filling a v2 pad would have silently
         * broken slot parsing. The header grows to 20 bytes and the
         * reader's _STATS_HEADER_BYTES moves with it. */
        uint32_t rec[5] = {3u, 0u, (uint32_t)o.workers, 1024u + 1u,
                           UINT32_MAX};
        rec[1] = p_poisoned ? p_poisoned() : 0u;
        /* Both accessors, or no verdict: a counter that cannot be asked
         * whether it is live cannot distinguish "no frames" from "not
         * counting". */
        if (p_committed && p_c07_enabled && p_c07_enabled()) {
            /* Sum every logical node the engine exposes. The accessor
             * returns -1 for node >= global_num_nodes, so that is the
             * stop condition -- no separate node count is needed, and
             * the same code is correct once NUMA raises that count.
             * The cap is a backstop against a future accessor that never
             * rejects; reaching it leaves the field a sentinel rather
             * than inventing a total. */
            uint64_t total = 0;
            int node, ok = 1;
            (void)ok;
            for (node = 0; node < 64; ++node) {
                uint64_t c = 0;
                if (p_committed(node, &c) != 0) break;
                total += c;
            }
            if (ok && node >= 1 && total < (uint64_t)UINT32_MAX)
                rec[4] = (uint32_t)total;
            if (node >= 64) rec[4] = UINT32_MAX;   /* cap hit: no verdict */
        }
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