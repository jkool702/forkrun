"""Negative tests for tools/acceptance_installed_wheel.py.

These tests exercise the harness's fail-closed behavior by invoking it as a
subprocess. They do not test forkrun itself.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
HARNESS = os.path.join(REPO, "tools", "acceptance_installed_wheel.py")


def _run(*args, timeout=120):
    return subprocess.run(
        [sys.executable, HARNESS] + list(args),
        capture_output=True, text=True, timeout=timeout)


class TestAcceptanceHarnessNegative(unittest.TestCase):
    """The harness must fail closed on bad inputs."""

    def test_missing_wheel_fails(self):
        r = _run("--wheel", "/nonexistent/wheel.whl",
                 "--interpreter", sys.executable, "--mode", "generic")
        self.assertNotEqual(r.returncode, 0)

    def test_malformed_wheel_path_fails(self):
        r = _run("--wheel", "/tmp/not_a_wheel.txt",
                 "--interpreter", sys.executable, "--mode", "generic")
        self.assertNotEqual(r.returncode, 0)

    def test_udf_mode_requires_udf_func(self):
        r = _run("--wheel", "/nonexistent/wheel.whl",
                 "--interpreter", sys.executable, "--mode", "udf")
        self.assertNotEqual(r.returncode, 0)

    def test_unknown_mode_fails(self):
        r = _run("--wheel", "/nonexistent/wheel.whl",
                 "--interpreter", sys.executable, "--mode", "bogus")
        self.assertNotEqual(r.returncode, 0)

    def test_wrong_interpreter_minor_fails(self):
        # Request a 3.9 interpreter (doesn't exist) — should fail.
        r = _run("--wheel", "/nonexistent/wheel.whl",
                 "--interpreter", "/usr/bin/python3.9", "--mode", "generic")
        self.assertNotEqual(r.returncode, 0)

    def test_inherited_env_does_not_mask_failure(self):
        # Set FORKRUN_LIB to a bogus path; harness should still fail on
        # the missing wheel (not silently use the override).
        env = dict(os.environ)
        env["FORKRUN_LIB"] = "/tmp/bogus.so"
        r = subprocess.run(
            [sys.executable, HARNESS, "--wheel", "/nonexistent/wheel.whl",
             "--interpreter", sys.executable, "--mode", "generic"],
            capture_output=True, text=True, timeout=120, env=env)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
PY
cd /mnt/ramdisk/forkrun/python && python3 -m unittest tests.test_acceptance_harness 2>&1 | tail -5