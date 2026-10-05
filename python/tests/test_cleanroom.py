# W-CR1: cleanroom (exec-based launcher) integration tests.
#
# The lesson that shaped this file: an earlier smoke test asserted only
# that both flag settings produced the same totals -- which they did,
# because the hook was DEAD CODE and both runs took the in-process path.
# So the first test here proves the launcher actually EXECUTES, by
# recording the execv call, before anything asserts on output.
import os
import sys
import glob
import time
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forkrun  # noqa: E402
from forkrun.run import (  # noqa: E402
    _cleanroom_eligible, _cleanroom_enabled, _cleanroom_explicit,
    _cleanroom_launcher_path)

PLUGIN = None
for _cand in (
        os.environ.get("FORKRUN_TEST_PLUGIN"),
        "/tmp/opencode/mlbench/ml_plugin_light.so",
):
    if _cand and os.path.exists(_cand):
        PLUGIN = _cand
        break
HAVE_PLUGIN = PLUGIN is not None


def _spec():
    return "%s:ml_process_light" % PLUGIN


def _make_input(n=2000, path=None):
    import tempfile
    if path is None:
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
    with open(path, "w") as fh:
        for i in range(n):
            fh.write('{"eid":"e%d","uid":1,"iid":2,"ts":1700000000,'
                     '"et":"view","dev":"ios","dur":5}\n' % i)
    return path


def _joined(res):
    return b"".join(bytes(x) for x in res)


def _find_launcher():
    """pid of the live cleanroom launcher among our children."""
    for d in glob.glob("/proc/self/task/*/children"):
        try:
            pids = [int(x) for x in open(d).read().split()]
        except OSError:
            continue
        for p in pids:
            try:
                with open("/proc/%d/comm" % p, "rb") as fh:
                    # /proc/pid/comm is capped at 15 chars (TASK_COMM_LEN),
                    # so "_forkrun_cleanroom" never matches in full.
                    if fh.read().startswith(b"_forkrun"):
                        return p
            except OSError:
                pass
    return None


def _descendants_of(pid):
    """Every descendant pid of `pid`, via /proc children files."""
    out = set()
    stack = [pid]
    while stack:
        cur = stack.pop()
        for d in glob.glob("/proc/%d/task/*/children" % cur):
            try:
                kids = [int(x) for x in open(d).read().split()]
            except OSError:
                continue
            for k in kids:
                if k not in out:
                    out.add(k)
                    stack.append(k)
    return out


class TestCleanroomHelpers(unittest.TestCase):
    """The envelope predicate -- pure, no plugin or launcher needed."""

    def test_disabled_by_default(self):
        # The default is OFF. It was briefly ON (5ae0b0a0) and reversed:
        # the envelope excludes orchestrator=True, which is map()'s own
        # default, so a plain map() never took the cleanroom anyway --
        # and the launcher runs no supervisor, so defaulting it ON would
        # have meant defaulting crash recovery OFF for every caller who
        # did not ask for it.
        old = os.environ.pop("FORKRUN_CLEANROOM", None)
        try:
            self.assertFalse(_cleanroom_enabled())
            self.assertFalse(_cleanroom_explicit())
        finally:
            if old is not None:
                os.environ["FORKRUN_CLEANROOM"] = old

    def test_explicit_opt_out_disables(self):
        old = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "0"
        try:
            self.assertFalse(_cleanroom_enabled())
            self.assertFalse(_cleanroom_explicit())
        finally:
            if old is None:
                os.environ.pop("FORKRUN_CLEANROOM", None)
            else:
                os.environ["FORKRUN_CLEANROOM"] = old

    def test_explicit_request_is_flagged(self):
        old = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        try:
            self.assertTrue(_cleanroom_enabled())
            self.assertTrue(_cleanroom_explicit())
        finally:
            if old is None:
                os.environ.pop("FORKRUN_CLEANROOM", None)
            else:
                os.environ["FORKRUN_CLEANROOM"] = old

    def test_truthy_and_falsey_spellings(self):
        old = os.environ.get("FORKRUN_CLEANROOM")
        try:
            for v in ("1", "yes", "on", "TRUE", " true "):
                os.environ["FORKRUN_CLEANROOM"] = v
                self.assertTrue(_cleanroom_enabled(), v)
            for v in ("0", "", "no", "off", "false"):
                os.environ["FORKRUN_CLEANROOM"] = v
                self.assertFalse(_cleanroom_enabled(), v)
        finally:
            if old is None:
                os.environ.pop("FORKRUN_CLEANROOM", None)
            else:
                os.environ["FORKRUN_CLEANROOM"] = old

    def test_envelope_accepts_only_what_it_can_honour(self):
        p = _make_input(10)
        self.addCleanup(lambda: os.path.exists(p) and os.unlink(p))
        ok, _ = _cleanroom_eligible(p, "plugin", 1, "none", False, False)
        self.assertTrue(ok)
        # Each of these would change RESULTS, not just speed.
        for args in (
                (p, "python", 1, "none", False, False),   # no plugin
                (p, "plugin", 4, "none", False, False),   # multi-node
                (p, "plugin", 1, "index", False, False),  # needs orderer
                (p, "plugin", 1, "none", True, False),    # strict_poison
                (p, "plugin", 1, "none", False, True),    # orchestrator
                ("/no/such/file", "plugin", 1, "none", False, False),
        ):
            ok, why = _cleanroom_eligible(*args)
            self.assertFalse(ok, "should reject %r" % (args,))
            self.assertTrue(why)


@unittest.skipUnless(HAVE_PLUGIN, "test plugin not available")
class TestCleanroomExecutes(unittest.TestCase):
    """Prove the launcher is REALLY taken, then that it is correct."""

    def setUp(self):
        self._old = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.path = _make_input(2000)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass
        if self._old is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._old

    def _run_marked(self, **kw):
        """Run map() with the cleanroom entry point instrumented.

        The marker is recorded in the PARENT, before any fork. An
        earlier version of this probe spied on os.execv and wrote a
        marker file from inside the forked child -- which HANGS THE
        SUITE: fork()ing a multi-threaded process and then doing Python
        work in the child is the documented deadlock hazard (the same
        one Python 3.12+ warns about at every os.fork() site in
        run.py). Nothing in a forked child may touch Python here.

        A parent-side marker is also the RIGHT assertion: the defect
        this file exists to catch was a hook that never fired, which a
        parent-side marker detects exactly, and which an exec-status
        check alone would not.
        """
        # NB: sys.modules, NOT `import forkrun.run as R` -- the package
        # re-exports a function named `run`, so attribute access on the
        # imported name lands on the function, not this module.
        R = sys.modules["forkrun.run"]
        real = R._execute_cleanroom
        seen = []

        def spy(*a, **k):
            seen.append(True)
            return real(*a, **k)

        R._execute_cleanroom = spy
        self.addCleanup(setattr, R, "_execute_cleanroom", real)
        out = forkrun.map(_spec(), self.path, workers=2, nodes=1,
                          mode="plugin", output="bytes", **kw)
        return out, bool(seen)

    def test_cleanroom_path_is_actually_taken(self):
        """The load-bearing test: FORKRUN_CLEANROOM=1 must REACH the
        launcher. A hook that never fires is invisible to every other
        assertion in this file -- an earlier version asserted only that
        both flag settings produced identical totals, which they did
        because both took the in-process path.
        """
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        out, taken = self._run_marked(orchestrator=False)
        self.assertTrue(
            taken,
            "FORKRUN_CLEANROOM=1 never reached the launcher -- the hook "
            "is dead code and this whole file would prove nothing")
        self.assertEqual(len(_joined(out)), 2000)

    def test_matches_in_process_content(self):
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        cr, _ = self._run_marked(orchestrator=False)
        old = os.environ["FORKRUN_CLEANROOM"]
        os.environ["FORKRUN_CLEANROOM"] = "0"
        try:
            ref = forkrun.map(_spec(), self.path, workers=2, nodes=1,
                              mode="plugin", output="bytes",
                              orchestrator=False)
        finally:
            os.environ["FORKRUN_CLEANROOM"] = old
        # Batch boundaries may differ (the launcher spills and scans in
        # its own process); the delivered BYTES must not.
        self.assertEqual(_joined(cr), _joined(ref))
        self.assertEqual(len(_joined(cr)), 2000)

    def test_empty_input_yields_empty_result(self):
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        empty = _make_input(0, path=self.path + ".empty")
        self.addCleanup(lambda: os.path.exists(empty) and os.unlink(empty))
        out = forkrun.map(_spec(), empty, workers=2, nodes=1,
                          mode="plugin", output="bytes",
                          orchestrator=False)
        self.assertEqual(len(out), 0)

    def test_outside_envelope_warns_and_stays_correct(self):
        # orchestrator=True is the DEFAULT, and the launcher has no
        # reactor. It must refuse loudly and still return right answers.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = forkrun.map(_spec(), self.path, workers=2, nodes=1,
                              mode="plugin", output="bytes")
        self.assertEqual(len(_joined(out)), 2000)
        self.assertTrue(
            any("FORKRUN_CLEANROOM" in str(w.message) for w in caught),
            "expected a loud warning, got %r"
            % [str(w.message) for w in caught])

    def test_order_index_refuses_cleanroom(self):
        # order="index" must NOT silently come back permuted.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = forkrun.map(_spec(), self.path, workers=2, nodes=1,
                              mode="plugin", output="bytes",
                              order="index", orchestrator=False)
        self.assertTrue(
            any("FORKRUN_CLEANROOM" in str(w.message) for w in caught),
            "order='index' must warn that the launcher was skipped")
        self.assertEqual(len(_joined(out)), 2000)


@unittest.skipUnless(HAVE_PLUGIN, "test plugin not available")
class TestCleanroomFaultParity(unittest.TestCase):
    """W-CR1: the launcher's fault policy must match the in-process path.

    This is the gate for flipping the default ON. The launcher takes
    --on-error/--retry across the exec boundary, so retry/skip/fail-fast
    and FORKRUN_RETRY_LIMIT are TRANSPORTED rather than refused -- but
    transported is not the same as honoured, and only a comparison
    against the in-process path can show which.
    """

    V1_SO = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        "python", "tests", "plugins", "test_plugin_v1.so")

    def setUp(self):
        if not os.path.exists(self.V1_SO):
            self.skipTest("test_plugin_v1.so not built")
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        self._old_cr = os.environ.get("FORKRUN_CLEANROOM")
        self._old_rl = os.environ.get("FORKRUN_RETRY_LIMIT")
        self.path = _make_input(600)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for p in (self.path,):
            try:
                os.unlink(p)
            except OSError:
                pass
        for k, v in (("FORKRUN_CLEANROOM", self._old_cr),
                     ("FORKRUN_RETRY_LIMIT", self._old_rl)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _up(self):
        return self.V1_SO + ":process_v1"

    def _fail(self):
        return self.V1_SO + ":always_fail_v1"

    def _both(self, spec, **kw):
        """Run once per path. orchestrator=False pins the cleanroom
        inside its envelope so this compares FAULT POLICY, not topology
        or supervision."""
        kw.setdefault("nodes", 1)
        kw.setdefault("workers", 1)
        kw.setdefault("orchestrator", False)
        os.environ["FORKRUN_CLEANROOM"] = "0"
        a = forkrun.map(spec, self.path, mode="plugin", output="bytes", **kw)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        b = forkrun.map(spec, self.path, mode="plugin", output="bytes", **kw)
        return a, b

    def test_success_identical(self):
        a, b = self._both(self._up())
        self.assertEqual(_joined(a), _joined(b))
        self.assertGreater(len(_joined(a)), 0)

    def test_retry_then_poison_identical(self):
        # always_fail_v1 with the default retry limit: every batch is
        # retried then poisoned, so both paths must yield nothing.
        a, b = self._both(self._fail())
        self.assertEqual(a, [])
        self.assertEqual(b, [])
        self.assertEqual(_joined(a), _joined(b))

    def test_skip_identical(self):
        a, b = self._both(self._fail(), on_error="skip")
        self.assertEqual(_joined(a), _joined(b))
        self.assertEqual(a, [])

    def test_fail_fast_raises_both(self):
        for cr in ("0", "1"):
            os.environ["FORKRUN_CLEANROOM"] = cr
            with self.assertRaises(
                    RuntimeError, msg="cr=%s did not raise" % cr):
                forkrun.map(self._fail(), self.path, mode="plugin",
                            output="bytes", nodes=1, workers=1,
                            on_error="fail-fast", orchestrator=False)

    def test_retry_limit_is_transported(self):
        # FORKRUN_RETRY_LIMIT=0 poisons on the FIRST failure, so the
        # launcher must not silently use its own default of 3. Both
        # paths must still agree, and agree on empty.
        os.environ["FORKRUN_RETRY_LIMIT"] = "0"
        a, b = self._both(self._fail())
        self.assertEqual(_joined(a), _joined(b))

    def test_retry_limit_custom_agrees(self):
        os.environ["FORKRUN_RETRY_LIMIT"] = "1"
        a, b = self._both(self._fail())
        self.assertEqual(_joined(a), _joined(b))


@unittest.skipUnless(HAVE_PLUGIN, "test plugin not available")
class TestCleanroomStreaming(unittest.TestCase):
    """W-CR3: streaming through the public stream() API.

    The C capability was verified standalone before any wiring (first
    result at 2.8 ms on a 200k-record pipe). These tests pin the
    PYTHON half: byte-exactness against the in-process path, liveness,
    and -- the one that would hurt most -- teardown when the caller
    abandons the stream early.
    """

    def setUp(self):
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        self.n = 40000
        self._old = os.environ.get("FORKRUN_CLEANROOM")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._old is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._old

    def _lines(self, n):
        for i in range(n):
            yield ('{"eid":"e%d","uid":1,"iid":2,"ts":1700000000,'
                   '"et":"view","dev":"ios","dur":5}\n' % i).encode()

    def _pipe_with_producer(self, n, delay=0.0):
        """A pipe fed by a background thread; returns (read_fd, thread)."""
        import threading
        r, w = os.pipe()

        def run():
            buf = []
            for i in range(n):
                buf.append('{"eid":"e%d","uid":1,"iid":2,"ts":1700000000,'
                           '"et":"view","dev":"ios","dur":5}\n' % i)
                if len(buf) >= 500:
                    os.write(w, "".join(buf).encode())
                    buf = []
                if delay:
                    time.sleep(delay)
            if buf:
                os.write(w, "".join(buf).encode())
            os.close(w)

        th = threading.Thread(target=run, daemon=True)
        th.start()
        return r, th

    def _drain(self, fd):
        out = []
        for blob in forkrun.stream(
                _spec(), fd, mode="plugin", workers=4, nodes=1,
                streaming=True, orchestrator=False):
            out.append(bytes(blob))
        return b"".join(out)

    def test_stream_matches_in_process(self):
        r, th = self._pipe_with_producer(self.n)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        streamed = self._drain(r)
        th.join()
        os.close(r)
        # Reference: same records, materialized, in-process.
        path = _make_input(self.n)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        os.environ["FORKRUN_CLEANROOM"] = "0"
        ref = b"".join(bytes(x) for x in forkrun.map(
            _spec(), path, workers=4, nodes=1, mode="plugin",
            output="bytes", orchestrator=False))
        self.assertEqual(len(streamed), len(ref))
        self.assertEqual(streamed, ref)

    def test_stream_is_live(self):
        # A slow producer: if the launcher buffered to EOF, the first
        # result could not arrive until the producer finished.
        r, th = self._pipe_with_producer(self.n, delay=0.00005)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        t0 = time.time()
        first = None
        for blob in forkrun.stream(
                _spec(), r, mode="plugin", workers=4, nodes=1,
                streaming=True, orchestrator=False):
            if first is None:
                first = time.time() - t0
        th.join()
        os.close(r)
        self.assertIsNotNone(first, "no result arrived at all")
        self.assertLess(
            first, 5.0,
            "first result took %.1fs -- the launcher is buffering to EOF "
            "instead of streaming" % (first,))

    def test_abandon_early_does_not_hang_or_leak(self):
        """Abandon mid-stream: nothing may survive.

        This test used to assert that the PRODUCER completes, and it
        passed -- but only because of the leak it was supposed to catch.
        Abandoning killed the launcher while its children survived, and
        the orphaned spill child kept draining the producer's pipe, so
        the producer ran to completion. "Producer finished" was
        therefore evidence of the bug, not of correctness.

        PR_SET_PDEATHSIG in the launcher fixes that: the subtree dies,
        and the producer then blocks on a full pipe -- correctly, since
        no reader is left. So the assertion has to change to the
        property that actually matters: NO DESCENDANT SURVIVES.

        The test also closes its own read fd before streaming (the
        library dups it), so the producer gets EPIPE and unwinds rather
        than parking on a pipe whose only reader is this process.
        """
        r, th = self._pipe_with_producer(200000)
        r2 = os.dup(r)
        os.close(r)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        gen = forkrun.stream(
            _spec(), r2, mode="plugin", workers=4, nodes=1,
            streaming=True, orchestrator=False)
        got = next(iter(gen))
        self.assertTrue(len(bytes(got)) > 0)
        # The library has now dup'd the source and closed its own copy,
        # so dropping ours leaves the spill child as the only reader.
        # That is what lets the producer see EPIPE once the subtree dies,
        # instead of parking forever on a pipe nobody is draining.
        os.close(r2)

        # Snapshot the launcher's whole subtree BEFORE abandoning --
        # afterwards the launcher is gone and there is nothing to walk.
        launch_pid = _find_launcher()
        self.assertIsNotNone(launch_pid, "launcher pid not found")
        before = _descendants_of(launch_pid)
        self.assertTrue(before, "launcher had no descendants to leak")

        gen.close()

        # The whole point: nothing outlives the launcher.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            alive = [k for k in before
                     if os.path.exists("/proc/%d" % k)]
            if not alive:
                break
            time.sleep(0.1)
        self.assertFalse(
            os.path.exists("/proc/%d" % launch_pid),
            "launcher survived gen.close()")
        survivors = [k for k in before
                     if os.path.exists("/proc/%d" % k)]
        self.assertEqual(
            survivors, [],
            "descendants survived abandonment -- PDEATHSIG not effective: "
            "%r" % (survivors,))
        # And the producer must unwind rather than park on a full pipe.
        th.join(timeout=30)
        self.assertFalse(th.is_alive(),
                         "producer still blocked after abandonment")
        th.join(timeout=5)

    def test_stream_outside_envelope_falls_back(self):
        # orchestrator=True is the default and is OUTSIDE the envelope;
        # it must still produce correct output rather than break.
        r, th = self._pipe_with_producer(5000)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        out = b"".join(bytes(x) for x in forkrun.stream(
            _spec(), r, mode="plugin", workers=2, nodes=1,
            streaming=True))
        th.join()
        os.close(r)
        self.assertGreater(len(out), 0)


if __name__ == "__main__":
    unittest.main()
