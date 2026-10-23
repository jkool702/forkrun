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
- Version-matrix (run 39898594446) remains red for 3.10 and 3.12-3.15;
  3.11 was still in progress when this entry was written. Documented
  cause: that lane installs the GENERIC wheel, which carries no per-minor
  helper, so helper-dependent tests fail there. The per-minor helper lane
  now exists as the UDF acceptance lane (§4); version-matrix still
  installs the generic wheel only. Tracked separately, NOT part of the
  acceptance claim.
- `python-v0` in the same run is red as well: that job builds the
  substrate but not the per-minor UDF helper, so the source-tree suite
  reports helper-dependent (and some environment-sensitive cleanroom/bench)
  failures, then the known pre-existing `KeyboardInterrupt` inside
  `_signals.py` during `test_teardown_interrupt.py` aborts the run
  (exit 130). The same suite passes locally from `python/` with the
  helper built (1587 tests, OK, 2 skipped); not caused by the acceptance
  changes.
- Free-threaded explicitly refused (correct, keep).

## 4. Release wheels (WO-COMPAT-05)

Generic substrate wheel: builds in manylinux_2_28 (glibc 2.28), tagged
`manylinux_2_28_x86_64`, py3-none. Installed and exercised on all six
minors by the generic-acceptance lane below.

Per-minor UDF wheels: `tools/wheel_matrix.py` orchestration exists with
fail-closed rules (no substitution, no reuse, strict mode). Each UDF cell
source-builds the pinned shared CPython, builds the per-minor helper and
the launcher, builds an intermediate `linux_x86_64` wheel, and lets
`auditwheel repair` set the manylinux floor. `auditwheel` strips the
helper's libpython DT_NEEDED; the launcher loads the caller's libpython
and the helper resolves its symbols through it.

Status: **ENFORCED** (2026-10-23, CI run
[39898594446](https://github.com/jkool702/forkrun/actions/runs/39898594446),
PR #585, SHA `2b5f62f0`). Both lanes pass on every supported minor:

| lane | 3.10 | 3.11 | 3.12 | 3.13 | 3.14 | 3.15 |
|---|---|---|---|---|---|---|
| generic wheel, installed, real `map()` | PASS | PASS | PASS | PASS | PASS | PASS |
| per-minor UDF wheel, installed, real UDF | PASS | PASS | PASS | PASS | PASS | PASS |

Per-cell UDF evidence (from each job's JSON report):
- Pinned shared CPython actually run: 3.10.22, 3.11.17, 3.12.15,
  3.13.17, 3.14.9, 3.15.1.
- Repaired wheel: `forkrun-0.17.0-cpXXX-cpXXX-manylinux_2_28_x86_64.whl`;
  `wheel_matrix --validate-wheel` agrees with the tag for all six.
- Every cell: `isolated=True`, two helper PIDs distinct from the
  driver's PID, 40 UDF invocations, byte-exact 38,890-byte output.
- Provenance: every required installed file is SHA-256-identical to its
  wheel member, and the installed helper suffix equals the interpreter's
  `EXT_SUFFIX`.

Loader-path note: `tools/ci_udf_acceptance.sh::build_cpython` exports
`$PREFIX/lib` BEFORE the first execution of the freshly built shared
interpreter. The pre-fix run (39896998145) failed 5/6 cells with
`libpython3.X.so.1.0: cannot open shared object file` because validation
ran before `run_one` set the path. Validation also reads
`/proc/self/maps` and requires the mapped libpython to be the prefix's
own file, so a same-soname library elsewhere cannot produce a pass.

Negative coverage (65 tests, all passing locally):
`python/tests/test_acceptance_harness.py` (42),
`test_cleanroom_libpython.py` (4), `test_udf_version_barrier.py` (19)
cover missing `--udf-func`, wrong minor/interpreter, malformed/missing
wheel, wrong wheel contents (helper absent, wrong suffix, wrong ABI,
path escape), provenance mismatch, hostile env (`FR_UDF_HOME`,
`FORKRUN_*`, `PYTHON*`, `LD_PRELOAD`, `LD_AUDIT`), unresolved libpython,
and a false UDF-route success (same PID, non-isolated, stale nonce,
missing marker, self-reported PID).

Local evidence (no Docker; host Python 3.14.7):
- Fresh shared CPython 3.14.9 at a non-system prefix: interpreter
  validation, helper, substrate/launcher and raw wheel built; stopped
  only at `auditwheel repair` because the host glibc is newer than any
  manylinux tag (CI performs this step in manylinux_2_28).
- With the prefix loader path validation passes; without it the same
  interpreter starts on `/usr/lib64/libpython3.14.so.1.0` (3.14.7) and
  the maps assertion rejects it.
- Hostile `FR_UDF_HOME=/nonexistent`: removed in `env_audit`, UDF run
  still isolated and byte-exact.
- Full suite: 1587 tests, OK, 2 skipped.

## 5. CI wiring (WO-COMPAT-06)

Workflows present: bashcompat-smoke, bash-suite, forkrun_release, python-check,
sanitizer-freshness, sh-format, shim-check, static-analysis, idl-check.
Triggers: `python-check.yml` runs on pushes to `main` and on pull requests
whose BASE is `main`, filtered by paths (the acceptance-critical tools are
listed in both filters); `workflow_dispatch` is also present. Feature-branch
pushes alone do not match the `push` filter, but PR #585 (base `main`) runs
the workflow on every branch update.

Status (run 39898594446, SHA `2b5f62f0`): build-wheel, six
generic-acceptance and six udf-acceptance cells green; see §4.
`python-v0` red: helper-less source-tree suite failures plus the known
`KeyboardInterrupt` in `_signals.py` during `test_teardown_interrupt.py`
(exit 130). version-matrix 3.10 and 3.12-3.15 red; 3.11 still in
progress (§3). sanitizer-asan-ubsan advisory, red (pre-existing).

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
  built and validated by tag. `auditwheel` strips the helper's DT_NEEDED
  libpython; the launcher supplies it at runtime (now exercised by the UDF lane).
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
- Acceptance work (commits ab244841..2b5f62f0): rewrote
  `tools/acceptance_installed_wheel.py` with `--expect-minor`, wheel
  tag/member/METADATA inspection, SHA-256 provenance, a sanitized child
  environment, and nonce/PID/version markers; rewrote its 42 negative
  tests; added the libpython-refusal tests (4) and the launcher version
  barrier tests (19).
- Fixed the UDF lane's loader-path ordering and added the
  `/proc/self/maps` proof; dropped `FR_UDF_HOME` from the acceptance
  child env (commit `2b5f62f0`).
- Evidence (run 39898594446): six generic + six UDF cells green, with
  pinned patches and per-cell facts in §4. Local full suite: 1587 tests,
  OK, 2 skipped.
