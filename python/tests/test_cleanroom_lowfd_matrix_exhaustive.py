"""F6 Stage 4 audit: EXHAUSTIVE standard-stream closure matrix.

An independent review asked for something the suite did not have: proof
that descriptor placement is correct for EVERY pattern of closed standard
descriptors, not only the combinations that happened to expose the two
Stage 3/4 defects. The existing matrix closed {2}, {0}, {1} and {1,2}.
This file closes all 2^3 = 8 subsets, for both launch backends and both
route shapes.

Three things are asserted per case, and they are deliberately different
kinds of evidence:

  1. DESCRIPTORS. Every route-owned descriptor handed to the launcher
     (`--src`, `--result`, `--stats-fd`) is above 2. This is the
     anti-aliasing property itself. `os.dup()` returns the LOWEST FREE
     descriptor, so it can relocate a descriptor straight back into the
     gap; `fcntl(F_DUPFD, 3)` cannot. Asserting the numbers is the only
     way to catch a regression that happens to be survivable.

  2. RECORDS. The exact number of records is returned, on both shapes.
     "Did not raise" is not the contract -- the contract is that the work
     completes with the right answer.

  3. CONTENT. The exact SET of payload tokens is returned, not merely a
     count of distinct tokens. A route descriptor aliased by another
     channel can produce the right COUNT from the wrong bytes -- that is
     precisely what C5 was, where `src_fd` was overwritten by the error
     memfd and the launcher computed a well-formed result from the error
     channel. Counting tokens catches that only if the wrong source has a
     different token set, which is why the expected set is pinned here.

Every case runs in a subprocess because closing fd 0/1/2 is
irreversible, and the log file is opened BEFORE the closures so the child
never has to write through a descriptor it just closed.
"""

import itertools
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))

EXPECTED_TOKENS = [b"PAYLOAD_%02d" % i for i in range(8)]
BACKENDS = ("forkexec", "posix_spawn")

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


_CHILD = r"""
import os, sys, tempfile
sys.path.insert(0, PYTHON_DIR)
os.environ['FORKRUN_CLEANROOM'] = '1'
os.environ['FORKRUN_RETRY_LIMIT'] = '1'
import forkrun
R = sys.modules['forkrun.run']
R._set_cleanroom_launch_backend(BACKEND)

_log = open(REPORT, 'w')
def log(msg):
    os.write(_log.fileno(), (str(msg) + chr(10)).encode())

_tmp = tempfile.mkdtemp()
_src = os.path.join(_tmp, 'in.txt')
_fd = os.open(_src, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
os.write(_fd, b''.join(TOKENS))
os.close(_fd)

# Close the requested standard streams. The log was opened first, so the
# child never writes through a descriptor it has just closed.
for target in CLOSED:
    try:
        os.close(target)
    except OSError:
        pass

_cap = []
_real = R._spawn_or_fork
def _spy(launcher, argv, actions):
    _cap.append((list(argv), list(actions)))
    return _real(launcher, argv, actions)
R._spawn_or_fork = _spy

def check(shape):
    argv, actions = _cap[-1]
    for key in ('--src', '--result', '--stats-fd'):
        log('%s %s %s' % (shape, key, argv[argv.index(key) + 1]))
    log('%s actions %d' % (shape, len(actions)))
    for act in actions:
        log('%s action %d %d %d' % (shape, act[0], act[1], act[2]))

try:
    out = forkrun.map(SPEC, _src, mode='plugin', workers=2, lines=1)
    blob = b''.join(bytes(b) for b in out)
    log('MAP records %d' % len(out))
    log('MAP tokens %s' % ','.join(
        t.decode() for t in sorted(set(
            t for t in blob.split() if t.startswith(b'PAYLOAD')))))
    check('MAP')
except BaseException as _e:
    log('MAP raised %s %s' % (type(_e).__name__, str(_e)[:120]))

try:
    gen = forkrun.stream(SPEC, _src, mode='plugin', workers=2, lines=1,
                         streaming=True)
    recs = list(gen)
    gen.close()
    blob = b''.join(recs)
    log('STREAM records %d' % len(recs))
    log('STREAM tokens %s' % ','.join(
        t.decode() for t in sorted(set(
            t for t in blob.split() if t.startswith(b'PAYLOAD')))))
    check('STREAM')
except BaseException as _e:
    log('STREAM raised %s %s' % (type(_e).__name__, str(_e)[:120]))
"""


class TestExhaustiveStandardStreamMatrix(unittest.TestCase):
    """All 8 subsets of {0,1,2}, both backends, both shapes."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="s4-matrix-")
        cls.spec = _build(cls._tmp)

    def _run(self, closed, backend):
        report = "/tmp/fr-matrix-%s-%s.txt" % (
            backend, "-".join(map(str, closed)) or "none")
        if os.path.exists(report):
            os.unlink(report)
        body = textwrap.dedent(_CHILD)
        body = (body
                .replace("PYTHON_DIR", repr(str(REPO / "python")))
                .replace("BACKEND", repr(backend))
                .replace("REPORT", repr(report))
                .replace("SPEC", repr(self.spec))
                .replace("CLOSED", repr(list(closed)))
                .replace("TOKENS", repr(
                    [t + b"\n" for t in EXPECTED_TOKENS])))
        proc = subprocess.run([sys.executable, "-c", body],
                              capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0,
                         "child failed for %s/%s: %s"
                         % (backend, closed, proc.stderr[-500:]))
        self.assertTrue(os.path.exists(report),
                        "child wrote no report for %s/%s: %s"
                        % (backend, closed, proc.stderr[-500:]))
        return Path(report).read_text()

    def _assert_case(self, closed, backend, report):
        label = "closed=%s backend=%s" % (list(closed) or "none", backend)
        self.assertNotIn("raised", report,
                         "%s: the route failed instead of completing\n%s"
                         % (label, report))

        for shape in ("MAP", "STREAM"):
            records = None
            for line in report.splitlines():
                if line.startswith("%s records " % shape):
                    records = int(line.split()[-1])
            self.assertIsNotNone(records, "%s/%s: no record count\n%s"
                                 % (label, shape, report))
            self.assertEqual(records, len(EXPECTED_TOKENS),
                             "%s/%s returned %d records, expected %d. A "
                             "short or empty result here is silent data loss."
                             % (label, shape, records, len(EXPECTED_TOKENS)))

            tokens = None
            for line in report.splitlines():
                if line.startswith("%s tokens " % shape):
                    tokens = [t for t in line.split(" ", 2)[2].split(",") if t]
            self.assertEqual(
                [t.encode() for t in tokens or []], EXPECTED_TOKENS,
                "%s/%s returned the wrong PAYLOAD tokens. A correct record "
                "COUNT with wrong CONTENT means the route read some other "
                "descriptor -- the C5 failure mode.\n%s"
                % (label, shape, report))

            for line in report.splitlines():
                if not line.startswith("%s --" % shape):
                    continue
                _shape, key, value = line.split()
                self.assertGreater(
                    int(value), 2,
                    "%s/%s: %s=%s is inside the standard-stream gap (closed=%s)"
                    % (label, shape, key, value, list(closed)))

    def test_all_subsets_both_backends(self):
        subsets = []
        for size in range(4):
            subsets.extend(itertools.combinations((0, 1, 2), size))
        self.assertEqual(len(subsets), 8)
        for closed in subsets:
            for backend in BACKENDS:
                with self.subTest(closed=closed, backend=backend):
                    report = self._run(closed, backend)
                    self._assert_case(closed, backend, report)

    def test_materialized_action_list_is_exactly_one_dup2_to_two(self):
        """The equivalence-first action list must not drift per pattern."""
        for closed in [(0,), (1,), (2,), (0, 1), (1, 2), (0, 2), (0, 1, 2)]:
            for backend in BACKENDS:
                with self.subTest(closed=closed, backend=backend):
                    report = self._run(closed, backend)
                    dup2 = os.POSIX_SPAWN_DUP2
                    acts = [line.split() for line in report.splitlines()
                            if " action " in line and line.startswith("MAP ")]
                    self.assertEqual(len(acts), 1,
                                     "materialized route must pass exactly one "
                                     "action: %s" % report)
                    shape, _kind, op, src, dst = acts[0]
                    self.assertEqual(int(op), dup2)
                    self.assertEqual(int(dst), 2,
                                     "the DUP2 must target fd 2, the error "
                                     "channel: %s" % report)

    def test_streaming_action_list_is_empty(self):
        for closed in [(2,), (0, 2), (0, 1, 2)]:
            for backend in BACKENDS:
                with self.subTest(closed=closed, backend=backend):
                    report = self._run(closed, backend)
                    acts = [line for line in report.splitlines()
                            if line.startswith("STREAM action ")]
                    self.assertEqual(acts, [],
                                     "the streaming shape must pass NO file "
                                     "actions: %s" % report)


if __name__ == "__main__":
    unittest.main()