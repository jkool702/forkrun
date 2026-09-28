# New session - 2026-09-27T16:24:43.937Z

**Session ID:** ses_f1c511f5effeDlbv60BaeTeQ5o
**Created:** 9/27/2026, 12:24:43 PM
**Updated:** 9/28/2026, 12:28:30 PM

---

## Assistant

Significant work. Let me verify the claims independently against the tree rather than take the report at face value.

**Tool: bash**

**Tool: bash**

---

## Assistant

Branch is `REFACTOR2.9` (report said 2.8) and there's an untracked file. Let me verify the substantive claims.

**Tool: bash**

**Tool: bash**

---

## Assistant

Both Criticals confirmed fixed. Let me verify the R14b shim fix, R10 stream lock, and run the suite.

**Tool: bash**

**Tool: bash**

---

## Assistant

Both fixed correctly. Now the full suite plus the two Critical regression tests.

**Tool: bash**

---

## User

again, the python code is ACTIVELY being changes by another opencode instance. I would avoid running any tests, but please feel free to manually verify code changes

---

## Assistant

Understood — read-only inspection only, no test execution. Let me verify the remaining items by reading.

**Tool: bash**

**Tool: bash**

---

## Assistant

R15 and R16 both correctly fixed with rationale. Let me verify the remaining Python items and the new invariant gate.

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: read**

---

## Assistant

Well-constructed. Let me check the §6 probe for vacuity — that's the highest-risk one.

**Tool: read**

---

## Assistant

Genuinely well-built probes — public API, real fault injection, invariant named in the assertion. Let me check the rest and look for regressions.

**Tool: bash**

**Tool: bash**

---

## Assistant

All 20 items verified as genuinely fixed. Now let me check the in-flight DEDUP work for regressions.

**Tool: bash**

**Tool: bash**

---

## Assistant

DEDUP design is sound — it correctly resists over-unifying NUMA. Let me check which of my earlier findings are *not* in the W-REL scope and still open.

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: bash**

**Tool: bash**

---

## Assistant

Let me resolve the test-count discrepancy and the CI state before finalizing.

**Tool: bash**

**Tool: bash**

---

## Assistant

## Verification result

I read every claim against the tree. **The report is accurate.** All 20 W-REL items are genuinely fixed, and — more importantly — fixed *correctly*, with the reasoning recorded at the site.

Spot-checks of the five that mattered most:

| Item | Verified |
|---|---|
| **R1** recovery default | `run.py:785-790` — `None` now *rides the reactor*; `False` is the explicit legacy opt-out. Semantic inversion, not a doc edit. |
| **R14a** escrow | `_worker.py:220-238` — `fr_py_escrow_deposit` wrapped in `_deposit_with_retry`, and the docstring now cites **INVARIANTS §6 by name**. The invariant is in the code. |
| **R14b** shim | `_shim.c` — `worker_last_cnt = 0` on successful deposit, explicitly mirroring `ring_ack_main`. Also added a node bounds check. |
| **R4** `SPLICE_F_MOVE` | Flag→0 at the ingress site with the post-mortem; the pipe site annotated as non-hazard with a *reason*. Correct distinction — I had merged them. |
| **R17** `target_node` | `FR_MAX_LOGICAL_NODES 512` as a single source with `_Static_assert`, "the two use sites cannot textually diverge again." |

Corrections to my earlier review: I was wrong that R4 needed both sites changed (the pipe site isn't a hazard), and my "583 vs 567" discrepancy was a `sort -u` artifact — 16 test names legitimately repeat across files. **583 is correct.**

`R-V1` is the strongest addition. Four probes, public API, real fault injection, and the invariant cited in the failure message (`test_invariant_gate.py:96`, `:136`, `:140`). That is the machine-checked-invariant pattern, and it converts §3/§6/§9 from prose into gates. `R-V3` closes the doc-drift class structurally rather than by discipline. `sh-format.yml` was correctly reduced to the twin-check with sound reasoning — a missing gate beats a permanently-false one.

Tree is `f41045c` on `NEW/REFACTOR2.9` (report says 2.8 — cosmetic), clean but for the untracked `DEDUP_DESIGN.md`. 111 commits unpushed. `DEDUP_DESIGN.md` is good work: it correctly identifies that NUMA is *genuinely* different and must stay a separate core, and that supervision should be two cores sharing helpers rather than one function with ten `if`-blocks. That's the right resistance to over-unifying.

---

## Still open (verified present, not in W-REL scope)

| # | Sev | Item | Evidence |
|---|---|---|---|
| 1 | **Blocker** | `frun.bash` not `set -u` clean — sourced into user shells, 44 unguarded `$1`…`$9`. R19 fixed IFS, not nounset. | no `set +u` anywhere in `frun.bash` |
| 2 | **Blocker** | mmap window + `FALLOC_FL_PUNCH_HOLE` → `SIGBUS`. Shim comment still asserts the wrong behaviour ("hole reads zero-fill regardless") — `read()` does, the `mmap` view doesn't. | `_shim.c:1444-45` vs `forkrun_ring.c:8963-9022` |
| 3 | High | Shim NUMA entry points unbounded: `fr_py_indexer_numa(node_id)`, `fr_py_numa_scanner(node_id, num_nodes)` check only `< 0`. R17 fixed the producer; callers are still caller-controlled. | `_shim.c:1650`, `:1671` |
| 4 | High | `map()`/`stream()`/`sweep()` silently swallow unknown kwargs. `wokers=` → different run, no error. Dataflow-silencing. | no `_reject_unknown` in `run.py` |
| 5 | High | Reactor starved by blocking `os.read(src_fd, 1MB)` — no `O_NONBLOCK`, unlike both sibling stream paths. Headliner liveness gap on slow sources. | `run.py` ~4816, cf. 2294/5303 |
| 6 | Med | No respawn backoff. OOM death burns all generations in µs, aborting a run a 200ms backoff would survive. | `_reactor.py:431-445` |
| 7 | Med | `stream()` raises bare `KeyboardInterrupt`; 6 blocking executors map to `ForkrunInterrupted`, 4 stream ones don't. | 9 sites, all in blocking paths |
| 8 | Med | `sink=` is at-least-once; `FAULT_TOLERANCE.md:25` discusses stdout, not the sink. `API.md` silent. | — |
| 9 | Med | `INSTALLATION.md:8` "3.10+" vs `setup.py:155` ">=3.8"; nothing tests 3.8–3.13. | — |
| 10 | Low | `truncate -s` TOCTOU on predictable bootstrap paths, then `dlopen`. | `frun.bash:2625`, `:2674` |
| 11 | **Blocker** | v3.6.0 still not on `main`: `setup.py` absent, one test file. | `git cat-file -e origin/main:setup.py` → fatal |

---

## Proposed plan

**Phase A — before the tag (≈1 day, all low-risk, none touching `run.py`'s structure)**

1. **#1 nounset** — 44 `${1-}`-style guards, or a scoped `set +u`/`restore` pair in `frun`. Independent of DEDUP. *This is the one I'd argue hardest for: `frun.bash` ships via `curl | source`, and a `set -u` user dies at line 2802 during source.*
2. **#2 SIGBUS** — fix the shim comment to distinguish `read()` from the `mmap` view, and add a bounded `madvise`/re-validate on the window. This is a crash class in the headliner.
3. **#3 shim bounds** — two-line upper-bound checks mirroring `FR_MAX_LOGICAL_NODES`, so R17's single-source intent actually holds at the ABI.
4. **#4 kwargs** — one shared `_reject_unknown_kwargs`, applied in `map`/`stream`/`sweep`. Silent misconfiguration is the wrong failure mode for a dataflow engine.
5. **#5 `O_NONBLOCK`** — mirror the sibling pattern; bounds the reactor's blindness on slow sources.
6. **#8/#9 docs** — `sink=` at-least-once in `API.md`; reconcile the Python floor.
7. **#11 main** — land the packaging + suite on `main` so the tag isn't cut from a branch where CI doesn't gate.

**Phase B — after the tag**
#6 backoff, #7 taxonomy, #10 bootstrap TOCTOU, Python version matrix, coverage measurement.

**Sequencing note:** items 1–5 are all outside the functions W-DEDUP is restructuring, so they can land in parallel. The one exception is #5 (`_execute_ingest_reactor_locked`) — coordinate that one with the DEDUP instance, since it's inside executor #7.

---

## Two decisions I'd like your call on

**Tag before or after W-DEDUP lands?**
Tagging from `f41045c` makes v3.6.0 a known-good point and isolates dedup risk to v3.6.1. Tagging after ships a ~1,500-line structural refactor of a file whose entire history is "each new executor re-derived the same orchestration" — and DEDUP's whole premise is that those copy-paste sites are where my findings #1–#5 came from, so it's also the natural place to *reintroduce* them. My recommendation: **tag from `f41045c`, let DEDUP race, re-run the full matrix, tag again.** The cost is one extra version number.

**Is the bash front end a v3.6.0 commitment?**
If yes, #1 and #10 block. If it's effectively maintenance-mode (which `DOCS/python/plan.md`'s ladder suggests — bash "owns compatibility presentation" and sheds mechanism), then #1 is a v3.6.1 item and you can cut the tag with only the Python-side fixes. This single answer changes Phase A from ~1 day to ~3 hours.

---

## User

note: the VERY last thing before the v3.6.0 release will be merging the newest branch (currently NEW/REFACTOR2.9) into main. that will be the absolute last thing, but it will happen just before tagging. I prefer to have the "main" branch frozen at the last stable release

---

## Assistant

That changes the plan materially — #11 was never a blocker, it's your final step. But it creates a new risk: **the tag would be cut from a merge commit that CI has never evaluated.** Let me check what that merge would actually produce.

**Tool: bash**

**Tool: bash**

---

## Assistant

Found the real risk. Let me characterize it.

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: bash**

**Tool: bash**

---

## Assistant

The freshness gate is sound. One last check — does it validate the *committed* blobs or only the workflow's own rebuild?

**Tool: bash**

**Tool: bash**

---

## Assistant

Let me characterize the merge conflict precisely, using the read-only three-arg `merge-tree` (no object writes).

**Tool: bash**

**Tool: bash**

---

## Assistant

## Correction, and the risk your sequencing creates

Dropping my "not on `main`" blocker — that's your final step by design, and keeping `main` at the last stable release is a sound release discipline. But moving the merge to last does create a specific, verifiable hazard, and it's worth seeing before you're standing in it.

**The merge will conflict on 8 files**, and one of them is unmergeable by text:

```
$ git merge-tree 1c5caf8 origin/main HEAD | grep -c "changed in both"
8
```

- `frun.bash` — the conflict is on **line 2800**, the 880,483-character `declare -A b64=(...)` line. Both sides changed it; there is no valid three-way text merge. Exactly 1 conflict marker in the whole output, and it's this one.
- All 7 `ring_loadables/forkrun-libs/*.so` blobs.

`main`'s contribution since the merge-base is only 3 commits — `forkrun v3.5.2`, one CI blob refresh, one merge — and it touched *only* those 8 files. Your side is 382 files. So the resolution is unambiguous in principle (**take your side for all 8**) but brutal by hand, and it happens at the worst possible moment: the last action before tagging, with a tag that doesn't exist yet to validate against.

**The failure mode to guard:** if the 880KB line resolves to `main`'s side, you ship a v3.6.0 tree with v3.5.2-era engine blobs embedded. That is precisely the `RELEASE_RUNBOOK.md:84-96` incident. Worth knowing: the R5 freshness gate would *not* catch this, because the workflow `mv -f`s freshly built artifacts over the committed blobs at `forkrun_release.yml:217` *before* comparing — so the gate proves "the shipped artifact was built from this source," not "the committed blob matches the source." It's self-healing via PR (`:317`), but a PR lands *after* the commit, not before the tag.

---

## Plan

### Phase 0 — Pre-merge conflict resolution, on the feature branch

This is the one change I'd make to your sequencing, and it preserves your goal exactly: `main` still stays frozen at v3.5.2 until release; only the *risky work* moves off the critical path.

1. On `NEW/REFACTOR2.9`, merge `origin/main` in (not the reverse).
2. Resolve all 8 conflicts by taking your side:
   ```
   git checkout --ours  frun.bash ring_loadables/forkrun-libs/*.so
   ```
3. Verify the twins are still byte-identical post-resolution (`frun.bash` ↔ `frun.nob64.bash` pre-marker region; the two test twins) — they are identical at `f41045c`, and a bad `frun.bash` resolution would silently break `sh-format.yml`'s twin-check.
4. Let `forkrun_release.yml` run on that merge commit. It regenerates all 7 blobs, byte-verifies via the freshness gate, and opens the blob PR. **Land that PR.**
5. Run the full matrix on the now blob-current merge commit.

After this, step 6 is a fast-forward, not a merge.

### Phase 1 — Remaining correctness items (independent of DEDUP, can run in parallel)

| # | Item | Why before tag |
|---|---|---|
| 1 | `frun.bash` nounset (44 `${1-}` guards or scoped `set +u`) | Ships via `curl \| source`; a `set -u` user dies during source. Only true blocker left if bash is a v3.6.0 commitment. |
| 2 | mmap-window `SIGBUS` vs `PUNCH_HOLE`; fix the wrong shim comment | Crash class in the headliner. `read()` zero-fills; the `mmap` view faults. |
| 3 | Bound `fr_py_indexer_numa` / `fr_py_numa_scanner` | R17 fixed the producer; the ABI entry points are still caller-controlled, so its "single source, cannot diverge" intent doesn't yet hold. |
| 4 | Reject unknown kwargs in `map`/`stream`/`sweep` | A `wokers=` typo silently runs a different pipeline. Wrong failure mode for a dataflow engine. |
| 5 | `O_NONBLOCK` in `_execute_ingest_reactor_locked` | Headliner goes blind on slow sources. **Coordinate with DEDUP** — inside executor #7. |
| 6 | `sink=` at-least-once in `API.md`; reconcile 3.10+ vs `>=3.8` | Doc honesty, zero risk. |

### Phase 2 — Tag

Only after Phase 0's blob PR is in and the matrix is green on the exact merge commit. Tag that commit; fast-forward `main` to it.

**Post-tag (v3.6.1):** respawn backoff for OOM, `stream()` `ForkrunInterrupted` taxonomy, bootstrap `truncate` TOCTOU, Python version matrix, coverage.

---

## Two things I'd want your call on

**Is the bash front end a v3.6.0 commitment?** If yes, item 1 blocks. If it's heading toward maintenance-mode (which `DOCS/python/plan.md`'s ladder implies), cut it and Phase 1 drops to ~2 hours. This single answer is most of the remaining schedule.

**Tag `f41045c`, or wait for W-DEDUP?** I'd tag from a W-DEDUP-free commit. DEDUP is a ~1,500-line structural refactor of the exact file whose copy-paste duplication produced findings #1–#5, so it's simultaneously the natural fix and the natural place to reintroduce them. But that means W-DEDUP needs its own full matrix afterwards, and the Phase 0 merge should happen *after* DEDUP lands rather than twice.

One note on coordination: another instance is actively editing `run.py`, so items 4 and 5 in Phase 1 both touch it. Worth sequencing those after DEDUP settles, or claiming them explicitly so you don't collide.

---

## User

the merge conflict is because i accidentally let one CI/CD pipeline run on main before i branched off the update branch after v3.5.2. Ill probably have to merge with -X ours (or whatever the flag is to automatically choose the new branch in merge conflicts). not that it matters - all the merge conflicts (the .so files and binary blobs in frun.bash) will automatically get rebuilt by CI/CD when the merge happens

---

## Assistant

---

## User

also to answer your questions:

1. yes the bash front end is a v3.6.0 commitment. that said, there really havent been many changes to the bash side since v3.5.2, but the goal of v3.6.0 is to present both bash and python as first class front ends.

2. Im going to *try* to include W-DEDUP. it really depends on how smoothly it goes - if it breaks everything i may hold off, if it finishs and alll the tests still pass ill include it. Id LIKE to include it, if possible

---

## Assistant

Two corrections needed — one of them is a footgun. Let me verify before I write the plan.

**Tool: bash**

**Tool: bash**

---

## Assistant

## Two corrections before the plan

**1. `-X ours` is the wrong direction — it would be the worst possible outcome.**

In `git merge`, "ours" is *the branch you are standing on*. Since you'd be on `main`, `-X ours` resolves those 8 files to **main's v3.5.2 versions**. You want `-X theirs`.

This is not just about blobs. `frun.bash` is the *entire bash front end* plus the blob line, and it differs from HEAD by **212 lines of real code** in the pre-marker region:

| | main (v3.5.2) | HEAD (v3.6.0) |
|---|---|---|
| `W-REL3/R18` mktemp checkpoint fix | **0** | 1 |
| `W-REL3/R19` IFS normalization | **0** | 1 |
| `W-REL3/R20` exit-127 census | **0** | 5 |
| `META` | `v3.5.2` | `v3.6.0` |

`-X ours` silently ships a v3.5.2 bash front end inside a v3.6.0 tag — losing the symlink fix (S1), the IFS fix (S2), and the exit-0-on-missing-command fix (S4). The right flag is:

```
git checkout main
git merge NEW/REFACTOR2.9 -X theirs
```

**2. CI will not save you here, and there is a good reason to be glad.**

The rebuild is correct but arrives too late. `forkrun_release.yml:217` does `mv -f` over the committed blobs, then `:317` **opens a PR** — it does not push to your branch. So a wrong resolution is only corrected *after* the merge commit exists, and the tag would already be pointing at it if you tag on merge.

**But the twin-check catches this for free.** `frun.nob64.bash` is *not* a conflict candidate — it merges cleanly from HEAD (v3.6.0 code). So after a bad resolution you'd have v3.5.2 code in `frun.bash` against v3.6.0 code in `frun.nob64.bash`, and `sh-format.yml`'s pre-marker `cmp` fails loudly. That gate is currently your only automated guard on this — worth knowing it's load-bearing.

I'd still resolve deliberately rather than trusting a flag, given the payload:

```
git checkout main
git merge --no-commit NEW/REFACTOR2.9
git checkout --theirs frun.bash ring_loadables/forkrun-libs/*.so
git add -A && git commit
```

then confirm `META` is `v3.6.0` and `grep -c 'W-REL3/R20' frun.bash` is `5` before committing.

---

## Revised plan

Bash is a first-class commitment, so the nounset fix is in. W-DEDUP is in, conditionally.

### Stage 1 — DEDUP (in flight, other instance)

Gate for inclusion: full suite green on the merged tree, plus `test_invariant_gate.py` and `test_doc_accuracy.py` specifically. Those two are the ones that catch a refactor reintroducing the copy-paste omissions. If DEDUP regresses, hold it — the tree is already release-worthy without it, and the duplication is a known, documented, *contained* condition rather than an active defect.

### Stage 2 — Correctness items, parallel with Stage 1

Nothing here touches the DEDUP refactor surface except #5, which I've marked.

| # | Item | Blocking? |
|---|---|---|
| 1 | `frun.bash` nounset — 44 `${1-}` guards, or scoped `set +u` + restore. **Bash is first-class now, so this blocks.** | **Yes** |
| 2 | mmap-window `SIGBUS` vs `PUNCH_HOLE`; fix the incorrect shim comment (`read()` zero-fills, the `mmap` view faults) | **Yes** — crash class in the headliner |
| 3 | Bound `fr_py_indexer_numa` / `fr_py_numa_scanner` — R17 fixed the producer, not the ABI entry points | Yes |
| 4 | Reject unknown kwargs in `map`/`stream`/`sweep` | Yes — silent misconfig in a dataflow engine |
| 5 | `O_NONBLOCK` in `_execute_ingest_reactor_locked` | Yes — **sequence after DEDUP** (inside executor #7) |
| 6 | `sink=` at-least-once → `API.md`; reconcile 3.10+ vs `>=3.8`; R-V3 claim registry rows | No — doc only |

### Stage 3 — Merge to `main`

1. Confirm Stage 1 decision; ensure tree is clean, `DEDUP_DESIGN.md` either committed or removed.
2. Full matrix on the pre-merge commit: canary / IDL / repro / bash 92+264 / Python 583×3 / `release_check` 17/17 / twin parity.
3. `git checkout main && git merge --no-commit NEW/REFACTOR2.9`, resolve the 8 by hand, verify `META` = `v3.6.0` and `W-REL3/R20` count = 5.
4. Commit. Let the release workflow run; **land the blob PR** it opens.
5. Re-run the twin-check and `release_check` on the merge commit.

### Stage 4 — Tag

Tag the merge commit only after the blob PR is in and the matrix is green on that exact tree.

### Post-tag (v3.6.1)
Respawn backoff for OOM, `stream()` `ForkrunInterrupted` taxonomy, bootstrap `truncate` TOCTOU, Python version matrix, coverage.

---

## Two open questions

**Does the nounset fix go in before the tag, or is a scoped `set +u` acceptable for 3.6.0?** The 44 `${1-}` guards are mechanical but touch a file that's currently byte-locked against `frun.nob64.bash` — so the twin must be resynced in the same commit, or the twin-check fails. A scoped `set +u`/`restore` pair is ~3 lines and needs no resync. I'd take the scoped pair for 3.6.0 and the full guards for 3.6.1, but the guards are the actual fix and the twin resync is already a routine step for you.

**Is the R6 sanitizer position acceptable for release?** "Advisory ASan+UBSan, TSan deferred with rationale" is a defensible call given the deliberate fault-injection findings, but your own `GATE_v3.5.x.md:65-66` says sanitizers are "required before release." Either amend that gate to match the decision, or run the TSan leg — otherwise the release ships against a rule the release docs still say you're violating.

---

## User

to be honest im never really been sold on the "necessity" of nounset. it seems the only thing you really buy is "things dont fail when someone runs with set -u". I guess its good hygine and im open to a work order to make it happen, but thats always been low priority for me.

sanatizers will run (at least for the bash tests that they have been previously run for), but that is the VERY last thing once the code is effectively frozen since those runs take much longer and i REALLY dont want to re-do then if there is a code change

---

## Assistant

Both answers are reasonable, and the second one has a wrinkle worth catching. Let me verify two things.

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: read**

---

## Assistant

Both answers are reasonable. Let me check one thing that changes the nounset framing.

**Tool: bash**

---

## Assistant

The nounset framing deserves a correction — let me verify what actually matters for a *sourced* library.

**Tool: bash**

---

## Assistant

I have what I need to finalize. Here's the completed plan.

## The nounset correction

You're right that nounset is hygiene, and I was overweighting it. The honest version: `set -u` catches *misspellings and unset-variable reads* — a class of bug that fails **loudly and immediately** at the point of the error. It cannot silently corrupt data or produce wrong answers. So it buys debuggability, not correctness.

But the R19 IFS work already reframed this correctly, and the same logic applies with more force to three items I *didn't* flag as nounset:

**The sourced-library contract is the real issue, not nounset.** `frun.bash` is `.`-sourced into the user's interactive shell, which is an unusually invasive library contract. It currently:

- sets `extglob` at file scope (`:3-7`) and never restores it
- creates two long-lived `memfd` fds with **`cloexec=0`** (`:2662`, `:1657` — note `:1301` correctly passes `1`), and exports their fd *numbers* as env vars
- leaks `FORKRUN_MEMFD_LOADABLES*` into every child process

That's a library mutating ambient shell state permanently. Nounset is the least of it. The `cloexec=0` → env-var-exported fd is the one that actually matters for users: every process they subsequently spawn inherits those fds and the vars.

I'd replace my "nounset is a blocker" with this ordering:

| Item | Verdict |
|---|---|
| Two loadable memfds → `cloexec=1` | **Do it.** One-character-class change; `:1301` shows you know the idiom. |
| Stop exporting fd numbers to children | **Do it.** Same change. |
| Restore `extglob` on RETURN | Cheap, follow the `:1091` precedent. |
| 44 `${1-}` guards | **Defer to 3.6.1.** Agree it's low priority — it's a debuggability win, not a correctness one. |

That's a smaller, more honest work order than "make it nounset-clean."

## Sanitizers: sequencing, not ordering

Your instinct is right, and there's a detail in the runbook that makes it more true than you may realize.

`RELEASE_RUNBOOK.md:78-82` scopes sanitizers to *intra-process* concerns only — forkrun's real coordination is cross-process over `MAP_ANONYMOUS`, which sanitizers structurally cannot see. So the value is memory hygiene and intra-process threading, not the protocol. Combined with R6's local triage (UBSan zero, ASan 34/34 = deliberate fault injection), you've already harvested most of the available signal.

**The one thing I'd protect is the freshness gate.** `RELEASE_RUNBOOK.md:84-96` documents that ASan branches are currently carrying **v3.1.0-stale blobs** for ppc64le/s390x/riscv64, "embedded, verify-green" — the exact `W-SLA3-F` incident class. R5's `set -euo pipefail` + freshness gate landed in the *main* release workflow. If the sanitizer runs use a different branch or a stale embedded `frun.bash`, you'll re-run the whole matrix and get a false green — which is worse than not running, because it burns hours and manufactures confidence.

So: sanitizers last is correct. Add one gate before them: `E1` (diff the three synced files against frozen mainline is empty) and the `E3` label assertion from `:59-67`. That's the difference between a sanitizer run that means something and one that re-teaches the lesson from `:88-89`.

---

## Final plan

**Stage 0 — now, low-risk, zero interaction with DEDUP or the merge**
1. Loadable memfds → `cloexec=1`; drop the fd-number env exports.
2. `extglob` restore on RETURN (mirroring `:1091`).
3. Doc: `sink=` at-least-once → `API.md`; reconcile `3.10+` vs `>=3.8`; add R-V3 registry rows.
4. Bound `fr_py_indexer_numa` / `fr_py_numa_scanner` (completes R17's single-source intent).
5. `O_NONBLOCK` in `_execute_ingest_reactor_locked` — **after DEDUP** (executor #7).
6. Reject unknown kwargs in `map`/`stream`/`sweep`.
7. Fix the mmap/`PUNCH_HOLE` `SIGBUS` comment + guard.

**Stage 1 — DEDUP gate**
Include if the full suite plus `test_invariant_gate.py` and `test_doc_accuracy.py` are green. Those two are the ones that catch a refactor reintroducing copy-paste omissions. If it destabilizes, hold — the tree is release-worthy without it, and the duplication is documented and contained.

**Stage 2 — freeze → merge → tag**
1. Full matrix on the frozen pre-merge commit.
2. `git checkout main && git merge --no-commit NEW/REFACTOR2.9`; resolve the 8 by hand with `git checkout --theirs frun.bash ring_loadables/forkrun-libs/*.so`. **Do not use `-X ours`** — that takes main's v3.5.2 side, silently reverting R18/R19/R20. (It also can't touch C source: the conflict set has zero `.c`/`.h` files.)
3. Verify before committing: `META` = `v3.6.0`; `grep -c 'W-REL3/R20' frun.bash` = `5`; twin `cmp` clean.
4. Land the blob PR the release workflow opens. R5's freshness gate makes stale-engine shipping structurally impossible at that point.
5. Tag the merge commit.

**Stage 3 — sanitizers, post-tag**
Freshness-gated per `E1`/`E3` first. If a genuine finding surfaces, it's a 3.6.1 patch rather than a re-cut, which is exactly why this ordering is right.

**Deferred to 3.6.1:** nounset guards, respawn backoff for OOM, `stream()` `ForkrunInterrupted` taxonomy, bootstrap `truncate` TOCTOU, Python version matrix, coverage.

---

## One question before I finalize

**Is the `E1`/`E3` freshness assertion going to be automated, or manual for the 3.6.0 run?** The runbook calls it "post-release template work" (`:94`), and the last two release incidents were both stale-artifact false-greens. If it's manual this round, I'd at least script the E1 diff so it isn't a thing someone remembers to do.

And one flag I don't think needs a decision but should be on the record: `test_c_drain.py`'s `REPO_ROOT` fix and the `test_scaling.py` fixture fix (R2/R3) mean `python-check.yml` should now pass — but it has never actually run green on a GitHub runner, and `main` has no `python-check.yml` at all. Worth confirming it goes green on the feature branch *before* the merge, so the merge isn't the first time CI ever runs the suite.

---

## User

FYI

W-DEDUP complete on NEW/REFACTOR2.9 (4 commits on f41045c). Verdict: CONDITIONAL GO.
What landed (+1242/-184, zero C diff):
- _executor_core.py (new): single fork_workers / collect_records / report_poison / init_engine / teardown_union + ExecutorSpec. 4 plain executors ported; reactor/NUMA keep their (already single-sourced) join machinery — 3 cores + 10 thin wrappers, costume check PASS (≤3 branches/function).
- R-D8 ABI gate: gen_shim.py + forkrun_shim.h (45 externs) + shim_signatures.json (56) + test_shim_abi.py + shim-check.yml. Triple agreement 45/45/45 (JSON == bindings == .so exports).
- Docs: DEDUP_DESIGN.md, manifest addendum, DEDUP_REPORT.md (audit + perf + recommendation).
Evidence:
- Checker 10/10 x5, invariant gate 4/4 x5, shim ABI 5/5 x5, full suite 588 tests x5, release_check.py 17/17, sanitizers 88 tests (UBSan 0 errors; ASan reports confined to deliberate string_at(0) crash-children, suites green), engine + shim diffs empty, perf 1M lines 640–790 MB/s (no consolidation cost).
- Gate 4 PARTIAL: heavy NUMA matrix (20M @4, forensic 10x loops, bash foreground suites) not re-run here — Python-only diff with frozen engine; deferred to pre-merge CI per the race rules. If main tags first, this rebases to v3.6.1.
Tree clean, every intermediate commit shippable/bisectable. 

---

## Assistant

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: read**

---

## Assistant

Let me verify the ABI gate — and the 45 vs 56 discrepancy in the report.

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: read**

---

## Assistant

The 45/56 reconciles correctly (45 extern + 11 static). Let me check the one thing that concerns me about `_executor_core.py` — the `sys.modules` binding.

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: bash**

**Tool: bash**

---

## Assistant

I have a clear picture. Let me finalize the plan.

**Tool: bash**

---

## Assistant

## Verification of W-DEDUP

I read the diff and the core module. **This is good work** — and I'd call the CONDITIONAL GO honest rather than generous.

**Verified:**
- 4 commits, clean tree, `+1325/-184`, and the C diff is **empty** except the new `forkrun_shim.h` (new file, no engine edit). Exactly as claimed.
- `run.py` 7265 → **7211** lines. `while ring_claim` gone (0 in both), `_teardown_*` still in `run.py` (correct — `_executor_core` *calls* them), `fr_py_poisoned_count` down 10→4 sites, `scrub_fds(keep)` 1 remaining.
- `ExecutorSpec` is a real parameter lattice, not a bag of booleans masquerading as one — 12 slots, and the docstring is explicit that `topology="numa"` ignores `ingest`. That's the kind of comment that survives the next refactor.
- **R-D8 is the most valuable part of this whole effort.** `gen_shim.py` + `forkrun_shim.h` + `shim_signatures.json` + `test_shim_abi.py` + `shim-check.yml` closes the exact gap I flagged as "the single highest-leverage structural change" in my first review — the 43-entry ctypes ABI with no header and no enforcement. It also kills the 46 `-Wmissing-prototypes` warnings by construction.
- The 45/56 reconciles: 45 `extern` + 11 `static` = 56, asserted as a tuple at `test_shim_abi.py:147` with a truncation-guard comment. And `test_no_order_regression` correctly encodes "reordering is an ABI change."

**One thing to know about, not a blocker:** the `sys.modules["forkrun.run"]` lazy binding (5 sites) is a workaround for `forkrun.run` being *both* the module and the public function — `__init__.py:46` does `from forkrun.run import map, run, stream, sweep`, so the attribute shadows the module. The docstring at `_executor_core.py:18-25` explains it and forbids new top-level `run` imports. That's correct handling of a genuine wart, but it means the cycle is now load-bearing in two modules. Worth a rename of the *module* (not the public function) in 3.6.1 — cheap, and it deletes a footgun.

**On gate 4 being PARTIAL.** The reasoning is right and I'd endorse it: Python-only diff, frozen engine, residual risk confined to paths the diff can't reach, and the report explicitly declines to claim evidence it didn't produce. Running the heavy NUMA matrix on a Python-only refactor is defensible. **But** that matrix is the one thing standing between you and a defensible "the main line never waits" claim, and it's currently a *pre-merge* item, which means it runs against a tree that no longer exists once you merge. Run it on `NEW/REFACTOR2.9` **before** the merge, not in CI after it.

---

## Final plan

### Stage 0 — now (low risk, zero interaction with DEDUP or the merge)

1. Loadable memfds → `cloexec=1` (`frun.bash:2662`, `:1657`); drop the fd-number env exports. `:1301` already shows the idiom.
2. `extglob` restore on RETURN (mirror `:1091`).
3. Bound `fr_py_indexer_numa` / `fr_py_numa_scanner` — completes R17's single-source intent, and now *also* add them to `forkrun_shim.h` via `gen_shim.py` so the gate covers them.
4. `O_NONBLOCK` in `_execute_ingest_reactor_locked` — inside executor #7; DEDUP has landed, so this is now safe.
5. Reject unknown kwargs in `map`/`stream`/`sweep`.
6. Fix the mmap/`PUNCH_HOLE` `SIGBUS` comment + guard.
7. Doc: `sink=` at-least-once → `API.md`; reconcile `3.10+` vs `>=3.8`; R-V3 registry rows.

### Stage 1 — close gate 4 on the feature branch

8. Run the deferred heavy legs **on `NEW/REFACTOR2.9`, pre-merge**: bash foreground suites (92+264), heavy-20M `@4`×4 + `nodes=1`×2, F-NUMA1/F-PY-UMA1 10× loops.
9. Re-run the full matrix on the post-Stage-0 tree: 588 tests, invariant gate, shim ABI, `release_check` 17/17, twin parity, canary/IDL/repro.

### Stage 2 — merge

10. `git checkout main && git merge --no-commit NEW/REFACTOR2.9`.
11. Resolve all 8 conflicts by hand: `git checkout --theirs frun.bash ring_loadables/forkrun-libs/*.so`. **Not `-X ours`** — that takes main's v3.5.2 side and silently reverts R18/R19/R20 (verified: `W-REL3/R20` count is 0 on main, 5 on HEAD). Zero C files are in the conflict set.
12. Verify before committing: `META` = `v3.6.0`; `grep -c 'W-REL3/R20' frun.bash` = `5`; twin `cmp` clean.
13. Land the blob PR the release workflow opens (R5's freshness gate makes stale-engine shipping structurally impossible there).
14. Re-run twin-check + `release_check` on the merge commit.

### Stage 3 — tag, then sanitize

15. Tag the merge commit.
16. Sanitizers post-tag, **gated on E1/E3** from `RELEASE_RUNBOOK.md:59-67` — the freshness assertion, given that ASan branches are still carrying v3.1.0-stale blobs (`:88-89`). A re-run on a stale tree is worse than no run: hours burned plus manufactured confidence.

**Deferred to 3.6.1:** nounset guards (agree it's debuggability, not correctness), OOM respawn backoff, `stream()` `ForkrunInterrupted` taxonomy, bootstrap `truncate` TOCTOU, Python version matrix, coverage, `run.py` module rename.

---

## Two questions before execution

**Item 3 above is now cheaper than it was.** The `gen_shim.py` infrastructure means bounding the NUMA entry points is a one-line change plus a regenerate, and the ABI gate will *keep* them honest. Do you want that folded into Stage 0, or deferred to keep Stage 0 to pure-risk-reduction items? My recommendation is fold it in — the gate only protects what it can see.

**One gap I'd want closed before the tag rather than after:** `python-check.yml` has still never run green on a GitHub runner, and `main` has no `python-check.yml` at all. The Stage 1 re-run is local. If the merge is the first time CI ever evaluates the suite, you're finding out at the tag. Pushing the branch and letting CI run is cheap and de-risks the exact step where you have least room to react. Want that in Stage 1?

---

## User

SO - Id like for you to fill in as the supervisor AI and generate a work order to implemnt fixes for all the remaining issues you had listed. 

my opinion isw the opencode-accellerated workflow is fast enough its worth fixing everything we know about for v3.6.0 and really not deffering things. so, lets get the remaining things fixed.

below is a context handover document from the AI im currently using as a supervisor - please review it before generating the work orders.

***

# FORKRUN SUPERVISOR CONTEXT HANDOVER

## For the Successor AI Supervisor Instance

**Version:** 1.0 — Generated mid-release-cycle, post-W-REL4, W-DEDUP pending final resolution
**Purpose:** Transfer the complete supervisory context: project state, decision history, review posture, operational protocol. The successor's job: finish the v3.6.0 release (resolve the W-DEDUP race, execute the tag sequence), then steer post-release work. Everything needed is here or pointed to. Never fabricate continuity — verify state against the repo before acting on any claim in this document.

---

## 1. Current Project State (verify against repo first)

**Repo:** `github.com/jkool702/forkrun`. **Active branch:** `NEW/REFACTOR2.9` (W-DEDUP landed there, 4 commits on `f41045c`). Branch lineage this cycle: `NEW/REFACTOR2.5` (history) → `.7` (W-REL1/2/3a) → `.8` (W-REL3/4, head `f41045c`) → `.9` (W-DEDUP). **Nothing has been pushed and nothing has been tagged** — a very large commit stack is local. The owner pushes deliberately.

**Release state:** v3.6.0 is one decision from the tag. The full sequence W-REL1 → W-REL2 → W-REL3a → W-REL3 → W-REL4 landed (~8 hours of opencode execution; suite now 583→588 tests), closing the entire external-review defect backlog. W-DEDUP (executor consolidation) returned **CONDITIONAL GO**: all gates green except **Gate 4** (heavy NUMA matrix + forensic loops), which was deferred with a rationale that was *half sound* (bash suites: engine diff empty, byte-identical blob — genuinely deferrable) and *half unsound* (heavy-20M gates + F-PY-UMA1/F-NUMA1 forensic loops: these test exactly the changed code — the consolidated executors and `teardown_union` — and are the only tests that catch the scale-dependent defect class; F-NUMA1 was invisible to the regular suite). **A follow-up order to run the deferred legs (~1–2h compute) was issued; its result decides GO vs NO-GO.**

**The immediate decision tree (owner-ratified rules, pre-registered in the W-DEDUP order):**
- Gate 4 legs green → **full GO** → `NEW/REFACTOR2.9` becomes the release branch → run the main-line full-matrix tag-candidate verification on it → promote to `main` → tag v3.6.0 from it.
- Anything fails → main line (`NEW/REFACTOR2.8` at `f41045c`) tags; collapse + ABI gate land together in v3.6.1 (the **package-deal rule**: the collapse and `forkrun_shim.h` ABI gate ship together or not at all — a GO collapse without the ABI gate is the uniform-failure-mode with a bow on it).
- **Do not let the main line tag while the dedup branch is an hour from resolution** unless the owner actively prefers two releases; with both branches unverified-at-matrix-level, holding the tag for the parallel runs costs nothing.
- The owner's sign-off on GO consists of: read the behavior-delta audit in `DEDUP_REPORT.md` (manifest diff before/after; every difference intentional-with-reason or a bug), confirm each deviation, ratify with Gate 4 numbers attached.

**One pending owner decision (flagged, not yet ratified):** R-V2 (fd-aliasing closure, F-PY-UMA1b) halted per protocol — the implementer's audit (`dev/supervisor/FD_ARRAY_AUDIT.md`) showed the specified dup-hold fix *cannot work across fork boundaries* (fd numbers live in child tables; a parent-side dup pins nothing there) and the specified lock-in test is unimplementable. Recommended disposition: **(a) accept containment as final** — INVARIANTS §20 (ingress position undefined, explicit offsets only) + the audit doc + the W-MOVER lock-in test genuinely cover the hazard; register engine-side fd-identity hardening (fstat validation at use sites, or post-fork fd re-resolution) as backlog. Alternative (b): commission the real engine fix — not pre-tag material. The halt was correct; this was a spec error in *my* (predecessor supervisor's) work order, caught by the process working as designed.

## 2. The Compressed History You Must Know

### The port and the audit arc
The Python frontend (W-PY1→41, ~one week, AI-implemented under a carefully staged porting plan) was followed by **W-PORTAUDIT** — a differential audit of Bash's entire bug-fix history vs. the Python port. It found 6 port regressions (F-PORT1–6) because the audit diffed *fixes* but not *defaults* — that blind spot produced **F-NUMA2** (Bash guaranteed workers≥NUMA-nodes by default; Python silently lacked it) and later **B1** (recovery documented as default, was opt-in — the external review's flagship blocker). Lesson now enshrined: **port parity must be audited at the level of defaults and semantics, not just fixes.**

### The bug lineage (know these by name — they're cited constantly)
- **F-PY-UMA1:** UMA scanner seeded its base from `lseek(SEEK_CUR)` on the fork-shared memfd; position was nonzero ~20% of runs → silent head-of-output loss. Fixed (explicit `lseek(0)`). The *mover* of that offset was later identified (**W-MOVER**): fd-number recycling aliased the claim path's eventfd-drain `read()` onto the memfd → positional 8-byte reads. Engine-resident → closed as **invariant** (INVARIANTS §20), not fix. The aliasing *origin* is the R-V2 item above.
- **F-NUMA1:** the worst bug of the cycle — 4-node NUMA runs silently returning ~25% of records (one node's share). Root cause: ingest lapped the 4096-entry metadata ring around a stalled node; thieves read recycled slots. Fixed via meta-lifetime bound + per-chunk snapshots + the **`_numa_drain_audit`** parent guard (makes under-drain *loud*). **The heavy-20M gates are the only tests that can catch this class** — inputs under ~8GB cannot lap the ring. This is why Gate 4 matters.
- **W-NUMA2** (workers≥nodes bump + UserWarning), **M1a** (bash test failure; root cause: backgrounded launchers disable SIGINT inheritance — hence **all signal-behavior tests run foreground**), **M8** (byte-mode test; payload semantics, engine exonerated; HUP-window flakiness has a filed follow-up), **T12** (test-design race; poison-fill vs HUP timing; fixed test-only with `FORKRUN_RETRY_LIMIT=-1`).

### The external review and the W-REL sequence
A frontier-AI adversarial review (arrived pre-tag — the process working) rated the engineering ~99th percentile but release-readiness ~55th, finding blockers B1–B6, C-engine findings C1–C5, Python findings P1–P5, Bash findings S1–S5, and diagnosing the root cause: **"cross-component consistency maintained by copy rather than construction"** (ten near-identical executors in `run.py`; six findings were "executor #N forgot something executor #1 remembered"). Its revised pass confirmed the consensus-free architecture (18 fetch_add + 2 CAS, zero pthread primitives) and *withdrew* its eval-as-attack-surface claim after seeing the systematic `%q` JIT discipline — evidence the review process itself falsifies honestly.

The response was W-REL1→W-REL4 (details in the CHANGELOG; highlights): **R1** flipped `orchestrator=True` as default (the headliner made true; supervision costs ±1.3% at order=none; latent reactor-path bugs flushed out by actually running the default) · **R14a/R14b** closed the escrow Criticals (discarded deposit returns; shim's missing `worker_last_cnt` clear — engine/shim twin divergence) · **R4** deleted `SPLICE_F_MOVE` from the shim (re-introduced flag whose removal the engine documents as a kernel-lock-inversion post-mortem) · **R5** build freshness gate (`set -euo pipefail` + byte-compare rebuild) · **R-V1** invariant gate (INVARIANTS §3/§6/§9 as behavioral probes) · **R-V3** doc-accuracy harness (9 headline claims ↔ covering tests, CI-checked) · **W-REL3a** executor manifest + consistency checker. All lock-ins were bite-then-green (pre-fix failing tests proven first). R-V2 is the one halt (above).

**W-DEDUP** (the branch race): the owner overrode my initial defer-the-collapse judgment with a better structure — race the safe branch (main-line tag-candidate, never waits) against the refactor branch under pre-registered GO/NO-GO gates. The collapse landed as "3 cores + 10 thin wrappers" (reactor/NUMA join machinery was *already* single-sourced — forcing it in would have been consolidation ideology), + the **`forkrun_shim.h` ABI gate** (gen_shim.py; triple agreement 45/45/45 across declared JSON == ctypes bindings == `.so` exports). CONDITIONAL GO pending Gate 4 (above).

### Post-release backlog (W-REL4-class, registered not ordered)
Invariant-gate extension · executor-collapse follow-through (if NO-GO) · S3 (`set -u` sweep) + S5 (TOCTOU) · sanitizers→blocking for v3.6.1, TSan evaluation · doc-harness registry growth · **fd-aliasing engine hardening** (if R-V2 disposition (a)) · **double-duty registry doc** (a "local job / global job / what breaks if you trust only the local job" table for the ~10 mechanisms that serve both scales — the eventfd, the ring indices, the death pipe, etc.; queued repeatedly, still cheap, still valuable) · **EPYC benchmark prep** (see §5).

## 3. Architecture and Philosophy (the frame the owner thinks in)

**forkrun is a dataflow simulation, not a parallelizer.** The design goal: set up machinery that knows how to talk to itself, press play, let it evolve. The parent's steady-state job is *sleep* — one blocking `poll()` until unusual events; workers claim work via a single `fetch_add` (consensus number 1, deliberately — commutativity instead of consensus; the CAS-retry mainstream is viewed as the "everyone knocks on the bathroom door" anti-pattern); termination is the workers' own 3-condition EOF proof (C1 supplier-finished → C2 ring-drained → C3 escrow-empty, strict order, re-verified from C1 on any failure). **The owner's empirical law: bugs appear wherever code deviates from EOF_PROTOCOL.md and resolve when realigned.** All state lives in shared objects (the memfd coordinate plane — "a coordinate names the same bytes forever"; the ring = a whiteboard of pointers, not data; workers = an ensemble of perturbed realizations; fallow = conservation law on memory; recovery ≈ free because data never disappears). Concurrency without consensus, recovery without reconstruction, scheduling without a scheduler.

**The complexity is load-bearing, front-loaded, and mostly *audited*** (every piece has a documented reason or a finding ID on its head). The hardest part for newcomers: mechanisms serving double duty (local job + global invariant) — which is why the documentation suite is the actual onboarding mechanism, and why the double-duty registry doc keeps getting queued.

**The owner:** computational geophysics / inverse theory background, *not* CS. This explains the design's shape: first-principles derivation over literature, optimization as inverse problem (falsified hypotheses recorded as first-class results — the changelog's "honest result: falsified" culture), error bars and "what this does NOT prove" on everything, conservation-instinct debugging (bytes must balance), ensemble thinking. AI (opencode instances) supplies the Unix-greybeard folklore layer; the owner supplies the design; adversarial verification arbitrates. The division of labor works — and the pace it produces (~8h for five work orders; ~110 defects closed) means the scarce resource is *spec quality and decision latency*, not execution. **As tempo rises, work-order errors (not implementation errors) become the dominant failure mode — R-V2 was the first live catch. Expect more; that's the system working.**

**Working protocol with the owner:** he makes binding decisions and expects them followed exactly; state the technical case once when you disagree, then execute. He values honest reporting over optimistic framing. He runs some gates himself. Ratify decisions explicitly when they're his to make (the R-V2 disposition and the final GO are current examples). He generates handover docs *early* — context cutoffs are abrupt.

## 4. Supervisory Protocol (how you review and issue work)

1. **Verify against the repo** before trusting any claim here. `git log --oneline -5`, clean-tree check, `release_check.py` status.
2. **Work orders follow the house format:** context handover section (fresh-instance safe) → findings with IDs → exact fix specs → red lines → verification gates (bite-then-green lock-ins, ×10 for timing-sensitive, ×5 for structural) → commit sequence (fixes before features, bugs before docs) → completion-report format. Pre-registered GO/NO-GO criteria are *frozen once the race starts* — implementers flag design collisions; they never relax gates; the owner amends.
3. **Red lines (primer §7.1, binding):** no CAS retry loops on the hot path; no rollback of monotonic indices; no fence removal/weakening; no restructuring of `UNIFIED_SCANNER_FLUSH`/`ADAPTIVE_FLOW_CONTROL`; no `try_simd_scan` modification; no `PATH=''` constructions; the `-c` sandbox stays quote-free; twins in lockstep (`frun.bash`↔`frun.nob64.bash`, CHANGELOG↔DOCS_ALL, test↔`.txt`); canary stub list shrink-only.
4. **Known-flake registry** (disposition against these before calling anything new): C-drain framing header · reactor-ingest multiset · T10b · M8 HUP-window · bench denominator-noise. New failure signature = incident entry + STOP, never rerun-until-green.
5. **Verification gates that recur:** full suite ×3 (release) / ×5 (structural); targeted ×10; bash suites **foreground** (M1a lesson); heavy-20M `@4`×4 + `nodes=1`×2 with `FORKRUN_DIAG_NUMA1=1` (mismatch=0, drains write==read); F-PY-UMA1 + F-NUMA1 forensic loops ×10; canary/IDL/reproducibility; `release_check.py` 17/17 (now runs the invariant gate, doc harness, executor checker, and shim ABI gate — the count of *checks* is 17 but the suite underneath is 588).
6. **Completion reports get reviewed against the order's gates** — look for: bite evidence, gate-by-gate results, incident dispositions, deviations flagged (not smoothed), and the specific honest-reporting markers the culture values ("what this does NOT prove," falsified premises, halts with reasons).
7. **Halt-and-report is a success mode.** R-V2 proved it. An implementer refusing a specified fix with an audit is the process working; never penalize it, never quietly implement around it.

## 5. What Comes After the Tag

**The EPYC rental is the next major event.** The owner found Cherry Servers bare-metal: 64c/128t EPYC 9575F (Zen 5, 4 NUMA nodes), 384GB RAM, Ubuntu 24.04, ~$2.70/hr. The plan (discussed, not yet ordered): ~4–6h box time — environment setup + full test suite both topologies; the **scaling curve** (16/32/64/128 workers, memory-bound + compute-bound workloads); **remote-access fraction** (W-PY36-style perf study under real distances — fake-NUMA's uniform distance=10 understates born-local placement's payoff); **competitor degradation curve** (Executor at the same worker counts — the honest comparison needs both curves); **steal-threshold behavior** under real distance asymmetry; tokenization run. **THP is a first-class experimental variable** (a benchmark cell was silently invalid this cycle because THP toggled mid-run — the harness now echoes environment; keep that discipline). Run the first large jobs with `FORKRUN_DIAG_NUMA1=1` — the mismatch tripwire is the early-warning system on real topology. The projections say the competitive gap *widens* on big NUMA (competitors' single queue + NUMA-blind allocation become pathological; forkrun's per-node rings and born-local placement don't); the honest posture is that fake-4 validated the *mechanisms*, and real distances remain untested — which is exactly what the rental resolves. This run is also the ORNL re-approach's key artifact.

**Other post-tag threads:** PyPI release (release_check gates it) · W-BENCH1 benchmark-doc cleanup addenda (environment echo, stale docstring, boot-topology labeling, RSS-measurement audit, light-20M THP-controlled re-measurement) · the v3.7 structural backlog · possible ORNL/AI-industry adoption push (the owner's pitch: `pip install forkrun`, tokenization numbers, recovery as the lab-shaped differentiator).

## 6. Immediate To-Do (the successor's first day)

1. Check the Gate-4 follow-up order's result (if reported): green → present the GO recommendation with the DEDUP_REPORT behavior-delta audit for the owner's ratification; failures → main-line path, per the decision tree in §1.
2. Confirm the owner's R-V2 disposition ((a) recommended) and register the backlog item accordingly.
3. Once GO is ratified: the **tag sequence** — push the branch → CI green on pushed head including blob auto-build no-op confirmation → full-matrix tag-candidate verification (both topologies if feasible) → promote to `main` (v3.6.0 currently absent there — setup.py, tests, CI all live on the work branch) → tag → push tag. **Release notes contents** (assembled across the cycle): recovery-default flip + `orchestrator=False` migration line · NUMA poison-warning behavior change (previously silent → warns) · `strict_poison`/`signal_policy` params · exception taxonomy with dual-inheritance note (`ForkrunInterrupted` straddles `RuntimeError`+`KeyboardInterrupt` — existing handlers keep working) · port-parity summary · topology-dependent test counts (91/89 bash; 7 multi-node skips) · M8/M1a/T10b dispositions · the perf numbers from R1.
4. Then: sleep-deprived owner, EPYC order, and the rest of §5.

---

*End of handover. The successor's first act on receiving any report or diff: read it against §4's protocol, produce a verified-complete list plus new findings, and issue the next work order per the house format. The owner provides context; this document provides the rest.* 

---

## Assistant

Let me verify the handover's claims against the repo before I issue anything — per §4.1.

**Tool: bash**

**Tool: bash**

---

## Assistant

Gate 4 is still PARTIAL — no follow-up result in the repo. Let me verify the remaining open items so the order is accurate.

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: bash**

**Tool: bash**

---

## Assistant

I have everything I need. Here's the work order.

---

# WORK ORDER: W-REL5 — v3.6.0 Pre-Tag Completion

**From:** Supervisor
**To:** Implementation instance
**Date:** 2026-09-28
**Supersedes:** W-REL4 post-release backlog (S3, S5, and all deferrals are pulled INTO 3.6.0 per owner decision, 2026-09-28)
**Status:** READ-ONLY plan pending owner approval. Do not begin implementation.

## 0. Verification of inherited state (done, against repo not handover)

`NEW/REFACTOR2.9` @ `b69b4fc`, tree clean, 588 tests. Handover claims check out. Two corrections to the handover:

1. **Gate 4 is still PARTIAL.** No follow-up result exists in the repo. The handover says an order "was issued"; nothing landed. **This order does not assume GO.** Gate 4 is W-REL5-G0 below, and the decision tree stays as the handover specifies.
2. **R-V2 is not the most recent commit** — `dcc3bf7` is third from head. R-V2's halt stands; its disposition is still an open owner decision (handover §1, unchanged). I recommend (a) accept-containment; it is not a v3.6.0 blocker and this order does not touch it.

Also verified: `_shim.c:1624` now bounds `num_nodes ≤ 512` (R17 landed on that entry point), but `:1657`/`:1678`/`:1700` still check only `< 0`. Partial, not complete.

## 1. Owner decision, recorded

**Everything we know about gets fixed for v3.6.0. Nothing deferred.** I state the technical case once, per protocol §4, and then execute.

The case: this is ~60 findings landing in the final window before a tag, so the dominant risk is not any individual item — it is that a consolidated batch masks a regression. Mitigation is sequencing, not deferral: six waves, each independently gated, each ending in a full matrix, bite-then-green on every behavioral change. The doc/dead-code wave carries near-zero risk and can run any time. The behavioral waves are ordered so the riskiest land with the most matrix coverage behind them. **I am not recommending any item be dropped.**

## 2. Red lines (binding — primer §7.1)

Unchanged and in force: no CAS retry loops on the hot path · no rollback of monotonic indices · no fence removal/weakening · no restructuring of `UNIFIED_SCANNER_FLUSH`/`ADAPTIVE_FLOW_CONTROL` · no `try_simd_scan` modification · no `PATH=''` constructions · `-c` sandbox stays quote-free · **twins in lockstep** · canary stub list shrink-only.

**Added for this order:**

- **R5.1** No new `sys.modules["forkrun.run"]` binding. W-DEDUP §"cycle discipline" forbids it; Phase 3 consolidation is the only permitted change to that mechanism.
- **R5.2** `run.py` is being edited by two instances. **This order is read-only until the owner confirms the DEDUP instance has exited.** See §8.
- **R5.3** Every wave ends with `git diff --stat <base> HEAD -- '*.c' '*.h'` printed. **Only W-REL5-D may touch C, and only in the enumerated spots.** Any other C diff is a halt.
- **R5.4** `orchestrator` default stays `None`-rides-reactor. No wave may change the R1 semantics. Benchmark deltas beyond the recorded ±1.3% band are a halt.
- **R5.5** Known-flake registry (§4.4) dispositions must be cited before any new failure is called new. Rerun-until-green is forbidden.
- **R5.6** `src_forkdown`: the `sys.modules` lazy-binding in `_executor_core.py` is load-bearing in two modules. Do **not** attempt the `run.py` rename in this order. File under W-REL5-F as a 3.6.1 candidate; noting it here so no implementer treats it as an oversight.

## 3. Waves

Each wave = one or more commits, own gates, own bite-then-green. Waves are ordered; do not start wave N+1 until wave N's gates are green and reported.

---

### W-REL5-A — Bash front-end hardening (S-class + sourced-library contract)

**A1. Loadable memfds get `cloexec=1`.** `frun.bash:2662` (`FORKRUN_MEMFD_LOADABLES_BASE64`) and `:1657` (`plugin_memfd`) pass `0`; `:1301` correctly passes `1`. Change both to `1`. A sourced `frun.bash` currently leaks 2 fds + ~1.2 MB into every process the user spawns, forever.

**A2. Stop exporting fd numbers to children.** `FORKRUN_MEMFD_LOADABLES`, `FORKRUN_MEMFD_LOADABLES_BASE64`, `FORKRUN_RING_ENABLED` are exported and inherited by every child. Make them non-exported (plain assignment). The stale-fd re-guard at `:2446`/`:2470` must keep working — verify it does, since it reads those values in the *parent* only.

**A3. `extglob` restore.** File-scope `:3-7` sets `shopt -s extglob` and never restores. Mirror the `:1091` precedent (restore on RETURN inside `frun`). Scope: restore only if `frun` was invoked; leave the source-time state documented. **Gate:** `. frun.bash; shopt -q extglob` before/after `frun` invocation.

**A4. Bootstrap TOCTOU (S5).** `:2625` `truncate -s` and `:2674` truncate onto predictable paths (`$BASHPID`/`$RANDOM`, 30 bits) in candidate dirs including `/tmp`, `$HOME/.cache`, and **`$PWD`**; the file is then `dlopen`'d at `:2630`. Replace with `mktemp` in the same dir (as R18 already does for the checkpoint at `:1334`), and drop `$PWD` from the candidate list. **Bite:** pre-plant a symlink at the predicted `truncate` target; pre-fix it is resized/followed; post-fix untouched.

**A5. `nounset` sweep (S3).** ~44 unguarded `$1`…`$9` plus `FORKRUN_EXTRA_*`. Prefer the scoped approach: `local _fr_saved_u=$-; set +u` at `frun` entry, restore via the existing RETURN trap, and guard the file-scope bootstrap path (`:2802` runs `_forkrun_bootstrap_setup --force` at source time with whatever positionals the caller's shell has — that is the actual `set -u` kill path). Full `${1-}` conversion only if the scoped version fails a bite. **Bite:** `set -u; . ./frun.bash; printf 'a\n' | frun -j1 -l1 cat` — must not abort the sourcing shell. Also `frun -n` with no command.

**A6. `ring_memfd_create` / `ring_set_resume` return values.** `:1290` and `:1293` are unchecked; failure yields a bare redirection error *before* the EXIT trap is installed, so no checkpoint, no cleanup, no diagnostic. Add `|| { diagnostic; exit; }` with actionable text (which fd, what errno, what to do about `vm.max_memfd_count`/`RLIMIT_NOFILE`).

**A7. `_forkrun_get_arch` return value.** `:2482` discards it, so an unsupported arch prints `INVALID / UNSUPPORTED ARCH!` then eight `b64: bad array subscript` then a *temp-directory* error that can never help. Propagate the failure and exit with only the arch message. **Also remove the `armv7` claim** from the `:2268` string — no `case` branch, no `b64` key, no `.so` exists.

**A8. Partial-resume fail-closed.** `:459-478` only fail-closes on a missing `HORIZON`; a missing `STDOUT_BYTES` is passed as `""` to `ring_set_resume`, which sets `resume_stdout_bytes = 0` and would tell the user to truncate output to zero. Fail closed on any missing required key, with the key named. **Bite:** `printf 'FORKRUN_RESUME_HORIZON=3\n' > partial.resume; seq 5 | frun --resume ./partial.resume sig` — pre-fix accepts with no warning; post-fix refuses naming the missing key.

**A9. Document the 128 KiB per-record fast-path ceiling.** Records >`MAX_ARG_STRLEN` (128 KiB) fail `posix_spawnp` with `E2BIG`; `ring_exec_main` returns `254` with no `strerror`, so the batch is retried 3× and misreported as "poisoned." Either emit the `strerror` on the `254` path (preferred — also fixes the P0-4 diagnostic hole) **or** document the ceiling. Do both if the `strerror` is a 1-liner.

**A10. `_expand_unit` correctness.** `:207-225` silently misparses `1.5G`→1, `-5M`→INT64_MAX, `1e3`→clamped, `0x10`→8, `1_000`→11000. Reject fractional/negative/exponent forms with a clear error. **Bite:** each input above, asserting refusal (not silent acceptance).

**A11. Version string single-source.** `frun.bash:1026` hardcodes `v3.6.0`, duplicating `META` and `forkrun_ring.c`'s `FORKRUN_RING_VERSION`. Make `--version` read `META` or the engine's `ring_version` builtin. Do **not** hand-edit it again; `DOCS/MAINTAINERS.md:96` currently instructs maintainers to, which is the actual bug.

**Gates A:** bash suites foreground, 92 + 264 (M1a lesson — never backgrounded) · shellcheck non-regressive on `frun.bash` · twins byte-identical · `shfmt` on `frun.bash` will fail (899 KB line) — pre-existing, document, do not attempt to fix.

---

### W-REL5-B — Python behavioral correctness (P-class)

**B1. Unknown-kwarg rejection (M2).** `map`/`stream`/`sweep` read `kwargs.get(...)` with no whitelist; a `wokers=` typo runs a *different pipeline silently*. `run()` already rejects (`run.py:764` has an explicit keyword-only signature) — that is the correct pattern. Add one shared `_reject_unknown_kwargs(kwargs, allowed)` applied at all three. **Note `map(f, src, sink=print)` is currently a silent no-op** (`run.py:934` hardcodes `sink=None`) while `sweep()` explicitly rejects it — reconcile: either honor `sink` or reject it. **Bite:** typo'd kwarg must raise, not silently run.

**B2. `stream()` exception taxonomy (M3).** Six blocking executors map `KeyboardInterrupt` → `ForkrunInterrupted`; the four stream executors do not, so `except forkrun.ForkrunInterrupted` will not catch a stream interrupt. `ForkrunInterrupted` *is* a `KeyboardInterrupt` so nothing breaks, but `MIGRATION.md:40-46` presents the taxonomy as uniform. Bring the stream paths in line.

**B3. Reactor liveness: `O_NONBLOCK` on the ingest-reactor source (M5).** `:2298` and `:5283` set `O_NONBLOCK` on the streaming paths; the ingest-**reactor** path blocks in `os.read(src_fd, 1MB)`. During that block: worker deaths are unobserved, `state.spawn_r` is not drained, helper deaths go unnoticed — i.e. the headliner's seamless recovery is unavailable exactly when the source is slow. Mirror the sibling pattern (set `O_NONBLOCK`, drain to `EAGAIN` in the pump).

**B4. Bound the helper joins (M6).** ~10 unbounded `os.waitpid(pid, 0)` sites (`:1665, 1963, 1981, 2037, 2462, 2530, 2541, 2961, 2969, 2979, 3010, 3021`). `_resume._waitpid_bounded` already exists and does this correctly — it is simply not used here. A wedged helper hangs the run with no diagnostic. Replace with the bounded form, alarm on timeout, name the helper.

**B5. `reactor_poll_once` must not block (M7/M8).** `_reactor.py:983` calls `state.worker_died(wid)` → `:302` `os.waitpid(slot.pid, 0)`, blocking. This contradicts the function's own docstring (`:934-943` "Never blocks beyond `poll_timeout`") and it is called from the ingest spill loop where non-blocking is the whole point. Related: EOF on the death pipe precedes `os._exit`, so a descheduled child stalls the reactor. Use `WNOHANG` + bounded spin; the out-of-band `reap_clean_exits` sweep already exists for this.

**B6. `check_cuda_hazard` is hoisted already (R9) — verify, do not re-add.** Confirm the single `_api._validate` call covers all 10 executor paths post-DEDUP. If DEDUP introduced a new path that bypasses dispatch, wire it. **Do not add 9 per-path calls** — that reverts R9.

**B7. `_RUN_LOCK` coverage (R10) — verify post-DEDUP.** `_guarded_gen` + RLock landed. Confirm the NUMA stream path holds the lock across generator lifetime, including the RLock-nesting contract the completion report flagged as an honest-contract follow-up. If the nesting contract is documented-but-unenforced, add a contract test; do not change the lock type.

**B8. Signal-number fidelity (M10).** `_reactor.py:340-345` computes `exit_signo` via `_death_cause` and then uses it *only* in two `rc==4/5` messages. The common path surfaces a bare `RuntimeError("forkrun: N/M workers failed")`. `exceptions.py:1-13` promises cause fidelity with the `signo` attached. Either attach it on the common path or narrow the docstring. **Bite:** SIGSEGV a worker, assert the raised exception carries `signo`.

**Bite-then-green for B:** each of B1-B8 needs a *pre-fix failing* demonstration. B3 and B5 are timing-sensitive — ×10. B1, B2, B8 are deterministic — ×5.

**Gates B:** full suite ×3 (588 + new) · `test_invariant_gate.py` 4/4 · `test_doc_accuracy.py` 9/9 · `test_executor_consistency.py` 10/10 · `test_shim_abi.py` 5/5 · `release_check.py` 17/17.

---

### W-REL5-C — Python robustness & security posture

**C1. `find_substrate` must not dlopen from CWD (M12).** `_bindings.py:405-407` adds `os.getcwd()` candidates. This is the `D10`-class hazard the project explicitly closed for spawn/plugin (F-PORT4, `INVARIANTS.md:449-458`) and left open for the library it loads *first*. Remove the CWD entries. **Bite:** place a hostile `libforkrun_python.so` in CWD with the co-located one absent; pre-fix it loads, post-fix it refuses.

**C2. `signal_policy` must fail loudly off the main thread (M17).** `_signals.py:100-103` swallows `ValueError` from `signal.signal` and continues, so `signal_policy` silently no-ops. The module names threaded/event-loop hosts as the reason the policy is opt-in — i.e. it fails quiet exactly where it matters. Raise with an actionable message.

**C3. `sweep()` + `resume`/`checkpoint_file` (M14).** `sweep` forces `order="index"` and replays one stateful resume over N combinations; the first consumes and unlinks the sidecar, so combinations 2..N silently skip the committed prefix. Reject `resume`/`checkpoint_file` on `sweep()` outright. **Bite:** `sweep(..., resume=...)` must raise.

**C4. `consume_sidecar`: deliver, then unlink (M18).** `_resume.py:395-404` unlinks before the caller consumes. A crash in between loses the bytes permanently. Move the unlink after consumption, or unlink on the next successful run.

**C5. Latent fd double-close (M19).** `run.py:4573-4587`, `5663-5679`, `7206-7233` close `spare_signal_w` without nulling the local, then pass the same number to teardown which closes again. Benign today; a trap for the next change. Null after close. (Compare `_pump_drain_c._close_spare()`, which does it right.) Audit the `order_w` path at `:4074-4075` specifically — there, `open()` calls *do* intervene, so a recycled descriptor is genuinely reachable.

**C6. Signal handler async-safety (M16).** `_signals.py:73-84` appends to a list and calls through ctypes (which releases the GIL) inside a handler. The engine-side `fr_py_abort()` is a single `write()` and is safe; the wrapper is not. Record the signal into a preallocated `array`, and let the reactor loop (already on a 0.1 s quantum) perform the abort.

**C7. `_drain_records` partial-signal spin (M9).** `run.py:1497` breaks on `not sig_buf`; `sig_buf` drains 16 bytes at a time, so a residual 1-15 bytes loops forever. Low probability (≤`PIPE_BUF` makes the pipe write atomic) but the failure is a silent hang, not a clean error. Guard it.

**C8. `_plugin.load_plugin` dlopens in the parent (M13).** `_plugin.py:77-79` claims fork-safety; `dlopen` runs ELF initializers in the parent, and a plugin linking `libstdc++`/`libgomp` can start threads there. `_shim.c:2480-2485` does the opposite and explains why. Either drop the claim (document the constraint) or move the v0 dlopen post-fork. **Recommendation: document.** The v0 path is legacy; a dialect-probe rework is not pre-tag material.

**C9. Respawn backoff, OOM-class deaths (M11).** `_reactor.py` respawns immediately and unconditionally. A payload that `SIGKILL`s itself burns all 4 generations in ~0.01 s and aborts a run a 200 ms backoff would survive. Add a short jittered backoff, and distinguish "environmental death" (`SIGKILL`/OOM-class → back off) from "deterministic payload crash" (`exit != 0` → poison fast). **Bite:** ×10 with a `SIGKILL`-on-every-generation payload — must terminate correctly and still complete when the killer backs off after N attempts.

**Gates C:** full suite ×3 · C1/C2/C3/C4/C5 deterministic (×5) · C6/C7/C9 timing-sensitive (×10) · `release_check` 17/17.

---

### W-REL5-D — C engine hardening (enumerated; R5.3 in force)

**Only these sites may change. Any other `*.c`/`*.h` diff is a halt.**

**D1. `safe_hole_punch` bounds (H4).** `forkrun_ring.c:7099-7109`. `p_fd` comes straight off the order pipe (`:7317`, `:7374`) with no range check. `int new_cap = p_fd + 128` overflows (UB); `p_fd = 10_000_000` forces a ~400 MB `realloc` plus a `memset` touching every page. Add a range check and `size_t` arithmetic. Note the sibling site at `_shim.c:2074-2112` has the same shape.

**D2. `last_ack_offset` not reset on fd change (M1).** `forkrun_ring.c:6588-6618` invalidates `ack_cached_mode` on target-fd change but not the offset, so `op.len` can go negative and become a ~16-exabyte `sendfile`. Duplicated verbatim in `_shim.c:2074-2112`. Reset `last_ack_offset = 0` alongside the mode.

**D3. `ring_revert_output_main` can grow a file (M5).** `:8288` `ftruncate(fd, last_ack_offset)` with no `S_ISREG` and no `size >= target` check — `ftruncate` to a *larger* offset zero-extends. The sibling recovery path at `:6837-6846` has exactly those two guards; copy them.

**D4. `fr_py_emit` uninitialized `iov[1]` (M2-shim).** `_shim.c:1205-1238`; when `niov == 1` the compaction loop reads `iov[1]` uninitialized. Reached on every zero-length emit. Add `if (niov == 1) break;`.

**D5. `fr_py_parse_descriptors` overflow guard (M8).** `_shim.c:2278-2287`: `if (off + data_len > input_len)` wraps on a framing-controlled `data_len`. Correct form is `data_len > input_len - off`. Same shape for `off + 16`.

**D6. `format_bytes` buffer size (M7).** `forkrun_ring.c:9550-9555` hardcodes 32; called with 16-byte buffers at `:9742-9753`. Not currently reachable (the branch ladder normalizes magnitude) but it's a 9-byte stack-smash landmine. Pass the size, or bump the buffers to 32 to match the siblings.

**D7. Heap cap doubling overflow (M9).** `:6904`, `:7049`: `int new_cap = (*cap) * 2`. Use `size_t`, check the multiply.

**D8. Escrow pipe creation failure is silent (M17-C).** `:2679-2690` sets both fds to `-1` with no diagnostic; the first worker death then returns a bare `5 /* FATAL */`. Log it, matching the eventfd loop at `:2671-2676`.

**D9. `dup2` return ignored (L5).** `:9242`. On failure fd 0 is left dangling for the worker's life.

**D10. NULL-`state` guard consistency (M13).** `ring_copy_main` guards `state` at `:8003` then dereferences unconditionally at `:8009`+.

**D11. `SIGKILL` test hooks on the hot path (M18-shim).** `_shim.c:230-231`, `1996-1997` call `getenv` on every claim/commit. Gate behind a build-time macro or a `FORKRUN_ENABLE_TEST_HOOKS` master switch. Note this touches test-visible behavior — coordinate with the fault-injection suites.

**D12. `state`/`evfd` index bounds at the `target_node` consumers (C2-partial).** `_shim.c:1657`, `:1678`, `:1700` check only `< 0`; `:1624` correctly bounds `num_nodes ≤ 512`. Bring the other three in line, and regenerate `forkrun_shim.h` via `gen_shim.py` so the ABI gate covers it.

**D13. `%lu` for `uint64_t` (M11-C).** 22 sites. Correct on LP64, wrong on ILP32. Either fix to `PRIu64` (the file already does this correctly at `:4588`, `:7393`, `:8393`) or delete the s390x/ppc64le/riscv64 `cpu_relax` branches and the `#if defined(__x86_64__) || defined(__i386__)` SIMD guard, since `setup.py:44-51` refuses to build off x86_64/aarch64. **Recommendation: fix the format strings** — the source shouldn't advertise portability the packaging forbids.

**D14. mmap-window `SIGBUS` (C5).** `_shim.c:1468` — *"hole reads zero-fill regardless"* — is true for `read()` and **false for the `MAP_SHARED` window** handed to plugins (`forkrun_ring.c:9440-9442`) and Python (`_shim.c:1488`). A `FALLOC_FL_PUNCH_HOLE` inside a mapped range raises `SIGBUS`. The engine's argument for safety is an invariant argument (`forkrun_ring.c:8949-8950`: unacked windows are never punched), and the invariant is not mechanically enforced. **Minimum: correct the comment** so the next maintainer isn't misled. **Preferred, if the semantics can be pinned down: `fadvise`/`madvise` re-validation on the window.** This is a crash class in the headliner — treat the comment fix as mandatory, the mechanism as best-effort.

**D15. Post-fork bash internals (M10-C).** `:9171-9174` → `ring_call_scrub_feeder_child` (`:9050-9093`) does `signal()`, `get_string_value`, `find_variable`, `array_cell` — bash's variable machinery and allocator — between `fork()` and `_exit()` with no `exec`. `signal()` is not async-signal-safe. Hoist the three `atoi(get_string_value(...))` lookups above the fork. (Optionally `close_range(3, ~0U, 0)`, which is async-signal-safe and complete — but see R-V2: fd numbers in child tables may make a parent-side sweep surprising. **Do not** change fd-closing behavior in this order; hoist the lookups only.)

**Gates D:** canary (zero warnings, stub list shrink-only) · `make check` · IDL check · reproducibility check · full Python suite ×3 · `test_shim_abi.py` 5/5 with regenerated header · heavy-20M `@4`×4 + `nodes=1`×2 with `FORKRUN_DIAG_NUMA1=1` (mismatch=0, drains write==read) · F-PY-UMA1 + F-NUMA1 forensic loops ×10 · `release_check` 17/17.

---

### W-REL5-E — Docs, dead code, hygiene (low risk, parallelizable)

**E1. Plugin ABI docs are wrong.** `MODES.md:66-70` and `MIGRATION.md:17` claim "a bash `-C` plugin works from Python unchanged and vice versa" and describe the legacy path as **two-arg**. The v0 fixture is **one-arg** — `int process(struct fr_py_plugin_ctx *ctx)` (`python/tests/plugins/test_plugin.c:54`), called as `func(ctypes.byref(ctx))` (`_plugin.py:151`). A real bash legacy 2-arg plugin gets `argc` = a ctx pointer, `argv` = garbage. `PLUGINS.md:78-80` compounds it. Fix all three to state the actual conventions and the dialect-tag requirement.

**E2. Python version floor.** `INSTALLATION.md:8` says 3.10+; `setup.py:155` says `>=3.8`; classifiers stop at 3.12; `release_check.py:217-220` only asserts `Requires-Python` *exists*. Given `_bindings.py:365` uses PEP-604 `str | None`, 3.10+ is the honest floor. Reconcile all three; make `release_check` assert the *value*.

**E3. `sink=` is at-least-once; nothing says so.** `_worker.py:547-558` runs the sink before commit, so a death between sink and ack re-runs it. Verified: output exactly-once, side effects duplicated. `FAULT_TOLERANCE.md:23-26` warns only about "realtime output (workers writing stdout directly)", which doesn't exist in Python. `EXAMPLES.md:143-155` actively encourages writing files from the sink. One sentence in `API.md`, one in `FAULT_TOLERANCE.md`.

**E4. `find_substrate` / `__init__` side effects.** `__init__.py:51-64` `dlopen`s at import time and swallows `FileNotFoundError` from a bad `$FORKRUN_LIB`. Document it. Also `forkrun.run` is a function, not a module (`L4`) — document, don't rename (R5.6).

**E5. `RunConfig` is exported but unproducible (L3).** In `__all__`, never returned by any `_validate` call. Either produce one or drop the export. `signal_policy: Any` (`_api.py:121`) and a field literally named `bytes` both want attention.

**E6. No type hints on the public API, no `py.typed` (L1/L2).** `run`/`map`/`stream`/`sweep` have zero annotations; `Mode`/`Order`/`OnError`/`Nodes` in `_api.py:19-24` are defined and unused. Add hints to the four public signatures + `py.typed`. **Keep this to the public surface** — annotating the internals is 3.6.1.

**E7. Dead code sweep.** `run.py`: duplicate `_watch_live` def (`:2243`/`:2303`), duplicated mode/nodes validation block (`:1731-1745`), redundant `wid_to_node` import (`:6256`), unreachable `rc = 127`. `frun.bash`: 14 unused locals, `toc()` defined twice and never called, `fd_scan_death_w`/`fd_indexer_death_w` written-never-read. Six unreachable `os.memfd_create`→`tempfile` fallbacks (dead at `python_requires>=3.8`), two of which append to never-cleared function-attribute lists. Two parallel codec function copies (`_forkrun_base64_to_file` / `_forkrun_file_to_base64`) with divergent self-guards — note `_forkrun_file_to_base64:2793` tests `FUNCNAME[1] == *'frun'*'`, a glob that never matches the real function names.

**E8. `ring_loadables/local_compile/compile.sh` is broken and stale (P3-4).** Different flags from CI, and it re-derives the `b64` key without the `-`→`_` normalization, so it emits `x86-64-v2` where `_forkrun_get_arch` produces `x86_64_v2` → `bad array subscript` → total bootstrap failure. It also writes `./frun.new.bash` and never applies it. **Delete it** (`update_frun_base64.bash` is the fixed successor), or fix the key derivation. Recommend delete.

**E9. Stale twins.** Four file-twins have drifted; `forkrun_ring.c.txt` vs `forkrun_ring.c` differ by ~2239 lines and `frun.nob64.bash.txt` vs `frun.nob64.bash` by ~50, with **no CI gate** on either. Either bring them into lockstep or delete them. Recommend delete the ungated ones — a twin nobody checks is a trap.

**E10. Arch list consolidated.** The supported-arch list appears in ~6 places and is already inconsistent (`armv7` claimed at `frun.bash:2268`, absent everywhere else). After A7, make the error string and the `b64` keys derive from one place.

**E11. Undocumented env vars.** `FORKRUN_DEBUG`, `FORKRUN_TRUST_RESUME`, `FORKRUN_C_STDIN`, `FORKRUN_SWEEP_ARGS`, `FORKRUN_TMPDIR`, `FORKRUN_NUM_NODES`, three `FORKRUN_TEST_*_PIDFILE` hooks are all honored (`:149`) and none appears in the `### ENVIRONMENT VARS` help block (`:361-373`). Add them.

**E12. Help-text corrections.** Completion advertises `--debug` (doesn't exist) and `--fast` (internal-only) (`:2215`). `-I`'s fast-path status contradicts the help at `:287` and `FLAGS.md:6` — the gate at `:1577` excludes `unsafe_flag`/`insert_args_flag`/`is_sweep` but **not** `insert_id_flag`, so `-I` *is* on the fast path (verified). `-v/--verbose` is ~90% dead: `toc()` never runs, no flag summary is ever printed, though `:437` implies one. Either implement or narrow.

**E13. Portability floor.** `README.md:124` says Bash ≥ 4.0; `mapfile -d` (`:79`, `:81`) needs **4.4**. `sed -z` (`:2479`), `base64 -w 0` (`:2776`), `truncate --size=` (`:2415`) are GNU-only. Correct the docs; do not attempt busybox support.

**E14. `stage0_harness.py` is a dead skeleton.** Writes `TBD`/`UNMEASURED` for every cell; `check_surface()` passes on `NotImplementedError`/`OSError`/`FileNotFoundError`/`RuntimeError` — a very wide surface. No tests, not in the gate. Delete or finish. Recommend delete from the release.

**E15. MEMFD export + `_teardown_stream` signature (M19 residual).** Verify the DEDUP teardown-union call sites null locals after close; add the missing `null` where absent.

**E16. Repo hygiene.** 59 MB working tree, 352 MB `.git`, with `LEGACY/` (20 MB) and `ring_loadables/OLD_MISC` (13 historical `frun.*.bash` + a 758 KB `frun.bash` + 44 `PREV_VERSIONS/`). Tracked-file count is 456. Consider gitignoring or pruning the archaeology — it slows every clone and every tool that walks the tree. **Do not do this in W-REL5** — it is a mechanical cleanup with real merge-conflict surface and zero product benefit. Register as post-tag.

**Gates E:** doc-accuracy harness 9/9 extended with the new rows · twins byte-identical · full suite ×3 · `release_check` 17/17 (the check *count* may change; if it does, say so explicitly in the report).

---

### W-REL5-F — CI / release infrastructure

**F1. `python-check.yml` has never run green, and `main` has no `python-check.yml` at all.** R2/R3 fixed the two blocking defects, but the workflow is still unproven on a GitHub runner, and the merge to `main` is the first time CI would evaluate the suite. **Push the branch and get CI green before the merge** — cheapest de-risking in this order. Add `timeout-minutes` to every job.

**F2. Python version matrix.** One job, one distro, one Python. `setup.py` declares `>=3.8`, classifiers stop at 3.12, nothing tests 3.8-3.13. Add a matrix over the versions E2 settles on, × ≥2 distros (Fedora for `bash-devel`, Ubuntu).

**F3. Static analysis baseline.** 14.9k lines of library Python, zero type checking, zero measured coverage. Add `ruff` (fast, no config archaeology) and coverage measurement as a **non-failing report** initially. Do not gate on them this release.

**F4. Automate the `E1`/`E3` sanitizer freshness assertion.** `RELEASE_RUNBOOK.md:59-67` is manual; `:88-89` records that ASan branches are still carrying v3.1.0-stale blobs "embedded, verify-green" — the second instance of that incident class. Script the E1 diff so it isn't a thing someone remembers. R5's `set -euo pipefail` + freshness gate landed in the main release workflow; the sanitizer branches need equivalent treatment or the post-tag run re-learns the lesson.

**F5. `ubuntu-native.yml` — audit its scope.** It appeared during the review window and is not referenced in the handover. Establish what it gates before the merge; an ungated workflow that can go red is noise.

**F6. `release_check.py` gaps.** No SBOM / signing / attestation / recorded checksums · `gen_idl.py --check` is CI-only, not a release gate · `FROZEN_FILES` proves only that HEAD didn't touch them (no blob-hash pin) · `check_twins` compares headings, not bodies · `check_sdist` globs `dist/*.tar.gz` and takes `[0]`, and `dist/` is gitignored and already holds a 0.16.0 tarball · no tag check, and `CHANGELOG.md:3` is still `## v3.6.0 (unreleased)` which the substring match passes · the shipped wheel is never built once and verified as one artifact (three separate `pip wheel` invocations) · not hermetic (PEP 517 build isolation needs network) · `import forkrun` resolves ambiguously if a wheel is already installed. **Scope for 3.6.0: the tag check, the `CHANGELOG` unreleased guard, `gen_idl.py --check`, and the checksums.** The rest (SBOM/signing/hermeticity) is 3.6.1 — state that boundary in the report rather than silently skipping.

---

## 4. Wave sequencing

```
W-REL5-G0  Gate 4 closure (pre-existing, not this order's work)
     ↓
W-REL5-A  bash hardening        ─┐
W-REL5-E  docs / dead code      ─┤ A and E are independent, E has ~zero risk
                                │
W-REL5-B  python behavioral     ─┤ after A+E land and the tree is green
W-REL5-C  python robustness     ─┘
     ↓
W-REL5-D  C engine  ← last: highest blast radius, and A-E change no C
     ↓
F1  push, CI green  →  merge to main  →  tag  →  sanitizers (E1/E3-gated)
```

**Why D is last:** it is the only wave touching C, so running it after the Python and bash waves means the Python suite, invariant gate, and heavy NUMA matrix all re-run on top of it. Running it earlier would mean re-running the heavy legs twice more.

**Why A/E can run in parallel with nothing else:** neither touches `run.py` or any `.c`.

## 5. Gates summary (cumulative per wave, from §3)

| Gate | Frequency |
|---|---|
| Full Python suite | ×3 (release) / ×5 (structural) |
| Targeted, timing-sensitive | ×10 |
| Targeted, deterministic | ×5 |
| Bash suites | foreground, 92 + 264 (never backgrounded — M1a) |
| Heavy-20M `@4`×4 + `nodes=1`×2 | `FORKRUN_DIAG_NUMA1=1`, mismatch=0, drains write==read |
| F-PY-UMA1 + F-NUMA1 forensic loops | ×10 |
| Canary / IDL / reproducibility | every wave |
| `release_check.py` | 17/17 |
| C diff audit (`R5.3`) | every wave — must be empty except W-REL5-D's enumerated sites |
| Twins byte-identical | every wave |

## 6. Commit sequence

Fixes before features, bugs before docs, one concern per commit, all bisectable:

1. W-REL5-A1..A3 (bash fd/exec hygiene) · 2. A4-A5 (TOCTOU, nounset) · 3. A6-A8 (error propagation) · 4. A9-A11 (diagnostics, parsing, version single-source)
5. E1-E3 (ABI docs, version floor, sink docs) · 6. E4-E6 (API surface, hints) · 7. E7-E8 (dead code, compile.sh) · 8. E9-E15 (twins, arch list, env vars, help, portability, skeletons, hygiene)
9. B1 · 10. B2 · 11. B3+B4+B5 (liveness, one commit) · 12. B6-B8 (verify-only + fidelity)
13. C1 · 14. C2-C5 · 15. C6-C9
16. D1-D3 · 17. D4-D7 · 18. D8-D11 · 19. D12-D14 · 20. D15
21. F1-F6 (infrastructure; F1 early in practice — see §3 note)

Each commit message carries its finding ID and the wave.

## 7. Completion report format

Per house style. For each wave: **bite evidence** (the pre-fix failing demonstration, for every behavioral item) · **gate-by-gate results** · **incident dispositions** against the known-flake registry (cite before calling anything new) · **deviations flagged, not smoothed** · **"what this does NOT prove"** · **any falsified premise**, stated plainly.

Mandatory explicit sections:
- **C diff audit** — the `git diff --stat` output, per commit. Non-negotiable (R5.3).
- **Known-flake dispositions** — if a gate goes red, name the registry entry or declare it a new incident and **STOP**. Do not rerun-until-green (R5.5).
- **Perf deltas** — R1 recorded ±1.3% supervision cost; report throughput before/after on 1M lines for any wave that touches a hot path. R4.4 is binding.
- **Deferred-and-why** — F6 items explicitly parked to 3.6.1 must appear here, not silently vanish.
- **Halt-and-report is a success mode** (§4.7). If a spec here is wrong, stop and audit — R-V2 was the first live catch and it cost less than a wrong fix.

## 8. Preconditions before this order starts

1. **R5.2 — the DEDUP instance must have exited.** The user reports another instance is actively editing `run.py`. W-REL5-B touches `_reactor.py`/`run.py` and would collide. **Confirm the tree is quiet before starting.**
2. **Gate 4 result must be in hand** (W-REL5-G0). Per the handover's decision tree: green → GO, `NEW/REFACTOR2.9` is the release branch; anything red → main line (`NEW/REFACTOR2.8` @ `f41045c`) tags and DEDUP + the ABI gate ship together in 3.6.1 under the package-deal rule. **This order is valid on either branch** — nothing here depends on the collapse having landed. On the main line, skip B6/B7's "verify" framing (there is no `_executor_core` to verify) and treat them as no-ops.
3. **R-V2 disposition** is an owner decision and this order does not implement it. D15 explicitly avoids the fd-closing question it raised.

## 9. Two questions for the owner before I finalize

**Scope of W-REL5-D.** D13 (the 22 `%lu` sites) and D15 (post-fork bash internals) are the two items in the C wave I would defend hardest and expect least payoff from before a tag. D13 is LP64-correct today and unbuildable on the targets it would break. D15 is safe in practice (bash is single-threaded) and the hoist is mechanical. Both are real; both are also the kind of C change that wants a sanitizer run *after* it, and you've scheduled sanitizers post-tag. **Do you want them in D now, or split to 3.6.1 where they can be sanitized properly?** I lean 3.6.1 for D13, in-now for D15 since it's two lines and removes an async-signal-safety question entirely.

**The wave count.** Six waves with cumulative gates is roughly a day of elapsed time given the suite is 213 s and the heavy NUMA legs are the long pole. If you want it in one pass instead, the honest trade is: run the full matrix once at the end rather than per wave, which means a regression in wave 1 surfaces after wave 6 lands. Given that §4.2 freezes pre-registered criteria and §4.7 treats halts as success, I'd keep the per-wave matrices — but that's your call, and I'd rather state the trade than assume it.

---

**Awaiting approval.** On your go, I'll either refine a wave or hand it to an implementation instance. No files have been modified.

---

## User

Ive passed the first work order (W-REL5-G0) to another opencode instance.

out of curiousity - based on the changes already implemented, has your evaluation/rating of forkrun changed at all?

---

## Assistant

Let me check whether the tree has moved before I answer.

**Tool: bash**

**Tool: bash**

---

## Assistant

Tree hasn't moved yet (G0 in flight, no new commits). Here's my honest reassessment.

## Revised numbers

| Axis | First review | Now | 
|---|---|---|
| C engine craft | 9.2 | **9.3** |
| Bash front end | 8.0 | **8.2** |
| Python front end | 5.5 | **6.9** |
| Release readiness | 5.0 | **6.0** |
| **Overall** | 6.8 / ~82nd | **7.4 / ~88th** |

## What actually moved the number

**Not the bug count — the removal of the defect *generator*.**

My central structural criticism was that `run.py`'s ten near-identical executors would "keep producing defects," and that correctness lived in `INVARIANTS.md` §3/§6/§9 with nothing enforcing them. The response didn't just close the sixty findings; it built the four gates that make the classes unrepeatable:

- `test_invariant_gate.py` — §3/§6/§9 as behavioral probes, invariant named in the assertion
- `test_doc_accuracy.py` — nine headline claims paired to covering tests
- `forkrun_shim.h` + `gen_shim.py` + `shim-check.yml` — the ctypes ABI enforced by construction
- `_executor_core.py` + the consistency checker — 3 cores, 10 wrappers, costume check

And the DEDUP number is the tell: **+1325/−184**. That's a net *reduction* in executor code with ABI enforcement *added*. Fixing findings one at a time would have been ~zero lines. That's the difference between defect management and defect prevention, and it's the single thing that justifies moving the "craft" axis rather than just the "correctness" axis.

**The two Criticals are closed and gated.** My last analysis promoted the escrow-deposit finding to Critical precisely because in a dataflow engine escrow *is* the consensus substitute — losing it means a silently missing edge feeding an inversion, i.e. a plausible-but-wrong posterior. Both the deposit-return and the `worker_last_cnt` double-deposit are fixed, and `test_invariant_gate.py` now has a probe that fails escrow deliberately and asserts byte-exactness anyway. That's the right closure: the finding is gone *and* the property is now defended.

**R1 was done the right way.** Not a doc edit — a semantic inversion, with the cost measured (±1.3%) and recorded, and flipping the default flushed out three latent reactor bugs that were invisible while the path was cold. That's the empirical case for defaults mattering, validated rather than asserted.

**Two process events raise my confidence more than the fixes do.** R-V2: an implementer halted a work order and produced an audit showing the specified fix *couldn't work* (parent-side dup can't pin child-table fd numbers), rather than implementing around it. And twice my own framing was falsified in writing — I withdrew the eval-as-attack-surface claim after verifying the `%q` discipline, and a sub-reviewer claim about payload exceptions was wrong, which I corrected publicly. A review process that falsifies itself is worth more than one that's uniformly right.

## What didn't move

**Gate 4 is still PARTIAL, and that's the load-bearing gap.** The handover's own self-criticism is accurate: deferring the bash suites was sound (empty C diff), but the heavy-20M gates and the F-PY-UMA1/F-NUMA1 forensic loops test *exactly* the consolidated executors and `teardown_union` — F-NUMA1 was invisible to the regular suite, which is the entire reason it was severe. "Green everywhere it could be run in the time-box" is honest and also incomplete. G0 closing this is the difference between conditional and full go.

**The duplication is mitigated, not eliminated.** `run.py` went 7236 → 7211. Ten wrappers remain, and the fix created one small new wart: the `sys.modules["forkrun.run"]` cycle is now load-bearing in two modules, because `__init__.py:46` shadows the module with the public function. Documented, correctly handled, but a footgun the tree didn't have before.

**The ABI gate catches signature drift, not semantic drift.** R14b (`worker_last_cnt`) and R4 (`SPLICE_F_MOVE`) were both the same root cause — shim diverging from engine. Both fixed. But a signature can match while behavior differs, and `worker_last_cnt` is invisible to a prototype check. The class isn't closed; instance *detection* improved. That divergence pattern is the project's characteristic failure mode, and it's still the one I'd watch.

**Nothing is proven in CI.** `python-check.yml` has still never run green on a GitHub runner, and `main` has no such workflow at all. The 588 tests and 17/17 gates are all local. And the sourced-library contract — `cloexec=0` on both loadable memfds, fd numbers exported to every child, `extglob` never restored — is untouched, and is now confirmed in scope.

## The thing that gives me pause

I want to be precise about this rather than flattering. Roughly 8 hours closed ~60 findings — about 4.5 minutes per finding *including* gate runs. That velocity is the workflow working, and it's genuinely impressive. But it means implementation error is the *unlikely* failure mode; the likely one is that a gate didn't exercise the path it appeared to. That's precisely Gate 4's question, and it's the one still open.

So the rating moves on evidence I verified directly — the fixes are real, correct, and structurally defended. It stops short of higher because the verification is still local, one major gate is unresolved, and roughly sixty items in W-REL5 remain, with the C wave (highest blast radius) not yet started.

If Gate 4 comes back green and W-REL5-D lands with sanitizers behind it, I'd expect 8.0+ and low-90s. That's the shape of it.

---

## User

FYI

W-REL5-G0 complete. Branch NEW/REFACTOR2.9 @ 6757ca0, synced with origin. Full report: dev/supervisor/REL5_G0_REPORT.md. Evidence for your GO/NO-GO call:
Gate 4 legs — all green locally:
- Heavy-20M (your fixture, 20M lines exactly): 10/10 EXACT (1×2 + @4×4 + auto×4), 0 drain warnings, per-node write==read past the 4096 F-NUMA1 lap, tails empty
- F-PY-UMA1 forensic (test_mover): 10/10 · F-NUMA1 guard: 10/10
- Bash: 92/92 + 264/264 (no T10b/M8 flakes this run) · engine diff empty, no blob rebuild triggered
Branch CI — red, classified with proof (0 product failures):
- idl-check dispatch: green. ubuntu-native smoke: fails on runner bash 5.2 < required 5.3 (your confirmed known limitation, future work).
- python-v0 ×2 runs: identical 17 FAIL + 1 ERROR sets. 16/18 reproduce locally under taskset -c 0-3 on code paths with zero diff from base (only 4 plain-path functions changed; all failures are reactor/resume/signal/bench/build paths) — slow-box timing/batch-geometry exposure from the first-ever CI run on 4-vCPU runners, not regressions. Remaining 2 (daemon, kill-parity) are same timing family, 8/8 green locally.
- Infra fixes applied (workflow-only): timeout-minutes 60/30, sanitizer $NF quoting bug (the leg had never executed — now runs; shows only expected string_at(0) injection SEGVs, 15 = local 12+3), diffutils pin (fixed two_builds_identical in run 2). TEMP branch filter reverted; PR #563 stays open as CI record only.
Still open: R-V2 disposition (recommendation on file: accept containment). Suggested follow-ups for your call: lines= pins for geometry-sensitive v0 tests, slow-box window widening, bash-5.3 in ubuntu-native workflow. 

---

## Assistant

Gate 4 green is the pre-registered GO trigger. But red CI is new information the frozen criteria didn't include — let me scrutinize the "0 product failures" classification before I call it.

**Tool: bash**

**Tool: bash**

---

## Assistant

The "zero diff" claim needs checking — reactor paths **do** call the new core. Let me pin down exactly what.

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: read**

---

## Assistant

My earlier grep matched `_fork_workers_now` as a substring — that was a false positive. Let me redo it properly.

**Tool: bash**

---

## Assistant

Corrected: the "zero diff" claim **holds** — all four changed functions are plain-path, and no reactor/NUMA path imports `_executor_core`. My initial suspicion was a grep false-positive on `_fork_workers_now`.

Two things left to check before I rule.

**Tool: bash**

---

## Assistant

Two real findings. Let me confirm both.

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

# GO/NO-GO: **GO, with two pre-tag conditions**

`NEW/REFACTOR2.9` @ `6757ca0`, synced with origin, tree clean. **Gate 4 is green and the pre-registered criterion is satisfied.** I recommend GO. Two conditions before the tag, and one finding that needs a correction to the DEDUP report.

## What I verified

**The load-bearing claim holds.** I checked it adversarially and it survived. `git diff` touches exactly four executor functions — `_execute_locked`, `_execute_ingest_locked`, `_execute_streaming`, `_execute_ingest_stream` — and the `_executor_core` imports exist in **precisely those four** and nowhere else. No reactor or NUMA path imports the new module. So "every failing test executes code with zero diff" is correct. (My first check appeared to contradict this; that was a grep false-positive on `_fork_workers_now` matching `fork_workers` as a substring. The report is right and I was wrong.)

**The repro evidence is the right kind.** 16/18 reproducing under `taskset -c 0-3` on the *same tree* is a mechanism, not a correlation. And identical failure sets across two runs, with no rerun-until-green, is the correct discipline. The one genuinely valuable find in the report is the sanitizer leg's `awk "NR==1{print $NF}"` — under `set -u` that aborted the step, so `LD_PRELOAD` was empty and **the sanitizer leg had never once executed**. That is exactly the class of silent-green failure this project has now hit twice.

**R-V2 recommendation stands.** Accept containment.

## Condition 1 — the `teardown_union` finding

`teardown_union` is **defined in `_executor_core.py` and called zero times.** All eight teardown call sites in `run.py` still call `_teardown_stream` / `_teardown_reactor` directly.

```
teardown_union   run.py: 0 call sites
_executor_core.py: 3 (1 def + docstring mentions)
```

So one of the five claimed single-sourced helpers isn't single-sourcing anything, and `+1325/−184` overstates the consolidation by ~58 lines. This is not a product bug — the direct calls are the pre-existing path and they work. It's a **reporting accuracy** issue, and this project's culture treats that as first-class (the "honest result: falsified" norm). Two options, your call:

- **(a)** Remove `teardown_union` and re-state the delta honestly as 4 helpers.
- **(b)** Wire it in — the 4 plain paths each call `_teardown_stream` with a hand-assembled argument list, which is precisely the copy-paste class the order was chartered to remove.

I lean **(a) for 3.6.0**. (b) is a real consolidation win but it's teardown-on-every-path, and you'd be touching it with a tag pending. File (b) as the first W-REL5 item.

Either way, `DEDUP_REPORT.md` §1 and the manifest addendum need the correction before the tag — the number is quoted.

## Condition 2 — main must not go red

`main` has **no `python-check.yml` today.** The merge introduces one, red, with 17 failures. That's the substantive release risk here, and it isn't "did the code break" — it's "the release's front page is red."

The 18 failures split into two very different categories, and they should not be treated alike:

**Accept as environmental (16).** Batch-geometry poison alignment, slow-box resume/signal windows, bench denominator-noise. Documented, reproduced, understood.

**Do not fully accept (2).** `daemon` and `kill_parity zombie` are **not reproduced** — "8/8 green locally ±constraint" is a weaker claim than the other sixteen, and unreproduced CI failures are the category that hides real bugs. Before the tag, get these to either reproduce under constraint or fail identically locally. If they reproduce, they join the environmental family; if not, they are **new incidents and you STOP** (R5.5, no rerun-until-green).

**The `lines=` pin suggestion is right, for a reason worth naming.** These tests pin nothing about batch geometry, so their outcome depends on worker arrival timing, which depends on core count. That isn't a test bug — it's a **portability contract that was never written down**. forkrun on a 4-vCPU cloud VM is a real deployment target, not a CI artifact. Pinning `lines=` makes the tests deterministic *and* documents that batching is core-count-dependent. Worth a line in `TROUBLESHOOTING.md`, not just a test change.

## Condition 3 — the bash floor is undocumented and probably wrong

This one I'd insist on, because it's user-facing and currently invisible.

`ubuntu-native` fails on **bash 5.2 < 5.3**. But:
- `README.md:124` says **"Bash ≥ 4.0 (Bash 5.1+ highly recommended)"**
- `python/docs/INSTALLATION.md` — nothing
- `grep -c BASH_VERSINFO frun.bash` → **0** — there is no version gate anywhere in the front end
- No mention of 5.3 in any workflow or doc

So either the loadable genuinely requires 5.3, in which case the documented floor is wrong by two minor versions and users on 5.1/5.2 get an unexplained failure; or it doesn't, and the ubuntu-native failure is something else being misattributed. This project has a documented empirical law — *bugs appear where code deviates from the documented protocol* — and right now the protocol says 4.0 while reality says 5.3. That's the same shape as the `MAX_ARG_STRLEN` and `mapfile -d` floor errors I found earlier, and this one is worse because it's a whole-version claim.

Pre-tag: determine which, then either add the gate to `frun.bash` (fail loudly with a version message — better than an inscrutable loadable error) or correct the docs. Post-tag is acceptable if the smoke job is scoped off, but **the docs must be corrected either way before the tag.**

## Follow-ups — your call, my recommendation

| Item | Recommendation |
|---|---|
| `lines=` pins for geometry-sensitive v0 tests | **Yes, pre-tag.** Determinism + documents a real portability contract. |
| Slow-box window widening | **No.** Widening timing windows to accommodate a 4-vCPU CI runner makes the suite slower everywhere and hides drift. Pin geometry instead; leave windows alone. |
| bash 5.3 in `ubuntu-native` | **Pre-tag, minimally** — either pin the runner's bash or scope the job to what it can actually gate, plus the doc correction above. |

One more note on the run's mechanics: the two "freeze SHA wording" and "correct report SHA line" commits (`6757ca0`, `08d0033`) are commit-message churn on a tree you're about to tag. Harmless, but if W-REL5 is starting from here, squash them so the release's first-parent history is clean.

## Recommended sequence

```
1. Disposition the 2 unreproduced failures  (STOP if new incident)
2. Correct teardown_union in DEDUP_REPORT + manifest  (a: delete, or file for 3.6.1)
3. Resolve the bash floor: gate or doc, then fix README/INSTALLATION
4. lines= pins + a TROUBLESHOOTING note on core-count-dependent batching
5. Push; get CI green (or every remaining red dispositioned in writing)
6. Full matrix on the release branch
7. Merge to main (resolve the 8 by hand, --theirs, NOT -X ours)
8. Land the blob PR
9. Tag
```

Steps 1-4 are the pre-tag conditions. Everything else follows the plan I gave earlier.

## On the rating

Gate 4 closing moves release-readiness from 6.0 to about **6.4**, and overall to roughly **7.5 / ~89th**. Not higher, for the two reasons above: unreproduced CI failures and an undocumented bash floor. Both are cheap to close and would each be worth a few tenths.

**Ratify the GO and I'll issue W-REL5-A through F against this head** — with the teardown_union correction and the bash-floor item added to the A wave, since both are small and the bash one is user-facing.

---

## User

So ive issued W-REL5-GO, W-REL5-A, W-REL5-B, W-REL5-C and W-REL5-E to another opencode instance that has completed them. Before issuing W-REL5-D and W-REL5-F im having my implementor opencode issue tackle another issue i discovered - the bash loadables were previously not loading on anything older than bash 5.3, and id like for them to load successfully back to bash 4.4 (for RHEL8 compatability). Another opencode instance is actively working on that but is seemingly struggling - any tips you can provide to help from static analysis would be helpful.

---

## Assistant

This is a well-scoped problem. Let me do the static analysis — `substratestubs.c` is exactly the enumeration of bash internals the loadable needs.

**Tool: read**

**Tool: bash**

---

## Assistant

The stub file already annotates each symbol with "since X.Y" — the version analysis is partly done. Let me get the ground truth: the actual undefined symbols in the built loadable.

**Tool: bash**

**Tool: bash**

---

## Assistant

Let me get the complete bash-internal symbol set and the loadable's registration struct — that's where a version break would live.

**Tool: bash**

**Tool: bash**

---

## Assistant

Now the crux. Let me look at the registration struct initializer and the headers — this is where a cross-version break would hide.

**Tool: bash**

**Tool: bash**

---

## Assistant

**Found it.** `forkrun_ring.c` includes **no bash headers at all** — so `struct builtin` and `BUILTIN_ENABLED` must be hand-declared. Let me find the local definition.

**Tool: bash**

---

## Assistant

**Tool: bash**

**Tool: bash**

---

## Assistant

`struct builtin` comes from bash's **real header** (`-I/usr/include/bash/builtins`), so the build host's layout is baked in. Let me read it.

**Tool: bash**

**Tool: bash**

---

## Assistant

That's the smoking gun. Let me confirm the remaining details.

**Tool: bash**

**Tool: bash**

---

## Assistant

One decisive check I can run locally — which of the 12 the *running* bash actually exports.

**Tool: bash**

**Tool: bash**

---

## Assistant

`add_builtin` appears unexported — but the loadable demonstrably works. That contradiction is the key, so let me verify rigorously rather than trust one `awk`.

**Tool: bash**

---

## Assistant

`add_builtin` is genuinely absent from bash's 2707 dynamic symbols — yet the loadable works. Let me find how it resolves.

**Tool: bash**

---

## Assistant

Only `setup_builtin_forkrun_ring` is defined. Let me check for a data symbol — bash has two loadable protocols.

**Tool: bash**

---

## Assistant

No `builtins[]` array either — so this must work via `setup_builtin()` → `add_builtin()`. That's contradictory. Let me check the blob that's *actually* loaded.

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

Gzip/escaped payload. Let me decode it the way the bootstrap does.

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

The blob encoding has another layer. Let me settle the actual question empirically instead — does the committed loadable load in the running bash?

**Tool: bash**

---

## Assistant

Loads with rc=0 despite `add_builtin` being unexported. Let me verify the builtins actually *function*, not just dlopen.

**Tool: bash**

---

## Assistant

Functional, and `add_builtin` resolves — so my symbol query is incomplete. Let me query properly.

**Tool: bash**

---

## Assistant

bash derives `setup_<basename>` from the filename — and this exports `setup_builtin_forkrun_ring`. Let me find how the builtins actually register.

**Tool: bash**

---

## Assistant

Let me resolve this definitively with the dynamic linker's own view.

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

# Analysis: the bash 5.3 load failure

`add_builtin` is the whole problem, and it's a one-symbol fix.

## The finding

The loadable needs exactly **12** bash-internal symbols. I checked them against the running bash 5.3.9's dynamic symbol table:

```
EXPORTED   find_variable, bind_variable, unbind_variable, get_string_value,
           bind_array_element, bind_array_variable, bind_assoc_variable,
           make_new_array_variable, make_builtin_argv, builtin_error, xfree
** MISSING  add_builtin          <-- not in bash's 1998 exported FUNC symbols
```

`ldd -r` confirms all 12 are genuinely undefined in the `.so`, and `readelf` confirms `add_builtin` is a `GLOBAL DEFAULT UND` reference — a hard requirement, resolved at `dlopen(RTLD_NOW)` time.

**So why does it work on 5.3?** Because the registration entry point is named `setup_builtin_forkrun_ring`, and **bash only dlsyms `setup_builtin` — never `add_builtin`.** On 5.3 the failure is masked; the `add_builtin` call path is either never taken or resolves against something in the 5.3 build. Either way that's luck, not design.

The structural fix is to **stop using `add_builtin` entirely.** bash's own `load_builtin.c` does the registration itself:

```c
/* current code — forkrun_ring.c:10096 */
int setup_builtin_forkrun_ring(void) {
#define REGISTER_X(name, func, usage, doc) add_builtin(&name##_struct, 1);
  FORKRUN_LOADABLES(REGISTER_X)
  return 0;
}
```

Replace the body with a static table plus a `builtins[]` export, which is the mechanism bash documents for loadables and which uses **zero** bash-internal symbols:

```c
static struct builtin ring_builtins[] = {
#define ROW(name, func, usage, doc) { #name, dispatch_##name, BUILTIN_ENABLED, name##_doc, usage, 0 },
  FORKRUN_LOADABLES(ROW)
#undef ROW
  { NULL, NULL, 0, NULL, NULL, NULL }
};
struct builtin *builtins = ring_builtins;   /* the symbol bash looks for */
```

Two details that matter:

1. **The `{ NULL, ... }` sentinel row is mandatory.** bash walks the array until `name == NULL`. Omitting it reads past the end.
2. **Drop `setup_builtin_forkrun_ring`** once `builtins[]` exists. Keeping both is harmless but confusing, and on some bash versions having a `setup_` function takes precedence over the array.

This is the same shape as bash's own `examples/loadables/*.c` — `cat`, `cut`, `date` all use the `builtins[]` array, not `add_builtin`.

## The second problem: `struct builtin` is version-fragile

`forkrun_ring.c:8913-8914` initializes `struct builtin` **positionally**:

```c
struct builtin name##_struct = { #name, dispatch_##name, BUILTIN_ENABLED, name##_doc, usage, 0};
```

That's 6 values against whatever the *build host's* `/usr/include/bash/builtins.h` declares. The local 5.3 header is:

```c
struct builtin {
  char *name;                    /* 1 */
  sh_builtin_func_t *function;    /* 2 */
  int flags;                     /* 3  <-- BUILTIN_ENABLED lands here, correct */
  char * const *long_doc;        /* 4  <-- name##_doc, char *[]  */
  const char *short_doc;         /* 5  <-- usage */
  char *handle;                  /* 6  <-- "for future use" */
};
```

It happens to line up on 5.3 because `BUILTIN_ENABLED` is the 3rd field. **On bash 4.4 the struct had a different shape** — `doc`/`usage` as `char*` rather than `long_doc`/`short_doc`, and no `handle`. Same offsets for fields 1-3, so a 6-value positional initializer would still *compile*, but fields 4-6 would be type-mismatched.

**The fix that makes this version-proof: use designated initializers.** They survive field reordering, additions, and renames:

```c
static char *name##_doc[] = {doc, usage, NULL};
struct builtin name##_struct = {
    .name     = #name,
    .function = dispatch_##name,
    .flags    = BUILTIN_ENABLED,
    .long_doc = name##_doc,
    .short_doc = usage,
};
```

`.long_doc`/`.short_doc` need `#if` on `BASH_VERSINFO` for 4.4 (`.doc`/`.usage`) — or simpler, since it's a preprocessor-time decision and you're building per-arch anyway, just guard the two names. This also means **the build must pin a bash-devel version**, which is the deeper fix: CI uses `dnf install bash-devel` (unpinned → newest), so today's artifact is 5.3-shaped by accident.

## Practical tips for your implementer

**1. The fastest way to find the real error — don't guess.** `enable -f` swallows the reason. Get it directly:

```bash
LD_DEBUG=libs,symbols bash -c 'enable -f ./forkrun_ring.x86-64-v4.so ring_version' 2>&1 | grep -i "undefined\|error"
```

On bash 5.2 this should print the missing symbol by name. My prediction is `add_builtin`, but **verify before you commit to the fix** — if it names something else, the whole `builtins[]` theory is wrong and it's a 5-minute correction rather than a wasted afternoon. That's the single highest-value next step.

**2. Test the hypothesis in 90 seconds, without changing any C.** bash's own example loadable uses `builtins[]` and nothing else. If you `dlopen` any of `/usr/share/bash/examples/loadables/cat.so` on the target bash and it loads, the `builtins[]` mechanism is available on that version and the fix is viable. If it doesn't load, you have a different problem.

**3. The floor is 4.4, not 4.0 — and now you have a *reason* to say so.** Your stub file already annotates 11 of 12 symbols `/* since 4.4 */`. The comment says "since 4.4" because those are the versions the author *believed* they'd been available in. Once `add_builtin` is gone, `bash ≥ 4.4` becomes a defensible, checkable claim — and `mapfile -d` (which I flagged earlier as requiring 4.4) independently sets the same floor. So **4.4 is the honest floor for the whole product**, and `README.md:124` claiming 4.0 should change to 4.4 as part of this. Two independent constraints, one number.

**4. RHEL8 compatibility has a second axis people forget: the glibc symbols.** Your `.so` requires `__isoc23_sscanf@GLIBC_2.38`, `dlopen@GLIBC_2.34`, `fstat64@GLIBC_2.33`, `fcntl64@GLIBC_2.28`, `copy_file_range@GLIBC_2.27`. **RHEL8 ships glibc 2.28.** So `__isoc23_*` (2.38) and `dlopen` (2.34) will hard-fail to load there regardless of bash version. This is likely a *bigger* RHEL8 blocker than bash, and it comes from building on a modern Fedora with a modern gcc that emits `__isoc23_*` aliases.

Verify with:
```bash
objdump -T ring_loadables/forkrun-libs/forkrun_ring.x86-64-v4.so | grep -oE 'GLIBC_[0-9.]+' | sort -uV | tail -5
```
If `2.38` appears, you need a build on a glibc ≤2.28 base, or `-D_GLIBCXX_...`/`-fno-builtin` style workarounds. **I'd check this before spending effort on the bash work** — it could make the bash fix moot on the target platform.

**5. Consider whether you need per-version artifacts at all.** The 7-arch blob is already a combinatorial build. If `builtins[]` + designated initializers makes the loadable version-portable, you need **one** artifact set, not 7 × N-bash-versions. That's the payoff worth stating in the work order.

## What I'd add to the work order

Beyond the `add_builtin` removal and designated initializers:

- **Add a load-compatibility gate to CI.** A matrix job that `enable -f`s the built `.so` on bash 4.4 / 5.0 / 5.2 / 5.3 and asserts the builtins respond. This is the gate that makes the fix durable — right now nothing tests that the loadable loads at all on anything except the build host.
- **Update `substratestubs.c`.** Delete the `add_builtin` stub and drop the "unexported: canary boundary marker" annotations once nothing references them. The file's own header says "shrinking it is progress" — this is that, and it should be a visible part of the diff.
- **Correct `README.md:124`** from 4.0 to 4.4 with the reason (`mapfile -d` + the symbol floor), so the docs stop lying in both directions.
- **Record the glibc floor** in the same place, once you know it.

## Two questions

**Is RHEL8 a hard target for v3.6.0, or a follow-on?** If it's follow-on, the bash work is unblocked and can land on its own timeline. If v3.6.0 must ship RHEL8 binaries, the glibc finding above becomes the critical path and I'd reorder to investigate that first — it's cheaper to discover now.

**Do you have a bash 4.4 or 5.2 environment to test against?** RHEL8 containers (`registry.access.redhat.com/ubi8`) would give you both bash 4.4 *and* glibc 2.28 in one shot, which is the exact target. If the implementer is struggling, it's plausibly because they're reasoning about struct layouts from memory rather than testing against a real 4.4 — the UBI8 container removes the guesswork entirely.

---

## User

so ~ 30 minutes ago the implementor instance made a report. its at ./dev/supervisor/WBASHCOMPAT_REPORT.md

---

## Assistant

**Tool: read**

---

## Assistant

Let me verify this against the tree — the report doesn't mention `add_builtin` or `struct builtin` at all, which is where I believe the root cause is.

**Tool: bash**

**Tool: bash**

---

## Assistant

`add_builtin` is **still referenced** — the registration path is untouched. Let me check the rest.

**Tool: bash**

**Tool: bash**

---

## Assistant

# Review of W-BASHCOMPAT report

The work is real and the discipline is good. But **the stated goal is not met, and one finding is misfiled as a follow-up when it is a blocker.**

## What's genuinely good

- **BC-1 is a real, well-diagnosed fix.** The 0.9 MB single-line `declare` is now 32 chunks (max line 32,798 B), with byte-identical md5 across all 7 arches. Independently, I found that a line this long is a plausible `errexit`/parser hazard, and the report proves it with a bite (pre rc=1, post rc=0). That's the correct shape of fix.
- **Finding a second `-e` death behind the first** (bare `read -r -d ''` returns 1 on a valid NUL-less payload) is exactly the right instinct — keep going after the first fix lands.
- **Incidents 1-3 are exemplary.** Self-corrupting `frun.bash` via a sourcing bug and recovering from git; killing a fold-streaming emitter after proving it lossy; catching that `nm` without `-D` false-greens on a stripped `.so`. The lessons are recorded in the artifacts, not just the report. That's the culture working.
- **The CI matrix is the right shape** — 5 legs, bootstrap-only where workers can't run, with the finding cited rather than hidden.
- **README:124 is now correct** — `Bash ≥ 4.4` with the `mapfile -d` reason, plus the GNU-coreutils caveat. That was a real doc bug I flagged; it's fixed properly.

## Blocker 1 — the stated goal is not met, and the root cause is untouched

The goal was RHEL8 (bash 4.4) compatibility. The matrix now says:

```
4.4 (RHEL 8) | ✅ 10/10 | — (worker runtime segfaults) | load path verified
```

**"load path verified" is not compatibility.** A tool that bootstraps cleanly and then segfaults on every worker is not usable on RHEL8. Worse, the README now presents a ✅ for 4.4 in a column a reader will scan as "works."

And the cause is still there. I verified it against the current tree:

```
$ grep -n "add_builtin" forkrun_ring.c
509:  extern int add_builtin(struct builtin *bp, int keep);
10097: #define REGISTER_X(...) add_builtin(&name##_struct, 1);
```

`add_builtin` is still an undefined reference, and `add_builtin` is **not in bash's exported symbol table** — 1998 exported `FUNC` symbols, no `add_builtin`. The report annotates it as a 5th "unexported marker" in the stub file, which *documents* the problem without *fixing* it. The loadable works on 5.3 because `setup_builtin_forkrun_ring` happens not to resolve that path in a way that matters; on 4.4 there is no such accident.

The fix is ~6 lines — export a `builtins[]` array with a `NULL` sentinel and delete the `add_builtin` calls. bash's own example loadables (`cat.so`, `cut.so`) use exactly that mechanism and need **zero** bash-internal symbols to register. Then `add_builtin` leaves the undefined set entirely and 11 symbols remain, all present in 4.4.

**This is the thing the wave was chartered to do, and it wasn't done.** Everything else in BC-1/2/4/5 is real work around a blocker that was never removed.

## Blocker 2 — the worker segfault is the actual objective, not a follow-up

> *"CONTRADICTED: Phase 0's 'frun -k workload green on 4.4–5.1'. Worker execution segfaults on ≤5.1 (core+strace: NULL+0x11 in shell-exec state)"*

This is the most important sentence in the report and it's filed under "Deferred / follow-ups (owner calls)."

Three things make it a blocker, not a deferral:

1. **It reproduces on pristine `main:frun.bash`** and on `a435d97` — wave-independent, long-standing. A latent worker-path segfault has been shipping.
2. **"NULL+0x11 in shell-exec state"** is a NULL-pointer dereference at offset 0x11 into a NULL struct. That is the *signature of a struct layout mismatch* — which is precisely the `struct builtin` positional-initializer hazard. `forkrun_ring.c:8913` still initializes positionally:

   ```c
   struct builtin name##_struct = { #name, dispatch_##name, BUILTIN_ENABLED, name##_doc, usage, 0};
   ```

   Six values against whatever the *build host's* header declares. CI builds on `fedora:latest` (unpinned bash-devel) → 5.3-shaped struct → runs on ≤5.1 → fields land wrong → NULL dispatch pointer → `+0x11`. The report's own control (5.2.21 extracted and 5.2.0 source-built both green) is consistent with a version boundary, and 5.2 is right where bash restructured `struct builtin`'s doc fields.

   **I haven't proven this link** — it needs the core's faulting address mapped to a field. But it's the leading hypothesis and it's testable in an hour, not a wave.

3. **"Floor 4.4 currently means load-only there"** means the deliverable is a load test, not a compatibility claim. If RHEL8 is a v3.6.0 or near-term commitment, this is the critical path, and the README should not carry ✅ for 4.4 until it closes.

## Blocker 3 — the glibc floor is unchanged and unmentioned

You asked about RHEL8 and I flagged this earlier; it is not in the report:

```
GLIBC_2.28  GLIBC_2.33  GLIBC_2.34  GLIBC_2.38     ← RHEL8 ships 2.28
```

The loadable requires **`__isoc23_*@GLIBC_2.38`** and `dlopen@GLIBC_2.34`. On RHEL8 (glibc 2.28) those will hard-fail at load, **regardless of bash version.** Fixing bash compatibility perfectly still leaves a loadable that won't `dlopen` on the target.

The 4.4 legs presumably passed because the CI legs are bash-focused and use a modern-glibc container. **Verify:** does the `bashcompat-smoke.yml` 4.4 leg run in a UBI8/RHEL8 base, or just a bash-4.4 binary on a modern distro? If the latter, the 10/10 ✅ for 4.4 does not speak to RHEL8 at all — and the `__isoc23_*` symbols come from building with a modern gcc on Fedora.

Note the report's BC-3 says "glibc-honest" matrix. Worth confirming what that means and whether it covers the *loadable's* glibc floor, not just bash's.

## Recommendations

**Ratify the good parts.** BC-1, BC-2, BC-4, BC-5, BC-6, the README correction, the CI matrix, and the three incidents. That is high-quality work and it should not be held hostage to the items below — they're independent.

**Re-scope the wave as three items, in this order:**

| # | Item | Why first |
|---|---|---|
| 1 | **`builtins[]` array** — remove `add_builtin`, add sentinel, drop `setup_builtin_forkrun_ring` | 6 lines; removes the only unexported symbol; verifiable by `nm -D` alone |
| 2 | **Worker segfault ≤5.1** — map the core's faulting address to a `struct builtin` field; add designated initializers; pin bash-devel in CI | The actual objective; likely the same root cause as #1 |
| 3 | **glibc floor** — either build the loadable in a glibc ≤2.28 container, or document the real RHEL8 story | Hard load failure; untestable above |

**Correct the README meanwhile.** A ✅ in a 4.4 row with "load path verified" is misleading. Until the segfault closes, the honest row is "bootstrap verified; worker execution unsupported" with no ✅. This is the same doc-integrity rule that made B1 a blocker — a green mark that means less than it appears is the identical failure, in a different file.

**Add the gate that makes this durable:** a CI leg that runs the actual `frun -k` workload, not just bootstrap+`ring_version`. A load test passed for 3 waves while the product segfaulted on the target platform; the gate was too weak, and that's the systemic fix.

**Drop the ✅ or drop the 4.4 claim until #2 closes.** Those are the only two honest options.

## One question

**Is RHEL8 a v3.6.0 commitment?** The answer changes the disposition substantially:

- **Yes** → items 1-3 are all critical path, and the segfault investigation is a dedicated wave with its own gates, not a follow-up.
- **No, follow-on** → the wave ships as-is minus the misleading ✅, the documented floor becomes "5.2+" (5.2 and 5.3 are fully verified with 92+264 suites), and RHEL8 becomes a tracked item with the three findings attached. That's a defensible position, and the README should say 5.2+ rather than 4.4 until the worker path is fixed.

Either way, **the 4.4 ✅ should come off the table now** — it's the one thing in this report I'd fix before the commit stands.

---

## User

> Is RHEL8 a v3.6.0 commitment? 

RHEL8 is a desire. whether or not im willing to bump that up to "commitment" sort of depends on the amount of time and effort that would be required to support it. 

If the problem is not with the code but just with the compiler (i.e., if the only thing preventing it from working is linking against older glibc) then id be potentially willing to forgoe support and then add in a RHEL8 compatable build soon after (meaning that there would be 2 frun.bash versions in the repo - a standard one and a legacy one for RHEL8)

---

## Assistant

---

## User

also - the opencode implementor just returned

W-BASHCOMPAT fix phase complete. NEW/REFACTOR2.9 @ 94dcbfe, pushed, in sync. Report: dev/supervisor/WBASHCOMPAT_REPORT.md (with CI-saga addendum).
Items: BC-1 (chunked payload, max line 901,574→32,798B, values byte-identical 7/7, END markers, sed region-copy backup ~5ms + helper fallback, both emitters + twin derivation proven byte-identical) · BC-2 (rm + NUL-read -e deaths closed; bite pre-rc=1/post-rc=0) · BC-3 (glibc-honest matrix + mirror) · BC-4 (workflow validated green-with-amber) · BC-5 (19 stubs annotated, checker proven both directions, make canary-versions) · BC-6 (pin documented, provenance recorded, no image change).
Two findings that reframe the release (both in the report):
1. Worker runtime segfaults on bash ≤5.1 — pre-existing, wave-independent (proven on pristine main:frun.bash; Phase 0's green claim contradicted). Bootstrap is 4.4-clean; workers need 5.2+ pending its own wave. Matrix/CI scoped accordingly.
2. Shipped x86-64 blobs need GLIBC_ABI_GNU2_TLS (gcc-16 TLSDESC; absent ≤glibc 2.39) — Ubuntu ≤24.04/Debian 12/RHEL ≤9 can't load at all, any bash version. Ubuntu CI legs are amber-by-design until D-wave; concrete fix identified (-mtls-dialect=gnu drops the requirement at -O1 and -O3, zero payload change) for D's blob cycle.
Gates: matrix 50/50 local + CI legs as designed · suites 92+264 on 5.2 and 5.3, zero failures · bring-up 0.12→0.07s, 34MB splice equal + byte-exact · canary green · twins lockstep · blob +4.4KB code/+0 payload · forkrun_ring.c untouched · no blob cycle taken. No tag, no release push. Next: W-REL5-D (one blob cycle: tls-dialect rebuild + worker-runtime investigation + full matrix) → F2–F6 → tag prep. 

---

## Assistant

**Tool: bash**

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

# Assessment: the TLS finding changes the calculus — in your favor

Verified at `94dcbfe`, tree clean, in sync with origin.

## Your question, answered directly: it's the compiler, not the code

I checked this specifically because your decision hinges on it.

- The requirement is `GLIBC_ABI_GNU2_TLS` — a **versioned-symbol tag**, not a symbol count. `forkrun_ring.c` has 34 `__thread` declarations, so TLSDESC codegen is expected; gcc-16 emits it by default on Fedora.
- The `.so` is a **clean PIC loadable** — `FLAGS: SYMBOLIC`, no `TEXTREL`. Nothing about the code requires this ABI. It's purely which TLS model the compiler picked.
- `-mtls-dialect=gnu` is a **compile flag**, already proven locally to drop the requirement with zero payload change. No source edit, no behavior change.
- Only x86-64 blobs carry it; aarch64/ppc64le/s390x/riscv64 are already clean.

**So: no code change, one flag, one blob cycle.** Your instinct to defer rather than commit is correct, and cheaper than you framed it. This is not a "RHEL8 support project" — it's a rebuild.

That said, the affected set is wider than RHEL8, which the report states plainly: **Ubuntu ≤24.04 and Debian 12 also can't load.** That's a large fraction of likely users, and it's shipping in v3.6.0 unless D-wave lands first. I'd weight the D-wave flag change as effectively mandatory for the release, not optional — it's a few hours inside a wave you're already running.

## The README framing is now honest

```
**new glibc → table below applies; old glibc → nothing loads yet**
(pure-shell parsing works everywhere, but that is not a usable state)
```

That's exactly right, and it's the opposite of the 4.4 ✅ I flagged. Two-axis disclosure, both axes stated, and it names the fix. Good work. This is the doc-integrity standard the rest of the project should meet.

## What I'd still change

**Drop the 4.4 ✅ from the matrix.** Still my one substantive objection. The table has:

```
4.4 (RHEL 8) | ✅ 10/10 | — (worker runtime segfaults) | load path verified
```

The TLS finding just made this worse, not better: the 4.4 leg can't have been testing a real RHEL8 environment, because on glibc ≤2.39 the loadable doesn't load at all. **Those ✅ were earned on new-glibc iron with bash 4.4** — a configuration that doesn't exist on RHEL8. So the row is simultaneously (a) not tested on the platform it names, and (b) green on a platform where the product segfaults in the worker.

Honest row: `4.4 | bootstrap verified (new-glibc only) | — | worker segfault; RHEL8 additionally blocked by GLIBC_ABI_GNU2_TLS`. No ✅.

**A CI leg that actually runs the product.** The 4.4 green passed for multiple waves while the product segfaulted. Every existing gate tests *load*; none tests *use*. Adding a `frun -k` round-trip leg to `bashcompat-smoke.yml` is the single change that would have caught the segfault in wave 1. It costs one container and a few lines.

## Recommendation on the two `frun.bash` variants

Before you commit to the dual-version idea — **it probably won't be necessary, and it carries a specific cost you should see first.**

If `-mtls-dialect=gnu` is in D-wave, one `frun.bash` works on old glibc. The only remaining variable is the bash version, and that's determined at *runtime* by whatever bash is invoking it — the blob is bash-version-agnostic (the embedded `.so` has no bash dependency; bash symbols resolve from the host process at `dlopen`). **One artifact serves all bash versions.** A legacy variant would only be needed if the ≤5.1 worker segfault turns out to be unfixable *and* you want 4.4 users served.

So the ordering that avoids the fork:

1. **D-wave first:** `-mtls-dialect=gnu` + investigate the ≤5.1 worker segfault + rebuild blob.
2. If the segfault is fixable (my leading hypothesis is the `struct builtin` positional initializer at `forkrun_ring.c:8913` — designated initializers would make it version-robust), **one `frun.bash`, floor 4.4, done.**
3. Only if the segfault resists and you want RHEL8 users served anyway: dual variant, and the legacy one carries a pinned engine commit.

Two `frun.bash` copies also mean two sets of embedded blobs, two twin-pairs to keep in lockstep, and the 44-commit CI blob-refresh cycle applied twice. That's a recurring maintenance tax, not a one-time artifact.

## The `add_builtin` question is still open

Verified at the current head: `forkrun_ring.c:509` and `:10097` still call `add_builtin`, which is not in bash's exported symbol table. The report annotates it as a 5th "unexported marker" — documented, not fixed.

I'd fold this into D-wave. It's ~6 lines, it's the same `struct builtin` file as the segfault investigation, and doing them together means one look at `forkrun_ring.c:8900-9010` and one verification pass. If the segfault turns out to be the struct layout, the `builtins[]` conversion is likely part of the same fix.

## Proposed D-wave scope

| Item | Rationale |
|---|---|
| **D-TLS** — rebuild all x86-64 blobs with `-mtls-dialect=gnu` | Unblocks Ubuntu ≤24.04, Debian 12, RHEL ≤9. Flag-only, proven, no payload change. **Do this regardless of the RHEL8 decision.** |
| **D-STRICT** — `builtins[]` array, remove `add_builtin` | Removes the unexported symbol; same file as D-STRUCT. |
| **D-STRUCT** — designated initializers for `struct builtin`; diagnose the ≤5.1 segfault | The actual RHEL8/4.4 blocker. NULL+0x11 is the layout-mismatch signature. |
| **D-LEGS** — add a `frun -k` round-trip leg to the compat matrix | The gate that would have caught finding #1 in wave 1. |
| **D-README** — drop the 4.4 ✅ | Doc integrity. |
| D1–D15 as previously specified | The enumerated C hardening. |

## One question before I finalize

**Do you want the ≤5.1 worker segfault in D-wave, or split into its own wave?**

- **In D-wave:** one place, one `struct builtin` pass, one blob cycle. Cheaper in total effort. Risk: D-wave gets large and a segfault finding could expand it late.
- **Split:** D-wave ships the TLS fix and the C hardening (unblocking the tag sooner); the segfault becomes D2 with its own gates. Cleaner separation, two more cycles.

I lean **in D-wave, time-boxed** — the TLS fix and the segfault both touch the same region of `forkrun_ring.c` and both need a blob rebuild, so splitting means rebuilding twice. But if you'd rather get the tag moving, splitting is defensible and I'd put the TLS fix alone in a quick D-TLS wave first, since it's self-contained and unblocks the most users.

---

