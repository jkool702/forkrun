"""A helper child's death is fatal UNLESS an abort is already in flight.

THE FAILURE MODE THIS LOCKS DOWN. D-PORT2/D6 introduced the
abort-aware classification ("an abort already in flight makes helper
deaths expected (emergency path), not fatal") and wired it into 2 of
the 28 places the front end turns a helper child's non-zero exit into a
fatal error. The other 26 had the same rule written out -- or, in the
materialized PLAIN path's inline `_scan_pump`, omitted entirely.

That is exactly the failure the de-duplication pass exists to remove: a
fix lands in the copies its author happened to find, and lives on in the
execution paths nobody looked at. The fix here is therefore not "patch
twenty-six sites" but **one decision point** every site asks, so the
next change to the rule lands everywhere by construction.

Two invariants, both checked here:

1. **No site may decide for itself.** Every helper-death raise must be
   CONTROL-FLOW GOVERNED by the shared decision -- not merely in a
   function that happens to mention it. A function that consults the
   decision in one branch and raises a fatal error unguarded in
   another is exactly the shape this test exists to catch, so the check
   is about control flow, and it **fails closed**: an unfamiliar
   pattern is treated as a violation, not as a pass.
2. **The consult must come BEFORE the abort.** The abort publishes the
   reason the consult reads, so a consult placed after it always sees
   "excused" and silently swallows a genuine helper failure.
   D-PORT2 says so explicitly: "query the abort reason BEFORE the
   handler's own abort -- the order is the fix".
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

from _helpers import ChildLifecycleMixin, assert_no_zombies  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


# The helper-death message family: every place the front end turns a
# helper child's non-zero exit into a fatal error.
HELPER_DEATH = re.compile(
    r"(scanner failed|helper failed|orderer failed|reaper failed"
    r"|index/scan failed|scan failed|drain failed)")


# --------------------------------------------------------------------------
# The checker. It is a module-level function so it can be SELF-TESTED on a
# synthetic snippet -- which is how the "an unguarded raise next to a
# valid helper call" case is proven to fail, without mutating the tree.
# --------------------------------------------------------------------------

def _parents(tree):
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[id(child)] = node
    return out


def _consult_call(node):
    """A consult DIRECTLY in this statement.

    "Directly" matters: a consult nested deeper -- inside a nested
    `if` -- belongs to that nested statement, not to this one. Treating
    it as belonging to the outer statement made the checks see aborts
    and consults that are in entirely different branches.
    """
    if isinstance(node, ast.If):
        target = node.test
    elif isinstance(node, ast.Assign):
        target = node.value
    else:
        return None
    for n in ast.walk(target):
        if isinstance(n, ast.Call) and \
                getattr(n.func, "id", None) == "_helper_death_excused":
            return n
    return None


def _exits(stmt):
    """Does this statement leave the enclosing block?"""
    for n in ast.walk(stmt):
        if isinstance(n, (ast.Return, ast.Continue, ast.Break, ast.Raise)):
            return True
    return False


def _consult_names_upwards(node, parents):
    """Names assigned from the consult, in the enclosing block chain.

    The assignment is often nested several blocks deep relative to the
    function, so the search walks UP from the use rather than looking
    only at the function's top-level statements.
    """
    names = set()
    cur = node
    while cur is not None:
        par = parents.get(id(cur))
        if par is None:
            break
        body = getattr(par, "body", None)
        if isinstance(body, list):
            for st in body:
                if isinstance(st, ast.Assign) and \
                        _consult_call(st) is not None:
                    for t in st.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
        cur = par
    return names


def _owner(tree, node):
    best = None
    for t in tree.body:
        if isinstance(t, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and t.lineno <= node.lineno <= t.end_lineno:
            if best is None or t.lineno > best.lineno:
                best = t
    return best


def governed_by_the_decision(tree, raise_node, parents=None):
    """Is this raise CONTROL-FLOW DEPENDENT on the shared decision?

    Not "does the enclosing function mention the helper somewhere" --
    that is satisfiable by a helper call in an unrelated branch, which
    is precisely the shape this test exists to catch.

    A raise is governed when one of these holds:

      * it sits inside an `if` whose TEST is the consult (the
        `if not _helper_death_excused(...): raise` shape);
      * it sits inside an `if not <name>:` where <name> was assigned
        from the consult in an enclosing block (the
        `excused = ...; if not excused: raise` shape);
      * it is in a block that is only REACHED when a preceding
        `if _helper_death_excused(...): <exit>` did not exit -- so
        falling through means the decision said "not excused".

    Anything else is UNGOVERNED, and the check fails closed.
    """
    if parents is None:
        parents = _parents(tree)
    node = raise_node
    while node is not None:
        par = parents.get(id(node))
        if par is None:
            return False

        if isinstance(par, ast.If):
            test = ast.unparse(par.test)
            if "_helper_death_excused" in test:
                return True
            if test.startswith("not "):
                name = test[4:].strip()
                if name in _consult_names_upwards(par, parents):
                    return True

        body = getattr(par, "body", None)
        if isinstance(body, list):
            for st in body:
                if st is node:
                    break
                if isinstance(st, ast.If) and \
                        _consult_call(st) is not None:
                    if st.body and all(_exits(b) for b in st.body):
                        return True
        node = par
    return False


class TestTheCheckerItself(unittest.TestCase):
    """The checker must be proven on the shapes it is meant to catch.

    A checker that cannot be shown to fail is not a guard, so the
    "unguarded raise next to a valid helper call" case is exercised
    here, on a synthetic snippet, rather than by mutating the tree.
    """

    GUARDED = '''
def f(lib, st):
    if not _helper_death_excused("error", False, lib):
        raise RuntimeError("forkrun: scanner failed (status %r)" % (st,))
'''

    GUARDED_BY_ASSIGNMENT = '''
def f(lib, st):
    excused = _helper_death_excused("error", False, lib)
    if not excused:
        raise RuntimeError("forkrun: scanner failed (status %r)" % (st,))
'''

    GUARDED_BY_FALLTHROUGH = '''
def f(lib, st):
    if _helper_death_excused("error", False, lib):
        return True
    raise RuntimeError("forkrun: scanner failed (status %r)" % (st,))
'''

    UNGOVERNED = '''
def f(lib, st):
    if _helper_death_excused("error", False, lib):
        pass
    raise RuntimeError("forkrun: scanner failed (status %r)" % (st,))
'''

    UNGOVERNED_IN_A_SIBLING_BRANCH = '''
def f(lib, st):
    if _helper_death_excused("error", False, lib):
        log_it()
    if something_else:
        raise RuntimeError("forkrun: scanner failed (status %r)" % (st,))
'''

    def _raises(self, src):
        tree = ast.parse(src)
        parents = _parents(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                return governed_by_the_decision(tree, node, parents)
        raise AssertionError("the snippet has no raise")

    def test_it_accepts_the_guarded_shapes(self):
        for src in (self.GUARDED, self.GUARDED_BY_ASSIGNMENT,
                    self.GUARDED_BY_FALLTHROUGH):
            self.assertTrue(self._raises(src),
                            "the checker rejected a governed raise:\n%s" % src)

    def test_it_rejects_an_unguarded_raise_next_to_a_valid_call(self):
        """The case the reviewer named: a valid helper call in the same
        function, and a fatal raise the call does not govern.

        Note the consult's body must NOT exit: if it exits, falling
        through the consult means the decision said "not excused", and
        the raise IS governed. That is the difference between the
        fall-through shape and the ungoverned one.
        """
        for src in (self.UNGOVERNED, self.UNGOVERNED_IN_A_SIBLING_BRANCH):
            self.assertFalse(
                self._raises(src),
                "the checker accepted an unguarded raise next to a valid "
                "helper call:\n%s" % src)

    def test_it_rejects_an_unguarded_raise_injected_into_a_real_executor(self):
        """The reviewer's case, on the REAL tree.

        Take an executor that already consults the shared decision
        correctly, inject a LOCAL, UNGUARDED helper-death raise into it,
        and require the checker to flag it. This is the regression the
        weaker "is the helper mentioned in this function" check would
        have missed: the function still mentions the helper, and still
        has a valid consult -- and the injected raise is not governed by
        either.
        """
        path = os.path.join(os.path.dirname(__file__), "..", "forkrun",
                            "run.py")
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)

        # an executor that consults the decision
        target = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if any(_consult_call(st) is not None
                   for st in node.body if isinstance(st, (ast.If,
                                                        ast.Assign))):
                target = node
                break
        self.assertIsNotNone(target,
                             "no executor consults the shared decision")

        # inject an unguarded raise at the TOP of its body: it is
        # reached whatever the decision says.
        injected = ast.parse(
            "def _probe():\n"
            "    raise RuntimeError(\"forkrun: scanner failed (status %r)\"\n"
            "        % (1,))\n")
        injected_raise = injected.body[0].body[0]
        target.body.insert(0, injected.body[0])
        ast.fix_missing_locations(target)

        parents = _parents(tree)
        self.assertFalse(
            governed_by_the_decision(tree, injected_raise, parents),
            "the checker accepted an UNGOARDED helper-death raise "
            "injected into %s, which already contains a valid helper "
            "call -- this is the case a 'mentions the helper' check "
            "would miss" % (target.name,))


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
        cls.parents = _parents(cls.tree)

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

    def test_every_helper_death_site_is_governed_by_the_decision(self):
        """The raise must be CONTROLLED by the shared decision.

        A function that consults the decision in one branch and raises
        a fatal error unguarded in another is exactly the shape this
        test exists to catch, so the check is about control flow, not
        about the presence of a helper call in the same function.
        """
        offenders = []
        for node in self._helper_death_sites():
            if not governed_by_the_decision(self.tree, node, self.parents):
                owner = _owner(self.tree, node)
                offenders.append(
                    "line %d (%s): the raise is not governed by the "
                    "shared decision" % (node.lineno,
                                         owner.name if owner else "?"))
        self.assertEqual(
            [], offenders,
            "these helper-death raises are not governed by the shared "
            "decision:\n  %s" % "\n  ".join(offenders))

    def test_the_consult_comes_before_the_abort_in_its_block(self):
        """The abort publishes the reason the consult reads.

        A consult placed AFTER the abort always sees "excuse" (the
        reason the abort just published) and so swallows a genuine
        helper failure. D-PORT2 says so explicitly: "query the abort
        reason BEFORE the handler's own abort -- the order is the fix".
        """
        offenders = []
        for parent in ast.walk(self.tree):
            body = getattr(parent, "body", None)
            if not isinstance(body, list):
                continue
            for i, stmt in enumerate(body):
                if _consult_call(stmt) is None:
                    continue
                for j in range(i):
                    aborted = any(
                        isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "fr_py_abort"
                        for n in ast.walk(body[j]))
                    if aborted:
                        offenders.append(
                            "line %d: an abort runs before the consult in "
                            "the same block" % (stmt.lineno,))
                        break
        self.assertEqual(
            [], offenders,
            "the consult must precede the abort in its block:\n  %s"
            % "\n  ".join(offenders))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestTheMaterializedPathsAgree(ChildLifecycleMixin, unittest.TestCase):
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
