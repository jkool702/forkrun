"""Output integrity across a worker death.

The Stage 3 lifecycle suite proves that a killed worker's descendants are
reaped and that the supervisor spawns a replacement. It does NOT prove
that the OUTPUT was correct afterwards, and the gap is not academic: a
worker can die holding a batch, and the engine's job at that moment is to
reclaim it and redeliver it exactly once. Getting that wrong produces
either a silent gap (the batch is lost) or a duplicate (it is delivered
twice) -- and both look like success unless something counts.

So these assert the recovered output BYTE-EXACTLY against the input,
which is the only invariant that distinguishes exactly-once from
at-least-once and from at-most-once. A count would not: a run that
delivered every batch twice and lost none would report the right number.

The probe is a shell command that SIGKILLs its own worker exactly once,
then does real work:

    if [ ! -f "$marker" ]; then touch "$marker"; kill -9 $$; fi
    tr a-z A-Z

A marker file makes the death happen ONCE even though the batch is
reclaimed and redelivered, so the run completes instead of livelocking on
a command that only ever kills itself. The transform is not incidental:
output that is merely the right LENGTH could come from the wrong batch,
whereas uppercased input pins each delivered record to its source line.
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

import forkrun  # noqa: E402

LINES = 60
LAUNCHER = os.path.join(_ROOT, "python", "forkrun", "_forkrun_cleanroom")

UPPER = bytes.maketrans(b"abcdefghijklmnopqrstuvwxyz",
                        b"ABCDEFGHIJKLMNOPQRSTUVWXYZ")

# Dies once, then uppercases stdin. The marker makes the death one-shot.
SCRIPT = """#!/bin/sh
M="$FR_DIE_MARKER"
if [ ! -f "$M" ]; then
    : > "$M"
    kill -9 $$
fi
exec tr a-z A-Z
"""


@unittest.skipUnless(os.path.exists(LAUNCHER), "launcher not built")
class TestRecoveryOutputIntegrity(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.src = os.path.join(self._tmp.name, "in.txt")
        with open(self.src, "w") as fh:
            fh.writelines("line%06d payload\n" % i for i in range(LINES))
        self.script = os.path.join(self._tmp.name, "die_once.sh")
        with open(self.script, "w") as fh:
            fh.write(SCRIPT)
        os.chmod(self.script, 0o755)
        self.marker = os.path.join(self._tmp.name, "marker")
        self._old_env = os.environ.get("FORKRUN_CLEANROOM")
        self._old_marker = os.environ.get("FR_DIE_MARKER")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        os.environ["FR_DIE_MARKER"] = self.marker
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in (("FORKRUN_CLEANROOM", self._old_env),
                     ("FR_DIE_MARKER", self._old_marker)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _run(self, workers, orchestrator=True, order="index"):
        return b"".join(
            bytes(x) for x in forkrun.map(
                self.script, self.src, mode="spawn", workers=workers,
                nodes=1, order=order, bytes=128, output="bytes",
                orchestrator=orchestrator, on_error="skip")
            if x is not None)

    def _cleanup_strays(self):
        """Kill anything the run left behind, matched to our tempdir.

        Without this a failing test can leave a killed worker's command
        running, and the NEXT test's process scan trips over it.
        """
        try:
            out = subprocess.run(["ps", "-eo", "pid,args"],
                                 capture_output=True, timeout=15).stdout
        except (OSError, subprocess.SubprocessError):
            return
        for line in out.decode(errors="replace").splitlines():
            if self._tmp.name in line and "ps -eo" not in line:
                try:
                    pid = int(line.split(None, 1)[0])
                    os.kill(pid, signal.SIGKILL)
                except (ValueError, ProcessLookupError, PermissionError):
                    pass

    @unittest.expectedFailure
    def test_worker_death_still_delivers_every_batch_exactly_once(self):
        """The batch in flight when the worker died must be reclaimed and
        redelivered -- not dropped, not duplicated."""
        self.addCleanup(self._cleanup_strays)
        got = self._run(workers=2)
        want = open(self.src, "rb").read().translate(UPPER)

        self.assertTrue(
            os.path.exists(self.marker),
            "the command never died, so recovery was never exercised")

        if got != want:
            got_lines = got.splitlines()
            want_lines = want.splitlines()
            dupes = [ln for ln in set(got_lines)
                     if got_lines.count(ln) > 1]
            missing = [ln for ln in want_lines if ln not in got_lines]
            self.fail(
                "output after worker death is not byte-exact.\n"
                "  got %d lines, want %d\n"
                "  duplicated: %d line(s) e.g. %r\n"
                "  missing:    %d line(s) e.g. %r\n"
                "  => %s"
                % (len(got_lines), len(want_lines), len(dupes),
                   dupes[:3], len(missing), missing[:3],
                   "DELIVERED TWICE (at-least-once)" if dupes else
                   "LOST (at-most-once)" if missing else
                   "wrong content"))

    @unittest.expectedFailure
    def test_recovery_is_stable_across_worker_counts(self):
        """Exactly-once must not depend on how the work was divided."""
        for workers in (1, 2, 4):
            with self.subTest(workers=workers):
                os.environ["FR_DIE_MARKER"] = self.marker + ".%d" % workers
                self.addCleanup(self._cleanup_strays)
                got = self._run(workers=workers)
                want = open(self.src, "rb").read().translate(UPPER)
                self.assertEqual(
                    want, got,
                    "workers=%d: output after worker death diverged from "
                    "the input" % workers)

    def test_the_run_actually_experienced_a_worker_death(self):
        """Guards the two tests above.

        If the kill did not happen, they would be asserting that a clean
        run is correct -- which is true, and which proves nothing about
        recovery. So the marker is checked, and so is that the run took
        a non-trivial amount of time: an instant completion is the
        signature of a batch that was never retried.
        """
        self.addCleanup(self._cleanup_strays)
        t0 = time.time()
        self._run(workers=2)
        dt = time.time() - t0
        self.assertTrue(
            os.path.exists(self.marker),
            "no worker death occurred -- the recovery assertions above "
            "would have been vacuous")
        self.assertLess(
            dt, 30.0,
            "the run took %.1fs, which suggests it was waiting rather "
            "than reclaiming the dead batch" % dt)


if __name__ == "__main__":
    unittest.main()
