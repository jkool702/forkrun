# Supervisor interface — the specification §3 requires

**Status: SPECIFICATION.** Closes the roadmap §3 gate
(`CLEANROOM_EXPANSION_ROADMAP.md:184-201`): *"the shared
launcher-supervision interface is specified and frozen in Phase 0"*,
which blocks **W-EXP-2** and **W-EXP-3**.

Builds on `DECISION-03-supervision-model.md`, which **decided the shape**
(§7.3: shared lifecycle layer, distinct worker-exit policies) and is
status DECIDED. DECISION-03 is not this artefact — it is the decision; the
decision did not write signatures, and the gate asks for an interface.

Everything below was verified against the branch head rather than
inherited from the decision brief. Where the brief and the code disagree,
**the code is recorded as authoritative** and the discrepancy noted.

---

## 1. Why this gate exists

The roadmap's hazard, quoted:

> Either the shared supervision interface is specified and frozen in Phase
> 0, or one branch is designated for integration and rebased before the
> other. Starting either workstream without this recorded is how two
> branches end up rewriting the same supervisor.

W-EXP-2 (NUMA) and W-EXP-3 (spawn-pipe) are separate stages that both
extend worker supervision. If neither owns the supervisor, both edit it.

## 2. What exists today — verified

| property | finding |
|---|---|
| supervision mode flag | `forkrun_cleanroom.c:193` — `o.supervise` (1 recover+respawn, 0 fail-fast) |
| CLI surface | `--supervise recover\|fail-fast` (`:1421-1425`), default recover (`:1377`) |
| recovery capability | `p_recover`, resolved via `dlsym(h, "fr_py_recover_worker")` (`:1653`), 6 references total |
| **structural separation** | **already implemented.** The fail-fast branch (`:2232`) classifies death from the **raw wait status** and never calls `p_recover` |
| test | `test_fail_fast_never_recovers` asserts the property |
| NUMA awareness in the launcher | **NONE** — `grep -c numa forkrun_cleanroom.c` is **0** |
| NUMA today | lives in Python: `fr_py_numa_scanner` / `fr_py_numa_ingest` (`run.py:9472, 9494`) and the ring's `ring_numa_*` |

**DECISION-03 §7.3's central requirement is therefore already met**: the
fail-fast policy does not merely avoid recovery behind a boolean, it never
receives the capability. That is worth recording because the decision
brief described it as a *proposed* structure.

**The gap is the launcher has no NUMA concept at all.** W-EXP-2 does not
extend an existing per-node supervisor; it introduces the first one. That
raises the stakes on this gate rather than lowering them.

## 3. The interface

Split by a criterion that is a property of the operation, not of the
caller: **can this operation ever re-execute user code?**

### Shared lifecycle layer — identical for both policies

```c
/* Classification, from the raw wait status. Never consults a policy. */
enum fr_death_class {
    FR_DEATH_COMPLETED,   /* exited 0 -- completion, not death */
    FR_DEATH_SIGNALED,    /* terminated by a signal */
    FR_DEATH_NONZERO,     /* exited non-zero of its own accord */
    FR_DEATH_UNKNOWN
};
enum fr_death_class fr_classify_death(int wstatus);

/* Child bookkeeping. */
int  fr_mark_slot_dead(int wid, int incarnation);   /* stops the slot being live */
int  fr_kill_worker_group(int wid);                 /* command descendants die with the generation */

/* Teardown. Identical for both policies -- the *decision* to abort differs,
 * the bounded killing and reaping does not. */
void fr_teardown(int abort_pipeline);
```

### Policy layer — distinct, and the capability does not cross

```c
typedef struct {
    /* Recovering policy only. The fail-fast policy is constructed WITHOUT
     * this member, so it cannot call recovery even by mistake. */
    int (*recover)(int wid, int incarnation, int output_fd, int reason);
    int  (*respawn)(int wid, int incarnation);
    void (*on_death)(int wid, enum fr_death_class, void *user);
} fr_recovering_policy;

typedef struct {
    /* No recover member exists. */
    void (*on_death)(int wid, enum fr_death_class, void *user);
} fr_fail_fast_policy;
```

The asymmetry is deliberate and is the whole point: the recovering policy
*has* a recovery capability, and the fail-fast policy has **no field to
assign one to**. A future edit cannot silently reintroduce recovery under
fail-fast by passing an argument, because there is nowhere to put it.

This is what already exists in `forkrun_cleanroom.c:2232` as a control
flow. This spec promotes it from "an if statement in one branch" to "the
type does not permit it".

## 4. What W-EXP-2 and W-EXP-3 must conform to

**W-EXP-2 (NUMA).** Requires per-worker death pipes to the launcher
(roadmap §3). The interface obligation: death arrival becomes a **source**
for the shared lifecycle layer, alongside `waitpid`. Classification is
unchanged and policy-independent. NUMA adds **where the worker was**, not
what death means.

**W-EXP-3 (spawn-pipe).** Requires `poll()` over the spawn pipe *plus*
per-worker death pipes (roadmap §7). Same obligation: a new readiness
source feeding the same `fr_classify_death`.

**Neither may add a policy branch to the shared layer.** If W-EXP-2 needs
"recover only on node 0", that is a predicate inside the recovering
policy's `on_death`, not a new conditional in teardown.

## 5. Integration strategy

**One branch owns the supervisor: this one** (`NEW/REFACTOR4.2`).
W-EXP-2 and W-EXP-3 land here in that order and rebase onto it. Neither
opens a parallel supervisor branch.

Rationale: the launcher has no NUMA concept today (§2), so W-EXP-2 is not
a refactor of shared code — it is the first extension of it. Running it
concurrently with W-EXP-3 would put two authors in the same control flow
with no interface to constrain them, which is the exact hazard §3 names.

## 6. Deliberately not specified here

* **Dead-letter / in-flight batch reclaim on fail-fast.** DECISION-03 §7.4b
  decided no recovery and immediate abort; the batch is *abandoned*, not
  reclaimed. Specifying reclaim would reopen a decided question.
* **`respawn_cap` vs `FORKRUN_RETRY_LIMIT` interaction.** DECISION-03
  §7.4 established they are different knobs. Their joint exhaustion
  policy is a W-EXP-2 concern (multi-node respawn), not a gate.
* **NUMA topology discovery.** Belongs to W-EXP-2's own design.
* **Anything in `forkrun_ring.c`.** Frozen, and this spec does not reach it.

## 6a. Post-review note

Round 16's review accepted the version barrier with one residual noted:
on Linux `dlsym(handle, ...)` searches the opened object **and its
automatically loaded dependencies**. That is now closed for the stamp —
`sym_owned_by()` attributes the resolved symbol with `dladdr()` and
refuses if it did not come from the helper file itself. Verified with a
fixture whose helper exports no stamp but pulls in a dependency that
does: the launcher reports

```
fr_udf_built_version_v2 resolves into libstampdep.so, not into the
helper libnohelper.so; refusing to call through a foreign definition
```

and refuses with 80.

This is a robustness measure, not a fix for a demonstrated defect. The
other six `fr_udf_*` symbols are still resolved by cast without the
ownership check; their signatures have not changed, so a helper built
from the same tree is unaffected, and the launcher only ever dlopens a
path the caller supplied. Recorded rather than presented as more than it
is.

## 7. What this does not establish

* **Not implemented.** No signature above has been written; the code has
  the *behaviour* (§2), not these types.
* **Not reviewed.** No external round has looked at this specification. It
  is written to close a recorded gate, not to claim consensus.
* **The shared-layer functions are named from the current code's behaviour,
  not extracted from it.** `fr_classify_death` does not exist as a
  function; the classification is inline at `forkrun_cleanroom.c:2242`.
  Implementing this means *extracting* existing behaviour, which can
  change it — and that extraction needs its own evidence, not this
  document's.
* **DECISION-03 §7.2's prerequisite is a separate obligation.** The
  "no fallback after user code may have run" rule is recorded there and is
  a prerequisite for widening eligibility; this document does not satisfy
  or supersede it.