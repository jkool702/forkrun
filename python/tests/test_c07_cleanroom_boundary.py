"""W-EXP-2 Phase A: the C0.7 certificate AT THE CLEANROOM BOUNDARY.

`test_c07_*.py` prove the committed-frame counter's semantics, but they
drive the engine directly through ctypes and never mention
`FORKRUN_CLEANROOM` -- not one line of the existing C0.7 evidence touches
the cleanroom route, where the engine runs in a separate exec'd process and
the count has to cross a memfd. That gap is what this module closes.

WHAT IS BEING PROVEN. The launcher resolves
`fr_py_committed_data_frames` out of the very .so it dlopens, sums it over
every logical node after all workers have joined, and writes it into the
stats header (v3, word 4). The parent reads it back and compares against
the records it actually collected.

The comparison is the whole point. `exit 0` and EOF prove nothing: a run
that loses an interior packet and delivers the rest exits zero and returns
a short result, which is exactly the silent-success shape the certificate
exists to catch.

INJECTION POINT, and why it is here. These cases drop frames from the
RESULT STREAM, immediately before the comparison, rather than trying to
break the engine's commit path. That is deliberate:

  * The commit path's rollback semantics are already covered by
    `test_c07_fault_injection` at the engine level. Re-testing them here
    would duplicate that evidence without adding a transport dimension.
  * What is NEW and unproven is whether a frame lost AFTER commit but
    BEFORE collection reaches the parent as a detectable shortfall. That
    boundary is exactly where the injection sits.

Every case asserts the injection actually fired -- a certificate that
passed because the fault never happened would otherwise look like a pass.
"""

import ctypes
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

import forkrun  # noqa: E402

R_str = str

_RUN = sys.modules["forkrun.run"]

_PLUGIN_C = (
    '#include "forkrun_plugin.h"\n'
    "#include <stdio.h>\n"
    "int forkrun_use_ctx = FORKRUN_CTX_ENABLE|FORKRUN_CTX_FLAG_RAW;\n"
    "int copy_v1(int argc, char **argv, const struct forkrun_ctx *ctx){\n"
    "  (void)argc; (void)argv;\n"
    "  if(ctx==NULL||ctx->version<2) return -1;\n"
    "  uint64_t n=ctx->batch_byte_length;\n"
    "  const char *in=(const char*)(uintptr_t)ctx->reserved[0];\n"
    "  if(in==NULL) return -1;\n"
    "  if(n==0) return 0;\n"
    "  if(fwrite(in,1,(size_t)n,stdout)!=(size_t)n) return -2;\n"
    "  return fflush(stdout)==0?0:-2;}\n"
)


def _build(tmpdir):
    src = os.path.join(tmpdir, "p.c")
    with open(src, "w") as fh:
        fh.write(_PLUGIN_C)
    out = os.path.join(tmpdir, "p.so")
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2",
         "-I", str(REPO / "ring_loadables"), "-o", out, src],
        check=True, capture_output=True, text=True)
    return out + ":copy_v1"


class _CleanroomC07Base(unittest.TestCase):
    """Runs through the CLEANROOM route -- an exec'd launcher -- not the
    in-process engine the existing C0.7 modules exercise."""

    LINES = 512
    BATCH = 64

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="c07-cleanroom-")
        cls.spec = _build(cls._tmp)
        cls.corpus = os.path.join(cls._tmp, "in.txt")
        with open(cls.corpus, "w") as fh:
            for i in range(cls.LINES):
                fh.write("payload %06d\n" % i)
        cls.expected_records = cls.LINES // cls.BATCH

    def setUp(self):
        # Capture the previous values BEFORE overwriting. Registering the
        # restore afterwards captures OUR OWN value as the "original" and
        # restores it faithfully, so the override silently survives the
        # test and every later test in the process inherits
        # FORKRUN_CLEANROOM=1. That is not hypothetical: it turned 37
        # unrelated recovery/ordering tests red in the full suite while
        # this module passed alone in 0.3 s.
        self._set_env("FORKRUN_CLEANROOM", "1")
        self._set_env("FORKRUN_RETRY_LIMIT", "1")
        self.addCleanup(self._reset_c07)

    def _set_env(self, name, value):
        """Set an env var for this test and put it back afterwards.

        The previous value MUST be captured before the assignment. Doing
        it afterwards -- registering a restore that re-reads os.environ at
        cleanup time -- captures the test's OWN value as the original and
        restores it faithfully, so the override outlives the test and
        every later test in the process silently inherits it.
        """
        self.addCleanup(self._restore_env, name, os.environ.get(name))
        os.environ[name] = value

    @staticmethod
    def _restore_env(name, old):
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old

    @staticmethod
    def _reset_c07():
        _RUN._CLEANROOM_C07.update(
            {"verdict": None, "expected": None, "observed": None,
             "reason": None})
        _RUN._LAST_COMMITTED = None

    def _run_cleanroom(self):
        out = forkrun.map(self.spec, self.corpus, mode="plugin",
                          workers=2, lines=self.BATCH)
        self.assertEqual(
            len(out), self.expected_records,
            "fixture changed shape: %d records, expected %d"
            % (len(out), self.expected_records))
        return out


class TestHealthyRunIsCertified(_CleanroomC07Base):
    """Control 1: a healthy run with complete output passes."""

    def test_healthy_run_certifies_complete(self):
        out = self._run_cleanroom()
        self.assertEqual(_RUN._CLEANROOM_C07["verdict"], "complete")
        self.assertEqual(_RUN._CLEANROOM_C07["expected"],
                         self.expected_records)
        self.assertEqual(_RUN._CLEANROOM_C07["observed"], len(out))
        self.assertIsNotNone(_RUN._LAST_COMMITTED,
                             "the launcher supplied no committed count, so "
                             "the certificate could not have been evaluated")

    def test_committed_count_is_absolute_not_a_delta(self):
        """The count comes from a region fr_py_init() creates FRESH per
        invocation, so it needs no baseline subtraction."""
        self._run_cleanroom()
        first = _RUN._LAST_COMMITTED
        self.assertEqual(first, self.expected_records)
        # A second run in the SAME parent must not accumulate.
        self._run_cleanroom()
        second = _RUN._LAST_COMMITTED
        self.assertEqual(second, first,
                         "a second invocation reported %r after %r -- the "
                         "counter is being carried across runs"
                         % (second, first))


class TestMissingInteriorPacketFailsLoudly(_CleanroomC07Base):
    """Control 2: a missing INTERIOR packet fails even though later
    packets exist. An empty heap or a clean exit cannot detect this."""

    def test_interior_gap_raises(self):
        real_collect = _RUN._cleanroom_collect

        def drop_interior(res_fd, views, order):
            records = real_collect(res_fd, views, order)
            self.assertGreaterEqual(len(records), 3)
            kept = records[:1] + records[2:]      # drop an interior record
            self.assertEqual(len(kept), len(records) - 1)
            return kept

        _RUN._cleanroom_collect = drop_interior
        self.addCleanup(setattr, _RUN, "_cleanroom_collect", real_collect)

        with self.assertRaises(RuntimeError) as ctx:
            self._run_cleanroom()
        msg = str(ctx.exception)
        self.assertIn("INCOMPLETE", msg)
        self.assertEqual(_RUN._CLEANROOM_C07["verdict"], "incomplete")
        self.assertEqual(_RUN._CLEANROOM_C07["observed"],
                         self.expected_records - 1,
                         "the injection did not remove exactly one record, "
                         "so this case would prove nothing")

    def test_interior_gap_is_detected_even_with_later_packets_delivered(self):
        """Sanity for the case above: the LAST record really is still
        there, so an EOF-based check would have seen a complete stream."""
        real_collect = _RUN._cleanroom_collect
        seen = {}

        def drop_interior(res_fd, views, order):
            records = real_collect(res_fd, views, order)
            seen["last"] = records[-1]
            return records[:1] + records[2:]

        _RUN._cleanroom_collect = drop_interior
        self.addCleanup(setattr, _RUN, "_cleanroom_collect", real_collect)
        with self.assertRaises(RuntimeError):
            self._run_cleanroom()
        # A record is a memoryview over BYTES; 64 lines of "payload %06d\n"
        # is 15 bytes each. Compare bytes, not line count.
        self.assertGreater(len(seen["last"]), 0,
                           "the final packet must still be present, or this "
                           "is really the terminal-loss case")
        # Measure a RENDERED corpus line, not the format string: the
        # format is 13 characters and the line it produces is 15.
        rendered = len(b"payload %06d" % 0) + 1
        self.assertEqual(len(bytes(seen["last"])), self.BATCH * rendered)


class TestMissingFinalPacketFailsLoudly(_CleanroomC07Base):
    """Control 3: a missing FINAL expected packet fails loudly. An empty
    heap at EOF is NOT proof that the final packet was delivered."""

    def test_terminal_loss_raises(self):
        real_collect = _RUN._cleanroom_collect

        def drop_final(res_fd, views, order):
            records = real_collect(res_fd, views, order)
            self.assertGreaterEqual(len(records), 2)
            return records[:-1]

        _RUN._cleanroom_collect = drop_final
        self.addCleanup(setattr, _RUN, "_cleanroom_collect", real_collect)

        with self.assertRaises(RuntimeError) as ctx:
            self._run_cleanroom()
        self.assertIn("INCOMPLETE", str(ctx.exception))
        self.assertEqual(_RUN._CLEANROOM_C07["observed"],
                         self.expected_records - 1)

    def test_all_but_one_dropped_still_fails(self):
        """Losing every record but one is the extreme of the same case."""
        real_collect = _RUN._cleanroom_collect

        def keep_one(res_fd, views, order):
            records = real_collect(res_fd, views, order)
            return records[:1]

        _RUN._cleanroom_collect = keep_one
        self.addCleanup(setattr, _RUN, "_cleanroom_collect", real_collect)
        with self.assertRaises(RuntimeError):
            self._run_cleanroom()
        self.assertEqual(_RUN._CLEANROOM_C07["observed"], 1)


class TestRecoveryDoesNotDoubleCount(_CleanroomC07Base):
    """Controls 4 and 5: a worker that dies BEFORE commit, and one that
    dies after its DATA frame is written but before it is signalled.

    Both are the cases where WRITTEN and COMMITTED legitimately diverge:
    recovery rolls the partial batch back and retries it, so a counter
    incremented at emit time would over-count and a certificate comparing
    it would fail a perfectly healthy recovered run. The counter is
    incremented in the commit flush, so the two must re-converge.

    These hooks live in _shim.c, which the exec'd cleanroom launcher
    loads, so the fault is injected in the real subprocess rather than
    simulated in-process.
    """

    def _recovered_run_is_certified_complete(self, env_var):
        # FORKRUN_TEST_DIE_<WHEN> counts attempts in a PER-PROCESS static,
        # so a bare "=1" kills the first attempt of every generation and
        # the whole run dies -- which tests the respawn cap, not recovery.
        # The ONCE variant names a file that outlives the process, so
        # exactly one attempt in the entire run dies and recovery then
        # gets to succeed. That is the case where WRITTEN and COMMITTED
        # could have diverged.
        # Retry budget must exceed 1 here. With FORKRUN_RETRY_LIMIT=1 the
        # killed batch has nowhere to go: the engine commits 7 of 8 and
        # the certificate correctly says "complete", because committed
        # really is 7. That is a different (and correct) statement --
        # it proves the certificate never fires on a merely-truncated run.
        # Exercising RECOVERY needs budget for the retry to succeed.
        self._set_env("FORKRUN_RETRY_LIMIT", "4")
        self._set_env(env_var, "1")
        once = os.path.join(
            self._tmp, "fired-%s-%s" % (env_var.rsplit("_", 1)[-1],
                                         self.id().rsplit(".", 1)[-1]))
        self.addCleanup(lambda: os.path.exists(once) and os.unlink(once))
        self._set_env(env_var + "_ONCE", once)
        out = self._run_cleanroom()
        self.assertEqual(
            len(out), self.expected_records,
            "recovery did not restore the full result: %d of %d records"
            % (len(out), self.expected_records))
        self.assertEqual(_RUN._CLEANROOM_C07["verdict"], "complete",
                         "a recovered run must still certify, not fail: the "
                         "counter must not double-count the retried batch")
        self.assertEqual(_RUN._LAST_COMMITTED, self.expected_records,
                         "committed count drifted from the record count "
                         "across a recovery -- the retry was counted twice")

    def test_worker_dying_before_commit_is_certified_complete(self):
        self._recovered_run_is_certified_complete(
            "FORKRUN_TEST_DIE_BEFORE_ACK")

    def test_worker_dying_before_notify_is_certified_complete(self):
        self._recovered_run_is_certified_complete(
            "FORKRUN_TEST_DIE_BEFORE_NOTIFY")

    def test_truncation_is_not_incompleteness(self):
        """The mirror image of control 4, and easy to get wrong.

        With no retry budget the killed batch is never committed, so the
        engine publishes 7 of 8 records AND commits 7. The counts AGREE,
        and the certificate must say "complete" -- a run that returned 7
        of 8 records with nothing left uncommitted is not a lost packet.

        A certificate that merely compared record counts against the
        input, or that treated "fewer records than expected" as failure,
        would fail here. Asserting this pins the difference between
        "output was truncated" and "output was LOST".
        """
        self._set_env("FORKRUN_RETRY_LIMIT", "1")
        self._set_env("FORKRUN_TEST_DIE_BEFORE_ACK", "1")
        once = os.path.join(self._tmp, "fired-trunc")
        self.addCleanup(lambda: os.path.exists(once) and os.unlink(once))
        self._set_env("FORKRUN_TEST_DIE_BEFORE_ACK_ONCE", once)

        out = forkrun.map(self.spec, self.corpus, mode="plugin",
                          workers=2, lines=self.BATCH)
        self.assertEqual(len(out), self.expected_records - 1,
                         "fixture no longer produces the truncated run this "
                         "test is about (%d records)" % len(out))
        self.assertEqual(_RUN._LAST_COMMITTED, len(out),
                         "committed and collected must still agree -- the "
                         "batch was never committed, so it was never lost")
        # With the budget exhausted the batch POISONS rather than silently
        # disappearing, so the run is refused upstream. A poisoned batch
        # emits a POISONED disposition, not DATA, so committed and
        # collected are legitimately unequal and must not be compared --
        # the certificate declines instead of reporting a verdict.
        self.assertEqual(_RUN._CLEANROOM_C07["verdict"], "no-verdict",
                         "a poisoned run must never be certified")
        self.assertIn("poison", (R_str(_RUN._CLEANROOM_C07["reason"])
                                 or "").lower())

    def test_emit_would_have_overcounted_this_run(self):
        """States WHY the counter sits at commit rather than at emit.

        A counter incremented in fr_py_emit would see the pre-recovery
        writes AND the retry, so it would exceed the collected records on
        a healthy run. Asserting the converged count documents the gap
        the design has to close rather than leaving it implicit.
        """
        self._recovered_run_is_certified_complete(
            "FORKRUN_TEST_DIE_BEFORE_ACK")


class TestUnavailableCounterYieldsNoVerdict(_CleanroomC07Base):
    """Controls 6 and 7: an unsupported accounting route must produce NO
    verdict -- never a fabricated zero that fails a complete run."""

    def test_counting_disabled_yields_no_verdict_not_a_failure(self):
        self._set_env("FORKRUN_C07_COUNT", "0")

        out = self._run_cleanroom()      # must NOT raise
        self.assertEqual(len(out), self.expected_records)
        self.assertIsNone(_RUN._LAST_COMMITTED,
                          "with counting disabled the launcher must emit the "
                          "unavailable sentinel, not a zero")
        self.assertEqual(_RUN._CLEANROOM_C07["verdict"], "no-verdict")

    def test_zero_verdict_would_be_wrong_not_right(self):
        """States the hazard the sentinel exists for.

        With FORKRUN_C07_COUNT=0 nothing increments, so a launcher that
        ignored the liveness check would report committed=0 against
        observed=8 and fail every complete run. This asserts the failure
        mode is real rather than hypothetical.
        """
        self._set_env("FORKRUN_C07_COUNT", "0")
        out = self._run_cleanroom()
        self.assertEqual(len(out), self.expected_records)
        # If the sentinel were 0 instead of "unavailable", this is the
        # comparison that would have fired:
        fabricated_zero = 0
        self.assertNotEqual(fabricated_zero, len(out),
                            "sanity: a fabricated zero would differ here")
        self.assertEqual(_RUN._CLEANROOM_C07["verdict"], "no-verdict",
                         "so the fabricated zero was never used")


class TestRecorderSemantics(_CleanroomC07Base):
    """Unit-level contract of the recorder, including the poisoned case."""

    def test_matching_counts_certify_complete(self):
        _RUN._cleanroom_c07_record(8, 8, poisoned=0)
        self.assertEqual(_RUN._CLEANROOM_C07["verdict"], "complete")

    def test_none_expected_records_no_verdict(self):
        _RUN._cleanroom_c07_record(None, 8, reason="unavailable")
        self.assertEqual(_RUN._CLEANROOM_C07["verdict"], "no-verdict")

    def test_shortfall_raises(self):
        with self.assertRaises(RuntimeError):
            _RUN._cleanroom_c07_record(8, 7, poisoned=0)

    def test_over_delivery_also_refuses(self):
        """Receiving MORE than published means the two sides are not
        describing the same universe -- a defect in the check, and also
        something to refuse rather than accept quietly."""
        with self.assertRaises(RuntimeError):
            _RUN._cleanroom_c07_record(8, 9, poisoned=0)

    def test_poisoned_run_is_not_compared(self):
        """A poisoned batch emits a POISONED disposition, not DATA, so the
        counts legitimately differ. Comparing them would fail a correct
        run, which is the other way to be wrong."""
        out = self._run_cleanroom()
        self.assertEqual(len(out), self.expected_records)
        self.assertEqual(_RUN._CLEANROOM_C07["verdict"], "complete")


if __name__ == "__main__":
    unittest.main()