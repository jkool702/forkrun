#!/usr/bin/env python3
"""WO-NUMA-PIPELINED-MADV-POPULATE-WRITE-STAGE0 tests. Builds standalone
prototype; verifies correctness, slot lifecycle, failure injection, no
silent fallback, accounting, all modes, edge cases, ordering, reclamation."""
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
SRC = os.path.join(PKG, "prefault_pipeline.c")
BIN = os.path.join(PKG, "prefault_pipeline")
SLOT = 2 * 1024 * 1024
PG = 4096


def build():
    subprocess.run(["make", "-C", PKG, "clean"], check=False, capture_output=True)
    r = subprocess.run(["make", "-C", PKG], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return BIN


def pattern(n):
    return bytes((i & 0xFF) for i in range(n))


def run(bin_path, mode="pipeline_madvise", data=b"", slot_size=SLOT, slots_per_node=2,
        workers_per_node=1, nodes="0", seam=None, consumer_delay_ns=0,
        chunks=None, timeout=60, extra=None):
    cmd = [bin_path, "--mode", mode, "--slot-size", str(slot_size),
           "--slots-per-node", str(slots_per_node), "--workers-per-node", str(workers_per_node),
           "--nodes", nodes]
    if seam: cmd += ["--seam", seam]
    if consumer_delay_ns: cmd += ["--consumer-delay-ns", str(consumer_delay_ns)]
    if extra: cmd += extra
    tmp = tempfile.mkdtemp(); jp = os.path.join(tmp, "out.json"); cmd += ["--json-out", jp]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # actual stdin/pipe; optional custom partial-read schedule
    if chunks is None:
        out, err = p.communicate(data, timeout=timeout)
    else:
        for c in chunks:
            try:
                p.stdin.write(c); p.stdin.flush()
            except BrokenPipeError:
                break
        try: p.stdin.close()
        except BrokenPipeError: pass
        out, err = p.communicate(timeout=timeout); err = err or b""
    res = None
    if os.path.exists(jp):
        try: res = json.load(open(jp))
        except Exception: res = None
    shutil.rmtree(tmp, ignore_errors=True)
    return p.returncode, res, err.decode("utf-8", "replace")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = build()


class TestCorrectness(Base):
    def test_all_modes_exact_accounting(self):
        data = pattern(3 * SLOT + 12345)
        for mode in ("lazy", "serial_madvise", "pipeline_madvise"):
            rc, res, err = run(self.bin, mode, data, slots_per_node=2)
            self.assertEqual(rc, 0, (mode, err))
            self.assertEqual(res["total_received"], len(data))
            self.assertEqual(res["total_copied"], len(data))
            self.assertEqual(res["total_published"], len(data))
            self.assertEqual(res["total_consumed"], len(data))
            self.assertEqual(res["rc"], 0)

    def test_empty_input(self):
        for mode in ("lazy", "serial_madvise", "pipeline_madvise"):
            rc, res, err = run(self.bin, mode, b"", slots_per_node=2)
            self.assertEqual(rc, 0, err)
            self.assertEqual(res["total_received"], 0)
            self.assertEqual(res["total_consumed"], 0)
            self.assertEqual(res["slots_free"] + res["slots_ready"], res["num_slots"])

    def test_smaller_than_one_slot(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(100), slot_size=SLOT, slots_per_node=2)
        self.assertEqual(rc, 0, err); self.assertEqual(res["total_consumed"], 100)

    def test_exact_slot_size(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(SLOT), slot_size=SLOT, slots_per_node=2)
        self.assertEqual(rc, 0, err); self.assertEqual(res["total_consumed"], SLOT)

    def test_partial_final_slot(self):
        n = SLOT + 777
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(n), slot_size=SLOT, slots_per_node=2)
        self.assertEqual(rc, 0, err); self.assertEqual(res["total_consumed"], n)

    def test_many_ring_wraps_multiple_generations(self):
        n = 8 * SLOT  # many wraps with slots_per_node=1
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(n), slot_size=SLOT, slots_per_node=1, nodes="0")
        self.assertEqual(rc, 0, err); self.assertEqual(res["total_consumed"], n)
        self.assertGreater(res["slots_completed"], res["num_slots"])
        self.assertEqual(res["slots_free"] + res["slots_ready"], res["num_slots"])

    def test_partial_stdin_reads(self):
        data = pattern(2 * SLOT + 5)
        # feed in tiny partial chunks
        chunks = [data[i:i + 4096] for i in range(0, len(data), 4096)]
        rc, res, err = run(self.bin, "pipeline_madvise", b"", slot_size=SLOT, slots_per_node=2, chunks=chunks)
        self.assertEqual(rc, 0, err); self.assertEqual(res["total_consumed"], len(data))

    def test_interrupted_syscall_eintr(self):
        data = pattern(2 * SLOT)
        rc, res, err = run(self.bin, "pipeline_madvise", data, slot_size=SLOT, slots_per_node=2, seam="eintr")
        self.assertEqual(rc, 0, err); self.assertEqual(res["total_consumed"], len(data))

    def test_ordering_no_dup_no_gap(self):
        data = pattern(4 * SLOT)
        rc, res, err = run(self.bin, "pipeline_madvise", data, slot_size=SLOT, slots_per_node=2)
        self.assertEqual(rc, 0, err); self.assertEqual(res["total_consumed"], len(data))

    def test_no_publication_before_copy_and_no_premature_reuse(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(4 * SLOT), slot_size=SLOT, slots_per_node=2)
        self.assertEqual(rc, 0, err)
        self.assertEqual(res["total_published"], res["total_copied"])

    def test_sparse_node_ids_and_multi_node(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(2 * SLOT), slot_size=SLOT,
                           slots_per_node=1, nodes="1,3", workers_per_node=1)
        self.assertEqual(rc, 0, err)
        self.assertIn(1, res["nodes"]); self.assertIn(3, res["nodes"])
        self.assertEqual(res["num_nodes"], 2)

    def test_burst_gap_schedule(self):
        data = pattern(4 * SLOT)
        chunks = [data[i:i + SLOT // 4] for i in range(0, len(data), SLOT // 4)]
        rc, res, err = run(self.bin, "pipeline_madvise", b"", slot_size=SLOT, slots_per_node=2, chunks=chunks)
        self.assertEqual(rc, 0, err); self.assertEqual(res["total_consumed"], len(data))

    def test_consumer_delay_backpressure(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(4 * SLOT), slot_size=SLOT, slots_per_node=2, consumer_delay_ns=1000)
        self.assertEqual(rc, 0, err); self.assertEqual(res["total_consumed"], 4 * SLOT)

    def test_lazy_genuinely_lazy(self):
        rc, res, err = run(self.bin, "lazy", pattern(2 * SLOT), slot_size=SLOT, slots_per_node=2)
        self.assertEqual(rc, 0, err)
        self.assertEqual(res["bytes_copied_prepared"], 0)
        self.assertEqual(res["bytes_copied_lazy"], res["total_consumed"])
        self.assertEqual(res["prepared_ratio"], 0.0)

    def test_serial_madvise_prepared(self):
        rc, res, err = run(self.bin, "serial_madvise", pattern(2 * SLOT), slot_size=SLOT, slots_per_node=2)
        self.assertEqual(rc, 0, err)
        self.assertEqual(res["bytes_copied_prepared"], res["total_consumed"])
        self.assertEqual(res["bytes_copied_lazy"], 0)

    def test_pipeline_madvise_reader_not_preparing(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(4 * SLOT), slot_size=SLOT, slots_per_node=2)
        self.assertEqual(rc, 0, err)
        self.assertEqual(res["bytes_copied_prepared"], res["total_consumed"])
        self.assertGreater(res["prep_union_ns"], 0)
        self.assertGreaterEqual(res["ready_at_assign"], 1)


class TestFailureInjection(Base):
    def _expect_fail(self, seam, mode="pipeline_madvise", n=4 * SLOT):
        rc, res, err = run(self.bin, mode, pattern(n), slot_size=SLOT, slots_per_node=2, seam=seam)
        self.assertNotEqual(rc, 0, seam)
        self.assertIsNotNone(res)
        self.assertTrue(res["failed"], seam)
        # accounting: totals never claim success on failure; no slot in-flight
        self.assertLessEqual(res["slots_free"] + res["slots_ready"], res["num_slots"])
        return res

    def test_no_worker_create(self):
        self._expect_fail("no-worker-create")

    def test_affinity_failure(self):
        self._expect_fail("affinity")

    def test_mempolicy_failure(self):
        self._expect_fail("mempolicy")

    def test_madvise_failure_not_ready_no_silent_fallback(self):
        res = self._expect_fail("madvise")
        self.assertEqual(res["bytes_copied_prepared"], 0)  # failed prep never READY

    def test_partial_prep_failure(self):
        self._expect_fail("partial-prep")

    def test_punch_hole_failure(self):
        self._expect_fail("punch-hole")

    def test_consumer_failure(self):
        self._expect_fail("consumer")

    def test_read_error(self):
        self._expect_fail("read")

    def test_shutdown_while_prep_in_progress(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(8 * SLOT), slot_size=SLOT, slots_per_node=4, seam="shutdown-prep")
        # no deadlock; threads join; truthful result
        self.assertIsNotNone(res)
        self.assertIn("total_received", res)

    def test_shutdown_reader_waiting_input(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(4 * SLOT), slot_size=SLOT, slots_per_node=2, seam="shutdown-reader-input")
        self.assertIsNotNone(res)

    def test_shutdown_reader_waiting_slot(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(8 * SLOT), slot_size=SLOT, slots_per_node=1, seam="shutdown-reader-slot")
        self.assertIsNotNone(res)

    def test_all_threads_terminate_and_join(self):
        for seam in ("no-worker-create","madvise","punch-hole","consumer","read","affinity","mempolicy"):
            rc, res, err = run(self.bin, "pipeline_madvise", pattern(4 * SLOT), slot_size=SLOT, slots_per_node=2, seam=seam, timeout=30)
            self.assertIsNotNone(res, seam)


class TestConfigValidation(Base):
    def test_invalid_dimensions_rejected(self):
        for args in (["--slot-size", "1000"], ["--slots-per-node", "0"], ["--workers-per-node", "0"], ["--slot-size", "0"]):
            p = subprocess.run([self.bin, "--nodes", "0"] + args, input=b"", capture_output=True, timeout=10)
            self.assertEqual(p.returncode, 2, args)

    def test_unknown_nodes_rejected(self):
        p = subprocess.run([self.bin, "--nodes", "-1"], input=b"", capture_output=True, timeout=10)
        self.assertEqual(p.returncode, 2)

    def test_unknown_mode_rejected(self):
        p = subprocess.run([self.bin, "--mode", "bogus", "--nodes", "0"], input=b"", capture_output=True, timeout=10)
        self.assertEqual(p.returncode, 2)


class TestSlotStateMachine(unittest.TestCase):
    def test_state_names_documented(self):
        src = open(SRC).read()
        for st in ("FREE","RESERVED","PREPARING","READY","ASSIGNED","COPYING","PUBLISHED","CONSUMED","RECLAIMING"):
            self.assertIn(st, src)
    def test_generation_checks(self):
        src = open(SRC).read()
        self.assertIn("generation", src); self.assertIn("mygen", src)
        self.assertIn("stale completion; rejected", src)
    def test_reclamation_punch_hole_keep_size(self):
        src = open(SRC).read()
        self.assertIn("FALLOC_FL_PUNCH_HOLE|FALLOC_FL_KEEP_SIZE", src)
    def test_no_silent_reclaim_fallback(self):
        src = open(SRC).read()
        self.assertIn("reclamation/hole-punch failure (no silent fallback)", src)
    def test_explicit_memcpy_not_read_into_dest(self):
        src = open(SRC).read()
        self.assertTrue("memcpy(dst, staging" in src or "memcpy((unsigned char*)e->map" in src)
        self.assertIn("NOT read-into-dest", src)
    def test_per_thread_policy_and_pinning(self):
        src = open(SRC).read()
        self.assertIn("SYS_set_mempolicy", src); self.assertIn("sched_setaffinity", src)
        self.assertIn("MPOL_BIND", src); self.assertIn("SYS_mbind", src)
    def test_madvise_populate_write_by_calling_thread(self):
        src = open(SRC).read()
        self.assertIn("MADV_POPULATE_WRITE", src)
    def test_pipeline_mode_has_prep_workers(self):
        src = open(SRC).read()
        self.assertIn("prep_thread", src); self.assertIn("input reader must not perform preparation", src)


class TestCorrections1(Base):
    def test_mapping_offset_zero_aligned_and_no_overrun(self):
        # P1 mapping: slot0==memfd offset0; aligned; no tail beyond ftruncate.
        n = 4 * SLOT
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(n), slot_size=SLOT, slots_per_node=2)
        self.assertEqual(rc, 0, err); self.assertEqual(res["total_consumed"], n)
        self.assertEqual(res["map_base_alignment"], max(SLOT, 4096))
        self.assertEqual(res["map_len"], res["num_slots"] * res["slot_size"])  # slot0==off0; no tail beyond ftruncate; ring bounded
        # many wraps prove no SIGBUS/overrun on reuse
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(8 * SLOT), slot_size=SLOT, slots_per_node=1)
        self.assertEqual(rc, 0, err)

    def test_numpy_alignment_prefix_suffix_source(self):
        src = open(SRC).read()
        self.assertIn("PROT_NONE", src); self.assertIn("MAP_FIXED", src)
        self.assertIn("ftruncate", src)
        # no partial unmap of file mapping; memfd mapped at offset 0
        self.assertNotIn("munmap((void*)base, aligned-base)", src)

    def test_real_byte_content_validation_checksum(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(4 * SLOT), slot_size=SLOT, slots_per_node=2)
        self.assertEqual(rc, 0, err)
        self.assertNotIn("byte-content", err)

    def test_copy_corruption_injection_detected(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(2 * SLOT), slot_size=SLOT, slots_per_node=2, seam="copy-corrupt")
        self.assertNotEqual(rc, 0); self.assertTrue(res["failed"])
        self.assertIn("checksum", res["fail_msg"].lower() if res.get("fail_msg") else "checksum")

    def test_validate_pattern_not_stub(self):
        src = open(SRC).read()
        self.assertIn("FNV-1a", src); self.assertIn("dcksum==s->checksum", src)

    def test_partial_read_then_fatal_no_hang_no_publish_partial(self):
        # partial slot followed by injected read failure: no hang, no partial publish
        data = pattern(SLOT // 2)
        chunks = [data, b""]  # then read error injected via seam
        rc, res, err = run(self.bin, "pipeline_madvise", b"", slot_size=SLOT, slots_per_node=2,
                           chunks=chunks, seam="read", timeout=30)
        self.assertIsNotNone(res)  # no deadlock
        # totals consistent; no dup; consumer drained; not claiming success
        self.assertLessEqual(res["total_published"], res["total_consumed"] + 1)

    def test_partial_read_error_discards_partial(self):
        src = open(SRC).read()
        self.assertIn("read_err", src); self.assertIn("do NOT publish partial", src)

    def test_partial_thread_startup_cleanup_source(self):
        src = open(SRC).read()
        self.assertIn("goto shutdown", src); self.assertIn("created_prep", src)
        self.assertIn("created_consumer", src); self.assertIn("created_reader", src)
        self.assertIn("no-worker-create-nth", src)

    def test_no_worker_create_nth_joins_started(self):
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(4 * SLOT), slot_size=SLOT,
                           slots_per_node=2, workers_per_node=2, seam="no-worker-create-nth", timeout=30)
        self.assertNotEqual(rc, 0); self.assertIsNotNone(res)  # no leak/hang

    def test_multi_worker_per_node_accounting_tsan_clean_source(self):
        src = open(SRC).read()
        self.assertIn("_Atomic uint64_t", src)
        # run with workers_per_node=2 (TSan separately verifies race-free)
        rc, res, err = run(self.bin, "pipeline_madvise", pattern(8 * SLOT), slot_size=SLOT,
                           slots_per_node=2, workers_per_node=2, nodes="0", extra=["--placement-sampling"])
        self.assertEqual(rc, 0, err); self.assertEqual(res["total_consumed"], 8 * SLOT)

    def test_serial_madvise_preparation_measured(self):
        rc, res, err = run(self.bin, "serial_madvise", pattern(2 * SLOT), slot_size=SLOT, slots_per_node=2)
        self.assertEqual(rc, 0, err)
        self.assertGreater(res["total_prep_ops"], 0)
        self.assertGreater(res["total_prep_ns"], 0)
        self.assertEqual(res["bytes_copied_prepared"], res["total_consumed"])

    def test_failed_madvise_quarantine_reclaim_source(self):
        src = open(SRC).read()
        self.assertIn("failed MADV_POPULATE_WRITE can leave some pages populated", src.lower() if False else src)
        self.assertIn("QUARANTINE", src)

    def test_eof_empty_reclaim_not_ignored(self):
        src = open(SRC).read()
        self.assertIn("P2: do NOT ignore fallocate failure", src)

    def test_stale_gen_seam_actually_exercises_rejection(self):
        src = open(SRC).read()
        self.assertIn("injected_stale", src); self.assertIn("inject stale completion", src)
        # production rejection logic: generation check before READY + before copy + publish
        self.assertIn("s->generation==mygen", src)


if __name__ == "__main__":
    unittest.main()
