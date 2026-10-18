"""forkrun.run / map / stream — the Python frontend entry points.

WHAT THIS MODULE IS
-------------------
Dispatch, supervision and result collection for four public entry points
(`run`, `map`, `stream`, `sweep`) over five payload modes
(`_api._VALID_MODES`: python, spawn, plugin, splice, udf).

This docstring previously described the "v0.5 pipeline" — a single-node,
UMA, fully-materializing shape with `mode="python"` only. Every one of
those limits has since been lifted, and the text was left asserting them
next to code that contradicted it line by line. It is rewritten here to
describe the shape that exists; the historical v0.5 pipeline is recorded
in dev/supervisor/MOVER_REPORT.md rather than in the module header.

EXECUTOR FAMILIES
-----------------
Dispatch selects a supervision model and an ingest shape. They are
deliberately NOT one flag-driven executor (see DECISION-03): the plain
waitpid path and the reactor path have different failure-detection,
recovery and teardown contracts, and merging them would trade a real
invariant for line count.

  Materialized ingest        Streaming ingest
  ------------------------    ------------------------
  _execute_locked            _execute_ingest_locked        (plain)
  _execute_reactor_locked    _execute_ingest_reactor_locked(reactor)
  _execute_numa_locked       _execute_numa_stream
  _execute_cleanroom         _execute_cleanroom_stream     (cleanroom)
  _execute_streaming         _execute_ingest_stream
                              _execute_streaming_reactor

  orchestrator=None / True -> the reactor is the DEFAULT (W-REL1/R1)
  orchestrator=False       -> plain waitpid path
  nodes>1                  -> NUMA pipeline
  eligible + FORKRUN_CLEANROOM -> cleanroom launcher (exec'd, no Python
                             address space inherited by workers)

INVARIANTS THIS MODULE OWNS
---------------------------
* No Python pipe/queue carries payload bytes, ever. No pickle.
* Workers claim exactly one ring slot (INVARIANTS.md 1-4).
* Escrow deposit and batch recovery are PARENT-side
  (RESILIENCE_PROTOCOL.md 2, W-PY28/W-PY29). A worker's exit path is
  cleanup only; depositing there would double-count.
* Descriptor hygiene: every forked child scrubs to the engine + job fds
  (`_fd_scrub.scrub_fds`); fd 2 is never redirected or closed.
* Batching: `workers` is normalized so multi-node topologies cover every
  node (INVARIANTS.md 18).
* `FORKRUN_RETRY_LIMIT` is read through `_api._resolve_retry_limit()`
  and never hardcoded at a worker-init site.

WHAT IS STILL TRUE OF THE OLD TEXT
----------------------------------
"map() is batch-granular: one result per batch" and "run() with a
callable sink runs the sink payload-side in the worker" both remain
accurate. The emitter transports keyed records and does not order them;
ordering is a separate concern (`order="none"` default vs
`order="index"`).
"""
from __future__ import annotations

import os
import struct
import mmap as _mmap_mod
import ctypes
import fcntl
import functools
import inspect
import weakref
from collections import deque as _deque
import sys

from ._api import Mode, Nodes, OnError, Order, _validate
from ._bindings import RC_OK, get, load
from ._fd_scrub import scrub_fds, snapshot_fds
from ._pipes import make_pipe
from ._plugin import make_plugin_payload
from ._reassembly import ReassemblyBuffer
from ._executor_core import ExecutorSpec
from ._executor_core import collect_records, init_engine as _core_init_engine
from ._executor_core import flush_stdio as _flush_stdio
from ._resume import (ORDERER_REAP_TIMEOUT, WORKER_REAP_TIMEOUT,
                       _waitpid_bounded, checkpoint_on_abort,
                       consume_sidecar, require_resume_path,
                       resume_begin)
from ._signals import guard as _signal_guard
from ._spawn import make_spawn_payload
from ._udf import (roots_spec as _udf_roots_spec,
                   udf_payload as _make_udf_payload)
from ._udf import helper_path as _udf_helper_path
from ._worker import _HDR, _c_plugin_spec, _c_spawn_spec, \
    _fork_c_plugin_worker, _fork_c_spawn_worker, resolve_payload_parent, \
    worker_main
from .exceptions import (ForkrunInterrupted, ForkrunPoisonSkip,
                           ForkrunProtocolError, ForkrunWorkerFailure)

import fcntl as _fcntl
import time as _time
from typing import Any, Callable, Iterator, List, Optional

# W-PY18: default byte-batch for mode="splice" (bash -b default).
_SPLICE_DEFAULT_BYTES = 512 * 1024

# DECISION-02 terminal dispositions (must match FR_DISP_* in _shim.c).
_DISP_DATA = 0
_DISP_NO_RESULT = 1

# D-PORT3: parent-side SIGINT translation (Bash exit 130). Every
# `except KeyboardInterrupt` site below aborts first, then raises
# ForkrunInterrupted chained from the original — which IS a
# KeyboardInterrupt, so W-PY22 abort→checkpoint→resume callers
# (assertRaises(KeyboardInterrupt)) keep working unchanged.
_INTERRUPTED_MSG = (
    "forkrun: interrupted by SIGINT in the parent (Bash exit 130); "
    "abort issued, partial work discarded — resume from the "
    "checkpoint when checkpoint_file= was armed")

# W-PY16 worker fork timing: the scanner's pre-flight BAILS when a
# worker is already waiting (active_waiters > 0 → CASE B → phase 1),
# and entering phase 1 with already-complete input publishes nothing
# (silent loss). So workers fork only after pre-flight is provably
# over — i.e. after the first DATA publish — except:
# - fork path: the parent forks workers as soon as its own setup is done,
#   with no artificial delay. `ready > 0` still short-circuits, so when the
#   pre-flight finished on its own during setup the fork is immediate and
#   nothing waits. STALL_FORK_AFTER is only the fallback for "setup done
#   and the scan has not finished", and it defaults to 0.
# - gate path: source exhausted with no publish yet -> wait for publish
#   (CASE A completes it); fork on publish, skip on empty input,
#   RuntimeError on the reaped-with-data-but-nothing-published anomaly.
#
# Why 0 and not the 2.0 this used to be. The pre-flight is a race the
# scanner should win or lose on merit, not a reason to hold workers back.
# CASE B (a worker arrives, scan cut short) resumes the geometric ramp from
# sim_L, and that ramp doubles, so it converges on a sane batch size without
# help -- delaying the fork buys the ramp nothing. The scanner is already
# forked before the ingest loop, so the scan gets the NATURAL latency of
# the parent's remaining setup; a timer only adds latency on top of that.
#
# Measured, light/medium/heavy 5M file plus a 2816-line input, median of 3-5:
#
#   STALL_FORK_AFTER   light    medium   heavy    small input
#   2.0                0.4081s  1.4793s  4.7188s  0.1079s
#   0.05               --       --       --       0.1073s
#   0.0                0.3952s  1.4771s  4.7085s  0.0257s   <-- default
#
# Equal or better everywhere, and 4x on a small input where a fixed wait
# dominates the whole run. CASE B is also the bash-normal path (see the
# parity note above), so 0 moves Python toward bash rather than away.
#
# FR_STALL_FORK_AFTER stays as a knob; 2.0 remains reachable.
STALL_FORK_AFTER = float(os.environ.get("FR_STALL_FORK_AFTER", "0.0"))
# Post-stall-fork gate grace: after a stall-triggered fork, withhold
# the EOF gate until first publish or this long, so the gate can never
# land before phase-1 entry (entry follows the bail within ms).
POST_FORK_GATE_GRACE = 2.0

# W-PYFORKGATE: NUMA fork-gate readiness cadence. The gate waits for the
# first DATA publish before forking workers (see STALL_FORK_AFTER above).
# Readiness is polled on a short doubling ramp from _GATE_POLL_MIN_S up to
# _GATE_POLL_MAX_S so normal startup tracks publish latency rather than a
# fixed sleep quantum; every _GATE_SUPERVISE_EVERY rounds the loop takes
# the full _GATE_WAIT_FULL_S cadence instead, which keeps the supervision
# sweep (helper deaths + reactor_poll_once's O(N) waitpid sweep) at exactly
# the pre-change rate. On a genuine stall the ramp saturates and the
# supervise tick restores the original flat 50ms loop, so the stall
# fallback and its timings are bit-for-bit unchanged.
_GATE_POLL_MIN_S = 0.0005
_GATE_POLL_MAX_S = 0.004
_GATE_WAIT_FULL_S = 0.05
_GATE_SUPERVISE_EVERY = 10
# Backlog floor: a node forks once it has published this many DATA batches
# per worker it needs (_GATE_MIN_BATCHES is the floor-of-one for small
# inputs, where any publish is enough). See the gate loop for why
# first-publish gating stampedes at high worker counts.
_GATE_BATCHES_PER_WORKER = 4
_GATE_MIN_BATCHES = 4

_CHUNK = 1 << 20

# W-PYZEROCOPY: return result records as memoryview slices over the
# collection mapping instead of bytes objects.
#
# This is the same move bash makes, not a workaround for a slow path.
# bash's orderer never parses results at all: it hands the consumer a
# coordinate (fd, offset, len) and the kernel moves bytes only if the
# consumer actually reads them (forkrun_ring.c:7520 ->
# forkrun_emit_with_fallback -> robust_sendfile). A memoryview over the
# mapped collection file is the in-process equivalent -- a reference,
# not a copy. Producing bytes instead forces a memcpy of the entire
# result stream on the parent's single thread, which was measured as
# the floor of the whole ordered path:
#
#   pread + bytes()   0.0813 s  (4.6 GB/s)   <- before
#   mmap  + bytes()   0.0346 s  (10.9 GB/s)
#   mmap  + memoryview 0.0017 s (217 GB/s)   <- 48x, the copy disappears
#
# A memoryview is a buffer, not a sequence. len(), slicing, iteration,
# .tobytes(), .hex(), comparison against bytes, and write() to a file
# object all work unchanged; .split(), .decode(), .startswith() and
# `x in blob` do NOT, and isinstance(blob, bytes) is False. That is why
# output="bytes" exists as the escape hatch, and why forkrun.materialize()
# is exported for converting one record at a time.

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


def _resolve_output(output) -> bool:
    """output="view"|"bytes" -> whether records are returned zero-copy.

    W-PYZEROCOPY. "view" (default) hands back memoryview slices over a
    read-only mapping of the result stream -- the in-process equivalent
    of what bash's orderer does, passing the consumer a coordinate
    (fd, offset, len) and letting the kernel move bytes only if the
    consumer reads them (forkrun_ring.c:7520). "bytes" copies every
    record, costing one extra memcpy per record on the parent's single
    thread; measured 1.5-2.6x slower end to end.

    A string rather than a boolean so the representation can grow
    without another API break. One name across run/map/stream.
    """
    if output is None:
        return True
    if output == "view":
        return True
    if output == "bytes":
        return False
    raise ValueError(
        "output must be 'view' or 'bytes' (got %r). 'view' returns "
        "memoryview records that avoid a per-record copy; 'bytes' "
        "returns bytes objects. Use forkrun.materialize() to convert "
        "individually if you need one or the other." % (output,))


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
        # W-REL5-E7: no tempfile fallback (os.memfd_create exists on
        # all supported Pythons, floor 3.10 — the AttributeError arm
        # could never fire).
        results_fd = os.memfd_create("forkrun_results")
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


def _validate_orchestrator(orchestrator):
    """Validate the W-PY19 orchestrator flag (None/True/False only)."""
    if orchestrator is None or isinstance(orchestrator, bool):
        return orchestrator
    raise TypeError(
        "orchestrator must be None, True, or False, got %r"
        % (orchestrator,))


# W-REL5-B1: the shared kwargs whitelist for the **kwargs frontends
# (map/stream/sweep). run() already rejects unknown keywords by
# construction (explicit keyword-only signature); these three read
# kwargs.get(...) with no whitelist, so a typo (wokers=) silently
# ran a different pipeline. sink= is NOT in the set: only run()
# owns a worker-side sink; the collecting frontends reject it with
# a dedicated ValueError (same wording as sweep's pre-existing
# gate) before this whitelist runs.
_MAP_STREAM_KWARGS = frozenset((
    "mode", "nodes", "order", "lines", "bytes", "workers",
    "on_error", "streaming", "orchestrator", "c_drain", "resume",
    "output",
    "checkpoint_file", "strict_poison", "signal_policy",
    "c_worker_loop", "c_spawn_loop",
))


def _reject_unknown_kwargs(who, kwargs, allowed=_MAP_STREAM_KWARGS):
    """Fail-closed unknown-keyword rejection (W-REL5-B1).

    who names the frontend for the message (e.g. "map()").
    Raises TypeError (Python's own unexpected-keyword error type)
    naming every unknown key plus the allowed set — never silently
    runs.
    """
    unknown = sorted(k for k in kwargs if k not in allowed)
    if unknown:
        raise TypeError(
            "%s got unexpected keyword argument(s): %s "
            "(allowed: %s)" % (
                who, ", ".join(repr(k) for k in unknown),
                ", ".join(sorted(allowed))))


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


def _cleanroom_route_for(entry, raw_mode):
    """The route identifier a public call would select, or None.

    `entry` is "map" or "stream"; `raw_mode` is the mode as the CALLER
    wrote it, before _coerce_payload rewrites plugin->python.
    """
    if raw_mode not in ("plugin", "udf", "spawn"):
        return None
    route = "%s-%s" % (entry, raw_mode)
    # Only SERVED routes get an identifier. stream(spawn) has no dispatch,
    # so "stream-spawn" must not be a name a user could select -- it
    # would be a selector that appears valid and can never fire, which is
    # worse than no selector at all. Deriving the check from the served
    # set also means the two cannot drift apart.
    return route if route in _CLEANROOM_ROUTES else None


# WO-CR-ROI-2 Phase C: per-route activation.
#
# FORKRUN_CLEANROOM was effectively boolean -- any non-false value
# enabled EVERY eligible route at once, coupling five envelopes whose
# dispatch and streaming behaviour differ and whose levels of proof
# differ. A mode-based selector would not fix it: "plugin" would still
# enable both map(plugin) and stream(plugin). So the identifier is the
# DISPATCH ROUTE, resolved from the raw public mode plus the entry point
# BEFORE payload coercion hides either.
#
# An unknown value is an ERROR, not a silent "enable everything" --
# that failure mode is the one a strict parser exists to prevent.
_CLEANROOM_FALSE_VALUES = ("", "0", "no", "off", "false")

_CLEANROOM_ROUTES = ("map-plugin", "map-udf", "map-spawn",
                     "stream-plugin", "stream-udf")

# Phase D default. Deliberately a single route.
_DEFAULT_ROUTES = frozenset(("map-plugin",))


def _cleanroom_selected_routes():
    """Parse FORKRUN_CLEANROOM into (enabled, routes, explicit).

    Returns (enabled, routes_or_None, explicit):
      enabled  -- may this run use the cleanroom at all?
      routes   -- None means "every eligible route" (legacy behaviour);
                  a frozenset means "only these";
      explicit -- did the user set the variable at all?

    Raises ValueError on an unknown selector, so a typo cannot silently
    widen what is enabled.
    """
    v = os.environ.get("FORKRUN_CLEANROOM")
    if v is None:
        # WO-CR-ROI-2 Phase D: the default moved. map(plugin) is now ON
        # by default; everything else stays opt-IN.
        #
        # This is the smallest default that the evidence supports. It is
        # one route, not "the cleanroom", and the per-route selector is
        # what makes it expressible -- before Phase C a default could only
        # be all-or-nothing across five envelopes.
        #
        # Evidence, all four of the decision document's blockers closed:
        #   * route proof  -- python/tests/test_cleanroom_routes.py execs
        #     the REAL launcher for map(plugin) and compares bytes to an
        #     in-process reference; mutation-proven (forcing the launcher
        #     to "missing" turns it red).
        #   * per-route gate -- Phase C, 6109dd93.
        #   * packaging -- _forkrun_cleanroom ships inside the manylinux
        #     wheel (verified in dist/), so a default is not a no-op for
        #     installed users.
        #   * performance -- python/benchmarks/
        #     bench_cleanroom_default_on.py, re-measured on this host
        #     with the in-repo plugin: startup 1.77x, startup+512MB
        #     ballast 2.34x, throughput 1.16x, in-process/cleanroom.
        #     No regime regresses, including the throughput regime where
        #     the advantage is smallest.
        #
        # If the launcher is missing or exec fails, the caller falls
        # back in-process, so a broken install degrades to the OLD
        # behaviour rather than to a failure.
        return True, _DEFAULT_ROUTES, False
    val = v.strip().lower()
    if val in _CLEANROOM_FALSE_VALUES:
        return False, None, True
    if val in ("1", "yes", "on", "true", "all", "*"):
        # Legacy: every route the envelope accepts. Preserved exactly.
        return True, None, True
    parts = [p.strip() for p in val.split(",") if p.strip()]
    if not parts:
        raise ValueError(
            "FORKRUN_CLEANROOM=%r selects no route. Use one of %s, a "
            "comma-separated subset, or 1 for every eligible route."
            % (v, ", ".join(_CLEANROOM_ROUTES)))
    unknown = [p for p in parts if p not in _CLEANROOM_ROUTES]
    if unknown:
        raise ValueError(
            "FORKRUN_CLEANROOM=%r contains unknown route(s) %s. Valid "
            "routes: %s. (Use 1 for the legacy all-routes behaviour.)"
            % (v, ", ".join(repr(u) for u in unknown),
               ", ".join(_CLEANROOM_ROUTES)))
    return True, frozenset(parts), True


def _cleanroom_enabled():
    """Is the exec-based cleanroom launcher requested at all?

    The WHOLE-ENVIRONMENT gate. Whether a given call may use it depends
    additionally on _cleanroom_route_enabled(), so this being true does
    NOT enable every envelope -- that separation is the point of the
    per-route selector.

    Current semantics (WO-CR-ROI-2, see
    dev/supervisor/CLEANROOM_DEFAULT_ON_DECISION.md for the evidence):

        unset                map(plugin) only  [default]
        0/no/off/false/""    nothing
        1/yes/on/true/all    every SERVED route [legacy]
        map-plugin[,...]     the named subset
        unknown              ValueError

    Two properties that are easy to get wrong:

    * An OFF value is the supported way to restore pre-Phase-D
      behaviour, since the default is now on for map(plugin). It is
      checked before route parsing, so the selector cannot shadow it.
    * "all" means all SERVED routes. stream(spawn) has no dispatch, so
      it is neither selectable nor enabled by any value.

    The measured performance history (parent-RSS scaling in both THP
    regimes, and the batch-count-variance note explaining why blob counts
    are not record counts) lives in
    dev/supervisor/CLEANROOM_ROUTE_INVENTORY.md and
    dev/supervisor/CLEANROOM_DEFAULT_ON_DECISION.md. It is deliberately
    NOT duplicated here: this docstring sat next to the gate for a long
    time asserting "OFF by default" after the default moved, which is
    exactly the failure mode comments are supposed to prevent.
    """
    enabled, _routes, _explicit = _cleanroom_selected_routes()
    return enabled


def _cleanroom_route_enabled(entry, raw_mode):
    """May THIS dispatch route use the launcher?

    A route selector narrows; it never widens. If the environment named
    specific routes, this route must be one of them. With the legacy
    unset-route selector every eligible route remains eligible.
    """
    _enabled, routes, _explicit = _cleanroom_selected_routes()
    if not _enabled:
        return False
    route = _cleanroom_route_for(entry, raw_mode)
    # The route must EXIST before either branch is consulted. Legacy "=1"
    # used to return True unconditionally, which reported stream(spawn) as
    # "enabled" even though it has no dispatch -- the selector said yes to
    # a route the product cannot serve. Harmless today only because the
    # stream predicate separately declines spawn, so the envelope still
    # refused it; that made correctness depend on two unrelated checks
    # agreeing. One check is enough.
    if route is None:
        return False
    if routes is None:
        return True                      # legacy: every SERVED route
    return route in routes


def _cleanroom_explicit():
    """Did the user actually ask for the cleanroom?

    Distinguishes "requested" from "not set". Both decline-warning sites
    are gated on this, and the default is now ON for map(plugin), so the
    distinction carries more weight than it did: UNSET-ON is not the same
    as ASKED-ON. A caller who never set the variable should not be warned
    that their call quietly used the in-process path -- they did not ask
    for anything. A caller who did set it, and whose call the envelope
    declines, must be warned, or they will believe they got a cleanroom
    they did not get.
    """
    v = os.environ.get("FORKRUN_CLEANROOM")
    if v is None:
        return False
    return v.strip().lower() not in ("", "0", "no", "off", "false")


def _warn_cleanroom_multinode(num_nodes):
    """Multi-node routes AROUND the cleanroom envelope entirely.

    Every `if num_nodes > 1:` branch RETURNS before
    _cleanroom_eligible is consulted, so an explicit
    FORKRUN_CLEANROOM used to be dropped here in silence. That
    contradicted the envelope's own rule ("a user who set
    FORKRUN_CLEANROOM must learn they did not get it") and read as the
    cleanroom quietly ignoring them.

    Multi-node is also the launcher's largest remaining gap -- it builds
    one ring in one process and has no node-bound worker placement -- so
    the message says so plainly rather than implying a transient miss.
    It must be called from each branch: the envelope check cannot cover
    these, because it is never reached.
    """
    if not (_cleanroom_enabled() and _cleanroom_explicit()):
        return
    import warnings as _warnings
    _warnings.warn(
        "forkrun: FORKRUN_CLEANROOM ignored -- multi-node (nodes=%r) "
        "runs the dedicated NUMA pipeline. The launcher serves UMA "
        "single-node only." % (num_nodes,),
        UserWarning, stacklevel=3)


# --------------------------------------------------------------------------
# Route-owned descriptor discipline (F6 Stage 3)
# --------------------------------------------------------------------------
class _RouteFdSet:
    """Descriptors a cleanroom route created, with single-owner release.

    WHY THIS EXISTS. Every descriptor a route allocates must be closed on
    EVERY exit -- including an exception raised during descriptor setup,
    argv construction, the spawn itself, waitpid, the stats or trace read,
    failure classification, or result collection. Adding a close statement
    per exit leaves the next exceptional exit uncovered, which is exactly
    how `errfd` and the streaming `stats_fd` came to leak on every call.

    THREE RULES, because the alternative is double-closing a recycled
    descriptor number:
      * `add`    -- the route just created this fd and owns it;
      * `close`  -- release it now (the common case, kept explicit so the
                    ordering constraint is visible at the call site);
      * `release`-- ownership is being TRANSFERRED elsewhere, so this set
                    must never close it. `_cleanroom_collect` owns
                    `res_fd` and closes it itself; without `release` the
                    cleanup would race it.
    """

    __slots__ = ("_owned", "_done")

    def __init__(self):
        self._owned = {}
        self._done = set()

    def add(self, name, fd):
        """Register a freshly created descriptor."""
        if fd is not None and fd >= 0:
            self._owned[name] = fd
        return fd

    def close(self, name):
        """Close one descriptor now, if still owned. Idempotent."""
        if name in self._done:
            return
        fd = self._owned.pop(name, None)
        if fd is None:
            return
        self._done.add(name)
        try:
            os.close(fd)
        except OSError:
            pass

    def release(self, name):
        """Give up ownership WITHOUT closing (transferred elsewhere)."""
        self._owned.pop(name, None)
        self._done.add(name)

    def close_all(self):
        """Close everything still owned. Never raises."""
        for name in list(self._owned):
            self.close(name)


def _fd_above_stdio(fd):
    """Return a descriptor number guaranteed to be > 2 for the same open
    file, or `fd` unchanged if it already is.

    WHY (F6 Stage 3 / C5). The materialized route ends with
    `os.dup2(errfd, 2)`. If the host process started with fd 2 CLOSED,
    the kernel hands the route's FIRST allocation the number 2 -- so
    `src_fd` can land on fd 2 and be silently overwritten by that dup2.
    The launcher is then told `--src 2` and reads the ERROR MEMFD as its
    input: a well-formed result computed from the wrong bytes, with no
    error, no warning and no non-zero exit.

    Relocating the route's own descriptor above 2 is the narrow fix. It
    deliberately does NOT reopen the caller's fd 0/1/2 in the parent (that
    would change process state the caller owns), does NOT enumerate
    /proc/self/fd, and does NOT touch any descriptor the caller supplied:
    every caller-supplied source is `os.dup()`ed by
    `_cleanroom_source_fd()` first, so what arrives here is always a
    route-owned copy and the original stays the caller's.

    F6 Stage 4 -- WHY fcntl(F_DUPFD) AND NOT os.dup().
    The Stage 3 version used `os.dup()`, which returns the LOWEST FREE
    descriptor. That is not a relocation at all when the gap is partly
    occupied: relocating a descriptor on fd 1 with fd 0 busy and fd 2 free
    returns fd 2, and with fds 1 and 2 busy returns fd 0. Reproduced
    deterministically before this fix:

        close fd 0 and fd 2, put the source on fd 1
        -> _fd_above_stdio(1) returned 0

    The Stage 3 low-FD matrix missed this because it closed ALL THREE of
    fd 0/1/2, which leaves the gap empty and makes the lowest free
    descriptor happen to be 3. C5 was therefore only closed for the one
    occupancy pattern the test happened to construct.

    `fcntl(fd, F_DUPFD, 3)` makes "> 2" a guarantee: the kernel picks the
    lowest descriptor at or above the given minimum, so the result cannot
    land back in the gap no matter what else is open.
    """
    if fd is None or fd > 2:
        return fd
    try:
        higher = fcntl.fcntl(fd, fcntl.F_DUPFD, 3)
    except OSError:
        return fd
    try:
        # F_DUPFD clears FD_CLOEXEC on the new number, so the inheritable
        # state the route set on the ORIGINAL must be re-applied here or
        # the relocated descriptor would silently stop crossing exec.
        inheritable = os.get_inheritable(fd)
        os.set_inheritable(higher, inheritable)
    except OSError:
        pass
    os.close(fd)
    return higher


def _route_fd_cleanup(fn):
    """Run a launch function with automatic cleanup of registered fds.

    A decorator rather than an inline `try/finally` because both route
    functions are long (250+ and 240+ lines) and re-indenting them to add
    a `finally` would be exactly the wholesale restructure this change is
    meant to avoid -- and would put the cleanup boundary nowhere near the
    allocations it protects.

    Generator-aware: `_execute_cleanroom_stream` is a generator, so its
    body is lazy and a plain wrapper would run the cleanup BEFORE the body
    ever executed. The generator form defers cleanup to generator exit,
    which is also what makes abandonment clean up.
    """
    if inspect.isgeneratorfunction(fn):
        @functools.wraps(fn)
        def gen_wrapper(*args, _own=None, **kwargs):
            own = _own if _own is not None else _RouteFdSet()
            try:
                for item in fn(*args, _own=own, **kwargs):
                    yield item
            finally:
                own.close_all()
        return gen_wrapper

    @functools.wraps(fn)
    def wrapper(*args, _own=None, **kwargs):
        own = _own if _own is not None else _RouteFdSet()
        try:
            return fn(*args, _own=own, **kwargs)
        finally:
            own.close_all()
    return wrapper


def _cleanroom_launcher_path():
    """W-CR1: locate the launcher shipped beside the substrate .so."""
    from ._bindings import find_substrate
    so = find_substrate()
    cand = os.path.join(os.path.dirname(os.path.abspath(so)),
                        "_forkrun_cleanroom")
    return cand if os.path.exists(cand) else None


def _validate_spawn_argv(spawn_argv):
    """Reject a command vector the launcher could not honour faithfully.

    Runs before the launcher starts and before any source byte is read,
    so an invalid command costs no input. Mirrors the launcher's own
    descriptor validation, but the NUL rule lives only here -- C cannot
    see an embedded NUL at all.
    """
    if not spawn_argv:
        raise ValueError("spawn command vector is empty")
    for i, el in enumerate(spawn_argv):
        if not isinstance(el, str):
            raise TypeError("spawn argv[%d] is %s, not str"
                            % (i, type(el).__name__))
        if "\0" in el:
            raise ValueError(
                "spawn argv[%d] contains NUL, which cannot be represented "
                "in a POSIX argument; it would be silently truncated"
                % i)
    return list(spawn_argv)


def _cleanroom_eligible(source, raw_mode, num_nodes, order, strict_poison,
                        orchestrator, return_stats=False, *, streaming=False,
                        resume=None, checkpoint_file=None):
    # orchestrator=True is REQUIRED, not merely accepted.
    #
    # orchestrator is not a performance knob; it selects a supervision
    # MODEL. False means legacy fork-and-wait / fail-fast: a batch whose
    # worker died is lost and the run fails. True means reactor
    # supervision with recovery by wid.
    #
    # The launcher supervises unconditionally (W-CR4), so it can serve
    # the second but NOT the first. Accepting orchestrator=False and
    # quietly supervising anyway means a caller who explicitly asked for
    # fail-fast gets recovery instead -- a worker death that should have
    # failed the run gets repaired, and the caller cannot tell. Slower is
    # acceptable; quietly different is not.
    #
    # The alternative -- teaching the launcher both models -- is a
    # protocol change for a mode whose only remaining users are the ones
    # deliberately asking for the legacy behaviour. They keep the
    # in-process path, which honours it exactly.
    """W-CR1: can the launcher serve this call FAITHFULLY?

    Returns (ok, reason). Every condition here is one where saying yes
    would change RESULTS, not merely speed. An opt-in acceleration that
    honours less than it claims is worse than no acceleration, because
    the caller has no way to tell.

    * materialized file source -- the launcher spills from a descriptor;
      there is no streaming-ingest or producer-side spill.
    * mode="plugin" -- it dlopens an object and calls an entry point.
      Note this is NOT the frozen-ABI restriction of the C *worker
      loop*. It IS, however, narrower in one respect: the plugin must
      export forkrun_use_ctx (dialect v1/v2). A plugin without it is
      driven by the engine via the legacy ARGV/stdout route, whose
      output lands on the worker's stdout rather than in the memfd the
      launcher collects -- so the launcher would exit 0 with an EMPTY
      result set. It now refuses such plugins (exit 78) so run.py falls
      back, rather than returning silently wrong results. An earlier
      draft of this comment claimed v0 plugins were served "fine too";
      nine existing plugin tests disproved that.
    * UMA single node -- no multi-node rings.
    * order in ("none", "index") -- the launcher does NOT run the C
      orderer (ring_order is forked only by the in-process reactor, for
      memory reasons), but it does not need to. The ordering is applied
      downstream by shared code: map/collect sorts by index in
      collect_records, and stream() reassembles parent-side from the
      batch_idx already present in the batch framing. Both consume the
      launcher's framing unchanged, so order="index" is served
      correctly without an orderer in the launcher.
    * strict_poison and return_stats -- served via a counter channel:
      the launcher writes [version][poisoned] to a memfd after joining
      every worker. It works because g_state (holding poisoned_count) is
      SHARED memory, so a worker's atomic poison increment is visible in
      the parent. Previously both were declined because there was no
      channel back, and return_stats was a live P0 bug: completed=len(out)
      with poisoned hardwired to 0 reported total=90 for a run of 100
      batches with 10 poisoned.
    * orchestrator=True ONLY -- was False-only, and that
      gate was the load-bearing one. The launcher used to run a plain C
      pipeline (fallow/workers/scanner/drain) with no death pipes, no
      respawn and no trap-ACK, so a dead worker's batch was silently
      lost. W-CR4 added the supervisor: waitpid over all children,
      ring_recover_worker by wid, respawn on the same wid, and abort on
      rc 4/5. That is the same recovery the reactor performs, so the
      cleanroom can serve orchestrator=True. Note the launcher always
      supervises -- there is no flag and no non-supervised mode.
    """
    if num_nodes != 1:
        return False, "UMA single-node only (got nodes=%r)" % (num_nodes,)
    # mode="udf" is served wherever mode="plugin" is: same launcher, same
    # envelope, same supervision. It differs only in WHICH loop the
    # launcher selects (fr_py_worker_udf_loop) and that an interpreter is
    # initialised pre-fork. P1-3.
    # Stage 3: spawn is served for materialized sources too, alongside
    # plugin and udf. Its worker loop takes an argv VECTOR, not the
    # plugin's two strings, so the launcher routes it through a
    # mode-specific descriptor rather than the plugin callback -- same
    # arity, incompatible types, and a cast would be undefined behaviour.
    #
    # Served only once the lifecycle gates held:
    #   - a killed worker's command descendants die with its process
    #     group (in-group cleanup);
    #   - a descendant that calls setsid() is explicitly OUTSIDE that
    #     guarantee, and that boundary is pinned by a test;
    #   - the supervisor observes the death and respawns;
    #   - teardown kills the group;
    #   - a command failure is handled by the on_error policy with an
    #     explicit SKIPPED record, not escalated to an infrastructure
    #     abort.
    # All six are in test_stage3_lifecycle.py.
    if raw_mode not in ("plugin", "udf", "spawn"):
        return False, ("mode='plugin', 'udf' or 'spawn' only "
                       "(got %r)" % (raw_mode,))
    # DECISION-03: orchestrator=False is now SERVED, via the launcher's
    # fail-fast supervision policy (--supervise fail-fast).
    #
    # It was declined because "the launcher supervises unconditionally and
    # would recover a dead worker's batch instead of failing the run" --
    # i.e. a caller asking for fail-fast would silently get recovery, and
    # could not tell from the result. That is fixed structurally rather than
    # by promising it will not happen: the launcher's fail-fast branch
    # RETURNS before the recovery call, so there is no flag guarding it.
    #
    # Semantics are DECISION-03 section 7.4(b): no recovery, no respawn,
    # immediate abort on the first worker death. The abandoned option 7.4(a)
    # ("no recovery but keep going") is NOT implemented and is not on the
    # roadmap; a caller wanting "don't retry a batch but finish" uses
    # orchestrator=True with FORKRUN_RETRY_LIMIT=0.
    if order not in ("none", "index"):
        return False, ("order=%r is not served; the launcher relies on "
                       "downstream ordering (collect_records sort for "
                       "map, parent-side reassembly for stream)" % (order,))
    # Streaming (stream()) is NARROWER than map() and the difference is
    # deliberate, so it is expressed here rather than as a second,
    # hand-written predicate at the stream() dispatch site. That second
    # copy had already drifted once: it required `not orchestrator` while
    # this one required it, and it excluded order="index" while this one
    # serves it -- so map and stream disagreed about the envelope.
    #
    # The streaming gap is real, not an oversight: the stream path has no
    # collect step, so it cannot sort by index after the fact, and its
    # parent-side reassembly only handles order="none". Until that is
    # built, order="index" declines to the ordinary reactor path -- which
    # is CORRECT (just not accelerated), and is why narrowing here is
    # safe: a declined call falls back, it does not silently change
    # semantics.
    # CR-FIX1-K: resume / checkpoint_file are refused for EVERY cleanroom
    # call, and the check sits here -- ABOVE the streaming block -- rather
    # than inside it.
    #
    # It used to live under `if streaming:`, which made the refusal
    # unreachable for map(). The map() dispatch site did not pass these
    # arguments either, so a call like
    #
    #     map(..., mode="plugin", order="index", orchestrator=True,
    #          resume=..., checkpoint_file=...)
    #
    # was accepted by the envelope, took the launcher, and silently
    # ignored both. Passing the arguments alone would not have fixed it:
    # the predicate would still not have executed the check. An
    # acceleration path must not accept an invocation it cannot honour,
    # so this is a refusal (with the existing observable warning), not a
    # silent ignore.
    if resume is not None or checkpoint_file is not None:
        return False, ("resume=/checkpoint_file= is not served; the "
                       "launcher neither transports nor implements "
                       "checkpoint/resume semantics")

    if streaming:
        # Stage 3: spawn is served for materialized map() only. The stream
        # path has no spawn dispatch -- it extracts a path:function spec
        # and has no place to put an argv vector -- so it DECLINES here
        # rather than falling through to a route that does not exist.
        # Admitting it would make the predicate disagree with the
        # dispatch, which is exactly the gap the review found.
        if raw_mode == "spawn":
            return False, ("stream(mode='spawn') is not served; the "
                           "streaming path has no spawn dispatch")
        if order != "none":
            return False, ("stream(order=%r) is not served; the stream "
                           "path has no collect step to sort with"
                           % (order,))
        # strict_poison IS served for stream() now. The decline said "no
        # poison count reaches a streaming caller" -- true when it was
        # written, and false since P2 (c3c321af) wired a statistics
        # memfd through the cleanroom stream launch: the launcher writes
        # the poison count, the parent consumes it AFTER a confirmed-clean
        # launcher exit, and _LAST_STATS carries it to the caller.
        #
        # The gate was simply never lifted, so the capability existed and
        # was unreachable -- the predicate and the tests disagreed. The
        # external review caught this by noting that tests existed for
        # streaming poison behaviour while the predicate still refused the
        # combination.
        #
        # Verified by forcing this gate open and running it end to end:
        # the cleanroom is entered and raises
        #   "3 poisoned batch(es) skipped in a streaming run and
        #    strict_poison=True"
        # which is the intended error, not a fallback artefact.

    # Sources: a materialized file or any already-open descriptor (int
    # fd, fifo, socket, file object). Python iterables are NOT accepted:
    # _api._reject_iterable_source refuses them ("Python is never an
    # input pump"). A forked iterable producer used to be described
    # here and in the eligibility comment below; it never ran on either
    # path and has been removed from both. What is NOT servable is a
    # source that is none of these -- notably a directory, or a path
    # that does not exist.
    if isinstance(source, (str, bytes, os.PathLike)):
        try:
            path = os.fspath(source)
        except (TypeError, ValueError) as exc:
            return False, "source path is unusable (%s)" % (exc,)
        if not os.path.exists(path):
            return False, "source is not an existing file"
        if os.path.isdir(path):
            return False, "source is a directory"
    elif isinstance(source, int) and not isinstance(source, bool):
        pass                                  # descriptor; validated later
    elif hasattr(source, "fileno") or hasattr(source, "__iter__"):
        # Structural type acceptance ONLY. This does NOT mean an iterable
        # is a supported cleanroom input:
        #   * _api._reject_iterable_source refuses Python iterables at the
        #     public API ("Python is never an input pump"), so no
        #     user-facing call reaches here with one;
        #   * an iterable reaching here at all came from an internal
        #     caller that bypassed validation. It is accepted here because
        #     the oracle (tools/capability_oracle.py) records that contract
        #     -- the caller continues to the in-process path rather than
        #     being refused -- and changing it would alter the recorded
        #     capability matrix, which is a separate decision;
        #   * there is no producer to pump one. The forked producer that
        #     used to exist here was unreachable and was removed from
        #     both cleanroom paths.
        pass
    else:
        return False, ("source must be a path, an open descriptor, or "
                       "an iterable (got %r)" % (type(source),))
    return True, ""


# ---------------------------------------------------------------------------
# CR-FIX1-D/C: the launcher outcome contract.
#
# Two things the parent used to conflate, both of which could turn a
# failure into silent data loss:
#
#   1. The wait status was reported RAW. os.waitpid() returns a 16-bit
#      status, so a launcher that exits 78 with code 78 arrives here as
#      19968 (78 << 8). "status 19968" tells a caller nothing. The
#      contract below decodes it into a class with an ACTION.
#
#   2. Every non-zero exit fell into one generic branch that returned
#      None, i.e. "fall back in-process". That is only safe when nothing
#      was consumed. The launcher spills by read()ing the caller's
#      descriptor, and for a caller-supplied fd that descriptor was
#      reached through os.dup() -- which shares the open file
#      description, and therefore the FILE OFFSET. So after ingestion the
#      fallback resumes mid-stream and returns a truncated result with
#      exit 0. That is the failure mode this contract exists to remove.
# ---------------------------------------------------------------------------

# Exit codes that the launcher is guaranteed to return BEFORE the spill
# child is forked (forkrun_cleanroom.c:411), and therefore before any
# byte of the caller's source can have been read:
#
#   64  argv validation            (:270-290)
#   69  dlopen / missing symbol    (:321, :343, :96)
#   71  fr_py_init failed          (:365-368)
#   78  plugin lacks forkrun_use_ctx (:328-338)
#
# 70 is deliberately ABSENT. It is die(), which fires both before the
# spill fork (:388) and after it (:498 fork(worker), :516 fork(scan),
# :539 fork(drain)), so it cannot be classified either way.
# 1 (supervision failure) is always post-ingestion. Any signal death is
# indeterminate. Both are unsafe.
_CR_EXIT_PRE_INGEST = frozenset((64, 69, 71, 78, 80, 81, 82))

# CR-FIX1-F: exits where falling back would REPRODUCE the hazard rather
# than route around it. 79 means the launcher's capability probe of the
# plugin never completed -- a constructor hung or crashed. The plugin's
# load is itself unsafe, so retrying in-process would dlopen it in the
# CALLER's process and reproduce the failure there, in a place with no
# launcher to bound it. 78 is deliberately NOT in this set: the probe
# completed and the plugin merely lacks the ctx protocol, which the
# in-process path handles correctly.
_CR_EXIT_NO_FALLBACK = frozenset((79,))

# 80/81 are refusals of the CLEANROOM ACCELERATOR, decided before the
# spill child is forked. They are eligible for in-process fallback and are
# deliberately absent from _CR_EXIT_NO_FALLBACK, because we CAN establish
# that declining them is safe -- which is exactly what separates them from
# 79, where the C plugin probe failed such that loading the plugin in the
# CALLER would itself be unsafe. The UDF fallback never loads the
# CPython-linked helper into the caller, so a hung UDF probe is safe to
# decline even though a hung plugin probe is not.

_CR_EXIT_LABELS = {
    64: "invalid invocation (bad arguments)",
    69: "missing launcher dependency or substrate symbol "
         "(is the substrate built and compatible with this launcher?)",
    70: "launcher internal error -- may have occurred before or after "
         "the input was consumed; treated as unsafe",
    71: "engine initialization failed (fr_py_init), OR a UDF helper could "
         "not be probed or loaded. Covers more than engine init since the "
         "UDF helper's disposable probe was added",
    78: "unsupported plugin capability (no forkrun_use_ctx dialect v1/v2)",
    79: "plugin capability probe did not complete (a constructor hung or "
         "crashed); loading this plugin is unsafe, so no fallback is "
         "attempted",
    80: "UDF helper CPython version does not match the caller's declared "
         "major.minor, or the helper's version could not be verified "
         "(no fr_udf_built_version_v2 symbol); refusing to initialise an "
         "interpreter across the mismatch",
    81: "UDF helper probe timed out (an ELF constructor did not return). "
         "The helper was NOT ACCEPTED into the launcher's execution path "
         "and was not initialised there, and no input was consumed. Note "
         "the disposable probe child did dlopen() it, so its constructors "
         "did run in that child -- this is not a sandbox",
    82: "invalid --caller-version declaration (must be MAJOR.MINOR with "
         "nothing after it). A CALLER bug, not a property of the helper -- "
         "rejected before the helper is loaded, so no ELF constructor runs",
    1: "runtime worker/helper failure",
}


def _decode_launcher_status(status):
    """Decode a waitpid() status into (exit_code, signum, label, pre_ingest).

    The fourth element is the whole point: it says whether falling back
    to the in-process path is SAFE, which is a question about how far the
    launcher got, not about how it failed.

    "Conservative" means indeterminate is treated as consumed. A refused
    fallback that turned out to have been fine costs one slow run; a
    fallback that silently returns half the input costs correctness.

    Codes in _CR_EXIT_NO_FALLBACK are reported with pre_ingest=True --
    nothing was consumed -- but callers must additionally consult
    _fallback_forbidden(code) before retrying."""
    if os.WIFSIGNALED(status):
        return (None, os.WTERMSIG(status),
                "killed by signal %d" % (os.WTERMSIG(status),), False)
    if os.WIFEXITED(status):
        code = os.WEXITSTATUS(status)
        label = _CR_EXIT_LABELS.get(code, "unknown exit code %d" % (code,))
        if code in _CR_EXIT_NO_FALLBACK:
            return (code, None, label, True)
        return (code, None, label, code in _CR_EXIT_PRE_INGEST)
    return (None, None, "unrecognised wait status %d" % (status,), False)


def _fallback_forbidden(status):
    """True when retrying in-process would recreate the original failure."""
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status) in _CR_EXIT_NO_FALLBACK
    return False


class _CleanroomPreIngestDecline(Exception):
    """The cleanroom was declined BEFORE ingestion began, so falling back
    in-process cannot duplicate committed work and cannot truncate.

    Base class for the two shapes of this. Both are raised, never
    returned as ``None``, because "the run failed" and "the accelerator
    was declined" lead to different next steps and collapsing them loses
    the distinction -- which is what made the original bare ``return
    None`` fall through into a route that could not run the payload.
    """


class _CleanroomCompatRefusal(_CleanroomPreIngestDecline):
    """The cleanroom ACCELERATOR was declined BEFORE ingestion began.

    Distinct from "the run failed". Carries:

      label     -- the launcher's exit-code label, for the message
      detail    -- the launcher's own diagnostic text
      conclusive-- True when the launcher positively established that this
                   artifact cannot serve this caller (a version mismatch or
                   an unverifiable helper), False when the outcome was
                   merely inconclusive (a probe timeout).

    Only ``conclusive`` refusals are remembered in the negative cache. A
    timeout says the helper did not answer in time, which is not evidence
    that it is incompatible -- caching that would let a transient stall
    permanently disable the accelerator.
    """

    def __init__(self, label, detail, conclusive, code=80):
        super().__init__(label)
        self.label = label
        self.detail = detail
        self.conclusive = conclusive
        self.code = code


# Launcher exits that are a compatibility refusal of the helper. 80 is
# conclusive (the mismatch or unverifiability is established); 81 is not.
_CR_COMPAT_REFUSALS = {80: True, 81: False}


def _stream_with_preingest_fallback(raw_payload, raw_mode, source, kwargs,
                                   num_nodes, orchestrator,
                                   plugin, func, udf_args, helper_fp=None):
    """stream() over the cleanroom, with an explicit pre-ingest fallback.

    LAZINESS IS THE POINT, and the first version of this broke it: it
    primed the cleanroom generator with next() to surface a pre-ingest
    refusal at the decision point, which made ``stream()`` block until the
    first record arrived. Measured: with a writer that slept 3s before its
    first record, stream() took 3.00s to RETURN instead of returning a
    generator immediately -- turning a live-draining call into a blocking
    one and defeating the contract the whole streaming surface is built
    on. An existing test did not catch it.

    So the refusal is handled INSIDE the generator body: nothing happens
    until the caller's first next(), and because a pre-ingestion code is
    decided before any record is produced, the first next() is still the
    earliest point at which the refusal can arrive. No record can have
    escaped before it, so switching mid-iteration cannot split a stream
    across two paths.
    """
    def _gen():
        cleanroom = _guarded_gen(
            _signal_guard(kwargs.get("signal_policy", "default")),
            _execute_cleanroom_stream(
                source,
                lines=kwargs.get("lines"),
                bytes_=kwargs.get("bytes"),
                workers=_resolve_workers_numa(
                    kwargs.get("workers"), num_nodes),
                plugin_path=plugin, plugin_func=func,
                on_error=kwargs.get("on_error", "retry"),
                strict_poison=bool(kwargs.get("strict_poison", False)),
                **udf_args))
        try:
            first = next(cleanroom)
        except StopIteration:
            return
        except _CleanroomPreIngestDecline as exc:
            if isinstance(exc, _CleanroomCompatRefusal):
                _record_compat_refusal(exc.code, exc.detail, helper_fp)
                _warn_compat_refusal(exc)
            new_payload, new_mode = _coerce_payload(
                raw_payload, raw_mode, force_inprocess_udf=True)
            # Only `mode` goes into kwargs: these generators take
            # `payload` POSITIONALLY, so putting it in kwargs as well is
            # a duplicate argument. (Which is exactly what happened the
            # first time.)
            inproc_kwargs = dict(kwargs, mode=new_mode)
            yield from _guarded_gen(
                _signal_guard(inproc_kwargs.get("signal_policy", "default")),
                _ingest_stream_reactor_gen(new_payload, source,
                                           **inproc_kwargs))
            return
        yield first
        yield from cleanroom
    return _gen()


def _helper_fingerprint(path):
    """Fingerprint a helper NOW, so a refusal can be keyed to this artifact.

    Captured at dispatch time -- before the launcher is exec'd -- and
    threaded into the refusal handler. A module-global slot was not
    sufficient: it was written outside _RUN_LOCK, so concurrent calls
    could overwrite each other and a refusal would be filed against
    whichever helper happened to be recorded last.
    """
    if not path:
        return None
    try:
        from ._udf import fingerprint_now
        return fingerprint_now(path)
    except Exception:
        return None


def _caller_version_argv():
    """``["--caller-version=M.m"]`` from THIS interpreter, or [].

    A declaration, not an authenticated identity -- after exec the
    launcher cannot know which interpreter started it, so it can only
    check the helper against what we declare. Taken from
    sys.version_info directly, never from the environment: a stray
    FORKRUN_* must not be able to forge the claim.
    """
    try:
        from ._udf import caller_version_arg
        return [caller_version_arg()]
    except Exception:
        return []


def _record_compat_refusal(code, detail, helper_fp=None):
    """Remember a CONCLUSIVE incompatibility against the helper artifact.

    Only 80 is cached. An 81 timeout is inconclusive and deliberately
    left uncached, so a transient stall does not permanently disable the
    accelerator.
    """
    if code != 80:
        return
    if helper_fp is None:
        return
    try:
        from ._udf import record_incompatible_for
    except Exception:
        return
    # The fingerprint is CAPTURED BEFORE the launcher starts and carried
    # in as a parameter. Re-deriving it afterwards is a TOCTOU: replace
    # the file while the launcher runs and the old helper's refusal lands
    # on the new helper's fingerprint, disabling a valid replacement.
    #
    # An earlier revision captured the PATH before launching but still
    # fingerprinted afterwards, so it fixed nothing on this path. That is
    # the bug this parameter exists to remove.
    record_incompatible_for(helper_fp, detail or
                            _CR_EXIT_LABELS.get(80, "mismatch"))


def _warn_compat_refusal(exc):
    """ONE warning per affected public invocation, deliberately not coalesced.

    ``warnings.warn`` applies the default filter ("default" == once per
    location), which would emit this once per call SITE and then stay
    silent -- the opposite of the required contract, since a permanently
    degraded cleanroom that has stopped complaining looks like a feature
    that simply chose not to run.

    Going straight to stderr is per-emission by construction and mutates
    no process-global filter, which is what the contract asks for. This
    diagnostic is more like a log line than a library warning: the caller
    is not being told about a type of problem they can catch, they are
    being told what the runtime did on their behalf.
    """
    import sys as _sys
    _sys.stderr.write(
        "forkrun [WARN]: cleanroom UDF helper declined (%s): %s\n"
        "         continuing on the in-process path for this call.\n"
        % (exc.label, (exc.detail or "").strip() or "no detail"))
    _sys.stderr.flush()


def _warn_if_cached_incompatible():
    """Warn once per affected invocation when the helper is already known bad.

    A cached mismatch means we skip the probe, so the launcher never runs
    and never reports anything -- but the call is still AFFECTED, and the
    contract is one warning per affected invocation, not per probe. Without
    this, the first call warns and every subsequent call in the process
    goes quiet, which reads as "the cleanroom just stopped being
    available".

    Emitted at the public-call decision point rather than inside
    helper_path(), which is called several times per call and would either
    warn many times or need state to avoid it.
    """
    try:
        from ._udf import candidate_helper_path, known_incompatible
    except Exception:
        return None
    # candidate_helper_path, NOT helper_path: the cache makes helper_path
    # return None, which would make the reason invisible and silence the
    # warning after the very first call.
    # The kill switch means the UDF path was never considered, so there is
    # no refusal to report. candidate_helper_path() deliberately ignores
    # both the cache and the switch to recover identity for diagnostics;
    # the WARNING DECISION has to honour the switch separately, or a
    # deliberately-disabled UDF would still nag.
    if os.environ.get("FORKRUN_NO_UDF"):
        return None
    path = candidate_helper_path()
    reason = known_incompatible(path) if path else None
    if not reason:
        return None
    import sys as _sys
    _sys.stderr.write(
        "forkrun [WARN]: cleanroom UDF helper declined (%s): %s\n"
        "         continuing on the in-process path for this call.\n"
        % (_CR_EXIT_LABELS.get(80, "version mismatch"), reason.strip()))
    _sys.stderr.flush()
    return reason


def _cleanroom_attempt(fn, payload, mode, helper_fp=None):
    """Run the cleanroom attempt, handling a compatibility refusal.

    Returns ``(out, payload, mode)``. On a refusal the warning is emitted
    (once, here -- the public-call decision point, NOT inside a helper
    lookup that may run many times per call) and the payload is re-coerced
    with ``force_inprocess_udf=True`` so the route genuinely becomes the
    in-process UDF path rather than an ``_UDFPayload`` handed to workers
    that cannot execute it.
    """
    try:
        out = fn()
    except _CleanroomCompatRefusal as exc:
        _record_compat_refusal(exc.code, exc.detail, helper_fp)
        _warn_compat_refusal(exc)
        new_payload, new_mode = _coerce_payload(
            payload, mode, force_inprocess_udf=True)
        return None, new_payload, new_mode
    return out, None, None


def _cleanroom_may_fallback(status):
    """DECISION-03 section 7.2 -- may this launcher failure fall back?

    Extracted as a named function rather than left inline, because the
    policy is the thing worth testing and an inline expression cannot be
    tested without re-implementing it -- which is exactly the mistake that
    made the first version of this test vacuous: it passed identically with
    and without the fix.

    Fallback is permitted ONLY for a failure the launcher confirms happened
    before execution could begin.

    It USED to be:

        replayable   = pre_ingest or _source_is_reopenable(source)
        may_fallback = replayable and not forbidden

    which is wrong, and was demonstrably wrong before it was changed:

        launcher exit 1 ("runtime worker/helper failure")
          PATH source : pre_ingest=False reopenable=True  -> MAY FALL BACK
          FD source   : pre_ingest=False reopenable=False -> no fallback

    The `or` answers "can the INPUT be re-read?" and then uses that answer
    for a different question: "is it SAFE to run the whole workload
    again?". Re-readable input makes replay POSSIBLE; it says nothing about
    user-code side effects already committed. Exit 1 is a runtime failure --
    workers ran, user code ran -- so replaying from batch zero re-executes
    side effects the caller has already been charged for.

    The old rule also made the decision depend on the SHAPE of the source:
    a path replayed, a caller-supplied descriptor did not, for one identical
    failure. That is not a safety property.

    This is deliberately conservative. A failure that happened early but is
    *reported* as a runtime failure now propagates instead of falling back.
    Slow is recoverable; double-executing a side effect is not. The launcher
    should eventually report "execution began" explicitly rather than have
    the parent infer it from an exit code.
    """
    _code, _signum, _label, pre_ingest = _decode_launcher_status(status)
    forbidden = _fallback_forbidden(status)
    return bool(pre_ingest) and not forbidden


def _describe_launcher_failure(status):
    """One human-readable line for a non-zero launcher exit."""
    code, signum, label, _pre = _decode_launcher_status(status)
    if code is not None:
        return "exit %d (%s)" % (code, label)
    if signum is not None:
        return "signal %d (%s)" % (signum, label)
    return label


def _read_launcher_stderr(fd, limit=400):
    """Tail of what the launcher and its children wrote to stderr.

    A launcher failure with no reason is close to undebuggable. The
    launcher's own diagnostics are the only place the real cause appears
    -- `sym()` exits 69 with "missing fr_py_worker_spawn_loop" when the
    substrate predates a worker loop, and the `--plugin`/`--func` path
    reports its own dlopen failure. Inheriting fd 2 put those bytes on
    the caller's terminal, where a test or a captured exception never
    sees them, so the Python-side error could only say
    "exit 127 (unknown exit code 127)".

    That is not hypothetical. A stale `libforkrun_python.so` is an
    ORDINARY state, not an anomaly: both build artifacts are
    gitignored, so a checkout that has not been rebuilt since a change
    to the substrate has exactly this failure, and it presented as a
    generic exec failure with no hint that a rebuild was the fix.

    A memfd, not a pipe: every descendant writes to fd 2, and a pipe
    would deadlock the launcher once 64KB accumulated with nobody
    draining it. The size is final after waitpid, so this is read once.
    """
    if fd is None or fd < 0:
        return ""
    try:
        size = os.fstat(fd).st_size
        if size <= 0:
            return ""
        with open(fd, "rb", closefd=False) as fh:
            fh.seek(max(0, size - limit))
            tail = fh.read(limit)
    except OSError:
        return ""
    text = tail.decode("utf-8", "replace").strip()
    if not text:
        return ""
    # Keep the LAST line: the launcher interleaves children, and the
    # final "fatal -- ..." summary is the one that names the cause.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _source_is_reopenable(source):
    """True if a fallback can re-read the input from the beginning.

    The distinction is OWNERSHIP, and it is decidable at the call site
    without any runtime safety argument:

      * a path -- _cleanroom_source_fd opens its own descriptor, and
        _open_source opens another on fallback, so the two have
        independent file offsets and the source is re-readable.
      * a caller-supplied descriptor (int, or anything with fileno()) --
        _cleanroom_source_fd os.dup()s it, which shares the open file
        description with the descriptor the caller still holds. Once the
        launcher has read from it, the caller's own descriptor is
        advanced and cannot be rewound safely.

    For paths this is still only as good as the file not changing under
    us: a replaced, truncated or deleted path does not replay to the same
    bytes. That is a documented assumption of the API, not a guarantee
    this function can make -- see the fallback contract in the docs."""
    if isinstance(source, (str, bytes, os.PathLike)):
        return True
    return False


# --------------------------------------------------------------------------
# Private candidate launch backend (F6 Stage 3) -- TEST-GATED ONLY
# --------------------------------------------------------------------------
# NOT a public option. There is no environment selector, no keyword, and no
# default change: the shipped path is `fork()` + `execv()` and stays that
# way until a separate adoption decision. Tests flip this module global;
# nothing reachable from the public API can.
_CLEANROOM_LAUNCH_BACKEND = "forkexec"


def _set_cleanroom_launch_backend(name):
    """PRIVATE, test-only. Returns the previous value.

    Accepts "forkexec" (default, shipped) or "posix_spawn" (candidate).
    Raises on anything else rather than silently falling back, so a typo in
    a test cannot quietly exercise the wrong backend.
    """
    global _CLEANROOM_LAUNCH_BACKEND
    if name not in ("forkexec", "posix_spawn"):
        raise ValueError("unknown cleanroom launch backend %r" % (name,))
    prev = _CLEANROOM_LAUNCH_BACKEND
    _CLEANROOM_LAUNCH_BACKEND = name
    return prev


# A waitpid() status for a normally-exited child, used when posix_spawn
# raises instead of returning a pid. 127 is exactly what the shipped
# fork+execv child produces when execv fails (os._exit(127) in
# _spawn_or_fork), so both backends converge on ONE failure path.
_CR_SPAWN_FAILURE_STATUS = 127 << 8


def _spawn_or_fork(launcher, argv, file_actions):
    """Launch `launcher`, return the child pid, or raise OSError.

    The default branch is the shipped code, unchanged: `os.fork()` then
    `os.execv()` in the child. The candidate branch is `os.posix_spawn()`
    with the EQUIVALENCE-FIRST action list -- it reproduces the current
    post-exec descriptor set, INCLUDING unrelated inheritable descriptors.
    It deliberately closes nothing the shipped path keeps.

    No `setsigdef` / `setsigmask` / `setpgroup` / `setsid` / `resetids`:
    those would change behaviour relative to fork+execv, and the signal
    probe in test_launch_failure_contract shows `setsigdef` resetting an
    inherited SIG_IGN to SIG_DFL. Environment is passed unchanged (F7).

    Raises OSError from posix_spawn when the executable cannot be started.
    There is then no wait status to classify, so the caller must map that
    onto the route's established exit-127 result explicitly -- otherwise
    the shipped failure contract would be bypassed.
    """
    if _CLEANROOM_LAUNCH_BACKEND != "posix_spawn":
        pid = os.fork()
        if pid == 0:
            try:
                for act in (file_actions or ()):
                    if act[0] == os.POSIX_SPAWN_DUP2:
                        os.dup2(act[1], act[2])
                os.execv(launcher, argv)
            except BaseException:
                os._exit(127)
        return pid
    return os.posix_spawn(launcher, argv, os.environ,
                          file_actions=tuple(file_actions or ()))


@_route_fd_cleanup
def _execute_cleanroom(source, *, lines, bytes_, workers, plugin_path,
                       plugin_func, on_error, views, strict_poison=False,
                       order="none", orchestrator=True,
                       udf_helper=None, udf_module=None, udf_attr=None,
                       udf_roots=None, spawn_argv=None, _own=None):
    """W-CR1: materialized file + C plugin, orchestrated entirely in C.

    Everything (fr_py_init, spill to the ingress memfd, per-worker output
    memfds, one shared signal pipe, the fallow/workers/scanner forks, the
    drain) happens inside forkrun_cleanroom.c AFTER exec, so no Python
    address space is inherited by the workers. This parent contributes
    two inherited descriptors -- the source file and a result memfd.

    Returns None if the launcher is unavailable or fails, having warned;
    the caller then continues into the normal in-process dispatch.
    """
    import warnings as _warnings
    launcher = _cleanroom_launcher_path()
    if launcher is None:
        _warnings.warn(
            "forkrun: FORKRUN_CLEANROOM=1 but the launcher binary is "
            "missing (expected _forkrun_cleanroom beside the substrate "
            ".so); build it with 'make -f Makefile.substrate "
            "python-substrate' — using the in-process path.",
            UserWarning, stacklevel=3)
        return None
    from ._bindings import find_substrate
    from ._api import _resolve_retry_limit
    from ._worker import _ON_ERROR_CODES
    so = find_substrate()

    # Validated BEFORE the source is opened or read, so an invalid
    # command vector costs no input.
    if spawn_argv is not None:
        spawn_argv = _validate_spawn_argv(spawn_argv)

    # Source resolution, matching the stream() path exactly:
    #   * already a descriptor (int fd, fifo, socket, file object) --
    #     passed straight through as --src. Nothing is pumped; the
    #     launcher reads it the way Bash's -s shape does. Proven by the
    #     SIGKILL tests, which feed a live pipe.
    #   * neither -- not eligible; the envelope declines it first.
    #
    # DESCRIPTORS ONLY, on every path including stream().
    # _api._reject_iterable_source rejects a Python iterable for map(),
    # run() and stream() alike, so there is no iterable producer here or
    # in _execute_cleanroom_stream(). Both used to carry one; both were
    # removed rather than left as dead code -- an unreachable fork of a
    # possibly-multithreaded process is exactly the hazard the codebase
    # comments warn about, and dead safety code is not safety.
    own = _own
    src_fd = _cleanroom_source_fd(source)
    if src_fd is None:
        return None
    # C5: keep every route-owned descriptor above fd 2 so the dup2(errfd, 2)
    # below can never overwrite one of them when the host started with a
    # closed standard stream.
    src_fd = _fd_above_stdio(src_fd)
    own.add("src_fd", src_fd)
    res_fd = _fd_above_stdio(os.memfd_create("fr_cleanroom_result"))
    own.add("res_fd", res_fd)
    # Counter channel. The launcher writes [u32 version][u32 poisoned]
    # here after joining every worker, which is what lets it serve
    # strict_poison and return_stats rather than declining them: without
    # it, _LAST_STATS["poisoned"] stayed 0 and a run with 10 poisoned
    # batches reported total=completed instead of completed+10.
    stats_fd = _fd_above_stdio(os.memfd_create("fr_cleanroom_stats"))
    own.add("stats_fd", stats_fd)
    # The launcher's own stderr, captured so a failure can say WHY. See
    # _read_launcher_stderr: a stale substrate .so otherwise presents as
    # "exit 127 (unknown exit code 127)" with the real cause --
    # "missing fr_py_worker_spawn_loop" -- landing on the caller's
    # terminal where no test or captured exception can see it.
    errfd = _fd_above_stdio(os.memfd_create("fr_cleanroom_err"))
    own.add("errfd", errfd)
    # Pre-size so every worker owns a real slot. A memfd starts
    # zero-filled, which the slot-count convention relies on.
    #
    # The slot STRIDE is _STATS_SLOT_U32 (count word + capacity), and the
    # C side writes the same number into the v2 header, so the two agree
    # by construction rather than by the pre-size happening to be close
    # enough. An earlier version pre-sized with the capacity instead of
    # the stride and carried a comment claiming writes past EOF are
    # "discarded" -- they are not: memfds are sparse, pwrite extends the
    # file, and _read_cleanroom_stats reads fstat's size, so the shortfall
    # silently repaired itself. The numbers were never wrong in practice;
    # the reasoning was, and it would have bitten anyone who took the
    # comment at face value.
    _stats_ftruncate(stats_fd, _STATS_HEADER_BYTES
                     + max(int(workers), 1) * _STATS_SLOT_U32 * 4)
    os.set_inheritable(src_fd, True)
    os.set_inheritable(res_fd, True)
    os.set_inheritable(stats_fd, True)

    # ---- C0.2 opt-in structured trace ----
    #
    # OFF unless FORKRUN_CLEANROOM_TRACE is set, and the fd is the ONLY
    # switch: when it is -1 the launcher's emit helper is a single
    # predictable branch, so a disabled trace costs no syscall and no
    # allocation and never appears in a benchmark.
    #
    # O_APPEND IS LOAD-BEARING, NOT COSMETIC. Measured on this machine
    # (os.fork, 16 children, one 64-byte record per write): a shared file
    # offset recovered 25,962 of 320,000 records -- 92% silently lost --
    # while O_APPEND recovered all 320,000 with zero torn records. The
    # trace exists to diagnose CONCURRENT stalls, so without O_APPEND it
    # would discard most of its evidence exactly when needed, and discard
    # it SILENTLY: a short but well-formed file reads as "fewer events",
    # not as "we lost data".
    trace_fd = -1
    if _cleanroom_trace_enabled():
        trace_fd = _fd_above_stdio(os.memfd_create("fr_cleanroom_trace"))
        os.set_inheritable(trace_fd, True)
        own.add("trace_fd", trace_fd)
        # Set O_APPEND on the SHARED open file description, before any
        # fork, so every child inherits the append semantics.
        _fcntl.fcntl(trace_fd, _fcntl.F_SETFL,
                     _fcntl.fcntl(trace_fd, _fcntl.F_GETFL) | os.O_APPEND)

    argv = [launcher, "--so", so,
            "--workers", str(int(workers)),
            "--lines", str(int(lines or 0)),
            "--bytes", str(int(bytes_ or 0)),
            # Transport the fault policy rather than refusing it: the
            # launcher already accepts both codes, and _ON_ERROR_CODES
            # is the same table the C worker loop uses.
            "--on-error", str(_ON_ERROR_CODES.get(on_error, 0)),
            "--retry", str(int(_resolve_retry_limit())),
            "--src", str(src_fd), "--result", str(res_fd),
            "--stats-fd", str(stats_fd)]
    if udf_helper:
        # P1-3: the launcher initialises the interpreter BEFORE forking
        # and selects fr_py_worker_udf_loop. --plugin/--func are NOT sent
        # in this mode; the launcher rejects the combination.
        argv += ["--udf-helper", udf_helper,
                 "--udf", udf_module,
                 "--udf-attr", udf_attr]
        argv += _caller_version_argv()
        if udf_roots:
            argv += ["--udf-roots", udf_roots]
    elif plugin_path is None and plugin_func is None:
        # Spawn mode: there is NO plugin to dlopen, and this must not
        # claim otherwise.
        #
        # This sent `--plugin None --func None`, so the launcher
        # dlopen()ed the literal four-character string "None", failed,
        # and the run died in the spill child with exit 1 -- surfaced
        # to the caller as a generic "launcher failed (exit 127)".
        # Spawn's own argv then still travelled correctly, which is why
        # the symptom looked like an exec failure rather than a
        # descriptor mix-up.
        pass
    else:
        argv += ["--plugin", plugin_path, "--func", plugin_func]
    if spawn_argv:
        # Stage 3: the command vector travels as DISTINCT elements.
        #
        # No shell-word parsing and no newline-delimited encoding: a
        # newline is a legal character inside a single argument, so any
        # line-based encoding is ambiguous against one.
        #
        # NUL is rejected HERE, at the point user input becomes an argv
        # element. It cannot be rejected in C: a C string is
        # NUL-terminated by definition, so an embedded NUL would have
        # silently truncated the argument before the launcher ever saw
        # it. This runs before the launcher starts and before the source
        # is read, so a rejected command costs no input.
        for _el in spawn_argv:
            argv += ["--spawn-argv", _el]
    if trace_fd >= 0:
        argv += ["--trace-fd", str(trace_fd)]
    # `orchestrator is False`, NOT `not orchestrator`: map() defaults
    # orchestrator to None (meaning "ride the reactor"), and None is falsy.
    # Using `not` here sent --supervise fail-fast for EVERY default call,
    # which broke the cleanroom for the ordinary path.
    if orchestrator is False:
        argv += ["--supervise", "fail-fast"]

    # Equivalence-first candidate action list: the materialized child does
    # exactly one descriptor transformation before exec, so the spawn
    # equivalent is a single DUP2. `errfd` itself stays FD_CLOEXEC and is
    # NOT closed -- that is what the shipped path does, and equivalence
    # means reproducing it, not improving it.
    _actions = ((os.POSIX_SPAWN_DUP2, errfd, 2),)
    # Only src_fd was the child's alone. res_fd MUST stay open here --
    # the parent reads the result memfd after waitpid. Closing it (an
    # earlier cut did) leaves the collector fstat-ing a closed
    # descriptor, and since the number is liable to be recycled that
    # surfaces as empty/corrupt output rather than a clean EBADF.
    try:
        pid = _spawn_or_fork(launcher, argv, _actions)
    except OSError:
        # posix_spawn reports "cannot execute" by raising IN THE PARENT:
        # there is no child, so there is no wait status to classify and no
        # pid to reap.
        #
        # Rather than inventing a parallel error path -- which is how a
        # backend swap ends up changing the PUBLIC failure contract -- this
        # synthesises the SAME wait status a child produces when execv
        # fails (127) and lets the existing classification below run
        # untouched. Everything downstream (the "NOT falling back"
        # warning, `_decode_launcher_status`, `_cleanroom_may_fallback`,
        # the RuntimeError) is therefore identical by construction.
        # Policy B -- treating this as pre-ingest and falling back -- is
        # explicitly NOT done, and 127 is outside _CR_EXIT_PRE_INGEST.
        status = _CR_SPAWN_FAILURE_STATUS
    else:
        own.close("src_fd")
        _wpid, status = os.waitpid(pid, 0)
    own.close("src_fd")
    # Unpack ONLY after the None check below. _read_cleanroom_stats
    # returns None for "no trustworthy count" -- notably when the
    # launcher declined the payload (a v0 plugin under FORKRUN_CLEANROOM=1
    # has no use_ctx, so there is no stats fd at all). Unpacking here
    # raised TypeError: cannot unpack non-iterable NoneType, which
    # crashed the fallback path the None was written to trigger. Eight
    # test_plugin tests hit this with the gate ON and were green with it
    # off, which is why the cleanroom-OFF run alone never showed it.
    stats = _read_cleanroom_stats(stats_fd)
    own.close("stats_fd")
    # Read the trace AFTER waitpid: the launcher and every child are gone
    # by then, so the file is complete and its size is final.
    if trace_fd >= 0:
        _LAST_TRACE[:] = _read_cleanroom_trace(trace_fd)
        own.close("trace_fd")
    if not (os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0):
        own.close("res_fd")
        code, signum, label, pre_ingest = _decode_launcher_status(status)
        # CR-FIX1-F: a failed capability probe means the plugin's LOAD is
        # unsafe, so the in-process fallback -- which would dlopen it
        # right here in the caller's process -- would reproduce the
        # failure in a place with no launcher to bound it. Refuse.
        forbidden = _fallback_forbidden(status)
        # DECISION-03 section 7.2: the replay policy lives in a named
        # function so it can be tested without re-implementing it.
        may_fallback = _cleanroom_may_fallback(status)
        _why_launcher = _read_launcher_stderr(errfd)
        # FD-LEAK-1 (failure half): errfd's LAST parent-side use is the
        # read above -- _read_launcher_stderr opens with closefd=False,
        # so the read does NOT close it. Close here, BEFORE every raise
        # and return below, so each of those exits releases it. Without
        # this the descriptor survived every failed call as well as every
        # successful one.
        own.close("errfd")
        if code in _CR_COMPAT_REFUSALS:
            # A compatibility refusal must NOT collapse into a bare
            # "return None": the dispatcher has to know WHY, because the
            # generic fall-through re-enters _coerce_payload(), which
            # consults helper_path() again and would hand back an
            # _UDFPayload for the ordinary Python worker to fail on --
            # since the file is still present, only the launcher knows it
            # is unusable.
            raise _CleanroomCompatRefusal(label, _why_launcher,
                                          _CR_COMPAT_REFUSALS[code],
                                          code=code)
        _warnings.warn(
            "forkrun: cleanroom launcher failed (%s)%s — %s"
            % (_describe_launcher_failure(status),
               ": " + _why_launcher if _why_launcher else "",
               "falling back to the in-process path" if may_fallback
               else "NOT falling back"),
            UserWarning, stacklevel=3)
        if forbidden:
            raise RuntimeError(
                "forkrun: cleanroom launcher failed (%s). Retrying "
                "in-process would load the same plugin in this process "
                "and reproduce the failure here, so the call is refused "
                "rather than retried. Load the plugin explicitly once to "
                "confirm it is safe before using it with forkrun."
                % (_describe_launcher_failure(status),))
        if may_fallback:
            return None
        # CR-FIX1-C: the launcher may have consumed bytes out of the
        # source, so the in-process path could resume mid-input and return
        # a truncated result with exit 0. Refuse instead: a failed run that
        # says so is strictly better than a successful-looking one that
        # lost records.
        #
        # NOTE this used to tell callers that passing a PATH would permit a
        # retry. That advice is WITHDRAWN. It was the bug: re-readable
        # input makes replay possible, not safe, and on a path source a
        # runtime failure replayed the whole workload -- re-executing user
        # side effects that had already been committed. See
        # _cleanroom_may_fallback.
        raise RuntimeError(
            "forkrun: cleanroom launcher failed (%s) after the input may "
            "have been consumed, and the supplied source is a descriptor "
            "whose read position the launcher shares. Retrying in-process "
            "would resume mid-input and silently return truncated output, "
            "so this call is refused rather than completed incorrectly. "
            "Pass a path (or seek the descriptor back to 0 yourself) if "
            "you want a retry." % (_describe_launcher_failure(status),))
    else:
        # FD-LEAK-1 (success half): the launcher exited cleanly, so
        # nothing reads errfd -- the stderr tail is consulted only on
        # failure. Without this the descriptor survived every successful
        # call. `errfd = -1` after closing keeps a stray later close from
        # hitting a RECYCLED descriptor number.
        own.close("errfd")
    if stats is None:
        # The counter record is missing, unreadable, or absent because the
        # launcher declined the payload. Refuse the
        # cleanroom result rather than report completed-as-total: a
        # wrong-but-plausible total is worse than the slower path.
        own.close("res_fd")
        _warnings.warn(
            "forkrun: cleanroom launcher returned no counter record; "
            "poison counts are unknown so total/poisoned would be wrong "
            "(or strict_poison unenforceable) — using the in-process "
            "path.", UserWarning, stacklevel=3)
        return None
    npois, npois_idx, nrelayed = stats
    # Surface, don't hide: a bounded slot means the list can be a strict
    # prefix of the count. Say so once, loudly, rather than letting a
    # caller infer completeness from a number that quietly stopped
    # growing. `poisoned` stays authoritative either way.
    _trunc = nrelayed < npois
    if _trunc:
        _warnings.warn(
            "forkrun: poisoned_batches is TRUNCATED — %d of %d poisoned "
            "batch indices are missing because a worker's relay slot is "
            "full (capacity %d indices per worker). The poisoned count is "
            "exact; only the index list is incomplete."
            % (npois - nrelayed, npois, _STATS_CAPACITY),
            UserWarning, stacklevel=3)
    # Record the counter BEFORE collecting: a poisoned batch is absent
    # from the results, so completed = len(out) undercounts unless the
    # poison count is added back, and _finish_map_stats needs it.
    _LAST_STATS["poisoned"] = npois
    _LAST_STATS["poisoned_batches"] = list(npois_idx)
    _LAST_STATS["poisoned_batches_truncated"] = _trunc
    # Ownership TRANSFER: _cleanroom_collect closes res_fd itself. Without
    # release() the decorator's cleanup would close the same number again,
    # and if the collector had already closed it the number may have been
    # recycled -- closing a descriptor the caller now owns.
    own.release("res_fd")
    out = _cleanroom_collect(res_fd, views, order)
    # strict_poison is served now: the count came back over the stats
    # channel, so raising is a real enforcement rather than a guess.
    # Default (False) keeps warn-and-return-partial semantics.
    if strict_poison:
        _raise_for_poisoned(npois, True)
    return out


# Stats channel geometry, mirrored by the launcher (v2 header) and by
# fr_poison_relay() in forkrun_ring.c. All three must agree:
#   header : [u32 version][u32 poisoned][u32 workers][u32 slot_stride]
#   slot   : [u32 count][count x u32 batch_idx], one per worker
_STATS_HEADER_BYTES = 16
# Slot STRIDE in u32, not capacity: one count word followed by the indices.
# Must equal FR_POISON_SLOT_U32 + 1 in forkrun_ring.c, which is also what
# the launcher puts in the v2 header's stride field.
_STATS_SLOT_U32 = 1024 + 1
_STATS_CAPACITY = _STATS_SLOT_U32 - 1   # indices per slot, excluding count


class _PoisonStatsChannel:
    """Parent end of the bounded poison-index relay, for plain paths.

    WO-PY-REL-1 / TD-09. The C relay (fr_py_poison_relay, _shim.c:447)
    ALREADY runs on the plain path -- fr_py_claim() calls it on the same
    `num_kills == threshold` edge that increments the shared poisoned
    count. What was missing is the receiving end: nothing created the
    stats memfd, nothing exported $FRK_POISON_FD, and the descriptor was
    not in the worker keep-set, so the relay resolved g_poison_fd < 0 and
    returned silently. The symptom -- a non-zero `poisoned` beside an
    empty `poisoned_batches` -- is indistinguishable from "nothing was
    poisoned", which is why it survived as long as it did.

    This is the same bounded transport the cleanroom already uses, so
    both paths now share one contract: `_STATS_CAPACITY` indices per
    worker, silent drop on overflow, and completeness decided by
    `relayed < poisoned` rather than by the length of the list.
    """

    __slots__ = ("fd", "workers")

    def __init__(self, workers):
        self.workers = max(1, int(workers))
        self.fd = None

    def open(self):
        """Create this run's stats memfd, pre-sized and headed.

        ONE memfd PER RUN, created here and closed in close(). An earlier
        iteration of this code reused a single process-wide memfd so the
        fd NUMBER stayed stable, because fr_py_poison_relay() used to
        cache the fd it read from $FRK_POISON_FD in a __thread variable
        and never re-read it; a fresh number per run would have left
        workers holding a stale one.

        That cache is GONE (see the comment on fr_py_poison_relay in
        _shim.c -- it was the cause of TD-09 resurfacing under the full
        suite), so the constraint no longer exists and the simpler
        per-run memfd is both correct and self-healing: a descriptor
        closed or recycled by anything else cannot invalidate it, because
        it lives for exactly one call.

        Pre-sizing matters: the slot convention relies on each worker's
        region existing so its count word is readable. The header's
        poisoned field is a placeholder -- the real count is known only
        after the join, and seal() writes it.
        """
        import struct as _struct
        fd = os.memfd_create("fr_poison_stats")
        self.fd = fd
        need = _STATS_HEADER_BYTES + self.workers * _STATS_SLOT_U32 * 4
        try:
            size = os.fstat(fd).st_size
        except OSError:
            size = 0
        if size != need:
            try:
                os.ftruncate(fd, 0)
                os.ftruncate(fd, need)
            except OSError:
                # Grow-only fallback; a short region just reads back as
                # fewer slots, and seal() reports that honestly.
                try:
                    os.ftruncate(fd, max(need, size))
                except OSError:
                    pass
        hdr = _struct.pack("<IIII", 2, 0, self.workers, _STATS_SLOT_U32)
        os.pwrite(fd, hdr, 0)
        self.fd = fd
        return fd

    def seal(self, poisoned):
        """Publish the authoritative count, then read indices back."""
        import struct as _struct
        if self.fd is None:
            return [], 0
        try:
            os.pwrite(self.fd, _struct.pack("<I", int(poisoned)), 4)
            _got, idxs, relayed = _read_cleanroom_stats(self.fd)
        except OSError:
            return [], 0
        return sorted(set(idxs)), relayed

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


class _ExportedPoisonFd:
    """Export $FRK_POISON_FD across the fork, and ALWAYS restore it.

    os.environ is process-global, so a plain set-and-forget would leak the
    variable into every later run and sibling test in the same process --
    and a stale fd number is worse than none: the relay would write into
    whatever happens to occupy that number. Restoration is therefore in a
    finally, not on the success path.
    """

    __slots__ = ("_prev", "_fd")

    def __init__(self, fd):
        self._fd = fd
        self._prev = os.environ.get("FRK_POISON_FD")

    def __enter__(self):
        if self._fd is not None and self._fd >= 0:
            os.environ["FRK_POISON_FD"] = str(self._fd)
        return self

    def __exit__(self, *exc):
        if self._prev is None:
            os.environ.pop("FRK_POISON_FD", None)
        else:
            os.environ["FRK_POISON_FD"] = self._prev
        return False


def _read_poison_count(lib):
    """The engine's authoritative poisoned count, or 0 if unreadable."""
    try:
        return lib.fr_py_poisoned_count()
    except Exception:
        return 0


def _collect_plain_poison(channel, poisoned, strict_truncation_warn=True):
    """Fold plain-path poison indices into _LAST_STATS.

    Called BEFORE report_poison(), because report_poison() may raise via
    strict_poison and the post-exception stats then have to be inspectable.
    """
    if channel is None:
        return
    idxs, relayed = channel.seal(poisoned)
    _trunc = relayed < int(poisoned or 0)
    _LAST_STATS["poisoned_batches"] = list(idxs)
    _LAST_STATS["poisoned_batches_truncated"] = bool(_trunc)
    if _trunc and strict_truncation_warn:
        import warnings as _warnings
        _warnings.warn(
            "forkrun: poisoned_batches is TRUNCATED — %d of %d poisoned "
            "batch indices are missing because a worker's relay slot is "
            "full (capacity %d indices per worker). The poisoned count is "
            "exact; only the index list is incomplete."
            % (int(poisoned or 0) - relayed, int(poisoned or 0),
               _STATS_CAPACITY),
            UserWarning, stacklevel=4)


def _stats_ftruncate(fd, size):
    """Grow the stats memfd. Best-effort; absence is caught downstream."""
    try:
        os.ftruncate(fd, size)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# C0.2: the cleanroom structured trace.
#
# The wire format is forkrun_trace.h. The constants are duplicated here
# deliberately rather than generated: a build-time dependency from the
# Python package on a C header would be a much larger coupling than 14
# integers, and _test_trace_layout_matches_header asserts the two agree by
# COMPILING the header, so a divergence fails the suite instead of
# corrupting a diagnosis.
# ---------------------------------------------------------------------------

_TRACE_REC = 64
_TRACE_MAGIC = 0x52544646          # 'F','T','R','F'
_TRACE_VERSION = 1
# The format is I,H,H,q,... because the C struct is uint32 magic then
# uint16 version then uint16 rec_bytes. An earlier draft wrote I,B,B,H --
# which totals the SAME 8 bytes, so the record-size check passed while
# every field after magic was misaligned and version was read as two
# bytes. _test_python_field_offsets_match_c now derives this format's
# offsets and compares them to the compiler's offsetof, which is the
# check that was missing and should have caught it.
_TRACE_STRUCT = "<IHHqIbb2xiiii24x"

_TRACE_ROLES = {
    0: "launcher", 1: "worker", 2: "probe", 3: "spill",
    4: "fallow", 5: "scan", 6: "drain", 7: "orderer",
}

_TRACE_EVENTS = {
    1: "launcher_init", 2: "fork_request", 3: "fork_return",
    4: "child_entry", 5: "child_exit", 6: "reap",
    7: "sup_enter", 8: "sup_exit", 9: "sup_abort", 10: "sup_respawn",
    11: "fatal_begin", 12: "fatal_kill", 13: "fatal_reap",
    14: "fatal_end",
}

# The most recent launcher trace. Empty when tracing was off.
_LAST_TRACE: list = []


def _cleanroom_trace_enabled() -> bool:
    """Is the opt-in trace on? Off unless the env var is set to a true-ish
    value.

    Deliberately NOT honoured when the value is present but falsy: a trace
    left on by an inherited environment is exactly the kind of thing that
    quietly perturbs a benchmark.
    """
    v = os.environ.get("FORKRUN_CLEANROOM_TRACE")
    return bool(v) and v not in ("0", "false", "no", "off")


def _read_cleanroom_trace(trace_fd):
    """Parse the trace memfd into a list of dicts.

    Returns [] on any doubt. The trace is an OBSERVATION channel: a parse
    failure must never propagate into the run it was observing, and a
    partial trace is worse than none because it invites conclusions from
    missing evidence. Every record is checked for magic, version and
    record size, so truncation or skew is detected rather than misparsed.
    """
    try:
        size = os.fstat(trace_fd).st_size
    except OSError:
        return []
    if size <= 0:
        return []
    # A trailing partial record means the file was cut mid-write. Report
    # nothing rather than the complete prefix: the caller asked for a
    # whole run, not a prefix of one.
    if size % _TRACE_REC:
        return []
    try:
        raw = os.pread(trace_fd, size, 0)
    except OSError:
        return []
    out = []
    for off in range(0, len(raw), _TRACE_REC):
        (magic, ver, rec, t_ns, pid, role, event,
         wid, wincarn, node, rc) = struct.unpack_from(
            _TRACE_STRUCT, raw, off)
        if magic != _TRACE_MAGIC or rec != _TRACE_REC:
            return []
        if ver != _TRACE_VERSION:
            return []
        out.append({
            "t_ns": t_ns,
            "pid": pid,
            "role": _TRACE_ROLES.get(role, "role%d" % role),
            "event": _TRACE_EVENTS.get(event, "event%d" % event),
            # FR_TRACE_NA is -1, meaning "not applicable". Surfaced as
            # None so a reader cannot mistake it for wid 0 or wincarn 0.
            "wid": None if wid == -1 else wid,
            "wincarn": None if wincarn == -1 else wincarn,
            "node": node,
            "rc": rc,
        })
    return out


def _read_cleanroom_stats(stats_fd):
    """Read the launcher's counter record. Returns the poisoned count.

    Returns None when the record is absent, short or a version we do not
    know -- meaning "no trustworthy count", which is deliberately NOT the
    same as zero. Zero would let _finish_map_stats compute
    total = completed + 0 and report a plausible-looking wrong total,
    which is the exact bug the stats channel exists to remove. None makes
    the caller fall back to the in-process path instead.
    """
    # Read the WHOLE region, not just the header: the poisoned-index
    # slots follow it. Reading 16 bytes made the slot loop below see
    # base+4 > len(raw) and return an empty list, i.e. the relay was
    # working and the reader threw the data away.
    try:
        size = os.fstat(stats_fd).st_size
    except OSError:
        return None
    try:
        raw = os.pread(stats_fd, max(int(size), 16), 0)
    except OSError:
        return None
    if len(raw) < 8:
        return None
    version, poisoned = struct.unpack_from("<II", raw, 0)
    if version < 1:
        return None
    if version == 1:
        return int(poisoned), [], 0
    # v2: poisoned batch indices follow the header, one bounded slot per
    # worker. Anything malformed degrades to the scalar alone, which is
    # still authoritative for total and strict_poison.
    if len(raw) < _STATS_HEADER_BYTES:
        return int(poisoned), [], 0
    _ver, _poi, workers, stride = struct.unpack_from("<IIII", raw, 0)
    if not stride:
        return int(poisoned), [], 0
    idxs = []
    relayed = 0
    for wid in range(min(int(workers), 4096)):
        base = _STATS_HEADER_BYTES + wid * stride * 4
        if base + 4 > len(raw):
            break
        (n,) = struct.unpack_from("<I", raw, base)
        if n > _STATS_CAPACITY:
            # One slot is unreadable, but slots are independent and each
            # has a single writer, so skip THIS one rather than abandoning
            # every later worker's indices as well.
            continue
        relayed += int(n)
        for k in range(int(n)):
            off = base + 4 + k * 4
            if off + 4 > len(raw):
                break
            (b,) = struct.unpack_from("<I", raw, off)
            idxs.append(int(b))
    # `relayed` is how many indices the workers actually managed to hand
    # over; `poisoned` is the exact scalar. Whenever relayed < poisoned the
    # list is a PREFIX of the truth, not the truth: either a worker filled
    # its 1024-entry slot and the rest were dropped, or a poison happened
    # with no usable $FRK_POISON_FD. The parent cannot tell those apart and
    # does not need to -- both mean the list is incomplete, which is the
    # one thing a caller has to know before trusting len(). Deriving this
    # from data that already crosses keeps the on-wire layout unchanged.
    return int(poisoned), sorted(set(idxs)), relayed


def _cleanroom_collect(res_fd, views, order="none"):
    """W-CR1: parse the launcher's framed records into map() output.

    Framing is the engine's own [batch_idx u64][len u64][payload] -- the
    same _HDR struct _worker writes -- so nothing new is invented.
    views=True mmaps the result memfd read-only for zero-copy
    memoryviews; views=False copies. Owns and closes res_fd.

    order="index" SORTS by the batch_idx already present in each record's
    own framing header. The launcher runs no orderer and its drain is
    unordered, so the memfd is in batch-COMPLETION order; without this
    sort, order="index" silently returned completion order, which is a
    direct violation of the documented API contract. (This is the same
    job collect_records does for the in-process paths -- it just cannot
    be used here because the cleanroom framing is parsed straight out of
    the result memfd rather than through _iter_records.)
    """
    try:
        size = os.fstat(res_fd).st_size
        out = []
        import warnings as _warnings
        if size == 0:
            # Empty input (or every record discarded) legitimately
            # yields a zero-length result memfd; there is nothing to map.
            # An empty run is [].
            return out

        # ONE buffer, ONE parse loop.
        #
        # This used to have two near-identical loops -- one over an
        # mmap.mmap, one over an os.pread -- which had already let the
        # torn-record fix land in one and miss the other. The only real
        # difference between them is where the bytes come from, so that
        # is the only thing that varies now.
        #
        # The mapping goes through _map_collect, the same helper the
        # in-process path uses, rather than stdlib mmap.mmap. Two
        # reasons, both substantive:
        #   - mmap.mmap(fd, ...) DUPs the descriptor and holds it for the
        #     life of the mapping. API.md states the invariant this
        #     violates: "No descriptor is held (mmap.mmap(fd, ...) would
        #     dups one)". The cleanroom path was the one place that broke
        #     it, and test_no_fd_leak_from_mappings only covered the shim
        #     path, so nothing noticed.
        #   - fr_py_map_readonly also prefaults (MADV_POPULATE_READ) and
        #     requests hugepages. Python's mmap exposes neither
        #     (MADV_POPULATE_READ is not in this build's mmap or os), so
        #     the cleanroom was paying the page-fault cost lazily on the
        #     first pass instead of up front.
        buf = None
        if views:
            from ._bindings import get as _get
            buf = _map_collect(_get(), res_fd, size)
        if buf is None:
            # Either the caller wanted bytes, or mapping was unavailable
            # (None means "cannot map", never "empty"). Degrade to a
            # pread: correct, one copy per record, and still no descriptor
            # retained past the read.
            raw = os.pread(res_fd, size, 0)
            if len(raw) < size:
                # Short read: parse what actually arrived rather than
                # trusting `size`, or unpack_from reads past the buffer.
                size = len(raw)
            buf = raw

        base = 0
        while size - base >= _HDR.size:
            _bidx, blen, _disp, _res = _HDR.unpack_from(buf, base)
            start = base + _HDR.size
            if size - start < blen:
                # A header whose payload is not fully there is a torn
                # record, not end-of-stream. Returning normally here made
                # a truncated result indistinguishable from a complete
                # one -- the same silent-tail-loss shape as F-NUMA1, and
                # the output still parsed cleanly, it was just short.
                #
                # WARN, do not raise: a worker killed mid-record
                # legitimately leaves a torn tail, and strict_poison /
                # the poison counts already report that death. Raising
                # would report one failure twice, the second time as an
                # exception the caller did not ask for.
                _warnings.warn(
                    "forkrun: cleanroom result ends in a torn record "
                    "-- %d byte(s) short of the advertised length. "
                    "Output is incomplete; check poisoned/strict_poison "
                    "for a worker death mid-record."
                    % (blen - (size - start)), UserWarning, stacklevel=3)
                break
            # DECISION-02: control records carry no payload; skip them
            # (see _split_records for why surfacing them as b"" would be
            # a wrong answer rather than a cosmetic one).
            if _disp == _DISP_DATA:
                out.append((_bidx, buf[start:start + blen]))
            base = start + blen
        if order == "index":
            out.sort(key=lambda kv: kv[0])
        return [blob for _, blob in out]
    finally:
        try:
            os.close(res_fd)
        except OSError:
            pass


def _cleanroom_source_fd(source):
    """Resolve a cleanroom source to an fd, or None if it is not one.

    THE single source resolver, used by both the map and stream cleanroom
    paths. There used to be two, and they disagreed in a way that was a
    live bug in each:

      * The stream resolver returned None for a REGULAR FILE (written
        when "streaming never materializes, so a fifo is the interesting
        case"). Its caller then asked "is this an iterable?" -- and a
        str path IS iterable, so forkrun.stream(spec, "/path/file",
        streaming=True) fed the PATH STRING to the producer, character by
        character. The launcher then failed ("spill child died"), and
        because that path also discarded the launcher's exit status, the
        caller saw a clean EOF: a truncated stream and no error.

      * The map resolver handled regular files correctly but was a second
        copy of the same path-vs-iterable precedence rule.

    Order is the whole point: decide "path/descriptor" BEFORE "iterable",
    because str and bytes both satisfy __iter__ and would otherwise be
    mistaken for a record source. A regular file needs no special case
    at all -- the launcher spills from a descriptor exactly as it does
    for a fifo.
    """
    try:
        if isinstance(source, int) and not isinstance(source, bool) \
                and source >= 0:
            fd = os.dup(source)
        elif isinstance(source, (str, bytes, os.PathLike)):
            fd = os.open(os.fspath(source), os.O_RDONLY)
        elif hasattr(source, "fileno"):
            fd = os.dup(source.fileno())
        else:
            return None
    except (OSError, ValueError, AttributeError):
        return None
    os.set_inheritable(fd, True)
    return fd


@_route_fd_cleanup
def _execute_cleanroom_stream(source, *, lines, bytes_, workers,
                              plugin_path, plugin_func, on_error,
                              strict_poison=False,
                              udf_helper=None, udf_module=None,
                              udf_attr=None, udf_roots=None, _own=None):
    """W-CR3: STREAMING cleanroom -- yield results as they arrive.

    Same envelope as the map() path (materialised-vs-streaming aside).
    The source must already be a descriptor -- a path, a fifo, a socket,
    an int fd or a file object -- and is passed straight through as
    `--src`. Nothing is pumped.

    ACCEPTED INPUT SHAPE, precisely: there is no iterable producer and
    no producer child. One used to exist here (a forked child pumping a
    Python iterable into a pipe) but it was UNREACHABLE --
    `_api._reject_iterable_source` refuses iterables for map(), run() and
    stream() alike, "Python is never an input pump" -- while its waitpid
    and teardown entries stayed live in this function's control flow. It
    was removed; its sibling in `_execute_cleanroom()` had already been
    removed for the same reason. A source that `_cleanroom_source_fd()`
    cannot turn into a descriptor is a TypeError, not a forked pump.

    The parent only ever DRAINS. That is what makes it deadlock-free:
    the launcher can block writing results and the spill child can block
    reading the source, and both are relieved because the parent never
    stops reading rr until EOF.

    Teardown is explicit rather than best-effort: on abandonment
    (GeneratorExit) the launcher child is killed before the fds close,
    so an early `break` out of the caller's loop cannot leave it
    writing into a closed pipe.
    """
    import warnings as _warnings
    launcher = _cleanroom_launcher_path()
    if launcher is None:
        _warnings.warn(
            "forkrun: cleanroom launcher missing — streaming uses the "
            "in-process path. Build it with 'make -f Makefile.substrate "
            "python-substrate'.", UserWarning, stacklevel=3)
        return None
    from ._bindings import find_substrate
    from ._api import _resolve_retry_limit
    from ._worker import _ON_ERROR_CODES
    so = find_substrate()

    src_fd = _cleanroom_source_fd(source)
    if src_fd is None:
        # Reachable as a VALIDATION (an unrecognised source), so it stays.
        # What is NOT reachable is the iterable producer this used to
        # guard: _api._reject_iterable_source refuses Python iterables
        # before dispatch, so there is nothing to pump.
        raise TypeError(
            "FORKRUN_CLEANROOM stream(): source must be a readable "
            "descriptor or a path, got %r" % (type(source),))

    # C5: every route-owned descriptor must sit above fd 2. This shape has
    # no dup2(errfd, 2), but a route descriptor landing on a standard-stream
    # number would still alias what the host left there AND be handed to the
    # launcher as that number.
    own = _own
    src_fd = _fd_above_stdio(src_fd)
    own.add("src_fd", src_fd)
    rr, rw = os.pipe()
    # F6 Stage 4. Stage 3 relocated `src_fd` here and then left the pipe
    # ends exactly where `os.pipe()` put them, under a comment claiming
    # "every route-owned descriptor must sit above fd 2". `os.pipe()`
    # returns the LOWEST FREE pair, so with the standard-stream gap
    # partly free these land INSIDE it -- and `rw` is then made
    # inheritable and handed to the launcher as `--result`. A `rw` on fd 1
    # is simultaneously the launcher's stdout, and a `rw` on fd 2 is its
    # stderr: results are written into a channel the launcher also uses for
    # diagnostics, and the parent drains a stream that never contained what
    # it claimed to. Observed end to end before this fix, with fd 0/1/2
    # closed: `--src 2`, then `2 worker(s) failed ... respawn cap reached`.
    rr = _fd_above_stdio(rr)
    own.add("rr", rr)
    rw = _fd_above_stdio(rw)
    own.add("rw", rw)
    os.set_inheritable(src_fd, True)
    os.set_inheritable(rw, True)

    # DECISION-02 / P2 strict_poison: the streaming launch contract had NO
    # statistics channel at all, so strict_poison could not be honoured here
    # -- it was not a dropped return value, the descriptor was never passed.
    # Same memfd convention as the map path, pre-sized so every worker owns a
    # real slot.
    stats_fd = _fd_above_stdio(os.memfd_create("fr_cleanroom_stream_stats"))
    own.add("stats_fd", stats_fd)
    _stats_ftruncate(stats_fd, _STATS_HEADER_BYTES
                     + max(int(workers), 1) * _STATS_SLOT_U32 * 4)
    os.set_inheritable(stats_fd, True)

    argv = [launcher, "--so", so,
            "--workers", str(int(workers)),
            "--lines", str(int(lines or 0)),
            "--bytes", str(int(bytes_ or 0)),
            "--on-error", str(_ON_ERROR_CODES.get(on_error, 0)),
            "--retry", str(int(_resolve_retry_limit())),
            "--src", str(src_fd),      # non-None: validated above
            "--result", str(rw),
            "--stats-fd", str(stats_fd)]
    if udf_helper:
        argv += ["--udf-helper", udf_helper,
                 "--udf", udf_module,
                 "--udf-attr", udf_attr]
        argv += _caller_version_argv()
        if udf_roots:
            argv += ["--udf-roots", udf_roots]
    else:
        argv += ["--plugin", plugin_path, "--func", plugin_func]

    # Equivalence-first candidate action list: EMPTY, and deliberately so.
    # The streaming child closes `rr` before exec, but `rr` is ALREADY
    # FD_CLOEXEC (os.pipe sets it), so the kernel removes it at exec in the
    # shipped path too. Adding a POSIX_SPAWN_CLOSE for rr would imitate the
    # SPELLING of os.close(rr) rather than its EFFECT; the post-exec
    # descriptor state is already identical with no actions at all.
    try:
        launch_pid = _spawn_or_fork(launcher, argv, ())
    except OSError:
        # Same mapping as the materialized route: synthesise the exit-127
        # status so the existing classification raises the STREAMING
        # truncation error, not a materialized input-consumption one.
        launch_pid = None
        launch_status = _CR_SPAWN_FAILURE_STATUS
    else:
        launch_status = None
    # parent
    own.close("src_fd")
    own.close("rw")
    tail = b""
    finished = False
    try:
        while True:
            data = os.read(rr, 1 << 16)
            if data == b"":
                break
            if tail:
                data = tail + data
                tail = b""
            base = 0
            while len(data) - base >= _HDR.size:
                _bidx, blen, _disp, _res = _HDR.unpack_from(data, base)
                start = base + _HDR.size
                if len(data) - start < blen:
                    break
                # DECISION-02: skip control dispositions (see _split_records).
                if _disp == _DISP_DATA:
                    yield data[start:start + blen]
                base = start + blen
            tail = data[base:]
        # The pipe hit EOF. That is only a legitimate END OF INPUT if the
        # producer exited cleanly: a producer that raises (or is killed)
        # also EOFs the pipe, and the launcher ingests a SHORT corpus and
        # exits 0, so the caller would get plausible-looking truncated
        # results and no error.
        #
        # HONEST SCOPE, and it is a REAL limitation, not a hedge: this
        # function cannot detect that a CALLER-FED pipe died mid-stream.
        # There is no child of ours to inspect -- the writer is the
        # caller's own process or thread -- so a writer that errors out
        # simply EOFs the pipe, the launcher ingests a SHORT corpus and
        # exits 0, and the caller receives plausible-looking truncated
        # results with no error naming the cause.
        #
        # This used to be checkable, via a fork()ed Python producer that
        # pumped an iterable. That branch was unreachable and was removed
        # (WO Phase D.4): _api._reject_iterable_source refuses a Python
        # iterable for map(), run() and stream() alike -- "Python is never
        # an input pump" -- so the producer could never run, while its
        # 30-odd lines and its waitpid/teardown entries stayed live in
        # this function's control flow.
        # EOF on the result pipe is NOT proof of success. The launcher
        # exits non-zero for unrecoverable worker death, helper death,
        # spill failure, recovery failure and abort -- and in every one
        # of those cases it has already streamed some records and then
        # closed the pipe. Treating that EOF as normal completion
        # returns a PARTIAL stream and no error, which is the exact
        # silent truncation this codebase rejects everywhere else (the
        # map cleanroom path has checked its status since W-CR1; this
        # one did not).
        #
        # So reap the launcher here and judge its status BEFORE
        # declaring the stream finished. Raising from the finally below
        # would mask the real error and double-wait the child, hence the
        # explicit waitpid here and finished=1 (which tells the finally
        # the child is already reaped).
        if launch_status is not None:
            # posix_spawn raised: no child exists, so judge the synthesised
            # exit-127 through the SAME classification the reaped-child path
            # uses. That preserves the STREAMING route's truncation error
            # instead of a materialized-route message.
            lstatus = launch_status
        elif launch_pid is not None:
            _lp, lstatus = os.waitpid(launch_pid, 0)
            launch_pid = None
        if lstatus is not None and not (os.WIFEXITED(lstatus)
                                        and os.WEXITSTATUS(lstatus) == 0):
            # A PRE-INGESTION decline is categorically different from
            # a failed run, and this function used to treat them the
            # same. It raised on every nonzero exit because for the
            # failures that class covers, records WERE yielded first
            # and a partial stream must not look complete.
            #
            # But a refusal decided before the spill child is forked
            # produced NO records, so "TRUNCATED" is false and raising
            # loses a recoverable situation for no safety gain. The
            # launcher's own classification answers which is which --
            # the same one the map path has used since W-CR1, which
            # is why this is a shared decision and not a second
            # opinion formed at the stream call site.
            _lc, _ls, _ll, _lpre = _decode_launcher_status(lstatus)
            if _lpre and not _fallback_forbidden(lstatus):
                if _lc in _CR_COMPAT_REFUSALS:
                    raise _CleanroomCompatRefusal(
                        _ll, "", _CR_COMPAT_REFUSALS[_lc], code=_lc)
                raise _CleanroomPreIngestDecline(
                    "cleanroom launcher declined before ingestion "
                    "(%s)" % (_describe_launcher_failure(lstatus),))
            raise RuntimeError(
                "forkrun: cleanroom launcher failed (%s); the "
                "stream is TRUNCATED and the records already yielded "
                "are incomplete"
                % (_describe_launcher_failure(lstatus),))
        # DECISION-02: consume the poison count ONLY now, and ONLY
        # after a confirmed-clean exit.
        #
        # The ordering is the safety property. A launcher that failed
        # may have written a partial or absent count, and reading it
        # anyway would report "0 poisoned" for a run that died -- i.e.
        # it would disguise a failure as a clean stream. Reading it
        # after the status check means the two facts stay independent.
        # _read_cleanroom_stats returns (poisoned, poisoned_batches,
        # truncated) -- a tuple, not a mapping.
        stats = _read_cleanroom_stats(stats_fd)
        if stats is not None:
            npois, batch_idx, _trunc = stats
            _LAST_STATS["poisoned"] = npois
            _LAST_STATS["poisoned_batches"] = list(batch_idx or [])
            _LAST_STATS["poisoned_batches_truncated"] = _trunc
        else:
            npois = 0
        if npois and strict_poison:
            raise RuntimeError(
                "forkrun: %d poisoned batch(es) skipped in a "
                "streaming run and strict_poison=True" % (npois,))
        finished = True
    finally:
        # Descriptor ownership: the decorator's close_all() runs when this
        # generator exits -- on completion, on any raise, and on
        # abandonment (GeneratorExit) -- so rr and stats_fd are released on
        # every path without a close statement per exit.
        #
        # Closing the parent's copies here cannot disturb a running child:
        # after fork the two processes hold SEPARATE descriptor-table
        # entries pointing at one shared open file description, so the
        # child keeps its own reference and its writes still land. The
        # stats read has already happened on every non-raising path.
        #
        # The child is killed BEFORE that close matters, because a child
        # still blocked writing into a pipe whose read end just closed
        # would otherwise linger until the pipe teardown below.
        for pid in (launch_pid,):
            if pid is None:
                continue
            try:
                if not finished:
                    os.kill(pid, 9)
                os.waitpid(pid, 0)
            except OSError:
                pass


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
# state. The lock makes concurrent invocations SEQUENTIALLY correct --
# two forkrun calls from two threads are safe because one waits. It does
# NOT make forking safe in general: an unrelated application thread can
# still hold a lock at fork time. See _warn_threaded_fork. One lock for
# the whole pipeline: coarse, deterministic, v0-appropriate.
# W-REL2/R10: RLock, not Lock, so that cross-thread contenders serialize
# without deadlocking against the thread that owns the session.
#
# WO-ROI-1-R1 CORRECTED THIS. The original text said same-thread
# nesting "is legitimate and must re-enter instead of deadlocking". That
# was the reasoning that motivated a bare RLock, and it is exactly what
# made nesting possible -- and unsafe, because the engine is
# process-global. A bare RLock prevents a deadlock; it is not a safety
# property, and a re-entrant lock admits the second session happily.
# _RunLock now REFUSES same-thread re-entry before acquiring, so
# nesting raises instead of re-entering. See _RunLock.__enter__.
import threading as _threading

_THREAD_WARNED = []


def _warn_threaded_fork():
    """P0: fork() from a multi-threaded Python process is not safe.

    CPython warns at every os.fork() site (3.12+) because a lock held by
    a thread that does not exist in the child can never be released --
    the child then hangs before it reaches its exec or os._exit. This
    codebase forks 21 times (run.py 15, _reactor 3, _worker 2, plus the
    launcher), and the children run PYTHON between fork and exit, so the
    window is wide, not theoretical.

    _RUN_LOCK does NOT make this safe. It serialises forkrun calls
    against each other; it does nothing about an unrelated application
    thread that happened to hold the import lock, an allocator lock or
    a logging lock at the moment of the fork.

    Default is a warning, not an error: raising would break hosts that
    are working today, and the cleanroom's fork->exec is the narrowest
    case. Set FORKRUN_REQUIRE_SINGLE_THREADED=1 to make it fatal where
    a hang is worse than an error.

    Warns ONCE per process -- it fires on every run entry otherwise.
    """
    if _THREAD_WARNED:
        return
    import threading as _t
    if _t.active_count() <= 1:
        return
    _THREAD_WARNED.append(1)
    msg = (
        "forkrun: running in a multi-threaded Python process "
        "(%d threads). forkrun forks %d times and its children run "
        "Python before exec/_exit, so a lock held by another thread at "
        "fork time can deadlock the child. This is a known hazard, not a "
        "bug in your code. If this run hangs, that is the likely cause. "
        "Set FORKRUN_REQUIRE_SINGLE_THREADED=1 to refuse instead."
        % (_t.active_count(), 21))
    import os as _os
    if _os.environ.get("FORKRUN_REQUIRE_SINGLE_THREADED") == "1":
        raise RuntimeError(msg)
    import warnings as _w
    _w.warn(msg, RuntimeWarning, stacklevel=3)


class _RunLock:
    """_RUN_LOCK: one live engine session per process, enforced.

    THE INVARIANT
    -------------
    At most ONE engine session may be live at a time. The C engine's
    state is process-global (`g_state` / `state` in forkrun_ring.c), so a
    second session does not merely interleave work -- it REPLACES the
    first session's state. Specifically:

      * ring_init_main mmaps unconditionally and overwrites `g_state`,
        leaking the previous mapping;
      * ring_destroy_main munmaps it and sets both pointers to NULL.

    A nested run therefore returns its own correct results while
    DESTROYING its parent's ability to supervise or recover its workers.
    Measured: the enclosing run's fr_py_diag_node goes from rc=0 (live)
    to rc=-1 (no engine state) across a nested map(). The parent cannot
    then revert an orphan, so the run aborts with "Worker N recovery
    failed (orphan revert/escrow)".

    ENFORCEMENT
    -----------
    The lock is reentrant, which prevents a same-thread deadlock but is
    NOT a safety property -- a reentrant lock happily lets the second
    session in. So re-entry is REFUSED.

    This class is the single choke point: every stream() path returns
    through _guarded_gen, and every run()/map() branch takes the lock
    before dispatching, so checking here covers all entry points by
    construction rather than by remembering to check at each one.

      * different threads -> serialize (the RLock blocks), because
        engine globals are process-wide;
      * same thread, no live session -> acquire normally;
      * same thread, live session -> RuntimeError BEFORE acquiring, so
        the nested call cannot initialise or destroy anything.

    Every `with _RUN_LOCK:` site in this module is a sibling branch that
    returns immediately, so no internal path relies on re-entry. That was
    verified rather than assumed; see
    python/tests/test_stream_lock.py.
    """

    def __init__(self, lock):
        self._lock = lock
        # Per-thread session marker. A plain counter on self would be
        # wrong: it must record whether THIS thread is inside a session,
        # not how many threads are waiting.
        self._local = _threading.local()
        # WO-ROI-1-R1: a forked child inherits the parent's thread-local
        # state, so it inherits `active` too -- VERIFIED: a forked child
        # sees active=True. A worker that starts a nested run from its
        # payload therefore inherits the refusal.
        #
        # That refusal is the correct outcome, but it arrives by accident
        # and with a misleading message (it claims another run is live
        # "in this thread", when what actually happened is that this
        # PROCESS is a forked worker). So the inheritance is recorded
        # explicitly and the diagnostic is made accurate.
        #
        # The marker is deliberately NOT cleared in the child. Clearing it
        # would ADMIT worker-side nesting, and that is unsafe: the worker
        # is mid-batch on the inherited engine state, so a nested
        # _init_engine_and_fds would mmap over the mapping its own
        # ack path still depends on. Refusal is the safe contract, and the
        # smallest defensible one.
        try:
            os.register_at_fork(after_in_child=self._after_fork_child)
        except AttributeError:      # pragma: no cover - non-POSIX
            pass

    def _after_fork_child(self):
        # Runs in the child immediately after fork(). `active` is left
        # True deliberately -- see __init__.
        self._local.inherited_from_parent = True

    def _session_live(self):
        return getattr(self._local, "active", False)

    def __enter__(self):
        if self._session_live():
            # Refuse BEFORE acquiring. Acquiring first would succeed
            # (RLock) and the nested session would then reinitialise the
            # engine we are trying to protect.
            if getattr(self._local, "inherited_from_parent", False):
                raise RuntimeError(
                    "forkrun: refusing to start a nested run inside a "
                    "forkrun worker process. A worker inherits the "
                    "engine session of the run that created it, and is "
                    "mid-batch on that state, so a nested session would "
                    "replace the mapping its own completion path depends "
                    "on. Start the nested run from the parent instead -- "
                    "pass it as data, or use a separate process.")
            raise RuntimeError(
                "forkrun: refusing to start a nested run while another "
                "forkrun execution is live in this thread. The engine's "
                "state is process-global, so a nested session would "
                "replace the live one's state and leave the parent "
                "unable to supervise or recover its workers. Finish or "
                "close the active stream() before starting another run; "
                "runs in SEPARATE threads are still supported and are "
                "serialised.")
        self._lock.acquire()
        try:
            _warn_threaded_fork()
        except BaseException:
            self._lock.release()
            raise
        self._local.active = True
        return self._lock

    def __exit__(self, *exc):
        # Cleared BEFORE release so a session is never left marked live
        # by an exception unwinding through here -- a stuck marker would
        # make every later top-level run raise, which looks like the
        # library being broken rather than a leaked guard.
        self._local.active = False
        self._local.inherited_from_parent = False
        self._lock.release()
        return False

    def acquire(self, *a, **k):
        return self._lock.acquire(*a, **k)

    def release(self):
        return self._lock.release()


_RUN_LOCK = _RunLock(_threading.RLock())

# C0.7: how many forkrun runs are live in THIS process, counted across
# nested execution.
#
# WO-ROI-1-R1: the comment here used to say nesting "is permitted",
# because an RLock is reentrant. That described the pre-guard behaviour
# and is now WRONG: _RunLock refuses same-thread re-entry outright, so a
# map() inside a live stream() is rejected rather than admitted. The
# counter still exists because it is not redundant with the refusal --
# see below -- but it no longer relies on nesting being allowed.
#
# The certificate's expected side is a DELTA of a counter that belongs to
# the shared engine. That delta is only meaningful if no other producer
# committed during the interval. A baseline captured before this run's
# fork does not establish that: an outer stream's worker can commit
# after the baseline and before this run's final snapshot, and its frame
# would be charged to the inner run (measured: the inner run collected
# 24 while a global counter read 56).
#
# Rather than attempt producer quiescence -- which would mean suspending
# an outer run's live workers, mid-stream, around an unrelated call --
# a nested run simply REFUSES to certify. That is the fail-closed
# choice, and it is honest: no verdict beats a possibly-wrong one.
_C07_RUN_DEPTH = [0]

# C0.7: monotonically increasing count of runs STARTED in this process.
#
# Depth alone is not enough, because the exposure runs in BOTH
# directions. A nested run's delta is polluted by the enclosing run's
# live workers, which depth catches at start. But the ENCLOSING run's
# delta is polluted too: the nested run commits into the same engine
# between the enclosing run's baseline and its final snapshot, so the
# outer run is charged for the inner one's frames. Measured with a
# map() inside a payload: the outer run reported "collected 0, published
# 25" -- every one of the 25 being the inner run's.
#
# A run that sees this counter advance during its own lifetime knows
# that some other run committed inside its measurement window.
_C07_RUNS_STARTED = [0]

# C0.7 test hook state: the Nth DATA frame to drop on the observed side,
# read once from FORKRUN_C07_DROP_FRAME. 0 (the default) drops nothing.
# A list rather than a scalar so the walkers do not need `global`.
_C07_DROP = [None]
_C07_DROP_SEEN = [0]


def _init_engine_and_fds(*, lines, bytes_, spec, num_nodes=None,
                         numa_map=None):
    """W-DEDUP-INIT: snapshot -> load -> fr_py_init -> engine_fds.

    This four-step idiom was repeated verbatim at ten executor entry
    points in this file. Collapse it for correctness, not tidiness:
    `engine_fds` is the keep-set every child scrubs to, so a site that
    computed it differently would leak descriptors into that one path's
    workers and nowhere else -- a bug every other test in the suite would
    miss, because no other path is wrong.

    Returns (lib, engine_fds).
    """
    pre_fds = snapshot_fds()
    lib = load()
    if num_nodes is None:
        _core_init_engine(lib, lines=lines or 0, bytes_=bytes_ or 0,
                          spec=spec)
    else:
        _core_init_engine(lib, lines=lines or 0, bytes_=bytes_ or 0,
                          num_nodes=num_nodes, numa_map=numa_map, spec=spec)
    # Engine fds for child keep sets (W-PY16 addendum scrub).
    return lib, snapshot_fds() - pre_fds

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

    INVARIANTS.md §20: this fd's file offset is UNDEFINED — never
    read or relied upon by any consumer (all access is explicit-
    offset or mmap-windowed). The pre-fork lseek(0) below is belt
    only; correctness never depends on the position.

    W-PY18 addendum: kernel copy first (copy_file_range via
    fr_py_copy_range, explicit offsets — never touches fd positions),
    userspace pread/pwrite loop on -1 (exotic pairs) or shortfall.
    Either way the bytes are identical; only the copy count differs.
    """
    # W-REL5-E7: no tempfile fallback (os.memfd_create exists on all
    # supported Pythons, floor 3.10).
    memfd = os.memfd_create("forkrun_ingress")
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


def _new_output_memfds(n) -> tuple[list, list]:
    """Create one output memfd per worker, PRE-FORK (W-PY3 correction).

    A memfd created post-fork in the child exists only in the child's fd
    table — the parent could never read it. So the parent creates all N
    here; children inherit them across fork and write their own slice
    (worker i writes fd i only — never shared between workers). The
    parent preads them after waitpid.
    Returns (fds, hold) where hold is always empty (kept so callers
    unpack two values; W-REL5-E7 removed the tempfile fallback).
    """
    fds: list = []
    hold: list = []
    for i in range(n):
        fds.append(os.memfd_create("forkrun_out%d" % i))
    return fds, hold


def _resume_begin_after_init(lib, resume, *, order, mode, collect,
                             splice, source):
    """resume_begin, guaranteeing the pre-fork engine destroy on failure.

    resume_begin raises BEFORE the caller's try/finally is entered (it is
    pre-fork by design) but AFTER fr_py_init. So when it raises, the
    initialized engine is still live and nothing else owns tearing it
    down: without an explicit destroy it leaks into the next call in the
    same process. That was observed as total output loss on the
    following run, which is a spectacular way to learn the rule.

    No children or fds exist at this point, so a bare destroy is
    complete teardown.

    Four executors carried this try/except by hand. The invariant is
    exactly the kind that must not have four independent copies: the
    failure mode is a leak that only manifests on a LATER, unrelated
    call, so it is invisible in the test that provoked it.
    """
    try:
        return resume_begin(lib, resume, order=order, orchestrator=True,
                           mode=mode, collect=collect, splice=splice,
                           source=source)
    except BaseException:
        # W-REL6-3.4b
        try:
            lib.fr_py_destroy()
        except Exception:
            pass
        raise


def _watch_ingest_helpers(lib, *, fallow_pid, scan_pid, helpers,
                           scan_death_r, state, gate_issued):
    """Classify ingest helper deaths for one supervision step.

    Returns the (possibly advanced) ``scan_death_r`` for the caller to
    store back; raises on a fatal classification.

    Single source for the blocking and streaming ingest-reactor
    executors. Merging them FIXED a divergence rather than merely
    removing a copy: the streaming path was missing
    ``state.scan_death_r = -1``, which the blocking path sets precisely
    so the teardown-parked copy cannot hold a stale descriptor number
    after the real pipe has been consumed and its number recycled
    (W-REL2/R11). Exactly the "fixed one path, forgot the other" failure
    this duplication invites -- the comment explaining the rule existed
    only on the copy that had it.

    ``gate_issued`` is passed as a value because the two callers keep it
    under different names (a bool in one, a dict key in the other);
    normalising here is cheaper than unifying their state containers,
    which are genuinely per-executor.
    """
    from ._reactor import check_scanner_death

    # Fallow death (WNOHANG) is fatal; scanner state comes from its
    # death pipe with error classification. A clean scanner exit BEFORE
    # the gate is equally fatal (exit 0 is only reachable via the EOF
    # gate -- an early 0 means the tail it never saw is lost).
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
                "forkrun: ingest reaper failed (status %r)" % (st,))
    if scan_death_r is not None and helpers["scan_kind"] is None:
        kind, code = check_scanner_death(scan_pid, scan_death_r)
        if kind != "running":
            # Definitive: the pipe is consumed (closed inside) --
            # record and stop polling it.
            helpers["scan_kind"] = kind
            helpers["scan_code"] = code
            scan_death_r = None
            # Keep the teardown-parked copy in sync; a stale number must
            # never be closed after reuse (W-REL2/R11).
            state.scan_death_r = -1
            if kind == "error" or not gate_issued:
                lib.fr_py_abort()
                raise RuntimeError(
                    "forkrun: ingest scanner failed (status %r)" % (code,))
    return scan_death_r


def _watch_numa_pipeline(lib, pipe, helpers, num_nodes):
    """Classify NUMA helper deaths for one supervision step. Raises on fatal.

    Single source for the NUMA blocking and streaming executors, which
    carried byte-identical copies of this -- the only textual difference
    was a comment, which is the clearest possible evidence that the
    duplication was accidental.

    Deliberately split by KIND rather than by lifecycle: what a child
    death MEANS is a mechanic and lives here, while what the executor does
    next stays with the caller. That boundary is what lets two different
    lifecycles share it without growing a 14-argument helper -- `pipe`
    and `helpers` are already the per-executor state containers, so no
    shape-specific knowledge leaks through this signature.
    """
    # Fallow death (WNOHANG) is fatal; indexer/scanner/ingest
    # deaths classify via their death pipes. Error kinds
    # raise at once. A clean indexer/scanner exit keys on
    # ingest EOF POSTED (fr_py_ingest_eof_posted -- the same
    # sentinel the indexers watch), NOT on ingest process
    # exit: the ingest routinely outlives its helpers (it
    # flushes on chunk_done before exiting), so
    # exit-ordering alone cannot tell normal teardown
    # ("helper done after EOF posted, ingest still
    # flushing") from tail loss ("helper done before EOF
    # was even posted" -- fatal).
    #
    # Imported here, not at module scope, for the same reason every
    # executor imports it locally: _reactor resolves run.py-owned
    # symbols lazily, so a top-level import would close the cycle. This
    # keeps the helper usable from both NUMA lifecycles without either
    # of them having to pass it in -- a parameter here would have been
    # the fourth argument that exists only to work around an import
    # cycle.
    from ._reactor import check_scanner_death

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
    _poll_ingest_once(lib, helpers, pipe)
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
            # D-PORT2/D6: query the abort reason BEFORE our
            # own abort — an abort already in flight makes
            # this death an expected emergency exit, not a
            # fatal one (re-aborting would print a spurious
            # FATAL and clobber the abort's own outcome).
            disp = _helper_death_disposition(
                kind, bool(eof_posted),
                _abort_reason_now(lib))
            helpers[key][node] = (kind, code)
            deaths[node] = None
            if disp != "fatal":
                if disp == "excuse":
                    helpers.setdefault(
                        "excused", set()).add((key, node))
                continue
            lib.fr_py_abort()
            raise RuntimeError(
                "forkrun: NUMA %s %d failed "
                "(status %r)" % (key, node, code))


def _fork_workers_for_node(state, assignments, node, forked):
    """Spawn every worker assigned to `node`. Returns nothing.

    The node -> worker mapping is the part that must not diverge between
    the blocking and streaming NUMA executors: a fix applied to one and
    not the other shows up only as a NUMA-specific hang or a wrong
    worker count. The two closures this replaces differed ONLY in which
    assignment list they read (`wid_node` vs `stream_wid_node`) and in
    trailing bookkeeping their owners needed, so both are now
    parameters/return-free and the lifecycle step stays with the caller.
    """
    for wid, nd in enumerate(assignments):
        if nd == node:
            state.spawn_worker(wid=wid, node=node)
    forked.add(node)


def _retire_parent_signal(signal_w, state, spare_signal_w):
    """Retire the parent's copy of the worker-signal pipe. Returns the
    new value for the caller's ``signal_w`` (always None).

    Workers -- those present now and any future respawn via the spare --
    each hold a write end, so the parent's own copy must go or the drain
    never sees EOF. The spare is installed into the reactor state at the
    same moment so a respawn has a write end to hand out.

    Returning the new value rather than using ``nonlocal`` is what makes
    this shareable: the two copies this replaces were closures over
    different enclosing scopes, which is the only reason they were ever
    separate functions.

    WHY signal_w MUST become None (W-PY21-A erratum, kept here because
    this is the one copy of the rule that explains it): if it kept the
    old integer, every later _fork_node would close the same descriptor
    NUMBER again. The results pipe later recycles that number, so the
    second close kills the pump's read end and the run hangs with data
    ready but unread -- a use-after-close that presents as a deadlock,
    which is why it was so expensive to find.
    """
    if signal_w is not None:
        try:
            os.close(signal_w)
        except OSError:
            pass
        signal_w = None
    state.ctx["signal_w"] = spare_signal_w
    return signal_w


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


def _map_collect(lib, fd, size):
    """memoryview over a read-only mapping of a whole result stream.

    W-PYZEROCOPY. Returns None if the stream cannot be mapped, so the
    caller can fall back to reading it.

    The mapping is owned by a ctypes array wrapped in weakref.finalize:
    every memoryview slice references the array, and the finalizer
    unmaps when the array dies. That ordering is the whole safety
    argument -- reading a record after munmap is SIGSEGV, not an
    exception, so the unmap must be strictly later than every slice.
    The finalizer's arguments are addresses and a length only; nothing
    in them can keep the array alive.
    """
    addr = ctypes.c_uint64(0)
    try:
        rc = lib.fr_py_map_readonly(fd, size, ctypes.byref(addr))
    except Exception:                                    # noqa: BLE001
        return None
    if rc != 0 or not addr.value:
        return None
    try:
        # c_ubyte, NOT c_char: c_char yields a memoryview of format
        # '<c', and CPython refuses to compare that against bytes
        # (`view == b"..."` is False). c_ubyte gives format 'B', which
        # compares equal in both directions -- found by writing the
        # buffer-operation tests, not by reading the docs. `in` still
        # raises NotImplementedError for any memoryview; that one is
        # CPython's and callers use forkrun.materialize().
        arr = (ctypes.c_ubyte * int(size)).from_address(addr.value)
    except BaseException:                                # noqa: BLE001
        try:
            lib.fr_py_unmap(addr.value, size)
        except Exception:                                # noqa: BLE001
            pass
        raise
    try:
        weakref.finalize(arr, lib.fr_py_unmap, addr.value, size)
    except BaseException:                                # noqa: BLE001
        # No finalizer available: unmap eagerly rather than leak.
        try:
            lib.fr_py_unmap(addr.value, size)
        except Exception:                                # noqa: BLE001
            pass
        return None
    return memoryview(arr)


def _prepare_ingest_source(src_fd, must_close):
    """Take ownership of an ingest source fd. ONE site, every executor.

    Two things have to happen before ANY executor spills a source, and
    both are easy to forget at an individual call site -- which is
    exactly what happened: the reactor ingest executor resized the pipe
    and the fail-fast and stream ones did not, so the same `cat file |`
    ran 16x the spill syscalls on two of three paths.

      1. Dup the fd. We never mutate flags on a descriptor we do not
         own.
      2. W-PYINGESTPIPE: a read() from a PIPE returns at most what the
         pipe buffer holds, however much was requested. With the 64 KiB
         default against a 1 MiB _CHUNK, a streamed source spills in
         64 KiB writes -- 16x the syscall count of the same bytes read
         from a file, where read() returns the full request.

    Both Bash ingest paths already do (2) on S_ISFIFO --
    forkrun_ring.c ring_copy_main (UMA) and ring_numa_ingest_main
    (NUMA) -- so this is parity, not tuning.

    Returns (fd, must_close). Resize failure is not an error: a
    non-FIFO source, a capped fs.pipe-max-size, or EPERM all just leave
    the size alone.
    """
    if not must_close:
        src_fd = os.dup(src_fd)
        must_close = True
    try:
        _fcntl.fcntl(src_fd, _fcntl.F_SETPIPE_SZ, _INGEST_PIPE_SZ)
    except OSError:
        pass
    return src_fd, must_close


def _ingest_copy_loop(src_fd, mem_fd, chunk=_CHUNK, lib=None):
    """Copy a source stream into the ingress memfd until EOF.

    The single implementation of "read the source, spill to ingress"
    for the UMA streaming path. It BLOCKS on the source by design: the
    caller runs it in a forked ingest child (mirroring bash, which
    backgrounds `ring_copy ... &` on UMA as well as NUMA) so the parent
    is free to run the reactor instead of interleaving a copy with it.

    Returns bytes written. Raises RuntimeError on a read or write
    failure -- the child's exit status is the parent's only signal, so
    the message has to survive in the status, not just in a traceback.

    W-PREFLIGHT: after each chunk lands, tell the engine that more
    bytes are available (``fr_py_ingest_data_post``). The pre-flight
    scan blocks on that eventfd rather than spin-sleeping while it waits
    for the ingest to catch up. This mirrors ring_copy_main, which
    signals evfd_ingest_data per chunk for bash. Best-effort: a missing
    or failing signal just leaves the pre-flight on its 50 ms timeout.
    """
    total = 0
    while True:
        try:
            buf = os.read(src_fd, chunk)
        except OSError as exc:
            raise RuntimeError("failed reading source: %s" % (exc,))
        if not buf:
            return total
        view = memoryview(buf)
        while view:
            try:
                n = os.pwrite(mem_fd, view, total)
            except OSError as exc:
                raise RuntimeError("failed writing ingress: %s" % (exc,))
            view = view[n:]
            total += n
        if lib is not None:
            try:
                lib.fr_py_ingest_data_post()
            except Exception:
                pass  # advisory only; never fail the copy over it


def _iter_records(lib, fd, _chunk=_CHUNK, views=False):
    """Yield (batch_idx, payload) from a framed stream, incrementally.

    W-PYCOLLECT: equivalent to iterating
    ``_parse_records(_read_fd_all(fd))`` but without materialising the
    stream twice. The collect paths used to buffer every chunk in a list
    and then b"".join them -- a second full copy of the entire result
    stream -- before parsing anything. On a 386MB in / 386MB out ordered
    run that join alone measured 155ms of a 638ms run (24%).

    ``views=True`` returns memoryview slices instead of bytes
    (W-PYZEROCOPY), which removes the remaining per-record copy.

    Why a mapping made in C rather than ``mmap.mmap(fd, ...)``:
    ``mmap.mmap`` dups the descriptor, and that dup is released only
    when the mmap is collected -- which, with views outstanding, is
    whenever the CALLER drops the records. Holding a result list
    therefore holds an extra fd for the life of the list, which is
    exactly what test_concurrent's fd-stability gate (and test_v1_fast's
    child fd hygiene) forbid. ``_map_collect`` calls mmap in the shim
    and keeps no descriptor at all, so a view costs zero fds.

    Three tiers, in order: a ``PROT_READ``/``MAP_SHARED`` mapping (no
    kernel copy, slicing is free); failing that, one pread of the whole
    stream into a single bytes object, sliced (one kernel copy for the
    whole run instead of one per record); failing that, the chunked
    read below, which also yields views so the result TYPE never depends
    on whether the stream happened to be mappable. Measured at 10 GB /
    7.44M records, views are 2.0-2.3x faster than bytes end to end.

    Lifetime: the mapping is unmapped by a ``weakref.finalize`` attached
    to the ctypes array each memoryview references, so the mapping
    cannot be torn down while any view is reachable. That also means the
    mapped file must not be truncated underneath us; SIGBUS on
    truncation is documented, not handled.

    ``_chunk`` grows to fit a single record that exceeds it, so a record
    larger than the chunk is read once rather than re-parsed on every
    subsequent read.

    A trailing partial record is dropped, matching _parse_records (a
    short tail means an internal inconsistency, not user data -- waitpid
    failure raises before this point).
    """
    # Map the whole stream when we can, in BOTH modes. For views this
    # is the whole point: zero kernel->user copies, so slicing is free.
    # For output="bytes" it still saves one full pass -- the old bytes
    # path pread the entire stream into a buffer (kernel->user) and
    # THEN copied each record out of it, i.e. two passes over the data
    # where one will do. Mapping and copying per record is one.
    #
    # Falls back to a pread of the whole stream, then to chunked reads,
    # so the result type never depends on whether the fd turned out to
    # be mappable.
    try:
        size = os.fstat(fd).st_size
    except OSError:
        size = 0
    if size > 0:
        mv = _map_collect(lib, fd, size) if lib is not None else None
        if mv is not None:
            recs, _tail = _split_records_views(mv)
            for idx, rec in recs:
                # recs are (batch_idx, payload); only the payload differs
                # between modes.
                yield (idx, rec) if views else (idx, bytes(rec))
            return
        if views:
            data = b""
            got = 0
            while got < size:
                try:
                    chunk = os.pread(fd, size - got, got)
                except OSError:
                    break
                if not chunk:
                    break
                data += chunk
                got += len(chunk)
            if data:
                records, _ = _split_records_views(data)
                for rec in records:
                    yield rec
            return
    try:
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError:
        pass
    tail = b""
    while True:
        try:
            chunk = os.read(fd, _chunk)
        except OSError:
            break
        if not chunk:
            break
        buf = tail + chunk if tail else chunk
        records, tail = (_split_records_views(buf) if views
                         else _split_records(buf))
        for rec in records:
            yield rec
        if tail and len(tail) >= _chunk:
            # One record is bigger than the read size: grow to hold it
            # whole so the next pass can complete it in a single parse.
            _chunk = len(tail) + _CHUNK


# C0.7 frame accounting.
#
# The framer ALREADY walks every complete frame; it simply does not count
# the ones it then filters (non-DATA dispositions, which include the
# EOF sentinel and any NO_RESULT/SKIPPED/POISONED control record).
# Counting here -- after a complete frame has been read and validated,
# BEFORE the disposition filter -- measures exactly the quantity the
# certificate needs, with no engine change.
#
# Named frames, not records: "records" is what the collector YIELDS, and
# that is the quantity that differs from the ring's published slots.
# "complete" counts EVERY complete frame, including the non-DATA
# dispositions the collector filters, so it is NOT the observed side of
# the certificate. "data_frames" is the DATA-only count: complete, valid
# FR_DISP_DATA frames actually accepted. A zero-length DATA result still
# counts as one frame -- it IS a frame, and counting it as zero would
# make a legitimate b"" look like a lost frame.
_FRAME_STATS = {"complete": 0, "filtered": 0, "data_frames": 0}

# C0.7 expected-side. fr_py_diag_node answers only while the ring state is
# live, so the published-slot total has to be captured DURING the run --
# a probe after map() returns reads zeros. Recorded here purely as
# telemetry so the correspondence sweep can compare the two sides.
_PUBLISHED_SLOTS = {"total": None, "nodes": 0}

# C0.7 expected-side, captured DURING the run for the same reason as the
# published-slot total above: fr_py_committed_data_frames answers only
# while the ring state is live, so a probe after map() returns reads
# nothing. The certificate itself reads it inline, where the engine is
# still up; this copy exists so tools and tests can compare the two
# sides after the fact, the way c07_correspondence_sweep does.
_COMMITTED_FRAMES = {"total": None, "nodes": 0}


def reset_frame_stats():
    _FRAME_STATS["complete"] = 0
    _FRAME_STATS["filtered"] = 0
    _FRAME_STATS["data_frames"] = 0
    _PUBLISHED_SLOTS["total"] = None
    _PUBLISHED_SLOTS["nodes"] = 0
    _COMMITTED_FRAMES["total"] = None
    _COMMITTED_FRAMES["nodes"] = 0


def frame_stats():
    return dict(_FRAME_STATS)


def published_slots():
    return dict(_PUBLISHED_SLOTS)


def committed_frames():
    """Committed DATA frames for the most recent run (C0.7 telemetry)."""
    return dict(_COMMITTED_FRAMES)


def _split_records_views(blob):
    """_split_records, yielding memoryview slices instead of bytes.

    Identical framing walk and identical record boundaries; only the
    payload object differs. Used on the chunked-read fallback so the
    result type does not depend on whether the stream turned out to be
    mappable (W-PYZEROCOPY).
    """
    records = []
    off = 0
    n = len(blob)
    view = blob if isinstance(blob, memoryview) else memoryview(blob)
    # C0.7 TEST HOOK: drop the Nth DATA frame on the OBSERVED side, so it
    # was committed but never delivered -- the shape a completeness
    # certificate exists to catch.
    #
    # Deliberately on this side of the comparison. Dropping at emission
    # would drop the commit too, and both sides would fall together, which
    # is precisely the case the certificate must NOT flag.
    #
    # Test-only and inert unless the variable is set, matching the
    # existing FORKRUN_TEST_DIE_* convention in _shim.c. Read once and
    # cached, so the hot path pays one dict lookup.
    if _C07_DROP[0] is None:
        _C07_DROP[0] = int(os.environ.get("FORKRUN_C07_DROP_FRAME", "0") or 0)
        _C07_DROP_SEEN[0] = 0
    while True:
        rec_start = off
        if off + _HDR.size > n:
            break
        idx, ln, disp, _res = _HDR.unpack_from(view, off)
        off += _HDR.size
        if off + ln > n:
            off = rec_start
            break
        # DECISION-02: a NO_RESULT record is a control signal, not data.
        # It must NOT surface as an empty payload, or a UDF returning None
        # would hand map()'s caller a spurious b"" -- a new class of wrong
        # answer in exactly the place that decides what a call returns.
        if disp != _DISP_DATA:
            # A COMPLETE frame that carries a control disposition rather
            # than payload. Counted, because it occupied a published slot
            # and must be accounted for at the certificate boundary.
            _FRAME_STATS["complete"] += 1
            _FRAME_STATS["filtered"] += 1
            off += ln
            continue
        _FRAME_STATS["complete"] += 1
        # Counted against DATA frames specifically, not against
        # "complete": complete also counts the filtered control records,
        # so using it would skip the drop whenever a NO_RESULT preceded
        # the target -- making the hook silently unreliable.
        _C07_DROP_SEEN[0] += 1
        if _C07_DROP[0] and _C07_DROP_SEEN[0] == _C07_DROP[0]:
            # Committed, but never delivered. See the hook note above.
            _FRAME_STATS["data_frames"] += 1
            off += ln
            continue
        _FRAME_STATS["data_frames"] += 1
        records.append((idx, view[off:off + ln]))
        off += ln
    tail = view[off:]
    return records, (bytes(tail) if isinstance(blob, bytes) else tail)


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
        idx, ln, disp, _res = _HDR.unpack_from(blob, off)
        off += _HDR.size
        if off + ln > n:
            off = rec_start
            break
        # DECISION-02: NO_RESULT is a control signal, not data. Surfacing it
        # as an empty payload would hand map()'s caller a spurious b"" for
        # a UDF that returned None -- a new class of wrong answer in exactly
        # the place that decides what a call returns.
        if disp != _DISP_DATA:
            _FRAME_STATS["complete"] += 1
            _FRAME_STATS["filtered"] += 1
            off += ln
            continue
        _FRAME_STATS["complete"] += 1
        # Counted against DATA frames specifically, not against
        # "complete": complete also counts the filtered control records,
        # so using it would skip the drop whenever a NO_RESULT preceded
        # the target -- making the hook silently unreliable.
        _C07_DROP_SEEN[0] += 1
        if _C07_DROP[0] and _C07_DROP_SEEN[0] == _C07_DROP[0]:
            # Committed, but never delivered. See the hook note above.
            _FRAME_STATS["data_frames"] += 1
            off += ln
            continue
        _FRAME_STATS["data_frames"] += 1
        records.append((idx, blob[off:off + ln]))
        off += ln
    return records, blob[off:]


def _split_records_terminal(blob: bytes) -> tuple:
    """Split a record stream keeping EVERY record's disposition.

    Stage 1. ``_split_records`` drops every non-DATA record, which is
    correct for its callers (a map() caller must not receive a spurious
    b"" for a batch that produced nothing) but fatal for ordered
    reassembly: a NO_RESULT / SKIPPED / POISONED batch then looks
    identical to a batch that never answered, and the consumer waits on
    a hole that will never close.

    So this is a SEPARATE parser rather than a change to ``_split_records``.
    That function's filtering is load-bearing for several other callers,
    and altering it to keep control records would hand them payloads they
    are explicitly written not to see.

    Returns (records, tail) where records is [(batch_idx, disposition,
    payload)] and the tail is an incomplete header or short body, held
    back for the next chunk exactly as elsewhere.
    """
    records = []
    off = 0
    n = len(blob)
    while True:
        rec_start = off
        if off + _HDR.size > n:
            break
        idx, ln, disp, _res = _HDR.unpack_from(blob, off)
        off += _HDR.size
        if off + ln > n:
            off = rec_start
            break
        records.append((idx, disp, blob[off:off + ln]))
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
    bound = n // _HDR.size  # records are >= one header: always terminates
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


def _resolve_workers_numa(workers, num_nodes=1):
    """Resolve the effective worker count for a topology (W-NUMA2).

    Single normalization point for the F-NUMA2 guarantee: on
    multi-node topologies (`num_nodes > 1`) a pool smaller than the
    node count strands born-local rings (RESILIENCE §7.3.1), so the
    count is bumped to `num_nodes` with one UserWarning stating
    requested vs effective. UMA (`num_nodes == 1`, the default —
    callers that can only reach UMA executors omit it) never bumps.
    Idempotent: an already-effective count passes through silently,
    so downstream re-resolution never double-warns.
    """
    base = _resolve_workers(workers)
    if num_nodes is None:
        num_nodes = 1
    try:
        num_nodes = int(num_nodes)
    except (TypeError, ValueError):
        num_nodes = 1
    if num_nodes > 1 and base < num_nodes:
        import warnings as _warnings
        _warnings.warn(
            "forkrun: workers=%d raised to %d to cover %d NUMA "
            "nodes (an uncovered node's born-local ring is never "
            "claimed — pass workers>=nodes or nodes=1 for "
            "single-node work)" % (base, num_nodes, num_nodes),
            UserWarning, stacklevel=3)
        return num_nodes
    return base


def _udf_as_inprocess(fn):
    """Adapt a mode="udf" callable to the in-process UDF contract.

    THE TWO MODES DO NOT CALL USER CODE THE SAME WAY, which is why a bare
    fallback is not safe:

    * mode="udf" (embedded CPython in the launcher) hands the callable
      one ``bytes`` object -- fr_udf_call does PyBytes_FromStringAndSize
      -- and reads back ``bytes`` or None.
    * mode="python" hands it a ``forkrun._batch.Batch``, which carries
      offsets, line counts and metadata as well as the data.

    So without this adapter the "fallback" would silently change the
    contract: a UDF written for mode="udf" would be handed a Batch,
    ``b.upper()`` would raise AttributeError, every batch would retry
    and poison, and the caller would see an empty result with no error
    naming the cause. That failure was reproduced here before the
    adapter existed.

    The adapter restores the mode="udf" contract exactly: bytes in,
    bytes-or-None out. The Batch's own fields are discarded -- a mode="udf"
    callable has no way to observe them, and synthesising them would be a
    second, subtler contract change.
    """
    def _wrapped(batch):
        data = batch.data
        raw = bytes(data) if data is not None else b""
        out = fn(raw)
        return out            # bytes passes through; None means no result
    _wrapped.__name__ = getattr(fn, "__name__", "udf")
    _wrapped.__doc__ = getattr(fn, "__doc__", None)
    return _wrapped


def _coerce_payload(payload, mode, force_inprocess_udf=False):
    """Normalize the payload + mode for the engine path (W-PY8, eager).

    Returns (payload_fn, engine_mode). mode="spawn" wraps the command and
    mode="plugin" binds the C entry point; both normalize to "python"
    downstream — the spawn-ness/plugin-ness is fully encapsulated in the
    wrapper, so the claim/ack loop, emitter, and reassembly never branch
    on mode. Raises ValueError for shape mismatches eagerly, so stream()
    still validates on call.

    ``force_inprocess_udf`` overrides the helper-present branch for a
    single call whose helper the launcher has just declined. See the
    comment at that branch.
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
    if mode == "udf":
        if callable(payload):
            raise ValueError(
                "mode='udf' requires a 'module:attribute' string, not a "
                "callable.")
        # A helper for this minor is what makes the isolated in-launcher
        # interpreter possible. If it is not built, the call must STILL
        # work -- mode="udf" is not an error, and the documented
        # fallback is the in-process path, which runs the UDF in THIS
        # interpreter.
        #
        # This used to return ("udf") unconditionally and rely on the
        # ordinary executors to cope. They cannot: the reactor accepts
        # only "python" and "splice", so with no helper built (and the
        # cleanroom flag off, which is the default) the promise of a
        # fallback ended in
        #     NotImplementedError: v0 supports mode='python' only
        # A fallback that raises is not a fallback.
        #
        # The trade is isolation, not correctness: resolved here, the UDF
        # runs in the parent's interpreter instead of an isolated one.
        # Same "slower and correct beats fast and empty" doctrine the
        # cleanroom fallback already uses.
        # force_inprocess_udf is set when the launcher has positively
        # declined the helper for THIS call. Without it the check below
        # would consult helper_path() -- which still returns the file,
        # because the file is present and only the launcher knows it is
        # unusable -- and hand back an _UDFPayload for the ordinary
        # Python worker, which cannot execute it as a plain callable.
        if not force_inprocess_udf and _udf_helper_path() is not None:
            # Like mode="plugin", the spec is NOT resolved when the
            # cleanroom will serve it: importing the user's module in
            # this process would put their state into the parent that
            # forks every worker.
            return _make_udf_payload(payload), "udf"
        return _udf_as_inprocess(resolve_payload_parent(payload)), "python"
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
    if isinstance(payload, str):
        # W-REL6-3.1: resolve "pkg.mod:func" in the PARENT, before any
        # fork, so a child forked from a threaded host never imports
        # (frozen import locks in the child deadlock). The callable
        # crosses by fork inheritance like the callable form always
        # did; import errors surface here, loudly and early.
        payload = resolve_payload_parent(payload)
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


def run(payload: Any, source: Any, *, mode: Mode = "python",
        sink: Optional[Callable[..., Any]] = None, order: Order = "none",
        lines: Optional[int] = None, bytes: Optional[int] = None,
        workers: Optional[int] = None, nodes: Nodes = "auto",
        on_error: OnError = "retry", streaming: Optional[bool] = None,
        orchestrator: Optional[bool] = None, c_drain: Optional[bool] = None,
        resume: Optional[Any] = None,
        checkpoint_file: Optional[Any] = None,
        c_worker_loop: Optional[bool] = None, strict_poison: bool = False,
        signal_policy: Optional[str] = "default",
        output: str = "view") -> None:
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
    orchestrator: None (default) = W-PY19 reactor supervision
      (death pipes, bounded respawn, trap-ACK confirmation, C orderer
      for order="index") — worker death is recovered automatically.
      True = same as the default explicitly. False = legacy
      fork-and-wait fail-fast: a worker death raises RuntimeError.
      The reactor is additive: identical results, stronger fault
      tolerance.
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
    strict_poison: False (default) = poisoned batches warn and the
      run continues (Bash -E continuation semantics). True =
      raise ForkrunPoisonSkip (Bash exit 3) carrying the engine's
      poisoned count instead of returning partial output.
    signal_policy: "default" (default) = install no signal handlers
      (library non-invasive; Ctrl-C raises through as standard
      Python). "checkpoint" = install HUP/TERM handlers (+USR1
      under FORKRUN_PREEMPT_MODE=1) for the run: an operator
      signal aborts the engine, publishes any armed checkpoint,
      and raises ForkrunTerminated/ForkrunPreempted. Handlers are
      always restored afterwards.
    """
    _validate(payload, source, mode=mode, sink=sink, order=order,
              lines=lines, bytes_=bytes, workers=workers, nodes=nodes,
              on_error=on_error, streaming=streaming,
              resume=resume, checkpoint_file=checkpoint_file,
              strict_poison=strict_poison, signal_policy=signal_policy)
    if resume is not None or checkpoint_file is not None:
        raise RuntimeError(
            "run(): resume=/checkpoint_file= require a C-orderer-backed "
            "path (map()/stream() with orchestrator=True, "
            "order='index'); run() has no C orderer")
    orchestrator = _validate_orchestrator(orchestrator)
    if orchestrator is None:
        # W-REL1/R1 (ratified Option A): recovery is the default.
        # None rides the reactor; explicit False keeps fail-fast.
        orchestrator = True
    c_drain = _validate_c_drain(c_drain)
    if _validate_c_worker_loop(c_worker_loop):
        raise RuntimeError(
            "run(): c_worker_loop=True needs collection (the C loop "
            "always frames output records); use map()/stream()")
    if mode not in ("python", "spawn", "plugin", "splice"):
        raise NotImplementedError(
            "unknown mode %r" % (mode,))
    numa_map_str, num_nodes, node_cpus = _resolve_numa(nodes)

    # Single source of truth for the 4 UMA dispatch sites below; same
    # reasoning as map()'s bundle. run() differs from map() in exactly
    # two entries -- sink=sink and collect=False. order/mode are filled
    # in after the branch's _coerce_payload, which can change both.
    base = dict(
        sink=sink,
        workers=_resolve_workers_numa(workers, num_nodes),
        on_error=on_error, strict_poison=strict_poison,
        collect=False, c_drain=c_drain, views=output)

    if num_nodes > 1:
        _warn_cleanroom_multinode(num_nodes)
        # NUMA pipeline (ingest owns the source — files and pipes
        # uniformly; no materialized/streaming split here).
        _require_numa_symbol()
        payload, mode = _coerce_payload(payload, mode)
        if mode == "splice":
            raise ValueError(
                "mode='splice' produces output records — use map() or "
                "stream() (payload=None, bytes=N).")
        numa = dict(base, order=order, mode=mode,
                    numa_map=numa_map_str, num_nodes=num_nodes,
                    node_cpus=node_cpus)
        with _signal_guard(signal_policy) as _sg:
            with _RUN_LOCK:
                _execute_numa_locked(
                    payload, source, lines=lines, bytes_=bytes, **numa)
            _sg.check()
        return None
    nodes = 1
    payload, mode = _coerce_payload(payload, mode)
    if mode == "splice":
        raise ValueError(
            "mode='splice' produces output records — use map() or "
            "stream() (payload=None, bytes=N).")
    base["order"] = order
    base["mode"] = mode

    if _detect_streaming(source, streaming):
        if orchestrator:
            with _signal_guard(signal_policy) as _sg:
                with _RUN_LOCK:
                    _execute_ingest_reactor_locked(
                        payload, source, lines=lines, bytes_=bytes,
                        nodes=nodes, **base)
                _sg.check()
            return None
        with _signal_guard(signal_policy) as _sg:
            _execute_ingest(payload, source, lines=lines, bytes_=bytes,
                            nodes=nodes, **base)
            _sg.check()
        return None
    if orchestrator:
        with _signal_guard(signal_policy) as _sg:
            with _RUN_LOCK:
                _execute_reactor_locked(
                    payload, source, lines=lines, bytes_=bytes,
                    nodes=nodes, **base)
            _sg.check()
        return None
    with _signal_guard(signal_policy) as _sg:
        _execute(payload, source, lines=lines, bytes_=bytes, **base)
        _sg.check()
    return None


def map(payload: Any, source: Any, **kwargs: Any) -> List[bytes]:
    """Batch-granular map: payload(Batch) -> result per batch.

    ORDER: the default is order="none" -- worker-completion order, no
    reassembly. order="index" restores input order via the C orderer.
    (The docstring here used to claim results were "ordered by
    batch_index" unconditionally, which contradicted both the default and
    docs/API.md. It described the order="index" case as if it were the
    only one.)

    v0 collects parent-side after workers exit (not streaming).

    mode="splice": kernel passthrough (payload must be None) — each
      result blob is one input byte-window (bytes=N, default 512KB).

    orchestrator=True: W-PY19 reactor supervision (death pipes,
      bounded respawn, trap-ACK, C orderer for order="index").
      Default None rides the reactor (same as True); False selects
      legacy fork-and-wait fail-fast (worker death raises
      RuntimeError).

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
      the reactor path (the default; orchestrator=False rejects),
      order="index", UMA single-node, non-splice
      (C-orderer path); anything else raises RuntimeError loudly.
      Engine commit is exactly-once; Python consumption is not
      (persist consumed results yourself for end-to-end exactly-once).

    strict_poison: False (default) = poisoned batches warn and map
      returns partial output (Bash -E continuation semantics).
      True = raise ForkrunPoisonSkip (Bash exit 3) carrying the
      engine's poisoned count instead.

    sink= is rejected (W-REL5-B1): map() collects results — the
      payload return value IS the result. A worker-side sink lives
      only on run(). Unknown keyword arguments are likewise
      rejected (TypeError) instead of silently running.

    return_stats=False (default) returns the bare list[bytes].
      True returns (list[bytes], stats) where stats is
      {"total", "completed", "poisoned", "poisoned_batches",
       "poisoned_batches_truncated"} --
      total = completed + poisoned, poisoned_batches sorted batch
      indices (see forkrun.last_run_stats for the caveats).

      The cleanroom serves BOTH the scalars and the index list. The
      launcher relays each poisoned batch index out of the worker on a
      per-worker slot of the stats memfd (see fr_py_poison_relay), so
      `len(poisoned_batches) == poisoned` holds on the cleanroom path
      exactly as it does in process. The slot is BOUNDED (1024 indices
      per worker); a run that poisons more than that in one worker keeps
      the correct COUNT and reports a truncated list, which is the
      degradation direction that cannot make a number look better than
      it is. When that happens map() warns and sets
      poisoned_batches_truncated=True, so a caller never has to guess
      whether len(poisoned_batches) means "all of them". The count is
      always exact.
    """
    if kwargs.get("sink") is not None:
        raise ValueError(
            "map() collects results — sink= is not accepted (the "
            "payload return value is the result; use run() for a "
            "worker-side sink)")
    # W-REL6-3.6: popped before the whitelist (map-only option;
    # stream()/sweep() still reject it as unknown).
    return_stats = kwargs.pop("return_stats", False)
    if not isinstance(return_stats, bool):
        raise TypeError(
            "return_stats must be True or False, got %r"
            % (return_stats,))
    _reset_stats()  # W-REL6-3.6: fresh accounting for this call
    _reject_unknown_kwargs("map()", kwargs)
    mode = kwargs.get("mode", "python")
    nodes = kwargs.get("nodes", "auto")
    _validate(payload, source, mode=mode, sink=None,
              order=kwargs.get("order", "none"), lines=kwargs.get("lines"),
              bytes_=kwargs.get("bytes"), workers=kwargs.get("workers"),
              nodes=nodes, on_error=kwargs.get("on_error", "retry"),
              streaming=kwargs.get("streaming"),
              resume=kwargs.get("resume"),
              checkpoint_file=kwargs.get("checkpoint_file"),
               strict_poison=kwargs.get("strict_poison", False),
               signal_policy=kwargs.get("signal_policy", "default"))
    orchestrator = _validate_orchestrator(kwargs.get("orchestrator"))
    if orchestrator is None:
        # W-REL1/R1 (ratified Option A): recovery is the default.
        orchestrator = True
    c_drain = _validate_c_drain(kwargs.get("c_drain"))
    output = _resolve_output(kwargs.get("output"))
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
    # Single source of truth for the 8 UMA executor dispatch sites below
    # (W-PYDISPATCH), plus the NUMA variant. They used to re-type the
    # same keywords by hand -- 99 hand-maintained keyword arguments in
    # one function. That is why output= had to be threaded by hand and
    # was silently dropped on the paths I missed: a forgotten site just
    # takes the callee's default and returns the wrong thing, no error.
    #
    # With **base, adding a parameter is ONE edit here, and a parameter
    # an executor does not accept raises TypeError at that site rather
    # than being silently defaulted. Only genuinely per-path arguments
    # (lines/bytes_, splice, and the plugin/spawn/resume extras) stay
    # spelled out at the site.
    #
    # order/mode are set after the branch's _coerce_payload, which can
    # change both, so they are not baked in here.
    base = dict(
        sink=None,
        workers=_resolve_workers_numa(kwargs.get("workers"), num_nodes),
        on_error=kwargs.get("on_error", "retry"),
        strict_poison=kwargs.get("strict_poison", False),
        collect=True, c_drain=c_drain, views=output)

    if num_nodes > 1:
        _warn_cleanroom_multinode(num_nodes)
        _require_numa_symbol()
        payload, mode = _coerce_payload(payload, mode)
        order = kwargs.get("order", "none")
        if mode == "splice":
            _require_splice_symbol()
            b = kwargs.get("bytes") or _SPLICE_DEFAULT_BYTES
        else:
            b = kwargs.get("bytes")
        # Same bundle as the UMA sites, plus the three NUMA-only keys
        # (and without `nodes`, which the NUMA executor does not take).
        numa = dict(base, order=order, mode=mode,
                    numa_map=numa_map_str, num_nodes=num_nodes,
                    node_cpus=node_cpus, splice=(mode == "splice"))
        with _signal_guard(kwargs.get("signal_policy", "default")) as _sg:
            with _RUN_LOCK:
                out = _execute_numa_locked(
                    payload, source,
                    lines=kwargs.get("lines"), bytes_=b, **numa)
            _sg.check()
            return _map_return(out, return_stats)
    nodes = 1
    # W-CR1: keep the RAW mode and payload. _coerce_payload normalizes
    # "plugin" -> "python" (plugin-ness rides the payload marker, not the
    # mode) and replaces the "path:function" string with a closure, so
    # both are gone by the time the hook below runs. Gating on the
    # coerced values is not hypothetical: an earlier cut did exactly
    # that, was dead code, and its smoke test still passed because BOTH
    # flag settings quietly ran the in-process path.
    raw_mode = mode
    raw_payload = payload
    order = kwargs.get("order", "none")
    # Initialised BEFORE any branch that may report a reason. The
    # decline warning below interpolates it, and the condition that
    # selects it (_cleanroom_enabled() and a launcher-served mode) can be
    # False while the warning branch is still reached -- e.g. spawn with
    # FORKRUN_CLEANROOM=1 -- which raised UnboundLocalError instead of
    # declining cleanly.
    _why = "mode=%r is not a launcher-served envelope" % (raw_mode,)
    if raw_mode == "udf":
        _warn_if_cached_incompatible()
    # WO-CR-ROI-2 Phase C: the route gate narrows which envelopes the
    # environment enables. It is consulted with the RAW mode and the
    # entry point, before _coerce_payload rewrites plugin->python, so the
    # identifier reflects what the caller asked for.
    if (_cleanroom_enabled()
            and _cleanroom_route_enabled("map", raw_mode)):
        _ok, _why = _cleanroom_eligible(
            source, raw_mode, num_nodes, order,
            kwargs.get("strict_poison", False), orchestrator,
            bool(return_stats),
            # CR-FIX1-K: these were not passed here, so the envelope could
            # not see them and a resume request was silently dropped.
            # The predicate is the single authority for the refusal; the
            # call sites only supply the facts.
            resume=kwargs.get("resume"),
            checkpoint_file=kwargs.get("checkpoint_file"))
        if _ok:
            # rpartition on the last colon, exactly as _coerce_payload
            # parses the spec. Deliberately NOT _c_plugin_spec(): that
            # only answers for a dialect-1/2 frozen-ABI plugin, which is
            # a constraint of the C *worker loop*.
            #
            # This dispatch sits ABOVE _coerce_payload on purpose (see
            # the note at the top of the block): coercing first would
            # build the ctypes payload and dlopen the plugin IN THIS
            # PROCESS, which both wastes the work -- the launcher
            # dlopens it again -- and is the fork hazard _plugin.py
            # itself warns about, for a plugin whose ELF initializers
            # start threads. The cleanroom exists to create workers after
            # a clean exec; loading the object beforehand in the large
            # Python parent quietly undid that.
            #
            # A plugin without forkrun_use_ctx is refused by the launcher
            # (see its dlopen probe); _cleanroom_eligible's docstring
            # covers why.
            #
            # A UDF needs its helper built for THIS minor; if it is not,
            # fall through to the in-process path rather than refusing --
            # slower and correct beats fast and missing.
            # Only plugin and udf carry a "path:function" spec. A spawn
            # payload is an ARGV LIST and has no rpartition, so parsing
            # it unconditionally raised AttributeError before the spawn
            # branch below could run.
            if raw_mode == "spawn":
                _p, _sep, _f = "", "", ""
            else:
                _p, _sep, _f = raw_payload.rpartition(":")
            _udf_args = {}
            if raw_mode == "udf" and _p and _f:
                # Helper missing for this minor -> fall through to the
                # in-process path. Slower and correct beats fast and
                # missing, and an absent build artifact is not a reason
                # to fail the caller's program.
                _helper = _udf_helper_path()
                if _helper:
                    _udf_args = {
                        "udf_helper": _helper,
                        "udf_module": _p,
                        "udf_attr": _f,
                        "udf_roots": _udf_roots_spec(_p),
                    }
            if raw_mode == "spawn":
                # Stage 3: spawn carries an ARGV VECTOR, not a
                # path:function plugin spec. It cannot share the branch
                # below, which rpartitions a string and passes two
                # strings to the launcher. The argv is extracted from the
                # coerced payload's tagged wrapper and validated BEFORE
                # the launcher starts and before the source is read, so a
                # malformed command costs no input.
                from ._worker import _c_spawn_spec as _spawn_argv_of
                _coerced, _coerced_mode = _coerce_payload(
                    raw_payload, "spawn")
                # _coerce_payload returns (payload_fn, engine_mode) and
                # _c_spawn_spec reads the argv off the FUNCTION's tag.
                # Passing the TUPLE made getattr() return None, so _sargv
                # was falsy, the whole launcher branch below was dead
                # code, and every public map(mode="spawn") call quietly
                # fell through to the in-process executor -- while
                # test_map_spawn_routes_through_the_launcher passed,
                # because it could only check that the OUTPUT was right.
                _sargv = _spawn_argv_of(_coerced)
                if _sargv:
                    _sargv = _validate_spawn_argv(_sargv)
                    with _signal_guard(
                            kwargs.get("signal_policy",
                                       "default")) as _sg:
                        with _RUN_LOCK:
                            out, _ip_p, _ip_m = _cleanroom_attempt(
                                lambda: _execute_cleanroom(
                                    source,
                                    lines=kwargs.get("lines"),
                                    bytes_=kwargs.get("bytes"),
                                    workers=base["workers"],
                                    plugin_path=None, plugin_func=None,
                                    on_error=kwargs.get("on_error", "retry"),
                                    views=base["views"],
                                    strict_poison=bool(
                                        kwargs.get("strict_poison", False)),
                                    order=order,
                                    orchestrator=orchestrator,
                                    spawn_argv=_sargv,
                                    **_udf_args),
                                payload, mode,
                                helper_fp=_helper_fingerprint(
                                    _udf_args.get("udf_helper")))
                    _sg.check()
                    if _ip_m is not None:
                        payload, mode = _ip_p, _ip_m
                    if out is not None:
                        return _map_return(out, return_stats)
            if raw_mode != "spawn" and _p and _f and (
                    raw_mode != "udf" or _udf_args):
                with _signal_guard(
                        kwargs.get("signal_policy", "default")) as _sg:
                    with _RUN_LOCK:
                        out, _ip_p, _ip_m = _cleanroom_attempt(
                            lambda: _execute_cleanroom(
                                source,
                                lines=kwargs.get("lines"),
                                bytes_=kwargs.get("bytes"),
                                workers=base["workers"],
                                plugin_path=_p, plugin_func=_f,
                                on_error=kwargs.get("on_error", "retry"),
                                views=base["views"],
                                strict_poison=bool(
                                    kwargs.get("strict_poison", False)),
                                order=order,
                                orchestrator=orchestrator,
                                **_udf_args),
                            payload, mode,
                            helper_fp=_helper_fingerprint(
                                _udf_args.get("udf_helper")))
                    _sg.check()
                if _ip_m is not None:
                    payload, mode = _ip_p, _ip_m
                if out is not None:
                    return _map_return(out, return_stats)
        elif _cleanroom_explicit():
            # Only warn when the user ASKED. The default is OFF, so
            # this branch is reachable only via an explicit
            # FORKRUN_CLEANROOM -- which is exactly when the user needs
            # to hear that the envelope could not be honoured.
            import warnings as _warnings
            _warnings.warn(
                "forkrun: requested cleanroom ignored for this call "
                "(%s) — using the in-process path. The launcher covers "
                "materialized file + C plugin + UMA + "
                "order in ('none', 'index')." % (_why,),
                UserWarning, stacklevel=3)

    payload, mode = _coerce_payload(payload, mode)

    base["order"] = order
    base["mode"] = mode

    if mode == "splice":
        _require_splice_symbol()
        b = kwargs.get("bytes") or _SPLICE_DEFAULT_BYTES
        if _detect_streaming(source, kwargs.get("streaming")):
            if orchestrator:
                with _signal_guard(kwargs.get("signal_policy", "default")) as _sg:
                    with _RUN_LOCK:
                        out = _execute_ingest_reactor_locked(
                            None, source,
                            lines=None, bytes_=b, nodes=nodes, splice=True,
                            **base)
                    _sg.check()
                    return _map_return(out, return_stats)
            with _signal_guard(kwargs.get("signal_policy", "default")) as _sg:
                out = _execute_ingest(
                    None, source,
                    lines=None, bytes_=b, nodes=nodes, splice=True,
                    **base)
                _sg.check()
                return _map_return(out, return_stats)
        if orchestrator:
            with _signal_guard(kwargs.get("signal_policy", "default")) as _sg:
                with _RUN_LOCK:
                    out = _execute_reactor_locked(
                        None, source,
                        lines=None, bytes_=b, nodes=nodes, splice=True,
                        **base)
                _sg.check()
                return _map_return(out, return_stats)
        with _signal_guard(kwargs.get("signal_policy", "default")) as _sg:
            out = _execute(
                None, source,
                lines=None, bytes_=b, nodes=nodes, splice=True,
                **base)
            _sg.check()
            return _map_return(out, return_stats)
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
            with _signal_guard(kwargs.get("signal_policy", "default")) as _sg:
                with _RUN_LOCK:
                    out = _execute_ingest_reactor_locked(
                        payload, source,
                        lines=kwargs.get("lines"),
                        bytes_=kwargs.get("bytes"), nodes=nodes,
                        resume=kwargs.get("resume"),
                        checkpoint_file=kwargs.get("checkpoint_file"),
                        **base)
                _sg.check()
                return _map_return(out, return_stats)
        with _signal_guard(kwargs.get("signal_policy", "default")) as _sg:
            out = _execute_ingest(
                payload, source,
                lines=kwargs.get("lines"),
                bytes_=kwargs.get("bytes"), nodes=nodes,
                **base)
            _sg.check()
            return _map_return(out, return_stats)
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
    # NOTE: named c_spawn_argv, not spawn_argv. A bare spawn_argv here
    # shadowed _execute_cleanroom's parameter of the same name for the
    # whole module scope of that call, so every cleanroom invocation
    # raised UnboundLocalError before reaching the launcher.
    c_spawn_argv = None
    if c_spawn_loop:
        # Coerced spawn payloads carry the argv list on the wrapper
        # (make_spawn_payload tags _forkrun_spawn_argv); the C loop
        # replays exactly this argv per batch (no shell).
        c_spawn_argv = _c_spawn_spec(payload)
        if c_spawn_argv is None:
            raise RuntimeError(
                "c_spawn_loop=True needs a spawn argv payload "
                "(mode='spawn') — use c_spawn_loop=False")

    # W-CR1: cleanroom (exec-based) launcher. Placed after every other
    # gate, so it only sees calls already known to be materialized, UMA
    # and plugin. Outside its envelope it WARNS and falls through to the
    # in-process path rather than raising: the in-process result is always
    # correct, and breaking a working map() call to advertise an
    # experimental accelerator is strictly worse. Not silent, though --
    # a user who set FORKRUN_CLEANROOM must learn they did not get it.
    if orchestrator:
        with _signal_guard(kwargs.get("signal_policy", "default")) as _sg:
            with _RUN_LOCK:
                out = _execute_reactor_locked(
                    payload, source,
                    lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
                    nodes=nodes,
                    resume=kwargs.get("resume"),
                    checkpoint_file=kwargs.get("checkpoint_file"),
                    c_worker_loop=c_worker_loop,
                    plugin_spec=plugin_spec,
                    c_spawn_loop=c_spawn_loop,
                    spawn_argv=c_spawn_argv,
                    **base)
            _sg.check()
            return _map_return(out, return_stats)
    with _signal_guard(kwargs.get("signal_policy", "default")) as _sg:
        results = _execute(
            payload, source,
            lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
            nodes=nodes,
            c_worker_loop=c_worker_loop,
            plugin_spec=plugin_spec,
            c_spawn_loop=c_spawn_loop,
            spawn_argv=c_spawn_argv,
            **base)
        _sg.check()
    return _map_return(results, return_stats)


def stream(payload: Any, source: Any, **kwargs: Any) -> Iterator[Any]:
    """Yield results as they arrive — TRUE v1 streaming.

    order="none" (default): worker-completion order (first-finished first).
    order="index": batch_idx sequence via parent-side reassembly (bounded
      out-of-order buffer; holes from poisoned batches flush sorted at
      EOF — brief head-of-line blocking behind a hole is inherent).

    Records are always bytes, even with output="view" (the map() and
    run() default): stream() drains records live from a results pipe or
    worker memfd as they arrive, so there is no finished collection file
    to map. Zero-copy is a map()-only property. output= is still
    accepted and validated so map/run/stream share one surface; it does
    not change what stream() yields.

    Validates eagerly (raises on call, before the first next()).

    orchestrator=True: W-PY19 reactor supervision (death pipes,
      bounded respawn, trap-ACK, C orderer for order="index").
      Default None rides the reactor (same as True); False selects
      legacy fail-fast. Resume needs the reactor path (the default).

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

    strict_poison: False (default) = poisoned batches warn and the
      stream yields partial output (Bash -E continuation semantics).
      True = raise ForkrunPoisonSkip (Bash exit 3) at exhaustion
      instead of returning normally.

    sink= is rejected (W-REL5-B1): stream() yields results — the
      payload return value IS the result. A worker-side sink lives
      only on run(). Unknown keyword arguments are likewise
      rejected (TypeError) instead of silently running.
    """
    if kwargs.get("sink") is not None:
        raise ValueError(
            "stream() yields results — sink= is not accepted (the "
            "payload return value is the result; use run() for a "
            "worker-side sink)")
    _reject_unknown_kwargs("stream()", kwargs)
    _validate(payload, source, mode=kwargs.get("mode", "python"),
              sink=None, order=kwargs.get("order", "none"),
              lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
              workers=kwargs.get("workers"),
              nodes=kwargs.get("nodes", "auto"),
              on_error=kwargs.get("on_error", "retry"),
              streaming=kwargs.get("streaming"),
              resume=kwargs.get("resume"),
              checkpoint_file=kwargs.get("checkpoint_file"),
               strict_poison=kwargs.get("strict_poison", False),
               signal_policy=kwargs.get("signal_policy", "default"))
    # W-CR3: keep RAW mode/payload. _coerce_payload normalizes plugin ->
    # python and replaces the "path:function" string with a closure, so
    # the cleanroom hook below needs the pre-coercion values.
    raw_mode = kwargs.get("mode", "python")
    raw_payload = payload
    orchestrator = _validate_orchestrator(kwargs.get("orchestrator"))
    if orchestrator is None:
        # W-REL1/R1 (ratified Option A): recovery is the default.
        orchestrator = True
    c_drain = _validate_c_drain(kwargs.get("c_drain"))
    # Validated for a consistent surface, but stream() yields bytes:
    # it drains records live out of a results pipe / worker memfd as
    # they arrive, and there is no collection file to map. Zero-copy
    # is a map()-only property (see _iter_records(views=True)).
    output = _resolve_output(kwargs.get("output"))
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
        _warn_cleanroom_multinode(num_nodes)
        _require_numa_symbol()
        payload, engine_mode = _coerce_payload(payload, kwargs.get(
            "mode", "python"))
        if engine_mode == "splice":
            _require_splice_symbol()
        return _guarded_gen(
            _signal_guard(kwargs.get("signal_policy", "default")),
            _numa_stream_gen(
            payload, source,
            lines=kwargs.get("lines"),
            bytes_=(kwargs.get("bytes") or _SPLICE_DEFAULT_BYTES
                    if engine_mode == "splice" else kwargs.get("bytes")),
            workers=_resolve_workers_numa(kwargs.get("workers"), num_nodes),
            on_error=kwargs.get("on_error", "retry"),
            strict_poison=kwargs.get("strict_poison", False),
            mode=engine_mode, order=kwargs.get("order", "none"),
            orchestrator=orchestrator, numa_map=numa_map_str,
            num_nodes=num_nodes, node_cpus=node_cpus,
            splice=(engine_mode == "splice"), c_drain=c_drain))
    payload, engine_mode = _coerce_payload(payload, kwargs.get("mode",
                                                               "python"))
    kwargs = dict(kwargs, mode=engine_mode)
    if engine_mode == "splice":
        _require_splice_symbol()
        b = kwargs.get("bytes") or _SPLICE_DEFAULT_BYTES
        if _detect_streaming(source, kwargs.get("streaming")):
            if orchestrator:
                return _guarded_gen(
                    _signal_guard(kwargs.get("signal_policy", "default")),
                    _splice_ingest_stream_reactor_gen(
                    source, bytes_=b,
                    workers=_resolve_workers_numa(kwargs.get("workers"), num_nodes),
                    on_error=kwargs.get("on_error", "retry"),
                    strict_poison=kwargs.get("strict_poison", False),
                    nodes=kwargs.get("nodes", "auto"),
                    order=kwargs.get("order", "none"),
                    c_drain=kwargs.get("c_drain", True)))
            return _guarded_gen(
                _signal_guard(kwargs.get("signal_policy", "default")),
                _splice_ingest_stream_gen(
                source, bytes_=b,
                workers=_resolve_workers_numa(kwargs.get("workers"), num_nodes),
                on_error=kwargs.get("on_error", "retry"),
                strict_poison=kwargs.get("strict_poison", False),
                nodes=kwargs.get("nodes", "auto"),
                order=kwargs.get("order", "none"),
                c_drain=kwargs.get("c_drain", True)))
        if orchestrator:
            return _guarded_gen(
                _signal_guard(kwargs.get("signal_policy", "default")),
                _splice_stream_reactor_gen(
                source, bytes_=b,
                workers=_resolve_workers_numa(kwargs.get("workers"), num_nodes),
                on_error=kwargs.get("on_error", "retry"),
                strict_poison=kwargs.get("strict_poison", False),
                nodes=kwargs.get("nodes", "auto"),
                order=kwargs.get("order", "none"),
                c_drain=kwargs.get("c_drain", True)))
        return _guarded_gen(
            _signal_guard(kwargs.get("signal_policy", "default")),
            _splice_stream_gen(
            source, bytes_=b,
            workers=_resolve_workers_numa(kwargs.get("workers"), num_nodes),
            on_error=kwargs.get("on_error", "retry"),
            strict_poison=kwargs.get("strict_poison", False),
            nodes=kwargs.get("nodes", "auto"),
            order=kwargs.get("order", "none"),
            c_drain=kwargs.get("c_drain", True)))
    if _detect_streaming(source, kwargs.get("streaming")):
        # W-CR3: cleanroom streaming, gated by the SAME predicate map()
        # uses. This used to be a second hand-written condition here, and
        # the two had already drifted (it wanted `not orchestrator` where
        # the envelope wanted it, and it excluded order="index" where the
        # envelope serves it). One predicate, one answer.
        #
        # Falls through QUIETLY when ineligible: the default is OFF, so
        # an unserved call is the overwhelmingly common case and
        # warning on each would be noise. An explicit request that cannot
        # be honoured still warns, as it does for map().
        if raw_mode == "udf":
            _warn_if_cached_incompatible()
        # WO-CR-ROI-2 Phase C: same route gate as map(), keyed on the
        # STREAM routes. stream(spawn) has no dispatch regardless.
        if (_cleanroom_enabled()
                and _cleanroom_route_enabled("stream", raw_mode)):
            _ok, _why = _cleanroom_eligible(
                source, raw_mode, num_nodes,
                kwargs.get("order", "none"),
                kwargs.get("strict_poison", False), orchestrator,
                streaming=True,
                resume=kwargs.get("resume"),
                checkpoint_file=kwargs.get("checkpoint_file"))
            if _ok and _cleanroom_launcher_path() is not None:
                _p, _sep, _f = (
                    raw_payload.rpartition(":")
                    if isinstance(raw_payload, str) else ("", "", ""))
                # Same UDF wiring as map(): helper for this minor, or
                # fall through to the in-process path.
                _udf_args = {}
                if raw_mode == "udf" and _p and _f:
                    _helper = _udf_helper_path()
                    if _helper:
                        _udf_args = {
                            "udf_helper": _helper,
                            "udf_module": _p,
                            "udf_attr": _f,
                            "udf_roots": _udf_roots_spec(_p),
                        }
                if _p and _f and (raw_mode != "udf" or _udf_args):
                    return _stream_with_preingest_fallback(
                        raw_payload, raw_mode, source, kwargs,
                        num_nodes, orchestrator, _p, _f, _udf_args,
                        helper_fp=_helper_fingerprint(
                            _udf_args.get("udf_helper")))
            elif _cleanroom_explicit() and _why:
                import warnings as _warnings
                _warnings.warn(
                    "forkrun: requested cleanroom ignored for this "
                    "stream() call (%s) \u2014 using the in-process path."
                    % (_why,), UserWarning, stacklevel=3)
        if orchestrator:
            return _guarded_gen(
                _signal_guard(kwargs.get("signal_policy", "default")),
                _ingest_stream_reactor_gen(payload, source, **kwargs))
        return _guarded_gen(
            _signal_guard(kwargs.get("signal_policy", "default")),
            _ingest_stream_gen(payload, source, **kwargs))
    if orchestrator:
        return _guarded_gen(
            _signal_guard(kwargs.get("signal_policy", "default")),
            _stream_reactor_gen(payload, source, **kwargs))
    return _guarded_gen(
        _signal_guard(kwargs.get("signal_policy", "default")),
        _stream_gen(payload, source, **kwargs))


def _guarded_gen(guard, gen):
    """Hold a signal guard open across a result generator (D-PORT1).

    stream() validates eagerly but runs lazily: installing handlers
    in stream() itself would uninstall before the first next().
    The guard therefore lives here — installed on first next(),
    restored at exhaustion (with pending-signal translation), or
    on abandonment (GeneratorExit propagates unmasked, same
    doctrine as teardown: never mask GeneratorExit).

    W-REL2/R10: the process-wide _RUN_LOCK is ALSO held here, for
    the same lazy lifetime. Every stream() path returns through
    this choke point, so all five stream executors (and the
    reactor executors they drive) serialize against concurrent
    run/map/stream in other threads — engine globals are
    process-global.

    WO-ROI-1-R1 CORRECTED THIS. The line here used to read "Same-thread
    nesting re-enters via RLock" -- true of a bare RLock, and the reason
    the guard was needed. _RunLock now REFUSES same-thread re-entry
    before acquiring, so nesting no longer re-enters anything; a nested
    run inside a live stream raises RuntimeError. Abandonment
    (close()/GeneratorExit) still releases through the with-finally
    together with the signal guard, riding the existing W-PY6 cleanup.
    """
    with _RUN_LOCK:
        with guard as _sg:
            yield from gen
            _sg.check()


def _stream_gen(payload, source, **kwargs):
    # v1 true streaming: yields blobs in worker-completion order WHILE
    # workers run (not after collection). map() stays on the v0.5
    # post-completion path; run() (discard/worker-sink) needs no drain.
    yield from _execute_streaming(
        payload, source,
        lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
        workers=_resolve_workers_numa(kwargs.get("workers")),
        on_error=kwargs.get("on_error", "retry"),
        strict_poison=kwargs.get("strict_poison", False),
        mode=kwargs.get("mode", "python"), nodes=kwargs.get("nodes", "auto"),
        order=kwargs.get("order", "none"),
        c_drain=kwargs.get("c_drain", True))


def _splice_stream_gen(source, *, bytes_, workers, on_error, nodes,
                       order, c_drain=True, strict_poison=False):
    # W-PY18 stream() over the C passthrough loop (materialized
    # ingest, live results): yields raw byte-windows as they arrive.
    yield from _execute_streaming(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, strict_poison=strict_poison,
        mode="splice", nodes=nodes, order=order,
        splice=True, c_drain=c_drain)


def _splice_ingest_stream_gen(source, *, bytes_, workers, on_error,
                              nodes, order, c_drain=True,
                              strict_poison=False):
    # W-PY18 stream() over passthrough + streaming ingest (unbounded
    # in, live out — the bash -s shape): spill and drain interleave.
    yield from _execute_ingest_stream(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, strict_poison=strict_poison,
        mode="splice", nodes=nodes, order=order,
        splice=True, c_drain=c_drain)


def _stream_reactor_gen(payload, source, **kwargs):
    # W-PY19 stream() under reactor supervision (materialized input,
    # live drain): identical ordering contract to _stream_gen, plus
    # death pipes, bounded respawn, and trap-ACK confirmation.
    yield from _execute_streaming_reactor(
        payload, source,
        lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
        workers=_resolve_workers_numa(kwargs.get("workers")),
        on_error=kwargs.get("on_error", "retry"),
        strict_poison=kwargs.get("strict_poison", False),
        mode=kwargs.get("mode", "python"), nodes=kwargs.get("nodes", "auto"),
        order=kwargs.get("order", "none"),
        splice=kwargs.get("mode") == "splice",
        c_drain=kwargs.get("c_drain", True),
        resume=kwargs.get("resume"),
        checkpoint_file=kwargs.get("checkpoint_file"))


def _splice_stream_reactor_gen(source, *, bytes_, workers, on_error,
                               nodes, order, c_drain=True,
                               strict_poison=False):
    # W-PY19 stream() over splice + reactor (materialized ingest,
    # live results, respawn on death). Python reassembly only (the C
    # orderer needs OrderPackets the splice loop never sends).
    yield from _execute_streaming_reactor(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, strict_poison=strict_poison,
        mode="splice", nodes=nodes, order=order,
        splice=True, c_drain=c_drain)


def _ingest_stream_reactor_gen(payload, source, **kwargs):
    # W-PY19 stream() over a streaming source under the reactor:
    # live drain interleaved with the spill (pump hook), scanner
    # death pipe, spawn-pipe dynamic scaling.
    yield from _execute_ingest_stream_reactor(
        payload, source,
        lines=kwargs.get("lines"), bytes_=kwargs.get("bytes"),
        workers=_resolve_workers_numa(kwargs.get("workers")),
        on_error=kwargs.get("on_error", "retry"),
        strict_poison=kwargs.get("strict_poison", False),
        mode=kwargs.get("mode", "python"), nodes=kwargs.get("nodes", "auto"),
        order=kwargs.get("order", "none"),
        c_drain=kwargs.get("c_drain", True),
        resume=kwargs.get("resume"),
        checkpoint_file=kwargs.get("checkpoint_file"))


def _splice_ingest_stream_reactor_gen(source, *, bytes_, workers,
                                      on_error, nodes, order,
                                      c_drain=True, strict_poison=False):
    # W-PY19 stream() over splice + streaming ingest + reactor.
    yield from _execute_ingest_stream_reactor(
        None, source, lines=None, bytes_=bytes_, workers=workers,
        on_error=on_error, strict_poison=strict_poison,
        mode="splice", nodes=nodes, order=order,
        splice=True, c_drain=c_drain)


def _drain_worker_memfd(fd, state) -> list:
    """Incrementally pread new bytes from one worker memfd.

    state is [read_offset, tail]; pread (never read/lseek -- the fd's open
    description is SHARED with the writing child). Returns complete
    [(batch_idx, payload)] records; the incomplete tail stays buffered.

    W-PYKEEPFSTAT: the fstat-then-pread-the-delta form was measured
    against two cheaper-looking alternatives and WON both, so it stays:

    - Dropping the fstat for a fixed-size pread, looping until a short
      read (W-PYNOFSTAT, attempted and reverted): fewer syscalls per
      CALL, but MORE per run. The fstat is a cheap early-out -- a worker
      that signalled before its bytes were visible costs one fstat
      instead of a pread -- and the loop's extra iterations came to 160
      preads where this form does 28 on a 1293-signal run. Measured
      -4% to -9% on stream() (paired, 30 rounds) and worse still at one
      line per batch.
    - A fixed cap with no loop strands whatever exceeds it once the
      signal stream runs dry before the memfd does, and the drain then
      never completes: it hung test_c_drain and test_numa_bump.

    The change that DID pay here is upstream, in _parse_drain_quantum:
    drain each worker at most once per quantum rather than once per
    signal (W-PYONCEDRAIN).
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


def _drain_worker_memfd_terminal(fd, state) -> list:
    """Terminal-aware sibling of _drain_worker_memfd.

    Same cursor and tail discipline, but parses with
    _split_records_terminal so control records survive, returning
    [(batch_idx, disposition, payload)].

    This is what lets a SKIPPED / POISONED / NO_RESULT batch advance an
    ordered consumer's prefix instead of masquerading as a hole until
    final_drain(). The DATA-only helper stays for callers that must not
    see control records at all.
    """
    try:
        want = os.fstat(fd).st_size
    except OSError:
        return []
    if want <= state[0]:
        return []
    try:
        chunk = os.pread(fd, want - state[0], state[0])
    except OSError:
        return []
    if not chunk:
        return []
    state[0] += len(chunk)
    records, tail = _split_records_terminal(state[1] + chunk)
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
    (all write ends closed) AND the pump (if any) is done; a torn
    trailing signal (1-15 bytes at EOF) is discarded loudly instead
    of hanging (W-REL5-C7).
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
        # W-PYSIGCURSOR: cursor, not a reslice per signal. The old
        # `sig_buf = sig_buf[_sig.size:]` recopied the whole remaining
        # buffer per signal, which is quadratic in signals-per-read.
        _sp = 0
        while len(sig_buf) - _sp >= _sig.size:
            wid, _idx = _sig.unpack_from(sig_buf, _sp)
            _sp += _sig.size
            if 0 <= wid:
                while len(per_worker) <= wid:
                    per_worker.append([0, b""])
                for _bidx, _disp, _blob in _drain_worker_memfd_terminal(
                        out_fds[wid], per_worker[wid]):
                    if reassembly is None:
                        # No ordering requested: only DATA is a result.
                        # Control records are intentionally dropped, as
                        # they always were for this shape.
                        if _disp == _DISP_DATA:
                            yield _blob
                    else:
                        reassembly.add_disposition(_bidx, _disp, _blob)
                        for _, ordered in reassembly.drain():
                            yield ordered
        if _sp:
            sig_buf = sig_buf[_sp:]
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
        if not alive and sig_eof and pump_done:
            if sig_buf:
                # W-REL5-C7: torn trailing signal (1-15 bytes at EOF
                # with nobody left to complete it — pipe writes are
                # atomic, so a short tail means a torn writer, not a
                # slow one). The old `not sig_buf` conjunct turned
                # this into a silent infinite hang; discard loudly.
                try:
                    os.write(2, ("forkrun [WARN]: torn trailing "
                                 "signal (%d byte(s)) discarded at "
                                 "EOF.\n" % len(sig_buf)).encode())
                except OSError:
                    pass
                sig_buf = b""
            break
    # Safety sweep: every record arrived with its signal before EOF, so
    # this should find nothing — but a short final write must never be
    # silently lost.
    for wid in range(len(per_worker)):
        for bidx, bdisp, bblob in _drain_worker_memfd_terminal(
                out_fds[wid], per_worker[wid]):
            if reassembly is None:
                if bdisp == _DISP_DATA:
                    yield bblob
            else:
                reassembly.add_disposition(bidx, bdisp, bblob)
                for _, ordered in reassembly.drain():
                    yield ordered
    if reassembly is not None:
        for _, ordered in reassembly.final_drain():
            yield ordered
        if stats is not None:
            stats["reassembly_max"] = reassembly.max_size
        # LABEL CORRECTED (round-9 review). This said "map()", but
        # _drain_records() is called only from _execute_streaming() and
        # _execute_ingest_stream() -- both generator/stream paths.
        # map() never constructs a ReassemblyBuffer at all: it uses the C
        # orderer (`use_orderer`), so there is no buffer here to refuse.
        _raise_on_disposition_conflicts(reassembly, "stream()")


def _raise_on_disposition_conflicts(reassembly, where):
    """Refuse a result the reassembly buffer says is untrustworthy.

    `ReassemblyBuffer.conflicts()` is documented as "a caller can refuse
    the result". Until now no caller existed, so the policy was
    record-and-ignore -- the conflicts were recorded faithfully and then
    never read by anything in production.

    This is that caller, and it is wired into EVERY path that
    constructs a ReassemblyBuffer:

        _drain_records                  (streaming, ingest-stream)
        _make_results_pump             (C-drain: materialized stream,
                                         ingest-stream, reactor-stream,
                                         NUMA-stream)
        _execute_streaming_reactor
        _execute_ingest_stream_reactor
        _execute_numa_stream

    Streams raise at the point of detection rather than at EOF, because
    a stream cannot retract records already yielded and because
    delaying permits further output to escape after integrity has
    already been invalidated. The message says plainly that
    already-yielded data is not withdrawn.

    ABOUT `map()` -- there is deliberately no hook here, and claiming
    one would be wrong. map() never constructs a ReassemblyBuffer: its
    order="index" path uses the C orderer (`use_orderer`), which merges
    by (major, minor) and emits only records that exist. A skipped or
    poisoned batch produces no record there at all, so the orderer
    simply never sees it and no contradiction can arise.

    An earlier version of this helper's comment claimed map() was the
    collected-result consumer checked here. It was not -- the single
    call site was inside _drain_records(), which is a STREAM path, and
    it was mislabelled "map()". Corrected in round 9.
    """
    conflicts = reassembly.conflicts()
    if not conflicts:
        return
    detail = "; ".join("batch %d: %s" % (idx, "; ".join(what))
                       for idx, what in sorted(conflicts.items()))
    raise ForkrunProtocolError(
        "forkrun: %s produced contradictory terminal outcomes for %d "
        "batch(es) -- the result is NOT trustworthy and is refused.\n"
        "  %s\n"
        "  A correct producer emits exactly ONE terminal outcome per batch.\n"
        "  This is an engine-protocol defect, not a caller error."
        % (where, len(conflicts), detail),
        conflicts=conflicts)


def _make_results_pump(results_r, order="none", stats=None):
    """Build a C-drain results-pipe pump for streaming (W-PY21-A).

    The drain child moves framed records verbatim into the results
    pipe; this pump is the parent's incremental consumer. Returns
    pump(alive), where alive is True while any producer (worker or
    drain process) may still deliver bytes. Returns the next blob,
    None when nothing is complete YET (not EOF — keep polling), or
    raises StopIteration when producers are gone AND the pipe hit
    EOF AND no buffered records remain (same EOF-anchored rule as
    _drain_records; a truncated tail is dropped, like _parse_records).

    On what a truncated tail means, the wording corrected (round-8
    review). It previously read "a worker that died mid-record, never
    user data", which is too strong. `RESILIENCE_PROTOCOL.md` 2.2 states
    that output rollback is guarded by `S_ISREG` and that PIPES downgrade
    to at-least-once -- a pipe cannot be truncated, so partial output
    from a killed batch genuinely can appear on one.

    In this specific path the risk is limited: the results pipe carries
    already-framed records out of the per-worker memfds, and memfds are
    S_ISREG, so the rollback that protects a killed batch's partial
    output happens at the memfd rather than here. The truncation source
    is therefore the DRAIN process losing a partial write, not a worker
    emitting a partial batch.

    So the honest statement is that the tail is dropped because it is an
    incomplete FRAME, not because it is provably not user data. The
    runtime behaviour is unchanged -- correcting the claim, not the
    semantics -- but a caller reading this should know the difference.

    order="index" reassembles completion-order records into
    batch_idx sequence via ReassemblyBuffer (holes flush sorted at
    EOF — same head-of-line contract as _drain_records). stats
    receives {"reassembly_max": high-water} when ordering.
    """
    import select as _select

    st = {"tail": b"", "eof": False, "pending": _deque(),
          "reassembly": (ReassemblyBuffer() if order == "index"
                         else None)}

    def _check_conflicts():
        # Checked IMMEDIATELY on ingestion, before any further pending
        # output is handed back.
        #
        # Waiting until EOF permits more records to escape after the
        # producer has already violated the protocol, which is the
        # window the check exists to close. Already-yielded records
        # cannot be withdrawn, so the error says so -- but no further
        # ones are released after the contradiction is known.
        if st["reassembly"] is not None:
            _raise_on_disposition_conflicts(
                st["reassembly"],
                "stream() [records already yielded before this point "
                "are NOT withdrawn]")

    def _ingest(chunk):
        # Stage 1: the results-PIPE consumer is a distinct production
        # path from the worker-memfd drains, and it was still
        # DATA-only. With the C drain active the records arrive here
        # through this pipe rather than from the per-worker memfds, so
        # SKIPPED / POISONED / NO_RESULT were being discarded before
        # the reassembly buffer saw them and later DATA stayed blocked
        # behind that hole until finalisation -- the exact behaviour
        # Stage 1 exists to remove.
        #
        # The unordered branch keeps DATA-only semantics, which is what
        # those callers require.
        if st["reassembly"] is None:
            records, tail = _split_records(st["tail"] + chunk)
            st["tail"] = tail
            st["pending"].extend(blob for _, blob in records)
            return
        records, tail = _split_records_terminal(st["tail"] + chunk)
        st["tail"] = tail
        for bidx, bdisp, bblob in records:
            st["reassembly"].add_disposition(bidx, bdisp, bblob)
        # BEFORE draining: a contradiction detected here must not release
        # further output. Checked after drain() it would already have
        # queued records that the caller can no longer be told about.
        _check_conflicts()
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
            return st["pending"].popleft()
        if not alive and st["eof"]:
            if st["reassembly"] is not None:
                for _, ordered in st["reassembly"].final_drain():
                    st["pending"].append(ordered)
                if stats is not None:
                    stats["reassembly_max"] = (
                        st["reassembly"].max_size)
                # And again at EOF, for a contradiction whose second
                # outcome arrived with the final chunk and was not seen
                # on a later ingestion pass.
                _check_conflicts()
                if st["pending"]:
                    return st["pending"].popleft()
            raise StopIteration
        return None

    return pump


# W-REL5-B4: default deadline for helper joins (scanner, fallow
# reaper, C drain, C orderer, NUMA ingest/indexers). Helpers are
# expected to exit promptly once their EOF lands (workers are
# already reaped / EOF posted by then); a helper still alive past
# this is wedged — SIGKILL (via _waitpid_bounded) is mercy, and the
# alarm names it. Worker COMPLETION joins stay unbounded (the run
# IS the wait); post-abort worker reaps use WORKER_REAP_TIMEOUT
# (abort already woke them); the orderer uses ORDERER_REAP_TIMEOUT.
_HELPER_JOIN_TIMEOUT = 10.0

# W-PYINGESTPIPE: ingress pipe capacity for a streamed source. Matched
# to _CHUNK so one read() yields one spill write. Clamped to
# fs.pipe-max-size by the kernel; EPERM/EINVAL falls back silently.
_INGEST_PIPE_SZ = 1 << 20




def _join_helper_bounded(pid, name, timeout=_HELPER_JOIN_TIMEOUT):
    """Bounded join for one helper child (W-REL5-B4).

    Reaps with a deadline via _resume._waitpid_bounded (SIGKILL on
    expiry, then reap); on expiry an alarm naming the helper goes
    to stderr. Returns the wait status, or None when no status is
    obtainable (reaped elsewhere / unreaped even after SIGKILL —
    callers treat None like the old ChildProcessError leniency).
    Never raises.
    """
    start = _time.monotonic()
    try:
        _reaped, status = _waitpid_bounded(pid, timeout)
    except Exception:
        return None
    if not _reaped:
        status = None
    if _time.monotonic() - start >= max(timeout, 0.0):
        try:
            os.write(2, ("forkrun [WARN]: helper '%s' (pid %s) did "
                         "not exit within %.1fs (SIGKILL issued); "
                         "continuing.\n" % (name, pid, timeout)
                         ).encode())
        except OSError:
            pass
    return status


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
    for _pid, _name in (
            [(_p, "worker") for _p in pids]
            + [(_p, "helper") for _p in extra_pids]
            + ([(drain_pid, "drain")] if drain_pid is not None
               else [])):
        # W-REL5-B4: bounded (kill already issued above; the spin
        # reaps promptly in practice, the deadline covers D-state).
        _join_helper_bounded(_pid, _name)
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
                        engine_fds, extra_keep_fds=None):
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
            if extra_keep_fds:
                keep.update(extra_keep_fds)
            scrub_fds(keep)
        except Exception:
            pass
        try:
            # F-PORT1: poison threshold from FORKRUN_RETRY_LIMIT, never hardcoded.
            from ._api import _resolve_retry_limit as _retry_limit
            if lib.fr_py_worker_init(wid, 0, 0, _retry_limit(), 0) != 0:
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
                       on_error, strict_poison=False, mode="python", nodes="auto",
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
    # TD-09b: declared at function scope because the poison summary below
    # sits outside the scope that binds the real channel. Leaving it
    # unbound there made globals().get() fall back to None, which
    # silently skipped index collection and published an EMPTY
    # poisoned_batches next to a non-zero poisoned count.
    _poison_ch = None
    use_drain = bool(c_drain)
    if use_drain:
        _require_drain_symbol()
    # W-REL6-5: lattice position (executor #3: UMA, materialized,
    # plain, generator) + this call's behavior flags (stream always
    # collects into yields: collect=True).
    _spec = ExecutorSpec(topology="uma", ingest="materialized",
                         supervision="plain", shape="generator",
                         collect=True, splice=splice, c_drain=c_drain,
                         order=order)
    lib, engine_fds = _init_engine_and_fds(
        lines=lines, bytes_=bytes_, spec=_spec)

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
    scan_pid = None
    scan_rc = None
    try:
        memfd, size = _spill_to_memfd(src_fd)
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        if lib.fr_py_ingest_done() != RC_OK:
            raise RuntimeError("ingest signal failed")
        # W-PY39: fork the scanner so its pre-flight + publish
        # overlap worker execution below (bash/NUMA topology).
        # Workers arriving mid-scan trip the pre-flight bail
        # (CASE B); the engine main loop always scans from byte 0.
        scan_pid = _fork_materialized_scanner(lib, memfd, engine_fds)

        def _scan_pump():
            # W-PY39 scanner watch for _drain_records: raises on
            # scanner failure (else workers would hang without EOF
            # and the drain would never exhaust); True once the
            # scanner exited cleanly (drain termination stays
            # worker/signal-driven).
            nonlocal scan_pid, scan_rc
            if scan_pid is None:
                return True
            try:
                wpid, scan_st = os.waitpid(scan_pid, os.WNOHANG)
            except ChildProcessError:
                scan_pid = None
                return True
            except OSError:
                return False
            if wpid != scan_pid:
                return False
            scan_pid = None
            if os.WIFEXITED(scan_st) and \
                    os.WEXITSTATUS(scan_st) == 0:
                scan_rc = 0
                return True
            scan_rc = scan_st
            try:
                lib.fr_py_abort()
            except Exception:
                pass
            raise RuntimeError(
                "forkrun: materialized scanner failed (status %r)"
                % (scan_st,))

        _flush_stdio()

        out_fds, out_hold = _new_output_memfds(workers)
        # W-PY15: 1MB signal pipe (65536 outstanding 16B signals vs 4096
        # at default) — workers run further ahead of a slow consumer.
        # Best-effort: falls back to 64KB where F_SETPIPE_SZ is capped.
        signal_r, signal_w, _ = make_pipe()
        # W-DEDUP: single fork dispatch (generator shape closes the
        # parent's signal-read end in the child for exact EOF).
        from ._executor_core import fork_workers as _core_fork
        # WO-PY-REL-1/TD-09: poison-index relay receiving end.
        _poison_ch = _PoisonStatsChannel(workers)
        _poison_keep = [_poison_ch.open()] or []
        with _ExportedPoisonFd(_poison_keep[0]):
            pids.extend(_core_fork(
                lib, workers=workers, memfd=memfd, size=size,
                out_fds=out_fds, signal_w=signal_w, fallow_w=None,
                engine_fds=engine_fds, payload=payload, sink=None,
                mode="python", on_error=on_error,
                src_fd=src_fd, must_close=must_close,
                signal_r_to_close=signal_r, spec=_spec,
                extra_keep_fds=_poison_keep))
        # Parent drops its write copy: EOF on signal_r then means every
        # worker has exited (or abandoned teardown closed it).
        try:
            os.close(signal_w)
        except OSError:
            pass
        signal_w = None

        statuses: list = []
        # D-PORT3: the drain-branch finally below destroys the engine
        # before the shared poison summary runs, so the count is
        # stashed pre-teardown (the summary uses max(live, stashed)).
        npois_stashed = 0
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
            scan_alive = True
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
                    if scan_alive:
                        # W-PY39: fail fast on scanner death (no EOF
                        # can arrive without it); clean exit just
                        # retires the watch (drain stays
                        # worker-driven).
                        try:
                            wpid, scan_st = os.waitpid(
                                scan_pid, os.WNOHANG)
                        except ChildProcessError:
                            scan_alive = False
                            scan_pid = None
                        except OSError:
                            pass
                        else:
                            if wpid == scan_pid:
                                scan_alive = False
                                scan_pid = None
                                if not (os.WIFEXITED(scan_st) and
                                        os.WEXITSTATUS(scan_st)
                                        == 0):
                                    scan_rc = scan_st
                                    try:
                                        lib.fr_py_abort()
                                    except Exception:
                                        pass
                                    raise RuntimeError(
                                        "forkrun: materialized "
                                        "scanner failed (status %r)"
                                        % (scan_st,))
                                scan_rc = 0
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
                # — join it here to capture its rc. Bounded
                # (W-REL5-B4): EOF implies the write end is closed.
                if drain_alive:
                    # W-REL5-B4: bounded.
                    _dst = _join_helper_bounded(drain_pid, "drain")
                    if _dst is not None:
                        drain_alive = False
                        drain_status = _dst
                exhausted = True
                # Workers are gone: the engine poison count is final —
                # stash it before the finally below destroys the engine.
                npois_stashed = _poisoned_now(lib)
                # W-PY39 scanner join (backstop: the in-loop watch
                # above already fail-fasted on error and retired on
                # clean exit; workers cannot EOF without a clean
                # scanner finish).
                if scan_pid is not None and scan_rc is None:
                    # W-REL5-B4: bounded (proof-based leniency below
                    # covers the reaped-elsewhere None).
                    scan_st = _join_helper_bounded(scan_pid, "scanner")
                    scan_pid = None
                    if scan_st is not None and not (
                            os.WIFEXITED(scan_st) and
                            os.WEXITSTATUS(scan_st) == 0):
                        raise RuntimeError(
                            "forkrun: materialized scanner failed "
                            "(status %r)" % (scan_st,))
                else:
                    scan_pid = None
            finally:
                # Normal exhaustion falls through; abandonment
                # (GeneratorExit) or consumer error lands here: reap,
                # close, destroy, re-raise (a fresh raise on the
                # abandon path would mask GeneratorExit). The
                # teardown EPIPEs a drain blocked on a full pipe via
                # the results read end.
                _teardown_stream(lib, pids, signal_r, out_fds,
                                 out_hold, memfd, src_fd, must_close,
                                 extra_pids=([scan_pid]
                                             if scan_pid else []),
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
                                           stats=stats, pump=_scan_pump):
                    yield blob
                # Workers are gone: stash the engine poison count
                # before the finally below destroys the engine.
                npois_stashed = _poisoned_now(lib)
            finally:
                # Normal exhaustion falls through; abandonment (GeneratorExit)
                # or consumer error lands here: reap, close, destroy, re-raise
                # (a fresh raise on the abandon path would mask GeneratorExit).
                _teardown_stream(lib, pids, signal_r, out_fds, out_hold,
                                 memfd, src_fd, must_close,
                                 extra_pids=([scan_pid]
                                             if scan_pid else []))
                memfd = None
                signal_r = None
                out_fds = []

        # W-PY39 scanner join (backstop for the non-drain branch:
        # the pump fail-fasted on error and retired on clean exit;
        # workers cannot EOF without a clean scanner finish).
        if scan_pid is not None and scan_rc is None:
            # W-REL5-B4: bounded (proof-based leniency below covers
            # the reaped-elsewhere None).
            scan_st = _join_helper_bounded(scan_pid, "scanner")
            scan_pid = None
            if scan_st is not None and not (
                    os.WIFEXITED(scan_st) and
                    os.WEXITSTATUS(scan_st) == 0):
                raise RuntimeError(
                    "forkrun: materialized scanner failed (status %r)"
                    % (scan_st,))
        else:
            scan_pid = None

        failed = [s for s in statuses
                  if not (os.WIFEXITED(s[1]) and os.WEXITSTATUS(s[1]) == 0)]
        if failed:
            _raise_worker_failure(failed, len(pids), on_error)

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
        # _execute_streaming's branch finallys above already destroyed
        # the engine: prefer the pre-teardown stash when the live
        # read comes back zero (npois_stashed is always defined in
        # this function — initialized beside statuses above).
        # WO-PY-REL-1/TD-09: collect indices BEFORE the poison summary,
        # because report_poison raises under strict_poison and the
        # post-exception stats must stay inspectable.
        try:
            _collect_plain_poison(_poison_ch,
                                  max(npois, npois_stashed))
        except Exception:
            pass
        from ._executor_core import report_poison as _core_poison
        _core_poison(lib, strict_poison=strict_poison,
                     npois=max(npois, npois_stashed))
    except KeyboardInterrupt as _ki:
        # W-REL5-B2: stream taxonomy matches the six blocking
        # executors — abort, then ForkrunInterrupted (still a
        # KeyboardInterrupt), never bare KeyboardInterrupt.
        try:
            lib.fr_py_abort()
        except Exception:
            pass
        raise ForkrunInterrupted(_INTERRUPTED_MSG) from _ki
    finally:
        # WO-PY-REL-1/TD-09: close the poison-index stats memfd (see
        # _execute_ingest_locked for why this is not optional).
        try:
            _poison_ch.close()
        except (NameError, UnboundLocalError, AttributeError):
            pass
        # Idempotent second layer: teardown already ran inside; these are
        # no-ops when it did (Nones/empties) and save abandon paths where
        # setup itself raised before forking.
        _teardown_stream(lib, pids, signal_r, out_fds, out_hold, memfd,
                         src_fd, must_close,
                         extra_pids=([scan_pid] if scan_pid else []))


def _execute_ingest_stream(payload, source, *, lines, bytes_, workers,
                           on_error, strict_poison=False, mode="python", nodes="auto",
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
    # WO-PY-REL-1/TD-09: holds the poison-index relay channel. Declared at
    # function scope, not inside the nested forker: in this generator the
    # fork and the poison summary sit in different scopes.
    poison_state: dict = {}
    # TD-09b: the engine poison count, captured while g_state is still
    # live. The poison summary below runs AFTER the branch finallys call
    # _teardown_stream -> fr_py_destroy(), and fr_py_poisoned_count()
    # returns 0 once g_state is NULL, so the count must be stashed before
    # teardown. Whether the engine happened to still be alive at summary
    # time was a race (identical runs reported poisoned=0 and poisoned=2).
    # Same idiom and rationale as _execute_streaming's npois_stashed.
    npois_stashed = 0
    use_drain = bool(c_drain)
    if use_drain:
        _require_drain_symbol()
    # W-REL6-5: lattice position (executor #4: UMA, streaming,
    # plain, generator) + this call's behavior flags.
    _spec = ExecutorSpec(topology="uma", ingest="streaming",
                         supervision="plain", shape="generator",
                         collect=True, splice=splice, c_drain=c_drain,
                         order=order)
    lib, engine_fds = _init_engine_and_fds(
        lines=lines, bytes_=bytes_, spec=_spec)

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

        _flush_stdio()

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
            # W-DEDUP: single fork dispatch (streaming-ingest generator;
            # fallow acks ride worker_main; signal_r stays open in the
            # child by exact preservation of the pre-dedup behavior —
            # EOF keys off write ends, so both shapes are correct).
            from ._executor_core import fork_workers as _core_fork
            # WO-PY-REL-1/TD-09: poison-index relay receiving end. The
            # fork is deferred here, so the channel is created with it.
            poison_state["ch"] = _PoisonStatsChannel(workers)
            _pk = [poison_state["ch"].open()] or []
            with _ExportedPoisonFd(_pk[0]):
                pids.extend(_core_fork(
                    lib, workers=workers, memfd=memfd, size=-1,
                    out_fds=out_fds, signal_w=signal_w, fallow_w=fallow_w,
                    engine_fds=engine_fds, payload=payload, sink=None,
                    mode="python", on_error=on_error, spec=_spec,
                    extra_keep_fds=_pk))
            _drop_parent_copies()
            state["workers"] = True
            state["fork_at"] = _time.monotonic()
            _fork_drain_if_needed()

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
        src_fd, must_close = _prepare_ingest_source(src_fd, must_close)
        try:
            fl = _fcntl.fcntl(src_fd, _fcntl.F_GETFL)
            _fcntl.fcntl(src_fd, _fcntl.F_SETFL, fl | os.O_NONBLOCK)
        except OSError:
            pass

        def _pump():
            # One drain-loop quantum. Returns True when ingest is fully
            # done: gate issued AND (workers forked OR input was empty).
            # Side effects: forks workers per the timing rule, spills
            # source quanta via pwrite, issues the gate (with the
            # post-stall-fork grace). Raises on helper death / anomaly.
            _watch_helper_deaths(lib, scan_pid, fallow_pid, helpers,
                                 gate["issued"])
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
                # Join the drain for its rc (EOF seen ⇒ exited;
                # bounded, W-REL5-B4).
                if drain["pid"] is not None and drain["alive"]:
                    # W-REL5-B4: bounded.
                    _dst = _join_helper_bounded(drain["pid"], "drain")
                    if _dst is not None:
                        drain["alive"] = False
                        drain["status"] = _dst
                drain_status = drain["status"]
                drain_alive = drain["alive"]
                exhausted = True
                # Workers are gone: the engine poison count is final --
                # stash it before the finally below destroys the engine
                # (TD-09b).
                npois_stashed = _poisoned_now(lib)
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
                # Workers are gone: stash the engine poison count before
                # the finally below destroys the engine (TD-09b).
                npois_stashed = _poisoned_now(lib)
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
            _raise_worker_failure(failed, len(pids), on_error)

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
        # locked path for the full argument). Join is bounded
        # (W-REL5-B4).
        if scan_pid is not None and helpers["scan_rc"] is None:
            try:
                wpid, scan_st = os.waitpid(scan_pid, os.WNOHANG)
            except ChildProcessError:
                wpid, scan_st = scan_pid, None
            if wpid == 0:
                # W-REL5-B4: bounded.
                scan_st = _join_helper_bounded(scan_pid, "scanner")
            if scan_st is not None and not (
                    os.WIFEXITED(scan_st) and
                    os.WEXITSTATUS(scan_st) == 0):
                raise RuntimeError(
                    "forkrun: ingest scanner failed (status %r)"
                    % (scan_st,))
        if fallow_pid is not None and helpers["fallow_rc"] is None:
            # W-REL5-B4: bounded (WARN-lenient below covers None).
            fallow_st = _join_helper_bounded(fallow_pid, "fallow")
            if fallow_st is not None and not (
                    os.WIFEXITED(fallow_st) and
                    os.WEXITSTATUS(fallow_st) == 0):
                try:
                    os.write(2, b"forkrun [WARN]: ingest reaper exited "
                             b"abnormally; ingress may not be fully "
                             b"reclaimed.\n")
                except OSError:
                    pass

        # W-REL6-5: WARN + raise funnel through the core twin
        # (identical text; _raise_for_poisoned stash preserved).
        # WO-PY-REL-1/TD-09: collect indices BEFORE the poison summary,
        # because report_poison raises under strict_poison and the
        # post-exception stats must stay inspectable.
        try:
            _collect_plain_poison(poison_state.get("ch"),
                                  max(_read_poison_count(lib),
                                      npois_stashed))
        except Exception:
            pass
        from ._executor_core import report_poison as _core_poison
        _core_poison(lib, strict_poison=strict_poison,
                     npois=max(_read_poison_count(lib),
                               npois_stashed))
    except KeyboardInterrupt as _ki:
        # W-REL5-B2: stream taxonomy matches the six blocking
        # executors — abort, then ForkrunInterrupted (still a
        # KeyboardInterrupt), never bare KeyboardInterrupt.
        try:
            lib.fr_py_abort()
        except Exception:
            pass
        raise ForkrunInterrupted(_INTERRUPTED_MSG) from _ki
    finally:
        # WO-PY-REL-1/TD-09: close the poison-index stats memfd (see
        # _execute_ingest_locked for why this is not optional).
        try:
            poison_state["ch"].close()
        except (KeyError, AttributeError):
            pass
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
        workers=_resolve_workers_numa(kwargs.get("workers")),
        on_error=kwargs.get("on_error", "retry"),
        strict_poison=kwargs.get("strict_poison", False),
        mode=kwargs.get("mode", "python"), nodes=kwargs.get("nodes", "auto"),
        order=kwargs.get("order", "none"),
        c_drain=kwargs.get("c_drain", True))


def _new_ingress_memfd():
    """Create the streaming-ingest memfd (parent writes, scanner + workers
    read). Returns (fd, hold) where hold is always empty (W-REL5-E7
    removed the tempfile fallback; os.memfd_create exists on all
    supported Pythons, floor 3.10).

    INVARIANTS.md §20: this fd's file offset is UNDEFINED — never
    read or relied upon (explicit offsets / mmap windows only)."""
    return os.memfd_create("forkrun_ingress"), []


def _execute_ingest(payload, source, *, sink, lines, bytes_, workers,
                    on_error, strict_poison=False, collect, order, mode="python", nodes="auto",
                    splice=False, c_drain=True, views=True):
    """Streaming-ingest entry for map/run (blocking, like _execute)."""
    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    with _RUN_LOCK:
        return _execute_ingest_locked(
            payload, source, sink=sink, lines=lines, bytes_=bytes_,
            workers=workers, on_error=on_error, strict_poison=strict_poison,
            collect=collect,
            order=order, splice=splice, c_drain=c_drain, views=views)


def _fork_materialized_scanner(lib, memfd, engine_fds):
    """Fork a scanner child over complete (materialized) input (W-PY39).

    The child scrubs to engine fds + memfd, runs fr_py_scan to EOF,
    and exits with the engine rc. Returns the child pid; the caller
    MUST reap it (waitpid) and treat a nonzero rc as run failure
    ("scan failed" — the synchronous fr_py_scan contract).

    Materialized callers fork workers immediately after their
    natural setup (output memfds, pipes, orderer/drain, reactor
    state — the 1-5ms pre-flight window): workers arriving
    mid-scan trip the engine pre-flight bail (CASE B → geometric
    ramp from partial calibration), overlapping scan with
    compute. A zero-window arrival is equally correct (ramp from
    scratch): the engine main loop always scans from byte 0, so
    CASE A/B differ only in batch sizing, never in completeness.
    (The ingest paths keep their first-publish gate instead —
    their input is still arriving while the scanner runs.)
    """
    pid = os.fork()
    if pid == 0:
        try:
            scrub_fds(engine_fds | {memfd})
            rc = lib.fr_py_scan(memfd)
        except BaseException:
            rc = 1
        os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
    return pid


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
                           workers, on_error, strict_poison=False, collect, order,
                           splice=False, c_drain=True, views=True):
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
    # WO-PY-REL-1/TD-09: poison-index relay channel, created with the
    # deferred fork (this path forks workers on first data publish).
    poison_state: dict = {}
    use_drain = bool(c_drain) and collect
    if use_drain:
        _require_drain_symbol()
    # W-REL6-5: lattice position (executor #2: UMA, streaming,
    # plain, blocking) + this call's behavior flags.
    _spec = ExecutorSpec(topology="uma", ingest="streaming",
                         supervision="plain", shape="blocking",
                         collect=collect, splice=splice, c_drain=c_drain,
                         order=order)
    lib, engine_fds = _init_engine_and_fds(
        lines=lines, bytes_=bytes_, spec=_spec)

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

        _flush_stdio()

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
            from ._executor_core import fork_workers as _core_fork
            if splice and not collect:
                # Unreachable by dispatch (map splice always collects;
                # run() rejects splice) but preserved for exactness:
                # splice needs an out fd per worker.
                raise RuntimeError(
                    "splice without collect has no output transport")
            # W-DEDUP: single fork dispatch (splice fail-loud / python
            # with fallow acks). Pids return in worker-index order.
            # WO-PY-REL-1/TD-09: poison-index relay receiving end.
            poison_state["ch"] = _PoisonStatsChannel(workers)
            _pk = [poison_state["ch"].open()] or []
            with _ExportedPoisonFd(_pk[0]):
                pids.extend(_core_fork(
                    lib, workers=workers, memfd=memfd, size=-1,
                    out_fds=out_fds if collect else [], signal_w=signal_w
                    if use_drain else None, fallow_w=fallow_w,
                    engine_fds=engine_fds, payload=payload, sink=sink,
                    mode="python", on_error=on_error, spec=_spec,
                    extra_keep_fds=_pk))
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
                _watch_helper_deaths(lib, scan_pid, fallow_pid, helpers, gate_issued)
                _maybe_fork_workers()
        except KeyboardInterrupt as _ki:
            lib.fr_py_abort()
            raise ForkrunInterrupted(_INTERRUPTED_MSG) from _ki
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
                _watch_helper_deaths(lib, scan_pid, fallow_pid, helpers, gate_issued)
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
                _watch_helper_deaths(lib, scan_pid, fallow_pid, helpers, gate_issued)
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
        except KeyboardInterrupt as _ki:
            lib.fr_py_abort()
            for pid in pids:
                # W-REL5-B4: bounded post-abort reap (abort woke
                # claim-gated workers; a straggler gets SIGKILL).
                _join_helper_bounded(pid, "worker",
                                     WORKER_REAP_TIMEOUT)
            raise ForkrunInterrupted(_INTERRUPTED_MSG) from _ki

        if use_drain and drain_pid is not None:
            # Signal EOF (all workers gone) terminates the drain on
            # its own — reap it. Worker error below wins on the
            # failed path (results moot, child still reaped).
            # W-REL5-B4: bounded (None ⇒ reaped elsewhere, same
            # leniency as the old ChildProcessError branch).
            _dst = _join_helper_bounded(drain_pid, "drain")
            if _dst is None:
                _dst = 0
            drain_status = _dst
            drain_pid = None
            if not failed and _dst != 0 and not (
                    os.WIFEXITED(_dst) and os.WEXITSTATUS(_dst) == 0):
                raise RuntimeError(
                    "forkrun: C drain failed (status %r)" % (_dst,))

        if failed:
            _raise_worker_failure(failed, len(pids), on_error)

        # Join the scanner (strict) and the reaper (lenient warn).
        # helpers["scan_rc"] set means _watch_helpers observed the exit
        # during the run — check it. Otherwise the scanner is either
        # still alive (bounded join, W-REL5-B4) or was already reaped
        # by teardown after healthy workers + complete drain — which
        # PROVES a clean finish (workers cannot reach EOF without
        # scanner_finished, and any crash/abort fails workers first).
        # Same leniency the reaper has always had.
        if scan_pid is not None and helpers["scan_rc"] is None:
            try:
                wpid, scan_st = os.waitpid(scan_pid, os.WNOHANG)
            except ChildProcessError:
                wpid, scan_st = scan_pid, None
            if wpid == 0:
                # W-REL5-B4: bounded.
                scan_st = _join_helper_bounded(scan_pid, "scanner")
            if scan_st is not None and not (
                    os.WIFEXITED(scan_st) and
                    os.WEXITSTATUS(scan_st) == 0):
                raise RuntimeError(
                    "forkrun: ingest scanner failed (status %r)"
                    % (scan_st,))
        if fallow_pid is not None and helpers["fallow_rc"] is None:
            # W-REL5-B4: bounded (WARN-lenient below covers None).
            fallow_st = _join_helper_bounded(fallow_pid, "fallow")
            if fallow_st is not None and not (
                    os.WIFEXITED(fallow_st) and
                    os.WEXITSTATUS(fallow_st) == 0):
                try:
                    os.write(2, b"forkrun [WARN]: ingest reaper exited "
                             b"abnormally; ingress may not be fully "
                             b"reclaimed.\n")
                except OSError:
                    pass

        # WO-PY-REL-1/TD-09: collect indices BEFORE the poison summary,
        # because report_poison raises under strict_poison and the
        # post-exception stats must stay inspectable.
        try:
            _collect_plain_poison(poison_state.get("ch"),
                                  _read_poison_count(lib))
        except Exception:
            pass
        from ._executor_core import report_poison as _core_poison
        _core_poison(lib, strict_poison=strict_poison,
                     npois=_read_poison_count(lib))

        if not collect:
            return None
        return collect_records(results_fd=results_fd,
                             out_fds=out_fds, spec=_spec,
                             lib=lib, views=views)
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
            # W-REL5-B4: bounded (kill already issued above).
            _join_helper_bounded(drain_pid, "drain")
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
        for _pid, _name in ((fallow_pid, "fallow"),
                            (scan_pid, "scanner")):
            if _pid is None:
                continue
            # W-REL5-B4: bounded (kill already issued above).
            _join_helper_bounded(_pid, _name)
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
        # WO-PY-REL-1/TD-09: close the poison-index stats memfd. Omitting
        # this leaks one fd per call, which the fd-hygiene probes in
        # test_executor_consistency detect: invisible to a caller, but
        # unbounded across a long-lived process.
        try:
            poison_state["ch"].close()
        except (KeyError, AttributeError):
            pass
        try:
            lib.fr_py_destroy()
        except Exception:
            pass


def _execute(payload, source, *, sink, lines, bytes_, workers, on_error,
               strict_poison=False,
               collect, order, mode="python", nodes="auto", splice=False,
               c_drain=True, c_worker_loop=False, plugin_spec=None,
               c_spawn_loop=False, spawn_argv=None, views=True):
    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    with _RUN_LOCK:
        return _execute_locked(payload, source, sink=sink, lines=lines,
                               bytes_=bytes_, workers=workers,
                               on_error=on_error, strict_poison=strict_poison,
                               collect=collect,
                               order=order, splice=splice,
                               c_drain=c_drain,
                               c_worker_loop=c_worker_loop,
                               plugin_spec=plugin_spec,
                               c_spawn_loop=c_spawn_loop,
                               spawn_argv=spawn_argv, views=views)


def _execute_locked(payload, source, *, sink, lines, bytes_, workers,
                    on_error, strict_poison=False, collect, order, splice=False,
                    c_drain=True, c_worker_loop=False, plugin_spec=None,
                    c_spawn_loop=False, spawn_argv=None, views=True):
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
    # W-REL6-5: lattice position (executor #1: UMA, materialized,
    # plain, blocking) + this call's behavior flags, threaded through
    # the core calls below instead of flag soup.
    _spec = ExecutorSpec(topology="uma", ingest="materialized",
                         supervision="plain", shape="blocking",
                         collect=collect, splice=splice, c_drain=c_drain,
                         order=order, c_worker_loop=c_worker_loop,
                         c_spawn_loop=c_spawn_loop)
    lib, engine_fds = _init_engine_and_fds(
        lines=lines, bytes_=bytes_, spec=_spec)

    src_fd, must_close = _open_source(source)
    memfd = None
    signal_r = None
    signal_w = None
    drain_pid = None
    results_fd = None
    scan_pid = None
    try:
        memfd, size = _spill_to_memfd(src_fd)
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        if lib.fr_py_ingest_done() != RC_OK:
            raise RuntimeError("ingest signal failed")
        # W-PY39: fork the scanner so its pre-flight + publish
        # overlap the setup + worker execution below (bash/NUMA
        # topology). Workers arriving mid-scan trip the pre-flight
        # bail (CASE B); the engine main loop always scans from
        # byte 0, so completeness never depends on the race.
        scan_pid = _fork_materialized_scanner(lib, memfd, engine_fds)

        # Flush buffered stdio before forking (no duplicated output).
        _flush_stdio()

        out_fds: list = []
        out_hold: list = []
        if collect:
            # Emitter transport, created pre-fork (see _new_output_memfds).
            out_fds, out_hold = _new_output_memfds(workers)

        if use_drain:
            # Workers signal the drain (not the parent): 1MB pipe.
            signal_r, signal_w, _ = make_pipe()

        from ._executor_core import fork_workers as _core_fork
        from ._executor_core import report_poison as _core_poison
        # WO-PY-REL-1/TD-09: receiving end of the poison-index relay.
        _poison_ch = _PoisonStatsChannel(workers)
        _poison_keep = [_poison_ch.open()] or []
        with _ExportedPoisonFd(_poison_keep[0]):
            pids = _core_fork(
                lib, workers=workers, memfd=memfd, size=size,
                out_fds=out_fds if collect else [], signal_w=signal_w
                if use_drain else None, fallow_w=None, engine_fds=engine_fds,
                payload=payload, sink=sink, mode="python", on_error=on_error,
                plugin_spec=plugin_spec, spawn_argv=spawn_argv,
                src_fd=src_fd, must_close=must_close, spec=_spec,
                extra_keep_fds=_poison_keep)

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
        # P0LEGACY: reap workers first while watching the scanner
        # (reactor pattern). The materialized scanner parks under
        # backpressure (uma_max_ahead) for ~the full run on slow-UDF
        # workloads, so joining it first with the bounded W-REL5-B4
        # deadline kills healthy runs past ~10s wall. Joining workers
        # first is safe by the engine invariant the reactor relies on
        # ("workers cannot EOF without a clean scanner finish" — by
        # the time workers are gone the scanner has necessarily
        # exited, and the backstop join below never fires). Scanner
        # death stays fail-fast here (the crash-safety the old
        # scanner-first order cited: a dead scanner aborts instead
        # of stranding workers in claim).
        scan_st = None
        alive = set(pids)
        try:
            while alive:
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
                        if not (os.WIFEXITED(status) and
                                os.WEXITSTATUS(status) == 0):
                            failed.append((pid, status))
                if scan_pid is not None:
                    try:
                        wpid, scan_st = os.waitpid(
                            scan_pid, os.WNOHANG)
                    except ChildProcessError:
                        scan_pid = None
                        scan_st = 0
                    except OSError:
                        pass
                    else:
                        if wpid == scan_pid:
                            scan_pid = None
                            if not (os.WIFEXITED(scan_st) and
                                    os.WEXITSTATUS(scan_st) == 0):
                                try:
                                    lib.fr_py_abort()
                                except Exception:
                                    pass
                                for pid in alive:
                                    # W-REL5-B4: bounded post-abort reap.
                                    _join_helper_bounded(
                                        pid, "worker",
                                        WORKER_REAP_TIMEOUT)
                                raise RuntimeError(
                                    "forkrun: scan failed (status %r)"
                                    % (scan_st,))
                if alive:
                    _time.sleep(0.005)
        except KeyboardInterrupt as _ki:
            lib.fr_py_abort()
            for pid in alive:
                # W-REL5-B4: bounded post-abort reap.
                _join_helper_bounded(pid, "worker",
                                     WORKER_REAP_TIMEOUT)
            raise ForkrunInterrupted(_INTERRUPTED_MSG) from _ki
        finally:
            pass
        # Backstop: workers are gone, so the scanner has necessarily
        # finished (invariant above) — this join retires an
        # already-exited helper and never trips the bound. A nonzero
        # status here (scanner died with the last worker) still fails
        # the run (the synchronous fr_py_scan contract, preserved).
        # W-REL5-B4: bounded (None ⇒ reaped elsewhere, read as
        # clean like the old ChildProcessError branch).
        if scan_pid is not None:
            scan_st = _join_helper_bounded(scan_pid, "scanner")
            if scan_st is None:
                scan_st = 0
            scan_pid = None
            if not (os.WIFEXITED(scan_st) and
                    os.WEXITSTATUS(scan_st) == 0):
                try:
                    lib.fr_py_abort()
                except Exception:
                    pass
                raise RuntimeError(
                    "forkrun: scan failed (status %r)" % (scan_st,))

        if use_drain and drain_pid is not None:
            # Workers are gone so the signal pipe hit EOF; the drain
            # exits on its own — reap it and check its rc. (On the
            # failed path below this still runs first: results are
            # moot but the child must be reaped. A drain failure
            # there is secondary — the worker error below wins.)
            # W-REL5-B4: bounded (None ⇒ reaped elsewhere, same
            # leniency as the old ChildProcessError branch).
            _dst = _join_helper_bounded(drain_pid, "drain")
            if _dst is None:
                _dst = 0
            drain_pid = None
            if not failed and _dst != 0 and not (
                    os.WIFEXITED(_dst) and os.WEXITSTATUS(_dst) == 0):
                raise RuntimeError(
                    "forkrun: C drain failed (status %r)" % (_dst,))

        if failed:
            _raise_worker_failure(failed, len(pids), on_error)

        # Parent-side poison summary (g_state is MAP_SHARED: the parent
        # observes worker increments without IPC). Read BEFORE destroy.
        # W-DEDUP: single implementation in _executor_core.
        #
        # WO-PY-REL-1/TD-09: collect the index list FIRST. report_poison
        # raises under strict_poison, and the contract is that stats stay
        # inspectable after that raise -- which they cannot be if the
        # indices are collected afterwards.
        try:
            _npois = lib.fr_py_poisoned_count()
        except Exception:
            _npois = 0
        _collect_plain_poison(_poison_ch, _npois)
        _core_poison(lib, strict_poison=strict_poison, npois=_npois)

        if not collect:
            return None
        return collect_records(results_fd=results_fd,
                             out_fds=out_fds, spec=_spec,
                             lib=lib, views=views)
    finally:
        if scan_pid is not None:
            # Stray scanner (exception path): SIGKILL + reap so no
            # zombie pins the pid and no child outlives the run.
            try:
                wpid, _ = os.waitpid(scan_pid, os.WNOHANG)
                if wpid == 0:
                    try:
                        os.kill(scan_pid, 9)
                    except OSError:
                        pass
            except ChildProcessError:
                pass
            except OSError:
                pass
            # W-REL5-B4: bounded (kill already issued above).
            _join_helper_bounded(scan_pid, "scanner")
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
            # W-REL5-B4: bounded (kill already issued above).
            _join_helper_bounded(drain_pid, "drain")
        if results_fd is not None:
            try:
                os.close(results_fd)
            except OSError:
                pass
        try:
            _poison_ch.close()
        except (NameError, UnboundLocalError):
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

def _poisoned_now(lib) -> int:
    """Best-effort live poisoned count (0 when unreadable)."""
    try:
        return int(lib.fr_py_poisoned_count() or 0)
    except Exception:
        return 0


# W-REL6-3.6: last-run batch accounting. Poison-summary choke points
# record here synchronously (same thread, inside the executor);
# map() resets at entry, completes with completed/total on success,
# and snapshots for return_stats / last_run_stats. Reactor paths run
# under _RUN_LOCK (exact); concurrent legacy maps already share
# process-global engine state, so the stash is no less safe than
# the engine. completed/total are None until a map() succeeds;
# poisoned/poisoned_batches reflect the last poison summary of any
# frontend (map-focused; a stream()/run() leaves its own poisoned
# count with the previous completed/total).
_LAST_STATS: dict = {"total": None, "completed": None,
                     "poisoned": 0, "poisoned_batches": [],
                     # False means "the index list is the complete truth".
                     # Only the cleanroom's bounded relay slot can make it
                     # True; the in-process path keeps every index.
                     "poisoned_batches_truncated": False}


def _reset_stats() -> None:
    """Fresh accounting for one map() call (stale runs never leak)."""
    _LAST_STATS["total"] = None
    _LAST_STATS["completed"] = None
    _LAST_STATS["poisoned"] = 0
    _LAST_STATS["poisoned_batches"] = []
    _LAST_STATS["poisoned_batches_truncated"] = False


def _poison_indices(entries):
    """Parse reactor poison-batch strings to sorted batch indices.

    Entries look like "Index 7 (failed 3 times)" (handle_trap_ack_bytes
    format); unparseable entries are skipped best-effort (scalar
    poisoned count stays authoritative).
    """
    import re as _re
    out = []
    for entry in entries or ():
        match = _re.match(r"^Index (\d+)", str(entry))
        if match:
            out.append(int(match.group(1)))
    return sorted(set(out))


def _finish_map_stats(out):
    """Complete accounting for a successful map() and snapshot it."""
    completed = len(out) if out is not None else 0
    poisoned = _LAST_STATS.get("poisoned", 0) or 0
    _LAST_STATS["completed"] = completed
    _LAST_STATS["total"] = completed + poisoned
    return dict(_LAST_STATS)


def _map_return(out, return_stats):
    """map() return path (W-REL6-3.6): plain list by default, or
    (list, stats) with return_stats=True. Default behavior unchanged."""
    stats = _finish_map_stats(out)
    if return_stats:
        return out, stats
    return out


def last_run_stats():
    """Batch accounting for the last map() call (W-REL6-3.6).

    Returns a snapshot dict {"total", "completed", "poisoned",
    "poisoned_batches", "poisoned_batches_truncated"} (batch indices,
    sorted). total =
    completed + poisoned: on_error="skip" immediate skips appear in
    neither (documented lower bound in that mode). completed/total
    are None until a map() succeeds; use map(return_stats=True)
    for per-call exactness under threads.

    poisoned_batches_truncated is True only when the cleanroom's bounded
    relay slot filled up, so poisoned_batches is a prefix of the poisoned
    set rather than all of it. Check it before treating len() as a count;
    `poisoned` itself is always exact.

    ``poisoned_batches`` is populated on the reactor path (the default,
    ``orchestrator=None``/``True``) and on both cleanroom paths. It is
    **EMPTY on the non-reactor path** (``orchestrator=False``), where it
    comes back ``[]`` even when ``poisoned`` is non-zero -- the engine
    exposes only a poisoned COUNT there (``fr_py_poisoned_count()``), not
    the indices, so there is nothing to list. Verified divergence; see
    TD-09 in dev/supervisor/TECH_DEBT_REGISTER.md. Treat ``poisoned`` as
    the portable field and ``poisoned_batches`` as available only on the
    paths above.
    """
    return dict(_LAST_STATS)


def _abort_reason_now(lib):
    """Abort reason without touching abort state (D-PORT2/D6 mirror).

    Returns 0 (unset), 1 (SIGPIPE/downstream close), 2 (fault),
    or None when unknown (no engine / pre-D-PORT2 substrate /
    unreadable). Never raises; never aborts. Query BEFORE the
    handler's own abort — the order is the fix.
    """
    try:
        fn = getattr(lib, "fr_py_abort_reason", None)
    except Exception:
        return None
    if fn is None:
        return None
    try:
        return int(fn())
    except Exception:
        return None


def _helper_death_disposition(kind, eof_ok, reason):
    """D6 abort-aware classification for helper deaths (D-PORT2).

    Returns 'record' (clean drain: file it, continue), 'excuse'
    (expected abort-path exit: file it, mark excused, continue —
    no abort, no raise), or 'fatal' (abort + raise).
    - clean + EOF posted → 'record' (normal drain, unchanged).
    - anything + abort already in flight (reason not in
      (0, None, -1)) → 'excuse' (the helper's non-zero exit is its
      expected emergency path; re-aborting would print a spurious
      FATAL and clobber the abort's own outcome).
    - else → 'fatal' (clean-before-EOF with no abort is tail
      loss; error with no abort is violent death).
    """
    if kind == "clean" and eof_ok:
        return "record"
    if reason not in (0, None, -1):
        return "excuse"
    return "fatal"


def _raise_for_poisoned(npois, strict_poison) -> None:
    """Raise ForkrunPoisonSkip under opt-in strict_poison (D-PORT3).

    Default (False) preserves warn-and-return-partial (Bash -E
    continuation semantics). strict_poison=True maps Bash exit 3 to
    a caller-visible exception carrying the engine's poisoned count.
    Records the count in the last-run stats (W-REL6-3.6) first, so
    it survives the raise for last_run_stats().
    """
    _LAST_STATS["poisoned"] = npois
    if strict_poison and npois:
        raise ForkrunPoisonSkip(
            "forkrun: %d batch(es) poisoned (retry limit reached) "
            "(Bash exit 3); re-run the offending input with a fixed "
            "payload, or run without strict_poison for warn-and-"
            "partial results" % (npois,), count=npois)


def _reactor_poison_summary(lib, state, strict_poison=False) -> None:
    """Poison summary: engine scalar count + reactor batch list."""
    try:
        npois = lib.fr_py_poisoned_count()
    except Exception:
        npois = 0
    # W-REL6-3.6: batch-index accounting FIRST (scalar stays
    # authoritative; the list is empty on poison-free runs and on
    # paths without a reactor batch list) -- so a strict_poison
    # raise below still leaves the batches for last_run_stats().
    _LAST_STATS["poisoned_batches"] = _poison_indices(
        getattr(state, "poisoned_batches", None))
    # The in-process path keeps every index in a Python list, so it is
    # never truncated -- only the cleanroom's fixed-size relay slot can
    # drop indices. Stated explicitly so the flag means one thing.
    _LAST_STATS["poisoned_batches_truncated"] = False
    if npois:
        try:
            os.write(2, ("forkrun [WARN]: %d poisoned batch(es) "
                         "skipped (retry limit reached).\n" % npois
                         ).encode())
        except OSError:
            pass
        _raise_for_poisoned(npois, strict_poison)
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
        # W-REL5-B8: cause fidelity — the first signal death rides
        # along as .signo (None for plain exits). A ForkrunWorkerFailure
        # stays a RuntimeError subclass (Bash exit-1 contract for
        # engine faults; .signo is a typed attribute, not a monkeypatch).
        raise ForkrunWorkerFailure(
            "forkrun: %d worker(s) failed without recovery "
            "(respawn cap reached) (on_error=%s)"
            % (state.n_unrecovered, on_error),
            signo=_failure_signo(getattr(state, "statuses", ())))


def _failure_signo(statuses):
    """First death-signal number in (pid, status) pairs (W-REL5-B8).

    None when no entry is a signal death (plain exits) or no
    statuses are available — the caller still raises, just without
    a signal cause.
    """
    for _pid, _st in statuses or ():
        try:
            if os.WIFSIGNALED(_st):
                return os.WTERMSIG(_st)
        except Exception:
            continue
    return None


def _raise_worker_failure(failed, total, on_error, statuses=None):
    """Common N/M-workers-failed raise (W-REL5-B8).

    Message is identical to the historical raise; the exception
    additionally carries .signo (first signal death, or None) for
    cause fidelity (exceptions.py D-PORT3). Stays a RuntimeError
    subclass — engine faults keep the Bash-exit-1 contract
    (see test_taxonomy.TestCrashStaysRuntimeError).
    """
    raise ForkrunWorkerFailure(
        "forkrun: %d/%d workers failed%s" % (
            len(failed), total, " (on_error=%s)" % on_error),
        signo=_failure_signo(
            statuses if statuses is not None else failed))


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
    # EVERY slot's pid must be REAPED, not just the live ones. A slot
    # the reactor marked dead (worker SIGKILLed mid-run) still owns a
    # real, unreaped child; filtering on slot.alive left that pid
    # behind as a zombie. Found with a fork ledger: state.workers held
    # two slots but teardown was handed one.
    #
    # Dead slots are JOIN-ONLY, never SIGKILLed. Their child has already
    # exited, so there is nothing to kill, and the pid may since have
    # been recycled to an unrelated process -- killing it would take out
    # a bystander. Only live slots get the kill+join treatment.
    live = []
    dead = []
    if state is not None:
        for slot in list(state.workers.values()):
            if not slot.pid or slot.pid <= 0:
                continue
            (live if slot.alive else dead).append(slot.pid)
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
        # W-REL5-B4: bounded (kill already issued above).
        _join_helper_bounded(pid, "worker")
    for pid in dead:
        # Already exited; reap only. No kill -- see the note above.
        _join_helper_bounded(pid, "worker-dead")
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
    for _pid, _name in (
            [(_p, "helper") for _p in extra_pids if _p is not None]
            + ([(orderer_pid, "orderer")]
               if orderer_pid is not None else [])
            + ([(drain_pid, "drain")] if drain_pid is not None
               else [])):
        # W-REL5-B4: bounded (kill already issued above).
        _join_helper_bounded(_pid, _name)

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
    # W-REL2/R11: the spawn_r + fallow_w spares leaked +2 fds/run on
    # the failure path (never in any close list). Every reactor path
    # parks them on state (spawn_r attribute, ctx["fallow_w"]), so
    # closing from state covers all six teardown callers with no
    # signature change. Mark -1 afterwards (a stale number must
    # never be reused); double-close is EBADF-caught, safe.
    if state is not None:
        try:
            _ctx = state.ctx or {}
        except AttributeError:
            _ctx = {}
        for fd in (getattr(state, "spawn_r", -1),
                   _ctx.get("spawn_w", -1),
                   _ctx.get("fallow_w", -1)):
            if fd is None or fd < 0:
                continue
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            state.spawn_r = -1
        except AttributeError:
            pass
        for _k in ("spawn_w", "fallow_w"):
            try:
                if _k in _ctx:
                    _ctx[_k] = -1
            except TypeError:
                pass
        # W-REL2/R11: the scanner death-pipe read end (parked by
        # _execute_ingest_reactor_locked; -1/unset elsewhere).
        # Unclassified on abort paths (no clean/error verdict ever
        # arrived) — without this it leaks +1 fd per failing run.
        try:
            _scan_death = getattr(state, "scan_death_r", -1)
        except AttributeError:
            _scan_death = -1
        if _scan_death is not None and _scan_death >= 0:
            try:
                os.close(_scan_death)
            except OSError:
                pass
            try:
                state.scan_death_r = -1
            except AttributeError:
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
                            workers, on_error, views=True, strict_poison=False, collect, order,
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
    # W-REL6-5: lattice position (executor #5: UMA, materialized,
    # reactor, blocking) + this call's behavior flags.
    _spec = ExecutorSpec(topology="uma", ingest="materialized",
                         supervision="reactor", shape="blocking",
                         collect=collect, splice=splice, c_drain=c_drain,
                         order=order, c_worker_loop=c_worker_loop,
                         c_spawn_loop=c_spawn_loop)
    lib, engine_fds = _init_engine_and_fds(
        lines=lines, bytes_=bytes_, spec=_spec)
    # W-PY22 resume: parse + gate + engine state AFTER init (which
    # zeroes the ledger) and BEFORE any fork. Raises before any
    # child exists. engine_live gates the abort choreography below.
    resume_state = _resume_begin_after_init(
        lib, resume, order=order, mode=mode,
        collect=collect, splice=splice, source=source)
    # C0.7 expected-side baseline. Captured HERE: after the engine exists,
    # after resume-begin has folded in any sidecar, and BEFORE any fork --
    # so no worker of THIS run has committed anything yet.
    #
    # A per-run LOCAL, not a module global, because a nested map() inside
    # a stream() shares this engine: a shared global would carry the outer
    # run's commits into the inner run's comparison (measured: inner run
    # collected 24 while a global counter read 56).
    # C0.7: keep the None sentinel. `... or 0` would turn an unreadable
    # baseline into zero, so a baseline read that fails while the FINAL
    # read succeeds would compare against the CUMULATIVE count and raise
    # on a correct run. None disables the certificate instead.
    _c07_base = _c07_read_committed(lib, 1) if _c07_enabled() else None
    # C0.7: is another run live in this process? Recorded BEFORE the
    # increment below, so it refers to the enclosing run, not this one.
    _c07_nested = _C07_RUN_DEPTH[0] > 0
    _C07_RUN_DEPTH[0] += 1
    _C07_RUNS_STARTED[0] += 1
    # Recorded AFTER our own increment: from here on, any further change
    # means ANOTHER run started inside our measurement window. Recording
    # it before would make every run trip its own check.
    _c07_runs_at_start = _C07_RUNS_STARTED[0]
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
    scan_pid = None
    scan_rc = None
    # W-PY22: pre-try defaults so the abort handler below never
    # NameErrors on early failures (spill/scan, before assignment).
    use_orderer = False
    _zc = bool(views)
    try:
        memfd, size = _spill_to_memfd(src_fd)
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        if lib.fr_py_ingest_done() != RC_OK:
            raise RuntimeError("ingest signal failed")
        # W-PY39: fork the scanner so its pre-flight + publish
        # overlap the setup + worker execution below (bash/NUMA
        # topology). Workers arriving mid-scan trip the pre-flight
        # bail (CASE B); the engine main loop always scans from
        # byte 0, so completeness never depends on the race.
        scan_pid = _fork_materialized_scanner(lib, memfd, engine_fds)

        _flush_stdio()

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
            # W-REL5-E7: no tempfile fallback (floor 3.10).
            coll_fd = os.memfd_create("forkrun_ordered")
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

        def _watch_scanner():
            # W-PY39: the forked materialized scanner runs
            # concurrently with supervision. A clean exit is the
            # normal case (scan finished; workers still draining)
            # and is only recorded. A failed scan aborts the run:
            # without the scanner no EOF can arrive, so waiting
            # workers would hang — fail loud instead.
            nonlocal scan_pid, scan_rc
            if scan_pid is None or scan_rc is not None:
                return
            try:
                wpid, scan_st = os.waitpid(scan_pid, os.WNOHANG)
            except ChildProcessError:
                return
            except OSError:
                return
            if wpid != scan_pid:
                return
            if os.WIFEXITED(scan_st) and \
                    os.WEXITSTATUS(scan_st) == 0:
                scan_rc = 0
                scan_pid = None
                return
            scan_rc = scan_st
            scan_pid = None
            # D-PORT2/D6: query the abort reason BEFORE our own
            # abort — an abort already in flight makes this an
            # expected emergency exit. Retire it as observed (the
            # code stays honest in scan_rc; the abort's own outcome
            # governs the run) instead of raising a spurious fatal
            # over it.
            if _helper_death_disposition(
                    "error", False,
                    _abort_reason_now(lib)) == "excuse":
                return
            try:
                lib.fr_py_abort()
            except Exception:
                pass
            raise RuntimeError(
                "forkrun: materialized scanner failed (status %r)"
                % (scan_st,))

        try:
            reactor_run(state, service=_watch_scanner)
        except KeyboardInterrupt as _ki:
            raise ForkrunInterrupted(_INTERRUPTED_MSG) from _ki

        _reactor_failure_check(state, workers, on_error)

        # Scanner join: strict when observed, proof-based when
        # already reaped by the watch above after healthy workers
        # (workers cannot EOF without a clean scanner finish).
        if scan_pid is not None and scan_rc is None:
            try:
                wpid, scan_st = os.waitpid(scan_pid, os.WNOHANG)
            except ChildProcessError:
                wpid, scan_st = scan_pid, None
            if wpid == 0:
                # W-REL5-B4: bounded (reaped-elsewhere None keeps
                # the proof-based leniency below).
                scan_st = _join_helper_bounded(scan_pid, "scanner")
            # Reaped (or already reaped): clear so teardown never
            # signals a recycled pid.
            scan_pid = None
            if scan_st is not None and not (
                    os.WIFEXITED(scan_st) and
                    os.WEXITSTATUS(scan_st) == 0):
                raise RuntimeError(
                    "forkrun: materialized scanner failed (status %r)"
                    % (scan_st,))

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
                # W-REL5-B4: bounded (None ⇒ reaped elsewhere,
                # same leniency as the old ChildProcessError
                # branch).
                _dst = _join_helper_bounded(drain_pid, "drain")
                if _dst is None:
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
                # W-REL5-B4: bounded (None ⇒ reaped elsewhere,
                # same leniency as the old ChildProcessError
                # branch).
                _ost = _join_helper_bounded(
                    orderer_pid, "orderer", ORDERER_REAP_TIMEOUT)
                if _ost is None:
                    _ost = 0
                if _ost != 0 and not (
                        os.WIFEXITED(_ost) and
                        os.WEXITSTATUS(_ost) == 0):
                    raise RuntimeError(
                        "forkrun: C orderer failed (status %r)"
                        % (_ost,))

        _reactor_poison_summary(lib, state, strict_poison)

        if not collect:
            return None
        if not use_orderer and collect and order == "index":
            # The caller ASKED for ordered output, so a completeness
            # certificate is the natural expectation -- but the C orderer
            # is not in play, so this run gets no verdict at all.
            #
            # This is the dispatch-point warning round 20 asked for.
            # _c07_evaluate cannot cover it: it lives INSIDE the
            # use_orderer branch, so splice and any configuration with
            # the orderer masked (FORKRUN_NO_V1) never reach it. Their
            # silence was fail-closed but opaque -- the safety property
            # held while the operator got nothing to act on.
            #
            # Deliberately not an error: ordered delivery still happens
            # via the fallback path. What is missing is the PROOF, not
            # the ordering.
            try:
                os.write(2, ("forkrun [WARN]: ordered output requested but "
                             "the C orderer is not in use (mode=%s): no C0.7 "
                             "completeness certificate for this run; ordered "
                             "delivery still performed, completeness "
                             "unverified\n" % (mode,)).encode())
            except OSError:
                pass
        if use_orderer:
            records = list(_iter_records(lib, coll_fd, views=_zc))
            # C0.7 observed side: DATA frames THIS collection delivered.
            # len(records) is exactly that -- _iter_records delegates to
            # _split_records_views, which filters non-DATA dispositions,
            # so everything it yields is a DATA frame. Deliberately NOT
            # _FRAME_STATS, which is a module global and would charge a
            # nested run with its parent's frames.
            _c07_observed = len(records)
            # Already batch_idx-ordered by the C orderer; prepend any
            # sidecar output from previously aborted run(s), then sort
            # (committed ranges are jagged — the union of two ordered
            # lists is not ordered). Reads the sidecar (non-destructive;
            # superseded files are removed at the next cumulative
            # publish — W-REL5-C4).
            if resume is not None:
                records = consume_sidecar(resume, records)
            # C0.7 expected side: committed DATA frames MINUS this run's
            # baseline, so a shared engine (a nested map inside a stream)
            # or a resumed run is not charged for frames committed
            # elsewhere. Producers are quiescent: the orderer has been
            # joined and the reactor has returned.
            _c07_now = (_c07_read_committed(lib, 1)
                        if _c07_enabled() else None)
            if _c07_nested or _C07_RUNS_STARTED[0] != _c07_runs_at_start:
                # Either we are nested (an enclosing run's live workers
                # commit to the same engine counter) or a run STARTED
                # inside our measurement window (so someone else's
                # commits landed in our delta). Either way the delta
                # cannot be attributed to this run alone. Refuse rather
                # than certify a number we cannot trust -- and note this
                # covers the ENCLOSING run too, which is charged for a
                # nested run's frames just as surely.
                _c07_no_verdict(
                    "another forkrun run is live or started inside this "
                    "run's measurement window; all runs on this engine "
                    "share one committed-frame counter, so the delta "
                    "cannot be attributed to a single run")
            elif _c07_now is not None and _c07_base is not None:
                _c07_total = int(_c07_now) - int(_c07_base)
                _COMMITTED_FRAMES["total"] = _c07_total
                _COMMITTED_FRAMES["nodes"] = 1
                _c07_evaluate(_c07_total, _c07_observed, lib, mode)
            # Already batch_idx-ordered by the C orderer; no sort.
            return [blob for _, blob in records]
        # Collection is _executor_core.collect_records: drain-vs-direct
        # and order-index-vs-none are mechanics, not lifecycle shape.
        return collect_records(use_drain=use_drain,
                               results_fd=results_fd, out_fds=out_fds,
                               order=order, lib=lib, views=_zc)
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
        # C0.7: leave the nesting depth on EVERY exit path, including
        # aborts and exceptions. A leaked depth would make every later
        # top-level run believe it is nested and silently stop
        # certifying -- a failure that looks like a pass.
        _C07_RUN_DEPTH[0] -= 1
        _teardown_reactor(lib, state, out_fds=out_fds,
                          out_hold=out_hold, memfd=memfd,
                          src_fd=src_fd, must_close=must_close,
                          extra_pids=[scan_pid] if scan_pid else [],
                          orderer_pid=orderer_pid, order_r=order_r,
                          order_w=order_w, trap_r=trap_r, trap_w=trap_w,
                          coll_fd=coll_fd, coll_hold=coll_hold,
                          drain_pid=drain_pid, results_fd=results_fd,
                          spare_signal_w=signal_w)


def _suppliers_finished(helpers, num_nodes):
    """W-STREAMDRAIN: True once the scanners have all been reaped.

    helpers["scan"] gains a key per node as each scanner is reaped, so
    its length reaching num_nodes means "all scanners finished". Note
    this is necessary but NOT sufficient on its own -- scanners exit
    AFTER writing their spawn requests, so requests can still be
    buffered. Use _spawn_quiescent() for the spare-drop decision.
    """
    scan = helpers.get("scan") or {}
    return len(scan) >= num_nodes


def _spawn_quiescent(state, scanner_done):
    """W-STREAMDRAIN: C1 at the parent boundary -- no further worker can
    appear, so a signal-pipe EOF would be truthful.

    Three conditions, ALL required, mirroring EOF_PROTOCOL.md §1's
    ordering (the supplier must declare done, C1, before liveness, C2,
    is allowed to conclude EOF):

    1. ``scanner_done`` -- the supplier will produce no further spawn
       requests. Necessary, not sufficient: scanners exit *after*
       writing their requests, so requests can still be buffered.
    2. no live worker -- C2.
    3. the spawn pipe holds nothing buffered. A request the scanner
       already wrote is still acted on next round, and select() says so
       soundly: a buffered request makes the fd readable.

    Getting this wrong is silent data loss, not a hang. Workers fork
    incrementally as the scan advances, so "no live worker" is briefly
    true while the scanner still has another to fork. Dropping the
    parent's spare signal write end then hands the pipe a false EOF,
    the C drain child exits on it believing it is finished, and every
    byte the later worker emits is emitted and acked but never
    delivered. Measured: 4092 of 18890 bytes silently dropped in ~5-10%
    of streaming runs, with no exception, no stderr, and a clean
    drain-side exit (rc=0, nothing undrained).
    """
    if not scanner_done:
        return False
    if any(s.alive for s in state.workers.values()):
        return False
    sr = getattr(state, "spawn_r", -1)
    if sr is not None and sr >= 0:
        # function-local, matching this module's convention: every other
        # select use in run.py imports here rather than at module scope.
        import select as _select
        try:
            ready, _, _ = _select.select([sr], [], [], 0)
        except (OSError, ValueError):
            return False
        if ready:
            return False
    return True


def _close_spare_fd(state, fd):
    """Drop a spare signal write end (W-REL6-5: single implementation).

    The spare is dup'd for future respawns but must close for signal
    EOF; idempotent (invalid/None fds pass through). Resets
    state.ctx["signal_w"] on close (respawns re-dup from the live
    end; a stale ctx fd would starve the drain). Unifying the seven
    inline copies: the no-reset copies all sat post-use
    (finally/teardown with state discarded), so the reset is
    unobservable there. Returns None when closed, else the input fd
    (callers rebind: ``spare_signal_w = _close_spare_fd(...)``).
    """
    if fd is not None and fd >= 0:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            state.ctx["signal_w"] = -1
        except (AttributeError, TypeError):
            pass
        return None
    return fd


def _watch_helper_deaths(lib, scan_pid, fallow_pid, helpers, gate_issued):
    """Reap helper deaths, nonblocking (W-REL6-5: single implementation).

    Unifies the _watch_live / _watch_helpers twins (plain ingest
    paths): scanner death is fatal (unpublished tail would be
    silently lost); reaper death aborts too (acks would EPIPE);
    scanner exit 0 before the gate is equally fatal (early 0 means
    the tail it never saw is lost). ``gate_issued`` is the caller's
    gate flag (dict entry or plain bool -- same rule); ``helpers``
    receives scan_rc/fallow_rc. Reactor variants keep their own
    death-pipe watchers (different mechanism, not merged).
    """
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


def _parse_drain_quantum(drain, coll_fd, use_orderer, out_fds, per_worker,
                         sig_struct):
    """Incremental preads into drain["pending"] (W-REL6-5: single impl).

    Unifies the _parse_quantum twins (NUMA locked/stream): orderer
    collection-file preads or per-worker memfd preads (+ optional
    reassembly), all through the shared ``drain`` dict. Returns True
    if any complete record buffered. Zero mode branches (same code,
    parameterized carriers).
    """
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
        _consume_sig_wakeups(drain, sig_struct)
    else:
        # W-PYONCEDRAIN: drain each worker at most ONCE per quantum,
        # whatever the number of its signals in this read. Draining per
        # signal is pure redundancy -- a worker that emitted 10 signals
        # between two reactor rounds has 10 wakeups but one contiguous
        # region of new bytes in its memfd, and 9 of those 10 preads
        # return nothing. On a 1293-signal / 1292-record stream run that
        # was 1411 preads where draining per worker needs ~28. Same
        # records, same order, far fewer syscalls.
        _seen = None
        _sigpos = drain["sig_pos"]
        while len(drain["sig_buf"]) - _sigpos >= sig_struct.size:
            wid, _idx = sig_struct.unpack_from(
                drain["sig_buf"], _sigpos)
            _sigpos += sig_struct.size
            if 0 <= wid and wid < len(out_fds):
                if _seen is None:
                    _seen = set()
                _seen.add(wid)
        drain["sig_pos"] = _sigpos
        if _seen:
            for wid in _seen:
                while len(per_worker) <= wid:
                    per_worker.append([0, b""])
                for _bidx, _disp, _blob in _drain_worker_memfd_terminal(
                        out_fds[wid], per_worker[wid]):
                    if drain["reassembly"] is None:
                        if _disp == _DISP_DATA:
                            drain["pending"].append(_blob)
                    else:
                        drain["reassembly"].add_disposition(
                            _bidx, _disp, _blob)
                        for _, ordered in drain["reassembly"].drain():
                            drain["pending"].append(ordered)
                got = True
    # Compact the consumed prefix once per quantum, not once per signal
    # (see _consume_sig_wakeups).
    if drain["sig_pos"]:
        drain["sig_buf"] = drain["sig_buf"][drain["sig_pos"]:]
        drain["sig_pos"] = 0
    return got


def _consume_sig_wakeups(drain, sig_struct):
    """Drop consumed signal bytes from an orderer-path drain.

    W-PYSIGCURSOR: the signal pipe carries wakeups only (16 bytes each:
    worker id + batch index) when the orderer owns ordering, so the
    content is ignored here -- but the bytes still have to GO. Every
    quantum used to drop them one at a time with
    ``buf = buf[sig_struct.size:]``, which recopies the ENTIRE
    remaining buffer per signal. With one signal per batch that is
    quadratic in signals-per-read: a 60MB input at one line per batch is
    ~700k signals, and stream() stopped completing at all (measured
    >120s against bash's 1.22s for the same input).

    Trim to the last whole signal in one slice. A torn trailing signal
    (1-15 bytes, the writer died mid-write) is deliberately KEPT so the
    caller's existing torn-signal handling still sees it -- and because
    signals are single 16-byte writes they are atomic, so a clean EOF
    leaves no remainder and the buffer drains to empty.

    The buffer must actually reach empty: the stream's StopIteration is
    anchored on ``sig_eof AND not sig_buf``. Leaving the signals in
    place hangs the stream forever (which is what the first cut of this
    change did -- test_c_drain_stream_ordered hung in reactor_loop's
    select).
    """
    buf = drain["sig_buf"]
    if not buf:
        return
    size = sig_struct.size
    keep = len(buf) % size
    pos = len(buf) - keep
    if pos:
        drain["sig_buf"] = buf[pos:]


def _poll_ingest_once(lib, helpers, pipe):
    """One nonblocking ingest-death classification (W-REL6-5: single).

    Unifies the _poll_ingest twins (NUMA locked/stream): records
    definitive outcomes (pipe consumed/closed inside); raises on
    error. Same rule both callers.
    """
    if helpers["ingest_kind"] is not None:
        return
    from ._reactor import check_scanner_death as _check_death
    kind, code = _check_death(
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


def _pipeline_quiescent(helpers, num_nodes):
    """Full-pipeline quiescence (W-REL6-5: single implementation).

    Unifies the _all_helpers_done twins (NUMA locked/stream): ingest
    clean + index/scan coverage on every node. Ingest-clean alone
    never triggers the verdict (indexers/scanners still spinning
    up) -- only the whole pipeline being done does.
    """
    return (helpers["ingest_kind"] == "clean"
            and len(helpers["index"]) >= num_nodes
            and len(helpers["scan"]) >= num_nodes)


def _execute_streaming_reactor(payload, source, *, lines, bytes_,
                               workers, on_error, strict_poison=False, mode="python",
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
    # W-REL6-5: lattice position (executor #6: UMA, materialized,
    # reactor, generator) + this call's behavior flags.
    _spec = ExecutorSpec(topology="uma", ingest="materialized",
                         supervision="reactor", shape="generator",
                         collect=True, splice=splice, c_drain=c_drain,
                         order=order)
    lib, engine_fds = _init_engine_and_fds(
        lines=lines, bytes_=bytes_, spec=_spec)
    # W-PY22 resume: parse + gate + engine state AFTER init (which
    # zeroes the ledger) and BEFORE any fork. engine_live gates the
    # abort choreography below.
    resume_state = _resume_begin_after_init(
        lib, resume, order=order, mode=mode,
        collect=True, splice=splice, source=source)
    # C0.7: count this run in the nesting depth. This executor does
    # NOT certify, but its workers commit to the same engine counter,
    # so a nested run must see depth > 0 and refuse. Omitting it here
    # is exactly what let a map() inside a stream() certify silently.
    _C07_RUN_DEPTH[0] += 1
    _C07_RUNS_STARTED[0] += 1
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
    scan_pid = None
    scan_rc = None
    try:
        memfd, size = _spill_to_memfd(src_fd)
        try:
            os.lseek(memfd, 0, os.SEEK_SET)
        except OSError:
            pass
        if lib.fr_py_ingest_done() != RC_OK:
            raise RuntimeError("ingest signal failed")
        # W-PY39: fork the scanner so its pre-flight + publish
        # overlap the setup + worker execution below (bash/NUMA
        # topology). Workers arriving mid-scan trip the pre-flight
        # bail (CASE B); the engine main loop always scans from
        # byte 0, so completeness never depends on the race.
        scan_pid = _fork_materialized_scanner(lib, memfd, engine_fds)

        _flush_stdio()

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
            # W-REL5-E7: no tempfile fallback (floor 3.10).
            coll_fd = os.memfd_create("forkrun_ordered")
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

        def _pump_drain_c():
            # W-PY21-A results-pipe consumer: spare management +
            # drain reap + incremental parse. Same StopIteration
            # contract as _pump_drain below.
            nonlocal spare_signal_w
# W-STREAMDRAIN: scan_rc is the C1 signal here (single UMA scanner
            # reaped). Workers fork incrementally, so "no live worker"
            # can be briefly true while the scanner still has another to
            # fork; dropping the spare then hands the drain a false EOF
            # and every byte the later worker emits is lost. See
            # EOF_PROTOCOL.md §1 (C1 before C2).
            if _spawn_quiescent(state, scan_rc is not None):
                spare_signal_w = _close_spare_fd(state, spare_signal_w)
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
        # W-PYSIGCURSOR: consumed-signal cursor into sig_buf. A list so
        # the nested drain generator can rebind sig_buf (a local) while
        # the offset stays reachable. Compacted once per quantum, never
        # per signal.
        sig_pos = [0]
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
            # No live worker left AND the scanner is reaped: drop the
            # parent's spare signal write end (kept for future
            # respawns) so the signal pipe hits EOF and the drain can
            # terminate. Idempotent.
# W-STREAMDRAIN: scan_rc is the C1 signal here (single UMA scanner
            # reaped). Workers fork incrementally, so "no live worker"
            # can be briefly true while the scanner still has another to
            # fork; dropping the spare then hands the drain a false EOF
            # and every byte the later worker emits is lost. See
            # EOF_PROTOCOL.md §1 (C1 before C2).
            if _spawn_quiescent(state, scan_rc is not None):
                spare_signal_w = _close_spare_fd(state, spare_signal_w)
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
                # W-PYSIGCURSOR: cursor, not a reslice per signal — the
                # per-signal copy is quadratic in signals-per-read.
                _sp = sig_pos[0]
                while len(sig_buf) - _sp >= _sig.size:
                    _sp += _sig.size
                sig_pos[0] = _sp
                if _sp:
                    sig_buf = sig_buf[_sp:]
                    sig_pos[0] = 0
            else:
                _sp = sig_pos[0]
                while len(sig_buf) - _sp >= _sig.size:
                    wid, _idx = _sig.unpack_from(sig_buf, _sp)
                    _sp += _sig.size
                    if 0 <= wid:
                        while len(per_worker) <= wid:
                            per_worker.append([0, b""])
                        if wid < len(out_fds):
                            for _bidx, _disp, _blob in \
                                    _drain_worker_memfd_terminal(
                                        out_fds[wid], per_worker[wid]):
                                if reassembly is None:
                                    if _disp == _DISP_DATA:
                                        _pending.append(_blob)
                                else:
                                    reassembly.add_disposition(
                                        _bidx, _disp, _blob)
                                    for _, ordered in reassembly.drain():
                                        _pending.append(ordered)
                if _sp:
                    sig_buf = sig_buf[_sp:]
                    sig_pos[0] = 0
            if _pending:
                return _pending.popleft()
            # Exhausted for now: StopIteration only when the reactor
            # has no live workers AND the signal pipe hit EOF (same
            # EOF-anchored rule as _drain_records). A torn trailing
            # signal (1-15 bytes, nobody left to complete it) is
            # discarded loudly instead of polling forever (W-REL5-C7).
            # Otherwise None (not EOF — keep polling).
            if (not any(s.alive for s in state.workers.values())
                    and sig_eof):
                if sig_buf:
                    try:
                        os.write(2, ("forkrun [WARN]: torn trailing "
                                     "signal (%d byte(s)) discarded "
                                     "at EOF.\n" % len(sig_buf)
                                     ).encode())
                    except OSError:
                        pass
                    sig_buf = b""
                    sig_pos[0] = 0
                if reassembly is not None:
                    for _, ordered in reassembly.final_drain():
                        _pending.append(ordered)
                    # Streaming boundary: records yielded BEFORE this
                    # point cannot be retracted, so the error is raised
                    # at detection rather than at the end, and says so.
                    # A contradictory stream must not complete
                    # successfully just because the contradiction
                    # happened to arrive before EOF.
                    _raise_on_disposition_conflicts(
                        reassembly,
                        "stream() [records already yielded before this "
                        "point are NOT withdrawn]")
                    if _pending:
                        return _pending.popleft()
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
                                return _pending.popleft()
                else:
                    for _wid in range(len(per_worker)):
                        if _wid >= len(out_fds):
                            continue
                        for _bidx, _disp, _blob in \
                                _drain_worker_memfd_terminal(
                                    out_fds[_wid], per_worker[_wid]):
                            if reassembly is None:
                                if _disp == _DISP_DATA:
                                    _pending.append(_blob)
                            else:
                                reassembly.add_disposition(
                                    _bidx, _disp, _blob)
                                for _, ordered in reassembly.drain():
                                    _pending.append(ordered)
                    if _pending:
                        return _pending.popleft()
                raise StopIteration
            return None

        # W-PYPENDING: deque, not list. These were popped with
        # pop(0), which shifts every remaining element -- quadratic
        # in the backlog. At 79k batches that single call site was
        # 0.35s of a 1.8s streaming run; with the input at one line
        # per batch the same shape stopped stream() completing at
        # all. popleft() is O(1).
        _pending: list = _deque()
        _stream_ok = False

        def _watch_scanner():
            # W-PY39: the forked materialized scanner runs
            # concurrently with supervision. A clean exit is the
            # normal case (scan finished; workers still draining)
            # and is only recorded. A failed scan aborts the run:
            # without the scanner no EOF can arrive, so waiting
            # workers would hang — fail loud instead.
            nonlocal scan_pid, scan_rc
            if scan_pid is None or scan_rc is not None:
                return
            try:
                wpid, scan_st = os.waitpid(scan_pid, os.WNOHANG)
            except ChildProcessError:
                return
            except OSError:
                return
            if wpid != scan_pid:
                return
            scan_pid = None
            if os.WIFEXITED(scan_st) and \
                    os.WEXITSTATUS(scan_st) == 0:
                scan_rc = 0
                return
            scan_rc = scan_st
            # D-PORT2/D6: query the abort reason BEFORE our own
            # abort — an abort already in flight makes this an
            # expected emergency exit. Retire it as observed (the
            # code stays honest in scan_rc; the abort's own outcome
            # governs the run) instead of raising a spurious fatal
            # over it.
            if _helper_death_disposition(
                    "error", False,
                    _abort_reason_now(lib)) == "excuse":
                return
            try:
                lib.fr_py_abort()
            except Exception:
                pass
            raise RuntimeError(
                "forkrun: materialized scanner failed (status %r)"
                % (scan_st,))

        try:
            try:
                yield from reactor_loop(
                    state,
                    drain_gen=_pump_drain_c if use_drain else _pump_drain,
                    service=_watch_scanner)
            finally:
                pass
        except BaseException as _exc:
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
            if isinstance(_exc, KeyboardInterrupt) and not isinstance(
                    _exc, ForkrunInterrupted):
                # W-REL5-B2: stream taxonomy matches the blocking
                # executors (abort already issued by the choreography
                # above) — never bare KeyboardInterrupt.
                raise ForkrunInterrupted(_INTERRUPTED_MSG) from _exc
            raise

        # W-PY39 scanner join: strict when observed, proof-based
        # when already reaped by the watch above after healthy
        # workers (workers cannot EOF without a clean scanner
        # finish).
        if scan_pid is not None and scan_rc is None:
            try:
                wpid, scan_st = os.waitpid(scan_pid, os.WNOHANG)
            except ChildProcessError:
                wpid, scan_st = scan_pid, None
            if wpid == 0:
                # W-REL5-B4: bounded (reaped-elsewhere None keeps
                # the proof-based leniency below).
                scan_st = _join_helper_bounded(scan_pid, "scanner")
            # Reaped (or already reaped): clear so teardown never
            # signals a recycled pid.
            scan_pid = None
            if scan_st is not None and not (
                    os.WIFEXITED(scan_st) and
                    os.WEXITSTATUS(scan_st) == 0):
                raise RuntimeError(
                    "forkrun: materialized scanner failed (status %r)"
                    % (scan_st,))
        else:
            scan_pid = None

        _reactor_failure_check(state, workers, on_error)

        if use_drain:
            # Workers are gone and the results pipe hit EOF, so the
            # drain has exited — join it for its rc (worker error
            # above already raised; teardown covers that path).
            # W-REL5-B4: bounded.
            if drain_st["alive"]:
                _dst = _join_helper_bounded(drain_pid, "drain")
                if _dst is not None:
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
                # W-REL5-B4: bounded (None ⇒ reaped elsewhere,
                # same leniency as the old ChildProcessError
                # branch).
                _ost = _join_helper_bounded(
                    orderer_pid, "orderer", ORDERER_REAP_TIMEOUT)
                if _ost is None:
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

        _reactor_poison_summary(lib, state, strict_poison)
        # W-PY22: normal exhaustion — generator completed; the
        # abort handler above must not fire on the way out.
        _stream_ok = True
    finally:
        # C0.7: leave the nesting depth on every exit path.
        _C07_RUN_DEPTH[0] -= 1
        spare_signal_w = _close_spare_fd(state, spare_signal_w)
        _teardown_reactor(lib, state, signal_r=signal_r,
                          out_fds=out_fds, out_hold=out_hold,
                          memfd=memfd, src_fd=src_fd,
                          must_close=must_close,
                          extra_pids=[scan_pid] if scan_pid else [],
                          orderer_pid=orderer_pid, order_r=order_r,
                          order_w=order_w, trap_r=trap_r, trap_w=trap_w,
                          coll_fd=coll_fd, coll_hold=coll_hold,
                          drain_pid=drain_pid, results_fd=results_r,
                          spare_signal_w=spare_signal_w)


def _execute_ingest_reactor_locked(payload, source, *, sink, lines,
                                   bytes_, workers, on_error, views=True,
                                   strict_poison=False, collect,
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
                           reactor_watch_fds,
                           spawn_orderer)
    import fcntl as _fcntl

    if mode not in ("python", "splice"):
        raise NotImplementedError(
            "v0 supports mode='python' only (spawn/plugin are Stage 5)")
    if not (nodes == "auto" or nodes == 1):
        raise NotImplementedError(
            "v0 supports nodes='auto'/1 only (multi-node is Stage 5)")
    # W-REL6-5: lattice position (executor #7: UMA, streaming,
    # reactor, blocking) + this call's behavior flags.
    _spec = ExecutorSpec(topology="uma", ingest="streaming",
                         supervision="reactor", shape="blocking",
                         collect=collect, splice=splice, c_drain=c_drain,
                         order=order)
    lib, engine_fds = _init_engine_and_fds(
        lines=lines, bytes_=bytes_, spec=_spec)
    # W-PY22 resume: parse + gate + engine state AFTER init (which
    # zeroes the ledger) and BEFORE any fork. engine_live gates the
    # abort choreography below.
    resume_state = _resume_begin_after_init(
        lib, resume, order=order, mode=mode,
        collect=collect, splice=splice, source=source)
    # C0.7: count this run in the nesting depth. This executor does
    # NOT certify, but its workers commit to the same engine counter,
    # so a nested run must see depth > 0 and refuse. Omitting it here
    # is exactly what let a map() inside a stream() certify silently.
    _C07_RUN_DEPTH[0] += 1
    _C07_RUNS_STARTED[0] += 1
    engine_live = True
    # W-PY22: pre-try default so the abort handler never NameErrors
    # on early failures (before assignment below).
    _zc = bool(views)
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
        # W-REL1/R1: no spawn pipe (scanner disarmed above) — keep
        # the names bound for the close-out below.
        spawn_r, spawn_w = None, None

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
            # W-REL5-E7: no tempfile fallback (floor 3.10).
            coll_fd = os.memfd_create("forkrun_ordered")
            orderer_pid = spawn_orderer(order_r, coll_fd,
                                        engine_fds=engine_fds,
                                        out_fds=out_fds)

        trap_r, trap_w = os.pipe()

        if use_drain:
            # Workers signal the drain; the parent keeps the spare
            # write end for respawns (closed when no worker is live).
            signal_r, signal_w, _ = make_pipe()

        _flush_stdio()

        # Fallow reaper child (plain fork: no spawn pipe needed).
        # Pre-fork default: the finally block reaps ingest_pid even when
        # the run aborts before the ingest child is forked.
        ingest_pid = None
        fallow_pid = os.fork()
        if fallow_pid == 0:
            try:
                scrub_fds(engine_fds | {fallow_r, memfd})
                rc = lib.fr_py_fallow_loop(fallow_r, memfd)
            except BaseException:
                rc = 1
            os._exit(rc if isinstance(rc, int) and 0 <= rc < 256 else 1)
        # Plain scanner with a death pipe (bash SCAN_DEATH).
        # W-REL1/R1: spawn DISARMED (spawn_w=-1 → fr_py_scan
        # semantics). A spawn-aware scanner forks workers during
        # pre-flight via the parent's per-chunk reactor poll; those
        # early workers trip the CASE-B bail and phase 1 with
        # complete input publishes nothing — racy silent suffix
        # loss (workers exit clean, no warning, no poison).
        # Same rationale as _execute_ingest_stream_reactor's
        # spawn_w=-1; the locked ingest path never had spawn
        # requests either. Dynamic scaling on this path never
        # worked (ceiling == workers: extras only forked into the
        # early-exit cascade) — nothing that works is lost.
        scan_pid, scan_death_r = fork_scanner_with_death_pipe(
            lib, memfd, -1, engine_fds)
        # Parent drops copies it never uses (no scanner-owned
        # spawn_w now — both spawn ends close; the fallow read end
        # belongs to the reaper). The SPARES for future respawns
        # (fallow_w) stay open in ctx.
        for _fd in (spawn_w, spawn_r, fallow_r):
            if _fd is None:
                continue
            try:
                os.close(_fd)
            except OSError:
                pass
        spawn_w = None
        spawn_r = None
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
        state.spawn_r = -1  # W-REL1/R1: spawn disarmed (see above)
        state.trap_ack_r = trap_r
        # W-REL2/R11: park the scanner death-pipe read end on state
        # so teardown can close it on paths where the death pipe is
        # never definitively classified (abort before clean/error —
        # otherwise +1 fd/run). _watch_helpers syncs this alongside
        # the local on consume.
        state.scan_death_r = scan_death_r

        def _watch_helpers():
            nonlocal scan_death_r
            scan_death_r = _watch_ingest_helpers(
                lib, fallow_pid=fallow_pid, scan_pid=scan_pid,
                helpers=helpers, scan_death_r=scan_death_r, state=state,
                gate_issued=gate_issued)

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

        # W-PYINGESTCHILD: the spill runs in a FORKED CHILD, so the
        # parent does nothing but run the reactor.
        #
        # Previously the parent interleaved the copy with the reactor,
        # one 64KB pipe quantum at a time. A pipe hands over 64KB per
        # read, so a 533MB stream is ~8,100 quanta, and each one ran
        # read + pwrite + reactor_poll_once + _watch_helpers +
        # _maybe_fork_workers on the single thread that also has to
        # service the drain. Measured cost of that interleaving on UMA
        # with THP on: reactor default +77% (light) / +93% (medium)
        # for a pipe, against +15% / +13% for the fail-fast path that
        # does the same copy without the reactor. NUMA never paid it --
        # its ingest has its own process.
        #
        # This is a parity fix, not just a speed fix: the Bash frontend
        # backgrounds the UMA spill too -- the same shape it uses for
        # NUMA, where ingest has its own process. Python was the only
        # frontend doing this copy inline on the reactor thread.
        # (Named deliberately, not by path: test_reactor's purity gate
        # forbids Bash references in the package source.)
        #
        # The child BLOCKS on the source, so O_NONBLOCK is neither set
        # nor needed here; nothing on the parent's side reads src_fd
        # any more.
        src_fd, must_close = _prepare_ingest_source(src_fd, must_close)
        ingest_death_r, ingest_death_w = os.pipe()
        ingest_pid = os.fork()
        if ingest_pid == 0:
            # Child — never returns.
            rc = 0
            try:
                os.close(ingest_death_r)
                # scrub_fds is module-level (line 52). Importing it here
                # would make it a LOCAL of this whole function for the
                # rest of the body -- and the fallow child forked ABOVE
                # this point references it before any local assignment
                # runs, so it died with UnboundLocalError. Cheap trap.
                scrub_fds(engine_fds | {src_fd, memfd, ingest_death_w})
                _ingest_copy_loop(src_fd, memfd, lib=lib)
            except BaseException:
                rc = 1
            finally:
                os._exit(rc)
        try:
            os.close(ingest_death_w)
        except OSError:
            pass
        ingest_death_w = None
        try:
            # Parent: service the reactor until the ingest child closes
            # its death pipe. Blocking here (rather than spinning) is
            # what lets the copy overlap the run at all -- previously
            # the parent was the thing doing the copy.
            ingest_done = False
            while not ingest_done:
                _watch_helpers()
                _maybe_fork_workers()
                watch = [ingest_death_r] + reactor_watch_fds(state)
                try:
                    import select as _select
                    readable, _, _ = _select.select(watch, [], [], 0.02)
                except (OSError, ValueError):
                    readable = []
                if ingest_death_r in readable or ingest_death_r < 0:
                    ingest_done = True
                elif any(fd != ingest_death_r for fd in readable):
                    reactor_poll_once(state)
                    _watch_helpers()
                    _maybe_fork_workers()
            # The child's exit status is the only channel it has, and
            # the spill length is simply the memfd's size -- no IPC.
            _st = _join_helper_bounded(ingest_pid, "ingest")
            # Close it HERE, on the joined path -- marking it -1 without
            # closing leaks the descriptor (the finally's guard would
            # then skip it). Child exit is the EOF, so the read end is
            # already dead.
            try:
                os.close(ingest_death_r)
            except OSError:
                pass
            ingest_death_r = -1
            if _st is not None and not (os.WIFEXITED(_st)
                                        and os.WEXITSTATUS(_st) == 0):
                lib.fr_py_abort()
                raise RuntimeError(
                    "forkrun: ingest child failed (status %r)" % (_st,))
            # Recovered from the memfd rather than accumulated in the
            # parent: with the copy in a child, the parent no longer
            # sees every write.
            try:
                total_written = os.fstat(memfd).st_size
            except OSError:
                total_written = 0
        except KeyboardInterrupt as _ki:
            lib.fr_py_abort()
            raise ForkrunInterrupted(_INTERRUPTED_MSG) from _ki
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
                        # W-REL1/R1: inline close — the
                        # _execute_ingest-local helper of the same
                        # name is not in scope here; its bare
                        # reference was a latent NameError on this
                        # empty-input branch (unreachable pre-flip:
                        # the default never rode the reactor).
                        if fallow_w is not None:
                            try:
                                os.close(fallow_w)
                            except OSError:
                                pass
                            fallow_w = None
                            state.ctx["fallow_w"] = -1
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
            except KeyboardInterrupt as _ki:
                raise ForkrunInterrupted(_INTERRUPTED_MSG) from _ki
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
            # W-REL5-B4: bounded (None ⇒ reaped elsewhere, same
            # leniency as the old ChildProcessError branch).
            if signal_w is not None:
                try:
                    os.close(signal_w)
                except OSError:
                    pass
                signal_w = None
                state.ctx["signal_w"] = -1
            _dst = _join_helper_bounded(drain_pid, "drain")
            if _dst is None:
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
                # W-REL5-B4: bounded (None ⇒ reaped elsewhere,
                # same leniency as the old ChildProcessError
                # branch).
                _ost = _join_helper_bounded(
                    orderer_pid, "orderer", ORDERER_REAP_TIMEOUT)
                if _ost is None:
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
            # bounded join proves a clean finish (W-REL5-B4).
            scan_st = _join_helper_bounded(scan_pid, "scanner")
            if scan_st is not None and not (
                    os.WIFEXITED(scan_st) and
                    os.WEXITSTATUS(scan_st) == 0):
                raise RuntimeError(
                    "forkrun: ingest scanner failed (status %r)"
                    % (scan_st,))
        if fallow_pid is not None and helpers["fallow_rc"] is None:
            # W-REL5-B4: bounded (WARN-lenient below covers None).
            fallow_st = _join_helper_bounded(fallow_pid, "fallow")
            if fallow_st is not None and not (
                    os.WIFEXITED(fallow_st) and
                    os.WEXITSTATUS(fallow_st) == 0):
                try:
                    os.write(2, b"forkrun [WARN]: ingest reaper exited "
                             b"abnormally; ingress may not be fully "
                             b"reclaimed.\n")
                except OSError:
                    pass

        _reactor_poison_summary(lib, state, strict_poison)

        if not collect:
            return None
        if use_orderer:
            records = list(_iter_records(lib, coll_fd, views=_zc))
            # Already batch_idx-ordered by the C orderer; prepend any
            # sidecar output from previously aborted run(s), then sort
            # (committed ranges are jagged). Reads the sidecar
            # (non-destructive — W-REL5-C4).
            if resume is not None:
                records = consume_sidecar(resume, records)
            return [blob for _, blob in records]
        # Collection is _executor_core.collect_records: drain-vs-direct
        # and order-index-vs-none are mechanics, not lifecycle shape.
        return collect_records(use_drain=use_drain,
                               results_fd=results_fd, out_fds=out_fds,
                               order=order, lib=lib, views=_zc)
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
        # C0.7: leave the nesting depth on every exit path.
        _C07_RUN_DEPTH[0] -= 1
        # The ingest death pipe is ours on every exit path, not just
        # the joined one: a failure before the join would leak both
        # ends. The child's own copy was closed inside the child.
        if ingest_death_r is not None and ingest_death_r >= 0:
            try:
                os.close(ingest_death_r)
            except OSError:
                pass
            ingest_death_r = -1
        _teardown_reactor(lib, state, out_fds=out_fds,
                          out_hold=out_hold, memfd=memfd,
                          mem_hold=mem_hold, src_fd=src_fd,
                          must_close=must_close,
                          extra_pids=[p for p in (fallow_pid, scan_pid,
                                                      ingest_pid)
                                      if p is not None],
                          # W-REL5-B4: orderer_pid/order_r were MISSING
                          # here. On the success path the orderer is
                          # joined explicitly above, so the omission was
                          # invisible; on any ABORT before that join the
                          # orderer child defaulted to None, was never
                          # killed or reaped, and became a zombie that
                          # pinned its pid. Found by forking every site in
                          # this path and diffing the ledger against what
                          # teardown was told about.
                          orderer_pid=orderer_pid, order_r=order_r,
                          order_w=order_w, trap_r=trap_r, trap_w=trap_w,
                          coll_fd=coll_fd, coll_hold=coll_hold,
                          drain_pid=drain_pid, results_fd=results_fd,
                          spare_signal_w=signal_w)


def _execute_ingest_stream_reactor(payload, source, *, lines, bytes_,
                                     workers, on_error, strict_poison=False, mode="python",
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
    # W-REL6-5: lattice position (executor #8: UMA, streaming,
    # reactor, generator) + this call's behavior flags.
    _spec = ExecutorSpec(topology="uma", ingest="streaming",
                         supervision="reactor", shape="generator",
                         collect=True, splice=splice, c_drain=c_drain,
                         order=order)
    lib, engine_fds = _init_engine_and_fds(
        lines=lines, bytes_=bytes_, spec=_spec)
    # W-PY22 resume: parse + gate + engine state AFTER init (which
    # zeroes the ledger) and BEFORE any fork. engine_live gates the
    # abort choreography below.
    resume_state = _resume_begin_after_init(
        lib, resume, order=order, mode=mode,
        collect=True, splice=splice, source=source)
    # C0.7: count this run in the nesting depth. This executor does
    # NOT certify, but its workers commit to the same engine counter,
    # so a nested run must see depth > 0 and refuse. Omitting it here
    # is exactly what let a map() inside a stream() certify silently.
    _C07_RUN_DEPTH[0] += 1
    _C07_RUNS_STARTED[0] += 1
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
            # W-REL5-E7: no tempfile fallback (floor 3.10).
            coll_fd = os.memfd_create("forkrun_ordered")
            orderer_pid = spawn_orderer(order_r, coll_fd,
                                        engine_fds=engine_fds,
                                        out_fds=out_fds)

        trap_r, trap_w = os.pipe()

        _flush_stdio()

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
            signal_w = _retire_parent_signal(signal_w, state,
                                        spare_signal_w)

        def _fork_workers_now():
            for _ in range(workers):
                if state.spawn_worker(node=0) is None:
                    break
            _drop_parent_signal()
            fstate["workers"] = True
            fstate["fork_at"] = _time.monotonic()
            _fork_cdrain_if_needed()

        def _watch_helpers():
            nonlocal scan_death_r
            scan_death_r = _watch_ingest_helpers(
                lib, fallow_pid=fallow_pid, scan_pid=scan_pid,
                helpers=helpers, scan_death_r=scan_death_r, state=state,
                gate_issued=gate["issued"])

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

        src_fd, must_close = _prepare_ingest_source(src_fd, must_close)
        try:
            fl = _fcntl.fcntl(src_fd, _fcntl.F_GETFL)
            _fcntl.fcntl(src_fd, _fcntl.F_SETFL, fl | os.O_NONBLOCK)
        except OSError:
            pass

        # Drain state (same two shapes as _execute_streaming_reactor).
        _sig = struct.Struct("<QQ")
        # W-PYPENDING: deque -- popleft() is O(1); pop(0) is O(n).
        drain = {"coll_off": 0, "coll_tail": b"", "sig_buf": b"",
                 "sig_pos": 0, "sig_eof": False, "pending": _deque(),
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
            #
            # W-STREAMDRAIN: helpers["scan_kind"] is the C1 signal on
            # this path (single scanner, recorded when reaped). Without
            # it the drop can fire while the scanner still has a worker
            # left to fork, giving the drain a false EOF and losing
            # everything that worker emits. EOF_PROTOCOL.md §1: C1
            # before C2.
            if fstate["workers"] and _spawn_quiescent(
                    state, helpers["scan_kind"] is not None):
                spare_signal_w = _close_spare_fd(state, spare_signal_w)
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
            _parse_drain_quantum(drain, coll_fd, use_orderer,
                                 out_fds, per_worker, _sig)
            if drain["pending"]:
                return drain["pending"].popleft()
            if (fstate["pump_done"]
                    and not any(s.alive
                                for s in state.workers.values())
                    and drain["sig_eof"] and not drain["sig_buf"]):
                if drain["reassembly"] is not None:
                    for _, ordered in drain["reassembly"].final_drain():
                        drain["pending"].append(ordered)
                    _raise_on_disposition_conflicts(
                        drain["reassembly"],
                        "stream() [records already yielded before this "
                        "point are NOT withdrawn]")
                    if drain["pending"]:
                        return drain["pending"].popleft()
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
                                return drain["pending"].popleft()
                else:
                    for _wid in range(len(per_worker)):
                        if _wid >= len(out_fds):
                            continue
                        for _bidx, _disp, _blob in \
                                _drain_worker_memfd_terminal(
                                    out_fds[_wid], per_worker[_wid]):
                            if drain["reassembly"] is None:
                                if _disp == _DISP_DATA:
                                    drain["pending"].append(_blob)
                            else:
                                drain["reassembly"].add_disposition(
                                    _bidx, _disp, _blob)
                                for _, ordered in drain[
                                        "reassembly"].drain():
                                    drain["pending"].append(ordered)
                    if drain["pending"]:
                        return drain["pending"].popleft()
                raise StopIteration
            return None

        try:
            yield from reactor_loop(state, drain_gen=_pump_drain)
        except BaseException as _exc:
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
            if isinstance(_exc, KeyboardInterrupt) and not isinstance(
                    _exc, ForkrunInterrupted):
                # W-REL5-B2: stream taxonomy matches the blocking
                # executors (abort already issued by the choreography
                # above) — never bare KeyboardInterrupt.
                raise ForkrunInterrupted(_INTERRUPTED_MSG) from _exc
            raise
        finally:
            pass

        _reactor_failure_check(state, workers, on_error)

        if use_drain and cdrain["pid"] is not None:
            # Results EOF ⇒ the drain exited — join it for its rc
            # (worker error above already raised; teardown covers).
            # W-REL5-B4: bounded.
            if cdrain["alive"]:
                _dst = _join_helper_bounded(cdrain["pid"], "drain")
                if _dst is not None:
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
                # W-REL5-B4: bounded (None ⇒ reaped elsewhere,
                # same leniency as the old ChildProcessError
                # branch).
                _ost = _join_helper_bounded(
                    orderer_pid, "orderer", ORDERER_REAP_TIMEOUT)
                if _ost is None:
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
            # W-REL5-B4: bounded (None keeps the leniency below).
            scan_st = _join_helper_bounded(scan_pid, "scanner")
            if scan_st is not None and not (
                    os.WIFEXITED(scan_st) and
                    os.WEXITSTATUS(scan_st) == 0):
                raise RuntimeError(
                    "forkrun: ingest scanner failed (status %r)"
                    % (scan_st,))
        if fallow_pid is not None and helpers["fallow_rc"] is None:
            # W-REL5-B4: bounded (WARN-lenient below covers None).
            fallow_st = _join_helper_bounded(fallow_pid, "fallow")
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

        _reactor_poison_summary(lib, state, strict_poison)
    finally:
        # C0.7: leave the nesting depth on every exit path.
        _C07_RUN_DEPTH[0] -= 1
        spare_signal_w = _close_spare_fd(state, spare_signal_w)
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

def sweep(payload: Any, source: Any = None, *,
          args: Optional[List[List[Any]]] = None,
          args_from: Optional[List[Any]] = None, link: bool = False,
          workers: Optional[int] = None, on_error: OnError = "retry",
          **kwargs: Any) -> List[bytes]:
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
    # W-REL5-C3: resume=/checkpoint_file= replay one stateful resume
    # over N combinations (sweep forces order="index"): combination 1
    # consumes the committed prefix, 2..N silently skip it. Reject
    # outright — resume each combination's map() call explicitly
    # instead (one checkpoint per combination).
    if kwargs.get("resume") is not None or \
            kwargs.get("checkpoint_file") is not None:
        raise ValueError(
            "sweep() with resume=/checkpoint_file= is rejected: a "
            "single stateful resume replayed over N combinations "
            "silently skips the committed prefix in combinations "
            "2..N (combination 1 consumes it). Resume each "
            "combination's map() call explicitly instead.")
    _reject_unknown_kwargs("sweep()", kwargs)
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

# W-REL6-3.5: last-throttle timestamp for _pump_debug_tick (was a
# function attribute, which mypy cannot model -- a module global
# carries the identical single-writer semantics).
_pump_debug_last = 0.0


def _pump_debug_tick():
    """Env-gated pump diagnostic throttle (W-PY21-A debugging).

    Returns True ~once/sec when FORKRUN_DEBUG_PUMP is set, else
    False.

    W-PYENVGATE: this used to read the environment on every call, on
    the assumption that "the callers already do costlier work per
    round". At 79k batches that is one pump round per batch, and
    os.environ.get costs ~1.6us (dict lookup + encode + abc dispatch)
    -- 79500 of them were 0.13s, about 11% of the run, to test a flag
    nobody had set. Throttle on the monotonic clock FIRST and consult
    the environment at most once a second. A flag set mid-run is now
    noticed within a second rather than on the next round, which is the
    right trade for a debug gate.
    """
    import time as _t
    now = _t.monotonic()
    global _pump_debug_last
    if now - _pump_debug_last < 1.0:
        return False
    _pump_debug_last = now
    return bool(os.environ.get("FORKRUN_DEBUG_PUMP"))


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
    _flush_stdio()

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

    # W-PYSPAWNWIRE: arm the scanner spawn pipe.
    #
    # This is the structural difference from bash. bash's scanner asks
    # the orchestrator for more workers as backlog appears
    # (forkrun_ring.c:3925-3942: request until live == min(backlog,
    # W_max)), so workers arrive when there is work for them. The engine
    # here has supported that all along -- ring_numa_scanner_main takes
    # fd_spawn and passes it to core_scanner_loop, and the shim exposes
    # it -- but this call site passed -1, so the request path was
    # disconnected and the gate had to fork the entire -j complement on
    # first publish. That is what makes python collapse at high worker
    # counts where bash does not: every worker is born at once against a
    # barely-filled ring, spins (forkrun_ring.c:6121 cpu_relax x100),
    # and steals the cores the ingest threads need.
    #
    # The parent keeps spawn_w open as a spare so the read end never
    # EOFs even if every scanner dies -- otherwise the reactor would
    # select on a permanently-readable fd.
    spawn_r, spawn_w = os.pipe()

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
                scrub_fds(engine_fds | {memfd, death_w, spawn_w})
                rc = lib.fr_py_numa_scanner(memfd, node, spawn_w,
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
            "spawn_r": spawn_r, "spawn_w": spawn_w,
            "indexer_pids": indexer_pids,
            "indexer_deaths": indexer_deaths,
            "scanner_pids": scanner_pids,
            "scanner_deaths": scanner_deaths,
            "ingest_pid": ingest_pid,
            "ingest_death": ingest_death_r}


def _numa_drain_audit(lib, num_nodes, forked, wid_node,
                      workers, label="map/run"):
    """F-NUMA1: per-node drain verification + telemetry (fail-loud guard).

    Called after reactor supervision returns and BEFORE the parent
    parses output: reads the read-only `fr_py_diag_node` snapshot per
    node (write_idx, read_idx, scanner_finished, chunk_head,
    chunk_tail) and verifies every node drained (every published
    slot claimed: `read_idx >= write_idx`). `forked` is the set of nodes that ever
    got workers; `wid_node` maps wid → node (stable for the run).

    Telemetry: one stderr block when FORKRUN_DIAG_NUMA1=1 (files, per
    context hygiene — never return payload data, only indices).

    Guard (REQUIRED, W-NUMA1 §12 — silent partial completion must
    become impossible-or-loud): any node with `read < write` (more
    published than claimed) AND a non-empty unclaimed tail is a
    violation. Disposition depends on worker coverage: when the
    pool covers every node (workers >= num_nodes — the only
    configuration that can drain fully), it raises RuntimeError
    naming the node, ALWAYS (a fork-gate miss, premature EOF, or
    publication skip with full coverage is a system fault). When
    the pool under-covers (workers < num_nodes — the documented
    RESILIENCE §7.3.1 topology constraint: an unworked node's
    born-local ring is never claimed), it emits one stderr
    warning with the same detail and returns the partial output —
    benchmark sweeps deliberately probe this shape (INCOMPLETE
    rows), so it must stay observable, not fatal. Rationale: a
    healthy covered run cannot violate it — workers exit only at
    EOF (C1+C2+C3 ⇒ every published slot ticketed). The reverse
    (`read > write`, claim overshoot by exactly the stragglers'
    FAA tickets past the final publish) is benign by construction:
    overshoot tickets wait, observe EOF, and exit without ack,
    output, or order packets — every published slot is still
    claimed exactly once. A node whose unclaimed tail is ALL EMPTY
    (the EOF sentinel / zero-length tail: never counted by the fork
    gate, never claimed, contributes no output) is vacuous, not a
    violation — small-scale sentinel-only nodes fork no workers
    with complete output. Missing symbol (pre-diagnostic .so)
    disarms both paths silently.
    """
    import ctypes as _ctypes

    diag = getattr(lib, "fr_py_diag_node", None)
    rows = []
    if diag is not None:
        try:
            diag.argtypes = [_ctypes.c_int,
                             _ctypes.POINTER(_ctypes.c_uint64)]
            diag.restype = _ctypes.c_int
        except Exception:
            diag = None
    for node in range(num_nodes):
        if diag is not None:
            arr = (_ctypes.c_uint64 * 6)()
            try:
                rc = diag(node, arr)
            except Exception:
                rc = -1
            if int(rc) == 0:
                rows.append((node, int(arr[0]), int(arr[1]),
                             int(arr[2]), int(arr[3]), int(arr[4]),
                             int(arr[5])))
                continue
        rows.append((node, -1, -1, -1, -1, -1, -1))
    if os.environ.get("FORKRUN_DIAG_NUMA1") == "1":
        try:
            per_node_wids = {}
            for wid, nd in enumerate(wid_node or []):
                per_node_wids.setdefault(nd, []).append(wid)
            parts = ["forkrun [DIAG-NUMA1] %s completion:" % label,
                     "  nodes=%d workers=%d forked=%s" % (
                         num_nodes, workers, sorted(forked or ()))]
            for (node, w, r, fin, ch, ct, te) in rows:
                parts.append(
                    "  node=%d write=%d read=%d finished=%d "
                    "chunks(head=%d tail=%d) tail_empty=%d forked=%s "
                    "wids=%s" % (
                        node, w, r, fin, ch, ct, te,
                        "yes" if node in (forked or ()) else "NO",
                        per_node_wids.get(node, [])))
            os.write(2, ("\n".join(parts) + "\n").encode())
        except OSError:
            pass
    # C0.7: the published-slot total, read HERE because fr_py_diag_node
    # only answers while the ring state is live -- a probe issued after
    # map() returns reads zeros. Returning it lets the caller compare it
    # against the records it subsequently collects, which it cannot do
    # itself because collection happens after this function returns.
    expected_total = None
    if any(w >= 0 for (_n, w, _r, _f, _c, _t, _te) in rows):
        expected_total = sum(w for (_n, w, _r, _f, _c, _t, _te) in rows
                             if w >= 0)
    _PUBLISHED_SLOTS["total"] = expected_total
    _PUBLISHED_SLOTS["nodes"] = num_nodes

    bad = [(node, w, r) for (node, w, r, _f, _c, _t, te) in rows
           if w >= 0 and r >= 0 and w > r and te != 1]
    if not bad:
        return expected_total
    detail = ", ".join(
        "node %d (write_idx=%d != read_idx=%d)" % (n, w, r)
        for (n, w, r) in bad)
    try:
        covered = len(set(wid_node or [])) >= num_nodes
    except TypeError:
        covered = False
    if not covered:
        # Documented topology constraint (RESILIENCE §7.3.1), not a
        # system fault: the pool cannot drain nodes it never worked.
        # Warn loudly (never silent) and return the partial output —
        # benchmark sweeps probe this shape on purpose.
        try:
            os.write(2, ("forkrun [WARN]: NUMA partial completion "
                         "(%s): %d/%d node(s) unclaimed (%s) — pool "
                         "covers %d/%d node(s); size workers >= nodes "
                         "or pass nodes=1 for single-node work\n"
                         % (label, len(bad), num_nodes, detail,
                            len(set(wid_node or [])), num_nodes)
                         ).encode())
        except OSError:
            pass
        return expected_total
    raise RuntimeError(
        "forkrun: NUMA drain incomplete (%s): %d/%d node(s) "
        "hold unclaimed published batches (%s) — refusing silent "
        "partial completion" % (label, len(bad), num_nodes,
                                detail))


def _c07_envelope(lib, mode, *, use_complete, has_emit,
                  has_ack_direct):
    """C0.7: decide whether this execution is INSIDE the counted envelope.

    Fail-closed by construction. Every branch here corresponds to a path
    that writes DATA frames without incrementing the pending counter, or
    commits without running the shim-side flush. A comment would not
    help: the risk is a supported fallback silently bypassing the
    expected side and the certificate still reporting clean.

    Returns (covered: bool, reason: str).

      * mode == "splice" -- fr_py_worker_splice_loop frames DATA inline
        and streams it with sendfile, bypassing fr_py_emit,
        fr_py_emit_record_buf AND fr_py_emit_record. Only its
        sendfile-UNAVAILABLE fallback is counted, so the fast path and
        the fallback would disagree about accounting.
      * no C emitter -- the Python `_write_all` fallback in _worker.py
        writes the frame from Python with no C involvement at all, so a
        C counter cannot see it (reached under FORKRUN_NO_V1=1).
      * no fr_py_ack_direct -- _ack() falls back to fr_py_ack, which
        routes to ring_ack_main and skips the shim-side commit flush.
        The absence of the symbol DETERMINES that the fallback happens,
        so this is decidable up front rather than needing to observe a
        child process.
    """
    if mode == "splice":
        return False, ("splice mode frames DATA inline via sendfile and "
                       "bypasses all counted emitters")
    if not (use_complete or has_emit):
        return False, ("python _write_all fallback emits frames outside "
                       "the C counter (no fr_py_complete/fr_py_emit)")
    if not has_ack_direct:
        return False, ("no fr_py_ack_direct: _ack() falls back to "
                       "fr_py_ack/ring_ack_main, skipping the commit flush")
    return True, ""


def _c07_enabled():
    """Read the SAME switch the shim reads.

    Both halves must agree or the feature becomes a false-pass factory:
    accounting off with the certificate still live compares a counter
    that reads 0 against real collected frames, so every correct run
    fails; accounting on with the certificate silently skipped measures
    nothing while reporting success.

    The shim caches this per process on first use. So must this, or a
    run would compare against a counter whose accounting state was
    decided at a different moment.
    """
    v = os.environ.get("FORKRUN_C07_COUNT")
    return not (v and v[0] and v == "0")


def _c07_no_verdict(reason):
    """Emit NO certificate verdict, and say why.

    The distinction from _c07_evaluate matters: that one refuses an
    uncovered ENVELOPE, this one refuses an untrustworthy NUMBER. Both
    produce no pass. Neither is an error -- ordered delivery still
    happened; only the proof is unavailable.
    """
    try:
        os.write(2, ("forkrun [WARN]: C0.7 completeness certificate not "
                     "evaluated: %s\n" % (reason,)).encode())
    except OSError:
        pass


def _c07_evaluate(expected, observed, lib, mode):
    """Gate the comparison on the envelope, then run the certificate.

    Fail-closed: an uncovered execution emits NO verdict. It never emits
    a passing one. The warning names the specific path, because a bare
    "certificate unavailable" is not something an operator can act on.

    The capabilities come from v1_available(), NOT from symbol
    existence. Those differ under FORKRUN_NO_V1: the symbol is still
    present but masked, so a worker will take the Python _write_all
    fallback and emit frames the C counter never sees. Asking "does
    lib.fr_py_emit exist" would have reported the envelope COVERED on
    exactly the configuration that breaks it.
    """
    from ._bindings import v1_available as _v1a
    _v1 = _v1a()
    covered, reason = _c07_envelope(
        lib, mode,
        use_complete=bool(_v1.get("complete", False)),
        has_emit=bool(_v1.get("emit", False)),
        has_ack_direct=bool(_v1.get("ack_direct", False)))
    if not covered:
        try:
            os.write(2, ("forkrun [WARN]: C0.7 completeness certificate "
                         "not evaluated: execution envelope not covered "
                         "(mode=%s): %s\n" % (mode, reason)).encode())
        except OSError:
            pass
        return
    _ordered_completeness_certificate(expected, observed, label="map/run")


def _c07_read_committed(lib, num_nodes):
    """Sum the committed DATA frames across nodes, or None.

    None means "not readable" -- an older substrate without the symbol.
    That must NEVER be read as zero: a zero would look like "the engine
    committed nothing", which is the one value that would make the
    certificate fire on every run. Callers treat None as "no verdict".

    The load itself is RELAXED and that is correct here, because the
    caller has already joined the workers: quiescence is a lifecycle
    fact, not something a stronger memory order can express. Reading
    while a worker were mid-batch would undercount, not double-count.
    """
    import ctypes as _ct
    fn = getattr(lib, "fr_py_committed_data_frames", None)
    if fn is None:
        return None
    total = 0
    nodes = max(int(num_nodes or 1), 1)
    for node in range(nodes):
        out = _ct.c_uint64(0)
        try:
            rc = fn(node, _ct.byref(out))
        except Exception:
            return None
        if rc != 0:
            # A node the engine does not have is not a shortfall; it
            # means the snapshot is unavailable, so decline the verdict.
            return None
        total += int(out.value)
    return total


def _ordered_completeness_certificate(expected, actual, *, label,
                                      covered=True, unordered=False,
                                      emit_failed=False):
    """C0.7: prove every COMMITTED DATA frame reached the ordered output.

    The claim/drain audit can only prove "every published slot was
    CLAIMED". It cannot prove every claimed record reached the orderer's
    output: a record can be claimed, framed, written into the order pipe
    and lost there. Collection deliberately does not sort when the C
    orderer ran, so there is no second line of defence — `map(...,
    nodes="@2", order="index")` had no completeness gate at all.

        expected = committed DATA frames, counted in the shim at the
                  COMMIT point (not at write time -- an uncommitted
                  frame is rolled back and retried), summed over
                  nodes, MINUS this run's baseline
        observed = DATA frames the parent actually collected
        certificate = (observed == expected)

    THE OLD FORMULATION WAS FALSE, and it is worth recording why: it
    compared `sum(write_idx)` against collected records. write_idx
    counts SLOTS, not DATA frames, and the EOF sentinel occupies a slot
    while yielding no record -- so every multi-node NUMA run was short
    by exactly one. Asserting that equality would have made a
    completeness certificate fire on correct runs, which is worse than
    having none. The committed-DATA invariant excludes the sentinel by
    construction rather than by calibration.

    Counting rather than inspecting the orderer's heap catches the case
    a heap inspection CANNOT: a missing FINAL packet leaves an empty
    heap, so "drained cleanly and heap empty" is not a certificate.

    SCOPE, stated precisely because the code is more limited than the
    word "certificate" suggests:

      * Only the C-orderer path (order="index" with use_orderer) is
        certified at all. Splice, and any configuration where the C
        orderer is unavailable (FORKRUN_NO_V1 masks it), take a
        different collection path and produce NO verdict at all -- not a
        pass, and not a warning from here.
      * Within that path, the envelope (_c07_evaluate) refuses when the
        worker used an emitter or ack route the counter cannot see.

    unordered mode has no per-slot correspondence, and an emit failure
    legitimately produces fewer records but already pulls the fire
    alarm, so it is not double-reported here.
    """
    if expected is None:
        return                      # diag unavailable: disarmed, not failing
    if unordered or emit_failed:
        return
    if int(actual) == int(expected):
        return
    where = "ordered output lost published records"
    detail = ("collected %d record(s) but the engine published %d "
              "(short by %d)" % (actual, expected, expected - actual))
    if not covered:
        # Same disposition as the drain audit: an under-covered pool
        # cannot claim nodes it never worked, and benchmark sweeps probe
        # this shape deliberately. Observable, not fatal.
        try:
            os.write(2, ("forkrun [WARN]: %s (%s): %s — pool under-covers "
                         "the topology; partial output is expected here\n"
                         % (where, label, detail)).encode())
        except OSError:
            pass
        return
    raise RuntimeError(
        "forkrun: %s (%s): %s — refusing silent partial completion"
        % (where, label, detail))


def _execute_numa_locked(payload, source, *, sink, lines, bytes_,
                         workers, on_error, views=True, strict_poison=False, collect, order,
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
    # W-REL6-5: lattice position (executor #9: NUMA, reactor-implied,
    # blocking) + this call's behavior flags.
    _spec = ExecutorSpec(topology="numa", ingest="materialized",
                         supervision="reactor", shape="blocking",
                         collect=collect, splice=splice, c_drain=c_drain,
                         order=order)
    _zc = bool(views)
    lib, engine_fds = _init_engine_and_fds(
        lines=lines, bytes_=bytes_, spec=_spec,
        num_nodes=num_nodes, numa_map=numa_map)

    # C0.7 expected-side baseline -- see the UMA reactor executor for
    # why this is a local captured before any fork rather than a global.
    # C0.7: keep the None sentinel -- see the UMA reactor executor.
    _c07_base = _c07_read_committed(lib, num_nodes) if _c07_enabled() else None
    _c07_nested = _C07_RUN_DEPTH[0] > 0
    _C07_RUN_DEPTH[0] += 1
    _C07_RUNS_STARTED[0] += 1
    # Recorded AFTER our own increment: from here on, any further change
    # means ANOTHER run started inside our measurement window. Recording
    # it before would make every run trip its own check.
    _c07_runs_at_start = _C07_RUNS_STARTED[0]

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
            # W-REL5-E7: no tempfile fallback (floor 3.10).
            coll_fd = os.memfd_create("forkrun_ordered")
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
        # W-PYSPAWNWIRE: hand the reactor the scanner's spawn read end and
        # keep the write end parked as a spare, so the reactor's watch set
        # includes it and the pipe never EOFs. Teardown already closes
        # both (it walks state.spawn_r and ctx["spawn_w"]).
        state_spawn_r = pipe.get("spawn_r", -1)
        state_spawn_w = pipe.get("spawn_w", -1)
        if must_close:
            try:
                os.close(src_fd)
            except OSError:
                pass
            must_close = False

        # wid → node blocks (stable for the run: respawns reuse the
        # wid, hence the same memfd and the same claim ring).
        # (W-REL5-E7: the duplicate function-level import that was
        # here is gone — the top-of-function import above binds it.)
        wid_node = wid_to_node(workers, num_nodes)

        state = ReactorState(workers, num_nodes=num_nodes,
                             respawn_cap=REACTOR_RESPAWN_CAP,
                             spawn_ceiling=workers,
                             wid_node=wid_node)
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
        # W-PYSPAWNWIRE: park BOTH spawn ends on state from the start so
        # teardown owns them on every path, including early errors. The
        # gate does not SERVICE this pipe -- it passes spawn=False to
        # reactor_poll_once -- so the scanner's ramp cannot fork workers
        # the gate's ``forked`` set never records.
        state.spawn_r = state_spawn_r
        state.ctx["spawn_w"] = state_spawn_w

        def _ready_all():
            try:
                return [lib.fr_py_data_ready_node(n)
                        for n in range(num_nodes)]
            except Exception:
                return [0] * num_nodes

        def _watch_pipeline():
            _watch_numa_pipeline(lib, pipe, helpers, num_nodes)
        def _fork_node(node):
            _fork_workers_for_node(state, wid_node, node, forked)

        # Workers a node's workers-block needs, and the published-batch
        # floor its fork is gated on (see the loop comment below).
        _node_need = {}
        for _wid, _nd in enumerate(wid_node):
            _node_need[_nd] = _node_need.get(_nd, 0) + 1
        # A substrate predating fr_py_backlog_node has no level gauge, so
        # the floor degrades to 1 — i.e. today's first-publish gate — and
        # the rest of this change (the poll ramp) still applies. Keeps an
        # un-rebuilt .so working rather than hard-failing the NUMA path.
        _have_backlog = hasattr(lib, "fr_py_backlog_node")
        _node_floor = {
            n: (max(_GATE_MIN_BATCHES, c * _GATE_BATCHES_PER_WORKER)
                if _have_backlog else 1)
            for n, c in _node_need.items()
        }

        def _node_ready(node):
            """Level (not edge) published backlog for one node.

            fr_py_data_ready_node is consume-once — it returns only what
            published SINCE the previous call — so it cannot express a
            floor: a poll whose value is below the floor has already
            burned that evidence and the floor becomes unreachable. Use
            the non-destructive backlog instead; _ready_all() below is
            retained for the stall/diagnostic path that wants the edge.
            """
            if not _have_backlog:
                try:
                    return lib.fr_py_data_ready_node(node)
                except Exception:
                    return 0
            try:
                return lib.fr_py_backlog_node(node)
            except Exception:
                return 0

# Fork-timing loop: per-node publish gating + global stall
        # fallback. Ends when every node forked, or when the whole
        # pipeline is done (ingest + all indexers + all scanners
        # clean — then fstat below separates empty input from a publish
        # anomaly). Fork-on-publish precedes the done-check
        # each round so a publish coinciding with pipeline EOF still
        # forks before the loop can exit.
        #
        # W-PYFORKGATE: readiness is polled on a short ramp instead of a
        # flat 50ms sleep. The sleep used to be unconditional, so every
        # multi-node run paid a full 50ms quantum even when the first
        # publish landed a millisecond in — measured at 24-37% of total
        # wall on a 5M-record input (50.00ms of a 137ms run). The
        # publish latency is the real bound, so ramp toward it.
        #
        # The two polls are deliberately decoupled. _ready_all() is
        # cheap (one ctypes call per node), but _watch_pipeline() +
        # reactor_poll_once() are not: the latter runs an O(N) waitpid
        # sweep over every live worker slot, so running it on every fast
        # readiness poll made high worker counts measurably SLOWER
        # (+8.8% at 48w, +24% at 96w in paired A/B) while the same ramp
        # won -20.8% at 8w. Supervision therefore keeps the original
        # 50ms cadence (_GATE_SUPERVISE_EVERY fast rounds between
        # sweeps); only readiness accelerates. On a long stall the ramp
        # saturates at _GATE_POLL_MAX_S and the supervise tick restores
        # the exact pre-change 50ms cadence, so the stall fallback
        # (STALL_FORK_AFTER) and its helper-death detection are
        # unchanged.
        stalled = False
        _gate_wait = _GATE_POLL_MIN_S
        _gate_tick = 0
        stalled = False
        _gate_wait = _GATE_POLL_MIN_S
        _gate_tick = 0
        while len(forked) < num_nodes:
            if _gate_tick == 0:
                _watch_pipeline()
                # spawn=False: the gate, not the scanner, owns worker
                # creation here (W-PYSPAWNWIRE). Serving spawn requests
                # from inside the gate forks workers its ``forked`` set
                # never records.
                reactor_poll_once(state, spawn=False)
            _gate_tick += 1
            for node in range(num_nodes):
                if node in forked:
                    continue
                # Fork on BACKLOG, not on first publish. bash's scanner
                # only requests workers once scan_idx - read_idx exceeds
                # the live count (forkrun_ring.c:3925-3942); this path
                # used to fork the entire -j complement on the first
                # publish of any size, which starts every worker against
                # a ring that has barely been filled. Each idle worker
                # then spins (forkrun_ring.c:6121, cpu_relax x100) and
                # steals the cores the ingest threads need to fill that
                # ring — the pipeline and the workers starve each other.
                # Measured publish rate here is ~13 batches/ms, so at
                # 96 workers a first-publish gate saw 46 batches of
                # backlog (0.5/worker) and cost +34% wall versus
                # waiting for ~700 (7/worker). Gating on a per-worker
                # backlog floor makes the fork point independent of how
                # many workers were asked for.
                if _node_ready(node) >= _node_floor[node]:
                    _fork_node(node)
            if len(forked) >= num_nodes:
                break
            if _pipeline_quiescent(helpers, num_nodes):
                # The pipeline finished. A node still holding unclaimed
                # batches MUST get its workers even though its backlog
                # never reached _GATE_BATCHES_PER_WORKER — a small input
                # can publish fewer batches in total than the floor asks
                # for. The floor is a startup throttle, not a permission
                # to drop work: skipping these nodes left published
                # batches unclaimed and tripped the drain audit
                # ("NUMA drain incomplete ... hold unclaimed published
                # batches"). Fork-on-any-backlog here, matching the
                # pre-change first-publish gate.
                for node in range(num_nodes):
                    if node not in forked and _node_ready(node) > 0:
                        _fork_node(node)
                break
            if not stalled and (
                    _time.monotonic() - t_start) >= STALL_FORK_AFTER:
                stalled = True
                for node in range(num_nodes):
                    if node not in forked:
                        _fork_node(node)
            if _gate_tick >= _GATE_SUPERVISE_EVERY:
                _time.sleep(_GATE_WAIT_FULL_S)
                _gate_tick = 0
                _gate_wait = _GATE_POLL_MIN_S
            else:
                _time.sleep(_gate_wait)
                _gate_wait = min(_gate_wait * 2, _GATE_POLL_MAX_S)

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
            except KeyboardInterrupt as _ki:
                raise ForkrunInterrupted(_INTERRUPTED_MSG) from _ki

        _reactor_failure_check(state, workers, on_error)

        _expected_published = _numa_drain_audit(
            lib, num_nodes, forked, wid_node, workers, label="map/run")

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
            # teardown covers that path). W-REL5-B4: bounded.
            if signal_w is not None:
                try:
                    os.close(signal_w)
                except OSError:
                    pass
                signal_w = None
                state.ctx["signal_w"] = -1
            _dst = _join_helper_bounded(drain_pid, "drain")
            if _dst is None:
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
                # W-REL5-B4: bounded.
                _ost = _join_helper_bounded(
                    orderer_pid, "orderer", ORDERER_REAP_TIMEOUT)
                if _ost is None:
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
        # All bounded (W-REL5-B4); None keeps the leniency below.
        if helpers["ingest_kind"] == "error":
            raise RuntimeError(
                "forkrun: NUMA ingest failed (status %r)"
                % (helpers["ingest_code"],))
        if helpers["ingest_kind"] is None:
            _st = _join_helper_bounded(pipe["ingest_pid"],
                                       "numa-ingest")
            if _st is not None and not (
                    os.WIFEXITED(_st) and os.WEXITSTATUS(_st) == 0):
                raise RuntimeError(
                    "forkrun: NUMA ingest failed (status %r)" % (_st,))
        for key, pids in (("index", pipe["indexer_pids"]),
                          ("scan", pipe["scanner_pids"])):
            for node in range(num_nodes):
                if node in helpers[key]:
                    # D-PORT2: deaths excused by the abort-aware
                    # watch (abort already in flight) stay excused
                    # here — re-raising them would clobber the
                    # abort's own outcome with a spurious fatal.
                    if (key, node) in helpers.get("excused", ()):
                        continue
                    kind, code = helpers[key][node]
                    if kind == "error":
                        raise RuntimeError(
                            "forkrun: NUMA %s %d failed (status %r)"
                            % (key, node, code))
                    continue
                _st = _join_helper_bounded(
                    pids[node], "numa-%s-%d" % (key, node))
                if _st is not None and not (
                        os.WIFEXITED(_st) and os.WEXITSTATUS(_st) == 0):
                    # Fresh death at join time: same D6 rule — an
                    # abort in flight makes it expected (file it as
                    # excused); otherwise violent death (fatal).
                    if _helper_death_disposition(
                            "error", False,
                            _abort_reason_now(lib)) == "excuse":
                        helpers[key][node] = ("error", _st)
                        helpers.setdefault(
                            "excused", set()).add((key, node))
                        continue
                    raise RuntimeError(
                        "forkrun: NUMA %s %d failed (status %r)"
                        % (key, node, _st))
        if helpers["fallow_rc"] is None:
            _fst = _join_helper_bounded(pipe["fallow_pid"],
                                        "numa-fallow")
            if _fst is not None and not (
                    os.WIFEXITED(_fst) and os.WEXITSTATUS(_fst) == 0):
                try:
                    os.write(2, b"forkrun [WARN]: NUMA reaper exited "
                             b"abnormally; ingress may not be fully "
                             b"reclaimed.\n")
                except OSError:
                    pass

        _reactor_poison_summary(lib, state, strict_poison)

        if not collect:
            return None
        if use_orderer:
            # C0.7 HISTORY, kept because each failure invalidated a
            # different scoping strategy and none of the three is
            # obvious in hindsight. The sweep shows committed ==
            # collected on all 24 line configurations across UMA, @2 and
            # @4.
            #
            # A first wiring attempt failed in three distinct ways, each
            # of which invalidated a different attempt to scope it:
            #
            #  - _FRAME_STATS is a module global, so it accumulated across
            #    map() calls in one process ("collected 282, published
            #    26"). Fixed by resetting per collection.
            #  - a RESUME merges sidecar records committed by EARLIER
            #    runs, which were counted then, so including them gave
            #    "collected 40, published 33" on a correct resume. Fixed
            #    by snapshotting the observed count before the merge.
            #  - a NESTED map() inside a stream() SHARES the engine, so
            #    the committed counter is cumulative across both runs.
            #    The inner run collected 24 while the counter read 56.
            #    No amount of resetting the observed side fixes this: the
            #    EXPECTED side needed a baseline captured before this
            #    run's workers commit, compared as a delta. That is what
            #    _c07_base does, below.
            #
            # That baseline is a real design decision (where to capture
            # it, how it interacts with resume and with nested runs), so
            # it is not being guessed at here. The count, the accessor,
            # the envelope and both proof tests stand.
            #
            # SOLVED by scoping the EXPECTED side: _c07_base was captured
            # at engine init, before any fork, so the comparison is this
            # run's commits minus this run's baseline. See the UMA reactor
            # executor for why the baseline is a per-run local.
            _ordered = [blob for _, blob in _iter_records(lib, coll_fd,
                                                          views=_zc)]
            _c07_now = (_c07_read_committed(lib, num_nodes)
                        if _c07_enabled() else None)
            if _c07_nested:
                _c07_no_verdict(
                    "nested inside another forkrun run, whose live workers "
                    "commit to the same engine counter; the delta cannot be "
                    "attributed to this run alone")
            elif _c07_now is not None and _c07_base is not None:
                _c07_total = int(_c07_now) - int(_c07_base)
                _COMMITTED_FRAMES["total"] = _c07_total
                _COMMITTED_FRAMES["nodes"] = int(num_nodes or 1)
                _c07_evaluate(_c07_total, len(_ordered), lib, mode)
            return _ordered
        # Collection is _executor_core.collect_records: drain-vs-direct
        # and order-index-vs-none are mechanics, not lifecycle shape.
        return collect_records(use_drain=use_drain,
                               results_fd=results_fd, out_fds=out_fds,
                               order=order, lib=lib, views=_zc)
    except KeyboardInterrupt as _ki:
        try:
            lib.fr_py_abort()
        except Exception:
            pass
        raise ForkrunInterrupted(_INTERRUPTED_MSG) from _ki
    finally:
        # C0.7: leave the nesting depth on EVERY exit path, including
        # aborts and exceptions. A leaked depth would make every later
        # top-level run believe it is nested and silently stop
        # certifying -- a failure that looks like a pass.
        _C07_RUN_DEPTH[0] -= 1
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
                       on_error, strict_poison, mode, order, orchestrator, numa_map,
                       num_nodes, node_cpus, splice=False, c_drain=True):
    # stream() over the NUMA pipeline: live drain while the ingest
    # feeds per-node rings. Always reactor-supervised (the NUMA path
    # is new in W-PY21 — no legacy non-reactor NUMA exists to preserve).
    _ = orchestrator  # accepted for call uniformity; NUMA implies reactor
    yield from _execute_numa_stream(
        payload, source, lines=lines, bytes_=bytes_, workers=workers,
        on_error=on_error, strict_poison=strict_poison, mode=mode, order=order,
        numa_map=numa_map, num_nodes=num_nodes, node_cpus=node_cpus,
        splice=splice, c_drain=c_drain)


def _execute_numa_stream(payload, source, *, lines, bytes_, workers,
                         on_error, strict_poison=False, mode="python", order="none",
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
    # W-REL6-5: lattice position (executor #10: NUMA, reactor-implied,
    # generator) + this call's behavior flags.
    _spec = ExecutorSpec(topology="numa", ingest="materialized",
                         supervision="reactor", shape="generator",
                         collect=True, splice=splice, c_drain=c_drain,
                         order=order)
    lib, engine_fds = _init_engine_and_fds(
        lines=lines, bytes_=bytes_, spec=_spec,
        num_nodes=num_nodes, numa_map=numa_map)

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
            # W-REL5-E7: no tempfile fallback (floor 3.10).
            coll_fd = os.memfd_create("forkrun_ordered")
            orderer_pid = spawn_orderer(order_r, coll_fd,
                                        unordered=False, numa=True,
                                        engine_fds=engine_fds,
                                        out_fds=out_fds)

        trap_r, trap_w = os.pipe()

        pipe = _numa_fork_pipeline(lib, memfd, src_fd, num_nodes,
                                   engine_fds)
        fallow_w = pipe["fallow_w"]
        # W-PYSPAWNWIRE: hand the reactor the scanner's spawn read end and
        # keep the write end parked as a spare, so the reactor's watch set
        # includes it and the pipe never EOFs. Teardown already closes
        # both (it walks state.spawn_r and ctx["spawn_w"]).
        state_spawn_r = pipe.get("spawn_r", -1)
        state_spawn_w = pipe.get("spawn_w", -1)
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
                             spawn_ceiling=workers,
                             wid_node=stream_wid_node)
        state.configure(payload_spec=payload, sink_spec=None,
                        memfd=memfd, file_size=-1,
                        out_fds=list(out_fds), signal_w=signal_w,
                        fallow_w=fallow_w,
                        order_w=order_w if use_orderer else -1,
                        trap_ack_w=trap_w, on_error=on_error,
                        engine_fds=engine_fds, splice=splice,
                        node_cpus=node_cpus)
        state.trap_ack_r = trap_r
        # W-PYSPAWNWIRE: park BOTH spawn ends on state from the start so
        # teardown owns them on every path, including early errors. The
        # gate does not SERVICE this pipe -- it passes spawn=False to
        # reactor_poll_once -- so the scanner's ramp cannot fork workers
        # the gate's ``forked`` set never records.
        state.spawn_r = state_spawn_r
        state.ctx["spawn_w"] = state_spawn_w
        spare_signal_w = os.dup(signal_w)

        def _drop_parent_signal():
            nonlocal signal_w
            signal_w = _retire_parent_signal(signal_w, state,
                                        spare_signal_w)

        def _fork_node(node):
            _fork_workers_for_node(state, stream_wid_node, node, forked)
            # Only the streaming path retires the parent signal here: it
            # has a drain blocked on EOF, so the parent's write end must
            # go once workers exist. The blocking NUMA path collects from
            # out_fds directly and needs no EOF.
            _drop_parent_signal()

        def _watch_pipeline():
            _watch_numa_pipeline(lib, pipe, helpers, num_nodes)
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
        # W-PYPENDING: deque -- popleft() is O(1); pop(0) is O(n).
        drain = {"coll_off": 0, "coll_tail": b"", "sig_buf": b"",
                 "sig_pos": 0, "sig_eof": False, "pending": _deque(),
                 "reassembly": None}
        if order == "index" and not use_orderer:
            drain["reassembly"] = ReassemblyBuffer()
        per_worker = [[0, b""] for _ in range(workers)]

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
                    for _bidx, _disp, _blob in _drain_worker_memfd_terminal(
                            out_fds[_wid], per_worker[_wid]):
                        if drain["reassembly"] is None:
                            if _disp == _DISP_DATA:
                                drain["pending"].append(_blob)
                        else:
                            drain["reassembly"].add_disposition(
                                _bidx, _disp, _blob)
                            for _, ordered in drain[
                                    "reassembly"].drain():
                                drain["pending"].append(ordered)
            if drain["reassembly"] is not None:
                for _, ordered in drain["reassembly"].final_drain():
                    drain["pending"].append(ordered)
                # Added (round-9 review): this route finalised without
                # consulting conflicts(), so a contradiction recorded on
                # the NUMA-stream path was silently ignored.
                _raise_on_disposition_conflicts(
                    drain["reassembly"],
                    "stream() [records already yielded before this point "
                    "are NOT withdrawn]")

        def _pump_drain():
            nonlocal spare_signal_w, signal_w
            # Spare-drop rule (W-PY19 erratum, see ingest path):
            # only once some node forked (forked set), never on
            # pre-first-fork rounds — closing early poisons ctx for
            # future forks (signal_w=-1 ⇒ no signals ⇒ starvation).
            #
            # W-STREAMDRAIN: `_suppliers_finished` is load-bearing, not
            # belt-and-braces. Workers fork incrementally as the scan
            # advances, so "no live worker" is briefly true while the
            # scanner still has another to fork. Dropping the spare
            # there gave the signal pipe a false EOF; the C drain child
            # exited on it and everything the later worker emitted was
            # lost without a warning. Gate on C1 (scanners finished)
            # before C2 (no live worker) per EOF_PROTOCOL §1.
            if forked and _spawn_quiescent(
                    state, _suppliers_finished(helpers, num_nodes)):
                spare_signal_w = _close_spare_fd(state, spare_signal_w)
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
                    and _pipeline_quiescent(helpers, num_nodes):
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
                    forked or _pipeline_quiescent(helpers, num_nodes)):
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
            _parse_drain_quantum(drain, coll_fd, use_orderer,
                                 out_fds, per_worker, _sig)
            if drain["pending"]:
                return drain["pending"].popleft()
            if (pump_state["done"]
                    and not any(s.alive
                                for s in state.workers.values())
                    and drain["sig_eof"] and not drain["sig_buf"]):
                _sweep_memfds()
                if drain["pending"]:
                    return drain["pending"].popleft()
                raise StopIteration
            return None

        try:
            yield from reactor_loop(state, drain_gen=_pump_drain)
        finally:
            pass

        _reactor_failure_check(state, workers, on_error)

        _numa_drain_audit(lib, num_nodes, forked, stream_wid_node,
                          workers, label="stream")

        if use_drain and cdrain_n["pid"] is not None:
            # Results EOF ⇒ the drain exited — join it for its rc
            # (worker error above already raised; teardown covers).
            # W-REL5-B4: bounded.
            if cdrain_n["alive"]:
                _dst = _join_helper_bounded(cdrain_n["pid"], "drain")
                if _dst is not None:
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
                # W-REL5-B4: bounded (None ⇒ reaped elsewhere,
                # same leniency as the old ChildProcessError
                # branch).
                _ost = _join_helper_bounded(
                    orderer_pid, "orderer", ORDERER_REAP_TIMEOUT)
                if _ost is None:
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
            # W-REL5-B4: bounded (None keeps the leniency below).
            _st = _join_helper_bounded(pipe["ingest_pid"],
                                       "numa-ingest")
            if _st is not None and not (
                    os.WIFEXITED(_st) and os.WEXITSTATUS(_st) == 0):
                raise RuntimeError(
                    "forkrun: NUMA ingest failed (status %r)" % (_st,))
        for key, pids in (("index", pipe["indexer_pids"]),
                          ("scan", pipe["scanner_pids"])):
            for node in range(num_nodes):
                if node in helpers[key]:
                    # D-PORT2: deaths excused by the abort-aware
                    # watch (abort already in flight) stay excused
                    # here — re-raising them would clobber the
                    # abort's own outcome with a spurious fatal.
                    if (key, node) in helpers.get("excused", ()):
                        continue
                    kind, code = helpers[key][node]
                    if kind == "error":
                        raise RuntimeError(
                            "forkrun: NUMA %s %d failed (status %r)"
                            % (key, node, code))
                    continue
                # W-REL5-B4: bounded (None keeps the leniency
                # below).
                _st = _join_helper_bounded(
                    pids[node], "numa-%s-%d" % (key, node))
                if _st is not None and not (
                        os.WIFEXITED(_st) and os.WEXITSTATUS(_st) == 0):
                    # Fresh death at join time: same D6 rule — an
                    # abort in flight makes it expected (file it as
                    # excused); otherwise violent death (fatal).
                    if _helper_death_disposition(
                            "error", False,
                            _abort_reason_now(lib)) == "excuse":
                        helpers[key][node] = ("error", _st)
                        helpers.setdefault(
                            "excused", set()).add((key, node))
                        continue
                    raise RuntimeError(
                        "forkrun: NUMA %s %d failed (status %r)"
                        % (key, node, _st))
        if helpers["fallow_rc"] is None:
            # W-REL5-B4: bounded (WARN-lenient below covers None).
            _fst = _join_helper_bounded(pipe["fallow_pid"],
                                        "numa-fallow")
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

        _reactor_poison_summary(lib, state, strict_poison)
    except KeyboardInterrupt as _ki:
        # W-REL5-B2: stream taxonomy matches the blocking
        # executors — abort, then ForkrunInterrupted (still a
        # KeyboardInterrupt), never bare KeyboardInterrupt. NUMA
        # twin of the four UMA stream executors (lockstep).
        try:
            lib.fr_py_abort()
        except Exception:
            pass
        raise ForkrunInterrupted(_INTERRUPTED_MSG) from _ki
    finally:
        spare_signal_w = _close_spare_fd(state, spare_signal_w)
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
