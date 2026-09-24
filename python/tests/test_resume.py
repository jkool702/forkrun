"""W-PY22 resume/checkpoint: engine-committed output recovery.

Resume is supported ONLY on C-orderer paths (map()/stream() with
orchestrator=True, order="index", UMA, non-splice). All coordinates
are BYTES on the Universal Coordinate Plane (horizon = contiguous
committed input offset; jagged = committed intervals beyond it) —
never batch numbers.

Semantic contract under test: ENGINE COMMIT is exactly-once (the
C orderer's committed frontier survives abort+resume without
duplication); PYTHON CONSUMPTION is not (a crash between commit
and observation means the checkpoint skips bytes the caller never
saw — the stream test documents this consumer gap).

Test inputs use fixed-width lines ("line %05d\\n" = 11 bytes) so
byte ranges map exactly to line sets.
"""

import gc
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate, get  # noqa: E402
from forkrun._checkpoint import (CheckpointState,  # noqa: E402
                                 check_checkpoint_safety,
                                 collapse_intervals, parse_checkpoint,
                                 serialize_checkpoint,
                                 snapshot_from_engine, write_checkpoint)

from _helpers import assert_no_zombies  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

LINE_FMT = "line %05d\n"
LINE_BYTES = 11  # len("line 00000\n")


def _write_input(path, n):
    with open(path, "w") as fh:
        for i in range(n):
            fh.write(LINE_FMT % i)


def _lines_list(blob):
    """Line numbers in order, duplicates kept (multiset proofs)."""
    out = []
    for line in blob.split(b"\n"):
        if line.startswith(b"LINE "):
            try:
                out.append(int(line[5:]))
            except ValueError:
                pass
    return out


def _lines_of(blob):
    """Line numbers (ints) contained in an upper-cased output blob."""
    return set(_lines_list(blob))


def _framed_lines(blob):
    """Line numbers in a FRAMED record stream (sidecar/coll bytes).

    The 16-byte [idx][len] headers are binary: a naive split on
    newlines misparses whenever a header contains 0x0A (eating the
    next record's first line) or at blob offset 0 (binary prefix).
    Always decode framing first.
    """
    from forkrun.run import _parse_records
    return _lines_list(b"".join(data for _, data in
                                _parse_records(blob)))


def _byte_lines(start_byte, end_byte):
    """Line numbers fully inside [start_byte, end_byte)."""
    first = (start_byte + LINE_BYTES - 1) // LINE_BYTES
    last = (end_byte - 1) // LINE_BYTES if end_byte > 0 else -1
    return set(range(first, last + 1))


def _up(batch):
    return bytes(batch.data).upper()


def _write_file(path, content):
    with open(path, "w") as fh:
        fh.write(content)


class TestCheckpointCodec(unittest.TestCase):
    def test_parse_valid(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            _write_file(path, "FORKRUN_RESUME_HORIZON=12345\n"
                              "FORKRUN_RESUME_STDOUT_BYTES=678\n"
                              "FORKRUN_RESUME_JAGGED=(\"0:100\" "
                              "\"200:300\")\n")
            state = parse_checkpoint(path)
            self.assertEqual(state.horizon, 12345)
            self.assertEqual(state.stdout_bytes, 678)
            self.assertEqual(state.jagged, [(0, 100), (200, 300)])
        finally:
            os.unlink(path)

    def test_parse_empty_jagged(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            _write_file(path, "FORKRUN_RESUME_HORIZON=0\n"
                              "FORKRUN_RESUME_STDOUT_BYTES=0\n"
                              "FORKRUN_RESUME_JAGGED=()\n")
            state = parse_checkpoint(path)
            self.assertEqual((state.horizon, state.stdout_bytes,
                              state.jagged), (0, 0, []))
        finally:
            os.unlink(path)

    def test_parse_missing_lines(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            _write_file(path, "FORKRUN_RESUME_HORIZON=1\n"
                              "FORKRUN_RESUME_STDOUT_BYTES=2\n")
            with self.assertRaises(ValueError):
                parse_checkpoint(path)
        finally:
            os.unlink(path)

    def test_parse_extra_lines(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            _write_file(path, "FORKRUN_RESUME_HORIZON=1\n"
                              "FORKRUN_RESUME_STDOUT_BYTES=2\n"
                              "FORKRUN_RESUME_JAGGED=()\n"
                              "EXTRA=1\n")
            with self.assertRaises(ValueError):
                parse_checkpoint(path)
        finally:
            os.unlink(path)

    def test_parse_wrong_order(self):
        # Keys must appear in HORIZON/STDOUT/JAGGED order (positional).
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            _write_file(path, "FORKRUN_RESUME_JAGGED=()\n"
                              "FORKRUN_RESUME_STDOUT_BYTES=2\n"
                              "FORKRUN_RESUME_HORIZON=1\n")
            with self.assertRaises(ValueError):
                parse_checkpoint(path)
        finally:
            os.unlink(path)

    def test_parse_bad_interval(self):
        for bad in ("\"100:100\"", "\"200:100\"", "\"x:10\"",
                    "\"10\"", "10:20"):
            fd, path = tempfile.mkstemp(suffix=".ckpt")
            os.close(fd)
            try:
                _write_file(path, "FORKRUN_RESUME_HORIZON=1\n"
                                  "FORKRUN_RESUME_STDOUT_BYTES=2\n"
                                  "FORKRUN_RESUME_JAGGED=(%s)\n" % bad)
                with self.assertRaises(ValueError, msg=bad):
                    parse_checkpoint(path)
            finally:
                os.unlink(path)

    def test_parse_hex_rejected(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            _write_file(path, "FORKRUN_RESUME_HORIZON=0x10\n"
                              "FORKRUN_RESUME_STDOUT_BYTES=2\n"
                              "FORKRUN_RESUME_JAGGED=()\n")
            with self.assertRaises(ValueError):
                parse_checkpoint(path)
        finally:
            os.unlink(path)

    def test_parse_negative_rejected(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            _write_file(path, "FORKRUN_RESUME_HORIZON=-5\n"
                              "FORKRUN_RESUME_STDOUT_BYTES=2\n"
                              "FORKRUN_RESUME_JAGGED=()\n")
            with self.assertRaises(ValueError):
                parse_checkpoint(path)
        finally:
            os.unlink(path)

    def test_parse_u64_bounds(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            _write_file(path, "FORKRUN_RESUME_HORIZON=%d\n"
                              "FORKRUN_RESUME_STDOUT_BYTES=0\n"
                              "FORKRUN_RESUME_JAGGED=()\n"
                              % ((1 << 64) - 1))
            state = parse_checkpoint(path)
            self.assertEqual(state.horizon, (1 << 64) - 1)
            _write_file(path, "FORKRUN_RESUME_HORIZON=%d\n"
                              "FORKRUN_RESUME_STDOUT_BYTES=0\n"
                              "FORKRUN_RESUME_JAGGED=()\n" % (1 << 64,))
            with self.assertRaises(ValueError):
                parse_checkpoint(path)
        finally:
            os.unlink(path)

    def test_parse_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            parse_checkpoint("/nonexistent/forkrun-test.ckpt")

    def test_roundtrip(self):
        state = CheckpointState(999, 111, [(50, 60), (0, 10), (5, 55)])
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            write_checkpoint(path, state)
            back = parse_checkpoint(path)
            # Serialized form is sorted + collapsed (bash-canonical).
            self.assertEqual(back, CheckpointState(999, 111,
                                                  [(0, 60)]))
            self.assertEqual(oct(os.stat(path).st_mode & 0o777),
                             "0o600")
        finally:
            os.unlink(path)

    def test_collapse(self):
        self.assertEqual(
            collapse_intervals([(5, 10), (1, 3), (2, 6), (20, 25)]),
            [(1, 10), (20, 25)])
        self.assertEqual(collapse_intervals([(0, 5), (5, 10)]),
                         [(0, 10)])

    def test_serialize_degenerate_rejected(self):
        with self.assertRaises(ValueError):
            serialize_checkpoint(CheckpointState(0, 0, [(10, 10)]))

    def test_max_intervals(self):
        many = " ".join("\"%d:%d\"" % (2 * i, 2 * i + 1)
                        for i in range(1025))
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            _write_file(path, "FORKRUN_RESUME_HORIZON=1\n"
                              "FORKRUN_RESUME_STDOUT_BYTES=2\n"
                              "FORKRUN_RESUME_JAGGED=(%s)\n" % many)
            with self.assertRaises(ValueError):
                parse_checkpoint(path)
        finally:
            os.unlink(path)

    def test_atomic_write_preserves_previous(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            write_checkpoint(path, CheckpointState(7, 8, [(1, 2)]))
            # A failed publication (target is a directory) leaves the
            # previous checkpoint byte-identical.
            os.mkdir(path + ".d")
            try:
                with self.assertRaises(Exception):
                    write_checkpoint(path + ".d",
                                     CheckpointState(9, 9, []))
            finally:
                os.rmdir(path + ".d")
            self.assertEqual(parse_checkpoint(path),
                             CheckpointState(7, 8, [(1, 2)]))
        finally:
            os.unlink(path)

    def test_safety(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        try:
            write_checkpoint(path, CheckpointState(1, 2, []))
            ok, _ = check_checkpoint_safety(path)
            self.assertTrue(ok)
            os.chmod(path, 0o664)
            ok, warnings = check_checkpoint_safety(path)
            self.assertFalse(ok)
            self.assertTrue(warnings)
            ok, _ = check_checkpoint_safety(path + ".missing")
            self.assertFalse(ok)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestSnapshotAPI(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_symbols_present(self):
        lib = get()
        for sym in ("fr_py_resume_snapshot", "fr_py_set_resume_state",
                    "fr_py_is_resume_mode"):
            self.assertTrue(hasattr(lib, sym), sym)
        from forkrun._bindings import v1_available
        self.assertTrue(v1_available().get("resume"))

    def test_set_snapshot_roundtrip(self):
        from forkrun._resume import _set_engine_state
        lib = get()
        lib.fr_py_init(0, 0)
        try:
            self.assertEqual(lib.fr_py_is_resume_mode(), 0)
            _set_engine_state(
                lib, CheckpointState(12345, 678, [(30, 40), (10, 20)]))
            self.assertEqual(lib.fr_py_is_resume_mode(), 1)
            snap = snapshot_from_engine(lib)
            # Snapshot returns engine-sorted intervals.
            self.assertEqual(snap, CheckpointState(12345, 678,
                                                  [(10, 20), (30, 40)]))
        finally:
            lib.fr_py_destroy()
        self.assertEqual(lib.fr_py_is_resume_mode(), 0)

    def test_snapshot_no_progress(self):
        lib = get()
        lib.fr_py_init(0, 0)
        try:
            snap = snapshot_from_engine(lib)
            self.assertIsNotNone(snap)
            self.assertEqual(snap.horizon, 0)
            self.assertEqual(snap.jagged, [])
        finally:
            lib.fr_py_destroy()


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestResumePathValidation(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def _ckpt(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        write_checkpoint(path, CheckpointState(0, 0, []))
        self.addCleanup(os.unlink, path)
        return path

    def _input(self, n=500):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        _write_input(path, n)
        self.addCleanup(os.unlink, path)
        return path

    def test_resume_without_orderer_fails(self):
        with self.assertRaises(RuntimeError):
            forkrun.map(_up, self._input(), workers=2,
                        orchestrator=True, order="none",
                        resume=self._ckpt(), nodes=1)

    def test_resume_without_reactor_fails(self):
        with self.assertRaises(RuntimeError):
            forkrun.map(_up, self._input(), workers=2,
                        order="index", resume=self._ckpt(), nodes=1)

    def test_resume_splice_fails(self):
        with self.assertRaises(RuntimeError):
            forkrun.map(None, self._input(), workers=2, mode="splice",
                        bytes=1024, orchestrator=True, order="index",
                        resume=self._ckpt(), nodes=1)

    def test_resume_numa_fails(self):
        with self.assertRaises(RuntimeError):
            forkrun.map(_up, self._input(), workers=2,
                        orchestrator=True, order="index", nodes="@2",
                        resume=self._ckpt())

    def test_resume_missing_file_fails(self):
        with self.assertRaises(FileNotFoundError):
            forkrun.map(_up, self._input(), workers=2,
                        orchestrator=True, order="index",
                        resume="/nonexistent/forkrun-test.ckpt", nodes=1)

    def test_resume_bad_type_fails(self):
        with self.assertRaises(TypeError):
            forkrun.map(_up, self._input(), workers=2,
                        orchestrator=True, order="index", resume=123, nodes=1)

    def test_resume_malformed_fails(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        _write_file(path, "garbage\n")
        with self.assertRaises(ValueError):
            forkrun.map(_up, self._input(), workers=2,
                        orchestrator=True, order="index",
                        resume=path, nodes=1)

    def test_run_resume_fails(self):
        with self.assertRaises(RuntimeError):
            forkrun.run(_up, self._input(), workers=2,
                        resume=self._ckpt(), nodes=1)

    def test_run_checkpoint_file_fails(self):
        with self.assertRaises(RuntimeError):
            forkrun.run(_up, self._input(), workers=2,
                        checkpoint_file=self._ckpt() + ".out", nodes=1)

    def test_checkpoint_file_unsupported_path_fails(self):
        dest = self._ckpt() + ".out"
        with self.assertRaises(RuntimeError):
            forkrun.map(_up, self._input(), workers=2,
                        order="none", checkpoint_file=dest, nodes=1)
        self.assertFalse(os.path.exists(dest))

    def test_stream_resume_unsupported_path_fails(self):
        with self.assertRaises(RuntimeError):
            list(forkrun.stream(_up, self._input(), workers=2,
                                order="none", resume=self._ckpt(), nodes=1))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestResumeExecution(unittest.TestCase):
    """Abort -> checkpoint -> resume cycles (byte-coordinate proofs).

    Abort mechanism: a file-append counter shared by forked workers
    (O_APPEND 1-byte writes are atomic). The K-th executed batch
    raises (fail-fast) or SIGINTs the parent. Execution counting
    (not content markers) makes progress-before-abort deterministic:
    at most `workers` batches can be in flight, so K executions
    guarantee >= K - workers commits.
    """

    def tearDown(self):
        assert_no_zombies(self)

    def _input(self, n=20000):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        _write_input(path, n)
        self.addCleanup(os.unlink, path)
        return path

    def _counter_payload(self, counter_path, limit, action="raise",
                           fired_path=None):
        """Top-level payload factory (fork-safe: state in files)."""
        def _payload(batch):
            with open(counter_path, "ab") as fh:
                fh.write(b"x")
            try:
                count = os.path.getsize(counter_path)
            except OSError:
                count = 0
            if count >= limit:
                if action == "raise":
                    raise RuntimeError("synthetic abort")
                if action == "sigint":
                    # Single-shot: exactly one SIGINT per run (a second
                    # delivery mid-choreography would kill the runner —
                    # O_EXCL creation is atomic across workers).
                    try:
                        fd = os.open(fired_path,
                                     os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                        os.close(fd)
                    except OSError:
                        return bytes(batch.data).upper()
                    import signal
                    os.kill(os.getppid(), signal.SIGINT)
            return bytes(batch.data).upper()
        return _payload

    def _abort_run(self, path, counter, limit, ckpt, action="raise",
                   workers=2):
        """Run to a synthetic abort; return nothing (asserts abort)."""
        with self.assertRaises(RuntimeError):
            forkrun.map(self._counter_payload(counter, limit, action),
                        path, workers=workers, orchestrator=True,
                        order="index", on_error="fail-fast",
                        checkpoint_file=ckpt, nodes=1)
        self.assertTrue(os.path.exists(ckpt),
                        "abort with progress must checkpoint")

    def test_resume_worker_crash(self):
        path = self._input()
        counter = path + ".count"
        ckpt = path + ".ckpt"
        for f in (counter, ckpt, ckpt + ".coll"):
            if os.path.exists(f):
                os.unlink(f)
            self.addCleanup(
                lambda f=f: os.path.exists(f) and os.unlink(f))
        self._abort_run(path, counter, 8, ckpt)
        state = parse_checkpoint(ckpt)
        self.assertGreater(state.horizon, 0)

    def test_no_checkpoint_no_progress(self):
        # Single worker, first execution aborts: nothing committed.
        path = self._input(n=2000)
        counter = path + ".count"
        ckpt = path + ".ckpt"
        for f in (counter, ckpt, ckpt + ".coll"):
            if os.path.exists(f):
                os.unlink(f)
            self.addCleanup(
                lambda f=f: os.path.exists(f) and os.unlink(f))
        with self.assertRaises(RuntimeError):
            forkrun.map(self._counter_payload(counter, 1), path,
                        workers=1, orchestrator=True, order="index",
                        on_error="fail-fast", checkpoint_file=ckpt, nodes=1)
        self.assertFalse(os.path.exists(ckpt))

    def test_no_checkpoint_on_success(self):
        path = self._input(n=2000)
        ckpt = path + ".ckpt"
        self.addCleanup(
            lambda: os.path.exists(ckpt) and os.unlink(ckpt))
        res = forkrun.map(_up, path, workers=2, orchestrator=True,
                      order="index", checkpoint_file=ckpt, nodes=1)
        self.assertTrue(res)
        self.assertFalse(os.path.exists(ckpt))

    def test_resume_committed_intervals_skipped(self):
        """Byte-coordinate proof: the resumed run never re-executes
        committed bytes (output-derived line coverage)."""
        n = 20000
        path = self._input(n=n)
        counter = path + ".count"
        ckpt = path + ".ckpt"
        for f in (counter, ckpt, ckpt + ".coll"):
            if os.path.exists(f):
                os.unlink(f)
            self.addCleanup(
                lambda f=f: os.path.exists(f) and os.unlink(f))
        self._abort_run(path, counter, 8, ckpt)
        state = parse_checkpoint(ckpt)
        committed = _byte_lines(0, state.horizon)
        for s, e in state.jagged:
            committed |= _byte_lines(s, e)
        self.assertTrue(committed)
        # The resumed call returns sidecar ++ fresh (concat). Multiset
        # difference isolates the fresh contribution: it must avoid
        # every committed byte (byte-coordinate skip proof).
        from collections import Counter
        with open(ckpt + ".coll", "rb") as fh:
            sidecar_blob = fh.read()
        res = forkrun.map(_up, path, workers=4, orchestrator=True,
                          order="index", resume=ckpt, nodes=1)
        # Non-vacuity: the resumed run delivered NEW records beyond
        # the sidecar (concat, no dedup — length strictly grows).
        from forkrun.run import _parse_records
        self.assertGreater(len(res),
                           len(_parse_records(sidecar_blob)))
        fresh = Counter(_lines_list(b"".join(res)))
        fresh.subtract(_framed_lines(sidecar_blob))
        fresh_lines = {line for line, c in fresh.items() if c > 0}
        self.assertFalse(fresh_lines & committed,
                         "resumed run re-executed committed bytes")

    def test_resume_complete_output(self):
        """Abort + resume = byte-identical to an uninterrupted run."""
        n = 20000
        path = self._input(n=n)
        counter = path + ".count"
        ckpt = path + ".ckpt"
        for f in (counter, ckpt, ckpt + ".coll"):
            if os.path.exists(f):
                os.unlink(f)
            self.addCleanup(
                lambda f=f: os.path.exists(f) and os.unlink(f))
        self._abort_run(path, counter, 8, ckpt)
        res = forkrun.map(_up, path, workers=4, orchestrator=True,
                          order="index", resume=ckpt, nodes=1)
        expect = forkrun.map(_up, path, workers=4, orchestrator=True,
                             order="index", nodes=1)
        self.assertEqual(b"".join(res), b"".join(expect))
        self.assertEqual(len(res), len(expect))
        # Sidecar consumed exactly once (no resurrection source).
        self.assertFalse(os.path.exists(ckpt + ".coll"))

    def test_engine_commit_exactly_once(self):
        """No input line is delivered twice across abort + resume."""
        n = 20000
        path = self._input(n=n)
        counter = path + ".count"
        ckpt = path + ".ckpt"
        for f in (counter, ckpt, ckpt + ".coll"):
            if os.path.exists(f):
                os.unlink(f)
            self.addCleanup(
                lambda f=f: os.path.exists(f) and os.unlink(f))
        self._abort_run(path, counter, 8, ckpt)
        # Aborted run's committed output (sidecar, read BEFORE the
        # resume consumes it) + resumed output: every input line
        # exactly once (multiset proof — any cross-run duplicate
        # would appear twice in the final concatenation).
        with open(ckpt + ".coll", "rb") as fh:
            sidecar_list = _framed_lines(fh.read())
        self.assertEqual(len(sidecar_list), len(set(sidecar_list)))
        res = forkrun.map(_up, path, workers=4, orchestrator=True,
                          order="index", resume=ckpt, nodes=1)
        final_list = _lines_list(b"".join(res))
        self.assertEqual(len(final_list), len(set(final_list)),
                         "duplicate delivery across abort+resume")
        self.assertEqual(set(final_list), set(range(n)))

    def test_multi_resume_cumulative(self):
        """Two aborts then completion: frontiers mount, union whole."""
        n = 20000
        path = self._input(n=n)
        ckpt = path + ".ckpt"
        for f in (ckpt, ckpt + ".coll"):
            if os.path.exists(f):
                os.unlink(f)
            self.addCleanup(
                lambda f=f: os.path.exists(f) and os.unlink(f))
        counter1 = path + ".c1"
        self.addCleanup(
            lambda: os.path.exists(counter1) and os.unlink(counter1))
        self._abort_run(path, counter1, 8, ckpt)
        h1 = parse_checkpoint(ckpt).horizon
        self.assertGreater(h1, 0)
        counter2 = path + ".c2"
        self.addCleanup(
            lambda: os.path.exists(counter2) and os.unlink(counter2))
        with self.assertRaises(RuntimeError):
            forkrun.map(self._counter_payload(counter2, 12), path,
                        workers=2, orchestrator=True, order="index",
                        on_error="fail-fast", resume=ckpt,
                        checkpoint_file=ckpt, nodes=1)
        self.assertTrue(os.path.exists(ckpt))
        h2 = parse_checkpoint(ckpt).horizon
        self.assertGreaterEqual(h2, h1)
        res = forkrun.map(_up, path, workers=4, orchestrator=True,
                          order="index", resume=ckpt, nodes=1)
        expect = forkrun.map(_up, path, workers=4, orchestrator=True,
                             order="index", nodes=1)
        self.assertEqual(b"".join(res), b"".join(expect))

    def test_resume_sigint(self):
        """SIGINT mid-pipeline checkpoints; resume completes."""
        n = 20000
        path = self._input(n=n)
        counter = path + ".count"
        fired = path + ".fired"
        ckpt = path + ".ckpt"
        for f in (counter, fired, ckpt, ckpt + ".coll"):
            if os.path.exists(f):
                os.unlink(f)
            self.addCleanup(
                lambda f=f: os.path.exists(f) and os.unlink(f))
        payload = self._counter_payload(counter, 8, "sigint", fired)
        # The SIGINT trigger needs the default disposition: background
        # launchers (nohup/setsid/CI supervisors without job control)
        # start children with SIGINT ignored, which Python then
        # inherits instead of installing default_int_handler. Pin it
        # explicitly (restored after) so the test is launcher-proof.
        import signal as _signal
        _old_int = _signal.getsignal(_signal.SIGINT)
        _signal.signal(_signal.SIGINT, _signal.default_int_handler)
        try:
            with self.assertRaises(KeyboardInterrupt):
                forkrun.map(payload, path, workers=2, orchestrator=True,
                            order="index", checkpoint_file=ckpt, nodes=1)
        finally:
            _signal.signal(_signal.SIGINT, _old_int)
        self.assertTrue(os.path.exists(ckpt),
                        "SIGINT abort must checkpoint")
        res = forkrun.map(_up, path, workers=4, orchestrator=True,
                          order="index", resume=ckpt, nodes=1)
        expect = forkrun.map(_up, path, workers=4, orchestrator=True,
                             order="index", nodes=1)
        self.assertEqual(b"".join(res), b"".join(expect))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestResumeStream(unittest.TestCase):
    """stream() resume: consumer-owns-yielded contract.

    The consumer persists everything yielded live. After abandon +
    checkpoint, the resumed stream must deliver every byte the
    checkpoint leaves uncommitted (no silent loss); committed-band
    redelivery is the documented consumer gap (not asserted).
    """

    def tearDown(self):
        assert_no_zombies(self)
        gc.collect()

    def _input(self, n=20000):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        _write_input(path, n)
        self.addCleanup(os.unlink, path)
        return path

    def test_stream_abandon_checkpoint_resume(self):
        n = 20000
        path = self._input(n=n)
        ckpt = path + ".ckpt"
        for f in (ckpt, ckpt + ".coll"):
            if os.path.exists(f):
                os.unlink(f)
            self.addCleanup(
                lambda f=f: os.path.exists(f) and os.unlink(f))
        def _slow(batch):
            import time
            time.sleep(0.05)
            return bytes(batch.data).upper()

        gen = forkrun.stream(_slow, path, workers=4, orchestrator=True,
                             order="index", checkpoint_file=ckpt,
                             nodes=1)
        seen = []
        try:
            # ~64 batches for 20k lines at 50ms each: abandon after 20
            # (workers cannot have committed everything yet, so the
            # tail is guaranteed non-empty — no vacuous assertions).
            for i, blob in enumerate(gen):
                seen.append(blob)
                if i >= 19:
                    break
        finally:
            try:
                gen.close()
            except Exception:
                pass
        gc.collect()
        self.assertTrue(os.path.exists(ckpt),
                        "abandoned stream must checkpoint")
        state = parse_checkpoint(ckpt)
        self.assertGreater(state.horizon, 0)
        consumed = _lines_of(b"".join(seen))
        # Everything at/after the committed frontier is delivered
        # by the resumed stream (no silent loss of uncommitted data).
        tail_lines = set(range(n)) - _byte_lines(0, state.horizon)
        for s, e in state.jagged:
            tail_lines -= _byte_lines(s, e)
        self.assertTrue(tail_lines,
                        "abandoned too late — tail vacuous")
        resumed = list(forkrun.stream(
            _up, path, workers=4, orchestrator=True, order="index",
            resume=ckpt, nodes=1))
        resumed_lines = _lines_of(b"".join(resumed))
        self.assertTrue(tail_lines <= resumed_lines,
                        "resumed stream lost uncommitted bytes")


if __name__ == "__main__":
    unittest.main()
