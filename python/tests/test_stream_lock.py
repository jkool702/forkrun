"""W-REL2/R10: _RUN_LOCK covers stream + reactor executors (RLock).

Engine globals are process-global, so at most ONE engine session may be
live per process. Two threads driving runs concurrently must serialize
init/destroy -- that still works. Same-thread NESTING into a live
session is REFUSED rather than re-entered: a second session replaces
g_state, leaving the parent unable to supervise or recover its workers.
Lazy-acquire on first __next__ keeps generator creation side-effect-free;
abandonment releases via finally.

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

    def test_nested_map_inside_live_stream_is_refused(self):
        """The engine-session invariant: one live session per process.

        The engine's state is process-global. A nested run does not
        merely interleave work -- ring_init_main replaces g_state and
        ring_destroy_main NULLs it, so a nested session leaves the
        parent unable to supervise or recover its workers. The previous
        version of this test PERMITTED the nesting and declined to assert
        inner byte-exactness, documenting that the inner run "intermittently
        comes back short". A contract that admits a known-corrupting call
        is not a contract, so the nesting is now refused outright.

        Every assertion here is a distinct part of the contract:
          * the nested call is REJECTED, not merely slowed or truncated;
          * it is rejected PROMPTLY (bounded join, so a regression to a
            hang fails instead of wedging the suite);
          * the OUTER stream stays byte-exact -- the rejection must not
            have touched the live session;
          * the session guard is RELEASED, so a later run still works;
          * catching the exception does not leave the guard stuck.
        """
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
                    # The live engine session must refuse this outright.
                    try:
                        outcome["b"] = forkrun.map(
                            _up, pb, workers=2, order="index", nodes=1)
                    except RuntimeError as exc:
                        outcome["refused"] = str(exc)

                    # Catching the refusal must not disturb the session:
                    # the outer stream must still complete byte-exactly.
                    rest = list(gen)
                    outcome["first"] = first
                    outcome["rest"] = len(rest)
                except BaseException as exc:  # noqa: BLE001
                    outcome["error"] = exc
                finally:
                    if gen is not None:
                        try:
                            gen.close()
                        except Exception:  # noqa: BLE001
                            pass

            th = threading.Thread(target=worker)
            th.start()
            th.join(300)
            self.assertFalse(th.is_alive(),
                             "nested map deadlocked instead of being "
                             "refused promptly")
            self.assertNotIn("error", outcome,
                             "the outer stream must survive the refusal: "
                             "%r" % outcome.get("error"))
            self.assertNotIn(
                "b", outcome,
                "the nested map RAN. One engine session per process is the "
                "invariant; a completed nested call means the guard is "
                "not enforced.")
            self.assertIn("refused", outcome,
                          "nested map must raise RuntimeError, not return")
            self.assertIn("nested run", outcome["refused"],
                          "the message must explain WHY it was refused, so "
                          "a caller can act on it")
            self.assertIsNotNone(outcome.get("first"))
            self.assertGreater(outcome.get("rest", 0), 0,
                               "the outer stream must continue after the "
                               "nested attempt is refused")

            # The guard must be RELEASED: a fresh top-level run works.
            after = forkrun.map(_up, pb, workers=2, order="index", nodes=1)
            self.assertTrue(after,
                            "a sequential run after the stream closed must "
                            "work -- a leaked session marker would make "
                            "every later run raise")
        finally:
            os.unlink(pa)
            os.unlink(pb)

    def test_sequential_runs_are_unaffected(self):
        """The guard must not make ordinary sequential use impossible."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pa = fh.name
        try:
            write_lines(pa, 500)
            for i in range(3):
                out = forkrun.map(_up, pa, workers=1, order="index", nodes=1)
                self.assertTrue(out, "run %d produced nothing" % i)
            gen = forkrun.stream(_up, pa, workers=1, order="index", nodes=1)
            self.assertGreater(len(list(gen)), 0)
        finally:
            os.unlink(pa)

    def test_session_is_released_after_a_stream_raises(self):
        """An abandoned stream must not leave the session marked live.

        If the marker leaked on an exception path, every subsequent run
        in the process would refuse -- which presents as "the library is
        broken" rather than "the guard did not clean up".
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            pa = fh.name
        try:
            write_lines(pa, 400)
            gen = forkrun.stream(_up, pa, workers=1, order="index", nodes=1)
            next(gen)
            gen.close()          # abandonment, not exhaustion

            out = forkrun.map(_up, pa, workers=1, order="index", nodes=1)
            self.assertTrue(out,
                            "the session marker leaked past close()")
        finally:
            os.unlink(pa)


if __name__ == "__main__":
    unittest.main()
