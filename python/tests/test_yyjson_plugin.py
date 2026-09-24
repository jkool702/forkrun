"""W-PY30 yyjson plugin: byte-identity vs the scalar medium plugin.

The yyjson plugin (ml_plugin_yyjson.c) must produce byte-identical
output to the scalar plugin (ml_plugin_medium.c) on all generator
shapes (clean + malformed). Comparison is at the RECORD level
(sorted record sets): the adaptive batcher splits input into
batches differently run-to-run, so batch-blob comparison would flag
spurious differences on identical record sets.

Two generator-impossible shapes are documented residuals (locked in
by explicit tests, not silently): backslash escapes in strings
(scalar emits raw bytes, yyjson unescaped text) and trailing garbage
after a valid object (scalar gate accepts, yyjson rejects). The
generator provably emits neither (no escapes in 2000 sampled events;
malformed shapes are truncated/missing/wrong-type/garbage/empty).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "benchmarks"))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402
from ml_data_gen import generate_data, generate_event  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

import shutil as _shutil

HAVE_GCC = _shutil.which("gcc") is not None

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN_DIR = os.path.join(REPO_ROOT, "python", "benchmarks", "plugins")


def _build(tmpdir, srcs, out):
    cmd = ["gcc", "-O3", "-shared", "-fPIC", "-march=native",
           "-I", os.path.join(REPO_ROOT, "ring_loadables"),
           "-o", out] + srcs + ["-lm"]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("plugin build failed:\n%s"
                           % proc.stderr[-2000:])
    return out


def _records(results):
    """Sorted record set (batching-independent comparison)."""
    return sorted(r for blob in results for r in blob.split(b"\n")
                  if r)


def _base_event():
    return {
        "event_id": "e1", "user_id": "u1", "item_id": "i1",
        "timestamp": 1700000001, "event_type": "click",
        "device": "web", "duration_ms": 5000,
        "scroll_depth": 0.5, "revenue_cents": 100,
        "user_context": {"user_tier": "basic",
                         "num_prev_sessions": 3,
                         "days_since_signup": 10},
        "item_context": {"price_cents": 999, "rating": 4.5},
    }


def _J(o):
    return json.dumps(o, separators=(",", ":"))


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
@unittest.skipUnless(HAVE_GCC, "gcc not available")
class TestYyjsonCorrectness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="yyjson_test_")
        cls.scalar = _build(
            cls.tmpdir,
            [os.path.join(PLUGIN_DIR, "ml_plugin_medium.c")],
            os.path.join(cls.tmpdir, "ml_scalar.so"))
        cls.yyjson = _build(
            cls.tmpdir,
            [os.path.join(PLUGIN_DIR, "ml_plugin_yyjson.c"),
             os.path.join(PLUGIN_DIR, "yyjson.c")],
            os.path.join(cls.tmpdir, "ml_yyjson.so"))
        cls.scalar_spec = cls.scalar + ":ml_process_medium"
        cls.yyjson_spec = cls.yyjson + ":ml_process_medium_yyjson"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def tearDown(self):
        assert_no_zombies(self)

    def _run_both(self, path, workers=4):
        a = forkrun.map(self.scalar_spec, path, mode="plugin",
                        workers=workers, order="index")
        b = forkrun.map(self.yyjson_spec, path, mode="plugin",
                        workers=workers, order="index")
        return _records(a), _records(b)

    def _write_input(self, lines):
        fd, path = tempfile.mkstemp(suffix=".jsonl",
                                    dir=self.tmpdir)
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        return path

    def test_output_matches_scalar_clean(self):
        path = os.path.join(self.tmpdir, "clean.jsonl")
        generate_data(path, 20000, variant="medium",
                      malformed_pct=0.0)
        ra, rb = self._run_both(path)
        self.assertGreater(len(ra), 0)
        self.assertEqual(ra, rb)

    def test_output_matches_scalar_malformed(self):
        for pct, n in ((5.0, 20000), (50.0, 5000)):
            path = os.path.join(self.tmpdir, "mal%.0f.jsonl" % pct)
            generate_data(path, n, variant="medium",
                          malformed_pct=pct)
            ra, rb = self._run_both(path)
            self.assertEqual(ra, rb,
                             "divergence at malformed_pct=%s" % pct)

    def test_edge_cases(self):
        """Curated edge lines (all generator-reachable shapes)."""
        base = _base_event()
        lines = [
            _J(base),
            "", "   ",
            _J({**base, "timestamp": "not_a_number"}),
            _J({k: v for k, v in base.items() if k != "device"}),
            _J({k: v for k, v in base.items()
                if k != "duration_ms"}),
            _J({k: v for k, v in base.items()
                if k != "user_context"}),
            _J({k: v for k, v in base.items()
                if k != "item_context"}),
            _J({**base, "duration_ms": 50}),
            _J({**base, "event_type": "bogus"}),
            _J({**base, "device": "watch"}),
            _J({**base, "timestamp": -5, "duration_ms": 5000}),
            _J({**base, "timestamp": 18446744073709551615}),
            _J({**base, "timestamp": 1700000001.5}),
            _J({**base, "scroll_depth": "0.5"}),
            _J({**base, "rating": "x"}),
            _J({**base, "revenue_cents": 0}),
            _J({**base, "user_context": {
                "user_tier": "gold", "num_prev_sessions": "x",
                "days_since_signup": -3}}),
            _J({**base, "item_context": {
                "price_cents": "p", "rating": 123456789}}),
            _J({**base, "extra_field": [1, 2, {"a": 1}]}),
            "[1,2,3]", "12345",
            '{"event_id":"e1","event_id":"e2","user_id":"u1",'
            '"item_id":"i1","timestamp":1700000001,'
            '"event_type":"click","device":"web",'
            '"duration_ms":5000}',
            '{"user_id":"u1","item_id":"i1","timestamp":1700000001,'
            '"event_type":"click","device":"web",'
            '"duration_ms":5000}',
            '{"event_id":}',
        ]
        path = self._write_input(lines)
        ra, rb = self._run_both(path, workers=2)
        self.assertEqual(ra, rb)

    def test_quality_filter_matches(self):
        """Duration/event_type gates agree record-for-record."""
        base = _base_event()
        lines = []
        for dur in (0, 1, 99, 100, 101, 60000, 120000, 120001):
            lines.append(_J({**base, "duration_ms": dur}))
        for et in ("view", "click", "scroll", "hover", "purchase",
                   "skip", "bogus", "", 42):
            lines.append(_J({**base, "event_type": et}))
        path = self._write_input(lines)
        ra, rb = self._run_both(path, workers=2)
        # 6 valid event_types (duration 5000 kept) + 5 kept durations
        # (100/101/60000/120000/120001 — the scalar has no upper
        # duration bound; 0/1/99 filtered; int/str/unknown events
        # skipped). Both plugins must agree exactly.
        self.assertEqual(len(ra), 11)
        self.assertEqual(ra, rb)

    def test_nested_object_extraction(self):
        """user_context/item_context members land in output."""
        base = _base_event()
        lines = [
            _J(base),
            _J({**base, "user_context": {}}),
            _J({**base, "item_context": {}}),
            _J({**base, "user_context": "notanobject"}),
            _J({**base, "item_context": [1, 2]}),
            _J({**base, "user_context": {"user_tier": "premium",
                                         "num_prev_sessions": 0,
                                         "days_since_signup": 0}}),
        ]
        path = self._write_input(lines)
        ra, rb = self._run_both(path, workers=2)
        self.assertEqual(len(ra), 6)
        self.assertEqual(ra, rb)
        # Spot-check decoded fields on the base-event record (ra is
        # a lexicographically sorted record SET — locate it by its
        # unique sess:3 marker, not by position).
        base_recs = [r for r in ra
                     if b'"sess":3' in r and b'"rate":4.5' in r]
        self.assertEqual(len(base_recs), 1)
        fields = dict(
            kv.split(":", 1) for kv in
            base_recs[0].decode().strip("{}").replace('"', "").split(
                ","))
        self.assertEqual(fields["tier"], "1")
        self.assertEqual(fields["sess"], "3")
        self.assertEqual(fields["rate"], "4.5")

    def test_known_residual_escapes(self):
        """Backslash escapes: scalar emits raw bytes, yyjson unescaped
        text. Generator data provably contains no escapes (sampled
        2000 events), so this shape is unreachable in practice —
        locked in here so a behavior change fails loudly."""
        base = _base_event()
        base["event_id"] = 'e"1'
        path = self._write_input([_J(base)])
        ra, rb = self._run_both(path, workers=1)
        self.assertEqual(len(ra), 1)
        self.assertEqual(len(rb), 1)
        self.assertNotEqual(ra, rb)
        self.assertIn(b'e\\"1', ra[0])  # scalar: raw escaped bytes
        self.assertIn('e"1"'.encode("utf-8"), rb[0])  # yyjson: decoded

    def test_known_residual_trailing_garbage(self):
        """Trailing garbage after a valid object: scalar gate accepts
        and emits; yyjson rejects the line. Unreachable from the
        generator (all malformed shapes covered by the battery above)
        — locked in so a behavior change fails loudly."""
        line = ('{"event_id":"e1","user_id":"u1","item_id":"i1",'
                '"timestamp":1700000001,"event_type":"click",'
                '"device":"web","duration_ms":5000} trailing')
        path = self._write_input([line])
        ra, rb = self._run_both(path, workers=1)
        self.assertEqual(len(ra), 1)  # scalar emits
        self.assertEqual(len(rb), 0)  # yyjson skips


if __name__ == "__main__":
    unittest.main()
