# W-EXP-1 — Python UDF cleanroom on UMA: implementation report

**Branch:** `NEW/REFACTOR4.4`
**Start commit:** `d25203c3` (the tree this work order started on)
**Final commit:** see §9
**Primary scope:** `setup.py`, `tools/build_wheel.sh`, `tools/matrix_c05.sh`,
focused tests, documentation.

---

## 1. The headline, and it is not what the work order expected

**The work order's premise is already satisfied by the tree.** The
cleanroom UDF route exists, is wired, and is tested: the helper
(`fr_udf.c`), the worker loop (`fr_py_worker_udf_loop`), the launcher's
dynamic resolution of it, the `udf` capability, the `FORKRUN_NO_UDF`
kill switch, the environment/import contract, the eligibility kind check
and the caller/helper version barrier are all present.

So W-EXP-1 turned out to be a **verification and closure** job, with
**one real implementation gap**: the **release wheel packaging**. The
helper was built but shipped in no wheel, and the wheel's tag did not
identify the minor the helper needed. That gap is now closed, and the
interpreter-matrix gate — which was silently broken — is now green.

The full audit is in `dev/supervisor/W_EXP_1_STAGE_A_AUDIT.md`.

---

## 2. What was actually wrong, and what changed

### 2.1 The helper was in nobody's wheel

`setup.py` listed the substrate and the launcher in `package_data` and
not the helper:

```python
package_data={"forkrun": [SO_NAME, CR_NAME, "py.typed"]},
options={"bdist_wheel": {"plat_name": PLATFORM_TAG}},
```

Two consequences, and they are the same bug:

- **A wheel install silently had no UDF accelerator.** The route
  degraded to the in-process path — slower, but correct, so nothing
  failed loudly. This is the CR-FIX1-I class of bug exactly: the
  cleanroom launcher was once "listed NOWHERE" and a wheel install
  silently had no cleanroom at all.
- **The tag could not prove the minor.** `DECISION-01` §6.2.1:
  *"a wheel built from an sdist on one machine and tagged `py3-none`
  would carry a different minor than its tag claims, with nothing in the
  artifact to prove it."*

**The fix: the wheel's python tag follows the HELPER, not the running
interpreter.** The helper's extension suffix *encodes* the minor it was
compiled against (`_fr_udf.cpython-314-x86_64-linux-gnu.so` → 3.14), so
a helper built for a different minor has a different NAME and is simply
not found. That is what makes a mismatched build safe: **it cannot
produce a wheel that claims the wrong minor.**

- helper for this interpreter present → it ships, and the wheel is
  tagged `cp3XX`;
- otherwise → no helper ships and the tag stays `py3-none-<platform>`,
  so the substrate wheel remains interpreter-agnostic.

This satisfies "keep the source-only development path honest: do not
advertise a locally built helper as present in a generic ABI-independent
wheel" **by construction** — the tag is never `py3-none` while a helper
is present. A plain `_fr_udf.so` (no suffix) is deliberately **not**
shipped: its minor cannot be established from its name. The runtime
fallback in `_udf.py` still finds it in a source checkout, so the
development path keeps working; only the wheel declines to vouch for it.

### 2.2 The wheel builder rejected a per-minor tag

`tools/build_wheel.sh:143` globbed `forkrun-*-none-*.whl`, which rejects
a `cp3XX` tag outright. It now accepts either python tag, **refuses to
choose between two wheels** (an ambiguous build must not ship one of
them silently), and a new check requires the tag and the shipped helper
to agree: a `cp3XX` wheel with a mismatched helper, or a `py3` wheel
carrying one, is a lying tag and fails the build.

### 2.3 The interpreter matrix could not build a single per-minor driver

This is the finding that mattered most, because the gate was **green
while measuring nothing**.

`tools/matrix_c05.sh`'s manual gcc line was missing `-I"$ROOT"`, and
`forkrun_udf_version.h` — the build stamp the launcher and the helper
must agree on — lives at the **REPO ROOT**. Every per-minor build
failed:

```
fr_udf.c:19:10: fatal error: forkrun_udf_version.h: No such file or directory
  3.10: BUILD FAILED
  ... (all five)
```

**And the failure was invisible**, because the lifecycle sweep then
measured the **stale driver left over from a previous run** — the
October build. A matrix gate that reports numbers from a binary it did
not build is worse than no gate.

Two fixes: the include path, and the harness now **removes the old
driver before building** and the sweep **refuses to measure a driver
this run did not produce**.

---

## 3. Evidence

### 3.1 The interpreter matrix — GREEN on all six minors

`bash tools/matrix_c05.sh` → **EXIT 0**, after the harness fix:

| minor | verdict | control | respawn |
|---|---|---|---|
| 3.10 | pre-fork works, 10.19x faster | DIRTY as required (probe not vacuous) | CLEAN (no inherited interpreter state) |
| 3.11 | pre-fork works, 4.12x faster | DIRTY | CLEAN |
| 3.12 | pre-fork works, 7.36x faster | DIRTY | CLEAN |
| 3.13 | pre-fork works, 3.63x faster | DIRTY | CLEAN |
| 3.15 | pre-fork works, 10.39x faster | DIRTY | CLEAN |
| 3.14 (system) | pre-fork works, 10.18x faster | DIRTY | CLEAN |

Lifecycle curves, on **freshly built** drivers this run:

| minor | pre-fork faster on | speedup min / median / max |
|---|---|---|
| 3.10 | 48/48 configurations | 1.23x / 2.94x / 8.00x |
| 3.11 | 48/48 | 1.22x / 2.84x / 10.00x |
| 3.12 | 48/48 | 1.33x / 3.38x / 9.08x |
| 3.13 | 48/48 | 1.31x / 3.28x / 8.25x |
| 3.15 | 48/48 | 1.18x / 3.59x / 9.70x |

**240/240 configurations across the five fetched minors**, plus the system
3.14 — which is the roadmap's "pre-fork wins on 48/48 (56/56 on 3.14)
configurations of EVERY minor", reproduced on this host.

### 3.2 The packaging

```
$ python3 setup.py bdist_wheel -d /tmp/wheeltest
forkrun-0.17.0-cp314-none-manylinux_2_39_x86_64.whl
  helper inside : forkrun/_fr_udf.cpython-314-x86_64-linux-gnu.so

$ pip install --no-deps --target /tmp/instest <wheel>
$ PYTHONPATH=/tmp/instest python3 -c "from forkrun._bindings import v1_available; print(v1_available()['udf'])"
True
```

The capability is **True from the installed package** — which is the
whole point: before this change, a wheel install had no UDF accelerator
at all.

### 3.3 Tests

| command | result |
|---|---|
| `cd python/tests && python3 -m unittest test_udf_packaging test_udf_mode test_udf_helper test_udf_version_barrier test_udf_exactly_once test_udf_stream_liveness test_no_udf_switch test_class_payload_refusal` | **100 tests, OK (1 skipped)** |
| `python3 tools/capability_matrix.py --check` | **OK: 40320 cells, matrix is current** |
| `python3 tools/gen_docs_all.py --check` | **DOCS_ALL.md is current (17 documents)** |
| `bash tools/matrix_c05.sh` | **EXIT 0, green on six minors** |
| full suite + release gate | see §8 |

The new module `python/tests/test_udf_packaging.py` (6 tests) pins the
RULE directly — detection of this interpreter's helper, refusal of
another minor's, refusal of the plain-named one, and the tag/contents
coupling — without needing a second interpreter or building a wheel.

---

## 4. Deviations from the work order, and why

| the work order says | what is true | justification |
|---|---|---|
| "extend the existing launcher to support eligible Python UDF workloads" | it already did | the route, helper, capability, kill switch, environment contract, eligibility check and version barrier were all present before this work. The audit lists the evidence per contract. |
| "the roadmap specifies a `--caller-minor=3.X` argument" | the implemented and REVIEWED name is `--caller-version=MAJOR.MINOR` | `REVIEW_REQUEST_ROUND12.md` records it as a new REQUIRED launcher argument; `ROUND13.md` records that the requirement was added as a condition of approval. The implementation under review is authoritative over the roadmap's illustrative prose, so the PROSE was corrected, not the code. |
| "run the supported interpreter matrix" | the matrix harness could not build a driver | fixed: a missing `-I"$ROOT"`, and a stale-artifact path that let the gate report October's numbers as fresh. |

---

## 5. What was NOT done, and why

- **The per-minor RELEASE build is a CI-pipeline item.** Producing one
  `cp3XX` wheel per minor means one interpreter per wheel in the release
  container. `tools/build_wheel.sh` now *handles* the tag and *checks*
  the helper against it, but the per-minor build matrix itself needs a
  container image per minor, and this box has neither Docker nor the
  manylinux images. The tag logic is verified by a real local build
  (§3.2); the matrix is not.
- **The `auditwheel` verdict is still UNVERIFIED.** `auditwheel` and
  `patchelf` are not installed here, so "what `auditwheel repair` does to
  a CPython-linked helper" remains open — exactly as `DECISION-01`
  §6.2.1 left it. The two checks that CAN be run without it were run
  and are recorded there: `DT_NEEDED` requests the intended minor
  (with a negative control), and the artifact carries no
  `RPATH`/`RUNPATH` at all.
- **The C-drain path was not touched.** It is a different work order.
- **No default-on decision was implemented.** See §8.

---

## 6. Remaining gaps

1. The per-minor release build (§5).
2. The `auditwheel` verdict (§5).
3. The **closure evidence** this work order asks for — the differential
   correctness of the UDF route against the in-process path, the
   return-value contract (`None`/`b""`/`bytes`/`bytearray`/`memoryview`/
   `str`/invalid), the import-failure-vs-batch-exception distinction,
   the bounded import hang, the import-time-threading check, and the
   worker-death/respawn/poison/abandonment matrix — is **already in the
   tree** (`test_udf_helper.py`, `test_udf_mode.py`,
   `test_udf_version_barrier.py`, `test_udf_exactly_once.py`,
   `test_udf_stream_liveness.py`, `test_class_payload_refusal.py`) and
   was re-run green in §3.3. It is reported here rather than
   re-authored, because re-authoring a passing suite to look like new
   work would be the dishonest version of "closure".
4. The **crossover** publication is `C0.6_M2_MEASUREMENT.md`
   §"Crossover statement", and the per-minor lifecycle curves in §3.1
   refresh it.

---

## 7. The recommendation (deliberately UNCOMMITTED)

**The UDF envelope is ready for its own default-on review, but this
work order does not make that decision, and the recommendation is not
committed** (the work order says: *"a proposed default-on decision as a
separate, uncommitted recommendation"*).

What the evidence supports:

- The route is **correct**: 100 focused tests green, capability
  reported honestly from an installed package, the version barrier
  refusing a mismatch before any source bytes are consumed.
- The lifecycle is **measured and wins**: 240/240 configurations across
  five minors, plus the system 3.14, pre-fork faster with medians
  2.84x-3.59x.
- The packaging is **honest**: a `cp3XX` wheel carries the helper and
  proves the minor; a generic wheel carries none.

What it does **not** support, and must not be papered over:

- **The memory story is mixed and was measured**: pre-fork is *worse* on
  memory at 1-2 workers (+39%, +7.5% at parent 0 MB), crosses over
  near 3 workers, and is better from there (-46% at 16 workers). A
  default-on decision should name the worker count it assumes.
- **No physical NUMA.** This is a UMA envelope only.
- **The release build and the `auditwheel` gate are unverified here.**
  A default-on decision is a release decision, and it should wait for
  a per-minor wheel that has actually been through `auditwheel`.

So: **the route is ready to be REVIEWED for default-on; it is not ready
to BE default-on.** The two release gates above are the difference, and
neither is a code problem.

---

## 8. Gates

On the final commit (`c40fa29f`):

| gate | result |
|---|---|
| `python3 -m unittest discover -s python/tests` | **1437 tests, OK (2 skipped)** |
| `python3 python/release_check.py gate` | **ALL CHECKS PASSED — ready to tag v3.6.1** (23 PASS / 0 FAIL / 1 SKIP: the tag check, which needs `FORKRUN_RELEASE_CHECK_TAGS=1`) |
| focused UDF modules (§3.3) | **100 tests, OK (1 skipped)** |
| `python3 tools/capability_matrix.py --check` | **OK: 40320 cells, matrix is current** |
| `python3 tools/gen_docs_all.py --check` | **DOCS_ALL.md is current (17 documents)** |
| `bash tools/matrix_c05.sh` | **EXIT 0 — green on six minors** |
| frozen files | empty diff; their last-touching commit is not HEAD |

The gate's own `UDF helper: no test-only version override in the
shipped artifact` check is the one that would have caught a helper
built with a test-only version stamp; it passes.

## 9. Commits, changed files, and the final state

| file | change |
|---|---|
| `setup.py` | detect the helper for this interpreter; ship it in `package_data`; set `bdist_wheel`'s `python_tag` to `cp3XX` when it ships |
| `tools/build_wheel.sh` | accept a `cp3XX` tag; refuse ambiguity; check the tag against the shipped helper |
| `tools/matrix_c05.sh` | `-I"$ROOT"` (the missing build stamp); remove the stale driver before building; measure only a driver this run produced |
| `python/tests/test_udf_packaging.py` | **new** — 6 tests pinning the tag rule |
| `dev/supervisor/W_EXP_1_STAGE_A_AUDIT.md` | **new** — the Stage A audit |
| `dev/supervisor/CLEANROOM_EXPANSION_ROADMAP.md` | the argument's NAME corrected to the reviewed `--caller-version` |
| `python/docs/INSTALLATION.md` | the optional helper, its build, and the per-minor wheel constraint |
| `DOCS/CHANGELOG.md` (+ regenerated `DOCS/DOCS_ALL.md`) | the packaging entry |

**Frozen files untouched:** `forkrun_ring.c`, `forkrun_substrate.h`,
`substratestubs.c` — empty diff, and their last-touching commit is not
HEAD. `frun.bash` untouched. The substrate's `DT_NEEDED` is unchanged: the
helper is a separate object and the substrate stays free of `libpython`.
