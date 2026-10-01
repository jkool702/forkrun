"""Spawn-time CUDA-fork hazard detection (W-PY5, Stage 4 final item).

The Fork Memory Paradox: a CUDA context cannot survive fork(). A worker
forked while the parent holds a live context inherits corrupted driver
state (UB). v0 workers are CPU-only by default; this guard refuses to
fork when the parent holds live CUDA state, with an actionable message.

Detection (conservative, replaceable — the CONTRACT is refusal behavior,
not the mechanism):
  1. Primary: dlopen("libcuda.so.1", RTLD_NOLOAD) + cuCtxGetCurrent.
     Definitive when it resolves: refuses ONLY on a live context, so
     torch-importing-but-CUDA-virgin scripts pass untaxed.
  2. Fallback: /proc/self/maps libcuda scan. Consulted ONLY when the
     primary is INCONCLUSIVE (library present but the symbol path fails
     unexpectedly) — never as an override of a definitive answer.
     (W-PY5 correction: the naive "mapped => refuse" reading would fire
     on CUDA-virgin processes that merely map libcuda, contradicting the
     must-not-tax-virgin-scripts rule. Absent library => definitive safe;
     a clean no-context answer => pass; only "cannot tell" consults maps.)

Over-refusal (false positive) is the safe direction; under-refusal
(allowing fork with a live context) causes UB.
"""

from __future__ import annotations

import ctypes
import os

_HAZARD_MESSAGE = """\
forkrun: refusing to fork workers — a live CUDA context exists in the parent.

The CUDA driver does not support fork() with an active context. Workers
would inherit corrupted driver state, causing undefined behavior.

Fix: spawn forkrun workers BEFORE initializing CUDA:

    # Wrong (what you probably did):
    import torch
    torch.cuda.init()          # or: model.to('cuda')
    forkrun.run(...)           # <- fork with a live context

    # Right:
    forkrun.run(...)           # fork first (CPU-only workers)
    # ... then initialize CUDA in the parent or consumer

GPU work belongs in the parent/consumer (the DataLoader mental model:
swap-in, not restructure). An early-spawn escape hatch for GPU-holding
parents is demand-pulled Stage 6+ work, not a v0 feature.
"""

_HAZARD_MESSAGE_CONSERVATIVE = """\
forkrun: refusing to fork workers — possible CUDA state in the parent.

The primary context check was inconclusive, but a CUDA library mapping
was detected. This may indicate driver state that fork() would corrupt,
so this is a conservative refusal (over-refusal is the safe direction).

Fix: spawn workers before importing or initializing CUDA. If you are
certain no CUDA state exists, isolate the forkrun call in a fresh
(CUDA-virgin) process.
"""


def _live_context_check():
    """Tri-state primary check.

    Returns True (live context — refuse), False (definitively safe), or
    None (inconclusive — consult the fallback). Library-absent is
    definitive safe: no libcuda, no context, no hazard.
    """
    try:
        # RTLD_NOLOAD lives on os, not ctypes: resolve without loading.
        lib = ctypes.CDLL("libcuda.so.1", mode=os.RTLD_NOLOAD)
    except OSError:
        return False  # not loaded => no context can exist
    try:
        current = lib.cuCtxGetCurrent
    except AttributeError:
        return None  # loaded but unreadable => cannot tell
    try:
        current.restype = ctypes.c_int
        current.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        ctx = ctypes.c_void_p()
        rc = current(ctypes.byref(ctx))
    except Exception:  # noqa: BLE001
        return None  # call failed unexpectedly => cannot tell
    if rc == 0 and ctx.value is not None:
        return True
    return False


def _libcuda_mapped() -> bool:
    """Fallback: True if any libcuda mapping exists in this process."""
    try:
        with open("/proc/self/maps", "r") as fh:
            for line in fh:
                if "libcuda" in line:
                    return True
    except OSError:
        pass
    return False


def check_cuda_hazard() -> tuple[bool, str]:
    """Check for CUDA-fork hazard in THIS process (call pre-fork).

    Returns (hazard: bool, message: str). hazard True => the caller must
    refuse to fork; message names the fix.
    """
    verdict = _live_context_check()
    if verdict is True:
        return True, _HAZARD_MESSAGE
    if verdict is False:
        return False, ""
    # Inconclusive primary: conservative fallback.
    if _libcuda_mapped():
        return True, _HAZARD_MESSAGE_CONSERVATIVE
    return False, ""


__all__ = ["check_cuda_hazard"]
