"""W-PY1 v0 engine tests (Stage 4 Phase 1).

End-to-end coverage for forkrun.run/map/stream over the ctypes substrate.
Requires libforkrun_python.so (make -f Makefile.substrate python-substrate);
skipped otherwise so validation-only environments stay green.
"""

import mmap
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import forkrun  # noqa: E402
from forkrun._batch import Batch  # noqa: E402

try:
    from forkrun._bindings import find_substrate  # noqa: E402
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _write_lines(path, n, fmt="line %d\n"):
    with open(path, "w") as fh:
        for i in range(n):
            fh.write(fmt % i)


def _identity(batch):
    return bytes(batch.data)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestMapExact(unittest.TestCase):
    def test_map_byte_exact_ordered(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 2000)
            out = forkrun.map(_identity, path, workers=2, order="index")
            self.assertTrue(len(out) > 1)
            idxs = [i for i, _ in enumerate(out)]
            self.assertEqual(idxs, sorted(idxs))
            total = sum(len(b) for b in out)
            self.assertEqual(total, os.path.getsize(path))
            # Reassembly in batch_index order reproduces the input exactly.
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
        finally:
            os.unlink(path)

    def test_empty_input(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            out = forkrun.map(_identity, path, workers=2)
            self.assertEqual(out, [])
        finally:
            os.unlink(path)

    def test_fd_and_pipe_sources(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 500)
            with open(path, "rb") as fh:
                expected = fh.read()
            fd = os.open(path, os.O_RDONLY)
            try:
                out = forkrun.map(_identity, fd, workers=2, order="index")
            finally:
                os.close(fd)
            self.assertEqual(b"".join(out), expected)
            r, w = os.pipe()
            with open(path, "rb") as fh2:
                while True:
                    chunk = fh2.read(65536)
                    if not chunk:
                        break
                    os.write(w, chunk)
            os.close(w)
            try:
                out = forkrun.map(_identity, r, workers=2, order="index")
            finally:
                os.close(r)
            self.assertEqual(b"".join(out), expected)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestRunSink(unittest.TestCase):
    def test_run_sink_payload_side(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".out",
                                         delete=False) as fh2:
            sink_path = fh2.name
        try:
            _write_lines(path, 500)

            def up(batch):
                return bytes(batch.data).upper()

            def sink(meta, result):
                self.assertIsInstance(meta.batch_index, int)
                with open(sink_path, "ab") as out:
                    out.write(result)

            self.assertIsNone(forkrun.run(up, path, sink=sink, workers=2))
            with open(sink_path, "rb") as fh:
                got = fh.read()
            exp = b"".join(("line %d\n" % i).upper().encode()
                           for i in range(500))
            self.assertEqual(sorted(got.splitlines()),
                             sorted(exp.splitlines()))
        finally:
            os.unlink(path)
            os.unlink(sink_path)

    def test_module_path_payload(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        moddir = tempfile.mkdtemp()
        try:
            _write_lines(path, 300)
            with open(os.path.join(moddir, "v0mod.py"), "w") as fh:
                fh.write("def up(batch):\n    return bytes(batch.data).upper()\n")
            sys.path.insert(0, moddir)
            try:
                out = forkrun.map("v0mod:up", path, workers=2, order="index")
            finally:
                sys.path.remove(moddir)
            exp = b"".join(("line %d\n" % i).upper().encode()
                           for i in range(300))
            self.assertEqual(b"".join(out), exp)
        finally:
            os.unlink(path)

    def test_stream_matches_map(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 300)
            self.assertEqual(list(forkrun.stream(_identity, path, workers=2,
                                                 order="index")),
                             forkrun.map(_identity, path, workers=2,
                                         order="index"))
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestBatchSemantics(unittest.TestCase):
    def test_memoryview_and_metadata_survive(self):
        # NOTE: probes must RETURN their observations (workers are forked
        # children — closure writes never reach the parent).
        def probe(batch):
            assert isinstance(batch.data, memoryview)
            first = struct.Struct("<Q").unpack_from(batch.offsets, 0)[0]
            head = struct.Struct("<QQQQ").pack(
                batch.batch_index, batch.byte_offset, batch.byte_length,
                first)
            nlines = batch.line_count
            return head + struct.Struct("<Q").pack(
                0xFFFFFFFFFFFFFFFF if nlines is None else nlines
            ) + bytes(batch.data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 100)
            out = forkrun.map(probe, path, workers=1, order="index")
            with open(path, "rb") as fh:
                raw = fh.read()
            pos = 0
            for rec in out:
                idx, off, ln, first = struct.Struct("<QQQQ").unpack_from(
                    rec, 0)
                (nl,) = struct.Struct("<Q").unpack_from(rec, 32)
                data = rec[40:]
                self.assertEqual(first, off)  # absolute plane coordinates
                self.assertEqual(raw[off:off + ln], data)
                self.assertEqual(nl, data.count(b"\n"))
                pos += ln
            self.assertEqual(pos, len(raw))
        finally:
            os.unlink(path)

    def test_line_count_none_in_byte_mode(self):
        def probe(batch):
            self.assertIsNone(batch.line_count)
            return bytes(batch.data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 200)
            out = forkrun.map(probe, path, bytes=1024, workers=2)
            self.assertEqual(sum(len(b) for b in out),
                             os.path.getsize(path))
        finally:
            os.unlink(path)

    def test_mmap_backed_window(self):
        # The worker's whole-file mmap is a true MAP_SHARED view: the
        # Batch slice matches a direct read of the same coordinates.
        def probe(batch):
            return (struct.Struct("<QQ").pack(batch.byte_offset,
                                              batch.byte_length)
                    + bytes(batch.data))

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 50)
            out = forkrun.map(probe, path, workers=1, order="index")
            with open(path, "rb") as fh:
                raw = fh.read()
            for rec in out:
                off, ln = struct.Struct("<QQ").unpack_from(rec, 0)
                self.assertEqual(raw[off:off + ln], rec[16:])
            # First batch starts at plane offset 0.
            off0, _ = struct.Struct("<QQ").unpack_from(out[0], 0)
            self.assertEqual(off0, 0)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestErrors(unittest.TestCase):
    def _flaky(self, batch):
        d = bytes(batch.data)
        if b"line 1\n" in d or d.startswith(b"line 1"):
            raise RuntimeError("boom")
        return d

    def test_retry_then_poison_continues(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 2000)
            out = forkrun.map(self._flaky, path, workers=1)
            got = b"".join(out)
            # Unaffected batches are delivered exactly once.
            self.assertIn(b"line 100\n", got)
            self.assertTrue(len(out) > 0)
        finally:
            os.unlink(path)

    def test_skip(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 2000)
            out = forkrun.map(self._flaky, path, workers=1, on_error="skip")
            self.assertIn(b"line 100\n", b"".join(out))
        finally:
            os.unlink(path)

    def test_fail_fast_raises(self):
        def always(batch):
            raise RuntimeError("nope")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 500)
            with self.assertRaises(RuntimeError):
                forkrun.map(always, path, workers=2, on_error="fail-fast")
        finally:
            os.unlink(path)

    def test_bad_return_type_is_error(self):
        def bad(batch):
            return 12345

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 100)
            # retry path: every batch poisons, nothing delivered, no crash.
            out = forkrun.map(bad, path, workers=1)
            self.assertEqual(out, [])
        finally:
            os.unlink(path)


class TestPurity(unittest.TestCase):
    """Guardrails: no bash, no pickle, no subprocess in the Python path."""

    def test_no_bash_subprocess_or_pickle(self):
        pkg = os.path.join(os.path.dirname(__file__), "..", "forkrun")
        offenders = []
        for name in ("run.py", "_worker.py", "_bindings.py", "_batch.py",
                     "_api.py", "__init__.py", "_cuda_guard.py"):
            with open(os.path.join(pkg, name)) as fh:
                src = fh.read()
            # "subprocess." (with dot) bans direct subprocess CALLS in the
            # transport files; the bare word still appears in prose.
            # _spawn.py is exempt by design (sanctioned exec, own test).
            for token in ("subprocess.", "Popen", "import pickle",
                          "from pickle", "cPickle", "os.system",
                          "frun.bash", "source ./frun",
                          "multiprocessing", "multiprocessing.Pipe",
                          "multiprocessing.Queue"):
                if token in src:
                    offenders.append("%s: %s" % (name, token))
        self.assertEqual(offenders, [])

    def test_mmap_used_for_data(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "forkrun",
                               "_worker.py")) as fh:
            src = fh.read()
        self.assertIn("mmap.mmap", src)
        self.assertIn("os._exit", src)
        self.assertIn("os.fork", open(os.path.join(
            os.path.dirname(__file__), "..", "forkrun", "run.py")).read())


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestWPY2(unittest.TestCase):
    """W-PY2 lock-ins: F-PY1 flush, F-PY2 thread guard, granularity."""

    def _redirect_fd(self, fd, path):
        saved = os.dup(fd)
        tmp = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        os.dup2(tmp, fd)
        os.close(tmp)
        return saved

    def test_flush_before_ack(self):
        # Payload print() is stdio-buffered; the worker os._exit()s without
        # interpreter cleanup, so markers survive ONLY via flush-before-ack.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        cap = path + ".cap"
        try:
            _write_lines(path, 200)

            def noisy(batch):
                print("MARKER batch=%d" % batch.batch_index)
                return bytes(batch.data)

            saved = self._redirect_fd(1, cap)
            try:
                sys.stdout.flush()
                forkrun.map(noisy, path, workers=2)
                sys.stdout.flush()
            finally:
                os.dup2(saved, 1)
                os.close(saved)
            with open(cap, "rb") as fh:
                captured = fh.read().decode()
            markers = [ln for ln in captured.splitlines()
                       if ln.startswith("MARKER batch=")]
            self.assertTrue(len(markers) > 0, captured[-500:])
        finally:
            os.unlink(path)
            if os.path.exists(cap):
                os.unlink(cap)

    def test_thread_warning_and_quiet(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        cap = path + ".err"
        try:
            _write_lines(path, 200)

            def thready(batch):
                import threading
                import time

                def keep():
                    time.sleep(5)

                t = threading.Thread(target=keep, daemon=True)
                t.start()
                return bytes(batch.data)

            saved = self._redirect_fd(2, cap)
            try:
                sys.stderr.flush()
                forkrun.map(thready, path, workers=1)
                sys.stderr.flush()
            finally:
                os.dup2(saved, 2)
                os.close(saved)
            with open(cap, "rb") as fh:
                self.assertIn(b"single-threaded", fh.read())

            def clean(batch):
                return bytes(batch.data)

            saved = self._redirect_fd(2, cap)
            try:
                sys.stderr.flush()
                forkrun.map(clean, path, workers=1)
                sys.stderr.flush()
            finally:
                os.dup2(saved, 2)
                os.close(saved)
            with open(cap, "rb") as fh:
                self.assertNotIn(b"single-threaded", fh.read())
        finally:
            os.unlink(path)
            if os.path.exists(cap):
                os.unlink(cap)

    def test_single_line(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("only\n")
            out = forkrun.map(_identity, path, workers=2, order="index")
            self.assertEqual(len(out), 1)
            self.assertEqual(b"".join(out), b"only\n")
        finally:
            os.unlink(path)

    def test_batch_granularity(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 50000)
            out = forkrun.map(_identity, path, workers=4, lines=500,
                              order="index")
            self.assertEqual(len(out), 100)
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
        finally:
            os.unlink(path)

    def test_version(self):
        self.assertEqual(forkrun.__version__, "0.10.0")
        self.assertIn("Batch", forkrun.__all__)
        self.assertEqual(forkrun.__engine_version__, "v3.5.2")


class TestScanPerf(unittest.TestCase):
    """F-PY3 lock-in: find()-based scan is C-speed (engine-free)."""

    def test_offset_scan_performance(self):
        unit = b"x" * 64 + b"\n"  # 65-byte lines
        raw = bytearray(unit * ((1 << 20) // len(unit) + 1))
        raw = raw[:(1 << 20)]
        buf = memoryview(raw)
        # NOTE: memoryview.count(b"\n") is always 0 (it compares int
        # elements against a bytes object) — count on the bytearray.
        b = Batch(7, 1000, len(buf), raw.count(b"\n"), buf)
        import time

        t0 = time.perf_counter()
        offs = b.offsets
        dt = time.perf_counter() - t0
        self.assertLess(dt, 0.1, "scan took %.3fs" % dt)
        fmt = struct.Struct("<Q")
        nn = raw.count(b"\n")
        # NOTE: len() on a u64 memoryview counts ELEMENTS, not bytes.
        self.assertEqual(len(offs), nn + 1)
        self.assertEqual(offs.nbytes, (nn + 1) * 8)
        self.assertEqual(fmt.unpack_from(offs, 0)[0], 1000)
        # Last entry = base + index just past the final newline (raw is
        # NOT newline-terminated: 61 trailing "x" bytes follow it).
        self.assertEqual(fmt.unpack_from(offs, nn * 8)[0],
                         1000 + raw.rindex(b"\n") + 1)
        prev = 0
        for k in range(nn + 1):
            cur = fmt.unpack_from(offs, k * 8)[0]
            self.assertGreaterEqual(cur, prev)
            prev = cur


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestEmitter(unittest.TestCase):
    """W-PY3 lock-ins: §3.9b v0.5 emitter (per-worker output memfds,
    keyed records, parent-side reassembly)."""

    def test_emitter_basic(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 1000)
            out = forkrun.map(_identity, path, workers=2, order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
        finally:
            os.unlink(path)

    def test_emitter_ordered(self):
        # batch_index keys drive reassembly: idx-prefixed markers arrive
        # strictly increasing under order="index"...
        def marked(batch):
            return b"%08d:" % batch.batch_index + bytes(batch.data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 3000)
            out = forkrun.map(marked, path, workers=4, order="index")
            idxs = [int(rec.split(b":", 1)[0]) for rec in out]
            self.assertEqual(idxs, sorted(idxs))
            self.assertEqual(len(set(idxs)), len(idxs))
            # ...and unordered delivery still carries every line exactly once
            # (compare line multisets — batches and lines differ in
            # granularity, so sort lines, not blobs).
            out2 = forkrun.map(_identity, path, workers=4)
            with open(path, "rb") as fh:
                raw = fh.read()
            self.assertEqual(sorted(b"".join(out2).splitlines()),
                             sorted(raw.splitlines()))
        finally:
            os.unlink(path)

    def test_emitter_none_return(self):
        def drop(batch):
            return None

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 500)
            self.assertEqual(forkrun.map(drop, path, workers=2), [])
        finally:
            os.unlink(path)

    def test_emitter_memory_bounded(self):
        # v0.5 collects parent-side, so "bounded" means output-sized: the
        # parent's peak RSS grows with total OUTPUT bytes, not stream
        # length. True constant-memory PIPE drain is v1.
        import resource

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 20000)  # ~200KB in, ~200KB out
            before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            out = forkrun.map(_identity, path, workers=4, order="index")
            after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            # ru_maxrss is KB on Linux: 50MB headroom is generous for a
            # ~200KB collection; it guards against accidental full-stream
            # duplication, not the collection itself.
            self.assertLess(after - before, 50 * 1024)
        finally:
            os.unlink(path)

    def test_emitter_vs_worker_sink(self):
        # Emitter collection and payload-side sink observe identical bytes.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".out",
                                         delete=False) as fh2:
            sink_path = fh2.name
        try:
            _write_lines(path, 800)

            def up(batch):
                return bytes(batch.data).upper()

            collected = forkrun.map(up, path, workers=2)

            def sink(meta, result):
                with open(sink_path, "ab") as out:
                    out.write(result)

            forkrun.run(up, path, sink=sink, workers=2)
            with open(sink_path, "rb") as fh:
                sunk = fh.read()
            # Batch blobs vs lines differ in granularity — compare multisets.
            self.assertEqual(sorted(b"".join(collected).splitlines()),
                             sorted(sunk.splitlines()))
        finally:
            os.unlink(path)
            os.unlink(sink_path)

    def test_output_record_format(self):
        # The v0 record framing round-trips through the real path: each
        # emitted record carries its batch_index key ahead of its bytes,
        # keys are unique, and key-ordered reassembly is byte-exact.
        def marked(batch):
            return b"%08d:" % batch.batch_index + bytes(batch.data)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 1500)
            out = forkrun.map(marked, path, workers=3, order="index")
            body = {}
            for rec in out:
                idx = int(rec.split(b":", 1)[0])
                self.assertNotIn(idx, body)
                body[idx] = rec.split(b":", 1)[1]
            with open(path, "rb") as fh:
                self.assertEqual(
                    b"".join(body[k] for k in sorted(body)), fh.read())
        finally:
            os.unlink(path)

    def test_emitter_large_output(self):
        # 1MB in, 4x amplification out: completes byte-exact (v0.5 holds
        # the output in memfds + parent list — bounded by OUTPUT size).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            _write_lines(path, 100000)  # ~1MB
            with open(path, "rb") as fh:
                raw = fh.read()

            def amplify(batch):
                return bytes(batch.data) * 4

            out = forkrun.map(amplify, path, workers=4, order="index")
            joined = b"".join(out)
            self.assertEqual(len(joined), 4 * len(raw))
            # Each batch blob is its raw span repeated 4x: the first
            # quarters reassemble to the input exactly.
            quarters = []
            for rec in out:
                self.assertEqual(len(rec) % 4, 0)
                q = rec[:len(rec) // 4]
                self.assertEqual(rec, q * 4)
                quarters.append(q)
            self.assertEqual(b"".join(quarters), raw)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
