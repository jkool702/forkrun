#!/usr/bin/env bash
# CI script: build shared CPython + per-minor UDF wheels + run acceptance.
# Usage: ci_udf_acceptance.sh <minor>  (e.g. 3.10)  or "all"
set -euo pipefail
run_one() {
  local minor="$1"
  # Build shared CPython if not present.
  if [ ! -x "/opt/pyshared/cp${minor/./}-cp${minor/./}/bin/python${minor}" ]; then
    # Inline build (mirrors build_cpython.sh).
    case "$minor" in
      3.10) patch=3.10.22 ;; 3.11) patch=3.11.17 ;; 3.12) patch=3.12.15 ;;
      3.13) patch=3.13.17 ;; 3.14) patch=3.14.9 ;; 3.15) patch=3.15.1 ;;
    esac
    prefix="/opt/pyshared/cp${minor/./}-cp${minor/./}"
    if ! rpm -q openssl-devel >/dev/null 2>&1; then
      dnf install -y -q openssl-devel bzip2-devel libffi-devel zlib-devel \
        readline-devel sqlite-devel xz-devel >/dev/null 2>&1
    fi
    cd /tmp
    tarball="Python-${patch}.tgz"
    [ -f "$tarball" ] || curl -fsSL "https://www.python.org/ftp/python/${patch}/${tarball}" -o "$tarball"
    rm -rf "Python-${patch}"
    tar xzf "$tarball"
    cd "Python-${patch}"
    ./configure --enable-shared --prefix="$prefix" >/tmp/cfg.log 2>&1
    make -j"$(nproc)" >/tmp/make.log 2>&1
    make install >/tmp/install.log 2>&1
  fi
  export LD_LIBRARY_PATH="/opt/pyshared/cp${minor/./}-cp${minor/./}/lib:${LD_LIBRARY_PATH:-}"
  PY="/opt/pyshared/cp${minor/./}-cp${minor/./}/bin/python${minor}"
  cd /src
  rm -rf build python/forkrun.egg-info
  "$PY" -m pip install --quiet build auditwheel setuptools wheel
  make -f Makefile.substrate udf-lib PYTHON="$PY"
  rm -f python/forkrun/_forkrun_cleanroom
  make -f Makefile.substrate cleanroom-launcher
  rm -rf /src/dist/raw /src/dist/repaired
  mkdir -p /src/dist/raw /src/dist/repaired
  "$PY" setup.py bdist_wheel --dist-dir /src/dist/raw
  RAW=$(ls /src/dist/raw/*.whl | head -1)
  "$PY" -m auditwheel repair -w /src/dist/repaired "$RAW"
  REPAIRED=$(ls /src/dist/repaired/*.whl | head -1)
  echo "WHEEL=$REPAIRED"
  rm -rf "/tmp/udfacc_${minor}" && mkdir -p "/tmp/udfacc_${minor}"
  PYTHONPATH="/tmp/udfacc_${minor}" "$PY" tools/acceptance_installed_wheel.py \
    --wheel "$REPAIRED" --interpreter "$PY" --mode udf \
    --udf-func px_udf:up --workdir "/tmp/udfacc_${minor}"
}

if [ "${1:-all}" = "all" ]; then
  for m in 3.10 3.11 3.12 3.13 3.14 3.15; do
    run_one "$m"
  done
else
  run_one "$1"
fi
echo "ALL UDF ACCEPTANCE PASSED"
EOF
echo "created"