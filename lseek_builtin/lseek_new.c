#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
#include <fcntl.h>

#include "command.h"
#include "builtins.h"
#include "shell.h"
#include "common.h"
#include "bashgetopt.h"
#include "xmalloc.h"
#include "variables.h"  

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

#ifndef errno
extern int errno;
#endif

// Function declaration for our builtin
static int lseek_main(int argc, char **argv);
int lseek_builtin(WORD_LIST *list);
extern char **make_builtin_argv();

// Metadata about the builtin
static char *lseek_doc[] = {
    "",
    "----------------------------------------------",
    "USAGE:    lseek [-v <VAR> | -q] <FD> <REL_OFFSET> [<SEEK_TYPE>]",
    "",
    "Move the file descriptor <FD> by <REL_OFFSET>",
    "bytes relative to its current byte offset.",
    "",
    "positive <REL_OFFSET> advances the <FD>",
    "negative <REL_OFFSET> rewinds the <FD>",
    "",
    "SEEK_TYPE is optional and can take the value of:",
    "     'SEEK_SET'   'SEEK_CUR'    'SEEK_END'",
    "  If omitted, SEEK_CUR is used.",
    "",
    "If -v <VAR> are the first 2 args, the final byte offset",
    "for the file descriptor will be saved in variable <VAR>.",
    "If omitted, it will be printed to stdout unless the 1st arg is -q.",
    "----------------------------------------------",
    "",
    NULL
};

// Struct to register the builtin with bash
struct builtin lseek_struct = {
    "lseek",              // Name of the builtin
    lseek_builtin,        // Function to call
    BUILTIN_ENABLED,      // Default status
    lseek_doc,            // Documentation strings
    "lseek [-v <VAR> | -q] <FD> <REL_OFFSET> [<SEEK_TYPE>]",  // Usage string
    0                     // Number of long options
};

// main function
static int lseek_main(int argc, char **argv) {
    optind = 1; // Reset getopt() state
    int opt;
    char *varname = NULL;
    int fd_index = 1;  // Default index for FD argument
    int quiet = 0;     // Suppress output flag

    // Parse optional flags
    while ((opt = getopt(argc, argv, "v:q")) != -1) {
        switch (opt) {
            case 'v':
                varname = optarg;
                fd_index += 2;  // Shift FD index to account for -v <varname>
                break;
            case 'q':
                quiet = 1;  // Enable quiet mode
                fd_index += 1;  // Shift FD index to account for -q
                break;			
            default:
                fprintf(stderr, "Usage: lseek [-v varname | -q] <FD> <REL_OFFSET> [<SEEK_TYPE>]\n");
                return 1;
        }
    }

    // Ensure enough arguments remain
    if (argc - fd_index < 2 || argc - fd_index > 3) {
        fprintf(stderr, "Usage: lseek [-v varname | -q] <FD> <REL_OFFSET> [<SEEK_TYPE>]\n");
        return 1;
    }

    // Get + validate file descriptor
    int fd = atoi(argv[fd_index]);
    if (fd == 0 && strcmp(argv[fd_index], "0") != 0) {
        fprintf(stderr, "ERROR: Invalid file descriptor.\n");
        return 1;
    }

    // Get + validate offset
    errno = 0;
    off_t offset = atoll(argv[fd_index + 1]);
    if (errno == ERANGE) {
        fprintf(stderr, "ERROR: Offset out of range.\n");
        return 1;
    }

    // Get SEEK_TYPE
    int whence = SEEK_CUR;
    if (argc - fd_index == 3) {
        if (strcmp(argv[fd_index + 2], "SEEK_SET") == 0) {
            whence = SEEK_SET;
        } else if (strcmp(argv[fd_index + 2], "SEEK_END") == 0) {
            whence = SEEK_END;
        } else if (strcmp(argv[fd_index + 2], "SEEK_CUR") != 0) {
            fprintf(stderr, "ERROR: Invalid SEEK_TYPE. Must be SEEK_SET, SEEK_CUR, or SEEK_END\n");
            return 1;
        }
    }

    // Call lseek to move fd byte offset
    off_t new_offset = lseek(fd, offset, whence);
    if (new_offset == (off_t)-1) {
        fprintf(stderr, "ERROR: %s\n", strerror(errno));
        return 1;
    }

    // If -v flag was used, save new offset in the shell variable
    if (varname) {
        char offset_str[32];
        snprintf(offset_str, sizeof(offset_str), "%lld", (long long)new_offset);
        bind_variable(varname, offset_str, 0);
    } else if (!quiet) {
        // Otherwise, print to stdout unless -q was specified
        printf("%lld\n", (long long)new_offset);
        fflush(stdout);
    }

    return 0;
}

// func to convert WORD_LIST to argc + argv 
// (this one is called by the builtin)
int lseek_builtin(WORD_LIST *list) {
    int c, r;
    char **v;

    v = make_builtin_argv(list, &c);
    r = lseek_main(c, v);
    xfree(v);

    return r;
}
