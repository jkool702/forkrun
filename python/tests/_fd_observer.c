/* _fd_observer.c -- TEST-ONLY. Dump the descriptor set this process was
 * EXEC'd with.
 *
 * WHY THIS EXISTS. The cleanroom launcher's own `--fd-selfcheck` cannot
 * answer the descriptor-equivalence question: it runs in `enter_child()`
 * AFTER exec, and only verifies that descriptors on the launcher's
 * internal keep-list survived the launcher's own `scrub_apply()`. It says
 * nothing about which descriptors the launcher was HANDED at the exec
 * boundary -- which is precisely the set `os.posix_spawn()` would have to
 * reproduce.
 *
 * Modifying the launcher to report its inherited set was rejected: the
 * F6 Stage 2 work order forbids production changes. So this is a
 * standalone observer, compiled at test time, that is launched INSTEAD of
 * the launcher from an isolated replication of run.py's descriptor setup.
 *
 * It deliberately knows nothing about forkrun. It reports what it has:
 *
 *   FD <n> cloexec=<0|1> target=<readlink /proc/self/fd/n>
 *   FD -- end
 *
 * `cloexec` is reported but is expected to be 0 for every inherited
 * descriptor: exec CLEARS FD_CLOEXEC on what it keeps, so a surviving
 * inherited descriptor arriving with cloexec=1 would be impossible. The
 * column exists to make that checkable rather than assumed.
 *
 * Reads only its own state. No environment contents, no paths from the
 * environment, nothing that could carry a secret: the `target` is the
 * kernel's own readlink of the descriptor, and forkrun's job descriptors
 * are memfds/anonymous files whose names are fixed literals in run.py.
 */
#define _GNU_SOURCE
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <unistd.h>

/* Scan limit: a FIXED compile-time ceiling, not an adaptive one.
 *
 * A small ceiling would make a HIGH-DESCRIPTOR test pass VACUOUSLY: a
 * descriptor at, say, fd 1500 would sit outside the scan, so "both arms
 * agree" would be trivially true while neither arm had observed
 * anything. That is why this is 4096 and not 1024.
 *
 * WHAT IT DOES NOT COVER, stated plainly: a descriptor numbered 4096 or
 * above is INVISIBLE to this observer, and a test asserting "the arms
 * agree" would then be vacuous again at that altitude. This observer
 * performs NO runtime check of RLIMIT_NOFILE or `ulimit -n` -- an earlier
 * comment here claimed it did, which was false and would have led a
 * reader to believe the ceiling tracked the host's limit. It does not.
 *
 * A descriptor that high would require the host to have had thousands of
 * descriptors open; for the layout cases under test the ceiling is far
 * above what is reachable, but the limitation is real and a future test
 * that needs to go higher must raise this constant explicitly rather than
 * assume the observer follows the process limit. */
#define FD_SCAN_MAX 4096

int main(void)
{
    char tgt[PATH_MAX + 1];
    char path[64];

    for (int fd = 0; fd < FD_SCAN_MAX; fd++) {
        int fl = fcntl(fd, F_GETFD);
        if (fl == -1)
            continue;                       /* not open */
        snprintf(path, sizeof path, "/proc/self/fd/%d", fd);
        ssize_t m = readlink(path, tgt, sizeof tgt - 1);
        if (m < 0)
            m = 0;
        tgt[m] = '\0';
        printf("FD %d cloexec=%d target=%s\n",
               fd, (fl & FD_CLOEXEC) ? 1 : 0, tgt);
    }
    printf("FD -- end\n");
    fflush(stdout);
    return 0;
}