import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import run_dist  # noqa: E402


class TestTopologyResolution(unittest.TestCase):
    def _patch_topo(self, online, node_cpus, node_mem_kb, allowed_cpus, allowed_mems):
        def fake_read_first(path):
            if path == "/sys/devices/system/node/online":
                return ",".join(str(n) for n in online) + "\n"
            if path == "/proc/self/status":
                lines = []
                lines.append("Cpus_allowed_list:\t" + ",".join(str(c) for c in allowed_cpus) + "\n")
                lines.append("Mems_allowed_list:\t" + ",".join(str(m) for m in allowed_mems) + "\n")
                return "".join(lines)
            for nid in online:
                if path == f"/sys/devices/system/node/node{nid}/cpulist":
                    return ",".join(str(c) for c in node_cpus.get(nid, [])) + "\n"
                if path == f"/sys/devices/system/node/node{nid}/meminfo":
                    kb = node_mem_kb.get(nid, 0)
                    return f"Node {nid} MemTotal:       {kb} kB\nNode {nid} MemFree:        {kb} kB\n"
            return None

        patches = [
            mock.patch.object(run_dist, "_read_first", side_effect=fake_read_first),
            mock.patch.object(run_dist.os, "sched_getaffinity", side_effect=OSError("no sched"), create=True),
        ]
        return patches

    def test_auto_selects_usable_nodes(self):
        patches = self._patch_topo(
            online=[0, 1, 2], node_cpus={0:[0,1],1:[2,3],2:[4,5]},
            node_mem_kb={0:100,1:100,2:100}, allowed_cpus=[0,1,2,3,4,5], allowed_mems=[0,1,2])
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(2)
        self.assertEqual(errs, [])
        self.assertEqual(phys, [0,1])
        self.assertEqual(cpus, [[0,1],[2,3]])
        self.assertEqual(info["logical_to_physical"], [0,1])

    def test_sparse_physical_node_ids(self):
        patches = self._patch_topo(
            online=[0, 2, 7], node_cpus={0:[0],2:[1],7:[2]},
            node_mem_kb={0:100,2:100,7:100}, allowed_cpus=[0,1,2], allowed_mems=[0,2,7])
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(2)
        self.assertEqual(errs, [])
        self.assertEqual(phys, [0,2])

    def test_nodes_without_usable_memory_rejected(self):
        patches = self._patch_topo(
            online=[0, 1], node_cpus={0:[0],1:[1]},
            node_mem_kb={0:100,1:0}, allowed_cpus=[0,1], allowed_mems=[0,1])
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(2)
        self.assertNotEqual(errs, [])
        self.assertEqual(phys, [])

    def test_insufficient_available_nodes(self):
        patches = self._patch_topo(
            online=[0], node_cpus={0:[0,1]}, node_mem_kb={0:100},
            allowed_cpus=[0,1], allowed_mems=[0])
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(2)
        self.assertTrue(any("insufficient" in e for e in errs))

    def test_restricted_cpu_affinity_filters_cpus(self):
        patches = self._patch_topo(
            online=[0, 1], node_cpus={0:[0,1,2,3],1:[4,5,6,7]},
            node_mem_kb={0:100,1:100}, allowed_cpus=[1,3,5], allowed_mems=[0,1])
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(2)
        self.assertEqual(errs, [])
        self.assertEqual(cpus, [[1,3],[5]])

    def test_explicit_phys_nodes(self):
        patches = self._patch_topo(
            online=[0, 1, 2], node_cpus={0:[0],1:[1],2:[2]},
            node_mem_kb={0:100,1:100,2:100}, allowed_cpus=[0,1,2], allowed_mems=[0,1,2])
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(2, phys_nodes_spec="2,0")
        self.assertEqual(errs, [])
        self.assertEqual(phys, [2,0])

    def test_invalid_physical_node_id(self):
        patches = self._patch_topo(
            online=[0, 1], node_cpus={0:[0],1:[1]},
            node_mem_kb={0:100,1:100}, allowed_cpus=[0,1], allowed_mems=[0,1])
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(2, phys_nodes_spec="0,9")
        self.assertNotEqual(errs, [])

    def test_cpu_list_construction_and_mapping(self):
        patches = self._patch_topo(
            online=[4, 5], node_cpus={4:[10,11],5:[20,21]},
            node_mem_kb={4:100,5:100}, allowed_cpus=[10,11,20,21], allowed_mems=[4,5])
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(2)
        self.assertEqual(errs, [])
        self.assertEqual(info["logical_to_physical"], [4,5])
        self.assertEqual(cpus[0], [10,11])
        self.assertEqual(cpus[1], [20,21])

    def test_ctypes_lifetime_objects_alive(self):
        logical = [0, 2]
        per = [[0,1], [4]]
        phys_arr, counts_arr, cpu_ptrs, keepalive = run_dist.build_ctypes_topology(logical, per)
        self.assertEqual(list(phys_arr), [0,2])
        self.assertEqual(list(counts_arr), [2,1])
        self.assertEqual(phys_arr._length_, 2)
        self.assertIs(keepalive[0], phys_arr)
        self.assertIs(keepalive[1], counts_arr)
        self.assertIs(keepalive[3], cpu_ptrs)


if __name__ == "__main__":
    unittest.main()


class TestTopologyUncertainty(unittest.TestCase):
    """Addendum A §6: preserve uncertainty in topology discovery."""

    def _patch_status(self, status_text, online, node_cpus, node_mem_raw):
        def fake_read_first(path):
            if path == "/proc/self/status":
                return status_text
            if path == "/sys/devices/system/node/online":
                return online
            for nid, raw in node_mem_raw.items():
                if path == f"/sys/devices/system/node/node{nid}/meminfo":
                    return raw
            for nid, lst in node_cpus.items():
                if path == f"/sys/devices/system/node/node{nid}/cpulist":
                    return lst
            return None
        return [
            mock.patch.object(run_dist, "_read_first", side_effect=fake_read_first),
            mock.patch.object(run_dist.os, "sched_getaffinity", side_effect=OSError("no sched"), create=True),
        ]

    def test_mems_allowed_unreadable_auto_not_verified(self):
        # missing Mems_allowed_list => unknown; auto must not present nodes as verified usable
        status = "Cpus_allowed_list:\t0,1\n"  # no Mems_allowed_list
        patches = self._patch_status(status, "0,1\n", {0:"0",1:"1"},
                                     {0:"Node 0 MemTotal: 100 kB\n", 1:"Node 1 MemTotal: 100 kB\n"})
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(1)
        self.assertNotEqual(errs, [])
        self.assertEqual(phys, [])
        self.assertFalse(info.get("mems_allowed_known", True))

    def test_mems_allowed_malformed_auto_not_verified(self):
        status = "Cpus_allowed_list:\t0\nMems_allowed_list:\tbogus\n"
        patches = self._patch_status(status, "0\n", {0:"0"}, {0:"Node 0 MemTotal: 100 kB\n"})
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(1)
        self.assertNotEqual(errs, [])
        self.assertFalse(info.get("mems_allowed_known", True))

    def test_meminfo_missing_explicit_fails_clearly(self):
        status = "Cpus_allowed_list:\t0\nMems_allowed_list:\t0\n"
        patches = self._patch_status(status, "0\n", {0:"0"}, {0: None})  # meminfo missing
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(1, phys_nodes_spec="0")
        self.assertNotEqual(errs, [])
        self.assertTrue(any("memory information" in e or "cannot be validated" in e for e in errs))

    def test_meminfo_unparsable_explicit_fails_clearly(self):
        status = "Cpus_allowed_list:\t0\nMems_allowed_list:\t0\n"
        patches = self._patch_status(status, "0\n", {0:"0"}, {0:"garbage\n"})
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(1, phys_nodes_spec="0")
        self.assertNotEqual(errs, [])

    def test_mems_allowed_unreadable_explicit_fails_clearly(self):
        status = "Cpus_allowed_list:\t0\n"
        patches = self._patch_status(status, "0\n", {0:"0"}, {0:"Node 0 MemTotal: 100 kB\n"})
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(1, phys_nodes_spec="0")
        self.assertNotEqual(errs, [])
        self.assertTrue(any("Mems_allowed" in e for e in errs))

    def test_duplicate_phys_nodes_rejected_runner(self):
        status = "Cpus_allowed_list:\t0,1\nMems_allowed_list:\t0,1\n"
        patches = self._patch_status(status, "0,1\n", {0:"0",1:"1"},
                                     {0:"Node 0 MemTotal: 100 kB\n", 1:"Node 1 MemTotal: 100 kB\n"})
        with patches[0], patches[1]:
            phys, cpus, info, errs = run_dist.resolve_topology(2, phys_nodes_spec="0,0")
        self.assertNotEqual(errs, [])
        self.assertTrue(any("duplicate" in e for e in errs))

    def test_malformed_phys_nodes_rejected(self):
        phys, cpus, info, errs = run_dist.resolve_topology(2, phys_nodes_spec="a,b")
        self.assertNotEqual(errs, [])
