import ctypes
import os
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PKG))
LIB_PATH = os.path.join(os.path.dirname(PKG), "libdist_ingest.so")

DI_POLICY_FIXED_FAA = 1
DI_MAX_NODES = 64


class DiPolicyParams(ctypes.Structure):
    _fields_ = [
        ("base_quantum", ctypes.c_uint64),
        ("max_reservation", ctypes.c_uint64),
        ("max_backlog", ctypes.c_uint64),
        ("rel_min_claim", ctypes.c_uint64),
        ("rel_max_claim_quanta", ctypes.c_uint64),
        ("relative_rounding", ctypes.c_int),
        ("local_max_claim_quanta", ctypes.c_uint64),
        ("align_reservations", ctypes.c_int),
        ("prefer_hugepage", ctypes.c_int),
        ("strict_affinity", ctypes.c_int),
        ("strict_mbind", ctypes.c_int),
        ("one_outstanding_per_node", ctypes.c_int),
        ("enable_peer_headroom", ctypes.c_int),
        ("consumer_kernel", ctypes.c_int),
        ("placement_sampling", ctypes.c_int), ("invariant_asserts", ctypes.c_int),
    ]


class DiConsumerCfg(ctypes.Structure):
    _fields_ = [("mode", ctypes.c_int), ("bytes_per_sec", ctypes.c_uint64), ("stall_ms", ctypes.c_uint64)]


class DiAffinityRole(ctypes.Structure):
    _fields_ = [
        ("requested", ctypes.c_int),
        ("set_applied", ctypes.c_int),
        ("query_succeeded", ctypes.c_int),
        ("matched", ctypes.c_int),
        ("error", ctypes.c_int),
        ("strict_failed", ctypes.c_int),
    ]


class DiNodeMetrics(ctypes.Structure):
    _fields_ = [
        ("reservations", ctypes.c_uint64), ("bytes_reserved_req", ctypes.c_uint64), ("bytes_assigned", ctypes.c_uint64),
        ("bytes_read", ctypes.c_uint64), ("bytes_published", ctypes.c_uint64), ("bytes_consumed", ctypes.c_uint64),
        ("consumer_bytes_scanned", ctypes.c_uint64),
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
        # §5.2: ingestor workload control evidence (observed, per node).
        ("ingestor_mode", ctypes.c_int),
        ("ingestor_delay_ns", ctypes.c_uint64),
        ("ingestor_stall_fired", ctypes.c_uint64),
        ("ingestor_rate_throttled_ns", ctypes.c_uint64),
        ("mbind_policy_requested", ctypes.c_int), ("mbind_policy_applied", ctypes.c_int),
        ("mbind_error", ctypes.c_int), ("mbind_requested_count", ctypes.c_uint64), ("mbind_success_count", ctypes.c_uint64), ("mbind_failure_count", ctypes.c_uint64), ("strict_mbind_failed", ctypes.c_int),
        ("strict_affinity_failed", ctypes.c_int), ("last_error", ctypes.c_int),
    ]


class DiResult(ctypes.Structure):
    _fields_ = [
        ("total_bytes", ctypes.c_uint64), ("total_reserved_req", ctypes.c_uint64), ("total_assigned", ctypes.c_uint64),
        ("total_read", ctypes.c_uint64), ("total_published", ctypes.c_uint64), ("total_consumed", ctypes.c_uint64),
        ("total_consumer_bytes_scanned", ctypes.c_uint64),
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
        ("ingestors", ctypes.c_void_p),
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
    lib.di_debug_node_accounting.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                             ctypes.POINTER(ctypes.c_uint64),
                                             ctypes.POINTER(ctypes.c_uint64),
                                             ctypes.POINTER(ctypes.c_uint64),
                                             ctypes.POINTER(ctypes.c_uint64)]
    lib.di_debug_node_accounting.restype = ctypes.c_int
    lib.di_effective_backlog.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
    lib.di_effective_backlog.restype = ctypes.c_uint64
    return lib


def make_file(size):
    fd, path = tempfile.mkstemp(prefix='dist_s2_')
    os.close(fd)
    with open(path, 'wb') as f:
        if size:
            f.write(b'A' * size)
    return path


class TestEffectiveBacklogLifecycle(unittest.TestCase):
    def test_consumer_inflight_counts_in_effective_backlog(self):
        lib = load_lib()
        quantum = 1024 * 1024
        path = make_file(3 * quantum)
        fd = os.open(path, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            params = DiPolicyParams()
            params.base_quantum = quantum
            params.max_reservation = 0
            params.max_backlog = 2 * quantum
            params.relative_rounding = 1
            params.local_max_claim_quanta = 0
            params.align_reservations = 1
            params.prefer_hugepage = 0
            params.strict_affinity = 0
            params.strict_mbind = 0
            params.one_outstanding_per_node = 1
            params.enable_peer_headroom = 1
            cons = (DiConsumerCfg * 1)()
            cons[0].mode = 1
            cons[0].bytes_per_sec = 2 * 1024 * 1024
            cons[0].stall_ms = 0
            cfg = DiConfig()
            cfg.num_nodes = 1
            cfg.policy = DI_POLICY_FIXED_FAA
            cfg.params = params
            cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
            cfg.cpu_lists = None; cfg.cpu_counts = None; cfg.phys_nodes = None
            eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            self.assertTrue(eng)
            res = DiResult()
            seen_inflight = {'v': False}
            max_eff_seen = {'v': 0}

            def runner():
                lib.di_run(eng, ctypes.byref(res))

            t = threading.Thread(target=runner)
            t.start()
            deadline = time.time() + 5.0
            p = ctypes.c_uint64(); inf = ctypes.c_uint64(); o = ctypes.c_uint64(); e = ctypes.c_uint64()
            while t.is_alive() and time.time() < deadline:
                if lib.di_debug_node_accounting(eng, 0, ctypes.byref(p), ctypes.byref(inf), ctypes.byref(o), ctypes.byref(e)) == 0:
                    if inf.value > 0:
                        seen_inflight['v'] = True
                        self.assertEqual(e.value, lib.di_effective_backlog(p.value, inf.value, o.value))
                    if e.value > max_eff_seen['v']:
                        max_eff_seen['v'] = e.value
                    self.assertLessEqual(e.value, 2 * quantum)
                time.sleep(0.005)
            t.join(timeout=10)
            self.assertFalse(t.is_alive())
            lib.di_destroy(eng)
            self.assertEqual(res.overlap_detected, 0)
            self.assertEqual(res.duplicate_detected, 0)
            self.assertEqual(res.lost_detected, 0)
            self.assertEqual(int(res.total_consumed), st.st_size)
            self.assertTrue(seen_inflight['v'], "did not observe consumer inflight state")
            self.assertLessEqual(int(res.nodes[0].max_effective_backlog), 2 * quantum)
            self.assertGreaterEqual(int(res.nodes[0].max_consumer_inflight_backlog), quantum)
        finally:
            os.close(fd)
            os.unlink(path)


class TestAllocationProperties(unittest.TestCase):
    def test_effective_backlog_helper_three_part(self):
        lib = load_lib()
        self.assertEqual(lib.di_effective_backlog(10, 20, 30), 60)

    def test_repeated_runs_no_leak_or_corruption(self):
        lib = load_lib()
        for size in (0, 1, 4096, 1024*1024, 2*1024*1024 + 7):
            path = make_file(size)
            fd = os.open(path, os.O_RDONLY)
            try:
                st = os.fstat(fd)
                params = DiPolicyParams()
                params.base_quantum = 1024*1024
                params.max_backlog = 8*1024*1024
                params.one_outstanding_per_node = 1
                params.enable_peer_headroom = 1
                params.align_reservations = 1
                cons = (DiConsumerCfg * 2)()
                for i in range(2):
                    cons[i].mode = 2; cons[i].bytes_per_sec = 0; cons[i].stall_ms = 0
                cfg = DiConfig(); cfg.num_nodes = 2; cfg.policy = DI_POLICY_FIXED_FAA
                cfg.params = params; cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
                eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
                self.assertTrue(eng)
                res = DiResult()
                rc = lib.di_run(eng, ctypes.byref(res))
                lib.di_destroy(eng)
                self.assertEqual(rc, 0)
                self.assertEqual(int(res.total_consumed), size)
            finally:
                os.close(fd); os.unlink(path)


if __name__ == "__main__":
    unittest.main()
