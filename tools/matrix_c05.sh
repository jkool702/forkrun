#!/bin/bash
# C0.5 -- the interpreter matrix gate.
#
#   tools/matrix_c05.sh [--quick]
#
# Fetches the distro CPythons for 3.10-3.15 into a local prefix (no root
# needed: dnf download + rpm2cpio), builds the UDF helper and the C0.4
# fork-lifecycle driver against EACH one, and runs the three probes:
#
#   default   pre-fork vs post-fork timing, with a verdict REFUSED unless
#             every requested trial succeeded and neither arm failed
#   --control in-process state mutation must be detectable; a CLEAN
#             result means the probe is vacuous and its verdict on a real
#             respawn means nothing
#   --respawn a respawned generation must NOT inherit interpreter state
#
# All three exist because "pre-fork works" is otherwise unfalsifiable in
# the direction that matters. See dev/supervisor/C0.5_INTERPRETER_MATRIX.md.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK=/tmp/pymin
PREFIX="$WORK/root"
# THE supported minors, from the ONE definition (tools/wheel_matrix.py
# -- DECISION-01 Option A: one wheel per supported minor). This script
# used to carry its own copy of the list, which is exactly how two
# lists drift; it now reads the canonical one and drops the HOST's own
# minor, which is already present.
MINORS="$(python3 "$ROOT/tools/wheel_matrix.py" --list | tr '\n' ' ')"
MINORS="$(python3 - "$MINORS" <<'PYEOF'
import sys
host = "%d.%d" % sys.version_info[:2]
print(" ".join(m for m in sys.argv[1].split() if m != host))
PYEOF
)"
QUICK="--quick"
SAN=""

# --asan builds every minor with ASan+UBSan and runs each probe with the
# allocator settings that make that meaningful for an EMBEDDED CPython.
#
# Two settings matter and neither is obvious:
#
#   PYTHONMALLOC=malloc routes CPython's object allocations through the
#   system allocator so ASan can actually see them. Without it CPython
#   uses its own pymalloc arenas and an overflow inside an object is
#   invisible to the sanitizer -- the single most common reason people
#   report "ASan is clean on Python".
#
#   detect_leaks=0, because an embedded interpreter initialised and torn
#   down in a short-lived process reports CPython's own module-cache
#   allocations as leaks. Leaving it on produces noise that trains
#   reviewers to ignore the output; UBSan is the one that carries real
#   signal here, so it runs with halt_on_error and a stack trace.
SAN_ENV="ASAN_OPTIONS=detect_leaks=0:abort_on_error=1 UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1 PYTHONMALLOC=malloc"

for arg in "$@"; do
    case "$arg" in
        --quick) QUICK="--quick" ;;
        --asan)  SAN="-fsanitize=address,undefined -fno-omit-frame-pointer -g" ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

mkdir -p "$PREFIX" "$WORK/rpms"

fetch() {   # fetch <minor>
    local v="$1"
    if [ -x "$PREFIX/usr/bin/python$v" ]; then return 0; fi
    echo "  fetching $v..."
    ( cd "$WORK/rpms" && \
      timeout 600 dnf download --destdir=. --resolve \
        "python$v" "python$v-devel" >/dev/null 2>&1 )
    local rc=$?
    if [ $rc -ne 0 ]; then
        echo "  $v: download FAILED (rc=$rc)"
        return 1
    fi
    local rpm
    for rpm in "$WORK"/rpms/python$v-*.rpm "$WORK"/rpms/python$v-devel-*.rpm; do
        [ -e "$rpm" ] || continue
        rpm2cpio "$rpm" | ( cd "$PREFIX" && cpio -idmu --quiet 2>/dev/null )
        rm -f "$rpm"
    done
    [ -x "$PREFIX/usr/bin/python$v" ] || { echo "  $v: no interpreter"; return 1; }
}

wrapper() {  # wrapper <minor>
    local v="$1"
    cat > "$WORK/bin/python$v" <<EOF
#!/bin/bash
export LD_LIBRARY_PATH=$PREFIX/usr/lib64\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}
exec "$PREFIX/usr/bin/python$v" "\$@"
EOF
    chmod +x "$WORK/bin/python$v"
}

build() {    # build <minor>  -> /tmp/pymin/root/usr/bin/udf_fork_<minor>
    local v="$1" inc lib
    inc="$(LD_LIBRARY_PATH="$PREFIX/usr/lib64" "$PREFIX/usr/bin/python$v" -c \
             'import sysconfig;print(sysconfig.get_paths()["include"])' 2>/dev/null)"
    [ -f "$inc/Python.h" ] || { echo "  $v: no headers"; return 1; }
    lib="$PREFIX/usr/lib64"
    # -I"$ROOT" is REQUIRED, not cosmetic: forkrun_udf_version.h (the
    # build stamp the launcher and the helper must agree on) lives at the
    # REPO ROOT, and the Makefile's equivalent line has always said -I.
    # Without it EVERY per-minor build failed on the missing header --
    # and the failure was invisible, because the lifecycle sweep below
    # then used the STALE driver from a previous run.
    #
    # Remove the old driver FIRST: a failed build must not be able to
    # leave a previous run's binary in place to be measured as if it
    # were fresh.
    rm -f "$PREFIX/usr/bin/udf_fork_$v"
    gcc -O2 $SAN -I"$inc" -I"$ROOT" -I"$ROOT/python/forkrun" \
        -o "$PREFIX/usr/bin/udf_fork_$v" \
        "$ROOT/python/forkrun/fr_udf_fork.c" "$ROOT/python/forkrun/fr_udf.c" \
        -L"$lib" "-lpython$v" -ldl -lm 2>"$WORK/build_$v.log" \
        && return 0
    echo "  $v: BUILD FAILED"; grep -m2 "error:" "$WORK/build_$v.log"
    return 1
}

echo "C0.5 interpreter matrix gate"
echo "  minors: 3.10-3.14 (system 3.14) + 3.15  |  probes: verdict, control, respawn"
echo

rc_all=0
for v in $MINORS; do
    echo "=== CPython $v ==="
    fetch "$v"   || { rc_all=1; continue; }
    wrapper "$v"
    build  "$v"  || { rc_all=1; continue; }
    export FR_UDF_HOME="$PREFIX/usr"
    export LD_LIBRARY_PATH="$PREFIX/usr/lib64"
    for probe in "" "--control" "--respawn"; do
        raw=$(timeout 180 env $SAN_ENV "$PREFIX/usr/bin/udf_fork_$v" \
                 /tmp/udfroot myudf:up 2 20 $probe 2>&1)
        echo "$raw" > "$WORK/probe_${v}_${probe:-verdict}.log"
        line=$(echo "$raw" \
               | grep -E "interpreter :|VERDICT|NO VERDICT|control :|respawn :" \
               | head -2 | tr '\n' '|')
        printf "   %-9s %s\n" "${probe:-verdict}" "$line"
        san=$(echo "$raw" | grep -cE "AddressSanitizer|runtime error:|SUMMARY: .*Sanitizer")
        if [ "$san" -gt 0 ]; then
            printf "   %-9s SANITIZER HITS: %s\n" "" "$san"
            echo "$raw" | grep -m2 -E "AddressSanitizer|runtime error:" | sed 's/^/       /'
            rc_all=1
        fi
    done
    echo
done

# The system interpreter, for comparison.
if [ -x "$ROOT/python/forkrun/fr_udf_fork" ]; then
    # FR_UDF_HOME and LD_LIBRARY_PATH are exported in the loop above and
    # point at the extracted prefix. Leaving them set makes the SYSTEM
    # 3.14 driver initialise against a prefix that has no 3.14 stdlib, so
    # it fails and the verdict line silently vanishes -- a row that looks
    # like "no result" rather than "not run".
    unset FR_UDF_HOME
    export LD_LIBRARY_PATH=""
    echo "=== CPython 3.14 (system build) ==="
    for probe in "" "--control" "--respawn"; do
        raw=$(timeout 180 env $SAN_ENV "$ROOT/python/forkrun/fr_udf_fork" \
                 /tmp/udfroot myudf:up 2 20 $probe 2>&1)
        echo "$raw" > "$WORK/probe_sys_${probe:-verdict}.log"
        line=$(echo "$raw" \
               | grep -E "interpreter :|VERDICT|NO VERDICT|control :|respawn :" \
               | head -2 | tr '\n' '|')
        printf "   %-9s %s\n" "${probe:-verdict}" "$line"
        san=$(echo "$raw" | grep -cE "AddressSanitizer|runtime error:|SUMMARY: .*Sanitizer")
        if [ "$san" -gt 0 ]; then
            printf "   %-9s SANITIZER HITS: %s\n" "" "$san"
            echo "$raw" | grep -m2 -E "AddressSanitizer|runtime error:" | sed 's/^/       /'
            rc_all=1
        fi
    done
fi

echo
echo "Lifecyle curves per minor (needs /tmp/udfroot/myudf.py with up/touch/is_touched):"
for v in $MINORS; do
    # Only a driver THIS RUN produced may be measured.
    [ -x "$PREFIX/usr/bin/udf_fork_$v" ] || continue
    [ "$PREFIX/usr/bin/udf_fork_$v" -nt "$WORK/build_$v.log" ] || continue
    if [ -n "$SAN" ]; then
        echo "  $v: lifecycle sweep skipped under sanitizers (3 trials x 2 arms x 6 minors does not fit a gate)"
        continue
    fi
    FR_UDF_HOME="$PREFIX/usr" LD_LIBRARY_PATH="$PREFIX/usr/lib64" \
    FR_BENCH_DRIVER="$PREFIX/usr/bin/udf_fork_$v" \
        timeout 1200 python3 "$ROOT/tools/bench_m2_lifecycle.py" $QUICK \
        --trials 3 2>&1 | grep -E "driver cp|pre-fork faster|speedup  min" \
        | sed 's/^/  /'
done

exit $rc_all