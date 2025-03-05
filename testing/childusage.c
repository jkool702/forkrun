/*
 * childusage.c -- a bash loadable builtin that calls getrusage(RUSAGE_CHILDREN)
 * and writes the finished children CPU time (in clock ticks) to a file.
 *
 * Modifications:
 *   - Uses the process's own PID (via getpid()) as the identifier.
 *     The CPU time is saved in "${tmpDir}/.cpuusage/cpu.<PID>" (or /tmp/.cpuusage/cpu.<PID> if tmpDir is unset).
 *   - If the optional argument "-q" or "--quiet" is passed as the only argument,
 *     nothing is printed to stdout.
 *
 * Compile with:
 *    gcc -Wall -fPIC -c childusage.c -o childusage.o
 *    gcc -shared -o childusage.so childusage.o
 *
 * Load in bash (adjust path as needed):
 *    enable -f /path/to/childusage.so childusage
 */

#include "builtins.h"
#include "shell.h"
#include "bashgetopt.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <sys/resource.h>
#include <unistd.h>
#include <limits.h>
#include <sys/stat.h>
#include <errno.h>

/* Helper: Get persistent directory from environment.
 * Returns a newly allocated string containing "${tmpDir}/.cpuusage"
 * (or "/tmp/.cpuusage" if tmpDir is not set).
 */
static char *get_persistent_dir(void) {
    const char *tmpDir = getenv("tmpDir");
    if (!tmpDir)
        tmpDir = "/tmp";
    size_t len = strlen(tmpDir) + strlen("/.cpuusage") + 1;
    char *pdir = malloc(len);
    if (!pdir)
        return NULL;
    snprintf(pdir, len, "%s/.cpuusage", tmpDir);
    return pdir;
}

/* Main function for the childusage builtin.
 * Behavior:
 *   - Uses getpid() as the unique identifier.
 *   - If the only argument is "-q" or "--quiet", operates in quiet mode (no stdout).
 *   - Otherwise, prints the finished CPU time.
 */
static int childusage_main(int argc, char **argv) {
    int quiet = 0;
    if (argc == 2) {
        if (strcmp(argv[1], "-q") == 0 || strcmp(argv[1], "--quiet") == 0)
            quiet = 1;
        else {
            fprintf(stderr, "Usage: childusage [ -q | --quiet ]\n");
            return EXECUTION_FAILURE;
        }
    } else if (argc > 2) {
        fprintf(stderr, "Usage: childusage [ -q | --quiet ]\n");
        return EXECUTION_FAILURE;
    }
    pid_t pid = getpid();
    struct rusage ru;
    if (getrusage(RUSAGE_CHILDREN, &ru) != 0) {
        perror("getrusage");
        return EXECUTION_FAILURE;
    }
    long ticks_per_sec = sysconf(_SC_CLK_TCK);
    if (ticks_per_sec <= 0) {
        fprintf(stderr, "Invalid _SC_CLK_TCK value\n");
        return EXECUTION_FAILURE;
    }
    unsigned long long child_ticks = 0;
    child_ticks += ru.ru_utime.tv_sec * ticks_per_sec +
                   (ru.ru_utime.tv_usec * ticks_per_sec) / 1000000;
    child_ticks += ru.ru_stime.tv_sec * ticks_per_sec +
                   (ru.ru_stime.tv_usec * ticks_per_sec) / 1000000;
    /* Ensure persistent directory exists */
    char *pdir = get_persistent_dir();
    if (!pdir) {
        perror("malloc");
        return EXECUTION_FAILURE;
    }
    if (mkdir(pdir, 0777) != 0 && errno != EEXIST) {
        perror("mkdir");
        free(pdir);
        return EXECUTION_FAILURE;
    }
    char filepath[PATH_MAX];
    snprintf(filepath, sizeof(filepath), "%s/cpu.%d", pdir, pid);
    free(pdir);
    FILE *f = fopen(filepath, "w");
    if (!f) {
        perror("fopen");
        return EXECUTION_FAILURE;
    }
    fprintf(f, "%llu\n", child_ticks);
    fclose(f);
    if (!quiet)
        printf("%llu\n", child_ticks);
    return EXECUTION_SUCCESS;
}

/* Wrapper: Convert WORD_LIST to argc/argv, call childusage_main, free argv */
int childusage_builtin(WORD_LIST *list) {
    int argc;
    char **argv = make_builtin_argv(list, &argc);
    int ret = childusage_main(argc, argv);
    xfree(argv);
    return ret;
}

/* Documentation for childusage builtin */
static char *childusage_doc[] = {
    "",
    "USAGE: childusage [ -q | --quiet ]",
    "",
    "Calls getrusage(RUSAGE_CHILDREN) to obtain finished children CPU time (in clock ticks)",
    "and writes this value to ${tmpDir}/.cpuusage/cpu.<PID> (or /tmp/.cpuusage/cpu.<PID> if tmpDir is unset),",
    "using the process's own PID as the identifier.",
    "If the optional argument -q or --quiet is given, no output is printed.",
    "",
    NULL
};

/* Registration structure for bash builtins */
struct builtin childusage_struct = {
    "childusage",              /* name */
    childusage_builtin,        /* function */
    BUILTIN_ENABLED,           /* flags */
    childusage_doc,            /* long doc */
    "childusage [ -q | --quiet ]", /* usage */
    0
};
