"""A post-commit notification failure must not re-execute the batch.

The one link in the Stage 0 protocol that was asserted rather than
tested: fr_py_complete returns FR_PY_ERR_NOTIFY (-4) when the commit
succeeded but the drain was never notified, and every worker loop treats
a nonzero return as "worker died". Recovery then has to classify that
death as IDLE -- committed, nothing in flight -- and decline to retry.

If it retried, the batch would execute a second time. That is a
duplicate-execution bug introduced by the fix for the publication race,
so it deserves a test rather than an argument.

FORKRUN_TEST_NOTIFY_FAIL_ONCE makes exactly one notification per process
fail after the commit.

The UDF appends every invocation to a log, so a re-execution shows up as
a repeated input line rather than something inferred.

Run: make -f Makefile.substrate python-substrate && cd python/tests
     python3 -m unittest test_stage0_notify_failure
"""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))
sys.path.insert(0, _HERE)

import forkrun  # noqa: E402
from forkrun._udf import helper_path  # noqa: E402

# Logs each invocation so duplicates are observable.
UDF_SRC = '''
import os

_LOG = os.path.join(os.path.dirname(__file__), "invocations.txt")

def up(b):
    with open(_LOG, "a") as fh:
        fh.write(b.decode().strip() + "\\n")
    return b.upper()
'''

BATCHES = 5


def _available():
    try:
        return bool(helper_path()) and os.path.exists(
            os.path.join(_ROOT, "python", "forkrun", "_forkrun_cleanroom"))
    except Exception:
        return False


@unittest.skipUnless(_available(), "udf helper / launcher not built")
class TestPostCommitNotifyFailure(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = self._tmp.name
        with open(os.path.join(self.d, "px_udf.py"), "w") as fh:
            fh.write(UDF_SRC)
        self.log = os.path.join(self.d, "invocations.txt")
        self.src = os.path.join(self.d, "in.txt")
        with open(self.src, "w") as fh:
            fh.writelines("line%06d\n" % i for i in range(BATCHES))
        sys.path.insert(0, self.d)
        self.addCleanup(sys.path.remove, self.d)

    def tearDown(self):
        self._tmp.cleanup()

    def _set(self, **kv):
        old = {}
        for k, v in kv.items():
            old[k] = os.environ.get(k)
            os.environ[k] = v
        return old

    def _restore(self, old):
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _invocations(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as fh:
            return [ln.strip() for ln in fh if ln.strip()]

    def _run(self, fail_notify, real_write_failure=False):
        old = self._set(FORKRUN_CLEANROOM="1")
        self.mark = os.path.join(self.d, "notify_fail.marker")
        if os.path.exists(self.mark):
            os.unlink(self.mark)
        # The two faults are alternatives, not stacked: FAIL_ONCE returns
        # before attempting the write, so leaving it set alongside
        # CLOSE_SIGNAL_FD would mean the real write path is never reached.
        if fail_notify and not real_write_failure:
            os.environ["FORKRUN_TEST_NOTIFY_FAIL_ONCE"] = "1"
            os.environ["FORKRUN_TEST_NOTIFY_FAIL_MARK"] = self.mark
        else:
            os.environ.pop("FORKRUN_TEST_NOTIFY_FAIL_ONCE", None)
        if fail_notify:
            os.environ["FORKRUN_TEST_NOTIFY_FAIL_MARK"] = self.mark
        else:
            os.environ.pop("FORKRUN_TEST_NOTIFY_FAIL_ONCE", None)
            os.environ.pop("FORKRUN_TEST_NOTIFY_FAIL_MARK", None)
        if real_write_failure:
            # Close only the worker's duplicate of signal_fd, so the REAL
            # write() fails with EBADF while the drain and the launcher's
            # spare writer stay alive and the supervisor can still send
            # its synthetic recovery wakeup.
            os.environ["FORKRUN_TEST_CLOSE_SIGNAL_FD"] = "1"
        else:
            os.environ.pop("FORKRUN_TEST_CLOSE_SIGNAL_FD", None)
        try:
            return list(forkrun.stream(
                "px_udf:up", self.src, streaming=True, mode="udf",
                workers=1, nodes=1, output="bytes", lines=1))
        finally:
            self._restore(old)
            for k in ("FORKRUN_TEST_NOTIFY_FAIL_ONCE",
                      "FORKRUN_TEST_NOTIFY_FAIL_MARK",
                      "FORKRUN_TEST_CLOSE_SIGNAL_FD"):
                os.environ.pop(k, None)

    # -- control -------------------------------------------------------

    def test_control_no_fault_executes_each_batch_once(self):
        got = self._run(fail_notify=False)
        inv = self._invocations()
        self.assertEqual(sorted("line%06d" % i for i in range(BATCHES)),
                         sorted(inv),
                         "control is not one-execution-per-batch: %r" % (inv,))
        self.assertTrue(got, "control produced no records")

    # -- the test ------------------------------------------------------

    def test_committed_batch_is_not_re_executed_after_notify_failure(self):
        """The batch commits, the notification fails, the worker exits,
        and recovery must NOT run that batch again."""
        got = self._run(fail_notify=True)
        inv = self._invocations()

        self.assertTrue(inv, "the UDF never ran; the fault was not injected")

        # Positive evidence the fault actually fired. Without this the
        # duplicate-execution assertion below would also hold in a run
        # where nothing was ever injected.
        self.assertTrue(os.path.exists(self.mark),
                        "the post-commit notification failure was never "
                        "injected, so this test proved nothing")

        # No input may appear twice: a retry would duplicate its line.
        dupes = sorted({ln for ln in inv if inv.count(ln) > 1})
        self.assertEqual(
            [], dupes,
            "DUPLICATE EXECUTION: %r appeared more than once in the "
            "invocation log. A post-commit notification failure (-4) was "
            "treated as a pre-commit failure, so the committed batch ran "
            "again -- the exact duplicate-execution bug the distinct error "
            "code exists to prevent. Full log: %r" % (dupes, inv))

        # And every batch must still have been delivered.
        joined = b"".join(g for g in got if g).decode()
        self.assertEqual("".join("LINE%06d\n" % i for i in range(BATCHES)),
                         joined,
                         "not every batch was delivered to the caller "
                         "(got %d bytes)" % len(joined))


    def test_real_signal_write_failure_is_recovered_not_retried(self):
        """The REAL write() path, not a synthetic return.

        FORKRUN_TEST_CLOSE_SIGNAL_FD closes only this worker's duplicate of
        signal_fd, so fr_py_notify_committed() performs a genuine write
        that fails with EBADF. The drain and the launcher's spare writer
        remain open, so the supervisor's synthetic post-recovery wakeup can
        still deliver the committed record.

        Requires the same outcome as the synthetic case: the committed
        batch is delivered exactly once and never re-executed.
        """
        got = self._run(fail_notify=True, real_write_failure=True)
        inv = self._invocations()
        self.assertTrue(inv, "the UDF never ran; nothing was exercised")

        # Positive evidence the REAL failure path was taken: the notifier
        # writes 'C' (as opposed to 'F' for the synthetic early return).
        with open(self.mark) as fh:
            marks = fh.read()
        self.assertIn("C", marks,
                      "the real signal-write failure was never exercised; "
                      "marker held only %r" % marks)

        dupes = sorted({ln for ln in inv if inv.count(ln) > 1})
        self.assertEqual(
            [], dupes,
            "DUPLICATE EXECUTION after a real notification write failure: "
            "%r appeared more than once. The commit had already happened, "
            "so the batch must not run again." % (dupes,))

        joined = b"".join(g for g in got if g).decode()
        self.assertEqual("".join("LINE%06d\n" % i for i in range(BATCHES)),
                         joined,
                         "the committed batch was not delivered exactly "
                         "once (got %d bytes)" % len(joined))


    def test_undeliverable_synthetic_wakeup_fails_the_run_closed(self):
        """A committed record whose synthetic wakeup cannot be sent must
        NOT produce a successful-looking run.

        spare_sig is normally held open for the whole supervision loop,
        which is what makes the real fail-closed path safe. This closes
        it so the wakeup genuinely cannot be delivered.

        SCOPE, stated precisely: the hook sets spare_sig to -1, so this
        exercises the helper's INVALID-DESCRIPTOR rejection, not a real
        failed write()/EPIPE. That still validates the decision that
        matters -- an undeliverable wakeup aborts rather than reporting
        success with committed output missing -- but it is not syscall-
        failure coverage. The genuine write-failure path is covered
        separately by test_real_signal_write_failure_is_recovered_not_
        retried, which closes the worker's own signal fd.
        """
        import subprocess
        import tempfile
        launcher = os.path.join(_ROOT, "python", "forkrun",
                                "_forkrun_cleanroom")
        if not os.path.exists(launcher):
            self.skipTest("launcher not built")
        from forkrun._bindings import find_substrate
        plugin = os.path.join(_HERE, "plugins", "test_plugin_v1.so")
        if not os.path.exists(plugin):
            self.skipTest("plugin fixture not built")

        out = os.path.join(self.d, "wakeup.bin")
        sfd = os.open(self.src, os.O_RDONLY)
        ofd = os.open(out, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        env = dict(os.environ)
        # BEFORE_NOTIFY, not BEFORE_ACK. The scenario under test is a
        # COMMITTED record whose ordinary notification was lost.
        # BEFORE_ACK killed the worker with uncommitted output, which
        # recovery rolled back -- so the abandoned record was gone and
        # the test exercised the error branch without ever establishing
        # the committed-but-unnotified case its name claims.
        env["FORKRUN_TEST_DIE_BEFORE_NOTIFY"] = "1"
        env["FORKRUN_TEST_DIE_AFTER_DRAIN_MS"] = "150"
        env["FORKRUN_TEST_BREAK_DRAIN_WAKEUP"] = "1"
        try:
            proc = subprocess.run(
                [launcher, "--so", find_substrate(),
                 "--workers", "1", "--lines", "1", "--bytes", "0",
                 "--on-error", "0", "--retry", "2",
                 "--src", str(sfd), "--result", str(ofd),
                 "--stats-fd", "-1", "--plugin", plugin,
                 "--func", "count_lines_v1"],
                env=env, pass_fds=(sfd, ofd), capture_output=True, timeout=120)
        finally:
            os.close(sfd)
            os.close(ofd)

        err = proc.stderr.decode(errors="replace")
        self.assertNotEqual(
            0, proc.returncode,
            "the run reported SUCCESS despite being unable to deliver "
            "committed output: that is exactly the silent-loss failure "
            "fail-closed exists to prevent")
        self.assertIn("post-recovery drain wakeup failed", err,
                      "expected the fail-closed abort; stderr was: %r"
                      % err[-400:])
        # And the run must not have delivered a short stream as if whole.
        with open(out, "rb") as fh:
            blob = fh.read()
        self.assertLess(len(blob), 24 * BATCHES,
                        "stream unexpectedly complete for an aborted run")


if __name__ == "__main__":
    unittest.main()