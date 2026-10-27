"""W-PY29 adversarial recovery tests: race windows + rollback exactness.

Exercises the 4-state WorkerTxn machine (IDLE → CLAIMING → CLAIMED →
COMMITTING → IDLE) at its boundaries:

- Claim→publish race (TXN_CLAIMING → RACE_DETECTED, rc 4)
- ACK→clear race (TXN_COMMITTING → RACE_DETECTED, rc 4)
- SIGKILL partial-output rollback, ordered AND unordered (cursor fix)
- output_start exactness across a simulated respawn
- Publish→payload boundary (the normal catastrophic path)
- Multiple / back-to-back deaths (each transaction recovered once)
- No lseek in the claim-time publication path (white-box lock-in)

Kill-injection mechanism: FORKRUN_TEST_DIE_AT_CLAIM /
FORKRUN_TEST_DIE_AT_COMMIT make a worker SIGKILL itself inside the
exact window (checked in fr_py_claim / fr_py_ack_core, inert unless
the env var is set). Unit tests drive this in a forked child sharing
the MAP_SHARED engine; integration tests set the env var around a
real orchestrator run and expect abort/resume (RuntimeError).

No threads. Forks only where noted; every forked child is reaped.
"""

import ctypes
import os
import select
import signal
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import (FrPyBatch, RC_OK, find_substrate,  # noqa: E402
                               get)
from forkrun._worker import _HDR  # noqa: E402

from _helpers import (assert_no_zombies, joined_bytes,  # noqa: E402
                      ChildLifecycleMixin,
                      lines_of, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


# WorkerTxn phases. 0-3 live in forkrun_ring.c; 4 (WAITING) is the
# shim-only phase that makes an idle worker's death recoverable.
(TXN_IDLE, TXN_CLAIMING, TXN_CLAIMED, TXN_COMMITTING,
 TXN_WAITING) = range(5)


def _waiter_node(reg):
    """Decode the shim waiter-registry word: 0 = not registered,
    else the node the wid registered on."""
    return (reg >> 1) if (reg & 1) else None



def _has_symbols():
    if not HAVE_LIB:
        return False
    try:
        lib = get()
        return all(hasattr(lib, s) for s in (
            "fr_py_recover_worker", "fr_py_ack_init",
            "fr_py_output_advanced"))
    except Exception:
        return False


def _make_input(n=2000, prefix="line"):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    write_lines(path, n, fmt=prefix + " %d\n")
    return path


def _write_kill_module(plugin_dir, name, condition, per_batch=False):
    """Write a payload module that SIGKILLs itself when `condition`
    (a Python expression over batch/os/MARKER) holds, once per marker.
    per_batch=True gives each batch index its own marker (multiple
    gated deaths across the run); False fires exactly once total."""
    mod_path = os.path.join(plugin_dir, name + ".py")
    marker = os.path.join(plugin_dir, name + ".dead")
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
            "import os, signal\n"
            "MARKER = %r\n"
            "def payload(batch):\n"
            "    %s"
            "        os.kill(os.getpid(), signal.SIGKILL)\n"
            "    return bytes(batch.data).upper()\n" % (marker, gate))
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


def _up(batch):
    return bytes(batch.data).upper()


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestClaimPublishRace(ChildLifecycleMixin, unittest.TestCase):
    """Death between begin_claim and publish reads TXN_CLAIMING → 4."""

    def tearDown(self):
        assert_no_zombies(self)

    @staticmethod
    def _close(fd):
        try:
            os.close(fd)
        except OSError:
            pass

    def _init_with_lines(self, lines):
        lib = get()
        self.assertEqual(lib.fr_py_init(0, 0), 0)
        memfd = os.memfd_create("fr_adv_in")
        self.addCleanup(lambda: self._close(memfd))
        data = "".join("line %d\n" % i for i in range(lines)).encode()
        os.write(memfd, data)
        os.lseek(memfd, 0, os.SEEK_SET)
        self.assertEqual(lib.fr_py_ingest_done(), 0)
        self.assertEqual(lib.fr_py_scan(memfd), 0)
        self.addCleanup(lib.fr_py_destroy)
        return lib

    def test_claiming_returns_code_4(self):
        """Forked child dies inside the claim window → RACE_DETECTED."""
        lib = self._init_with_lines(50)
        out_fd = os.memfd_create("fr_adv_out")
        self.addCleanup(lambda: self._close(out_fd))

        pid = os.fork()
        if pid == 0:
            # Child: share the MAP_SHARED engine, die in the window.
            try:
                lib.fr_py_worker_init(0, 0, 0, 3, 0)
                lib.fr_py_set_output_fd(out_fd)
                lib.fr_py_ack_init(out_fd)
                os.environ["FORKRUN_TEST_DIE_AT_CLAIM"] = "1"
                claimed = FrPyBatch()
                lib.fr_py_claim(ctypes.byref(claimed))
            except BaseException:
                pass
            # If the hook failed to kill us, fail loudly (exit 42).
            os._exit(42)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status),
                        "child should die by signal, got %r" % (status,))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)

        rc = lib.fr_py_recover_worker(0, 0, out_fd, 9)
        self.assertEqual(rc, 4)  # RACE_DETECTED

    def test_waiting_returns_code_1(self):
        """A death while WAITING (no ticket) is recoverable, not a race.

        W-PY31: the old shim set TXN_CLAIMING across the whole blocking
        claim, so an idle worker killed while waiting for its first
        batch was misclassified as RACE_DETECTED and aborted the run.
        WAITING is the "no ticket yet" phase; recovery must respawn.
        """
        lib = get()
        self.assertEqual(lib.fr_py_init(0, 0), 0)
        self.addCleanup(lib.fr_py_destroy)
        out_fd = os.memfd_create("fr_adv_wait_out")
        self.addCleanup(lambda: self._close(out_fd))

        pid = os.fork()
        if pid == 0:
            try:
                lib.fr_py_worker_init(0, 0, 0, 3, 0)
                lib.fr_py_set_output_fd(out_fd)
                lib.fr_py_ack_init(out_fd)
                os.environ["FORKRUN_TEST_DIE_AT_WAIT"] = "1"
                claimed = FrPyBatch()
                lib.fr_py_claim(ctypes.byref(claimed))
            except BaseException:
                pass
            # If the hook failed to fire, fail loudly.
            os._exit(42)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status),
                        "child should die by signal, got %r" % (status,))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)

        rc = lib.fr_py_recover_worker(0, 0, out_fd, 9)
        self.assertEqual(rc, 1)  # NO_BATCH — respawn, no ticket in flight

    def test_forced_claim_publish_death(self):
        """Real run with DIE_AT_CLAIM: every worker dies claiming →
        the reactor aborts (conservative) instead of losing a ticket."""
        path = _make_input(500)
        os.environ["FORKRUN_TEST_DIE_AT_CLAIM"] = "1"
        try:
            with self.assertRaisesRegex(RuntimeError, "race"):
                forkrun.map(_up, path, workers=2, orchestrator=True, nodes=1)
        finally:
            del os.environ["FORKRUN_TEST_DIE_AT_CLAIM"]
            os.unlink(path)


class WaiterHarness:
    """Shared driver for the W-PY31 waiter-registry probes.

    Claims are issued by forked children because the registry lives in
    a MAP_SHARED mapping created before any fork, and every observation
    goes through fr_py_worker_probe / fr_py_active_waiters -- the same
    state recovery reads -- rather than through timing guesses.
    """

    def tearDown(self):
        assert_no_zombies(self)

    @staticmethod
    def _close(fd):
        try:
            os.close(fd)
        except OSError:
            pass

    def _init(self, nodes=1):
        lib = get()
        if nodes == 1:
            self.assertEqual(lib.fr_py_init(0, 0), 0)
        else:
            self.assertEqual(
                lib.fr_py_init_numa(0, 0, nodes,
                                    ",".join(str(i)
                                             for i in range(nodes)).encode()),
                0)
        self.addCleanup(lib.fr_py_destroy)
        out_fd = os.memfd_create("fr_wait_out")
        self.addCleanup(lambda: self._close(out_fd))
        return lib, out_fd

    @staticmethod
    def _probe(lib, wid):
        out = (ctypes.c_uint32 * 3)()
        rc = lib.fr_py_worker_probe(wid, out)
        if rc != 0:
            raise AssertionError("worker_probe(%d) rc=%d" % (wid, rc))
        return out[0], out[1], out[2]

    def _fork_claim(self, lib, wid, out_fd, hook=None, node=0,
                    incarnation=0, env=None, delay=0.0):
        """Fork a worker that enters fr_py_claim and blocks waiting.

        `hook` (if given) makes the child SIGKILL itself at that
        injection point.  `env` is applied in the CHILD only, so a test
        can arm the publication-pause hook for one worker without
        arming it for the parent or for siblings forked later.  A child
        without a hook stays parked in TXN_WAITING until the test kills
        it.
        """
        pid = os.fork()
        if pid == 0:
            try:
                if delay:
                    time.sleep(delay)
                lib.fr_py_worker_init(wid, node, incarnation, 3, 0)
                lib.fr_py_set_output_fd(out_fd)
                lib.fr_py_ack_init(out_fd)
                if hook:
                    os.environ[hook] = "1"
                for key, val in (env or {}).items():
                    os.environ[key] = val
                claimed = FrPyBatch()
                lib.fr_py_claim(ctypes.byref(claimed))
            except BaseException:
                pass
            os._exit(42)
        return pid

    def _kill(self, pid):
        """SIGKILL (if still alive) and reap, so recovery sees a dead,
        already-reaped worker -- the order the supervisor uses."""
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

    def _wait_exit(self, pid, deadline=10.0):
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            try:
                w, _ = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                return True
            if w == pid:
                return True
            time.sleep(0.01)
        return False

    def _wait_count(self, lib, node, want, deadline=10.0):
        end = time.monotonic() + deadline
        last = None
        while time.monotonic() < end:
            last = lib.fr_py_active_waiters(node)
            if last == want:
                return
            time.sleep(0.01)
        self.fail("active_waiters[%d] never reached %d (last=%r)"
                  % (node, want, last))

    def _wait_registered(self, lib, wid, node, deadline=10.0):
        end = time.monotonic() + deadline
        last = None
        while time.monotonic() < end:
            last = _waiter_node(self._probe(lib, wid)[2])
            if last == node:
                return
            time.sleep(0.01)
        self.fail("wid %d never registered on node %d (last=%r)"
                  % (wid, node, last))

    def _registry_count(self, lib, node, wids):
        """The authority the mirror must match: how many of `wids` say
        they are registered on `node`."""
        return sum(1 for w in wids
                   if _waiter_node(self._probe(lib, w)[2]) == node)

    def _trigger_eof(self, lib):
        """Publish end-of-input with nothing to read, so every parked
        worker's next claim decodes as EOF (and releases its wait)."""
        fd = os.memfd_create("fr_wait_eof")
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            self.assertEqual(lib.fr_py_ingest_done(), 0)
            self.assertEqual(lib.fr_py_scan(fd), 0)
        finally:
            self._close(fd)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestWaiterAccounting(WaiterHarness, ChildLifecycleMixin,
                           unittest.TestCase):
    """W-PY31: a dead waiter's active_waiters contribution is removed
    exactly once, and only if it actually registered.

    The registry is wid-scoped, so recovery must not decrement a live
    sibling's contribution and must not underflow on a death that
    happened before the registration increment.  Observations go
    through fr_py_worker_probe / fr_py_active_waiters (the same state
    recovery reads), not through timing guesses.

    These cases sequence the transitions.  TestWaiterPublishRace is the
    concurrent counterpart: same registry, competing publications.
    """

    def test_death_before_registration_preserves_other_waiter(self):
        """A pre-registration death decrements nothing.

        This is the case a blanket 'TXN_WAITING => active_waiters--'
        would get wrong: the dead worker never contributed, so the
        subtraction would steal the live sibling's slot.
        """
        lib, out_fd = self._init()
        live = self._fork_claim(lib, 0, out_fd)
        self._wait_count(lib, 0, 1)

        dead = self._fork_claim(lib, 1, out_fd,
                                "FORKRUN_TEST_DIE_AT_WAIT")
        _, status = os.waitpid(dead, 0)
        self.assertTrue(os.WIFSIGNALED(status))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
        st, _node, reg = self._probe(lib, 1)
        self.assertEqual(st, TXN_WAITING)
        self.assertEqual(reg, 0, "worker died before registering")
        self.assertEqual(lib.fr_py_active_waiters(0), 1)

        self.assertEqual(lib.fr_py_recover_worker(1, 0, out_fd, 9), 1)
        self.assertEqual(
            lib.fr_py_active_waiters(0), 1,
            "pre-registration recovery stole the live waiter's slot")
        self.assertEqual(self._probe(lib, 1)[2], 0)

        os.kill(live, signal.SIGKILL)
        os.waitpid(live, 0)
        self.assertEqual(_waiter_node(self._probe(lib, 0)[2]), 0)
        self.assertEqual(lib.fr_py_recover_worker(0, 0, out_fd, 9), 1)
        self.assertEqual(lib.fr_py_active_waiters(0), 0)

    def test_death_after_registration_restores_count(self):
        """A registered waiter's death is removed by recovery."""
        lib, out_fd = self._init()
        pid = self._fork_claim(lib, 0, out_fd,
                               "FORKRUN_TEST_DIE_AT_WAIT_REGISTERED")
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)

        st, node, reg = self._probe(lib, 0)
        self.assertEqual(st, TXN_WAITING)
        self.assertEqual(node, 0)
        self.assertEqual(_waiter_node(reg), 0,
                         "worker must have registered as a waiter")
        self.assertEqual(lib.fr_py_active_waiters(0), 1)

        self.assertEqual(lib.fr_py_recover_worker(0, 0, out_fd, 9), 1)
        self.assertEqual(lib.fr_py_active_waiters(0), 0)
        self.assertEqual(self._probe(lib, 0)[:2], (TXN_IDLE, 0))

    def test_two_registered_waiters_remove_only_the_dead_one(self):
        """Concurrent waiters: recovery is wid-scoped, not a node reset."""
        lib, out_fd = self._init()
        live = self._fork_claim(lib, 0, out_fd)
        self._wait_count(lib, 0, 1)

        dead = self._fork_claim(lib, 1, out_fd,
                                "FORKRUN_TEST_DIE_AT_WAIT_REGISTERED")
        os.waitpid(dead, 0)
        self.assertEqual(lib.fr_py_active_waiters(0), 2)

        self.assertEqual(lib.fr_py_recover_worker(1, 0, out_fd, 9), 1)
        self.assertEqual(
            lib.fr_py_active_waiters(0), 1,
            "recovery removed a live sibling's waiter contribution")
        self.assertEqual(_waiter_node(self._probe(lib, 0)[2]), 0,
                         "live waiter lost its registration")

        os.kill(live, signal.SIGKILL)
        os.waitpid(live, 0)
        self.assertEqual(lib.fr_py_recover_worker(0, 0, out_fd, 9), 1)
        self.assertEqual(lib.fr_py_active_waiters(0), 0)

    def test_repeated_registered_deaths_same_wid(self):
        """Respawning the same wid cannot leave a stale contribution."""
        lib, out_fd = self._init()
        for gen in range(3):
            pid = self._fork_claim(
                lib, 0, out_fd, "FORKRUN_TEST_DIE_AT_WAIT_REGISTERED",
                incarnation=gen)
            _, status = os.waitpid(pid, 0)
            self.assertTrue(os.WIFSIGNALED(status))
            self.assertEqual(lib.fr_py_active_waiters(0), 1)
            self.assertEqual(
                lib.fr_py_recover_worker(0, gen, out_fd, 9), 1)
            self.assertEqual(lib.fr_py_active_waiters(0), 0)
            self.assertEqual(self._probe(lib, 0)[2], 0)

    def test_worker_init_publishes_node_before_first_claim(self):
        """A never-published worker's txn node is its real node.

        Recovery classifies an IDLE/WAITING death against
        txn->node.  Before this floor, a node-1 worker that died before
        its first claim read node 0 and could be dismissed as
        'normal exit' while node 0 was drained and node 1 was not.
        """
        lib, out_fd = self._init(nodes=2)
        pid = self._fork_claim(lib, 0, out_fd, node=1)
        self._wait_count(lib, 1, 1)
        st, node, reg = self._probe(lib, 0)
        self.assertEqual(st, TXN_WAITING)
        self.assertEqual(node, 1,
                         "worker_init must publish the generation's node")
        self.assertEqual(_waiter_node(reg), 1,
                         "registration must name the worker's node")

        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        self.assertEqual(lib.fr_py_recover_worker(0, 0, out_fd, 9), 1)
        self.assertEqual(lib.fr_py_active_waiters(1), 0)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestWaiterPublishRace(WaiterHarness, ChildLifecycleMixin,
                            unittest.TestCase):
    """W-PY31: competing waiter transitions cannot leave a stale mirror.

    shim_waiter_publish() snapshots popcount(g_wait_bits[node]) and
    publishes it into the engine's active_waiters gauge.  A snapshot
    taken before a competing transition and stored after it is stale,
    and if it is the LAST store the gauge stops mirroring the registry.
    A stale zero is the dangerous direction (the scanner skips the
    eventfd poke that would wake a waiter); a stale high costs
    unnecessary pokes.

    Each case holds one publication between its snapshot and its store
    (FORKRUN_TEST_WAITER_PAUSE_MS, filtered to the transition under
    test), lets a real competing transition complete, then releases it.
    A test that only registers sequentially never overlaps those two
    operations, which is exactly the defect this class covers.

    Every case waits for the participating transitions to SETTLE and
    then compares the gauge with the registry (fr_py_worker_probe) --
    the authority the gauge must mirror.
    """

    def test_register_vs_register_keeps_the_newest_count(self):
        """Two registrations: the first snapshot is stale-low.

        The pauser signals each time it holds a snapshot, so the test
        can prove the stale publication was actually RETRIED -- polling
        the gauge alone would pass as soon as the late worker's publish
        landed, before the stale store ever happened.
        """
        lib, out_fd = self._init()
        procs = []
        try:
            base = self._fork_claim(lib, 0, out_fd)
            procs.append(base)
            self._wait_count(lib, 0, 1)

            sig_r, sig_w = os.pipe()
            self.addCleanup(self._close, sig_r)
            pauser = self._fork_claim(
                lib, 1, out_fd,
                env={"FORKRUN_TEST_WAITER_PAUSE_MS": "800",
                     "FORKRUN_TEST_WAITER_PAUSE_ON": "register",
                     "FORKRUN_TEST_WAITER_SIGNAL_FD": str(sig_w)})
            procs.append(pauser)
            self._close(sig_w)
            # The pause is observable: wid 1 has claimed its bit (so the
            # registry already names it) but has not published the count.
            end = time.monotonic() + 10.0
            while time.monotonic() < end:
                if (_waiter_node(self._probe(lib, 1)[2]) == 0
                        and lib.fr_py_active_waiters(0) == 1):
                    break
                time.sleep(0.01)
            else:
                self.fail("worker 1 never entered the register pause")

            late = self._fork_claim(lib, 2, out_fd)
            procs.append(late)
            self._wait_registered(lib, 2, 0)

            # First signal: the held snapshot.  Second: the retry the
            # stale store must trigger.  A store that simply won would
            # not retry.
            for want in (1, 2):
                ready, _, _ = select.select([sig_r], [], [], 10.0)
                self.assertTrue(
                    ready, "worker 1 never signalled pause %d -- the "
                           "stale snapshot was not retried" % want)
                self.assertEqual(len(os.read(sig_r, 8)), 8,
                                 "worker 1 exited before pause %d" % want)

            # Settled: the retry's own 800 ms pause, then the exact count.
            self._wait_count(lib, 0, 3)
            self.assertEqual(self._registry_count(lib, 0, (0, 1, 2)), 3)
        finally:
            for pid in procs:
                self._kill(pid)

    def test_recovery_vs_register_cannot_publish_stale_zero(self):
        """Recovery snapshots zero, then a new waiter registers.

        This is the direction that loses a wakeup: if the stale zero is
        the last store, the scanner believes nobody is parked and does
        not poke the eventfd.
        """
        lib, out_fd = self._init()
        procs = []
        try:
            dead = self._fork_claim(lib, 0, out_fd)
            procs.append(dead)
            self._wait_count(lib, 0, 1)
            self._kill(dead)

            # Register while the recovery holds its zero snapshot.  Fork
            # BEFORE arming the pause: the child must not inherit it.
            late = self._fork_claim(lib, 1, out_fd, delay=0.1)
            procs.append(late)
            os.environ["FORKRUN_TEST_WAITER_PAUSE_MS"] = "800"
            os.environ["FORKRUN_TEST_WAITER_PAUSE_ON"] = "recover"
            try:
                rc = lib.fr_py_recover_worker(0, 0, out_fd, 9)
            finally:
                del os.environ["FORKRUN_TEST_WAITER_PAUSE_MS"]
                del os.environ["FORKRUN_TEST_WAITER_PAUSE_ON"]
            self.assertEqual(rc, 1)
            # Settled: the register that landed during the held zero
            # wins, and the recovery's retry republishes that value.
            self._wait_count(lib, 0, 1)
            self._wait_registered(lib, 1, 0)
            self.assertEqual(self._registry_count(lib, 0, (0, 1)), 1)
            self.assertEqual(self._probe(lib, 0)[2], 0)
        finally:
            for pid in procs:
                self._kill(pid)

    def test_release_vs_recovery_cannot_publish_stale_high(self):
        """A release snapshots one waiter, recovery removes the other.

        The dead waiter's bit is still set when the live worker clears
        its own, so the live worker's snapshot is 1; recovery then takes
        the last bit and publishes 0.  The release's stale 1 must not
        be the final store.
        """
        lib, out_fd = self._init()
        procs = []
        try:
            base = self._fork_claim(lib, 0, out_fd)
            procs.append(base)
            self._wait_count(lib, 0, 1)

            sig_r, sig_w = os.pipe()
            self.addCleanup(self._close, sig_r)
            releaser = self._fork_claim(
                lib, 1, out_fd,
                env={"FORKRUN_TEST_WAITER_PAUSE_MS": "800",
                     "FORKRUN_TEST_WAITER_PAUSE_ON": "release",
                     "FORKRUN_TEST_WAITER_SIGNAL_FD": str(sig_w)})
            procs.append(releaser)
            self._close(sig_w)
            self._wait_count(lib, 0, 2)

            # Kill BEFORE EOF: the dead waiter keeps its bit (recovery
            # has not run), so the releaser's snapshot still counts it.
            self._kill(base)
            self._trigger_eof(lib)

            ready, _, _ = select.select([sig_r], [], [], 10.0)
            self.assertTrue(
                ready, "worker 1 never entered the release pause")
            self.assertEqual(len(os.read(sig_r, 8)), 8,
                             "worker 1 exited before its release pause")

            # The gate is already closed (EOF was published), so an IDLE
            # death is classified NORMAL_EXIT (2) rather than NO_BATCH
            # (1).  Either way the registry cleanup has already run.
            self.assertIn(
                lib.fr_py_recover_worker(0, 0, out_fd, 9), (1, 2))
            self.assertTrue(self._wait_exit(releaser),
                            "releaser never finished its release")
            self.assertEqual(lib.fr_py_active_waiters(0), 0)
            self.assertEqual(self._registry_count(lib, 0, (0, 1)), 0)
        finally:
            for pid in procs:
                self._kill(pid)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestAckClearRace(ChildLifecycleMixin, unittest.TestCase):
    """Death between order-packet write and clear reads COMMITTING → 4."""

    def tearDown(self):
        assert_no_zombies(self)

    @staticmethod
    def _close(fd):
        try:
            os.close(fd)
        except OSError:
            pass

    def _init_with_lines(self, lines):
        lib = get()
        self.assertEqual(lib.fr_py_init(0, 0), 0)
        memfd = os.memfd_create("fr_adv_in2")
        self.addCleanup(lambda: self._close(memfd))
        data = "".join("line %d\n" % i for i in range(lines)).encode()
        os.write(memfd, data)
        os.lseek(memfd, 0, os.SEEK_SET)
        self.assertEqual(lib.fr_py_ingest_done(), 0)
        self.assertEqual(lib.fr_py_scan(memfd), 0)
        self.addCleanup(lib.fr_py_destroy)
        return lib

    def test_committing_returns_code_4(self):
        """Forked child claims, then dies inside ack → RACE_DETECTED."""
        lib = self._init_with_lines(50)
        out_fd = os.memfd_create("fr_adv_out2")
        self.addCleanup(lambda: self._close(out_fd))

        pid = os.fork()
        if pid == 0:
            try:
                lib.fr_py_worker_init(0, 0, 0, 3, 0)
                lib.fr_py_set_output_fd(out_fd)
                lib.fr_py_ack_init(out_fd)
                claimed = FrPyBatch()
                rc = lib.fr_py_claim(ctypes.byref(claimed))
                if rc != RC_OK:
                    os._exit(43)
                os.environ["FORKRUN_TEST_DIE_AT_COMMIT"] = "1"
                lib.fr_py_ack_direct(-1, -1)
            except BaseException:
                pass
            os._exit(42)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status),
                        "child should die by signal, got %r" % (status,))
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)

        rc = lib.fr_py_recover_worker(0, 0, out_fd, 9)
        self.assertEqual(rc, 4)  # RACE_DETECTED

    def test_forced_ack_clear_death(self):
        """Real run with DIE_AT_COMMIT: deaths in the commit window →
        abort (never a silent double-emit via re-execution)."""
        path = _make_input(500)
        os.environ["FORKRUN_TEST_DIE_AT_COMMIT"] = "1"
        try:
            with self.assertRaisesRegex(RuntimeError, "race"):
                forkrun.map(_up, path, workers=2, orchestrator=True, nodes=1)
        finally:
            del os.environ["FORKRUN_TEST_DIE_AT_COMMIT"]
            os.unlink(path)


@unittest.skipUnless(_has_symbols(), "recovery symbols absent")
class TestPythonOutputRollback(ChildLifecycleMixin, unittest.TestCase):
    """SIGKILL mid-payload rolls back to the cursor, both orders."""

    def tearDown(self):
        assert_no_zombies(self)

    def _kill_once_run(self, order):
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w29rb_")
        mod_name = "w29rb_%s_mod" % order
        try:
            spec = _write_kill_module(
                plugin_dir, mod_name, "batch.batch_index == 0")
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = forkrun.map(spec, path, workers=2,
                                  output="bytes",
                                  orchestrator=True, order=order, nodes=1)
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=2, order=order,
                                  nodes=1, output="bytes")
            if order == "none":
                # Completion order is nondeterministic — compare sets.
                self.assertEqual(lines_of(res), lines_of(healthy))
            else:
                self.assertEqual(joined_bytes(res), joined_bytes(healthy))
            self.assertLess(dt, 60)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_sigkill_partial_output_ordered(self):
        """order=index: orphaned bytes never referenced downstream."""
        self._kill_once_run("index")

    def test_sigkill_partial_output_unordered(self):
        """order=none: cursor rollback (catches the stale-cursor bug —
        pre-W-PY29 the first claim published no usable frontier)."""
        self._kill_once_run("none")

    def test_output_start_exact_sequence_with_respawn(self):
        """output_start is the exact live end across batches AND across
        a simulated respawn (worker_init incarn+1 + ack_init on the
        reused fd). Recovery truncates exactly to it — no more (would
        destroy committed output), no less (would duplicate)."""
        lib = get()
        self.assertEqual(lib.fr_py_init(0, 0), 0)
        self.addCleanup(lib.fr_py_destroy)
        memfd = os.memfd_create("fr_adv_in3")
        self.addCleanup(lambda: os.close(memfd))
        data = "".join("line %d\n" % i for i in range(60)).encode()
        os.write(memfd, data)
        os.lseek(memfd, 0, os.SEEK_SET)
        self.assertEqual(lib.fr_py_ingest_done(), 0)
        self.assertEqual(lib.fr_py_scan(memfd), 0)
        out_fd = os.memfd_create("fr_adv_out3")
        self.addCleanup(lambda: os.close(out_fd))

        self.assertEqual(lib.fr_py_worker_init(0, 0, 0, 3, 0), 0)
        lib.fr_py_set_output_fd(out_fd)
        lib.fr_py_ack_init(out_fd)

        # Batch 0: emit D0 + ack → end0 is the committed frontier.
        c0 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c0)), RC_OK)
        d0 = b"x" * 100
        self.assertEqual(lib.fr_py_emit(out_fd, -1, 0, c0.batch_idx,
                                        d0, len(d0)), 0)
        self.assertEqual(lib.fr_py_ack_direct(-1, -1), 0)
        end0 = os.fstat(out_fd).st_size
        # DECISION-02: the header now carries a disposition, so the
        # per-record footprint is _HDR.size, not a literal 16.
        self.assertEqual(end0, _HDR.size + len(d0))

        # Batch 1: emit D1 + ack → end1.
        c1 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c1)), RC_OK)
        d1 = b"y" * 200
        self.assertEqual(lib.fr_py_emit(out_fd, -1, 0, c1.batch_idx,
                                        d1, len(d1)), 0)
        self.assertEqual(lib.fr_py_ack_direct(-1, -1), 0)
        end1 = os.fstat(out_fd).st_size
        self.assertEqual(end1, end0 + _HDR.size + len(d1))

        # Simulated respawn: fresh generation on the reused fd. The
        # cursor must restart at the live end (one lseek at init).
        self.assertEqual(lib.fr_py_worker_init(0, 0, 1, 3, 0), 0)
        lib.fr_py_set_output_fd(out_fd)
        lib.fr_py_ack_init(out_fd)

        # Batch 2: partial output, no ack (death mid-batch).
        c2 = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(c2)), RC_OK)
        os.write(out_fd, b"PARTIAL")
        self.assertGreater(os.fstat(out_fd).st_size, end1)

        rc = lib.fr_py_recover_worker(0, 1, out_fd, 9)
        self.assertEqual(rc, 0)  # RECOVERED
        # Exact truncation: committed prefix intact, partial gone.
        self.assertEqual(os.fstat(out_fd).st_size, end1)

        # Escrowed with kills+1: the next claim re-issues batch 2.
        again = FrPyBatch()
        self.assertEqual(lib.fr_py_claim(ctypes.byref(again)), RC_OK)
        self.assertEqual(again.batch_idx, c2.batch_idx)
        self.assertEqual(again.num_kills, c2.num_kills + 1)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestPublishPayloadBoundary(ChildLifecycleMixin, unittest.TestCase):
    """Kill after CLAIMED but before any payload work: the fundamental
    normal-catastrophic path — truncate (no-op), escrow, retry wins."""

    def tearDown(self):
        assert_no_zombies(self)

    def test_kill_after_publish_before_payload(self):
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w29pp_")
        try:
            # First payload invocation in the whole run dies instantly
            # (marker gates exactly one death; the retry succeeds).
            spec = _write_kill_module(plugin_dir, "w29pp_mod", "True")
            sys.path.insert(0, plugin_dir)
            try:
                res = forkrun.map(spec, path, workers=2,
                                  output="bytes",
                                  orchestrator=True, order="index", nodes=1)
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=2, order="index", nodes=1)
            self.assertEqual(joined_bytes(res), joined_bytes(healthy))
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestMultipleDeaths(ChildLifecycleMixin, unittest.TestCase):
    """Each dead worker's transaction is recovered exactly once;
    the final output is complete regardless of death interleaving."""

    def tearDown(self):
        assert_no_zombies(self)

    def _count_kill_run(self, limit, workers):
        path = _make_input(3000)
        plugin_dir = tempfile.mkdtemp(prefix="w29mk_")
        try:
            spec = _write_count_kill_module(plugin_dir, "w29mk_mod",
                                            limit)
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = forkrun.map(spec, path, workers=workers,
                                  orchestrator=True, order="index", nodes=1)
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=workers,
                                  order="index", nodes=1)
            self.assertEqual(joined_bytes(res), joined_bytes(healthy))
            self.assertLess(dt, 120)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_two_workers_killed(self):
        self._count_kill_run(2, 4)

    def test_three_workers_killed(self):
        self._count_kill_run(3, 4)

    def test_worker_killed_while_recovery_in_progress(self):
        """Back-to-back deaths on different batches: the reactor handles
        deaths sequentially (synchronous recovery) — the second death
        lands while the first generation's replacement is still
        draining escrow. Both recover; output is complete."""
        path = _make_input(3000)
        plugin_dir = tempfile.mkdtemp(prefix="w29seq_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w29seq_mod",
                "batch.batch_index in (0, 7)", per_batch=True)
            # Two markers (one per target batch): each fires once.
            sys.path.insert(0, plugin_dir)
            try:
                res = forkrun.map(spec, path, workers=2,
                                  output="bytes",
                                  orchestrator=True, order="index", nodes=1)
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=2, order="index", nodes=1)
            self.assertEqual(joined_bytes(res), joined_bytes(healthy))
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestNoLseekInPublication(unittest.TestCase):
    """Lock-in: the claim-time publication path performs no lseek.

    The ordered ACK path keeps its pre-existing position lseek (commit
    accounting) — only the per-batch CLAIM path must be syscall-free.
    Verified white-box (the publish/bracket helpers' bodies) plus the
    behavioral rollback tests above (a cursor that required a per-batch
    lseek could not produce the exact frontiers they assert)."""

    def test_no_lseek_during_claim(self):
        root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        engine = os.path.join(root, "forkrun_ring.c")
        with open(engine) as fh:
            src = fh.read()
        for name in ("worker_txn_begin_claim",
                     "worker_txn_publish",
                     "worker_txn_abort_claim",
                     "worker_txn_begin_commit",
                     "worker_txn_clear",
                     "worker_txn_advance_output",
                     "worker_txn_init_output_cursor"):
            start = src.find(name + "(")
            # Definition site: "static inline ... name(" precedes it.
            decl = src.rfind("static inline", 0, start)
            self.assertNotEqual(decl, -1, name)
            depth = 0
            end = -1
            for i in range(src.find("{", decl), len(src)):
                if src[i] == "{":
                    depth += 1
                elif src[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            self.assertNotEqual(end, -1, name)
            body = src[decl:end]
            if name == "worker_txn_init_output_cursor":
                # The once-per-worker initializer OWNS the cursor lseek.
                self.assertIn("lseek", body, name)
            else:
                self.assertNotIn("lseek", body,
                                 "%s must not call lseek" % name)


if __name__ == "__main__":
    unittest.main()
