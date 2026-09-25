"""W-PY23 packaging v2: platform wheel, metadata, sdist, coherence.

Extends test_packaging.py (install cycle) with release-gate checks:
the wheel must be platform-tagged (never py3-none-any), METADATA
complete, the sdist self-contained (builds + installs from source),
and versions coherent (0.16.0 everywhere, v3.6.0 in the changelog).
The full release_check.py gate runs only on committed trees (it
asserts a clean tree, which a working tree cannot satisfy — it
skips there and runs on CI release branches).
"""

import glob
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

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


class TestWheelPlatform(unittest.TestCase):
    def test_platform_tag_helpers(self):
        """get_platform_tag: this platform tagged, others refused."""
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
            self.assertEqual(_setup_mod.get_platform_tag(),
                             "linux_%s" % this_machine)
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
            self.assertEqual(_setup_mod.get_platform_tag(),
                             "linux_aarch64")
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
            self.assertIn("linux_", name,
                          "wheel lacks platform tag: %s" % name)
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
                          "Requires-Python: >=3.8",
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
        self.assertEqual(forkrun.__version__, "0.16.0")

    def test_changelog_has_v3_6_0(self):
        with open(os.path.join(REPO_ROOT, "DOCS",
                               "CHANGELOG.md")) as fh:
            content = fh.read()
        self.assertIn("v3.6.0", content)
        self.assertIn("0.16.0", content)

    def test_readme_matches_version(self):
        with open(os.path.join(REPO_ROOT, "python",
                               "README.md")) as fh:
            content = fh.read()
        self.assertIn(forkrun.__version__, content)


class TestReleaseChecklist(unittest.TestCase):
    def test_release_check_passes(self):
        """release_check.py all-pass — only on committed trees.

        The checklist asserts a clean tree, which a working tree
        cannot satisfy by construction; it skips there and runs
        fully on CI release branches / pre-tag checkouts.
        Skips too when running UNDER release_check itself
        (FORKRUN_UNDER_RELEASE_CHECK — otherwise the checklist's
        own suite run would re-invoke the checklist without
        bound).
        """
        if os.environ.get("FORKRUN_UNDER_RELEASE_CHECK"):
            self.skipTest("running under release_check — no recursion")
            return
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=60, cwd=REPO_ROOT)
        if proc.stdout.strip():
            self.skipTest("tree dirty — checklist runs pre-tag only")
            return
        proc = subprocess.run(
            [sys.executable, "python/release_check.py"],
            capture_output=True, text=True, timeout=1500, cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0,
                         "release checklist failed:\n%s\n%s"
                         % (proc.stdout[-3000:], proc.stderr[-1000:]))
        self.assertIn("ALL CHECKS PASSED", proc.stdout)


if __name__ == "__main__":
    unittest.main()
