"""forkrun.run / map / stream — Stage 4 Phase 2 (W-PY3) emitter path.

v0.5 pipeline (single-node UMA, materializing input):
  parent: validate -> load substrate -> fr_py_init -> spill source into an
    ingress memfd -> fr_py_ingest_done -> fr_py_scan (publishes all slots
    synchronously) -> create one OUTPUT memfd per worker -> fork N workers
    (both memfds inherited) -> waitpid -> pread output memfds -> destroy.
  worker (post-fork child): mmap the ingress memfd once -> claim/Batch/
    payload/invalidate/flush/copy-to-output-memfd/ack loop with escrow
    retry -> os._exit.

Emitter (§3.9b, v0.5 stage): per-worker output memfds carrying keyed records
(batch_idx u64 LE, length u64 LE, payload bytes). The emitter TRANSPORTS;
it does not order — batch_index is the execution identity/ordering key and
the parent does optional consumer-side reassembly (map(order="index")
sorts; the C orderer is skipped by design). v0.5 drains after workers
complete; true PIPE streaming (parent drains while workers run, closing the
hydraulic backpressure loop) is v1. No Python pipe/queue carries payload
bytes at any point; no pickle; no bash.

Scope notes (v0.5 != the full plan):
- Input AND output are materialized: bounded inputs/outputs only. TB-scale
  boundedness (streaming ingest + fallow + windowed mmap + PIPE drain)
  is v1/Stage 4 refinement, not this path.
- Copy-on-return: payload returns bytes/memoryview/str/None; the wrapper
  copies into the output memfd (stated cost; write-in-place OutputBatch
  is demand-pulled Stage 6+).
- No NUMA multi-node (nodes must be "auto"/1), no resume, no spawn/plugin
  modes (mode must be "python").
- Same-process retry: a failing batch is escrow-deposited (kills+1) and the
  worker continues; it re-claims the batch via the escrow drain without a
  respawn manager. Poisoned batches are skipped+acked. This preserves the
  retry-then-poison counting of bash -E without a reactor.
- map() is BATCH-granular (payload receives a Batch, one result per batch),
  collected parent-side from the output memfds after waitpid.
- run() with sink=None discards results; with a callable sink the sink runs
  payload-side in the worker (zero crossing, §3.9a).
"""

from __future__ import annotations

import os
import struct
import sys

from ._api import _validate
from ._bindings import RC_OK, get, load
from ._cuda_guard import check_cuda_hazard
from ._pipes import make_pipe
from ._plugin import make_plugin_payload
from ._reassembly import ReassemblyBuffer
from ._spawn import make_spawn_payload
from ._worker import _HDR, worker_main

import fcntl as _fcntl

_CHUNK = 1 << 20

# Process-wide run serialization (W-PY4.b G/Q-series). The engine's
# globals (g_state/state, eventfds, escrow pipes) are process-wide, so two
# _execute() calls racing in parent threads would interleave init/scan
# state. The lock makes concurrent invocations sequentially correct
# (parent threads are fine — workers fork from whichever thread holds the
# lock; the child never touches it). One lock for the whole pipeline:
# coarse, deterministic, v0-appropriate.
import threading as _threading

_RUN_LOCK = _threading.Lock()


def _open_source(source):
    """Return (fd, must_close) for path | int-fd | fileno() object."""
    import os as _os

    if isinstance(source, (str, bytes, _os.PathLike)):
        return _os.open(source, _os.O_RDONLY), True
    if isinstance(source, int):
        return source, False
    fileno = source.fileno()
    if isinstance(fileno, int) and fileno >= 0:
        return fileno, False
    raise TypeError("unreachable: source validated by _validate")


def _spill_to_memfd(src_fd) -> tuple[int, int]:
    """Copy src_fd until EOF into a sealed-by-usage ingress memfd.

    Returns (memfd_fd, size). v0 materializes the whole input (bounded
    inputs only — see module docstring).
    """
    try:
        memfd = os.memfd_create("forkrun_ingress")
    except AttributeError:
        # Fallback for old Pythons: tmpfs-backed anonymous file.
        import tempfile as _tf

        tmp = _tf.TemporaryFile(prefix="forkrun_ingress_")
        memfd = tmp.fileno()
        # Keep tmp alive via the fd only is unsafe (GC closes it); stash.
        _spill_to_memfd._tmp_hold.append(tmp)
    size = 0
    while True:
        try:
            chunk = os.read(src_fd, _CHUNK)
        except OSError as exc:
            raise RuntimeError("failed reading source: %s" % (exc,))
        if not chunk:
            break
        view = memoryview(chunk)
        while view:
            n = os.write(memfd, view)
            size += n
            view = view[n:]
    return memfd, size


_spill_to_memfd._tmp_hold = []


def _new_output_memfds(n) -> tuple[list, list]:
    """Create one output memfd per worker, PRE-FORK (W-PY3 correction).

    A memfd created post-fork in the child exists only in the child's fd
    table — the parent could never read it. So the parent creates all N
    here; children inherit them across fork and write their own slice
    (worker i writes fd i only — never shared between workers). The
    parent preads them after waitpid. Falls back to anonymous temp files
    where os.memfd_create is unavailable.
    Returns (fds, hold) where hold keeps fallback files alive.
    """
    fds: list = []
    hold: list = []
    try:
        for i in range(n):
            fds.append(os.memfd_create("forkrun_out%d" % i))
        return fds, hold
    except AttributeError:
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
        fds = []
        import tempfile as _tf

        for _ in range(n):
            tmp = _tf.TemporaryFile(prefix="forkrun_out_")
            hold.append(tmp)
            fds.append(tmp.fileno())
        return fds, hold


def _read_fd_all(fd) -> bytes:
    """Read an fd from offset 0 to EOF (parent-side, post-waitpid)."""
    try:
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError:
        pass
    chunks = []
    while True:
        try:
            chunk = os.read(fd, _CHUNK)
        except OSError:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _split_records(blob: bytes) -> tuple:
    """Split a record stream into (complete records, leftover tail).

    Complete records: [(batch_idx, payload_bytes)]. The tail is an
    incomplete header or a header + short body — held back for the next
    chunk, never silently consumed.
    """
    records = []
    off = 0
    n = len(blob)
    while True:
        rec_start = off
        if off + _HDR.size > n:
            break
        idx, ln = _HDR.unpack_from(blob, off)
        off += _HDR.size
        if off + ln > n:
            off = rec_start
            break
        records.append((idx, blob[off:off + ln]))
        off += ln
    return records, blob[off:]


def _parse_records(blob: bytes) -> list:
    """Parse the v0 emitter record stream: [batch_idx u64][len u64][bytes]*.

    Returns [(batch_idx, payload_bytes)]. Truncated tails (worker died
    mid-record) are dropped — waitpid failure already raises before this
    runs, so a short tail means an internal inconsistency, not user data.
    """
    records, _tail = _split_records(blob)
    return records


def _resolve_workers(workers):
    if workers is not None:
        return workers
    try:
        n = os.cpu_count() or 4
    except NotImplementedError:
        n = 4
    return max(1, min(n, 64))


def _coerce_payload(payload, mode):
    """Normalize the payload + mode for the engine path (W-PY8, eager).

    Returns (payload_fn, engine_mode). mode="spawn" wraps the command and
    mode="plugin" binds the C entry point; both normalize to "python"
    downstream — the spawn-ness/plugin-ness is fully encapsulated in the
    wrapper, so the claim/ack loop, emitter, and reassembly never branch
    on mode. Raises ValueError for shape mismatches eagerly, so stream()
    still validates on call.
    """
    if mode == "plugin":
        if callable(payload):
            raise ValueError(
                "mode='plugin' requires a 'path:function' string, not a "
                "callable. Use mode='python' for Python functions.")
        if not isinstance(payload, str) or ":" not in payload:
            raise ValueError(
                "mode='plugin' payload must be 'path:function' format, "
                "got %r" % (payload,))
        path, _, func_name = payload.rpartition(":")
        if not path or not func_name:
            raise ValueError(
                "mode='plugin' payload must be 'path:function' format, "
                "got %r" % (payload,))
        return make_plugin_payload(path, func_name), "python"
    if mode == "spawn":
        if callable(payload):
            raise ValueError(
                "mode='spawn' requires a command (str or list), not a "
                "callable. Use mode='python' for Python functions.")
        return make_spawn_payload(payload), "python"
    return payload, mode


def _detect_streaming(source, streaming):
    """Resolve streaming=None to a bool (W-PY16).

    Explicit True/False always wins. Auto (None): fifo/socket sources
    stream (unbounded, can't pre-stat a size — and a slow writer must
    not block a full spill); everything else materializes. Works for
    paths (stat), int fds (fstat), and fileno() objects.
    """
    if streaming is not None:
        return streaming
    try:
        import stat as _stat
        if isinstance(source, (str, bytes, os.PathLike)):
            st = os.stat(source)
        elif isinstance(source, int):
            if isinstance(source, bool) or source < 0:
                return False
            st = os.fstat(source)
        elif hasattr(source, "fileno"):
            st = os.fstat(source.fileno())
        else:
            return False
        return _stat.S_ISFIFO(st.st_mode) or _stat.S_ISSOCK(st.st_mode)
    except (OSError, ValueError):
        return False


def _close_all_except(keep):
    """Close every fd >= 3 not in keep (post-fork child hygiene, W-PY16).

    The fallow/scanner children must not hold the write ends whose
    closure signals EOF (fallow_w pins the reaper; signal_w pins the
    drain), nor src copies, nor sibling out_fds. keep is a set of ints.
    Best-effort; never raises (runs pre-_exit in children).
    """
    try:
        try:
            fds = [int(n) for n in os.listdir("/proc/self/fd")]
        except (OSError, ValueError):
            fds = list(range(3, 1024))
        for fd in fds:
            if fd >= 3 and fd not in keep:
                try:
                    os.close(fd)
                except OSError:
                    pass
    except Exception:
        pass


def run(payload, source, *, mode="python", sink=None, order="none",
        lines=None, bytes=None, workers=None, nodes="auto",
        on_error="retry", streaming=None):
    """Run payload over source in parallel. See module docstring for v0 scope.

    mode="python": payload is "pkg.mod:func" | callable (Batch -> bytes).
    mode="spawn": payload is a command (str | list) executed per batch
      with batch bytes on stdin; stdout captured as the result.
    mode="plugin": payload is "path:function" (C .so entry point per the
      v0 Python-side convention — see _plugin.py ABI notice).
    streaming: None (default) auto-detects (fifo/socket sources stream,
      files materialize); True forces streaming ingest (bounded ingress
      via the fallow reaper — TB-scale/unbounded sources); False forces
      the materialized path.
    """
    _validate(payload, source, mode=mode, sink=sink, order=order,
              lines=lines, bytes_=bytes, workers=workers, nodes=nodes,
              on_error=on_error, streaming=streaming)
    if mode not in ("python", "spawn", "plugin"):
        raise NotImplementedError(
            "unknown mode %r" % (mode,))
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    payload, mode = _coerce_payload(payload, mode)
    if _detect_streaming(source, streaming):
        _execute_ingest(payload, source, sink=sink, lines=lines,
                        bytes_=bytes, workers=_resolve_workers(workers),
                        on_error=on_error, collect=False, order=order,
                        mode=mode, nodes=nodes)
        return None
    _execute(payload, source, sink=sink, lines=lines, bytes_=bytes,
             workers=_resolve_workers(workers), on_error=on_error,
             collect=False, order=order)
    return None


def map(payload, source, **kwargs):
    """Batch-granular map: payload(Batch) -> result per batch, ordered by
    batch_index. v0 collects parent-side after workers exit (not streaming)."""
    mode = kwargs.get("mode", "python")
    nodes = kwargs.get("nodes", "auto")
    _validate(payload, source, mode=mode, sink=None,
              order=kwargs.get("order", "none"), lines=kwargs.get("lines"),
              bytes_=kwargs.get("bytes"), workers=kwargs.get("workers"),
              nodes=nodes, on_error=kwargs.get("on_error", "retry"),
              streaming=kwargs.get("streaming"))
    payload, mode = _coerce_payload(payload, mode)
    order = kwargs.get("order", "none")
    if _detect_streaming(source, kwargs.get("streaming")):
        return _execute_ingest(
            payload, source, sink=None, lines=kwargs.get("lines"),
            bytes_=kwargs.get("bytes"),
            workers=_resolve_workers(kwargs.get("workers")),
            on_error=kwargs.get("on_error", "retry"),
            collect=True, order=order, mode=mode, nodes=nodes)
    results = _execute(payload, source, sink=None,
                       lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
                       workers=_resolve_workers(kwargs.get("workers")),
                       on_error=kwargs.get("on_error", "retry"),
                       collect=True, order=order,
                       mode=mode, nodes=nodes)
    return results


def stream(payload, source, **kwargs):
    """Yield results as they arrive — TRUE v1 streaming.

    order="none" (default): worker-completion order (first-finished first).
    order="index": batch_idx sequence via parent-side reassembly (bounded
      out-of-order buffer; holes from poisoned batches flush sorted at
      EOF — brief head-of-line blocking behind a hole is inherent).

    Validates eagerly (raises on call, before the first next()).
    """
    _validate(payload, source, mode=kwargs.get("mode", "python"),
              sink=None, order=kwargs.get("order", "none"),
              lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
              workers=kwargs.get("workers"),
              nodes=kwargs.get("nodes", "auto"),
              on_error=kwargs.get("on_error", "retry"),
              streaming=kwargs.get("streaming"))
    payload, engine_mode = _coerce_payload(payload, kwargs.get("mode",
                                                               "python"))
    kwargs = dict(kwargs, mode=engine_mode)
    if _detect_streaming(source, kwargs.get("streaming")):
        return _ingest_stream_gen(payload, source, **kwargs)
    return _stream_gen(payload, source, **kwargs)


def _stream_gen(payload, source, **kwargs):
    yield from _execute_streaming(
        payload, source,
        lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
        workers=_resolve_workers(kwargs.get("workers")),
        on_error=kwargs.get("on_error", "retry"),
        mode=kwargs.get("mode", "python"), nodes=kwargs.get("nodes", "auto"))


def _stream_gen(payload, source, **kwargs):
    # v1 true streaming: yields blobs in worker-completion order WHILE
    # workers run (not after collection). map() stays on the v0.5
    # post-completion path; run() (discard/worker-sink) needs no drain.
    yield from _execute_streaming(
        payload, source,
        lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
        workers=_resolve_workers(kwargs.get("workers")),
        on_error=kwargs.get("on_error", "retry"),
        mode=kwargs.get("mode", "python"), nodes=kwargs.get("nodes", "auto"),
        order=kwargs.get("order", "none"))


def _drain_worker_memfd(fd, state) -> tuple:
    """Incrementally pread new bytes from one worker memfd.

    state is [read_offset, tail]; pread (never read/lseek — the fd's open
    description is SHARED with the writing child). Returns complete
    [(batch_idx, payload)] records; the incomplete tail stays buffered.
    """
    try:
        size = os.fstat(fd).st_size
    except OSError:
        return []
    if size <= state[0]:
        return []
    try:
        chunk = os.pread(fd, size - state[0], state[0])
    except OSError:
        return []
    if not chunk:
        return []
    state[0] += len(chunk)
    records, tail = _split_records(state[1] + chunk)
    state[1] = tail
    return records


def _drain_records(lib, signal_r, out_fds, pids, statuses,
                   order="none", stats=None, pump=None):
    """Yield payload blobs (v1 drain loop).

    order="none": worker-completion order (W-PY6 behavior).
    order="index": batch_idx sequence via parent-side reassembly (W-PY7);
      holes (poisoned/skipped batches) flush sorted at EOF — mid-stream
      head-of-line blocking behind a hole is the inherent cost of ordered
      streaming. Reassembly keys come from the records themselves (the
      keyed transport); the signal's idx is a wakeup cross-check only.
    stats (optional dict): receives {"reassembly_max": high-water mark}
      when ordering (white-box diagnostic for the boundedness test).
    pump (W-PY16): optional zero-arg callable run once per drain-loop
      iteration; returns True when the ingest it services is fully done
      (source EOF consumed AND ingest gate issued). Lets stream() over a
      streaming source interleave spill and drain in one thread. Raising
      inside pump propagates (caller teardown handles children).
    Terminates when every worker is reaped AND the signal pipe hits EOF
    (all write ends closed) with no unframed signal bytes left AND the
    pump (if any) is done.
    """
    import select as _select
    import struct as _struct

    _sig = _struct.Struct("<QQ")
    n = len(pids)
    reassembly = ReassemblyBuffer() if order == "index" else None
    per_worker = [[0, b""] for _ in range(n)]  # [read_offset, tail]
    alive = set(pids)
    sig_buf = b""
    sig_eof = False
    pump_done = pump is None
    while True:
        if not sig_eof:
            try:
                ready, _, _ = _select.select([signal_r], [], [], 0.1)
            except (OSError, ValueError):
                ready = []
            if ready:
                try:
                    chunk = os.read(signal_r, 65536)
                except OSError:
                    chunk = b""
                if chunk == b"":
                    sig_eof = True
                else:
                    sig_buf += chunk
        while len(sig_buf) >= _sig.size:
            wid, _idx = _sig.unpack_from(sig_buf[:_sig.size])
            sig_buf = sig_buf[_sig.size:]
            if 0 <= wid < n:
                for _bidx, blob in _drain_worker_memfd(
                        out_fds[wid], per_worker[wid]):
                    if reassembly is None:
                        yield blob
                    else:
                        reassembly.add(_bidx, blob)
                        for _, ordered in reassembly.drain():
                            yield ordered
        for pid in list(alive):
            try:
                wpid, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                alive.discard(pid)
                continue
            if wpid == pid:
                alive.discard(pid)
                statuses.append((pid, status))
        if pump is not None and not pump_done:
            pump_done = bool(pump())
        if not alive and sig_eof and not sig_buf and pump_done:
            break
    # Safety sweep: every record arrived with its signal before EOF, so
    # this should find nothing — but a short final write must never be
    # silently lost.
    for wid in range(n):
        for bidx, blob in _drain_worker_memfd(out_fds[wid],
                                              per_worker[wid]):
            if reassembly is None:
                yield blob
            else:
                reassembly.add(bidx, blob)
                for _, ordered in reassembly.drain():
                    yield ordered
    if reassembly is not None:
        for _, ordered in reassembly.final_drain():
            yield ordered
        if stats is not None:
            stats["reassembly_max"] = reassembly.max_size


def _teardown_stream(lib, pids, signal_r, out_fds, out_hold, memfd,
                     src_fd, must_close, extra_pids=(), fallow_w=None):
    """Reap-all + close-all + destroy. Abandon-safe: unblocks claim-gated
    workers via the fire alarm and EPIPEs signal-blocked ones by closing
    the read end, then reaps (zombies pin pids, so no PID-reuse hazard
    for the SIGKILL straggler pass).

    W-PY16: extra_pids covers the scanner + fallow children (same
    kill-then-reap discipline — the fire alarm unblocks a scanner gated
    on ingest, and closing fallow_w EOFs a reaper gated on acks);
    fallow_w is closed here (idempotent: normal flow already closed it
    before reaping the reaper).
    """
    try:
        lib.fr_py_abort()
    except Exception:
        pass
    if signal_r is not None:
        try:
            os.close(signal_r)
        except OSError:
            pass
    if fallow_w is not None:
        try:
            os.close(fallow_w)
        except OSError:
            pass
    for pid in list(pids) + list(extra_pids):
        try:
            wpid, _ = os.waitpid(pid, os.WNOHANG)
            if wpid == 0:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
        except ChildProcessError:
            pass
    for pid in list(pids) + list(extra_pids):
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        except OSError:
            pass
    for fd in out_fds:
        try:
            os.close(fd)
        except OSError:
            pass
    out_hold.clear()
    if memfd is not None:
        try:
            os.close(memfd)
        except OSError:
            pass
    if must_close:
        try:
            os.close(src_fd)
        except OSError:
            pass
    try:
        lib.fr_py_destroy()
    except Exception:
        pass


def _execute_streaming(payload, source, *, lines, bytes_, workers,
                       on_error, mode="python", nodes="auto",
                       order="none", stats=None):
    """v1 streaming pipeline: a GENERATOR. Fork happens on first next(),
    blobs yield in worker-completion order (order="none") or batch_idx
    sequence (order="index", parent-side reassembly) while workers run.
    Failure accounting + poison summary run at exhaustion. Abandoning the
    generator (close/GC/exception) tears down workers via the finally.
    stats (optional dict): white-box drain diagnostics (reassembly_max).
    """
    if mode != "python":
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    if order not in ("none", "index"):
        raise ValueError(
            "order must be 'none' or 'index', got %r" % (order,))
    if mode != "python":
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")

    src_fd, must_close = _open_source(source)
    memfd = None
    out_fds: list = []
    out_hold: list = []
    signal_r = None
    signal_w = None
    pids: list = []
    try:
        memfd, size = _spill_to_memfd(src_fd)
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        if lib.fr_py_ingest_done() != RC_OK:
            raise RuntimeError("ingest signal failed")
        if lib.fr_py_scan(memfd) != RC_OK:
            raise RuntimeError("scan failed")

        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass

        out_fds, out_hold = _new_output_memfds(workers)
        # W-PY15: 1MB signal pipe (65536 outstanding 16B signals vs 4096
        # at default) — workers run further ahead of a slow consumer.
        # Best-effort: falls back to 64KB where F_SETPIPE_SZ is capped.
        signal_r, signal_w, _ = make_pipe()
        for i in range(workers):
            pid = os.fork()
            if pid == 0:
                # Child — never returns. Drops the ends it doesn't use so
                # the parent's EOF detection is exact.
                try:
                    os.close(signal_r)
                except OSError:
                    pass
                try:
                    if must_close:
                        os.close(src_fd)
                except OSError:
                    pass
                worker_main(i, payload, None, memfd, size, out_fds[i],
                            signal_w, on_error)
                os._exit(127)  # unreachable; worker_main exits
            else:
                pids.append(pid)
        # Parent drops its write copy: EOF on signal_r then means every
        # worker has exited (or abandoned teardown closed it).
        try:
            os.close(signal_w)
        except OSError:
            pass
        signal_w = None

        statuses: list = []
        try:
            for blob in _drain_records(lib, signal_r, out_fds, pids,
                                       statuses, order=order, stats=stats):
                yield blob
        finally:
            # Normal exhaustion falls through; abandonment (GeneratorExit)
            # or consumer error lands here: reap, close, destroy, re-raise
            # (a fresh raise on the abandon path would mask GeneratorExit).
            _teardown_stream(lib, pids, signal_r, out_fds, out_hold,
                             memfd, src_fd, must_close)
            memfd = None
            signal_r = None
            out_fds = []

        failed = [s for s in statuses
                  if not (os.WIFEXITED(s[1]) and os.WEXITSTATUS(s[1]) == 0)]
        if failed:
            raise RuntimeError(
                "forkrun: %d/%d workers failed%s" % (
                    len(failed), len(pids),
                    " (on_error=%s)" % on_error))

        try:
            npois = lib.fr_py_poisoned_count()
        except Exception:
            npois = 0
        if npois:
            try:
                os.write(2, ("forkrun [WARN]: %d poisoned batch(es) "
                             "skipped (retry limit reached).\n" % npois
                             ).encode())
            except OSError:
                pass
    finally:
        # Idempotent second layer: teardown already ran inside; these are
        # no-ops when it did (Nones/empties) and save abandon paths where
        # setup itself raised before forking.
        _teardown_stream(lib, pids, signal_r, out_fds, out_hold, memfd,
                         src_fd, must_close)


def _execute_ingest_stream(payload, source, *, lines, bytes_, workers,
                           on_error, mode="python", nodes="auto",
                           order="none", stats=None):
    """stream() over a streaming source: a GENERATOR (W-PY16).

    Same fork topology as _execute_ingest_locked (reaper + scanner +
    workers, file_size=-1, fallow acks), but the parent interleaves the
    spill with the live drain in one thread: each drain-loop iteration
    runs pump(), which spill-quantum-drains the (nonblocking) source
    until EAGAIN and issues the ingest gate at source EOF. First results
    can arrive before the source is exhausted (slow-source pipelining).
    Abandonment tears everything down via the finally (helpers reaped
    through extra_pids). Mirrors _execute_streaming's guard convention.
    """
    if mode != "python":
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    if order not in ("none", "index"):
        raise ValueError(
            "order must be 'none' or 'index', got %r" % (order,))
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")

    src_fd, must_close = _open_source(source)
    memfd = None
    mem_hold: list = []
    out_fds: list = []
    out_hold: list = []
    fallow_r = fallow_w = None
    signal_r = None
    signal_w = None
    fallow_pid = scan_pid = None
    helpers = {"scan_rc": None, "fallow_rc": None}
    gate = {"issued": False}
    pids: list = []
    try:
        memfd, mem_hold = _new_ingress_memfd()
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        out_fds, out_hold = _new_output_memfds(workers)
        signal_r, signal_w, _ = make_pipe()
        fallow_r, fallow_w = os.pipe()

        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass

        fallow_pid, scan_pid = _fork_ingest_helpers(
            lib, memfd, fallow_r, fallow_w)
        for i in range(workers):
            pid = os.fork()
            if pid == 0:
                try:
                    os.close(signal_r)
                except OSError:
                    pass
                try:
                    if must_close:
                        os.close(src_fd)
                except OSError:
                    pass
                _close_all_except({memfd, out_fds[i], signal_w, fallow_w})
                worker_main(i, payload, None, memfd, -1, out_fds[i],
                            signal_w, on_error, fallow_w)
                os._exit(127)  # unreachable; worker_main exits
            else:
                pids.append(pid)
        # Parent drops its write copies: signal EOF then means every
        # worker exited; reaper EOF means every worker exited too.
        try:
            os.close(signal_w)
        except OSError:
            pass
        signal_w = None
        try:
            os.close(fallow_r)
        except OSError:
            pass
        fallow_r = None
        try:
            os.close(fallow_w)
        except OSError:
            pass
        fallow_w = None

        # Nonblocking source for the interleave (dup user fds — never
        # mutate flags on a descriptor we don't own).
        if not must_close:
            src_fd = os.dup(src_fd)
            must_close = True
        try:
            fl = _fcntl.fcntl(src_fd, _fcntl.F_GETFL)
            _fcntl.fcntl(src_fd, _fcntl.F_SETFL, fl | os.O_NONBLOCK)
        except OSError:
            pass

        def _watch_live():
            # Same helper-liveness rule as the locked path (abort +
            # raise on death / premature clean scanner exit).
            for pid, name in ((scan_pid, "scanner"),
                              (fallow_pid, "fallow")):
                if pid is None:
                    continue
                try:
                    wpid, st = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    continue
                if wpid != pid:
                    continue
                ok = os.WIFEXITED(st) and os.WEXITSTATUS(st) == 0
                if name == "scanner":
                    helpers["scan_rc"] = st
                    if not ok or not gate["issued"]:
                        lib.fr_py_abort()
                        raise RuntimeError(
                            "forkrun: ingest scanner failed "
                            "(status %r)" % (st,))
                else:
                    helpers["fallow_rc"] = st
                    if not ok:
                        lib.fr_py_abort()
                        raise RuntimeError(
                            "forkrun: ingest reaper failed "
                            "(status %r)" % (st,))

        def _pump():
            # One spill quantum: drain the source until EAGAIN, then
            # return False (more may come) — or True once source EOF is
            # consumed and the ingest gate issued.
            _watch_live()
            if gate["issued"]:
                return True
            while True:
                try:
                    chunk = os.read(src_fd, _CHUNK)
                except BlockingIOError:
                    return False
                except OSError as exc:
                    raise RuntimeError(
                        "failed reading source: %s" % (exc,))
                if not chunk:
                    if lib.fr_py_ingest_done() != RC_OK:
                        raise RuntimeError("ingest signal failed")
                    gate["issued"] = True
                    return True
                view = memoryview(chunk)
                while view:
                    try:
                        n = os.write(memfd, view)
                    except OSError as exc:
                        raise RuntimeError(
                            "failed writing ingress: %s" % (exc,))
                    view = view[n:]
            # unreachable

        statuses: list = []
        try:
            for blob in _drain_records(lib, signal_r, out_fds, pids,
                                       statuses, order=order, stats=stats,
                                       pump=_pump):
                yield blob
        finally:
            _teardown_stream(lib, pids, signal_r, out_fds, out_hold,
                             memfd, src_fd, must_close,
                             extra_pids=[p for p in (fallow_pid, scan_pid)
                                         if p is not None])
            memfd = None
            signal_r = None
            out_fds = []

        failed = [s for s in statuses
                  if not (os.WIFEXITED(s[1]) and os.WEXITSTATUS(s[1]) == 0)]
        if failed:
            raise RuntimeError(
                "forkrun: %d/%d workers failed%s" % (
                    len(failed), len(pids),
                    " (on_error=%s)" % on_error))

        if scan_pid is not None and helpers["scan_rc"] is None:
            try:
                _, scan_st = os.waitpid(scan_pid, 0)
            except ChildProcessError:
                scan_st = None
            if scan_st is None or not (
                    os.WIFEXITED(scan_st) and
                    os.WEXITSTATUS(scan_st) == 0):
                raise RuntimeError(
                    "forkrun: ingest scanner failed (status %r)"
                    % (scan_st,))
        if fallow_pid is not None and helpers["fallow_rc"] is None:
            try:
                _, fallow_st = os.waitpid(fallow_pid, 0)
            except ChildProcessError:
                fallow_st = None
            if fallow_st is not None and not (
                    os.WIFEXITED(fallow_st) and
                    os.WEXITSTATUS(fallow_st) == 0):
                try:
                    os.write(2, b"forkrun [WARN]: ingest reaper exited "
                             b"abnormally; ingress may not be fully "
                             b"reclaimed.\n")
                except OSError:
                    pass

        try:
            npois = lib.fr_py_poisoned_count()
        except Exception:
            npois = 0
        if npois:
            try:
                os.write(2, ("forkrun [WARN]: %d poisoned batch(es) "
                             "skipped (retry limit reached).\n" % npois
                             ).encode())
            except OSError:
                pass
    finally:
        _teardown_stream(lib, pids, signal_r, out_fds, out_hold, memfd,
                         src_fd, must_close,
                         extra_pids=[p for p in (fallow_pid, scan_pid)
                                     if p is not None])


def _ingest_stream_gen(payload, source, **kwargs):
    # stream() over a streaming source: live drain interleaved with the
    # spill (pump hook), same ordering contract as _stream_gen.
    yield from _execute_ingest_stream(
        payload, source,
        lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
        workers=_resolve_workers(kwargs.get("workers")),
        on_error=kwargs.get("on_error", "retry"),
        mode=kwargs.get("mode", "python"), nodes=kwargs.get("nodes", "auto"),
        order=kwargs.get("order", "none"))


def _new_ingress_memfd():
    """Create the streaming-ingest memfd (parent writes, scanner + workers
    read). Falls back to an anonymous temp file where memfd_create is
    unavailable (same rationale as _spill_to_memfd). Returns (fd, hold)
    where hold keeps a fallback file alive (empty for memfd)."""
    try:
        return os.memfd_create("forkrun_ingress"), []
    except AttributeError:
        import tempfile as _tf

        tmp = _tf.TemporaryFile(prefix="forkrun_ingress_")
        return tmp.fileno(), [tmp]


def _execute_ingest(payload, source, *, sink, lines, bytes_, workers,
                    on_error, collect, order, mode="python", nodes="auto"):
    """Streaming-ingest entry for map/run (blocking, like _execute)."""
    if mode != "python":
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    # CUDA-fork hazard guard (W-PY5, same position as _execute).
    hazard, message = check_cuda_hazard()
    if hazard:
        raise RuntimeError(message)
    with _RUN_LOCK:
        return _execute_ingest_locked(
            payload, source, sink=sink, lines=lines, bytes_=bytes_,
            workers=workers, on_error=on_error, collect=collect,
            order=order)


def _fork_ingest_helpers(lib, memfd, fallow_r, fallow_w):
    """Fork the fallow reaper + scanner children (W-PY16).

    Both run long-lived engine loops concurrently with the parent's
    spill: the reaper punches holes behind the contiguous acked prefix
    (bounded ingress), the scanner publishes batches as bytes land
    (its pread loop waits on !ingest_complete — the bash topology).
    Returns (fallow_pid, scan_pid). Children never return (os._exit).
    The caller forks workers after; the parent closes its fallow copies
    once every child exists (reaper EOF = workers' write ends only).
    """
    fallow_pid = os.fork()
    if fallow_pid == 0:
        try:
            _close_all_except({fallow_r, memfd})
            rc = lib.fr_py_fallow_loop(fallow_r, memfd)
        except BaseException:
            rc = 1
        os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
    scan_pid = os.fork()
    if scan_pid == 0:
        try:
            _close_all_except({memfd})
            rc = lib.fr_py_scan(memfd)
        except BaseException:
            rc = 1
        os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
    return fallow_pid, scan_pid


def _execute_ingest_locked(payload, source, *, sink, lines, bytes_,
                           workers, on_error, collect, order):
    """map/run over a streaming source (W-PY16, collect/discard).

    Pipeline: init → ingress memfd → output memfds → fallow pipe →
    fork reaper + scanner → fork workers (file_size=-1, fallow_w) →
    parent spills source in 1MB chunks (WNOHANG helper watches) →
    ingest gate → waitpid workers → join scanner (strict) + reaper
    (lenient) → poison summary → parse. Ingress stays bounded: the
    reaper punches acked prefixes while the spill advances.
    """
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")

    src_fd, must_close = _open_source(source)
    memfd = None
    mem_hold: list = []
    out_fds: list = []
    out_hold: list = []
    fallow_r = fallow_w = None
    fallow_pid = scan_pid = None
    helpers = {"scan_rc": None, "fallow_rc": None}
    gate_issued = False
    pids: list = []
    try:
        memfd, mem_hold = _new_ingress_memfd()
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        if collect:
            out_fds, out_hold = _new_output_memfds(workers)
        fallow_r, fallow_w = os.pipe()

        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass

        fallow_pid, scan_pid = _fork_ingest_helpers(
            lib, memfd, fallow_r, fallow_w)
        for i in range(workers):
            pid = os.fork()
            if pid == 0:
                try:
                    _close_all_except(
                        {memfd, fallow_w} |
                        ({out_fds[i]} if collect else set()))
                except Exception:
                    pass
                worker_main(i, payload, sink, memfd, -1,
                            out_fds[i] if collect else None, None,
                            on_error, fallow_w)
                os._exit(127)  # unreachable; worker_main exits
            else:
                pids.append(pid)
        # Parent drops its fallow copies: reaper EOF then means every
        # worker has exited (its own write end closed at _exit).
        try:
            os.close(fallow_r)
        except OSError:
            pass
        fallow_r = None
        try:
            os.close(fallow_w)
        except OSError:
            pass
        fallow_w = None

        def _watch_helpers():
            # Reap helper deaths mid-spill (nonblocking). Scanner death
            # is fatal (unpublished tail would be silently lost);
            # reaper death aborts too (acks would EPIPE and fail
            # workers — fail fast instead of spilling pointlessly).
            # Scanner exit 0 before the gate is equally fatal: it can
            # only exit 0 via the EOF gate, so an early 0 means the
            # tail it never saw is lost.
            nonlocal gate_issued
            for pid, name in ((scan_pid, "scanner"),
                              (fallow_pid, "fallow")):
                if pid is None:
                    continue
                try:
                    wpid, st = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    continue
                if wpid != pid:
                    continue
                ok = os.WIFEXITED(st) and os.WEXITSTATUS(st) == 0
                if name == "scanner":
                    helpers["scan_rc"] = st
                    if not ok or not gate_issued:
                        lib.fr_py_abort()
                        raise RuntimeError(
                            "forkrun: ingest scanner failed "
                            "(status %r)" % (st,))
                else:
                    helpers["fallow_rc"] = st
                    if not ok:
                        lib.fr_py_abort()
                        raise RuntimeError(
                            "forkrun: ingest reaper failed "
                            "(status %r)" % (st,))

        try:
            while True:
                try:
                    chunk = os.read(src_fd, _CHUNK)
                except OSError as exc:
                    raise RuntimeError(
                        "failed reading source: %s" % (exc,))
                if not chunk:
                    break
                view = memoryview(chunk)
                while view:
                    try:
                        n = os.write(memfd, view)
                    except OSError as exc:
                        raise RuntimeError(
                            "failed writing ingress: %s" % (exc,))
                    view = view[n:]
                _watch_helpers()
        except KeyboardInterrupt:
            lib.fr_py_abort()
            raise
        if lib.fr_py_ingest_done() != RC_OK:
            raise RuntimeError("ingest signal failed")
        gate_issued = True

        failed = []
        try:
            for pid in pids:
                _, status = os.waitpid(pid, 0)
                if not (os.WIFEXITED(status) and
                        os.WEXITSTATUS(status) == 0):
                    failed.append((pid, status))
        except KeyboardInterrupt:
            lib.fr_py_abort()
            for pid in pids:
                try:
                    os.waitpid(pid, 0)
                except Exception:
                    pass
            raise

        if failed:
            raise RuntimeError(
                "forkrun: %d/%d workers failed%s" % (
                    len(failed), len(pids),
                    " (on_error=%s)" % on_error))

        # Join the scanner (strict: unpublished tail is data loss) and
        # the reaper (lenient warn: workers-OK implies acks landed; a
        # late reaper death loses nothing).
        if scan_pid is not None and helpers["scan_rc"] is None:
            try:
                _, scan_st = os.waitpid(scan_pid, 0)
            except ChildProcessError:
                scan_st = None
            if scan_st is None or not (
                    os.WIFEXITED(scan_st) and
                    os.WEXITSTATUS(scan_st) == 0):
                raise RuntimeError(
                    "forkrun: ingest scanner failed (status %r)"
                    % (scan_st,))
        if fallow_pid is not None and helpers["fallow_rc"] is None:
            try:
                _, fallow_st = os.waitpid(fallow_pid, 0)
            except ChildProcessError:
                fallow_st = None
            if fallow_st is not None and not (
                    os.WIFEXITED(fallow_st) and
                    os.WEXITSTATUS(fallow_st) == 0):
                try:
                    os.write(2, b"forkrun [WARN]: ingest reaper exited "
                             b"abnormally; ingress may not be fully "
                             b"reclaimed.\n")
                except OSError:
                    pass

        try:
            npois = lib.fr_py_poisoned_count()
        except Exception:
            npois = 0
        if npois:
            try:
                os.write(2, ("forkrun [WARN]: %d poisoned batch(es) "
                             "skipped (retry limit reached).\n" % npois
                             ).encode())
            except OSError:
                pass

        if not collect:
            return None
        records = []
        for fd in out_fds:
            records.extend(_parse_records(_read_fd_all(fd)))
        if order == "index":
            records.sort(key=lambda kv: kv[0])
        return [blob for _, blob in records]
    finally:
        for fd in out_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        out_hold.clear()
        mem_hold.clear()
        if fallow_r is not None:
            try:
                os.close(fallow_r)
            except OSError:
                pass
        if fallow_w is not None:
            try:
                os.close(fallow_w)
            except OSError:
                pass
        for pid in [fallow_pid, scan_pid]:
            if pid is None:
                continue
            try:
                wpid, _ = os.waitpid(pid, os.WNOHANG)
                if wpid == 0:
                    try:
                        os.kill(pid, 9)
                    except OSError:
                        pass
            except ChildProcessError:
                pass
        for pid in [fallow_pid, scan_pid]:
            if pid is None:
                continue
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            except OSError:
                pass
        if memfd is not None:
            try:
                os.close(memfd)
            except OSError:
                pass
        if must_close:
            try:
                os.close(src_fd)
            except OSError:
                pass
        try:
            lib.fr_py_destroy()
        except Exception:
            pass


def _execute(payload, source, *, sink, lines, bytes_, workers, on_error,
             collect, order, mode="python", nodes="auto"):
    if mode != "python":
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    # CUDA-fork hazard guard (W-PY5): runs in the PARENT before any engine
    # contact or forking. Fail fast — never fork under a live context.
    hazard, message = check_cuda_hazard()
    if hazard:
        raise RuntimeError(message)
    with _RUN_LOCK:
        return _execute_locked(payload, source, sink=sink, lines=lines,
                               bytes_=bytes_, workers=workers,
                               on_error=on_error, collect=collect,
                               order=order)


def _execute_locked(payload, source, *, sink, lines, bytes_, workers,
                    on_error, collect, order):
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")

    src_fd, must_close = _open_source(source)
    memfd = None
    try:
        memfd, size = _spill_to_memfd(src_fd)
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        if lib.fr_py_ingest_done() != RC_OK:
            raise RuntimeError("ingest signal failed")
        if lib.fr_py_scan(memfd) != RC_OK:
            raise RuntimeError("scan failed")

        # Flush buffered stdio before forking (no duplicated output).
        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass

        out_fds: list = []
        out_hold: list = []
        if collect:
            # Emitter transport, created pre-fork (see _new_output_memfds).
            out_fds, out_hold = _new_output_memfds(workers)

        pids = []
        for i in range(workers):
            pid = os.fork()
            if pid == 0:
                # Child — never returns.
                try:
                    if must_close:
                        try:
                            os.close(src_fd)
                        except OSError:
                            pass
                except Exception:
                    pass
                worker_main(i, payload, sink, memfd, size,
                            out_fds[i] if collect else None, None, on_error)
                os._exit(127)  # unreachable; worker_main exits
            else:
                pids.append(pid)

        failed = []
        try:
            for pid in pids:
                _, status = os.waitpid(pid, 0)
                if not (os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0):
                    failed.append((pid, status))
        except KeyboardInterrupt:
            lib.fr_py_abort()
            for pid in pids:
                try:
                    os.waitpid(pid, 0)
                except Exception:
                    pass
            raise
        finally:
            pass

        if failed:
            raise RuntimeError(
                "forkrun: %d/%d workers failed%s" % (
                    len(failed), len(pids),
                    " (on_error=%s)" % on_error))

        # Parent-side poison summary (g_state is MAP_SHARED: the parent
        # observes worker increments without IPC). Read BEFORE destroy.
        try:
            npois = lib.fr_py_poisoned_count()
        except Exception:
            npois = 0
        if npois:
            try:
                os.write(2, ("forkrun [WARN]: %d poisoned batch(es) "
                             "skipped (retry limit reached).\n" % npois
                             ).encode())
            except OSError:
                pass

        if not collect:
            return None
        records = []
        for fd in out_fds:
            records.extend(_parse_records(_read_fd_all(fd)))
        if order == "index":
            records.sort(key=lambda kv: kv[0])
        return [blob for _, blob in records]
    finally:
        for fd in out_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        out_hold.clear()
        if memfd is not None:
            try:
                os.close(memfd)
            except OSError:
                pass
        if must_close:
            try:
                os.close(src_fd)
            except OSError:
                pass
        try:
            lib.fr_py_destroy()
        except Exception:
            pass


__all__ = ["run", "map", "stream"]
