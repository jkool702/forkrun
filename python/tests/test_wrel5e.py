"""W-REL5-E-PYTHON lock-in bites (E5 import-surface, E15 probe).

E6/E7 are non-behavioral (evidence: failing-grep/typecheck notes in
the commits). Each behavioral bite demonstrated pre-fix failing
(stash the fix — see wave report).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402

try:
    from forkrun._bindings import find_substrate  # noqa: E402
    find_substrate()
    HAVE_LIB = True
except (FileNotFoundError, ImportError):
    HAVE_LIB = False


class TestE5NoRunConfigExport(unittest.TestCase):
    """E5: RunConfig must not be importable from the top level."""

    def test_not_in_all(self):
        self.assertNotIn("RunConfig", forkrun.__all__)

    def test_import_raises(self):
        for _ in range(5):
            with self.assertRaises(ImportError):
                exec("from forkrun import RunConfig", {})

    def test_validate_seam_intact(self):
        # The _validate_config test seam still produces the class
        # internally (no collateral from the export drop).
        cfg = forkrun._validate_config(
            "pkg.mod:func", "/tmp/in.txt", mode="python", sink=None,
            order="none", lines=None, bytes_=None, workers=None,
            nodes=1, on_error="retry", streaming=None, resume=None,
            checkpoint_file=None, strict_poison=False,
            signal_policy="default")
        self.assertIsNone(cfg.bytes)
        self.assertEqual(cfg.signal_policy, "default")


if __name__ == "__main__":
    unittest.main()
