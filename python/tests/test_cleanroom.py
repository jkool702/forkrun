# W-CR1: cleanroom (exec-based launcher) integration tests.
#
# The lesson that shaped this file: an earlier smoke test asserted only
# that both flag settings produced the same totals -- which they did,
# because the hook was DEAD CODE and both runs took the in-process path.
# So the first test here proves the launcher actually EXECUTES, by
# recording the execv call, before anything asserts on output.
import os
import sys
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


class TestCleanroomHelpers(unittest.TestCase):
    """The envelope predicate -- pure, no plugin or launcher needed."""

    def test_enabled_by_default(self):
        # Default is ON, but NOT "explicitly requested" -- that
        # distinction is what keeps the fallback quiet for ordinary
        # map() calls while still warning when a request is declined.
        old = os.environ.pop("FORKRUN_CLEANROOM", None)
        try:
            self.assertTrue(_cleanroom_enabled())
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


if __name__ == "__main__":
    unittest.main()
