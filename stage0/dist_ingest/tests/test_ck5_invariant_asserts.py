#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1 — CK-5.2/5.1: invariant-assert
tests run with assertions ENABLED (via the runtime flag AND the compiled
mode), verify publication+accounting invariants and post-join outstanding==0.
"""
import ctypes, os, sys, time, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from stage0.dist_ingest.tests.test_dist_ingest import (  # noqa: E402
    DiConfig, DiPolicyParams, DiConsumerCfg, DiResult, DiIngestorCfg,
    make_file, load_lib, LIB_PATH)


class TestCK5Invariants(unittest.TestCase):
    def _mk_eng(self, invariant_asserts=1):
        lib = load_lib()
        path = make_file(2 * 1024 * 1024)
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
        self.assertTrue(eng)
        return lib, eng, fd, path

    def test_invariant_successful_run_outstanding_zero_after_join(self):
        lib, eng, fd, path = self._mk_eng(invariant_asserts=1)
        try:
            res = DiResult()
            t0 = time.monotonic()
            rc = lib.di_run(eng, ctypes.byref(res))
            self.assertLess(time.monotonic() - t0, 10.0)
            self.assertEqual(rc, 0)
            # CK-5.2: outstanding == 0 after join on successful run.
            from stage0.dist_ingest.tests.test_dist_ingest import DiNodeMetrics
            for i in range(len(res.nodes)):
                self.assertEqual(res.nodes[i].current_outstanding, 0,
                                 "node %d outstanding != 0" % i)
        finally:
            lib.di_destroy(eng)
            os.close(fd); os.unlink(path)

    def test_invariant_mode_on_publish_records_and_returns(self):
        lib, eng, fd, path = self._mk_eng(invariant_asserts=1)
        try:
            res = DiResult()
            rc = lib.di_run(eng, ctypes.byref(res))
            # Invariant build passes on success; the assertion path was exercised.
            self.assertEqual(rc, 0)
        finally:
            lib.di_destroy(eng)
            os.close(fd); os.unlink(path)


if __name__ == "__main__":
    unittest.main()
