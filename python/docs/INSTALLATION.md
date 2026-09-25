# forkrun Installation

## Requirements

| Requirement | Notes |
|---|---|
| Linux (any recent kernel) | Uses `memfd_create`, `splice`, `fallocate` — import raises `ImportError` anywhere else |
| Python 3.10+ | Pure-Python frontend + ctypes (no Cython, no extensions to compile yourself) |
| `gcc` + `make` | Builds the C substrate at install time |
| bash headers | Fedora/RHEL: `dnf install -y gcc make bash-devel python3-devel`. Debian/Ubuntu do **not** package bash headers — use the Fedora container (same rule as the substrate Makefile) |

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
| bash headers missing on Debian/Ubuntu | Expected — use Fedora/RHEL or the container image |
| `pip install` fails on setuptools | Needs `setuptools>=61` + `wheel` (PEP 517 build) |

## What gets installed

- `forkrun` package: `run`, `map`, `stream`, `sweep`, `Batch`
- The prebuilt-in-place `libforkrun_python.so` (gitignored in-tree,
  bundled in the wheel)
- No test files, no benchmarks, no daemon processes. `forkrun`
  forks short-lived workers per call and reaps them before
  returning — nothing runs when you're not calling it.
