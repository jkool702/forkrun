"""ctypes bindings for the Python-facing substrate shim (W-PY1).

The shared object is built by ``make -f Makefile.substrate python-substrate``
from ``python/forkrun/_shim.c`` (which textually includes the engine TU, so
all fr_py_* entry points below are real exports; the engine's own
ring_*_main helpers stay static and are NOT bound here).

Guardrails: fork before threads (load in the parent before forking workers
is fine — the .so carries no thread state; payload native imports happen
post-fork in the worker). No pickle, no bash, no argv vectors anywhere.

GIL note (W-PY16 addendum): ctypes.CDLL releases the GIL during calls
(unlike PyDLL), so a blocking fr_py_* call never starves other Python
threads — but the design avoids the question anyway (scanner and reaper
run as separate processes, never as threads around a blocking call).
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
    try:
        # W-PY18: C splice worker loop (claim→sendfile→signal→ack).
        lib.fr_py_worker_splice_loop.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int]
        lib.fr_py_worker_splice_loop.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        # W-PY18 addendum: kernel copy src[src_off,+len)→dst[dst_off)
        # (copy_file_range, then sendfile; -1 = use userspace loop).
        lib.fr_py_copy_range.argtypes = [
            ctypes.c_int, ctypes.c_uint64, ctypes.c_int,
            ctypes.c_uint64, ctypes.c_uint64]
        lib.fr_py_copy_range.restype = ctypes.c_int64
    except AttributeError:
        pass
    try:
        # W-PY18 addendum: borrowed MAP_SHARED window pointer.
        lib.fr_py_get_raw_window.argtypes = [
            ctypes.c_int, ctypes.c_uint64, ctypes.c_uint64]
        lib.fr_py_get_raw_window.restype = ctypes.c_void_p
    except AttributeError:
        pass
    try:
        # W-PY16: published-DATA-batch count (worker fork timing).
        lib.fr_py_data_ready.argtypes = []
        lib.fr_py_data_ready.restype = ctypes.c_uint64
    except AttributeError:
        pass
    try:
        # W-PY19: worker-local order-pipe fd for ordered acks.
        lib.fr_py_set_order_pipe.argtypes = [ctypes.c_int]
        lib.fr_py_set_order_pipe.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        # W-PY19: spawn-aware scan (scanner → reactor spawn pipe).
        lib.fr_py_scan_with_spawn.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.fr_py_scan_with_spawn.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        # W-PY19: C-level orderer (ring_order_main in a forked child).
        lib.fr_py_orderer.argtypes = [ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int]
        lib.fr_py_orderer.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        # W-PY21: NUMA-aware init (--numa-map topology).
        lib.fr_py_init_numa.argtypes = [ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_char_p]
        lib.fr_py_init_numa.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        # W-PY21: NUMA pipeline stages (ingest/indexer/scanner/fallow).
        lib.fr_py_numa_ingest.argtypes = [ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int]
        lib.fr_py_numa_ingest.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        lib.fr_py_indexer_numa.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.fr_py_indexer_numa.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        lib.fr_py_numa_scanner.argtypes = [ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int]
        lib.fr_py_numa_scanner.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        lib.fr_py_fallow_phys.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.fr_py_fallow_phys.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        # W-PY21: per-node published-DATA-batch count.
        lib.fr_py_data_ready_node.argtypes = [ctypes.c_int]
        lib.fr_py_data_ready_node.restype = ctypes.c_uint64
    except AttributeError:
        pass
    try:
        # W-PY21: NUMA ingest-EOF-posted query (helper classification).
        lib.fr_py_ingest_eof_posted.argtypes = []
        lib.fr_py_ingest_eof_posted.restype = ctypes.c_int
    except AttributeError:
        pass
    try:
        # W-PY21-A: C drain process (data/control path separation).
        lib.fr_py_drain_loop.argtypes = [ctypes.c_int,
                                         ctypes.POINTER(ctypes.c_int),
                                         ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int]
        lib.fr_py_drain_loop.restype = ctypes.c_int
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
        return {"exec": False, "plugin": False, "emit": False,
                "splice": False}
    return {"exec": hasattr(lib, "fr_py_exec_spawn"),
            "plugin": hasattr(lib, "fr_py_plugin_call"),
            "emit": hasattr(lib, "fr_py_emit"),
            "splice": hasattr(lib, "fr_py_worker_splice_loop"),
            "orderer": hasattr(lib, "fr_py_orderer"),
            "order_pipe": hasattr(lib, "fr_py_set_order_pipe"),
            "scan_spawn": hasattr(lib, "fr_py_scan_with_spawn"),
            "numa": all(hasattr(lib, s) for s in (
                "fr_py_init_numa", "fr_py_numa_ingest",
                "fr_py_indexer_numa", "fr_py_numa_scanner",
                "fr_py_fallow_phys", "fr_py_data_ready_node",
                "fr_py_ingest_eof_posted")),
            "drain": hasattr(lib, "fr_py_drain_loop")}
