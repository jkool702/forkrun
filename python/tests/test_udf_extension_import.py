"""The cleanroom's UDF route must be able to import a C extension module.

THE DEFECT THIS LOCKS DOWN. The launcher used to dlopen the per-minor
UDF helper with ``RTLD_LOCAL`` (``forkrun_cleanroom.c``), so libpython's
symbols never entered the global namespace. Since CPython 3.8 on Unix,
extension modules resolve libpython's symbols (PyFloat_Type and
friends) out of the **global** namespace at load time -- CPython's own
embedding guidance says libpython must be loaded with ``RTLD_GLOBAL``
for exactly this reason. With ``RTLD_LOCAL``, the interpreter the
launcher created could not load ANY extension module:

    ImportError: .../lib-dynload/math.cpython-314-...so:
                 undefined symbol: PyFloat_Type

Two consequences, and the second is the more dangerous one because it
is **silent**:

1. A UDF importing ``math`` / ``re`` / ``numpy`` returned **ZERO records
   and NO exception** -- every batch poisoned, with nothing naming the
   cause in the caller's visible output.
2. ``json`` still imported, but **without its C accelerator**, so
   ``json.loads`` ran 13.19us instead of 2.88us -- **4.6x slower**, with
   no diagnostic of any kind.

**The existing suite could not see either.** Its UDF fixture
(``test_udf_mode.py``) is PURE PYTHON -- ``b.upper()``, ``import sys``
-- and imports no extension at all, so a hundred green UDF tests were
compatible with the route being unable to import ``math``.

MUTATION CHECK. Reverting the launcher's ``RTLD_GLOBAL`` to
``RTLD_LOCAL`` must make ``test_a_udf_can_import_a_c_extension`` and
``test_the_json_c_accelerator_is_loaded`` FAIL. That was verified by
reverting the flag, rebuilding the launcher and re-running this file.

The assertions are DETERMINISTIC, not wall-clock thresholds: the
accelerator check reads ``json.decoder.scanstring.__module__``, which is
``_json`` when the C scanner is in use and ``json.decoder`` when the
pure-Python fallback is -- an exact, non-timing-dependent witness of
the defect.
"""

import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# The extension imports are at MODULE LEVEL on purpose: that is how a
# real UDF is written, and it is the strictest form -- a module-level
# import failure takes down EVERY function in the module, not just the
# one that wanted it.
FIXTURE_SRC = '''
import math
import re

_LINE_RE = re.compile(rb"line(\\d+)")


def ext(b):
    """One output record per input line, each computed with math."""
    out = []
    for line in bytes(b).split(b"\\n"):
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        n = int(m.group(1)) if m else 0
        out.append(b"%d:%0.9f" % (n, math.sqrt(n)))
    return b"\\n".join(out) + b"\\n"


def json_accel(b):
    """Report WHICH json implementation is in use."""
    import json
    return ("%s" % (json.decoder.scanstring.__module__,)).encode()


def json_scalars(b):
    """json must also WORK, not merely import."""
    import json
    return json.dumps({"n": len(bytes(b)), "ok": True}).encode()
'''


def _helper_built():
    from forkrun._udf import helper_path
    return helper_path() is not None


class TestUDFExtensionImport(unittest.TestCase):
    """The route under test is the CLEANROOM's, so this class OWNS its
    precondition: it sets ``FORKRUN_CLEANROOM=1`` itself and puts the
    previous value back.

    Gating on the AMBIENT value instead is what made the pre-existing
    end-to-end UDF suite dead: ``FORKRUN_CLEANROOM`` is process-global,
    another test module changed it, and every later test that checked
    it SKIPPED rather than failing loudly -- in the pass that runs with
    the flag set, too. A test that silently does not run is worse than
    no test, so the value this test needs is set explicitly, and the
    house pattern (test_cleanroom.py) is followed.
    """

    @classmethod
    def setUpClass(cls):
        if not _helper_built():
            raise unittest.SkipTest("UDF helper not built")
        cls._old_env = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        cls.addClassCleanup(cls._restore_env)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = cls._tmp.name
        with open(os.path.join(cls.root, "forkrun_ext_fixture.py"), "w") as fh:
            fh.write(FIXTURE_SRC)
        # The fixture must be importable HERE, because that is how the
        # root set is derived: _udf_dir() scans sys.path for the module
        # file WITHOUT importing it.
        sys.path.insert(0, cls.root)
        cls.addClassCleanup(sys.path.remove, cls.root)
        cls.addClassCleanup(cls._tmp.cleanup)
        src = os.path.join(cls.root, "input.txt")
        with open(src, "w") as fh:
            fh.writelines("line%06d\n" % i for i in range(20))
        cls.src = src
        import forkrun
        cls.forkrun = forkrun

    @staticmethod
    def _restore_env():
        if TestUDFExtensionImport._old_env is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = \
                TestUDFExtensionImport._old_env

    def _map(self, attr, **kw):
        return self.forkrun.map(
            "forkrun_ext_fixture:" + attr, self.src,
            mode="udf", output="bytes", **kw)

    # -- the extension import itself -------------------------------------

    def test_a_udf_can_import_a_c_extension(self):
        """math and re must be importable, and the records must arrive.

        Before the fix this returned ZERO records with no exception:
        every batch was poisoned and the caller's visible output said
        nothing about the cause.
        """
        got = self._map("ext", workers=2, lines=5, order="index")
        self.assertTrue(got, "the UDF produced no records at all")
        lines = b"".join(got).decode().splitlines()
        # `lines=` is the BATCH size, not a truncation of the input, so
        # every input line must come back exactly once.
        with open(self.src) as fh:
            expected = fh.read().splitlines()
        self.assertEqual(len(expected), len(lines),
                         "expected one record per input line, got %r"
                         % (lines,))
        for i, line in enumerate(lines):
            n, root = line.split(":")
            self.assertEqual(str(i), n)
            # The value is computed by math.sqrt in the WORKER, so it
            # witnesses that the extension actually ran.
            self.assertEqual("%.9f" % (i ** 0.5), root)

    def test_no_batch_is_poisoned(self):
        """A silently-poisoned batch is the failure mode to catch."""
        self._map("ext", workers=2, lines=5, order="index")
        stats = self.forkrun.last_run_stats()
        self.assertEqual(0, stats.get("poisoned"),
                         "batches were poisoned: %r" % (stats,))
        self.assertEqual(stats.get("total"), stats.get("completed"))

    def test_the_json_c_accelerator_is_loaded(self):
        """json must run on the C scanner, not the pure-Python fallback.

        This is the assertion that makes the silent 4.6x slowdown
        impossible to reintroduce: with the fallback, the module is
        'json.decoder'; with the accelerator, it is '_json'.
        """
        got = self._map("json_accel", workers=1, lines=2, order="index")
        self.assertTrue(got, "the probe produced no records")
        # The probe runs once per BATCH, so every result carries the
        # same answer; the first one is the witness.
        module = bytes(got[0]).decode().strip()
        self.assertEqual("_json", module,
                         "the cleanroom's UDF ran json on the pure-Python "
                         "fallback (%r); the C accelerator was not loaded"
                         % (module,))

    def test_json_still_works(self):
        got = self._map("json_scalars", workers=1, lines=2, order="index")
        self.assertTrue(got)
        self.assertIn('"ok": true', b"".join(got).decode())

    # -- output semantics are preserved ----------------------------------

    def test_the_cleanroom_and_in_process_results_are_byte_identical(self):
        """The route must not change what the UDF computes.

        The in-process arm runs the same UDF through the documented
        adapter, so the two arms must agree byte for byte.
        """
        # `forkrun.run` is shadowed by a public function of the same name
        # in forkrun/__init__.py, so the MODULE comes from the registry.
        R = sys.modules["forkrun.run"]
        saved = R._udf_helper_path
        try:
            cleanroom = b"".join(self._map("ext", workers=2, lines=5,
                                           order="index"))
            R._udf_helper_path = lambda: None
            inprocess = b"".join(self._map("ext", workers=2, lines=5,
                                           order="index"))
        finally:
            R._udf_helper_path = saved
        self.assertTrue(cleanroom)
        self.assertEqual(inprocess, cleanroom,
                         "the cleanroom and the in-process path disagree")


if __name__ == "__main__":
    unittest.main()
