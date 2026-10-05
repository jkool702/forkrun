# W-CR1: cleanroom (exec-based launcher) integration tests.
#
# The lesson that shaped this file: an earlier smoke test asserted only
# that both flag settings produced the same totals -- which they did,
# because the hook was DEAD CODE and both runs took the in-process path.
# So the first test here proves the launcher actually EXECUTES, by
# recording the execv call, before anything asserts on output.
import os
import sys
import glob
import shutil
import signal
import struct
import tempfile
import threading
import time
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forkrun  # noqa: E402
from forkrun.run import (  # noqa: E402
    _cleanroom_eligible, _cleanroom_enabled, _cleanroom_explicit,
    _cleanroom_launcher_path)

PLUGIN = None
for _cand in (
        os.environ.get("FORKRUN_TEST_PLUGIN"),
        "/tmp/opencode/mlbench/ml_plugin_light.so",
):
    if _cand and os.path.exists(_cand):
        PLUGIN = _cand
        break
HAVE_PLUGIN = PLUGIN is not None


def _spec():
    return "%s:ml_process_light" % PLUGIN


def _make_input(n=2000, path=None):
    import tempfile
    if path is None:
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
    with open(path, "w") as fh:
        for i in range(n):
            fh.write('{"eid":"e%d","uid":1,"iid":2,"ts":1700000000,'
                     '"et":"view","dev":"ios","dur":5}\n' % i)
    return path


def _joined(res):
    return b"".join(bytes(x) for x in res)


def _find_launcher():
    """pid of the live cleanroom launcher among our children."""
    for d in glob.glob("/proc/self/task/*/children"):
        try:
            pids = [int(x) for x in open(d).read().split()]
        except OSError:
            continue
        for p in pids:
            try:
                with open("/proc/%d/comm" % p, "rb") as fh:
                    # /proc/pid/comm is capped at 15 chars (TASK_COMM_LEN),
                    # so "_forkrun_cleanroom" never matches in full.
                    if fh.read().startswith(b"_forkrun"):
                        return p
            except OSError:
                pass
    return None


def _descendants_of(pid):
    """Every descendant pid of `pid`, via /proc children files."""
    out = set()
    stack = [pid]
    while stack:
        cur = stack.pop()
        for d in glob.glob("/proc/%d/task/*/children" % cur):
            try:
                kids = [int(x) for x in open(d).read().split()]
            except OSError:
                continue
            for k in kids:
                if k not in out:
                    out.add(k)
                    stack.append(k)
    return out


class TestCleanroomHelpers(unittest.TestCase):
    """The envelope predicate -- pure, no plugin or launcher needed."""

    def test_disabled_by_default(self):
        # The default is OFF. It was briefly ON (5ae0b0a0) and reversed:
        # the envelope excludes orchestrator=True, which is map()'s own
        # default, so a plain map() never took the cleanroom anyway --
        # and the launcher runs no supervisor, so defaulting it ON would
        # have meant defaulting crash recovery OFF for every caller who
        # did not ask for it.
        old = os.environ.pop("FORKRUN_CLEANROOM", None)
        try:
            self.assertFalse(_cleanroom_enabled())
            self.assertFalse(_cleanroom_explicit())
        finally:
            if old is not None:
                os.environ["FORKRUN_CLEANROOM"] = old

    def test_explicit_opt_out_disables(self):
        old = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "0"
        try:
            self.assertFalse(_cleanroom_enabled())
            self.assertFalse(_cleanroom_explicit())
        finally:
            if old is None:
                os.environ.pop("FORKRUN_CLEANROOM", None)
            else:
                os.environ["FORKRUN_CLEANROOM"] = old

    def test_explicit_request_is_flagged(self):
        old = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        try:
            self.assertTrue(_cleanroom_enabled())
            self.assertTrue(_cleanroom_explicit())
        finally:
            if old is None:
                os.environ.pop("FORKRUN_CLEANROOM", None)
            else:
                os.environ["FORKRUN_CLEANROOM"] = old

    def test_truthy_and_falsey_spellings(self):
        old = os.environ.get("FORKRUN_CLEANROOM")
        try:
            for v in ("1", "yes", "on", "TRUE", " true "):
                os.environ["FORKRUN_CLEANROOM"] = v
                self.assertTrue(_cleanroom_enabled(), v)
            for v in ("0", "", "no", "off", "false"):
                os.environ["FORKRUN_CLEANROOM"] = v
                self.assertFalse(_cleanroom_enabled(), v)
        finally:
            if old is None:
                os.environ.pop("FORKRUN_CLEANROOM", None)
            else:
                os.environ["FORKRUN_CLEANROOM"] = old

    def test_envelope_accepts_only_what_it_can_honour(self):
        p = _make_input(10)
        self.addCleanup(lambda: os.path.exists(p) and os.unlink(p))
        ok, _ = _cleanroom_eligible(p, "plugin", 1, "none", False, False)
        self.assertTrue(ok)
        # W-CR4 gave the launcher a supervisor and the ordering is
        # applied downstream, so these three are now served and must be
        # ACCEPTED. They used to be in the reject list; leaving them
        # there would keep the gate lying about what the launcher does.
        for args in (
                (p, "plugin", 1, "index", False, False),  # ordered map
                (p, "plugin", 1, "index", False, True),   # + orchestrator
                (p, "plugin", 1, "none", False, True),    # orchestrator
                (p, "plugin", 1, "none", True, False),    # strict_poison
                (p, "plugin", 1, "none", True, True),     # both counters
        ):
            ok, why = _cleanroom_eligible(*args)
            self.assertTrue(ok, "should now accept %r (%s)" % (args, why))
        # Each of these would change RESULTS, not just speed.
        for args in (
                (p, "python", 1, "none", False, False),   # no plugin
                (p, "plugin", 4, "none", False, False),   # multi-node
                (p, "plugin", 1, "hash", False, False),   # unknown order
                ("/no/such/file", "plugin", 1, "none", False, False),
        ):
            ok, why = _cleanroom_eligible(*args)
            self.assertFalse(ok, "should reject %r" % (args,))
            self.assertTrue(why)


@unittest.skipUnless(HAVE_PLUGIN, "test plugin not available")
class TestCleanroomExecutes(unittest.TestCase):
    """Prove the launcher is REALLY taken, then that it is correct."""

    def setUp(self):
        self._old = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.path = _make_input(2000)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass
        if self._old is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._old

    def _run_marked(self, **kw):
        """Run map() with the cleanroom entry point instrumented.

        The marker is recorded in the PARENT, before any fork. An
        earlier version of this probe spied on os.execv and wrote a
        marker file from inside the forked child -- which HANGS THE
        SUITE: fork()ing a multi-threaded process and then doing Python
        work in the child is the documented deadlock hazard (the same
        one Python 3.12+ warns about at every os.fork() site in
        run.py). Nothing in a forked child may touch Python here.

        A parent-side marker is also the RIGHT assertion: the defect
        this file exists to catch was a hook that never fired, which a
        parent-side marker detects exactly, and which an exec-status
        check alone would not.
        """
        # NB: sys.modules, NOT `import forkrun.run as R` -- the package
        # re-exports a function named `run`, so attribute access on the
        # imported name lands on the function, not this module.
        R = sys.modules["forkrun.run"]
        real = R._execute_cleanroom
        seen = []

        def spy(*a, **k):
            seen.append(True)
            return real(*a, **k)

        R._execute_cleanroom = spy
        self.addCleanup(setattr, R, "_execute_cleanroom", real)
        out = forkrun.map(_spec(), self.path, workers=2, nodes=1,
                          mode="plugin", output="bytes", **kw)
        return out, bool(seen)

    def test_cleanroom_path_is_actually_taken(self):
        """The load-bearing test: FORKRUN_CLEANROOM=1 must REACH the
        launcher. A hook that never fires is invisible to every other
        assertion in this file -- an earlier version asserted only that
        both flag settings produced identical totals, which they did
        because both took the in-process path.
        """
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        out, taken = self._run_marked(orchestrator=False)
        self.assertTrue(
            taken,
            "FORKRUN_CLEANROOM=1 never reached the launcher -- the hook "
            "is dead code and this whole file would prove nothing")
        self.assertEqual(len(_joined(out)), 2000)

    def test_matches_in_process_content(self):
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        cr, _ = self._run_marked(orchestrator=False)
        old = os.environ["FORKRUN_CLEANROOM"]
        os.environ["FORKRUN_CLEANROOM"] = "0"
        try:
            ref = forkrun.map(_spec(), self.path, workers=2, nodes=1,
                              mode="plugin", output="bytes",
                              orchestrator=False)
        finally:
            os.environ["FORKRUN_CLEANROOM"] = old
        # Batch boundaries may differ (the launcher spills and scans in
        # its own process); the delivered BYTES must not.
        self.assertEqual(_joined(cr), _joined(ref))
        self.assertEqual(len(_joined(cr)), 2000)

    def test_empty_input_yields_empty_result(self):
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        empty = _make_input(0, path=self.path + ".empty")
        self.addCleanup(lambda: os.path.exists(empty) and os.unlink(empty))
        out = forkrun.map(_spec(), empty, workers=2, nodes=1,
                          mode="plugin", output="bytes",
                          orchestrator=False)
        self.assertEqual(len(out), 0)

    def test_outside_envelope_warns_and_stays_correct(self):
        """A call the launcher CANNOT serve must still warn, and still
        return right answers.

        The trigger has moved twice as the envelope grew: it was
        orchestrator=True (the default), then strict_poison, and is now
        multi-node. Each was the load-bearing exclusion at the time, and
        each was removed only when the launcher genuinely stopped losing
        information on that path. nodes=2 is still excluded -- the
        launcher builds one ring in one process and has no node-bound
        worker placement. The refusal path itself is what this guards:
        warning plus correct results, never silent wrong answers.
        """
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = forkrun.map(_spec(), self.path, workers=2, nodes=2,
                              mode="plugin", output="bytes")
        self.assertEqual(len(_joined(out)), 2000)
        self.assertTrue(
            any("FORKRUN_CLEANROOM" in str(w.message) for w in caught),
            "expected a loud warning, got %r"
            % [str(w.message) for w in caught])

    def test_order_index_takes_cleanroom_and_matches_in_process(self):
        """order="index" is served by the launcher, not refused.

        This test used to assert the opposite -- that order="index"
        warns and falls back. That was correct while the launcher had no
        ordering story at all, but it was over-narrow: the ordering is
        applied by SHARED downstream code (collect_records sorts by
        index; stream() reassembles parent-side from batch_idx), and the
        launcher already emits both keys in its batch framing. So no C
        orderer is needed in the launcher and the gate was refusing a
        case the launcher serves correctly.

        Asserted two ways, because the failure mode is silent:
          1. the launcher is ACTUALLY taken (otherwise a future
             regression re-falls-back and still passes), and
          2. the bytes equal the in-process ordered run -- parity, not
             "looks sorted". The in-process path is the oracle.
        """
        out, seen = self._run_marked(order="index", orchestrator=False)
        self.assertTrue(seen, "order='index' must take the launcher")

        os.environ["FORKRUN_CLEANROOM"] = "0"
        ref = forkrun.map(_spec(), self.path, workers=2, nodes=1,
                          mode="plugin", output="bytes",
                          order="index", orchestrator=False)
        os.environ["FORKRUN_CLEANROOM"] = "1"

        self.assertEqual(_joined(out), _joined(ref),
                         "cleanroom order='index' differs from in-process")
        self.assertEqual(len(_joined(out)), 2000)

    def test_orchestrator_true_takes_cleanroom_and_matches(self):
        """map()'s DEFAULT orchestrator=True is now served.

        orchestrator=True used to be the load-bearing rejection: the
        launcher had no supervisor, so a dead worker's batch was
        silently lost, and the default map() call could therefore not
        be accelerated at all. W-CR4 added the supervisor, so the
        default path can take the launcher. Death-recovery behaviour
        under orchestrator=True is covered in TestCleanroomWorkerDeath.
        """
        out, seen = self._run_marked(orchestrator=True)
        self.assertTrue(seen, "orchestrator=True must take the launcher")
        self.assertEqual(len(_joined(out)), 2000)

        os.environ["FORKRUN_CLEANROOM"] = "0"
        ref = forkrun.map(_spec(), self.path, workers=2, nodes=1,
                          mode="plugin", output="bytes")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.assertEqual(_joined(out), _joined(ref))

    def test_default_map_call_needs_no_kwargs(self):
        """A plain map() call -- all defaults -- must be eligible.

        Guards the interaction of the two flipped gates: orchestrator
        defaults True and order defaults "none", so if EITHER gate were
        still closed the default call would silently fall back and the
        acceleration would never be reachable in practice.
        """
        R = sys.modules["forkrun.run"]
        ok, why = R._cleanroom_eligible(self.path, "plugin", 1,
                                        "none", False, True)
        self.assertTrue(ok, "default map() must be eligible: %s" % (why,))


@unittest.skipUnless(HAVE_PLUGIN, "test plugin not available")
class TestCleanroomNonFileSources(unittest.TestCase):
    """map() over sources that are not a file on disk.

    The engine does not distinguish these: the spill child just read()s
    the descriptor into the input memfd until EOF, so a regular file, a
    fifo and a producer-fed pipe are the same shape by the time the
    scanner sees them. What differs is only how the descriptor is
    OBTAINED -- which is why this was wiring rather than a feature.

    The launcher resolves a source in a strict order: path/descriptor
    first, iterable second. That order is load-bearing, not stylistic:
    str and bytes both satisfy __iter__, so checking iterability first
    pumps a plain file path in one character at a time. That bug shipped
    briefly here and produced 1 byte of output where 2000 were expected,
    so test_iterable_source_is_not_mistaken_for_a_path guards it.
    """
    def setUp(self):
        self._old = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.path = _make_input(2000)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for p in (getattr(self, "path", None),):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        if self._old is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._old

    def _records(self, n=2000):
        return ['{"eid":"e%d","uid":1,"iid":2,"ts":1700000000,'
                '"et":"view","dev":"ios","dur":5}\n' % i for i in range(n)]

    def _fresh_pipe(self, records):
        """A NEW pipe fed by a live writer thread, for ONE run.

        A pipe is one-shot, so a parity check cannot hand the same
        descriptor to both paths -- each gets its own.

        The writer runs CONCURRENTLY and is joined only after the run
        drains it. Writing everything first and then joining deadlocks
        whenever the payload exceeds the pipe buffer (64 KiB by default):
        the writer blocks in write() forever because the only reader is
        the run that has not started yet. ~85 bytes per record means
        ~780 records is the ceiling, which is exactly the kind of hidden
        limit that makes a test mysteriously hang instead of failing.
        """
        r, w = os.pipe()

        def pump():
            try:
                os.write(w, "".join(records).encode())
            finally:
                os.close(w)

        th = threading.Thread(target=pump)
        th.start()
        self.addCleanup(th.join)
        return r

    def _agree(self, make_source, **kw):
        """Run both paths, each on its OWN source, and assert parity.

        `make_source` is called once per path precisely because the
        sources may be one-shot. Parity against the in-process path, not
        an expected byte count: a permuted or truncated corpus can still
        hit a plausible total.
        """
        R = sys.modules["forkrun.run"]
        real = R._execute_cleanroom
        seen = []
        R._execute_cleanroom = lambda *a, **k: (seen.append(1),
                                                real(*a, **k))[1]
        self.addCleanup(setattr, R, "_execute_cleanroom", real)

        os.environ["FORKRUN_CLEANROOM"] = "1"
        got = forkrun.map(_spec(), make_source(), workers=2, nodes=1,
                          mode="plugin", output="bytes", **kw)
        self.assertTrue(seen, "launcher was not taken for %r"
                             % (type(make_source()),))
        os.environ["FORKRUN_CLEANROOM"] = "0"
        ref = forkrun.map(_spec(), make_source(), workers=2, nodes=1,
                          mode="plugin", output="bytes", **kw)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.assertEqual(_joined(got), _joined(ref))
        return got

    def test_pipe_descriptor(self):
        out = self._agree(lambda: self._fresh_pipe(self._records(1000)))
        self.assertEqual(len(_joined(out)), 1000)

    def test_int_fd_of_a_file(self):
        out = self._agree(lambda: os.open(self.path, os.O_RDONLY))
        self.assertEqual(len(_joined(out)), 2000)

    def test_open_file_object(self):
        out = self._agree(lambda: open(self.path))
        self.assertEqual(len(_joined(out)), 2000)

    def test_path_still_works(self):
        out = self._agree(lambda: self.path)
        self.assertEqual(len(_joined(out)), 2000)

    def test_iterable_source_is_rejected_by_the_api(self):
        """map() must NOT accept a Python iterable -- the launcher has no
        producer branch, by design.

        _api._reject_iterable_source refuses iterables outright for
        map()/run() ("Python is never an input pump"), so the cleanroom
        never sees one. An earlier cut here forked a producer child for
        iterables; it was unreachable dead code, and an unreachable fork
        of a multi-threaded process is precisely the deadlock hazard the
        codebase warns about, so it was removed instead of kept "just in
        case". This pins that the API still refuses, so the removal stays
        honest.
        """
        for bad in (self._records(3), iter(self._records(3))):
            with self.assertRaises(TypeError):
                forkrun.map(_spec(), bad, workers=2, nodes=1,
                            mode="plugin", output="bytes")

    def test_iterable_is_not_mistaken_for_a_path(self):
        """Resolver ordering: path/descriptor BEFORE iterable.

        str and bytes both satisfy __iter__, so an iterable-first check
        sends a plain file path to a producer and emits it one character
        at a time. That bug shipped briefly here (1 byte of output where
        2000 were expected), so the ordering is pinned directly.
        """
        R = sys.modules["forkrun.run"]
        self.assertIsNone(
            R._cleanroom_map_source_fd(iter(self._records(3))),
            "a list iterator is not a descriptor")
        fd = R._cleanroom_map_source_fd(self.path)
        self.addCleanup(os.close, fd)
        self.assertIsInstance(fd, int)


@unittest.skipUnless(HAVE_PLUGIN, "test plugin not available")
class TestCleanroomFaultParity(unittest.TestCase):
    """W-CR1: the launcher's fault policy must match the in-process path.

    This is the gate for flipping the default ON. The launcher takes
    --on-error/--retry across the exec boundary, so retry/skip/fail-fast
    and FORKRUN_RETRY_LIMIT are TRANSPORTED rather than refused -- but
    transported is not the same as honoured, and only a comparison
    against the in-process path can show which.
    """

    V1_SO = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        "python", "tests", "plugins", "test_plugin_v1.so")

    def setUp(self):
        if not os.path.exists(self.V1_SO):
            self.skipTest("test_plugin_v1.so not built")
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        self._old_cr = os.environ.get("FORKRUN_CLEANROOM")
        self._old_rl = os.environ.get("FORKRUN_RETRY_LIMIT")
        self.path = _make_input(600)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for p in (self.path,):
            try:
                os.unlink(p)
            except OSError:
                pass
        for k, v in (("FORKRUN_CLEANROOM", self._old_cr),
                     ("FORKRUN_RETRY_LIMIT", self._old_rl)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _up(self):
        return self.V1_SO + ":process_v1"

    def _fail(self):
        return self.V1_SO + ":always_fail_v1"

    def _both(self, spec, **kw):
        """Run once per path. orchestrator=False pins the cleanroom
        inside its envelope so this compares FAULT POLICY, not topology
        or supervision."""
        kw.setdefault("nodes", 1)
        kw.setdefault("workers", 1)
        kw.setdefault("orchestrator", False)
        os.environ["FORKRUN_CLEANROOM"] = "0"
        a = forkrun.map(spec, self.path, mode="plugin", output="bytes", **kw)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        b = forkrun.map(spec, self.path, mode="plugin", output="bytes", **kw)
        return a, b

    def test_success_identical(self):
        a, b = self._both(self._up())
        self.assertEqual(_joined(a), _joined(b))
        self.assertGreater(len(_joined(a)), 0)

    def test_retry_then_poison_identical(self):
        # always_fail_v1 with the default retry limit: every batch is
        # retried then poisoned, so both paths must yield nothing.
        a, b = self._both(self._fail())
        self.assertEqual(a, [])
        self.assertEqual(b, [])
        self.assertEqual(_joined(a), _joined(b))

    def test_skip_identical(self):
        a, b = self._both(self._fail(), on_error="skip")
        self.assertEqual(_joined(a), _joined(b))
        self.assertEqual(a, [])

    def test_fail_fast_raises_both(self):
        for cr in ("0", "1"):
            os.environ["FORKRUN_CLEANROOM"] = cr
            with self.assertRaises(
                    RuntimeError, msg="cr=%s did not raise" % cr):
                forkrun.map(self._fail(), self.path, mode="plugin",
                            output="bytes", nodes=1, workers=1,
                            on_error="fail-fast", orchestrator=False)

    def test_return_stats_poison_counts_are_consistent(self):
        """return_stats now works on the cleanroom, and is self-consistent.

        This was a live P0: the cleanroom never populated
        _LAST_STATS["poisoned"], so _finish_map_stats computed
        completed = len(out) and total = completed + 0. A run of 100
        batches with 10 poisoned reported total=90 and poisoned=0 --
        silently wrong numbers from a call that looked entirely
        successful. The launcher now reports the count over a stats
        memfd.

        What is asserted is INTERNAL CONSISTENCY, not equality of counts
        against the in-process path. Batch count is timing-dependent: a
        batch's size depends on how much has spilled by the time a worker
        claims, so the same input legitimately yields 19 batches on one
        run and 29 on another. Pinning cross-path count equality made
        this test fail intermittently with poisoned=29 vs poisoned=19 --
        the same trap as the invocation-count comparisons in
        TestCleanroomProcessDeath. The invariants below hold regardless
        of how the input was chopped up.
        """
        os.environ["FORKRUN_RETRY_LIMIT"] = "1"
        for flag in ("0", "1"):
            os.environ["FORKRUN_CLEANROOM"] = flag
            out, st = forkrun.map(self._fail(), self.path, mode="plugin",
                                  output="bytes", return_stats=True,
                                  nodes=1, workers=1, orchestrator=False)
            self.assertEqual(
                st["total"], st["completed"] + st["poisoned"],
                "FORKRUN_CLEANROOM=%s: total %r != completed %r + "
                "poisoned %r" % (flag, st["total"], st["completed"],
                                 st["poisoned"]))
            self.assertEqual(st["completed"], len(out))
            self.assertGreater(
                st["poisoned"], 0,
                "FORKRUN_CLEANROOM=%s: fixture must poison something; the "
                "old bug reported 0 here" % (flag,))
            # always_fail_v1 poisons EVERY batch, so nothing completes.
            # This is the assertion the P0 would have failed hardest:
            # poisoned=0 AND completed=len(out) both looked plausible.
            self.assertEqual(st["completed"], 0)

    def test_strict_poison_raises_with_a_real_count(self):
        """strict_poison=True is enforced on the cleanroom.

        Only enforceable because the count came back over the stats
        channel; before that the launcher declined the call outright.

        The count is NOT compared across paths -- see the note in
        test_return_stats_poison_counts_are_consistent about batch count
        being timing-dependent. Asserting it is a positive integer is
        the real property: a raise carrying count=0 would satisfy a
        weaker "did it raise" test while telling the user nothing about
        how much was skipped.
        """
        import forkrun as _fk
        os.environ["FORKRUN_RETRY_LIMIT"] = "1"
        for flag in ("0", "1"):
            os.environ["FORKRUN_CLEANROOM"] = flag
            with self.assertRaises(_fk.ForkrunPoisonSkip) as ctx:
                forkrun.map(self._fail(), self.path, mode="plugin",
                            output="bytes", strict_poison=True,
                            nodes=1, workers=1, orchestrator=False)
            self.assertGreater(
                ctx.exception.count, 0,
                "FORKRUN_CLEANROOM=%s raised with count=0" % (flag,))
            # The count must survive into last_run_stats, so a caller
            # can inspect it after catching the exception.
            self.assertEqual(forkrun.last_run_stats()["poisoned"],
                             ctx.exception.count)

    def test_retry_limit_is_transported(self):
        # FORKRUN_RETRY_LIMIT=0 poisons on the FIRST failure, so the
        # launcher must not silently use its own default of 3. Both
        # paths must still agree, and agree on empty.
        os.environ["FORKRUN_RETRY_LIMIT"] = "0"
        a, b = self._both(self._fail())
        self.assertEqual(_joined(a), _joined(b))

    def test_retry_limit_custom_agrees(self):
        os.environ["FORKRUN_RETRY_LIMIT"] = "1"
        a, b = self._both(self._fail())
        self.assertEqual(_joined(a), _joined(b))


@unittest.skipUnless(HAVE_PLUGIN, "test plugin not available")
class TestCleanroomStreaming(unittest.TestCase):
    """W-CR3: streaming through the public stream() API.

    The C capability was verified standalone before any wiring (first
    result at 2.8 ms on a 200k-record pipe). These tests pin the
    PYTHON half: byte-exactness against the in-process path, liveness,
    and -- the one that would hurt most -- teardown when the caller
    abandons the stream early.
    """

    def setUp(self):
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        self.n = 40000
        self._old = os.environ.get("FORKRUN_CLEANROOM")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._old is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._old

    def _lines(self, n):
        for i in range(n):
            yield ('{"eid":"e%d","uid":1,"iid":2,"ts":1700000000,'
                   '"et":"view","dev":"ios","dur":5}\n' % i).encode()

    def _pipe_with_producer(self, n, delay=0.0):
        """A pipe fed by a background thread; returns (read_fd, thread)."""
        import threading
        r, w = os.pipe()

        def run():
            buf = []
            for i in range(n):
                buf.append('{"eid":"e%d","uid":1,"iid":2,"ts":1700000000,'
                           '"et":"view","dev":"ios","dur":5}\n' % i)
                if len(buf) >= 500:
                    os.write(w, "".join(buf).encode())
                    buf = []
                if delay:
                    time.sleep(delay)
            if buf:
                os.write(w, "".join(buf).encode())
            os.close(w)

        th = threading.Thread(target=run, daemon=True)
        th.start()
        return r, th

    def _drain(self, fd, order="none"):
        out = []
        for blob in forkrun.stream(
                _spec(), fd, mode="plugin", workers=4, nodes=1,
                streaming=True, orchestrator=False, order=order):
            out.append(bytes(blob))
        return b"".join(out)

    def test_stream_matches_in_process(self):
        r, th = self._pipe_with_producer(self.n)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        streamed = self._drain(r)
        th.join()
        os.close(r)
        # Reference: same records, materialized, in-process.
        path = _make_input(self.n)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        os.environ["FORKRUN_CLEANROOM"] = "0"
        ref = b"".join(bytes(x) for x in forkrun.map(
            _spec(), path, workers=4, nodes=1, mode="plugin",
            output="bytes", orchestrator=False))
        self.assertEqual(len(streamed), len(ref))
        self.assertEqual(streamed, ref)

    def test_stream_order_index_matches_in_process(self):
        """stream(order="index") through the launcher must match.

        stream() orders by PARENT-SIDE reassembly from batch_idx, with a
        bounded out-of-order buffer -- it does not run the C orderer
        either, so the launcher needs no ordering process. This pins
        that: the ordered streamed bytes must equal the ordered
        in-process run, which is the oracle.

        Compared against the in-process run rather than a sorted-ness
        check on purpose. A stream that silently dropped or duplicated
        records could still come out monotonic; only parity catches
        that.
        """
        r, th = self._pipe_with_producer(self.n)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        streamed = self._drain(r, order="index")
        th.join()
        os.close(r)

        path = _make_input(self.n)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        os.environ["FORKRUN_CLEANROOM"] = "0"
        ref = b"".join(bytes(x) for x in forkrun.map(
            _spec(), path, workers=4, nodes=1, mode="plugin",
            output="bytes", order="index", orchestrator=False))
        self.assertEqual(len(streamed), len(ref))
        self.assertEqual(streamed, ref,
                         "cleanroom stream order='index' differs from "
                         "in-process")

    def test_stream_is_live(self):
        # A slow producer: if the launcher buffered to EOF, the first
        # result could not arrive until the producer finished.
        r, th = self._pipe_with_producer(self.n, delay=0.00005)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        t0 = time.time()
        first = None
        for blob in forkrun.stream(
                _spec(), r, mode="plugin", workers=4, nodes=1,
                streaming=True, orchestrator=False):
            if first is None:
                first = time.time() - t0
        th.join()
        os.close(r)
        self.assertIsNotNone(first, "no result arrived at all")
        self.assertLess(
            first, 5.0,
            "first result took %.1fs -- the launcher is buffering to EOF "
            "instead of streaming" % (first,))

    def test_abandon_early_does_not_hang_or_leak(self):
        """Abandon mid-stream: nothing may survive.

        This test used to assert that the PRODUCER completes, and it
        passed -- but only because of the leak it was supposed to catch.
        Abandoning killed the launcher while its children survived, and
        the orphaned spill child kept draining the producer's pipe, so
        the producer ran to completion. "Producer finished" was
        therefore evidence of the bug, not of correctness.

        PR_SET_PDEATHSIG in the launcher fixes that: the subtree dies,
        and the producer then blocks on a full pipe -- correctly, since
        no reader is left. So the assertion has to change to the
        property that actually matters: NO DESCENDANT SURVIVES.

        The test also closes its own read fd before streaming (the
        library dups it), so the producer gets EPIPE and unwinds rather
        than parking on a pipe whose only reader is this process.
        """
        r, th = self._pipe_with_producer(200000)
        r2 = os.dup(r)
        os.close(r)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        gen = forkrun.stream(
            _spec(), r2, mode="plugin", workers=4, nodes=1,
            streaming=True, orchestrator=False)
        got = next(iter(gen))
        self.assertTrue(len(bytes(got)) > 0)
        # The library has now dup'd the source and closed its own copy,
        # so dropping ours leaves the spill child as the only reader.
        # That is what lets the producer see EPIPE once the subtree dies,
        # instead of parking forever on a pipe nobody is draining.
        os.close(r2)

        # Snapshot the launcher's whole subtree BEFORE abandoning --
        # afterwards the launcher is gone and there is nothing to walk.
        launch_pid = _find_launcher()
        self.assertIsNotNone(launch_pid, "launcher pid not found")
        before = _descendants_of(launch_pid)
        self.assertTrue(before, "launcher had no descendants to leak")

        gen.close()

        # The whole point: nothing outlives the launcher.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            alive = [k for k in before
                     if os.path.exists("/proc/%d" % k)]
            if not alive:
                break
            time.sleep(0.1)
        self.assertFalse(
            os.path.exists("/proc/%d" % launch_pid),
            "launcher survived gen.close()")
        survivors = [k for k in before
                     if os.path.exists("/proc/%d" % k)]
        self.assertEqual(
            survivors, [],
            "descendants survived abandonment -- PDEATHSIG not effective: "
            "%r" % (survivors,))
        # And the producer must unwind rather than park on a full pipe.
        th.join(timeout=30)
        self.assertFalse(th.is_alive(),
                         "producer still blocked after abandonment")
        th.join(timeout=5)

    def test_stream_outside_envelope_falls_back(self):
        # orchestrator=True is the default and is OUTSIDE the envelope;
        # it must still produce correct output rather than break.
        r, th = self._pipe_with_producer(5000)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        out = b"".join(bytes(x) for x in forkrun.stream(
            _spec(), r, mode="plugin", workers=2, nodes=1,
            streaming=True))
        th.join()
        os.close(r)
        self.assertGreater(len(out), 0)


@unittest.skipUnless(HAVE_PLUGIN, "test plugin not available")
class TestCleanroomProcessDeath(unittest.TestCase):
    """P0: a worker that DIES, not one that returns an error.

    always_fail_v1 covers the ordinary path (return 42 -> retry ->
    poison). These fixtures raise(SIGKILL) inside the plugin, which is
    the case external review flagged: the launcher exits non-zero,
    Python falls back, and the WHOLE JOB RE-RUNS.

    That makes cleanroom semantics AT-LEAST-ONCE for any plugin with
    side effects. These tests pin that behaviour explicitly rather than
    leaving it implied -- a reader should not have to infer it.
    """

    V1_SO = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        "python", "tests", "plugins", "test_plugin_v1.so")

    def setUp(self):
        if not os.path.exists(self.V1_SO):
            self.skipTest("test_plugin_v1.so not built")
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        self._old = {k: os.environ.get(k) for k in
                     ("FORKRUN_CLEANROOM", "FORKRUN_TEST_SIDE_EFFECT_FILE",
                      "FORKRUN_TEST_DIE_FILE")}
        self.tmp = tempfile.mkdtemp(prefix="frdeath")
        self.path = _make_input(400)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _marker(self):
        p = os.path.join(self.tmp, "side_effects")
        os.environ["FORKRUN_TEST_SIDE_EFFECT_FILE"] = p
        return p

    def _read(self, p):
        if not os.path.exists(p):
            return []
        with open(p) as fh:
            return [ln.strip() for ln in fh if ln.strip()]

    def test_worker_death_falls_back_and_returns_correct_bytes(self):
        """A SIGKILLed worker must not cost the caller its output."""
        die = os.path.join(self.tmp, "died")
        os.environ["FORKRUN_TEST_DIE_FILE"] = die
        self._marker()
        os.environ["FORKRUN_CLEANROOM"] = "1"
        out = forkrun.map(self.V1_SO + ":die_once_v1", self.path,
                          workers=2, nodes=1, mode="plugin",
                          output="bytes", orchestrator=False)
        joined = b"".join(bytes(x) for x in out)
        # die_once_v1 emits nothing, so correct output IS empty -- what
        # matters is that the run completed rather than hanging or
        # aborting, and that the job was actually re-executed.
        self.assertEqual(joined, b"")
        self.assertTrue(
            os.path.exists(die),
            "the kill-once marker was never written, so the worker never "
            "died and this test proved nothing")

    def test_worker_death_is_recovered_not_replayed(self):
        """A dead worker is RECOVERED -- the job is not replayed.

        This test used to assert the opposite. Before W-CR4 the launcher
        had no supervisor, so a dead worker made it exit non-zero and
        map() re-ran the WHOLE input in process -- at-least-once
        execution, with every side effect performed twice.

        With the supervisor in place (ring_recover_worker + respawn on
        the same wid) the launcher recovers the dead worker and finishes
        the job itself, so invocation counts stay level with an
        undisturbed run. Equal counts are therefore the WINNING outcome,
        and the at-least-once caveat no longer describes the common
        case. What still replays is a death the recovery core refuses
        (rc 4, mid-transaction), which falls back -- see
        TestCleanroomWorkerDeath for the abort-on-race path.

        Both arms run the same plugin so batching is comparable; only
        the die marker differs.
        """
        os.environ["FORKRUN_CLEANROOM"] = "1"

        m = self._marker()
        os.environ["FORKRUN_TEST_DIE_FILE"] = os.path.join(
            self.tmp, "already-fired")
        forkrun.map(self.V1_SO + ":die_once_v1", self.path,
                    workers=2, nodes=1, mode="plugin", output="bytes",
                    orchestrator=False)
        clean_arm = len(self._read(m))
        os.unlink(m)

        os.environ["FORKRUN_TEST_DIE_FILE"] = os.path.join(
            self.tmp, "not-yet-fired")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            forkrun.map(self.V1_SO + ":die_once_v1", self.path,
                        workers=2, nodes=1, mode="plugin", output="bytes",
                        orchestrator=False)
        fallbacks = [str(w.message) for w in caught
                     if "in-process path" in str(w.message)]
        self.assertEqual(
            fallbacks, [],
            "the cleanroom run fell back to the in-process path, so the "
            "job WAS replayed end to end: %r" % (fallbacks,))
        death_arm = len(self._read(m))

        # One extra invocation is the retried batch. Anything approaching
        # a whole second pass means the job was replayed end to end.
        # Note the count is inherently timing-dependent: a respawned
        # worker whose ring is ALREADY drained calls fr_py_claim, gets
        # RC_EOF and exits WITHOUT invoking the plugin, so whether the
        # retried batch adds an invocation depends on when the respawn
        # lands relative to the ring emptying. Pinning death_arm >=
        # clean_arm therefore tests scheduling luck, not behaviour.
        #
        # The property is "the job was not replayed end to end". A
        # replay roughly doubles the invocation count; recovery leaves it
        # at the same level or one higher (the retried batch). Do NOT
        # assert death_arm >= clean_arm: whether the retried batch adds
        # an invocation depends on where the death landed, and pinning
        # that made this test flake on arithmetic rather than behaviour.
        # The property is "the job was not replayed end to end".
        #
        # Do NOT assert this with arithmetic. Invocation count is a
        # function of BATCHING, and batching is timing-dependent: it
        # varies with how much has spilled when a worker claims, and it
        # shifts whenever anything else changes (a different fd in the
        # launcher's layout is enough). Observed clean-arm counts across
        # runs of an UNCHANGED test: 8, 19, 26, 27, 28. Pinning a ratio
        # against that is pinning noise -- this test failed at 26-vs-8
        # and passed at 26-vs-26 with identical code.
        #
        # The direct signal is whether the run FELL BACK. A whole-job
        # replay happens in-process, and run.py warns loudly when it
        # does ("cleanroom launcher failed ... using the in-process
        # path"). No such warning means the launcher recovered the dead
        # worker itself, which is exactly the behaviour under test.
        # The counts are kept only as a loose sanity bound.
        self.assertLess(
            death_arm, clean_arm * 8,
            "a worker death multiplied invocations %dx (%d vs %d) -- far "
            "beyond a retried batch"
            % (death_arm // max(clean_arm, 1), death_arm, clean_arm))


@unittest.skipUnless(HAVE_PLUGIN, "test plugin not available")
class TestCleanroomWorkerDeath(unittest.TestCase):
    """W-CR4: an EXTERNALLY killed worker must not hang the run.

    Distinct from TestCleanroomProcessDeath, where the plugin kills
    ITSELF from inside. Here the signal comes from outside, so the
    launcher reaps a child that died for reasons the engine never saw,
    which is the case W-CR4's supervision loop exists to handle.

    What this pins is TERMINATION plus protocol correctness, not
    completeness of output. A worker killed mid-claim yields
    ring_recover_worker rc 4 (RACE_DETECTED) and the run ABORTS, exactly
    as frun.bash does; killed between batches it recovers and finishes.
    Asserting byte-completeness would be asserting a guarantee the
    engine does not make on either path -- a killed batch is retried and
    then POISONED, so some records are legitimately dropped.
    """

    def setUp(self):
        if _cleanroom_launcher_path() is None:
            self.skipTest("launcher binary not built")
        self.path = _make_input(4000)
        self.addCleanup(lambda: os.path.exists(self.path)
                        and os.unlink(self.path))

    def _expect_bytes(self):
        old = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "0"
        try:
            return sum(len(bytes(x)) for x in forkrun.map(
                _spec(), self.path, workers=4, nodes=1, mode="plugin",
                output="bytes", orchestrator=False))
        finally:
            if old is None:
                os.environ.pop("FORKRUN_CLEANROOM", None)
            else:
                os.environ["FORKRUN_CLEANROOM"] = old

    def _kill_a_worker(self):
        """Run the launcher on a SLOW PIPE, SIGKILL one worker, read on.

        A pipe source rather than a file: with a small file the launcher
        finishes in milliseconds and the scan finds no children at all,
        so the test silently proved nothing (it did, twice). A producer
        that trickles keeps the launcher alive deterministically, so a
        worker is always there to kill.
        """
        import subprocess
        import threading
        import time
        from forkrun._bindings import find_substrate
        launcher = _cleanroom_launcher_path()
        sr, sw = os.pipe()

        def produce():
            buf = []
            try:
                for i in range(30000):
                    buf.append('{"eid":"e%d","uid":1,"iid":2,'
                               '"ts":1700000000,"et":"view","dev":"ios",'
                               '"dur":5}\n' % i)
                    if len(buf) >= 200:
                        os.write(sw, "".join(buf).encode())
                        buf = []
                    time.sleep(0.0002)
                if buf:
                    os.write(sw, "".join(buf).encode())
            except OSError:
                pass          # launcher gone; producer unwinds
            finally:
                try:
                    os.close(sw)
                except OSError:
                    pass

        th = threading.Thread(target=produce, daemon=True)
        th.start()

        rr, rw = os.pipe()
        os.set_inheritable(sr, True)
        os.set_inheritable(rw, True)
        proc = subprocess.Popen(
            [launcher, "--so", find_substrate(), "--plugin", PLUGIN,
             "--func", "ml_process_light", "--workers", "8",
             "--lines", "0", "--src", str(sr), "--result", str(rw)],
            pass_fds=(sr, rw), stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE)
        os.close(sr)
        os.close(rw)

        # Let the pipeline reach steady state FIRST. Killing a worker
        # during startup, before it has ever claimed, exercises a
        # different path (and can read as a mid-claim race); we want the
        # ordinary case of a running worker dying between batches.
        time.sleep(1.5)
        victim = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and victim is None:
            for d in glob.glob("/proc/%d/task/*/children" % proc.pid):
                try:
                    kids = open(d).read().split()
                except OSError:
                    continue
                for k in kids:
                    # A WORKER holds exactly ONE output memfd; the
                    # DRAIN holds ALL of them (it must, to move every
                    # worker's bytes), and the scanner holds
                    # fr_cr_ingress. Matching on "has an fr_cr_out_"
                    # therefore selects the drain and kills the wrong
                    # process -- which is unrecoverable and yields a
                    # clean exit with zero output. Count them.
                    try:
                        nout = 0
                        for f in os.listdir("/proc/%s/fd" % k):
                            if "fr_cr_out_" in os.readlink(
                                    "/proc/%s/fd/%s" % (k, f)):
                                nout += 1
                        if nout == 1:
                            victim = k
                    except OSError:
                        pass
            if victim is None:
                time.sleep(0.05)
        killed = False
        if victim:
            try:
                os.kill(int(victim), signal.SIGKILL)
                killed = True
            except OSError:
                pass

        # Drain fully. Breaking on BlockingIOError once the launcher has
        # exited discards whatever is still buffered in the pipe, which
        # showed up as a spurious "launcher produced no output".
        out = b""
        os.set_blocking(rr, False)
        end = time.monotonic() + 90
        while time.monotonic() < end:
            try:
                chunk = os.read(rr, 1 << 16)
            except BlockingIOError:
                if proc.poll() is not None:
                    # exited AND nothing left to read: give the pipe one
                    # last chance to hand over buffered bytes.
                    for _ in range(20):
                        try:
                            chunk = os.read(rr, 1 << 16)
                        except BlockingIOError:
                            time.sleep(0.05)
                            continue
                        if not chunk:
                            break
                        out += chunk
                    break
                time.sleep(0.05)
                continue
            if not chunk:
                break
            out += chunk
        try:
            _, err = proc.communicate(timeout=30)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            err, rc = b"", -1
        self._stderr = (err or b"").decode(errors="replace")
        try:
            os.close(sw)
        except OSError:
            pass
        os.close(rr)
        return killed, rc, out

    def test_sigkilled_worker_does_not_hang_the_run(self):
        """A SIGKILLed worker must not hang the cleanroom.

        What this asserts is deliberately NOT "output is complete".
        A killed batch is retried and then POISONED -- the engine's
        documented num_kills path, identical to what the in-process
        reactor does with a failing batch -- so some records are
        legitimately dropped and the launcher exits 0 with less output.
        Asserting completeness here would be asserting a behaviour the
        engine does not have on either path.

        What must hold is the thing that was broken: the run TERMINATES,
        cleanly, rather than deadlocking with every worker polling a
        ring slot nobody will ever reclaim.
        """
        killed, rc, out = self._kill_a_worker()
        self.assertTrue(killed, "no worker was identified and killed -- "
                                "the test proved nothing")
        # Either outcome is CORRECT, and which one you get depends on
        # where the worker happened to be:
        #   rc 0 -> died between batches; recover returned RECOVERED, the
        #           wid was respawned, and the run finished normally.
        #   rc 1 -> died CLAIMING or COMMITTING; ring_recover_worker
        #           returns 4 (RACE_DETECTED) and the protocol ABORTS,
        #           because the in-flight batch is unattributable. bash
        #           does exactly this (frun.bash: "died mid-transaction
        #           (race window); batch unattributable" -> ring_abort).
        # Asserting rc==0 would be asserting a guarantee the engine does
        # not make on either path.
        self.assertIn(rc, (0, 1),
                      "launcher exited %r; stderr:\n%s"
                      % (rc, getattr(self, "_stderr", "")))
        # Some output must exist: a run that produced nothing at all
        # would mean the kill aborted the pipeline instead of recovering.
        if rc == 0:
            self.assertGreater(
                len(out), 0,
                "recovered run produced no output; stderr:\n%s"
                % getattr(self, "_stderr", ""))
        # Framing must be intact -- a truncated trailing record is the
        # documented drop, a malformed middle is not.
        pos = 0
        recs = 0
        while pos + 16 <= len(out):
            _b, blen = struct.unpack_from("<QQ", out, pos)
            self.assertLessEqual(pos + 16 + blen, len(out),
                                 "record %d claims %d bytes but only %d "
                                 "remain -- framing desync"
                                 % (recs, blen, len(out) - pos - 16))
            pos += 16 + blen
            recs += 1
        if rc == 0:
            # A recovered run must have delivered whole records.
            self.assertGreater(recs, 0, "no complete records")
        else:
            # Aborted mid-transaction: a torn trailing record is the
            # documented drop and there may be nothing at all.
            self.assertEqual(pos, len(out),
                             "output has %d trailing bytes that do not "
                             "form a whole record" % (len(out) - pos))


if __name__ == "__main__":
    unittest.main()
