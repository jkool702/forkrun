"""W-REL5-E-PYTHON lock-in bites (E5 import-surface, E15 probe).

E6/E7 are non-behavioral (evidence: failing-grep/typecheck notes in
the commits). Each behavioral bite demonstrated pre-fix failing
(stash the fix — see wave report).
"""

import os
import sys
import tempfile
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


def _nfd():
    return len(os.listdir("/proc/self/fd"))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestE15TeardownHygiene(unittest.TestCase):
    """E15 (M19 completion): no stale numbers reach teardown; fds stable.

    Audit (see wave report) classified every close in run.py:
    nulled / flag-nulled (must_close) / member-nulled loops /
    rebind-before-use loop vars / terminal (child _exit, function
    end, teardown-internal with no intervening opens). These probes
    lock that in: order_w arrives None at teardown (the recycled-
    descriptor path), and fd counts are stable across mixed runs.
    """

    def test_order_w_none_at_teardown(self):
        import sys as _sys  # noqa: PLC0415
        from unittest import mock as _mock  # noqa: PLC0415
        from _helpers import (  # noqa: PLC0415
            assert_no_zombies, write_lines)

        _run_mod = _sys.modules["forkrun.run"]
        seen = []
        real = _run_mod._teardown_reactor

        def _spy(lib, state, **kw):
            seen.append(kw.get("order_w", "absent"))
            return real(lib, state, **kw)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 200)

            def _up(batch):
                return bytes(batch.data)

            for _ in range(5):
                del seen[:]
                with _mock.patch.object(_run_mod, "_teardown_reactor",
                                        side_effect=_spy):
                    out = forkrun.map(
                        _up, path, workers=2, nodes=1, order="index")
                self.assertTrue(out)
                self.assertTrue(seen)
                for val in seen:
                    self.assertIsNone(
                        val, "stale order_w passed to teardown: %r"
                        % (val,))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_fd_stable_across_mixed_runs(self):
        from _helpers import (  # noqa: PLC0415
            assert_no_zombies, write_lines)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 200)

            def _up(batch):
                return bytes(batch.data)

            import gc as _gc  # noqa: PLC0415
            # Warmup (allocator/mmap caches), then baseline.
            forkrun.map(_up, path, workers=1, nodes=1)
            _gc.collect()
            base = _nfd()
            for i in range(10):
                forkrun.map(_up, path, workers=2, nodes=1,
                            order="index", c_drain=True)
                list(forkrun.stream(_up, path, workers=2, nodes=1))
                forkrun.map(_up, path, workers=2, nodes=1,
                            streaming=True)
                _gc.collect()
                self.assertEqual(_nfd(), base,
                                 "fd drift after mixed loop %d" % i)
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
