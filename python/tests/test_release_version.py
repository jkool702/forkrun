"""F-PORT5: release-gate version coherence (P26).

release_check.py never verified the ENGINE version (wheel-vs-local
drift passed silently) nor the META mapping. Lock-ins invoke the
new checks directly (no clean tree needed); the full checklist
runs pre-tag via TestReleaseChecklist.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "python"))

import release_check  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _check_by_name(prefix):
    for name, fn in release_check.CHECKS:
        if name.startswith(prefix):
            return fn
    raise AssertionError("check not found: %s" % prefix)


class TestReleaseVersionGates(unittest.TestCase):
    def test_meta_mapping(self):
        fn = _check_by_name("Version: META maps")
        self.assertTrue(fn())

    @unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
    def test_built_engine_matches(self):
        fn = _check_by_name("Version: built engine is")
        self.assertTrue(fn())

    @unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
    def test_so_helper_reads_local_substrate(self):
        from release_check import (PROJECT_VERSION,
                                   _so_engine_version)  # noqa: E402
        self.assertEqual(_so_engine_version(find_substrate()),
                         PROJECT_VERSION)

    @unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
    def test_wheel_embedded_so_matches(self):
        fn = _check_by_name("Wheel: embedded .so reports")
        self.assertTrue(fn())


if __name__ == "__main__":
    unittest.main()
