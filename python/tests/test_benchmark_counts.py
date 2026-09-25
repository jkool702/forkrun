"""Exact benchmark totals: filtered records emit blanks (W-PY42 follow-up).

Payload convention (ML + tokenize, Python + C): every non-blank
input line yields exactly one newline-terminated output segment
(the transform, or a bare newline when filtered/malformed).
Input blanks are not records and stay silent. Consequence,
locked in here:

- count_total() == non-blank input lines, on EVERY path
  (Python UDF, scalar C plugin, yyjson C plugin, tokenize).
- count_results() (valid records only) is identical across paths
  for the same input.

Residual (documented, not a bug): a degenerate single-record batch
whose record filters frames as b"" and counts 0 under the join
framing. Real batches are huge; no test below constructs one.
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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "benchmarks", "ml"))
# NOTE: benchmarks/tokenize/ is imported FLAT (tokenize_data_gen,
# tokenize_payload), never as `tokenize.*` — that name resolves to
# the stdlib module (already imported by the unittest runner).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "benchmarks", "tokenize"))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402

from _helpers import assert_no_zombies  # noqa: E402
from ml.ml_data_gen import generate_data  # noqa: E402
from ml.ml_payload import (  # noqa: E402
    forkrun_payload_heavy,
    forkrun_payload_light,
    forkrun_payload_medium,
)
from ml.bench_ml_pipeline import count_results, count_total  # noqa: E402
from tokenize_data_gen import generate_corpus  # noqa: E402
from tokenize_payload import Tokenizer, batch_payload  # noqa: E402

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


def _nonblank_lines(path):
    with open(path, "rb") as fh:
        return sum(1 for ln in fh.read().split(b"\n") if ln.strip())


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
@unittest.skipUnless(HAVE_GCC, "gcc not available")
class TestExactTotals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="fr_exact_totals_")
        cls.light_so = _build(
            cls.tmpdir,
            [os.path.join(PLUGIN_DIR, "ml_plugin_light.c")],
            os.path.join(cls.tmpdir, "ml_light.so"))
        cls.medium_so = _build(
            cls.tmpdir,
            [os.path.join(PLUGIN_DIR, "ml_plugin_medium.c")],
            os.path.join(cls.tmpdir, "ml_medium.so"))
        cls.heavy_so = _build(
            cls.tmpdir,
            [os.path.join(PLUGIN_DIR, "ml_plugin_heavy.c")],
            os.path.join(cls.tmpdir, "ml_heavy.so"))
        cls.yyjson_so = _build(
            cls.tmpdir,
            [os.path.join(PLUGIN_DIR, "ml_plugin_yyjson.c"),
             os.path.join(PLUGIN_DIR, "yyjson.c")],
            os.path.join(cls.tmpdir, "ml_yyjson.so"))
        cls.tok_so = _build(
            cls.tmpdir,
            [os.path.join(PLUGIN_DIR, "tokenize_plugin.c")],
            os.path.join(cls.tmpdir, "tok.so"))
        cls.light_spec = cls.light_so + ":ml_process_light"
        cls.medium_spec = cls.medium_so + ":ml_process_medium"
        cls.heavy_spec = cls.heavy_so + ":ml_process_heavy"
        cls.yyjson_spec = (cls.yyjson_so +
                           ":ml_process_medium_yyjson")
        cls.tok_spec = cls.tok_so + ":ml_tokenize"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def tearDown(self):
        assert_no_zombies(self)

    def _check_paths(self, path, jobs):
        """Every path: total == non-blank input lines; valid equal."""
        n_in = _nonblank_lines(path)
        valids = []
        for label, payload, mode in jobs:
            out = forkrun.map(payload, path, mode=mode, workers=4,
                              order="index", nodes=1)
            total = count_total(out)
            valid = count_results(out)
            self.assertEqual(
                total, n_in,
                "%s: total %d != %d non-blank input lines"
                % (label, total, n_in))
            valids.append(valid)
        self.assertEqual(
            len(set(valids)), 1,
            "valid-record counts differ across paths: %r" % (valids,))
        return valids[0]

    def test_ml_medium_totals(self):
        for fname, pct in (("clean.jsonl", 0.0), ("mal5.jsonl", 5.0),
                           ("mal50.jsonl", 50.0)):
            path = os.path.join(self.tmpdir, fname)
            generate_data(path, 3000, variant="medium",
                          malformed_pct=pct)
            self._check_paths(path, [
                ("python", forkrun_payload_medium, "python"),
                ("scalar", self.medium_spec, "plugin"),
                ("yyjson", self.yyjson_spec, "plugin"),
            ])

    def test_ml_light_heavy_totals(self):
        for variant, payload, spec in (
                ("light", forkrun_payload_light, self.light_spec),
                ("heavy", forkrun_payload_heavy, self.heavy_spec)):
            path = os.path.join(self.tmpdir, "%s.jsonl" % variant)
            generate_data(path, 2000, variant=variant,
                          malformed_pct=5.0)
            self._check_paths(path, [
                ("python", payload, "python"),
                ("scalar", spec, "plugin"),
            ])

    def test_tokenize_totals(self):
        corpus = os.path.join(self.tmpdir, "tok.jsonl")
        generate_corpus(corpus, 500)
        vocab = corpus + ".vocab"
        tok = Tokenizer(vocab_path=vocab)
        # The C plugin loads its vocabulary via the environment
        # (same as bench_tokenize.py); without it every doc skips.
        old_vocab = os.environ.get("FORKRUN_VOCAB_PATH")
        os.environ["FORKRUN_VOCAB_PATH"] = vocab
        try:
            self._check_tokenize(corpus, vocab, tok)
        finally:
            if old_vocab is None:
                os.environ.pop("FORKRUN_VOCAB_PATH", None)
            else:
                os.environ["FORKRUN_VOCAB_PATH"] = old_vocab

    def _check_tokenize(self, corpus, vocab, tok):

        def py_payload(batch):
            data = bytes(batch.data)
            out = batch_payload(
                [ln for ln in data.split(b"\n") if ln.strip()], tok)
            return b"\n".join(out) if out else None

        n_in = _nonblank_lines(corpus)
        for label, payload, mode in (
                ("python", py_payload, "python"),
                ("plugin", self.tok_spec, "plugin")):
            out = forkrun.map(payload, corpus, mode=mode, workers=4,
                              order="index", nodes=1)
            self.assertEqual(
                count_total(out), n_in,
                "%s: total != %d non-blank input docs" % (label, n_in))
        py_valid = count_results(forkrun.map(
            py_payload, corpus, mode="python", workers=4,
            order="index", nodes=1))
        pl_valid = count_results(forkrun.map(
            self.tok_spec, corpus, mode="plugin", workers=4,
            order="index", nodes=1))
        self.assertEqual(py_valid, pl_valid)


if __name__ == "__main__":
    unittest.main()
