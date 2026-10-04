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
    _cleanroom_eligible, _cleanroom_enabled, _cleanroom_launcher_path)

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

    def test_disabled_without_env(self):
        old = os.environ.pop("FORKRUN_CLEANROOM", None)
        try:
            self.assertFalse(_cleanroom_enabled())
        finally:
            if old is not None:
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

    def _run_with_exec_probe(self, **kw):
        """Run map() with os.execv instrumented to leave a marker.

        The marker is written BEFORE the real exec, so the child records
        that the launcher was invoked and then genuinely becomes it.
        Totals alone cannot prove this -- that was the original bug.
        """
        import forkrun.run as R
        marker = self.path + ".execmarker"
        real_execv = os.execv

        def spy(path, argv):
            with open(marker, "w") as fh:
                fh.write("%s\n" % " ".join(map(str, argv)))
            return real_execv(path, argv)

        os.execv = spy
        self.addCleanup(setattr, os, "execv", real_execv)
        out = forkrun.map(_spec(), self.path, workers=2, nodes=1,
                          mode="plugin", output="bytes", **kw)
        return out, os.path.exists(marker)

    def test_launcher_actually_execs(self):
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        out, execed = self._run_with_exec_probe(orchestrator=False)
        self.assertTrue(
            execed,
            "the launcher never exec'd -- FORKRUN_CLEANROOM=1 took the "
            "in-process path, so this whole file proves nothing")
        self.assertEqual(len(_joined(out)), 2000)

    def test_matches_in_process_content(self):
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        cr, _ = self._run_with_exec_probe(orchestrator=False)
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


if __name__ == "__main__":
    unittest.main()
