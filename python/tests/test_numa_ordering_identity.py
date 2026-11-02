"""W-EXP-2 step A: NUMA output-identity probe, pinned as a regression test.

WHAT THE SOURCE SAYS (forkrun_ring.c, frozen):

  * `out->batch_idx = my_read_idx` (ring.c:6385), where
    `local_state = &state[my_numa_node]` (ring.c:6158, 4166) -- the claim
    counter is PER NODE, so `batch_idx` is a per-node ticket and two
    nodes both emit 0, 1, 2, ...
  * The GLOBAL ordering key is `(major, minor)`, packed by FR_PACK_KEY,
    and the C orderer sorts on that packed key (ring.c:7673).
  * The wire framing `<QQII>` is (batch_idx, len, disposition, reserved):
    `major`/`minor` NEVER reach the parent. The parent cannot reconstruct
    global order from what it collects on its own.

WHAT THE PROBE CONFIRMS (this file):

  * On a corpus large enough that BOTH logical nodes scan, batch_idx
    values collide.
  * The C-orderer path (`order="index"`, production) is BYTE-EXACT
    against the independently constructed input sequence.
  * The Python fallback sort by batch_idx (collect_records' `sort(key=
    kv[0])`, used when the orderer is unavailable) is WRONG ORDER on the
    same corpus.

WHY THE FALLBACK HAZARD IS ASSERTED, NOT JUST DOCUMENTED. A test that
only proved the production path correct would not stop someone from
later "simplifying" to the sort -- it looks like a working shortcut
whenever the input is small enough that only one node claims. That is
precisely the failure the user's instruction warns about: a limited
test not exposing a collision must not be allowed to overrule the
source. So the wrongness of the sort is itself pinned.

WHY A REGULAR FILE, ONE WORKER PER NODE. The engine's small-file NUMA
routing is what makes both nodes real, and it is source-visible:
`ring_numa_ingest_main` scales a regular file's chunk size so every
node receives at least two chunks (the "Small File NUMA Starvation
Prevention" block), forces `TM_READ_WRITE` whenever `numa_enabled &&
num_nodes > 1`, and republishes one chunk per read with target
selection advancing from `last_target + 1` -- so successive chunks
alternate between the two nodes instead of piling onto node 0. One
worker per node (`workers=2` over `@2`) then guarantees each node's
published batches are claimed by that node's own worker; cross-node
stealing is a SCANNER-side operation (chunk queues), not a batch
claim. A FIFO is deliberately NOT used: the Python streaming spill
publishes on a different path whose chunking differs (observed: 86
chunks on node 0, 1 on node 1 -- the synthetic EOF marker), which is
exactly the single-real-node shape this test must not accept.

SCANNER STEALING IS A SEPARATE, LEGAL EFFECT. A starved scanner may
claim from a peer's chunk queue (the engine's distance-charged
stealing). On a loaded UMA host it can take ALL of one node's chunks,
leaving that node's own scanner with only its EOF marker to publish.
The liveness gate correctly refuses such a run -- it cannot exercise
cross-node batch claims -- but that is legal load balancing, not a
product failure. `_map_live` therefore retries that exact shape a
bounded number of times and accepts only a run that passes the gate.
A node that never received a real chunk (`chunk_head <= 1`) is the UMA
fallback the gate exists to reject, and a node whose queue was not
fully consumed is a scanner failure; neither is retried.

WHY THE GATE IS STRONGER THAN `rc == 0`. `fr_py_diag_node` returns
rc==0 even for a node whose counters are all zero (it is a bounds/
serviceability return, not a liveness claim). The earlier version of
this test accepted that, so a run whose data all went to one node
while the other received only the EOF marker passed the gate and then
failed the collision assertion with no evidence about why. The gate
below requires, per node, `write_idx > 0`, `read_idx > 0`,
`read_idx >= write_idx`, `scanner_finished == 1` and a used chunk
queue, and it runs BEFORE the collision assertion. The full per-node
rows are printed on failure.

WHAT THIS TEST DOES NOT CLAIM. This host has one PHYSICAL NUMA node;
all runs here use logical `@N` nodes and validate the ordering
PROTOCOL, not physical locality or bandwidth. Node liveness is verified
per run by probing `fr_py_diag_node` while the ring state is live
(inside the drain-audit window), never after `map()` has destroyed it.
"""

import ctypes
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

import forkrun  # noqa: E402
from forkrun import _bindings as _bindings  # noqa: E402

_RUN = sys.modules["forkrun.run"]

_PLUGIN_C = (
    '#include "forkrun_plugin.h"\n'
    "#include <stdio.h>\n"
    "int forkrun_use_ctx = FORKRUN_CTX_ENABLE|FORKRUN_CTX_FLAG_RAW;\n"
    "int copy_v1(int argc, char **argv, const struct forkrun_ctx *ctx){\n"
    "  (void)argc; (void)argv;\n"
    "  if(ctx==NULL||ctx->version<2) return -1;\n"
    "  uint64_t n=ctx->batch_byte_length;\n"
    "  const char *in=(const char*)(uintptr_t)ctx->reserved[0];\n"
    "  if(in==NULL) return -1;\n"
    "  if(n==0) return 0;\n"
    "  if(fwrite(in,1,(size_t)n,stdout)!=(size_t)n) return -2;\n"
    "  return fflush(stdout)==0?0:-2;}\n"
)

# Large enough that scanning spans multiple SCANNER_CHUNK_SIZE (2 MiB)
# chunks, so the small-file scaling gives each logical node real work.
N_LINES = 600000
LINE_FMT = "u%07d\n"
LINES_GRANULARITIES = (4096, 512)

# One worker per logical node: a node's own claims cannot be taken by
# another node's worker, so real per-node publication is preserved.
WORKERS_2_NODES = 2

# Bounded retries for a fixture run whose node liveness was lost to
# LEGAL scanner-side chunk stealing (see `_map_live`). Each retry is a
# fresh run; the gate is re-evaluated, never relaxed. Eight attempts
# make the residual probability of an all-stolen set of runs negligible
# even on a heavily loaded 4-vCPU runner, and a systematic single-node
# regression still fails after the last attempt with every attempt's
# per-node rows.
_MAP_LIVE_ATTEMPTS = 8


def _plugin(tmpdir):
    src = os.path.join(tmpdir, "p.c")
    with open(src, "w") as fh:
        fh.write(_PLUGIN_C)
    out = os.path.join(tmpdir, "p.so")
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2",
         "-I", str(REPO / "ring_loadables"), "-o", out, src],
        check=True, capture_output=True, text=True)
    return out + ":copy_v1"


def _row_activity_gaps(rows, num_nodes):
    """Explain, per node, why it does NOT prove that it did work.

    `fr_py_diag_node` returns rc==0 even for a node whose counters are
    all zero, so rc alone is not evidence. The required evidence is
    the engine's own publication protocol:

      write_idx >= 2       the node published at least two slots
      read_idx > 0         the node claimed at least one slot
      read_idx >= write_idx  every published slot was claimed
                           (read > write is the documented benign
                           straggler-ticket overshoot; `_numa_drain_audit`
                           uses `read < write` as the violation)
      scanner_finished == 1  its scanner published its final ring state
      chunk_head >= 2 and chunk_tail > 0  the node received and
                           consumed real chunks

    The >= 2 floors are load-bearing, not tidiness. A node that received
    ONLY the ingest's synthetic EOF marker reports write_idx=1,
    read_idx=1, chunk_head=1, chunk_tail=1 -- identical in shape to a
    node that did one real chunk, and exactly what a run whose data all
    landed on the other node produces. Accepting it is how the old
    `rc == 0` gate let such a run reach the collision assertion. A
    regular-file corpus is routed so every node receives at least two
    chunks (`ring_numa_ingest_main`'s small-file scaling says so in the
    source), so the floor rejects the degenerate shape without
    rejecting any run the engine is supposed to produce.

    Returns {node: [reason, ...]}; an empty dict means both nodes have
    real, complete activity.
    """
    gaps = {}
    by_node = {r[0]: r for r in rows}
    for node in range(num_nodes):
        row = by_node.get(node)
        if row is None:
            gaps[node] = ["no diagnostic row (probe failed)"]
            continue
        (node, rc, w, r, sf, ch, ct, te) = row
        bad = []
        if rc != 0:
            bad.append("fr_py_diag_node rc=%d" % rc)
        if w < 2:
            bad.append("write_idx=%d (fewer than 2 published slots: not "
                       "distinguishable from the synthetic EOF marker)"
                       % w)
        if r <= 0:
            bad.append("read_idx=0 (claimed no slots)")
        if r < w:
            bad.append("read_idx %d < write_idx %d (unclaimed published "
                       "slots)" % (r, w))
        if sf != 1:
            bad.append("scanner_finished=%d (final ring state not "
                       "published)" % sf)
        if ch < 2:
            bad.append("chunk_head=%d (the ingest routes >= 2 chunks per "
                       "node for a regular-file corpus; this node saw "
                       "only the EOF marker or no chunk)" % ch)
        if ct <= 0:
            bad.append("chunk_tail=0 (the node's scanner consumed no "
                       "chunk)")
        if bad:
            gaps[node] = bad
    return gaps


def _liveness_threshold(num_nodes, require_all):
    """How many distinct logical nodes must be active for this fixture."""
    return int(num_nodes) if require_all else 2


def _liveness_state(audits, num_nodes):
    """Per-node activity across every captured audit.

    Returns `(active, gap_report)`. A node is active only when
    `_row_activity_gaps` reports no gap for it. `gap_report` keeps the
    rows and the named reasons for every audit that had a gap, so the
    caller can either fail with the standard diagnostic or classify the
    gap before deciding whether another run is warranted.
    """
    active = set()
    gap_report = []
    for a in audits:
        rows = a["rows"] or []
        gaps = _row_activity_gaps(rows, int(a["num_nodes"]))
        active.update(n for n in range(int(a["num_nodes"]))
                      if n not in gaps)
        if gaps:
            gap_report.append({"rows": rows, "gaps": gaps})
    return active, gap_report


def _liveness_ok(active, num_nodes, require_all):
    """Does `active` satisfy the fixture's liveness requirement?"""
    needed = _liveness_threshold(num_nodes, require_all)
    if len(active) < needed:
        return False
    return (not require_all) or active == set(range(int(num_nodes)))


def _steal_explains_gaps(gap_report):
    """Is every liveness gap the legal scanner-side stealing shape?

    A starved scanner may claim from a peer's chunk queue (the engine's
    distance-charged stealing, `forkrun_ring.c`). When it takes ALL of a
    node's chunks, that node's own scanner publishes only its EOF
    marker, so its row is:

        write_idx == read_idx == 1, scanner_finished == 1,
        chunk_head >= 2, chunk_tail == chunk_head

    That is a legal scheduling outcome, not a UMA fallback: the ingest
    DID route real chunks to the node and every one was consumed. The
    ordering assertions are only meaningful when both nodes PUBLISHED,
    so a run of this shape is worth retrying.

    The UMA fallback this gate exists to reject looks different: the
    node receives only the synthetic EOF marker (`chunk_head <= 1`), so
    no peer could have taken real work from it. A partially consumed
    queue (`chunk_tail < chunk_head`) is also not stealing -- the node's
    scanner stopped with work still queued, which is a scanner failure.
    Both must fail immediately rather than be retried away.

    An EMPTY report is not evidence of stealing either. It means no
    audit observation explained the missing activity at all (no probe
    recorded, or no gap named), and absence of evidence cannot be
    classified as a legal outcome: the policy retries only a POSITIVE
    legal-steal observation. Returning True here would spend retries on
    a condition the policy calls immediately fatal and would let a
    missing-diagnostic regression hide behind the attempt bound, so it
    fails CLOSED.
    """
    if not gap_report:
        return False
    for entry in gap_report:
        gaps = entry.get("gaps") or {}
        # An entry with no named gap explains nothing. The caller only
        # builds entries for non-empty gaps, so this is a guard against
        # a malformed/incomplete report, not a normal shape.
        if not gaps:
            return False
        rows = entry["rows"] or []
        by_node = {r[0]: r for r in rows}
        for node in gaps:
            row = by_node.get(node)
            if row is None:
                return False
            (_n, rc, w, r, sf, ch, ct, _te) = row
            if not (rc == 0 and w == 1 and r == 1 and sf == 1
                    and ch >= 2 and ct == ch):
                return False
    return True


class TestLivenessGate(unittest.TestCase):
    """The gate must reject an all-zero node, or it proves nothing."""

    def test_all_zero_rows_are_rejected(self):
        rows = [(0, 0, 0, 0, 1, 0, 0, 1),
                (1, 0, 0, 0, 1, 0, 0, 1)]
        gaps = _row_activity_gaps(rows, 2)
        self.assertEqual(set(gaps), {0, 1})
        self.assertTrue(any("write_idx=0" in g for g in gaps[1]))

    def test_eof_marker_only_node_is_rejected(self):
        """The exact shape a single-real-node run produces.

        Node 1's single published/claimed slot is the ingest's synthetic
        EOF marker. It reports the same counters as "one real chunk",
        which is why the gate needs the >= 2 floors; otherwise this run
        reaches the collision assertion with no explanation.
        """
        rows = [(0, 0, 172, 172, 1, 86, 86, 1),
                (1, 0, 1, 1, 1, 1, 1, 1)]
        gaps = _row_activity_gaps(rows, 2)
        self.assertEqual(set(gaps), {1})
        self.assertTrue(any("write_idx=1" in g for g in gaps[1]))
        self.assertTrue(any("chunk_head=1" in g for g in gaps[1]))

    def test_two_real_chunks_on_both_nodes_is_accepted(self):
        rows = [(0, 0, 88, 88, 1, 4, 4, 1),
                (1, 0, 63, 63, 1, 3, 3, 1)]
        self.assertEqual(_row_activity_gaps(rows, 2), {})

    def test_benign_read_overshoot_is_accepted(self):
        rows = [(0, 0, 172, 173, 1, 86, 86, 0),
                (1, 0, 63, 63, 1, 3, 3, 0)]
        self.assertEqual(_row_activity_gaps(rows, 2), {},
                         "read > write is the documented benign straggler "
                         "overshoot and must not be treated as missing "
                         "drain")

    def test_unclaimed_publication_is_rejected(self):
        rows = [(0, 0, 172, 171, 1, 86, 86, 0),
                (1, 0, 63, 63, 1, 3, 3, 0)]
        gaps = _row_activity_gaps(rows, 2)
        self.assertIn(0, gaps)
        self.assertTrue(any("unclaimed published" in g for g in gaps[0]))

    def test_scanner_stealing_is_classified_retryable(self):
        """The exact CI shape: node 1 received 3 chunks, published EOF.

        Node 0's starved scanner claimed all three of node 1's chunks
        (legal distance-charged stealing), so node 1's own scanner
        published only its EOF marker. The ingest still routed real work
        to node 1, which distinguishes this from the UMA fallback the
        gate exists to reject.
        """
        rows = [(0, 0, 150, 150, 1, 4, 4, 1),
                (1, 0, 1, 1, 1, 3, 3, 1)]
        gaps = _row_activity_gaps(rows, 2)
        self.assertIn(1, gaps)
        self.assertTrue(
            _steal_explains_gaps([{"rows": rows, "gaps": gaps}]),
            "the CI row shape is legal scanner stealing and must be "
            "retryable, not reported as a UMA fallback")

    def test_eof_marker_only_node_is_not_retryable(self):
        """A node that never received a real chunk is the UMA fallback."""
        rows = [(0, 0, 172, 172, 1, 86, 86, 1),
                (1, 0, 1, 1, 1, 1, 1, 1)]
        gaps = _row_activity_gaps(rows, 2)
        self.assertFalse(
            _steal_explains_gaps([{"rows": rows, "gaps": gaps}]),
            "retrying this shape would hide the single-node fallback "
            "the liveness gate exists to catch")

    def test_partially_consumed_queue_is_not_retryable(self):
        """A scanner that stops with chunks queued is a failure, not a
        steal: stealing leaves the victim's queue fully consumed."""
        rows = [(0, 0, 150, 150, 1, 4, 4, 1),
                (1, 0, 1, 1, 1, 3, 2, 1)]
        gaps = _row_activity_gaps(rows, 2)
        self.assertFalse(
            _steal_explains_gaps([{"rows": rows, "gaps": gaps}]))

    def test_unfinished_scanner_is_not_retryable(self):
        """A scanner that never published its final ring state failed."""
        rows = [(0, 0, 150, 150, 1, 4, 4, 1),
                (1, 0, 1, 1, 0, 3, 3, 1)]
        gaps = _row_activity_gaps(rows, 2)
        self.assertIn(1, gaps)
        self.assertFalse(
            _steal_explains_gaps([{"rows": rows, "gaps": gaps}]))

    def test_unclaimed_eof_is_not_retryable(self):
        """write_idx=read_idx=1 is part of the signature; an unclaimed
        EOF slot is a drain failure, not a steal."""
        rows = [(0, 0, 150, 150, 1, 4, 4, 1),
                (1, 0, 1, 0, 1, 3, 3, 1)]
        gaps = _row_activity_gaps(rows, 2)
        self.assertIn(1, gaps)
        self.assertFalse(
            _steal_explains_gaps([{"rows": rows, "gaps": gaps}]))

    def test_probe_failure_is_not_retryable(self):
        """A failed diagnostic probe proves nothing about stealing."""
        rows = [(0, 0, 150, 150, 1, 4, 4, 1),
                (1, -1, -1, -1, -1, -1, -1, -1)]
        gaps = _row_activity_gaps(rows, 2)
        self.assertIn(1, gaps)
        self.assertFalse(
            _steal_explains_gaps([{"rows": rows, "gaps": gaps}]))

    def test_empty_gap_report_is_not_retryable(self):
        """No observation at all is not an observation of stealing.

        The classifier used `all()`-style semantics over the report, so
        an empty report vacuously passed. That spends retries on a
        condition the policy calls immediately fatal and would let a
        missing-diagnostic regression hide behind the attempt bound.
        """
        self.assertFalse(
            _steal_explains_gaps([]),
            "an empty gap report was classified as legal stealing")
        self.assertFalse(
            _steal_explains_gaps([{"rows": [], "gaps": {}}]),
            "an audit entry that names no gap was classified as legal "
            "stealing")

    def test_missing_audits_are_not_retryable(self):
        """A run with no audit records has no evidence to explain a gap."""
        active, gap_report = _liveness_state([], 2)
        self.assertEqual(active, set())
        self.assertEqual(gap_report, [])
        self.assertFalse(
            _steal_explains_gaps(gap_report),
            "a missing audit was classified as legal stealing")

    def test_missing_node_row_is_not_retryable(self):
        """A report that omits a node cannot prove that node was stolen."""
        rows = [(0, 0, 150, 150, 1, 4, 4, 1)]     # node 1 row missing
        gaps = _row_activity_gaps(rows, 2)
        self.assertIn(1, gaps)
        self.assertFalse(
            _steal_explains_gaps([{"rows": rows, "gaps": gaps}]),
            "an absent node row was classified as legal stealing")

    def test_mixed_gap_report_is_not_retryable(self):
        """One legal steal does not excuse an unrelated failure."""
        legal = [(0, 0, 150, 150, 1, 4, 4, 1),
                 (1, 0, 1, 1, 1, 3, 3, 1)]          # legal-steal victim
        broken = [(0, 0, 150, 150, 1, 4, 4, 1),
                  (1, 0, 1, 1, 0, 3, 3, 1)]         # unfinished scanner
        self.assertTrue(
            _steal_explains_gaps(
                [{"rows": legal, "gaps": _row_activity_gaps(legal, 2)}]),
            "the legal-steal fixture is no longer recognised")
        gap_report = [
            {"rows": legal, "gaps": _row_activity_gaps(legal, 2)},
            {"rows": broken, "gaps": _row_activity_gaps(broken, 2)},
        ]
        self.assertFalse(
            _steal_explains_gaps(gap_report),
            "a mixed report was accepted because one entry looked legal")


class TestNumaOrderingIdentity(unittest.TestCase):
    """Ordering identity under logical multi-node NUMA."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="numa-identity-")
        cls.spec = _plugin(cls._tmp)
        cls.corpus = os.path.join(cls._tmp, "in.txt")
        with open(cls.corpus, "w") as fh:
            for i in range(N_LINES):
                fh.write(LINE_FMT % i)
        with open(cls.corpus, "rb") as fh:
            cls.want = fh.read()
        cls.want_lines = cls.want.splitlines(keepends=True)
        # 5,400,000 bytes over 600,000 lines. A regular file makes the
        # ingest take the per-node alternating path described in the
        # module docstring.
        if not len(cls.want) > 3 * 1024 * 1024:
            raise AssertionError(
                "corpus must span multiple scanner chunks, got %d bytes"
                % len(cls.want))
        cls.prev_cleanroom = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "0"     # in-process NUMA path
        cls.addClassCleanup(cls._restore_cleanroom)

    @classmethod
    def _restore_cleanroom(cls):
        if cls.prev_cleanroom is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = cls.prev_cleanroom

    def _map(self, *, lines, nodes, order, workers):
        """Run map, capturing records and the live per-node diagnostics.

        All patches are restored in `finally`, including when the run
        raises.
        """
        frames = []
        audits = []
        real_iter = _RUN._iter_records
        real_audit = _RUN._numa_drain_audit

        def spy_iter(lib, fd, _chunk=None, views=False):
            for rec in real_iter(lib, fd, views=views):
                frames.append(tuple(rec))
                yield rec

        def spy_audit(lib, num_nodes, forked, wid_node, *a, **k):
            out = real_audit(lib, num_nodes, forked, wid_node, *a, **k)
            # The audit runs while the ring state is live (a probe after
            # map() returns reads zeros), so per-node liveness is probed
            # HERE -- inside the audit's window, not after the fact.
            diag = getattr(lib, "fr_py_diag_node", None)
            rows = []
            if diag is not None and num_nodes:
                for node in range(int(num_nodes)):
                    arr = (ctypes.c_uint64 * 6)()
                    try:
                        rc = int(diag(node, arr))
                    except Exception:
                        rc = -1
                    if rc == 0:
                        rows.append((node, rc) + tuple(int(x) for x in arr))
                    else:
                        rows.append((node, rc) + (-1,) * 6)
            audits.append({"num_nodes": num_nodes, "rows": rows})
            return out

        try:
            _RUN._iter_records = spy_iter
            _RUN._numa_drain_audit = spy_audit
            out = forkrun.map(self.spec, self.corpus, mode="plugin",
                              workers=workers, lines=lines, nodes=nodes,
                              order=order)
        finally:
            _RUN._iter_records = real_iter
            _RUN._numa_drain_audit = real_audit
        return out, frames, audits

    def _map_live(self, *, lines, nodes, order, workers,
                  num_nodes, require_all=False):
        """Run `_map` until the liveness gate holds.

        Scanner-side chunk stealing is LEGAL load balancing
        (`forkrun_ring.c`: a starved scanner may claim from a peer's
        chunk queue). When a peer takes ALL of a node's chunks, that
        node's own scanner publishes only its EOF marker, so the
        per-node rows look like a single-real-node run even though the
        ingest DID route real work there. The ordering claims this
        class makes are only meaningful on a run where both nodes
        published, so retry -- but ONLY that shape.

        A node that never received a real chunk (`chunk_head <= 1`) is
        the UMA fallback the gate exists to reject, and a node whose
        queue was not fully consumed is a scanner failure. Neither is
        retried: `_assert_two_logical_nodes_live` reports them
        immediately with the standard per-node diagnostics.

        Neither is a MISSING audit: a run that produced no per-node
        observation at all has no legal-steal evidence, so it fails
        immediately too (`_steal_explains_gaps` fails closed on an
        empty report). Absence of evidence is not an explanation.

        The gate itself is not relaxed. Every attempt is judged by the
        same `_row_activity_gaps`, and the returned run is one that
        passed it. Exhausting the attempts fails with every attempt's
        rows, so a systematic single-node regression cannot pass.
        """
        attempts = []
        for attempt in range(1, _MAP_LIVE_ATTEMPTS + 1):
            out, frames, audits = self._map(
                lines=lines, nodes=nodes, order=order, workers=workers)
            # Completeness is a precondition on EVERY attempt, not just
            # the accepted one. A retry must never discard a run that
            # lost records and then pass because a later run happened to
            # be complete: lost output is a failure regardless of which
            # node scanned the chunk.
            self._assert_output_complete(
                out, "attempt %d lines=%d" % (attempt, lines))
            active, gap_report = _liveness_state(audits, num_nodes)
            if _liveness_ok(active, num_nodes, require_all):
                return out, frames, audits
            if not _steal_explains_gaps(gap_report):
                # Not the legal stealing shape: report it as the
                # precondition failure it is, with the standard message.
                self._assert_two_logical_nodes_live(
                    audits, num_nodes, require_all)
            attempts.append({"attempt": attempt,
                             "gap_report": gap_report})
        self.fail(
            "the @%d fixture did not produce %s live node(s) in %d "
            "attempts; every failed attempt was scanner-side chunk "
            "stealing (legal load balancing), so the per-node ordering "
            "behaviour was never exercised. Attempts:\n%s"
            % (num_nodes,
               "both" if require_all else "at least 2",
               _MAP_LIVE_ATTEMPTS,
               "\n".join("attempt %d:\n%s"
                         % (a["attempt"], _format_gaps(a["gap_report"]))
                         for a in attempts)))

    def _assert_two_logical_nodes_live(self, audits, num_nodes,
                                       require_all=False):
        """A3 gate: no UMA fallback may make these tests pass.

        Every run must report REAL activity on at least two logical
        nodes. `rc==0` from fr_py_diag_node is not enough: it is
        returned for a node whose counters are all zero. The complete
        per-node rows are printed on failure, and the missing activity
        is named explicitly.

        `require_all=True` (the @2 fixture) demands both nodes: with
        only two nodes, "at least two" and "both" are the same
        requirement, and naming it makes a one-node run unambiguous.
        """
        active, gap_report = _liveness_state(audits, num_nodes)
        needed = _liveness_threshold(num_nodes, require_all)
        self.assertGreaterEqual(
            len(active), needed,
            "fewer than %d logical node(s) did real work -- the run "
            "cannot prove the per-node claim/ordering behaviour it is "
            "asserted to prove. Missing activity:\n%s\nfull audits:\n%r"
            % (needed, _format_gaps(gap_report), audits))
        if require_all:
            self.assertEqual(
                active, set(range(int(num_nodes))),
                "the @2 fixture must exercise BOTH nodes; missing "
                "activity:\n%s\nfull audits:\n%r"
                % (_format_gaps(gap_report), audits))

    def _assert_output_complete(self, out, where):
        """Exact record multiset BEFORE any ordering assertion.

        `order="none"` promises no input order, so a byte-for-byte
        comparison against the ordered input would be wrong. Compare
        what completeness actually means: byte count, record count, and
        the full multiset with duplicate multiplicity.
        """
        got = b"".join(bytes(r) for r in out)
        self.assertEqual(
            len(got), len(self.want),
            "%s: output byte count %d != input %d"
            % (where, len(got), len(self.want)))
        got_lines = got.splitlines(keepends=True)
        self.assertEqual(
            len(got_lines), N_LINES,
            "%s: output record count %d != input %d"
            % (where, len(got_lines), N_LINES))
        if Counter(got_lines) != Counter(self.want_lines):
            missing = Counter(self.want_lines) - Counter(got_lines)
            extra = Counter(got_lines) - Counter(self.want_lines)
            self.fail(
                "%s: output record multiset differs from the input "
                "(missing %d distinct, extra %d distinct); first "
                "missing=%r first extra=%r"
                % (where, len(missing), len(extra),
                   next(iter(missing), None), next(iter(extra), None)))

    def test_logical_nodes_are_live(self):
        """@2 and @4 must actually engage >=2 active nodes, per run.

        @2 uses one worker per node so a node's own claims cannot be
        taken by another node's worker. @4 keeps 8 workers and only
        requires >=2 of four active nodes (with one CPU per logical
        node on a small runner, demanding all four would be a
        topology claim, not an ordering claim).

        A run whose liveness was lost to legal scanner-side chunk
        stealing is retried by `_map_live`; the run this test accepts
        must still pass the gate, and a systematic single-node fallback
        still fails after the last attempt.
        """
        for lines in LINES_GRANULARITIES:
            _out, _frames, audits = self._map_live(
                lines=lines, nodes="@2", order="none",
                workers=WORKERS_2_NODES, num_nodes=2, require_all=True)
            self._assert_two_logical_nodes_live(
                audits, num_nodes=2, require_all=True)
        for lines in LINES_GRANULARITIES:
            _out, _frames, audits = self._map_live(
                lines=lines, nodes="@4", order="none", workers=8,
                num_nodes=4)
            self._assert_two_logical_nodes_live(audits, num_nodes=4)

    def test_batch_idx_is_not_globally_unique(self):
        """The source conclusion, confirmed empirically.

        With both nodes claiming from their own rings, batch_idx values
        MUST collide. A run where they do not has not exercised the
        multi-node claim path and proves nothing about ordering. The
        liveness gate runs first, so a run whose data all landed on one
        node is reported as a failed PRECONDITION with per-node rows --
        not as a mysterious absence of collisions. Output completeness
        is then established, so lost records are reported as lost
        records rather than as an ordering-precondition failure.
        """
        for lines in LINES_GRANULARITIES:
            out, frames, audits = self._map_live(
                lines=lines, nodes="@2", order="none",
                workers=WORKERS_2_NODES, num_nodes=2, require_all=True)
            self._assert_two_logical_nodes_live(
                audits, num_nodes=2, require_all=True)
            self._assert_output_complete(out, "collision lines=%d" % lines)
            idxs = [i for (i, _p) in frames]
            self.assertGreater(
                len(idxs) - len(set(idxs)), 0,
                "no batch_idx collisions on this run despite both nodes "
                "passing the liveness gate: the corpus did not engage "
                "both nodes' claim counters, so this run cannot "
                "distinguish global from per-node tickets. frames=%d "
                "distinct=%d" % (len(idxs), len(set(idxs))))

    def test_orderer_path_is_byte_exact(self):
        """Production ordering: the C orderer's (major, minor) key."""
        for lines in LINES_GRANULARITIES:
            out, _frames, audits = self._map_live(
                lines=lines, nodes="@2", order="index",
                workers=WORKERS_2_NODES, num_nodes=2, require_all=True)
            self._assert_two_logical_nodes_live(
                audits, num_nodes=2, require_all=True)
            got = b"".join(bytes(r) for r in out)
            self.assertTrue(
                got == self.want,
                "orderer path is not byte-exact at lines=%d: first "
                "difference at byte %s"
                % (lines, next((i for i, (a, b) in
                                enumerate(zip(got, self.want)) if a != b),
                               "len %d vs %d" % (len(got),
                                                 len(self.want)))))

    def test_batch_idx_sort_is_wrong_under_numa(self):
        """The hazard, pinned so it cannot be re-adopted as a shortcut.

        collect_records() sorts by batch_idx when the orderer is
        unavailable. Source says that key is per-node; this proves the
        consequence -- wrong order -- rather than leaving it as a
        comment that a green small-input run would appear to refute.
        """
        real_v1a = _bindings.v1_available

        def no_orderer(lib=None, _r=real_v1a):
            d0 = dict(_r())
            d0["orderer"] = None
            return d0

        # Restored in a finally, NOT addClassCleanup: the stub must not
        # outlive this test, because the cleanup would fire at class
        # teardown and leave the stub installed for every LATER test in
        # this class -- including the production-orderer test, which
        # would then run orderer-less and fail for a reason that has
        # nothing to do with what it tests.
        try:
            _bindings.v1_available = no_orderer
            for lines in LINES_GRANULARITIES:
                out, _frames, audits = self._map_live(
                    lines=lines, nodes="@2", order="index",
                    workers=WORKERS_2_NODES, num_nodes=2, require_all=True)
                self._assert_two_logical_nodes_live(
                    audits, num_nodes=2, require_all=True)
                got = b"".join(bytes(r) for r in out)
                self.assertNotEqual(
                    got, self.want,
                    "sorting by batch_idx produced input order under @2 "
                    "-- this run did not exercise the cross-node "
                    "collision the source analysis predicts, so this "
                    "hazard case is no longer demonstrated")
        finally:
            _bindings.v1_available = real_v1a

    def test_map_live_fails_after_bounded_steal_attempts(self):
        """A steal-only fixture must fail after the bound, not loop.

        The retry tolerates a legal scheduling outcome on a FIXTURE
        run; it must not turn a systematic single-node regression into
        an eventual success. Feed the exact legal-steal shape on every
        attempt and assert that the helper stops at the bound and keeps
        every attempt's diagnostic rows.
        """
        steal_audit = {"num_nodes": 2,
                       "rows": [(0, 0, 150, 150, 1, 4, 4, 1),
                                (1, 0, 1, 1, 1, 3, 3, 1)]}
        calls = []

        def always_steal(**_kw):
            calls.append(_kw)
            return list(self.want_lines), [], [steal_audit]

        real_map = self._map
        try:
            self._map = always_steal
            with self.assertRaises(AssertionError) as cm:
                self._map_live(
                    lines=4096, nodes="@2", order="none",
                    workers=WORKERS_2_NODES, num_nodes=2,
                    require_all=True)
        finally:
            self._map = real_map

        self.assertEqual(
            len(calls), _MAP_LIVE_ATTEMPTS,
            "the retry bound was not honoured: %d attempts" % len(calls))
        msg = str(cm.exception)
        self.assertIn("scanner-side chunk stealing", msg)
        for attempt in range(1, _MAP_LIVE_ATTEMPTS + 1):
            self.assertIn("attempt %d:" % attempt, msg,
                          "attempt %d's diagnostics were not retained"
                          % attempt)

    def test_map_live_never_retries_an_incomplete_attempt(self):
        """A run that lost records fails at once, not on a later retry.

        The retry exists only for a complete run whose node liveness
        was lost to legal stealing. Discarding an incomplete run would
        let a data-loss defect hide behind a later, complete attempt.
        """
        steal_audit = {"num_nodes": 2,
                       "rows": [(0, 0, 150, 150, 1, 4, 4, 1),
                                (1, 0, 1, 1, 1, 3, 3, 1)]}
        calls = []

        def incomplete(**_kw):
            calls.append(_kw)
            return list(self.want_lines[:-1]), [], [steal_audit]

        real_map = self._map
        try:
            self._map = incomplete
            with self.assertRaises(AssertionError) as cm:
                self._map_live(
                    lines=4096, nodes="@2", order="none",
                    workers=WORKERS_2_NODES, num_nodes=2,
                    require_all=True)
        finally:
            self._map = real_map

        self.assertEqual(len(calls), 1,
                         "an incomplete attempt was retried")
        self.assertIn("attempt 1 lines=4096", str(cm.exception))

    def test_map_live_never_retries_a_missing_audit(self):
        """A complete run with no audit observation fails at once.

        The retry is for a POSITIVE legal-steal observation. `_map_live`
        must not read a missing audit as "nothing to report, therefore
        fine": with no per-node rows there is no evidence that any node
        did work, so it is a precondition failure on the first attempt.
        """
        calls = []

        def no_audit(**_kw):
            calls.append(_kw)
            return list(self.want_lines), [], []

        real_map = self._map
        try:
            self._map = no_audit
            with self.assertRaises(AssertionError) as cm:
                self._map_live(
                    lines=4096, nodes="@2", order="none",
                    workers=WORKERS_2_NODES, num_nodes=2,
                    require_all=True)
        finally:
            self._map = real_map

        self.assertEqual(
            len(calls), 1,
            "a run with no audit observations was retried; missing "
            "evidence must fail closed")
        self.assertIn("fewer than 2 logical node(s) did real work",
                      str(cm.exception))


def _format_gaps(gap_report):
    if not gap_report:
        return "  (no gaps reported)"
    lines = []
    for entry in gap_report:
        lines.append("  rows=%r" % (entry["rows"],))
        for node in sorted(entry["gaps"]):
            lines.append("  node %d: %s"
                         % (node, "; ".join(entry["gaps"][node])))
    return "\n".join(lines)


if __name__ == "__main__":
    unittest.main()
