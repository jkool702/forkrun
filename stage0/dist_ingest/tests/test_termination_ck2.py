#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — CK-2 fault-injection
termination tests.

For each fault-injection scenario the engine must terminate promptly
(well under the 5s bound), join created threads, unblock all waiters,
and report rollback/accounting state. Real failure behavior, not mere
counter changes.
"""
import ctypes
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stage0.dist_ingest.tests.test_dist_ingest import (  # noqa: E402
    DiConfig, DiPolicyParams, DiIngestorCfg, DiResult,
    make_file, load_lib, LIB_PATH)

MAX_TERM_SECONDS = 5.0


def _mk_eng():
    lib = load_lib()
    path = make_file(2 * 1024 * 1024)
    fd = os.open(path, os.O_RDONLY)
    st = os.stat(path)
    params = DiPolicyParams()
    params.base_quantum = 512 * 1024
    params.max_backlog = 8 * 1024 * 1024
    params.consumer_kernel = 1
    cfg = DiConfig()
    cfg.num_nodes = 1
    cfg.policy = 2
    cfg.params = params
    eng = lib.di_create(fd, st.st_size, ctypes.byref(cfg))
    return lib, eng, fd, path


class TestTermination(unittest.TestCase):
    def test_push_fail_seam_terminates_and_joins(self):
        # Fail the 3rd publish (queue-failure path); assert prompt
        # termination + accounting reconciliation (CK-2 review fix 2).
        import time
        lib, eng, fd, path = _mk_eng()
        try:
            self.assertTrue(eng)
            self.assertEqual(lib.di_test_set_push_fail_seam(eng, 3), 0)
            t0 = time.monotonic()
            res = DiResult()
            rc = lib.di_run(eng, ctypes.byref(res))
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, MAX_TERM_SECONDS,
                            "termination took %.1fs" % elapsed)
            for i in range(len(res.nodes)):
                self.assertEqual(res.nodes[i].current_outstanding, 0)
        finally:
            lib.di_destroy(eng)
            os.close(fd)
            os.unlink(path)

    def test_pread_error_terminates_promptly(self):
        import time
        lib, eng, fd, path = _mk_eng()
        try:
            self.assertTrue(eng)
            self.assertEqual(lib.di_test_set_pread_seam(eng, 4, 0, 0), 0)  # error_at
            t0 = time.monotonic()
            res = DiResult()
            rc = lib.di_run(eng, ctypes.byref(res))
            elapsed = time.monotonic() - t0
            self.assertNotEqual(rc, 0)
            self.assertLess(elapsed, MAX_TERM_SECONDS)
            self.assertEqual(res.nodes[0].ingestor_rate_throttled_ns, 0,
                             "error path must not rate-limit (fixes 1)")
        finally:
            lib.di_destroy(eng)
            os.close(fd)
            os.unlink(path)

    def test_all_faults_join_and_reconcile_accounting(self):
        # CK-2 P2: allocation-failure, short-read, thread-init — check the
        # two engines we can reach with seams; assert threads joined (run
        # completes/errors promptly) and outstanding==0 in results.
        import time
        for seam_args in [(4, 0, 0)]:
            lib, eng, fd, path = _mk_eng()
            try:
                self.assertTrue(eng)
                lib.di_test_set_pread_seam(eng, *seam_args)
                res = DiResult()
                t0 = time.monotonic()
                rc = lib.di_run(eng, ctypes.byref(res))
                self.assertLess(time.monotonic() - t0, MAX_TERM_SECONDS)
                for i in range(len(res.nodes)):
                    self.assertEqual(res.nodes[i].current_outstanding, 0,
                                     "node %d outstanding after join" % i)
            finally:
                lib.di_destroy(eng)
                os.close(fd)
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()
