/* toy_bind.c — W-MAPAPI Experiment 2: array-binding surface reproducer.
 *
 * Mirrors forkrun_ring.c's ACTUAL array-binding call shapes
 * (forkrun_ring.c:704 make_new_array_variable + NULL check;
 * :662/:673 bind_array_element(arr, (arrayind_t)idx, ptr, 0)).
 * Built ONCE against 5.3-era headers (the shipped blob's provenance);
 * run under 5.1/5.2/5.3 (+4.4 if smooth) to test the H2 theory that
 * a 5.1/5.2 mapfile-overhaul signature/convention change crashes
 * 5.3-built callers. Same -D/-I flags as Makefile.substrate.
 */

#include <sys/types.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef HAVE_CONFIG_H
#include <config.h>
#endif

// clang-format off
#include "command.h"
#include "shell.h"
#include "variables.h"
#include "builtins.h"
#include "common.h"
#include "xmalloc.h"

// See forkrun_ring.c: glibc allocators only, never bash's.
#undef malloc
#undef free
#undef realloc
#undef calloc
// clang-format on

static char *toy_bind_doc[] = {
    "Bind N array elements the way forkrun's do_tokenize does.",
    "toy_bind <array> <count>",
    (char *)NULL
};

static int toy_bind_builtin(WORD_LIST *list)
{
    char *arr_name = "toy_arr";
    char *count_s = "0";
    int count = 64;
    SHELL_VAR *arr;
    int i;

    if (list && list->word && list->word->word)
        arr_name = list->word->word;
    if (list && list->next && list->next->word && list->next->word->word)
        count_s = list->next->word->word;
    count = atoi(count_s);
    if (count <= 0 || count > 100000)
        count = 64;

    /* forkrun_ring.c:704 shape (+ NULL check, as forkrun does). */
    arr = make_new_array_variable(arr_name);
    if (!arr)
        return EXECUTION_FAILURE;

    /* forkrun_ring.c:662 shape: (arrayind_t)idx from a size_t-ish
       counter, string payload, flags 0. */
    for (i = 0; i < count; i++) {
        char buf[64];
        snprintf(buf, sizeof(buf), "value-%d", i);
        /* NOTE: forkrun passes pointers into its mmap batch buffer;
           a stack/local copy is equivalent for the binding call. */
        if (!bind_array_element(arr, (arrayind_t)i, buf, 0))
            return EXECUTION_FAILURE;
    }
    return EXECUTION_SUCCESS;
}

struct builtin toy_bind_struct = {
    "toy_bind", toy_bind_builtin, BUILTIN_ENABLED, toy_bind_doc,
    "toy_bind <array> <count>", 0
};
