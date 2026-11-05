"""mode="udf" -- the Python UDF cleanroom path, end to end.

P1-3. These run the REAL path: run.py -> exec'd launcher -> pre-fork
interpreter init -> fr_py_worker_udf_loop. None of it is simulated, and
none of it is stubbed, because the interesting failures in this feature
are integration failures -- a loop that works in isolation and drops
records in the launcher, or an interpreter initialised in the wrong
process.

Skipped when the per-minor helper is not built
(``make -f Makefile.substrate udf-lib``) or the cleanroom is off, since
this mode is opt-in via FORKRUN_CLEANROOM like the plugin path.

Run: python3 -m unittest test_udf_mode
"""

import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

UDF_SRC = '''
def up(b):
    return b.upper()

def to_none(b):
    return None

def empty(b):
    return b""

def first_index_even(b):
    n = int(b.split()[0].replace(b"line", b""))
    return b.upper() if n % 2 == 0 else None

def raiser(b):
    raise ValueError("udf exploded")

def sys_exit(b):
    import sys
    sys.exit(7)
'''


def _helper_built():
    from forkrun._udf import helper_path
    return helper_path() is not None


def _cleanroom_on():
    return os.environ.get("FORKRUN_CLEANROOM") == "1"


class _UDFFixture(unittest.TestCase):
    """Fixture only: a UDF module and an input file. No cleanroom gate.

    Split out from TestUDFModeEndToEnd because the FALLBACK tests are
    about the path where the cleanroom is NOT used -- gating them on
    FORKRUN_CLEANROOM would skip exactly the tests that matter most,
    since the default configuration has the flag off.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = cls._tmp.name
        with open(os.path.join(cls.root, "forkrun_udf_fixture.py"), "w") as fh:
            fh.write(UDF_SRC)
        # The fixture must be importable HERE, because that is how the
        # root set is derived: _udf_dir() scans sys.path for the module
        # file WITHOUT importing it. A user's UDF is importable in their
        # own process, so this mirrors reality rather than contriving it.
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

    def map(self, attr, **kw):
        # Explicit single-node: the cleanroom's UDF envelope is UMA (a
        # multi-node UDF route is not served), and on a fake-NUMA host
        # nodes="auto" would silently decline the cleanroom and run the
        # NUMA in-process path instead. The NUMA fallback tests pass
        # nodes="@2" explicitly, which overrides this default.
        kw.setdefault("nodes", 1)
        return self.forkrun.map(
            "forkrun_udf_fixture:" + attr, self.src,
            mode="udf", output="bytes", **kw)


class TestUDFModeEndToEnd(_UDFFixture):
    """Skipped in setUpClass, not by a module-level decorator.

    FORKRUN_CLEANROOM is process-global and other test modules mutate
    it; a decorator evaluated at IMPORT time can be True while the value
    is False by the time the test RUNS, and the test then fails with a
    confusing NotImplementedError from the in-process path instead of
    skipping.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not _cleanroom_on():
            raise unittest.SkipTest(
                "cleanroom is opt-in via FORKRUN_CLEANROOM=1")
        if not _helper_built():
            raise unittest.SkipTest("UDF helper not built")

    # -- the path works at all ------------------------------------------

    def test_udf_runs_in_the_cleanroom(self):
        got = self.map("up", workers=2, lines=5)
        lines = b"".join(got).decode().splitlines()
        expected = [l.upper() for l in open(self.src).read().splitlines()]
        self.assertTrue(got, "UDF mode produced no records at all")
        self.assertEqual(sorted(expected), sorted(lines))
        self.assertTrue(all(isinstance(x, bytes) for x in got))

    def test_streaming_udf_also_works(self):
        got = list(self.forkrun.stream(
            "forkrun_udf_fixture:up", self.src, mode="udf",
            workers=2, lines=5, nodes=1, streaming=True))
        self.assertTrue(got, "streaming UDF produced no records")

    # -- DECISION-02: None and b"" stay distinct -----------------------

    def test_none_is_not_an_empty_record(self):
        """A UDF returning None emits a NO_RESULT record, not a 0-length
        payload, so map() must NOT surface it as b""."""
        self.assertEqual([], self.map("to_none", workers=1, lines=5))

    def test_empty_bytes_is_a_real_empty_record(self):
        """The counterpart. Together with the test above this is the
        proof that the two are distinguishable end to end -- either
        alone would be satisfied by collapsing them."""
        got = self.map("empty", workers=1, lines=5)
        self.assertTrue(got, "b'' produced no records")
        self.assertTrue(all(len(x) == 0 for x in got))

    def test_a_mixed_run_keeps_only_the_bytes_batches(self):
        """Half the batches return None. The surviving records must be
        exactly the even-indexed ones -- neither all nor none."""
        got = self.map("first_index_even", workers=1, lines=1)
        self.assertTrue(got, "no records survived; None batches were not "
                             "filtered, or the DATA ones were lost")
        self.assertTrue(all(b == b.upper() for b in got))
        self.assertEqual(len(got), 20 // 2)

    # -- failures are batch-level, not worker deaths -------------------

    def test_a_raising_udf_is_handled_not_crashed(self):
        """Q3: an exception is a payload failure routed through
        on_error. The call must return, not hang or kill the parent."""
        got = self.forkrun.map(
            "forkrun_udf_fixture:raiser", self.src, mode="udf",
            output="bytes", workers=1, lines=5, on_error="skip")
        self.assertEqual([], got)

    def test_sys_exit_in_a_udf_does_not_kill_the_worker(self):
        """SystemExit used to terminate the whole helper process,
        converting a recoverable batch error into a worker death."""
        got = self.forkrun.map(
            "forkrun_udf_fixture:sys_exit", self.src, mode="udf",
            output="bytes", workers=1, lines=5, on_error="skip")
        self.assertEqual([], got)


class TestUDFFallbackWithoutHelper(_UDFFixture):
    """The path taken when no per-minor helper is built.

    Deliberately NOT gated on FORKRUN_CLEANROOM: this is the in-process
    path, and the default configuration has the flag OFF. Gating these on
    it would skip exactly the tests that matter.
    """

    def test_a_missing_helper_falls_back_and_still_produces_results(self):
        """The fallback has to actually EXECUTE the UDF.

        For a long time the code claimed a fallback and did not have one:
        _coerce_payload returned mode "udf", but the ordinary executors
        accept only "python" and "splice", so with no helper built -- and
        FORKRUN_CLEANROOM off, which is the default -- the promised
        fallback ended in

            NotImplementedError: v0 supports mode='python' only

        A fallback that raises is not a fallback.
        """
        import forkrun.run
        R = sys.modules["forkrun.run"]
        saved = R._udf_helper_path
        R._udf_helper_path = lambda: None      # "not built for this minor"
        try:
            got = forkrun.map("forkrun_udf_fixture:up", self.src,
                              mode="udf", output="bytes",
                              workers=1, lines=2)
        finally:
            R._udf_helper_path = saved
        self.assertTrue(got, "the in-process fallback produced nothing")
        self.assertTrue(got[0].startswith(b"LINE000000"), got[0][:40])

    def test_the_fallback_adapts_the_differing_udf_contracts(self):
        """mode='udf' and mode='python' do NOT call user code the same way.

        The embedded helper hands the callable one `bytes` object
        (fr_udf_call does PyBytes_FromStringAndSize); the in-process
        executor hands it a `forkrun._batch.Batch` carrying offsets,
        line counts and metadata as well as data.

        So the fallback needs an adapter, or it silently changes the
        contract under the user: a mode='udf' callable handed a Batch
        raises AttributeError on b.upper(), every batch retries and
        poisons, and the caller sees an empty result with nothing naming
        the cause. That is exactly what happened before the adapter.
        """
        import forkrun.run
        R = sys.modules["forkrun.run"]
        saved = R._udf_helper_path
        R._udf_helper_path = lambda: None
        try:
            none = forkrun.map("forkrun_udf_fixture:to_none", self.src,
                               mode="udf", output="bytes",
                               workers=1, lines=2)
            empty = forkrun.map("forkrun_udf_fixture:empty", self.src,
                                mode="udf", output="bytes",
                                workers=1, lines=2)
        finally:
            R._udf_helper_path = saved
        # The DECISION-02 distinction must survive the fallback too, or
        # it holds only on the cleanroom path.
        self.assertEqual([], none, "None must not become an empty record")
        self.assertTrue(empty, "b'' must still produce a record")
        self.assertTrue(all(len(x) == 0 for x in empty))


@unittest.skipUnless(_helper_built(), "UDF helper not built")
class TestUDFSpec(unittest.TestCase):
    """Spec handling and root derivation, without launching anything."""

    def setUp(self):
        from forkrun._udf import UDFError, parse_spec
        self.parse = parse_spec
        self.UDFError = UDFError

    def test_spec_splits_on_the_last_colon(self):
        self.assertEqual(("pkg.mod", "Cls.meth"),
                         self.parse("pkg.mod:Cls.meth"))

    def test_bad_specs_are_refused(self):
        for bad in ("nomodule", "", ":attr", "mod:"):
            with self.subTest(spec=bad):
                with self.assertRaises(self.UDFError):
                    self.parse(bad)

    def test_roots_include_the_udf_directory(self):
        """Without this a UDF outside site-packages is unimportable in
        the worker and every batch poisons -- which is exactly what the
        first end-to-end run did."""
        import sys
        sys.path.insert(0, _ROOT)
        from forkrun._udf import roots_spec
        roots = roots_spec("forkrun")
        self.assertIn(_ROOT, roots)

    def test_roots_are_never_empty(self):
        from forkrun._udf import roots_spec
        self.assertTrue(roots_spec("forkrun").strip())

    def test_missing_helper_is_reported_not_raised(self):
        """The caller treats an unbuilt helper as "cleanroom unavailable"
        and falls back; it must not be an exception."""
        from forkrun._udf import helper_path
        self.assertTrue(helper_path() is None or
                        os.path.exists(helper_path()))


if __name__ == "__main__":
    unittest.main()