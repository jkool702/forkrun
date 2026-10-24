"""The shared orderer helper must preserve every caller's configuration.

THE DEFECT THIS LOCKS DOWN. `_spawn_c_orderer()` replaced six copies of
the orderer setup. The fold briefly DROPPED the two NUMA callers'
`numa=True` -- and `numa` is not decoration: it reaches the C orderer as
the "numa" argument of `ring_order`, selecting the orderer's NUMA mode.
The NUMA ordered paths were therefore running the default orderer mode,
with no test noticing -- `nodes="@2"` forces two LOGICAL nodes
(cycling over the online physicals), so the NUMA executors DO run on
this single-node host, but the orderer's NUMA *mode* is not observable
in the output with one physical node: the ordering comes out the same
either way. The configuration was checkable; its EFFECT was not.

That is the failure mode this file exists to prevent: centralising a
decision correctly while accidentally losing a SEPARATE configuration
dimension. The authoritative implementation has to represent every
meaningful variation, and each caller's variation has to be asserted.

These are static checks on the call sites, deliberately. The NUMA order
path IS reachable here -- `nodes="@2"` forces two LOGICAL nodes, cycling
over the online physicals, so the NUMA executors do run on this
single-node host -- but the orderer's NUMA MODE is not observable in the
output on one physical node: the ordering comes out the same either
way. The configuration is therefore checkable but its EFFECT is not,
and a behavioural test would pass whether the mode was right or wrong.
That is why the regression survived a green gate.
"""

import ast
import os
import sys
import unittest

_ROOT = os.path.join(os.path.dirname(__file__), "..", "forkrun")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The executors that serve an ordered stream, and the orderer mode
# each one needs. The NUMA executors need the orderer's NUMA mode; the
# UMA ones must not ask for it.
NUMA_EXECUTORS = ("_execute_numa_locked", "_execute_numa_stream")
UMA_EXECUTORS = ("_execute_reactor_locked", "_execute_streaming_reactor",
                 "_execute_ingest_reactor_locked",
                 "_execute_ingest_stream_reactor")


def _run_py():
    path = os.path.join(_ROOT, "run.py")
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    tops = [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def owner(node):
        best = None
        for t in tops:
            if t.lineno <= node.lineno <= t.end_lineno:
                if best is None or t.lineno > best.lineno:
                    best = t
        return best.name if best else "?"

    calls = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if getattr(fn, "id", None) != "_spawn_c_orderer":
            continue
        kw = {k.arg: ast.unparse(k.value) for k in node.keywords}
        calls.setdefault(owner(node), []).append(kw)
    return calls, src


class TestOrdererSetupConfiguration(unittest.TestCase):
    """Each caller of the shared helper asks for what it needs."""

    @classmethod
    def setUpClass(cls):
        cls.calls, cls.src = _run_py()

    def test_every_ordered_executor_uses_the_shared_helper(self):
        for name in NUMA_EXECUTORS + UMA_EXECUTORS:
            self.assertIn(name, self.calls,
                          "%s no longer uses the shared orderer helper"
                          % (name,))

    def test_the_numa_executors_ask_for_the_numa_orderer_mode(self):
        for name in NUMA_EXECUTORS:
            for kw in self.calls[name]:
                self.assertEqual(
                    kw.get("numa"), "True",
                    "%s must ask for the orderer's NUMA mode: the C "
                    "orderer selects it with the 'numa' argument of "
                    "ring_order, and dropping it silently runs the "
                    "default orderer mode on the NUMA ordered paths"
                    % (name,))

    def test_the_uma_executors_do_not_ask_for_the_numa_orderer_mode(self):
        for name in UMA_EXECUTORS:
            for kw in self.calls[name]:
                self.assertNotEqual(
                    kw.get("numa"), "True",
                    "%s must not ask for the NUMA orderer mode" % (name,))

    def test_the_helper_forwards_the_configuration_to_the_orderer(self):
        """The helper must PASS IT ON, not swallow it."""
        from forkrun.run import _spawn_c_orderer
        import inspect
        sig = inspect.signature(_spawn_c_orderer)
        for name in ("unordered", "numa"):
            self.assertIn(name, sig.parameters,
                          "_spawn_c_orderer must accept %r and forward it"
                          % (name,))
            self.assertIs(sig.parameters[name].default, False,
                          "%r defaults to False" % (name,))
        body = inspect.getsource(_spawn_c_orderer)
        self.assertIn("numa=numa", body,
                      "_spawn_c_orderer must forward numa to "
                      "spawn_orderer")
        self.assertIn("unordered=unordered", body,
                      "_spawn_c_orderer must forward unordered to "
                      "spawn_orderer")

    def test_the_helper_defaults_match_the_uma_callers(self):
        """The default configuration IS the UMA one, so a caller that
        says nothing still gets what it got before the fold."""
        from forkrun.run import _spawn_c_orderer
        import inspect
        sig = inspect.signature(_spawn_c_orderer)
        self.assertIs(sig.parameters["numa"].default, False)
        self.assertIs(sig.parameters["unordered"].default, False)


if __name__ == "__main__":
    unittest.main()
