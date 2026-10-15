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
import forkrun                             # noqa: E402

# `forkrun.run` is an EXPORTED FUNCTION of the same name as the module,
# so the module must come from sys.modules or every attribute lookup
# below fails. Same trap as in the prober itself.
_rm = sys.modules["forkrun.run"]


def forkrun_map(payload, source, **kw):
    return cd.Rm.map(payload, source, **kw) if hasattr(cd, "Rm") \
        else _rm.map(payload, source, **kw)


def forkrun_run(payload, source, **kw):
    return _rm.run(payload, source, **kw)


def forkrun_stream(payload, source, **kw):
    return _rm.stream(payload, source, **kw)

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

class TestStructuralIndependence(unittest.TestCase):
    """The oracle and the prober must not share a source of truth.

    WO-CM1-R1 required this explicitly. Without it, "the oracle agrees
    with the predicate" can be satisfied by both being wrong the same
    way, which is the failure mode an independent oracle exists to
    prevent.
    """

    def _source(self, name):
        path = os.path.join(_ROOT, "tools", name)
        with open(path) as fh:
            return fh.read()

    def test_oracle_imports_nothing_from_forkrun(self):
        src = self._source("capability_oracle.py")
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                self.assertNotIn(
                    "forkrun", stripped,
                    "capability_oracle.py must not import forkrun: %r"
                    % stripped)

    def test_oracle_names_the_predicate_but_never_calls_it(self):
        """Prose references are REQUIRED; a call would be disqualifying.

        The oracle must say WHERE its rules come from -- naming the
        predicate's docstring and the roadmap is what makes the
        independence auditable rather than a bare assertion. What it must
        not do is invoke it. An earlier version of this test forbade the
        string outright and failed on the module docstring, which would
        have pushed the author to delete exactly the citations that make
        the file trustworthy.
        """
        import ast
        src = self._source("capability_oracle.py")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                self.assertNotEqual(
                    "_cleanroom_eligible", name,
                    "the oracle must not CALL the predicate it checks")
        # The citations must still be there.
        self.assertIn("_cleanroom_eligible", src,
                      "the oracle should still CITE the predicate's "
                      "docstring so its rules are traceable")

    def test_prober_classifies_without_the_predicate_result(self):
        """route() may count predicate CALLS; it must not use the answer.

        A prober that classified on the predicate's return value would be
        testing the predicate against itself and could never detect a
        dispatch regression -- the exact gap this work order opened with.
        """
        src = self._source("capability_dispatch.py")
        body = src[src.index("def route(self):"):]
        body = body[:body.index("class _StopRoute")]
        self.assertIn("predicate_called", body,
                      "route() should key off whether the predicate was "
                      "CONSULTED")
        self.assertNotIn("_ok", body)
        self.assertNotIn("return real_eligible", body)
        # The real predicate's value is returned to the caller but must
        # not be stored on the probe for classification.
        self.assertNotIn("self.eligible", src)


class TestRemainingRouteFacts(_Fixtures):
    """Phase D items the first pass did not cover.

    Each is a boundary the matrix's axes cannot express: they depend on
    artifacts or policy rather than on a configuration value, so they are
    tested as routes rather than enumerated as cells.
    """

    def test_map_and_stream_differ_on_a_missing_launcher(self):
        """A real asymmetry between the two entry points, found here.

        `map()` gates only on the predicate and calls _execute_cleanroom
        unconditionally; that function resolves the launcher ITSELF and,
        when it is missing, warns and returns None so the caller continues
        on the in-process path. `stream()` instead tests
        `_cleanroom_launcher_path() is not None` BEFORE selecting
        (run.py:4345), so a missing launcher prevents selection outright.

        The two are therefore not interchangeable on this boundary, and an
        earlier version of this test asserted the wrong one -- it expected
        a missing launcher to stop map() selecting the cleanroom, which the
        code does not do.
        """
        map_route, map_called = cd.probe_call(
            "map", source=self.so, payload=self.plugin_spec,
            mode="plugin", nodes=1, workers=1, launcher=False)[0:2]
        self.assertEqual(
            cd.CLEANROOM_SELECTED, map_route,
            "map() selects the cleanroom path on the predicate alone; the "
            "missing-launcher fallback happens INSIDE it")
        self.assertEqual(1, map_called)

        stream_route, stream_called = cd.probe_call(
            "stream", source=self.so, payload=self.plugin_spec,
            mode="plugin", nodes=1, workers=1, streaming=True,
            launcher=False)[0:2]
        self.assertNotEqual(
            cd.CLEANROOM_SELECTED, stream_route,
            "stream() tests launcher availability before selecting, so a "
            "missing launcher stops it there")
        self.assertEqual(
            1, stream_called,
            "and it still consults the envelope first -- capability and "
            "artifact availability are different questions")

    def test_supervision_policy_does_not_change_the_route(self):
        """orchestrator selects a worker loop, not an entry destination."""
        routes = set()
        for orch in (True, False):
            r, _ = cd.probe_call("map", source=self.so,
                                 payload=self.plugin_spec, mode="plugin",
                                 nodes=1, workers=1, orchestrator=orch)[0:2]
            routes.add(r)
        self.assertEqual(1, len(routes),
                         "orchestrator must not move a map() call between "
                         "routes; observed %r" % routes)

    def test_strict_poison_does_not_change_the_route(self):
        routes = set()
        for sp in (True, False):
            r, _ = cd.probe_call("map", source=self.so,
                                 payload=self.plugin_spec, mode="plugin",
                                 nodes=1, workers=1, strict_poison=sp)[0:2]
            routes.add(r)
        self.assertEqual(1, len(routes),
                         "strict_poison is a policy on the same route, "
                         "observed %r" % routes)

    def test_invalid_cells_never_receive_an_execution_route(self):
        """An unusable configuration must be rejected, not routed.

        Mirrors the generator's own rule, but through the REAL API: a
        configuration that public validation refuses must raise rather
        than quietly take a route.
        """
        import capability_oracle as _o
        bad = _o.Facts(kind="map", source_kind="iterable",
                       mode="plugin", nodes=1, order="none",
                       orchestrator=True, strict_poison=False,
                       return_stats=False, resume=None,
                       checkpoint_file=None, entry="map")
        self.assertFalse(_o.public_valid(bad))
        with self.assertRaises((TypeError, ValueError)):
            list(cd.probe_call("map", source=iter(["0:A\n"]),
                               payload=self.plugin_spec, mode="plugin",
                               nodes=1, workers=1)[0:3] and
                             forkrun_map(self.plugin_spec,
                                         iter(["0:A\n"])))

    def test_run_mode_splice_is_rejected_by_the_contract(self):
        """Verified against the live API rather than asserted by hand.

        run(mode='splice') raises for BOTH payload shapes: with a payload
        ("takes no payload") and with payload=None ("produces output
        records -- use map() or stream()"). So it is unconditionally
        unsupported there, not merely payload-shaped.
        """
        with self.assertRaises(ValueError):
            forkrun_run(self.plugin_spec, self.src, mode="splice")
        with self.assertRaises(ValueError):
            forkrun_run(None, self.src, mode="splice")

    def test_run_mode_udf_is_rejected(self):
        with self.assertRaises(NotImplementedError):
            forkrun_run("os:getcwd", self.src, mode="udf")

    def test_return_stats_is_map_only(self):
        with self.assertRaises(TypeError):
            forkrun_run(lambda b: b, self.src, return_stats=True)
        with self.assertRaises(TypeError):
            list(forkrun_stream(lambda b: b, self.src, return_stats=True))
