"""F-PORT1: FORKRUN_RETRY_LIMIT is honored (not hardcoded 3).

The Bash frontend reads FORKRUN_RETRY_LIMIT at worker init
(ring_worker inc -> g_fr_config.retry_limit); the Python port
hardcoded 3 at all 7 init sites, making 0/<0/custom unreachable
despite CONFIGURATION.md/FAULT_TOLERANCE.md documenting the env.
Single normalization point: forkrun._api._resolve_retry_limit().
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._api import _resolve_retry_limit  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


class TestResolveRetryLimit(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("FORKRUN_RETRY_LIMIT")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("FORKRUN_RETRY_LIMIT", None)
        else:
            os.environ["FORKRUN_RETRY_LIMIT"] = self._saved

    def test_default_is_3(self):
        os.environ.pop("FORKRUN_RETRY_LIMIT", None)
        self.assertEqual(_resolve_retry_limit(), 3)

    def test_empty_is_default(self):
        os.environ["FORKRUN_RETRY_LIMIT"] = ""
        self.assertEqual(_resolve_retry_limit(), 3)

    def test_custom_values(self):
        for raw, want in (("0", 0), ("1", 1), ("5", 5), ("-1", -1)):
            os.environ["FORKRUN_RETRY_LIMIT"] = raw
            self.assertEqual(_resolve_retry_limit(), want,
                             "FORKRUN_RETRY_LIMIT=%r" % raw)

    def test_invalid_raises_fail_closed(self):
        for raw in ("abc", "3.5", "  "):
            os.environ["FORKRUN_RETRY_LIMIT"] = raw
            with self.assertRaises(ValueError):
                _resolve_retry_limit()


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestRetryLimitEndToEnd(unittest.TestCase):
    def _run_counted_failures(self, limit):
        """Fail every batch; return payload execution count.

        Counter is a file (workers are forked processes — in-memory
        counters never propagate to the parent).
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        counter = path + ".count"
        try:
            write_lines(path, 1000)
            open(counter, "w").close()

            def always_fail(batch):
                with open(counter, "a") as cfh:
                    cfh.write("x")
                raise ValueError("boom")

            saved = os.environ.get("FORKRUN_RETRY_LIMIT")
            try:
                if limit is None:
                    os.environ.pop("FORKRUN_RETRY_LIMIT", None)
                else:
                    os.environ["FORKRUN_RETRY_LIMIT"] = str(limit)
                out = forkrun.map(always_fail, path, workers=1,
                                  nodes=1, lines=500)
            finally:
                if saved is None:
                    os.environ.pop("FORKRUN_RETRY_LIMIT", None)
                else:
                    os.environ["FORKRUN_RETRY_LIMIT"] = saved
            self.assertEqual(out, [])
            with open(counter) as cfh:
                return len(cfh.read())
        finally:
            os.unlink(path)
            if os.path.exists(counter):
                os.unlink(counter)

    def test_limit_zero_poisons_first_try(self):
        # 1000 lines / lines=500 = 2 batches; limit 0 = exactly-once:
        # each batch executes exactly once (no retries).
        self.assertEqual(self._run_counted_failures(0), 2)

    def test_default_retries_three_times(self):
        # Default 3 = up to 3 executions per batch: 2 batches x 3.
        self.assertEqual(self._run_counted_failures(None), 6)

    def test_no_zombies(self):
        assert_no_zombies(self)


if __name__ == "__main__":
    unittest.main()
