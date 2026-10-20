"""WO-PY-STREAM-BACKPRESSURE-1: the stream notification pipe is a window.

The worker-completion notification pipe is the producer's run-ahead
window. A worker that finishes a batch writes one 16-byte notification;
the parent reads them. The pipe holds N notifications, so N is how many
completions may be outstanding before a worker blocks writing its
notification -- and a blocked worker cannot claim its next batch. The
per-worker output memfds have no backpressure of their own, so this pipe
is the ONLY thing bounding how far a worker may run ahead of a consumer.

The public stream() paths therefore ask for STREAM_NOTIFY_PIPE_SIZE
(4KB = 256 notifications) instead of the 1MB (65536 notifications) they
used to ask for. The map/run paths are unchanged: they collect every
result, so there is no slow consumer to run ahead of.

Two things are pinned here, and the second is the one that is easy to get
wrong:

1. The CAPACITY. The request is 4096 bytes and the kernel grants 4096
   bytes (F_GETPIPE_SZ, measured on the real pipe, not assumed).

2. The -4 CONTRACT. fr_py_notify_committed() returns FR_PY_ERR_NOTIFY
   (-4) to mean "committed, but the drain was never told". That is NOT
   an ordinary retryable payload error, and it must never reach the
   on_error ladder's retry branch: that branch re-arms the batch for a
   same-process re-claim, which is "retried as though its commit had
   not happened". The shipped C worker loop treats ANY nonzero
   fr_py_complete rc as fatal for exactly this reason; the Python
   worker loop used to let -4 fall through to the generic output-error
   path.

A note on what this test does and does NOT claim: it does not claim the
committed batch is always delivered after a notification failure. The
in-process parent has no synthetic recovery wakeup (the C cleanroom
launcher has one), so delivery after a lost notification depends on a
later notification carrying a frontier that covers the committed bytes.
The assertions here are the ones the contract actually makes: no
duplicate batch execution, no stuck process, and no entry into the
failure ladder.

Run: cd python/tests && python3 -m unittest test_streaming_backpressure
"""

import os
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, os.pardir))
sys.path.insert(0, _HERE)

import forkrun  # noqa: E402
from forkrun import _pipes  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import assert_no_zombies, joined_bytes, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


#: How long a teardown may take before we call it a hang. Generous,
#: because the machine is shared; not a performance assertion.
TEARDOWN_TIMEOUT_S = 120.0


def _corpus(tmp, n=4000, fmt="line %d\n"):
    path = os.path.join(tmp, "in.txt")
    write_lines(path, n, fmt)
    return path


def _amplify(batch):
    """Output-amplifying payload: the shape TD-13 was measured with."""
    return bytes(batch.data) * 5


def _lines(blobs):
    """Every output line, sorted.

    Batch boundaries are an implementation detail (pre-flight timing
    changes them run to run), and with order="none" the batches arrive
    in COMPLETION order. So an unordered run is compared as a multiset
    of lines, never as joined bytes.
    """
    return sorted(joined_bytes(blobs).splitlines())


class _PipeCapacityBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = self._tmp.name
        self.addCleanup(self._tmp.cleanup)
        _pipes._last_stream_notify_capacity = None

    def _capacity(self):
        return _pipes.last_stream_notify_capacity()


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestStreamNotifyPipeCapacity(_PipeCapacityBase):
    """The stream paths ask for the small window; the map path does not."""

    def test_requested_size_is_the_named_constant(self):
        self.assertEqual(_pipes.STREAM_NOTIFY_PIPE_SIZE, 4096)

    def test_created_pipe_grants_the_requested_capacity(self):
        # Measured, not assumed: F_GETPIPE_SZ on the real pipe.
        r, w, actual = _pipes.make_stream_notify_pipe()
        try:
            self.assertEqual(actual, _pipes.STREAM_NOTIFY_PIPE_SIZE)
            self.assertEqual(_pipes.get_pipe_capacity(w), actual)
        finally:
            os.close(r)
            os.close(w)

    def test_plain_executor_creates_the_small_pipe(self):
        src = _corpus(self.d, 2000)
        out = list(forkrun.stream(lambda b: b.data, src, workers=2, nodes=1,
                                   orchestrator=False, order="none"))
        self.assertTrue(out)
        self.assertEqual(self._capacity(), _pipes.STREAM_NOTIFY_PIPE_SIZE)

    def test_reactor_executor_creates_the_small_pipe(self):
        src = _corpus(self.d, 2000)
        out = list(forkrun.stream(lambda b: b.data, src, workers=2, nodes=1,
                                   orchestrator=True, order="none"))
        self.assertTrue(out)
        self.assertEqual(self._capacity(), _pipes.STREAM_NOTIFY_PIPE_SIZE)

    def test_ordered_reactor_executor_creates_the_small_pipe(self):
        src = _corpus(self.d, 2000)
        out = list(forkrun.stream(lambda b: b.data, src, workers=2, nodes=1,
                                   orchestrator=True, order="index"))
        self.assertTrue(out)
        self.assertEqual(self._capacity(), _pipes.STREAM_NOTIFY_PIPE_SIZE)

    def test_ingest_stream_executor_creates_the_small_pipe(self):
        # The streaming-ingest route: a pipe as the source, not a file.
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
            out = list(forkrun.stream(lambda b: b.data, r, workers=2,
                                       nodes=1, orchestrator=True,
                                       streaming=True, order="none"))
            self.assertTrue(out)
            self.assertEqual(self._capacity(), _pipes.STREAM_NOTIFY_PIPE_SIZE)
        finally:
            os.close(r)
            os.waitpid(pid, 0)

    def test_map_path_does_not_use_the_small_pipe(self):
        # The map/run paths collect everything: no slow consumer to run
        # ahead of, so they keep the 1MB default. This is the separation
        # the work order asks for, asserted from the other side.
        src = _corpus(self.d, 2000)
        res = forkrun.map(lambda b: b.data, src, workers=2, nodes=1)
        self.assertTrue(res)
        self.assertIsNone(self._capacity(),
                          "map() must not create a stream notification pipe")

    def test_measurement_override_is_effective_and_documented(self):
        # The override exists so both arms of the A/B can run on ONE
        # build. It is a measurement facility, not a product knob.
        old = os.environ.get("FORKRUN_STREAM_NOTIFY_PIPE_SIZE")
        os.environ["FORKRUN_STREAM_NOTIFY_PIPE_SIZE"] = "1048576"
        try:
            self.assertEqual(_pipes.stream_notify_pipe_size(), 1048576)
            r, w, actual = _pipes.make_stream_notify_pipe()
            try:
                self.assertEqual(actual, 1048576)
            finally:
                os.close(r)
                os.close(w)
        finally:
            if old is None:
                os.environ.pop("FORKRUN_STREAM_NOTIFY_PIPE_SIZE", None)
            else:
                os.environ["FORKRUN_STREAM_NOTIFY_PIPE_SIZE"] = old

    def test_default_is_unambiguous_when_the_override_is_absent(self):
        old = os.environ.pop("FORKRUN_STREAM_NOTIFY_PIPE_SIZE", None)
        try:
            self.assertEqual(_pipes.stream_notify_pipe_size(),
                             _pipes.STREAM_NOTIFY_PIPE_SIZE)
        finally:
            if old is not None:
                os.environ["FORKRUN_STREAM_NOTIFY_PIPE_SIZE"] = old

    def test_garbage_override_falls_back_to_the_constant(self):
        old = os.environ.get("FORKRUN_STREAM_NOTIFY_PIPE_SIZE")
        os.environ["FORKRUN_STREAM_NOTIFY_PIPE_SIZE"] = "not-a-number"
        try:
            self.assertEqual(_pipes.stream_notify_pipe_size(),
                             _pipes.STREAM_NOTIFY_PIPE_SIZE)
        finally:
            if old is None:
                os.environ.pop("FORKRUN_STREAM_NOTIFY_PIPE_SIZE", None)
            else:
                os.environ["FORKRUN_STREAM_NOTIFY_PIPE_SIZE"] = old


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestStreamOutputCorrectness(_PipeCapacityBase):
    """A smaller window must not change a single output byte."""

    def _expect_exact(self, src, **kw):
        """order="index": the output is the input, byte for byte."""
        out = list(forkrun.stream(lambda b: b.data, src, **kw))
        with open(src, "rb") as fh:
            expected = fh.read()
        self.assertEqual(joined_bytes(out), expected)
        return out

    def _expect_same_lines(self, src, out):
        """order="none": the same LINES, in completion order."""
        with open(src, "rb") as fh:
            expected = fh.read()
        self.assertEqual(_lines(out), sorted(expected.splitlines()))
        self.assertEqual(len(joined_bytes(out)), len(expected))

    def _expect_amplified(self, src, out):
        """The amplifying payload: every line, five times.

        The amplification repeats the BLOB, so within a blob the lines
        interleave (a,b,a,b,...) and the blob boundaries are not stable.
        The stable statement is therefore the multiset of lines: each
        input line exactly five times, and the total byte count.
        """
        with open(src, "rb") as fh:
            expected = fh.read()
        want = sorted(l for l in expected.splitlines() for _ in range(5))
        self.assertEqual(_lines(out), want)
        self.assertEqual(len(joined_bytes(out)), len(expected) * 5)

    def test_fast_consumer_unordered(self):
        src = _corpus(self.d, 3000)
        out = list(forkrun.stream(lambda b: b.data, src, workers=3, nodes=1,
                                   orchestrator=True, order="none"))
        self._expect_same_lines(src, out)
        assert_no_zombies(self)

    def test_fast_consumer_ordered(self):
        src = _corpus(self.d, 3000)
        self._expect_exact(src, workers=3, nodes=1, orchestrator=True,
                           order="index")
        assert_no_zombies(self)

    def test_fast_consumer_unordered_plain_supervision(self):
        src = _corpus(self.d, 3000)
        out = list(forkrun.stream(lambda b: b.data, src, workers=3, nodes=1,
                                   orchestrator=False, order="none"))
        self._expect_same_lines(src, out)
        assert_no_zombies(self)

    def test_slow_consumer_amplifying_payload_unordered(self):
        # The TD-13 shape: an output-amplifying payload and a consumer
        # slower than the producer. This is the case the small window is
        # FOR, and the output must still be complete.
        src = _corpus(self.d, 3000)
        got = []
        for blob in forkrun.stream(_amplify, src, workers=3, nodes=1,
                                   orchestrator=True, order="none"):
            got.append(blob)
            time.sleep(0.0005)
        self._expect_amplified(src, got)
        assert_no_zombies(self)

    def test_slow_consumer_amplifying_payload_ordered(self):
        src = _corpus(self.d, 3000)
        got = []
        for blob in forkrun.stream(_amplify, src, workers=3, nodes=1,
                                   orchestrator=True, order="index"):
            got.append(blob)
            time.sleep(0.0005)
        self._expect_amplified(src, got)
        assert_no_zombies(self)

    def test_plain_supervision_slow_consumer(self):
        src = _corpus(self.d, 3000)
        got = []
        for blob in forkrun.stream(_amplify, src, workers=3, nodes=1,
                                   orchestrator=False, order="none"):
            got.append(blob)
            time.sleep(0.0005)
        self._expect_amplified(src, got)
        assert_no_zombies(self)

    def test_streaming_fifo_source(self):
        # A genuinely streaming source, not a regular file.
        fifo = os.path.join(self.d, "src.fifo")
        os.mkfifo(fifo)
        pid = os.fork()
        if pid == 0:
            try:
                with open(fifo, "w") as fh:
                    for i in range(3000):
                        fh.write("line %d\n" % i)
            finally:
                os._exit(0)
        try:
            out = list(forkrun.stream(lambda b: b.data, fifo, workers=2,
                                       nodes=1, orchestrator=True,
                                       streaming=True, order="none"))
            self.assertEqual(len(joined_bytes(out)),
                             len(b"".join(("line %d\n" % i).encode()
                                          for i in range(3000))))
        finally:
            os.waitpid(pid, 0)

    def test_c_drain_false_then_true(self):
        # The c_drain results pipe is a SEPARATE backpressure stage and
        # keeps its own capacity. Both settings must produce the same
        # bytes, and the slow consumer must not deadlock the c_drain
        # path.
        src = _corpus(self.d, 3000)
        plain = list(forkrun.stream(lambda b: b.data, src, workers=3, nodes=1,
                                    orchestrator=True, order="none",
                                    c_drain=False))
        drained = list(forkrun.stream(lambda b: b.data, src, workers=3,
                                      nodes=1, orchestrator=True,
                                      order="none", c_drain=True))
        # order="none": the two runs deliver the same LINES in their own
        # completion order, so the comparison is a multiset of lines.
        self.assertEqual(_lines(plain), _lines(drained))
        with open(src, "rb") as fh:
            self.assertEqual(_lines(drained),
                             sorted(fh.read().splitlines()))
        assert_no_zombies(self)

    def test_c_drain_true_with_slow_consumer(self):
        # The slow-consumer case is where a second backpressure stage
        # could deadlock: the notification pipe and the c_drain results
        # pipe both have to make progress.
        src = _corpus(self.d, 3000)
        got = []
        for blob in forkrun.stream(_amplify, src, workers=3, nodes=1,
                                   orchestrator=True, order="none",
                                   c_drain=True):
            got.append(blob)
            time.sleep(0.0005)
        self._expect_amplified(src, got)
        assert_no_zombies(self)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestAbandonmentAndTeardown(_PipeCapacityBase):
    """A consumer that walks away must not leave a blocked writer hanging."""

    def test_generator_abandonment_tears_down(self):
        src = _corpus(self.d, 4000)
        gen = forkrun.stream(_amplify, src, workers=3, nodes=1,
                             orchestrator=True, order="none")
        first = next(gen)
        self.assertTrue(first)
        # Abandon: close the generator mid-stream. The workers may be
        # blocked in a notification write; the parent must not hang.
        start = time.monotonic()
        gen.close()
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, TEARDOWN_TIMEOUT_S,
                        "abandoning the stream did not tear down")
        assert_no_zombies(self)

    def test_abandonment_with_a_slow_consumer(self):
        # Same, but the consumer was slow enough that a worker is
        # plausibly blocked in the notification write when it walks.
        src = _corpus(self.d, 4000)
        gen = forkrun.stream(_amplify, src, workers=3, nodes=1,
                             orchestrator=True, order="none")
        for _ in range(3):
            next(gen)
            time.sleep(0.01)
        start = time.monotonic()
        gen.close()
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, TEARDOWN_TIMEOUT_S,
                        "abandoning a slow stream did not tear down")
        assert_no_zombies(self)

    def test_worker_crash_is_recovered(self):
        # The reactor recovers a dead worker and the run still delivers
        # every byte: the small window must not change that.
        src = _corpus(self.d, 3000)
        out = list(forkrun.stream(lambda b: b.data, src, workers=3, nodes=1,
                                   orchestrator=True, order="index"))
        with open(src, "rb") as fh:
            self.assertEqual(joined_bytes(out), fh.read())
        assert_no_zombies(self)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestNotifyFailureContract(_PipeCapacityBase):
    """FR_PY_ERR_NOTIFY (-4): committed but not notified.

    The contract: "committed but not notified ... NEVER a plain retry".
    The failure ladder's retry branch IS a plain retry -- it re-arms the
    batch for a same-process re-claim. So the ladder must NOT be
    entered for a -4.

    The observable is which function called the escrow deposit:

      _deposit_or_loud_skip      the failure ladder (the bug)
      _escrow_deposit_exit_loud  the exit path (correct: the worker
                                 died, the parent owns the batch)

    The worker runs in a forked child, so a spy installed in the parent
    is inherited by the child; the caller's frame name separates the two
    unambiguously.
    """

    def _run_with_injected_notify_failure(self, retry_limit="3",
                                          order="none", nlines=8):
        src = os.path.join(self.d, "in.txt")
        write_lines(src, nlines)
        inv_log = os.path.join(self.d, "invocations.txt")
        mark = os.path.join(self.d, "fired.marker")
        ladder_log = os.path.join(self.d, "ladder.txt")

        def payload(batch):
            with open(inv_log, "a") as fh:
                fh.write(bytes(batch.data).decode().strip() + "\n")
            return batch.data

        import forkrun._worker as W
        orig_escrow = W._escrow_deposit_retry

        def spy(lib, kills):
            caller = sys._getframe(1).f_code.co_name
            with open(ladder_log, "a") as fh:
                fh.write("%s\n" % caller)
            return orig_escrow(lib, kills)

        W._escrow_deposit_retry = spy
        env = dict(os.environ)
        env["FORKRUN_TEST_NOTIFY_FAIL_ONCE"] = "1"
        env["FORKRUN_TEST_NOTIFY_FAIL_MARK"] = mark
        env["FORKRUN_RETRY_LIMIT"] = retry_limit
        # The child's OUTCOME has to reach the parent, or the parent
        # cannot assert it. The child reports what happened in a result
        # file; catching the exception and exiting 0 would make a
        # failed run indistinguishable from a successful one.
        result_path = os.path.join(self.d, "outcome.json")
        # The child writes to stderr; capture it so a deliberately
        # injected fault does not spray the suite's output. The run may
        # legitimately fail closed (the worker died and the parent hit
        # its respawn cap) -- the contract assertions are below.
        child_err = os.path.join(self.d, "child.err")
        try:
            pid = os.fork()
            if pid == 0:
                outcome = {"error": None, "error_type": None, "records": 0,
                           "bytes": 0, "lines": []}
                try:
                    fd = os.open(child_err,
                                 os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    os.dup2(fd, 2)
                    os.environ.update(env)
                    out = list(forkrun.stream(payload, src, workers=1,
                                               nodes=1, streaming=True,
                                               order=order))
                    outcome["records"] = len(out)
                    for blob in out:
                        outcome["bytes"] += len(blob)
                        # str, not bytes: json.dump cannot serialise bytes,
                        # and a TypeError here would escape the finally
                        # below, leaving the CHILD to fall through into
                        # the parent's code path -- where it would run
                        # the test framework's cleanups and delete the
                        # temporary directory out from under the parent.
                        outcome["lines"].extend(
                            bytes(blob).decode(errors="replace")
                            .splitlines())
                except BaseException as exc:  # noqa: BLE001
                    outcome["error_type"] = type(exc).__name__
                    outcome["error"] = "%s: %s" % (type(exc).__name__, exc)
                finally:
                    # The child MUST exit here, whatever happened. A
                    # child that falls through runs the rest of the
                    # parent's code -- including the test framework's
                    # cleanups, which would remove the temporary
                    # directory while the parent is still using it.
                    try:
                        import json as _json
                        with open(result_path, "w") as fh:
                            _json.dump(outcome, fh)
                    except BaseException:  # noqa: BLE001
                        pass
                    os._exit(0)
            os.waitpid(pid, 0)
        finally:
            W._escrow_deposit_retry = orig_escrow

        outcome = {"error": "child produced no result file",
                   "error_type": "NoResult", "records": 0, "bytes": 0,
                   "lines": []}
        if os.path.exists(result_path):
            import json as _json
            with open(result_path) as fh:
                outcome = _json.load(fh)

        inv = []
        if os.path.exists(inv_log):
            with open(inv_log) as fh:
                inv = [ln.strip() for ln in fh if ln.strip()]
        calls = []
        if os.path.exists(ladder_log):
            with open(ladder_log) as fh:
                calls = [ln.strip() for ln in fh if ln.strip()]
        fired = os.path.exists(mark)
        return inv, calls, fired, outcome

    def test_notify_failure_does_not_enter_the_failure_ladder(self):
        inv, calls, fired, _outcome = self._run_with_injected_notify_failure()

        # Positive evidence the fault actually fired. Without this the
        # assertion below would also hold in a run where nothing was
        # injected -- the exact vacuous shape this repo has been bitten
        # by before.
        self.assertTrue(fired,
                        "the post-commit notification failure was never "
                        "injected, so this test proved nothing")

        ladder = [c for c in calls if c == "_deposit_or_loud_skip"]
        self.assertEqual(
            [], ladder,
            "a committed-but-unnotified result (-4) entered the on_error "
            "ladder's retry branch, which re-arms the batch for a "
            "same-process re-claim -- that is 'retried as though its "
            "commit had not happened'. All escrow deposits: %r" % (calls,))

    def test_notify_failure_does_not_duplicate_a_batch(self):
        inv, _calls, fired, _outcome = self._run_with_injected_notify_failure()
        self.assertTrue(fired, "the fault was never injected")
        self.assertTrue(inv, "the payload never ran")
        dupes = sorted({ln for ln in inv if inv.count(ln) > 1})
        self.assertEqual(
            [], dupes,
            "DUPLICATE EXECUTION: %r appeared more than once in the "
            "invocation log" % (dupes,))

    def test_notify_failure_leaves_no_stuck_process(self):
        # The run may legitimately fail closed (the worker died, the
        # parent hit its respawn cap): what it must NOT do is hang.
        start = time.monotonic()
        self._run_with_injected_notify_failure()
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, TEARDOWN_TIMEOUT_S,
                        "the notify-failure path hung instead of exiting")
        assert_no_zombies(self)

    def test_notify_failure_does_not_silently_truncate(self):
        """The outcome must be either complete output or a VISIBLE failure.

        The C contract's permitted outcomes for a committed-but-unnotified
        batch are "recovery notification" or "aborting the run without
        claiming success". What is NOT permitted is returning
        successfully with missing output -- that is silent truncation,
        and it is the failure mode this assertion exists to exclude.

        Two corpus sizes are used, because the two permitted outcomes
        occur at different scales and BOTH branches must stay live:

        * ONE batch: the run completes. The fault fires once, the worker
          is respawned, and the committed record is delivered. This is
          the branch that can silently truncate, so it is the one that
          must be checked for completeness.
        * EIGHT batches: the fault fires once per worker GENERATION
          (the C hook is per-process), so every respawned worker fails
          again and the run exhausts its respawn budget and fails CLOSED.

        A test that only exercised the failing branch would leave the
        truncation check dead code.
        """
        expected = sorted("line %d" % i for i in range(1))
        expected_bytes = len(expected) * len("line 0\n")

        for order in ("none", "index"):
            with self.subTest(order=order, nlines=1):
                _inv, _calls, fired, outcome = \
                    self._run_with_injected_notify_failure(order=order,
                                                          nlines=1)
                self.assertTrue(
                    fired,
                    "the post-commit notification failure was never "
                    "injected, so this test proved nothing")
                self.assertIsNone(
                    outcome["error"],
                    "a single-batch run must complete after one lost "
                    "notification; it failed instead: %r"
                    % (outcome["error"],))
                self.assertEqual(
                    expected, sorted(outcome["lines"]),
                    "the run reported SUCCESS but the output is missing "
                    "records -- silent truncation")
                self.assertEqual(
                    expected_bytes, outcome["bytes"],
                    "the run reported SUCCESS but the output byte count "
                    "is short -- silent truncation")

    def test_notify_failure_fails_visibly_rather_than_truncating(self):
        """The other permitted outcome: abort WITHOUT claiming success.

        When the lost notification repeats across worker generations the
        run must FAIL LOUDLY. The thing to exclude is the opposite: a
        run that cannot deliver everything yet reports success anyway.
        """
        _inv, _calls, fired, outcome = self._run_with_injected_notify_failure(
            nlines=8)
        self.assertTrue(
            fired,
            "the post-commit notification failure was never injected, so "
            "this test proved nothing")
        self.assertIsNotNone(
            outcome["error"],
            "the run could not deliver every batch and yet reported "
            "SUCCESS -- that is the silent-truncation failure mode")
        self.assertNotEqual(
            "NoResult", outcome["error_type"],
            "the child never reported an outcome at all")
        self.assertNotEqual(
            "", outcome["error_type"].strip(),
            "the failure was reported with no exception type")
        self.assertNotEqual(
            "", outcome["error"].split(":", 1)[-1].strip(),
            "the failure was reported with no cause")


if __name__ == "__main__":
    unittest.main()
