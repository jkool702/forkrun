"""W-PY10 packaging tests: installability without touching the engine.

Covers: Linux import + guard (faked platform in a subprocess), version
single-sourcing (setup.py --version vs runtime), in-place .so presence,
and a true pip-wheel → isolated-target → subprocess-run cycle.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

_FAKE_PLATFORM_DRIVER = "\n".join([
    "import sys",
    "sys.platform = 'darwin'",
    "sys.path.insert(0, 'python')",
    "try:",
    "    import forkrun",
    "except ImportError as e:",
    "    assert 'Linux' in str(e), str(e)",
    "    sys.exit(0)",
    "sys.exit(1)",
])


class TestPackaging(unittest.TestCase):
    def test_import_linux(self):
        self.assertTrue(hasattr(forkrun, "run"))
        self.assertTrue(hasattr(forkrun, "map"))
        self.assertTrue(hasattr(forkrun, "stream"))

    def test_linux_only_guard(self):
        proc = subprocess.run(
            [sys.executable, "-c", _FAKE_PLATFORM_DRIVER],
            capture_output=True, text=True, timeout=120, cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0,
                         "non-Linux import must fail cleanly:\n%s"
                         % proc.stderr)

    def test_version_single_sourced(self):
        proc = subprocess.run(
            [sys.executable, "setup.py", "--version"],
            capture_output=True, text=True, timeout=120, cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), forkrun.__version__)
        self.assertEqual(forkrun.__version__, "0.10.0")

    def test_so_present_in_place(self):
        pkg_dir = os.path.dirname(os.path.abspath(forkrun.__file__))
        so_path = os.path.join(pkg_dir, "libforkrun_python.so")
        self.assertTrue(os.path.exists(so_path), so_path)

    def test_pip_install_and_run(self):
        # True install cycle: wheel -> isolated target -> subprocess run
        # with cwd outside the repo (repo tree must not shadow). Skips
        # where the pip toolchain is absent (CI installs it; see
        # python-check.yml) rather than failing on packaging infra.
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                capture_output=True, check=True, timeout=60)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("no pip toolchain")
            return
        workdir = tempfile.mkdtemp(prefix="forkrun_pkg_")
        try:
            wheel = subprocess.run(
                [sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
                 "-w", workdir],
                capture_output=True, text=True, timeout=600, cwd=REPO_ROOT)
            self.assertEqual(wheel.returncode, 0, wheel.stderr[-2000:])
            target = os.path.join(workdir, "target")
            os.mkdir(target)
            install = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--no-deps",
                 "--target", target, "--no-index", "--find-links", workdir,
                 "forkrun"],
                capture_output=True, text=True, timeout=600, cwd=REPO_ROOT)
            self.assertEqual(install.returncode, 0,
                             install.stderr[-2000:])
            inp = os.path.join(workdir, "in.txt")
            with open(inp, "w") as fh:
                for i in range(500):
                    fh.write("line %d\n" % i)
            driver = "\n".join([
                "import sys",
                "sys.path.insert(0, %r)" % target,
                "import forkrun",
                "assert 'target' in forkrun.__file__, forkrun.__file__",
                "out = forkrun.map(lambda b: bytes(b.data), %r, "
                "workers=2, order='index')" % inp,
                "assert b''.join(out) == open(%r, 'rb').read()" % inp,
                "print('INSTALLED-OK')",
            ])
            env = dict(os.environ)
            env["PYTHONPATH"] = target
            run = subprocess.run(
                [sys.executable, "-c", driver],
                capture_output=True, text=True, timeout=300,
                cwd=workdir, env=env)
            self.assertEqual(run.returncode, 0,
                             "installed run failed:\n%s\n%s"
                             % (run.stdout, run.stderr[-2000:]))
            self.assertIn("INSTALLED-OK", run.stdout)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
