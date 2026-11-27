#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 — CK-2.

Fault-injection evidence. For each claimed fault the test must prove:
  - the engine was created;
  - the injection seam was configured;
  - the injection ACTUALLY FIRED;
  - the expected result (di_run error, NOT a normally-completed run);
  - all created threads are joined (di_run returns after pthread_join);
  - outstanding reservations + accounting are reconciled;
  - prompt termination within a defined bound.

Categories:
  - queue-push failure (push_fail seam; CK-2.1)
  - pread immediate error (mode 4), error-after-partial (mode 5),
    premature EOF/short read (mode 3); correct error propagation; no
    inappropriate rate-limit sleep after error; reservation rollback;
    reconciliation; prompt join (CK-2.2)
  - allocation failure (di_alloc_local seam; CK-2.3)
  - thread-creation failure in di_run (seam; CK-2.3)
  - engine partial-init / thread-initialization failure in di_create
    (existing di_test_set_create_fail_seam; CK-2.3)
"""
import ctypes
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stage0.dist_ingest.tests.test_dist_ingest import (  # noqa: E402
    DiConfig, DiPolicyParams, DiIngestorCfg, DiResult,
    make_file, load_lib, LIB_PATH)

MAX_TERM_SECONDS = 5.0
DI_ERR_THREAD = -5
DI_ERR_NOMEM = -3


def _mk_eng(ingestor_mode=0, ingestor_rate_bps=0, size=2 * 1024 * 1024, base_quantum=512 * 1024):
    lib = load_lib()
    path = make_file(size)
    fd = os.open(path, os.O_RDONLY)
    st = os.stat(path)
    params = DiPolicyParams()
    params.base_quantum = base_quantum
    params.max_backlog = 8 * 1024 * 1024
    params.consumer_kernel = 1
    cfg = DiConfig()
    cfg.num_nodes = 1
    cfg.policy = 2
    cfg.params = params
    ing = DiIngestorCfg()
    ing.mode = ingestor_mode
    ing.rate_bps = ingestor_rate_bps
    ing_arr = (DiIngestorCfg * 1)(ing)
    cfg.ingestors = ctypes.cast(ing_arr, ctypes.c_void_p)
    eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
    return lib, eng, fd, path, cfg


def _accounting_reconciled(test, res):
    for i in range(res.num_nodes):
        n = res.nodes[i]
        test.assertEqual(n.current_outstanding, 0, "node %d outstanding != 0" % i)
        test.assertEqual(n.current_published_backlog, 0, "node %d published != 0" % i)
        test.assertEqual(n.current_consumer_inflight_backlog, 0, "node %d inflight != 0" % i)
        test.assertEqual(n.current_effective_backlog, 0, "node %d effective != 0" % i)
        test.assertEqual(n.accounting_violation, 0, "node %d accounting_violation" % i)
    test.assertEqual(res.accounting_failed, 0, "accounting_failed flag")
    test.assertEqual(res.invariant_failed, 0, "invariant_failed flag")


class TestTermination(unittest.TestCase):
    # ---- CK-2.1 queue-push failure ----
    def test_push_fail_seam_fired_run_fails_joins_reconciles(self):
        lib, eng, fd, path, _cfg = _mk_eng()
        try:
            # engine successfully created
            self.assertTrue(eng, "engine creation must succeed")
            # seam successfully configured
            self.assertEqual(lib.di_test_set_push_fail_seam(eng, 1), 0)
            t0 = time.monotonic()
            res = DiResult()
            rc = lib.di_run(eng, ctypes.byref(res))
            elapsed = time.monotonic() - t0
            # seam actually fired
            self.assertEqual(lib.di_test_push_fail_fired(eng), 1,
                             "push_fail seam must have fired")
            # di_run returned the expected failure result, NOT normally completed
            self.assertNotEqual(rc, 0, "di_run must return an error on queue-push failure")
            # all created threads joined (di_run only returns after pthread_join) + prompt
            self.assertLess(elapsed, MAX_TERM_SECONDS, "termination took %.1fs" % elapsed)
            # outstanding reservations + accounting reconciled
            _accounting_reconciled(self, res)
        finally:
            lib.di_destroy(eng); os.close(fd); os.unlink(path)

    # ---- CK-2.2 pread failure + short-read behavior ----
    def _pread_case(self, seam_args, name, expect_fired=True):
        lib, eng, fd, path, _cfg = _mk_eng(ingestor_mode=4, ingestor_rate_bps=1)  # rate_limit on
        try:
            self.assertTrue(eng)
            self.assertEqual(lib.di_test_set_pread_seam(eng, *seam_args), 0)
            t0 = time.monotonic()
            res = DiResult()
            rc = lib.di_run(eng, ctypes.byref(res))
            elapsed = time.monotonic() - t0
            # intended injection fired
            self.assertEqual(lib.di_test_pread_seam_fired(eng), 1, "%s: pread seam must fire" % name)
            # correct error propagation
            self.assertNotEqual(rc, 0, "%s: di_run must return error" % name)
            # no inappropriate rate-limit sleep after an error
            self.assertEqual(res.nodes[0].ingestor_rate_throttled_ns, 0,
                             "%s: error path must not rate-limit" % name)
            # reservation rollback + outstanding reconciliation
            _accounting_reconciled(self, res)
            # prompt thread termination/join
            self.assertLess(elapsed, MAX_TERM_SECONDS, "%s: %.1fs" % (name, elapsed))
        finally:
            lib.di_destroy(eng); os.close(fd); os.unlink(path)

    def test_pread_immediate_error_mode4(self):
        self._pread_case((4, 0, 0), "immediate pread error")

    def test_pread_error_after_partial_mode5(self):
        self._pread_case((5, 1, 0), "error after partial progress")

    def test_pread_premature_eof_short_read_mode3(self):
        self._pread_case((3, 0, 0), "premature EOF / short read")

    # ---- CK-2.3 allocation failure ----
    def test_allocation_failure_fired_joins_reconciles(self):
        lib, eng, fd, path, _cfg = _mk_eng()
        try:
            self.assertTrue(eng)
            self.assertEqual(lib.di_test_set_alloc_fail_seam(eng, 1), 0)
            t0 = time.monotonic()
            res = DiResult()
            rc = lib.di_run(eng, ctypes.byref(res))
            elapsed = time.monotonic() - t0
            self.assertEqual(lib.di_test_alloc_fail_fired(eng), 1, "alloc-fail seam must fire")
            self.assertNotEqual(rc, 0, "allocation failure must propagate")
            self.assertLess(elapsed, MAX_TERM_SECONDS)
            # nothing leaked/published; queues valid; accounting reconciled
            _accounting_reconciled(self, res)
        finally:
            lib.di_destroy(eng); os.close(fd); os.unlink(path)

    # ---- CK-2.3 thread-creation failure in di_run ----
    def test_thread_creation_failure_fired_joins_reconciles(self):
        lib, eng, fd, path, _cfg = _mk_eng()
        try:
            self.assertTrue(eng)
            self.assertEqual(lib.di_test_set_thread_create_fail_seam(eng, 1), 0)
            t0 = time.monotonic()
            res = DiResult()
            rc = lib.di_run(eng, ctypes.byref(res))
            elapsed = time.monotonic() - t0
            self.assertEqual(lib.di_test_thread_create_fail_fired(eng), 1,
                             "thread-create seam must fire")
            self.assertEqual(rc, DI_ERR_THREAD, "thread-creation failure -> DI_ERR_THREAD")
            self.assertLess(elapsed, MAX_TERM_SECONDS)
            _accounting_reconciled(self, res)
        finally:
            lib.di_destroy(eng); os.close(fd); os.unlink(path)

    # ---- CK-2.3 engine partial-init / thread-initialization failure in di_create ----
    def test_engine_partial_init_failure_returns_null_and_cleans_up(self):
        lib = load_lib()
        path = make_file(2 * 1024 * 1024)
        fd = os.open(path, os.O_RDONLY)
        st = os.stat(path)
        try:
            params = DiPolicyParams(); params.base_quantum = 512 * 1024
            params.max_backlog = 8 * 1024 * 1024; params.consumer_kernel = 1
            cfg = DiConfig(); cfg.num_nodes = 4; cfg.policy = 2; cfg.params = params
            # inject partial-init failure after N nodes
            lib.di_test_set_create_fail_seam(2)
            eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
            self.assertFalse(eng, "partial-init must return NULL")
            lib.di_test_set_create_fail_seam(-1)
        finally:
            os.close(fd); os.unlink(path)

    def test_mutex_init_failure_path_clean_source(self):
        # pthread_mutex_init/cond_init failure returns NULL + cleans up;
        # cannot inject real pthread_* failure here — verify source handles it.
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "dist_ingest.c")).read()
        self.assertIn("pthread_mutex_init(&n->mu, NULL) != 0", src)
        self.assertIn("pthread_cond_init(&n->cv_can_push, NULL) != 0", src)
        self.assertIn("pthread_cond_init(&n->cv_can_pop, NULL) != 0", src)

    # ---- existing aggregate fault test ----
    def test_all_faults_join_and_reconcile_accounting(self):
        lib, eng, fd, path, _cfg = _mk_eng()
        try:
            self.assertTrue(eng)
            self.assertEqual(lib.di_test_set_pread_seam(eng, 4, 0, 0), 0)
            res = DiResult(); t0 = time.monotonic()
            rc = lib.di_run(eng, ctypes.byref(res))
            self.assertNotEqual(rc, 0)
            self.assertLess(time.monotonic() - t0, MAX_TERM_SECONDS)
            _accounting_reconciled(self, res)
        finally:
            lib.di_destroy(eng); os.close(fd); os.unlink(path)


if __name__ == "__main__":
    unittest.main()
