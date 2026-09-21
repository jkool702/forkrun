"""W-PY20 parameter sweeps: bash ::: / :::: / --link equivalent.

Pure frontend feature: combinations become ordinary batches whose
.metadata carries the sweep tuple. The engine is unchanged; error
handling rides the existing escrow/retry/poison path per batch.
"""

import os
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun._sweep import generate_combinations  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


class TestSweepGeneration(unittest.TestCase):
    """Combination generation (engine-free)."""

    def test_cartesian_product(self):
        combos = list(generate_combinations(
            args=[["a", "b", "c"], ["x", "y"]]))
        self.assertEqual(len(combos), 6)
        self.assertIn(("a", "x"), combos)
        self.assertIn(("c", "y"), combos)
        # Dimension order is tuple order.
        self.assertEqual(combos[0], ("a", "x"))
        self.assertEqual(combos[-1], ("c", "y"))

    def test_zip_mode(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            combos = list(generate_combinations(
                args=[["a", "b"], ["1", "2"]], link=True))
        self.assertEqual(combos, [("a", "1"), ("b", "2")])

    def test_zip_truncates_with_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", UserWarning)
            combos = list(generate_combinations(
                args=[["a", "b", "c"], ["x", "y"]], link=True))
        self.assertEqual(len(combos), 2)
        self.assertEqual(combos[0], ("a", "x"))
        self.assertEqual(combos[1], ("b", "y"))
        self.assertTrue(any(issubclass(w.category, UserWarning)
                            for w in caught))

    def test_from_files(self):
        d = tempfile.mkdtemp(prefix="w20dim_")
        try:
            f1 = os.path.join(d, "dim1.txt")
            f2 = os.path.join(d, "dim2.txt")
            with open(f1, "w") as fh:
                fh.write("a\n\nb\n")  # blank line skipped
            with open(f2, "w") as fh:
                fh.write("x\ny\n")
            combos = list(generate_combinations(args_from=[f1, f2]))
            self.assertEqual(len(combos), 4)
            self.assertIn(("a", "x"), combos)
            self.assertIn(("b", "y"), combos)
        finally:
            import shutil as _shutil
            _shutil.rmtree(d, ignore_errors=True)

    def test_from_files_missing(self):
        with self.assertRaises(ValueError):
            list(generate_combinations(
                args_from=["/nonexistent/dim.txt"]))

    def test_single_dimension(self):
        combos = list(generate_combinations(args=[["a", "b"]]))
        self.assertEqual(combos, [("a",), ("b",)])

    def test_empty_dimension(self):
        self.assertEqual(list(generate_combinations(args=[[]])), [])
        self.assertEqual(
            list(generate_combinations(args=[["a"], []])), [])

    def test_both_and_neither_rejected(self):
        with self.assertRaises(ValueError):
            list(generate_combinations(args=[["a"]],
                                       args_from=["f.txt"]))
        with self.assertRaises(ValueError):
            list(generate_combinations())

    def test_bad_dimension_rejected(self):
        for bad in ("ab", ["a", "bc"], [["a"], "bc"], [["a"], 42]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                list(generate_combinations(args=bad))

    def test_lazy_iterator(self):
        it = generate_combinations(args=[["a", "b"], ["x"]])
        self.assertTrue(hasattr(it, "__next__"))
        self.assertIs(iter(it), it)
        self.assertEqual(next(it), ("a", "x"))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestSweepExecution(unittest.TestCase):
    def tearDown(self):
        assert_no_zombies(self)

    def test_sweep_basic(self):
        res = forkrun.sweep(
            lambda b: ("%s-%s" % (b.metadata[0],
                                  b.metadata[1])).encode(),
            args=[["a", "b"], ["x", "y"]])
        self.assertEqual(len(res), 4)
        self.assertIn(b"a-x", res)
        self.assertIn(b"b-y", res)

    def test_sweep_combination_order(self):
        # Standalone results arrive in combination order.
        res = forkrun.sweep(lambda b: str(b.metadata).encode(),
                            args=[["a", "b"], ["x", "y"]])
        self.assertEqual(
            res, [b"('a', 'x')", b"('a', 'y')",
                  b"('b', 'x')", b"('b', 'y')"])

    def test_sweep_with_source(self):
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            with open(path, "w") as fh:
                fh.write("data line 1\ndata line 2\n")
            res = forkrun.sweep(
                lambda b: ("%s:%s" % (
                    b.metadata[0],
                    bytes(b.data).decode().strip().splitlines()[0]
                )).encode(),
                source=path, args=[["p1", "p2"]])
            # Each of the 2 combos processes the whole source.
            self.assertEqual(len(res), 2 * len(
                forkrun.map(lambda b: bytes(b.data), path)))
            self.assertTrue(all(r.startswith(b"p1:") or
                                r.startswith(b"p2:") for r in res))
        finally:
            os.unlink(path)

    def test_sweep_with_fd_source(self):
        # fd sources are materialized once: every combo sees it all.
        fd, path = tempfile.mkstemp(suffix=".txt")
        try:
            os.write(fd, b"hello\n")
            res = forkrun.sweep(
                lambda b: (b.metadata[0].encode() + b":" +
                           bytes(b.data).strip()),
                source=fd, args=[["q1", "q2"]])
            self.assertEqual(sorted(res),
                             [b"q1:hello", b"q2:hello"])
        finally:
            os.close(fd)
            os.unlink(path)

    def test_sweep_link_mode(self):
        res = forkrun.sweep(
            lambda b: ("%s=%s" % (b.metadata[0],
                                  b.metadata[1])).encode(),
            args=[["a", "b"], ["1", "2"]], link=True)
        self.assertEqual(len(res), 2)
        self.assertIn(b"a=1", res)
        self.assertIn(b"b=2", res)

    def test_sweep_from_files(self):
        d = tempfile.mkdtemp(prefix="w20sw_")
        try:
            f1 = os.path.join(d, "a.txt")
            f2 = os.path.join(d, "b.txt")
            with open(f1, "w") as fh:
                fh.write("m1\nm2\n")
            with open(f2, "w") as fh:
                fh.write("n1\n")
            res = forkrun.sweep(
                lambda b: ("%s/%s" % (b.metadata[0],
                                      b.metadata[1])).encode(),
                args_from=[f1, f2])
            self.assertEqual(sorted(res), [b"m1/n1", b"m2/n1"])
        finally:
            import shutil as _shutil
            _shutil.rmtree(d, ignore_errors=True)

    def test_sweep_error_retry(self):
        # Failing combos ride escrow retry → poison-skip like any
        # batch; the healthy combos still land.
        def _sometimes(b):
            if b.metadata[0] == "bad":
                raise ValueError("bad combo")
            return b.metadata[0].encode()

        res = forkrun.sweep(_sometimes, args=[["bad", "good"]])
        self.assertEqual(res, [b"good"])

    def test_sweep_empty_args(self):
        self.assertEqual(
            forkrun.sweep(lambda b: b"never", args=[[]]), [])

    def test_sweep_forced_mapping_conflicts(self):
        # Standalone batch↔combo mapping is load-bearing: silently
        # accepting lines=/bytes=/order= would scramble it.
        with self.assertRaises(ValueError):
            forkrun.sweep(lambda b: b"x", args=[["a"]], lines=5)
        with self.assertRaises(ValueError):
            forkrun.sweep(lambda b: b"x", args=[["a"]], bytes=64)
        with self.assertRaises(ValueError):
            forkrun.sweep(lambda b: b"x", args=[["a"]],
                          order="none")
        with self.assertRaises(ValueError):
            forkrun.sweep(lambda b: b"x", args=[["a"]],
                          sink=lambda m, r: None)
        with self.assertRaises(ValueError):
            forkrun.sweep(None, args=[["a"]], mode="splice")

    def test_sweep_orchestrator_passthrough(self):
        res = forkrun.sweep(
            lambda b: b.metadata[0].encode(),
            args=[["a", "b", "c"]], orchestrator=True)
        self.assertEqual(sorted(res), [b"a", b"b", b"c"])

    def test_metadata_default_none(self):
        # Outside sweeps, Batch.metadata is None (additive change).
        # Observed via map results (fork-closure: worker-side appends
        # never reach the parent — results cross via memfds only).
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            write_lines(path, 50)
            res = forkrun.map(
                lambda b: b"x" if b.metadata is None else b"y",
                path, workers=2)
        finally:
            os.unlink(path)
        self.assertTrue(res)
        self.assertTrue(all(r == b"x" for r in res))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestSweepPurity(unittest.TestCase):
    def test_no_banned_tokens(self):
        pkg = os.path.join(os.path.dirname(__file__), "..", "forkrun")
        offenders = []
        for name in ("_sweep.py",):
            with open(os.path.join(pkg, name)) as fh:
                src = fh.read()
            for token in ("subprocess.", "Popen", "import pickle",
                          "from pickle", "cPickle", "os.system",
                          "frun.bash", "source ./frun",
                          "multiprocessing", "multiprocessing.Pipe",
                          "multiprocessing.Queue"):
                if token in src:
                    offenders.append("%s: %s" % (name, token))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
