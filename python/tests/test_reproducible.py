"""W-PY23 reproducible builds: same source + compiler = identical .so.

The substrate embeds wall-clock (__DATE__/__TIME__ in the frozen
engine version output) and paths (__FILE__) by default; the
Makefile pins both via build flags (macro override + prefix map)
and drops the build-id. These tests lock that in.
"""

import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
MAKEFILE = os.path.join(REPO_ROOT, "Makefile.substrate")


class TestReproducibleBuild(unittest.TestCase):
    def test_two_builds_identical(self):
        """Two consecutive substrate builds are byte-identical."""
        proc = subprocess.run(
            ["make", "-f", MAKEFILE, "reproducibility-check"],
            capture_output=True, text=True, timeout=900, cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0,
                         "builds differ:\n%s\n%s"
                         % (proc.stdout[-2000:], proc.stderr[-2000:]))
        self.assertIn("REPRODUCIBLE", proc.stdout)

    def test_ccstamp_tracks_compiler(self):
        """CCSTAMP exists and captures the compiler identity."""
        stamp = os.path.join(REPO_ROOT, ".canary-cc")
        self.assertTrue(os.path.exists(stamp),
                        ".canary-cc missing — build at least once")
        with open(stamp) as fh:
            content = fh.read().strip()
        self.assertTrue(content, ".canary-cc is empty")
        # Compiler identity line looks like "gcc :: -O1 ..." (CCSTAMP
        # recipe prints '$(CC) :: $(CFLAGS)').
        self.assertIn("::", content)

    def test_no_build_id(self):
        """The shipped .so carries no build-id note (link variance)."""
        so_path = os.path.join(REPO_ROOT, "python", "forkrun",
                               "libforkrun_python.so")
        if not os.path.exists(so_path):
            self.skipTest("substrate not built")
            return
        proc = subprocess.run(
            ["readelf", "--notes", so_path],
            capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            self.skipTest("readelf unavailable")
            return
        self.assertNotIn("NT_GNU_BUILD_ID", proc.stdout)

    def test_pinned_date_strings(self):
        """__DATE__/__TIME__ expand to the pinned values, not today."""
        so_path = os.path.join(REPO_ROOT, "python", "forkrun",
                               "libforkrun_python.so")
        if not os.path.exists(so_path):
            self.skipTest("substrate not built")
            return
        proc = subprocess.run(
            ["strings", so_path],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0)
        # Pinned values present; today's date must not leak in.
        self.assertIn("Sep  1 2026", proc.stdout)
        import datetime
        today = datetime.date.today().strftime("%b %d %Y")
        if today != "Sep  1 2026":
            self.assertNotIn(today, proc.stdout)


if __name__ == "__main__":
    unittest.main()
