"""A helper child's death is fatal UNLESS an abort is already in flight.

THE FAILURE MODE THIS LOCKS DOWN. D-PORT2/D6 introduced the
abort-aware classification ("an abort already in flight makes helper
deaths expected (emergency path), not fatal") and wired it into 2 of
the 28 places the front end turns a helper child's non-zero exit into a
fatal error. The other 26 had the same rule written out -- or, in the
materialized PLAIN path's inline `_scan_pump`, omitted entirely.

That is exactly the failure the de-duplication pass exists to remove: a
fix lands in the copies its author happened to find and lives on in the
execution paths nobody looked at. The fix here is therefore not "patch
twenty-six sites" but **one decision point** every site asks, so the
next change to the rule lands everywhere by construction.

Two invariants, both checked here:

1. **No site may decide for itself.** Every helper-death raise site
   must reach the decision through `_helper_death_excused()`.
2. **The consult must come BEFORE the abort.** The abort publishes the
   reason the consult reads, so a consult placed after it would always
   see "excused" and silently swallow a genuine helper failure. That
   ordering is D-PORT2's own note -- "query the abort reason BEFORE the
   handler's own abort -- the order is the fix" -- and it is easy to
   get wrong when the rule is copied.
"""

import ast
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun.run import (_abort_reason_now,  # noqa: E402
                         _helper_death_disposition,
                         _helper_death_excused)

from _helpers import assert_no_zombies  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


# The helper-death message family: every place the front end turns a
# helper child's non-zero exit into a fatal error.
HELPER_DEATH = re.compile(
    r"(scanner failed|helper failed|orderer failed|reaper failed"
    r"|index/scan failed|scan failed)")


def _calls(fn, name):
    """Does this statement call `name` directly?

    Nested function and class bodies are NOT descended into: a closure
    that calls it is not the enclosing statement's own call.
    """
    found = [False]

    def walk(n):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                           ast.ClassDef)):
            return
        if isinstance(n, ast.Call):
            fn = n.func
            if (isinstance(fn, ast.Attribute) and fn.attr == name) or \
                    (isinstance(fn, ast.Name) and fn.id == name):
                found[0] = True
                return
        for c in ast.iter_child_nodes(n):
            walk(c)
    walk(fn)
    return found[0]


def _aborts_directly(stmt):
    """Does this statement call fr_py_abort() itself?"""
    return _calls(stmt, "fr_py_abort")


def _asks_directly(stmt):
    """Does this statement ASK the shared decision itself?

    Two shapes count: `if not _helper_death_excused(...)` (ask and
    branch) and `excused = _helper_death_excused(...)` (ask, then branch
    on the saved answer). A statement that merely CONTAINS a nested
    statement which asks is not itself the consult.
    """
    if isinstance(stmt, ast.Assign):
        return _calls(stmt.value, "_helper_death_excused")
    if isinstance(stmt, ast.If):
        return "_helper_death_excused" in ast.unparse(stmt.test)
    return False


def _scopes_and_owners(tree):
    """Every function-like scope, and the owner of each line."""
    scopes = [t for t in tree.body
              if isinstance(t, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for t in list(scopes):
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and n is not t:
                scopes.append(n)

    def nested_defs(node):
        out = set()

        def walk(n):
            for c in ast.iter_child_nodes(n):
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                    out.add((c.lineno, c.end_lineno))
                    walk(c)
                else:
                    walk(c)
        walk(node)
        return out

    def innermost(ln):
        best = None
        for sc in scopes:
            if sc.lineno <= ln <= sc.end_lineno:
                if best is None or sc.lineno > best.lineno:
                    best = sc
        return best
    return scopes, nested_defs, innermost


class TestTheSharedDecision(unittest.TestCase):
    """The decision itself -- the rule, in one place."""

    def test_the_decision_is_the_documented_truth_table(self):
        # No abort in flight -> fatal (a clean drain is still 'record').
        for reason in (0, None, -1):
            self.assertEqual(
                _helper_death_disposition("error", False, reason), "fatal",
                "reason=%r" % (reason,))
        # An abort in flight -> excused: the death is its consequence.
        for reason in (1, 2):
            self.assertEqual(
                _helper_death_disposition("error", False, reason), "excuse",
                "reason=%r" % (reason,))

    def test_the_shared_helper_agrees_with_the_truth_table(self):
        """_helper_death_excused() is the ONE entry point, and it must
        not drift from the truth table it wraps."""
        import forkrun.run as _unused
        R = sys.modules["forkrun.run"]
        saved = R._abort_reason_now
        try:
            class _Lib:
                def __init__(self, reason):
                    self._reason = reason

                def fr_py_abort_reason(self):
                    return self._reason
            for reason, expect in ((0, False), (1, True), (2, True),
                                    (None, False), (-1, False)):
                R._abort_reason_now = lambda lib, r=reason: r
                self.assertEqual(
                    _helper_death_excused("error", False, _Lib(reason)),
                    expect, "reason=%r" % (reason,))
        finally:
            R._abort_reason_now = saved


class TestNoHelperDeathSiteDecidesForItself(unittest.TestCase):
    """The structural invariant, and the reason this defect class
    cannot recur: a site that decides locally is a site the next fix
    will miss."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(__file__), "..", "forkrun",
                            "run.py")
        cls.src = open(path, encoding="utf-8").read()
        cls.tree = ast.parse(cls.src)
        cls.lines = cls.src.split("\n")
        (cls.scopes, cls.nested_defs,
         cls.innermost) = _scopes_and_owners(cls.tree)
        # staticmethod: accessed through self, a plain function would be
        # bound and take `self` as its first argument.
        cls.nested_defs = staticmethod(cls.nested_defs)
        cls.innermost = staticmethod(cls.innermost)

    def _helper_death_sites(self):
        out = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Raise):
                continue
            seg = "\n".join(self.lines[node.lineno - 1:node.end_lineno])
            if not HELPER_DEATH.search(seg):
                continue
            out.append(node)
        return out

    def test_there_are_enough_sites_for_the_check_to_mean_something(self):
        sites = self._helper_death_sites()
        self.assertGreaterEqual(
            len(sites), 10,
            "the helper-death family moved (%d sites) -- update this test"
            % (len(sites),))

    def test_every_helper_death_site_asks_the_shared_decision(self):
        offenders = []
        for node in self._helper_death_sites():
            sc = self.innermost(node.lineno)
            if sc is None:
                offenders.append("line %d: no enclosing scope" % node.lineno)
                continue
            nested = self.nested_defs(sc)
            consults = [i + 1
                        for i in range(sc.lineno - 1, sc.end_lineno)
                        if "_helper_death_excused" in self.lines[i]
                        and not any(a <= i + 1 <= b for a, b in nested)]
            if not any(c < node.lineno for c in consults):
                offenders.append("line %d (%s): decides locally"
                                 % (node.lineno, sc.name))
        self.assertEqual(
            [], offenders,
            "these helper-death sites decide for themselves instead of "
            "asking _helper_death_excused():\n  %s"
            % "\n  ".join(offenders))

    def test_the_consult_comes_before_the_abort_in_its_block(self):
        """The abort publishes the reason the consult reads.

        A consult placed AFTER the abort always sees "excuse" (the
        reason the abort just published) and so swallows a genuine
        helper failure. D-PORT2 says so explicitly: "query the abort
        reason BEFORE the handler's own abort -- the order is the fix".

        The statement that asks the decision may be either shape --
        `if not _helper_death_excused(...)` (ask and branch) or
        `excused = _helper_death_excused(...)` (ask, then branch on the
        saved answer) -- so the check looks for ANY statement that
        mentions the shared decision.
        """
        offenders = []
        for parent in ast.walk(self.tree):
            body = getattr(parent, "body", None)
            if not isinstance(body, list):
                continue
            aborts = [i for i, s in enumerate(body) if _aborts_directly(s)]
            consults = [i for i, s in enumerate(body) if _asks_directly(s)]
            if not aborts or not consults:
                continue
            if min(consults) > min(aborts):
                offenders.append(
                    "line %d: an abort runs before the consult in the "
                    "same block" % (body[min(consults)].lineno,))
        self.assertEqual(
            [], offenders,
            "the consult must precede the abort in its block:\n  %s"
            % "\n  ".join(offenders))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestTheMaterializedPathsAgree(unittest.TestCase):
    """The two supervision shapes of the SAME path must not disagree.

    Before the fix the materialized PLAIN path raised "materialized
    scanner failed" where the REACTOR path did not, for one condition
    and one reason. That asymmetry IS the bug: the same rule, two
    answers.
    """

    def test_the_plain_and_reactor_materialized_paths_answer_alike(self):
        import ctypes
        import tempfile
        import traceback

        def _segv(batch):
            ctypes.string_at(0)      # SIGSEGV in the worker child
            return b"unreachable"

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "in.txt")
            with open(path, "w") as fh:
                for i in range(50000):
                    fh.write("line %08d abcdefghijklmnop\n" % i)

            def drive(**kw):
                try:
                    for _ in forkrun.stream(_segv, path, workers=4,
                                            order="index", **kw):
                        pass
                except Exception:            # noqa: BLE001
                    return traceback.format_exc()
                return ""

            plain = drive()
            reactor = drive(orchestrator=True)
            self.assertEqual(
                "materialized scanner failed" in plain,
                "materialized scanner failed" in reactor,
                "the two materialized supervision shapes disagree:\n"
                "--- plain ---\n%s\n--- reactor ---\n%s"
                % (plain, reactor))
            assert_no_zombies(self)


if __name__ == "__main__":
    unittest.main()
