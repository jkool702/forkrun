"""The authoritative registry of the children THIS PROCESS forked.

WHY THIS EXISTS
---------------
A child that is forked but not recorded is INVISIBLE. The teardown
cannot kill it, cannot reap it, and when it exits it becomes a
zombie -- an unreaped child that outlives the run.

That is not hypothetical. An exception raised between ``os.fork()``
and the caller's own bookkeeping -- a signal handler firing, a
MemoryError -- orphans the child, and the exception then unwinds past
every teardown that would have reaped it. Measured: injecting a
KeyboardInterrupt between the reactor's ``os.fork()`` and
``self.workers[wid] = slot`` leaves the forked worker alive, unowned,
and (once it exits) a zombie -- exactly the signature seen in
``test_resume_sigint``.

THE RULE
--------
Every fork in this package records its child HERE, before anything
else can raise, and the teardown reconciles the registry against what
it believes it owns. One registry, one rule, one reconciliation --
not a per-site convention.

PID REUSE
---------
A registered pid is safe to signal. The kernel keeps a pid reserved
for as long as the process is in the process table, and a
terminated-but-unreaped child (a zombie) keeps its pid reserved too.
A pid that is NOT our child raises ``ChildProcessError`` on waitpid,
which is how the registry tells "already reaped" from "still ours".
So the reconciliation can signal a registered pid without the
PID-reuse hazard that makes an unowned pid dangerous: the check is
"is it still my child?", not "was it ever my child?".
"""

import os
import signal as _signal
import time

from . import _signals

# pid -> owner label (a human-readable "who was this child")
_OWNED = {}


def fork_child():
    """os.fork(), with SIGINT deferred across it.

    WHY THIS EXISTS
    ---------------
    CPython's ``os.fork()`` calls ``logging._prepareFork()`` in the
    PARENT before the syscall and ``logging._afterFork()`` after it:
    the logging module's lock is held across the fork so a child
    cannot inherit it half-configured.

    An ASYNCHRONOUS EXCEPTION between the two -- a SIGINT arriving
    mid-fork -- leaves that lock HELD FOREVER, and every later fork
    in the process then blocks inside ``_prepareFork``. In a threaded
    caller that is a DEADLOCK: the forking thread holds the engine
    session lock while it waits for a fork that will never return, so
    the whole suite wedges. Measured: the process stuck in
    ``logging._prepareFork`` while the main thread waited for the
    engine lock the forking thread held.

    So the fork is a critical section: SIGINT is deferred across it
    (never swallowed -- it is delivered as soon as the fork returns)
    and the child restores the mask as it leaves the deferred region,
    so it behaves exactly as it would have without the deferral.

    This is the ONE fork primitive in the package: every fork site
    calls it, so the rule is implemented once.
    """
    with _signals.defer_interrupts():
        pid = os.fork()
    return pid


def adopt(pid, owner):
    """Record a just-forked child. Call IMMEDIATELY after os.fork().

    `owner` is a short label used only in the report -- "worker",
    "scanner", "drain" -- so a leak names what leaked.
    """
    if pid and pid > 0:
        _OWNED[pid] = owner
    return pid


def pending():
    """The registered children: {pid: owner}.

    Includes children that have since been reaped (the registry is
    pruned by the reconciliation), so the size is an upper bound on
    the number of forks this process made, not the number of live
    children.
    """
    return dict(_OWNED)


def _child_state(pid):
    """The /proc state letter for a pid, or '' if it is gone."""
    try:
        with open("/proc/%d/stat" % pid) as fh:
            data = fh.read()
        return data[data.rfind(")") + 2]
    except (OSError, IndexError):
        return ""


def reap_orphans(timeout=5.0):
    """Kill and reap every REGISTERED child that is still ours.

    Returns the list of (pid, owner, outcome) for the children this
    call resolved. A child that was already reaped by its owning
    structure is pruned silently; a child that was still ours is
    killed, reaped, and REPORTED -- because an orphan that survived
    a run is a defect, not a detail.

    Call this LAST in a teardown: the owning structures reap their
    own children first, so by the time the registry is swept, any
    pid still registered AND still our child is an orphan.
    """
    resolved = []
    for pid in sorted(_OWNED):
        owner = _OWNED[pid]
        try:
            wpid, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            # Not our child any more: reaped by its owner, or the pid
            # was recycled. Either way there is nothing to do.
            _OWNED.pop(pid, None)
            continue
        except OSError:
            _OWNED.pop(pid, None)
            continue
        if wpid == pid:
            # Already exited and we just reaped it: a zombie nobody
            # else claimed. Report it -- the run left it behind.
            _OWNED.pop(pid, None)
            resolved.append((pid, owner, "reaped (already exited)"))
            continue
        # Still running and unowned: kill it, then reap it with a
        # BOUNDED wait. The wait is bounded because a process in
        # uninterruptible sleep does not die on SIGKILL, and a
        # blocking wait here would hang the whole run.
        try:
            os.kill(pid, 9)
        except OSError:
            pass
        deadline = time.monotonic() + max(0.0, timeout)
        reaped = False
        while True:
            try:
                wpid, _status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                reaped = True
                break
            except OSError:
                break
            if wpid == pid:
                reaped = True
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.005)
        _OWNED.pop(pid, None)
        if reaped:
            resolved.append((pid, owner, "killed and reaped"))
        else:
            resolved.append((pid, owner, "COULD NOT be reaped (state %s)"
                             % (_child_state(pid) or "?",)))
    return resolved


def report_orphans(resolved, stream=None):
    """Write a loud report for the children the registry resolved."""
    if not resolved:
        return
    if stream is None:
        try:
            stream = os.fdopen(2, "w", closefd=False)
        except OSError:
            return
    for pid, owner, outcome in resolved:
        try:
            stream.write(
                "forkrun [WARN]: orphaned child pid %s (%s) %s -- the run "
                "left a child it did not own; it has been resolved\n"
                % (pid, owner, outcome))
            stream.flush()
        except (OSError, ValueError):
            return


def reconcile():
    """Resolve every registered child that is still ours. Never raises.

    Call LAST in a teardown: the owning structures reap their own
    children first, so anything still registered AND still our child
    is an orphan -- a child whose bookkeeping was interrupted between
    the fork and the record that owns it.
    """
    try:
        resolved = reap_orphans()
        report_orphans(resolved)
        return resolved
    except Exception:
        # A teardown must never raise: it runs in a finally, and an
        # exception here would replace the run's own error.
        return []


def reset():
    """Forget every registered child. Test-only."""
    _OWNED.clear()
