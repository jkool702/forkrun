"""Forked Python worker (W-PY1, Stage 4 Phase 1).

Runs ONLY in the child after os.fork(). Never returns — always os._exit().
No native payload imports here; the payload (or its module, for "pkg:fn"
specs) is imported/called in this process, post-fork.

Loop (bash -E semantics, same-process retry variant documented in run.py):
  claim -> Batch over the shared memfd mmap -> payload -> [sink] ->
  invalidate (finally) -> flush -> ack(-1,-1).
Exception -> escrow deposit (kills+1) + continue (retry), or skip (ack and
continue), or fail-fast (global abort + _exit(1)). Poisoned batches
(kills >= limit) are skipped with a stderr warning and acked.
EOF (rc 2) -> clean exit 0. FAILURE (rc 1, e.g. global abort) -> exit 1.

SINGLE-THREADED CONTRACT (v0):
The payload runs single-threaded. Spawning threads inside the payload is
unsupported: a thread holding a Batch memoryview past invalidation makes
that view's lifetime unenforceable (Layer 3 UB-by-contract — the worker
os._exit()s without joining anything). If a batch needs inner parallelism,
return its bytes and parallelize in the parent. A payload that violates
the contract gets a RuntimeWarning at ack time (checked, not prevented).
"""

from __future__ import annotations

import mmap
import os
import struct
import sys
import threading
import traceback
import warnings

from ._bindings import RC_EOF, RC_FAIL, RC_OK, FrPyBatch, get
from ._batch import Batch

_HDR = struct.Struct("<QQ")  # batch_idx u64, payload length u64


def _flush() -> None:
    """Flush payload-facing buffered streams (F-PY1 standing rule: flush
    before ack — os._exit() skips interpreter cleanup, so unflushed
    buffered output would be lost). Best-effort; never raises."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass


def _ack(lib) -> int:
    """Thread-guard + flush + ack. The single ack funnel: every ack site
    warns on contract violation and flushes before acking."""
    if threading.active_count() > 1:
        try:
            warnings.simplefilter("always", RuntimeWarning)
            warnings.warn(
                "Payload spawned threads — the v0 single-threaded contract "
                "is violated. Memoryview references held by threads past "
                "invalidation are UB-by-contract.",
                RuntimeWarning, stacklevel=2)
        except Exception:
            pass
    _flush()
    return lib.fr_py_ack(-1, -1)


def _write_all(fd, buf) -> None:
    view = memoryview(buf)
    while view:
        n = os.write(fd, view)
        view = view[n:]


def _resolve_payload(spec):
    """Resolve the payload spec IN THE WORKER (post-fork).

    "pkg.mod:func" -> import here (keeps the parent virgin of native
    threadpool imports — the fork-safety mechanism). Callables pass through
    via fork-inherited memory (never pickled).
    """
    if isinstance(spec, str):
        mod_name, _, func_name = spec.partition(":")
        if not mod_name or not func_name:
            raise ValueError(
                "payload string must be 'pkg.mod:func', got %r" % (spec,))
        import importlib

        mod = importlib.import_module(mod_name)
        fn = getattr(mod, func_name)
        if not callable(fn):
            raise TypeError(
                "payload %r is not callable" % (spec,))
        return fn
    if not callable(spec):
        raise TypeError("payload must be 'pkg.mod:func' or callable")
    return spec


def _coerce_result(ret):
    """Payload return -> bytes (None = no output)."""
    if ret is None:
        return None
    if isinstance(ret, bytes):
        return ret
    if isinstance(ret, (bytearray, memoryview)):
        return bytes(ret)
    if isinstance(ret, str):
        return ret.encode("utf-8")
    raise TypeError(
        "payload must return bytes/memoryview/str/None, got %s"
        % type(ret).__name__)


def worker_main(wid, payload_spec, sink_spec, memfd_fd, file_size,
                out_fd, on_error):
    """Child entry point. Never returns.

    out_fd: parent-created output memfd inherited across fork (W-PY3
      emitter transport; None discards results). The worker writes ONLY
      this fd — never shared between workers. Copy-on-return: payload
      bytes are copied into the memfd (stated v0 cost; write-in-place
      OutputBatch is demand-pulled Stage 6+).
    """
    code = 1
    try:
        code = _run(wid, payload_spec, sink_spec, memfd_fd, file_size,
                    out_fd, on_error)
    except BaseException:
        try:
            traceback.print_exc()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass
        code = 1
    finally:
        os._exit(code)


def _run(wid, payload_spec, sink_spec, memfd_fd, file_size, out_fd,
         on_error):
    lib = get()
    payload_fn = _resolve_payload(payload_spec)
    sink_fn = _resolve_payload(sink_spec) if sink_spec is not None else None

    if lib.fr_py_worker_init(wid, 0, 0, 3, 0) != 0:
        return 1

    mm = None
    view = None
    if file_size > 0:
        mm = mmap.mmap(memfd_fd, file_size, access=mmap.ACCESS_READ)
        view = memoryview(mm)

    try:
        while True:
            claimed = FrPyBatch()
            rc = lib.fr_py_claim(claimed)
            if rc == RC_EOF:
                return 0
            if rc != RC_OK:
                return 1

            if claimed.poisoned:
                try:
                    msg = ("forkrun [WARN]: Skipping poisoned batch %d "
                           "(killed %d times).\n"
                           % (claimed.batch_idx, claimed.num_kills))
                    os.write(2, msg.encode())
                except OSError:
                    pass
                if _ack(lib) != 0:
                    return 1
                continue

            if claimed.length == 0:
                # EOF sentinel slot (scanner publishes lines=0/len=0 past
                # the last byte). Bash parity: `if REPLY != 0` skips the
                # payload but still acks. Never delivered to Python.
                if _ack(lib) != 0:
                    return 1
                continue

            line_count = (claimed.lines if claimed.lines > 0 else None)
            batch = Batch.from_window(
                claimed.batch_idx, claimed.offset, claimed.length,
                line_count, view if view is not None else memoryview(b""))
            if file_size == 0:
                # Degenerate: zero-length input still claims nothing; the
                # loop above already EOFs. This branch is unreachable but
                # kept explicit so a 0-byte file cannot spin.
                batch.invalidate()
                if _ack(lib) != 0:
                    return 1
                continue

            error = None
            try:
                ret = payload_fn(batch)
                if sink_fn is not None:
                    import types

                    meta = types.SimpleNamespace(
                        batch_index=batch.batch_index,
                        byte_offset=batch.byte_offset,
                        byte_length=batch.byte_length,
                        line_count=batch.line_count,
                        num_kills=claimed.num_kills)
                    sink_fn(meta, ret)
                blob = _coerce_result(ret)
                if blob is not None and out_fd is not None:
                    _write_all(out_fd, _HDR.pack(batch.batch_index,
                                                 len(blob)))
                    if blob:
                        _write_all(out_fd, blob)
            except BaseException as exc:  # noqa: BLE001
                error = exc
            finally:
                try:
                    batch.invalidate()
                except Exception:
                    pass

            if error is None:
                if _ack(lib) != 0:
                    return 1
                continue

            # --- failure path (bash -E analogue) ---
            if on_error == "skip":
                if _ack(lib) != 0:
                    return 1
                continue
            if on_error == "fail-fast":
                _flush()
                lib.fr_py_abort()
                return 1
            # Default "retry": escrow with kills+1, no ack (the next claim
            # overwrites the TLS the deposit left armed), same-process retry
            # when this worker re-claims the deposited batch.
            _flush()
            lib.fr_py_escrow_deposit(claimed.num_kills + 1)
            continue
    finally:
        if out_fd is not None:
            try:
                os.close(out_fd)
            except OSError:
                pass
        # NOTE: the shared mmap stays open until _exit (pages must remain
        # valid for any in-flight exported views; Layer 3 UB otherwise).
