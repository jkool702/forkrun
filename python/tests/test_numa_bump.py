"""W-NUMA2: parent guarantees >= 1 worker per NUMA node.

Under-provisioned pools (workers < nodes) strand born-local rings
(RESILIENCE §7.3.1). The parent bumps the effective count to the
node count with one UserWarning instead of running short. Tests
use nodes="@4" (forced-logical, real per-node machinery on any
box). Correctness compares line multisets / joined bytes, never
blob identity (per-node batching varies run to run).
"""

import os
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun._numa import distribute_workers  # noqa: E402
from forkrun.run import _resolve_workers_numa  # noqa: E402

from _helpers import assert_no_zombies, joined_bytes  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

NODES_4 = "@4"


def _up(batch):
    return bytes(batch.data).upper()


def _make_input(n=3000):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    with open(path, "w") as fh:
        for i in range(n):
            fh.write("line %06d abcdef\n" % i)
    return path


def _map_warn(payload, path, **kw):
    """forkrun.map capturing UserWarnings (returns (out, warns))."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", UserWarning)
        out = forkrun.map(payload, path, output="bytes", **kw)
    warns = [w for w in caught
             if issubclass(w.category, UserWarning)
             and "raised to" in str(w.message)]
    return out, warns


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestNumaWorkerBump(unittest.TestCase):
    def test_workers_bumped_to_node_count(self):
        # workers=1 on @4: completes exact, warns once with counts.
        path = _make_input()
        try:
            out, warns = _map_warn(_up, path, workers=1,
                                   order="index", nodes=NODES_4)
            ref = forkrun.map(_up, path, workers=8, order="index",
                              nodes=1)
            self.assertEqual(joined_bytes(out), joined_bytes(ref))
            self.assertEqual(len(warns), 1)
            self.assertIn("workers=1", str(warns[0].message))
            self.assertIn("raised to 4", str(warns[0].message))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_workers_equal_nodes_no_warning(self):
        path = _make_input()
        try:
            out, warns = _map_warn(_up, path, workers=4,
                                   order="index", nodes=NODES_4)
            ref = forkrun.map(_up, path, workers=8, order="index",
                              nodes=1)
            self.assertEqual(joined_bytes(out), joined_bytes(ref))
            self.assertEqual(warns, [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_workers_above_nodes_no_warning(self):
        path = _make_input()
        try:
            out, warns = _map_warn(_up, path, workers=8,
                                   order="index", nodes=NODES_4)
            ref = forkrun.map(_up, path, workers=8, order="index",
                              nodes=1)
            self.assertEqual(joined_bytes(out), joined_bytes(ref))
            self.assertEqual(warns, [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_bump_uma_exempt(self):
        path = _make_input()
        try:
            out, warns = _map_warn(_up, path, workers=1,
                                   order="index", nodes=1)
            self.assertEqual(warns, [])
            self.assertTrue(sum(b.count(b"\n") for b in out) == 3000)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_bumped_run_drain_guard_quiet(self):
        # F-NUMA1 interaction: the bumped run must complete without
        # the drain guard firing (no RuntimeError, exact output).
        path = _make_input()
        try:
            out, _ = _map_warn(_up, path, workers=2,
                               order="index", nodes=NODES_4)
            ref = forkrun.map(_up, path, workers=8, order="index",
                              nodes=1)
            self.assertEqual(joined_bytes(out), joined_bytes(ref))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_distribution_floor_unit(self):
        # First-N one-per-node is structural in distribute_workers;
        # lock it (workers >= nodes covers all nodes by construction).
        for total, nodes in ((4, 4), (5, 4), (6, 4), (7, 3), (28, 4)):
            dist = dict(distribute_workers(total, nodes))
            for n in range(nodes):
                self.assertGreaterEqual(dist.get(n, 0), 1)
        # Resolver unit checks (no engine): bump, idempotent, exempt.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self.assertEqual(_resolve_workers_numa(1, 4), 4)
            self.assertEqual(_resolve_workers_numa(4, 4), 4)
            self.assertEqual(_resolve_workers_numa(8, 4), 8)
            self.assertEqual(_resolve_workers_numa(1, 1), 1)
            self.assertEqual(_resolve_workers_numa(None, 1) >= 1, True)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", UserWarning)
            self.assertEqual(_resolve_workers_numa(2, 4), 4)
            self.assertEqual(_resolve_workers_numa(4, 4), 4)
        bumped = [w for w in caught
                  if "raised to" in str(w.message)]
        self.assertEqual(len(bumped), 1)

    def test_stream_bumped_path(self):
        # stream() over NUMA with workers=1: same guarantee through
        # the generator path (warning fires on first drain).
        path = _make_input()
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", UserWarning)
                out = list(forkrun.stream(_up, path, workers=1,
                                          order="index", nodes=NODES_4))
            warns = [w for w in caught
                     if issubclass(w.category, UserWarning)
                     and "raised to" in str(w.message)]
            ref = forkrun.map(_up, path, workers=8, order="index",
                              nodes=1)
            self.assertEqual(joined_bytes(out), joined_bytes(ref))
            self.assertEqual(len(warns), 1)
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
