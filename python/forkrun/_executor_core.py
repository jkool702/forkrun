"""W-DEDUP consolidated executor core (Phase 1).

Single-source implementations of the mechanics duplicated across the ten
executors in ``run.py`` (see ``dev/supervisor/DEDUP_DESIGN.md`` + 
``dev/supervisor/EXECUTOR_MANIFEST.md``):

- :func:`fork_workers` — splice / C-plugin / C-spawn / Python fork dispatch
  (one branch per worker kind; the only per-kind code in the tree).
- :func:`collect_records` — drain-vs-direct + order-index-vs-none collection.
- :func:`report_poison` — engine poison summary + ``strict_poison`` mapping.
- :func:`init_engine` — ``fr_py_init`` vs ``fr_py_init_numa`` selection.

Cycle discipline: leaf modules (``_bindings``, ``_fd_scrub``, ``_pipes``,
``_worker``) are imported at top level. ``run.py``-owned helpers
(``_spill_*``, ``_fork_splice_worker``, ``_teardown_*``, ``_parse_*``) are
resolved via ``sys.modules["forkrun.run"]`` lazily inside function bodies —
``forkrun.run`` is the public function shadowing the submodule in the
package namespace, so ``from . import run`` would bind the function, not
the module (see test_executor_consistency.py header). The module is fully
loaded by the time any executor runs, so deferred binding never observes
a partial module. New code must not add top-level ``run`` imports here.

Invariants: I1 (guards) stays at ``run/map/stream`` dispatch (R9 hoist);
I2 (lock) stays in ``_guarded_gen`` / dispatch-site ``_RUN_LOCK``; this
module implements I3/I4/I6/I7/I8 mechanics exactly once.
"""

from __future__ import annotations

import os
import sys
import time as _time

from ._bindings import RC_OK, get as _get_lib
from ._fd_scrub import scrub_fds

# ---------------------------------------------------------------------------
# Spec: the parameter lattice (DEDUP_DESIGN.md §2)
# ---------------------------------------------------------------------------


class ExecutorSpec:
    """Parameter bundle replacing per-executor if-chains.

    Fields mirror the already-boolean flags on every executor signature;
    no new semantics. ``topology`` in {"uma", "numa"}; ``ingest`` in
    {"materialized", "streaming"} ("numa" ignores ``ingest`` — the NUMA
    pipeline owns the source uniformly); ``supervision`` in {"plain",
    "reactor"}; ``shape`` in {"blocking", "generator"} (lifetime only).

    W-REL6-5: the spec is LOAD-BEARING, not documentation. Every core
    function below accepts ``spec=`` and reads its mapped fields from
    it (explicit keywords override per call). Each executor constructs
    one spec naming its lattice position (topology/ingest/supervision/
    shape + behavior flags) and threads it through -- the per-executor
    flag soup collapses to one object.
    """

    __slots__ = ("topology", "ingest", "supervision", "shape",
                 "collect", "splice", "c_drain", "order",
                 "c_worker_loop", "c_spawn_loop",
                 "escrow_fail_loud", "resume_supported")

    def __init__(self, *, topology="uma", ingest="materialized",
                 supervision="plain", shape="blocking",
                 collect=True, splice=False, c_drain=True, order="none",
                 c_worker_loop=False, c_spawn_loop=False,
                 escrow_fail_loud=False, resume_supported=False):
        self.topology = topology
        self.ingest = ingest
        self.supervision = supervision
        self.shape = shape
        self.collect = collect
        self.splice = splice
        self.c_drain = c_drain
        self.order = order
        self.c_worker_loop = c_worker_loop
        self.c_spawn_loop = c_spawn_loop
        self.escrow_fail_loud = escrow_fail_loud
        self.resume_supported = resume_supported


# ---------------------------------------------------------------------------
# Single worker-fork dispatch (I4 escrow discipline lives in the callees)
# ---------------------------------------------------------------------------

_RSS_WARNED = False


def _parent_rss_kb():
    """Resident set size of THIS process, in KiB. None if unavailable."""
    try:
        with open("/proc/self/statm") as fh:
            return int(fh.read().split()[1]) * (os.sysconf("SC_PAGE_SIZE")
                                               // 1024)
    except (OSError, ValueError, IndexError, AttributeError):
        return None


def warn_fork_cost(rss_kb, fork_ms, n_workers):
    """Warn once when this fan-out is paying an unusual fork cost.

    fork() copies the parent's page tables, so its cost scales with the
    parent's RSS rather than with anything the workers touch. Measured
    on this host: 1.6 ms per fork at 10 MB, 58 ms at 1.6 GB -- a 36x
    swing that buys the workers nothing. A user whose host process has
    grown sees forkrun get mysteriously slow with no visible cause, and
    no signal that the cause is their own RSS.

    So measure it and say so, once per process. Emitting this on every
    call would be noise in a loop; never emitting it leaves the cost
    invisible. Threshold via FORKRUN_RSS_WARN_KB (0 disables).

    This is diagnostics only: it never changes behaviour, and a failure
    to read /proc is silent rather than fatal.
    """
    global _RSS_WARNED
    if _RSS_WARNED or rss_kb is None:
        return False
    try:
        limit = int(os.environ.get("FORKRUN_RSS_WARN_KB", "524288"))
    except ValueError:
        limit = 524288
    if limit <= 0 or rss_kb < limit:
        return False
    _RSS_WARNED = True
    per = (fork_ms / n_workers) if n_workers else fork_ms
    import sys as _sys
    print(
        "forkrun: warning: this process holds %.1f GiB resident before "
        "forking %d worker%s (%.1f ms of fork, %.1f ms per worker). fork() "
        "copies page tables, so its cost scales with OUR memory, not with "
        "what the workers read -- the workers will not use these pages. "
        "Call forkrun before the memory-heavy phase, or from a fresh "
        "process, if fan-out latency matters. Suppress with "
        "FORKRUN_RSS_WARN_KB=0."
        % (rss_kb / 1048576.0, n_workers,
           "" if n_workers == 1 else "s", fork_ms, per),
        file=_sys.stderr)
    return True


def fork_workers(lib, *, workers, memfd, size, out_fds, signal_w, fallow_w,
                  engine_fds, payload, sink, mode, on_error,
                  plugin_spec=None, spawn_argv=None, splice=None,
                  c_worker_loop=None, c_spawn_loop=None,
                  src_fd=None, must_close=False, signal_r_to_close=None,
                  spec=None):
    """Fork ``workers`` children; return pid list. Single dispatch site.

    Branches: splice / c_plugin / c_spawn / python — a dispatch table over
    worker kinds (3 branches, costume budget §3). Splice arms intentionally
    deposit nothing on failure (fail-loud, I4 deviation recorded in the
    manifest); all Python-worker paths share the escrow retry helpers via
    ``worker_main``.

    fork() cost scales with parent RSS, so the fan-out is MEASURED and
    reported here -- see ``warn_fork_cost``. Measuring at the ONE place
    workers are forked covers every executor rather than relying on ten
    call sites to remember.

    It deliberately does NOT call malloc_trim(0) first. That was tried,
    on the reasonable theory that returning free heap pages makes the
    page-table copy cheaper. It is cheap, it is plausible, and it
    BREAKS WORKER-DEATH RECOVERY: 31 tests across test_recovery_
    adversarial, test_streaming_recovery, test_reactor, test_numa_
    recovery and others failed with it in place, producing truncated
    output that started at an arbitrary offset (LINE 256 and similar),
    and all passed with it removed. The cause is not fully understood --
    the leading suspicion is that malloc_trim's arena walk interacts
    badly with forking around it -- but the empirical result is
    unambiguous, so the "obviously safe" mitigation was deleted rather
    than kept with a caveat. Do not reintroduce it without a test that
    exercises recovery.

    ``src_fd``/``must_close``: materialized executors close the source in
    the Python child post-fork (parent spilled already; I3 hygiene).
    C-loop children never held it (scrub drops it by construction).

    W-REL6-5: ``splice``/``c_worker_loop``/``c_spawn_loop`` default from
    ``spec`` when not passed explicitly (None = unset; False stays a
    valid explicit value). Callers pass one ExecutorSpec naming their
    lattice position instead of flag soup.

    W-REL6-3.1: string payload/sink specs are resolved HERE, in the
    parent, before the fork loop (backstop: the primary path is
    _coerce_payload at the public-API entry; resolving a callable is
    a no-op). Nothing reaching worker_main is ever imported post-fork.
    """
    if spec is not None:
        if splice is None:
            splice = spec.splice
        if c_worker_loop is None:
            c_worker_loop = spec.c_worker_loop
        if c_spawn_loop is None:
            c_spawn_loop = spec.c_spawn_loop
    else:
        if splice is None:
            splice = False
        if c_worker_loop is None:
            c_worker_loop = False
        if c_spawn_loop is None:
            c_spawn_loop = False
    _rss_before = _parent_rss_kb()
    _t_fork = _time.perf_counter()
    from ._worker import resolve_payload_parent as _resolve_parent
    if payload is not None and isinstance(payload, str):
        payload = _resolve_parent(payload)
    if sink is not None and isinstance(sink, str):
        sink = _resolve_parent(sink)
    # Deferred: _fork_splice_worker lives in run.py (moved here in Phase 3;
    # lazy binding avoids the import cycle meanwhile).
    import sys as _sys
    _run_mod = _sys.modules["forkrun.run"]
    from ._worker import (_fork_c_plugin_worker, _fork_c_spawn_worker,
                          worker_main)

    pids = []
    for i in range(workers):
        if splice:
            pids.append(_run_mod._fork_splice_worker(
                lib, i, memfd, out_fds[i],
                signal_w, fallow_w, engine_fds))
            continue
        if c_worker_loop:
            pids.append(_fork_c_plugin_worker(
                lib, i, plugin_spec[0], plugin_spec[1],
                memfd, out_fds[i], signal_w, fallow_w,
                engine_fds, on_error))
            continue
        if c_spawn_loop:
            pids.append(_fork_c_spawn_worker(
                lib, i, spawn_argv, memfd, out_fds[i],
                signal_w, fallow_w, engine_fds, on_error))
            continue
        pid = os.fork()
        if pid == 0:
            try:
                if signal_r_to_close is not None:
                    # Generator shape: child drops the parent's signal-read
                    # end so EOF detection is exact (streaming drain).
                    try:
                        os.close(signal_r_to_close)
                    except OSError:
                        pass
            except Exception:
                pass
            try:
                if must_close and src_fd is not None:
                    try:
                        os.close(src_fd)
                    except OSError:
                        pass
            except Exception:
                pass
            try:
                keep = set(engine_fds) | {memfd}
                if out_fds is not None and len(out_fds) > i \
                        and out_fds[i] is not None:
                    keep.add(out_fds[i])
                if signal_w is not None:
                    keep.add(signal_w)
                if fallow_w is not None and fallow_w >= 0:
                    keep.add(fallow_w)
                scrub_fds(keep)
            except Exception:
                pass
            try:
                worker_main(i, payload, sink, memfd, size,
                            out_fds[i] if out_fds else None,
                            signal_w, on_error, fallow_w
                            if fallow_w is not None and fallow_w >= 0
                            else None)
            except BaseException:
                pass
            os._exit(127)  # unreachable; worker_main exits
        else:
            pids.append(pid)
    # Measured AFTER, so the number reported is the real fan-out cost and
    # not an estimate. warn_fork_cost is diagnostics only and warns at
    # most once per process.
    try:
        warn_fork_cost(_rss_before,
                       (_time.perf_counter() - _t_fork) * 1e3,
                       max(workers, 1))
    except Exception:
        pass
    return pids


# ---------------------------------------------------------------------------
# Single collection (I7 EOF verification at the callers' join)
# ---------------------------------------------------------------------------

def flush_stdio():
    """Flush the parent's buffered stdout/stderr before any fork.

    A fork duplicates the whole userspace buffer, so anything still
    buffered in the parent is written TWICE -- once by the parent and
    once by the child that inherited the copy. With multiple workers
    inheriting the same buffer the duplication multiplies.

    This is a SEMANTIC rule, not boilerplate, which is why it was worth
    nine identical inline copies (one per executor, plus one at a
    different indent level). A single definition means a future change to
    the policy -- say, an fsync, or a check that the streams are not
    line-buffered -- cannot land in eight of nine executors.

    Errors are ignored deliberately: a stream can legitimately be closed
    or detached under `pythonw`/embedded use, and failing to fork because
    a flush on a dead stream raised would be a worse outcome than
    possibly-unflushed output.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass


def collect_records(*, use_drain=None, results_fd, out_fds, order=None,
                      spec=None, lib=None, views=False):
    """Parse collected output memfds into ordered blobs. Single site.

    Branches: drain-vs-direct (1), order-index-vs-none (1). Byte-identical
    to the ten inline copies it replaces (drain reads ``results_fd``;
    direct reads each of ``out_fds``; ``order == "index"`` sorts).

    W-REL6-5: ``use_drain``/``order`` default from ``spec``
    (``use_drain = spec.c_drain and spec.collect``).

    W-PYZEROCOPY: ``views=True`` with a ``lib`` routes the parse through
    ``_iter_records`` so records are memoryview slices over a mapping of
    the stream instead of per-record copies. Without it this stayed on
    ``_read_fd_all`` + ``_parse_records``, which meant the fail-fast
    (``orchestrator=False``) path silently returned ``bytes`` even when
    the caller asked for ``output="view"``. Framing, record boundaries
    and ordering are ``_iter_records``' contract and are unchanged.
    """
    if spec is not None:
        if use_drain is None:
            use_drain = bool(spec.c_drain and spec.collect)
        if order is None:
            order = spec.order
    else:
        if use_drain is None:
            raise TypeError("collect_records: no spec and no use_drain")
        if order is None:
            raise TypeError("collect_records: no spec and no order")
    import sys as _sys
    _run_mod = _sys.modules["forkrun.run"]

    def _records_from(fd):
        if fd is None:
            return []
        if lib is not None:
            # Always the incremental C iterator, not just for views.
            # _iter_records is documented as equivalent to
            # _parse_records(_read_fd_all(fd)) minus the double
            # buffering, so this is the same RESULT either way -- but
            # the old `views and lib is not None` test sent every
            # views=False caller down the _read_fd_all path, which
            # materialises the whole stream and then copies it again in
            # _parse_records. That is the 155ms-of-638ms join the
            # _iter_records docstring was written to remove, still being
            # paid by the fail-fast path. views is a payload TYPE choice
            # (bytes vs memoryview), never a parser choice.
            return list(_run_mod._iter_records(lib, fd, views=views))
        return _run_mod._parse_records(_run_mod._read_fd_all(fd))

    if use_drain:
        records = _records_from(results_fd)
    else:
        records = []
        for fd in out_fds:
            records.extend(_records_from(fd))
    if order == "index":
        records.sort(key=lambda kv: kv[0])
    return [blob for _, blob in records]


# ---------------------------------------------------------------------------
# Single poison summary (I6 rollback lives in emit paths; this is reporting)
# ---------------------------------------------------------------------------

def report_poison(lib, *, strict_poison=False, npois=None):
    """Emit the engine poison WARN + map strict_poison → raise. Single site.

    W-REL6-5: ``npois`` override for callers whose engine is already
    destroyed (streaming branch finallys): they pass max(live, stash).
    None (default) reads live. WARN text + raise funnel here from all
    scalar paths (legacy streaming/ingest twins collapsed here; the
    reactor summary keeps its batches-carrying twin for state lists).
    """
    import sys as _sys
    _run_mod = _sys.modules["forkrun.run"]

    if npois is None:
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
        _run_mod._raise_for_poisoned(npois, strict_poison)


# ---------------------------------------------------------------------------
# Single engine init (UMA vs NUMA selection, 1 branch)
# ---------------------------------------------------------------------------

def init_engine(lib, *, lines, bytes_, topology=None, num_nodes=1,
                 numa_map="", spec=None):
    """Call fr_py_init / fr_py_init_numa. Single selection site.

    W-REL6-5: ``topology`` defaults from ``spec`` (explicit wins).
    """
    if topology is None:
        topology = spec.topology if spec is not None else "uma"
    if topology == "numa":
        # Call-site-exact form (matches the inlined bodies this
        # replaces): falsy map -> NULL, else encoded/passed through.
        rc = lib.fr_py_init_numa(lines or 0, bytes_ or 0,
                                 num_nodes, numa_map.encode()
                                 if numa_map else None)
    else:
        rc = lib.fr_py_init(lines or 0, bytes_ or 0)
    if rc != RC_OK:
        raise RuntimeError("NUMA substrate init failed"
                           if topology == "numa"
                           else "substrate init failed")
    return rc

__all__ = ["ExecutorSpec", "fork_workers", "collect_records",
           "warn_fork_cost",
           "report_poison", "init_engine", "flush_stdio"]
