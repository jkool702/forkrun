/* W-CLEANROOM launcher — proof of concept.
 *
 * Mirrors frun's cleanroom for the Python frontend:
 *
 *   bloated Python parent --posix_spawn--> THIS (small, post-exec)
 *                                            |-- fr_py_init()
 *                                            +-- fork x N workers
 *
 * posix_spawn uses CLONE_VM|CLONE_VFORK, so the spawn copies NO page
 * table. The launcher dlopens the substrate and then FORKS (no second
 * exec), so workers inherit the engine mapping by COW. That makes the
 * N forks cheap -- the whole point.
 *
 * Like frun, we init AFTER arriving here, so no engine state ever
 * crosses the exec boundary. That is why the MAP_ANONYMOUS shared
 * state is not an obstacle: we do not carry it, we recreate it.
 *
 * PoC scope, deliberately narrow: prove the fork tax is gone. This does
 * NOT yet implement the full orchestration (scan/drain/reactor) -- that
 * is the integration step, gated on this measurement.
 *
 * Build: see Makefile.substrate (fr_py_cleanroom target).
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <sys/syscall.h>

/* Substrate entry points, resolved at runtime. Signatures mirror
 * python/forkrun/_shim.c -- keep the two in step. */
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
typedef int (*fn_abort)(void);
typedef void *(*fn_map_range)(int src_fd, unsigned long long src_off,
                              int dst_fd, unsigned long long dst_off,
                              unsigned long long length);
typedef int (*fn_unmap)(void *p);

struct opts {
    const char *so_path;
    const char *plugin_path;
    const char *plugin_func;
    int workers;
    int lines;              /* >0 lines mode, >0 bytes mode mutually excl. */
    int bytes;
    int source_fd;
    int result_fd;
    int verbose;
    int fork_only;   /* PoC: measure fork cost, do not wait for workers */
};

static long clock_gettime_nsec(void);

/* memfd_create is not exposed by glibc headers under _GNU_SOURCE on
 * every toolchain; the engine reaches it through the same syscall
 * (forkrun_ring.c:1249), so do the same rather than adding a libc
 * dependency the engine does not have. */
static int fr_memfd_create(const char *name, unsigned int flags) {
    return (int)syscall(__NR_memfd_create, name, flags);
}

static void die(const char *what) {
    fprintf(stderr, "forkrun-cleanroom: %s: %s\n", what, strerror(errno));
    exit(70);
}

static void *sym(void *h, const char *name) {
    void *p = dlsym(h, name);
    if (!p) {
        fprintf(stderr, "forkrun-cleanroom: missing symbol %s\n", name);
        exit(69);
    }
    return p;
}

/* Raise the fd limit to the hard limit, exactly as frun's cleanroom
 * does (`ulimit -n $(ulimit -Hn)`). A launcher that inherits a low
 * RLIMIT_NOFILE would fail late and confusingly when it sets up
 * per-worker pipes. */
static void raise_fd_limit(void) {
    struct rlimit rl;
    if (getrlimit(RLIMIT_NOFILE, &rl) != 0)
        return;
    if (rl.rlim_cur != rl.rlim_max) {
        rl.rlim_cur = rl.rlim_max;
        (void)setrlimit(RLIMIT_NOFILE, &rl);   /* best effort */
    }
}

static long vm_rss_kb(void) {
    FILE *f = fopen("/proc/self/status", "r");
    if (!f)
        return -1;
    char line[256];
    long kb = -1;
    while (fgets(line, sizeof line, f)) {
        if (strncmp(line, "VmRSS:", 6) == 0) {
            kb = strtol(line + 6, NULL, 10);
            break;
        }
    }
    fclose(f);
    return kb;
}

int main(int argc, char **argv) {
    struct opts o;
    memset(&o, 0, sizeof o);
    o.workers = 1;
    o.source_fd = -1;
    o.result_fd = -1;

    /* argv: --so --plugin --func --workers --lines --bytes --src
     *       --result --verbose
     * fds arrive as inherited descriptors, NOT numbers to look up:
     * posix_spawn's file_actions dup2 them in before exec. */
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--so") && i + 1 < argc)          o.so_path = argv[++i];
        else if (!strcmp(argv[i], "--plugin") && i + 1 < argc) o.plugin_path = argv[++i];
        else if (!strcmp(argv[i], "--func") && i + 1 < argc)   o.plugin_func = argv[++i];
        else if (!strcmp(argv[i], "--workers") && i + 1 < argc) o.workers = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--lines") && i + 1 < argc)  o.lines = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--bytes") && i + 1 < argc)  o.bytes = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--src") && i + 1 < argc)   o.source_fd = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--result") && i + 1 < argc) o.result_fd = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--verbose"))                o.verbose = 1;
        else if (!strcmp(argv[i], "--fork-only"))             o.fork_only = 1;
        else { fprintf(stderr, "forkrun-cleanroom: bad arg %s\n", argv[i]); return 64; }
    }
    if (!o.so_path || o.source_fd < 0) {
        fprintf(stderr, "forkrun-cleanroom: --so and --src are required\n");
        return 64;
    }
    if (o.workers < 1) o.workers = 1;

    raise_fd_limit();

    /* _FR_IN_CLEANROOM equivalent: we are already the clean process, so
     * there is nothing to guard against here. The GUARD belongs on the
     * parent side, which must not spawn us twice. */

    if (o.verbose)
        fprintf(stderr, "forkrun-cleanroom: RSS at entry %ld kB\n",
                vm_rss_kb());

    void *h = dlopen(o.so_path, RTLD_NOW | RTLD_LOCAL);
    if (!h) {
        fprintf(stderr, "forkrun-cleanroom: dlopen %s: %s\n",
                o.so_path, dlerror());
        return 69;
    }
    fn_init              p_init        = (fn_init)             sym(h, "fr_py_init");
    fn_worker_plugin_loop p_wloop      = (fn_worker_plugin_loop) sym(h, "fr_py_worker_plugin_loop");
    fn_scan              p_scan        = (fn_scan)             sym(h, "fr_py_scan");
    fn_ingest_done       p_idone       = (fn_ingest_done)      sym(h, "fr_py_ingest_done");
    fn_ingest_data_post  p_ipost       = (fn_ingest_data_post) sym(h, "fr_py_ingest_data_post");
    fn_map_range         p_copy        = (fn_map_range)        sym(h, "fr_py_copy_range");
    fn_abort             p_abort       = (fn_abort)            sym(h, "fr_py_abort");

    if (o.verbose)
        fprintf(stderr, "forkrun-cleanroom: RSS after dlopen %ld kB\n",
                vm_rss_kb());

    /* Init HERE, after exec -- this is what makes the cleanroom work.
     * The state mapping is created in this address space and inherited
     * by the workers we fork below; it never has to survive an exec. */
    if (p_init(o.lines, o.bytes) != 0) {
        fprintf(stderr, "forkrun-cleanroom: fr_py_init failed\n");
        return 71;
    }
    if (o.verbose)
        fprintf(stderr, "forkrun-cleanroom: RSS after init %ld kB\n",
                vm_rss_kb());

    /* Ingress: copy the source into a memfd so workers can pread it.
     * PoC keeps this synchronous; the integrated launcher will overlap
     * it with the scan exactly as the Python path does. */
    int ingress = fr_memfd_create("fr_cleanroom_ingress", 0);
    if (ingress < 0) die("memfd_create(ingress)");
    {
        char buf[1 << 20];
        unsigned long long off = 0;
        for (;;) {
            ssize_t n = read(o.source_fd, buf, sizeof buf);
            if (n < 0) {
                if (errno == EINTR) continue;
                die("read(source)");
            }
            if (n == 0) break;
            ssize_t w = pwrite(ingress, buf, (size_t)n, (off_t)off);
            if (w != n) die("pwrite(ingress)");
            off += (unsigned long long)n;
            p_ipost();            /* same per-chunk poke the Python
                                     * spill does, so the scanner's
                                     * pre-flight does not spin */
        }
    }
    if (p_idone() != 0)
        fprintf(stderr, "forkrun-cleanroom: warning: ingest_done failed\n");

    /* Per-worker output memfds. */
    int *outs = calloc((size_t)o.workers, sizeof(int));
    int *sigw = calloc((size_t)o.workers, sizeof(int));
    int *sigr = calloc((size_t)o.workers, sizeof(int));
    if (!outs || !sigw || !sigr) die("calloc");
    for (int i = 0; i < o.workers; i++) {
        char nm[64];
        snprintf(nm, sizeof nm, "fr_cleanroom_out_%d", i);
        outs[i] = fr_memfd_create(nm, 0);
        if (outs[i] < 0) die("memfd_create(out)");
        int pfd[2];
        if (pipe(pfd) != 0) die("pipe(signal)");
        sigr[i] = pfd[0];
        sigw[i] = pfd[1];
    }

    /* Fork the workers. THIS is the measurement that matters: the parent
     * is small, so each fork should cost ~0.27ms rather than ~45ms. */
    long t0 = clock_gettime_nsec();
    pid_t *pids = calloc((size_t)o.workers, sizeof(pid_t));
    if (!pids) die("calloc(pids)");
    for (int i = 0; i < o.workers; i++) {
        pid_t p = fork();
        if (p < 0) die("fork(worker)");
        if (p == 0) {
            /* child: close everything not ours, then run the loop */
            for (int j = 0; j < o.workers; j++) {
                if (j != i) { close(outs[j]); close(sigr[j]); close(sigw[j]); }
            }
            close(o.source_fd);
            if (o.result_fd >= 0) close(o.result_fd);
            close(ingress);           /* workers only read their slice */
            (void)p_init; (void)p_scan; (void)p_abort; (void)p_copy;
            int rc = p_wloop(i, o.plugin_path, o.plugin_func,
                             ingress, outs[i], sigw[i], -1, -1, -1,
                             0, 3, 0);
            _exit(rc == 0 ? 0 : 1);
        }
        pids[i] = p;
        close(sigr[i]);                 /* parent keeps only the write end */
    }
    long t1 = clock_gettime_nsec();
    double fork_ms = (double)(t1 - t0) / 1e6;

    if (o.verbose)
        fprintf(stderr,
                "forkrun-cleanroom: %d worker forks in %.2f ms "
                "(%.3f ms/fork), launcher RSS %ld kB\n",
                o.workers, fork_ms, fork_ms / o.workers, vm_rss_kb());

    /* Machine-readable line for the harness to compare against the
     * in-process path. */
    printf("CLEANROOM workers=%d fork_ms=%.3f per_fork_ms=%.4f rss_kb=%ld\n",
           o.workers, fork_ms, fork_ms / o.workers, vm_rss_kb());

    if (o.fork_only) {
        /* PoC mode: the measurement above is the deliverable. The
         * workers' full orchestration (scan/drain/ack) is the
         * integration step, gated on this number, so do not wait for
         * it here -- reap with WNOHANG and leave. */
        for (int i = 0; i < o.workers; i++)
            (void)waitpid(pids[i], NULL, WNOHANG);
        fflush(stdout);
        _exit(0);
    }

    /* Wait for workers. The integrated launcher drains their output
     * memfds here instead. */
    int alive = o.workers;
    while (alive > 0) {
        int st;
        pid_t p = waitpid(-1, &st, 0);
        if (p < 0) {
            if (errno == EINTR) continue;
            break;
        }
        alive--;
    }
    free(pids);
    return 0;
}

static long clock_gettime_nsec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long)ts.tv_sec * 1000000000L + ts.tv_nsec;
}
