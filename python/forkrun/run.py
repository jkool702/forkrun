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
from ._fd_scrub import scrub_fds, snapshot_fds
from ._pipes import make_pipe
from ._plugin import make_plugin_payload
from ._reassembly import ReassemblyBuffer
from ._spawn import make_spawn_payload
from ._worker import _HDR, worker_main

import fcntl as _fcntl
import time as _time

# W-PY18: default byte-batch for mode="splice" (bash -b default).
_SPLICE_DEFAULT_BYTES = 512 * 1024

# W-PY16 worker fork timing: the scanner's pre-flight BAILS when a
# worker is already waiting (active_waiters > 0 → CASE B → phase 1),
# and entering phase 1 with already-complete input publishes nothing
# (silent loss). So workers fork only after pre-flight is provably
# over — i.e. after the first DATA publish — except:
# - stall path: no publish within STALL_FORK_AFTER with the gate still
#   open (slow source) → fork to trigger the bail deliberately; the
#   input is still arriving, which is the shape CASE B handles (bash
#   parity: pre-flight routinely bails under early workers).
# - gate path: source exhausted with no publish yet → wait for publish
#   (CASE A completes it); fork on publish, skip on empty input,
#   RuntimeError on the reaped-with-data-but-nothing-published anomaly.
STALL_FORK_AFTER = 2.0
# Post-stall-fork gate grace: after a stall-triggered fork, withhold
# the EOF gate until first publish or this long, so the gate can never
# land before phase-1 entry (entry follows the bail within ms).
POST_FORK_GATE_GRACE = 2.0

_CHUNK = 1 << 20

# W-PY19: default per-slot respawn bound for reactor runs. Crash-loop
# workers (death on every generation) must terminate: the trap-ACK
# grace catches SIGKILL-class deaths (~3s), but ACK-confirmed deaths
# (exit through the worker finally) would respawn forever without a
# cap. 3 mirrors the engine retry_limit default (retry-then-poison
# symmetry: 3 same-process retries ≈ 3 cross-process respawns).
REACTOR_RESPAWN_CAP = 3


def _validate_orchestrator(orchestrator):
    """Validate the W-PY19 orchestrator flag (None/True/False only)."""
    if orchestrator is None or isinstance(orchestrator, bool):
        return orchestrator
    raise TypeError(
        "orchestrator must be None, True, or False, got %r"
        % (orchestrator,))


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

    W-PY18 addendum: kernel copy first (copy_file_range via
    fr_py_copy_range, explicit offsets — never touches fd positions),
    userspace pread/pwrite loop on -1 (exotic pairs) or shortfall.
    Either way the bytes are identical; only the copy count differs.
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
    lib = None
    try:
        from ._bindings import get as _get

        lib = _get()
        copy_range = lib.fr_py_copy_range
    except Exception:
        copy_range = None
    if copy_range is not None:
        # Kernel path: loop single-shot copies until EOF (0) or -1
        # (unsupported pair → userspace loop below from `size`).
        while True:
            try:
                n = copy_range(src_fd, size, memfd, size, (1 << 40))
            except Exception:
                n = -1
            if n < 0:
                break
            if n == 0:
                return memfd, size
            size += n
    if size == 0:
        # Nothing moved (unsupported pair or no kernel path): the
        # ORIGINAL sequential loop verbatim — pipes/sockets can only
        # be read sequentially (pread would ESPIPE).
        while True:
            try:
                chunk = os.read(src_fd, _CHUNK)
            except OSError as exc:
                raise RuntimeError("failed reading source: %s" % (exc,))
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                try:
                    n = os.write(memfd, view)
                except OSError as exc:
                    raise RuntimeError(
                        "failed writing ingress: %s" % (exc,))
                size += n
                view = view[n:]
        return memfd, size
    # Partial kernel copy then failure (seekable source by
    # construction — explicit offsets already worked): finish with
    # pread/pwrite at the exact frontier.
    while True:
        try:
            chunk = os.pread(src_fd, _CHUNK, size)
        except OSError as exc:
            raise RuntimeError("failed reading source: %s" % (exc,))
        if not chunk:
            break
        view = memoryview(chunk)
        off = size
        while view:
            try:
                n = os.pwrite(memfd, view, off)
            except OSError as exc:
                raise RuntimeError(
                    "failed writing ingress: %s" % (exc,))
            view = view[n:]
            off += n
            size += n
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
    if mode == "splice":
        # Passthrough: no Python payload exists downstream. _validate
        # already required payload=None; the marker carries the mode so
        # run/map/stream dispatch to the C-loop executors below.
        return None, "splice"
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


def run(payload, source, *, mode="python", sink=None, order="none",
        lines=None, bytes=None, workers=None, nodes="auto",
        on_error="retry", streaming=None, orchestrator=None):
    """Run payload over source in parallel. See module docstring for v0 scope.

    mode="python": payload is "pkg.mod:func" | callable (Batch -> bytes).
    mode="spawn": payload is a command (str | list) executed per batch
      with batch bytes on stdin; stdout captured as the result.
    mode="plugin": payload is "path:function" (C .so entry point per the
      v0 Python-side convention — see _plugin.py ABI notice).
    mode="splice": kernel passthrough (bash -b equivalent) — NOT valid
      for run() (it produces output records); use map()/stream() with
      payload=None and bytes=N (default 512KB).
    streaming: None (default) auto-detects (fifo/socket sources stream,
      files materialize); True forces streaming ingest (bounded ingress
      via the fallow reaper — TB-scale/unbounded sources); False forces
      the materialized path.
    orchestrator: None (default) = current fork-and-wait behavior;
      True = W-PY19 reactor supervision (death pipes, bounded respawn,
      trap-ACK confirmation, C orderer for order="index"). False =
      current behavior explicitly. The reactor is additive: identical
      results, stronger fault tolerance.
    """
    _validate(payload, source, mode=mode, sink=sink, order=order,
              lines=lines, bytes_=bytes, workers=workers, nodes=nodes,
              on_error=on_error, streaming=streaming)
    orchestrator = _validate_orchestrator(orchestrator)
    if mode not in ("python", "spawn", "plugin", "splice"):
        raise NotImplementedError(
            "unknown mode %r" % (mode,))
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    payload, mode = _coerce_payload(payload, mode)
    if mode == "splice":
        raise ValueError(
            "mode='splice' produces output records — use map() or "
            "stream() (payload=None, bytes=N).")
    if _detect_streaming(source, streaming):
        if orchestrator:
            with _RUN_LOCK:
                _execute_ingest_reactor_locked(
                    payload, source, sink=sink, lines=lines,
                    bytes_=bytes, workers=_resolve_workers(workers),
                    on_error=on_error, collect=False, order=order,
                    mode=mode, nodes=nodes)
            return None
        _execute_ingest(payload, source, sink=sink, lines=lines,
                        bytes_=bytes, workers=_resolve_workers(workers),
                        on_error=on_error, collect=False, order=order,
                        mode=mode, nodes=nodes)
        return None
    if orchestrator:
        with _RUN_LOCK:
            _execute_reactor_locked(
                payload, source, sink=sink, lines=lines, bytes_=bytes,
                workers=_resolve_workers(workers), on_error=on_error,
                collect=False, order=order, mode=mode, nodes=nodes)
        return None
    _execute(payload, source, sink=sink, lines=lines, bytes_=bytes,
             workers=_resolve_workers(workers), on_error=on_error,
             collect=False, order=order)
    return None


def map(payload, source, **kwargs):
    """Batch-granular map: payload(Batch) -> result per batch, ordered by
    batch_index. v0 collects parent-side after workers exit (not streaming).

    mode="splice": kernel passthrough (payload must be None) — each
      result blob is one input byte-window (bytes=N, default 512KB).

    orchestrator=True: W-PY19 reactor supervision (death pipes,
      bounded respawn, trap-ACK, C orderer for order="index").
      Default None = current fork-and-wait behavior.
    """
    mode = kwargs.get("mode", "python")
    nodes = kwargs.get("nodes", "auto")
    _validate(payload, source, mode=mode, sink=None,
              order=kwargs.get("order", "none"), lines=kwargs.get("lines"),
              bytes_=kwargs.get("bytes"), workers=kwargs.get("workers"),
              nodes=nodes, on_error=kwargs.get("on_error", "retry"),
              streaming=kwargs.get("streaming"))
    orchestrator = _validate_orchestrator(kwargs.get("orchestrator"))
    payload, mode = _coerce_payload(payload, mode)
    order = kwargs.get("order", "none")
    if mode == "splice":
        _require_splice_symbol()
        b = kwargs.get("bytes") or _SPLICE_DEFAULT_BYTES
        if _detect_streaming(source, kwargs.get("streaming")):
            if orchestrator:
                with _RUN_LOCK:
                    return _execute_ingest_reactor_locked(
                        None, source, sink=None, lines=None, bytes_=b,
                        workers=_resolve_workers(kwargs.get("workers")),
                        on_error=kwargs.get("on_error", "retry"),
                        collect=True, order=order, mode=mode,
                        nodes=nodes, splice=True)
            return _execute_ingest(
                None, source, sink=None, lines=None, bytes_=b,
                workers=_resolve_workers(kwargs.get("workers")),
                on_error=kwargs.get("on_error", "retry"),
                collect=True, order=order, mode=mode, nodes=nodes,
                splice=True)
        if orchestrator:
            with _RUN_LOCK:
                return _execute_reactor_locked(
                    None, source, sink=None, lines=None, bytes_=b,
                    workers=_resolve_workers(kwargs.get("workers")),
                    on_error=kwargs.get("on_error", "retry"),
                    collect=True, order=order, mode=mode, nodes=nodes,
                    splice=True)
        return _execute(
            None, source, sink=None, lines=None, bytes_=b,
            workers=_resolve_workers(kwargs.get("workers")),
            on_error=kwargs.get("on_error", "retry"),
            collect=True, order=order, mode=mode, nodes=nodes,
            splice=True)
    if _detect_streaming(source, kwargs.get("streaming")):
        if orchestrator:
            with _RUN_LOCK:
                return _execute_ingest_reactor_locked(
                    payload, source, sink=None,
                    lines=kwargs.get("lines"),
                    bytes_=kwargs.get("bytes"),
                    workers=_resolve_workers(kwargs.get("workers")),
                    on_error=kwargs.get("on_error", "retry"),
                    collect=True, order=order, mode=mode, nodes=nodes)
        return _execute_ingest(
            payload, source, sink=None, lines=kwargs.get("lines"),
            bytes_=kwargs.get("bytes"),
            workers=_resolve_workers(kwargs.get("workers")),
            on_error=kwargs.get("on_error", "retry"),
            collect=True, order=order, mode=mode, nodes=nodes)
    if orchestrator:
        with _RUN_LOCK:
            return _execute_reactor_locked(
                payload, source, sink=None,
                lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
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

    orchestrator=True: W-PY19 reactor supervision (death pipes,
      bounded respawn, trap-ACK, C orderer for order="index").
      Default None = current streaming behavior.
    """
    _validate(payload, source, mode=kwargs.get("mode", "python"),
              sink=None, order=kwargs.get("order", "none"),
              lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
              workers=kwargs.get("workers"),
              nodes=kwargs.get("nodes", "auto"),
              on_error=kwargs.get("on_error", "retry"),
              streaming=kwargs.get("streaming"))
    orchestrator = _validate_orchestrator(kwargs.get("orchestrator"))
    payload, engine_mode = _coerce_payload(payload, kwargs.get("mode",
                                                               "python"))
    kwargs = dict(kwargs, mode=engine_mode)
    if engine_mode == "splice":
        _require_splice_symbol()
        b = kwargs.get("bytes") or _SPLICE_DEFAULT_BYTES
        if _detect_streaming(source, kwargs.get("streaming")):
            if orchestrator:
                return _splice_ingest_stream_reactor_gen(
                    source, bytes_=b,
                    workers=_resolve_workers(kwargs.get("workers")),
                    on_error=kwargs.get("on_error", "retry"),
                    nodes=kwargs.get("nodes", "auto"),
                    order=kwargs.get("order", "none"))
            return _splice_ingest_stream_gen(
                source, bytes_=b,
                workers=_resolve_workers(kwargs.get("workers")),
                on_error=kwargs.get("on_error", "retry"),
                nodes=kwargs.get("nodes", "auto"),
                order=kwargs.get("order", "none"))
        if orchestrator:
            return _splice_stream_reactor_gen(
                source, bytes_=b,
                workers=_resolve_workers(kwargs.get("workers")),
                on_error=kwargs.get("on_error", "retry"),
                nodes=kwargs.get("nodes", "auto"),
                order=kwargs.get("order", "none"))
        return _splice_stream_gen(
            source, bytes_=b,
            workers=_resolve_workers(kwargs.get("workers")),
            on_error=kwargs.get("on_error", "retry"),
            nodes=kwargs.get("nodes", "auto"),
            order=kwargs.get("order", "none"))
    if _detect_streaming(source, kwargs.get("streaming")):
        if orchestrator:
            return _ingest_stream_reactor_gen(payload, source, **kwargs)
        return _ingest_stream_gen(payload, source, **kwargs)
    if orchestrator:
        return _stream_reactor_gen(payload, source, **kwargs)
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


def _splice_stream_gen(source, *, bytes_, workers, on_error, nodes,
                       order):
    # W-PY18 stream() over the C passthrough loop (materialized
    # ingest, live results): yields raw byte-windows as they arrive.
    yield from _execute_streaming(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, mode="splice", nodes=nodes, order=order,
        splice=True)


def _splice_ingest_stream_gen(source, *, bytes_, workers, on_error,
                              nodes, order):
    # W-PY18 stream() over passthrough + streaming ingest (unbounded
    # in, live out — the bash -s shape): spill and drain interleave.
    yield from _execute_ingest_stream(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, mode="splice", nodes=nodes, order=order,
        splice=True)


def _stream_reactor_gen(payload, source, **kwargs):
    # W-PY19 stream() under reactor supervision (materialized input,
    # live drain): identical ordering contract to _stream_gen, plus
    # death pipes, bounded respawn, and trap-ACK confirmation.
    yield from _execute_streaming_reactor(
        payload, source,
        lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
        workers=_resolve_workers(kwargs.get("workers")),
        on_error=kwargs.get("on_error", "retry"),
        mode=kwargs.get("mode", "python"), nodes=kwargs.get("nodes", "auto"),
        order=kwargs.get("order", "none"),
        splice=kwargs.get("mode") == "splice")


def _splice_stream_reactor_gen(source, *, bytes_, workers, on_error,
                               nodes, order):
    # W-PY19 stream() over splice + reactor (materialized ingest,
    # live results, respawn on death). Python reassembly only (the C
    # orderer needs OrderPackets the splice loop never sends).
    yield from _execute_streaming_reactor(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, mode="splice", nodes=nodes, order=order,
        splice=True)


def _ingest_stream_reactor_gen(payload, source, **kwargs):
    # W-PY19 stream() over a streaming source under the reactor:
    # live drain interleaved with the spill (pump hook), scanner
    # death pipe, spawn-pipe dynamic scaling.
    yield from _execute_ingest_stream_reactor(
        payload, source,
        lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
        workers=_resolve_workers(kwargs.get("workers")),
        on_error=kwargs.get("on_error", "retry"),
        mode=kwargs.get("mode", "python"), nodes=kwargs.get("nodes", "auto"),
        order=kwargs.get("order", "none"))


def _splice_ingest_stream_reactor_gen(source, *, bytes_, workers,
                                      on_error, nodes, order):
    # W-PY19 stream() over splice + streaming ingest + reactor.
    yield from _execute_ingest_stream_reactor(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, mode="splice", nodes=nodes, order=order,
        splice=True)


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
    reassembly = ReassemblyBuffer() if order == "index" else None
    # W-PY16: pids is a LIVE list — workers may be forked mid-drain
    # (streaming ingest forks them on first publish). per_worker grows
    # on demand and alive picks up late additions each round, so signals
    # from late workers are never dropped and late workers are reaped.
    per_worker = [[0, b""] for _ in range(len(pids))]
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
            if 0 <= wid:
                while len(per_worker) <= wid:
                    per_worker.append([0, b""])
                for _bidx, blob in _drain_worker_memfd(
                        out_fds[wid], per_worker[wid]):
                    if reassembly is None:
                        yield blob
                    else:
                        reassembly.add(_bidx, blob)
                        for _, ordered in reassembly.drain():
                            yield ordered
        alive.update(pids)
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
    for wid in range(len(per_worker)):
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


def _require_splice_symbol():
    """Raise a clear error when the substrate predates the splice loop
    (pre-W-PY18 .so): mode="splice" has no v0 fallback (there is no
    Python equivalent of a zero-Python loop), unlike spawn/plugin/emit.
    """
    from ._bindings import v1_available as _v1a

    if not _v1a()["splice"]:
        raise RuntimeError(
            "mode='splice' needs fr_py_worker_splice_loop — rebuild "
            "the substrate ('make -f Makefile.substrate "
            "python-substrate')")


def _fork_splice_worker(lib, wid, memfd, out_fd, signal_w, fallow_w,
                        engine_fds):
    """Fork one C-loop passthrough worker (W-PY18 mode="splice").

    The child scrubs to engine + job fds, initializes worker state via
    ctypes (one call — per-batch work stays in C), then runs
    fr_py_worker_splice_loop to EOF. Returns the child pid in the
    parent; the child never returns (os._exit with the loop rc mapped
    to 0/1 — the parent's failed-check treats nonzero as failure).
    signal_w/fallow_w may be None (→ -1 disarm, map/materialized).
    out_fd must be a parent-created output memfd (never None: splice
    always frames records for the parent to parse).
    """
    pid = os.fork()
    if pid == 0:
        try:
            keep = set(engine_fds) | {memfd, out_fd}
            if signal_w is not None:
                keep.add(signal_w)
            if fallow_w is not None and fallow_w >= 0:
                keep.add(fallow_w)
            scrub_fds(keep)
        except Exception:
            pass
        try:
            if lib.fr_py_worker_init(wid, 0, 0, 3, 0) != 0:
                os._exit(1)
            rc = lib.fr_py_worker_splice_loop(
                wid, memfd, out_fd,
                signal_w if signal_w is not None else -1,
                fallow_w if fallow_w is not None else -1)
        except BaseException:
            rc = 1
        os._exit(0 if rc == 0 else 1)
    return pid


def _execute_streaming(payload, source, *, lines, bytes_, workers,
                       on_error, mode="python", nodes="auto",
                       order="none", stats=None, splice=False):
    """v1 streaming pipeline: a GENERATOR. Fork happens on first next(),
    blobs yield in worker-completion order (order="none") or batch_idx
    sequence (order="index", parent-side reassembly) while workers run.
    Failure accounting + poison summary run at exhaustion. Abandoning the
    generator (close/GC/exception) tears down workers via the finally.
    stats (optional dict): white-box drain diagnostics (reassembly_max).
    splice (W-PY18): children run the C passthrough loop (no payload).
    """
    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    if order not in ("none", "index"):
        raise ValueError(
            "order must be 'none' or 'index', got %r" % (order,))
    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")
    # Engine fds for child keep sets (W-PY16 addendum scrub).
    engine_fds = snapshot_fds() - pre_fds

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
            if splice:
                # W-PY18: C-loop passthrough worker (signal live).
                pids.append(_fork_splice_worker(
                    lib, i, memfd, out_fds[i], signal_w, None,
                    engine_fds))
                continue
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
                # W-PY16 addendum: scrub host event-loop fds.
                try:
                    scrub_fds(engine_fds | {memfd, out_fds[i],
                                            signal_w})
                except Exception:
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
                           order="none", stats=None, splice=False):
    """stream() over a streaming source: a GENERATOR (W-PY16).

    Same fork topology as _execute_ingest_locked (reaper + scanner +
    workers, file_size=-1, fallow acks), but the parent interleaves the
    spill with the live drain in one thread: each drain-loop iteration
    runs pump(), which spill-quantum-drains the (nonblocking) source
    until EAGAIN and issues the ingest gate at source EOF. First results
    can arrive before the source is exhausted (slow-source pipelining).
    Abandonment tears everything down via the finally (helpers reaped
    through extra_pids). Mirrors _execute_streaming's guard convention.
    splice (W-PY18): workers run the C passthrough loop.
    """
    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    if order not in ("none", "index"):
        raise ValueError(
            "order must be 'none' or 'index', got %r" % (order,))
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")
    # Engine fds for child keep sets (see locked path).
    engine_fds = snapshot_fds() - pre_fds

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
    spill = {"off": 0}  # pwrite cursor (shared fd offset stays 0)
    state = {"workers": False, "stall": False, "fork_at": 0.0,
             "t_start": _time.monotonic()}
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
            lib, memfd, fallow_r, fallow_w, engine_fds)

        def _drop_parent_copies():
            # Idempotent parent-side close of signal + fallow copies.
            # Signal EOF needs every write end closed; reaper EOF the
            # same. Runs at worker fork (every child exists) and on the
            # empty-input done path (no workers will ever exist).
            nonlocal signal_w, fallow_r, fallow_w
            if signal_w is not None:
                try:
                    os.close(signal_w)
                except OSError:
                    pass
                signal_w = None
            if fallow_r is not None:
                try:
                    os.close(fallow_r)
                except OSError:
                    pass
                fallow_r = None
            if fallow_w is not None:
                try:
                    os.close(fallow_w)
                except OSError:
                    pass
                fallow_w = None

        def _fork_workers():
            # Single fork event (also closes the parent's signal +
            # fallow write copies here: every child exists, so EOF on
            # both means every worker exited).
            for i in range(workers):
                if splice:
                    # W-PY18: C-loop passthrough (signal live, fallow).
                    pids.append(_fork_splice_worker(
                        lib, i, memfd, out_fds[i], signal_w, fallow_w,
                        engine_fds))
                    continue
                pid = os.fork()
                if pid == 0:
                    try:
                        scrub_fds(engine_fds | {memfd, out_fds[i],
                                                signal_w, fallow_w})
                    except Exception:
                        pass
                    worker_main(i, payload, None, memfd, -1, out_fds[i],
                                signal_w, on_error, fallow_w)
                    os._exit(127)  # unreachable; worker_main exits
                else:
                    pids.append(pid)
            _drop_parent_copies()
            state["workers"] = True
            state["fork_at"] = _time.monotonic()

        def _watch_live():            # Same helper-liveness rule as the locked path (abort +
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

        def _maybe_fork_workers():
            # Fork-timing rule (see module constants): first DATA
            # publish, or stall timeout pre-gate (slow-source
            # pipelining). Post-gate waits for publish (CASE A).
            if state["workers"]:
                return True
            try:
                ready = lib.fr_py_data_ready()
            except Exception:
                ready = 0
            if ready > 0:
                _fork_workers()
                return True
            if not gate["issued"] and (
                    _time.monotonic() - state["t_start"]
                    ) >= STALL_FORK_AFTER:
                state["stall"] = True
                _fork_workers()
                return True
            return False

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
            # One drain-loop quantum. Returns True when ingest is fully
            # done: gate issued AND (workers forked OR input was empty).
            # Side effects: forks workers per the timing rule, spills
            # source quanta via pwrite, issues the gate (with the
            # post-stall-fork grace). Raises on helper death / anomaly.
            _watch_live()
            if not state["workers"]:
                if gate["issued"]:
                    # Post-gate wait: fork on first publish (CASE-A
                    # completion); empty input is done; a reaped
                    # scanner with spilled-but-unpublished bytes is a
                    # loud anomaly (never silent loss).
                    try:
                        ready = lib.fr_py_data_ready()
                    except Exception:
                        ready = 0
                    if ready > 0:
                        _fork_workers()
                    elif helpers["scan_rc"] is not None:
                        if spill["off"] == 0:
                            # Empty input: drop parent copies (signal
                            # EOF + reaper EOF) and finish — no workers
                            # will ever exist.
                            _drop_parent_copies()
                            return True
                        raise RuntimeError(
                            "forkrun: ingest scanner published no "
                            "data for %d spilled bytes" % spill["off"])
                    else:
                        return False
                else:
                    _maybe_fork_workers()
            if gate["issued"]:
                return state["workers"] or spill["off"] == 0
            while True:
                try:
                    chunk = os.read(src_fd, _CHUNK)
                except BlockingIOError:
                    return False
                except OSError as exc:
                    raise RuntimeError(
                        "failed reading source: %s" % (exc,))
                if not chunk:
                    # Source EOF: gate now, unless a stall-triggered
                    # fork is younger than the grace (withhold until
                    # first publish or grace expiry — never gate
                    # pre-phase-1-entry).
                    if state["stall"] and (
                            _time.monotonic() - state["fork_at"]
                            ) < POST_FORK_GATE_GRACE:
                        try:
                            ready = lib.fr_py_data_ready()
                        except Exception:
                            ready = 0
                        if ready == 0:
                            return False
                    if lib.fr_py_ingest_done() != RC_OK:
                        raise RuntimeError("ingest signal failed")
                    gate["issued"] = True
                    if spill["off"] == 0 and not state["workers"]:
                        # Empty input with no workers: drop parent
                        # copies and finish.
                        _drop_parent_copies()
                    return state["workers"] or spill["off"] == 0
                # pwrite at explicit offsets (see locked path): never
                # move the shared fd offset under the scanner.
                view = memoryview(chunk)
                while view:
                    try:
                        n = os.pwrite(memfd, view, spill["off"])
                    except OSError as exc:
                        raise RuntimeError(
                            "failed writing ingress: %s" % (exc,))
                    view = view[n:]
                    spill["off"] += n
                _maybe_fork_workers()
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

        # Scanner join: strict when observed, proof-based when already
        # reaped by teardown after healthy workers + complete drain
        # (workers cannot EOF without a clean scanner finish; see the
        # locked path for the full argument).
        if scan_pid is not None and helpers["scan_rc"] is None:
            try:
                wpid, scan_st = os.waitpid(scan_pid, os.WNOHANG)
            except ChildProcessError:
                wpid, scan_st = scan_pid, None
            if wpid == 0:
                try:
                    _, scan_st = os.waitpid(scan_pid, 0)
                except ChildProcessError:
                    scan_st = None
            if scan_st is not None and not (
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
                    on_error, collect, order, mode="python", nodes="auto",
                    splice=False):
    """Streaming-ingest entry for map/run (blocking, like _execute)."""
    if mode not in ("python", "splice"):
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
            order=order, splice=splice)


def _fork_ingest_helpers(lib, memfd, fallow_r, fallow_w, engine_fds):
    """Fork the fallow reaper + scanner children (W-PY16).

    Both run long-lived engine loops concurrently with the parent's
    spill: the reaper punches holes behind the contiguous acked prefix
    (bounded ingress), the scanner publishes batches as bytes land
    (its pread loop waits on !ingest_complete — the bash topology).
    Returns (fallow_pid, scan_pid). Children scrub to their keep set
    (engine fds + job fds; _fd_scrub) and never return (os._exit).
    The caller forks workers after; the parent closes its fallow copies
    once every child exists (reaper EOF = workers' write ends only).
    """
    fallow_pid = os.fork()
    if fallow_pid == 0:
        try:
            scrub_fds(engine_fds | {fallow_r, memfd})
            rc = lib.fr_py_fallow_loop(fallow_r, memfd)
        except BaseException:
            rc = 1
        os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
    scan_pid = os.fork()
    if scan_pid == 0:
        try:
            scrub_fds(engine_fds | {memfd})
            rc = lib.fr_py_scan(memfd)
        except BaseException:
            rc = 1
        os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
    return fallow_pid, scan_pid


def _execute_ingest_locked(payload, source, *, sink, lines, bytes_,
                           workers, on_error, collect, order,
                           splice=False):
    """map/run over a streaming source (W-PY16, collect/discard).

    Pipeline: init → ingress memfd → output memfds → fallow pipe →
    fork reaper + scanner → spill in 1MB chunks (WNOHANG helper
    watches) → fork workers ON FIRST DATA PUBLISH (never during
    pre-flight: a waiting worker trips the pre-flight bail, and phase 1
    entered with already-complete input publishes nothing) → ingest
    gate → waitpid workers → join scanner (strict) + reaper (lenient)
    → poison summary → parse. Ingress stays bounded: the reaper punches
    acked prefixes while the spill advances. Slow sources (no publish
    within STALL_FORK_AFTER, gate still open) fork workers anyway for
    pipelining — the input is still arriving, the shape CASE B handles.
    """
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")
    # Engine fds (escrow/eventfds, born in init) stay open in every
    # child: closing them breaks escrow retry and forces claim-polling
    # into POLLNVAL spins. Differenced out of the pre-init baseline so
    # host event-loop fds are never kept.
    engine_fds = snapshot_fds() - pre_fds

    src_fd, must_close = _open_source(source)
    memfd = None
    mem_hold: list = []
    out_fds: list = []
    out_hold: list = []
    fallow_r = fallow_w = None
    fallow_pid = scan_pid = None
    helpers = {"scan_rc": None, "fallow_rc": None}
    gate_issued = False
    workers_forked = False
    stall_forked = False
    fork_at = 0.0
    total_written = 0
    t_start = _time.monotonic()
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
            lib, memfd, fallow_r, fallow_w, engine_fds)

        def _drop_fallow_copies():
            # Idempotent parent-side close (normal flow closes here;
            # teardown re-closes safely). Reaper EOF needs every write
            # end closed — including the parent's copy.
            nonlocal fallow_r, fallow_w
            if fallow_r is not None:
                try:
                    os.close(fallow_r)
                except OSError:
                    pass
                fallow_r = None
            if fallow_w is not None:
                try:
                    os.close(fallow_w)
                except OSError:
                    pass
                fallow_w = None

        def _fork_workers():
            # Forked at most once, on first DATA publish (pre-flight is
            # provably over — publishing happens only in the main loop),
            # on stall timeout (slow source, gate still open), or never
            # (empty input: nothing to consume). Closes parent fallow
            # copies here: every child exists, so reaper EOF = workers.
            nonlocal workers_forked, stall_forked
            nonlocal fork_at
            for i in range(workers):
                if splice:
                    # W-PY18: C-loop passthrough (fallow acks included;
                    # file growth is irrelevant — the loop splices by
                    # explicit offsets, never mmaps).
                    pids.append(_fork_splice_worker(
                        lib, i, memfd,
                        out_fds[i] if collect else None, None, fallow_w,
                        engine_fds))
                    continue
                pid = os.fork()
                if pid == 0:
                    try:
                        scrub_fds(engine_fds | {memfd, fallow_w} |
                                  ({out_fds[i]} if collect else set()))
                    except Exception:
                        pass
                    worker_main(i, payload, sink, memfd, -1,
                                out_fds[i] if collect else None, None,
                                on_error, fallow_w)
                    os._exit(127)  # unreachable; worker_main exits
                else:
                    pids.append(pid)
            _drop_fallow_copies()
            workers_forked = True
            fork_at = _time.monotonic()

        def _watch_helpers():
            # Reap helper deaths (nonblocking). Scanner death is fatal
            # (unpublished tail would be silently lost); reaper death
            # aborts too (acks would EPIPE and fail workers — fail fast
            # instead of spilling pointlessly). Scanner exit 0 before
            # the gate is equally fatal: it can only exit 0 via the EOF
            # gate, so an early 0 means the tail it never saw is lost.
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

        def _maybe_fork_workers():
            # The fork-timing rule (see module constants): data publish
            # always forks; the stall timeout only fires pre-gate (slow
            # source → CASE-B pipelining). Returns True when workers
            # exist (or the empty-input skip was taken by the caller).
            nonlocal stall_forked
            if workers_forked:
                return True
            try:
                ready = lib.fr_py_data_ready()
            except Exception:
                ready = 0
            if ready > 0:
                _fork_workers()
                return True
            if not gate_issued and (
                    _time.monotonic() - t_start) >= STALL_FORK_AFTER:
                stall_forked = True
                _fork_workers()
                return True
            return False

        try:
            while True:
                try:
                    chunk = os.read(src_fd, _CHUNK)
                except OSError as exc:
                    raise RuntimeError(
                        "failed reading source: %s" % (exc,))
                if not chunk:
                    break
                # pwrite at explicit offsets (W-PY16): the scanner seeds
                # its base with lseek(SEEK_CUR) at startup, and that
                # offset is SHARED with our fd across fork. os.write
                # would advance it under a late-starting scanner (base
                # lands at end-of-spill: sentinel-only publish). pwrite
                # never moves it — the scanner always observes base 0.
                view = memoryview(chunk)
                while view:
                    try:
                        n = os.pwrite(memfd, view, total_written)
                    except OSError as exc:
                        raise RuntimeError(
                            "failed writing ingress: %s" % (exc,))
                    view = view[n:]
                    total_written += n
                _watch_helpers()
                _maybe_fork_workers()
        except KeyboardInterrupt:
            lib.fr_py_abort()
            raise
        # Post-stall-fork gate grace: after a stall-triggered fork, the
        # gate must not land before phase-1 entry (entry follows the
        # bail within ms; the grace is conservative). Otherwise gate at
        # source EOF unconditionally — pre-flight is either over
        # (publish observed) or gate-bound (CASE A completes it).
        if stall_forked:
            while True:
                try:
                    ready = lib.fr_py_data_ready()
                except Exception:
                    ready = 0
                if ready > 0:
                    break
                if (_time.monotonic() - fork_at) >= POST_FORK_GATE_GRACE:
                    break
                _watch_helpers()
                _time.sleep(0.05)
        if lib.fr_py_ingest_done() != RC_OK:
            raise RuntimeError("ingest signal failed")
        gate_issued = True
        # Post-gate: fork on first publish (CASE-A completion); empty
        # input (nothing spilled, scanner reaped) skips workers; a
        # reaped scanner with spilled-but-unpublished bytes is a loud
        # anomaly (never silent loss).
        if not workers_forked:
            while True:
                try:
                    ready = lib.fr_py_data_ready()
                except Exception:
                    ready = 0
                if ready > 0:
                    _fork_workers()
                    break
                _watch_helpers()
                if helpers["scan_rc"] is not None:
                    if total_written == 0:
                        # Empty input: drop the fallow copies (reaper
                        # EOF) and skip workers — nothing to consume.
                        _drop_fallow_copies()
                        break
                    raise RuntimeError(
                        "forkrun: ingest scanner published no data "
                        "for %d spilled bytes" % total_written)
                _time.sleep(0.05)

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

        # Join the scanner (strict) and the reaper (lenient warn).
        # helpers["scan_rc"] set means _watch_helpers observed the exit
        # during the run — check it. Otherwise the scanner is either
        # still alive (blocking join) or was already reaped by teardown
        # after healthy workers + complete drain — which PROVES a clean
        # finish (workers cannot reach EOF without scanner_finished, and
        # any crash/abort fails workers first). Same leniency the
        # reaper has always had.
        if scan_pid is not None and helpers["scan_rc"] is None:
            try:
                wpid, scan_st = os.waitpid(scan_pid, os.WNOHANG)
            except ChildProcessError:
                wpid, scan_st = scan_pid, None
            if wpid == 0:
                try:
                    _, scan_st = os.waitpid(scan_pid, 0)
                except ChildProcessError:
                    scan_st = None
            if scan_st is not None and not (
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
             collect, order, mode="python", nodes="auto", splice=False):
    if mode not in ("python", "splice"):
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
                               order=order, splice=splice)


def _execute_locked(payload, source, *, sink, lines, bytes_, workers,
                    on_error, collect, order, splice=False):
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")
    # Engine fds for child keep sets (W-PY16 addendum: scrub host
    # event-loop fds in every forked child, keep engine + job fds).
    engine_fds = snapshot_fds() - pre_fds

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
            if splice:
                # W-PY18: C-loop passthrough (no Python payload).
                # out_fd always present here (splice requires
                # collect; run() rejects the mode).
                pids.append(_fork_splice_worker(
                    lib, i, memfd, out_fds[i], None, None,
                    engine_fds))
                continue
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
                try:
                    scrub_fds(engine_fds | {memfd} |
                              ({out_fds[i]} if collect else set()))
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


# =====================================================================
# W-PY19 reactor executors — orchestrator=True paths.
#
# Same pipelines as the default executors above, but workers are
# supervised by ReactorState/ ­reactor_loop (death pipes, bounded
# respawn, trap-ACK grace) instead of plain waitpid. Additive:
# identical results on the healthy path; the reactor only changes
# what happens when a worker dies (respawn + continue vs abort).
# =====================================================================

def _reactor_poison_summary(lib, state) -> None:
    """Poison summary: engine scalar count + reactor batch list."""
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
    if getattr(state, "poisoned_batches", None):
        from ._reactor import report_poisoned as _report
        _report(state.poisoned_batches)
    if getattr(state, "recovered", None):
        try:
            os.write(2, ("forkrun [WARN]: %d worker death(s) recovered "
                         "via respawn (wid(s) %s).\n"
                         % (len(state.recovered),
                            ",".join(str(w) for w in state.recovered))
                         ).encode())
        except OSError:
            pass


def _reactor_failure_check(state, n_workers, on_error) -> None:
    """Raise when the reactor run lost work (cap-reached deaths)."""
    if getattr(state, "n_unrecovered", 0):
        raise RuntimeError(
            "forkrun: %d worker(s) failed without recovery "
            "(respawn cap reached) (on_error=%s)"
            % (state.n_unrecovered, on_error))


def _teardown_reactor(lib, state, *, signal_r=None, out_fds=(),
                      out_hold=None, memfd=None, mem_hold=None,
                      src_fd=None, must_close=False, extra_pids=(),
                      orderer_pid=None, order_r=None, order_w=None,
                      trap_r=None, trap_w=None, coll_fd=None,
                      coll_hold=None):
    """Kill stray reactor children + close-all + destroy (abandon-safe).

    Mirrors _teardown_stream: fire alarm first (unblocks claim-gated
    workers), SIGKILL stragglers, reap everything (zombies pin PIDs,
    so no PID-reuse hazard), then close fds and destroy. The reactor
    already reaped supervised workers; this covers the orderer,
    scanner/fallow helpers, and any respawn racing teardown.
    """
    try:
        lib.fr_py_abort()
    except Exception:
        pass
    live = []
    if state is not None:
        for slot in list(state.workers.values()):
            if slot.alive:
                live.append(slot.pid)
            if slot.death_r is not None and slot.death_r >= 0:
                try:
                    os.close(slot.death_r)
                except OSError:
                    pass
                slot.death_r = -1
    for pid in live:
        try:
            wpid, _ = os.waitpid(pid, os.WNOHANG)
            if wpid == 0:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
        except ChildProcessError:
            pass
        except OSError:
            pass
    for pid in live:
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        except OSError:
            pass
    for pid in list(extra_pids) + ([orderer_pid]
                                   if orderer_pid is not None else []):
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
        except OSError:
            pass
    for pid in list(extra_pids) + ([orderer_pid]
                                   if orderer_pid is not None else []):
        if pid is None:
            continue
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        except OSError:
            pass
    for fd in list(out_fds):
        try:
            os.close(fd)
        except OSError:
            pass
    if out_hold is not None:
        out_hold.clear()
    if mem_hold is not None:
        mem_hold.clear()
    for fd in (signal_r, order_r, order_w, trap_r, trap_w, coll_fd,
               memfd):
        if fd is None or fd < 0:
            continue
        try:
            os.close(fd)
        except OSError:
            pass
    if coll_hold is not None:
        coll_hold.clear()
    if must_close and src_fd is not None:
        try:
            os.close(src_fd)
        except OSError:
            pass
    try:
        lib.fr_py_destroy()
    except Exception:
        pass


def _execute_reactor_locked(payload, source, *, sink, lines, bytes_,
                            workers, on_error, collect, order,
                            mode="python", nodes="auto", splice=False):
    """Materialized map/run under reactor supervision (blocking).

    init → spill → sync scan → (output memfds) → (order pipe +
    orderer for collect+order=index, non-splice) → trap-ACK pipe →
    fork N workers with death pipes → reactor_loop → failure
    accounting → parse (collection file when the C orderer ran, else
    per-worker memfds) → teardown. Raises RuntimeError on trap-ACK
    timeout (catastrophic) or unrecovered deaths (cap reached).
    """
    from ._bindings import v1_available as _v1a
    from ._reactor import (ORDER_PIPE_SIZE, ReactorState, reactor_run,
                           spawn_orderer)
    import fcntl as _fcntl

    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")
    engine_fds = snapshot_fds() - pre_fds

    src_fd, must_close = _open_source(source)
    memfd = None
    out_fds: list = []
    out_hold: list = []
    order_r = order_w = None
    coll_fd = None
    coll_hold: list = []
    orderer_pid = None
    trap_r = trap_w = None
    state = None
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

        if collect:
            out_fds, out_hold = _new_output_memfds(workers)

        # C orderer for collect+index (non-splice only: the splice
        # loop never sends OrderPackets, so the orderer would emit
        # nothing — splice keeps Python parse+sort). Missing symbol
        # (pre-W-PY19 .so) falls back to Python reassembly silently.
        use_orderer = (collect and order == "index" and not splice
                       and _v1a(lib).get("orderer"))
        if use_orderer:
            order_r, order_w = os.pipe()
            try:
                _fcntl.fcntl(order_w, _fcntl.F_SETPIPE_SZ,
                             ORDER_PIPE_SIZE)
            except OSError:
                pass
            try:
                coll_fd = os.memfd_create("forkrun_ordered")
            except AttributeError:
                import tempfile as _tf
                _tmp = _tf.TemporaryFile(prefix="forkrun_ordered_")
                coll_hold.append(_tmp)
                coll_fd = _tmp.fileno()
            orderer_pid = spawn_orderer(order_r, coll_fd,
                                        engine_fds=engine_fds,
                                        out_fds=out_fds)

        trap_r, trap_w = os.pipe()

        state = ReactorState(workers, num_nodes=1,
                             respawn_cap=REACTOR_RESPAWN_CAP,
                             spawn_ceiling=workers)
        state.configure(payload_spec=payload, sink_spec=sink,
                        memfd=memfd, file_size=size,
                        out_fds=list(out_fds), signal_w=None,
                        fallow_w=-1,
                        order_w=order_w if use_orderer else -1,
                        trap_ack_w=trap_w, on_error=on_error,
                        engine_fds=engine_fds, splice=splice)
        state.trap_ack_r = trap_r
        for _ in range(workers):
            if state.spawn_worker(node=0) is None:
                break

        try:
            reactor_run(state)
        except KeyboardInterrupt:
            raise

        _reactor_failure_check(state, workers, on_error)

        # Orderer EOF: every worker write end is closed (all workers
        # reaped) — drop the parent's spare so the orderer finishes.
        if use_orderer:
            if order_w is not None:
                try:
                    os.close(order_w)
                except OSError:
                    pass
                order_w = None
                state.ctx["order_w"] = -1
            if orderer_pid is not None:
                try:
                    _, _ost = os.waitpid(orderer_pid, 0)
                except ChildProcessError:
                    _ost = 0
                if _ost != 0 and not (
                        os.WIFEXITED(_ost) and
                        os.WEXITSTATUS(_ost) == 0):
                    raise RuntimeError(
                        "forkrun: C orderer failed (status %r)"
                        % (_ost,))

        _reactor_poison_summary(lib, state)

        if not collect:
            return None
        if use_orderer:
            records = _parse_records(_read_fd_all(coll_fd))
            # Already batch_idx-ordered by the C orderer; no sort.
            return [blob for _, blob in records]
        records = []
        for fd in out_fds:
            records.extend(_parse_records(_read_fd_all(fd)))
        if order == "index":
            records.sort(key=lambda kv: kv[0])
        return [blob for _, blob in records]
    except KeyboardInterrupt:
        try:
            lib.fr_py_abort()
        except Exception:
            pass
        raise
    finally:
        _teardown_reactor(lib, state, out_fds=out_fds,
                          out_hold=out_hold, memfd=memfd,
                          src_fd=src_fd, must_close=must_close,
                          orderer_pid=orderer_pid, order_r=order_r,
                          order_w=order_w, trap_r=trap_r, trap_w=trap_w,
                          coll_fd=coll_fd, coll_hold=coll_hold)


def _execute_streaming_reactor(payload, source, *, lines, bytes_,
                               workers, on_error, mode="python",
                               nodes="auto", order="none", stats=None,
                               splice=False):
    """Materialized stream() under reactor supervision (generator).

    Fork happens on first next(); blobs yield live via the signal
    pipe while the reactor supervises deaths/respawns. order=index
    uses the C orderer (non-splice): the parent incrementally parses
    the orderer's collection file (already ordered — no Python
    reassembly buffer); order=none (or splice) drains per-worker
    memfds exactly like _execute_streaming. Abandonment tears down
    via the finally (reactor teardown kills strays).
    """
    from ._bindings import v1_available as _v1a
    from ._reactor import (ORDER_PIPE_SIZE, ReactorState, reactor_loop,
                           spawn_orderer)
    import fcntl as _fcntl
    import select as _select

    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    if order not in ("none", "index"):
        raise ValueError(
            "order must be 'none' or 'index', got %r" % (order,))
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")
    engine_fds = snapshot_fds() - pre_fds

    src_fd, must_close = _open_source(source)
    memfd = None
    out_fds: list = []
    out_hold: list = []
    signal_r = None
    signal_w = None
    spare_signal_w = None
    order_r = order_w = None
    coll_fd = None
    coll_hold: list = []
    orderer_pid = None
    trap_r = trap_w = None
    state = None
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
        signal_r, signal_w, _ = make_pipe()

        use_orderer = (order == "index" and not splice
                       and _v1a(lib).get("orderer"))
        if use_orderer:
            order_r, order_w = os.pipe()
            try:
                _fcntl.fcntl(order_w, _fcntl.F_SETPIPE_SZ,
                             ORDER_PIPE_SIZE)
            except OSError:
                pass
            try:
                coll_fd = os.memfd_create("forkrun_ordered")
            except AttributeError:
                import tempfile as _tf
                _tmp = _tf.TemporaryFile(prefix="forkrun_ordered_")
                coll_hold.append(_tmp)
                coll_fd = _tmp.fileno()
            orderer_pid = spawn_orderer(order_r, coll_fd,
                                        engine_fds=engine_fds,
                                        out_fds=out_fds)

        trap_r, trap_w = os.pipe()

        state = ReactorState(workers, num_nodes=1,
                             respawn_cap=REACTOR_RESPAWN_CAP,
                             spawn_ceiling=workers)
        state.configure(payload_spec=payload, sink_spec=None,
                        memfd=memfd, file_size=size,
                        out_fds=list(out_fds), signal_w=signal_w,
                        fallow_w=-1,
                        order_w=order_w if use_orderer else -1,
                        trap_ack_w=trap_w, on_error=on_error,
                        engine_fds=engine_fds, splice=splice)
        state.trap_ack_r = trap_r
        for _ in range(workers):
            if state.spawn_worker(node=0) is None:
                break
        # Parent drops its signal write copy for EOF detection; the
        # SPARE for future respawns is dup'd first (respawns need a
        # write end, but EOF needs every parent copy closed at the
        # end — the reactor closes the spare when no worker is live).
        spare_signal_w = os.dup(signal_w)
        try:
            os.close(signal_w)
        except OSError:
            pass
        signal_w = None
        state.ctx["signal_w"] = spare_signal_w

        # Drain state: per-worker (order=none/splice) or single
        # collection file (C orderer). Signals are wakeups only.
        _sig = struct.Struct("<QQ")
        if use_orderer:
            drain_state = [0, b""]
        else:
            drain_state = None
        per_worker = [[0, b""] for _ in range(workers)]
        sig_buf = b""
        sig_eof = False
        if order == "index" and not use_orderer:
            reassembly = ReassemblyBuffer()
        else:
            reassembly = None

        def _pump_drain():
            # One live-drain quantum: nonblocking signal read, then
            # incremental preads. Returns the next blob, None when no
            # complete record is available YET (not EOF — the reactor
            # keeps polling), or raises StopIteration when workers are
            # gone AND pipes EOF AND no buffered records remain (same
            # EOF-anchored rule as _drain_records).
            nonlocal sig_buf, sig_eof, spare_signal_w
            # No live worker left: drop the parent's spare signal
            # write end (kept for future respawns) so the signal
            # pipe hits EOF and the drain can terminate. Idempotent.
            if not any(s.alive for s in state.workers.values()):
                if spare_signal_w is not None and spare_signal_w >= 0:
                    try:
                        os.close(spare_signal_w)
                    except OSError:
                        pass
                    spare_signal_w = None
                    state.ctx["signal_w"] = -1
            if not sig_eof:
                try:
                    ready, _, _ = _select.select([signal_r], [], [], 0)
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
            if use_orderer:
                # Collection file is already ordered: parse the new
                # prefix, hold the short tail for the next quantum.
                try:
                    _sz = os.fstat(coll_fd).st_size
                except OSError:
                    _sz = drain_state[0]
                if _sz > drain_state[0]:
                    try:
                        _ch = os.pread(coll_fd, _sz - drain_state[0],
                                       drain_state[0])
                    except OSError:
                        _ch = b""
                    if _ch:
                        drain_state[0] += len(_ch)
                        recs, tail = _split_records(
                            drain_state[1] + _ch)
                        drain_state[1] = tail
                        if recs:
                            _pending.extend(
                                blob for _, blob in recs)
                # Consume signals (wakeups only — content ignored).
                while len(sig_buf) >= _sig.size:
                    sig_buf = sig_buf[_sig.size:]
            else:
                while len(sig_buf) >= _sig.size:
                    wid, _idx = _sig.unpack_from(
                        sig_buf[:_sig.size])
                    sig_buf = sig_buf[_sig.size:]
                    if 0 <= wid:
                        while len(per_worker) <= wid:
                            per_worker.append([0, b""])
                        if wid < len(out_fds):
                            for _bidx, blob in _drain_worker_memfd(
                                    out_fds[wid], per_worker[wid]):
                                if reassembly is None:
                                    _pending.append(blob)
                                else:
                                    reassembly.add(_bidx, blob)
                                    for _, ordered in reassembly.drain():
                                        _pending.append(ordered)
            if _pending:
                return _pending.pop(0)
            # Exhausted for now: StopIteration only when the reactor
            # has no live workers AND the signal pipe hit EOF AND no
            # unframed signal bytes remain (same EOF-anchored rule as
            # _drain_records). Otherwise None (not EOF — keep polling).
            if (not any(s.alive for s in state.workers.values())
                    and sig_eof and not sig_buf):
                if reassembly is not None:
                    for _, ordered in reassembly.final_drain():
                        _pending.append(ordered)
                    if _pending:
                        return _pending.pop(0)
                # Safety sweep before giving up (short final writes).
                if use_orderer:
                    try:
                        _sz = os.fstat(coll_fd).st_size
                    except OSError:
                        _sz = drain_state[0]
                    if _sz > drain_state[0]:
                        try:
                            _ch = os.pread(
                                coll_fd, _sz - drain_state[0],
                                drain_state[0])
                        except OSError:
                            _ch = b""
                        if _ch:
                            drain_state[0] += len(_ch)
                            recs, tail = _split_records(
                                drain_state[1] + _ch)
                            drain_state[1] = tail
                            _pending.extend(
                                blob for _, blob in recs)
                            if _pending:
                                return _pending.pop(0)
                else:
                    for _wid in range(len(per_worker)):
                        if _wid >= len(out_fds):
                            continue
                        for _bidx, blob in _drain_worker_memfd(
                                out_fds[_wid], per_worker[_wid]):
                            if reassembly is None:
                                _pending.append(blob)
                            else:
                                reassembly.add(_bidx, blob)
                                for _, ordered in reassembly.drain():
                                    _pending.append(ordered)
                    if _pending:
                        return _pending.pop(0)
                raise StopIteration
            return None

        _pending: list = []
        try:
            yield from reactor_loop(state, drain_gen=_pump_drain)
        finally:
            pass

        _reactor_failure_check(state, workers, on_error)

        if use_orderer:
            if order_w is not None:
                try:
                    os.close(order_w)
                except OSError:
                    pass
                order_w = None
            if orderer_pid is not None:
                try:
                    _, _ost = os.waitpid(orderer_pid, 0)
                except ChildProcessError:
                    _ost = 0
                if _ost != 0 and not (
                        os.WIFEXITED(_ost) and
                        os.WEXITSTATUS(_ost) == 0):
                    raise RuntimeError(
                        "forkrun: C orderer failed (status %r)"
                        % (_ost,))
        if stats is not None and reassembly is not None:
            stats["reassembly_max"] = reassembly.max_size

        _reactor_poison_summary(lib, state)
    finally:
        if spare_signal_w is not None and spare_signal_w >= 0:
            try:
                os.close(spare_signal_w)
            except OSError:
                pass
        _teardown_reactor(lib, state, signal_r=signal_r,
                          out_fds=out_fds, out_hold=out_hold,
                          memfd=memfd, src_fd=src_fd,
                          must_close=must_close,
                          orderer_pid=orderer_pid, order_r=order_r,
                          order_w=order_w, trap_r=trap_r, trap_w=trap_w,
                          coll_fd=coll_fd, coll_hold=coll_hold)


def _execute_ingest_reactor_locked(payload, source, *, sink, lines,
                                   bytes_, workers, on_error, collect,
                                   order, mode="python", nodes="auto",
                                   splice=False):
    """map/run over a streaming source under reactor supervision.

    Mirrors _execute_ingest_locked (reaper + spawn-aware scanner +
    publish-timed worker forks, bounded ingress) with ReactorState
    supervision instead of plain waitpid: worker deaths respawn
    (bounded), trap-ACKs confirm, the scanner has a death pipe with
    error classification, and order=index+collect uses the C orderer.
    """
    from ._bindings import v1_available as _v1a
    from ._reactor import (ORDER_PIPE_SIZE, ReactorState,
                           check_scanner_death,
                           fork_scanner_with_death_pipe,
                           reactor_poll_once, reactor_run,
                           spawn_orderer)
    import fcntl as _fcntl

    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")
    engine_fds = snapshot_fds() - pre_fds

    src_fd, must_close = _open_source(source)
    memfd = None
    mem_hold: list = []
    out_fds: list = []
    out_hold: list = []
    fallow_r = fallow_w = None
    order_r = order_w = None
    coll_fd = None
    coll_hold: list = []
    orderer_pid = None
    spawn_r = spawn_w = None
    trap_r = trap_w = None
    fallow_pid = scan_pid = None
    scan_death_r = None
    state = None
    helpers = {"fallow_rc": None, "scan_kind": None, "scan_code": None}
    gate_issued = False
    workers_forked = False
    stall_forked = False
    fork_at = 0.0
    total_written = 0
    t_start = _time.monotonic()
    try:
        memfd, mem_hold = _new_ingress_memfd()
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        if collect:
            out_fds, out_hold = _new_output_memfds(workers)
        fallow_r, fallow_w = os.pipe()
        spawn_r, spawn_w = os.pipe()

        use_orderer = (collect and order == "index" and not splice
                       and _v1a(lib).get("orderer"))
        if use_orderer:
            order_r, order_w = os.pipe()
            try:
                _fcntl.fcntl(order_w, _fcntl.F_SETPIPE_SZ,
                             ORDER_PIPE_SIZE)
            except OSError:
                pass
            try:
                coll_fd = os.memfd_create("forkrun_ordered")
            except AttributeError:
                import tempfile as _tf
                _tmp = _tf.TemporaryFile(prefix="forkrun_ordered_")
                coll_hold.append(_tmp)
                coll_fd = _tmp.fileno()
            orderer_pid = spawn_orderer(order_r, coll_fd,
                                        engine_fds=engine_fds,
                                        out_fds=out_fds)

        trap_r, trap_w = os.pipe()

        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass

        # Fallow reaper child (plain fork: no spawn pipe needed).
        fallow_pid = os.fork()
        if fallow_pid == 0:
            try:
                scrub_fds(engine_fds | {fallow_r, memfd})
                rc = lib.fr_py_fallow_loop(fallow_r, memfd)
            except BaseException:
                rc = 1
            os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
        # Spawn-aware scanner with a death pipe (bash SCAN_DEATH).
        scan_pid, scan_death_r = fork_scanner_with_death_pipe(
            lib, memfd, spawn_w, engine_fds)
        # Parent drops write copies it never uses (scanner owns
        # spawn_w; the fallow read end belongs to the reaper). The
        # SPARES for future respawns (fallow_w) stay open in ctx.
        for _fd in (spawn_w, fallow_r):
            try:
                os.close(_fd)
            except OSError:
                pass
        spawn_w = None
        fallow_r = None

        state = ReactorState(workers, num_nodes=1,
                             respawn_cap=REACTOR_RESPAWN_CAP,
                             spawn_ceiling=workers)
        state.configure(payload_spec=payload, sink_spec=sink,
                        memfd=memfd, file_size=-1,
                        out_fds=list(out_fds) if collect else [],
                        signal_w=None, fallow_w=fallow_w,
                        order_w=order_w if use_orderer else -1,
                        trap_ack_w=trap_w, on_error=on_error,
                        engine_fds=engine_fds, splice=splice)
        state.spawn_r = spawn_r
        state.trap_ack_r = trap_r

        def _watch_helpers():
            # Fallow death (WNOHANG) is fatal; scanner state comes
            # from its death pipe with error classification. A clean
            # scanner exit BEFORE the gate is equally fatal (exit 0
            # is only reachable via the EOF gate — an early 0 means
            # the tail it never saw is lost).
            nonlocal scan_death_r
            try:
                wpid, st = os.waitpid(fallow_pid, os.WNOHANG)
            except ChildProcessError:
                wpid, st = None, None
            except OSError:
                wpid, st = None, None
            if wpid == fallow_pid:
                helpers["fallow_rc"] = st
                ok = os.WIFEXITED(st) and os.WEXITSTATUS(st) == 0
                if not ok:
                    lib.fr_py_abort()
                    raise RuntimeError(
                        "forkrun: ingest reaper failed (status %r)"
                        % (st,))
            if scan_death_r is not None and helpers["scan_kind"] is None:
                kind, code = check_scanner_death(scan_pid,
                                                scan_death_r)
                if kind != "running":
                    # Definitive: the pipe is consumed (closed
                    # inside) — record and stop polling it.
                    helpers["scan_kind"] = kind
                    helpers["scan_code"] = code
                    scan_death_r = None
                    if kind == "error" or not gate_issued:
                        lib.fr_py_abort()
                        raise RuntimeError(
                            "forkrun: ingest scanner failed (status %r)"
                            % (code,))

        def _fork_workers_now():
            nonlocal workers_forked, fork_at
            for _ in range(workers):
                if state.spawn_worker(node=0) is None:
                    break
            workers_forked = True
            fork_at = _time.monotonic()

        def _maybe_fork_workers():
            nonlocal stall_forked
            if workers_forked:
                return True
            try:
                ready = lib.fr_py_data_ready()
            except Exception:
                ready = 0
            if ready > 0:
                _fork_workers_now()
                return True
            if not gate_issued and (
                    _time.monotonic() - t_start) >= STALL_FORK_AFTER:
                stall_forked = True
                _fork_workers_now()
                return True
            return False

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
                        n = os.pwrite(memfd, view, total_written)
                    except OSError as exc:
                        raise RuntimeError(
                            "failed writing ingress: %s" % (exc,))
                    view = view[n:]
                    total_written += n
                _watch_helpers()
                _maybe_fork_workers()
                reactor_poll_once(state)
        except KeyboardInterrupt:
            lib.fr_py_abort()
            raise
        if stall_forked:
            while True:
                try:
                    ready = lib.fr_py_data_ready()
                except Exception:
                    ready = 0
                if ready > 0:
                    break
                if (_time.monotonic() - fork_at) >= POST_FORK_GATE_GRACE:
                    break
                _watch_helpers()
                reactor_poll_once(state)
                _time.sleep(0.05)
        if lib.fr_py_ingest_done() != RC_OK:
            raise RuntimeError("ingest signal failed")
        gate_issued = True
        if not workers_forked:
            while True:
                try:
                    ready = lib.fr_py_data_ready()
                except Exception:
                    ready = 0
                if ready > 0:
                    _fork_workers_now()
                    break
                _watch_helpers()
                reactor_poll_once(state)
                if helpers["scan_kind"] == "clean":
                    if total_written == 0:
                        break
                    raise RuntimeError(
                        "forkrun: ingest scanner published no data "
                        "for %d spilled bytes" % total_written)
                if helpers["scan_kind"] == "error":
                    lib.fr_py_abort()
                    raise RuntimeError(
                        "forkrun: ingest scanner failed (status %r)"
                        % (helpers["scan_code"],))
                _time.sleep(0.05)

        if workers_forked:
            try:
                reactor_run(state)
            except KeyboardInterrupt:
                raise
        else:
            # Empty input: no workers ever existed. Drop the spares
            # whose EOF the helpers wait on (reaper + orderer).
            for _fd in (fallow_w, order_w):
                if _fd is not None:
                    try:
                        os.close(_fd)
                    except OSError:
                        pass
            if fallow_w is not None:
                fallow_w = None
                state.ctx["fallow_w"] = -1
            if order_w is not None:
                order_w = None
                state.ctx["order_w"] = -1

        _reactor_failure_check(state, workers, on_error)

        # Reaper EOF: all worker write ends are closed (no live
        # workers remain, so no respawn can reopen them) — drop the
        # parent's spare so the reaper observes EOF and exits.
        if fallow_w is not None:
            try:
                os.close(fallow_w)
            except OSError:
                pass
            fallow_w = None
            state.ctx["fallow_w"] = -1
        if use_orderer:
            if order_w is not None:
                try:
                    os.close(order_w)
                except OSError:
                    pass
                order_w = None
            if orderer_pid is not None:
                try:
                    _, _ost = os.waitpid(orderer_pid, 0)
                except ChildProcessError:
                    _ost = 0
                if _ost != 0 and not (
                        os.WIFEXITED(_ost) and
                        os.WEXITSTATUS(_ost) == 0):
                    raise RuntimeError(
                        "forkrun: C orderer failed (status %r)"
                        % (_ost,))

        if helpers["scan_kind"] == "error":
            raise RuntimeError(
                "forkrun: ingest scanner failed (status %r)"
                % (helpers["scan_code"],))
        if helpers["scan_kind"] is None:
            # Never observed via the death pipe (already reaped by
            # teardown after healthy workers, or still alive):
            # blocking join proves a clean finish.
            try:
                _, scan_st = os.waitpid(scan_pid, 0)
            except ChildProcessError:
                scan_st = None
            if scan_st is not None and not (
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

        _reactor_poison_summary(lib, state)

        if not collect:
            return None
        if use_orderer:
            records = _parse_records(_read_fd_all(coll_fd))
            return [blob for _, blob in records]
        records = []
        for fd in out_fds:
            records.extend(_parse_records(_read_fd_all(fd)))
        if order == "index":
            records.sort(key=lambda kv: kv[0])
        return [blob for _, blob in records]
    except KeyboardInterrupt:
        try:
            lib.fr_py_abort()
        except Exception:
            pass
        raise
    finally:
        _teardown_reactor(lib, state, out_fds=out_fds,
                          out_hold=out_hold, memfd=memfd,
                          mem_hold=mem_hold, src_fd=src_fd,
                          must_close=must_close,
                          extra_pids=[p for p in (fallow_pid, scan_pid)
                                      if p is not None],
                          orderer_pid=orderer_pid, order_r=order_r,
                          order_w=order_w, trap_r=trap_r, trap_w=trap_w,
                          coll_fd=coll_fd, coll_hold=coll_hold)


def _execute_ingest_stream_reactor(payload, source, *, lines, bytes_,
                                     workers, on_error, mode="python",
                                     nodes="auto", order="none",
                                     stats=None, splice=False):
    """stream() over a streaming source under reactor supervision.

    Mirrors _execute_ingest_stream (spill/pump interleaved with a
    live drain) with ReactorState supervision: death pipes, bounded
    respawn, trap-ACK, scanner death pipe, C orderer for
    order=index (non-splice). Fork timing stays publish-gated (first
    DATA publish / stall / post-gate — the pre-flight bail rule);
    the scanner runs WITHOUT a spawn pipe (spawn_w=-1): the
    spawn-request mechanism (fr_py_scan_with_spawn,
    handle_spawn_bytes) is implemented and unit-tested, but
    auto-forking on scanner requests would fork workers during
    pre-flight and trip the CASE-B bail (silent loss), so ingest
    forks stay publish-gated. Abandonment tears down via finally.
    """
    from ._bindings import v1_available as _v1a
    from ._reactor import (ORDER_PIPE_SIZE, ReactorState,
                           check_scanner_death,
                           fork_scanner_with_death_pipe,
                           reactor_loop, spawn_orderer)
    import fcntl as _fcntl
    import select as _select

    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    if order not in ("none", "index"):
        raise ValueError(
            "order must be 'none' or 'index', got %r" % (order,))
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")
    engine_fds = snapshot_fds() - pre_fds

    src_fd, must_close = _open_source(source)
    memfd = None
    mem_hold: list = []
    out_fds: list = []
    out_hold: list = []
    fallow_r = fallow_w = None
    signal_r = None
    signal_w = None
    spare_signal_w = None
    order_r = order_w = None
    coll_fd = None
    coll_hold: list = []
    orderer_pid = None
    trap_r = trap_w = None
    fallow_pid = scan_pid = None
    scan_death_r = None
    state = None
    helpers = {"fallow_rc": None, "scan_kind": None, "scan_code": None}
    gate = {"issued": False}
    spill = {"off": 0}
    fstate = {"workers": False, "stall": False, "fork_at": 0.0,
              "t_start": _time.monotonic(), "pump_done": False}
    try:
        memfd, mem_hold = _new_ingress_memfd()
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        out_fds, out_hold = _new_output_memfds(workers)
        signal_r, signal_w, _ = make_pipe()
        fallow_r, fallow_w = os.pipe()

        use_orderer = (order == "index" and not splice
                       and _v1a(lib).get("orderer"))
        if use_orderer:
            order_r, order_w = os.pipe()
            try:
                _fcntl.fcntl(order_w, _fcntl.F_SETPIPE_SZ,
                             ORDER_PIPE_SIZE)
            except OSError:
                pass
            try:
                coll_fd = os.memfd_create("forkrun_ordered")
            except AttributeError:
                import tempfile as _tf
                _tmp = _tf.TemporaryFile(prefix="forkrun_ordered_")
                coll_hold.append(_tmp)
                coll_fd = _tmp.fileno()
            orderer_pid = spawn_orderer(order_r, coll_fd,
                                        engine_fds=engine_fds,
                                        out_fds=out_fds)

        trap_r, trap_w = os.pipe()

        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass

        fallow_pid = os.fork()
        if fallow_pid == 0:
            try:
                scrub_fds(engine_fds | {fallow_r, memfd})
                rc = lib.fr_py_fallow_loop(fallow_r, memfd)
            except BaseException:
                rc = 1
            os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
        scan_pid, scan_death_r = fork_scanner_with_death_pipe(
            lib, memfd, -1, engine_fds)
        try:
            os.close(fallow_r)
        except OSError:
            pass
        fallow_r = None

        state = ReactorState(workers, num_nodes=1,
                             respawn_cap=REACTOR_RESPAWN_CAP,
                             spawn_ceiling=workers)
        state.configure(payload_spec=payload, sink_spec=None,
                        memfd=memfd, file_size=-1,
                        out_fds=list(out_fds), signal_w=signal_w,
                        fallow_w=fallow_w,
                        order_w=order_w if use_orderer else -1,
                        trap_ack_w=trap_w, on_error=on_error,
                        engine_fds=engine_fds, splice=splice)
        state.trap_ack_r = trap_r
        spare_signal_w = os.dup(signal_w)

        def _drop_parent_signal():
            nonlocal signal_w, spare_signal_w
            # Workers (present + future respawns via the spare) hold
            # write ends; the parent's original copy must go for EOF.
            if signal_w is not None:
                try:
                    os.close(signal_w)
                except OSError:
                    pass
                signal_w = None
            state.ctx["signal_w"] = spare_signal_w

        def _fork_workers_now():
            for _ in range(workers):
                if state.spawn_worker(node=0) is None:
                    break
            _drop_parent_signal()
            fstate["workers"] = True
            fstate["fork_at"] = _time.monotonic()

        def _watch_helpers():
            # Raises on fallow death / scanner error / early clean
            # scanner exit (same rules as the locked ingest path).
            nonlocal scan_death_r
            try:
                wpid, st = os.waitpid(fallow_pid, os.WNOHANG)
            except ChildProcessError:
                wpid, st = None, None
            except OSError:
                wpid, st = None, None
            if wpid == fallow_pid:
                helpers["fallow_rc"] = st
                ok = os.WIFEXITED(st) and os.WEXITSTATUS(st) == 0
                if not ok:
                    lib.fr_py_abort()
                    raise RuntimeError(
                        "forkrun: ingest reaper failed (status %r)"
                        % (st,))
            if scan_death_r is not None \
                    and helpers["scan_kind"] is None:
                kind, code = check_scanner_death(scan_pid,
                                                scan_death_r)
                if kind != "running":
                    helpers["scan_kind"] = kind
                    helpers["scan_code"] = code
                    scan_death_r = None
                    if kind == "error" or not gate["issued"]:
                        lib.fr_py_abort()
                        raise RuntimeError(
                            "forkrun: ingest scanner failed "
                            "(status %r)" % (code,))

        def _maybe_fork_workers():
            if fstate["workers"]:
                return True
            try:
                ready = lib.fr_py_data_ready()
            except Exception:
                ready = 0
            if ready > 0:
                _fork_workers_now()
                return True
            if not gate["issued"] and (
                    _time.monotonic() - fstate["t_start"]
                    ) >= STALL_FORK_AFTER:
                fstate["stall"] = True
                _fork_workers_now()
                return True
            return False

        if not must_close:
            src_fd = os.dup(src_fd)
            must_close = True
        try:
            fl = _fcntl.fcntl(src_fd, _fcntl.F_GETFL)
            _fcntl.fcntl(src_fd, _fcntl.F_SETFL, fl | os.O_NONBLOCK)
        except OSError:
            pass

        # Drain state (same two shapes as _execute_streaming_reactor).
        _sig = struct.Struct("<QQ")
        drain = {"coll_off": 0, "coll_tail": b"", "sig_buf": b"",
                 "sig_eof": False, "pending": [],
                 "reassembly": None}
        if order == "index" and not use_orderer:
            drain["reassembly"] = ReassemblyBuffer()
        per_worker = [[0, b""] for _ in range(workers)]

        def _spill_quantum():
            # Returns True when ingest is fully done (gate issued AND
            # (workers forked OR input was empty)). Raises on helper
            # death / anomaly. Mirrors _execute_ingest_stream._pump.
            _watch_helpers()
            if not fstate["workers"]:
                if gate["issued"]:
                    try:
                        ready = lib.fr_py_data_ready()
                    except Exception:
                        ready = 0
                    if ready > 0:
                        _fork_workers_now()
                    elif helpers["scan_kind"] == "clean":
                        if spill["off"] == 0:
                            fstate["pump_done"] = True
                            return True
                        raise RuntimeError(
                            "forkrun: ingest scanner published no "
                            "data for %d spilled bytes" % spill["off"])
                    else:
                        return False
                else:
                    _maybe_fork_workers()
            if gate["issued"]:
                done = fstate["workers"] or spill["off"] == 0
                fstate["pump_done"] = done
                return done
            while True:
                try:
                    chunk = os.read(src_fd, _CHUNK)
                except BlockingIOError:
                    return False
                except OSError as exc:
                    raise RuntimeError(
                        "failed reading source: %s" % (exc,))
                if not chunk:
                    if fstate["stall"] and (
                            _time.monotonic() - fstate["fork_at"]
                            ) < POST_FORK_GATE_GRACE:
                        try:
                            ready = lib.fr_py_data_ready()
                        except Exception:
                            ready = 0
                        if ready == 0:
                            return False
                    if lib.fr_py_ingest_done() != RC_OK:
                        raise RuntimeError("ingest signal failed")
                    gate["issued"] = True
                    done = fstate["workers"] or spill["off"] == 0
                    fstate["pump_done"] = done
                    return done
                view = memoryview(chunk)
                while view:
                    try:
                        n = os.pwrite(memfd, view, spill["off"])
                    except OSError as exc:
                        raise RuntimeError(
                            "failed writing ingress: %s" % (exc,))
                    view = view[n:]
                    spill["off"] += n
                _maybe_fork_workers()

        def _parse_quantum():
            # Incremental preads → drain["pending"]. Returns True if
            # any complete record was buffered.
            got = False
            if use_orderer:
                try:
                    _sz = os.fstat(coll_fd).st_size
                except OSError:
                    _sz = drain["coll_off"]
                if _sz > drain["coll_off"]:
                    try:
                        _ch = os.pread(coll_fd, _sz - drain["coll_off"],
                                       drain["coll_off"])
                    except OSError:
                        _ch = b""
                    if _ch:
                        drain["coll_off"] += len(_ch)
                        recs, tail = _split_records(
                            drain["coll_tail"] + _ch)
                        drain["coll_tail"] = tail
                        if recs:
                            drain["pending"].extend(
                                blob for _, blob in recs)
                            got = True
                while len(drain["sig_buf"]) >= _sig.size:
                    drain["sig_buf"] = drain["sig_buf"][_sig.size:]
            else:
                while len(drain["sig_buf"]) >= _sig.size:
                    wid, _idx = _sig.unpack_from(
                        drain["sig_buf"][:_sig.size])
                    drain["sig_buf"] = drain["sig_buf"][_sig.size:]
                    if 0 <= wid:
                        while len(per_worker) <= wid:
                            per_worker.append([0, b""])
                        if wid < len(out_fds):
                            for _bidx, blob in _drain_worker_memfd(
                                    out_fds[wid], per_worker[wid]):
                                if drain["reassembly"] is None:
                                    drain["pending"].append(blob)
                                else:
                                    drain["reassembly"].add(_bidx, blob)
                                    for _, ordered in drain[
                                            "reassembly"].drain():
                                        drain["pending"].append(ordered)
                                got = True
            return got

        def _pump_drain():
            nonlocal spare_signal_w
            if not any(s.alive for s in state.workers.values()):
                if spare_signal_w is not None and spare_signal_w >= 0:
                    try:
                        os.close(spare_signal_w)
                    except OSError:
                        pass
                    spare_signal_w = None
                    state.ctx["signal_w"] = -1
            try:
                pump_done = _spill_quantum()
            except StopIteration:
                raise
            if not drain["sig_eof"]:
                try:
                    ready, _, _ = _select.select([signal_r], [], [], 0)
                except (OSError, ValueError):
                    ready = []
                if ready:
                    try:
                        chunk = os.read(signal_r, 65536)
                    except OSError:
                        chunk = b""
                    if chunk == b"":
                        drain["sig_eof"] = True
                    else:
                        drain["sig_buf"] += chunk
            _parse_quantum()
            if drain["pending"]:
                return drain["pending"].pop(0)
            if (fstate["pump_done"]
                    and not any(s.alive
                                for s in state.workers.values())
                    and drain["sig_eof"] and not drain["sig_buf"]):
                if drain["reassembly"] is not None:
                    for _, ordered in drain["reassembly"].final_drain():
                        drain["pending"].append(ordered)
                    if drain["pending"]:
                        return drain["pending"].pop(0)
                if use_orderer:
                    try:
                        _sz = os.fstat(coll_fd).st_size
                    except OSError:
                        _sz = drain["coll_off"]
                    if _sz > drain["coll_off"]:
                        try:
                            _ch = os.pread(
                                coll_fd, _sz - drain["coll_off"],
                                drain["coll_off"])
                        except OSError:
                            _ch = b""
                        if _ch:
                            drain["coll_off"] += len(_ch)
                            recs, tail = _split_records(
                                drain["coll_tail"] + _ch)
                            drain["coll_tail"] = tail
                            drain["pending"].extend(
                                blob for _, blob in recs)
                            if drain["pending"]:
                                return drain["pending"].pop(0)
                else:
                    for _wid in range(len(per_worker)):
                        if _wid >= len(out_fds):
                            continue
                        for _bidx, blob in _drain_worker_memfd(
                                out_fds[_wid], per_worker[_wid]):
                            if drain["reassembly"] is None:
                                drain["pending"].append(blob)
                            else:
                                drain["reassembly"].add(_bidx, blob)
                                for _, ordered in drain[
                                        "reassembly"].drain():
                                    drain["pending"].append(ordered)
                    if drain["pending"]:
                        return drain["pending"].pop(0)
                raise StopIteration
            return None

        try:
            yield from reactor_loop(state, drain_gen=_pump_drain)
        finally:
            pass

        _reactor_failure_check(state, workers, on_error)

        # Reaper EOF (same rule as the locked ingest path): drop the
        # parent's spare fallow write end now that no respawn can
        # reopen one, so the reaper observes EOF and exits.
        if fallow_w is not None:
            try:
                os.close(fallow_w)
            except OSError:
                pass
            fallow_w = None
            state.ctx["fallow_w"] = -1
        if use_orderer:
            if order_w is not None:
                try:
                    os.close(order_w)
                except OSError:
                    pass
                order_w = None
            if orderer_pid is not None:
                try:
                    _, _ost = os.waitpid(orderer_pid, 0)
                except ChildProcessError:
                    _ost = 0
                if _ost != 0 and not (
                        os.WIFEXITED(_ost) and
                        os.WEXITSTATUS(_ost) == 0):
                    raise RuntimeError(
                        "forkrun: C orderer failed (status %r)"
                        % (_ost,))
        if helpers["scan_kind"] == "error":
            raise RuntimeError(
                "forkrun: ingest scanner failed (status %r)"
                % (helpers["scan_code"],))
        if helpers["scan_kind"] is None:
            try:
                _, scan_st = os.waitpid(scan_pid, 0)
            except ChildProcessError:
                scan_st = None
            if scan_st is not None and not (
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
        if stats is not None and drain["reassembly"] is not None:
            stats["reassembly_max"] = drain["reassembly"].max_size

        _reactor_poison_summary(lib, state)
    finally:
        if spare_signal_w is not None and spare_signal_w >= 0:
            try:
                os.close(spare_signal_w)
            except OSError:
                pass
        _teardown_reactor(lib, state, signal_r=signal_r,
                          out_fds=out_fds, out_hold=out_hold,
                          memfd=memfd, mem_hold=mem_hold,
                          src_fd=src_fd, must_close=must_close,
                          extra_pids=[p for p in (fallow_pid, scan_pid)
                                      if p is not None],
                          orderer_pid=orderer_pid, order_r=order_r,
                          order_w=order_w, trap_r=trap_r, trap_w=trap_w,
                          coll_fd=coll_fd, coll_hold=coll_hold)


__all__ = ["run", "map", "stream"]
