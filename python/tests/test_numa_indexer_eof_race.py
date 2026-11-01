"""W-NUMA-STALE-EOF: the indexer death classification must use a
fresh EOF observation.

The defect this file pins (confirmed from instrumented CI output):

    eof sample before helper observation: 0
    indexer waitpid:                      0 (clean, normal exit)
    eof sample after helper observation:  1
    classification:                       fatal  <- WRONG

`check_scanner_death()` may block while it drains a death pipe and
reaps the child. Sampling `fr_py_ingest_eof_posted()` BEFORE that
observation can therefore predate the EOF publication that made a
healthy indexer exit legitimate. A clean indexer exit is gated on
ingest EOF in the engine (`ring_indexer_numa_main` returns success
only after `ingest_eof_idx` is posted), so the only faithful
observation point is AFTER the definitive death result.

The scanner is deliberately NOT refreshed the same way: a clean
scanner exit is also reachable from `emergency_abort` and the
`limit_reached` paths, so "EOF is visible now" does not prove the
scanner consumed its node's chunks. The regression below pins that
asymmetry so a later "consistency" cleanup cannot silently widen the
fix.
"""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import forkrun  # noqa: E402
from forkrun import _bindings  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun import _reactor  # noqa: E402

from _helpers import ChildLifecycleMixin, assert_no_zombies  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

_RUN = sys.modules["forkrun.run"]

NODES_2 = "@2"
N_LINES = 200000
LINE_FMT = "l%06d\n"


class _FakeLib:
    """Minimal engine surface for `_watch_numa_pipeline` unit tests."""

    def __init__(self, eof_values, reason=0):
        self._eof_values = list(eof_values)
        self._last_eof = 0
        self.reason = reason
        self.eof_calls = []
        self.aborts = 0

    def fr_py_ingest_eof_posted(self):
        if self._eof_values:
            self._last_eof = int(self._eof_values.pop(0))
        self.eof_calls.append(self._last_eof)
        return self._last_eof

    def fr_py_abort_reason(self):
        return self.reason

    def fr_py_abort(self):
        self.aborts += 1


def _unit_pipe(key):
    """A pipe dict whose fallow wait is already reaped.

    `os.getpid()` is not our child, so waitpid(WNOHANG) raises
    ChildProcessError, which the watcher treats as "not observed" --
    exactly the fallow state a live unit test needs without forking.
    """
    pipe = {
        "fallow_pid": os.getpid(),
        "indexer_pids": [424242],
        "indexer_deaths": [-1],
        "scanner_pids": [424243],
        "scanner_deaths": [-1],
        "ingest_pid": -1,
        "ingest_death": None,
    }
    del key
    return pipe


def _unit_helpers(key):
    # ingest already classified: _poll_ingest_once is a no-op. The
    # UNTESTED helper family is pre-classified so only one death is
    # offered to the watcher (the patched observer would otherwise
    # return the same definitive result for both).
    other = "scan" if key == "index" else "index"
    return {"fallow_rc": None, "ingest_kind": "clean",
            "ingest_code": 0, "index": {}, "scan": {}, "excused": set(),
            other: {0: ("clean", 0)}}


class TestIndexerEofRefreshUnit(unittest.TestCase):
    """Decision-level tests: no process scheduling involved."""

    def _run_watch(self, key, eof_values, kind="clean", code=0):
        lib = _FakeLib(eof_values)
        helpers = _unit_helpers(key)
        pipe = _unit_pipe(key)
        expected_pid = (pipe["indexer_pids"][0] if key == "index"
                        else pipe["scanner_pids"][0])
        with mock.patch.object(
                _reactor, "check_scanner_death",
                return_value=(kind, code)):
            err = None
            try:
                _RUN._watch_numa_pipeline(lib, pipe, helpers, 1)
            except RuntimeError as exc:
                err = exc
        return lib, helpers, err, expected_pid

    def test_indexer_clean_death_rereads_eof_and_records(self):
        """The positive decision: initial 0, definitive clean, fresh 1."""
        lib, helpers, err, _pid = self._run_watch("index", [0, 1])
        self.assertIsNone(err)
        self.assertEqual(helpers["index"][0], ("clean", 0))
        self.assertEqual(lib.eof_calls, [0, 1],
                         "the indexer re-read did not happen or read the "
                         "stale value: calls=%r" % (lib.eof_calls,))
        self.assertEqual(lib.aborts, 0)

    def test_premature_clean_indexer_remains_fatal(self):
        """Negative: clean + still no EOF + no abort in flight is fatal."""
        lib, helpers, err, _pid = self._run_watch("index", [0, 0])
        self.assertIsNotNone(
            err, "a clean indexer exit without EOF was accepted")
        self.assertIn("NUMA index 0 failed", str(err))
        self.assertEqual(lib.eof_calls, [0, 0])
        self.assertEqual(lib.aborts, 1)

    def test_scanner_clean_death_uses_pre_observation_sample(self):
        """Pinned asymmetry: scanners are NOT refreshed.

        The fake would return 1 on a second read. If the scanner branch
        were ever changed to re-read after the death observation (the
        tempting "make it consistent" cleanup), this clean scanner exit
        would be accepted. It must stay fatal on the pre-observation 0.
        """
        lib, helpers, err, _pid = self._run_watch("scan", [0, 1])
        self.assertIsNotNone(
            err, "a scanner clean exit was accepted on a refreshed EOF "
                 "sample -- scanner and indexer completion semantics "
                 "have been conflated")
        self.assertIn("NUMA scan 0 failed", str(err))
        self.assertEqual(lib.eof_calls, [0],
                         "the scanner path read EOF again after the death "
                         "observation: calls=%r" % (lib.eof_calls,))
        self.assertEqual(lib.aborts, 1)

    def test_indexer_abort_in_flight_is_excused(self):
        """The abort-reason check still precedes our own abort."""
        lib = _FakeLib([0, 0], reason=2)
        helpers = _unit_helpers("index")
        pipe = _unit_pipe("index")
        with mock.patch.object(
                _reactor, "check_scanner_death",
                return_value=("clean", 0)):
            _RUN._watch_numa_pipeline(lib, pipe, helpers, 1)
        self.assertEqual(lib.aborts, 0,
                         "an in-flight abort was re-aborted")
        self.assertIn(("index", 0), helpers["excused"])


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
class TestIndexerEofRefreshIntegration(ChildLifecycleMixin,
                                       unittest.TestCase):
    """The real NUMA pipeline, real indexer pids, real death pipe."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="indexer-eof-")
        cls.corpus = os.path.join(cls._tmp, "in.txt")
        with open(cls.corpus, "w") as fh:
            for i in range(N_LINES):
                fh.write(LINE_FMT % i)
        with open(cls.corpus, "rb") as fh:
            cls.want = fh.read()
        cls.prev_cleanroom = os.environ.get("FORKRUN_CLEANROOM")
        os.environ["FORKRUN_CLEANROOM"] = "0"
        cls.addClassCleanup(cls._restore_cleanroom)

    @classmethod
    def _restore_cleanroom(cls):
        if cls.prev_cleanroom is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = cls.prev_cleanroom

    def test_stale_sample_is_refreshed_after_real_indexer_death(self):
        """Old implementation: false fatal. Corrected: exact output.

        The seam is test-level only, and models the race at the one
        point it exists. Until EOF is posted the fake reports the real
        value (0). The FIRST watch round whose sample sees the real 1
        is reported as 0 instead -- the pre-observation sample -- and
        that round is held open until the real indexer has exited
        (`waitid(WNOWAIT)` peeks without reaping, so the watcher's own
        observer still consumes the status). The indexer's clean death
        is therefore observed in the same falsified round, the watcher
        re-reads, gets 1, and the corrected classification accepts it
        (the old code aborted here: sample 0 + clean exit = fatal).

        Scanners share the round's sample, so a scanner observed in
        that one falsified round would be judged on the test's
        artificial 0. Their observation is deferred while the sample
        is stale or while the engine still reports no EOF; a
        `running` verdict does not consume the death pipe, so a later
        round still observes them. Scanner death semantics are pinned
        separately (the unit test above), which keeps this test about
        the indexer.
        """
        lib = _bindings.get()
        events = []
        forced_stale = [False]
        round_is_stale = [False]
        pipes = []
        real_check = _reactor.check_scanner_death
        real_fork = _RUN._numa_fork_pipeline
        real_watch = _RUN._watch_numa_pipeline
        real_eof = lib.fr_py_ingest_eof_posted
        had_cached = "fr_py_ingest_eof_posted" in lib.__dict__

        def fake_eof():
            value = int(real_eof())
            if value == 1 and not forced_stale[0]:
                # The race, exactly once: EOF became visible between
                # this round's sample and the death observation.
                forced_stale[0] = True
                round_is_stale[0] = True
                value = 0
            events.append(("eof", value))
            return value

        def spy_fork(*args, **kwargs):
            pipe = real_fork(*args, **kwargs)
            pipes.append(pipe)
            return pipe

        def spy_watch(*args, **kwargs):
            # One watcher invocation is one round; the falsified sample
            # belongs to exactly one of them.
            round_is_stale[0] = False
            return real_watch(*args, **kwargs)

        def spy_check(pid, death_r):
            pipe = pipes[-1] if pipes else None
            is_indexer = bool(pipe) and pid in pipe["indexer_pids"]
            if not is_indexer:
                if round_is_stale[0] or int(real_eof()) != 1:
                    return ("running", None)
                return real_check(pid, death_r)
            if round_is_stale[0]:
                # Hold this round open until the indexer exits, without
                # reaping it (the watcher's observer must still be the
                # one that consumes the status).
                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    try:
                        info = os.waitid(
                            os.P_PID, pid,
                            os.WEXITED | os.WNOWAIT | os.WNOHANG)
                    except ChildProcessError:
                        break
                    if info is not None:
                        break
                    time.sleep(0.001)
            kind, code = real_check(pid, death_r)
            if is_indexer and kind != "running":
                events.append(("death", pid, kind, code))
            return kind, code

        try:
            lib.fr_py_ingest_eof_posted = fake_eof
            _RUN._numa_fork_pipeline = spy_fork
            _RUN._watch_numa_pipeline = spy_watch
            _reactor.check_scanner_death = spy_check
            out = forkrun.map(lambda b: bytes(b.data), self.corpus,
                              workers=4, nodes=NODES_2, order="index")
        finally:
            _reactor.check_scanner_death = real_check
            _RUN._numa_fork_pipeline = real_fork
            _RUN._watch_numa_pipeline = real_watch
            if had_cached:
                lib.__dict__["fr_py_ingest_eof_posted"] = real_eof
            else:
                lib.__dict__.pop("fr_py_ingest_eof_posted", None)

        got = b"".join(bytes(r) for r in out)
        self.assertEqual(got, self.want,
                         "the corrected classification lost or reordered "
                         "output")
        deaths = [i for i, e in enumerate(events)
                  if e[0] == "death" and e[1] in pipes[-1]["indexer_pids"]]
        self.assertTrue(
            deaths,
            "the real indexer death was never observed by the watcher "
            "(teardown may have joined it instead); events=%r"
            % (events,))
        first_death = deaths[0]
        self.assertEqual(events[first_death][2], "clean")
        self.assertTrue(
            any(e[0] == "eof" and e[1] == 0 for e in events[:first_death]),
            "the stale pre-observation EOF sample never happened; "
            "events=%r" % (events,))
        self.assertTrue(
            any(e[0] == "eof" and e[1] == 1
                for e in events[first_death + 1:]),
            "no fresh EOF read followed the definitive indexer death; "
            "events=%r" % (events,))

    def tearDown(self):
        assert_no_zombies(self)


if __name__ == "__main__":
    unittest.main()
