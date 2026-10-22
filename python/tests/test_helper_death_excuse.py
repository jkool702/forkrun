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


def _body_exits(body):
    """Does this BLOCK of statements leave the enclosing block?

    A block leaves as soon as ONE of its statements leaves: the rest
    are unreachable. An empty block does not leave.
    """
    if not body:
        return False
    return any(_exits_unconditionally(st) for st in body)


def _message_literal(raise_node):
    """The string literal of a raise's message, or None.

    Handles both a plain literal and the `"... %s" % (...)` form, which
    is how every helper-death message is written.
    """
    exc = getattr(raise_node, "exc", None)
    if not isinstance(exc, ast.Call) or not exc.args:
        return None
    a0 = exc.args[0]
    if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
        return a0.value
    if isinstance(a0, ast.BinOp) and isinstance(a0.left, ast.Constant) \
            and isinstance(a0.left.value, str):
        return a0.left.value
    return None


def _helper_death_sites(tree, parents, lines):
    """The helper-death raise sites, found STRUCTURALLY.

    A helper death is reported by one of two choreographies, and BOTH
    are structural -- neither depends on the error MESSAGE:

      * the abort-then-raise shape: a RuntimeError preceded by an
        engine abort in its own block (`lib.fr_py_abort()` then
        `raise RuntimeError(...)`);
      * the decision-then-raise shape: a raise inside the BODY of an
        `if` whose test consults the shared decision.

    The old census matched the message text, which made it fragile in
    a way that mattered: rewording a message could make a site
    DISAPPEAR from the check, and the check would still pass. The
    message family is kept as a THIRD net, for a site that reports a
    helper death with neither choreography -- but a site is found by
    its structure first.

    Deliberately NOT included: the interrupt path's
    `raise ForkrunInterrupted(...)` after an abort. That is the
    operator's Ctrl-C, not a helper death, and classifying it as one
    would be the overbroad classification this signature exists to
    avoid.
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise):
            continue
        seg = "\n".join(lines[node.lineno - 1:node.end_lineno])
        if (HELPER_DEATH.search(seg)
                or _aborts_before(node, parents)
                or _under_a_consult(node, parents)):
            out.append(node)
    return out


def _aborts_before(node, parents):
    """Is this a helper-death RUNTIMEERROR preceded by an ENGINE ABORT
    in its own block?"""
    if not _is_runtime_error(node):
        return False
    par = parents.get(id(node))
    body = getattr(par, "body", None)
    if not isinstance(body, list):
        return False
    for i, st in enumerate(body):
        if st is node:
            return any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "fr_py_abort"
                for j in range(i)
                for n in ast.walk(body[j]))
    return False


def _under_a_consult(node, parents):
    """Is this raise inside the BODY of an `if` whose test consults the
    shared decision?

    EITHER polarity counts -- the point of the signature is to FIND
    the site, not to judge it, and a polarity flip (the mutation the
    checker must reject) leaves the consult in place.

    A raise in the ELSE branch does not count: that branch runs when
    the condition is false.
    """
    cur = node
    while cur is not None:
        par = parents.get(id(cur))
        if par is None:
            return False
        if isinstance(par, ast.If):
            if cur in getattr(par, "orelse", []):
                return False
            if any(isinstance(n, ast.Call)
                   and getattr(n.func, "id", None) == "_helper_death_excused"
                   for n in ast.walk(par.test)):
                return True
        cur = par
    return False


def _is_runtime_error(node):
    """Does this raise a plain RuntimeError?"""
    exc = getattr(node, "exc", None)
    if isinstance(exc, ast.Call) and \
            getattr(exc.func, "id", None) == "RuntimeError":
        return True
    return False


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


def _negated_consult(node):
    """The consult call, if `node` is `not <consult>`.

    POLARITY MATTERS. `_helper_death_excused(...)` is TRUE when the
    death is EXCUSED. So a fatal raise may only execute when the
    decision said NOT excused -- which means the raise belongs in the
    NEGATED branch. A raise in the POSITIVE branch executes exactly
    when the death was excused: that is the shape that swallows a
    genuine helper failure, and it must be rejected.
    """
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = node.operand
        if isinstance(inner, ast.Call) and \
                getattr(inner.func, "id", None) == "_helper_death_excused":
            return inner
    return None


def _positive_consult(node):
    """The consult call, if `node` IS the consult (not negated)."""
    if isinstance(node, ast.Call) and \
            getattr(node.func, "id", None) == "_helper_death_excused":
        return node
    return None


def _exits_unconditionally(stmt):
    """Does this statement leave the enclosing block on EVERY path?

    The old `_exits` asked "is there a return/raise/break/continue
    ANYWHERE below this statement". That is not the question. An exit
    nested inside a conditional does not establish that every path
    through the outer statement exits:

        if _helper_death_excused(...):
            if some_other_condition:
                return
        raise RuntimeError("helper failed")

    The raise is still reachable when the decision said EXCUSED, so
    the branch does not establish the fall-through. This asks the
    question soundly, and answers False for anything it cannot
    establish: loops, try/finally, with, a bare expression, and an
    `if` with no `else` (which may fall through).
    """
    if isinstance(stmt, list):
        # A BLOCK of statements leaves when ONE of them leaves.
        return _body_exits(stmt)
    if isinstance(stmt, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
        return True
    if isinstance(stmt, ast.If):
        # BOTH branches must exit. An `if` with no else may fall
        # through, and an `except` handler that returns is not an exit
        # of the enclosing block.
        if stmt.orelse:
            return (_exits_unconditionally(stmt.body)
                    and _exits_unconditionally(stmt.orelse))
        return False
    return False


def _consult_names_upwards(node, parents):
    """Names assigned from the consult that DOMINATE `node`.

    The assignment is often nested several blocks deep relative to the
    function, so the search walks UP from the use rather than looking
    only at the function's top-level statements.

    DOMINANCE, not proximity: only the statements BEFORE the current
    node in a block count. An assignment AFTER the use has not run
    yet, and an assignment in a SIBLING branch may never have run --
    neither makes the name hold the decision's value at the use.
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
                if st is cur:
                    break
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

    THE INVARIANT, IN REACHABILITY TERMS
    ------------------------------------
    The raise may not execute on any control-flow path on which
    `_helper_death_excused(...)` is TRUE. So the question is not
    "does the enclosing block mention the consult" but "does the
    decision's TRUE outcome PROVABLY prevent this raise from
    executing".

    SUPPORTED SHAPES -- a small, auditable set. Anything else is
    UNGOVERNED, and the check fails closed:

      1. The raise is inside the BODY of `if not <consult>:`. The
         body runs only when the decision said NOT excused.
      2. The raise is inside the BODY of `if not <name>:`, where
         <name> was assigned from the consult by a statement that
         DOMINATES the `if`.
      3. The raise FOLLOWS `if <consult>: <unconditional exit>` in
         the same block. The exit leaves on every path, so the raise
         is reached only when the decision said NOT excused.

    Two shapes are therefore REJECTED that a name-matching check
    would accept:

      * the raise in the POSITIVE branch (`if _helper_death_excused(
        ...): raise`) -- it executes exactly when the death was
        excused;
      * the raise after `if _helper_death_excused(...): <exit>` where
        the exit is CONDITIONAL -- the fall-through may still reach
        the raise.
    """
    if parents is None:
        parents = _parents(tree)
    node = raise_node
    in_orelse = False
    while node is not None:
        par = parents.get(id(node))
        if par is None:
            return False

        # Is the child we came from in the parent's ELSE branch? That
        # has to be known BEFORE the shapes are considered: the else
        # branch of a negated consult runs exactly when the death WAS
        # excused.
        if isinstance(par, ast.If) and node in getattr(par, "orelse", []):
            in_orelse = True

        if isinstance(par, ast.If) and not in_orelse:
            # SHAPE 1: the NEGATED branch of the consult.
            if _negated_consult(par.test) is not None:
                return True
            # SHAPE 2: `if not <name>:` with <name> assigned from the
            # consult by a dominating statement.
            test = par.test
            if isinstance(test, ast.UnaryOp) and \
                    isinstance(test.op, ast.Not) and \
                    isinstance(test.operand, ast.Name):
                if test.operand.id in _consult_names_upwards(par, parents):
                    return True

        body = getattr(par, "body", None)
        if isinstance(body, list):
            for st in body:
                if st is node:
                    break
                # SHAPE 3: a preceding `if <consult>: <exit>` in the
                # same block, where the exit is UNCONDITIONAL.
                if isinstance(st, ast.If) and \
                        _positive_consult(st.test) is not None and \
                        _body_exits(st.body):
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


class TestTheCheckerRejectsTheKnownMutations(unittest.TestCase):
    """The checker must FAIL on the shapes that would reintroduce the
    defect. A checker that has never been shown to fail is not a
    guard.

    Every mutation below is one the review named. Each is applied to a
    REAL site in the REAL tree (in memory -- the file on disk is never
    touched) or to a synthetic snippet, and the checker must then
    report the site as UNGOVERNED.

    A mutation test that passes because the snippet failed to PARSE,
    or because the target site was not FOUND, proves nothing. So
    every case below asserts that the site was found and that the
    checker reached a verdict on it.
    """

    def _tree(self):
        path = os.path.join(os.path.dirname(__file__), "..", "forkrun",
                            "run.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        return ast.parse(src), src

    def _negated_consult_ifs(self, tree):
        """The `if not _helper_death_excused(...)` statements in the tree."""
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and \
                    _negated_consult(node.test) is not None:
                out.append(node)
        return out

    def _raises_in(self, node):
        return [n for n in ast.walk(node) if isinstance(n, ast.Raise)]

    def _verdict(self, src):
        """(governed, found) for the raises in a snippet."""
        tree = ast.parse(src)
        parents = _parents(tree)
        raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise)]
        if not raises:
            return None, 0
        verdicts = [governed_by_the_decision(tree, r, parents)
                    for r in raises]
        return verdicts, len(raises)

    # -- 1. the polarity flipped ---------------------------------------

    def test_the_polarity_flip_is_rejected(self):
        """`if not consult:` becomes `if consult:` -- the raise then
        executes exactly when the death was EXCUSED."""
        tree, src = self._tree()
        mutated = src.replace("if not _helper_death_excused(",
                               "if _helper_death_excused(", 1)
        self.assertNotEqual(src, mutated, "the mutation did not apply")
        verdicts, n = self._verdict(mutated)
        self.assertGreater(n, 0, "the mutated tree has no raise")
        # The flipped site is the one that must now be UNGOVERNED. Find
        # it: it is the first negated-consult-shaped `if` in the
        # ORIGINAL tree, whose raise the mutation just un-governed.
        # The mutated statement is the FIRST textual occurrence, so
        # find its line that way -- ast.walk is not source-ordered,
        # and the test must exercise the site it actually mutated.
        idx = src.index("if not _helper_death_excused(")
        first_line = src[:idx].count("\n") + 1
        mtree = ast.parse(mutated)
        mparents = _parents(mtree)
        mif = None
        for node in ast.walk(mtree):
            if isinstance(node, ast.If) and node.lineno == first_line:
                mif = node
                break
        self.assertIsNotNone(mif,
                             "the mutated statement was not found -- the "
                             "test would pass without reaching the checker")
        target = None
        for node in ast.walk(mif):
            if isinstance(node, ast.Raise):
                target = node
                break
        self.assertIsNotNone(target,
                             "the mutated site has no raise -- the test "
                             "would pass without reaching the checker")
        self.assertIsNotNone(target,
                             "the mutated site was not found -- the test "
                             "would pass without reaching the checker")
        self.assertFalse(
            governed_by_the_decision(mtree, target, mparents),
            "the checker accepted a raise whose polarity was flipped: it "
            "now executes exactly when the death was excused")

    # -- 2. the raise moved to the excused branch ----------------------

    def test_the_raise_moved_to_the_excused_branch_is_rejected(self):
        """`if not consult: <body>` becomes `if not consult: <body> else:
        <raise>` -- the raise now runs when the death was excused."""
        tree, _ = self._tree()
        checked = 0
        for stmt in self._negated_consult_ifs(tree):
            raises = self._raises_in(stmt)
            if not raises:
                continue
            # Move the body into the else branch and the raise into the
            # positive branch: the raise now executes when the decision
            # said EXCUSED.
            stmt.body, stmt.orelse = stmt.orelse, stmt.body
            ast.fix_missing_locations(stmt)
            parents = _parents(tree)
            for r in self._raises_in(stmt):
                self.assertFalse(
                    governed_by_the_decision(tree, r, parents),
                    "the checker accepted a raise moved into the EXCUSED "
                    "branch (line %d)" % (r.lineno,))
            checked += 1
            break
        self.assertGreater(checked, 0,
                           "no site with a raise under a negated consult "
                           "was found -- the mutation never reached the "
                           "checker")

    # -- 3. a conditionally reached return -----------------------------

    def test_a_conditionally_reached_return_does_not_govern(self):
        """A `return` nested inside a conditional does not establish
        that the branch exits."""
        src = ('def f(lib, st):\n'
               '    if _helper_death_excused("error", False, lib):\n'
               '        if some_other_condition:\n'
               '            return\n'
               '    raise RuntimeError("forkrun: scanner failed (status %r)"'
               ' % (st,))\n')
        verdicts, n = self._verdict(src)
        self.assertEqual(1, n, "the snippet must contain exactly one raise")
        self.assertFalse(
            verdicts[0],
            "the checker accepted a raise guarded only by a "
            "CONDITIONALLY reached return")

    # -- 4. a raise after a nested conditional exit --------------------

    def test_a_nested_conditional_exit_does_not_dominate(self):
        """The fall-through is not established by a nested exit."""
        src = ('def f(lib, st):\n'
               '    if _helper_death_excused("error", False, lib):\n'
               '        if a:\n'
               '            return 1\n'
               '        else:\n'
               '            return 2\n'
               '    raise RuntimeError("forkrun: scanner failed (status %r)"'
               ' % (st,))\n')
        verdicts, n = self._verdict(src)
        self.assertEqual(1, n)
        self.assertTrue(
            verdicts[0],
            "the checker rejected a raise guarded by an UNCONDITIONAL "
            "exit (both branches leave)")

    # -- 5. a sibling branch -------------------------------------------

    def test_a_sibling_branch_does_not_govern(self):
        """A valid consult in one branch cannot govern a raise in a
        sibling branch."""
        src = ('def f(lib, st):\n'
               '    if _helper_death_excused("error", False, lib):\n'
               '        log_it()\n'
               '    if something_else:\n'
               '        raise RuntimeError("forkrun: scanner failed'
               ' (status %r)" % (st,))\n')
        verdicts, n = self._verdict(src)
        self.assertEqual(1, n)
        self.assertFalse(
            verdicts[0],
            "the checker accepted a raise in a SIBLING branch of a valid "
            "consult")

    # -- 6. an unguarded raise in an executor that consults correctly --

    def test_an_unguarded_raise_in_a_real_executor_is_rejected(self):
        """The reviewer's case, on the REAL tree, through the CENSUS.

        The injected raise must be FOUND by the census (which is
        structural now) and then REJECTED by the checker. A mutation
        that the census cannot see would pass this test vacuously.
        """
        tree, _ = self._tree()
        parents = _parents(tree)
        target = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if any(_consult_call(st) is not None
                   for st in node.body
                   if isinstance(st, (ast.If, ast.Assign))):
                target = node
                break
        self.assertIsNotNone(target,
                             "no executor consults the shared decision")
        injected = ast.parse(
            "def _probe():\n"
            "    if True:\n"
            "        lib.fr_py_abort()\n"
            "        raise RuntimeError(\"forkrun: scanner failed"
            " (status %r)\" % (1,))\n")
        stmt = injected.body[0].body[0]
        raise_node = stmt.body[1]
        target.body.insert(0, injected.body[0])
        ast.fix_missing_locations(target)
        parents = _parents(tree)
        self.assertFalse(
            governed_by_the_decision(tree, raise_node, parents),
            "the checker accepted an UNGOVERNED helper-death raise "
            "injected into %s, which already contains a valid consult"
            % (target.name,))

    # -- the census must survive a reworded message --------------------

    def test_a_reworded_message_stays_covered(self):
        """Rewording a helper-death message must not remove the site
        from the census.

        The old census matched the message text, so a reworded message
        made a site DISAPPEAR from the check -- and the check still
        passed. The census is structural now, so the site is still
        found, and the checker still has a verdict on it.
        """
        tree, src = self._tree()
        parents = _parents(tree)
        # a real, governed site
        sites = self._negated_consult_ifs(tree)
        self.assertTrue(sites, "no negated-consult site in the tree")
        stmt = None
        raise_node = None
        for cand in sites:
            for r in self._raises_in(cand):
                if _message_literal(r) is not None:
                    stmt = cand
                    raise_node = r
                    break
            if raise_node is not None:
                break
        self.assertIsNotNone(raise_node,
                             "no site with a literal message was found")
        self.assertTrue(governed_by_the_decision(tree, raise_node, parents),
                        "the site is not governed to begin with")

        # reword its message: the census must still find it, by
        # STRUCTURE, and the checker must still reach a verdict. The
        # message is taken from the site itself, so the test does not
        # depend on a particular wording existing.
        msg = _message_literal(raise_node)
        self.assertIsNotNone(msg,
                            "the site's message is not a string literal")
        new_msg = msg.replace("failed", "went away", 1)
        self.assertNotEqual(msg, new_msg,
                            "the message has no 'failed' to reword")
        reworded = src.replace(msg, new_msg, 1)
        self.assertNotEqual(src, reworded, "the rewording did not apply")
        self.assertNotIn(msg, reworded,
                         "the rewording did not change the message")
        mtree = ast.parse(reworded)
        mparents = _parents(mtree)
        found = [n for n in ast.walk(mtree)
                 if isinstance(n, ast.Raise)
                 and n.lineno == raise_node.lineno]
        self.assertTrue(found,
                        "the reworded site vanished from the tree")
        # the census finds it by structure -- the REAL census, not a
        # re-implementation of it
        census = [n.lineno for n in
                  _helper_death_sites(mtree, mparents,
                                      reworded.split("\n"))]
        self.assertIn(
            raise_node.lineno, census,
            "a reworded helper-death site dropped out of the census: the "
            "census still depends on the message text")
        # and the checker still governs it
        self.assertTrue(
            governed_by_the_decision(mtree, found[0], mparents),
            "the reworded site is no longer governed")

    def _structural_census(self, tree, parents, src):
        """The line numbers the census finds, with the message family
        REMOVED -- i.e. the sites found by STRUCTURE alone."""
        lines = src.split("\n")
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise):
                continue
            par = parents.get(id(node))
            body = getattr(par, "body", None)
            if not isinstance(body, list):
                continue
            for i, st in enumerate(body):
                if st is node:
                    if any(
                            isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Attribute)
                            and n.func.attr == "fr_py_abort"
                            for j in range(i)
                            for n in ast.walk(body[j])):
                        out.append(node.lineno)
                    break
        return out

    # -- 7. the abort must come AFTER the consult ---------------------

    def test_an_abort_before_the_consult_is_rejected(self):
        """A consult placed AFTER the abort always sees "excuse".

        The abort publishes the reason the consult reads, so a consult
        after it swallows a genuine helper failure. The ordering check
        is about the ORDER on the path, not about a consult and an
        abort merely co-existing in a function.
        """
        tree, _ = self._tree()
        parents = _parents(tree)
        # a real site: `if not consult: <abort>; <raise>`
        target = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            if _negated_consult(node.test) is None:
                continue
            aborts = [st for st in node.body
                      if any(isinstance(n, ast.Call)
                             and isinstance(n.func, ast.Attribute)
                             and n.func.attr == "fr_py_abort"
                             for n in ast.walk(st))]
            if aborts:
                target = (node, aborts[0])
                break
        self.assertIsNotNone(target,
                             "no real site with an abort under a consult "
                             "was found -- the mutation never reached the "
                             "checker")
        stmt, abort_stmt = target
        par = parents.get(id(stmt))
        block = getattr(par, "body", None)
        self.assertIsNotNone(block, "the site's block is not a list")
        # Move the abort OUT of the consult's body and BEFORE it: the
        # abort now publishes the reason the consult is about to read.
        stmt.body.remove(abort_stmt)
        idx = block.index(stmt)
        block.insert(idx, abort_stmt)
        ast.fix_missing_locations(par)

        # The ordering check, run over the mutated tree.
        offenders = []
        for parent in ast.walk(tree):
            body = getattr(parent, "body", None)
            if not isinstance(body, list):
                continue
            for i, st in enumerate(body):
                if _consult_call(st) is None:
                    continue
                for j in range(i):
                    aborted = any(
                        isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "fr_py_abort"
                        for n in ast.walk(body[j]))
                    if aborted:
                        offenders.append(st.lineno)
                        break
        self.assertTrue(
            offenders,
            "the checker accepted an abort that runs BEFORE the consult "
            "in the same block: the consult would then always read "
            "'excuse' and swallow a genuine helper failure")


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

    def _under_a_consult(self, node):
        """Is this raise inside the BODY of an `if` whose test consults
        the shared decision?

        The second structural signature of a helper-death site: the
        decision is consulted and the raise follows it. EITHER
        polarity counts -- the point of the signature is to find the
        site, not to judge it, and a polarity flip (the mutation this
        checker must reject) leaves the consult in place.

        A raise in the ELSE branch does not count: that branch runs
        when the condition is false.
        """
        cur = node
        while cur is not None:
            par = self.parents.get(id(cur))
            if par is None:
                return False
            if isinstance(par, ast.If):
                if cur in getattr(par, "orelse", []):
                    return False
                if _consult_call(par) is not None or \
                        any(isinstance(n, ast.Call)
                            and getattr(n.func, "id", None)
                            == "_helper_death_excused"
                            for n in ast.walk(par.test)):
                    return True
            cur = par
        return False

    def _aborts_before(self, node):
        """Is this a helper-death RUNTIMEERROR preceded by an ENGINE
        ABORT in its own block?

        The helper-death choreography is: consult the shared decision,
        abort the engine, then raise. The abort call is the STRUCTURAL
        signature of a helper-death site, and -- unlike the message --
        it does not change when the message is reworded.

        The exception TYPE is part of the signature, and it is what
        keeps the classification narrow. The abort-then-raise shape is
        also how the INTERRUPT path reports itself
        (`raise ForkrunInterrupted(...)` after `fr_py_abort()`), and
        that is not a helper death: it is the operator's Ctrl-C.
        Classifying it as one would be the overbroad classification
        this signature exists to avoid.
        """
        if not self._is_runtime_error(node):
            return False
        par = self.parents.get(id(node))
        body = getattr(par, "body", None)
        if not isinstance(body, list):
            return False
        for i, st in enumerate(body):
            if st is node:
                return any(
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "fr_py_abort"
                    for j in range(i)
                    for n in ast.walk(body[j]))
        return False

    def _helper_death_sites(self):
        """The helper-death raise sites (see the module-level census)."""
        return _helper_death_sites(self.tree, self.parents, self.lines)

    def _is_runtime_error(self, node):
        """Does this raise a plain RuntimeError?"""
        exc = node.exc
        if isinstance(exc, ast.Call) and \
                getattr(exc.func, "id", None) == "RuntimeError":
            return True
        return False

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
