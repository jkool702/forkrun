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
return its bytes and parallelize in the parent. The contract is documented,
not policed at runtime (W-PY21-B deleted the per-batch thread check —
a startup check would observe nothing, and payload-created threads are
the caller's UB, same as Layer 3 numpy UB).
"""

from __future__ import annotations

import mmap
import os
import struct
import sys
import traceback

from ._bindings import RC_EOF, RC_FAIL, RC_OK, FrPyBatch, get, v1_available
from ._batch import Batch
from ._plugin import PluginError
from ._spawn import SpawnError

_HDR = struct.Struct("<QQ")  # batch_idx u64, payload length u64
# v1 streaming signal: (worker_id u64, batch_idx u64). Indices only — never
# payload bytes (<= PIPE_BUF, so one write is atomic across workers).
_SIG = struct.Struct("<QQ")


def _flush() -> None:
    """Flush payload-facing buffered streams (F-PY1 standing rule: flush
    before ack — os._exit() skips interpreter cleanup, so unflushed
    buffered output would be lost). Best-effort; never raises."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass


def _cloexec_all() -> None:
    """Mark every fd > 2 close-on-exec (W-PY13 v1 hygiene).

    posix_spawn'd children must start with ONLY the dup2'd stdio (0/1):
    inheriting the signal pipe write end, escrow/eventfds, or sibling
    output memfds would let a daemonizing/long-lived command pin the
    parent's EOF detection or leak engine fds. This is the v1 analogue
    of subprocess close_fds=True (which already covers the v0 path).
    CLOEXEC affects exec only — fork inheritance (memfds, pipes, mmaps
    the worker itself uses) is untouched. Best-effort; never raises.
    """
    try:
        try:
            fds = [int(n) for n in os.listdir("/proc/self/fd")]
        except (OSError, ValueError):
            fds = list(range(3, 256))
        for fd in fds:
            if fd > 2:
                try:
                    os.set_inheritable(fd, False)
                except OSError:
                    pass
    except Exception:
        pass


def _ack(lib, fallow_fd=-1, target_fd=-1) -> int:
    """Flush + ack. The single ack funnel for the pre-W-PY21-B paths.

    W-PY21-B: the per-batch thread-count check is DELETED
    (addendum Option A — the single-threaded contract is documented,
    not policed; a startup check would observe nothing since workers
    are born single-threaded, and payload-created threads are the
    user's UB). _flush() stays: payload print() output would be lost
    to os._exit() without it. Prefers fr_py_ack_direct (no argv)
    when the substrate offers it, else the legacy fr_py_ack.

    fallow_fd: W-PY16 streaming-ingest write end (parent-created,
    inherited). >= 0 publishes the acked IndexPacket to the fallow
    reaper (hole-punch behind the contiguous prefix → bounded ingress);
    -1 is the materialized-path disarm (no reaper exists).
    target_fd: W-PY19 C-orderer target (>= 0 emits an OrderPacket for
    the bytes appended since the last ack; -1 disarms, the v0 default).
    """
    _flush()
    ack_direct = getattr(lib, "fr_py_ack_direct", None)
    if ack_direct is not None:
        try:
            return ack_direct(fallow_fd, target_fd)
        except Exception:
            pass
    return lib.fr_py_ack(fallow_fd, target_fd)


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
                out_fd, signal_w, on_error, fallow_fd=None):
    """Child entry point. Never returns.

    out_fd: parent-created output memfd inherited across fork (W-PY3
      emitter transport; None discards results). The worker writes ONLY
      this fd — never shared between workers. Copy-on-return: payload
      bytes are copied into the memfd (stated v0 cost; write-in-place
      OutputBatch is demand-pulled Stage 6+).
    signal_w: parent-created signal pipe write end (W-PY6 v1 streaming;
      None for the v0.5 post-completion drain). After each record write
      the worker emits one 16-byte (wid, batch_idx) signal — indices
      only, never payload bytes. A blocked signal write IS the
      backpressure mechanism (pipe full => consumer slow); EPIPE means
      the parent abandoned the stream => fatal worker exit (reaped).
    file_size: ingress size at fork; -1 (W-PY16) means streaming/unknown
      — the worker grows its MAP_SHARED view as claims advance instead
      of mapping once.
    fallow_fd: W-PY16 reaper write end (or None to disarm). Acked
      IndexPackets flow here; the reaper punches holes behind the
      contiguous prefix, bounding ingress memory.
    """
    code = 1
    try:
        code = _run(wid, payload_spec, sink_spec, memfd_fd, file_size,
                    out_fd, signal_w, on_error, fallow_fd)
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


def _trap_ack_notify(trap_ack_w, msg) -> None:
    """Best-effort write of one trap-ACK line (W-PY19).

    trap_ack_w is the reactor pipe write end (or None/-1 to disarm).
    Never raises: the parent may be gone (abandoned run) and the
    worker must not turn a dead pipe into a second failure.
    """
    if trap_ack_w is None or trap_ack_w < 0:
        return
    try:
        if isinstance(msg, str):
            msg = msg.encode()
        view = memoryview(msg)
        while view:
            n = os.write(trap_ack_w, view)
            view = view[n:]
    except OSError:
        pass
    except Exception:
        pass


def _run(wid, payload_spec, sink_spec, memfd_fd, file_size, out_fd,
         signal_w, on_error, fallow_fd=None, trap_ack_w=None,
         order_target=-1, wincarn=0, node=0):
    lib = get()
    payload_fn = _resolve_payload(payload_spec)
    sink_fn = _resolve_payload(sink_spec) if sink_spec is not None else None
    fallow_w = fallow_fd if fallow_fd is not None else -1
    trap_w = trap_ack_w if trap_ack_w is not None else -1
    # W-PY19 C-orderer target: ack(target) emits an OrderPacket for the
    # bytes appended since the last ack. Armed only when the caller set
    # the order pipe AND an output memfd exists to name in the packet.
    # order_target carries the ORDER PIPE fd here (or -1); the ack
    # target is out_fd whenever ordered. See worker_main_with_death_pipe.
    order_pipe = order_target if (order_target is not None and
                                  order_target >= 0 and
                                  out_fd is not None) else -1
    order_tgt = out_fd if order_pipe >= 0 else -1

    if lib.fr_py_worker_init(wid, node, wincarn, 3, 0) != 0:
        return 1
    if order_pipe >= 0:
        try:
            lib.fr_py_set_order_pipe(order_pipe)
        except Exception:
            pass
    # W-PY13 v1 fast-path detection (once per worker). The factories tag
    # their closures (spawn: _forkrun_spawn_argv, plugin: _forkrun_plugin);
    # when the tag AND the C symbol are present (and a sink isn't stealing
    # the output, and an output memfd exists to frame into), the claim loop
    # below bypasses Python dispatch entirely: batch bytes stay in the
    # shared memfd (zero-copy input), C frames the record, Python only
    # signals + acks. Otherwise the v0 Batch path runs unchanged.
    _v1 = v1_available(lib)
    _spawn_argv = getattr(payload_fn, "_forkrun_spawn_argv", None)
    _plugin_spec = getattr(payload_fn, "_forkrun_plugin", None)
    use_v1_spawn = (_spawn_argv is not None and sink_fn is None and
                    out_fd is not None and _v1["exec"])
    # _forkrun_plugin_v1 (probed in the parent by make_plugin_payload):
    # only dialect-1/2 plugins take the C path. A missing tag (or False)
    # means the v0 72B convention — never guess (a 72B entry point and a
    # legacy 2-arg entry point are symbol-indistinguishable).
    use_v1_plugin = (not use_v1_spawn and _plugin_spec is not None and
                     getattr(payload_fn, "_forkrun_plugin_v1", False) and
                     sink_fn is None and out_fd is not None and
                     _v1["plugin"])
    argv_c = None
    if use_v1_spawn:
        import ctypes as _ctypes

        _argv_b = [(a.encode("utf-8") if isinstance(a, str) else bytes(a))
                   for a in list(_spawn_argv)]
        argv_c = (_ctypes.c_char_p * (len(_argv_b) + 1))(*_argv_b, None)
    # W-PY14: C-level output emit. Active whenever results are collected
    # (out_fd present) and the symbol exists — orthogonal to the spawn/
    # plugin dispatch above (those frame inside C and never reach the
    # output block below). One ctypes call replaces header pack + two
    # writes + signal pack/write; bytes returns pass their internal
    # buffer pointer (zero-copy). FORKRUN_NO_V1 forces the v0 path.
    use_emit = out_fd is not None and _v1["emit"]
    if use_v1_spawn or use_v1_plugin:
        _cloexec_all()

    # W-PY21-B: batch commit primitive (fr_py_complete = emit + signal
    # + fallow + order + ack in one C call). Active whenever the
    # substrate offers it; FORKRUN_NO_V1 forces the legacy split path
    # below. _success/_ack stay for the fallback and the ack-only
    # paths (skip/deposit carry no output and never signal).
    use_complete = bool(_v1.get("complete", False))
    _sig_w = signal_w if signal_w is not None else -1
    _out = out_fd if out_fd is not None else -1
    # Bind once: CDLL attribute access must not sit in the per-batch
    # path (a fresh FuncPtr per lookup).
    _complete_fn = lib.fr_py_complete if use_complete else None

    def _commit(bidx, blob):
        """Output + signal + ack (v0 success path). Flushes first
        (flush-before-ack invariant — payload print() would be lost
        to os._exit() otherwise). Returns 0 ok, -1 output failure
        (rides escrow like a Python write error), -2 signal failure
        (fatal infrastructure), -3 ack failure (fatal, v0 parity)."""
        _flush()
        return _complete_fn(
            _sig_w, wid, bidx, fallow_w, _out,
            blob, len(blob) if blob is not None else 0)

    def _commit_recorded(bidx):
        """Signal + ack, no output (v1 spawn/plugin success: C already
        framed the record into out_fd). Any nonzero rc is fatal
        (v0 parity with _success False)."""
        _flush()
        return _complete_fn(
            _sig_w, wid, bidx, fallow_w, _out, None, 0)

    def _commit_silent(bidx):
        """Ack only (poison/sentinel: no record emitted, hence no
        signal — v0 parity). _out is still passed so ordered mode
        emits the empty OrderPacket the C orderer expects (same as
        the old ack(fallow_w, order_tgt)). Returns 0 ok, else fatal.
        """
        return _complete_fn(-1, wid, bidx, fallow_w, _out,
                            None, 0)

    def _success(bidx):
        """Signal (indices only) + ack. Shared by v0 and v1 paths."""
        if out_fd is not None and signal_w is not None:
            try:
                _write_all(signal_w, _SIG.pack(wid, bidx))
            except OSError:
                return False  # parent gone (abandoned stream)
        return _ack(lib, fallow_w, order_tgt) == 0

    streaming = file_size is not None and file_size < 0
    mm = None
    view = None
    mapped = 0
    if not streaming and file_size > 0:
        mm = mmap.mmap(memfd_fd, file_size, access=mmap.ACCESS_READ)
        view = memoryview(mm)
        mapped = file_size

    def _ensure_mapped(need):
        """Grow the MAP_SHARED ingress view to cover [0, need) (W-PY16).

        Streaming ingest grows the memfd after fork, so the worker maps
        geometrically (1MB floor, doubling) instead of once. Runs
        BETWEEN batches only: no Batch views are live here (the previous
        batch was invalidated before ack), so replacing the mapping via
        close + re-mmap is safe — same ordering rule the engine's
        ring_call_ensure_ingress_map relies on. Punched (fallow)
        prefixes are never re-read: only unacked windows are mapped
        into Batches, and hole reads zero-fill regardless.
        Returns True mapped, False on failure (fatal: the claim names
        bytes the engine published, so this is unreachable in practice).
        """
        nonlocal mm, view, mapped
        if need <= mapped:
            return True
        # CPython refuses mmap() past EOF (ValueError), unlike raw
        # mmap(2) — so growth clamps to the current file size. need is
        # always <= fstat size (the scanner publishes only written
        # bytes); otherwise fail loud, never silently short.
        try:
            cur = os.fstat(memfd_fd).st_size
        except OSError:
            return False
        size = mapped * 2 if mapped else (1 << 20)
        while size < need:
            size *= 2
        if size > cur:
            size = cur
        if size < need:
            return False
        try:
            if mm is not None:
                try:
                    view.release()
                except (ValueError, BufferError, AttributeError):
                    pass
                view = None
                mm.close()
                mm = None
            mm = mmap.mmap(memfd_fd, size, access=mmap.ACCESS_READ)
            view = memoryview(mm)
            mapped = size
            return True
        except (OSError, ValueError, BufferError):
            # BufferError: the payload leaked a view past invalidate
            # (Layer 3) and the old mapping can't close — fail loud
            # (worker exit 1 → parent RuntimeError), never silently
            # short. OSError/ValueError: mapping itself failed.
            return False

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
                # W-PY19: poison notification to the reactor (bash
                # "P:idx:kills" on the trap-ACK pipe). Best effort.
                _trap_ack_notify(
                    trap_w, "P:%d:%d\n" % (claimed.batch_idx,
                                           claimed.num_kills))
                if use_complete:
                    if _commit_silent(claimed.batch_idx) != 0:
                        return 1
                elif _ack(lib, fallow_w, order_tgt) != 0:
                    return 1
                continue

            if claimed.length == 0:
                # EOF sentinel slot (scanner publishes lines=0/len=0 past
                # the last byte). Bash parity: `if REPLY != 0` skips the
                # payload but still acks. Never delivered to Python.
                if use_complete:
                    if _commit_silent(claimed.batch_idx) != 0:
                        return 1
                elif _ack(lib, fallow_w, order_tgt) != 0:
                    return 1
                continue

            line_count = (claimed.lines if claimed.lines > 0 else None)
            if streaming:
                # Unknown size at fork: grow the shared view to cover
                # this claim (between-batch remap — no live views).
                if not _ensure_mapped(claimed.offset + claimed.length):
                    return 1
            if use_v1_spawn or use_v1_plugin:
                # v1: C-level dispatch (no Batch, no Python copy — the
                # input window stays in the shared memfd; C already framed
                # the record into out_fd). Flush BEFORE the call: fd 1 may
                # be redirected by the plugin capture, so buffered Python
                # output must land first (else it leaks into the record).
                _flush()
                error = None
                if use_v1_spawn:
                    rc = lib.fr_py_exec_spawn(
                        argv_c, len(argv_c) - 1,
                        claimed.offset, claimed.length,
                        memfd_fd, out_fd, claimed.batch_idx)
                    if rc == 0:
                        if use_complete:
                            if _commit_recorded(claimed.batch_idx) != 0:
                                return 1
                        elif not _success(claimed.batch_idx):
                            return 1
                        continue
                    if rc < 0:
                        # Pipe/framing/wait failure: the worker's own
                        # transport is broken (retry cannot fix it), and
                        # the partial record was truncated in C — fatal
                        # rather than a silently short stream.
                        return 1
                    error = SpawnError(
                        "command %r exited with %d on batch %d" % (
                            list(_spawn_argv), rc, claimed.batch_idx))
                else:
                    _ppath, _pfunc = _plugin_spec
                    rc = lib.fr_py_plugin_call(
                        _ppath.encode("utf-8"), _pfunc.encode("utf-8"),
                        memfd_fd, out_fd,
                        claimed.offset, claimed.length, claimed.batch_idx,
                        claimed.lines, claimed.num_kills, wid, 0)
                    if rc == 0:
                        if use_complete:
                            if _commit_recorded(claimed.batch_idx) != 0:
                                return 1
                        elif not _success(claimed.batch_idx):
                            return 1
                        continue
                    # Negative (dl/capture/tokenize failure) rides the
                    # retry path too (v0 "wasteful but correct" doctrine:
                    # bounded retries, then poison with warnings — never
                    # a silent drop, never a whole-run abort for one
                    # batch's failure). Only a dead signal pipe (_success
                    # False above) is fatal infrastructure.
                    error = PluginError(
                        "plugin %s failed with code %d on batch %d" % (
                            _pfunc, rc, claimed.batch_idx))
                # --- failure path (bash -E analogue, shared with v0) ---
                if on_error == "skip":
                    if _ack(lib, fallow_w, order_tgt) != 0:
                        return 1
                    continue
                if on_error == "fail-fast":
                    _flush()
                    lib.fr_py_abort()
                    return 1
                _flush()
                lib.fr_py_escrow_deposit(claimed.num_kills + 1)
                continue
            batch = Batch.from_window(
                claimed.batch_idx, claimed.offset, claimed.length,
                line_count, view if view is not None else memoryview(b""))
            if file_size == 0:
                # Degenerate: zero-length input still claims nothing; the
                # loop above already EOFs. This branch is unreachable but
                # kept explicit so a 0-byte file cannot spin.
                batch.invalidate()
                if use_complete:
                    if _commit_silent(batch.batch_index) != 0:
                        return 1
                elif _ack(lib, fallow_w, order_tgt) != 0:
                    return 1
                continue

            error = None
            emit_rc = None
            blob = None
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
                if use_complete:
                    # W-PY21-B: fast-type fast path (None/bytes pass
                    # straight through — no extra call); anything else
                    # coerces once with validation preserved. The
                    # single C call below does output + signal + ack.
                    # Flush happens inside _commit.
                    if ret is None or isinstance(ret, bytes):
                        blob = ret
                    else:
                        blob = _coerce_result(ret)
                elif use_emit:
                    # W-PY14: one C call replaces header pack + two
                    # writes + signal pack/write. bytes pass their
                    # internal buffer (zero-copy); anything else is
                    # coerced once (validation + conversion preserved).
                    # signal_w None (map/run) → -1 → signal skipped.
                    if ret is None:
                        data, data_len = None, 0
                    elif isinstance(ret, bytes):
                        data, data_len = ret, len(ret)
                    else:
                        blob = _coerce_result(ret)
                        if blob is None:
                            data, data_len = None, 0
                        else:
                            data, data_len = blob, len(blob)
                    emit_rc = lib.fr_py_emit(
                        out_fd, signal_w if signal_w is not None else -1,
                        wid, batch.batch_index, data, data_len)
                else:
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
                if use_complete:
                    # W-PY21-B: ONE C CALL — output + signal + fallow
                    # + order + ack (flush-before-complete inside).
                    # -2/-3 are fatal infrastructure (v0 parity with
                    # _success False); -1 rides the escrow failure
                    # path like a Python write error.
                    comp_rc = _commit(batch.batch_index, blob)
                    if comp_rc == 0:
                        continue
                    if comp_rc == -2 or comp_rc == -3:
                        return 1
                    error = OSError(
                        "forkrun: output write failed on batch %d"
                        % batch.batch_index)
                elif emit_rc is not None:
                    # C emit path: output (+ signal, unless map/run)
                    # already done. -2 (signal) is fatal infrastructure
                    # (v0 parity); other nonzero (output) rides the
                    # shared failure path like a Python write error.
                    if emit_rc == -2:
                        return 1
                    if emit_rc != 0:
                        error = OSError(
                            "forkrun: output write failed on batch %d"
                            % batch.batch_index)
                    elif _ack(lib, fallow_w, order_tgt) != 0:
                        return 1
                    else:
                        continue
                else:
                    # v1 streaming signal (indices only) goes out AFTER the
                    # record bytes are visible and BEFORE ack: a worker blocked
                    # here holds an unacked batch, which is exactly the
                    # backpressure the hydraulic loop needs. Outside the payload
                    # try — a signal failure is infrastructure, never escrowed.
                    if not _success(batch.batch_index):
                        return 1
                    continue

            # --- failure path (bash -E analogue) ---
            if on_error == "skip":
                if _ack(lib, fallow_w, order_tgt) != 0:
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


_ON_ERROR_CODES = {"retry": 0, "skip": 1, "fail-fast": 2}


def _c_plugin_spec(payload_fn):
    """Extract the (path, func) frozen-ABI plugin spec from a coerced
    plugin payload closure (W-PY26).

    Returns (path, func) when the closure carries a dialect-1/2
    _forkrun_plugin marker (C-loop eligible), else None. v0 72B
    conventions (no forkrun_use_ctx) are NOT eligible — the C loop
    speaks only the frozen engine ABI.
    """
    spec = getattr(payload_fn, "_forkrun_plugin", None)
    if not spec:
        return None
    if not getattr(payload_fn, "_forkrun_plugin_v1", False):
        return None
    if not isinstance(spec, (tuple, list)) or len(spec) != 2:
        return None
    path, func = spec
    if not isinstance(path, str) or not path:
        return None
    if not isinstance(func, str) or not func:
        return None
    return (path, func)


def _fork_c_plugin_worker(lib, wid, plugin_path, plugin_func, memfd_fd,
                           out_fd, signal_w, fallow_w, engine_fds,
                           on_error="retry"):
    """Fork one C-loop plugin worker (W-PY26 mode="plugin" fast path).

    The child scrubs to engine + job fds, then runs
    fr_py_worker_plugin_loop to EOF: claim → plugin → signal → ack
    with zero Python per batch. Returns the child pid in the parent;
    the child never returns (os._exit with the loop rc mapped to
    0/1 — the parent's failed-check treats nonzero as failure).
    signal_w/fallow_w may be None (→ -1 disarm, map/materialized).
    out_fd must be a parent-created output memfd (never None: the
    C loop always frames records for the parent to parse).
    on_error rides the same codes as the Python worker (retry/skip/
    fail-fast); v0 72B plugins must never reach here (gate on
    _c_plugin_spec first).
    """
    pid = os.fork()
    if pid == 0:
        try:
            keep = set(engine_fds) | {memfd_fd, out_fd}
            if signal_w is not None:
                keep.add(signal_w)
            if fallow_w is not None and fallow_w >= 0:
                keep.add(fallow_w)
            from ._fd_scrub import scrub_fds
            scrub_fds(keep)
        except Exception:
            pass
        try:
            rc = lib.fr_py_worker_plugin_loop(
                wid,
                plugin_path.encode("utf-8")
                if isinstance(plugin_path, str) else plugin_path,
                plugin_func.encode("utf-8")
                if isinstance(plugin_func, str) else plugin_func,
                memfd_fd, out_fd,
                signal_w if signal_w is not None else -1,
                fallow_w if fallow_w is not None else -1,
                -1, -1, 0, 3,
                _ON_ERROR_CODES.get(on_error, 0))
        except BaseException:
            rc = 1
        os._exit(0 if rc == 0 else 1)
    return pid


def worker_main_with_death_pipe(wid, node, payload_spec, sink_spec,
                                memfd_fd, file_size, out_fd, signal_w,
                                death_r, death_w, trap_ack_w, on_error,
                                fallow_fd=None, order_w=None,
                                wincarn=0):
    """Reactor-managed worker entry point (W-PY19). Never returns.

    Same claim/payload/ack loop as worker_main (via _run), plus the
    bash EXIT-trap equivalent:

    death_r/death_w: this worker's death pipe. The parent holds
      death_r and polls it; the child closes death_r immediately and
      holds death_w until exit — the kernel then closes it, which the
      parent observes as readable EOF (POLLHUP equivalent). death_r
      None (or < 0) disarms; death_w None disarms the close.
    trap_ack_w: reactor trap-ACK pipe write end (or None/-1 to
      disarm). Non-zero exit writes one "wid\\n" line (graceful
      failure confirmation); poisoned batches already notified inline
      as "P:idx:kills" by _run. Best effort, never raises.
    order_w: C-orderer pipe write end (or None/-1 to disarm). When
      armed (and out_fd present), acks carry the output memfd as the
      OrderPacket target so the C orderer emits in batch_idx order.
    node/wincarn: worker identity for fr_py_worker_init (respawn
      lineage: the reactor increments wincarn per generation).

    No signal handlers are installed here: KeyboardInterrupt inside
    the payload stays a payload error (retry path), matching
    worker_main. Global abort arrives via the engine fire alarm.
    """
    code = 1
    try:
        # The parent's read end must not stay open in the child, or
        # the parent's EOF detection never fires.
        if death_r is not None and death_r >= 0:
            try:
                os.close(death_r)
            except OSError:
                pass
        order_pipe = (order_w if order_w is not None and order_w >= 0
                      else -1)
        code = _run(wid, payload_spec, sink_spec, memfd_fd, file_size,
                    out_fd, signal_w, on_error, fallow_fd,
                    trap_ack_w=trap_ack_w, order_target=order_pipe,
                    wincarn=wincarn, node=node)
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
        if code != 0:
            # EXIT-trap equivalent, graceful-failure branch:
            # 1. best-effort escrow of any in-flight batch (the
            #    failure paths in _run already deposited with exact
            #    kills; this covers only unexpected crashes, where 1
            #    is the safe-direction estimate — an underestimate
            #    merely retries, never poisons early).
            try:
                get().fr_py_escrow_deposit(1)
            except Exception:
                pass
            # 2. trap-ACK confirmation for the reactor's 3s grace.
            _trap_ack_notify(trap_ack_w, "%d\n" % (wid,))
        # 3. death-pipe close → parent observes worker exit.
        if death_w is not None and death_w >= 0:
            try:
                os.close(death_w)
            except OSError:
                pass
        os._exit(code)
