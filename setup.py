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
import platform
import re
import shutil
import subprocess

from setuptools import setup
from setuptools.command.build_py import build_py

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.join(REPO_ROOT, "python", "forkrun")
SO_NAME = "libforkrun_python.so"


def get_platform_tag():
    """W-PY23: correct platform tag for the wheel (fail-fast off-Linux).

    The wheel carries a compiled .so (ctypes-loaded, so any Python 3
    works — only the platform matters). A py3-none-any tag would let
    pip install it on ARM/macOS where the .so cannot load; the
    platform tag makes that a clean refusal instead.
    """
    system = platform.system()
    if system != "Linux":
        raise RuntimeError(
            "forkrun requires Linux (got %s). The C substrate uses "
            "Linux-specific syscalls (memfd_create, splice, "
            "fallocate)." % system)
    machine = platform.machine()
    if machine == "x86_64":
        return "linux_x86_64"
    if machine == "aarch64":
        return "linux_aarch64"
    raise RuntimeError(
        "unsupported architecture %r (supported: x86_64, aarch64)"
        % machine)


PLATFORM_TAG = get_platform_tag()


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
            # inspection; prefer make whenever available). Mirrors the
            # W-PY23 reproducibility flags too (prefix map, pinned
            # __DATE__/__TIME__, no build-id).
            self.announce("make not found; using fallback gcc invocation")
            if shutil.which("gcc") is None:
                raise RuntimeError(
                    "need gcc (or make) to build the C substrate")
            cc = ["gcc", "-O1", "-fPIC", "-Wall", "-Wextra",
                  "-ffile-prefix-map=" + REPO_ROOT + "=.",
                  "-Wno-builtin-macro-redefined",
                  '-D__DATE__="Sep  1 2026"', '-D__TIME__="00:00:00"',
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
                 "-Wl,--no-undefined", "-Wl,--build-id=none",
                 "-ldl", "-lrt"],
                check=True, cwd=REPO_ROOT)
        if not os.path.exists(so_path):
            raise RuntimeError("substrate build produced no %s" % SO_NAME)


def read_readme():
    with open(os.path.join(REPO_ROOT, "python", "README.md")) as fh:
        return fh.read()


setup(
    name="forkrun",
    version=read_version(),
    description="NUMA-aware contention-free streaming parallelization for Python",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    license="MIT",
    author="forkrun contributors",
    author_email="",  # Set by the maintainer before `twine upload`.
    url="https://github.com/jkool702/forkrun",
    project_urls={
        "Source": "https://github.com/jkool702/forkrun",
        "Documentation": "https://github.com/jkool702/forkrun/tree/main/DOCS",
        "Bug Tracker": "https://github.com/jkool702/forkrun/issues",
        "Benchmarks": "https://github.com/jkool702/forkrun/tree/main/python/benchmarks",
    },
    keywords=[
        "parallel", "parallelization", "streaming", "NUMA",
        "high-performance", "data-processing", "fork",
        "multiprocessing", "concurrent", "pipeline",
    ],
    package_dir={"": "python"},
    packages=["forkrun"],
    package_data={"forkrun": [SO_NAME]},
    cmdclass={"build_py": BuildSubstratePy},
    # The wheel carries a compiled .so: tag it for this platform so
    # pip refuses it elsewhere (never py3-none-any).
    options={"bdist_wheel": {"plat_name": PLATFORM_TAG}},
    python_requires=">=3.8",
    install_requires=[],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: C",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Distributed Computing",
        "Topic :: System :: Parallel Processing",
        "Topic :: Scientific/Engineering",
        "Topic :: Utilities",
    ],
)
