"""Cleanroom parent-side descriptor LIFECYCLE (F6 Stage 2C).

WHAT THIS PINS
--------------
Two parent-owned descriptors leaked on every cleanroom call:

* `_execute_cleanroom` created `errfd` (a memfd for the launcher's
  stderr) and never closed it. `_read_launcher_stderr()` opens with
  `closefd=False`, so the diagnostic read does not close it either.
* `_execute_cleanroom_stream` created `stats_fd` and read it on the
  success path but never closed it, so success, every failure raise, the
  `strict_poison` raise, and GENERATOR ABANDONMENT each leaked one.

Both were measured growing linearly (1, 2, 3, ... named memfds after
1, 2, 3 calls) before the fix and flat after.

HOW IT MEASURES
---------------
By counting `/proc/self/fd` entries whose readlink target contains the
specific memfd NAME. Naming rather than counting is deliberate: the test
process holds many unrelated descriptors, and a raw count would be noise.
The names are the literals in `run.py`, so this observes the real
descriptors the real launch functions created.

It exercises the PRODUCTION launch functions through the public API. It
does not re-implement their cleanup, and it does not mock `os.close` --
a test that copied the cleanup logic would pass whether or not the
production code closed anything.

The exec-failure cases patch `_cleanroom_launcher_path` to point at a
TEMPORARY NON-EXECUTABLE file. The real build artifact's mode is never
changed, so a failing test cannot leave the checkout broken.
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

ERR_MEMFD = "fr_cleanroom_err"            # run.py: _execute_cleanroom
STREAM_STATS_MEMFD = "fr_cleanroom_stream_stats"   # _execute_cleanroom_stream


FIXTURE_PLUGIN_C = (
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


def open_named(pattern):
    """Count open descriptors whose /proc/self/fd target contains `pattern`."""
    n = 0
    try:
        entries = os.listdir("/proc/self/fd")
    except OSError:
        return 0
    for fd in entries:
        try:
            target = os.readlink("/proc/self/fd/%s" % fd)
        except OSError:
            continue                      # the listdir fd itself, etc.
        if pattern in target:
            n += 1
    return n


class _FdLifecycleBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("gcc"):
            raise unittest.SkipTest("gcc absent; the cleanroom plugin "
                                    "fixture cannot be built")
        cls._tmp = tempfile.mkdtemp(prefix="fdlife-")
        src = os.path.join(cls._tmp, "plugin.c")
        with open(src, "w") as fh:
            # Signature MUST match the engine dispatch: (argc, argv, ctx).
            # A one-argument form does not fail loudly -- the run
            # "succeeds" with zero records, which reads like a broken
            # lifecycle fix rather than a broken fixture.
            fh.write(FIXTURE_PLUGIN_C)
        cls.so = os.path.join(cls._tmp, "copy.so")
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

        # A non-executable stand-in for the launcher. Existence satisfies
        # the preflight; execv then fails, which is the failure we want.
        cls.fake = os.path.join(cls._tmp, "not_a_launcher")
        with open(cls.fake, "w") as fh:
            fh.write("#!/bin/sh\nexit 0\n")
        os.chmod(cls.fake, 0o644)

        cls.corpus = os.path.join(cls._tmp, "in.txt")
        with open(cls.corpus, "w") as fh:
            for i in range(16):
                fh.write("line%03d\n" % i)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        for name in ("FORKRUN_CLEANROOM", "FORKRUN_RETRY_LIMIT",
                     "FORKRUN_NO_UDF", "FRK_POISON_FD"):
            self.addCleanup(self._restore, name, os.environ.get(name))
            os.environ.pop(name, None)
        os.environ["FORKRUN_CLEANROOM"] = "1"      # exercise the launcher
        os.environ["FORKRUN_RETRY_LIMIT"] = "1"

    @staticmethod
    def _restore(name, value):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def _map_ok(self):
        return forkrun.map(self.spec, self.corpus, mode="plugin",
                           workers=2, lines=1)

    def _stream_all(self):
        gen = forkrun.stream(self.spec, self.corpus, mode="plugin",
                             workers=2, lines=1, streaming=True)
        try:
            return list(gen)
        finally:
            try:
                gen.close()
            except Exception:
                pass

    def _stream_abandon(self):
        gen = forkrun.stream(self.spec, self.corpus, mode="plugin",
                             workers=2, lines=1, streaming=True)
        it = iter(gen)
        next(it, None)
        gen.close()

    def _map_exec_fail(self):
        """Point the resolver at a non-executable file. Patches the
        MODULE attribute -- `from forkrun import run` yields the frontend
        FUNCTION, which shadows the submodule, so patching that object
        silently does nothing and the real launcher runs instead."""
        R = sys.modules["forkrun.run"]
        self.addCleanup(setattr, R, "_cleanroom_launcher_path",
                        R._cleanroom_launcher_path)
        R._cleanroom_launcher_path = lambda: self.fake
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return forkrun.map(self.spec, self.corpus, mode="plugin",
                               workers=2, lines=1)


class TestMaterializedErrfdLifecycle(_FdLifecycleBase):
    def test_errfd_does_not_accumulate_on_success(self):
        self.assertEqual(open_named(ERR_MEMFD), 0, "precondition: clean")
        for i in range(1, 6):
            self._map_ok()
            self.assertEqual(
                open_named(ERR_MEMFD), 0,
                "after %d successful map() call(s) an %r descriptor is "
                "still open -- errfd is created per launch and never "
                "closed" % (i, ERR_MEMFD))

    def test_errfd_does_not_accumulate_on_exec_failure(self):
        self.assertEqual(open_named(ERR_MEMFD), 0)
        raised = 0
        for i in range(1, 4):
            with self.assertRaises(RuntimeError,
                                   msg="exit-127 path must still raise"):
                self._map_exec_fail()
            raised += 1
            self.assertEqual(
                open_named(ERR_MEMFD), 0,
                "after %d failed map() call(s) an %r descriptor is still "
                "open" % (i, ERR_MEMFD))
        self.assertEqual(raised, 3)


class TestStreamingStatsFdLifecycle(_FdLifecycleBase):
    def test_stats_fd_does_not_accumulate_on_success(self):
        self.assertEqual(open_named(STREAM_STATS_MEMFD), 0, "precondition")
        for i in range(1, 6):
            self._stream_all()
            self.assertEqual(
                open_named(STREAM_STATS_MEMFD), 0,
                "after %d successful stream() call(s) a %r descriptor is "
                "still open" % (i, STREAM_STATS_MEMFD))

    def test_stats_fd_does_not_accumulate_on_exec_failure(self):
        R = sys.modules["forkrun.run"]
        self.addCleanup(setattr, R, "_cleanroom_launcher_path",
                        R._cleanroom_launcher_path)
        R._cleanroom_launcher_path = lambda: self.fake
        for i in range(1, 4):
            with self.assertRaises(RuntimeError,
                                   msg="stream truncation path must raise"):
                self._stream_all()
            self.assertEqual(
                open_named(STREAM_STATS_MEMFD), 0,
                "after %d failed stream() call(s) a %r descriptor is still "
                "open" % (i, STREAM_STATS_MEMFD))

    def test_stats_fd_does_not_accumulate_on_abandonment(self):
        """Abandoning mid-stream takes the generator's finally, not the
        normal completion path -- a distinct exit that leaked separately.
        """
        for i in range(1, 4):
            self._stream_abandon()
            self.assertEqual(
                open_named(STREAM_STATS_MEMFD), 0,
                "after %d ABANDONED stream() a %r descriptor is still open"
                % (i, STREAM_STATS_MEMFD))


class TestOtherRouteDescriptorsAreNotDisturbed(_FdLifecycleBase):
    """The fix must not have closed something it should not have."""

    def test_materialized_result_and_stats_are_still_consumed(self):
        """If res_fd or stats_fd were closed early, this would yield an
        empty or corrupt result rather than the expected records."""
        out = self._map_ok()
        self.assertEqual(len(out), 16,
                         "materialized result collection must still work")

    def test_streaming_still_yields_all_records(self):
        out = self._stream_all()
        self.assertEqual(len(out), 16,
                         "streaming delivery must still work")

    def test_no_general_fd_growth(self):
        """Belt and braces: no descriptor of ANY kind should accumulate
        across repeated cleanroom calls, not just the two named ones."""
        def total():
            try:
                return len(os.listdir("/proc/self/fd"))
            except OSError:
                return -1
        self._map_ok()
        self._stream_all()
        before = total()
        for _ in range(4):
            self._map_ok()
            self._stream_all()
        after = total()
        self.assertLessEqual(
            after, before,
            "total open descriptors grew from %d to %d across 4 map + "
            "4 stream cleanroom calls" % (before, after))


if __name__ == "__main__":
    unittest.main()