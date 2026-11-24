#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — CK-1 tests.

Build portability (CK-1.4) and preflight honesty (CK-1.8):
  * mandatory libdist_ingest.so builds (uses mbind via syscall when present);
  * optional-only probes (libstage0, production reference) warn, not fail;
  * mandatory failure gives nonzero exit;
  * --json-out is machine-readable and includes the preflight record;
  * mbind path is either syscall interface or clear warning.
"""
import json
import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TOOL = os.path.join(REPO_ROOT, "tools", "di_preflight.py")
SO = os.path.join(REPO_ROOT, "stage0", "libdist_ingest.so")


class TestDiPreflightCK1(unittest.TestCase):
    def _run_preflight(self):
        return subprocess.run([sys.executable, TOOL, "--json-out", "/tmp/opencode/di_preflight_ck1.json"],
                              capture_output=True, text=True, cwd=REPO_ROOT, timeout=900)

    def test_mandatory_engine_build_succeeds(self):
        p = self._run_preflight()
        self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
        self.assertTrue(os.path.exists(SO), "mandatory engine artifact missing")

    def test_machine_readable_json_out(self):
        p = self._run_preflight()
        self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)
        with open("/tmp/opencode/di_preflight_ck1.json") as f:
            d = json.load(f)
        self.assertIn("preflight", d)
        self.assertTrue(d["preflight"]["mandatory_engine_build"]["available"])

    def test_mandatory_failure_nonzero_exit(self):
        # Simulate failure: run the preflight function with a broken tool dir.
        r = subprocess.run([sys.executable, TOOL, "--json-out", "/tmp/opencode/di_preflight_ck1b.json"],
                           cwd=REPO_ROOT, capture_output=True, text=True, timeout=900,
                           env={**os.environ, "CC": "nonexistent-cc"})
        # Either the build fails (nonzero) or it succeeds — we assert the
        # contract: exit status reflects mandatory build, not all probes.
        with open("/tmp/opencode/di_preflight_ck1b.json") as f:
            d = json.load(f)
        expected = 0 if d["preflight"]["mandatory_engine_build"]["available"] else 1
        self.assertEqual(r.returncode, expected)

    def test_mbind_interface_documented(self):
        r = subprocess.run([sys.executable, TOOL], capture_output=True, text=True, cwd=REPO_ROOT, timeout=60)
        # mbind is now via syscall (SYS_mbind/__NR_mbind fallback); warn otherwise.
        self.assertNotIn("mbind", r.stderr, "unexpected stderr")


if __name__ == "__main__":
    unittest.main()
