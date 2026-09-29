# TAG_PREP_v3.6.0 — owner's keypress kit

**Do not tag. Do not push to `main`. Do not finalize the CHANGELOG
heading.** Those are owner acts, staged here. When this wave reports
green, the sequence below is the entire remaining path to shipped.

## 1. The sequence, in order

1. **Push branch** `NEW/REFACTOR2.11` (work branch; the F order's
   "2.10" is stale — D landed and the blob cycle ran on 2.11).
2. **Wait CI green**, including the blob auto-build
   (`forkrun_release.yml`). Confirm the freshness gate reports
   embedded==source — that is the moment it proves the D-wave
   engine (segfix included) is what ships. Expected: success
   (the cycle already ran green on this tree as PR #570).
3. **Promote `NEW/REFACTOR2.11` to `main`** (v3.6.0's first
   appearance there; `main` currently has no v3.6.0 content).
4. **CI green on `main`** (python-check, bashcompat-smoke,
   idl-check, shim-check, static-analysis advisory).
5. **Finalize `DOCS/CHANGELOG.md`** heading `## v3.6.0 (unreleased)`
   → `## v3.6.0` (date per convention). This flips the F6.2
   changelog guard green. Commit on `main`.
6. **Tag `v3.6.0`**, push tag. `release_check.py` (now 20 checks)
   must read ALL CHECKS PASSED first — the F6.1 tag-freedom check
   refuses an already-taken tag.
7. Attach `dist/checksums.txt` (wheel + sdist sha256, written by
   the F6.4 single-build path) to the GitHub release with the
   notes below.

## 2. Release notes contents list, final form

Recovery-default flip (`orchestrator` rides the reactor unless
`orchestrator=False`; migration: pass `orchestrator=False` for the
previous fail-fast behavior; supervision cost ±1.3%) · NUMA
poison-warning behavior change (previously silent → warns) ·
`strict_poison` / `signal_policy` params · exception taxonomy with
the dual-inheritance compatibility note (`ForkrunInterrupted`
straddles `RuntimeError`+`KeyboardInterrupt` — existing handlers
keep working) · `sink=` rejection as the documented API boundary ·
**the bash compatibility saga as a story** (0.9MB declare-death →
chunked bootstrap; gcc-16 TLSDESC wall → `-mtls-dialect=gnu`
rebuild; `struct array.head` 24→16 worker segfault on ≤5.1 →
stable-API pair-list fix; floor bash ≥4.4; glibc floor honestly
2.38 pending the old-base `-std=gnu17` build, 2.28 when it lands) ·
port-parity summary (W-PORTAUDIT 32/32 dispositioned: 11 ported,
8 equivalent, 7 N/A-by-design, 6 fixed, 0 deferred) ·
topology-dependent test counts (bash 92/89 by boot; multi-node
skips; Python 621 + 8 toolchain skips) · M8 (test bug, engine
exonerated) / M1a (foreground rule) / T10b (known flake) /
T12 (poison-vs-HUP race pinned open, `FORKRUN_RETRY_LIMIT=-1`)
dispositions · R1 benchmark numbers (README table) ·
**verification-culture evidence** (three halt-and-report spec-flaw
catches during final assembly — D2-coherence, D4 `niov = 0`,
D11-revert; the gates caught what optimism would have shipped) ·
deferred-to-3.6.1 list (§5).

## 3. Compatibility matrix, final state

| Bash | glibc | Evidence |
|---|---|---|
| 4.4 (RHEL 8) | ≥2.38 (new iron); RHEL8's 2.28 blocked | extracted-binary round-trips (D matrix); UBI8 leg amber (cause cited) |
| 5.0 | ≥2.38 | extracted-binary round-trips |
| 5.1 | ≥2.38 | source-built 5.1.0 + extracted 5.1.16 round-trips, byte-exact; permanent CI leg (D-LEGS) |
| 5.2 | ≥2.38 (Ubuntu 24.04's 2.39 loads) | 92 + 264 suites, zero failures |
| 5.3 | current | 92 + 264 suites, zero failures; CI binds |

Python: 3.10/3.11/3.12/3.13 CI cells (F2) + 3.14 dev flow; floor 3.10.
glibc floor note: x86-64 blobs need ≥2.38 (`__isoc23_strto*`
aliasing); non-x86 blobs never carried `GLIBC_ABI_GNU2_TLS`.
Debian 12 (2.36)/RHEL ≤9 stay blocked → the old-base build item.

## 4. Known-open items ledger (into the tag)

- 2.38→2.28 build migration (`-std=gnu17` probe; UBI8 leg amber).
- D13 (`%lu`→`PRIu64`, pairs with post-tag sanitizer legs).
- D11's reverted mechanism (hook cost accepted: ~150ns/batch).
- Old-base build image pin (follows the 2.28 item).
- F6 remainder: SBOM/signing/attestation, hermeticity, import
  ambiguity (explicit 3.6.1).
- EPYC benchmark prep (next major event — owner-provided plan:
  Cherry Servers 64c/128t EPYC 9575F, 4 NUMA nodes, 384GB
  ~$2.70/hr).
- Sanitizer RUNS (legs exist advisory; runs deferred).
- Ruff top findings (UP031/BLE001/S110 sampling exonerated;
  counts recorded for the 3.6.1 gating decision).

## 5. Verification receipts (where every claim above is proved)

- `dev/supervisor/WREL5_D_REPORT.md` (D wave: root causes,
  bite/green evidence, audits, halt log).
- This wave's completion report (F items, new-count release_check,
  CI inventory) — filed at wave end alongside this bundle.
- `python/release_check.py` (20 checks) ALL CHECKS PASSED pre-tag.
- `dist/checksums.txt` (single-build wheel+sdist hashes).
