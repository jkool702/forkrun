"""Every executor that ingests from a source must prepare it the same way.

The pipe resize (F_SETPIPE_SZ) was added to one executor and forgotten
in two siblings, so `cat file | forkrun` ran 16x the spill syscalls on
some paths and not others. This pins the invariant structurally rather
than by review: any code that dups a source fd must go through
_prepare_ingest_source, so a new executor cannot skip it.
"""
import ast
import os
import re
import unittest

RUN_PY = os.path.join(os.path.dirname(__file__), "..", "forkrun", "run.py")


def _tree():
    with open(RUN_PY) as fh:
        return ast.parse(fh.read())


class TestIngestSourceSetup(unittest.TestCase):
    def test_only_the_helper_dups_a_source_fd(self):
        """`src_fd = os.dup(` must appear exactly once, in the helper."""
        with open(RUN_PY) as fh:
            src = fh.read()
        sites = [(i + 1, ln) for i, ln in enumerate(src.split("\n"))
                 if "src_fd = os.dup(" in ln]
        self.assertEqual(
            len(sites), 1,
            "src_fd = os.dup( appears at %r; every ingest executor must "
            "call _prepare_ingest_source() instead, or a new one will "
            "skip the F_SETPIPE_SZ" % ([s[0] for s in sites],))
        # ...and that one site is inside the helper (defined just above).
        window = src.split("\n")[max(0, sites[0][0] - 32):sites[0][0] + 2]
        self.assertTrue(
            any(ln.startswith("def _prepare_ingest_source(") for ln in window),
            "the only src_fd = os.dup( is not inside "
            "_prepare_ingest_source; found at line %d" % sites[0][0])

    def test_helper_resizes_and_dups(self):
        """The helper must do BOTH jobs, not just one."""
        tree = _tree()
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_prepare_ingest_source")
        body = ast.dump(fn)
        self.assertIn("F_SETPIPE_SZ", body,
                      "helper stopped resizing the pipe -- that was the "
                      "whole pipe-vs-file throughput gap")
        self.assertIn("dup", body, "helper stopped duping the source fd")

    def test_every_executor_with_a_spill_loop_calls_the_helper(self):
        """No executor may read a source without preparing it first.

        Cheap proxy for the real invariant: any function that reads
        src_fd must reference _prepare_ingest_source somewhere in its
        body, or pass src_fd to something that does.
        """
        tree = _tree()
        offenders = []
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            reads_src = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("read", "pread", "pread64")
                and n.args and isinstance(n.args[0], ast.Name)
                and n.args[0].id == "src_fd"
                for n in ast.walk(fn))
            if not reads_src:
                continue
            body = ast.dump(fn)
            # Inner helpers legitimately read an ALREADY-prepared fd
            # handed down by a caller that did prepare it. They are
            # listed explicitly so adding one is a deliberate act.
            PREPARED_BY_CALLER = {"_spill_to_memfd", "_pump"}
            if ("_prepare_ingest_source" not in body
                    and "_ingest_copy_loop" not in body
                    and "spill_quantum" not in fn.name
                    and "_open_source" not in body
                    and fn.name not in PREPARED_BY_CALLER):
                offenders.append("%s (line %d)" % (fn.name, fn.lineno))
        self.assertEqual(offenders, [],
                         "these functions read src_fd without routing it "
                         "through _prepare_ingest_source: %s" % offenders)

    def test_pipe_sizing_constant_is_one_mib(self):
        with open(RUN_PY) as fh:
            src = fh.read()
        m = re.search(r"^_INGEST_PIPE_SZ = (.+)$", src, re.M)
        self.assertIsNotNone(m, "_INGEST_PIPE_SZ is gone")
        self.assertEqual(m.group(1).strip(), "1 << 20",
                         "ingress pipe size must stay matched to _CHUNK "
                         "(1 MiB); _CHUNK = %s" % re.search(
                             r"^_CHUNK = (.+)$", src, re.M).group(1))


if __name__ == "__main__":
    unittest.main()
