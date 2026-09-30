# EPYC rental — environment record

Collected 2026-09-30T15:17:27Z

## Machine

| property | value |
|---|---|
| CPU | AMD EPYC 7443 24-Core Processor |
| sockets | 2 |
| cores/socket | 24 |
| physical cores | 48 |
| logical CPUs (nproc) | 96 |
| NUMA nodes online | `0-1` (2 nodes) |
| topology shape | NPS1 |
| real multi-socket? | **YES** |
| F-NUMA1 meta bound | 2048/2 = 1024 chunks/node (fake-4 baselines: 512) |
| node -> socket | `0:0 1:1` |

### NUMA distance matrix (SLIT)

| measurement | value | forkrun base steal threshold `1 + d/10` |
|---|---|---|
| self | 10 | — |
| nearest other node | 32 | 4 |
| nearest cross-socket | 32 | 4 |
| maximum | 32 | 4 |

```
  node 0|10 32
  node 1|32 10
```

forkrun builds a threshold for **every (src,dst) node pair**
(`forkrun_ring.c:2711`, `thresh = 1 + dist/10`, floored at 2), so there is no
single "the" distance. The reference box's `numa=fake=4` had a uniform distance
of 10, charging every pair 2; a real 2-socket NPS4 box charges 2 within a socket
and 4 across the socket link. The "fake-NUMA is a worst case" claim therefore
does not transfer cleanly in either direction.

**Topology as an experimental condition:**

NPS1 (1 NUMA node per socket). This is a genuine 2-socket topology and it
answers the primary question. Two consequences worth recording:
  * 'nodes=auto' selects one node per socket, so the UMA-vs-NUMA contrast is
    a clean socket-to-socket comparison.
  * It is a LOOSER F-NUMA1 configuration than the fake-4 baselines
    (2048/2 = 1024 chunks/node vs 512). A clean result here does NOT rule out
    F-NUMA1 at higher node counts; if a reboot into NPS2/NPS4 is ever possible,
    re-run stages 41 and 43 on it.



## System

| property | value |
|---|---|
| distro | Ubuntu 26.04.1 LTS (26.04) |
| kernel | 7.0.0-31-generic |
| glibc | 2.43 |
| bash | 5.3.9(1)-release |
| gcc | 15 |
| python | 3.14.4 |
| multiprocessing start method | forkserver |

## forkrun

| property | value |
|---|---|
| checkout | /opt/forkrun |
| git SHA | 3e4fac26d971f8936baf333e97deb1cb9b44a010 |
| META version | v3.6.0 |
| engine version (live) | v3.6.0 |
| python package | 0.16.0 |

## Tuning applied by 10_setup.sh

```
governor: performance
governor: performance
governor: performance
governor: performance
governor: performance
governor: performance
governor: performance
governor: performance
governor: performance
governor: performance
```

- THP `enabled`: [always] madvise never
- THP `shmem_enabled`: [always] within_size advise never deny force
- THP `defrag`: always defer defer+madvise [madvise] never
- `kernel.numa_balancing`: 0
- `vm.max_map_count`: 1048576

## Competitor framework versions

```
polars	1.44.2 (pinned)
duckdb	1.5.5 (pinned)
datasets	5.0.1 (pinned)
ray	2.58.0 (pinned)
```

Full preflight transcript: `00_environment/PREFLIGHT.txt`
