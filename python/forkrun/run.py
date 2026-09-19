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
from ._worker import _HDR, worker_main

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


def _parse_records(blob: bytes) -> list:
    """Parse the v0 emitter record stream: [batch_idx u64][len u64][bytes]*.

    Returns [(batch_idx, payload_bytes)]. Truncated tails (worker died
    mid-record) are dropped — waitpid failure already raises before this
    runs, so a short tail means an internal inconsistency, not user data.
    """
    records = []
    off = 0
    n = len(blob)
    while off + _HDR.size <= n:
        idx, ln = _HDR.unpack_from(blob, off)
        off += _HDR.size
        if off + ln > n:
            break
        records.append((idx, blob[off:off + ln]))
        off += ln
    return records


def _resolve_workers(workers):
    if workers is not None:
        return workers
    try:
        n = os.cpu_count() or 4
    except NotImplementedError:
        n = 4
    return max(1, min(n, 64))


def run(payload, source, *, mode="python", sink=None, order="none",
        lines=None, bytes=None, workers=None, nodes="auto",
        on_error="retry"):
    """Run payload over source in parallel. See module docstring for v0 scope."""
    _validate(payload, source, mode=mode, sink=sink, order=order,
              lines=lines, bytes_=bytes, workers=workers, nodes=nodes,
              on_error=on_error)
    if mode != "python":
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
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
              nodes=nodes, on_error=kwargs.get("on_error", "retry"))
    order = kwargs.get("order", "none")
    results = _execute(payload, source, sink=None,
                       lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
                       workers=_resolve_workers(kwargs.get("workers")),
                       on_error=kwargs.get("on_error", "retry"),
                       collect=True, order=order,
                       mode=mode, nodes=nodes)
    return results


def stream(payload, source, **kwargs):
    """v0: generator over the collected map results (true streaming via the
    emitter pipe is Stage 4 refinement). Yields results ordered by
    batch_index when order='index', else in per-worker completion order.

    Validates eagerly (raises on call, before the first next()).
    """
    _validate(payload, source, mode=kwargs.get("mode", "python"),
              sink=None, order=kwargs.get("order", "none"),
              lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
              workers=kwargs.get("workers"),
              nodes=kwargs.get("nodes", "auto"),
              on_error=kwargs.get("on_error", "retry"))
    return _stream_gen(payload, source, **kwargs)


def _stream_gen(payload, source, **kwargs):
    yield from map(payload, source, **kwargs)


def _execute(payload, source, *, sink, lines, bytes_, workers, on_error,
             collect, order, mode="python", nodes="auto"):
    if mode != "python":
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
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
                            out_fds[i] if collect else None, on_error)
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
