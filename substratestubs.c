/* substratestubs.c — bash-internal stubs for the Stage-1 link canary.
 *
 * forkrun_ring.c is a bash loadable: it calls into bash internals
 * (variables, builtins, xmalloc...). The canary links the SAME TU against
 * these stubs with -Wl,--no-undefined so CI fails the moment the engine
 * gains a NEW bash-internal dependency. The stub list is the current
 * closure — shrinking it is progress (decoupling), growing it needs
 * justification in the commit message.
 *
 * This does NOT make the engine standalone yet (physical forkrun_core.c
 * split comes later); it freezes the boundary so the split is mechanical.
 */
#include <stdlib.h>
#include <string.h>

/* Opaque bash types, sized as pointers only. */
typedef void *SHELL_VAR_p;
typedef void *ARRAY_p;

/* --- variables --- */
void *find_variable(const char *n) /* since 4.4 */ { (void)n; return 0; }
void *bind_variable(const char *n, const char *v, int f) /* since 4.4 */ { (void)n; (void)v; (void)f; return 0; }
void *bind_var_or_array(const char *n, char *v, int f) /* unexported: canary boundary marker (never resolved at runtime) */ { (void)n; (void)v; (void)f; return 0; }
void unbind_variable(const char *n) /* since 4.4 */ { (void)n; }
int array_p(void *v) /* unexported: canary boundary marker (never resolved at runtime) */ { (void)v; return 0; }
void *array_cell(void *v) /* unexported: canary boundary marker (never resolved at runtime) */ { (void)v; return 0; }
void *make_new_array_variable(char *n) /* since 4.4 */ { (void)n; return 0; }
void *bind_array_element(void *v, long i, const char *s, int f) /* since 4.4 */ { (void)v; (void)i; (void)s; (void)f; return 0; }
void *bind_assoc_variable(void *v, const char *k, const char *s, int f) /* since 4.4 */ { (void)v; (void)k; (void)s; (void)f; return 0; }
void *bind_array_variable(const char *n, long i, const char *s, int f) /* since 4.4 */ { (void)n; (void)i; (void)s; (void)f; return 0; }
char *get_string_value(const char *n) /* since 4.4 */ { (void)n; return 0; }

/* --- builtins --- */
void builtin_error(const char *fmt, ...) /* since 4.4 */ { (void)fmt; }
void builtin_usage(void) /* since 4.4 */ {}
int make_builtin_argv(void *list, int *argc) /* since 4.4 */ { (void)list; /* signature fidelity: mirrors bash's make_builtin_argv(WORD_LIST *); the stub ignores the list. */ if (argc) *argc = 0; return 0; }
void xfree(void *p) /* since 4.4 */ { free(p); }
char *xmalloc_dup(const char *s) /* unexported: canary boundary marker (never resolved at runtime) */ { return s ? strdup(s) : 0; }

/* --- commands --- */
void dispose_command(void *c) /* since 4.4 */ { (void)c; }
int execute_command(void *c) /* since 4.4 */ { (void)c; return 0; }
