#ifdef HAVE_CONFIG_H
# include <config.h>
#endif

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

// Helper for builtins
extern char **make_builtin_argv();

/* -------------------------------------------------- */
/* lseek builtin                                    */
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
/* evfd_* builtins                                  */
/* -------------------------------------------------- */
static int evfd = -1;

static char *evfd_init_doc[] = {"evfd_init", NULL};
int evfd_init_builtin(WORD_LIST *list) {
    if (evfd >= 0) { close(evfd); evfd = -1; }
    evfd = eventfd(0, EFD_CLOEXEC);
    if (evfd < 0) { builtin_error("evfd_init: %s", strerror(errno)); return EXECUTION_FAILURE; }
    char buf[32]; snprintf(buf, sizeof(buf), "%d", evfd);
    assign("EVFD_FD", buf, KNOWN_ASSIGNMENT);
    return EXECUTION_SUCCESS;
}
struct builtin evfd_init_struct = {"evfd_init", evfd_init_builtin, BUILTIN_ENABLED, evfd_init_doc, "evfd_init", 0};

static char *evfd_wait_doc[] = {"evfd_wait", NULL};
int evfd_wait_builtin(WORD_LIST *list) {
    int argc; char **argv = make_builtin_argv(list, &argc);
    int read_fd = -1, sig_fd = -1, status_fd = -1;
    if (argc == 1) {
        if (evfd < 0) { builtin_error("evfd_wait: evfd not initialized"); xfree(argv); return EXECUTION_FAILURE; }
        sig_fd = evfd;
    } else if (argc == 2) {
        read_fd = atoi(argv[1]); sig_fd = evfd;
    } else if (argc == 3 || argc == 4) {
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
struct builtin evfd_wait_struct = {"evfd_wait", evfd_wait_builtin, BUILTIN_ENABLED, evfd_wait_doc, "evfd_wait", 0};

static char *evfd_signal_doc[] = {"evfd_signal", NULL};
int evfd_signal_builtin(WORD_LIST *list) {
    int argc; char **argv = make_builtin_argv(list, &argc);
    int fd;
    if (argc == 1) {
        if (evfd < 0) { builtin_error("evfd_signal: evfd not initialized"); xfree(argv); return EXECUTION_FAILURE; }
        fd = evfd;
    } else if (argc == 2) {
        fd = atoi(argv[1]);
    } else {
        builtin_usage(); xfree(argv); return EXECUTION_FAILURE;
    }
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
struct builtin evfd_signal_struct = {"evfd_signal", evfd_signal_builtin, BUILTIN_ENABLED, evfd_signal_doc, "evfd_signal", 0};

static char *evfd_splice_doc[] = {"evfd_splice", NULL};
int evfd_splice_builtin(WORD_LIST *list) {
    int argc; char **argv = make_builtin_argv(list, &argc);
    if (argc != 2) { builtin_usage(); xfree(argv); return EXECUTION_FAILURE; }
    int splice_fd = atoi(argv[1]); const size_t CHUNK = 1 << 20; uint64_t one = 1;
    while (1) {
        ssize_t n = splice(STDIN_FILENO, NULL, splice_fd, NULL, CHUNK, SPLICE_F_MOVE|SPLICE_F_MORE);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        int flags = fcntl(evfd, F_GETFL, 0);
        fcntl(evfd, F_SETFL, flags | O_NONBLOCK);
        syscall(SYS_write, evfd, &one, sizeof(one));
        fcntl(evfd, F_SETFL, flags);
    }
    xfree(argv);
    return EXECUTION_SUCCESS;
}
struct builtin evfd_splice_struct = {"evfd_splice", evfd_splice_builtin, BUILTIN_ENABLED, evfd_splice_doc, "evfd_splice", 0};

static char *evfd_close_doc[] = {"evfd_close", NULL};
int evfd_close_builtin(WORD_LIST *list) {
    if (evfd >= 0) {
        close(evfd);
        evfd = -1;
    }
    unset_internal("EVFD_FD", KSH_UNSET);
    return EXECUTION_SUCCESS;
}
struct builtin evfd_close_struct = {"evfd_close", evfd_close_builtin, BUILTIN_ENABLED, evfd_close_doc, "evfd_close", 0};

/* -------------------------------------------------- */
/* childusage builtin                                */
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
    const char *tmp = getenv("tmpDir");
    if (!tmp) tmp = "/tmp";
    char *pdir = xmalloc(strlen(tmp) + strlen("/.cpuusage") + 1);
    snprintf(pdir, strlen(tmp) + strlen("/.cpuusage") + 1, "%s/.cpuusage", tmp);
    return pdir;
}
static int childusage_main(int argc, char **argv) {
    int quiet = 0;
    if (argc == 2 && (!strcmp(argv[1], "-q") || !strcmp(argv[1], "--quiet"))) {
        quiet = 1;
    } else if (argc > 2) {
        builtin_error("Usage: childusage [ -q | --quiet ]");
        return EXECUTION_FAILURE;
    }
    pid_t pid = getpid();
    struct rusage ru;
    if (getrusage(RUSAGE_CHILDREN, &ru) != 0) {
        builtin_error("getrusage: %s", strerror(errno));
        return EXECUTION_FAILURE;
    }
    long tps = sysconf(_
