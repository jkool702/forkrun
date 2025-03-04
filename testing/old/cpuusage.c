/*
 * cpuusage.c -- a bash loadable builtin that computes the total CPU time
 * for a group of worker coprocesses and their descendants.
 *
 * Modifications:
 *   1. Uses the persistent directory specified by the environment variable "tmpDir"
 *      (falling back to /tmp if not set) and its subdirectory ".cpuusage".
 *   2. Reads finished children CPU times from multiple files (cpu.<ID>) in that directory.
 *
 * The builtin performs these steps:
 *   a) Reads persistent finished CPU time by scanning ${tmpDir}/.cpuusage/ and summing
 *      all values found in files named "cpu.*".
 *   b) Scans /proc to build a list of live processes in the group (by recursively matching PPIDs).
 *      For each worker process (supplied on the command line), it adds only its self time (utime+stime);
 *      for descendant processes it adds the full CPU time (utime+stime+cutime+cstime).
 *   c) Adds the persistent finished CPU time to the live time.
 *   d) Reads the system-wide CPU time from /proc/stat (first "cpu" line).
 *   e) Prints two numbers: CPU_LOAD_TIME and CPU_ALL_TIME.
 *
 * Compile with:
 *    gcc -Wall -fPIC -c cpuusage.c -o cpuusage.o
 *    gcc -shared -o cpuusage.so cpuusage.o
 *
 * Load in bash (adjust path as needed):
 *    enable -f /path/to/cpuusage.so cpuusage
 */

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
 
 #ifdef BUILDING_FOR_BASH
 #include "builtins.h"
 #include "shell.h"
 #include "bashgetopt.h"
 #else
 /* For standalone testing, define minimal dummy macros and list API */
 #define EXECUTION_SUCCESS 0
 #define EXECUTION_FAILURE 1
 #define builtin_usage() fprintf(stderr, "Usage: cpuusage pid [pid ...]\n")
 #define builtin_error(str) fprintf(stderr, "%s\n", (str))
 
 /* Dummy list type for testing */
 typedef struct {
     int argc;
     char **argv;
 } list;
 int list_length(list *l) { return l->argc; }
 char *list_nth(list *l, int i) { return l->argv[i]; }
 #endif
 
 /* Get persistent directory from environment.
  * Returns a newly allocated string that must be freed.
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
 
 /* Structure to hold minimal /proc/<pid>/stat info */
 typedef struct {
     pid_t pid;
     pid_t ppid;
     unsigned long utime;
     unsigned long stime;
     unsigned long cutime;
     unsigned long cstime;
 } proc_info;
 
 /* Returns nonzero if the string is entirely numeric */
 static int is_number(const char *s) {
     while (*s) {
         if (!isdigit((unsigned char)*s))
             return 0;
         s++;
     }
     return 1;
 }
 
 /* Read /proc/<pid>/stat and parse the required fields.
  * Format (from "man proc"): pid (comm) state ppid ... utime stime cutime cstime ...
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
 
     /* Find the closing parenthesis */
     char *paren = strrchr(buf, ')');
     if (!paren)
         return -1;
     paren++;  /* Move past the ')' */
 
     char *saveptr;
     /* Field 3: state (skip) */
     char *token = strtok_r(paren, " ", &saveptr);
     if (!token)
         return -1;
     /* Field 4: ppid */
     token = strtok_r(NULL, " ", &saveptr);
     if (!token)
         return -1;
     info->ppid = (pid_t)atoi(token);
 
     /* Skip fields 5-13 */
     for (int i = 0; i < 9; i++) {
         token = strtok_r(NULL, " ", &saveptr);
         if (!token)
             return -1;
     }
     /* Field 14: utime */
     token = strtok_r(NULL, " ", &saveptr);
     if (!token)
         return -1;
     info->utime = strtoul(token, NULL, 10);
     /* Field 15: stime */
     token = strtok_r(NULL, " ", &saveptr);
     if (!token)
         return -1;
     info->stime = strtoul(token, NULL, 10);
     /* Field 16: cutime */
     token = strtok_r(NULL, " ", &saveptr);
     if (!token)
         return -1;
     info->cutime = strtoul(token, NULL, 10);
     /* Field 17: cstime */
     token = strtok_r(NULL, " ", &saveptr);
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
 
 /* Returns nonzero if 'pid' is in the list (of length n) */
 static int pid_in_list(pid_t pid, pid_t *list, size_t n) {
     for (size_t i = 0; i < n; i++) {
         if (list[i] == pid)
             return 1;
     }
     return 0;
 }
 
 /* Read persistent finished CPU time by scanning the persistent directory.
  * For each file whose name begins with "cpu.", open it and sum its value (in clock ticks).
  */
 static unsigned long long read_all_finished_time(void) {
     unsigned long long total = 0;
     char *pdir = get_persistent_dir();
     if (!pdir)
         return 0;
     DIR *dir = opendir(pdir);
     if (!dir) {
         free(pdir);
         return 0;
     }
     struct dirent *entry;
     while ((entry = readdir(dir)) != NULL) {
         if (strncmp(entry->d_name, "cpu.", 4) != 0)
             continue;
         char filepath[PATH_MAX];
         snprintf(filepath, sizeof(filepath), "%s/%s", pdir, entry->d_name);
         FILE *f = fopen(filepath, "r");
         if (f) {
             unsigned long long val = 0;
             if (fscanf(f, "%llu", &val) == 1)
                 total += val;
             fclose(f);
         }
     }
     closedir(dir);
     free(pdir);
     return total;
 }
 
 /* Compute total CPU time of live processes in the group.
  * The group is built by starting with the worker PIDs (roots) provided on the command line
  * and then recursively adding any process in proc_array whose ppid is in the group.
  *
  * For each process:
  *   - If it is a worker (its pid is in worker_pids), add (utime+stime)
  *   - Otherwise (descendant), add (utime+stime+cutime+cstime)
  */
 static unsigned long long compute_live_cpu_time(pid_t *worker_pids, size_t nworkers,
                                                 proc_info *proc_array, size_t num_procs)
 {
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
                 pid_in_list(proc_array[i].ppid, group, group_count))
             {
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
                 if (pid_in_list(proc_array[j].pid, worker_pids, nworkers)) {
                     total += proc_array[j].utime + proc_array[j].stime;
                 } else {
                     total += proc_array[j].utime + proc_array[j].stime +
                              proc_array[j].cutime + proc_array[j].cstime;
                 }
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
 
 /*
  * Builtin: cpuusage pid [pid ...]
  *
  * Usage:
  *   cpuusage pid [pid ...]
  *
  * Computes:
  *   live_cpu = (for each worker: utime+stime) +
  *              (for each descendant: utime+stime+cutime+cstime)
  *   persistent_cpu = sum of finished CPU times from persistent files in ${tmpDir}/.cpuusage/
  *   CPU_LOAD_TIME = live_cpu + persistent_cpu
  *   CPU_ALL_TIME  = sum of all fields from the first "cpu" line in /proc/stat
  *
  * Prints: CPU_LOAD_TIME and CPU_ALL_TIME (separated by a space)
  */
 int cpuusage_builtin(list *list) {
     if (list_length(list) < 2) {
         builtin_usage();
         return EXECUTION_FAILURE;
     }
     size_t nworkers = list_length(list) - 1;
     pid_t *worker_pids = malloc(nworkers * sizeof(pid_t));
     if (!worker_pids) {
         perror("malloc");
         return EXECUTION_FAILURE;
     }
     for (size_t i = 0; i < nworkers; i++) {
         char *arg = list_nth(list, i + 1);
         worker_pids[i] = (pid_t)atoi(arg);
     }
 
     size_t num_procs = 0;
     proc_info *proc_array = get_all_processes(&num_procs);
     if (!proc_array) {
         free(worker_pids);
         builtin_error("Failed to read /proc");
         return EXECUTION_FAILURE;
     }
 
     unsigned long long live_cpu = compute_live_cpu_time(worker_pids, nworkers, proc_array, num_procs);
     free(worker_pids);
     free(proc_array);
 
     unsigned long long persistent_cpu = read_all_finished_time();
     unsigned long long total_cpu_load = live_cpu + persistent_cpu;
     unsigned long long cpu_all_time = read_all_cpu_time();
 
     printf("%llu %llu\n", total_cpu_load, cpu_all_time);
     return EXECUTION_SUCCESS;
 }
 
 #ifdef BUILDING_FOR_BASH
 /* Registration structure for bash loadable builtins */
 struct builtin bash_builtin_struct = {
     .name = "cpuusage",
     .function = cpuusage_builtin,
     .flags = BUILTIN_ENABLED,
     .long_doc =
         "Usage: cpuusage pid [pid ...]\n"
         "Calculates total CPU load time for the given worker coprocesses and their descendants.\n"
         "The load is computed as live CPU time (from /proc) plus persistent finished children CPU time,\n"
         "which is read from files in ${tmpDir}/.cpuusage (or /tmp/.cpuusage if tmpDir is unset).\n"
         "Also outputs total system CPU time from /proc/stat.",
     .short_doc = "cpuusage: compute CPU times for process groups",
     .handle = 0
 };
 #endif
 