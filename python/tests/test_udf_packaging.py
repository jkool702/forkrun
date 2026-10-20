"""W-EXP-1: the UDF helper's WHEEL packaging.

DECISION-01 §5.4/§6.2.1: the UDF helper is a SEPARATE, CPython-LINKED
artifact, and that has two consequences for the wheel:

  * a wheel that SHIPS the helper must not claim a generic `py3` tag --
    the helper links libpython3.X, so the wheel is valid only for the
    minor it was built against;
  * a wheel with NO helper stays `py3-none-<platform>`, and the
    substrate remains interpreter-agnostic. "Keep the source-only
    development path honest: do not advertise a locally built helper as
    present in a generic ABI-independent wheel."

The rule that satisfies both: **the wheel's python tag follows the
HELPER, not the running interpreter.** The helper's extension suffix
encodes the minor it was compiled against
(`_fr_udf.cpython-314-x86_64-linux-gnu.so` -> 3.14), so a helper built
for a different minor has a different NAME and is simply not found. That
is what makes a mismatched build safe: it cannot produce a wheel that
claims the wrong minor.

These tests pin the RULE directly, with a temporary package directory,
so they do not need a second interpreter and do not build a wheel.

Run: cd python/tests && python3 -m unittest test_udf_packaging
"""

import os
import sys
import sysconfig
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, os.pardir))
sys.path.insert(0, _HERE)

REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))


def _load_setup_module():
    """setup.py runs setup() at import, so pull the helper out of the
    SOURCE TEXT instead of importing it.

    The extraction is AST-based: a regex over a docstring-heavy file is
    a trap (and was one).
    """
    import ast
    path = os.path.join(REPO_ROOT, "setup.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) \
                and node.name == "_udf_helper_for_this_interpreter":
            fn = node
            break
    assert fn is not None, "_udf_helper_for_this_interpreter not in setup.py"
    ns = {"__file__": path, "os": os}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), path, "exec"), ns)
    return ns


_SETUP = _load_setup_module()


class TestUdfWheelTagRule(unittest.TestCase):
    """Which helper may ship, and under which tag."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
        self.minor = "cpython-%d%d" % sys.version_info[:2]

    def _detect(self):
        return _SETUP["_udf_helper_for_this_interpreter"](self.d)

    def test_the_helper_for_this_interpreter_is_detected(self):
        name = "_fr_udf" + self.suffix
        open(os.path.join(self.d, name), "wb").close()
        self.assertEqual(self._detect(), name,
                         "a helper built for THIS interpreter was not "
                         "detected, so the wheel would not ship it")

    def test_no_helper_means_no_helper(self):
        self.assertIsNone(self._detect(),
                          "an absent helper was reported as present")

    def test_a_helper_for_another_minor_is_refused(self):
        # A helper built for 3.12 in a tree running 3.14: its name
        # differs, so it is not found, so it cannot ship under cp314.
        other = "_fr_udf" + self.suffix.replace(
            "cpython-%d%d" % sys.version_info[:2], "cpython-312")
        open(os.path.join(self.d, other), "wb").close()
        self.assertIsNone(
            self._detect(),
            "a helper built for a DIFFERENT minor was accepted: the wheel "
            "would claim this interpreter's tag for someone else's binary")

    def test_the_plain_named_helper_is_refused(self):
        # `_fr_udf.so` (no suffix) is the runtime fallback for a SOURCE
        # CHECKOUT. Its minor cannot be established from its name, so a
        # wheel must not ship it and must not claim a minor for it.
        open(os.path.join(self.d, "_fr_udf.so"), "wb").close()
        self.assertIsNone(
            self._detect(),
            "the plain-named helper was accepted: the wheel would claim a "
            "minor it cannot establish")

    def test_the_wheel_tag_follows_the_helper(self):
        # The tag is derived from the DETECTED helper, so "helper present"
        # and "cp3XX tag" cannot disagree.
        with open(os.path.join(REPO_ROOT, "setup.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("WHEEL_PYTHON_TAG", src)
        self.assertRegex(
            src, r"if\s+UDF_HELPER\s*:",
            "the python tag must be set exactly when the helper is "
            "shipped, or the two can disagree")
        self.assertRegex(
            src, r'WHEEL_PYTHON_TAG\s*=\s*"cp%d%d"',
            "the per-minor tag must be derived from the interpreter's "
            "minor")

    def test_a_helper_present_forces_a_non_generic_tag(self):
        # The helper must be in package_data exactly when it is shipped.
        with open(os.path.join(REPO_ROOT, "setup.py"), encoding="utf-8") as fh:
            src = fh.read()
        lines = src.splitlines()
        idx = [i for i, ln in enumerate(lines) if "package_data=" in ln]
        self.assertTrue(idx, "no package_data in setup.py")
        block = "\n".join(lines[idx[0]:idx[0] + 4])
        self.assertIn("UDF_HELPER", block,
                      "the helper must be listed in package_data, or a "
                      "wheel install silently has no UDF accelerator "
                      "(the CR-FIX1-I class of bug)")
        # And the generic tag must not be claimed when it ships.
        self.assertRegex(
            src, r'"python_tag":\s*WHEEL_PYTHON_TAG',
            "the wheel's python tag must come from the helper-derived "
            "value")


if __name__ == "__main__":
    unittest.main()
