# forkrun Installation


## Requirements

| Requirement | Notes |
|---|---|
| Linux (any recent kernel) | Uses `memfd_create`, `splice`, `fallocate` — import raises `ImportError` anywhere else |
| Python 3.10+ | Pure-Python frontend + ctypes (no Cython, no extensions to compile yourself) |
| `gcc` + `make` | Builds the C substrate at install time |
| bash headers | Fedora/RHEL: `dnf install -y gcc make bash-devel python3-devel`. Debian/Ubuntu do **not** package bash headers — use the Fedora container (same rule as the substrate Makefile) |

## The optional Python-UDF helper (`_fr_udf`)

The cleanroom can run **Python UDFs** — `mode="udf"` with a
`"module:attribute"` reference — using a **separate, optional helper
shared object** that embeds CPython. The helper is NOT part of the
substrate: `libforkrun_python.so` stays interpreter-independent and
free of any `libpython` dependency, which is what lets one substrate
serve 3.10-3.15.

**It is optional, and its absence is not a failure.** A wheel built
without the helper installs and works; the UDF route then degrades to
the in-process path, which is slower and correct. The capability
predicate reports this honestly:

```python
from forkrun._bindings import v1_available
v1_available()["udf"]        # False -> no usable helper for this caller
```

`FORKRUN_NO_UDF=1` masks **only** that capability. It is deliberately
not a mirror of `FORKRUN_NO_V1`, which forces every v1 fast path off.

**Building it yourself (the development path).**

```bash
make -f Makefile.substrate udf-lib PYTHON=/path/to/python3.12
```

Resolve the interpreter **explicitly**: the helper links `libpython3.X`,
and the `X` is decided by which headers were on the command line. The
first `python3-config` on `PATH` is not proof of a matching
interpreter, so pass the one you mean.

**Wheel tags follow the helper, not your shell.** A wheel that ships
the helper is tagged `cp3XX-cp3XX` — it is valid only for the minor it
was built against. A wheel with no helper is tagged `py3-none-<platform>`
and stays interpreter-agnostic. The tag is derived from the helper's
extension suffix, which encodes its minor, so a mismatched build
cannot produce a wheel that claims the wrong minor.

**The ABI tag is not the same thing as the version tag, and it matters.**
`cp314` names a python *version*; the abi tag names the *ABI*. A
free-threaded CPython 3.14 links `libpython3.14t.so.1.0` where a GIL
one links `libpython3.14.so.1.0` — different sonames, so a helper
built for one cannot be loaded by the other. The loose ABI tag `none`
means "no ABI constraint", and a free-threaded 3.14 accepts
`cp314-none-<platform>` exactly as a GIL 3.14 does — so a GIL-built
helper in a `none`-ABI wheel would be offered to an interpreter that
cannot load it. The wheel therefore carries the **real** ABI tag.

**Free-threaded CPython is NOT supported for this helper route**, and the
packaging declines to claim it: such a build ships no helper at all, and
the wheel stays the generic `py3-none` one. The reasons are structural,
not caution — the helper links a different `libpython` soname, the
interpreter matrix fetches GIL builds only, and the cleanroom launcher
has never been exercised against a free-threaded interpreter. Supporting
it is a separate piece of work: distinguish `cp3XXt` in the helper
detection and tag the wheel `cp3XX-cp3XXt`.

**A caveat on the source-only path.** A helper built locally into a
source checkout is found by the runtime fallback
(`forkrun/_udf.py` looks for `_fr_udf.so` as well as the suffixed
name), so the development path works. A *wheel* refuses to ship the
plain-named helper: its minor cannot be established from its name, and
the wheel must not claim a minor it cannot prove.


## From PyPI

```bash
pip install forkrun
```

This builds the C substrate (`python/forkrun/libforkrun_python.so`)
during install and places it next to the package. Verify:

```bash
python3 -c "import forkrun; print(forkrun.__engine_version__)"
# e.g. "v3.5.2" — "unknown" means the .so didn't build
```

## From source

```bash
git clone https://github.com/jkool702/forkrun
cd forkrun
make -f Makefile.substrate python-substrate   # builds python/forkrun/libforkrun_python.so
pip install .                                 # installs the wheel
```

Reproducible builds: two consecutive builds from the same source
are byte-identical (`make -f Makefile.substrate
reproducibility-check`).

## Offline / pinned installs

```bash
pip wheel .                                   # local wheel, no index
pip install --no-index --find-links . forkrun
```

No PyPI upload is automated in-tree; releases are cut manually.

## Troubleshooting the install

| Symptom | Cause / fix |
|---|---|
| `ImportError: forkrun requires Linux` | Non-Linux host — not supported, by design |
| `libforkrun_python.so not found` | Substrate never built — run the `make` line above, or reinstall |
| `__engine_version__ == "unknown"` | Same as above; import still works for validation-only use, engine calls will fail until the `.so` exists |
| Bad `$FORKRUN_LIB`, yet `import forkrun` succeeds | By design: import dlopens the substrate and swallows the lookup failure (`FileNotFoundError` → `"unknown"`), so validation-only use never breaks. Engine calls raise the same `FileNotFoundError` later — unset/fix `$FORKRUN_LIB` (search order: `$FORKRUN_LIB`, package dir, repo root, CWD) and rebuild |
| bash headers missing on Debian/Ubuntu | Expected — use Fedora/RHEL or the container image |
| `pip install` fails on setuptools | Needs `setuptools>=61` + `wheel` (PEP 517 build) |

## What gets installed

- `forkrun` package: `run`, `map`, `stream`, `sweep`, `Batch`
- The prebuilt-in-place `libforkrun_python.so` (gitignored in-tree,
  bundled in the wheel)
- No test files, no benchmarks, no daemon processes. `forkrun`
  forks short-lived workers per call and reaps them before
  returning — nothing runs when you're not calling it.
