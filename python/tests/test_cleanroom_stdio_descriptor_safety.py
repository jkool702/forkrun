"""F6 Stage 4: standard-stream descriptor safety on the cleanroom routes.

Stage 3 introduced `_fd_above_stdio()` so a route-owned descriptor can never
be aliased by -- or alias -- the host's standard streams. It shipped two
defects that only matter once every caller can reach the route (i.e. once it
is the DEFAULT backend). Both were found by audit, not by the Stage 3 suite.

DEFECT 1 -- `_fd_above_stdio()` could return a descriptor <= 2.
    It relocated with `os.dup()`, which returns the LOWEST FREE descriptor.
    That is not a relocation at all when the gap is partly occupied:
    relocating a descriptor sitting on fd 1 while fd 0 is busy and fd 2 is
    free returns fd 2; with fd 1/2 busy it returns fd 0. Deterministic
    reproduction before the fix:

        close fd 0 and fd 2; put the source on fd 1
        -> _fd_above_stdio(1) returned 0

    The Stage 3 low-FD matrix closed ALL THREE of fd 0/1/2, leaving the gap
    empty so the lowest free descriptor happened to be 3. C5 was therefore
    closed only for the one occupancy pattern the test constructed.

DEFECT 2 -- the streaming result pipe was never relocated.
    The streaming shape comments "every route-owned descriptor must sit
    above fd 2" immediately before `os.pipe()`, and nothing relocated
    `rr`/`rw`. `os.pipe()` also returns the lowest free pair, so with the
    gap partly free the ends land inside it -- and `rw` is made inheritable
    and handed to the launcher as `--result`. A `rw` on fd 1 is
    simultaneously the launcher's stdout, a `rw` on fd 2 is its stderr.
    Observed end to end before the fix, with fd 0/1/2 closed:
    `--src 2`, then `2 worker(s) failed without recovery (respawn cap
    reached)`.

Both defects corrupt results SILENTLY when they alias, so the assertions
below are about descriptor NUMBERS and identity, not just "did it run".

NOTE on module access: `forkrun.run` the ATTRIBUTE is the public `run()`
function, which shadows the `forkrun.run` SUBMODULE. The module object must
be reached through `sys.modules['forkrun.run']`.
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

import forkrun  # noqa: E402

_RUN = sys.modules["forkrun.run"]


# The real plugin ABI: a v0 plugin with no forkrun_use_ctx is refused by
# the launcher with exit 78, so a hand-rolled signature is not enough here.
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


def _plugin(tmpdir):
    src = os.path.join(tmpdir, "p.c")
    with open(src, "w") as fh:
        fh.write(_PLUGIN_SRC)
    out = os.path.join(tmpdir, "p.so")
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2",
         "-I", str(REPO / "ring_loadables"), "-o", out, src],
        check=True, capture_output=True, text=True)
    return out + ":copy_v1"


def _sample(tmpdir):
    path = os.path.join(tmpdir, "in.txt")
    with open(path, "w") as fh:
        for i in range(512):
            fh.write("payload %06d\n" % i)
    return path


def _run_child(body, *, close_stdio=False, report=None, timeout=300):
    """Run a child script; optionally close 0/1/2 first and log to `report`."""
    prefix = ""
    if report and not close_stdio:
        prefix += textwrap.dedent("""
            import os, sys
            _LOG = open(%r, 'w')
            sys.stdout = _LOG
            sys.stderr = _LOG

            def log(msg):
                os.write(_LOG.fileno(), (str(msg) + "\\n").encode())
        """ % report)
    if close_stdio:
        prefix += textwrap.dedent("""
            import os, sys
            for _fd in (0, 1, 2):
                try:
                    os.close(_fd)
                except OSError:
                    pass
        """)
        if report:
            # Land the log INSIDE the freed gap so it does not accidentally
            # occupy the numbers the route is supposed to be relocating away
            # from -- otherwise the route looks correct by accident.
            prefix += textwrap.dedent("""
                _LOG = open(%r, 'w')
                sys.stdout = _LOG
                sys.stderr = _LOG

                def log(msg):
                    os.write(_LOG.fileno(), (str(msg) + "\\n").encode())
            """ % report)
    env = dict(os.environ)
    env["FORKRUN_CLEANROOM"] = "1"
    env["PYTHONPATH"] = str(REPO / "python")
    proc = subprocess.run([sys.executable, "-c", prefix + body],
                          capture_output=True, text=True,
                          timeout=timeout, env=env)
    if report:
        return proc, Path(report).read_text()
    return proc, proc.stdout + proc.stderr


def _dedent(src):
    out = textwrap.dedent(src)
    while out.startswith("\n"):
        out = out[1:]
    return out


class TestRelocationLeavesTheStandardStreamGap(unittest.TestCase):
    """DEFECT 1: F_DUPFD, not os.dup()."""

    def _relocate_with_free(self, freed, report):
        """Close `freed`, park a source descriptor on fd 1, relocate it."""
        body = _dedent("""
            import os, sys
            _log = os.open(%r, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            from forkrun.run import _fd_above_stdio
            for target in %r:
                try:
                    os.close(target)
                except OSError:
                    pass
            src, _w = os.pipe()
            os.dup2(src, 1)
            if src != 1:
                os.close(src)
            moved = _fd_above_stdio(1)
            os.write(_log, ("MOVED " + str(moved) + chr(10)).encode())
        """ % (report, freed))
        proc = subprocess.run(
            [sys.executable, "-c", body], capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=str(REPO / "python")),
            timeout=120)
        self.assertEqual(proc.returncode, 0,
                         "relocation child failed: %s" % proc.stderr[-400:])
        return int(Path(report).read_text().split()[1])

    def test_relocation_with_fds_0_and_2_free(self):
        """The exact case os.dup() got wrong: it returned fd 0."""
        moved = self._relocate_with_free(
            [0, 2], "/tmp/fr-reloc-case-a.txt")
        self.assertGreater(moved, 2,
                           "relocation returned %d, which is still inside the "
                           "standard-stream gap (os.dup returns the lowest "
                           "free descriptor, so it can land back in the gap)"
                           % moved)

    def test_relocation_with_fds_1_and_2_free(self):
        moved = self._relocate_with_free(
            [1, 2], "/tmp/fr-reloc-case-b.txt")
        self.assertGreater(moved, 2, "relocation returned %d" % moved)

    def test_relocation_with_only_fd2_free(self):
        moved = self._relocate_with_free(
            [2], "/tmp/fr-reloc-case-c.txt")
        self.assertGreater(moved, 2, "relocation returned %d" % moved)

    def _park_on_fd1(self, src):
        """Put `src` on fd 1 and RESTORE fd 1 when the test finishes.

        These two tests have to exercise the relocation of a descriptor
        that actually sits on fd 1, which means overwriting the test
        runner's own stdout. Forgetting to put it back does not fail here:
        it silently breaks every LATER test in the run that writes to
        stdout, and the damage surfaces hundreds of tests away as
        unrelated failures. (It did exactly that once already.)
        """
        saved = os.dup(1)
        # Cleanups run LAST-IN-FIRST-OUT, so the close must be registered
        # BEFORE the dup2: that makes dup2 run first, while `saved` is
        # still valid.
        self.addCleanup(os.close, saved)
        self.addCleanup(os.dup2, saved, 1)
        os.dup2(src, 1)

    def test_relocation_is_identity_preserving(self):
        """Whatever it returns must be the same open file, and stay open."""
        r, w = os.pipe()
        self.addCleanup(os.close, r)
        self.addCleanup(os.close, w)
        st = os.fstat(r)
        self._park_on_fd1(r)
        moved = _RUN._fd_above_stdio(1)
        self.assertGreater(moved, 2)
        self.addCleanup(os.close, moved)
        after = os.fstat(moved)
        self.assertEqual((after.st_dev, after.st_ino),
                         (st.st_dev, st.st_ino),
                         "relocated descriptor points at a different file")
        # The source descriptor must still be readable at the new number.
        self.assertEqual(os.read(moved, 0), b"")

    def test_relocation_preserves_inheritable_flag(self):
        r, w = os.pipe()
        self.addCleanup(os.close, r)
        self.addCleanup(os.close, w)
        os.set_inheritable(r, True)
        self._park_on_fd1(r)
        moved = _RUN._fd_above_stdio(1)
        self.addCleanup(os.close, moved)
        self.assertTrue(os.get_inheritable(moved),
                        "FD_CLOEXEC was not cleared on the relocated "
                        "descriptor, so it would not cross exec")

    def test_stdout_is_still_usable_afterwards(self):
        """The guard for the guard: this suite must not leak fd damage."""
        before = os.fstat(1)
        self._park_on_fd1(os.open("/dev/null", os.O_RDONLY))
        after = os.fstat(1)
        self.assertNotEqual(
            (before.st_dev, before.st_ino), (after.st_dev, after.st_ino),
            "sanity: fd 1 really was replaced during the test")
        self.doCleanups()
        restored = os.fstat(1)
        self.assertEqual((restored.st_dev, restored.st_ino),
                         (before.st_dev, before.st_ino),
                         "fd 1 was not restored, so every later test that "
                         "writes to stdout is broken")

    def test_already_high_descriptor_is_returned_unchanged(self):
        r, w = os.pipe()
        try:
            self.assertEqual(_RUN._fd_above_stdio(r), r)
        finally:
            for fd in {r, w}:
                try:
                    os.close(fd)
                except OSError:
                    pass


class TestRouteDescriptorsAboveStdioBothShapes(unittest.TestCase):
    """Both routes must hand the launcher only descriptors > 2."""

    def _spy_argv(self, tmpdir, shape):
        report = "/tmp/fr-route-argv-%s.txt" % shape
        body = _dedent("""
            import os, sys, tempfile
            import forkrun
            R = sys.modules['forkrun.run']
            _cap = []
            _real = R._spawn_or_fork
            def _spy(launcher, argv, actions):
                _cap.append(list(argv))
                return _real(launcher, argv, actions)
            R._spawn_or_fork = _spy
            _tmp = tempfile.mkdtemp()
            _src = os.path.join(_tmp, 'in.txt')
            with open(_src, 'w') as _fh:
                for _i in range(512):
                    _fh.write('payload %%06d\\n' %% _i)
            _so = %r
            _n = -1
            try:
                if %r == 'map':
                    _n = len(forkrun.map(_so, _src, mode='plugin',
                                         workers=2, lines=64, nodes=1))
                else:
                    _n = 0
                    for _c in forkrun.stream(_so, _src, streaming=True,
                                             mode='plugin', workers=2,
                                             lines=64, nodes=1,
                                             output='bytes'):
                        _n += 1
            except BaseException as _e:
                log('FAILED ' + type(_e).__name__ + ': ' + str(_e)[:160])
            _a = _cap[0]
            for _k in ('--src', '--result', '--stats-fd'):
                log('%%s=%%s' %% (_k, _a[_a.index(_k) + 1]))
            log('UNITS %%d' %% _n)
        """ % (_plugin(tmpdir), shape))
        return _run_child(body, close_stdio=True, report=report)

    def test_map_route_descriptors_are_above_stdio(self):
        tmpdir = tempfile.mkdtemp()
        proc, out = self._spy_argv(tmpdir, "map")
        self.assertNotIn("FAILED", out, out)
        vals = {}
        for line in out.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                vals[key.strip()] = val.strip()
            elif " " in line:
                key, _, val = line.partition(" ")
                vals[key.strip()] = val.strip()
        for key in ("--src", "--result", "--stats-fd"):
            self.assertIn(key, vals, out)
            self.assertGreater(int(vals[key]), 2,
                               "%s landed on a standard-stream number: %s"
                               % (key, out))

    def test_stream_route_descriptors_are_above_stdio(self):
        tmpdir = tempfile.mkdtemp()
        proc, out = self._spy_argv(tmpdir, "stream")
        self.assertNotIn("FAILED", out, out)
        vals = {}
        for line in out.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                vals[key.strip()] = val.strip()
            elif " " in line:
                key, _, val = line.partition(" ")
                vals[key.strip()] = val.strip()
        for key in ("--src", "--result", "--stats-fd"):
            self.assertIn(key, vals, out)
            self.assertGreater(int(vals[key]), 2,
                               "%s landed on a standard-stream number: %s"
                               % (key, out))
        self.assertIn("UNITS", out, out)
        self.assertGreater(int(vals["UNITS"]), 0, out)


class TestStreamingPipeEndsAreRelocated(unittest.TestCase):
    """DEFECT 2, isolated so the test actually discriminates.

    Every other streaming test lets the SOURCE descriptor consume a
    standard-stream number first, which pushes the pipe above the gap by
    accident -- so removing the `rr`/`rw` relocation does not make them
    fail. This case keeps all of fd 0/1/2 genuinely free (the log is opened
    BEFORE they are closed) so the pipe is forced to land in the gap:

        pre-fix : --src 1, --result 2   (the launcher's own stderr)
        post-fix: --src 4, --result 6

    Everything is imported and the log is opened before the standard
    streams are closed, so the child never needs to write a diagnostic
    through a descriptor it just closed.
    """

    def test_pipe_ends_avoid_a_fully_free_standard_stream_gap(self):
        report = "/tmp/fr-pipe-ends.txt"
        body = _dedent("""
            import os, sys, tempfile
            import forkrun
            R = sys.modules['forkrun.run']
            _log = os.open(REPORT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            _cap = []
            _real = R._spawn_or_fork

            def _spy(launcher, argv, actions):
                _cap.append(list(argv))
                return _real(launcher, argv, actions)

            R._spawn_or_fork = _spy
            _tmp = tempfile.mkdtemp()
            _src = os.path.join(_tmp, 'in.txt')
            _fd = os.open(_src, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            _blob = b''.join(
                b'payload ' + format(i, '06d').encode() + bytes([10])
                for i in range(512))
            os.write(_fd, _blob)
            os.close(_fd)
            # Only now take the standard streams away, so every one of
            # 0/1/2 is genuinely free when the route allocates.
            for _t in (0, 1, 2):
                try:
                    os.close(_t)
                except OSError:
                    pass
            _n = -1
            try:
                for _c in forkrun.stream(SPEC, _src, streaming=True,
                                         mode='plugin', workers=2,
                                         lines=64, nodes=1, output='bytes'):
                    _n += 1
                os.write(_log, ('UNITS ' + str(_n) + chr(10)).encode())
            except BaseException as _e:
                os.write(_log, ('FAILED ' + type(_e).__name__ + chr(10)).encode())
            _a = _cap[0]
            for _k in ('--src', '--result', '--stats-fd'):
                os.write(_log, (_k + '=' + _a[_a.index(_k) + 1]
                                + chr(10)).encode())
        """).replace("REPORT", repr(report)).replace(
            "SPEC", repr(_plugin(tempfile.mkdtemp())))
        proc = subprocess.run([sys.executable, "-c", body],
                              capture_output=True, text=True, timeout=300,
                              env=dict(os.environ, FORKRUN_CLEANROOM="1",
                                       PYTHONPATH=str(REPO / "python")))
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        report_text = Path(report).read_text()
        vals = {}
        for line in report_text.splitlines():
            key, _, val = line.partition("=")
            if val:
                vals[key] = val
        self.assertNotIn("FAILED", report_text, report_text)
        for key in ("--src", "--result", "--stats-fd"):
            self.assertIn(key, vals, report_text)
            self.assertGreater(
                int(vals[key]), 2,
                "%s=%s landed in the standard-stream gap; the streaming pipe "
                "ends are not being relocated (%s)"
                % (key, vals.get(key), report_text))
        self.assertGreater(int(report_text.split("UNITS")[1].split()[0]), 0,
                           report_text)


class TestPartiallyOccupiedStandardStreams(unittest.TestCase):
    """The occupancy pattern the Stage 3 matrix never constructed."""

    def _case(self, occupy):
        tmpdir = tempfile.mkdtemp()
        report = "/tmp/fr-partial-%s.txt" % "_".join(map(str, occupy))
        body = _dedent("""
            import os, sys, tempfile
            import forkrun
            R = sys.modules['forkrun.run']
            _cap = []
            _real = R._spawn_or_fork
            def _spy(launcher, argv, actions):
                _cap.append(list(argv))
                return _real(launcher, argv, actions)
            R._spawn_or_fork = _spy
            for _t in %r:
                try:
                    os.close(_t)
                except OSError:
                    pass
            _tmp = tempfile.mkdtemp()
            _src = os.path.join(_tmp, 'in.txt')
            with open(_src, 'w') as _fh:
                for _i in range(512):
                    _fh.write('payload %%06d\\n' %% _i)
            _n = -1
            try:
                _n = len(forkrun.map(%r, _src, mode='plugin',
                                     workers=2, lines=64, nodes=1))
            except BaseException as _e:
                log('FAILED ' + type(_e).__name__ + ': ' + str(_e)[:160])
                _n = -1
            _a = _cap[0]
            for _k in ('--src', '--result', '--stats-fd'):
                log('%%s=%%s' %% (_k, _a[_a.index(_k) + 1]))
            log('UNITS %%d' %% _n)
        """ % (occupy, _plugin(tmpdir)))
        return _run_child(body, close_stdio=False, report=report)

    def test_map_with_fd0_and_fd2_closed(self):
        """The case that returned fd 0 before the F_DUPFD fix."""
        _proc, out = self._case([0, 2])
        self.assertNotIn("FAILED", out, out)
        vals = {}
        for line in out.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                vals[key.strip()] = val.strip()
            elif " " in line:
                key, _, val = line.partition(" ")
                vals[key.strip()] = val.strip()
        for key in ("--src", "--result", "--stats-fd"):
            self.assertGreater(int(vals[key]), 2,
                               "%s=%s is inside the stdio gap: %s"
                               % (key, vals.get(key), out))
        self.assertEqual(int(vals["UNITS"]), 8, out)

    def test_stream_with_fd0_and_fd2_closed(self):
        _proc, out = self._case([0, 2])
        self.assertNotIn("FAILED", out, out)


class TestCallerOwnedDescriptorsSurviveTheRoute(unittest.TestCase):
    """`_cleanroom_source_fd` dups, so the caller's fd is never consumed."""

    def _body(self, target):
        # No `%%d`-style escapes here: the child source is built by simple
        # substitution so a stray format specifier cannot silently eat an
        # argument (which is how this test first failed).
        return _dedent("""
            import os, sys, tempfile
            import forkrun
            _t = TARGET
            _tmp = tempfile.mkdtemp()
            _src = os.path.join(_tmp, 'in.txt')
            with open(_src, 'w') as _fh:
                for _i in range(512):
                    _fh.write('payload ' + format(_i, '06d') + chr(10))
            _saved = os.dup(_t)
            os.dup2(os.open(_src, os.O_RDONLY), _t)
            _before = os.fstat(_t)
            try:
                _out = forkrun.map(SPEC, _t, mode='plugin',
                                   workers=2, lines=64, nodes=1)
                try:
                    _after = os.fstat(_t)
                    _same = ((_after.st_dev, _after.st_ino)
                             == (_before.st_dev, _before.st_ino))
                except OSError:
                    _same = False
                print('UNITS', len(_out))
                print('INTACT', _same)
            finally:
                os.dup2(_saved, _t)
                os.close(_saved)
        """).replace("TARGET", repr(target)).replace(
            "SPEC", repr(_plugin(tempfile.mkdtemp())))

    def _check(self, target):
        proc, out = _run_child(self._body(target))
        self.assertIn("INTACT True", out, out)
        self.assertIn("UNITS 8", out, out)

    def test_source_on_fd0(self):
        self._check(0)

    def test_source_on_fd1(self):
        self._check(1)

    def test_source_on_fd2(self):
        self._check(2)


if __name__ == "__main__":
    unittest.main()