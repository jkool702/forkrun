#!/usr/bin/env python3
"""Installed-wheel acceptance test (WO-COMPAT-04A Lane B / WO-COMPAT-05A Lane C).

PROVES, from the artifact a user would install:

  * the wheel's filename tag agrees with the artifacts INSIDE it
    (`tools/wheel_matrix.py` is the one authority for that rule);
  * the wheel carries an exact, complete set of runtime members
    (package, substrate, launcher, and -- for UDF mode -- one helper
    whose extension suffix is THIS interpreter's EXT_SUFFIX);
  * a clean venv created by the REQUESTED interpreter installs it, and
    every required installed file is byte-for-byte the wheel's member
    (SHA-256), not merely "some file with that name";
  * the imported package resolves to that venv, not a source checkout,
    a user site directory, or a FORKRUN_LIB override;
  * a real workload produces byte-exact output;
  * for UDF mode, the work ran in a separate process under the
    launcher's isolated embedded interpreter, at the requested minor --
    not through the in-process fallback. A fresh nonce makes a stale
    marker from a previous run unusable.

The harness NEVER inherits a proxy variable that could select a
different library or execution route: every FORKRUN_* / PYTHON* key is
dropped from the child environment and LD_PRELOAD/LD_AUDIT are cleared.

Usage:
    python3 tools/acceptance_installed_wheel.py \\
        --wheel dist/forkrun-...-manylinux_2_28_x86_64.whl \\
        --interpreter /opt/python/cp310-cp310/bin/python3.10 \\
        --expect-minor 3.10 \\
        --mode generic|udf \\
        [--udf-func MODULE:FUNC]   # required for mode=udf

Exits 0 only on a fully verified pass. Prints a JSON report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import BytesParser
from email.policy import default as _EMAIL_POLICY

_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import wheel_matrix  # noqa: E402

REQUIRED_MEMBERS = (
    "forkrun/__init__.py",
    "forkrun/libforkrun_python.so",
    "forkrun/_forkrun_cleanroom",
)
HELPER_STEM = "_fr_udf"
_MINOR_RE = re.compile(r"^\d+\.\d+$")

# Variables an ambient shell (or a previous test) must never be able to
# use to redirect the acceptance run. Prefix rules cover the whole
# FORKRUN_* and PYTHON* namespaces; the LD_* entries can substitute code
# or an audit library, and FR_UDF_HOME relocates the embedded
# interpreter's stdlib.
_DROP_PREFIXES = ("FORKRUN_", "PYTHON")
_DROP_EXACT = ("LD_PRELOAD", "LD_AUDIT", "FR_UDF_HOME")


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _inside(child, parent):
    try:
        return os.path.commonpath([child, parent]) == parent
    except (ValueError, TypeError):
        return False


def _run(cmd, *, env=None, cwd=None, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True,
                          errors="replace", env=env, cwd=cwd,
                          timeout=timeout)


def _run_with_pid(cmd, *, env=None, cwd=None, timeout=600):
    """Run a child and return (its real pid, CompletedProcess).

    The UDF driver reports its own pid, but a self-report is not evidence
    that the isolated helper is a DIFFERENT process: a fallback would
    report the same pid it is running in. The caller therefore compares
    the driver's claim against the pid the kernel actually assigned, and
    every marker against that pid as well.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            errors="replace", env=env, cwd=cwd)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        return proc.pid, subprocess.CompletedProcess(
            cmd, -9, stdout, stderr)
    return proc.pid, subprocess.CompletedProcess(
        cmd, proc.returncode, stdout, stderr)


def _last_json(prefix, stdout):
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            try:
                return json.loads(line[len(prefix):])
            except ValueError:
                return None
    return None


def build_child_env(parent_env, lib_dir, extra=None):
    """The one child-environment rule: no inherited proxy may decide.

    Keeping PATH/HOME/LANG is ordinary process hygiene. Dropping the
    FORKRUN_* namespace is the load-bearing part: FORKRUN_LIB,
    FORKRUN_CLEANROOM, FORKRUN_NO_UDF and FORKRUN_CLEANROOM_NUMA can
    each make an acceptance run measure something other than the
    installed wheel. FR_UDF_HOME is dropped for the same reason: it
    overrides the embedded interpreter's `home`, i.e. which stdlib the
    helper initializes against, so an inherited value could make a
    relocated interpreter pass where the installed one would not.
    FR_UDF_TRACEBACK is deliberately KEPT: it changes only how much of
    an error is printed, never what the run decides, and dropping it
    would hide diagnostics from a caller who asked for them. The
    returned audit lists what was removed so the report can show it.
    """
    env = {}
    removed = []
    for key, value in (parent_env or {}).items():
        if key.startswith(_DROP_PREFIXES) or key in _DROP_EXACT:
            removed.append(key)
            continue
        env[key] = value
    env["PATH"] = env.get("PATH") or "/usr/local/bin:/usr/bin:/bin"
    env["HOME"] = env.get("HOME") or tempfile.gettempdir()
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")
    env["LD_LIBRARY_PATH"] = lib_dir or ""
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return {k: v for k, v in env.items() if v != ""}, sorted(removed)


def probe_interpreter(interpreter, env):
    """Ask the REQUESTED interpreter what it actually is.

    Returns (info, problems). `libdir` is asked for rather than derived
    from the executable path: /usr/bin/python3.14 needs /usr/lib64 on
    Fedora, while a manylinux interpreter needs its own prefix/lib.
    """
    code = (
        "import json, os, sys, sysconfig\n"
        "print('PROBE=' + json.dumps({\n"
        "  'minor': '%d.%d' % sys.version_info[:2],\n"
        "  'patch': '%d.%d.%d' % sys.version_info[:3],\n"
        "  'executable': os.path.realpath(sys.executable),\n"
        "  'libdir': sysconfig.get_config_var('LIBDIR') or '',\n"
        "  'ldlibrary': (sysconfig.get_config_var('LDLIBRARY')\n"
        "                or sysconfig.get_config_var('LIBRARY') or ''),\n"
        "  'suffix': sysconfig.get_config_var('EXT_SUFFIX') or '.so',\n"
        "  'shared': bool(sysconfig.get_config_var('Py_ENABLE_SHARED')),\n"
        "}))\n"
    )
    r = _run([interpreter, "-c", code], env=env)
    info = _last_json("PROBE=", r.stdout)
    if r.returncode != 0 or not info:
        return None, ["could not probe interpreter %r: %s"
                      % (interpreter, (r.stderr or r.stdout)[-800:].strip())]
    problems = []
    if not info.get("suffix"):
        problems.append("interpreter reported no EXT_SUFFIX")
    return info, problems


def _wheel_parts(wheel_path):
    name = os.path.basename(wheel_path)
    if not name.endswith(".whl"):
        return None
    parts = name[:-len(".whl")].split("-")
    if len(parts) < 5:
        return None
    return {
        "distribution": parts[0],
        "version": parts[1],
        "python": parts[-3],
        "abi": parts[-2],
        "platform": parts[-1],
        "parts": parts,
    }


def inspect_wheel(wheel_path, expect_minor, mode, expected_suffix=None):
    """Inspect the artifact before anything is installed.

    Pure enough to test against synthetic wheels: the only input beyond
    the path is the expected minor and the interpreter's suffix.
    """
    problems = []
    info = {"path": os.path.abspath(wheel_path), "mode": mode,
            "expect_minor": expect_minor, "members": [], "helper": None}
    if not os.path.isfile(wheel_path):
        problems.append("wheel does not exist: %s" % (wheel_path,))
        return info, problems
    parts = _wheel_parts(wheel_path)
    if parts is None:
        problems.append("not a wheel filename: %s"
                        % (os.path.basename(wheel_path),))
        return info, problems
    info.update({k: parts[k] for k in
                 ("distribution", "version", "python", "abi", "platform")})
    if parts["distribution"] != "forkrun":
        problems.append("wheel distribution is %r, expected 'forkrun'"
                        % (parts["distribution"],))
    if not parts["platform"].startswith("manylinux_"):
        problems.append(
            "wheel platform tag %r is not a PEP 600 manylinux tag"
            % (parts["platform"],))
    if parts["python"] == "py3":
        if mode == "udf":
            problems.append(
                "generic py3 wheel cannot satisfy UDF acceptance: it "
                "ships no minor-specific helper")
        if parts["abi"] != "none":
            problems.append(
                "generic wheel ABI tag is %r, expected 'none'"
                % (parts["abi"],))
    elif mode == "generic":
        problems.append(
            "generic acceptance requires a py3-none wheel, got %s-%s"
            % (parts["python"], parts["abi"]))

    # Reuse the repository's one tag-vs-artifact rule. For UDF mode the
    # stronger form additionally requires the wheel to name THIS minor.
    if mode == "udf":
        tag_problems = wheel_matrix.validate_wheel(wheel_path, expect_minor)
    else:
        tag_problems = wheel_matrix.validate_wheel_tags(wheel_path)
    if tag_problems:
        problems.extend("wheel: " + p for p in tag_problems)
        if any("not a readable wheel" in p for p in tag_problems):
            return info, problems

    try:
        with zipfile.ZipFile(wheel_path) as zf:
            names = zf.namelist()
            metadata = [n for n in names
                        if n.startswith("forkrun-")
                        and n.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                problems.append(
                    "wheel must contain exactly one forkrun dist-info "
                    "METADATA, found %d" % (len(metadata),))
            else:
                parsed = BytesParser(policy=_EMAIL_POLICY).parsebytes(
                    zf.read(metadata[0]))
                meta_name = (parsed.get("Name") or "").strip()
                meta_version = (parsed.get("Version") or "").strip()
                info["metadata_name"] = meta_name
                info["metadata_version"] = meta_version
                if meta_name != "forkrun":
                    problems.append(
                        "wheel METADATA Name is %r, expected 'forkrun'"
                        % (meta_name,))
                if meta_version != parts["version"]:
                    problems.append(
                        "wheel filename version %r and METADATA version "
                        "%r disagree" % (parts["version"], meta_version))
            info["members"] = sorted(names)
            if len(set(names)) != len(names):
                problems.append("wheel contains duplicate member names")
            for name in names:
                if name.startswith("/") or ".." in name.split("/"):
                    problems.append(
                        "wheel member %r escapes the install root" % (name,))
            for rel in REQUIRED_MEMBERS:
                if rel not in names:
                    problems.append(
                        "wheel is missing required member %r" % (rel,))
            helpers = [n for n in names
                       if os.path.basename(n).startswith(HELPER_STEM)
                       and n.endswith(".so")]
            info["helpers"] = helpers
            if mode == "udf":
                if len(helpers) != 1:
                    problems.append(
                        "UDF wheel must carry exactly one helper, found %r"
                        % (helpers,))
                if expected_suffix is None:
                    problems.append(
                        "cannot verify the UDF helper suffix: the "
                        "interpreter's EXT_SUFFIX was not obtained")
                elif helpers:
                    expected = HELPER_STEM + expected_suffix
                    info["expected_helper"] = "forkrun/" + expected
                    for h in helpers:
                        if os.path.dirname(h) != "forkrun":
                            problems.append(
                                "UDF helper %r is not inside forkrun/"
                                % (h,))
                        if os.path.basename(h) != expected:
                            problems.append(
                                "UDF helper %r does not match this "
                                "interpreter's EXT_SUFFIX (expected %r)"
                                % (os.path.basename(h), expected))
                    info["helper"] = helpers[0]
            else:
                if helpers:
                    problems.append(
                        "generic wheel must carry no UDF helper, found %r"
                        % (helpers,))
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        problems.append("wheel is not a readable zip: %s" % (exc,))
    return info, problems


def verify_installed_files(wheel_path, install_root, members):
    """Every required member is byte-identical to the installed file.

    Containment alone is not provenance: a stale file with the right
    NAME inside the venv would pass it. SHA-256 ties the installed bytes
    to the artifact that was inspected.
    """
    problems = []
    evidence = {}
    root_real = os.path.realpath(install_root)
    try:
        zf = zipfile.ZipFile(wheel_path)
    except (OSError, zipfile.BadZipFile) as exc:
        return {}, ["cannot reopen wheel for provenance: %s" % (exc,)]
    with zf:
        for rel in members:
            try:
                expected = zf.read(rel)
            except KeyError:
                problems.append("wheel has no member %r" % (rel,))
                continue
            dest = os.path.join(install_root, rel)
            if not os.path.isfile(dest):
                problems.append("installed file missing: %s" % (dest,))
                continue
            real = os.path.realpath(dest)
            if not _inside(real, root_real):
                problems.append(
                    "installed file resolves outside the venv: %s -> %s"
                    % (dest, real))
                continue
            actual = _sha256_file(dest)
            want = _sha256_bytes(expected)
            if actual != want:
                problems.append(
                    "installed bytes differ from the wheel for %s "
                    "(wheel %s, installed %s)" % (rel, want, actual))
                continue
            evidence[rel] = {"sha256": actual, "size": len(expected)}
    return evidence, problems


def evaluate_generic_report(report, expected_bytes, expected_sha256):
    problems = []
    if not isinstance(report, dict):
        return ["generic driver did not emit a JSON report"]
    if report.get("bytes") != expected_bytes:
        problems.append("generic output length %r, expected %r"
                        % (report.get("bytes"), expected_bytes))
    if report.get("sha256") != expected_sha256:
        problems.append("generic output SHA-256 %r, expected %r"
                        % (report.get("sha256"), expected_sha256))
    return problems


def evaluate_udf_report(report, *, expect_minor, expected_bytes,
                        expected_sha256, parent_pid, nonce):
    """Judge the UDF run from the DRIVER's facts, independently.

    A driver that claims success is not evidence: every property that
    distinguishes the launcher's isolated helper from the in-process
    fallback is re-checked here, and a marker is only accepted if it
    carries THIS run's nonce.
    """
    problems = []
    if not isinstance(report, dict):
        return ["UDF driver did not emit a JSON report"]
    if report.get("bytes") != expected_bytes:
        problems.append("UDF output length %r, expected %r"
                        % (report.get("bytes"), expected_bytes))
    if report.get("sha256") != expected_sha256:
        problems.append("UDF output SHA-256 %r, expected %r"
                        % (report.get("sha256"), expected_sha256))
    if report.get("parent_pid") != parent_pid:
        problems.append(
            "UDF driver reported parent_pid %r, expected %r"
            % (report.get("parent_pid"), parent_pid))
    markers = report.get("markers")
    if not isinstance(markers, list) or not markers:
        problems.append(
            "no UDF marker was written; the workload did not prove "
            "helper execution")
        return problems
    for idx, marker in enumerate(markers):
        where = "UDF marker %d" % (idx,)
        if not isinstance(marker, dict):
            problems.append("%s is not an object" % (where,))
            continue
        if marker.get("nonce") != nonce:
            problems.append(
                "%s carries nonce %r, not this run's nonce %r (stale or "
                "foreign marker)" % (where, marker.get("nonce"), nonce))
        if marker.get("version") != expect_minor:
            problems.append(
                "%s ran under Python %r, expected %r"
                % (where, marker.get("version"), expect_minor))
        if marker.get("isolated") is not True:
            problems.append(
                "%s was not produced by the launcher's isolated embedded "
                "interpreter (isolated=%r)" % (where,
                                               marker.get("isolated")))
        pid = marker.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            problems.append("%s has no usable pid (%r)" % (where, pid))
        elif pid == parent_pid:
            problems.append(
                "%s ran in the caller process (pid %d), not a separate "
                "helper process" % (where, pid))
    return problems


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _make_workdir(requested):
    if requested:
        os.makedirs(requested, exist_ok=True)
        return os.path.abspath(requested)
    return tempfile.mkdtemp(prefix="fr_accept_")


def _fail(report, problems):
    report["problems"] = list(problems)
    report["result"] = "FAIL"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wheel", required=True)
    ap.add_argument("--interpreter", required=True)
    ap.add_argument("--expect-minor", required=True,
                    help="the CPython minor this wheel/lane must be, e.g. 3.10")
    ap.add_argument("--mode", choices=("generic", "udf"), required=True)
    ap.add_argument("--udf-func", default=None,
                    help="MODULE:FUNC importable from --workdir for UDF mode")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args(argv)

    report = {
        "mode": args.mode,
        "wheel": os.path.abspath(args.wheel),
        "interpreter": args.interpreter,
        "expect_minor": args.expect_minor,
    }
    try:
        return _run_acceptance(args, report)
    except Exception as exc:  # fail closed, with the diagnosis, not a traceback
        return _fail(report, ["unexpected acceptance failure: %s: %s"
                              % (type(exc).__name__, exc)])


def _run_acceptance(args, report):
    problems = []

    # --- 1. Arguments that need no subprocess -------------------------
    if not _MINOR_RE.match(args.expect_minor or ""):
        return _fail(report, ["--expect-minor %r is not MAJOR.MINOR"
                              % (args.expect_minor,)])
    if args.expect_minor not in wheel_matrix.SUPPORTED_MINORS:
        return _fail(report, [
            "--expect-minor %s is not supported; tools/wheel_matrix.py "
            "SUPPORTED_MINORS is %r"
            % (args.expect_minor, list(wheel_matrix.SUPPORTED_MINORS))])
    udf_spec = None
    if args.mode == "udf":
        if not args.udf_func:
            return _fail(report, ["--udf-func is required for mode=udf"])
        if args.udf_func.count(":") != 1:
            return _fail(report, ["--udf-func must be MODULE:FUNC, got %r"
                                  % (args.udf_func,)])
        module, attr = args.udf_func.split(":", 1)
        if not module or not attr:
            return _fail(report, ["--udf-func must name both a module and "
                                  "an attribute, got %r" % (args.udf_func,)])
        udf_spec = (module, attr)
    report["udf_func"] = args.udf_func

    wheel = os.path.abspath(args.wheel)
    interp = args.interpreter
    if os.sep in interp:
        interp = os.path.abspath(interp)
    else:
        interp = shutil.which(interp) or interp
    report["interpreter_resolved"] = interp
    if not (os.path.isfile(interp) and os.access(interp, os.X_OK)):
        return _fail(report, ["interpreter is not an executable file: %s"
                              % (interp,)])

    workdir = _make_workdir(args.workdir)
    report["workdir"] = workdir

    # Bootstrap environment: keep the caller's loader path just long
    # enough to START the requested interpreter, and nothing else that
    # can steer the run.
    parent_env = dict(os.environ)
    bootstrap_lib = parent_env.get("LD_LIBRARY_PATH", "")
    boot_env, removed = build_child_env(parent_env, bootstrap_lib)
    report["env_audit"] = {"removed": removed}
    interp_info, probe_problems = probe_interpreter(interp, boot_env)
    if probe_problems:
        return _fail(report, probe_problems)
    report["interpreter_info"] = interp_info
    if interp_info["minor"] != args.expect_minor:
        return _fail(report, [
            "interpreter %s is Python %s, expected %s"
            % (interp, interp_info["minor"], args.expect_minor)])
    if args.mode == "udf" and not interp_info.get("shared"):
        return _fail(report, [
            "UDF acceptance requires an interpreter built with a shared "
            "libpython (Py_ENABLE_SHARED); %s is static" % (interp,)])

    # The interpreter's own LIBDIR is the authoritative loader path for
    # every child (Fedora: /usr/lib64; manylinux: <prefix>/lib).
    lib_dir = interp_info.get("libdir") or bootstrap_lib
    child_env, removed2 = build_child_env(parent_env, lib_dir)
    report["env_audit"] = {"removed": sorted(set(removed) | set(removed2)),
                           "lib_dir": lib_dir}

    # --- 2. Inspect the wheel BEFORE installing it --------------------
    inspection, wheel_problems = inspect_wheel(
        wheel, args.expect_minor, args.mode,
        expected_suffix=interp_info.get("suffix"))
    report["wheel_inspection"] = inspection
    if wheel_problems:
        return _fail(report, wheel_problems)
    version = inspection["version"]
    helper_member = inspection.get("helper")

    # --- 3. Clean venv from the REQUESTED interpreter -----------------
    env_dir = os.path.join(workdir, "venv")
    shutil.rmtree(env_dir, ignore_errors=True)
    r = _run([interp, "-m", "venv", env_dir], env=child_env,
             cwd=workdir, timeout=args.timeout)
    if r.returncode != 0:
        return _fail(report, ["venv creation failed: %s"
                              % ((r.stderr or r.stdout)[-800:].strip(),)])
    py = os.path.join(env_dir, "bin", "python")
    if not os.path.exists(py):
        return _fail(report, ["venv did not create bin/python in %s"
                              % (env_dir,)])
    report["venv_python"] = py
    # bin/python is normally a symlink to the base interpreter, so
    # containment in the venv is the wrong test. sys.prefix (below) is
    # what proves the venv is in use, and the requested interpreter's
    # realpath is checked against the running interpreter there.

    # --- 4. Install, offline, with no inherited route selector --------
    r = _run([py, "-m", "pip", "install", "--quiet", "--no-deps",
              "--no-index", "--disable-pip-version-check", wheel],
             env=child_env, cwd=workdir, timeout=args.timeout)
    if r.returncode != 0:
        return _fail(report, ["pip install failed: %s"
                              % ((r.stderr or r.stdout)[-1200:].strip(),)])
    report["pip_install"] = "ok"

    probe_code = (
        "import json, os, sys, sysconfig\n"
        "import forkrun\n"
        "from forkrun._bindings import find_substrate\n"
        "from forkrun import _udf\n"
        "try:\n"
        "    from importlib.metadata import version as _v\n"
        "    meta_version = _v('forkrun')\n"
        "except Exception as exc:\n"
        "    meta_version = None\n"
        "purelib = sysconfig.get_paths()['purelib']\n"
        "helper = _udf.candidate_helper_path()\n"
        "libpython = _udf.caller_libpython_arg()\n"
        "print('PROBE=' + json.dumps({\n"
        "  'purelib': purelib,\n"
        "  'prefix': sys.prefix,\n"
        "  'minor': '%d.%d' % sys.version_info[:2],\n"
        "  'executable': os.path.realpath(sys.executable),\n"
        "  'file': os.path.realpath(forkrun.__file__),\n"
        "  'version': forkrun.__version__,\n"
        "  'engine_version': str(getattr(forkrun, '__engine_version__', '?')),\n"
        "  'metadata_version': meta_version,\n"
        "  'lib': os.path.realpath(find_substrate()),\n"
        "  'helper': os.path.realpath(helper) if helper else None,\n"
        "  'helper_candidate': helper,\n"
        "  'libpython': libpython,\n"
        "  'suffix': sysconfig.get_config_var('EXT_SUFFIX') or '.so',\n"
        "  'isolated': bool(sys.flags.isolated),\n"
        "}))\n"
    )
    r = _run([py, "-c", probe_code], env=child_env, cwd=workdir,
             timeout=args.timeout)
    installed = _last_json("PROBE=", r.stdout)
    if r.returncode != 0 or not installed:
        return _fail(report, ["installed-package probe failed: %s"
                              % ((r.stderr or r.stdout)[-1200:].strip(),)])
    report["installed"] = installed
    purelib = os.path.realpath(installed["purelib"])
    venv_real = os.path.realpath(env_dir)
    if not _inside(purelib, venv_real):
        return _fail(report, ["purelib %s is outside venv %s"
                              % (purelib, venv_real)])
    if os.path.realpath(installed["prefix"]) != venv_real:
        return _fail(report, ["imported package used sys.prefix %s, not "
                              "the venv %s"
                              % (installed["prefix"], venv_real)])
    # The venv's `bin/python` is normally a symlink to the base
    # interpreter, so containment is the wrong test. Identity is the
    # right one: the process actually running the workload must be the
    # interpreter that was requested, at the requested minor.
    if installed.get("minor") != args.expect_minor:
        return _fail(report, [
            "the venv interpreter is Python %r, expected %s"
            % (installed.get("minor"), args.expect_minor)])
    if installed.get("executable") != interp_info.get("executable"):
        return _fail(report, [
            "the venv interpreter resolves to %r, not the requested "
            "interpreter %r" % (installed.get("executable"),
                               interp_info.get("executable"))])
    if installed.get("suffix") != interp_info.get("suffix"):
        return _fail(report, [
            "the venv EXT_SUFFIX %r differs from the requested "
            "interpreter's %r" % (installed.get("suffix"),
                                  interp_info.get("suffix"))])
    expected_init = os.path.join(purelib, "forkrun", "__init__.py")
    expected_lib = os.path.join(purelib, "forkrun",
                                "libforkrun_python.so")
    expected_launcher = os.path.join(purelib, "forkrun",
                                     "_forkrun_cleanroom")
    if installed["file"] != os.path.realpath(expected_init):
        return _fail(report, [
            "provenance failure: forkrun imported from %s, not %s"
            % (installed["file"], expected_init)])
    if installed["lib"] != os.path.realpath(expected_lib):
        return _fail(report, [
            "native-lib provenance failure: substrate resolved to %s, "
            "not %s" % (installed["lib"], expected_lib)])
    if not os.path.isfile(expected_launcher):
        return _fail(report, ["cleanroom launcher is not installed at %s"
                              % (expected_launcher,)])
    installed_launcher = os.path.realpath(expected_launcher)
    if not _inside(installed_launcher, venv_real):
        return _fail(report, ["cleanroom launcher resolves outside venv: %s"
                              % (installed_launcher,)])
    if installed["version"] != version:
        return _fail(report, [
            "imported forkrun.__version__ %r differs from the wheel "
            "filename version %r" % (installed["version"], version)])
    if installed["metadata_version"] != version:
        return _fail(report, [
            "installed distribution metadata version %r differs from the "
            "wheel filename version %r"
            % (installed["metadata_version"], version)])
    if installed["isolated"]:
        return _fail(report, [
            "the caller's interpreter is running isolated; the acceptance "
            "workload would not be representative"])

    # --- 5. UDF-specific runtime shape --------------------------------
    members = list(REQUIRED_MEMBERS)
    if args.mode == "udf":
        expected_helper_name = os.path.basename(helper_member)
        installed_helper = os.path.join(purelib, "forkrun",
                                        expected_helper_name)
        if not os.path.isfile(installed_helper):
            return _fail(report, [
                "UDF helper is not installed at %s" % (installed_helper,)])
        if installed["helper"] != os.path.realpath(installed_helper):
            return _fail(report, [
                "runtime helper resolution points at %r, not the wheel's "
                "installed helper %r"
                % (installed["helper"], os.path.realpath(installed_helper))])
        if os.path.basename(installed_helper) != (
                HELPER_STEM + installed["suffix"]):
            return _fail(report, [
                "installed helper %r does not match the venv EXT_SUFFIX %r"
                % (os.path.basename(installed_helper),
                   installed["suffix"])])
        libpython = installed.get("libpython")
        if (not isinstance(libpython, list) or len(libpython) != 1
                or not libpython[0].startswith("--libpython=")):
            return _fail(report, [
                "the installed package cannot resolve this interpreter's "
                "libpython (%r); the cleanroom UDF route would decline"
                % (libpython,)])
        libpython_path = libpython[0].split("=", 1)[1]
        if not os.path.isfile(libpython_path):
            return _fail(report, [
                "resolved libpython does not exist: %s" % (libpython_path,)])
        members.append(helper_member)
        report["udf_route"] = {
            "helper": os.path.realpath(installed_helper),
            "libpython": os.path.realpath(libpython_path),
            "ext_suffix": installed["suffix"],
        }
    else:
        if installed.get("helper") is not None:
            return _fail(report, [
                "generic wheel installed a UDF helper (%r); its wheel must "
                "carry none" % (installed.get("helper"),)])
        stray = [n for n in os.listdir(os.path.join(purelib, "forkrun"))
                 if n.startswith(HELPER_STEM)]
        if stray:
            return _fail(report, ["generic install contains helper "
                                  "artifacts: %r" % (stray,)])

    # --- 6. SHA-256 provenance for every required member --------------
    evidence, prov_problems = verify_installed_files(wheel, purelib, members)
    report["provenance"] = evidence
    if prov_problems:
        return _fail(report, prov_problems)

    # --- 7. Real workload ---------------------------------------------
    inp = os.path.join(workdir, "input.txt")
    with open(inp, "w", encoding="utf-8", newline="\n") as fh:
        for i in range(4000):
            fh.write("line %d\n" % i)
    with open(inp, "rb") as fh:
        input_bytes = fh.read()
    expected_generic = input_bytes

    if args.mode == "generic":
        expected = expected_generic
        driver = os.path.join(workdir, "driver_generic.py")
        template = r'''import hashlib, json, os, sys
import forkrun
INP = @INP@
EXPECTED = @EXPECTED@
def f(batch):
    return bytes(batch.data)
out = list(forkrun.map(f, INP, workers=2, order="index"))
joined = b"".join(bytes(x) for x in out)
expected = open(EXPECTED, "rb").read()
report = {
    "bytes": len(joined),
    "sha256": hashlib.sha256(joined).hexdigest(),
    "exists": os.path.exists(INP),
    "forkrun_file": os.path.realpath(forkrun.__file__),
}
print("GENERIC_REPORT=" + json.dumps(report))
sys.exit(0 if joined == expected else 3)
'''
        _write(driver, template.replace("@INP@", json.dumps(inp))
               .replace("@EXPECTED@", json.dumps(inp)))
        r = _run([py, driver], env=child_env, cwd=workdir,
                 timeout=args.timeout)
        wl = _last_json("GENERIC_REPORT=", r.stdout)
        report["workload"] = wl or {"stdout": r.stdout[-2000:],
                                    "stderr": r.stderr[-2000:]}
        if r.returncode != 0:
            return _fail(report, [
                "generic workload exited %d: %s"
                % (r.returncode, (r.stderr or r.stdout)[-1200:].strip())])
        gp = evaluate_generic_report(wl, len(expected),
                                     _sha256_bytes(expected))
        if gp:
            return _fail(report, gp)
        report["workload_evidence"] = (
            "map() over a file returned byte-exact input (%d bytes)"
            % (len(expected),))
        report["result"] = "PASS"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    # UDF mode.
    expected = input_bytes.upper()
    expected_sha = _sha256_bytes(expected)
    nonce = secrets.token_hex(16)
    module, attr = udf_spec
    marker = os.path.join(workdir, "udf_markers.jsonl")
    for stale in (marker,):
        try:
            os.unlink(stale)
        except FileNotFoundError:
            pass
    udf_path = os.path.join(workdir, module + ".py")
    if not _inside(os.path.realpath(udf_path), os.path.realpath(workdir)):
        return _fail(report, ["UDF module would escape the workdir: %r"
                              % (udf_path,)])
    udf_src = '''import json as _json
import os as _os
import sys as _sys

_MARKER = @MARKER@
_NONCE = @NONCE@


def @ATTR@(batch):
    record = {
        "pid": _os.getpid(),
        "isolated": bool(_sys.flags.isolated),
        "version": "%d.%d" % _sys.version_info[:2],
        "nonce": _NONCE,
    }
    fd = _os.open(_MARKER, _os.O_WRONLY | _os.O_CREAT | _os.O_APPEND, 0o600)
    try:
        _os.write(fd, (_json.dumps(record, sort_keys=True) + "\\n").encode("ascii"))
    finally:
        _os.close(fd)
    return batch.upper()
'''
    udf_src = (udf_src.replace("@MARKER@", json.dumps(marker))
               .replace("@NONCE@", json.dumps(nonce))
               .replace("@ATTR@", attr))
    _write(udf_path, udf_src)

    spec = "%s:%s" % (module, attr)
    driver = os.path.join(workdir, "driver_udf.py")
    template = r'''import hashlib, json, os, sys
sys.path.insert(0, @WORKDIR@)
import forkrun
SPEC = @SPEC@
INP = @INP@
EXPECTED = @EXPECTED@
MARKER = @MARKER@
try:
    os.unlink(MARKER)
except FileNotFoundError:
    pass
parent_pid = os.getpid()
out = list(forkrun.map(SPEC, INP, workers=2, mode="udf", order="index"))
joined = b"".join(bytes(x) for x in out)
expected = open(EXPECTED, "rb").read()
markers = []
try:
    with open(MARKER, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                markers.append(json.loads(line))
except FileNotFoundError:
    pass
candidate = None
try:
    from forkrun import _udf
    candidate = _udf.candidate_helper_path()
except Exception:
    pass
report = {
    "bytes": len(joined),
    "sha256": hashlib.sha256(joined).hexdigest(),
    "parent_pid": parent_pid,
    "markers": markers,
    "helper": os.path.realpath(candidate) if candidate else None,
    "cleanroom_env": os.environ.get("FORKRUN_CLEANROOM"),
    "forkrun_file": os.path.realpath(forkrun.__file__),
}
print("UDF_REPORT=" + json.dumps(report))
sys.exit(0 if joined == expected else 3)
'''
    driver_src = (template
                  .replace("@WORKDIR@", json.dumps(workdir))
                  .replace("@SPEC@", json.dumps(spec))
                  .replace("@INP@", json.dumps(inp))
                  .replace("@EXPECTED@", json.dumps(inp + ".expected"))
                  .replace("@MARKER@", json.dumps(marker)))
    _write(driver, driver_src)
    with open(inp + ".expected", "wb") as fh:
        fh.write(expected)

    udf_env = dict(child_env)
    udf_env["FORKRUN_CLEANROOM"] = "map-udf"
    driver_pid, r = _run_with_pid([py, driver], env=udf_env, cwd=workdir,
                                  timeout=args.timeout)
    wl = _last_json("UDF_REPORT=", r.stdout)
    report["workload"] = wl or {"stdout": r.stdout[-2000:],
                                "stderr": r.stderr[-2000:]}
    report["marker_nonce"] = nonce
    report["driver_pid"] = driver_pid
    if r.returncode != 0:
        return _fail(report, [
            "UDF workload exited %d: %s"
            % (r.returncode, (r.stderr or r.stdout)[-1600:].strip())])
    up = evaluate_udf_report(
        wl, expect_minor=args.expect_minor,
        expected_bytes=len(expected), expected_sha256=expected_sha,
        parent_pid=driver_pid, nonce=nonce)
    if up:
        return _fail(report, up)
    if wl.get("helper") != report["udf_route"]["helper"]:
        return _fail(report, [
            "the workload resolved helper %r, not the installed helper %r"
            % (wl.get("helper"), report["udf_route"]["helper"])])
    helper_pids = sorted({m["pid"] for m in wl["markers"]})
    report["workload_evidence"] = (
        "UDF ran in %d helper process(es) [%s] over %d invocation(s), "
        "isolated=True, Python %s, byte-exact %d bytes"
        % (len(helper_pids), ", ".join(str(p) for p in helper_pids),
           len(wl["markers"]), args.expect_minor, len(expected)))
    report["result"] = "PASS"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
