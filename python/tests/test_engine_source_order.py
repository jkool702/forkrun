"""The process-global engine is acquired only after the source is accepted.

Regression this pins: every executor used to initialize the engine and
THEN open the source. A missing path (ordinary user input, not a crash)
raised between the two, before the executor's try/finally was entered,
so the engine stayed live. The next call in the same process succeeded
only if it asked for the same node count; a later ``nodes=1`` call hit
``ring_init_main``'s "cannot change --nodes without calling ring_destroy
first" and surfaced as ``RuntimeError: substrate init failed`` in a
test hundreds of cases away from the call that leaked it.

Both halves matter, so both are tested:

* structurally -- there is exactly ONE engine-init site, it lives in
  ``_init_engine_source``, and the source is opened before it, so a new
  executor cannot reintroduce the leak by calling init directly;
* behaviorally -- a rejected source followed by a different node count
  still works, which is the outcome the caller can observe.
"""
import ast
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

import forkrun  # noqa: E402
from forkrun._numa import detect_numa_nodes  # noqa: E402
from _helpers import write_lines  # noqa: E402

RUN_PY = os.path.join(_HERE, "..", "forkrun", "run.py")


def _calls(fn, name):
    return [n for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == name]


class TestEngineInitOrder(unittest.TestCase):
    def test_one_engine_init_site_after_the_source_is_opened(self):
        with open(RUN_PY) as fh:
            tree = ast.parse(fh.read())
        fns = {n.name: n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)}
        self.assertIn("_init_engine_source", fns,
                      "the shared source-then-engine helper is gone")
        helper = fns["_init_engine_source"]

        inits = _calls(tree, "_init_engine_and_fds")
        self.assertEqual(
            len(inits), 1,
            "engine init has %d sites; every executor must route through "
            "_init_engine_source so the source is opened first"
            % (len(inits),))
        init = inits[0]
        self.assertTrue(
            helper.lineno <= init.lineno <= helper.end_lineno,
            "the only _init_engine_and_fds call is outside "
            "_init_engine_source (line %d); a direct caller reopens the "
            "leak window" % (init.lineno,))

        opens = _calls(helper, "_open_source")
        self.assertTrue(opens, "_init_engine_source no longer opens the "
                        "source")
        self.assertLess(
            min(n.lineno for n in opens), init.lineno,
            "ORDER IS THE DECISION: the source must be opened BEFORE the "
            "engine is initialized, or a rejected source leaves a live "
            "engine behind")


class TestRejectedSourceLeavesNoEngine(unittest.TestCase):
    def test_missing_source_then_a_different_node_count(self):
        online = detect_numa_nodes()
        if len(online) < 2:
            self.skipTest("single-node host: a later nodes=1 call cannot "
                          "observe the leaked node count")

        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        self.addCleanup(os.unlink, path)
        write_lines(path, 16, fmt="line %d\n")

        # First call: select the multi-node engine, then have the source
        # rejected. With the leak this leaves a live N-node engine.
        with self.assertRaises(FileNotFoundError):
            forkrun.map(lambda b: bytes(b.data), path + ".missing",
                        workers=len(online), lines=1, nodes=len(online))

        # Second call: a different node count. ring_init_main refuses to
        # change it while the leaked engine is live.
        out = forkrun.map(lambda b: bytes(b.data), path, workers=1,
                          lines=1, nodes=1, output="bytes")
        got = sorted(b"".join(out).splitlines())
        with open(path, "rb") as fh:
            want = sorted(fh.read().splitlines())
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main(verbosity=2)
