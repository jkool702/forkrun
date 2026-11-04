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
SIGINT is NEVER captured by that policy (it stays ``KeyboardInterrupt``
→ ``ForkrunInterrupted``). Separately, the process-wide deferral below
installs a short-lived recorder around critical sections; it does not
convert SIGINT either -- it delivers ``KeyboardInterrupt`` at the
section boundary (see "SIGINT deferral" below).

**Handler restoration is a correctness invariant, not cleanup
nicety** (W-PORTDEFER red line): previous dispositions are saved
at install and restored on guard exit come what may — a host
app's handler must survive a forkrun run.
"""

from __future__ import annotations

import os
import signal as _signal
import sys as _sys
import threading as _threading

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


# ---------------------------------------------------------------------------
# SIGINT deferral: PROCESS-WIDE, kernel-level, thread-agnostic
# ---------------------------------------------------------------------------
#
# THE DEFECT THIS REPLACES, IN TWO STAGES.
#
# 1. The original implementation blocked SIGINT with
#    ``signal.pthread_sigmask``. A mask is PER THREAD, but CPython runs a
#    Python-level signal handler in the MAIN thread regardless of which
#    thread received the signal. With any sibling thread eligible, a
#    process-directed SIGINT (a worker calling
#    ``os.kill(getppid(), SIGINT)`` -- the real shape) was delivered to
#    that sibling, and CPython raised ``KeyboardInterrupt`` in the MAIN
#    thread at an arbitrary bytecode boundary, including inside the
#    "protected" section. Measured: 0/10 inside with no sibling thread,
#    10/10 with one.
#
# 2. A Python-level handler fixes that for main-thread callers, but
#    ``signal.signal`` is main-thread-only. A run invoked from a worker
#    thread -- a supported shape, serialised by ``_RUN_LOCK`` -- could
#    not arm it at all, and the host's callable could only be restored
#    from the main thread. A warning there is not a guarantee.
#
# THE MODEL: ONE KERNEL DISPOSITION, SWAPPED IN C.
#
#   * ``_shim.c`` owns the kernel state. ``fr_py_sigint_defer_begin``
#     saves the host's ``struct sigaction`` and installs a recorder that
#     only sets a ``sig_atomic_t`` (async-signal-safe: no allocation, no
#     Python, no locks). ``fr_py_sigint_defer_end`` restores the saved
#     disposition FIRST and then reports whether a signal arrived.
#     ``fr_py_sigint_defer_cancel`` is the forked-child reset.
#   * This module owns the process-wide DEPTH and GENERATION. The
#     outermost section arms the recorder; nested sections (same thread
#     or another) only increment the depth; the outermost exit disarms
#     and delivers.
#   * Delivery honours the restored disposition SYNCHRONOUSLY on the
#     thread that closes the outermost section. ``SIG_IGN`` drops it and
#     ``SIG_DFL`` re-raises through the kernel so the default action
#     applies. A Python-level disposition (``default_int_handler`` or a
#     host callable) is invoked DIRECTLY, on this thread, after the
#     kernel disposition has been restored.
#
#     THAT LAST POINT IS LOAD-BEARING, AND A KERNEL RE-RAISE IS WRONG.
#     ``os.kill(getpid(), SIGINT)`` with the main thread's SIGINT masked
#     hands the kernel delivery to an eligible sibling. CPython's C
#     handler then sets the main thread's trip flag, and the Python-level
#     ``KeyboardInterrupt`` is raised at whatever bytecode the main
#     thread reaches next -- potentially inside the NEXT protected
#     section, or inside ``_RUN_LOCK.__exit__`` before it can clear the
#     session marker. Measured: the sibling-teardown test passed in
#     isolation and then left every later run in the process refused as
#     a "nested run". A pending Python-level trip is not something a
#     kernel disposition can defer; only delivering it here, before
#     returning to the caller, can guarantee the section boundary.
#   * A caller already unwinding keeps ITS exception: the recorded signal
#     is dropped (never delivered), because that exception is the run's
#     reason for stopping. The context manager cannot see an exception
#     propagating through a ``finally``, hence ``unwinding``.
#
# DELIVERY THREAD: A DELIBERATE DEPARTURE FROM CPYTHON'S CONVENTION.
# CPython runs a Python-level signal handler on the MAIN thread of the
# main interpreter no matter which thread the kernel delivered the
# signal to. The deferral cannot do that: it has already restored the
# kernel disposition, and re-raising through the kernel to regain
# main-thread dispatch is exactly the late-interrupt bug above. So the
# handler runs SYNCHRONOUSLY on the thread that closes the outermost
# section -- which may be a background thread, because ``_RUN_LOCK``
# permits a run from one. Consequences, all tested:
#
#   * ``default_int_handler`` raises ``KeyboardInterrupt`` on THAT
#     thread. A run started from a background thread therefore raises
#     there, not on the main thread. This is the supported contract.
#   * A custom host callable receives ``(signo, frame)`` on that thread.
#     A host that requires main-thread dispatch must marshal itself; the
#     deferral will not move the callback.
#   * ``SIG_IGN`` drops the signal and ``SIG_DFL`` (or a C-level
#     disposition CPython cannot see, reported as ``None``) re-raises
#     through the kernel so the kernel's default action applies.
#
# The same thread contract covers BOTH delivery paths. A signal recorded
# while the section was open is delivered by ``_disarm`` returning True.
# A SIGINT still pending in the KERNEL at the boundary is claimed by
# end() (sigtimedwait) and reported the same way: a process-directed
# signal whose eligible thread was never scheduled must not be left to
# surface through CPython's handler at an arbitrary later bytecode.
# A recorder invocation that was already running when the section closed
# parks a HANDOFF in C and ``_disarm`` reports it the same way; it is not
# re-raised through the kernel. A signal that arrives after the previous
# section closed has no open interval: a recorder invocation that sees
# the closed generation forwards it through the restored host
# disposition (late, but never lost). The STALE path in ``_arm`` is
# defensive for a park left by an older substrate, and is exercised by
# the test-only fault hook. A recorder invocation that starts after the
# FINAL boundary has closed (the unobservable "kernel dequeued it,
# handler not entered yet" residual) takes the same forwarding path
# rather than parking for a begin() that may never come. The only other
# kernel re-raise is the broken-state last resort (SIG_DFL), which is
# the point at which the process must remain interruptible.
#
# FORK. Pending signals are not inherited across fork, and neither is the
# parent's reason for deferring. ``after_fork_child`` restores the saved
# disposition, clears the armed/seen/pending flags, resets the depth, and
# bumps the generation so the copied scope's ``__exit__`` is a no-op
# instead of decrementing the parent's depth. It MUST NOT take the state
# lock: a sibling thread may have held it at the moment of the fork, and
# the child has no thread to release it.
#
# The recorder never takes the lock: a signal can interrupt the main
# thread while it holds it.


class DeferralError(RuntimeError):
    """The C recorder could not establish a clean deferral boundary.

    Raised when arming, disarming, or the forked-child reset fails. It
    always means the process's SIGINT disposition is not provably the
    one the caller asked for, so the state is reported rather than
    assumed. A subclass of RuntimeError so existing callers that catch
    RuntimeError keep working.
    """


class _DeferState:
    __slots__ = ("lock", "depth", "generation")

    def __init__(self):
        self.lock = _threading.RLock()
        # Number of open sections PROCESS-WIDE. Only the transition 0->1
        # arms the kernel recorder, and 1->0 disarms it, so nesting and
        # overlapping groups cannot deliver twice or restore early.
        self.depth = 0
        # Bumped when a group closes and when a forked child resets, so a
        # scope object from a previous group/process cannot mutate the
        # current one.
        self.generation = 0


_STATE = _DeferState()

# The last boundary failure that could not be raised (because an
# exception was already unwinding). Diagnostics/tests only.
_LAST_DEFERRAL_FAILURE = None


def _shim():
    """The substrate lib (deferral is a C facility); fail closed."""
    from ._bindings import get as _get  # noqa: PLC0415

    lib = _get()
    try:
        lib.fr_py_sigint_defer_begin
    except AttributeError:
        raise RuntimeError(
            "forkrun: the substrate predates process-wide SIGINT "
            "deferral (fr_py_sigint_defer_* missing); rebuild it with "
            "'make -f Makefile.substrate python-substrate'") from None
    return lib


# The C layer's positive return codes (python/forkrun/_shim.c). Negative
# codes are errors and are mapped in _RC_TEXT.
_RC_OK = 0
_RC_SEEN = 1
_RC_HANDOFF = 2
_RC_STALE = 3


def _arm():
    """Arm the outermost section (idempotent at the kernel layer).

    Fail closed: every negative return means the recorder is not provably
    installed, so the section is not opened at all.

    STALE means the recorder has a parked SIGINT from a closed
    generation. This is a defensive path: the CAS protocol forwards a
    late recorder invocation through the host disposition instead of
    parking it for a begin() that may never come, so in normal operation
    STALE is unreachable. The test-only fault hook exercises it, and an
    older substrate could still leave a park. There is no open interval
    for it to belong to, so it is delivered NOW, before this section
    opens, through the host disposition; then the arm is retried.
    Delivering it inside the section, or clearing it, would each violate
    the contract in a different direction.
    """
    lib = _shim()
    while True:
        rc = lib.fr_py_sigint_defer_begin()
        if rc == _RC_OK:
            return
        if rc == _RC_STALE:
            _deliver(_signal.SIGINT)
            continue
        raise DeferralError(
            "forkrun: cannot arm process-wide SIGINT deferral (C rc=%d: %s)"
            % (rc, _RC_TEXT.get(rc, "unknown")))


# The C layer's return codes (python/forkrun/_shim.c). Kept as a table
# rather than an if-chain so a new code cannot be reported as "unknown"
# by accident: the mapping is data, and an unmapped code still names the
# number.
_RC_TEXT = {
    -1: "could not read the host SIGINT disposition",
    -2: "could not install the SIGINT recorder",
    -3: ("could not restore the host SIGINT disposition; the recorder may "
         "still be installed and deferral is disabled until the process "
         "is restarted or the state is reset"),
    -4: ("an in-flight SIGINT recorder invocation did not finish; the "
         "pending state cannot be proven complete"),
    -5: ("a previous SIGINT disposition failure left the deferral state "
         "unsafe"),
}


def _disarm():
    """Restore the host disposition; True iff a SIGINT must be delivered.

    True covers a signal recorded while the section was open, a SIGINT
    still pending in the kernel at the boundary (claimed by end() before
    it restores), and an in-flight recorder invocation that parked a
    HANDOFF at the boundary. Raises DeferralError when the C layer could
    not establish a clean boundary. The caller must NOT report success in
    that case: the recorder may still be installed, and the pending state
    is unknown.
    """
    rc = _shim().fr_py_sigint_defer_end()
    if rc < 0:
        raise DeferralError(
            "forkrun: SIGINT deferral could not be closed cleanly (C "
            "rc=%d: %s)" % (rc, _RC_TEXT.get(rc, "unknown")))
    return rc != _RC_OK


def _deliver(signo):
    """Deliver a deferred signal through the restored disposition.

    Python-level dispositions are invoked SYNCHRONOUSLY. A kernel
    re-raise cannot be used for them: with the main thread masked, the
    kernel delivers the signal to an eligible sibling, CPython then sets
    the main thread's trip flag, and the resulting ``KeyboardInterrupt``
    lands at an arbitrary later bytecode -- after the section boundary
    this whole facility exists to enforce. ``SIG_IGN`` is a no-op;
    ``SIG_DFL`` (or a disposition not installed from Python, reported as
    ``None``) is re-raised so the default action applies.
    """
    handler = _signal.getsignal(signo)
    if handler is _signal.SIG_IGN:
        return
    if handler is _signal.SIG_DFL or handler is None:
        os.kill(os.getpid(), signo)
        return
    handler(signo, _sys._getframe(1))


class _DeferredInterrupt:
    """Defer SIGINT across a critical section (process-wide).

    The signal is NOT swallowed. It is delivered through the host's prior
    disposition as the outermost section exits: ``default_int_handler``
    raises ``KeyboardInterrupt``, a custom callable receives
    ``(signo, frame)``, ``SIG_IGN`` drops it, and ``SIG_DFL`` re-raises
    it so the default action applies.

    When an exception is already propagating, that exception is the run's
    reason for stopping and it must survive: the deferred SIGINT is
    redundant then, so it is dropped (never delivered) and the original
    is preserved.

    SIGHUP/SIGTERM are NOT deferred: under the checkpoint policy
    forkrun's own handler records them without raising, so they cannot
    abandon a cleanup. Under the default policy they keep their default
    disposition, which terminates the process -- there is no cleanup
    left to protect.
    """

    def __init__(self, unwinding=False):
        # The caller was already unwinding when this section was entered.
        # The context manager cannot see that by itself: an exception
        # propagating THROUGH the section (a teardown runs in a finally)
        # is not raised inside the `with` block, so __exit__ sees no
        # exception at all. The caller has to say so, or the deferred
        # interrupt would replace the run's own error.
        self._unwinding = unwinding
        self._gen = None
        self._active = False

    def __enter__(self):
        st = _STATE
        with st.lock:
            if st.depth == 0:
                # Arm BEFORE publishing the depth: a signal arriving in
                # this window is recorded by the kernel recorder, and the
                # section is not considered open until the recorder can
                # actually catch it.
                _arm()
            st.depth += 1
            self._gen = st.generation
            self._active = True
        return self

    def __exit__(self, exc_type, exc, tb):
        st = _STATE
        signo = None
        failure = None
        with st.lock:
            # A forked child reset the state: the parent's section is not
            # this process's section, so leave it alone.
            if not self._active or self._gen != st.generation:
                return False
            self._active = False
            if st.depth <= 0:
                return False
            st.depth -= 1
            if st.depth > 0:
                return False
            # OUTERMOST exit.
            unwinding = exc_type is not None or self._unwinding
            try:
                deliver = _disarm()
            except DeferralError as err:
                failure = err
                deliver = False
            st.generation += 1
            if deliver and not unwinding:
                signo = _signal.SIGINT
        if failure is not None:
            if not unwinding:
                raise failure
            # An exception is already propagating. It is the run's reason
            # for stopping, and a teardown failure must never replace it
            # (the diagnosis would be lost). The failure is reported on
            # stderr and recorded, and every later section fails closed
            # because the C layer is left in its broken state.
            _record_deferral_failure(failure)
            return False
        if signo is not None:
            # Outside the lock: the host handler may call back into
            # forkrun (and on the main thread it raises immediately).
            _deliver(signo)
        return False


def defer_interrupts(unwinding=False):
    """Defer SIGINT for the duration of the block.

    The ONE place that defers an interrupt, so every critical section
    (the teardown's cleanup sequence, the fork-adoption window, the
    checkpoint choreography) has the same semantics.

    `unwinding` says the CALLER was already propagating an exception when
    the section was entered; see _DeferredInterrupt.
    """
    return _DeferredInterrupt(unwinding=unwinding)


def defer_interrupts_for_cleanup():
    """Defer for a cleanup section and infer whether we are unwinding.

    Call this from a ``finally``: the exception (if any) that sent us
    there is exactly the one that must survive a deferred interrupt, and
    ``sys.exc_info()`` is the authoritative way to observe it. Computing
    it here -- instead of at each of the executor finally blocks -- keeps
    the precedence rule in one place.
    """
    return _DeferredInterrupt(unwinding=_sys.exc_info()[0] is not None)


def uninterruptible(fn, /, *args, **kwargs):
    """Run ``fn`` with SIGINT deferred, returning its result.

    A cleanup sequence that can be interrupted half-way is not a cleanup:
    the children it had not reached are left behind. This is the ONE
    callable wrapper for that property; `interrupt_safe` is its decorator
    form, and the checkpoint choreography uses it directly so an operator
    interrupt cannot abandon a half-published checkpoint.
    """
    with defer_interrupts_for_cleanup():
        return fn(*args, **kwargs)


def interrupt_safe(fn):
    """Run `fn` with SIGINT deferred (decorator form of uninterruptible)."""
    import functools  # noqa: PLC0415

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return uninterruptible(fn, *args, **kwargs)

    return wrapper


def _record_deferral_failure(err):
    """Record (and report) a boundary failure that could not be raised.

    Called when the failure happens while an exception is already
    unwinding. The exception keeps propagating -- it is the run's
    reason for stopping -- but the deferral failure must not vanish:
    it is written to stderr and kept for diagnostics/tests.
    """
    global _LAST_DEFERRAL_FAILURE
    _LAST_DEFERRAL_FAILURE = err
    try:
        _sys.stderr.write("forkrun [FATAL]: %s\n" % (err,))
        _sys.stderr.flush()
    except Exception:
        pass


def deferral_failure():
    """The last boundary failure that could not be raised, or None."""
    return _LAST_DEFERRAL_FAILURE


def after_fork_child():
    """Reset SIGINT-deferral state in a freshly forked child.

    Pending signals are NOT inherited across fork, and neither is the
    parent's reason for deferring. The child:

      * restores the disposition the PARENT saved, so the child does not
        keep the recorder installed,
      * starts at depth 0 (the copied scope's ``__exit__`` is a no-op via
        the generation check),
      * discards the parent's recorded signal (it belongs to the parent
        process and must not be replayed here).

    Called by ``_childreg.fork_child`` in the child branch, BEFORE any
    other Python statement can raise: the child's first act must be to
    stop being the parent.

    THE LOCK IS REPLACED, NOT ACQUIRED. A sibling thread may have held
    ``st.lock`` at the instant of the fork; the child has only the
    forking thread, so acquiring it could block forever. With one thread
    alive the direct assignments below are race-free.
    """
    st = _STATE
    st.lock = _threading.RLock()
    st.depth = 0
    st.generation += 1
    try:
        rc = _shim().fr_py_sigint_defer_cancel()
    except Exception as exc:
        # A child that keeps the recorder would defer SIGINT forever and
        # never honour the host's disposition. Fail closed: the caller
        # turns this into a failed worker, never a silently
        # mis-signalled one.
        raise DeferralError(
            "forkrun: a forked child could not restore the parent's "
            "SIGINT disposition (%r); refusing to run with a stale "
            "deferral handler" % (exc,)) from exc
    if rc < 0:
        raise DeferralError(
            "forkrun: a forked child could not restore the parent's "
            "SIGINT disposition (C rc=%d: %s); refusing to run with a "
            "stale deferral handler"
            % (rc, _RC_TEXT.get(rc, "unknown")))


def deferral_state():
    """Diagnostics: the one authoritative deferral state (tests use it)."""
    st = _STATE
    return {"depth": st.depth, "generation": st.generation,
            "armed": st.depth > 0}


def guard(policy, abort_fn=None):
    """Build a SignalGuard (no-op unless policy == "checkpoint")."""
    return SignalGuard(policy, abort_fn=abort_fn)


__all__ = ["POLICY_DEFAULT", "POLICY_CHECKPOINT",
           "validate_signal_policy", "SignalGuard", "guard",
           "defer_interrupts", "defer_interrupts_for_cleanup",
           "uninterruptible", "interrupt_safe", "after_fork_child",
           "deferral_state", "DeferralError", "deferral_failure"]
