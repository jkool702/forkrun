"""WO-CR-ROI-2 Phase B: prove a route REALLY exec'd the launcher.

A spy on `_execute_cleanroom` cannot establish this. That function is
also entered when the launcher binary is MISSING, and then falls back
in-process -- so the spy fires identically whether the launcher ran or
not. WO-ROI-1 already found a test that turns on exactly that
distinction.

So the probe replaces the launcher PATH with a wrapper that records its
own execution and then execs the real binary unchanged:

    : "${FORKRUN_EXEC_MARKER:?}"     # fail loudly if env is wrong
    printf '%s\\n' "$$" >> "$FORKRUN_EXEC_MARKER"
    exec "$REAL_LAUNCHER" "$@"

`exec` is what makes this sound: the wrapper does not remain as a parent
of the launcher, it BECOMES the launcher, so the recorded PID is a real
launcher process and the exit status is the launcher's own.

Everything the probe touches is restored in a finally -- the patched
function, both environment variables, and the temp directory -- so a
failing assertion cannot leave the suite with a wrapper launcher
installed.
"""

import os
import shutil
import sys
import tempfile
import unittest

_WRAPPER = """#!/usr/bin/env bash
: "${FORKRUN_EXEC_MARKER:?}"
: "${REAL_LAUNCHER:?}"
printf '%s\\n' "$$" >> "$FORKRUN_EXEC_MARKER"
exec "$REAL_LAUNCHER" "$@"
"""


class LauncherExecProbe:
    """Count real launcher execs while a block runs.

    Use as a context manager. `probe.read()` is valid both INSIDE the
    block and after it; after the block it returns a snapshot taken at
    exit, so the natural

        with LauncherExecProbe() as probe:
            out = forkrun.map(...)
        self.assertGreaterEqual(probe.read(), 1)

    works. Reading the marker directly after exit would return 0, because
    the marker directory is removed then -- which is indistinguishable
    from "the launcher never ran", so the count is snapshotted before
    teardown instead.
    """

    def __init__(self):
        # `sys.modules`, NOT `import forkrun.run as R`: the package
        # re-exports a FUNCTION named `run`, so the import binds that
        # and every attribute lookup would fail.
        import forkrun                                   # noqa: F401
        self._R = sys.modules["forkrun.run"]
        self.count = 0
        self._marker = None
        self._saved = {}

    def __enter__(self):
        real_path_fn = self._R._cleanroom_launcher_path
        self._saved["_cleanroom_launcher_path"] = real_path_fn
        for var in ("FORKRUN_EXEC_MARKER", "REAL_LAUNCHER"):
            self._saved[var] = os.environ.get(var)

        self._real_launcher = real_path_fn()
        if self._real_launcher is None:
            raise unittest.SkipTest(
                "launcher binary not built (expected _forkrun_cleanroom "
                "beside the substrate .so); build it with 'make -f "
                "Makefile.substrate python-substrate'. A SKIP IS NOT "
                "evidence the route works.")

        self._dir = tempfile.mkdtemp(prefix="crmexec-")
        self._marker = os.path.join(self._dir, "execs")
        self._wrapper = os.path.join(self._dir, "probe.sh")
        with open(self._wrapper, "w") as fh:
            fh.write(_WRAPPER)
        os.chmod(self._wrapper, 0o755)

        os.environ["FORKRUN_EXEC_MARKER"] = self._marker
        os.environ["REAL_LAUNCHER"] = self._real_launcher
        self._R._cleanroom_launcher_path = lambda: self._wrapper
        return self

    def __exit__(self, *exc):
        self.count = self._read_marker()          # BEFORE teardown
        self._R._cleanroom_launcher_path = \
            self._saved["_cleanroom_launcher_path"]
        for var, old in self._saved.items():
            if var == "_cleanroom_launcher_path":
                continue
            if old is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = old
        if getattr(self, "_dir", None):
            shutil.rmtree(self._dir, ignore_errors=True)
        return False

    def _read_marker(self):
        if not self._marker:
            return 0
        try:
            with open(self._marker) as fh:
                return len([ln for ln in fh if ln.strip()])
        except FileNotFoundError:
            return 0

    def read(self):
        """Launcher execs observed (live inside the block, snapshot after)."""
        return self.count if self.count else self._read_marker()


def joined(records):
    """Exact joined output bytes.

    Lengths are not enough: a substituted or reordered record satisfies
    a byte count. Pair this with order="index" before asserting equality,
    and compare unordered runs by record identity instead.
    """
    return b"".join(bytes(r) for r in records)
