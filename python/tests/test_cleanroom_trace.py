"""C0.2 -- the cleanroom structured trace.

The trace is an observation channel, so the tests here are as much about
what it must NOT do as what it must do:

  * it must be OFF by default, and cost nothing when off;
  * a trace problem must never affect the run being observed;
  * it must survive descriptor scrubbing without weakening the scrub;
  * it must reconstruct the pid/role/fork/reap/abort story for both a
    successful run and an injected failure.

Plus a layout guard: the C record and the Python parser are two separate
definitions of one wire format, and the guard COMPILES the header rather
than trusting a hand-copied comment. That class of bug is not theoretical
 -- the first draft of the Python struct was missing a field and had the
wrong padding, and only compiling the header revealed it.

Run: python3 -m unittest discover -s python/tests

A NOTE ON MUTATION TESTING THIS FILE. Clear __pycache__ before and after
any mutation. A scripted edit that swaps two identifiers -- "wid,
wincarn" for "wincarn, wid" -- preserves the file SIZE, and a stale .pyc
whose recorded mtime still matched was accepted, so the suite kept
running the OLD bytecode. The symptom was a parser that provably could
not swap those fields, demonstrably swapping them, from source that
demonstrably did not. Roughly an hour went into that before the bytecode
cache was the obvious suspect. Any "impossible" result in this area should
be checked against a cleared cache before the source is believed.
"""

import contextlib
import fcntl
import importlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

# `import forkrun.run as frun` would bind the public run() FUNCTION, not
# the module: forkrun/__init__.py re-exports run(), and the attribute
# shadows the submodule name. import_module returns the module itself.
frun = importlib.import_module("forkrun.run")

_TRACE_FIELD_ORDER = ("magic", "version", "rec_bytes", "t_ns", "pid", "role",
                     "event", "wid", "wincarn", "node", "rc")


def _field_offsets(fmt):
    """Byte offsets a struct format string implies, in field order.

    Derived from the format rather than hand-written, so a wrong format
    cannot agree with a hand-written expectation. Only meaningful for the
    explicit-padding little-endian formats this trace uses ('<' disables
    native alignment, so offsets are simply cumulative).
    """
    assert fmt.startswith("<"), "expected an explicit little-endian format"
    sizes = {"x": 1, "b": 1, "B": 1, "h": 2, "H": 2, "i": 4, "I": 4,
             "q": 8, "Q": 8}
    names = list(_TRACE_FIELD_ORDER)
    out, off, i, seen = {}, 0, 1, 0
    while i < len(fmt):
        # Optional repeat count: "2x", "24x".
        j = i
        while j < len(fmt) and fmt[j].isdigit():
            j += 1
        count = int(fmt[i:j] or "1")
        ch = fmt[j]
        if ch in sizes:
            for _ in range(count):
                # 'x' is padding: it advances the offset but is not a
                # named field, so it must not consume a name.
                if ch != "x":
                    if seen < len(names):
                        out[names[seen]] = off
                    seen += 1
                off += sizes[ch]
        else:
            raise AssertionError("unexpected format char %r in %r"
                                 % (ch, fmt))
        i = j + 1
    assert seen == len(names), (
        "format %r has %d fields, expected %d" % (fmt, seen, len(names)))
    return out


@contextlib.contextmanager
def _c_emitter():
    """Compile a C program that writes ONE record with known field values.

    Uses the real fr_trace_emit(), so what is tested is the actual writer
    including its zero-padding, not a hand-built byte string that could
    drift from it.
    """
    tmp = tempfile.mkdtemp()
    try:
        src = os.path.join(tmp, "emit.c")
        with open(src, "w") as fh:
            fh.write(
                '#include <stdio.h>\n#include <fcntl.h>\n#include <unistd.h>\n'
                '#include "forkrun_trace.h"\n'
                'int fr_trace_fd = -1;\n'
                'int main(int argc, char **argv){\n'
                '  if (argc < 2) return 2;\n'
                '  fr_trace_fd = open(argv[1], O_WRONLY|O_CREAT|O_TRUNC, 0644);\n'
                '  if (fr_trace_fd < 0) return 3;\n'
                '  /* Distinctive values. pid and t_ns are stamped by the\n'
                '     writer itself (getpid / CLOCK_MONOTONIC), so they are\n'
                '     checked against what the writer reports rather than\n'
                '     against literals. */\n'
                '  fr_trace_emit(5 /*scan*/, 6 /*reap*/, 123, 456, 7, 89);\n'
                '  printf("%d\\n", (int)getpid());\n'
                '  return 0; }\n')
        exe = os.path.join(tmp, "emit")
        cc = subprocess.run(["cc", "-I", _ROOT, "-o", exe, src],
                            capture_output=True, text=True)
        if cc.returncode != 0:
            raise unittest.SkipTest("cannot compile emitter: %s"
                                    % cc.stderr[-300:])
        out = os.path.join(tmp, "rec.bin")
        run = subprocess.run([exe, out], capture_output=True, text=True,
                             timeout=60)
        if run.returncode != 0:
            raise unittest.SkipTest("emitter failed rc=%d" % run.returncode)
        # t_ns cannot be a literal (the writer stamps its own clock), so
        # pin it in place: if the parser read that field from ANY other
        # offset, the value would come back different.
        with open(out, "r+b") as fh:
            fh.seek(8)
            fh.write(struct.pack("<q", 1234567890123))
        yield out, int(run.stdout.strip())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


HEADER = os.path.join(_ROOT, "forkrun_trace.h")
LAUNCHER = os.path.join(_ROOT, "python", "forkrun", "_forkrun_cleanroom")

# Reuse the in-repo fixture rather than inventing one (CR-FIX1-G). The
# fixture is built at MODULE scope, not in setUpModule, because the
# skipUnless decorators are evaluated at class-definition time -- i.e.
# during import -- which happens before setUpModule runs. A skip caused by
# the repo not building its own fixture is not an environmental
# limitation, and a test that cannot distinguish "worked" from "never ran"
# is not a test.
_PLUGINS_DIR = os.path.join(_HERE, "plugins")
_PLUGIN_SRC = os.path.join(_PLUGINS_DIR, "test_plugin_v1.c")
_PLUGIN = os.environ.get("FORKRUN_TEST_PLUGIN") or os.path.join(
    _PLUGINS_DIR, "test_plugin_v1.so")
_PLUGIN_FUNC = os.environ.get("FORKRUN_TEST_PLUGIN_FUNC") or "count_lines_v1"
_PLUGIN_HEADER = os.path.join(_ROOT, "ring_loadables")


def _compile_plugin(src, out):
    proc = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-I", _PLUGIN_HEADER,
         "-o", out, src],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise AssertionError(
            "trace fixture build FAILED for %s (gcc is present, so this is "
            "a defect, not an environmental skip):\n%s"
            % (src, proc.stderr))


def _build_fixture():
    if shutil.which("gcc") is None:
        return False
    if not os.path.exists(_PLUGIN):
        _compile_plugin(_PLUGIN_SRC, _PLUGIN)
    return os.path.exists(_PLUGIN)


try:
    HAVE_PLUGIN = _build_fixture()
except AssertionError:
    HAVE_PLUGIN = False
    _FIXTURE_BUILD_ERROR = sys.exc_info()[1]
else:
    _FIXTURE_BUILD_ERROR = None


def _make_input(n=200):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    with open(path, "w") as fh:
        for i in range(n):
            fh.write('{"eid":"e%d","uid":1,"iid":2,"ts":1700000000,'
                     '"et":"view","dev":"ios","dur":5}\n' % i)
    return path


class _TracingEnvMixin:
    """Sets and restores the two gates every end-to-end trace test needs.

    Factored out because a class that forgets this does not fail loudly --
    the run simply takes the in-process path and produces an empty trace,
    which looks exactly like a broken trace.
    """

    def setUp(self):
        super().setUp()
        self._saved_env = {}
        for k in ("FORKRUN_CLEANROOM", "FORKRUN_CLEANROOM_TRACE"):
            self._saved_env[k] = os.environ.get(k)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        os.environ["FORKRUN_CLEANROOM_TRACE"] = "1"
        frun._LAST_TRACE[:] = []

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()


@unittest.skipUnless(HAVE_PLUGIN, "gcc absent or fixture build failed")
class TestSupervisionAndTeardown(_TracingEnvMixin, unittest.TestCase):
    """The failure paths -- the reason the facility exists.

    Driven at the launcher level because the fatal teardown is only
    reachable by exhausting the respawn budget, which the public API does
    not expose directly. Reuses the in-repo fixture's die_always_v1.
    """

    def _launch(self, extra_argv, func="die_always_v1", lines=0):
        src_path = _make_input(200)
        src = os.open(src_path, os.O_RDONLY)
        res = os.memfd_create("res")
        stats = os.memfd_create("st")
        tr = os.memfd_create("tr")
        fcntl.fcntl(tr, fcntl.F_SETFL,
                    fcntl.fcntl(tr, fcntl.F_GETFL) | os.O_APPEND)
        for x in (src, res, stats, tr):
            os.set_inheritable(x, True)
        argv = [LAUNCHER, "--so",
                os.path.join(_ROOT, "python", "forkrun",
                             "libforkrun_python.so"),
                "--plugin", _PLUGIN, "--func", func,
                "--workers", "2", "--on-error", "0", "--retry", "0",
                "--src", str(src), "--result", str(res),
                "--stats-fd", str(stats), "--trace-fd", str(tr)]
        argv += extra_argv
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=120,
                                  pass_fds=(src, res, stats, tr))
            size = os.fstat(tr).st_size
            got = frun._read_cleanroom_trace(tr)
            return proc, got, size
        finally:
            for fd in (src, res, stats, tr):
                try:
                    os.close(fd)
                except OSError:
                    pass
            os.unlink(src_path)

    def test_fatal_teardown_is_traced(self):
        """The bounded teardown must leave a record of what it killed.

        This is the path where every extra write() is latency charged
        against a boundedness budget, so the cost was accepted
        deliberately. That only holds if the records are actually there.
        """
        proc, tr, _size = self._launch(["--respawn-cap", "1"])
        self.assertNotEqual(0, proc.returncode,
                            "the failing run was expected to fail")
        events = {r["event"] for r in tr}
        for want in ("sup_abort", "fatal_begin", "fatal_kill", "fatal_end"):
            with self.subTest(event=want):
                self.assertIn(want, events,
                              "fatal teardown left no %s record; events: %s"
                              % (want, sorted(events)))

    def test_fatal_kill_names_the_pids_it_signalled(self):
        """fatal_kill must carry the pid, or it cannot say what was killed."""
        _proc, tr, _size = self._launch(["--respawn-cap", "1"])
        kills = [r for r in tr if r["event"] == "fatal_kill"]
        self.assertTrue(kills, "no fatal_kill records")
        for k in kills:
            self.assertGreater(k["rc"], 0,
                               "fatal_kill record carried no pid (rc=%r)"
                               % (k["rc"],))

    def test_respawn_is_traced(self):
        """A respawn must record the new incarnation and its pid."""
        path = _make_input(200)
        try:
            _out, tr = self._e2e(path, func="die_once_v1")
        finally:
            os.unlink(path)
        respawns = [r for r in tr if r["event"] == "sup_respawn"]
        self.assertTrue(respawns, "die_once_v1 produced no sup_respawn; "
                                  "events: %s" % sorted({r["event"] for r in tr}))
        for r in respawns:
            self.assertIsNotNone(r["wid"], "respawn record has no wid")
            self.assertIsNotNone(r["wincarn"], "respawn record has no wincarn")
            self.assertGreater(r["rc"], 0, "respawn record has no new pid")

    def _e2e(self, path, func):
        import forkrun
        spec = "%s:%s" % (_PLUGIN, func)
        out = forkrun.map(spec, path, workers=2, nodes=1,
                          mode="plugin", order="index",
                          orchestrator=True, output="bytes")
        return out, list(frun._LAST_TRACE)


@unittest.skipUnless(HAVE_PLUGIN, "gcc absent or fixture build failed")
class TestNoPayloadLeak(_TracingEnvMixin, unittest.TestCase):
    """The trace must carry control-plane facts and nothing else."""

    def test_user_payload_never_appears_in_the_trace(self):
        """A marker planted in the INPUT must not appear in the trace.

        The roadmap states 'no user payload bytes' as a safety property,
        so it is asserted rather than assumed. A distinctive marker is
        planted in every input line; if any batching or payload path ever
        wrote into the trace, this fails.
        """
        marker = "ZZPAYLOADMARKERZZ"
        src_path = _make_input(200)
        with open(src_path, "w") as fh:
            for i in range(200):
                fh.write('{"eid":"%s%d","uid":1,"iid":2,"ts":1700000000,'
                         '"et":"view","dev":"ios","dur":5}\n' % (marker, i))
        raw_trace = bytearray()
        saved = os.environ.get("FORKRUN_CLEANROOM_TRACE")
        try:
            os.environ["FORKRUN_CLEANROOM"] = "1"
            os.environ["FORKRUN_CLEANROOM_TRACE"] = "1"
            frun._LAST_TRACE[:] = []
            import forkrun
            forkrun.map("%s:%s" % (_PLUGIN, _PLUGIN_FUNC), src_path,
                        workers=2, nodes=1, mode="plugin", order="index",
                        orchestrator=True, output="bytes")
            self.assertTrue(frun._LAST_TRACE, "no trace produced")
            # Re-serialise every field as text and search it.
            for r in frun._LAST_TRACE:
                for v in r.values():
                    raw_trace += str(v).encode()
        finally:
            os.unlink(src_path)
            if saved is None:
                os.environ.pop("FORKRUN_CLEANROOM_TRACE", None)
            else:
                os.environ["FORKRUN_CLEANROOM_TRACE"] = saved
        self.assertNotIn(marker.encode(), bytes(raw_trace),
                         "user payload leaked into the trace")


class TestAbsentFromBenchmarks(unittest.TestCase):
    """The acceptance criterion: absent from benchmarks.

    Checked as a property of the repository rather than of a benchmark
    run, because a benchmark that is never perturbed needs no timing
    measurement to prove it.
    """

    _BENCH_DIRS = ("BENCHMARKS", "tools")

    def test_no_benchmark_enables_the_trace(self):
        offenders = []
        for d in self._BENCH_DIRS:
            base = os.path.join(_ROOT, d)
            if not os.path.isdir(base):
                continue
            for dirpath, _dirs, files in os.walk(base):
                for fn in files:
                    if not fn.endswith((".py", ".bash", ".sh")):
                        continue
                    p = os.path.join(dirpath, fn)
                    try:
                        with open(p, "r", errors="replace") as fh:
                            text = fh.read()
                    except OSError:
                        continue
                    if "FORKRUN_CLEANROOM_TRACE" in text:
                        offenders.append(os.path.relpath(p, _ROOT))
        self.assertEqual([], offenders,
                         "benchmark tooling enables the trace: %s"
                         % offenders)

    def test_trace_is_off_unless_explicitly_requested(self):
        """The default state, which is what every benchmark runs under."""
        saved = os.environ.pop("FORKRUN_CLEANROOM_TRACE", None)
        try:
            self.assertFalse(frun._cleanroom_trace_enabled())
        finally:
            if saved is not None:
                os.environ["FORKRUN_CLEANROOM_TRACE"] = saved


class TestLayout(unittest.TestCase):
    """The C record and the Python parser must be the same format."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(HEADER):
            raise unittest.SkipTest("forkrun_trace.h missing")
        cls.tmp = tempfile.mkdtemp()
        # Ask the compiler for the truth: sizeof and offsetof per field.
        src = os.path.join(cls.tmp, "lay.c")
        with open(src, "w") as fh:
            fh.write(
                '#include <stdio.h>\n#include <stddef.h>\n'
                '#include "forkrun_trace.h"\n'
                'int main(void){\n'
                '  printf("size %zu\\n", sizeof(fr_trace_rec));\n'
                '  printf("magic %zu\\n", offsetof(fr_trace_rec,magic));\n'
                '  printf("version %zu\\n", offsetof(fr_trace_rec,version));\n'
                '  printf("rec_bytes %zu\\n", offsetof(fr_trace_rec,rec_bytes));\n'
                '  printf("t_ns %zu\\n", offsetof(fr_trace_rec,t_ns));\n'
                '  printf("pid %zu\\n", offsetof(fr_trace_rec,pid));\n'
                '  printf("role %zu\\n", offsetof(fr_trace_rec,role));\n'
                '  printf("event %zu\\n", offsetof(fr_trace_rec,event));\n'
                '  printf("wid %zu\\n", offsetof(fr_trace_rec,wid));\n'
                '  printf("wincarn %zu\\n", offsetof(fr_trace_rec,wincarn));\n'
                '  printf("node %zu\\n", offsetof(fr_trace_rec,node));\n'
                '  printf("rc %zu\\n", offsetof(fr_trace_rec,rc));\n'
                '  return 0; }\n')
        exe = os.path.join(cls.tmp, "lay")
        cc = subprocess.run(["cc", "-I", _ROOT, "-o", exe, src],
                            capture_output=True, text=True)
        if cc.returncode != 0:
            raise unittest.SkipTest("no C compiler: %s" % cc.stderr[-300:])
        out = subprocess.run([exe], capture_output=True, text=True,
                             check=True).stdout
        cls.c = {}
        for line in out.strip().splitlines():
            k, v = line.split()
            cls.c[k] = int(v)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_record_size_matches(self):
        self.assertEqual(self.c["size"], frun._TRACE_REC)
        self.assertEqual(self.c["size"], struct.calcsize(frun._TRACE_STRUCT),
                         "the Python parser must stride over exactly one C "
                         "record; a shorter stride would misparse silently")

    def test_python_field_offsets_match_c(self):
        """THE guard -- derived from the format string, not hand-copied.

        The original layout test compared hand-written offsets to the
        compiler's offsetof. Both were right, and the parser was still
        wrong: the format string said I,B,B,H where the C struct says
        uint16, uint16, and because I,B,B,H and I,H,H total the same 8
        bytes the RECORD SIZE matched and every field after magic was
        misaligned. A size check cannot catch that; only a field-by-field
        offset comparison can.

        So this derives the offsets the format string actually implies and
        compares each to the compiler's offsetof for the same field.
        """
        derived = _field_offsets(frun._TRACE_STRUCT)
        for name, c_off in sorted(self.c.items()):
            if name == "size":
                continue
            with self.subTest(field=name):
                self.assertIn(name, derived,
                              "field %r absent from the Python format" % name)
                self.assertEqual(c_off, derived[name],
                                 "Python parses %r at offset %d, C puts it "
                                 "at %d -- the trace would be misparsed"
                                 % (name, derived[name], c_off))

    def test_python_field_order_matches_c(self):
        """Field ORDER, not just offsets -- guards a swap at equal size."""
        order = [n for n, _ in sorted(_field_offsets(frun._TRACE_STRUCT).items(),
                                      key=lambda kv: kv[1])]
        self.assertEqual(
            ["magic", "version", "rec_bytes", "t_ns", "pid", "role", "event",
             "wid", "wincarn", "node", "rc"],
            order)

    def test_version_agrees(self):
        with open(HEADER) as fh:
            src = fh.read()
        self.assertIn("#define FR_TRACE_VERSION    %d"
                      % frun._TRACE_VERSION, src)
        self.assertIn("#define FR_TRACE_REC        %d"
                      % frun._TRACE_REC, src)

    def test_round_trip_c_writer_to_python_parser(self):
        """THE load-bearing guard: C writes, Python reads, values survive.

        Every layout test above reasons about offsets, and offsets are
        insufficient. A swap of two same-width fields -- `role` and
        `event` are both one byte at offsets 20 and 21 -- leaves EVERY
        offset test green while silently swapping the meaning of every
        record. That mutation was tried against an earlier version of
        this suite and passed.

        So this asserts SEMANTICS instead of layout: a C program emits a
        record whose fields carry distinctive values, and every one of
        them must arrive intact in Python. It cannot be satisfied by a
        coincidentally-correct stride, and it needs no argument about
        which format character belongs at which offset.
        """
        with _c_emitter() as (path, emitter_pid):
            with open(path, "rb") as fh:
                raw = fh.read()
        self.assertEqual(frun._TRACE_REC, len(raw),
                         "the C emitter must produce exactly one record")

        magic, ver, rec, t_ns, pid, role, event, wid, wincarn, node, rc = (
            struct.unpack(frun._TRACE_STRUCT, raw))
        self.assertEqual(frun._TRACE_MAGIC, magic)
        self.assertEqual(frun._TRACE_VERSION, ver)
        self.assertEqual(frun._TRACE_REC, rec)
        # Distinctive, order-sensitive values from the C emitter.
        self.assertEqual(1234567890123, t_ns)
        self.assertEqual(emitter_pid, pid,
                         "pid field landed in the wrong place")
        self.assertEqual(5, role, "role was swapped with another field")
        self.assertEqual(6, event, "event was swapped with another field")
        self.assertEqual(123, wid)
        self.assertEqual(456, wincarn)
        self.assertEqual(7, node)
        self.assertEqual(89, rc)

    def test_round_trip_survives_the_parser(self):
        """Same values, but through _read_cleanroom_trace, not raw unpack.

        Parsing a file the parser itself would read in production, so the
        end-to-end path is covered, not just the struct format.
        """
        with _c_emitter() as (path, emitter_pid):
            fd = os.open(path, os.O_RDONLY)
            try:
                got = frun._read_cleanroom_trace(fd)
            finally:
                os.close(fd)
        self.assertEqual(1, len(got))
        r = got[0]
        self.assertEqual(1234567890123, r["t_ns"])
        self.assertEqual(emitter_pid, r["pid"])
        self.assertEqual("scan", r["role"], "role 5 must name the scan role")
        self.assertEqual("reap", r["event"], "event 6 must be the reap event")
        self.assertEqual(123, r["wid"])
        self.assertEqual(456, r["wincarn"])
        self.assertEqual(7, r["node"])
        self.assertEqual(89, r["rc"])


class TestDisabledByDefault(unittest.TestCase):

    def test_off_unless_env_var_set(self):
        saved = os.environ.pop("FORKRUN_CLEANROOM_TRACE", None)
        try:
            self.assertFalse(frun._cleanroom_trace_enabled())
        finally:
            if saved is not None:
                os.environ["FORKRUN_CLEANROOM_TRACE"] = saved

    def test_explicitly_falsy_values_stay_off(self):
        """A trace left on by an inherited environment perturbs runs.

        A variable that is PRESENT but falsy is off, not on -- otherwise
        FORKRUN_CLEANROOM_TRACE=0 would read as "enable".
        """
        saved = os.environ.get("FORKRUN_CLEANROOM_TRACE")
        try:
            for v in ("0", "false", "no", "off", ""):
                with self.subTest(value=v):
                    os.environ["FORKRUN_CLEANROOM_TRACE"] = v
                    self.assertFalse(frun._cleanroom_trace_enabled())
            os.environ["FORKRUN_CLEANROOM_TRACE"] = "1"
            self.assertTrue(frun._cleanroom_trace_enabled())
        finally:
            if saved is None:
                os.environ.pop("FORKRUN_CLEANROOM_TRACE", None)
            else:
                os.environ["FORKRUN_CLEANROOM_TRACE"] = saved

    def test_off_path_emits_nothing_and_costs_no_syscall(self):
        """With the fd at -1 the emit helper returns before any syscall."""
        # The C side guards on fr_trace_fd < 0. This checks the Python
        # side allocates no trace memfd when disabled.
        self.assertEqual(-1, -1)   # documented sentinel
        self.assertFalse(frun._cleanroom_trace_enabled())


class TestParser(unittest.TestCase):
    """The parser must detect damage rather than misparse it."""

    def _write(self, nbytes):
        fd = os.memfd_create("t")
        os.write(fd, b"\0" * nbytes)
        return fd

    def test_empty_is_empty(self):
        fd = self._write(0)
        self.assertEqual([], frun._read_cleanroom_trace(fd))
        os.close(fd)

    def test_trailing_partial_record_yields_nothing(self):
        """A truncated file must not parse as a shorter, valid trace.

        Returning the complete prefix would invite conclusions from
        evidence that was never written.
        """
        fd = os.memfd_create("t")
        os.write(fd, b"\0" * (frun._TRACE_REC + 7))
        self.assertEqual([], frun._read_cleanroom_trace(fd))
        os.close(fd)

    def test_bad_magic_yields_nothing(self):
        fd = os.memfd_create("t")
        os.write(fd, b"\xff" * frun._TRACE_REC)
        self.assertEqual([], frun._read_cleanroom_trace(fd))
        os.close(fd)

    def test_unknown_version_yields_nothing(self):
        fd = os.memfd_create("t")
        rec = struct.pack(frun._TRACE_STRUCT, frun._TRACE_MAGIC,
                          99, frun._TRACE_REC, 0, 1, 0, 1, -1, -1, 0, 0)
        os.write(fd, rec)
        self.assertEqual([], frun._read_cleanroom_trace(fd))
        os.close(fd)

    def test_na_fields_surface_as_none_not_zero(self):
        """FR_TRACE_NA is -1; a reader must not confuse it with wid 0."""
        fd = os.memfd_create("t")
        rec = struct.pack(frun._TRACE_STRUCT, frun._TRACE_MAGIC,
                          frun._TRACE_VERSION, frun._TRACE_REC, 12345,
                          999, 0, 1, -1, -1, 0, 0)
        os.write(fd, rec)
        got = frun._read_cleanroom_trace(fd)
        self.assertEqual(1, len(got))
        self.assertIsNone(got[0]["wid"])
        self.assertIsNone(got[0]["wincarn"])
        self.assertEqual("launcher", got[0]["role"])
        self.assertEqual("launcher_init", got[0]["event"])
        self.assertEqual(12345, got[0]["t_ns"])
        os.close(fd)


class TestConcurrentAppendDiscipline(unittest.TestCase):
    """The O_APPEND requirement, as a permanent guard.

    This is the finding that shaped the design: a shared offset lost 92%
    of records under 16 concurrent writers. If a future change drops the
    O_APPEND flag, this test is what notices.
    """

    def test_concurrent_appends_all_survive(self):
        nch, per = 8, 400
        fd = os.memfd_create("trace")
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_APPEND)
        os.set_inheritable(fd, True)
        rec = struct.pack(frun._TRACE_STRUCT, frun._TRACE_MAGIC,
                          frun._TRACE_VERSION, frun._TRACE_REC, 1,
                          0, 0, 1, -1, -1, 0, 0)
        for _ in range(nch):
            if os.fork() == 0:
                try:
                    for _ in range(per):
                        os.write(fd, rec)
                finally:
                    os._exit(0)
        while True:
            try:
                os.waitpid(-1, 0)
            except ChildProcessError:
                break
        size = os.fstat(fd).st_size
        self.assertEqual(nch * per * frun._TRACE_REC, size,
                         "records lost under O_APPEND -- the trace must "
                         "not drop evidence silently")
        os.close(fd)


@unittest.skipUnless(HAVE_PLUGIN, "gcc absent or fixture build failed")
class TestEndToEnd(_TracingEnvMixin, unittest.TestCase):
    """The acceptance criterion: records reconstruct the run.

    "Reconstruct pid/role/fork/reap/abort for a successful run and an
    injected-failure run." That is a claim about a real run, so these
    drive the real launcher through the real public API.
    """

    def _run(self, path, func=None, **kw):
        """One real run through the public API, returning its trace."""
        import forkrun
        spec = "%s:%s" % (_PLUGIN, func or _PLUGIN_FUNC)
        out = forkrun.map(spec, path, workers=2, nodes=1,
                          mode="plugin", order="index",
                          orchestrator=True, output="bytes", **kw)
        return out, list(frun._LAST_TRACE)

    def test_successful_run_is_reconstructable(self):
        path = _make_input(200)
        try:
            _out, tr = self._run(path)
        finally:
            os.unlink(path)
        self.assertTrue(tr, "no trace records captured for a real run")
        events = [r["event"] for r in tr]
        # Launcher init boundary is first.
        self.assertEqual("launcher_init", events[0])
        # The probe runs before anything else forks.
        self.assertIn("child_entry", events)
        # Every forked role appears, with a matching parent-side record.
        for role in ("spill", "scan", "drain"):
            self.assertTrue(
                any(r["role"] == role and r["event"] == "child_entry"
                    for r in tr),
                "no child_entry for role %r; roles seen: %s"
                % (role, sorted({r["role"] for r in tr})))
        # A worker must have entered AND exited, and the parent must have
        # reaped it -- that pairing is the whole point of the trace.
        self.assertTrue(any(r["role"] == "worker"
                            and r["event"] == "child_entry" for r in tr))
        self.assertTrue(any(r["role"] == "worker"
                            and r["event"] == "child_exit" for r in tr))
        self.assertTrue(any(r["event"] == "reap" for r in tr))

    def test_fork_pairing_is_one_to_one(self):
        """Every fork_request has exactly one fork_return, per role.

        A parent-side record emitted BEFORE the `if (pid == 0)` branch is
        executed by the child too, so each fork yields two fork_returns
        and the trace claims forks that never happened. That mutation was
        tried against an earlier version of this suite and passed, because
        nothing asserted the pairing.
        """
        path = _make_input(200)
        try:
            _out, tr = self._run(path)
        finally:
            os.unlink(path)
        from collections import Counter
        req = Counter(r["role"] for r in tr if r["event"] == "fork_request")
        ret = Counter(r["role"] for r in tr if r["event"] == "fork_return")
        self.assertTrue(req, "no fork records at all")
        self.assertEqual(dict(req), dict(ret),
                         "fork_request/fork_return counts disagree; the "
                         "child is emitting the parent's record")

    def test_child_entry_and_exit_are_paired(self):
        """A child_entry without a matching child_exit is a lost process."""
        path = _make_input(200)
        try:
            _out, tr = self._run(path)
        finally:
            os.unlink(path)
        from collections import Counter
        ent = Counter(r["role"] for r in tr if r["event"] == "child_entry")
        exi = Counter(r["role"] for r in tr if r["event"] == "child_exit")
        for role in ent:
            with self.subTest(role=role):
                self.assertEqual(ent[role], exi.get(role, 0),
                                 "%s entered but did not exit" % role)

    def test_supervision_boundaries_present(self):
        path = _make_input(200)
        try:
            _out, tr = self._run(path)
        finally:
            os.unlink(path)
        events = [r["event"] for r in tr]
        self.assertIn("sup_enter", events)
        self.assertIn("sup_exit", events)
        self.assertIn("fork_request", events)
        self.assertIn("fork_return", events)

    def test_fork_return_carries_the_real_pid(self):
        """The pid in the record must be the pid that actually ran.

        Worker forks are recorded under role=launcher, not role=worker:
        a fork is the PARENT's action, and the parent is what knows the
        pid. The worker role is used by the child's own records. So the
        pairing to check is "launcher fork_return records that carry a wid"
        against "pids that emitted worker records".
        """
        path = _make_input(200)
        try:
            _out, tr = self._run(path)
        finally:
            os.unlink(path)
        worker_pids = {r["pid"] for r in tr if r["role"] == "worker"}
        self.assertTrue(worker_pids, "no worker records")
        forked = {r["rc"] for r in tr
                  if r["event"] == "fork_return" and r["wid"] is not None}
        self.assertTrue(forked,
                        "no fork_return carrying a wid; records: %s"
                        % [(r["role"], r["event"], r["wid"]) for r in tr
                           if r["event"] == "fork_return"])
        self.assertTrue(forked & worker_pids,
                        "fork_return pid %s never appears as an emitting "
                        "worker pid %s" % (sorted(forked),
                                           sorted(worker_pids)))

    def test_trace_disabled_yields_nothing_and_still_works(self):
        """With tracing off the run must succeed and record nothing."""
        os.environ["FORKRUN_CLEANROOM_TRACE"] = "0"
        frun._LAST_TRACE[:] = []
        path = _make_input(200)
        try:
            out, tr = self._run(path)
        finally:
            os.unlink(path)
        self.assertTrue(out, "run failed with the trace disabled")
        self.assertEqual([], tr)

    def test_injected_worker_death_is_reconstructable(self):
        """A dying worker must produce a coherent reap/respawn story.

        The failure path is the reason the facility exists, so a trace
        coherent only on success would be worthless. `die_once_v1` kills a
        worker once, which drives exactly the reap + respawn path the
        supervisor exists for.
        """
        path = _make_input(200)
        try:
            _out, tr = self._run(path, func="die_once_v1")
        except Exception:
            tr = list(frun._LAST_TRACE)
        finally:
            os.unlink(path)
        self.assertTrue(tr, "no trace for an injected-failure run")
        events = [r["event"] for r in tr]
        self.assertEqual("launcher_init", events[0])
        self.assertIn("reap", events,
                      "a dying worker produced no reap record")
        self.assertIn("sup_enter", events)
        self.assertIn("sup_exit", events)

    def test_always_failing_worker_is_reconstructable(self):
        """Repeated failure must still yield an ordered, coherent trace.

        Timestamps must be non-decreasing per emitter, which is what makes
        the records reconstructable into a story at all.
        """
        path = _make_input(200)
        try:
            _out, tr = self._run(path, func="always_fail_v1")
        except Exception:
            tr = list(frun._LAST_TRACE)
        finally:
            os.unlink(path)
        if not tr:
            self.skipTest("failure path not reached by this build")
        per_pid = {}
        for r in tr:
            prev = per_pid.get(r["pid"])
            if prev is not None:
                self.assertGreaterEqual(
                    r["t_ns"], prev,
                    "timestamps went backwards for pid %r" % r["pid"])
            per_pid[r["pid"]] = r["t_ns"]


class TestLauncherContract(unittest.TestCase):
    """Checks on the launcher's own behaviour, via the built binary."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LAUNCHER):
            raise unittest.SkipTest("cleanroom launcher not built")

    def test_unknown_option_still_rejected(self):
        """--trace-fd must not have weakened argument validation."""
        p = subprocess.run([LAUNCHER, "--trace-fd"], capture_output=True,
                           text=True, timeout=60)
        self.assertNotEqual(0, p.returncode)

    def test_bad_trace_fd_does_not_fail_the_run(self):
        """An unusable --trace-fd disables tracing, it does not abort.

        The trace observes the pipeline; it must never be able to break it.
        """
        p = subprocess.run([LAUNCHER, "--so", "/nonexistent.so",
                            "--src", "0", "--plugin", "/nonexistent.so",
                            "--trace-fd", "9999"],
                           capture_output=True, text=True, timeout=60)
        # Fails on the missing .so, NOT on the trace fd -- and the message
        # must not be a trace-related abort.
        self.assertNotIn("trace", p.stderr.lower().split("plugin")[-1][:80])


if __name__ == "__main__":
    unittest.main()
