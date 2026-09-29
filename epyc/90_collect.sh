#!/usr/bin/env bash
# epyc/90_collect.sh — bundle everything, write the environment + deviations
# record, and print a one-page summary.
#
#   bash epyc/90_collect.sh
#
# Run this LAST (or any time you want a snapshot). It never fails on a missing
# artifact — a partial rental still deserves an honest, readable record of what
# completed and what did not.

set -uo pipefail
EPYC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$EPYC_DIR/lib.sh"
load_env

banner "90 collect"

# ------------------------------------------------------- ENVIRONMENT.md ------
cat >"$EPYC_OUT/ENVIRONMENT.md" <<EOF
# EPYC rental — environment record

Collected $(date -u '+%Y-%m-%dT%H:%M:%SZ')

## Machine

| property | value |
|---|---|
| CPU | $EPYC_MODEL_NAME |
| sockets | $EPYC_SOCKETS |
| cores/socket | $(( EPYC_PHYS / EPYC_SOCKETS )) |
| physical cores | $EPYC_PHYS |
| logical CPUs (nproc) | $EPYC_NPROC |
| NUMA nodes online | \`$EPYC_NODES_ONLINE\` ($EPYC_NODES nodes) |
| cross-node distance | $EPYC_XNODE_DIST |
| forkrun base steal threshold | $(( 1 + EPYC_XNODE_DIST / 10 )) |

## System

| property | value |
|---|---|
| distro | $EPYC_DISTRO ($EPYC_DISTRO_ID) |
| kernel | $EPYC_KERNEL |
| glibc | $EPYC_GLIBC_VERSION |
| bash | $EPYC_BASH_VERSION |
| gcc | $EPYC_GCC_VERSION |
| python | $EPYC_PYTHON_VERSION |
| multiprocessing start method | $EPYC_MP_STARTMETHOD |

## forkrun

| property | value |
|---|---|
| checkout | $EPYC_ROOT |
| git SHA | $EPYC_GIT_SHA |
| META version | $(awk '/^VERSION:/{print $2}' "$EPYC_ROOT/META" 2>/dev/null) |
| engine version (live) | $(bash -c 'source "'"$EPYC_ROOT"'/frun.bash" 2>/dev/null && ring_version' 2>/dev/null || echo '?') |
| python package | $(python3 -c 'import sys;sys.path.insert(0,"'"$EPYC_ROOT"'/python");import forkrun;print(forkrun.__version__)' 2>/dev/null || echo '?') |

## Tuning applied by 10_setup.sh

\`\`\`
$(cat "$EPYC_OUT/00_environment/tuning.txt" 2>/dev/null || echo "  (not recorded)")
\`\`\`

- THP \`enabled\`: $(cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null)
- THP \`shmem_enabled\`: $(cat /sys/kernel/mm/transparent_hugepage/shmem_enabled 2>/dev/null)
- THP \`defrag\`: $(cat /sys/kernel/mm/transparent_hugepage/defrag 2>/dev/null)
- \`kernel.numa_balancing\`: $(sysctl -n kernel.numa_balancing 2>/dev/null)
- \`vm.max_map_count\`: $(sysctl -n vm.max_map_count 2>/dev/null)

## Competitor framework versions

\`\`\`
$(cat "$EPYC_OUT/00_environment/PIP_VERSIONS.txt" 2>/dev/null || echo "  (not recorded)")
\`\`\`

Full preflight transcript: \`00_environment/PREFLIGHT.txt\`
EOF

# ------------------------------------------------------- DEVIATIONS.md -------
cat >"$EPYC_OUT/DEVIATIONS.md" <<EOF
# Deviations from the published reference

**Every published forkrun number in this repo was measured on ONE box:**
28c Intel i9-7940X, single socket, **1 NUMA node**, distance 10, 28 workers,
Fedora, glibc 2.43, Python 3.14.7, gcc 16.2, kernel 7.1.x, THP
\`enabled=always\` + \`shmem_enabled=always\`.

This rental differs on nine axes at once. **No percentage in these results is a
regression measurement**; each is a new hardware data point.

| # | axis | reference | this box | effect |
|---|---|---|---|---|
| 1 | sockets | 1 | $EPYC_SOCKETS | the whole point of the run |
| 2 | NUMA nodes | 1 | $EPYC_NODES | \`nodes=auto\` resolves to $EPYC_NODES here, 1 there |
| 3 | node distance | 10 | $EPYC_XNODE_DIST | base steal threshold $(( 1 + 10 / 10 )) = 2 -> $(( 1 + EPYC_XNODE_DIST / 10 )) = $(( 1 + EPYC_XNODE_DIST / 10 )) |
| 4 | physical cores | 14 | $EPYC_PHYS | memory bandwidth and L3 scale together |
| 5 | logical CPUs | 28 | $EPYC_NPROC | worker sweeps are on a different curve |
| 6 | worker count | 28 | $EPYC_WORKERS_MAX | per-worker share of the machine differs |
| 7 | userland | Fedora (glibc 2.43 / py 3.14.7 / gcc 16.2) | $EPYC_DISTRO_ID (glibc $EPYC_GLIBC_VERSION / py $EPYC_PYTHON_VERSION / gcc $EPYC_GCC_VERSION) | libjson/glibc memcpy, allocator, compiler codegen |
| 8 | compiler | gcc 16.2 | gcc $EPYC_GCC_VERSION | plugin codegen (\`-march=native\` on Zen3 vs Skylake-X) |
| 9 | 20M competitor coverage | n/a | Ray + HF omitted at 20M | intentional; repo convention is competitors-at-5M |

## Deliberate methodology decisions

1. **Ray + HuggingFace Datasets omitted from the 20M stage.** Matches
   RELEASE_v3.6.0.md §0/§2, where competitors are measured at 5M and 20M is
   forkrun-only. Blocking is done with \`epyc/blockmods/sitecustomize.py\` so the
   absence is recorded, not silent.

2. **Benchmark worker cap raised from 8 to $EPYC_WORKERS_MAX.** Ten modules in
   \`python/benchmarks/{core,ml}/\` hardcode \`min(8, cpu_count)\`. On a
   $EPYC_NPROC-thread box that measures 8-way parallelism. 10_setup.sh rewrites
   it to honour \$FORKRUN_BENCH_WORKERS_MAX. (On the reference box the 8 *was*
   the effective cap, so the reference numbers are not invalidated — but they
   are not reproduced either.)

3. **(\*) Worker sweeps are >= the node count.** \`bench_numa_5m.py\` with
   \`workers < nodes\` returns INCOMPLETE and is pathologically slow (measured
   ~2,500 s for one 1M cell under fake-4), because an unworked node's
   born-local ring is never claimed (INVARIANTS.md §17).

4. **The bash matrix is single-shot.** \`run_benchmark.bash\` runs each
   configuration exactly once: no warmup, no repetition, no outlier rejection.
   The Python suite is median-of-5 with a warmup. Treat bash numbers as
   indicative and Python numbers as the defensible ones.

5. **Separate \`--tmpdir\` per ML scale.** \`bench_ml_pipeline.py\` reuses
   \`<tmpdir>/ml_<variant>.jsonl\` on existence alone and the filename carries
   no record count, so a 5M directory reused for a 20M run silently measures 5M
   and reports 4x-inflated rates. Every stage asserts the line count first.

6. **The comprehensive suite runs last and un-timeboxed.** It is the longest
   suite in the repo and the least performance-critical, so a slow box costs the
   least valuable hours by putting it here.

## What was NOT done

- The bash matrix was run **unmodified** at whatever size \`EPYC_BASH_BENCH_REDUCED\`
  selected. Its 216-config product and 1s inter-config cooldown are as-is repo
  behaviour.
- No sanitizer (ASan/UBSan/TSan) matrix. MAINTAINERS.md §5 requires one on
  frozen code, and it cannot be mixed with timing data in the same session.
- No NPS-mode BIOS change was attempted. Whatever the box booted with is what
  was measured.
- \`bench_scaling.py\` (the 1,2,4,8,14,28 scaling study) was not run: its sweep
  is hardcoded to the reference box's topology and is not in \`run_all.py\`'s
  registry.

See \`$(basename "$EPYC_OUT")/DEVIATIONS_worker_cap.txt\` for the exact patch.
EOF

# ------------------------------------------------------------------ tallies --
{
    echo "# stage outcomes"
    echo
    for m in "$EPYC_STATE"/*.done; do
        [ -e "$m" ] || continue
        printf '  PASS  %s\n' "$(basename "$m" .done)"
    done
    for m in "$EPYC_STATE"/*.fail; do
        [ -e "$m" ] || continue
        printf '  FAIL  %s\n' "$(basename "$m" .fail)"
    done
    for m in "$EPYC_STATE"/*.skip; do
        [ -e "$m" ] || continue
        printf '  SKIP  %-28s %s\n' "$(basename "$m" .skip)" "$(cat "$m.why" 2>/dev/null)"
    done
    echo
    echo "# stage wall-clock"
    [ -f "$EPYC_OUT/STAGE_TIMINGS.tsv" ] && sort -t$'\t' -k3 -rn "$EPYC_OUT/STAGE_TIMINGS.tsv" \
        | awk -F'\t' 'BEGIN{printf "  %-34s %-4s %s\n","stage","rc","sec"} {printf "  %-34s %-4s %s\n",$1,$2,$3}'
    echo
    echo "# longest individual commands"
    [ -f "$EPYC_OUT/CMD_TIMINGS.tsv" ] && sort -t$'\t' -k3 -rn "$EPYC_OUT/CMD_TIMINGS.tsv" | head -20 \
        | awk -F'\t' 'BEGIN{printf "  %-34s %-4s %s\n","command","rc","sec"} {printf "  %-34s %-4s %s\n",$1,$2,$3}'
} >"$EPYC_OUT/RUN_REPORT.txt"

# --------------------------------------------------------------- manifest -----
( cd "$EPYC_OUT" && find . -type f ! -name 'MANIFEST.sha256' -print0 \
    | sort -z | xargs -0 sha256sum >MANIFEST.sha256 2>/dev/null ) || true

# ----------------------------------------------------------------- summary ----
banner "90 collection summary"
{
    echo
    echo "  output dir : $EPYC_OUT"
    echo "  size       : $(du -sh "$EPYC_OUT" 2>/dev/null | cut -f1)"
    echo "  files      : $(find "$EPYC_OUT" -type f 2>/dev/null | wc -l)"
    echo
    echo "  KEY FILES"
    for f in ENVIRONMENT.md DEVIATIONS.md RUN_REPORT.txt TEST_TALLIES.txt \
             20_benchmarks/F_NUMA1_AUDIT.md; do
        [ -f "$EPYC_OUT/$f" ] && echo "    $f"
    done
    for f in 20_benchmarks/headline/headline_*.csv \
             20_benchmarks/ml5m/ml5m_*.csv \
             20_benchmarks/ml20m/ml20m_*.csv \
             20_benchmarks/tokenize/tokenize_*.csv \
             20_benchmarks/core/core_*.csv \
             20_benchmarks/bash/benchmark.out.txt \
             20_benchmarks/bash/benchmark_parallel.out.txt \
             20_benchmarks/bash/benchmark_xargs.out.txt \
             20_benchmarks/bash/benchmark_functions.out.txt \
             20_benchmarks/numa5m/numa5m_*.csv; do
        for g in "$EPYC_OUT"/$f; do
            [ -f "$g" ] && echo "    ${g#"$EPYC_OUT"/}"
        done
    done
    echo
} | tee "$EPYC_OUT/00_environment/COLLECTION_SUMMARY.txt"

banner "collect COMPLETE"
echo
echo "  Grab it with:"
echo "    rsync -avz root@<rental>:$EPYC_OUT ./epyc-results"
echo "  or archive in place:"
echo "    tar -C $(dirname "$EPYC_OUT") -czf forkrun-epyc-results.tar.gz $(basename "$EPYC_OUT")"
echo
exit 0
