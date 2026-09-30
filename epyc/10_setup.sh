#!/usr/bin/env bash
# epyc/10_setup.sh — install dependencies, tune the box, build the substrate.
#
#   bash epyc/10_setup.sh
#
# Must run AFTER 00_preflight.sh. Exits non-zero if forkrun does not work at
# the end (either frontend), so we never spend rental hours benchmarking a
# broken install.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

banner "10 setup"

# ---------------------------------------------------------------- packages --
APT_PKGS=(
    build-essential bash-builtins      # bash-builtins ships /usr/include/bash/*
    git rsync curl ca-certificates
    numactl libnuma1 libnuma-dev
    time parallel
    python3 python3-venv python3-pip python3-numpy
    # NOTE: `numfmt` is NOT a package — it is a binary inside GNU coreutils.
    # An earlier version of this list named it and apt failed with "Unable to
    # locate package numfmt", which then looked like a setup failure. coreutils
    # is listed instead, and lib.sh's human() has an awk fallback anyway.
    bc coreutils procps psmisc
    iproute2 sysstat ethtool
    xz-utils
)

banner "10a apt packages"
log "apt-get update"
DEBIAN_FRONTEND=noninteractive apt-get update -qq >>"$EPYC_OUT/00_environment/apt.log" 2>&1
log "installing: ${APT_PKGS[*]}"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${APT_PKGS[@]}" \
    >>"$EPYC_OUT/00_environment/apt.log" 2>&1
APT_RC=$?
if [ "$APT_RC" -ne 0 ]; then
    err "apt-get install failed rc=$APT_RC — see $EPYC_OUT/00_environment/apt.log"
    # bash-builtins is the one that must not be missing; anything else is survivable
    if [ ! -e /usr/include/bash/shell.h ]; then
        die "bash headers missing after apt; cannot build the Python substrate"
    fi
    warn "continuing despite apt failure"
else
    log "apt ok"
fi

# bash headers are what the engine compiles against (shell.h, builtins.h,
# variables.h, command.h, xmalloc.h, builtins/common.h, config.h).
# pyproject.toml claims these are not packaged on Debian/Ubuntu; that is wrong
# for this header set — bash-builtins(5.2.21) provides all of them.
MISSING_HDRS=()
for h in shell.h builtins.h variables.h command.h xmalloc.h config.h builtins/common.h; do
    [ -e "/usr/include/bash/$h" ] || MISSING_HDRS+=("$h")
done
if [ ${#MISSING_HDRS[@]} -eq 0 ]; then
    log "bash headers OK in /usr/include/bash ($(ls /usr/include/bash | wc -l) entries)"
else
    die "bash headers missing: ${MISSING_HDRS[*]}"
fi

# ------------------------------------------------------------ system tuning --
banner "10b system tuning"

set_sysfs() { # path value
    local p="$1" v="$2" cur
    [ -e "$p" ] || { warn "no such knob: $p"; return 0; }
    cur=$(cat "$p")
    if echo "$cur" | grep -q "\[$v\]"; then
        log "already set: $p = $v"
        return 0
    fi
    if echo "$v" | grep -qq ' '; then
        printf '%s' "$v" >"$p" 2>/dev/null
    else
        printf '%s\n' "$v" >"$p" 2>/dev/null
    fi
    log "set $p: $cur -> $(cat "$p")"
}

# THP: FAKE4_REVERIFY.md Incident 1 — the fake-4 reference environment is
# enabled=always, shmem_enabled=always, defrag=madvise. Ubuntu defaults to
# madvise, and the repo's own record says "No data taken under madvise."
set_sysfs /sys/kernel/mm/transparent_hugepage/enabled      always
set_sysfs /sys/kernel/mm/transparent_hugepage/shmem_enabled always
set_sysfs /sys/kernel/mm/transparent_hugepage/defrag        madvise

# Automatic NUMA balancing fights MPOL_BIND, which is the whole born-local
# thesis. Disarm it.
if sysctl -w kernel.numa_balancing=0 >/dev/null 2>&1; then
    log "kernel.numa_balancing=0"
else
    warn "could not set kernel.numa_balancing"
fi

# Raise the map count: 96 workers x per-node rings + memfds.
CUR_MAP=$(sysctl -n vm.max_map_count)
if [ "$CUR_MAP" -lt 1048576 ]; then
    sysctl -w vm.max_map_count=1048576 >/dev/null 2>&1 && log "vm.max_map_count -> 1048576 (was $CUR_MAP)"
fi

# File descriptors: 96 workers, per-node indexer/scanner/fallow, orderer pipes.
ulimit -n 1048576 2>/dev/null && log "ulimit -n soft = $(ulimit -Sn)" || warn "could not raise ulimit -n"
ulimit -u 1048576 2>/dev/null && log "ulimit -u soft = $(ulimit -Su)" || warn "could not raise ulimit -u"

# CPU governor. Non-fatal: many bare-metal hosts expose no cpufreq knob.
if command -v cpupower >/dev/null 2>&1; then
    cpupower frequency-set -g performance >/dev/null 2>&1 && log "governor -> performance" || true
else
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq linux-tools-common linux-tools-generic \
        >/dev/null 2>&1 || true
    if command -v cpupower >/dev/null 2>&1; then
        cpupower frequency-set -g performance >/dev/null 2>&1 && log "governor -> performance" || true
    fi
fi
{
    echo "governor: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo '<n/a>')"
} >>"$EPYC_OUT/00_environment/tuning.txt"

# Drop page cache once, before anything measured.
sync
printf 3 >/proc/sys/vm/drop_caches 2>/dev/null && log "dropped page cache" || log "page cache left warm (no permission)"

# ------------------------------------------------------------------ python --
banner "10c python venv + competitor frameworks"

mkdir -p "$EPYC_DATA" "$EPYC_TMPDIR" "$EPYC_OUT"
if [ ! -x "$EPYC_VENV/bin/python" ]; then
    log "creating venv at $EPYC_VENV"
    python3 -m venv "$EPYC_VENV" >>"$EPYC_OUT/00_environment/venv.log" 2>&1 \
        || die "could not create venv at $EPYC_VENV"
fi
PY="$EPYC_VENV/bin/python"
PIP="$EPYC_VENV/bin/pip"

# Fail loudly and early if the derived paths are not sane. A venv path of
# "//venv" means the data dir was empty or unnormalised, and the resulting
# `python3 -m venv` failure is a very confusing way to learn that. Check before
# spending money on anything.
for _pair in "EPYC_DATA:$EPYC_DATA" "EPYC_VENV:$EPYC_VENV" \
             "EPYC_TMPDIR:$EPYC_TMPDIR" "EPYC_OUT:$EPYC_OUT"; do
    _name=${_pair%%:*}
    _val=${_pair#*:}
    if [ -z "$_val" ] || [ "$_val" = "/" ] || [ "${_val//\/\//}" != "$_val" ]; then
        die "$_name is not a usable path: '$_val'
   epyc/env/epyc.env is malformed, or was written by an older 00_preflight.sh
   that did not normalise the data dir. Re-run:
       bash epyc/00_preflight.sh $EPYC_OUT $EPYC_DATA
   (both arguments optional; preflight will auto-select the data dir)"
    fi
done
log "paths OK: data=$EPYC_DATA venv=$EPYC_VENV tmp=$EPYC_TMPDIR"

log "venv python: $($PY --version)"

# Pin to the versions the published baselines used (tokenize_study.md line 7:
# "Python 3.14. Ray 2.58, Polars 1.44.2, HF datasets 5.0.1."; ml_pipeline_study
# also records DuckDB 1.5.5). Try the exact pin; fall back to a compatible
# release, and ALWAYS record what actually got installed — an unpinned
# competitor silently invalidates every comparison table.
log "installing base python packages"
"$PIP" install -q --upgrade pip setuptools wheel >>"$EPYC_OUT/00_environment/pip.log" 2>&1
"$PIP" install -q numpy pandas >>"$EPYC_OUT/00_environment/pip.log" 2>&1 \
    || warn "numpy/pandas install failed"

PIP_VERSIONS="$EPYC_OUT/00_environment/PIP_VERSIONS.txt"
: >"$PIP_VERSIONS"
install_pinned() { # name exact_pin fallback_spec
    local name="$1" exact="$2" loose="$3"
    log "pip install $name ($exact)"
    if "$PIP" install -q "$exact" >>"$EPYC_OUT/00_environment/pip.log" 2>&1; then
        printf '%s\t%s (pinned)\n' "$name" "$("$PY" -c "import importlib.metadata as m;print(m.version('$name'))" 2>/dev/null || echo '?')" >>"$PIP_VERSIONS"
        return 0
    fi
    warn "exact pin $exact unavailable; falling back to $loose"
    if "$PIP" install -q "$loose" >>"$EPYC_OUT/00_environment/pip.log" 2>&1; then
        printf '%s\t%s (FELL BACK from %s — NOT the baseline version)\n' \
            "$name" "$("$PY" -c "import importlib.metadata as m;print(m.version('$name'))" 2>/dev/null || echo '?')" \
            "$exact" >>"$PIP_VERSIONS"
        return 0
    fi
    warn "could not install $name at all — its legs will be skipped by the probes"
    printf '%s\t<NOT INSTALLED>\n' "$name" >>"$PIP_VERSIONS"
    return 1
}

install_pinned polars  "polars==1.44.2"  "polars>=1.44,<2"
install_pinned duckdb  "duckdb==1.5.5"   "duckdb>=1.5,<2"
install_pinned datasets "datasets==5.0.1" "datasets>=5.0,<6"
install_pinned ray     "ray==2.58.0"    "ray>=2.58,<3"

{
    echo "python:  $("$PY" --version 2>&1)"
    echo "pip:     $("$PIP" --version 2>&1)"
    echo "mp start: $("$PY" -c 'import multiprocessing as m; print(m.get_start_method())' 2>&1)"
    echo "          (python>=3.14 defaults to forkserver on Linux; the lab box runs"
    echo "           3.14 so the baselines already have this. A bare top-level"
    echo "           Pool() with no __main__ guard WILL fail — see"
    echo "           python/benchmarks/README_misc.md)"
    echo
    echo "REFERENCE BOX (every published number): 28c Intel i9-7940X, single socket,"
    echo "  bash 5.3.9 / glibc 2.43 / Python 3.14.7 / gcc 16.2.1 / kernel 7.1.x,"
    echo "  28 workers, NUMA distance 10, THP enabled+shmem always."
    echo
    echo "REQUESTED COMPETITOR VERSIONS (tokenize_study.md / ml_pipeline_study.md):"
    echo "  Ray 2.58.0 | Polars 1.44.2 | DuckDB 1.5.5 | HF datasets 5.0.1 | pyarrow 25.0.1"
    echo
    echo "ACTUALLY INSTALLED:"
    cat "$PIP_VERSIONS"
} >"$EPYC_OUT/00_environment/PYTHON_STACK.txt"

"$PY" - <<'PY' | tee -a "$EPYC_OUT/00_environment/PYTHON_STACK.txt"
import importlib
for m in ("numpy", "pandas", "polars", "duckdb", "datasets", "ray", "pyarrow"):
    try:
        mod = importlib.import_module(m)
        print(f"  import {m:<10} OK   {getattr(mod, '__version__', '?')}")
    except Exception as e:
        print(f"  import {m:<10} MISSING ({type(e).__name__})")
PY

# ------------------------------------------------------------------- build --
banner "10d build the C substrate"

# The checkout may carry stale build artifacts from another machine. The
# makefile's own comment documents a FALSE-GREEN guard: make tracks timestamps,
# not command lines, so a pre-existing libforkrun.so from an rsync can be
# reported as "canary OK" while being stale. Wipe first, always.
log "removing any stale build artifacts"
rm -f "$EPYC_ROOT"/*.o "$EPYC_ROOT"/*.so "$EPYC_ROOT"/.canary-cc
rm -f "$EPYC_ROOT"/python/forkrun/*.so

MACHINE=$(gcc -dumpmachine 2>/dev/null || echo unknown)
log "target triplet: $MACHINE"
case "$MACHINE" in
    x86_64*) : ;;
    *) die "gcc targets $MACHINE but this checkout ships x86-64 loadables" ;;
esac

log "make canary (link check: zero bash linkage)"
if ! run_logged "$EPYC_OUT/02_build/canary.log" "make-canary" \
        make -C "$EPYC_ROOT" -f Makefile.substrate canary; then
    die "substrate canary FAILED — see $EPYC_OUT/02_build/canary.log"
fi

log "make python-substrate (libforkrun_python.so)"
if ! run_logged "$EPYC_OUT/02_build/substrate.log" "make-python-substrate" \
        make -C "$EPYC_ROOT" -f Makefile.substrate python-substrate; then
    die "python-substrate build FAILED — see $EPYC_OUT/02_build/substrate.log"
fi
SUB="$EPYC_ROOT/python/forkrun/libforkrun_python.so"
[ -f "$SUB" ] || die "libforkrun_python.so missing after build"
log "built $SUB ($(human "$(stat -c %s "$SUB")"))"
file "$SUB" | tee -a "$EPYC_OUT/00_environment/PYTHON_STACK.txt"

# ------------------------------------------------------------------ verify --
banner "10e verify both frontends"

banner "bash frontend: source frun.bash, load the embedded loadable, round-trip"
# This must be a clean, non-interactive shell. frun.bash self-extracts the
# x86-64 loadable from its embedded base64 and `enable`s it.
run_bash_logged "$EPYC_OUT/02_build/bash_bootstrap.log" "bash-bootstrap" '
    set -o pipefail
    cd '"$EPYC_ROOT"'
    source ./frun.bash
    echo "--- ring_version"
    ring_version
    echo "--- frun -V"
    frun -V
    echo "--- NUMA nodes visible to bash"
    cat /sys/devices/system/node/online
    echo "--- round-trip: 200000 lines, ordered, must be byte-exact"
    seq 200000 > /tmp/_epyc_rt.txt
    frun -k cat < /tmp/_epyc_rt.txt > /tmp/_epyc_rt.out
    cmp /tmp/_epyc_rt.txt /tmp/_epyc_rt.out && echo "ROUNDTRIP-OK"
    echo "--- ordered round-trip with substitution"
    frun -k -I echo "{ID}-x" < /tmp/_epyc_rt.txt | head -3
    echo "--- stats/NUMA telemetry smoke"
    frun --stats -k cat < /tmp/_epyc_rt.txt 2>&1 >/dev/null | head -20
    rm -f /tmp/_epyc_rt.txt /tmp/_epyc_rt.out
'
BASH_RC=$?
if [ "$BASH_RC" -ne 0 ]; then
    err "bash frontend smoke rc=$BASH_RC — see $EPYC_OUT/02_build/bash_bootstrap.log"
fi
grep -q 'ROUNDTRIP-OK' "$EPYC_OUT/02_build/bash_bootstrap.log" \
    || die "bash round-trip FAILED — the loadable is not working; stop and investigate"

banner "python frontend: import forkrun, run a plugin map"
run_logged "$EPYC_OUT/02_build/python_bootstrap.log" "python-bootstrap" env -C "$EPYC_ROOT" \
    PYTHONPATH="$EPYC_ROOT/python" FORKRUN_LIB="$SUB" "$PY" - <<'PYEOF'
import sys
sys.path.insert(0, "python")
import forkrun
print("forkrun.__version__      =", forkrun.__version__)
print("forkrun.__engine_version__=", forkrun.__engine_version__)
assert forkrun.__engine_version__ != "unknown", "engine version unavailable — substrate not loaded"
import tempfile, os
p = tempfile.mktemp(suffix=".txt", dir=os.environ.get("TMPDIR", "/tmp"))
with open(p, "w") as f:
    f.write("".join("line %06d\n" % i for i in range(200000)))
out = forkrun.map(lambda b: bytes(b.data).upper(), p, workers=os.cpu_count(),
                  order="index", nodes="auto")
txt = b"".join(out).decode()
assert txt == "".join("LINE %06d\n" % i for i in range(200000)), "round-trip mismatch"
print("PYTHON-ROUNDTRIP-OK  workers=%d nodes=auto out_lines=%d" % (os.cpu_count(), txt.count("\n")))
os.unlink(p)
PYEOF
PY_RC=$?
[ "$PY_RC" -eq 0 ] || die "python frontend smoke FAILED — see $EPYC_OUT/02_build/python_bootstrap.log"
grep -q 'PYTHON-ROUNDTRIP-OK' "$EPYC_OUT/02_build/python_bootstrap.log" \
    || die "python round-trip did not report OK"

# ------------------------------------------------------- worker-cap patch ----
banner "10f raise the benchmark worker cap (min(8, ...) -> min(\$EPYC_WORKERS_MAX, ...))"
# Ten benchmark modules hardcode `return min(8, os.cpu_count() or 4)`. On a
# 96-thread box that silently measures 8-way parallelism. _nworkers() is called
# at runtime, so rewriting the literal is sufficient. This is a deliberate,
# recorded deviation from the i9-7940X baselines (which ran these at 8 on a
# 28-thread box — i.e. their 8 WAS the cap; ours must not be).
PATCHED=()
while IFS= read -r f; do
    if grep -q 'return min(8, os\.cpu_count() or 4)' "$f"; then
        sed -i 's/return min(8, os\.cpu_count() or 4)/return min(int(os.environ.get("FORKRUN_BENCH_WORKERS_MAX", "8")), os.cpu_count() or 4)/' "$f"
        PATCHED+=("${f#"$EPYC_ROOT"/}")
    fi
done < <(grep -rl 'return min(8, os\.cpu_count() or 4)' "$EPYC_ROOT/python/benchmarks" 2>/dev/null)
{
    echo "Benchmark worker-cap patch applied by epyc/10_setup.sh"
    echo "  reason: core/ + ml/ benchmark modules hardcode min(8, cpu_count)."
    echo "          On this box that would measure 8 workers on $EPYC_NPROC threads."
    echo "  change: min(8, ...) -> min(\$FORKRUN_BENCH_WORKERS_MAX, ...), default 8."
    echo "  files:"
    for f in "${PATCHED[@]:-}"; do [ -n "$f" ] && echo "    $f"; done
} >"$EPYC_OUT/DEVIATIONS_worker_cap.txt"
log "patched ${#PATCHED[@]} file(s): ${PATCHED[*]:-none}"
export FORKRUN_BENCH_WORKERS_MAX="$EPYC_WORKERS_MAX"
echo "export FORKRUN_BENCH_WORKERS_MAX=$EPYC_WORKERS_MAX" >>"$EPYC_ENV_FILE"

# ------------------------------------------------- opencode supervisor ------
# An overnight run should not need a human for a missing package or a wiped
# substrate build. epyc/55_agent_supervise.sh drives the same harness under an
# opencode instance that triages stage failures. This block makes opencode
# available and verifies it can actually be used — the last thing you want is to
# discover at 3am that it was never authenticated.
banner "10g opencode agent supervisor (optional)"

AGENT_MODEL="${EPYC_AGENT_MODEL:-opencode/space-bunny-free}"
OC_PROMPT="$EPYC_DIR/AGENT_PROMPT.md"
OC_CONFIG="$EPYC_DIR/opencode.json"
AGENT_OK=0

if [ -n "${EPYC_SKIP_AGENT:-}" ]; then
    warn "EPYC_SKIP_AGENT set — not installing opencode"
else
    if ! command -v opencode >/dev/null 2>&1; then
        log "installing opencode (official installer)"
        if curl -fsSL https://opencode.ai/install | bash >"$EPYC_OUT/00_environment/opencode_install.log" 2>&1; then
            export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH"
            hash -r 2>/dev/null || true
        fi
    fi
    if ! command -v opencode >/dev/null 2>&1 && [ -x "$HOME/.opencode/bin/opencode" ]; then
        export PATH="$HOME/.opencode/bin:$PATH"
    fi
fi

if command -v opencode >/dev/null 2>&1; then
    OC_VER=$(opencode --version 2>/dev/null)
    log "opencode: $OC_VER"

    if opencode auth list >/dev/null 2>&1; then
        log "opencode is authenticated"
        if opencode models 2>/dev/null | grep -qxF "$AGENT_MODEL"; then
            log "agent model '$AGENT_MODEL' is available"
            AGENT_OK=1
        else
            warn "agent model '$AGENT_MODEL' is NOT in the opencode catalogue."
            warn "  space/bunny models that ARE available:"
            opencode models 2>/dev/null | grep -iE 'space|bunny' | sed 's/^/    /' >&2
            warn "  set EPYC_AGENT_MODEL=opencode/<id> and re-run, or continue with"
            warn "  EPYC_SKIP_AGENT=1 to run the harness unattended instead."
        fi
    else
        warn "opencode is installed but NOT authenticated — the agent cannot run."
        warn "  Authenticate interactively with:  opencode auth login"
        warn "  The harness still runs fine unattended; it just will not self-triage."
    fi

    for f in "$OC_PROMPT" "$OC_CONFIG"; do
        [ -f "$f" ] || warn "MISSING agent control file: $f (55_agent_supervise.sh will refuse to consult the agent)"
    done
    # Validate the config against opencode's own resolver so a syntax error is
    # found now rather than at the first triage attempt.
    if [ -f "$OC_CONFIG" ]; then
        if ( cd "$EPYC_ROOT" && opencode debug config >/dev/null 2>&1 ); then
            log "opencode.json resolves cleanly"
        else
            warn "opencode.json did not resolve (opencode debug config failed) — agent triage will not work"
        fi
    fi
else
    warn "opencode is not available. 55_agent_supervise.sh will run the harness"
    warn "  unattended instead of supervising it. Everything else is unaffected."
fi

{
    echo "opencode binary   : $(command -v opencode 2>/dev/null || echo '<not installed>')"
    echo "opencode version  : ${OC_VER:-n/a}"
    echo "agent model       : $AGENT_MODEL"
    echo "agent available   : $([ "$AGENT_OK" -eq 1 ] && echo yes || echo NO)"
    echo "agent prompt      : $OC_PROMPT"
    echo "agent config      : $OC_CONFIG"
    echo "supervisor script : $EPYC_DIR/55_agent_supervise.sh"
} >"$EPYC_OUT/00_environment/AGENT.txt"
cat "$EPYC_OUT/00_environment/AGENT.txt" | tee -a "$EPYC_OUT/00_environment/PYTHON_STACK.txt"
echo "EPYC_AGENT_MODEL=$AGENT_MODEL" >>"$EPYC_ENV_FILE"

# ------------------------------------------------- integrity manifest ------
# The agent's authority is declared in three independent places: the prompt it
# reads, the opencode permission config, and this manifest. The prompt can be
# ignored; the permission config can be edited; but a modified integrity-critical
# file is detected here and reported by 90_collect.sh. That redundancy is the
# point — a single layer of "please don't" is not a control.
banner "10h integrity manifest (tamper evidence for the agent's boundaries)"
INTEG="$EPYC_OUT/INTEGRITY.sha256"
{
    echo "# forkrun EPYC rental — integrity manifest"
    echo "# written by epyc/10_setup.sh at $(date -u '+%FT%TZ')"
    echo "#"
    echo "# Tier 1: the product under test, the benchmark sources, and the validator."
    echo "# The opencode agent is denied write access to all of these AND their"
    echo "# hashes are recorded here. epyc/90_collect.sh re-verifies every line and"
    echo "# reports any mismatch as a finding about the run, so a boundary violation"
    echo "# cannot pass silently even if the permission config was edited."
    echo "#"
    echo "# Tier 2: the harness's own stage scripts. The agent MAY edit these (a bug"
    echo "# in the harness is exactly the kind of shallow problem it should fix), so"
    echo "# they are hashed separately and reported as 'agent-modified harness' rather"
    echo "# than as tampering."
    echo
    echo "## TIER1 product+benchmark+validator"
    find "$EPYC_ROOT" -maxdepth 1 -type f \
        \( -name 'forkrun_ring.c' -o -name 'frun.bash' -o -name 'META' \
           -o -name 'forkrun_substrate.h' -o -name 'forkrun_shim.h' \
           -o -name 'forkrun_callschema.h' -o -name 'substratestubs.c' \
           -o -name 'Makefile.substrate' \) -print0 2>/dev/null \
        | sort -z | xargs -0 -r sha256sum
    find "$EPYC_ROOT/ring_loadables" -type f -name '*.h' -print0 2>/dev/null \
        | sort -z | xargs -0 -r sha256sum
    find "$EPYC_ROOT/python/forkrun" -type f -name '*.py' -print0 2>/dev/null \
        | sort -z | xargs -0 -r sha256sum
    find "$EPYC_ROOT/python/benchmarks" -type f \( -name '*.py' -o -name '*.c' -o -name '*.h' -o -name '*.sh' \) -print0 2>/dev/null \
        | sort -z | xargs -0 -r sha256sum
    for f in "$EPYC_ROOT/BENCHMARKS"/*.bash "$EPYC_ROOT/UNIT_TESTS"/test_*.sh; do
        [ -f "$f" ] && sha256sum "$f"
    done
    sha256sum "$EPYC_DIR/validate_cells.py"
    echo
    echo "## TIER2 harness stage scripts (agent-editable, changes reported)"
    sha256sum "$EPYC_DIR"/*.sh "$EPYC_DIR"/*.py 2>/dev/null
    echo
    echo "## TIER3 agent control plane (must never change)"
    sha256sum "$OC_PROMPT" "$OC_CONFIG" 2>/dev/null
} >"$INTEG" 2>/dev/null

TIER1_N=$(sed -n '/## TIER1/,/## TIER2/p' "$INTEG" | grep -c '^[0-9a-f]\{64\}')
TIER2_N=$(sed -n '/## TIER2/,/## TIER3/p' "$INTEG" | grep -c '^[0-9a-f]\{64\}')
log "integrity manifest: $TIER1_N Tier-1 files, $TIER2_N Tier-2 files -> $INTEG"
if [ "$TIER1_N" -lt 10 ]; then
    warn "only $TIER1_N Tier-1 files were hashed — expected many more."
    warn "  The manifest may be too weak to detect boundary violations."
fi
export FORKRUN_INTEGRITY_MANIFEST="$INTEG"
echo "EPYC_INTEGRITY_MANIFEST=\"$INTEG\"" >>"$EPYC_ENV_FILE"

banner "10 setup COMPLETE"
cat <<EOF
  bash   : $(bash --version | head -1)
  python : $("$PY" --version 2>&1)
  engine : $(grep -E '^VERSION' "$EPYC_ROOT/META" | cut -d' ' -f2)
  data   : $EPYC_DATA
  out    : $EPYC_OUT
  agent  : $([ "${AGENT_OK:-0}" = 1 ] && echo "opencode $OC_VER ready ($AGENT_MODEL)" || echo 'DISABLED (unattended run)')

Next (unattended, harness only):
  bash epyc/run_all.sh --hours 12

Next (overnight, agent supervises and self-triages stage failures):
  nohup bash epyc/55_agent_supervise.sh --hours 12 > /var/log/epyc-agent.log 2>&1 &
EOF
exit 0
