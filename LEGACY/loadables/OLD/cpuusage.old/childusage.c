/*
 * childusage.c -- a bash loadable builtin that calls getrusage(RUSAGE_CHILDREN)
 * and writes the finished children CPU time to a file.
 *
 * Modifications:
 *   1. Uses the persistent directory specified by the environment variable "tmpDir"
 *      (falling back to /tmp if not set) and its subdirectory ".cpuusage".
 *   2. Requires one argument, a unique identifier (<ID>), to create a file named
 *      "cpu.<ID>" (i.e. ${tmpDir}/.cpuusage/cpu.<ID>), where the finished CPU time
 *      (in clock ticks) will be stored.
 *
 * Compile with:
 *    gcc -Wall -fPIC -c childusage.c -o childusage.o
 *    gcc -shared -o childusage.so childusage.o
 *
 * Load in bash (adjust path as needed):
 *    enable -f /path/to/childusage.so childusage
 */

 #include <stdio.h>
 #include <stdlib.h>
 #include <string.h>
 #include <sys/time.h>
 #include <sys/resource.h>
 #include <unistd.h>
 #include <limits.h>
 #include <sys/stat.h>
 #include <errno.h>
 
 #ifdef BUILDING_FOR_BASH
 #include "builtins.h"
 #include "shell.h"
 #include "bashgetopt.h"
 #else
 /* For standalone testing */
 #define EXECUTION_SUCCESS 0
 #define EXECUTION_FAILURE 1
 
 /* Dummy list type for testing */
 typedef struct {
     int argc;
     char **argv;
 } list;
 int list_length(list *l) { return l->argc; }
 char *list_nth(list *l, int i) { return l->argv[i]; }
 #endif
 
 /* Get persistent directory from environment (same as in cpuusage.c) */
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
 
 /*
  * Builtin: childusage <ID>
  *
  * Calls getrusage(RUSAGE_CHILDREN) and converts the returned ru_utime and ru_stime
  * to clock ticks (using sysconf(_SC_CLK_TCK)). The sum is then written to a file
  * named "${tmpDir}/.cpuusage/cpu.<ID>".
  *
  * Prints the value and returns success.
  */
 int childusage_builtin(list *list) {
     if (list_length(list) < 2) {
         fprintf(stderr, "Usage: childusage <uniqueID>\n");
         return EXECUTION_FAILURE;
     }
     char *uniqueID = list_nth(list, 1);
 
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
 
     /* Get persistent directory and ensure it exists */
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
     snprintf(filepath, sizeof(filepath), "%s/cpu.%s", pdir, uniqueID);
     free(pdir);
 
     FILE *f = fopen(filepath, "w");
     if (!f) {
         perror("fopen");
         return EXECUTION_FAILURE;
     }
     fprintf(f, "%llu\n", child_ticks);
     fclose(f);
 
     /* Optionally, also print the value to stdout */
     printf("%llu\n", child_ticks);
     return EXECUTION_SUCCESS;
 }
 
 #ifdef BUILDING_FOR_BASH
 /* Registration structure for bash loadable builtins */
 struct builtin bash_builtin_struct = {
     .name = "childusage",
     .function = (int (*)(list *)) childusage_builtin,
     .flags = BUILTIN_ENABLED,
     .long_doc =
         "Usage: childusage <uniqueID>\n"
         "Calls getrusage(RUSAGE_CHILDREN) to obtain the finished children CPU time (in clock ticks),\n"
         "and writes this value to ${tmpDir}/.cpuusage/cpu.<uniqueID> (or /tmp/.cpuusage/cpu.<uniqueID> if tmpDir is unset).\n"
         "Prints the value to stdout.",
     .short_doc = "childusage: record finished children CPU time",
     .handle = 0
 };
 #endif
 