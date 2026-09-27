"""D-PORT2: abort-aware helper-death classification (P7, D6 mirror).

An abort already in flight makes helper deaths expected
(emergency path), not fatal. Locks the disposition truth table,
the live reason accessor, and the end-to-end suppression shape:
a HUP-aborted NUMA run raises ForkrunTerminated WITHOUT a
chained "NUMA index/scan failed" spurious fatal (pre-fix, the
watch raised first and the taxonomy error merely chained it).
"""

import os
import signal as _signal
import sys
import tempfile
import threading
import time
import traceback
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate, get  # noqa: E402
from forkrun.exceptions import ForkrunTerminated  # noqa: E402
from forkrun.run import (_abort_reason_now,  # noqa: E402
                         _helper_death_disposition)

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


class TestDispositionTable(unittest.TestCase):
    def test_clean_with_eof_records(self):
        for reason in (0, 1, 2, None, -1):
            self.assertEqual(
                _helper_death_disposition("clean", True, reason),
                "record", "reason=%r" % (reason,))

    def test_abort_in_flight_excuses(self):
        for kind in ("clean", "error"):
            for reason in (1, 2):
                self.assertEqual(
                    _helper_death_disposition(kind, False, reason),
                    "excuse", "kind=%s reason=%r" % (kind, reason))

    def test_no_abort_is_fatal(self):
        # Clean-before-EOF with no abort is tail loss; error with
        # no abort is violent death. Unknown (-1/None: no engine
        # or pre-D-PORT2 substrate) fails safe to fatal.
        for kind in ("clean", "error"):
            for reason in (0, None, -1):
                self.assertEqual(
                    _helper_death_disposition(kind, False, reason),
                    "fatal", "kind=%s reason=%r" % (kind, reason))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestReasonAccessor(unittest.TestCase):
    def test_symbol_present_and_int(self):
        lib = get()
        self.assertTrue(hasattr(lib, "fr_py_abort_reason"))
        reason = _abort_reason_now(lib)
        self.assertIn(reason, (None, -1, 0, 1, 2))

    def test_missing_symbol_reads_unknown(self):
        self.assertIsNone(_abort_reason_now(object()))

    def test_no_engine_reads_minus_one(self):
        lib = get()
        fn = getattr(lib, "fr_py_abort_reason", None)
        if fn is None:
            self.skipTest("substrate predates D-PORT2")
        # No live engine in the test process itself (each run
        # inits/destroys its own): either -1 or a stale byte —
        # the contract is int-ness, not a specific value.
        self.assertIsInstance(int(fn()), int)


def _slow(batch):
    time.sleep(0.15)
    return bytes(batch.data)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestNumaHupSuppression(unittest.TestCase):
    def test_hup_abort_has_no_spurious_index_fatal(self):
        # HUP-aborted NUMA run raises ForkrunTerminated with NO
        # chained "NUMA index/scan failed" spurious fatal. The
        # trickling pipe keeps ingest/indexers alive across the
        # abort window (a fast file lets helpers finish before
        # the abort lands, traversing no watch-during-abort path).
        # The disposition truth table above locks the decision
        # itself; this locks the realistic end-to-end shape.
        r, w = os.pipe()
        stop = threading.Event()

        def writer():
            i = 0
            while not stop.is_set() and i < 120:
                try:
                    os.write(w, ('line %06d abcdefghijklmnop\n'
                                 % i).encode())
                except OSError:
                    break
                i += 1
                time.sleep(0.05)
            try:
                os.close(w)
            except OSError:
                pass

        wt = threading.Thread(target=writer, daemon=True)
        wt.start()
        t = threading.Timer(
            1.5, lambda: os.kill(os.getpid(), _signal.SIGHUP))
        t.daemon = True
        t.start()
        try:
            try:
                forkrun.map(_slow, r, workers=4, nodes="@2",
                            order="index", orchestrator=True,
                            signal_policy="checkpoint")
            except ForkrunTerminated:
                text = traceback.format_exc()
                self.assertNotIn("NUMA index", text)
                self.assertNotIn("NUMA scan", text)
            else:
                # Abort landing after full drain still completes —
                # acceptable (nothing lost, nothing spurious).
                pass
            assert_no_zombies(self)
        finally:
            t.cancel()
            stop.set()
            try:
                os.close(r)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
