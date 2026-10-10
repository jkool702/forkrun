"""C0.1 -- the capability matrix agrees with the independent oracle.

Four things are checked. The fourth is the one that makes the first three
mean anything:

  1. AGREEMENT -- every cell of the 16,128-cell matrix resolves the same way
     in the live predicate and in `tools/capability_oracle.py`.
  2. COVERAGE -- the enumeration exercises every outcome AND every rule.
     Without this, agreement is cheap: an oracle predicting only SERVED
     would agree with a predicate refusing everything.
  3. REGRESSIONS -- the contract points that were historically wrong, pinned
     by name, because a generic rule check would not catch them.
  4. INDEPENDENCE -- the oracle cannot see the predicate.

Independence is structural rather than editorial: `tools/capability_oracle.py`
imports nothing from forkrun, and `test_oracle_cannot_see_the_predicate`
enforces that by AST so it cannot rot into a comment.

Run: python3 -m unittest discover -s python/tests
"""

import ast
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "tools"))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import capability_matrix                                    # noqa: E402
import capability_oracle as oracle                           # noqa: E402

_CELLS = None


def cells():
    """The whole matrix, enumerated once."""
    global _CELLS
    if _CELLS is None:
        _CELLS = capability_matrix.collect()
    return _CELLS


class _MatrixBase(unittest.TestCase):
    """Shared tempdir so source objects can be built for direct calls."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def call(self, fact):
        """Run the live predicate on a Facts row."""
        src = capability_matrix.make_source(fact.source_kind, self._tmp.name)
        try:
            return capability_matrix.call_predicate(fact, src)
        finally:
            capability_matrix.cleanup_source(fact.source_kind, src)


class TestAgreement(_MatrixBase):

    def test_predicate_agrees_with_oracle_on_every_cell(self):
        """Every cell resolves identically in the predicate and the oracle."""
        mismatches = []
        for f, _ok, _reason, actual in cells():
            want, _rule = oracle.expected(f)
            if actual != want:
                mismatches.append((f, want, actual))
        self.assertEqual(
            [], mismatches[:5],
            "%d/%d cells disagree; first 5 shown. The oracle cites the "
            "documented contract, so one of the two is wrong."
            % (len(mismatches), len(cells())))

    def test_served_declined_split_matches(self):
        """Agreement on the DECISION, not merely on the reason text.

        Guards the classification layer. If an anchor string were widened
        until every decline fell into one bucket, the outcome test could
        pass while the served/declined split itself was wrong.
        """
        bad = []
        for f, ok, _reason, outcome in cells():
            want, _rule = oracle.expected(f)
            if (outcome == oracle.SERVED) != bool(ok):
                bad.append((f, ok, outcome))
            if (want == oracle.SERVED) != bool(ok):
                bad.append((f, ok, want))
        self.assertEqual([], bad[:5],
                         "served/declined split disagrees between the two")


class TestCoverage(_MatrixBase):

    def test_every_declined_outcome_is_exercised(self):
        """Stops the oracle from being trivially satisfiable.

        A rule that never fires is indistinguishable from a rule that is
        wrong, so every outcome must be reachable from the matrix.
        """
        reached = {outcome for _f, _ok, _r, outcome in cells()}
        missing = set(oracle.OUTCOMES) - reached
        self.assertEqual(set(), missing,
                         "outcomes never exercised: %s" % sorted(missing))
        self.assertNotIn("UNCLASSIFIED", reached,
                         "a predicate reason matched no oracle anchor")

    def test_every_oracle_rule_fires(self):
        """Per-rule coverage, not just per-outcome.

        Two rules could share an outcome while one of them was dead code.
        """
        fired = {oracle.expected(f)[1] for f, _ok, _r, _o in cells()}
        unfired = {r[0] for r in oracle.RULES} - fired
        self.assertEqual(set(), unfired,
                         "oracle rules that never fire: %s" % sorted(unfired))

    def test_served_fraction_is_plausibly_small(self):
        """Sanity floor, not a correctness claim.

        Guards against an axis silently losing its effect, which would make
        the entire matrix resolve to SERVED and pass every other test here.
        """
        all_cells = cells()
        served = sum(1 for c in all_cells if c[1])
        frac = served / len(all_cells)
        self.assertTrue(0 < frac < 0.01,
                        "served fraction %.4f looks wrong; an axis may have "
                        "lost its effect" % frac)

    def test_matrix_size_is_stable(self):
        """Pins the cell count so an axis cannot be dropped unnoticed."""
        self.assertEqual(16128, len(cells()))


class TestRegressions(_MatrixBase):

    def test_regression_points(self):
        """Each historically-wrong contract point, pinned by name."""
        for name, fact, want, _rule, _why in oracle.REGRESSIONS:
            with self.subTest(point=name):
                ok, reason = self.call(fact)
                got = oracle.classify(ok, reason)
                self.assertEqual(want, got,
                                 "%s: oracle says %s, predicate says %s (%r)"
                                 % (name, want, got, reason))

    def test_resume_refused_for_map_not_only_stream(self):
        """CR-FIX1-K, on its own because it is the subtlest of the set.

        The check used to live under `if streaming:`, which made the
        refusal unreachable for map(); and map()'s dispatch site never
        passed the arguments, so a resume request on an accelerated map()
        call was silently dropped rather than refused.
        """
        for kind in ("map", "stream"):
            with self.subTest(kind=kind):
                f = oracle.Facts(kind, "path", "plugin", 1, "none", True,
                                 False, False, "state.json", None)
                ok, reason = self.call(f)
                self.assertFalse(
                    ok, "resume= was accepted for %s() and must be refused (%r)"
                        % (kind, reason))

    def test_checkpoint_refused_without_resume(self):
        """checkpoint_file alone is enough to decline, independent of resume."""
        for resume in (None, "state.json"):
            with self.subTest(resume=resume):
                f = oracle.Facts("map", "path", "plugin", 1, "none", True,
                                 False, False, resume, "ckpt.json")
                ok, _reason = self.call(f)
                self.assertFalse(ok, "checkpoint_file= was accepted")

    def test_map_and_stream_agree_on_the_shared_envelope(self):
        """The shared gates are not stream-only.

        map and stream have a deliberately DIFFERENT envelope for order and
        strict_poison, but the gates above the streaming block -- nodes,
        mode, orchestrator, order, resume -- must not differ between them.
        A second hand-written predicate at the stream() dispatch site had
        already drifted from the map() one once.
        """
        for axes in (("nodes", 2), ("mode", "python"), ("orchestrator", False),
                     ("order", "sorted"), ("resume", "state.json")):
            with self.subTest(gate=axes[0]):
                base = dict(kind="map", source_kind="path", mode="plugin",
                            nodes=1, order="none", orchestrator=True,
                            strict_poison=False, return_stats=False,
                            resume=None, checkpoint_file=None)
                base[axes[0]] = axes[1]
                m = self.call(oracle.Facts(**base))
                base["kind"] = "stream"
                s = self.call(oracle.Facts(**base))
                self.assertEqual(
                    oracle.classify(*m), oracle.classify(*s),
                    "map() and stream() disagree about the %s gate; the "
                    "envelope above the streaming block is meant to be "
                    "shared" % axes[0])


class TestIndependence(unittest.TestCase):

    def _oracle_path(self):
        return os.path.join(_ROOT, "tools", "capability_oracle.py")

    def test_oracle_cannot_see_the_predicate(self):
        """The oracle must not import forkrun -- enforced by AST.

        An independence claim held only by a comment is exactly the kind of
        claim this roadmap has been burned by. If this fails, the oracle is
        no longer independent and the agreement tests prove much less than
        they appear to.
        """
        with open(self._oracle_path()) as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        offending = sorted(m for m in imported
                           if m.split(".")[0] in ("forkrun", "_shim", "run"))
        self.assertEqual([], offending,
                         "oracle imports %s; it must be written from the "
                         "contract alone" % (offending,))

    def test_oracle_states_its_independence_where_readers_look(self):
        with open(self._oracle_path()) as fh:
            text = fh.read()
        self.assertIn("imports nothing from `forkrun`", text)


class TestDeliverable(unittest.TestCase):

    def test_committed_matrix_document_is_current(self):
        """The matrix is a generated deliverable and must not be stale."""
        with open(capability_matrix.MATRIX) as fh:
            have = fh.read()
        want = capability_matrix.render(cells())
        self.assertEqual(
            want, have,
            "%s is stale. Regenerate: python3 tools/capability_matrix.py"
            % capability_matrix.MATRIX)

    def test_matrix_documents_the_two_axis_corrections(self):
        """The findings are part of the deliverable, not just this test."""
        with open(capability_matrix.MATRIX) as fh:
            text = fh.read()
        self.assertIn("Replayability is not an eligibility axis", text)
        self.assertIn("return_stats", text)


if __name__ == "__main__":
    unittest.main()
