"""WO-PY-CDRAIN-REACTOR-WAKEUP-1: the reactor must WAKE on the C drain.

The C drain moves framed records from the workers' output memfds into a
results pipe, and the parent consumes that pipe. The defect this work
order fixes: the pump read at most ONE 64 KiB chunk per call and
returned None whenever the pipe was momentarily empty, which ended the
reactor's DRAIN_BURST, which left the reactor's "did I drain last
round" flag false, which made the reactor's next select() wait the FULL
poll_timeout (0.1s). At scale that put the C drain 16-19x behind the
legacy Python drain.

Two changes, and they are not interchangeable:

  * the pump consumes everything ALREADY AVAILABLE (read until the pipe
    is drained), and
  * the reactor SELECTS on the results pipe, so the arrival of data
    wakes the reactor instead of waiting for the timeout.

The memory half matters as much as the speed half. The C drain's whole
advantage is that its parent retention is FLAT (~3.5MB) while the
legacy drain's grows with the output. A read-until-drained loop that
ignored the consumer queued the run's whole output in `pending` and
threw that away -- measured at ~18MB on a 2M-line run. The pump
therefore bounds its read-ahead by the bytes it ALREADY holds
un-yielded, which is what keeps the profile flat.

The pump unit tests here are the deterministic part: they do not assert
wall-clock durations (a shared box cannot support that) but they assert
the OBSERVABLE properties -- what the pump consumed, how it classified
EAGAIN vs EOF vs a real error, and when it disarmed the watch.

Run: cd python/tests && python3 -m unittest test_c_drain_reactor_wakeup
"""

import errno
import os
import select
import struct
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, os.pardir))
sys.path.insert(0, _HERE)

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

# `forkrun.run` is the PUBLIC FUNCTION, not the module (the package does
# `from forkrun.run import map, run, stream, sweep`). Reach the module
# through sys.modules.
import importlib  # noqa: E402
_R = importlib.import_module("forkrun.run")

from _helpers import assert_no_zombies, joined_bytes, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


#: The record framing the C drain emits (batch_idx, len, disposition,
#: reserved) -- the same struct the worker writes.
_HDR = struct.Struct("<QQII")
_DISP_DATA = 0


def _frame(idx, payload, disp=_DISP_DATA):
    return _HDR.pack(idx, len(payload), disp, 0) + payload


def _up(batch):
    return bytes(batch.data)


class _Pipe:
    """A results-pipe stand-in: a real pipe with a measured capacity.

    The capacity is REQUESTED and then MEASURED. The kernel caps
    F_SETPIPE_SZ at /proc/sys/fs/pipe-max-size (1 MiB here) for an
    unprivileged process, so a test that assumed it could ask for 4 MiB
    and then wrote 2 MiB would DEADLOCK: the pipe fills and nobody is
    reading, because the pump has not been called yet.
    """

    def __init__(self, capacity=1 << 20):
        self.r, self.w = os.pipe()
        try:
            import fcntl
            fcntl.fcntl(self.w, fcntl.F_SETPIPE_SZ, capacity)
        except (OSError, AttributeError):
            pass
        # What the kernel actually granted.
        self.capacity = self._measure()
        os.set_blocking(self.r, False)

    def _measure(self):
        try:
            import fcntl
            return fcntl.fcntl(self.w, fcntl.F_GETPIPE_SZ)
        except (OSError, AttributeError):
            return 65536

    def write(self, data):
        """Write, never blocking. The caller must keep the total under
        the pipe's capacity."""
        os.write(self.w, data)

    def close_write(self):
        os.close(self.w)

    def close_read(self):
        os.close(self.r)

    def readable(self):
        """Is there still data in the pipe?"""
        try:
            r, _, _ = select.select([self.r], [], [], 0)
        except (OSError, ValueError):
            return False
        return bool(r)

    def bytes_left(self):
        """How many bytes are still buffered (non-destructively).

        FIONREAD, not st_size: a PIPE's st_size is always 0, so an
        st_size-based measurement would report "nothing left" no matter
        how much was still queued -- exactly the direction that would
        hide a read-ahead regression.
        """
        import array
        import fcntl
        import termios
        buf = array.array("i", [0])
        try:
            fcntl.ioctl(self.r, termios.FIONREAD, buf, True)
        except OSError:
            return 0
        return int(buf[0])


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestPumpReadsEverythingAvailable(unittest.TestCase):
    """The pump must not stop after an arbitrary 64 KiB chunk."""

    def setUp(self):
        self.pipes = []

    def tearDown(self):
        for p in self.pipes:
            for fd in (p.r, p.w):
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _pipe(self, capacity=1 << 20):
        p = _Pipe(capacity)
        self.pipes.append(p)
        return p

    def test_one_pump_call_drains_the_pipe(self):
        # 5 records x 30 KiB = 150 KiB, well over one 64 KiB chunk.
        p = self._pipe()
        for i in range(5):
            p.write(_frame(i, b"x" * 30000))
        pump = _R._make_results_pump(p.r)
        blob = pump(True)
        self.assertIsNotNone(blob, "the pump produced nothing")
        self.assertEqual(len(blob), 30000)
        # The whole pipe is consumed, not just the first chunk.
        self.assertFalse(p.readable(),
                         "the pump stopped with %d bytes still buffered: it "
                         "read one chunk instead of everything available"
                         % p.bytes_left())

    def test_partial_frame_is_held_across_calls(self):
        # A frame split across the read boundary must not be emitted
        # early and must not be dropped.
        p = self._pipe()
        whole = _frame(0, b"y" * 5000)
        p.write(whole[:100])
        pump = _R._make_results_pump(p.r)
        self.assertIsNone(pump(True),
                          "a partial frame was emitted as a record")
        p.write(whole[100:])
        blob = pump(True)
        self.assertIsNotNone(blob, "the frame was lost across the boundary")
        self.assertEqual(len(blob), 5000)

    def test_eagain_is_not_eof(self):
        # An empty-but-open pipe is NOT EOF: the drain may write again.
        p = self._pipe()
        pump = _R._make_results_pump(p.r)
        self.assertIsNone(pump(True), "an empty pipe produced a record")
        p.write(_frame(0, b"z" * 10))
        blob = pump(True)
        self.assertIsNotNone(blob,
                             "the pump treated a temporarily empty pipe as "
                             "EOF and stopped consuming it")
        self.assertEqual(len(blob), 10)

    def test_read_error_is_not_eof(self):
        # A genuine read failure must NOT look like a clean end of
        # stream. The old code turned EVERY OSError into EOF, so a
        # broken pipe looked exactly like a complete run -- a false
        # clean completion with the output silently short.
        p = self._pipe()
        p.close_read()
        pump = _R._make_results_pump(p.r)
        with self.assertRaises(RuntimeError) as ctx:
            pump(True)
        self.assertIn("results pipe", str(ctx.exception))

    def test_eof_is_reported_as_eof(self):
        p = self._pipe()
        p.write(_frame(0, b"q" * 10))
        p.close_write()
        pump = _R._make_results_pump(p.r)
        blob = pump(True)
        self.assertIsNotNone(blob, "the record before EOF was lost")
        with self.assertRaises(StopIteration):
            pump(False)

    def test_read_ahead_is_bounded_by_the_pending_budget(self):
        # The parent must not hold the run's whole output in `pending`.
        # Fill the pipe to just under its measured capacity, call the
        # pump once, and require that the pending budget stopped the
        # read: most of the pipe must still be buffered.
        p = self._pipe()
        # Never write more than the pipe holds, or the write blocks
        # with nobody reading.
        room = p.capacity - 65536
        rec = _frame(0, b"w" * 30000)
        nrec = max(1, room // len(rec))
        for i in range(nrec):
            p.write(_frame(i, b"w" * 30000))
        total = nrec * len(rec)
        self.assertGreater(total, 512 * 1024,
                           "the fixture did not fill enough of the pipe to "
                           "be meaningful (got %d bytes)" % total)
        pump = _R._make_results_pump(p.r)
        pump(True)
        left = p.bytes_left()
        self.assertGreater(
            left, total // 2,
            "one pump call consumed %d of %d bytes: the read-ahead is not "
            "bounded by the pending budget, so the parent would queue the "
            "run's whole output" % (total - left, total))

    def test_pump_makes_its_read_end_nonblocking(self):
        """The pump reads until EAGAIN, so it must not read from a
        BLOCKING descriptor.

        _fork_drain() sets the flag for the production path, but the
        pump is also driven directly over a caller-owned pipe -- and a
        blocking read end there would stall the supervision path
        forever on an empty pipe. The contract is therefore enforced by
        the pump, not left as a caller obligation.

        The flag is asserted BEFORE the functional read, so a regression
        fails this test cleanly instead of hanging it.
        """
        r, w = os.pipe()   # BLOCKING, default capacity
        self.addCleanup(lambda: os.close(r))
        self.addCleanup(lambda: os.close(w))
        self.assertTrue(os.get_blocking(r),
                        "the fixture must start with a BLOCKING read end")
        pump = _R._make_results_pump(r)
        self.assertFalse(
            os.get_blocking(r),
            "the pump must make its read end nonblocking: it reads until "
            "EAGAIN, and a blocking descriptor there would stall the "
            "supervision path on an empty pipe")
        # Safe to reach only because the flag is now known to be set.
        os.write(w, _frame(0, b"x" * 10))
        blob = pump(True)
        self.assertIsNotNone(blob, "the pump produced nothing")
        self.assertEqual(len(blob), 10)

    def test_watch_is_disarmed_at_eof(self):
        # A pipe at EOF is permanently readable. Leaving it in the
        # reactor's watch set would spin the reactor.
        from forkrun._reactor import ExtraWatch
        p = self._pipe()
        p.close_write()
        watch = ExtraWatch(p.r)
        pump = _R._make_results_pump(p.r, watch=watch)
        self.assertTrue(watch.active(), "the watch should start armed")
        with self.assertRaises(StopIteration):
            pump(False)
        self.assertFalse(watch.active(),
                         "the watch was left armed at EOF: a readable-EOF "
                         "pipe would spin the reactor")


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestReactorWatchMechanism(unittest.TestCase):
    """The extra watch fd is a WAKEUP, and nothing else."""

    def test_watch_fds_includes_extra_and_dedupes(self):
        from forkrun._reactor import reactor_watch_fds
        from forkrun._reactor import ReactorState
        st = ReactorState(1)
        st.spawn_r = -1
        st.trap_ack_r = -1
        extra = [11, 12]
        watch = reactor_watch_fds(st, extra=extra)
        self.assertIn(11, watch)
        self.assertIn(12, watch)
        # De-duplicated, and sentinels ignored.
        watch = reactor_watch_fds(st, extra=[11, 11, -1, None])
        self.assertEqual(watch.count(11), 1)
        self.assertNotIn(-1, watch)
        self.assertNotIn(None, watch)

    def test_callers_without_extra_fds_are_unchanged(self):
        from forkrun._reactor import reactor_watch_fds
        from forkrun._reactor import ReactorState
        st = ReactorState(1)
        st.spawn_r = -1
        st.trap_ack_r = -1
        self.assertEqual(reactor_watch_fds(st), [])
        st.trap_ack_r = 7
        self.assertEqual(reactor_watch_fds(st), [7])

    def test_extra_ready_fd_is_not_misclassified_as_a_death(self):
        # A readable EXTRA fd must not be treated as a worker death, and
        # must not be read by the reactor (the pump owns the read side).
        from forkrun._reactor import ExtraWatch, reactor_poll_once
        from forkrun._reactor import ReactorState
        st = ReactorState(1)
        st.spawn_r = -1
        st.trap_ack_r = -1
        p = _Pipe()
        p.write(b"payload the pump owns")
        watch = ExtraWatch(p.r)
        # One non-blocking round. The extra fd is readable, so the round
        # must not raise, must not respawn, and must not consume the
        # bytes.
        reactor_poll_once(st, poll_timeout=0.0, extra_watch=[watch])
        self.assertTrue(p.readable(),
                        "the reactor consumed the extra fd's bytes; the pump "
                        "must stay the sole owner of the read side")
        self.assertEqual(p.bytes_left(), len(b"payload the pump owns"))
        self.assertEqual(len(st.workers), 0,
                         "an extra readable fd was misclassified as a "
                         "worker event")


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCDrainFunctional(unittest.TestCase):
    """The C drain must still deliver the same bytes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        self.src = os.path.join(self.d, "in.txt")
        write_lines(self.src, 2000)

    def tearDown(self):
        assert_no_zombies(self)

    def _expected(self):
        with open(self.src, "rb") as fh:
            return fh.read()

    def test_matches_legacy_reactor_unordered(self):
        legacy = list(forkrun.stream(_up, self.src, workers=2, nodes=1,
                                     orchestrator=True, order="none",
                                     c_drain=False))
        drained = list(forkrun.stream(_up, self.src, workers=2, nodes=1,
                                      orchestrator=True, order="none",
                                      c_drain=True))
        self.assertEqual(sorted(joined_bytes(legacy).splitlines()),
                         sorted(joined_bytes(drained).splitlines()))
        self.assertEqual(len(joined_bytes(drained)),
                         len(self._expected()))

    def test_matches_legacy_reactor_ordered_byte_exact(self):
        legacy = list(forkrun.stream(_up, self.src, workers=2, nodes=1,
                                     orchestrator=True, order="index",
                                     c_drain=False))
        drained = list(forkrun.stream(_up, self.src, workers=2, nodes=1,
                                      orchestrator=True, order="index",
                                      c_drain=True))
        self.assertEqual(joined_bytes(legacy), self._expected())
        self.assertEqual(joined_bytes(drained), self._expected())

    def test_matches_legacy_plain_supervision(self):
        drained = list(forkrun.stream(_up, self.src, workers=2, nodes=1,
                                      orchestrator=False, order="index",
                                      c_drain=True))
        self.assertEqual(joined_bytes(drained), self._expected())

    def test_amplified_record_larger_than_a_chunk(self):
        # A record bigger than the 64 KiB read chunk must survive the
        # chunked read. The payload runs once per BATCH, so the total is
        # batches x payload -- the differential against the legacy drain
        # is the real assertion, not a count computed from input lines.
        big = b"z" * (300 * 1024)
        legacy = list(forkrun.stream(lambda b: big, self.src, workers=2,
                                     nodes=1, orchestrator=True,
                                     order="none", c_drain=False))
        drained = list(forkrun.stream(lambda b: big, self.src, workers=2,
                                      nodes=1, orchestrator=True,
                                      order="none", c_drain=True))
        self.assertTrue(drained)
        self.assertTrue(all(len(blob) >= 300 * 1024 for blob in drained),
                        "an amplified record was split or lost")
        self.assertEqual(sum(len(b) for b in legacy),
                         sum(len(b) for b in drained),
                         "the C drain delivered a different number of bytes "
                         "than the legacy drain for the same workload")

    def test_empty_input(self):
        empty = os.path.join(self.d, "empty.txt")
        open(empty, "w").close()
        out = list(forkrun.stream(_up, empty, workers=2, nodes=1,
                                  orchestrator=True, order="none",
                                  c_drain=True))
        self.assertEqual(out, [], "an empty input produced output")

    def test_slow_consumer_completes(self):
        import time
        got = []
        for blob in forkrun.stream(_up, self.src, workers=2, nodes=1,
                                   orchestrator=True, order="none",
                                   c_drain=True):
            got.append(blob)
            time.sleep(0.001)
        self.assertEqual(len(joined_bytes(got)), len(self._expected()))

    def test_generator_abandonment_tears_down(self):
        gen = forkrun.stream(_up, self.src, workers=2, nodes=1,
                             orchestrator=True, order="none", c_drain=True)
        first = next(gen)
        self.assertTrue(first)
        gen.close()
        assert_no_zombies(self)

    def test_streaming_ingest_source(self):
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                os.close(r)
                for i in range(2000):
                    os.write(w, ("line %d\n" % i).encode())
            finally:
                os.close(w)
                os._exit(0)
        os.close(w)
        try:
            out = list(forkrun.stream(_up, r, workers=2, nodes=1,
                                      orchestrator=True, streaming=True,
                                      order="none", c_drain=True))
            self.assertEqual(len(joined_bytes(out)),
                             len(self._expected()))
        finally:
            os.close(r)
            os.waitpid(pid, 0)

    def test_numa_route(self):
        # A LOGICAL @N envelope: this host has one NUMA node, so this
        # asserts the route runs and is byte-exact -- it is NOT a
        # physical multi-node claim.
        out = list(forkrun.stream(_up, self.src, workers=2, nodes="@2",
                                  orchestrator=True, order="none",
                                  c_drain=True))
        self.assertEqual(len(joined_bytes(out)), len(self._expected()))


if __name__ == "__main__":
    unittest.main()
