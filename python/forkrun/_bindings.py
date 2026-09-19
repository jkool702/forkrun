"""ctypes bindings for the Python-facing substrate shim (W-PY1).

The shared object is built by ``make -f Makefile.substrate python-substrate``
from ``python/forkrun/_shim.c`` (which textually includes the engine TU, so
all fr_py_* entry points below are real exports; the engine's own
ring_*_main helpers stay static and are NOT bound here).

Guardrails: fork before threads (load in the parent before forking workers
is fine — the .so carries no thread state; payload native imports happen
post-fork in the worker). No pickle, no bash, no argv vectors anywhere.
"""

from __future__ import annotations

import ctypes
import os

_LIB = None
_LIB_PATH = None

# fr_py_claim return codes (mirror do_lockfree_claim via the shim).
RC_OK = 0
RC_FAIL = 1
RC_EOF = 2


class FrPyBatch(ctypes.Structure):
    """Claim out-param (mirrors fr_py_batch_t in _shim.c).

    Identity fields match fr_state_t widths; offset/length/lines carry the
    payload byte window that fr_state_t deliberately excludes.
    """

    _fields_ = [
        ("batch_idx", ctypes.c_uint64),
        ("slots", ctypes.c_uint32),
        ("lines", ctypes.c_uint32),
        ("num_kills", ctypes.c_uint32),
        ("poisoned", ctypes.c_uint32),
        ("offset", ctypes.c_uint64),
        ("length", ctypes.c_uint64),
        ("major", ctypes.c_uint64),
        ("minor", ctypes.c_uint32),
    ]


def _setup_signatures(lib) -> None:
    lib.fr_py_version.argtypes = []
    lib.fr_py_version.restype = ctypes.c_char_p
    lib.fr_py_init.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.fr_py_init.restype = ctypes.c_int
    lib.fr_py_destroy.argtypes = []
    lib.fr_py_destroy.restype = ctypes.c_int
    lib.fr_py_ingest_done.argtypes = []
    lib.fr_py_ingest_done.restype = ctypes.c_int
    lib.fr_py_scan.argtypes = [ctypes.c_int]
    lib.fr_py_scan.restype = ctypes.c_int
    lib.fr_py_worker_init.argtypes = [ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int]
    lib.fr_py_worker_init.restype = ctypes.c_int
    lib.fr_py_claim.argtypes = [ctypes.POINTER(FrPyBatch)]
    lib.fr_py_claim.restype = ctypes.c_int
    lib.fr_py_ack.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.fr_py_ack.restype = ctypes.c_int
    lib.fr_py_escrow_deposit.argtypes = [ctypes.c_uint]
    lib.fr_py_escrow_deposit.restype = ctypes.c_int
    lib.fr_py_abort.argtypes = []
    lib.fr_py_abort.restype = ctypes.c_int
    lib.fr_py_poisoned_count.argtypes = []
    lib.fr_py_poisoned_count.restype = ctypes.c_uint


def load(path: str | None = None):
    """Load the substrate .so and set up signatures. Idempotent per path."""
    global _LIB, _LIB_PATH
    if path is None:
        path = find_substrate()
    if _LIB is not None and _LIB_PATH == path:
        return _LIB
    lib = ctypes.CDLL(path)
    _setup_signatures(lib)
    _LIB = lib
    _LIB_PATH = path
    return lib


def get() -> ctypes.CDLL:
    """Return the loaded library, loading the default search path first."""
    if _LIB is None:
        load()
    assert _LIB is not None
    return _LIB


def find_substrate() -> str:
    """Locate libforkrun_python.so.

    Search order: $FORKRUN_LIB, the package directory (co-located build),
    the repo root, the CWD.
    """
    env = os.environ.get("FORKRUN_LIB")
    if env:
        if not os.path.exists(env):
            raise FileNotFoundError(
                "FORKRUN_LIB=%r does not exist" % (env,))
        return env
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(pkg_dir, "libforkrun_python.so"),
        os.path.join(os.path.dirname(pkg_dir), "libforkrun_python.so"),
        os.path.join(os.path.dirname(os.path.dirname(pkg_dir)),
                     "libforkrun_python.so"),
        os.path.join(os.getcwd(), "libforkrun_python.so"),
        os.path.join(os.getcwd(), "python", "forkrun",
                     "libforkrun_python.so"),
    ]
    for cand in candidates:
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError(
        "libforkrun_python.so not found — run "
        "'make -f Makefile.substrate python-substrate'")

__all__ = ["FrPyBatch", "RC_OK", "RC_FAIL", "RC_EOF", "load", "get",
           "find_substrate"]
