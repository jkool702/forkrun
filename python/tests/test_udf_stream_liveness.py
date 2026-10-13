"""Liveness and per-invocation observability of the W-EXP-1 fallback.

Two regressions found by MEASURING rather than by reading, both of which
the existing suite did not catch, and both introduced by the round-12
work:

1. **stream() stopped being lazy.** The first implementation primed the
   cleanroom generator with next() so a pre-ingest refusal would surface
   at the decision point. That made stream() block until the first
   record arrived. Measured: a writer sleeping 3s before its first record
   made stream() take 3.00s to RETURN. A live-draining call became a
   blocking one.

2. **The per-invocation warning went silent after the first call.** Once
   an artifact is cached as incompatible, helper_path() returns None, so
   the fallback never probes -- and a warning helper that asked
   helper_path() "which artifact did we reject?" always got "none". The
   first call warned; every later call in the process went quiet, which
   reads as the cleanroom simply being unavailable.

The positive control for (1) asserts on TIMING, which is what makes it a
liveness test rather than an output test.
"""

import os
import sys
import tempfile
import threading
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun  # noqa: E402
from forkrun import _udf  # noqa: E402

# mode="udf" hands the callable BYTES, not a Batch.
_UDF = "def up(b):\n    return b.upper()\n"


@unittest.skipUnless(_udf.helper_path(),
                     "cleanroom UDF helper not built")
class StreamFallbackLiveness(unittest.TestCase):
    def setUp(self):
        _udf.clear_incompatibles()
        self.tmp = tempfile.mkdtemp(prefix="streamlive-")
        with open(os.path.join(self.tmp, "sl.py"), "w") as fh:
            fh.write(_UDF)
        sys.path.insert(0, self.tmp)
        self.addCleanup(sys.path.remove, self.tmp)
        self.addCleanup(_udf.clear_incompatibles)
        self._old_cr = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.addCleanup(self._restore_cr)

    def _restore_cr(self):
        if self._old_cr is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._old_cr

    def test_stream_returns_before_the_first_record_exists(self):
        """stream() must hand back a generator, not block for data.

        The writer deliberately withholds its first record. If stream()
        primed the cleanroom path to detect a refusal, this returns at
        ~3s instead of immediately.
        """
        r, w = os.pipe()

        def _feeder():
            time.sleep(3.0)
            try:
                os.write(w, b"line0\n")
            except OSError:
                pass
            os.close(w)

        t = threading.Thread(target=_feeder, daemon=True)
        t.start()
        try:
            t0 = time.time()
            gen = forkrun.stream("sl:up", r, mode="udf", workers=1,
                                 output="bytes")
            elapsed = time.time() - t0
            self.assertLess(
                elapsed, 1.0,
                "stream() took %.2fs to return; it must return a generator "
                "immediately and drain lazily. Priming the cleanroom path "
                "to detect a refusal turns a live call into a blocking "
                "one." % elapsed)
            # And it must still deliver, once data actually arrives.
            first = next(iter(gen))
            self.assertEqual(first, b"LINE0\n")
        finally:
            t.join(timeout=10)

    def test_warning_once_per_affected_invocation_including_cached(self):
        """A cached mismatch still affects every call, so every call warns.

        The cache stops the probe, not the consequence.
        """
        orig = _udf.caller_version_arg
        _udf.caller_version_arg = lambda: "--caller-version=9.9"
        self.addCleanup(setattr, _udf, "caller_version_arg", orig)

        import io
        import contextlib
        warnings_seen = []
        real_stderr = sys.stderr
        buf = io.StringIO()
        try:
            sys.stderr = buf
            for _ in range(3):
                forkrun.map("sl:up", self.src(), mode="udf", workers=1,
                            on_error="retry", output="bytes")
        finally:
            sys.stderr = real_stderr
        warnings_seen = buf.getvalue().count("cleanroom UDF helper declined")
        self.assertEqual(
            warnings_seen, 3,
            "three affected invocations must produce three warnings; got "
            "%d. The cache exists to skip the PROBE, not to silence the "
            "consequence." % warnings_seen)

    def src(self):
        path = os.path.join(self.tmp, "in.txt")
        with open(path, "wb") as fh:
            fh.write(b"line0\nline1\n")
        return path


if __name__ == "__main__":
    unittest.main()