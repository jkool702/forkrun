"""W-REL5-C lock-in bites (behavioral, deterministic unless noted).

C1/C2/C3/C4/C5 ×5 deterministic; C6/C7/C9 timing ×10 (in-test loops).
Each test asserts post-fix behavior; pre-fix failures were demonstrated
by stashing the fix (see commit messages / wave report).
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from forkrun import _bindings as _b  # noqa: E402
from _helpers import assert_no_zombies  # noqa: E402

try:
    _b.find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestC1NoCwdDlopen(unittest.TestCase):
    """C1 (M12): a CWD-planted .so must never load."""

    def test_candidates_never_cwd_anchored(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                cands = _b._substrate_candidates()
                for cand in cands:
                    self.assertFalse(
                        os.path.abspath(cand).startswith(
                            os.path.abspath(tmp) + os.sep),
                        "CWD-anchored candidate: %r" % (cand,))
            finally:
                os.chdir(old)

    def test_hostile_cwd_so_refused(self):
        # Hostile lib in CWD, co-located real ones masked: pre-fix
        # returned the hostile path; post-fix raises FileNotFoundError.
        with tempfile.TemporaryDirectory() as tmp:
            hostile = os.path.join(tmp, "libforkrun_python.so")
            with open(hostile, "wb") as fh:
                fh.write(b"not a real substrate")
            real_exists = os.path.exists

            def _masked(path):
                if os.path.abspath(str(path)).startswith(
                        os.path.abspath(tmp) + os.sep):
                    return True  # the hostile file exists...
                if str(path).endswith("libforkrun_python.so"):
                    return False  # ...but no co-located real one does
                return real_exists(path)

            old = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.object(os.path, "exists",
                                       side_effect=_masked):
                    with self.assertRaises(FileNotFoundError):
                        _b.find_substrate()
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
