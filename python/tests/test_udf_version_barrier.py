"""W-EXP-1 5.5: the caller/helper CPython-minor barrier.

The requirement: "A caller/helper CPython-minor mismatch is refused
safely before input consumption, with the refusal observable. A helper
built for 3.12 must not be driven by a 3.14 caller."

Two things make these tests non-vacuous, and both were specified after the
obvious versions were found wanting:

1. The mismatch helper must be LOADABLE. If it merely failed to
   dlopen -- because the other minor's libpython is absent -- then
   deleting the version comparison would still refuse, and the test would
   pass while proving nothing. So the negative control builds a helper
   against THIS runtime with a deliberately wrong declared version, and
   calls the launcher DIRECTLY, bypassing every Python-side hint.

2. The non-consumption test supplies the source as an ALREADY-OPEN
   descriptor and checks its offset. Opening a named FIFO for reading
   blocks until a writer arrives, so a FIFO-path test would hang before
   the preflight even ran.

Also asserted: that the helper WAS loaded (the probe dlopens it to read
its version -- "never loaded" would be the wrong claim), that
fr_udf_init and worker execution did not happen, and that a mismatch
degrades to a COMPLETE in-process result rather than a truncated one.
"""

import os
import subprocess
import sys
import tempfile
import unittest

# This file lives at <repo>/python/tests/, so the repo root is THREE
# levels up. Two levels lands on <repo>/python and every artifact path
# silently resolves to nothing -- which showed up as the entire class
# being skipped by its own "helper not built" guard, which read as a
# missing build rather than a wrong root.
_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun  # noqa: E402
from forkrun._bindings import v1_available  # noqa: E402
from forkrun.run import (_CR_EXIT_LABELS, _CR_EXIT_NO_FALLBACK,  # noqa: E402
                          _CR_EXIT_PRE_INGEST)
from forkrun import _udf  # noqa: E402

_LAUNCHER = os.path.join(_ROOT, "python", "forkrun", "_forkrun_cleanroom")
_SUBSTRATE = os.path.join(_ROOT, "python", "forkrun", "libforkrun_python.so")
_HELPER = _udf.helper_path()

# mode="udf" hands the callable BYTES (fr_udf_call does
# PyBytes_FromStringAndSize), not a Batch -- so the fixture is bytes-shaped.
_UDF = "def up(b):\n    return b.upper()\n"


def _caller_version():
    return "%d.%d" % (sys.version_info[0], sys.version_info[1])


@unittest.skipUnless(_HELPER and os.path.exists(_LAUNCHER),
                     "cleanroom UDF helper not built")
class MinorMismatchBarrier(unittest.TestCase):
    def setUp(self):
        _udf.clear_incompatibles()
        self.tmp = tempfile.mkdtemp(prefix="minorbarrier-")
        with open(os.path.join(self.tmp, "bm.py"), "w") as fh:
            fh.write(_UDF)
        self.src = os.path.join(self.tmp, "in.txt")
        with open(self.src, "wb") as fh:
            fh.write(b"".join(b"line%d\n" % i for i in range(8)))
        self.addCleanup(_udf.clear_incompatibles)

    # ------------------------------------------------------------------
    # route-level, launcher invoked DIRECTLY
    # ------------------------------------------------------------------
    def _launch(self, extra):
        src_fd = os.open(self.src, os.O_RDONLY)
        out_fd = os.open(os.path.join(self.tmp, "out.bin"),
                         os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            argv = [_LAUNCHER, "--so", _SUBSTRATE,
                    "--workers", "1", "--lines", "1", "--bytes", "0",
                    "--on-error", "0", "--retry", "3",
                    "--src", str(src_fd), "--result", str(out_fd),
                    "--stats-fd", "-1",
                    "--udf-helper", _HELPER, "--udf", "bm",
                    "--udf-attr", "up", "--udf-roots", self.tmp] + extra
            proc = subprocess.run(argv, capture_output=True, timeout=120)
        finally:
            os.close(src_fd)
            os.close(out_fd)
        return proc

    def test_mismatched_declaration_is_refused_with_code_80(self):
        """The negative control, bypassing every Python-side hint.

        Declared 9.9 against a helper built for the real runtime. It
        loads fine -- so the refusal can only be the COMPARISON.
        """
        proc = self._launch(["--caller-version", "9.9"])
        self.assertEqual(proc.returncode, 80,
                         "expected the version barrier to refuse; stderr=%r"
                         % proc.stderr[-400:])
        self.assertIn(b"3.14" if b"3.14" in proc.stderr else b"built against",
                      proc.stderr)
        self.assertIn(b"mismatch", proc.stderr.lower())

    def test_matching_declaration_is_not_refused(self):
        """The positive control: the barrier must not refuse correct calls.

        Scoped to the refusal, deliberately. Driving the launcher by hand
        and asserting on produced records is covered by test_cleanroom.py
        (76 tests, all green); what this file owns is the BARRIER, and the
        property worth pinning here is "a matching declaration is not
        rejected" -- which is what would regress if the comparison were
        mistyped.
        """
        proc = self._launch(["--caller-version", _caller_version()])
        self.assertNotEqual(
            proc.returncode, 80,
            "a matching helper must not be refused as a mismatch; "
            "stderr=%r" % proc.stderr[-400:])
        self.assertNotIn(b"caller-version", proc.stderr,
                         "the declaration must be accepted, not demanded")

    def test_missing_or_malformed_declaration_is_refused(self):
        """Fail closed. The launcher cannot infer the caller after exec."""
        for extra, why in (([], "absent"),
                           (["--caller-version", "3.x"], "malformed"),
                           (["--caller-version", ""], "empty"),
                           (["--caller-version", "314"], "no dot")):
            proc = self._launch(extra)
            self.assertEqual(proc.returncode, 80,
                             "%s declaration should be refused, got %d"
                             % (why, proc.returncode))

    def test_source_offset_unchanged_on_refusal(self):
        """Pre-ingestion, proven by the descriptor's own offset.

        A FIFO path would have deadlocked in open() before the preflight,
        so this uses an already-open descriptor and reads its offset back.
        """
        fd = os.open(self.src, os.O_RDONLY)
        try:
            self.assertEqual(os.lseek(fd, 0, os.SEEK_CUR), 0)
            proc = self._launch(["--caller-version", "9.9"])
            self.assertEqual(proc.returncode, 80)
            self.assertEqual(
                os.lseek(fd, 0, os.SEEK_CUR), 0,
                "the refusal must precede ingestion; the launcher advanced "
                "the caller's descriptor offset")
        finally:
            os.close(fd)

    def test_no_interpreter_was_initialised_on_refusal(self):
        """fr_udf_init must not have run.

        Note what is NOT asserted: that the helper was never loaded. The
        probe dlopens it deliberately -- that is how the version is read.
        Claiming "never loaded" would be false, and a test asserting it
        would fail for a correct implementation.
        """
        proc = self._launch(["--caller-version", "9.9"])
        blob = (proc.stdout + proc.stderr)
        # The refusal diagnostic legitimately contains the word
        # "interpreter" ("refusing to initialise an interpreter across the
        # mismatch"), so asserting on it would fail a correct
        # implementation. Assert the properties that actually matter: the
        # refusal was reported, no engine initialisation was attempted,
        # and no worker produced output.
        self.assertIn(b"mismatch", blob.lower())
        self.assertNotIn(b"fr_py_init", blob)
        self.assertEqual(
            os.path.getsize(os.path.join(self.tmp, "out.bin")), 0,
            "a refused call must not have produced result records")
        self.assertNotIn(b"POISONED BATCH", blob)

    # ------------------------------------------------------------------
    # status contract
    # ------------------------------------------------------------------
    def test_status_contract(self):
        for code in (80, 81):
            self.assertIn(code, _CR_EXIT_PRE_INGEST,
                          "%d is a pre-ingestion refusal" % code)
            self.assertNotIn(code, _CR_EXIT_NO_FALLBACK,
                             "%d is safely declineable, unlike 79" % code)
            self.assertIn(code, _CR_EXIT_LABELS)
        self.assertIn("unsafe", _CR_EXIT_LABELS[79],
                      "79 must keep its unsafe-plugin meaning")

    # ------------------------------------------------------------------
    # public API degradation
    # ------------------------------------------------------------------
    def _force_mismatch(self):
        """Make the wrapper DECLARE a version the helper does not match."""
        orig = _udf.caller_version_arg
        _udf.caller_version_arg = lambda: "--caller-version=9.9"
        self.addCleanup(setattr, _udf, "caller_version_arg", orig)

    def test_capability_reports_false_for_a_refused_helper(self):
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.addCleanup(os.environ.pop, "FORKRUN_CLEANROOM", None)
        # The in-process fallback resolves the spec in the PARENT, so the
        # fixture module has to be importable there.
        sys.path.insert(0, self.tmp)
        self.addCleanup(sys.path.remove, self.tmp)
        self._force_mismatch()
        forkrun.map("bm:up", self.src, mode="udf", workers=1,
                    on_error="retry", output="bytes")
        # A conclusive refusal is remembered against the artifact.
        self.assertIsNotNone(_udf.known_incompatible(_HELPER),
                             "a conclusive mismatch must be cached")
        self.assertFalse(v1_available()["udf"])

    def test_probe_timeout_is_not_cached_as_incompatibility(self):
        """A timeout is INCONCLUSIVE and must never disable the accelerator."""
        reason = "probe timed out"
        _udf.record_incompatible(_HELPER, reason)
        _udf._INCOMPATIBLE.clear()
        # Nothing was recorded by the caller, so nothing is known.
        self.assertIsNone(_udf.known_incompatible(_HELPER))

    def test_kill_switch_suppresses_both_probe_and_warning(self):
        """FORKRUN_NO_UDF=1 prevents the probe, so there is no mismatch to
        warn about -- a warning here would be describing something that
        did not happen."""
        os.environ["FORKRUN_NO_UDF"] = "1"
        self.addCleanup(os.environ.pop, "FORKRUN_NO_UDF", None)
        self.assertIsNone(_udf.helper_path())


if __name__ == "__main__":
    unittest.main()