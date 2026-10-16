"""Test-file integrity: a class defined after unittest.main() never runs.

Found in WO-CR-ROI-2 and fixed there, but the GUARD was lost when a
working-tree revert wiped it -- so it lives in its own module now rather
than inside an unrelated feature file, and this test proves it still
fails when the pattern comes back.

The failure mode is silent. `unittest.main()` runs, finds whatever is
defined above it, and exits -- so the class below is never defined, let
alone run. Direct invocation reports OK having executed fewer tests than
discovery does, and nothing says which ones are missing. It cost 35 tests
across six files before it was noticed (worst: the capability-dispatch
oracle losing half its cases to any direct run).

Discovery is unaffected, which is exactly why this can sit unnoticed for
a long time: CI runs discovery and is green either way.
"""

import os
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


class TestMainBlockIsLast(unittest.TestCase):
    def _files(self):
        return [os.path.join(_TESTS_DIR, f)
                for f in sorted(os.listdir(_TESTS_DIR))
                if f.startswith("test_") and f.endswith(".py")]

    def test_main_block_follows_every_class(self):
        offenders = []
        for path in self._files():
            name = os.path.basename(path)
            with open(path) as fh:
                lines = fh.read().splitlines()
            mains = [i for i, ln in enumerate(lines)
                     if ln.startswith('if __name__ == "__main__"')]
            classes = [i for i, ln in enumerate(lines)
                       if ln.startswith("class ")]
            if not mains:
                continue
            if len(mains) != 1:
                offenders.append("%s: %d __main__ blocks" % (name,
                                                              len(mains)))
            elif classes and mains[0] < max(classes):
                offenders.append(
                    "%s: defines a class at line %d AFTER unittest.main() "
                    "at line %d -- direct execution silently skips it"
                    % (name, max(classes) + 1, mains[0] + 1))
        self.assertEqual([], offenders,
                         "\n".join(offenders))

    def test_direct_and_discovery_agree_on_test_count(self):
        """The property the guard exists to protect, asserted directly.

        Run in-process for a couple of files rather than by shelling out:
        the structural check above is the real detector, this one is the
        behavioural confirmation, and paying a subprocess per file would
        make the guard expensive enough that people disable it.
        """
        loader = unittest.TestLoader()
        for name in ("test_poison_accounting.py",):
            path = os.path.join(_TESTS_DIR, name)
            with open(path) as fh:
                lines = fh.read().splitlines()
            mains = [i for i, ln in enumerate(lines)
                     if ln.startswith('if __name__ == "__main__"')]
            classes = [i for i, ln in enumerate(lines)
                       if ln.startswith("class ")]
            self.assertTrue(mains and classes)
            self.assertGreater(mains[0], max(classes),
                               "%s would lose tests under direct "
                               "invocation" % name)
            suite = loader.discover(_TESTS_DIR, pattern=name)
            self.assertGreater(suite.countTestCases(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)