"""Shared helpers for the W-PY4 robustness suites (no tests in here).

Discover pattern is test*.py, so this module is never collected directly.
"""

import os


def redirect_fd(fd, path):
    """Dup2 fd onto a fresh capture file. Returns the saved fd."""
    saved = os.dup(fd)
    tmp = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    os.dup2(tmp, fd)
    os.close(tmp)
    return saved


def restore_fd(fd, saved):
    os.dup2(saved, fd)
    os.close(saved)


def nfd():
    return len(os.listdir("/proc/self/fd"))


def write_lines(path, n, fmt="line %d\n"):
    with open(path, "w") as fh:
        for i in range(n):
            fh.write(fmt % i)


def child_census():
    """Direct children of this process, with their states.

    Every THREAD's children are included: a thread can fork, and
    /proc/self/task/<tid>/children is where the kernel reports them.
    The state is the third field of /proc/<pid>/stat -- 'Z' for a
    zombie, 'R'/'S'/'D'/'T' for a child that is still running.
    """
    out = {}
    try:
        tids = os.listdir("/proc/self/task")
    except OSError:
        return out
    for tid in tids:
        try:
            with open("/proc/self/task/%s/children" % tid) as fh:
                kids = fh.read().split()
        except OSError:
            continue
        for kid in kids:
            try:
                pid = int(kid)
            except ValueError:
                continue
            if pid in out:
                continue
            out[pid] = _child_state(pid)
    return out


def _child_state(pid):
    try:
        with open("/proc/%d/stat" % pid) as fh:
            data = fh.read()
        # the comm field may contain spaces and parentheses; the state
        # is the field after the last ')'
        return data[data.rfind(")") + 2]
    except (OSError, IndexError):
        return "?"


def _child_cmdline(pid):
    """What a child was, for the report.

    A ZOMBIE has an empty cmdline (the kernel clears it), so fall back
    to `comm` -- the executable name -- which survives. That is what
    distinguishes, say, a forked worker from an exec'd launcher.
    """
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as fh:
            raw = fh.read()
    except OSError:
        raw = b""
    parts = [p for p in raw.split(b"\0") if p]
    if parts:
        try:
            return " ".join(p.decode("utf-8", "replace") for p in parts)
        except Exception:
            return repr(parts)
    return _child_comm(pid)


def _child_comm(pid):
    """The executable name of a child, or ''."""
    try:
        with open("/proc/%d/stat" % pid) as fh:
            data = fh.read()
        # comm is the parenthesised field; the state follows it
        i = data.rfind(")")
        return data[data.find("(") + 1:i]
    except (OSError, IndexError):
        return ""


# PIDs this process has already reported are NOT tracked here on
# purpose. An earlier version kept a process-global set and skipped
# them, which made a lifecycle leak appear only ONCE -- and that is not
# the same as making the leak happen only once. Worse, the child was
# never resolved: a child reported as live and reported-as-skipped
# afterwards could still exit and become an unreaped zombie that
# nothing would ever reap. Making a failure appear once is not a fix;
# resolving the condition is.
#
# The fix is ownership plus cleanup: a child is reported by the test
# that CREATED it (per-test baseline), and the helper resolves it --
# terminated, waited for, reaped -- so the process is left clean and the
# next test inherits nothing.


def _reap(pid, grace=1.0):
    """Reap one terminated child, with a BOUNDED wait.

    The wait is bounded because a process in uninterruptible sleep does
    not die on SIGKILL, and a blocking wait here would hang the whole
    test run -- the cleanup is supposed to be bounded, and a cleanup
    that can block is not a cleanup.

    Returns True if the child was reaped, False if it could not be.
    """
    import time
    deadline = time.monotonic() + grace
    while True:
        try:
            wpid, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True          # already gone
        except OSError:
            return False
        if wpid == pid:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def _stop_child(pid, grace=1.0):
    """Terminate a live child and reap it. Bounded throughout.

    SIGTERM, then SIGKILL, then a BOUNDED reap. Returns True when the
    child is gone, False when it could not be reaped -- a child stuck
    in uninterruptible sleep does not die on SIGKILL, and the caller
    must be able to say so rather than claim the child was resolved.
    """
    import signal
    import time
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            wpid, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True
        except OSError:
            return False
        if wpid == pid:
            return True
        time.sleep(0.01)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    # Bounded after SIGKILL too: SIGKILL is not a guarantee.
    return _reap(pid, grace)


def assert_no_zombies(testcase, before=None):
    """Every child this test created is gone, and none is left unreaped.

    OWNERSHIP. `before` is the census of the children that existed
    BEFORE the test ran; only children not in it are this test's to
    answer for. A caller that does not supply one falls back to the
    test case's own baseline (ChildLifecycleMixin records it in setUp).

    WITH NO BASELINE AT ALL, THE HELPER FAILS CLOSED: it reports that
    ownership could not be established, and it does NOT terminate or
    reap anything. Reporting that it does not know who owns a child
    does not make it safe to kill one -- these children may belong to
    another test, and killing another test's child would destroy that
    test's evidence. Every class that uses this helper has the mixin, so
    a missing baseline means a caller that has not opted in.

    THREE OUTCOMES, distinguished:

      * no children at all
            -> nothing to check; pass.

      * a child that has EXITED and is still around
            -> a genuine unreaped child. Reaped HERE, by pid, and
            reported. This is the "zombie leak" case.

      * a child that is still RUNNING
            -> a lifecycle leak: the test left a child alive. Also
            reported -- it is NOT a zombie -- and RESOLVED: terminated,
            waited for, and reaped, so the process is left clean and the
            next test inherits nothing. The pid, state and command line
            are recorded BEFORE the cleanup, so the report stays
            diagnosable.

    The census is by /proc, not waitpid(-1). waitpid(-1) reaps ANY
    child of this process, including one an EARLIER test left behind:
    that both misattributes the failure to whichever test runs next and
    destroys the evidence that the earlier test left the child.

    The assertion is NOT weakened: a live child and an unreaped
    terminated child were failures before and are failures now.
    """
    if before is None:
        before = getattr(testcase, "_child_baseline", None)
    census = child_census()

    if before is None:
        # NO OWNERSHIP. Report it and touch nothing: the children
        # visible here may belong to another test, and killing or
        # reaping one of those would destroy that test's evidence.
        if not census:
            return
        listed = ", ".join("%s(state %s)[%s]" % (p, s, _child_cmdline(p))
                           for p, s in sorted(census.items()))
        testcase.fail(
            "child lifecycle leak -- ownership could NOT be established "
            "(no per-test baseline), so nothing was terminated or reaped; "
            "visible child pid(s): %s" % (listed,))
        return          # the sink may not raise; touch nothing either way

    mine = {p: s for p, s in census.items() if p not in before}
    if not mine:
        return

    zombies, live = [], []
    for pid, state in sorted(mine.items()):
        cmd = _child_cmdline(pid)
        if state == "Z":
            # A terminated child nobody reaped. Reap it HERE so the
            # process does not accumulate them, and report it.
            if not _reap(pid):
                zombies.append((pid, cmd + " (could NOT be reaped)",))
                continue
            zombies.append((pid, cmd))
        else:
            live.append((pid, state, cmd))

    # Resolve the live children. Their identity is already recorded, so
    # the cleanup cannot erase the diagnosis.
    unresolved = []
    for pid, _state, cmd in live:
        if not _stop_child(pid):
            unresolved.append((pid, cmd))

    parts = []
    if zombies:
        parts.append("unreaped (terminated) child pid(s) %s"
                     % (", ".join("%s[%s]" % (p, c) for p, c in zombies),))
    if live:
        parts.append("child still RUNNING after the test: %s"
                     % (", ".join("%s(state %s)[%s]" % (p, s, c)
                                  for p, s, c in live),))
    if unresolved:
        parts.append("child could NOT be terminated/reaped: %s"
                     % (", ".join("%s[%s]" % (p, c) for p, c in unresolved),))
    testcase.fail("child lifecycle leak -- %s" % "; ".join(parts))


class ChildLifecycleMixin:
    """Per-test child ownership.

    Records the child census before the test runs, so the teardown check
    can tell WHICH children this test created. A child that was already
    there is not this test's to complain about, and -- because the
    helper resolves only the children it owns -- is not this test's to
    kill either.

    Without this, the helper can only say "the first test to notice a
    child is the one that failed", which is an assumption about
    ordering, not ownership.

    The baseline is taken by WRAPPING the class's own setUp, rather than
    by defining one here: most of these test classes define their own
    setUp, and a plain mixin setUp would be shadowed by it -- and a
    class that does not call super().setUp() would never record a
    baseline at all. Wrapping at class-creation time takes the census
    before ANY of the class's own setup work, whatever it does.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        original = cls.setUp
        if getattr(original, "_child_lifecycle_wrapped", False):
            return

        def setUp(self, *args, **kw):
            self._child_baseline = child_census()
            return original(self, *args, **kw)

        setUp._child_lifecycle_wrapped = True
        setUp.__doc__ = getattr(original, "__doc__", None)
        cls.setUp = setUp


def lines_of(blobs):
    """All output lines across result blobs, sorted.

    Split-agnostic: batch boundaries are an implementation
    detail (pre-flight timing changes them run to run), so
    cross-run comparisons must use lines (or joined bytes),
    never blob identity or blob sort order.
    """
    out = []
    for b in blobs:
        if b is None:
            continue
        if isinstance(b, str):
            b = b.encode()
        # Results are memoryview views by default since 0.17.0, and this
        # helper needs bytes to split. tobytes() rather than
        # forkrun.materialize() to keep this module import-light.
        if isinstance(b, memoryview):
            b = b.tobytes()
        out.extend(b.splitlines())
    return sorted(out)


def joined_bytes(blobs):
    """Concatenated output bytes (split-agnostic, order-sensitive)."""
    parts = []
    for b in blobs:
        if b is None:
            continue
        if isinstance(b, str):
            b = b.encode()
        parts.append(bytes(b))
    return b"".join(parts)
