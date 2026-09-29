"""Make named modules look un-importable, without uninstalling anything.

bench_ml_pipeline.py decides which competing systems to run purely by
probing importability (detect_frameworks(), ~line 44):

    for key, mod in (("ray","ray"), ("polars","polars"),
                     ("duckdb","duckdb"), ("hf_datasets","datasets")):
        try:
            __import__(mod); found[key] = True
        except ImportError:
            found[key] = False

A missing framework makes its legs vanish from the --csv SILENTLY — only
ray and hf_datasets print a note. That is a real hazard for a comparison
table: a reader who does not notice a missing line assumes the system lost.

We want Ray and HuggingFace Datasets for the 5M competitor matrix (they are
in the headline table) but NOT for the 20M run, where they cost ~4.5 h for
numbers the repo itself only ever published at 5M (RELEASE_v3.6.0.md §0/§2:
competitors are 5M, 20M is forkrun-only).

Rather than uninstall or edit the runner, put this directory on PYTHONPATH
for the 20M invocation only and set EPYC_BLOCK_MODULES. Every blocked name
then raises ImportError, the probe takes its "not installed" branch, and the
absence is recorded rather than inferred.

    EPYC_BLOCK_MODULES=ray,datasets PYTHONPATH=epyc/blockmods python3 ...
"""

import os
import sys

BLOCKED = {
    name.strip()
    for name in os.environ.get("EPYC_BLOCK_MODULES", "").split(",")
    if name.strip()
}


class _Blocker:
    """A meta_path finder that raises ImportError for blocked top-level names."""

    def find_module(self, fullname, path=None):  # legacy API, unused on 3.12+
        return None

    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split(".", 1)[0]
        if root in BLOCKED:
            raise ImportError(
                f"No module named {root!r} "
                f"(blocked by epyc/blockmods/sitecustomize.py; "
                f"EPYC_BLOCK_MODULES={os.environ.get('EPYC_BLOCK_MODULES')!r})"
            )
        return None


if BLOCKED:
    # NOTE: do not try to evict ourselves from sys.modules here. This body runs
    # *during* `import sitecustomize`, so sys.modules['sitecustomize'] is only
    # partially populated; deleting it makes the import machinery raise
    # KeyError on cleanup ("Error in sitecustomize"). Nothing needs removing —
    # sitecustomize is imported exactly once per interpreter, and our finder
    # wins because we insert at position 0.
    sys.meta_path.insert(0, _Blocker())
    print(
        f"[epyc] blocked imports: {', '.join(sorted(BLOCKED))}",
        file=sys.stderr,
    )
