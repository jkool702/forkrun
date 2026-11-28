# Sanitizer evidence — prefault_pipeline (WO-NUMA-PIPELINED-MADV-POPULATE-WRITE-STAGE0)

**Separate from existing dist_ingest evidence. NOT claimed to be covered
by it.** Source `prefault_pipeline.c`. Exact source SHA: **470f6905c3b84725980c0b0f603ad521fd869e68**
(prototype C source at clean committed tree; sanitizer re-run + 39 tests at this SHA; `git diff <san-SHA> <final> -- prefault_pipeline.c` empty).; build command + runtime + exit status recorded.

## Build (strict diagnostics)
```
make -C stage0/dist_ingest/prefault_pipeline clean
make -C stage0/dist_ingest/prefault_pipeline            # -Wall -Wextra -Wpedantic -Wshadow -Wconversion -std=gnu11
# sanitizer (isolated artifacts; no clobber):
cc -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined -o prefault_pipeline-asan prefault_pipeline.c -pthread -fsanitize=address,undefined
cc -O1 -g -fno-omit-frame-pointer -fsanitize=thread -o prefault_pipeline-tsan prefault_pipeline.c -pthread -fsanitize=thread
```

## Results (this environment; exact SHA in CLOSEOUT + `git rev-parse HEAD`)
- **Normal**: build + `python3 -m unittest stage0.dist_ingest.prefault_pipeline.tests.test_prefault_pipeline` → 39 OK.
- **ASan+UBSan** (`-fsanitize=address,undefined`, `ASAN_OPTIONS=detect_leaks=1`, `UBSAN_OPTIONS=halt_on_error=1`): smoke all 3 modes + slot-size/gen paths → rc=0, 0 findings; **LSan smoke clean** (memory freed; no leaks reported — not proof).
- **TSan** (`-fsanitize=thread`, `halt_on_error=1`): all 3 modes → rc=0, 0 `WARNING: ThreadSanitizer`; verified runtime + instrumentation.
- **LSan** attempted; effective on smoke; absence ≠ proof no leaks.
- No sanitizer coverage is claimed for code not present; existing dist_ingest evidence NOT reused.

## Runtime configuration
Linux `memfd_create`, `ftruncate`, `MAP_SHARED`, `MADV_POPULATE_WRITE`, `fallocate(PUNCH_HOLE|KEEP_SIZE)`, `sched_setaffinity`, `SYS_set_mempolicy`, `SYS_mbind`, `SYS_move_pages`, `poll`, `RUSAGE_THREAD`, C11 `_Atomic` + pthread. `MADV_POPULATE_WRITE` kernel support + `PUNCH_HOLE` capability validated at runtime; unsupported => explicit failure (no silent fallback); placement unverified => reported.
