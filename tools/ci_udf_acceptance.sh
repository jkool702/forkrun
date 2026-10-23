#!/usr/bin/env bash
# CI script: build a shared CPython + per-minor UDF wheel, then prove the
# INSTALLED wheel runs a real UDF through the cleanroom helper.
#
# Usage:
#   tools/ci_udf_acceptance.sh <minor>     # e.g. 3.10
#   tools/ci_udf_acceptance.sh all         # every supported minor
#   tools/ci_udf_acceptance.sh --list      # the supported-minor set
#
# The supported-minor SET has exactly one definition:
# tools/wheel_matrix.py::SUPPORTED_MINORS, read through `--list`. The
# minor -> CPython patch table below is a MAPPING (which tarball to fetch),
# not a second support list: it is checked against the one set and fails
# loudly if a supported minor has no pinned patch.
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO"

LIST_PYTHON=${LIST_PYTHON:-python3}
PREFIX_ROOT=${PREFIX_ROOT:-/opt/pyshared}
# The caller's loader path is preserved per interpreter prefix, never
# accumulated across minors: build_cpython owns the export.
BASE_LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-}

die() {
  echo "ci_udf_acceptance: $*" >&2
  exit 1
}

list_minors() {
  command -v "$LIST_PYTHON" >/dev/null 2>&1 \
    || die "cannot find '$LIST_PYTHON' to read the supported-minor list"
  "$LIST_PYTHON" "$REPO/tools/wheel_matrix.py" --list
}

# Explicit mapping: minor -> pinned CPython source release. This is NOT
# the support definition; a missing entry is a hard error, not a skip.
patch_for_minor() {
  case "$1" in
    3.10) echo "3.10.22" ;;
    3.11) echo "3.11.17" ;;
    3.12) echo "3.12.15" ;;
    3.13) echo "3.13.17" ;;
    3.14) echo "3.14.9" ;;
    3.15) echo "3.15.1" ;;
    *) return 1 ;;
  esac
}

minor_is_supported() {
  # Capture first: `list_minors | grep -q` can SIGPIPE the producer, and
  # `set -o pipefail` would then report a SUPPORTED minor as unsupported.
  local supported
  supported=$(list_minors) || return 1
  grep -Fxq -- "$1" <<<"$supported"
}

install_build_deps() {
  # bash-devel is required by the substrate; the rest are CPython's
  # usual optional modules. rpm -q fails if ANY package is absent.
  if ! rpm -q curl openssl-devel bzip2-devel libffi-devel zlib-devel \
       readline-devel sqlite-devel xz-devel bash-devel >/dev/null 2>&1; then
    dnf install -y -q curl openssl-devel bzip2-devel libffi-devel \
      zlib-devel readline-devel sqlite-devel xz-devel bash-devel \
      >/tmp/udf-dnf.log 2>&1 \
      || { tail -n 80 /tmp/udf-dnf.log >&2; die "dnf install failed"; }
  fi
}

# Sets PY (interpreter) and PREFIX for the requested minor. A cached
# prefix is accepted only if it is EXACTLY the pinned patch and was built
# shared -- a stale/different interpreter is a hard failure, never a
# silent substitution.
build_cpython() {
  local minor="$1" patch py tarball
  patch=$(patch_for_minor "$minor") \
    || die "no CPython patch pinned for supported minor $minor"
  PREFIX="$PREFIX_ROOT/cp${minor/./}-cp${minor/./}"
  py="$PREFIX/bin/python$minor"
  # A --enable-shared install has no rpath to its own prefix, and this
  # script never runs ldconfig. The loader path must therefore be set by
  # the SAME function that establishes the interpreter, BEFORE the first
  # execution: validating "$py" without it fails with
  # "libpython3.X.so.1.0: cannot open shared object file". Setting it
  # later in run_one was too late for exactly that check.
  export LD_LIBRARY_PATH="$PREFIX/lib${BASE_LD_LIBRARY_PATH:+:$BASE_LD_LIBRARY_PATH}"
  if [ ! -x "$py" ]; then
    install_build_deps
    cd /tmp
    tarball="Python-${patch}.tgz"
    if [ ! -f "$tarball" ]; then
      curl -fsSL "https://www.python.org/ftp/python/${patch}/${tarball}" \
        -o "$tarball" \
        || die "could not download CPython ${patch}"
    fi
    rm -rf "Python-${patch}"
    tar xzf "$tarball"
    cd "Python-${patch}"
    ./configure --prefix="$PREFIX" --enable-shared \
      --with-ensurepip=install >"/tmp/udf-configure-${minor}.log" 2>&1 \
      || { tail -n 80 "/tmp/udf-configure-${minor}.log" >&2
           die "configure failed for CPython ${patch}"; }
    make -j"$(nproc)" >"/tmp/udf-make-${minor}.log" 2>&1 \
      || { tail -n 80 "/tmp/udf-make-${minor}.log" >&2
           die "make failed for CPython ${patch}"; }
    make install >"/tmp/udf-install-${minor}.log" 2>&1 \
      || { tail -n 80 "/tmp/udf-install-${minor}.log" >&2
           die "make install failed for CPython ${patch}"; }
    cd "$REPO"
  fi
  [ -x "$py" ] || die "interpreter was not installed: $py"
  "$py" - "$minor" "$patch" <<'PY' \
    || die "interpreter at $py is not the pinned shared CPython"
import os
import sys
import sysconfig

minor, patch = sys.argv[1], sys.argv[2]
want = tuple(int(part) for part in patch.split("."))
got = sys.version_info[:3]
if got != want:
    raise SystemExit("interpreter is Python %s, expected %s"
                     % (".".join(str(x) for x in got), patch))
if "%d.%d" % got[:2] != minor:
    raise SystemExit("interpreter minor %d.%d != requested %s"
                     % (got[0], got[1], minor))
if not sysconfig.get_config_var("Py_ENABLE_SHARED"):
    raise SystemExit("interpreter is static; the UDF helper needs a "
                     "shared libpython")
# Py_ENABLE_SHARED is a COMPILED-IN fact; it is not proof that this
# process loaded the libpython just built. A same-soname library
# elsewhere in the loader search path can satisfy the NEEDED entry, so
# the process starts on a different build. Read the actual mapping and
# require it to be the prefix's own file.
libdir = sysconfig.get_config_var("LIBDIR") or ""
ldlibrary = sysconfig.get_config_var("LDLIBRARY") or ""
want_lib = (os.path.realpath(os.path.join(libdir, ldlibrary))
            if libdir and ldlibrary else "")
loaded = set()
with open("/proc/self/maps", encoding="utf-8", errors="replace") as maps:
    for line in maps:
        fields = line.split(None, 5)
        if len(fields) < 6:
            continue
        path = fields[5].strip()
        if "libpython" in os.path.basename(path):
            loaded.add(os.path.realpath(path))
if not loaded:
    raise SystemExit("no libpython is mapped; this is not a shared "
                     "interpreter")
if want_lib not in loaded:
    raise SystemExit("loaded libpython %s is not the built one %s"
                     % (sorted(loaded), want_lib))
PY
  PY="$py"
}

run_one() {
  local minor="$1" suffix helper raw_dir rep_dir log
  local -a raw_wheels rep_wheels

  echo "=== UDF acceptance: Python $minor ==="
  build_cpython "$minor"

  suffix=$("$PY" -c \
    'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX") or "")')
  [ -n "$suffix" ] || die "no EXT_SUFFIX for $minor"
  if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    die "unusable interpreter for $minor"
  fi
  "$PY" -m pip install --quiet --disable-pip-version-check \
    build auditwheel setuptools wheel \
    || die "could not install build tools for $minor"

  # THE STALENESS RULE: Makefile.substrate's udf-lib target has no
  # interpreter stamp, so fr_udf.o (and any helper built by a previous
  # minor) would be reused for the wrong interpreter. Remove them first;
  # the suffix assertion below then proves what was actually built.
  rm -f "$REPO/fr_udf.o" "$REPO"/python/forkrun/_fr_udf*.so
  rm -rf "$REPO/build" "$REPO/python/forkrun.egg-info"
  make -f "$REPO/Makefile.substrate" udf-lib \
    PYTHON="$PY" PYCONFIG="$PY-config" \
    >"/tmp/udf-helper-${minor}.log" 2>&1 \
    || { tail -n 80 "/tmp/udf-helper-${minor}.log" >&2
         die "UDF helper build failed for $minor"; }
  helper="$REPO/python/forkrun/_fr_udf${suffix}"
  [ -f "$helper" ] \
    || die "helper build produced no _fr_udf${suffix} for $minor"
  [ "$(basename "$helper")" = "_fr_udf${suffix}" ] \
    || die "helper name does not carry this interpreter's suffix: $helper"

  make -f "$REPO/Makefile.substrate" python-substrate \
    >"/tmp/udf-substrate-${minor}.log" 2>&1 \
    || { tail -n 80 "/tmp/udf-substrate-${minor}.log" >&2
         die "python substrate/launcher build failed for $minor"; }
  [ -f "$REPO/python/forkrun/libforkrun_python.so" ] \
    || die "substrate .so missing after build"
  [ -x "$REPO/python/forkrun/_forkrun_cleanroom" ] \
    || die "cleanroom launcher missing after build"

  raw_dir="$REPO/dist/udf/$minor/raw"
  rep_dir="$REPO/dist/udf/$minor/repaired"
  rm -rf "$REPO/dist/udf/$minor"
  mkdir -p "$raw_dir" "$rep_dir"

  # Build the INTERMEDIATE linux wheel, then let auditwheel decide the
  # manylinux floor. Shipping the intermediate is not an option.
  log="/tmp/udf-wheel-${minor}.log"
  "$PY" setup.py bdist_wheel --dist-dir "$raw_dir" \
    --plat-name linux_x86_64 >"$log" 2>&1 \
    || { tail -n 80 "$log" >&2; die "wheel build failed for $minor"; }
  shopt -s nullglob
  raw_wheels=("$raw_dir"/*.whl)
  shopt -u nullglob
  [ "${#raw_wheels[@]}" -eq 1 ] \
    || die "expected exactly one raw wheel for $minor, found ${#raw_wheels[@]}"

  log="/tmp/udf-auditwheel-${minor}.log"
  "$PY" -m auditwheel repair -w "$rep_dir" "${raw_wheels[0]}" \
    >"$log" 2>&1 \
    || { tail -n 80 "$log" >&2
         die "auditwheel repair failed for $minor"; }
  shopt -s nullglob
  rep_wheels=("$rep_dir"/*.whl)
  shopt -u nullglob
  [ "${#rep_wheels[@]}" -eq 1 ] \
    || die "expected exactly one repaired wheel for $minor, found ${#rep_wheels[@]}"
  local repaired="${rep_wheels[0]}"

  # The tag-vs-artifact rule has one authority; use it before installing.
  "$PY" "$REPO/tools/wheel_matrix.py" --validate-wheel "$repaired" \
    || die "repaired wheel failed tag/artifact validation: $repaired"
  "$PY" - "$repaired" "$minor" "$REPO" <<'PY' \
    || die "repaired wheel does not name the requested minor"
import os
import sys

repo, wheel, minor = sys.argv[3], sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(repo, "tools"))
import wheel_matrix
problems = wheel_matrix.validate_wheel(wheel, minor)
if problems:
    for problem in problems:
        sys.stderr.write("FAIL: %s\n" % (problem,))
    raise SystemExit(1)
PY

  rm -rf "/tmp/udfacc_${minor}"
  mkdir -p "/tmp/udfacc_${minor}"
  "$PY" "$REPO/tools/acceptance_installed_wheel.py" \
    --wheel "$repaired" --interpreter "$PY" --expect-minor "$minor" \
    --mode udf --udf-func px_udf:up \
    --workdir "/tmp/udfacc_${minor}" \
    || die "installed-wheel UDF acceptance failed for $minor"

  echo "=== UDF acceptance PASSED: Python $minor ($(basename "$repaired")) ==="
}

if [ "$#" -gt 1 ]; then
  die "usage: $0 <minor>|all|--list"
fi
target="${1:-all}"
if [ "$target" = "--list" ]; then
  list_minors
  exit 0
fi
if [ "$target" != "all" ] && ! minor_is_supported "$target"; then
  die "not a supported minor: $target (supported: $(list_minors | tr '\n' ' '))"
fi

if [ "$target" = "all" ]; then
  while IFS= read -r minor; do
    [ -n "$minor" ] || continue
    run_one "$minor"
  done < <(list_minors)
  echo "ALL UDF ACCEPTANCE PASSED"
else
  run_one "$target"
fi
