# Experiment 1 — Source diffs: array-binding surface + struct builtin

Sources: `/tmp/bash-src/bash-{4.4,5.1,5.2,5.3}/` (upstream tarballs).
Scope: every symbol in the canary stub closure that `do_tokenize` /
`ring_map` touch, plus `struct builtin` (H1) and `arrayind_t`.

## 1. `bind_array_element` — STABLE (H2 core claim refuted)

Declaration (`arrayfunc.h`):

| ver | declaration |
|---|---|
| 4.4 (:41) | `extern SHELL_VAR *bind_array_element __P((SHELL_VAR *, arrayind_t, char *, int));` |
| 5.1 (:53) | `extern SHELL_VAR *bind_array_element PARAMS((SHELL_VAR *, arrayind_t, char *, int));` |
| 5.2 (:82) | same as 5.1 (plus a comment block above) |
| 5.3 (:81) | `extern SHELL_VAR *bind_array_element (SHELL_VAR *, arrayind_t, char *, int);` |

Only the prototype macro changes (`__P` → `PARAMS` → plain ANSI).
Definition (`arrayfunc.c`): all four delegate identically —
`return (bind_array_var_internal (entry, ind, 0, value, flags));`
(4.4/5.1/5.2 K&R style, 5.3 ANSI style; same body).

## 2. Whole stub closure, 5.1→5.2 declarations — 19/19 STABLE

`find_variable`, `bind_variable`, `bind_var_or_array`,
`unbind_variable`, `array_p`, `array_cell`,
`make_new_array_variable`, `bind_array_variable`,
`bind_assoc_variable`, `get_string_value`, `builtin_error`,
`builtin_usage`, `make_builtin_argv`, `add_builtin`, `xfree`,
`xmalloc_dup`, `dispose_command`, `execute_command` — token-normalized
declarations identical (macro-style noise only).

## 3. `arrayind_t` — STABLE (owner refinement 1 exonerated)

`array.h:28`: `typedef intmax_t  arrayind_t;` — byte-identical in all
four versions, unconditional (no ifdefs). 64-bit signed LP64
everywhere. forkrun's `(arrayind_t)idx` cast from `size_t`
(`forkrun_ring.c:662,673`, batch indices) cannot truncate or flip
sign on any version. The "NULL+0x11 via bad hash index" mechanism
has no support.

## 4. `make_new_array_variable` — STABLE (owner refinement 2 exonerated)

- Declaration: `(char *)` → `(const char *)` in 5.3 only
  (`variables.h:363/390/394/417`) — const-correctness, ABI-identical.
- Definition (`variables.c`): 13 lines, **identical 5.1→5.2**;
  4.4→5.1 and 5.2→5.3 differ only in K&R→ANSI style.
- forkrun NULL-checks EVERY result (`forkrun_ring.c:704`,
  `:2741`; `do_tokenize` guards all binds with `if (arr)` including
  the by-design `NULL` fixed_argc call at `:769`). An unchecked
  NULL→bind path does not exist in forkrun's code.

## 5. `bind_array_var_internal` — identical 5.1→5.2 (24 lines)

The shared core under `bind_array_element` did not change in the
overhaul window.

## 6. Where the overhaul actually lives

`builtins/mapfile.def` 5.1→5.2: 55 diff lines, all inside the
`mapfile` builtin's OWN logic (entry setup via
`find_or_make_array_variable`, delim signedness cast, CLEARARRAY
handling). The shared bind entry points above are untouched by it.
`arrayfunc.c`/`array.c`/`variables.c` line deltas (575/82/555 at
5.1→5.2) are the same story: builtin-local and assoc/unset-internal
churn, not callee-visible contract change.

## 7. `struct builtin` — byte-identical 4.4→5.3 (H1 refuted at header)

`builtins.h`: `{ char *name; sh_builtin_func_t *function; int flags;
char * const *long_doc; const char *short_doc; char *handle; }` —
same 6 fields, order, types in all four versions (only the
`builtins.h` diff 4.4→5.1 is 7 lines of macro noise, 5.1→5.2 is 6,
5.2→5.3 is 0). Layout-identical on LP64 by construction. A
5.3-built positional initializer (`forkrun_ring.c:8913` shape)
reads identically on ≤5.1.

## Verdicts

- H2 (signature/convention change): REFUTED (declaration +
  definition + whole-closure sweep + both owner refinements).
- H1 (struct drift): REFUTED at header level (extends Phase 0's
  5.2↔5.3 probe to 4.4).
