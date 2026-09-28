# W-REL5 Morning Report — tonight's waves merged + matrix-verified

**Merged tree:** `wrel5-alpha` (beta merged in, plus 2 coordinator fix
commits). **Verification:** full suite 605×3 green, bash 92+264
foreground green, 4 referees 30/30, `release_check` 17/17, C-diff empty.
**Do not tag** — W-REL5-C/D, E-python, BASHCOMPAT-fix, F2–F6 remain.

## Per-wave results

**Track-α — W-REL5-B** (`57fd92c`, 6 commits): B1–B5+B8 landed with
bites (B1/B2/B8 ×5, B3/B5 ×10); B6/B7 verify-only, zero diff; new
`python/tests/test_wrel5b.py` (15 lock-ins); C-diff empty; no flake
hits. **B1 `sink=` decision for ratification: REJECT** (collecting
frontends; payload return IS the result; matches sweep's gate; fails
closed) — `run()` keeps the only legitimate `sink=`.

**Track-β1 — W-REL5-A** (`0264f4b`, 4 commits): A2–A11 done with bites;
twins byte-identical; MAINTAINERS.md:96 fixed (was the actual version
bug). **A1 BLOCKED — spec collision** (literal cloexec=1 breaks the
cleanroom exec + read-only JIT path; no tree change). Proposed design:
cloexec=1 **plus** explicit non-cloexec fd pass-through at the
cleanroom exec site (morning decision or fold into BASHCOMPAT-fix).

**Track-β2 — E-docs** (`a435d97`, 12 commits): E1–E4, E8–E14 + E2 done;
E5/E6/E7/E15 excluded as ordered; deletions enumerated (compile.sh,
2 ungated twins, stage0_harness.py); release_check stayed 17→17;
twins identical. Doc-accuracy rows added for E1/E3.

**Track-β3 — BASHCOMPAT Phase 0** (`960c7e2`, diagnosis only, HALTED):
**headlines for the owner — the evidence contradicts the working
framing.** Proximate CI killer is silent death in the 0.9MB single-line
`declare -A b64=` evaluation (BEFORE any `enable -f` runs), NOT a 5.2
`enable` failure; symbol audit (11/12 present since 4.4; `add_builtin`
never bound) + byte-identical 5.2↔5.3 `builtins.h` refute modes
(a)/(b)/(c); actual .so floor = **4.4**; plus a latent `-e` landmine
(`rm -f` on a live memfd fd → EPERM) that will bite right after any
declare fix under CI's `-e` shell. Docker legs BLOCKED (no daemon).
Full analysis: `dev/supervisor/BASHCOMPAT_DIAGNOSIS.md`. Floor
recommendation stands at **4.4** (E13/RHEL8) — ratify, and decide
whether the fix phase targets the declare-line/`-e` mechanism, the
original 5.3 framing, or both.

## Merge + attribution audit

Merge `wrel5-beta`→`wrel5-alpha`: clean, no conflicts (disjoint
surfaces held). Audit vs base `6757ca0`: 27 files, every file in
exactly one wave's declared surface, with two noted items: (1)
`frun.bash` dual-declared intra-β-track (A logic + E10/E11/E12
help/comment — pre-authorized by both orders, serial application, no
conflict); (2) `DOCS_ALL.md` 2-line in-place correction of the Bash
floor (E13 mandate — unfixable append-only).

## Serial matrix (merged tree, coordinator-run)

| Gate | Result |
|---|---|
| Full Python suite ×3 | 605/605 green (~132s each, 8 skipped) |
| Bash 92 + 264 foreground | green, 0 failures |
| Referees (executor/invariant/doc-accuracy/shim) | 10+4+11+5 = 30/30 |
| `release_check.py` | 17/17 |
| C-diff audit | EMPTY |
| 1M-line perf band (B3/B5) | 636–781 MB/s vs pre-wave 641–788 — no sacrifice |

**One matrix-caught regression, fixed:** B4's bounded joins polled
WNOHANG with `sleep(0.02)` — up to +40ms systematic per run, tripping
`test_c_drain_not_slower` deterministically (merged 0.14s vs base
0.05s; B5 exonerated by monkeypatch probe). Fix: 2ms quantum
(`_resume.py`, deadline/SIGKILL/alarm semantics unchanged) —
single-test 6/6, per-mode medians inside gate (1.28 vs 2.0 budget),
micro-gate green. Residual common-path +4ms/map (B5 sweep overhead)
is scale-invariant and inside the band. Fix commit on `wrel5-alpha`
with full evidence in the message.

**One gate-closure fix:** B's CHANGELOG section lacked its DOCS_ALL
verbatim mirror (release_check twin gate) — 65-line mirror appended.
No test changes were made by the coordinator at any point.

## Incidents + registry dispositions

No genuinely-new failure signatures in any wave (all red was pre-fix
bites or self-inflicted edit errors repaired same-session). Flake
registry: zero hits across tonight's work (no heavy concurrent runs
per protocol). Prior G0 items unchanged: branch CI red is environmental
(small-runner timing on zero-diff paths); R-V2 still open (accept
containment).

## Recommended next dispatches (in order)

1. **W-REL5-C** (needs B: file overlap + C9-on-B5, C2/C6-on-B2).
2. **E-python subset** (E5/E6/E7/E15 — conflicted with B, now mergeable).
3. **BASHCOMPAT fix phase** (needs owner call first: declare-line/`-e`
   mechanism vs 5.3 framing vs both; A1 design decision folds in here;
   blob rebuild folds into D's cycle).
4. **W-REL5-D LAST** (carries BASHCOMPAT engine shims + own sites; one
   blob cycle + full matrix). 5. F2–F6 → main → tag prep (owner
   ratifies tag).

## Owner ratifications needed (3 + 1)

1. B1 `sink=` REJECT — ratify.
2. Bash floor **4.4** — ratify.
3. BASHCOMPAT fix targeting (declare-line/`-e` vs 5.3-framing vs both)
   + A1 cloexec+passthrough design — decide.
4. Tag path stands (no tag executed; nothing pushed to release branch).
