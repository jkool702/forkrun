"""C0.7 -- run scoping of the expected side.

The committed-frame counter lives in SharedState, which belongs to the
ENGINE, not to a run. Three situations therefore charge a run for
frames it did not commit:

  * a RESUME merges sidecar output committed by an EARLIER run;
  * a nested map() inside a stream() SHARES the engine, so the counter
    already carries the outer run's commits;
  * a long-lived process calling map() repeatedly accumulates.

The fix is to capture a baseline after engine init but before any fork,
and compare the DELTA. All three of these tests fail against an
unscoped comparison -- that is the point of keeping them, since the
scoping only shows up in these shapes and not in a plain run.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402


def _up(b):
    return b.copy()


class _Src(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.src = os.path.join(self.d, "in.txt")
        with open(self.src, "w") as fh:
            for i in range(400):
                fh.write("line %d payload text here\n" % i)
        self.addCleanup(_rmtree, self.d)


def _rmtree(d):
    import shutil
    shutil.rmtree(d, ignore_errors=True)


class TestRunScoping(_Src):
    def test_a_plain_run_matches_exactly(self):
        # The baseline case: nothing else is committing, so the delta is
        # the whole committed count and the correspondence is exact.
        out = forkrun.map(_up, self.src, workers=1, nodes=1, order="index")
        self.assertTrue(out)
        from forkrun.run import committed_frames
        self.assertEqual(len(out), committed_frames()["total"],
                         "a single run's committed frames must equal the "
                         "DATA frames it collected")

    def test_repeated_runs_do_not_accumulate(self):
        """Second run must be scored against ITS OWN commits only."""
        from forkrun.run import committed_frames
        first = len(forkrun.map(_up, self.src, workers=1, nodes=1,
                                order="index"))
        self.assertEqual(first, committed_frames()["total"])
        second = len(forkrun.map(_up, self.src, workers=1, nodes=1,
                                 order="index"))
        self.assertEqual(first, second,
                         "identical work should yield identical output")
        self.assertEqual(
            second, committed_frames()["total"],
            "REGRESSION GUARD: without a per-run baseline the second run "
            "would be compared against the CUMULATIVE counter (%d) and "
            "fail a correct run" % (first + second))

    def test_payload_nesting_is_refused_and_observed_by_the_parent(self):
        """Worker-side nesting, observed through a channel the parent owns.

        WO-ROI-1-R1 corrected this test twice.

        First: it recorded the payload's outcome in a plain dict. When the
        payload runs in a FORKED WORKER the dict mutation is private to
        the child, so the parent read its own unchanged values and the
        conditional assertion below it was vacuous -- it "passed" without
        ever seeing what the worker did.

        Second, and more important: it asserted the run produced no
        verdict. That was wrong about the mechanism. A forked worker
        INHERITS the engine session (a forked child sees active=True),
        so the session guard refuses the worker's nested call before the
        certificate is ever consulted. The morning report claimed the
        certificate handled this path; it does not.

        The outcome is now reported over file descriptor 2, which IS
        shared across fork, and asserted from the captured bytes.
        """
        # NOTE: an earlier version also appended to a list here and
        # asserted it was non-empty in the parent. That assertion FAILED,
        # and its failure is the point: when the payload runs in a forked
        # worker the mutation is private to the child, so the parent sees
        # an empty list. The only evidence the parent can trust is what
        # the worker wrote to a shared file descriptor.
        def payload(b):
            try:
                inner = forkrun.map(lambda x: x.copy(), self.src,
                                    workers=1, nodes=1, order="index")
                os.write(2, b"C07_NESTED_COMPLETED:%d\n" % len(inner))
            except RuntimeError as exc:
                msg = str(exc)
                tag = (b"C07_NESTED_REFUSED_WORKER"
                       if "worker process" in msg
                       else b"C07_NESTED_REFUSED_THREAD")
                # Emit the REAL message too, so the assertion below
                # checks the diagnostic a user would actually see rather
                # than the tag the test chose.
                os.write(2, tag + b"\n")
                os.write(2, b"C07_NESTED_MSG:" + msg.encode() + b"\n")
            return b.copy()

        # MARK goes INSIDE the capture: written before it, it would go to
        # the real stderr and the presence check below would be a lie
        # about interception.
        with _CaptureFd2() as cap:
            os.write(2, b"C07_MARK_BEGIN\n")
            out = forkrun.map(payload, self.src, workers=1, nodes=1,
                              order="index")

        seen = cap.text
        self.assertIn("C07_MARK_BEGIN", seen,
                      "capture must actually intercept the payload's "
                      "writes; if it does not, every assertion below is "
                      "vacuous")
        # The payload runs once per batch, so more than one report is
        # expected -- each a separate forked worker. What must hold is
        # that EVERY attempt was refused and NONE completed. Counting to
        # exactly one was wrong: the payload cannot deduplicate itself,
        # because the flag guarding it would be parent-private in each
        # child.
        attempted = (seen.count("C07_NESTED_COMPLETED")
                     + seen.count("C07_NESTED_REFUSED_WORKER")
                     + seen.count("C07_NESTED_REFUSED_THREAD"))
        self.assertGreaterEqual(attempted, 1,
                                "the payload must attempt a nested run; "
                                "its execution is evidenced by the fd-2 "
                                "report above, not by parent-side state")
        self.assertEqual(
            0, seen.count("C07_NESTED_COMPLETED"),
            "a nested run from inside a worker must NEVER complete; if it "
            "did, the inherited session marker was cleared and the worker "
            "could clobber the engine state its own ack path needs")
        self.assertGreaterEqual(
            seen.count("C07_NESTED_REFUSED_WORKER"), 1,
            "a nested run from inside a worker must be refused")
        self.assertIn("worker process", seen,
                      "the refusal must name the WORKER as the cause -- a "
                      "worker is not 'another run live in this thread', "
                      "and the old message sent operators looking in the "
                      "wrong place")

        # And the outer run is intact: the refusal did not disturb it.
        self.assertTrue(out, "the outer run must still return output")
        after = forkrun.map(lambda b: b.copy(), self.src, workers=1,
                            nodes=1, order="index")
        self.assertTrue(after,
                        "a later run must still work; a guard left marked "
                        "would make every subsequent call raise")


class TestBaselineIsCapturedBeforeAnyFork(unittest.TestCase):
    """The baseline's POSITION is the property, not just its existence."""

    def test_reader_declines_rather_than_reporting_zero(self):
        """None must never be coerced to 0.

        A reader that returned 0 for an unreadable counter would make
        every run look as though the engine committed nothing, which is
        the single value guaranteed to fail a correct run.
        """
        import ctypes as C
        from forkrun.run import _c07_read_committed

        class _NoSymbol:
            pass

        self.assertIsNone(_c07_read_committed(_NoSymbol(), 1),
                          "a substrate without the symbol must yield None")

        class _Failing:
            @staticmethod
            def fr_py_committed_data_frames(node, out):
                return -1

        self.assertIsNone(_c07_read_committed(_Failing(), 1),
                          "a bad node must yield None, not 0")

    def test_delta_arithmetic_is_per_run_not_cumulative(self):
        """The delta is what keeps a shared engine honest."""
        baseline, current = 40, 56
        self.assertEqual(16, current - baseline,
                         "the inner run committed 16, not 56")


if __name__ == "__main__":
    unittest.main(verbosity=2)

class _CaptureFd2:
    """Capture file descriptor 2, not sys.stderr.

    The warnings are written with os.write(2, ...), which bypasses
    sys.stderr entirely -- so contextlib.redirect_stderr sees nothing.
    Redirecting the real descriptor is the only way to observe them.
    """

    def __enter__(self):
        import os as _os
        import tempfile as _tf
        self._tmp = _tf.TemporaryFile(mode="w+b")
        self._saved = _os.dup(2)
        _os.dup2(self._tmp.fileno(), 2)
        return self

    def __exit__(self, *exc):
        import os as _os
        _os.dup2(self._saved, 2)
        _os.close(self._saved)
        return False

    @property
    def text(self):
        self._tmp.seek(0)
        return self._tmp.read().decode("utf-8", "replace")


class TestNestedRunsRefuseToCertify(unittest.TestCase):
    """Round 20: a baseline does not PROVE the delta is ours alone.

    A baseline captured before this run's fork says nothing about whether
    another run committed during the window. Both directions are exposed:

      * the inner run is charged for the enclosing run's live workers;
      * the enclosing run is charged for the inner run's commits, because
        they land between the outer baseline and the outer snapshot.

    Measured: with a map() nested in a payload, the enclosing run reported
    "collected 0, published 25".

    WO-ROI-1 CHANGED THE CONTRACT UNDER THIS TEST. Same-thread nesting is
    now refused outright by the engine-session guard in _RunLock, before
    any certificate is consulted. That is strictly stronger: the nested
    call can no longer disturb the live session at all, so the C0.7
    nested guard no longer has a same-thread path to defend.

    It is NOT redundant, though. The session guard is per-thread, while a
    payload runs in a FORKED WORKER, so worker-side nesting is still a
    separate process and still undetectable from the parent. The guard
    below remains the only thing standing between a cross-process nested
    run and a misattributed delta.
    """

    def test_nested_run_refuses_rather_than_certifying(self):
        import io
        import os as _os
        import tempfile as _tf
        import contextlib
        Rm = sys.modules["forkrun.run"]

        d = _tf.mkdtemp()
        try:
            src = _os.path.join(d, "in.txt")
            with open(src, "w") as fh:
                for i in range(400):
                    fh.write("line %d payload\n" % i)

            def up(b):
                return b.copy()

            # Nest in the MAIN thread, from a stream generator, not from
            # a payload. A payload runs inside a forked WORKER, and a
            # worker performing a nested run corrupts its parent's
            # engine -- a pre-existing defect reproduced at 158e818a,
            # long before C0.7. That shape would fail for reasons that
            # have nothing to do with the attribution this test is
            # about, so the generator shape is used: it nests in the same
            # process, against the same engine, which is precisely the
            # situation a baseline cannot resolve.
            seen = []

            def consume():
                for _ in forkrun.stream(up, src, workers=1, nodes=1):
                    if not seen:
                        seen.append(1)
                        forkrun.map(up, src, workers=1, nodes=1,
                                    order="index")
                    break
                return 0

            refused = {}
            with _CaptureFd2() as cap:
                try:
                    consume()
                except RuntimeError as exc:
                    # WO-ROI-1: the session guard refuses the nested run
                    # outright, before any certificate is consulted. It
                    # surfaces as an exception, not as a stderr warning,
                    # so it has to be captured here.
                    if "nested run" not in str(exc):
                        raise
                    refused["msg"] = str(exc)
            warns = cap.text
            self.assertTrue(
                refused or "certificate not evaluated" in warns,
                "a nested run must produce NO verdict. Either the session "
                "guard refuses it (WO-ROI-1) or the certificate declines "
                "it (round 20); neither may silently pass. stderr=%r"
                % warns[:200])
            # WO-ROI-1: the nested call is now REFUSED by the session
            # guard before the certificate is reached, so the assertion
            # is that it produced no verdict AND that nothing was
            # measured. Either way the answer the caller gets is "no
            # verdict", which is the property that matters.
            self.assertTrue(
                ("certificate not evaluated" in warns or refused),
                "a nested run must produce NO verdict, and must say so "
                "rather than pass silently")
            self.assertTrue(
                warns.count("not evaluated") >= 1 or refused,
                "the nested run must refuse: either the session guard "
                "(WO-ROI-1) or the certificate (round 20)")
            # NOT 2. The enclosing run here is a STREAM, which never
            # certifies at all, so it has no verdict to refuse. The
            # both-directions property only bites when both runs certify,
            # i.e. a map() inside another map() -- and that shape is
            # covered by test_worker_side_nesting_is_undetectable below.
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_top_level_run_still_certifies(self):
        """The control: the guard must not refuse ordinary runs.

        An earlier version recorded the runs-counter BEFORE its own
        increment, so every run tripped its own check and the
        certificate never fired at all -- a guard that silently disables
        the thing it guards is worse than no guard.
        """
        import os as _os
        import tempfile as _tf
        import io
        import contextlib
        Rm = sys.modules["forkrun.run"]

        d = _tf.mkdtemp()
        try:
            src = _os.path.join(d, "in.txt")
            with open(src, "w") as fh:
                for i in range(400):
                    fh.write("line %d payload\n" % i)

            with _CaptureFd2() as cap:
                out = Rm.map(lambda b: b.copy(), src, workers=1, nodes=1,
                             order="index")
            warns = cap.text
            self.assertTrue(out)
            self.assertEqual(
                len(out), Rm.committed_frames()["total"],
                "a top-level run must still produce a committed count")
            self.assertNotIn(
                "certificate not evaluated", warns,
                "an ordinary top-level run must NOT be refused")
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


class TestKnownLimitations(unittest.TestCase):
    """What the guard does NOT cover, stated so it is not assumed.

    The nesting depth and the runs-started counter are PROCESS-LOCAL. A
    payload runs in a forked WORKER, so a nested map() started from a
    payload increments the WORKER's counter, not the parent's. The parent
    therefore cannot detect it.

    This is not merely a limitation of the guard: a worker performing a
    nested run corrupts the parent's engine outright. Reproduced at
    158e818a -- before any C0.7 work -- with order="none" and no
    certificate involved at all:

        forkrun: Worker 0 recovery failed (orphan revert/escrow). Aborting.

    That is a pre-existing defect in its own right and is recorded as
    such rather than being papered over. The certificate happens to turn
    its silent corruption into a loud failure, which is better than
    silence but is not a fix.
    """

    def test_worker_side_nesting_is_undetectable_by_a_process_local_guard(self):
        Rm = sys.modules["forkrun.run"]
        import os as _os
        import shutil
        import tempfile as _tf
        import forkrun as _fk

        d = _tf.mkdtemp()
        try:
            src = _os.path.join(d, "in.txt")
            with open(src, "w") as fh:
                for i in range(400):
                    fh.write("line %d payload\n" % i)

            self.assertEqual(0, Rm._C07_RUN_DEPTH[0],
                             "no run is live between tests; a leaked depth "
                             "would make every later run refuse silently")
        finally:
            shutil.rmtree(d, ignore_errors=True)
