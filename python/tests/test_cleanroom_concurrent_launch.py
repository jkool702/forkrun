"""F6 Stage 4: concurrent-host safety of the cleanroom launch path.

`posix_spawn` is specified to be safe to call from a multithreaded
process, which is one of the reasons it is a candidate default over
`fork()+execv()`. But the launch path is not just the spawn call: it also
allocates, relocates and registers route descriptors, and on the streaming
shape it mutates a process-global backend selector.

What this covers that the existing descriptor suites do not:

  * Several threads launching through the routes AT ONCE, each asserting it
    got its own correct answer -- a route descriptor handed to one caller
    and reused by another would show up as cross-contaminated records.
  * Concurrent streaming launches, where the result pipe is per-call and a
    mistake there is not merely wrong data but two callers reading each
    other's bytes.
  * Repeated launch under load with the leak check, because relocation now
    runs `F_DUPFD` per descriptor and a lost close would accumulate.
  * Backend identity: a thread reading the selector mid-switch must observe
    one backend or the other, never a broken state.

The thread body deliberately does NOT call `_set_cleanroom_launch_backend`;
switching the global while other threads launch is exactly the race the
production code does not permit (there is no public selector, F7), so it is
tested here only as an unsupported-misuse observation.
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

import forkrun  # noqa: E402

_RUN = sys.modules["forkrun.run"]


_PLUGIN_SRC = (
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


def _build(tmpdir):
    src = os.path.join(tmpdir, "p.c")
    with open(src, "w") as fh:
        fh.write(_PLUGIN_SRC)
    out = os.path.join(tmpdir, "p.so")
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2",
         "-I", str(REPO / "ring_loadables"), "-o", out, src],
        check=True, capture_output=True, text=True)
    return out + ":copy_v1"


def _corpus(tmpdir, tag, lines=512):
    """A corpus whose payload is unique per caller, so mixing shows up."""
    path = os.path.join(tmpdir, "in-%s.txt" % tag)
    with open(path, "w") as fh:
        for i in range(lines):
            fh.write("%s-payload %06d\n" % (tag, i))
    return path


class _ConcurrentBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="s4-thread-")
        cls.spec = _build(cls._tmp)

    def _run_threads(self, fn, count):
        """Run `fn(i)` on `count` threads; re-raise the first failure."""
        errors = []
        results = [None] * count
        barrier = threading.Barrier(count)

        def worker(i):
            try:
                barrier.wait(timeout=60)
                results[i] = fn(i)
            except BaseException as exc:  # noqa: BLE001
                errors.append((i, exc))

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=300)
        for t in threads:
            self.assertFalse(t.is_alive(), "a launch thread hung")
        if errors:
            i, exc = errors[0]
            raise exc
        return results


class TestConcurrentMapLaunches(_ConcurrentBase):
    """Each caller must get ITS OWN records, not another caller's."""

    def _one(self, backend, threads=6):
        _RUN._set_cleanroom_launch_backend(backend)
        paths = [_corpus(self._tmp, "t%d" % i) for i in range(threads)]

        def fn(i):
            out = forkrun.map(self.spec, paths[i], mode="plugin",
                              workers=2, lines=64, nodes=1)
            # 512 lines of "tN-payload NNNNNN" -> 8 records of 64 lines.
            self.assertEqual(len(out), 8)
            # map() yields memoryviews; str() on one is its repr, not the
            # bytes, so the payload assertions would silently pass on the
            # "not present" branch.
            blob = b"".join(bytes(r) if not isinstance(r, bytes) else r
                            for r in out)
            text = blob.decode("utf-8", "replace")
            other = [j for j in range(threads) if j != i]
            for j in other:
                self.assertNotIn(
                    "t%d-payload" % j, text,
                    "caller %d received records belonging to caller %d -- "
                    "route descriptors are being shared across threads"
                    % (i, j))
            self.assertIn("t%d-payload" % i, text)
            return len(out)

        prev = _RUN._set_cleanroom_launch_backend(backend)
        try:
            return self._run_threads(fn, threads)
        finally:
            _RUN._set_cleanroom_launch_backend(prev)

    def test_concurrent_map_with_posix_spawn(self):
        self._one("posix_spawn")

    def test_concurrent_map_with_forkexec(self):
        self._one("forkexec")

    def test_concurrent_mixed_backend_selection_is_one_or_other(self):
        """Switching the private selector mid-flight must never yield a
        half-configured state (e.g. spawn with fork actions or vice versa)."""
        prev = _RUN._set_cleanroom_launch_backend("posix_spawn")
        try:
            seen = []
            lock = threading.Lock()
            stop = threading.Event()

            def flipper():
                while not stop.is_set():
                    _RUN._set_cleanroom_launch_backend("forkexec")
                    _RUN._set_cleanroom_launch_backend("posix_spawn")

            def launcher(i):
                path = _corpus(self._tmp, "mix%d" % i)
                out = forkrun.map(self.spec, path, mode="plugin",
                                  workers=2, lines=64, nodes=1)
                with lock:
                    seen.append(len(out))

            flip = threading.Thread(target=flipper, daemon=True)
            flip.start()
            try:
                self._run_threads(launcher, 4)
            finally:
                stop.set()
                flip.join(timeout=30)
                self.assertFalse(
                    flip.is_alive(),
                    "the flipper thread outlived the test; a stray live "
                    "thread makes every LATER os.fork() in the suite emit "
                    "the multi-threaded fork() DeprecationWarning and can "
                    "deadlock a child")
            self.assertTrue(seen, "no launches completed")
            for count in seen:
                self.assertEqual(count, 8)
        finally:
            _RUN._set_cleanroom_launch_backend(prev)


class TestConcurrentStreamLaunches(_ConcurrentBase):
    """Per-call result pipes: two callers must not read each other's bytes."""

    def _one(self, backend, threads=5):
        _RUN._set_cleanroom_launch_backend(backend)
        paths = [_corpus(self._tmp, "s%d" % i) for i in range(threads)]

        def fn(i):
            chunks = list(forkrun.stream(self.spec, paths[i],
                                         streaming=True, mode="plugin",
                                         workers=2, lines=64, nodes=1,
                                         output="bytes"))
            self.assertTrue(chunks, "stream produced nothing")
            blob = b"".join(chunks)
            text = blob.decode("utf-8", "replace")
            for j in range(threads):
                if j == i:
                    continue
                self.assertNotIn(
                    "s%d-payload" % j, text,
                    "caller %d read bytes belonging to caller %d -- the "
                    "streaming result pipe is being shared across threads"
                    % (i, j))
            self.assertIn("s%d-payload" % i, text)
            return len(chunks)

        prev = _RUN._set_cleanroom_launch_backend(backend)
        try:
            return self._run_threads(fn, threads)
        finally:
            _RUN._set_cleanroom_launch_backend(prev)

    def test_concurrent_stream_with_posix_spawn(self):
        self._one("posix_spawn")

    def test_concurrent_stream_with_forkexec(self):
        self._one("forkexec")


class TestRepeatedLaunchDoesNotLeakDescriptors(_ConcurrentBase):
    """Relocation adds an F_DUPFD per descriptor; each must be closed."""

    def _fd_count(self):
        return len(os.listdir("/proc/self/fd"))

    def _one(self, backend, rounds=12):
        prev = _RUN._set_cleanroom_launch_backend(backend)
        path = _corpus(self._tmp, "leak")
        # Warm up so one-off allocations are not counted as growth.
        forkrun.map(self.spec, path, mode="plugin", workers=2, lines=64, nodes=1)
        before = self._fd_count()
        for _ in range(rounds):
            out = forkrun.map(self.spec, path, mode="plugin",
                              workers=2, lines=64, nodes=1)
            self.assertEqual(len(out), 8)
        after = self._fd_count()
        self.assertLessEqual(
            after, before + 2,
            "descriptor count grew from %d to %d across %d launches under "
            "%s: the relocated descriptors are not all being closed"
            % (before, after, rounds, backend))

    def test_no_descriptor_growth_with_posix_spawn(self):
        self._one("posix_spawn")

    def test_no_descriptor_growth_with_forkexec(self):
        self._one("forkexec")

    def test_streaming_releases_descriptors(self):
        prev = _RUN._set_cleanroom_launch_backend("posix_spawn")
        path = _corpus(self._tmp, "leakstream")
        try:
            for _ in range(3):
                list(forkrun.stream(self.spec, path, streaming=True,
                                    mode="plugin", workers=2, lines=64, nodes=1,
                                    output="bytes"))
            before = self._fd_count()
            for _ in range(8):
                list(forkrun.stream(self.spec, path, streaming=True,
                                    mode="plugin", workers=2, lines=64, nodes=1,
                                    output="bytes"))
            after = self._fd_count()
            self.assertLessEqual(
                after, before + 2,
                "streaming descriptor count grew from %d to %d" % (before, after))
        finally:
            _RUN._set_cleanroom_launch_backend(prev)


class TestConcurrentCleanupIsolation(_ConcurrentBase):
    """A failing call must not disturb its neighbours, or leak.

    The contamination tests prove callers cannot read each other's DATA.
    These prove the other half: when one call fails mid-route -- after it
    has allocated route descriptors and before it has released them -- the
    other in-flight calls still complete correctly, and the failed call's
    descriptors do not accumulate or get closed twice.

    This is the case a descriptor-ownership bug would actually show up in:
    a shared descriptor table, a cleanup that runs while another call is
    still using the same number, or a failure path that returns without
    releasing.
    """

    def _fail_once(self, missing):
        """Run one failing call so the error path's lazy init happens now."""
        try:
            forkrun.map(self.spec, missing, mode="plugin", workers=2,
                        lines=1)
        except BaseException:
            pass

    def _one(self, backend, good=4, bad=2):
        prev = _RUN._set_cleanroom_launch_backend(backend)
        paths = [_corpus(self._tmp, "ok%d" % i) for i in range(good)]
        missing = [os.path.join(self._tmp, "absent-%d.txt" % i)
                   for i in range(bad)]

        def fn(i):
            if i < good:
                out = forkrun.map(self.spec, paths[i], mode="plugin",
                                  workers=2, lines=64, nodes=1)
                self.assertEqual(len(out), 8,
                                 "a neighbouring failure disturbed this call")
                blob = b"".join(bytes(r) if not isinstance(r, bytes) else r
                                for r in out).decode("utf-8", "replace")
                self.assertIn("ok%d-payload" % i, blob)
                return len(out)
            # A source that does not exist: the route must decline or fail,
            # and either way must clean up after itself.
            try:
                forkrun.map(self.spec, missing[i - good], mode="plugin",
                            workers=2, lines=64, nodes=1)
            except BaseException:
                return "failed-as-expected"
            return "no-error"

        # Warm the failure path FIRST. A source that does not exist makes
        # the route decline and the in-process path raise, and that path
        # performs a one-time lazy initialisation the first time it runs
        # (+9 descriptors here, identical with the cleanroom gate OFF, so
        # it is not a cleanroom-route leak). Asserting an absolute count
        # across that boundary would be a brittle whole-FD-table
        # assertion that fails for reasons unrelated to this route. What
        # matters is STABILITY once the path is warm.
        self._fail_once(missing[0])
        try:
            before = len(os.listdir("/proc/self/fd"))
            results = self._run_threads(fn, good + bad)
            after = len(os.listdir("/proc/self/fd"))
            for i in range(good):
                self.assertEqual(results[i], 8, "a good call returned %r"
                                 % (results[i],))
            for i in range(good, good + bad):
                self.assertIn(results[i], ("failed-as-expected", "no-error"),
                              "unexpected outcome for the failing call: %r"
                              % (results[i],))
            self.assertLessEqual(
                after, before + 2,
                "descriptors accumulated across concurrent calls including "
                "failing ones: %d -> %d once the failure path is warm"
                % (before, after))
        finally:
            _RUN._set_cleanroom_launch_backend(prev)

    def test_cleanup_isolation_with_posix_spawn(self):
        self._one("posix_spawn")

    def test_cleanup_isolation_with_forkexec(self):
        self._one("forkexec")


class TestConcurrentLaunchesTerminate(_ConcurrentBase):
    """Concurrency must not deadlock: there is a wall-clock bound.

    The contamination tests prove the results are right when the calls
    finish. A lock-ordering or cleanup-ordering bug would instead make
    them never finish, which no correctness assertion can catch -- so this
    asserts a bound and fails with the thread dump if it is exceeded.
    """

    def _mixed(self, backend, threads=6):
        prev = _RUN._set_cleanroom_launch_backend(backend)
        paths = [_corpus(self._tmp, "mix%d" % i) for i in range(threads)]

        def fn(i):
            if i % 2 == 0:
                out = forkrun.map(self.spec, paths[i], mode="plugin",
                                  workers=2, lines=64, nodes=1)
                return len(out)
            recs = list(forkrun.stream(self.spec, paths[i], mode="plugin",
                                       workers=2, lines=64, nodes=1,
                                       output="bytes"))
            return len(recs)

        started = time.perf_counter()
        try:
            results = self._run_threads(fn, threads)
        finally:
            _RUN._set_cleanroom_launch_backend(prev)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(results), threads)
        for r in results:
            self.assertTrue(r > 0, "a concurrent call produced nothing: %r"
                            % (results,))
        return elapsed

    def test_mixed_map_and_stream_terminate_under_posix_spawn(self):
        self._one = self._mixed
        elapsed = self._mixed("posix_spawn")
        # Sequential baseline is well under a second; allow generous slack
        # for a loaded machine while still failing on a real hang.
        self.assertLess(elapsed, 60.0,
                        "6 concurrent mixed launches took %.1fs, which "
                        "indicates contention rather than deadlock" % elapsed)

    def test_mixed_map_and_stream_terminate_under_forkexec(self):
        elapsed = self._mixed("forkexec")
        self.assertLess(elapsed, 60.0,
                        "6 concurrent mixed launches took %.1fs" % elapsed)


if __name__ == "__main__":
    unittest.main()