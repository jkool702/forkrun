#!/usr/bin/env python3
"""WO-CM1 -- observe the ACTUAL public dispatch route.

The capability matrix (tools/capability_matrix.py) is a predicate truth
table: it calls `_cleanroom_eligible()` and reports what it says. That
is necessary and not sufficient. A configuration is not cleanroom-served
merely because the predicate would accept it -- the public entry point
has to actually *reach* the predicate, and then actually *select* the
launcher.

The audit found three ways those differ at the current head:

  * `run()` never calls the predicate at all. It has no cleanroom branch
    whatsoever, so it is unserved for every configuration -- and the
    matrix's entry-point axis never mentioned `run` at all.
  * `map()` reaches the predicate only when the gate is enabled AND
    raw_mode is in ("plugin", "udf", "spawn").
  * `stream()` reaches it only for ("plugin", "udf") -- spawn is absent.

So a cell can be predicate-SERVED yet dispatch-UNREACHABLE. This module
measures dispatch by *observing* it rather than by reasoning about the
source:

  * `_cleanroom_eligible` is replaced with a probe that records that it
    was called, then returns the real answer;
  * the executors that the cleanroom path would otherwise use are
    replaced with recorders, so "which route did this actually take" is
    answered by what ran, not by what ought to have run.

That keeps production dispatch untouched -- the work order forbids
refactoring it to make the matrix easier, and this does not: the public
functions still execute their own branch logic; only the leaves are
observed.

Route vocabulary (deliberately distinct; do not merge these):
    cleanroom-selected      the launcher branch was taken
    cleanroom-not-reached   the predicate was never consulted
    validation-rejected     public validation refused the call first
    numa-pipeline           the dedicated multi-node executor ran
    splice-pipeline         the dedicated splice executor ran
    in-process / reactor    the ordinary non-launcher execution ran
    unsupported             refused with no fallback route
    unclassified            nothing observed -- a finding, never a pass
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir))
if os.path.join(_ROOT, "python") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "python"))


# --------------------------------------------------------------------------
# Route constants
# --------------------------------------------------------------------------

CLEANROOM_SELECTED = "cleanroom-selected"
CLEANROOM_NOT_REACHED = "cleanroom-not-reached"
VALIDATION_REJECTED = "validation-rejected"
NUMA_PIPELINE = "numa-pipeline"
SPLICE_PIPELINE = "splice-pipeline"
IN_PROCESS = "in-process/reactor"
UNSUPPORTED = "unsupported"
UNCLASSIFIED = "unclassified"

ROUTES = (
    CLEANROOM_SELECTED,
    CLEANROOM_NOT_REACHED,
    VALIDATION_REJECTED,
    NUMA_PIPELINE,
    SPLICE_PIPELINE,
    IN_PROCESS,
    UNSUPPORTED,
    UNCLASSIFIED,
)


class _Probe:
    """Records which leaves a public call actually reached.

    Restores every attribute it replaces, including on exception, so a
    failed probe cannot leave the module patched for the next cell.
    """

    def __init__(self, gate=True, launcher=True):
        self.gate = gate
        self.launcher = launcher
        self.predicate_called = 0
        self.launcher_taken = 0
        self.numa = 0
        self.splice = 0
        self.reactor = 0
        self.in_process = 0
        self.cleanroom = 0
        self.error = None
        self._saved = []

    def __enter__(self):
        # NOT `from forkrun import run`: `run` is also the name of the
        # exported FUNCTION, and the import binds that, so every
        # attribute lookup below would fail. The module is only reachable
        # through sys.modules -- the same idiom tools/capability_matrix.py
        # uses via `sys.modules['forkrun.run']`.
        import forkrun                                  # noqa: F401
        Rm = sys.modules["forkrun.run"]

        self._Rm = Rm
        real_eligible = Rm._cleanroom_eligible
        probe_self = self

        def probe_eligible(*a, **kw):
            probe_self.predicate_called += 1
            return real_eligible(*a, **kw)

        def probe_enabled():
            return probe_self.gate

        def probe_launcher_path():
            return "/nonexistent/_forkrun_cleanroom" if probe_self.launcher \
                else None

        def wrap(name, counter):
            real = getattr(Rm, name, None)
            if real is None:
                return

            def probe(*a, **kw):
                setattr(probe_self, counter, getattr(probe_self, counter) + 1)
                raise _StopRoute()
            probe.__name__ = name
            self._saved.append((name, real))
            setattr(Rm, name, probe)

        self._patch(Rm, "_cleanroom_eligible", probe_eligible)
        self._patch(Rm, "_cleanroom_enabled", probe_enabled)
        self._patch(Rm, "_cleanroom_launcher_path", probe_launcher_path)

        # Record the ordinary executors. Raising _StopRoute ends the call
        # as soon as we know the route, which keeps the probe fast and
        # avoids running a real workload for every cell.
        wrap("_execute_numa_locked", "numa")
        wrap("_execute_cleanroom", "cleanroom")
        wrap("_execute_cleanroom_stream", "cleanroom")
        wrap("_splice_reactor_gen", "splice")
        wrap("_splice_stream_gen", "splice")
        wrap("_splice_stream_reactor_gen", "splice")
        wrap("_execute_reactor_locked", "reactor")
        wrap("_execute_ingest_reactor_locked", "reactor")
        wrap("_execute_ingest_stream_reactor", "reactor")
        wrap("_execute", "in_process")
        wrap("_execute_streaming_reactor", "reactor")
        wrap("_execute_locked", "in_process")
        return self

    def _patch(self, obj, name, value):
        self._saved.append((name, getattr(obj, name)))
        setattr(obj, name, value)

    def __exit__(self, *exc):
        Rm = self._Rm
        for name, real in reversed(self._saved):
            setattr(Rm, name, real)
        self._saved = []
        return False

    def route(self):
        """Resolve the observation into exactly one route."""
        if self.cleanroom:
            return CLEANROOM_SELECTED
        if self.splice:
            return SPLICE_PIPELINE
        if self.numa:
            return NUMA_PIPELINE
        if self.reactor:
            return IN_PROCESS
        if self.in_process:
            return IN_PROCESS
        if self.predicate_called:
            # Reached the predicate but did not select the launcher: the
            # predicate declined, or the launcher was missing.
            return CLEANROOM_NOT_REACHED
        if isinstance(self.error, (TypeError, ValueError, FileNotFoundError,
                                   NotADirectoryError, IsADirectoryError,
                                   PermissionError)):
            return VALIDATION_REJECTED
        if self.error is not None:
            return UNSUPPORTED
        return UNCLASSIFIED


class _StopRoute(Exception):
    """Raised by an instrumented leaf once the route is known."""


def probe_call(entry, *, source, payload, gate=True, launcher=True,
               **kwargs):
    """Call a public entry point and report the route it ACTUALLY took.

    Returns (route, predicate_called, error_type_name).
    """
    import forkrun                                      # noqa: F401
    Rm = sys.modules["forkrun.run"]

    with _Probe(gate=gate, launcher=launcher) as p:
        try:
            if entry == "run":
                Rm.run(payload, source, **kwargs)
            elif entry == "map":
                Rm.map(payload, source, **kwargs)
            elif entry == "stream":
                for _ in Rm.stream(payload, source, **kwargs):
                    break
            else:
                raise ValueError("unknown entry point %r" % (entry,))
        except _StopRoute:
            pass
        except BaseException as exc:              # noqa: BLE001
            p.error = exc
    return p.route(), p.predicate_called, type(p.error).__name__