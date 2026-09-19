"""Stage 3.0 schema tests (v3.5.2 scaffolding — annotation-only).

Enforces the v1.3 plan section 2.2 deliverables without touching the
frozen engine:
  1. The schema table compiles (standalone AND after system headers —
     the substrate header-hygiene rules apply to schema headers too).
  2. Every FORKRUN_LOADABLES entry has a schema entry (parsed textually;
     the engine is frozen, so no C-side coupling is possible yet).
  3. The generator's usage/doc output matches the engine strings exactly.
  4. The generator's committed artifacts are fresh (gen_idl.py --check).
  5. The generated ctypes mirror imports and is self-consistent.

Run: python3 tools/test_idl.py   (or: python3 -m unittest tools.test_idl)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TOOLS_DIR)

sys.path.insert(0, TOOLS_DIR)

from idl_schema import MIGRATION_ORDER, SCHEMA, parse_engine_table  # noqa: E402


class TestSchemaCompiles(unittest.TestCase):
    def _compile(self, prologue):
        with tempfile.NamedTemporaryFile("w", suffix=".c",
                                         delete=False) as fh:
            fh.write(prologue)
            fh.write('#include "forkrun_callschema.h"\n')
            fh.write("int main(void) { return 0; }\n")
            path = fh.name
        try:
            proc = subprocess.run(
                ["gcc", "-fsyntax-only", "-I", REPO_ROOT, path],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0,
                             "schema header failed to compile:\n%s"
                             % proc.stderr)
        finally:
            os.unlink(path)

    def test_standalone(self):
        """Self-contained: compiles with no prior includes."""
        self._compile("")

    def test_after_system_headers(self):
        """Order-independent: compiles after libc headers."""
        self._compile('#include <stdio.h>\n#include <stdlib.h>\n'
                      '#include <string.h>\n')


class TestSchemaCoverage(unittest.TestCase):
    def test_every_loadable_has_schema_entry(self):
        engine = parse_engine_table(os.path.join(REPO_ROOT,
                                                 "forkrun_ring.c"))
        engine_names = [name for name, _, _, _ in engine]
        self.assertEqual(sorted(engine_names), sorted(SCHEMA.keys()),
                         "schema/engine name mismatch")
        # No duplicate X() entries in the engine table.
        self.assertEqual(len(engine_names), len(set(engine_names)))

    def test_migration_order_present(self):
        for name in MIGRATION_ORDER:
            self.assertIn(name, SCHEMA)

    def test_all_argc_argv_in_v352(self):
        """Annotation-only: no THUNK flips in v3.5.2 (Stage 3's commits)."""
        flipped = [n for n, e in SCHEMA.items()
                   if e["convention"] != "ARGC_ARGV"]
        self.assertEqual(flipped, [])

    def test_field_vocab(self):
        for name, entry in SCHEMA.items():
            for direction, ftype, fname, opt in entry["fields"]:
                self.assertIn(direction, ("IN", "OUT", "LOCAL"), name)
                self.assertIn(ftype, ("I32", "U32", "U64", "U8", "STR",
                                      "PTR"), name)
                self.assertIsInstance(fname, str)
                self.assertIsInstance(opt, bool)


class TestUsageEquality(unittest.TestCase):
    def test_usage_doc_match_engine_exactly(self):
        """Generated usage output matches current strings exactly."""
        engine = parse_engine_table(os.path.join(REPO_ROOT,
                                                 "forkrun_ring.c"))
        for name, _, usage, doc in engine:
            self.assertEqual(SCHEMA[name]["usage"], usage, name)
            self.assertEqual(SCHEMA[name]["doc"], doc, name)


class TestGeneratorFreshness(unittest.TestCase):
    def test_check_passes(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(TOOLS_DIR, "gen_idl.py"),
             "--check"],
            capture_output=True, text=True, timeout=120, cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0,
                         "gen_idl.py --check failed:\n%s%s"
                         % (proc.stdout, proc.stderr))


class TestCtypesMirror(unittest.TestCase):
    def test_imports_and_covers_schema(self):
        sys.path.insert(0, os.path.join(TOOLS_DIR, "generated"))
        try:
            import fr_ctypes  # noqa: PLC0415
        finally:
            sys.path.pop()
        self.assertEqual(sorted(fr_ctypes.CONVENTIONS),
                         sorted(SCHEMA.keys()))
        for name, entry in SCHEMA.items():
            self.assertEqual(fr_ctypes.USAGE[name], entry["usage"])
            self.assertEqual(fr_ctypes.DOC[name], entry["doc"])
        # Spot-checks: claim field count, type map, PTR+LEN pair on call.
        self.assertEqual(len(fr_ctypes.FIELDS["ring_claim"]), 6)
        self.assertIs(fr_ctypes.field_ctype("U64"),
                      fr_ctypes.ctypes.c_uint64)
        call_types = [t for _, t, _, _ in fr_ctypes.FIELDS["ring_call"]]
        self.assertIn("PTR", call_types)
        with self.assertRaises(KeyError):
            fr_ctypes.field_ctype("BOGUS")

    def test_usage_table_parses(self):
        path = os.path.join(TOOLS_DIR, "generated", "usage_table.json")
        with open(path) as fh:
            table = json.load(fh)
        self.assertEqual(sorted(table), sorted(SCHEMA.keys()))
        for name, entry in SCHEMA.items():
            self.assertEqual(table[name]["usage"], entry["usage"])
            self.assertEqual(table[name]["doc"], entry["doc"])


if __name__ == "__main__":
    unittest.main()
