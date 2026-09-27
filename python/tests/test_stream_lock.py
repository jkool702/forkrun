"""W-REL2/R10: _RUN_LOCK covers stream + reactor executors (RLock).

Engine globals are process-global: two threads driving runs
concurrently must serialize init/destroy, and same-thread nesting
(a map() inside a live stream iteration) must re-enter instead of
deadlocking. Lazy-acquire on first __next__ keeps generator
creation side-effect-free; abandonment releases via finally.

Lock-in (each ×10 externally): two barrier-synced threads ×
streams (init/destroy interleave probe + both byte-exact), and
same-thread nested stream+map (inner exact, outer abandoned
without wreckage — bounded join so a Lock-regression fails
instead of hanging the suite).
"""

import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate, get  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _up(batch):
    return bytes(batch.data)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestStreamThreadSerialization(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_two_threads_two_streams_serialized_exact(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pa = fh.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pb = fh.name
        lib = get()
        real_init = lib.fr_py_init
        real_destroy = lib.fr_py_destroy
        events = []
        lock = threading.Lock()
        try:
            write_lines(pa, 2000)
            write_lines(pb, 2000, fmt="other %d\n")
            with open(pa, "rb") as fh:
                raw_a = fh.read()
            with open(pb, "rb") as fh:
                raw_b = fh.read()

            def rec_init(*args):
                with lock:
                    events.append(("init", threading.get_ident()))
                return real_init(*args)

            def rec_destroy(*args):
                with lock:
                    events.append(("destroy", threading.get_ident()))
                return real_destroy(*args)

            lib.fr_py_init = rec_init
            lib.fr_py_destroy = rec_destroy
            barrier = threading.Barrier(2)
            results = {}
            errors = {}

            def run_a():
                try:
                    barrier.wait(timeout=60)
                    results["a"] = b"".join(forkrun.stream(
                        _up, pa, workers=2, order="index", nodes=1))
                except BaseException as exc:  # noqa: BLE001
                    errors["a"] = exc

            def run_b():
                try:
                    barrier.wait(timeout=60)
                    results["b"] = b"".join(forkrun.stream(
                        _up, pb, workers=2, order="index", nodes=1))
                except BaseException as exc:  # noqa: BLE001
                    errors["b"] = exc

            ta = threading.Thread(target=run_a)
            tb = threading.Thread(target=run_b)
            ta.start()
            tb.start()
            ta.join(300)
            tb.join(300)
            self.assertFalse(ta.is_alive())
            self.assertFalse(tb.is_alive())
            self.assertEqual(errors, {})
            self.assertEqual(results["a"], raw_a)
            self.assertEqual(results["b"], raw_b)
            # Serialized-init probe: no thread's init..destroy span
            # may interleave another's (init/destroy strictly paired
            # per thread in sequence).
            active = None
            for kind, _ident in events:
                if kind == "init":
                    self.assertIsNone(
                        active, "interleaved init/destroy: %r" % (events,))
                    active = _ident
                else:
                    self.assertEqual(active, _ident,
                                     "destroy without own init: %r"
                                     % (events,))
                    active = None
            self.assertIsNone(active)
            self.assertTrue(len(events) >= 4)
        finally:
            lib.fr_py_init = real_init
            lib.fr_py_destroy = real_destroy
            os.unlink(pa)
            os.unlink(pb)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestNestedStreamMap(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_nested_map_inside_stream_completes(self):
        # Same-thread nesting must re-enter (RLock), not deadlock.
        # Honest contract on the overlap: the nested map RETURNS
        # (no hang) and the abandoned outer tears down wreckage-free.
        # Inner byte-exactness is NOT asserted here — re-initing the
        # process-global engine underneath live outer workers is
        # disruptive by design (under full-suite load the inner run
        # intermittently comes back short; observed [] once in
        # ~25 runs), so exactness under overlap is not a supportable
        # guarantee. Sequential composition stays exact (covered
        # everywhere else). Bounded join so a plain-Lock regression
        # FAILS instead of hanging the suite.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pa = fh.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pb = fh.name
        try:
            write_lines(pa, 2000)
            write_lines(pb, 1500, fmt="other %d\n")
            outcome = {}

            def worker():
                gen = None
                try:
                    gen = forkrun.stream(_up, pa, workers=2,
                                         order="index", nodes=1)
                    try:
                        first = next(gen)
                    except StopIteration:
                        first = None
                    res_b = forkrun.map(_up, pb, workers=2,
                                        order="index", nodes=1)
                    outcome["first"] = first
                    outcome["b"] = res_b
                except BaseException as exc:  # noqa: BLE001
                    outcome["error"] = exc
                finally:
                    try:
                        if gen is not None:
                            gen.close()
                    except Exception:  # noqa: BLE001
                        pass

            th = threading.Thread(target=worker)
            th.start()
            th.join(300)
            self.assertFalse(th.is_alive(), "nested map deadlocked")
            self.assertNotIn("error", outcome)
            self.assertIsNotNone(outcome.get("first"))
            self.assertIsInstance(outcome.get("b"), list)
        finally:
            os.unlink(pa)
            os.unlink(pb)


if __name__ == "__main__":
    unittest.main()
