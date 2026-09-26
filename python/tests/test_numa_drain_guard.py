"""F-NUMA1 drain guard: per-node read_idx == write_idx before success.

The parent's NUMA completion path must refuse silent partial
completion: any node holding unclaimed published batches (with a
non-empty tail) raises RuntimeError naming the node and indices.
A node whose only unclaimed work is an empty tail (EOF sentinel /
zero-length tail: never counted by the fork gate, never claimed,
contributes no output) is vacuous, not a violation. Missing
telemetry symbol (pre-diagnostic .so) disarms silently.

These tests drive forkrun.run._numa_drain_audit with a stub lib
(no engine needed); live NUMA coverage stays in test_numa.py.
"""

import ctypes
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from forkrun.run import _numa_drain_audit  # noqa: E402


class _StubDiag:
    """Stand-in for lib.fr_py_diag_node (out-param ctypes array)."""

    def __init__(self, rows):
        # rows: node -> (write, read, finished, chunk_head,
        # chunk_tail, tail_empty) or None (rc -1).
        self._rows = rows

    def __call__(self, node, arr):
        row = self._rows.get(node)
        if row is None:
            return -1
        for i, v in enumerate(row):
            arr[i] = v
        return 0


class _StubLib:
    def __init__(self, rows):
        self.fr_py_diag_node = _StubDiag(rows)


def _clean_rows(n=4, base=100):
    return {i: (base + i, base + i, 1, 10 + i, 10 + i, 1)
            for i in range(n)}


class TestNumaDrainAudit(unittest.TestCase):
    def test_clean_passes_silently(self):
        lib = _StubLib(_clean_rows())
        # Must not raise; must not write (DIAG env unset here).
        _numa_drain_audit(lib, 4, {0, 1, 2, 3},
                          [0] * 7 + [1] * 7 + [2] * 7 + [3] * 7,
                          28, label="map/run")

    def test_violation_raises_naming_node(self):
        rows = _clean_rows()
        rows[2] = (150, 100, 1, 12, 12, 0)  # 50 unclaimed, non-empty
        lib = _StubLib(rows)
        with self.assertRaises(RuntimeError) as ctx:
            _numa_drain_audit(lib, 4, {0, 1, 2, 3},
                              [0] * 7 + [1] * 7 + [2] * 7 + [3] * 7,
                              28, label="map/run")
        msg = str(ctx.exception)
        self.assertIn("node 2", msg)
        self.assertIn("150", msg)
        self.assertIn("100", msg)

    def test_empty_tail_is_vacuous(self):
        # write != read but every unclaimed slot empty (sentinel-only
        # node that never forked workers): complete output, no raise.
        rows = _clean_rows()
        rows[3] = (1, 0, 1, 1, 1, 1)
        lib = _StubLib(rows)
        _numa_drain_audit(lib, 4, {0, 1, 2},
                          [0] * 7 + [1] * 7 + [2] * 7 + [3] * 7,
                          28, label="map/run")

    def test_missing_symbol_disarms(self):
        lib = object()  # no fr_py_diag_node at all
        _numa_drain_audit(lib, 4, {0, 1, 2, 3}, [0] * 28,
                          28, label="map/run")

    def test_diag_unavailable_rows_skip(self):
        lib = _StubLib({})  # every node rc -1
        _numa_drain_audit(lib, 2, {0, 1}, [0, 1],
                          2, label="map/run")


if __name__ == "__main__":
    # Guard against env leakage: DIAG must be unset for the silent
    # paths above (CI sets it only for forensic runs).
    os.environ.pop("FORKRUN_DIAG_NUMA1", None)
    unittest.main()
