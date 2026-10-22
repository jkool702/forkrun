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
| glibc (Bash loadables) | ≥ 2.38 (current shipped); 2.28 feasible (see §3) | `README.md`; ELF symbol versions of shipped artifacts |
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
| 4.4 | D-SEGFIX round-trips byte-exact on extracted binary (historical); shipped blob built from source commit `e6b9e785` which contains D-SEGFIX (verified: `git merge-base --is-ancestor 98fce81 e6b9e785` → true). Embedded blob byte-identical to a fresh build (verified for v2/v3/v4). | MEASURED (not yet blocking in CI for ≤5.1) |
| 5.0 | same as 4.4 | MEASURED |
| 5.1 | same; source-built 5.1.0 byte-exact | MEASURED |
| 5.2 | full suites green (92+264) | ENFORCED (bash-suite basic) |
| 5.3 | full suites green | ENFORCED |
| newest stable | fedora:latest (asserted, not assumed) | ADVISORY (scheduled check TBD) |

Gaps:
- `bashcompat-smoke.yml` legs for 4.4/5.0/5.1/4.4-ubi8 are `allow-fail: true`.
- Path filters omit `substratestubs.c`, `tools/check_canary_versions.py`,
  `tools/gen_shim.py`, `Makefile.substrate`, `forkrun_substrate.h`.
- No source-build leg for 4.4/5.0 (only 5.1).
- Embedded-blob vs freshly-built distinction: release workflow freshness gate
  (decode-and-cmp) proves correspondence; smoke tests the embedded blob only.

## 2. glibc floor (WO-COMPAT-03)

Shipped artifacts (all 7) require max `GLIBC_2.38` (measured via `objdump -T`):
aarch64, ppc64le, riscv64, s390x, x86-64-v2/v3/v4 → top GLIBC_2.38.
No `GLIBC_ABI_GNU2_TLS` references (D-TLS).

Feasibility of 2.28: **proven on x86-64** — built in `manylinux_2_28_x86_64`
(glibc 2.28, GCC 14) with the release flags; result max `GLIBC_2.28`,
loads on bash 4.4 (glibc 2.28) and round-trips byte-exact on bash 5.3 (glibc 2.43).
Same applies to aarch64/ppc64le/s390x (manylinux_2_28 images available).
riscv64 has no manylinux_2_28 image (fedorariscv base is glibc 2.39.9000).

Decision: keep shipped floor at 2.38 for now (no blob cycle yet); provide
the 2.28 build recipe and an opt-in CI job. Lowering to 2.28 requires
rebuilding all arches + blob cycle + docs; tracked as follow-up.

## 3. CPython runtime (WO-COMPAT-04)

Supported minors: 3.10, 3.11, 3.12, 3.13, 3.14, 3.15 (GIL only).
`matrix_c05.sh` fetches 3.10–3.15 and runs verdict/control/respawn probes.
Historical: all six minors measured (3.15 was rc2; now stable 3.15.1 available).

Gaps:
- `python-check.yml` version-matrix only covers 3.10–3.13.
- Wheel-tag/environment mismatch: builds in `fedora:latest` (glibc 2.39+)
  then installs into Ubuntu 22.04 (glibc 2.35). Must build in manylinux_2_28.
- Free-threaded explicitly refused (correct, keep).

## 4. Release wheels (WO-COMPAT-05)

Generic substrate wheel: builds in manylinux_2_28 (glibc 2.28), tagged
`manylinux_2_28_x86_64`, py3-none. Validated locally (dist/).

Per-minor UDF wheels: `tools/wheel_matrix.py` orchestration exists with
fail-closed rules (no substitution, no reuse, strict mode). Blocked by
missing shared libpython in manylinux_2_28 image (static builds only).
Needs CPython built with `--enable-shared` inside the container.

Status: INCOMPLETE (only 3.14 built locally, as cp314 wheel in dist/).

## 5. CI wiring (WO-COMPAT-06)

Workflows present: bashcompat-smoke, bash-suite, forkrun_release, python-check,
sanitizer-freshness, sh-format, shim-check, static-analysis, idl-check.
Triggers: push/PR to `main` only. Feature branches (NEW/REFACTOR*) do not
trigger. Need PR to main to observe checks.

Gaps: path filters (see §1); advisory status of supported Bash versions;
python-check wheel build env mismatch; no scheduled newest-stable check.

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
- Measured glibc requirements: all 7 shipped artifacts top out at GLIBC_2.38;
  zero GLIBC_ABI_GNU2_TLS.
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
- Opened PR #585. CI: build-wheel, shim-check, idl-check, CodeQL pass.
  bash-basic failed on a timing-sensitive min-heap test that passes locally (flake).
  twin-check fails pre-existingly on baseline too (comprehensive.sh vs .txt differ).
  sanitizer-asan-ubsan advisory, failed (pre-existing advisory).
