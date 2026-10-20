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
from setuptools.command.bdist_wheel import bdist_wheel as _bdist_wheel
from setuptools.command.build_py import build_py

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.join(REPO_ROOT, "python", "forkrun")
SO_NAME = "libforkrun_python.so"
# CR-FIX1-I: the cleanroom launcher. Sits beside the substrate .so;
# forkrun.run._cleanroom_launcher_path() looks for exactly this name in
# exactly this directory, and nothing used to ship it.
CR_NAME = "_forkrun_cleanroom"

# W-EXP-1 (DECISION-01 5.4 / 6.2.1): the UDF helper is a SEPARATE,
# CPython-LINKED artifact. Two rules follow, and they are one rule:
#
#   * A wheel that SHIPS the helper must not claim a generic `py3` tag.
#     The helper links libpython3.X, so the wheel is valid only for the
#     minor it was built against. DECISION-01 6.2.1: "a wheel built from
#     an sdist on one machine and tagged py3-none would carry a
#     different minor than its tag claims, with nothing in the artifact
#     to prove it."
#   * A wheel with NO helper stays `py3-none-<platform>`, and the
#     substrate remains interpreter-agnostic. "Keep the source-only
#     development path honest: do not advertise a locally built helper
#     as present in a generic ABI-independent wheel."
#
# The tag follows the HELPER, not the running interpreter. The helper's
# extension suffix ENCODES the minor it was compiled against
# (_fr_udf.cpython-314-x86_64-linux-gnu.so -> 3.14), so a helper built
# for a different minor has a different NAME and is simply not found
# here -- which is the property that makes this safe: a mismatched build
# cannot produce a wheel that claims the wrong minor.
#
# A plain `_fr_udf.so` (no suffix) is deliberately NOT shipped: its
# minor cannot be established from its name. The runtime fallback in
# forkrun/_udf.py still finds it in a SOURCE CHECKOUT, so the
# development path keeps working -- it is only the WHEEL that declines
# to vouch for it.
def _freethreaded_interpreter():
    """Is THIS interpreter a free-threaded (no-GIL) CPython build?

    Two independent signals, because either alone could be absent:
    `Py_GIL_DISABLED` in the build config (3.13+), and the `t` in the
    extension suffix (`cpython-314t-...`).

    WHY THIS MATTERS. A free-threaded CPython links
    `libpython3.14t.so.1.0`; a GIL one links `libpython3.14.so.1.0`.
    Different sonames, so the helper built for one cannot be loaded by
    the other -- and a wheel tagged `cp314` (which does not distinguish
    them) would be offered to both.
    """
    import sysconfig
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        return True
    suffix = sysconfig.get_config_var("EXT_SUFFIX") or ""
    minor = "%d%d" % sys.version_info[:2]
    return ("cpython-%st-" % minor) in suffix


def _udf_helper_for_this_interpreter(pkg_dir=None, suffix=None):
    """The UDF helper built for THIS interpreter, or None.

    None means: ship no helper, and keep the generic `py3-none` tag.

    `pkg_dir` is the package directory to look in; it defaults to the
    real one. It is a parameter so the RULE can be tested directly
    (which minor a helper was built for, and what may ship) without
    needing a second interpreter on the box. `suffix` is likewise a
    parameter, for the same reason.
    """
    import sys
    import sysconfig
    if pkg_dir is None:
        pkg_dir = PKG_DIR
    if suffix is None:
        suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
    # FREE-THREADED CPython IS NOT SUPPORTED for this helper route, so
    # a free-threaded build ships no helper at all. The reasons are
    # structural, not caution: the helper links libpython3.X and the
    # free-threaded build links libpython3.Xt -- different sonames, so
    # the artifacts are mutually load-incompatible; the C0.5 matrix
    # fetches GIL interpreters only, so there is no measured evidence
    # for the free-threaded path; and the launcher has never been
    # exercised against one. Shipping it would be shipping an UNMEASUREED
    # configuration, so the wheel declines to claim it.
    minor = "%d%d" % sys.version_info[:2]
    if ("cpython-%st-" % minor) in suffix:
        return None
    if sysconfig.get_config_var("Py_GIL_DISABLED"):
        return None
    name = "_fr_udf" + suffix
    if not os.path.exists(os.path.join(pkg_dir, name)):
        return None
    # The suffix must carry THIS interpreter's minor. It normally does
    # (cpython-314 for 3.14), and if it does not, the helper was built
    # for something else and must not ship under this interpreter's tag.
    if ("cpython-%s" % minor) not in suffix:
        return None
    return name


UDF_HELPER = _udf_helper_for_this_interpreter()
# The wheel's python AND abi tags. cp3XX when the helper ships; None
# (so setuptools keeps py3-none) when it does not. Never `py3` with a
# CPython-linked helper inside, and never `none` as the ABI of a wheel
# that carries one -- "none" means "no ABI constraint", and a
# free-threaded CPython 3.14 accepts `cp314-none-<platform>` exactly as
# a GIL 3.14 does.
WHEEL_PYTHON_TAG = None
WHEEL_ABI_TAG = None
if UDF_HELPER:
    import sys as _sys
    WHEEL_PYTHON_TAG = "cp%d%d" % _sys.version_info[:2]
    WHEEL_ABI_TAG = WHEEL_PYTHON_TAG


class BdistWheel(_bdist_wheel):
    """bdist_wheel that emits the REAL ABI tag, not "none".

    This project ships its binaries as package_data rather than as C
    extension modules, so setuptools considers the distribution PURE and
    bdist_wheel emits the ABI tag "none". "none" means "no ABI
    constraint" -- and a free-threaded CPython 3.14 accepts
    "cp314-none-<platform>" just as a GIL 3.14 does. So a GIL-built
    helper in a "none"-ABI wheel advertises compatibility with a
    free-threaded interpreter that cannot load it.

    Emitting the real ABI ("cp314") makes the wheel's compatibility set
    exactly the interpreters that can actually use the helper: the GIL
    build, and not the free-threaded one (whose tag set contains
    cp314-cp314t and cp314-abi3t, but not cp314-cp314).
    """

    def get_tag(self):
        if UDF_HELPER and WHEEL_ABI_TAG:
            plat = self.plat_name or "any"
            return (WHEEL_PYTHON_TAG, WHEEL_ABI_TAG, plat)
        return super().get_tag()

# W-PY23/REL: PEP 600 manylinux policy floors, oldest first. A wheel
# built against glibc G may claim the highest policy floor <= G:
# claiming a floor ABOVE the symbols the binary actually needs is
# merely conservative (a glibc-F host still runs it); claiming one
# BELOW them is a lie that pip cannot detect but the loader can.
#
# The build host's glibc is the ceiling, NOT the floor: building on
# Fedora (glibc 2.43) yields a binary needing 2.38 (see __isoc23_*
# below), so 2_39 is the honest tag there. Building inside the
# manylinux_2_28 image yields 2_28. tools/build_wheel.sh does the
# latter and lets auditwheel confirm.
_MANYLINUX_POLICIES = ((2, 5), (2, 12), (2, 17), (2, 28), (2, 31),
                       (2, 34), (2, 35), (2, 39))


def _glibc_version():
    """(major, minor) of the build host's glibc; None on musl/other libc.

    os.confstr is the only reliable probe: platform.libc_ver() returns
    ("", "") for glibc under CPython. A musl host returns None here and
    is rejected below — musl needs a musllinux tag, which we do not
    build (forkrun's engine is glibc-tuned).
    """
    try:
        confstr = os.confstr("CS_GNU_LIBC_VERSION")
    except (AttributeError, ValueError, OSError):
        return None
    if not confstr:
        return None
    m = re.search(r"(\d+)\.(\d+)", confstr)
    return (int(m.group(1)), int(m.group(2))) if m else None


def get_platform_tag():
    """W-PY23: correct platform tag for the wheel (fail-fast off-Linux).

    The wheel carries a compiled .so (ctypes-loaded, so any Python 3
    works — only the platform matters). A py3-none-any tag would let
    pip install it on ARM/macOS where the .so cannot load; the
    platform tag makes that a clean refusal instead.

    W-REL: PyPI rejects a bare `linux_x86_64` platform tag outright
    ("unsupported platform tag") — only PEP 600 manylinux/musllinux
    tags are accepted for Linux wheels. So the tag must name the glibc
    floor, which is why this reads the build host's libc instead of
    hardcoding a string.
    """
    system = platform.system()
    if system != "Linux":
        raise RuntimeError(
            "forkrun requires Linux (got %s). The C substrate uses "
            "Linux-specific syscalls (memfd_create, splice, "
            "fallocate)." % system)
    machine = platform.machine()
    if machine not in ("x86_64", "aarch64"):
        raise RuntimeError(
            "unsupported architecture %r (supported: x86_64, aarch64)"
            % machine)
    glibc = _glibc_version()
    if glibc is None:
        raise RuntimeError(
            "no glibc detected on this build host (musl?). forkrun's "
            "engine links against glibc; build the wheel inside a "
            "manylinux container (tools/build_wheel.sh) or on glibc.")
    eligible = [p for p in _MANYLINUX_POLICIES if p <= glibc]
    if not eligible:
        raise RuntimeError(
            "glibc %d.%d predates every supported manylinux policy"
            % glibc)
    floor = eligible[-1]
    return "manylinux_%d_%d_%s" % (floor[0], floor[1], machine)


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

        # CR-FIX1-I: build the launcher on BOTH paths. The gcc fallback
        # used to stop at the substrate, so behaviour silently diverged
        # by host tooling -- and because the launcher was never listed in
        # package_data, that divergence was invisible.
        cr_path = os.path.join(PKG_DIR, CR_NAME)
        self.announce("building cleanroom launcher %s" % CR_NAME)
        if shutil.which("gcc") is None:
            raise RuntimeError("need gcc to build the cleanroom launcher")
        subprocess.run(
            ["gcc", "-O2", "-o", cr_path,
             os.path.join(REPO_ROOT, "forkrun_cleanroom.c"),
             "-ldl", "-lrt"],
            check=True, cwd=REPO_ROOT)
        if not os.path.exists(cr_path):
            raise RuntimeError("launcher build produced no %s" % CR_NAME)


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
    # CR-FIX1-I: the launcher ships too. It was listed NOWHERE, so a
    # wheel install silently had no cleanroom at all: _cleanroom_
    # launcher_path() resolves the binary relative to the substrate .so,
    # and it simply was not there. That made `pip install forkrun`
    # quietly different from a source checkout, which is exactly the
    # kind of divergence the substrate .so being explicitly listed was
    # meant to prevent.
    # CR-FIX1-I again: an artifact that is not LISTED does not ship, and
    # a wheel install is then quietly different from a source checkout.
    # The UDF helper is the same class of artifact as the launcher.
    package_data={"forkrun": ([SO_NAME, CR_NAME, "py.typed"]
                               + ([UDF_HELPER] if UDF_HELPER else []))},
    cmdclass={"build_py": BuildSubstratePy, "bdist_wheel": BdistWheel},
    # The wheel carries a compiled .so: tag it for this platform so
    # pip refuses it elsewhere (never py3-none-any). The tag is a
    # PEP 600 manylinux floor derived from the BUILD HOST's glibc —
    # see get_platform_tag(). Build inside the manylinux container to
    # get a floor below your distro's glibc (tools/build_wheel.sh).
    options={"bdist_wheel": dict(
        {"plat_name": PLATFORM_TAG},
        # cp3XX when the CPython-linked helper ships; absent otherwise,
        # so the generic substrate wheel keeps its py3-none tag.
        **({"python_tag": WHEEL_PYTHON_TAG} if WHEEL_PYTHON_TAG else {}))},
    python_requires=">=3.10",
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
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        # W-REL5-F (F2): 3.13 joins the CI version matrix (python-check
        # version-matrix job); the floor stays 3.10 (python_requires).
        "Programming Language :: Python :: 3.13",
        "Topic :: System :: Distributed Computing",
        "Topic :: System",
        "Topic :: Scientific/Engineering",
        "Topic :: Utilities",
    ],
)
