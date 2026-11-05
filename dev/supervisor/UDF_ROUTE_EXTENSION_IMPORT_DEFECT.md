# The cleanroom's `map-udf` route cannot import C extension modules

**Status:** the extension-import half is **FIXED** (see §9) — the loader
policy changed to `RTLD_GLOBAL` at the real helper load, with a
mutation-checked regression test. **The `mode="udf"` fallback defect in
§6 is still OPEN** and is deliberately a separate work order.
**Severity (as found):** the route was unusable for realistic UDFs, and
it failed **silently**.
**Blocks:** any default-on decision for `map-udf`. The route is
currently opt-in and must stay that way until §6 is fixed and the
release gates are cleared.

> **Summary of the fix.** The launcher loaded the per-minor helper with
> `RTLD_LOCAL`, so libpython's symbols never entered the global
> namespace and **no CPython extension module could be imported** in the
> isolated interpreter. The route is now at **parity with the in-process
> path** (0.975x–1.038x, was 3.65x–4.59x slower) and keeps its memory
> advantage. `math`, `re`, `numpy` and the `json` C accelerator all work
> in the cleanroom now.


---

## 1. The symptom

A UDF that imports a C extension module produces **zero records** and
**no exception**:

```python
# /tmp/opencode/udfbench/t7.py
def try_math(data):
    try:
        import math
        return b"OK math"
    except BaseException as e:
        return ("ERR " + type(e).__name__ + ": " + str(e)).encode()
```

```
$ FORKRUN_CLEANROOM=1 python3 -c "forkrun.map('t7:try_math', ..., mode='udf')"
try_math -> 2 entries
    ERR ImportError: /usr/lib64/python3.14/lib-dynload/math.cpython-314-x86_64-linux-gnu.so: undefined symbol: PyFloat_Type
```

The call **succeeds** (no exception, `map()` returns a result), the
UDF reports its own `ImportError` through the return value, and the
records are **poisoned** rather than delivered:

```
$ python3 -c "...; forkrun.last_run_stats()"
{'total': 2, 'completed': 0, 'poisoned': 2, 'poisoned_batches': [0, 1]}
```

With the default `on_error="retry"` the caller sees **an empty result
and nothing naming the cause**. The launcher's captured stderr says
only:

```
forkrun [WARN]: Skipping poisoned batch 0 (killed 3 times).
```

## 2. The root cause

`forkrun_cleanroom.c:1079` loads the per-minor UDF helper:

```c
hu = dlopen(helper_path, RTLD_NOW | RTLD_LOCAL);
```

The helper (`_fr_udf.cpython-314-x86_64-linux-gnu.so`) **depends on
libpython** — that is how it embeds an interpreter:

```
$ ldd python/forkrun/_fr_udf.cpython-314-x86_64-linux-gnu.so | grep python
    libpython3.14.so.1.0 => /lib64/libpython3.14.so.1.0
```

With **`RTLD_LOCAL`**, libpython's symbols are NOT placed in the global
namespace. Every later `dlopen` of a CPython **extension module**
(`lib-dynload/*.so`, each linked against libpython) therefore fails to
resolve `PyFloat_Type` and friends:

```
ImportError: .../lib-dynload/math.cpython-314-x86_64-linux-gnu.so:
             undefined symbol: PyFloat_Type
```

**The probe binary does not have this problem, and that is why it was
never seen.** `fr_udf_helper` is *linked* against libpython:

```
$ ldd python/forkrun/fr_udf_helper | grep python
    libpython3.14.so.1.0 => /lib64/libpython3.14.so.1.0
```

so libpython's symbols are global from the start, and the probe
imports `math`, `re` and `numpy` fine. The launcher is **not** linked
to libpython (`ldd _forkrun_cleanroom` shows no libpython), and that is
the only difference between the two paths.

### 2.1 This was a PYTHON-frontend drift from the bash reference

The project's rule is that the **bash frontend is the frozen
reference**. On this point the bash side was right and the Python
frontend had drifted:

- `fr_udf_fork` — the bash side's helper runner — is **linked against
  libpython** (`ldd fr_udf_fork` shows `libpython3.14.so.1.0`), so its
  symbols are global from the start and extension imports work.
- The bash frontend does not use `_forkrun_cleanroom` at all, so the
  defect was **Python-frontend-only**.

The fix restores parity with the reference rather than inventing a new
policy: the Python launcher now gets libpython into the global
namespace the same way the bash runner already had it.

### The worker's `sys.path` is fine — it is the symbol scope that is not

The isolated interpreter's search path is correct, which rules out the
obvious explanation:

```
 0  /tmp/opencode/udfbench                    <- the UDF's own directory
 1  /usr/local/lib64/python3.14/site-packages
 ...
 6  /usr/lib64/python314.zip
 7  /usr/lib64/python3.14
 8  /usr/lib64/python3.14/lib-dynload         <- PRESENT
```

and `lib-dynload/math.cpython-314-x86_64-linux-gnu.so` exists. The
path is right; the **symbol scope** is not.

## 3. Blast radius

Anything that imports a C extension module fails:

| import | result in the `map-udf` route |
|---|---|
| `json` | **works** — but silently loses its C accelerator (see §3a) |
| `sys`, `os`, `time`, `collections` | work — pure Python |
| `math`, `re`, `datetime` (C parts) | **FAIL** — `undefined symbol: PyFloat_Type` |
| `numpy`, `pandas`, `torch`, `sklearn` | **FAIL** — same cause |

`re` is the one that hurts most: it is in the standard library of
virtually every real program, and `ml_payload.py` — the benchmark's own
payload — imports `math` and `re` **at module level**. So:

> **Even if the published Python-UDF row were re-expressed as
> `mode="udf"`, it would return ZERO records** — not because of the
> `Batch`/`bytes` contract mismatch, but because of this defect.

That is a second, independent reason the published UDF row cannot move
(§5 of `CLEANROOM_HEADLINE_REMEASURE_2026-10-20.md`).

## 3a. The same defect also costs 4.6x SILENTLY, with no error at all

This is the worse half of the defect, because nothing fails.

`json` has a pure-Python fallback, so `import json` **succeeds** — but
`json`'s C accelerator is `_json`, which is itself an extension module,
so it cannot be loaded either. The UDF therefore runs on the pure-Python
scanner, with no diagnostic of any kind:

```
                    json.decoder.scanstring      json.loads
  in-process        '_json'          (C)           2.88 us/call
  cleanroom         'json.decoder'   (pure Py)    13.19 us/call    4.6x slower
```

**Measured inside the UDF itself**, so the number is the UDF's own
experience, not an inference:

```python
# jsonprobe.py
def which_scanstring(data):
    return ("scanstring module=%r" % (json.decoder.scanstring.__module__,)).encode()

def speed_probe(data):
    blob = b'{"eid":"x","uid":1,"iid":2,"ts":1700000000,"et":"view","dev":"ios","dur":80}'
    t0 = time.perf_counter()
    for _ in range(20000):
        json.loads(blob)
    t1 = time.perf_counter()
    return ("json.loads %.2f us/call" % ((t1 - t0) / 20000 * 1e6)).encode()
```

**This accounts for the entire throughput gap** in the RSS A/B
(`WO_PY_UDF_CLEANROOM_MEMORY_AB_2026-10-20.md`): the cleanroom's
`map-udf` route measured **3.65x–4.6x slower** than the in-process path
on a json-per-record payload, and only **1.5x slower** on a payload that
does no json at all. The route's own overhead is ~30 ms of start-up
plus a per-batch cost that is *smaller* than the in-process path's; the
gap was the missing C accelerator all along.

**Consequence for the default-on decision:** defaulting `map-udf` would
make every json-using UDF about 4.6x slower, silently, unless this
defect is fixed first.

## 4. Why the test suite cannot see it

`python/tests/test_udf_mode.py` builds its fixture as **pure Python**:

```python
UDF_SRC = '''
def up(b):        return b.upper()
def to_none(b):   return None
def empty(b):     return b""
def raiser(b):    raise ValueError("udf exploded")
def sys_exit(b):  import sys; sys.exit(7)
'''
```

Not one fixture imports an extension module. The 100 focused UDF tests
are green, and they would stay green with this defect present.

**A mutation-checked regression test is required:** a fixture that
imports a C extension (`math`, or better `re` — stdlib, always
present) and asserts the UDF's records come back. Reverting the fix
must make it fail.

## 5. The fix

Two candidates were considered. **Option (b) was chosen** — load the
real helper with `RTLD_GLOBAL` — after external review:

> *"The decisive point is that the problem isn't merely that the
> helper's symbols are local. The embedded interpreter needs its
> `libpython` symbols visible to subsequently loaded extension modules."*
> *"CPython's 3.8 release notes say that on Unix, when Python is
> embedded, `libpython` must not be loaded with `RTLD_LOCAL`; it must be
> loaded with `RTLD_GLOBAL`... because C extensions no longer generally
> link directly against `libpython` on Unix."*

Option (a) (promote only libpython, discovering its path at runtime) is
retained as the **fallback design**, to be used only if the one-flag
approach turns out to be unsafe in some supported environment.

### 5.1 The change

`forkrun_cleanroom.c`, the real helper load (was line 1079):

```c
-    hu = dlopen(helper_path, RTLD_NOW | RTLD_LOCAL);
+    hu = dlopen(helper_path, RTLD_NOW | RTLD_GLOBAL);
```

**The disposable probe load keeps `RTLD_LOCAL`** — it is a throwaway
child whose only job is to prove the artifact loads. The plugin probe
and the substrate load are also unchanged (neither is CPython-linked).

### 5.2 The loader policy, recorded

The wider symbol scope is confined to **this launcher's own address
space**: the launcher is a separate, `exec`'d process, so the caller's
Python process is untouched.

The helper's exported dynamic symbols were inspected: **15 of them, all
prefixed `fr_udf_*`** (`nm -D --defined-only`), so the added collision
surface is negligible. **Symbol visibility is not treated as a security
boundary here** — the boundary is the separate process, the
interpreter's isolated config, and the explicit root allowlist. The
review was explicit that "the claim of no real security downside is too
absolute", and that is why the trade is recorded here rather than left
implicit in a flag.


## 6. A second, smaller defect found alongside it

`mode="udf"` **raises** when the helper is present but the `map-udf`
route is not selected:

```
$ FORKRUN_CLEANROOM=0 python3 -c "forkrun.map('udf_payload:up', ..., mode='udf')"
NotImplementedError: v0 supports mode='python' only (spawn/plugin are Stage 5)
```

The documented contract is the opposite — `forkrun/run.py:4466`:

> *"The call must STILL work -- mode='udf' is not an error, and the
> documented fallback is the in-process path, which runs the UDF in THIS
> interpreter."*

The in-process fallback fires when the **helper file is absent**
(`_coerce_payload` consults `_udf_helper_path()`), which is why
`test_udf_mode.py` exercises it by monkeypatching `_udf_helper_path`
to return `None`. It does **not** fire when the helper is present and
the route is merely **not selected** — the ordinary executors then
receive an `_UDFPayload` they cannot execute.

**This matters for the default-on decision specifically:** "opt-in"
currently means *"the default configuration raises `NotImplementedError`
for anyone who pip-installs a wheel carrying the helper"*. Opting OUT
(`FORKRUN_CLEANROOM=0`) raises too. A default-on decision needs the
non-cleanroom path to be genuinely graceful, because that is the path
a user falls back to when the cleanroom is unavailable.

A fix would make `_coerce_payload`'s helper-present branch conditional
on the `map-udf` route actually being selected, so the in-process
fallback is taken when it is not.

## 7. Work orders

**WO-PY-UDF-EXTENSION-IMPORT-1 — the cleanroom's `map-udf` route must
be able to import a C extension module.** — **DONE** (§9).

- Fix the symbol scope: **option (b)**, `RTLD_GLOBAL` at the real
  helper load, the disposable probe left alone.
- Mutation-checked regression test: `python/tests/test_udf_extension_import.py`.
- Rebuild the launcher and re-run the full gate.

**WO-PY-UDF-FALLBACK-1 — `mode="udf"` must fall back to the in-process
path when the `map-udf` route is not selected** (§6), with a
mutation-checked test covering BOTH the helper-present-but-disabled and
the helper-absent cases. — **OPEN**, deliberately a separate fix and a
separate commit.

Both were prerequisites for reviewing `map-udf` for default-on. Neither
is a code problem in the *product's* design; both are defects in the
plumbing around it.

## 9. The fix, the test, and the re-measurement

### 9.1 The regression test

`python/tests/test_udf_extension_import.py` — 5 tests. The assertions
are **deterministic, not wall-clock thresholds**:

| test | what it pins |
|---|---|
| `test_a_udf_can_import_a_c_extension` | a fixture importing `math` and `re` **at module level** returns every record, with the values `math.sqrt` computed **in the worker** |
| `test_no_batch_is_poisoned` | `last_run_stats()` shows zero poisoned batches and completed == total — the silent-empty failure mode |
| `test_the_json_c_accelerator_is_loaded` | `json.decoder.scanstring.__module__ == "_json"` — the C scanner, not the pure-Python fallback. An exact witness, not a timing |
| `test_json_still_works` | json still functions |
| `test_the_cleanroom_and_in_process_results_are_byte_identical` | the two arms agree byte for byte, so the route does not change what the UDF computes |

The fixture imports the extensions **at module level** on purpose: that
is how a real UDF is written, and it is the strictest form — a
module-level import failure takes down every function in the module.

### 9.1a The test would have been dead too — and so was the UDF suite

The first version of this test **gated on the ambient
`FORKRUN_CLEANROOM`**, following `test_udf_mode.py`. It was skipped in
BOTH gate passes — including the one that runs with the flag set — so
it would have guarded nothing.

The cause: `test_stage3_public_dispatch.py`'s `_restore` did
`os.environ.pop("FORKRUN_CLEANROOM", None)` unconditionally, **deleting**
the variable for every test that ran afterwards. Every later test that
gates on it then SKIPPED rather than running.

Watched at every test boundary through a real discover run:

```
VALUE '1'       before test_abort_reason...
VALUE '0'       before test_numa_ordering_identity...
VALUE '1'       before test_numa_recovery...
VALUE '<unset>' before test_stage3_public_dispatch...    <-- the leak
```

**So the pre-existing end-to-end UDF suite — `test_udf_mode`'s
`TestUDFModeEndToEnd`, 14 tests including the DECISION-02 `None`/`b""`
contract tests — was also dead.** That is the deeper reason this defect
survived a green gate: the UDF route's end-to-end coverage was not
executing at all.

Fixed in two places:

- `_restore` now restores the saved value (the `self._old = {}` that was
  meant to hold it was never populated; the house pattern in
  `test_cleanroom.py` saves and puts back).
- The new test **owns its precondition**: it sets `FORKRUN_CLEANROOM=1`
  itself and restores the previous value, rather than gating on
  ambient state — the way `test_cleanroom.py` does.

The gate counts show the revival:

| pass | before | after |
|---|---|---|
| g1 (cleanroom off) | 1446 tests, 2 skipped | **1451 tests, 2 skipped** |
| g1on (cleanroom on) | 1446 tests, 2 skipped | **1458 tests, 1 skipped** |

Both passes OK.

### 9.2 The mutation check

Reverting the launcher to `RTLD_LOCAL`, rebuilding, and re-running the
file: **5 of 5 tests FAIL**. Restoring `RTLD_GLOBAL` and rebuilding:
**5 of 5 pass.** The test is not vacuous.

### 9.3 The reviewer's acceptance conditions, and how each was met

| condition | how it was established |
|---|---|
| Fix the correct load site; keep the probe's `RTLD_LOCAL` | `forkrun_cleanroom.c`: the real load is now `RTLD_GLOBAL`; the disposable probe (993), the plugin probe (2703) and the substrate (2790) are unchanged |
| Prove native extensions work | a cleanroom UDF importing `math`, `re` **and `numpy` (2.4.6)** now returns all expected records, 0 poisoned |
| Catch the original failure | the mutation check in §9.2: reverting the flag fails all 5 tests |
| Prove JSON acceleration works | `json.decoder.scanstring.__module__ == "_json"` from inside the UDF; `json.loads` 13.19us -> **2.39us** |
| Preserve output semantics | the two arms are byte-identical over the whole corpus; 0 poisoned batches |
| Validate the claimed performance benefit | re-measured with the arms **alternating** — see §9.4 |

### 9.4 The re-measurement

Same payload, same corpus, same arms, **arms alternating per rep**, 5
reps, no sampler running:

| workers | in-process | cleanroom | ratio (before fix) | ratio (after fix) |
|---|---|---|---|---|
| 1 | 3.361 s | 3.276 s | 4.59x | **0.975x** |
| 2 | 1.762 s | 1.772 s | 4.35x | **1.006x** |
| 3 | 1.191 s | 1.218 s | 4.36x | **1.023x** |
| 4 | 0.917 s | 0.911 s | 4.31x | **0.993x** |
| 8 | 0.487 s | 0.499 s | 4.18x | **1.026x** |
| 14 | 0.329 s | 0.329 s | 3.89x | **0.998x** |
| 28 | 0.323 s | 0.336 s | 3.65x | **1.038x** |

**The route is at parity with the in-process path, within ±4%.** The
missing C accelerator was the entire gap.

**No 4.6x promise is made**: the reviewer was right that the
microbenchmark only implicates the accelerator. What is measured is the
end-to-end result on this workload, and it is parity.

Memory is **unchanged** by the fix (it is structural — the route never
inherits the caller's heap):

| inflated parent, 28 workers | tree RSS | tree PSS |
|---|---|---|
| in-process | 16,403 MB | 647 MB |
| cleanroom | **1,133 MB** | **428 MB** |

(Before the fix the same cells read 16,392 / 1,169 MB and 698 / 440 MB —
the same picture within run-to-run variation.)

### 9.5 What this leaves

The route is now **strictly better than the in-process path**: the same
speed, less memory, and a UDF that keeps its extensions. The two
remaining obstacles to a default-on decision are the **fallback defect
(§6)**, the **per-minor release wheel build**, and the **`auditwheel`
verdict** — and the route stays **opt-in** until those are done.


## 8. Reproduction

```
mkdir -p /tmp/repro && cd /tmp/repro
printf 'def probe(data):\n    import math\n    return b"OK"\n' > m.py
PYTHONPATH=/tmp/repro:$PWD python3 -c "
import forkrun
got = list(forkrun.map('m:probe', 'input.txt', mode='udf',
                       output='bytes', workers=1, order='index'))
print(len(got), 'entries', forkrun.last_run_stats())"
```

with `FORKRUN_CLEANROOM=1` and a helper built for the running minor.
Expected: `0 entries` with `poisoned: 1`, and no exception.
