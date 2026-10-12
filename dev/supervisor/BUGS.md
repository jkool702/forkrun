# Open bugs

Confirmed, reproducible defects. Each has a reproducer, evidence, and an
explicit statement of what is NOT yet known — because a confident guess
at a cause is worse than an admitted gap when someone is about to go
fix it in concurrency code.

Status vocabulary:

| status | meaning |
|---|---|
| `CONFIRMED` | reproduced, cause understood |
| `CONFIRMED / cause open` | reproduced, cause not established |
| `MITIGATED` | worked around, underlying defect remains |

---

## B-01 — worker killed mid-batch loses the consumed prefix of that batch

**Status:** `CONFIRMED / cause open`
**Severity:** high — silent data loss
**Found:** 2026-10-12, while adding the recovery output-integrity gate the
Stage 1–4 review asked for (round 7 follow-up)
**Frozen code:** fix is expected to land in `forkrun_ring.c`, which is frozen

### Symptom

A worker SIGKILLed while holding a batch causes that batch's
**consumed prefix to be discarded**. The batch is reclaimed and
redelivered, but the redelivered batch's input begins partway through,
so only the unconsumed tail is ever processed.

At 20 lines of 21 bytes with 128-byte batches, a run returns **14 of 20
lines** and exits normally — no error, no poison record, no non-zero
status. The first delivered record is the 4-byte fragment `LOAD`, which
is the tail of `LINE000006 PAYLOAD`: the batch's start was lost and only
`end - 4` survived.

```
cleanroom=0 orchestrator=True   14/20 lines  first=b'LOAD'   LOST 7 lines
cleanroom=0 orchestrator=False  14/20 lines  first=b'LOAD'   LOST 7 lines
cleanroom=1 orchestrator=True   14/20 lines  first=b'LOAD'   LOST 7 lines
cleanroom=1 orchestrator=False  14/20 lines  first=b'LOAD'   LOST 7 lines
```

### Scope

**Engine-core, not cleanroom.** Identical loss with `FORKRUN_CLEANROOM=0`
and `=1`, and under `orchestrator=True` and `False`. The cleanroom
discipline is not implicated; this is reachable on the ordinary path.

Recovery itself works — a replacement worker appears, later batches
arrive intact and in order — so the defect is confined to the *input
extent* of the one redelivered batch. This is what makes it dangerous:
the run looks healthy, the counts look plausible, and the loss is silent.

### Reproducer

```
python3 dev/supervisor/repro_B01_worker_death_truncation.py
```

Exits 0 while the bug is present. Once fixed it exits 1 and prints
`NOT REPRODUCED`, at which point the two `@unittest.expectedFailure`
markers in `python/tests/test_stage3_recovery_integrity.py` must be
removed or the suite will report **unexpected success**.

### Cause: not established

What is known about the code path:

* `ring_recover_worker_core` Case 2b ("THE ORPHAN") escrows
  `batch_idx` and a slot **count** (`ep.cnt`), but carries no byte
  extent — it has no way to say which bytes the dead worker had already
  consumed.
* The claimant derives the batch start from
  `local_state->offset_ring[my_read_idx & RING_MASK]`, which *should*
  name the batch start regardless of how far the dead worker read.

Those two facts are in tension with the observed 4-byte delivery, and
the resolution is not yet pinned down. Candidate mechanisms, none
confirmed:

1. `offset_ring[slot]` is overwritten or stale by the time the escrow is
   serviced, so the redelivery reads a later start.
2. The batch's input extent is established somewhere other than
   `offset_ring` on the spawn/exec path, and *that* is what is resumed.
3. Partial-output rollback (`ftruncate` to `txn->output_start`) interacts
   with the reclaim such that the already-consumed prefix is suppressed
   rather than the input being truncated.

**Do not act on this list without instrumentation.** The next step is to
log, for the claimed batch, `offset_ring[slot]`, `end_ring[slot]`,
`txn->offset`, and the bytes actually fed to the command, for both the
original claim and the escrow redelivery. That distinguishes (1) from
(2) directly.

### Why this was not caught

The Stage 3 lifecycle suite proved a replacement worker *appears* after a
death, and that is genuinely useful. It never checked the output. The
review's request for a "recovery output-integrity test" is what surfaced
this — and it is the third time in this project that a test asserting
*observable structure* passed while asserting nothing about *results*
(`map(mode="spawn")` never reaching the launcher; the teardown test
signalling a process with no handler; the ceiling test whose mutation
silently did not apply). Structural assertions are necessary and not
sufficient.
