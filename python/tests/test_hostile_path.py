"""F-PORT4: hostile-PATH handling in spawn/plugin paths (P25, D10-class).

Bash D10: extraction/re-render shells run with PATH at a fresh
mktemp-ud dir (constructed environment, never the caller PATH).
Python inherited the caller PATH unsanitized: subprocess.run argv
and posix_spawnp PATH lookup, plus CWD-relative CDLL loads.
"""

import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun._plugin import PluginError, load_plugin  # noqa: E402
from forkrun._spawn import make_spawn_payload  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


class TestSpawnPathPinning(unittest.TestCase):
    def setUp(self):
        self._saved_path = os.environ.get("PATH")
        self._tmp = tempfile.mkdtemp(prefix="forkrun_hostile_")
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def tearDown(self):
        if self._saved_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self._saved_path

    def _plant(self, name, body="#!/bin/sh\necho PWNED\n"):
        planted = os.path.join(self._tmp, name)
        with open(planted, "w") as fh:
            fh.write(body)
        os.chmod(planted, os.stat(planted).st_mode | stat.S_IXUSR
                 | stat.S_IXGRP | stat.S_IXOTH)
        return planted

    def test_bare_name_ignores_hostile_path(self):
        # A CWD/PATH-planted 'winnow' must never be selected: either
        # the system copy (absolute) or the unchanged bare name
        # (lazy payload-time SpawnError for truly-missing commands).
        planted = self._plant("forkrun_winnow_xyz_123")
        os.environ["PATH"] = self._tmp + os.pathsep + (
            self._saved_path or "")
        payload = make_spawn_payload("forkrun_winnow_xyz_123")
        self.assertNotEqual(payload._forkrun_spawn_argv[0], planted)
        self.assertEqual(payload._forkrun_spawn_argv[0],
                         "forkrun_winnow_xyz_123")

    def test_system_command_resolves_absolute(self):
        cat = shutil.which("cat", path=os.defpath)
        self.assertIsNotNone(cat)  # test env must have cat on defpath
        os.environ["PATH"] = self._tmp + os.pathsep + (
            self._saved_path or "")
        payload = make_spawn_payload("cat")
        self.assertEqual(payload._forkrun_spawn_argv[0], cat)
        self.assertTrue(os.path.isabs(payload._forkrun_spawn_argv[0]))

    @unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
    def test_hostile_cat_does_not_execute(self):
        # End-to-end: hostile 'cat' first on PATH must not run.
        self._plant("cat")
        os.environ["PATH"] = self._tmp + os.pathsep + (
            self._saved_path or "")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 200)
            out = forkrun.map("cat", path, mode="spawn", workers=1,
                              nodes=1)
            with open(path, "rb") as fh:
                want = b"".join(fh.read().splitlines(keepends=True))
            self.assertEqual(b"".join(out), want)
            assert_no_zombies(self)
        finally:
            os.unlink(path)


class TestPluginPathGate(unittest.TestCase):
    def test_bare_filename_rejected(self):
        with self.assertRaisesRegex(PluginError, "must contain '/'"):
            load_plugin("planted_xyz.so", "func")

    def test_absolute_missing_still_not_found(self):
        with self.assertRaisesRegex(PluginError, "not found"):
            load_plugin("/nonexistent/path_xyz.so", "func")


if __name__ == "__main__":
    unittest.main()
