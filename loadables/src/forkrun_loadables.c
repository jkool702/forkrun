// forkrun_loadables.c

// Enable GNU extensions for splice
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

// System headers\
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdint.h>
#include <sys/eventfd.h>
#include <sys/time.h>
#include <sys/resource.h>
#include <dirent.h>
#include <ctype.h>
#include <sys/sendfile.h>
#include <poll.h>
#include <limits.h>

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

// Bash internal headers
#include "command.h"
#include "builtins.h"
#include "shell.h"
#include "common.h"
#include "xmalloc.h"
#include "variables.h"

// Helpers for builtins
extern int add_builtin(struct builtin * bp, int keep);
extern char ** make_builtin_argv();

// define function prototypes
static int fr_builtin(WORD_LIST * list);
static int lseek_main(int argc, char ** argv);
static int evfd_init_main(int argc, char ** argv);
static int evfd_wait_main(int argc, char ** argv);
static int evfd_signal_main(int argc, char ** argv);
static int evfd_copy_main(int argc, char ** argv);
static int evfd_close_main(int argc, char ** argv);
static int childusage_main(int argc, char ** argv);
static int cpuusage_main(int argc, char ** argv);
static char * get_persistent_dir(void);

/* -------------------------------------------------- */
/* lseek builtin                                     */
/* -------------------------------------------------- */

static char * lseek_doc[] = {
    "",
    "USAGE: lseek <FD> <OFFSET> [<SEEK_TYPE>] [<VAR>]",
    "",
    "Move the given file descriptor <FD> by <OFFSET> bytes.",
    "",
    "- SEEK_TYPE (optional): SEEK_SET, SEEK_CUR (default), SEEK_END",
    "- VAR (optional): If given, store new file offset in variable VAR.",
    "- If VAR is empty (''), enable quiet mode (no output).",
    "",
    "Returns new offset or stores it.",
    NULL
};

static int lseek_main(int argc, char ** argv) {
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
    char * varname = NULL;
    if (argc > 3) {
        if (strcmp(argv[3], "SEEK_SET") == 0) whence = SEEK_SET;
        else if (strcmp(argv[3], "SEEK_END") == 0) whence = SEEK_END;
        else if (argv[3][0] != '\0') {
            varname = argv[3];
        }
        if (argc == 5) {
            if (argv[4][0] == '\0') quiet = 1;
            else varname = argv[4];
        }
    }
    off_t new_offset = lseek(fd, offset, whence);
    if (new_offset == (off_t) - 1) {
        builtin_error("lseek: %s", strerror(errno));
        return EXECUTION_FAILURE;
    }
    if (varname) {
        char buf_off[32];
        snprintf(buf_off, sizeof(buf_off), "%lld", (long long) new_offset);
        bind_variable(varname, buf_off, 0);
    } else if (!quiet) {
        printf("%lld\n", (long long) new_offset);
    }
    return EXECUTION_SUCCESS;
}

struct builtin lseek_struct = {
    "lseek",
    fr_builtin,
    BUILTIN_ENABLED,
    lseek_doc,
    "lseek <FD> <OFFSET> [<SEEK_TYPE>] [<VAR>]",
    0
};

/* -------------------------------------------------- */
/* evfd_* builtins                                   */
/* -------------------------------------------------- */
static int evfd = -1;

// evfd_init

static char * evfd_init_doc[] = {
    "",
    "USAGE: evfd_init",
    "",
    "Create a new eventfd, store FD number in $EVFD_FD.",
    "Must be called once before using evfd_wait / evfd_signal.",
    NULL
};

static int evfd_init_main(int argc, char ** argv) {
    if (evfd >= 0) close(evfd);
    evfd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    if (evfd < 0) {
        builtin_error("evfd_init: %s", strerror(errno));
        return EXECUTION_FAILURE;
    }
    char buf[16];
    snprintf(buf, sizeof(buf), "%d", evfd);
    bind_variable("EVFD_FD", buf, 0);
    return EXECUTION_SUCCESS;
}

struct builtin evfd_init_struct = {
    "evfd_init",
    fr_builtin,
    BUILTIN_ENABLED,
    evfd_init_doc,
    "evfd_init",
    0
};

// evfd_wait
static char * evfd_wait_doc[] = {
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

static int evfd_wait_main(int argc, char ** argv) {

    int read_fd = -1, sig_fd = evfd, status_fd = -1;
    if (argc == 2) {
        read_fd = atoi(argv[1]);
    } else if (argc >= 3) {
        read_fd = atoi(argv[1]);
        if (argv[2][0] != '\0') sig_fd = atoi(argv[2]);
        if (argc == 4) status_fd = atoi(argv[3]);
    }

    // 1) Check for unread data
    off_t cur = lseek(read_fd, 0, SEEK_CUR);
    off_t end = lseek(read_fd, 0, SEEK_END);
    if (cur < end) {
        lseek(read_fd, cur, SEEK_SET);
        if (status_fd >= 0) dprintf(status_fd, "0\n");
        return EXECUTION_SUCCESS;
    }

    // Determine tmpdir for .done/.quit
    const char * tmpdir = getenv("FORKRUN_TMPDIR");
    if (!tmpdir) tmpdir = "/tmp";
    char donepath[PATH_MAX], quitpath[PATH_MAX];
    snprintf(donepath, sizeof(donepath), "%s/.done", tmpdir);
    snprintf(quitpath, sizeof(quitpath), "%s/.quit", tmpdir);

    // 2) Check for final-batch marker
    if (access(donepath, F_OK) == 0 || access(quitpath, F_OK) == 0) {
        bind_variable("doneIndicatorFlag", "true", 0);
        if (status_fd >= 0) dprintf(status_fd, "0\n");
        return EXECUTION_SUCCESS;
    }

    // 3) Block on eventfd alone
    struct pollfd pfd = {
        .fd = sig_fd,
        .events = POLLIN
    };
    int ret = poll( & pfd, 1, -1);
    if (ret < 0) {
        builtin_error("evfd_wait: poll failed: %s", strerror(errno));
        return EXECUTION_FAILURE;
    }
    if (pfd.revents & POLLIN) {
        uint64_t cnt;
        if (read(sig_fd, & cnt, sizeof(cnt)) != sizeof(cnt)) {
            builtin_error("evfd_wait: read eventfd: %s", strerror(errno));
            return EXECUTION_FAILURE;
        }
        if (status_fd >= 0) dprintf(status_fd, "1\n");
    }
    return EXECUTION_SUCCESS;
}

struct builtin evfd_wait_struct = {
    "evfd_wait",
    fr_builtin,
    BUILTIN_ENABLED,
    evfd_wait_doc,
    "evfd_wait [<read_fd>] [<signal_fd>] [<notify_fd>]",
    0
};

// evfd_signal
static char * evfd_signal_doc[] = {
    "",
    "USAGE: evfd_signal [<signal_fd>]",
    "",
    "Signal an eventfd to wake waiters.",
    "Defaults to $EVFD_FD if no FD given.",
    NULL
};

static int evfd_signal_main(int argc, char ** argv) {
    int fd = (argc > 1 ? atoi(argv[1]) : evfd);
    uint64_t one = 1;

    if (write(fd, &one, sizeof(one)) != sizeof(one) && errno != EAGAIN) {
        builtin_error("evfd_signal: %s", strerror(errno));
    }

    return EXECUTION_SUCCESS;
}

struct builtin evfd_signal_struct = {
    "evfd_signal",
    fr_builtin,
    BUILTIN_ENABLED,
    evfd_signal_doc,
    "evfd_signal [<signal_fd>]",
    0
};

// evfd_copy
static char * evfd_copy_doc[] = {
    "",
    "USAGE: evfd_copy <output_fd>",
    "",
    "Continuously splice from stdin to output_fd in chunks.",
    "After each chunk, signal eventfd to wake readers.",
    NULL
};

static size_t pick_chunk_size(int fd)
{
    size_t chunk;
    struct stat st;

    // 1) Try filesystem-preferred block size
    if (fstat(fd, &st) == 0 && st.st_blksize > 0) {
        chunk = st.st_blksize;
    } else {
        chunk = 128 * 1024;          // fallback to 128 KiB
    }

    // 2) Clamp into the 128 KiB–256 KiB range
    if (chunk < 128 * 1024)  chunk = 128 * 1024;
    if (chunk > 256 * 1024)  chunk = 256 * 1024;

    // 3) Optional override via env var FORKRUN_CHUNK
    if (const char *e = getenv("FORKRUN_CHUNK")) {
        long val = strtol(e, NULL, 10);
        if (val > 0 && val <= INT_MAX) {
            chunk = (size_t)val;
        }
    }

    return chunk;
}

static int evfd_copy_main(int argc, char **argv)
{
    if (argc != 3) {
        builtin_error("evfd_copy: wrong args");
        return EXECUTION_FAILURE;
    }
    int outfd = atoi(argv[1]);
    int infd  = atoi(argv[2]);
    const size_t CHUNK = 128 * 1024;
    uint64_t one = 1;

    // 1) Try in-kernel file→file
    while (1) {
        ssize_t n = copy_file_range(infd, NULL, outfd, NULL, CHUNK, 0);
        if (n > 0) {
            write(evfd, &one, sizeof(one));  // ignore EAGAIN
            continue;
        }
        if (n == 0)  // EOF
            return EXECUTION_SUCCESS;
        if (errno == EINTR)
            continue;
        // On EINVAL/ENOSYS, kernel/FS doesn’t support it → break to splice
        if (errno == EINVAL || errno == ENOSYS)
            break;
        builtin_error("evfd_copy: copy_file_range: %s", strerror(errno));
        return EXECUTION_FAILURE;
    }

    // 2) Fallback: splice (requires a pipe on infd)
    while (1) {
        ssize_t n = splice(infd, NULL, outfd, NULL,
                           CHUNK, SPLICE_F_MOVE | SPLICE_F_MORE);
        if (n < 0) {
            if (errno == EINTR) continue;
            builtin_error("evfd_copy: splice failed: %s", strerror(errno));
            return EXECUTION_FAILURE;
        }
        if (n == 0)  // EOF
            return EXECUTION_SUCCESS;
        write(evfd, &one, sizeof(one));  // ignore EAGAIN
    }
}

struct builtin evfd_copy_struct = {
    "evfd_copy",
    fr_builtin,
    BUILTIN_ENABLED,
    evfd_copy_doc,
    "evfd_copy <output_fd>",
    0
};

// evfd_close
static char * evfd_close_doc[] = {
    "",
    "USAGE: evfd_close",
    "",
    "Close and clean up the eventfd, unset $EVFD_FD.",
    NULL
};

static int evfd_close_main(int argc, char ** argv) {
    if (evfd >= 0) close(evfd);
    return EXECUTION_SUCCESS;
}

struct builtin evfd_close_struct = {
    "evfd_close",
    fr_builtin,
    BUILTIN_ENABLED,
    evfd_close_doc,
    "evfd_close",
    0
};

/* -------------------------------------------------- */
/* childusage builtin                                */
/* -------------------------------------------------- */
static char * childusage_doc[] = {
    "",
    "USAGE: childusage [ -q | --quiet ]",
    "",
    "Record finished children's CPU time to ${tmpDir}/.cpuusage/cpu.<PID>.",
    "If '-q' or '--quiet' is given, suppress output.",
    NULL
};

static char * get_persistent_dir(void) {
    const char * tmp = getenv("tmpDir");
    if (!tmp) tmp = "/tmp";
    size_t len = strlen(tmp) + strlen("/.cpuusage") + 1;
    char * p = xmalloc(len);
    snprintf(p, len, "%s/.cpuusage", tmp);
    return p;
}

static int childusage_main(int argc, char ** argv) {
    int quiet = 0;
    if (argc == 2 && (strcmp(argv[1], "-q") == 0 || strcmp(argv[1], "--quiet") == 0)) quiet = 1;
    else if (argc > 2) {
        builtin_error("Usage: childusage [ -q ]");
        return EXECUTION_FAILURE;
    }
    pid_t pid = getpid();
    struct rusage ru;
    if (getrusage(RUSAGE_CHILDREN, & ru) != 0) {
        builtin_error("getrusage: %s", strerror(errno));
        return EXECUTION_FAILURE;
    }
    long tps = sysconf(_SC_CLK_TCK);
    if (tps <= 0) {
        builtin_error("sysconf(_SC_CLK_TCK) failed");
        return EXECUTION_FAILURE;
    }
    unsigned long long ticks = (unsigned long long) ru.ru_utime.tv_sec * tps + ru.ru_utime.tv_usec * tps / 1000000;
    ticks += (unsigned long long) ru.ru_stime.tv_sec * tps + ru.ru_stime.tv_usec * tps / 1000000;
    char * pdir = get_persistent_dir();
    if (mkdir(pdir, 0777) != 0 && errno != EEXIST) {
        builtin_error("mkdir %s: %s", pdir, strerror(errno));
        xfree(pdir);
        return EXECUTION_FAILURE;
    }
    char path[PATH_MAX];
    snprintf(path, sizeof(path), "%s/cpu.%d", pdir, pid);
    xfree(pdir);
    FILE * f = fopen(path, "w");
    if (!f) {
        builtin_error("fopen %s: %s", path, strerror(errno));
        return EXECUTION_FAILURE;
    }
    fprintf(f, "%llu\n", ticks);
    fclose(f);
    if (!quiet) printf("%llu\n", ticks);
    return EXECUTION_SUCCESS;
}

struct builtin childusage_struct = {
    "childusage",
    fr_builtin,
    BUILTIN_ENABLED,
    childusage_doc,
    "childusage [ -q | --quiet ]",
    0
};

/* -------------------------------------------------- */
/* cpuusage helpers and builtin                      */
/* -------------------------------------------------- */
static char * cpuusage_doc[] = {
    "",
    "USAGE: cpuusage <worker_pid> [worker_pid ...]",
    "",
    "Compute total CPU time for workers and their descendants.",
    "Adds finished CPU time (from .cpuusage files) + live /proc times.",
    "Outputs: <TOTAL_CPU_TIME> <SYSTEM_CPU_TIME>",
    NULL
};

typedef struct {
    pid_t pid, ppid;
    unsigned long utime, stime, cutime, cstime;
}
proc_info;

static int is_number(const char * s) {
    for (;* s; ++s)
        if (!isdigit((unsigned char) * s)) return 0;
    return 1;
}

static int read_proc_stat(pid_t pid, proc_info * info) {
    char file[64];
    snprintf(file, sizeof(file), "/proc/%d/stat", pid);
    FILE * f = fopen(file, "r");
    if (!f) return -1;
    char buf[1024];
    if (!fgets(buf, sizeof(buf), f)) {
        fclose(f);
        return -1;
    }
    fclose(f);
    char * paren = strrchr(buf, ')');
    if (!paren) return -1;
    char * p = paren + 1, * tok;
    int fld = 0;
    tok = strtok(p, " ");
    while (tok && fld < 2) {
        tok = strtok(NULL, " ");
        fld++;
    }
    if (!tok) return -1;
    info -> ppid = atoi(tok);
    for (int i = 0; i < 9; ++i) tok = strtok(NULL, " ");
    if (!tok) return -1;
    info -> utime = strtoul(strtok(NULL, " "), NULL, 10);
    info -> stime = strtoul(strtok(NULL, " "), NULL, 10);
    info -> cutime = strtoul(strtok(NULL, " "), NULL, 10);
    info -> cstime = strtoul(strtok(NULL, " "), NULL, 10);
    info -> pid = pid;
    return 0;
}

static proc_info * get_all_processes(size_t * num) {
    DIR * d = opendir("/proc");
    if (!d) return NULL;
    size_t cap = 256, cnt = 0;
    proc_info * arr = xmalloc(cap * sizeof(proc_info));
    struct dirent * e;
    while ((e = readdir(d))) {
        if (!is_number(e -> d_name)) continue;
        pid_t pid = atoi(e -> d_name);
        proc_info inf;
        if (read_proc_stat(pid, & inf) == 0) {
            if (cnt == cap) arr = xrealloc(arr, (cap *= 2) * sizeof(proc_info));
            arr[cnt++] = inf;
        }
    }
    closedir(d);
    * num = cnt;
    return arr;
}

static int pid_in_list(pid_t pid, pid_t * lst, size_t n) {
    for (size_t i = 0; i < n; ++i)
        if (lst[i] == pid) return 1;
    return 0;
}

static unsigned long long compute_live_cpu_time(pid_t * w, size_t wn, proc_info * a, size_t an) {
    pid_t * grp = xmalloc(wn * sizeof(pid_t));
    size_t gc = wn;
    memcpy(grp, w, wn * sizeof(pid_t));
    int added;
    do {
        added = 0;
        for (size_t i = 0; i < an; ++i)
            if (!pid_in_list(a[i].pid, grp, gc) && pid_in_list(a[i].ppid, grp, gc)) {
                grp = xrealloc(grp, (gc + 1) * sizeof(pid_t));
                grp[gc++] = a[i].pid;
                added = 1;
            }
    }
    while (added);
    unsigned long long tot = 0;
    for (size_t i = 0; i < gc; ++i)
        for (size_t j = 0; j < an; ++j)
            if (a[j].pid == grp[i]) {
                if (pid_in_list(a[j].pid, w, wn)) tot += a[j].utime + a[j].stime;
                else tot += a[j].utime + a[j].stime + a[j].cutime + a[j].cstime;
                break;
            }
    xfree(grp);
    return tot;
}

static unsigned long long read_finished_time_for_pid(pid_t pid,
    const char * pdir) {
    char path[PATH_MAX];
    snprintf(path, sizeof(path), "%s/cpu.%d", pdir, pid);
    FILE * f = fopen(path, "r");
    if (!f) return 0;
    unsigned long long v = 0;
    fscanf(f, "%llu", & v);
    fclose(f);
    return v;
}

static unsigned long long read_all_cpu_time(void) {
    FILE * f = fopen("/proc/stat", "r");
    if (!f) return 0;
    char ln[512];
    unsigned long long sum = 0;
    if (fgets(ln, sizeof(ln), f) && strncmp(ln, "cpu ", 4) == 0) {
        char * tok = strtok(ln + 4, " ");
        while (tok) {
            sum += strtoull(tok, NULL, 10);
            tok = strtok(NULL, " ");
        }
    }
    fclose(f);
    return sum;
}

static int cpuusage_main(int argc, char ** argv) {
    if (argc < 2) {
        builtin_error("cpuusage: missing PIDs");
        return EXECUTION_FAILURE;
    }
    size_t wn = argc - 1;
    pid_t * w = xmalloc(wn * sizeof(pid_t));
    for (size_t i = 0; i < wn; ++i) w[i] = atoi(argv[i + 1]);
    size_t ap;
    proc_info * a = get_all_processes( & ap);
    if (!a) {
        builtin_error("cpuusage: /proc fail");
        xfree(w);
        return EXECUTION_FAILURE;
    }
    unsigned long long live = compute_live_cpu_time(w, wn, a, ap);
    xfree(a);
    char * pdir = get_persistent_dir();
    unsigned long long pers = 0;
    for (size_t i = 0; i < wn; ++i) pers += read_finished_time_for_pid(w[i], pdir);
    xfree(pdir);
    xfree(w);
    unsigned long long total = live + pers, all = read_all_cpu_time();
    printf("%llu %llu\n", total, all);
    return EXECUTION_SUCCESS;
}

struct builtin cpuusage_struct = {
    "cpuusage",
    fr_builtin,
    BUILTIN_ENABLED,
    cpuusage_doc,
    "cpuusage <worker_pid> [<worker_pid> [<...>]]",
    0
};

/* -------------------------------------------------- */
/* Register all builtins  (under fr)                  */
/* -------------------------------------------------- */

static int fr_builtin(WORD_LIST * list) {
    int argc;
    char ** argv = make_builtin_argv(list, & argc);

    char * sub = argv[0];

    int ret;
    if (strcmp(sub, "lseek") == 0) {
        ret = lseek_main(argc, argv);
    } else if (strcmp(sub, "evfd_wait") == 0) {
        ret = evfd_wait_main(argc, argv);
    } else if (strcmp(sub, "evfd_init") == 0) {
        ret = evfd_init_main(argc, argv);
    } else if (strcmp(sub, "evfd_signal") == 0) {
        ret = evfd_signal_main(argc, argv);
    } else if (strcmp(sub, "evfd_copy") == 0) {
        ret = evfd_copy_main(argc, argv);
    } else if (strcmp(sub, "evfd_close") == 0) {
        ret = evfd_close_main(argc, argv);
    } else if (strcmp(sub, "cpuusage") == 0) {
        ret = cpuusage_main(argc, argv);
    } else if (strcmp(sub, "childusage") == 0) {
        ret = childusage_main(argc, argv);
    } else {
        builtin_error("fr: unknown subcommand '%s'", sub);
        ret = EXECUTION_FAILURE;
    }

    xfree(argv);
    return ret;
}

int setup_builtin_forkrun_loadables(void) {
    add_builtin( & lseek_struct, 1);
    add_builtin( & evfd_init_struct, 1);
    add_builtin( & evfd_wait_struct, 1);
    add_builtin( & evfd_signal_struct, 1);
    add_builtin( & evfd_copy_struct, 1);
    add_builtin( & evfd_close_struct, 1);
    add_builtin( & childusage_struct, 1);
    add_builtin( & cpuusage_struct, 1);
    return 0;
}
