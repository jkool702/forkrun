import ctypes
import os
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
LIB_PATH = os.path.join(os.path.dirname(PKG), "libdist_ingest.so")

DI_POLICY_FIXED_FAA = 1
DI_MAX_NODES = 64


class DiPolicyParams(ctypes.Structure):
    _fields_ = [
        ("base_quantum", ctypes.c_uint64), ("max_reservation", ctypes.c_uint64), ("max_backlog", ctypes.c_uint64),
        ("rel_min_claim", ctypes.c_uint64), ("rel_max_claim_quanta", ctypes.c_uint64),
        ("relative_rounding", ctypes.c_int), ("local_max_claim_quanta", ctypes.c_uint64),
        ("align_reservations", ctypes.c_int), ("prefer_hugepage", ctypes.c_int),
        ("strict_affinity", ctypes.c_int), ("strict_mbind", ctypes.c_int),
        ("one_outstanding_per_node", ctypes.c_int), ("enable_peer_headroom", ctypes.c_int), ("consumer_kernel", ctypes.c_int),
        ("placement_sampling", ctypes.c_int), ("invariant_asserts", ctypes.c_int),
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
    lib.di_test_set_pread_seam.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint64]
    lib.di_test_set_pread_seam.restype = ctypes.c_int
    lib.di_test_pread_seam_fired.argtypes = [ctypes.c_void_p]
    lib.di_test_pread_seam_fired.restype = ctypes.c_int
    lib.di_test_check_2m_alignment.argtypes = [ctypes.c_size_t]
    lib.di_test_check_2m_alignment.restype = ctypes.c_int
    return lib


def make_file(size):
    fd, path = tempfile.mkstemp(prefix='dist_s3_')
    os.close(fd)
    with open(path, 'wb') as f:
        if size:
            f.write((b'0123456789abcdef' * ((size // 16) + 1))[:size])
    return path


def run_with_seam(path, lib, seam_mode, seam_counter, seam_threshold, nodes=1, quantum=1024*1024, max_backlog=8*1024*1024):
    st = os.stat(path)
    fd = os.open(path, os.O_RDONLY)
    try:
        params = DiPolicyParams()
        params.base_quantum = quantum; params.max_backlog = max_backlog
        params.one_outstanding_per_node = 1; params.enable_peer_headroom = 1
        params.align_reservations = 1; params.relative_rounding = 1
        cons = (DiConsumerCfg * nodes)()
        for i in range(nodes):
            cons[i].mode = 2
        cfg = DiConfig(); cfg.num_nodes = nodes; cfg.policy = DI_POLICY_FIXED_FAA
        cfg.params = params; cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
        eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
        assert eng
        lib.di_test_set_pread_seam(eng, seam_mode, seam_counter, seam_threshold)
        res = DiResult()
        rc = lib.di_run(eng, ctypes.byref(res))
        fired = lib.di_test_pread_seam_fired(eng)
        lib.di_destroy(eng)
        return rc, res, st.st_size, fired
    finally:
        os.close(fd)


def run_simple(path, lib, nodes=2, quantum=1024*1024, max_backlog=8*1024*1024):
    st = os.stat(path)
    fd = os.open(path, os.O_RDONLY)
    try:
        params = DiPolicyParams()
        params.base_quantum = quantum; params.max_backlog = max_backlog
        params.one_outstanding_per_node = 1; params.enable_peer_headroom = 1
        params.align_reservations = 1; params.relative_rounding = 1
        cons = (DiConsumerCfg * nodes)()
        for i in range(nodes):
            cons[i].mode = 2
        cfg = DiConfig(); cfg.num_nodes = nodes; cfg.policy = DI_POLICY_FIXED_FAA
        cfg.params = params; cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
        eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
        assert eng
        res = DiResult()
        rc = lib.di_run(eng, ctypes.byref(res))
        lib.di_destroy(eng)
        return rc, res, st.st_size
    finally:
        os.close(fd)


class TestPartialReadAndEOF(unittest.TestCase):
    def setUp(self):
        self.lib = load_lib()

    def test_repeated_eintr_retried(self):
        path = make_file(2 * 1024 * 1024)
        try:
            rc, res, sz, fired = run_with_seam(path, self.lib, 1, 5, 0, nodes=1)
            self.assertEqual(rc, 0)
            self.assertEqual(int(res.total_consumed), sz)
            self.assertEqual(int(res.total_read), sz)
            self.assertTrue(fired)
        finally:
            os.unlink(path)

    def test_partial_reads_fill_reservation(self):
        path = make_file(2 * 1024 * 1024)
        try:
            rc, res, sz, fired = run_with_seam(path, self.lib, 2, 4096, 0, nodes=1, quantum=512*1024)
            self.assertEqual(rc, 0)
            self.assertEqual(int(res.total_consumed), sz)
            self.assertFalse(res.lost_detected)
            self.assertTrue(fired)
        finally:
            os.unlink(path)

    def test_final_partial_reservation(self):
        path = make_file(2 * 1024 * 1024 + 123)
        try:
            rc, res, sz = run_simple(path, self.lib, nodes=2, quantum=1024*1024)
            self.assertEqual(rc, 0)
            self.assertEqual(int(res.total_consumed), sz)
            self.assertEqual(int(res.total_read), sz)
            self.assertFalse(res.overlap_detected or res.duplicate_detected or res.lost_detected)
        finally:
            os.unlink(path)

    def test_premature_eof_marks_invalid(self):
        path = make_file(2 * 1024 * 1024)
        try:
            rc, res, sz, fired = run_with_seam(path, self.lib, 3, 0, 1024*1024, nodes=1, quantum=1024*1024)
            self.assertNotEqual(rc, 0)
            self.assertTrue(res.input_changed or res.lost_detected or rc != 0)
            self.assertNotEqual(int(res.total_consumed), sz)
            self.assertTrue(fired)
        finally:
            os.unlink(path)

    def test_range_ends_at_file_boundary(self):
        # exact multiple / boundary end: assigned/read/published/consumed all equal file size
        path = make_file(3 * 1024 * 1024)
        try:
            rc, res, sz = run_simple(path, self.lib, nodes=2, quantum=1024*1024)
            self.assertEqual(rc, 0)
            self.assertEqual(int(res.total_assigned), sz)
            self.assertEqual(int(res.total_read), sz)
            self.assertEqual(int(res.total_published), sz)
            self.assertEqual(int(res.total_consumed), sz)
        finally:
            os.unlink(path)

    def test_partial_positive_read_followed_by_fatal_error(self):
        # mode 5: deliver partial then fatal error => run must fail; in-progress
        # reservation is not published/committed.
        path = make_file(2 * 1024 * 1024)
        try:
            rc, res, sz, fired = run_with_seam(path, self.lib, 5, 4096, 0, nodes=1, quantum=1024*1024)
            self.assertNotEqual(rc, 0)
            self.assertTrue(fired)
            self.assertNotEqual(int(res.total_consumed), sz)
            # failed reservation must not be published; assigned/read/published/consumed
            # remain consistent (only fully completed chunks are counted).
            self.assertEqual(int(res.total_published), int(res.total_consumed))
            self.assertLessEqual(int(res.total_read), int(res.total_assigned))
            self.assertGreaterEqual(int(res.total_assigned), int(res.total_read))
        finally:
            os.unlink(path)

    def test_truncation_or_premature_eof_final_range(self):
        # premature EOF affecting final assigned range (threshold near end)
        path = make_file(2 * 1024 * 1024 + 123)
        try:
            rc, res, sz, fired = run_with_seam(path, self.lib, 3, 0, 2*1024*1024, nodes=1, quantum=1024*1024)
            self.assertNotEqual(rc, 0)
            self.assertTrue(fired)
            self.assertTrue(res.input_changed or res.lost_detected)
        finally:
            os.unlink(path)

    def test_file_truncation_during_ingestion_detected(self):
        path = make_file(8 * 1024 * 1024)
        try:
            st = os.stat(path)
            fd = os.open(path, os.O_RDONLY)
            try:
                params = DiPolicyParams()
                params.base_quantum = 512*1024; params.max_backlog = 2*1024*1024
                params.one_outstanding_per_node = 1; params.enable_peer_headroom = 1
                params.align_reservations = 1; params.relative_rounding = 1
                cons = (DiConsumerCfg * 1)()
                cons[0].mode = 1; cons[0].bytes_per_sec = 512*1024
                cfg = DiConfig(); cfg.num_nodes = 1; cfg.policy = DI_POLICY_FIXED_FAA
                cfg.params = params; cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
                eng = self.lib.di_create(fd, st.st_size, ctypes.byref(cfg))
                self.assertTrue(eng)
                res = DiResult()
                def trunc():
                    time.sleep(0.05)
                    try:
                        os.truncate(path, 1024*1024)
                    except OSError:
                        pass
                th = threading.Thread(target=trunc)
                th.start()
                rc = self.lib.di_run(eng, ctypes.byref(res))
                th.join()
                self.lib.di_destroy(eng)
                self.assertTrue(rc != 0 or res.input_changed or int(res.total_consumed) != st.st_size)
            finally:
                os.close(fd)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


class TestAllocationAlignment(unittest.TestCase):
    def test_2m_alignment_various_sizes(self):
        lib = load_lib()
        for sz in (1, 4096, 65536, 1024*1024, 2*1024*1024, 2*1024*1024+1, 3*1024*1024):
            r = lib.di_test_check_2m_alignment(sz)
            self.assertEqual(r, 1, msg="size %d not 2MiB aligned (rc=%s)" % (sz, r))


if __name__ == "__main__":
    unittest.main()
