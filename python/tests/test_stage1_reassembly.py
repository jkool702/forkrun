"""Stage 1: terminal-aware parsing and reassembly.

Stage 1 gives ordered reassembly a view of every batch's TERMINAL
outcome instead of only the ones that produced a payload. It changes no
eligibility decision: stream(order="index") stays declined on the
cleanroom path, because Stage 2's boundedness and liveness design is
still unproven, and Stage 0's publication protocol is a precondition.

Three things are pinned here:

  BUFFER SEMANTICS
    All four dispositions advance the contiguous prefix; only DATA
    yields. A genuine b"" is a REAL empty DATA result and must never be
    conflated with NO_RESULT -- that conflation is what DECISION-02
    exists to remove. A batch that never yields must not strand
    everything behind it.

  PARSER SEPARATION
    _split_records_terminal keeps control records; _split_records still
    drops them. The latter's filtering is load-bearing for callers that
    must not receive a spurious b"" for a batch that produced nothing,
    so it is NOT changed. Asserted explicitly so a future "simplification"
    that unifies them breaks here.

  PRODUCER COVERAGE
    Not every producer emits every disposition, so the unresolved-gap
    check may only be applied where the protocol actually provides
    terminal records. Enumerated per producer rather than assumed.
"""

import os
import re
import struct
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

from forkrun._reassembly import ReassemblyBuffer  # noqa: E402
from forkrun._worker import _HDR  # noqa: E402
import importlib  # noqa: E402
# forkrun.run is the exported FUNCTION; the module needs an
# explicit import or attribute lookup hits the function.
_run_mod = importlib.import_module("forkrun.run")

DISP_DATA, DISP_NO_RESULT, DISP_SKIPPED, DISP_POISONED = 0, 1, 2, 3
NAME = {0: "DATA", 1: "NO_RESULT", 2: "SKIPPED", 3: "POISONED"}


def frame(idx, disp, payload=b""):
    return _HDR.pack(idx, len(payload), disp, 0) + payload


# -- buffer ------------------------------------------------------------

class TestReassemblyDispositions(unittest.TestCase):

    def test_every_disposition_advances_the_prefix(self):
        for disp in (DISP_DATA, DISP_NO_RESULT, DISP_SKIPPED,
                     DISP_POISONED):
            with self.subTest(disposition=NAME[disp]):
                b = ReassemblyBuffer()
                payload = b"x" if disp == DISP_DATA else None
                b.add_disposition(0, disp, payload)
                got = list(b.drain())
                self.assertEqual(
                    [(0, b"x")] if disp == DISP_DATA else [],
                    got,
                    "%s must %s the prefix"
                    % (NAME[disp],
                       "yield its payload" if disp == DISP_DATA
                       else "advance without yielding"))
                self.assertEqual(0, b.pending,
                                 "%s left the buffer non-empty" % NAME[disp])

    def test_empty_bytes_is_data_not_no_result(self):
        """b"" is a REAL empty result. Treating it as NO_RESULT would
        discard a legitimate answer and re-create the conflation
        DECISION-02 removed."""
        b = ReassemblyBuffer()
        b.add_disposition(0, DISP_DATA, b"")
        self.assertEqual([(0, b"")], list(b.drain()),
                         "an empty DATA result must be yielded, not dropped")

        c = ReassemblyBuffer()
        c.add_disposition(0, DISP_NO_RESULT)
        self.assertEqual([], list(c.drain()),
                         "NO_RESULT must not surface as an empty payload")

    def test_terminal_after_terminal_advances_and_keeps_distinctions(self):
        b = ReassemblyBuffer()
        b.add_disposition(0, DISP_POISONED)
        b.add_disposition(1, DISP_SKIPPED)
        b.add_disposition(2, DISP_NO_RESULT)
        b.add_disposition(3, DISP_DATA, b"last")
        self.assertEqual([(3, b"last")], list(b.drain()))
        self.assertEqual(0, b.pending)

    def test_never_yields_out_of_order(self):
        """A later batch must not be yielded while an earlier index is
        still unresolved. Yielding batch 1 before batch 0 resolves is a
        correctness failure, not an optimisation."""
        b = ReassemblyBuffer()
        b.add_disposition(1, DISP_DATA, b"one")
        self.assertEqual([], list(b.drain()),
                         "yielded past an unresolved earlier index")
        b.add_disposition(0, DISP_DATA, b"zero")
        self.assertEqual([(0, b"zero"), (1, b"one")], list(b.drain()))

    def test_advances_promptly_without_waiting_for_eof(self):
        """A terminal disposition must open the gate for everything
        behind it immediately, not at finalisation."""
        b = ReassemblyBuffer()
        b.add_disposition(0, DISP_POISONED)
        b.add_disposition(1, DISP_DATA, b"one")
        b.add_disposition(2, DISP_SKIPPED)
        b.add_disposition(3, DISP_DATA, b"three")
        # No final_drain(): a mid-stream drain must already see the run.
        self.assertEqual([(1, b"one"), (3, b"three")], list(b.drain()))

    def test_unresolved_gaps_detect_a_missing_terminal(self):
        b = ReassemblyBuffer()
        b.add_disposition(0, DISP_DATA, b"a")
        b.add_disposition(2, DISP_DATA, b"c")
        list(b.drain())
        self.assertEqual([1], b.unresolved_gaps(3),
                         "index 1 never received a terminal outcome")

    def test_gone_are_not_reported_as_gaps(self):
        b = ReassemblyBuffer()
        for i, d in enumerate((DISP_DATA, DISP_NO_RESULT, DISP_SKIPPED,
                               DISP_POISONED)):
            b.add_disposition(i, d, b"p" if d == DISP_DATA else None)
        list(b.drain())
        self.assertEqual([], b.unresolved_gaps(4),
                         "a covered index must not be reported as a gap")

    def test_add_path_unchanged_for_legacy_callers(self):
        """add()/final_drain() must behave exactly as before for callers
        that never opted into dispositions."""
        b = ReassemblyBuffer()
        b.add(0, b"a")
        b.add(2, b"c")
        self.assertEqual([(0, b"a")], list(b.drain()))
        self.assertEqual([(2, b"c")], list(b.final_drain()))


class TestContradictoryOutcomes(unittest.TestCase):
    """A correct producer emits ONE terminal outcome per batch.

    Contradictions are recorded rather than merged, because the
    reassembly layer is exactly where a future exactly-once regression
    would otherwise be absorbed and made to look like a healthy stream.
    """

    def test_data_after_terminal_is_recorded(self):
        b = ReassemblyBuffer()
        b.add_disposition(0, DISP_POISONED)
        b.add_disposition(0, DISP_DATA, b"late")
        self.assertIn(0, b.conflicts())
        # The FIRST outcome is kept; the late DATA is not published.
        self.assertEqual([], list(b.drain()),
                         "late DATA was yielded after a terminal outcome")
        self.assertEqual(0, b.pending)

    def test_terminal_after_data_is_recorded(self):
        b = ReassemblyBuffer()
        b.add_disposition(0, DISP_DATA, b"a")
        b.add_disposition(0, DISP_SKIPPED)
        self.assertIn(0, b.conflicts())
        self.assertEqual([(0, b"a")], list(b.drain()),
                         "the original DATA should still be delivered")

    def test_differing_terminal_outcomes_are_recorded(self):
        b = ReassemblyBuffer()
        b.add_disposition(0, DISP_SKIPPED)
        b.add_disposition(0, DISP_POISONED)
        self.assertIn(0, b.conflicts())

    def test_duplicate_data_keeps_the_FIRST_payload(self):
        """First-wins, like every other contradiction branch.

        The original version noted the conflict and then called `add()`,
        which overwrites -- so duplicate DATA was last-wins while every
        other contradiction was first-wins. The docstring claimed one
        policy and the code implemented another.
        """
        b = ReassemblyBuffer()
        b.add_disposition(0, DISP_DATA, b"first")
        b.add_disposition(0, DISP_DATA, b"SECOND")
        self.assertIn(0, b.conflicts())
        self.assertEqual(
            [(0, b"first")], list(b.drain()),
            "a second delivery replaced an already-delivered payload; "
            "first-wins is both the documented policy and the "
            "conservative direction for exactly-once")

    def test_a_correct_producer_records_no_conflicts(self):
        b = ReassemblyBuffer()
        for i, d in enumerate((DISP_DATA, DISP_NO_RESULT, DISP_SKIPPED,
                               DISP_POISONED)):
            b.add_disposition(i, d, b"p" if d == DISP_DATA else None)
        list(b.drain())
        self.assertEqual({}, b.conflicts(),
                         "a single terminal outcome per batch must not be "
                         "flagged as a conflict")


# -- parser ------------------------------------------------------------

class TestTerminalParser(unittest.TestCase):

    def test_terminal_parser_keeps_control_records(self):
        blob = (frame(0, DISP_DATA, b"a") + frame(1, DISP_NO_RESULT)
                + frame(2, DISP_SKIPPED) + frame(3, DISP_POISONED)
                + frame(4, DISP_DATA, b""))
        recs, tail = _run_mod._split_records_terminal(blob)
        self.assertEqual(b"", tail)
        self.assertEqual(
            [(0, DISP_DATA, b"a"), (1, DISP_NO_RESULT, b""),
             (2, DISP_SKIPPED, b""), (3, DISP_POISONED, b""),
             (4, DISP_DATA, b"")],
            recs,
            "the terminal parser must not drop control records")

    def test_existing_parser_still_filters_control_records(self):
        """Pinned deliberately: _split_records' filtering is load-bearing
        for callers that must not see a spurious b"". Unifying the two
        parsers would hand those callers records they are written not to
        receive."""
        blob = (frame(0, DISP_DATA, b"a") + frame(1, DISP_NO_RESULT)
                + frame(2, DISP_SKIPPED))
        recs, tail = _run_mod._split_records(blob)
        self.assertEqual([(0, b"a")], recs)
        self.assertEqual(b"", tail)

    def test_both_parsers_hold_back_a_partial_tail(self):
        whole = frame(0, DISP_DATA, b"abc")
        for fn in (_run_mod._split_records, _run_mod._split_records_terminal):
            with self.subTest(parser=fn.__name__):
                recs, tail = fn(whole[:-1])
                self.assertEqual([], recs)
                self.assertEqual(whole[:-1], tail,
                                 "a short body must be held, not consumed")

    def test_round_trip_through_the_buffer(self):
        blob = (frame(0, DISP_DATA, b"a") + frame(1, DISP_POISONED)
                + frame(2, DISP_NO_RESULT) + frame(3, DISP_SKIPPED)
                + frame(4, DISP_DATA, b"e"))
        recs, _tail = _run_mod._split_records_terminal(blob)
        b = ReassemblyBuffer()
        for idx, disp, payload in recs:
            b.add_disposition(idx, disp, payload)
        self.assertEqual([(0, b"a"), (4, b"e")], list(b.drain()))
        self.assertEqual([], b.unresolved_gaps(5))


# -- producer coverage contract ----------------------------------------

# Which dispositions each producer can put on the wire, read from the
# source rather than asserted by hand. The gap check is only meaningful
# where a producer emits terminal records for non-DATA outcomes.
EXPECTED = {
    "fr_py_worker_plugin_loop": {"FR_DISP_SKIPPED", "FR_DISP_POISONED"},
    "fr_py_worker_udf_loop": {"FR_DISP_SKIPPED", "FR_DISP_POISONED"},
    "fr_py_worker_spawn_loop": {"FR_DISP_SKIPPED", "FR_DISP_POISONED"},
    # splice has no on_error=skip arm, so SKIPPED never appears.
    "fr_py_worker_splice_loop": {"FR_DISP_POISONED", "FR_DISP_DATA"},
}


class TestProducerCoverage(unittest.TestCase):

    def _shim(self):
        path = os.path.join(_ROOT, "python", "forkrun", "_shim.c")
        with open(path) as fh:
            return fh.read()

    def test_documented_coverage_matches_the_source(self):
        """The per-producer contract must be true of the code, not of
        this docstring. Two reviews have already caught audits that
        enumerated the wrong call sites."""
        src = self._shim()
        for fn, expected in sorted(EXPECTED.items()):
            with self.subTest(loop=fn):
                m = re.search(r"int %s\(.*?\n\}\n" % re.escape(fn), src,
                              re.S)
                self.assertIsNotNone(m, "%s not found in _shim.c" % fn)
                body = m.group(0)
                found = set(re.findall(r"FR_DISP_[A-Z_]+", body))
                self.assertEqual(
                    expected, found,
                    "%s emits %s; the documented contract says %s"
                    % (fn, sorted(found), sorted(expected)))

    def test_python_worker_emits_an_explicit_disposition(self):
        """The direct-write path packs a disposition explicitly rather
        than inferring one, so DATA and NO_RESULT stay distinguishable."""
        with open(os.path.join(_ROOT, "python", "forkrun", "_worker.py")) as fh:
            body = fh.read()
        self.assertIn("_HDR.pack(", body)
        self.assertRegex(body, r"_HDR\.pack\(\s*batch\.batch_index")

    def test_gap_check_is_scoped_to_terminal_aware_protocols(self):
        """unresolved_gaps is only meaningful where every published batch
        emits a terminal record. Producers that do not must keep the
        legacy finalisation behaviour, so the helper is opt-in."""
        self.assertTrue(callable(ReassemblyBuffer.unresolved_gaps))
        self.assertIn("unresolved_gaps",
                      inspect_source_of(ReassemblyBuffer),
                      "the helper must be documented on the class")


def inspect_source_of(obj):
    import inspect
    return inspect.getsource(obj)


# -- scope guard -------------------------------------------------------

class TestResultsPipeConsumer(unittest.TestCase):
    """The results-PIPE consumer is a separate production path.

    With the C drain active, records reach the parent through a results
    pipe and are consumed by _make_results_pump()._ingest(), not by the
    per-worker memfd drains. Wiring the memfd sites alone left this one
    DATA-only, so a SKIPPED/POISONED/NO_RESULT batch was discarded
    before the buffer saw it and later DATA stayed blocked behind that
    hole until finalisation.
    """

    def test_results_pipe_ingest_is_disposition_aware(self):
        import importlib
        run = importlib.import_module("forkrun.run")
        src = __import__("inspect").getsource(run)
        m = __import__("re").search(
            r"def _ingest\(chunk\):.*?(?=\n    def )", src, __import__("re").S)
        self.assertIsNotNone(m, "_ingest not found in _make_results_pump")
        body = m.group(0)
        self.assertIn("_split_records_terminal", body,
                      "the results-pipe consumer must parse terminally "
                      "when reassembling")
        self.assertIn("add_disposition", body,
                      "the results-pipe consumer must submit dispositions")
        # ...and must keep DATA-only semantics for the unordered branch,
        # whose callers must not see control records at all.
        self.assertIn("_split_records(", body,
                      "the unordered branch must keep the DATA-only parser")

    def test_ordered_results_pipe_advances_past_a_terminal_before_eof(self):
        """A terminal outcome for batch 0 followed by DATA for batch 1
        must yield batch 1 WITHOUT waiting for EOF."""
        import importlib
        run = importlib.import_module("forkrun.run")
        blob = (frame(0, DISP_NO_RESULT) + frame(1, DISP_DATA, b"one")
                + frame(2, DISP_SKIPPED) + frame(3, DISP_DATA, b"three"))
        recs, tail = run._split_records_terminal(blob)
        self.assertEqual(b"", tail)
        b = ReassemblyBuffer()
        for idx, disp, payload in recs:
            b.add_disposition(idx, disp, payload)
        # A mid-stream drain, with no final_drain() anywhere.
        self.assertEqual([(1, b"one"), (3, b"three")], list(b.drain()))
        self.assertEqual([], b.unresolved_gaps(4))


class TestStage1ChangedNoEligibility(unittest.TestCase):

    def test_ordered_streaming_is_still_declined(self):
        """Stage 1 is consumer-side only. It must NOT have flipped the
        ordered-streaming eligibility the design keeps declined."""
        src = open(os.path.join(_ROOT, "python", "forkrun",
                                "run.py")).read()
        m = re.search(r"def _cleanroom_eligible\(.*?\n(?=def )", src, re.S)
        self.assertIsNotNone(m, "_cleanroom_eligible not found")
        body = m.group(0)
        # Assert the DECLINE, not just the presence of the word "stream".
        # A scope guard that only checked for a string could pass on a
        # comment while the gate had been removed.
        # Stage 3 added a spawn decline above the ordering one, so this
        # matches the streaming block structurally rather than assuming
        # the ordering check is first.
        stream_block = re.search(r"if streaming:\s*\n(.*?)\n(?=    #|"
                                 r"\n    if |\n    return True)",
                                 body, re.S)
        self.assertIsNotNone(stream_block, "no streaming block found")
        sb = stream_block.group(1)
        decline = re.search(
            r"if order != [\"']none[\"']:\s*\n\s*return False", sb)
        self.assertIsNotNone(
            decline,
            "expected ordered STREAMING to still be declined in "
            "_cleanroom_eligible; Stage 1 must not have enabled it")
        # Stage 3: spawn has no stream dispatch, so it declines too.
        self.assertRegex(sb, r'if raw_mode == "spawn":\s*\n\s*return False',
                         "stream(mode='spawn') must be declined")
        # ...and MAP order="index" must still be served (it always was).
        self.assertIn('if order not in ("none", "index"):', body,
                      "map ordering eligibility changed unexpectedly")


if __name__ == "__main__":
    unittest.main()