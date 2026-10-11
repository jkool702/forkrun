"""Independent expected-behaviour oracle for the cleanroom acceleration envelope.

C0.1 requires an oracle that is NOT the predicate re-expressed -- a table
that merely restates `_cleanroom_eligible` proves nothing, because it
inherits every mistake the predicate has.

The strongest available guarantee is structural rather than editorial. **This
module imports nothing from `forkrun` and cannot see the predicate's body.**
It is written from the documented contract alone:

  * the `_cleanroom_eligible` docstring (run.py:647-693),
  * the CR-FIX1 outcome contract (run.py:898, run.py:1025),
  * `dev/supervisor/CLEANROOM_EXPANSION_ROADMAP.md` section 4.

If a rule here disagrees with the predicate, one of the two is wrong, and the
citation on each rule says which document to re-read first.

Evaluation is FIRST-MATCH-WINS over ordered rules, because the ORDER in which
the predicate declines is part of the contract: it decides which warning the
caller actually sees when several decline conditions hold at once.

Two precedence classes, and the difference matters:

  * R1-R7 precedence is **load-bearing**. Several can hold simultaneously
    (nodes=2 AND mode="python" AND orchestrator=False), and the winner is
    the message the user gets. Reordering these silently changes observable
    behaviour.
  * R8-R10 precedence is **immaterial**. They classify mutually exclusive
    source kinds, so at most one can hold. Their relative order here is an
    arbitrary convenience and carries no contract weight.
"""

from typing import NamedTuple

# ---------------------------------------------------------------------------
# The axes. These are the facts a CALL carries. They are deliberately the
# public API's parameters -- not internal state, and not runtime properties
# of the data being processed.
#
# Replayability is NOT here, and its absence is a finding rather than an
# oversight: `replayable = pre_ingest or _source_is_reopenable(source)`
# (run.py:1025) is decided AFTER the launcher has run, in the outcome
# contract. It answers "may we fall back?", not "may the launcher serve this
# call?". Roadmap section 4.1 lists replayable/non-replayable as an envelope
# axis; it is an OUTCOME axis. See dev/supervisor/CLEANROOM_CAPABILITY_MATRIX.md.
# ---------------------------------------------------------------------------


class Facts(NamedTuple):
    """One cell of the matrix: everything a call tells the envelope."""

    kind: str            # "map" | "stream"
    source_kind: str     # see SOURCE_KINDS
    mode: str            # "plugin" | "python" | "spawn" | "splice"
    nodes: int           # 1 | 2 | 4
    order: str           # "none" | "index" | "sorted"
    orchestrator: bool
    strict_poison: bool
    return_stats: bool
    resume: str | None
    checkpoint_file: str | None


SOURCE_KINDS = ("path", "fd", "fileobj", "iterable",
                "missing", "dir", "bogus")

# ---------------------------------------------------------------------------
# Outcomes. `anchor` is the stable substring that classifies a predicate
# reason string into this outcome. Keeping it a short, distinctive fragment
# means a harmless rewording of the surrounding prose will not break the
# test, but gutting the fragment will.
# ---------------------------------------------------------------------------

SERVED = "SERVED"

OUTCOMES = {
    SERVED: None,
    "DECLINE_NODES": "UMA single-node only",
    # Anchor is a SUBSTRING of the predicate's refusal text, so it must
    # track it. Widened with P1-3 when mode='udf' was admitted alongside
    # mode='plugin'; a stale anchor here shows up as UNCLASSIFIED on
    # every non-served mode, which is a loud failure rather than a quiet
    # one -- but it reads as "the oracle is wrong", not "the anchor
    # drifted".
    "DECLINE_MODE": "only (got",
    "DECLINE_ORDER": "is not served; the launcher relies on downstream",
    "DECLINE_RESUME": "resume=/checkpoint_file= is not served",
    "DECLINE_STREAM_ORDER": "the stream path has no collect step",
    "DECLINE_STREAM_POISON": "no poison count reaches a streaming caller",
    "DECLINE_SOURCE_MISSING": "source is not an existing file",
    "DECLINE_SOURCE_DIR": "source is a directory",
    "DECLINE_SOURCE_TYPE": "source must be a path, an open descriptor, or",
}


def classify(ok, reason):
    """Map a predicate result onto an outcome id, for comparison."""
    if ok:
        return SERVED
    for outcome, anchor in OUTCOMES.items():
        if outcome != SERVED and anchor and anchor in reason:
            return outcome
    return "UNCLASSIFIED"


# ---------------------------------------------------------------------------
# THE ORACLE. Ordered, first-match-wins. Each rule is the contract's own
# words plus a citation; none of it was derived by reading the predicate's
# body, and none of it could be -- see the module docstring.
# ---------------------------------------------------------------------------

RULES = [
    ("R1", "nodes",
     lambda f: f.nodes != 1,
     "DECLINE_NODES",
     "docstring: 'UMA single node -- no multi-node rings'"),

    ("R2", "mode",
     lambda f: f.mode not in ("plugin", "udf"),
     "DECLINE_MODE",
     "docstring: 'mode=plugin -- it dlopens an object and calls an entry "
     "point'; and the plugin must export forkrun_use_ctx, since a plugin "
     "without it is driven by the legacy ARGV/stdout route whose output "
     "lands on the worker's stdout, not the memfd -- exit 78, not silent "
     "success with an empty result set. "
     "P1-3 adds mode='udf', served wherever plugin is: the launcher "
     "dlopens a per-minor helper, initialises the interpreter before "
     "forking, and selects fr_py_worker_udf_loop, which has the same "
     "signature and the same lifecycle. The refusal reason does not "
     "transfer -- a UDF has no ctx dialect to be mismatched on -- but the "
     "envelope is identical, so the outcome is too."),

    # R3 (orchestrator) REMOVED. It used to decline orchestrator=False with
    # "the launcher supervises unconditionally, so serving False would hand a
    # caller who asked for fail-fast silent batch recovery". DECISION-03
    # fixed that structurally -- the launcher's fail-fast branch RETURNS
    # before the recovery call -- so both models are served and the rule no
    # longer has anything to assert.

    ("R4", "order",
     lambda f: f.order not in ("none", "index"),
     "DECLINE_ORDER",
     "docstring: 'order in (none, index)'. The launcher forks no C orderer, "
     "but does not need to: collect_records sorts by index for map, and "
     "stream reassembles parent-side from the batch_idx already in the "
     "framing"),

    ("R5", "resume/checkpoint",
     lambda f: f.resume is not None or f.checkpoint_file is not None,
     "DECLINE_RESUME",
     "CR-FIX1-K: the launcher neither transports nor implements "
     "checkpoint/resume. The check sits ABOVE the streaming block, so it "
     "applies to map() too -- it used to live under `if streaming:`, which "
     "made the refusal unreachable for map(), and the map() dispatch site "
     "did not pass the arguments, so a resume request was silently dropped "
     "on an accelerated path"),

    ("R6", "stream+order",
     lambda f: f.kind == "stream" and f.order != "none",
     "DECLINE_STREAM_ORDER",
     "docstring + inline note: the stream path has no collect step to sort "
     "with, and its parent-side reassembly handles order='none' only. "
     "NOTE the asymmetry with R4: map SERVES order='index', stream does "
     "not. A single predicate holds both, deliberately"),

    ("R7", "stream+strict_poison",
     lambda f: f.kind == "stream" and f.strict_poison,
     "DECLINE_STREAM_POISON",
     "docstring: strict_poison is served for map via the counter channel "
     "([version][poisoned] written to a memfd after the join, relying on "
     "g_state being SHARED). But no poison count reaches a streaming "
     "caller, so stream declines it"),

    ("R8", "source missing",
     lambda f: f.source_kind == "missing",
     "DECLINE_SOURCE_MISSING",
     "inline: a path that does not exist is not servable"),

    ("R9", "source directory",
     lambda f: f.source_kind == "dir",
     "DECLINE_SOURCE_DIR",
     "inline: a directory is not servable"),

    ("R10", "source type",
     lambda f: f.source_kind == "bogus",
     "DECLINE_SOURCE_TYPE",
     "inline: source must be a path, an open descriptor, or an iterable"),
]


def expected(f):
    """Return (outcome_id, rule_id) for a cell, from the contract alone."""
    for rule_id, _name, cond, outcome, _cite in RULES:
        if cond(f):
            return outcome, rule_id
    return SERVED, "R0"


# ---------------------------------------------------------------------------
# Contract points that were historically WRONG. These are the assertions with
# the most value in the whole matrix, because each one corresponds to a real
# defect that reached this codebase. If the predicate regresses on any of
# them, the generic rule checks would still pass -- these are the checks that
# would not.
#
# Each names the defect it locks down.
# ---------------------------------------------------------------------------

REGRESSIONS = [
    ("resume_is_refused_for_map_not_just_stream",
     Facts("map", "path", "plugin", 1, "none", True, False, False,
           "state.json", None),
     "DECLINE_RESUME", "R5",
     "CR-FIX1-K: the refusal was unreachable for map() because the check "
     "lived under `if streaming:`, and map()'s dispatch site never passed "
     "resume at all -- so the envelope could not see it"),

    ("both_supervision_models_are_served",
     Facts("map", "path", "plugin", 1, "none", False, False, False, None, None),
     SERVED, "R0",
     "orchestrator=False used to be DECLINED (DECLINE_ORCH), because the "
     "launcher supervised unconditionally and a caller asking for fail-fast "
     "would silently get recovery. DECISION-03 gave the launcher a fail-fast "
     "policy whose branch returns before the recovery call, so the refusal "
     "reason no longer holds"),

    ("map_serves_order_index",
     Facts("map", "path", "plugin", 1, "index", True, False, False, None, None),
     SERVED, "R0",
     "ordering is applied downstream by shared code, so the launcher needs "
     "no C orderer to honour it"),

    ("map_serves_strict_poison",
     Facts("map", "path", "plugin", 1, "none", True, True, True, None, None),
     SERVED, "R0",
     "served via the counter channel; both were previously declined and "
     "return_stats was a live P0 bug reporting poisoned=0 for a run that "
     "had poisoned batches"),

    ("stream_declines_order_index_that_map_serves",
     Facts("stream", "path", "plugin", 1, "index", True, False, False, None, None),
     "DECLINE_STREAM_ORDER", "R6",
     "asymmetry is intentional; a second hand-written predicate at the "
     "stream() dispatch site had already drifted from the map() one once, "
     "requiring not-orchestrator while this one required orchestrator"),

    ("stream_serves_order_none",
     Facts("stream", "path", "plugin", 1, "none", True, False, False, None, None),
     SERVED, "R0",
     "the stream path's actual envelope"),

    ("descending_precedence_puts_orchestrator_before_order",
     Facts("map", "path", "plugin", 2, "sorted", False, True, True,
           "s.json", "c.json"),
     "DECLINE_NODES", "R1",
     "five decline conditions hold simultaneously. R1 wins, so the caller "
     "is told about nodes first rather than about the last thing checked"),

    ("resume_outranks_stream_order",
     Facts("stream", "path", "plugin", 1, "index", True, False, False,
           "s.json", None),
     "DECLINE_RESUME", "R5",
     "R5 sits above the streaming block precisely so that resume is refused "
     "before the stream/order distinction is consulted"),
]
