"""The cleanroom UDF route must decline when libpython is unresolved.

The launcher preloads libpython BY PATH before it dlopen()s the helper.
Name-based lookup can bind a different library than the interpreter is
running against, so the pre-fix code's "warn and let the launcher guess"
was a correctness hole, not a convenience. The two routes now consult ONE
decision and apply their own pre-ingest consequence:

  * map()    -> return None (fall through to the in-process UDF path)
  * stream() -> raise _CleanroomPreIngestDecline (fall back before a
                single record is yielded)

The integration tests below patch only the *route wiring* (launcher path
and helper presence). The libpython answer comes from the real decision
function with the real `_udf.caller_libpython_arg` mocked, and the
fallback output is checked byte-for-byte.
"""
import os
import sys
import tempfile
import unittest
import warnings
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun  # noqa: E402
import forkrun.run  # noqa: E402
R = sys.modules["forkrun.run"]

UDF_SRC = '''
def up(batch):
    return batch.upper()
'''


class TestLibpythonDecision(unittest.TestCase):
    def test_unresolved_returns_none_and_warns_for_each_route(self):
        for route in ("map", "stream"):
            with mock.patch("forkrun._udf.caller_libpython_arg",
                            return_value=None):
                with self.assertWarns(UserWarning) as caught:
                    got = R._udf_libpython_or_decline(route)
                self.assertIsNone(got)
                message = str(caught.warning)
                self.assertIn(route, message)
                self.assertIn("libpython", message)

    def test_resolved_argv_passes_through_without_warning(self):
        argv = ["--libpython=/opt/cpython/lib/libpython3.14.so.1.0"]
        with mock.patch("forkrun._udf.caller_libpython_arg",
                        return_value=argv):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self.assertEqual(argv, R._udf_libpython_or_decline("map"))
        self.assertEqual([], [w for w in caught
                              if issubclass(w.category, UserWarning)])


class _RouteFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = cls._tmp.name
        with open(os.path.join(cls.root, "libpython_fixture.py"), "w") as fh:
            fh.write(UDF_SRC)
        sys.path.insert(0, cls.root)
        cls.addClassCleanup(sys.path.remove, cls.root)
        cls.src = os.path.join(cls.root, "input.txt")
        with open(cls.src, "wb") as fh:
            for i in range(40):
                fh.write(b"line%06d\n" % i)
        with open(cls.src, "rb") as fh:
            cls.expected = fh.read().upper()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _patches(self, route):
        env = {"FORKRUN_CLEANROOM": route}
        return [
            mock.patch.dict(os.environ, env),
            # The route is made ELIGIBLE (launcher exists, helper exists)
            # so the libpython decision is the thing that declines it.
            mock.patch.object(R, "_cleanroom_launcher_path",
                              return_value="/bin/true"),
            mock.patch.object(R, "_udf_helper_path",
                              return_value="/tmp/fake/_fr_udf.so"),
            mock.patch("forkrun._udf.caller_libpython_arg",
                       return_value=None),
        ]


class TestMapDeclinesToInProcess(_RouteFixture):
    def test_map_falls_back_and_returns_byte_exact_output(self):
        patches = self._patches("map-udf")
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with self.assertWarns(UserWarning) as caught:
            out = forkrun.map("libpython_fixture:up", self.src,
                              mode="udf", workers=2, order="index", nodes=1,
                              output="bytes")
        self.assertIn("map UDF route", str(caught.warning))
        self.assertEqual(self.expected, b"".join(bytes(x) for x in out))


class TestStreamDeclinesBeforeYielding(_RouteFixture):
    def test_stream_falls_back_and_returns_complete_output(self):
        patches = self._patches("stream-udf")
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # A regular file is MATERIALIZED by stream(), so it never reaches
        # the streaming cleanroom branch. A pipe is the shape the branch
        # exists for; write it up-front, then let the fallback consume the
        # original descriptor.
        rfd, wfd = os.pipe()
        try:
            os.write(wfd, self.expected)
            os.close(wfd)
            wfd = -1
            with self.assertWarns(UserWarning) as caught:
                chunks = list(forkrun.stream("libpython_fixture:up", rfd,
                                             mode="udf", workers=2, nodes=1))
        finally:
            if wfd >= 0:
                os.close(wfd)
            os.close(rfd)
        self.assertIn("stream UDF route", str(caught.warning))
        joined = b"".join(bytes(x) for x in chunks)
        # order="none" on a streaming source is completion order, so the
        # fallback is judged on completeness, not sequence.
        self.assertEqual(len(self.expected), len(joined))
        self.assertEqual(sorted(self.expected.splitlines()),
                         sorted(joined.splitlines()))


if __name__ == "__main__":
    unittest.main()
