#!/usr/bin/env python3
"""forkrun v3.6.0 release checklist (W-PY23).

Run from the repo root BEFORE tagging v3.6.0. Every check must pass:

    python3 python/release_check.py

Checks: version coherence, full test suite, canary link check, IDL
schema check, reproducible builds, wheel platform tag + metadata,
sdist completeness, doc twins, clean tree, frozen engine.

Exit 0 + "ALL CHECKS PASSED" means ready to tag. Anything else means
DO NOT TAG. (The tree-clean and frozen-engine checks require a
committed tree — run after `git add -A && git commit`.)
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY_VERSION = "0.16.0"
PROJECT_VERSION = "v3.6.0"
FROZEN_FILES = ["forkrun_ring.c", "forkrun_substrate.h", "substratestubs.c"]

CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


def _run(cmd, timeout=600, cwd=None):
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        cwd=cwd or REPO_ROOT)


@check("Version: __version__ is %s" % PY_VERSION)
def check_version():
    sys.path.insert(0, os.path.join(REPO_ROOT, "python"))
    import forkrun
    assert forkrun.__version__ == PY_VERSION, forkrun.__version__
    return True


@check("Version: setup.py agrees with __version__")
def check_setup_version():
    proc = _run([sys.executable, "setup.py", "--version"], timeout=120)
    assert proc.returncode == 0, proc.stderr[-1000:]
    sys.path.insert(0, os.path.join(REPO_ROOT, "python"))
    import forkrun
    assert proc.stdout.strip() == forkrun.__version__, proc.stdout
    return True


@check("Version: CHANGELOG has %s and %s" % (PROJECT_VERSION, PY_VERSION))
def check_changelog_version():
    with open(os.path.join(REPO_ROOT, "DOCS", "CHANGELOG.md")) as fh:
        content = fh.read()
    assert PROJECT_VERSION in content, "no %s entry" % PROJECT_VERSION
    assert PY_VERSION in content, "no %s entry" % PY_VERSION
    return True


@check("Docs: CHANGELOG/DOCS_ALL section structure matches")
def check_twins():
    # DOCS_ALL.md embeds CHANGELOG.md (plus every other doc), so
    # whole-file heading sequences cannot match — the lockstep rule
    # is: every CHANGELOG section heading exists verbatim in
    # DOCS_ALL (a new release entry missing from the embedded copy
    # fails loudly).
    def headings(path):
        with open(path) as fh:
            return [line.strip() for line in fh
                    if line.startswith("## ") or line.startswith("### ")]
    changelog = headings(os.path.join(REPO_ROOT, "DOCS", "CHANGELOG.md"))
    assert changelog, "no headings in CHANGELOG.md"
    with open(os.path.join(REPO_ROOT, "DOCS", "DOCS_ALL.md")) as fh:
        docs_all = fh.read()
    missing = [h for h in changelog if h + "\n" not in docs_all]
    assert not missing, "headings missing from DOCS_ALL.md: %r" % missing
    return True


@check("Tests: full suite passes")
def check_tests():
    proc = _run([sys.executable, "-m", "unittest", "discover",
                 "-s", "python/tests"], timeout=1200)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return True


@check("Canary: substrate links with no bash linkage")
def check_canary():
    proc = _run(["make", "-f", "Makefile.substrate", "canary"],
                timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return True


@check("IDL: schema checks pass")
def check_idl():
    proc = _run([sys.executable, "tools/test_idl.py"], timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return True


@check("Reproducible: two substrate builds are byte-identical")
def check_reproducible():
    proc = _run(["make", "-f", "Makefile.substrate",
                 "reproducibility-check"], timeout=900)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    return True


@check("Wheel: builds with a platform tag (not py3-none-any)")
def check_wheel():
    workdir = tempfile.mkdtemp(prefix="forkrun_release_wheel_")
    try:
        proc = _run([sys.executable, "-m", "pip", "wheel", ".",
                     "--no-deps", "-w", workdir], timeout=900)
        assert proc.returncode == 0, proc.stderr[-2000:]
        wheels = glob.glob(os.path.join(workdir, "*.whl"))
        assert wheels, "no wheel built"
        name = os.path.basename(wheels[0])
        assert "linux_" in name, "wheel lacks platform tag: %s" % name
        assert "none-any" not in name, \
            "wheel wrongly tagged py3-none-any: %s" % name
        assert PY_VERSION in name, \
            "wheel version mismatch: %s" % name
        return True
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


@check("Wheel: METADATA is complete")
def check_metadata():
    import zipfile
    workdir = tempfile.mkdtemp(prefix="forkrun_release_meta_")
    try:
        proc = _run([sys.executable, "-m", "pip", "wheel", ".",
                     "--no-deps", "-w", workdir], timeout=900)
        assert proc.returncode == 0, proc.stderr[-2000:]
        wheels = glob.glob(os.path.join(workdir, "*.whl"))
        assert wheels, "no wheel built"
        with zipfile.ZipFile(wheels[0]) as zf:
            meta_names = [n for n in zf.namelist()
                          if n.endswith(".dist-info/METADATA")]
            assert meta_names, "no METADATA in wheel"
            meta = zf.read(meta_names[0]).decode("utf-8")
        for field in ("Name: forkrun", "Version: " + PY_VERSION,
                      "Summary:", "Home-page:", "Requires-Python:",
                      "License:", "Classifier:"):
            assert field in meta, "METADATA missing %r" % field
        assert "Development Status :: 4 - Beta" in meta
        return True
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


@check("sdist: builds and contains all C sources")
def check_sdist():
    proc = _run([sys.executable, "setup.py", "-q", "sdist"],
                timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    import tarfile
    dist_dir = os.path.join(REPO_ROOT, "dist")
    sdists = glob.glob(os.path.join(dist_dir, "*.tar.gz"))
    assert sdists, "no sdist built"
    with tarfile.open(sdists[0]) as tf:
        names = tf.getnames()
    top = "forkrun-%s/" % PY_VERSION
    needed = ["forkrun_ring.c", "forkrun_substrate.h",
              "substratestubs.c", "Makefile.substrate",
              "ring_loadables/forkrun_plugin.h",
              "python/forkrun/_shim.c", "python/README.md",
              "LICENSE", "setup.py", "pyproject.toml"]
    for rel in needed:
        assert top + rel in names, "sdist missing %s" % rel
    return True


@check("Docs: python README matches release version")
def check_readme_version():
    with open(os.path.join(REPO_ROOT, "python", "README.md")) as fh:
        content = fh.read()
    assert PY_VERSION in content, "README lacks %s" % PY_VERSION
    return True


@check("Tree: no uncommitted changes")
def check_clean():
    proc = _run(["git", "status", "--porcelain"], timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert proc.stdout.strip() == "", \
        "uncommitted changes:\n%s" % proc.stdout.strip()
    return True


@check("Engine: frozen files untouched (tree + history)")
def check_engine_frozen():
    proc = _run(["git", "status", "--porcelain", "--"]
                + FROZEN_FILES, timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert proc.stdout.strip() == "", \
        "frozen file modified:\n%s" % proc.stdout.strip()
    head = _run(["git", "rev-parse", "HEAD"], timeout=60)
    assert head.returncode == 0
    for path in FROZEN_FILES:
        touched = _run(["git", "log", "--format=%H", "-1", "--", path],
                       timeout=60)
        assert touched.returncode == 0, touched.stderr[-500:]
        assert touched.stdout.strip() != head.stdout.strip(), \
            "%s touched by HEAD commit" % path
    return True


def main(argv=None):
    del argv
    print("forkrun %s release checklist" % PROJECT_VERSION)
    print("=" * 60)
    failures = 0
    for name, fn in CHECKS:
        try:
            fn()
        except AssertionError as exc:
            print("  [FAIL] %s\n         %s" % (name, exc))
            failures += 1
        except Exception as exc:  # noqa: BLE001
            print("  [ERROR] %s\n         %s: %s"
                  % (name, type(exc).__name__, exc))
            failures += 1
        else:
            print("  [PASS] %s" % name)
    print("=" * 60)
    if failures:
        print("SOME CHECKS FAILED (%d) — DO NOT TAG" % failures)
        return 1
    print("ALL CHECKS PASSED — ready to tag %s" % PROJECT_VERSION)
    return 0


if __name__ == "__main__":
    sys.exit(main())
