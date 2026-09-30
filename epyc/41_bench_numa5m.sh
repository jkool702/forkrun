#!/usr/bin/env bash
# epyc/41_bench_numa5m.sh — THE REAL-NUMA EXPERIMENT.
#
#   bash epyc/41_bench_numa5m.sh
#
# Everything else in this harness re-measures something that was already
# measured on an i9-7940X. This stage measures the thing that has NEVER been
# measured on real multi-socket hardware (RELEASE_v3.6.0.md §6: "Real
# multi-socket hardware (where born-local placement pays) remains unmeasured —
# the standing prediction is NUMA at parity-or-better there, unproven.").
#
# Two things this box changes relative to every published number:
#
#  1. NODE COUNT. 8 real nodes (NPS4, 4 CCDs/socket) vs 4 fake (numa=fake=4)
#     and 1 UMA. META_RING_SIZE is 4096, so the ingest meta-lifetime bound
#     (INVARIANTS §17 / F-NUMA1) is 2048/8 = 256 chunks per node — the tightest
#     configuration the engine has ever run under. F-NUMA1 was discovered as a
#     ~25%-silent-loss bug at 4 nodes on heavy-20M. That cell is the single
#     most interesting thing this rental can produce, either way.
#
#  2. DISTANCE. There is no single "the" distance: forkrun charges a steal
#     threshold per (src,dst) node PAIR, thresh = 1 + dist/10, floored at 2
#     (forkrun_ring.c:2711-2717). On 2-socket NPS4 that is 2 for a sibling CCD
#     on the same socket (distance 12) and 4 across the socket link (32). So
#     "fake-NUMA is a worst case" does not transfer cleanly: fake-4's uniform
#     distance 10 charged every pair the same 2, which is pessimistic for
#     cross-socket stealing and optimistic for intra-socket stealing at the
#     same time. We measure the matrix instead of assuming a verdict.
#
# --nodes semantics, which are easy to misread (_numa.py:95-136):
#   1        -> UMA (one logical node, no pinning)
#   @N       -> N LOGICAL nodes cycling the physicals: picked =
#               [online[i % len(online)] for i in range(N)]. On an 8-node NPS4
#               box, @2 = physicals {0,1} and @4 = {0,1,2,3} — which, under
#               Linux's socket-ordered node ids, are BOTH WITHIN SOCKET 0.
#   auto     -> every online physical node, i.e. all 8, spanning both sockets.
# So this is NOT "1 node vs 2 nodes vs 4 nodes vs 8 nodes"; it is a locality
# ladder: UMA -> intra-socket-2 -> intra-socket-4 -> both sockets. The
# interesting result is where the curve bends, i.e. how much of the locality
# benefit is intra-socket and how much needs the socket hop.
#
# --nodes uses @N (forced logical) and never a bare int > 1: _numa.py:109
# raises ValueError for an int above the online count ("silently running UMA
# after nodes=N was requested would be a benchmarking lie").

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

OUTD="$EPYC_OUT/20_benchmarks/numa5m"
NUMA5="$EPYC_DATA/numa5"
RECORDS=5000000
SWEEP="${EPYC_SWEEP_NUMA}"
WMAX="$EPYC_WORKERS_MAX"
TRIALS="${EPYC_TRIALS_NUMA:-2}"
DOCS="${EPYC_TOKENIZE_DOCS:-2000000}"

# Topology variants. On 8 nodes these are eight distinct real subsets, which is
# exactly the axis fake-4 could not resolve. "@2" and "auto" coincide on a
# 2-node box; on 8 they do not. See the header note for what @2/@4 actually
# select (under NPS4 they are BOTH intra-socket, not a socket count).
NODES="1,@2,@4,auto"

mkdir -p "$OUTD"
cd "$EPYC_ROOT" || die "no repo root"

banner "41 bench_numa_5m — real multi-socket NUMA"
log "nodes online   : $EPYC_NODES_ONLINE ($EPYC_NODES nodes, shape $EPYC_NUMA_SHAPE)"
log "node->socket   : $EPYC_NODE_SOCKETS"
log "distance matrix: $(printf '%s' "${EPYC_DIST_MATRIX:-<unreadable>}" | tr ';' '\n' | head -1 | sed 's/^/  /') ..."
log "  nearest other node  : ${EPYC_DIST_MIN_REMOTE:-?}  -> steal threshold ${EPYC_THRESH_MIN_REMOTE:-?} (sibling CCD)"
log "  nearest CROSS-socket: ${EPYC_DIST_MIN_CROSS:-?}  -> steal threshold ${EPYC_THRESH_MIN_CROSS:-?} (socket hop)"
log "  max distance        : ${EPYC_DIST_MAX:-?}  -> steal threshold ${EPYC_THRESH_MAX:-?}"
log "node variants  : $NODES"
log "  ^ ladder: UMA -> 2 intra-socket nodes -> 4 intra-socket -> all $EPYC_NODES across both sockets"
log "cell workers   : $WMAX"
log "scaling sweep  : $SWEEP   (min >= $EPYC_NODES: below that, a node's ring is never claimed)"
log "tmpdir         : $NUMA5"

if [ "$EPYC_NODES" -lt 2 ]; then
    banner "41 SKIPPED — this box is UMA"
    err "only $EPYC_NODES node online: the real-NUMA experiment is vacuous here."
    err "Nothing in this stage would tell you anything. Skipping deliberately."
    stage_skip "41_bench_numa5m" "box is UMA ($EPYC_NODES node)"
    exit 0
fi

# Topology acknowledgment gate (set by 00_preflight). The sanity check there
# flagged this machine as not matching the expected 2S/NPS4 shape. A weaker
# topology still yields a real measurement, but it is NOT the experiment the
# tables claim, so it must be an explicit decision rather than a surprise
# discovered in the write-up eight hours later.
if [ "${EPYC_NUMA_ACK:-0}" != "1" ]; then
    if [ "${EPYC_TOPOLOGY_OK:-1}" != "1" ] 2>/dev/null; then
        banner "41 REFUSING — topology does not match the expected 2S/NPS4 shape"
        err "00_preflight.sh recorded shape=$EPYC_NUMA_SHAPE with $EPYC_NODES node(s)"
        err "across $EPYC_SOCKETS socket(s), cross-socket distance ${EPYC_DIST_MIN_CROSS:-none}."
        err ""
        err "Stage 43 (the 20M F-NUMA1 probe) has the same guard and will also refuse."
        err "Options:"
        err "  a) reboot into the expected NPS mode, then re-run 00_preflight.sh"
        err "  b) accept this topology:  EPYC_NUMA_ACK=1 bash epyc/run_all.sh ..."
        err "     (it will be recorded in ENVIRONMENT.md as a stated limitation)"
        err "  c) skip this stage:     --skip 41_bench_numa5m,43_bench_ml20m"
        exit 1
    fi
fi

# Guard the dataset.
for v in light medium heavy; do
    f="$NUMA5/ml_${v}_${RECORDS}.jsonl"
    [ -f "$f" ] || die "missing $f — run epyc/20_datagen.sh"
    n=$(wc -l <"$f")
    [ "$n" = "$RECORDS" ] || die "$f has $n lines, expected $RECORDS"
    log "ok $(basename "$f") : $n lines, $(human "$(stat -c %s "$f")")"
done

RC=0

# ------------------------------------------------------------- part A -------
# Part A = the main steady-state grid (C plugin + Python UDF across node
# variants) plus the per-worker scaling sweep on a 1M medium corpus.
banner "41a part A — steady state across node variants + worker scaling"
if deadline_ok 5400; then
    if run_logged "$OUTD/part_a.log" "numa5m-part-a" \
        python3 python/benchmarks/ml/bench_numa_5m.py \
            --records "$RECORDS" \
            --variants light,medium,heavy \
            --workers "$WMAX" \
            --sweep-workers "$SWEEP" \
            --trials "$TRIALS" \
            --nodes "$NODES" \
            --parts a \
            --tmpdir "$NUMA5" \
            --csv "$OUTD/numa5m_part_a.csv"; then
        log "part A done"
    else
        err "part A FAILED — see $OUTD/part_a.log"
        RC=1
    fi
else
    stage_skip "41_bench_numa5m_a" "deadline"
fi

# ------------------------------------------------------------- part B -------
# Part B = tokenize at --docs + the spawn (`tr`) leg + two C-loop capability
# gates. Note c_spawn_loop is UMA-only by design, so the multi-node spawn cell
# records a gate message rather than a rate — that is expected, not a failure.
banner "41b part B — tokenize + spawn"
if deadline_ok 3600; then
    if run_logged "$OUTD/part_b.log" "numa5m-part-b" \
        python3 python/benchmarks/ml/bench_numa_5m.py \
            --records "$RECORDS" \
            --workers "$WMAX" \
            --docs "$DOCS" \
            --nodes "$NODES" \
            --parts b \
            --tmpdir "$NUMA5" \
            --csv "$OUTD/numa5m_part_b.csv"; then
        log "part B done"
    else
        err "part B FAILED — see $OUTD/part_b.log"
        RC=1
    fi
else
    stage_skip "41_bench_numa5m_b" "deadline"
fi

# ------------------------------------------------------------- part C -------
# Part C = the NUMA-unaware controls (multiprocessing.Pool, ProcessPoolExecutor)
# at the same scale, on the same boot. Without these the forkrun NUMA numbers
# have nothing to be compared against.
#
# RAM note: these legs read the entire corpus into a Python list of decoded
# str before chunking (bench_competitor). At 5M heavy that is ~28 GB of str
# objects plus the read buffer. This box has 256 GB, so it fits — but it is
# the reason heavy must be its own invocation.
banner "41c part C — Pool / Executor controls"
if deadline_ok 5400; then
    for v in light medium heavy; do
        if ! deadline_ok 3600; then
            stage_skip "41_bench_numa5m_c_$v" "deadline"
            break
        fi
        if run_logged "$OUTD/part_c_$v.log" "numa5m-part-c-$v" \
            python3 python/benchmarks/ml/bench_numa_5m.py \
                --records "$RECORDS" \
                --variants "$v" \
                --workers "$WMAX" \
                --nodes "$NODES" \
                --parts c \
                --tmpdir "$NUMA5" \
                --csv "$OUTD/numa5m_part_c_$v.csv"; then
            log "part C variant $v done"
        else
            err "part C variant $v FAILED"
            RC=1
        fi
    done
else
    stage_skip "41_bench_numa5m_c" "deadline"
fi

# ------------------------------------------------------------- part D -------
# Part D = streaming memory behaviour under slow-consumer backpressure across
# nodes. Fast (seconds).
banner "41d part D — streaming RSS under backpressure"
if deadline_ok 600; then
    if run_logged "$OUTD/part_d.log" "numa5m-part-d" \
        python3 python/benchmarks/ml/bench_numa_5m.py \
            --records "$RECORDS" \
            --parts d \
            --tmpdir "$NUMA5" \
            --csv "$OUTD/numa5m_part_d.csv"; then
        log "part D done"
    else
        err "part D FAILED"
        RC=1
    fi
else
    stage_skip "41_bench_numa5m_d" "deadline"
fi

# ----------------------------------------------------------------- the point --
banner "41e F-NUMA1 audit — the question this rental exists to answer"
# The single number that matters: is any cell SILENTLY short? A short cell is a
# correctness bug (data loss), not a slow cell. Distinguish them loudly.
# Loss arithmetic is shared with the other stages via epyc/validate_cells.py.
AUDIT="$EPYC_OUT/20_benchmarks/F_NUMA1_AUDIT.md"
if python3 "$EPYC_DIR/validate_cells.py" \
        --csv "$OUTD"/numa5m_*.csv \
        --records "$RECORDS" \
        --require-counts \
        --title "F-NUMA1 audit — real ${EPYC_NODES}-node topology" \
        --context "Topology as measured:
  nodes online \`$EPYC_NODES_ONLINE\` (${EPYC_NODES} nodes, shape $EPYC_NUMA_SHAPE)
  node->socket: $EPYC_NODE_SOCKETS
  SLIT matrix (node|distances): \`$EPYC_DIST_MATRIX\`
  self ${EPYC_DIST_SELF} | nearest other node ${EPYC_DIST_MIN_REMOTE} (steal threshold ${EPYC_THRESH_MIN_REMOTE}) | nearest cross-socket ${EPYC_DIST_MIN_CROSS:-n/a} (steal threshold ${EPYC_THRESH_MIN_CROSS}) | max ${EPYC_DIST_MAX} (threshold ${EPYC_THRESH_MAX})
  META_RING_SIZE=4096 -> ingest meta-lifetime bound 2048/${EPYC_NODES} = $(( 2048 / EPYC_NODES )) chunks/node

forkrun charges a steal threshold per (src,dst) node PAIR (forkrun_ring.c:2711),
so the intra- and cross-socket figures differ rather than collapsing to one
value the way they do on the reference box's uniform distance-10 fake topology.

**A row that is short is DATA LOSS, not a slow run.** Under a healthy run
\`valid\` equals \`total\` except for the medium/heavy quality gate (2108 / 2018
records at 5M, by design). F-NUMA1 surfaced at 4 nodes on heavy-20M as a run
that returned ~25% of its records with no error at all.
Cells with no cardinality at all are treated as FAILURE here (\`--require-counts\`):
for the NUMA experiment, a throughput number nothing can check is an invalid
experiment, not a passing one." \
        --out "$AUDIT"; then
    log "F-NUMA1 audit clean: no cell lost records"
else
    err "F-NUMA1 AUDIT FOUND SILENT DATA LOSS — see $AUDIT"
    err "This is the most valuable thing this rental could produce. Keep the box."
    err "Re-run the affected cell in isolation before quoting any rate from it."
    RC=1
fi

{ echo; echo "## Cross-check: the 10x byte-exactness gate from FAKE4_REVERIFY.md §5"; } >>"$AUDIT"
cat >>"$AUDIT" <<EOF

\`\`\`bash
# heavy-${RECORDS}, the workload F-NUMA1 was originally found on
FORKRUN_DIAG_NUMA1=1 python3 - <<'PY'
import forkrun, os
p = os.path.join("$NUMA5", "ml_heavy_${RECORDS}.jsonl")
out = forkrun.map(lambda b: b, p, workers=$WMAX, order="index",
                  nodes="auto", mode="splice")
print("blobs:", len(out))
PY
\`\`\`

The FAKE4_REVERIFY.md §5 protocol is 10 consecutive trials of exactly this cell
on both topologies, checking that orderer recv == emitted, heap_left == 0, and
that zero drain-audit warnings appear. If the audit above flagged anything, run
this ten times and report the divergence.
EOF

banner "41 numa5m COMPLETE"
log "audit: $AUDIT"
[ "$RC" -eq 0 ] || warn "see $AUDIT and $OUTD/*.log"
exit $RC
