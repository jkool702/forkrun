# Sanitizer evidence — dist_ingest.c (C2/C3/corrections; local, no rental)

Engine under test: `stage0/dist_ingest/dist_ingest.c` (the experimental
distributed-ingest engine, changed by C1/C2/C3 and the C4/C5 corrections).

Environment: this rehearsal/rental-prep box (UMA, fake-NUMA boot available);
`gcc` (GCC 16, `libasan.so.8`/`libtsan.so.2` via ldconfig), clang 22 present
but not used (its `__atomic_fetch_add` rejects `_Atomic`-qualified pointers —
a real, verified toolchain difference).

Suite run: `python3 -m unittest discover -s stage0/dist_ingest/tests`
(254 tests; includes `test_randomized_stress` — repeated randomized stress —
`test_multi_node_race`, `test_stall_and_recovery`, `test_slow_consumer_backpressure`,
the placement-sampling on/off isolation tests, and the §5.2
`TestIngestorWorkloadControls` engine tests + 2 campaign-wiring tests).

Engine under test includes §5.2 per-node ingestor workload controls
(dist_ingest.c updated by corrections-3) and §2 `placement_sampling=2` (full).

## ASan + UBSan

Build:

```
cd stage0/dist_ingest
make clean
make CC=gcc CFLAGS="-O1 -g -fno-omit-frame-pointer -fPIC -fsanitize=address,undefined" \
     LDFLAGS="-shared -pthread -fsanitize=address,undefined" NUMA_LIBS="-lnuma"
# produces ../libdist_ingest.so (DT_NEEDED: libasan.so.8, libubsan.so.1; __asan_init present)
LD_PRELOAD=/lib64/libasan.so.8 python3 -m unittest discover -s stage0/dist_ingest/tests
```

Result (dated 2026-11-23; **rerun** — the pre-existing evidence claimed 246
tests against corrections-2 tip `3e6a924e`, which did not match the 254-test
suite on the corrected corrections-4 tree `60a699e2`): **Ran 259 tests —
OK, 0 ASan/UBSan reports, 0 UBSan runtime errors**
(UBSan in gcc's default recover mode: any `runtime error` line would have been
captured; none fired).
Test source SHA: `60a699e2e38e976932d0e7c2b70abdfbd1f3c870`;
**clean** working tree (`git status --short` empty) at that SHA — the
corrections-3 finding that the C code moved after the evidence was recorded
is resolved: the evidence now names the tree it validated.
Build: `make CC=gcc CFLAGS="-O1 -g -fno-omit-frame-pointer -fPIC -fsanitize=address,undefined" LDFLAGS="-shared -pthread -fsanitize=address,undefined" NUMA_LIBS="-lnuma"` —
`__asan_init` present in `stage0/libdist_ingest.so` (not stripped).

**Corrections-4 rerun (conditional acceptance):** rerun on tip
`4b5297bb9b8e14be459aa074ce2e7236b7e0fd31` of
`WO-NUMA-ONE-SHOT-RENTAL-PREPARATION-C4-C5-CORRECTIONS-4` (final code commit
`3d023d66`; tip adds only doc-only changes — `git diff 3d023d66 4b5297bb --
stage0/dist_ingest/dist_ingest.c` is empty): **Ran 259 tests — OK, 0
ASan/UBSan reports, 0 UBSan runtime errors** (2026-11-24).
Build: same flags (rebuilt at `3d023d66`); `__asan_init` present in
`stage0/libdist_ingest.so` (not stripped).

## TSan

Build:

```
cd stage0/dist_ingest
make clean
make CC=gcc CFLAGS="-O1 -g -fno-omit-frame-pointer -fPIC -fsanitize=thread" \
     LDFLAGS="-shared -pthread -fsanitize=thread" NUMA_LIBS="-lnuma"
# produces ../libdist_ingest.so (__tsan_init/__tsan_report symbols present)
LD_PRELOAD=/lib64/libtsan.so.2 python3 -m unittest discover -s stage0/dist_ingest/tests
```

Result (dated 2026-11-23; **rerun** — matching the ASan+UBSan rerun):
**Ran 259 tests — OK, 0 ThreadSanitizer warnings**
(empty `WARNING: ThreadSanitizer` set captured).
Test source SHA: `60a699e2e38e976932d0e7c2b70abdfbd1f3c870` (clean tree —
`__tsan_init`/`__tsan_report` symbols present in `stage0/libdist_ingest.so`).

**Corrections-4 rerun (conditional acceptance):** rerun on tip
`4b5297bb9b8e14be459aa074ce2e7236b7e0fd31`: **Ran 259 tests — OK, 0
ThreadSanitizer warnings** (2026-11-24).
Build: `make CC=gcc CFLAGS="-O1 -g -fno-omit-frame-pointer -fPIC -fsanitize=thread" LDFLAGS="-shared -pthread -fsanitize=thread" NUMA_LIBS="-lnuma"` —
`__tsan_init`/`__tsan_report` present in `stage0/libdist_ingest.so` (not
stripped; tip's extra commit is doc-only over `3d023d66`).

## Honest scope notes

- ASan/UBSan/TSan run the engine under the full dist-ingest suite (including
  the randomized stress test) — not a hand-picked subset.
- Leak checking is not separately claimed: gcc's ASan runtime was preloaded,
  not compiled in, and LeakSanitizer only reports on clean interpreter exit;
  no leak reports were observed in the ASan run (LSan runs as part of the
  ASan process exit path when the runtime is present).
- Failure-injection coverage is the engine's own `pread_seam`/`placement_seam`
  test seams (exercised by the suite, e.g. `TestCheckpoint2PlacementSamplingIsolation`
  seam tests and the seam/counter assertions in `test_dist_ingest.py`); there
  is no standalone randomized fault-injection fuzzer — failure modes are
  covered deterministically by the suite under the sanitizers above.
- Sanitizer runs at SHA `60a699e2` (corrections-3) include the
  corrections-3 C changes; sanitizer runs at `4b5297bb9b8e14be459aa074ce2e7236b7e0fd31`
  (corrections-4 tip; final code commit `3d023d66`) include the
  corrections-4 fixes (rate-limit error path, exhaustive
  `placement_sampling=2`). Both reruns: 259 tests, 0 findings.
- `git diff 3d023d66 4b5297bb -- stage0/dist_ingest/dist_ingest.c` is empty —
  the final tip's extra commit is doc-only (`epyc/RENTAL_READINESS.md`,
  `stage0/dist_ingest/CLOSEOUT.md`), so the sanitizer SHAs are code-exact:
  sanitizer at `3d023d66` covers the `4b5297bb` tip's C code.
