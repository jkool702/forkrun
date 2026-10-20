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

THE ABI TAG MATTERS TOO, AND IT IS NOT THE SAME THING. `cp314` names a
python VERSION; the abi tag names the ABI. A free-threaded CPython 3.14
links `libpython3.14t.so.1.0` where a GIL one links
`libpython3.14.so.1.0` -- different sonames, so the helper built for
one cannot be loaded by the other. The python tag `cp314` does not
distinguish them, so the ABI tag has to: `cp314-cp314` for the GIL
build, `cp314-cp314t` for the free-threaded one.

And the loose tag is the trap: the ABI tag `none` means "no ABI
constraint", and a free-threaded 3.14 accepts `cp314-none-<platform>`
exactly as a GIL 3.14 does -- so a GIL-built helper in a "none"-ABI
wheel advertises compatibility with an interpreter that cannot load it.
The compatibility assertions below are made against REAL
`packaging.tags` tag sets, not against filename strings, because the
filename is not what pip consults.

FREE-THREADED CPython IS NOT SUPPORTED for this helper route, and the
packaging declines to claim it: the helper links a different
`libpython` soname, the C0.5 matrix fetches GIL interpreters only, and
the launcher has never been exercised against a free-threaded build. So
a free-threaded build ships no helper at all.

These tests pin the RULE directly, with a temporary package directory,
so they do not need a second interpreter and do not build a wheel.

Run: cd python/tests && python3 -m unittest test_udf_packaging
"""

import os
import shutil
import sys
import sysconfig
import tempfile
import unittest

from packaging.tags import Tag

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, os.pardir))
sys.path.insert(0, _HERE)

REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))


def _load_setup_module(freethreaded=False):
    """setup.py's REAL module-level state, with setup() stubbed out.

    The point is to test the values setup.py ACTUALLY computes -- the
    helper it would ship and the tag it would write -- rather than a
    re-implementation of the rule, which would be a test of the test.

    setup.py calls setup() at import, so setuptools.setup is stubbed
    before the source is executed.

    `freethreaded=True` makes the interpreter LOOK free-threaded (the
    build config and the extension suffix are both rewritten), so the
    free-threaded policy can be verified on a GIL host -- which is the
    only kind of interpreter this repository has.
    """
    import setuptools
    path = os.path.join(REPO_ROOT, "setup.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    real_setup = setuptools.setup
    setuptools.setup = lambda *a, **k: None
    real_cfg = sysconfig.get_config_var
    if freethreaded:
        minor = "%d%d" % sys.version_info[:2]

        def fake_get_config_var(name):
            if name == "Py_GIL_DISABLED":
                return 1
            if name == "EXT_SUFFIX":
                return (real_cfg(name) or "").replace(
                    "cpython-%s" % minor, "cpython-%st" % minor)
            return real_cfg(name)
        sysconfig.get_config_var = fake_get_config_var
    try:
        ns = {"__file__": path, "__name__": "setup_under_test"}
        exec(compile(src, path, "exec"), ns)
    finally:
        setuptools.setup = real_setup
        sysconfig.get_config_var = real_cfg
    for key in ("_udf_helper_for_this_interpreter", "UDF_HELPER",
                "WHEEL_PYTHON_TAG", "WHEEL_ABI_TAG"):
        assert key in ns, "%s not found in setup.py" % key
    return ns


_SETUP = _load_setup_module()


def _load_runtime_module():
    """forkrun/_udf.py, loaded by path (it has no relative imports)."""
    import importlib.util
    path = os.path.join(REPO_ROOT, "python", "forkrun", "_udf.py")
    spec = importlib.util.spec_from_file_location("forkrun._udf_under_test",
                                                  path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_RUNTIME = _load_runtime_module()

#: A platform tag to build the compatibility tags against. The exact
#: platform does not matter for the question being asked (does an
#: interpreter accept this tag), and the wheel's own platform tag is
#: checked separately by the release gate.
_PLATFORM = "manylinux_2_39_x86_64"


def _compatible_tags(abis=None):
    """The REAL compatible-tag set for an interpreter of this version.

    Built with `packaging.tags`, which is what pip consults -- not with
    the filename conventions, which are only how the tag is WRITTEN.
    """
    try:
        from packaging.tags import cpython_tags
    except ImportError:
        raise unittest.SkipTest("packaging is not available")
    if abis is None:
        abis = ["cp%d%d" % sys.version_info[:2]]
    return set(cpython_tags(tuple(sys.version_info[:2]), abis=abis,
                             platforms=[_PLATFORM]))


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

    def _gil_suffix(self):
        """The GIL extension suffix for this interpreter's MINOR.

        Deliberately NOT the host's own suffix: the rule under test is
        "a GIL helper for this minor is detected", and that must hold
        whether the suite is running on a GIL or a free-threaded
        interpreter. Using the host's suffix would make the test
        assert the OPPOSITE of the policy on a free-threaded host --
        the detector correctly declines a free-threaded helper there,
        so the test would fail for doing the right thing.
        """
        suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
        return suffix.replace(
            "cpython-%d%dt" % sys.version_info[:2],
            "cpython-%d%d" % sys.version_info[:2])

    def _free_threaded_suffix(self):
        """The free-threaded extension suffix for this minor."""
        return ".cpython-%d%dt-x86_64-linux-gnu.so" % (
            sys.version_info[0], sys.version_info[1])

    def test_a_gil_helper_for_this_minor_is_detected(self):
        # The GIL flavour of this minor IS eligible, on any host.
        suffix = self._gil_suffix()
        name = "_fr_udf" + suffix
        open(os.path.join(self.d, name), "wb").close()
        self.assertEqual(
            _SETUP["_udf_helper_for_this_interpreter"](self.d, suffix),
            name,
            "a GIL helper built for THIS minor was not detected, so the "
            "wheel would not ship it")

    def test_this_host_s_own_policy_matches_the_packaging_rule(self):
        """What the packaging does on THIS host, asserted directly.

        On a GIL host the helper is eligible; on a free-threaded host
        it is declined and the packaging falls back to the generic
        (helper-free) wheel. The test states the policy rather than
        assuming it, so the suite is green -- and meaningful -- on
        either kind of interpreter.
        """
        suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
        name = "_fr_udf" + suffix
        open(os.path.join(self.d, name), "wb").close()
        detected = _SETUP["_udf_helper_for_this_interpreter"](self.d, suffix)
        if _RUNTIME.freethreaded_interpreter():
            self.assertIsNone(
                detected,
                "this is a FREE-THREADED interpreter, so the helper "
                "must be declined and the wheel must be the generic one")
            self.assertIsNone(
                _SETUP["WHEEL_PYTHON_TAG"],
                "a free-threaded build must not produce a per-minor tag")
        else:
            self.assertEqual(detected, name,
                             "a GIL helper for this minor must be "
                             "detected on a GIL interpreter")
            self.assertIsNotNone(
                _SETUP["WHEEL_PYTHON_TAG"],
                "a helper-carrying build must produce a per-minor tag")

    def test_the_packaging_declines_a_free_threaded_build(self):
        """Simulated free-threaded build: no helper, no per-minor tag.

        This is the packaging's half of the policy, exercised on a GIL
        host by making the interpreter LOOK free-threaded -- the build
        config and the extension suffix are both rewritten, so the
        detection sees exactly what it would see on a real one.
        """
        setup = _load_setup_module(freethreaded=True)
        self.assertIsNone(
            setup["UDF_HELPER"],
            "a free-threaded build was about to ship a helper")
        self.assertIsNone(
            setup["WHEEL_PYTHON_TAG"],
            "a free-threaded build produced a per-minor python tag")
        self.assertIsNone(
            setup["WHEEL_ABI_TAG"],
            "a free-threaded build produced an ABI tag")

    def test_the_runtime_declines_a_free_threaded_interpreter(self):
        """The policy is RUNTIME, not only packaging.

        The version barrier compares only major.minor -- the build
        stamp carries no free-threading bit -- so the two flavours of
        the same minor are indistinguishable to it. Declining here is
        what makes "free-threaded is not supported" true end to end:
        the capability reports False, the launcher is never handed a
        helper to load, and the route degrades to the in-process path.
        """
        minor = "%d%d" % sys.version_info[:2]
        ft_suffix = ".cpython-%st-x86_64-linux-gnu.so" % minor
        self.assertTrue(
            _RUNTIME.freethreaded_interpreter(suffix=ft_suffix),
            "a free-threaded suffix was not recognised as free-threaded")
        self.assertFalse(
            _RUNTIME.freethreaded_interpreter(
                suffix=".cpython-%s-x86_64-linux-gnu.so" % minor),
            "a GIL suffix was misread as free-threaded")

    def test_the_packaging_and_the_runtime_agree(self):
        """ONE rule, two layers -- on THIS host AND simulated.

        The packaging asks the runtime's answer rather than keeping a
        second copy of it, so there is nothing to disagree about. This
        asserts the wiring, so a future refactor that reintroduces a
        second copy fails here.

        The simulated comparison matters as much as the real one: a
        local flavour check in setup.py could make the two disagree
        under free-threaded conditions while agreeing here.
        """
        self.assertIs(
            _SETUP["_freethreaded_interpreter"](),
            _RUNTIME.freethreaded_interpreter(),
            "the packaging and the runtime disagree about whether this "
            "interpreter is free-threaded")
        for suffix in (self._gil_suffix(), self._free_threaded_suffix()):
            self.assertIs(
                _SETUP["_freethreaded_interpreter"](suffix=suffix),
                _RUNTIME.freethreaded_interpreter(suffix=suffix),
                "the packaging and the runtime disagree about the "
                "flavour of %r" % (suffix,))

    def test_the_runtime_refuses_a_helper_under_free_threading(self):
        """The RUNTIME lookup path, with a candidate helper IN it.

        The reviewer's point: the packaging test can decline a
        free-threaded candidate on its own, without the runtime's
        lookup ever being consulted. This puts a candidate helper where
        the runtime LOOKS for one and asserts the lookup refuses it --
        so the refusal is proven at the boundary that matters, not only
        in the packaging.

        The package directory is redirected by patching the module's
        __file__, so nothing is written into the real package.
        """
        mod = _RUNTIME
        old_file = mod.__file__
        old_cfg = sysconfig.get_config_var
        minor = "%d%d" % sys.version_info[:2]

        # Two flavours, each with a candidate helper NAMED for it, so
        # the lookup can actually find the thing it is refusing.
        for flavour, suffix in (("gil", self._gil_suffix()),
                                ("free-threaded",
                                 self._free_threaded_suffix())):
            with self.subTest(flavour=flavour):
                d = tempfile.mkdtemp()
                self.addCleanup(shutil.rmtree, d, True)
                open(os.path.join(d, "_fr_udf" + suffix), "wb").close()
                mod.__file__ = os.path.join(d, "_udf.py")
                is_ft = ("cpython-%st-" % minor) in suffix

                def fake(name, _s=suffix, _ft=is_ft, _old=old_cfg):
                    if name == "Py_GIL_DISABLED":
                        return 1 if _ft else 0
                    if name == "EXT_SUFFIX":
                        return _s
                    return _old(name)

                try:
                    sysconfig.get_config_var = fake
                    found = mod.helper_path()
                finally:
                    sysconfig.get_config_var = old_cfg
                    mod.__file__ = old_file

                if flavour == "gil":
                    self.assertIsNotNone(
                        found,
                        "the control failed: a GIL interpreter did not "
                        "find the candidate helper, so the refusal below "
                        "would prove nothing")
                else:
                    self.assertIsNone(
                        found,
                        "a free-threaded interpreter was handed a helper: "
                        "the runtime must refuse it before the launcher "
                        "is invoked")

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

    # -- the ABI half ---------------------------------------------------

    def test_a_free_threaded_helper_is_refused(self):
        # A free-threaded build's extension suffix is
        # cpython-314t-..., which CONTAINS "cpython-314". A substring
        # check on the minor alone would therefore accept it, and the
        # wheel would claim a GIL minor for a free-threaded binary.
        ft_suffix = self.suffix.replace(
            "cpython-%d%d" % sys.version_info[:2],
            "cpython-%d%dt" % sys.version_info[:2])
        name = "_fr_udf" + ft_suffix
        open(os.path.join(self.d, name), "wb").close()
        self.assertIsNone(
            _SETUP["_udf_helper_for_this_interpreter"](self.d, ft_suffix),
            "a free-threaded helper was accepted: the route does not "
            "support free-threaded CPython, so the wheel must not claim "
            "one")

    def test_the_shipped_tag_is_accepted_by_this_interpreter(self):
        # The tag the packaging produces must be in the RUNNING
        # interpreter's own compatible set, or pip would refuse the
        # wheel it just built.
        tag = _SETUP["WHEEL_PYTHON_TAG"]
        if tag is None:
            self.skipTest("no helper in this tree: the generic wheel is "
                          "py3-none, which every interpreter accepts")
        abi = _SETUP["WHEEL_ABI_TAG"]
        self.assertIsNotNone(abi, "a helper-carrying wheel needs a real "
                                   "ABI tag")
        self.assertNotEqual("none", abi,
                            "the ABI tag must not be 'none': that "
                            "advertises compatibility with a "
                            "free-threaded interpreter that cannot load "
                            "a GIL-built helper")
        mine = _compatible_tags()
        self.assertIn(Tag(tag, abi, _PLATFORM), mine,
                      "the wheel's own tag is not in this interpreter's "
                      "compatible set: pip would refuse it")

    def test_the_shipped_tag_is_not_accepted_by_a_free_threaded_one(self):
        # The direction that matters: a GIL-built helper must NOT be
        # offered to a free-threaded interpreter.
        tag = _SETUP["WHEEL_PYTHON_TAG"]
        if tag is None:
            self.skipTest("no helper in this tree")
        abi = _SETUP["WHEEL_ABI_TAG"]
        free = _compatible_tags(abis=["cp%d%dt" % sys.version_info[:2]])
        self.assertNotIn(
            Tag(tag, abi, _PLATFORM), free,
            "the wheel's tag is accepted by a FREE-THREADED interpreter: "
            "it would install a helper that interpreter cannot load")

    def test_a_free_threaded_wheel_would_be_distinct(self):
        # If free-threaded were supported later, its tag would be
        # cp314-cp314t -- in the free-threaded set and NOT in the GIL
        # one. This pins that the two directions are distinguishable at
        # all, so the "not supported yet" decision is a policy and not
        # a limitation of the tagging.
        minor = "%d%d" % sys.version_info[:2]
        ft = Tag("cp" + minor, "cp" + minor + "t", _PLATFORM)
        gil = Tag("cp" + minor, "cp" + minor, _PLATFORM)
        free = _compatible_tags(abis=["cp" + minor + "t"])
        mine = _compatible_tags()
        self.assertIn(ft, free,
                      "a free-threaded tag must be accepted by a "
                      "free-threaded interpreter")
        self.assertNotIn(ft, mine,
                         "a free-threaded tag must NOT be accepted by a "
                         "GIL interpreter")
        self.assertNotIn(gil, free,
                         "a GIL tag must NOT be accepted by a "
                         "free-threaded interpreter")


if __name__ == "__main__":
    unittest.main()
