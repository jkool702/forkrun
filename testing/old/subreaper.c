#include <sys/prctl.h>
#include "config.h"
#include "builtins.h"
#include "shell.h"

int subreaper_builtin(WORD_LIST *list) {
    if (prctl(PR_SET_CHILD_SUBREAPER, 1) == -1) {
        perror("prctl");
        return EXECUTION_FAILURE;
    }
    return EXECUTION_SUCCESS;
}

struct builtin subreaper_struct = {
    (char *)"subreaper",  // Explicit cast for name
    subreaper_builtin,
    BUILTIN_ENABLED,
    (char *)"Set process as child subreaper",  // Cast for short_doc
    NULL
};