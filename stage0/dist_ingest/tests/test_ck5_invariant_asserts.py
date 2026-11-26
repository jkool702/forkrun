#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 — CK-5.

Invariant checking contract (see CK5_INVARIANTS.md):

  - runtime `P.invariant_asserts` activates invariant checking in an ordinary build;
  - a build compiled with `-DDI_INVARIANT_ASSERT` forces checking on regardless
    of the runtime flag;
  - both modes run the SAME underlying checks;
  - no unconditional `|| 1`;
  - the publication checker runs BEFORE publication admission, does not
    relock a mutex already held, returns a meaningful status, has its return
    value propagated, prevents invalid publication, takes an error/stop path,
    and preserves ownership + reservation rollback;
  - after all threads are joined, outstanding reservations are reconciled on
    normal completion AND injected-failure paths; original engine error is
    preserved; additional accounting/invariant failure is reported accurately.

A deliberately malformed chunk exercises the ACTUAL publication validation/
error path (narrow seam corrupts a by-value copy; underlying allocation
ownership is preserved).
"""
import ctypes, os, shutil, subprocess, sys, tempfile, time, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from stage0.dist_ingest.tests.test_dist_ingest import (  # noqa: E402
    DiConfig, DiPolicyParams, DiConsumerCfg, DiResult, DiIngestorCfg,
    DiNodeMetrics, make_file, load_lib, LIB_PATH)

DI_ERR_INVARIANT = -6
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DIST_DIR = os.path.join(REPO, "stage0", "dist_ingest")

# publication-seam modes (mirror dist_ingest.c)
PUBLISH_SEAM_NULL_BUF = 1
PUBLISH_SEAM_ZERO_LEN = 2
PUBLISH_SEAM_UNMATERIALIZED = 3


def _mk_eng(lib, invariant_asserts=1, size=2 * 1024 * 1024):
    path = make_file(size)
    fd = os.open(path, os.O_RDONLY)
    st = os.stat(path)
    p = DiPolicyParams()
    p.base_quantum = 512 * 1024
    p.max_backlog = 8 * 1024 * 1024
    p.consumer_kernel = 1
    p.invariant_asserts = invariant_asserts
    cfg = DiConfig()
    cfg.num_nodes = 1
    cfg.policy = 2
    cfg.params = p
    eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
    assert eng, "engine creation failed"
    return eng, fd, path


def _run(lib, eng):
    res = DiResult()
    t0 = time.monotonic()
    rc = lib.di_run(eng, ctypes.byref(res))
    elapsed = time.monotonic() - t0
    return rc, res, elapsed


def _assert_reconciled(test, res):
    for i in range(res.num_nodes):
        n = res.nodes[i]
        test.assertEqual(n.current_outstanding, 0, "node %d outstanding != 0" % i)
        test.assertEqual(n.current_published_backlog, 0, "node %d published != 0" % i)
        test.assertEqual(n.current_consumer_inflight_backlog, 0, "node %d inflight != 0" % i)
        test.assertEqual(n.current_effective_backlog, 0, "node %d effective != 0" % i)
        test.assertEqual(n.accounting_violation, 0, "node %d accounting_violation" % i)
    test.assertEqual(res.invariant_failed, 0, "invariant_failed flag set")
    test.assertEqual(res.accounting_failed, 0, "accounting_failed flag set")


class TestCK5Activation(unittest.TestCase):
    def test_ordinary_runtime_enabled_checking_works(self):
        lib = load_lib()
        eng, fd, path = _mk_eng(lib, invariant_asserts=1)
        try:
            rc, res, elapsed = _run(lib, eng)
            self.assertLess(elapsed, 10.0)
            self.assertEqual(rc, 0)
            _assert_reconciled(self, res)
        finally:
            lib.di_destroy(eng); os.close(fd); os.unlink(path)

    def test_compile_time_assertion_mode_forces_on(self):
        # build a separate shared object with -DDI_INVARIANT_ASSERT
        tmp = tempfile.mkdtemp(prefix="di_invassert_")
        so = os.path.join(tmp, "libdist_ingest_invassert.so")
        cc = os.environ.get("CC", "cc")
        cmd = [cc, "-O1", "-g", "-fPIC", "-pthread", "-Wall", "-Wextra",
               "-Wno-unused-parameter", "-DDI_INVARIANT_ASSERT",
               "-o", so, os.path.join(DIST_DIR, "dist_ingest.c"), "-shared", "-pthread"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(so))
        lib = ctypes.CDLL(so)
        lib.di_create.argtypes = [ctypes.c_int, ctypes.c_uint64, ctypes.POINTER(DiConfig)]
        lib.di_create.restype = ctypes.c_void_p
        lib.di_destroy.argtypes = [ctypes.c_void_p]; lib.di_destroy.restype = None
        lib.di_run.argtypes = [ctypes.c_void_p, ctypes.POINTER(DiResult)]; lib.di_run.restype = ctypes.c_int
        lib.di_test_set_publish_seam.argtypes = [ctypes.c_void_p, ctypes.c_int]; lib.di_test_set_publish_seam.restype = ctypes.c_int
        lib.di_test_publish_seam_fired.argtypes = [ctypes.c_void_p]; lib.di_test_publish_seam_fired.restype = ctypes.c_int
        try:
            # runtime flag explicitly OFF; compile-time mode must still check
            eng, fd, path = _mk_eng(lib, invariant_asserts=0)
            try:
                # valid chunk passes in compile-time mode
                rc, res, _ = _run(lib, eng)
                self.assertEqual(rc, 0)
                _assert_reconciled(self, res)
            finally:
                lib.di_destroy(eng); os.close(fd); os.unlink(path)
            # invalid chunk rejected in compile-time mode even with runtime flag=0
            eng, fd, path = _mk_eng(lib, invariant_asserts=0)
            try:
                self.assertEqual(lib.di_test_set_publish_seam(eng, PUBLISH_SEAM_NULL_BUF), 0)
                rc, res, elapsed = _run(lib, eng)
                self.assertNotEqual(rc, 0, "malformed chunk must fail in compile-time mode")
                self.assertTrue(lib.di_test_publish_seam_fired(eng), "publish seam must fire")
                self.assertLess(elapsed, 10.0, "no deadlock")
            finally:
                lib.di_destroy(eng); os.close(fd); os.unlink(path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_valid_chunk_passes(self):
        lib = load_lib()
        eng, fd, path = _mk_eng(lib, invariant_asserts=1)
        try:
            rc, res, _ = _run(lib, eng)
            self.assertEqual(rc, 0)
            self.assertGreater(res.total_published, 0)
            self.assertEqual(res.total_published, res.total_consumed)
            _assert_reconciled(self, res)
        finally:
            lib.di_destroy(eng); os.close(fd); os.unlink(path)


class TestCK5MalformedChunk(unittest.TestCase):
    def _run_malformed(self, seam_mode):
        lib = load_lib()
        eng, fd, path = _mk_eng(lib, invariant_asserts=1)
        try:
            self.assertEqual(lib.di_test_set_publish_seam(eng, seam_mode), 0)
            rc, res, elapsed = _run(lib, eng)
            return lib, eng, fd, path, rc, res, elapsed
        except Exception:
            lib.di_destroy(eng); os.close(fd); os.unlink(path)
            raise

    def _check_malformed(self, seam_mode):
        lib, eng, fd, path, rc, res, elapsed = self._run_malformed(seam_mode)
        try:
            # injection fired, on the actual publication path
            self.assertTrue(lib.di_test_publish_seam_fired(eng), "publish seam must fire")
            # engine takes an appropriate error/stop path
            self.assertNotEqual(rc, 0, "malformed chunk must not yield success")
            # no deadlock; engine terminated and JOINED its threads (di_run returned)
            self.assertLess(elapsed, 10.0, "no deadlock; threads joined")
            # invalid chunk NOT published (not committed to queue; nothing published/consumed)
            self.assertEqual(res.nodes[0].chunks_published, 0, "malformed chunk must not be published")
            self.assertEqual(res.total_published, 0, "malformed chunk must not be published")
            self.assertEqual(res.total_consumed, 0, "malformed chunk must not be consumed")
            # reserved bytes + other accounting reconciled after join
            self.assertEqual(res.nodes[0].current_outstanding, 0, "outstanding rolled back")
            self.assertEqual(res.nodes[0].current_published_backlog, 0, "no dangling published backlog")
            self.assertEqual(res.nodes[0].current_consumer_inflight_backlog, 0, "no dangling inflight")
            self.assertEqual(res.nodes[0].current_effective_backlog, 0)
            self.assertEqual(res.nodes[0].accounting_violation, 0, "no accounting violation recorded")
        finally:
            lib.di_destroy(eng); os.close(fd); os.unlink(path)

    def test_null_buffer_chunk_rejected_not_published(self):
        self._check_malformed(PUBLISH_SEAM_NULL_BUF)

    def test_zero_length_chunk_rejected_not_published(self):
        self._check_malformed(PUBLISH_SEAM_ZERO_LEN)

    def test_unmaterialized_chunk_rejected_not_published(self):
        self._check_malformed(PUBLISH_SEAM_UNMATERIALIZED)


class TestCK5NormalCompletion(unittest.TestCase):
    def test_normal_completion_success_outstanding_zero(self):
        lib = load_lib()
        eng, fd, path = _mk_eng(lib, invariant_asserts=1)
        try:
            rc, res, elapsed = _run(lib, eng)
            self.assertLess(elapsed, 10.0)
            self.assertEqual(rc, 0)
            self.assertEqual(res.total_consumed, 2 * 1024 * 1024)
            _assert_reconciled(self, res)
        finally:
            lib.di_destroy(eng); os.close(fd); os.unlink(path)


if __name__ == "__main__":
    unittest.main()
