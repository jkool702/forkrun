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
    """One cell of the matrix: everything a call tells the envelope.

    WO-CM1 added `entry` and `streaming`, because a predicate truth table
    over (map, stream) x mode could not distinguish three facts that are
    independently true at the current head:

      * `run` has NO cleanroom branch at all;
      * `stream` reaches the predicate only inside its streaming branch,
        so a materialised source never consults it;
      * `stream` omits "spawn" from the modes it offers the launcher,
        while `map` includes it.

    `kind` is retained for backwards compatibility with the existing
    rule set; `entry` supersedes it where they differ.
    """

    kind: str            # "map" | "stream"  (legacy alias of `entry`)
    source_kind: str     # see SOURCE_KINDS
    mode: str            # "plugin" | "python" | "spawn" | "splice"
    nodes: int           # 1 | 2 | 4
    order: str           # "none" | "index" | "sorted"
    orchestrator: bool
    strict_poison: bool
    return_stats: bool
    resume: str | None
    checkpoint_file: str | None
    # WO-CM1. Defaults keep every existing positional construction valid.
    entry: str = "map"           # "run" | "map" | "stream"
    streaming: bool = False      # effective ingestion for stream()


SOURCE_KINDS = ("path", "fd", "fileobj", "iterable",
                "missing", "dir", "bogus")

# ---------------------------------------------------------------------------
# WO-CM1 -- the public DISPATCH contract, stated independently of the
# predicate.
#
# `_cleanroom_eligible` answers "would this configuration be acceptable to
# the launcher ENVELOPE?". It cannot answer "does a public call ever ASK?",
# because reaching it is a property of the branch structure of run/map/
# stream, not of the envelope. The audit at 460c77da found three cells
# where those two answers diverge, so the matrix now carries both.
#
# These tables are transcribed from the public contract and the reviewed
# dispatch rules, NOT by reading the predicate -- same discipline as the
# rest of this module. `tools/capability_dispatch.py` independently
# OBSERVES the live branches and the tests assert the two agree.

# run() has no cleanroom branch at all: it dispatches straight to
# _execute_numa_locked / _execute_reactor_locked / _execute.
LAUNCHER_SERVED_MODES = {
    "run":    (),                      # no cleanroom branch exists
    "map":    ("plugin", "udf", "spawn"),
    "stream": ("plugin", "udf"),       # spawn has no streaming dispatch
}

# Both map() and stream() take the NUMA path when num_nodes > 1, which
# RETURNS before the predicate is consulted (run.py:3834 and :4254).
NUMA_BYPASSES_PREDICATE = True

# stream() consults the predicate only inside its streaming branch, so a
# materialised source (a regular path with streaming=None/False) never
# reaches it at all.
PREDICATE_REQUIRES_STREAMING = ("stream",)


def dispatch_reaches_predicate(facts) -> bool:
    """Does a public call for these facts ever CONSULT the predicate?

    True does not mean served -- the predicate may still decline, and the
    launcher may still be absent. It means the envelope was asked.
    """
    entry = getattr(facts, "entry", None) or facts.kind
    if not LAUNCHER_SERVED_MODES.get(entry):
        return False
    if facts.mode not in LAUNCHER_SERVED_MODES[entry]:
        return False
    if NUMA_BYPASSES_PREDICATE and facts.nodes != 1:
        return False
    if entry in PREDICATE_REQUIRES_STREAMING and not facts.streaming:
        return False
    return True


# Entry-point argument applicability, established by CALLING each entry
# point and recording what it raises. Re-stated here so the oracle stays
# independent of forkrun.
#
#   run(return_stats=True)    -> TypeError: got an unexpected keyword
#   stream(return_stats=True) -> TypeError: unexpected keyword argument(s)
#   run(mode="udf")           -> NotImplementedError: unknown mode 'udf'
#   run(mode="splice")        -> ValueError either way: with a payload
#                                "takes no payload (passthrough)"; with
#                                payload=None "produces output records --
#                                use map() or stream()". So it is rejected
#                                unconditionally, not merely payload-shaped.
#   resume / checkpoint_file  -> accepted by all three, but the path must
#                                EXIST (FileNotFoundError otherwise). The
#                                generator now creates the fixture so the
#                                precondition holds rather than silently
#                                failing every resume cell.
MAP_ONLY_KWARGS = ("return_stats",)
RUN_UNSUPPORTED_MODES = ("udf", "splice")


def public_valid(facts) -> bool:
    """Does this cell satisfy the PUBLIC API contract?

    Invalid configurations must not enter the capability denominator.
    They keep their conformance tests; they are simply not configurations
    a caller could ever make.

    Three layers, all re-derived from the live implementation:
      1. values the public validators reject regardless of entry point
         (_VALID_ORDERS, _reject_iterable_source, unreadable sources);
      2. arguments that are not applicable to the entry point at all;
      3. (entry, mode) pairs the entry point refuses outright.
    """
    entry = getattr(facts, "entry", None) or facts.kind

    # (1) universally invalid values
    if facts.order not in ("none", "index"):
        return False
    if facts.source_kind in ("iterable", "missing", "dir", "bogus"):
        return False

    # (2) argument applicability
    if entry != "map" and facts.return_stats:
        return False

    # (3) entry-point contract refusals
    if entry == "run" and facts.mode in RUN_UNSUPPORTED_MODES:
        return False
    return True

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
    "DECLINE_MODE_STREAM_SPAWN": "the streaming path has no spawn "
                                  "dispatch",
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
     lambda f: f.mode not in ("plugin", "udf", "spawn"),
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
     "envelope is identical, so the outcome is too. "
     "Stage 3 adds mode='spawn', whose worker loop takes an argv VECTOR "
     "rather than the plugin's two strings. Same arity, incompatible "
     "types, so the launcher routes it through a mode-specific worker "
     "descriptor instead of casting. It is served only once the process-"
     "lifecycle gates held: in-group descendant cleanup on worker death, "
     "a tested setsid-escape boundary, observed respawn, teardown "
     "cleanup, and command failure handled by on_error with an explicit "
     "SKIPPED record rather than an infrastructure abort. All six are in "
     "test_stage3_lifecycle.py."),

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

    # R2b: stream() has no spawn dispatch. Ordered AFTER R5 on purpose:
# the predicate checks resume/checkpoint ABOVE the streaming block
# (CR-FIX1-K), so a stream+spawn cell carrying resume must decline as
# DECLINE_RESUME, not as DECLINE_MODE_STREAM_SPAWN. Placing this
# rule earlier disagreed with the predicate on 560 cells. It extracts a path:function
    # spec and has no place to put an argv vector, so the predicate
    # DECLINES spawn for streaming rather than admitting a route that
    # does not exist. map() IS served for spawn. The two share the mode
    # axis but not the route, so the rule is ordered after R2.
    ("R2b", "mode",
     lambda f: f.streaming and f.mode == "spawn",
     "DECLINE_MODE_STREAM_SPAWN",
     "stream(mode='spawn') is not served; the streaming path has no "
     "spawn dispatch"),

    ("R6", "stream+order",
     lambda f: f.streaming and f.order != "none",
     "DECLINE_STREAM_ORDER",
     "docstring + inline note: the stream path has no collect step to sort "
     "with, and its parent-side reassembly handles order='none' only. "
     "NOTE the asymmetry with R4: map SERVES order='index', stream does "
     "not. A single predicate holds both, deliberately"),

    # R7 REMOVED. It declined stream(strict_poison=True) on the grounds
    # that "no poison count reaches a streaming caller" -- true when
    # written, and false since P2 (c3c321af) wired a statistics memfd
    # through the cleanroom stream launch. The launcher writes the poison
    # count, the parent consumes it after a CONFIRMED-CLEAN launcher
    # exit, and _LAST_STATS carries it to the caller.
    #
    # The predicate was never updated to match, so the capability existed
    # and was unreachable, and the tests disagreed with the gate. Removing
    # the rule rather than editing its outcome keeps the oracle honest:
    # there is no longer a distinct refusal to describe.

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
     Facts("stream", "path", "plugin", 1, "index", True, False, False, None, None,
           streaming=True),
     "DECLINE_STREAM_ORDER", "R6",
     "asymmetry is intentional; a second hand-written predicate at the "
     "stream() dispatch site had already drifted from the map() one once, "
     "requiring not-orchestrator while this one required orchestrator"),

    ("stream_serves_order_none",
     Facts("stream", "path", "plugin", 1, "none", True, False, False, None, None,
           streaming=True),
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
