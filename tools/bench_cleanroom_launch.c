/* bench_cleanroom_launch.c -- MEASUREMENT ONLY (decision-report step 2)
 *
 * What this measures, precisely:
 *
 *   The cost of STARTING the cleanroom launcher by two mechanisms:
 *     (a) fork() + execv()  -- what run.py does today
 *     (b) posix_spawn()     -- the candidate
 *
 *   Both drive the REAL launcher binary with --fork-only, so the launcher's
 *   own dlopen + fr_py_init + worker-fork work happens identically in both
 *   arms. The launcher prints its internal `fork_ms`, which is therefore
 *   expected to be MATCHED between arms; the difference between arms is
 *   the launch mechanism's own overhead.
 *
 * What this does NOT measure, and must not be reported as if it did:
 *   - Nothing about supervision, poison, retry, or NUMA behaviour.
 *   - Nothing about whether posix_spawn is CORRECT for the route. The
 *     decision report gates integration on the fork tax, not on this.
 *   - Not the dlopen/fr_py_init cost itself: that is inside `fork_ms` and
 *     is common to both arms.
 *
 * This tool produces a NUMBER to record in the decision report. It does not
 * by itself justify integrating posix_spawn; that stays a separate,
 * flag-gated decision.
 *
 * Build:  cc -O2 -o /tmp/bench_cleanroom_launch tools/bench_cleanroom_launch.c
 * Use:    bench_cleanroom_launch <launcher> <substrate.so> <plugin.so> <func> <workers> <iters>
 */
#define _GNU_SOURCE
#include <errno.h>
#include <spawn.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1e3 + ts.tv_nsec * 1e-6;   /* ns -> ms */
}

static int cmp_double(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

/* Child: redirect stdout to `out_fd`, then exec. Shared by both arms so
 * neither arm gets a different descriptor story. */
/* Wait with a deadline. A benchmark tool that can hang forever is a
 * benchmark tool that eventually gets abandoned; a bounded wait turns a
 * stuck launcher into a reported non-zero sample instead. */
static int wait_bounded(pid_t p, double seconds)
{
    int st = 0;
    double t0 = now_ms();
    for (;;) {
        pid_t r = waitpid(p, &st, WNOHANG);
        if (r == p) break;
        if (r < 0) { if (errno == EINTR) continue; return -1; }
        if (now_ms() - t0 > seconds * 1000.0) {
            kill(p, SIGKILL);
            (void)waitpid(p, &st, 0);
            return 124;            /* timeout, distinguishable */
        }
        struct timespec ts = {0, 200000};   /* 0.2 ms */
        nanosleep(&ts, NULL);
    }
    return WIFEXITED(st) ? WEXITSTATUS(st) : -1;
}

static void child_exec(char *const argv[], int out_fd)
{
    if (out_fd >= 0 && dup2(out_fd, 1) < 0)
        _exit(126);
    execv(argv[0], argv);
    _exit(127);
}

static int run_fork_exec(char *const argv[], int out_fd)
{
    pid_t p = fork();
    if (p < 0) return -1;
    if (p == 0) child_exec(argv, out_fd);
    return wait_bounded(p, 10.0);
}

static int run_posix_spawn(char *const argv[], int out_fd)
{
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    if (out_fd >= 0)
        posix_spawn_file_actions_adddup2(&fa, out_fd, STDOUT_FILENO);
    pid_t p = 0;
    int rc = posix_spawn(&p, argv[0], &fa, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&fa);
    if (rc != 0) { errno = rc; return -1; }
    return wait_bounded(p, 10.0);
}

static void report(const char *label, double *v, int n, double *fork_ms_out)
{
    qsort(v, (size_t)n, sizeof *v, cmp_double);
    double sum = 0.0;
    for (int i = 0; i < n; i++) sum += v[i];
    double mean = sum / n;
    double med = v[n / 2];
    double p95 = v[(int)(n * 0.95)];
    printf("%-12s n=%d  min=%.3f  median=%.3f  mean=%.3f  p95=%.3f  max=%.3f (ms/launch)\n",
           label, n, v[0], med, mean, p95, v[n - 1]);
    if (fork_ms_out) *fork_ms_out = mean;
}

int main(int argc, char **argv)
{
    if (argc < 7) {
        fprintf(stderr,
                "usage: %s <launcher> <substrate.so> <plugin.so> <func> <workers> <iters>\n",
                argv[0]);
        return 64;
    }
    const char *launcher = argv[1];
    const char *so = argv[2];        /* substrate: libforkrun */
    const char *plug = argv[3];      /* loadable payload, must export
                                      * forkrun_use_ctx */
    const char *func = argv[4];
    int workers = atoi(argv[5]);
    int iters = atoi(argv[6]);
    if (workers < 1) workers = 1;
    if (iters < 1) iters = 1;

    /* Real descriptors, not /dev/null: the launcher WRITES results and
     * stats, and a read-only fd makes those writes fail while workers
     * block -- which hangs the benchmark instead of measuring it. */
    char src_path[]  = "/tmp/forkrun_bench_srcXXXXXX";
    char res_path[]  = "/tmp/forkrun_bench_resXXXXXX";
    char stat_path[] = "/tmp/forkrun_bench_staXXXXXX";
    int src_fd = mkstemp(src_path);
    int res_fd = mkstemp(res_path);
    int sta_fd = mkstemp(stat_path);
    if (src_fd < 0 || res_fd < 0 || sta_fd < 0) { perror("mkstemp"); return 1; }
    if (write(src_fd, "a\nb\nc\n", 6) != 6) { perror("write"); return 1; }
    lseek(src_fd, 0, SEEK_SET);

    int pipefd[2];
    if (pipe(pipefd) != 0) { perror("pipe"); return 1; }

    /* Build the launcher argv exactly as run.py does, plus --fork-only. */
    char wbuf[32], lbuf[32], bbuf[32], rbuf[32], sbuf[32], fbuf[32];
    snprintf(wbuf, sizeof wbuf, "%d", workers);
    snprintf(lbuf, sizeof lbuf, "%d", 1);
    snprintf(bbuf, sizeof bbuf, "%d", 0);
    snprintf(rbuf, sizeof rbuf, "%d", res_fd);
    snprintf(sbuf, sizeof sbuf, "%d", src_fd);
    snprintf(fbuf, sizeof fbuf, "%d", sta_fd);

    char *largv[] = {
        (char *)launcher,
        /* --so is the SUBSTRATE (libforkrun); --plugin is the loadable
         * payload. run.py passes both; omitting --so makes the launcher
         * exit 64 before doing any work, which would benchmark an
         * argument error rather than a launch. */
        "--so", (char *)so,
        "--plugin", (char *)plug, "--func", (char *)func,
        "--workers", wbuf, "--lines", lbuf, "--bytes", bbuf,
        "--on-error", (char *)"0", "--retry", (char *)"0",
        "--src", sbuf, "--result", rbuf, "--stats-fd", fbuf,
        "--fork-only", NULL
    };

    /* Warmup: page cache, dynamic loader, first-touch costs. Excluded
     * from the samples -- otherwise arm A pays and arm B does not. */
    for (int i = 0; i < 3; i++) {
        close(pipefd[0]);
        pipe(pipefd);
        run_fork_exec(largv, pipefd[1]);
    }

    double *a = calloc((size_t)iters, sizeof *a);
    double *b = calloc((size_t)iters, sizeof *b);
    char last[512];
    last[0] = 0;
    int bad = 0;

    for (int i = 0; i < iters; i++) {
        close(pipefd[0]);
        if (pipe(pipefd) != 0) { perror("pipe"); return 1; }
        double t0 = now_ms();
        int rc = run_fork_exec(largv, pipefd[1]);
        a[i] = now_ms() - t0;
        if (rc != 0) bad++;
        close(pipefd[1]);
        ssize_t got = read(pipefd[0], last, sizeof last - 1);
        if (got > 0) last[got] = 0;

        close(pipefd[0]);
        if (pipe(pipefd) != 0) { perror("pipe"); return 1; }
        t0 = now_ms();
        rc = run_posix_spawn(largv, pipefd[1]);
        b[i] = now_ms() - t0;
        if (rc != 0) bad++;
        close(pipefd[1]);
    }
    close(pipefd[0]);

    printf("# launcher : %s\n", launcher);
    printf("# workers  : %d\n# iters    : %d (interleaved A/B, 3 warmups discarded)\n",
           workers, iters);
    if (bad) printf("# NOTE: %d launch(es) exited non-zero; samples retained\n", bad);
    printf("# launcher self-report: %s", last);
    if (last[0] && last[strlen(last) - 1] != '\n') printf("\n");
    double fa = 0, fb = 0;
    report("fork+exec", a, iters, &fa);
    report("posix_spawn", b, iters, &fb);
    printf("# delta (median-equivalent means): posix_spawn - fork+exec = %+.3f ms "
           "(%+.2f%%)\n", fb - fa, fa > 0 ? (fb - fa) / fa * 100.0 : 0.0);
    printf("# The launcher's internal fork_ms is COMMON to both arms by "
           "construction; it is the WORKER fork cost, not the launch cost.\n");
    free(a);
    free(b);
    close(src_fd); close(res_fd); close(sta_fd);
    unlink(src_path); unlink(res_path); unlink(stat_path);
    return 0;
}