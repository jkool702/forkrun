"""W-DEDUP R-D8: shim ABI gate (signatures only, not semantics).

Single source: python/forkrun/_shim.c. Generated artifacts:
forkrun_shim.h + tools/generated/shim_signatures.json (via
tools/gen_shim.py; CI runs --check). This test diffs the live
substrate + _bindings.py against the committed signature table —
the practical equivalent of typechecking the Python/C boundary.

Scope guard: arity + name + linkage + export presence only. Semantic
contracts (which entry clears worker_last_cnt, 5-on-fatal) belong to
test_invariant_gate.py §3/§6/§9, never here.
"""

import ctypes
import json
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SIG_JSON = os.path.join(REPO_ROOT, "tools", "generated",
                        "shim_signatures.json")
SHIM_H = os.path.join(REPO_ROOT, "forkrun_shim.h")
SHIM_C = os.path.join(REPO_ROOT, "python", "forkrun", "_shim.c")

from forkrun._bindings import find_substrate  # noqa: E402

try:
    find_substrate()
    HAVE_LIB = True
except FileNotFoundError:
    HAVE_LIB = False


def _load_table():
    with open(SIG_JSON) as fh:
        return json.load(fh)


def _c_arity(args_s):
    args_s = args_s.strip()
    if args_s == "void" or args_s == "":
        return 0
    # Top-level commas only (no nested parens in this ABI).
    return args_s.count(",") + 1


class TestShimArtifactsFresh(unittest.TestCase):
    """Committed header + JSON match regeneration (mirrors CI --check)."""

    def test_gen_shim_check(self):
        rc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "tools",
                                          "gen_shim.py"), "--check"],
            capture_output=True, text=True, cwd=REPO_ROOT).returncode
        self.assertEqual(rc, 0,
                         "gen_shim.py --check failed (regenerate: "
                         "python3 tools/gen_shim.py)")

    def test_header_lists_all_externs(self):
        table = _load_table()
        with open(SHIM_H) as fh:
            hdr = fh.read()
        for name, ent in table.items():
            if ent["linkage"] != "extern":
                continue
            self.assertIn(name, hdr,
                          "extern %s missing from forkrun_shim.h" % name)
        for name, ent in table.items():
            if ent["linkage"] == "extern":
                continue
            # Static internals must NOT be in the ABI header.
            self.assertNotRegex(
                hdr, r"\b%s\s*\(" % re.escape(name),
                "static %s leaked into forkrun_shim.h" % name)


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestShimExports(unittest.TestCase):
    """Every extern is exported by the .so; no extra fr_py_* exports."""

    def test_exports_match_table(self):
        table = _load_table()
        externs = sorted(k for k, v in table.items()
                         if v["linkage"] == "extern")
        lib_path = find_substrate()
        out = subprocess.run(
            ["nm", "-D", "--defined-only", lib_path],
            capture_output=True, text=True).stdout
        exported = sorted(set(re.findall(r"\b(fr_py_\w+)", out)))
        self.assertEqual(exported, externs,
                         "export drift: extra=%s missing=%s"
                         % (sorted(set(exported) - set(externs)),
                            sorted(set(externs) - set(exported))))


@unittest.skipUnless(HAVE_LIB, "libforkrun_python.so not built")
class TestShimBindings(unittest.TestCase):
    """_bindings.py covers every extern with matching arity."""

    def test_bindings_cover_externs(self):
        import forkrun._bindings as _b

        table = _load_table()
        lib = ctypes.CDLL(find_substrate())
        _b._setup_signatures(lib)
        missing = []
        arity_mismatch = []
        for name, ent in table.items():
            if ent["linkage"] != "extern":
                continue
            fn = getattr(lib, name, None)
            if fn is None:
                missing.append(name)
                continue
            # ctypes argtypes must exist and match C arity.
            try:
                n_ctypes = len(fn.argtypes or [])
            except AttributeError:
                n_ctypes = None
            n_c = _c_arity(ent["args"])
            # void-arg C functions bind as [] (0).
            if n_ctypes is not None and n_ctypes != n_c:
                arity_mismatch.append((name, n_c, n_ctypes))
        self.assertEqual(missing, [],
                         "externs missing from loaded lib: %s" % missing)
        self.assertEqual(arity_mismatch, [],
                         "arity drift (C vs ctypes): %s"
                         % arity_mismatch)

    def test_no_order_regression(self):
        # Reordering is an ABI change: source order in the JSON must be
        # stable (insertion-ordered dict from parse order).
        table = _load_table()
        names = list(table.keys())
        self.assertEqual(len(names), len(set(names)), "duplicate entries")
        # 50 extern + 11 static = 61 (guard against silent truncation).
        # 50 rather than 49 because fr_py_poison_relay was added (the
        # cleanroom's poisoned-batch-index relay).
        # W-PREFLIGHT added fr_py_ingest_data_post: an advisory
        # "more bytes landed in ingress" poke on evfd_ingest_data, so
        # the pre-flight scan can block on the eventfd instead of
        # spin-sleeping. It deliberately does NOT touch
        # state[0].ingest_complete -- that is the scanner's EOF gate and
        # must only be set on a genuine drain (see the W-GATE2 postmortem
        # in MEMORY.md, which lost records by trusting it). Additive: no
        # existing signature changed, no struct layout changed, nothing
        # removed.
        # W-PYFORKGATE added fr_py_backlog_node: a read-only,
        # non-destructive per-node backlog accessor. It is additive — no
        # existing signature changed, no struct layout changed, and
        # nothing was removed — so the ABI stays backward compatible for
        # already-built consumers. The reason it could not be done in
        # Python: fr_py_data_ready_node is consume-once (it walks
        # write_idx forward from a private hwm), so the fork gate cannot
        # read a LEVEL with it. Behavior delta is confined to the NUMA
        # fork gate's fork timing; see the gate loop in run.py.
        n_ext = sum(1 for v in table.values()
                    if v["linkage"] == "extern")
        n_st = sum(1 for v in table.values()
                   if v["linkage"] == "static")
        self.assertEqual((n_ext, n_st), (50, 11),
                         "ABI surface changed (extern=%d static=%d) — "
                         "if intentional, regenerate + justify in the "
                         "behavior-delta audit" % (n_ext, n_st))


if __name__ == "__main__":
    unittest.main()
