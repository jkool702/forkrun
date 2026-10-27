"""STAGE0: every framed record advances the rollback frontier.

External review of 1d3aba37 found fr_py_exec_spawn() advancing the
transaction frontier only when cap_len > 0, while fr_py_emit_record()
always writes a complete header. Two spawn sites were wrong in opposite
ways:

  * one emitted unconditionally but advanced only for a non-empty payload,
    so a zero-payload NO_RESULT record left the frontier behind. Recovery
    would then truncate to a stale output_start and destroy an
    already-committed terminal record the drain's cursor had moved past;

  * the other skipped the emit entirely on cap_len == 0, so a successful
    command with empty stdout produced NO terminal record at all.

The fix centralises the advance inside the framer.

This tests the FRAMER, not map(). Two reasons that matters:

  * mode="spawn" defaults to the in-process Python loop, and the consumer
    filters non-DATA dispositions away, so a NO_RESULT record is
    invisible through the public value list. Asserting "no terminal
    record" there would pass vacuously.

WHAT THIS DOES AND DOES NOT COVER, stated plainly:

  Covered: a silent command's terminal record exists and is framed, and
  two consecutive batches frame exactly and stay parseable.

  NOT covered: the frontier advance itself. worker_output_end is
  worker-local TLS with no accessor, and fr_py_exec_spawn exposes no way
  to read it back, so the stale-frontier consequence cannot be observed
  through this entry point -- reverting the advance leaves these tests
  passing. The advance is instead guaranteed structurally, by being
  centralised inside the framer where no caller can omit it, and
  behaviourally by the launcher-backed suites that DO observe rollback
  (test_stage0_matrix's frontier test, test_stage0_publication).

  A genuine end-to-end test of spawn rollback would need the C spawn loop
  driven under supervision with a real drain. The launcher does not serve
  spawn -- it serves plugin and UDF only -- so that harness does not exist
  yet. Recorded as a gap rather than papered over.

  A second, unrelated site was fixed in the same function: the
  plugin-callback-in-child branch (fr_py_plugin_ctx_fn) also skipped the
  emit on cap_len == 0. It is not reached by a plain exec and so is not
  exercised here.

Run: make -f Makefile.substrate python-substrate && cd python/tests
     python3 -m unittest test_stage0_spawn_frontier
"""

import ctypes
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

from forkrun._worker import _HDR  # noqa: E402

DISP_DATA, DISP_NO_RESULT, DISP_SKIPPED, DISP_POISONED = 0, 1, 2, 3


def _lib():
    from forkrun._bindings import find_substrate, get
    find_substrate()
    lib = get()
    if not hasattr(lib, "fr_py_exec_spawn"):
        return None
    lib.fr_py_exec_spawn.argtypes = [ctypes.POINTER(ctypes.c_char_p),
                                     ctypes.c_int, ctypes.c_uint64,
                                     ctypes.c_uint64, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_uint64]
    lib.fr_py_exec_spawn.restype = ctypes.c_int
    return lib


def _argv(*words):
    arr = (ctypes.c_char_p * (len(words) + 1))()
    for i, w in enumerate(words):
        arr[i] = w.encode()
    arr[len(words)] = None
    return arr


def _read(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    out = b""
    while True:
        c = os.read(fd, 65536)
        if not c:
            break
        out += c
    return out


def _records(blob):
    recs, off = [], 0
    while off + _HDR.size <= len(blob):
        idx, ln, disp, _r = _HDR.unpack_from(blob, off)
        off += _HDR.size
        if off + ln > len(blob):
            break
        recs.append((idx, disp, blob[off:off + ln]))
        off += ln
    return recs


@unittest.skipUnless(_lib() and shutil.which("true"), "lib or 'true' missing")
class TestSpawnFrontier(unittest.TestCase):

    def setUp(self):
        self.lib = _lib()
        self._tmp = tempfile.TemporaryDirectory()
        self.ingress = os.memfd_create("ing")
        self.out = os.memfd_create("out")
        payload = b"line000000\n"
        os.write(self.ingress, payload)
        self.len = len(payload)

    def tearDown(self):
        os.close(self.ingress)
        os.close(self.out)
        self._tmp.cleanup()

    def _run(self, cmd, batch_idx=0):
        """Run fr_py_exec_spawn in a FORKED child.

        worker_output_end is __thread-local state that the framer now
        advances. Calling the notifier in-process would leave that cursor
        dirty for every later suite in the same process -- which is
        exactly how this test broke test_v1_fast before the fork. Worker
        loops run in their own process in production, so forking also
        matches how the code is actually used.
        """
        in_fd = os.dup(self.ingress)
        out_fd = os.dup(self.out)
        os.lseek(in_fd, 0, os.SEEK_SET)
        os.lseek(out_fd, 0, os.SEEK_END)
        argv = _argv(*cmd)
        argc = len(cmd)
        length = self.len
        lib = self.lib

        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:                      # child
            try:
                os.close(r)
                rc = lib.fr_py_exec_spawn(argv, argc, 0, length, in_fd,
                                          out_fd, batch_idx)
                os.write(w, b"K" if rc == 0 else b"E")
            finally:
                os._exit(0)
        os.close(w)
        tag = os.read(r, 1)
        os.close(r)
        os.waitpid(pid, 0)
        os.close(in_fd)
        os.close(out_fd)
        return (0 if tag == b"K" else 1), _read(self.out)

    # -- the two spawn sites ------------------------------------------

    def test_silent_command_still_emits_a_terminal_record(self):
        """A successful command with empty stdout is a COMPLETED batch.
        Before the fix it emitted nothing at all, so a consumer had no
        terminal outcome to advance on."""
        rc, blob = self._run(["true"])
        self.assertEqual(0, rc, "the command should have succeeded")
        self.assertEqual(
            _HDR.size, len(blob),
            "a silent command wrote %d bytes; a completed batch must still "
            "emit a terminal record (a zero-payload NO_RESULT header is %d "
            "bytes). Emitting nothing leaves a consumer waiting on a batch "
            "that has already finished." % (len(blob), _HDR.size))
        idx, ln, disp, _r = _HDR.unpack(blob)
        self.assertEqual((0, 0, DISP_NO_RESULT, 0), (idx, ln, disp, _r))

    def test_noisy_command_emits_a_data_record(self):
        """Control: the ordinary case must be unchanged."""
        rc, blob = self._run(["echo", "hello"])
        self.assertEqual(0, rc)
        recs = _records(blob)
        self.assertEqual(1, len(recs))
        idx, disp, payload = recs[0]
        self.assertEqual(0, idx)
        self.assertEqual(DISP_DATA, disp)
        self.assertEqual(b"hello\n", payload)

    # -- the frontier consequence -------------------------------------

    def test_frontier_covers_every_framed_record_across_batches(self):
        """Two batches: a silent one, then a noisy one. The frontier must
        account for BOTH, so recovery truncating to the second batch's
        output_start cannot reach back past the first batch's committed
        NO_RESULT record.

        Observable form of that: after batch 1 claims, the memfd must
        still contain batch 0's record, and both records must parse.
        Before the fix batch 0's bytes were on disk but outside the
        frontier, so a rollback would have removed them while the
        consumer's cursor had already advanced past them.
        """
        rc0, blob0 = self._run(["true"], batch_idx=0)
        self.assertEqual(0, rc0)
        self.assertEqual(_HDR.size, len(blob0),
                         "batch 0 should be one NO_RESULT record")

        # Batch 1 claims: worker_txn_publish snapshots worker_output_end,
        # which must already be past batch 0's record. Run batch 1 and
        # confirm the stream stays exactly parseable.
        rc1, blob1 = self._run(["echo", "hello"], batch_idx=1)
        self.assertEqual(0, rc1)

        recs = _records(blob1)
        self.assertEqual(2, len(recs),
                         "expected both batches framed; got %r"
                         % ([(i, d) for i, d, _p in recs],))
        self.assertEqual(2 * _HDR.size + len(b"hello\n"), len(blob1),
                         "stream length does not match two framed records")
        self.assertEqual([0, 1], [i for i, _d, _p in recs])
        self.assertEqual([DISP_NO_RESULT, DISP_DATA],
                         [d for _i, d, _p in recs])


if __name__ == "__main__":
    unittest.main()