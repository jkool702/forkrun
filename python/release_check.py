#!/usr/bin/env python3
"""forkrun v3.6.0 release checklist (W-PY23, W-REL5-F F6).

Run from the repo root BEFORE tagging v3.6.0. Every check must pass:

    python3 python/release_check.py

Checks: version coherence, tag freedom (F6.1), changelog finality
(F6.2, DESIGNED RED until the owner finalizes the heading at tag
time), full test suite, canary link check, IDL schema + freshness
(F6.3) checks, reproducible builds, single-artifact wheel/sdist
build with recorded checksums (F6.4), doc twins, clean tree, frozen
engine.

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


_BUILT = {}


def _ensure_artifacts():
    """Build the wheel + sdist ONCE per release_check run (W-REL5-F F6.4).

    Returns (wheel_path, sdist_path). Records sha256 of both (+ HEAD
    + versions) into dist/checksums.txt for the tag bundle. Drops OUR
    OWN stale outputs first, so a leftover tarball can never satisfy
    the checks (the old check_sdist globbed whatever dist/ held).
    dist/ is gitignored build space; the checksums file travels with
    the artifacts it describes.
    """
    if "wheel" in _BUILT:
        return _BUILT["wheel"], _BUILT["sdist"]
    import hashlib
    dist_dir = os.path.join(REPO_ROOT, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    for pat in ("forkrun-%s*.whl" % PY_VERSION,
                "forkrun-%s*.tar.gz" % PY_VERSION):
        for stale in glob.glob(os.path.join(dist_dir, pat)):
            os.remove(stale)
    proc = _run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
                 "-w", dist_dir], timeout=900)
    assert proc.returncode == 0, proc.stderr[-2000:]
    wheels = sorted(glob.glob(
        os.path.join(dist_dir, "forkrun-%s*.whl" % PY_VERSION)))
    assert len(wheels) == 1, \
        "expected exactly one fresh wheel, found %r" % (wheels,)
    proc = _run([sys.executable, "setup.py", "-q", "sdist"], timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    sdists = sorted(glob.glob(
        os.path.join(dist_dir, "forkrun-%s*.tar.gz" % PY_VERSION)))
    assert len(sdists) == 1, \
        "expected exactly one fresh sdist, found %r" % (sdists,)
    head = _run(["git", "rev-parse", "HEAD"], timeout=60)
    lines = []
    for path in wheels + sdists:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1048576), b""):
                h.update(chunk)
        lines.append("%s  %s" % (h.hexdigest(), os.path.basename(path)))
    lines.append("# forkrun %s / py %s / HEAD %s" % (
        PROJECT_VERSION, PY_VERSION, head.stdout.strip()))
    with open(os.path.join(dist_dir, "checksums.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    _BUILT["wheel"], _BUILT["sdist"] = wheels[0], sdists[0]
    return wheels[0], sdists[0]


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


@check("Docs: CHANGELOG %s heading is final (no (unreleased))" % PROJECT_VERSION)
def check_changelog_final():
    # W-REL5-F (F6.2): the release is not final while its own heading
    # says unreleased. Scoped to the release heading (older entries
    # keep their historical markers). DESIGNED RED until the owner
    # finalizes the heading at tag time -- do NOT "fix" this by
    # editing early; the red is the gate working.
    with open(os.path.join(REPO_ROOT, "DOCS", "CHANGELOG.md")) as fh:
        content = fh.read()
    marked = re.search(r"^##\s+%s\s+\(unreleased\)" % re.escape(PROJECT_VERSION),
                       content, re.M)
    assert marked is None, \
        "CHANGELOG.md still heads %s as (unreleased) -- finalize the " \
        "heading at tag time (TAG_PREP_v3.6.0.md step: this red is " \
        "designed, not a bug)" % PROJECT_VERSION
    return True


@check("Docs: no (unreleased) heading on a tagged version")
def check_unreleased_untagged():
    # W-REL6-2.2: the v3.6.0-finality guard above is scoped to the release
    # heading by design (it stays red until tag time). THIS guard catches
    # the wider class: any older heading still marked (unreleased) after
    # its version was tagged (v3.5.2 shipped tagged while its heading said
    # unreleased -- a bug in the changelog itself, fixed alongside this
    # guard). Markers on untagged versions (v3.5.4-v3.5.14: cut but never
    # released) are legitimate and pass.
    with open(os.path.join(REPO_ROOT, "DOCS", "CHANGELOG.md")) as fh:
        content = fh.read()
    marked = re.findall(r"^##\s+(v\S+)\s+\(unreleased\)", content, re.M)
    if not marked:
        return True
    proc = _run(["git", "tag", "--list"], timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    tagged = set(proc.stdout.split())
    bad = [v for v in marked if v in tagged]
    assert not bad, \
        "heading(s) still marked (unreleased) for tagged version(s) %s " \
        "-- drop the marker (the version shipped) or delete the tag" % bad
    return True


@check("Tag: %s not already taken" % PROJECT_VERSION)
def check_tag_free():
    # W-REL5-F (F6.1): tagging over an existing tag would move/fail
    # it. Local tags only (offline-safe); pushing the tag is the
    # owner's step in TAG_PREP_v3.6.0.md.
    proc = _run(["git", "tag", "--list", PROJECT_VERSION], timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    assert proc.stdout.strip() == "", \
        "tag %s already exists locally -- delete it or pick a new " \
        "version (refusing to tag over it)" % PROJECT_VERSION
    return True


def _so_engine_version(so_path):
    """Read fr_py_version() from a substrate .so file (F-PORT5).

    Returns the version string, or raises AssertionError when the
    symbol is missing/unreadable. Used by the engine-match checks
    so wheel-embedded and tree-built substrates are compared by
    the same code path.
    """
    import ctypes
    lib = ctypes.CDLL(so_path)
    fn = getattr(lib, "fr_py_version", None)
    assert fn is not None, "no fr_py_version in %s" % so_path
    fn.argtypes = []
    fn.restype = ctypes.c_char_p
    ver = fn()
    assert ver, "empty fr_py_version from %s" % so_path
    return ver.decode("utf-8") if isinstance(ver, bytes) else str(ver)


@check("Version: META maps %s" % PROJECT_VERSION)
def check_meta_mapping():
    # F-PORT5: META is the Bash-side version source (-V, CI blob
    # rebuild trigger); it must name the release being tagged, or
    # the shipped frun.bash and the Python wheel diverge silently.
    with open(os.path.join(REPO_ROOT, "META")) as fh:
        meta = fh.read()
    assert ("VERSION: %s" % PROJECT_VERSION) in meta, \
        "META lacks VERSION: %s:\n%s" % (PROJECT_VERSION, meta)
    return True


@check("Version: built engine is %s" % PROJECT_VERSION)
def check_engine_version():
    # F-PORT5: the tree-built substrate must report the release
    # version — a stale local .so (or an unbuilt one, "unknown")
    # passing silently is wheel-vs-local drift by another name.
    sys.path.insert(0, os.path.join(REPO_ROOT, "python"))
    import forkrun
    eng = forkrun.__engine_version__
    assert eng == PROJECT_VERSION, (
        "engine %r != %s (rebuild: make -f Makefile.substrate "
        "python-substrate; $FORKRUN_LIB override?)"
        % (eng, PROJECT_VERSION))
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
    # Anti-recursion: the suite contains
    # test_packaging_v2.TestReleaseChecklist, which invokes THIS
    # script on clean trees — running it unguarded nests suites
    # without bound (each level takes ~90s to reach the test
    # again). Mark the child run so the test skips itself there;
    # every other test still runs, so coverage is intact.
    env = dict(os.environ)
    env["FORKRUN_UNDER_RELEASE_CHECK"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover",
         "-s", "python/tests"], capture_output=True, text=True,
        timeout=1200, cwd=REPO_ROOT, env=env)
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


@check("IDL: generated artifacts match (gen_idl.py --check)")
def check_idl_fresh():
    # W-REL5-F (F6.3): the freshness gate used to be CI-only; a stale
    # regen committed without running it would sail through tagging.
    proc = _run([sys.executable, "tools/gen_idl.py", "--check"],
                timeout=300)
    assert proc.returncode == 0, \
        (proc.stdout + proc.stderr)[-2000:]
    return True


@check("Reproducible: two substrate builds are byte-identical")
def check_reproducible():
    proc = _run(["make", "-f", "Makefile.substrate",
                 "reproducibility-check"], timeout=900)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    return True


def _wheel_glibc_floor(wheel):
    """Highest GLIBC_x.y the wheel's .so references, or None.

    The manylinux tag in a wheel filename is a claim about the libc the
    binary needs. It is metadata — nothing validates it at build time —
    so the release gate re-derives the floor from the ELF. Returns None
    when the toolchain to do so (binutils) is unavailable, so the gate
    degrades to tag-shape validation rather than failing spuriously.
    """
    import zipfile
    try:
        with zipfile.ZipFile(wheel) as zf:
            names = [n for n in zf.namelist() if n.endswith(".so")]
            if not names:
                return None
            blob = zf.read(names[0])
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    proc = subprocess.run(["objdump", "-T", "-"], input=blob,
                          capture_output=True)
    if proc.returncode != 0:
        return None
    vers = {(int(a), int(b)) for a, b in
            re.findall(r"GLIBC_(\d+)\.(\d+)", proc.stdout.decode(
                "utf-8", "replace"))}
    return max(vers) if vers else None


@check("Wheel: PEP 600 manylinux tag that the binary actually honors")
def check_wheel():
    # W-REL5-F (F6.4): reads the single shared build (see
    # _ensure_artifacts), not a private pip invocation.
    #
    # W-REL: the old assertion was `"linux_" in name`. That was two
    # bugs at once — it passed for `manylinux_2_28_x86_64` purely as a
    # substring ("many|linux_"), and it would have passed for the bare
    # `linux_x86_64` tag that PyPI rejects outright ("unsupported
    # platform tag"). Assert the tag's SHAPE, and that the binary's
    # glibc floor does not exceed what the tag promises.
    wheel, _ = _ensure_artifacts()
    name = os.path.basename(wheel)
    plat = name[:-len(".whl")].rsplit("-", 1)[-1]
    assert plat != "any", "wheel wrongly tagged py3-none-any: %s" % name
    m = re.match(r"^manylinux_(\d+)_(\d+)_(x86_64|aarch64|i686)$", plat)
    assert m, (
        "wheel platform tag must be PEP 600 manylinux_<maj>_<min>_<arch> "
        "(PyPI rejects a bare linux_* tag); got %r from %s. "
        "Release wheels come from tools/build_wheel.sh." % (plat, name))
    claimed = (int(m.group(1)), int(m.group(2)))
    assert PY_VERSION in name, "wheel version mismatch: %s" % name

    need = _wheel_glibc_floor(wheel)
    if need is not None:
        assert need <= claimed, (
            "wheel is tagged manylinux_%d_%d but the embedded .so "
            "references GLIBC_%d.%d — the tag is a promise pip trusts "
            "and the loader enforces. Build inside the manylinux "
            "container (tools/build_wheel.sh)." % (claimed + need))
    return True


@check("Wheel: METADATA is complete")
def check_metadata():
    import zipfile
    wheel, _ = _ensure_artifacts()
    with zipfile.ZipFile(wheel) as zf:
        meta_names = [n for n in zf.namelist()
                      if n.endswith(".dist-info/METADATA")]
        assert meta_names, "no METADATA in wheel"
        meta = zf.read(meta_names[0]).decode("utf-8")
    for field in ("Name: forkrun", "Version: " + PY_VERSION,
                  "Summary:", "Home-page:",
                  "Requires-Python: >=3.10",
                  "License:", "Classifier:"):
        assert field in meta, "METADATA missing %r" % field
    assert "Development Status :: 4 - Beta" in meta
    return True


@check("sdist: builds and contains all C sources")
def check_sdist():
    # W-REL5-F (F6.4): uses the exact fresh sdist from the shared
    # build (stale tarballs are removed first -- the old glob could
    # pass on leftovers).
    import tarfile
    _, sdist = _ensure_artifacts()
    with tarfile.open(sdist) as tf:
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


@check("Wheel: embedded .so reports %s" % PROJECT_VERSION)
def check_wheel_so_version():
    # F-PORT5: the wheel must SHIP the release engine, not a stale
    # local build. Extract the packaged .so and read its version by
    # the same helper as the tree-built substrate. W-REL5-F (F6.4):
    # reads the single shared build.
    import zipfile
    wheel, _ = _ensure_artifacts()
    with zipfile.ZipFile(wheel) as zf:
        so_names = [n for n in zf.namelist()
                    if n.endswith("libforkrun_python.so")]
        assert so_names, "no substrate .so in wheel"
        so_data = zf.read(so_names[0])
    workdir = tempfile.mkdtemp(prefix="forkrun_release_sovers_")
    try:
        so_path = os.path.join(workdir, "libforkrun_python.so")
        with open(so_path, "wb") as fh:
            fh.write(so_data)
        ver = _so_engine_version(so_path)
        assert ver == PROJECT_VERSION, \
            "wheel-embedded engine %r != %s (stale substrate build)" \
            % (ver, PROJECT_VERSION)
        return True
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


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
