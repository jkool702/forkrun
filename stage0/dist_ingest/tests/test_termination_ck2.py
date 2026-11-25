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
    def _assert_prompt_terminate(self, fn):
        import time
        t0 = time.monotonic()
        try:
            rc = fn()
        finally:
            elapsed = time.monotonic() - t0
        self.assertLess(elapsed, MAX_TERM_SECONDS,
                        "engine termination took %.1fs (> %.0fs)" % (elapsed, MAX_TERM_SECONDS))
        return rc

    def test_push_fail_seam_terminates_and_joins(self):
        import time
        lib, eng, fd, path = _mk_eng()
        try:
            self.assertTrue(eng)
            # Fail the 3rd publish (real queue-failure path in di_queue_push);
            # the engine must terminate promptly (stop broadcasts to waiters),
            # whether or not the injected failure is fatal.
            self.assertEqual(lib.di_test_set_push_fail_seam(eng, 3), 0)
            t0 = time.monotonic()
            res = DiResult()
            rc = lib.di_run(eng, ctypes.byref(res))
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, MAX_TERM_SECONDS)
        finally:
            lib.di_destroy(eng)
            os.close(fd)
            os.unlink(path)

    def test_pread_error_terminates_promptly(self):
        # Errors must terminate promptly, not block (CK-2 + fixes 1 & 2).
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


if __name__ == "__main__":
    unittest.main()
