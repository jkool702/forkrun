"""Stage 3 lifecycle gates: no orphaned command descendants.

Stage 3's design accepted Option A -- a MANAGED PROCESS GROUP -- and that
contract has a specific limit, so these tests exist to pin both halves of
it:

  IN the group  a descendant of a killed worker MUST be gone by PID.
  OUT of it    a descendant that escapes (setsid) is explicitly NOT
               guaranteed, and that boundary is tested rather than
               implied. Promising universal descendant cleanup would be a
               lie: a subreaper makes an escaped process waitable but does
               not kill it.

The orphan this prevents is the whole reason spawn was the riskiest item:
a SIGKILLed worker whose command had forked a long-lived child leaves
that child running, reparented, and unobservable to the run.

A child that is gone because the LAUNCHER exited is not evidence of the
group signal working -- the OS would reap it either way. So each test
keeps the launcher alive while it checks, which is what makes the
positive case meaningful.
"""

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

from forkrun._worker import _HDR  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

LAUNCHER = os.path.join(_ROOT, "python", "forkrun", "_forkrun_cleanroom")

# Writes its own PID, then idles. A command whose child outlives the
# worker is exactly the case Option A exists to bound.
SPAWNER = "import os,time,sys;open(os.environ['PIDFILE'],'w').write(str(os.getpid()));time.sleep(300)"
# Same, but leaves the process group first.
ESCAPER = ("import os,time,sys;os.setsid();"
           "open(os.environ['PIDFILE'],'w').write(str(os.getpid()));"
           "time.sleep(300)")


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _records(blob):
    recs, off = [], 0
    while off + _HDR.size <= len(blob):
        idx, ln, disp, _r = _HDR.unpack_from(blob, off)
        off += _HDR.size
        recs.append((idx, disp, blob[off:off + ln]))
        off += ln
    return recs


@unittest.skipUnless(os.path.exists(LAUNCHER), "launcher not built")
class TestProcessGroupLifecycle(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = self._tmp.name
        self.src = os.path.join(self.d, "in.txt")
        with open(self.src, "w") as fh:
            fh.writelines("line%06d\n" % i for i in range(3))
        self.pidfile = os.path.join(self.d, "child.pid")
        self.out = os.path.join(self.d, "out.bin")

    def tearDown(self):
        self._tmp.cleanup()

    def _read_pid(self, timeout=8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(self.pidfile):
                try:
                    txt = open(self.pidfile).read().strip()
                except OSError:
                    txt = ""
                if txt:
                    return int(txt)
            time.sleep(0.02)
        return None

    def _argv(self, code):
        return ["--spawn-argv", sys.executable, "--spawn-argv", "-c",
                "--spawn-argv", code]

    def _launch(self, code, extra=(), env_extra=None, timeout=25):
        env = dict(os.environ)
        env["PIDFILE"] = self.pidfile
        env.update(env_extra or {})
        sfd = os.open(self.src, os.O_RDONLY)
        ofd = os.open(self.out, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        argv = ([LAUNCHER, "--so", find_substrate(),
                 "--workers", "1", "--lines", "1", "--bytes", "0",
                 "--on-error", "0", "--retry", "1",
                 "--src", str(sfd), "--result", str(ofd),
                 "--stats-fd", "-1"] + self._argv(code) + list(extra))
        try:
            proc = subprocess.Popen(argv, env=env, pass_fds=(sfd, ofd),
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
        finally:
            os.close(sfd)
            os.close(ofd)
        return proc

    def _find_worker(self, launcher_pid):
        """The launcher forks exactly one worker for workers=1."""
        deadline = time.time() + 10.0
        while time.time() < deadline:
            try:
                kids = open("/proc/%d/task/%d/children"
                            % (launcher_pid, launcher_pid)).read().split()
            except OSError:
                kids = []
            for k in kids:
                pid = int(k)
                # Skip the drain/scanner/fallow helpers: the worker is the
                # one whose process GROUP is its own pid.
                try:
                    if os.getpgid(pid) == pid:
                        return pid
                except OSError:
                    continue
            time.sleep(0.05)
        return None

    def _cleanup(self, pid):
        if pid and _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    # -- the positive case ---------------------------------------------

    def test_child_dies_with_its_worker_generation(self):
        """A descendant in the worker's process group must be gone once
        the launcher has torn that generation down.

        The check happens while the LAUNCHER is still alive, so a passing
        result reflects the group signal rather than ordinary teardown.

        HISTORY, because the first diagnosis was wrong. This test
        originally failed and I concluded the launcher "never notices the
        worker's death" -- that no respawn occurred at all.

        The reviewer showed that was not it. The supervisor's
        waitpid(-1, &st, 0) does observe the death; the group signal was
        a silent NO-OP because the loop cleared pids[wid] = -1 the moment
        it reaped the worker, and kill_worker_group() took the slot
        POINTER and refused to act on a non-positive value. The helper now
        takes the pid by value, which makes that ordering mistake
        impossible rather than merely unlikely.

        Worth keeping because the wrong conclusion was the plausible one:
        "the child survived" reads like "the supervisor never noticed",
        and acting on it would have meant redesigning supervision that was
        working. The distinction between "cleanup failed" and "supervision
        failed" needed the test to observe the right thing.
        """
        proc = self._launch(SPAWNER, extra=["--supervise", "recover"])
        pid = None
        try:
            pid = self._read_pid()
            self.assertIsNotNone(pid,
                                 "the command never reported a pid; the "
                                 "spawn path did not run")
            self.assertTrue(_pid_alive(pid),
                            "child should be alive while the worker runs")

            # SIGKILL the WORKER generation. Its command child must go
            # with it -- this is the orphan Option A exists to prevent.
            worker = self._find_worker(proc.pid)
            self.assertIsNotNone(worker, "could not find the worker process")
            self.assertEqual(
                worker, os.getpgid(worker),
                "the worker must lead its own process group, or a group "
                "signal cannot address it precisely")
            os.kill(worker, signal.SIGKILL)

            deadline = time.time() + 15.0
            gone = False
            while time.time() < deadline:
                if not _pid_alive(pid):
                    gone = True
                    break
                time.sleep(0.05)
            self.assertTrue(
                gone,
                "child pid %d outlived its worker's process group while "
                "the launcher was still running -- Option A guarantees "
                "cleanup for descendants that REMAIN in the group"
                % pid)
        finally:
            self._cleanup(pid)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    # -- the documented boundary ---------------------------------------

    def test_escaping_descendant_is_outside_the_guarantee(self):
        """A descendant that calls setsid() leaves the managed group.

        This test asserts the BOUNDARY, not a kill: the escaped process
        is expected to SURVIVE. Pinning the boundary means a future
        change that starts silently killing escaped processes -- or
        starts losing them without saying so -- shows up here rather
        than in production.
        """
        proc = self._launch(ESCAPER, extra=["--supervise", "recover"])
        pid = None
        try:
            pid = self._read_pid()
            self.assertIsNotNone(pid, "the escaping command never ran")
            time.sleep(0.5)
            self.assertTrue(
                _pid_alive(pid),
                "the setsid'd child should survive worker teardown: it is "
                "OUTSIDE the managed process group and therefore outside "
                "Option A's guarantee. If this now fails, the guarantee "
                "either widened or silently lost the process.")
        finally:
            self._cleanup(pid)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _children(self, pid):
        try:
            return [int(k) for k in
                    open("/proc/%d/task/%d/children" % (pid, pid)).read().split()]
        except OSError:
            return []

    def _worker_pids(self, launcher_pid):
        """Every child that leads its own process group, i.e. workers."""
        out = []
        for k in self._children(launcher_pid):
            try:
                if os.getpgid(k) == k:
                    out.append(k)
            except OSError:
                pass
        return out

    def test_supervisor_respawns_after_a_worker_death(self):
        """Separate from cleanup, and worth proving on its own.

        The reviewer asked for explicit evidence of death OBSERVATION
        and the respawn decision, separate from whether descendants were
        cleaned up. My earlier diagnosis conflated the two and was wrong:
        the supervisor does observe the death (waitpid(-1, &st, 0)) and
        does respawn -- it was the group signal that no-oped.

        So this asserts supervision directly: after a worker is killed, a
        DIFFERENT worker pid appears in the same launcher.
        """
        proc = self._launch(SPAWNER, extra=["--supervise", "recover"])
        first = None
        try:
            pid = self._read_pid()
            self.assertIsNotNone(pid, "the command never ran")
            workers = self._worker_pids(proc.pid)
            self.assertTrue(workers, "no worker found in the launcher")
            first = workers[0]

            os.kill(first, signal.SIGKILL)

            deadline = time.time() + 15.0
            replacement = None
            while time.time() < deadline:
                for w in self._worker_pids(proc.pid):
                    if w != first:
                        replacement = w
                        break
                if replacement:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(
                replacement,
                "no replacement worker appeared: the supervisor did not "
                "observe the death of pid %d" % first)
            self.assertNotEqual(first, replacement)
        finally:
            for w in self._worker_pids(proc.pid):
                self._cleanup(w)
            self._cleanup(pid)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def test_teardown_kills_the_command_descendant(self):
        """At launcher teardown, a still-running command's descendants
        must not outlive the run."""
        proc = self._launch(SPAWNER, extra=["--supervise", "recover"])
        pid = None
        try:
            pid = self._read_pid()
            self.assertIsNotNone(pid, "the command never ran")
            # Tear the run down while the command is mid-sleep.
            for w in self._worker_pids(proc.pid):
                self._cleanup(w)
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            deadline = time.time() + 10.0
            gone = False
            while time.time() < deadline:
                if not _pid_alive(pid):
                    gone = True
                    break
                time.sleep(0.05)
            self.assertTrue(
                gone,
                "command pid %d outlived the launcher" % pid)
        finally:
            self._cleanup(pid)

    def test_infrastructure_failure_is_distinct_from_command_failure(self):
        """A command that cannot be executed must surface as a command
        failure (poison/skip per on_error), not as an infrastructure
        abort of the whole run.

        Without a binary at that path the spawn loop's exec fails; the
        batch should be handled by the ordinary on_error policy rather
        than taking the launcher down.
        """
        # A REAL result descriptor. An earlier version passed --result -2
        # as a placeholder, which made the drain fail immediately with
        # "drain child died" -- so the test was measuring a broken
        # harness and reporting it as a command-failure escalation.
        out = os.path.join(self.d, "infra.bin")
        sfd = os.open(self.src, os.O_RDONLY)
        ofd = os.open(out, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            proc = subprocess.run(
                [LAUNCHER, "--so", find_substrate(),
                 "--workers", "1", "--lines", "1", "--bytes", "0",
                 "--on-error", "1", "--retry", "1",
                 "--src", str(sfd), "--result", str(ofd),
                 "--stats-fd", "-1",
                 "--spawn-argv", "/nonexistent/forkrun-no-such-binary"],
                pass_fds=(sfd, ofd), capture_output=True, timeout=90)
        finally:
            os.close(sfd)
            os.close(ofd)
        # What must hold, precisely:
        #   * it is NOT escalated to an infrastructure abort;
        #   * each skipped batch carries an explicit SKIPPED terminal
        #     record, so a consumer can tell "skipped" from "never ran"
        #     and from "produced no output";
        #   * the run completes under on_error=skip, which is the
        #     DOCUMENTED policy for a failing command.
        #
        # An earlier version asserted a nonzero exit, which was wrong:
        # skip semantics mean the run succeeds with those batches
        # skipped. Asserting otherwise would have demanded that a command
        # failure be reported as a run failure -- the opposite of the
        # on_error contract.
        self.assertEqual(0, proc.returncode,
                         "on_error=skip should let the run complete: %r"
                         % proc.stderr[-300:])
        self.assertNotIn(b"fatal", proc.stderr.lower(),
                         "a command failure was escalated to an "
                         "infrastructure abort: %r" % proc.stderr[-300:])
        expected = sum(1 for _ in open(self.src))
        with open(out, "rb") as fh:
            recs = _records(fh.read())
        self.assertEqual(expected, len(recs),
                         "every batch must reach a terminal outcome")
        for i, disp, _p in recs:
            self.assertEqual(2, disp,
                             "batch %d should be SKIPPED, got disposition %d"
                             % (i, disp))

    # -- positive output -----------------------------------------------

    def test_spawn_through_the_launcher_produces_records(self):
        """Positive output, asserted properly.

        Previously this passed --result -1 (its own comment called that
        invalid) and asserted only `returncode != 64`, so it could pass
        without proving successful execution or ANY output. It now uses a
        real descriptor, requires exit 0, and checks every batch's
        payload.
        """
        out = os.path.join(self.d, "positive.bin")
        sfd = os.open(self.src, os.O_RDONLY)
        ofd = os.open(out, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            proc = subprocess.run(
                [LAUNCHER, "--so", find_substrate(),
                 "--workers", "2", "--lines", "1", "--bytes", "0",
                 "--on-error", "0", "--retry", "2",
                 "--src", str(sfd), "--result", str(ofd),
                 "--stats-fd", "-1",
                 "--spawn-argv", "tr", "--spawn-argv", "a-z",
                 "--spawn-argv", "A-Z"],
                pass_fds=(sfd, ofd), capture_output=True, timeout=90)
        finally:
            os.close(sfd)
            os.close(ofd)

        self.assertEqual(0, proc.returncode,
                         "spawn through the launcher failed: %r"
                         % proc.stderr[-400:])
        with open(out, "rb") as fh:
            recs = _records(fh.read())
        self.assertEqual(3, len(recs),
                         "expected one record per batch, got %r"
                         % ([(i, d) for i, d, _p in recs],))
        by_batch = {i: p for i, _d, p in recs}
        self.assertEqual(sorted(range(3)), sorted(by_batch),
                         "batch-index set is incomplete")
        for i, _d, payload in recs:
            self.assertEqual(("LINE%06d\n" % i).encode(), payload,
                             "batch %d payload wrong" % i)


if __name__ == "__main__":
    unittest.main()
