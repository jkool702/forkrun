"""WO-CM1 -- the public DISPATCH claims, verified against real calls.

The capability matrix asserts a dispatch contract transcribed into
`tools/capability_oracle.py`. A transcription proves nothing on its own,
so these tests OBSERVE the routes the public entry points actually take,
by intercepting the leaves of the dispatch (`tools/capability_dispatch.py`)
and then asserting the oracle's contract matches what happened.

This is the test the old suite was missing. Every pre-existing C0.1 test
called `_cleanroom_eligible()` directly, so a regression that stopped the
public API from ever reaching the predicate would have left the whole
matrix suite green.

Fixtures are real, not stubs. A dummy `.so` is not loadable, which made
`stream(mode="plugin")` look like an unconditional refusal and masked the
actual finding -- so the plugin is compiled from the repository's own
fixture, exactly as test_cleanroom.py does.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
for _p in (os.path.join(_ROOT, "python"), os.path.join(_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capability_dispatch as cd           # noqa: E402
import capability_oracle as oracle         # noqa: E402

PLUGIN_HEADER = os.path.join(_ROOT, "ring_loadables", "forkrun_plugin.h")
PLUGIN_SRC = os.path.join(_ROOT, "python", "tests", "plugins",
                          "test_plugin_v1.c")


def _have_gcc():
    return shutil.which("gcc") is not None


class _Fixtures(unittest.TestCase):
    """A REAL plugin plus a real workload file.

    The plugin is compiled, not stubbed. With a stub, every plugin cell
    failed at load time and the probe reported "unsupported" -- which is
    indistinguishable from a genuine refusal, and is exactly what hid the
    streaming finding during the audit.
    """

    @classmethod
    def setUpClass(cls):
        if not _have_gcc():
            raise unittest.SkipTest("gcc absent; cannot build the plugin "
                                    "fixture the probe needs")
        cls.dir = tempfile.mkdtemp(prefix="c07-dispatch-")
        cls.src = os.path.join(cls.dir, "in.txt")
        with open(cls.src, "w") as fh:
            fh.write("0:A\n1:B\n")
        cls.so = os.path.join(cls.dir, "plug.so")
        proc = subprocess.run(
            ["gcc", "-shared", "-fPIC", "-O2", "-I", PLUGIN_HEADER,
             "-o", cls.so, PLUGIN_SRC],
            capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise unittest.SkipTest("plugin fixture build failed: %s"
                                    % proc.stderr[-300:])
        cls.plugin_spec = "%s:count_lines_v1" % cls.so

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "dir", None):
            shutil.rmtree(cls.dir, ignore_errors=True)


class TestObservedRoutes(_Fixtures):
    """What the public entry points actually do."""

    def _route(self, entry, **kw):
        route, called, err = cd.probe_call(entry, **kw)
        self.assertNotEqual(cd.UNCLASSIFIED, route,
                            "route %r was UNCLASSIFIED (error=%s); an "
                            "unobserved route is a finding, never a pass"
                            % (route, err))
        return route, called

    # -- the headline finding ------------------------------------------

    def test_run_never_reaches_the_predicate(self):
        """run() has no cleanroom branch at all.

        Checked for EVERY launcher-served mode, not just one: if any of
        them reached the predicate, the claim would be wrong.
        """
        for mode, payload in (("plugin", self.plugin_spec),
                              ("python", lambda b: b)):
            with self.subTest(mode=mode):
                route, called = self._route(
                    "run", source=self.so, payload=payload, mode=mode,
                    nodes=1, workers=1)
                self.assertEqual(
                    0, called,
                    "run(mode=%r) consulted _cleanroom_eligible; the "
                    "matrix claims run() has no cleanroom branch" % mode)
                self.assertNotEqual(cd.CLEANROOM_SELECTED, route)

    def test_run_plugin_is_not_cleanroom_served(self):
        route, called = self._route(
            "run", source=self.so, payload=self.plugin_spec,
            mode="plugin", nodes=1, workers=1)
        self.assertNotEqual(cd.CLEANROOM_SELECTED, route)
        self.assertEqual(0, called)

    # -- map -----------------------------------------------------------

    def test_map_plugin_selects_the_launcher(self):
        route, called = self._route(
            "map", source=self.so, payload=self.plugin_spec,
            mode="plugin", nodes=1, workers=1)
        self.assertEqual(cd.CLEANROOM_SELECTED, route)
        self.assertEqual(1, called)

    def test_map_python_never_reaches_the_predicate(self):
        """mode="python" is not the UDF path and is never launcher-served.

        The work order asks specifically that these not be conflated, so
        this asserts the distinction from BOTH sides: python is not
        consulted, and udf is.
        """
        route, called = self._route(
            "map", source=self.src, payload=lambda b: b,
            mode="python", nodes=1, workers=1)
        self.assertEqual(0, called,
                         "mode='python' must not consult the launcher "
                         "envelope")
        self.assertNotEqual(cd.CLEANROOM_SELECTED, route)

    def test_map_udf_is_a_distinct_route_from_python(self):
        r_py, c_py = self._route("map", source=self.src,
                                 payload=lambda b: b, mode="python",
                                 nodes=1, workers=1)
        r_udf, c_udf = self._route("map", source=self.src,
                                   payload="os:getcwd", mode="udf",
                                   nodes=1, workers=1)
        self.assertEqual(0, c_py)
        self.assertEqual(1, c_udf,
                         "mode='udf' DOES consult the envelope; if this "
                         "ever equalled the python path the two would have "
                         "been conflated")
        self.assertNotEqual(r_py, r_udf)

    def test_map_numa_bypasses_the_predicate(self):
        route, called = self._route(
            "map", source=self.so, payload=self.plugin_spec,
            mode="plugin", nodes="2", workers=2)
        self.assertEqual(0, called,
                         "num_nodes>1 takes the NUMA path before the "
                         "predicate is consulted")
        self.assertNotEqual(cd.CLEANROOM_SELECTED, route)

    # -- stream: the finding that only a real fixture exposed ----------

    def test_stream_reaches_the_predicate_only_when_streaming(self):
        """The single most easily missed fact in this audit.

        stream() consults the predicate INSIDE its streaming branch. A
        materialised source therefore never reaches it, so
        `stream(mode="plugin")` and `stream(mode="plugin",
        streaming=True)` are different configurations -- the first is
        never launcher-served, the second can be.
        """
        r_auto, c_auto = self._route(
            "stream", source=self.so, payload=self.plugin_spec,
            mode="plugin", nodes=1, workers=1)
        r_true, c_true = self._route(
            "stream", source=self.so, payload=self.plugin_spec,
            mode="plugin", nodes=1, workers=1, streaming=True)

        self.assertEqual(0, c_auto,
                         "a materialised stream() must not consult the "
                         "envelope")
        self.assertEqual(1, c_true,
                         "an explicitly streaming stream() must")
        self.assertNotEqual(r_auto, r_true)

    def test_stream_omits_spawn_which_map_offers(self):
        """stream() has no spawn dispatch; map() does.

        Observed, because this asymmetry is invisible to a predicate
        truth table -- the predicate answers the same question for both.
        """
        _, m_spawn = self._route("map", source=self.src,
                                 payload=["/bin/echo", "hi"],
                                 mode="spawn", nodes=1, workers=1)
        _, s_spawn = self._route("stream", source=self.src,
                                 payload=["/bin/echo", "hi"],
                                 mode="spawn", nodes=1, workers=1,
                                 streaming=True)
        self.assertEqual(1, m_spawn,
                         "map() offers spawn to the launcher")
        self.assertEqual(0, s_spawn,
                         "stream() has no spawn dispatch and must not "
                         "consult the envelope for it")

    # -- the gate is a separate question from capability ----------------

    def test_gate_off_changes_the_route_not_the_capability(self):
        """Default-off must not be reported as a capability refusal."""
        on, c_on = self._route("map", source=self.so,
                               payload=self.plugin_spec, mode="plugin",
                               nodes=1, workers=1)
        route, called = cd.probe_call(
            "map", source=self.so, payload=self.plugin_spec, mode="plugin",
            nodes=1, workers=1, gate=False)[0:2]
        self.assertEqual(cd.CLEANROOM_SELECTED, on)
        self.assertEqual(1, c_on)
        self.assertNotEqual(cd.CLEANROOM_SELECTED, route,
                            "with the gate off the launcher must not be "
                            "selected")
        self.assertEqual(
            cd.IN_PROCESS, route,
            "gate-off must fall through to the ordinary in-process route, "
            "not to a refusal: the capability is unchanged, only the "
            "rollout state differs")
        self.assertEqual(
            0, cd.probe_call("map", source=self.so,
                             payload=self.plugin_spec, mode="plugin",
                             nodes=1, workers=1, gate=False)[1],
            "and the envelope must not even be consulted when the gate is "
            "off -- it is not consulted in order to be overridden")


class TestOracleContractMatchesObservation(_Fixtures):
    """The transcribed contract must equal what was observed.

    Without this, the oracle is a second opinion nobody checked -- and a
    disagreement has two possible causes (wrong contract, or wrong
    observation), which the work order requires distinguishing rather
    than papering over by editing whichever side is convenient.
    """

    CASES = [
        # (entry, mode, nodes, streaming, expect_predicate_reached)
        ("map",   "plugin", 1, False, True),
        ("map",   "plugin", "2", False, False),   # NUMA bypass
        ("map",   "spawn",  1, False, True),
        ("map",   "udf",    1, False, True),
        ("map",   "python", 1, False, False),    # not a served mode
        ("map",   "splice", 1, False, False),
        ("stream", "plugin", 1, False, False),    # materialised
        ("stream", "plugin", 1, True,  True),
        ("stream", "spawn",  1, True,  False),    # no spawn dispatch
        ("stream", "udf",    1, True,  True),
        ("run",   "plugin", 1, False, False),    # no cleanroom branch
        ("run",   "python", 1, False, False),
    ]

    def test_contract_matches_every_observed_case(self):
        bad = []
        for entry, mode, nodes, streaming, want in self.CASES:
            payload = {"plugin": self.plugin_spec,
                       "python": lambda b: b,
                       "udf": "os:getcwd",
                       "spawn": ["/bin/echo", "hi"],
                       "splice": lambda b: b}[mode]
            source = self.so if mode == "plugin" else self.src
            kwargs = dict(source=source, payload=payload, mode=mode,
                          nodes=nodes, workers=2 if nodes == "2" else 1)
            if streaming:
                kwargs["streaming"] = True
            try:
                route, called, _err = cd.probe_call(entry, **kwargs)
            except Exception as exc:                       # noqa: BLE001
                bad.append((entry, mode, "probe error: %s" % exc))
                continue
            facts = oracle.Facts(
                kind="map", source_kind="path", mode=mode,
                nodes=(2 if nodes == "2" else 1), order="none",
                orchestrator=True, strict_poison=False, return_stats=False,
                resume=None, checkpoint_file=None,
                entry=entry, streaming=streaming)
            contract = oracle.dispatch_reaches_predicate(facts)
            if contract != (called > 0):
                bad.append((entry, mode,
                            "contract says reached=%s, observed called=%s"
                            % (contract, called)))
        self.assertEqual([], bad,
                         "the transcribed dispatch contract disagrees with "
                         "observation: %r" % bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)