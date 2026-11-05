"""Parity: the cleanroom launcher and the in-process executor must agree.

The review asked for a test showing a caller gets the SAME RESULT
whichever engine runs. That is a stronger property than either engine's
own tests, because the two share no execution machinery -- one forks a
launcher that dlopens a plugin or execs an argv, the other does it in
this process. A bug that makes one drop bytes, reorder them, or mangle
an argument is invisible to tests that only ever use one of them.

Two properties are asserted, deliberately in this order:

  1. DETERMINISM -- the same engine, run twice, gives identical bytes.
  2. PARITY -- engine A's bytes equal engine B's bytes.

The order matters. If determinism is asserted second, or omitted, a
mismatch has two possible causes and the failure names the wrong one: it
reads as "the launcher corrupts output" when the real cause may be that
batching is nondeterministic for that command, which no amount of fixing
the launcher will change.

A third property is asserted alongside, because parity alone is
satisfiable by two engines that agree on the same wrong answer: for
commands whose output does not depend on batch boundaries, each engine
is also checked against what the command should actually produce.

Ordering note: every case uses `order="index"`. With `order="none"` and
more than one worker, batches complete OUT OF ORDER BY DESIGN -- that is
the documented meaning of "none". Comparing joined bytes across two such
runs would fail on ordering alone and teach us to distrust a correct
pipeline. Indexed order is the promise actually made, so it is the one
parity can be asserted on. Unordered completeness is covered by the
byte-multiset checks in tools/bench_splice.py and the Stage 1 reassembly
suites.
"""

import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun  # noqa: E402

LINES = 40
PLUGIN = os.path.join(_HERE, "plugins", "test_plugin_v1.so")

UPPER = bytes.maketrans(b"abcdefghijklmnopqrstuvwxyz",
                        b"ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _make_input(tmp, name="in.txt", lines=LINES):
    path = os.path.join(tmp, name)
    with open(path, "w") as fh:
        fh.writelines("line%06d payload\n" % i for i in range(lines))
    return path


def _has_plugin():
    return os.path.exists(PLUGIN)


def _cases():
    """(label, payload, mode, expected_or_None).

    `expected` is None for commands whose output depends on how input is
    split into batches (`wc -c` emits one count per batch), so there is
    no batch-independent answer to compare against. Those still get
    determinism and parity, which is what they can support.

    Every case that is meant to exercise the launcher must have SOME
    positive success condition. A case with expected=None plus
    on_error="skip" can satisfy every assertion while the command failed,
    which is how the old `spawn-sh-argv` case passed.

    Both engine-distinguishing modes are represented. `mode="plugin"`
    takes a "path:function" spec and dlopens it; it is NOT a shell
    command -- the first version of this file passed "cat" and got
    "must be 'path:function' format" 33 times, which is a reminder that
    a suite full of subTest errors can still look like a real result.
    """
    out = [
        ("spawn-cat", "cat", "spawn", "SOURCE"),
        ("spawn-tr-argv", "tr a-z A-Z", "spawn", "UPPER"),
        ("spawn-wc-c", "wc -c", "spawn", None),
        ("spawn-head-n", "head -n 5", "spawn", None),
        # LIST form for anything needing quoting: str.split() does no
        # shell parsing (make_spawn_payload documents this). The previous
        # case was "sh -c wc\ -c", a backslash-quoted string that
        # str.split() renders as the literal argv
        # ['sh','-c','wc\','-c'] -- a different command entirely -- and
        # its expected output was None, so under on_error="skip" it
        # passed by producing nothing at all. Now a list payload with a
        # real, checkable answer.
        ("spawn-sh-argv", ["sh", "-c", "tr a-z A-Z"], "spawn", "UPPER"),
    ]
    if _has_plugin():
        out.append(("plugin-upper", PLUGIN + ":process_v1", "plugin",
                    "UPPER"))
    return out


CASES = _cases()
ENGINE_CASES = [c for c in CASES if c[3] is not None]


class _ParityBase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.src = _make_input(self._tmp.name)
        self._old = os.environ.get("FORKRUN_CLEANROOM")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._old is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._old

    def _source(self):
        return open(self.src, "rb").read()

    def _expected(self, spec):
        src = self._source()
        if spec == "SOURCE":
            return src
        if spec == "UPPER":
            return src.translate(UPPER)
        raise AssertionError("unknown expectation %r" % spec)

    def _run(self, payload, mode, workers, cleanroom, order="index",
             path=None):
        os.environ["FORKRUN_CLEANROOM"] = "1" if cleanroom else "0"
        return b"".join(
            bytes(x) for x in forkrun.map(
                payload, path or self.src, mode=mode, workers=workers,
                nodes=1, order=order, bytes=64, output="bytes",
                on_error="skip") if x is not None)


class TestEngineParity(_ParityBase):

    def test_in_process_is_deterministic_run_to_run(self):
        for label, payload, mode, _e in CASES:
            with self.subTest(case=label):
                a = self._run(payload, mode, 2, cleanroom=False)
                b = self._run(payload, mode, 2, cleanroom=False)
                self.assertEqual(a, b,
                                 "in-process route is not deterministic for "
                                 "%r; a parity mismatch would be blamed on "
                                 "the wrong engine" % label)

    def test_cleanroom_is_deterministic_run_to_run(self):
        for label, payload, mode, _e in CASES:
            with self.subTest(case=label):
                a = self._run(payload, mode, 2, cleanroom=True)
                b = self._run(payload, mode, 2, cleanroom=True)
                self.assertEqual(a, b,
                                 "launcher route is not deterministic for "
                                 "%r" % label)

    def test_engines_produce_identical_bytes(self):
        for label, payload, mode, _e in CASES:
            with self.subTest(case=label):
                inproc = self._run(payload, mode, 2, cleanroom=False)
                launcher = self._run(payload, mode, 2, cleanroom=True)
                self.assertEqual(
                    inproc, launcher,
                    "%r: launcher and in-process disagree\n  in-process: "
                    "%r\n  launcher:   %r"
                    % (label, inproc[:120], launcher[:120]))

    def test_each_engine_matches_the_expected_output(self):
        """Parity alone is satisfiable by two engines that agree on the
        same wrong answer."""
        for label, payload, mode, spec in ENGINE_CASES:
            with self.subTest(case=label):
                want = self._expected(spec)
                for cleanroom, engine in ((False, "in-process"),
                                          (True, "launcher")):
                    got = self._run(payload, mode, 2, cleanroom)
                    self.assertEqual(
                        want, got,
                        "%r via %s did not reproduce the command's output "
                        "(%d bytes, want %d)"
                        % (label, engine, len(got), len(want)))

    def test_parity_holds_across_worker_counts(self):
        """A bug affecting only one engine, or only at one width, shows
        up here."""
        for workers in (1, 2, 4):
            with self.subTest(workers=workers):
                for label, payload, mode, _e in CASES:
                    with self.subTest(case=label):
                        self.assertEqual(
                            self._run(payload, mode, workers, False),
                            self._run(payload, mode, workers, True),
                            "%r diverged at workers=%d" % (label, workers))

    def test_parity_holds_for_streaming_plugin(self):
        """stream() has no spawn dispatch, so stream+spawn falls back
        in-process on BOTH settings -- asserting parity there would be
        vacuous, and is deliberately not done. The plugin case is a
        genuine two-engine compare."""
        for cleanroom, engine in ((False, "in-process"), (True, "launcher")):
            os.environ["FORKRUN_CLEANROOM"] = "1" if cleanroom else "0"
            got = b"".join(
                bytes(x) for x in forkrun.stream(
                    PLUGIN + ":process_v1", self.src, streaming=True,
                    mode="plugin", workers=2, nodes=1, order="index",
                    bytes=64, output="bytes") if x is not None)
            self.assertEqual(
                self._expected("UPPER"), got,
                "stream(plugin) via %s lost or altered data" % engine)


class TestParityIsNotVacuous(_ParityBase):
    """Guard: the parity comparison must actually compare two engines.

    Without this, every parity test passes for the wrong reason if the
    cleanroom silently declines and BOTH runs take the in-process route
    -- they would agree trivially. That is not hypothetical: it is
    precisely what happened in the previous round, where mode='spawn'
    was gated out of the public dispatch, so the "launcher" numbers were
    really two in-process runs.

    Counting calls into the launcher entry point is the direct
    assertion. Checking that FORKRUN_CLEANROOM=1 was set would prove
    nothing -- the engine declines for reasons that have nothing to do
    with the environment.
    """

    def _counted(self, cleanroom, payload, mode):
        """Record whether _execute_cleanroom was CALLED and SUCCEEDED.

        The round-8 review is right that counting calls is not enough.
        The dispatch site is:

            out = _execute_cleanroom(...)
            if out is not None:
                return _map_return(out, return_stats)

        so a None return -- launcher unavailable, or a launcher failure
        the policy allows falling back from -- silently continues to the
        in-process executor. Every output-parity assertion downstream
        would then pass while comparing two in-process runs. Recording
        the call proved the wrapper was REACHED, not that the launcher
        served the run. That is a narrower version of the round-7 false
        positive: correct results from the wrong engine.

        So each entry carries the return value, and the callers assert
        `served is True`, which means the launcher actually produced
        this result.
        """
        import importlib
        run_mod = importlib.import_module("forkrun.run")
        real = run_mod._execute_cleanroom
        calls = []

        def counting(*a, **kw):
            out = real(*a, **kw)
            calls.append({
                "argv": kw.get("spawn_argv") or kw.get("plugin_path"),
                "served": out is not None,
            })
            return out

        run_mod._execute_cleanroom = counting
        self.addCleanup(setattr, run_mod, "_execute_cleanroom", real)
        got = self._run(payload, mode, 2, cleanroom)
        return got, calls

    def test_cleanroom_run_really_uses_the_launcher(self):
        for label, payload, mode, _e in CASES:
            with self.subTest(case=label):
                _got, calls = self._counted(True, payload, mode)
                self.assertTrue(
                    calls, "%r: FORKRUN_CLEANROOM=1 did not reach the "
                           "launcher at all -- every parity result for "
                           "this case is an in-process run compared with "
                           "itself" % label)
                self.assertTrue(
                    all(c["served"] for c in calls),
                    "%r: the launcher was called but returned None for at "
                    "least one batch, so the run fell back in-process and "
                    "the parity comparison below proves nothing about "
                    "the launcher: %r" % (label, calls))

    def test_in_process_run_really_avoids_the_launcher(self):
        for label, payload, mode, _e in CASES:
            with self.subTest(case=label):
                _got, calls = self._counted(False, payload, mode)
                self.assertEqual(
                    [], calls,
                    "%r: the launcher ran with FORKRUN_CLEANROOM=0; the "
                    "two arms of the comparison are not two engines"
                    % label)

    def test_spawn_cases_carry_the_expected_argv(self):
        """The launcher must receive the argv the caller asked for.

        Output parity alone cannot distinguish `tr a-z A-Z` from a
        command that uppercased by some other route. The argv is the
        contract, and it is directly observable at the dispatch site.
        """
        expected = {
            "spawn-cat": ["cat"],
            "spawn-tr-argv": ["tr", "a-z", "A-Z"],
            "spawn-wc-c": ["wc", "-c"],
            "spawn-head-n": ["head", "-n", "5"],
            "spawn-sh-argv": ["sh", "-c", "tr a-z A-Z"],
        }
        for label, payload, mode, _e in CASES:
            if label not in expected:
                continue
            with self.subTest(case=label):
                _got, calls = self._counted(True, payload, mode)
                self.assertTrue(calls, "%r: launcher not reached" % label)
                want = expected[label]
                for c in calls:
                    argv = c["argv"]
                    # argv[0] is resolved to an ABSOLUTE path before the
                    # launcher gets it, which is correct and necessary:
                    # the child scrubs its environment, so a bare "cat"
                    # would have no PATH to resolve against. Comparing
                    # basename() keeps the assertion about what matters
                    # -- the ARGUMENT VECTORS, which is where a re-split
                    # or re-join would show up -- without freezing an
                    # incidental path.
                    self.assertEqual(
                        want[1:], argv[1:],
                        "%r: launcher received argv %r; arguments after "
                        "argv[0] must match %r exactly" % (label, argv, want))
                    self.assertEqual(
                        os.path.basename(want[0]), os.path.basename(argv[0]),
                        "%r: launcher received argv[0] %r, expected the "
                        "command %r" % (label, argv[0], want[0]))


class TestParityInCleanSubprocess(_ParityBase):
    """Same property, with each engine in its own fresh interpreter.

    In-process toggling of an environment variable is the convenient way
    to switch engines, but it shares one interpreter across both. If the
    launcher path left some global mutated -- a cached eligibility
    verdict, a swapped stdio buffer, a loaded helper -- the comparison
    above could be testing the residue of the first run rather than the
    two engines. A fresh interpreter per engine removes that doubt, at
    the cost of a slower test.
    """

    def _child(self, cleanroom, payload, mode, path):
        env = dict(os.environ)
        env["FORKRUN_CLEANROOM"] = "1" if cleanroom else "0"
        code = (
            "import sys,os,hashlib\n"
            "sys.path.insert(0, os.path.join(%r,'python'))\n"
            "import forkrun\n"
            "out = forkrun.map(%r, sys.argv[1], mode=%r, workers=2,\n"
            "                 nodes=1, order='index', bytes=64,\n"
            "                 output='bytes', on_error='skip')\n"
            "sys.stdout.buffer.write(hashlib.sha256(\n"
            "    b''.join(bytes(x) for x in out if x is not None)"
            ").digest())" % (_ROOT, payload, mode))
        proc = subprocess.run([sys.executable, "-c", code, path],
                              env=env, capture_output=True)
        self.assertEqual(
            0, proc.returncode,
            "child (cleanroom=%s) failed: %s"
            % (cleanroom, proc.stderr.decode()[-400:]))
        return proc.stdout

    def test_hashes_match_across_fresh_interpreters(self):
        for label, payload, mode, _e in CASES:
            with self.subTest(case=label):
                a = self._child(False, payload, mode, self.src)
                b = self._child(True, payload, mode, self.src)
                self.assertEqual(
                    len(a), 32,
                    "child produced no output for %r -- parity against "
                    "empty output would be meaningless" % label)
                self.assertEqual(
                    a, b,
                    "%r: fresh in-process and launcher interpreters disagree "
                    "(sha256 %s vs %s)" % (label, a.hex(), b.hex()))


if __name__ == "__main__":
    unittest.main()
