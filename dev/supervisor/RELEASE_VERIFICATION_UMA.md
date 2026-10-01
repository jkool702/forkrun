# RELEASE_VERIFICATION_UMA — UMA-boot companion to RELEASE_VERIFICATION.md (W-UMARESTART)

**Tree:** `NEW/REFACTOR2.7` @ `7c2ca40` (+ this file). **Date:** 2026-09-27.
**Box:** 28-thread, single-node UMA kernel view, 125GB RAM. **Method:** all legs
foreground except Leg 4's sequential driver (no signal tests inside);
evidence logs in `/tmp/uma_rel/` (ephemeral — this file is the durable record).
Companion to the fake-4 NUMA bundle (`RELEASE_VERIFICATION.md` @ `0325e7c`);
together the v3.6.0 tag rests on both topology legs.

## Leg 0 — Environment confirmation

- `numactl --hardware`: **1 node (0)**, 28 cpus, 128494 MB. UMA boot confirmed
  (no `numa=fake` on kernel cmdline).
- THP: `always [madvise] never` (mode **madvise**, recorded as-run;
  matches the box default used for the fake-4 legs).
- Pre-restart checklist (order §2): tree was clean at `7c2ca40` with
  `HEAD == origin/NEW/REFACTOR2.7` — the push-before-restart was already
  satisfied, verified not re-done; leaving-env (fake-4) is documented in
  the prior bundle; nothing uncommitted to lose.
- `make -f Makefile.substrate python-substrate`: OK
  (`libforkrun_python.so` x86-64). `make canary`: OK.
  `forkrun.__version__ == 0.16.0`, `__engine_version__ == v3.6.0`.
- Engine diff: empty (`forkrun_ring.c`, `forkrun_substrate.h`,
  `substratestubs.c` untouched in tree and by HEAD).

## Leg 1 — Full Python suite ×4 (`/tmp/uma_rel/leg1_{1,2,3,verbose}.log`)

- Runs 1–2: **549 tests OK (skipped=7)** each, ~211–213s.
- Run 3: 549 tests, **1 failure** — `test_c_drain_identical`
  (`test_scaling.TestCWorkerLoopParity`), framing-header bytes in row 0
  (`\x02\x00\x00\x00...` vs `LINE 0`). Disposition: **known residual
  family** (C-drain framing header — handover registry item 3), NOT new.
  **5/5 green in isolation** (`/tmp/uma_rel/leg1_cdi_iso_{1..5}.log`).
- Run 4 (verbose, definitive): **549 tests OK (skipped=7)**, 215s.
- The 7 skips are **all** `test_numa_recovery.py` "Requires multi-node
  NUMA" (5 map + 2 stream) — by design under a 1-node kernel
  (W-PY38 topology-isolation doctrine). No other skips.
- Net: **3/4 clean + 1 known-flake**, flake green 5/5 isolated.

## Leg 2 — Targeted re-verification ×10 each (`/tmp/uma_rel/leg2_*`)

| Suite (order) | Result |
|---|---|
| `test_numa_bump` (W-NUMA2) | 10/10 |
| `test_numa_drain_guard` (F-NUMA1) | 10/10 |
| `test_taxonomy` (D-PORT3) | 10/10 |
| `test_signals` (D-PORT1) | 10/10 |
| `test_abort_reason` (D-PORT2) | 10/10 |
| `test_retry_limit` (F-PORT1) | 10/10 |
| `test_checkpoint_gate` (F-PORT2) | 10/10 |
| `test_hostile_path` (F-PORT4) | 10/10 |
| `test_edge_degenerate` (F-PORT6) | 10/10 |
| `test_release_version` (F-PORT5) | 10/10 |
| `test_mover` (F-PY-UMA1b) | 10/10 |

**110/110**, all foreground. The mover invariant holds under UMA boot's
different fd-recycling pressure (order §3 note).

## Leg 3 — Bash suites, foreground

- `test_frun.sh`: **89/89** (`/tmp/uma_rel/leg3_basic.log`). Delta vs the
  fake-4 91/91 is **structural, not a regression**: 2 NUMA-native tests
  register only when `/sys/devices/system/node/online` matches `0-`
  (`test_frun.sh:939`); under UMA (`online == 0`) they are absent by
  design, with 0 skipped and 0 failed.
- `test_frun_comprehensive.sh`: **263/263 clean first try**
  (`/tmp/uma_rel/leg3_comp.log`). No T10b/M8 manifestation; M1a green
  (foreground launch throughout).

## Leg 4 — Forced-logical heavy-20M (`/tmp/uma_rel/leg4_quads.log`)

Full 10-run driver (exceeds the order's `@4`×2 + `nodes=1`×2 minimum),
input `/mnt/ramdisk/numa1/ml/heavy_20M.jsonl` (20,000,000 records),
plugin `/mnt/ramdisk/numa1/ml/ml_plugin_heavy.so:ml_process_heavy`
(`/tmp` copies were reboot-wiped; `/mnt/ramdisk` copies verified:
`ml_process_heavy` exported), workers=28, `order="index"`,
`FORKRUN_DIAG_NUMA1=1`, sequential in-process:

| Run | Result (20M lines, sha `2dc03907…`) |
|---|---|
| `1` #1 (REF) | 6,099,447,409 B, 31.5s |
| `1` #2 | EXACT |
| `@4` #1–4 | EXACT ×4 (26–27s), DIAG per-node `write==read` (e.g. #1: 9943/9834/9487/9899 — ~39K batches, past the 4096 meta-ring lap exercising the F-NUMA1 bound), all nodes forked, tails empty, orderer `recv==emitted` (39163), heap empty |
| `auto` #1–4 | EXACT ×4 (~30–31s), single-node path (no per-node DIAG — **expected**: `auto` resolves to the boot topology, which is 1 node here) |

**10/10 byte-exact** (hash+len+lines over ordered bytes),
**zero drain-audit warnings** (all 10 err files clean of
`NUMA partial`; copies in `/tmp/uma_rel/quad_err/`).
Note: output sha differs from the fake-4 bundle's `a41696d0…` — expected,
different input file (regenerated heavy dataset), not a divergence:
exactness is judged within-leg vs its own REF.

## Leg 5 — Build/integrity gates

- `python/release_check.py`: **17/17 PASS** ("ready to tag v3.6.0")
  (`/tmp/uma_rel/leg5_release_check.log` — includes nested full suite
  with the anti-recursion skip).
- `reproducibility-check`: PASS (consecutive `.so` builds byte-identical).
- `tools/test_idl.py`: PASS.
- Frozen files (`forkrun_ring.c`, `forkrun_substrate.h`,
  `substratestubs.c`): untouched in tree and by HEAD (`15a011d` last
  touches engine, predates this work). `_shim.c`: no uncommitted diff
  (the sanctioned D-PORT2 accessor rides in history).
- Twins spot-check: F-NUMA2 / F-PORT / D-PORT / F-PY-UMA1b sections
  present in both CHANGELOG.md and DOCS_ALL.md; INVARIANTS §20 present.

## Incidents (1, dispositioned, known-flake)

1. Leg 1 run 3 `test_c_drain_identical` — C-drain framing-header residual
   (registry family 3), 5/5 green in isolation. No rerun-until-green:
   recorded here as the disposition.

## Recommendation

**TAG v3.6.0.** UMA leg: all green modulo one known-flake-only failure
with a 5/5-isolation disposition — the order's §5 "Known-flake-only
failures" row. Engine diff empty, tree clean at start and end
(`7c2ca40` + this file), both topology legs proven.
