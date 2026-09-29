# W-REL5-F Completion Report — Release Infrastructure & Tag Preparation

**Branch:** `NEW/REFACTOR2.11` (the F order's "2.10" is stale — D
landed and the blob cycle ran on 2.11). Nothing tagged. `main`
untouched. R5.3: **zero C diff across the wave** (verified
`git diff <base> HEAD -- '*.c' '*.h'` empty).

## 1. Per-item table

| Item | Change (files) | Gates |
|---|---|---|
| F1 verify | none (report-only) | branch pushed + CI green on head; timeouts on every python-check job verified; two older workflow-refactor failures classified (mid-refactor transients, superseded by greens) |
| F2 version matrix | `python-check.yml` (+build-wheel, +version-matrix 3.10–3.13), `setup.py` (3.13 classifier; floor stays 3.10), `.gitignore` (wheelhouse/) | YAML valid; wheel `py3-none` proven installable cross-version (venv 0.16.0/v3.6.0); MODS-list + FORKRUN_LIB shape green (13/13); packaging excluded per-cell with rationale (needs headers) |
| F3 static analysis | `static-analysis.yml` (new, advisory) | ruff 554 (UP031 211, BLE001 142, S110 78; F841/PLW1510 sampled, no live bug, nothing fixed); coverage 62% TOTAL (fork-flush artifact documented) |
| F4 freshness automation | `ring_loadables/verify_blob_freshness.bash` (new, +x), `sanitizer-freshness.yml` (new, reusable), RUNBOOK E1/E3 → automation pointer | gate bites both directions (fresh OK / cross-arch FAIL); RUNBOOK updated |
| F5 ubuntu-native | **deleted** `ubuntu-native.yml` | dead trigger (2.7), nonexistent `bash-builtins` dep, unbuildable premise (no Ubuntu headers), broken `frun -k cat` test, full F2/D-LEGS overlap |
| F6 release_check | `python/release_check.py` (17→20), `test_packaging_v2.py` (state-aware) | each addition bite-proven (§3); single-build checksums verified |
| F7 tag bundle | `TAG_PREP_v3.6.0.md` (new), RUNBOOK §6 (mask rule) + §7 (v3.6.0 pointer) | content assembled, sequence ordered |
| Hygiene | timeout-minutes on idl/shim/sh-format/release-build/embed; coverage note in F3 comment | all 8 workflows parse |

## 2. New `release_check.py` count and check list — **20 checks**

17 inherited + 3 added (F6): `Docs: CHANGELOG v3.6.0 heading is
final (no (unreleased)))`, `Tag: v3.6.0 not already taken`, `IDL:
generated artifacts match (gen_idl.py --check)`. Restructured (no
count change): wheel/metadata/sdist/so-version read one shared
build; stale outputs of our own pattern removed first; sha256 of
both recorded to `dist/checksums.txt`. Full list printed by the
tool itself; count asserted here: **20, was 17**.

## 3. Designed-red changelog guard — bite and expected state

- Bite evidence: fails NOW with the finalize instruction
  (`CHANGELOG.md still heads v3.6.0 as (unreleased) -- finalize
  ... (this red is designed, not a bug)`); scoped to the release
  heading (older `(unreleased)` markers untouched).
- Tag check bites against existing `v3.5.2`, passes for `v3.6.0`.
- Expected state at wave end: **19/20, the 1 failure being
  exactly this guard** (verified in §6 runs). `test_packaging_v2`
  pins whichever state is current (designed-red signature
  pre-finalization; full green after). NOBODY fixes this early.

## 4. CI job inventory (status · role · disposition)

| Workflow → job | Status | Role |
|---|---|---|
| forkrun_release → build ×5 | green (PR #570 ran it) | binding; carries D-TLS flags |
| forkrun_release → embed/verify/PR | green | binding (freshness gate proves D engine ships) |
| python-check → python-v0 | binding (fedora source+suite) | last branch run: G0 era (main-only trigger) |
| python-check → sanitizer | advisory (continue-on-error) | unchanged |
| python-check → build-wheel | NEW, binding | first run at promotion |
| python-check → version-matrix ×4 | NEW, binding-on-green | first run at promotion; 3.13 halts-named, no trim |
| bashcompat-smoke → canary-versions | binds | green |
| bashcompat-smoke → version-smoke ×6 | fedora binds; 5 amber-with-cause + TODO | D-LEGS legs; logic validated locally |
| static-analysis → baseline | advisory, never fails | first run at promotion |
| sanitizer-freshness | reusable/dispatch | adopted by sanitizer branches post-promotion |
| idl-check / shim-check / sh-format twin-check | binding | green path (timeouts added) |

No silent ambers: every amber names its cause + unblock condition.
Directly observed this wave (gh): release successes ×N incl. the
D-LEGS and changelog commits; bashcompat-smoke success; two
superseded mid-refactor failures (17:42/17:46, workflow-edit
transients). Version-matrix/static-analysis/freshness jobs have
never run (new files) — first runs happen on `main`, owned by F7
step 4's CI-green gate.

## 5. Deferred-and-why (3.6.1)

- F6 remainder: SBOM/signing/attestation, hermeticity, import
  ambiguity (explicitly out of F6 scope).
- D13 (`%lu`→`PRIu64`), old-base `-std=gnu17` build (2.28 floor),
  sanitizer RUNS, D11's reverted mechanism (cost accepted).
- Ruff top findings (counts recorded; fix-or-gate decision then).
- F2 3.13 unknowns (if the cell surfaces any: halt-named there).

## 6. Tag-prep bundle + keypress summary

`dev/supervisor/TAG_PREP_v3.6.0.md`: push 2.11 → CI green +
freshness proof → promote to `main` → CI green → finalize
changelog (flips F6.2 green) → tag v3.6.0 → push tag → attach
`dist/checksums.txt` + §2 notes. Release-notes contents, final
matrix with per-cell evidence, open ledger, and receipts are all
in the bundle.

## 7. Known-flake dispositions; incidents; halt log

- Registry + R5.5 (now including nohup SigIgn poisoning): cited
  before anything called new. No registry signature observed.
- **Incident: environment migration mid-wave** (uptime reset,
  /tmp scratch + /mnt/ramdisk/numa1 pregen data lost, jobs dead;
  repo intact through F2 commit). Response: recreated the launcher,
  re-verified gates that depended on lost artifacts (F2 shape,
  coverage 62%), recorded D-matrix numbers from committed reports
  (quads, perf A/B) rather than re-deriving. Pregen-data loss
  means heavy-20M cannot be re-run without regeneration (27GB);
  the D-matrix QUADS-EXACT stands as observed.
- Halt-and-report log: F5 remove-vs-fix (removed with 5-point
  rationale); F6 test interaction (redesigned the test to pin the
  designed-red state instead of weakening the gate); no product
  halts (no C in scope to collide with).

## 9. Final verification runs (post-commit)

- Full `release_check.py`: **19/20, the single failure exactly the
  designed-red changelog guard** (`SOME CHECKS FAILED (1) — DO NOT
  TAG`), everything else green incl. a further full-suite pass,
  tag-freedom, IDL freshness, and the single-build checksums.
- Referee gates 30/30; twins lockstep (72 headings, frun pair);
  R5.3 empty; perf A/B parity (~2%, noise).

## 8. What this does NOT prove

- Version-matrix/deadsnakes/static-analysis/freshness CI legs
  (written + locally validated shape, never executed — first runs
  on `main`).
- `main`-branch CI state (this branch's pushes don't trigger
  main-filtered workflows; F7 step 4 covers it).
- Cross-version skip parity (no version-conditional skips exist
  in-tree, so nothing to diverge — stated, not proved).
- Tag-time changelog finalization (owner act; guard enforces it).
