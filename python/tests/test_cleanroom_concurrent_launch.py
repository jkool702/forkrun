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
                              workers=2, lines=64)
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

        try:
            return self._run_threads(fn, threads)
        finally:
            _RUN._set_cleanroom_launch_backend("forkexec")

    def test_concurrent_map_with_posix_spawn(self):
        self._one("posix_spawn")

    def test_concurrent_map_with_forkexec(self):
        self._one("forkexec")

    def test_concurrent_mixed_backend_selection_is_one_or_other(self):
        """Switching the private selector mid-flight must never yield a
        half-configured state (e.g. spawn with fork actions or vice versa)."""
        _RUN._set_cleanroom_launch_backend("posix_spawn")
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
                                  workers=2, lines=64)
                with lock:
                    seen.append(len(out))

            flip = threading.Thread(target=flipper, daemon=True)
            flip.start()
            try:
                self._run_threads(launcher, 4)
            finally:
                stop.set()
                flip.join(timeout=30)
            self.assertTrue(seen, "no launches completed")
            for count in seen:
                self.assertEqual(count, 8)
        finally:
            _RUN._set_cleanroom_launch_backend("forkexec")


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

        try:
            return self._run_threads(fn, threads)
        finally:
            _RUN._set_cleanroom_launch_backend("forkexec")

    def test_concurrent_stream_with_posix_spawn(self):
        self._one("posix_spawn")

    def test_concurrent_stream_with_forkexec(self):
        self._one("forkexec")


class TestRepeatedLaunchDoesNotLeakDescriptors(_ConcurrentBase):
    """Relocation adds an F_DUPFD per descriptor; each must be closed."""

    def _fd_count(self):
        return len(os.listdir("/proc/self/fd"))

    def _one(self, backend, rounds=12):
        _RUN._set_cleanroom_launch_backend(backend)
        path = _corpus(self._tmp, "leak")
        # Warm up so one-off allocations are not counted as growth.
        forkrun.map(self.spec, path, mode="plugin", workers=2, lines=64)
        before = self._fd_count()
        for _ in range(rounds):
            out = forkrun.map(self.spec, path, mode="plugin",
                              workers=2, lines=64)
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
        _RUN._set_cleanroom_launch_backend("posix_spawn")
        path = _corpus(self._tmp, "leakstream")
        try:
            for _ in range(3):
                list(forkrun.stream(self.spec, path, streaming=True,
                                    mode="plugin", workers=2, lines=64,
                                    nodes=1, output="bytes"))
            before = self._fd_count()
            for _ in range(8):
                list(forkrun.stream(self.spec, path, streaming=True,
                                    mode="plugin", workers=2, lines=64,
                                    nodes=1, output="bytes"))
            after = self._fd_count()
            self.assertLessEqual(
                after, before + 2,
                "streaming descriptor count grew from %d to %d" % (before, after))
        finally:
            _RUN._set_cleanroom_launch_backend("forkexec")


if __name__ == "__main__":
    unittest.main()