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
    "USAGE:    lseek <FD> <REL_OFFSET>",
    "",
    "Move the file descriptor <FD> by <REL_OFFSET>",
    "bytes relative to its current byte offset.",
    "",
    "positive <REL_OFFSET> advances the <FD>",
    "negative <REL_OFFSET> rewinds the <FD>",
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
    "lseek <FD> <REL_OFFSET>",  // Usage string
    0                     // Number of long options
};

// main function
static int lseek_main(int argc, char **argv) {
    // check for exactly 2 args passed to lseek
    if (argc != 3) {
        fprintf(stderr, "\nIncorrect number of arguments.\nUSAGE: lseek <FD> <REL_OFFSET>\n");
        return 1;
    }

    // get + validate file descriptor
    int fd = atoi(argv[1]);
    if (fd == 0 && strcmp(argv[1], "0") != 0) {
        fprintf(stderr, "\nERROR: Invalid file descriptor.\n");
        return 1;
    }

     // get + validate (relative) offset
    errno = 0;
    off_t offset = atoll(argv[2]);
    if (errno == ERANGE) {
        fprintf(stderr, "\nERROR: Offset out of range.\n");
        return 1;
    }

    // call lseek to move fd byte offset 
    if (lseek(fd, offset, SEEK_CUR) == (off_t) -1) {
        fprintf(stderr, "\nERROR: %s\n", strerror(errno));
        return 1;
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
