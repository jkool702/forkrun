import ctypes
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PKG))
LIB_PATH = os.path.join(os.path.dirname(PKG), "libdist_ingest.so")

DI_MAX_NODES = 64
DI_POLICY_FIXED_FAA = 1
DI_POLICY_LOCAL_ADAPTIVE = 2
DI_POLICY_RELATIVE_ADAPTIVE = 3
DI_POLICY_CENTRALIZED_INGEST = 4


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
        ("placement_sampling", ctypes.c_int),
        ("invariant_asserts", ctypes.c_int),  # CK-5 (appended, matches C)
    ]


class DiConsumerCfg(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("bytes_per_sec", ctypes.c_uint64),
        ("stall_ms", ctypes.c_uint64),
    ]


class DiIngestorCfg(ctypes.Structure):
    # §5.2: mirrors dist_ingest.h di_ingestor_cfg_t.
    _fields_ = [
        ("mode", ctypes.c_int),          # 0=off,1=delay_per_claim,2=delay_after_read,3=stall_then_recover,4=rate_limit
        ("delay_ns", ctypes.c_uint64),
        ("stall_ms", ctypes.c_uint64),
        ("rate_bps", ctypes.c_uint64),
    ]


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
        ("reservations", ctypes.c_uint64),
        ("bytes_reserved_req", ctypes.c_uint64),
        ("bytes_assigned", ctypes.c_uint64),
        ("bytes_read", ctypes.c_uint64),
        ("bytes_published", ctypes.c_uint64),
        ("bytes_consumed", ctypes.c_uint64),
        ("consumer_bytes_scanned", ctypes.c_uint64),
        ("chunks_published", ctypes.c_uint64),
        ("chunks_consumed", ctypes.c_uint64),
        ("zero_claims", ctypes.c_uint64),
        ("claim_wait_ns", ctypes.c_uint64),
        ("read_wait_ns", ctypes.c_uint64),
        ("publish_wait_ns", ctypes.c_uint64),
        ("consume_wait_ns", ctypes.c_uint64),
        ("current_published_backlog", ctypes.c_uint64),
        ("current_consumer_inflight_backlog", ctypes.c_uint64),
        ("current_outstanding", ctypes.c_uint64),
        ("current_effective_backlog", ctypes.c_uint64),
        ("max_published_backlog", ctypes.c_uint64),
        ("max_consumer_inflight_backlog", ctypes.c_uint64),
        ("max_effective_backlog", ctypes.c_uint64),
        ("peer_observe_ns", ctypes.c_uint64),
        ("peer_observe_count", ctypes.c_uint64),
        ("placement_total_addressable_pages", ctypes.c_uint64),
        ("placement_sampled_pages", ctypes.c_uint64),
        ("placement_sample_limit", ctypes.c_uint64),
        ("placement_sample_spacing", ctypes.c_uint64),
        ("placement_sample_target_match_pages", ctypes.c_uint64),
        ("placement_sample_other_node_pages", ctypes.c_uint64),
        ("placement_sample_unknown_pages", ctypes.c_uint64),
        ("placement_sampling_unavailable", ctypes.c_int),
        ("placement_sampling_not_performed", ctypes.c_int),
        ("hugepage_map_requested_bytes", ctypes.c_uint64),
        ("hugepage_map_obtained_bytes", ctypes.c_uint64),
        ("hugepage_fallback_bytes", ctypes.c_uint64),
        ("hugepage_observed_kb", ctypes.c_uint64),
        ("alloc_bytes", ctypes.c_uint64),
        ("ingest_cpu_ns", ctypes.c_uint64),
        ("consumer_cpu_ns", ctypes.c_uint64),
        ("res_hist", ctypes.c_uint64 * 20),
        ("affinity_ingestor", DiAffinityRole),
        ("affinity_consumer", DiAffinityRole),
        # §5.2: ingestor workload control evidence (observed, per node).
        ("ingestor_mode", ctypes.c_int),
        ("ingestor_delay_ns", ctypes.c_uint64),
        ("ingestor_stall_fired", ctypes.c_uint64),
        ("ingestor_rate_throttled_ns", ctypes.c_uint64),
        ("mbind_policy_requested", ctypes.c_int),
        ("mbind_policy_applied", ctypes.c_int),
        ("mbind_error", ctypes.c_int),
        ("mbind_requested_count", ctypes.c_uint64),
        ("mbind_success_count", ctypes.c_uint64),
        ("mbind_failure_count", ctypes.c_uint64),
        ("strict_mbind_failed", ctypes.c_int),
        ("strict_affinity_failed", ctypes.c_int),
        ("last_error", ctypes.c_int),
            ("zero_claims_policy", ctypes.c_uint64), ("zero_claims_admission", ctypes.c_uint64), ("accounting_violation", ctypes.c_int),
]


class DiResult(ctypes.Structure):
    _fields_ = [
        ("total_bytes", ctypes.c_uint64),
        ("total_reserved_req", ctypes.c_uint64),
        ("total_assigned", ctypes.c_uint64),
        ("total_read", ctypes.c_uint64),
        ("total_published", ctypes.c_uint64),
        ("total_consumed", ctypes.c_uint64),
        ("total_consumer_bytes_scanned", ctypes.c_uint64),
        ("reservations_total", ctypes.c_uint64),
        ("eof_offset", ctypes.c_uint64),
        ("overlap_detected", ctypes.c_int),
        ("duplicate_detected", ctypes.c_int),
        ("lost_detected", ctypes.c_int),
        ("input_changed", ctypes.c_int),
        ("wall_seconds", ctypes.c_double),
        ("ingest_cpu_ns", ctypes.c_uint64),
        ("consumer_cpu_ns", ctypes.c_uint64),
        ("num_nodes", ctypes.c_int),
        ("policy", ctypes.c_int),
        ("nodes", DiNodeMetrics * DI_MAX_NODES),
        ("res_hist", ctypes.c_uint64 * 20),
        ("invariant_failed", ctypes.c_int), ("accounting_failed", ctypes.c_int),
    ]


class DiConfig(ctypes.Structure):
    _fields_ = [
        ("num_nodes", ctypes.c_int),
        ("policy", ctypes.c_int),
        ("params", DiPolicyParams),
        ("consumers", ctypes.POINTER(DiConsumerCfg)),
        ("ingestors", ctypes.c_void_p),
        ("cpu_lists", ctypes.c_void_p),
        ("cpu_counts", ctypes.c_void_p),
        ("phys_nodes", ctypes.c_void_p),
    ]


def load_lib():
    lib = ctypes.CDLL(LIB_PATH)
    lib.di_create.argtypes = [ctypes.c_int, ctypes.c_uint64, ctypes.POINTER(DiConfig)]
    lib.di_create.restype = ctypes.c_void_p
    lib.di_destroy.argtypes = [ctypes.c_void_p]
    lib.di_destroy.restype = None
    lib.di_run.argtypes = [ctypes.c_void_p, ctypes.POINTER(DiResult)]
    lib.di_run.restype = ctypes.c_int
    lib.di_policy_decide.argtypes = [ctypes.c_int, ctypes.POINTER(DiPolicyParams), ctypes.c_int, ctypes.c_int,
                                     ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
    lib.di_policy_decide.restype = ctypes.c_uint64
    lib.di_test_set_pread_seam.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint64]
    lib.di_test_set_pread_seam.restype = ctypes.c_int
    lib.di_test_pread_seam_fired.argtypes = [ctypes.c_void_p]
    lib.di_test_pread_seam_fired.restype = ctypes.c_int
    lib.di_test_set_push_fail_seam.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.di_test_set_push_fail_seam.restype = ctypes.c_int
    for _name in ("di_test_push_fail_fired", "di_test_alloc_fail_fired",
                  "di_test_thread_create_fail_fired", "di_test_publish_seam_fired"):
        getattr(lib, _name).argtypes = [ctypes.c_void_p]
        getattr(lib, _name).restype = ctypes.c_int
    for _name in ("di_test_set_alloc_fail_seam", "di_test_set_thread_create_fail_seam",
                  "di_test_set_publish_seam"):
        getattr(lib, _name).argtypes = [ctypes.c_void_p, ctypes.c_int]
        getattr(lib, _name).restype = ctypes.c_int
    lib.di_effective_backlog.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
    lib.di_effective_backlog.restype = ctypes.c_uint64
    return lib


def make_file(size, pattern=b'abcd'):
    fd, path = tempfile.mkstemp(prefix='dist_')
    os.close(fd)
    with open(path, 'wb') as f:
        remaining = size
        while remaining > 0:
            n = min(remaining, len(pattern) * 4096)
            block = (pattern * ((n // len(pattern)) + 1))[:n]
            f.write(block)
            remaining -= n
    return path


def run_engine(path, policy, num_nodes=2, quantum=1024*1024, max_backlog=8*1024*1024,
               consumer_mode=0, slow_node=-1, slow_mode=1, slow_bps=1000000, slow_stall_ms=0,
               relative_rounding=1):
    lib = load_lib()
    st = os.stat(path)
    fd = os.open(path, os.O_RDONLY)
    try:
        params = DiPolicyParams()
        params.base_quantum = quantum
        params.max_reservation = 0
        params.max_backlog = max_backlog
        params.rel_min_claim = 0
        params.rel_max_claim_quanta = 0
        params.relative_rounding = relative_rounding
        params.local_max_claim_quanta = 0
        params.align_reservations = 1
        params.prefer_hugepage = 0
        params.strict_affinity = 0
        params.strict_mbind = 0
        params.one_outstanding_per_node = 1
        params.enable_peer_headroom = 1
        cons = (DiConsumerCfg * num_nodes)()
        for i in range(num_nodes):
            cons[i].mode = consumer_mode
            cons[i].bytes_per_sec = 0
            cons[i].stall_ms = 0
        if 0 <= slow_node < num_nodes:
            cons[slow_node].mode = slow_mode
            cons[slow_node].bytes_per_sec = slow_bps
            cons[slow_node].stall_ms = slow_stall_ms
        cfg = DiConfig()
        cfg.num_nodes = num_nodes
        cfg.policy = policy
        cfg.params = params
        cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
        cfg.cpu_lists = None; cfg.cpu_counts = None; cfg.phys_nodes = None
        eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
        assert eng
        res = DiResult()
        rc = lib.di_run(eng, ctypes.byref(res))
        lib.di_destroy(eng)
        return rc, res, st.st_size
    finally:
        os.close(fd)


class TestPolicyDecisions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = load_lib()

    def test_fixed_faa_one_quantum_when_headroom(self):
        p = DiPolicyParams(); p.base_quantum=1024; p.max_backlog=4096; p.max_reservation=4096
        eff = (ctypes.c_uint64*2)(0,0); hr=(ctypes.c_uint64*2)(2048,2048)
        got = self.lib.di_policy_decide(DI_POLICY_FIXED_FAA, ctypes.byref(p), 2, 0, eff, hr)
        self.assertEqual(got, 1024)

    def test_fixed_faa_zero_when_no_headroom(self):
        p = DiPolicyParams(); p.base_quantum=1024; p.max_backlog=4096; p.max_reservation=4096
        eff=(ctypes.c_uint64*1)(4096); hr=(ctypes.c_uint64*1)(0)
        self.assertEqual(self.lib.di_policy_decide(DI_POLICY_FIXED_FAA, ctypes.byref(p), 1, 0, eff, hr), 0)

    def test_local_adaptive_claims_headroom_quanta(self):
        p = DiPolicyParams(); p.base_quantum=1024; p.max_backlog=8192; p.max_reservation=8192
        eff=(ctypes.c_uint64*1)(0); hr=(ctypes.c_uint64*1)(5000)
        self.assertEqual(self.lib.di_policy_decide(DI_POLICY_LOCAL_ADAPTIVE, ctypes.byref(p), 1, 0, eff, hr), 4096)

    def test_relative_single_node_behaves_local(self):
        p = DiPolicyParams(); p.base_quantum=1024; p.max_backlog=8192; p.max_reservation=8192; p.relative_rounding=1
        eff=(ctypes.c_uint64*1)(0); hr=(ctypes.c_uint64*1)(3000)
        self.assertEqual(self.lib.di_policy_decide(DI_POLICY_RELATIVE_ADAPTIVE, ctypes.byref(p), 1, 0, eff, hr), 2048)

    def test_relative_equal_headroom_one_quantum(self):
        p = DiPolicyParams(); p.base_quantum=1024; p.max_backlog=8192; p.max_reservation=8192; p.relative_rounding=1
        eff=(ctypes.c_uint64*2)(0,0); hr=(ctypes.c_uint64*2)(4096,4096)
        self.assertEqual(self.lib.di_policy_decide(DI_POLICY_RELATIVE_ADAPTIVE, ctypes.byref(p), 2, 0, eff, hr), 1024)

    def test_relative_zero_peer_headroom_claims_local(self):
        p = DiPolicyParams(); p.base_quantum=1024; p.max_backlog=8192; p.max_reservation=8192; p.relative_rounding=1
        eff=(ctypes.c_uint64*2)(0,8192); hr=(ctypes.c_uint64*2)(4096,0)
        self.assertEqual(self.lib.di_policy_decide(DI_POLICY_RELATIVE_ADAPTIVE, ctypes.byref(p), 2, 0, eff, hr), 4096)

    def test_relative_less_than_peers_can_be_zero(self):
        p = DiPolicyParams(); p.base_quantum=1024; p.max_backlog=8192; p.max_reservation=8192; p.relative_rounding=0
        eff=(ctypes.c_uint64*2)(7000,0); hr=(ctypes.c_uint64*2)(512,4096)
        got = self.lib.di_policy_decide(DI_POLICY_RELATIVE_ADAPTIVE, ctypes.byref(p), 2, 0, eff, hr)
        self.assertEqual(got, 0)


class TestEngineCorrectness(unittest.TestCase):
    def _assert_correct(self, rc, res, size):
        self.assertEqual(rc, 0)
        self.assertFalse(res.overlap_detected)
        self.assertFalse(res.duplicate_detected)
        self.assertFalse(res.lost_detected)
        self.assertEqual(int(res.total_consumed), size)
        self.assertEqual(int(res.total_read), size)

    def test_empty_file(self):
        path = make_file(0)
        try:
            for pol in (DI_POLICY_FIXED_FAA, DI_POLICY_LOCAL_ADAPTIVE, DI_POLICY_RELATIVE_ADAPTIVE):
                rc, res, size = run_engine(path, pol, num_nodes=2)
                self.assertEqual(rc, 0)
                self.assertFalse(res.overlap_detected or res.duplicate_detected or res.lost_detected)
                self.assertEqual(int(res.total_consumed), 0)
        finally:
            os.unlink(path)

    def test_small_files_and_boundaries(self):
        sizes = [1, 7, 4095, 4096, 4097, 1024*1024-1, 1024*1024, 1024*1024+1, 2*1024*1024, 2*1024*1024+1]
        for size in sizes:
            path = make_file(size)
            try:
                for pol in (DI_POLICY_FIXED_FAA, DI_POLICY_LOCAL_ADAPTIVE, DI_POLICY_RELATIVE_ADAPTIVE):
                    rc, res, sz = run_engine(path, pol, num_nodes=2, quantum=1024*1024, max_backlog=4*1024*1024)
                    self._assert_correct(rc, res, sz)
            finally:
                os.unlink(path)

    def test_single_node(self):
        path = make_file(3*1024*1024 + 123)
        try:
            for pol in (DI_POLICY_FIXED_FAA, DI_POLICY_LOCAL_ADAPTIVE, DI_POLICY_RELATIVE_ADAPTIVE):
                rc, res, sz = run_engine(path, pol, num_nodes=1)
                self._assert_correct(rc, res, sz)
        finally:
            os.unlink(path)

    def test_multi_node_race(self):
        path = make_file(16*1024*1024)
        try:
            for pol in (DI_POLICY_FIXED_FAA, DI_POLICY_LOCAL_ADAPTIVE, DI_POLICY_RELATIVE_ADAPTIVE):
                rc, res, sz = run_engine(path, pol, num_nodes=4, quantum=512*1024, max_backlog=8*1024*1024)
                self._assert_correct(rc, res, sz)
        finally:
            os.unlink(path)

    def test_slow_consumer_backpressure(self):
        path = make_file(8*1024*1024)
        try:
            rc, res, sz = run_engine(path, DI_POLICY_FIXED_FAA, num_nodes=2, quantum=512*1024,
                                     max_backlog=2*1024*1024, consumer_mode=1, slow_node=0,
                                     slow_mode=1, slow_bps=2*1024*1024)
            self._assert_correct(rc, res, sz)
            for i in range(res.num_nodes):
                self.assertLessEqual(int(res.nodes[i].max_effective_backlog), 2*1024*1024)
        finally:
            os.unlink(path)

    def test_stall_and_recovery(self):
        path = make_file(8*1024*1024)
        try:
            rc, res, sz = run_engine(path, DI_POLICY_RELATIVE_ADAPTIVE, num_nodes=4, quantum=512*1024,
                                     max_backlog=4*1024*1024, consumer_mode=0, slow_node=1,
                                     slow_mode=3, slow_bps=0, slow_stall_ms=200)
            self._assert_correct(rc, res, sz)
        finally:
            os.unlink(path)

    def test_randomized_stress(self):
        rng = random.Random(12345)
        for _ in range(12):
            size = rng.randint(0, 5*1024*1024)
            nodes = rng.randint(1, 6)
            quantum = rng.choice([4096, 65536, 262144, 1048576])
            max_backlog = rng.choice([quantum*2, quantum*8, quantum*32])
            pol = rng.choice([DI_POLICY_FIXED_FAA, DI_POLICY_LOCAL_ADAPTIVE, DI_POLICY_RELATIVE_ADAPTIVE, DI_POLICY_CENTRALIZED_INGEST])
            path = make_file(size)
            try:
                rc, res, sz = run_engine(path, pol, num_nodes=nodes, quantum=quantum, max_backlog=max_backlog,
                                         consumer_mode=rng.choice([0,2]))
                self.assertEqual(rc, 0, msg=(size,nodes,quantum,max_backlog,pol))
                self.assertFalse(res.overlap_detected or res.duplicate_detected or res.lost_detected)
                self.assertEqual(int(res.total_consumed), size)
            finally:
                os.unlink(path)


class TestCentralizedEngine(unittest.TestCase):
    """Section 5: in-engine centralized control baseline (same engine/consumers/work units)."""

    def _assert_correct(self, rc, res, file_size):
        self.assertEqual(rc, 0)
        self.assertFalse(res.overlap_detected)
        self.assertFalse(res.duplicate_detected)
        self.assertFalse(res.lost_detected)
        self.assertEqual(int(res.input_changed), 0)
        self.assertEqual(int(res.total_consumed), file_size)
        self.assertEqual(int(res.total_published), file_size)

    def test_centralized_correctness_multi_node(self):
        for size in (0, 1, 4096, 2*1024*1024 + 7, 5*1024*1024):
            path = make_file(size)
            try:
                rc, res, sz = run_engine(path, DI_POLICY_CENTRALIZED_INGEST, num_nodes=4, quantum=512*1024, max_backlog=4*1024*1024)
                self._assert_correct(rc, res, sz)
            finally:
                os.unlink(path)

    def test_centralized_cli(self):
        path = make_file(2*1024*1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG,'run_dist.py'),
                                '--candidate','centralized_ingest','--input',path,'--nodes','2','--no-pin'],
                               capture_output=True,text=True,cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-800:] + "\n" + p.stdout[-400:])
            self.assertIn('CHILD_DONE', p.stdout)
            self.assertIn('DIST_RESULT', p.stderr)
            self.assertIn('"engine_model": "dist_ingest_experimental"', p.stderr)
            self.assertIn('"centralized_baseline": true', p.stderr)
        finally:
            os.unlink(path)


class TestRunnerCLI(unittest.TestCase):
    def test_run_dist_cli(self):
        path = make_file(2*1024*1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG,'run_dist.py'),
                                '--candidate','fixed_faa','--input',path,'--nodes','1','--no-pin'],
                               capture_output=True,text=True,cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-800:] + "\n" + p.stdout[-400:])
            self.assertIn('CHILD_DONE', p.stdout)
            self.assertIn('DIST_RESULT', p.stderr)
        finally:
            os.unlink(path)


class TestIngestorWorkloadControls(unittest.TestCase):
    """§5.2: per-node ingestor workload controls (off by default).

    Engine modes: 0=off (default), 1=delay_per_claim, 2=delay_after_read,
    3=stall_then_recover, 4=rate_limit. Evidence is recorded per node in
    DIST_RESULT (mode/phase + observed counters); disabled-by-default runs
    record zero evidence.
    """

    def _run_dist(self, extra_args, size=4*1024*1024):
        path = make_file(size)
        try:
            cmd = [sys.executable, os.path.join(PKG, 'run_dist.py'),
                   '--candidate', 'fixed_faa', '--input', path,
                   '--nodes', '2', '--no-pin'] + extra_args
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-800:] + "\n" + p.stdout[-400:])
            line = [l for l in p.stderr.splitlines() if l.startswith('DIST_RESULT ')][0]
            return json.loads(line[len('DIST_RESULT '):])
        finally:
            os.unlink(path)

    def _ic(self, d, node):
        return d['nodes'][node]['ingestor_controls']

    def test_default_off_records_zero_evidence(self):
        d = self._run_dist([])
        for nd in d['nodes']:
            ic = nd['ingestor_controls']
            self.assertEqual(ic['mode'], 0)
            self.assertEqual(ic['phase'], 'off')
            self.assertEqual(ic['delay_ns'], 0)
            self.assertEqual(ic['stall_fired'], 0)
            self.assertEqual(ic['rate_throttled_ns'], 0)
        self.assertTrue(d['correct'])
        # Provenance: every node recorded as off; controls disabled by default.
        self.assertTrue(all(x['mode'] == 0 for x in d['ingestor_controls']['config_per_node']))
        self.assertTrue(d['ingestor_controls']['disabled_by_default'])

    def test_delay_per_claim_fires_and_completes(self):
        d = self._run_dist(['--ingestor-modes-per-node', 'delay_per_claim',
                            '--ingestor-delay-ns-per-node', '5000000'])
        ic = self._ic(d, 0)
        self.assertEqual(ic['mode'], 1)
        self.assertEqual(ic['phase'], 'delay_per_claim')
        self.assertGreater(ic['delay_ns'], 0)
        self.assertTrue(d['correct'])
        # Provenance matches the request.
        cfg = d['ingestor_controls']['config_per_node'][0]
        self.assertEqual(cfg['mode'], 1)
        self.assertEqual(cfg['phase'], 'delay_per_claim')
        self.assertEqual(cfg['delay_ns'], 5000000)

    def test_delay_after_read_before_publish_fires(self):
        d = self._run_dist(['--ingestor-modes-per-node', 'delay_after_read',
                            '--ingestor-delay-ns-per-node', '5000000'])
        ic = self._ic(d, 0)
        self.assertEqual(ic['mode'], 2)
        self.assertEqual(ic['phase'], 'delay_after_read_before_publish')
        self.assertGreater(ic['delay_ns'], 0)
        self.assertTrue(d['correct'])

    def test_stall_then_recover_fires(self):
        d = self._run_dist(['--ingestor-modes-per-node', 'stall_then_recover',
                            '--ingestor-stall-ms-per-node', '20'])
        ic = self._ic(d, 0)
        self.assertEqual(ic['mode'], 3)
        self.assertEqual(ic['phase'], 'stall_then_recover')
        self.assertGreaterEqual(ic['stall_fired'], 1)
        self.assertTrue(d['correct'])

    def test_rate_limit_throttles(self):
        d = self._run_dist(['--ingestor-modes-per-node', 'rate_limit',
                            '--ingestor-rate-bps-per-node', '1000000'])
        ic = self._ic(d, 0)
        self.assertEqual(ic['mode'], 4)
        self.assertEqual(ic['phase'], 'rate_limit')
        self.assertGreater(ic['rate_throttled_ns'], 0)

    def test_per_node_modes_apply_independently(self):
        d = self._run_dist(['--ingestor-modes-per-node', 'delay_per_claim,off',
                            '--ingestor-delay-ns-per-node', '5000000,0'])
        self.assertEqual(self._ic(d, 0)['mode'], 1)
        self.assertEqual(self._ic(d, 0)['phase'], 'delay_per_claim')
        self.assertEqual(self._ic(d, 1)['mode'], 0)
        self.assertEqual(self._ic(d, 1)['phase'], 'off')
        self.assertTrue(d['correct'])

    def test_rate_limit_error_path_terminates_promptly(self):
        # WO review: with rate_limit + injected pread error, the engine must
        # terminate with the error promptly — the old code slept before
        # reaching the error path (UINT64_MAX conversion of rr<0 wrapped the
        # sleep to ~5 hours).
        import time as _time
        sys.path.insert(0, PKG)
        import run_dist
        lib = ctypes.CDLL(LIB_PATH)
        lib.di_create.argtypes = [ctypes.c_int, ctypes.c_uint64, ctypes.POINTER(run_dist.DiConfig)]
        lib.di_create.restype = ctypes.c_void_p
        lib.di_run.argtypes = [ctypes.c_void_p, ctypes.POINTER(run_dist.DiResult)]
        lib.di_run.restype = ctypes.c_int
        lib.di_destroy.argtypes = [ctypes.c_void_p]
        lib.di_destroy.restype = None
        lib.di_test_set_pread_seam.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint64]
        lib.di_test_set_pread_seam.restype = ctypes.c_int
        path = make_file(1 * 1024 * 1024)
        fd = os.open(path, os.O_RDONLY)
        try:
            st = os.stat(path)
            params = run_dist.DiPolicyParams()
            params.base_quantum = 512 * 1024
            params.max_backlog = 8 * 1024 * 1024
            params.consumer_kernel = 1
            ing = run_dist.DiIngestorCfg()
            ing.mode = 4
            ing.rate_bps = 1000000
            cfg = run_dist.DiConfig()
            cfg.num_nodes = 1
            cfg.policy = DI_POLICY_FIXED_FAA
            cfg.params = params
            cfg.ingestors = ctypes.cast(ctypes.byref(ing), ctypes.POINTER(run_dist.DiIngestorCfg))
            eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            self.assertTrue(eng)
            # Inject a pread error on the first read (seam mode 4 = error_at).
            self.assertEqual(lib.di_test_set_pread_seam(eng, 4, 0, 0), 0)
            t0 = _time.monotonic()
            res = run_dist.DiResult()
            rc = lib.di_run(eng, ctypes.byref(res))
            elapsed = _time.monotonic() - t0
            lib.di_destroy(eng)
            self.assertNotEqual(rc, 0, "engine must fail on injected pread error")
            self.assertLess(elapsed, 10.0, "engine must terminate promptly on pread error, not sleep")
            self.assertEqual(res.nodes[0].ingestor_rate_throttled_ns, 0)
        finally:
            os.close(fd)
            os.unlink(path)


    def test_malformed_ingestor_args_fail_preflight(self):
        # WO review: malformed ingestor-workload lists must fail preflight
        # (non-zero exit) rather than silently degrading to defaults.
        import subprocess as sp
        bad_cases = [
            ['--ingestor-modes-per-node', 'off,rate_limit,extra'],   # excess entries
            ['--ingestor-modes-per-node', 'badmode'],                # unknown name
            ['--ingestor-modes-per-node', 'delay_per_claim,-1'],     # negative entry
            ['--ingestor-modes-per-node', 'delay_per_claim,garbage'], # non-integer
        ]
        for extra in bad_cases:
            path = make_file(4*1024*1024)
            try:
                cmd = [sys.executable, os.path.join(PKG, 'run_dist.py'),
                       '--candidate', 'fixed_faa', '--input', path,
                       '--nodes', '2', '--no-pin'] + extra
                p = sp.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=300)
                self.assertNotEqual(p.returncode, 0,
                                    msg="%r must fail preflight" % extra)
                self.assertTrue(p.stderr.strip(), "expected a stderr diagnostic")
            finally:
                os.unlink(path)


class TestPlacementSamplingModes(unittest.TestCase):
    """§2: placement-sampling modes — 0=off, 1=on (bounded, <=1024),
    2=full (exhaustive). Full mode must sample every addressable page."""

    def _run_dist_get_dist_result(self, extra_args, size):
        path = make_file(size)
        try:
            cmd = [sys.executable, os.path.join(PKG, 'run_dist.py'),
                   '--input', path, '--nodes', '2'] + extra_args
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, timeout=300)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-800:] + "\n" + p.stdout[-400:])
            line = [l for l in p.stderr.splitlines() if l.startswith('DIST_RESULT ')][0]
            return json.loads(line[len('DIST_RESULT '):])
        finally:
            os.unlink(path)

    def test_full_mode_samples_all_addressable_pages(self):
        # WO review: mode 2 must be exhaustive; use a corpus >1024 pages/node
        # (16 MiB input -> 8 MiB/node = 2048 pages) so bounded-1024 behavior
        # would be distinguishable.
        d = self._run_dist_get_dist_result(['--placement-sampling', 'full'], 16*1024*1024)
        seen_big = 0
        for nd in d['nodes']:
            pl = nd['placement']
            if pl['total_addressable_pages'] > 0:
                self.assertEqual(pl['sampled_pages'], pl['total_addressable_pages'],
                                 msg="full mode must sample every page on node %s" % nd['node'])
            if pl['total_addressable_pages'] > 1024:
                seen_big += 1
        self.assertGreater(seen_big, 0, 'expected at least one node with >1024 addressable pages')
        self.assertTrue(d['correct'])

    def test_bounded_mode_limit_still_applies(self):
        # Mode 1 (on/bounded) keeps the <=1024-page-per-allocation limit.
        d = self._run_dist_get_dist_result(['--placement-sampling', 'on'], 16*1024*1024)
        for nd in d['nodes']:
            pl = nd['placement']
            if pl['total_addressable_pages'] > 0:
                self.assertEqual(pl['sample_limit_per_allocation'], 1024, msg=nd['node'])
                self.assertLessEqual(pl['sampled_pages'], pl['total_addressable_pages'], msg=nd['node'])


if __name__ == '__main__':
    unittest.main()
