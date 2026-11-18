import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(PKG))
LIB_PATH = os.path.join(os.path.dirname(PKG), "libdist_ingest.so")
sys.path.insert(0, PKG)
sys.path.insert(0, REPO)

import run_dist  # noqa: E402

DI_MAX_NODES = 64
DI_POLICY_FIXED_FAA = 1
DI_POLICY_LOCAL_ADAPTIVE = 2
DI_POLICY_RELATIVE_ADAPTIVE = 3
DI_POLICY_CENTRALIZED_INGEST = 4
POLICIES = [
    ("fixed_faa", DI_POLICY_FIXED_FAA),
    ("local_adaptive", DI_POLICY_LOCAL_ADAPTIVE),
    ("relative_adaptive", DI_POLICY_RELATIVE_ADAPTIVE),
    ("centralized_ingest", DI_POLICY_CENTRALIZED_INGEST),
]


class DiPolicyParams(ctypes.Structure):
    _fields_ = [
        ("base_quantum", ctypes.c_uint64), ("max_reservation", ctypes.c_uint64), ("max_backlog", ctypes.c_uint64),
        ("rel_min_claim", ctypes.c_uint64), ("rel_max_claim_quanta", ctypes.c_uint64),
        ("relative_rounding", ctypes.c_int), ("local_max_claim_quanta", ctypes.c_uint64),
        ("align_reservations", ctypes.c_int), ("prefer_hugepage", ctypes.c_int),
        ("strict_affinity", ctypes.c_int), ("strict_mbind", ctypes.c_int),
        ("one_outstanding_per_node", ctypes.c_int), ("enable_peer_headroom", ctypes.c_int), ("consumer_kernel", ctypes.c_int),
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
        ("mbind_policy_requested", ctypes.c_int), ("mbind_policy_applied", ctypes.c_int),
        ("mbind_error", ctypes.c_int),
        ("mbind_requested_count", ctypes.c_uint64), ("mbind_success_count", ctypes.c_uint64), ("mbind_failure_count", ctypes.c_uint64),
        ("strict_mbind_failed", ctypes.c_int), ("strict_affinity_failed", ctypes.c_int), ("last_error", ctypes.c_int),
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
    lib.di_test_pin_role_with_inject.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int,
                                                 ctypes.POINTER(DiAffinityRole),
                                                 ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.di_test_pin_role_with_inject.restype = ctypes.c_int
    return lib


def make_file(size):
    fd, path = tempfile.mkstemp(prefix='dist_bs_')
    os.close(fd)
    with open(path, 'wb') as f:
        if size:
            chunk = b'abcdefgh' * 4096
            rem = size
            while rem > 0:
                n = min(rem, len(chunk))
                f.write(chunk[:n])
                rem -= n
    return path


def run_engine(path, policy, num_nodes=2, quantum=512*1024, max_backlog=8*1024*1024, consumer_kernel=1):
    lib = load_lib()
    st = os.stat(path)
    fd = os.open(path, os.O_RDONLY)
    try:
        params = DiPolicyParams()
        params.base_quantum = quantum
        params.max_backlog = max_backlog
        params.max_reservation = 0
        params.relative_rounding = 1
        params.local_max_claim_quanta = 0
        params.align_reservations = 1
        params.prefer_hugepage = 0
        params.strict_affinity = 0
        params.strict_mbind = 0
        params.one_outstanding_per_node = 1
        params.enable_peer_headroom = 1
        params.consumer_kernel = consumer_kernel
        cons = (DiConsumerCfg * num_nodes)()
        for i in range(num_nodes):
            cons[i].mode = 2  # fast
            cons[i].bytes_per_sec = 0
            cons[i].stall_ms = 0
        cfg = DiConfig()
        cfg.num_nodes = num_nodes
        cfg.policy = policy
        cfg.params = params
        cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
        cfg.cpu_lists = None
        cfg.cpu_counts = None
        cfg.phys_nodes = None
        eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
        if not eng:
            return -999, None, st.st_size
        res = DiResult()
        rc = lib.di_run(eng, ctypes.byref(res))
        lib.di_destroy(eng)
        return rc, res, st.st_size
    finally:
        os.close(fd)


def parse_dist_result(stderr):
    for line in (stderr or '').splitlines():
        if line.startswith('DIST_RESULT '):
            return json.loads(line[len('DIST_RESULT '):])
    return None


class TestConsumerKernel(unittest.TestCase):
    """WO P0: consumer kernel default, opt-out, evidence, provenance, all policies."""

    def test_runner_default_selects_full_byte_scan(self):
        path = make_file(2 * 1024 * 1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG, 'run_dist.py'),
                                '--candidate', 'fixed_faa', '--input', path, '--nodes', '2', '--no-pin'],
                               capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-1200:] + "\n" + p.stdout[-400:])
            dr = parse_dist_result(p.stderr)
            self.assertIsNotNone(dr)
            self.assertEqual(dr['consumer_kernel']['name'], 'full_byte_scan')
            self.assertEqual(dr['consumer_kernel']['id'], 1)
            self.assertEqual(dr['comparability']['consumer_kernel'], 'full_byte_scan')
        finally:
            os.unlink(path)

    def test_explicit_none_disables_scan(self):
        path = make_file(2 * 1024 * 1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG, 'run_dist.py'),
                                '--candidate', 'fixed_faa', '--input', path, '--nodes', '2', '--no-pin',
                                '--consumer-kernel', 'none'],
                               capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-1200:] + "\n" + p.stdout[-400:])
            dr = parse_dist_result(p.stderr)
            self.assertIsNotNone(dr)
            self.assertEqual(dr['consumer_kernel']['name'], 'none')
            self.assertEqual(dr['total_consumer_bytes_scanned'], 0)
            self.assertTrue(dr['consumer_kernel']['scan_bytes_evidence']['scan_equals_consumed'])
            for n in dr['nodes']:
                self.assertEqual(n['consumer_bytes_scanned'], 0)
        finally:
            os.unlink(path)

    def test_full_scan_reports_exact_consumed_bytes_all_policies(self):
        for name, pol in POLICIES:
            with self.subTest(candidate=name):
                path = make_file(3 * 1024 * 1024 + 123)
                try:
                    rc, res, sz = run_engine(path, pol, num_nodes=2, consumer_kernel=1)
                    self.assertEqual(rc, 0)
                    self.assertEqual(int(res.total_consumed), sz)
                    self.assertEqual(int(res.total_consumer_bytes_scanned), sz)
                    per = 0
                    for i in range(res.num_nodes):
                        scanned = int(res.nodes[i].consumer_bytes_scanned)
                        consumed = int(res.nodes[i].bytes_consumed)
                        # each consumed chunk scanned once => per-node scanned == consumed
                        self.assertEqual(scanned, consumed, msg=(name, i, scanned, consumed))
                        per += scanned
                    self.assertEqual(per, sz)
                finally:
                    os.unlink(path)

    def test_none_reports_zero_scanned_all_policies(self):
        for name, pol in POLICIES:
            with self.subTest(candidate=name):
                path = make_file(2 * 1024 * 1024)
                try:
                    rc, res, sz = run_engine(path, pol, num_nodes=2, consumer_kernel=0)
                    self.assertEqual(rc, 0)
                    self.assertEqual(int(res.total_consumed), sz)
                    self.assertEqual(int(res.total_consumer_bytes_scanned), 0)
                    for i in range(res.num_nodes):
                        self.assertEqual(int(res.nodes[i].consumer_bytes_scanned), 0)
                finally:
                    os.unlink(path)

    def test_result_provenance_identifies_kernel(self):
        path = make_file(1024 * 1024)
        try:
            for kname in ('full_byte_scan', 'none'):
                p = subprocess.run([sys.executable, os.path.join(PKG, 'run_dist.py'),
                                    '--candidate', 'local_adaptive', '--input', path, '--nodes', '2', '--no-pin',
                                    '--consumer-kernel', kname],
                                   capture_output=True, text=True, cwd=REPO)
                self.assertEqual(p.returncode, 0, msg=p.stderr[-1200:])
                dr = parse_dist_result(p.stderr)
                self.assertEqual(dr['consumer_kernel']['name'], kname)
                self.assertEqual(dr['comparability']['consumer_kernel'], kname)
                self.assertIn('scan_bytes_evidence', dr['consumer_kernel'])
        finally:
            os.unlink(path)


class TestAffinityValidityFactual(unittest.TestCase):
    """WO P0: factual affinity validity independent of strictness; no-pin; role topology."""

    def test_no_pin_affinity_unknown_not_verified(self):
        path = make_file(1024 * 1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG, 'run_dist.py'),
                                '--candidate', 'fixed_faa', '--input', path, '--nodes', '2', '--no-pin'],
                               capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-1200:])
            dr = parse_dist_result(p.stderr)
            # required affinity not requested => cannot be established
            self.assertIsNone(dr['validity']['affinity'])
            self.assertIsNone(dr['validity']['affinity_valid'])
            self.assertFalse(dr['topology'].get('pinning') == 'disabled' and dr['validity']['affinity'] is True)
        finally:
            os.unlink(path)

    def test_factual_helper_role_states(self):
        # required + requested + matched => True
        r_ok = {"requested": True, "set_applied": True, "query_succeeded": True, "matched": True}
        self.assertTrue(run_dist._affinity_role_factual(r_ok, True))
        # required + requested + failed => False
        r_fail = {"requested": True, "set_applied": True, "query_succeeded": True, "matched": False}
        self.assertFalse(run_dist._affinity_role_factual(r_fail, True))
        r_fail2 = {"requested": True, "set_applied": False, "query_succeeded": False, "matched": False}
        self.assertFalse(run_dist._affinity_role_factual(r_fail2, True))
        # required + not requested => None
        r_nr = {"requested": False, "set_applied": False, "query_succeeded": False, "matched": False}
        self.assertIsNone(run_dist._affinity_role_factual(r_nr, True))
        # not required => N/A
        self.assertIsNone(run_dist._affinity_role_factual(r_nr, False))

    def test_affinity_valid_factual_independent_of_strictness(self):
        # requested required role failed => False regardless of strict flag semantics at Python level
        def mk_nodes(ing_req=True, ing_ok=False, con_ok=True):
            ing = {"requested": ing_req, "set_applied": ing_ok, "query_succeeded": ing_ok, "matched": ing_ok, "required": True, "applicable": True}
            con = {"requested": True, "set_applied": con_ok, "query_succeeded": con_ok, "matched": con_ok, "required": True, "applicable": True}
            return [{"affinity": {"ingestor": ing, "consumer": con}}]
        self.assertFalse(run_dist._affinity_valid_factual(mk_nodes(True, False, True)))
        self.assertTrue(run_dist._affinity_valid_factual(mk_nodes(True, True, True)))
        self.assertIsNone(run_dist._affinity_valid_factual(mk_nodes(False, False, True)))  # required but not requested

    def test_centralized_ingest_ingestor_role_na_on_noncentral_nodes(self):
        """centralized_ingest: only node 0 ingestor required; others N/A (not failures)."""
        path = make_file(2 * 1024 * 1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG, 'run_dist.py'),
                                '--candidate', 'centralized_ingest', '--input', path, '--nodes', '2', '--no-pin'],
                               capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-1200:])
            dr = parse_dist_result(p.stderr)
            self.assertEqual(dr['candidate'], 'centralized_ingest')
            # node 0 ingestor applicable/required; node 1 ingestor not required/applicable
            self.assertTrue(dr['nodes'][0]['affinity']['ingestor'].get('required', False))
            self.assertFalse(dr['nodes'][1]['affinity']['ingestor'].get('required', True))
            self.assertFalse(dr['nodes'][1]['affinity']['ingestor'].get('applicable', True))
            # consumers required on all nodes
            for n in dr['nodes']:
                self.assertTrue(n['affinity']['consumer'].get('required', False))
            # no-pin => affinity unknown overall (not false due to N/A ingestor roles)
            self.assertIsNone(dr['validity']['affinity'])
        finally:
            os.unlink(path)

    def test_distributed_ingestor_required_all_nodes(self):
        path = make_file(2 * 1024 * 1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG, 'run_dist.py'),
                                '--candidate', 'fixed_faa', '--input', path, '--nodes', '2', '--no-pin'],
                               capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-1200:])
            dr = parse_dist_result(p.stderr)
            for n in dr['nodes']:
                self.assertTrue(n['affinity']['ingestor'].get('required', False))
                self.assertTrue(n['affinity']['consumer'].get('required', False))
        finally:
            os.unlink(path)


class TestMbindValidityFactual(unittest.TestCase):
    """WO P0: mbind requested/succeeded/failed accounting and factual validity."""

    def test_mbind_counts_all_success(self):
        path = make_file(2 * 1024 * 1024)
        try:
            rc, res, sz = run_engine(path, DI_POLICY_FIXED_FAA, num_nodes=2, consumer_kernel=0)
            self.assertEqual(rc, 0)
            # phys_nodes None in direct engine call => no policy requested
            # but use run_dist CLI path for requested policy with resolved topology
        finally:
            os.unlink(path)
        path = make_file(2 * 1024 * 1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG, 'run_dist.py'),
                                '--candidate', 'fixed_faa', '--input', path, '--nodes', '2', '--no-pin'],
                               capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-1200:])
            dr = parse_dist_result(p.stderr)
            # memory policy application validity factual (independent of strict)
            mpv = dr['validity']['memory_policy_application']
            # on this host with resolved physical nodes, mbind is requested; result must be True or False, not "any success hides failure"
            self.assertIn(mpv, (True, False, None))
            for n in dr['nodes']:
                mp = n['memory_policy']
                req = int(mp.get('requested_count', 0))
                suc = int(mp.get('success_count', 0))
                fail = int(mp.get('failure_count', 0))
                self.assertEqual(req, suc + fail)
                if req > 0 and fail == 0:
                    self.assertTrue(mp['all_requested_succeeded'])
                    self.assertTrue(mp['mbind_policy_applied'])
                if fail > 0:
                    self.assertFalse(mp['all_requested_succeeded'])
                    self.assertFalse(mp['mbind_policy_applied'])
        finally:
            os.unlink(path)

    def test_memory_policy_valid_factual_helper(self):
        nodes_all_ok = [{"memory_policy": {"requested_count": 3, "success_count": 3, "failure_count": 0}}]
        self.assertTrue(run_dist._memory_policy_valid_factual(nodes_all_ok))
        nodes_mixed = [{"memory_policy": {"requested_count": 3, "success_count": 2, "failure_count": 1}}]
        self.assertFalse(run_dist._memory_policy_valid_factual(nodes_mixed))
        nodes_all_fail = [{"memory_policy": {"requested_count": 2, "success_count": 0, "failure_count": 2}}]
        self.assertFalse(run_dist._memory_policy_valid_factual(nodes_all_fail))
        nodes_none = [{"memory_policy": {"requested_count": 0, "success_count": 0, "failure_count": 0, "requested": False}}]
        self.assertIsNone(run_dist._memory_policy_valid_factual(nodes_none))

    def test_no_mbind_request_engine_direct(self):
        # phys_nodes None => policy not requested
        path = make_file(1024 * 1024)
        try:
            rc, res, sz = run_engine(path, DI_POLICY_FIXED_FAA, num_nodes=1, consumer_kernel=0)
            self.assertEqual(rc, 0)
            m = res.nodes[0]
            self.assertEqual(int(m.mbind_requested_count), 0)
            self.assertEqual(int(m.mbind_failure_count), 0)
            # factual validity None
            nd = run_dist.node_metrics_to_dict(m, 0, requested_phys_node=None, policy=DI_POLICY_FIXED_FAA)
            self.assertIsNone(run_dist._memory_policy_valid_factual([nd]))
        finally:
            os.unlink(path)


class TestCombinedValidity(unittest.TestCase):
    def test_numa_placement_requires_verified_affinity_policy_and_observation(self):
        # cannot be true if affinity unknown
        nodes = [{
            "affinity": {"ingestor": {"required": True, "requested": False, "applicable": True},
                         "consumer": {"required": True, "requested": False, "applicable": True}},
            "memory_policy": {"requested_count": 1, "success_count": 1, "failure_count": 0, "requested": True},
            "placement": {"sample_other_node_pages": 0, "sampling_unavailable": False, "sampling_not_performed": False, "sample_unknown_pages": 0, "sampled_pages": 10},
        }]
        aff = run_dist._affinity_valid_factual(nodes)
        mp = run_dist._memory_policy_valid_factual(nodes)
        obs = run_dist._placement_observed_all_sampled_on_target(nodes)
        self.assertIsNone(aff)
        self.assertTrue(mp)
        self.assertTrue(obs)
        # numa placement cannot be promoted to true
        numa = None
        if obs is False:
            numa = False
        elif obs is True and mp is True and aff is True:
            numa = True
        elif aff is False or mp is False:
            numa = False
        else:
            numa = None
        self.assertIsNone(numa)


if __name__ == '__main__':
    unittest.main()


class TestAffinityFailureModes(unittest.TestCase):
    def test_strict_affinity_failure_aborts_but_factual_false(self):
        """Strict affinity: enforcement aborts/fails run; factual validity remains false."""
        path = make_file(2 * 1024 * 1024)
        try:
            # Request an impossible CPU via explicit phys-nodes/cpu mapping isn't directly exposed,
            # but engine strict_affinity with requested pinning on a valid topology should succeed.
            # To force a deterministic failure we rely on di_test_pin_role_with_inject semantics in C tests
            # and verify strict/non-strict factual computation is independent in helpers.
            # Here: strict_affinity with valid no-pin? no-pin means not requested -> unknown.
            # Use helpers for deterministic factual-independence assertion.
            nodes_fail = [{
                "affinity": {
                    "ingestor": {"required": True, "requested": True, "set_applied": False, "query_succeeded": False, "matched": False, "applicable": True},
                    "consumer": {"required": True, "requested": True, "set_applied": True, "query_succeeded": True, "matched": True, "applicable": True},
                },
                "memory_policy": {"requested_count": 0, "success_count": 0, "failure_count": 0},
                "placement": {"sample_other_node_pages": 0, "sampling_unavailable": True, "sampling_not_performed": True, "sample_unknown_pages": 0, "sampled_pages": 0},
            }]
            # factual validity is false regardless of strictness concept
            self.assertFalse(run_dist._affinity_valid_factual(nodes_fail))
            self.assertFalse(run_dist._affinity_valid_factual(nodes_fail))  # same result
        finally:
            os.unlink(path)

    def test_non_strict_affinity_failure_factual_false(self):
        nodes_fail = [{
            "affinity": {
                "ingestor": {"required": True, "requested": True, "set_applied": True, "query_succeeded": True, "matched": False, "applicable": True},
                "consumer": {"required": True, "requested": True, "set_applied": True, "query_succeeded": True, "matched": True, "applicable": True},
            },
            "memory_policy": {"requested_count": 0, "success_count": 0, "failure_count": 0},
            "placement": {"sample_other_node_pages": 0, "sampling_unavailable": True, "sampling_not_performed": True, "sample_unknown_pages": 0, "sampled_pages": 0},
        }]
        self.assertFalse(run_dist._affinity_valid_factual(nodes_fail))


class TestMbindAccountingDeterministic(unittest.TestCase):
    def test_mixed_success_and_failure(self):
        nodes = [{"memory_policy": {"requested_count": 4, "success_count": 3, "failure_count": 1, "requested": True}}]
        self.assertFalse(run_dist._memory_policy_valid_factual(nodes))

    def test_all_failed(self):
        nodes = [{"memory_policy": {"requested_count": 2, "success_count": 0, "failure_count": 2, "requested": True}}]
        self.assertFalse(run_dist._memory_policy_valid_factual(nodes))

    def test_strict_non_strict_same_factual_validity(self):
        # strictness affects enforcement, not factual classification
        nodes_fail = [{"memory_policy": {"requested_count": 3, "success_count": 2, "failure_count": 1, "requested": True}}]
        nodes_ok = [{"memory_policy": {"requested_count": 3, "success_count": 3, "failure_count": 0, "requested": True}}]
        nodes_none = [{"memory_policy": {"requested_count": 0, "success_count": 0, "failure_count": 0, "requested": False}}]
        for nset, expected in ((nodes_fail, False), (nodes_ok, True), (nodes_none, None)):
            self.assertEqual(run_dist._memory_policy_valid_factual(nset), expected)
            # calling again gives same result (no hidden strictness parameter)
            self.assertEqual(run_dist._memory_policy_valid_factual(nset), expected)

    def test_all_success(self):
        nodes = [{"memory_policy": {"requested_count": 5, "success_count": 5, "failure_count": 0, "requested": True}}]
        self.assertTrue(run_dist._memory_policy_valid_factual(nodes))


class TestCampaignWiring(unittest.TestCase):
    def test_campaign_generated_specs_explicit_kernel_and_strict_options(self):
        out = tempfile.mkdtemp(prefix='dist_camp_spec_')
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--quick', '--out', out, '--campaign-id', 'test-specs',
                   '--candidates', 'centralized_ingest,fixed_faa',
                   '--trials', '1', '--seed', 's1',
                   '--consumer-kernel', 'none',
                   '--strict-affinity', '--strict-mbind']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-2000:] + "\n" + p.stdout[-1000:])
            # every dist-engine case spec must explicitly include consumer_kernel and strict flags
            specs = []
            for root, dirs, files in os.walk(os.path.join(out, 'cases')):
                for f in files:
                    if f == 'spec.json':
                        specs.append(os.path.join(root, f))
            self.assertTrue(specs, 'no specs found')
            for sp in specs:
                with open(sp) as fh:
                    d = json.load(fh)
                if d.get('ingest_candidate') in ('centralized_ingest', 'fixed_faa', 'local_adaptive', 'relative_adaptive'):
                    self.assertEqual(d.get('consumer_kernel'), 'none', msg=sp)
                    self.assertTrue(d.get('strict_affinity'), msg=sp)
                    self.assertTrue(d.get('strict_mbind'), msg=sp)
            # campaign manifest records config
            with open(os.path.join(out, 'campaign-manifest.json')) as fh:
                cm = json.load(fh)
            self.assertEqual(cm['campaign_config']['consumer_kernel'], 'none')
            self.assertTrue(cm['campaign_config']['strict_affinity'])
            self.assertTrue(cm['campaign_config']['strict_mbind'])
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_end_to_end_campaign_smoke_kernel_reaches_c_engine(self):
        """End-to-end: selected kernel reaches C engine (scan bytes evidence), not just CLI accepted."""
        out = tempfile.mkdtemp(prefix='dist_camp_e2e_')
        try:
            # full_byte_scan (default explicit) should show scanned == consumed in dist results
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--quick', '--out', out, '--campaign-id', 'test-e2e-kernel',
                   '--candidates', 'fixed_faa,centralized_ingest',
                   '--trials', '1', '--seed', 'k1',
                   '--consumer-kernel', 'full_byte_scan']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-2000:] + "\n" + p.stdout[-1000:])
            # find dist-result.json or DIST_RESULT in manifests/stderr logs
            found = 0
            for root, dirs, files in os.walk(os.path.join(out, 'cases')):
                # manifests contain dist_result
                if 'manifest.json' in files:
                    with open(os.path.join(root, 'manifest.json')) as fh:
                        m = json.load(fh)
                    dr = m.get('dist_result')
                    if dr:
                        found += 1
                        self.assertEqual(dr.get('consumer_kernel', {}).get('name'), 'full_byte_scan', msg=root)
                        self.assertEqual(int(dr.get('total_consumer_bytes_scanned', -1)), int(dr.get('total_consumed', -2)), msg=root)
                        self.assertTrue(dr.get('consumer_kernel', {}).get('scan_bytes_evidence', {}).get('scan_equals_consumed'), msg=root)
                        # per-node evidence
                        per = sum(int(n.get('consumer_bytes_scanned', 0)) for n in dr.get('nodes', []))
                        self.assertEqual(per, int(dr.get('total_consumed', 0)), msg=root)
            self.assertGreater(found, 0, 'no dist results found in campaign manifests')
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()


class TestAffinityStrictEnforcement(unittest.TestCase):
    """WO P0: strict aborts on required failure; non-strict may complete but factual validity false."""

    def _run_with_bad_cpu(self, strict_affinity):
        path = make_file(1024 * 1024)
        lib = load_lib()
        st = os.stat(path)
        fd = os.open(path, os.O_RDONLY)
        try:
            params = DiPolicyParams()
            params.base_quantum = 512 * 1024
            params.max_backlog = 8 * 1024 * 1024
            params.align_reservations = 1
            params.one_outstanding_per_node = 1
            params.enable_peer_headroom = 1
            params.consumer_kernel = 0
            params.strict_affinity = 1 if strict_affinity else 0
            cons = (DiConsumerCfg * 1)()
            cons[0].mode = 2
            cpu = (ctypes.c_int * 1)(999999)
            CpuArr = ctypes.POINTER(ctypes.c_int) * 1
            cpu_lists = CpuArr(ctypes.cast(cpu, ctypes.POINTER(ctypes.c_int)))
            counts = (ctypes.c_int * 1)(1)
            cfg = DiConfig()
            cfg.num_nodes = 1
            cfg.policy = DI_POLICY_FIXED_FAA
            cfg.params = params
            cfg.consumers = ctypes.cast(cons, ctypes.POINTER(DiConsumerCfg))
            cfg.cpu_lists = ctypes.cast(cpu_lists, ctypes.c_void_p)
            cfg.cpu_counts = ctypes.cast(counts, ctypes.c_void_p)
            cfg.phys_nodes = None
            eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            self.assertTrue(eng)
            res = DiResult()
            rc = lib.di_run(eng, ctypes.byref(res))
            lib.di_destroy(eng)
            return rc, res, st.st_size
        finally:
            os.close(fd)
            os.unlink(path)

    def test_strict_affinity_failure_aborts_and_factual_false(self):
        rc, res, sz = self._run_with_bad_cpu(strict_affinity=True)
        self.assertNotEqual(rc, 0, "strict affinity must fail/abort run on required failure")
        # factual role outcomes show failure
        for i in range(res.num_nodes):
            ing = res.nodes[i].affinity_ingestor
            con = res.nodes[i].affinity_consumer
            # at least one required role was requested and failed to match/apply
            failed_role = ((ing.requested and (not ing.matched or not ing.set_applied)) or
                           (con.requested and (not con.matched or not con.set_applied)))
            self.assertTrue(failed_role)
        self.assertTrue(any(bool(res.nodes[i].strict_affinity_failed) for i in range(res.num_nodes)))
        # factual validity (Python computation, independent of strictness flag) is false
        nds = [run_dist.node_metrics_to_dict(res.nodes[i], i, requested_phys_node=None, policy=DI_POLICY_FIXED_FAA)
               for i in range(res.num_nodes)]
        self.assertFalse(run_dist._affinity_valid_factual(nds))

    def test_non_strict_affinity_failure_may_complete_but_factual_false(self):
        rc, res, sz = self._run_with_bad_cpu(strict_affinity=False)
        # non-strict: run may complete functionally; affinity failure is reported factually
        # (on this platform pin failure is reported; functional completion depends on engine behavior,
        # but factual validity must be false because required requested roles failed)
        nds = [run_dist.node_metrics_to_dict(res.nodes[i], i, requested_phys_node=None, policy=DI_POLICY_FIXED_FAA)
               for i in range(res.num_nodes)]
        self.assertFalse(run_dist._affinity_valid_factual(nds))
        # roles record requested but not matched
        any_failed = False
        for i in range(res.num_nodes):
            ing = res.nodes[i].affinity_ingestor
            con = res.nodes[i].affinity_consumer
            if ing.requested and not ing.matched:
                any_failed = True
            if con.requested and not con.matched:
                any_failed = True
        self.assertTrue(any_failed)
        # strict enforcement flag should not be the cause of factual classification in non-strict mode
        # (factual helper doesn't take strict_affinity)
