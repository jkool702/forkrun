# Fake-4 Re-Verification (W-FAKE4 Rev 2) — post-restart NUMA leg

Date: 2026-09-29 (post-reboot session). Branch `NEW/REFACTOR2.12`
SHA `9e7e4cac2c025e1c3e5aecb8973d0030033c680b` (W-P0LEGACY head; teardown
reorder present). Tree clean. Nothing pushed, nothing tagged (per order).

## 1. Environment echo

```
numactl:                4 nodes (0-3), 28 cpus each (all shared, fake topology)
cmdline:                ... numa=fake=4 ... (boot verified)
THP enabled:            [always] madvise never   (was madvise at boot under the
                        numa_emu kernel cmdline default; owner flipped to always
                        mid-session before any benchmark cell — all cells below
                        ran under always)
THP shmem_enabled:      [always] ... (already always, untouched)
kernel:                 7.1.10-200.numa_emu.fc44.x86_64 (NUMA-emu kernel;
                        differs from the UMA sessions' 7.1.13 by boot design)
uptime at start:        22 min (fresh reboot confirmed)
```

## 2. Data inventory (reused vs regenerated)

- **Reused (persistent archive restored pre-handoff, mtimes preserved):**
  `heavy_1M.jsonl` 1,343,690,021 B / 1,000,000 lines ✓,
  `heavy_20M.jsonl` 26,880,545,542 B / 20,000,000 lines ✓. Integrity by
  line count; NOT regenerated.
- **Regenerated (seeded-identical, `ml_data_gen.SEED=42`, same entry as W-SPOT):**
  `light_5M.jsonl` 532,711,015 B / 5,000,000 lines (byte-identical size),
  `medium_5M.jsonl` 2,347,403,909 B / 5,000,000 lines (byte-identical size).
  ~2 min for both. No tokenize data (none needed — no tokenize cells here).

## 3. Substrate

- `make -f Makefile.substrate check`: canary OK (no undefined symbols).
- `make -f Makefile.substrate python-substrate`: rebuilt (the reboot wiped the
  untracked `.so`; the first canary-run suite attempt ran without it — see §7
  incident 2). `libforkrun_python.so` 279K, x86-64.

## 4. Bash side (foreground)

| Suite | Result | Expectation |
|---|---|---|
| `test_frun.sh` | **98/98** rc=0 | 96 → exceeded (2 added since), green |
| `test_frun_security.sh` | **101/101** rc=0 | first fake-4 run ever, green, no new surface |
| `test_frun_comprehensive.sh` | **264/264** rc=0 | green (the ✗ lines in the log are intentional negative self-tests) |

M8/T12/M22: no reds; no registry dispositions needed.

## 5. Python side

**§3.1 suite ×2** (644 tests, ~463s each — fake-4 runs slower than UMA's ~206s):
both runs identical — exactly the 3 known pre-existing failures
(`test_death_cause_mapping` suite-order signal-disposition flake, its
`test_claim_taxonomy` cascade, `test_release_check_passes` whose inner suite
carries the same flake). Zero errors, zero new signatures. NUMA-family tests
(`test_numa*`, drain-guard) green in-suite.

**§3.2 heavy NUMA gates** (C-plugin heavy, 28w, `order="index"`,
`FORKRUN_DIAG_NUMA1=1`, subprocess-isolated stderr):

| Gate | Result |
|---|---|
| heavy-20M `@4` ×4 | exact 20000000/19991658 every trial; orderer recv==emitted, heap_left=0; **zero warnings** (0.692/0.736/0.756/0.757M) |
| heavy-20M `nodes=1` ×2 | exact, zero warnings (0.637/0.624M) |
| F-PY-UMA1 forensic (`TestSequentialHeadExactness`, 10×) | OK |
| F-NUMA1 drain-guard (`test_numa_drain_guard`, 7 tests) | OK |
| P0LEGACY lock-in ×5 under fake-4 | OK (40.3/40.8/42.3/43.3/43.2s — timing profile holds) |

No mismatch ≠ 0 anywhere; the silent-loss tripwire never fired.

**§3.3 `@4` spot cells** (median-of-3 + warmup, 28w, configs pinned):

| Cell | Measured | Reference | Delta/verdict |
|---|---|---|---|
| ML-L-C-@4 (†) | 4.839M (1.03s; 0.88/1.03/1.06) | 4.73M W-SPOT | +2.3% ok |
| ML-L-C-@4 (max) | 5.981M (0.84s; 0.65/0.84/0.92) | — first-time | baseline |
| ML-M-C-@4 (†) | 1.822M (2.74s; 2.38/2.97/2.74) | 1.85M W-SPOT | −1.5% ok |
| ML-M-C-@4 (max) | 2.084M (2.40s; 2.36/2.40/2.41) | — first-time | baseline |
| ML-H-C-@4-20M (max) | 0.681M (29.37s; 25.58/30.09/29.37) | ~0.76M (†-config) | first-time baseline for max (wide trials ±8% noted) |

All totals exact. Warm-first pattern visible (light-max 0.65→0.92; heavy-max
25.58→30.09); medians absorb it; triples recorded in `/tmp/fake4_spot.jsonl`.
Note: light-@4-max (+23.6% over †) shows the C-orderer transit scales with batch
count on the light workload; medium-@4-max (+14.4%) matches the flip-commit shape.

**§3.4 torch-host pre-flight:** 4 concurrent parent threads × `@4` maps, exact
outputs, 0.3s — OK. Fork-deadline machinery exercised on the NUMA path.

## 6. Incidents + dispositions

1. **THP=madvise at boot** (numa_emu cmdline default) vs reference `always`.
   Disposition: owner flipped mid-session before any benchmark cell; verified
   `[always]` + shmem `[always]`; recorded here. No data taken under madvise.
2. **Canary-run suite anomaly** (429 skipped + 14 failures + 2 errors): root
   cause = reboot wiped the untracked `libforkrun_python.so`, so every
   lib-gated test skipped and dependents errored/cascaded. Not product.
   Disposition: rebuilt substrate, re-ran clean (the §3.1 runs above are the
   valid record). Lesson recorded: post-reboot runs must rebuild the
   substrate BEFORE trusting suite output.

## 7. Verdict line

**CLEAN:** all suites green (modulo the 3 known pre-existing failures identical
on UMA), heavy gates exact with zero warnings and clean DIAG, `@4` cells
in-band or first-time-baselined, torch pre-flight OK, two incidents
dispositioned without product findings. **The box is cleared for EPYC duty.**

Release-verification record: *"fake-4 leg re-verified post-W-REL6/P0LEGACY:
suites + heavy gates + @4 baselines green; light/medium regenerated
seeded-identical, heavy reused."*
