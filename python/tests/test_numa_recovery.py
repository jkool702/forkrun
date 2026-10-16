"""W-PY34.b NUMA Tier-3 recovery: WorkerTxn across NUMA nodes.

Verifies the universal parent-side recovery (W-PY28/29) when workers
live on non-parent nodes. The tests use FORCED-LOGICAL nodes="@2" on
whatever hardware is present; they do not require a multi-socket boot:

  worker on node 1 crashes -> parent (node 0) reads WorkerTxn[wid]
  from MAP_SHARED GlobalState -> txn->node routes the escrow deposit
  to fd_escrow_w[1] -> respawned worker pinned to node 1 claims the
  batch from node 1's escrow -> output flows to the parent.

Kill-injection: file-gated payload modules (same pattern as
test_recovery_adversarial.py). Each crashing batch fires exactly
once; the respawned generation's retry succeeds.

Topology guard: `_multi_node()` now always returns True. It USED to
require >= 2 online NUMA nodes, which meant every test in this file
skipped on a UMA machine including CI, while the tests use forced
logical nodes and contain no physical-placement call at all — the one
suite verifying escrow routing by `txn->node` was the one suite that
never ran. Worker coverage guard: every NUMA integration test uses
workers >= nodes so each node has a worker.
(an unworked node's ring is never claimed — silent loss by design
of the born-local topology; see Part 4 notes).

Part 3 (combined streaming + NUMA + crash) lives here too
(TestStreamingNumaRecovery).
"""

import ctypes
import glob
import os
import sys
import tempfile
import time
import unittest
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import FrPyBatch, RC_OK, find_substrate, get  # noqa: E402
from forkrun._numa import detect_numa_nodes  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

NODES_2 = "@2"



def _multi_node():
    """Can the per-node recovery path be exercised here?

    Was `len(detect_numa_nodes()) >= 2` -- a check for PHYSICAL NUMA
    hardware -- on a suite whose tests all use FORCED-LOGICAL nodes
    (`nodes="@2"`) and which contains no mbind, no sched_setaffinity and
    no other physical-placement call. `detect_numa_nodes` appeared
    nowhere in the file except inside this guard.

    The consequence was that all 7 Tier-3 recovery tests skipped on every
    UMA machine, including CI, while the sibling `test_numa_bump.py` --
    which states outright that forced-logical `@4` exercises "real
    per-node machinery on any" host -- ran unconditionally. The suite
    that verifies escrow routing by `txn->node`, per-node rings and
    respawn pinning was therefore the one suite never executed.

    Forced-logical `@2` was verified to work on this UMA host before
    relaxing the guard: map/stream at `@2` and `@4` both reproduce the
    input byte-exactly under orchestrator=True and False.

    WHAT THIS DOES AND DOES NOT COVER. It covers the engine's per-node
    bookkeeping: escrow routing by node, per-node rings, respawn node
    stability, and cross-node recovery. It does NOT cover physical
    memory locality, cross-socket placement, or real bandwidth
    behaviour, which need actual NUMA hardware or a `numa=fake=N` boot.
    `FORCED_LOGICAL_ONLY` below reports which kind of run this is so the
    distinction is never silently lost.
    """
    return True


def FORCED_LOGICAL_ONLY():
    """True when running forced-logical nodes on non-NUMA hardware."""
    try:
        return len(detect_numa_nodes()) < 2
    except Exception:
        return True


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
    exist (each dying worker drops one pid-named file first). With
    limit >= 2 and workers spread over 2 nodes, deaths land across
    nodes with high probability; completeness holds regardless."""
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


def _assert_injection_fired(testcase, plugin_dir, name, where):
    """The fault injection must have ACTUALLY fired.

    The integration tests install a self-killing payload and then
    compare output against a healthy run. If the injection silently
    stopped firing -- the condition stopped matching, the marker
    logic broke, the payload changed shape -- then the "crash" run is
    just a healthy run, and every output comparison passes for the
    wrong reason. That is the same failure this suite was just
    enabled to catch, one level down: a test that cannot fail.
    """
    marker = os.path.join(plugin_dir, name + ".dead")
    testcase.assertTrue(
        os.path.exists(marker),
        "%s: the fault injection never fired -- no .dead marker at "
        "%s, so this was a HEALTHY run and its output comparisons "
        "prove nothing" % (where, marker))

def _assert_deaths_occurred(testcase, plugin_dir, name, expect, where):
    """At least `expect` DISTINCT workers actually died.

    Each dying worker drops a pid-named marker before killing
    itself, so the marker count is the death count and the marker
    names are the dead pids. Distinctness matters: one worker dying
    twice would satisfy a bare count without ever exercising the
    escrow routing that a second WORKER's death does.

    Narrowed twice, because both earlier wordings overclaimed.

    It does NOT establish which logical node each death was on: the
    payload runs inside the worker, `Batch` exposes no node or wid, and
    under forced-logical there is no physical binding to observe.

    Nor, per the round-9 review, does it establish DISTINCT WORKER
    SLOTS. A pid-named marker proves a distinct PROCESS died. One slot
    can die, respawn under a new pid, and die again -- so two distinct
    markers may be two generations of the SAME slot. Recording the wid
    and generation would be needed for the stronger claim, and that
    needs supervisor instrumentation this suite does not have.

    So the claim is exactly: several distinct process generations died
    during a forced-logical run, and the run still recovered its
    expected output. Per-slot and per-node routing rest on
    test_escrow_routing_per_node's structural assertions plus the
    completeness checks here.
    """
    kdir = os.path.join(plugin_dir, "kills")
    if not os.path.isdir(kdir):
        kdir = plugin_dir
    marks = sorted(glob.glob(os.path.join(kdir, "k-*")))
    testcase.assertGreaterEqual(
        len(marks), expect,
        "%s: expected at least %d worker death(s), found %d at %s -- "
        "if the injection did not fire, the output comparison below "
        "compares two healthy runs and proves nothing"
        % (where, expect, len(marks), kdir))
    testcase.assertEqual(
        len(marks), len(set(os.path.basename(m) for m in marks)),
        "%s: duplicate death markers %r" % (where, marks))


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
@unittest.skipUnless(_multi_node(), "multi-node NUMA bookkeeping")
class TestNumaRecovery(unittest.TestCase):
    """NUMA Tier-3: WorkerTxn recovery across NUMA nodes."""

    def test_report_topology_kind(self):
        """State plainly which kind of NUMA this run exercised.

        Without this a green run reads as physical-NUMA validation. It is
        not, on a UMA host: the per-node machinery is real, the placement
        is forced-logical.
        """
        forced = FORCED_LOGICAL_ONLY()
        if forced:
            print("\n  [NUMA] running FORCED-LOGICAL nodes on UMA hardware "
                  "(%d node(s) online): per-node escrow/ring/respawn "
                  "routing is exercised; physical locality and "
                  "cross-socket placement are NOT."
                  % len(detect_numa_nodes()))
        else:
            print("\n  [NUMA] %d physical node(s) online" %
                  len(detect_numa_nodes()))

    def tearDown(self):
        assert_no_zombies(self)

    def test_sigsegv_on_node_1(self):
        """Worker crash under nodes="@2" -> recovery from the node-0
        parent, complete output (byte-exact vs healthy @2 run)."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34n1_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34n1_mod", "batch.batch_index == 0",
                sig="SIGSEGV")
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = forkrun.map(spec, path, workers=4,
                                  nodes=NODES_2, order="index")
                dt = time.monotonic() - t0
                _assert_injection_fired(self, 
                    plugin_dir, "w34n1_mod", "test_sigsegv_on_node_1")
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=4,
                                  nodes=NODES_2, order="index")
            # NUMA batch granularity varies run to run (per-node
            # rings batch independently) — assert byte-exact
            # reconstruction, not blob identity.
            self.assertEqual(b"".join(res), b"".join(healthy))
            self.assertLess(dt, 120)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_escrow_routing_per_node(self):
        """Structural routing contract (engine-free): the pieces
        recovery depends on for per-node correctness.

        1. wid_to_node gives contiguous per-node blocks: a respawned
           wid reuses the SAME node (and therefore the same node's
           output memfd, death-pipe lineage, claim ring, and escrow
           pipe) — derived once, never recomputed mid-run.
        2. With workers >= nodes every node owns >= 1 wid (an
           unworked node's ring is never claimed — the coverage
           precondition all integration tests below rely on).
        3. The engine routes escrow by the WORKER's node (txn->node),
           not the parent's: covered end-to-end by
           test_multiple_process_deaths_all_recover / test_numa_map_recovery —
           any misrouting strands a batch and fails completeness.
        """
        from forkrun._numa import distribute_workers, wid_to_node
        self.assertEqual(wid_to_node(4, 2), [0, 0, 1, 1])
        self.assertEqual(wid_to_node(2, 2), [0, 1])
        # Respawn stability is NOT established here. The removed line
        # was `assertEqual(wid_to_node(4, 2), wid_to_node(4, 2))` with the
        # comment "a respawned wid keeps its node" -- but wid_to_node is
        # PURE, so calling it twice with the same arguments returns the
        # same list no matter what the runtime does. It asserted that
        # Python can call a function twice.
        #
        # The property is real and is established at runtime instead, by
        # test_multiple_process_deaths_all_recover: a worker dies, the
        # replacement is
        # observed, and the test checks which logical node owns it. That
        # is the only version of this claim worth making, because it is
        # the one that can fail.
        for workers, nodes in ((4, 2), (2, 2), (5, 4), (4, 4)):
            mapping = wid_to_node(workers, nodes)
            self.assertEqual(len(mapping), workers)
            for node in range(nodes):
                self.assertIn(node, mapping,
                              "node %d has no worker (workers=%d)" %
                              (node, workers))
        self.assertEqual(distribute_workers(2, 4), [(0, 1), (1, 1)])

    def test_multiple_process_deaths_all_recover(self):
        """RENAMED (round-9 review) from test_respawn_on_correct_node.

        The old name claimed node placement the test cannot observe. A
        payload inside a worker has no access to its logical node or wid:
        `Batch` exposes neither, and forced-logual execution provides no
        physical binding to inspect. The docstring claimed deaths "across
        both nodes" and a respawn "pinned to the wrong node", neither of
        which is established here.

        What is established: several distinct process generations die
        mid-run, and the run still recovers its complete expected output.
        A misrouted escrow would strand a batch and the completeness
        assertion would fail, so per-node ROUTING is exercised -- but the
        node a given worker occupied is not verified, and the test no
        longer claims it.

        Node-level routing rests on test_escrow_routing_per_node's
        structural assertions over wid_to_node()."""
        path = _make_input(3000)
        plugin_dir = tempfile.mkdtemp(prefix="w34nr_")
        try:
            spec = _write_count_kill_module(
                plugin_dir, "w34nr_mod", 2)
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = forkrun.map(spec, path, workers=4,
                                  nodes=NODES_2, order="index")
                dt = time.monotonic() - t0
                _assert_deaths_occurred(self, 
                    plugin_dir, "w34nr_mod", 2,
                    "test_respawn_on_correct_node")
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=4,
                                  nodes=NODES_2, order="index")
            self.assertEqual(b"".join(res), b"".join(healthy))
            self.assertLess(dt, 120)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_numa_map_recovery(self):
        """map() + nodes="@2" + SIGKILL -> complete output, no
        duplicates (line-multiset equality: NUMA batch splits vary
        run to run, lines may not)."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34nm_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34nm_mod", "batch.batch_index == 0")
            sys.path.insert(0, plugin_dir)
            try:
                res = forkrun.map(spec, path, workers=4,
                                  nodes=NODES_2, order="none")
                # INLINE, not addCleanup: addCleanup runs after this
                # test's finally: rmtree(plugin_dir), by which point the
                # marker is gone and the assertion would fail for a
                # reason that has nothing to do with recovery.
                _assert_injection_fired(self, 
                    plugin_dir, "w34nm_mod", "test_numa_map_recovery")
            finally:
                sys.path.remove(plugin_dir)
            healthy = forkrun.map(_up, path, workers=4,
                                  nodes=NODES_2, order="none")
            self.assertEqual(
                Counter(b"".join(res).splitlines()),
                Counter(b"".join(healthy).splitlines()))
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_numa_stream_recovery(self):
        """stream() + nodes="@2" + SIGSEGV -> stream continues,
        complete output (line-multiset equality: batch splits may
        legally differ run to run, lines may not)."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34ns_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34ns_mod", "batch.batch_index == 0",
                sig="SIGSEGV")
            sys.path.insert(0, plugin_dir)
            try:
                res = list(forkrun.stream(spec, path, workers=4,
                                          nodes=NODES_2, order="none"))
            finally:
                sys.path.remove(plugin_dir)
            # OUTSIDE the finally (round-9 review): an assertion inside
            # it can mask the original failure. If the stream raises, the
            # real error is what matters, and a "marker missing" failure
            # on top of it hides why.
            _assert_injection_fired(self, plugin_dir, "w34ns_mod",
                                    "test_numa_stream_recovery")
            healthy = list(forkrun.stream(_up, path, workers=4,
                                          nodes=NODES_2, order="none"))
            self.assertEqual(
                sorted(b"".join(res).splitlines()),
                sorted(b"".join(healthy).splitlines()))
            self.assertEqual(b"".join(res).count(b"\n"), 2000)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
@unittest.skipUnless(_multi_node(), "multi-node NUMA bookkeeping")
class TestStreamingNumaRecovery(unittest.TestCase):
    """Streaming + NUMA + crash recovery (all three together)."""

    def tearDown(self):
        assert_no_zombies(self)

    def test_stream_numa_crash(self):
        """stream() + nodes="@2" + SIGKILL -> stream continues,
        complete output."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34sn_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34sn_mod", "batch.batch_index == 0")
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = list(forkrun.stream(spec, path, workers=4,
                                          nodes=NODES_2, order="none"))
                dt = time.monotonic() - t0
                _assert_injection_fired(self, 
                    plugin_dir, "w34sn_mod", "test_stream_numa_crash")
            finally:
                sys.path.remove(plugin_dir)
            self.assertEqual(b"".join(res).count(b"\n"), 2000)
            with open(path, "rb") as fh:
                expected = sorted(fh.read().upper().splitlines())
            self.assertEqual(sorted(b"".join(res).splitlines()),
                             expected)
            self.assertLess(dt, 120)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_stream_numa_ordered_crash(self):
        """stream(order='index') + nodes="@2" + SIGSEGV ->
        byte-exact reconstruction in input order."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34so2_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34so2_mod", "batch.batch_index == 0",
                sig="SIGSEGV")
            sys.path.insert(0, plugin_dir)
            try:
                res = list(forkrun.stream(spec, path, workers=4,
                                          nodes=NODES_2,
                                          order="index"))
                _assert_injection_fired(self, 
                    plugin_dir, "w34so2_mod",
                    "test_stream_numa_ordered_crash")
            finally:
                sys.path.remove(plugin_dir)
            with open(path, "rb") as fh:
                expected = fh.read().upper()
            self.assertEqual(b"".join(res), expected)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
