#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
#include <fcntl.h>
#include <limits.h>

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
    "  If omitted, SEEK_CUR is used by default.",
    "",
    "<VAR> is optional. If present, the new byte offset of",
    "  file descriptor <FD> will be saved in variable <VAR>",
    "",
    "NOTE: to use 'SEEK_SET' or 'SEEK_CUR' or 'SEEK_END' as <VAR>,",
    "  <SEEK_TYPE> *must* explicitly be passed on the lseek cmdline",
    "--------------------------------------------------------------",
    "",
    NULL
};

// Struct to register the builtin with bash
struct builtin lseek_struct = {
    "lseek",              // Name of the builtin
    lseek_builtin,        // Function to call
    BUILTIN_ENABLED,      // Default status
    lseek_doc,            // Documentation strings
    "lseek <FD> <OFFSET> [<SEEK_TYPE>] [<VAR>]",  // Usage string
    0                     // Number of long options
};

// main function
static int lseek_main(int argc, char **argv) {
    // check for 3, 4, or 5 arguments
    if (argc < 3 || argc > 5) {
        fprintf(stderr, "\nIncorrect number of arguments.\nUSAGE: lseek <FD> <OFFSET> [<SEEK_TYPE>] [<VAR>]\n");
        return 1;
    }

    // Get + validate file descriptor
    int fd = atoi(argv[1]);
    if (fd == 0 && strcmp(argv[1], "0") != 0) {
        fprintf(stderr, "\nERROR: Invalid file descriptor.\n");
        return 1;
    }

    // Get + validate offset
    errno = 0;
    off_t offset = atoll(argv[2]);
    if (offset == LLONG_MAX || offset == LLONG_MIN) {  // Better range check
        fprintf(stderr, "\nERROR: Offset out of range.\n");
        return 1;
    }

    // Default SEEK_TYPE is SEEK_CUR
    int whence = SEEK_CUR;
    char *varname = NULL;

    // Handle SEEK_TYPE and optional VAR
    if (argc > 3) {
        // If argv[3] is a valid SEEK_TYPE, set it
        if (strcmp(argv[3], "SEEK_SET") == 0) {
            whence = SEEK_SET;
        } else if (strcmp(argv[3], "SEEK_END") == 0) {
            whence = SEEK_END;
        }
        // If argv[3] is SEEK_CUR or empty, do nothing (default is SEEK_CUR)
        else if (strcmp(argv[3], "SEEK_CUR") == 0 || argv[3][0] == '\0') {
            // No action needed
        }
        // If 4 args and argv[3] is not a valid SEEK_TYPE, assume it's a variable name
        else if (argc == 4) {
            varname = argv[3];
        }
        // If 5 args but argv[3] is invalid, print an error
        else {
            fprintf(stderr, "Error: Invalid SEEK_TYPE. Must be SEEK_SET, SEEK_CUR, SEEK_END, or empty ('').\n");
            return 1;
        }

        // If there are 5 arguments, the last one is always the variable name
        if (argc == 5) {
            varname = argv[4];
        }
    }

    // Call lseek to move fd byte offset 
    off_t new_offset = lseek(fd, offset, whence);
    if (new_offset == (off_t)-1) {
        fprintf(stderr, "ERROR: %s\n", strerror(errno));
        return 1;
    }

    // If <VAR> was provided, then store new byte offset in shell variable "varname"
    if (varname) {
        char offset_str[32];
        snprintf(offset_str, sizeof(offset_str), "%lld", (long long)new_offset);
        bind_variable(varname, offset_str, 0);
    } else {
        // Otherwise, print to stdout
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
