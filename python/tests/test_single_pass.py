"""W-PY32 single-pass extraction: byte-identity vs scalar ground truth.

The working-tree ml_plugin_yyjson.c (single-pass foreach + fast
fmt_r4) must produce byte-identical output to the scalar
ml_plugin_medium.c. (The obj_get -> single-pass refactor step was
verified by a manual three-way differential during development;
the scalar leg here is the committed permanent gate.)

Comparison is at the RECORD level (sorted record sets): the
adaptive batcher splits input differently run-to-run, so batch-blob
comparison flags spurious differences on identical record sets.

Generator-impossible residuals (backslash escapes, trailing garbage
after a valid object) are excluded here — they are pinned by
test_yyjson_plugin.py and behave identically in both yyjson
variants by construction (same parse core, same span rules).
"""

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

from _helpers import assert_no_zombies  # noqa: E402
from ml.ml_data_gen import generate_data  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False

import shutil as _shutil

HAVE_GCC = _shutil.which("gcc") is not None

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN_DIR = os.path.join(REPO_ROOT, "python", "benchmarks", "ml",
                                "plugins")


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
    return sorted(r for blob in results for r in blob.split(b"\n")
                  if r)


@unittest.skipUnless(HAVE_LIB, "substrate .so not built")
@unittest.skipUnless(HAVE_GCC, "gcc not available")
class TestSinglePassCorrectness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="singlepass_test_")
        yjsrc = os.path.join(PLUGIN_DIR, "yyjson.c")
        cls.new = _build(
            cls.tmpdir,
            [os.path.join(PLUGIN_DIR, "ml_plugin_yyjson.c"), yjsrc],
            os.path.join(cls.tmpdir, "ml_new.so"))
        cls.scalar = _build(
            cls.tmpdir,
            [os.path.join(PLUGIN_DIR, "ml_plugin_medium.c")],
            os.path.join(cls.tmpdir, "ml_scalar.so"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def tearDown(self):
        assert_no_zombies(self)

    def _run_both(self, path, workers=4):
        specs = {
            "scalar": self.scalar + ":ml_process_medium",
            "new": self.new + ":ml_process_medium_yyjson",
        }
        out = {}
        for tag, spec in specs.items():
            res = forkrun.map(spec, path, mode="plugin",
                              workers=workers, order="index", nodes=1)
            out[tag] = _records(res)
        return out

    def test_clean(self):
        path = os.path.join(self.tmpdir, "sp_clean.jsonl")
        generate_data(path, 30000, variant="medium",
                      malformed_pct=0.0)
        out = self._run_both(path)
        self.assertGreater(len(out["scalar"]), 0)
        self.assertEqual(out["new"], out["scalar"])

    def test_malformed(self):
        path = os.path.join(self.tmpdir, "sp_mal.jsonl")
        generate_data(path, 15000, variant="medium",
                      malformed_pct=10.0)
        out = self._run_both(path)
        self.assertEqual(out["new"], out["scalar"])

    def test_three_way_edge(self):
        """Curated edge lines (all generator-reachable shapes —
        escapes and trailing-garbage excluded: pinned residuals in
        test_yyjson_plugin.py, identical across both yyjson variants
        by construction)."""
        import json as _json

        def _J(o):
            return _json.dumps(o, separators=(",", ":"))

        base = {
            "event_id": "e1", "user_id": "u1", "item_id": "i1",
            "timestamp": 1700000001, "event_type": "click",
            "device": "web", "duration_ms": 5000,
            "scroll_depth": 0.5, "revenue_cents": 100,
            "user_context": {"user_tier": "basic",
                             "num_prev_sessions": 3,
                             "days_since_signup": 10},
            "item_context": {"price_cents": 999, "rating": 4.5},
        }
        lines = [
            _J(base), "", "   ",
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
        fd, path = tempfile.mkstemp(suffix=".jsonl", dir=self.tmpdir)
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        out = self._run_both(path, workers=2)
        self.assertEqual(out["new"], out["scalar"])


if __name__ == "__main__":
    unittest.main()
