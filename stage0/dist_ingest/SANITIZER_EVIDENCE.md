# Sanitizer evidence — dist_ingest.c (experimental)

Engine under test: `stage0/dist_ingest/dist_ingest.c` +
`dist_ingest.h`. Reproducible harness: `tools/di_sanitizer_harness.sh
asan-ubsan|tsan` (clean-tree required; exact SHA; make-clean + sanitizer-
build status; instrumentation symbol; loaded artifact; SHA-256 unchanged;
isolated preflight (CK-1 DI_OUTPUT); real test RC; accurate diagnostics;
machine-readable result.json on any failure; nonzero on REVIEW_REQUIRED;
runtime discovery; compiler/flags/runtime recorded; logs preserved).

## Identities (distinct; CK-7.1)
- **Sanitizer-tested source SHA:** `3f4f3f892a045d5c2c733b1825bd19dcdd973de6`
  (dirty=0; both modes; CLEAN tree).
- **Final C-code SHA:** last commit touching `dist_ingest.c`/`dist_ingest.h`
  — dist_ingest.c `a6ba01a0ccfb3ba51d8fd3af11ae7d87f0fb3213`,
  dist_ingest.h `6a0d6cd47eb4cb632f6086578681ab8109c41098`; C content
  unchanged by sanitizer run + subsequent commits. (actual SHA recorded
  by `git log`; not requiring self-reference.)
- **Final branch HEAD** + **subsequent documentation-only commits:** see
  CLOSEOUT.md + terminal closeout report. Sanitizer-tested SHA is NOT
  claimed to be final branch HEAD.

Historical evidence at `21fc710e` is NOT presented as evidence for C
changes made after it; this is a fresh rerun at the final C source.

## Runs (2026-11-26, fake/local NUMA host; NOT physical-NUMA)

Compiler **gcc 16.2.1**; sanitizer runtime **libasan.so.8.0.0** +
**libubsan.so.1.0.0** (asan-ubsan); **libtsan.so.2.0.0** (tsan);
runtime discovered; artifact instrumentation verified; LD_PRELOAD actual.

| Sanitizer | mode | source SHA | tests | findings | test RC | artifact unchanged | result |
|---|---|---|---|---|---|---|---|
| ASan+UBSan | full suite | `3f4f3f89` | **Ran 340 tests** | **0** | 0 | yes (SHA-256) | PASS_OK |
| TSan | full suite | `3f4f3f89` | **Ran 340 tests** | **0** | 0 | yes (SHA-256) | PASS_OK |

Flags: ASan+UBSan `-O1 -g -fno-omit-frame-pointer -fPIC -fsanitize=address,undefined`
+ `-shared -pthread -fsanitize=address,undefined`; ASan `halt_on_error=1`;
UBSan `halt_on_error=1` + print_stacktrace; TSan `-fsanitize=thread`
+ `halt_on_error=1`. make clean rc=0; sanitizer build rc=0.
Instrumentation symbol: `__asan_init` / `__tsan_init` (nm -D).

Artifacts (retained): `sanitizer_evidence/asan-ubsan/` + `sanitizer_evidence/tsan/`
(result.json + full run.log + make_clean.log + sanitizer_build.log + LSan log).

## LeakSanitizer honesty (CK-3.3)
- **Full python suite LSan NOT validated**: main suite runs
  `ASAN_OPTIONS=detect_leaks=0` (python-runtime noise); recorded. **No
  claim** that the suite includes successful leak checking; lack of
  findings is not proof of no leaks.
- **Separate standalone engine LSan smoke attempted** (no python
  runtime): `detect_leaks=1`, engine create→run→destroy;
  `lsan_enabled=true`, `lsan_effective=true`, `lsan_findings=0`.
  Recorded as effective; **not** claimed as proof of no leaks.
  See `sanitizer_evidence/asan-ubsan/lsan_smoke.log`.
- **TSan**: actual TSan runtime verified + instrumentation `__tsan_init`;
  no `WARNING: ThreadSanitizer`; not physical-NUMA.
- ASan/UBSan settings make undefined-behavior diagnostics fail; findings
  counted; harness returns nonzero on REVIEW_REQUIRED.

## Historical (not current evidence)
Prior evidence at `21fc710e` (276 tests, detect_leaks=0) and earlier
are historical; superseded by this fresh rerun at `3f4f3f89`.
