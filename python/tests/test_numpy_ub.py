"""W-PY4.c Numpy-past-invalidation characterization (Stage 4 Phase 3).

Plan §3.5 Layer 3 is UB-by-contract: exported buffers (np.frombuffer) hold
their own references, so post-invalidation reads are NOT enforced — the
pages may be reused, punched (fallow PUNCH_HOLE: zeros/SIGBUS), or intact.
v0 measurement (this file): the worker holds the whole-file MAP_SHARED
mmap until os._exit() and no fallow ever runs, so exported views stay
INTACT for the run's duration. The contract warning stands regardless:
v1 fallow/windowed-mmap may turn intact reads into zeros or SIGBUS, and
no test may depend on intactness.

Method (fork-safe): the payload stashes an np export on batch 0 and reads
it back on batch 1 (same worker, sequential batches — the batch-0 Batch
was invalidated between the two calls). Observations cross to the parent
via a worker-side file, never via fork memory.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._batch import Batch  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

try:
    import numpy  # noqa: F401
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


class TestLayer1Enforced(unittest.TestCase):
    """Layer 1 is a contract: direct views raise after release."""

    def test_memoryview_release_then_access(self):
        buf = bytearray(b"hello\nworld\n")
        b = Batch(0, 0, len(buf), 2, memoryview(buf))
        b.invalidate()
        with self.assertRaises(ValueError):
            b.data
        with self.assertRaises(ValueError):
            b.copy()

    @unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
    def test_numpy_export_does_not_extend_batch(self):
        # np.frombuffer takes its own reference to the BYTES, not to the
        # Batch: invalidating the Batch does not invalidate the array
        # object — that is exactly the Layer 3 hazard.
        import numpy as np

        buf = bytearray(b"0123456789abcdef")
        b = Batch(0, 0, len(buf), None, memoryview(buf))
        arr = np.frombuffer(b.data, dtype=np.uint8)
        self.assertEqual(bytes(arr[:4]), b"0123")
        b.invalidate()
        with self.assertRaises(ValueError):
            b.data
        # The array object itself is unaffected by Batch.invalidate()
        # (it holds the buffer reference, not Batch state).
        self.assertEqual(arr.shape, (16,))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
@unittest.skipUnless(HAVE_NUMPY, "numpy not installed")
class TestNumpyPastInvalidation(unittest.TestCase):
    def test_characterize_cross_batch_read(self):
        """Stash an np export on batch 0, read it back on batch 1.

        Between the two calls the batch-0 Batch was invalidated. v0
        measurement: intact (worker mmap held, no fallow). Recorded here
        as the observed value, not as a contract — v1 may zero it.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".obs",
                                         delete=False) as fh2:
            obs_path = fh2.name
        try:
            write_lines(path, 3000)
            with open(path, "rb") as fh:
                raw = fh.read()

            def spy2(batch):
                import numpy as np

                if not hasattr(spy2, "live"):
                    spy2.live = np.frombuffer(batch.data, dtype=np.uint8)
                    spy2.expect = bytes(batch.data)
                else:
                    # batch N>=1: the batch-0 Batch is long invalidated.
                    # Read the live export now.
                    try:
                        got = bytes(spy2.live)
                        status = "intact" if got == spy2.expect else \
                            "changed:%s" % got[:32].hex()
                    except ValueError as exc:
                        status = "raised-ValueError:%s" % exc
                    with open(obs_path, "w") as fh:
                        fh.write(status)
                return bytes(batch.data)

            out = forkrun.map(spy2, path, workers=1, order="index", nodes=1)
            self.assertEqual(b"".join(out), raw)
            with open(obs_path) as fh:
                status = fh.read()
            # v0 MEASUREMENT (not contract): intact — mmap held, no fallow.
            # If a future engine change alters this, update this comment
            # and the Batch warning text; do not "fix" the engine.
            self.assertEqual(status, "intact", status)
            assert_no_zombies(self)
        finally:
            os.unlink(path)
            os.unlink(obs_path)


if __name__ == "__main__":
    unittest.main()
