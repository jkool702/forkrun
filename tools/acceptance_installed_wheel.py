#!/usr/bin/env python3
"""Installed-wheel acceptance test (WO-COMPAT-04A Lane B / WO-COMPAT-05A Lane C).

Proves that the Python package actually imported is the one installed in the
target virtual environment, and runs a real forkrun workload through it.

Usage:
    python3 tools/acceptance_installed_wheel.py \\
        --wheel dist/forkrun-...-manylinux_2_28_x86_64.whl \\
        --interpreter /opt/python/cp310-cp310/bin/python3.10 \\
        --mode generic|udf \\
        [--udf-func MODULE:FUNC]   # required for mode=udf
        [--helper-expected]        # require a UDF helper to be present

Exits 0 on success, non-zero on any failure. Prints a JSON-ish report.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wheel", required=True)
    ap.add_argument("--interpreter", required=True)
    ap.add_argument("--mode", choices=("generic", "udf"), required=True)
    ap.add_argument("--udf-func", default=None,
                    help="MODULE:FUNC importable from the workdir for UDF mode")
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args(argv)

    wheel = os.path.abspath(args.wheel)
    interp = args.interpreter
    workdir = args.workdir or tempfile.mkdtemp(prefix="fr_accept_")
    os.makedirs(workdir, exist_ok=True)

    report = {"wheel": wheel, "interpreter": interp, "mode": args.mode,
              "workdir": workdir}

    # 1. Create clean venv WITH THE REQUESTED INTERPRETER (not the
    # interpreter running this script). Use subprocess so the venv's
    # Python minor is exactly the one requested.
    env_dir = os.path.join(workdir, "venv")
    if os.path.exists(env_dir):
        import shutil
        shutil.rmtree(env_dir)
    r = _run([interp, "-m", "venv", env_dir])
    if r.returncode != 0:
        report["error"] = "venv creation failed: " + r.stderr[-500:]
        print(json.dumps(report, indent=2))
        return 1
    py = os.path.join(env_dir, "bin", "python")
    if not os.path.exists(py):
        py = os.path.join(env_dir, "Scripts", "python.exe")
    report["venv_python"] = py
    # Assert the venv's minor matches the requested interpreter.
    r = _run([py, "-c",
              "import sys; print('%d.%d' % sys.version_info[:2])"])
    actual_minor = r.stdout.strip()
    requested_minor = subprocess.run(
        [interp, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
        capture_output=True, text=True).stdout.strip()
    report["requested_interpreter_minor"] = requested_minor
    report["actual_venv_minor"] = actual_minor
    if actual_minor != requested_minor:
        report["error"] = ("interpreter mismatch: requested %s, venv is %s"
                           % (requested_minor, actual_minor))
        print(json.dumps(report, indent=2))
        return 1

    # 2. Install the wheel.
    r = _run([py, "-m", "pip", "install", "--quiet", "--no-deps", wheel])
    if r.returncode != 0:
        report["error"] = "pip install failed: " + r.stderr[-500:]
        print(json.dumps(report, indent=2))
        return 1
    report["pip_install"] = "ok"

    # 3. Prove import provenance: forkrun.__file__ must be inside the venv.
    # Clear FORKRUN_LIB so the resolver must use the installed library.
    clean_env = dict(os.environ)
    clean_env.pop("FORKRUN_LIB", None)
    clean_env.pop("FORKRUN_CLEANROOM", None)
    code = (
        "import forkrun, os, sys\n"
        "from forkrun._bindings import find_substrate\n"
        "lib = find_substrate()\n"
        "print('FILE=' + os.path.realpath(forkrun.__file__))\n"
        "print('VERSION=' + forkrun.__version__)\n"
        "print('ENGINE=' + str(getattr(forkrun, '__engine_version__', '?')))\n"
        "print('LIB=' + os.path.realpath(lib))\n"
        "print('VENV=' + os.path.realpath(os.path.dirname(os.path.dirname(forkrun.__file__))))\n"
    )
    r = _run([py, "-c", code], cwd=workdir, env=clean_env)
    if r.returncode != 0:
        report["error"] = "import failed: " + r.stderr[-500:]
        print(json.dumps(report, indent=2))
        return 1
    info = {}
    for line in r.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k] = v
    report["import"] = info
    env_real = os.path.realpath(env_dir)
    file_real = os.path.realpath(info.get("FILE", ""))
    lib_real = os.path.realpath(info.get("LIB", ""))
    # Exact containment via commonpath, not substring.
    def _inside(child, parent):
        try:
            return os.path.commonpath([child, parent]) == parent
        except ValueError:
            return False
    if not _inside(file_real, env_real):
        report["error"] = ("provenance failure: forkrun imported from %s, "
                           "not inside venv %s" % (file_real, env_real))
        print(json.dumps(report, indent=2))
        return 1
    if not _inside(lib_real, env_real):
        report["error"] = ("native-lib provenance failure: lib resolved to %s, "
                           "not inside venv %s" % (lib_real, env_real))
        print(json.dumps(report, indent=2))
        return 1
    # Helper provenance for UDF mode.
    if args.mode == "udf":
        helpers = [os.path.realpath(os.path.join(os.path.dirname(file_real), h))
                    for h in os.listdir(os.path.dirname(file_real))
                    if h.startswith("_fr_udf")]
        report["helpers_resolved"] = helpers
        if not helpers:
            report["error"] = "no UDF helper found in installed package"
            print(json.dumps(report, indent=2))
            return 1
        for h in helpers:
            if not _inside(h, env_real):
                report["error"] = ("helper provenance failure: %s not inside venv %s"
                                   % (h, env_real))
                print(json.dumps(report, indent=2))
                return 1
        # suffix check: helper must match the venv interpreter's EXT_SUFFIX
        r2 = _run([py, "-c",
                   "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or '.so')"],
                  env=clean_env)
        venv_suffix = r2.stdout.strip()
        if not venv_suffix or r2.returncode != 0:
            report["error"] = "could not determine venv EXT_SUFFIX"
            print(json.dumps(report, indent=2))
            return 1
        for h in helpers:
            if not os.path.basename(h).endswith(venv_suffix):
                report["error"] = ("helper suffix mismatch: %s does not end with %s"
                                   % (os.path.basename(h), venv_suffix))
                print(json.dumps(report, indent=2))
                return 1
        report["venv_ext_suffix"] = venv_suffix
        report["helper_check"] = "ok (helper suffix %s inside venv: %r)"
        report["helper_check"] = report["helper_check"] % (venv_suffix, helpers)
    report["provenance"] = ("ok (forkrun=%s, lib=%s)"
                            % (info.get("FILE"), info.get("LIB")))

    # 4. Check helper presence according to mode.
    pkg_dir = os.path.dirname(info["FILE"])
    helpers = sorted(n for n in os.listdir(pkg_dir) if n.startswith("_fr_udf"))
    report["helpers"] = helpers
    if args.mode == "generic":
        if helpers:
            report["error"] = ("generic wheel must not ship a UDF helper, "
                               "but found: %r" % helpers)
            print(json.dumps(report, indent=2))
            return 1
        report["helper_check"] = "ok (no helper, as expected for generic)"
    else:
        if not helpers:
            report["error"] = "UDF wheel ships no helper"
            print(json.dumps(report, indent=2))
            return 1
        report["helper_check"] = "ok (helper present: %r)" % helpers

    # 5. Run a real workload.
    if args.mode == "generic":
        # Representative generic workload: map identity over a file.
        inp = os.path.join(workdir, "input.txt")
        with open(inp, "w") as fh:
            for i in range(1000):
                fh.write("line %d\n" % i)
        driver = os.path.join(workdir, "driver_generic.py")
        with open(driver, "w") as fh:
            fh.write(
                "import forkrun, os\n"
                "def f(b): return bytes(b.data)\n"
                "out = list(forkrun.map(f, %r, workers=2, order='index'))\n"
                "joined = b''.join(out)\n"
                "expected = open(%r, 'rb').read()\n"
                "assert joined == expected, 'mismatch %%d vs %%d' %% (len(joined), len(expected))\n"
                "print('GENERIC_OK bytes=' + str(len(joined)))\n"
                % (inp, inp))
        generic_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", workdir),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        r = _run([py, driver], cwd=workdir, env=generic_env)
        if r.returncode != 0 or "GENERIC_OK" not in r.stdout:
            report["error"] = "generic workload failed: " + (r.stderr or r.stdout)[-500:]
            print(json.dumps(report, indent=2))
            return 1
        report["workload"] = r.stdout.strip()
    else:
        # UDF mode: requires --udf-func.
        if not args.udf_func:
            report["error"] = "--udf-func required for mode=udf"
            print(json.dumps(report, indent=2))
            return 1
        mod, func = args.udf_func.split(":", 1)
        # Create the UDF module in the workdir (the launcher scans sys.path).
        marker = os.path.join(workdir, "udf_pid.txt")
        isolated_marker = os.path.join(workdir, "udf_isolated.txt")
        version_marker = os.path.join(workdir, "udf_version.txt")
        udf_path = os.path.join(workdir, mod + ".py")
        with open(udf_path, "w") as fh:
            fh.write(
                "import os as _os, sys as _sys\n"
                "def %s(b):\n"
                "    with open(%r, 'w') as _f:\n"
                "        _f.write(str(_os.getpid()))\n"
                "    with open(%r, 'w') as _f:\n"
                "        _f.write(str(bool(_sys.flags.isolated)))\n"
                "    with open(%r, 'w') as _f:\n"
                "        _f.write('%%d.%%d' %% _sys.version_info[:2])\n"
                "    return b.upper()\n" % (func, marker, isolated_marker, version_marker))
        inp = os.path.join(workdir, "input.txt")
        with open(inp, "w") as fh:
            for i in range(1000):
                fh.write("line %d\n" % i)
        with open(inp + ".expected", "wb") as fh:
            fh.write(open(inp, "rb").read().upper())
        driver = os.path.join(workdir, "driver_udf.py")
        with open(driver, "w") as fh:
            fh.write(
                "import forkrun, os, sys\n"
                "sys.path.insert(0, %r)\n"
                "parent_pid = os.getpid()\n"
                "out = list(forkrun.map(%r, %r, workers=2, mode='udf', order='index'))\n"
                "joined = b''.join(out)\n"
                "expected = open(%r, 'rb').read()\n"
                "assert joined == expected, 'mismatch %%d vs %%d' %% (len(joined), len(expected))\n"
                "helper_pid = int(open(%r).read().strip())\n"
                "isolated = open(%r).read().strip()\n"
                "udf_version = open(%r).read().strip()\n"
                "assert helper_pid != parent_pid, 'helper did not run in a separate process (helper_pid == parent_pid == %%d)' %% parent_pid\n"
                "assert isolated == 'True', 'UDF did not run under isolated interpreter (got %%r); possible fallback to in-process Python' %% isolated\n"
                "assert udf_version == '%s', 'UDF ran under wrong Python (%%s vs %s)' %% udf_version\n"
                "print('UDF_OK bytes=' + str(len(joined)) + ' helper_pid=' + str(helper_pid) + ' parent_pid=' + str(parent_pid) + ' isolated=' + isolated + ' version=' + udf_version)\n"
                % (workdir, args.udf_func, inp, inp + ".expected", marker, isolated_marker, version_marker, actual_minor, actual_minor))
        # Controlled environment: only the workdir on PYTHONPATH, no
        # inherited PYTHONPATH/LD_* overrides.
        # The helper needs libpython at runtime (provided by the Python
        # install). In a normal consumer environment libpython is on the
        # default linker path; in the manylinux test container it lives
        # beside the interpreter, so add that directory explicitly rather
        # than inheriting an ambient LD_LIBRARY_PATH.
        interp_lib = os.path.join(os.path.dirname(os.path.dirname(interp)),
                                  "lib")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", workdir),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONPATH": workdir,
            "FORKRUN_CLEANROOM": "map-udf",
            "LD_LIBRARY_PATH": interp_lib,
        }
        r = _run([py, driver], cwd=workdir, env=env)
        if r.returncode != 0 or "UDF_OK" not in r.stdout:
            report["error"] = "UDF workload failed: " + (r.stderr or r.stdout)[-1000:]
            print(json.dumps(report, indent=2))
            return 1
        report["workload"] = r.stdout.strip()
        report["route_evidence"] = "helper ran in separate process (helper_pid != parent_pid)"

    report["result"] = "PASS"
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())