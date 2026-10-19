"""W-EXP-2 step C: the multi-node cleanroom envelope, driven as a real process.

The launcher grew a NUMA route in step C: real ingest/indexer/scanner/
fallow families under the typed registry, the engine's C orderer for
ordered collection, and a registry sized from the requested topology
rather than a fixed array.

These tests start the launcher DIRECTLY (not through `forkrun.map`),
because the required evidence is the launcher's own behaviour: which
families were registered, what the certificate said, and whether a
helper death aborted the run. The public-API routing is checked
separately, in-process, where the cleanroom-path globals are
observable.

Every fault-injection case asserts that its injection actually fired.
A "helper death aborts the run" test in which the helper survived would
otherwise look like a pass.

Limits: this host has one physical NUMA node, so everything here is
LOGICAL @N. The tests validate the protocol, the identity model and the
ordering guarantee -- not physical locality or bandwidth.
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
SLEEP_MS = 2

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

_REGISTER = re.compile(
    r"forkrun-sup: register role=(\w+) wid=(-?\d+) node=(-?\d+) "
    r"pid=(\d+) incarnation=(\d+)")
_DEATH = re.compile(
    r"forkrun-sup: death role=(\w+) wid=(-?\d+) node=(-?\d+) pid=(\d+) "
    r"incarnation=(\d+) status=(-?\d+) class=(\w+) recoverable=(\d)")
_CAPACITY = re.compile(r"forkrun-sup: capacity entries=(\d+) required=(\d+)")
_FATAL = "forkrun-cleanroom: fatal"


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
class TestCleanroomNuma(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="cleanroom-numa-")
        cls.plugin = _build_plugin(cls._tmp)
        cls.corpus = os.path.join(cls._tmp, "in.txt")
        with open(cls.corpus, "w") as fh:
            for i in range(LINES):
                fh.write("line %06d\n" % i)
        with open(cls.corpus, "rb") as fh:
            cls.corpus_bytes = fh.read()
        cls.result = os.path.join(cls._tmp, "out.bin")

    # -- harness -------------------------------------------------------

    def _run(self, nodes=2, order="index", workers=4, lines=BATCH,
             extra_env=None, kill_role=None, kill_delay=0.0,
             timeout=120, numa_map=None):
        """Run the launcher with a logical topology.

        `kill_role` names a helper family to SIGKILL once it registers
        (`indexer`, `scanner`, `fallow`, `ingest`). Returns
        (rc, elapsed, stderr_lines, result_bytes, registered_pids).
        """
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("FORKRUN_TEST_")}
        env.update(extra_env or {})

        if numa_map is None:
            # Logical @N on a one-node host: N logical nodes, all
            # pinned to physical node 0. This is exactly the map
            # _numa.build_numa_map produces for the '@N' form.
            numa_map = ",".join(["0"] * nodes)

        src_fd = os.open(self.corpus, os.O_RDONLY)
        out_fd = os.open(self.result,
                         os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        argv = [
            str(_LAUNCHER), "--so", str(_SUBSTRATE),
            "--workers", str(workers), "--lines", str(lines), "--bytes", "0",
            "--on-error", "0", "--retry", "3",
            "--src", str(src_fd), "--result", str(out_fd),
            "--stats-fd", "-1",
            "--plugin", self.plugin, "--func", "copy_slow",
            "--nodes", str(nodes), "--numa-map", numa_map,
            "--order", order,
        ]
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

        lines_out = []
        registered = {}
        killed = False
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
                lines_out.append(line)
                m = _REGISTER.search(line)
                if m:
                    role = m.group(1)
                    registered.setdefault(role, []).append(int(m.group(4)))
                    if (kill_role is not None and role == kill_role
                            and not killed):
                        # The kill lands at REGISTRATION, not after a
                        # delay: these families finish in milliseconds
                        # on a small corpus, so a delayed kill can find
                        # an already-exited process and prove nothing.
                        if kill_delay:
                            time.sleep(kill_delay)
                        killed = self._kill(int(m.group(4)))
            try:
                rc = proc.wait(timeout=max(1.0, deadline - time.time()))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                self.fail("launcher did not exit within %ds" % timeout)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stderr.close()

        if kill_role is not None:
            self.assertTrue(killed,
                            "the %s family never registered, so the fatal "
                            "injection could not have fired" % kill_role)
        with open(self.result, "rb") as fh:
            blob = fh.read()
        return rc, time.time() - t0, lines_out, blob, registered

    @staticmethod
    def _kill(pid):
        """SIGKILL a pid. Returns True only if the signal landed.

        The return value is the injection's own proof: a ProcessLookupError
        means the process had already exited, so the death this test
        claims to have caused was not caused by the test.
        """
        try:
            os.kill(pid, 9)
            return True
        except ProcessLookupError:
            return False

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

    def _assert_no_survivors(self, registered):
        pids = [p for seq in registered.values() for p in seq]
        alive = [p for p in pids if os.path.exists("/proc/%d" % p)]
        self.assertEqual(alive, [],
                         "registered descendants survived the run: %r" % alive)

    # -- the model -----------------------------------------------------

    def test_ordered_run_is_byte_exact_at_two_nodes(self):
        """The whole point of the step A finding: cross-node ordering.

        `batch_idx` is a PER-NODE ticket, so the cleanroom's old
        parent-side sort by batch_idx cannot express global order across
        nodes. The launcher therefore runs the engine's C orderer, and
        the collected stream must be byte-identical to the input.
        """
        rc, _dt, _lines, blob, reg = self._run(nodes=2, order="index")
        self.assertEqual(rc, 0)
        recs = self._records(blob)
        self.assertTrue(recs, "the run delivered no records")
        self.assertTrue(all(d == 0 for _i, d, _p in recs),
                        "a record was not DATA")
        self.assertEqual(b"".join(p for _i, _d, p in recs), self.corpus_bytes,
                         "the ordered stream is not byte-exact")
        self._assert_no_survivors(reg)

    def test_ordered_run_is_byte_exact_at_four_nodes(self):
        rc, _dt, _lines, blob, reg = self._run(nodes=4, order="index")
        self.assertEqual(rc, 0)
        recs = self._records(blob)
        self.assertTrue(recs)
        self.assertEqual(b"".join(p for _i, _d, p in recs), self.corpus_bytes,
                         "the ordered stream is not byte-exact at 4 nodes")
        self._assert_no_survivors(reg)

    def test_unordered_run_is_complete_at_two_nodes(self):
        """order="none" promises completeness, not order."""
        rc, _dt, _lines, blob, reg = self._run(nodes=2, order="none")
        self.assertEqual(rc, 0)
        recs = self._records(blob)
        payload = b"".join(p for _i, _d, p in recs)
        self.assertEqual(sorted(payload.splitlines()),
                         sorted(self.corpus_bytes.splitlines()),
                         "the unordered stream lost or duplicated records")
        self._assert_no_survivors(reg)

    def test_unordered_run_is_complete_at_four_nodes(self):
        rc, _dt, _lines, blob, reg = self._run(nodes=4, order="none")
        self.assertEqual(rc, 0)
        recs = self._records(blob)
        payload = b"".join(p for _i, _d, p in recs)
        self.assertEqual(sorted(payload.splitlines()),
                         sorted(self.corpus_bytes.splitlines()))
        self._assert_no_survivors(reg)

    def test_every_helper_family_is_registered_under_its_own_role(self):
        """Five families, five identities -- no "helper" catch-all."""
        rc, _dt, lines, _blob, reg = self._run(nodes=2, order="index")
        self.assertEqual(rc, 0)
        for role in ("ingest", "fallow", "indexer", "scanner", "orderer"):
            self.assertIn(role, reg,
                          "the %s family was never registered: %r"
                          % (role, sorted(reg)))
        self.assertEqual(len(reg.get("indexer", [])), 2,
                         "one indexer per logical node is required")
        self.assertEqual(len(reg.get("scanner", [])), 2,
                         "one scanner per logical node is required")
        workers = [m for m in
                   (_REGISTER.search(l) for l in lines) if m
                   and m.group(1) == "worker"]
        self.assertEqual(len(workers), 4)
        nodes = {int(m.group(3)) for m in workers}
        self.assertEqual(nodes, {0, 1},
                         "workers were not distributed across both nodes")

    def test_ingest_completion_is_backed_by_the_engine_sentinel(self):
        """The EOF window is engine-backed, not a child's self-report.

        The launcher accepts a clean ingest exit only when the ENGINE
        reports ingest EOF posted (fr_py_ingest_eof_posted). The death
        record must therefore carry evidence=1 for the accepted exit.
        """
        rc, _dt, lines, _blob, _reg = self._run(nodes=2, order="index")
        self.assertEqual(rc, 0)
        deaths = [m for m in (_DEATH.search(l) for l in lines)
                  if m and m.group(1) == "ingest"]
        self.assertEqual(len(deaths), 1,
                         "expected exactly one ingest death")
        self.assertEqual(deaths[0].group(7), "clean")
        line = [l for l in lines if "death role=ingest" in l][0]
        self.assertIn("evidence=1", line,
                      "the accepted clean exit carried no EOF evidence")

    def test_clean_exit_without_eof_evidence_is_fatal(self):
        """A clean exit is not proof that the source was consumed.

        The EOF window is engine-backed: the helper's clean exit is
        accepted only when the ENGINE reports ingest EOF posted. The
        test hook withholds that evidence, modelling an engine that
        never completed the ingest -- and the run must fail rather than
        report a clean-looking, short result.
        """
        rc, dt, lines, _blob, reg = self._run(
            nodes=2, order="index",
            extra_env={"FORKRUN_TEST_NO_EOF_EVIDENCE": "1"})
        self.assertNotEqual(rc, 0,
                            "a clean exit without EOF evidence exited 0")
        self.assertTrue(
            any("without completion evidence" in l
                or "without ingest-completion evidence" in l
                for l in lines),
            "the missing evidence was not reported: %r" % lines[-6:])
        self.assertLess(dt, 20.0)
        self._assert_no_survivors(reg)

    def test_registry_capacity_is_sized_from_the_topology(self):
        """The reviewer's capacity gate, as a live assertion.

        The old registry was a fixed 520-entry array. The target
        topology -- 512 workers + 4 indexers + 4 scanners + fallow +
        ingest + orderer = 523 -- already exceeded it BEFORE any extra
        process, so the registry must now be sized from the request.
        """
        rc, _dt, lines, _blob, _reg = self._run(
            nodes=4, order="index", workers=512, lines=1, timeout=180)
        self.assertEqual(rc, 0)
        caps = [m for m in (_CAPACITY.search(l) for l in lines) if m]
        self.assertTrue(caps, "the launcher did not report its capacity")
        entries = int(caps[0].group(1))
        required = int(caps[0].group(2))
        self.assertEqual(entries, required,
                         "the registry was not sized to the requirement")
        self.assertEqual(required, 512 + 4 * 2 + 3,
                         "the capacity model changed: %d" % required)
        self.assertGreater(required, 520,
                           "this configuration is supposed to exceed the "
                           "old fixed array")

    def test_oversized_topology_is_refused_before_any_input_is_read(self):
        """An unservable configuration must cost no input.

        The worker count is checked against the ENGINE's own ceiling
        before anything is forked: a configuration the engine cannot
        run must not get as far as starting a pipeline.
        """
        rc, _dt, lines, _blob, _reg = self._run(
            nodes=2, order="index", workers=9000, lines=1, timeout=60)
        self.assertNotEqual(rc, 0, "an oversized topology was accepted")
        self.assertTrue(
            any("worker ceiling" in l for l in lines),
            "the refusal did not name the ceiling: %r" % lines[:5])
        self.assertFalse(any("forkrun-sup: register" in l for l in lines),
                         "the launcher started processes before refusing")

    def test_a_large_worker_complement_is_servable(self):
        """The keep-list must hold one output descriptor per worker.

        The descriptor keep-list was a fixed 256 entries, and the drain
        child holds one output descriptor PER WORKER -- so the launcher
        silently capped at ~250 workers and failed in a CHILD, halfway
        through startup, with the real cause invisible. The bound is now
        derived from the engine's own worker ceiling, and a 512-worker
        run (the reviewed topology's scale) must actually complete.
        """
        rc, dt, lines, blob, reg = self._run(
            nodes=2, order="index", workers=512, lines=1, timeout=240)
        self.assertEqual(rc, 0,
                         "a 512-worker run did not complete: %r"
                         % [l for l in lines if "refus" in l
                            or "could not be given" in l][:3])
        self.assertTrue(reg.get("worker"),
                        "no workers were registered at all")
        self.assertLess(dt, 240.0)

    def test_ingest_death_aborts_the_run(self):
        rc, dt, lines, _blob, reg = self._run(
            nodes=2, order="index", kill_role="ingest")
        self.assertNotEqual(rc, 0, "an ingest death exited 0")
        self.assertTrue(any("is not recoverable -- aborting" in l
                            for l in lines),
                        "the family policy did not fire")
        self.assertTrue(any(_FATAL in l for l in lines))
        self.assertLess(dt, 20.0, "teardown was not bounded")
        self._assert_no_survivors(reg)

    def test_indexer_death_aborts_the_run(self):
        rc, dt, lines, _blob, reg = self._run(
            nodes=2, order="index", kill_role="indexer")
        self.assertNotEqual(rc, 0, "an indexer death exited 0")
        self.assertTrue(any("is not recoverable -- aborting" in l
                            for l in lines))
        self.assertLess(dt, 20.0)
        self._assert_no_survivors(reg)

    def test_scanner_death_aborts_the_run(self):
        rc, dt, lines, _blob, reg = self._run(
            nodes=2, order="index", kill_role="scanner")
        self.assertNotEqual(rc, 0, "a scanner death exited 0")
        self.assertTrue(any("is not recoverable -- aborting" in l
                            for l in lines))
        self.assertLess(dt, 20.0)
        self._assert_no_survivors(reg)

    def test_fallow_death_aborts_the_run(self):
        rc, dt, lines, _blob, reg = self._run(
            nodes=2, order="index", kill_role="fallow")
        self.assertNotEqual(rc, 0, "a fallow death exited 0")
        self.assertTrue(any("is not recoverable -- aborting" in l
                            for l in lines))
        self.assertLess(dt, 20.0)
        self._assert_no_survivors(reg)

    def test_a_helper_death_leaves_no_surviving_descendant(self):
        """The fatal path must reap what it killed.

        The multi-node fatal path signalled the worker groups and then
        exited WITHOUT reaping them, so a dead worker was still
        observable as a process after the launcher was gone -- which
        reads as "a descendant survived the run" for a process that was
        in fact already dead.
        """
        rc, _dt, _lines, _blob, reg = self._run(
            nodes=2, order="index", kill_role="scanner")
        self.assertNotEqual(rc, 0)
        # The workers are the descendants that outlive a naive teardown.
        workers = reg.get("worker", [])
        self.assertTrue(workers, "no workers were registered")
        self._assert_no_survivors(reg)

    def test_a_tampered_topology_is_refused(self):
        """A map whose length disagrees with --nodes is a config error."""
        rc, _dt, lines, _blob, _reg = self._run(
            nodes=2, order="index", numa_map="0", timeout=60)
        self.assertNotEqual(rc, 0, "a mismatched topology was accepted")
        self.assertTrue(any("--numa-map must hold" in l for l in lines),
                        "the refusal did not explain itself: %r" % lines[:5])

    def test_ordered_mode_requires_a_multi_node_topology(self):
        """--order index on a single node is a configuration error.

        The UMA path orders with a parent-side sort over a GLOBAL
        batch_idx; the launcher's own orderer path is the multi-node
        one. Accepting the combination would silently pick a different
        ordering mechanism than the caller asked for.
        """
        rc, _dt, lines, _blob, _reg = self._run(
            nodes=1, order="index", timeout=60)
        self.assertNotEqual(rc, 0,
                            "--order index was accepted on a single node")
        self.assertTrue(any("--order index requires" in l for l in lines),
                        "the refusal did not explain itself: %r" % lines[:5])


class TestCleanroomNumaRouting(unittest.TestCase):
    """The public-API routing, observed through the cleanroom globals.

    The launcher-level tests above prove the launcher's behaviour. These
    prove that `forkrun.map` actually ROUTES to it when the multi-node
    route is opted into -- and does not when it is not.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="cleanroom-numa-api-")
        cls.plugin = _build_plugin(cls._tmp)
        cls.corpus = os.path.join(cls._tmp, "in.txt")
        with open(cls.corpus, "w") as fh:
            for i in range(LINES):
                fh.write("line %06d\n" % i)
        with open(cls.corpus, "rb") as fh:
            cls.corpus_bytes = fh.read()

    def _map(self, *, numa_opt_in, order="index", nodes="@2"):
        """Run forkrun.map in a child and report the cleanroom globals."""
        code = (
            "import os, sys, importlib\n"
            "sys.path.insert(0, %r)\n"
            "%s"
            "import forkrun\n"
            "R = importlib.import_module('forkrun.run')\n"
            "out = forkrun.map(%r, %r, mode='plugin', nodes=%r,\n"
            "                 order=%r, workers=4, lines=%d)\n"
            "want = open(%r, 'rb').read()\n"
            "print('RECORDS', len(out))\n"
            "print('EXACT', b''.join(out) == want)\n"
            "print('C07', R._CLEANROOM_C07)\n"
            "print('LAST_COMMITTED', R._LAST_COMMITTED)\n"
            % (str(REPO / "python"),
               ("os.environ['FORKRUN_CLEANROOM_NUMA'] = '1'\n"
                if numa_opt_in else ""),
               "%s:copy_slow" % self.plugin, self.corpus, nodes, order,
               BATCH, self.corpus))
        env = dict(os.environ)
        env["FORKRUN_CLEANROOM"] = "map-plugin"
        env.pop("FORKRUN_CLEANROOM_NUMA", None)
        proc = subprocess.run([sys.executable, "-c", code], env=env,
                              capture_output=True, text=True, timeout=180)
        return proc

    def test_multinode_route_requires_the_explicit_opt_in(self):
        """Decision 3 is NOT passed: multi-node must not default to the
        launcher. Without the opt-in the in-process NUMA path runs, and
        the cleanroom globals stay untouched."""
        proc = self._map(numa_opt_in=False)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("EXACT True", proc.stdout)
        self.assertIn("'verdict': None", proc.stdout,
                      "the cleanroom path ran without the opt-in: %s"
                      % proc.stdout)

    def test_multinode_route_serves_the_launcher_when_opted_in(self):
        proc = self._map(numa_opt_in=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("EXACT True", proc.stdout)
        self.assertIn("'verdict': 'complete'", proc.stdout,
                      "the launcher did not certify the run: %s"
                      % proc.stdout)
        # The certificate is the completeness proof: the launcher's
        # committed DATA-frame count must equal what the caller got.
        m = re.search(r"'expected': (\d+), 'observed': (\d+)", proc.stdout)
        self.assertIsNotNone(m, proc.stdout)
        self.assertEqual(m.group(1), m.group(2),
                         "the completeness certificate failed: %s"
                         % proc.stdout)

    def test_unordered_multinode_route_is_complete(self):
        proc = self._map(numa_opt_in=True, order="none")
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("'verdict': 'complete'", proc.stdout)
        m = re.search(r"'expected': (\d+), 'observed': (\d+)", proc.stdout)
        self.assertIsNotNone(m, proc.stdout)
        self.assertEqual(m.group(1), m.group(2))


if __name__ == "__main__":
    unittest.main()
