"""W-PY23 packaging v2: platform wheel, metadata, sdist, coherence.

Extends test_packaging.py (install cycle) with release-gate checks:
the wheel must be platform-tagged (never py3-none-any), METADATA
complete, the sdist self-contained (builds + installs from source),
and versions coherent (0.18.0 everywhere, v3.6.2 in the changelog).
The full release_check.py gate runs only on committed trees (it
asserts a clean tree, which a working tree cannot satisfy — it
skips there and runs on CI release branches).
"""

import glob
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))


def _pip_available():
    try:
        subprocess.run([sys.executable, "-m", "pip", "--version"],
                       capture_output=True, check=True, timeout=60)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _build_wheel(workdir):
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
         "-w", workdir],
        capture_output=True, text=True, timeout=900, cwd=REPO_ROOT)
    assert proc.returncode == 0, \
        "wheel build failed:\n%s" % proc.stderr[-3000:]
    wheels = glob.glob(os.path.join(workdir, "*.whl"))
    assert wheels, "no wheel produced"
    return wheels[0]


_MANYLINUX_TAG_RE = re.compile(r"^manylinux_(\d+)_(\d+)_(x86_64|aarch64|i686)$")


def _host_glibc():
    """(major, minor) of the build host's glibc, or None on musl."""
    try:
        confstr = os.confstr("CS_GNU_LIBC_VERSION")
    except (AttributeError, ValueError, OSError):
        return None
    m = re.search(r"(\d+)\.(\d+)", confstr or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def assert_manylinux_tag(case, tag, machine):
    """Tag must be PEP 600 manylinux and must not over-promise.

    Deliberately does NOT reuse setup.py's policy table: this asserts
    the two properties that were actually violated before — a bare
    `linux_x86_64` tag (PyPI rejects it), and a floor newer than the
    libc the binary was linked against.
    """
    m = _MANYLINUX_TAG_RE.match(tag)
    case.assertIsNotNone(
        m, "not a PEP 600 manylinux_<maj>_<min>_<arch> tag (PyPI rejects "
           "bare linux_* with 'unsupported platform tag'): %r" % tag)
    case.assertTrue(
        tag.endswith("_" + machine),
        "tag %r is not for this architecture %r" % (tag, machine))
    host = _host_glibc()
    if host is not None:
        claimed = (int(m.group(1)), int(m.group(2)))
        case.assertLessEqual(
            claimed, host,
            "tag promises glibc %d.%d but the build host only has %d.%d — "
            "the binary cannot have been compiled there"
            % (claimed + host))


class TestWheelPlatform(unittest.TestCase):
    def test_platform_tag_helpers(self):
        """get_platform_tag: manylinux tag from host glibc, others refused."""
        # Importing setup.py executes setup() at module level — stub
        # it out; we only want get_platform_tag().
        from unittest import mock
        sys.path.insert(0, REPO_ROOT)
        try:
            with mock.patch("setuptools.setup"):
                if "setup" in sys.modules:
                    del sys.modules["setup"]
                import setup as _setup_mod
        finally:
            sys.path.remove(REPO_ROOT)
        this_machine = platform.machine()
        if this_machine in ("x86_64", "aarch64"):
            # W-REL: never a bare linux_* tag — PyPI 400s on those.
            assert_manylinux_tag(self, _setup_mod.get_platform_tag(),
                                 this_machine)
        real_system, real_machine = platform.system, platform.machine
        try:
            platform.system = lambda: "Darwin"
            with self.assertRaises(RuntimeError):
                _setup_mod.get_platform_tag()
            platform.system = lambda: "Linux"
            platform.machine = lambda: "riscv64"
            with self.assertRaises(RuntimeError):
                _setup_mod.get_platform_tag()
            platform.machine = lambda: "aarch64"
            assert_manylinux_tag(self, _setup_mod.get_platform_tag(),
                                 "aarch64")
            # musl has no manylinux floor; a musllinux build is a
            # separate piece of work, so refuse loudly rather than
            # emitting a tag that misstates the libc.
            with mock.patch.object(_setup_mod, "_glibc_version",
                                   return_value=None):
                with self.assertRaises(RuntimeError):
                    _setup_mod.get_platform_tag()
        finally:
            platform.system, platform.machine = real_system, real_machine

    def test_wheel_platform_tag(self):
        """Built wheel is platform-tagged, never py3-none-any."""
        if not _pip_available():
            self.skipTest("no pip toolchain")
            return
        workdir = tempfile.mkdtemp(prefix="forkrun_wheel_")
        try:
            name = os.path.basename(_build_wheel(workdir))
            plat = name[:-len(".whl")].rsplit("-", 1)[-1]
            assert_manylinux_tag(self, plat, platform.machine())
            self.assertNotIn("none-any", name,
                             "wheel wrongly pure-Python tagged: %s"
                             % name)
            self.assertIn(forkrun.__version__, name)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def test_wheel_metadata_complete(self):
        """Wheel METADATA carries the full PyPI record."""
        if not _pip_available():
            self.skipTest("no pip toolchain")
            return
        workdir = tempfile.mkdtemp(prefix="forkrun_meta_")
        try:
            wheel = _build_wheel(workdir)
            with zipfile.ZipFile(wheel) as zf:
                metas = [n for n in zf.namelist()
                         if n.endswith(".dist-info/METADATA")]
                self.assertTrue(metas, "no METADATA in wheel")
                meta = zf.read(metas[0]).decode("utf-8")
            for field in ("Name: forkrun",
                          "Version: " + forkrun.__version__,
                          "Summary:", "Home-page:",
                          "Requires-Python: >=3.10",
                          "License:", "Classifier:",
                          "Project-URL:"):
                self.assertIn(field, meta,
                              "METADATA missing %r" % field)
            self.assertIn("Development Status :: 4 - Beta", meta)
            self.assertIn("Operating System :: POSIX :: Linux", meta)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


class TestSdist(unittest.TestCase):
    def _build_sdist(self, workdir):
        proc = subprocess.run(
            [sys.executable, "setup.py", "-q", "sdist",
             "--dist-dir", workdir],
            capture_output=True, text=True, timeout=600, cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0,
                         "sdist failed:\n%s" % proc.stderr[-3000:])
        sdists = glob.glob(os.path.join(workdir, "*.tar.gz"))
        self.assertTrue(sdists, "no sdist produced")
        return sdists[0]

    def test_sdist_contains_sources(self):
        """sdist carries every file the substrate build needs."""
        import tarfile
        workdir = tempfile.mkdtemp(prefix="forkrun_sdist_")
        try:
            sdist = self._build_sdist(workdir)
            with tarfile.open(sdist) as tf:
                names = tf.getnames()
            top = "forkrun-%s/" % forkrun.__version__
            for rel in ("forkrun_ring.c", "forkrun_substrate.h",
                        "substratestubs.c", "Makefile.substrate",
                        "ring_loadables/forkrun_plugin.h",
                        "python/forkrun/_shim.c",
                        "python/forkrun/__init__.py",
                        "python/README.md", "LICENSE",
                        "setup.py", "pyproject.toml", "MANIFEST.in"):
                self.assertIn(top + rel, names,
                              "sdist missing %s" % rel)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def test_sdist_installs_from_source(self):
        """pip install of the sdist builds the .so and runs."""
        if not _pip_available():
            self.skipTest("no pip toolchain")
            return
        import tarfile
        workdir = tempfile.mkdtemp(prefix="forkrun_sdist_inst_")
        try:
            sdist = self._build_sdist(workdir)
            with tarfile.open(sdist) as tf:
                tf.extractall(workdir)
            srcdir = os.path.join(
                workdir, "forkrun-%s" % forkrun.__version__)
            target = os.path.join(workdir, "target")
            os.mkdir(target)
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-deps",
                 "--target", target, "--no-index", "--find-links",
                 workdir, "forkrun==%s" % forkrun.__version__],
                capture_output=True, text=True, timeout=900,
                cwd=srcdir)
            # Offline CI lacks even setuptools in the isolated env;
            # retry without build isolation (uses installed backend).
            if proc.returncode != 0 and "setuptools" in proc.stderr:
                proc = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--no-deps",
                     "--no-build-isolation", "--target", target,
                     "--no-index", sdist],
                    capture_output=True, text=True, timeout=900,
                    cwd=srcdir)
            self.assertEqual(proc.returncode, 0,
                             "sdist install failed:\n%s"
                             % proc.stderr[-3000:])
            inp = os.path.join(workdir, "in.txt")
            with open(inp, "w") as fh:
                for i in range(300):
                    fh.write("line %d\n" % i)
            driver = "\n".join([
                "import sys",
                "sys.path.insert(0, %r)" % target,
                "import forkrun",
                "out = forkrun.map(lambda b: bytes(b.data), %r, "
                "workers=2, order='index', nodes=1)" % inp,
                "assert b''.join(out) == open(%r, 'rb').read()" % inp,
                "print('SDIST-OK')",
            ])
            run = subprocess.run(
                [sys.executable, "-c", driver],
                capture_output=True, text=True, timeout=300,
                cwd=workdir)
            self.assertEqual(run.returncode, 0,
                             "sdist-installed run failed:\n%s\n%s"
                             % (run.stdout, run.stderr[-2000:]))
            self.assertIn("SDIST-OK", run.stdout)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


class TestVersionCoherence(unittest.TestCase):
    def test_version_is_0_16_0(self):
        self.assertEqual(forkrun.__version__, "0.18.0")

    def test_changelog_has_v3_6_2(self):
        with open(os.path.join(REPO_ROOT, "DOCS",
                               "CHANGELOG.md")) as fh:
            content = fh.read()
        self.assertIn("v3.6.2", content)
        self.assertIn("0.18.0", content)

    def test_readme_matches_version(self):
        with open(os.path.join(REPO_ROOT, "python",
                               "README.md")) as fh:
            content = fh.read()
        self.assertIn(forkrun.__version__, content)


class TestReleaseChecklist(unittest.TestCase):
    def test_release_check_passes(self):
        """release_check.py gate -- only on committed trees.

        The checklist asserts a clean tree, which a working tree
        cannot satisfy by construction; it FAILS there (fail-closed:
        a skip would let a dirty tree look release-ready) and runs
        fully on CI release branches / pre-tag checkouts.
        Skips too when running UNDER release_check itself
        (FORKRUN_UNDER_RELEASE_CHECK — otherwise the checklist's
        own suite run would re-invoke the checklist without
        bound).
        W-REL5-F (F6.2): the changelog-finality guard is DESIGNED
        RED pre-tag (the heading still says unreleased until the
        owner finalizes it at tag time). This test pins whichever
        state is current: pre-finalization it asserts exactly one
        failure (the changelog guard) with everything else green;
        post-finalization it asserts the full green.
        W-REL6-2.1: the dirty-tree branch below is a FAIL, not a
        skip -- commit or stash first, then re-run.
        """
        if os.environ.get("FORKRUN_UNDER_RELEASE_CHECK"):
            self.skipTest("running under release_check — no recursion")
            return
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=60, cwd=REPO_ROOT)
        if proc.stdout.strip():
            self.fail(
                "release checklist requires a committed tree (it asserts "
                "a clean tree plus HEAD-anchored checks) -- commit or "
                "stash first, then re-run. Dirty paths:\n%s"
                % proc.stdout.strip())
            return
        with open(os.path.join(REPO_ROOT, "DOCS", "CHANGELOG.md")) as fh:
            # v3.6.2, and tolerant of the em-dash form the changelog
            # actually uses. The old pattern was pinned to v3.6.0 in
            # parentheses, so after the bump it would have matched nothing
            # and this test would have demanded a FULL GREEN while the
            # release heading still said unreleased.
            unreleased = re.search(
                r"^##\s+v3\.6\.2\s*(?:\(|—|-)\s*unreleased\s*\)?",
                fh.read(), re.M) is not None
        # The deadline here must exceed the release gate's OWN nested
        # suite deadline (2400s in release_check.py) plus its other
        # checks. It used to be 1500s, which was LOWER than the nested
        # budget: the outer test could kill the gate while its nested
        # suite was still running, so raising the inner budget alone
        # changed nothing -- the outer deadline was the binding one.
        # Both layers now hold the same intent, and this one is the
        # outer bound.
        # The outer deadline is derived from the gate's OWN nested
        # deadline, so the two layers cannot drift apart: the outer one
        # must exceed the inner one plus the gate's other checks.
        # Reading the constant (rather than hard-coding a second
        # number) is what makes that true by construction.
        sys.path.insert(0, os.path.join(REPO_ROOT, "python"))
        import release_check as _rc
        outer_deadline = _rc.SUITE_DEADLINE_S + 600
        # One diag directory for the whole gate run. CI sets
        # FORKRUN_RELEASE_DIAG_DIR to a path OUTSIDE the checkout and
        # uploads it under `if: always()`; locally we create one and name
        # it in every failure message so the full nested logs are always
        # reachable, not just the part inside a fixed tail window. The
        # location must stay outside the tree: release_check's clean-tree
        # check runs after the nested suite, so an in-tree diag
        # directory would itself look like an uncommitted change.
        diag_dir = os.environ.get(_rc.DIAG_DIR_ENV)
        if not diag_dir:
            diag_dir = tempfile.mkdtemp(prefix="release-check-diag-")
        gate_env = dict(os.environ)
        gate_env[_rc.DIAG_DIR_ENV] = diag_dir
        try:
            proc = subprocess.run(
                [sys.executable, "python/release_check.py"],
                capture_output=True, text=True, timeout=outer_deadline,
                cwd=REPO_ROOT, env=gate_env)
        except subprocess.TimeoutExpired as exc:
            # A timeout is a DEADLINE being reached, not a verdict: the
            # gate did not finish, so it is not known whether the cause
            # was load, a hang, or a regression. The partial output is
            # what makes it diagnosable.
            self.fail(
                "release_check.py did not finish within %ds -- the "
                "gate's own nested suite deadline is %ds, so this is the "
                "OUTER deadline being reached. The result is INCOMPLETE: "
                "without a finished run it cannot be said whether the "
                "cause was load, a hang, or a regression. Partial "
                "gate output:\n%s\n%s\n%s"
                % (outer_deadline, _rc.SUITE_DEADLINE_S,
                   _stream_tail(exc.stdout, 3000),
                   _stream_tail(exc.stderr, 1000),
                   _diag_snapshot(diag_dir, _rc,
                                  note="the killed gate may not have "
                                       "finished writing these")))
            return

        def gate_detail(prefix):
            return "\n".join([
                prefix,
                "checklist stdout (tail):\n%s"
                % _stream_tail(proc.stdout, 12000),
                "checklist stderr (tail):\n%s"
                % _stream_tail(proc.stderr, 4000),
                _diag_snapshot(diag_dir, _rc),
            ])

        if unreleased:
            self.assertEqual(
                proc.returncode, 1,
                gate_detail("expected designed-red checklist (exit 1)"))
            # Exactly the one designed failure and NOTHING else. The
            # previous form asserted only that the string "SOME CHECKS
            # FAILED (1)" occurred, so any second failure first broke
            # the substring match and then lost its own diagnosis to a
            # 2000-char stderr clip. Name every failure explicitly.
            fails = re.findall(r"^  \[FAIL\] (.+)$", proc.stdout, re.M)
            errors = re.findall(r"^  \[ERROR\] (.+)$", proc.stdout, re.M)
            self.assertEqual(
                errors, [],
                gate_detail("a release check raised an unexpected ERROR"))
            self.assertEqual(
                fails,
                ["Docs: CHANGELOG v3.6.2 heading is final "
                 "(no (unreleased))"],
                gate_detail(
                    "expected exactly the designed changelog failure; "
                    "every other check must be green pre-finalization"))
            self.assertIn("SOME CHECKS FAILED (1)", proc.stdout,
                          gate_detail("wrong failure count"))
        else:
            self.assertEqual(
                proc.returncode, 0,
                gate_detail("release checklist failed"))
            self.assertIn("ALL CHECKS PASSED", proc.stdout,
                          gate_detail("missing final success marker"))


class TestReleaseCheckDiagnostics(unittest.TestCase):
    """The nested suite's failure output must survive intact.

    The gate's old failure path raised ``proc.stderr[-2000:]``, so a
    failure whose traceback was earlier in the stream was invisible --
    and when a SECOND check failed, the outer suite reported only
    "SOME CHECKS FAILED (2)" with no way to discover which. These tests
    pin the replacement contract: the complete streams are written to
    files, and every ``FAIL:``/``ERROR:`` header in the summary is
    named in the message regardless of where it falls.
    """

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(REPO_ROOT, "python"))
        import release_check
        cls._rc = release_check

    def setUp(self):
        self._diag = tempfile.mkdtemp(prefix="rc-diag-test-")
        self.addCleanup(shutil.rmtree, self._diag, ignore_errors=True)

    @staticmethod
    def _unittest_stderr():
        """Realistic unittest output, written to the stream it uses.

        TextTestRunner writes progress, failure headers and the result
        line to stderr. This fixture puts the headers near the end; the
        "failure is far beyond a fixed tail window" case is covered
        separately by
        `test_report_preserves_full_streams_and_names_every_failure`.
        What this fixture pins is that the report NAMES the headers from
        stderr and that the assertions target the extracted,
        two-space-indented section and the explicit result line -- a raw
        stderr echo would not satisfy either shape.
        """
        return (
            "".join("test_progress_%05d ... ok\n" % i
                    for i in range(1000))
            + "\n"
            "======================================================================\n"
            "FAIL: test_beta (test_mod.TestB)\n"
            "----------------------------------------------------------------------\n"
            "Traceback (most recent call last):\n"
            '  File "test_mod.py", line 10, in test_beta\n'
            "AssertionError: beta broke\n"
            "\n"
            "======================================================================\n"
            "ERROR: test_gamma (test_mod.TestC)\n"
            "----------------------------------------------------------------------\n"
            "Traceback (most recent call last):\n"
            '  File "test_mod.py", line 20, in test_gamma\n'
            "RuntimeError: gamma exploded\n"
            "\n"
            "----------------------------------------------------------------------\n"
            "Ran 3 tests in 0.012s\n"
            "\n"
            "FAILED (failures=1, errors=1)\n")

    def test_report_names_stderr_only_failures_and_summary(self):
        """The defect: unittest writes its diagnostics to stderr.

        Assertions target the EXTRACTED section (two-space-indented
        headers and the explicit result line), not a substring that
        the raw stderr tail would also satisfy.
        """
        stdout = "a test printed this on stdout\n"
        stderr = self._unittest_stderr()
        self.assertNotIn("FAIL:", stdout)
        report = self._rc._suite_failure_report(
            stdout, stderr, reason="reason-marker", diag_dir=self._diag)

        named = [line for line in report.splitlines()
                 if line.startswith(("  FAIL:", "  ERROR:"))]
        self.assertEqual(named, [
            "  FAIL: test_beta (test_mod.TestB)",
            "  ERROR: test_gamma (test_mod.TestC)",
        ])
        self.assertIn("Failing tests named by the nested summary:", report)
        self.assertEqual(
            [line for line in report.splitlines()
             if line.startswith("Nested result line:")],
            ["Nested result line: FAILED (failures=1, errors=1)"],
            "the stderr result line was not extracted")
        self.assertIn("a test printed this on stdout", report)
        with open(os.path.join(self._diag, "suite.stdout.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), stdout)
        with open(os.path.join(self._diag, "suite.stderr.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), stderr,
                             "the complete stderr must stay verbatim")

    def test_report_deduplicates_headers_and_summary_across_streams(self):
        """Identical information in both streams is named once."""
        shared = "FAIL: test_shared (test_mod.TestShared)\n"
        stdout = (shared
                  + "FAIL: test_stdout_only (test_mod.TestS)\n"
                  + "FAILED (failures=2)\n")
        stderr = (shared
                  + "ERROR: test_stderr_only (test_mod.TestE)\n"
                  + "FAILED (failures=2)\n")
        report = self._rc._suite_failure_report(
            stdout, stderr, reason="reason-marker", diag_dir=self._diag)

        named = [line for line in report.splitlines()
                 if line.startswith(("  FAIL:", "  ERROR:"))]
        self.assertEqual(named, [
            "  FAIL: test_shared (test_mod.TestShared)",
            "  FAIL: test_stdout_only (test_mod.TestS)",
            "  ERROR: test_stderr_only (test_mod.TestE)",
        ])
        self.assertEqual(
            [line for line in report.splitlines()
             if line.startswith("Nested result line:")],
            ["Nested result line: FAILED (failures=2)"],
            "an identical result line present in both streams was "
            "reported twice")

    def test_report_preserves_full_streams_and_names_every_failure(self):
        # The early failure is > 20 KB from the end, so any fixed tail
        # window (the bug) cannot contain it. The late one is an ERROR,
        # to prove both header kinds are recognised.
        early = ("FAIL: test_early_breaks (test_mod.TestX)\n"
                 "Traceback (most recent call last):\n"
                 "  ... the diagnosis that used to be lost ...\n")
        filler = ("noise line\n" * 4000)
        late = ("ERROR: test_late_raises (test_mod.TestY)\n"
                "Traceback: late failure\n")
        stdout = early + filler + late + ("-" * 70 + "\n"
                                          "FAILED (failures=1, errors=1)\n")
        stderr = "stderr-marker: complete stream\n"
        report = self._rc._suite_failure_report(
            stdout, stderr, reason="reason-marker", diag_dir=self._diag)

        self.assertIn("reason-marker", report)
        self.assertIn("FAIL: test_early_breaks (test_mod.TestX)", report)
        self.assertIn("ERROR: test_late_raises (test_mod.TestY)", report)
        self.assertIn("Nested result line: FAILED (failures=1, errors=1)",
                      report)
        out_path = os.path.join(self._diag, "suite.stdout.txt")
        err_path = os.path.join(self._diag, "suite.stderr.txt")
        self.assertIn(out_path, report)
        self.assertIn(err_path, report)
        with open(out_path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), stdout,
                             "the preserved stdout must be VERBATIM, not "
                             "a clipped view")
        with open(err_path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), stderr)

    def test_report_is_best_effort_when_diag_dir_is_unwritable(self):
        # A regular file cannot contain a directory, so makedirs fails;
        # the report must still name the failure and carry the streams.
        blocker = os.path.join(self._diag, "blocker")
        with open(blocker, "w") as fh:
            fh.write("x")
        stdout = "FAIL: test_still_named (test_mod.TestZ)\n"
        report = self._rc._suite_failure_report(
            stdout, "err", reason="reason-marker",
            diag_dir=os.path.join(blocker, "diag"))
        self.assertIn("reason-marker", report)
        self.assertIn("FAIL: test_still_named (test_mod.TestZ)", report)
        self.assertIn("could not preserve full logs", report)
        self.assertIn("FAIL: test_still_named", report)

    def _run_check_tests(self, **run_kwargs):
        fake = mock.Mock(**run_kwargs)
        with mock.patch.object(self._rc.subprocess, "run", fake):
            with mock.patch.dict(os.environ,
                                 {self._rc.DIAG_DIR_ENV: self._diag}):
                with self.assertRaises(AssertionError) as cm:
                    self._rc.check_tests()
        return str(cm.exception), fake

    def test_check_tests_routes_nonzero_exit_through_report(self):
        stdout = ("FAIL: test_in_nested_suite (test_mod.TestA)\n"
                  + "x" * 20000 + "\nFAILED (failures=1)\n")
        msg, fake = self._run_check_tests(
            return_value=mock.Mock(returncode=1, stdout=stdout,
                                   stderr="nested-stderr-marker"))
        self.assertIn("the full suite failed (nested unittest exit 1)",
                      msg)
        self.assertIn("FAIL: test_in_nested_suite (test_mod.TestA)", msg)
        self.assertIn("nested-stderr-marker", msg)
        with open(os.path.join(self._diag, "suite.stdout.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), stdout)
        # Anti-recursion must still mark the child run.
        child_env = fake.call_args.kwargs["env"]
        self.assertEqual(child_env["FORKRUN_UNDER_RELEASE_CHECK"], "1")

    def test_check_tests_reports_stderr_only_unittest_output(self):
        """The gate's own path must surface stderr-written failures."""
        stdout = "only test prints land here\n"
        stderr = self._unittest_stderr()
        msg, fake = self._run_check_tests(
            return_value=mock.Mock(returncode=1, stdout=stdout,
                                   stderr=stderr))
        self.assertIn("the full suite failed (nested unittest exit 1)",
                      msg)
        self.assertIn("  FAIL: test_beta (test_mod.TestB)", msg)
        self.assertIn("  ERROR: test_gamma (test_mod.TestC)", msg)
        self.assertIn("Nested result line: FAILED (failures=1, errors=1)",
                      msg)
        with open(os.path.join(self._diag, "suite.stdout.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), stdout)
        with open(os.path.join(self._diag, "suite.stderr.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), stderr)
        child_env = fake.call_args.kwargs["env"]
        self.assertEqual(child_env["FORKRUN_UNDER_RELEASE_CHECK"], "1")

    def test_check_tests_routes_timeout_through_report(self):
        stdout = ("FAIL: test_hung (test_mod.TestH)\n"
                  + "y" * 12000 + "\npartial run\n")
        timeout_exc = subprocess.TimeoutExpired(
            cmd=[sys.executable, "-m", "unittest"], timeout=1,
            output=stdout, stderr="timeout-stderr-marker")
        msg, _fake = self._run_check_tests(side_effect=timeout_exc)
        self.assertIn("did not finish within", msg)
        self.assertIn("DEADLINE being reached", msg)
        self.assertIn("INCOMPLETE", msg)
        self.assertIn("FAIL: test_hung (test_mod.TestH)", msg)
        self.assertIn("timeout-stderr-marker", msg)
        with open(os.path.join(self._diag, "suite.stdout.txt"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read(), stdout,
                             "partial output at the deadline is evidence and "
                             "must be preserved in full")


def _stream_tail(stream, limit):
    """Tail of a str-or-bytes subprocess stream, decoded for messages."""
    if stream is None:
        return "(no output)"
    if isinstance(stream, bytes):
        stream = stream.decode("utf-8", "replace")
    if len(stream) <= limit:
        return stream
    return ("...[clipped; %d chars total]...\n" % len(stream)
            + stream[-limit:])


def _diag_snapshot(diag_dir, release_check, note=None):
    """Name the preserved nested logs and show their tails.

    The paths are the point: a CI run uploads this directory under
    `if: always()`, so the complete stdout/stderr survive even though
    this message must stay bounded. Reading them here also folds their
    tails into the assertion text for logs-only diagnosis.
    """
    lines = ["nested-suite diagnostics (%s=%s):"
             % (release_check.DIAG_DIR_ENV, diag_dir)]
    if note:
        lines.append("  note: %s" % note)
    found = False
    for name in ("suite.stdout.txt", "suite.stderr.txt"):
        path = os.path.join(diag_dir, name)
        if not os.path.exists(path):
            continue
        found = True
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            lines.append("  %s (unreadable: %s)" % (path, exc))
            continue
        lines.append("  %s (%d chars), tail:" % (path, len(text)))
        lines.append(_stream_tail(text, 8000))
    if not found:
        lines.append("  (no suite.stdout.txt/suite.stderr.txt preserved)")
    return "\n".join(lines)


if __name__ == "__main__":
    unittest.main()
