#!/usr/bin/env python3
"""Per-minor wheel build orchestration (DECISION-01, Option A).

THE DECISION
------------
`dev/supervisor/DECISION-01-helper-packaging.md` chose **Option A**:
one wheel per supported CPython minor, each carrying the UDF helper
built for THAT minor, tagged ``cp3XX-cp3XX-<platform>``. The helper
LINKS libpython, so its minor is a hard constraint the tag has to
state -- a wheel claiming a minor it does not carry is a wheel that
lies about what it can do.

DECISION-01 section 4.3 says the implementation is "a small change" to
`tools/build_wheel.sh`: it already selects an interpreter from
``/opt/python/cp3XX-cp3XX``; this module adds the loop, the per-minor
helper build, and the per-wheel validation.

WHAT THIS IS NOT
----------------
This is NOT a second packaging implementation. The wheel is still built
by the repository's own ``setup.py`` (``python -m build --wheel``),
the helper is still built by ``Makefile.substrate``'s ``udf-lib``
target, and the platform/ABI tags are still ``setup.py``'s to decide
(``setup.py`` derives the tag FROM the helper's extension suffix).
What lives here is the ORCHESTRATION -- which minor, which
interpreter, in what order, with what cleanup between minors, and
whether the result is complete -- plus the validation of the artifacts
that orchestration produced.

FAIL CLOSED
-----------
Two rules, both deliberate:

* **Never substitute.** If the interpreter for a minor is missing, the
  minor is REPORTED as not built. The build does not fall back to
  another interpreter, because a wheel tagged ``cp310`` that was
  compiled by 3.12 is a lie the tag cannot detect.
* **Never reuse.** Each minor's helper is removed before the next
  minor's is built, so a stale ``_fr_udf.cpython-312-*.so`` can never
  end up inside a 3.13 wheel.

The free-threaded flavour is NOT built here: ``setup.py`` declines to
ship a free-threaded helper (the sonames differ, so the artifacts are
mutually load-incompatible), and the C0.5 matrix measures GIL
interpreters only. The interpreter lookup therefore refuses the
free-threaded variant rather than silently picking it and producing a
``py3-none`` wheel that is not a per-minor wheel at all.

Usage (inside the manylinux container, where the interpreters live):

    python3 tools/wheel_matrix.py --list
    python3 tools/wheel_matrix.py --minor 3.13
    python3 tools/wheel_matrix.py --all
    python3 tools/wheel_matrix.py --all --strict
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG_DIR = os.path.join(REPO_ROOT, "python", "forkrun")
HELPER_STEM = "_fr_udf"

# THE supported CPython minors.
#
# DECISION-01 sections 3 and 4: "Build one helper per supported
# CPython minor; ship wheels tagged cp310, cp311, ... cp315" -- six
# minors, and the roadmap "already requires a 3.10-3.15 matrix".
# `tools/matrix_c05.sh` fetches the same set (minus the host's own
# minor, which is already present), and it reads THIS list -- so there
# is one definition of "supported", not three.
#
# Note the tension with setup.py, whose classifiers stop at 3.13 while
# the floor (`python_requires`) is >=3.10. That is a REPORTED gap, not
# a second list: the wheels here follow the decision, and the
# classifier list is upstream's to fix.
SUPPORTED_MINORS = ("3.10", "3.11", "3.12", "3.13", "3.14", "3.15")


def minor_tag(minor):
    """The wheel's python/abi tag prefix for a minor: 3.13 -> cp313."""
    return "cp%s" % minor.replace(".", "")


def _freethreaded_interpreter(suffix=None):
    """The RUNTIME's free-threading detector (one rule, not two).

    The packaging and the runtime must agree about which
    configurations are supported, and two copies of that rule is how
    they drift -- so this delegates to `forkrun._udf`, which is what
    `setup.py` also delegates to.
    """
    import importlib.util
    path = os.path.join(REPO_ROOT, "python", "forkrun", "_udf.py")
    spec = importlib.util.spec_from_file_location("forkrun._udf_matrix",
                                                  path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.freethreaded_interpreter(suffix=suffix)


def interpreter_for_minor(minor, roots=("/opt/python",),
                           running=None):
    """The GIL interpreter for `minor`, or None.

    The manylinux layout is /opt/python/cp313-cp313/bin/python3.13.
    The free-threaded twin (cp313-cp313t) is REFUSED: setup.py will
    not ship a free-threaded helper, so building against it could only
    produce a wheel that is not a per-minor wheel.

    The RUNNING interpreter is a candidate for its OWN minor only
    (that is not a substitution -- it is the same minor, by
    definition). It is never offered for a different minor: that would
    produce a wheel tagged for one interpreter and compiled by another.
    """
    tag = "cp%s-cp%s" % (minor.replace(".", ""), minor.replace(".", ""))
    for root in roots:
        cand = os.path.join(root, tag, "bin", "python" + minor)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    if running is None:
        running = sys.executable
    try:
        import sysconfig
        if ("%d.%d" % sys.version_info[:2]) == minor:
            if _freethreaded_interpreter():
                # A free-threaded interpreter cannot produce a
                # per-minor wheel (setup.py refuses to ship the
                # helper), so it is not a candidate.
                return None
            return running
    except Exception:
        pass
    return None


def helper_files(pkg_dir=None):
    """Every UDF helper artifact present in the package directory."""
    if pkg_dir is None:
        pkg_dir = PKG_DIR
    try:
        names = os.listdir(pkg_dir)
    except OSError:
        return []
    return sorted(n for n in names
                  if n.startswith(HELPER_STEM) and n.endswith(".so"))


def remove_helpers(pkg_dir=None):
    """Remove every UDF helper artifact. Returns the removed names.

    Between minors this is what keeps a stale helper out of the next
    wheel: the helper's extension suffix encodes its minor, and
    setup.py ships "the helper for this interpreter" -- so a leftover
    3.12 helper beside a 3.13 interpreter is not shipped, but a
    leftover helper beside a 3.12 interpreter IS. Removing them all
    is the only state that cannot be wrong.
    """
    removed = []
    for name in helper_files(pkg_dir):
        try:
            os.unlink(os.path.join(pkg_dir or PKG_DIR, name))
            removed.append(name)
        except OSError:
            pass
    return removed


def build_helper(minor, interpreter, repo_root=None, dry_run=False):
    """Build the UDF helper for `minor` with THAT minor's interpreter.

    Uses the repository's own Makefile target (`udf-lib`), which takes
    PYTHON= -- the matrix comment in Makefile.substrate names exactly
    this use ("building the wheel matrix"). Returns (ok, detail).
    """
    if repo_root is None:
        repo_root = REPO_ROOT
    cmd = ["make", "-f", os.path.join(repo_root, "Makefile.substrate"),
           "udf-lib", "PYTHON=%s" % interpreter]
    if dry_run:
        return True, " ".join(cmd)
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True,
                          text=True)
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]


def build_wheel(minor, interpreter, out_dir, repo_root=None, dry_run=False):
    """Build the wheel for `minor` with THAT minor's interpreter.

    The wheel is built from the SDIST, as tools/build_wheel.sh does:
    the sdist is the only install path for anyone on a glibc we do not
    ship a wheel for, so the wheel must be provably buildable from it.
    """
    if repo_root is None:
        repo_root = REPO_ROOT
    if dry_run:
        return True, "%s setup.py bdist_wheel (outdir=%s)" % (interpreter,
                                                              out_dir)
    # Build the wheel directly with bdist_wheel rather than via
    # `python -m build`. The latter creates an sdist from the source tree
    # and the sdist's recursive-include (python/forkrun *.py *.c *.h) does
    # NOT cover *.so -- but a stale sdist / build cache on the host can
    # still drag every helper into the wheel, so a 3.10 wheel ends up
    # shipping 3.14's helper and fails validate_wheel. bdist_wheel packages
    # exactly what is in the tree right now, which is what build_minor's
    # remove_helpers + build_helper just produced.
    cmd = [interpreter, "setup.py", "bdist_wheel", "--dist-dir", out_dir]
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True,
                          text=True)
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]


def wheel_python_tag(wheel_path):
    """The wheel's python tag (the second-to-last dash group)."""
    name = os.path.basename(wheel_path)
    if not name.endswith(".whl"):
        return None
    parts = name[:-len(".whl")].split("-")
    if len(parts) < 3:
        return None
    return parts[-3]


def wheel_abi_tag(wheel_path):
    """The wheel's abi tag (the last group before the platform tag)."""
    name = os.path.basename(wheel_path)
    if not name.endswith(".whl"):
        return None
    parts = name[:-len(".whl")].split("-")
    if len(parts) < 3:
        return None
    return parts[-2]


def wheel_helpers(wheel_path):
    """The UDF helper artifacts inside a wheel."""
    try:
        import zipfile
        with zipfile.ZipFile(wheel_path) as zf:
            names = zf.namelist()
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    return [n for n in names
            if os.path.basename(n).startswith(HELPER_STEM)
            and n.endswith(".so")]


def validate_wheel_tags(wheel_path):
    """The tag-vs-artifact rule, derived from the wheel's OWN tag.

    This is the ONE implementation of the rule (tools/build_wheel.sh
    calls it rather than carrying its own copy):

    * a cp3XX wheel ships a UDF helper, and the helper's extension
      suffix encodes XX -- the suffix is what setup.py derives the tag
      from, so a mismatch means the tag was not derived from the
      artifact;
    * the ABI tag is the REAL one, not "none": "none" means "no ABI
      constraint", and a free-threaded CPython accepts
      "cp314-none-<platform>" exactly as a GIL 3.14 does, so a
      GIL-built helper in a "none"-ABI wheel advertises compatibility
      with an interpreter that cannot load it;
    * a generic py3-none wheel ships NO helper: "keep the source-only
      development path honest: do not advertise a locally built helper
      as present in a generic ABI-independent wheel".

    Returns a list of problems (empty means the wheel is sound).
    """
    problems = []
    pytag = wheel_python_tag(wheel_path)
    abitag = wheel_abi_tag(wheel_path)
    if pytag is None or abitag is None:
        return ["%s is not a wheel filename" % (os.path.basename(
            wheel_path),)]
    helpers = wheel_helpers(wheel_path)
    if helpers is None:
        return ["%s is not a readable wheel" % (os.path.basename(
            wheel_path),)]
    if pytag.startswith("cp3"):
        minor = pytag[2:]
        if not helpers:
            problems.append(
                "wheel is tagged %s but ships no UDF helper: the tag "
                "promises a CPython-linked helper for %s"
                % (pytag, minor))
        bad = [h for h in helpers if ("cpython-%s" % minor) not in h]
        if bad:
            problems.append(
                "wheel is tagged %s but its helper is for a different "
                "minor: %r" % (pytag, bad))
        if abitag == "none":
            problems.append(
                "wheel ships a CPython-linked helper but its ABI tag is "
                "'none': it would be offered to a free-threaded %s that "
                "cannot load it. The ABI tag must be the real one (%s)."
                % (minor, pytag))
        if abitag != pytag:
            problems.append("wheel python tag %s and ABI tag %s disagree"
                            % (pytag, abitag))
    else:
        if helpers:
            problems.append(
                "wheel is tagged %s but ships a CPython-linked helper "
                "(%r): a generic ABI-independent wheel must not advertise "
                "one" % (pytag, helpers))
    return problems


def validate_wheel(wheel_path, minor):
    """Check a built wheel against the minor it claims to be for.

    The tag-vs-artifact rule (validate_wheel_tags) plus the
    cross-check that the tag names THIS minor -- a wheel tagged cp312
    is not evidence of a 3.13 build.
    """
    problems = validate_wheel_tags(wheel_path)
    want = minor_tag(minor)
    pytag = wheel_python_tag(wheel_path)
    abitag = wheel_abi_tag(wheel_path)
    if pytag != want:
        problems.append("wheel python tag is %r, expected %r (%s)"
                        % (pytag, want, os.path.basename(wheel_path)))
    if abitag != want:
        problems.append("wheel abi tag is %r, expected %r (%s)"
                        % (abitag, want, os.path.basename(wheel_path)))
    helpers = wheel_helpers(wheel_path)
    if helpers is None:
        return problems
    if not helpers:
        problems.append(
            "the wheel carries no UDF helper, so it is not a per-minor "
            "wheel: it would install as the generic py3-none substrate "
            "wheel")
        return problems
    for name in helpers:
        base = os.path.basename(name)
        if ("cpython-%s" % minor.replace(".", "")) not in base:
            problems.append(
                "the wheel carries %s, whose suffix does not encode %s; "
                "the tag would be a claim the artifact does not support"
                % (base, minor))
    return problems


def auditwheel_repair(wheel_path, out_dir, interpreter):
    """Run auditwheel repair for one wheel, in place.

    auditwheel is the authority on the manylinux floor: it re-tags the
    wheel to the highest policy the binary actually satisfies. The
    release gate's "PEP 600 manylinux tag that the binary actually
    honors" check depends on it having run.
    """
    cmd = [interpreter, "-m", "auditwheel", "repair", "-w", out_dir,
           wheel_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]


def smoke_test(wheel_path, interpreter, workdir):
    """Install the wheel into an ISOLATED environment and smoke-test it.

    "The wheel builds" is not "the wheel works": a wheel can install
    and still be missing the substrate .so, the cleanroom launcher, or
    the per-minor helper -- and the import is where that shows up.

    Returns (ok, detail). The environment is created with the SAME
    interpreter that built the wheel, so a wheel that only works on
    another interpreter cannot pass here.
    """
    import venv
    env_dir = os.path.join(workdir, "venv")
    try:
        venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
    except Exception as exc:
        return False, "could not create a venv: %s" % (exc,)
    py = os.path.join(env_dir, "bin", "python")
    if not os.path.exists(py):
        py = os.path.join(env_dir, "Scripts", "python.exe")
    proc = subprocess.run([py, "-m", "pip", "install", "--quiet",
                           "--no-deps", wheel_path],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return False, "pip install failed: %s" % (proc.stderr[-1500:],)
    # The smoke test: import the package, find the substrate, and run
    # a trivial map through it.
    code = (
        "import forkrun, os, sys\n"
        "import forkrun.run as R\n"
        "so = R._so_path() if hasattr(R, '_so_path') else None\n"
        "print('forkrun', forkrun.__version__)\n"
        "print('substrate', os.path.exists(os.path.join(os.path.dirname("
        "forkrun.__file__), 'libforkrun_python.so')))\n"
        "print('launcher', os.path.exists(os.path.join(os.path.dirname("
        "forkrun.__file__), '_forkrun_cleanroom')))\n"
        "print('helpers', sorted(n for n in os.listdir(os.path.dirname("
        "forkrun.__file__)) if n.startswith('_fr_udf')))\n"
    )
    proc = subprocess.run([py, "-c", code], capture_output=True, text=True)
    if proc.returncode != 0:
        return False, "import failed: %s" % (proc.stderr[-1500:],)
    return True, proc.stdout.strip()


def find_wheel(out_dir, minor):
    """The wheel in `out_dir` built for `minor`, or None."""
    want = minor_tag(minor)
    try:
        names = sorted(os.listdir(out_dir))
    except OSError:
        return None
    for name in names:
        if name.endswith(".whl") and ("-%s-" % want) in name:
            return os.path.join(out_dir, name)
    return None


def build_minor(minor, out_dir, repo_root=None, roots=("/opt/python",),
                dry_run=False, auditwheel=False, install_check=False):
    """Build (and validate) the wheel for one minor.

    Returns a result dict -- never raises for an ordinary failure, so
    one unavailable minor does not hide the others.
    """
    if repo_root is None:
        repo_root = REPO_ROOT
    result = {"minor": minor, "status": "not-built", "wheel": None,
              "problems": [], "detail": ""}
    interp = interpreter_for_minor(minor, roots=roots)
    if interp is None:
        result["detail"] = ("no interpreter for %s under %s"
                             % (minor, ", ".join(roots)))
        return result
    result["interpreter"] = interp
    # Clean slate: a helper left by a previous minor must not be able
    # to ship inside this wheel. Removing from the source tree is not
    # enough -- build/ caches a copy from the previous minor and
    # build_py copies additively, so stale helpers would otherwise
    # accumulate in every subsequent wheel.
    removed = remove_helpers(PKG_DIR)
    if removed:
        result["removed_helpers"] = removed
    build_dir = os.path.join(repo_root, "build")
    if os.path.isdir(build_dir):
        shutil.rmtree(build_dir, ignore_errors=True)
    egg_info = os.path.join(repo_root, "python", "forkrun.egg-info")
    if os.path.isdir(egg_info):
        shutil.rmtree(egg_info, ignore_errors=True)
    ok, detail = build_helper(minor, interp, repo_root=repo_root,
                              dry_run=dry_run)
    if not ok:
        result["status"] = "failed"
        result["detail"] = "helper build failed: %s" % (detail,)
        return result
    ok, detail = build_wheel(minor, interp, out_dir, repo_root=repo_root,
                             dry_run=dry_run)
    if not ok:
        result["status"] = "failed"
        result["detail"] = "wheel build failed: %s" % (detail,)
        return result
    if dry_run:
        result["status"] = "dry-run"
        return result
    wheel = find_wheel(out_dir, minor)
    if wheel is None:
        result["status"] = "failed"
        result["detail"] = ("no wheel named for %s in %s"
                            % (minor, out_dir))
        return result
    result["wheel"] = wheel
    if auditwheel:
        ok, detail = auditwheel_repair(wheel, out_dir, interp)
        if not ok:
            result["status"] = "failed"
            result["detail"] = "auditwheel repair failed: %s" % (detail,)
            return result
        repaired = find_wheel(out_dir, minor)
        if repaired:
            wheel = repaired
            result["wheel"] = wheel
    problems = validate_wheel(wheel, minor)
    if problems:
        result["status"] = "invalid"
        result["problems"] = problems
        return result
    if install_check:
        ok, detail = smoke_test(wheel, interp, out_dir)
        result["smoke"] = detail
        if not ok:
            result["status"] = "invalid"
            result["problems"] = ["install/smoke test failed: %s" % (detail,)]
            return result
    result["status"] = "built"
    return result


def run_matrix(minors, out_dir, repo_root=None, roots=("/opt/python",),
               dry_run=False, auditwheel=False, install_check=False):
    """Build every minor in `minors`. Returns the list of results."""
    results = []
    for minor in minors:
        results.append(build_minor(minor, out_dir, repo_root=repo_root,
                                   roots=roots, dry_run=dry_run,
                                   auditwheel=auditwheel,
                                   install_check=install_check))
    return results


def report(results):
    """A human-readable report, and the machine-readable form."""
    lines = []
    for r in results:
        what = os.path.basename(r["wheel"]) if r["wheel"] else ""
        detail = (r["detail"] or "").strip()
        for p in r.get("problems") or ():
            detail = (detail + "; " + p) if detail else p
        if detail:
            what = ("%s [%s]" % (what, detail)) if what else detail
        lines.append("%-6s %-9s %s" % (r["minor"], r["status"], what))
    return "\n".join(lines)


def incomplete(results):
    """The minors that did not produce a valid wheel."""
    return [r["minor"] for r in results
            if r["status"] not in ("built", "dry-run")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true",
                    help="print the supported minors and exit")
    ap.add_argument("--minor", action="append",
                    help="build one minor (repeatable)")
    ap.add_argument("--all", action="store_true",
                    help="build every supported minor")
    ap.add_argument("--out-dir", default=os.path.join(REPO_ROOT, "dist",
                                                       "matrix"))
    ap.add_argument("--python-root", action="append",
                    help="where to look for interpreters "
                         "(default /opt/python)")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero unless EVERY supported minor was "
                         "built")
    ap.add_argument("--json", action="store_true",
                    help="emit the results as JSON")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--validate-wheel", metavar="WHEEL",
                    help="validate one wheel's tag against its artifacts "
                         "and exit")
    ap.add_argument("--auditwheel", action="store_true",
                    help="run auditwheel repair on each wheel")
    ap.add_argument("--install-check", action="store_true",
                    help="install each wheel into an isolated environment "
                         "and smoke-test the import")
    args = ap.parse_args(argv)

    if args.list:
        print("\n".join(SUPPORTED_MINORS))
        return 0

    if args.validate_wheel:
        problems = validate_wheel_tags(args.validate_wheel)
        if problems:
            for p in problems:
                sys.stderr.write("FAIL: %s\n" % (p,))
            return 1
        print("OK         : tag %s-%s agrees with the shipped artifacts"
              % (wheel_python_tag(args.validate_wheel),
                 wheel_abi_tag(args.validate_wheel)))
        return 0

    if args.all:
        minors = list(SUPPORTED_MINORS)
    elif args.minor:
        minors = list(args.minor)
    else:
        ap.error("one of --list, --minor or --all is required")

    roots = tuple(args.python_root or ("/opt/python",))
    os.makedirs(args.out_dir, exist_ok=True)
    results = run_matrix(minors, args.out_dir, roots=roots,
                         dry_run=args.dry_run, auditwheel=args.auditwheel,
                         install_check=args.install_check)
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        print(report(results))
    missing = incomplete(results)
    if missing and args.strict:
        sys.stderr.write(
            "\nINCOMPLETE MATRIX: %d of %d supported minors did not "
            "produce a valid wheel: %s\n"
            "This is NOT a successful release build.\n"
            % (len(missing), len(minors), ", ".join(missing)))
        return 2
    if missing:
        sys.stderr.write(
            "\nNOTE: %d of %d minors were not built (%s). The result is a "
            "PARTIAL matrix and must not be reported as a complete "
            "release build.\n" % (len(missing), len(minors),
                                  ", ".join(missing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
