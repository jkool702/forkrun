"""W-PY30 final-attempt coredump policy.

Coredumps are OFF by default on all workers (soft RLIMIT_CORE 0 at
worker startup, generous hard preserved). They are enabled for
exactly one batch execution: the final allowed escrow attempt (the
attempt whose failure poisons the batch). Success, poison-skip, and
soft-fail-continuation paths disarm, so the enabled limit never leaks
into later batches.

Unit tests drive the claim/ack/deposit entry points in-process and
observe RLIMIT_CORE directly. The integration test runs the full
fail-twice-then-succeed lifecycle through a real worker and logs the
soft limit per payload invocation (no actual dump is produced).
"""

import ctypes
import os
import resource
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import (FrPyBatch, RC_OK, find_substrate,  # noqa: E402
                               get)

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _soft():
    return resource.getrlimit(resource.RLIMIT_CORE)[0]


def _hard():
    return resource.getrlimit(resource.RLIMIT_CORE)[1]


def _filter():
    with open("/proc/self/coredump_filter") as fh:
        return int(fh.read().strip(), 16)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestCoredumpDefaults(unittest.TestCase):
    """Worker startup: soft 0, hard preserved, small-dump filter."""

    def setUp(self):
        self._saved_rlimit = resource.getrlimit(resource.RLIMIT_CORE)
        try:
            with open("/proc/self/coredump_filter") as fh:
                self._saved_filter = fh.read().strip()
        except OSError:
            self._saved_filter = None
        self.addCleanup(self._restore)

    def _restore(self):
        try:
            resource.setrlimit(resource.RLIMIT_CORE, self._saved_rlimit)
        except (OSError, ValueError):
            pass
        if self._saved_filter is not None:
            try:
                with open("/proc/self/coredump_filter", "w") as fh:
                    fh.write(self._saved_filter)
            except OSError:
                pass

    @staticmethod
    def _close(fd):
        try:
            os.close(fd)
        except OSError:
            pass

    def _init_with_lines(self, lines, retry_limit=3):
        lib = get()
        self.assertEqual(lib.fr_py_init(0, 0), 0)
        memfd = os.memfd_create("fr_core_in")
        self.addCleanup(lambda: self._close(memfd))
        data = "".join("line %d\n" % i for i in range(lines)).encode()
        os.write(memfd, data)
        os.lseek(memfd, 0, os.SEEK_SET)
        self.assertEqual(lib.fr_py_ingest_done(), 0)
        self.assertEqual(lib.fr_py_scan(memfd), 0)
        self.addCleanup(lib.fr_py_destroy)
        return lib

    def test_startup_disables_soft_preserves_hard(self):
        lib = self._init_with_lines(10)
        hard_before = _hard()
        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        self.assertEqual(_soft(), 0)
        self.assertEqual(_hard(), hard_before)

    def test_startup_sets_small_dump_filter(self):
        lib = self._init_with_lines(10)
        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        # anon-private + ELF headers + hugetlb-private (no file-backed
        # / anon-shared arenas — the multi-GB ingress memfds).
        self.assertEqual(_filter(), 0x31)

    def test_fresh_claim_never_arms(self):
        lib = self._init_with_lines(10)
        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        claimed = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(claimed)), RC_OK)
        self.assertEqual(claimed.num_kills, 0)
        self.assertEqual(_soft(), 0)
        self.assertEqual(lib.fr_py_ack_direct(-1, -1), 0)
        self.assertEqual(_soft(), 0)

    def test_final_attempt_arms_and_ack_disarms(self):
        """kills=2 of limit=3: claim arms (soft raised), ack disarms."""
        lib = self._init_with_lines(30)
        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        c0 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c0)), RC_OK)
        # Jump the batch to kills=2 via worker-side deposit.
        self.assertEqual(lib.fr_py_escrow_deposit(2), 0)
        self.assertEqual(_soft(), 0)  # deposit itself never arms
        c1 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c1)), RC_OK)
        self.assertEqual(c1.num_kills, 2)
        self.assertEqual(c1.poisoned, 0)
        self.assertNotEqual(_soft(), 0)  # armed: final attempt
        self.assertEqual(lib.fr_py_ack_direct(-1, -1), 0)
        self.assertEqual(_soft(), 0)  # success disarms before rejoin

    def test_poison_read_never_arms(self):
        """kills=3 of limit=3: poison-skipped, coredump untouched."""
        lib = self._init_with_lines(30)
        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        c0 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c0)), RC_OK)
        self.assertEqual(lib.fr_py_escrow_deposit(3), 0)
        c1 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c1)), RC_OK)
        self.assertEqual(c1.poisoned, 1)
        self.assertEqual(_soft(), 0)

    def test_deposit_disarms_soft_fail_continuation(self):
        """Armed final attempt that soft-fails (deposit, no death):
        disarmed at deposit so the same worker's next batches are clean."""
        lib = self._init_with_lines(30)
        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        c0 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c0)), RC_OK)
        self.assertEqual(lib.fr_py_escrow_deposit(2), 0)
        c1 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c1)), RC_OK)
        self.assertEqual(c1.num_kills, 2)
        self.assertNotEqual(_soft(), 0)  # armed
        # Payload raises (no death) → worker-side escrow, same process.
        self.assertEqual(lib.fr_py_escrow_deposit(3), 0)
        self.assertEqual(_soft(), 0)  # disarmed at deposit
        # Next read poisons (no run, still disarmed).
        c2 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c2)), RC_OK)
        self.assertEqual(c2.poisoned, 1)
        self.assertEqual(_soft(), 0)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestCoredumpLifecycleIntegration(unittest.TestCase):
    """Fail-twice-then-succeed through a real worker: only the final
    attempt (3rd invocation) observes an enabled soft limit; every
    later batch observes 0 (disarm-after-success). No dump is fired."""

    def tearDown(self):
        assert_no_zombies(self)

    def test_final_attempt_only_sees_enabled(self):
        tmpdir = tempfile.mkdtemp(prefix="w30core_")
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        write_lines(path, 60, fmt="line %d\n")
        log_path = os.path.join(tmpdir, "soft.log")
        mod_path = os.path.join(tmpdir, "w30core_mod.py")
        try:
            with open(mod_path, "w") as fh:
                fh.write(
                    "import os, resource\n"
                    "LOG = %r\n"
                    "CNT = %r\n"
                    "def payload(batch):\n"
                    "    soft = resource.getrlimit(resource.RLIMIT_CORE)[0]\n"
                    "    try:\n"
                    "        with open(CNT) as f:\n"
                    "            n = int(f.read() or 0)\n"
                    "    except OSError:\n"
                    "        n = 0\n"
                    "    with open(CNT, 'w') as f:\n"
                    "        f.write(str(n + 1))\n"
                    "    with open(LOG, 'a') as f:\n"
                    "        f.write('%%d:%%d\\n' %% (n + 1, soft))\n"
                    "    if n < 2:\n"
                    "        raise RuntimeError('fail %%d' %% (n + 1))\n"
                    "    return bytes(batch.data).upper()\n"
                    % (log_path, os.path.join(tmpdir, "cnt")))
            sys.path.insert(0, tmpdir)
            try:
                res = forkrun.map("w30core_mod:payload", path,
                                  workers=1, lines=10, order="index",
                                  nodes=1)
            finally:
                sys.path.remove(tmpdir)
            # Full output (the final attempt succeeded, no poison):
            # map() is batch-granular — expect 6 ordered batch blobs.
            with open(path, "rb") as fh:
                lines = [l for l in fh.read().split(b"\n") if l.strip()]
            want = [b"\n".join(g) + b"\n"
                    for g in (lines[i:i + 10] for i in range(0, 60, 10))]
            want = [w.upper() for w in want]
            self.assertEqual(res, want)
            with open(log_path) as fh:
                seen = [tuple(map(int, l.split(":")))
                        for l in fh.read().split()]
            by_inv = dict(seen)
            # Invocations 1-2 (kills 0,1): disabled. Invocation 3
            # (kills 2 == limit-1: final): enabled. Everything after
            # (fresh batches post-disarm): disabled.
            self.assertEqual(by_inv[1], 0)
            self.assertEqual(by_inv[2], 0)
            self.assertNotEqual(by_inv[3], 0)
            for inv in sorted(by_inv):
                if inv > 3:
                    self.assertEqual(by_inv[inv], 0,
                                     "soft leaked into batch %d" % inv)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
