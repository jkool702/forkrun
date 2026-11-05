"""Public-API proof that mode='spawn' actually reaches the launcher.

The review's blocking finding was that `_cleanroom_eligible()` admitted
spawn while `map()` and `stream()` still gated on
`raw_mode in ("plugin", "udf")`. So spawn fell through to the ordinary
in-process executor, and with FORKRUN_CLEANROOM=1 the decline warning
interpolated an unassigned `_why` -- an UnboundLocalError instead of a
clean decline.

A predicate-level test cannot catch that: the predicate WAS correct and
the dispatch was not. These run the real public API and check the RESULT,
plus the observable that distinguishes launcher from in-process.

Run: make -f Makefile.substrate python-substrate && cd python/tests
     python3 -m unittest test_stage3_public_dispatch
"""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun  # noqa: E402

LINES = 9


class TestSpawnPublicDispatch(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self._tmp.name, "in.txt")
        with open(self.src, "w") as fh:
            fh.writelines("line%06d\n" % i for i in range(LINES))
        self._old = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.addCleanup(self._restore)

    def _restore(self):
        # RESTORE the previous value, do not DELETE the variable.
        #
        # This used to `os.environ.pop("FORKRUN_CLEANROOM", None)`
        # unconditionally, which UNSET it for every test that ran
        # afterwards -- and every later test that gates on the variable
        # then SKIPPED instead of running. The whole cleanroom-gated UDF
        # suite (test_udf_mode's end-to-end class and
        # test_udf_extension_import) was therefore dead in the gate,
        # including the pass that runs with FORKRUN_CLEANROOM=1.
        #
        # The `self._old = {}` above was the intended save and was
        # never populated; the house pattern (test_cleanroom.py) saves
        # the old value and puts it back.
        if self._old is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._old

    def _joined(self, out):
        return b"".join(bytes(x) for x in out if x is not None)

    def test_map_spawn_routes_through_the_launcher(self):
        """cat through the public API with cleanroom explicitly on.

        Checks the joined bytes, not a record count: batch grouping
        varies, so a count would assert an implementation detail.
        """
        out = list(forkrun.map("cat", self.src, mode="spawn", workers=2,
                               nodes=1, bytes=32768, output="bytes"))
        got = self._joined(out)
        want = open(self.src, "rb").read()
        self.assertEqual(want, got,
                         "spawn through the public API did not reproduce "
                         "the input byte-for-byte (%d vs %d bytes)"
                         % (len(got), len(want)))

    def test_map_spawn_preserves_argument_boundaries(self):
        """Arguments must survive as distinct argv elements.

        `tr a-z A-Z` collapses its argument into 'a-z'/'A-Z' if anything
        re-splits or joins them, which changes the command's meaning.
        """
        out = list(forkrun.map("tr a-z A-Z", self.src, mode="spawn",
                               workers=1, nodes=1, bytes=32768,
                               output="bytes"))
        got = self._joined(out)
        self.assertEqual(open(self.src, "rb").read().replace(b"line", b"LINE"),
                         got,
                         "argv boundaries were not preserved: %r" % got[:60])

    def test_spawn_error_goes_through_on_error_not_a_crash(self):
        """A nonexistent command must be handled by the on_error policy
        (SKIPPED records, run completes) -- not surface an
        UnboundLocalError from the decline path."""
        out = list(forkrun.map("/nonexistent/forkrun-no-such-binary",
                               self.src, mode="spawn", workers=1, nodes=1,
                               bytes=32768, output="bytes",
                               on_error="skip"))
        self.assertEqual([], [bytes(x) for x in out if x],
                         "a failing command produced data")

    def test_stream_declines_the_cleanroom_but_still_works(self):
        """stream() has no spawn dispatch, so the PREDICATE declines the
        cleanroom. The ordinary in-process executor still handles spawn,
        so the call must succeed via that route -- not raise, and not
        crash on an unassigned reason.

        An earlier version of this test asserted a raise and found none:
        declining an ACCELERATION is not refusing the call. Asserting a
        raise would have demanded that a supported call fail, which is
        the opposite of the contract.
        """
        got = self._joined(forkrun.stream(
            "cat", self.src, streaming=True, mode="spawn", workers=1,
            nodes=1, bytes=32768, output="bytes"))
        self.assertEqual(open(self.src, "rb").read(), got,
                         "stream(mode='spawn') lost data on the in-process "
                         "route")

    def test_predicate_and_dispatch_agree_for_stream_spawn(self):
        """The predicate must decline spawn for stream, and the dispatch
        must therefore not take the launcher route. Asserted on the
        predicate's answer rather than on an incidental exception."""
        from forkrun.run import _cleanroom_eligible
        ok, why = _cleanroom_eligible(self.src, "spawn", 1, "none", False,
                                      True, False, streaming=True)
        self.assertFalse(ok, "stream(mode='spawn') must be declined")
        self.assertIn("spawn", why.lower())


class TestLauncherFailureIsDiagnosable(unittest.TestCase):
    """A launcher failure must say WHY, not just what.

    Both build artifacts -- `libforkrun_python.so` and
    `_forkrun_cleanroom` -- are gitignored, so a substrate that predates
    a change is an ORDINARY state, not an anomaly. When it happens the
    launcher exits 69 from `sym()` with "missing fr_py_worker_spawn_loop"
    on its own stderr, but that used to be inherited straight to the
    caller's terminal: invisible to any test, and invisible to a caller
    reading a captured exception. The Python-side error could only say
    "exit 127 (unknown exit code 127)", which points at the exec, not at
    the rebuild that fixes it.
    """

    def test_launcher_stderr_tail_is_readable(self):
        from forkrun.run import _read_launcher_stderr
        fd = os.memfd_create("t")
        os.write(fd, b"some chatter\n"
                     b"forkrun-cleanroom: missing fr_py_worker_spawn_loop\n")
        self.assertEqual("forkrun-cleanroom: missing fr_py_worker_spawn_loop",
                         _read_launcher_stderr(fd))
        os.close(fd)

    def test_empty_and_absent_stderr_are_not_invented(self):
        from forkrun.run import _read_launcher_stderr
        self.assertEqual("", _read_launcher_stderr(None),
                         "a None fd must not produce a fabricated reason")
        fd = os.memfd_create("t")
        self.assertEqual("", _read_launcher_stderr(fd))
        os.close(fd)

    def test_only_the_tail_is_returned(self):
        """The last line names the cause; earlier lines are interleaved
        child chatter and would bury it."""
        from forkrun.run import _read_launcher_stderr
        fd = os.memfd_create("t")
        os.write(fd, b"x" * 5000 + b"\nTHE ACTUAL CAUSE\n")
        self.assertEqual("THE ACTUAL CAUSE", _read_launcher_stderr(fd))
        os.close(fd)


if __name__ == "__main__":
    unittest.main()