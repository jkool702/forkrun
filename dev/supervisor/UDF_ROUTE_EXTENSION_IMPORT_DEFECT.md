# The cleanroom's `map-udf` route cannot import C extension modules

**Status:** OPEN — a defect, found 2026-10-20 while preparing the
RSS-instrumented A/B that the UDF default-on decision needs.
**Severity:** the route is unusable for realistic UDFs, and it fails
**silently**.
**Blocks:** any default-on decision for `map-udf`. The route is
currently opt-in and must stay that way until this is fixed.

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

## 5. The proposed fix (NOT applied — it needs a review)

Two candidates, in the launcher (`forkrun_cleanroom.c`):

**(a) Promote libpython to the global scope, and only libpython.**
After the helper is loaded, find libpython's path from a symbol it
exports (`dladdr` on a libpython symbol, or read the helper's
`DT_NEEDED`) and `dlopen(that_path, RTLD_NOW | RTLD_GLOBAL)`. The
helper's own symbols stay local.

**(b) `dlopen(helper_path, RTLD_NOW | RTLD_GLOBAL)`.**
One word. In glibc this also promotes the helper's dependencies
(libpython) into the global scope. Simplest, but it widens the global
symbol scope to the helper's symbols too.

**Note on the security posture.** Today the accidental `RTLD_LOCAL`
behaviour *is* a hardening property — no extension module can load at
all. **That is not a defensible hardening**: it makes the route unable
to run real UDFs, and it is an accident of the dlopen flag rather than
a decision. Whatever is chosen should be recorded as a deliberate
decision, with the trade stated: extension modules become loadable in
the isolated interpreter. The isolation boundary itself (a separate
interpreter, an explicit root allowlist, `isolated=1`, `safe_path=1`)
is unaffected.

The **disposable probe** dlopen at `forkrun_cleanroom.c:993` should
stay `RTLD_LOCAL` — it is a throwaway.

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

## 7. Proposed work order

**WO-PY-UDF-EXTENSION-IMPORT-1 — the cleanroom's `map-udf` route must
be able to import a C extension module.**

- Fix the symbol scope (option (a) or (b) in §5), with the security
  trade recorded.
- Add a mutation-checked regression test: a UDF fixture that imports
  `math` (or `re`) and asserts the records come back. **Reverting the
  fix must fail it.**
- The existing fixture's purity is the reason this was invisible; say so
  in the test's docstring, so the next person does not assume "the
  suite is green" means "imports work".
- Rebuild the launcher and re-run the full gate.

**WO-PY-UDF-FALLBACK-1 — `mode="udf"` must fall back to the in-process
path when the `map-udf` route is not selected** (§6), with a
mutation-checked test.

Both are prerequisites for reviewing `map-udf` for default-on. Neither
is a code problem in the *product's* design; both are defects in the
plumbing around it.

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
