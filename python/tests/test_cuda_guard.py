"""W-PY5 contract tests: CUDA-fork hazard guard (Stage 4 final item).

These assert the CONTRACT (hazard → clean refusal → actionable message),
not the detection mechanism. The mechanism (dlopen/maps) is replaceable;
refusal behavior is not. Subprocess drivers run with cwd=repo root and
PYTHONPATH=python (the test_rss pattern).
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))

_TORCH_VIRGIN_DRIVER = "\n".join([
    "import sys",
    "sys.path.insert(0, 'python')",
    "try:",
    "    import torch",
    "except ImportError:",
    "    sys.exit(0)",
    "from forkrun._cuda_guard import check_cuda_hazard",
    "hazard, msg = check_cuda_hazard()",
    "sys.exit(0 if not hazard else 1)",
])

_LIVE_CUDA_DRIVER = "\n".join([
    "import sys",
    "sys.path.insert(0, 'python')",
    "try:",
    "    import torch",
    "    torch.cuda.init()",
    "except Exception:",
    "    sys.exit(0)",
    "import forkrun",
    "try:",
    "    forkrun.run(lambda b: None, '/dev/null', workers=1)",
    "    sys.exit(1)",
    "except RuntimeError as e:",
    "    msg = str(e).lower()",
    "    assert 'cuda' in msg, msg",
    "    assert 'fork' in msg or 'spawn' in msg, msg",
    "    sys.exit(0)",
])


class TestCudaGuardContract(unittest.TestCase):
    def test_guard_module_imports_clean(self):
        from forkrun._cuda_guard import check_cuda_hazard  # noqa: PLC0415

        hazard, msg = check_cuda_hazard()
        self.assertFalse(hazard)
        self.assertEqual(msg, "")

    def test_refusal_message_is_actionable(self):
        from forkrun._cuda_guard import (  # noqa: PLC0415
            _HAZARD_MESSAGE, _HAZARD_MESSAGE_CONSERVATIVE)

        for text in (_HAZARD_MESSAGE, _HAZARD_MESSAGE_CONSERVATIVE):
            low = text.lower()
            self.assertIn("cuda", low)
            self.assertIn("fork", low)
            self.assertIn("before", low)

    def test_definitive_answer_overrides_maps(self):
        # Lock-in for the W-PY5 correction: a definitive primary answer
        # is never overridden by the maps fallback. A clean no-context
        # verdict passes even with libcuda mapped (virgin scripts untaxed);
        # only INCONCLUSIVE consults the fallback.
        from forkrun import _cuda_guard  # noqa: PLC0415

        with mock.patch.object(_cuda_guard, "_live_context_check",
                               return_value=False), \
             mock.patch.object(_cuda_guard, "_libcuda_mapped",
                               return_value=True):
            hazard, _ = _cuda_guard.check_cuda_hazard()
            self.assertFalse(hazard)
        with mock.patch.object(_cuda_guard, "_live_context_check",
                               return_value=None), \
             mock.patch.object(_cuda_guard, "_libcuda_mapped",
                               return_value=True):
            hazard, msg = _cuda_guard.check_cuda_hazard()
            self.assertTrue(hazard)
            self.assertIn("conservative", msg.lower())
        with mock.patch.object(_cuda_guard, "_live_context_check",
                               return_value=True):
            hazard, msg = _cuda_guard.check_cuda_hazard()
            self.assertTrue(hazard)
            self.assertIn("live cuda context", msg.lower())

    def test_simulated_hazard_refuses_run(self):
        # Positive control without a GPU: a hazard verdict refuses out of
        # run() with the actionable message (patch at the run seam).
        import importlib  # noqa: PLC0415

        run_mod = importlib.import_module("forkrun.run")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("x\n")
            with mock.patch.object(
                    run_mod, "check_cuda_hazard",
                    return_value=(True, "fake hazard: spawn first")):
                with self.assertRaisesRegex(RuntimeError, "spawn first"):
                    forkrun.run(lambda b: None, path, workers=1)
        finally:
            os.unlink(path)

    def test_torch_import_no_cuda_init_passes(self):
        proc = subprocess.run(
            [sys.executable, "-c", _TORCH_VIRGIN_DRIVER],
            capture_output=True, text=True, timeout=120, cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0,
                         "guard fired on CUDA-virgin torch import:\n%s"
                         % proc.stderr)

    def test_live_cuda_context_refuses(self):
        proc = subprocess.run(
            [sys.executable, "-c", _LIVE_CUDA_DRIVER],
            capture_output=True, text=True, timeout=120, cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0,
                         "CUDA guard contract failed:\n%s" % proc.stderr)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestCudaGuardIntegration(unittest.TestCase):
    def test_no_cuda_no_refusal(self):
        # This runner is CUDA-virgin: a real run must pass the guard.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("test\n")
            out = forkrun.map(lambda b: b.copy(), path, workers=1)
            self.assertEqual(b"".join(out), b"test\n")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
