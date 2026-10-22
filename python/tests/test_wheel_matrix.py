"""The per-minor wheel build orchestration must fail closed.

DECISION-01 chose Option A: one wheel per supported CPython minor,
each carrying the UDF helper built for THAT minor. The helper LINKS
libpython, so the minor is a hard constraint the wheel's tag has to
state -- and a wheel whose tag does not match its artifact is a lie
that pip cannot detect but the loader can.

These tests exercise the ORCHESTRATION's behaviour, not the existence
of a shell script: the functions under test are the ones the build
actually calls (`tools/wheel_matrix.py`), driven against a fake
filesystem so they run in milliseconds.

THE CASES THAT MATTER
---------------------
* a missing interpreter is REPORTED, never SUBSTITUTED -- a wheel
  tagged cp310 that was compiled by 3.12 is a lie;
* a stale helper from a previous minor cannot end up in the next
  wheel;
* a wheel whose tag does not match the helper it carries is rejected;
* a partial matrix is never reported as a complete release build.
"""

import os
import shutil
import sys
import tempfile
import unittest
import zipfile

_ROOT = os.path.normpath(os.path.join(os.path.dirname(
    os.path.abspath(__file__)), os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "tools"))

import wheel_matrix  # noqa: E402


def _make_wheel(path, python_tag, abi_tag, helpers=(), extra=()):
    """A wheel-shaped zip with the given tags and helper names."""
    parts = ["forkrun", "3.6.1", python_tag, abi_tag, "manylinux_2_28_x86_64"]
    name = "-".join(parts) + ".whl"
    full = os.path.join(path, name)
    with zipfile.ZipFile(full, "w") as zf:
        zf.writestr("forkrun/__init__.py", "# forkrun\n")
        zf.writestr("forkrun/py.typed", "")
        for h in helpers:
            zf.writestr("forkrun/" + h, "not a real .so")
        for e in extra:
            zf.writestr(e, "x")
    return full


class TestSupportedMinors(unittest.TestCase):
    """There must be ONE definition of "supported"."""

    def test_the_list_is_the_decision_ones(self):
        """DECISION-01 section 3: "ship wheels tagged cp310, cp311, ...
        cp315" -- six minors, 3.10 through 3.15."""
        self.assertEqual(("3.10", "3.11", "3.12", "3.13", "3.14", "3.15"),
                         wheel_matrix.SUPPORTED_MINORS)

    def test_the_interpreter_matrix_script_reads_the_same_list(self):
        """tools/matrix_c05.sh used to carry its OWN copy of the list.

        Two copies of "supported" is exactly how they drift, so the
        script now reads the canonical one. This test fails if it goes
        back to a private list.
        """
        with open(os.path.join(_ROOT, "tools", "matrix_c05.sh"),
                  encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn('MINORS="3.10', src,
                         "matrix_c05.sh carries its own list of supported "
                         "minors; it must read the canonical one")
        self.assertIn("wheel_matrix.py", src,
                      "matrix_c05.sh must read the canonical list")

    def test_the_tag_follows_the_minor(self):
        self.assertEqual("cp313", wheel_matrix.minor_tag("3.13"))


class TestInterpreterDiscovery(unittest.TestCase):
    """The interpreter lookup must never substitute."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _make_interp(self, minor, flavour="gil"):
        tag = "cp%s-cp%s" % (minor.replace(".", ""), minor.replace(".", ""))
        if flavour == "freethreaded":
            tag += "t"
        d = os.path.join(self.tmp, tag, "bin")
        os.makedirs(d)
        p = os.path.join(d, "python" + minor)
        with open(p, "w") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(p, 0o755)
        return p

    def test_a_missing_interpreter_is_not_substituted(self):
        """No interpreter -> None. NOT "the newest one we can find"."""
        self._make_interp("3.13")
        self.assertIsNone(
            wheel_matrix.interpreter_for_minor("3.11", roots=(self.tmp,)),
            "a missing interpreter resolved to something else -- that is "
            "the substitution this must never do")

    def test_the_interpreter_for_a_minor_is_found(self):
        p = self._make_interp("3.13")
        self.assertEqual(
            p, wheel_matrix.interpreter_for_minor("3.13", roots=(self.tmp,)))

    def test_the_free_threaded_twin_is_refused(self):
        """setup.py will not ship a free-threaded helper (the sonames
        differ, so the artifacts are mutually load-incompatible), so
        building against one could only produce a wheel that is not a
        per-minor wheel."""
        self._make_interp("3.13", flavour="freethreaded")
        self.assertIsNone(
            wheel_matrix.interpreter_for_minor("3.13", roots=(self.tmp,)),
            "the free-threaded interpreter was selected; it cannot "
            "produce a per-minor wheel")

    def test_the_gil_interpreter_wins_when_both_exist(self):
        gil = self._make_interp("3.14", flavour="gil")
        self._make_interp("3.14", flavour="freethreaded")
        self.assertEqual(
            gil, wheel_matrix.interpreter_for_minor("3.14", roots=(self.tmp,)))


class TestStaleHelpers(unittest.TestCase):
    """A helper left by a previous minor must not reach the next wheel."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_only_helper_artifacts_are_removed(self):
        for name in ("_fr_udf.cpython-312-x86_64-linux-gnu.so",
                     "_fr_udf.cpython-313-x86_64-linux-gnu.so",
                     "_fr_udf.so",
                     "libforkrun_python.so",
                     "_forkrun_cleanroom",
                     "__init__.py"):
            with open(os.path.join(self.tmp, name), "w") as fh:
                fh.write("x")
        removed = wheel_matrix.remove_helpers(self.tmp)
        self.assertEqual(
            ["_fr_udf.cpython-312-x86_64-linux-gnu.so",
             "_fr_udf.cpython-313-x86_64-linux-gnu.so",
             "_fr_udf.so"],
            removed)
        self.assertTrue(
            os.path.exists(os.path.join(self.tmp, "libforkrun_python.so")),
            "the substrate .so must not be removed")
        self.assertTrue(
            os.path.exists(os.path.join(self.tmp, "_forkrun_cleanroom")),
            "the cleanroom launcher must not be removed")


class TestWheelValidation(unittest.TestCase):
    """The tag must agree with the artifact it ships."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_a_correct_per_minor_wheel_passes(self):
        w = _make_wheel(self.tmp, "cp313", "cp313",
                        helpers=["_fr_udf.cpython-313-x86_64-linux-gnu.so"])
        self.assertEqual([], wheel_matrix.validate_wheel(w, "3.13"))

    def test_a_wheel_tagged_for_another_minor_is_rejected(self):
        w = _make_wheel(self.tmp, "cp312", "cp312",
                        helpers=["_fr_udf.cpython-312-x86_64-linux-gnu.so"])
        problems = wheel_matrix.validate_wheel(w, "3.13")
        self.assertTrue(problems,
                        "a 3.12 wheel was accepted as a 3.13 build")

    def test_a_wheel_with_a_helper_for_another_minor_is_rejected(self):
        """The tag says 3.13; the helper says 3.12. One of them is a
        lie, and the artifact decides which."""
        w = _make_wheel(self.tmp, "cp313", "cp313",
                        helpers=["_fr_udf.cpython-312-x86_64-linux-gnu.so"])
        problems = wheel_matrix.validate_wheel_tags(w)
        self.assertTrue(problems,
                        "a wheel whose helper is for a different minor was "
                        "accepted")

    def test_a_per_minor_wheel_with_no_helper_is_rejected(self):
        """The tag promises a CPython-linked helper. Shipping none
        makes the tag a claim the artifact does not support."""
        w = _make_wheel(self.tmp, "cp313", "cp313")
        problems = wheel_matrix.validate_wheel_tags(w)
        self.assertTrue(problems,
                        "a cp313 wheel that ships no helper was accepted")

    def test_a_generic_wheel_that_ships_a_helper_is_rejected(self):
        """The mirror: a generic ABI-independent wheel must not
        advertise a helper."""
        w = _make_wheel(self.tmp, "py3", "none",
                        helpers=["_fr_udf.cpython-313-x86_64-linux-gnu.so"])
        problems = wheel_matrix.validate_wheel_tags(w)
        self.assertTrue(problems,
                        "a py3-none wheel shipping a CPython-linked helper "
                        "was accepted")

    def test_a_none_abi_tag_with_a_helper_is_rejected(self):
        """"none" means "no ABI constraint", and a free-threaded
        interpreter accepts cp313-none-<platform> exactly as a GIL one
        does -- so a GIL helper in a none-ABI wheel advertises
        compatibility with an interpreter that cannot load it."""
        w = _make_wheel(self.tmp, "cp313", "none",
                        helpers=["_fr_udf.cpython-313-x86_64-linux-gnu.so"])
        problems = wheel_matrix.validate_wheel_tags(w)
        self.assertTrue(problems,
                        "a cp313-none wheel shipping a GIL helper was "
                        "accepted")

    def test_a_generic_wheel_with_no_helper_is_accepted(self):
        """The substrate-only wheel is legitimate: no helper, generic
        tags."""
        w = _make_wheel(self.tmp, "py3", "none")
        self.assertEqual([], wheel_matrix.validate_wheel_tags(w))


class TestMatrixReporting(unittest.TestCase):
    """A partial matrix must never read as a complete one."""

    def _result(self, minor, status):
        return {"minor": minor, "status": status, "wheel": None,
                "problems": [], "detail": ""}

    def test_an_incomplete_matrix_lists_its_missing_minors(self):
        results = [self._result("3.12", "built"),
                   self._result("3.13", "not-built"),
                   self._result("3.14", "failed")]
        self.assertEqual(["3.13", "3.14"], wheel_matrix.incomplete(results))

    def test_a_complete_matrix_has_nothing_incomplete(self):
        results = [self._result(m, "built")
                   for m in wheel_matrix.SUPPORTED_MINORS]
        self.assertEqual([], wheel_matrix.incomplete(results))

    def test_the_strict_cli_fails_on_a_partial_matrix(self):
        """--strict must exit non-zero when a supported minor did not
        produce a valid wheel."""
        import subprocess
        out = os.path.join(self.tmp_dir(), "matrix")
        proc = subprocess.run(
            [sys.executable,
             os.path.join(_ROOT, "tools", "wheel_matrix.py"),
             "--all", "--out-dir", out, "--strict"],
            capture_output=True, text=True,
            env=dict(os.environ, FORKRUN_WHEEL_MATRIX_TEST="1"))
        # On this host no /opt/python exists, so every minor is
        # unavailable -> the strict run must fail.
        self.assertNotEqual(0, proc.returncode,
                            "a strict matrix run with no interpreters "
                            "reported success")
        self.assertIn("INCOMPLETE MATRIX", proc.stderr)

    def tmp_dir(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d


if __name__ == "__main__":
    unittest.main()
