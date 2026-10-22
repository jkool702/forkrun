"""WO-PY-UDF-FALLBACK-1 -- mode="udf" must fall back to the in-process
path whenever the map-udf route is not selected for the call.

THE DEFECT
----------
The in-process fallback fired only when the helper file for this minor
was ABSENT (``_coerce_payload`` consults ``_udf_helper_path()``). When
the helper was PRESENT but the route was not selected for the call --
the default configuration, because the cleanroom is opt-in -- the
ordinary executors were handed an ``_UDFPayload`` they cannot execute,
and the call ended in

    NotImplementedError: v0 supports mode='python' only

A fallback that raises is not a fallback. The documented contract is
the opposite: *"mode='udf' is not an error, and the documented
fallback is the in-process path, which runs the UDF in THIS
interpreter."*

WHY THE EXISTING TEST DID NOT CATCH IT
--------------------------------------
``test_udf_mode.py::test_a_missing_helper_falls_back_and_still_produces_results``
monkeypatches ``_udf_helper_path`` to return ``None`` -- the
helper-ABSENT case -- so it passed identically with and without the
fix. It does not distinguish the desired behaviour from the broken one.

Every test here therefore keeps the helper PRESENT and makes the route
not selected, which is the case that raised.
"""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))
sys.path.insert(0, _HERE)

from _helpers import redirect_fd, restore_fd  # noqa: E402

def _py_raiser(batch):
    """The same failure, expressed in the mode='python' contract."""
    raise ValueError("udf exploded")


UDF_SRC = '''
def up(b):
    return b.upper()

def to_none(b):
    return None

def raiser(b):
    raise ValueError("udf exploded")
'''


def _helper_path():
    from forkrun._udf import helper_path
    return helper_path()


class _UDFFallbackFixture(unittest.TestCase):
    """A UDF module, an input file, and the cleanroom switched OFF.

    FORKRUN_CLEANROOM is process-global and other modules mutate it,
    so it is set and restored around every test rather than assumed.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = cls._tmp.name
        with open(os.path.join(cls.root, "forkrun_udf_fb_fixture.py"), "w") \
                as fh:
            fh.write(UDF_SRC)
        # The fixture must be importable HERE: that is how the root set
        # is derived (_udf_dir scans sys.path for the module file
        # WITHOUT importing it).
        sys.path.insert(0, cls.root)
        cls.addClassCleanup(sys.path.remove, cls.root)
        src = os.path.join(cls.root, "input.txt")
        with open(src, "w") as fh:
            fh.writelines("line%06d\n" % i for i in range(20))
        cls.src = src
        import forkrun
        cls.forkrun = forkrun

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self._old_cleanroom = os.environ.get("FORKRUN_CLEANROOM")
        # "0" disables every route: the map-udf route is then NOT
        # selected for this call, which is the condition under test.
        os.environ["FORKRUN_CLEANROOM"] = "0"
        self.addCleanup(self._restore_cleanroom)

    def _restore_cleanroom(self):
        if self._old_cleanroom is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._old_cleanroom

    def map(self, attr="up", **kw):
        kw.setdefault("output", "bytes")
        kw.setdefault("workers", 1)
        kw.setdefault("lines", 3)
        return self.forkrun.map(
            "forkrun_udf_fb_fixture:" + attr, self.src, mode="udf", **kw)


class TestUDFFallbackCondition(_UDFFallbackFixture):
    """The two conditions that must both land on the in-process path."""

    def setUp(self):
        super().setUp()
        if _helper_path() is None:
            self.skipTest("the per-minor UDF helper is not built; without "
                          "it the helper-absent case is exercised instead "
                          "and this test cannot distinguish the defect")

    def test_the_helper_present_and_the_route_not_selected_falls_back(self):
        """THE DEFECT CASE.

        The helper for this minor EXISTS, and the map-udf route is not
        selected for the call. The call must still work, in-process.
        """
        got = self.map("up")
        self.assertTrue(got, "the in-process fallback produced nothing")
        self.assertTrue(got[0].startswith(b"LINE000000"), got[0][:40])

    def test_the_helper_absent_falls_back_too(self):
        """The other condition: the helper is not built for this minor.

        This is the case the existing test covers; it is repeated here
        so BOTH conditions are pinned by one file.
        """
        import forkrun.run
        R = sys.modules["forkrun.run"]
        saved = R._udf_helper_path
        R._udf_helper_path = lambda: None
        try:
            got = self.map("up")
        finally:
            R._udf_helper_path = saved
        self.assertTrue(got, "the in-process fallback produced nothing")
        self.assertTrue(got[0].startswith(b"LINE000000"), got[0][:40])

    def test_the_helper_present_is_the_default_state_of_this_fixture(self):
        """Guard the guard: the test above must really be the
        helper-PRESENT case, not the helper-absent one by accident."""
        self.assertIsNotNone(_helper_path(),
                             "the helper must be present for this test to "
                             "exercise the defect case")


class TestUDFFallbackOutput(_UDFFallbackFixture):
    """Output, ordering and cardinality on the fallback path."""

    def setUp(self):
        super().setUp()

    def _expected_lines(self):
        with open(self.src) as fh:
            return [l.strip().upper() for l in fh]

    def test_the_output_is_exact_and_not_duplicated(self):
        """Every input line appears exactly once, uppercased.

        A partial or duplicated result is the failure mode a fallback
        is most likely to have (the primary attempt produced some
        output before failing).
        """
        got = self.map("up", lines=3, workers=2)
        joined = b"".join(got).decode().split()
        expected = self._expected_lines()
        self.assertEqual(sorted(expected), sorted(joined),
                         "the fallback output is not the input, exactly "
                         "once each")
        self.assertEqual(len(joined), len(expected),
                         "the fallback duplicated or dropped records")

    def test_ordered_output_is_preserved(self):
        """order="index" must still deliver the lines in input order."""
        got = self.map("up", lines=3, workers=2, order="index")
        joined = b"".join(got).decode().split()
        self.assertEqual(self._expected_lines(), joined,
                         "the fallback did not preserve the requested order")

    def test_a_none_result_is_still_not_an_empty_record(self):
        """The DECISION-02 distinction must survive the fallback."""
        got = self.map("to_none", lines=3, workers=1)
        self.assertEqual([], got, "None must not become an empty record")

    def test_repeated_invocations_work(self):
        """A fallback that works only once is not a fallback.

        This also catches state leaked by the first call (a cached
        decision, a stale payload, an unreleased helper).
        """
        for i in range(3):
            got = self.map("up", lines=3, workers=1)
            self.assertTrue(got, "invocation %d produced nothing" % (i,))
            self.assertTrue(got[0].startswith(b"LINE000000"),
                            "invocation %d produced %r" % (i, got[0][:20]))


class TestUDFFallbackDoesNotSwallowFailures(_UDFFallbackFixture):
    """Conditions that must NOT be turned into a fallback."""

    def test_a_malformed_spec_is_refused(self):
        """An invalid configuration is an error, not a fallback."""
        with self.assertRaises(ValueError):
            self.forkrun.map("not-a-module-spec", self.src, mode="udf",
                             output="bytes", workers=1, lines=2)

    def test_a_callable_is_refused(self):
        """mode='udf' takes a 'module:attribute' string."""
        with self.assertRaises(ValueError):
            self.forkrun.map(lambda b: b.upper(), self.src, mode="udf",
                             output="bytes", workers=1, lines=2)

    def test_a_missing_module_is_an_error_not_an_empty_result(self):
        """A user-code failure must surface, not become a silent empty
        result (the failure mode the adapter's docstring describes)."""
        with self.assertRaises(Exception):
            self.forkrun.map("forkrun_udf_fb_fixture:no_such_attr", self.src,
                             mode="udf", output="bytes", workers=1, lines=2)

    def test_a_raising_udf_behaves_exactly_like_the_in_process_mode(self):
        """The fallback must not change the contract under the user.

        A mode="udf" callable handed a Batch raises AttributeError on
        b.upper(); every batch retries and poisons, and the caller sees
        an empty result with nothing naming the cause. The adapter
        restores the mode="udf" contract (bytes in), and after that the
        fallback must behave EXACTLY like the in-process python mode:
        the same output for the same work, and the same failure
        routing.

        This is the "does not swallow a genuine user-code failure"
        witness: a failure in the payload is routed through on_error
        and is NOT turned into records.
        """
        import forkrun.run
        R = sys.modules["forkrun.run"]
        saved = R._udf_helper_path
        R._udf_helper_path = lambda: None
        try:
            udf_got = self.map("raiser", lines=5, workers=1,
                               on_error="skip")
            py_got = self.forkrun.map(
                _py_raiser, self.src, output="bytes", workers=1, lines=5,
                on_error="skip")
        finally:
            R._udf_helper_path = saved
        self.assertEqual([], udf_got,
                         "a raising UDF produced records -- the failure was "
                         "turned into output")
        self.assertEqual(
            list(py_got), list(udf_got),
            "the fallback does not behave like the in-process mode: a "
            "genuine user-code failure must be routed the same way on "
            "both paths")


class TestEveryInProcessPathFallsBack(_UDFFallbackFixture):
    """THE ARCHITECTURE TEST.

    Every entry point that can carry mode="udf" must reach the
    in-process fallback. This is a BEHAVIOURAL test of the routing,
    not a source scan: it exercises each path and asserts the call
    works. A source scan would only prove the file mentions a helper
    name.

    The paths:
      * map()            -- the UMA in-process executor
      * map() + NUMA     -- the NUMA in-process executor
      * stream()         -- the UMA streaming in-process executor
      * stream() + NUMA  -- the NUMA streaming in-process executor
    """

    def setUp(self):
        super().setUp()
        if _helper_path() is None:
            self.skipTest("the per-minor UDF helper is not built")

    def test_map_uma_falls_back(self):
        got = self.map("up", lines=3, workers=1)
        self.assertTrue(got, "map() did not fall back")

    def test_map_numa_falls_back(self):
        # "@2" forces two LOGICAL nodes on any host (they cycle the
        # online physicals), so this exercises the NUMA path without
        # needing a multi-socket machine.
        got = self.map("up", lines=3, workers=1, nodes="@2")
        self.assertTrue(got, "map() on the NUMA path did not fall back")

    def test_stream_uma_falls_back(self):
        got = list(self.forkrun.stream(
            "forkrun_udf_fb_fixture:up", self.src, mode="udf",
            output="bytes", workers=1, lines=3))
        self.assertTrue(got, "stream() did not fall back")

    def test_stream_numa_falls_back(self):
        got = list(self.forkrun.stream(
            "forkrun_udf_fb_fixture:up", self.src, mode="udf",
            output="bytes", workers=1, lines=3, nodes="@2"))
        self.assertTrue(got, "stream() on the NUMA path did not fall back")


if __name__ == "__main__":
    unittest.main()
