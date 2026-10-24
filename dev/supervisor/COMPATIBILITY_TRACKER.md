# Compatibility Tracker (WO-COMPAT-01 … WO-COMPAT-07)

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
- Version-matrix (run 39898594446) was red for every Ubuntu cell, and
  the earlier entry misdiagnosed it. The 3.11 cell never reached the
  tests: `apt-get install python3.11` pulled tzdata and blocked on the
  interactive geographic-area prompt at 04:12:32; the job was cancelled
  44m23s later at its 45-minute timeout. The other cells reached the
  suite and aborted with exit 130 at
  `test_teardown_interrupt.py::test_a_signal_during_the_teardown_still_checkpoints`.
  The detailed FAIL blocks never appeared because unittest prints them
  at the END, which the abort prevented, so the lane's per-test failures
  were not enumerated; do not quote a count for them. The abort itself
  was a test premise that depended on CPU count: its UDF aborts after 8
  invocations, and default batching gives 25 batches on a 28-vCPU host
  but only 7 on a 4-vCPU runner. With 7 the run completes; the injected
  SIGINT is then delivered during teardown with no exception in flight
  (the documented path), and unittest re-raises KeyboardInterrupt,
  killing the run.
  Fixed in WO-COMPAT-07 (§5a): explicit `bytes=16` (106 batches) plus
  a guard that turns a broken premise into a clean test failure.
- `python-v0` was red for the same test (exit 130). It built the
  substrate and the launcher (`cleanroom launcher OK` appears in the
  log) but not the UDF helper: `udf helper library OK` never appears
  and 20 tests skipped with `udf helper / launcher not built`. Before
  the abort the log also shows **8 real FAILs**, not skips (the
  earlier "helper-dependent failures" wording was closer than a later
  "they were only skips" correction -- the truth is both):

  * `test_bench.TestHarness.test_cpu_pct_around_trivial`
  * `test_c07_e2e::test_drop_at_several_positions_is_caught` (drop=10
    needs 11 frames; a 4-vCPU runner produces fewer)
  * `test_capability_dispatch::test_map_udf_is_a_distinct_route_from_python`
  * `test_cleanroom_numa::test_a_helper_death_leaves_no_surviving_descendant`
  * `test_cleanroom_numa::test_indexer_death_aborts_the_run`
  * `test_cleanroom_routes::test_launcher_actually_executes_and_bytes_are_exact`
  * `test_packaging_v2::test_release_check_passes`
  * `test_supervision_substrate::test_registry_slots_are_reused_across_generations`

  Four have an established mechanism that WO-COMPAT-07 addresses: the
  C07 drop position (explicit `lines=1`), the two UDF-route tests (the
  helper is now built), the release gate (`release_check`'s UDF helper
  check asserts an artifact exists), and `test_cpu_pct_around_trivial`
  (a no-op is measured almost entirely as harness overhead: 300 samples
  on four CPUs gave median 84%, max 98%, against a `< 100%` assertion;
  the test now measures a 10 ms sleep instead). The other three did not
  reproduce in a full local suite on four CPUs and the aborted log has
  no tracebacks; the new run is what discriminates them. `python-v0`
  now installs `python3-devel` and builds `udf` (§5a).
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
`python-v0` and every version-matrix cell were red at
`test_teardown_interrupt.py` (exit 130); the source core had skipped
the UDF-helper tests, and the 3.11 cell never started because of the
tzdata prompt. Those are source-suite/CI status, distinct from the
wheel-acceptance claim in §4. WO-COMPAT-07 addresses them (§5a).
sanitizer-asan-ubsan advisory, red (pre-existing).

## 5a. WO-COMPAT-07 — Python CI matrix repair

**Cause of the 3.11 stall.** Not a test hang. `apt-get install
python3.11` (deadsnakes) pulled tzdata, whose postinst entered the
interactive "Please select the geographic area" prompt at 04:12:32;
the job was cancelled at 04:56:55, 44m23s later, at its 45-minute
timeout. Every version-matrix apt path now exports
`DEBIAN_FRONTEND=noninteractive` and `TZ=Etc/UTC` before `apt-get
update`, so the answer is deterministic and no maintainer script can
block on a prompt.

**version-matrix contract.** The lane runs the full source suite, not
a generic-wheel package test and not a reduced set. The tests import
the checkout's `python/forkrun`; the wheel's `libforkrun_python.so`
is copied beside it and `cmp`'d against the installed copy, so the
engine is provably the wheel artifact. Because the generic wheel
deliberately ships no UDF helper, each cell installs
`python$PYVER-dev` and builds `udf` for that interpreter (`udf` covers
the helper, the probe and the fork driver -- `udf-lib` alone leaves the
probe/fork tests skipping); the launcher is built from source
(`make -o ... cleanroom-launcher`, which dlopens the staged .so and
needs no bash headers). `test_packaging` AND `test_reproducible` are
excluded per cell: both compile the substrate and need bash headers,
which Ubuntu does not carry. They are covered by the Fedora source
cell + `release_check`. That exclusion is explicit, not a blanket
skip.

**python-v0 prerequisites.** Fedora now installs `python3-devel` and
runs `make -f Makefile.substrate python-substrate udf`, so the suite
it claims to run no longer skips `udf helper / launcher not built`.
It also marks `/src` as a safe git directory: the container runs as
root over a host-owned mount, and `release_check`'s clean-tree and
frozen-file checks shell out to git, which refuses such a repository
as "dubious ownership" -- a failure that would have looked like a
dirty tree.

**Teardown interruption.** `test_a_signal_during_the_teardown_still_checkpoints`
aborted the suite because its `_aborting` UDF raises only after 8
invocations; a 4-vCPU runner produces 7 batches for the 200-line
input, so the run completed and the injected SIGINT was delivered
with no exception in flight. That delivery is the documented
behaviour, not an implementation defect in `_signals.py`; unittest
re-raises KeyboardInterrupt, which is why the job exited 130. The
test now forces `bytes=16` (106 batches, CPU-independent) and catches
`BaseException` so a future premise break is a named failure, not a
suite abort. Verified: 10/10 module runs on `taskset -c 0-3` (14
tests each); with the `bytes=` cap suppressed (the old premise) the
test reports one clean failure and exits 1, not 130.

**Bench harness premise.** `test_cpu_pct_around_trivial` asserted
`< 100%` around `lambda: None`, but around a no-op the sample is
almost entirely the harness's own `getrusage`/`perf_counter` cost:
300 samples on four CPUs gave median 84% and max 98%, so the
assertion had about two points of headroom and a slower runner
crossed it. The test now measures `time.sleep(0.01)`, where the same
samples read 0.01–0.02%; the assertion itself is unchanged.

**Residual, not this failure.** `_DeferredInterrupt.__exit__` drains a
pending SIGINT before restoring the mask when an exception is already
propagating, but a signal that arrives in the window between the
drain and the restore is still delivered at the restore and can
replace the original exception. The window is narrow and was not the
CI cause (the run had no exception in flight). Tracked as an open
hardening item; no behaviour change was made in this work order.

**Evidence.** Local: a full suite on four CPUs (`taskset -c 0-3`)
ran 1587 tests with 1 failure and 2 skips; the failure is
`test_release_check_passes` refusing the dirty tree that this
uncommitted work created, not a code failure. Ten consecutive
`test_teardown_interrupt` module runs passed. The per-minor build
form used by the matrix (`make ... udf PYTHON=... PYCONFIG=...`)
and the launcher target (`-o <engine>.so cleanroom-launcher`, with no
engine objects present, exactly the matrix's condition) were
exercised on a clean clone. CI: pending
run (update this line with the URL and per-job result once complete).

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
- WO-COMPAT-07: made both version-matrix apt paths noninteractive
  (`DEBIAN_FRONTEND=noninteractive`, `TZ=Etc/UTC`); aligned that lane
  with the full source suite by staging and `cmp`-ing the wheel's .so
  and building the per-minor helper + launcher; added `python3-devel`
  and `udf` to `python-v0`; diagnosed the exit-130 teardown abort
  as a 4-vCPU batching premise (7 batches < 8 invocations) and made the
  test deterministic with `bytes=16` plus a clean-failure guard; made
  the bench idle-CPU test measure a sleep instead of its own overhead.
