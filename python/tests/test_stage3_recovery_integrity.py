"""Batch atomicity across a worker death.

The Stage 3 lifecycle suite proves that a killed worker's descendants are
reaped and that the supervisor spawns a replacement. It does not prove
what happened to the OUTPUT, which is the property that actually matters
to a caller.

The contract being asserted is the one frun.bash implements:

  A batch is ATOMIC. There is no "partial batch output" a caller can
  ever observe. A worker killed mid-batch leaves its partial output in
  the output memfd, where it is rolled back, and the batch is re-run IN
  FULL from its start offset. The two failure policies then differ only
  in what happens to the batch's DATA:

    on_error="retry"  the batch is re-run in full  -> byte-exact output
    on_error="skip"   the batch yields no result   -> exactly that one
                      batch is absent, and the remainder is delivered
                      CONTIGUOUSLY

Both are correct, and both are byte-checkable rather than count-checkable.
A count cannot tell them apart from a partial-write bug: a run that lost
half a batch and delivered half a batch again has plausible totals.

WHY THE FIRST VERSION OF THIS FILE WAS WRONG, since it was a false
alarm worth recording. It asserted byte-exactness under on_error="skip"
and read the resulting loss as silent data loss (filed as "B-01"). It was
not data loss. Skip mode drops the failed batch BY CONTRACT, and the
output was in fact exactly `input[batch_bytes:]` -- a clean, contiguous
remainder with the failed batch removed and its partial output rolled
back. The correct conclusion required knowing the failure policy, which
the test did not state.

That mistake is the reason every case below asserts the EXPECTED OUTPUT
FOR ITS POLICY rather than a single blanket "byte-exact", and why the
worker-death precondition is checked separately: without asserting that
a death actually happened, a wrong-contract assertion reads as an
engine bug.
"""

import os
import signal
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun  # noqa: E402

LINES = 20
BATCH_BYTES = 128
LAUNCHER = os.path.join(_ROOT, "python", "forkrun", "_forkrun_cleanroom")

UPPER = bytes.maketrans(b"abcdefghijklmnopqrstuvwxyz",
                        b"ABCDEFGHIJKLMNOPQRSTUVWXYZ")

# Emits PARTIAL output and THEN dies. The partial bytes are the probe:
# if they survive anywhere in the output, the rollback did not happen and
# a caller can see torn batch output -- the thing this suite exists to
# forbid. A marker file makes the death one-shot, so the reclaimed batch
# completes instead of killing itself again.
DIE_WITH_PARTIAL_OUTPUT = """#!/bin/sh
M="$FR_DIE_MARKER"
if [ ! -f "$M" ]; then
    : > "$M"
    printf '%s'
    kill -9 $$
fi
exec tr a-z A-Z
"""

# Dies without emitting anything first. Used to separate "the batch was
# re-run in full" from "partial output was rolled back": this one has no
# partial output to lose, so any shortfall is an extent problem rather
# than a rollback problem.
DIE_CLEAN = """#!/bin/sh
M="$FR_DIE_MARKER"
if [ ! -f "$M" ]; then
    : > "$M"
    kill -9 $$
fi
exec tr a-z A-Z
"""

PARTIAL = b"PARTIALJUNKTHATWASROLLBACK"


@unittest.skipUnless(os.path.exists(LAUNCHER), "launcher not built")
class TestBatchAtomicityAcrossWorkerDeath(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.src = os.path.join(self._tmp.name, "in.txt")
        with open(self.src, "w") as fh:
            fh.writelines("line%06d payload\n" % i for i in range(LINES))
        self.script = self._script(DIE_WITH_PARTIAL_OUTPUT % PARTIAL.decode())
        self._old_cr = os.environ.get("FORKRUN_CLEANROOM")
        self._old_mk = os.environ.get("FR_DIE_MARKER")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in (("FORKRUN_CLEANROOM", self._old_cr),
                     ("FR_DIE_MARKER", self._old_mk)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _script(self, body):
        path = os.path.join(self._tmp.name, "probe.sh")
        with open(path, "w") as fh:
            fh.write(body)
        os.chmod(path, 0o755)
        return path

    def _marker(self, tag):
        return os.path.join(self._tmp.name, "marker.%s" % tag)

    def _data(self):
        return open(self.src, "rb").read()

    def _run(self, script, workers, on_error, tag):
        os.environ["FR_DIE_MARKER"] = self._marker(tag)
        return [bytes(x) for x in forkrun.map(
            script, self.src, mode="spawn", workers=workers, nodes=1,
            order="index", bytes=BATCH_BYTES, output="bytes",
            orchestrator=True, on_error=on_error) if x is not None]

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
                    os.kill(int(line.split(None, 1)[0]), signal.SIGKILL)
                except (ValueError, ProcessLookupError, PermissionError):
                    pass

    # -- the rollback half ---------------------------------------------

    def test_partial_output_is_rolled_back_under_both_policies(self):
        """The probe emits bytes BEFORE dying. If any survive, a caller
        can observe torn batch output."""
        for on_error in ("retry", "skip"):
            for workers in (1, 2):
                with self.subTest(on_error=on_error, workers=workers):
                    self.addCleanup(self._cleanup_strays)
                    tag = "%s.%d" % (on_error, workers)
                    recs = self._run(self.script, workers, on_error, tag)
                    self.assertTrue(
                        os.path.exists(self._marker(tag)),
                        "the command never died -- the rollback assertions "
                        "would have been vacuous")
                    got = b"".join(recs)
                    self.assertNotIn(
                        PARTIAL, got,
                        "partial output from a killed batch SURVIVED: a "
                        "caller can see torn batch output, which is the one "
                        "thing batch atomicity forbids")

    # -- the re-run-in-full half ---------------------------------------

    def test_retry_re_runs_the_batch_in_full(self):
        """retry must return the batch's data, not merely not lose it."""
        for workers in (1, 2, 4):
            with self.subTest(workers=workers):
                self.addCleanup(self._cleanup_strays)
                recs = self._run(self.script, workers, "retry",
                                 "retry.%d" % workers)
                self.assertTrue(
                    os.path.exists(self._marker("retry.%d" % workers)),
                    "no worker death occurred -- vacuous")
                got = b"".join(recs)
                self.assertEqual(
                    self._data().translate(UPPER), got,
                    "retry did not reproduce the input: the batch was not "
                    "re-run in full (got %d bytes, want %d)"
                    % (len(got), len(self._data())))

    def test_retry_is_byte_exact_with_no_partial_output_to_roll_back(self):
        """Separates the two mechanisms.

        This probe emits NOTHING before dying, so a shortfall here cannot
        be blamed on rollback -- it would be a wrong input extent on the
        redelivered batch, which is a different bug with a different
        fix.
        """
        clean = self._script(DIE_CLEAN)
        for workers in (1, 2):
            with self.subTest(workers=workers):
                self.addCleanup(self._cleanup_strays)
                tag = "clean.%d" % workers
                recs = self._run(clean, workers, "retry", tag)
                self.assertTrue(os.path.exists(self._marker(tag)),
                                "no worker death occurred -- vacuous")
                self.assertEqual(
                    self._data().translate(UPPER), b"".join(recs),
                    "a batch that died having emitted nothing was not "
                    "re-run in full")

    # -- the skip policy ------------------------------------------------

    @staticmethod
    def _skipped_batch_offsets(want, got, batch):
        """Offsets of whole input batches absent from `got`.

        Returns (skipped, consumed_all), or (None, False) if `got` is not
        a batch-aligned contiguous subsequence of `want`.

        `got` must be walkable by taking input batches IN ORDER and
        deciding for each whether it appears in `got` or was dropped.
        That is the shape skip actually produces, and it is far stricter
        than a count: a torn or misaligned remainder fails here even when
        the byte total looks plausible.

        It deliberately does NOT assume how many batches are dropped.
        With one worker that is exactly one. With several, a worker death
        can take more than one batch with it -- measured at 4 workers,
        where 124 of 380 bytes survived, i.e. TWO whole batches absent and
        the ragged final batch delivered intact. An earlier version
        asserted "exactly one batch missing" and failed intermittently,
        about one run in five, purely because which batches the race took
        varies. The window is clamped at the end because the final batch
        is ragged: 380 bytes at 128 per batch leaves a 124-byte tail.
        """
        gi = 0
        skipped = []
        pos = 0
        while pos < len(want):
            win_end = min(pos + batch, len(want))
            window = want[pos:win_end]
            if got[gi:gi + len(window)] == window:
                gi += len(window)
            else:
                skipped.append(pos)
            pos = win_end
        return skipped, gi == len(got)

    def test_skip_drops_only_whole_batches_and_delivers_the_rest(self):
        """skip means "no result", so a failed batch's data is absent BY
        CONTRACT.

        What must hold is that everything still delivered is CONTIGUOUS
        and batch-ALIGNED -- no torn record, no fragment, no reordering.
        Asserting byte-exact output would be a false alarm; asserting a
        count would miss a misaligned remainder.
        """
        for workers in (1, 2, 4):
            with self.subTest(workers=workers):
                self.addCleanup(self._cleanup_strays)
                tag = "skip.%d" % workers
                recs = self._run(self.script, workers, "skip", tag)
                self.assertTrue(os.path.exists(self._marker(tag)),
                                "no worker death occurred -- vacuous")
                want_all = self._data().translate(UPPER)
                got = b"".join(recs)
                skipped, consumed = self._skipped_batch_offsets(
                    want_all, got, BATCH_BYTES)
                self.assertTrue(
                    skipped,
                    "skip dropped nothing, yet the command died -- the "
                    "policy is not being applied")
                self.assertTrue(
                    consumed,
                    "skip output is not a batch-aligned contiguous "
                    "remainder: %d bytes delivered but only %d account for "
                    "whole input batches (a torn or misaligned remainder "
                    "would look like this)"
                    % (len(got), len(want_all) - sum(
                        min(BATCH_BYTES, len(want_all) - o)
                        for o in skipped)))
                self.assertNotIn(PARTIAL, got)

    def test_health_check_no_death_is_byte_exact_under_both_policies(self):
        """Control: with no death, BOTH policies must be byte-exact.

        Without this, a test asserting the skip remainder would also
        pass if skip dropped a batch that never failed.
        """
        # Shebang required: without it the kernel refuses the exec
        # outright, and the run fails as an infra error rather than
        # producing empty output, which reads like a lost-data bug.
        clean = self._script("#!/bin/sh\nexec tr a-z A-Z\n")
        for on_error in ("retry", "skip"):
            for workers in (1, 2):
                with self.subTest(on_error=on_error, workers=workers):
                    self.addCleanup(self._cleanup_strays)
                    tag = "healthy.%s.%d" % (on_error, workers)
                    recs = self._run(clean, workers, on_error, tag)
                    self.assertEqual(
                        self._data().translate(UPPER), b"".join(recs),
                        "a healthy run under on_error=%r lost data" % on_error)


if __name__ == "__main__":
    unittest.main()
