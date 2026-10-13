/* fr_udf_fork -- measure the pre-fork vs post-fork candidates for C0.4.
 *
 * DECISION-01 section 9 leaves this open: the interpreter is process
 * global, so it is initialised either ONCE in the parent before fork
 * (pre-fork) or once per child after fork (post-fork). Phase 1 did not
 * touch the question because it never forked.
 *
 * This driver exists to answer two things, in this order:
 *
 *   1. DOES IT WORK. Pre-fork is only a candidate if a forked child can
 *      still run Python. If CPython's runtime does not survive fork, the
 *      performance question is moot and post-fork wins by default.
 *   2. WHAT DOES IT COST. Post-fork pays a full interpreter start per
 *      worker; pre-fork pays one, shared by copy-on-write.
 *
 * Correctness first, then the number. A benchmark that only prints a
 * timing would happily report a fast wrong answer.
 *
 * The child protocol is deliberately tiny: one UDF call per child, result
 * written to a pipe as a status byte, so the parent can prove each child
 * actually produced output rather than inferring success from its exit.
 */

#define _GNU_SOURCE
#include "fr_udf.h"
/* For the --version-probe: the driver is linked against a specific
 * libpython and the harness needs to know WHICH. Including Python.h
 * gives Py_GetVersion; the include path is already per-minor. */
#include <Python.h>

#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>

/* ---- C0.6 measurement support --------------------------------------
 *
 * The roadmap asks for more than a ratio: peak RSS AND PSS/USS, the
 * THP state, and the parent's resident size at the moment of the fork
 * (30/64/128/256/554/2127 MB). The parent-RSS axis is the one that
 * decides the fleet-memory question, because a forked child inherits
 * the parent's resident pages copy-on-write, so "one interpreter shared"
 * is only as cheap as the pages nobody dirties.
 *
 * PSS matters more than RSS here and RSS is what most tools report.
 * With N children over one parent, RSS double-counts every shared page
 * N times, which is precisely the quantity the shared-interpreter claim
 * rests on. PSS divides shared pages by the number of sharers, so it
 * answers "what does one more worker actually cost".
 */

/* Inflate the parent's resident set to `mb` megabytes by touching real
 * pages. Untouched pages would be reclaimed and never inherited, so the
 * touch is the measurement rather than an optimisation. */
static int inflate_parent_rss(long mb)
{
    long page = sysconf(_SC_PAGESIZE);
    long want = mb * 1024L * 1024L;
    if (want <= 0) return 0;
    /* VOLATILE, and the result is consumed. A plain loop storing into a
     * malloc'd buffer that is never read is dead code, and at -O2 GCC
     * removes it: the first version of this reported parent_rss_kb 6004
     * after asking for 256 MB, because the pages were never touched and
     * therefore never resident and never inherited. The knob silently
     * did nothing, which is the failure mode this whole exercise exists
     * to avoid -- a measurement that measures nothing.
     *
     * The volatile store is load-bearing for the same reason. */
    volatile char *p = (volatile char *)malloc((size_t)want);
    if (!p) return -1;
    volatile unsigned long sink = 0;
    for (long off = 0; off < want; off += page) {
        p[off] = 1;
        sink += (unsigned long)p[off];
    }
    /* Keep the pages from being reclaimed: touch one byte per page
     * again after the fork point would be too late, so hold the
     * allocation and a reference to it for the process lifetime. */
    static volatile char *keep = NULL;
    static unsigned long keep_sink = 0;
    keep = p;
    keep_sink = sink;
    (void)keep_sink;
    return 0;
}

static double now_s(void);

/* Monotonic nanoseconds, for the report's sample timestamp.
 *
 * The review asks for timestamps alongside the raw per-PID numbers, so
 * two children that "should" have sampled simultaneously can be checked
 * rather than assumed to have. Defined here rather than borrowed from
 * the launcher: the driver links only fr_udf.c, and now_ns lives in
 * forkrun_cleanroom.c. */
static long now_ns(void)
{
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return -1;
    return (long)ts.tv_sec * 1000000000L + (long)ts.tv_nsec;
}

/* What a child reports back: outcome plus its OWN memory footprint.
 *
 * IDENTITY MATTERS. The review's point 2: every report carries a
 * version and a pid, and the parent validates that each report
 * corresponds to the child it is waiting for -- rather than parsing
 * whatever bytes arrive next. Without that, a duplicated or reordered
 * report is indistinguishable from a correct one, and the fleet sum is
 * silently wrong.
 *
 * FIXED SIZE on purpose, and asserted with _Static_assert, because a
 * struct whose layout differs between the writer and the reader is the
 * class of bug this whole protocol has already produced twice (a
 * one-byte report read as a struct; an ack byte consumed as report
 * data). */
#define FR_REPORT_VERSION 1
#define MAX_CHILDREN 256

struct child_report {
    unsigned int version;      /* FR_REPORT_VERSION */
    int          pid;          /* the child that measured itself */
    char         status;
    char         _pad[3];
    long         rss_kb;
    long         pss_kb;
    long         uss_kb;
    long long    t_ns;         /* monotonic at sample time */
};

/* 48, not the 40 the arithmetic suggested: the 12-byte header is
 * followed by 8-byte-aligned longs, so 4 bytes of padding land at
 * offset 12. Asserted rather than documented, and the assert is what
 * caught it -- the first guess (40) and the second (44) both FAILED to
 * compile. A layout that silently shifts every field is exactly the bug
 * class this protocol has already produced twice.
 *
 * Measured: version@0 pid@4 status@8 rss@16 pss@24 uss@32 t_ns@40. */
_Static_assert(sizeof(struct child_report) == 48,
               "report layout changed; writer and reader must agree");

/* Full-transfer helpers.
 *
 * A pipe is a BYTE STREAM. `read(fd, &struct, sizeof struct)` is not
 * guaranteed to return the whole struct: it can return a short count,
 * and read() is interruptible by a signal. The review lists this as the
 * first failure mode to audit, and the earlier one-byte ack is a live
 * demonstration that the byte-level framing here is unforgiving.
 *
 * These loop until the whole object is transferred, retrying EINTR,
 * and treat EOF mid-object as an error rather than a short success. */
/* A blocking wait here would be a hang, not a slow run. The ack phase in
 * particular CANNOT rely on EOF: a child that fails before acknowledging
 * is still alive and still holding its write end, waiting for a release
 * that the parent will not send until it has seen the ack. That is a
 * deadlock by construction, so every wait is bounded and a timeout is
 * an error, not a partial success. */
static int io_timeout_ms(void)
{
    static int cached = -1;
    if (cached < 0) {
        const char *e = getenv("FR_UDF_IO_TIMEOUT_MS");
        cached = (e && atoi(e) > 0) ? atoi(e) : 10000;
    }
    return cached;
}

static int wait_fd(int fd, short events)
{
    for (;;) {
        struct pollfd pf;
        pf.fd = fd; pf.events = events; pf.revents = 0;
        int r = poll(&pf, 1, io_timeout_ms());
        if (r < 0 && errno == EINTR) continue;
        if (r < 0) return -1;
        if (r == 0) { errno = ETIMEDOUT; return 0; }
        return 1;               /* POLLHUP/POLLERR still land on the I/O */
    }
}

static int write_all(int fd, const void *buf, size_t n)
{
    const char *p = (const char *)buf;
    size_t done = 0;
    while (done < n) {
        if (wait_fd(fd, POLLOUT) <= 0) return -1;
        ssize_t w = write(fd, p + done, n - done);
        if (w > 0) { done += (size_t)w; continue; }
        if (w < 0 && errno == EINTR) continue;
        return -1;              /* EPIPE, EAGAIN, anything else */
    }
    return 0;
}

static int read_all(int fd, void *buf, size_t n)
{
    char *p = (char *)buf;
    size_t done = 0;
    while (done < n) {
        if (wait_fd(fd, POLLIN) <= 0) return -1;
        ssize_t r = read(fd, p + done, n - done);
        if (r > 0) { done += (size_t)r; continue; }
        if (r < 0 && errno == EINTR) continue;
        return -1;              /* EOF or error, mid-object */
    }
    return 0;
}

/* Fault injection, driven by tools/protocol_faults.py. Each hook fires for
 * exactly ONE child, so the run keeps N-1 good reports: that is what
 * proves a single defect invalidates the whole sample instead of
 * quietly shrinking it. */
static int fault(const char *name)
{
    const char *v = getenv(name);
    return v && *v && strcmp(v, "0") != 0;
}
static int fault_child(const char *name, int c)
{
    return c == 0 && fault(name);
}

/* Per-run accumulation, filled from the children's reports. */
static long child_pss_kb = 0;
static long child_uss_kb = 0;
static long child_rss_kb = 0;
static int  child_sampled = 0;

/* Per-ARM snapshots, indexed [0]=post-fork [1]=pre-fork.
 *
 * The fleet-memory QUESTION is which candidate costs more physical
 * memory, so reporting only the last arm answers nothing. run() is
 * called twice; each arm's totals are kept separately and printed
 * side by side. */
static long arm_child_pss[2] = {0, 0};
static long arm_child_uss[2] = {0, 0};
static long arm_child_rss[2] = {0, 0};

/* Integrity counters. Every one of these INVALIDS a sample rather than
 * degrading it: a fleet figure computed from an incomplete barrier or a
 * report from the wrong process is not a smaller measurement, it is a
 * wrong one, and it prints just as confidently. */
static int ack_missing = 0;
static int report_bad = 0;
static int release_failed = 0;
static int child_pids[MAX_CHILDREN];
static long arm_parent_pss[2] = {0, 0};
static long arm_parent_rss[2] = {0, 0};
static int  arm_sampled[2]   = {0, 0};

/* Current and peak RSS are DIFFERENT quantities and both are wanted.
 *
 * ru_maxrss is the high-water mark and is what "peak RSS" means; the
 * `Rss:` line in smaps_rollup is the CURRENT resident set. The first
 * version reported only one `rss_kb`, seeded from ru_maxrss and then
 * OVERWRITTEN by the smaps value -- so the field named as peak was in
 * fact current whenever smaps_rollup was readable, which is on every
 * modern kernel. Reporting both removes the ambiguity rather than
 * picking a winner.
 *
 * -1 means "not measured" and is never substituted with another
 * quantity. Conflating RSS, PSS and USS is the error being avoided, so
 * a missing source leaves its own field at -1. */
static void read_smaps_rollup(const char *path, long *rss_kb, long *pss_kb,
                              long *uss_kb);

static void read_self_mem(long *rss_kb, long *pss_kb, long *uss_kb)
{
    read_smaps_rollup("/proc/self/smaps_rollup", rss_kb, pss_kb, uss_kb);
}

static void read_mem_self(long *rss_cur_kb, long *rss_peak_kb,
                          long *pss_kb, long *uss_kb)
{
    *rss_cur_kb = *pss_kb = *uss_kb = -1;
    *rss_peak_kb = -1;
    struct rusage ru;
    if (getrusage(RUSAGE_SELF, &ru) == 0) *rss_peak_kb = (long)ru.ru_maxrss;
    read_smaps_rollup("/proc/self/smaps_rollup", rss_cur_kb, pss_kb, uss_kb);
}

static void read_smaps_rollup(const char *path, long *rss_kb, long *pss_kb,
                              long *uss_kb)
{
    FILE *f = fopen(path, "r");
    if (!f) return;
    /* USS = Private_Clean + Private_Dirty + Private_Hugetlb.
     *
     * The first version skipped Private_Clean and, worse, accumulated
     * into a value initialised to -1 -- so the sum started one kilobyte
     * below zero AND omitted the entire private-clean category. Both
     * are wrong: USS counts all three private categories, and a
     * partially-clean process (a file-backed library mapped MAP_PRIVATE)
     * has a large private-clean component that was being dropped
     * entirely. */
    long uss = 0;
    int have_uss = 0;
    char line[256];
    while (fgets(line, sizeof line, f)) {
        long v;
        if (sscanf(line, "Rss: %ld kB", &v) == 1) *rss_kb = v;
        else if (sscanf(line, "Pss: %ld kB", &v) == 1) *pss_kb = v;
        else if (sscanf(line, "Private_Clean: %ld kB", &v) == 1) {
            uss += v; have_uss = 1;
        } else if (sscanf(line, "Private_Dirty: %ld kB", &v) == 1) {
            uss += v; have_uss = 1;
        } else if (sscanf(line, "Private_Hugetlb: %ld kB", &v) == 1) {
            uss += v; have_uss = 1;
        }
    }
    fclose(f);
    if (have_uss) *uss_kb = uss;
}

static int set_thp(const char *mode)
{
    if (!mode) return 0;                     /* leave inherited state */
    if (strcmp(mode, "on") == 0) return prctl(PR_SET_THP_DISABLE, 0, 0, 0, 0);
    if (strcmp(mode, "off") == 0) return prctl(PR_SET_THP_DISABLE, 1, 0, 0, 0);
    return -1;
}

/* The ONE fork site for this driver.
 *
 * Centralised deliberately. CPython requires every fork of an
 * initialised interpreter to be choreographed (see fr_udf.h), and the
 * whole point of a helper is that an individual call site cannot forget.
 * Three separate forks here (post-fork run, pre-fork run, respawn) each
 * had to be correct -- three chances to get one wrong.
 *
 *   parent: fr_udf_before_fork() / fork() / fr_udf_after_fork_parent()
 *   child:  fr_udf_after_fork_child() before any Python C API call
 *
 * The parent hook runs even when fork() FAILS, which is why it sits
 * after the call rather than inside the success branch.
 *
 * When the parent has no interpreter (the post-fork measurement run),
 * there is nothing to choreograph and the hooks correctly refuse. */
static pid_t udf_fork(void)
{
    int have = fr_udf_is_initialized();
    if (have && fr_udf_before_fork() != FR_UDF_OK) {
        fprintf(stderr, "  udf_fork: before_fork failed: %s\n",
                fr_udf_last_error());
        return -1;
    }
    pid_t p = fork();
    if (p == 0) {
        if (have) {
            /* CHILD. Must precede any other Python call here, and must
             * NOT be paired with the parent hook: running
             * PyOS_AfterFork_Parent() in the child unlocks the mutex that
             * PyOS_AfterFork_Child() is responsible for, which aborts
             * with "PyMutex_Unlock: unlocking mutex that is not locked".
             * That is exactly what happened here -- the first wiring ran
             * both hooks in both processes. */
            fr_udf_after_fork_child();
        }
        return p;
    }
    if (have) {
        /* PARENT only. Runs on the failure path too (p < 0), because
         * PyOS_BeforeFork() already took locks that must be released. */
        fr_udf_after_fork_parent();
    }
    return p;
}

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

/* Run `nchildren` children, each calling module:attr `iters` times over
 * `batch`. Returns elapsed seconds. Every child's outcome is checked;
 * a mismatch is reported rather than averaged away. */
static double run(int pre_fork, int nchildren, int iters,
                  const char *module, const char *attr,
                  const char *batch, size_t blen,
                  const char *const *roots, int nroots,
                  int *failures)
{
    int (*data)[2] = calloc((size_t)nchildren, sizeof *data);
    int (*gate)[2] = calloc((size_t)nchildren, sizeof *gate);
    if (!data || !gate) { perror("calloc"); exit(1); }

    /* Per-ARM, not per-process: run() is called twice (post-fork, then
     * pre-fork), and a static accumulator carried the first arm's
     * children into the second -- "children_sampled: 8 of 4". */
    child_pss_kb = child_uss_kb = child_rss_kb = 0;
    child_sampled = 0;
    ack_missing = 0;
    report_bad = 0;
    release_failed = 0;

    /* The parent's OWN footprint DURING this arm. Sampling it only at the
     * very end (after both runs, and after fr_udf_finalize) made the
     * fleet figure ambiguous: a parent-side number that moves between
     * the two arms cannot be attributed to either. */
    {
        long r = -1, pss = -1, uss = -1;
        read_self_mem(&r, &pss, &uss);
        arm_parent_rss[pre_fork ? 1 : 0] = r;
        arm_parent_pss[pre_fork ? 1 : 0] = pss;
    }

    /* ALL pipes are created BEFORE any fork.
     *
     * Creating each pipe inside the fork loop meant child N inherited
     * every previously-created pipe's write end, held open via the
     * parent's arrays. That is survivable for data, but it means the
     * parent can never observe EOF on a pipe whose child has died,
     * because the PARENT ITSELF holds the write end it is reading from.
     * A child that died before writing then hung the parent forever --
     * observed as two zombies and a parent blocked in anon_pipe_read.
     *
     * Two pipes per child, one per direction, so neither end has to be
     * shared between a reader and a writer:
     *     data[c]  child -> parent   (ack, then report)
     *     gate[c]  parent -> child   (release) */
    for (int c = 0; c < nchildren; c++) {
        if (pipe(data[c]) != 0) { perror("pipe(data)"); exit(1); }
        if (pipe(gate[c]) != 0) { perror("pipe(gate)"); exit(1); }
    }

    double t0 = now_s();
    for (int c = 0; c < nchildren; c++) {
        /* Flush before every fork. A child that calls Py_FinalizeEx()
         * flushes stdio, and it has inherited THIS process's buffer --
         * so without this each child re-prints the header on the way
         * out. Cosmetic, but it makes the output look like the run
         * happened N times. */
        fflush(stdout);
        int *fd_data = data[c];
        int *fd_gate = gate[c];
        pid_t pid = udf_fork();
        if (pid < 0) { perror("fork"); exit(1); }
        if (pid == 0) {
            /* Child. Report one status byte; never write to stdout, which
             * is the parent's line-buffered table. */
            /* Close every pipe except this child's own two, so the
             * parent gets EOF the moment this child dies. */
            for (int j = 0; j < nchildren; j++) {
                if (j == c) continue;
                close(data[j][0]); close(data[j][1]);
                close(gate[j][0]); close(gate[j][1]);
            }
            char status = 0;
            if (pre_fork) {
                /* Inherited interpreter: must NOT initialise again. */
                if (!fr_udf_is_initialized()) status = 1;
            } else {
                /* Post-fork must install the SAME validated roots the
                 * parent would have. Initialising with no roots is not a
                 * neutral default: site_import=0 means the UDF's own
                 * module is then not importable at all, and every call
                 * fails. Which is exactly what happened the first time
                 * this ran -- the driver reported 4/4 failures, which is
                 * the point of having it check instead of printing a
                 * timing. */
                if (fr_udf_init(roots, nroots) != FR_UDF_OK) status = 2;
            }
            if (status == 0) {
                for (int i = 0; i < iters; i++) {
                    char *out = NULL; size_t n = 0;
                    int rc = fr_udf_call(module, attr, batch, blen, &out, &n);
                    if (rc != FR_UDF_OK) { status = 3; break; }
                    /* Prove the result is real, not just non-error. */
                    if (n == 0) { status = 4; break; }
                    fr_udf_free(out);
                }
            }
            /* BARRIER before sampling.
             *
             * Self-sampling at exit is WRONG for PSS. PSS divides each
             * shared page by the number of processes MAPPING it, and the
             * children exit one at a time -- so the last child to sample
             * sees a divisor near 1 and reports nearly the whole parent
             * as if it were private. Summing staggered self-reports
             * therefore OVER-COUNTS, which showed up as pre-fork
             * "using" +29% PSS with a 256MB parent, a result that made no
             * physical sense: 8 children each inheriting a 256MB COW
             * mapping cannot collectively cost 646MB when the mapping
             * totals 256MB.
             *
             * The barrier makes every sample simultaneous: each child
             * reports "done", and none samples or exits until the parent
             * has released them all. Then every divisor is the full
             * mapper count and the sum IS the fleet footprint. */
            /* ack on the write end, release read from the READ end --
             * the opposite end to the one it writes on. Getting this
             * backwards fails with EBADF and looks like a no-op. */
            if (fault_child("FR_FAULT_EXIT_BEFORE_BARRIER", c)) _exit(92);
            if (!fault_child("FR_FAULT_NO_ACK", c)) {
                char sig = 1;
                if (write_all(fd_data[1], &sig, 1) != 0) { _exit(90); }
            }
            { char go = 0;
              if (read_all(fd_gate[0], &go, 1) != 0)   { _exit(90); } }

            /* Sample SELF at peak -- after the work, before teardown.
             *
             * This is the measurement C0.6 asks for and that the parent
             * cannot make: by the time the parent could read
             * /proc/<pid>/smaps_rollup the child may already have exited,
             * and reading it while the child is alive still races with
             * the child's own exit. Self-measurement has neither
             * problem.
             *
             * PSS is the right per-child number precisely because it
             * divides each shared page by the number of sharers: summing
             * PSS over parent and children yields the FLEET's actual
             * physical footprint. RSS cannot be summed -- it would count
             * every shared page once per worker, which is precisely the
             * quantity the shared-interpreter claim rests on. */
            struct child_report rep;
            memset(&rep, 0, sizeof rep);
            rep.version = FR_REPORT_VERSION;
            rep.pid = (int)getpid();
            rep.status = status;
            rep.t_ns = now_ns();
            read_self_mem(&rep.rss_kb, &rep.pss_kb, &rep.uss_kb);
            if (!pre_fork) fr_udf_finalize();
            if (fault_child("FR_FAULT_DIE_BEFORE_REPORT", c)) _exit(93);
            if (fault_child("FR_FAULT_BAD_VERSION", c))
                rep.version = 0xDEADBEEFu;
            if (fault_child("FR_FAULT_BAD_PID", c))
                rep.pid = 0x7FFFFFFFu;
            if (fault_child("FR_FAULT_TRUNCATED", c)) {
                /* Half a record: read_all must treat the short tail as an
                 * error rather than as a report with zeroed fields. */
                if (write_all(fd_data[1], &rep, sizeof rep / 2) != 0)
                    _exit(91);
                close(fd_data[1]);
                close(fd_gate[0]);
                _exit(0);
            }
            if (write_all(fd_data[1], &rep, sizeof rep) != 0) _exit(91);
            if (fault_child("FR_FAULT_DUPLICATE", c)) {
                /* The extra bytes must not be mistaken for another
                 * child's record. */
                if (write_all(fd_data[1], &rep, sizeof rep) != 0) _exit(91);
            }
            close(fd_data[1]);
            close(fd_gate[0]);
            _exit(0);
        }
        child_pids[c] = (int)pid;
    }

    /* The parent must not hold the WRITE end of any pipe it reads. If it
     * does, EOF is unreachable and a child that dies is invisible: the
     * read blocks until the timeout instead of failing fast. This close
     * has to happen BEFORE collection, not after. */
    for (int c = 0; c < nchildren; c++) {
        close(data[c][1]);
        close(gate[c][0]);
    }

    /* Parent: collect every child's status before finalising, because a
     * pre-fork child is still using the shared interpreter until it
     * exits. */
    /* TWO PHASES, and the ack MUST be drained before the release.
     *
     * Child: write 1 ack byte, block on read, sample, write the report.
     * Parent: read the ack from EVERY child, THEN release every child,
     *         THEN read the reports.
     *
     * Releasing before draining desynchronised the pipe: the parent
     * wrote 'go' into a pipe still holding each child's ack byte, so the
     * following read() of sizeof rep consumed the ack plus 27 bytes of
     * the report. Every field was shifted, which is how a 271 MB child
     * reported rss=68794368 kB (68 GB) and the run claimed 98 GB of
     * fleet PSS -- physically impossible, and the tell that the protocol
     * rather than the kernel was wrong.
     *
     * Draining first is also what makes the barrier work: every child is
     * released only after every child has reported "done", so all
     * samples see the same mapper count. */
    for (int c = 0; c < nchildren; c++) {
        char ack = 0;
        if (read_all(data[c][0], &ack, 1) != 0) {
            /* Barrier INCOMPLETE. Recorded rather than tolerated: the
             * whole point of the barrier is that every child samples
             * with every child mapped, so a missing ack means the
             * divisor for PSS is wrong for whoever is still alive. */
            ack_missing++;
            fprintf(stderr, "  child %d: no barrier ack\n", c);
        }
    }
    for (int c = 0; c < nchildren; c++) {
        char go = 1;
        if (fault_child("FR_FAULT_RELEASE_FAIL", c)) {
            /* Make the release genuinely impossible, rather than
             * skipping it silently: the child's read must then see EOF
             * and the parent must notice. */
            close(gate[c][1]);
            gate[c][1] = -1;
        }
        if (write_all(gate[c][1], &go, 1) != 0) {
            fprintf(stderr, "  child %d: RELEASE FAILED (errno=%d)\n",
                    c, errno);
            release_failed++;
        }
    }

    for (int c = 0; c < nchildren; c++) {
        struct child_report rep;
        memset(&rep, 0, sizeof rep);
        rep.status = -1;
        int got = read_all(data[c][0], &rep, sizeof rep);
        char status = rep.status;
        /* Validate BEFORE trusting anything in it. A report that is not
         * from this run, or from the child we are waiting for, must not
         * reach the aggregate: it would silently inflate or deflate the
         * fleet figure while still printing a number. */
        int rep_ok = (got == 0)
                     && rep.version == FR_REPORT_VERSION
                     && rep.pid == (int)child_pids[c];
        if (!rep_ok) {
            fprintf(stderr, "  child %d: BAD REPORT (got=%d ver=%u "
                    "pid=%d expected=%d) -- excluded\n", c, got,
                    rep.version, rep.pid, (int)child_pids[c]);
            report_bad++;
        }

        /* Reap FIRST, then look for anything left on the pipe. Once the
         * child is reaped it can never write again, so leftover bytes are
         * definitive: a duplicate or a stray second record. Reading
         * exactly sizeof rep and never checking what follows is how a
         * doubled report would sit unnoticed in the buffer forever --
         * the arithmetic still looks reasonable, so nothing else would
         * reveal it. */
        int wstatus = 0;
        waitpid(-1, &wstatus, 0);
        {
            struct pollfd tp;
            tp.fd = data[c][0]; tp.events = POLLIN; tp.revents = 0;
            /* Poll first so the check cannot block, but decide on the
             * byte COUNT, not on the poll flags: a closed pipe reports
             * POLLHUP (and POLLIN on Linux) with nothing to read, and
             * keying on the flags would flag every healthy child. */
            if (poll(&tp, 1, 0) > 0) {
                char extra[64];
                ssize_t nleft = read(data[c][0], extra, sizeof extra);
                if (nleft <= 0) {
                    /* clean EOF: the child wrote exactly one record */
                } else {
                fprintf(stderr, "  child %d: %ld trailing byte(s) after the "
                        "report -- duplicate or stray record, child "
                        "excluded\n", c, (long)nleft);
                report_bad++;
                rep_ok = 0;
                }
            }
        }

        if (rep_ok) {
            /* Fleet memory: the children's own PSS, summed. The parent's
             * is added at finalisation, after the interpreter is torn
             * down -- which is why this is a CHILD number and the parent
             * figure elsewhere is not a substitute. */
            if (getenv("FR_DEBUG_CHILD_MEM")) {
                fprintf(stderr, "    child %d: pid=%d status=%d rss=%ld "
                        "pss=%ld uss=%ld t_ns=%lld\n", c, rep.pid,
                        (int)status, rep.rss_kb, rep.pss_kb, rep.uss_kb,
                        (long long)rep.t_ns);
            }
            child_pss_kb += rep.pss_kb;
            child_uss_kb += rep.uss_kb;
            child_rss_kb += rep.rss_kb;
            child_sampled++;
        }
        close(data[c][0]);
        close(gate[c][1]);
        /* sizeof rep, NOT 1. Extending the child's report from a status
         * byte to a struct left this check comparing against 1, so every
         * child counted as a failure and the run reported "8 of 8 failed"
         * while the reports were in fact arriving intact -- the reports
         * had been accumulated, and printed "children_sampled: 8 of 4".
         *
         * Worth recording: changing a wire protocol without updating the
         * validator produces a run that is *self-contradictory* rather
         * than obviously broken, and both symptoms were only visible
         * because the fleet block printed the sample count. */
        if (!rep_ok || status != 0) {
            /* Say WHICH signal. "exit -1" is what this printed for a
             * while and it distinguishes nothing between SIGABRT (a
             * fatal Python error), SIGSEGV, and a hang-kill -- which is
             * the difference between "the hook is wrong" and "the hook
             * exposed a real bug". */
            if (WIFSIGNALED(wstatus))
                fprintf(stderr, "  child %d FAILED (status %d, killed by "
                                "signal %d %s)\n", c, (int)status,
                        WTERMSIG(wstatus), strsignal(WTERMSIG(wstatus)));
            else if (WIFEXITED(wstatus))
                fprintf(stderr, "  child %d FAILED (status %d, exit %d)\n",
                        c, (int)status, WEXITSTATUS(wstatus));
            else
                fprintf(stderr, "  child %d FAILED (status %d, no status)\n",
                        c, (int)status);
            (*failures)++;
        }
    }
    arm_child_pss[pre_fork ? 1 : 0] = child_pss_kb;
    arm_child_uss[pre_fork ? 1 : 0] = child_uss_kb;
    arm_child_rss[pre_fork ? 1 : 0] = child_rss_kb;
    arm_sampled[pre_fork ? 1 : 0]   = child_sampled;

    /* Close our copies of every child's data-write end. Without this the
     * parent holds the write end of the pipe it reads, so a child that
     * dies is invisible and the read blocks forever instead of seeing
     * EOF. */
    double elapsed = now_s() - t0;
    free(data);
    free(gate);
    return elapsed;
}

/* Respawn probe (P1-3 section 5): does a RESPAWNED generation inherit
 * dirty interpreter state?
 *
 * The question matters because supervision respawns a worker onto the
 * same wid after a death. Under pre-fork every generation is a fresh
 * fork of the launcher, which still holds the PRISTINE pre-fork
 * interpreter -- the dead child's mutations died with it. Under
 * post-fork each generation initialises its own, which is also clean.
 * So the prediction is "clean" either way, and the reason to test it is
 * that a wrong answer here would mean respawned workers share mutable
 * Python state, which is a correctness bug nothing else would catch.
 *
 * Child A dirties interpreter state then dies simulating a crash.
 * Child B (the respawn) asks whether the state is still dirty.
 *
 * Returns 0 if the respawned generation is CLEAN, 1 if it is dirty. */
static int run_respawn(const char *module, const char *touch_attr,
                       const char *check_attr, const char *batch)
{
    int fds[2];
    if (pipe(fds) != 0) { perror("pipe"); return 1; }

    /* Generation 1: dirty the interpreter, then die without finalising. */
    pid_t p1 = udf_fork();
    if (p1 == 0) {
        close(fds[0]);
        char *out = NULL; size_t n = 0;
        (void)fr_udf_call(module, touch_attr, batch, strlen(batch), &out, &n);
        fr_udf_free(out);
        _exit(0);                      /* "died": no cleanup, no finalize */
    }
    int w = 0; waitpid(p1, &w, 0);

    /* Generation 2: the respawn, onto the same interpreter. */
    pid_t p2 = udf_fork();
    if (p2 == 0) {
        close(fds[0]);
        char status = 0;
        char *out = NULL; size_t n = 0;
        int rc = fr_udf_call(module, check_attr, batch, strlen(batch),
                             &out, &n);
        if (rc != FR_UDF_OK || n < 2) {
            status = 1;
        } else if (out[0] == 'y') {    /* "yes" -> state survived the death */
            status = 2;
        }
        fr_udf_free(out);
        ssize_t ignored = write(fds[1], &status, 1);
        (void)ignored;
        _exit(0);
    }
    close(fds[1]);
    char status = -1;
    ssize_t got = read(fds[0], &status, 1);
    close(fds[0]);
    waitpid(p2, &w, 0);

    if (got != 1) { fprintf(stderr, "  respawn probe: no status\n"); return 1; }
    if (status == 2) {
        printf("  respawn : DIRTY  (a respawned generation inherited "
               "interpreter state from the dead one)\n");
        return 1;
    }
    if (status != 0) {
        printf("  respawn : INCONCLUSIVE (status %d)\n", (int)status);
        return 1;
    }
    printf("  respawn : CLEAN  (a respawned generation does NOT inherit "
           "interpreter state)\n");
    return 0;
}

/* Negative control for run_respawn.
 *
 * run_respawn answering CLEAN is only evidence if it is capable of
 * answering DIRTY. So dirty and check in ONE process, where the state
 * certainly survives: this MUST report DIRTY. If it ever reports CLEAN,
 * the probe is vacuous and its verdict on a real respawn means nothing.
 *
 * Returns 0 when it correctly detects the dirt (the control passes). */
static int run_control(const char *module, const char *batch)
{
    char *out = NULL; size_t n = 0;
    int rc = fr_udf_call(module, "touch", batch, strlen(batch), &out, &n);
    fr_udf_free(out);
    if (rc != FR_UDF_OK) {
        printf("  control : SETUP FAILED (%s)\n", fr_udf_last_error());
        return 1;
    }
    out = NULL; n = 0;
    rc = fr_udf_call(module, "is_touched", batch, strlen(batch), &out, &n);
    if (rc != FR_UDF_OK) {
        printf("  control : CHECK FAILED (%s)\n", fr_udf_last_error());
        return 1;
    }
    int dirty = (n > 0 && out && out[0] == 'y');
    fr_udf_free(out);
    printf("  control : %s (in-process dirt must be detected)\n",
           dirty ? "DIRTY, as required -- probe is not vacuous"
                 : "CLEAN -- PROBE IS VACUOUS");
    return dirty ? 0 : 1;
}

/* Are the fork hooks LOAD-BEARING, or decoration?
 *
 * Without this, "pre-fork works" is unfalsifiable in the wrong direction:
 * the prototype ran green for a long time with NO hooks at all, purely
 * because nothing was contending for the locks. That is exactly the
 * situation the review amendment is about -- correctness that happens to
 * hold until it does not.
 *
 * So: deliberately violate the choreography (take BeforeFork, fork, and
 * omit AfterFork_Child in the child) and see whether the child breaks.
 * If it breaks, the hooks are doing real work and the correct wiring is
 * load-bearing. If it survives, this mode says so honestly rather than
 * letting us claim the hooks matter on faith.
 *
 * The abort is contained in the child, so the driver still reports. */
static int run_hooks_misuse(const char *module, const char *batch)
{
    if (!fr_udf_fork_hooks_available()) {
        printf("  hooks   : UNAVAILABLE on this CPython build (no HAVE_FORK)\n");
        return 2;
    }
    int fds[2];
    if (pipe(fds) != 0) { perror("pipe"); return 1; }

    if (fr_udf_before_fork() != FR_UDF_OK) {
        fprintf(stderr, "  before_fork failed: %s\n", fr_udf_last_error());
        return 1;
    }
    pid_t p = fork();                 /* deliberately NO hooks at all */
    if (p == 0) {
        close(fds[0]);
        char status = 0;
        char *out = NULL; size_t n = 0;
        int rc = fr_udf_call(module, "up", batch, strlen(batch), &out, &n);
        if (rc != FR_UDF_OK || n == 0) status = 1;
        fr_udf_free(out);
        ssize_t ignored = write(fds[1], &status, 1);
        (void)ignored;
        _exit(0);
    }
    /* Parent: release what BeforeFork took, so this process can exit. */
    fr_udf_after_fork_parent();
    close(fds[1]);
    char status = -1;
    ssize_t got = read(fds[0], &status, 1);
    close(fds[0]);
    int w = 0; waitpid(p, &w, 0);

    int signalled = WIFSIGNALED(w) ? WTERMSIG(w) : 0;
    printf("  hooks   : %s\n",
           (got != 1 || status != 0 || signalled)
             ? "LOAD-BEARING -- an unhooked child breaks, so the "
               "choreography is required, not decorative"
             : "unhooked child SURVIVED -- the hooks may not matter here, "
               "but do not read that as permission to omit them");
    return 0;
}

int main(int argc, char **argv)
{
    /* A write to a dead child's pipe must fail with EPIPE, not kill the
     * parent. Under fault injection a child dies by design. */
    signal(SIGPIPE, SIG_IGN);

    /* A probe that prints the interpreter and exits, so a harness can
     * report the version the DRIVER is linked against rather than the
     * version of whatever Python is running the harness. Those differ
     * whenever the C0.5 matrix is in play. */
    (void)0;
    if (argc > 1 && strcmp(argv[1], "--version-probe") == 0) {
        /* The driver does not include Python.h, so the macros are not
         * available here; the version comes from the interpreter the
         * binary is linked against at run time. */
        /* Deliberately fr_udf_init(), NOT a bare Py_Initialize().
         *
         * A bare Py_Initialize() ignores FR_UDF_HOME -- that variable is
         * consumed by configure() inside fr_udf_init -- so the probe died
         * with "No module named 'encodings'", the harness parsed nothing,
         * and SILENTLY fell back to the host interpreter's version. Every
         * sweep of the 3.10 driver therefore printed "3.14.7" and its
         * numbers were mislabelled, which is the round-7 defect again:
         * the label must describe what was measured.
         *
         * Going through the product's own init also means the probe
         * fails loudly if the helper cannot initialise on this minor,
         * rather than quietly reporting a plausible-looking version. */
        if (fr_udf_init(NULL, 0) != 0) {
            fprintf(stderr, "probe: init failed: %s\n",
                    fr_udf_last_error());
            return 1;
        }
        const char *v = Py_GetVersion();   /* borrowed static string */
        printf("interpreter : %s\n", v ? v : "unknown");
        fr_udf_finalize();
        return 0;
    }

    const char *root  = (argc > 1) ? argv[1] : NULL;
    const char *spec  = (argc > 2) ? argv[2] : "myudf:up";
    int nchildren     = (argc > 3) ? atoi(argv[3]) : 4;
    int iters         = (argc > 4) ? atoi(argv[4]) : 50;
    const char *mode  = (argc > 5) ? argv[5] : NULL;
    /* C0.6 axes, optional and trailing so the original argv shape still
     * works: <root> <spec> <children> <iters> [mode] [parent_mb] [thp] */
    const char *thp_mode = NULL;
    long parent_mb = 0;
    if (argc > 6) parent_mb = atol(argv[6]);
    if (argc > 7) thp_mode = argv[7];
    int respawn_only  = mode && !strcmp(mode, "--respawn");
    int control_only  = mode && !strcmp(mode, "--control");
    int hooks_only    = mode && !strcmp(mode, "--hooks");
    const char *batch = "line000042\n";

    /* Apply the C0.6 axes BEFORE any fork, so the inflated pages are
     * resident and inherited by every child. Applying them after would
     * measure a parent that never had them. */
    if (set_thp(thp_mode) != 0) {
        fprintf(stderr, "cannot set THP state to %s\n", thp_mode);
        return 2;
    }
    if (parent_mb > 0 && inflate_parent_rss(parent_mb) != 0) {
        fprintf(stderr, "cannot inflate parent RSS to %ld MB\n", parent_mb);
        return 2;
    }

    char mbuf[256];
    snprintf(mbuf, sizeof mbuf, "%s", spec);
    char *colon = strrchr(mbuf, ':');
    if (!colon) { fprintf(stderr, "spec must be module:attr\n"); return 2; }
    *colon = '\0';
    const char *module = mbuf, *attr = colon + 1;

    const char *roots[1];
    int nroots = 0;
    if (root) { roots[0] = root; nroots = 1; }

    printf("fr_udf_fork -- pre-fork vs post-fork (C0.4)\n");
    printf("  interpreter : %s\n", fr_udf_version());
    printf("  udf         : %s\n", spec);
    printf("  children    : %d, iters/child: %d, batch: %zu B\n",
           nchildren, iters, strlen(batch));

    int fail_pre = 0, fail_post = 0;

    if (hooks_only) {
        if (fr_udf_init(roots, nroots) != FR_UDF_OK) {
            fprintf(stderr, "init failed: %s\n", fr_udf_last_error());
            return 3;
        }
        fflush(stdout);
        int rc = run_hooks_misuse(module, batch);
        fr_udf_finalize();
        return rc;
    }

    if (control_only || respawn_only) {
        /* Pre-fork, because that is the candidate under test: the
         * interesting case is a respawn onto an INHERITED interpreter. */
        if (fr_udf_init(roots, nroots) != FR_UDF_OK) {
            fprintf(stderr, "respawn: init failed: %s\n", fr_udf_last_error());
            return 3;
        }
        fflush(stdout);
        int rc = control_only
            ? run_control(module, batch)
            : run_respawn(module, "touch", "is_touched", batch);
        fr_udf_finalize();
        return rc;
    }

    /* POST-FORK first, so the shared-interpreter path is not already
     * warm when the pre-fork number is taken. */
    double t_post = run(0, nchildren, iters, module, attr,
                        batch, strlen(batch), roots, nroots, &fail_post);

    double t_pre = 0.0;
    if (fr_udf_init(roots, nroots) != FR_UDF_OK) {
        fprintf(stderr, "pre-fork init failed: %s\n", fr_udf_last_error());
        return 3;
    }
    t_pre = run(1, nchildren, iters, module, attr,
                batch, strlen(batch), roots, nroots, &fail_pre);
    fr_udf_finalize();

    printf("\n  post-fork : %8.4f s  (failures: %d)\n", t_post, fail_post);
    printf("  pre-fork  : %8.4f s  (failures: %d)\n", t_pre,  fail_pre);
    if (t_post > 0)
        printf("  speedup   : %8.2fx\n", t_post / (t_pre > 0 ? t_pre : 1e-9));

    /* C0.6 evidence block: the fleet-memory axis. */
    {
        long rss_cur, rss_peak, pss, uss;
        read_mem_self(&rss_cur, &rss_peak, &pss, &uss);
        printf("\n  --- C0.6 evidence ---\n");
        printf("  parent_rss_target : %ld MB\n", parent_mb);
        printf("  thp               : %s\n", thp_mode ? thp_mode : "inherited");
        printf("  parent_rss_cur_kb : %ld%s\n", rss_cur,
               rss_cur < 0 ? "  (not exposed by this kernel)" : "");
        printf("  parent_rss_peak_kb: %ld\n", rss_peak);
        printf("  parent_pss_kb     : %ld%s\n", pss,
               pss < 0 ? "  (not exposed by this kernel)" : "");
        printf("  parent_uss_kb     : %ld%s\n", uss,
               uss < 0 ? "  (not exposed by this kernel)" : "");
        printf("  children          : %d\n", nchildren);
        if (arm_sampled[0] > 0 || arm_sampled[1] > 0) {
            printf("  --- fleet memory, BOTH arms ---\n");
            printf("  integrity: %d missing ack(s), %d failed release(s), "
                   "%d bad report(s) -- any of these invalidates the "
                   "sample\n", ack_missing, release_failed, report_bad);
            printf("  %-9s %-11s %-11s %-11s %-11s %s\n",
                   "arm", "parent_pss", "child_pss", "parent_rss",
                   "child_rss", "n");
            const char *names[2] = {"post-fork", "pre-fork"};
            for (int a = 0; a < 2; a++) {
                if (arm_sampled[a] <= 0) continue;
                printf("  %-9s %-11ld %-11ld %-11ld %-11ld %d\n",
                       names[a], arm_parent_pss[a], arm_child_pss[a],
                       arm_parent_rss[a], arm_child_rss[a], arm_sampled[a]);
            }
            if (arm_sampled[0] > 0 && arm_sampled[1] > 0) {
                long pss0 = arm_parent_pss[0] + arm_child_pss[0];
                long pss1 = arm_parent_pss[1] + arm_child_pss[1];
                long uss0 = (uss >= 0 ? uss : 0) + arm_child_uss[0];
                long uss1 = (uss >= 0 ? uss : 0) + arm_child_uss[1];
                printf("  fleet PSS (parent+children): post-fork %ld kB, "
                       "pre-fork %ld kB\n", pss0, pss1);
                printf("  fleet USS (parent+children): post-fork %ld kB, "
                       "pre-fork %ld kB\n", uss0, uss1);
                printf("  --> pre-fork uses %+.1f%% PSS vs post-fork\n",
                       pss0 > 0 ? (double)(pss1 - pss0) * 100.0 / pss0
                                : 0.0);
                printf("      RSS for the same runs would read %ld vs %ld kB "
                       "-- a %.1fx over-count, because RSS counts every\n"
                       "      shared page once per process. That gap is "
                       "why the roadmap marked the\n      memory rows [H] "
                       "and deferred them to measurement.\n",
                       arm_child_rss[0] + rss_cur, arm_child_rss[1] + rss_cur,
                       (double)(arm_child_rss[0] + rss_cur) /
                       (arm_child_rss[1] + rss_cur + 1));
            }
        } else {
            printf("  fleet memory      : NOT SAMPLED (no child reported; "
                   "a failed run is not a measurement)\n");
        }
        printf("  ms_per_child_post : %.3f\n",
               nchildren ? 1000.0 * t_post / nchildren : 0.0);
        printf("  ms_per_child_pre  : %.3f\n",
               nchildren ? 1000.0 * t_pre / nchildren : 0.0);
    }

    /* NO VERDICT unless BOTH arms actually ran the UDF.
     *
     * The child check caught a failing BASELINE, which is what it was
     * written for. It did not catch the case where BOTH arms fail, and
     * in that case it still emitted a confident architectural verdict:
     *
     *   $ fr_udf_fork                 # default spec is myudf:up
     *   child 0..3 FAILED (status 3)  # x2
     *   post-fork : 0.0135 s  (failures: 4)
     *   pre-fork  : 0.0014 s  (failures: 4)
     *   VERDICT: pre-fork DOES NOT WORK -- post-fork is the only option.
     *
     * Both arms had failed to import the module, so the 9.76x was two
     * failing runs divided, and the verdict named the wrong winner on
     * no evidence at all. With a real UDF supplied the same binary
     * reports failures: 0 and pre-fork works at ~9x.
     *
     * A harness that prints a number when nothing ran will be believed.
     * So: any failure in EITHER arm suppresses the comparison entirely.
     * This is the same rule tools/bench_splice.py follows -- one failed
     * trial discards the whole configuration. */
    if (fail_pre || fail_post) {
        printf("\n  NO VERDICT: %d of %d children failed "
               "(post-fork %d, pre-fork %d).\n"
               "  A candidate that cannot run the UDF is not a candidate, "
               "and a\n  ratio between two failing runs is not a "
               "measurement. Check that the module is importable from "
               "root.\n  argv: <root> <module:attr> <children> <iters>\n",
               fail_pre + fail_post, 2 * nchildren, fail_post, fail_pre);
        return 1;
    }
    printf("\n  VERDICT: pre-fork works and is %.2fx %s\n",
           t_post / (t_pre > 0 ? t_pre : 1e-9),
           (t_pre < t_post) ? "faster" : "SLOWER (check for noise)");
    return 0;
}
