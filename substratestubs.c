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
void *find_variable(const char *n) { (void)n; return 0; }
void *bind_variable(const char *n, const char *v, int f) { (void)n; (void)v; (void)f; return 0; }
void *bind_var_or_array(const char *n, char *v, int f) { (void)n; (void)v; (void)f; return 0; }
void unbind_variable(const char *n) { (void)n; }
int array_p(void *v) { (void)v; return 0; }
void *array_cell(void *v) { (void)v; return 0; }
void *make_new_array_variable(char *n) { (void)n; return 0; }
void *bind_array_element(void *v, long i, const char *s, int f) { (void)v; (void)i; (void)s; (void)f; return 0; }
void *bind_assoc_variable(void *v, const char *k, const char *s, int f) { (void)v; (void)k; (void)s; (void)f; return 0; }
void *bind_array_variable(const char *n, long i, const char *s, int f) { (void)n; (void)i; (void)s; (void)f; return 0; }
char *get_string_value(const char *n) { (void)n; return 0; }

/* --- builtins --- */
void builtin_error(const char *fmt, ...) { (void)fmt; }
void builtin_usage(void) {}
int make_builtin_argv(void *list, int *argc) { if (argc) *argc = 0; return 0; }
int add_builtin(void *bp, int keep) { (void)bp; (void)keep; return 0; }
void xfree(void *p) { free(p); }
char *xmalloc_dup(const char *s) { return s ? strdup(s) : 0; }

/* --- commands --- */
void dispose_command(void *c) { (void)c; }
int execute_command(void *c) { (void)c; return 0; }
