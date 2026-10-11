"""P1 Phase 2 (DECISION-01) -- the embedded-CPython UDF helper.

Scope: the shipped-shape artifact from DECISION-01 section 8 --
a per-minor .so that embeds a deliberately-initialised interpreter, plus
the Phase-1 probe (now driving that library) and the C0.4 fork driver.

WHY EVERY TEST HERE RUNS A SUBPROCESS
    The helper links and initialises libpython. A test runner is itself a
    running Python, so dlopening the helper into it and calling
    fr_udf_init means calling Py_InitializeFromConfig on a live
    interpreter -- undefined, and in practice a core dump. That is not a
    quirk of the tests; it is the helper's actual contract, and it is the
    reason the helper lives in a separate dlopen-able object driven by
    the C launcher rather than linked into the Python parent. So the tests
    exercise the binaries directly, which is also what ships.

Run: make -f Makefile.substrate udf && python3 -m unittest test_udf_helper
"""

import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
_PKG = os.path.join(_ROOT, "python", "forkrun")

# The interpreter whose headers the helper was built against. If the
# helper was built for a different minor these binaries are meaningless,
# so the tests skip rather than assert something about the wrong build.
import sysconfig  # noqa: E402

_PROBE = os.path.join(_PKG, "fr_udf_helper")
_FORK = os.path.join(_PKG, "fr_udf_fork")
_LIB_GLOB = "_fr_udf%s" % (sysconfig.get_config_var("EXT_SUFFIX") or ".so")

UDF_SRC = '''
def up(b):
    return b.upper()

def to_none(b):
    return None

def empty(b):
    return b""

def raises(b):
    raise ValueError("udf exploded")

STATE = {"touched": False}

def touch(b):
    STATE["touched"] = True
    return b

def is_touched(b):
    return b"yes" if STATE["touched"] else b"no"

def wrong_type(b):
    return 42
'''


def _have(binary):
    return os.path.exists(binary)


def _run(argv, timeout=120):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


class _UDFFixture(unittest.TestCase):
    """Builds a throwaway import root containing a known UDF module."""

    @classmethod
    def setUpClass(cls):
        if not _have(_PROBE):
            raise unittest.SkipTest(
                "udf artifacts not built -- run: make -f Makefile.substrate udf")
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = cls._tmp.name
        with open(os.path.join(cls.root, "myudf.py"), "w") as fh:
            fh.write(UDF_SRC)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def probe(self, *args):
        return _run([_PROBE, self.root, *args])


class TestIsolationHolds(_UDFFixture):
    """DECISION-01 6.1(a): the caller's environment must not reach it."""

    def test_isolated_flag_is_set(self):
        self.assertIn("(a) isolated=1        : HOLDS", self.probe().stdout)

    def test_env_flag_absent_is_not_reported_as_a_violation(self):
        """A flag that does not exist on this minor is UNCHECKABLE.

        Reporting "VIOLATED" for an absent attribute accuses the design of
        a breach it did not commit -- and that is precisely the bug this
        test pins, since sys.flags.use_environment is absent on 3.14.
        """
        out = self.probe().stdout
        self.assertNotIn("VIOLATED", out,
                         "reported a violation; check whether the verdict "
                         "distinguishes ABSENT from a real value")
        if "use_environment      : ABSENT" in out:
            self.assertIn("use_environment=0: CANNOT CHECK", out)

    def test_without_roots_a_third_party_package_is_unreachable(self):
        """site_import=0 drops EVERY site root, not just user site.

        This is finding 1 of DECISION-01 section 8: the obvious reading of
        user_site_directory is "turn off user site", but it turns off the
        mechanism that adds system site-packages too.
        """
        out = _run([_PROBE]).stdout
        self.assertIn("numpy (system site)      : NOT importable", out)


class TestExplicitRootsRestoreImportability(_UDFFixture):
    """6.1(b)/(c): explicit, validated roots."""

    def _system_roots(self):
        import site
        roots = []
        try:
            for p in site.getsitepackages():
                if p not in roots:
                    roots.append(p)
        except Exception:
            pass
        try:
            u = site.getusersitepackages()
            if isinstance(u, str) and u not in roots:
                roots.append(u)
        except Exception:
            pass
        return roots

    def test_numpy_is_importable_once_its_root_is_passed(self):
        """Only meaningful if numpy is actually installed here."""
        try:
            import numpy  # noqa: F401
        except Exception:
            self.skipTest("numpy not installed; would be vacuous")
        root = os.path.dirname(os.path.dirname(numpy.__file__))
        out = _run([_PROBE, root]).stdout
        self.assertIn("numpy (system site)      : importable", out)

    def test_roots_are_echoed_in_caller_order(self):
        # Two SIBLINGS, not a path and its parent: str.index() finds the
        # first occurrence, and "/tmp/x" contains "/tmp", so a parent/child
        # pair reports the same offset for both and the comparison passes
        # or fails for reasons that have nothing to do with ordering.
        a = os.path.join(self.root, "aaa_root")
        b = os.path.join(self.root, "bbb_root")
        os.makedirs(a, exist_ok=True)
        os.makedirs(b, exist_ok=True)
        out = _run([_PROBE, a, b]).stdout
        self.assertLess(out.index(a), out.index(b),
                        "roots must be reported in the order given; the "
                        "first root is the one that wins shadowing")

    def test_an_unreadable_root_is_refused(self):
        """Fail closed. An interpreter running with an unvalidated search
        path is the exact failure this design exists to prevent."""
        r = _run([_PROBE, "/nonexistent/root/xyz", "myudf:up"])
        self.assertNotEqual(0, r.returncode,
                            "an unreadable root must not be accepted")
        self.assertIn("not readable", r.stderr)


class TestUDFInvocation(_UDFFixture):
    """6.1(d): resolve, invoke, convert."""

    def test_returns_bytes(self):
        self.assertIn("call -> bytes, 11: LINE000042",
                      self.probe("myudf:up").stdout)

    def test_none_is_reported_as_no_result(self):
        """The DECISION-02 distinction, at the UDF boundary.

        None must not be laundered into an empty frame. fr_udf.h gives it
        its own return code precisely so that a caller cannot have to
        guess whether an empty buffer means "no result" or "empty result".
        """
        out = self.probe("myudf:to_none").stdout
        self.assertIn("call -> None", out)
        self.assertIn("NO_RESULT", out)

    def test_empty_bytes_is_distinct_from_none(self):
        out = self.probe("myudf:empty").stdout
        self.assertIn("call -> bytes, 0:", out)
        self.assertNotIn("call -> None", out)

    def test_missing_attribute_is_an_error_not_a_crash(self):
        r = self.probe("myudf:nosuch")
        self.assertIn("call FAILED", r.stdout)
        self.assertIn("nosuch", r.stdout)

    def test_exception_in_the_udf_is_reported(self):
        r = self.probe("myudf:raises")
        self.assertIn("call FAILED", r.stdout)
        self.assertIn("udf exploded", r.stdout + r.stderr)

    def test_non_bytes_return_is_refused(self):
        """A UDF returning an int is a contract violation, not a result."""
        r = self.probe("myudf:wrong_type")
        self.assertIn("call FAILED", r.stdout)
        self.assertIn("not bytes", r.stdout)


@unittest.skipUnless(_have(_PROBE), "udf artifacts not built")
class TestLifecycle(_UDFFixture):

    def test_clean_finalisation(self):
        self.assertIn("[ok] clean finalisation", self.probe().stdout)

    def test_library_is_built_with_the_right_extension_suffix(self):
        """The .so must carry the EXT_SUFFIX for the minor it was built
        for; a bare .so would be picked up by the wrong interpreter."""
        path = os.path.join(_PKG, _LIB_GLOB)
        self.assertTrue(os.path.exists(path),
                        "expected %s -- rebuild with "
                        "`make -f Makefile.substrate udf-lib`" % path)


@unittest.skipUnless(_have(_FORK), "udf artifacts not built")
class TestPreForkSurvivesFork(_UDFFixture):
    """C0.4: can a forked child still run Python?

    This is the correctness gate for the pre-fork candidate. If it fails,
    post-fork is the only option regardless of timings -- which is why
    the driver checks each child's outcome and refuses to report a speedup
    for a configuration that produced nothing.
    """

    def test_pre_fork_children_produce_real_output(self):
        r = _run([_FORK, self.root, "myudf:up", "4", "25"])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("failures: 0", r.stdout)
        self.assertNotIn("FAILED", r.stdout)
        self.assertIn("pre-fork works", r.stdout)

    def test_both_candidates_are_measured(self):
        r = _run([_FORK, self.root, "myudf:up", "2", "10"])
        self.assertIn("post-fork", r.stdout)
        self.assertIn("pre-fork", r.stdout)

    def test_a_broken_udf_is_reported_not_scored(self):
        """The driver must not print a speedup for children that failed."""
        r = _run([_FORK, self.root, "myudf:nosuch", "2", "5"])
        self.assertNotEqual(0, r.returncode,
                            "a UDF that cannot resolve must fail the run")
        self.assertIn("FAILED", r.stdout + r.stderr)

    def test_an_empty_result_is_caught(self):
        """A child that returns nothing must NOT count as a success.

        Without this the driver's n == 0 check is dead code: every other
        fixture UDF returns a non-empty result, so dropping the check
        entirely still produced a green run. A timing harness that counts
        a no-op as a measurement is worse than no harness.
        """
        r = _run([_FORK, self.root, "myudf:empty", "2", "3"])
        self.assertNotEqual(0, r.returncode,
                            "an empty result must not be scored as a pass")
        self.assertIn("FAILED", r.stdout + r.stderr)

    def test_a_none_result_is_caught(self):
        """None is not a result either -- and it is a different failure
        from empty, which is the whole point of FR_UDF_NO_RESULT."""
        r = _run([_FORK, self.root, "myudf:to_none", "2", "3"])
        self.assertNotEqual(0, r.returncode,
                            "a None result must not be scored as a pass")
        self.assertIn("FAILED", r.stdout + r.stderr)

    def test_a_respawned_generation_does_not_inherit_interpreter_state(self):
        """P1-3 section 5, supervision question.

        Supervision respawns a worker onto the same wid after a death. If
        a respawned generation inherited the dead one's Python-level
        state, two batches could observe each other's mutations -- a
        correctness bug nothing else in the suite would catch.

        Under pre-fork every generation is a fresh fork of the launcher,
        which still holds the PRISTINE interpreter, so the dirt dies with
        the child that made it.
        """
        r = _run([_FORK, self.root, "myudf:up", "1", "1", "--respawn"])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("respawn : CLEAN", r.stdout)

    def test_the_respawn_probe_is_not_vacuous(self):
        """The control: dirt in ONE process must be detected.

        Without this, the CLEAN verdict above would be unfalsifiable --
        a probe that can only ever report CLEAN would pass it forever.
        """
        r = _run([_FORK, self.root, "myudf:up", "1", "1", "--control"])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("probe is not vacuous", r.stdout)


if __name__ == "__main__":
    unittest.main()
