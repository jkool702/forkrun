"""W-PY34.b NUMA Tier-3 recovery: WorkerTxn across NUMA nodes.

Verifies the universal parent-side recovery (W-PY28/29) when workers
live on non-parent nodes (booted with numa=fake=4; tests use
nodes="@2"):

  worker on node 1 crashes -> parent (node 0) reads WorkerTxn[wid]
  from MAP_SHARED GlobalState -> txn->node routes the escrow deposit
  to fd_escrow_w[1] -> respawned worker pinned to node 1 claims the
  batch from node 1's escrow -> output flows to the parent.

Kill-injection: file-gated payload modules (same pattern as
test_recovery_adversarial.py). Each crashing batch fires exactly
once; the respawned generation's retry succeeds.

Topology guard: tests skip unless >= 2 NUMA nodes are online
(boot with numa=fake=N). Worker coverage guard: every NUMA
integration test uses workers >= nodes so each node has a worker
(an unworked node's ring is never claimed — silent loss by design
of the born-local topology; see Part 4 notes).

Part 3 (combined streaming + NUMA + crash) lives here too
(TestStreamingNumaRecovery).
"""

import ctypes
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


def _has_numa():
    if not HAVE_LIB:
        return False
    try:
        lib = get()
        return all(hasattr(lib, s) for s in (
            "fr_py_init_numa", "fr_py_recover_worker",
            "fr_py_numa_ingest", "fr_py_indexer_numa",
            "fr_py_numa_scanner"))
    except Exception:
        return False


def _multi_node():
    try:
        return len(detect_numa_nodes()) >= 2
    except Exception:
        return False


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


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
@unittest.skipUnless(_multi_node(), "Requires multi-node NUMA")
class TestNumaRecovery(unittest.TestCase):
    """NUMA Tier-3: WorkerTxn recovery across NUMA nodes."""

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
           test_respawn_on_correct_node / test_numa_map_recovery —
           any misrouting strands a batch and fails completeness.
        """
        from forkrun._numa import distribute_workers, wid_to_node
        self.assertEqual(wid_to_node(4, 2), [0, 0, 1, 1])
        self.assertEqual(wid_to_node(2, 2), [0, 1])
        # Respawn stability: the mapping is a pure function of the
        # run's (workers, nodes) — a respawned wid keeps its node.
        self.assertEqual(wid_to_node(4, 2), wid_to_node(4, 2))
        for workers, nodes in ((4, 2), (2, 2), (5, 4), (4, 4)):
            mapping = wid_to_node(workers, nodes)
            self.assertEqual(len(mapping), workers)
            for node in range(nodes):
                self.assertIn(node, mapping,
                              "node %d has no worker (workers=%d)" %
                              (node, workers))
        self.assertEqual(distribute_workers(2, 4), [(0, 1), (1, 1)])

    def test_respawn_on_correct_node(self):
        """Kills across both nodes (count-gated) -> all recovered,
        output complete. A respawn pinned to the wrong node (or an
        escrow deposited to the wrong node's pipe) would strand a
        batch and the completeness assertion would fail."""
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
@unittest.skipUnless(_multi_node(), "Requires multi-node NUMA")
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
