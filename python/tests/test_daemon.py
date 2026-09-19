"""W-PY4.e Payload-forks-daemon (Stage 4 Phase 3).

v0 fd reality (characterization, not enforcement): worker children inherit
EVERYTHING (ingress/output memfds, escrow pipes, eventfds) — v0 does no
CLOEXEC/scrubbing. A payload daemon therefore inherits the full set too.
What v0 guarantees: the daemon neither blocks waitpid (it is reparented
away from the pipeline) nor breaks the run. Minimal-fd hygiene
(close-on-exec + death-pipe/trap-ack/fallow scrub, cf. the C feeder
scrub) is v1 work; the inherited count is RECORDED here so v1 has a
baseline to shrink.

Daemon shape: double-fork + setsid, self-terminating heartbeat (3 beats,
then exit) — no orphans left on CI machines.
"""

import os
import signal
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestPayloadForksDaemon(unittest.TestCase):
    def test_daemon_survives_and_run_returns(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        beat_path = path + ".beat"
        pid_path = path + ".pid"
        try:
            write_lines(path, 800)
            with open(path, "rb") as fh:
                raw = fh.read()

            def forking(batch):
                data = bytes(batch.data)
                if batch.batch_index == 0 and not os.path.exists(pid_path):
                    pid = os.fork()
                    if pid == 0:
                        # Child: detach fully, then daemonize.
                        try:
                            if os.fork() > 0:
                                os._exit(0)
                            os.setsid()
                            with open(pid_path, "w") as fh:
                                fh.write("%d" % os.getpid())
                            # v1 baseline: how many fds did we inherit?
                            try:
                                nfds = len(os.listdir("/proc/self/fd"))
                            except OSError:
                                nfds = -1
                            with open(pid_path, "a") as fh:
                                fh.write(" fds=%d" % nfds)
                            for _ in range(3):
                                with open(beat_path, "a") as fh:
                                    fh.write("beat\n")
                                time.sleep(0.2)
                        finally:
                            os._exit(0)
                    os.waitpid(pid, 0)  # reap the middle process only
                return data

            out = forkrun.map(forking, path, workers=1, order="index")
            # The run is unaffected by the daemon fork.
            self.assertEqual(b"".join(out), raw)
            # The daemon lived past the batch and past the run (3 beats).
            deadline = time.time() + 10
            beats = []
            while time.time() < deadline:
                if os.path.exists(beat_path):
                    with open(beat_path) as fh:
                        beats = fh.read().splitlines()
                    if len(beats) >= 3:
                        break
                time.sleep(0.1)
            self.assertEqual(len(beats), 3)
            with open(pid_path) as fh:
                pid_txt, fds_txt = fh.read().split()
            # Characterization: the daemon inherited the full worker fd
            # set (v0 does no scrubbing). Recorded for v1 to shrink.
            nfds = int(fds_txt.split("=")[1])
            self.assertGreater(nfds, 3,
                               "daemon should inherit worker fds in v0")
            # Daemon reaped itself (triple-beat then _exit): no kill needed,
            # no orphans. Confirm the pid is gone.
            daemon_pid = int(pid_txt)
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    os.kill(daemon_pid, 0)
                except ProcessLookupError:
                    break
                except PermissionError:
                    break
                time.sleep(0.1)
            else:
                try:
                    os.kill(daemon_pid, signal.SIGKILL)
                except OSError:
                    pass
                self.fail("daemon did not self-terminate")
            assert_no_zombies(self)
        finally:
            os.unlink(path)
            for extra in (beat_path, pid_path):
                if os.path.exists(extra):
                    os.unlink(extra)


if __name__ == "__main__":
    unittest.main()
