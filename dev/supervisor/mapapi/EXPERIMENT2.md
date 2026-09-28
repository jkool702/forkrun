# Experiment 2 — Toy-loadable reproducer matrix

## Fidelity (what was mirrored)

`toy_bind.c` (this directory) replicates forkrun's exact call shapes:
- `make_new_array_variable(name)` + NULL check (`forkrun_ring.c:704`);
- `bind_array_element(arr, (arrayind_t)idx, ptr, 0)` in a loop over
  64 stack-string values (`:662/:673`; `:2766`/`:7789` same shape;
  `:9551` same flags).
- `struct builtin toy_bind_struct` positional init mirrors
  `DEFINE_STRUCT_X` (`forkrun_ring.c:8913`): name, function,
  `BUILTIN_ENABLED`, doc array, usage literal, 0.
- Same toolchain/flags as the shipped blob provenance: gcc 16,
  `-O1 -fPIC -DSHELL -DHAVE_CONFIG_H -I/usr/include/bash{,/include,
  /builtins}` (bash-devel 5.3.9), shared link leaving bash symbols
  undefined (as the real blob links). U-list is exactly
  `bind_array_element` + `make_new_array_variable` (+ libc).

Build:

```bash
gcc -O1 -fPIC -Wall -Wextra -DSHELL -DHAVE_CONFIG_H \
  -I/usr/include/bash -I/usr/include/bash/include \
  -I/usr/include/bash/builtins \
  -c dev/supervisor/mapapi/toy_bind.c -o /tmp/opencode/toy_bind.o
gcc -shared -o /tmp/opencode/toy_bind.so /tmp/opencode/toy_bind.o -ldl
```

(Two build frictions, both fixed in the committed source: bash
headers need `<sys/types.h>` first (`pid_t`); struct usage string
must be a literal, not a variable (constant initializer). The
`--no-undefined` link correctly FAILS on the bash symbols — the
real blob links the same way; dropped for the toy.)

Run (per cell, ×5):

```bash
$BIN --noprofile --norc -c \
  'enable -f /tmp/opencode/toy_bind.so toy_bind && toy_bind toy_arr 64 && echo "arr63=${toy_arr[63]} n=${#toy_arr[@]}"'
```

## Matrix (25/25 clean — H2 eliminated live)

| bash | binary | result ×5 |
|---|---|---|
| 4.4.20 | extracted Ubuntu | `arr63=value-63 n=64`, rc=0 ×5 |
| 5.0.17 | extracted Ubuntu | same ×5 |
| 5.1.16 | extracted Ubuntu | same ×5 |
| 5.2.21 | extracted Ubuntu (exact CI build) | same ×5 |
| 5.3.9 | extracted Ubuntu | same ×5 |

A 5.3-built caller of `make_new_array_variable` +
`bind_array_element` runs perfectly on every version 4.4→5.3.
Combined with Experiment 1 (source-stable) and forkrun's NULL
guards, the array-binding surface is exonerated three ways:
signature, behavior-live, and call-site hygiene.

Note: this exonerates the *binding API*, not the *worker*. frun
worker execution still segfaults on ≤5.1 (see VERDICT.md) — via a
mechanism outside this surface.
