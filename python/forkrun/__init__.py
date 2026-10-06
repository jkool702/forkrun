"""forkrun — NUMA-aware streaming parallelization for Python.

Quick start::

    import forkrun
    results = forkrun.map(my_function, "input.txt", workers=8)

Modes (``mode=``): ``"python"`` (callable payload, default),
``"spawn"`` (external command), ``"plugin"`` (C callback in a
``.so``), ``"splice"`` (kernel passthrough, payload must be
``None``). Entry points: ``run`` (fire-and-forget),
``map`` (collect), ``stream`` (live generator), ``sweep``
(parameter combinations). ``Batch`` is the per-batch view
(``.data`` borrowed memoryview — ``copy()`` to keep).

Full guides: ``python/docs/`` (QUICKSTART, API, MODES,
CONFIGURATION, FAULT_TOLERANCE, NUMA, STREAMING, EXAMPLES,
PLUGINS, PERFORMANCE, TROUBLESHOOTING, MIGRATION,
COMPARISON).

Naming note: this is a namespaced API, so `forkrun.map` deliberately shadows
the builtin `map` *inside this namespace only* (`forkrun.map(...)`, never a
bare `map(...)`). The alias is chosen to match the mental model of the
incumbents we benchmark against (`ProcessPoolExecutor.map`, `joblib`, and the
DataLoader idiom), which is the point of the convenience wrappers. `import
forkrun` does not shadow anything at the call site of the importer.
"""

import sys as _sys

if _sys.platform != "linux":
    raise ImportError(
        "forkrun requires Linux (got %s). The C substrate uses "
        "Linux-specific syscalls (memfd_create, splice, fallocate)."
        % _sys.platform)
del _sys

# W-REL5-E5: RunConfig is NOT re-exported (it was in __all__ but no
# public entry point returns it — run/map/stream/sweep discard the
# _validate product, and importing it documented a contract that
# doesn't exist). Reachable as forkrun._api.RunConfig for the
# _validate_config test seam below. Producing one is API design
# (3.6.1 if wanted), not hygiene.
# Private in _api (not part of the v0 surface); re-exported here only so the
# Stage 0 harness and tests can assert validation without reaching into _api.
from forkrun._api import _validate as _validate_config  # noqa: F401
from forkrun._batch import Batch  # noqa: F401
from forkrun.exceptions import (BASH_CODE_MAP, ForkrunInterrupted,  # noqa: F401
                                ForkrunPoisonSkip, ForkrunPreempted,
                                ForkrunSignalError, ForkrunTerminated,
                                ForkrunWorkerFailure)
from forkrun.run import map, run, stream, sweep  # noqa: F401
from forkrun.run import last_run_stats  # noqa: F401

# 0.17.0: result records default to memoryview (output="view"); the
# copy-per-record representation moves to the explicit output="bytes".
# Bumped rather than reused so a 0.16.0 wheel and a 0.17.0 wheel never
# claim the same version while behaving differently.
__version__ = "0.17.0"


def materialize(blob):
    """Return a real ``bytes`` from a result record.

    Records come back as ``memoryview`` slices over the mapped
    collection file rather than copies -- the same hand-a-reference
    approach bash's orderer takes with (fd, offset, len), and ~48x
    cheaper on the collect path (W-PYZEROCOPY). That is a buffer, not a
    sequence: ``len()``, slicing, iteration, ``.tobytes()``, ``.hex()``,
    comparison against ``bytes`` and writing to a file object all work
    unchanged, but ``x in blob`` does not, and ``isinstance(blob,
    bytes)`` is False.

    Call this when you need true bytes (hashing, a regex, a library
    that type-checks, a comparison by containment). It copies, so use
    it once at the boundary rather than per record. Alternatively set
    ``FORKRUN_ZERO_COPY=0`` before importing forkrun to get ``bytes``
    back everywhere, at the old cost.
    """
    return blob if isinstance(blob, bytes) else bytes(blob)



def _query_engine_version() -> str:
    """Read ring_version() from the built substrate (W-PY2 API polish)."""
    from forkrun._bindings import find_substrate, load  # noqa: PLC0415

    lib = load(find_substrate())
    ver = lib.fr_py_version()
    return ver.decode("utf-8") if isinstance(ver, bytes) else str(ver)


try:
    __engine_version__ = _query_engine_version()
except Exception:  # noqa: BLE001
    # Validation-only environments (no built .so): import must never fail.
    __engine_version__ = "unknown"

__all__ = ["run", "map", "stream", "sweep", "Batch",
            "last_run_stats", "materialize",
            "ForkrunSignalError", "ForkrunInterrupted", "ForkrunPreempted",
            "ForkrunTerminated", "ForkrunPoisonSkip", "ForkrunWorkerFailure",
            "BASH_CODE_MAP", "__version__", "__engine_version__"]
