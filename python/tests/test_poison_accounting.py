"""Poison accounting must not differ between supported configurations.

WO-PY-REL-1 / TD-09.

`last_run_stats()` documents five keys. `poisoned_batches` used to be
populated on the reactor path and on both cleanroom paths but come back
EMPTY on `orchestrator=False`, beside a correct non-zero `poisoned`.

That asymmetry is now CLOSED, and this module is the regression matrix for
the corrected contract. The previous version of this file pinned the gap
as a "known gap"; its own docstring said what to do when the gap closed:

    "If this assertion ever starts failing because the gap was closed,
     delete it and extend the test above to cover orchestrator=False --
     do not just relax it."

That is what happened, and this is that rewrite.

DETERMINISM
-----------
Identity assertions use `workers=1` with `lines=1`, so batch i is exactly
record i. Batch boundaries otherwise depend on ingest timing, and this
codebase has already been bitten by counting blobs instead of records
(test_c07 correspondence) -- so identity is pinned here, never inferred.

FIXTURES
--------
A test-local plugin is compiled at setUpClass, following the pattern
test_cleanroom_routes.py already uses. It fails a batch IFF the batch
contains "BOOM", which gives SELECTIVE poisoning: a chosen SUBSET of
batches fails and the rest succeed.

That matters, because an all-or-nothing fixture cannot distinguish
"reported every poisoned index" from "reported every index it saw". With
BOOM at records 2 and 5 of 8, the only correct answer is exactly [2, 5].

The in-repo fixtures were not usable here: count_lines_v1 and
always_fail_v1 are all-or-nothing, and die_once_v1 kills the worker,
which raises ForkrunWorkerFailure rather than poisoning a batch.

GATE
----
FORKRUN_CLEANROOM is pinned to 0 in setUpClass. map(plugin) has been
default-ON since WO-CR-ROI-2, so without this these tests would silently
exercise the CLEANROOM route (which already reported indices) instead of
the in-process plain route -- the very path TD-09 is about. The cleanroom
route's own coverage lives in test_cleanroom.py.

THE CONTRACT, asserted everywhere below:
  * `poisoned` is the EXACT count;
  * `poisoned_batches` holds those indices, sorted and deduplicated;
  * `poisoned_batches_truncated` is True whenever the list cannot
    represent every poisoned batch, so a truncated list never reads as
    complete.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import warnings

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun                                            # noqa: E402
from forkrun.run import last_run_stats                    # noqa: E402
# `forkrun.run` the ATTRIBUTE is the frontend function (re-exported in
# forkrun/__init__.py), which shadows the submodule of the same name, so
# reach the module object through sys.modules for patching.
_run_mod = sys.modules["forkrun.run"]                    # noqa: E402

# -I takes the DIRECTORY; passing the header path makes gcc warn
# "not a directory" and then fail to find the include.
PLUGIN_INC = os.path.join(_ROOT, "ring_loadables")
PLUGIN_HEADER = os.path.join(PLUGIN_INC, "forkrun_plugin.h")

PLUGIN_SRC = r'''
#include "forkrun_plugin.h"
#include <stdio.h>
#include <string.h>

/* Dialect 2 + RAW window delivery. Without this the shim tokenizes and
   ctx->reserved[0] is NULL, which fails EVERY batch. */
int forkrun_use_ctx = FORKRUN_CTX_ENABLE | FORKRUN_CTX_FLAG_RAW;

/* Fails only batches containing "BOOM" -> selective poisoning. */
int selective_v1(int argc, char **argv, const struct forkrun_ctx *ctx) {
    const char *in; uint64_t n;
    (void)argc; (void)argv;
    if (ctx == NULL || ctx->version < 2) return -1;
    n = ctx->batch_byte_length;
    if (n == 0) return 0;
    in = (const char *)(uintptr_t)ctx->reserved[0];
    if (in == NULL) return -1;
    if (memmem(in, (size_t)n, "BOOM", 4) != NULL) return -1;
    if (fwrite(in, 1, (size_t)n, stdout) != (size_t)n) return -2;
    return fflush(stdout) == 0 ? 0 : -2;
}
'''

HAVE_GCC = shutil.which("gcc") is not None


def _write_corpus(path, n, boom=frozenset()):
    with open(path, "w") as fh:
        for i in range(n):
            fh.write("BOOM\n" if i in boom else "line%05d\n" % i)


class _PoisonBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAVE_GCC:
            raise unittest.SkipTest(
                "gcc absent; the selective-poison plugin cannot be built")
        cls._tmp = tempfile.mkdtemp(prefix="poison-rel-")
        cls.so = os.path.join(cls._tmp, "sel.so")
        proc = subprocess.run(
            ["gcc", "-shared", "-fPIC", "-O2", "-I", PLUGIN_INC,
             "-o", cls.so, "-x", "c", "-"],
            input=PLUGIN_SRC, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            shutil.rmtree(cls._tmp, ignore_errors=True)
            raise unittest.SkipTest("plugin fixture build failed: %s"
                                    % proc.stderr[-300:])
        cls.spec = "%s:selective_v1" % cls.so

    def setUp(self):
        for name in ("FORKRUN_CLEANROOM", "FORKRUN_RETRY_LIMIT",
                     "FRK_POISON_FD"):
            self.addCleanup(self._restore, name, os.environ.get(name))
            os.environ.pop(name, None)
        # In-process routes only; see GATE in the module docstring.
        os.environ["FORKRUN_CLEANROOM"] = "0"
        # 1 == poisoned on the first failure: deterministic, and it does
        # NOT poison successful batches (limit=0 does, oddly -- every
        # batch poisons even when the payload succeeds, which made an
        # earlier draft of this file assert nonsense).
        os.environ["FORKRUN_RETRY_LIMIT"] = "1"
        self.tmp = tempfile.mkdtemp(prefix="poison-case-")

    @staticmethod
    def _restore(name, value):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def tearDown(self):
        # The relay's fd number is process-global; a leaked one is worse
        # than an absent one, so the export is CHECKED, not assumed.
        self.assertNotIn(
            "FRK_POISON_FD", os.environ,
            "FRK_POISON_FD leaked out of a run; a stale fd number would "
            "make a later run relay into whatever now occupies it")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def corpus(self, n, boom=frozenset()):
        p = os.path.join(self.tmp, "c%d_%d.txt" % (n, len(boom)))
        _write_corpus(p, n, boom)
        return p

    def run_map(self, src, *, boom_orch=True, **kw):
        kw.setdefault("workers", 1)
        kw.setdefault("lines", 1)
        kw.setdefault("on_error", "retry")
        kw.setdefault("mode", "plugin")
        out, stats = forkrun.map(self.spec, src, output="bytes",
                                 return_stats=True, **kw)
        return out, stats, last_run_stats()

    def assertContractHolds(self, stats, label):
        poisoned = stats["poisoned"]
        idxs = stats["poisoned_batches"]
        trunc = stats["poisoned_batches_truncated"]

        self.assertEqual(idxs, sorted(set(idxs)),
                         "%s: indices must be sorted and deduplicated, "
                         "got %r" % (label, idxs))
        if trunc:
            self.assertLess(
                len(idxs), poisoned,
                "%s: a TRUNCATED list must be shorter than the count; "
                "otherwise the flag calls an incomplete list complete"
                % label)
        else:
            self.assertEqual(
                len(idxs), poisoned,
                "%s: a COMPLETE list has one index per poisoned batch "
                "(poisoned=%d, got %r)" % (label, poisoned, idxs))
        for i in idxs:
            self.assertIsInstance(i, int)
            self.assertGreaterEqual(i, 0, "batch indices are never negative")


# --------------------------------------------------------------------------
# C1 -- plain path: the TD-09 regression itself
# --------------------------------------------------------------------------
class TestPlainPathIndices(_PoisonBase):
    def test_plain_path_reports_the_exact_indices(self):
        """orchestrator=False must list exactly what it counts.

        This is the assertion TD-09 made impossible. A non-zero poison
        count beside an empty list is a FAILURE here, not a documented
        gap. BOOM sits at records 2 and 5 of 8, so [2, 5] is the only
        correct answer -- not "all of them".
        """
        src = self.corpus(8, boom={2, 5})
        out, stats, last = self.run_map(src, orchestrator=False)
        self.assertGreater(stats["poisoned"], 0,
                           "fixture must actually poison, or this proves "
                           "nothing")
        self.assertContractHolds(stats, "orchestrator=False")
        self.assertEqual(stats["poisoned"], 2)
        self.assertEqual(stats["poisoned_batches"], [2, 5],
                         "batch i == record i under lines=1, and only "
                         "records 2 and 5 carry BOOM")
        self.assertFalse(stats["poisoned_batches_truncated"])
        self.assertEqual(last["poisoned_batches"], stats["poisoned_batches"])

    def test_plain_path_lists_every_poisoned_batch(self):
        """All-poisoned variant: indices must be exactly 0..n-1.

        Expected list derived from the FIXTURE (every record is BOOM), not
        from the scalar count -- restating the count would prove nothing.
        """
        n = 6
        src = self.corpus(n, boom=set(range(n)))
        out, stats, _ = self.run_map(src, orchestrator=False)
        self.assertEqual(stats["poisoned"], n)
        self.assertEqual(stats["poisoned_batches"], list(range(n)))
        self.assertFalse(stats["poisoned_batches_truncated"])

    def test_plain_path_c_plugin_loop_reports_the_same_indices(self):
        """The C plugin loop is a DIFFERENT worker loop.

        It reaches the relay through fr_py_worker_plugin_loop rather than
        the Python worker, and it builds its own scrub keep-set. A fix
        threaded into only one loop passes every other test here and is
        still broken for this one -- so it gets its own assertion.
        """
        src = self.corpus(8, boom={2, 5})
        out, stats, _ = self.run_map(src, orchestrator=False,
                                     c_worker_loop=True)
        self.assertEqual(stats["poisoned_batches"], [2, 5],
                         "the C plugin loop must relay indices too")
        self.assertEqual(stats["poisoned"], 2)

    def test_plain_path_spawn_loop_reports_indices(self):
        """The spawn loop is a THIRD worker loop, with its own keep-set.

        /bin/false fails every batch, so all indices must appear. Added
        because the spawn keep-set mutation went undetected until this
        existed -- three loops, three keep-sets, and only two were covered.
        """
        src = self.corpus(5, boom=set())
        out, stats = forkrun.map(
            ["/bin/false"], src, workers=1, lines=1, mode="spawn",
            on_error="retry", output="bytes", return_stats=True,
            orchestrator=False, c_spawn_loop=True)
        self.assertGreater(stats["poisoned"], 0)
        self.assertContractHolds(stats, "spawn loop")
        self.assertEqual(stats["poisoned_batches"],
                         list(range(stats["poisoned"])))

    def test_both_worker_loops_agree(self):
        """Explicit cross-loop parity, so neither can drift alone."""
        src = self.corpus(8, boom={2, 5})
        _, py_loop, _ = self.run_map(src, orchestrator=False,
                                     c_worker_loop=False)
        _, c_loop, _ = self.run_map(src, orchestrator=False,
                                    c_worker_loop=True)
        self.assertEqual(py_loop["poisoned_batches"],
                         c_loop["poisoned_batches"])
        self.assertEqual(py_loop["poisoned"], c_loop["poisoned"])


# --------------------------------------------------------------------------
# C2 -- reactor path (retained and strengthened)
# --------------------------------------------------------------------------
class TestReactorPathIndices(_PoisonBase):
    def test_reactor_path_contract(self):
        src = self.corpus(8, boom={2, 5})
        out, stats, last = self.run_map(src, orchestrator=True)
        self.assertContractHolds(stats, "orchestrator=True")
        self.assertEqual(stats["poisoned_batches"], [2, 5])
        self.assertFalse(stats["poisoned_batches_truncated"])
        self.assertEqual(last["poisoned_batches"], stats["poisoned_batches"])

    def test_indices_sorted_and_deduplicated(self):
        n = 12
        src = self.corpus(n, boom=set(range(n)))
        out, stats, _ = self.run_map(src, orchestrator=True)
        idxs = stats["poisoned_batches"]
        self.assertEqual(idxs, sorted(set(idxs)))
        self.assertEqual(idxs, list(range(n)))


# --------------------------------------------------------------------------
# C3 -- cross-path agreement
# --------------------------------------------------------------------------
class TestCrossPathParity(_PoisonBase):
    def test_scalars_and_indices_agree_across_paths(self):
        src = self.corpus(8, boom={2, 5})
        _, plain, plain_last = self.run_map(src, orchestrator=False)
        _, reac, reac_last = self.run_map(src, orchestrator=True)

        self.assertEqual(plain["poisoned"], reac["poisoned"],
                         "the PORTABLE field must agree; total derives "
                         "from it, so divergence corrupts the headline")
        self.assertEqual(plain["total"], reac["total"])
        self.assertEqual(plain["completed"], reac["completed"])
        self.assertEqual(plain["poisoned_batches"], reac["poisoned_batches"],
                         "TD-09: the index lists must agree too")
        self.assertEqual(plain["poisoned_batches_truncated"],
                         reac["poisoned_batches_truncated"])
        self.assertEqual(plain_last["poisoned_batches"],
                         plain["poisoned_batches"])
        self.assertEqual(reac_last["poisoned_batches"],
                         reac["poisoned_batches"])

    def test_zero_poison_reports_empty_and_not_truncated(self):
        """The other direction: a fixed implementation must not invent
        indices for a run that poisoned nothing."""
        src = self.corpus(8, boom=set())
        for orch in (False, True):
            with self.subTest(orchestrator=orch):
                out, stats, _ = self.run_map(src, orchestrator=orch)
                self.assertEqual(stats["poisoned"], 0)
                self.assertEqual(stats["poisoned_batches"], [])
                self.assertFalse(stats["poisoned_batches_truncated"])
                self.assertEqual(stats["completed"], 8)

    def test_counts_do_not_leak_between_calls(self):
        """Two calls in one process: the second must not inherit the
        first's indices. _reset_stats() runs per map() call, so this is
        a regression guard on that, not on the relay."""
        a = self.corpus(8, boom={2, 5})
        b = self.corpus(8, boom={1})
        self.run_map(a, orchestrator=False)
        _, second, _ = self.run_map(b, orchestrator=False)
        self.assertEqual(second["poisoned_batches"], [1],
                         "a later call must not inherit earlier indices")


# --------------------------------------------------------------------------
# C4 -- bounded list, truthful truncation
# --------------------------------------------------------------------------
class TestTruncation(_PoisonBase):
    def _all_poisoned(self, n):
        return self.corpus(n, boom=set(range(n)))

    def test_bounded_slot_truncates_truthfully(self):
        """More poisons than one slot holds.

        Capacity is _STATS_CAPACITY (1024) indices PER WORKER, so this
        needs >1024 poisoned batches on one worker. Kept out of the cheap
        cases because it emits that many poison WARN lines.

        The per-worker limit is why workers=1: with several workers each
        has its own slot and the aggregate could exceed capacity without
        any single slot being full.
        """
        from forkrun.run import _STATS_CAPACITY
        n = _STATS_CAPACITY + 76
        src = self._all_poisoned(n)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out, stats, _ = self.run_map(src, orchestrator=False)
        self.assertEqual(
            stats["poisoned"], n,
            "the scalar stays EXACT even when the list cannot hold every "
            "index")
        self.assertTrue(
            stats["poisoned_batches_truncated"],
            "%d poisons exceed the %d-index slot, so the list cannot be "
            "complete" % (n, _STATS_CAPACITY))
        self.assertLessEqual(len(stats["poisoned_batches"]),
                             _STATS_CAPACITY,
                             "the list must stay BOUNDED by the slot")
        # A PREFIX, not the whole set: the slot held exactly its capacity
        # and the overflow was dropped. Asserting range(n) here would
        # contradict the truncation this test exists to observe.
        self.assertEqual(stats["poisoned_batches"],
                         list(range(_STATS_CAPACITY)))
        self.assertContractHolds(stats, "truncated plain path")
        self.assertTrue(
            [w for w in caught if "poisoned_batches is TRUNCATED"
             in str(w.message)],
            "a truncated list must be announced, or callers cannot trust "
            "len() without reading the flag")

    def test_completeness_is_never_claimed_while_truncated(self):
        """The exact failure mode this contract exists to prevent."""
        from forkrun.run import _STATS_CAPACITY
        n = _STATS_CAPACITY + 5
        src = self._all_poisoned(n)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out, stats, _ = self.run_map(src, orchestrator=False)
        self.assertEqual(len(stats["poisoned_batches"]), _STATS_CAPACITY)
        self.assertNotEqual(
            len(stats["poisoned_batches"]), stats["poisoned"],
            "len() must not equal the count while truncated, or a caller "
            "cannot tell an incomplete list from a complete one")
        self.assertTrue(stats["poisoned_batches_truncated"])


# --------------------------------------------------------------------------
# C2b -- streaming plain path
# --------------------------------------------------------------------------
class TestStreamingPlainPath(_PoisonBase):
    """stream() on the plain path, for BOTH generator executors.

    Added after a mutation proved the coverage was missing: altering the
    poisoned COUNT on this path turned no test red, because the streaming
    executors were wired but never asserted. Wiring without asserting is
    how an unverified change looks like a verified one.

    TD-09b (fixed here) was two independent defects, one per generator
    executor, both invisible to the assertions that existed at the time:

    * `_execute_ingest_stream` (streaming=True) read the engine poison
      count in the poison summary, which runs AFTER the branch `finally`
      calls `_teardown_stream()` -> `fr_py_destroy()`. Once `g_state` is
      NULL, `fr_py_poisoned_count()` returns 0, so `report_poison` never
      reached `_raise_for_poisoned()` and the scalar stayed 0 while the
      relay-backed index list was correct. Whether the engine was still
      alive at summary time was a RACE: identical runs were observed
      reporting 0 and 2.
    * `_execute_streaming` (streaming=False) looked its relay channel up
      with `globals().get("_poison_ch")`, but `_poison_ch` is a LOCAL of
      the forking scope, so the lookup always yielded None. Index
      collection silently no-oped and published an EMPTY
      `poisoned_batches` next to a correct non-zero scalar -- the exact
      inverse skew, from the same missing assertions.

    Both executors are asserted on both fields, and both must agree with
    the reactor.
    """

    def _stream(self, src, orchestrator, streaming=True):
        # stream() does NOT reset the stats stash (only map() does, by
        # design -- a stream leaves the previous completed/total), so a
        # previous run's poisoned_batches can survive into this one.
        # Poison a DISTINCT index first: that makes any value observed
        # after the stream attributable to the stream itself, and it is
        # what makes a silently-skipped index collection observable
        # rather than masked by a stale identical list.
        self.run_map(self.corpus(8, boom={7}))
        gen = forkrun.stream(
            self.spec, src, mode="plugin", workers=1, lines=1,
            streaming=streaming, on_error="retry", output="bytes",
            order="none", orchestrator=orchestrator)
        try:
            out = list(gen)
        finally:
            try:
                gen.close()
            except Exception:
                pass
        return out, last_run_stats()

    def _assert_both_fields(self, stats, where):
        """Scalar and index list must describe the SAME poison events."""
        self.assertEqual(stats["poisoned"], 2,
                         "%s: poisoned scalar must be the true count" % where)
        self.assertEqual(stats["poisoned_batches"], [2, 5],
                         "%s: index list must match the scalar" % where)
        self.assertFalse(stats["poisoned_batches_truncated"],
                         "%s: a 2-batch run must never report truncation"
                         % where)

    def test_streaming_plain_path_reports_the_exact_indices(self):
        src = self.corpus(8, boom={2, 5})
        out, stats = self._stream(src, orchestrator=False)
        self.assertEqual(stats["poisoned_batches"], [2, 5],
                         "the streaming plain path must relay indices too")
        self.assertFalse(stats["poisoned_batches_truncated"])
        self.assertEqual(len(out), 6, "the non-poisoned records still flow")

    def test_materialized_ingest_plain_path_reports_both_fields(self):
        """streaming=False exercises _execute_streaming, the second
        generator executor. TD-09b's index half landed here."""
        src = self.corpus(8, boom={2, 5})
        _, stats = self._stream(src, orchestrator=False, streaming=False)
        self._assert_both_fields(stats, "_execute_streaming")

    def test_streaming_ingest_plain_path_reports_both_fields(self):
        """streaming=True exercises _execute_ingest_stream, where
        TD-09b's scalar half landed."""
        src = self.corpus(8, boom={2, 5})
        _, stats = self._stream(src, orchestrator=False, streaming=True)
        self._assert_both_fields(stats, "_execute_ingest_stream")

    def test_no_empty_index_list_next_to_a_nonzero_scalar(self):
        """The exact shape of the _execute_streaming bug: scalar right,
        list silently empty. Asserted directly so a regression cannot be
        reintroduced by making the relay quietly no-op."""
        src = self.corpus(8, boom={2, 5})
        for streaming in (False, True):
            _, stats = self._stream(src, orchestrator=False,
                                   streaming=streaming)
            self.assertTrue(stats["poisoned_batches"],
                            "streaming=%s: a nonzero poisoned count must "
                            "never publish an empty index list" % streaming)

    def test_streaming_index_lists_agree_across_paths(self):
        src = self.corpus(8, boom={2, 5})
        _, plain = self._stream(src, orchestrator=False)
        _, reac = self._stream(src, orchestrator=True)
        self.assertEqual(plain["poisoned_batches"],
                         reac["poisoned_batches"],
                         "TD-09 applies to stream() exactly as it does to "
                         "map(); the lists must agree")

    def test_both_generators_agree_with_reactor_on_both_fields(self):
        """Cross-check every generator executor against the reactor, on
        the scalar as well as the list."""
        src = self.corpus(8, boom={2, 5})
        _, reac = self._stream(src, orchestrator=True)
        for streaming in (False, True):
            _, plain = self._stream(src, orchestrator=False,
                                    streaming=streaming)
            self.assertEqual(plain["poisoned"], reac["poisoned"],
                             "streaming=%s: scalar must match the reactor"
                             % streaming)
            self.assertEqual(plain["poisoned_batches"],
                             reac["poisoned_batches"],
                             "streaming=%s: indices must match the reactor"
                             % streaming)

    def test_scalar_survives_a_post_teardown_engine_read(self):
        """The ordering guarantee, asserted directly.

        On the GENERATOR paths the poison summary runs after teardown, so
        a live `fr_py_poisoned_count()` there can legitimately return 0
        (its `if (!g_state) return 0` guard once fr_py_destroy() has run).
        The scalar must therefore come from the count stashed BEFORE
        teardown, and must not collapse to whatever the post-teardown
        read happens to say.

        Simulated here rather than raced for: whether the engine is still
        alive at summary time is timing-dependent, so the unpremeditated
        version of this test passed or failed by luck -- which is exactly
        why the stash exists. Forcing the post-teardown read to 0 makes
        the assertion deterministic in both directions.
        """
        src = self.corpus(8, boom={2, 5})
        def dead_engine_read(lib):
            # Mimic fr_py_poisoned_count() after fr_py_destroy(): g_state
            # is NULL, so the accessor returns 0.
            return 0

        for streaming in (False, True):
            with unittest.mock.patch.object(_run_mod, "_read_poison_count",
                                            dead_engine_read):
                _, stats = self._stream(src, orchestrator=False,
                                        streaming=streaming)
            self.assertEqual(
                stats["poisoned"], 2,
                "streaming=%s: a post-teardown engine read must not "
                "overwrite the pre-teardown stashed count" % streaming)
            self.assertEqual(stats["poisoned_batches"], [2, 5],
                             "streaming=%s: indices still come from the "
                             "relay and must be unaffected" % streaming)


# --------------------------------------------------------------------------
# C5 -- failure-policy boundaries
# --------------------------------------------------------------------------
class TestFailurePolicies(_PoisonBase):
    def test_on_error_skip_keeps_the_three_fields_consistent(self):
        """skip is a different failure contract from retry.

        Documented distinction: under skip a batch is skipped, so it can
        appear in NEITHER completed nor poisoned, and the count need NOT
        match retry. What must hold is that the poison fields stay
        internally consistent. Parity is not invented here.
        """
        src = self.corpus(8, boom={2, 5})
        for orch in (False, True):
            with self.subTest(orchestrator=orch):
                out, stats, _ = self.run_map(src, orchestrator=orch,
                                             on_error="skip")
                self.assertContractHolds(stats, "skip orchestrator=%s" % orch)

    def test_strict_poison_raises_and_leaves_stats_inspectable(self):
        """C5+C6 intersection.

        The index list is collected BEFORE report_poison(), precisely so
        a strict_poison raise does not lose it. Moving collection after the
        summary -- the obvious-looking order -- fails this test.
        """
        src = self.corpus(4, boom={1})
        for orch in (False, True):
            with self.subTest(orchestrator=orch):
                with self.assertRaises(Exception):
                    forkrun.map(self.spec, src, workers=1, lines=1,
                                mode="plugin", on_error="retry",
                                strict_poison=True, output="bytes",
                                orchestrator=orch)
                last = last_run_stats()
                self.assertGreater(
                    last["poisoned"], 0,
                    "the scalar must survive the strict_poison raise")
                self.assertEqual(
                    last["poisoned_batches"], [1],
                    "poisoned_batches must survive the raise too; "
                    "collection must happen BEFORE report_poison()")


# --------------------------------------------------------------------------
# C6 -- both public stats surfaces
# --------------------------------------------------------------------------
class TestStatsSurfaces(_PoisonBase):
    def test_return_stats_and_last_run_stats_agree(self):
        src = self.corpus(8, boom={2, 5})
        for orch in (False, True):
            with self.subTest(orchestrator=orch):
                out, stats, last = self.run_map(src, orchestrator=orch)
                for key in ("total", "completed", "poisoned",
                            "poisoned_batches",
                            "poisoned_batches_truncated"):
                    self.assertEqual(
                        stats[key], last[key],
                        "return_stats and last_run_stats must agree on %r "
                        "for the most recent completed call" % key)


if __name__ == "__main__":
    unittest.main(verbosity=2)