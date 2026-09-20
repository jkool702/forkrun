#!/usr/bin/env python3
"""forkrun packaging (W-PY10). `pip install .` / `pip wheel . --no-deps`.

Layout note: the package lives at python/forkrun/ (NOT src/ — moving a
dozen library files plus every test/Makefile/CI/docs path reference is
churn without function). package_dir={"": "python"} maps it to the
top-level `forkrun` wheel package; python/tests/ has no __init__.py so
tests never ship.

Version single-sources from python/forkrun/__init__.py (__version__).
The build_py step compiles libforkrun_python.so FIRST (via
Makefile.substrate — the single source of compiler flags), then lets
setuptools copy it as package_data. No PyPI upload happens here.
"""

import os
import re
import shutil
import subprocess

from setuptools import setup
from setuptools.command.build_py import build_py

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.join(REPO_ROOT, "python", "forkrun")
SO_NAME = "libforkrun_python.so"


def read_version():
    with open(os.path.join(PKG_DIR, "__init__.py")) as fh:
        src = fh.read()
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', src, re.M)
    if not m:
        raise RuntimeError("could not find __version__ in __init__.py")
    return m.group(1)


class BuildSubstratePy(build_py):
    """Compile the C substrate, then run the normal purelib copy."""

    def run(self):
        self._build_substrate()
        super().run()

    def _build_substrate(self):
        so_path = os.path.join(PKG_DIR, SO_NAME)
        makefile = os.path.join(REPO_ROOT, "Makefile.substrate")
        if shutil.which("make") is not None:
            # Single source of flags: the same target CI/docs use.
            cmd = ["make", "-f", makefile, "python-substrate",
                   "PY_OUT=" + os.path.join("python", "forkrun", SO_NAME)]
            self.announce("building substrate: %s" % " ".join(cmd))
            try:
                subprocess.run(cmd, check=True, cwd=REPO_ROOT)
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    "substrate build failed (need gcc + bash headers; "
                    "Fedora: dnf install -y gcc make bash-devel): %s"
                    % exc) from exc
        else:
            # Fallback mirror of the Makefile recipe (kept in sync by
            # inspection; prefer make whenever available).
            self.announce("make not found; using fallback gcc invocation")
            if shutil.which("gcc") is None:
                raise RuntimeError(
                    "need gcc (or make) to build the C substrate")
            cc = ["gcc", "-O1", "-fPIC", "-Wall", "-Wextra",
                  "-DSHELL", "-DHAVE_CONFIG_H",
                  "-I/usr/include/bash",
                  "-I/usr/include/bash/include",
                  "-I/usr/include/bash/builtins"]
            obj = os.path.join(REPO_ROOT, "forkrun_python_shim.o")
            subprocess.run(
                cc + ["-c", os.path.join("python", "forkrun", "_shim.c"),
                      "-o", obj], check=True, cwd=REPO_ROOT)
            stub = os.path.join(REPO_ROOT, "substratestubs.o")
            subprocess.run(
                cc + ["-c", "substratestubs.c", "-o", stub],
                check=True, cwd=REPO_ROOT)
            subprocess.run(
                ["gcc", "-shared", "-o", so_path, obj, stub,
                 "-Wl,--no-undefined", "-ldl", "-lrt"],
                check=True, cwd=REPO_ROOT)
        if not os.path.exists(so_path):
            raise RuntimeError("substrate build produced no %s" % SO_NAME)


setup(
    name="forkrun",
    version=read_version(),
    description="NUMA-aware contention-free streaming parallelization",
    long_description=(
        "forkrun is a self-tuning parallelizer: fault-tolerant,"
        " zero-copy streaming over a coordinate plane, with Python"
        " (this package), spawn, and C-plugin frontends. Linux-only."
    ),
    license="MIT",
    author="forkrun contributors",
    url="https://github.com/jkool702/forkrun",
    package_dir={"": "python"},
    packages=["forkrun"],
    package_data={"forkrun": [SO_NAME]},
    cmdclass={"build_py": BuildSubstratePy},
    python_requires=">=3.8",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: C",
        "Programming Language :: Python :: 3",
        "Topic :: System :: Distributed Computing",
    ],
)
