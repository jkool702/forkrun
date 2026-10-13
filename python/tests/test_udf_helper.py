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
import re
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

NOT_CALLABLE = 42

def raises_systemexit(b):
    raise SystemExit(3)
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


class TestInheritedPathScrubbed(_UDFFixture):
    """sys.path carries no caller-influenced entry, on ANY minor.

    This is the observable surface of scrub_inherited_path(), which is
    the 3.10 substitute for PyConfig.safe_path -- a field that does not
    exist before 3.11 and is what keeps a caller-controlled directory off
    sys.path. Until the probe printed sys.path there was no way to test
    that control at all.

    Two halves, and the second matters as much as the first: the scrub
    must remove the inherited entries WITHOUT removing the
    interpreter's own. A scrub that removed stdlib or lib-dynload would
    "pass" the security check and break every UDF.
    """

    def _syspath(self):
        """(count, sys.path BLOCK) -- scoped to the block, not the whole
        output. An unscoped regex matched an [ok] marker printed by an
        earlier section and returned "interpreter" as the first entry."""
        out = self.probe().stdout
        m = re.search(r"caller-influenced entries on sys.path: (\d+)",
                      out)
        self.assertIsNotNone(m, "probe did not report the count:\n%s"
                             % out[:600])
        b = re.search(r"-- sys.path .*?--\n(.*?)\n  caller-influenced",
                      out, re.S)
        self.assertIsNotNone(b, "probe did not report sys.path entries:\n%s"
                             % out[:600])
        return int(m.group(1)), b.group(1)

    def test_no_caller_influenced_entries_survive(self):
        n, out = self._syspath()
        self.assertEqual(
            0, n,
            "a caller-influenced entry (the empty string, meaning the "
            "current directory) survived on sys.path:\n%s" % out[:600])

    def test_the_working_directory_is_not_importable(self):
        """The sharpest form of the same claim.

        Run the probe FROM a directory, and require that directory not
        to be reachable as an import root. A module placed there must
        NOT be importable, which is what the control is for -- an
        interpreter that can import cwd is an interpreter that will
        import whatever the caller happened to leave lying around.
        """
        import shutil
        elsewhere = tempfile.mkdtemp(prefix="udf_scrub_")
        self.addCleanup(shutil.rmtree, elsewhere, ignore_errors=True)
        with open(os.path.join(elsewhere, "should_not_import.py"),
                  "w") as fh:
            fh.write("raise AssertionError('cwd was importable')\n")
        proc = subprocess.run([_PROBE, self.root], cwd=elsewhere,
                              capture_output=True, timeout=120)
        out = proc.stdout.decode()
        self.assertIn(
            "caller-influenced entries on sys.path: 0", out,
            "the cwd reached sys.path when the probe was launched from it:\n%s"
            % out[:600])
        self.assertNotIn(
            elsewhere, out,
            "the cwd appears verbatim in sys.path:\n%s" % out[:600])

    def test_the_interpreter_still_functions_after_the_scrub(self):
        """Over-scrubbing would pass the security test and break the
        product. The probe calls a UDF, so a stripped sys.path surfaces
        here as an init or call failure."""
        proc = self.probe()
        self.assertIn("[ok] interpreter initialised", proc.stdout,
                      "the interpreter failed to initialise; the scrub may "
                      "have removed too much:\n%s" % proc.stdout[:600])

    def test_stdlib_entries_survive(self):
        """stdlib and lib-dynload must remain: they are interpreter-owned
        and not caller-influenced."""
        _, entries = self._syspath()
        self.assertRegex(entries, r"\[ok\] .*lib-dynload",
                         "lib-dynload was removed from sys.path; the scrub "
                         "is removing interpreter-owned entries:\n%s"
                         % entries)
        self.assertRegex(entries, r"\[ok\] .*python3\.\d+",
                         "the stdlib entry was removed from sys.path:\n%s"
                         % entries)

    def test_the_callers_root_is_present_and_first(self):
        """The scrub must not remove what install_roots() added."""
        _, entries = self._syspath()
        first = re.search(r"\[ok\] (\S+)", entries)
        self.assertIsNotNone(first, "no sys.path entries reported")
        self.assertEqual(
            self.root, first.group(1),
            "the caller's root is not first on sys.path; something "
            "reordered or replaced it:\n%s" % entries)


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

    def test_systemexit_is_a_batch_error_not_a_worker_death(self):
        """A UDF calling sys.exit() must not kill the process.

        PyErr_Print() EXITS for SystemExit rather than returning, so the
        first implementation turned an ordinary batch-level failure into
        a worker death: the batch was lost and escrow/retry/skip/
        fail-fast were all bypassed, because the process was gone before
        any of them could run. Structured extraction fixes it.
        """
        r = self.probe("myudf:raises_systemexit")
        self.assertEqual(0, r.returncode,
                         "SystemExit must not terminate the helper")
        self.assertIn("call FAILED", r.stdout)
        self.assertIn("SystemExit", r.stdout)

    def test_exception_diagnostic_names_the_type(self):
        """str(SystemExit(3)) is just "3"; without the type name the
        diagnostic says nothing about what actually happened."""
        r = self.probe("myudf:raises_systemexit")
        self.assertIn("udf raised: SystemExit:", r.stdout)

    def test_non_callable_attribute_is_a_defined_error(self):
        """Named explicitly, not as a stray TypeError from the call.

        Otherwise a UDF wired as `mod:CONSTANT` instead of `mod:fn`
        reports as though the invocation failed, naming neither the
        module nor the attribute.
        """
        r = self.probe("myudf:NOT_CALLABLE")
        self.assertIn("call FAILED", r.stdout)
        self.assertIn("is not callable", r.stdout)
        self.assertIn("myudf.NOT_CALLABLE", r.stdout)

    def test_non_bytes_return_is_refused(self):
        """A UDF returning an int is a contract violation, not a result."""
        r = self.probe("myudf:wrong_type")
        self.assertIn("call FAILED", r.stdout)
        self.assertIn("not bytes", r.stdout)


@unittest.skipUnless(_have(_PROBE), "udf artifacts not built")
class TestForkHooks(_UDFFixture):
    """CPython's fork lifecycle hooks (review amendment).

    `fr_udf_init` before `fork()` obliges the launcher to choreograph every
    fork: `PyOS_BeforeFork()` before, `PyOS_AfterFork_Parent()` after (even
    when fork fails), `PyOS_AfterFork_Child()` in the child before any
    Python call. These are compiled only under CPython's `HAVE_FORK`, so
    availability is reported rather than assumed.
    """

    def test_hooks_are_available_on_this_build(self):
        self.assertIn("CPython fork hooks    : available",
                      self.probe().stdout)

    def test_they_are_not_optional_silence(self):
        """An unavailable build must SAY so.

        The hooks fail closed rather than degrading to no-ops: a caller
        that believes it choreographed its forks when it did not is the
        silent-corruption case they exist to prevent.
        """
        out = self.probe().stdout
        self.assertNotIn("UNAVAILABLE (CPython built without HAVE_FORK)",
                         out, "this build reports the hooks are missing")


@unittest.skipUnless(_have(_FORK), "udf artifacts not built")
class TestHooksAreLoadBearing(_UDFFixture):
    """Are the hooks actually doing anything, or is pre-fork merely
    happening to work?

    Asked deliberately, because the answer is not the flattering one. The
    probe deliberately violates the choreography -- takes BeforeFork,
    forks, and omits AfterFork_Child -- and reports what happened. On this
    single-threaded, contention-free machine the unhooked child SURVIVES.

    That is recorded rather than buried. It means the hooks are not
    currently earning their keep here: they protect contention cases this
    harness never creates (another thread at fork time, a UDF that spawns
    a thread). They stay because CPython documents them as mandatory for
    exactly this embedding pattern -- not because this test proves it.
    """

    def test_unhooked_child_is_probed_and_reported(self):
        r = _run([_FORK, self.root, "myudf:up", "1", "1", "--hooks"])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"hooks\s+:\s+(LOAD-BEARING|unhooked)")

    def test_correctly_hooked_children_still_work(self):
        """The control for the above: proper choreography must not break
        anything, or 'load-bearing' would be indistinguishable from
        'hooks break forks'."""
        r = _run([_FORK, self.root, "myudf:up", "2", "10"])
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("pre-fork works", r.stdout)


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
