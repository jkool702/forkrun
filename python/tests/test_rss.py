"""W-PY4.d RSS verification (Stage 4 Phase 3).

The engine is bounded by construction (fixed 1M-slot rings, fallow
reclamation); this suite verifies the PYTHON frontend doesn't reintroduce
buffering that scales with STREAM size:

- run() with None-returning payloads (no output collection): parent peak
  RSS must not grow with input size (5/10/20MB).
- map() identity (output == input): parent peak grows with OUTPUT size
  (collect-all v0.5 is output-sized by design), not faster.

ru_maxrss is a per-process PEAK (monotonic), so each size runs in a FRESH
subprocess driver; deltas between peaks are the measurement. Drivers exit
non-zero on any exactness mismatch, so RSS numbers always describe
correct runs.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: F401,E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))

_DISCARD_DRIVER = "\n".join([
    "import os, resource, sys",
    "sys.path.insert(0, 'python')",
    "import forkrun",
    "def none(batch): return None",
    "forkrun.run(none, sys.argv[1], workers=4, nodes=1)",
    "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)",
])

_IDENTITY_DRIVER = "\n".join([
    "import os, resource, sys",
    "sys.path.insert(0, 'python')",
    "import forkrun",
    "def ident(batch): return bytes(batch.data)",
    "out = forkrun.map(ident, sys.argv[1], workers=4, order='index', nodes=1)",
    "raw = open(sys.argv[1], 'rb').read()",
    "assert b''.join(out) == raw, 'inexact'",
    "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)",
])

# W-REL6-3.2: poisoned-head order="index" path. Batch 0 always fails
# (poison after retries); every other batch is identity. The hole at
# the head forces the reassembly buffer to hold the whole tail until
# EOF -- full-stream buffering by design. lines=100 pins batch 0 to
# exactly the first 100 input lines, so exactness is assertable.
# NOTE: exactness is verified without split()-lists (a 700k-element
# list of an 8MB input would dominate ru_maxrss and measure the test,
# not the product).
_POISON_HEAD_DRIVER = "\n".join([
    "import os, resource, sys",
    "sys.path.insert(0, 'python')",
    "import forkrun",
    "def ph(batch):",
    "    if batch.batch_index == 0: raise ValueError('head poison')",
    "    return bytes(batch.data)",
    "out = forkrun.map(ph, sys.argv[1], workers=4, order='index',",
    "                  lines=100, nodes=1)",
    "raw = open(sys.argv[1], 'rb').read()",
    "off = -1",
    "for _ in range(100): off = raw.index(b'\\n', off + 1)",
    "assert b''.join(out) == raw[off + 1:], 'inexact poison-head output'",
    "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)",
])


def _peak_kb(driver, path):
    proc = subprocess.run(
        [sys.executable, "-c", driver, path],
        capture_output=True, text=True, timeout=600, cwd=REPO_ROOT)
    if proc.returncode != 0:
        raise AssertionError(
            "driver failed for %s:\n%s\n%s"
            % (path, proc.stdout, proc.stderr))
    return int(proc.stdout.strip())


def _sized_input(mb):
    # ~12B/line ("line %d\n"): 1MB ~= 87k lines.
    fd, path = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    lines = int(mb * 1024 * 1024 / 12)
    write_lines(path, lines)
    return path


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestRSSBoundedness(unittest.TestCase):
    def test_no_linear_accumulation(self):
        """4x stream (5→20MB), None outputs: parent peak ~flat."""
        paths = [_sized_input(mb) for mb in (5, 10, 20)]
        try:
            peaks = [_peak_kb(_DISCARD_DRIVER, p) for p in paths]
        finally:
            for p in paths:
                os.unlink(p)
        # ru_maxrss is KB: 30MB headroom across a 15MB stream growth.
        # Linear accumulation would add ~15MB+; bounded adds ~0.
        self.assertLess(peaks[2] - peaks[0], 30 * 1024,
                        "peaks KB: %r" % (peaks,))

    def test_output_bounded_by_output_size(self):
        """Parent growth tracks OUTPUT (collect-all), not stream overhead."""
        paths = [_sized_input(mb) for mb in (2, 4)]
        try:
            peaks = [_peak_kb(_IDENTITY_DRIVER, p) for p in paths]
        finally:
            for p in paths:
                os.unlink(p)
        # Output grows 2MB; parent may grow ~that plus working set.
        # 12MB bound documents output-sized (v1 PIPE drain makes it flat).
        self.assertLess(peaks[1] - peaks[0], 12 * 1024,
                        "peaks KB: %r" % (peaks,))

    def test_poison_head_buffers_tail_only(self):
        """W-REL6-3.2: order="index" behind a poisoned head.

        The hole at batch 0 forces full-tail buffering until EOF (by
        design -- see STREAMING.md). The buffer must hold ~1x the
        output, not multiples: same input through the identity driver
        (no holes) vs the poison-head driver; the peak DELTA must stay
        under 2x the input size (exactness is asserted inside both
        drivers, so these peaks always describe correct runs).
        """
        path = _sized_input(8)
        try:
            nbytes = os.path.getsize(path)
            p_ident = _peak_kb(_IDENTITY_DRIVER, path)
            p_poison = _peak_kb(_POISON_HEAD_DRIVER, path)
        finally:
            os.unlink(path)
        self.assertLess(p_poison - p_ident, 2 * nbytes / 1024,
                        "poison-head peak %dKB vs identity %dKB "
                        "(input %dKB)" % (p_poison, p_ident,
                                          nbytes / 1024))


if __name__ == "__main__":
    unittest.main()
