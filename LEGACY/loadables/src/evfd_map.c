#include "config.h"
#include "command.h"
#include "builtins.h"
#include "shell.h"
#include "common.h"
#include "xmalloc.h"

#include <sys/eventfd.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>
#include <stdio.h>
#include <sys/stat.h>
#include <sys/types.h>

static int evfd = -1;

/* -------------------------------------------------- */
/* evfd_init     — create the eventfd and export FD   */
/* -------------------------------------------------- */
static char *evfd_init_doc[] = {
    "evfd_init",
    "----------------------------------------------",
    "USAGE:    evfd_init",
    "",
    "Create a new eventfd(0) and export its FD in EVFD_FD.",
    "Subsequent evfd_wait / evfd_signal calls use this FD.",
    "----------------------------------------------",
    NULL
};

int evfd_init_builtin(WORD_LIST *list)
{
    if (evfd >= 0) {
        close(evfd);
        evfd = -1;
    }

    evfd = eventfd(0, EFD_CLOEXEC);
    if (evfd < 0) {
        builtin_error("evfd_init: eventfd: %s", strerror(errno));
        return 1;
    }

    char buf[32];
    snprintf(buf, sizeof(buf), "%d", evfd);
    assign("EVFD_FD", buf, KNOWN_ASSIGNMENT);
    return 0;
}

struct builtin evfd_init_struct = {
    .name       = "evfd_init",
    .function   = evfd_init_builtin,
    .flags      = BUILTIN_ENABLED,
    .long_docs  = evfd_init_doc,
    .short_docs = "evfd_init",
};

/* -------------------------------------------------- */
/* evfd_wait     — block until event or immediate if data */
/*                optional status pipe fd reports wait */
/* -------------------------------------------------- */
static char *evfd_wait_doc[] = {
    "evfd_wait",
    "----------------------------------------------",
    "USAGE:    evfd_wait [read_fd] [evfd_fd] [status_pipe_fd]",
    "",
    "If read_fd is given, check for leftover data and return immediately if present.",
    "Else block on the eventfd counter. If status_pipe_fd is provided,",
    "write '0\n' if returned immediately, '1\n' if waited.",
    "----------------------------------------------",
    NULL
};

int evfd_wait_builtin(WORD_LIST *list)
{
    int argc; char **argv = make_builtin_argv(list, &argc);
    int read_fd = -1, sig_fd = -1, status_fd = -1;

    if (argc == 1) {
        if (evfd < 0) {
            builtin_error("evfd_wait: evfd not initialized; call evfd_init first");
            xfree(argv);
            return 1;
        }
        sig_fd = evfd;
    }
    else if (argc == 2) {
        read_fd = atoi(argv[1]);
        sig_fd  = evfd;
    }
    else if (argc == 3 || argc == 4) {
        read_fd = atoi(argv[1]);
        if (argv[2][0] == '\0') {
            sig_fd = evfd;
        } else {
            sig_fd = atoi(argv[2]);
        }
        if (argc == 4) {
            status_fd = atoi(argv[3]);
        }
    }
    else {
        builtin_usage();
        xfree(argv);
        return 1;
    }

    /* Preflight: if read_fd given and file has extra data, return immediately */
    if (read_fd >= 0) {
        off_t pos = lseek(read_fd, 0, SEEK_CUR);
        struct stat st;
        if (pos >= 0 && fstat(read_fd, &st) == 0 && st.st_size > pos) {
            if (status_fd >= 0) {
                dprintf(status_fd, "0\n");
            }
            xfree(argv);
            return 0;
        }
    }

    /* Block on the eventfd counter */
    uint64_t cnt;
    if (read(sig_fd, &cnt, sizeof(cnt)) != sizeof(cnt)) {
        builtin_error("evfd_wait: read: %s", strerror(errno));
        xfree(argv);
        return 1;
    }

    /* Report that we did wait */
    if (status_fd >= 0) {
        dprintf(status_fd, "1\n");
    }

    xfree(argv);
    return 0;
}

struct builtin evfd_wait_struct = {
    .name       = "evfd_wait",
    .function   = evfd_wait_builtin,
    .flags      = BUILTIN_ENABLED,
    .long_docs  = evfd_wait_doc,
    .short_docs = "evfd_wait [read_fd] [evfd_fd] [status_pipe_fd]",
};

/* -------------------------------------------------- */
/* evfd_signal   — non-blocking notify (drops on err) */
/* -------------------------------------------------- */
static char *evfd_signal_doc[] = {
    "evfd_signal",
    "----------------------------------------------",
    "USAGE:    evfd_signal [fd]",
    "",
    "Non-blocking increment of the eventfd counter by 1.",
    "If write would block (overflow), drops silently.",
    "If no fd is passed, uses $EVFD_FD.",
    "----------------------------------------------",
    NULL
};

int evfd_signal_builtin(WORD_LIST *list)
{
    int argc; char **argv = make_builtin_argv(list, &argc);
    int fd;

    if (argc == 1) {
        if (evfd < 0) {
            builtin_error("evfd_signal: evfd not initialized; call evfd_init first");
            xfree(argv);
            return 1;
        }
        fd = evfd;
    }
    else if (argc == 2) {
        fd = atoi(argv[1]);
    }
    else {
        builtin_usage();
        xfree(argv);
        return 1;
    }

    uint64_t one = 1;
    int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    if (write(fd, &one, sizeof(one)) != sizeof(one) && errno != EAGAIN) {
        builtin_error("evfd_signal: write: %s", strerror(errno));
    }
    fcntl(fd, F_SETFL, flags);

    xfree(argv);
    return 0;
}

struct builtin evfd_signal_struct = {
    .name       = "evfd_signal",
    .function   = evfd_signal_builtin,
    .flags      = BUILTIN_ENABLED,
    .long_docs  = evfd_signal_doc,
    .short_docs = "evfd_signal [fd]",
};

/* -------------------------------------------------- */
/* evfd_close    — tear down the eventfd              */
/* -------------------------------------------------- */
static char *evfd_close_doc[] = {
    "evfd_close",
    "----------------------------------------------",
    "USAGE:    evfd_close",
    "",
    "Close the shared eventfd and unset $EVFD_FD.",
    "----------------------------------------------",
    NULL
};

int evfd_close_builtin(WORD_LIST *list)
{
    if (evfd >= 0) {
        close(evfd);
        evfd = -1;
    }
    unset_internal("EVFD_FD", KSH_UNSET);
    return 0;
}

struct builtin evfd_close_struct = {
    .name       = "evfd_close",
    .function   = evfd_close_builtin,
    .flags      = BUILTIN_ENABLED,
    .long_docs  = evfd_close_doc,
    .short_docs = "evfd_close",
};

/* -------------------------------------------------- */
/* Register all builtins on load                     */
/* -------------------------------------------------- */
int setup_builtin_evfd(void)
{
    add_builtin(&evfd_init_struct,   1);
    add_builtin(&evfd_wait_struct,   1);
    add_builtin(&evfd_signal_struct, 1);
    add_builtin(&evfd_close_struct,  1);
    return 0;
}
