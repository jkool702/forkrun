"""W-DEDUP consolidated executor core (Phase 1).

Single-source implementations of the mechanics duplicated across the ten
executors in ``run.py`` (see ``dev/supervisor/DEDUP_DESIGN.md`` + 
``dev/supervisor/EXECUTOR_MANIFEST.md``):

- :func:`fork_workers` — splice / C-plugin / C-spawn / Python fork dispatch
  (one branch per worker kind; the only per-kind code in the tree).
- :func:`collect_records` — drain-vs-direct + order-index-vs-none collection.
- :func:`report_poison` — engine poison summary + ``strict_poison`` mapping.
- :func:`teardown_union` — union-fd-set teardown covering both plain
  (``_teardown_stream`` shape) and reactor (``_teardown_reactor`` shape)
  callers; supervision-specific pid sets arrive as parameters so this
  function carries zero mode branches.
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
    return pids


# ---------------------------------------------------------------------------
# Single collection (I7 EOF verification at the callers' join)
# ---------------------------------------------------------------------------

def collect_records(*, use_drain=None, results_fd, out_fds, order=None,
                      spec=None):
    """Parse collected output memfds into ordered blobs. Single site.

    Branches: drain-vs-direct (1), order-index-vs-none (1). Byte-identical
    to the ten inline copies it replaces (drain reads ``results_fd``;
    direct reads each of ``out_fds``; ``order == "index"`` sorts).

    W-REL6-5: ``use_drain``/``order`` default from ``spec``
    (``use_drain = spec.c_drain and spec.collect``).
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

    if use_drain:
        records = (_run_mod._parse_records(
            _run_mod._read_fd_all(results_fd))
            if results_fd is not None else [])
    else:
        records = []
        for fd in out_fds:
            records.extend(_run_mod._parse_records(
                _run_mod._read_fd_all(fd)))
    if order == "index":
        records.sort(key=lambda kv: kv[0])
    return [blob for _, blob in records]


# ---------------------------------------------------------------------------
# Single poison summary (I6 rollback lives in emit paths; this is reporting)
# ---------------------------------------------------------------------------

def report_poison(lib, *, strict_poison=False):
    """Emit the engine poison WARN + map strict_poison → raise. Single site."""
    import sys as _sys
    _run_mod = _sys.modules["forkrun.run"]

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


# ---------------------------------------------------------------------------
# Union teardown (I3 + I8, zero mode branches)
# ---------------------------------------------------------------------------

def teardown_union(lib, *, supervision=None, state=None,
                    pids=(), extra_pids=(), orderer_pid=None,
                    drain_pid=None, results_fd=None,
                    signal_r=None, signal_w=None, spare_signal_w=None,
                    out_fds=(), out_hold=None, memfd=None, mem_hold=None,
                    src_fd=None, must_close=False,
                    order_r=None, order_w=None, trap_r=None, trap_w=None,
                    coll_fd=None, coll_hold=None, fallow_w=None,
                    scan_pid=None, spec=None):
    """Kill strays + close union fd set + destroy. Single implementation.

    ``supervision == "reactor"`` routes to ``_teardown_reactor`` (which
    additionally reaps ``state.workers``, parked spawn/fallow spares, and
    the scanner death pipe); otherwise routes to ``_teardown_stream``.
    Callers pass already-assembled pid/fd sets — this function adds no
    per-mode branches beyond the one supervision selection.

    W-REL6-5: ``supervision`` defaults from ``spec`` (explicit wins).
    """
    if supervision is None:
        supervision = spec.supervision if spec is not None else "plain"
    import sys as _sys
    _run_mod = _sys.modules["forkrun.run"]

    if supervision == "reactor":
        _run_mod._teardown_reactor(
            lib, state, signal_r=signal_r, out_fds=out_fds,
            out_hold=out_hold, memfd=memfd, mem_hold=mem_hold,
            src_fd=src_fd, must_close=must_close,
            extra_pids=tuple(extra_pids)
            + ((scan_pid,) if scan_pid is not None else ()),
            orderer_pid=orderer_pid, order_r=order_r, order_w=order_w,
            trap_r=trap_r, trap_w=trap_w, coll_fd=coll_fd,
            coll_hold=coll_hold, drain_pid=drain_pid,
            results_fd=results_fd, spare_signal_w=spare_signal_w)
        return
    _run_mod._teardown_stream(
        lib, list(pids), signal_r, list(out_fds),
        out_hold if out_hold is not None else [],
        memfd, src_fd, must_close,
        extra_pids=tuple(extra_pids)
        + ((scan_pid,) if scan_pid is not None else ()),
        fallow_w=fallow_w, drain_pid=drain_pid,
        results_fd=results_fd)


__all__ = ["ExecutorSpec", "fork_workers", "collect_records",
           "report_poison", "init_engine", "teardown_union"]
