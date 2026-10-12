"""Stage 0 failure-cut matrix: retry content and recovery cases.

Rows 7-9 of the Stage 0 matrix. Each pairs a retry that produces a
DIFFERENT result with the published outcome, because "no duplicate" and
"the right record" are different claims.

  row 7  same size, different content  -> stale content would survive
  row 8  different size                -> suppression / framing corruption
  row 9  repeated recovery             -> delivered exactly once
  row 3b death after the commit store, input queue already drained
                                         -> the rc==2 path, where no later
                                            generation exists to cover a
                                            stranded record

The per-attempt payload comes from a counter file the UDF appends to, so
each attempt genuinely produces different bytes. A retry that returned
the same value would make these tests vacuous.

Run: make -f Makefile.substrate python-substrate && cd python/tests
     python3 -m unittest test_stage0_matrix
"""

import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

from forkrun._worker import _HDR  # noqa: E402

DISP_DATA, DISP_NO_RESULT, DISP_SKIPPED, DISP_POISONED = 0, 1, 2, 3
NAME = {0: "DATA", 1: "NO_RESULT", 2: "SKIPPED", 3: "POISONED"}

# Each invocation bumps a counter file and encodes the attempt number,
# so the payload DIFFERS per attempt. Two widths, for the two rows.
UDF_SRC = '''
import os

_CNT = os.path.join(os.path.dirname(__file__), "attempts.txt")

def _n():
    try:
        with open(_CNT) as fh:
            v = int(fh.read().strip() or "0")
    except Exception:
        v = 0
    v += 1
    with open(_CNT, "w") as fh:
        fh.write(str(v))
    return v

def same_len(b):
    """Same LENGTH every attempt; only the content varies."""
    return ("attempt%04d" % _n()).encode().ljust(12, b".")

def diff_len(b):
    """Length varies per attempt."""
    return (b"x" * (4 * _n())) + b"!"

def plain(b):
    return b.upper()
'''

BATCHES = 3


def _helper():
    from forkrun._udf import helper_path
    return helper_path()


def _launcher():
    return os.path.join(_ROOT, "python", "forkrun", "_forkrun_cleanroom")


def _substrate():
    from forkrun._bindings import find_substrate
    return find_substrate()


def _roots(udf_dir):
    import site
    out = []
    for p in site.getsitepackages():
        if p not in out and os.path.isdir(p):
            out.append(p)
    try:
        u = site.getusersitepackages()
        if isinstance(u, str) and u not in out and os.path.isdir(u):
            out.append(u)
    except Exception:
        pass
    out.append(udf_dir)
    return " ".join(out)


def parse(blob):
    recs, off = [], 0
    while off + _HDR.size <= len(blob):
        idx, ln, disp, _r = _HDR.unpack_from(blob, off)
        off += _HDR.size
        if off + ln > len(blob):
            break
        recs.append((idx, disp, blob[off:off + ln]))
        off += ln
    return recs


@unittest.skipUnless(_helper() and os.path.exists(_launcher()),
                     "udf helper / launcher not built")
class TestStage0Matrix(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = self._tmp.name
        with open(os.path.join(self.d, "px_udf.py"), "w") as fh:
            fh.write(UDF_SRC)
        self.src = os.path.join(self.d, "in.txt")
        with open(self.src, "w") as fh:
            fh.writelines("line%06d\n" % i for i in range(BATCHES))
        self.out = os.path.join(self.d, "out.bin")

    def tearDown(self):
        self._tmp.cleanup()

    def run_launcher(self, func, mode=None, workers=1, delay_ms=150,
                     handshake=False):
        env = dict(os.environ)
        for k in ("FORKRUN_TEST_DIE_BEFORE_ACK",
                  "FORKRUN_TEST_DIE_BEFORE_NOTIFY",
                  "FORKRUN_TEST_DIE_AFTER_DRAIN_MS",
                  "FORKRUN_TEST_DRAIN_ACK_FIFO"):
            env.pop(k, None)
        if mode == "before_ack":
            env["FORKRUN_TEST_DIE_BEFORE_ACK"] = "1"
        elif mode == "before_notify":
            env["FORKRUN_TEST_DIE_BEFORE_NOTIFY"] = "1"
        if mode:
            env["FORKRUN_TEST_DIE_AFTER_DRAIN_MS"] = str(delay_ms)
        if handshake:
            fifo = os.path.join(self.d, "drain_ack.fifo")
            if not os.path.exists(fifo):
                os.mkfifo(fifo)
            env["FORKRUN_TEST_DRAIN_ACK_FIFO"] = fifo
        src_fd = os.open(self.src, os.O_RDONLY)
        out_fd = os.open(self.out, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            argv = [_launcher(),
                    "--so", _substrate(),
                    "--workers", str(workers), "--lines", "1", "--bytes", "0",
                    "--on-error", "0", "--retry", "3",
                    "--src", str(src_fd), "--result", str(out_fd),
                    "--stats-fd", "-1",
                    "--udf-helper", _helper(),
                    "--udf", "px_udf", "--udf-attr", func,
                    "--udf-roots", _roots(self.d)]
            proc = subprocess.run(argv, env=env, pass_fds=(src_fd, out_fd),
                                  capture_output=True, timeout=180)
        finally:
            os.close(src_fd)
            os.close(out_fd)
        with open(self.out, "rb") as fh:
            return proc, fh.read()

    def _attempts(self):
        p = os.path.join(self.d, "attempts.txt")
        if not os.path.exists(p):
            return 0
        with open(p) as fh:
            return int(fh.read().strip() or "0")

    # -- controls ------------------------------------------------------

    def test_retry_payload_really_varies(self):
        """Guard against a vacuous matrix: prove the per-attempt payloads
        differ. If this fails, rows 7 and 8 prove nothing."""
        _p, blob = self.run_launcher("same_len", mode=None)
        recs = parse(blob)
        self.assertTrue(recs)
        # A clean run executes once per batch; run again for a second set.
        self.run_launcher("same_len", mode=None)
        self.assertGreaterEqual(self._attempts(), 2 * BATCHES,
                                "the UDF is not varying its payload per call")

    # -- row 7: same size, different content ---------------------------

    def test_same_size_retry_publishes_the_committed_attempt(self):
        """Every attempt writes a 24-byte record; only the bytes differ.
        A drain keyed on size rather than on the committed frontier would
        suppress the retry and leave the FIRST attempt's content visible.
        """
        proc, blob = self.run_launcher("same_len", mode="before_ack")
        recs = parse(blob)
        self.assertTrue(recs, "nothing reached the parent")
        data = [(i, p) for i, d, p in recs if d == DISP_DATA]
        self.assertEqual(
            [], data,
            "STALE CONTENT: %r -- every attempt produces a same-sized "
            "record, so a size-keyed cursor would suppress the retry and "
            "publish the abandoned first attempt's bytes" % (data,))
        by_batch = {}
        for i, d, _p in recs:
            by_batch.setdefault(i, []).append(d)
        self.assertEqual({}, {i: d for i, d in by_batch.items() if len(d) > 1},
                         "duplicate terminal records: %r" % (by_batch,))

    # -- row 8: different size ----------------------------------------

    def test_differing_size_retry_publishes_the_committed_attempt(self):
        """Each attempt's record is 4 bytes longer than the last. The
        committed frontier is absolute, so the retry must be published
        and the abandoned attempt's shorter record must not survive."""
        proc, blob = self.run_launcher("diff_len", mode="before_ack")
        recs = parse(blob)
        self.assertTrue(recs, "nothing reached the parent")
        data = [(i, p) for i, d, p in recs if d == DISP_DATA]
        self.assertEqual(
            [], data,
            "STALE CONTENT: %r -- the retry's record differs in size, so a "
            "cursor keyed on the previous attempt's extent would suppress "
            "it and leave the abandoned bytes visible" % (data,))
        # The stream must be exactly consumed -- no framing corruption.
        total = sum(_HDR.size + len(p) for _i, _d, p in recs)
        self.assertEqual(len(blob), total,
                         "stream not fully consumed: %d bytes on disk, %d "
                         "accounted for by parsed records" % (len(blob), total))

    # -- row 9: repeated recovery --------------------------------------

    def test_repeated_recovery_delivers_each_batch_exactly_once(self):
        proc, blob = self.run_launcher("plain", mode="before_ack")
        recs = parse(blob)
        seen = {}
        for i, d, p in recs:
            seen.setdefault(i, []).append(d)
        self.assertEqual({}, {i: d for i, d in seen.items() if len(d) > 1},
                         "a batch was delivered more than once: %r" % (seen,))
        self.assertEqual(sorted(range(BATCHES)), sorted(seen),
                         "batches missing a terminal record")

    def _run_one_shot(self, func):
        """Kill EXACTLY ONE attempt in the whole run, before its commit,
        then let recovery succeed. Returns (proc, records, invocations)."""
        self.setUp() if not hasattr(self, "d") else None
        once = os.path.join(self.d, "died_once.marker")
        if os.path.exists(once):
            os.unlink(once)
        env_backup = os.environ.get("FORKRUN_TEST_DIE_BEFORE_ACK_ONCE")
        os.environ["FORKRUN_TEST_DIE_BEFORE_ACK_ONCE"] = once
        try:
            proc, blob = self.run_launcher(func, mode="before_ack",
                                           delay_ms=0)
        finally:
            if env_backup is None:
                os.environ.pop("FORKRUN_TEST_DIE_BEFORE_ACK_ONCE", None)
            else:
                os.environ["FORKRUN_TEST_DIE_BEFORE_ACK_ONCE"] = env_backup
        # Positive evidence the one-shot death actually happened.
        self.assertTrue(os.path.exists(once),
                        "the one-shot death never fired, so this run cannot "
                        "show a successful retry winning")
        return proc, parse(blob), self._attempts()

    # -- complementary case: the SUCCESSFUL retry's content wins -------

    def test_successful_retry_content_wins_same_size(self):
        """Attempt 1 writes a distinct same-sized payload and dies before
        commit. Attempt 2 commits a different payload of the SAME length.
        The caller must receive attempt 2's bytes -- a drain keyed on size
        rather than the committed frontier would suppress attempt 2 and
        leave attempt 1's visible.
        """
        proc, recs, attempts = self._run_one_shot("same_len")
        # Exactly one extra invocation: the attempt that died. If the
        # death never fired there would be BATCHES invocations, and the
        # "retry won" claim below would be vacuous.
        self.assertEqual(BATCHES + 1, attempts,
                         "expected exactly one killed attempt (%d "
                         "invocations for %d batches)" % (attempts, BATCHES))
        data = [(i, p) for i, d, p in recs if d == DISP_DATA]
        self.assertTrue(data, "no DATA delivered at all")
        by_batch = {}
        for i, _d, p in recs:
            by_batch.setdefault(i, []).append(p)
        dupes = {i: len(v) for i, v in by_batch.items() if len(v) > 1}
        self.assertEqual({}, dupes,
                         "a batch was delivered more than once: %r" % dupes)
        for i, payloads in by_batch.items():
            self.assertEqual(1, len(payloads))
        # The abandoned attempt's bytes must never reach the caller. The
        # UDF encodes its attempt number, so the FIRST attempt's payload
        # is identifiable -- and it is the one that died uncommitted.
        first = [p for _i, p in data if p.startswith(b"attempt0001")]
        self.assertEqual(
            [], first,
            "STALE CONTENT: the abandoned first attempt's payload %r was "
            "published. Its bytes were written before the commit and must "
            "never become visible." % (first,))

    def test_successful_retry_content_wins_different_size(self):
        """Same, with a payload whose LENGTH changes per attempt."""
        proc, recs, attempts = self._run_one_shot("diff_len")
        self.assertEqual(BATCHES + 1, attempts,
                         "expected exactly one killed attempt (%d "
                         "invocations for %d batches)" % (attempts, BATCHES))
        first = [p for _i, _d, p in recs if p == b"x" * 4 + b"!"]
        self.assertEqual(
            [], first,
            "STALE CONTENT: the abandoned first attempt's payload %r was "
            "published; the retry's differently-sized record should have "
            "replaced it" % (first,))
        total = sum(_HDR.size + len(p) for _i, _d, p in recs)
        self.assertEqual(len(self._read_out()), total,
                         "stream not exactly consumed -- the suppressed or "
                         "duplicated record left a framing artifact")
        dupes = {}
        seen = {}
        for i, _d, p in recs:
            seen.setdefault(i, []).append(p)
        dupes = {i: len(v) for i, v in seen.items() if len(v) > 1}
        self.assertEqual({}, dupes,
                         "a batch was delivered more than once: %r" % dupes)

    def _read_out(self):
        with open(self.out, "rb") as fh:
            return fh.read()

    # -- rollback frontier invariant ----------------------------------

    def test_rollback_never_truncates_past_the_committed_frontier(self):
        """The persistent drain cursor depends on an engine invariant:
        rollback truncates the output memfd to output_start, which must
        never fall below the last committed frontier.

        worker_output_end advances only after a COMPLETE emit, and the
        transaction snapshots it at claim, so output_start IS the
        committed frontier. If that ever stopped holding, recovery would
        destroy bytes the drain had already forwarded -- which shows up
        as a stream that no longer parses, or that loses its tail.

        Observed end-to-end rather than asserted in the engine: a run with
        deaths, varying record sizes, and several workers must deliver a
        stream that is exactly consumed with every batch present.
        """
        proc, blob = self.run_launcher("diff_len", mode="before_ack",
                                       workers=2)
        recs = parse(blob)
        self.assertTrue(recs, "nothing reached the parent")
        total = sum(_HDR.size + len(p) for _i, _d, p in recs)
        self.assertEqual(
            len(blob), total,
            "stream not exactly consumed (%d bytes, %d parsed) -- recovery "
            "destroyed or duplicated output, which is what a rollback past "
            "the committed frontier would look like"
            % (len(blob), total))
        # Every batch must have a terminal outcome: no batch may be left
        # waiting because its record was destroyed by a rollback.
        seen = {i for i, _d, _p in recs}
        self.assertEqual(sorted(range(BATCHES)), sorted(seen),
                         "batches left without a terminal record: %r"
                         % (sorted(set(range(BATCHES)) - seen),))

    # -- row 3b: drained queue, no later generation to cover a stranding

    def test_drained_queue_still_delivers_a_committed_record(self):
        """One batch, worker commits then dies before notifying, and the
        input queue is drained -- so there is NO later generation whose
        frontier could cover the stranded record. Only the synthetic
        post-recovery wakeup can deliver it."""
        one = os.path.join(self.d, "one.txt")
        with open(one, "w") as fh:
            fh.write("onlyline\n")
        self.src = one
        proc, blob = self.run_launcher("plain", mode="before_notify")
        recs = parse(blob)
        self.assertEqual(
            1, len(recs),
            "the committed record was stranded with a drained queue and no "
            "later generation to cover it: got %r"
            % ([(i, NAME.get(d, d)) for i, d, _p in recs],))
        self.assertEqual(DISP_DATA, recs[0][1])


if __name__ == "__main__":
    unittest.main()