"""W-REL3/R16: order-pipe read errors abort loudly (never clean EOF).

ring_order_main treated robust_pipe_read() == -1 as clean EOF,
dropping every in-heap packet with exit 0 — including via the
Python ordered+reactor path (shared ring_order_main). Now -1
aborts with a message + FAILURE; 0 remains EOF.

Lock-in: fork an orderer child (spawn_orderer shape — no
in-process global pollution) with a directory fd as the order
pipe (read() -> EISDIR). Pre-fix: rc 0, silent. Post-fix:
rc != 0. (The engine-side string rides builtin_error —
bash-visible, stubbed to no-op in the substrate by design; the
Python parent surfaces the nonzero exit as "C orderer failed".
The abort-vs-EOF distinction, i.e. the rc, is what this locks.)
x10.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forkrun._bindings import find_substrate, get  # noqa: E402

from _helpers import assert_no_zombies  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestOrdererReadErrorAborts(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_order_pipe_error_is_not_eof(self):
        lib = get()
        pid = os.fork()
        if pid == 0:
            # NOTE: fr_py_orderer closes output_fd after dup2 (and
            # never closes fd_in) — the finally below tolerates
            # EBADF so rc is always the genuine engine return.
            rc = 42
            try:
                dir_fd = os.open("/tmp", os.O_RDONLY)
                devnull = os.open("/dev/null", os.O_WRONLY)
                try:
                    rc = lib.fr_py_orderer(dir_fd, devnull, 1, 0)
                finally:
                    for _fd in (dir_fd, devnull):
                        try:
                            os.close(_fd)
                        except OSError:
                            pass
            except BaseException:
                rc = 42
            os._exit(rc if isinstance(rc, int) and 0 <= rc < 256
                     else 42)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFEXITED(status),
                        "orderer child did not exit cleanly: %r" % (status,))
        self.assertNotEqual(
            os.WEXITSTATUS(status), 0,
            "order-pipe read error returned success (silent loss)")


if __name__ == "__main__":
    unittest.main()
