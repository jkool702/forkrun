"""W-REL5-C lock-in bites (behavioral, deterministic unless noted).

C1/C2/C3/C4/C5 ×5 deterministic; C6/C7/C9 timing ×10 (in-test loops).
Each test asserts post-fix behavior; pre-fix failures were demonstrated
by stashing the fix (see commit messages / wave report).
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from forkrun import _bindings as _b  # noqa: E402
from _helpers import assert_no_zombies  # noqa: E402

try:
    _b.find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestC1NoCwdDlopen(unittest.TestCase):
    """C1 (M12): a CWD-planted .so must never load."""

    def test_candidates_never_cwd_anchored(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                cands = _b._substrate_candidates()
                for cand in cands:
                    self.assertFalse(
                        os.path.abspath(cand).startswith(
                            os.path.abspath(tmp) + os.sep),
                        "CWD-anchored candidate: %r" % (cand,))
            finally:
                os.chdir(old)

    def test_hostile_cwd_so_refused(self):
        # Hostile lib in CWD, co-located real ones masked: pre-fix
        # returned the hostile path; post-fix raises FileNotFoundError.
        with tempfile.TemporaryDirectory() as tmp:
            hostile = os.path.join(tmp, "libforkrun_python.so")
            with open(hostile, "wb") as fh:
                fh.write(b"not a real substrate")
            real_exists = os.path.exists

            def _masked(path):
                if os.path.abspath(str(path)).startswith(
                        os.path.abspath(tmp) + os.sep):
                    return True  # the hostile file exists...
                if str(path).endswith("libforkrun_python.so"):
                    return False  # ...but no co-located real one does
                return real_exists(path)

            old = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.object(os.path, "exists",
                                       side_effect=_masked):
                    with self.assertRaises(FileNotFoundError):
                        _b.find_substrate()
            finally:
                os.chdir(old)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestC3SweepResumeRejected(unittest.TestCase):
    """C3 (M14): sweep() must reject resume=/checkpoint_file=."""

    def _sweep_raises(self, **kw):
        import forkrun  # noqa: PLC0415

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("x\n")
            for _ in range(5):
                with self.assertRaises(ValueError):
                    forkrun.sweep(lambda b: b"y", path,
                                  args=[[1, 2]], **kw)
        finally:
            os.unlink(path)

    def test_resume_rejected(self):
        self._sweep_raises(resume="/tmp/does-not-matter.ckpt")

    def test_checkpoint_file_rejected(self):
        self._sweep_raises(checkpoint_file="/tmp/x.ckpt")


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestC2OffMainThreadLoud(unittest.TestCase):
    """C2 (M17): checkpoint policy off the main thread must raise."""

    def test_raises_with_remedy(self):
        import threading  # noqa: PLC0415
        from forkrun._signals import guard  # noqa: PLC0415

        errors = []

        def _enter():
            try:
                with guard("checkpoint"):
                    pass
            except RuntimeError as exc:
                errors.append(str(exc))

        for _ in range(5):
            th = threading.Thread(target=_enter)
            th.start()
            th.join()
            self.assertEqual(len(errors), 1)
            self.assertIn("main thread", errors.pop())
        # Main thread itself still works (returns the guard).
        with guard("checkpoint"):
            pass
        with guard("default"):
            pass


def _framed(*pairs):
    import struct  # noqa: PLC0415

    out = []
    for idx, blob in pairs:
        out.append(struct.pack("<QQ", idx, len(blob)) + blob)
    return b"".join(out)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestC4DeliverThenUnlink(unittest.TestCase):
    """C4 (M18): consume must not delete; publish GCs the superseded."""

    def test_consume_keeps_merge_publish_gcs(self):
        from forkrun._resume import (SIDECAR_SUFFIX, _publish_sidecar,  # noqa: PLC0415
                                     consume_sidecar)
        from forkrun.run import _parse_records  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            old_ckpt = os.path.join(tmp, "a.ckpt")
            with open(old_ckpt, "w") as fh:
                fh.write("FORKRUN_RESUME_HORIZON=0\n"
                         "FORKRUN_RESUME_STDOUT_BYTES=0\n")
            old_coll = old_ckpt + SIDECAR_SUFFIX
            with open(old_coll, "wb") as fh:
                fh.write(_framed((0, b"hello"), (1, b"world")))
            cur = _parse_records(_framed((10, b"new")))
            for _ in range(5):
                # Re-create: consume must be non-destructive now.
                if not os.path.exists(old_coll):
                    with open(old_coll, "wb") as fh:
                        fh.write(_framed((0, b"hello"), (1, b"world")))
                merged = consume_sidecar(old_ckpt, cur)
                self.assertEqual(
                    [b for _, b in merged], [b"hello", b"world", b"new"])
                self.assertTrue(os.path.exists(old_coll),
                                "consume deleted the only durable copy")
            # Publish folds old + current collection, then GCs the old.
            with tempfile.NamedTemporaryFile(delete=False) as fh:
                fh.write(_framed((2, b"more!")))
                coll_path = fh.name
            try:
                with open(coll_path, "rb") as fh:
                    coll_fd = fh.fileno()
                    new_ckpt = os.path.join(tmp, "b.ckpt")
                    self.assertTrue(_publish_sidecar(
                        new_ckpt + SIDECAR_SUFFIX, old_ckpt, coll_fd))
                with open(new_ckpt + SIDECAR_SUFFIX, "rb") as fh:
                    new_blob = fh.read()
                self.assertEqual(
                    _parse_records(new_blob),
                    _parse_records(_framed(
                        (0, b"hello"), (1, b"world"), (2, b"more!"))))
                self.assertFalse(os.path.exists(old_coll),
                                 "superseded sidecar not collected")
            finally:
                os.unlink(coll_path)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestC5SpareNulled(unittest.TestCase):
    """C5 (M19): teardown must not receive a closed spare number."""

    def test_spare_is_none_at_teardown(self):
        import forkrun  # noqa: PLC0415
        import sys as _sys  # noqa: PLC0415
        from _helpers import write_lines  # noqa: PLC0415

        _run_mod = _sys.modules["forkrun.run"]
        seen = []
        real = _run_mod._teardown_reactor

        def _spy(lib, state, **kw):
            seen.append(kw.get("spare_signal_w", "absent"))
            return real(lib, state, **kw)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 200)

            from unittest import mock as _mock  # noqa: PLC0415
            for _ in range(5):
                del seen[:]
                with _mock.patch.object(_run_mod, "_teardown_reactor",
                                        side_effect=_spy):
                    # Abandon mid-stream with workers provably live
                    # (slow payload: first result arrives while
                    # hundreds of batches remain). The spare is
                    # still set at finally time (the mid-run
                    # _close_spare only fires once no worker is
                    # alive). Pre-fix the finally closed it without
                    # nulling and handed the stale number to
                    # teardown (double-close).
                    def _slow(batch):
                        import time as _time  # noqa: PLC0415
                        _time.sleep(0.5)
                        return bytes(batch.data)

                    gen = forkrun.stream(
                        _slow, path, workers=2, nodes=1, c_drain=True)
                    try:
                        next(gen)
                    except StopIteration:
                        pass
                    gen.close()
                    import gc as _gc  # noqa: PLC0415
                    _gc.collect()
                self.assertTrue(seen, "teardown never ran")
                for val in seen:
                    self.assertIsNone(
                        val, "stale spare fd passed to teardown: %r"
                        % (val,))
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
