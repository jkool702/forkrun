"""W-DEDUP R-D8: shim ABI gate (signatures only, not semantics).

Single source: python/forkrun/_shim.c. Generated artifacts:
forkrun_shim.h + tools/generated/shim_signatures.json (via
tools/gen_shim.py; CI runs --check). This test diffs the live
substrate + _bindings.py against the committed signature table —
the practical equivalent of typechecking the Python/C boundary.

Scope guard: arity + name + linkage + export presence only. Semantic
contracts (which entry clears worker_last_cnt, 5-on-fatal) belong to
test_invariant_gate.py §3/§6/§9, never here.
"""

import ctypes
import json
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SIG_JSON = os.path.join(REPO_ROOT, "tools", "generated",
                        "shim_signatures.json")
SHIM_H = os.path.join(REPO_ROOT, "forkrun_shim.h")
SHIM_C = os.path.join(REPO_ROOT, "python", "forkrun", "_shim.c")

from forkrun._bindings import find_substrate  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _load_table():
    with open(SIG_JSON) as fh:
        return json.load(fh)


def _c_arity(args_s):
    args_s = args_s.strip()
    if args_s == "void" or args_s == "":
        return 0
    # Top-level commas only (no nested parens in this ABI).
    return args_s.count(",") + 1


class TestShimArtifactsFresh(unittest.TestCase):
    """Committed header + JSON match regeneration (mirrors CI --check)."""

    def test_gen_shim_check(self):
        rc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "tools",
                                          "gen_shim.py"), "--check"],
            capture_output=True, text=True, cwd=REPO_ROOT).returncode
        self.assertEqual(rc, 0,
                         "gen_shim.py --check failed (regenerate: "
                         "python3 tools/gen_shim.py)")

    def test_header_lists_all_externs(self):
        table = _load_table()
        with open(SHIM_H) as fh:
            hdr = fh.read()
        for name, ent in table.items():
            if ent["linkage"] != "extern":
                continue
            self.assertIn(name, hdr,
                          "extern %s missing from forkrun_shim.h" % name)
        for name, ent in table.items():
            if ent["linkage"] == "extern":
                continue
            # Static internals must NOT be in the ABI header.
            self.assertNotRegex(
                hdr, r"\b%s\s*\(" % re.escape(name),
                "static %s leaked into forkrun_shim.h" % name)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestShimExports(unittest.TestCase):
    """Every extern is exported by the .so; no extra fr_py_* exports."""

    def test_exports_match_table(self):
        table = _load_table()
        externs = sorted(k for k, v in table.items()
                         if v["linkage"] == "extern")
        lib_path = find_substrate()
        out = subprocess.run(
            ["nm", "-D", "--defined-only", lib_path],
            capture_output=True, text=True).stdout
        exported = sorted(set(re.findall(r"\b(fr_py_\w+)", out)))
        self.assertEqual(exported, externs,
                         "export drift: extra=%s missing=%s"
                         % (sorted(set(exported) - set(externs)),
                            sorted(set(externs) - set(exported))))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestShimBindings(unittest.TestCase):
    """_bindings.py covers every extern with matching arity."""

    def test_bindings_cover_externs(self):
        import forkrun._bindings as _b

        table = _load_table()
        lib = ctypes.CDLL(find_substrate())
        _b._setup_signatures(lib)
        missing = []
        arity_mismatch = []
        for name, ent in table.items():
            if ent["linkage"] != "extern":
                continue
            fn = getattr(lib, name, None)
            if fn is None:
                missing.append(name)
                continue
            # ctypes argtypes must exist and match C arity.
            try:
                n_ctypes = len(fn.argtypes or [])
            except AttributeError:
                n_ctypes = None
            n_c = _c_arity(ent["args"])
            # void-arg C functions bind as [] (0).
            if n_ctypes is not None and n_ctypes != n_c:
                arity_mismatch.append((name, n_c, n_ctypes))
        self.assertEqual(missing, [],
                         "externs missing from loaded lib: %s" % missing)
        self.assertEqual(arity_mismatch, [],
                         "arity drift (C vs ctypes): %s"
                         % arity_mismatch)

    def test_no_order_regression(self):
        # Reordering is an ABI change: source order in the JSON must be
        # stable (insertion-ordered dict from parse order).
        table = _load_table()
        names = list(table.keys())
        self.assertEqual(len(names), len(set(names)), "duplicate entries")
        # 50 extern + 11 static = 61 (guard against silent truncation).
        # 50 rather than 49 because fr_py_poison_relay was added (the
        # cleanroom's poisoned-batch-index relay).
        # W-PREFLIGHT added fr_py_ingest_data_post: an advisory
        # "more bytes landed in ingress" poke on evfd_ingest_data, so
        # the pre-flight scan can block on the eventfd instead of
        # spin-sleeping. It deliberately does NOT touch
        # state[0].ingest_complete -- that is the scanner's EOF gate and
        # must only be set on a genuine drain (see the W-GATE2 postmortem
        # in MEMORY.md, which lost records by trusting it). Additive: no
        # existing signature changed, no struct layout changed, nothing
        # removed.
        # W-PYFORKGATE added fr_py_backlog_node: a read-only,
        # non-destructive per-node backlog accessor. It is additive — no
        # existing signature changed, no struct layout changed, and
        # nothing was removed — so the ABI stays backward compatible for
        # already-built consumers. The reason it could not be done in
        # Python: fr_py_data_ready_node is consume-once (it walks
        # write_idx forward from a private hwm), so the fork gate cannot
        # read a LEVEL with it. Behavior delta is confined to the NUMA
        # fork gate's fork timing; see the gate loop in run.py.
        n_ext = sum(1 for v in table.values()
                    if v["linkage"] == "extern")
        n_st = sum(1 for v in table.values()
                   if v["linkage"] == "static")
        # 50->52 extern, 11->13 static (P1-3, 2026-10-11):
        #   extern  fr_py_udf_bind        launcher binds the helper's
        #                                 fr_udf_call/fr_udf_free so the
        #                                 shim never links libpython.
        #   extern  fr_py_worker_udf_loop the fifth execution-mode loop.
        #                                 Same signature as the plugin
        #                                 loop, so spawn_wid is unchanged.
        #   static  fr_py_emit_record_buf frames an in-memory payload with
        #                                 an EXPLICIT disposition. Needed
        #                                 because fr_py_emit_record infers
        #                                 NO_RESULT from src_len == 0,
        #                                 which would collapse None and
        #                                 b"" -- the exact conflation
        #                                 DECISION-02 removes.
        #   static  fr_py_udf_invoke     the UDF invoke body.
        #   extern  fr_py_emit_disposition SKIPPED/POISONED terminal
        #                                 records (P5). Exported rather
        #                                 than static so the exactly-once
        #                                 proof exercises the REAL
        #                                 emitter; a test that re-wrote
        #                                 the record would skip the
        #                                 frontier advance and pass while
        #                                 the shipped path leaked a
        #                                 duplicate on every retry.
        #                                 records (P5). Zero payload --
        #                                 an empty DATA record would make
        #                                 poison indistinguishable from a
        #                                 UDF returning b"".
        # Behavior delta: this one is NOT purely additive in effect.
        # fr_py_emit_disposition adds two new records to the stream --
        # a POISONED record per poison-skipped batch and a SKIPPED record
        # per on_error=skip batch, in all four worker loops. Readers
        # already filtered every non-DATA disposition, so no caller sees
        # them as results; what changes is that a terminal outcome now
        # has a representation on the wire instead of being inferred from
        # a counter. No existing symbol changed arity or signature.
        # static additions: fr_py_signal_write (factored out of
        # fr_py_emit so the disposition emitter can announce its record),
        # fr_py_maybe_die_before_ack (the shared fault-injection
        # hook, so every worker loop is injectable and not just the UDF
        # one), and fr_py_maybe_die_after_signal (fault injection in the
        # interval the before-ack hook structurally cannot reach --
        # after a DATA record is written AND signalled, before the ack).
        # Inert unless the env var is set; it exists to expose the
        # pre-existing publication/commit defect documented in
        # dev/supervisor/CLEANROOM_EXPANSION_PROPOSAL.md section 0a,
        # which is otherwise untestable because a DATA record is never
        # signalled before the before-ack hook fires. Extern count is
        # unchanged at 53: no dlsym-visible entry was added or changed,
        # so this is a fault-injection-only addition.
        #
        # C0.7 extern (54 -> 55): fr_py_committed_data_frames(node, *out).
        # Read-only snapshot of COMMITTED DATA frames per node, for the
        # ordered completeness certificate. Purely additive: a NEW entry
        # point, no existing symbol changed arity or signature.
        #
        #   extern  fr_py_committed_data_frames C0.7 committed-DATA
        #                                 snapshot. Deliberately its own
        #                                 entry point rather than a 7th
        #                                 value on fr_py_diag_node:
        #                                 existing callers allocate
        #                                 exactly six, so widening that
        #                                 array would overrun their
        #                                 buffers. Returns the DATA-only
        #                                 count, NOT the generic
        #                                 complete-frame statistic, which
        #                                 includes non-DATA dispositions
        #                                 the parent filters -- the two
        #                                 are not interchangeable.
        #
        # Behavior delta: read-only and inert until a caller opts in.
        # A missing symbol on an older substrate is treated by callers as
        # "certificate unavailable", never as a pass, so the new entry
        # point cannot make an uncovered run look certified. Nothing is
        # written by this symbol; the counter it reads is maintained by
        # the commit flush in fr_py_ack_core.
        #
        # W-EXP-2 Phase A extern (55 -> 56): fr_py_c07_counting_enabled().
        # The companion to fr_py_committed_data_frames, and it exists
        # because that counter is NOT self-describing. With
        # FORKRUN_C07_COUNT=0 nothing increments, so the counter reads
        # zero -- indistinguishable, from outside, from a run that
        # genuinely committed no DATA frames. The cleanroom launcher
        # would then sum 0 against the records it actually collected and
        # the completeness certificate would fail every COMPLETE run. A
        # caller can only avoid that by asking whether the counter is
        # live, so the launcher dlsyms this and reports "unavailable"
        # rather than a fabricated zero. No existing symbol changed
        # arity or signature.
        #
        #   extern  fr_py_c07_counting_enabled  Whether the committed-DATA
        #                                 counter is live in this process.
        #                                 Read-only and inert; consults
        #                                 the same fr_c07_enabled() gate
        #                                 that decides whether commits are
        #                                 counted at all. Its absence on
        #                                 an older substrate is treated as
        #                                 "unavailable", which is
        #                                 fail-OPEN into "no verdict" --
        #                                 never into a pass.
        #
        # Behavior delta: none on any existing path. Nothing calls this
        # symbol except the cleanroom launcher, which treats "no symbol",
        # "symbol says disabled", and "symbol says enabled" as three
        # distinct cases and only certifies in the third.
        #
        # W-EXP-2 step C adds ONE extern:
        #
        #   extern  fr_py_worker_plugin_loop_numa
        #                                 The plugin loop with an explicit
        #                                 logical node id. It is the same
        #                                 loop body; fr_py_worker_init
        #                                 already accepted node_id and the
        #                                 Python paths already supply it,
        #                                 so this only exposes an existing
        #                                 operation to the exec-based
        #                                 launcher. fr_py_worker_plugin_loop
        #                                 is unchanged. No existing symbol
        #                                 changed signature.
        #
        #   extern  fr_py_worker_bind_node
        #                                 Bind the logical node the next
        #                                 fr_py_worker_init call will use.
        #                                 It exists so the multi-node
        #                                 launcher can select a ring
        #                                 WITHOUT a second copy of the
        #                                 worker loop body: the parity
        #                                 test requires the three worker
        #                                 modes to share one lifecycle, and
        #                                 a duplicated body would be a
        #                                 fourth place for a fix to miss.
        #                                 Inert (-1) unless called.
        #
        #   extern  fr_py_node_index_complete
        #                                 Whether this NODE's indexer has
        #                                 consumed every chunk published
        #                                 for it, and the global ingest
        #                                 EOF is posted (so no further
        #                                 chunk can arrive). The global
        #                                 marker alone is NOT a per-node
        #                                 completion signal: it says the
        #                                 source was consumed, not that
        #                                 this node's work is done.
        #                                 Read-only. 1 complete, 0 not,
        #                                 -1 no verdict.
        #
        #   extern  fr_py_node_scan_complete
        #                                 Whether this NODE's scanner
        #                                 finished publishing its final
        #                                 ring state (scanner_finished,
        #                                 published after the final
        #                                 write_idx and before the EOF
        #                                 evfd blast). Read-only. Same
        #                                 1/0/-1 convention.
        # W-PY31 (aec0161c): static fr_py_claim_wait_poll (the idle
        # worker's data/escrow/EOF wait, mirroring do_lockfree_claim's
        # own wait set) is internal -- it is called only from
        # fr_py_claim in this translation unit and is never dlsym'd.
        # The extern surface is therefore unchanged (60) and the
        # static surface grows 16 -> 17. No existing signature and no
        # struct layout changed.
        # W-PY31 waiter accounting (this change): TWO read-only extern
        # probes, so the recovery tests can observe the same state the
        # shim decides from rather than inferring it from timing:
        #   fr_py_active_waiters(node)  the scanner-facing gauge
        #   fr_py_worker_probe(wid,out) (txn phase, txn node, this wid's
        #                               shim waiter registration word)
        # Both are inert diagnostics: no library caller, nothing
        # written, no existing signature or struct layout changed.
        # Extern 60 -> 62; static stays 17.
        self.assertEqual((n_ext, n_st), (62, 17),
                         "ABI surface changed (extern=%d static=%d) — "
                         "if intentional, regenerate + justify in the "
                         "behavior-delta audit" % (n_ext, n_st))


if __name__ == "__main__":
    unittest.main()
