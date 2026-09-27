"""W-PY26 C worker loop: zero-Python-per-batch plugin path (Stage 5).

fr_py_worker_plugin_loop owns claim → plugin → signal → ack in C —
the plugin analogue of the W-PY18 splice loop. Results are
byte-identical to the Python worker loop on every path (plain,
ordered, reactor, c_drain); error semantics (retry/skip/fail-fast,
poison, sentinel) match _worker.py; the flag is gated to its
supported envelope (map, mode="plugin", dialect-1/2, UMA,
materialized) and raises loudly elsewhere.

No threads anywhere (fork-before-threads stays intact).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate, v1_available  # noqa: E402

from _helpers import (assert_no_zombies, joined_bytes,  # noqa: E402
                      lines_of, write_lines)

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
V1_SO = os.path.join(REPO_ROOT, "python", "tests", "plugins",
                     "test_plugin_v1.so")
V0_SO = os.path.join(REPO_ROOT, "python", "tests", "plugins",
                     "test_plugin.so")

V1_UP = V1_SO + ":process_v1"
V1_FAIL = V1_SO + ":always_fail_v1"
V1_IDENT = V1_SO + ":identify_v1"


def _has_loop():
    if not HAVE_LIB:
        return False
    try:
        return bool(v1_available().get("plugin_loop"))
    except Exception:
        return False


def _make_input(n=300, prefix="line"):
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    write_lines(path, n, fmt=prefix + " %d\n")
    return path


def _need_so(testcase, path):
    if not os.path.exists(path):
        testcase.skipTest("missing fixture %s" % path)


# W-REL1/R3: build missing fixtures here instead of inheriting them
# from test_v1_fast.py's setUpModule (which sorts later, so this
# module's parity tests silently skipped inside release_check.py's
# nested-suite skip). Idempotent: rebuild only when the .so is
# missing or older than its source; skip-with-reason when no
# toolchain exists. _BUILD_ERROR carries the reason to setUp.
_BUILD_ERROR = None


def _build_fixture(src, so):
    if os.path.exists(so) and (
            os.path.getmtime(so) >= os.path.getmtime(src)):
        return
    if shutil.which("gcc") is None:
        raise unittest.SkipTest("gcc not available — cannot build %s"
                                % os.path.basename(so))
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-o", so, src],
        check=True, capture_output=True, timeout=300)


def setUpModule():
    # Fixture .so files (mirror test_v1_fast.py's gcc line for v1;
    # same line builds the v0 fixture test_v0_plugin_rejected needs).
    global _BUILD_ERROR
    plugins = os.path.join(REPO_ROOT, "python", "tests", "plugins")
    try:
        _build_fixture(os.path.join(plugins, "test_plugin_v1.c"), V1_SO)
        _build_fixture(os.path.join(plugins, "test_plugin.c"), V0_SO)
    except unittest.SkipTest as exc:
        _BUILD_ERROR = str(exc)
        return
    except Exception as exc:  # noqa: BLE001
        _BUILD_ERROR = "fixture build failed: %s" % exc
        return
    # Substrate .so: build when absent so the parity tests below RUN
    # inside gates that never built it (release_check.py's nested
    # skip suppresses the packaging-driver builds). HAVE_LIB is
    # re-resolved at runtime in setUp (the class-level skipUnless
    # below had to go — it froze the import-time value).
    global HAVE_LIB
    if not HAVE_LIB:
        if shutil.which("gcc") is None or shutil.which("make") is None:
            _BUILD_ERROR = "no toolchain — cannot build substrate"
            return
        try:
            subprocess.run(
                ["make", "-f", "Makefile.substrate", "python-substrate"],
                check=True, capture_output=True, timeout=900,
                cwd=REPO_ROOT)
        except Exception as exc:  # noqa: BLE001
            _BUILD_ERROR = "substrate build failed: %s" % exc
            return
        try:
            find_substrate()
            HAVE_LIB = True
        except FileNotFoundError:
            _BUILD_ERROR = "substrate .so not built"
            return


class TestCWorkerLoopValidation(unittest.TestCase):
    """Eager validation of the c_worker_loop flag (engine-free shape)."""

    def test_bad_flag_rejected(self):
        for bad in ("yes", 1, 0, [], {}):
            with self.assertRaises(TypeError, msg=repr(bad)):
                forkrun.map(V1_UP, "f.txt", mode="plugin",
                            c_worker_loop=bad)

    def test_non_plugin_mode_rejected(self):
        with self.assertRaises(ValueError):
            forkrun.map(lambda b: b"x", "f.txt", c_worker_loop=True)

    def test_run_rejected(self):
        with self.assertRaises(RuntimeError):
            forkrun.run(V1_UP, "f.txt", mode="plugin",
                        c_worker_loop=True)

    def test_stream_rejected(self):
        # stream() validates eagerly (raises on call, before next()).
        with self.assertRaises(RuntimeError):
            forkrun.stream(V1_UP, "f.txt", mode="plugin",
                           c_worker_loop=True)


class TestCWorkerLoopParity(unittest.TestCase):
    """Byte-identical results to the Python worker loop."""

    def setUp(self):
        # W-REL1/R3: runtime gating (setUpModule above may have built
        # what import time lacked — a class-level skipUnless would
        # freeze the stale value and silently skip inside gates).
        if _BUILD_ERROR is not None:
            self.skipTest(_BUILD_ERROR)
        if not HAVE_LIB:
            self.skipTest("substrate .so not built")
        _need_so(self, V1_SO)
        if not _has_loop():
            self.skipTest("fr_py_worker_plugin_loop absent — rebuild")

    def tearDown(self):
        assert_no_zombies(self)

    def _both(self, path, **kw):
        # C worker loops are UMA-only by gate — pin UMA so the
        # parity compares loop implementations, not topologies.
        kw.setdefault("nodes", 1)
        a = forkrun.map(V1_UP, path, mode="plugin", **kw)
        b = forkrun.map(V1_UP, path, mode="plugin", c_worker_loop=True,
                        **kw)
        return a, b

    def test_plain_none_identical(self):
        path = _make_input()
        try:
            a, b = self._both(path, workers=2, order="none")
            self.assertEqual(lines_of(a), lines_of(b))
            self.assertTrue(len(a) > 0)
        finally:
            os.unlink(path)

    def test_plain_index_identical(self):
        path = _make_input()
        try:
            a, b = self._both(path, workers=2, order="index")
            self.assertEqual(joined_bytes(a), joined_bytes(b))
        finally:
            os.unlink(path)

    def test_reactor_index_identical(self):
        path = _make_input()
        try:
            a, b = self._both(path, workers=2, order="index",
                              orchestrator=True)
            self.assertEqual(joined_bytes(a), joined_bytes(b))
        finally:
            os.unlink(path)

    def test_c_drain_identical(self):
        path = _make_input()
        try:
            a, b = self._both(path, workers=2, order="none",
                              c_drain=True)
            self.assertEqual(lines_of(a), lines_of(b))
        finally:
            os.unlink(path)

    def test_ctx_fields_identical(self):
        path = _make_input(n=100)
        try:
            a = forkrun.map(V1_IDENT, path, mode="plugin", workers=2,
                            nodes=1)
            b = forkrun.map(V1_IDENT, path, mode="plugin", workers=2,
                            c_worker_loop=True, nodes=1)
            # Batch counts legitimately differ run to run (pre-flight
            # race sets L), so compare identity SEMANTICS, not idx
            # values: every batch reports kills=0 and each run's idx
            # set is exactly range(N) (claimed exactly once).
            import re as _re
            for res in (a, b):
                raw = lines_of(res)
                pairs = [_re.match(rb"idx=(\d+) kills=(\d+)$",
                                   bytes(x).strip()) for x in raw]
                self.assertTrue(raw)
                self.assertTrue(all(pairs),
                                "unparseable ctx line in %r" % (raw,))
                pairs = [p.groups() for p in pairs]
                self.assertTrue(all(int(k) == 0 for _, k in pairs))
                self.assertEqual(sorted(int(i) for i, _ in pairs),
                                 list(range(len(pairs))))
        finally:
            os.unlink(path)

    def test_fail_retry_poison_parity(self):
        path = _make_input(n=100)
        try:
            a = forkrun.map(V1_FAIL, path, mode="plugin", workers=1, nodes=1)
            b = forkrun.map(V1_FAIL, path, mode="plugin", workers=1, nodes=1,
                            c_worker_loop=True)
            self.assertEqual(joined_bytes(a), joined_bytes(b))
            self.assertEqual(a, [])
        finally:
            os.unlink(path)

    def test_fail_skip_parity(self):
        path = _make_input(n=100)
        try:
            a = forkrun.map(V1_FAIL, path, mode="plugin", workers=1, nodes=1,
                            on_error="skip")
            b = forkrun.map(V1_FAIL, path, mode="plugin", workers=1, nodes=1,
                            on_error="skip", c_worker_loop=True)
            self.assertEqual(joined_bytes(a), joined_bytes(b))
            self.assertEqual(a, [])
        finally:
            os.unlink(path)

    def test_fail_fast_raises_both(self):
        path = _make_input(n=100)
        try:
            with self.assertRaises(RuntimeError):
                forkrun.map(V1_FAIL, path, mode="plugin", workers=1, nodes=1,
                            on_error="fail-fast")
            with self.assertRaises(RuntimeError):
                forkrun.map(V1_FAIL, path, mode="plugin", workers=1, nodes=1,
                            on_error="fail-fast", c_worker_loop=True)
        finally:
            os.unlink(path)

    def test_v0_plugin_rejected(self):
        _need_so(self, V0_SO)
        path = _make_input(n=50)
        try:
            with self.assertRaises(RuntimeError):
                forkrun.map(V0_SO + ":process", path, mode="plugin",
                            workers=1, c_worker_loop=True)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
