"""W-PY34.a streaming Tier-3 recovery: WorkerTxn during active stream().

Verifies the universal parent-side recovery (W-PY28/29) works while the
parent is actively draining results:

  stream() yielding -> worker crashes -> reactor detects (death pipe)
  -> fr_py_recover_worker() -> escrow + respawn -> new generation
  re-processes the batch -> drain loop yields it -> stream continues.

Kill-injection: file-gated payload modules (same pattern as
test_recovery_adversarial.py). Each crashing batch fires exactly once;
the respawned generation's retry succeeds. No threads; every forked
child is reaped by the reactor (assert_no_zombies in tearDown).

All tests use orchestrator=True (the reactor path — the only path
with death detection + recovery). Without the reactor there is no
recovery by design.

All tests pin nodes=1 (UMA). Rationale: nodes="auto" follows the
boot topology — under numa=fake=N it fans out to the NUMA pipeline,
where workers must cover every node (an unworked node's ring is
never claimed — silent loss, see W-PY34 Part 4 notes). Streaming
Tier-3 verifies WorkerTxn recovery during the active drain; the UMA
envelope isolates that variable. NUMA recovery is covered by
test_numa_recovery.py (nodes="@2").
"""

import os
import sys
import tempfile
import time
import unittest
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import (assert_no_zombies, joined_bytes,  # noqa: E402
                      lines_of, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _up(batch):
    return bytes(batch.data).upper()


def _make_input(n=2000, prefix="line"):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    write_lines(path, n, fmt=prefix + " %d\n")
    return path


def _write_kill_module(plugin_dir, name, condition, sig="SIGKILL",
                       per_batch=False):
    """Payload module that kills itself when `condition` (a Python
    expression over batch) holds, once per marker. sig is "SIGKILL"
    or "SIGSEGV" (real segfault via ctypes.string_at(0))."""
    mod_path = os.path.join(plugin_dir, name + ".py")
    marker = os.path.join(plugin_dir, name + ".dead")
    if sig == "SIGSEGV":
        kill = "ctypes.string_at(0)"
        imports = "import ctypes, os\n"
    else:
        kill = "os.kill(os.getpid(), signal.SIGKILL)"
        imports = "import os, signal\n"
    if per_batch:
        gate = ("MARK = MARKER + '.' + str(batch.batch_index)\n"
                "    if (%s) and not os.path.exists(MARK):\n"
                "        with open(MARK, 'w') as _m:\n"
                "            _m.write('x')\n") % condition
    else:
        gate = ("if (%s) and not os.path.exists(MARKER):\n"
                "        with open(MARKER, 'w') as _m:\n"
                "            _m.write('x')\n") % condition
    with open(mod_path, "w") as fh:
        fh.write(
            imports +
            "MARKER = %r\n"
            "def payload(batch):\n"
            "    %s"
            "        %s\n"
            "    return bytes(batch.data).upper()\n" % (marker, gate, kill))
    return name + ":payload"


def _write_count_kill_module(plugin_dir, name, limit):
    """Payload that SIGKILLs while fewer than `limit` kill-claim files
    exist (each dying worker drops one pid-named file first)."""
    mod_path = os.path.join(plugin_dir, name + ".py")
    with open(mod_path, "w") as fh:
        fh.write(
            "import glob, os, signal\n"
            "KDIR = %r\n"
            "LIMIT = %d\n"
            "def payload(batch):\n"
            "    have = glob.glob(os.path.join(KDIR, 'k-*'))\n"
            "    if len(have) < LIMIT:\n"
            "        with open(os.path.join(KDIR, 'k-%%d' %% os.getpid()),\n"
        "                      'w') as _m:\n"
        "            _m.write('x')\n"
            "        os.kill(os.getpid(), signal.SIGKILL)\n"
            "    return bytes(batch.data).upper()\n" % (plugin_dir, limit))
    return name + ":payload"


def _run_stream(spec, path, **kwargs):
    """Collect a full stream() into a list (sys.path handling is the
    caller's job — the generator is lazy). Pins nodes=1 (UMA)
    unless the caller overrides (see module docstring)."""
    kwargs.setdefault("nodes", 1)
    return list(forkrun.stream(spec, path, **kwargs))


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestStreamingRecovery(unittest.TestCase):
    """Streaming Tier-3: WorkerTxn recovery during active stream()."""

    def tearDown(self):
        assert_no_zombies(self)

    def test_sigsegv_during_stream_unordered(self):
        """Worker SIGSEGVs during stream(order='none') -> stream
        continues, complete output, recovered batch exactly once."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34su_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34su_mod", "batch.batch_index == 0",
                sig="SIGSEGV")
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = _run_stream(spec, path, workers=2,
                                  orchestrator=True, order="none")
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=2,
                                  orchestrator=True, order="none")
            self.assertEqual(lines_of(res), lines_of(healthy))
            self.assertEqual(len(res), len(healthy))
            self.assertGreater(len(res), 0)
            self.assertLess(dt, 120)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_sigsegv_during_stream_ordered(self):
        """Worker SIGSEGVs during stream(order='index') -> reassembly
        holds the gap; results in exact batch order with the late
        batch in its correct position."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34so_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34so_mod", "batch.batch_index == 0",
                sig="SIGSEGV")
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = _run_stream(spec, path, workers=2,
                                  orchestrator=True, order="index")
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=2,
                                  orchestrator=True, order="index")
            self.assertEqual(joined_bytes(res), joined_bytes(healthy))
            self.assertLess(dt, 120)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_sigkill_during_stream(self):
        """External-style SIGKILL during stream() -> recovery, stream
        continues with complete output."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34sk_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34sk_mod", "batch.batch_index == 0",
                sig="SIGKILL")
            sys.path.insert(0, plugin_dir)
            try:
                res = _run_stream(spec, path, workers=2,
                                  orchestrator=True, order="none")
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=2,
                                  orchestrator=True, order="none")
            self.assertEqual(lines_of(res), lines_of(healthy))
            self.assertEqual(len(res), len(healthy))
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_multiple_deaths_during_stream(self):
        """2 workers crash at different batches during stream() ->
        both recovered, stream continues, output complete."""
        path = _make_input(3000)
        plugin_dir = tempfile.mkdtemp(prefix="w34md_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34md_mod",
                "batch.batch_index in (0, 7)", per_batch=True)
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = _run_stream(spec, path, workers=2,
                                  orchestrator=True, order="index")
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=2,
                                  orchestrator=True, order="index")
            self.assertEqual(joined_bytes(res), joined_bytes(healthy))
            self.assertLess(dt, 120)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_recovered_batch_not_duplicated(self):
        """Recovered batch's output appears exactly once (Counter over
        result blobs: no loss, no duplication)."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34nd_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34nd_mod", "batch.batch_index == 0")
            sys.path.insert(0, plugin_dir)
            try:
                res = _run_stream(spec, path, workers=4,
                                  orchestrator=True, order="none")
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=4,
                                  orchestrator=True, order="none")
            self.assertEqual(Counter(lines_of(res)), Counter(lines_of(healthy)))
            # Every blob unique (input lines unique -> batch blobs
            # unique): exactly-once means no blob appears twice.
            self.assertEqual(len(lines_of(res)), len(set(lines_of(res))))
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_stream_backpressure_during_recovery(self):
        """Slow consumer + worker crash -> recovery happens, memory
        stays bounded (streaming holds only the in-flight window)."""
        import resource

        path = _make_input(3000)
        plugin_dir = tempfile.mkdtemp(prefix="w34bp_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34bp_mod", "batch.batch_index == 0")
            sys.path.insert(0, plugin_dir)
            try:
                before = resource.getrusage(
                    resource.RUSAGE_SELF).ru_maxrss
                n = 0
                got = []
                for blob in forkrun.stream(spec, path, workers=2,
                                           orchestrator=True, nodes=1,
                                           order="none"):
                    got.append(blob)
                    n += 1
                    time.sleep(0.002)
                after = resource.getrusage(
                    resource.RUSAGE_SELF).ru_maxrss
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=2,
                                  orchestrator=True, order="none")
            self.assertEqual(lines_of(got), lines_of(healthy))
            self.assertGreater(n, 0)
            # ru_maxrss is KB on Linux; 100MB headroom is generous
            # for a ~40KB input (any leak-per-recovery would scale
            # with output, not stay flat).
            self.assertLess(after - before, 100 * 1024,
                            "parent grew during slow-drain recovery")
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
