"""F6 Stage 3 -- the private `posix_spawn` candidate and the C5 low-FD fix.

SCOPE AND STATUS
----------------
The candidate backend is PRIVATE and test-gated. `_set_cleanroom_launch_backend`
is the only way in; there is no environment selector, no keyword argument and
no default change. The shipped path is `fork()` + `execv()` and every test
here asserts it is still the default.

WHAT THESE TESTS ESTABLISH
--------------------------
1. The candidate produces the same caller-visible results and the SAME
   failure contract as the shipped path -- including exit-127 semantics,
   which are mapped by synthesising the status rather than by a parallel
   error path.
2. The action/signal/environment contract of the candidate is what the
   design says it is (one DUP2 for materialized, an EMPTY list for
   streaming, no signal options, environment untouched).
3. Closing fd 2 no longer silently feeds the launcher the wrong input
   (C5). This is the case that was previously CORRUPTION rather than
   failure.
4. No route-owned descriptor accumulates on success, on failure, on
   abandonment, or when a stats/trace read raises.

WHAT IS NOT ESTABLISHED
-----------------------
The real launcher's entry descriptor set is observed by
`test_cleanroom_launcher_entry_fds.py` against a test-only instrumented
build, not against the shipped release binary. No test here claims
otherwise.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun                                            # noqa: E402
import forkrun.run as _unused_run_module                  # noqa: E402,F401
from forkrun.run import (                                 # noqa: E402
    _CR_EXIT_PRE_INGEST,
    _cleanroom_may_fallback,
    _decode_launcher_status,
)

_R = sys.modules["forkrun.run"]

BACKENDS = ("forkexec", "posix_spawn")

try:
    HAVE_LAUNCHER_STATE = True
except Exception:
    HAVE_LAUNCHER_STATE = False

# Copies its batch to stdout, which is how the plugin ABI returns results.
PLUGIN_C = (
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


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("gcc"):
            raise unittest.SkipTest("gcc absent; plugin fixture cannot build")
        cls._tmp = tempfile.mkdtemp(prefix="stage3-")
        src = os.path.join(cls._tmp, "plugin.c")
        with open(src, "w") as fh:
            fh.write(PLUGIN_C)
        cls.so = os.path.join(cls._tmp, "copyplug.so")
        proc = subprocess.run(
            ["gcc", "-shared", "-fPIC", "-O2",
             "-I", os.path.join(_ROOT, "ring_loadables"),
             "-o", cls.so, src],
            capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            shutil.rmtree(cls._tmp, ignore_errors=True)
            raise unittest.SkipTest("plugin build failed: %s"
                                    % proc.stderr[-300:])
        cls.spec = "%s:copy_v1" % cls.so
        cls.corpus = os.path.join(cls._tmp, "in.txt")
        with open(cls.corpus, "w") as fh:
            # Distinctive tokens so WRONG input is detectable, not just
            # a wrong count.
            for i in range(8):
                fh.write("PAYLOAD_%02d\n" % i)
        # A non-executable launcher stand-in: exists (passes preflight),
        # then fails execv.
        cls.fake = os.path.join(cls._tmp, "not_a_launcher")
        with open(cls.fake, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(cls.fake, 0o644)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        for name in ("FORKRUN_CLEANROOM", "FORKRUN_RETRY_LIMIT"):
            old = os.environ.get(name)
            self.addCleanup(self._restore, name, old)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        os.environ["FORKRUN_RETRY_LIMIT"] = "1"
        prev = _R._set_cleanroom_launch_backend("forkexec")
        self.addCleanup(_R._set_cleanroom_launch_backend, prev)

    @staticmethod
    def _restore(name, value):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def _use(self, backend):
        _R._set_cleanroom_launch_backend(backend)

    def _payload_tokens(self, blobs):
        joined = b"".join(bytes(b) for b in blobs)
        return sorted(set(t for t in joined.split() if t.startswith(b"PAYLOAD")))

    def _non_executable_launcher(self):
        self.addCleanup(setattr, _R, "_cleanroom_launcher_path",
                        _R._cleanroom_launcher_path)
        _R._cleanroom_launcher_path = lambda: self.fake

    def _named_open(self, pattern):
        n = 0
        try:
            entries = os.listdir("/proc/self/fd")
        except OSError:
            return 0
        for fd in entries:
            try:
                tgt = os.readlink("/proc/self/fd/%s" % fd)
            except OSError:
                continue
            if pattern in tgt:
                n += 1
        return n


class TestDefaultBackendIsUnchanged(_Base):
    def test_default_is_forkexec(self):
        """The shipped default must stay fork()+execv(); the candidate is
        reachable only by an explicit private call."""
        self.assertEqual(_R._CLEANROOM_LAUNCH_BACKEND, "forkexec")
        self.assertFalse(hasattr(forkrun, "posix_spawn"),
                         "no posix_spawn option may appear on the public "
                         "API surface")

    def test_no_public_selector_exists(self):
        for forbidden in ("POSIX_SPAWN", "CLEANROOM_BACKEND",
                          "CLEANROOM_LAUNCH", "FORKRUN_SPAWN"):
            self.assertNotIn(forbidden, dir(forkrun),
                             "%s would be a public selector" % forbidden)

    def test_setter_rejects_unknown_backend(self):
        with self.assertRaises(ValueError):
            _R._set_cleanroom_launch_backend("nonsense")


class TestBothBackendsProduceCorrectResults(_Base):
    def test_materialized_matches_across_backends(self):
        results = {}
        for backend in BACKENDS:
            self._use(backend)
            out = forkrun.map(self.spec, self.corpus, mode="plugin",
                              workers=2, lines=1)
            results[backend] = (len(out), self._payload_tokens(out))
        self.assertEqual(results["forkexec"], (8, [b"PAYLOAD_%02d" % i
                                                   for i in range(8)]))
        self.assertEqual(results["posix_spawn"], results["forkexec"],
                         "candidate backend diverged from the shipped one")

    def test_streaming_matches_across_backends(self):
        results = {}
        for backend in BACKENDS:
            self._use(backend)
            gen = forkrun.stream(self.spec, self.corpus, mode="plugin",
                                 workers=2, lines=1, streaming=True)
            try:
                recs = list(gen)
            finally:
                gen.close()
            results[backend] = (len(recs), self._payload_tokens(recs))
        self.assertEqual(results["posix_spawn"], results["forkexec"])

    def test_no_descriptor_accumulation_on_either_backend(self):
        for backend in BACKENDS:
            self._use(backend)
            for _ in range(3):
                forkrun.map(self.spec, self.corpus, mode="plugin",
                            workers=2, lines=1)
            gen = forkrun.stream(self.spec, self.corpus, mode="plugin",
                                 workers=2, lines=1, streaming=True)
            try:
                list(gen)
            finally:
                gen.close()
            self.assertEqual(self._named_open("fr_cleanroom_err"), 0,
                             "%s leaked errfd" % backend)
            self.assertEqual(self._named_open("fr_cleanroom_stream_stats"), 0,
                             "%s leaked stream stats_fd" % backend)


class TestFailureContractIsBackendIndependent(_Base):
    """C1: a spawn-time OSError must produce the route's ESTABLISHED
    caller-visible result, not a raw OSError and not a fallback."""

    def _run_materialized(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                forkrun.map(self.spec, self.corpus, mode="plugin",
                            workers=2, lines=1)
                return None, None, [str(w.message) for w in caught]
            except Exception as e:
                return type(e), str(e), [str(w.message) for w in caught]

    def _run_streaming(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("ignore")
            gen = forkrun.stream(self.spec, self.corpus, mode="plugin",
                                 workers=2, lines=1, streaming=True)
            try:
                list(gen)
                return None, None
            except Exception as e:
                return type(e), str(e)

    def test_materialized_failure_identical_on_both_backends(self):
        self._non_executable_launcher()
        seen = {}
        for backend in BACKENDS:
            self._use(backend)
            etype, msg, warns = self._run_materialized()
            seen[backend] = (etype, msg, warns)
        for backend in BACKENDS:
            self.assertIs(seen[backend][0], RuntimeError,
                          "%s raised %r, expected RuntimeError"
                          % (backend, seen[backend][0]))
            self.assertIn("exit 127", seen[backend][1])
            self.assertIn("consumed", seen[backend][1])
            self.assertTrue(any("NOT falling back" in w
                                for w in seen[backend][2]),
                            "%s must warn that it is NOT falling back"
                            % backend)
        self.assertEqual(seen["forkexec"][:2], seen["posix_spawn"][:2],
                         "the candidate must not change the public failure")

    def test_streaming_failure_identical_on_both_backends(self):
        self._non_executable_launcher()
        seen = {}
        for backend in BACKENDS:
            self._use(backend)
            seen[backend] = self._run_streaming()
        for backend in BACKENDS:
            self.assertIs(seen[backend][0], RuntimeError,
                          "%s raised %r" % (backend, seen[backend][0]))
            self.assertIn("TRUNCATED", seen[backend][1],
                          "streaming must keep its OWN truncation error")
            self.assertIn("exit 127", seen[backend][1])
        self.assertEqual(seen["forkexec"], seen["posix_spawn"])

    def test_no_raw_oserror_escapes(self):
        """The candidate's OSError must not leak out raw: it is mapped
        onto the route's established result."""
        self._non_executable_launcher()
        self._use("posix_spawn")
        etype, msg, _ = self._run_materialized()
        self.assertNotIn(etype, (FileNotFoundError, PermissionError),
                         "raw spawn OSError escaped: %s" % etype)
        self.assertIs(etype, RuntimeError)

    def test_failure_does_not_leak_descriptors(self):
        self._non_executable_launcher()
        for backend in BACKENDS:
            self._use(backend)
            for _ in range(3):
                self._run_materialized()
                self._run_streaming()
            self.assertEqual(self._named_open("fr_cleanroom_err"), 0,
                             "%s leaked errfd on failure" % backend)
            self.assertEqual(self._named_open("fr_cleanroom_stream_stats"),
                             0, "%s leaked stream stats_fd on failure"
                             % backend)

    def test_exit_127_classification_is_untouched(self):
        """C1/D: whatever the backend, 127 stays outside pre-ingest."""
        st = 127 << 8
        self.assertNotIn(127, _CR_EXIT_PRE_INGEST)
        self.assertFalse(_decode_launcher_status(st)[3])
        self.assertFalse(_cleanroom_may_fallback(st))


class TestCandidateActionAndSignalContract(_Base):
    """D2: inspect what is actually passed to os.posix_spawn()."""

    def _capture_spawn_args(self, shape):
        calls = {}
        real = os.posix_spawn

        def spy(path, argv, env, **kw):
            calls["path"] = path
            calls["argv"] = list(argv)
            calls["env"] = env
            calls["kwargs"] = kw
            return real(path, argv, env, **kw)

        self.addCleanup(setattr, os, "posix_spawn", real)
        os.posix_spawn = spy
        self._use("posix_spawn")
        if shape == "materialized":
            forkrun.map(self.spec, self.corpus, mode="plugin",
                        workers=2, lines=1)
        else:
            gen = forkrun.stream(self.spec, self.corpus, mode="plugin",
                                 workers=2, lines=1, streaming=True)
            try:
                list(gen)
            finally:
                gen.close()
        return calls

    def test_materialized_uses_exactly_one_dup2(self):
        c = self._capture_spawn_args("materialized")
        fa = c["kwargs"].get("file_actions", ())
        self.assertEqual(len(fa), 1,
                         "materialized shape should need exactly one action")
        self.assertEqual(fa[0][0], os.POSIX_SPAWN_DUP2)
        self.assertEqual(fa[0][2], 2,
                         "the DUP2 destination must be fd 2 (stderr)")

    def test_streaming_uses_no_actions(self):
        c = self._capture_spawn_args("streaming")
        self.assertEqual(tuple(c["kwargs"].get("file_actions", ())), (),
                         "streaming shape needs NO actions: every required "
                         "descriptor is already inheritable and rr is "
                         "already FD_CLOEXEC")

    def test_no_signal_or_session_options_are_passed(self):
        for shape in ("materialized", "streaming"):
            c = self._capture_spawn_args(shape)
            for opt in ("setsigdef", "setsigmask", "setpgroup", "setsid",
                        "resetids", "scheduler"):
                self.assertNotIn(opt, c["kwargs"],
                                 "%s passed %s; setsigdef measurably resets "
                                 "an inherited SIG_IGN"
                                 % (shape, opt))

    def test_environment_is_passed_unchanged(self):
        c = self._capture_spawn_args("materialized")
        self.assertIs(c["env"], os.environ,
                      "the candidate must pass the inherited environment "
                      "unchanged -- F7 is separate and out of scope")

    def test_argv_carries_the_real_descriptor_numbers(self):
        c = self._capture_spawn_args("materialized")
        argv = c["argv"]
        for flag in ("--src", "--result", "--stats-fd"):
            self.assertIn(flag, argv)
            val = argv[argv.index(flag) + 1]
            self.assertTrue(val.isdigit() and int(val) > 2,
                            "%s=%s must be a relocated descriptor above 2"
                            % (flag, val))


# The C5 low-FD matrix must run in a SUBPROCESS: it deliberately closes
# fd 0/1/2, which would corrupt this test runner's own stdio.
_LOWFD_SCRIPT = r"""
import os, sys, tempfile
sys.path.insert(0, %(python)r)
os.environ['FORKRUN_CLEANROOM'] = '1'
os.environ['FORKRUN_RETRY_LIMIT'] = '1'
import forkrun
R = sys.modules['forkrun.run']
R._set_cleanroom_launch_backend(%(backend)r)
d = tempfile.mkdtemp()
src = os.path.join(d, 'in.txt')
open(src, 'w').write(''.join('PAYLOAD_%%02d\n' %% i for i in range(8)))
for fd in [int(x) for x in %(close)r.split(',')]:
    try:
        os.close(fd)
    except OSError:
        pass
res = []
try:
    out = forkrun.map(%(spec)r, src, mode='plugin', workers=2, lines=1)
    joined = b''.join(bytes(b) for b in out)
    toks = sorted(set(t for t in joined.split() if t.startswith(b'PAYLOAD')))
    res.append('MAP records=%%d tokens=%%d %%s' %% (
        len(out), len(toks), 'OK' if len(toks) == 8 else 'WRONG'))
except Exception as e:
    res.append('MAP raised %%s: %%s' %% (type(e).__name__, str(e)[:80]))
try:
    g = forkrun.stream(%(spec)r, src, mode='plugin', workers=2, lines=1,
                       streaming=True)
    recs = list(g); g.close()
    joined = b''.join(recs)
    toks = sorted(set(t for t in joined.split() if t.startswith(b'PAYLOAD')))
    res.append('STREAM records=%%d tokens=%%d %%s' %% (
        len(recs), len(toks), 'OK' if len(toks) == 8 else 'WRONG'))
except Exception as e:
    res.append('STREAM raised %%s: %%s' %% (type(e).__name__, str(e)[:80]))
open(%(out)r, 'w').write('\n'.join(res))
"""


@unittest.skipUnless(HAVE_LAUNCHER_STATE, "launcher or substrate unavailable")
class TestClosedStandardDescriptorsAreSafe(_Base):
    """C5: with fd 2 closed the route used to hand the launcher the ERROR
    MEMFD as its source -- a well-formed result computed from the wrong
    bytes, with no error anywhere.

    Each case runs in its own process because it closes fd 0/1/2.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._have = True
        try:
            from forkrun.run import _cleanroom_launcher_path
            cls._have = bool(_cleanroom_launcher_path())
        except Exception:
            cls._have = False
        if cls._have:
            try:
                from forkrun._bindings import find_substrate
                cls._have = bool(find_substrate())
            except Exception:
                cls._have = False
        if not cls._have:
            raise unittest.SkipTest("launcher or substrate not built")

    def _run_lowfd(self, backend, close):
        out = os.path.join(self._tmp, "res_%s_%s.txt" % (backend, close))
        if os.path.exists(out):
            os.unlink(out)
        script = _LOWFD_SCRIPT % {
            "python": os.path.join(_ROOT, "python"),
            "backend": backend, "close": close, "spec": self.spec,
            "out": out,
        }
        proc = subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True, timeout=300)
        if not os.path.exists(out):
            self.fail("low-fd subprocess produced no result for %s/%s\n%s"
                      % (backend, close, proc.stderr[-400:]))
        with open(out) as fh:
            return fh.read()

    def test_fd2_closed_gives_correct_input(self):
        """THE C5 case. Before the fix this produced records, but they
        were computed from the error memfd -- count right, content wrong.
        Asserting only the count would have passed while the corruption
        persisted, so the PAYLOAD tokens are what is checked."""
        for backend in BACKENDS:
            text = self._run_lowfd(backend, "2")
            self.assertIn("MAP records=8 tokens=8 OK", text,
                          "fd 2 closed: %s must still read the real source\n%s"
                          % (backend, text))
            self.assertIn("STREAM records=8 tokens=8 OK", text,
                          "fd 2 closed streaming: %s\n%s" % (backend, text))

    def test_fd0_or_fd1_closed_alone_is_unaffected(self):
        for close in ("0", "1"):
            for backend in BACKENDS:
                text = self._run_lowfd(backend, close)
                self.assertIn("MAP records=8 tokens=8 OK", text,
                              "closing fd %s must not disturb the route "
                              "(%s)\n%s" % (close, backend, text))

    def test_stdout_and_stderr_together(self):
        """Documented, not asserted as correct: with BOTH fd 1 and fd 2
        closed the child has no stdout, and the plugin ABI returns results
        by writing to stdout -- so zero records is the honest outcome. The
        pre-fix behaviour here was ACCIDENTALLY correct (the result memfd
        happened to occupy fd 1 and stdout pointed into it), which is worse:
        it depended on a descriptor-number coincidence."""
        import re
        for backend in BACKENDS:
            text = self._run_lowfd(backend, "1,2")
            m = re.search(r"MAP records=(\d+) tokens=(\d+)", text)
            self.assertIsNotNone(m, "no MAP line: %s\n%s" % (backend, text))
            self.assertEqual(
                m.group(1), "0",
                "with fd 1 and fd 2 both closed the child has no stdout, and "
                "the plugin ABI returns results by writing there -- so the "
                "materialized route must return ZERO records rather than "
                "invent some. Got records=%s (%s)\n%s"
                % (m.group(1), backend, text))


class TestFdRelocationHelper(_Base):
    """Direct tests of _fd_above_stdio.

    The route-level tests could NOT catch a dropped inheritable re-apply,
    because that mutation makes a relocated descriptor MORE permissive
    rather than broken: `os.dup` clears FD_CLOEXEC, so skipping the
    re-apply turns a close-on-exec descriptor into an inheritable one that
    silently crosses exec. Nothing observable fails -- it is a quiet leak
    in the wrong direction, and only a direct assertion finds it.
    """

    def _cloexec_fd(self):
        fd = os.memfd_create("reloc_probe")
        os.set_inheritable(fd, False)
        return fd

    # A descriptor only gets a number <= 2 if a standard stream is closed
    # first, and closing one in THIS process would corrupt the runner. So
    # both checks run in a subprocess that closes fd 2 and then allocates.
    _RELOC_SCRIPT = r"""
import os, sys
sys.path.insert(0, %(python)r)
from forkrun.run import _fd_above_stdio
out = []
for want_inheritable in (False, True):
    # The relocation helper CLOSES the original, so after the first
    # iteration fd 2 is already free and a bare close(2) would raise
    # EBADF and kill the script before it writes anything.
    try:
        os.close(2)
    except OSError:
        pass
    fd = os.memfd_create('reloc')
    os.set_inheritable(fd, want_inheritable)
    before = os.get_inheritable(fd)
    new = _fd_above_stdio(fd)
    out.append('%%d %%d %%d %%d' %% (fd, new, int(before),
                                    int(os.get_inheritable(new))))
open(%(out)r, 'w').write('\n'.join(out))
"""

    def _reloc(self, want_inheritable):
        out = os.path.join(self._tmp, "reloc.txt")
        if os.path.exists(out):
            os.unlink(out)
        script = self._RELOC_SCRIPT % {
            "python": os.path.join(_ROOT, "python"), "out": out}
        proc = subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True, timeout=120)
        self.assertTrue(os.path.exists(out),
                        "relocation subprocess produced nothing: %s"
                        % proc.stderr[-300:])
        with open(out) as fh:
            rows = [line.split() for line in fh.read().split("\n") if line]
        fd, new, before, after = (int(x) for x in rows[want_inheritable])
        return fd, new, bool(before), bool(after)

    def test_preserves_close_on_exec_state(self):
        """A close-on-exec descriptor must NOT become inheritable merely
        by being relocated. os.dup() clears FD_CLOEXEC, so without the
        re-apply this flips -- and nothing observable fails, because the
        descriptor simply crosses exec when it must not."""
        fd, new, before, after = self._reloc(False)
        self.assertTrue(new > 2, "expected relocation above 2, got %d" % new)
        self.assertFalse(before, "precondition: fd %d was close-on-exec" % fd)
        self.assertFalse(after,
                         "a close-on-exec descriptor became INHERITABLE "
                         "after relocation; it would now cross exec when it "
                         "must not")

    def test_preserves_inheritable_state(self):
        """The opposite direction: an inheritable descriptor must stay
        inheritable, or it would stop reaching the launcher."""
        fd, new, before, after = self._reloc(True)
        self.assertTrue(new > 2, "expected relocation above 2, got %d" % new)
        self.assertTrue(before, "precondition: fd %d was inheritable" % fd)
        self.assertTrue(after,
                        "an inheritable descriptor became close-on-exec "
                        "after relocation; the launcher would never see it")

    def test_only_relocates_when_at_or_below_stdio(self):
        high = os.memfd_create("reloc_high")
        self.addCleanup(os.close, high)
        self.assertEqual(_R._fd_above_stdio(high), high,
                         "a descriptor already above 2 must be returned "
                         "unchanged, not churned")

    def test_relocation_shares_the_same_open_file(self):
        """dup() shares the open file description, so the caller keeps a
        valid descriptor to the same bytes -- relocating the route's copy
        must not damage or invalidate the caller's own."""
        path = os.path.join(self._tmp, "shared.txt")
        with open(path, "wb") as fh:
            fh.write(b"SHARED-PAYLOAD")
        caller_fd = os.open(path, os.O_RDONLY)
        self.addCleanup(os.close, caller_fd)
        new = _R._fd_above_stdio(caller_fd)
        if new != caller_fd:
            self.addCleanup(os.close, new)
        os.lseek(new, 0, os.SEEK_SET)
        self.assertEqual(os.read(new, 32), b"SHARED-PAYLOAD")
        os.lseek(caller_fd, 0, os.SEEK_SET)
        self.assertEqual(os.read(caller_fd, 32), b"SHARED-PAYLOAD",
                         "the caller's descriptor must remain usable after "
                         "the route relocates its copy")
        # NB: an earlier draft of this test used os.dup2(caller_fd, 2) to
        # force a low descriptor number. That clobbered the TEST RUNNER's
        # stderr and silently swallowed every subsequent line of output --
        # the same hazard C5 is about, committed inside a test for it. The
        # number a descriptor gets is not something this test needs to
        # control; what it needs to assert is that relocation does not
        # damage the caller, and that is asserted above.


if __name__ == "__main__":
    unittest.main()