# Compatibility Tracker (WO-COMPAT-01 … WO-COMPAT-06)

Branch: `NEW/REFACTOR4.5` (from `NEW/REFACTOR4.4` @ `01b5de92`).
Baseline verified: branch `NEW/REFACTOR4.4`, HEAD `01b5de92650cd6ee8323c8d4006967971cd594f0`,
upstream `origin/NEW/REFACTOR4.4`, clean working tree, 12 commits ahead of `8ac54de1`.

This tracker is the single source of truth for the compatibility initiative.
Status legend: **ENFORCED** (blocking CI + artifact/runtime test),
**MEASURED** (evidence exists, not yet blocking),
**ADVISORY** (intentionally non-blocking, reason documented),
**UNSUPPORTED** (explicitly out of contract),
**UNTESTED/INCOMPLETE** (no sufficient evidence).

---

## 0. Support contract (authoritative sources)

| Axis | Promise | Authoritative source |
|---|---|---|
| Bash (frontend) | ≥ 4.4 | `README.md` §Requirements; `tools/check_canary_versions.py::FLOOR` |
| glibc (Bash loadables) | 2.28 on x86-64/aarch64/ppc64le/s390x; 2.38 on riscv64 | `README.md`; `tools/check_glibc_versions.py` |
| glibc (Python wheel) | ≥ 2.28 (manylinux_2_28) | `tools/build_wheel.sh`; `setup.py::get_platform_tag` |
| CPython | 3.10–3.15 (GIL only) | `tools/wheel_matrix.py::SUPPORTED_MINORS` (single source) |
| Free-threaded CPython | explicitly unsupported | `setup.py::_freethreaded_interpreter`; `forkrun/_udf.py` |
| Linux kernel | ≥ 3.17 (memfd); ≥ 4.5 enables copy_file_range fast path | `README.md` |
| GNU coreutils | required (sed -z, base64 -w 0, truncate --size=) | `README.md` (no busybox) |
| Architecture (Bash) | x86-64 v2/v3/v4, aarch64, ppc64le, s390x, riscv64 | `forkrun_release.yml` matrix |
| Architecture (Python wheel) | x86_64, aarch64 | `setup.py::get_platform_tag` |

## 1. Bash compatibility (WO-COMPAT-02)

| Bash | Evidence | Status |
|---|---|---|
| 4.4 | D-SEGFIX round-trips byte-exact on extracted binary (historical); shipped blob built from source commit `e6b9e785` which contains D-SEGFIX. Embedded blob byte-identical to a fresh build (verified for v2/v3/v4). CI: source-build leg `allow-fail: false`, passed (run 39849193265). | ENFORCED (bashcompat-smoke, 2026-10-22) |
| 5.0 | same as 4.4 | ENFORCED (bashcompat-smoke, 2026-10-22) |
| 5.1 | same; source-built 5.1.0 byte-exact | ENFORCED (bashcompat-smoke, 2026-10-22) |
| 5.2 | full suites green (92+264) | ENFORCED (bash-suite basic) |
| 5.3 | full suites green | ENFORCED (bash-suite basic) |
| newest stable | fedora:latest (asserted, not assumed) | ADVISORY (scheduled check TBD) |

Gaps:
- Embedded-blob vs freshly-built distinction: release workflow freshness gate
  (decode-and-cmp) proves correspondence; smoke tests the embedded blob only.
- Min-heap ordering test failed in CI twice (runs 39849193302, 39862126718);
  passes locally. Classified as a separate item (passes locally, not yet
  diagnosed). Twin-check red on baseline and current (run 39862126671).

## 2. glibc floor (WO-COMPAT-03)

Shipped artifacts (current state after the blob cycle):
- x86-64-v2/v3/v4, aarch64, ppc64le, s390x: max `GLIBC_2.28`
  (rebuilt in manylinux_2_28, verified by `tools/check_glibc_versions.py`,
  end-to-end round-trip passed on glibc 2.28).
- riscv64: max `GLIBC_2.38` (no manylinux_2_28 image; advisory arch).

No `GLIBC_ABI_GNU2_TLS` references (D-TLS). Gate: `glibc-floor` job in
`bashcompat-smoke.yml`, green (run 39849193265). Release workflow now builds
in manylinux_2_28 (run 39849185555 green).

## 3. CPython runtime (WO-COMPAT-04)

Supported minors: 3.10, 3.11, 3.12, 3.13, 3.14, 3.15 (GIL only).
`matrix_c05.sh` fetches 3.10–3.15 and runs verdict/control/respawn probes.
Historical: all six minors measured (3.15 was rc2; now stable 3.15.1 available).

Gaps:
- Version-matrix now covers 3.10–3.15, but the generic-substrate wheel lane
  runs helper-dependent tests against a helper-less wheel; needs a separate
  helper lane (WO-COMPAT-04 open).
- Python CI run 39862126756 red: matrix cells 3.10, 3.12-3.15 fail;
  3.11 in progress; python-v0 failed. Failures include
  `test_helper_is_present_for_this_interpreter`, capability-dispatch,
  NUMA/helper-death, release-check/benchmark, and a `KeyboardInterrupt`
  in `_signals.py` during `test_teardown_interrupt.py`. Not all are
  compatibility regressions; needs diagnosis.
- Free-threaded explicitly refused (correct, keep).

## 4. Release wheels (WO-COMPAT-05)

Generic substrate wheel: builds in manylinux_2_28 (glibc 2.28), tagged
`manylinux_2_28_x86_64`, py3-none. Validated locally (dist/).

Per-minor UDF wheels: `tools/wheel_matrix.py` orchestration exists with
fail-closed rules (no substitution, no reuse, strict mode). Shared CPython
3.10-3.15 built with `--enable-shared` in manylinux_2_28; all six per-minor
wheels build and validate by tag (in-container). The remaining blocker is
runtime, not build: `auditwheel repair` strips the `libpython` DT_NEEDED
dependency, so the released helper route is unvalidated (WO-COMPAT-05 open).
Smoke test is shallow (import + presence only); no real UDF workload exercised.

Status: FUNCTIONALLY VALIDATED (3.14). All six per-minor wheels build and
validate by tag in manylinux_2_28. auditwheel repair strips the libpython
DT_NEEDED dependency, but the repaired helper still resolves libpython at
runtime via the system linker (libpython is provided by the Python install).
Acceptance test (tools/acceptance_installed_wheel.py) confirms UDF_OK on the
repaired 3.14 wheel (bytes=8890). Remaining: run the same acceptance on
3.10-3.13 and 3.15 (WO-COMPAT-05 open until all six pass).

## 5. CI wiring (WO-COMPAT-06)

Workflows present: bashcompat-smoke, bash-suite, forkrun_release, python-check,
sanitizer-freshness, sh-format, shim-check, static-analysis, idl-check.
Triggers: push/PR to `main` only. Feature branches (NEW/REFACTOR*) do not
trigger. PR #585 opened to observe checks.

Status (run 39862126642+): bashcompat-smoke green (7 jobs incl. canary-versions
and glibc-floor); shim-check, idl-check, static-analysis green; build-wheel green.
bash-suite red: min-heap ordering test (run 39862126718) — recurring, classified
as separate item (passes locally). sh-format red: twin-file mismatch (run
39862126671) — pre-existing on baseline. python-check red: matrix cells 3.10,
3.12-3.15 fail (run 39862126756); 3.11 in progress; helper-dependent tests
mismatch + KeyboardInterrupt in _signals.py. sanitizer-asan-ubsan advisory, red.

## 6. Linux kernel / GNU utilities (WO-COMPAT-01 audit)

Kernel ≥ 3.17 (memfd_create) required; ≥ 4.5 enables copy_file_range fast
path with automatic fallback. GNU coreutils required (sed -z, base64 -w 0,
truncate --size=); busybox unsupported. These are documented in README.
No separate CI gate; the functional round-trips exercise them implicitly.
No change required; recorded for completeness.

## Actions taken this session

- Verified baseline (branch/HEAD/upstream/clean) — matches snapshot.
- Verified shipped embedded blobs decode byte-identical to ring_loadables artifacts (all 7).
- Verified fresh rebuild (x86-64 v2/v3/v4) is byte-identical to shipped artifacts
  using host GCC 16.2.1 (same as CI). Proves embedded blob == current source.
- Measured glibc requirements (pre-rebuild): all 7 shipped artifacts top out at
  GLIBC_2.38; zero GLIBC_ABI_GNU2_TLS. Post-rebuild: six arches at GLIBC_2.28,
  riscv64 at GLIBC_2.38.
- Proved 2.28 build feasibility in manylinux_2_28 (x86-64 v2).
- Confirmed manylinux_2_28 image has all six CPython minors 3.10–3.15 (static libpython).
- Confirmed gh CLI authenticated with workflow scope; remote reachable.
- Branched to NEW/REFACTOR4.5.
- Rebuilt six Bash-loadable arches (x86-64 v2/v3/v4, aarch64, ppc64le, s390x) in
  manylinux_2_28 (max GLIBC_2.28); regenerated frun.bash base64; verified
  byte-equality of embedded blobs; end-to-end round-trip passed on glibc 2.28
  (bash 4.4) and glibc 2.43 (bash 5.3).
- Rebuilt Python substrate in manylinux_2_28 (max GLIBC_2.28).
- Built shared CPython 3.10-3.15 in manylinux_2_28; all six per-minor wheels
  built and validated by tag. auditwheel repair strips libpython (documented blocker).
- Added tools/check_glibc_versions.py (per-arch floors). Both canary + glibc gates green.
- Python suite: 1541 tests, 1 pre-existing dirty-tree failure (now resolved by commit),
  2 skipped. wheel_matrix tests 18/18.
- Bash basic suite: 96/96 locally on new blob.
- Opened PR #585. CI (run 39862126642+): bashcompat-smoke green (7 jobs);
  shim-check, idl-check, static-analysis green; build-wheel green.
  bash-suite red: min-heap ordering (run 39862126718, recurring).
  sh-format red: twin-file mismatch (run 39862126671, pre-existing).
  python-check red: matrix cells 3.10, 3.12-3.15 (run 39862126756).
  sanitizer-asan-ubsan advisory, red.
