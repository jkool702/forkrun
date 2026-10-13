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
static void read_mem_self(long *rss_cur_kb, long *rss_peak_kb,
                          long *pss_kb, long *uss_kb)
{
    *rss_cur_kb = *pss_kb = *uss_kb = -1;
    *rss_peak_kb = -1;
    struct rusage ru;
    if (getrusage(RUSAGE_SELF, &ru) == 0) *rss_peak_kb = (long)ru.ru_maxrss;

    FILE *f = fopen("/proc/self/smaps_rollup", "r");
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
        if (sscanf(line, "Rss: %ld kB", &v) == 1) *rss_cur_kb = v;
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
    int *pipes = calloc((size_t)nchildren, sizeof(int));
    if (!pipes) { perror("calloc"); exit(1); }

    double t0 = now_s();
    for (int c = 0; c < nchildren; c++) {
        /* Flush before every fork. A child that calls Py_FinalizeEx()
         * flushes stdio, and it has inherited THIS process's buffer --
         * so without this each child re-prints the header on the way
         * out. Cosmetic, but it makes the output look like the run
         * happened N times. */
        fflush(stdout);
        int fds[2];
        if (pipe(fds) != 0) { perror("pipe"); exit(1); }
        pid_t pid = udf_fork();
        if (pid < 0) { perror("fork"); exit(1); }
        if (pid == 0) {
            /* Child. Report one status byte; never write to stdout, which
             * is the parent's line-buffered table. */
            close(fds[0]);
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
            if (!pre_fork) fr_udf_finalize();
            ssize_t ignored = write(fds[1], &status, 1);
            (void)ignored;
            close(fds[1]);
            _exit(0);
        }
        close(fds[1]);
        pipes[c] = fds[0];
    }

    /* Parent: collect every child's status before finalising, because a
     * pre-fork child is still using the shared interpreter until it
     * exits. */
    for (int c = 0; c < nchildren; c++) {
        char status = -1;
        ssize_t got = read(pipes[c], &status, 1);
        close(pipes[c]);
        int wstatus = 0;
        waitpid(-1, &wstatus, 0);
        if (got != 1 || status != 0) {
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
    double elapsed = now_s() - t0;
    free(pipes);
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
