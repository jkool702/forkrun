"""F6 Stage 2B -- the CURRENT launch-failure contract, and how a
posix_spawn backend would differ.

WHY THIS FILE EXISTS
--------------------
The Stage 2 design document claimed that a child-side `execv()` failure
(observed as exit 127) is routed into an in-process fallback. **That was
wrong**, and this file exists to pin the real contract so the mistake
cannot recur.

The truth, from source and confirmed by observation:

* `_CR_EXIT_PRE_INGEST = {64, 69, 71, 78, 80, 81, 82}` -- **127 is absent**.
* `_decode_launcher_status()` derives `pre_ingest` from that set.
* `_cleanroom_may_fallback()` returns `bool(pre_ingest) and not forbidden`.
* Therefore exit 127 has `pre_ingest=False`, `may_fallback=False`,
  `forbidden=False`, and the caller is given a **`RuntimeError`** -- the
  call does NOT fall back.

The case that DOES fall back is different and must not be confused with
it: the launcher being **absent at preflight** (`_cleanroom_launcher_path()`
returns None), which warns and returns None before any fork. A launcher
that exists but cannot be *executed* is not that case.

These tests call the PRODUCTION helpers directly rather than
re-implementing the policy. A copy of the logic would pass identically
whether the production rule changed or not -- which is precisely how the
wrong claim survived in the first place.

Scope: this is a contract description plus mechanism observation. It does
not implement a backend, does not modify `run.py`, and does not assert any
posix_spawn integration exists.
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
import warnings

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "python"))

from forkrun.run import (                                    # noqa: E402
    _CR_EXIT_PRE_INGEST,
    _CR_EXIT_NO_FALLBACK,
    _cleanroom_may_fallback,
    _decode_launcher_status,
    _fallback_forbidden,
)


def _status(code):
    """A waitpid() status for a normally-exited child."""
    return code << 8


class TestExit127IsNotFallbackSafe(unittest.TestCase):
    """The correction to the Stage 2 claim."""

    def test_127_is_not_in_pre_ingest(self):
        self.assertNotIn(
            127, _CR_EXIT_PRE_INGEST,
            "if 127 were pre-ingest, execv() failure WOULD fall back; the "
            "Stage 2 claim rested on the opposite")

    def test_127_decodes_as_not_pre_ingest(self):
        code, signum, label, pre = _decode_launcher_status(_status(127))
        self.assertEqual(code, 127)
        self.assertIsNone(signum)
        self.assertFalse(pre, "exit 127 must decode as NOT pre-ingest")

    def test_127_is_not_fallback_permitted(self):
        self.assertFalse(_cleanroom_may_fallback(_status(127)))
        self.assertFalse(_fallback_forbidden(_status(127)),
                         "127 is not in _CR_EXIT_NO_FALLBACK either, so it "
                         "is neither safe-to-fallback nor explicitly "
                         "forbidden -- it lands in the ordinary failure "
                         "path")

    def test_preflight_missing_launcher_returns_none_early(self):
        """Launcher ABSENT AT PREFLIGHT: the launch function warns and
        returns None BEFORE any fork.

        This is the case that DOES fall back, and the one Stage 2B
        conflated with the exec-failure case. It is exercised here by
        patching the path resolver to return None -- the real
        `_execute_cleanroom` body, not a copy.
        """
        import forkrun
        from forkrun.run import _execute_cleanroom
        R = sys.modules["forkrun.run"]
        self.addCleanup(setattr, R, "_cleanroom_launcher_path",
                        R._cleanroom_launcher_path)
        R._cleanroom_launcher_path = lambda: None
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        src = os.path.join(d, "in.txt")
        with open(src, "w") as fh:
            fh.write("a\nb\n")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _execute_cleanroom(
                src, lines=1, bytes_=None, workers=2,
                plugin_path="/nonexistent.so", plugin_func="f",
                on_error="retry", views=True)
        self.assertIsNone(result, "absent launcher must decline early")
        self.assertTrue(
            any("launcher binary is missing" in str(w.message)
                for w in caught),
            "expected the missing-launcher warning, got %r"
            % [str(w.message) for w in caught])

    def test_known_fallback_codes_still_fall_back(self):
        """Guard against "fixing" the table in the wrong direction."""
        for code in sorted(_CR_EXIT_PRE_INGEST):
            if code in _CR_EXIT_NO_FALLBACK:
                continue
            self.assertTrue(
                _cleanroom_may_fallback(_status(code)),
                "exit %d is classified pre-ingest and must still fall back"
                % code)

    def test_post_ingest_codes_do_not_fall_back(self):
        for code in (0, 1, 70, 79, 127):
            self.assertFalse(
                _cleanroom_may_fallback(_status(code)),
                "exit %d must not fall back" % code)


class TestMechanismDifference(unittest.TestCase):
    """What each mechanism actually does when the executable cannot run."""

    def test_fork_execv_reports_failure_through_child_status(self):
        pid = os.fork()
        if pid == 0:
            try:
                os.execv("/nonexistent/no/such/binary", ["x"])
            except BaseException:
                os._exit(127)
        _, st = os.waitpid(pid, 0)
        self.assertTrue(os.WIFEXITED(st))
        code, _signum, _label, pre = _decode_launcher_status(st)
        self.assertEqual(code, 127)
        self.assertFalse(pre)
        self.assertFalse(_cleanroom_may_fallback(st))

    def test_posix_spawn_raises_in_the_parent_instead(self):
        with self.assertRaises(FileNotFoundError):
            os.posix_spawn("/nonexistent/no/such/binary", ["x"], os.environ)

    def test_non_executable_raises_permission_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write("#!/bin/sh\nexit 0\n")
            path = f.name
        self.addCleanup(os.unlink, path)
        os.chmod(path, 0o644)
        with self.assertRaises(PermissionError):
            os.posix_spawn(path, [path], os.environ)

    def test_the_two_mechanisms_disagree(self):
        """Stated as a test so the divergence cannot be quietly forgotten.

        Same failure, different reporting channel: fork+execv yields a
        wait status the caller must classify; posix_spawn raises before
        any child exists. There is no status to classify, so a naive swap
        would bypass _cleanroom_may_fallback entirely.
        """
        pid = os.fork()
        if pid == 0:
            try:
                os.execv("/nonexistent/no/such/binary", ["x"])
            except BaseException:
                os._exit(127)
        _, st = os.waitpid(pid, 0)
        got_status = os.WIFEXITED(st) and os.WEXITSTATUS(st) == 127
        try:
            os.posix_spawn("/nonexistent/no/such/binary", ["x"], os.environ)
            got_raise = False
        except OSError:
            got_raise = True
        # BOTH report the failure -- that is the point. What differs is the
        # CHANNEL: one produces a wait status for the caller to classify,
        # the other raises before any child exists. An earlier draft
        # asserted the two booleans were unequal, which is nonsense: they
        # are both true, and the divergence is in kind, not in occurrence.
        self.assertTrue(got_status, "fork+execv must surface exit 127")
        self.assertTrue(got_raise, "posix_spawn must raise to the parent")
        # And the consequence that matters for the design: there is no
        # status under posix_spawn, so _cleanroom_may_fallback() -- which
        # is the only thing that permits a fallback -- cannot be consulted.
        self.assertFalse(_cleanroom_may_fallback(_status(127)),
                         "even when the failure is a status, 127 is not "
                         "fallback-safe; under posix_spawn there is no "
                         "status at all")


class TestRouteLevelCallerVisibleResults(unittest.TestCase):
    """Exercise the REAL launch functions, not their logic re-derived.

    Stage 2B asserted what each route does on exit 127 from reading the
    source. These tests execute it: a non-executable stand-in for the
    launcher satisfies the existence preflight, fails execv, and the
    production body runs to its own conclusion.

    The two routes are asserted SEPARATELY and differently, because they
    are different: materialized reports input consumption, streaming
    reports a truncated stream. Asserting them together would hide that.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="routefail-")
        self.addCleanup(shutil.rmtree, self._tmp, True)
        self.fake = os.path.join(self._tmp, "not_a_launcher")
        with open(self.fake, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.fake, 0o644)
        self.src = os.path.join(self._tmp, "in.txt")
        with open(self.src, "w") as fh:
            fh.write("a\nb\nc\n")
        for name in ("FORKRUN_CLEANROOM", "FORKRUN_RETRY_LIMIT"):
            old = os.environ.get(name)
            self.addCleanup(self._restore, name, old)
        os.environ.pop("FORKRUN_CLEANROOM", None)
        os.environ["FORKRUN_RETRY_LIMIT"] = "1"

        # Patch the MODULE attribute. `from forkrun import run` yields the
        # frontend FUNCTION, which shadows the submodule; patching that
        # object silently does nothing and the real launcher runs.
        import forkrun.run  # noqa: F401
        R = sys.modules["forkrun.run"]
        self.addCleanup(setattr, R, "_cleanroom_launcher_path",
                        R._cleanroom_launcher_path)
        R._cleanroom_launcher_path = lambda: self.fake

    @staticmethod
    def _restore(name, value):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def _skip_without_substrate(self):
        try:
            from forkrun._bindings import find_substrate
            if not find_substrate():
                self.skipTest("substrate not built")
        except Exception:
            self.skipTest("substrate not available")

    def test_materialized_route_raises_input_consumption_error(self):
        """map-mode launch function: exit 127 -> RuntimeError about the
        input possibly having been consumed. NOT a fallback."""
        self._skip_without_substrate()
        from forkrun.run import _execute_cleanroom
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with self.assertRaises(RuntimeError) as ctx:
                _execute_cleanroom(
                    self.src, lines=1, bytes_=None, workers=2,
                    plugin_path="/nonexistent.so", plugin_func="f",
                    on_error="retry", views=True)
        msg = str(ctx.exception)
        self.assertIn("exit 127", msg)
        self.assertIn("consumed", msg,
                      "materialized route must report the input-consumption "
                      "rationale, got %r" % msg)
        self.assertTrue(
            any("NOT falling back" in str(w.message) for w in caught),
            "the warning must say the run is NOT falling back")
        # And the status classification is the production one.
        st = 127 << 8
        self.assertFalse(_cleanroom_may_fallback(st))
        self.assertEqual(_decode_launcher_status(st)[3], False)

    def test_streaming_route_raises_truncation_error(self):
        """stream-mode launch function: exit 127 -> RuntimeError about a
        TRUNCATED stream. Different message, same no-fallback outcome."""
        self._skip_without_substrate()
        from forkrun.run import _execute_cleanroom_stream
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("ignore")
            gen = _execute_cleanroom_stream(
                self.src, lines=1, bytes_=None, workers=2,
                plugin_path="/nonexistent.so", plugin_func="f",
                on_error="retry")
            with self.assertRaises(RuntimeError) as ctx:
                list(gen)
        msg = str(ctx.exception)
        self.assertIn("TRUNCATED", msg,
                      "streaming route must report truncation, got %r" % msg)
        self.assertIn("exit 127", msg)

    def test_routes_report_differently_on_the_same_failure(self):
        """The two routes must not be collapsed: same condition, two
        caller-visible messages."""
        self._skip_without_substrate()
        from forkrun.run import (_execute_cleanroom,
                                 _execute_cleanroom_stream)
        msgs = []
        for fn, drive in (
                (_execute_cleanroom, "call"),
                (_execute_cleanroom_stream, "gen")):
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("ignore")
                try:
                    if drive == "call":
                        fn(self.src, lines=1, bytes_=None, workers=2,
                           plugin_path="/nonexistent.so", plugin_func="f",
                           on_error="retry", views=True)
                    else:
                        list(fn(self.src, lines=1, bytes_=None, workers=2,
                                plugin_path="/nonexistent.so",
                                plugin_func="f", on_error="retry"))
                except RuntimeError as e:
                    msgs.append(str(e))
        self.assertEqual(len(msgs), 2, "both routes must have raised")
        self.assertNotEqual(
            msgs[0], msgs[1],
            "the routes report DIFFERENT reasons; if these are equal, a "
            "routing change has collapsed them")


class TestSignalSemantics(unittest.TestCase):
    """Signal dispositions must match. Uses a C child: a Python child
    re-establishes its own handlers and would mask the question."""

    # RAW string: "\n" must reach C as backslash-n. In a normal Python
    # literal it collapses to a real newline and the C source fails to
    # compile with "missing terminating \"" -- which is exactly what
    # happened the first time.
    _C = r"""
#define _GNU_SOURCE
#include <signal.h>
#include <stdio.h>
int main(void){
    struct sigaction sa; sigaction(SIGPIPE, NULL, &sa);
    printf("%d\n", sa.sa_handler == SIG_IGN ? 2 : 0);
    fflush(stdout); return 0;
}
"""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc"):
            raise unittest.SkipTest("no C compiler")
        cls._dir = tempfile.mkdtemp(prefix="sigprobe-")
        cls._bin = os.path.join(cls._dir, "sigrep")
        with open(cls._bin + ".c", "w") as fh:
            fh.write(cls._C)
        proc = subprocess.run(["cc", "-O2", "-o", cls._bin,
                               cls._bin + ".c"],
                              capture_output=True, timeout=300)
        if proc.returncode != 0:
            raise unittest.SkipTest("signal probe build failed")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._dir, ignore_errors=True)

    def _run(self, mechanism, **kw):
        r, w = os.pipe()
        os.set_inheritable(w, True)
        if mechanism == "fork":
            pid = os.fork()
            if pid == 0:
                os.dup2(w, 1)
                os.close(r)
                os.execv(self._bin, [self._bin])
            os.close(w)
            out = os.read(r, 16).decode().strip()
            os.close(r)
            os.waitpid(pid, 0)
        else:
            pid = os.posix_spawn(self._bin, [self._bin], os.environ,
                                 file_actions=[(os.POSIX_SPAWN_DUP2, w, 1)],
                                 **kw)
            os.close(w)
            out = os.read(r, 16).decode().strip()
            os.close(r)
            os.waitpid(pid, 0)
        return out

    def test_inherited_sigign_survives_both_mechanisms(self):
        old = signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        self.addCleanup(signal.signal, signal.SIGPIPE, old)
        fork_out = self._run("fork")
        spawn_out = self._run("spawn")
        self.assertEqual(fork_out, "2", "fork+execv must preserve SIG_IGN")
        self.assertEqual(spawn_out, fork_out,
                         "posix_spawn with NO signal options must match")

    def test_setsigdef_would_change_the_disposition(self):
        """Why the eventual backend must NOT pass setsigdef.

        Passing it RESETS an inherited SIG_IGN to SIG_DFL -- a real
        behaviour change relative to the shipped path, and a silent one,
        because nothing about the descriptor work surfaces it.
        """
        old = signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        self.addCleanup(signal.signal, signal.SIGPIPE, old)
        fork_out = self._run("fork")
        reset_out = self._run("spawn", setsigdef=(signal.SIGPIPE,))
        self.assertEqual(fork_out, "2")
        self.assertEqual(reset_out, "0",
                         "setsigdef resets SIG_IGN; if this ever reports 2 "
                         "the probe is no longer measuring dispositions")


class TestClosedStandardDescriptors(unittest.TestCase):
    """Audit only. A pre-existing edge case, NOT a posix_spawn defect."""

    def test_route_descriptor_can_land_on_fd2_and_be_clobbered(self):
        """With fd 2 closed, run.py's allocation order (src, res, stats,
        errfd) puts a ROUTE descriptor on fd 2, which `dup2(errfd, 2)`
        then destroys.

        Isolated in a subprocess: closing fd 2 in the test runner would
        corrupt its own error reporting.
        """
        src = os.path.join(_ROOT, "python", "tests", "_fd_observer.c")
        if not os.path.exists(src):
            self.skipTest("observer source missing")
        code = (
            "import os, sys\n"
            "os.close(2)\n"
            "src = os.open('/etc/hostname', os.O_RDONLY)\n"
            "res = os.memfd_create('res')\n"
            "stats = os.memfd_create('stats')\n"
            "err = os.memfd_create('err')\n"
            "before = os.readlink('/proc/self/fd/%d' % src)\n"
            "os.dup2(err, 2)\n"
            "try:\n"
            "    after = os.readlink('/proc/self/fd/%d' % src)\n"
            "except OSError as e:\n"
            "    after = 'GONE:' + e.strerror\n"
            "print('%d|%s|%s' % (src, before, after))\n"
        )
        proc = subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
        num, before, after = proc.stdout.strip().splitlines()[-1].split("|")
        self.assertEqual(
            before, "/etc/hostname",
            "precondition: a route descriptor occupies the freed fd 2")
        self.assertNotEqual(
            after, before,
            "dup2(errfd, 2) destroyed the descriptor at fd %s -- CONFIRMED "
            "pre-existing defect: the launcher would be handed --src %s and "
            "read the error memfd as input" % (num, num))


if __name__ == "__main__":
    unittest.main()