"""F6 Stage 5: fault injection on the descriptor-relocation guard.

`_fd_above_stdio()` is the last line of defence between the route and the
C5 corruption -- a route descriptor landing on fd 0/1/2, being handed to
the launcher under that number, and the launcher then reading the wrong
descriptor as its input. It therefore has one hard obligation:

    it must NEVER return a descriptor number <= 2.

The Stage 4 implementation broke that obligation under failure. It
swallowed the OSError from the relocation syscall and returned the input
unchanged, so if the kernel could not supply a number at or above 3 --
EMFILE, for instance -- the guard quietly stopped guarding and handed back
the very descriptor it existed to move. Injecting that failure produced a
route that would have launched with `--src 1` and read whatever was on it.

These tests pin the corrected behaviour:

  * a failed relocation RAISES, and the message names the invariant;
  * the descriptor is not leaked -- the function takes ownership, which
    matters because the call sites register with `_RouteFdSet` only after
    it returns, so a raise between creation and registration would leak;
  * the same for a failure to restore the inheritable flag, where guessing
    the direction would either leak a descriptor across exec or hide one
    from the launcher;
  * and, end to end, that the failure reaches the CALLER rather than being
    converted into a silent in-process fallback. Policy B is excluded, and
    a guard that fails open would be a quiet version of it.

HARNESS RULE, learned the hard way in this same work order: every case
here closes fd 0 and/or fd 2, so every case runs in a SUBPROCESS. An
in-process version of this file -- which is what it first contained --
destroys the test runner's own descriptors and takes the rest of the suite
with it. An earlier draft of the F6 descriptor tests did precisely that
and produced 32 unrelated failures hundreds of tests away.

Child source is assembled with str.replace(), never %-formatting: the
embedded child code contains its own %s specifiers, and outer formatting
eats them.

One thing worth recording, because it is easy to get the fault injection
wrong and conclude the guard is untested: `_fd_above_stdio` is a NO-OP when
every route descriptor is already above fd 2, which is the normal case. An
injected fcntl failure is therefore never reached unless the standard
streams are ALSO closed, so that the route's first allocations land inside
the gap. The first draft of these route-level tests injected the fault
without closing stdio, and "passed" by observing that the run returned 8
records -- which says only that the guard had not been called.
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

import forkrun  # noqa: E402,F401  (imported so the module is initialised)

_RUN = sys.modules["forkrun.run"]


_PLUGIN_SRC = (
    '#include "forkrun_plugin.h"\n'
    "#include <stdio.h>\n"
    "int forkrun_use_ctx = FORKRUN_CTX_ENABLE|FORKRUN_CTX_FLAG_RAW;\n"
    "int copy_v1(int argc, char **argv, const struct forkrun_ctx *ctx){\n"
    "  (void)argc; (void)argv;\n"
    "  if(ctx==NULL||ctx->version<2) return -1;\n"
    "  uint64_t n=ctx->batch_byte_length;\n"
    "  const char *in=(const char*)(uintptr_t)ctx->reserved[0];\n"
    "  if(in==NULL) return -1;\n"
    "  if(n==0) return 0;\n"
    "  if(fwrite(in,1,(size_t)n,stdout)!=(size_t)n) return -2;\n"
    "  return fflush(stdout)==0?0:-2;}\n"
)


def _build(tmpdir):
    src = os.path.join(tmpdir, "p.c")
    with open(src, "w") as fh:
        fh.write(_PLUGIN_SRC)
    out = os.path.join(tmpdir, "p.so")
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2",
         "-I", str(REPO / "ring_loadables"), "-o", out, src],
        check=True, capture_output=True, text=True)
    return out + ":copy_v1"


def _corpus(tmpdir):
    path = os.path.join(tmpdir, "in.txt")
    with open(path, "w") as fh:
        for i in range(8):
            fh.write("PAYLOAD_%02d\n" % i)
    return path


# A descriptor parked inside the standard-stream gap, with fd 0 and fd 2
# free. Used by the unit-level cases.
_UNIT_CHILD = textwrap.dedent("""
    import os, sys, fcntl
    sys.path.insert(0, PYTHON_DIR)
    import forkrun
    R = sys.modules['forkrun.run']
    LOG = open(LOGPATH, 'w')

    def log(m):
        os.write(LOG.fileno(), (str(m) + chr(10)).encode())

    MODE = sys.argv[1]
    ERRNO = int(sys.argv[2])

    class FailingFcntl:
        def __init__(self, real):
            self._real = real
        def fcntl(self, fd, cmd, arg=0):
            if cmd == fcntl.F_DUPFD:
                raise OSError(ERRNO, 'injected')
            return self._real.fcntl(fd, cmd, arg)
        def __getattr__(self, n):
            return getattr(self._real, n)

    def park_in_gap():
        # fd 0 and fd 2 free; a live descriptor on fd 1.
        #
        # dup2() CLEARS FD_CLOEXEC on the target, so the flag is restored
        # explicitly. Without that the descriptor is inheritable by
        # construction and the preservation assertion below would pass for
        # the wrong reason.
        os.close(0)
        os.close(2)
        r, w = os.pipe()
        os.dup2(r, 1)
        if r != 1:
            os.close(r)
        os.set_inheritable(1, False)

    def park_on_zero():
        # fd 0 and fd 2 free; a live descriptor on fd 0.
        os.close(0)
        os.close(2)
        r, w = os.pipe()
        os.dup2(r, 0)
        if r != 0:
            os.close(r)

    if MODE == 'return_value':
        park_in_gap()
        R.fcntl = FailingFcntl(fcntl)
        try:
            got = R._fd_above_stdio(1)
            log('RETURNED ' + str(got))
        except BaseException as e:
            log('RAISED ' + type(e).__name__)

    elif MODE == 'flag_restore':
        park_on_zero()
        real_get = os.get_inheritable

        def boom(_fd):
            raise OSError(9, 'Bad file descriptor')

        os.get_inheritable = boom
        try:
            R._fd_above_stdio(0)
            log('RETURNED')
        except OSError as e:
            log('RAISED OSError')
            log('MESSAGE ' + str(e)[:240])
        finally:
            os.get_inheritable = real_get

    elif MODE == 'leak':
        os.close(0)
        os.close(2)
        R.fcntl = FailingFcntl(fcntl)
        before = len(os.listdir('/proc/self/fd'))
        raised = 0
        for _ in range(5):
            fd = os.memfd_create('fr_leak_probe')
            log('PROBE_FD ' + str(fd))
            try:
                R._fd_above_stdio(fd)
            except OSError:
                raised += 1
        log('RAISED ' + str(raised))
        log('FD_BEFORE ' + str(before))
        log('FD_AFTER ' + str(len(os.listdir('/proc/self/fd'))))

    elif MODE == 'healthy':
        park_in_gap()
        try:
            got = R._fd_above_stdio(1)
            log('RETURNED ' + str(got))
            log('INHERITABLE ' + str(os.get_inheritable(got)))
        except BaseException as e:
            log('RAISED ' + type(e).__name__)
""")


class _ChildCase(unittest.TestCase):
    """Runs the unit-level child script. Never touches this process's fds."""

    def _child(self, mode, errno=24):
        log = os.path.join(tempfile.mkdtemp(prefix="fr-fault-"), "log.txt")
        body = (_UNIT_CHILD
                .replace("PYTHON_DIR", repr(str(REPO / "python")))
                .replace("LOGPATH", repr(log)))
        proc = subprocess.run(
            [sys.executable, "-c", body, mode, str(errno)],
            capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0,
                         "child %s failed: %s" % (mode, proc.stderr[-500:]))
        return Path(log).read_text()

    @staticmethod
    def _fields(report):
        out = []
        for line in report.splitlines():
            parts = line.split()
            if len(parts) == 2:
                out.append((parts[0], parts[1]))
        return out


class TestRelocationNeverReturnsInsideTheGap(_ChildCase):
    def test_injected_failure_does_not_yield_a_low_descriptor(self):
        """The obligation, stated once: never <= 2, whatever happens."""
        for errno in (24, 9, 22, 4, 12):
            with self.subTest(errno=errno):
                report = self._child("return_value", errno)
                returned = dict(self._fields(report)).get("RETURNED")
                if returned is not None:
                    self.assertGreater(
                        int(returned), 2,
                        "the guard returned fd %s, which is inside the "
                        "standard-stream gap -- the exact C5 corruption"
                        % returned)
                else:
                    self.assertIn("RAISED", report, report)

    def test_failure_raises_and_names_the_invariant(self):
        report = self._child("return_value", 24)
        self.assertIn("RAISED OSError", report, report)

    def test_failure_does_not_leak_the_descriptor(self):
        """The call sites register with _RouteFdSet only AFTER this
        returns, so a raise between creation and registration would leak."""
        report = self._child("leak")
        fields = dict(self._fields(report))
        probes = [v for k, v in self._fields(report) if k == "PROBE_FD"]
        self.assertEqual(len(probes), 5, report)
        for probe in probes:
            self.assertLessEqual(int(probe), 2,
                                 "the probe must actually need relocation; it "
                                 "landed at %s" % probe)
        self.assertEqual(fields["RAISED"], "5",
                         "every relocation failure must raise: %s" % report)
        self.assertLessEqual(
            int(fields["FD_AFTER"]), int(fields["FD_BEFORE"]) + 1,
            "descriptors leaked on the relocation-failure path: %s" % report)

    def test_flag_restore_failure_raises_and_says_so(self):
        """F_DUPFD clears FD_CLOEXEC, so a failed restore leaves the
        descriptor's close-on-exec state wrong in an unknown direction."""
        report = self._child("flag_restore", 9)
        self.assertIn("RAISED OSError", report, report)
        self.assertIn("inheritable", report,
                      "the error must name what could not be preserved: %s"
                      % report)

    def test_relocation_still_works_when_nothing_is_injected(self):
        """The guard must not have been replaced by an always-raise."""
        report = self._child("healthy")
        self.assertIn("RETURNED", report, report)
        got = int(dict(self._fields(report))["RETURNED"])
        self.assertGreater(got, 2, report)
        self.assertEqual(dict(self._fields(report))["INHERITABLE"], "False",
                         "a pipe end must stay close-on-exec after relocation: "
                         "%s" % report)


# The end-to-end case: the failure must reach the CALLER, not be converted
# into a silent in-process fallback.
_ROUTE_CHILD = textwrap.dedent("""
    import os, sys, fcntl
    sys.path.insert(0, PYTHON_DIR)
    os.environ['FORKRUN_CLEANROOM'] = '1'
    os.environ['FORKRUN_RETRY_LIMIT'] = '1'
    import forkrun
    R = sys.modules['forkrun.run']
    BACKEND = sys.argv[1]
    R._set_cleanroom_launch_backend(BACKEND)
    LOG = open(LOGPATH, 'w')

    def log(m):
        os.write(LOG.fileno(), (str(m) + chr(10)).encode())

    class FailingFcntl:
        def __init__(self, real):
            self._real = real
        def fcntl(self, fd, cmd, arg=0):
            if cmd == fcntl.F_DUPFD:
                raise OSError(24, 'Too many open files')
            return self._real.fcntl(fd, cmd, arg)
        def __getattr__(self, n):
            return getattr(self._real, n)

    # The route only RELOCATES when one of its descriptors lands inside the
    # standard-stream gap. With stdio open, memfd_create hands back numbers
    # above 2 and _fd_above_stdio returns early without ever calling fcntl --
    # so an injected fcntl failure is never reached and the route succeeds.
    # Closing 0/1/2 forces the first allocations into the gap. LOG was opened
    # above, so nothing needs those descriptors.
    for _fd in (0, 1, 2):
        try:
            os.close(_fd)
        except OSError:
            pass

    R.fcntl = FailingFcntl(fcntl)
    try:
        out = forkrun.map(SPEC, SRC, mode='plugin', workers=2, lines=1, nodes=1)
        log('RETURNED ' + str(len(out)))
    except BaseException as e:
        log('RAISED ' + type(e).__name__)
        log('IS_OSERROR ' + str(isinstance(e, OSError)))
        log('MESSAGE ' + str(e)[:200])
""")


class TestRouteSurfacesRelocationFailure(unittest.TestCase):
    def _route_child(self, backend):
        tmpdir = tempfile.mkdtemp(prefix="fr-fault-")
        log = os.path.join(tmpdir, "log.txt")
        body = (_ROUTE_CHILD
                .replace("PYTHON_DIR", repr(str(REPO / "python")))
                .replace("LOGPATH", repr(log))
                .replace("SPEC", repr(_build(tmpdir)))
                .replace("SRC", repr(_corpus(tmpdir))))
        proc = subprocess.run(
            [sys.executable, "-c", body, backend],
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "PYTHONWARNINGS": "ignore"})
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        return Path(log).read_text()

    def test_map_raises_instead_of_silently_falling_back(self):
        report = self._route_child("posix_spawn")
        self.assertIn("RAISED OSError", report,
                      "a relocation failure must surface to the caller: %s"
                      % report)
        self.assertNotIn("RETURNED", report,
                         "the route produced records despite a failed "
                         "relocation, which would be silent corruption: %s"
                         % report)
        self.assertIn("IS_OSERROR True", report, report)

    def test_behaviour_is_identical_on_both_backends(self):
        """The guard sits below the backend switch, so the observable
        failure must not depend on which backend is selected."""
        reports = {}
        for backend in ("forkexec", "posix_spawn"):
            reports[backend] = self._route_child(backend)
            self.assertIn("RAISED OSError", reports[backend],
                          "%s: %s" % (backend, reports[backend]))
        self.assertEqual(
            [line for line in reports["forkexec"].splitlines()
             if line.startswith("RAISED")],
            [line for line in reports["posix_spawn"].splitlines()
             if line.startswith("RAISED")],
            "the two backends disagree about the failure: %r" % reports)

    def test_streaming_route_also_surfaces_the_failure(self):
        tmpdir = tempfile.mkdtemp(prefix="fr-fault-")
        log = os.path.join(tmpdir, "log.txt")
        body = textwrap.dedent("""
            import os, sys, fcntl
            sys.path.insert(0, PYTHON_DIR)
            os.environ['FORKRUN_CLEANROOM'] = '1'
            os.environ['FORKRUN_RETRY_LIMIT'] = '1'
            import forkrun
            R = sys.modules['forkrun.run']
            LOG = open(LOGPATH, 'w')

            def log(m):
                os.write(LOG.fileno(), (str(m) + chr(10)).encode())

            class FailingFcntl:
                def __init__(self, real):
                    self._real = real
                def fcntl(self, fd, cmd, arg=0):
                    if cmd == fcntl.F_DUPFD:
                        raise OSError(24, 'Too many open files')
                    return self._real.fcntl(fd, cmd, arg)
                def __getattr__(self, n):
                    return getattr(self._real, n)

            for _fd in (0, 1, 2):
                try:
                    os.close(_fd)
                except OSError:
                    pass
            R.fcntl = FailingFcntl(fcntl)
            try:
                recs = list(forkrun.stream(SPEC, SRC, mode='plugin',
                                           workers=2, lines=1, nodes=1,
                                           streaming=True))
                log('RETURNED ' + str(len(recs)))
            except BaseException as e:
                log('RAISED ' + type(e).__name__)
        """).replace("PYTHON_DIR", repr(str(REPO / "python"))) \
           .replace("LOGPATH", repr(log)) \
           .replace("SPEC", repr(_build(tmpdir))) \
           .replace("SRC", repr(_corpus(tmpdir)))
        proc = subprocess.run([sys.executable, "-c", body],
                              capture_output=True, text=True, timeout=300,
                              env={**os.environ, "PYTHONWARNINGS": "ignore"})
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        report = Path(log).read_text()
        self.assertIn("RAISED", report,
                      "the streaming route must surface a relocation failure "
                      "too: %s" % report)


if __name__ == "__main__":
    unittest.main()