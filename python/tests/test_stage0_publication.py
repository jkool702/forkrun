"""Stage 0 publication protocol: safety and completeness.

The Stage 0 protocol makes publication strictly post-commit. Two
properties follow, and they are independent:

  SAFETY      nothing from an uncommitted attempt is ever visible.
              Inject a death AFTER the record is written but BEFORE the
              commit. The drain must never publish it.

  COMPLETENESS every committed record is delivered exactly once.
              Inject a death AFTER the commit but BEFORE the drain is
              notified. Recovery must wake the drain, or the committed
              result is stranded forever.

Both normally use FORKRUN_TEST_DIE_AFTER_DRAIN_MS to widen the window.

test_drain_was_awake_replaces_a_sleep with a HANDSHAKE: the drain
publishes (worker, cursor) on a FIFO for every wakeup it processes, and
the worker blocks until it sees its own before dying. Without that, a
passing test cannot distinguish "the drain forwarded, then the worker
died" from "the drain never ran, so the window was never exercised" --
an ambiguity that already produced one wrong conclusion in this
codebase.

Before Stage 0 the signal was written at emit time and the drain
forwarded to the memfd's current SIZE, so a single wakeup published any
uncommitted bytes and a poisoned batch returned the abandoned attempt's
DATA with rc=0. That was reproduced at 0341c9b4.

Run: make -f Makefile.substrate python-substrate && cd python/tests
     python3 -m unittest test_stage0_publication
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



def _caller_version():
    """This interpreter's major.minor, for the launcher's
    --caller-version contract.

    The launcher CANNOT infer it after exec, so it is a DECLARATION, not
    an authenticated identity -- and it is therefore required on every
    direct launcher invocation that asks for UDF mode. Direct invocations
    bypass the Python wrapper that would normally supply it, so the test
    has to state it explicitly.
    """
    return "%d.%d" % (sys.version_info[0], sys.version_info[1])

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
class TestStage0Publication(unittest.TestCase):

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

    def run_launcher(self, mode, delay_ms=150, retry="1", handshake=False):
        env = dict(os.environ)
        for k in ("FORKRUN_TEST_DIE_BEFORE_ACK",
                  "FORKRUN_TEST_DIE_BEFORE_NOTIFY",
                  "FORKRUN_TEST_DIE_AFTER_DRAIN_MS",
                  "FORKRUN_TEST_DRAIN_ACK_FIFO"):
            env.pop(k, None)
        # NOT popped: the caller sets it deliberately to prove the
        # death-before-notification was actually injected. Popping it here
        # silently defeated exactly the check it was meant to support.
        if handshake:
            env["FORKRUN_TEST_DRAIN_ACK_FIFO"] = self._handshake_env(
                self._tmp.name)
            # The handshake replaces the sleep; keeping both would mask a
            # handshake that silently timed out.
            delay_ms = 0
        if mode == "before_ack":          # record written, not committed
            env["FORKRUN_TEST_DIE_BEFORE_ACK"] = "1"
            env["FORKRUN_TEST_DIE_AFTER_DRAIN_MS"] = str(delay_ms)
        elif mode == "before_notify":     # committed, not notified
            env["FORKRUN_TEST_DIE_BEFORE_NOTIFY"] = "1"
            env["FORKRUN_TEST_DIE_AFTER_DRAIN_MS"] = str(delay_ms)
        src_fd = os.open(self.src, os.O_RDONLY)
        out_fd = os.open(self.out, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            argv = [_launcher(),
                    "--so", _substrate(),
                    "--workers", "1", "--lines", "1", "--bytes", "0",
                    "--on-error", "0", "--retry", retry,
                    "--src", str(src_fd), "--result", str(out_fd),
                    "--stats-fd", "-1",
                    "--udf-helper", _helper(),
                    "--udf", "px_udf", "--udf-attr", "up", "--caller-version", _caller_version(),
                    "--udf-roots", _roots(self._tmp.name)]
            proc = subprocess.run(argv, env=env, pass_fds=(src_fd, out_fd),
                                  capture_output=True, timeout=180)
        finally:
            os.close(src_fd)
            os.close(out_fd)
        with open(self.out, "rb") as fh:
            return proc, fh.read()

    def _handshake_env(self, tmpdir):
        """FIFO the drain writes (worker, cursor) acks to."""
        path = os.path.join(tmpdir, "drain_ack.fifo")
        if not os.path.exists(path):
            os.mkfifo(path)
        return path

    def _fresh_marker(self, name):
        path = os.path.join(self._tmp.name, name)
        if os.path.exists(path):
            os.unlink(path)
        return path

    # -- control ------------------------------------------------------

    def test_control_unfaulted_run_delivers_data(self):
        _p, blob = self.run_launcher("clean")
        recs = parse(blob)
        self.assertEqual(BATCHES, len(recs), "control broken: %r" % (recs,))
        for _i, disp, _p in recs:
            self.assertEqual(DISP_DATA, disp)

    # -- SAFETY -------------------------------------------------------

    def test_uncommitted_record_is_never_published(self):
        """Death AFTER the record is written, BEFORE the commit.

        Every generation writes DATA then dies uncommitted, so recovery
        retries until the batch poisons. The batch's terminal outcome is
        POISONED, and that is the only thing a consumer may see: no
        DATA from any abandoned attempt may survive.
        """
        _p, blob = self.run_launcher("before_ack")
        recs = parse(blob)
        self.assertTrue(recs, "nothing reached the parent; harness is wrong")
        leaked = [(i, NAME.get(d, d), p) for i, d, p in recs if d == DISP_DATA]
        print("\n  before_ack stream: %r"
              % ([(i, NAME.get(d, d)) for i, d, _p in recs],))
        self.assertEqual(
            [], leaked,
            "SAFETY VIOLATION: %r -- DATA from an uncommitted attempt was "
            "published. The record was written before the commit and must "
            "not be reachable by the drain until TXN_IDLE." % (leaked,))

    def test_each_batch_reaches_exactly_one_terminal_record(self):
        _p, blob = self.run_launcher("before_ack")
        recs = parse(blob)
        by_batch = {}
        for idx, disp, _pl in recs:
            by_batch.setdefault(idx, []).append(disp)
        dupes = {i: d for i, d in by_batch.items() if len(d) > 1}
        self.assertEqual({}, dupes, "duplicate terminal records: %r" % (dupes,))
        self.assertEqual(sorted(range(BATCHES)), sorted(by_batch),
                         "batches missing a terminal record")

    def test_drain_was_awake_replaces_a_sleep(self):
        """The safety test above is only meaningful if the drain was
        demonstrably AWAKE while the uncommitted record sat in the memfd.

        Uses the handshake rather than a sleep: the drain publishes
        (worker, cursor) for every wakeup it processes, and the worker
        blocks until it sees its own before dying. If the drain never
        ran, the wait would time out and the worker would still die --
        so this test also asserts the stream is intact, which it would
        not be if the uncommitted record had leaked.
        """
        proc, blob = self.run_launcher("before_ack", handshake=True)
        recs = parse(blob)
        self.assertTrue(recs, "nothing reached the parent; harness is wrong")

        # rc 97 is the worker refusing to fall through a handshake that
        # never completed. If the drain had not been confirmed awake, the
        # stream below could look fine while proving nothing at all.
        self.assertNotEqual(
            97, proc.returncode,
            "handshake never completed (rc 97): the drain was never "
            "confirmed awake, so this run proves nothing about the "
            "uncommitted-publication window")

        leaked = [(i, NAME.get(d, d), p) for i, d, p in recs if d == DISP_DATA]
        self.assertEqual(
            [], leaked,
            "handshake run leaked uncommitted DATA: %r -- the drain was "
            "confirmed awake and still must not publish past the committed "
            "frontier" % (leaked,))
        by_batch = {i for i, _d, _p in recs}
        self.assertEqual(sorted(range(BATCHES)), sorted(by_batch),
                         "handshake run lost a batch's terminal record")

    # -- COMPLETENESS -------------------------------------------------

    def test_committed_record_survives_a_lost_notification(self):
        """Death AFTER the commit, BEFORE the drain is notified.

        These batches COMMITTED with DATA, so DATA is the correct outcome
        -- but the notification that would have delivered it was lost. If
        the supervisor does not synthesize a wakeup after recovery, the
        committed result is stranded and the stream is short.

        The handshake here is deliberately NON-PUBLISHING: the worker
        wakes the drain with frontier 0, which excludes the record just
        committed, waits for the drain to confirm it is alive and has
        nothing new to move, and only then dies. No notification carrying
        this record's bytes is ever sent before the death, so the
        supervisor's synthetic post-recovery wakeup is the ONLY path that
        can deliver it.

        An earlier version of this test published the record's real
        frontier and waited for the drain to forward it. That proved an
        ordinary notification works -- the opposite of the property under
        test -- and a lost-notification test that sends the notification
        cannot fail when the notification is lost.
        """
        marker = self._fresh_marker("before_notify.marker")
        old = os.environ.get("FORKRUN_TEST_DIE_BEFORE_NOTIFY_MARK")
        os.environ["FORKRUN_TEST_DIE_BEFORE_NOTIFY_MARK"] = marker
        try:
            proc, blob = self.run_launcher("before_notify", handshake=True)
        finally:
            if old is None:
                os.environ.pop("FORKRUN_TEST_DIE_BEFORE_NOTIFY_MARK", None)
            else:
                os.environ["FORKRUN_TEST_DIE_BEFORE_NOTIFY_MARK"] = old

        recs = parse(blob)
        print("\n  before_notify stream: %r"
              % ([(i, NAME.get(d, d)) for i, d, _p in recs],))

        # Positive evidence the injected death-before-notification
        # actually happened. Without it this test passes whenever the
        # ordinary notification works, which is the case it must exclude.
        self.assertTrue(os.path.exists(marker),
                        "the death-before-notification was never injected, "
                        "so this run cannot demonstrate lost-notification "
                        "recovery")

        self.assertNotEqual(
            97, proc.returncode,
            "handshake never completed (rc 97): the drain was never "
            "confirmed alive, so the test did not exercise the window")

        by_batch = {i for i, _d, _p in recs}
        missing = sorted(set(range(BATCHES)) - by_batch)
        self.assertEqual(
            [], missing,
            "COMPLETENESS VIOLATION: batches %r committed but were never "
            "delivered. No notification ever carried their bytes, so the "
            "supervisor's synthetic post-recovery wakeup must have."
            % (missing,))


if __name__ == "__main__":
    unittest.main()