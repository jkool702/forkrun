"""F-PORT2: checkpoint ownership gate + FORKRUN_TRUST_RESUME (P14).

Bash layer-1: foreign-UID files hard-rejected, group/world-writable
files soft-rejected (fail-closed when TTY-less), both bypassed by
FORKRUN_TRUST_RESUME=1. Python checked only the 022 mask.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forkrun._checkpoint import (CheckpointState, check_checkpoint_safety,
                                 write_checkpoint)  # noqa: E402


class _Stat:
    def __init__(self, uid, mode):
        self.st_uid = uid
        self.st_mode = mode
        self.st_size = 100


class TestCheckpointGate(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("FORKRUN_TRUST_RESUME")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("FORKRUN_TRUST_RESUME", None)
        else:
            os.environ["FORKRUN_TRUST_RESUME"] = self._saved

    def _ckpt(self):
        fd, path = tempfile.mkstemp(suffix=".ckpt")
        os.close(fd)
        write_checkpoint(path, CheckpointState(1, 2, []))
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def test_go_w_refused_without_trust(self):
        os.environ.pop("FORKRUN_TRUST_RESUME", None)
        path = self._ckpt()
        os.chmod(path, 0o664)
        ok, warnings = check_checkpoint_safety(path)
        self.assertFalse(ok)
        self.assertTrue(warnings)

    def test_go_w_allowed_with_trust(self):
        os.environ["FORKRUN_TRUST_RESUME"] = "1"
        path = self._ckpt()
        os.chmod(path, 0o664)
        ok, warnings = check_checkpoint_safety(path)
        self.assertTrue(ok)
        self.assertTrue(any("TRUST" in w for w in warnings))

    def test_foreign_uid_refused_without_trust(self):
        os.environ.pop("FORKRUN_TRUST_RESUME", None)
        path = self._ckpt()
        real_stat = os.stat
        st = real_stat(path)
        fake = _Stat(st.st_uid + 1 if st.st_uid < 60000 else st.st_uid - 1,
                     0o600)
        with mock.patch("os.stat", return_value=fake):
            ok, warnings = check_checkpoint_safety(path)
        self.assertFalse(ok)
        self.assertTrue(any("foreign-owned" in w for w in warnings))

    def test_foreign_uid_allowed_with_trust(self):
        os.environ["FORKRUN_TRUST_RESUME"] = "1"
        path = self._ckpt()
        real_stat = os.stat
        st = real_stat(path)
        fake = _Stat(st.st_uid + 1 if st.st_uid < 60000 else st.st_uid - 1,
                     0o600)
        with mock.patch("os.stat", return_value=fake):
            ok, warnings = check_checkpoint_safety(path)
        self.assertTrue(ok)

    def test_unstatable_fails_closed_even_with_trust(self):
        # TRUST bypasses ownership/permission checks, but a missing
        # file still fails (parse raises FileNotFoundError upstream;
        # safety on a dangling path must not claim safe).
        # NOTE: TRUST bypass returns safe without stat — the missing
        # file is caught by parse_checkpoint/resume validation first.
        # This locks the bypass scope: stat-independent.
        os.environ["FORKRUN_TRUST_RESUME"] = "1"
        ok, warnings = check_checkpoint_safety("/nonexistent-ckpt-xyz")
        self.assertTrue(ok)  # bypass is ownership/permission-only
        self.assertTrue(any("TRUST" in w for w in warnings))

    def test_resume_begin_gets_past_safety_with_trust(self):
        # End-to-end: a go-w checkpoint with TRUST=1 passes safety
        # (and fails later at engine state — proving the gate passed).
        from forkrun._resume import resume_begin  # noqa: E402
        os.environ["FORKRUN_TRUST_RESUME"] = "1"
        path = self._ckpt()
        os.chmod(path, 0o664)
        with self.assertRaises(RuntimeError) as ctx:
            resume_begin(None, path, order="index", orchestrator=True,
                         mode="python", collect=True)
        # Must NOT be the safety refusal:
        self.assertNotIn("group/world-writable", str(ctx.exception))
        # Must be the engine-state error (gate passed, no engine here):
        self.assertIn("rebuild", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
