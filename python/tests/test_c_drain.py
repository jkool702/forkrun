"""W-PY21-A C drain: data/control path separation (Stage 5).

A forked C loop (fr_py_drain_loop) moves signal consume + output
memfd pread into a results destination; the parent never touches
the data path (signals/memfds) on drain paths — control only.
Framing and parsing are untouched, so results are byte-identical
to the legacy Python drain either way (c_drain=True/False).

No threads anywhere (fork-before-threads stays intact): streaming
pumps the results pipe single-threaded alongside WNOHANG reaps
and spill quanta.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate, get, v1_available  # noqa: E402

from _helpers import (assert_no_zombies, joined_bytes,  # noqa: E402
                      lines_of, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _up(batch):
    return bytes(batch.data).upper()


def _make_input(n=2000, prefix="line"):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    write_lines(path, n, fmt=prefix + " %d\n")
    return path


def _lines(res):
    return sorted(b"".join(res).splitlines())


class TestCDrainValidation(unittest.TestCase):
    """Eager validation of the c_drain flag (engine-free shape)."""

    def test_bad_c_drain_rejected(self):
        for bad in ("yes", 1, 0, [], {}):
            with self.assertRaises(TypeError, msg=repr(bad)):
                forkrun.map(_up, "f.txt", c_drain=bad)

    def test_bad_c_drain_run_rejected(self):
        with self.assertRaises(TypeError):
            forkrun.run(_up, "f.txt", c_drain="true")

    def test_bad_c_drain_stream_rejected(self):
        with self.assertRaises(TypeError):
            forkrun.stream(_up, "f.txt", c_drain=1)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCDrainBasic(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_drain_symbol(self):
        self.assertTrue(v1_available().get("drain"))
        self.assertTrue(hasattr(get(), "fr_py_drain_loop"))

    def test_c_drain_map(self):
        path = _make_input()
        try:
            res = forkrun.map(_up, path, workers=4, c_drain=True)
            self.assertEqual(_lines(res), _lines(
                forkrun.map(_up, path, workers=4, c_drain=False)))
        finally:
            os.unlink(path)

    def test_c_drain_vs_python_drain(self):
        path = _make_input(3000)
        try:
            for order in ("none", "index"):
                c_res = forkrun.map(_up, path, workers=4,
                                    order=order, c_drain=True,
                                    nodes=1)
                py_res = forkrun.map(_up, path, workers=4,
                                     order=order, c_drain=False,
                                     nodes=1)
                if order == "index":
                    # Split-agnostic parity: the C drain and the
                    # Python drain consume the same records, but the
                    # two runs batch independently (adaptive L races
                    # run to run) — compare joined bytes (F-PY-UMA1),
                    # never blob identity across runs.
                    self.assertEqual(joined_bytes(c_res),
                                     joined_bytes(py_res))
                else:
                    self.assertEqual(lines_of(c_res), lines_of(py_res))
        finally:
            os.unlink(path)

    def test_c_drain_default_is_legacy(self):
        # Default (None) takes the legacy path: identical results to
        # explicit False. (Measured 0.7-1.0x for opt-in True — the
        # default stays legacy so no user regresses.)
        path = _make_input(1000)
        try:
            default = forkrun.map(_up, path, workers=2, nodes=1)
            explicit = forkrun.map(_up, path, workers=2, nodes=1,
                                   c_drain=True)
            legacy = forkrun.map(_up, path, workers=2, nodes=1,
                                 c_drain=False)
            self.assertEqual(lines_of(default), lines_of(legacy))
            self.assertEqual(lines_of(default), lines_of(explicit))
        finally:
            os.unlink(path)

    def test_c_drain_ordered(self):
        path = _make_input()
        try:
            res = forkrun.map(_up, path, workers=4, order="index",
                              c_drain=True, nodes=1)
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(res), fh.read().upper())
        finally:
            os.unlink(path)

    def test_c_drain_empty(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            self.assertEqual(
                forkrun.map(_up, path, workers=2, c_drain=True), [])
            self.assertEqual(
                list(forkrun.stream(_up, path, workers=2,
                                    c_drain=True)), [])
        finally:
            os.unlink(path)

    def test_c_drain_run_discard(self):
        path = _make_input(500)
        try:
            # run() discards (no out memfds): drain not engaged,
            # flag accepted harmlessly either way.
            self.assertIsNone(forkrun.run(_up, path, workers=2,
                                          c_drain=True))
            self.assertIsNone(forkrun.run(_up, path, workers=2,
                                          c_drain=False))
        finally:
            os.unlink(path)

    def test_c_drain_fault(self):
        # Payload errors ride escrow/retry/poison per batch under
        # the drain exactly like the legacy path.
        path = _make_input(1000)
        try:
            def _sometimes(b):
                if b.batch_index % 7 == 3:
                    raise ValueError("poison me")
                return bytes(b.data).upper()

            for cd in (True, False):
                res = forkrun.map(_sometimes, path, workers=4,
                                  on_error="retry", c_drain=cd)
                healthy = forkrun.map(_up, path, workers=4)
                self.assertLess(len(res), len(healthy))
                self.assertTrue(
                    set(_lines(res)) <= set(_lines(healthy)))
        finally:
            os.unlink(path)

    def test_c_drain_splice(self):
        path = _make_input(2000)
        try:
            c_res = forkrun.map(None, path, mode="splice",
                                bytes=32768, workers=2, c_drain=True,
                                nodes=1)
            py_res = forkrun.map(None, path, mode="splice",
                                 bytes=32768, workers=2,
                                 c_drain=False, nodes=1)
            self.assertEqual(_lines(c_res), _lines(py_res))
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCDrainStream(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_c_drain_stream(self):
        path = _make_input()
        try:
            n = 0
            for _ in forkrun.stream(_up, path, workers=4,
                                    c_drain=True):
                n += 1
            self.assertGreater(n, 0)
        finally:
            os.unlink(path)

    def test_c_drain_stream_matches(self):
        path = _make_input()
        try:
            c_res = list(forkrun.stream(_up, path, workers=4,
                                        c_drain=True))
            py_res = list(forkrun.stream(_up, path, workers=4,
                                         c_drain=False))
            self.assertEqual(lines_of(c_res), lines_of(py_res))
        finally:
            os.unlink(path)

    def test_c_drain_stream_ordered(self):
        path = _make_input()
        try:
            c_res = list(forkrun.stream(_up, path, workers=4,
                                        order="index", c_drain=True))
            py_res = list(forkrun.stream(_up, path, workers=4,
                                         order="index",
                                         c_drain=False))
            # Same split-agnostic rule as above (F-PY-UMA1).
            self.assertEqual(joined_bytes(c_res), joined_bytes(py_res))
        finally:
            os.unlink(path)

    def test_c_drain_stream_incremental(self):
        # Results arrive while workers run (not post-join): full
        # content lands through the results pipe, first yield first.
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(r)
            with os.fdopen(w, "w") as fh:
                for i in range(2000):
                    fh.write("pipe %d\n" % i)
            os._exit(0)
        os.close(w)
        try:
            gen = forkrun.stream(_up, r, workers=4, c_drain=True,
                                 streaming=True)
            first = next(gen)
            rest = list(gen)
            self.assertTrue(first)
            total = _lines([first] + rest)
            self.assertEqual(len(total), 2000)
            self.assertEqual(total[0], b"PIPE 0")
        finally:
            os.close(r)
            os.waitpid(pid, 0)

    def test_c_drain_stream_content(self):
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(r)
            with os.fdopen(w, "w") as fh:
                for i in range(1500):
                    fh.write("spipe %d\n" % i)
            os._exit(0)
        os.close(w)
        try:
            res = list(forkrun.stream(_up, r, workers=2,
                                      c_drain=True, nodes=1))
        finally:
            os.close(r)
            os.waitpid(pid, 0)
        path = _make_input(1500, prefix="spipe")
        try:
            self.assertEqual(_lines(res), _lines(
                forkrun.map(_up, path, workers=2, nodes=1)))
        finally:
            os.unlink(path)

    def test_c_drain_abandon(self):
        # Abandoned stream: no zombies, no hung children (drain
        # EPIPEs on the closed results pipe and is reaped).
        path = _make_input(5000)
        try:
            gen = forkrun.stream(_up, path, workers=4,
                                 c_drain=True)
            first = next(gen)
            self.assertTrue(first)
            gen.close()
        finally:
            os.unlink(path)
        assert_no_zombies(self)

    def test_c_drain_backpressure(self):
        # Slow consumer through the drain: completes with full
        # content (the 1MB results pipe, not unbounded buffering,
        # carries the backlog — hydraulic backpressure). Runs the
        # consumer in a subprocess so its RSS is observable and the
        # test process never blocks on it.
        import subprocess
        path = _make_input(3000)
        try:
            code = "\n".join([
                "import sys, time",
                "sys.path.insert(0, 'python')",
                "import forkrun",
                "n = 0",
                "for blob in forkrun.stream(",
                "    lambda b: bytes(b.data).upper(),",
                "    '%s', workers=4, c_drain=True):" % path,
                "    n += 1",
                "    time.sleep(0.005)",
                "print(n)",
            ])
            proc = subprocess.run(
                [sys.executable, "-c", code], capture_output=True,
                text=True, timeout=300, cwd="/mnt/ramdisk/forkrun")
            self.assertEqual(proc.returncode, 0,
                             proc.stderr[-2000:])
            self.assertGreater(
                int(proc.stdout.strip().splitlines()[-1]), 0)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCDrainReactor(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_reactor_drain_parity(self):
        path = _make_input()
        try:
            for order in ("none", "index"):
                kw = {} if order == "none" else {"order": "index"}
                a = forkrun.map(_up, path, workers=4,
                                orchestrator=True, c_drain=True,
                                **kw)
                b = forkrun.map(_up, path, workers=4,
                                orchestrator=True, c_drain=False,
                                **kw)
                if order == "index":
                    # index+non-splice uses the C orderer under both
                    # settings (the flag is accepted but inert
                    # there) — still a valid equivalence check.
                    self.assertEqual(joined_bytes(a), joined_bytes(b))
                else:
                    self.assertEqual(lines_of(a), lines_of(b))
        finally:
            os.unlink(path)

    def test_reactor_stream_drain_parity(self):
        path = _make_input()
        try:
            a = list(forkrun.stream(_up, path, workers=4,
                                    orchestrator=True, c_drain=True))
            b = list(forkrun.stream(_up, path, workers=4,
                                    orchestrator=True,
                                    c_drain=False))
            self.assertEqual(lines_of(a), lines_of(b))
        finally:
            os.unlink(path)

    def test_reactor_ingest_drain_parity(self):
        path = _make_input(1500)
        try:
            a = forkrun.map(_up, path, workers=2, orchestrator=True,
                            streaming=True, c_drain=True, nodes=1)
            b = forkrun.map(_up, path, workers=2, orchestrator=True,
                            streaming=True, c_drain=False, nodes=1)
            self.assertEqual(lines_of(a), lines_of(b))
        finally:
            os.unlink(path)

    def test_reactor_respawn_with_drain(self):
        # Segfault recovery under the drain: respawned, rest lands.
        path = _make_input(1500)
        d = tempfile.mkdtemp(prefix="w21adsegv_")
        mod_path = os.path.join(d, "w21adsegv_mod.py")
        try:
            with open(mod_path, "w") as fh:
                fh.write(
                    "import ctypes\n"
                    "def payload(batch):\n"
                    "    if batch.batch_index == 0:\n"
                    "        ctypes.string_at(0)\n"
                    "    return bytes(batch.data).upper()\n")
            sys.path.insert(0, d)
            try:
                res = forkrun.map("w21adsegv_mod:payload", path,
                                  workers=2, orchestrator=True,
                                  c_drain=True, nodes=1)
            finally:
                sys.path.remove(d)
            healthy = forkrun.map(_up, path, workers=2, nodes=1)
            rl, hl = _lines(res), _lines(healthy)
            self.assertTrue(rl)
            self.assertTrue(set(rl) <= set(hl))
        finally:
            os.unlink(path)
            import shutil as _shutil
            _shutil.rmtree(d, ignore_errors=True)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCDrainNUMA(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_numa_drain_parity(self):
        path = _make_input()
        try:
            a = forkrun.map(_up, path, workers=4, nodes="@2",
                            c_drain=True)
            b = forkrun.map(_up, path, workers=4, nodes="@2",
                            c_drain=False)
            self.assertEqual(_lines(a), _lines(b))
        finally:
            os.unlink(path)

    def test_numa_drain_ordered(self):
        path = _make_input(1500)
        try:
            with open(path, "rb") as fh:
                expected = fh.read().upper()
            # index+non-splice uses the C orderer on both settings.
            res = forkrun.map(_up, path, workers=4, nodes="@2",
                              order="index", c_drain=True)
            self.assertEqual(b"".join(res), expected)
        finally:
            os.unlink(path)

    def test_numa_stream_drain_parity(self):
        path = _make_input(1500)
        try:
            a = list(forkrun.stream(_up, path, workers=4,
                                    nodes="@2", c_drain=True))
            b = list(forkrun.stream(_up, path, workers=4,
                                    nodes="@2", c_drain=False))
            self.assertEqual(_lines(a), _lines(b))
        finally:
            os.unlink(path)

    def test_numa_drain_empty(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            self.assertEqual(
                forkrun.map(_up, path, workers=4, nodes="@2",
                            c_drain=True), [])
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCDrainPerformance(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_c_drain_not_slower(self):
        # Back-to-back medians on the same box: the drain path must
        # not be catastrophically slower than legacy (2x gate —
        # generous headroom over the measured ~1.4x typical, so
        # loaded CI boxes don't flake; the money numbers live in
        # bench_c_drain.py. NOTE: measured 0.7-1.0x overall — the
        # work order's ≥1.5x-faster premise is falsified, hence
        # opt-in default. This test guards against REGRESSION,
        # not for speedup.)
        import statistics
        path = _make_input(20000)
        try:
            def _t(cdr):
                ts = []
                for _ in range(3):
                    t0 = time.monotonic()
                    forkrun.map(_up, path, workers=8, c_drain=cdr)
                    ts.append(time.monotonic() - t0)
                return statistics.median(ts)

            t_c = _t(True)
            t_py = _t(False)
            self.assertLessEqual(
                t_c, t_py * 2.0,
                "C drain catastrophically slow: %.3fs vs legacy %.3fs"
                % (t_c, t_py))
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCDrainPurity(unittest.TestCase):
    def test_drain_capability_reported(self):
        caps = v1_available()
        self.assertTrue(caps.get("drain"),
                        "fr_py_drain_loop missing from .so")
        self.assertTrue(hasattr(get(), "fr_py_drain_loop"))


if __name__ == "__main__":
    unittest.main()
