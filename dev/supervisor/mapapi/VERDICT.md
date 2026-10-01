# W-MAPAPI Verdict — one page for D-wave planning

## H2 (mapfile-API signature change): ELIMINATED

Three independent kills:
1. **Source:** `bind_array_element` declaration + delegating
   definition identical 4.4→5.3; whole 19-symbol stub closure
   STABLE 5.1→5.2; `bind_array_var_internal` body identical
   5.1→5.2. The overhaul touched `mapfile`-the-builtin's own
   logic only.
2. **Live:** 5.3-built toy calling the exact forkrun shapes runs
   25/25 clean on 4.4/5.0/5.1/5.2.21/5.3.9.
3. **Call-site hygiene:** forkrun NULL-checks every
   `make_new_array_variable` result and guards every bind with
   `if (arr)` — no unchecked-NULL path exists to produce the
   observed NULL+offset fault.

Owner refinements, both exonerated with the requested evidence:
`arrayind_t` is `typedef intmax_t` ×4 (cast safe);
`make_new_array_variable` is signature- and body-stable with the
only delta const-correctness in 5.3.

## H1 (struct drift): LOWERED to background

Struct byte-identical 4.4→5.3 (extends Phase 0); registration
proven struct-driven with `add_builtin` vestigial (Exp 3) — so the
live mechanism was checked and is clean. No evidence for H1
remains, but it is not *disproven* as a class the way H2 is
(H1 makes no falsifiable prediction beyond "layout differs",
which is false).

## The actual finding (bigger than H1/H2)

frun worker execution segfaults on ≤5.1 **version-intrinsically**:
source-built 5.1.0 (host libc, `-std=gnu17` + `-Wno-error` kit
for the C23-strict host compiler) reproduces the exact signature
(top-shell `return` complaint + cleanroom-exec-line SIGSEGV,
NULL+0x11) seen with Ubuntu binaries on 5.1.16 — and pristine
`main:frun.bash` fails identically, so no recent wave is
implicated. The extracted-binary methodology is thereby validated
(source 5.2.0 and extracted 5.2.21 behave identically: green).

## Recommended D focus

1. **Bisect worker/cleanroom shell constructs** for a 5.1-hostile
   form (NOT the array API, NOT the struct — both exonerated).
   Start from the strace anchor (death amid sigprocmask dance in a
   forked worker child) and the `exec -c` cleanroom line; suspect
   version-sensitive shell grammar or a builtin-behavior delta in
   the generated worker code, tested directly with `enable`d
   probes per construct.
2. **glibc wall is a separate axis** (x86-64 blobs need
   `GLIBC_ABI_GNU2_TLS`; `-mtls-dialect=gnu` drops it locally) —
   do not conflate with the bash-version work.
3. Keep the toy + matrices: if a future suspect is another
   bash-internal API, the toy pattern re-targets in minutes.

## What this evidence does NOT prove (house rule)

- The crashing construct is **unidentified** — only the exonerated
  surfaces are known. "Something third" (not array API, not
  struct) is now the leading shape, unnamed.
- 4.4 worker behavior beyond the toy (frun runs fail there like
  5.1 in the compat matrix, but no 4.4 source build or core was
  taken — the 4.4 leg rests on the shared signature + toy green).
- The `add_builtin` vestigiality conclusion is load-path-only;
  nothing says anything about hypothetical future registration
  designs.
