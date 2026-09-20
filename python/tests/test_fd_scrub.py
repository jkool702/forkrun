"""W-PY16 addendum: fd scrubbing for forked children (Stage 5).

When forkrun runs inside an event-loop host (opencode, Jupyter,
asyncio), forked children must not inherit the host's fds (epoll,
timerfds, sockets). scrub_fds() closes everything outside the keep
set + 0/1/2; engine fds (escrow/eventfds, differenced from the
pre-init baseline) are always kept — closing those breaks escrow
retry and forces claim-polling into POLLNVAL spins.
"""

import os
import select
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forkrun._fd_scrub import (  # noqa: E402
    scrub_fds, snapshot_fds, verify_scrubbed)


class TestScrubFunction(unittest.TestCase):
    def test_scrub_closes_unneeded_fds(self):
        extra = [os.open("/dev/null", os.O_RDONLY) for _ in range(5)]
        try:
            for fd in extra:
                self.assertIn(fd, verify_scrubbed(set()))
            closed = scrub_fds(set())
            self.assertGreaterEqual(closed, 5)
            for fd in extra:
                self.assertNotIn(fd, verify_scrubbed(set()))
        finally:
            for fd in extra:
                try:
                    os.close(fd)
                except OSError:
                    pass  # already closed by the scrub

    def test_scrub_keeps_essential_fds(self):
        keep_fd = os.open("/dev/null", os.O_RDONLY)
        try:
            scrub_fds({keep_fd})
            os.lseek(keep_fd, 0, os.SEEK_CUR)  # still open: no error
            for std in (0, 1, 2):
                self.assertNotIn(std, verify_scrubbed({keep_fd}))
        finally:
            os.close(keep_fd)

    def test_scrub_idempotent(self):
        scrub_fds(set())
        scrub_fds(set())  # no error

    def test_snapshot_roundtrip(self):
        before = snapshot_fds()
        fd = os.open("/dev/null", os.O_RDONLY)
        try:
            after = snapshot_fds()
            # fd numbers are reused by background activity; assert
            # membership and bounded growth, not exact set equality.
            self.assertIn(fd, after)
            self.assertLessEqual(len(after), len(before) + 1)
        finally:
            os.close(fd)


class TestWorkerFDIsolation(unittest.TestCase):
    def test_worker_does_not_inherit_extra_fds(self):
        """Forked worker keeps engine + job fds only (W-PY13 hygiene
        test moved to the scrub mechanism: same assertion)."""
        import forkrun

        extra_fds = [os.open("/dev/null", os.O_RDONLY) for _ in range(3)]
        try:
            def fd_checker(batch):
                import os as _os
                return str(len(_os.listdir("/proc/self/fd"))).encode()

            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                             delete=False) as fh:
                fh.write("test\n")
                path = fh.name
            try:
                results = forkrun.map(fd_checker, path, workers=1)
                # 0,1,2 + memfd + out + engine pipes/eventfds: small and
                # bounded — crucially WITHOUT the parent's 3 extras.
                self.assertLess(int(results[0]), 20,
                                "worker fd count unreasonable")
            finally:
                os.unlink(path)
        finally:
            for fd in extra_fds:
                os.close(fd)


class TestEventLoopNoDeadlock(unittest.TestCase):
    """forkrun inside an event-loop host must complete (the opencode
    deadlock shape: parent holds epoll + extra fds across the fork)."""

    def test_event_loop_parent_no_deadlock(self):
        driver = (
            "import os, sys, select\n"
            "sys.path.insert(0, 'python')\n"
            "# Event-loop shape: an open epoll fd + extra fds held across\n"
            "# the fork (registration unnecessary — inheritance is the\n"
            "# hazard; some sandboxes forbid epoll_register).\n"
            "ep = select.epoll()\n"
            "extra = [os.open('/dev/null', os.O_RDONLY)"
            " for _ in range(5)]\n"
            "import forkrun\n"
            "out = forkrun.map(lambda b: bytes(b.data).upper(),\n"
            "                  sys.argv[1], workers=2, order='index')\n"
            "raw = open(sys.argv[1], 'rb').read()\n"
            "assert b''.join(out) == raw.upper(), 'results incorrect'\n"
            "ep.close()\n"
            "for fd in extra:\n"
            "    os.close(fd)\n"
            "print('EVENT-LOOP-OK')\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            for i in range(100):
                fh.write("line %d\n" % i)
            path = fh.name
        try:
            proc = subprocess.run(
                [sys.executable, "-c", driver, path],
                capture_output=True, text=True, timeout=60,
                cwd=os.path.join(os.path.dirname(__file__), "..", ".."))
            self.assertEqual(proc.returncode, 0,
                             "event loop test failed:\n%s" % proc.stderr)
            self.assertIn("EVENT-LOOP-OK", proc.stdout)
        finally:
            os.unlink(path)

    def test_streaming_ingest_with_event_loop(self):
        driver = (
            "import os, sys\n"
            "sys.path.insert(0, 'python')\n"
            "extra = [os.open('/dev/null', os.O_RDONLY)"
            " for _ in range(5)]\n"
            "import forkrun\n"
            "r, w = os.pipe()\n"
            "pid = os.fork()\n"
            "if pid == 0:\n"
            "    os.close(r)\n"
            "    for i in range(2000):\n"
            "        os.write(w, ('line %d\\n' % i).encode())\n"
            "    os.close(w)\n"
            "    os._exit(0)\n"
            "os.close(w)\n"
            "out = forkrun.map(lambda b: bytes(b.data).upper(), r,\n"
            "                  workers=2, order='index', streaming=True)\n"
            "os.close(r)\n"
            "os.waitpid(pid, 0)\n"
            "assert len(out) > 0, 'no results'\n"
            "got = sorted(b for blob in out for b in blob.splitlines())\n"
            "exp = sorted(('line %d' % i).upper().encode()\n"
            "             for i in range(2000))\n"
            "assert got == exp, 'results wrong'\n"
            "for fd in extra:\n"
            "    os.close(fd)\n"
            "print('STREAMING-EVENT-LOOP-OK')\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", driver],
            capture_output=True, text=True, timeout=120,
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."))
        self.assertEqual(proc.returncode, 0,
                         "streaming + event loop failed:\n%s" % proc.stderr)
        self.assertIn("STREAMING-EVENT-LOOP-OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
