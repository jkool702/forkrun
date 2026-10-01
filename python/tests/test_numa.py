"""W-PY21 NUMA multi-node: born-local rings, pinning, per-node claims.

Per-node rings batch independently, so batch GRANULARITY differs
from UMA by construction — parity is over byte CONTENT (sorted
lines) or exact input reconstruction (ordered mode), never over
batch counts. Forced "@N" topologies run on any hardware (same
approach as the bash tests); real multi-socket additionally
exercises cross-node placement and stealing.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate, get, v1_available  # noqa: E402
from forkrun._numa import (build_numa_map, detect_numa_nodes,  # noqa: E402
                           distribute_workers, get_node_cpus,
                           pin_to_node)

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

NODES_2 = "@2"


def _up(batch):
    return bytes(batch.data).upper()


def _make_input(n=2000, prefix="line"):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    write_lines(path, n, fmt=prefix + " %d\n")
    return path


def _lines(res):
    return sorted(b"".join(res).splitlines())


class TestNumaTopology(unittest.TestCase):
    """Topology detection/mapping (engine-free)."""

    def test_detect_nodes(self):
        nodes = detect_numa_nodes()
        self.assertTrue(nodes)
        self.assertTrue(all(isinstance(n, int) and n >= 0
                            for n in nodes))

    def test_auto_single_or_multi(self):
        numa_map, num_nodes, cpus = build_numa_map("auto")
        online = detect_numa_nodes()
        if len(online) <= 1:
            self.assertEqual((numa_map, num_nodes), ("", 1))
        else:
            self.assertEqual(num_nodes, len(online))
            self.assertEqual(numa_map, ",".join(str(n) for n in online))
        self.assertEqual(len(cpus), num_nodes)

    def test_none_is_auto(self):
        self.assertEqual(build_numa_map(None), build_numa_map("auto"))

    def test_force_uma(self):
        for spec in (1, "1"):
            numa_map, num_nodes, _ = build_numa_map(spec)
            self.assertEqual((numa_map, num_nodes), ("", 1))

    def test_int_count(self):
        online = detect_numa_nodes()
        n = min(2, len(online))
        numa_map, num_nodes, cpus = build_numa_map(n)
        if n == 1:
            self.assertEqual((numa_map, num_nodes), ("", 1))
        else:
            self.assertEqual(num_nodes, n)
        self.assertEqual(len(cpus), num_nodes)

    def test_int_over_online_rejected(self):
        online = detect_numa_nodes()
        with self.assertRaises(ValueError):
            build_numa_map(len(online) + 1)

    def test_forced_logical(self):
        numa_map, num_nodes, cpus = build_numa_map("@4")
        self.assertEqual(num_nodes, 4)
        online = detect_numa_nodes()
        expect = ",".join(str(online[i % len(online)])
                          for i in range(4))
        self.assertEqual(numa_map, expect)
        self.assertEqual(len(cpus), 4)

    def test_explicit_list(self):
        # A lone ID string is a COUNT ("0" → invalid), not a node:
        # explicit physicals need the comma form ("0,0" = 2 logical
        # on physical 0 — the oversubscription shape).
        with self.assertRaises(ValueError):
            build_numa_map("0")
        online = detect_numa_nodes()
        spec = "%d,%d" % (online[0], online[0])
        numa_map, num_nodes, _ = build_numa_map(spec)
        self.assertEqual(num_nodes, 2)
        self.assertEqual(numa_map, spec)
        # "@1" is the single-logical UMA form.
        self.assertEqual(build_numa_map("@1")[1], 1)

    def test_invalid_specs(self):
        for bad in ("@0", "@-2", "@x", "@513", 0, -1, True, False,
                    "bogus", "", "0", "0,,1", 513):
            with self.assertRaises(ValueError, msg=repr(bad)):
                build_numa_map(bad)
        with self.assertRaises(ValueError):
            build_numa_map("999")  # offline physical node

    def test_node_cpus_shape(self):
        cpus = get_node_cpus(detect_numa_nodes()[0])
        self.assertIsInstance(cpus, list)
        self.assertTrue(all(isinstance(c, int) and c >= 0
                            for c in cpus))

    def test_distribute_workers(self):
        self.assertEqual(distribute_workers(8, 1), [(0, 8)])
        self.assertEqual(distribute_workers(8, 4),
                         [(0, 2), (1, 2), (2, 2), (3, 2)])
        self.assertEqual(distribute_workers(7, 4),
                         [(0, 2), (1, 2), (2, 2), (3, 1)])
        self.assertEqual(distribute_workers(2, 4), [(0, 1), (1, 1)])
        self.assertEqual(distribute_workers(1, 4), [(0, 1)])
        with self.assertRaises(ValueError):
            distribute_workers(0, 2)

    def test_wid_to_node_stable_blocks(self):
        from forkrun._numa import wid_to_node as _w2n
        self.assertEqual(_w2n(8, 1), [0] * 8)
        self.assertEqual(_w2n(8, 4), [0, 0, 1, 1, 2, 2, 3, 3])
        self.assertEqual(_w2n(5, 3), [0, 0, 1, 1, 2])
        self.assertEqual(_w2n(2, 4), [0, 1])
        # Length invariant: every wid has exactly one node.
        for total in (1, 3, 7, 16):
            for nodes in (1, 2, 3, 5):
                m = _w2n(total, nodes)
                self.assertEqual(len(m), total)
                self.assertTrue(all(0 <= n < nodes for n in m))

    def test_pin_to_node_contract(self):
        # Never raises; empty list is always False.
        self.assertFalse(pin_to_node([]))
        self.assertFalse(pin_to_node(None))
        cpus = get_node_cpus(detect_numa_nodes()[0])
        if cpus:
            # Best-effort: True on a normal box, False in a
            # restricted container — either is a valid answer.
            self.assertIsInstance(pin_to_node(cpus), bool)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestNumaSymbols(unittest.TestCase):
    def test_numa_symbols_present(self):
        self.assertTrue(v1_available()["numa"])
        for sym in ("fr_py_init_numa", "fr_py_numa_ingest",
                    "fr_py_indexer_numa", "fr_py_numa_scanner",
                    "fr_py_fallow_phys", "fr_py_data_ready_node"):
            self.assertTrue(hasattr(get(), sym), sym)

    def test_init_numa_uma_equivalent(self):
        lib = get()
        self.assertEqual(lib.fr_py_init_numa(0, 0, 1, None), 0)
        lib.fr_py_destroy()


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestNumaExecution(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_numa_basic(self):
        path = _make_input()
        try:
            res = forkrun.map(_up, path, workers=4, nodes=NODES_2)
            self.assertEqual(_lines(res), _lines(
                forkrun.map(_up, path, workers=4, nodes=1)))
        finally:
            os.unlink(path)

    def test_numa_vs_uma_content(self):
        path = _make_input(3000)
        try:
            uma = forkrun.map(_up, path, workers=4, nodes=1,
                              order="index")
            numa = forkrun.map(_up, path, workers=4, nodes=NODES_2,
                               order="index")
            self.assertEqual(_lines(uma), _lines(numa))
        finally:
            os.unlink(path)

    def test_numa_ordered_reconstructs(self):
        # The C orderer (numa=1) emits batches in input order:
        # concatenation reconstructs the source byte-exact.
        path = _make_input(1500)
        try:
            with open(path, "rb") as fh:
                expected = fh.read().upper()
            res = forkrun.map(_up, path, workers=4, nodes=NODES_2,
                              order="index")
            self.assertEqual(b"".join(res), expected)
        finally:
            os.unlink(path)

    def test_numa_streaming(self):
        path = _make_input(1500)
        try:
            res = list(forkrun.stream(_up, path, workers=4,
                                      nodes=NODES_2))
            self.assertEqual(_lines(res), _lines(
                forkrun.map(_up, path, workers=4, nodes=1)))
        finally:
            os.unlink(path)

    def test_numa_streaming_ordered(self):
        path = _make_input(1500)
        try:
            with open(path, "rb") as fh:
                expected = fh.read().upper()
            res = list(forkrun.stream(_up, path, workers=4,
                                      nodes=NODES_2, order="index"))
            self.assertEqual(b"".join(res), expected)
        finally:
            os.unlink(path)

    def test_numa_pipe_source(self):
        # The NUMA ingest owns pipes directly (no pre-spill).
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(r)
            with os.fdopen(w, "w") as fh:
                for i in range(1200):
                    fh.write("pipe %d\n" % i)
            os._exit(0)
        os.close(w)
        try:
            res = forkrun.map(_up, r, workers=4, nodes=NODES_2)
        finally:
            os.close(r)
            os.waitpid(pid, 0)
        path = _make_input(1200, prefix="pipe")
        try:
            self.assertEqual(_lines(res), _lines(
                forkrun.map(_up, path, workers=4, nodes=1)))
        finally:
            os.unlink(path)

    def test_numa_run_discard(self):
        path = _make_input(600)
        try:
            self.assertIsNone(forkrun.run(_up, path, workers=2,
                                          nodes=NODES_2))
        finally:
            os.unlink(path)

    def test_numa_empty_input(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            self.assertEqual(
                forkrun.map(_up, path, workers=4, nodes=NODES_2), [])
            self.assertEqual(
                list(forkrun.stream(_up, path, workers=4,
                                    nodes=NODES_2)), [])
        finally:
            os.unlink(path)

    def test_numa_fault_tolerance(self):
        # Segfault on one batch: respawned, rest completes (same
        # best-effort batch loss as the UMA reactor path).
        path = _make_input(1500)
        d = tempfile.mkdtemp(prefix="w21segv_")
        mod_path = os.path.join(d, "w21segv_mod.py")
        try:
            with open(mod_path, "w") as fh:
                fh.write(
                    "import ctypes\n"
                    "def payload(batch):\n"
                    "    if batch.batch_index == 0:\n"
                    "        ctypes.string_at(0)\n"
                    "    return bytes(batch.data).upper()\n")
            sys.path.insert(0, d)
            try:
                res = forkrun.map("w21segv_mod:payload", path,
                                  workers=4, nodes=NODES_2)
            finally:
                sys.path.remove(d)
            healthy = forkrun.map(_up, path, workers=4, nodes=1)
            # Batch granularity differs across topologies, so the
            # comparison is over LINES: every landed line is
            # byte-exact, and only the crashed batch's lines may be
            # missing (a SIGKILL-class death runs no code — no escrow
            # deposit exists for it). Never a hang, never a
            # whole-run abort for one batch's death.
            rl, hl = _lines(res), _lines(healthy)
            self.assertTrue(rl)
            self.assertTrue(set(rl) <= set(hl))
            self.assertLess(len(hl) - len(rl), 300)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(d, ignore_errors=True)

    def test_numa_spawn_mode(self):
        path = _make_input(800)
        try:
            res = forkrun.map("tr a-z A-Z", path, mode="spawn",
                              workers=4, nodes=NODES_2)
            self.assertEqual(_lines(res), _lines(
                forkrun.map(_up, path, workers=4, nodes=1)))
        finally:
            os.unlink(path)

    def test_numa_splice_mode(self):
        path = _make_input(1500)
        try:
            res = forkrun.map(None, path, mode="splice",
                              bytes=32768, workers=2, nodes=NODES_2)
            exp = forkrun.map(None, path, mode="splice",
                              bytes=32768, workers=2, nodes=1)
            self.assertEqual(_lines(res), _lines(exp))
        finally:
            os.unlink(path)

    def test_numa_worker_pinning_observed(self):
        # Workers record the CPU they run on; with @2 all workers
        # share physical 0's cpuset on this single-socket box — the
        # assertion is structural (every worker pinned to a valid
        # online CPU), not a specific layout.
        import shutil as _shutil
        d = tempfile.mkdtemp(prefix="w21pin_")
        mod_path = os.path.join(d, "w21pin_mod.py")
        try:
            with open(mod_path, "w") as fh:
                fh.write(
                    "import os\n"
                    "def payload(batch):\n"
                    "    return str(os.sched_getaffinity(0)).encode()\n")
            sys.path.insert(0, d)
            try:
                res = forkrun.map("w21pin_mod:payload",
                                  _make_input(400), workers=4,
                                  nodes=NODES_2)
            finally:
                sys.path.remove(d)
            self.assertTrue(res)
            online_cpus = set()
            for n in detect_numa_nodes():
                online_cpus.update(get_node_cpus(n))
            for blob in res:
                cpus = eval(blob.decode())
                self.assertTrue(set(cpus) & online_cpus)
        finally:
            _shutil.rmtree(d, ignore_errors=True)

    def test_numa_distribution_round_robin(self):
        # 5 workers over @3: nodes own contiguous wid blocks with
        # round-robin counts (2,2,1) — verify via per-wid node
        # capture through the reactor's lineage-agnostic channel:
        # batch affinity is engine-internal, so assert the mapping
        # function itself plus a live 3-node run.
        from forkrun._numa import distribute_workers as _dist
        self.assertEqual(_dist(5, 3), [(0, 2), (1, 2), (2, 1)])
        path = _make_input(900)
        try:
            res = forkrun.map(_up, path, workers=5, nodes="@3")
            self.assertEqual(_lines(res), _lines(
                forkrun.map(_up, path, workers=5, nodes=1)))
        finally:
            os.unlink(path)

    def test_numa_dynamic_fork_pipelining(self):
        # Bursty pipe source: workers fork on first DATA publish
        # (per node) and the run completes with full content.
        # NOTE on timing: the NUMA ingest fills 2MB pipe chunks, so
        # a sub-chunk trickle is (by engine design) held until EOF
        # — first-result latency on pipes is chunk-fill bound, not
        # fork bound. The bursty shape below (multi-MB instantly)
        # publishes promptly; the test pins completion + content,
        # with a generous bound that fails only on a real stall.
        import time as _time
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(r)
            with os.fdopen(w, "w", buffering=1024 * 1024) as fh:
                for i in range(200000):
                    fh.write("slow %06d\n" % i)
                fh.flush()
                _time.sleep(2.0)
                for i in range(200000, 210000):
                    fh.write("slow %06d\n" % i)
            os._exit(0)
        os.close(w)
        try:
            t0 = _time.monotonic()
            res = list(forkrun.stream(_up, r, workers=4,
                                      nodes=NODES_2))
            dt = _time.monotonic() - t0
        finally:
            os.close(r)
            os.waitpid(pid, 0)
        # Completes promptly after EOF (no hang past the source).
        self.assertLess(dt, 6.0)
        # Full content lands (both bursts: 210k lines).
        want = sorted(("SLOW %06d" % i).encode()
                      for i in list(range(200000))
                      + list(range(200000, 210000)))
        got = sorted(x.strip() for x in
                     b"".join(res).splitlines())
        self.assertEqual(got, want)

    def test_numa_orchestrator_flag_accepted(self):
        # NUMA implies reactor supervision; the flag is accepted for
        # call uniformity (both values run the same pipeline).
        path = _make_input(500)
        try:
            a = forkrun.map(_up, path, workers=2, nodes=NODES_2,
                            orchestrator=True)
            b = forkrun.map(_up, path, workers=2, nodes=NODES_2,
                            orchestrator=False)
            self.assertEqual(_lines(a), _lines(b))
        finally:
            os.unlink(path)

    def test_numa_nodes_validation(self):
        # Bad specs fail eagerly (before any fork).
        for bad in ("@0", "bogus", 0, -2, True):
            with self.assertRaises((ValueError, TypeError),
                                   msg=repr(bad)):
                forkrun.map(_up, "f.txt", nodes=bad)
        with self.assertRaises((ValueError, TypeError)):
            list(forkrun.stream(_up, "f.txt", nodes="@0"))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestNumaPurity(unittest.TestCase):
    def test_no_banned_tokens(self):
        pkg = os.path.join(os.path.dirname(__file__), "..", "forkrun")
        offenders = []
        for name in ("_numa.py",):
            with open(os.path.join(pkg, name)) as fh:
                src = fh.read()
            for token in ("subprocess.", "Popen", "import pickle",
                          "from pickle", "cPickle", "os.system",
                          "frun.bash", "source ./frun",
                          "multiprocessing", "multiprocessing.Pipe",
                          "multiprocessing.Queue"):
                if token in src:
                    offenders.append("%s: %s" % (name, token))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
