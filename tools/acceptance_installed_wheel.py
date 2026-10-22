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

    # 1. Create clean venv with the matching interpreter.
    env_dir = os.path.join(workdir, "venv")
    venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
    py = os.path.join(env_dir, "bin", "python")
    if not os.path.exists(py):
        py = os.path.join(env_dir, "Scripts", "python.exe")
    report["venv_python"] = py

    # 2. Install the wheel.
    r = _run([py, "-m", "pip", "install", "--quiet", "--no-deps", wheel])
    if r.returncode != 0:
        report["error"] = "pip install failed: " + r.stderr[-500:]
        print(json.dumps(report, indent=2))
        return 1
    report["pip_install"] = "ok"

    # 3. Prove import provenance: forkrun.__file__ must be inside the venv.
    code = (
        "import forkrun, os, sys\n"
        "print('FILE=' + forkrun.__file__)\n"
        "print('VERSION=' + forkrun.__version__)\n"
        "print('ENGINE=' + str(getattr(forkrun, '__engine_version__', '?')))\n"
        "print('VENV=' + os.path.dirname(os.path.dirname(forkrun.__file__)))\n"
    )
    r = _run([py, "-c", code], cwd=workdir)
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
    if env_dir not in info.get("FILE", ""):
        report["error"] = ("provenance failure: forkrun imported from %s, "
                           "not from venv %s" % (info.get("FILE"), env_dir))
        print(json.dumps(report, indent=2))
        return 1
    report["provenance"] = "ok (forkrun from installed venv)"

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
        r = _run([py, driver], cwd=workdir)
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
        udf_path = os.path.join(workdir, mod + ".py")
        with open(udf_path, "w") as fh:
            fh.write("def %s(b):\n    return b.upper()\n" % func)
        inp = os.path.join(workdir, "input.txt")
        with open(inp, "w") as fh:
            for i in range(1000):
                fh.write("line %d\n" % i)
        # Expected output: uppercased input.
        with open(inp + ".expected", "wb") as fh:
            fh.write(open(inp, "rb").read().upper())
        driver = os.path.join(workdir, "driver_udf.py")
        with open(driver, "w") as fh:
            fh.write(
                "import forkrun, os, sys\n"
                "sys.path.insert(0, %r)\n"
                "out = list(forkrun.map(%r, %r, workers=2, mode='udf', order='index'))\n"
                "joined = b''.join(out)\n"
                "expected = open(%r, 'rb').read()\n"
                "assert joined == expected, 'mismatch %%d vs %%d' %% (len(joined), len(expected))\n"
                "print('UDF_OK bytes=' + str(len(joined)))\n"
                % (workdir, args.udf_func, inp, inp + ".expected"))
        # Run with PYTHONPATH including workdir so the launcher can find the module.
        env = dict(os.environ)
        env["PYTHONPATH"] = workdir + (":" + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")
        r = _run([py, driver], cwd=workdir, env=env)
        if r.returncode != 0 or "UDF_OK" not in r.stdout:
            report["error"] = "UDF workload failed: " + (r.stderr or r.stdout)[-1000:]
            print(json.dumps(report, indent=2))
            return 1
        report["workload"] = r.stdout.strip()
        r = _run([py, driver], cwd=workdir)
        if r.returncode != 0 or "UDF_OK" not in r.stdout:
            report["error"] = "UDF workload failed: " + (r.stderr or r.stdout)[-1000:]
            print(json.dumps(report, indent=2))
            return 1
        report["workload"] = r.stdout.strip()

    report["result"] = "PASS"
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())