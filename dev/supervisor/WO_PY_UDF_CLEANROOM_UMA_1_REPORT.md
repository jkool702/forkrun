# W-EXP-1 — Python UDF cleanroom on UMA: implementation report

**Branch:** `NEW/REFACTOR4.4`
**Start commit:** `d25203c3` (the tree this work order started on)
**Final commit:** `c41d132a`
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
  tagged `cp3XX-cp3XX` (version AND ABI — see §2.1a);
- otherwise → no helper ships and the tag stays `py3-none-<platform>`,
  so the substrate wheel remains interpreter-agnostic.

This satisfies "keep the source-only development path honest: do not
advertise a locally built helper as present in a generic ABI-independent
wheel" **by construction** — the tag is never `py3-none` while a helper
is present. A plain `_fr_udf.so` (no suffix) is deliberately **not**
shipped: its minor cannot be established from its name. The runtime
fallback in `_udf.py` still finds it in a source checkout, so the
development path keeps working; only the wheel declines to vouch for it.

### 2.1a The ABI tag: `cp314` does not mean what it looks like

A follow-up review found a real gap in the packaging above, and it is
worth recording because the gap was in the part the first change got
*most* right.

The python tag `cp314` names a **version**; the **ABI** tag names the
ABI. A free-threaded CPython 3.14 links `libpython3.14t.so.1.0` where a
GIL one links `libpython3.14.so.1.0` — different sonames, so the helper
built for one cannot be loaded by the other. And the free-threaded
extension suffix is `cpython-314t-...`, which **contains** the GIL
suffix's `cpython-314` — so a substring check on the minor alone
accepts a free-threaded helper.

Meanwhile the loose ABI tag `none` means "no ABI constraint", and
`packaging`'s own tag generator (not a filename convention) gives a
free-threaded 3.14 this set:

```
cp314-cp314t, cp314-abi3t, cp314-none, cp313-abi3t, ... cp39-abi3t
```

So `cp314-none` is accepted by a free-threaded 3.14 **and** by a GIL 3.14:
a GIL-built helper in a `none`-ABI wheel advertises compatibility with an
interpreter that cannot load it. The first change shipped exactly that
(`cp314-none-...`).

**The decision: free-threaded CPython is NOT supported for this helper
route**, and the packaging declines to claim it. The reasons are
structural rather than caution: the helper links a different
`libpython` soname; the C0.5 matrix fetches GIL interpreters only; and
the launcher has never been exercised against a free-threaded build.
Shipping it would be shipping an UNMEASURED configuration.

**The fix:**

- the detector refuses a free-threaded helper (two independent
  signals: `Py_GIL_DISABLED` in the build config, and the `t` in the
  extension suffix), so such a build ships no helper and keeps the
  generic `py3-none` tag;
- the wheel carries the **real** ABI tag — `cp314-cp314` for the GIL
  build — so its compatibility set is exactly the interpreters that can
  load the helper. `cp314-cp314` is accepted by a GIL 3.14 and
  **rejected** by a free-threaded 3.14; the old `cp314-none` was
  accepted by both;
- the build check refuses a helper-carrying wheel whose ABI tag is
  `none`, and refuses a python/ABI tag disagreement.

If free-threaded is supported later, the tag becomes `cp314-cp314t` —
accepted by the free-threaded interpreter and not by the GIL one. The
two directions are distinguishable, so the current position is a
**policy**, not a limitation of the tagging.

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
forkrun-0.17.0-cp314-cp314-manylinux_2_39_x86_64.whl
  helper inside : forkrun/_fr_udf.cpython-314-x86_64-linux-gnu.so

  the tag, against packaging's REAL compatible sets:
    cp314-cp314  accepted by a GIL 3.14       : True
    cp314-cp314  accepted by a free-threaded  : False
    cp314-none   accepted by a free-threaded  : True   <- the old tag

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

### 4a. The packaging tests, and the ABI half of the contract

**A follow-up review found one more inconsistency, and it was in the
policy rather than the code.** The packaging declined a free-threaded
helper, but the RUNTIME would still have discovered and used one: the
version barrier compares only `major.minor` (the build stamp carries no
free-threading bit), so the two flavours of the same minor are
indistinguishable to it. "Not supported" was therefore a packaging
statement, not a fact.

It is now a fact, and the policy lives in ONE place:
`forkrun/_udf.py` gained `freethreaded_interpreter()`, and the runtime
refuses a free-threaded interpreter's helper. `setup.py` asks the
runtime's answer by loading that module by path (it has no relative
imports, so no package import is needed), rather than keeping a second
copy of the rule. A test asserts the two layers AGREE.

The consequence is that on a free-threaded interpreter the capability
reports False, the launcher is never handed a helper to load, and the
route degrades to the in-process path.

`python/tests/test_udf_packaging.py` now has **14 tests**, and they
exercise the values `setup.py` ACTUALLY computes — the loader executes
setup.py's real module-level code with `setup()` stubbed out, so the
tag under test is the real one rather than a re-implementation of the
rule.

The ABI assertions are made against **real `packaging.tags` compatible
sets**, not against filename strings, because the filename is only how
the tag is WRITTEN — pip consults the tag set:

- the shipped tag is in THIS interpreter's compatible set (otherwise pip
  would refuse the wheel it just built);
- the shipped tag is **not** in a free-threaded interpreter's set;
- a free-threaded helper is refused by the detector;
- `cp314-cp314t` and `cp314-cp314` are mutually exclusive across the two
  interpreters, so the current "not supported yet" position is a policy
  and not a limitation of the tagging;
- the packaging's behaviour on a **simulated free-threaded build** (the
  build config and the extension suffix are both rewritten, so the
  detection sees what it would see on a real one): no helper, no
  per-minor tag, no ABI tag;
- the runtime declines a free-threaded interpreter, and the packaging and
  the runtime agree about it.

**Mutation check:** reverting the ABI tag to `none` — the exact bug the
review found — fails **2** of the 10 tests. The tests are not vacuous.

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
| `python3 -m unittest discover -s python/tests` | **1445 tests, OK (2 skipped)** |
| `python3 python/release_check.py gate` | **ALL CHECKS PASSED — ready to tag v3.6.1** (23 PASS / 0 FAIL / 1 SKIP: the tag check, which needs `FORKRUN_RELEASE_CHECK_TAGS=1`) |
| focused UDF modules (§3.3) | **108 tests, OK (1 skipped)** |
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
