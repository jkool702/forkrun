"""Publication/commit race -- does a forwarded record survive rollback?

The external review of the expansion proposal raised this: the drain
(`fr_py_drain_loop`) forwards a record to the results stream as soon as
it sees the worker's SIGNAL, and does NOT wait for the worker's ack.
Meanwhile the worker has already advanced its rollback frontier
(`worker_txn_advance_output`) for that record. So there is a window in
which:

    worker: frame record -> advance frontier -> SIGNAL
    drain:            see signal -> copy record to results -> PUNCH memfd
    worker:                                                       -> ack

If the worker dies in that window, recovery rolls the transaction back
and retries the batch. The frontier rewind is real, but the record the
drain already copied is NOT in the frontier any more -- it is gone from
the memfd (punched) and already published downstream. Nothing can
retract it. The retry then re-emits.

If that reasoning is right, forcing the drain to run BEFORE the death
yields two records for one batch -- which is exactly the invariant the
existing exactly-once tests claim to hold.

The existing tests cannot see this: DIE_BEFORE_ACK fires immediately
after the signal, so whether the drain has forwarded yet is a scheduler
race. When the worker usually wins that race, the record is still in the
memfd, the rollback rewinds cleanly, and the test passes -- for the
wrong reason. It proves "rollback works when nothing was published
yet", not "publication is consistent with commit".

FORKRUN_TEST_DIE_AFTER_DRAIN_MS exists to remove the race.

Run: make -f Makefile.substrate udf && python3 -m unittest test_drain_publication_race
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

UDF_SRC = "def up(b):\n    return b.upper()\n"
BATCHES = 5


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
    recs, off, n = [], 0, len(blob)
    while off + _HDR.size <= n:
        idx, ln, disp, _res = _HDR.unpack_from(blob, off)
        off += _HDR.size
        if off + ln > n:
            break
        recs.append((idx, disp, blob[off:off + ln]))
        off += ln
    return recs


@unittest.skipUnless(_helper() and os.path.exists(_launcher()),
                     "udf helper / launcher not built")
class TestPublicationCommitRace(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        d = cls._tmp.name
        with open(os.path.join(d, "px_udf.py"), "w") as fh:
            fh.write(UDF_SRC)
        cls.src = os.path.join(d, "in.txt")
        with open(cls.src, "w") as fh:
            fh.writelines("line%06d\n" % i for i in range(BATCHES))
        cls.out = os.path.join(d, "out.bin")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_launcher(self, die_after_drain_ms=None):
        env = dict(os.environ)
        env["FORKRUN_TEST_DIE_BEFORE_ACK"] = "1"
        if die_after_drain_ms is None:
            env.pop("FORKRUN_TEST_DIE_AFTER_DRAIN_MS", None)
        else:
            env["FORKRUN_TEST_DIE_AFTER_DRAIN_MS"] = str(die_after_drain_ms)
        src_fd = os.open(self.src, os.O_RDONLY)
        out_fd = os.open(self.out, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            argv = [_launcher(),
                    "--so", _substrate(),
                    "--workers", "2", "--lines", "1", "--bytes", "0",
                    "--on-error", "0", "--retry", "3",
                    "--src", str(src_fd), "--result", str(out_fd),
                    "--stats-fd", "-1",
                    "--udf-helper", _helper(),
                    "--udf", "px_udf", "--udf-attr", "up",
                    "--udf-roots", _roots(self._tmp.name)]
            proc = subprocess.run(argv, env=env, pass_fds=(src_fd, out_fd),
                                  capture_output=True, timeout=180)
        finally:
            os.close(src_fd)
            os.close(out_fd)
        with open(self.out, "rb") as fh:
            return proc, fh.read()

    def _duplicates(self, blob):
        seen = {}
        for idx, disp, _p in parse(blob):
            seen.setdefault(idx, []).append(disp)
        return {i: d for i, d in seen.items() if len(d) > 1}

    def test_racy_window_is_not_the_interesting_one(self):
        """Baseline: existing tests' timing. Assert it is at least
        self-consistent, so a failure below is attributable to the
        forced window and not to a broken harness."""
        _proc, blob = self.run_launcher(die_after_drain_ms=None)
        recs = parse(blob)
        self.assertTrue(recs, "no records reached the parent at all")
        self.assertEqual({}, self._duplicates(blob),
                         "baseline already duplicated")

    def test_drain_forwards_before_death_still_yields_one_record_per_batch(self):
        """THE RACE.

        The worker signals, the drain demonstrably forwards, and only
        then does the worker die. Recovery retries the batch. If
        publication were consistent with the commit point, each batch
        would still show exactly one record.

        This is the assertion the existing exactly-once tests cannot
        make: they die before the drain has moved the bytes, so the
        rollback is still able to retract them.
        """
        _proc, blob = self.run_launcher(die_after_drain_ms=150)
        recs = parse(blob)
        self.assertTrue(recs, "no records reached the parent at all")

        dupes = self._duplicates(blob)
        self.assertEqual(
            {}, dupes,
            "DUPLICATE PUBLICATION: a batch reached the results stream "
            "more than once because the drain forwarded its record before "
            "the worker acked, and the rollback could not retract what had "
            "already been copied out and punched. %r -- a duplicate shifts "
            "every later batch and breaks ordered reassembly outright."
            % (dupes,))

        missing = sorted(set(range(BATCHES)) - {i for i, _d, _p in recs})
        self.assertEqual([], missing,
                         "batches lost when the record had already been "
                         "forwarded: %r" % (missing,))

    def test_no_contradictory_terminal_outcomes(self):
        """A retried batch must not disagree with itself.

        If attempt 1 published SKIPPED and the retry produced DATA, an
        ordered consumer would have advanced the prefix on SKIPPED and
        then seen data for a batch it had already closed -- the precise
        inconsistency the proposal relies on dispositions to prevent.
        """
        _proc, blob = self.run_launcher(die_after_drain_ms=150)
        by_batch = {}
        for idx, disp, _p in parse(blob):
            by_batch.setdefault(idx, []).append(disp)
        contradictions = {
            i: d for i, d in by_batch.items()
            if len(set(d)) > 1 and not (set(d) == {DISP_POISONED})
        }
        self.assertEqual(
            {}, contradictions,
            "a batch published two DIFFERENT terminal dispositions: %r"
            % (contradictions,))


if __name__ == "__main__":
    unittest.main()