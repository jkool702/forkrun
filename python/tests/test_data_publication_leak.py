"""DATA published, then abandoned: does a poisoned batch leak its result?

Round-2 review, round-3 response: the forced-window experiment in
`test_drain_publication_race` does NOT establish publication/commit
consistency, and it predicted a concrete counterexample from the source:

    1. attempt computes nonempty DATA of length n
    2. worker writes + signals; drain forwards it; cursor -> s + 24 + n
    3. worker killed before ack
    4. recovery truncates the output memfd back to s, batch retried
    5. retry emits POISONED -- 24 bytes, zero payload
    6. memfd size is now s + 24, so the drain's `size <= offset` check
       SUPPRESSES the retry record
    7. the abandoned DATA is already downstream and cannot be recalled

Observable result: DATA returned for a batch whose recovered terminal
outcome is POISONED.

That prior experiment could never have caught this. Its hook fires
BEFORE `fr_py_complete`, which is where the DATA record is actually
signalled -- so a DATA record was written, never signalled, never
forwarded, and rolled back cleanly. It only ever forwarded POISONED
records, all 24 bytes, all the same size, all correctly suppressed on
retry. "Exactly one record" held because the DATA path was never
exercised.

`FORKRUN_TEST_DIE_AFTER_SIGNAL` kills after the payload record is
written AND signalled, reaching the interval in question.

Run: make -f Makefile.substrate udf && python3 -m unittest test_data_publication_leak
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

UDF_SRC = "def up(b):\n    return b.upper()\n"
BATCHES = 4


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
class TestDataPublicationLeak(unittest.TestCase):

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

    def run_launcher(self, mode, delay_ms=150):
        """mode: 'clean' | 'after_signal'"""
        env = dict(os.environ)
        for k in ("FORKRUN_TEST_DIE_BEFORE_ACK",
                  "FORKRUN_TEST_DIE_AFTER_SIGNAL",
                  "FORKRUN_TEST_DIE_AFTER_DRAIN_MS"):
            env.pop(k, None)
        if mode == "after_signal":
            env["FORKRUN_TEST_DIE_AFTER_SIGNAL"] = "1"
            env["FORKRUN_TEST_DIE_AFTER_DRAIN_MS"] = str(delay_ms)
        src_fd = os.open(self.src, os.O_RDONLY)
        out_fd = os.open(self.out, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            argv = [_launcher(),
                    "--so", _substrate(),
                    "--workers", "1", "--lines", "1", "--bytes", "0",
                    "--on-error", "0", "--retry", "1",
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

    # -- the tests ----------------------------------------------------

    def test_control_unfaulted_run_delivers_data(self):
        _p, blob = self.run_launcher("clean")
        recs = parse(blob)
        self.assertEqual(BATCHES, len(recs), "control is broken: %r" % (recs,))
        for _i, disp, _p in recs:
            self.assertEqual(DISP_DATA, disp)

    @unittest.expectedFailure
    def test_no_data_survives_for_a_batch_that_recovery_poisoned(self):
        """THE COUNTEREXAMPLE -- CONFIRMED, currently failing.

        Marked expectedFailure on purpose: it passes the moment the
        publication/commit protocol is fixed, and unittest reports that
        as an unexpected success. That is the signal we want. It is not
        marked skip, because a skipped bug is a forgotten bug.

        DATA is forwarded by the drain, THEN the worker dies, THEN
        recovery retries and poisons the batch. The retry's 24-byte
        POISONED record should replace the abandoned 32-byte DATA
        record. Instead the drain's monotonic cursor suppresses the
        retry and the abandoned DATA survives.
        """
        proc, blob = self.run_launcher("after_signal")
        recs = parse(blob)
        self.assertTrue(recs, "nothing reached the parent; harness is wrong")

        print("\n  stream: %r" % ([(i, NAME.get(d, d), p[:14])
                                   for i, d, p in recs],))
        print("  launcher rc=%s" % proc.returncode)

        # Every record must be a terminal disposition, and no DATA may
        # be present: with the after-signal hook every generation dies
        # before acking, so --retry 1 guarantees the batch poisons.
        leaked = [(i, NAME.get(d, d), p) for i, d, p in recs if d == DISP_DATA]
        self.assertEqual(
            [], leaked,
            "PUBLICATION LEAK: %r -- DATA from an abandoned attempt reached "
            "the result stream for a batch that recovery poisoned. The "
            "drain forwarded the record before the ack; the rollback "
            "truncated the worker memfd but could not retract the bytes "
            "already forwarded, and the retry's SHORTER POISONED record "
            "was suppressed by the drain's monotonic cursor."
            % (leaked,))

    def test_terminal_outcome_matches_poison_accounting(self):
        """The published terminal record must agree with the outcome the
        engine committed -- not merely be singular."""
        _p, blob = self.run_launcher("after_signal")
        recs = parse(blob)
        by_batch = {}
        for idx, disp, _pl in recs:
            by_batch.setdefault(idx, []).append(disp)
        contradictory = {i: d for i, d in by_batch.items() if len(set(d)) > 1}
        self.assertEqual(
            {}, contradictory,
            "a batch published two different terminal outcomes: %r"
            % (contradictory,))


if __name__ == "__main__":
    unittest.main()