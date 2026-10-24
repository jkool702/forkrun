"""The Stage 4 benchmark's integrity check.

`tools/bench_splice.py` decides whether a timed run counts. That
decision is made by `_records_tile`, and it is the only thing standing
between a corrupted pipeline and a published speedup figure.

This matters because the check it replaced was not one. The original was
`sorted(got) == sorted(want)` -- a byte-value HISTOGRAM -- which passes:

    sorted(got[::-1]) == sorted(want)   -> True

so a batch assembled backwards, or any other within-batch
rearrangement, validated. The round-8 review caught that; these tests
pin the replacement so it cannot silently weaken back.

The helper is loaded by source rather than imported, because
`bench_splice.py` executes a module-level `BODY % {...}` at import time
and is a script, not a library.
"""

import ast
import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
_BENCH = os.path.join(_ROOT, "tools", "bench_splice.py")


def _load_helpers():
    """Exec the helper definitions out of the script's BODY template.

    They are not module level: `bench_splice.py` keeps its child code in
    a triple-quoted BODY string that is later %-formatted into the
    program the child runs. So the source is parsed twice -- once to
    find the string constant, once to reach the defs inside it.
    """
    src = open(_BENCH).read()
    body_src = None
    for node in ast.parse(src).body:
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "BODY"
                        for t in node.targets)):
            # Render the %-placeholders first: BODY contains %(root)r
            # and %% escapes, which are not valid Python.
            body_src = ast.literal_eval(node.value) % {
                "root": os.path.join(_ROOT, "python")}
            break
    if body_src is None:
        raise unittest.SkipTest("no BODY template in bench_splice.py")
    wanted = {"_records_tile"}
    ns = {"sys": __import__("sys"), "os": os}
    for node in ast.parse(body_src).body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            exec(compile(ast.Module(body=[node], type_ignores=[]),
                         _BENCH, "exec"), ns)
    missing = wanted - set(ns)
    if missing:
        raise AssertionError("helper(s) missing: %r" % (missing,))
    return ns


class TestRecordsTile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(_BENCH):
            raise unittest.SkipTest("bench_splice.py not present")
        ns = _load_helpers()
        cls.tile = staticmethod(ns["_records_tile"])

    # Two unique, non-empty slices.
    A = b"line000000 payload\n"
    B = b"line000001 payload\n"

    def test_accepts_an_in_order_tiling(self):
        want = self.A + self.B
        self.assertTrue(self.tile(want, [self.A, self.B]))

    def test_accepts_an_out_of_order_tiling(self):
        """order="none" completes batches out of order BY DESIGN, so the
        check must not reject that."""
        want = self.A + self.B
        self.assertTrue(self.tile(want, [self.B, self.A]))

    def test_rejects_a_reversed_batch(self):
        """The case the histogram accepted and this must not."""
        want = self.A + self.B
        self.assertFalse(
            self.tile(want, [self.A[::-1], self.B]),
            "a reversed batch passed the integrity check")

    def test_rejects_a_dropped_batch(self):
        want = self.A + self.B
        self.assertFalse(self.tile(want, [self.A]))

    def test_rejects_a_duplicated_batch(self):
        want = self.A + self.B
        self.assertFalse(self.tile(want, [self.A, self.B, self.A]))

    def test_allows_any_delivery_permutation(self):
        """Swapping whole batches in delivery order is NOT a defect.

        An earlier version of this file asserted the opposite, and the
        assertion was wrong rather than the check: with order="none" a
        batch completing before an earlier one is the documented
        meaning of "none", and the tiling check sorts spans by offset
        precisely so that permutation is allowed.

        What must still hold is that each record is an intact contiguous
        slice. That is what the reversal and alteration tests cover, and
        they are the cases the byte-histogram check could not see.
        """
        # Non-palindromic chunks: "AAAA"[::-1] == "AAAA", so a
        # palindrome would make the mangling assertion below vacuous.
        a1, a2 = b"alpha", b"bravo"
        b1, b2 = b"delta", b"echo "
        want = a1 + a2 + b1 + b2
        self.assertTrue(self.tile(want, [a1, a2, b1, b2]))
        self.assertTrue(self.tile(want, [b1, b2, a1, a2]))
        self.assertTrue(self.tile(want, [b2, a2, b1, a1]))
        # ...but a permutation that also mangles a record is still caught.
        self.assertFalse(self.tile(want, [a1, b1[::-1], a2, b2]))

    def test_rejects_altered_bytes(self):
        want = self.A + self.B
        self.assertFalse(self.tile(want, [self.A, self.B + b"x"]))

    def test_rejects_empty_output(self):
        self.assertFalse(self.tile(self.A + self.B, []))

    def test_accepts_a_single_complete_record(self):
        want = self.A
        self.assertTrue(self.tile(want, [self.A]))

    def test_empty_records_are_ignored_not_counted(self):
        """A zero-length record carries no bytes, so it neither covers
        nor breaks coverage."""
        want = self.A + self.B
        self.assertTrue(self.tile(want, [self.A, b"", self.B]))


if __name__ == "__main__":
    unittest.main()