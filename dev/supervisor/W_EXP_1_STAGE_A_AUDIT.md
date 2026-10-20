# W-EXP-1 — Stage A: audit and contract reconciliation

**Branch:** `NEW/REFACTOR4.4`
**Baseline at the start of this work order:** `31d7d555`
**Status:** audit complete; the implementation is largely present; the
remaining gap is the release packaging.

---

## 1. The headline finding

**The work order's premise — "extend the existing Python cleanroom
launcher to support eligible Python UDF workloads" — is already
substantially satisfied by the tree.** The route, the helper, the
capability, the kill switch, the environment contract, the eligibility
contract and the version barrier are all implemented and tested. W-EXP-1
is therefore mostly a **verification and closure** job, not a build.

The single genuinely missing piece is the **release packaging**: the
helper is built but **not shipped in any wheel**, and the wheel is
tagged `py3-none-<platform>` even when it carries (or could carry) a
CPython-LINKED helper. That is exactly the hazard `DECISION-01` §6.2.1
warns about, and it is the work to do.

---

## 2. Contract reconciliation

| contract | where it is recorded | state in the tree |
|---|---|---|
| **Eligibility** (C0.3) | roadmap §5.2 / C0.3 | **present.** `mode="udf"` accepts only a `"module:attribute"` string (`_udf.parse_spec`), so a lambda, closure or bound method is structurally declined. The shared resolver's `callable()` check admits a class, so `_worker.py` adds an explicit `inspect.isclass` kind check that raises before input is consumed. |
| **Three categories** (C0.3) | roadmap §5.2 | **present.** Category 1 is detected and declined; category 2 is a documented caller obligation (not detectable); category 3 is the parity-fixture set. |
| **Environment / import contract** (Design A §5.4) | roadmap §5.4, `DECISION-01` §6.1 | **present.** `fr_udf.c` uses `PyConfig_InitIsolatedConfig`, `isolated=1`, `use_environment=0`, `site_import=0`, `safe_path=1`, and sets `home`/`program_name` through `PyConfig_SetString` (the literal-pointer trap is documented in the source). `test_udf_helper.py` (46 tests) covers the isolation, the caller's roots, the hostile `PYTHONPATH`, the launch-directory shadowing and the installed-root cases. |
| **Caller/helper minor handoff** (Design A §5.3) | roadmap §5.3 | **present, under a different flag name — deliberately.** The wrapper passes `--caller-version=MAJOR.MINOR` (`_udf.caller_version_arg`) and the launcher refuses a mismatch with exit code 80, before any source bytes are consumed. The roadmap's prose names the argument `--caller-minor=3.X`, but **`--caller-version` is the name the review record chose**: `REVIEW_REQUEST_ROUND12.md` records it as a NEW REQUIRED launcher argument, and `ROUND13.md` records that the requirement was added after review. The implementation under review is authoritative over the roadmap's illustrative prose, so **this is not renamed**. The roadmap's §5.3 wording is the thing that is stale, and that is a documentation fix. |
| **Lifecycle** (C0.4/C0.5/C0.6) | `C0.5_INTERPRETER_MATRIX.md`, `C0.6_M2_MEASUREMENT.md` | **pre-fork is the recorded candidate**, measured on all six minors: pre-fork wins 48/48 (56/56 on 3.14) configurations, with the memory caveat measured too (pre-fork is worse at 1-2 workers, crosses over near 3, better from there). |
| **Packaging** (DECISION-01) | `DECISION-01-helper-packaging.md` §5.4, §6.3 | **Option A (per-minor wheels) for release; Option C (source-only) as the development path.** The Makefile already resolves the interpreter explicitly (`PYTHON ?= python3`, `PYCONFIG ?= $(PYTHON)-config`), so the "first `python3-config` on `PATH`" hazard is already handled. **The wheel-building side is NOT.** |
| **Supervision interface** | `SUPERVISION_INTERFACE.md` | **present** — this branch owns the supervisor; the launcher supervises in C with the same return codes as `_reactor.py`. |
| **Capability contract** | roadmap §5.5 | **present.** `v1_available()` has two return shapes and `"udf"` appears in **both**, including the `FORKRUN_NO_V1` branch. `FORKRUN_NO_UDF` masks only the UDF capability. |

---

## 3. What the work order asks for, and where it stands

| §12 definition-of-done item | state | evidence |
|---|---|---|
| UDF cleanroom route works for the eligible module-reference envelope on UMA | **present** | `fr_py_worker_udf_loop` in `_shim.c`; the launcher resolves it dynamically (`forkrun_cleanroom.c:2754`); `test_udf_mode.py`, `test_udf_helper.py`, `test_udf_version_barrier.py` |
| Unsupported callables declined before input consumption | **present** | `_udf.parse_spec` (string-only) + `_worker.py`'s `inspect.isclass` kind check; `test_class_payload_refusal.py` |
| The exact `Batch` class and return/error semantics match the in-process path | **present** | the helper calls the shared `_worker.py`; `test_udf_helper.py` |
| Caller/helper minor check enforced before input consumption | **present** | launcher exit code 80, before any source bytes; `test_udf_version_barrier.py` (19 tests) |
| Optional helper absence does not break ordinary builds or routes | **present** | the helper is optional in `Makefile.substrate`; `test_udf_mode.py` covers the absent-helper degradation |
| Substrate free of `libpython`; frozen ring untouched | **present** | the helper is a SEPARATE `.so`; the canary checks the substrate's `DT_NEEDED` |
| UDF capability and kill switch correct in every return shape | **present** | `_bindings.py:v1_available`; `test_no_udf_switch.py` |
| Worker death, respawn, poison, strict poison, abandonment, cleanup | **present** | `test_udf_exactly_once.py`, `test_udf_stream_liveness.py`, and the cleanroom suite |
| Cleanroom plugin, backpressure, C-drain, existing regression tests green | **present** | the full suite, and the C-drain work order's new module |
| Installed-package tests cover pure-Python and native-extension dependencies | **present** | `test_udf_helper.py` and `test_udf_mode.py` install into a temp prefix and import from it |
| Interpreter matrix and applicable packaging gates passed or limitations recorded | **PARTIAL** | the matrix harness works; the `auditwheel` gate cannot be run here (the tool is absent) |
| Performance and memory results include failures, sample counts, crossover | **present** | `C0.6_M2_MEASUREMENT.md` §"Crossover statement" |
| Generated capability matrix and authoritative documentation current | **to verify** | the matrix generator's `--check` |
| UDF cleanroom remains opt-in | **present** | `_DEFAULT_ROUTES = frozenset(("map-plugin",))` — the UDF routes are selectable but not default |

**The one real gap: the release wheel packaging.**

---

## 4. The gap, precisely

`setup.py` declares:

```python
package_data={"forkrun": [SO_NAME, CR_NAME, "py.typed"]},
options={"bdist_wheel": {"plat_name": PLATFORM_TAG}},
```

Two consequences:

1. **The helper is never shipped.** `python/forkrun/_fr_udf*.so` exists in
   the tree (built 2026-10-14) and is listed nowhere, so a wheel install
   has no UDF accelerator and silently degrades to the in-process path.
   This is the same class of bug as CR-FIX1-I, where the cleanroom
   launcher was "listed NOWHERE" and a wheel install silently had no
   cleanroom at all.

2. **The tag is `py3-none-<platform>`.** `DECISION-01` §6.2.1: *"a wheel
   built from an sdist on one machine and tagged `py3-none` would carry a
   different minor than its tag claims, with nothing in the artifact to
   prove it."* Shipping a CPython-linked helper under a `py3-none` tag is
   exactly that.

And `tools/build_wheel.sh:143`:

```bash
WHEELS=("$OUT_DIR"/forkrun-*-none-*.whl)
```

which rejects a `cp3XX` tag outright — the roadmap names this precisely.

---

## 5. The design that closes it

**The wheel's python tag follows the HELPER, not the running
interpreter.**

The helper's extension suffix encodes the minor it was compiled
against (`_fr_udf.cpython-314-x86_64-linux-gnu.so` -> 3.14). So:

- if `python/forkrun/_fr_udf<this interpreter's EXT_SUFFIX>` exists, it
  was built for this interpreter (the suffix carries the minor, and a
  helper built for another minor has a DIFFERENT name) -- so it is
  shipped, and the wheel is tagged `cp3XX` where XX is this
  interpreter's minor;
- otherwise the wheel stays `py3-none-<platform>` and no helper ships.

This satisfies the decision's "do not advertise a locally built helper
as present in a generic ABI-independent wheel" **by construction**: the
tag is never `py3-none` while a helper is present. It also means a
mismatched build produces a wheel whose tag says what the helper
actually is, rather than a lying one.

A plain `_fr_udf.so` (no suffix) is deliberately **not** shipped: its
minor cannot be established from its name, and the runtime fallback in
`_udf.py` still finds it in a source checkout, so the development path
keeps working.

---

## 6. Files and APIs to change

| file | change |
|---|---|
| `setup.py` | detect the helper for this interpreter; add it to `package_data`; set `bdist_wheel`'s `python_tag` to `cp3XX` when it is shipped |
| `tools/build_wheel.sh` | accept a `cp3XX` tag in the wheel glob, and refuse to select ambiguously |
| `python/tests/test_udf_helper.py` (or a new module) | pin the tag/contents contract: helper present -> `cp3XX` tag and the helper inside; helper absent -> `py3-none` and no helper |
| `dev/supervisor/DECISION-01-helper-packaging.md` | record that the per-minor RELEASE build (one interpreter per wheel) is a CI-pipeline item, and that the `auditwheel` verdict is unverified here |
| `DOCS/*` | align the `--caller-minor` / `--caller-version` naming with the roadmap |

## 6a. What this work order's own text got wrong, and what follows from it

Two places where the work order's text is behind the tree, recorded here
because a future agent will read the work order and not the tree:

1. **"Extend the existing Python cleanroom launcher to support eligible
   Python UDF workloads"** — the extension is already there. The helper
   (`fr_udf.c`), the worker loop (`fr_py_worker_udf_loop`), the launcher's
   dynamic resolution of it, the capability key, the kill switch, the
   environment contract and the version barrier are all implemented and
   tested. The work order's "Design A" section describes machinery that
   exists.
2. **"the roadmap specifies a `--caller-minor=3.X` argument"** — the
   implemented and REVIEWED name is `--caller-version=MAJOR.MINOR`
   (REVIEW_REQUEST_ROUND12/13). Renaming it would contradict the review
   record, so the roadmap's prose is what gets corrected.

**The consequence for the work order's scope:** §5 (packaging), §6
(eligibility/dispatch/helper boundary), §7 (tests) and most of §8
(performance) are largely CLOSURE work — verifying what exists and
recording it — with ONE real implementation gap (§4 above, the release
wheel packaging).

## 7. Stop conditions checked

- The tree matches the roadmap's key assumptions: **yes** (the route, the
  helper, the lifecycle candidate and the packaging decision are all as
  recorded).
- The helper architecture requires modifying the frozen engine: **no**
  (the helper is a separate `.so`; the engine is untouched).
- The substrate would acquire a `libpython` dependency: **no** (the helper
  is separate by construction, and the canary checks it).
- The supervisor contract would have to change incompatibly: **no**.

**No stop condition fires. Proceeding.**
