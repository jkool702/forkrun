#ifdef HAVE_CONFIG_H
# include <config.h>
#endif

#define _GNU_SOURCE  // for splice

// Bash internal headers
#include "command.h"
#include "builtins.h"
#include "shell.h"
#include "common.h"
#include "xmalloc.h"
#include "variables.h"
#include "bashgetopt.h"

// Standard headers
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/eventfd.h>
#include <stdint.h>
#include <sys/time.h>
#include <sys/resource.h>
#include <dirent.h>
#include <ctype.h>
#include <sys/sendfile.h>

// Helper for builtins
extern char **make_builtin_argv();

/* -------------------------------------------------- */
/* lseek builtin                                     */
/* -------------------------------------------------- */
static int lseek_main(int argc, char **argv);
int lseek_builtin(WORD_LIST *list);

static char *lseek_doc[] = {
    "",
    "--------------------------------------------------------------",
    "USAGE:    lseek <FD> <OFFSET> [<SEEK_TYPE>] [<VAR>]",
    "",
    "Move the file descriptor <FD> by <OFFSET> bytes.",
    "",
    "By default, <OFFSET> is relative to <FD>'s current byte offset:",
    "  positive <OFFSET> advances the <FD>",
    "  negative <OFFSET> rewinds the <FD>",
    "",
    "<SEEK_TYPE> is optional and can take the value of:",
    "     'SEEK_SET'   'SEEK_CUR'    'SEEK_END'",
    "  If omitted or empty (''), SEEK_CUR is used by default.",
    "",
    "<VAR> is optional. If present, the new byte offset of",
    "  file descriptor <FD> will be saved in variable <VAR>",
    "  If omitted, the new byte offset will be printed to stdout",
    "  If empty (''), quiet mode is enabled and the new byte offset",
    "    is not printed (requires SEEK_TYPE to be also given)",
    "",
    "NOTE: to use 'SEEK_SET' or 'SEEK_CUR' or 'SEEK_END' as <VAR>,",
    "  <SEEK_TYPE> *must* explicitly be passed on the lseek cmdline",
    "--------------------------------------------------------------",
    "",
    NULL
};

struct builtin lseek_struct = {
    "lseek",
    lseek_builtin,
    BUILTIN_ENABLED,
    lseek_doc,
    "lseek <FD> <OFFSET> [<SEEK_TYPE>] [<VAR>]",
    0
};

static int lseek_main(int argc, char **argv) {
    if (argc < 3 || argc > 5) {
        builtin_error("lseek: incorrect number of arguments");
        return EXECUTION_FAILURE;
    }
    int fd = atoi(argv[1]);
    if (fd < 0) {
        builtin_error("lseek: invalid file descriptor '%s'", argv[1]);
        return EXECUTION_FAILURE;
    }
    errno = 0;
    off_t offset = atoll(argv[2]);
    if (errno == ERANGE) {
        builtin_error("lseek: offset out of range '%s'", argv[2]);
        return EXECUTION_FAILURE;
    }
    int whence = SEEK_CUR;
    int quiet = 0;
    char *varname = NULL;
    if (argc > 3) {
        if (strcmp(argv[3], "SEEK_SET") == 0) whence = SEEK_SET;
        else if (strcmp(argv[3], "SEEK_END") == 0) whence = SEEK_END;
        else if (strcmp(argv[3], "SEEK_CUR") != 0 && argv[3][0] != '\0') {
            if (argc == 4) varname = argv[3];
            else {
                builtin_error("lseek: invalid SEEK_TYPE '%s'", argv[3]);
                return EXECUTION_FAILURE;
            }
        }
        if (argc == 5) {
            if (argv[4][0] == '\0') quiet = 1;
            else varname = argv[4];
        }
    }
    off_t new_offset = lseek(fd, offset, whence);
    if (new_offset == (off_t)-1) {
        builtin_error("lseek: %s", strerror(errno));
        return EXECUTION_FAILURE;
    }
    if (varname) {
        char offset_str[32];
        snprintf(offset_str, sizeof(offset_str), "%lld", (long long)new_offset);
        bind_variable(varname, offset_str, 0);
    } else if (!quiet) {
        printf("%lld\n", (long long)new_offset);
    }
    return EXECUTION_SUCCESS;
}

int lseek_builtin(WORD_LIST *list) {
    int argc; char **argv = make_builtin_argv(list, &argc);
    int ret = lseek_main(argc, argv);
    xfree(argv);
    return ret;
}

/* -------------------------------------------------- */
/* evfd_* builtins                                   */
/* -------------------------------------------------- */
static int evfd = -1;

// evfd_init
int evfd_init_builtin(WORD_LIST *list) {
    if (evfd >= 0) close(evfd);
    evfd = eventfd(0, EFD_CLOEXEC);
    if (evfd < 0) {
        builtin_error("evfd_init: %s", strerror(errno));
        return EXECUTION_FAILURE;
    }
    char buf[32]; snprintf(buf, sizeof(buf), "%d", evfd);
    assign("EVFD_FD", buf, KNOWN_ASSIGNMENT);
    return EXECUTION_SUCCESS;
}
struct builtin evfd_init_struct = {"evfd_init", evfd_init_builtin, BUILTIN_ENABLED, NULL, "evfd_init", 0};

// evfd_wait
int evfd_wait_builtin(WORD_LIST *list) {
    int argc; char **argv = make_builtin_argv(list, &argc);
    int read_fd = -1, sig_fd = -1, status_fd = -1;
    if (argc == 1) {
        if (evfd < 0) { builtin_error("evfd_wait: not initialized"); xfree(argv); return EXECUTION_FAILURE; }
        sig_fd = evfd;
    } else if (argc == 2) {
        read_fd = atoi(argv[1]); sig_fd = evfd;
    } else if (argc >= 3) {
        read_fd = atoi(argv[1]);
        sig_fd = (argv[2][0] == '\0' ? evfd : atoi(argv[2]));
        if (argc == 4) status_fd = atoi(argv[3]);
    } else {
        builtin_usage(); xfree(argv); return EXECUTION_FAILURE;
    }
    if (read_fd >= 0) {
        off_t pos = lseek(read_fd, 0, SEEK_CUR);
        struct stat st;
        if (pos >= 0 && fstat(read_fd, &st) == 0 && st.st_size > pos) {
            if (status_fd >= 0) dprintf(status_fd, "0\n");
            xfree(argv);
            return EXECUTION_SUCCESS;
        }
    }
    uint64_t cnt;
    if (read(sig_fd, &cnt, sizeof(cnt)) != sizeof(cnt)) {
        builtin_error("evfd_wait: %s", strerror(errno));
        xfree(argv);
        return EXECUTION_FAILURE;
    }
    if (status_fd >= 0) dprintf(status_fd, "1\n");
    xfree(argv);
    return EXECUTION_SUCCESS;
}
struct builtin evfd_wait_struct = {"evfd_wait", evfd_wait_builtin, BUILTIN_ENABLED, NULL, "evfd_wait", 0};

// evfd_signal
int evfd_signal_builtin(WORD_LIST *list) {
    int argc; char **argv = make_builtin_argv(list, &argc);
    int fd = (argc > 1 ? atoi(argv[1]) : evfd);
    uint64_t one = 1;
    int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    if (write(fd, &one, sizeof(one)) != sizeof(one) && errno != EAGAIN) {
        builtin_error("evfd_signal: %s", strerror(errno));
    }
    fcntl(fd, F_SETFL, flags);
    xfree(argv);
    return EXECUTION_SUCCESS;
}
struct builtin evfd_signal_struct = {"evfd_signal", evfd_signal_builtin, BUILTIN_ENABLED, NULL, "evfd_signal", 0};

// evfd_splice
int evfd_splice_builtin(WORD_LIST *list) {
    int argc; char **argv = make_builtin_argv(list, &argc);
    if (argc != 2) { builtin_usage(); xfree(argv); return EXECUTION_FAILURE; }
    int outfd = atoi(argv[1]);
    const size_t CHUNK = 64 * 1024;
    uint64_t one = 1;
    while (1) {
        ssize_t n = splice(STDIN_FILENO, NULL, outfd, NULL, CHUNK, SPLICE_F_MOVE | SPLICE_F_MORE);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        int flags = fcntl(evfd, F_GETFL, 0);
        fcntl(evfd, F_SETFL, flags | O_NONBLOCK);
        write(evfd, &one, sizeof(one));
        fcntl(evfd, F_SETFL, flags);
    }
    xfree(argv);
    return EXECUTION_SUCCESS;
}
struct builtin evfd_splice_struct = {"evfd_splice", evfd_splice_builtin, BUILTIN_ENABLED, NULL, "evfd_splice", 0};

// evfd_close
int evfd_close_builtin(WORD_LIST *list) {
    if (evfd >= 0) close(evfd);
    unset_internal("EVFD_FD", KSH_UNSET);
    return EXECUTION_SUCCESS;
}
struct builtin evfd_close_struct = {"evfd_close", evfd_close_builtin, BUILTIN_ENABLED, NULL, "evfd_close", 0};

/* -------------------------------------------------- */
/* childusage builtin                               */
/* -------------------------------------------------- */
static char *childusage_doc[] = {
    "",
    "USAGE: childusage [ -q | --quiet ]",
    "",
    "Calls getrusage(RUSAGE_CHILDREN) to obtain finished children CPU time and",
    "writes to ${tmpDir}/.cpuusage/cpu.<PID>.",
    NULL 
  };
static char *get_persistent_dir(void) {
    const char *tmp = getenv("tmpDir"); if (!tmp) tmp = "/tmp";
    size_t len = strlen(tmp) + strlen("/.cpuusage") + 1;
    char *p = xmalloc(len);
    snprintf(p, len, "%s/.cpuusage", tmp);
    return p;
}
static int childusage_main(int argc, char **argv) {
    int quiet = 0;
    if (argc == 2 && (!strcmp(argv[1], "-q") || !strcmp(argv[1], "--quiet"))) quiet = 1;
    else if (argc > 2) { builtin_error("Usage: childusage [ -q ]"); return EXECUTION_FAILURE; }
    pid_t pid = getpid(); struct rusage ru;
    if (getrusage(RUSAGE_CHILDREN, &ru) != 0) { builtin_error("getrusage: %s", strerror(errno)); return EXECUTION_FAILURE; }
    long tps = sysconf(_SC_CLK_TCK);
    if (tps <= 0) { builtin_error("sysconf(_SC_CLK_TCK) failed"); return EXECUTION_FAILURE; }
    unsigned long long ticks = (unsigned long long)ru.ru_utime.tv_sec * tps + (ru.ru_utime.tv_usec * tps) / 1000000;
    ticks += (unsigned long long)ru.ru_stime.tv_sec * tps + (ru.ru_stime.tv_usec * tps) / 1000000;
    char *pdir = get_persistent_dir();
    if (mkdir(pdir, 0777) != 0 && errno != EEXIST) { builtin_error("mkdir %s: %s", pdir, strerror(errno)); xfree(pdir); return EXECUTION_FAILURE; }
    char path[PATH_MAX]; snprintf(path, sizeof(path), "%s/cpu.%d", pdir, pid);
    xfree(pdir);
    FILE *f = fopen(path, "w"); if (!f) { builtin_error("fopen %s: %s", path, strerror(errno)); return EXECUTION_FAILURE; }
    fprintf(f, "%llu\n", ticks); fclose(f);
    if (!quiet) printf("%llu\n", ticks);
    return EXECUTION_SUCCESS;
}
int childusage_builtin(WORD_LIST *list) {
    int argc; char **argv = make_builtin_argv(list, &argc);
    int ret = childusage_main(argc, argv);
    xfree(argv);
    return ret;
}
struct builtin childusage_struct = {"childusage", childusage_builtin, BUILTIN_ENABLED, childusage_doc, "childusage [ -q ]", 0};

/* -------------------------------------------------- */
/* cpuusage helpers and builtin                      */
/* -------------------------------------------------- */
typedef struct { pid_t pid, ppid; unsigned long utime, stime, cutime, cstime; } proc_info;
static int is_number(const char *s) { for (; *s; ++s) if (!isdigit((unsigned char)*s)) return 0; return 1; }
static int read_proc_stat(pid_t pid, proc_info *info) {
    char file[64]; snprintf(file, sizeof(file), "/proc/%d/stat", pid);
    FILE *f = fopen(file, "r"); if (!f) return -1;
    char buf[1024]; if (!fgets(buf, sizeof(buf), f)) { fclose(f); return -1; }
    fclose(f);
    char *paren = strrchr(buf, ')'); if (!paren) return -1;
    char *p = paren + 1, *tok; int field=0;
    tok = strtok(p, " "); while (tok && field < 3) { tok = strtok(NULL, " "); field++; }
    if (!tok) return -1; info->ppid = atoi(tok);
    for (int i=0; i<9; ++i) tok = strtok(NULL, " "); if (!tok) return -1;
    info->utime = strtoul(strtok(NULL, " "), NULL, 10);
    info->stime = strtoul(strtok(NULL, " "), NULL, 10);
    info->cutime = strtoul(strtok(NULL, " "), NULL, 10);
    info->cstime = strtoul(strtok(NULL, " "), NULL, 10);
    info->pid = pid;
    return 0;
}
static proc_info *get_all_processes(size_t *num) {
    DIR *d = opendir("/proc"); if (!d) return NULL;
    size_t cap=256, cnt=0; proc_info *arr = xmalloc(cap * sizeof(proc_info));
    struct dirent *e;
    while ((e = readdir(d))) {
        if (!is_number(e->d_name)) continue;
        pid_t pid = atoi(e->d_name); proc_info info;
        if (read_proc_stat(pid, &info)==0) {
            if (cnt==cap) arr = xrealloc(arr, cap*=2 * sizeof(proc_info));
            arr[cnt++] = info;
        }
    }
    closedir(d);
    *num = cnt;
    return arr;
}
static int pid_in_list(pid_t pid, pid_t *list, size_t n) {
    for (size_t i=0;i<n;++i) if (list[i]==pid) return 1;
    return 0;
}
static unsigned long long compute_live_cpu_time(pid_t *workers, size_t nw, proc_info *procs, size_t np) {
    pid_t *group = xmalloc(nw * sizeof(pid_t)); size_t gc=0;
    for (size_t i=0;i<nw;++i) group[gc++] = workers[i];
    int added;
    do {
        added = 0;
        for (size_t i=0;i<np;++i) {
            if (!pid_in_list(procs[i].pid, group, gc) && pid_in_list(procs[i].ppid, group, gc)) {
                group = xrealloc(group, (gc+1) * sizeof(pid_t));
                group[gc++] = procs[i].pid;
                added = 1;
            }
        }
    } while (added);
    unsigned long long total=0;
    for (size_t i=0;i<gc;++i) {
        for (size_t j=0;j<np;++j) {
            if (procs[j].pid==group[i]) {
                if (pid_in_list(procs[j].pid, workers, nw))
                    total += procs[j].utime + procs[j].stime;
                else
                    total += procs[j].utime + procs[j].stime + procs[j].cutime + procs[j].cstime;
                break;
            }
        }
    }
    xfree(group);
    return total;
}
static unsigned long long read_finished_time_for_pid(pid_t pid, const char *pdir) {
    char path[PATH_MAX]; snprintf(path, sizeof(path), "%s/cpu.%d", pdir, pid);
    FILE *f = fopen(path, "r"); if (!f) return 0;
    unsigned long long v=0; fscanf(f, "%llu", &v); fclose(f);
    return v;
}
static unsigned long long read_all_cpu_time(void) {
    FILE *f = fopen("/proc/stat","r"); if (!f) return 0;
    char line[512]; unsigned long long sum=0;
    if (fgets(line, sizeof(line), f) && strncmp(line, "cpu ", 4)==0) {
        char *tok = strtok(line+4, " ");
        while (tok) { sum += strtoull(tok, NULL, 10); tok = strtok(NULL, " "); }
    }
    fclose(f);
    return sum;
}

static char *cpuusage_doc[] = {
    "",
    "USAGE: cpuusage <worker_pid> [worker_pid ...]",
    "",
    "Compute total CPU time for workers and their descendants.",
    "Adds finished CPU time (from .cpuusage files) + live /proc times.",
    "Outputs: <TOTAL_CPU_TIME> <SYSTEM_CPU_TIME>",
    NULL
};

int cpuusage_main(int argc, char **argv); 

int cpuusage_builtin(WORD_LIST *list);

struct builtin cpuusage_struct = {"cpuusage", cpuusage_builtin, BUILTIN_ENABLED, cpuusage_doc, "cpuusage <pid>...", 0};

static int cpuusage_main(int argc, char **argv) {
    if (argc < 2) { builtin_error("cpuusage: missing worker PIDs"); return EXECUTION_FAILURE; }
    size_t nw = argc-1;
    pid_t *workers = xmalloc(nw * sizeof(pid_t));
    for (size_t i=0;i<nw;++i) workers[i] = atoi(argv[i+1]);
    size_t np;
    proc_info *procs = get_all_processes(&np);
    if (!procs) { builtin_error("cpuusage: cannot read /proc"); xfree(workers); return EXECUTION_FAILURE; }
    unsigned long long live = compute_live_cpu_time(workers, nw, procs, np);
    xfree(procs);
    char *pdir = get_persistent_dir();
    unsigned long long pers=0;
    for (size_t i=0;i<nw;++i) pers += read_finished_time_for_pid(workers[i], pdir);
    xfree(pdir); xfree(workers);
    unsigned long long total = live + pers;
    unsigned long long all = read_all_cpu_time();
    printf("%llu %llu\n", total, all);
    return EXECUTION_SUCCESS;
}
int cpuusage_builtin(WORD_LIST *list) {
    int argc; char **argv = make_builtin_argv(list, &argc);
    int ret = cpuusage_main(argc, argv);
    xfree(argv);
    return ret;
}

/* -------------------------------------------------- */
/* Register all builtins                              */
/* -------------------------------------------------- */
int setup_builtin_forkrun_loadables(void) {
    add_builtin(&lseek_struct,         1);
    add_builtin(&evfd_init_struct,     1);
    add_builtin(&evfd_wait_struct,     1);
    add_builtin(&evfd_signal_struct,   1);
    add_builtin(&evfd_splice_struct,   1);
    add_builtin(&evfd_close_struct,    1);
    add_builtin(&childusage_struct,    1);
    add_builtin(&cpuusage_struct,      1);
    return 0;
}


/*

static char *evfd_init_doc[] = {
    "",
    "USAGE: evfd_init",
    "",
    "Create a new eventfd, store FD number in $EVFD_FD.",
    "Must be called once before using evfd_wait / evfd_signal.",
    NULL
};

static char *evfd_wait_doc[] = {
    "",
    "USAGE: evfd_wait [<read_fd>] [<signal_fd>] [<notify_fd>]",
    "",
    "Wait until data is available to read or an eventfd is signaled.",
    "",
    "- read_fd: Optional FD to check for unread data.",
    "- signal_fd: Optional eventfd FD (defaults to EVFD_FD).",
    "- notify_fd: Optional FD to write '0' (no wait) or '1' (waited).",
    NULL
};

static char *evfd_signal_doc[] = {
    "",
    "USAGE: evfd_signal [<signal_fd>]",
    "",
    "Signal an eventfd to wake waiters.",
    "Defaults to $EVFD_FD if no FD given.",
    NULL
};

static char *evfd_splice_doc[] = {
    "",
    "USAGE: evfd_splice <output_fd>",
    "",
    "Continuously splice from stdin to output_fd in chunks.",
    "After each chunk, signal eventfd to wake readers.",
    NULL
};

static char *evfd_close_doc[] = {
    "",
    "USAGE: evfd_close",
    "",
    "Close and clean up the eventfd, unset $EVFD_FD.",
    NULL
};
*/
