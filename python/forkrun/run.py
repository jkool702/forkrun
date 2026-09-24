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
from ._resume import (checkpoint_on_abort, consume_sidecar,
                      require_resume_path, resume_begin)
from ._spawn import make_spawn_payload
from ._worker import _HDR, _c_plugin_spec, _c_spawn_spec, \
    _fork_c_plugin_worker, _fork_c_spawn_worker, worker_main

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


def _require_numa_symbol():
    """Raise a clear error when the substrate predates the NUMA stages
    (pre-W-PY21 .so): nodes=@N has no UMA fallback (per-node rings
    cannot be emulated by the single-ring engine)."""
    from ._bindings import v1_available as _v1a

    if not _v1a()["numa"]:
        raise RuntimeError(
            "nodes=@N/multi-node needs the NUMA substrate "
            "(fr_py_init_numa et al.) — rebuild it ('make -f "
            "Makefile.substrate python-substrate')")


def _resolve_numa(nodes):
    """Resolve nodes= into (numa_map_str, num_nodes, node_cpus).

    Raises ValueError on malformed specs (via _numa.build_numa_map).
    num_nodes == 1 means UMA (existing paths); > 1 means the NUMA
    pipeline executors below.
    """
    from ._numa import build_numa_map

    return build_numa_map(nodes)


def _require_drain_symbol():
    """Raise a clear error when the substrate predates the C drain
    (pre-W-PY21-A .so): c_drain=True has no Python equivalent at
    zero per-result cost — fall back with c_drain=False."""
    from ._bindings import v1_available as _v1a

    if not _v1a().get("drain"):
        raise RuntimeError(
            "c_drain=True needs fr_py_drain_loop — rebuild "
            "the substrate ('make -f Makefile.substrate "
            "python-substrate')")


def _validate_c_drain(c_drain):
    """Normalize the W-PY21-A drain flag (None → False default).

    Measured (medium scale, same box, alternating medians): the C
    drain runs 0.7-1.0x of the legacy Python drain — never faster.
    Structural reason: the parent must parse every record either
    way, the Python signal reads are already batched (4096/64KB
    read), and the drain adds a full extra transit of the output
    bytes (out memfd → results → parent vs pread direct). The
    work order's ≥1.5x premise is therefore falsified, and the
    default stays legacy (opt-in True) so no user regresses. The
    drain remains available and byte-identical as substrate for a
    future design that also moves consumption client-side.

    The FORKRUN_NO_V1 escape hatch forces legacy paths (it masks
    every fast-path symbol, drain included): under it the default
    is likewise False. An explicit True with the hatch set still
    raises via _require_drain_symbol (asking for the drain while
    masking its symbol is a contradiction).
    """
    if c_drain is None:
        return False
    if isinstance(c_drain, bool):
        return c_drain
    raise TypeError(
        "c_drain must be None, True, or False, got %r" % (c_drain,))


def _fork_drain(signal_r, out_fds, workers, mode="memfd"):
    """Fork the C drain child (W-PY21-A data path separation).

    signal_r: read end of the 16B (wid, batch_idx) signal pipe.
      Ownership transfers to the drain: the parent MUST close its
      copy right after this returns (drain EOF = every write end
      closed = all workers exited + no parent spare/write copy).
    out_fds: parent-created per-worker output memfds (drain preads
      them; created pre-fork so both workers and drain inherit).
    workers: worker count (wid validity bound for the drain).
    mode "memfd": returns (pid, results_memfd) — drain appends
      framed bytes; parent reads once at end (map/run).
    mode "pipe": returns (pid, results_r) — 1MB results pipe the
      parent reads incrementally (stream); a full pipe blocks the
      drain → workers block on signal write → claims stop (the
      hydraulic backpressure loop extended through the drain).
      The parent's write copy is closed inside.

    The drain scrubs to {signal_r, results} + out_fds (pure
    pread/write syscalls — no engine contact, no engine fds) and
    never returns (os._exit with the fr_py_drain_loop rc).
    """
    import ctypes as _ctypes

    from ._bindings import get as _get
    from ._fd_scrub import scrub_fds as _scrub

    if not out_fds or workers < 1:
        raise ValueError(
            "c_drain needs per-worker output memfds")
    if mode not in ("memfd", "pipe"):
        raise ValueError("drain mode must be 'memfd' or 'pipe'")

    lib = _get()
    if mode == "memfd":
        try:
            results_fd = os.memfd_create("forkrun_results")
        except AttributeError:
            import tempfile as _tf
            _tmp = _tf.TemporaryFile(prefix="forkrun_results_")
            _fork_drain._tmp_hold.append(_tmp)
            results_fd = _tmp.fileno()
        results_r = None
    else:
        results_r, results_w, _ = make_pipe()
        results_fd = results_w

    arr = (_ctypes.c_int * len(out_fds))(*out_fds)
    pid = os.fork()
    if pid == 0:
        try:
            keep = {signal_r, results_fd} | set(out_fds)
            _scrub(keep)
        except Exception:
            pass
        if mode == "pipe":
            try:
                os.close(results_r)
            except OSError:
                pass
        try:
            rc = lib.fr_py_drain_loop(signal_r, arr, workers,
                                      results_fd,
                                      1 if mode == "pipe" else 0)
        except BaseException:
            rc = 1
        os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)

    # Parent: signal_r belongs to the drain now; pipe mode also
    # drops the results write end (drain owns it).
    try:
        os.close(signal_r)
    except OSError:
        pass
    if mode == "pipe":
        try:
            os.close(results_w)
        except OSError:
            pass
        return pid, results_r
    return pid, results_fd


_fork_drain._tmp_hold = []


def _validate_orchestrator(orchestrator):
    """Validate the W-PY19 orchestrator flag (None/True/False only)."""
    if orchestrator is None or isinstance(orchestrator, bool):
        return orchestrator
    raise TypeError(
        "orchestrator must be None, True, or False, got %r"
        % (orchestrator,))


def _validate_c_worker_loop(c_worker_loop):
    """Normalize the W-PY26 C worker-loop flag (None → False default).

    The C loop (fr_py_worker_plugin_loop) owns claim→plugin→signal→ack
    in C with zero Python per batch — the plugin analogue of the
    W-PY18 splice loop. Opt-in (default False): the Python worker loop
    stays the default so no user changes behavior without asking.
    """
    if c_worker_loop is None:
        return False
    if isinstance(c_worker_loop, bool):
        return c_worker_loop
    raise TypeError(
        "c_worker_loop must be None, True, or False, got %r"
        % (c_worker_loop,))


def _require_plugin_loop_symbol():
    """Raise a clear error when the substrate predates the C plugin loop
    (pre-W-PY26 .so): c_worker_loop=True has no Python equivalent at
    zero per-batch cost — fall back with c_worker_loop=False."""
    from ._bindings import v1_available as _v1a

    if not _v1a().get("plugin_loop"):
        raise RuntimeError(
            "c_worker_loop=True needs fr_py_worker_plugin_loop — rebuild "
            "the substrate ('make -f Makefile.substrate "
            "python-substrate')")


def _resolve_c_plugin_loop(c_worker_loop, raw_mode, num_nodes):
    """Gate the W-PY26 C worker loop to its supported envelope.

    Supported: map(), mode="plugin" (dialect-1/2 frozen ABI — checked
    later via _c_plugin_spec on the coerced closure), UMA
    single-node, materialized input. Anything else raises loudly
    (never silently falls back — a user asking for the C loop must
    know when they are not getting it). Splice/streaming/NUMA/run/
    stream executors are future work.
    """
    if not c_worker_loop:
        return False
    if raw_mode != "plugin":
        raise ValueError(
            "c_worker_loop=True needs mode='plugin' (the C loop speaks "
            "only the frozen plugin ABI), got mode=%r" % (raw_mode,))
    if num_nodes != 1:
        raise RuntimeError(
            "c_worker_loop=True is UMA-only in W-PY26 (multi-node is "
            "future work) — use c_worker_loop=False")
    _require_plugin_loop_symbol()
    return True


def _validate_c_spawn_loop(c_spawn_loop):
    """Normalize the W-PY33 C spawn-loop flag (None → False default).

    The C loop (fr_py_worker_spawn_loop) owns claim→spawn→signal→ack
    in C with zero Python per batch — the spawn analogue of the
    W-PY26 plugin loop. Opt-in (default False): the Python worker
    loop stays the default so no user changes behavior without
    asking.
    """
    if c_spawn_loop is None:
        return False
    if isinstance(c_spawn_loop, bool):
        return c_spawn_loop
    raise TypeError(
        "c_spawn_loop must be None, True, or False, got %r"
        % (c_spawn_loop,))


def _require_spawn_loop_symbol():
    """Raise a clear error when the substrate predates the C spawn loop
    (pre-W-PY33 .so): c_spawn_loop=True has no Python equivalent at
    zero per-batch cost — fall back with c_spawn_loop=False."""
    from ._bindings import v1_available as _v1a

    if not _v1a().get("spawn_loop"):
        raise RuntimeError(
            "c_spawn_loop=True needs fr_py_worker_spawn_loop — rebuild "
            "the substrate ('make -f Makefile.substrate "
            "python-substrate')")


def _resolve_c_spawn_loop(c_spawn_loop, raw_mode, num_nodes):
    """Gate the W-PY33 C spawn loop to its supported envelope.

    Supported: map(), mode="spawn", UMA single-node, materialized
    input. Anything else raises loudly (never silently falls back —
    a user asking for the C loop must know when they are not getting
    it). Splice/streaming/NUMA/run/stream executors are future work.
    """
    if not c_spawn_loop:
        return False
    if raw_mode != "spawn":
        raise ValueError(
            "c_spawn_loop=True needs mode='spawn' (the C loop replays "
            "a spawn argv per batch), got mode=%r" % (raw_mode,))
    if num_nodes != 1:
        raise RuntimeError(
            "c_spawn_loop=True is UMA-only in W-PY33 (multi-node is "
            "future work) — use c_spawn_loop=False")
    _require_spawn_loop_symbol()
    return True


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
        # Nothing moved (unsupported pair or no kernel path): pipes and
        # sockets can only be read sequentially (pread would ESPIPE).
        # W-PY21-B: C sequential copy first (fr_py_spill_sequential —
        # no Python per chunk); on any failure the ORIGINAL Python loop
        # below runs verbatim (odd fds still surface RuntimeError there;
        # a partial C copy is safe — both loops append at the live
        # offsets, so the fallback resumes, never duplicates).
        spill_seq = (getattr(lib, "fr_py_spill_sequential", None)
                     if lib is not None else None)
        if spill_seq is not None:
            try:
                n_seq = spill_seq(src_fd, memfd, 0)
            except Exception:
                n_seq = -1
            if n_seq is not None and int(n_seq) >= 0:
                return memfd, int(n_seq)
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


def _parse_records_c(blob: bytes) -> list | None:
    """W-PY21-B: C descriptor parse + Python slicing from known bounds.

    fr_py_parse_descriptors does the framing loop in C (no per-record
    struct.unpack/bounds-check/offset arithmetic in Python); result
    bytes objects are still sliced here — C cannot make Python
    objects. Truncated tails drop exactly like _split_records.
    Returns None when the fast path is unavailable or fails (the
    caller falls back to _split_records — never raises).
    """
    if not blob:
        return []
    try:
        from ._bindings import RecordDescriptor as _RD
        from ._bindings import get as _get

        fn = getattr(_get(), "fr_py_parse_descriptors", None)
        if fn is None:
            return None
    except Exception:
        return None
    import ctypes as _ct

    n = len(blob)
    bound = n // 16  # records are >= 16 bytes: always terminates
    if bound == 0:
        return []
    # Bound transient memory (24MB/round); grow-and-retry only when
    # the array filled exactly (cnt == cap < bound may be truncation
    # of the descriptor output, not of the input).
    cap = bound if bound < (1 << 20) else (1 << 20)
    try:
        while True:
            arr = (_RD * cap)()
            cnt = fn(blob, n, arr, cap)
            if cnt is None or int(cnt) < 0:
                return None
            cnt = int(cnt)
            if cnt < cap or cap >= bound:
                return [(int(arr[i].batch_idx),
                         bytes(blob[arr[i].offset:
                                    arr[i].offset + arr[i].length]))
                        for i in range(cnt)]
            cap = bound if bound < cap * 2 else cap * 2
    except Exception:
        return None


def _parse_records(blob: bytes) -> list:
    """Parse the v0 emitter record stream: [batch_idx u64][len u64][bytes]*.

    Returns [(batch_idx, payload_bytes)]. Truncated tails (worker died
    mid-record) are dropped — waitpid failure already raises before this
    runs, so a short tail means an internal inconsistency, not user data.

    W-PY21-B: tries the C descriptor fast path first (identical
    results), falling back to the Python loop verbatim.

    The C path is opt-in (FORKRUN_C_PARSE=1): measured 0.65x of the
    Python loop through ctypes — per-element struct attribute access
    costs more than struct.unpack_from, so the framing win never
    reaches the caller. The symbol stays as tested substrate for a
    future C-extension module (which would build the result list in
    C instead of returning descriptors through ctypes).
    """
    if os.environ.get("FORKRUN_C_PARSE") == "1":
        fast = _parse_records_c(blob)
        if fast is not None:
            return fast
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
        on_error="retry", streaming=None, orchestrator=None,
        c_drain=None, resume=None, checkpoint_file=None,
        c_worker_loop=None):
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
    nodes: None/"auto" (default) = detect topology (single-socket →
      UMA, unchanged); 1 = force UMA; N = first N physical nodes;
      "0,1" = explicit physicals; "@N" = N forced logical nodes
      (W-PY21 NUMA pipeline with per-node rings, born-local ingest,
      CPU pinning; testing-friendly on single-socket).
    c_drain: None (default False, opt-in True) = forked C loop
      moves result bytes (W-PY21-A data/control separation);
      False = legacy parent-side drain. Byte-identical either way;
      measured 0.7-1.0x of legacy (see _validate_c_drain).
    resume/checkpoint_file: W-PY22 — NOT supported by run() (no
      C orderer on any run path); passing either raises
      RuntimeError. Use map()/stream() with orchestrator=True,
      order="index".
    """
    _validate(payload, source, mode=mode, sink=sink, order=order,
              lines=lines, bytes_=bytes, workers=workers, nodes=nodes,
              on_error=on_error, streaming=streaming,
              resume=resume, checkpoint_file=checkpoint_file)
    if resume is not None or checkpoint_file is not None:
        raise RuntimeError(
            "run(): resume=/checkpoint_file= require a C-orderer-backed "
            "path (map()/stream() with orchestrator=True, "
            "order='index'); run() has no C orderer")
    orchestrator = _validate_orchestrator(orchestrator)
    c_drain = _validate_c_drain(c_drain)
    if _validate_c_worker_loop(c_worker_loop):
        raise RuntimeError(
            "run(): c_worker_loop=True needs collection (the C loop "
            "always frames output records); use map()/stream()")
    if mode not in ("python", "spawn", "plugin", "splice"):
        raise NotImplementedError(
            "unknown mode %r" % (mode,))
    numa_map_str, num_nodes, node_cpus = _resolve_numa(nodes)
    if num_nodes > 1:
        # NUMA pipeline (ingest owns the source — files and pipes
        # uniformly; no materialized/streaming split here).
        _require_numa_symbol()
        payload, mode = _coerce_payload(payload, mode)
        if mode == "splice":
            raise ValueError(
                "mode='splice' produces output records — use map() or "
                "stream() (payload=None, bytes=N).")
        with _RUN_LOCK:
            _execute_numa_locked(
                payload, source, sink=sink, lines=lines, bytes_=bytes,
                workers=_resolve_workers(workers), on_error=on_error,
                collect=False, order=order, mode=mode,
                numa_map=numa_map_str, num_nodes=num_nodes,
                node_cpus=node_cpus, c_drain=c_drain)
        return None
    nodes = 1
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
                    mode=mode, nodes=nodes, c_drain=c_drain)
            return None
        _execute_ingest(payload, source, sink=sink, lines=lines,
                        bytes_=bytes, workers=_resolve_workers(workers),
                        on_error=on_error, collect=False, order=order,
                        mode=mode, nodes=nodes, c_drain=c_drain)
        return None
    if orchestrator:
        with _RUN_LOCK:
            _execute_reactor_locked(
                payload, source, sink=sink, lines=lines, bytes_=bytes,
                workers=_resolve_workers(workers), on_error=on_error,
                collect=False, order=order, mode=mode, nodes=nodes,
                c_drain=c_drain)
        return None
    _execute(payload, source, sink=sink, lines=lines, bytes_=bytes,
             workers=_resolve_workers(workers), on_error=on_error,
             collect=False, order=order, c_drain=c_drain)
    return None


def map(payload, source, **kwargs):
    """Batch-granular map: payload(Batch) -> result per batch, ordered by
    batch_index. v0 collects parent-side after workers exit (not streaming).

    mode="splice": kernel passthrough (payload must be None) — each
      result blob is one input byte-window (bytes=N, default 512KB).

    orchestrator=True: W-PY19 reactor supervision (death pipes,
      bounded respawn, trap-ACK, C orderer for order="index").
      Default None = current fork-and-wait behavior.

    nodes: None/"auto" (default) = detect; 1 = force UMA; N/"0,1"/
      "@N" = W-PY21 NUMA pipeline (per-node rings, born-local
      ingest, pinning; uniform over files and pipes).

    c_drain: None (default False, opt-in True) = forked C loop
      moves result bytes (W-PY21-A data/control separation);
      False = legacy parent-side drain. Byte-identical either way;
      measured 0.7-1.0x of legacy (see _validate_c_drain).

    resume: None (default) or checkpoint path to resume FROM
      (W-PY22, byte coordinates). checkpoint_file: None (default)
      or path to publish a checkpoint TO on abort. Both require
      orchestrator=True, order="index", UMA single-node, non-splice
      (C-orderer path); anything else raises RuntimeError loudly.
      Engine commit is exactly-once; Python consumption is not
      (persist consumed results yourself for end-to-end exactly-once).
    """
    mode = kwargs.get("mode", "python")
    nodes = kwargs.get("nodes", "auto")
    _validate(payload, source, mode=mode, sink=None,
              order=kwargs.get("order", "none"), lines=kwargs.get("lines"),
              bytes_=kwargs.get("bytes"), workers=kwargs.get("workers"),
              nodes=nodes, on_error=kwargs.get("on_error", "retry"),
              streaming=kwargs.get("streaming"),
              resume=kwargs.get("resume"),
              checkpoint_file=kwargs.get("checkpoint_file"))
    orchestrator = _validate_orchestrator(kwargs.get("orchestrator"))
    c_drain = _validate_c_drain(kwargs.get("c_drain"))
    numa_map_str, num_nodes, node_cpus = _resolve_numa(nodes)
    # W-PY26: gate the C worker loop to its envelope (mode/plugin +
    # UMA + symbol). Spec extraction (dialect check) happens after
    # _coerce_payload per branch below.
    c_worker_loop = _resolve_c_plugin_loop(
        _validate_c_worker_loop(kwargs.get("c_worker_loop")),
        mode, num_nodes)
    # W-PY33: gate the C spawn loop to its envelope (mode/spawn +
    # UMA + symbol). Argv extraction happens after _coerce_payload
    # per branch below (the spawn-ness rides the wrapper's tag).
    c_spawn_loop = _resolve_c_spawn_loop(
        _validate_c_spawn_loop(kwargs.get("c_spawn_loop")),
        mode, num_nodes)
    if kwargs.get("resume") is not None or \
            kwargs.get("checkpoint_file") is not None:
        # W-PY22: capability gate (NUMA/splice/non-reactor never see
        # resume params — they are rejected here, loudly). Shape and
        # file-existence errors from _validate above take precedence.
        require_resume_path("map()", order=kwargs.get("order", "none"),
             orchestrator=orchestrator, mode=mode, collect=True,
             splice=False, num_nodes=num_nodes)
    if num_nodes > 1:
        _require_numa_symbol()
        payload, mode = _coerce_payload(payload, mode)
        order = kwargs.get("order", "none")
        if mode == "splice":
            _require_splice_symbol()
            b = kwargs.get("bytes") or _SPLICE_DEFAULT_BYTES
        else:
            b = kwargs.get("bytes")
        with _RUN_LOCK:
            return _execute_numa_locked(
                payload, source, sink=None,
                lines=kwargs.get("lines"), bytes_=b,
                workers=_resolve_workers(kwargs.get("workers")),
                on_error=kwargs.get("on_error", "retry"),
                collect=True, order=order, mode=mode,
                numa_map=numa_map_str, num_nodes=num_nodes,
                node_cpus=node_cpus,
                splice=(mode == "splice"), c_drain=c_drain)
    nodes = 1
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
                        nodes=nodes, splice=True, c_drain=c_drain)
            return _execute_ingest(
                None, source, sink=None, lines=None, bytes_=b,
                workers=_resolve_workers(kwargs.get("workers")),
                on_error=kwargs.get("on_error", "retry"),
                collect=True, order=order, mode=mode, nodes=nodes,
                splice=True, c_drain=c_drain)
        if orchestrator:
            with _RUN_LOCK:
                return _execute_reactor_locked(
                    None, source, sink=None, lines=None, bytes_=b,
                    workers=_resolve_workers(kwargs.get("workers")),
                    on_error=kwargs.get("on_error", "retry"),
                    collect=True, order=order, mode=mode, nodes=nodes,
                    splice=True, c_drain=c_drain)
        return _execute(
            None, source, sink=None, lines=None, bytes_=b,
            workers=_resolve_workers(kwargs.get("workers")),
            on_error=kwargs.get("on_error", "retry"),
            collect=True, order=order, mode=mode, nodes=nodes,
            splice=True, c_drain=c_drain)
    if _detect_streaming(source, kwargs.get("streaming")):
        if c_worker_loop:
            raise RuntimeError(
                "c_worker_loop=True is materialized-only in W-PY26 "
                "(streaming ingest is future work) — use "
                "c_worker_loop=False")
        if c_spawn_loop:
            raise RuntimeError(
                "c_spawn_loop=True is materialized-only in W-PY33 "
                "(streaming ingest is future work) — use "
                "c_spawn_loop=False")
        if orchestrator:
            with _RUN_LOCK:
                return _execute_ingest_reactor_locked(
                    payload, source, sink=None,
                    lines=kwargs.get("lines"),
                    bytes_=kwargs.get("bytes"),
                    workers=_resolve_workers(kwargs.get("workers")),
                    on_error=kwargs.get("on_error", "retry"),
                    collect=True, order=order, mode=mode, nodes=nodes,
                    c_drain=c_drain,
                    resume=kwargs.get("resume"),
                    checkpoint_file=kwargs.get("checkpoint_file"))
        return _execute_ingest(
            payload, source, sink=None, lines=kwargs.get("lines"),
            bytes_=kwargs.get("bytes"),
            workers=_resolve_workers(kwargs.get("workers")),
            on_error=kwargs.get("on_error", "retry"),
            collect=True, order=order, mode=mode, nodes=nodes,
            c_drain=c_drain)
    plugin_spec = None
    if c_worker_loop:
        # Coerced plugin payloads carry the (path, func) marker plus
        # the dialect probe: only dialect-1/2 (frozen ABI) can run
        # the C loop. v0 72B conventions stay on the Python loop.
        plugin_spec = _c_plugin_spec(payload)
        if plugin_spec is None:
            raise RuntimeError(
                "c_worker_loop=True needs a dialect-1/2 frozen-ABI "
                "plugin (forkrun_use_ctx opting into 1 or 2) — this "
                "payload negotiates no ctx; use c_worker_loop=False")
    spawn_argv = None
    if c_spawn_loop:
        # Coerced spawn payloads carry the argv list on the wrapper
        # (make_spawn_payload tags _forkrun_spawn_argv); the C loop
        # replays exactly this argv per batch (no shell).
        spawn_argv = _c_spawn_spec(payload)
        if spawn_argv is None:
            raise RuntimeError(
                "c_spawn_loop=True needs a spawn argv payload "
                "(mode='spawn') — use c_spawn_loop=False")
    if orchestrator:
        with _RUN_LOCK:
            return _execute_reactor_locked(
                payload, source, sink=None,
                lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
                workers=_resolve_workers(kwargs.get("workers")),
                on_error=kwargs.get("on_error", "retry"),
                collect=True, order=order, mode=mode, nodes=nodes,
                c_drain=c_drain,
                resume=kwargs.get("resume"),
                checkpoint_file=kwargs.get("checkpoint_file"),
                c_worker_loop=c_worker_loop,
                plugin_spec=plugin_spec,
                c_spawn_loop=c_spawn_loop,
                spawn_argv=spawn_argv)
    results = _execute(payload, source, sink=None,
                       lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
                       workers=_resolve_workers(kwargs.get("workers")),
                       on_error=kwargs.get("on_error", "retry"),
                       collect=True, order=order,
                       mode=mode, nodes=nodes, c_drain=c_drain,
                       c_worker_loop=c_worker_loop,
                       plugin_spec=plugin_spec,
                       c_spawn_loop=c_spawn_loop,
                       spawn_argv=spawn_argv)
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

    nodes: None/"auto" (default) = detect; 1 = force UMA; N/"0,1"/
      "@N" = W-PY21 NUMA pipeline (uniform over files and pipes).

    c_drain: None (default False, opt-in True) = forked C loop
      moves result bytes (W-PY21-A data/control separation);
      False = legacy parent-side drain. Byte-identical either way;
      measured 0.7-1.0x of legacy (see _validate_c_drain).

    resume/checkpoint_file: W-PY22, same contract as map() (C-orderer
      paths only: orchestrator=True, order="index", UMA, non-splice).
      For stream() there is no output sidecar: the consumer owns
      everything yielded live, and the checkpoint covers the engine
      frontier beyond it.
    """
    _validate(payload, source, mode=kwargs.get("mode", "python"),
              sink=None, order=kwargs.get("order", "none"),
              lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
              workers=kwargs.get("workers"),
              nodes=kwargs.get("nodes", "auto"),
              on_error=kwargs.get("on_error", "retry"),
              streaming=kwargs.get("streaming"),
              resume=kwargs.get("resume"),
              checkpoint_file=kwargs.get("checkpoint_file"))
    orchestrator = _validate_orchestrator(kwargs.get("orchestrator"))
    c_drain = _validate_c_drain(kwargs.get("c_drain"))
    if _validate_c_worker_loop(kwargs.get("c_worker_loop")):
        raise RuntimeError(
            "stream(): c_worker_loop=True is map()-only in W-PY26 "
            "(streaming executors are future work)")
    if _validate_c_spawn_loop(kwargs.get("c_spawn_loop")):
        raise RuntimeError(
            "stream(): c_spawn_loop=True is map()-only in W-PY33 "
            "(streaming executors are future work)")
    kwargs = dict(kwargs, c_drain=c_drain)
    numa_map_str, num_nodes, node_cpus = _resolve_numa(
        kwargs.get("nodes", "auto"))
    if kwargs.get("resume") is not None or \
            kwargs.get("checkpoint_file") is not None:
        # W-PY22: gate BEFORE dispatch (NUMA/splice/non-reactor never
        # see resume params — they are rejected here, loudly).
        require_resume_path("stream()", order=kwargs.get("order", "none"),
             orchestrator=orchestrator,
             mode=kwargs.get("mode", "python"),
             collect=True, splice=False, num_nodes=num_nodes)
    if num_nodes > 1:
        _require_numa_symbol()
        payload, engine_mode = _coerce_payload(payload, kwargs.get(
            "mode", "python"))
        if engine_mode == "splice":
            _require_splice_symbol()
        return _numa_stream_gen(
            payload, source,
            lines=kwargs.get("lines"),
            bytes_=(kwargs.get("bytes") or _SPLICE_DEFAULT_BYTES
                    if engine_mode == "splice" else kwargs.get("bytes")),
            workers=_resolve_workers(kwargs.get("workers")),
            on_error=kwargs.get("on_error", "retry"),
            mode=engine_mode, order=kwargs.get("order", "none"),
            orchestrator=orchestrator, numa_map=numa_map_str,
            num_nodes=num_nodes, node_cpus=node_cpus,
            splice=(engine_mode == "splice"), c_drain=c_drain)
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
                    order=kwargs.get("order", "none"),
                    c_drain=kwargs.get("c_drain", True))
            return _splice_ingest_stream_gen(
                source, bytes_=b,
                workers=_resolve_workers(kwargs.get("workers")),
                on_error=kwargs.get("on_error", "retry"),
                nodes=kwargs.get("nodes", "auto"),
                order=kwargs.get("order", "none"),
                c_drain=kwargs.get("c_drain", True))
        if orchestrator:
            return _splice_stream_reactor_gen(
                source, bytes_=b,
                workers=_resolve_workers(kwargs.get("workers")),
                on_error=kwargs.get("on_error", "retry"),
                nodes=kwargs.get("nodes", "auto"),
                order=kwargs.get("order", "none"),
                c_drain=kwargs.get("c_drain", True))
        return _splice_stream_gen(
            source, bytes_=b,
            workers=_resolve_workers(kwargs.get("workers")),
            on_error=kwargs.get("on_error", "retry"),
            nodes=kwargs.get("nodes", "auto"),
            order=kwargs.get("order", "none"),
            c_drain=kwargs.get("c_drain", True))
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
        order=kwargs.get("order", "none"),
        c_drain=kwargs.get("c_drain", True))


def _splice_stream_gen(source, *, bytes_, workers, on_error, nodes,
                       order, c_drain=True):
    # W-PY18 stream() over the C passthrough loop (materialized
    # ingest, live results): yields raw byte-windows as they arrive.
    yield from _execute_streaming(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, mode="splice", nodes=nodes, order=order,
        splice=True, c_drain=c_drain)


def _splice_ingest_stream_gen(source, *, bytes_, workers, on_error,
                              nodes, order, c_drain=True):
    # W-PY18 stream() over passthrough + streaming ingest (unbounded
    # in, live out — the bash -s shape): spill and drain interleave.
    yield from _execute_ingest_stream(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, mode="splice", nodes=nodes, order=order,
        splice=True, c_drain=c_drain)


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
        splice=kwargs.get("mode") == "splice",
        c_drain=kwargs.get("c_drain", True),
        resume=kwargs.get("resume"),
        checkpoint_file=kwargs.get("checkpoint_file"))


def _splice_stream_reactor_gen(source, *, bytes_, workers, on_error,
                               nodes, order, c_drain=True):
    # W-PY19 stream() over splice + reactor (materialized ingest,
    # live results, respawn on death). Python reassembly only (the C
    # orderer needs OrderPackets the splice loop never sends).
    yield from _execute_streaming_reactor(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, mode="splice", nodes=nodes, order=order,
        splice=True, c_drain=c_drain)


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
        order=kwargs.get("order", "none"),
        c_drain=kwargs.get("c_drain", True),
        resume=kwargs.get("resume"),
        checkpoint_file=kwargs.get("checkpoint_file"))


def _splice_ingest_stream_reactor_gen(source, *, bytes_, workers,
                                      on_error, nodes, order,
                                      c_drain=True):
    # W-PY19 stream() over splice + streaming ingest + reactor.
    yield from _execute_ingest_stream_reactor(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, mode="splice", nodes=nodes, order=order,
        splice=True, c_drain=c_drain)


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


def _make_results_pump(results_r, order="none", stats=None):
    """Build a C-drain results-pipe pump for streaming (W-PY21-A).

    The drain child moves framed records verbatim into the results
    pipe; this pump is the parent's incremental consumer. Returns
    pump(alive), where alive is True while any producer (worker or
    drain process) may still deliver bytes. Returns the next blob,
    None when nothing is complete YET (not EOF — keep polling), or
    raises StopIteration when producers are gone AND the pipe hit
    EOF AND no buffered records remain (same EOF-anchored rule as
    _drain_records; a truncated tail drops like _parse_records —
    a worker that died mid-record, never user data).

    order="index" reassembles completion-order records into
    batch_idx sequence via ReassemblyBuffer (holes flush sorted at
    EOF — same head-of-line contract as _drain_records). stats
    receives {"reassembly_max": high-water} when ordering.
    """
    import select as _select

    st = {"tail": b"", "eof": False, "pending": [],
          "reassembly": (ReassemblyBuffer() if order == "index"
                         else None)}

    def _ingest(chunk):
        records, tail = _split_records(st["tail"] + chunk)
        st["tail"] = tail
        if st["reassembly"] is None:
            st["pending"].extend(blob for _, blob in records)
        else:
            for bidx, blob in records:
                st["reassembly"].add(bidx, blob)
            for _, ordered in st["reassembly"].drain():
                st["pending"].append(ordered)

    def pump(alive):
        if not st["eof"]:
            try:
                ready, _, _ = _select.select([results_r], [], [], 0)
            except (OSError, ValueError):
                ready = []
            if ready:
                try:
                    chunk = os.read(results_r, 65536)
                except OSError:
                    chunk = b""
                if chunk == b"":
                    st["eof"] = True
                else:
                    _ingest(chunk)
        if st["pending"]:
            return st["pending"].pop(0)
        if not alive and st["eof"]:
            if st["reassembly"] is not None:
                for _, ordered in st["reassembly"].final_drain():
                    st["pending"].append(ordered)
                if stats is not None:
                    stats["reassembly_max"] = (
                        st["reassembly"].max_size)
                if st["pending"]:
                    return st["pending"].pop(0)
            raise StopIteration
        return None

    return pump


def _teardown_stream(lib, pids, signal_r, out_fds, out_hold, memfd,
                     src_fd, must_close, extra_pids=(), fallow_w=None,
                     drain_pid=None, results_fd=None):
    """Reap-all + close-all + destroy. Abandon-safe: unblocks claim-gated
    workers via the fire alarm and EPIPEs signal-blocked ones by closing
    the read end, then reaps (zombies pin pids, so no PID-reuse hazard
    for the SIGKILL straggler pass).

    W-PY16: extra_pids covers the scanner + fallow children (same
    kill-then-reap discipline — the fire alarm unblocks a scanner gated
    on ingest, and closing fallow_w EOFs a reaper gated on acks);
    fallow_w is closed here (idempotent: normal flow already closed it
    before reaping the reaper).

    W-PY21-A: drain_pid/results_fd cover the C drain child (same
    kill-then-reap discipline; closing the results read end EPIPEs a
    drain blocked on a full pipe). Omitted when the Python drain ran.
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
    if results_fd is not None:
        try:
            os.close(results_fd)
        except OSError:
            pass
    for pid in list(pids) + list(extra_pids) + (
            [drain_pid] if drain_pid is not None else []):
        try:
            wpid, _ = os.waitpid(pid, os.WNOHANG)
            if wpid == 0:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
        except ChildProcessError:
            pass
    for pid in list(pids) + list(extra_pids) + (
            [drain_pid] if drain_pid is not None else []):
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
                       order="none", stats=None, splice=False,
                       c_drain=True):
    """v1 streaming pipeline: a GENERATOR. Fork happens on first next(),
    blobs yield in worker-completion order (order="none") or batch_idx
    sequence (order="index", parent-side reassembly) while workers run.
    Failure accounting + poison summary run at exhaustion. Abandoning the
    generator (close/GC/exception) tears down workers via the finally.
    stats (optional dict): white-box drain diagnostics (reassembly_max).
    splice (W-PY18): children run the C passthrough loop (no payload).
    c_drain (W-PY21-A): True (opt-in) moves signal consume + memfd
      pread into a forked C loop feeding a results pipe the parent
      reads incrementally; False keeps the Python _drain_records path.
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
    use_drain = bool(c_drain)
    if use_drain:
        _require_drain_symbol()
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
    drain_pid = None
    results_r = None
    drain_status = None
    exhausted = False
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
        if use_drain:
            # W-PY21-A: the C drain owns signal_r from here on; the
            # parent consumes the results pipe (never signals/memfds).
            # No threads: one single-threaded loop below interleaves
            # results reads with WNOHANG reaps (fork-before-threads
            # stays intact — the reactor thread sketched in early
            # drafts would fork under a live thread on respawn).
            drain_pid, results_r = _fork_drain(
                signal_r, out_fds, workers, mode="pipe")
            signal_r = None
            pump = _make_results_pump(results_r, order=order,
                                      stats=stats)
            drain_alive = True
            try:
                alive = set(pids)
                while True:
                    for pid in list(alive):
                        try:
                            wpid, status = os.waitpid(pid, os.WNOHANG)
                        except ChildProcessError:
                            alive.discard(pid)
                            continue
                        except OSError:
                            continue
                        if wpid == pid:
                            alive.discard(pid)
                            statuses.append((pid, status))
                    if drain_alive:
                        try:
                            wpid, _dst = os.waitpid(drain_pid,
                                                    os.WNOHANG)
                        except ChildProcessError:
                            drain_alive = False
                        except OSError:
                            pass
                        else:
                            if wpid == drain_pid:
                                drain_alive = False
                                drain_status = _dst
                    try:
                        blob = pump(bool(alive) or drain_alive)
                    except StopIteration:
                        break
                    if blob is not None:
                        yield blob
                # Workers are gone and the results pipe hit EOF, so
                # the drain has exited (it terminates on signal EOF)
                # — join it here to capture its rc. Blocking is safe:
                # EOF implies the write end is closed.
                if drain_alive:
                    try:
                        _, _dst = os.waitpid(drain_pid, 0)
                    except ChildProcessError:
                        pass
                    except OSError:
                        pass
                    else:
                        drain_alive = False
                        drain_status = _dst
                exhausted = True
            finally:
                # Normal exhaustion falls through; abandonment
                # (GeneratorExit) or consumer error lands here: reap,
                # close, destroy, re-raise (a fresh raise on the
                # abandon path would mask GeneratorExit). The
                # teardown EPIPEs a drain blocked on a full pipe via
                # the results read end.
                _teardown_stream(lib, pids, signal_r, out_fds,
                                 out_hold, memfd, src_fd, must_close,
                                 drain_pid=drain_pid,
                                 results_fd=results_r)
                memfd = None
                signal_r = None
                out_fds = []
                drain_pid = None
                results_r = None
        else:
            try:
                for blob in _drain_records(lib, signal_r, out_fds, pids,
                                           statuses, order=order,
                                           stats=stats):
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

        if use_drain and exhausted and drain_status is not None:
            # Drain rc is secondary to worker failures (checked
            # above); on a clean worker set a nonzero drain rc is a
            # real infrastructure error. Abandoned runs skip this
            # (teardown EPIPEs the drain → rc 5 by design).
            if drain_status != 0 and not (
                    os.WIFEXITED(drain_status) and
                    os.WEXITSTATUS(drain_status) == 0):
                raise RuntimeError(
                    "forkrun: C drain failed (status %r)"
                    % (drain_status,))

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
                           order="none", stats=None, splice=False,
                           c_drain=True):
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
    c_drain (W-PY21-A): True (opt-in) moves signal consume + memfd
      pread into a forked C loop feeding a results pipe (forked
      lazily at first worker fork — workers fork dynamically here);
      False keeps the Python _drain_records path.
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
    use_drain = bool(c_drain)
    if use_drain:
        _require_drain_symbol()
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
    drain_pid = None
    results_r = None
    drain_status = None
    drain_alive = True
    exhausted = False
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

        drain = {"pid": None, "results_r": None, "pump": None,
                 "status": None, "alive": True}

        def _fork_drain_if_needed():
            # W-PY21-A: lazy drain fork (workers fork dynamically
            # here — the drain needs no earlier existence; signals
            # queue in the pipe until it starts). Runs once, at the
            # first worker fork. signal_r ownership transfers to
            # the drain; empty inputs never fork workers, hence
            # never need a drain.
            nonlocal signal_r, drain_pid, results_r
            if not use_drain or drain["pid"] is not None:
                return
            drain["pid"], drain["results_r"] = _fork_drain(
                signal_r, out_fds, workers, mode="pipe")
            drain["pump"] = _make_results_pump(
                drain["results_r"], order=order, stats=stats)
            signal_r = None
            drain_pid = drain["pid"]
            results_r = drain["results_r"]

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
            _fork_drain_if_needed()

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
        if use_drain:
            # W-PY21-A: spill pump + results-pipe consumer, one
            # single-threaded loop (no threads — see _execute_streaming).
            # The drain forks lazily at first worker fork; empty
            # inputs never need one.
            pump_done = False
            try:
                alive = set()
                while True:
                    if not pump_done:
                        pump_done = bool(_pump())
                    alive.update(pids)
                    for pid in list(alive):
                        try:
                            wpid, status = os.waitpid(pid, os.WNOHANG)
                        except ChildProcessError:
                            alive.discard(pid)
                            continue
                        except OSError:
                            continue
                        if wpid == pid:
                            alive.discard(pid)
                            statuses.append((pid, status))
                    if drain["pid"] is not None:
                        if drain["alive"]:
                            try:
                                wpid, _dst = os.waitpid(
                                    drain["pid"], os.WNOHANG)
                            except ChildProcessError:
                                drain["alive"] = False
                            except OSError:
                                pass
                            else:
                                if wpid == drain["pid"]:
                                    drain["alive"] = False
                                    drain["status"] = _dst
                        try:
                            blob = drain["pump"](
                                bool(alive) or drain["alive"])
                        except StopIteration:
                            break
                        if blob is not None:
                            yield blob
                    elif pump_done:
                        # No drain (no workers ever forked: empty
                        # input) and the spill is done — nothing will
                        # ever arrive.
                        break
                # Join the drain for its rc (EOF seen ⇒ exited).
                if drain["pid"] is not None and drain["alive"]:
                    try:
                        _, _dst = os.waitpid(drain["pid"], 0)
                    except ChildProcessError:
                        pass
                    except OSError:
                        pass
                    else:
                        drain["alive"] = False
                        drain["status"] = _dst
                drain_status = drain["status"]
                drain_alive = drain["alive"]
                exhausted = True
            finally:
                _teardown_stream(lib, pids, signal_r, out_fds,
                                 out_hold, memfd, src_fd, must_close,
                                 extra_pids=[p for p in (fallow_pid,
                                                         scan_pid)
                                             if p is not None],
                                 drain_pid=drain["pid"],
                                 results_fd=drain["results_r"])
                memfd = None
                signal_r = None
                out_fds = []
                drain_pid = None
                results_r = None
        else:
            try:
                for blob in _drain_records(lib, signal_r, out_fds, pids,
                                           statuses, order=order,
                                           stats=stats, pump=_pump):
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

        if use_drain and exhausted and drain_status is not None:
            # Secondary to worker failures (above); abandoned runs
            # skip this (teardown EPIPEs the drain → rc 5 by design).
            if drain_status != 0 and not (
                    os.WIFEXITED(drain_status) and
                    os.WEXITSTATUS(drain_status) == 0):
                raise RuntimeError(
                    "forkrun: C drain failed (status %r)"
                    % (drain_status,))

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
        order=kwargs.get("order", "none"),
        c_drain=kwargs.get("c_drain", True))


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
                    splice=False, c_drain=True):
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
            order=order, splice=splice, c_drain=c_drain)


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
                           splice=False, c_drain=True):
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
    c_drain (W-PY21-A): True (opt-in) moves result byte movement
      into a forked C loop (results memfd read once at end);
      False keeps the parent-side memfd parse.
    """
    use_drain = bool(c_drain) and collect
    if use_drain:
        _require_drain_symbol()
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
    signal_r = None
    signal_w = None
    drain_pid = None
    results_fd = None
    drain_status = None
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
        if use_drain:
            # Workers signal the C drain (1MB pipe, like streaming).
            signal_r, signal_w, _ = make_pipe()

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
            nonlocal fork_at, signal_r, signal_w
            nonlocal drain_pid, results_fd
            for i in range(workers):
                if splice:
                    # W-PY18: C-loop passthrough (fallow acks included;
                    # file growth is irrelevant — the loop splices by
                    # explicit offsets, never mmaps).
                    pids.append(_fork_splice_worker(
                        lib, i, memfd,
                        out_fds[i] if collect else None,
                        signal_w if use_drain else None, fallow_w,
                        engine_fds))
                    continue
                pid = os.fork()
                if pid == 0:
                    try:
                        scrub_fds(engine_fds | {memfd, fallow_w} |
                                  ({out_fds[i]} if collect else set()) |
                                  ({signal_w} if use_drain and
                                   signal_w is not None else set()))
                    except Exception:
                        pass
                    worker_main(i, payload, sink, memfd, -1,
                                out_fds[i] if collect else None,
                                signal_w if use_drain else None,
                                on_error, fallow_w)
                    os._exit(127)  # unreachable; worker_main exits
                else:
                    pids.append(pid)
            _drop_fallow_copies()
            workers_forked = True
            fork_at = _time.monotonic()
            if use_drain:
                # Parent's signal write copy goes now (no respawns in
                # this path — single fork event); the drain takes the
                # read end. Drain EOF = all workers out.
                try:
                    os.close(signal_w)
                except OSError:
                    pass
                signal_w = None
                drain_pid, results_fd = _fork_drain(
                    signal_r, out_fds, workers, mode="memfd")
                signal_r = None

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
                        # With c_drain the unused signal pipe goes too
                        # (no workers ⇒ no drain forked).
                        _drop_fallow_copies()
                        if use_drain:
                            for _fd in (signal_w, signal_r):
                                if _fd is not None:
                                    try:
                                        os.close(_fd)
                                    except OSError:
                                        pass
                            signal_w = signal_r = None
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

        if use_drain and drain_pid is not None:
            # Signal EOF (all workers gone) terminates the drain on
            # its own — reap it. Worker error below wins on the
            # failed path (results moot, child still reaped).
            try:
                _, _dst = os.waitpid(drain_pid, 0)
            except ChildProcessError:
                _dst = 0
            drain_status = _dst
            drain_pid = None
            if not failed and _dst != 0 and not (
                    os.WIFEXITED(_dst) and os.WEXITSTATUS(_dst) == 0):
                raise RuntimeError(
                    "forkrun: C drain failed (status %r)" % (_dst,))

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
        if use_drain:
            # Dynamic-fork paths (ingest/NUMA) fork no drain on
            # empty input (no workers ever existed) — vacuously
            # no records. Materialized paths always fork workers,
            # so their drain always exists here.
            records = (_parse_records(_read_fd_all(results_fd))
                       if results_fd is not None else [])
        else:
            records = []
            for fd in out_fds:
                records.extend(_parse_records(_read_fd_all(fd)))
        if order == "index":
            records.sort(key=lambda kv: kv[0])
        return [blob for _, blob in records]
    finally:
        if drain_pid is not None:
            # Stray drain (exception path): SIGKILL + reap.
            try:
                wpid, _ = os.waitpid(drain_pid, os.WNOHANG)
                if wpid == 0:
                    try:
                        os.kill(drain_pid, 9)
                    except OSError:
                        pass
            except ChildProcessError:
                pass
            except OSError:
                pass
            try:
                os.waitpid(drain_pid, 0)
            except ChildProcessError:
                pass
            except OSError:
                pass
        if results_fd is not None:
            try:
                os.close(results_fd)
            except OSError:
                pass
        for _fd in (signal_r, signal_w):
            if _fd is not None:
                try:
                    os.close(_fd)
                except OSError:
                    pass
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
               collect, order, mode="python", nodes="auto", splice=False,
               c_drain=True, c_worker_loop=False, plugin_spec=None,
               c_spawn_loop=False, spawn_argv=None):
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
                               order=order, splice=splice,
                               c_drain=c_drain,
                               c_worker_loop=c_worker_loop,
                               plugin_spec=plugin_spec,
                               c_spawn_loop=c_spawn_loop,
                               spawn_argv=spawn_argv)


def _execute_locked(payload, source, *, sink, lines, bytes_, workers,
                    on_error, collect, order, splice=False,
                    c_drain=True, c_worker_loop=False, plugin_spec=None,
                    c_spawn_loop=False, spawn_argv=None):
    # W-PY21-A: c_drain moves result byte movement (signal consume +
    # memfd pread) from the parent into a forked C loop. Framing and
    # parsing are untouched: the drain copies framed records
    # verbatim into a results memfd the parent reads once at end.
    use_drain = bool(c_drain) and collect
    if use_drain:
        _require_drain_symbol()
    if c_worker_loop:
        if not collect or plugin_spec is None:
            raise RuntimeError(
                "c_worker_loop=True needs collection with a "
                "dialect-1/2 plugin spec")
        _require_plugin_loop_symbol()
    if c_spawn_loop:
        if not collect or spawn_argv is None:
            raise RuntimeError(
                "c_spawn_loop=True needs collection with a "
                "spawn argv payload")
        _require_spawn_loop_symbol()
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")
    # Engine fds for child keep sets (W-PY16 addendum: scrub host
    # event-loop fds in every forked child, keep engine + job fds).
    engine_fds = snapshot_fds() - pre_fds

    src_fd, must_close = _open_source(source)
    memfd = None
    signal_r = None
    signal_w = None
    drain_pid = None
    results_fd = None
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

        if use_drain:
            # Workers signal the drain (not the parent): 1MB pipe.
            signal_r, signal_w, _ = make_pipe()

        pids = []
        for i in range(workers):
            if splice:
                # W-PY18: C-loop passthrough (no Python payload).
                # out_fd always present here (splice requires
                # collect; run() rejects the mode).
                pids.append(_fork_splice_worker(
                    lib, i, memfd, out_fds[i],
                    signal_w if use_drain else None, None,
                    engine_fds))
                continue
            if c_worker_loop:
                # W-PY26: C-loop plugin worker (zero Python per
                # batch). plugin_spec was dialect-gated in map();
                # collect is always true here (map-only flag).
                pids.append(_fork_c_plugin_worker(
                    lib, i, plugin_spec[0], plugin_spec[1],
                    memfd, out_fds[i],
                    signal_w if use_drain else None, None,
                    engine_fds, on_error))
                continue
            if c_spawn_loop:
                # W-PY33: C-loop spawn worker (zero Python per
                # batch). spawn_argv was tag-gated in map(); collect
                # is always true here (map-only flag).
                pids.append(_fork_c_spawn_worker(
                    lib, i, spawn_argv,
                    memfd, out_fds[i],
                    signal_w if use_drain else None, None,
                    engine_fds, on_error))
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
                              ({out_fds[i]} if collect else set()) |
                              ({signal_w} if use_drain and
                               signal_w is not None else set()))
                except Exception:
                    pass
                worker_main(i, payload, sink, memfd, size,
                            out_fds[i] if collect else None,
                            signal_w if use_drain else None, on_error)
                os._exit(127)  # unreachable; worker_main exits
            else:
                pids.append(pid)

        if use_drain:
            # Parent never writes signals and (no respawns here)
            # keeps no spare: close the write end now, fork the
            # drain, drop the read end. Drain EOF = all workers out.
            try:
                os.close(signal_w)
            except OSError:
                pass
            signal_w = None
            drain_pid, results_fd = _fork_drain(
                signal_r, out_fds, workers, mode="memfd")
            signal_r = None

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

        if use_drain and drain_pid is not None:
            # Workers are gone so the signal pipe hit EOF; the drain
            # exits on its own — reap it and check its rc. (On the
            # failed path below this still runs first: results are
            # moot but the child must be reaped. A drain failure
            # there is secondary — the worker error below wins.)
            try:
                _, _dst = os.waitpid(drain_pid, 0)
            except ChildProcessError:
                _dst = 0
            drain_pid = None
            if not failed and _dst != 0 and not (
                    os.WIFEXITED(_dst) and os.WEXITSTATUS(_dst) == 0):
                raise RuntimeError(
                    "forkrun: C drain failed (status %r)" % (_dst,))

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
        if use_drain:
            # Dynamic-fork paths (ingest/NUMA) fork no drain on
            # empty input (no workers ever existed) — vacuously
            # no records. Materialized paths always fork workers,
            # so their drain always exists here.
            records = (_parse_records(_read_fd_all(results_fd))
                       if results_fd is not None else [])
        else:
            records = []
            for fd in out_fds:
                records.extend(_parse_records(_read_fd_all(fd)))
        if order == "index":
            records.sort(key=lambda kv: kv[0])
        return [blob for _, blob in records]
    finally:
        if drain_pid is not None:
            # Stray drain (exception path): SIGKILL + reap so no
            # zombie pins the pid and no child outlives the run.
            try:
                wpid, _ = os.waitpid(drain_pid, os.WNOHANG)
                if wpid == 0:
                    try:
                        os.kill(drain_pid, 9)
                    except OSError:
                        pass
            except ChildProcessError:
                pass
            except OSError:
                pass
            try:
                os.waitpid(drain_pid, 0)
            except ChildProcessError:
                pass
            except OSError:
                pass
        if results_fd is not None:
            try:
                os.close(results_fd)
            except OSError:
                pass
        if signal_r is not None:
            try:
                os.close(signal_r)
            except OSError:
                pass
        if signal_w is not None:
            try:
                os.close(signal_w)
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
                      coll_hold=None, drain_pid=None, results_fd=None,
                      spare_signal_w=None):
    """Kill stray reactor children + close-all + destroy (abandon-safe).

    Mirrors _teardown_stream: fire alarm first (unblocks claim-gated
    workers), SIGKILL stragglers, reap everything (zombies pin PIDs,
    so no PID-reuse hazard), then close fds and destroy. The reactor
    already reaped supervised workers; this covers the orderer,
    scanner/fallow helpers, and any respawn racing teardown.

    W-PY21-A: drain_pid/results_fd/spare_signal_w cover the C drain
    child (kill+reap; closing the results read end EPIPEs a drain
    blocked on a full pipe; closing the spare lets a live drain
    observe signal EOF).
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
                                   if orderer_pid is not None else []) + (
                                       [drain_pid]
                                       if drain_pid is not None else []):
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
                                   if orderer_pid is not None else []) + (
                                       [drain_pid]
                                       if drain_pid is not None else []):
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
    for fd in (signal_r, spare_signal_w, order_r, order_w, trap_r,
               trap_w, coll_fd, results_fd, memfd):
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
                            mode="python", nodes="auto", splice=False,
                            c_drain=True, resume=None,
                            checkpoint_file=None, c_worker_loop=False,
                            plugin_spec=None, c_spawn_loop=False,
                            spawn_argv=None):
    """Materialized map/run under reactor supervision (blocking).

    init → spill → sync scan → (output memfds) → (order pipe +
    orderer for collect+order=index, non-splice) → trap-ACK pipe →
    fork N workers with death pipes → reactor_loop → failure
    accounting → parse (collection file when the C orderer ran,
    results memfd when the C drain ran, else per-worker memfds) →
    teardown. Raises RuntimeError on trap-ACK timeout (catastrophic)
    or unrecovered deaths (cap reached).
    c_drain (W-PY21-A): with collect and without the C orderer,
      workers signal a forked C drain loop instead of the parent
      (which never preads output memfds on this path).
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
    if c_worker_loop:
        # W-PY26: reactor + C loop needs collection, a dialect-gated
        # spec, and no sink (the C loop has no sink hook). Splice
        # never reaches here with the flag (map() gates raw modes).
        if not collect or plugin_spec is None:
            raise RuntimeError(
                "c_worker_loop=True needs collection with a "
                "dialect-1/2 plugin spec")
        if sink is not None:
            raise RuntimeError(
                "c_worker_loop=True takes no sink (no per-batch "
                "Python hook in the C loop)")
        _require_plugin_loop_symbol()
    if c_spawn_loop:
        # W-PY33: reactor + C spawn loop needs collection, a spawn
        # argv payload, and no sink (the C loop has no sink hook).
        if not collect or spawn_argv is None:
            raise RuntimeError(
                "c_spawn_loop=True needs collection with a "
                "spawn argv payload")
        if sink is not None:
            raise RuntimeError(
                "c_spawn_loop=True takes no sink (no per-batch "
                "Python hook in the C loop)")
        _require_spawn_loop_symbol()
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init(lines or 0, bytes_ or 0) != RC_OK:
        raise RuntimeError("substrate init failed")
    engine_fds = snapshot_fds() - pre_fds
    # W-PY22 resume: parse + gate + engine state AFTER init (which
    # zeroes the ledger) and BEFORE any fork. Raises before any
    # child exists. engine_live gates the abort choreography below.
    resume_state = resume_begin(lib, resume, order=order,
                                 orchestrator=True, mode=mode,
                                 collect=collect, splice=splice)
    engine_live = True

    src_fd, must_close = _open_source(source)
    memfd = None
    out_fds: list = []
    out_hold: list = []
    order_r = order_w = None
    coll_fd = None
    coll_hold: list = []
    orderer_pid = None
    trap_r = trap_w = None
    signal_r = None
    signal_w = None
    drain_pid = None
    results_fd = None
    drain_status = None
    state = None
    # W-PY22: pre-try defaults so the abort handler below never
    # NameErrors on early failures (spill/scan, before assignment).
    use_orderer = False
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
        # C drain for collect without the orderer (the orderer path
        # is already C-speed end to end — no drain needed there).
        use_drain = bool(c_drain) and collect and not use_orderer
        if use_drain:
            _require_drain_symbol()
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

        if use_drain:
            # Workers signal the drain; the parent keeps the spare
            # write end for respawns (closed when no worker is live,
            # so the drain observes EOF).
            signal_r, signal_w, _ = make_pipe()

        trap_r, trap_w = os.pipe()

        state = ReactorState(workers, num_nodes=1,
                             respawn_cap=REACTOR_RESPAWN_CAP,
                             spawn_ceiling=workers)
        state.configure(payload_spec=payload, sink_spec=sink,
                        memfd=memfd, file_size=size,
                        out_fds=list(out_fds), signal_w=signal_w,
                        fallow_w=-1,
                        order_w=order_w if use_orderer else -1,
                        trap_ack_w=trap_w, on_error=on_error,
                        engine_fds=engine_fds, splice=splice,
                        plugin_loop=(tuple(plugin_spec)
                                     if c_worker_loop else None),
                        spawn_loop=(tuple(spawn_argv)
                                    if c_spawn_loop else None))
        state.trap_ack_r = trap_r
        for _ in range(workers):
            if state.spawn_worker(node=0) is None:
                break

        if use_drain:
            # signal_r belongs to the drain from here on (the parent
            # never selects on it — control events only). The spare
            # write end stays open for future respawns.
            drain_pid, results_fd = _fork_drain(
                signal_r, out_fds, workers, mode="memfd")
            signal_r = None

        try:
            reactor_run(state)
        except KeyboardInterrupt:
            raise

        _reactor_failure_check(state, workers, on_error)

        if use_drain:
            # Every worker write end is closed (all reaped) — drop
            # the spare so the drain observes EOF, then join it.
            # Worker error above already raised (results moot, but
            # the drain must still be reaped — teardown covers the
            # raise path via drain_pid).
            if signal_w is not None:
                try:
                    os.close(signal_w)
                except OSError:
                    pass
                signal_w = None
                state.ctx["signal_w"] = -1
            if drain_pid is not None:
                try:
                    _, _dst = os.waitpid(drain_pid, 0)
                except ChildProcessError:
                    _dst = 0
                drain_status = _dst
                drain_pid = None
                if _dst != 0 and not (
                        os.WIFEXITED(_dst) and
                        os.WEXITSTATUS(_dst) == 0):
                    raise RuntimeError(
                        "forkrun: C drain failed (status %r)"
                        % (_dst,))

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
            # Already batch_idx-ordered by the C orderer; prepend any
            # sidecar output from previously aborted run(s), then sort
            # (committed ranges are jagged — the union of two ordered
            # lists is not ordered). Consumes (deletes) the sidecar.
            if resume is not None:
                records = consume_sidecar(resume, records)
            # Already batch_idx-ordered by the C orderer; no sort.
            return [blob for _, blob in records]
        if use_drain:
            # Dynamic-fork paths (ingest/NUMA) fork no drain on
            # empty input (no workers ever existed) — vacuously
            # no records. Materialized paths always fork workers,
            # so their drain always exists here.
            records = (_parse_records(_read_fd_all(results_fd))
                       if results_fd is not None else [])
        else:
            records = []
            for fd in out_fds:
                records.extend(_parse_records(_read_fd_all(fd)))
        if order == "index":
            records.sort(key=lambda kv: kv[0])
        return [blob for _, blob in records]
    except BaseException:
        # W-PY22 abort choreography (quiesce -> reap -> snapshot ->
        # publish) BEFORE the finally-teardown destroys the engine.
        # Re-raises with the original type (KeyboardInterrupt stays
        # KeyboardInterrupt). Skips silently unless armed with
        # resume=/checkpoint_file= on a live C-orderer path.
        try:
            checkpoint_on_abort(lib, state=state, orderer_pid=orderer_pid,
                        order_w=order_w, coll_fd=coll_fd,
                        use_orderer=use_orderer, collect=collect,
                        resume_src=resume,
                        checkpoint_file=checkpoint_file,
                        engine_live=engine_live)
        except Exception:
            pass
        raise
    finally:
        _teardown_reactor(lib, state, out_fds=out_fds,
                          out_hold=out_hold, memfd=memfd,
                          src_fd=src_fd, must_close=must_close,
                          orderer_pid=orderer_pid, order_r=order_r,
                          order_w=order_w, trap_r=trap_r, trap_w=trap_w,
                          coll_fd=coll_fd, coll_hold=coll_hold,
                          drain_pid=drain_pid, results_fd=results_fd,
                          spare_signal_w=signal_w)


def _execute_streaming_reactor(payload, source, *, lines, bytes_,
                               workers, on_error, mode="python",
                               nodes="auto", order="none", stats=None,
                               splice=False, c_drain=True, resume=None,
                               checkpoint_file=None):
    """Materialized stream() under reactor supervision (generator).

    Fork happens on first next(); blobs yield live while the reactor
    supervises deaths/respawns. order=index uses the C orderer
    (non-splice): the parent incrementally parses the orderer's
    collection file (already ordered — no Python reassembly
    buffer). c_drain (W-PY21-A, opt-in True, non-orderer paths):
    a forked C loop moves signal consume + memfd pread into a
    results pipe the parent reads incrementally (never signals/
    memfds itself); False keeps the per-worker Python drain.
    Abandonment tears down via the finally (reactor teardown kills
    strays).
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
    # W-PY22 resume: parse + gate + engine state AFTER init (which
    # zeroes the ledger) and BEFORE any fork. engine_live gates the
    # abort choreography below.
    resume_state = resume_begin(lib, resume, order=order,
                                 orchestrator=True, mode=mode,
                                 collect=True, splice=splice)
    engine_live = True
    # W-PY22: pre-try default so the abort handler never NameErrors
    # on early failures (spill/scan, before assignment below).
    use_orderer = False

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
    drain_pid = None
    results_r = None
    drain_status = None
    drain_alive = True
    exhausted = False
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
        # C drain for non-orderer paths (the orderer path is already
        # C-speed end to end — the parent only preads one file there).
        use_drain = bool(c_drain) and not use_orderer
        if use_drain:
            _require_drain_symbol()
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

        # W-PY21-A: with c_drain the C loop owns signal_r from here
        # on (the parent never selects on it — control events only).
        # The spare write end stays open for future respawns.
        drain_st = {"alive": True, "status": None}
        results_pump = None
        if use_drain:
            drain_pid, results_r = _fork_drain(
                signal_r, out_fds, workers, mode="pipe")
            signal_r = None
            results_pump = _make_results_pump(
                results_r, order=order, stats=stats)

        def _close_spare():
            # Drop the parent's spare signal write end (kept for
            # future respawns) so signal EOF can arrive. Idempotent.
            nonlocal spare_signal_w
            if spare_signal_w is not None and spare_signal_w >= 0:
                try:
                    os.close(spare_signal_w)
                except OSError:
                    pass
                spare_signal_w = None
                state.ctx["signal_w"] = -1

        def _pump_drain_c():
            # W-PY21-A results-pipe consumer: spare management +
            # drain reap + incremental parse. Same StopIteration
            # contract as _pump_drain below.
            if not any(s.alive for s in state.workers.values()):
                _close_spare()
            if drain_st["alive"]:
                try:
                    wpid, _dst = os.waitpid(drain_pid, os.WNOHANG)
                except ChildProcessError:
                    drain_st["alive"] = False
                except OSError:
                    pass
                else:
                    if wpid == drain_pid:
                        drain_st["alive"] = False
                        drain_st["status"] = _dst
            return results_pump(
                any(s.alive for s in state.workers.values())
                or drain_st["alive"])

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
        _stream_ok = False
        try:
            try:
                yield from reactor_loop(
                    state,
                    drain_gen=_pump_drain_c if use_drain else _pump_drain)
            finally:
                pass
        except BaseException:
            # W-PY22 abort choreography on abnormal generator exit
            # (consumer abandon/GeneratorExit, worker-crash
            # propagation, KeyboardInterrupt): quiesce -> reap ->
            # snapshot -> publish, then re-raise. No yields here
            # (GeneratorExit forbids them). Stream has no output
            # sidecar — the consumer owns everything yielded live.
            if not _stream_ok:
                try:
                    checkpoint_on_abort(lib, state=state,
                             orderer_pid=orderer_pid, order_w=order_w,
                             coll_fd=None, use_orderer=use_orderer,
                             collect=False, resume_src=resume,
                             checkpoint_file=checkpoint_file,
                             engine_live=engine_live)
                except Exception:
                    pass
            raise

        _reactor_failure_check(state, workers, on_error)

        if use_drain:
            # Workers are gone and the results pipe hit EOF, so the
            # drain has exited — join it for its rc (worker error
            # above already raised; teardown covers that path).
            if drain_st["alive"]:
                try:
                    _, _dst = os.waitpid(drain_pid, 0)
                except ChildProcessError:
                    pass
                except OSError:
                    pass
                else:
                    drain_st["alive"] = False
                    drain_st["status"] = _dst
            drain_status = drain_st["status"]
            if drain_status is not None and drain_status != 0 and not (
                    os.WIFEXITED(drain_status) and
                    os.WEXITSTATUS(drain_status) == 0):
                raise RuntimeError(
                    "forkrun: C drain failed (status %r)"
                    % (drain_status,))

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
        if stats is not None and reassembly is not None \
                and not use_drain:
            stats["reassembly_max"] = reassembly.max_size

        _reactor_poison_summary(lib, state)
        # W-PY22: normal exhaustion — generator completed; the
        # abort handler above must not fire on the way out.
        _stream_ok = True
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
                          coll_fd=coll_fd, coll_hold=coll_hold,
                          drain_pid=drain_pid, results_fd=results_r,
                          spare_signal_w=spare_signal_w)


def _execute_ingest_reactor_locked(payload, source, *, sink, lines,
                                   bytes_, workers, on_error, collect,
                                   order, mode="python", nodes="auto",
                                   splice=False, c_drain=True, resume=None,
                                   checkpoint_file=None):
    """map/run over a streaming source under reactor supervision.

    Mirrors _execute_ingest_locked (reaper + spawn-aware scanner +
    publish-timed worker forks, bounded ingress) with ReactorState
    supervision instead of plain waitpid: worker deaths respawn
    (bounded), trap-ACKs confirm, the scanner has a death pipe with
    error classification, and order=index+collect uses the C orderer.
    c_drain (W-PY21-A, opt-in True, non-orderer collect): workers
    signal a forked C drain loop (results memfd read once at end)
    instead of the parent parsing per-worker memfds.
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
    # W-PY22 resume: parse + gate + engine state AFTER init (which
    # zeroes the ledger) and BEFORE any fork. engine_live gates the
    # abort choreography below.
    resume_state = resume_begin(lib, resume, order=order,
                                 orchestrator=True, mode=mode,
                                 collect=collect, splice=splice)
    engine_live = True
    # W-PY22: pre-try default so the abort handler never NameErrors
    # on early failures (before assignment below).
    use_orderer = False

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
    signal_r = None
    signal_w = None
    drain_pid = None
    results_fd = None
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
        # C drain for collect without the orderer (orderer path is
        # already C-speed end to end).
        use_drain = bool(c_drain) and collect and not use_orderer
        if use_drain:
            _require_drain_symbol()
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

        if use_drain:
            # Workers signal the drain; the parent keeps the spare
            # write end for respawns (closed when no worker is live).
            signal_r, signal_w, _ = make_pipe()

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
                        signal_w=signal_w if use_drain else None,
                        fallow_w=fallow_w,
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
                        # Empty input: drop the fallow copies (reaper
                        # EOF) and skip workers — nothing to consume.
                        # With c_drain the unused signal pipe goes
                        # too (no workers ⇒ no drain forked).
                        _drop_fallow_copies()
                        if use_drain:
                            for _fd in (signal_w, signal_r):
                                if _fd is not None:
                                    try:
                                        os.close(_fd)
                                    except OSError:
                                        pass
                            signal_w = signal_r = None
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

        if use_drain and workers_forked and drain_pid is None:
            # Workers exist (spill/gate phases done); the drain takes
            # signal_r from here on. Signals queued meanwhile are
            # preserved in the pipe.
            drain_pid, results_fd = _fork_drain(
                signal_r, out_fds, workers, mode="memfd")
            signal_r = None

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
        if use_drain and drain_pid is not None:
            # Same for the drain's signal EOF: drop the signal spare,
            # then join the drain for its rc (worker error above
            # already raised — teardown covers that path).
            if signal_w is not None:
                try:
                    os.close(signal_w)
                except OSError:
                    pass
                signal_w = None
                state.ctx["signal_w"] = -1
            try:
                _, _dst = os.waitpid(drain_pid, 0)
            except ChildProcessError:
                _dst = 0
            drain_pid = None
            if _dst != 0 and not (
                    os.WIFEXITED(_dst) and os.WEXITSTATUS(_dst) == 0):
                raise RuntimeError(
                    "forkrun: C drain failed (status %r)" % (_dst,))
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
            # Already batch_idx-ordered by the C orderer; prepend any
            # sidecar output from previously aborted run(s), then sort
            # (committed ranges are jagged). Consumes the sidecar.
            if resume is not None:
                records = consume_sidecar(resume, records)
            return [blob for _, blob in records]
        if use_drain:
            # Dynamic-fork paths (ingest/NUMA) fork no drain on
            # empty input (no workers ever existed) — vacuously
            # no records. Materialized paths always fork workers,
            # so their drain always exists here.
            records = (_parse_records(_read_fd_all(results_fd))
                       if results_fd is not None else [])
        else:
            records = []
            for fd in out_fds:
                records.extend(_parse_records(_read_fd_all(fd)))
        if order == "index":
            records.sort(key=lambda kv: kv[0])
        return [blob for _, blob in records]
    except BaseException:
        # W-PY22 abort choreography (quiesce -> reap -> snapshot ->
        # publish) BEFORE the finally-teardown destroys the engine
        # (including the fallow/scanner helpers). Re-raises with the
        # original type. Skips silently unless armed with
        # resume=/checkpoint_file= on a live C-orderer path.
        try:
            checkpoint_on_abort(lib, state=state, orderer_pid=orderer_pid,
                        order_w=order_w, coll_fd=coll_fd,
                        use_orderer=use_orderer, collect=collect,
                        resume_src=resume,
                        checkpoint_file=checkpoint_file,
                        engine_live=engine_live)
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
                          coll_fd=coll_fd, coll_hold=coll_hold,
                          drain_pid=drain_pid, results_fd=results_fd,
                          spare_signal_w=signal_w)


def _execute_ingest_stream_reactor(payload, source, *, lines, bytes_,
                                     workers, on_error, mode="python",
                                     nodes="auto", order="none",
                                     stats=None, splice=False,
                                     c_drain=True, resume=None,
                                     checkpoint_file=None):
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
    c_drain (W-PY21-A, opt-in True, non-orderer paths): a forked C
    loop moves signal consume + memfd pread into a results pipe
    the parent reads incrementally (never signals/memfds itself).
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
    # W-PY22 resume: parse + gate + engine state AFTER init (which
    # zeroes the ledger) and BEFORE any fork. engine_live gates the
    # abort choreography below.
    resume_state = resume_begin(lib, resume, order=order,
                                 orchestrator=True, mode=mode,
                                 collect=True, splice=splice)
    engine_live = True
    # W-PY22: pre-try default so the abort handler never NameErrors
    # on early failures (before assignment below).
    use_orderer = False

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
    cdrain_pid = None
    cresults_r = None
    cdrain_status = None
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
        # C drain for non-orderer paths (orderer path already C-speed).
        use_drain = bool(c_drain) and not use_orderer
        if use_drain:
            _require_drain_symbol()
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

        # W-PY21-A drain delegation state (pipe mode; forked lazily
        # at first worker fork like the simple ingest path — the
        # legacy `drain` dict below stays for c_drain=False).
        cdrain = {"pid": None, "results_r": None, "pump": None,
                  "status": None, "alive": True}

        def _fork_cdrain_if_needed():
            nonlocal signal_r, cdrain_pid, cresults_r
            if not use_drain or cdrain["pid"] is not None:
                return
            cdrain["pid"], cdrain["results_r"] = _fork_drain(
                signal_r, out_fds, workers, mode="pipe")
            cdrain["pump"] = _make_results_pump(
                cdrain["results_r"], order=order, stats=stats)
            signal_r = None
            cdrain_pid = cdrain["pid"]
            cresults_r = cdrain["results_r"]

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
            _fork_cdrain_if_needed()

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

        def _pump_drain_c():
            # W-PY21-A quantum: spill interleave (drives forks) +
            # results-pipe consumer. Same StopIteration contract as
            # _pump_drain below (pump done + no producers + results
            # EOF + empty). The legacy signal/memfd machinery is
            # entirely bypassed — the drain owns it.
            pump_done = _spill_quantum()
            if cdrain["pid"] is None:
                # No workers ever forked (empty input): with the
                # spill done nothing will ever arrive.
                if pump_done:
                    raise StopIteration
                return None
            if cdrain["alive"]:
                try:
                    wpid, _dst = os.waitpid(cdrain["pid"], os.WNOHANG)
                except ChildProcessError:
                    cdrain["alive"] = False
                except OSError:
                    pass
                else:
                    if wpid == cdrain["pid"]:
                        cdrain["alive"] = False
                        cdrain["status"] = _dst
            try:
                blob = cdrain["pump"](
                    bool(any(s.alive for s in state.workers.values()))
                    or cdrain["alive"])
            except StopIteration:
                if pump_done:
                    raise
                return None
            return blob

        def _pump_drain():
            nonlocal spare_signal_w
            # Spare-drop rule (W-PY19 erratum): only once workers
            # have EVER forked (fstate). Rounds before the first
            # fork have no live workers either — closing the spare
            # then would poison ctx (future forks inherit
            # signal_w=-1 and never signal, starving the drain AND
            # the legacy signal parser; legacy limps home only via
            # its end-of-stream safety sweep).
            if fstate["workers"] and not any(
                    s.alive for s in state.workers.values()):
                if spare_signal_w is not None and spare_signal_w >= 0:
                    try:
                        os.close(spare_signal_w)
                    except OSError:
                        pass
                    spare_signal_w = None
                    state.ctx["signal_w"] = -1
            if use_drain:
                return _pump_drain_c()
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
        except BaseException:
            # W-PY22 abort choreography on abnormal generator exit
            # (consumer abandon/GeneratorExit, worker-crash
            # propagation, KeyboardInterrupt): quiesce -> reap ->
            # snapshot -> publish, then re-raise. No yields here.
            # Stream has no output sidecar — the consumer owns
            # everything yielded live.
            try:
                checkpoint_on_abort(lib, state=state,
                                    orderer_pid=orderer_pid,
                                    order_w=order_w,
                                    coll_fd=None, use_orderer=use_orderer,
                                    collect=False, resume_src=resume,
                                    checkpoint_file=checkpoint_file,
                                    engine_live=engine_live)
            except Exception:
                pass
            raise
        finally:
            pass

        _reactor_failure_check(state, workers, on_error)

        if use_drain and cdrain["pid"] is not None:
            # Results EOF ⇒ the drain exited — join it for its rc
            # (worker error above already raised; teardown covers).
            if cdrain["alive"]:
                try:
                    _, _dst = os.waitpid(cdrain["pid"], 0)
                except ChildProcessError:
                    pass
                except OSError:
                    pass
                else:
                    cdrain["alive"] = False
                    cdrain["status"] = _dst
            cdrain_status = cdrain["status"]
            if cdrain_status is not None and cdrain_status != 0 and not (
                    os.WIFEXITED(cdrain_status) and
                    os.WEXITSTATUS(cdrain_status) == 0):
                raise RuntimeError(
                    "forkrun: C drain failed (status %r)"
                    % (cdrain_status,))

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
        if stats is not None and drain["reassembly"] is not None \
                and not use_drain:
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
                          coll_fd=coll_fd, coll_hold=coll_hold,
                          drain_pid=cdrain_pid,
                          results_fd=cresults_r,
                          spare_signal_w=spare_signal_w)


# =====================================================================
# W-PY20 parameter sweeps — bash ::: / :::: / --link equivalent.
#
# Pure frontend feature: combinations are generated by _sweep.py and
# each becomes ordinary batches whose .metadata carries the sweep
# tuple. The engine never sees sweeps (same claim/ack loop, no new
# syscalls, no new IPC).
# =====================================================================

def sweep(payload, source=None, *, args=None, args_from=None,
          link=False, workers=None, on_error="retry", **kwargs):
    """Parameter sweep: run payload once per argument combination.

    payload: Batch -> bytes (receives .metadata with the sweep tuple;
      mode="spawn"/"plugin" run per combination with metadata set but
      unused by the external entry point — use mode="python" to
      consume it). mode="splice" is rejected (no payload exists to
      receive metadata).
    source: optional input every combination processes (path | fd |
      pipe/socket, same contract as map). None = standalone combos.
    args: list of lists (one per dimension); args_from: list of file
      paths (one dimension per file, one value per line).
    link: False (default) = Cartesian product (bash :::); True = zip
      dimensions pairwise with shortest-truncation warning (--link).
    workers/on_error: as in map (workers defaults to min(8, combos)
      standalone, cpu-count with source).
    Additional kwargs (lines/bytes/order/mode/streaming/
    orchestrator/nodes) forward to the underlying map call(s),
    except standalone sweeps force lines=1 + order="index" (the
    batch↔combination 1:1 mapping and combination-order results are
    load-bearing — conflicting values raise ValueError rather than
    silently scrambling).

    Returns one result per combination, in combination order. Empty
    combinations → []. Payload errors ride the usual escrow/retry/
    poison path per batch (= per combination standalone).
    """
    from ._sweep import generate_combinations

    if kwargs.get("sink") is not None:
        raise ValueError(
            "sweep() collects results — sink= is not accepted (the "
            "payload return value is the result)")
    if kwargs.get("mode", "python") == "splice":
        raise ValueError(
            "sweep() with mode='splice' is rejected: no payload "
            "exists to receive batch.metadata (passthrough has no "
            "per-combination hook)")
    combos = list(generate_combinations(args=args, args_from=args_from,
                                        link=link))
    if not combos:
        return []
    if source is not None:
        return _execute_sweep_with_source(
            payload, source, combos, workers, on_error, **kwargs)
    return _execute_sweep_standalone(payload, combos, workers,
                                     on_error, **kwargs)


def _execute_sweep_standalone(payload, combinations, workers, on_error,
                              **kwargs):
    """Standalone sweep: one batch per combination, no source data.

    Synthetic input (one index line per combination) run with
    lines=1 (exactly one batch per line — adaptive batching would
    otherwise pack several combos into one batch and break the
    index mapping) and order="index" (results in combination
    order — completion order would scramble it). Both are forced:
    user-supplied lines=/bytes=/order= raise instead of silently
    violating the mapping.
    """
    import tempfile as _tf

    if kwargs.get("lines") is not None \
            or kwargs.get("bytes") is not None:
        raise ValueError(
            "standalone sweep() forces lines=1 (one batch per "
            "combination) — lines=/bytes= would merge combinations")
    if kwargs.get("order") is not None \
            and kwargs.get("order") != "index":
        raise ValueError(
            "standalone sweep() forces order='index' (results in "
            "combination order) — got %r" % (kwargs.get("order"),))
    n = len(combinations)
    with _tf.NamedTemporaryFile(mode="w", suffix=".txt",
                                delete=False) as fh:
        for i in range(n):
            fh.write("%d\n" % i)
        path = fh.name
    try:
        def sweep_payload(batch):
            try:
                combo_idx = int(bytes(batch.data).strip())
            except ValueError:
                raise RuntimeError(
                    "forkrun: sweep index batch unparseable: %r"
                    % (bytes(batch.data)[:32],))
            batch.metadata = combinations[combo_idx]
            return payload(batch)

        return map(sweep_payload, path,
                   workers=(workers if workers is not None
                            else min(8, n)),
                   on_error=on_error, lines=1, order="index",
                   **{k: v for k, v in kwargs.items()
                      if k not in ("lines", "bytes", "order")})
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _execute_sweep_with_source(payload, source, combinations,
                               workers, on_error, **kwargs):
    """Sweep over source data: each combination processes the source.

    One map() per combination (≤100 expected; bounded inputs only —
    same materialization contract as map). Path sources are reused
    directly; fd/pipe sources are materialized to a temp file ONCE
    (a repeated drain would observe EOF after the first combo).
    Within each combo the order defaults to "index" for
    determinism unless the caller sets order=.
    """
    import os as _os

    if isinstance(source, (str, bytes, _os.PathLike)):
        # Path sources reopen per combination — reuse directly.
        combo_source = source
        tmp_hold = None
    else:
        # fd / fileno() object: consume once into a temp file so
        # every combination observes the full source. Rewind
        # seekables first (the kernel spill path reads from
        # explicit offset 0 regardless of position; pipes raise
        # ESPIPE here and read from the current position as usual).
        import tempfile as _tf
        src_fd, must_close = _open_source(source)
        try:
            try:
                os.lseek(src_fd, 0, os.SEEK_SET)
            except OSError:
                pass
            chunks = []
            while True:
                try:
                    chunk = os.read(src_fd, _CHUNK)
                except OSError as exc:
                    raise RuntimeError(
                        "failed reading source: %s" % (exc,))
                if not chunk:
                    break
                chunks.append(chunk)
            blob = b"".join(chunks)
        finally:
            if must_close:
                try:
                    os.close(src_fd)
                except OSError:
                    pass
        tmp = _tf.NamedTemporaryFile(mode="wb", suffix=".txt",
                                     delete=False)
        try:
            tmp.write(blob)
            tmp.close()
            combo_source = tmp.name
        except OSError:
            try:
                tmp.close()
            except OSError:
                pass
            raise
        tmp_hold = tmp.name

    kwargs = dict(kwargs)
    kwargs.setdefault("order", "index")
    try:
        results = []
        for combo in combinations:
            def combo_payload(batch, _combo=combo):
                batch.metadata = _combo
                return payload(batch)

            results.extend(map(combo_payload, combo_source,
                               workers=workers, on_error=on_error,
                               **kwargs))
        return results
    finally:
        if tmp_hold is not None:
            try:
                os.unlink(tmp_hold)
            except OSError:
                pass


# =====================================================================
# W-PY21 NUMA multi-node pipeline executors.
#
# Topology (engine owns the mechanism; this module only forks it):
#   ingest (born-local MPOL_BIND distributor, owns the source fd) →
#   N indexers (chunk boundaries, self-pinned) →
#   N scanners (per-node rings, distance-charged stealing) →
#   workers (per-node claims, self-pinned via fr_py_worker_init) →
#   physical fallow (PhysPackets) + C orderer (numa=1) as needed.
# Workers fork per-node on that node's first DATA publish (the
# W-PY19 pre-flight rule, applied per ring), with a global stall
# fallback for slow sources. Scanner spawn pipes stay disarmed
# (fd -1): auto-forking on the scanner's startup burst would trip
# the CASE-B pre-flight bail (silent loss) — publish-gating is the
# safe rule, same rationale as W-PY19 ingest.
# =====================================================================

def _pump_debug_tick():
    """Env-gated pump diagnostic throttle (W-PY21-A debugging).

    Returns True ~once/sec when FORKRUN_DEBUG_PUMP is set, else
    False. Zero overhead otherwise (one getenv per call — the
    callers already do costlier work per round; never enabled in
    tests or benchmarks).
    """
    import time as _t
    now = _t.monotonic()
    last = _pump_debug_tick._last
    if os.environ.get("FORKRUN_DEBUG_PUMP") and now - last >= 1.0:
        _pump_debug_tick._last = now
        return True
    return False


_pump_debug_tick._last = 0.0


def _pump_debug_log(msg):
    try:
        os.write(2, ("[pump %d] %s\n" % (os.getpid(), msg)).encode())
    except OSError:
        pass


def _numa_fork_pipeline(lib, memfd, src_fd, num_nodes, engine_fds):
    """Fork fallow-phys + N indexers + N scanners + ingest (W-PY21).

    All children scrub to their keep set and never return (os._exit
    with the engine rc). Scanners run with spawn disarmed (-1).
    Returns a dict with pids, death-pipe read ends, and the fallow
    write-end spare. The caller owns src_fd (closes it when
    must_close after this returns — every child already inherited
    what it needs).
    """
    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        sys.stderr.flush()
    except Exception:
        pass

    fallow_r, fallow_w = os.pipe()
    fallow_pid = os.fork()
    if fallow_pid == 0:
        try:
            scrub_fds(engine_fds | {fallow_r, memfd})
            rc = lib.fr_py_fallow_phys(fallow_r, memfd)
        except BaseException:
            rc = 1
        os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
    try:
        os.close(fallow_r)
    except OSError:
        pass

    indexer_pids = []
    indexer_deaths = []
    for node in range(num_nodes):
        death_r, death_w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(death_r)
            except OSError:
                pass
            try:
                scrub_fds(engine_fds | {memfd, death_w})
                rc = lib.fr_py_indexer_numa(memfd, node)
            except BaseException:
                rc = 1
            os._exit(rc if isinstance(rc, int) and 0 <= rc < 256
                      else 1)
        try:
            os.close(death_w)
        except OSError:
            pass
        indexer_pids.append(pid)
        indexer_deaths.append(death_r)

    scanner_pids = []
    scanner_deaths = []
    for node in range(num_nodes):
        death_r, death_w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(death_r)
            except OSError:
                pass
            try:
                scrub_fds(engine_fds | {memfd, death_w})
                rc = lib.fr_py_numa_scanner(memfd, node, -1,
                                            num_nodes)
            except BaseException:
                rc = 1
            os._exit(rc if isinstance(rc, int) and 0 <= rc < 256
                      else 1)
        try:
            os.close(death_w)
        except OSError:
            pass
        scanner_pids.append(pid)
        scanner_deaths.append(death_r)

    ingest_death_r, ingest_death_w = os.pipe()
    ingest_pid = os.fork()
    if ingest_pid == 0:
        try:
            os.close(ingest_death_r)
        except OSError:
            pass
        try:
            scrub_fds(engine_fds | {src_fd, memfd, ingest_death_w})
            rc = lib.fr_py_numa_ingest(src_fd, memfd, num_nodes)
        except BaseException:
            rc = 1
        os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
    try:
        os.close(ingest_death_w)
    except OSError:
        pass

    return {"fallow_pid": fallow_pid, "fallow_w": fallow_w,
            "indexer_pids": indexer_pids,
            "indexer_deaths": indexer_deaths,
            "scanner_pids": scanner_pids,
            "scanner_deaths": scanner_deaths,
            "ingest_pid": ingest_pid,
            "ingest_death": ingest_death_r}


def _execute_numa_locked(payload, source, *, sink, lines, bytes_,
                         workers, on_error, collect, order,
                         mode="python", numa_map="", num_nodes=2,
                         node_cpus=None, splice=False, c_drain=True):
    """Blocking map/run over the NUMA pipeline (W-PY21).

    init_numa → empty ingress memfd → pipeline (fallow-phys,
    indexers, scanners, ingest owning the source) → per-node
    publish-gated worker forks → reactor_run → failure accounting
    → orderer/parse → helper joins → teardown. Raises RuntimeError
    on ingest/indexer/scanner failure, trap-ACK timeout, or
    unrecovered deaths. Requires num_nodes > 1 (caller routes UMA
    elsewhere).
    c_drain (W-PY21-A, opt-in True, non-orderer collect): workers
    signal a forked C drain loop (results memfd read once at end)
    instead of the parent parsing per-worker memfds.
    """
    from ._bindings import v1_available as _v1a
    from ._numa import wid_to_node
    from ._reactor import (ORDER_PIPE_SIZE, ReactorState,
                           check_scanner_death, reactor_poll_once,
                           reactor_run, spawn_orderer)
    import fcntl as _fcntl

    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init_numa(lines or 0, bytes_ or 0, num_nodes,
                           numa_map.encode() if numa_map else None
                           ) != RC_OK:
        raise RuntimeError("NUMA substrate init failed")
    engine_fds = snapshot_fds() - pre_fds

    src_fd, must_close = _open_source(source)
    memfd = None
    mem_hold: list = []
    out_fds: list = []
    out_hold: list = []
    order_r = order_w = None
    coll_fd = None
    coll_hold: list = []
    orderer_pid = None
    trap_r = trap_w = None
    signal_r = None
    signal_w = None
    drain_pid = None
    results_fd = None
    fallow_w = None
    pipe = None
    state = None
    helpers = {"fallow_rc": None, "ingest_kind": None,
               "ingest_code": None, "index": {}, "scan": {}}
    forked = set()
    t_start = _time.monotonic()
    try:
        memfd, mem_hold = _new_ingress_memfd()
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        if collect:
            out_fds, out_hold = _new_output_memfds(workers)

        use_orderer = (collect and order == "index" and not splice
                       and _v1a(lib).get("orderer"))
        # C drain for collect without the orderer (orderer path is
        # already C-speed end to end).
        use_drain = bool(c_drain) and collect and not use_orderer
        if use_drain:
            _require_drain_symbol()
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
                                        unordered=False, numa=True,
                                        engine_fds=engine_fds,
                                        out_fds=out_fds)

        if use_drain:
            # Workers signal the drain; the parent keeps the spare
            # write end for respawns (closed when no worker is live).
            signal_r, signal_w, _ = make_pipe()

        trap_r, trap_w = os.pipe()

        pipe = _numa_fork_pipeline(lib, memfd, src_fd, num_nodes,
                                   engine_fds)
        fallow_w = pipe["fallow_w"]
        if must_close:
            try:
                os.close(src_fd)
            except OSError:
                pass
            must_close = False

        from ._numa import wid_to_node
        # wid → node blocks (stable for the run: respawns reuse the
        # wid, hence the same memfd and the same claim ring).
        wid_node = wid_to_node(workers, num_nodes)

        state = ReactorState(workers, num_nodes=num_nodes,
                             respawn_cap=REACTOR_RESPAWN_CAP,
                             spawn_ceiling=workers)
        state.configure(payload_spec=payload, sink_spec=sink,
                        memfd=memfd, file_size=-1,
                        out_fds=list(out_fds) if collect else [],
                        signal_w=signal_w if use_drain else None,
                        fallow_w=fallow_w,
                        order_w=order_w if use_orderer else -1,
                        trap_ack_w=trap_w, on_error=on_error,
                        engine_fds=engine_fds, splice=splice,
                        node_cpus=node_cpus)
        state.trap_ack_r = trap_r

        def _ready_all():
            try:
                return [lib.fr_py_data_ready_node(n)
                        for n in range(num_nodes)]
            except Exception:
                return [0] * num_nodes

        def _poll_ingest():
            # One nonblocking ingest-death classification. Records
            # definitive outcomes (the pipe is consumed/closed
            # inside); raises on error.
            if helpers["ingest_kind"] is not None:
                return
            kind, code = check_scanner_death(
                pipe["ingest_pid"], pipe["ingest_death"])
            if kind != "running":
                helpers["ingest_kind"] = kind
                helpers["ingest_code"] = code
                pipe["ingest_death"] = None
                if kind == "error":
                    lib.fr_py_abort()
                    raise RuntimeError(
                        "forkrun: NUMA ingest failed (status %r)"
                        % (code,))

        def _watch_pipeline():
            # Fallow death (WNOHANG) is fatal; indexer/scanner/ingest
            # deaths classify via their death pipes. Error kinds
            # raise at once. A clean indexer/scanner exit keys on
            # ingest EOF POSTED (fr_py_ingest_eof_posted — the same
            # sentinel the indexers watch), NOT on ingest process
            # exit: the ingest routinely outlives its helpers (it
            # flushes on chunk_done before exiting), so
            # exit-ordering alone cannot tell normal teardown
            # ("helper done after EOF posted, ingest still
            # flushing") from tail loss ("helper done before EOF
            # was even posted" — fatal).
            try:
                wpid, st = os.waitpid(pipe["fallow_pid"], os.WNOHANG)
            except (ChildProcessError, OSError):
                wpid, st = None, None
            if wpid == pipe["fallow_pid"]:
                helpers["fallow_rc"] = st
                ok = os.WIFEXITED(st) and os.WEXITSTATUS(st) == 0
                if not ok:
                    lib.fr_py_abort()
                    raise RuntimeError(
                        "forkrun: NUMA reaper failed (status %r)"
                        % (st,))
            _poll_ingest()
            try:
                eof_posted = lib.fr_py_ingest_eof_posted()
            except Exception:
                eof_posted = 0
            for pids, deaths, key in (
                    (pipe["indexer_pids"], pipe["indexer_deaths"],
                     "index"),
                    (pipe["scanner_pids"], pipe["scanner_deaths"],
                     "scan")):
                for node in range(num_nodes):
                    if node in helpers[key]:
                        continue
                    kind, code = check_scanner_death(
                        pids[node], deaths[node])
                    if kind == "running":
                        continue
                    if kind == "error" or not eof_posted:
                        helpers[key][node] = (kind, code)
                        deaths[node] = None
                        lib.fr_py_abort()
                        raise RuntimeError(
                            "forkrun: NUMA %s %d failed "
                            "(status %r)" % (key, node, code))
                    helpers[key][node] = (kind, code)
                    deaths[node] = None

        def _fork_node(node):
            for wid, nd in enumerate(wid_node):
                if nd == node:
                    state.spawn_worker(wid=wid, node=node)
            forked.add(node)

        def _all_helpers_done():
            return (helpers["ingest_kind"] == "clean"
                    and len(helpers["index"]) >= num_nodes
                    and len(helpers["scan"]) >= num_nodes)

        # Fork-timing loop: per-node publish gating + global stall
        # fallback. Ends when every node forked, or when the whole
        # pipeline is done (ingest + all indexers + all scanners
        # clean — then fstat below separates empty input from a
        # publish anomaly). Fork-on-publish precedes the done-check
        # each round so a publish coinciding with pipeline EOF still
        # forks before the loop can exit.
        stalled = False
        while len(forked) < num_nodes:
            _watch_pipeline()
            reactor_poll_once(state)
            for node, ready in enumerate(_ready_all()):
                if ready > 0 and node not in forked:
                    _fork_node(node)
            if len(forked) >= num_nodes:
                break
            if _all_helpers_done():
                break
            if not stalled and (
                    _time.monotonic() - t_start) >= STALL_FORK_AFTER:
                stalled = True
                for node in range(num_nodes):
                    if node not in forked:
                        _fork_node(node)
            _time.sleep(0.05)

        if not forked:
            # Nothing published and ingest is done: empty input
            # (fstat 0) skips workers; anything landed is a loud
            # anomaly (never silent loss).
            try:
                landed = os.fstat(memfd).st_size
            except OSError:
                landed = 0
            if landed != 0:
                raise RuntimeError(
                    "forkrun: NUMA ingest landed %d bytes with no "
                    "published batches" % landed)
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
            if use_drain:
                # No workers ⇒ no drain forked; drop the unused
                # signal pipe.
                for _fd in (signal_w, signal_r):
                    if _fd is not None:
                        try:
                            os.close(_fd)
                        except OSError:
                            pass
                signal_w = signal_r = None
        else:
            if use_drain and drain_pid is None:
                # Workers exist; the drain takes signal_r from here
                # on (the parent never selects on it — control only).
                # The spare write end stays open for respawns.
                drain_pid, results_fd = _fork_drain(
                    signal_r, out_fds, workers, mode="memfd")
                signal_r = None
            try:
                reactor_run(state, service=_watch_pipeline)
            except KeyboardInterrupt:
                raise

        _reactor_failure_check(state, workers, on_error)

        if fallow_w is not None:
            try:
                os.close(fallow_w)
            except OSError:
                pass
            fallow_w = None
            if state is not None:
                state.ctx["fallow_w"] = -1
        if use_drain and drain_pid is not None:
            # Drop the signal spare so the drain observes EOF, then
            # join it for its rc (worker error above already raised;
            # teardown covers that path).
            if signal_w is not None:
                try:
                    os.close(signal_w)
                except OSError:
                    pass
                signal_w = None
                state.ctx["signal_w"] = -1
            try:
                _, _dst = os.waitpid(drain_pid, 0)
            except ChildProcessError:
                _dst = 0
            drain_pid = None
            if _dst != 0 and not (
                    os.WIFEXITED(_dst) and os.WEXITSTATUS(_dst) == 0):
                raise RuntimeError(
                    "forkrun: C drain failed (status %r)" % (_dst,))
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

        # Helper joins: ingest strict-clean; indexers/scanners
        # strict unless already observed (proof-based leniency only
        # when teardown already reaped them — same rule as UMA).
        if helpers["ingest_kind"] == "error":
            raise RuntimeError(
                "forkrun: NUMA ingest failed (status %r)"
                % (helpers["ingest_code"],))
        if helpers["ingest_kind"] is None:
            try:
                _, _st = os.waitpid(pipe["ingest_pid"], 0)
            except ChildProcessError:
                _st = None
            if _st is not None and not (
                    os.WIFEXITED(_st) and os.WEXITSTATUS(_st) == 0):
                raise RuntimeError(
                    "forkrun: NUMA ingest failed (status %r)" % (_st,))
        for key, pids in (("index", pipe["indexer_pids"]),
                          ("scan", pipe["scanner_pids"])):
            for node in range(num_nodes):
                if node in helpers[key]:
                    kind, code = helpers[key][node]
                    if kind == "error":
                        raise RuntimeError(
                            "forkrun: NUMA %s %d failed (status %r)"
                            % (key, node, code))
                    continue
                try:
                    _, _st = os.waitpid(pids[node], 0)
                except ChildProcessError:
                    _st = None
                if _st is not None and not (
                        os.WIFEXITED(_st) and os.WEXITSTATUS(_st) == 0):
                    raise RuntimeError(
                        "forkrun: NUMA %s %d failed (status %r)"
                        % (key, node, _st))
        if helpers["fallow_rc"] is None:
            try:
                _, _fst = os.waitpid(pipe["fallow_pid"], 0)
            except ChildProcessError:
                _fst = None
            if _fst is not None and not (
                    os.WIFEXITED(_fst) and os.WEXITSTATUS(_fst) == 0):
                try:
                    os.write(2, b"forkrun [WARN]: NUMA reaper exited "
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
        if use_drain:
            # Dynamic-fork paths (ingest/NUMA) fork no drain on
            # empty input (no workers ever existed) — vacuously
            # no records. Materialized paths always fork workers,
            # so their drain always exists here.
            records = (_parse_records(_read_fd_all(results_fd))
                       if results_fd is not None else [])
        else:
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
        extra = []
        if pipe is not None:
            extra = ([pipe["fallow_pid"], pipe["ingest_pid"]]
                     + pipe["indexer_pids"] + pipe["scanner_pids"])
            # Death-pipe read ends the watches already consumed
            # (closed inside check_scanner_death); close any still
            # open so fd counts stay stable across runs.
            for _dr in ([pipe["ingest_death"]] + pipe["indexer_deaths"]
                        + pipe["scanner_deaths"]):
                if _dr is not None:
                    try:
                        os.close(_dr)
                    except OSError:
                        pass
        _teardown_reactor(lib, state, out_fds=out_fds,
                          out_hold=out_hold, memfd=memfd,
                          mem_hold=mem_hold,
                          src_fd=src_fd, must_close=must_close,
                          extra_pids=[p for p in extra
                                      if p is not None],
                          orderer_pid=orderer_pid, order_r=order_r,
                          order_w=order_w, trap_r=trap_r, trap_w=trap_w,
                          coll_fd=coll_fd, coll_hold=coll_hold,
                          drain_pid=drain_pid, results_fd=results_fd,
                          spare_signal_w=signal_w)


def _numa_stream_gen(payload, source, *, lines, bytes_, workers,
                       on_error, mode, order, orchestrator, numa_map,
                       num_nodes, node_cpus, splice=False, c_drain=True):
    # stream() over the NUMA pipeline: live drain while the ingest
    # feeds per-node rings. Always reactor-supervised (the NUMA path
    # is new in W-PY21 — no legacy non-reactor NUMA exists to preserve).
    _ = orchestrator  # accepted for call uniformity; NUMA implies reactor
    yield from _execute_numa_stream(
        payload, source, lines=lines, bytes_=bytes_, workers=workers,
        on_error=on_error, mode=mode, order=order,
        numa_map=numa_map, num_nodes=num_nodes, node_cpus=node_cpus,
        splice=splice, c_drain=c_drain)


def _execute_numa_stream(payload, source, *, lines, bytes_, workers,
                         on_error, mode="python", order="none",
                         numa_map="", num_nodes=2, node_cpus=None,
                         stats=None, splice=False, c_drain=True):
    """stream() over the NUMA pipeline (W-PY21 generator).

    Same pipeline as _execute_numa_locked, but the parent drains
    live: signal wakeups + incremental preads (per-worker memfds, or
    the C orderer's collection file when order=index non-splice).
    pump_done = ingest observed done AND (workers forked OR input
    was empty). Abandonment tears down via the finally.
    c_drain (W-PY21-A, opt-in True, non-orderer paths): a forked C
    loop moves signal consume + memfd pread into a results pipe
    the parent reads incrementally (never signals/memfds itself).
    """
    from ._bindings import v1_available as _v1a
    from ._numa import wid_to_node
    from ._reactor import (ORDER_PIPE_SIZE, ReactorState,
                           check_scanner_death, reactor_loop,
                           spawn_orderer)
    import fcntl as _fcntl
    import select as _select

    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if order not in ("none", "index"):
        raise ValueError(
            "order must be 'none' or 'index', got %r" % (order,))
    pre_fds = snapshot_fds()
    lib = load()
    if lib.fr_py_init_numa(lines or 0, bytes_ or 0, num_nodes,
                           numa_map.encode() if numa_map else None
                           ) != RC_OK:
        raise RuntimeError("NUMA substrate init failed")
    engine_fds = snapshot_fds() - pre_fds

    src_fd, must_close = _open_source(source)
    memfd = None
    mem_hold: list = []
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
    drain_pid = None
    results_r = None
    fallow_w = None
    pipe = None
    state = None
    helpers = {"fallow_rc": None, "ingest_kind": None,
               "ingest_code": None, "index": {}, "scan": {}}
    forked = set()
    pump_state = {"done": False, "t_start": _time.monotonic(),
                  "stalled": False}
    try:
        memfd, mem_hold = _new_ingress_memfd()
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        out_fds, out_hold = _new_output_memfds(workers)
        signal_r, signal_w, _ = make_pipe()

        use_orderer = (order == "index" and not splice
                       and _v1a(lib).get("orderer"))
        # C drain for non-orderer paths (orderer path already C-speed).
        use_drain = bool(c_drain) and not use_orderer
        if use_drain:
            _require_drain_symbol()
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
                                        unordered=False, numa=True,
                                        engine_fds=engine_fds,
                                        out_fds=out_fds)

        trap_r, trap_w = os.pipe()

        pipe = _numa_fork_pipeline(lib, memfd, src_fd, num_nodes,
                                   engine_fds)
        fallow_w = pipe["fallow_w"]
        if must_close:
            try:
                os.close(src_fd)
            except OSError:
                pass
            must_close = False

        # wid → node blocks (stable for the run — see locked path).
        stream_wid_node = wid_to_node(workers, num_nodes)

        state = ReactorState(workers, num_nodes=num_nodes,
                             respawn_cap=REACTOR_RESPAWN_CAP,
                             spawn_ceiling=workers)
        state.configure(payload_spec=payload, sink_spec=None,
                        memfd=memfd, file_size=-1,
                        out_fds=list(out_fds), signal_w=signal_w,
                        fallow_w=fallow_w,
                        order_w=order_w if use_orderer else -1,
                        trap_ack_w=trap_w, on_error=on_error,
                        engine_fds=engine_fds, splice=splice,
                        node_cpus=node_cpus)
        state.trap_ack_r = trap_r
        spare_signal_w = os.dup(signal_w)

        def _drop_parent_signal():
            nonlocal signal_w
            # NOTE: signal_w MUST go None here (W-PY21-A erratum):
            # without it every _fork_node re-closes the same NUMBER,
            # which the results pipe later recycles — killing the
            # pump's read end and hanging with data ready but unread.
            if signal_w is not None:
                try:
                    os.close(signal_w)
                except OSError:
                    pass
                signal_w = None
            state.ctx["signal_w"] = spare_signal_w

        def _fork_node(node):
            for wid, nd in enumerate(stream_wid_node):
                if nd == node:
                    state.spawn_worker(wid=wid, node=node)
            _drop_parent_signal()
            forked.add(node)

        def _poll_ingest():
            if helpers["ingest_kind"] is not None:
                return
            kind, code = check_scanner_death(
                pipe["ingest_pid"], pipe["ingest_death"])
            if kind != "running":
                helpers["ingest_kind"] = kind
                helpers["ingest_code"] = code
                pipe["ingest_death"] = None
                if kind == "error":
                    lib.fr_py_abort()
                    raise RuntimeError(
                        "forkrun: NUMA ingest failed (status %r)"
                        % (code,))

        def _watch_pipeline():
            # Same classification contract as the locked NUMA path:
            # clean helper exits key on ingest EOF POSTED (not on
            # ingest process exit — the ingest flushes last).
            try:
                wpid, st = os.waitpid(pipe["fallow_pid"], os.WNOHANG)
            except (ChildProcessError, OSError):
                wpid, st = None, None
            if wpid == pipe["fallow_pid"]:
                helpers["fallow_rc"] = st
                ok = os.WIFEXITED(st) and os.WEXITSTATUS(st) == 0
                if not ok:
                    lib.fr_py_abort()
                    raise RuntimeError(
                        "forkrun: NUMA reaper failed (status %r)"
                        % (st,))
            _poll_ingest()
            try:
                eof_posted = lib.fr_py_ingest_eof_posted()
            except Exception:
                eof_posted = 0
            for pids, deaths, key in (
                    (pipe["indexer_pids"], pipe["indexer_deaths"],
                     "index"),
                    (pipe["scanner_pids"], pipe["scanner_deaths"],
                     "scan")):
                for node in range(num_nodes):
                    if node in helpers[key]:
                        continue
                    kind, code = check_scanner_death(
                        pids[node], deaths[node])
                    if kind == "running":
                        continue
                    if kind == "error" or not eof_posted:
                        helpers[key][node] = (kind, code)
                        deaths[node] = None
                        lib.fr_py_abort()
                        raise RuntimeError(
                            "forkrun: NUMA %s %d failed "
                            "(status %r)" % (key, node, code))
                    helpers[key][node] = (kind, code)
                    deaths[node] = None

        def _fork_timing():
            if len(forked) >= num_nodes:
                return
            try:
                ready = [lib.fr_py_data_ready_node(n)
                         for n in range(num_nodes)]
            except Exception:
                ready = [0] * num_nodes
            for node, r in enumerate(ready):
                if r > 0 and node not in forked:
                    _fork_node(node)
            if len(forked) < num_nodes and not pump_state["stalled"] \
                    and (_time.monotonic() - pump_state["t_start"]
                         ) >= STALL_FORK_AFTER:
                pump_state["stalled"] = True
                for node in range(num_nodes):
                    if node not in forked:
                        _fork_node(node)

        def _all_helpers_done():
            # Full-pipeline quiescence (same rule as the locked NUMA
            # path): the ingest is fast (ms on small files) while
            # indexers/scanners are still spinning up, so ingest-clean
            # alone must never trigger the empty/anomaly verdict —
            # only the whole pipeline being done does.
            return (helpers["ingest_kind"] == "clean"
                    and len(helpers["index"]) >= num_nodes
                    and len(helpers["scan"]) >= num_nodes)

        # W-PY21-A drain delegation state (pipe mode; forked lazily
        # once some node forked — signals queue until the drain
        # starts; empty inputs never need one).
        cdrain_n = {"pid": None, "results_r": None, "pump": None,
                    "status": None, "alive": True}

        def _pump_drain_c_numa():
            # W-PY21-A quantum: results-pipe consumer. The spill
            # side already ran above in _pump_drain. Same
            # StopIteration contract (results exhausted AND spill
            # pump done — else keep polling).
            nonlocal signal_r, drain_pid, results_r
            if forked and cdrain_n["pid"] is None:
                cdrain_n["pid"], cdrain_n["results_r"] = _fork_drain(
                    signal_r, out_fds, workers, mode="pipe")
                cdrain_n["pump"] = _make_results_pump(
                    cdrain_n["results_r"], order=order, stats=stats)
                signal_r = None
                drain_pid = cdrain_n["pid"]
                results_r = cdrain_n["results_r"]
            if cdrain_n["pid"] is None:
                return None
            if cdrain_n["alive"]:
                try:
                    wpid, _dst = os.waitpid(cdrain_n["pid"], os.WNOHANG)
                except ChildProcessError:
                    cdrain_n["alive"] = False
                except OSError:
                    pass
                else:
                    if wpid == cdrain_n["pid"]:
                        cdrain_n["alive"] = False
                        cdrain_n["status"] = _dst
            try:
                return cdrain_n["pump"](
                    bool(any(s.alive for s in state.workers.values()))
                    or cdrain_n["alive"])
            except StopIteration:
                if pump_state["done"]:
                    raise
                return None

        _sig = struct.Struct("<QQ")
        drain = {"coll_off": 0, "coll_tail": b"", "sig_buf": b"",
                 "sig_eof": False, "pending": [],
                 "reassembly": None}
        if order == "index" and not use_orderer:
            drain["reassembly"] = ReassemblyBuffer()
        per_worker = [[0, b""] for _ in range(workers)]

        def _parse_quantum():
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

        def _sweep_memfds():
            # Safety sweep before EOF (short final writes).
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
                        drain["pending"].extend(
                            blob for _, blob in recs)
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
            if drain["reassembly"] is not None:
                for _, ordered in drain["reassembly"].final_drain():
                    drain["pending"].append(ordered)

        def _pump_drain():
            nonlocal spare_signal_w, signal_w
            # Spare-drop rule (W-PY19 erratum, see ingest path):
            # only once some node forked (forked set), never on
            # pre-first-fork rounds — closing early poisons ctx for
            # future forks (signal_w=-1 ⇒ no signals ⇒ starvation).
            if forked and not any(
                    s.alive for s in state.workers.values()):
                if spare_signal_w is not None and spare_signal_w >= 0:
                    try:
                        os.close(spare_signal_w)
                    except OSError:
                        pass
                    spare_signal_w = None
                    state.ctx["signal_w"] = -1
            if _pump_debug_tick():
                _pump_debug_log(
                    "forked=%s live=%s ingest=%s idx=%s scan=%s "
                    "cdrain=%s dalive=%s spare=%s ctxsig=%s sig_r=%s "
                    "res_r=%s done=%s" % (
                        sorted(forked),
                        sorted(w for w, s in state.workers.items()
                               if s.alive),
                        helpers["ingest_kind"],
                        {n: v[0] for n, v in helpers["index"].items()},
                        {n: v[0] for n, v in helpers["scan"].items()},
                        cdrain_n["pid"], cdrain_n["alive"],
                        spare_signal_w, state.ctx.get("signal_w"),
                        signal_r, cdrain_n["results_r"],
                        pump_state["done"]))
            # Spill-side quantum: helper watches + fork timing (the
            # ingest itself is a process — nothing to pump here).
            _watch_pipeline()
            _fork_timing()
            if helpers["ingest_kind"] == "clean" and not forked \
                    and _all_helpers_done():
                try:
                    landed = os.fstat(memfd).st_size
                except OSError:
                    landed = 0
                if landed != 0:
                    raise RuntimeError(
                        "forkrun: NUMA ingest landed %d bytes with no "
                        "published batches" % landed)
                pump_state["done"] = True
            elif helpers["ingest_kind"] == "clean" and (
                    forked or _all_helpers_done()):
                pump_state["done"] = True
            if use_drain:
                # W-PY21-A: results-pipe consumer (the drain owns
                # signals/memfds). Spill side already ran above.
                return _pump_drain_c_numa()
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
            if (pump_state["done"]
                    and not any(s.alive
                                for s in state.workers.values())
                    and drain["sig_eof"] and not drain["sig_buf"]):
                _sweep_memfds()
                if drain["pending"]:
                    return drain["pending"].pop(0)
                raise StopIteration
            return None

        try:
            yield from reactor_loop(state, drain_gen=_pump_drain)
        finally:
            pass

        _reactor_failure_check(state, workers, on_error)

        if use_drain and cdrain_n["pid"] is not None:
            # Results EOF ⇒ the drain exited — join it for its rc
            # (worker error above already raised; teardown covers).
            if cdrain_n["alive"]:
                try:
                    _, _dst = os.waitpid(cdrain_n["pid"], 0)
                except ChildProcessError:
                    pass
                except OSError:
                    pass
                else:
                    cdrain_n["alive"] = False
                    cdrain_n["status"] = _dst
            if cdrain_n["status"] is not None and cdrain_n["status"] != 0 \
                    and not (
                        os.WIFEXITED(cdrain_n["status"]) and
                        os.WEXITSTATUS(cdrain_n["status"]) == 0):
                raise RuntimeError(
                    "forkrun: C drain failed (status %r)"
                    % (cdrain_n["status"],))

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
        if helpers["ingest_kind"] == "error":
            raise RuntimeError(
                "forkrun: NUMA ingest failed (status %r)"
                % (helpers["ingest_code"],))
        if helpers["ingest_kind"] is None:
            try:
                _, _st = os.waitpid(pipe["ingest_pid"], 0)
            except ChildProcessError:
                _st = None
            if _st is not None and not (
                    os.WIFEXITED(_st) and os.WEXITSTATUS(_st) == 0):
                raise RuntimeError(
                    "forkrun: NUMA ingest failed (status %r)" % (_st,))
        for key, pids in (("index", pipe["indexer_pids"]),
                          ("scan", pipe["scanner_pids"])):
            for node in range(num_nodes):
                if node in helpers[key]:
                    kind, code = helpers[key][node]
                    if kind == "error":
                        raise RuntimeError(
                            "forkrun: NUMA %s %d failed (status %r)"
                            % (key, node, code))
                    continue
                try:
                    _, _st = os.waitpid(pids[node], 0)
                except ChildProcessError:
                    _st = None
                if _st is not None and not (
                        os.WIFEXITED(_st) and os.WEXITSTATUS(_st) == 0):
                    raise RuntimeError(
                        "forkrun: NUMA %s %d failed (status %r)"
                        % (key, node, _st))
        if helpers["fallow_rc"] is None:
            try:
                _, _fst = os.waitpid(pipe["fallow_pid"], 0)
            except ChildProcessError:
                _fst = None
            if _fst is not None and not (
                    os.WIFEXITED(_fst) and os.WEXITSTATUS(_fst) == 0):
                try:
                    os.write(2, b"forkrun [WARN]: NUMA reaper exited "
                             b"abnormally; ingress may not be fully "
                             b"reclaimed.\n")
                except OSError:
                    pass
        if stats is not None and drain["reassembly"] is not None \
                and not use_drain:
            stats["reassembly_max"] = drain["reassembly"].max_size

        _reactor_poison_summary(lib, state)
    finally:
        if spare_signal_w is not None and spare_signal_w >= 0:
            try:
                os.close(spare_signal_w)
            except OSError:
                pass
        extra = []
        if pipe is not None:
            extra = ([pipe["fallow_pid"], pipe["ingest_pid"]]
                     + pipe["indexer_pids"] + pipe["scanner_pids"])
            for _dr in ([pipe["ingest_death"]] + pipe["indexer_deaths"]
                        + pipe["scanner_deaths"]):
                if _dr is not None:
                    try:
                        os.close(_dr)
                    except OSError:
                        pass
        _teardown_reactor(lib, state, signal_r=signal_r,
                          out_fds=out_fds, out_hold=out_hold,
                          memfd=memfd, mem_hold=mem_hold,
                          src_fd=src_fd, must_close=must_close,
                          extra_pids=[p for p in extra
                                      if p is not None],
                          orderer_pid=orderer_pid, order_r=order_r,
                          order_w=order_w, trap_r=trap_r, trap_w=trap_w,
                          coll_fd=coll_fd, coll_hold=coll_hold,
                          drain_pid=drain_pid,
                          results_fd=results_r,
                          spare_signal_w=spare_signal_w)


__all__ = ["run", "map", "stream", "sweep"]
