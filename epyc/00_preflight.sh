#!/usr/bin/env bash
# epyc/00_preflight.sh — detect the machine, record it, and decide whether to run.
#
# This is the only stage that must succeed for anything else to be meaningful.
# It writes epyc/env/epyc.env (sourced by every later stage) and a full
# environment transcript under $EPYC_OUT/00_environment/.
#
#   bash epyc/00_preflight.sh [OUTPUT_DIR] [DATA_DIR]
#
# Overrides:  EPYC_OUT=<dir>  EPYC_DATA=<dir>

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"

EPYC_OUT="${1:-${EPYC_OUT:-$EPYC_ROOT/epyc-rental-out}}"
mkdir -p "$EPYC_OUT/00_environment" "$EPYC_DIR/env" "$EPYC_DIR/state"

ENVLOG="$EPYC_OUT/00_environment/PREFLIGHT.txt"
: >"$ENVLOG"
say() { printf '%s\n' "$*" | tee -a "$ENVLOG"; }
saygap() { say "------------------------------------------------------------"; }

banner "EPYC rental preflight"

# ---------------------------------------------------------------- identity --
saygap
say "== identity =="
say "date-utc        : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
say "hostname        : $(hostname)"
say "kernel          : $(uname -r)"
say "arch            : $(uname -m)"
say "distro          : $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
DISTRO=$(. /etc/os-release 2>/dev/null && echo "${VERSION_ID:-?} ${VERSION_CODENAME:-?}")
say "distro id       : $DISTRO"
UBUNTU_VER=$(. /etc/os-release 2>/dev/null && echo "${VERSION_ID:-}")
case "$UBUNTU_VER" in
    26.04|26.10|"")
        : ;;
    *)
        warn "tested on Ubuntu 26.04. You are on '${UBUNTU_VER:-unknown}'."
        warn "  Supported in principle (the gates below are absolute, not version-locked),"
        warn "  but any result is off-reference. It will be recorded in ENVIRONMENT.md."
        ;;
esac
say "model name      : $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
say "virt            : $(systemd-detect-virt 2>/dev/null || echo unknown)"
say "uptime          : $(uptime -p 2>/dev/null || uptime)"

# ---------------------------------------------------------------- topology --
saygap
say "== cpu topology =="
NPROC=$(nproc)
SOCKETS=$(lscpu 2>/dev/null | awk -F: '/^Socket\(s\)/{gsub(/ /,"",$2);print $2}')
CPS=$(lscpu 2>/dev/null | awk -F: '/^Core\(s\) per socket/{gsub(/ /,"",$2);print $2}')
TPC=$(lscpu 2>/dev/null | awk -F: '/^Thread\(s\) per core/{gsub(/ /,"",$2);print $2}')
SOCKETS=${SOCKETS:-1}; CPS=${CPS:-$NPROC}; TPC=${TPC:-1}
PHYS=$(( SOCKETS * CPS ))
say "nproc (logical) : $NPROC"
say "sockets         : $SOCKETS"
say "cores/socket    : $CPS"
say "threads/core    : $TPC"
say "physical cores  : $PHYS"
lscpu 2>/dev/null | grep -E '^(CPU\(s\)|On-line|Thread|Core|Socket|NUMA node\(s\)|NUMA node[0-9])' | sed 's/^/  lscpu| /' | tee -a "$ENVLOG"

NODES_ONLINE="$(cat /sys/devices/system/node/online 2>/dev/null || echo 0)"
NODES=$(python3 - "$NODES_ONLINE" <<'PY' 2>/dev/null || echo 1
import sys
s = sys.argv[1].strip()
n = set()
for tok in s.split(","):
    tok = tok.strip()
    if not tok:
        continue
    if "-" in tok:
        a, b = tok.split("-", 1)
        n.update(range(int(a), int(b) + 1))
    else:
        n.add(int(tok))
print(len(n))
PY
)
NODES=${NODES:-1}
say "numa online     : $NODES_ONLINE  (parsed node count: $NODES)"

saygap
say "== NUMA distance matrix (drives forkrun's per-node-pair steal threshold) =="
# forkrun_ring.c:2711-2717 builds a threshold for EVERY (source,dest) node pair:
#     thresh = 1 + dist/10, floored at 2
# So there is no single "the" distance. On a 2-socket NPS4 EPYC the matrix is
# typically
#     10 12 12 12 32 32 32 32
#     12 10 12 12 32 32 32 32
#     ...
# i.e. 10 self, 12 to a sibling CCD on the same socket, 32 across sockets. The
# threshold is therefore 2 within a socket and 4 across it, and cross-socket
# stealing is charged double intra-socket stealing. Report the whole matrix and
# derive the interesting values from it, rather than picking one column and
# calling it "the" cross-node distance.
DIST_MATRIX=""
DIST_MIN_REMOTE=0      # nearest DISTINCT node (could be same socket)
DIST_MIN_CROSS=0       # nearest node on a DIFFERENT socket
DIST_MAX=0
NODE_SOCKETS=""        # "0:0 1:0 2:0 3:0 4:1 ..."
NODE_IDS=""

for f in /sys/devices/system/node/node*/distance; do
    [ -e "$f" ] || continue
    nd=$(basename "$(dirname "$f")" | sed 's/^node//')
    NODE_IDS="$NODE_IDS $nd"
    row=$(tr -s ' ' <"$f")
    DIST_MATRIX="$DIST_MATRIX$nd|$row
"
    say "  node$nd: $row"
done
# Normalise to single-space-separated. `tr -d ' '` would collapse "0 1 2 3" into
# the single token "0123" and every per-node lookup would then miss.
NODE_IDS=$(printf '%s\n' $NODE_IDS | tr '\n' ' ' | sed 's/^ *//;s/ *$//')

# Map each NUMA node to its physical socket by reading the first CPU in its
# cpulist and asking sysfs which package that CPU is on. Pure sysfs, so it does
# not depend on the lscpu version's --extended support. This is what lets us
# separate "sibling CCD, same socket" from "other socket".
first_cpu_of_node() { # <node>
    tr ',' '\n' <"/sys/devices/system/node/node$1/cpulist" 2>/dev/null \
        | head -1 | sed 's/-.*//'
}
for nd in $NODE_IDS; do
    cpu=$(first_cpu_of_node "$nd")
    sock=$(cat "/sys/devices/system/cpu/cpu${cpu}/topology/physical_package_id" 2>/dev/null)
    NODE_SOCKETS="$NODE_SOCKETS${NODE_SOCKETS:+ }$nd:${sock:-?}"
done
say "  node->socket: $NODE_SOCKETS"

# Derive the interesting distances by walking node0's row.
sock_of() { echo "$NODE_SOCKETS" | tr ' ' '\n' | awk -v n="$1" -F: '$1==n{print $2}'; }
N0_SOCK=$(sock_of "${NODE_IDS%% *}")
NODE0_ROW=$(echo "$DIST_MATRIX" | awk -F'|' -v n="${NODE_IDS%% *}" '$1==n{print $2}')
for nd in $NODE_IDS; do
    [ "$nd" = "${NODE_IDS%% *}" ] && continue
    # Column k in node0's distance row corresponds to the k-th node in
    # NODE_IDS (1-based), because SLIT rows are ordered by node id. Do NOT
    # subtract one: on a uniform matrix (numa=fake=4, every distance 10) the
    # off-by-one is invisible, and only a mixed matrix like 2S/NPS4
    # (10 12 12 12 32 32 32 32) exposes it.
    k=$(printf '%s\n' $NODE_IDS | grep -n "^$nd$" | cut -d: -f1)
    d=$(printf '%s' "$NODE0_ROW" | awk -v k="$k" '{print $k}')
    [ -n "$d" ] || continue
    [ "$d" -gt "$DIST_MAX" ] && DIST_MAX=$d
    if [ "$DIST_MIN_REMOTE" -eq 0 ] || [ "$d" -lt "$DIST_MIN_REMOTE" ]; then
        DIST_MIN_REMOTE=$d
    fi
    nd_sock=$(sock_of "$nd")
    if [ -n "$nd_sock" ] && [ "$nd_sock" != "$N0_SOCK" ]; then
        if [ "$DIST_MIN_CROSS" -eq 0 ] || [ "$d" -lt "$DIST_MIN_CROSS" ]; then
            DIST_MIN_CROSS=$d
        fi
    fi
done
[ "$DIST_MAX" -eq 0 ] && DIST_MAX=$DIST_MIN_REMOTE

thr() { # 1 + d/10, floored at 2, exactly as forkrun_ring.c computes it
    local t=$(( 1 + ${1:-0} / 10 ))
    [ "$t" -lt 2 ] && t=2
    printf '%s' "$t"
}

SOCKETS_SEEN=$(echo "$NODE_SOCKETS" | tr ' ' '\n' | cut -d: -f2 | sort -u | grep -c .)
if [ "$NODES" -le 1 ]; then
    DIST_MIN_REMOTE=0; DIST_MIN_CROSS=0; DIST_MAX=0
fi
NUMA_SHAPE="UMA"
if [ "$NODES" -gt 1 ]; then
    if [ "$SOCKETS_SEEN" -le 1 ]; then
        NUMA_SHAPE="SINGLE-SOCKET-${NODES}NODE"
    elif [ "$NODES" -eq "$SOCKETS_SEEN" ]; then
        NUMA_SHAPE="NPS1"
    elif [ $(( NODES / SOCKETS_SEEN )) -eq 2 ]; then
        NUMA_SHAPE="NPS2"
    elif [ $(( NODES / SOCKETS_SEEN )) -eq 4 ]; then
        NUMA_SHAPE="NPS4"
    elif [ $(( NODES / SOCKETS_SEEN )) -eq 8 ]; then
        NUMA_SHAPE="NPS8"
    else
        NUMA_SHAPE="OTHER"
    fi
fi

say ""
say "  sockets seen         : $SOCKETS_SEEN"
say "  topology shape       : $NUMA_SHAPE"
say "  self distance        : 10"
say "  nearest other node   : ${DIST_MIN_REMOTE:-n/a}  -> base steal threshold $(thr "$DIST_MIN_REMOTE")"
say "  nearest CROSS-socket : ${DIST_MIN_CROSS:-n/a}  -> base steal threshold $(thr "$DIST_MIN_CROSS")"
say "  maximum distance     : ${DIST_MAX:-n/a}  -> base steal threshold $(thr "$DIST_MAX")"
say ""
say "  NOTE: forkrun builds a threshold for EVERY (src,dst) node pair, not one"
say "  global value. On this box a worker on node0 charges threshold"
say "  $(thr "$DIST_MIN_REMOTE") to steal from a same-socket node and $(thr "$DIST_MIN_CROSS") from a node on the other socket."
say "  Compare against the reference box's uniform distance 10 (numa=fake=4), where"
say "  EVERY pair was charged 2 — so fake-4 measurements are pessimistic for"
say "  cross-socket stealing and optimistic for intra-socket stealing at the same time."

CMDLINE_DIST=$(tr ' ' '\n' </proc/cmdline | grep -i '^numa=' || true)
say "  -> kernel numa= parameter: ${CMDLINE_DIST:-<none>}"

# ------------------------------------------------------------------- memory --
saygap
say "== memory =="
free -h | tee -a "$ENVLOG" >/dev/null
say "$(free -h | sed -n '1,2p' | tr '\n' ' ')"
say "$(free -h | awk '/^Swap:/{print "swap total: "$2" used: "$3}')"

# ------------------------------------------------------------------- disk ----
saygap
say "== filesystems =="
df -hT | tee -a "$ENVLOG" >/dev/null
df -hT | sed 's/^/  df| /' | tee -a "$ENVLOG"

# --------------------------------------------------------------- system tuning
saygap
say "== transparent hugepages =="
for knob in enabled shmem_enabled defrag; do
    p="/sys/kernel/mm/transparent_hugepage/$knob"
    [ -e "$p" ] && say "  $knob: $(cat "$p")"
done

saygap
say "== kernel tunables =="
for t in kernel.numa_balancing kernel.sched_autogroup_enabled vm.max_map_count; do
    say "  $t = $(sysctl -n "$t" 2>/dev/null || echo '<unreadable>')"
done
say "  vm.overcommit_memory = $(sysctl -n vm.overcommit_memory 2>/dev/null || echo '?')"
say "  cgroup cpu.max = $(cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo '<none>')"
say "  governor (cpu0) = $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo '<no cpufreq>')"
say "  ulimit -n (soft/hard) = $(ulimit -Sn)/$(ulimit -Hn)"
say "  ulimit -u (soft/hard) = $(ulimit -Su)/$(ulimit -Hu)"

# ------------------------------------------------------------------ toolchain
saygap
say "== toolchain =="
for t in bash gcc make python3 pip3 git parallel numactl; do
    if command -v "$t" >/dev/null 2>&1; then
        say "  $t: $(command -v "$t")"
    else
        say "  $t: <MISSING>"
    fi
done
say "  bash:    ${BASH_VERSION:-?}"
say "  gcc:     $(gcc --version 2>/dev/null | head -1)"
say "  make:    $(make --version 2>/dev/null | head -1)"
say "  python3: $(python3 --version 2>/dev/null)"
say "  glibc:   $(getconf GNU_LIBC_VERSION 2>/dev/null || echo '?')"
say "  numactl: $(numactl --version 2>/dev/null || echo '<not installed>')"
command -v numactl >/dev/null 2>&1 && numactl --hardware 2>&1 | sed 's/^/  | /' | tee -a "$ENVLOG"

# --- supported-platform matrix ---------------------------------------------
# The engine has only ever been measured on two userlands: the i9-7940X lab box
# (Fedora, bash 5.3, glibc 2.43, python 3.14, gcc 16) and Ubuntu 24.04 in CI
# (bash 5.2, glibc 2.39, python 3.12). Ubuntu 26.04 is neither, so say plainly
# how it relates to the reference rather than pretending it is verified.
saygap
say "== reference-platform matrix =="
say "  ROLE            BASH    GLIBC   PYTHON  GCC    NOTES"
say "  lab box         5.3.9   2.43    3.14.7  16.2   EVERY published number came from here (28c i9-7940X, 1 node)"
say "  Ubuntu 24.04    5.2.21  2.39    3.12.3  14     CI cells; bash 5.2 + glibc 2.39 explicitly 'fully verified'"
say "  THIS BOX        ${BASH_VERSION}  $(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')    $(python3 --version 2>/dev/null | awk '{print $2}')  $(gcc -dumpversion 2>/dev/null)   ${DISTRO:-?}"

# --- python multiprocessing start method ------------------------------------
# Python 3.14 changed the Linux default start method from fork to forkserver.
# The lab box runs 3.14, so the published baselines already have this property
# — but it is a real behavioural difference from 3.12, and
# python/benchmarks/README_misc.md records the failure mode: a bare top-level
# Pool(...) with no __main__ guard dies. Record it so a Pool leg that fails can
# be triaged against this rather than guessed at.
STARTMETHOD=$(python3 -c 'import multiprocessing as m; print(m.get_start_method())' 2>/dev/null || echo unknown)
say "  multiprocessing default start method: $STARTMETHOD"
if [ "$STARTMETHOD" = "forkserver" ]; then
    say "  (python >=3.14: matches the lab box, so baselines are consistent; but a"
    say "   bare top-level Pool() with no __main__ guard WILL fail — see"
    say "   python/benchmarks/README_misc.md)"
fi


# ------------------------------------------------------------------ repo -----
saygap
say "== forkrun checkout =="
say "  path:   $EPYC_ROOT"
say "  git:    $(git -C "$EPYC_ROOT" rev-parse --short HEAD 2>/dev/null || echo '<not a git checkout>')"
say "  META:   $(cat "$EPYC_ROOT/META" 2>/dev/null | tr '\n' ' ')"
say "  frun:   $(stat -c %s "$EPYC_ROOT/frun.bash" 2>/dev/null || echo '<missing>') bytes"
say "  engine: $(stat -c %s "$EPYC_ROOT/forkrun_ring.c" 2>/dev/null || echo '<missing>') bytes"
say "  dirty:  $(git -C "$EPYC_ROOT" status --porcelain 2>/dev/null | wc -l) modified path(s)"

# =============================================================== GO / NO-GO ==
banner "preflight gates"
FATAL=0
gate_fatal() { err  "FATAL: $*"; FATAL=1; }
gate_warn() { warn "WARN:  $*"; }

case "$(uname -m)" in
    x86_64) : ;;
    *) gate_fatal "only x86_64 is supported (frun.bash ships x86-64 loadables); found $(uname -m)" ;;
esac

VIRT=$(systemd-detect-virt 2>/dev/null)
# systemd-detect-virt prints "none" AND exits 1 on bare metal — that non-zero
# exit is not an error, it is how it says "no hypervisor". `|| echo unknown`
# would append to the real value, producing the two-line string "none\nunknown",
# which matches neither branch of the case below and aborts the run on the very
# bare-metal box this harness is for. Take the first line and treat an empty
# result as "could not determine", not as "virtual".
VIRT=$(printf '%s' "$VIRT" | head -1 | tr -d '[:space:]')
[ -n "$VIRT" ] || VIRT="undetermined"
case "$VIRT" in
    none) : ;;
    undetermined)
        gate_warn "systemd-detect-virt returned nothing; could not confirm this is bare metal."
        gate_warn "  Confirm by hand: lscpu | grep -i hypervisor  (an empty result is what you want)"
        ;;
    *)
        gate_fatal "running under hypervisor '$VIRT' — NUMA topology would be virtual. Benchmarking a VM is a benchmarking lie."
        ;;
esac
# Second opinion, from a source that does not depend on systemd.
HYP=$(grep -m1 -i '^hypervisor vendor' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')
if [ -n "$HYP" ]; then
    gate_fatal "/proc/cpuinfo reports 'hypervisor vendor: $HYP' — this is a guest VM."
fi

if [ -n "$CMDLINE_DIST" ]; then
    gate_fatal "kernel booted with '$CMDLINE_DIST' — this is a FAKE topology box, not real NUMA. Reboot without it."
fi

# glibc floor is 2.38 (the shipped x86-64 loadables max out at GLIBC_2.38 after
# the D-TLS rebuild; Ubuntu 24.04's 2.39 is the first distro above it).
#
# `getconf GNU_LIBC_VERSION` prints "glibc 2.43" — TWO numbers separated by a
# dot. `grep -oE '[0-9]+' | head -1` returns the FIRST one, "2", so a naive
# `[ "$x" -lt 38 ]` fires on glibc 2.43 and aborts the run on the very platform
# it was written for. Compare as a version, using dpkg's real comparator when
# available and an explicit major/minor split otherwise.
GLIBC_VER=$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')
if [ -z "$GLIBC_VER" ]; then
    gate_warn "could not determine the glibc version from getconf; skipping the 2.38 floor check"
elif command -v dpkg >/dev/null 2>&1 && dpkg --compare-versions "$GLIBC_VER" lt 2.38 2>/dev/null; then
    gate_fatal "glibc $GLIBC_VER < 2.38 — the shipped x86-64 loadables will not load"
else
    log "glibc $GLIBC_VER >= 2.38 (loadable floor OK)"
fi
BASH_MAJ=${BASH_VERSION%%.*}
BASH_MIN=$(echo "$BASH_VERSION" | cut -d. -f2)
if [ "$BASH_MAJ" -lt 4 ] || { [ "$BASH_MAJ" -eq 4 ] && [ "$BASH_MIN" -lt 4 ]; }; then
    gate_fatal "bash $BASH_VERSION < 4.4 (needs mapfile -d)"
fi

QUOTA=$(cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo "")
if [ -n "$QUOTA" ] && [ "$QUOTA" != "max 100000" ] && ! echo "$QUOTA" | grep -q '^max '; then
    gate_fatal "cgroup cpu.max='$QUOTA' — the CPU set is throttled; worker sweeps would measure the quota"
fi

if [ ! -f "$EPYC_ROOT/frun.bash" ]; then
    gate_fatal "frun.bash not found at $EPYC_ROOT — is this the forkrun checkout?"
fi

# --- topology expectations (warnings, not fatal: a 2-node box is still real) --
saygap
say "== NUMA TOPOLOGY SANITY CHECK =="
# The whole point of the rental is a real multi-node measurement. Discovering
# that Cherry booted the box in NPS1 (2 nodes) instead of NPS4 (8) after eight
# hours of benchmarking would waste the run, so make the topology an EXPLICIT,
# RECORDED experimental condition rather than something you notice afterwards.
#
# Expected 2-socket NPS4 EPYC (Milan/Zen3, 4 CCDs per socket):
#   sockets = 2, nodes = 8, self = 10, intra-socket = 12, cross-socket >= 30
# Nothing here is fatal by default. Set EPYC_NUMA_ACK=1 to acknowledge an
# unexpected topology and let stage 41 proceed; without it, stage 41 refuses.
TOPO_OK=0
TOPO_REASONS=""
expect() { # <label> <actual> <expected-desc> <test-rc>
    if [ "$4" -eq 0 ]; then
        say "  [ OK ] $1: $2"
    else
        say "  [!! ] $1: $2   (expected: $3)"
        TOPO_REASONS="$TOPO_REASONS
     - $1 is $2, expected $3"
    fi
}
say "  shape: $NUMA_SHAPE   sockets: $SOCKETS_SEEN   nodes: $NODES"
[ "$NODES" -ge 4 ];                                        expect "node count" "$NODES" ">= 4 (2S/NPS4 = 8)" $?
[ "$SOCKETS_SEEN" -ge 2 ];                                expect "socket count" "$SOCKETS_SEEN" ">= 2" $?
[ "$NUMA_SHAPE" = "NPS4" ];                                expect "topology shape" "$NUMA_SHAPE" "NPS4 (4 CCDs/socket)" $?
[ "${DIST_MIN_REMOTE:-0}" -ge 10 ];                        expect "self/remote distance" "${DIST_MIN_REMOTE:-0}" ">= 10" $?
{ [ "${DIST_MIN_CROSS:-0}" -ge 30 ] || [ "$NODES" -le 1 ]; }; expect "cross-socket distance" "${DIST_MIN_CROSS:-n/a}" ">= 30 (32 on Milan)" $?
if [ -z "$TOPO_REASONS" ]; then
    TOPO_OK=1
    say ""
    say "  TOPOLOGY MATCHES the expected 2S/NPS4 EPYC shape: YES"
    say "  The real-NUMA experiment (stages 41/43) is meaningful as designed."
else
    say ""
    say "  TOPOLOGY MATCHES the expected 2S/NPS4 EPYC shape: NO"
    say "  Deviations:$TOPO_REASONS"
    say ""
    if [ "${EPYC_NUMA_ACK:-0}" = "1" ]; then
        say "  EPYC_NUMA_ACK=1 set — proceeding with the unexpected topology."
        say "  This WILL be recorded in ENVIRONMENT.md as an experimental condition."
    else
        say "  Stages 41 and 43 (the real-NUMA experiment) will REFUSE to run."
        say "  Either:"
        say "    a) reboot into the expected NPS mode and re-run preflight, or"
        say "    b) acknowledge this topology and re-run with EPYC_NUMA_ACK=1, or"
        say "    c) leave it — a 2-node box is still real multi-socket NUMA, just a"
        say "       weaker version of the experiment. Everything else still runs."
        say "  The exact topology above is recorded in ENVIRONMENT.md regardless."
    fi
fi

if [ "$NODES" -ge 4 ]; then
    log "OK: $NODES NUMA nodes online — a genuine multi-node experiment."
else
    gate_warn "only $NODES NUMA node(s) online (expected 8 for 2-socket NPS4)."
    gate_warn "  Real 2-socket NUMA is still measured, but NPS4 (4 CCDs/socket) would give"
    gate_warn "  8 nodes and a much stronger born-local test. If you can reach the BIOS"
    gate_warn "  over IPMI/IP-KVM, enable NPS4/CcxAsNumaDomain and re-run 41_bench_numa5m.sh."
fi

if [ "$NODES" -ge 4 ]; then
    gate_warn "F-NUMA1 risk: $NODES nodes means META_RING_SIZE/2 (2048) splits $(( 2048 / NODES )) chunks/node."
    gate_warn "  Heavy-20M on many nodes is exactly where the ~25%-silent-loss bug lived"
    gate_warn "  (4 nodes). Stages 41/43 check valid/total on every row and will flag it."
fi

NB=$(sysctl -n kernel.numa_balancing 2>/dev/null || echo 0)
if [ "$NB" != "0" ]; then
    gate_warn "kernel.numa_balancing=$NB — automatic NUMA balancing will fight forkrun's MPOL_BIND."
    gate_warn "  10_setup.sh disables it; published baselines had it off."
fi

THP=$(cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || echo '?')
THPS=$(cat /sys/kernel/mm/transparent_hugepage/shmem_enabled 2>/dev/null || echo '?')
if ! echo "$THP" | grep -q '\[always\]'; then
    gate_warn "THP enabled=$THP (Ubuntu default is [madvise]). 10_setup.sh sets it to always;"
    gate_warn "  FAKE4_REVERIFY.md Incident 1 records 'No data taken under madvise'."
fi
if ! echo "$THPS" | grep -q '\[always\]'; then
    gate_warn "THP shmem_enabled=$THPS — this is the knob that matters for memfd. Setting to always."
fi

# --------------------------------------------------------------- data dir ----
if [ -n "${2:-}" ]; then
    EPYC_DATA="$2"
elif [ -n "${EPYC_DATA:-}" ]; then
    : # caller already chose
else
    EPYC_DATA=$(df -B1 --output=size,target 2>/dev/null \
        | awk 'NR>1 {t=$2; if (t ~ /^\/(run|dev|proc|sys|tmp)$/) next; if (t ~ /^(tmpfs|devtmpfs|overlay|udev)$/) next; if ($1>m) {m=$1; best=t}} END{print (best==""?"/":best)}')
fi
say ""
say "data directory  : $EPYC_DATA"
say "output directory: $EPYC_OUT"

# ------------------------------------------------------- derived parameters --
# Worker sweep. MUST start at >= $NODES: a workers<nodes run returns INCOMPLETE
# and is pathologically slow (measured ~2500s for one 1M cell under fake-4).
# See DOCS/INVARIANTS.md §17 and bench_numa_5m.py.
sweep() { # $1 = wanted comma list, min = NODES
    echo "$1" | tr ',' '\n' | awk -v min="$NODES" '
        {gsub(/ /,""); if ($1 ~ /^[0-9]+$/ && $1 >= min) print $1}' \
        | sort -n | uniq | paste -sd, -
}
# The "all logical cores" cell point, mirroring how 28 was used on the 28-thread i9.
W_ALL="$NPROC"
[ "$NPROC" -gt 128 ] && W_ALL=128
# Competitor matrices are the expensive ones — Ray, HF Datasets, Pool and
# Executor all cost 3-5 executions per worker point, and Ray alone is ~2h at
# 20M. Keep that sweep to 5 points. forkrun-only legs (which dominate the
# NUMA and 20M stages) get the full curve.
SWEEP_FAST="$(sweep "8,16,32,48,96")"
SWEEP_FULL="$(sweep "8,12,16,24,32,48,64,96")"
SWEEP_NUMA="$(sweep "8,16,32,48,96")"
WORKERS_MAX="$NPROC"

say ""
say "derived parameters:"
say "  EPYC_NPROC=$NPROC  EPYC_PHYS=$PHYS  EPYC_NODES=$NODES"
say "  EPYC_WORKERS_MAX=$WORKERS_MAX   (the 'all logical' cell point)"
say "  EPYC_SWEEP_FAST=$SWEEP_FAST    (competitor matrices)"
say "  EPYC_SWEEP_FULL=$SWEEP_FULL    (forkrun-only + core suite)"
say "  EPYC_SWEEP_NUMA=$SWEEP_NUMA    (numa_5m scaling sweep)"

# ---------------------------------------------------------------- write env --
ENVF="$EPYC_DIR/env/epyc.env"
cat >"$ENVF" <<EOF
# Generated by epyc/00_preflight.sh on $(date -u '+%Y-%m-%dT%H:%M:%SZ') — do not edit by hand.
EPYC_ROOT="$EPYC_ROOT"
EPYC_OUT="$EPYC_OUT"
EPYC_DATA="$EPYC_DATA"
EPYC_VENV="$EPYC_DATA/venv"
EPYC_TMPDIR="$EPYC_DATA/tmp"
EPYC_STATE="$EPYC_DIR/state"
EPYC_NPROC=$NPROC
EPYC_PHYS=$PHYS
EPYC_SOCKETS=$SOCKETS
EPYC_NODES=$NODES
EPYC_NODES_ONLINE="$NODES_ONLINE"
# Full SLIT matrix + the derived values. There is deliberately no single
# "XNODE_DIST": forkrun charges a threshold per (src,dst) node PAIR, and on a
# 2-socket NPS4 box that is 2 within a socket and 4 across it.
EPYC_DIST_MATRIX="$(printf '%s' "$DIST_MATRIX" | tr '\n' ';')"
EPYC_NODE_SOCKETS="$NODE_SOCKETS"
EPYC_NUMA_SHAPE="$NUMA_SHAPE"
EPYC_DIST_SELF=10
EPYC_DIST_MIN_REMOTE=${DIST_MIN_REMOTE:-0}
EPYC_DIST_MIN_CROSS=${DIST_MIN_CROSS:-0}
EPYC_DIST_MAX=${DIST_MAX:-0}
EPYC_THRESH_MIN_REMOTE=$(thr "$DIST_MIN_REMOTE")
EPYC_THRESH_MIN_CROSS=$(thr "$DIST_MIN_CROSS")
EPYC_THRESH_MAX=$(thr "$DIST_MAX")
EPYC_TOPOLOGY_OK=$TOPO_OK
EPYC_TOPOLOGY_REASONS="$(printf '%s' "$TOPO_REASONS" | tr '\n' ';')"
EPYC_TOPOLOGY_EXPECTED="${EPYC_TOPOLOGY_EXPECTED:-2S/NPS4}"
EPYC_WORKERS_MAX=$WORKERS_MAX
EPYC_SWEEP_FAST="$SWEEP_FAST"
EPYC_SWEEP_FULL="$SWEEP_FULL"
EPYC_SWEEP_NUMA="$SWEEP_NUMA"
EPYC_MODEL_NAME="$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//')"
EPYC_DISTRO="$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
EPYC_DISTRO_ID="${UBUNTU_VER:-unknown}"
EPYC_PYTHON_VERSION="$(python3 --version 2>/dev/null | awk '{print $2}')"
EPYC_MP_STARTMETHOD="$STARTMETHOD"
EPYC_GCC_VERSION="$(gcc -dumpversion 2>/dev/null)"
EPYC_GLIBC_VERSION="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')"
EPYC_BASH_VERSION="$BASH_VERSION"
EPYC_KERNEL="$(uname -r)"
EPYC_GIT_SHA="$(git -C "$EPYC_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
EOF
say ""
say "wrote $ENVF"

# --------------------------------------------------------------- run_logged --
: >"$EPYC_OUT/CMD_TIMINGS.tsv"
: >"$EPYC_OUT/STAGE_TIMINGS.tsv"
: >"$EPYC_OUT/TEST_TALLIES.txt"
cp "$ENVLOG" "$EPYC_OUT/00_environment/preflight_latest.txt" 2>/dev/null || true

if [ "$FATAL" -ne 0 ]; then
    banner "PREFLIGHT FAILED — do not proceed"
    err "one or more fatal gates tripped; see $ENVLOG"
    exit 1
fi

banner "PREFLIGHT PASSED"
say "Run next:  bash epyc/10_setup.sh"
say "Then:     bash epyc/run_all.sh --hours 12"
exit 0
