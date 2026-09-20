"""W-PY8 Mode 2 (spawn): external binaries per batch (Stage 5 Phase 3).

v0 executes via Python subprocess (correct, documented ~1-5ms/batch
overhead); stdout captured as the result, non-zero exit rides
escrow/retry/poison. Requires cat/gzip/sed/sh/false (coreutils).
"""

import gzip
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import forkrun  # noqa: E402
from forkrun._bindings import find_substrate  # noqa: E402
from forkrun._spawn import SpawnError, make_spawn_payload  # noqa: E402

from _helpers import assert_no_zombies, write_lines  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


class TestSpawnValidation(unittest.TestCase):
    """Engine-free: mode/shape mismatches raise before any engine contact."""

    def test_spawn_callable_rejected(self):
        with self.assertRaises(ValueError):
            forkrun.run(lambda b: None, "f.txt", mode="spawn")
        with self.assertRaises(ValueError):
            forkrun.map(lambda b: None, "f.txt", mode="spawn")

    def test_spawn_bad_command_shape(self):
        with self.assertRaises(ValueError):
            make_spawn_payload("")
        with self.assertRaises(ValueError):
            make_spawn_payload([])
        with self.assertRaises(ValueError):
            make_spawn_payload(123)

    def test_spawn_module_hygiene(self):
        # _spawn.py is OUTSIDE the purity-test scan list because its
        # subprocess use is execution (sanctioned v0 design), not
        # transport. It must still never touch pickle/bash/shell.
        with open(os.path.join(os.path.dirname(__file__), "..", "forkrun",
                               "_spawn.py")) as fh:
            src = fh.read()
        for token in ("pickle", "shell=True", "os.system", "frun.bash",
                      "Popen"):
            self.assertNotIn(token, src)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestSpawnMode(unittest.TestCase):
    def test_basic_spawn(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("hello\nworld\n")
            out = forkrun.map("cat", path, mode="spawn", workers=2,
                              order="index")
            self.assertEqual(b"".join(out), b"hello\nworld\n")
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_gzip(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("compress me\n" * 100)
            out = forkrun.map("gzip -c", path, mode="spawn", workers=2,
                              order="index")
            self.assertTrue(len(out) > 0)
            self.assertEqual(b"".join(gzip.decompress(r) for r in out),
                             b"compress me\n" * 100)
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_command_list(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                fh.write("old dog\nold cat\n")
            out = forkrun.map(["sed", "s/old/new/"], path, mode="spawn",
                              workers=1, order="index")
            self.assertEqual(b"".join(out), b"new dog\nnew cat\n")
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_error_retries_then_continues(self):
        # grep MARKER: batches without it exit 1 -> retry x3 -> poison;
        # the marker batch succeeds. Pipeline completes around the holes.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            with open(path, "w") as fh:
                for i in range(1000):
                    fh.write("MARKER\n" if i == 500 else "line %d\n" % i)
            out = forkrun.map("grep MARKER", path, mode="spawn", workers=1)
            self.assertIn(b"MARKER\n", b"".join(out))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_not_found_retries_then_poisons(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 200)
            out = forkrun.map("nonexistent_command_xyz_123", path,
                              mode="spawn", workers=1)
            self.assertEqual(out, [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_stdout_only(self):
        # List form for shell constructs: stdout captured, stderr excluded.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 100)
            out = forkrun.map(["sh", "-c", "cat; echo noise >&2"],
                              path, mode="spawn", workers=1, order="index")
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(out), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_empty_input(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            self.assertEqual(forkrun.map("cat", path, mode="spawn",
                                         workers=2), [])
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_with_stream(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1000)
            out = list(forkrun.stream("cat", path, mode="spawn", workers=2))
            with open(path, "rb") as fh:
                raw = fh.read()
            self.assertEqual(sorted(b"".join(out).splitlines()),
                             sorted(raw.splitlines()))
            assert_no_zombies(self)
        finally:
            os.unlink(path)

    def test_spawn_ordered(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                         delete=False) as fh:
            path = fh.name
        try:
            write_lines(path, 1000)
            streamed = list(forkrun.stream("cat", path, mode="spawn",
                                           workers=2, order="index"))
            mapped = forkrun.map("cat", path, mode="spawn", workers=2,
                                 order="index")
            self.assertEqual(streamed, mapped)
            with open(path, "rb") as fh:
                self.assertEqual(b"".join(streamed), fh.read())
            assert_no_zombies(self)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
