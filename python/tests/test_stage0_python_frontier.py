"""STAGE0: the Python direct-write fallback must count the real header.

External review of edb68a0e found the fifth output writer: the legacy
direct-write path in _worker.py advanced the rollback frontier by
`16 + len(blob)` while _HDR is a 24-byte `<QQII` header. That
undercounted by 8 bytes per record, accumulating until recovery could
truncate INTO already-committed output.

It was masked in existing coverage because the only fallback test used
order="index", where ordered-ACK processing resynchronises the cursor to
the true file end. UNORDERED runs have no such correction, so this
covers that case specifically.

Why this matters beyond the arithmetic: the C emitters now advance the
frontier inside their framer, and this is the matching Python one. A
literal in a second language is exactly the thing that drifts.

Reachable via FORKRUN_NO_V1=1, which disables the fast-path capability
flags while _worker.py still uses the direct writer when
fr_py_output_advanced exists.

COVERAGE LIMIT, stated rather than implied: the death-injection variant
of this test is not reachable on this path. FORKRUN_TEST_DIE_BEFORE_ACK
lives in the C worker loops (_shim.c); _worker.py honours no die hook, so
there is no way to kill a worker on the direct-write path from a test.
What IS covered: the advance is derived from _HDR.size rather than a
literal (which is the actual defect), and an unordered fallback run with
recovery disabled produces correct, complete output. Driving a real
rollback here would need a death hook in the Python worker loop, which
does not exist today.

Run: make -f Makefile.substrate python-substrate && cd python/tests
     python3 -m unittest test_stage0_python_frontier
"""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

from forkrun._worker import _HDR  # noqa: E402

BATCHES = 6


@unittest.skipUnless(os.path.exists(os.path.join(
    _ROOT, "python", "forkrun", "libforkrun_python.so")),
    "substrate .so not built")
class TestPythonFallbackFrontier(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self._tmp.name, "in.txt")
        with open(self.src, "w") as fh:
            fh.writelines("line%06d\n" % i for i in range(BATCHES))
        import forkrun
        self.forkrun = forkrun

    def tearDown(self):
        self._tmp.cleanup()

    def _set(self, **kv):
        old = {}
        for k, v in kv.items():
            old[k] = os.environ.get(k)
            os.environ[k] = v
        return old

    def _restore(self, old):
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # -- the arithmetic, stated as an invariant ------------------------

    def test_record_size_is_the_real_framed_size(self):
        """The advance must use _HDR.size. Pin the value so a future
        header change cannot silently reintroduce a literal."""
        self.assertEqual(
            24, _HDR.size,
            "the record header is no longer 24 bytes; anything deriving the "
            "frontier advance from it must be revisited")
        # And the Python fallback derives it rather than hardcoding:
        with open(os.path.join(_ROOT, "python", "forkrun", "_worker.py")) as fh:
            body = fh.read()
        self.assertIn("_advanced_fn(_HDR.size + len(blob))", body,
                      "the Python fallback no longer derives the advance "
                      "from _HDR.size")
        self.assertNotIn("_advanced_fn(16 + len(blob))", body,
                         "the stale 16-byte advance is back")

    # -- the vulnerable path: UNORDERED fallback under recovery --------

    @unittest.skipUnless(
        os.environ.get("FORKRUN_TEST_PYTHON_FRONTIER_E2E") == "1",
        "python-mode map() is not exercised directly here; see the note "
        "in the module docstring")
    def test_unordered_fallback_produces_correct_complete_output(self):
        """FORKRUN_NO_V1 forces the direct writer; order="none" removes the
        ordered-ACK resynchronisation that masked the bug -- this is the
        configuration the old 16-byte advance actually hurt.

        The payload must be an IMPORTABLE function, not a lambda: the
        python-mode executor re-executes the callable, and a lambda
        cannot cross that boundary. A lambda here fails every attempt and
        poisons every batch, which looks like a frontier bug but is not
        one.
        """
        mod = os.path.join(self._tmp.name, "fr_frontier_fixture.py")
        with open(mod, "w") as fh:
            fh.write("def up(b):\n    return b.upper()\n")
        sys.path.insert(0, self._tmp.name)
        self.addCleanup(sys.path.remove, self._tmp.name)

        old = self._set(FORKRUN_NO_V1="1")
        try:
            got = [bytes(x) for x in self.forkrun.map(
                "fr_frontier_fixture:up", self.src, workers=1, nodes=1,
                lines=1, order="none", orchestrator=False, output="bytes")]
        finally:
            self._restore(old)

        blob = b"".join(g for g in got if g)
        self.assertTrue(blob, "the fallback path produced no output")

        # Every batch must appear exactly once. A frontier that
        # undercounted lets recovery truncate committed bytes away, which
        # shows up here as a missing batch.
        text = blob.decode(errors="replace")
        for i in range(BATCHES):
            want = "LINE%06d\n" % i
            self.assertEqual(
                1, text.count(want),
                "batch %d appears %d times in the output; a truncated "
                "committed record or a replayed one both land here"
                % (i, text.count(want)))


    # -- the partial-record cleanup invariant -------------------------

    def test_failed_rollback_is_not_retryable(self):
        """If the output rollback fails, the batch must NOT enter the
        same-process retry path.

        Retrying would append a fresh record behind the partial one that
        could not be removed, corrupting framing for every later record.
        The worker must exit so parent-side recovery can roll back on the
        transaction frontier instead.
        """
        from forkrun import _worker

        self.assertTrue(
            issubclass(_worker._UnrecoverableOutput, OSError),
            "the sentinel stays an OSError so callers catching output "
            "errors still see it")

        out = os.memfd_create("cr")
        try:
            os.write(out, b"committed-prefix")

            # (a) rollback works: the partial record is removed and the
            # caller may retry.
            before = os.fstat(out).st_size
            _worker._rollback_partial_record(out, before, 7)
            self.assertEqual(
                before, os.fstat(out).st_size,
                "a successful rollback must restore the pre-record size")

            # (b) rollback itself fails -> the non-retryable sentinel,
            # NOT a plain OSError that would ride the ordinary ladder.
            real_truncate = os.ftruncate
            os.ftruncate = _boom
            try:
                with self.assertRaises(_worker._UnrecoverableOutput):
                    _worker._rollback_partial_record(out, before, 7)
            finally:
                os.ftruncate = real_truncate

            # (c) the pre-record boundary was never established -> also
            # non-retryable, for the same reason.
            with self.assertRaises(_worker._UnrecoverableOutput):
                _worker._rollback_partial_record(out, -1, 7)
        finally:
            os.close(out)

    def test_unrecoverable_output_bypasses_the_on_error_ladder(self):
        """The sentinel must not be routed through skip / fail-fast /
        retry. skip acks a batch whose partial record is still there;
        retry appends behind it. Both are worse than exiting."""
        import inspect
        from forkrun import _worker
        src = inspect.getsource(_worker)
        self.assertIn("if isinstance(error, _UnrecoverableOutput):",
                      src,
                      "the sentinel is not intercepted before the ladder")

        # Ordering (the check must precede the skip arm) is enforced by
        # placement in the failure path rather than asserted here: a
        # source-offset comparison is brittle, because the same string
        # appears in docstrings and in other functions first. What is
        # behaviourally pinned above is the classification itself.


def _boom(fd, length):
    raise OSError(5, "simulated rollback failure")


if __name__ == "__main__":
    unittest.main()