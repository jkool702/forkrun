#!/usr/bin/env bash
# tools/build_wheel.sh — build the forkrun sdist + wheel exactly as PyPI
# will receive them, then gate on the result.
#
# WHY A CONTAINER: the wheel embeds a compiled .so, so its PEP 600
# manylinux floor is set by the glibc it is COMPILED against, not by
# what forkrun actually needs. Building on a current Fedora box
# (glibc 2.43) bakes in GLIBC_2.38 references that have nothing to do
# with the engine:
#
#   __isoc23_strtol/strtoll/strtoul/strtoull/sscanf @ GLIBC_2.38
#       glibc >= 2.38 headers remap strtol() to __isoc23_strtol() when
#       __GLIBC_USE(C23_STRTOL) is set — which _GNU_SOURCE alone
#       triggers (see /usr/include/stdlib.h). The engine needs
#       _GNU_SOURCE (memfd_create, splice), so -std=gnu17 / -std=c17 /
#       -D_ISOC2X_SOURCE=0 do NOT suppress it. Only older headers do.
#   dlopen/dlsym/dlerror/dlclose @ GLIBC_2.34
#       dlopen moved into libc at 2.34; on the build host -ldl is a
#       forwarding stub, so the reference lands on libc's 2.34 node.
#
# The engine's TRUE floor is GLIBC_2.28 (fcntl64; memfd_create and
# copy_file_range are 2.27). So the manylinux_2_28 image — AlmaLinux 8,
# glibc 2.28 headers, real libdl — produces a wheel whose tag matches
# its actual requirements, covering RHEL 8, Debian 10+, Ubuntu 20.04+.
#
# Building on Fedora and merely RELABELLING the result is the trap:
# auditwheel would (correctly) refuse to stamp manylinux_2_28 on a
# binary that references 2.38 symbols.
#
# Usage:  tools/build_wheel.sh [--keep-raw]
# Output: dist/forkrun-<ver>-py3-none-manylinux_2_28_x86_64.whl
#         dist/forkrun-<ver>.tar.gz

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${FORKRUN_MANYLINUX_IMAGE:-quay.io/pypa/manylinux_2_28_x86_64}"
ARCH_TAG="${FORKRUN_ARCH_TAG:-manylinux_2_28_x86_64}"
OUT_DIR="$REPO_ROOT/dist"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

KEEP_RAW=0
MATRIX=0
STRICT=0
MINORS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --keep-raw) KEEP_RAW=1 ;;
        --matrix)   MATRIX=1 ;;
        --strict)   STRICT=1 ;;
        --minor)    MINORS="$MINORS ${2:-}"; shift ;;
        *) die "unknown option: $1" ;;
    esac
    shift
done

die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
step() { printf '\033[36m==>\033[0m %s\n' "$*"; }

# --- runtime -------------------------------------------------------------
if command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
    RUNTIME=podman
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    RUNTIME=docker
else
    die "neither podman nor docker is usable (daemon reachable?)"
fi
step "runtime: $RUNTIME"

# `podman info`/`docker info` are slow; already validated above.

step "image: $IMAGE"
$RUNTIME pull -q "$IMAGE" >/dev/null 2>&1 || \
    $RUNTIME image inspect "$IMAGE" >/dev/null 2>&1 || \
    die "could not pull or find $IMAGE"

# --- clean previous artifacts -------------------------------------------
# dist/ is gitignored build output; stale wheels are exactly how a
# rejected upload happens twice.
step "cleaning $OUT_DIR"
rm -rf "$OUT_DIR/raw" "$OUT_DIR"/forkrun-*.whl "$OUT_DIR"/forkrun-*.tar.gz
mkdir -p "$OUT_DIR"

# --- build in the container ---------------------------------------------
# The repo is mounted rw because setup.py's build_py compiles the .so
# in-tree (PY_OUT under python/forkrun/). That is intentional: the
# resulting tree .so is the portable glibc-2.28 artifact.
step "building sdist + wheel in $IMAGE"
$RUNTIME run --rm \
    -v "$REPO_ROOT:/src:rw,z" \
    -w /src \
    -e "FORKRUN_ARCH_TAG=$ARCH_TAG" \
    -e "FORKRUN_BUILD_PYTHON=${FORKRUN_BUILD_PYTHON:-}" \
    -e "FORKRUN_MATRIX=$MATRIX" \
    -e "FORKRUN_STRICT=$STRICT" \
    -e "FORKRUN_MINORS=${MINORS# }" \
    "$IMAGE" \
    bash -euo pipefail -c '
        # bash headers are NOT in the manylinux image, and the engine TU
        # includes them. AlmaLinux 8 has them in the base repo.
        dnf install -y bash-devel >/dev/null

        # The image'"'"'s /usr/bin/python3 has no pip; the real
        # interpreters live in /opt/python. Pick the newest stable
        # CPython that has pip (3.15 is an rc in this image — skip).
        PY="${FORKRUN_BUILD_PYTHON:-}"
        if [ -z "$PY" ]; then
            for cand in /opt/python/cp314-cp314/bin/python3.14 \
                        /opt/python/cp313-cp313/bin/python3.13 \
                        /opt/python/cp312-cp312/bin/python3.12; do
                if [ -x "$cand" ] && "$cand" -c "import pip" 2>/dev/null; then
                    PY="$cand"; break
                fi
            done
        fi
        [ -n "$PY" ] || { echo "no pip-capable python found" >&2; exit 1; }

        "$PY" -m pip install --quiet --upgrade build auditwheel

        echo "--- toolchain ---"
        # sed -n 1p, NOT `head -1`: under `set -o pipefail` a reader that
        # exits early sends SIGPIPE to gcc, which fails the whole script.
        ldd --version | sed -n 1p
        gcc --version | sed -n 1p
        "$PY" --version
        "$PY" -m auditwheel --version

        if [ "${FORKRUN_MATRIX:-0}" = "1" ]; then
            # PER-MINOR MATRIX (DECISION-01 Option A): one wheel per
            # supported CPython minor, each carrying the helper built
            # for THAT minor. The orchestration is tools/wheel_matrix.py
            # -- one implementation, testable without a container.
            echo "--- per-minor matrix ---"
            "$PY" -m pip install --quiet --upgrade build auditwheel
            mkdir -p dist/matrix
            STRICT_FLAG=""
            [ "${FORKRUN_STRICT:-0}" = "1" ] && STRICT_FLAG=--strict
            if [ -n "${FORKRUN_MINORS:-}" ]; then
                set -- --minor
                for m in $FORKRUN_MINORS; do set -- "$@" "$m"; done
                "$PY" tools/wheel_matrix.py "$@" --out-dir dist/matrix \
                    --auditwheel $STRICT_FLAG
            else
                "$PY" tools/wheel_matrix.py --all --out-dir dist/matrix \
                    --auditwheel $STRICT_FLAG
            fi
            exit 0
        fi

        # The UDF helper EMBEDS the interpreter (it links libpython).
        # This image ships NO libpython at all -- the interpreters under
        # /opt/python are built with a STATIC libpython and the static
        # archives are stripped -- so the helper CANNOT be built here.
        #
        # That means any helper already present in the tree is a
        # FOREIGN artifact: built on the host, linked against the HOST
        # glibc. Baking it into a manylinux_2_28 wheel would make the
        # tag a lie (the binary would need a newer glibc than the tag
        # claims) -- exactly the trap auditwheel refuses, and exactly
        # what the comment at the top of this file describes. Remove
        # them, so the container build produces the generic substrate
        # wheel it can honestly produce.
        #
        # The PER-MINOR wheels (which carry the helper) are built by
        # tools/wheel_matrix.py, where the interpreter is one that HAS
        # an embeddable libpython.
        rm -f python/forkrun/_fr_udf*.so
        echo "removed any pre-existing UDF helper from the tree"

        # 1. sdist first, from the tree.
        "$PY" -m build --sdist --outdir dist .

        SDIST="$(ls dist/forkrun-*.tar.gz)"

        # 2. wheel FROM the sdist, not from the tree. This proves the
        #    published sdist is self-sufficient (it must be — it is the
        #    only install path for anyone on a glibc we do not ship a
        #    wheel for, and Debian/Ubuntu cannot even build it without
        #    bash-devel).
        "$PY" -m build --wheel --outdir dist/raw "$SDIST"

        RAW="$(ls dist/raw/forkrun-*.whl)"

        # 3. auditwheel is the authority on the floor. No --plat: it
        #    picks the highest policy the binary actually satisfies,
        #    capped at the build image'"'"'s glibc.
        echo "--- auditwheel show ---"
        "$PY" -m auditwheel show "$RAW"

        "$PY" -m auditwheel repair -w dist "$RAW"
    '

# --- gate ----------------------------------------------------------------
if [ "$MATRIX" -eq 1 ]; then
    # PER-MINOR MATRIX gate. Every wheel is validated against its own
    # artifacts (the canonical rule, tools/wheel_matrix.py), and an
    # INCOMPLETE matrix is reported as such -- never as a successful
    # release build.
    step "verifying the per-minor matrix"
    shopt -s nullglob
    MATRIX_WHEELS=("$OUT_DIR"/matrix/forkrun-*.whl)
    [ "${#MATRIX_WHEELS[@]}" -ge 1 ] || die "the matrix produced no wheels"
    for w in "${MATRIX_WHEELS[@]}"; do
        case "$(basename "$w")" in
            *"$ARCH_TAG"*) : ;;
            *) die "wheel is not tagged $ARCH_TAG: $(basename "$w")" ;;
        esac
        python3 "$REPO_ROOT/tools/wheel_matrix.py" --validate-wheel "$w" \
            || die "invalid wheel: $(basename "$w")"
    done
    echo
    echo "matrix wheels:"
    ls -l "${MATRIX_WHEELS[@]}"
    # Strictness is enforced INSIDE the container run (the module exits
    # non-zero when a supported minor did not produce a valid wheel),
    # so an incomplete matrix fails the build there rather than being
    # rediscovered by rebuilding everything here.
    step "ok"
    exit 0
fi

# The whole point of the container build is this filename. If it is not
# the manylinux tag, PyPI will either 400 it (bare linux_*) or we have
# silently shipped a wheel with a floor higher than it needs.
step "verifying output"
shopt -s nullglob
# A per-minor wheel is tagged cp3XX, because the UDF helper it carries is
# CPython-LINKED (DECISION-01 5.4). The generic substrate wheel -- built
# without the helper -- stays py3-none. Accept EITHER, and refuse to pick
# between two: a build that produced both is ambiguous, and silently
# choosing one is how the wrong artifact ships.
WHEELS=("$OUT_DIR"/forkrun-*-py3-*.whl "$OUT_DIR"/forkrun-*-cp3??-*.whl)
SDISTS=("$OUT_DIR"/forkrun-*.tar.gz)
[ "${#WHEELS[@]}" -eq 1 ] || die "expected exactly 1 wheel, got ${#WHEELS[@]}"
[ "${#SDISTS[@]}" -eq 1 ] || die "expected exactly 1 sdist, got ${#SDISTS[@]}"

WHEEL="${WHEELS[0]}"
case "$(basename "$WHEEL")" in
    *"$ARCH_TAG"*) : ;;
    *) die "wheel is not tagged $ARCH_TAG: $(basename "$WHEEL")" ;;
esac

# Independently confirm the ELF floor rather than trusting the filename
# (or auditwheel). Parsed in python: the arch component of a platform
# tag contains an underscore ("x86_64"), so shell splitting is a trap.
python3 - "$WHEEL" "$ARCH_TAG" <<'PY' || exit 1
import re, subprocess, sys, zipfile, tempfile, os

wheel, want_tag = sys.argv[1], sys.argv[2]

plat = os.path.basename(wheel)[:-len(".whl")].split("-")[-1]
m = re.match(r"manylinux_(\d+)_(\d+)_(.+)$", plat)
if not m:
    sys.exit("not a manylinux platform tag: %r" % plat)
claimed = (int(m.group(1)), int(m.group(2)))
if plat != want_tag:
    sys.exit("wheel platform tag is %s, expected %s" % (plat, want_tag))

with tempfile.TemporaryDirectory() as tmp:
    with zipfile.ZipFile(wheel) as zf:
        names = [n for n in zf.namelist() if n.endswith(".so")]
        if not names:
            sys.exit("wheel embeds no .so — nothing to gate on")
        zf.extract(names[0], tmp)
        so = os.path.join(tmp, names[0])

    out = subprocess.run(["objdump", "-T", so],
                         capture_output=True, text=True).stdout
    vers = sorted({v for v in re.findall(r"GLIBC_(\d+)\.(\d+)", out)},
                  key=lambda v: (int(v[0]), int(v[1])))
    if not vers:
        sys.exit("no GLIBC versioned symbols found in %s" % names[0])
    need = (int(vers[-1][0]), int(vers[-1][1]))

    # Undefined symbols only: defined ones are forkrun's own.
    undef = [ln for ln in out.splitlines() if "*UND*" in ln]
    isoc = sorted({re.search(r"__isoc23_\w+", ln).group(0)
                   for ln in undef if "__isoc23_" in ln})

print("wheel      : %s" % os.path.basename(wheel))
print("tag claims : glibc %d.%d" % claimed)
print("needs      : glibc %d.%d" % need)
if isoc:
    # These come from glibc >= 2.38 headers under _GNU_SOURCE; they are
    # what forces a 2.38 floor when building outside the container.
    print("isoc23 refs: %s" % ", ".join(isoc))
if need > claimed:
    sys.exit(
        "MISMATCH: binary needs glibc %d.%d but is tagged %d.%d.\n"
        "       The tag is a promise pip trusts and the loader enforces.\n"
        "       Build inside %s (or a matching manylinux image); a host\n"
        "       with newer glibc can only push this number UP."
        % (need + claimed + (want_tag,)))
if need < claimed:
    print("note       : tag is conservative by glibc %d.%d "
          "(build with an older manylinux image to widen coverage)"
          % (claimed[0] - need[0], claimed[1] - need[1]))
else:
    print("OK         : tag matches the binary exactly")
PY

# The wheel's PYTHON tag must agree with the helper it carries.
#
#   cp3XX  -> the wheel ships the UDF helper, built for THAT minor.
#   py3    -> the wheel ships NO helper. "Keep the source-only development
#             path honest: do not advertise a locally built helper as
#             present in a generic ABI-independent wheel" (DECISION-01 5.4).
#
# A cp3XX wheel whose helper is for a different minor is a LYING tag, and
# pip would install it on the wrong interpreter.
# The tag-vs-artifact rule lives in ONE place (tools/wheel_matrix.py):
# it is the same rule the per-minor matrix validates each wheel with,
# and two copies of a rule is how they drift.
python3 "$REPO_ROOT/tools/wheel_matrix.py" --validate-wheel "$WHEEL" || exit 1

[ "$KEEP_RAW" -eq 1 ] || rm -rf "$OUT_DIR/raw"

# Regenerate checksums.txt rather than leaving whatever was there.
# TAG_PREP step 7 attaches this to the GitHub release, so a stale copy
# (e.g. left by release_check.py building a host-glibc wheel into the
# same directory) would publish hashes for files that are not the ones
# being released.
step "checksums"
( cd "$OUT_DIR" && rm -f checksums.txt && sha256sum "$(basename "$WHEEL")" \
    "$(basename "${SDISTS[0]}")" > checksums.txt )

step "ok"
ls -l "$WHEEL" "${SDISTS[0]}" "$OUT_DIR/checksums.txt"
echo
cat "$OUT_DIR/checksums.txt"
echo
echo "next:  twine upload ${WHEEL#"$REPO_ROOT"/} ${SDISTS[0]#"$REPO_ROOT"/}"
