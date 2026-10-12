# Review request — Stages 1–4 and the round-6 fixes

Branch `NEW/REFACTOR4.2`, head **`b9a7c651`**. Frozen ring files
(`forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c`) untouched
across `c72d27c6..HEAD`.

**942 tests, 0 failures, 0 expected failures.**
`python/release_check.py` → `ALL CHECKS PASSED` on a clean tree.

---

## 1. Commits, in review order

| # | SHA | what | blocking? |
|---|---|---|---|
| 1 | **`472645f1`** | group-kill ordering bug; Stage 1 wired into production | **yes** |
| 2 | `3a45f886` | Stage 3 complete — spawn envelope activated | — |
| 3 | `b9a7c651` | Stage 4 splice measurement + go/no-go | judgement call, §5 |

Prior rounds already reviewed: `0edd7475` (round 5), `3eff9218`,
`1b95f6a8`, `4228b6b7` (Stage 1 scaffolding — superseded by #1).

```
make -f Makefile.substrate python-substrate
cd python/tests
python3 -m unittest test_stage3_lifecycle test_stage3_spawn_launcher
python3 -m unittest test_stage1_reassembly test_capability_matrix
python3 -m unittest discover -s . -p "test_*.py"     # ~260-560s
python3 ../release_check.py
```

---

## 2. Round 6, finding 1 — you were right, I was wrong again

**Process-group cleanup was a silent no-op.** The supervision loop set
`pids[wid] = -1` the moment it reaped the worker, *before* calling
`kill_worker_group(&pids[wid])`. The helper took the slot **pointer** and
refused to act on a non-positive value, so both the fail-fast and
recovery branches signalled nothing.

Fixed by taking the pid **by value**, which makes the ordering impossible
rather than merely unlikely. `test_stage3_spawn_launcher.py` now asserts
that no call site passes a slot pointer.

Your correction to my diagnosis was the substantive part. I had written
"the launcher never notices the worker's death" and was about to redesign
supervision. `waitpid(-1, &st, 0)` observes the death fine — the *signal*
was broken. The lifecycle test then passed as an **unexpected success**
of its `expectedFailure` marker, which is what that marker was for.

I have kept the wrong-conclusion narrative in the design note, since it
is the most plausible mistake in the set and I would rather it be on
record than rediscovered.

---

## 3. Round 6, finding 2 — Stage 1 was scaffolding

You were right that neither `add_disposition`,
`_split_records_terminal` nor `unresolved_gaps` had a production caller,
so control records were still discarded before the buffer saw them and a
later DATA batch stayed blocked behind that hole until `final_drain()`.
**All seven ordered drain sites** now use
`_drain_worker_memfd_terminal()` + `add_disposition()`. The DATA-only
helpers remain for callers that must not see control records.

### `unresolved_gaps()` stays diagnostic-only — and your finding 6 is why

Ordinary python-mode payloads pass `data=NULL` to `fr_py_emit()`, which
writes **no record at all** for a `None` result. A `None` batch is
therefore a genuine hole, not a marker a consumer can skip, and enforcing
the gap check unconditionally would report **false completeness
failures**. Turning it into an invariant needs a per-producer capability
flag, which is follow-up work rather than something to smuggle in here.

The `_worker.py` comment that claimed the C emitter supplies a
`NO_RESULT` record for that case was my error; it does not, and the
comment is corrected.

---

## 4. Round 6, findings 3–6 — test quality

* **`test_spawn_through_the_launcher_produces_records`** passed
  `--result -1` (its own comment called that invalid) and asserted only
  `returncode != 64`. Now uses a real descriptor, requires exit 0, and
  checks every batch payload.
* **`test_undeliverable_synthetic_wakeup`** used `BEFORE_ACK`, killing
  with *uncommitted* output that recovery rolls back — exercising the
  error branch without ever establishing the committed-but-unnotified
  case its name claimed. Now uses `BEFORE_NOTIFY` plus the drain break.

Two new Stage 3 tests were wrong on first pass, both because I asserted
the wrong thing rather than because the code was:

* the infrastructure-vs-command test passed `--result -2`, another
  placeholder. The drain died instantly with "drain child died" and the
  test reported that as an escalation. With a real descriptor the run
  correctly completes `rc=0` with `SKIPPED` records — and my assertion of
  a **nonzero** exit was independently wrong, since skip semantics mean
  the run succeeds with those batches skipped.
* the teardown test hardcoded a batch count that had drifted from the
  fixture; it now derives from the input.

---

## 5. Stage 3 — envelope activated (`3a45f886`)

Six gates, all in `test_stage3_lifecycle.py`:

| gate | result |
|---|---|
| killed worker's command descendants die with its process group | PASS |
| a descendant that `setsid()`s away **survives** (the Option A boundary) | PASS |
| supervisor observes a death and **respawns** — a different pid appears | PASS |
| teardown kills the command descendant | PASS |
| positive output: real descriptor, exit 0, every payload checked | PASS |
| command failure → `on_error` + explicit `SKIPPED`, no infrastructure abort | PASS |

`_cleanroom_eligible` now admits `mode="spawn"`, naming the gates and
their test in the comment so the decision and its evidence move together.

The respawn gate is the one you asked to see separated from cleanup —
asserting a *different* worker pid in the same launcher, independent of
descendant survival.

---

## 6. Stage 4 — splice measurement (`b9a7c651`) — judgement call

`tools/bench_splice.py`. Median of 5 trials, peak parent RSS
(`ru_maxrss`) measured **per process**, because the high-water mark never
decreases and a shared process reports the largest run's peak for every
later variant. Only representable byte-moving paths are compared: the C
splice loop and `spawn cat`/`tr` through the launcher.

| input | workers | splice | spawn cat | ratio |
|---|---|---|---|---|
| 2.6 MB | 1 | 0.0170s | 0.0807s | 4.9x |
| 2.6 MB | 4 | 0.0130s | 0.0337s | 2.6x |
| 26.5 MB | 1 | 0.0481s | 0.5622s | 11.7x |
| 26.5 MB | 4 | 0.0330s | 0.1753s | 5.3x |

Peak parent RSS is flat across all variants (~50–70 MB on the 26.5 MB
run): a throughput win, not a memory one.

**Recommendation: keep the C splice loop; do NOT wire it into the
launcher.**

Two things I am deliberately not overselling:

* **The margin is widest where it matters least.** 11.7x on the biggest
  single-worker case — but that case is only 0.56s for a plain byte copy,
  so the user-visible saving is ~0.5s. Against a command doing real work
  the margin is unknown.
* **The comparison does not cover what the design asked for.** It
  compares in-process splice against *launcher-spawn*. It does not
  compare against a launcher-splice integration, which does not exist.
  The reasoning for not building it: the win comes from bypassing the
  per-batch payload invocation, which splice already does in-process, so
  crossing the launcher boundary to capture a path already 2.6–11.7x ahead
  is not justified. **If you think that reasoning is wrong, this is the
  item to push on** — it is a judgement, not a measurement.

`spawn tr` measures ~1.00x of `cat` at every size: the transform is free
next to the copy, so the dominant cost is crossing the boundary at all.
That is the cost splice removes, and it explains the ratio.

**A benchmarking mistake worth your scrutiny.** The first run passed
only `tr` to the spawn path, omitting `a-z A-Z`. Spawn transports
arguments as distinct argv elements, so it faithfully ran a *different,
failing* command — and the harness printed timings for failed runs
alongside poison summaries. Every row now asserts the delivered record
count, but the class of error is worth naming: a measurement harness that
reports numbers for runs which produced nothing.

---

## 7. Two changes that moved a threshold — please check the reasoning

**Capability matrix served-fraction bound: 1% → 5%** (`472645f1`).
Serving spawn took the fraction from 0.95% to 1.43%. The bound's stated
purpose is catching an axis that *stopped constraining* the matrix; three
served modes out of a nine-axis cross-product is not that, and a genuine
loss would exceed 5% by a wide margin. Recorded with that reasoning so it
reads as a judgement rather than a threshold nudged to pass.

**Oracle `DECLINE_MODE` now admits spawn.** Deliberate — the predicate
serves it, and the two must resolve identically or the agreement tests
are meaningless. The rule's justification now names the six gates.

---

## 8. Coverage caveats still standing

Unchanged from the previous round and still true:

1. **`test_stage0_spawn_frontier.py` does not observe the frontier.**
   `worker_output_end` is worker-local TLS with no accessor, and I
   verified by reverting the fix that these tests still pass. The
   guarantee rests on the advance being *centralised in the framer* plus
   the launcher-backed suites that do observe rollback.
2. **The unordered Python-fallback E2E test is gated and skipped.** A
   direct python-mode `map()` invocation poisons every batch in this
   environment for reasons unrelated to the frontier — it reproduces
   identically with the fix reverted. What is asserted unconditionally is
   the defect itself: the advance derives from `_HDR.size`.
3. **`FORKRUN_TEST_NOTIFY_FAIL_ONCE` returns before attempting the
   write.** The real-`EBADF` test closes the worker's own signal fd, so
   the syscall path is covered; `out_fd < 0` and `lseek` failure are not
   driven through a live launcher.

## 9. What I would most like challenged

1. **The Stage 4 recommendation (§6)** — keep-don't-wire rests on an
   argument about where the win comes from, not on a measurement of the
   thing being decided.
2. **The 5% matrix bound (§7)** — the reasoning is that the bound guards
   against a lost axis rather than against magnitude. Push back if that
   is the wrong reading of its purpose.
3. **Whether the lifecycle gates are sufficient for spawn activation**
   (§5). They cover death, respawn, teardown, the escape boundary and
   command-vs-infrastructure failure. They do **not** cover
   exactly-once under spawn in the launcher, or parity against the
   in-process spawn loop — both of which the design listed.

## 10. Not done

* **Stage 5** (`auto`/`off`/`required`) — untouched; `Auto` remains off.
* **Stage 2** (bounded/live ordered streaming) — untouched; the decline
  stands and its design note is unopened.
* Items **3** (`mode="python"` parity), **6** (NUMA), **7** (resume) —
  deferred future work orders, not cancelled.

## 11. Documents

* `dev/supervisor/CLEANROOM_EXPANSION_PROPOSAL.md` — roadmap, §0a defect
* `dev/supervisor/STAGE0_PUBLICATION_PROTOCOL.md` — §8a Stage 1, §8b
  Stage 3, §8c Stage 4, §9 as-built, §9.3a why fail-closed is safe
* `dev/supervisor/CLEANROOM_CAPABILITY_MATRIX.md` — 20,160 cells,
  288 served
