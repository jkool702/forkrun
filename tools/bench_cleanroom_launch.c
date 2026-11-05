/* bench_cleanroom_launch.c -- MEASUREMENT ONLY (decision-report step 2)
 *
 * WHAT THIS MEASURES, precisely:
 *
 *   The cost of STARTING the cleanroom launcher by two mechanisms:
 *     (a) fork() + execv()  -- what run.py does today
 *     (b) posix_spawn()     -- the candidate
 *
 *   Both arms drive the REAL launcher binary with the launcher's existing
 *   --fork-only mode, so its dlopen + fr_py_init + worker-fork work
 *   happens identically in both. The launcher prints its own `fork_ms`,
 *   which is therefore common to both arms by construction; the difference
 *   between arms is the launch mechanism's own overhead, reported
 *   SEPARATELY and never merged.
 *
 *   The independent variable is PARENT RESIDENT MEMORY. The design
 *   rationale is specifically about a multi-gigabyte parent and the cost
 *   of copying its page tables, so --ballast-mb allocates RESIDENT (touched)
 *   memory and verifies the resulting RSS from /proc before sampling.
 *   Virtual-only ballast would measure nothing.
 *
 * WHAT THIS DOES NOT MEASURE, and must not be reported as if it did:
 *   - Nothing about supervision, poison, retry, or NUMA behaviour.
 *   - Nothing about whether posix_spawn is CORRECT for the route.
 *   - Not the dlopen/fr_py_init cost itself: inside `fork_ms`, common to
 *     both arms.
 *   - Not end-to-end workload time.
 *
 * METHODOLOGY (see decision report §5):
 *   - Interleaved A/B within each iteration, so machine drift hits both
 *     arms equally.
 *   - Warmups discarded.
 *   - Exact-output guard: a sample is only accepted if the launcher exits
 *     0 AND emits the expected self-report. A launch that fails the guard
 *     is counted and DISCARDED WITH A REASON, never silently averaged in.
 *   - Per-arm failure and timeout counts reported.
 *
 * Build:  cc -O2 -o /tmp/bench_cleanroom_launch tools/bench_cleanroom_launch.c
 * Use:    see usage() below.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;

#define OUT_CAP 8192
#define TIMEOUT_S 10.0

/* ---------------------------------------------------------------- timing */
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

/* ---------------------------------------------------------------- ballast */
/* RSS from /proc/self/statm field 2 (resident pages). Cheap -- one short
 * read -- but the kernel documents statm's resident figures as
 * "potentially inaccurate" and recommends smaps/smaps_rollup where an
 * accurate value is required. Measured here, statm ran 124-188 KiB ABOVE
 * smaps_rollup at 256/1024/2048 MiB. Small, but it is the wrong source to
 * hang a "resident" claim on, so smaps_rollup below is authoritative and
 * statm is kept only as a cross-check. */
static long current_rss_kb(void)
{
    int fd = open("/proc/self/statm", O_RDONLY);
    if (fd < 0) return -1;
    char buf[256];
    ssize_t n = read(fd, buf, sizeof buf - 1);
    close(fd);
    if (n <= 0) return -1;
    buf[n] = 0;
    long long total = 0, resident = 0;
    if (sscanf(buf, "%lld %lld", &total, &resident) != 2) return -1;
    return (long)resident * (sysconf(_SC_PAGESIZE) / 1024);
}

/* AUTHORITATIVE RSS: /proc/self/smaps_rollup "Rss:" in KiB. This is the
 * kernel's own accurate accounting and is what the ballast-residency
 * claim is now based on. Returns -1 if unavailable. */
static long smaps_rss_kb(void)
{
    FILE *f = fopen("/proc/self/smaps_rollup", "r");
    if (!f) return -1;
    char line[256], key[64], unit[16];
    long val = -1;
    while (fgets(line, sizeof line, f)) {
        if (sscanf(line, "%63[^:]: %ld %15s", key, &val, unit) == 3
            && strcmp(key, "Rss") == 0)
            break;
        val = -1;
    }
    fclose(f);
    return val;
}

/* MemAvailable in KiB, from /proc/meminfo. */
static long mem_available_kb(void)
{
    FILE *f = fopen("/proc/meminfo", "r");
    if (!f) return -1;
    char key[64];
    long val = -1;
    while (fscanf(f, "%63s %ld kB\n", key, &val) == 2) {
        if (strcmp(key, "MemAvailable:") == 0) break;
    }
    fclose(f);
    return val;
}

/* Allocate `mb` of RESIDENT memory: mmap anonymous, then write one byte
 * per page so every page is actually faulted in. Without the touch loop
 * the mapping is virtual only and RSS does not move, which is the whole
 * point of this benchmark. MAP_NORESERVE avoids committing swap.
 * Returns the mapping (to be kept alive) or NULL. */
static void *touch_resident_mb(long mb)
{
    size_t bytes = (size_t)mb * 1024u * 1024u;
    if (bytes == 0) return NULL;
    void *p = mmap(NULL, bytes, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (p == MAP_FAILED) return NULL;
    long ps = sysconf(_SC_PAGESIZE);
    volatile unsigned char *q = (volatile unsigned char *)p;
    for (size_t off = 0; off < bytes; off += (size_t)ps)
        q[off] = (unsigned char)(off & 0xff);
    /* Read back so the compiler cannot elide the stores. */
    unsigned char sink = 0;
    for (size_t off = 0; off < bytes; off += (size_t)ps * 4096)
        sink ^= q[off];
    (void)sink;
    return p;
}

/* ---------------------------------------------------------------- launch */
struct arm_result {
    double ms;
    int rc;            /* 0 ok, 124 timeout, other = launcher failure */
    int guard_ok;      /* exact-output guard passed */
    char out[OUT_CAP];
};

/* Wait with a deadline. A benchmark that can hang forever is one that gets
 * abandoned; a stuck launcher becomes a reported timeout instead. */
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
            return 124;
        }
        struct timespec ts = {0, 200000};        /* 0.2 ms */
        nanosleep(&ts, NULL);
    }
    return WIFEXITED(st) ? WEXITSTATUS(st) : -1;
}

static void child_exec(char *const argv[], int out_fd)
{
    if (out_fd >= 0 && dup2(out_fd, 1) < 0) _exit(126);
    execv(argv[0], argv);
    _exit(127);
}

/* Capture the child's stdout from a temp file, not a pipe.
 *
 * A pipe is wrong for this benchmark: the launcher FORKS worker children,
 * and a forked child inherits the write end, so the read side never sees
 * EOF until every worker exits. Reading to EOF therefore blocks, and the
 * launcher's own timeout handler then fires and kills it -- which showed
 * up as "terminated -- killing worker process groups" and invalid
 * samples. A regular file decouples capture from worker lifetime. */
static void drain_output(int out_fd, struct arm_result *r)
{
    r->out[0] = 0;
    if (out_fd < 0) return;
    if (lseek(out_fd, 0, SEEK_SET) < 0) return;
    ssize_t got = read(out_fd, r->out, OUT_CAP - 1);
    if (got > 0) r->out[got] = 0;
    else r->out[0] = 0;
    /* Reset for reuse. The offset MUST go back to 0 as well: the child
     * inherits this same open file description (fork, or posix_spawn's
     * dup2 of the same description), so the write offset is shared with
     * us. Truncating without rewinding would leave the next child's
     * bytes at a non-zero offset, producing a sparse hole of NUL bytes
     * that the guard then (correctly) rejects. */
    if (ftruncate(out_fd, 0) == 0)
        (void)lseek(out_fd, 0, SEEK_SET);
}

static void run_fork_exec(char *const argv[], int out_fd,
                           struct arm_result *r)
{
    double t0 = now_ms();
    pid_t p = fork();
    if (p < 0) { r->ms = 0; r->rc = -1; r->guard_ok = 0; r->out[0] = 0; return; }
    if (p == 0) child_exec(argv, out_fd);
    r->rc = wait_bounded(p, TIMEOUT_S);
    r->ms = now_ms() - t0;
    drain_output(out_fd, r);
}

static void run_posix_spawn(char *const argv[], int out_fd,
                            struct arm_result *r)
{
    double t0 = now_ms();
    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    if (out_fd >= 0)
        posix_spawn_file_actions_adddup2(&fa, out_fd, STDOUT_FILENO);
    pid_t p = 0;
    int rc = posix_spawn(&p, argv[0], &fa, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&fa);
    if (rc != 0) {
        r->ms = now_ms() - t0; r->rc = rc; r->guard_ok = 0; r->out[0] = 0;
        return;
    }
    r->rc = wait_bounded(p, TIMEOUT_S);
    r->ms = now_ms() - t0;
    drain_output(out_fd, r);
}

/* Exact-output guard. In --fork-only mode the launcher's whole expected
 * output is one self-report line. Anything else means we measured a
 * different program than we think. */
static int output_guard_ok(const struct arm_result *r, int workers)
{
    if (r->rc != 0) return 0;
    char expect[64];
    snprintf(expect, sizeof expect, "CLEANROOM workers=%d fork_ms=", workers);
    return strstr(r->out, expect) != NULL;
}

/* ---------------------------------------------------------------- stats */
struct stats { double *v; int n; int failed; int timeout; int guard_fail; };

static void stats_init(struct stats *s, int cap)
{
    s->v = calloc((size_t)cap, sizeof *s->v);
    s->n = 0; s->failed = 0; s->timeout = 0; s->guard_fail = 0;
}

static void stats_add(struct stats *s, const struct arm_result *r, int workers)
{
    if (r->rc == 124) { s->timeout++; return; }
    if (r->rc != 0)   { s->failed++; return; }
    if (!output_guard_ok(r, workers)) { s->guard_fail++; return; }
    s->v[s->n++] = r->ms;
}

static void stats_report(const char *label, struct stats *s)
{
    if (s->n == 0) {
        printf("%-12s NO VALID SAMPLES (failed=%d timeout=%d guard_fail=%d)\n",
               label, s->failed, s->timeout, s->guard_fail);
        return;
    }
    qsort(s->v, (size_t)s->n, sizeof *s->v, cmp_double);
    double sum = 0.0;
    for (int i = 0; i < s->n; i++) sum += s->v[i];
    double mean = sum / s->n;
    double med = (s->n % 2) ? s->v[s->n / 2]
                            : 0.5 * (s->v[s->n / 2 - 1] + s->v[s->n / 2]);
    double p95 = s->v[(int)((double)(s->n - 1) * 0.95)];
    printf("%-12s n=%-4d min=%7.3f med=%7.3f mean=%7.3f p95=%7.3f max=%7.3f"
           "  spread(p95-min)=%7.3f ms   [failed=%d timeout=%d guard_fail=%d]\n",
           label, s->n, s->v[0], med, mean, p95, s->v[s->n - 1],
           p95 - s->v[0], s->failed, s->timeout, s->guard_fail);
}

static void usage(const char *p)
{
    fprintf(stderr,
        "usage: %s <launcher> <substrate.so> <plugin.so> <func> <workers> <iters>\n"
        "       [--ballast-mb N]   resident ballast in the launching process\n"
        "       [--workers N]      override the positional workers value\n",
        p);
}

int main(int argc, char **argv)
{
    long ballast_mb = 0;
    int workers_override = -1;
    const char *pos[7]; int npos = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--ballast-mb") == 0 && i + 1 < argc) {
            ballast_mb = atol(argv[++i]);
        } else if (strcmp(argv[i], "--workers") == 0 && i + 1 < argc) {
            workers_override = atoi(argv[++i]);
        } else if (npos < 7) {
            pos[npos++] = argv[i];
        } else {
            usage(argv[0]); return 64;
        }
    }
    if (npos < 6) { usage(argv[0]); return 64; }

    const char *launcher = pos[0];
    const char *so       = pos[1];   /* substrate: libforkrun */
    const char *plug     = pos[2];   /* loadable, must export forkrun_use_ctx */
    const char *func     = pos[3];
    int workers = workers_override > 0 ? workers_override : atoi(pos[4]);
    int iters   = atoi(pos[5]);
    if (workers < 1) workers = 1;
    if (iters < 1) iters = 1;

    printf("# launcher        : %s\n", launcher);
    printf("# ballast target  : %ld MiB\n", ballast_mb);
    /* Both baselines captured BEFORE the ballast is allocated. */
    long rss0 = current_rss_kb();
    long sm0 = smaps_rss_kb();
    printf("# RSS before ballast (smaps_rollup, AUTHORITATIVE): %ld KiB "
           "(%.1f MiB)\n", sm0, sm0 > 0 ? sm0 / 1024.0 : 0.0);
    printf("# RSS before ballast (statm, cross-check)           : %ld KiB "
           "(%.1f MiB)\n", rss0, rss0 > 0 ? rss0 / 1024.0 : 0.0);

    /* Safety: do not allocate ballast that could exhaust the host. We
     * report and refuse rather than silently substituting a smaller
     * value while still labelling it with the requested target. */
    void *ballast = NULL;
    if (ballast_mb > 0) {
        long avail = mem_available_kb();
        long need = ballast_mb * 1024;
        /* Leave a 4 GiB floor for everything else on the box. */
        if (avail > 0 && need > (avail - 4L * 1024 * 1024)) {
            printf("# REFUSING ballast: MemAvailable=%ld MiB, need=%ld MiB, "
                   "floor=4096 MiB. Skipping this level; NOT substituting.\n",
                   avail / 1024, ballast_mb);
            ballast_mb = 0;
            ballast = NULL;
        } else {
            ballast = touch_resident_mb(ballast_mb);
            if (!ballast) {
                printf("# REFUSING ballast: mmap/touch of %ld MiB failed. "
                       "Skipping this level; NOT substituting.\n", ballast_mb);
                ballast_mb = 0;
            }
        }
    }
    long rss1 = current_rss_kb();
    long sm1 = smaps_rss_kb();
    printf("# RSS after ballast (smaps_rollup, AUTHORITATIVE): %ld KiB "
           "(%.1f MiB)\n", sm1, sm1 > 0 ? sm1 / 1024.0 : 0.0);
    printf("# RSS after ballast (statm, cross-check)           : %ld KiB "
           "(%.1f MiB)\n", rss1, rss1 > 0 ? rss1 / 1024.0 : 0.0);
    if (ballast_mb == 0) {
        printf("# ballast: NONE requested (baseline control level); "
               "statm/smaps disagreement %ld KiB\n",
               (rss1 > 0 && rss0 > 0 && sm0 > 0 && sm1 > 0)
                   ? (rss1 - rss0) - (sm1 - sm0) : 0);
    } else if (sm0 > 0 && sm1 > 0) {
        printf("# ballast VERIFIED (smaps_rollup): %.1f MiB resident vs "
               "%.1f MiB target (%.2f%%); statm/smaps disagreement %ld KiB\n",
               (sm1 - sm0) / 1024.0, (double)ballast_mb,
               (sm1 - sm0) / 1024.0 / (double)ballast_mb * 100.0,
               (rss1 > 0 && rss0 > 0) ? (rss1 - rss0) - (sm1 - sm0) : 0);
    } else {
        printf("# ballast VERIFICATION UNAVAILABLE (smaps_rollup "
               "unreadable) — residency NOT confirmed\n");
    }
    printf("# workers          : %d\n# iters            : %d "
           "(interleaved A/B, 3 warmups discarded)\n", workers, iters);

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

    /* Capture file for the launcher's stdout (see drain_output). */
    char cap_path[] = "/tmp/forkrun_bench_capXXXXXX";
    int cap_fd = mkstemp(cap_path);
    if (cap_fd < 0) { perror("mkstemp"); return 1; }

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

    struct arm_result r;
    for (int i = 0; i < 3; i++)              /* warmups, discarded */
        run_fork_exec(largv, cap_fd, &r);

    struct stats A, B;
    stats_init(&A, iters); stats_init(&B, iters);

    for (int i = 0; i < iters; i++) {
        run_fork_exec(largv, cap_fd, &r);
        stats_add(&A, &r, workers);
        run_posix_spawn(largv, cap_fd, &r);
        stats_add(&B, &r, workers);
    }

    /* Launcher's own worker-fork timing: reported separately, never merged
     * with the launch-mechanism delta. */
    const char *fr = strstr(r.out, "fork_ms=");
    printf("# launcher self-report (arm B, WORKER fork cost -- common to "
           "both arms): %.140s\n", fr ? fr : "(none)");

    stats_report("fork+exec", &A);
    stats_report("posix_spawn", &B);
    if (A.n > 0 && B.n > 0) {
        qsort(A.v, (size_t)A.n, sizeof *A.v, cmp_double);
        qsort(B.v, (size_t)B.n, sizeof *B.v, cmp_double);
        double ma = A.v[A.n / 2], mb = B.v[B.n / 2];
        double xa = 0.0, xb = 0.0;
        for (int i = 0; i < A.n; i++) xa += A.v[i];
        for (int i = 0; i < B.n; i++) xb += B.v[i];
        xa /= A.n; xb /= B.n;
        printf("# delta MEDIAN  : posix_spawn - fork+exec = %+.3f ms (%+.2f%%)\n",
               mb - ma, ma > 0 ? (mb - ma) / ma * 100.0 : 0.0);
        printf("# delta MEAN    : posix_spawn - fork+exec = %+.3f ms (%+.2f%%)\n",
               xb - xa, xa > 0 ? (xb - xa) / xa * 100.0 : 0.0);
    }
    free(A.v); free(B.v);
    if (ballast) munmap(ballast, (size_t)ballast_mb * 1024u * 1024u);
    close(src_fd); close(res_fd); close(sta_fd); close(cap_fd);
    unlink(src_path); unlink(res_path); unlink(stat_path); unlink(cap_path);
    return 0;
}