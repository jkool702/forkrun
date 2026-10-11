"""DECISION-02 -- the typed terminal-disposition wire format.

The header gained an explicit disposition field (16 -> 24 bytes) so that
"this batch completed with no result" is distinguishable from "this batch
has not arrived yet".

**Why not overload `len == 0`.** Because `len == 0` was ALREADY spoken for.
`fr_py_emit`'s v0 contract and `test_v1_emit.py::test_emit_empty_bytes_writes_empty_record`
both define a zero-length payload as a REAL empty result. Overloading it
would have collapsed None and b"" -- the exact error the external review
caught in the withdrawn Option B. These tests exist so that collapse
cannot come back.

Three properties:
  1. None and b"" stay DISTINCT on the wire.
  2. A completed-but-empty batch DOES produce a record (the disposition),
     so an ordered consumer can advance past it.
  3. Every disposition is EXPLICIT -- nothing is inferred from length.

Run: python3 -m unittest discover -s python/tests
"""

import ctypes
import importlib
import os
import re
import struct
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

_HDR = importlib.import_module("forkrun._worker")._HDR

DISP_DATA = 0
DISP_NO_RESULT = 1


def _lib():
    from forkrun._bindings import find_substrate, get as _get
    if not find_substrate():
        raise unittest.SkipTest("libforkrun_python.so not built")
    return _get()


class TestHeaderLayout(unittest.TestCase):

    def test_header_carries_a_disposition_field(self):
        self.assertEqual(24, _HDR.size)
        self.assertEqual(struct.Struct("<QQII").format, _HDR.format)

    def test_disposition_is_explicit_not_inferred_from_length(self):
        """Both dispositions are representable with len == 0.

        That is the whole point: if only one of them existed, `len == 0`
        would be load-bearing and the ambiguity would be back.
        """
        for disp in (DISP_DATA, DISP_NO_RESULT):
            with self.subTest(disposition=disp):
                raw = _HDR.pack(7, 0, disp, 0)
                idx, ln, got, _r = _HDR.unpack(raw)
                self.assertEqual((7, 0), (idx, ln))
                self.assertEqual(disp, got)

    def test_header_is_eight_byte_aligned(self):
        """Keeps the memfd layout aligned; the struct asserts it in C."""
        self.assertEqual(0, _HDR.size % 8)


class TestNoneAndEmptyBytesStayDistinct(unittest.TestCase):
    """The regression that DECISION-02 exists to prevent."""

    def setUp(self):
        self.lib = _lib()

    def _emit(self, data):
        fd = os.memfd_create("disp")
        r, w = os.pipe()
        self.addCleanup(os.close, fd)
        rc = self.lib.fr_py_emit(fd, w, 1, 5, data,
                                 0 if data is None else len(data))
        os.close(w)
        return fd, rc, os.read(r, 64)

    def test_none_emits_no_record(self):
        """None means "no result" and emits nothing on this path."""
        fd, rc, _sig = self._emit(None)
        self.assertEqual(0, rc)
        self.assertEqual(0, os.fstat(fd).st_size,
                         "NULL data must not write a record")

    def test_empty_bytes_emits_a_data_record_with_len_zero(self):
        """b"" is a REAL empty result and stays DATA -- the v0 contract."""
        fd, rc, _sig = self._emit(b"")
        self.assertEqual(0, rc)
        raw = os.pread(fd, _HDR.size, 0)
        self.assertEqual(_HDR.size, len(raw), "b'' must emit a record")
        idx, ln, disp, _r = _HDR.unpack(raw)
        self.assertEqual((5, 0), (idx, ln))
        self.assertEqual(DISP_DATA, disp,
                         "b'' must be DATA, not NO_RESULT -- this is the "
                         "distinction Option B would have destroyed")

    def test_the_two_are_not_confusable(self):
        """The property, stated directly rather than via both cases."""
        fd_none, _, _ = self._emit(None)
        fd_empty, _, _ = self._emit(b"")
        self.assertNotEqual(
            os.fstat(fd_none).st_size, os.fstat(fd_empty).st_size,
            "None and b'' must differ on the wire")


class TestParserToleratesBoth(unittest.TestCase):

    def _parse(self, blob):
        mod = importlib.import_module("forkrun.run")
        return mod._parse_records(blob)

    def test_parser_reads_the_extended_header(self):
        blob = (_HDR.pack(1, 3, DISP_DATA, 0) + b"abc"
                + _HDR.pack(2, 5, DISP_DATA, 0) + b"hello")
        self.assertEqual([(1, b"abc"), (2, b"hello")], self._parse(blob))

    def test_no_result_record_parses_without_payload(self):
        """A disposition record carries no bytes and must not desync."""
        blob = (_HDR.pack(0, 0, DISP_NO_RESULT, 0)
                + _HDR.pack(1, 2, DISP_DATA, 0) + b"hi")
        got = self._parse(blob)
        self.assertEqual(1, len(got),
                         "the NO_RESULT record has no payload; the DATA "
                         "record after it must still parse")
        self.assertEqual((1, b"hi"), got[0])

    def test_truncated_header_is_dropped_not_raised(self):
        self.assertEqual([], self._parse(b"\x01\x02\x03"))


class TestNoFrozenFileDependsOnTheLayout(unittest.TestCase):
    """The blast-radius question, answered by test rather than by grep.

    Every failure from the disposition change was a DUPLICATED header
    declaration in a test harness. None was the frozen engine. If that ever
    stops being true, this fails -- and the reason it needs saying is that
    "the framing lives only in _shim.c" was my own claim, made from a grep,
    and it turned out to be true about the engine and false about the tests.
    """

    FROZEN = ("forkrun_ring.c", "forkrun_substrate.h", "substratestubs.c")

    def test_no_frozen_file_references_the_record_header(self):
        for name in self.FROZEN:
            path = os.path.join(_ROOT, name)
            with open(path) as fh:
                text = fh.read()
            with self.subTest(file=name):
                self.assertNotIn(
                    "fr_py_record_hdr", text,
                    "%s references the record header; the disposition "
                    "change is no longer engine-free" % name)

    def test_no_frozen_file_parses_the_record_framing(self):
        """A frozen file walking [batch_idx][len] would need the stride."""
        for name in self.FROZEN:
            path = os.path.join(_ROOT, name)
            with open(path) as fh:
                text = fh.read()
            with self.subTest(file=name):
                self.assertNotIn(
                    "fr_py_parse_descriptors", text,
                    "%s parses the record framing" % name)


class TestCFastPathAgrees(unittest.TestCase):
    """The opt-in C parse path must be result-for-result identical.

    FORKRUN_C_PARSE=1 is off by default, so NOTHING in the default suite
    exercises this code. That is exactly how a real defect survived here:
    the disposition field was read into a uint64_t via a 4-byte memcpy,
    leaving the top half uninitialized. The garbage compared unequal to
    FR_DISP_DATA, so the C path skipped EVERY record and returned zero
    descriptors -- and because the garbage came from the stack, a large
    zeroed buffer made it appear to work. No default test failed, because
    no default test called it.

    So: assert equality against the Python splitter directly.
    """

    def _blob(self):
        return (_HDR.pack(0, 3, DISP_DATA, 0) + b"abc"
                + _HDR.pack(1, 0, DISP_NO_RESULT, 0)
                + _HDR.pack(2, 2, DISP_DATA, 0) + b"hi"
                + _HDR.pack(3, 0, DISP_DATA, 0)
                + _HDR.pack(4, 4, DISP_DATA, 0) + b"zzzz")

    def _c_parse(self, blob):
        mod = importlib.import_module("forkrun.run")
        return mod._parse_records_c(blob)

    def test_c_and_python_splitters_agree(self):
        mod = importlib.import_module("forkrun.run")
        blob = self._blob()
        py = mod._split_records(blob)[0]
        c = self._c_parse(blob)
        self.assertIsNotNone(c, "C fast path unavailable")
        self.assertEqual(py, c,
                         "the C descriptor path and the Python splitter "
                         "disagree; map() would return different results "
                         "depending on FORKRUN_C_PARSE")

    def test_c_path_is_not_silently_empty(self):
        """The specific regression: every record skipped.

        A path that returns [] for valid input is worse than one that
        raises -- it looks like "no results", which is a plausible answer.
        """
        blob = self._blob()
        c = self._c_parse(blob)
        self.assertIsNotNone(c)
        self.assertTrue(c, "C parse returned no descriptors for a valid "
                          "stream -- check the disposition read width")

    def test_env_flag_path_agrees(self):
        mod = importlib.import_module("forkrun.run")
        blob = self._blob()
        py = mod._split_records(blob)[0]
        old = os.environ.get("FORKRUN_C_PARSE")
        os.environ["FORKRUN_C_PARSE"] = "1"
        try:
            self.assertEqual(py, mod._parse_records(blob))
        finally:
            if old is None:
                os.environ.pop("FORKRUN_C_PARSE", None)
            else:
                os.environ["FORKRUN_C_PARSE"] = old

    def test_truncated_tail_agrees(self):
        mod = importlib.import_module("forkrun.run")
        blob = self._blob() + _HDR.pack(9, 99, DISP_DATA, 0) + b"short"
        py = mod._split_records(blob)[0]
        c = self._c_parse(blob)
        self.assertIsNotNone(c)
        self.assertEqual(py, c)


class TestEveryEmitterSetsDisposition(unittest.TestCase):
    """A header field left unset on the wire is undefined behaviour.

    The spooled/streamed emitter at _shim.c wrote `batch_idx` and `len`
    and never touched `disposition`. The bytes were whatever was on the
    stack, the reader read them as a control disposition, and EVERY record
    from that path was dropped -- so `mode=splice` returned empty output
    for valid input.

    It is worth a structural guard as well as the behavioural tests,
    because "returns empty instead of raising" is the failure mode that
    behavioural coverage is slowest to notice, and the behavioural
    coverage for that path happened to be in a different file entirely.
    """

    SHIM = os.path.join(_ROOT, "python", "forkrun", "_shim.c")

    def _write_sites(self, text):
        """Each `struct fr_py_record_hdr hdr;` declaration site."""
        out = []
        for m in re.finditer(r"struct fr_py_record_hdr hdr;", text):
            out.append((m.start(), text[m.start():m.start() + 900]))
        return out

    def test_every_written_header_assigns_disposition_and_reserved(self):
        with open(self.SHIM) as fh:
            text = fh.read()
        checked = 0
        for pos, window in self._write_sites(text):
            line = text.count("\n", 0, pos) + 1
            # A read site does not write the struct; skip those.
            if "pread(" in window.split(";")[0] + window[:200] and \
                    "=" not in window.split("}")[0]:
                continue
            if "hdr.disposition" not in window:
                # Only flag sites that assign batch_idx (i.e. a writer).
                if "hdr.batch_idx =" in window:
                    self.fail("header written at _shim.c:%d never assigns "
                              "hdr.disposition -- the disposition would be "
                              "uninitialized stack bytes on the wire"
                              % line)
            checked += 1
        self.assertGreater(checked, 0, "found no header sites at all")


class TestDuplicationIsGone(unittest.TestCase):
    """The root cause of the 17-test blast radius, prevented from recurring.

    Each broken harness had redeclared the layout. Several even said so in a
    comment -- one read "must match forkrun._worker._HDR exactly" -- which is
    an admission it was a duplicate. They now import it.
    """

    REDECLARING = (
        "test_cleanroom.py",
        "test_complete.py",
        "test_wrel5c.py",
        "test_harness.py",
    )

    def _body(self, name):
        with open(os.path.join(_HERE, name)) as fh:
            return fh.read()

    def test_no_test_redeclares_the_record_header(self):
        offenders = []
        for name in self.REDECLARING:
            text = self._body(name)
            if 'struct.Struct("<QQ")' in text:
                offenders.append(name)
        self.assertEqual([], offenders,
                         "these redeclare the record layout instead of "
                         "importing forkrun._worker._HDR: %s" % offenders)


if __name__ == "__main__":
    unittest.main()


class TestTerminalControlDispositions(unittest.TestCase):
    """SKIPPED and POISONED (P5, DECISION-02 section 5.1).

    Before these, a skipped or poisoned batch produced NO record at all,
    which made it indistinguishable on the wire from a worker that died --
    and left an ordered consumer unable to advance the prefix past it,
    because the batch looked like a hole with a record still to come.
    """

    POISONED = 3
    SKIPPED = 2

    def test_the_four_dispositions_are_all_distinct(self):
        vals = {DISP_DATA, DISP_NO_RESULT, self.SKIPPED, self.POISONED}
        self.assertEqual(4, len(vals), "disposition codes must not collide")

    def test_control_records_carry_no_payload(self):
        """Zero length, and NOT DATA. An empty DATA record would make
        poison indistinguishable from a UDF that returned b""."""
        for disp in (self.SKIPPED, self.POISONED):
            with self.subTest(disposition=disp):
                raw = _HDR.pack(3, 0, disp, 0)
                idx, ln, got, _r = _HDR.unpack(raw)
                self.assertEqual(0, ln)
                self.assertNotEqual(DISP_DATA, got)

    def _parse(self, blob):
        mod = importlib.import_module("forkrun.run")
        return mod._parse_records(blob)

    def test_all_control_dispositions_are_filtered_from_results(self):
        """The caller must never see them. map() returns results; a
        poisoned batch is not a result, and surfacing it as b"" is
        exactly the failure DECISION-02 exists to prevent."""
        blob = b"".join(
            _HDR.pack(i, 0, d, 0)
            for i, d in ((0, self.POISONED), (1, self.SKIPPED),
                         (2, DISP_NO_RESULT)))
        blob += _HDR.pack(3, 2, DISP_DATA, 0) + b"ok"
        got = self._parse(blob)
        self.assertEqual([(3, b"ok")], got,
                         "only DATA may reach the caller")

    def test_every_loop_emits_poisoned(self):
        """All four worker loops, including splice.

        A loop that skipped poison silently would leave splice's batches
        unrepresentable on the wire while the other modes were fine.
        """
        with open(os.path.join(_ROOT, "python", "forkrun", "_shim.c")) as fh:
            shim = fh.read()
        for loop in ("fr_py_worker_splice_loop",
                     "fr_py_worker_plugin_loop",
                     "fr_py_worker_spawn_loop",
                     "fr_py_worker_udf_loop"):
            body = _loop_body(shim, loop)
            with self.subTest(loop=loop):
                self.assertIn("claimed.poisoned", body)
                self.assertIn("FR_DISP_POISONED", body)

    def test_the_payload_failure_loops_emit_skipped(self):
        """Splice has no skip arm -- it retries always, by design -- so
        it is deliberately excluded rather than counted as a gap."""
        with open(os.path.join(_ROOT, "python", "forkrun", "_shim.c")) as fh:
            shim = fh.read()
        for loop in ("fr_py_worker_plugin_loop",
                     "fr_py_worker_spawn_loop",
                     "fr_py_worker_udf_loop"):
            body = _loop_body(shim, loop)
            with self.subTest(loop=loop):
                self.assertIn("on_error == 1", body)
                self.assertIn("FR_DISP_SKIPPED", body)
        splice = _loop_body(shim, "fr_py_worker_splice_loop")
        self.assertNotIn("FR_DISP_SKIPPED", splice,
                         "splice does not skip; if it gained on_error, "
                         "revisit this expectation")

    def test_sentinel_slots_stay_silent(self):
        """A zero-length slot is an EOF marker, not a batch outcome.

        Emitting SKIPPED for it would put a terminal disposition on the
        wire for a batch that never existed.
        """
        with open(os.path.join(_ROOT, "python", "forkrun", "_shim.c")) as fh:
            shim = fh.read()
        for loop in ("fr_py_worker_splice_loop",
                     "fr_py_worker_plugin_loop",
                     "fr_py_worker_spawn_loop",
                     "fr_py_worker_udf_loop"):
            body = _loop_body(shim, loop)
            sentinel = body.split("EOF sentinel slot")
            self.assertGreaterEqual(len(sentinel), 2, loop)
            branch = sentinel[1][:400]
            with self.subTest(loop=loop):
                self.assertNotIn("fr_py_emit_disposition", branch,
                                 "the EOF sentinel must not emit a record")


def _loop_body(shim, name):
    start = shim.index("int %s(" % name)
    brace = shim.index("{", start)
    depth = 0
    for i in range(brace, len(shim)):
        if shim[i] == "{":
            depth += 1
        elif shim[i] == "}":
            depth -= 1
            if depth == 0:
                return shim[start:i + 1]
    raise AssertionError("unbalanced braces in %s" % name)
