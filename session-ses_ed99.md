# New session - 2026-10-10T15:19:59.848Z

**Session ID:** ses_ed999b797ffe8hj6aGZpBzBYfT
**Created:** 10/10/2026, 11:19:59 AM
**Updated:** 10/16/2026, 3:24:09 AM

---

## Assistant

**Tool: bash**

---

## Assistant

`test_fd_scrub.py` calls `scrub_fds(set())` **in the test process itself**, closing every fd. That invalidates a stable fd. Let me restore fresh-per-run and instrument to find the real suite failure:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

Still empty with a fresh per-run memfd. Let me test whether `test_fd_scrub` is the trigger:

**Tool: bash**

---

## Assistant

Not that either. Let me binary-search the module prefix:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

`test_exactly_once.py` is the culprit. Let me see what it leaves behind:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Root cause found.** `test_exactly_once.py` calls `fr_py_claim()` *in the parent process*, which fires the relay with `FRK_POISON_FD` unset — caching `g_poison_fd = -1` in the parent's thread. Every child forked afterwards inherits that poisoned cache. Let me check the build path before fixing the cache:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

The substrate rebuilds cleanly. Let me verify `fr_py_poison_relay` isn't part of the exported/generated ABI before touching it:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

It's in the generated ABI as a *signature* only — changing the body keeps `gen_shim.py --check` green. Fixing the stale cache:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

Fixed. Full suite:

**Tool: bash**

---

## Assistant

Only the dirty-tree guard. Let me remove the diagnostics and dead helpers:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

Frozen files byte-identical. Phase D — updating the debt register truthfully:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: todowrite**

---

## Assistant

Workstream A committed. Now Phase E — surveying all memory-measurement uses before editing anything:

**Tool: bash**

---

## Assistant

Four test files share the before/after `ru_maxrss` pattern. Note `test_rss.py:12` already documents the correct approach (fresh process per measurement). Let me examine each:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

All four share the identical flaw. Per the work order I'll fix the named target properly and report the others. Let me first measure actual behaviour to pick a defensible bound:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

My earlier `bisect.py` shadows the stdlib. Renaming and rerunning:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

Both modes show ~130MB growth — the premise needs checking. Let me test whether growth scales with output size:

**Tool: bash**

---

## Assistant

Growth scales linearly with amplification (33/65/160MB). Let me check whether it also scales with *input* size:

**Tool: bash**

---

## Assistant

Growth ≈ output size in both dimensions. Let me check the original test's own helper and instrument its actual numbers:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

Now I have the truth: the real delta is **56824 KB against a 61440 KB bound — an 8% margin**. Let me measure streaming vs collect with the exact original fixture:

**Tool: bash**

---

## Assistant

Decisive: **streaming (57MB) grows MORE than collect-all (46MB)**. Let me push amplification higher to see whether these are fixed-window or output-proportional:

**Tool: bash**

---

## Assistant

Growth tracks output size exactly, and stream ≈ collect at every level. Let me check whether any configuration is actually bounded before concluding:

**Tool: bash**

---

## Assistant

All four configurations grow proportionally to output — there is no bounded configuration. This changes Workstream B's outcome, so let me build the correct measurement tool first:

**Tool: write**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

Path bug — `_HERE`'s parent already *is* the package dir:

**Tool: bash**

---

## Assistant

Now with a clean isolated process there IS a real difference (stream 89MB vs collect 181MB at amp=20). Let me characterize the ratio across scales:

**Tool: bash**

---

## Assistant

Consistent and meaningful: **stream retains exactly 0.50× output, collect retains 1.00×**, stable across a 4× range. Let me check the original test's scale and timing:

**Tool: bash**

---

## Assistant

Decisive finding: the original 60MB bound sits *above* collect-all (58.9MB) — so it could never have discriminated streaming from accumulation even with a perfect measurement. Writing the replacement test:

**Tool: bash**

---

## Assistant

Phase G — proving the mutation is detected. `--collect` *is* the accumulate regression:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

G1 detected with a fully diagnosable message. Now the 30-run stability assessment:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

40 focused runs, 0 failures (30 standalone + 10 under concurrent full-suite load — the exact condition that used to trigger the flake). Recording TD-13 and committing:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

A doc-accuracy gate ties the streaming claim to the renamed test — and per TD-13 the claim itself is false. Let me look:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

`STREAMING.md:42` claims "holds parent RSS flat (measured +0MB)" — exactly what TD-13 disproves. Correcting the doc and the claim entry:

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

**Tool: bash**

---

## Assistant

The phrase wraps across a newline. Using a phrase that doesn't:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

Only the dirty-tree guard. Committing Workstream B:

**Tool: bash**

---

## Assistant

**Tool: todowrite**

---

## Assistant

Both workstreams committed. Running the mandated validation matrix in increasing-cost order.

**10.1 — focused poison tests, plain path then reactor path:**

**Tool: bash**

---

## Assistant

**10.2 — cleanroom poison/statistics tests:**

**Tool: bash**

---

## Assistant

**10.3–10.5 — memory test + mutation, direct/discovery parity, integrity guards:**

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

The hygiene guard class is gone — my earlier `git checkout -- python/tests/` (reverting a bad splice edit) wiped it. Let me check what else that cost:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

The 6 `__main__` fixes are safely in `a65aa4ca`; only the *guard test itself* was lost to that checkout. Item 10.5 explicitly requires it, so restoring it as a standalone module:

**Tool: write**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

My injection was in the *correct* order. Injecting after the main block, which is the actual defect:

**Tool: bash**

---

## Assistant

Guard confirmed working, and the consequence reproduced (direct 23 vs discovery 24). Committing it:

**Tool: bash**

---

## Assistant

**10.6–10.8 — full suite under each gate configuration:**

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

`test_spawn_ordered` fails under legacy `=1`. Checking whether that's mine or pre-existing:

**Tool: bash**

---

## Assistant

My change causes it. Let me see the actual failure:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

Release gate is green under default env; that failure was knock-on. Focusing on `test_spawn_ordered`:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

The `.so` is untracked, so my earlier comparison used HEAD's rebuilt substrate. Let me do a clean comparison by rebuilding from each source:

**Tool: bash**

---

## Assistant

Both fail with correctly-matched substrates — **pre-existing, not mine**. (My earlier "OK" reading was taken against a mismatched `.so`.) Now the release gate:

**Tool: bash**

---

## Assistant

Release gate fully green, including the engine-frozen check. Now item 11 — full diff review:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

Frozen files confirmed byte-identical. Recording the pre-existing spawn finding, then final verification:

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: bash**

---

## Assistant

**Tool: todowrite**

---

## Assistant

# WO-PY-REL-1 — morning report

## 1. Starting state
Branch `NEW/REFACTOR4.2` at `a65aa4ca`, working tree clean, in sync with origin.

## 2. TD-09 root cause and the path used

**The register's stated reason for leaving it open was wrong.** TD-09 said closing it "needs a C accessor … that is engine work, not a stats patch." No engine work was needed.

`fr_py_claim()` in `_shim.c` **has been calling `fr_py_poison_relay()` on the plain path all along**, on the same `num_kills == threshold` edge that increments the shared poisoned count. The index was being relayed correctly and **discarded**, because no Python code created the receiving end. Confirmed by forcing a memfd through scrub on an otherwise unmodified tree and reading back `[0..7]`.

Fix, all Python: parent creates the stats memfd and writes the v2 header; exports `$FRK_POISON_FD` across the fork with a `finally`-restore (process-global — a leaked stale fd would make a later run relay into the wrong object); the descriptor is threaded into the four worker keep-sets. Indices are collected **before** `report_poison()` so a `strict_poison` raise does not lose them. Truncation is `relayed < poisoned`, identical to the cleanroom.

**The fix exposed a second defect.** The relay cached its fd in a `__thread` variable. A Python parent can call `fr_py_claim()` itself — `test_exactly_once.py` drives a batch to its retry limit exactly that way — and the first such call with the variable unset cached `-1` **permanently**. Every worker forked afterwards inherited it through `fork()`: correct count, permanently empty index list. TD-09 reproduced by TD-09's own fix. It passed every focused run and failed only in the full suite; found by bisecting the module prefix. `_shim.c` (not frozen) now re-reads `getenv` per poisoned batch — a terminal event, not a hot path.

**No frozen file touched.** Verified twice — `git diff a65aa4ca..HEAD` empty for all three, plus sha256 against the session baseline.

## 3. Mutation evidence

| Mutation | Result |
|---|---|
| plain path reports `[]` again | 8 failures |
| one real poison index dropped | 8 failures |
| truncated list marked complete | 2 failures |
| scalar altered with no poison event | 5 failures |
| relay fd not kept (Python loop) | 8 failures |
| keep removed from **C plugin loop only** | 2 failures |
| keep removed from **spawn loop only** | 1 failure |
| streaming index list emptied | 10 failures |

The three keep-set mutations are why the loops are asserted separately — a one-loop fix passes everything else.

## 4–6. Memory measurement

Isolated subprocess, **current** RSS from `/proc/self/statm`, sampled **inside the consumer loop**, no monitoring thread. Growth as a fraction of output:

| output | streaming | collect-all |
|---|---|---|
| 47 MB | 0.52× | 1.24× |
| 95 MB | 0.50× | 1.21× |
| 190 MB | 0.50× | 1.00× |
| 380 MB | 0.50× | 1.00× |

The old test could not have caught this, for two independent reasons: it measured a peak delta, **and** its 60 MB bound sat *above* the measured collect-all figure (58.9 MB) for the same workload. The corrected measurement shows the ratio is a constant **0.50**, not a constant byte count — retention scales with output. `STREAMING.md`'s "holds parent RSS flat (measured +0MB)" was false and is corrected.

Broken case: making the engine retain everything fails the test with measured numbers in the message.

**40 consecutive focused runs, 0 failures** — 30 standalone plus 10 launched concurrently with a full suite. That is evidence the specific mechanism is gone, **not** proof of immunity to memory pressure generally.

## 7. Validation

Full suite **1190 tests, 0 failures, 2 skips** — gate unset, gate `off`, and `FORKRUN_CLEANROOM=map-plugin` all green. **Release gate: ALL CHECKS PASSED** including *"Engine: frozen files untouched (tree + history)"*. Direct vs discovery parity verified on all six touched test files.

Under `FORKRUN_CLEANROOM=1`, `test_spawn_ordered` fails. **Pre-existing, not mine** — established by rebuilding the substrate from each source revision. My first comparison was wrong because the `.so` is untracked, so checking out an older source still ran the newer build.

## 8. Commits

- **`0d3a48c1`** — Workstream A, TD-09 fixed
- **`93ae1187`** — Workstream B, valid measurement + TD-13
- `aac41e3f`, `01d46d2b` — guard restored, TD-14 recorded

Pushed `a65aa4ca..01d46d2b`.

## 9–10. Frozen files and register

All three byte-identical. Register: **TD-09 FIXED**, TD-09b (streaming scalar) open, TD-12 (u64→u32 index truncation, pre-existing, needs launcher re-release) open, TD-13 open with measurements, TD-14 open.

## Things you should know

**I broke the tree twice and caught both.** A `git checkout -- python/tests/` (taken to undo a bad edit) silently reverted that whole directory, destroying the test-integrity guard. The six `__main__` fixes it protected were already committed and survived — so I lost the guard, not the fixes. Restored as its own module and committed, which is why it exists as `test_test_integrity.py` rather than inside a feature file.

**One assertion I wrote was self-contradictory** — I asserted `poisoned_batches == range(n)` in the truncation test, which cannot hold when truncated. Caught immediately by the test.

**Two claims I could not support.** Phase G required the new memory test to distinguish bounded streaming from accumulation; it cannot, because the implementation does not have that property. And Workstream A's index-width requirement — the relay truncates u64 to u32 — I did **not** widen, because it requires re-releasing the shipped launcher binary. Both are recorded rather than papered over.

**Not investigated:** why the streaming ratio is exactly 0.50. It could be a bounded window that happens to be half this corpus, or a sampling artifact. TD-13 says so explicitly.

---

