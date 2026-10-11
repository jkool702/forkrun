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
#include <time.h>
#include <unistd.h>

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
    int respawn_only  = mode && !strcmp(mode, "--respawn");
    int control_only  = mode && !strcmp(mode, "--control");
    int hooks_only    = mode && !strcmp(mode, "--hooks");
    const char *batch = "line000042\n";

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

    /* A pre-fork candidate that cannot actually run the UDF in a child is
     * not a candidate, whatever the timing says. */
    if (fail_pre) {
        printf("\n  VERDICT: pre-fork DOES NOT WORK -- the interpreter does "
               "not survive fork. post-fork is the only option.\n");
        return 1;
    }
    printf("\n  VERDICT: pre-fork works and is %.2fx %s\n",
           t_post / (t_pre > 0 ? t_pre : 1e-9),
           (t_pre < t_post) ? "faster" : "SLOWER (check for noise)");
    return 0;
}
