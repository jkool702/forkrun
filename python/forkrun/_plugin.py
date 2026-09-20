"""Mode 3 (plugin): C callbacks via ctypes (W-PY9).

v0 calls plugin functions from Python through ctypes (~1-2us overhead per
call vs ~0.1us for the bash -C direct dispatch). v1 will add C-level
dispatch wrapping the engine's ring_call machinery.

ABI HONESTY NOTICE (load-bearing): the struct below is the v0
PYTHON-SIDE C-callback convention — it is NOT the frozen engine plugin
ABI (ring_loadables/forkrun_plugin.h, 128-byte forkrun_ctx with
batch_offset/fd_in/dialect negotiation). Real bash -C plugins are NOT
interchangeable with v0 Python plugins: the engine fills argv +
forkrun_ctx itself and captures stdout, while v0 passes an explicit
in/out buffer pair and captures the return code. Conflating the two
would silently miscompile one side's layout against the other, so the C
side is deliberately named struct fr_py_plugin_ctx (never forkrun_ctx)
and both sides pin the layout (C _Static_asserts + Python offset
asserts in test_plugin.py). v1 unifies the tiers by dispatching through
ring_call, at which point real .so plugins work from Python unchanged.
"""

from __future__ import annotations

import ctypes
import os

# v0 output buffer per worker: fixed 1MB, allocated lazily post-fork and
# reused across batches. Engine byte-mode batches clamp to min(L2, 1MB),
# so data_len > out_len is unreachable via engine batching (the plugin's
# -2 arm is strict `n > out_len` and stays green at exactly 1MB) —
# defense-in-depth, not a live path. Adaptive sizing is v1.
PLUGIN_OUTPUT_BUFFER_SIZE = 1024 * 1024


class PluginError(Exception):
    """Plugin loading or execution failure.

    Retriable through the existing escrow/retry/poison path (bash -E
    semantics), including known-fatal errors (missing file/function) —
    wasteful but correct in v0; fast-poison is a v1 optimization.
    """


class ForkrunCtx(ctypes.Structure):
    """v0 Python-side plugin context. MUST match struct fr_py_plugin_ctx
    in python/tests/plugins/test_plugin.c EXACTLY (explicit padding —
    no implicit-alignment dependence). Total 72 bytes.

    python/tests/test_plugin.py::TestPluginLayout pins every offset.
    """

    _fields_ = [
        ("data", ctypes.c_void_p),        #  0: input bytes (caller-owned)
        ("data_len", ctypes.c_uint64),    #  8: input length
        ("batch_idx", ctypes.c_uint64),   # 16: global batch index
        ("flags", ctypes.c_uint32),       # 24: reserved, must be 0 in v0
        ("_pad0", ctypes.c_uint32),       # 28: explicit pad
        ("out_buf", ctypes.c_void_p),     # 32: caller output buffer
        ("out_len", ctypes.c_uint64),     # 40: output capacity
        ("out_written", ctypes.c_uint64),  # 48: bytes written by plugin
        ("line_count", ctypes.c_uint64),  # 56: lines (0 = undefined)
        ("user_data", ctypes.c_void_p),   # 64: always NULL in v0
    ]


def load_plugin(path, function_name):
    """Dlopen a plugin .so and bind one function (parent-side, pre-fork).

    Dlopening without calling is fork-safe (no plugin state or threads
    exist yet); calls happen post-fork in workers. Returns (lib, func)
    with func typed as int (*)(ForkrunCtx *): 0 = success.
    Raises PluginError on missing file, load failure, or missing symbol.
    """
    if not isinstance(path, str) or not path:
        raise PluginError("plugin path must be a non-empty string, "
                          "got %r" % (path,))
    if not os.path.exists(path):
        raise PluginError("plugin not found: %s" % path)
    try:
        lib = ctypes.CDLL(path)
    except OSError as exc:
        raise PluginError("failed to load plugin %s: %s" % (path, exc))
    try:
        func = getattr(lib, function_name)
    except AttributeError:
        raise PluginError("plugin %s does not export %r"
                          % (path, function_name))
    func.restype = ctypes.c_int
    func.argtypes = [ctypes.POINTER(ForkrunCtx)]
    return lib, func


def make_plugin_payload(path, function_name):
    """Build a forkrun payload function around a C plugin entry point.

    Output buffer is allocated once per worker (lazily, post-fork) and
    reused. Input is copied once (create_string_buffer) — v0 copy cost,
    stated; zero-copy window passing is v1.
    """
    # func retains its CDLL (CPython _FuncPtr holds the library), so the
    # handle stays open for the payload's lifetime via this closure.
    _, func = load_plugin(path, function_name)
    output_buffer = None

    def plugin_payload(batch):
        nonlocal output_buffer
        if output_buffer is None:
            output_buffer = ctypes.create_string_buffer(
                PLUGIN_OUTPUT_BUFFER_SIZE)
        data = bytes(batch.data)  # v0: one copy out of the shared window
        in_buf = ctypes.create_string_buffer(data)
        ctx = ForkrunCtx()
        ctx.data = ctypes.cast(in_buf, ctypes.c_void_p)
        ctx.data_len = len(data)
        ctx.batch_idx = batch.batch_index
        ctx.flags = 0
        ctx.out_buf = ctypes.cast(output_buffer, ctypes.c_void_p)
        ctx.out_len = PLUGIN_OUTPUT_BUFFER_SIZE
        ctx.out_written = 0
        ctx.line_count = batch.line_count or 0
        ctx.user_data = None
        # in_buf/out_buf/ctx stay alive for the call duration via locals.
        rc = func(ctypes.byref(ctx))
        if rc != 0:
            raise PluginError(
                "plugin %s failed with code %d on batch %d"
                % (function_name, rc, batch.batch_index))
        n = ctx.out_written
        if n > PLUGIN_OUTPUT_BUFFER_SIZE:
            raise PluginError(
                "plugin %s overran output buffer (%d > %d)"
                % (function_name, n, PLUGIN_OUTPUT_BUFFER_SIZE))
        if n == 0:
            return None
        return bytes(output_buffer.raw[:n])

    plugin_payload._forkrun_plugin = (path, function_name)  # introspection
    return plugin_payload


__all__ = ["ForkrunCtx", "PluginError", "PLUGIN_OUTPUT_BUFFER_SIZE",
           "load_plugin", "make_plugin_payload"]
