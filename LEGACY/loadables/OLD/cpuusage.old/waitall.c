#include <sys/wait.h>
#include "config.h"
#include "builtins.h"
#include "shell.h"

int waitall_builtin(WORD_LIST *list) {
    int status;
    pid_t pid;
    while ((pid = waitpid(-1, &status, WNOHANG)) > 0);
    return EXECUTION_SUCCESS;
}

struct builtin waitall_struct = {
    (char *)"waitall",
    waitall_builtin,
    BUILTIN_ENABLED,
    (char *)"Reap all zombie children",
    NULL
};