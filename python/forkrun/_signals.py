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
import sys as _sys
import threading as _threading
import warnings as _warnings

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
# SIGINT deferral: PROCESS-WIDE, not thread-local
# ---------------------------------------------------------------------------
#
# THE DEFECT THIS REPLACES. The previous implementation blocked SIGINT
# with ``signal.pthread_sigmask``. A mask is PER THREAD, but CPython
# runs a Python-level signal handler in the MAIN thread regardless of
# which thread received the signal. So in a process with any other
# thread that had SIGINT unblocked, a process-directed SIGINT (a worker
# calling ``os.kill(getppid(), SIGINT)`` -- the real shape) was
# delivered to that thread, and CPython raised ``KeyboardInterrupt`` in
# the MAIN thread at an arbitrary bytecode boundary -- including inside
# the very section the mask was supposed to protect. Measured on a
# probe: 0/10 raised inside the section with no sibling thread, 10/10
# with one.
#
# THE MODEL. One process-wide state object, protected by one lock:
#
#   * The OUTERMOST section entered on the main thread installs a
#     Python handler for SIGINT. The handler only records ``(signo,
#     frame)`` into preallocated slots and returns -- it never
#     allocates and never calls host code.
#   * Nested sections (same thread or other threads) only increment a
#     process-wide depth. The handler records while depth > 0.
#   * The OUTERMOST exit restores the saved disposition FIRST, then
#     delivers the recorded signal through it: a callable is called
#     (``default_int_handler`` raises ``KeyboardInterrupt``), SIG_IGN
#     drops it, SIG_DFL re-raises it so the kernel's default action
#     applies.
#   * When the caller was already unwinding, the recorded signal is
#     dropped: that exception is the run's reason for stopping and must
#     survive. This is the same precedence the old implementation had.
#
# WHY NOTKEEP THE MASK. A mask can never be process-wide, so it can
# never make the guarantee this section exists for. The handler can.
#
# OFF THE MAIN THREAD. ``signal.signal`` is main-thread-only, so a
# section whose OUTERMOST entry is on another thread cannot install the
# handler. That case is not silently declared equivalent: it is a
# distinct, weaker mode (the process-wide handler is simply not
# installed, and CPython raises the interrupt on the main thread -- so
# the section is still not abandoned, but delivery is not delayed to
# this section's exit). One RuntimeWarning names the limitation the
# first time it happens. The realistic host shape -- runs in worker
# threads, serialised by _RUN_LOCK -- therefore keeps working, and the
# limitation is explicit rather than a silent no-op.
#
# FORK. Pending signals are not inherited across fork, and neither is
# the parent's reason for deferring. ``after_fork_child`` resets the
# child to depth 0, clears the parent's recorded state, restores the
# disposition the parent saved, and bumps a GENERATION so the copied
# ``_DeferredInterrupt`` object's ``__exit__`` (which the child runs as
# it leaves the ``with``) is a no-op instead of decrementing the
# parent's depth below zero.
#
# The handler never takes the lock: a signal can interrupt the main
# thread while it holds it. The handler only touches integers and
# preallocated slots, whose stores the GIL already serialises.

_MAX_DEFERRED = 32


class _DeferState:
    __slots__ = ("lock", "depth", "process_wide", "installed", "old",
                 "slots", "frames", "npending", "overflow", "generation",
                 "exiting", "warned")

    def __init__(self):
        self.lock = _threading.RLock()
        self.depth = 0
        # True when the outermost section installed the handler (it was
        # entered on the main thread). False for an off-main group.
        self.process_wide = False
        self.installed = False
        self.old = None
        # Handler-side storage, preallocated: indexed stores never
        # allocate, unlike list.append.
        self.slots = [0] * _MAX_DEFERRED
        self.frames = [None] * _MAX_DEFERRED
        self.npending = 0
        self.overflow = 0
        # Bumped when a forked child resets the state and when a group
        # closes, so a scope object from a previous group cannot mutate
        # the current one.
        self.generation = 0
        # True between "depth reached zero" and "handler restored": a
        # signal in that window must still be RECORDED, not raised.
        self.exiting = False
        self.warned = False


_STATE = _DeferState()


def _is_main_thread():
    return _threading.current_thread() is _threading.main_thread()


def _handler(signo, _frame):
    """Record a deferred SIGINT; never allocate, never call host code.

    Handler context (main thread, between bytecodes). An indexed store
    into the preallocated slots is the whole body -- arbitrary host
    callables are honoured at the outermost exit instead.
    """
    st = _STATE
    if st.depth > 0 or st.exiting:
        n = st.npending
        if n < _MAX_DEFERRED:
            st.slots[n] = signo
            st.frames[n] = _frame
            st.npending = n + 1
        else:
            # Saturation cannot lose the FACT of the signal: the run
            # still aborts on the first one. Counted so the exit path
            # can report multiplicity instead of pretending it did not
            # happen.
            st.overflow += 1
        return
    # The handler is only installed while a group is open, and the
    # group is closed only by a thread that restores it. Reaching here
    # means the signal module still points at us with no group open:
    # behave like the default disposition rather than swallowing it.
    raise KeyboardInterrupt


def _deliver(old, signo, frame, extra):
    """Honour the host's saved SIGINT disposition AFTER restoration.

    Called in normal context, with our handler already uninstalled.
    """
    if old is _signal.SIG_IGN:
        return
    if old is _signal.SIG_DFL:
        # Restored: re-raise the signal and let the kernel's default
        # action (terminate) happen with the process-wide disposition
        # the host asked for.
        os.kill(os.getpid(), signo)
        return
    if old is None:
        # getsignal() cannot represent a C-installed handler. The
        # install path refuses that case, so this is defensive only.
        raise KeyboardInterrupt
    # ``default_int_handler`` raises; a host callable may return.
    old(signo, frame)
    for _ in range(extra):
        # A returning host handler was called once per recorded signal
        # above only for the first; re-raise the rest through the
        # restored disposition so multiplicity is preserved rather
        # than silently collapsed.
        os.kill(os.getpid(), signo)


class _DeferredInterrupt:
    """Defer SIGINT across a critical section (process-wide).

    The signal is NOT swallowed. It is delivered through the host's
    prior disposition as the outermost section exits -- ``default_int_handler``
    raises ``KeyboardInterrupt`` there, a custom callable receives
    ``(signo, frame)``, ``SIG_IGN`` drops it, and ``SIG_DFL`` re-raises
    it so the default action applies.

    When an exception is already propagating, that exception is the
    run's reason for stopping and it must survive: the deferred SIGINT
    is redundant then, so it is dropped (never delivered) and the
    original is preserved. The context manager cannot see that by
    itself when the section runs in a ``finally``, hence ``unwinding``.

    SIGHUP/SIGTERM are NOT deferred: under the checkpoint policy
    forkrun's own handler records them without raising, so they cannot
    abandon a cleanup. Under the default policy they keep their default
    disposition, which terminates the process -- there is no cleanup
    left to protect.
    """

    def __init__(self, unwinding=False):
        self._unwinding = unwinding
        self._gen = None
        self._active = False

    def __enter__(self):
        st = _STATE
        with st.lock:
            if st.depth == 0:
                st.exiting = False
                st.process_wide = _is_main_thread()
                st.installed = False
                st.old = None
                st.npending = 0
                st.overflow = 0
                if st.process_wide:
                    old = _signal.getsignal(_signal.SIGINT)
                    if old is None:
                        raise RuntimeError(
                            "forkrun: cannot defer SIGINT -- the host's "
                            "SIGINT disposition was installed outside "
                            "Python (getsignal returned None), so it "
                            "cannot be saved and restored faithfully. "
                            "Install the handler with signal.signal(), or "
                            "run without interrupting the library.")
                    if old is _handler:
                        raise RuntimeError(
                            "forkrun: SIGINT is already deferred by a "
                            "section whose state was lost; refusing to "
                            "nest on top of a stale handler")
                    st.old = old
                    # Raise depth BEFORE the install so a signal that
                    # arrives in the install window is recorded rather
                    # than raised inside __enter__.
                    st.depth = 1
                    try:
                        _signal.signal(_signal.SIGINT, _handler)
                    except BaseException:
                        # The host's handler may have raised (a signal
                        # arrived before the install landed). Leave no
                        # half-installed state and no elevated depth.
                        try:
                            if _signal.getsignal(_signal.SIGINT) is _handler:
                                _signal.signal(_signal.SIGINT, st.old)
                        except (OSError, ValueError):
                            pass
                        st.depth = 0
                        st.process_wide = False
                        st.old = None
                        raise
                    st.installed = True
                else:
                    st.depth = 1
                    if not st.warned:
                        st.warned = True
                        _warnings.warn(
                            "forkrun: SIGINT deferral was entered on a "
                            "non-main thread (%r). signal.signal is "
                            "main-thread-only, so the process-wide handler "
                            "cannot be installed; the protected section is "
                            "still not abandoned (CPython raises the "
                            "interrupt on the main thread), but delivery is "
                            "not delayed to this section's exit. Run "
                            "forkrun on the main thread for full "
                            "deferral semantics."
                            % (_threading.current_thread().name,),
                            RuntimeWarning, stacklevel=3)
            else:
                st.depth += 1
            self._gen = st.generation
            self._active = True
        return self

    def __exit__(self, exc_type, exc, tb):
        st = _STATE
        pending = None
        with st.lock:
            # A forked child reset the state: the parent's section is
            # not this process's section, so leave it alone.
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
            if st.process_wide:
                if not _is_main_thread():
                    # The installing thread must be the last to leave.
                    # Production is serialised by _RUN_LOCK, so this can
                    # only be a caller nesting sections across threads
                    # improperly. Fail loudly instead of restoring a
                    # process-wide disposition from a thread that is
                    # not allowed to.
                    st.exiting = False
                    raise RuntimeError(
                        "forkrun: the outermost SIGINT-deferral section "
                        "was entered on the main thread but is exiting "
                        "on %r. A process-wide disposition can only be "
                        "restored from the main thread; nest sections "
                        "so the installing thread exits last."
                        % (_threading.current_thread().name,))
                # Freeze recording while the handler is restored, so a
                # signal in the restore window is still captured by our
                # handler rather than raised between the two operations.
                st.exiting = True
                n = st.npending
                first_signo = st.slots[0] if n else None
                first_frame = st.frames[0] if n else None
                extra = (n - 1 if n > 0 else 0) + st.overflow
                st.npending = 0
                st.overflow = 0
                st.installed = False
                old = st.old
                st.old = None
                try:
                    _signal.signal(_signal.SIGINT, old)
                finally:
                    st.exiting = False
                # Leave the group before delivery: the host handler may
                # call back into forkrun.
                st.depth = 0
                st.process_wide = False
                st.generation += 1
                if first_signo is not None and not unwinding:
                    pending = (old, first_signo, first_frame, extra)
                # Slots must not retain frame references.
                for i in range(n):
                    st.slots[i] = 0
                    st.frames[i] = None
            else:
                # Off-main group: nothing was installed, so there is
                # nothing to restore and no recorded signal to deliver
                # (CPython raised it on the main thread).
                st.depth = 0
                st.process_wide = False
                st.npending = 0
                st.overflow = 0
                st.generation += 1
        if pending is not None:
            _deliver(*pending)
        return False


def defer_interrupts(unwinding=False):
    """Defer SIGINT for the duration of the block.

    The ONE place that defers an interrupt, so every critical section
    (the teardown's cleanup sequence, the fork-adoption window) has the
    same semantics. Process-wide: see ``_DeferredInterrupt``.

    `unwinding` says the CALLER was already propagating an exception
    when the section was entered; see _DeferredInterrupt.
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

    A cleanup sequence that can be interrupted half-way is not a
    cleanup: the children it had not reached are left behind. This is
    the ONE callable wrapper for that property; `interrupt_safe` is its
    decorator form, and the checkpoint choreography uses it directly so
    an operator interrupt cannot abandon a half-published checkpoint.
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


def after_fork_child():
    """Reset SIGINT-deferral state in a freshly forked child.

    Pending signals are NOT inherited across fork, and neither is the
    parent's reason for deferring. The child:

      * starts at depth 0 (the copied scope's ``__exit__`` is a no-op
        via the generation check),
      * discards the parent's recorded signals (they belong to the
        parent process and must not be replayed here),
      * restores the disposition the PARENT saved, so the child does
        not keep forkrun's recording handler installed, and
      * keeps the parent's depth untouched (separate process).

    Called by ``_childreg.fork_child`` in the child branch, BEFORE any
    other Python statement can raise: the child's first act must be to
    stop being the parent.
    """
    st = _STATE
    with st.lock:
        old = st.old if st.installed else None
        st.depth = 0
        st.process_wide = False
        st.installed = False
        st.old = None
        st.npending = 0
        st.overflow = 0
        st.exiting = False
        st.generation += 1
    if old is not None:
        try:
            _signal.signal(_signal.SIGINT, old)
        except (OSError, ValueError) as exc:
            # A child that keeps the recording handler would defer
            # SIGINT forever and never honour the host's disposition.
            # Fail closed: the child's caller turns this into a failed
            # worker, never a silently mis-signalled one.
            raise RuntimeError(
                "forkrun: a forked child could not restore the parent's "
                "SIGINT disposition (%r); refusing to run with a stale "
                "deferral handler" % (exc,)) from exc


def deferral_state():
    """Diagnostics: the one authoritative deferral state (tests use it)."""
    st = _STATE
    return {"depth": st.depth, "process_wide": st.process_wide,
            "installed": st.installed, "pending": st.npending,
            "overflow": st.overflow, "generation": st.generation}


def guard(policy, abort_fn=None):
    """Build a SignalGuard (no-op unless policy == "checkpoint")."""
    return SignalGuard(policy, abort_fn=abort_fn)


__all__ = ["POLICY_DEFAULT", "POLICY_CHECKPOINT",
           "validate_signal_policy", "SignalGuard", "guard",
           "defer_interrupts", "defer_interrupts_for_cleanup",
           "uninterruptible", "interrupt_safe", "after_fork_child",
           "deferral_state"]
