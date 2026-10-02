"""Enforce the dispatch invariant: one bundle, no per-site retyping.

If any executor call site in map()/run() spells out a keyword that is
also in the shared `base` bundle, the two can drift -- which is exactly
how output= ended up honoured on some paths and silently ignored on
others. This is the structural guard for that class of bug.
"""
import ast, os, unittest

RUN_PY = os.path.join(os.path.dirname(__file__), "..", "forkrun", "run.py")
EXECUTORS = {"_execute", "_execute_ingest", "_execute_reactor_locked",
             "_execute_ingest_reactor_locked", "_execute_numa_locked",
             "_core_collect", "_core_fork"}
ENTRY = {"map", "run", "stream", "sweep"}


def _bundles(fn):
    """Keyword names of the dispatch bundle(s) assigned in fn.

    Accepts both spellings the bundle can take -- a dict literal
    (``base = {...}``) and a dict(...) call (``base = dict(...)``) --
    because a detector that only understands one of them is a detector
    that silently stops guarding when someone reformats.
    """
    out = {}
    for n in ast.walk(fn):
        if not isinstance(n, ast.Assign):
            continue
        keys = set()
        val = n.value
        if isinstance(val, ast.Dict):
            keys = {k.value for k in val.keys if isinstance(k, ast.Constant)}
        elif (isinstance(val, ast.Call) and isinstance(val.func, ast.Name)
                and val.func.id == "dict"):
            keys = {k.arg for k in val.keywords if k.arg}
        if not keys:
            continue
        for t in n.targets:
            if isinstance(t, ast.Name):
                out[t.id] = keys
    return out


class TestDispatchSingleSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(open(RUN_PY).read())
        cls.fns = {f.name: f for f in ast.walk(cls.tree)
                   if isinstance(f, ast.FunctionDef)}

    def test_no_site_retypes_a_kwarg_it_also_splats(self):
        """Compare each site against the bundle THAT SITE splats.

        Deliberately not "any bundle in the function": map() builds a
        NUMA variant alongside the UMA one, and keys that exist only in
        the variant (`splice`, `numa_map`) are genuinely per-path. The
        hazard is a site spelling out something its own bundle already
        carries -- those two sources can drift, and drift silently.
        """
        problems = []
        for name in ("map", "run"):
            fn = self.fns[name]
            bundles = _bundles(fn)
            self.assertTrue(bundles, "%s() has no dispatch bundle" % name)
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call):
                    continue
                callee = (n.func.attr if isinstance(n.func, ast.Attribute)
                          else getattr(n.func, "id", None))
                if callee not in EXECUTORS:
                    continue
                splatted = set()
                for k in n.keywords:
                    if k.arg is None and getattr(k.value, "id", "") in bundles:
                        splatted |= bundles[k.value.id]
                spelled = {k.arg for k in n.keywords if k.arg}
                dup = spelled & splatted
                if dup:
                    problems.append(
                        "%s() line %d -> %s re-spells %s (also in its bundle)"
                        % (name, n.lineno, callee, sorted(dup)))
        self.assertEqual(problems, [],
                         "executor dispatch kwargs duplicated:\n  "
                         + "\n  ".join(problems))

    def test_every_dispatch_site_uses_the_bundle(self):
        """A site that passes none of **base has re-derived the bundle."""
        for name in ("map", "run"):
            fn = self.fns[name]
            bundles = _bundles(fn)
            if not bundles:
                continue
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call):
                    continue
                callee = (n.func.attr if isinstance(n.func, ast.Attribute)
                          else getattr(n.func, "id", None))
                if callee not in EXECUTORS:
                    continue
                has_star = any(k.arg is None and k.value is not None
                               and getattr(k.value, "id", "") in bundles
                               for k in n.keywords)
                if not has_star:
                    self.fail(
                        "%s() line %d -> %s does not splat the bundle; it "
                        "re-derives the shared kwargs by hand"
                        % (name, n.lineno, callee))


if __name__ == "__main__":
    unittest.main()
