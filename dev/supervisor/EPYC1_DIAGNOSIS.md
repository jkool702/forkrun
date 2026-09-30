# W-EPYC1 Diagnosis — CPU-to-NUMA mapping: NO BUG FOUND (negative result)

Date: 2026-09-30. Tree: `3e4fac26` (`NEW/REFACTOR2.12`, clean + untracked
`epyc-rental-out/` only). Rental box (per `epyc-rental-out/HEADLINE_TABLE.md`):
2× EPYC 7443, 96 threads, 2 NUMA nodes NPS1. Local box: 28-thread i9-7940X,
`numa=fake=4` (online `0-3`).

## 0. Verdict up front

The hypothesized contiguous-slice bug **does not exist in this tree**. Every
code path that maps CPUs to NUMA nodes already does membership-grouping from
the authoritative sysfs per-node `cpulist`. There is no code anywhere in the
shipping paths that assigns contiguous CPU ranges to nodes, so the described
failure mode (CPUs 1–48 → node 0 straddling the true boundary) cannot be
produced by the current code. **No fix is required; no bite is possible**
(the EPYC-shaped unit probe passes pre-fix). Phase 1 has no work item.
Halt-and-report per standing rules — disposition below (§5).

Note: the order's "64c/128t 9575F" header does not match the rental's own
`HEADLINE_TABLE.md` (2× 7443, 48c/96t). The topology shape under test below
uses the order's node0={1–24,49–72} / node1={25–48,73–96} split, which is
the Mannheim-style interleave either machine would present; the conclusion
holds for any non-contiguous layout.

## 1. Source-of-truth audit (all consumers, file:line)

| # | Site | Source consumed | Verdict |
|---|---|---|---|
| 1 | `python/forkrun/_numa.py:30-50` `_parse_id_list` | pure parser: `X-Y,Z` ranges + singletons, whitespace-tolerant, skips garbage | correct |
| 2 | `_numa.py:64-72` `get_node_cpus` | reads `/sys/devices/system/node/nodeN/cpulist` per node | correct |
| 3 | `_numa.py:75-164` `build_numa_map` (auto/int/`@N`/explicit) | groups by actual per-node cpulists in ALL branches | correct |
| 4 | `frun.bash:1317-1395` `_forkrun_build_numa_map` | node-ID map from `/sys/.../node/online` (node identity, never assigns CPUs) | correct |
| 5 | `forkrun_ring.c:1042-1078` `pin_to_numa_node` | reads node's own `cpulist`, own range parser (`strtol` start[-end] loop) | correct |
| 6 | `forkrun_ring.c:9893-9920` `tui_get_node_cpus` | same algorithm (display only) | correct |
| 7 | `_shim.c:166-209` `fr_py_worker_init` | pins via `g_logical_to_phys_map[node]` → site 5 | correct |
| 8 | `forkrun_ring.c:7792-7823` `ring_worker inc` | same as 7 (bash-worker path) | correct |
| 9 | `forkrun_ring.c:3621-3632` `ring_indexer_numa` | pins via map → site 5 | correct |
| 10 | `forkrun_ring.c:4205-4210` `core_scanner_loop` | pins via map → site 5 | correct |
| 11 | `forkrun_ring.c:3256-3267` `ring_numa_ingest` | `MPOL_BIND` by physical node id (no CPU lists at all) | correct |
| 12 | `forkrun_ring.c:1033-1040` `auto_detect_numa_node` | `getcpu` syscall (kernel truth) | correct |

Full-repo sweeps (excluding `LEGACY/`, `OLD_MISC/`, `PREV_VERSIONS/`) for
`cpus_per_node`-style division, `nproc`-over-nodes arithmetic, `taskset`
with computed ranges, and `range(*cpu*)` enumeration found exactly one
division site: `forkrun_ring.c:10237` `logical_cores_per_node` — a TUI
**display-only** fallback denominator (worker-count saturation % when
hardware CPU stats are unavailable). It never touches affinity. The
`OLD_MISC/frun.bash:562-568` `taskset` site also pins from the real
`cpulist`, and is not shipped.

## 2. Empirical probes (the bite that wouldn't bite)

Fed the order's exact EPYC shape through the real `build_numa_map("auto")`
with injected sysfs readers (only injection point needed — `get_node_cpus`
reads a hardcoded path, `_parse_id_list` is already pure):

```
node0 cpulist '1-24,49-72'  -> 48 CPUs, head [1..5], tail [70,71,72]
node1 cpulist '25-48,73-96' -> 48 CPUs, head [25..29], tail [94,95,96]
build_numa_map('auto') -> map '0,1', num_nodes 2
node0 membership exact: True | node1 membership exact: True
straddle (any of 25–48 in node0's list): False
```

Local-box agreement: `build_numa_map("auto")` → `'0,1,2,3'`, 4 nodes × 28
CPUs, matching `/sys/devices/system/node/node*/cpulist` (`0-27` on all four
— the kernel's own fake-4 truth, consumed faithfully). The C parsers (sites
5–6) were verified line-for-line against `_parse_id_list` by reading; they
implement the identical start[-end]-per-comma algorithm and cannot straddle
a range boundary by construction (they never synthesize ranges, only expand
the ones sysfs reports).

`python -m unittest python.tests.test_numa python.tests.test_numa_recovery
python.tests.test_numa_drain_guard` → 46 tests, OK (13.6s).

## 3. What this means for the rental numbers

The order's §4 footnote ("first-generation EPYC results were collected with
a CPU-to-node mapping defect") **must NOT ship**: there is no evidence of
such a defect in this tree, and the empirical probe shows the mapping was
correct. Publishing an unowned-defect footnote would be a benchmarking
falsehood in the opposite direction. If the EPYC scaling shortfall (forkrun
inverts above 32–48w, loses ~2.1× by 96w per `HEADLINE_TABLE.md` §2) needs
explaining, it needs a real diagnosis — candidates untouched by this order:
worker oversubscription vs 48 physical cores, cross-socket steal thresholds
on the real distance matrix, memfd/memory-bandwidth contention. None of
these were investigated here.

Caveat on provenance: this diagnosis covers the tree at `3e4fac26`. If the
rental ran a different commit, the mapping code's history (`git log --
python/forkrun/_numa.py` → single commit `c1d28a57`) shows no contiguous
slicing ever landed in `_numa.py`. An engine-side regression in the rental
build cannot be ruled out from here, but no such code exists at HEAD.

## 4. Lock-in tests

None added — a regression test for a bug that does not exist would pin
nothing. The existing `test_numa.py` family (46 tests incl. recovery/drain
guards) already covers `build_numa_map` shape, `@N` cycling, and node-CPU
agreement, and is green. If the owner wants a belt-and-braces EPYC-shaped
membership test committed anyway (cheap, ~20 lines in `test_numa.py`),
say so — it passes as-is.

## 5. Disposition

- **W-EPYC1: CLOSE AS NOT-A-BUG (negative diagnosis).** No code change, no
  blob cycle, no gate runs beyond the `test_numa*` family already executed.
  No 3.6.0/3.6.1 landing needed — there is nothing to land.
- **Do NOT publish the §4 rental-numbers footnote** — its premise is
  refuted. The i9 baseline stands; the EPYC table stands as measured (with
  its existing matched-configuration caveats, which are real and separate).
- **W-EPYC2 (worker default policy): needs re-scope.** Its stated value
  "depends on the fixed mapping" — there is no fixed mapping. If the policy
  change has independent merit it can proceed on its own order; if it was
  purely remedial for the mapping bug, it should be dropped. Owner decides —
  the W-EPYC2 spec was not part of this order's text.
- Suggested follow-up (not this order): a genuine diagnosis of the EPYC
  >48-worker inversion, which this order's bug theory would have masked.
