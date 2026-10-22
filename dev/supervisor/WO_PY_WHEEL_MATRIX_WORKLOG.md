# Per-minor release wheel build — work log and findings

**Order:** Priority 2 of the overnight work order.
**Branch:** `NEW/REFACTOR4.4`
**Starting HEAD for this item:** `918b0b7e` (Priority 1 committed first).

---

## 1. The compatibility matrix, from the repository's own declarations

| source | what it declares |
|---|---|
| `dev/supervisor/DECISION-01-helper-packaging.md` §3/§4 | **Option A**: "Build one helper per supported CPython minor; ship wheels tagged `cp310`, `cp311`, … `cp315`" — **3.10–3.15**, and "the roadmap already requires a 3.10–3.15 test matrix, so per-minor wheels reuse that matrix; they do not create a new one" |
| `tools/matrix_c05.sh` | the same set, minus the host's own minor (which is already present) — it used to carry its own copy of the list |
| `setup.py` | `python_requires=">=3.10"`; classifiers 3.10–3.13 |
| `tools/build_wheel.sh` | "already selects newest-first from `/opt/python/cp3XX-cp3XX`, so adding `cp315` and looping it is a small change" (DECISION-01 §4.3) |

**The canonical list is now ONE definition**: `tools/wheel_matrix.py::SUPPORTED_MINORS`
= 3.10 … 3.15. `tools/matrix_c05.sh` reads it (and drops the host's own
minor, which is why it still resolves to "3.10 3.11 3.12 3.13 3.15" on a
3.14 host). A test asserts the script does not go back to a private list.

### ABI variants

**The free-threaded flavour is NOT built.** `setup.py` declines to ship
a free-threaded helper (it links `libpython3.Xt.so.1.0`, a different
soname from `libpython3.X.so.1.0`, so the artifacts are mutually
load-incompatible), and `DECISION-01`/the C0.5 matrix measure GIL
interpreters only. The interpreter lookup therefore **refuses** the
free-threaded twin rather than picking it and producing a `py3-none`
wheel that is not a per-minor wheel at all.

The existing distinction is preserved: `setup.py` and the matrix both
ask the **runtime's** detector (`forkrun._udf.freethreaded_interpreter`)
rather than keeping a local copy of the flavour rule.

### Platforms

`setup.py::get_platform_tag()` derives a PEP 600 manylinux floor from
the **build host's** glibc; `tools/build_wheel.sh` builds inside
`manylinux_2_28_x86_64` (the engine's true floor). Only x86_64 and
aarch64 are accepted. A wheel with a helper is tagged
`cp3XX-cp3XX-<platform>`; a wheel without one stays `py3-none-<platform>`.

**Reported discrepancy (not changed here):** `setup.py`'s classifiers
stop at 3.13 while the floor is `>=3.10` and the decision covers
3.10–3.15. The wheels follow the decision; the classifier list is
upstream's to fix.

---

## 2. What was implemented

`tools/wheel_matrix.py` (new) — the ORCHESTRATION, not a second
packaging implementation:

- the wheel is still built by the repository's own `setup.py`;
- the helper is still built by `Makefile.substrate`'s `udf-lib` target
  (which already takes `PYTHON=`, and whose comment names this exact
  use: "building the wheel matrix");
- the tag is still `setup.py`'s to decide — it derives the tag FROM the
  helper's extension suffix.

What the module adds: the loop, the interpreter lookup, the cleanup
between minors, the per-wheel validation, the install+smoke check, and
the honest report.

`tools/build_wheel.sh` gains `--matrix`, `--minor X.Y`, `--strict`.
`tools/matrix_c05.sh` now reads the canonical list.

### The tag-vs-artifact rule is ONE implementation

`tools/build_wheel.sh` carried an inline Python heredoc that checked
the wheel's python/ABI tag against the helper it shipped. The matrix
needed the same rule. It now lives in `tools/wheel_matrix.py`
(`validate_wheel_tags`) and the shell calls
`python3 tools/wheel_matrix.py --validate-wheel "$WHEEL"`. Two copies
of a rule is how they drift.

---

## 3. The two fail-closed rules

- **Never substitute.** A missing interpreter is REPORTED as not
  built. The build never falls back to another interpreter: a wheel
  tagged `cp310` that was compiled by 3.12 is a lie the tag cannot
  detect.
- **Never reuse.** Every helper artifact is removed from the tree
  before a minor's helper is built, so a stale `_fr_udf.cpython-312-*`
  can never reach a 3.13 wheel.

`--strict` exits non-zero when a supported minor did not produce a
valid wheel, so **a partial matrix is never reported as a complete
release build**.

---

## 4. What was validated, and what was not

### VALIDATED (observed)

**One minor, end to end: 3.14** (the host's own minor).

```
minor   : 3.14
status  : built
wheel   : dist/matrix/forkrun-0.17.0-cp314-cp314-manylinux_2_39_x86_64.whl
interp  : /usr/bin/python3
smoke   :  forkrun 0.17.0
           substrate True
           launcher True
           helpers ['_fr_udf.cpython-314-x86_64-linux-gnu.so']
```

- the wheel is built by the canonical `setup.py` ✓;
- its tags are `cp314-cp314` — the python tag AND the ABI tag name the
  minor, derived from the helper's suffix ✓;
- it installs into an isolated venv created with the SAME interpreter
  that built it ✓;
- `import forkrun` works from the installed wheel ✓;
- the installed wheel carries the substrate `.so`, the cleanroom
  launcher, and the UDF helper **for 3.14** ✓.

The matrix orchestration itself was observed to work end to end in the
container as well: it located each interpreter, built each helper, and
reported each outcome individually (see §5).

### NOT VALIDATED (and why) — reported, not simulated

| matrix entry | status | reason |
|---|---|---|
| 3.10, 3.11, 3.12, 3.13, 3.15 | **not built** | the `manylinux_2_28_x86_64` image ships no CPython with an embeddable libpython (see §5), so the helper cannot be built there; and this host's distro repositories could not supply the older interpreters (`dnf download` failed: `python3.13-libs` — "All mirrors were tried") |

**No entry was simulated into a successful build.** The matrix reports
`not-built` with the reason, and `--strict` turns that into a failure.

---

## 5. Two real findings about the release path

### 5.1 The manylinux image cannot build the UDF helper

The helper **embeds** the interpreter: it links `libpython3.X`, which
is why it is a separate artifact and why the wheel tag follows it.

The `manylinux_2_28_x86_64` image's interpreters are built with a
**static** libpython (`Py_ENABLE_SHARED=0`, `LDLIBRARY=libpython3.13.a`)
and the static archives are stripped from the image:

```
$ ls /opt/python/cp313-cp313/lib/     -> pkgconfig, python3.13   (no libpython)
$ find /opt/python -name 'libpython*.so*'   -> (nothing)
$ find /opt/_internal -name 'libpython*.a'   -> (nothing)
```

So `make udf-lib PYTHON=/opt/python/cp313-cp313/bin/python3.13` fails
with `cannot find -lpython3.13`, and the matrix reports it per minor.
**The container release path therefore cannot produce a per-minor
wheel** — it can produce the generic `py3-none` substrate wheel, which
is what it now honestly produces (see 5.2).

**What a per-minor release build needs that this environment does not
have**: a CPython **with an embeddable libpython** AND an old enough
glibc to satisfy the manylinux policy. The two constraints are in
tension here — the host has libpython but a too-new glibc (auditwheel
correctly refuses: "cannot repair … to `manylinux_2_41_x86_64` ABI
because of the presence of too-recent versioned symbols"), and the
container has the right glibc but no libpython. The remaining piece is
building a shared-libpython CPython inside the container.

### 5.2 The container build could ship a FOREIGN helper

Before this change, the container build took whatever helper was
already in the tree. That helper was built on the HOST, linked against
the HOST's glibc — so it could be baked into a `manylinux_2_28` wheel,
whose tag would then be a lie (the binary needs a newer glibc than the
tag claims). This is exactly the trap `tools/build_wheel.sh`'s own
header describes ("auditwheel would (correctly) refuse to stamp
manylinux_2_28 on a binary that references 2.38 symbols").

The container step now removes any pre-existing `_fr_udf*.so` before
building, so the container build produces the generic substrate wheel
it can honestly produce. The per-minor path builds its own helper
under its own interpreter, with the cleanup between minors.

---

## 6. Tests

`python/tests/test_wheel_matrix.py` — 18 tests, exercising the
orchestration's BEHAVIOUR (not the existence of a shell script):

- the supported list is the decision's, and `matrix_c05.sh` reads it;
- a missing interpreter is reported, never substituted;
- the free-threaded twin is refused; the GIL interpreter wins when
  both exist;
- only helper artifacts are removed (the substrate `.so`, the launcher
  and the package modules are not);
- a wheel tagged for another minor is rejected; a wheel whose helper
  is for another minor is rejected; a `cp3XX` wheel with no helper is
  rejected; a generic wheel that ships a helper is rejected; a
  `none`-ABI wheel with a GIL helper is rejected; a generic wheel with
  no helper is accepted;
- an incomplete matrix lists its missing minors, and `--strict` exits
  non-zero.
