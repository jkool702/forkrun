import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

import run_dist  # noqa: E402
import topology  # noqa: E402


def _no_sched(_pid=0):
    raise OSError("no sched_getaffinity in synthetic fixture")


def disc_topo(sysfs, proc):
    return topology.discover_topology(sysfs_root=sysfs, proc_root=proc,
                                      sched_getaffinity=_no_sched)


def resolve_plan(*args, **kwargs):
    kwargs.setdefault("sched_getaffinity", _no_sched)
    return run_dist.resolve_mapping_plan(*args, **kwargs)


def resolve_topo(*args, **kwargs):
    kwargs.setdefault("sched_getaffinity", _no_sched)
    return run_dist.resolve_topology(*args, **kwargs)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def make_sysfs(root, *, online, nodes, cpu_packages, node_distances=None,
               proc_status=None, status_cpus=None, status_mems=None):
    """Create a synthetic /sys and /proc tree.

    nodes: {nid: {cpulist, mem_total_kb, mem_free_kb, meminfo_raw(optional)}}
    cpu_packages: {cpu: package_id} for all CPUs referenced.
    node_distances: {nid: [dists in online order]} or raw string map.
    """
    sysfs = os.path.join(root, "sys")
    proc = os.path.join(root, "proc")
    node_base = os.path.join(sysfs, "devices", "system", "node")
    cpu_base = os.path.join(sysfs, "devices", "system", "cpu")
    os.makedirs(node_base, exist_ok=True)
    os.makedirs(cpu_base, exist_ok=True)

    # online
    _write(os.path.join(node_base, "online"), online + "\n")

    # cpu topology
    all_cpus = sorted(cpu_packages.keys())
    for cid in all_cpus:
        tdir = os.path.join(cpu_base, "cpu%d" % cid, "topology")
        _write(os.path.join(tdir, "physical_package_id"), str(cpu_packages[cid]) + "\n")
        # simple core mapping: one core per cpu unless overridden not needed
        _write(os.path.join(tdir, "core_id"), str(cid) + "\n")

    # nodes
    for nid, nd in nodes.items():
        ndir = os.path.join(node_base, "node%d" % nid)
        os.makedirs(ndir, exist_ok=True)
        if "cpulist" in nd:
            _write(os.path.join(ndir, "cpulist"), str(nd["cpulist"]) + "\n")
        if "meminfo_raw" in nd:
            _write(os.path.join(ndir, "meminfo"), nd["meminfo_raw"])
        elif "mem_total_kb" in nd:
            total = nd["mem_total_kb"]
            free = nd.get("mem_free_kb", total)
            _write(os.path.join(ndir, "meminfo"),
                   "Node %d MemTotal:       %d kB\nNode %d MemFree:        %d kB\n"
                   % (nid, total, nid, free))

    # distances
    if node_distances is not None:
        for nid, row in node_distances.items():
            if isinstance(row, str):
                content = row
            else:
                content = " ".join(str(x) for x in row)
            _write(os.path.join(node_base, "node%d" % nid, "distance"), content + "\n")

    # /proc/self/status
    if proc_status is None:
        lines = []
        if status_cpus is not None:
            lines.append("Cpus_allowed_list:\t%s\n" % status_cpus)
        if status_mems is not None:
            lines.append("Mems_allowed_list:\t%s\n" % status_mems)
        proc_status = "".join(lines)
    _write(os.path.join(proc, "self", "status"), proc_status)

    return sysfs, proc


class TestTopologyInventory(unittest.TestCase):
    def test_nps4_full_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            # 8 nodes, 2 sockets (0-3 socket0, 4-7 socket1), NPS4
            online = "0-7"
            cpu_packages = {}
            nodes = {}
            # 4 cpus per node for simplicity
            for nid in range(8):
                cpus = list(range(nid * 4, nid * 4 + 4))
                nodes[nid] = {"cpulist": ",".join(str(c) for c in cpus), "mem_total_kb": 1024 * 1024}
                pkg = 0 if nid < 4 else 1
                for c in cpus:
                    cpu_packages[c] = pkg
            # symmetric NPS4-like distances
            dist = {}
            for i in range(8):
                row = []
                for j in range(8):
                    if i == j:
                        row.append(10)
                    elif (i < 4) == (j < 4):
                        row.append(12)
                    else:
                        row.append(32)
                dist[i] = row
            sysfs, proc = make_sysfs(td, online=online, nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0-31", status_mems="0-7")
            inv = disc_topo(sysfs, proc)

        self.assertEqual(inv["online_nodes"], list(range(8)))
        self.assertTrue(inv["online_known"])
        self.assertTrue(inv["allowed_mem_nodes_known"])
        self.assertEqual(inv["allowed_mem_nodes"], list(range(8)))
        self.assertTrue(inv["allowed_cpus_known"])
        self.assertEqual(inv["cpu_topology"]["socket_count"], 2)
        for nid in range(8):
            nd = inv["nodes"][nid]
            self.assertTrue(nd["cpus_known"])
            self.assertEqual(nd["mem_state"], "has")
            self.assertEqual(nd["mem_total_kb"], 1024 * 1024)
            self.assertTrue(nd["socket_ids_known"])
            self.assertFalse(nd["socket_ambiguous"])
            self.assertEqual(nd["socket_id"], 0 if nid < 4 else 1)
        self.assertTrue(inv["distance"]["complete"])
        self.assertEqual(inv["distance"]["nearest_intra_socket_distance"], 12)
        self.assertEqual(inv["distance"]["nearest_cross_socket_distance"], 32)

    def test_sparse_ids_and_unequal_nodes(self):
        with tempfile.TemporaryDirectory() as td:
            online = "2,5,9"
            cpu_packages = {10: 0, 11: 0, 20: 0, 30: 1, 31: 1}
            nodes = {
                2: {"cpulist": "10,11", "mem_total_kb": 100},
                5: {"cpulist": "20", "mem_total_kb": 100},
                9: {"cpulist": "30,31", "mem_total_kb": 100},
            }
            dist = {2: [10, 20, 30], 5: [20, 10, 30], 9: [30, 30, 10]}
            sysfs, proc = make_sysfs(td, online=online, nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="10,11,20,30,31", status_mems="2,5,9")
            inv = disc_topo(sysfs, proc)
        self.assertEqual(inv["online_nodes"], [2, 5, 9])
        self.assertEqual(inv["nodes"][2]["socket_id"], 0)
        self.assertEqual(inv["nodes"][5]["socket_id"], 0)
        self.assertEqual(inv["nodes"][9]["socket_id"], 1)
        self.assertEqual(inv["distance"]["ordered_node_ids"], [2, 5, 9])

    def test_offline_and_no_mem_nodes_reported(self):
        with tempfile.TemporaryDirectory() as td:
            # node 1 online but no memory; node 3 online no cpus listed
            online = "0,1,3"
            cpu_packages = {0: 0, 1: 0}
            nodes = {
                0: {"cpulist": "0,1", "mem_total_kb": 100},
                1: {"cpulist": "0", "mem_total_kb": 0},
                3: {"cpulist": "", "mem_total_kb": 100},
            }
            dist = {0: [10, 20, 20], 1: [20, 10, 20], 3: [20, 20, 10]}
            sysfs, proc = make_sysfs(td, online=online, nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0,1", status_mems="0,1,3")
            inv = disc_topo(sysfs, proc)
        self.assertEqual(inv["nodes"][1]["mem_state"], "none")
        self.assertEqual(inv["nodes"][3]["cpus"], [])
        self.assertTrue(inv["nodes"][3]["cpus_known"])
        self.assertEqual(inv["nodes"][1]["socket_id"], 0)
        self.assertIn("node3.socket", inv["unknowns"])  # empty cpulist -> socket unknown
        self.assertNotIn("node1.socket", inv["unknowns"])  # socket derivable from cpu 0 package
        self.assertNotIn("node3.cpulist", inv["unknowns"])  # known-empty cpulist

    def test_restricted_cpuset_mems(self):
        with tempfile.TemporaryDirectory() as td:
            online = "0,1"
            cpu_packages = {0: 0, 1: 1}
            nodes = {0: {"cpulist": "0", "mem_total_kb": 100}, 1: {"cpulist": "1", "mem_total_kb": 100}}
            dist = {0: [10, 20], 1: [20, 10]}
            sysfs, proc = make_sysfs(td, online=online, nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0", status_mems="0")
            inv = disc_topo(sysfs, proc)
        self.assertEqual(inv["allowed_cpus"], [0])
        self.assertEqual(inv["allowed_mem_nodes"], [0])
        self.assertEqual(inv["nodes"][1]["effective_allowed_cpus"], [])

    def test_missing_and_invalid_distance(self):
        with tempfile.TemporaryDirectory() as td:
            online = "0,1"
            cpu_packages = {0: 0, 1: 1}
            nodes = {0: {"cpulist": "0", "mem_total_kb": 100}, 1: {"cpulist": "1", "mem_total_kb": 100}}
            dist = {0: [10, 20], 1: "bad"}  # invalid
            sysfs, proc = make_sysfs(td, online=online, nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0,1", status_mems="0,1")
            inv = disc_topo(sysfs, proc)
        self.assertFalse(inv["distance"]["complete"])
        self.assertIn("distance_matrix", inv["unknowns"])
        self.assertFalse(inv["distance"]["rows"][1]["known"])

    def test_ambiguous_node_to_socket(self):
        with tempfile.TemporaryDirectory() as td:
            online = "0,1"
            # node 0 spans two packages -> ambiguous
            cpu_packages = {0: 0, 1: 1, 2: 1}
            nodes = {0: {"cpulist": "0,1", "mem_total_kb": 100}, 1: {"cpulist": "2", "mem_total_kb": 100}}
            dist = {0: [10, 20], 1: [20, 10]}
            sysfs, proc = make_sysfs(td, online=online, nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0,1,2", status_mems="0,1")
            inv = disc_topo(sysfs, proc)
        self.assertTrue(inv["nodes"][0]["socket_ambiguous"])
        self.assertIsNone(inv["nodes"][0]["socket_id"])
        self.assertIn("node0.socket", inv["unknowns"])
        self.assertEqual(inv["nodes"][1]["socket_id"], 1)


class TestMappingProfiles(unittest.TestCase):
    def _nps4_inv(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        cpu_packages = {}
        nodes = {}
        for nid in range(8):
            cpus = list(range(nid * 4, nid * 4 + 4))
            nodes[nid] = {"cpulist": ",".join(str(c) for c in cpus), "mem_total_kb": 1024 * 1024}
            pkg = 0 if nid < 4 else 1
            for c in cpus:
                cpu_packages[c] = pkg
        dist = {}
        for i in range(8):
            row = []
            for j in range(8):
                if i == j:
                    row.append(10)
                elif (i < 4) == (j < 4):
                    row.append(12)
                else:
                    row.append(32)
            dist[i] = row
        sysfs, proc = make_sysfs(td.name, online="0-7", nodes=nodes, cpu_packages=cpu_packages,
                                 node_distances=dist, status_cpus="0-31", status_mems="0-7")
        return disc_topo(sysfs, proc)

    def test_nps4_cross_socket_not_all_socket0(self):
        inv = self._nps4_inv()
        usable = list(range(8))
        variants = topology.select_mapping_profiles(inv, 4, usable, requested_profiles=["cross_socket_spread"])
        self.assertEqual(len(variants), 1)
        v = variants[0]
        self.assertTrue(v["supported"], v.get("reason"))
        phys = v["logical_to_physical"]
        self.assertEqual(len(phys), 4)
        sockets = [inv["nodes"][n]["socket_id"] for n in phys]
        self.assertEqual(len(set(sockets)), 2, "4-node cross-socket on NPS4 must span both sockets: %s" % phys)
        self.assertNotEqual(set(phys), set([0, 1, 2, 3]), "must not pick all socket-0 nodes")

    def test_nps4_cross_socket_2node(self):
        inv = self._nps4_inv()
        variants = topology.select_mapping_profiles(inv, 2, list(range(8)), requested_profiles=["cross_socket_spread"])
        self.assertTrue(variants[0]["supported"])
        phys = variants[0]["logical_to_physical"]
        sockets = {inv["nodes"][n]["socket_id"] for n in phys}
        self.assertEqual(sockets, {0, 1})

    def test_nps4_intra_socket_variants(self):
        inv = self._nps4_inv()
        variants = topology.select_mapping_profiles(inv, 4, list(range(8)), requested_profiles=["intra_socket"])
        supported = [v for v in variants if v["supported"]]
        self.assertEqual(len(supported), 2)
        sock_sets = [set(v["logical_to_physical"]) for v in supported]
        self.assertIn(set([0, 1, 2, 3]), sock_sets)
        self.assertIn(set([4, 5, 6, 7]), sock_sets)
        for v in supported:
            sockets = {inv["nodes"][n]["socket_id"] for n in v["logical_to_physical"]}
            self.assertEqual(len(sockets), 1)

    def test_nps4_all_nodes_8(self):
        inv = self._nps4_inv()
        variants = topology.select_mapping_profiles(inv, 8, list(range(8)), requested_profiles=["all_nodes"])
        self.assertTrue(variants[0]["supported"])
        self.assertEqual(variants[0]["logical_to_physical"], list(range(8)))

    def test_nps1_no_unsupported_4_or_8(self):
        with tempfile.TemporaryDirectory() as td:
            cpu_packages = {0: 0, 1: 0, 2: 1, 3: 1}
            nodes = {0: {"cpulist": "0,1", "mem_total_kb": 100}, 1: {"cpulist": "2,3", "mem_total_kb": 100}}
            dist = {0: [10, 32], 1: [32, 10]}
            sysfs, proc = make_sysfs(td, online="0,1", nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0-3", status_mems="0,1")
            inv = disc_topo(sysfs, proc)
        usable = [0, 1]
        for count in (4, 8):
            for prof in ("cross_socket_spread", "intra_socket", "all_nodes"):
                variants = topology.select_mapping_profiles(inv, count, usable, requested_profiles=[prof])
                self.assertTrue(all(not v["supported"] for v in variants),
                                "NPS1 must not support %s for %d nodes: %s" % (prof, count, variants))
                self.assertTrue(any(v.get("reason") for v in variants))
        # 2-node cross-socket is supported
        v2 = topology.select_mapping_profiles(inv, 2, usable, requested_profiles=["cross_socket_spread"])
        self.assertTrue(v2[0]["supported"])

    def test_nps2_cases(self):
        with tempfile.TemporaryDirectory() as td:
            cpu_packages = {0: 0, 1: 0, 2: 0, 3: 0, 4: 1, 5: 1, 6: 1, 7: 1}
            nodes = {}
            for nid in range(4):
                cpus = list(range(nid * 2, nid * 2 + 2))
                nodes[nid] = {"cpulist": ",".join(str(c) for c in cpus), "mem_total_kb": 100}
                pkg = 0 if nid < 2 else 1
                for c in cpus:
                    cpu_packages[c] = pkg
            dist = {}
            for i in range(4):
                row = []
                for j in range(4):
                    if i == j:
                        row.append(10)
                    elif (i < 2) == (j < 2):
                        row.append(16)
                    else:
                        row.append(32)
                dist[i] = row
            sysfs, proc = make_sysfs(td, online="0-3", nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0-7", status_mems="0-3")
            inv = disc_topo(sysfs, proc)
        usable = [0, 1, 2, 3]
        # 2-node intra-socket supported (each socket has 2)
        intra2 = topology.select_mapping_profiles(inv, 2, usable, requested_profiles=["intra_socket"])
        self.assertEqual(len([v for v in intra2 if v["supported"]]), 2)
        # 2-node cross-socket
        cross2 = topology.select_mapping_profiles(inv, 2, usable, requested_profiles=["cross_socket_spread"])
        self.assertTrue(cross2[0]["supported"])
        self.assertEqual(len({inv["nodes"][n]["socket_id"] for n in cross2[0]["logical_to_physical"]}), 2)
        # 4-node all-node spans both sockets
        all4 = topology.select_mapping_profiles(inv, 4, usable, requested_profiles=["all_nodes"])
        self.assertTrue(all4[0]["supported"])
        self.assertEqual(set(all4[0]["logical_to_physical"]), {0, 1, 2, 3})

    def test_single_socket_multi_numa_cross_socket_unsupported(self):
        # 4 NUMA nodes, all on the same physical socket/package.
        with tempfile.TemporaryDirectory() as td:
            cpu_packages = {}
            nodes = {}
            for nid in range(4):
                cpus = [nid * 2, nid * 2 + 1]
                nodes[nid] = {"cpulist": ",".join(str(c) for c in cpus), "mem_total_kb": 1024}
                for c in cpus:
                    cpu_packages[c] = 0  # single socket
            dist = {i: [10 if i == j else 12 for j in range(4)] for i in range(4)}
            sysfs, proc = make_sysfs(td, online="0-3", nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0-7", status_mems="0-3")
            inv = disc_topo(sysfs, proc)
        variants = topology.select_mapping_profiles(inv, 2, [0, 1, 2, 3], requested_profiles=["cross_socket_spread"])
        self.assertEqual(len(variants), 1)
        v = variants[0]
        self.assertFalse(v["supported"])
        self.assertIsNotNone(v.get("reason"))
        self.assertIn("socket", (v.get("reason") or "").lower())
        self.assertNotEqual(v.get("spans_sockets"), True)

    def test_fake_numa_several_nodes_one_physical_socket_unsupported(self):
        # Fake/logical NUMA partitioning: several nodes presented, one physical socket.
        with tempfile.TemporaryDirectory() as td:
            cpu_packages = {0: 3, 1: 3, 2: 3, 3: 3, 4: 3, 5: 3}
            nodes = {
                0: {"cpulist": "0,1", "mem_total_kb": 512},
                1: {"cpulist": "2,3", "mem_total_kb": 512},
                2: {"cpulist": "4,5", "mem_total_kb": 512},
            }
            dist = {0: [10, 10, 10], 1: [10, 10, 10], 2: [10, 10, 10]}
            sysfs, proc = make_sysfs(td, online="0-2", nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0-5", status_mems="0-2")
            inv = disc_topo(sysfs, proc)
        for count in (2, 3):
            variants = topology.select_mapping_profiles(inv, count, [0, 1, 2], requested_profiles=["cross_socket_spread"])
            v = variants[0]
            self.assertFalse(v["supported"], (count, v))
            self.assertIsNotNone(v.get("reason"))
            self.assertNotEqual(v.get("spans_sockets"), True)

    def test_cross_socket_spread_requires_more_than_one_logical_node(self):
        with tempfile.TemporaryDirectory() as td:
            cpu_packages = {0: 0, 1: 1}
            nodes = {0: {"cpulist": "0", "mem_total_kb": 100}, 1: {"cpulist": "1", "mem_total_kb": 100}}
            dist = {0: [10, 20], 1: [20, 10]}
            sysfs, proc = make_sysfs(td, online="0,1", nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0,1", status_mems="0,1")
            inv = disc_topo(sysfs, proc)
        variants = topology.select_mapping_profiles(inv, 1, [0, 1], requested_profiles=["cross_socket_spread"])
        self.assertFalse(variants[0]["supported"])
        self.assertIsNotNone(variants[0].get("reason"))

    def test_nps1_two_node_cross_socket_supported_and_spans(self):
        with tempfile.TemporaryDirectory() as td:
            cpu_packages = {0: 0, 1: 0, 2: 1, 3: 1}
            nodes = {0: {"cpulist": "0,1", "mem_total_kb": 100}, 1: {"cpulist": "2,3", "mem_total_kb": 100}}
            dist = {0: [10, 32], 1: [32, 10]}
            sysfs, proc = make_sysfs(td, online="0,1", nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0-3", status_mems="0,1")
            inv = disc_topo(sysfs, proc)
        variants = topology.select_mapping_profiles(inv, 2, [0, 1], requested_profiles=["cross_socket_spread"])
        v = variants[0]
        self.assertTrue(v["supported"], v.get("reason"))
        self.assertEqual(set(v["logical_to_physical"]), {0, 1})
        self.assertIs(v.get("spans_sockets"), True)
        self.assertEqual(len({inv["nodes"][n]["socket_id"] for n in v["logical_to_physical"]}), 2)

    def test_nps4_four_node_cross_socket_supported_and_spans_both_sockets(self):
        inv = self._nps4_inv()
        usable = list(range(8))
        variants = topology.select_mapping_profiles(inv, 4, usable, requested_profiles=["cross_socket_spread"])
        self.assertEqual(len(variants), 1)
        v = variants[0]
        self.assertTrue(v["supported"], v.get("reason"))
        phys = v["logical_to_physical"]
        self.assertEqual(len(phys), 4)
        sockets = {inv["nodes"][n]["socket_id"] for n in phys}
        self.assertEqual(sockets, {0, 1}, phys)
        self.assertIs(v.get("spans_sockets"), True)

    def test_unknown_or_ambiguous_socket_membership_never_supports_cross_socket(self):
        # Ambiguous: node spans two packages.
        with tempfile.TemporaryDirectory() as td:
            cpu_packages = {0: 0, 1: 1, 2: 1}
            nodes = {0: {"cpulist": "0,1", "mem_total_kb": 100}, 1: {"cpulist": "2", "mem_total_kb": 100}}
            dist = {0: [10, 20], 1: [20, 10]}
            sysfs, proc = make_sysfs(td, online="0,1", nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0-2", status_mems="0,1")
            inv = disc_topo(sysfs, proc)
        variants = topology.select_mapping_profiles(inv, 2, [0, 1], requested_profiles=["cross_socket_spread"])
        v = variants[0]
        self.assertFalse(v["supported"])
        self.assertNotEqual(v.get("spans_sockets"), True)

        # Unknown: missing cpu package info / empty cpulist on a node.
        with tempfile.TemporaryDirectory() as td:
            cpu_packages = {0: 0}
            nodes = {0: {"cpulist": "0", "mem_total_kb": 100}, 1: {"cpulist": "", "mem_total_kb": 100}}
            dist = {0: [10, 20], 1: [20, 10]}
            sysfs, proc = make_sysfs(td, online="0,1", nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0", status_mems="0,1")
            inv = disc_topo(sysfs, proc)
        variants = topology.select_mapping_profiles(inv, 2, [0, 1], requested_profiles=["cross_socket_spread"])
        v = variants[0]
        self.assertFalse(v["supported"])
        self.assertNotEqual(v.get("spans_sockets"), True)


class TestResolveMappingPlan(unittest.TestCase):
    def test_validates_concrete_mapping_via_resolve_topology(self):
        with tempfile.TemporaryDirectory() as td:
            cpu_packages = {0: 0, 1: 0, 2: 1, 3: 1}
            nodes = {0: {"cpulist": "0", "mem_total_kb": 100}, 1: {"cpulist": "2", "mem_total_kb": 100}}
            dist = {0: [10, 32], 1: [32, 10]}
            sysfs, proc = make_sysfs(td, online="0,1", nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0,2", status_mems="0,1")
            variants, inv, errs = resolve_plan(
                2, profiles=["cross_socket_spread"], sysfs_root=sysfs, proc_root=proc)
        self.assertEqual(errs, [])
        supported = [v for v in variants if v.get("supported")]
        self.assertEqual(len(supported), 1)
        self.assertEqual(set(supported[0]["logical_to_physical"]), {0, 1})
        prov = supported[0].get("mapping_provenance") or {}
        self.assertEqual(prov.get("mapping_profile"), "cross_socket_spread")
        self.assertIn("pairwise_numa_distances", prov)

    def test_resolve_mapping_plan_uses_injected_affinity_fixture_not_host(self):
        # Synthetic cross-socket topology; success/failure must follow the injected
        # affinity/topology fixture regardless of actual host CPU affinity. The same
        # fixture inputs must govern inventory discovery, usable-node determination,
        # mapping selection, and final concrete mapping validation.
        with tempfile.TemporaryDirectory() as td:
            cpu_packages = {0: 0, 1: 0, 2: 1, 3: 1}
            nodes = {
                0: {"cpulist": "0,1", "mem_total_kb": 1024},
                1: {"cpulist": "2,3", "mem_total_kb": 1024},
            }
            dist = {0: [10, 32], 1: [32, 10]}
            sysfs, proc = make_sysfs(td, online="0,1", nodes=nodes, cpu_packages=cpu_packages,
                                     node_distances=dist, status_cpus="0-3", status_mems="0,1")

            def allow_all(_pid=0):
                return {0, 1, 2, 3}

            def allow_none_on_nodes(_pid=0):
                # Restrictive affinity excludes every node CPU in the fixture.
                return {99}

            variants_ok, _inv_ok, errs_ok = run_dist.resolve_mapping_plan(
                2, profiles=["cross_socket_spread"], no_pin=False,
                sysfs_root=sysfs, proc_root=proc, sched_getaffinity=allow_all)
            self.assertEqual(errs_ok, [], errs_ok)
            self.assertTrue(variants_ok and variants_ok[0].get("supported"), variants_ok)
            self.assertEqual(variants_ok[0].get("logical_to_physical"), [0, 1])
            prov = variants_ok[0].get("mapping_provenance") or {}
            self.assertTrue(prov)

            variants_bad, _inv_bad, _errs_bad = run_dist.resolve_mapping_plan(
                2, profiles=["cross_socket_spread"], no_pin=False,
                sysfs_root=sysfs, proc_root=proc, sched_getaffinity=allow_none_on_nodes)
            # Same topology fixture, different injected affinity => cannot establish a
            # supported/validated concrete mapping (no allowed CPUs on nodes), independent of host.
            self.assertTrue(variants_bad)
            self.assertFalse(variants_bad[0].get("supported"), variants_bad)
            self.assertIsNotNone(variants_bad[0].get("reason"))


if __name__ == "__main__":
    unittest.main()
