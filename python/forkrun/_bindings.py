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
    # W-PY13 v1 fast paths (optional: absent on pre-v1 substrates — the
    # worker falls back to v0 subprocess/ctypes dispatch). Guarded per
    # symbol so a partial substrate never breaks signature setup.
    try:
        lib.fr_py_exec_spawn.argtypes = [
            ctypes.POINTER(ctypes.c_char_p), ctypes.c_int,
            ctypes.c_uint64, ctypes.c_uint64,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint64]
        lib.fr_py_exec_spawn.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        lib.fr_py_plugin_call.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_int, ctypes.c_int,
            ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int, ctypes.c_int]
        lib.fr_py_plugin_call.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        # W-PY14: C-level output emit (header + data via writev, signal).
        lib.fr_py_emit.argtypes = [
            ctypes.c_int, ctypes.c_int,
            ctypes.c_uint64, ctypes.c_uint64,
            ctypes.c_char_p, ctypes.c_uint64]
        lib.fr_py_emit.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        # W-PY16: fallow reaper (IndexPacket pipe → punch-hole memfd).
        lib.fr_py_fallow_loop.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.fr_py_fallow_loop.restype = ctypes.c_int
    except AttributeError:
        pass


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
           "find_substrate", "v1_available"]


def v1_available(lib=None) -> dict:
    """W-PY13: which C-level fast paths the loaded substrate offers.

    Returns {"exec": bool, "plugin": bool}. Missing symbols (pre-v1
    .so) read as False — the worker then uses the v0 subprocess/ctypes
    dispatch. Respects the FORKRUN_NO_V1 kill switch (test escape hatch
    + operator override: forces v0 even when the symbols exist).
    """
    if lib is None:
        lib = get()
    if os.environ.get("FORKRUN_NO_V1"):
        return {"exec": False, "plugin": False, "emit": False}
    return {"exec": hasattr(lib, "fr_py_exec_spawn"),
            "plugin": hasattr(lib, "fr_py_plugin_call"),
            "emit": hasattr(lib, "fr_py_emit")}
