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

# --- topology expectations --------------------------------------------------
# The question this rental answers is "is forkrun correct on REAL MULTI-SOCKET
# NUMA". That is a property of the SOCKET topology, not of how many NUMA nodes
# the BIOS chose to expose. NPS1 (1 node/socket, 2 nodes total) is a perfectly
# good answer to it; NPS4 (4 nodes/socket, 8 total) is a stricter one.
#
# So the gate checks for a genuine multi-socket machine with a real cross-socket
# link, and REPORTS the node count as an experimental condition rather than
# demanding a particular NPS mode. Hardcoding "NPS4" here would have blocked the
# exact configuration Cherry shipped, which is a real 2-socket box that answers
# the primary question.
saygap
say "== NUMA TOPOLOGY SANITY CHECK =="
TOPO_OK=0
TOPO_REASONS=""
TOPO_NOTE=""

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
say "  F-NUMA1 meta-lifetime bound: 2048/$NODES = $(( 2048 / NODES )) chunks/node"
say "     (fake-4 baselines: 512. Fewer nodes = LOOSER bound = lower silent-loss risk.)"

# The gates that actually matter: is this real multi-socket hardware?
[ "$SOCKETS_SEEN" -ge 2 ];            expect "socket count" "$SOCKETS_SEEN" ">= 2 (a real multi-socket box)" $?
[ "$NODES" -ge 2 ];                   expect "NUMA node count" "$NODES" ">= 2 (a real NUMA pipeline)" $?
{ [ "${DIST_MIN_CROSS:-0}" -ge 20 ] || [ "$SOCKETS_SEEN" -lt 2 ]; }
                                       expect "cross-socket distance" "${DIST_MIN_CROSS:-n/a}" ">= 20 (32 on Milan)" $?
{ [ -z "$CMDLINE_DIST" ]; };          expect "kernel topology" "${CMDLINE_DIST:-real}" "not numa=fake=*" $?

if [ -z "$TOPO_REASONS" ]; then
    TOPO_OK=1
    say ""
    say "  REAL MULTI-SOCKET NUMA: YES  (${SOCKETS_SEEN} socket(s), ${NODES} node(s))"
    say "  The real-NUMA experiment (stages 41/43) is meaningful as designed."
    if [ "$NUMA_SHAPE" = "NPS1" ]; then
        TOPO_NOTE="NPS1 (1 NUMA node per socket). This is a genuine 2-socket topology and it
answers the primary question. Two consequences worth recording:
  * 'nodes=auto' selects one node per socket, so the UMA-vs-NUMA contrast is
    a clean socket-to-socket comparison.
  * It is a LOOSER F-NUMA1 configuration than the fake-4 baselines
    (2048/2 = 1024 chunks/node vs 512). A clean result here does NOT rule out
    F-NUMA1 at higher node counts; if a reboot into NPS2/NPS4 is ever possible,
    re-run stages 41 and 43 on it."
    say ""
    say "  Note: NPS1. Fewer nodes than the fake-4 baselines, so a lower chance of"
        say "  surfacing F-NUMA1 — but a clean 2-socket A/B, which is the primary question."
    elif [ "$NUMA_SHAPE" = "NPS2" ]; then
        TOPO_NOTE="NPS2 (2 NUMA nodes per socket, 4 total). This matches the fake-4 baseline
node count exactly, so results are directly comparable to every published
fake-4 number, while being real hardware with a real cross-socket distance
(32, not the fake-4 uniform 10)."
        say "  Note: NPS2 — node count matches the fake-4 baselines, so directly comparable."
    elif [ "$NUMA_SHAPE" = "NPS4" ]; then
        TOPO_NOTE="NPS4 (4 NUMA nodes per socket, 8 total). This is the tightest
F-NUMA1 configuration available (2048/8 = 256 chunks/node vs 512 under
numa=fake=4), and the one most likely to surface a stalled-node silent-loss
bug. Note it is NOT node-count-comparable to the fake-4 baselines."
        say "  Note: NPS4 — tightest F-NUMA1 configuration (256 chunks/node)."
    fi
else
    say ""
    say "  REAL MULTI-SOCKET NUMA: NO"
    say "  Deviations:$TOPO_REASONS"
    say ""
    say "  Stages 41 and 43 (the real-NUMA experiment) will REFUSE to run."
    say "  Options:"
    say "    a) fix the topology and re-run preflight, or"
    say "    b) accept it and run with EPYC_NUMA_ACK=1 (recorded as a limitation), or"
    say "    c) --skip 41_bench_numa5m,43_bench_ml20m and keep everything else."
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
# Pick the largest real, writable filesystem for the ~56 GB of datasets.
#
# This has to be robust, because a wrong pick costs real money: pointing the
# datasets at `/dev/shm` would silently consume RAM, and pointing them at a
# 500 MB boot partition would OOM the run two hours in. The previous version
# filtered by POSITIONAL columns and tested the mount point against filesystem
# TYPE names (dead code), and fell back to "/" with no warning when the awk
# matched nothing — which produced EPYC_DATA="/" and then EPYC_VENV="//venv".
#
# Use NAMED output columns, filter on the real fstype, and verify the result.
if [ -n "${2:-}" ]; then
    EPYC_DATA="$2"
elif [ -n "${EPYC_DATA:-}" ]; then
    : # caller already chose
else
    EPYC_DATA=$(df -B1 --output=source,fstype,size,target 2>/dev/null \
        | awk -F'[[:space:]]+' '
            NR==1 { next }
            NF >= 4 {
                src=$1; fst=$2; sz=$3; tgt=$4
                # real filesystems only — tmpfs/devtmpfs/overlay are RAM or
                # read-only, never a place to put 56 GB of benchmark corpora
                if (fst ~ /^(tmpfs|devtmpfs|ramfs|overlay|efivarfs|squashfs)$/) next
                # pseudo-filesystems by mount point
                if (tgt ~ /^\/(run|dev|proc|sys|tmp|boot)(\/|$)/) next
                if (sz !~ /^[0-9]+$/) next
                if (sz > best) { best=sz; chosen=tgt; how=src }
            }
            END {
                if (chosen == "") { print "NONE"; exit }
                print chosen
            }')
    if [ "$EPYC_DATA" = "NONE" ] || [ -z "$EPYC_DATA" ]; then
        # Do NOT silently fall back. Say so, pick /, and let the writability
        # check below surface it immediately.
        warn "could not identify a data filesystem from df; falling back to /"
        warn "  pass an explicit path:  bash epyc/00_preflight.sh <out_dir> <data_dir>"
        EPYC_DATA="/"
    fi
fi

# Normalise: strip trailing slashes so "/" + "/venv" cannot become "//venv".
while [ "${EPYC_DATA%/}" != "$EPYC_DATA" ] && [ "$EPYC_DATA" != "/" ]; do
    EPYC_DATA="${EPYC_DATA%/}"
done

# Verify it is usable BEFORE anything writes 56 GB to it. Cheap, and it turns a
# failure two hours into the run into a failure in the first minute.
say ""
say "data directory  : $EPYC_DATA"
say "output directory: $EPYC_OUT"
if mkdir -p "$EPYC_DATA" 2>/dev/null; then
    if [ -w "$EPYC_DATA" ]; then
        AVAIL=$(df -B1 --output=avail "$EPYC_DATA" 2>/dev/null | tail -1 | tr -cd '0-9')
        say "  writable      : yes"
        say "  free space    : ${AVAIL:-unknown} bytes ($(human "${AVAIL:-0}"))"
        say "  filesystem    : $(df -hT "$EPYC_DATA" 2>/dev/null | tail -1)"
        # The datasets need ~56 GB; the 20M pool/executor legs also want the
        # page cache to hold them, so headroom well beyond the raw total helps.
        if [ -n "$AVAIL" ] && [ "$AVAIL" -lt 80000000000 ]; then
            gate_warn "only $(human "$AVAIL") free on $EPYC_DATA; the harness wants >= 80 GB"
            gate_warn "  Datasets alone are ~56 GB. Pass a different path as argument 2."
        fi
    else
        gate_fatal "$EPYC_DATA is not writable by the current user"
    fi
else
    gate_fatal "cannot create $EPYC_DATA"
fi

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

# Derive child paths with a trailing-slash-safe join.
#   ${EPYC_DATA%/}/venv   "/"       -> /venv      (NOT //venv)
#                         "/data"   -> /data/venv
#                         "/data/"  -> /data/venv
# This is the actual defect behind the earlier "could not create venv at
# //venv": the data dir was correctly "/" all along — it is the largest real
# filesystem on a normal single-volume box — and "$EPYC_DATA/venv" simply does
# not join correctly when the base is the filesystem root.
EPYC_VENV_PATH="${EPYC_DATA%/}/venv"
EPYC_TMP_PATH="${EPYC_DATA%/}/tmp"
HF_CACHE_PATH="${EPYC_DATA%/}/hf_cache"
HF_HOME_PATH="${EPYC_DATA%/}/hf_home"

# ---------------------------------------------------------------- write env --
ENVF="$EPYC_DIR/env/epyc.env"
cat >"$ENVF" <<EOF
# Generated by epyc/00_preflight.sh on $(date -u '+%Y-%m-%dT%H:%M:%SZ') — do not edit by hand.
EPYC_ROOT="$EPYC_ROOT"
EPYC_OUT="$EPYC_OUT"
EPYC_DATA="$EPYC_DATA"
EPYC_VENV="$EPYC_VENV_PATH"
EPYC_TMPDIR="$EPYC_TMP_PATH"
EPYC_HF_CACHE="$HF_CACHE_PATH"
EPYC_HF_HOME="$HF_HOME_PATH"
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
EPYC_TOPOLOGY_NOTE="$(printf '%s' "$TOPO_NOTE")"
EPYC_TOPOLOGY_EXPECTED="real multi-socket (>=2 sockets, >=2 nodes, real cross-socket link)"
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
