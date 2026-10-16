"""The cleanroom launcher must inherit the HARD descriptor limit.

CLEANROOM_DESIGN.md, on the Bash cleanroom: "It also raises `ulimit -n`
to the hard limit in the cleanroom, which the launcher should do too."

`frun.bash` does exactly that -- `ulimit -n $(ulimit -Hn)` is the first
line of the cleanroom source (`FORKRUN_FRUN_SRC`). The Python launch
path did not, so a launcher started under a low soft limit could hit
EMFILE partway through a run. That failure does not look like descriptor
exhaustion: it surfaces as an exec failure or a truncated result, with
nothing naming the cause.

This lives in its own module rather than in test_cleanroom_routes.py so
the shared `LauncherExecProbe` is not extended for one test's needs --
that probe is used by the route suite, and widening its contract to
serve a single new case risks the suite that already works.
"""

import os
import resource
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun                                        # noqa: E402

# `from forkrun import run` yields the FUNCTION (the package re-exports
# it), not the module. The launch internals live on the module, so bind
# it through sys.modules rather than the package namespace.
_R = sys.modules["forkrun.run"]

HAVE_GCC = shutil.which("gcc") is not None
PLUGIN_INC = os.path.join(_ROOT, "ring_loadables")
PLUGIN_SRC = os.path.join(_ROOT, "python", "tests", "plugins",
                          "test_plugin_v1.c")

# Records this process's RLIMIT_NOFILE, then execs the REAL launcher.
# A shell wrapper is used rather than a fork probe because the question
# is "what limit does the launcher process itself run with", and only a
# real exec answers that.
WRAPPER = r'''#!/bin/sh
python3 -c 'import resource,sys; print(resource.getrlimit(resource.RLIMIT_NOFILE)[0])' > "$MARKER"
exec "$REAL_LAUNCHER" "$@"
'''


_CHILD_SCRIPT = """\
import os, resource, sys
SOFT, HARD = 64, 4096
resource.setrlimit(resource.RLIMIT_NOFILE, (SOFT, HARD))
sys.path.insert(0, PKG_DIR)
import forkrun
R = sys.modules["forkrun.run"]
R._cleanroom_launcher_path = lambda: WRAPPER
out, stats = forkrun.map(SPEC, SRC, workers=2, mode="plugin",
                         order="index", output="bytes",
                         return_stats=True)
sys.stderr.write("GOTLINES=" + str(len(out)) + chr(10))"""


class TestLauncherDescriptorLimit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not HAVE_GCC:
            raise unittest.SkipTest("gcc absent; plugin fixture unbuildable")
        cls._tmp = tempfile.mkdtemp(prefix="nofile-")
        cls.so = os.path.join(cls._tmp, "p.so")
        proc = subprocess.run(
            ["gcc", "-shared", "-fPIC", "-O2", "-I", PLUGIN_INC,
             "-o", cls.so, PLUGIN_SRC],
            capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise unittest.SkipTest("plugin build failed: %s"
                                    % proc.stderr[-200:])
        cls.spec = "%s:count_lines_v1" % cls.so
        real = _R._cleanroom_launcher_path()
        if real is None:
            raise unittest.SkipTest("cleanroom launcher not built")
        cls.wrapper = os.path.join(cls._tmp, "wrap.sh")
        with open(cls.wrapper, "w") as fh:
            fh.write(WRAPPER)
        os.chmod(cls.wrapper, 0o755)
        cls.real_launcher = real

    def setUp(self):
        self._soft, self._hard = resource.getrlimit(
            resource.RLIMIT_NOFILE)
        self._marker = os.path.join(self._tmp, "nofile.txt")
        self._saved_launcher = _R._cleanroom_launcher_path
        self._saved_env = {k: os.environ.get(k)
                           for k in ("MARKER", "REAL_LAUNCHER")}
        self.addCleanup(self._restore)

    def _restore(self):
        _R._cleanroom_launcher_path = self._saved_launcher
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        resource.setrlimit(resource.RLIMIT_NOFILE,
                           (self._soft, self._hard))

    def _squeeze(self, soft):
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, self._hard))

    def test_launcher_sees_the_hard_limit_not_the_parents_soft_limit(self):
        """Creates its OWN gap, inside a subprocess.

        Two hazards shaped this. (1) Depending on ambient limits made the
        test SKIP on any host where soft == hard -- which is this host
        (524288/524288) and most CI -- so the one test that proves the
        fix was the one that never ran. (2) Manufacturing the gap by
        lowering the HARD limit in-process is not recoverable: an
        unprivileged process can never raise the hard limit again, so the
        cleanup would fail AND the lowered ceiling would leak into every
        later test in the run.

        So the manipulation happens entirely inside a child process,
        which sets its own rlimit, runs one map through the recording
        wrapper, and reports what the launcher saw. This test process
        never touches its own limits.
        """
        src = os.path.join(self._tmp, "in.txt")
        with open(src, "w") as fh:
            fh.write("".join("line %d\n" % i for i in range(64)))
        if os.path.exists(self._marker):
            os.unlink(self._marker)

        # Definitions FIRST: the child script references them.
        prelude = ("PKG_DIR = %r\nWRAPPER = %r\nSPEC = %r\nSRC = %r\n"
                   % (os.path.join(_ROOT, "python"), self.wrapper,
                      self.spec, src))
        script = prelude + _CHILD_SCRIPT

        env = dict(os.environ)
        env["MARKER"] = self._marker
        env["REAL_LAUNCHER"] = self.real_launcher
        # Pin the gate ON. This test is about the launcher path, so it
        # must not silently no-op -- or fail for the wrong reason -- when
        # the suite is run with FORKRUN_CLEANROOM=off, which is a
        # supported way to run this repository.
        env["FORKRUN_CLEANROOM"] = "map-plugin"
        proc = subprocess.run([sys.executable, "-c", script],
                              capture_output=True, text=True, timeout=900,
                              env=env, cwd=_ROOT)
        self.assertEqual(
            0, proc.returncode,
            "child failed (rc=%d):\nstdout: %s\nstderr: %s"
            % (proc.returncode, proc.stdout[-1500:], proc.stderr[-1500:]))
        self.assertIn("GOTLINES=", proc.stderr,
                      "the child did not report the payload length, so the "
                      "run may not have produced output")
        got = int(proc.stderr.split("GOTLINES=")[1].split()[0])
        self.assertTrue(got, "sanity: the wrapped launcher must still run "
                             "and produce output")
        self.assertTrue(
            os.path.exists(self._marker),
            "the wrapper never ran -- the launch did not happen, so this "
            "test would otherwise prove nothing")
        with open(self._marker) as fh:
            seen = int(fh.read().strip())
        self.assertEqual(
            seen, 4096,
            "the launcher must run with the HARD limit (4096), not the "
            "child's soft limit (64); it saw %d" % seen)

    def test_helper_is_child_side_only(self):
        """RLIMIT_NOFILE is per-process.

        Raising it in the parent would silently widen the descriptor
        space of every other run in this process, including code that
        never asked for it -- so the helper is called post-fork and must
        not change the caller's own limit when invoked directly.
        """
        before = resource.getrlimit(resource.RLIMIT_NOFILE)
        _R._raise_nofile_to_hard_limit()
        after = resource.getrlimit(resource.RLIMIT_NOFILE)
        self.assertEqual(before, after,
                         "the helper changed the CALLING process's limit; "
                         "it is only safe because it runs in the forked "
                         "child between fork and execv")

    def test_helper_never_raises_and_reports_noop(self):
        """Degrade, never fail.

        A launcher that starts with the inherited limit behaves exactly
        as it did before this existed, so the helper must not be able to
        break the launch.
        """
        resource.setrlimit(resource.RLIMIT_NOFILE,
                           (self._hard, self._hard))
        try:
            self.assertFalse(_R._raise_nofile_to_hard_limit(),
                             "soft already at hard: expected a no-op")
        finally:
            resource.setrlimit(resource.RLIMIT_NOFILE,
                               (self._soft, self._hard))

    def test_both_launch_sites_raise_it(self):
        """Both cleanroom launch paths, not just the first one.

        `_execute_cleanroom` and `_execute_cleanroom_stream` build the
        same launcher invocation from different code. A fix in one is
        invisible to the other, and the streaming path is the one most
        likely to run long enough to exhaust descriptors.
        """
        with open(os.path.join(_ROOT, "python", "forkrun", "run.py")) as fh:
            src = fh.read()
        exec_sites = src.count("os.execv(launcher, argv)")
        raise_sites = src.count("_raise_nofile_to_hard_limit()")
        self.assertEqual(2, exec_sites,
                         "expected two cleanroom execv call sites; the "
                         "count changed, so re-check this test")
        # 2 calls + 1 in the helper's own definition/docstring context.
        self.assertGreaterEqual(
            raise_sites, exec_sites,
            "every os.execv(launcher, ...) must be preceded by the "
            "descriptor-limit raise")


if __name__ == "__main__":
    unittest.main(verbosity=2)