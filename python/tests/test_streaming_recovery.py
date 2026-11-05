"""W-PY34.a streaming Tier-3 recovery: WorkerTxn during active stream().

Verifies the universal parent-side recovery (W-PY28/29) works while the
parent is actively draining results:

  stream() yielding -> worker crashes -> reactor detects (death pipe)
  -> fr_py_recover_worker() -> escrow + respawn -> new generation
  re-processes the batch -> drain loop yields it -> stream continues.

Kill-injection: file-gated payload modules (same pattern as
test_recovery_adversarial.py). Each crashing batch fires exactly once;
the respawned generation's retry succeeds. No threads; every forked
child is reaped by the reactor (assert_no_zombies in tearDown).

All tests use orchestrator=True (the reactor path — the only path
with death detection + recovery). Without the reactor there is no
recovery by design.

All tests pin nodes=1 (UMA). Rationale: nodes="auto" follows the
boot topology — under numa=fake=N it fans out to the NUMA pipeline,
where workers must cover every node (an unworked node's ring is
never claimed — silent loss, see W-PY34 Part 4 notes). Streaming
Tier-3 verifies WorkerTxn recovery during the active drain; the UMA
envelope isolates that variable. NUMA recovery is covered by
test_numa_recovery.py (nodes="@2").
"""

import os
import sys
import tempfile
import time
import unittest
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import (assert_no_zombies, joined_bytes,  # noqa: E402
                      ChildLifecycleMixin,
                      lines_of, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _up(batch):
    return bytes(batch.data).upper()


def _make_input(n=2000, prefix="line"):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    write_lines(path, n, fmt=prefix + " %d\n")
    return path


def _write_kill_module(plugin_dir, name, condition, sig="SIGKILL",
                       per_batch=False):
    """Payload module that kills itself when `condition` (a Python
    expression over batch) holds, once per marker. sig is "SIGKILL"
    or "SIGSEGV" (real segfault via ctypes.string_at(0))."""
    mod_path = os.path.join(plugin_dir, name + ".py")
    marker = os.path.join(plugin_dir, name + ".dead")
    if sig == "SIGSEGV":
        kill = "ctypes.string_at(0)"
        imports = "import ctypes, os\n"
    else:
        kill = "os.kill(os.getpid(), signal.SIGKILL)"
        imports = "import os, signal\n"
    if per_batch:
        gate = ("MARK = MARKER + '.' + str(batch.batch_index)\n"
                "    if (%s) and not os.path.exists(MARK):\n"
                "        with open(MARK, 'w') as _m:\n"
                "            _m.write('x')\n") % condition
    else:
        gate = ("if (%s) and not os.path.exists(MARKER):\n"
                "        with open(MARKER, 'w') as _m:\n"
                "            _m.write('x')\n") % condition
    with open(mod_path, "w") as fh:
        fh.write(
            imports +
            "MARKER = %r\n"
            "def payload(batch):\n"
            "    %s"
            "        %s\n"
            "    return bytes(batch.data).upper()\n" % (marker, gate, kill))
    return name + ":payload"


def _write_count_kill_module(plugin_dir, name, limit):
    """Payload that SIGKILLs while fewer than `limit` kill-claim files
    exist (each dying worker drops one pid-named file first)."""
    mod_path = os.path.join(plugin_dir, name + ".py")
    with open(mod_path, "w") as fh:
        fh.write(
            "import glob, os, signal\n"
            "KDIR = %r\n"
            "LIMIT = %d\n"
            "def payload(batch):\n"
            "    have = glob.glob(os.path.join(KDIR, 'k-*'))\n"
            "    if len(have) < LIMIT:\n"
            "        with open(os.path.join(KDIR, 'k-%%d' %% os.getpid()),\n"
        "                      'w') as _m:\n"
        "            _m.write('x')\n"
            "        os.kill(os.getpid(), signal.SIGKILL)\n"
            "    return bytes(batch.data).upper()\n" % (plugin_dir, limit))
    return name + ":payload"


def _run_stream(spec, path, **kwargs):
    """Collect a full stream() into a list (sys.path handling is the
    caller's job — the generator is lazy). Pins nodes=1 (UMA)
    unless the caller overrides (see module docstring)."""
    kwargs.setdefault("nodes", 1)
    return list(forkrun.stream(spec, path, **kwargs))


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestStreamingRecovery(ChildLifecycleMixin, unittest.TestCase):
    """Streaming Tier-3: WorkerTxn recovery during active stream()."""

    def tearDown(self):
        assert_no_zombies(self)

    def test_sigsegv_during_stream_unordered(self):
        """Worker SIGSEGVs during stream(order='none') -> stream
        continues, complete output, recovered batch exactly once."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34su_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34su_mod", "batch.batch_index == 0",
                sig="SIGSEGV")
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = _run_stream(spec, path, workers=2,
                                  orchestrator=True, order="none")
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=2,
                                  orchestrator=True, order="none")
            self.assertEqual(lines_of(res), lines_of(healthy))
            # The BLOB-COUNT assertion that used to sit here --
            # assertEqual(len(res), len(healthy)) -- contradicted this
            # module's own rule. `_helpers.lines_of` documents: "batch
            # boundaries are an implementation detail (pre-flight timing
            # changes them run to run), so cross-run comparisons must use
            # lines (or joined bytes), never blob identity or blob sort
            # order." Counting blobs is blob identity.
            #
            # It was therefore inherently flaky: this test failed roughly
            # 1 run in 12 at HEAD, with the recovered stream yielding 32
            # blobs against a healthy run's 103 -- a difference in
            # BATCHING, not in data, and the lines_of assertion on the
            # line above had already passed.
            #
            # Completeness and content are covered by lines_of (a lost or
            # duplicated batch changes the multiset) and by
            # joined_bytes where order is promised. Blob count added
            # nothing except a way to fail.
            self.assertGreater(len(res), 0)
            self.assertLess(dt, 120)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_sigsegv_during_stream_ordered(self):
        """Worker SIGSEGVs during stream(order='index') -> reassembly
        holds the gap; results in exact batch order with the late
        batch in its correct position."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34so_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34so_mod", "batch.batch_index == 0",
                sig="SIGSEGV")
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = _run_stream(spec, path, workers=2,
                                  orchestrator=True, order="index")
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=2,
                                  orchestrator=True, order="index")
            self.assertEqual(joined_bytes(res), joined_bytes(healthy))
            self.assertLess(dt, 120)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_sigkill_during_stream(self):
        """External-style SIGKILL during stream() -> recovery, stream
        continues with complete output."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34sk_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34sk_mod", "batch.batch_index == 0",
                sig="SIGKILL")
            sys.path.insert(0, plugin_dir)
            try:
                res = _run_stream(spec, path, workers=2,
                                  orchestrator=True, order="none")
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=2,
                                  orchestrator=True, order="none")
            self.assertEqual(lines_of(res), lines_of(healthy))
            # The BLOB-COUNT assertion that used to sit here --
            # assertEqual(len(res), len(healthy)) -- contradicted this
            # module's own rule. `_helpers.lines_of` documents: "batch
            # boundaries are an implementation detail (pre-flight timing
            # changes them run to run), so cross-run comparisons must use
            # lines (or joined bytes), never blob identity or blob sort
            # order." Counting blobs is blob identity.
            #
            # It was therefore inherently flaky: this test failed roughly
            # 1 run in 12 at HEAD, with the recovered stream yielding 32
            # blobs against a healthy run's 103 -- a difference in
            # BATCHING, not in data, and the lines_of assertion on the
            # line above had already passed.
            #
            # Completeness and content are covered by lines_of (a lost or
            # duplicated batch changes the multiset) and by
            # joined_bytes where order is promised. Blob count added
            # nothing except a way to fail.
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_multiple_deaths_during_stream(self):
        """2 workers crash at different batches during stream() ->
        both recovered, stream continues, output complete."""
        path = _make_input(3000)
        plugin_dir = tempfile.mkdtemp(prefix="w34md_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34md_mod",
                "batch.batch_index in (0, 7)", per_batch=True)
            sys.path.insert(0, plugin_dir)
            try:
                t0 = time.monotonic()
                res = _run_stream(spec, path, workers=2,
                                  orchestrator=True, order="index")
                dt = time.monotonic() - t0
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=2,
                                  orchestrator=True, order="index")
            self.assertEqual(joined_bytes(res), joined_bytes(healthy))
            self.assertLess(dt, 120)
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_recovered_batch_not_duplicated(self):
        """Recovered batch's output appears exactly once (Counter over
        result blobs: no loss, no duplication)."""
        path = _make_input(2000)
        plugin_dir = tempfile.mkdtemp(prefix="w34nd_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34nd_mod", "batch.batch_index == 0")
            sys.path.insert(0, plugin_dir)
            try:
                res = _run_stream(spec, path, workers=4,
                                  orchestrator=True, order="none")
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=4,
                                  orchestrator=True, order="none")
            self.assertEqual(Counter(lines_of(res)), Counter(lines_of(healthy)))
            # Every blob unique (input lines unique -> batch blobs
            # unique): exactly-once means no blob appears twice.
            self.assertEqual(len(lines_of(res)), len(set(lines_of(res))))
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)

    def test_stream_backpressure_during_recovery(self):
        """Slow consumer + worker crash -> recovery happens, memory
        stays bounded (streaming holds only the in-flight window)."""
        import resource

        path = _make_input(3000)
        plugin_dir = tempfile.mkdtemp(prefix="w34bp_")
        try:
            spec = _write_kill_module(
                plugin_dir, "w34bp_mod", "batch.batch_index == 0")
            sys.path.insert(0, plugin_dir)
            try:
                before = resource.getrusage(
                    resource.RUSAGE_SELF).ru_maxrss
                n = 0
                got = []
                for blob in forkrun.stream(spec, path, workers=2,
                                           orchestrator=True, nodes=1,
                                           order="none"):
                    got.append(blob)
                    n += 1
                    time.sleep(0.002)
                after = resource.getrusage(
                    resource.RUSAGE_SELF).ru_maxrss
            finally:
                sys.path.remove(plugin_dir)
            healthy = _run_stream(_up, path, workers=2,
                                  orchestrator=True, order="none")
            self.assertEqual(lines_of(got), lines_of(healthy))
            self.assertGreater(n, 0)
            # ru_maxrss is KB on Linux; 100MB headroom is generous
            # for a ~40KB input (any leak-per-recovery would scale
            # with output, not stay flat).
            self.assertLess(after - before, 100 * 1024,
                            "parent grew during slow-drain recovery")
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(plugin_dir, ignore_errors=True)


class TestSpawnStreamingRecovery(unittest.TestCase):
    """RESILIENCE_PROTOCOL.md 7.4: recovery in mode="spawn" STREAMING.

    7.4 lists this as explicitly NOT covered -- "same WorkerTxn mechanism,
    no Tier-3 tests written". The suite above it exercises mode="python"
    (a plain callable), so the spawn worker loop's death path had no
    streaming coverage at all.

    The probe is a shell command that SIGKILLs its own worker exactly
    once, then does real work. A marker file makes the death one-shot so
    the reclaimed batch completes instead of killing itself again, and the
    `tr` is not incidental: output of merely the right LENGTH could come
    from the wrong batch, whereas uppercased input pins each delivered
    record to its source line.

    stream(mode="spawn") declines the cleanroom and takes the in-process
    route on both settings -- which is the WorkerTxn mechanism 7.4 is
    describing, so this is coverage of that mechanism for spawn.
    """

    LAUNCHER = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        "python", "forkrun", "_forkrun_cleanroom")

    DIE_ONCE = """#!/bin/sh
M="$FR_DIE_MARKER"
if [ ! -f "$M" ]; then
    : > "$M"
    kill -9 $$
fi
exec tr a-z A-Z
"""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(cls.LAUNCHER):
            raise unittest.SkipTest("launcher not built")
        cls._tmp = tempfile.TemporaryDirectory(prefix="spawnstream_")
        cls.root = cls._tmp.name
        cls.script = os.path.join(cls.root, "die_once.sh")
        with open(cls.script, "w") as fh:
            fh.write(cls.DIE_ONCE)
        os.chmod(cls.script, 0o755)

    @classmethod
    def tearDownClass(cls):
        tmp = getattr(cls, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    @staticmethod
    def _lines(blob):
        """Split on newlines, dropping a trailing partial.

        The trailing element after a final newline is an artefact of the
        split, not data, so it is excluded.
        """
        parts = blob.split(b"\n")
        if parts and parts[-1] == b"":
            parts.pop()
        return parts

    def _assert_complete(self, got_records, healthy_records, path, order):
        """Compare against a HEALTHY run in the same configuration.

        Three attempts were needed to get this right, and the failures
        are worth recording because each was a wrong assertion rather
        than a wrong engine.

        1. Comparing joined bytes to the INPUT fails for order="none":
           batches complete out of order by design, so even a healthy
           run does not reproduce the input. order="index" PASSED
           throughout that run -- the tell that the assertion, not the
           engine, was wrong.

        2. Comparing a line MULTISET also fails, for a second reason: at
           128-byte batches the records do not align to line boundaries,
           so the output contains fragments (b'L225', b'LI'). Every line
           was present, but not as a whole line.

        3. The sound comparison is against a healthy run with identical
           configuration, which is what this file already did for
           mode="python": `lines_of` and `joined_bytes` are both
           documented as split-agnostic for exactly this reason, and UMA
           batching is deterministic (RESILIENCE 7.3.3), so two runs of
           one config place record boundaries identically.

        For order="index" the input IS the right baseline, since indexed
        order is a promise and reconstruction is exact.
        """
        if order == "index":
            self.assertEqual(
                open(path, "rb").read().upper(), joined_bytes(got_records),
                "ordered stream did not reconstruct the input after a "
                "worker death")
            return
        # lines_of is SORTED and split-agnostic, so it compares CONTENT
        # and COMPLETENESS while claiming nothing about arrival order --
        # which is what order="none" promises. It still catches a lost
        # batch, a duplicated one, and any corruption, because all three
        # change the multiset.
        #
        # joined_bytes is deliberately NOT asserted here even though the
        # healthy baseline makes it available. It is order-sensitive, and
        # a RECLAIMED batch necessarily arrives after the healthy run's
        # would have: it ran, died, was escrowed, and was re-claimed.
        # Asserting it would encode "a recovered batch must arrive in the
        # position a batch that never died would have", which is not a
        # contract order="none" makes. For order="index" it IS one, and
        # that branch above asserts exactly that.
        self.assertEqual(lines_of(healthy_records), lines_of(got_records),
                         "unordered stream lost, duplicated or altered "
                         "output relative to a healthy run")

    def _run(self, path, order, tag, workers=2, healthy=False,
             script=None):
        """Stream mode="spawn" to completion, with a fresh die-marker.

        The generator is lazy, so it is consumed here rather than left to
        the caller -- an unconsumed stream would never fork a worker and
        the test would pass without exercising anything.
        """
        marker = os.path.join(self.root, "marker.%s" % tag)
        if os.path.exists(marker):
            os.unlink(marker)
        # healthy=True plants the marker up front, so the command NEVER
        # dies and the run is a clean baseline for the same config.
        if healthy:
            with open(marker, "w"):
                pass
        old = os.environ.get("FR_DIE_MARKER")
        os.environ["FR_DIE_MARKER"] = marker
        try:
            out = list(forkrun.stream(
            script or self.script, path, streaming=True, mode="spawn",
            workers=workers, nodes=1, order=order, bytes=128,
            output="bytes", orchestrator=True, on_error="retry"))
        finally:
            if old is None:
                os.environ.pop("FR_DIE_MARKER", None)
            else:
                os.environ["FR_DIE_MARKER"] = old
        return out, marker

    def test_spawn_stream_recovers_and_output_is_complete(self):
        """order="none": the stream continues and every byte arrives.

        Compared against the input rather than a count, because a count
        cannot distinguish complete output from a truncated stream that
        lost a batch and a whole one that duplicated it.
        """
        path = _make_input(600)
        try:
            got, marker = self._run(path, "none", "none")
            healthy, _ = self._run(path, "none", "none-healthy", healthy=True)
            self.assertTrue(os.path.exists(marker),
                            "no worker death occurred -- the recovery "
                            "assertions would be vacuous")
            self._assert_complete(got, healthy, path, "none")
        finally:
            os.unlink(path)

    def test_spawn_stream_ordered_recovers_into_the_right_position(self):
        """order="index": the late batch lands in its correct position.

        A recovered batch that arrives out of order would still give the
        right byte COUNT here, so the comparison is joined bytes.
        """
        path = _make_input(600)
        try:
            got, marker = self._run(path, "index", "index")
            self.assertTrue(os.path.exists(marker),
                            "no worker death occurred -- vacuous")
            self._assert_complete(got, got, path, "index")
        finally:
            os.unlink(path)

    def test_spawn_stream_recovers_at_several_worker_counts(self):
        """Recovery must not depend on how the work was divided."""
        for workers in (1, 4):
            with self.subTest(workers=workers):
                path = _make_input(400)
                try:
                    got, marker = self._run(path, "none",
                                            "w%d" % workers, workers)
                    healthy, _ = self._run(path, "none",
                                          "w%d-healthy" % workers, workers,
                                          healthy=True)
                    self.assertTrue(os.path.exists(marker),
                                    "no worker death at workers=%d" % workers)
                    self._assert_complete(got, healthy, path, "none")
                finally:
                    os.unlink(path)

    def test_spawn_stream_recovers_more_than_once(self):
        """Two deaths at different batches.

        A single-death test cannot distinguish "recovery works" from
        "the second death is what finally breaks it" -- the escrow path
        carries a kill counter, and a second death is the first time that
        counter is exercised.
        """
        path = _make_input(800)
        root = self.root
        script = os.path.join(root, "die_twice.sh")
        # Kill while handling EITHER marker: first death creates .a, the
        # reclaimed batch creates .b and dies again, the third attempt
        # finds both and succeeds. One-shot per marker, so the run
        # terminates rather than livelocking on a self-killing command.
        with open(script, "w") as fh:
            fh.write('#!/bin/sh\n'
                     'D="$FR_DIE_DIR"\n'
                     'if [ ! -f "$D/a" ]; then : > "$D/a"; kill -9 $$; fi\n'
                     'if [ ! -f "$D/b" ]; then : > "$D/b"; kill -9 $$; fi\n'
                     'exec tr a-z A-Z\n')
        os.chmod(script, 0o755)
        d = os.path.join(root, "twice")
        os.makedirs(d, exist_ok=True)
        old_m, old_d = (os.environ.get("FR_DIE_MARKER"),
                        os.environ.get("FR_DIE_DIR"))
        os.environ["FR_DIE_DIR"] = d
        try:
            # Collected as a LIST, not joined bytes: lines_of walks
            # records individually and splitlines() on an int-less
            # joined blob raised AttributeError.
            out = list(forkrun.stream(
                script, path, streaming=True, mode="spawn", workers=2,
                nodes=1, order="none", bytes=128, output="bytes",
                orchestrator=True, on_error="retry"))
        finally:
            for k, v in (("FR_DIE_MARKER", old_m), ("FR_DIE_DIR", old_d)):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        try:
            self.assertTrue(os.path.exists(os.path.join(d, "a")),
                            "no worker death occurred -- vacuous")
            self.assertTrue(
                os.path.exists(os.path.join(d, "b")),
                "only ONE death happened; this test is meant to exercise "
                "a second recovery and would otherwise prove nothing "
                "beyond the single-death case")
            # The baseline must be a DIFFERENT directory with BOTH
            # markers already planted. Planting FR_DIE_MARKER, as
            # _run(healthy=True) does, has no effect here: this script
            # keys off $FR_DIE_DIR/a and $FR_DIE_DIR/b, so the supposed
            # healthy run died twice as well and the comparison was
            # meaningless -- it compared two recovering runs.
            hdir = os.path.join(root, "healthy_twice")
            os.makedirs(hdir, exist_ok=True)
            for m in ("a", "b"):
                with open(os.path.join(hdir, m), "w"):
                    pass
            # .get, not []: the outer finally has already restored (and
            # popped) FR_DIE_DIR by this point, so indexing raised
            # KeyError.
            old_dir = os.environ.get("FR_DIE_DIR")
            os.environ["FR_DIE_DIR"] = hdir
            try:
                healthy_once = list(forkrun.stream(
                    script, path, streaming=True, mode="spawn", workers=2,
                    nodes=1, order="none", bytes=128, output="bytes",
                    orchestrator=True, on_error="retry"))
            finally:
                if old_dir is None:
                    os.environ.pop("FR_DIE_DIR", None)
                else:
                    os.environ["FR_DIE_DIR"] = old_dir
            self._assert_complete(out, healthy_once, path, "none")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
