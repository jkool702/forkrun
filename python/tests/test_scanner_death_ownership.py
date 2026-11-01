"""Descriptor ownership in `check_scanner_death`.

The helper's contract says a DEFINITIVE classification consumes and
closes the death pipe; a `running` result leaves it open because the
caller is still watching it. The `ChildProcessError` branch broke that
contract: it returned a definitive ("clean", 0) without closing the
descriptor, leaking one fd per helper whose status had been reaped
elsewhere.

It also invented a successful exit. `ChildProcessError` means the
status is no longer available through this wait. There is no
authoritative record of a lost helper status in this package, so the
only honest classification is an error (fail closed). These tests pin
both halves: closure on every definitive path, no closure while
running, and no synthesized success.
"""

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from forkrun import _reactor  # noqa: E402
from forkrun._reactor import check_scanner_death  # noqa: E402


def _fd_closed(fd):
    try:
        os.fstat(fd)
    except OSError:
        return True
    return False


class TestScannerDeathOwnership(unittest.TestCase):

    def _pipe(self):
        r, w = os.pipe()
        self.addCleanup(lambda: _safe_close(r))
        self.addCleanup(lambda: _safe_close(w))
        return r, w

    def test_non_readable_child_process_error_closes_and_fails_closed(self):
        death_r, _death_w = self._pipe()
        with mock.patch.object(_reactor._select, "select",
                               return_value=([], [], [])), \
                mock.patch.object(_reactor.os, "waitpid",
                                  side_effect=ChildProcessError):
            kind, code = check_scanner_death(424242, death_r)
        self.assertEqual((kind, code), ("error", 1),
                         "a lost wait status was reported as success")
        self.assertTrue(_fd_closed(death_r),
                        "the definitive ChildProcessError path leaked "
                        "the death-pipe descriptor")

    def test_non_readable_clean_closes(self):
        death_r, _death_w = self._pipe()
        with mock.patch.object(_reactor._select, "select",
                               return_value=([], [], [])), \
                mock.patch.object(_reactor.os, "waitpid",
                                  return_value=(424242, 0)):
            kind, code = check_scanner_death(424242, death_r)
        self.assertEqual((kind, code), ("clean", 0))
        self.assertTrue(_fd_closed(death_r))

    def test_non_readable_error_closes(self):
        death_r, _death_w = self._pipe()
        with mock.patch.object(_reactor._select, "select",
                               return_value=([], [], [])), \
                mock.patch.object(_reactor.os, "waitpid",
                                  return_value=(424242, 1 << 8)):
            kind, code = check_scanner_death(424242, death_r)
        self.assertEqual((kind, code), ("error", 1))
        self.assertTrue(_fd_closed(death_r))

    def test_running_does_not_close(self):
        death_r, death_w = self._pipe()
        with mock.patch.object(_reactor._select, "select",
                               return_value=([], [], [])), \
                mock.patch.object(_reactor.os, "waitpid",
                                  return_value=(0, 0)):
            kind, code = check_scanner_death(424242, death_r)
        self.assertEqual((kind, code), ("running", None))
        self.assertFalse(_fd_closed(death_r),
                         "a non-definitive result closed a descriptor the "
                         "caller is still watching")
        # The writer end must stay usable too (no accidental write-close).
        self.assertEqual(os.write(death_w, b"x"), 1)

    def test_readable_clean_closes(self):
        death_r, death_w = self._pipe()
        os.write(death_w, b"x")
        os.close(death_w)
        with mock.patch.object(_reactor.os, "waitpid",
                               return_value=(424242, 0)):
            kind, code = check_scanner_death(424242, death_r)
        self.assertEqual((kind, code), ("clean", 0))
        self.assertTrue(_fd_closed(death_r))

    def test_readable_child_process_error_closes_and_fails_closed(self):
        death_r, death_w = self._pipe()
        os.write(death_w, b"x")
        os.close(death_w)
        with mock.patch.object(_reactor.os, "waitpid",
                               side_effect=ChildProcessError):
            kind, code = check_scanner_death(424242, death_r)
        self.assertEqual((kind, code), ("error", 1))
        self.assertTrue(_fd_closed(death_r))

    def test_repeated_terminal_classifications_do_not_leak(self):
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(128):
            death_r, death_w = os.pipe()
            with mock.patch.object(_reactor._select, "select",
                                   return_value=([], [], [])), \
                    mock.patch.object(_reactor.os, "waitpid",
                                      return_value=(424242, 0)):
                kind, code = check_scanner_death(424242, death_r)
            self.assertEqual((kind, code), ("clean", 0))
            self.assertTrue(_fd_closed(death_r))
            _safe_close(death_w)
        after = len(os.listdir("/proc/self/fd"))
        self.assertEqual(
            after, before,
            "definitive classifications leaked descriptors: %d -> %d"
            % (before, after))


def _safe_close(fd):
    try:
        os.close(fd)
    except OSError:
        pass


if __name__ == "__main__":
    unittest.main()
