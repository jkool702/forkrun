"""W-EXP-2 step B: the typed supervision substrate, driven as a real process.

The substrate lives in the cleanroom launcher and is inert unless
`FORKRUN_SUPERVISE_TYPED=1`. These tests start the launcher directly (not
through `forkrun.map`) because the required evidence is the launcher's
supervision decisions: which family died, whether the death matched the
registered generation, and whether teardown was bounded.

Every case asserts that its injection actually fired. A "fatal helper
death" test in which the helper survived would otherwise look like a pass.

Limits: this host has one physical NUMA node. Everything here validates the
logical identity/protocol model, which is all step B claims.
"""

import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

from forkrun._worker import _HDR  # noqa: E402

_LAUNCHER = REPO / "python" / "forkrun" / "_forkrun_cleanroom"
_SUBSTRATE = REPO / "python" / "forkrun" / "libforkrun_python.so"

LINES = 512
BATCH = 64
SLEEP_MS = 40

_PLUGIN_C = r'''
#include "forkrun_plugin.h"
#include <unistd.h>
#include <stdio.h>
int forkrun_use_ctx = FORKRUN_CTX_ENABLE|FORKRUN_CTX_FLAG_RAW;
int copy_slow(int argc, char **argv, const struct forkrun_ctx *ctx){
  (void)argc; (void)argv;
  uint64_t n = ctx->batch_byte_length;
  const char *in = (const char*)(uintptr_t)ctx->reserved[0];
  if (in == NULL) return -1;
  usleep(%d * 1000);
  if (n && fwrite(in, 1, (size_t)n, stdout) != (size_t)n) return -2;
  return fflush(stdout) == 0 ? 0 : -2;
}
''' % SLEEP_MS

_POLICY = re.compile(
    r"forkrun-sup: policy role=(\w+) recoverable=(\d) node_scoped=(\d) "
    r"clean_window=([\w-]+)")
_REGISTER = re.compile(
    r"forkrun-sup: register role=(\w+) wid=(-?\d+) node=(-?\d+) "
    r"pid=(\d+) incarnation=(\d+)")
_DEATH = re.compile(
    r"forkrun-sup: death role=(\w+) wid=(-?\d+) node=(-?\d+) pid=(\d+) "
    r"incarnation=(\d+) status=(-?\d+) class=(\w+) recoverable=(\d)")
_STALE = re.compile(r"forkrun-sup: stale note role=worker ")
_FATAL = "forkrun-cleanroom: fatal -- terminated the pipeline"


def _build_plugin(tmp):
    src = os.path.join(tmp, "slow.c")
    with open(src, "w") as fh:
        fh.write(_PLUGIN_C)
    out = os.path.join(tmp, "slow.so")
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2",
         "-I", str(REPO / "ring_loadables"), "-o", out, src],
        check=True, capture_output=True, text=True)
    return out


@unittest.skipUnless(_LAUNCHER.exists() and _SUBSTRATE.exists(),
                     "cleanroom launcher / substrate not built")
class TestSupervisionSubstrate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="sup-substrate-")
        cls.plugin = _build_plugin(cls._tmp)
        cls.corpus = os.path.join(cls._tmp, "in.txt")
        with open(cls.corpus, "w") as fh:
            for i in range(LINES):
                fh.write("line %06d\n" % i)
        with open(cls.corpus, "rb") as fh:
            cls.corpus_bytes = fh.read()
        cls.result = os.path.join(cls._tmp, "out.bin")

    # -- harness -------------------------------------------------------

    def _run(self, extra_env=None, kill_ingest_delay=None,
             kill_worker_after=None, kill_worker_immediately=False,
             kill_budget=0, workers=2, respawn_cap=None, timeout=30,
             lines=None):
        """Run the launcher, optionally killing families mid-run.

        `kill_worker_after` is `(wid, delay_s)`. `kill_worker_immediately`
        SIGKILLs each worker generation as soon as it registers, up to
        `kill_budget` kills -- the slot-pressure regression. Returns
        (rc, elapsed, lines, ingest_pid, worker_pids).
        """
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("FORKRUN_TEST_")
               and k != "FORKRUN_SUPERVISE_TYPED"}
        env["FORKRUN_SUPERVISE_TYPED"] = "1"
        env.update(extra_env or {})

        src_fd = os.open(self.corpus, os.O_RDONLY)
        out_fd = os.open(self.result,
                         os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        argv = [
            str(_LAUNCHER), "--so", str(_SUBSTRATE),
            "--workers", str(workers), "--lines",
            str(BATCH if lines is None else lines), "--bytes", "0",
            "--on-error", "0", "--retry", "3",
            "--src", str(src_fd), "--result", str(out_fd),
            "--stats-fd", "-1",
            "--plugin", self.plugin, "--func", "copy_slow",
        ]
        if respawn_cap is not None:
            argv += ["--respawn-cap", str(respawn_cap)]
        try:
            proc = subprocess.Popen(
                argv, env=env, pass_fds=(src_fd, out_fd),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, bufsize=1)
        finally:
            os.close(src_fd)
            os.close(out_fd)

        q = queue.Queue()

        def _reader():
            for line in proc.stderr:
                q.put(line.rstrip())
            q.put(None)

        threading.Thread(target=_reader, daemon=True).start()

        lines = []
        ingest_pid = None
        worker_pids = {}
        killed_ingest = False
        killed_worker = False
        kills = 0
        t0 = time.time()
        deadline = t0 + timeout
        try:
            while time.time() < deadline:
                try:
                    line = q.get(timeout=0.1)
                except queue.Empty:
                    if proc.poll() is not None:
                        break
                    continue
                if line is None:
                    break
                lines.append(line)

                m = _REGISTER.search(line)
                if m and m.group(1) == "ingest":
                    ingest_pid = int(m.group(4))
                    if kill_ingest_delay is not None and not killed_ingest:
                        time.sleep(kill_ingest_delay)
                        self._kill(ingest_pid)
                        killed_ingest = True
                elif m and m.group(1) == "worker":
                    wid = int(m.group(2))
                    worker_pids.setdefault(wid, []).append(int(m.group(4)))
                    if (kill_worker_after is not None and not killed_worker
                            and wid == kill_worker_after[0]):
                        time.sleep(kill_worker_after[1])
                        self._kill(int(m.group(4)))
                        killed_worker = True
                    if (kill_worker_immediately and kills < kill_budget):
                        self._kill(int(m.group(4)))
                        kills += 1

            try:
                rc = proc.wait(timeout=max(1.0, deadline - time.time()))
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait()
                self.fail("launcher did not exit within %ds" % timeout)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stderr.close()

        if kill_ingest_delay is not None:
            self.assertTrue(killed_ingest,
                            "ingest was never registered, so the fatal "
                            "injection could not have fired")
        if kill_worker_immediately:
            self.assertGreaterEqual(
                kills, kill_budget,
                "the respawn injection stopped firing before the budget: "
                "%d of %d kills (rc=%r; last launcher lines: %r)"
                % (kills, kill_budget, rc, lines[-8:]))
        return rc, time.time() - t0, lines, ingest_pid, worker_pids

    @staticmethod
    def _kill(pid):
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass

    def _result(self):
        with open(self.result, "rb") as fh:
            return fh.read()

    @staticmethod
    def _records(blob):
        recs, off = [], 0
        while off + _HDR.size <= len(blob):
            idx, ln, disp, _res = _HDR.unpack_from(blob, off)
            off += _HDR.size
            if off + ln > len(blob):
                break
            recs.append((idx, disp, blob[off:off + ln]))
            off += ln
        return recs

    def _assert_no_survivors(self, ingest_pid, worker_pids):
        pids = ([ingest_pid] if ingest_pid else [])
        for seq in worker_pids.values():
            pids.extend(seq)
        alive = [p for p in pids if os.path.exists("/proc/%d" % p)]
        self.assertEqual(alive, [],
                         "registered descendants survived the run: %r" % alive)

    # -- the model -----------------------------------------------------

    def test_policy_inventory_is_explicit_and_complete(self):
        rc, _dt, lines, _ip, _wp = self._run()
        self.assertEqual(rc, 0)

        policy = {}
        for line in lines:
            m = _POLICY.search(line)
            if m:
                policy[m.group(1)] = (int(m.group(2)), int(m.group(3)),
                                      m.group(4))
        self.assertEqual(
            set(policy),
            {"worker", "orderer", "indexer", "scanner", "fallow",
             "ingest", "drain"},
            "a family without an explicit policy is a hole in the model")
        self.assertEqual(policy["worker"], (1, 1, "never"))
        # Clean-exit windows are part of the policy, not an implicit
        # "exit 0 means done". The ingest completes at the GLOBAL
        # ingest-EOF marker; the indexer and scanner complete on their
        # OWN node's state (the global marker says the source was
        # consumed, not that this node's work is done); orderer, fallow
        # and drain only once teardown has begun.
        self.assertEqual(policy["ingest"], (0, 0, "eof"), "ingest")
        for role in ("indexer", "scanner"):
            self.assertEqual(policy[role], (0, 0, "node-complete"), role)
        for role in ("orderer", "fallow", "drain"):
            self.assertEqual(policy[role], (0, 0, "teardown"), role)

    def test_healthy_run_reaps_helper_cleanly_and_transfers_all_bytes(self):
        rc, _dt, lines, ingest_pid, worker_pids = self._run()
        self.assertEqual(rc, 0)

        self.assertIsNotNone(ingest_pid, "sentinel helper was never registered")
        death = [m for line in lines
                 for m in [_DEATH.search(line)] if m and m.group(1) == "ingest"]
        self.assertEqual(len(death), 1, "expected exactly one sentinel death")
        self.assertEqual(death[0].group(7), "clean")
        self.assertEqual(death[0].group(6), "0")
        ingest_line = [line for line in lines if "death role=ingest" in line][0]
        self.assertIn("evidence=1", ingest_line,
                      "the accepted clean exit carried no completion "
                      "evidence, so the acceptance was status-only")
        self.assertFalse(any("guillotine" in line for line in lines),
                         "a clean run must not resort to the guillotine")
        self.assertFalse(
            any("role=worker exited 0 before" in line for line in lines),
            "a normal worker completion was logged as an unexpected "
            "helper exit")

        # The sentinel exits only when the launcher closes the control
        # pipe: the clean death also proves no worker inherited the write
        # end, or the run would have hung instead of reaching this point.
        recs = self._records(self._result())
        self.assertTrue(recs, "the drain delivered no records")
        self.assertTrue(all(disp == 0 for _i, disp, _p in recs),
                        "a record was not DATA: %r" % (recs,))
        payload = b"".join(p for _i, _d, p in recs)
        self.assertEqual(sorted(payload.splitlines()),
                         sorted(self.corpus_bytes.splitlines()))
        self._assert_no_survivors(ingest_pid, worker_pids)

    def test_worker_respawn_keeps_node_and_increments_incarnation(self):
        rc, _dt, lines, _ip, worker_pids = self._run(
            {"FORKRUN_TEST_DIE_BEFORE_ACK": "1"})
        self.assertEqual(rc, 0)

        regs = []
        for line in lines:
            m = _REGISTER.search(line)
            if m and m.group(1) == "worker":
                regs.append((int(m.group(2)), int(m.group(3)),
                             int(m.group(4)), int(m.group(5))))
        self.assertTrue(regs, "no worker registrations were emitted")
        self.assertTrue(any(len(v) >= 2 for v in worker_pids.values()),
                        "the death injection never produced a respawn; "
                        "this test would prove nothing")

        for wid in {r[0] for r in regs}:
            mine = [r for r in regs if r[0] == wid]
            nodes = {r[1] for r in mine}
            incs = [r[3] for r in mine]
            self.assertEqual(len(nodes), 1,
                             "wid %d changed logical node across respawn: %r"
                             % (wid, nodes))
            self.assertEqual(incs, list(range(len(incs))),
                             "wid %d incarnation sequence is not 0..n: %r"
                             % (wid, incs))

    def test_stale_note_is_ignored_and_never_reaches_the_replacement(self):
        rc, _dt, lines, _ip, worker_pids = self._run(
            {"FORKRUN_TEST_DIE_BEFORE_ACK": "1",
             "FORKRUN_TEST_STALE_NOTE_AFTER_RESPAWN": "1"})
        self.assertEqual(rc, 0,
                         "a stale note turned into a fatal event")

        stale = [line for line in lines if _STALE.search(line)]
        self.assertGreaterEqual(
            len(stale), 2,
            "expected two stale shapes (retired pid, live pid with the "
            "previous incarnation); got %r" % (stale,))
        for line in stale:
            self.assertIn("-- ignored", line)
        self.assertGreaterEqual(max(len(v) for v in worker_pids.values()), 2,
                                "no replacement existed for the note to "
                                "wrongly reach")
        # The live pid carrying the OLD incarnation is the case only the
        # incarnation check can reject; a pid-only matcher would accept it.
        checks = [line for line in lines if "forkrun-sup: stale-check" in line]
        self.assertTrue(checks, "the incarnation check never ran")
        for line in checks:
            m = re.search(r"given_incarnation=(\d+) current_incarnation=(\d+) "
                          r"rejected=(\d)", line)
            self.assertIsNotNone(m, line)
            given, current, rejected = (int(m.group(1)), int(m.group(2)),
                                        int(m.group(3)))
            self.assertLess(given, current,
                            "the injected note was not old: %s" % line)
            self.assertEqual(rejected, 1,
                             "a note naming the live pid with a stale "
                             "incarnation was accepted: %s" % line)
        self.assertFalse(any(_FATAL in line for line in lines))

    def test_abnormal_helper_death_aborts_within_budget(self):
        rc, dt, lines, ingest_pid, worker_pids = self._run(
            kill_ingest_delay=0.08)
        self.assertNotEqual(rc, 0, "an abnormal ingest death exited 0")
        self.assertTrue(any("is not recoverable -- aborting" in line
                            for line in lines),
                        "the family policy did not fire")
        self.assertTrue(any("forkrun-sup: guillotine" in line
                            for line in lines),
                        "teardown did not report a bounded guillotine")
        self.assertEqual(sum(_FATAL in line for line in lines), 1)
        self.assertLess(dt, 10.0, "teardown was not bounded")
        self._assert_no_survivors(ingest_pid, worker_pids)

    def test_concurrent_fatal_events_converge_on_one_bounded_abort(self):
        rc, dt, lines, ingest_pid, worker_pids = self._run(
            kill_ingest_delay=0.08, kill_worker_after=(0, 0.08))
        self.assertNotEqual(rc, 0)
        self.assertEqual(sum(_FATAL in line for line in lines), 1,
                         "the abort path ran more than once")
        self.assertLess(dt, 10.0)
        self._assert_no_survivors(ingest_pid, worker_pids)

    def test_registry_slots_are_reused_across_generations(self):
        """Slot pressure regression: more respawns than spare slots.

        Registration used to allocate a NEW slot per generation, so
        SUP_MAX_PROCS (520) was consumed by history, not by live
        children. The registry cap is lowered to 8 here so the same
        allocation boundary is crossed deterministically: one helper
        plus one worker leaves 6 new slots, and 30 killed generations
        must not exhaust them. Every regeneration must be a REUSE of the
        worker's single slot."""
        budget = 30
        # lines=8 -> 64 batches for the 512-line corpus. The corpus has
        # only 8 batches at the default 64, so a fast 4-CPU runner can
        # finish the work before 8 generations have been killed, leaving
        # the registration/reuse assertions below unexercised.
        rc, _dt, lines, ingest_pid, worker_pids = self._run(
            extra_env={"FORKRUN_TEST_SUP_MAX": "8"},
            kill_worker_immediately=True, kill_budget=budget,
            workers=1, respawn_cap=10000, timeout=120, lines=8)
        regs = [line for line in lines if "register role=worker" in line]
        reuses = [line for line in lines if "reuse role=worker" in line]
        self.assertGreaterEqual(
            len(regs), 8,
            "only %d worker registrations; slot reuse was not exercised"
            % len(regs))
        self.assertGreaterEqual(
            len(reuses), 6,
            "only %d slot reuses; generations consumed new slots"
            % len(reuses))
        self.assertNotIn("supervision registry full", "\n".join(lines),
                         "the registry ran out of slots")
        self.assertEqual(rc, 0, "the run failed under slot pressure")

        recs = self._records(self._result())
        payload = b"".join(p for _i, _d, p in recs)
        self.assertEqual(sorted(payload.splitlines()),
                         sorted(self.corpus_bytes.splitlines()),
                         "output was lost under repeated respawns")
        self._assert_no_survivors(ingest_pid, worker_pids)

    def test_early_clean_ingest_without_evidence_is_fatal(self):
        """The EOF window requires the completion event, not status 0.

        The sentinel is the default ingest role but exits 0 early
        WITHOUT publishing its modeled completion event. That must be
        fatal: a valid-looking prefix is not proof the source was fully
        ingested.
        """
        rc, dt, lines, ingest_pid, worker_pids = self._run(
            extra_env={"FORKRUN_TEST_HELPER_EXIT_CLEAN_EARLY": "1"})
        self.assertNotEqual(rc, 0, "an unproven clean ingest exit exited 0")
        self.assertTrue(
            any("without ingest-completion evidence" in line for line in lines),
            "the EOF window accepted a clean exit without evidence")
        self.assertTrue(any("is not recoverable -- aborting" in line
                            for line in lines))
        deaths = [line for line in lines if "death role=ingest" in line]
        self.assertTrue(deaths, "the ingest death was never classified")
        self.assertIn("class=clean", deaths[0])
        self.assertIn("evidence=0", deaths[0],
                      "the injected exit unexpectedly carried evidence")
        self.assertLess(dt, 10.0)
        self._assert_no_survivors(ingest_pid, worker_pids)

    def test_unexpected_clean_helper_exit_is_fatal(self):
        """Exit status zero outside the role's window is not success.

        The sentinel is registered as an orderer (clean window:
        teardown) and exits 0 while the pipeline is still running. The
        registry must treat that as an abnormal, non-recoverable death.
        """
        rc, dt, lines, ingest_pid, worker_pids = self._run(
            extra_env={"FORKRUN_TEST_HELPER_ROLE": "orderer",
                       "FORKRUN_TEST_HELPER_EXIT_CLEAN_EARLY": "1"})
        self.assertNotEqual(rc, 0, "an unexpected clean exit exited 0")
        self.assertTrue(any("register role=orderer" in line for line in lines),
                        "the sentinel was not registered under the "
                        "override role, so the policy was not exercised")
        self.assertTrue(any("exited 0 before its completion window" in line
                            for line in lines),
                        "the clean-exit window did not classify the death")
        self.assertTrue(any("is not recoverable -- aborting" in line
                            for line in lines))
        death = [m for line in lines
                 for m in [_DEATH.search(line)]
                 if m and m.group(1) == "orderer"]
        self.assertTrue(death and death[0].group(7) == "clean",
                        "the injected exit was not clean")
        self.assertLess(dt, 10.0)
        self._assert_no_survivors(ingest_pid, worker_pids)

    def test_registry_is_inert_without_the_hook(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("FORKRUN_TEST_")
               and k != "FORKRUN_SUPERVISE_TYPED"}
        env["FORKRUN_TEST_DIE_BEFORE_ACK"] = "1"
        src_fd = os.open(self.corpus, os.O_RDONLY)
        out_fd = os.open(self.result,
                         os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        argv = [
            str(_LAUNCHER), "--so", str(_SUBSTRATE),
            "--workers", "2", "--lines", str(BATCH), "--bytes", "0",
            "--on-error", "0", "--retry", "3",
            "--src", str(src_fd), "--result", str(out_fd),
            "--stats-fd", "-1",
            "--plugin", self.plugin, "--func", "copy_slow",
        ]
        try:
            proc = subprocess.run(argv, env=env, pass_fds=(src_fd, out_fd),
                                  capture_output=True, text=True, timeout=60)
        finally:
            os.close(src_fd)
            os.close(out_fd)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("forkrun-sup:", proc.stderr,
                         "the typed registry emitted records without the "
                         "opt-in hook")


if __name__ == "__main__":
    unittest.main()
