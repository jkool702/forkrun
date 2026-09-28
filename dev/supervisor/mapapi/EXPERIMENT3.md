# Experiment 3 — Registration-path liveness probe (H1's mechanism)

## Question

Does the mechanism that actually loads the blob use the structs
(H1's surface) or the `add_builtin` path?

## Method

gdb on bash 5.3, pending breakpoints on both symbols (both resolve —
`setup_builtin_forkrun_ring` in the `.so`, `add_builtin@plt`), then
`enable -f ./ring_loadables/forkrun-libs/forkrun_ring.x86-64-v3.so
ring_version` plus a `ring_version` invocation:

```bash
gdb --batch -ex "set confirm off" -ex "set breakpoint pending on" \
  -ex "break setup_builtin_forkrun_ring" -ex "break add_builtin" \
  -ex "run --noprofile --norc -c 'enable -f ... ring_version'" \
  -ex "info breakpoints" --args /bin/bash
```

## Result

- Both breakpoints RESOLVE (symbols exist).
- `ring_version` prints `v3.6.0` (loadable works).
- **Zero hits on either breakpoint** across the enable + invocation.

## Interpretation

Registration is struct-export-driven: bash's loader reads the
`ring_*_struct` data symbols itself; neither
`setup_builtin_forkrun_ring` nor `add_builtin` is ever called on
the load path. The `add_builtin` path is vestigial, as suspected
(consistent with its absence from every bash's export table per
Phase 0 §0.2, and with `nm -D` showing the 41 `ring_*_struct`
symbols on the artifact).

For H1: the struct surface IS the live dispatch mechanism (raises
its prior as "the thing to check"), but Experiment 1 already
checked it — byte-identical 4.4→5.3 — so there is nothing for a
version drift to bite on. No halt-and-report trigger fired (the
load model is as previously understood).
