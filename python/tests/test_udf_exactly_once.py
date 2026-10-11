"""P5 -- exactly-once through a REAL launcher run.

DECISION-02 section 7 recorded this as the open gap: the engine
primitives were proven, and the plugin/UDF loops covered structurally by
the parity test, but no test drove an exec'd launcher into repeated
deaths and then inspected the stream. This is that test.

It found a second real defect on the way. `fr_py_drain_loop` blocks on
the signal pipe and only ever inspects the worker id the signal names,
so a record written WITHOUT a signal never leaves the worker's memfd.
Poison-skip and on_error=skip both complete ACK-SILENT -- correctly, for
the acknowledgement semantics, since nothing was emitted in the payload
sense. But they now DO emit a record, and it was never signalled, so
every POISONED and SKIPPED disposition was written correctly and
delivered to nobody. A disposition the parent cannot observe is not a
disposition; it is the same failure as never emitting it, which is what
POISONED and SKIPPED were introduced to replace.

The fix signals the record (record first, then signal, so the drain can
never be told about bytes that are not there yet). The completion that
follows stays ack-silent: that governs the fallow and order
acknowledgements, and changing it would alter v0 ack parity.

Fault injection uses FORKRUN_TEST_DIE_BEFORE_ACK=n, which kills the
worker AFTER the record is framed but BEFORE the ack -- the only state
where a rollback is both possible and necessary. See DECISION-02
section 7.1 for why the two pre-existing hooks cannot reach it.

Run: make -f Makefile.substrate udf && python3 -m unittest test_udf_exactly_once
"""

import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

from forkrun._worker import _HDR  # noqa: E402

DISP_DATA, DISP_NO_RESULT, DISP_SKIPPED, DISP_POISONED = 0, 1, 2, 3

UDF_SRC = "def up(b):\n    return b.upper()\n"

BATCHES = 5


def _helper():
    from forkrun._udf import helper_path
    return helper_path()


def _launcher():
    return os.path.join(_ROOT, "python", "forkrun", "_forkrun_cleanroom")


def _substrate():
    from forkrun._bindings import find_substrate
    return find_substrate()


def _roots(udf_dir):
    import site
    out = []
    try:
        for p in site.getsitepackages():
            if p not in out and os.path.isdir(p):
                out.append(p)
    except Exception:
        pass
    try:
        u = site.getusersitepackages()
        if isinstance(u, str) and u not in out and os.path.isdir(u):
            out.append(u)
    except Exception:
        pass
    out.append(udf_dir)
    return " ".join(out)


def parse(blob):
    """[(batch_idx, disposition, payload)] -- control records INCLUDED."""
    recs, off, n = [], 0, len(blob)
    while off + _HDR.size <= n:
        idx, ln, disp, _res = _HDR.unpack_from(blob, off)
        off += _HDR.size
        if off + ln > n:
            break                      # partial trailing record
        recs.append((idx, disp, blob[off:off + ln]))
        off += ln
    return recs


@unittest.skipUnless(_helper() and os.path.exists(_launcher()),
                     "udf helper / launcher not built")
class TestLauncherExactlyOnce(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.udf_dir = cls._tmp.name
        with open(os.path.join(cls.udf_dir, "px_udf.py"), "w") as fh:
            fh.write(UDF_SRC)
        cls.src = os.path.join(cls.udf_dir, "in.txt")
        with open(cls.src, "w") as fh:
            fh.writelines("line%06d\n" % i for i in range(BATCHES))
        cls.out = os.path.join(cls.udf_dir, "out.bin")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_launcher(self, die=True):
        env = dict(os.environ)
        if die:
            env["FORKRUN_TEST_DIE_BEFORE_ACK"] = "1"
        else:
            env.pop("FORKRUN_TEST_DIE_BEFORE_ACK", None)
        src_fd = os.open(self.src, os.O_RDONLY)
        out_fd = os.open(self.out, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            argv = [_launcher(),
                    "--so", _substrate(),
                    "--workers", "2", "--lines", "1", "--bytes", "0",
                    "--on-error", "0", "--retry", "3",
                    "--src", str(src_fd), "--result", str(out_fd),
                    "--stats-fd", "-1",
                    "--udf-helper", _helper(),
                    "--udf", "px_udf", "--udf-attr", "up",
                    "--udf-roots", _roots(self.udf_dir)]
            proc = subprocess.run(argv, env=env, pass_fds=(src_fd, out_fd),
                                  capture_output=True, timeout=180)
        finally:
            os.close(src_fd)
            os.close(out_fd)
        with open(self.out, "rb") as fh:
            return proc, fh.read()

    # -- the tests ----------------------------------------------------

    def test_every_batch_reaches_exactly_one_terminal_record(self):
        """The invariant, through a real exec'd launcher.

        Every batch is killed after it frames its record but before it
        acks, repeatedly, until it poisons. Each must still end up with
        exactly ONE record on the wire.
        """
        proc, blob = self.run_launcher(die=True)
        recs = parse(blob)

        seen = {}
        for idx, disp, _payload in recs:
            seen.setdefault(idx, []).append(disp)
        dupes = {i: d for i, d in seen.items() if len(d) > 1}
        self.assertEqual(
            {}, dupes,
            "a batch produced more than one record under repeated death: "
            "%r -- a duplicate shifts every later batch" % (dupes,))

        self.assertEqual(
            sorted(range(BATCHES)), sorted(seen),
            "every published batch must reach a terminal state. Missing: "
            "%r" % (sorted(set(range(BATCHES)) - set(seen)),))

        for idx, disp, _payload in recs:
            self.assertEqual(DISP_POISONED, disp,
                            "batch %d should be POISONED under repeated "
                            "death, got disposition %d" % (idx, disp))

    def test_a_poisoned_disposition_actually_reaches_the_parent(self):
        """The defect this found, stated as its own test.

        Every worker dies before it can ack, so every batch poisons and
        every record on the wire is a POISONED disposition. If the drain
        is not signalled, those records are written correctly and
        delivered to nobody -- and this assertion sees an EMPTY stream.
        """
        _proc, blob = self.run_launcher(die=True)
        recs = parse(blob)
        self.assertTrue(recs,
                        "no records reached the parent: %d poison "
                        "dispositions were written but never signalled, so "
                        "the drain never looked at that worker"
                        % len(recs))
        self.assertEqual(
            BATCHES, len(recs),
            "expected one POISONED record per batch")

    def test_an_unfaulted_run_still_delivers_its_data(self):
        """Control: with no fault the same launcher delivers DATA for
        every batch, so the fault test is not passing because nothing
        ever reaches the parent."""
        _proc, blob = self.run_launcher(die=False)
        recs = parse(blob)
        self.assertEqual(BATCHES, len(recs))
        for idx, disp, payload in recs:
            self.assertEqual(DISP_DATA, disp)
            self.assertEqual("LINE%06d" % idx, payload.decode().strip())


if __name__ == "__main__":
    unittest.main()