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

Result (dated 2026-11-23): **Ran 246 tests — OK, 0 ASan/UBSan reports, 0 UBSan runtime errors**
(UBSan in gcc's default recover mode: any `runtime error` line would have been
captured; none fired).

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

Result (dated 2026-11-23): **Ran 246 tests — OK, 0 ThreadSanitizer warnings**
(empty `WARNING: ThreadSanitizer` set captured).

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
- `dist_ingest.c` was not changed by the C4/C5 corrections (calibration is
  Python-side); sanitizers therefore validate the C code as of
  `3e6a924e` (corrections-2 tip).
