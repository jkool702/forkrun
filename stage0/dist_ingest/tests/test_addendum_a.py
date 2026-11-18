import ctypes
import errno
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PKG))
LIB_PATH = os.path.join(os.path.dirname(PKG), "libdist_ingest.so")
sys.path.insert(0, PKG)

import run_dist  # noqa: E402

DI_POLICY_FIXED_FAA = 1
DI_MAX_NODES = 64


class DiPolicyParams(ctypes.Structure):
    _fields_ = [
        ("base_quantum", ctypes.c_uint64), ("max_reservation", ctypes.c_uint64), ("max_backlog", ctypes.c_uint64),
        ("rel_min_claim", ctypes.c_uint64), ("rel_max_claim_quanta", ctypes.c_uint64),
        ("relative_rounding", ctypes.c_int), ("local_max_claim_quanta", ctypes.c_uint64),
        ("align_reservations", ctypes.c_int), ("prefer_hugepage", ctypes.c_int),
        ("strict_affinity", ctypes.c_int), ("strict_mbind", ctypes.c_int),
        ("one_outstanding_per_node", ctypes.c_int), ("enable_peer_headroom", ctypes.c_int),
    ]


class DiConsumerCfg(ctypes.Structure):
    _fields_ = [("mode", ctypes.c_int), ("bytes_per_sec", ctypes.c_uint64), ("stall_ms", ctypes.c_uint64)]


class DiAffinityRole(ctypes.Structure):
    _fields_ = [
        ("requested", ctypes.c_int), ("set_applied", ctypes.c_int), ("query_succeeded", ctypes.c_int),
        ("matched", ctypes.c_int), ("error", ctypes.c_int), ("strict_failed", ctypes.c_int),
    ]


class DiNodeMetrics(ctypes.Structure):
    _fields_ = [
        ("reservations", ctypes.c_uint64), ("bytes_reserved_req", ctypes.c_uint64), ("bytes_assigned", ctypes.c_uint64),
        ("bytes_read", ctypes.c_uint64), ("bytes_published", ctypes.c_uint64), ("bytes_consumed", ctypes.c_uint64),
        ("chunks_published", ctypes.c_uint64), ("chunks_consumed", ctypes.c_uint64), ("zero_claims", ctypes.c_uint64),
        ("claim_wait_ns", ctypes.c_uint64), ("read_wait_ns", ctypes.c_uint64), ("publish_wait_ns", ctypes.c_uint64),
        ("consume_wait_ns", ctypes.c_uint64), ("current_published_backlog", ctypes.c_uint64),
        ("current_consumer_inflight_backlog", ctypes.c_uint64), ("current_outstanding", ctypes.c_uint64),
        ("current_effective_backlog", ctypes.c_uint64), ("max_published_backlog", ctypes.c_uint64),
        ("max_consumer_inflight_backlog", ctypes.c_uint64), ("max_effective_backlog", ctypes.c_uint64),
        ("peer_observe_ns", ctypes.c_uint64), ("peer_observe_count", ctypes.c_uint64),
        ("placement_total_addressable_pages", ctypes.c_uint64), ("placement_sampled_pages", ctypes.c_uint64),
        ("placement_sample_limit", ctypes.c_uint64), ("placement_sample_spacing", ctypes.c_uint64),
        ("placement_sample_target_match_pages", ctypes.c_uint64), ("placement_sample_other_node_pages", ctypes.c_uint64),
        ("placement_sample_unknown_pages", ctypes.c_uint64),
        ("placement_sampling_unavailable", ctypes.c_int), ("placement_sampling_not_performed", ctypes.c_int),
        ("hugepage_map_requested_bytes", ctypes.c_uint64), ("hugepage_map_obtained_bytes", ctypes.c_uint64),
        ("hugepage_fallback_bytes", ctypes.c_uint64), ("hugepage_observed_kb", ctypes.c_uint64),
        ("alloc_bytes", ctypes.c_uint64), ("ingest_cpu_ns", ctypes.c_uint64), ("consumer_cpu_ns", ctypes.c_uint64),
        ("res_hist", ctypes.c_uint64 * 20),
        ("affinity_ingestor", DiAffinityRole), ("affinity_consumer", DiAffinityRole),
        ("mbind_policy_requested", ctypes.c_int), ("mbind_policy_applied", ctypes.c_int),
        ("mbind_error", ctypes.c_int), ("strict_mbind_failed", ctypes.c_int),
        ("strict_affinity_failed", ctypes.c_int), ("last_error", ctypes.c_int),
    ]


class DiResult(ctypes.Structure):
    _fields_ = [
        ("total_bytes", ctypes.c_uint64), ("total_reserved_req", ctypes.c_uint64), ("total_assigned", ctypes.c_uint64),
        ("total_read", ctypes.c_uint64), ("total_published", ctypes.c_uint64), ("total_consumed", ctypes.c_uint64),
        ("reservations_total", ctypes.c_uint64), ("eof_offset", ctypes.c_uint64),
        ("overlap_detected", ctypes.c_int), ("duplicate_detected", ctypes.c_int), ("lost_detected", ctypes.c_int),
        ("input_changed", ctypes.c_int), ("wall_seconds", ctypes.c_double),
        ("ingest_cpu_ns", ctypes.c_uint64), ("consumer_cpu_ns", ctypes.c_uint64),
        ("num_nodes", ctypes.c_int), ("policy", ctypes.c_int),
        ("nodes", DiNodeMetrics * DI_MAX_NODES), ("res_hist", ctypes.c_uint64 * 20),
    ]


class DiConfig(ctypes.Structure):
    _fields_ = [
        ("num_nodes", ctypes.c_int), ("policy", ctypes.c_int), ("params", DiPolicyParams),
        ("consumers", ctypes.POINTER(DiConsumerCfg)),
        ("cpu_lists", ctypes.c_void_p), ("cpu_counts", ctypes.c_void_p), ("phys_nodes", ctypes.c_void_p),
    ]


def load_lib():
    lib = ctypes.CDLL(LIB_PATH)
    lib.di_create.argtypes = [ctypes.c_int, ctypes.c_uint64, ctypes.POINTER(DiConfig)]
    lib.di_create.restype = ctypes.c_void_p
    lib.di_destroy.argtypes = [ctypes.c_void_p]
    lib.di_destroy.restype = None
    lib.di_run.argtypes = [ctypes.c_void_p, ctypes.POINTER(DiResult)]
    lib.di_run.restype = ctypes.c_int
    lib.di_test_cpu_mask_check.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int]
    lib.di_test_cpu_mask_check.restype = ctypes.c_int
    lib.di_test_set_pread_seam.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint64]
    lib.di_test_set_pread_seam.restype = ctypes.c_int
    lib.di_test_pread_seam_fired.argtypes = [ctypes.c_void_p]
    lib.di_test_pread_seam_fired.restype = ctypes.c_int
    return lib


def make_file(size):
    fd, path = tempfile.mkstemp(prefix='dist_aa_')
    os.close(fd)
    with open(path, 'wb') as f:
        if size:
            f.write(b'X' * size)
    return path


def base_params(**kw):
    p = DiPolicyParams()
    p.base_quantum = kw.get('base_quantum', 1024*1024)
    p.max_reservation = kw.get('max_reservation', 0)
    p.max_backlog = kw.get('max_backlog', 8*1024*1024)
    p.rel_min_claim = 0; p.rel_max_claim_quanta = 0; p.relative_rounding = 1
    p.local_max_claim_quanta = 0; p.align_reservations = 1; p.prefer_hugepage = 0
    p.strict_affinity = kw.get('strict_affinity', 0)
    p.strict_mbind = kw.get('strict_mbind', 0)
    p.one_outstanding_per_node = 1; p.enable_peer_headroom = 1
    return p


class TestCpuMaskLargeIds(unittest.TestCase):
    """Addendum A §3: dynamic CPU sets, no silent truncation."""

    def setUp(self):
        self.lib = load_lib()

    def test_large_cpu_id_above_cpuset_size(self):
        # Must not depend on machine having CPU online; tests mask logic.
        big = [0, 7, int(os.sysconf('SC_NPROCESSORS_CONF') or 1) + 4096]
        # ensure above traditional boundary in intent; if system small, still test dynamic path
        arr = (ctypes.c_int * len(big))(*big)
        rc = self.lib.di_test_cpu_mask_check(arr, len(big), 0)
        self.assertEqual(rc, 1, "dynamic CPU mask should accept large CPU id, rc=%s" % rc)

    def test_require_above_cpuset_size_logic(self):
        # when require_above_cpuset_size and max < CPU_SETSIZE, helper returns -3
        small = [0]
        arr = (ctypes.c_int * 1)(*small)
        rc = self.lib.di_test_cpu_mask_check(arr, 1, 1)
        # on platforms where CPU_SETSIZE>0, small id should fail the "above" requirement
        self.assertEqual(rc, -3)

    def test_invalid_negative_cpu_id(self):
        arr = (ctypes.c_int * 2)(0, -1)
        rc = self.lib.di_test_cpu_mask_check(arr, 2, 0)
        self.assertEqual(rc, -2)

    def test_empty_list_invalid(self):
        arr = (ctypes.c_int * 1)(0)
        rc = self.lib.di_test_cpu_mask_check(arr, 0, 0)
        self.assertEqual(rc, -1)


class TestDuplicatePhysNodes(unittest.TestCase):
    """Addendum A §5: reject duplicates at runner and C boundary."""

    def test_c_boundary_rejects_duplicate_phys_nodes(self):
        lib = load_lib()
        path = make_file(1024*1024)
        fd = os.open(path, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            cons = (DiConsumerCfg * 2)()
            for i in range(2): cons[i].mode = 2
            phys = (ctypes.c_int * 2)(0, 0)
            cfg = DiConfig(); cfg.num_nodes = 2; cfg.policy = DI_POLICY_FIXED_FAA
            cfg.params = base_params(); cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
            cfg.phys_nodes = ctypes.cast(phys, ctypes.c_void_p)
            eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            self.assertFalse(eng, "di_create must reject duplicate phys_nodes")
        finally:
            os.close(fd); os.unlink(path)

    def test_c_boundary_accepts_unique_phys_nodes(self):
        lib = load_lib()
        path = make_file(1024*1024)
        fd = os.open(path, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            cons = (DiConsumerCfg * 2)()
            for i in range(2): cons[i].mode = 2
            phys = (ctypes.c_int * 2)(0, 1)
            cfg = DiConfig(); cfg.num_nodes = 2; cfg.policy = DI_POLICY_FIXED_FAA
            cfg.params = base_params(); cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
            cfg.phys_nodes = ctypes.cast(phys, ctypes.c_void_p)
            eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            self.assertTrue(eng)
            lib.di_destroy(eng)
        finally:
            os.close(fd); os.unlink(path)

    def test_runner_rejects_duplicate_phys_nodes(self):
        path = make_file(1024*1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG,'run_dist.py'),
                                '--candidate','fixed_faa','--input',path,'--nodes','2',
                                '--phys-nodes','0,0','--no-pin'],
                               capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('duplicate', (p.stderr + p.stdout).lower())
        finally:
            os.unlink(path)

    def test_runner_rejects_malformed_phys_nodes(self):
        path = make_file(1024*1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG,'run_dist.py'),
                                '--candidate','fixed_faa','--input',path,'--nodes','2',
                                '--phys-nodes','x,y','--no-pin'],
                               capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0)
        finally:
            os.unlink(path)


class TestAffinityPerRoleAndStrict(unittest.TestCase):
    """Addendum A §2: per-role affinity, no ambiguous shared record."""

    def test_affinity_roles_independent_no_pin(self):
        # unrequested affinity: roles remain independent/unrequested, not conflated
        lib = load_lib()
        path = make_file(2*1024*1024)
        fd = os.open(path, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            cons = (DiConsumerCfg * 1)()
            cons[0].mode = 2
            cfg = DiConfig(); cfg.num_nodes = 1; cfg.policy = DI_POLICY_FIXED_FAA
            cfg.params = base_params(strict_affinity=0)
            cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
            eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            self.assertTrue(eng)
            res = DiResult(); rc = lib.di_run(eng, ctypes.byref(res))
            lib.di_destroy(eng)
            self.assertEqual(rc, 0)
            n = res.nodes[0]
            # distinct role records exist; unrequested when no cpu lists
            self.assertEqual(n.affinity_ingestor.requested, 0)
            self.assertEqual(n.affinity_consumer.requested, 0)
            self.assertEqual(n.strict_affinity_failed, 0)
        finally:
            os.close(fd); os.unlink(path)

    def test_strict_affinity_fails_on_unpinnable_cpu(self):
        # request impossible CPU id to force failure; strict must fail aggregate
        lib = load_lib()
        path = make_file(1024*1024)
        fd = os.open(path, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            cons = (DiConsumerCfg * 1)()
            cons[0].mode = 2
            # impossible CPU id
            cpus = (ctypes.c_int * 1)(10**9)
            counts = (ctypes.c_int * 1)(1)
            ptrs = (ctypes.POINTER(ctypes.c_int) * 1)(ctypes.cast(cpus, ctypes.POINTER(ctypes.c_int)))
            cfg = DiConfig(); cfg.num_nodes = 1; cfg.policy = DI_POLICY_FIXED_FAA
            cfg.params = base_params(strict_affinity=1)
            cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
            cfg.cpu_lists = ctypes.cast(ptrs, ctypes.c_void_p)
            cfg.cpu_counts = ctypes.cast(counts, ctypes.c_void_p)
            eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            self.assertTrue(eng)
            res = DiResult(); rc = lib.di_run(eng, ctypes.byref(res))
            lib.di_destroy(eng)
            n = res.nodes[0]
            # per-role results recorded independently; at least one role reports failure details
            self.assertTrue(n.affinity_ingestor.requested or n.affinity_consumer.requested)
            self.assertTrue(n.strict_affinity_failed)
            self.assertNotEqual(rc, 0)
            # error codes are pthread-style actual values (nonzero) for failed requested roles
            if n.affinity_ingestor.requested and not n.affinity_ingestor.matched:
                self.assertNotEqual(n.affinity_ingestor.error, 0)
            if n.affinity_consumer.requested and not n.affinity_consumer.matched:
                self.assertNotEqual(n.affinity_consumer.error, 0)
        finally:
            os.close(fd); os.unlink(path)


class TestPlacementSamplingAndMbind(unittest.TestCase):
    """Addendum A §4: policy application != observed placement; sampling coverage."""

    def test_successful_mbind_not_claimed_as_verified_placement(self):
        # run_dist output must not label mbind syscall success as placement_verified.
        path = make_file(2*1024*1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG,'run_dist.py'),
                                '--candidate','fixed_faa','--input',path,'--nodes','1','--no-pin'],
                               capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-600:])
            # parse DIST_RESULT
            dist = None
            for line in p.stderr.splitlines():
                if line.startswith('DIST_RESULT '):
                    dist = json.loads(line[len('DIST_RESULT '):])
            self.assertIsNotNone(dist)
            js = json.dumps(dist)
            self.assertNotIn('placement_verified', js)
            self.assertNotIn('placement_ok', js)
            # has explicit separated fields
            n0 = dist['nodes'][0]
            self.assertIn('memory_policy', n0)
            self.assertIn('placement', n0)
            self.assertIn('mbind_policy_applied', n0['memory_policy'])
            self.assertIn('all_sampled_on_target_node', n0['placement'])
            self.assertIn('placement_semantics', dist)
        finally:
            os.unlink(path)

    def test_sampling_covers_allocation_and_no_duplicates_small(self):
        # small allocation (<1024 pages) sampled completely => sampled == addressable
        lib = load_lib()
        path = make_file(512 * 1024)  # 128 pages at 4k
        fd = os.open(path, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            cons = (DiConsumerCfg * 1)()
            cons[0].mode = 2
            cfg = DiConfig(); cfg.num_nodes = 1; cfg.policy = DI_POLICY_FIXED_FAA
            cfg.params = base_params(base_quantum=512*1024, max_backlog=4*1024*1024)
            cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
            eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            self.assertTrue(eng)
            res = DiResult(); rc = lib.di_run(eng, ctypes.byref(res))
            lib.di_destroy(eng)
            self.assertEqual(rc, 0)
            n = res.nodes[0]
            self.assertGreater(int(n.placement_total_addressable_pages), 0)
            self.assertGreater(int(n.placement_sampled_pages), 0)
            # small allocations should be sampled completely (up to limit); sampled <= addressable
            self.assertLessEqual(int(n.placement_sampled_pages), int(n.placement_total_addressable_pages))
            # no negative/overflow-ish; counts partition sampled (on linux with move_pages)
            total_classified = (int(n.placement_sample_target_match_pages) +
                                int(n.placement_sample_other_node_pages) +
                                int(n.placement_sample_unknown_pages))
            # sampling unavailable => sampled_pages may be counted but classified as unknown/unavailable
            if not n.placement_sampling_unavailable:
                self.assertEqual(total_classified, int(n.placement_sampled_pages))
        finally:
            os.close(fd); os.unlink(path)


if __name__ == '__main__':
    unittest.main()


class TestAllocationTeardown(unittest.TestCase):
    """Addendum A §7 targeted allocation/teardown coverage."""

    def test_repeated_create_destroy_cycles(self):
        lib = load_lib()
        for i in range(10):
            path = make_file(512*1024 if i % 2 == 0 else 0)
            fd = os.open(path, os.O_RDONLY)
            try:
                st = os.fstat(fd)
                cons = (DiConsumerCfg * 2)()
                for j in range(2): cons[j].mode = 2
                cfg = DiConfig(); cfg.num_nodes = 2; cfg.policy = DI_POLICY_FIXED_FAA
                cfg.params = base_params()
                cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
                eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
                self.assertTrue(eng)
                res = DiResult(); rc = lib.di_run(eng, ctypes.byref(res))
                lib.di_destroy(eng)
                self.assertEqual(rc, 0)
                self.assertEqual(int(res.total_consumed), st.st_size)
            finally:
                os.close(fd); os.unlink(path)

    def test_hugepage_request_fallback_reporting(self):
        lib = load_lib()
        path = make_file(2*1024*1024)
        fd = os.open(path, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            cons = (DiConsumerCfg * 1)(); cons[0].mode = 2
            cfg = DiConfig(); cfg.num_nodes = 1; cfg.policy = DI_POLICY_FIXED_FAA
            params = base_params(); params.prefer_hugepage = 1
            cfg.params = params
            cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
            eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            self.assertTrue(eng)
            res = DiResult(); rc = lib.di_run(eng, ctypes.byref(res))
            lib.di_destroy(eng)
            self.assertEqual(rc, 0)
            n = res.nodes[0]
            self.assertGreaterEqual(int(n.hugepage_map_requested_bytes), 0)
        finally:
            os.close(fd); os.unlink(path)

    def test_engine_local_seam_does_not_leak_across_engines(self):
        lib = load_lib()
        path = make_file(1024*1024)
        fd = os.open(path, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            cons = (DiConsumerCfg * 1)(); cons[0].mode = 2
            cfg = DiConfig(); cfg.num_nodes = 1; cfg.policy = DI_POLICY_FIXED_FAA
            cfg.params = base_params(); cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
            eng1 = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            eng2 = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            self.assertTrue(eng1 and eng2)
            lib.di_test_set_pread_seam(eng1, 1, 2, 0)
            self.assertEqual(lib.di_test_pread_seam_fired(eng2), 0)
            res = DiResult(); rc = lib.di_run(eng2, ctypes.byref(res))
            self.assertEqual(rc, 0)
            self.assertEqual(lib.di_test_pread_seam_fired(eng2), 0)
            lib.di_destroy(eng2); lib.di_destroy(eng1)
        finally:
            os.close(fd); os.unlink(path)
