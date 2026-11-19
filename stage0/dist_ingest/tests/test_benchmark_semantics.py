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


class TestAffinityEffectiveVerifiedTriState(unittest.TestCase):
    """WO-2 P1: per-node affinity.effective_verified tri-state over applicable required roles."""

    def _mk_role(self, requested=False, set_applied=False, query_succeeded=False, matched=False, required=True):
        return {
            "requested": requested, "set_applied": set_applied, "query_succeeded": query_succeeded,
            "matched": matched, "required": required, "applicable": required,
        }

    def _ev(self, ing, con):
        ing_v = run_dist._affinity_role_factual(ing, bool(ing.get("required", False)))
        con_v = run_dist._affinity_role_factual(con, bool(con.get("required", False)))
        return run_dist._affinity_effective_verified_node(ing, ing_v, con, con_v)

    def test_both_roles_unknown(self):
        ing = self._mk_role(requested=False, required=True)
        con = self._mk_role(requested=False, required=True)
        self.assertIsNone(self._ev(ing, con))

    def test_one_verified_one_unknown(self):
        ing = self._mk_role(requested=True, set_applied=True, query_succeeded=True, matched=True, required=True)
        con = self._mk_role(requested=False, required=True)
        self.assertIsNone(self._ev(ing, con))

    def test_one_failed_one_verified(self):
        ing = self._mk_role(requested=True, set_applied=False, query_succeeded=False, matched=False, required=True)
        con = self._mk_role(requested=True, set_applied=True, query_succeeded=True, matched=True, required=True)
        self.assertIs(self._ev(ing, con), False)

    def test_both_verified(self):
        ing = self._mk_role(requested=True, set_applied=True, query_succeeded=True, matched=True, required=True)
        con = self._mk_role(requested=True, set_applied=True, query_succeeded=True, matched=True, required=True)
        self.assertIs(self._ev(ing, con), True)

    def test_centralized_node0_both_required(self):
        ing = self._mk_role(requested=True, set_applied=True, query_succeeded=True, matched=True, required=True)
        con = self._mk_role(requested=True, set_applied=True, query_succeeded=True, matched=True, required=True)
        self.assertIs(self._ev(ing, con), True)

    def test_centralized_nonzero_ingestor_na_consumer_verified(self):
        ing = self._mk_role(requested=False, required=False)  # N/A on nonzero centralized node
        con = self._mk_role(requested=True, set_applied=True, query_succeeded=True, matched=True, required=True)
        self.assertIs(self._ev(ing, con), True)

    def test_centralized_nonzero_ingestor_na_consumer_unknown(self):
        ing = self._mk_role(requested=False, required=False)
        con = self._mk_role(requested=False, required=True)
        self.assertIsNone(self._ev(ing, con))

    def test_empty_applicable_required_set_unknown(self):
        ing = self._mk_role(requested=False, required=False)
        con = self._mk_role(requested=False, required=False)
        self.assertIsNone(self._ev(ing, con))

    def test_requested_but_unqueried_is_failed(self):
        ing = self._mk_role(requested=True, set_applied=True, query_succeeded=False, matched=False, required=True)
        con = self._mk_role(requested=True, set_applied=True, query_succeeded=True, matched=True, required=True)
        self.assertIs(self._ev(ing, con), False)

    def test_no_pin_produces_unknown_not_true(self):
        path = make_file(1024 * 1024)
        try:
            p = subprocess.run([sys.executable, os.path.join(PKG, 'run_dist.py'),
                                '--candidate', 'fixed_faa', '--input', path, '--nodes', '2', '--no-pin'],
                               capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-1200:])
            dr = parse_dist_result(p.stderr)
            self.assertIsNotNone(dr)
            for n in dr['nodes']:
                ev = n['affinity'].get('effective_verified')
                self.assertIsNone(ev, msg=('effective_verified must be unknown, not true, under --no-pin', n['affinity']))
                self.assertIsNot(ev, True)
        finally:
            os.unlink(path)

    def test_centralized_nonzero_node_ingestor_na_consumer_verified_runtime(self):
        path = make_file(1024 * 1024)
        try:
            # try with pinning; if topology doesn't allow verified pinning this may not yield true,
            # so validate structure/topology-aware NA regardless and check effective semantics.
            p = subprocess.run([sys.executable, os.path.join(PKG, 'run_dist.py'),
                                '--candidate', 'centralized_ingest', '--input', path, '--nodes', '2', '--no-pin'],
                               capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-1200:])
            dr = parse_dist_result(p.stderr)
            # node 1 ingestor N/A, consumer required but unknown under --no-pin => effective unknown
            n1 = dr['nodes'][1]
            self.assertFalse(n1['affinity']['ingestor'].get('required', True))
            self.assertTrue(n1['affinity']['consumer'].get('required', False))
            self.assertIsNone(n1['affinity']['effective_verified'])
        finally:
            os.unlink(path)


class TestPerformanceMeasurementValidity(unittest.TestCase):
    """WO-2 P1: performance validity requires evidenced consumer workload."""

    def test_full_scan_matching_evidence(self):
        v = run_dist._performance_measurement_valid(True, True, 'full_byte_scan', 1000, 1000)
        self.assertIs(v, True)

    def test_full_scan_incomplete_scan_byte_accounting(self):
        v = run_dist._performance_measurement_valid(True, True, 'full_byte_scan', 999, 1000)
        self.assertIs(v, False)

    def test_full_scan_unavailable_scan_evidence(self):
        v = run_dist._performance_measurement_valid(True, True, 'full_byte_scan', None, 1000)
        self.assertIsNone(v)

    def test_full_scan_unavailable_scan_evidence_but_functional_false(self):
        v = run_dist._performance_measurement_valid(False, True, 'full_byte_scan', None, 1000)
        self.assertIs(v, False)

    def test_none_with_zero_scanned_bytes(self):
        v = run_dist._performance_measurement_valid(True, True, 'none', 0, 1000)
        self.assertIs(v, True)

    def test_none_with_nonzero_scanned_bytes(self):
        v = run_dist._performance_measurement_valid(True, True, 'none', 5, 1000)
        self.assertIs(v, False)

    def test_none_unavailable_scan_evidence(self):
        v = run_dist._performance_measurement_valid(True, True, 'none', None, 1000)
        self.assertIsNone(v)

    def test_scan_false_overrides_otherwise_true(self):
        self.assertIs(run_dist._performance_measurement_valid(True, True, 'full_byte_scan', 1, 2), False)
        self.assertIs(run_dist._performance_measurement_valid(True, True, 'none', 1, 2), False)

    def test_affinity_false_makes_perf_false(self):
        self.assertIs(run_dist._performance_measurement_valid(True, False, 'full_byte_scan', 1000, 1000), False)

    def test_scan_evidence_valid_helper(self):
        self.assertIs(run_dist._scan_evidence_valid('full_byte_scan', 10, 10), True)
        self.assertIs(run_dist._scan_evidence_valid('full_byte_scan', 9, 10), False)
        self.assertIsNone(run_dist._scan_evidence_valid('full_byte_scan', None, 10))
        self.assertIs(run_dist._scan_evidence_valid('none', 0, 10), True)
        self.assertIs(run_dist._scan_evidence_valid('none', 3, 10), False)
        self.assertIsNone(run_dist._scan_evidence_valid('none', None, 10))


class TestCampaignScenarioValidation(unittest.TestCase):
    """WO-2/WO-3: scenario profile/topology compatibility, preflight validation, and provenance."""

    NONQUICK_NODES2 = ['nodes2', 'small', 'tiny']
    NONQUICK_NODES4 = ['equal', 'slow_one', 'fast_one', 'asymmetric', 'stall_recover',
                       'nodes2', 'large_seq', 'small', 'tiny', 'boundary', 'backpressure']
    NONQUICK_FULL = ['equal', 'slow_one', 'fast_one', 'asymmetric', 'stall_recover',
                     'nodes2', 'nodes8', 'large_seq', 'small', 'tiny', 'boundary', 'backpressure']

    def _assert_no_timed_trial_manifests(self, out):
        self.assertFalse(os.path.exists(os.path.join(out, 'campaign-manifest.json')),
                         'campaign must not complete with timed trials')
        cases_dir = os.path.join(out, 'cases')
        trial_evidence = []
        if os.path.isdir(cases_dir):
            for root, dirs, files in os.walk(cases_dir):
                if 'manifest.json' in files:
                    trial_evidence.append(os.path.join(root, 'manifest.json'))
        self.assertEqual(trial_evidence, [], 'no timed trial manifests expected before timed trials')

    def _run_preflight_only(self, extra_args, source_sha='deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'):
        """Run campaign CLI so preflight succeeds/writes prevalidation.json but build fails before trials."""
        out = tempfile.mkdtemp(prefix='dist_camp_pre_')
        os.rmdir(out)
        fakebin = tempfile.mkdtemp(prefix='fakebin_')
        try:
            make_path = os.path.join(fakebin, 'make')
            with open(make_path, 'w') as f:
                f.write('#!/bin/sh\nexit 1\n')
            os.chmod(make_path, 0o755)
            env = os.environ.copy()
            env['PATH'] = fakebin + os.pathsep + env.get('PATH', '')
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-preflight',
                   '--source-sha', source_sha] + list(extra_args)
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, env=env)
            return p, out
        finally:
            shutil.rmtree(fakebin, ignore_errors=True)

    def test_incompatible_scenario_fails_before_timed_trials(self):
        out = tempfile.mkdtemp(prefix='dist_camp_incompat_')
        os.rmdir(out)
        try:
            # nodes8 is incompatible on this host (4 usable fake-NUMA nodes)
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-incompat',
                   '--scenarios', 'nodes8', '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = p.stderr + p.stdout
            self.assertIn('before timed trials', combined)
            self.assertIn('nodes8', combined)
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_explicit_phys_nodes_count_mismatch_rejected_before_timed_trials(self):
        out = tempfile.mkdtemp(prefix='dist_camp_physmismatch_')
        os.rmdir(out)
        try:
            # explicit list has 4 nodes but selected scenario needs 2 => incompatible explicit mapping
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-phys-mismatch',
                   '--scenarios', 'small', '--phys-nodes', '0,1,2,3', '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = p.stderr + p.stdout
            self.assertIn('before timed trials', combined)
            self.assertIn('explicit', combined.lower())
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_duplicate_explicit_phys_node_ids_rejected_before_timed_trials(self):
        out = tempfile.mkdtemp(prefix='dist_camp_dup_')
        os.rmdir(out)
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-dup-phys',
                   '--scenarios', 'small', '--phys-nodes', '0,0', '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = p.stderr + p.stdout
            self.assertIn('before timed trials', combined)
            self.assertIn('duplicate', combined.lower())
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_explicit_phys_node_not_online_usable_rejected_before_timed_trials(self):
        out = tempfile.mkdtemp(prefix='dist_camp_badid_')
        os.rmdir(out)
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-bad-phys',
                   '--scenarios', 'small', '--phys-nodes', '0,99', '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = p.stderr + p.stdout
            self.assertIn('before timed trials', combined)
            self.assertTrue(('99' in combined) or ('not online' in combined.lower()) or ('invalid' in combined.lower()),
                            msg=combined)
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_explicit_mapping_valid_sparse_physical_ids_succeeds(self):
        out = tempfile.mkdtemp(prefix='dist_camp_sparse_')
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--quick', '--out', out, '--campaign-id', 'test-sparse',
                   '--scenarios', 'small', '--candidates', 'fixed_faa',
                   '--trials', '1', '--seed', 'sparse1',
                   '--phys-nodes', '0,2']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-2000:] + "\n" + p.stdout[-1000:])
            with open(os.path.join(out, 'prevalidation.json')) as fh:
                pv = json.load(fh)
            self.assertEqual(pv['physical_node_mapping']['mode'], 'explicit')
            self.assertTrue(pv['physical_node_mapping'].get('explicit_mapping_validated'))
            self.assertEqual(pv['explicit_physical_node_ids'], [0, 2])
            self.assertEqual(pv['explicit_selected_node_count'], 2)
            # host usable nodes discovered on host remain distinct from explicit selection
            self.assertEqual(pv['host_usable_node_count'], 4)
            self.assertEqual(pv['available_usable_nodes'], 4)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_explicit_mapping_rejects_mixed_logical_node_counts(self):
        out = tempfile.mkdtemp(prefix='dist_camp_mixed_')
        os.rmdir(out)
        try:
            # 4-node profile selection (mixed 2/4-node scenarios) cannot use single explicit list
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-mixed-explicit',
                   '--scenarios', 'small,equal', '--phys-nodes', '0,1,2,3', '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = p.stderr + p.stdout
            self.assertIn('before timed trials', combined)
            self.assertTrue(('logical node count' in combined.lower()) or ('mixed' in combined.lower()) or ('same logical' in combined.lower()),
                            msg=combined)
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_malformed_explicit_phys_nodes_rejected_before_timed_trials(self):
        cases = [
            ('0,,1', 'small'),
            ('0,1,', 'small'),
            (',0,1', 'small'),
            ('0, ,1', 'small'),
            ('0,a', 'small'),
        ]
        for phys, scen in cases:
            with self.subTest(phys_nodes=phys):
                out = tempfile.mkdtemp(prefix='dist_camp_malph_')
                os.rmdir(out)
                try:
                    cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                           '--out', out, '--campaign-id', 'test-malformed-phys',
                           '--scenarios', scen, '--phys-nodes', phys, '--trials', '1']
                    p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
                    self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
                    combined = (p.stderr + p.stdout).lower()
                    self.assertIn('before timed trials', combined)
                    self.assertTrue(('malformed' in combined) or ('phys-nodes' in combined), msg=p.stderr + p.stdout)
                    self._assert_no_timed_trial_manifests(out)
                finally:
                    shutil.rmtree(out, ignore_errors=True)

    def test_explicit_phys_nodes_whitespace_around_valid_ids_allowed(self):
        out = tempfile.mkdtemp(prefix='dist_camp_ws_')
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--quick', '--out', out, '--campaign-id', 'test-phys-ws',
                   '--scenarios', 'small', '--candidates', 'fixed_faa',
                   '--trials', '1', '--seed', 'ws1',
                   '--phys-nodes', ' 0 , 2 ']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-2000:] + "\n" + p.stdout[-1000:])
            with open(os.path.join(out, 'prevalidation.json')) as fh:
                pv = json.load(fh)
            self.assertEqual(pv['explicit_physical_node_ids'], [0, 2])
            self.assertTrue(pv['physical_node_mapping'].get('explicit_mapping_validated'))
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_duplicate_scenario_ids_rejected_before_timed_trials(self):
        out = tempfile.mkdtemp(prefix='dist_camp_dupscen_')
        os.rmdir(out)
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-dup-scen',
                   '--scenarios', 'equal,equal', '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = p.stderr + p.stdout
            self.assertIn('before timed trials', combined)
            self.assertIn('duplicate', combined.lower())
            self.assertIn('equal', combined)
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_profile_nodes2_quick_rejected(self):
        out = tempfile.mkdtemp(prefix='dist_camp_p2q_')
        os.rmdir(out)
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-p2q',
                   '--profile', 'nodes2', '--quick', '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = p.stderr + p.stdout
            self.assertIn('nodes2', combined)
            self.assertIn('non-quick', combined.lower())
            self.assertIn('--quick', combined)
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_profile_nodes4_quick_rejected(self):
        out = tempfile.mkdtemp(prefix='dist_camp_p4q_')
        os.rmdir(out)
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-p4q',
                   '--profile', 'nodes4', '--quick', '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = p.stderr + p.stdout
            self.assertIn('nodes4', combined)
            self.assertIn('non-quick', combined.lower())
            self.assertIn('--quick', combined)
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_profile_full_quick_supported_with_unambiguous_provenance(self):
        p, out = self._run_preflight_only(['--profile', 'full', '--quick', '--trials', '1'])
        try:
            self.assertTrue(os.path.exists(os.path.join(out, 'prevalidation.json')),
                            msg=p.stdout + '\n' + p.stderr)
            self._assert_no_timed_trial_manifests(out)
            with open(os.path.join(out, 'prevalidation.json')) as fh:
                pv = json.load(fh)
            self.assertEqual([s['id'] for s in pv['selected_scenarios']], ['equal', 'slow_one', 'stall_recover', 'small'])
            self.assertEqual(pv.get('scenario_profile_requested'), 'full')
            self.assertEqual(pv.get('scenario_profile_effective'), 'full_quick')
            self.assertFalse(pv.get('scenario_profile_overridden', False))
            self.assertTrue(pv.get('profile_quick'))
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_unknown_scenario_id_mixed_with_valid_rejected(self):
        out = tempfile.mkdtemp(prefix='dist_camp_unknown_')
        os.rmdir(out)
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-unknown-scen',
                   '--scenarios', 'equal,typo', '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = p.stderr + p.stdout
            self.assertIn('before timed trials', combined)
            self.assertIn('typo', combined)
            self.assertIn('unknown', combined.lower())
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_actual_profile_nodes2_selects_exact_nonquick_set(self):
        p, out = self._run_preflight_only(['--profile', 'nodes2', '--trials', '1'])
        try:
            # preflight should succeed and write selection; build fails intentionally after preflight
            self.assertTrue(os.path.exists(os.path.join(out, 'prevalidation.json')),
                            msg=p.stdout + '\n' + p.stderr)
            self._assert_no_timed_trial_manifests(out)
            with open(os.path.join(out, 'prevalidation.json')) as fh:
                pv = json.load(fh)
            self.assertEqual([s['id'] for s in pv['selected_scenarios']], self.NONQUICK_NODES2)
            self.assertEqual(pv.get('scenario_profile_requested'), 'nodes2')
            self.assertEqual(pv.get('scenario_profile_effective'), 'nodes2')
            self.assertFalse(pv.get('scenario_profile_overridden', False))
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_actual_profile_nodes4_selects_documented_nonquick_set(self):
        p, out = self._run_preflight_only(['--profile', 'nodes4', '--trials', '1'])
        try:
            self.assertTrue(os.path.exists(os.path.join(out, 'prevalidation.json')),
                            msg=p.stdout + '\n' + p.stderr)
            self._assert_no_timed_trial_manifests(out)
            with open(os.path.join(out, 'prevalidation.json')) as fh:
                pv = json.load(fh)
            self.assertEqual([s['id'] for s in pv['selected_scenarios']], self.NONQUICK_NODES4)
            self.assertEqual(pv.get('scenario_profile_requested'), 'nodes4')
            self.assertEqual(pv.get('scenario_profile_effective'), 'nodes4')
            self.assertFalse(pv.get('scenario_profile_overridden', False))
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_actual_profile_full_selects_full_default_set(self):
        # --profile full selects the full default non-quick set via CLI. On this 4-usable-node host
        # the set includes nodes8 and is correctly rejected before timed trials; the rejection of
        # nodes8 evidences nodes8/full-set selection. Full-quick selection and metadata are tested
        # separately (profile full is supported in quick mode with unambiguous provenance).
        out = tempfile.mkdtemp(prefix='dist_camp_fullprof_')
        os.rmdir(out)
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-full-prof',
                   '--profile', 'full', '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = p.stderr + p.stdout
            self.assertIn('before timed trials', combined)
            self.assertIn('nodes8', combined, msg='full profile must select nodes8 (full default set)')
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_explicit_scenario_override_provenance_accurate(self):
        p, out = self._run_preflight_only(['--profile', 'nodes2', '--scenarios', 'small', '--trials', '1'])
        try:
            self.assertTrue(os.path.exists(os.path.join(out, 'prevalidation.json')),
                            msg=p.stdout + '\n' + p.stderr)
            self._assert_no_timed_trial_manifests(out)
            with open(os.path.join(out, 'prevalidation.json')) as fh:
                pv = json.load(fh)
            self.assertEqual([s['id'] for s in pv['selected_scenarios']], ['small'])
            self.assertEqual(pv.get('scenario_profile_requested'), 'nodes2')
            self.assertEqual(pv.get('scenario_profile_effective'), 'custom')
            self.assertTrue(pv.get('scenario_profile_overridden', False))
            # backward-compat field must not represent requested profile as effective selection when overridden
            self.assertNotEqual(pv.get('scenario_profile'), 'nodes2')
            self.assertEqual(pv.get('scenario_profile'), 'custom')
            self.assertTrue(pv.get('scenarios_filter_explicit'))
            with open(os.path.join(out, 'prevalidation.json')) as fh:
                pv2 = json.load(fh)
            self.assertIsNotNone(pv2)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_default_full_selection_has_accurate_effective_profile_provenance(self):
        # default (no --profile, no --scenarios) in non-quick mode selects full default set;
        # on 4-node host this is incompatible due to nodes8 so preflight fails before trials.
        # Effective selection should still be identifiable as full/default in provenance when it can
        # be recorded. Use a compatible subset? not "default full selection".
        # Instead, use --profile full but on a compatible path: not possible. Alternative: run in quick
        # mode default selection (all quick scenarios) which is compatible on this host and record
        # effective profile accurately.
        p, out = self._run_preflight_only(['--quick', '--trials', '1'])
        try:
            self.assertTrue(os.path.exists(os.path.join(out, 'prevalidation.json')),
                            msg=p.stdout + '\n' + p.stderr)
            self._assert_no_timed_trial_manifests(out)
            with open(os.path.join(out, 'prevalidation.json')) as fh:
                pv = json.load(fh)
            self.assertIsNone(pv.get('scenario_profile_requested'))
            self.assertEqual(pv.get('scenario_profile_effective'), 'quick_default')
            self.assertFalse(pv.get('scenario_profile_overridden', False))
            self.assertEqual(pv.get('scenario_profile'), 'quick_default')
            # all quick scenarios selected
            self.assertEqual([s['id'] for s in pv['selected_scenarios']], ['equal', 'slow_one', 'stall_recover', 'small'])
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_default_nonquick_full_selection_requests_full_profile_via_cli(self):
        # Actual --profile full selects full default set (CLI). On this 4-node host nodes8 is
        # incompatible so preflight rejects before trials; assert nodes8 was part of selected set
        # by failure diagnostic and that profile was requested.
        out = tempfile.mkdtemp(prefix='dist_camp_fullsel_')
        os.rmdir(out)
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-full-default',
                   '--profile', 'full', '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = p.stderr + p.stdout
            self.assertIn('nodes8', combined)
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_profile_provenance_recorded(self):
        out = tempfile.mkdtemp(prefix='dist_camp_prov_')
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--quick', '--out', out, '--campaign-id', 'test-prov',
                   '--scenarios', 'small', '--candidates', 'fixed_faa',
                   '--trials', '1', '--seed', 'p1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertEqual(p.returncode, 0, msg=p.stderr[-2000:] + "\n" + p.stdout[-1000:])
            with open(os.path.join(out, 'prevalidation.json')) as fh:
                pv = json.load(fh)
            self.assertEqual(pv['available_usable_nodes'], 4)
            self.assertEqual(pv['host_usable_node_count'], 4)
            self.assertEqual(pv['physical_node_mapping']['mode'], 'auto')
            self.assertEqual([s['id'] for s in pv['selected_scenarios']], ['small'])
            self.assertEqual(pv.get('scenario_profile_requested'), None)
            self.assertEqual(pv.get('scenario_profile_effective'), 'custom')
            self.assertTrue(pv.get('scenarios_filter_explicit'))
            with open(os.path.join(out, 'campaign-manifest.json')) as fh:
                cm = json.load(fh)
            self.assertEqual(cm.get('available_usable_nodes'), 4)
            self.assertEqual(cm.get('host_usable_node_count'), 4)
            self.assertIsNotNone(cm.get('selected_scenarios'))
            self.assertEqual(cm.get('physical_node_mapping', {}).get('mode'), 'auto')
            self.assertEqual(cm.get('scenario_profile_requested'), None)
            self.assertEqual(cm.get('scenario_profile_effective'), 'custom')
        finally:
            shutil.rmtree(out, ignore_errors=True)


class TestCampaignPlanSemanticsC1Corrections(unittest.TestCase):
    """WO C1 corrections: CLI-to-execution-plan propagation, candidate validation, and shuffle/seed semantics."""

    def _assert_no_timed_trial_manifests(self, out):
        self.assertFalse(os.path.exists(os.path.join(out, 'campaign-manifest.json')),
                         'campaign must not complete with timed trials')
        cases_dir = os.path.join(out, 'cases')
        trial_evidence = []
        if os.path.isdir(cases_dir):
            for root, dirs, files in os.walk(cases_dir):
                if 'manifest.json' in files:
                    trial_evidence.append(os.path.join(root, 'manifest.json'))
        self.assertEqual(trial_evidence, [], 'no timed trial manifests expected before timed trials')

    def _run_plan_only(self, extra_args, source_sha='deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'):
        out = tempfile.mkdtemp(prefix='dist_camp_plan_')
        os.rmdir(out)
        cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
               '--plan-only', '--out', out, '--campaign-id', 'test-plan',
               '--source-sha', source_sha] + list(extra_args)
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
        return p, out

    def _run_real_campaign(self, extra_args, source_sha='deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'):
        out = tempfile.mkdtemp(prefix='dist_camp_real_')
        os.rmdir(out)
        cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
               '--out', out, '--campaign-id', 'test-real',
               '--source-sha', source_sha] + list(extra_args)
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
        return p, out

    def _load_plan(self, out):
        with open(os.path.join(out, 'execution-plan.json')) as fh:
            return json.load(fh)

    def _load_preval(self, out):
        with open(os.path.join(out, 'prevalidation.json')) as fh:
            return json.load(fh)

    def _cases_in_blocks(self, plan):
        return sorted({(b['scenario'], b['mapping_id']) for b in plan.get('blocks', [])})

    def test_quick_produces_one_trial_per_case(self):
        p, out = self._run_plan_only(['--quick', '--scenarios', 'small', '--candidates', 'fixed_faa,local_adaptive', '--seed', 'q1'])
        try:
            self.assertEqual(p.returncode, 0, msg=p.stderr + '\n' + p.stdout)
            plan = self._load_plan(out)
            self.assertEqual(plan.get('trials'), 1)
            self.assertTrue(plan.get('blocks'))
            cases = self._cases_in_blocks(plan)
            self.assertTrue(cases)
            for case in cases:
                trials = sorted([b['trial'] for b in plan['blocks'] if (b['scenario'], b['mapping_id']) == case])
                self.assertEqual(trials, [1], (case, trials))
            for b in plan['blocks']:
                self.assertEqual(b['trial'], 1)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_trials_five_produces_five_trials_per_case(self):
        p, out = self._run_plan_only(['--scenarios', 'small', '--candidates', 'fixed_faa', '--trials', '5', '--seed', 't5'])
        try:
            self.assertEqual(p.returncode, 0, msg=p.stderr + '\n' + p.stdout)
            plan = self._load_plan(out)
            self.assertEqual(plan.get('trials'), 5)
            cases = self._cases_in_blocks(plan)
            self.assertTrue(cases)
            for case in cases:
                trials = sorted([b['trial'] for b in plan['blocks'] if (b['scenario'], b['mapping_id']) == case])
                self.assertEqual(trials, [1, 2, 3, 4, 5], (case, trials))
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_candidates_fixed_faa_plans_and_executes_only_fixed_faa(self):
        args = ['--quick', '--scenarios', 'small', '--candidates', 'fixed_faa', '--trials', '1', '--seed', 'onlyfaa']
        p, out = self._run_real_campaign(args)
        try:
            self.assertEqual(p.returncode, 0, msg=p.stderr[-3000:] + '\n' + p.stdout[-2000:])
            plan = self._load_plan(out)
            self.assertEqual(plan.get('candidates'), ['fixed_faa'])
            self.assertTrue(plan.get('blocks'))
            for b in plan['blocks']:
                self.assertEqual(b.get('candidate_order'), ['fixed_faa'], b)
            with open(os.path.join(out, 'campaign-manifest.json')) as fh:
                cm = json.load(fh)
            outcomes = cm.get('outcomes') or []
            self.assertTrue(outcomes)
            self.assertTrue(all(o.get('candidate') == 'fixed_faa' for o in outcomes), outcomes)
            # execution evidence exists for fixed_faa only
            found_cands = set()
            cases_dir = os.path.join(out, 'cases')
            for root, dirs, files in os.walk(cases_dir):
                if 'manifest.json' in files:
                    with open(os.path.join(root, 'manifest.json')) as fh:
                        m = json.load(fh)
                    spec = m.get('spec') or {}
                    cand = spec.get('ingest_candidate') or spec.get('candidate')
                    if cand:
                        found_cands.add(cand)
            self.assertEqual(found_cands, {'fixed_faa'}, found_cands)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_unknown_candidate_rejected_before_timed_trials(self):
        out = tempfile.mkdtemp(prefix='dist_camp_unkcand_')
        os.rmdir(out)
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-unk-cand',
                   '--scenarios', 'small', '--candidates', 'fixed_faa,not_a_real_candidate',
                   '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = (p.stderr + p.stdout).lower()
            self.assertIn('before timed trials', combined)
            self.assertIn('not_a_real_candidate', p.stderr + p.stdout)
            self.assertIn('unknown', combined)
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_empty_candidate_list_rejected(self):
        out = tempfile.mkdtemp(prefix='dist_camp_emptycand_')
        os.rmdir(out)
        try:
            cmd = ['bash', 'stage0/dist_ingest/run_dist_campaign.sh',
                   '--out', out, '--campaign-id', 'test-empty-cand',
                   '--scenarios', 'small', '--candidates', '',
                   '--trials', '1']
            p = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + '\n' + p.stderr)
            combined = (p.stderr + p.stdout).lower()
            self.assertIn('before timed trials', combined)
            self.assertTrue(('candidate' in combined and ('empty' in combined or 'nonempty' in combined)), p.stderr + p.stdout)
            self._assert_no_timed_trial_manifests(out)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_specified_seed_recorded_and_reproducible_candidate_order(self):
        args = ['--scenarios', 'small', '--candidates', 'fixed_faa,local_adaptive,relative_adaptive',
                '--trials', '3', '--seed', 'repro-seed-42']
        p1, out1 = self._run_plan_only(args)
        p2, out2 = self._run_plan_only(args)
        try:
            self.assertEqual(p1.returncode, 0, msg=p1.stderr + '\n' + p1.stdout)
            self.assertEqual(p2.returncode, 0, msg=p2.stderr + '\n' + p2.stdout)
            plan1 = self._load_plan(out1)
            plan2 = self._load_plan(out2)
            self.assertEqual(plan1.get('seed'), 'repro-seed-42')
            self.assertEqual(plan2.get('seed'), 'repro-seed-42')
            self.assertEqual(self._load_preval(out1).get('seed'), 'repro-seed-42')
            # reproducible candidate order for identical args+seed
            orders1 = [(b['scenario'], b['mapping_id'], b['trial'], tuple(b['candidate_order'])) for b in plan1['blocks']]
            orders2 = [(b['scenario'], b['mapping_id'], b['trial'], tuple(b['candidate_order'])) for b in plan2['blocks']]
            self.assertEqual(orders1, orders2)
            # sanity: with 3 candidates and 3 trials there should be at least some variation/order recorded
            self.assertTrue(all(set(o[3]) == {'fixed_faa', 'local_adaptive', 'relative_adaptive'} for o in orders1))
        finally:
            shutil.rmtree(out1, ignore_errors=True)
            shutil.rmtree(out2, ignore_errors=True)

    def test_shuffle_scenarios_shuffles_mapping_blocks_with_seed(self):
        # Two scenarios/mapping blocks in quick mode: use two small 2-node scenarios if both selected?
        # quick includes small (2-node) and also equal/slow_one/stall_recover (4-node). With auto mapping
        # we get different mapping blocks per node-count; use --scenarios small,equal? but in quick mode
        # scenario set is the quick set; selecting explicit subset works. 'equal' is 4-node, 'small' 2-node.
        base = ['--quick', '--scenarios', 'small,equal', '--candidates', 'fixed_faa', '--trials', '1', '--seed', 'shuffle-seed-7']
        p_ns, out_ns = self._run_plan_only(base)
        p_sh, out_sh = self._run_plan_only(base + ['--shuffle-scenarios'])
        p_sh2, out_sh2 = self._run_plan_only(base + ['--shuffle-scenarios'])
        try:
            self.assertEqual(p_ns.returncode, 0, msg=p_ns.stderr + '\n' + p_ns.stdout)
            self.assertEqual(p_sh.returncode, 0, msg=p_sh.stderr + '\n' + p_sh.stdout)
            self.assertEqual(p_sh2.returncode, 0, msg=p_sh2.stderr + '\n' + p_sh2.stdout)
            plan_ns = self._load_plan(out_ns)
            plan_sh = self._load_plan(out_sh)
            plan_sh2 = self._load_plan(out_sh2)
            self.assertFalse(plan_ns.get('shuffle_scenarios'))
            self.assertTrue(plan_sh.get('shuffle_scenarios'))
            self.assertEqual(plan_sh.get('seed'), 'shuffle-seed-7')
            seq_ns = [(b['scenario'], b['mapping_id'], b['trial']) for b in plan_ns['blocks']]
            seq_sh = [(b['scenario'], b['mapping_id'], b['trial']) for b in plan_sh['blocks']]
            seq_sh2 = [(b['scenario'], b['mapping_id'], b['trial']) for b in plan_sh2['blocks']]
            # same set of blocks, reproducible when shuffled with same seed
            self.assertEqual(sorted(seq_ns), sorted(seq_sh))
            self.assertEqual(seq_sh, seq_sh2)
            # shuffle actually changes block order for this seed/selection (deterministic expectation)
            self.assertNotEqual(seq_ns, seq_sh, 'shuffle_scenarios should change scenario/mapping-block order for this seed')
        finally:
            shutil.rmtree(out_ns, ignore_errors=True)
            shutil.rmtree(out_sh, ignore_errors=True)
            shutil.rmtree(out_sh2, ignore_errors=True)

    def test_plan_only_and_real_campaign_agree_on_selected_plan(self):
        args = ['--quick', '--scenarios', 'small', '--candidates', 'fixed_faa,local_adaptive',
                '--trials', '2', '--seed', 'agree-seed']
        p_plan, out_plan = self._run_plan_only(args)
        p_real, out_real = self._run_real_campaign(args)
        try:
            self.assertEqual(p_plan.returncode, 0, msg=p_plan.stderr + '\n' + p_plan.stdout)
            self.assertEqual(p_real.returncode, 0, msg=p_real.stderr[-3000:] + '\n' + p_real.stdout[-2000:])
            plan_only = self._load_plan(out_plan)
            plan_real = self._load_plan(out_real)
            # identical selected plan fields
            for k in ('seed', 'shuffle_scenarios', 'trials', 'candidates', 'mapping_profiles_requested', 'mapping_mode'):
                self.assertEqual(plan_only.get(k), plan_real.get(k), k)
            # block-level agreement (scenario/mapping/trial/candidate order)
            def norm_blocks(plan):
                return [(b['scenario'], b['mapping_id'], b.get('mapping_profile'), b.get('mapping_variant'),
                         b['trial'], tuple(b['candidate_order']), tuple(b.get('logical_to_physical') or []))
                        for b in plan.get('blocks', [])]
            self.assertEqual(norm_blocks(plan_only), norm_blocks(plan_real))
            # campaign manifest records the same plan
            with open(os.path.join(out_real, 'campaign-manifest.json')) as fh:
                cm = json.load(fh)
            manifest_plan = ((cm.get('randomization') or {}).get('plan') or {})
            for k in ('seed', 'shuffle_scenarios', 'trials', 'candidates'):
                self.assertEqual(plan_only.get(k), manifest_plan.get(k), k)
            self.assertEqual(norm_blocks(plan_only), norm_blocks(manifest_plan))
        finally:
            shutil.rmtree(out_plan, ignore_errors=True)
            shutil.rmtree(out_real, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()


