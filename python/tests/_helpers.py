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
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as fh:
            raw = fh.read()
    except OSError:
        return ""
    parts = [p for p in raw.split(b"\0") if p]
    if not parts:
        return ""
    try:
        exe = parts[0].decode("utf-8", "replace")
    except Exception:
        exe = repr(parts[0])
    return " ".join([exe] + [p.decode("utf-8", "replace") for p in parts[1:]])


# PIDs this process has already reported. A child that is still running
# is reported ONCE, by the test that left it alive -- so the failure is
# attributed to the test that CAUSED it, not to whichever test happens
# to run next. Without this, one test's leftover child fails every
# later test in the run, and reaps the evidence of the real culprit.
_REPORTED = set()


def assert_no_zombies(testcase, before=None):
    """Every child this test created is gone, and none is left unreaped.

    Three outcomes, which the previous version conflated into one:

      * no children at all
            -> nothing to check; pass.

      * a child that has EXITED and is still around
            -> a genuine unreaped child. Reaped HERE, by pid, and
            reported. This is the "zombie leak" case.

      * a child that is still RUNNING
            -> a lifecycle leak: the test left a child alive. Also
            reported -- it is NOT a zombie, and it is NOT reaped here,
            because it is still running and reaping it would be wrong.
            The previous version reported this as a "zombie leak",
            which misdescribed it -- and, because the child stayed
            alive, it failed EVERY later test in the run as well.

    The census is by /proc, not waitpid(-1). waitpid(-1) reaps ANY
    child of this process, including one an EARLIER test left behind:
    that both misattributes the failure to whichever test runs next and
    destroys the evidence that the earlier test left the child.

    `before` optionally scopes the check to the children this test
    created. Pass the census taken before the test ran; children that
    were already there are then none of this test's business, and are
    left for the test that created them.
    """
    census = child_census()
    if before is not None:
        census = {p: s for p, s in census.items() if p not in before}

    zombies, live = [], []
    for pid, state in sorted(census.items()):
        if pid in _REPORTED:
            continue
        if state == "Z":
            # A terminated child nobody reaped. Reap it HERE so the
            # process does not accumulate them, and report it.
            try:
                os.waitpid(pid, 0)
            except (ChildProcessError, OSError):
                pass
            zombies.append(pid)
        else:
            live.append((pid, state))
            _REPORTED.add(pid)

    if not zombies and not live:
        return
    parts = []
    if zombies:
        parts.append("unreaped (terminated) child pid(s) %s"
                     % (", ".join("%s[%s]" % (p, _child_cmdline(p))
                                  for p in zombies),))
    if live:
        parts.append("child still RUNNING after the test: %s"
                     % (", ".join("%s(state %s)[%s]"
                                  % (p, s, _child_cmdline(p))
                                  for p, s in live),))
    testcase.fail("child lifecycle leak -- %s" % "; ".join(parts))


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
