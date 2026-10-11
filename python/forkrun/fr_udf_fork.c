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
        int fds[2];
        if (pipe(fds) != 0) { perror("pipe"); exit(1); }
        pid_t pid = fork();
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
            fprintf(stderr, "  child %d FAILED (status %d, exit %d)\n",
                    c, (int)status, WIFEXITED(wstatus) ? WEXITSTATUS(wstatus) : -1);
            (*failures)++;
        }
    }
    double elapsed = now_s() - t0;
    free(pipes);
    return elapsed;
}

int main(int argc, char **argv)
{
    const char *root  = (argc > 1) ? argv[1] : NULL;
    const char *spec  = (argc > 2) ? argv[2] : "myudf:up";
    int nchildren     = (argc > 3) ? atoi(argv[3]) : 4;
    int iters         = (argc > 4) ? atoi(argv[4]) : 50;
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
