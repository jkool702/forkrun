"""Opt-in parent signal policy (D-PORT1).

A library installing signal handlers by default is invasive — it
would capture signals belonging to the host application (and
forkrun explicitly supports running *inside* event-loop hosts).
So the default policy installs NOTHING (documented honest
contract: Ctrl-C raises through as standard Python;
graceful-abort-and-checkpoint on operator signals is
Bash-frontend functionality in v3.6.0).

``signal_policy="checkpoint"`` (opt-in) installs SIGHUP/SIGTERM
handlers — plus SIGUSR1 when ``FORKRUN_PREEMPT_MODE=1``
(mirroring the Bash conditional trap; Bash exit 138) — for the
duration of one run. The handler records the signal into a
preallocated slot array and raises the engine fire alarm; it never
allocates and never calls arbitrary code (W-REL5-C6). The run's
existing abort teardown then reaps, and the armed W-PY22
checkpoint choreography publishes, before the wrapper translates
the pending signal into ``ForkrunTerminated`` / ``ForkrunPreempted``.
SIGINT is NEVER captured (stays ``KeyboardInterrupt`` →
``ForkrunInterrupted``).

**Handler restoration is a correctness invariant, not cleanup
nicety** (W-PORTDEFER red line): previous dispositions are saved
at install and restored on guard exit come what may — a host
app's handler must survive a forkrun run.
"""

from __future__ import annotations

import os
import signal as _signal

POLICY_DEFAULT = "default"
POLICY_CHECKPOINT = "checkpoint"
_VALID_POLICIES = (POLICY_DEFAULT, POLICY_CHECKPOINT)

# W-REL5-C6: handler-side signal slots (preallocated — indexed
# stores never allocate, unlike list.append). Saturation drops
# extras (pending is already non-empty, so check() still fires).
_MAX_PENDING_SLOTS = 32


def validate_signal_policy(value):
    """Validate a signal_policy option (D-PORT1).

    Returns the policy string. None means default. Anything else
    raises ValueError (fail-closed: a misspelled policy must never
    silently run unguarded).
    """
    if value is None:
        return POLICY_DEFAULT
    if value in _VALID_POLICIES:
        return value
    raise ValueError(
        "signal_policy must be one of %r, got %r"
        % (_VALID_POLICIES, value))


def _abort_current():
    """Best-effort engine abort for handler context (never raises)."""
    try:
        from ._bindings import get as _get
        _get().fr_py_abort()
    except Exception:
        pass


class SignalGuard:
    """One run's opt-in handler installation (use via guard())."""

    def __init__(self, policy, abort_fn=None):
        self.policy = validate_signal_policy(policy)
        self._abort_fn = abort_fn or _abort_current
        self._custom_abort = abort_fn is not None
        self._old = {}
        self.pending = []
        self._slots = [0] * _MAX_PENDING_SLOTS
        self._nslots = 0
        self._engine_abort = None
        self._armed_preempt = (
            os.environ.get("FORKRUN_PREEMPT_MODE") == "1")

    def _handler(self, signo, _frame):
        # Handler context (main thread, between bytecodes): indexed
        # store into preallocated slots (never allocates), then the
        # engine fire alarm ONLY (pre-resolved ctypes call — the
        # engine's fr_py_abort is a single write() and safe here).
        # Arbitrary callables (self._abort_fn) NEVER run in handler
        # context — they are honored at drain time (check()/pump)
        # instead. Never raises.
        try:
            if self._nslots < _MAX_PENDING_SLOTS:
                self._slots[self._nslots] = signo
                self._nslots += 1
        except Exception:
            pass
        try:
            _abort = self._engine_abort
            if _abort is not None:
                _abort()
        except Exception:
            pass

    def _drain(self):
        """Move handler slots to pending (normal context ONLY).

        Allocation and arbitrary abort_fn calls are safe here
        (never in _handler). Custom abort_fn runs once per drained
        signal; the engine alarm already fired synchronously.
        """
        if self._nslots:
            for i in range(self._nslots):
                self.pending.append(self._slots[i])
            if self._custom_abort:
                for _ in range(self._nslots):
                    try:
                        self._abort_fn()
                    except Exception:
                        pass
            self._nslots = 0

    def _wanted(self):
        sigs = [_signal.SIGHUP, _signal.SIGTERM]
        if self._armed_preempt:
            sigs.append(_signal.SIGUSR1)
        return sigs

    def __enter__(self):
        if self.policy != POLICY_CHECKPOINT:
            return self
        # W-REL5-C2: signal.signal works only on the main thread —
        # anywhere else every per-sig install below raises ValueError
        # and the guard would run the whole job unguarded (silent
        # no-op in exactly the threaded/event-loop hosts this module
        # exists for). Fail loudly with the remedy instead.
        import threading as _threading  # noqa: PLC0415

        if _threading.current_thread() is not \
                _threading.main_thread():
            raise RuntimeError(
                "forkrun signal_policy='checkpoint' requires the "
                "main thread (signal.signal is main-thread-only; "
                "called from %r). Run forkrun on the main thread, "
                "or use the default policy."
                % (_threading.current_thread().name,))
        # W-REL5-C6: pre-resolve the engine alarm BEFORE any signal
        # can arrive, so the handler performs zero attribute chains
        # or imports (allocation-free steady state).
        try:
            from ._bindings import get as _get  # noqa: PLC0415
            self._engine_abort = _get().fr_py_abort
        except Exception:
            self._engine_abort = None
        for sig in self._wanted():
            try:
                self._old[sig] = _signal.getsignal(sig)
            except (OSError, ValueError):
                continue
            try:
                _signal.signal(sig, self._handler)
            except (OSError, ValueError):
                self._old.pop(sig, None)
        return self

    def __exit__(self, *exc):
        self.restore()
        self._drain()
        if (self.policy == POLICY_CHECKPOINT and exc[0] is not None
                and issubclass(exc[0], RuntimeError) and self.pending):
            # Abort-driven engine failure (worker-failure RuntimeError
            # after OUR abort killed the workers): attribute to the
            # operator signal, not the workers. Bash precedence —
            # a trapped signal wins over concurrent faults
            # (frun.bash keeps _ret_val when _fr_signalled is set).
            # Only RuntimeError is translated: KeyboardInterrupt /
            # GeneratorExit / anything else propagates untouched
            # (never mask generator protocol or KI semantics).
            self.check()
        return False

    def restore(self):
        """Restore every saved disposition (idempotent)."""
        for sig, old in list(self._old.items()):
            try:
                _signal.signal(sig, old)
            except (OSError, ValueError):
                pass
            self._old.pop(sig, None)

    def check(self):
        """Raise the taxonomy error for the first pending signal.

        Call AFTER engine teardown (checkpoint publication lives
        there) — the raise then carries a resumable state.
        No pending signal: returns None.
        """
        self._drain()
        if not self.pending:
            return None
        from .exceptions import (ForkrunPreempted,  # noqa: PLC0415
                                 ForkrunTerminated)
        signo = self.pending[0]
        if signo == _signal.SIGUSR1:
            raise ForkrunPreempted(
                "forkrun: preempted by SIGUSR1 under "
                "FORKRUN_PREEMPT_MODE=1 (Bash exit 138); abort "
                "issued — resume from the checkpoint when "
                "checkpoint_file= was armed", signo=signo)
        name = "SIGHUP" if signo == _signal.SIGHUP else "SIGTERM"
        raise ForkrunTerminated(
            "forkrun: %s received in the parent (Bash exit 143); "
            "abort issued, teardown complete — resume from the "
            "checkpoint when checkpoint_file= was armed" % (name,),
            signo=signo)


class _DeferredInterrupt:
    """Defer SIGINT across a critical section.

    Only SIGINT is deferred, and only because it is the one signal
    forkrun does NOT capture: it stays Python's ``KeyboardInterrupt``
    (``default_int_handler``), which is raised at an arbitrary
    bytecode boundary. A cleanup sequence that can be interrupted
    half-way is not a cleanup -- the children it had not reached are
    left behind -- so the teardown runs its sequence with SIGINT
    deferred.

    The signal is NOT swallowed. It is delivered as soon as the mask
    is restored, i.e. as the critical section's work completes. When
    an exception is already propagating, that exception is the run's
    reason for stopping and it must survive: the deferred SIGINT is
    redundant then, so it is drained (never delivered) and the
    original is preserved.

    SIGHUP/SIGTERM are NOT deferred: under the checkpoint policy
    forkrun's own handler records them without raising, so they
    cannot abandon a cleanup. Under the default policy they keep
    their default disposition, which terminates the process -- there
    is no cleanup left to protect.
    """

    def __init__(self, unwinding=False):
        self._old = None
        # The caller was already unwinding when this section was
        # entered. The context manager cannot see that by itself: an
        # exception propagating THROUGH the section (the teardown
        # runs in a finally) is not raised inside the `with` block,
        # so __exit__ sees no exception at all. The caller has to say
        # so, or the deferred interrupt would replace the run's own
        # error.
        self._unwinding = unwinding

    def __enter__(self):
        try:
            self._old = _signal.pthread_sigmask(
                _signal.SIG_BLOCK, {_signal.SIGINT})
        except (OSError, ValueError):
            # Not the main thread (pthread_sigmask is main-thread
            # only) or the platform lacks it: nothing to defer.
            self._old = None
        return self

    def __exit__(self, exc_type, exc, tb):
        old = self._old
        self._old = None
        if old is None:
            return False
        if exc_type is not None or self._unwinding:
            # An exception is already propagating: preserve it. The
            # deferred SIGINT is redundant -- the run is already
            # stopping -- so it is drained BEFORE the mask is
            # restored, which means it is never delivered and cannot
            # replace the original.
            try:
                if _signal.SIGINT in _signal.sigpending():
                    _signal.sigwait({_signal.SIGINT})
            except (OSError, ValueError):
                pass
        try:
            _signal.pthread_sigmask(_signal.SIG_SETMASK, old)
        except (OSError, ValueError):
            pass
        # No exception in flight: the deferred SIGINT (if any) is
        # delivered at the next bytecode -- i.e. right here -- and
        # propagates, which is the point: the interrupt is deferred,
        # not lost.
        return False


def defer_interrupts(unwinding=False):
    """Defer SIGINT for the duration of the block.

    The ONE place that defers an interrupt, so every critical section
    (the teardown's cleanup sequence) has the same semantics.

    `unwinding` says the CALLER was already propagating an exception
    when the section was entered; see _DeferredInterrupt.
    """
    return _DeferredInterrupt(unwinding=unwinding)


def interrupt_safe(fn):
    """Run `fn` with SIGINT deferred.

    A cleanup sequence that can be interrupted half-way is not a
    cleanup: the children it had not reached are left behind. This is
    the ONE wrapper that provides that property, so every teardown
    gets it instead of each growing its own local guard.
    """
    import functools  # noqa: PLC0415
    import sys as _sys  # noqa: PLC0415

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # Was the CALLER unwinding? A teardown runs in a finally, and
        # an exception propagating through it is not raised INSIDE the
        # `with` block -- so the context manager cannot see it, and
        # the wrapper has to say so.
        unwinding = _sys.exc_info()[0] is not None
        with defer_interrupts(unwinding=unwinding):
            return fn(*args, **kwargs)

    return wrapper


def guard(policy, abort_fn=None):
    """Build a SignalGuard (no-op unless policy == "checkpoint")."""
    return SignalGuard(policy, abort_fn=abort_fn)


__all__ = ["POLICY_DEFAULT", "POLICY_CHECKPOINT",
           "validate_signal_policy", "SignalGuard", "guard"]
