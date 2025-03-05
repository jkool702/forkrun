/*
 * cpuusage.c -- a bash loadable builtin that computes the total CPU time
 * for a group of worker coprocesses and their descendants.
 *
 * Modifications:
 *   - Uses the persistent directory from the environment variable "tmpDir"
 *     (falling back to /tmp) and its subdirectory ".cpuusage".
 *   - Instead of reading all files in that directory, only the files
 *     corresponding to the worker PIDs passed in (i.e. cpu.<PID>) are read.
 *
 * The builtin performs these steps:
 *   1. For each worker PID provided as argument, it reads the finished CPU time
 *      from the file "${tmpDir}/.cpuusage/cpu.<PID>" (if present).
 *   2. Scans /proc to build a list of live processes in the group (via recursive PPID matching).
 *      For each worker process, only its self time (utime+stime) is added;
 *      for descendant processes the full value (utime+stime+cutime+cstime) is added.
 *   3. Adds the persistent finished CPU time (for the given worker PIDs) to the live time.
 *   4. Reads system-wide CPU time from /proc/stat (the first "cpu" line).
 *   5. Prints two numbers: CPU_LOAD_TIME and CPU_ALL_TIME.
 *
 * Compile with:
 *    gcc -Wall -fPIC -c cpuusage.c -o cpuusage.o
 *    gcc -shared -o cpuusage.so cpuusage.o
 *
 * Load in bash (adjust path as needed):
 *    enable -f /path/to/cpuusage.so cpuusage
 */

#include "builtins.h"
#include "shell.h"
#include "bashgetopt.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <ctype.h>
#include <errno.h>
#include <sys/types.h>
#include <unistd.h>
#include <limits.h>
#include <sys/stat.h>

/* Helper: Get persistent directory from environment.
 * Returns a newly allocated string containing "${tmpDir}/.cpuusage"
 * (or "/tmp/.cpuusage" if tmpDir is not set). Caller must free.
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

/* Helper: Read persistent finished CPU time for a given worker PID.
 * Looks for a file "${pdir}/cpu.<pid>" and returns its value (in clock ticks)
 * if found, or 0 if the file does not exist or cannot be read.
 */
static unsigned long long read_finished_time_for_pid(pid_t pid, const char *pdir) {
    char filepath[PATH_MAX];
    snprintf(filepath, sizeof(filepath), "%s/cpu.%d", pdir, pid);
    FILE *f = fopen(filepath, "r");
    if (!f)
        return 0;
    unsigned long long val = 0;
    if (fscanf(f, "%llu", &val) != 1)
        val = 0;
    fclose(f);
    return val;
}

/* Minimal structure for process info from /proc/<pid>/stat */
typedef struct {
    pid_t pid;
    pid_t ppid;
    unsigned long utime;
    unsigned long stime;
    unsigned long cutime;
    unsigned long cstime;
} proc_info;

/* Returns nonzero if string s is entirely numeric */
static int is_number(const char *s) {
    while (*s) {
        if (!isdigit((unsigned char)*s))
            return 0;
        s++;
    }
    return 1;
}

/* Read /proc/<pid>/stat and parse required fields:
 * Format (per "man proc"): pid (comm) state ppid ... utime stime cutime cstime ...
 * We locate the closing ')' and then tokenize.
 */
static int read_proc_stat(pid_t pid, proc_info *info) {
    char path[256];
    snprintf(path, sizeof(path), "/proc/%d/stat", pid);
    FILE *f = fopen(path, "r");
    if (!f)
        return -1;
    char buf[1024];
    if (!fgets(buf, sizeof(buf), f)) {
        fclose(f);
        return -1;
    }
    fclose(f);
    char *paren = strrchr(buf, ')');
    if (!paren)
        return -1;
    paren++; /* move past ')' */
    char *saveptr;
    char *token = strtok_r(paren, " ", &saveptr); /* field 3: state (skip) */
    if (!token)
        return -1;
    token = strtok_r(NULL, " ", &saveptr); /* field 4: ppid */
    if (!token)
        return -1;
    info->ppid = (pid_t)atoi(token);
    /* Skip fields 5-13 */
    for (int i = 0; i < 9; i++) {
        token = strtok_r(NULL, " ", &saveptr);
        if (!token)
            return -1;
    }
    token = strtok_r(NULL, " ", &saveptr); /* field 14: utime */
    if (!token)
        return -1;
    info->utime = strtoul(token, NULL, 10);
    token = strtok_r(NULL, " ", &saveptr); /* field 15: stime */
    if (!token)
        return -1;
    info->stime = strtoul(token, NULL, 10);
    token = strtok_r(NULL, " ", &saveptr); /* field 16: cutime */
    if (!token)
        return -1;
    info->cutime = strtoul(token, NULL, 10);
    token = strtok_r(NULL, " ", &saveptr); /* field 17: cstime */
    if (!token)
        return -1;
    info->cstime = strtoul(token, NULL, 10);
    info->pid = pid;
    return 0;
}

/* Scan /proc and build an array of proc_info for all processes.
 * The count is returned in *num_procs.
 */
static proc_info *get_all_processes(size_t *num_procs) {
    DIR *dir = opendir("/proc");
    if (!dir)
        return NULL;
    size_t capacity = 1024;
    proc_info *array = malloc(capacity * sizeof(proc_info));
    if (!array) {
        closedir(dir);
        return NULL;
    }
    size_t count = 0;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (!is_number(entry->d_name))
            continue;
        pid_t pid = (pid_t)atoi(entry->d_name);
        proc_info info;
        if (read_proc_stat(pid, &info) == 0) {
            if (count >= capacity) {
                capacity *= 2;
                proc_info *temp = realloc(array, capacity * sizeof(proc_info));
                if (!temp) {
                    free(array);
                    closedir(dir);
                    return NULL;
                }
                array = temp;
            }
            array[count++] = info;
        }
    }
    closedir(dir);
    *num_procs = count;
    return array;
}

/* Returns nonzero if pid is found in the list (of length n) */
static int pid_in_list(pid_t pid, pid_t *list, size_t n) {
    for (size_t i = 0; i < n; i++) {
        if (list[i] == pid)
            return 1;
    }
    return 0;
}

/* Compute live CPU time for the group.
 * Start with the worker pids (provided as roots) and recursively add any process
 * whose PPID is in the group.
 * For each process:
 *   - If it is a worker, add (utime+stime)
 *   - Otherwise (descendant), add (utime+stime+cutime+cstime)
 */
static unsigned long long compute_live_cpu_time(pid_t *worker_pids, size_t nworkers,
                                                proc_info *proc_array, size_t num_procs) {
    size_t capacity = nworkers;
    pid_t *group = malloc(capacity * sizeof(pid_t));
    if (!group)
        return 0;
    size_t group_count = 0;
    for (size_t i = 0; i < nworkers; i++)
        group[group_count++] = worker_pids[i];
    int added;
    do {
        added = 0;
        for (size_t i = 0; i < num_procs; i++) {
            if (!pid_in_list(proc_array[i].pid, group, group_count) &&
                pid_in_list(proc_array[i].ppid, group, group_count)) {
                if (group_count >= capacity) {
                    capacity = capacity * 2 + 1;
                    pid_t *temp = realloc(group, capacity * sizeof(pid_t));
                    if (!temp) {
                        free(group);
                        return 0;
                    }
                    group = temp;
                }
                group[group_count++] = proc_array[i].pid;
                added = 1;
            }
        }
    } while (added);
    unsigned long long total = 0;
    for (size_t i = 0; i < group_count; i++) {
        for (size_t j = 0; j < num_procs; j++) {
            if (proc_array[j].pid == group[i]) {
                if (pid_in_list(proc_array[j].pid, worker_pids, nworkers))
                    total += proc_array[j].utime + proc_array[j].stime;
                else
                    total += proc_array[j].utime + proc_array[j].stime +
                             proc_array[j].cutime + proc_array[j].cstime;
                break;
            }
        }
    }
    free(group);
    return total;
}

/* Read system-wide CPU time from /proc/stat's first "cpu" line.
 * Returns the sum of all fields (in jiffies).
 */
static unsigned long long read_all_cpu_time(void) {
    unsigned long long cpu_all_time = 0;
    FILE *fstat = fopen("/proc/stat", "r");
    if (fstat) {
        char line[1024];
        if (fgets(line, sizeof(line), fstat)) {
            if (strncmp(line, "cpu ", 4) == 0) {
                char *ptr = line + 4;
                char *token = strtok(ptr, " ");
                while (token) {
                    cpu_all_time += strtoull(token, NULL, 10);
                    token = strtok(NULL, " ");
                }
            }
        }
        fclose(fstat);
    }
    return cpu_all_time;
}

/* Main function for the cpuusage builtin.
 * Expects: cpuusage <worker_pid> [worker_pid ...]
 * Prints: CPU_LOAD_TIME and CPU_ALL_TIME (separated by a space)
 */
static int cpuusage_main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: cpuusage <worker_pid> [worker_pid ...]\n");
        return EXECUTION_FAILURE;
    }
    size_t nworkers = (size_t)(argc - 1);
    pid_t *worker_pids = malloc(nworkers * sizeof(pid_t));
    if (!worker_pids) {
        perror("malloc");
        return EXECUTION_FAILURE;
    }
    for (int i = 1; i < argc; i++) {
        worker_pids[i - 1] = (pid_t)atoi(argv[i]);
    }
    size_t num_procs = 0;
    proc_info *proc_array = get_all_processes(&num_procs);
    if (!proc_array) {
        free(worker_pids);
        fprintf(stderr, "Failed to read /proc\n");
        return EXECUTION_FAILURE;
    }
    unsigned long long live_cpu = compute_live_cpu_time(worker_pids, nworkers, proc_array, num_procs);
    free(proc_array);
    /* Get persistent finished CPU time only for the worker PIDs provided */
    char *pdir = get_persistent_dir();
    if (!pdir) {
        free(worker_pids);
        return EXECUTION_FAILURE;
    }
    unsigned long long persistent_cpu = 0;
    for (size_t i = 0; i < nworkers; i++) {
        persistent_cpu += read_finished_time_for_pid(worker_pids[i], pdir);
    }
    free(pdir);
    free(worker_pids);
    unsigned long long total_cpu_load = live_cpu + persistent_cpu;
    unsigned long long cpu_all_time = read_all_cpu_time();
    printf("%llu %llu\n", total_cpu_load, cpu_all_time);
    return EXECUTION_SUCCESS;
}

/* Wrapper: Convert WORD_LIST to argc/argv, call cpuusage_main, and free argv */
int cpuusage_builtin(WORD_LIST *list) {
    int argc;
    char **argv = make_builtin_argv(list, &argc);
    int ret = cpuusage_main(argc, argv);
    xfree(argv);
    return ret;
}

/* Documentation for the cpuusage builtin */
static char *cpuusage_doc[] = {
    "",
    "USAGE: cpuusage <worker_pid> [worker_pid ...]",
    "",
    "Calculates total CPU load time for the specified worker coprocesses and their descendants.",
    "For each worker PID provided, it reads finished children CPU time from",
    "the file ${tmpDir}/.cpuusage/cpu.<worker_pid> (or /tmp/.cpuusage/cpu.<worker_pid> if tmpDir is unset).",
    "It adds that to the live CPU time (from /proc) and reports that along with the",
    "system-wide CPU time (from /proc/stat).",
    "",
    NULL
};

/* Registration structure for bash builtins */
struct builtin cpuusage_struct = {
    "cpuusage",              /* name */
    cpuusage_builtin,        /* function */
    BUILTIN_ENABLED,         /* flags */
    cpuusage_doc,            /* long doc */
    "cpuusage <worker_pid> [worker_pid ...]", /* usage */
    0
};
