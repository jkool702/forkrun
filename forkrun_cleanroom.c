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
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/syscall.h>
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
    int drain_mode;
    int retry_limit;
    int on_error;
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

int main(int argc, char **argv) {
    struct opts o;
    memset(&o, 0, sizeof o);
    o.workers = 1; o.source_fd = -1; o.result_fd = -1;
    o.drain_mode = 0; o.retry_limit = 3; o.on_error = 0;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--so") && i + 1 < argc)        o.so_path = argv[++i];
        else if (!strcmp(argv[i], "--plugin") && i + 1 < argc) o.plugin_path = argv[++i];
        else if (!strcmp(argv[i], "--func") && i + 1 < argc) o.plugin_func = argv[++i];
        else if (!strcmp(argv[i], "--workers") && i + 1 < argc) o.workers = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--lines") && i + 1 < argc)  o.lines = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--bytes") && i + 1 < argc)  o.bytes = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--src") && i + 1 < argc)   o.source_fd = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--result") && i + 1 < argc) o.result_fd = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--drain-mode") && i + 1 < argc) o.drain_mode = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--retry") && i + 1 < argc) o.retry_limit = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--on-error") && i + 1 < argc) o.on_error = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--verbose"))                o.verbose = 1;
        else if (!strcmp(argv[i], "--fork-only"))             o.fork_only = 1;
        else { fprintf(stderr, "forkrun-cleanroom: bad arg %s\n", argv[i]); return 64; }
    }
    if (!o.so_path || o.source_fd < 0 || !o.plugin_path) {
        fprintf(stderr, "forkrun-cleanroom: --so --src --plugin required\n");
        return 64;
    }
    if (o.workers < 1) o.workers = 1;
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

    /* Init HERE, after exec. This is the whole point: the state mapping
     * is created in this small address space and inherited by every
     * child forked below. Nothing had to cross the exec boundary. */
    if (p_init(o.lines, o.bytes) != 0) {
        fprintf(stderr, "forkrun-cleanroom: fr_py_init failed\n");
        return 71;
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
        int keep[2] = {o.source_fd, memfd};
        scrub_closem_others(keep, 2);
        static char sbuf[1 << 20];
        unsigned long long soff = 0;
        for (;;) {
            ssize_t n = read(o.source_fd, sbuf, sizeof sbuf);
            if (n < 0) { if (errno == EINTR) continue; _exit(1); }
            if (n == 0) break;
            ssize_t w = pwrite(memfd, sbuf, (size_t)n, (off_t)soff);
            if (w != n) _exit(1);
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

    long t0 = now_ns();

    /* fallow reaper child */
    pid_t fallow_pid = fork();
    if (fallow_pid < 0) die("fork(fallow)");
    if (fallow_pid == 0) {
        int keep[2] = {fallp[0], memfd};
        scrub_closem_others(keep, 2);
        _exit(p_fall(fallp[0], memfd) == 0 ? 0 : 1);
    }

    /* workers */
    for (int i = 0; i < o.workers; i++) {
        pid_t p = fork();
        if (p < 0) die("fork(worker)");
        if (p == 0) {
            int keep[4] = {memfd, out_fds[i], sigp[1], fallp[1]};
            scrub_closem_others(keep, 4);
            int rc = p_wloop(i, o.plugin_path, o.plugin_func,
                             memfd, out_fds[i], sigp[1], fallp[1],
                             -1, -1, 0, o.retry_limit, o.on_error);
            _exit(rc == 0 ? 0 : 1);
        }
        pids[i] = p;
    }
    /* Parent drops its write copies so EOF means every worker is gone. */
    close(sigp[1]);
    close(fallp[1]);

    /* scanner child: pre-flight, ramp, publish */
    pid_t scan_pid = fork();
    if (scan_pid < 0) die("fork(scan)");
    if (scan_pid == 0) {
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
    for (int i = 0; i < o.workers; i++) {
        int st; pid_t p = waitpid(pids[i], &st, 0);
        if (p > 0 && !(WIFEXITED(st) && WEXITSTATUS(st) == 0)) bad = 1;
    }
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
    return bad ? 1 : 0;
}