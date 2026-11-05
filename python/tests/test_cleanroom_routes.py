"""WO-CR-ROI-2 Phase B: real launcher-route proof for every served route.

Phase A exec-verified all five routes with a throwaway wrapper. This
module makes that a permanent, reusable test.

The property under test is NOT "the output is right". An in-process
fallback produces correct output, so an output-only assertion cannot
distinguish the launcher route from the fallback -- which is exactly the
defect class WO-ROI-1 hit. Each test therefore asserts the launcher
PROCESS actually ran, using `_cleanroom_exec_probe.LauncherExecProbe`.

Byte-exactness rules learned in Phase A, and encoded here:
  * byte comparisons require order="index"; order="none" returns
    worker-COMPLETION order, so equality would be a scheduling race;
  * unordered runs are compared by record IDENTITY (a multiset), never
    by position;
  * comparing lengths proves nothing -- a substituted record satisfies
    a byte count.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
for _p in (os.path.join(_ROOT, "python"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forkrun                                     # noqa: E402
from _cleanroom_exec_probe import (                # noqa: E402
    LauncherExecProbe, joined)

PLUGIN_HEADER = os.path.join(_ROOT, "ring_loadables", "forkrun_plugin.h")
PLUGIN_SRC = os.path.join(_HERE, "plugins", "test_plugin_v1.c")
PLUGIN_FUNC = "count_lines_v1"

HAVE_GCC = shutil.which("gcc") is not None

UDF_SRC = '''
def up(b):
    return b.upper()

def none_result(b):
    return None

def empty_result(b):
    return b""
'''

N_LINES = 200
LINES = ["line%06d\n" % i for i in range(N_LINES)]
EXPECTED = "".join(LINES).encode()
EXPECTED_UPPER = "".join(l.upper() for l in LINES).encode()


class _Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAVE_GCC:
            raise unittest.SkipTest("gcc absent; the plugin fixture that "
                                   "distinguishes real launcher execution "
                                   "cannot be built")
        cls._tmp = tempfile.mkdtemp(prefix="cr-route-")
        cls.so = os.path.join(cls._tmp, "plug.so")
        proc = subprocess.run(
            ["gcc", "-shared", "-fPIC", "-O2", "-I", PLUGIN_HEADER,
             "-o", cls.so, PLUGIN_SRC],
            capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            shutil.rmtree(cls._tmp, ignore_errors=True)
            raise unittest.SkipTest("plugin fixture build failed: %s"
                                    % proc.stderr[-300:])
        cls.spec = "%s:%s" % (cls.so, PLUGIN_FUNC)

        # The UDF fixture must be on the PARENT sys.path, because
        # _udf_dir() scans it there -- this is how a user's module is
        # found, and setting PYTHONPATH is NOT equivalent.
        with open(os.path.join(cls._tmp, "forkrun_udf_route_fixture.py"),
                  "w") as fh:
            fh.write(UDF_SRC)
        sys.path.insert(0, cls._tmp)
        cls.addClassCleanup(sys.path.remove, cls._tmp)

        cls.src = os.path.join(cls._tmp, "input.txt")
        with open(cls.src, "w") as fh:
            fh.writelines(LINES)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        self._old_gate = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.addCleanup(self._restore_gate)

    def _restore_gate(self):
        if self._old_gate is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._old_gate


class TestMapPluginRoute(_Fixtures):
    """map(plugin): the route the default-on decision turns on."""

    def test_launcher_actually_executes(self):
        with LauncherExecProbe() as probe:
            out = forkrun.map(self.spec, self.src, mode="plugin", nodes=1,
                              workers=4, order="index", output="bytes")
        self.assertGreaterEqual(
            probe.read(), 1,
            "the launcher process must have been started. Zero execs means "
            "the run fell back in-process while still producing output -- "
            "exactly the case an output-only assertion cannot see.")

    def test_output_matches_an_independent_in_process_reference(self):
        """Reference run, not a guessed expectation.

        count_lines_v1 TRANSFORMS records, so the input bytes are not the
        expected output. The two arms are compared instead.
        """
        with LauncherExecProbe() as probe:
            fast = forkrun.map(self.spec, self.src, mode="plugin", nodes=1,
                               workers=4, order="index", output="bytes")
        self.assertGreaterEqual(probe.read(), 1)

        os.environ["FORKRUN_CLEANROOM"] = "0"
        try:
            slow = forkrun.map(self.spec, self.src, mode="plugin", nodes=1,
                               workers=4, order="index", output="bytes")
        finally:
            os.environ["FORKRUN_CLEANROOM"] = "1"
        self.assertEqual(joined(fast), joined(slow),
                         "launcher and in-process paths must agree on the "
                         "exact bytes, under order=index")
        self.assertTrue(fast, "the route must produce output")

    def test_explicit_off_selects_no_launcher(self):
        """The rollback path must be independently proven, not assumed."""
        os.environ["FORKRUN_CLEANROOM"] = "0"
        with LauncherExecProbe() as probe:
            out = forkrun.map(self.spec, self.src, mode="plugin", nodes=1,
                              workers=2, order="index", output="bytes")
        self.assertEqual(0, probe.read(),
                         "with the gate explicitly OFF no launcher may be "
                         "executed")
        self.assertTrue(out, "and the in-process path must still work")


class TestMapUDFRoute(_Fixtures):
    """map(udf): requires a per-minor helper before the route is real."""

    def test_helper_is_present_for_this_interpreter(self):
        """Precondition, asserted rather than assumed.

        Without the helper for the running minor the UDF route cannot be
        exercised at all -- Phase A measured the in-process path raising
        NotImplementedError. A test that silently degraded here would
        'pass' without ever launching anything.
        """
        from forkrun._udf import helper_path
        self.assertIsNotNone(helper_path(),
                             "no UDF helper for this interpreter minor; "
                             "without it this route cannot be tested")

    def test_launcher_actually_executes_and_bytes_are_exact(self):
        with LauncherExecProbe() as probe:
            out = forkrun.map("forkrun_udf_route_fixture:up", self.src,
                              mode="udf", nodes=1, workers=4,
                              order="index", output="bytes")
        self.assertGreaterEqual(
            probe.read(), 1,
            "the UDF route must exec the launcher, not fall back")
        self.assertEqual(EXPECTED_UPPER, joined(out),
                         "UDF output must be byte-exact under order=index")

    def test_none_and_empty_remain_distinct_on_this_route(self):
        """DECISION-02 must survive the launcher route, not just in-process."""
        with LauncherExecProbe() as probe:
            none_out = forkrun.map("forkrun_udf_route_fixture:none_result",
                                   self.src, mode="udf", nodes=1,
                                   workers=2, order="index", output="bytes")
        self.assertGreaterEqual(probe.read(), 1)
        self.assertEqual([], list(none_out),
                         "a UDF returning None emits a NO_RESULT record, "
                         "which must NOT surface as an empty payload")

        with LauncherExecProbe() as probe2:
            empty_out = forkrun.map(
                "forkrun_udf_route_fixture:empty_result", self.src,
                mode="udf", nodes=1, workers=2, order="index",
                output="bytes")
        self.assertGreaterEqual(probe2.read(), 1)
        self.assertTrue(all(len(x) == 0 for x in empty_out),
                        "b'' is a real empty record and must be kept")


class TestMapSpawnRoute(_Fixtures):
    """map(spawn): an argv vector, and the route documentation was stale."""

    def test_launcher_actually_executes_with_a_real_argv(self):
        with LauncherExecProbe() as probe:
            out = forkrun.map(["/bin/cat"], self.src, mode="spawn", nodes=1,
                              workers=4, order="index", output="bytes")
        self.assertGreaterEqual(
            probe.read(), 1,
            "spawn must exec the launcher. The test module that used to "
            "claim this envelope was 'not activated' was stale; Phase A "
            "exec-verified it and this pins it.")
        self.assertEqual(EXPECTED, joined(out),
                         "cat is a passthrough, so the bytes must be exact")

    def test_argv_is_preserved_distinctly(self):
        """An argv vector must not be re-parsed into one string."""
        with LauncherExecProbe() as probe:
            out = forkrun.map(["/bin/echo", "alpha", "beta"], self.src,
                              mode="spawn", nodes=1, workers=1,
                              order="index", output="bytes")
        self.assertGreaterEqual(probe.read(), 1)
        flat = joined(out).decode()
        self.assertIn("alpha beta", flat,
                      "echo joins its arguments with spaces; separate argv "
                      "elements must stay separate all the way through")


class TestStreamRoutes(_Fixtures):
    """stream(plugin) and stream(udf): the streaming dispatch branch."""

    def _drain(self, fn, **kw):
        gen = forkrun.stream(fn, self.src, nodes=1, workers=4,
                             streaming=True, output="bytes", **kw)
        try:
            return list(gen)
        finally:
            try:
                gen.close()
            except Exception:                      # noqa: BLE001
                pass

    def test_stream_plugin_execs_the_launcher(self):
        with LauncherExecProbe() as probe:
            out = self._drain(self.spec, mode="plugin", order="none")
        self.assertGreaterEqual(
            probe.read(), 1,
            "stream(plugin) must exec the launcher. It is reached ONLY "
            "inside the streaming branch, so streaming=True is part of "
            "the route's conditions, not an incidental flag.")

    def test_stream_udf_execs_the_launcher(self):
        with LauncherExecProbe() as probe:
            out = self._drain("forkrun_udf_route_fixture:up", mode="udf",
                              order="none")
        self.assertGreaterEqual(probe.read(), 1)
        # order="none" is worker-completion order, so compare by identity.
        got = Counter(joined(out).decode().splitlines())
        want = Counter(l.upper().rstrip("\n") for l in LINES)
        self.assertEqual(
            want, got,
            "streaming UDF must deliver exactly the input lines once each; "
            "order is worker-completion, so this compares identity, not "
            "position")

    def test_stream_without_streaming_input_never_launches(self):
        """The effective-ingestion condition is part of the route.

        `stream()` consults the envelope only inside its streaming branch,
        so a materialised call never reaches it. This test is paired with
        `test_stream_plugin_execs_the_launcher`, which does stream: the two
        together establish that ingestion is what decides the route, not
        the mode name alone.

        The materialised call may reject the plugin spec outright on that
        path; the property is that no launcher is started either way.
        """
        with LauncherExecProbe() as probe:
            try:
                gen = forkrun.stream(self.spec, self.src, nodes=1,
                                     workers=2, streaming=False,
                                     output="bytes", order="none")
                try:
                    list(gen)
                finally:
                    try:
                        gen.close()
                    except Exception:              # noqa: BLE001
                        pass
            except (TypeError, ValueError, ModuleNotFoundError):
                pass
        self.assertEqual(0, probe.read(),
                         "a materialised stream() must not start a "
                         "launcher; it never enters the streaming branch")


class TestUnservedRoutesStayUnserved(_Fixtures):
    """Declined configurations must not be silently enabled."""

    def test_stream_spawn_never_launches(self):
        """stream has no spawn dispatch, whatever the payload form.

        The call is allowed to fail: Phase A found stream(spawn) taking
        the in-process path, and the argv-vector payload shape is not
        the property under test. What must never happen is a launcher.
        """
        with LauncherExecProbe() as probe:
            try:
                gen = forkrun.stream(["/bin/cat"], self.src, nodes=1,
                                     workers=2, streaming=True,
                                     output="bytes", order="none")
                try:
                    list(gen)
                finally:
                    try:
                        gen.close()
                    except Exception:              # noqa: BLE001
                        pass
            except TypeError:
                pass
        self.assertEqual(0, probe.read(),
                         "stream has no spawn dispatch; this route must "
                         "stay unserved")

    def test_run_never_launches(self):
        with LauncherExecProbe() as probe:
            forkrun.run(["/bin/cat"], self.src, mode="spawn", nodes=1,
                        workers=1)
        self.assertEqual(0, probe.read(),
                         "run() has no cleanroom dispatch at all")

    def test_numa_never_launches(self):
        # Multi-node stays opt-in (Decision 3): with the NUMA switch off
        # the launcher must never run, even under FORKRUN_CLEANROOM=1.
        _old_numa = os.environ.pop("FORKRUN_CLEANROOM_NUMA", None)
        os.environ["FORKRUN_CLEANROOM_NUMA"] = "0"
        self.addCleanup(self._restore_numa_gate, _old_numa)
        with LauncherExecProbe() as probe:
            forkrun.map(self.spec, self.src, mode="plugin", nodes="@2",
                        workers=2, order="none", output="bytes")
        self.assertEqual(0, probe.read(),
                         "multi-node routes around the cleanroom entirely")

    def _restore_numa_gate(self, old):
        if old is None:
            os.environ.pop("FORKRUN_CLEANROOM_NUMA", None)
        else:
            os.environ["FORKRUN_CLEANROOM_NUMA"] = old

    def test_resume_never_launches(self):
        """resume is refused by the shared envelope, so no launcher runs.

        The checkpoint file is validated BEFORE the envelope decision, so
        the call may raise for a malformed checkpoint rather than for the
        cleanroom refusal. That ordering is not the property under test:
        the property is that the launcher is never reached either way. The
        assertion is therefore on exec count, and the call is allowed to
        fail.
        """
        bad = os.path.join(self._tmp, "not-a-checkpoint.txt")
        with open(bad, "w") as fh:
            fh.write("this is not a three-line checkpoint\n")
        with LauncherExecProbe() as probe:
            try:
                forkrun.map(self.spec, self.src, mode="plugin", nodes=1,
                            workers=2, order="index", output="bytes",
                            resume=bad)
            except (ValueError, OSError):
                pass
        self.assertEqual(0, probe.read(),
                         "checkpoint/resume is not cleanroom-served; a "
                         "launcher must never be started for it")
class TestSelectorControlsRealDispatch(_Fixtures):
    """Phase C: the selector must change what actually RUNS.

    TestCleanroomSelector pins the parser. That is not enough on its own:
    a selector that parses correctly but is never consulted would pass
    every grammar test while enabling everything. These tests exercise
    the public API with the exec probe.
    """

    def _map_plugin(self):
        return forkrun.map(self.spec, self.src, mode="plugin", nodes=1,
                           workers=2, order="index", output="bytes")

    def _set_gate(self, value):
        os.environ["FORKRUN_CLEANROOM"] = value

    def test_map_plugin_selector_enables_map_plugin(self):
        self._set_gate("map-plugin")
        with LauncherExecProbe() as probe:
            out = self._map_plugin()
        self.assertGreaterEqual(probe.read(), 1,
                                "map-plugin must select the launcher")

    def test_stream_plugin_selector_does_not_enable_map_plugin(self):
        """The independence property, end to end."""
        self._set_gate("stream-plugin")
        with LauncherExecProbe() as probe:
            out = self._map_plugin()
        self.assertEqual(0, probe.read(),
                         "stream-plugin must NOT launch for a map() call")
        self.assertTrue(out, "and the run must still produce output")

    def test_legacy_one_still_enables_everything_eligible(self):
        self._set_gate("1")
        with LauncherExecProbe() as probe:
            self._map_plugin()
        self.assertGreaterEqual(probe.read(), 1,
                                "legacy =1 must keep enabling map(plugin)")

    def test_unknown_selector_fails_clearly_at_the_public_api(self):
        """A typo must surface, not silently widen the blast radius."""
        self._set_gate("map-plguin")
        with LauncherExecProbe() as probe:
            with self.assertRaises(ValueError):
                self._map_plugin()
        self.assertEqual(0, probe.read(),
                         "a rejected selector must not launch anything")

    def test_stream_spawn_selector_is_rejected_and_launches_nothing(self):
        """The user's view of the unserved route.

        Naming it must FAIL LOUDLY rather than fall through in-process:
        a silent fallback would leave the user believing they had selected
        a cleanroom route.
        """
        self._set_gate("stream-spawn")
        with LauncherExecProbe() as probe:
            with self.assertRaises(ValueError):
                list(forkrun.stream(["/bin/cat"], self.src, nodes=1,
                                    workers=2, streaming=True,
                                    output="bytes", order="none"))
        self.assertEqual(0, probe.read())

    def test_legacy_all_still_refuses_stream_spawn_end_to_end(self):
        """"=1" enables every SERVED route -- not an unserved one."""
        self._set_gate("1")
        with LauncherExecProbe() as probe:
            gen = forkrun.stream(["/bin/cat"], self.src, nodes=1,
                                 workers=2, streaming=True,
                                 output="bytes", order="none")
            try:
                list(gen)
            except TypeError:
                pass                            # payload form; not the point
            finally:
                try:
                    gen.close()
                except Exception:              # noqa: BLE001
                    pass
        self.assertEqual(0, probe.read(),
                         "even legacy =1 must not launch for stream(spawn)")

    def test_explicit_off_never_launches_end_to_end(self):
        self._set_gate("off")
        with LauncherExecProbe() as probe:
            out = self._map_plugin()
        self.assertEqual(0, probe.read())
        self.assertTrue(out)


class TestMultinodeOptInContract(unittest.TestCase):
    """The multi-node cleanroom switch is EXPLICIT and independent.

    CLEANROOM_EXPANSION_ROADMAP.md (W-EXP-2 step C): the multi-node
    envelope is served through FORKRUN_CLEANROOM_NUMA=1, "a separate
    switch from the FORKRUN_CLEANROOM route selector". Folding topology
    into the route namespace would silently change what an existing
    FORKRUN_CLEANROOM=map-plugin means, which is precisely the
    divergence the two switches exist to prevent.

    These are contract tests, not implementation tests: they pin the
    documented answer for unset, false, truthy and other non-false
    values, and they pin that an explicit false wins so a caller can
    opt out of the topology without changing its route selection.
    """

    def _set(self, name, value):
        old = os.environ.get(name)

        def restore():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old

        self.addCleanup(restore)
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def _enabled(self):
        return sys.modules["forkrun.run"]._cleanroom_multinode_enabled()

    def test_route_selector_alone_does_not_opt_in(self):
        for selector in ("1", "yes", "on", "true", "all", "map-plugin"):
            with self.subTest(selector=selector):
                self._set("FORKRUN_CLEANROOM_NUMA", None)
                self._set("FORKRUN_CLEANROOM", selector)
                self.assertFalse(
                    self._enabled(),
                    "FORKRUN_CLEANROOM=%r must not imply the multi-node "
                    "cleanroom; FORKRUN_CLEANROOM_NUMA is a separate "
                    "switch" % (selector,))

    def test_explicit_truthy_opt_in(self):
        self._set("FORKRUN_CLEANROOM", None)
        self._set("FORKRUN_CLEANROOM_NUMA", "1")
        self.assertTrue(self._enabled())

    def test_explicit_false_wins_over_the_route_selector(self):
        self._set("FORKRUN_CLEANROOM", "1")
        for value in ("0", "no", "off", "false", "none", "auto", ""):
            with self.subTest(value=value):
                self._set("FORKRUN_CLEANROOM_NUMA", value)
                self.assertFalse(self._enabled())

    def test_any_non_false_value_opts_in(self):
        """Only an explicit false disables; the selectors are truthy-style.

        This matches _cleanroom_explicit and _cleanroom_enabled: unset
        is off, an explicit false wins, any other value opts in. The
        old docstring claimed "garbage is off", which the
        implementation never did; the docstring was corrected rather
        than changing behaviour.
        """
        self._set("FORKRUN_CLEANROOM", None)
        for value in ("yes", "on", "true", "sometimes"):
            with self.subTest(value=value):
                self._set("FORKRUN_CLEANROOM_NUMA", value)
                self.assertTrue(self._enabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
