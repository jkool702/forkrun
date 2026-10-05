"""W-PY4.a L-Series: worker fault isolation (Stage 4 Phase 3).

Semantics under test (W-REL1/R1: the reactor is the default):
- Python exception in payload -> escrow deposit (kills+1) -> same-worker
  retry -> poison-skip at the limit -> pipeline CONTINUES, exit 0.
- True process death (segfault) on the DEFAULT path -> the reactor
  respawns the worker and the batch is retried: a transient death
  recovers byte-exact; a batch that kills every attempt is
  poison-skipped (mixed) or trips the respawn cap (all-death raises
  RuntimeError, bounded — never an infinite respawn loop).
- orchestrator=False = legacy fork-and-wait fail-fast: any true
  process death raises RuntimeError; survivors' partial output keeps
  the prefix property. No zombies: every child is reaped by waitpid.
- KeyboardInterrupt raised inside a payload is a BaseException like any
  other payload error (retry path), NOT a global abort. Global
  SIGINT (Ctrl-C at the parent) is the abort path and is not tested here.

All tests deterministic: single-worker ordering where batch identity
matters; byte/prefix properties (never timing) elsewhere.
"""

import errno
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import (assert_no_zombies, redirect_fd, restore_fd,  # noqa: E402
                      write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _segv(batch):
    import ctypes

    ctypes.string_at(0)  # SIGSEGV in the worker child
    return b"unreachable"


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestWorkerSegfault(unittest.TestCase):
    def test_all_segfault_parent_raises_no_zombies(self):
        # Every batch kills every attempt: the reactor's respawn cap
        # trips (bounded, never infinite) and the run raises.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 200)
            with self.assertRaises(RuntimeError):
                forkrun.map(_segv, path, workers=2, nodes=1)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_all_segfault_fail_fast_raises_no_zombies(self):
        # orchestrator=False keeps the legacy contract: the first
        # true process death raises RuntimeError immediately.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 200)
            with self.assertRaises(RuntimeError):
                forkrun.map(_segv, path, workers=2, nodes=1,
                            orchestrator=False)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_mixed_segfault_recovers_byte_exact(self):
        # W-REL1/R1 headliner: a transient mid-batch worker death on
        # the default path is recovered via respawn; the run
        # completes byte-exact (MARKER batch included — it succeeds
        # on retry). The flag file makes exactly the first MARKER
        # sighting die.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".out",
                                         delete=False) as fh2:
            sink_path = fh2.name
        flag = path + ".killed"
        try:
            with open(path, "w") as fh:
                for i in range(1000):
                    fh.write("MARKER\n" if i == 500 else "line %d\n" % i)
            with open(path, "rb") as fh:
                raw = fh.read()

            def mixed(batch):
                data = bytes(batch.data)
                if b"MARKER" in data and not os.path.exists(flag):
                    with open(flag, "w") as _fh:
                        _fh.write("1")
                    import ctypes

                    ctypes.string_at(0)
                return data

            def sink(meta, result):
                with open(sink_path, "ab") as out:
                    out.write(result)

            forkrun.run(mixed, path, sink=sink, workers=1, nodes=1)
            with open(sink_path, "rb") as fh:
                got = fh.read()
            # workers=1 but the retried batch completes out of sink
            # order — compare as line multisets (lines are unique).
            self.assertEqual(sorted(got.split(b"\n")),
                             sorted(raw.split(b"\n")))
            self.assertIn(b"MARKER", got)
            assert_no_zombies(self)
        finally:
            os.unlink(path)
            os.unlink(sink_path)
            if os.path.exists(flag):
                os.unlink(flag)

    def test_mixed_segfault_fail_fast_prefix(self):
        # orchestrator=False keeps the legacy contract: the death
        # raises, and survivors' sink output is an exact PREFIX of
        # the input (batches 0..k-1), never containing the marker.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".out",
                                         delete=False) as fh2:
            sink_path = fh2.name
        try:
            with open(path, "w") as fh:
                for i in range(1000):
                    fh.write("MARKER\n" if i == 500 else "line %d\n" % i)
            with open(path, "rb") as fh:
                raw = fh.read()

            def mixed(batch):
                data = bytes(batch.data)
                if b"MARKER" in data:
                    import ctypes

                    ctypes.string_at(0)
                return data

            def sink(meta, result):
                with open(sink_path, "ab") as out:
                    out.write(result)

            with self.assertRaises(RuntimeError):
                forkrun.run(mixed, path, sink=sink, workers=1, nodes=1,
                            orchestrator=False)
            with open(sink_path, "rb") as fh:
                got = fh.read()
            self.assertTrue(len(got) > 0)
            self.assertTrue(raw.startswith(got),
                            "survivor output must be an input prefix")
            self.assertNotIn(b"MARKER", got)
            assert_no_zombies(self)
        finally:
            os.unlink(path)
            os.unlink(sink_path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestWorkerOOM(unittest.TestCase):
    def test_allocation_failure_retries_then_poisons(self):
        # Explicit MemoryError exercises the same escrow path a real
        # allocation failure would take (a true 10GB alloc is nondetermin-
        # istic under overcommit, so the deterministic fault is used).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1500)

            def oom(batch):
                raise MemoryError("simulated allocation failure")

            out = forkrun.map(oom, path, workers=1, nodes=1)
            self.assertEqual(out, [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestWorkerException(unittest.TestCase):
    def test_value_error_poison_summary_on_stderr(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        cap = path + ".err"
        try:
            write_lines(path, 1200)

            def bad(batch):
                raise ValueError("boom")

            saved = redirect_fd(2, cap)
            try:
                sys.stderr.flush()
                out = forkrun.map(bad, path, workers=1, nodes=1)
                sys.stderr.flush()
            finally:
                restore_fd(2, saved)
            self.assertEqual(out, [])
            with open(cap, "rb") as fh:
                err = fh.read()
            self.assertIn(b"poisoned batch", err)
            assert_no_zombies(self)
        finally:
            os.unlink(path)
            if os.path.exists(cap):
                os.unlink(cap)

    def test_keyboard_interrupt_once_retries(self):
        # KI inside the payload is a payload error in v0 (retry path), not
        # a global abort. Flag file makes exactly the first call fail.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        flag = path + ".flag"
        try:
            write_lines(path, 400)

            def flaky(batch):
                if not os.path.exists(flag):
                    with open(flag, "w") as _fh:
                        _fh.write("1")
                    raise KeyboardInterrupt("once")
                return bytes(batch.data)

            out = forkrun.map(flaky, path, workers=1, order="index", nodes=1)
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)
            if os.path.exists(flag):
                os.unlink(flag)

    def test_payload_retry_count_at_least_once(self):
        """W-REL6-3.3: payload side effects are at-least-once (x5).

        Deterministic: 10 batches, batch 0 always fails. Default
        retry limit (3) executes the failing batch exactly 3 times;
        every healthy batch runs once. File-append counting (fork
        children cannot report to parent memory).
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        log = path + ".calls"
        try:
            write_lines(path, 100)
            for _ in range(5):
                if os.path.exists(log):
                    os.unlink(log)

                def counting(batch, _log=log):
                    with open(_log, "a") as _fh:
                        _fh.write("%d\n" % batch.batch_index)
                    if batch.batch_index == 0:
                        raise ValueError("always fails")
                    return bytes(batch.data)

                out = forkrun.map(counting, path, workers=2, lines=10,
                                  nodes=1)
                self.assertEqual(len(out), 9)
                with open(log) as _fh:
                    calls = [int(x) for x in _fh.read().split()]
                self.assertEqual(len(calls), 12)
                self.assertEqual(calls.count(0), 3)
            assert_no_zombies(self)
        finally:
            os.unlink(path)
            if os.path.exists(log):
                os.unlink(log)

    def test_map_return_stats(self):
        """W-REL6-3.6: map batch accounting (x5, deterministic).

        return_stats=True returns (list, stats) with exact
        total/completed/poisoned/poisoned_batches; default returns
        the bare list; forkrun.last_run_stats() matches the last
        call; non-bool return_stats is a TypeError.
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 100)
            for _ in range(5):
                def ident(batch):
                    return bytes(batch.data)

                out = forkrun.map(ident, path, workers=2, lines=10,
                                  nodes=1)
                self.assertIsInstance(out, list)
                self.assertEqual(len(out), 10)

                out2, stats = forkrun.map(
                    ident, path, workers=2, lines=10, nodes=1,
                    return_stats=True)
                self.assertIsInstance(out2, list)
                self.assertEqual(len(out2), 10)
                self.assertEqual(stats, {"total": 10, "completed": 10,
"poisoned": 0,
                             "poisoned_batches": [],
                             # New in v3.6.1: the cleanroom's bounded relay
                             # slot can drop indices, so the stats say so
                             # instead of leaving a short list
                             # indistinguishable from a complete one.
                             # False here because nothing poisoned.
                             "poisoned_batches_truncated": False})
                self.assertEqual(forkrun.last_run_stats(), stats)

                def poison_head(batch):
                    if batch.batch_index == 0:
                        raise ValueError("head poison")
                    return bytes(batch.data)

                out3, stats3 = forkrun.map(
                    poison_head, path, workers=2, lines=10, nodes=1,
                    return_stats=True)
                self.assertEqual(len(out3), 9)
                self.assertEqual(stats3, {"total": 10, "completed": 9,
                                          "poisoned": 1,
                                          "poisoned_batches": [0],
                                          "poisoned_batches_truncated":
                                              False})
                self.assertEqual(forkrun.last_run_stats(), stats3)

                with self.assertRaises(TypeError):
                    forkrun.map(ident, path, return_stats="yes")
            assert_no_zombies(self)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestEmitRollback(unittest.TestCase):
    """W-REL2/R13: the pure-Python v0 emit path rolls back partial
    records on write failure (the C-loop payload_error pattern
    verbatim: ftruncate to the pre-record end, append-once rule),
    so framing stays parseable under ENOSPC and the retry
    completes byte-exact."""

    def test_injected_enospc_recovers_byte_exact(self):
        # FORKRUN_NO_V1=1 forces the v0 Python writes (the C emit
        # path already rolls back inside fr_py_emit). The first
        # >1KB os.write anywhere fails once with ENOSPC (file flag:
        # once-only across fork; the parent never writes big chunks
        # via os.write — spill uses pwrite, signals are 16B — so
        # the fault lands on a worker blob write).
        old = os.environ.get("FORKRUN_NO_V1")
        os.environ["FORKRUN_NO_V1"] = "1"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        flag = path + ".enospc"
        real_write = os.write

        def fail_once(fd, data):
            if len(data) > 1024 and not os.path.exists(flag):
                with open(flag, "w") as _fh:
                    _fh.write("1")
                raise OSError(errno.ENOSPC, "injected")
            return real_write(fd, data)

        try:
            write_lines(path, 20000)
            with open(path, "rb") as fh:
                raw = fh.read()
            import unittest.mock as _mock
            with _mock.patch("os.write", side_effect=fail_once):
                out = forkrun.map(lambda b: bytes(b.data), path,
                                  workers=1, order="index", nodes=1)
            self.assertTrue(os.path.exists(flag),
                            "fault never fired — test vacuous")
            self.assertEqual(b"".join(out), raw)
            assert_no_zombies(self)
        finally:
            if old is None:
                os.environ.pop("FORKRUN_NO_V1", None)
            else:
                os.environ["FORKRUN_NO_V1"] = old
            os.unlink(path)
            if os.path.exists(flag):
                os.unlink(flag)


if __name__ == "__main__":
    unittest.main()
