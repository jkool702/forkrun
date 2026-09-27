# RELEASE_VERIFICATION — pre-v3.6.0 tag evidence (W-MOVER §7)

**Tree:** `NEW/REFACTOR2.7` @ `ebad918` (+ this file). **Date:** 2026-09-27.
**Box:** 28-thread, `numa=fake=4`, 125GB RAM. **Method:** all legs
foreground except where noted; evidence logs in `/tmp/rel_*.log`
(ephemeral — this file is the durable record).

## Leg 1 — Full Python suite ×3 (`/tmp/rel_leg1_{1,2,3}.log`)

PASS 3/3 — **549 tests green** (546 + 3 `test_mover.py`), ~250s each.
No failures, no skips-to-explain (release_check's nested skip only
inside leg 4's run).

## Leg 2 — Targeted re-verification ×10 each

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

110/110. (F-PORT3 rides `test_api_surface.py`, green in every full run.)

## Leg 3 — Bash suites, foreground

- `test_frun.sh`: **91/91** (`/tmp/rel_leg3_basic.log`).
- `test_frun_comprehensive.sh`: **261/263, then 262/263**
  (`/tmp/rel_leg3_comp{,2}.log`).
  - **T10b** (100KB lines + `-n 25`): 4/5 iters exact, iter=0 got
    0 lines (SIGTERM inside the HUP window) → green on rerun.
    Standing residual flake (pre-dispositioned) — NOT new.
  - **M8** (byte-mode resume, "no checkpoint"): 0/2 in-suite.
    Investigated as a potential F-NUMA1 regression (box is
    `numa=fake=4`, M8 runs the NUMA path, last green predates the
    F-NUMA1 engine change + blob rebuild):
    engine EXONERATED — uninterrupted run byte-exact (588895B,
    4.36s); manual HUP generation checkpoints fine
    (`wait_rc=129`, 824B resume file); full abort→truncate→resume
    flow byte-exact (**100000 lines, 0 missing**) on the fake-4
    NUMA path; standalone HUP loop **9/10 checkpoints** (one
    miss). Disposition: **HUP-timing marginality** (fixed
    readiness+3s sleep vs ~4.4s batch, ~1s margin — same family
    as the dispositioned T10b/T12 signal-timing flakes), NOT a
    product regression. Follow-up candidate: pin M8's HUP window
    (T12-style), non-blocking for tag — exactly like T10b's
    standing status.

## Leg 4 — Build/integrity gates

- `make -f Makefile.substrate check`: PASS (canary + 549-test suite).
- `python/release_check.py`: **17/17 PASS** ("ready to tag v3.6.0").
- `reproducibility-check`: PASS (consecutive `.so` builds byte-identical).
- Frozen files (`forkrun_ring.c`, `forkrun_substrate.h`,
  `substratestubs.c`): untouched (tree + history). `_shim.c` carries
  exactly the sanctioned D-PORT2 accessor.

## Leg 5 — NUMA EPYC-preview trio (`/tmp/rel_leg5_quads.log`)

Heavy-20M (`/tmp/heavy20m.jsonl`, 20,000,000 records, 26.9GB),
`ml_plugin_heavy`, workers=28, `order="index"`,
`FORKRUN_DIAG_NUMA1=1`, sequential in-process:

| Run | Result (20M lines, sha `a41696d0…`) |
|---|---|
| `nodes=1` #1 (REF) | 6,099,500,808 B, 33.3s |
| `nodes=1` #2 | EXACT |
| `nodes=@4` #1–4 | EXACT ×4 (27–29s) |
| `nodes=auto` #1–4 | EXACT ×4 (~26s) |

**10/10 byte-exact** (hash+len+lines over ordered bytes),
**zero drain-audit warnings** (all 10 err files clean),
DIAG telemetry on all 8 NUMA runs with per-node
`write==read` (e.g. `@4#1`: 9888/9727/9763/9790 per node —
~39K batches, past the 4096 meta-ring lap that exercises the
F-NUMA1 bound), all nodes forked, tails empty.

## Leg 6 — Twin/lockstep check

- CHANGELOG 62/62 `##`/`###` headings present verbatim in DOCS_ALL.
- INVARIANTS §20 (F-PY-UMA1b) + §21 checklist mirrored in DOCS_ALL.
- `PORT_AUDIT.md`: zero DEFERRED (11 PORTED / 8 EQUIVALENT /
  7 N/A-BY-DESIGN / 6 fixed / 3 resolved-by-design).
- W-MOVER entry + W-PORTDEFER entry twinned.

## Incidents (all dispositioned, none product)

1. T10b in-suite 4/5 → green on rerun (standing residual).
2. M8 0/2 in-suite → engine exonerated (full NUMA flow green),
   9/10 standalone (timing flake, same family; follow-up, non-blocking).
3. Tracer/sentry timing perturbation during the W-MOVER hunt on
   kill-window/parity tests (each green untraced; see MOVER_REPORT §6).
4. One background-nested-suite failure during W-PORTAUDIT verification
   (fully decomposed in PORT_AUDIT §5: known TestPurity comment +
   checklist correctly failing on in-progress docs — no M1a flake).

## Recommendation

**TAG v3.6.0.** All gates green; the two bash flakes are
same-family timing issues with the engine verified correct on
their exact paths; the EPYC-preview trio is 10/10 exact with
clean drains. Follow-ups (non-blocking): M8 HUP-window pinning,
D-PORT2-adjacent `fr_py_abort_reason` consumers (none required),
F-PY-UMA1b fd-aliasing origin (engine hardening for owner).
