"""W-REL3a: executor consistency tripwire (behavioral, not AST).

The ten blocking executors in python/forkrun/run.py are the known
root cause of the P1-P5/B1/C4 class ("executor #N forgot something
executor #1 remembered"). This test reads python/tests/
executor_manifest.json and verifies the eight invariants via probes
against what actually runs — routing calls, lock acquire/release
counts, fd-table deltas, refusal behavior — so the next copy-paste
miss fails CI naming the executor and the invariant.

Scope guards: minimal jobs (tiny inputs, 1-2 workers); seconds, not
minutes. Deep ×10 coverage lives in the linked lock-in tests (see
dev/supervisor/EXECUTOR_MANIFEST.md evidence map), not here.
"""

import gc
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
import sys as _sys  # noqa: E402
# NOTE: `forkrun.run` is the public function (shadowing the
# submodule in the package namespace) — the executors live in the
# MODULE, reachable only via sys.modules.
_run_mod = _sys.modules["forkrun.run"]  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

_MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "executor_manifest.json")


def _load_manifest():
    with open(_MANIFEST) as fh:
        return json.load(fh)


def _up(batch):
    return bytes(batch.data)


def _boom(batch):
    raise RuntimeError("injected")


def _nfd():
    return len(os.listdir("/proc/self/fd"))


class _FailCudaLib:
    """Mocked live CUDA context (cuCtxGetCurrent -> nonzero)."""

    def __init__(self, *args, **kwargs):
        pass

    @property
    def cuCtxGetCurrent(self):
        import ctypes as _ctypes

        def _current(ctxptr):
            _ctypes.cast(ctxptr,
                         _ctypes.POINTER(_ctypes.c_void_p))[0] = 0xDEAD
            return 0

        return _current


def _live_cuda():
    import ctypes as _ctypes
    real = _ctypes.CDLL

    def _fake(name, *args, **kwargs):
        if "libcuda" in str(name):
            return _FailCudaLib()
        return real(name, *args, **kwargs)

    return mock.patch("ctypes.CDLL", side_effect=_fake)


# Routing table: executor name -> minimal job exercising it.
# Numbering matches EXECUTOR_MANIFEST.md (#1..#10).
def _routings(path):
    return {
        "_execute_locked": lambda: forkrun.map(
            _up, path, workers=1, orchestrator=False, nodes=1),
        "_execute_ingest_locked": lambda: forkrun.map(
            _up, path, workers=1, orchestrator=False, streaming=True,
            nodes=1),
        "_execute_streaming": lambda: list(forkrun.stream(
            _up, path, workers=1, orchestrator=False, nodes=1)),
        "_execute_ingest_stream": lambda: list(forkrun.stream(
            _up, path, workers=1, orchestrator=False, streaming=True,
            nodes=1)),
        "_execute_reactor_locked": lambda: forkrun.map(
            _up, path, workers=1, nodes=1),
        "_execute_streaming_reactor": lambda: list(forkrun.stream(
            _up, path, workers=1, nodes=1)),
        "_execute_ingest_reactor_locked": lambda: forkrun.map(
            _up, path, workers=1, streaming=True, nodes=1),
        "_execute_ingest_stream_reactor": lambda: list(forkrun.stream(
            _up, path, workers=1, streaming=True, nodes=1)),
        "_execute_numa_locked": lambda: forkrun.map(
            _up, path, workers=2, nodes="@2"),
        "_execute_numa_stream": lambda: list(forkrun.stream(
            _up, path, workers=2, nodes="@2")),
    }


def _stream_routings(path):
    # Stream-generator executors only (abandon-path coverage).
    routes = _routings(path)
    return {k: v for k, v in routes.items()
            if "stream" in k.lower()}


class _LockSpy:
    """Counting RLock proxy (delegates everything else)."""

    def __init__(self, real):
        self._real = real
        self.acq = 0
        self.rel = 0

    def __enter__(self):
        self.acq += 1
        return self._real.__enter__()

    def __exit__(self, *args):
        try:
            return self._real.__exit__(*args)
        finally:
            self.rel += 1

    def __getattr__(self, name):
        return getattr(self.__dict__["_real"], name)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestExecutorRouting(unittest.TestCase):
    """Every manifest executor is reachable via its routing."""

    def test_all_ten_executors_hit(self):
        manifest = _load_manifest()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 100)
            calls = {e["name"]: 0 for e in manifest["executors"]}

            def _spy_fn(name, real):
                def wrapper(*args, **kwargs):
                    calls[name] += 1
                    return real(*args, **kwargs)
                return wrapper

            def _spy_gen(name, real):
                def wrapper(*args, **kwargs):
                    calls[name] += 1
                    yield from real(*args, **kwargs)
                return wrapper

            patches = []
            try:
                for num, exe in enumerate(manifest["executors"], 1):
                    name = exe["name"]
                    real = getattr(_run_mod, name)
                    if "stream" in name.lower():
                        patches.append(mock.patch.object(
                            _run_mod, name, _spy_gen(name, real)))
                    else:
                        patches.append(mock.patch.object(
                            _run_mod, name, _spy_fn(name, real)))
                for p in patches:
                    p.start()
                routes = _routings(path)
                self.assertEqual(
                    set(routes), set(calls),
                    "routing table drifted from manifest")
                for name, job in routes.items():
                    job()
                for num, exe in enumerate(manifest["executors"], 1):
                    self.assertGreater(
                        calls[exe["name"]], 0,
                        "executor #%d %s: routing never called it "
                        "(dispatch drift?)" % (num, exe["name"]))
            finally:
                for p in patches:
                    p.stop()
            assert_no_zombies(self)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestExecutorLocking(unittest.TestCase):
    """I2: _RUN_LOCK acquired/released per executor, exhaust+abandon."""

    def _check(self, routes, verb):
        spy = _LockSpy(_run_mod._RUN_LOCK)
        with mock.patch.object(_run_mod, "_RUN_LOCK", spy):
            for num, (name, job) in enumerate(routes.items(), 1):
                spy.acq = 0
                spy.rel = 0
                job()
                self.assertGreaterEqual(
                    spy.acq, 1,
                    "executor %s [I2 locking/%s]: lock never "
                    "acquired" % (name, verb))
                self.assertEqual(
                    spy.acq, spy.rel,
                    "executor %s [I2 locking/%s]: acquire=%d "
                    "release=%d (leak or early release)"
                    % (name, verb, spy.acq, spy.rel))

    def test_lock_balanced_exhaust(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 100)
            self._check(_routings(path), "exhaust")
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_lock_balanced_abandon(self):
        # Generator lifetimes: next-once then close must release.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 2000)
            spy = _LockSpy(_run_mod._RUN_LOCK)
            with mock.patch.object(_run_mod, "_RUN_LOCK", spy):
                routes = _stream_routings(path)
                self.assertTrue(routes)
                for name in routes:
                    spy.acq = 0
                    spy.rel = 0
                    if "numa" in name:
                        gen = forkrun.stream(
                            _up, path, workers=2, nodes="@2")
                    else:
                        kw = {}
                        if "ingest" in name:
                            kw["streaming"] = True
                        if "orchestrator" in name or "reactor" in name:
                            pass
                        elif name in ("_execute_streaming",
                                     "_execute_ingest_stream"):
                            kw["orchestrator"] = False
                        gen = forkrun.stream(_up, path, workers=1,
                                             nodes=1, **kw)
                    try:
                        next(gen)
                    except StopIteration:
                        pass
                    gen.close()
                    gc.collect()
                    self.assertGreaterEqual(
                        spy.acq, 1,
                        "executor %s [I2 locking/abandon]: lock never "
                        "acquired" % (name,))
                    self.assertEqual(
                        spy.acq, spy.rel,
                        "executor %s [I2 locking/abandon]: acquire=%d "
                        "release=%d" % (name, spy.acq, spy.rel))
            assert_no_zombies(self)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestExecutorFdHygiene(unittest.TestCase):
    """I3+I8: fd table returns to baseline per executor (ok + fail)."""

    def _baseline(self, routes, fail):
        gc.collect()
        for name, job in routes.items():
            base = _nfd()
            if fail:
                with self.assertRaises(
                        RuntimeError,
                        msg="executor %s [I8 teardown]: failure path "
                        "did not raise" % (name,)):
                    job()
            else:
                job()
            gc.collect()
            self.assertEqual(
                _nfd(), base,
                "executor %s [I3 fd-hygiene/%s]: fd delta %d "
                "(leak)" % (name, "fail" if fail else "ok",
                            _nfd() - base))

    def _fail_routes(self, path):
        return {
            "_execute_locked": lambda: forkrun.map(
                _boom, path, workers=1, orchestrator=False, nodes=1,
                on_error="fail-fast"),
            "_execute_ingest_locked": lambda: forkrun.map(
                _boom, path, workers=1, orchestrator=False,
                streaming=True, nodes=1, on_error="fail-fast"),
            "_execute_streaming": lambda: list(forkrun.stream(
                _boom, path, workers=1, orchestrator=False, nodes=1,
                on_error="fail-fast")),
            "_execute_ingest_stream": lambda: list(forkrun.stream(
                _boom, path, workers=1, orchestrator=False,
                streaming=True, nodes=1, on_error="fail-fast")),
            "_execute_reactor_locked": lambda: forkrun.map(
                _boom, path, workers=1, nodes=1, on_error="fail-fast"),
            "_execute_streaming_reactor": lambda: list(forkrun.stream(
                _boom, path, workers=1, nodes=1, on_error="fail-fast")),
            "_execute_ingest_reactor_locked": lambda: forkrun.map(
                _boom, path, workers=1, streaming=True, nodes=1,
                on_error="fail-fast"),
            "_execute_ingest_stream_reactor": lambda: list(
                forkrun.stream(_boom, path, workers=1, streaming=True,
                               nodes=1, on_error="fail-fast")),
            "_execute_numa_locked": lambda: forkrun.map(
                _boom, path, workers=2, nodes="@2",
                on_error="fail-fast"),
            "_execute_numa_stream": lambda: list(forkrun.stream(
                _boom, path, workers=2, nodes="@2",
                on_error="fail-fast")),
        }

    def test_fd_baseline_success(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 100)
            # Warmup (allocator/mmap caches stabilize, then measure).
            forkrun.map(_up, path, workers=1, nodes=1)
            self._baseline(_routings(path), fail=False)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_fd_baseline_failure(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 100)
            forkrun.map(_up, path, workers=1, nodes=1)
            self._baseline(self._fail_routes(path), fail=True)
            assert_no_zombies(self)
        finally:
            os.unlink(path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestExecutorGuards(unittest.TestCase):
    """I1+I5: CUDA refusal on all routings; resume refused-combos raise."""

    def test_cuda_refusal_all_routings(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("x\n")
            with _live_cuda():
                for num, (name, job) in enumerate(
                        _routings(path).items(), 1):
                    with self.assertRaises(
                            RuntimeError,
                            msg="executor #%d %s [I1 guards]: live "
                            "CUDA context did not refuse" % (num, name)):
                        job()
        finally:
            os.unlink(path)

    def test_resume_refused_combos_raise(self):
        # I5: refused combinations fail loudly (never silently
        # truncate). Supported roundtrip lives in test_resume.py
        # (evidence-linked, not duplicated).
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        ckpt = path + ".ckpt"
        try:
            write_lines(path, 100)
            with open(ckpt, "w") as fh:
                fh.write("FORKRUN_RESUME_HORIZON=0\n"
                         "FORKRUN_RESUME_STDOUT_BYTES=0\n")
            combos = {
                "unordered": lambda: forkrun.map(
                    _up, path, workers=1, order="none", nodes=1,
                    resume=ckpt),
                "fail-fast-path": lambda: forkrun.map(
                    _up, path, workers=1, order="index", nodes=1,
                    resume=ckpt, orchestrator=False),
                "numa": lambda: forkrun.map(
                    _up, path, workers=2, order="index", nodes="@2",
                    resume=ckpt),
                "run": lambda: forkrun.run(
                    _up, path, workers=1, nodes=1, resume=ckpt),
            }
            for label, job in combos.items():
                with self.assertRaises(
                        RuntimeError,
                        msg="resume combo %s [I5 gating]: silent "
                        "accept" % (label,)):
                    job()
        finally:
            os.unlink(path)
            if os.path.exists(ckpt):
                os.unlink(ckpt)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestExecutorDepositLoud(unittest.TestCase):
    """I4: one injected-failure instance on the default executor
    (exhaustive ×10 lives in test_escrow_refused.py)."""

    def test_deposit_refused_goes_loud(self):
        from forkrun._bindings import get as _get
        from _helpers import redirect_fd, restore_fd

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        cap = path + ".err"
        flag = path + ".failed"
        calls = path + ".calls"
        lib = _get()
        try:
            write_lines(path, 300)

            def flaky(batch):
                data = bytes(batch.data)
                if b"line 50" in data and not os.path.exists(flag):
                    with open(flag, "w") as _fh:
                        _fh.write("1")
                    raise ValueError("once")
                return data

            real = lib.fr_py_escrow_deposit

            def refuse_twice(kills):
                with open(calls, "a") as _fh:
                    _fh.write("1\n")
                n = sum(1 for _ in open(calls))
                if n <= 2:
                    return 5
                return real(kills)

            saved = redirect_fd(2, cap)
            try:
                with mock.patch.object(
                        lib, "fr_py_escrow_deposit",
                        side_effect=refuse_twice):
                    out = forkrun.map(flaky, path, workers=1,
                                      order="index", nodes=1)
            finally:
                restore_fd(2, saved)
            with open(cap, "rb") as fh:
                err = fh.read()
            self.assertIn(b"escrow deposit refused twice", err)
            self.assertTrue(len(b"".join(out)) > 0)
            assert_no_zombies(self)
        finally:
            os.unlink(path)
            for extra in (cap, flag, calls):
                if os.path.exists(extra):
                    os.unlink(extra)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestExecutorEofLinked(unittest.TestCase):
    """I7: EOF verification lives in test_numa_drain_guard.py —
    mechanically linked (module + audit entry points present)."""

    def test_drain_guard_present(self):
        import test_numa_drain_guard as _dg

        self.assertTrue(hasattr(_dg, "TestNumaDrainAudit"))
        for meth in ("test_clean_passes_silently",
                     "test_violation_raises_naming_node",
                     "test_claim_overshoot_is_benign"):
            self.assertTrue(
                hasattr(_dg.TestNumaDrainAudit, meth),
                "drain-guard audit method missing: %s" % (meth,))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestExecutorManifestIntegrity(unittest.TestCase):
    """The manifest itself: ten executors, eight invariants each,
    every cell evidenced, every deviation reasoned."""

    def test_manifest_complete(self):
        manifest = _load_manifest()
        self.assertEqual(len(manifest["executors"]), 10)
        inv_ids = [inv["id"] for inv in manifest["invariants"]]
        self.assertEqual(len(inv_ids), 8)
        for num, exe in enumerate(manifest["executors"], 1):
            self.assertTrue(exe["name"].startswith("_execute_"),
                            "executor #%d naming" % (num,))
            self.assertTrue(exe.get("paths"),
                            "executor #%d %s: no paths served"
                            % (num, exe["name"]))
            self.assertIn(exe["name"], dir(_run_mod),
                          "executor #%d %s: not in forkrun.run "
                          "(renamed?)" % (num, exe["name"]))
            for inv in inv_ids:
                cell = exe["invariants"].get(inv)
                self.assertIsNotNone(
                    cell,
                    "executor #%d %s [%s]: cell missing" % (
                        num, exe["name"], inv))
                self.assertTrue(
                    cell.get("evidence"),
                    "executor #%d %s [%s]: evidence empty "
                    "(verified-by-review+date required)" % (
                        num, exe["name"], inv))
                self.assertIn(cell.get("status"),
                              ("covered", "deviation"),
                              "executor #%d %s [%s]: bad status" % (
                                  num, exe["name"], inv))
                if cell["status"] == "deviation":
                    self.assertTrue(
                        cell.get("reason"),
                        "executor #%d %s [%s]: deviation "
                        "unreasoned" % (num, exe["name"], inv))


if __name__ == "__main__":
    unittest.main()
