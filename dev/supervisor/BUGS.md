# Open bugs

Confirmed, reproducible defects. Each has a reproducer, evidence, and an
explicit statement of what is NOT yet known — because a confident guess
at a cause is worse than an admitted gap when someone is about to go fix
it in concurrency code.

---

## RETRACTED — "B-01: worker killed mid-batch loses the consumed prefix"

**Retracted 2026-10-12, same day it was filed. There was no bug.**

I filed this after adding the recovery output-integrity gate the Stage
1–4 review asked for. The evidence at filing time looked compelling and
was reported to the maintainer as silent data loss:

```
run returns 14 of 20 lines, exits cleanly, no error, no poison record
first delivered record is the 4-byte fragment "LOAD"
identical under both cleanroom settings and both supervision policies
```

It was wrong. The test asserted byte-exactness while running with
`on_error="skip"`, and **skip mode drops the failed batch by contract**.
The output was in fact exactly `input[batch_bytes:]` — a clean,
contiguous remainder with the failed batch removed. Nothing was
corrupted, nothing was torn, and nothing was silently lost.

What the maintainer said at the time is the whole answer:

> on the bash side batches are treated as atomic — there is no "partial
> batch output". the batch is re-run in full, and the partial output
> from the batch is rolled back by fallocate (since the partial output is
> still in the output memfd)

That is the contract `frun.bash` implements, and the engine implements it
correctly. The measured behaviour:

| policy | records | partial output leaked | correct? |
|---|---|---|---|
| `on_error="retry"` | `[128, 128, 124]` | no | yes — batch re-run in full, byte-exact |
| `on_error="skip"` | `[128, 124]` | no | yes — exactly one batch absent, remainder contiguous |

The probe emitted `PARTIALJUNKTHATWASROLLBACK` *before* dying; none of
it survived, in either policy. The rollback works.

### Why it is recorded rather than deleted

The failure was not the engine's, but it was mine, and it was expensive
enough to be worth keeping. Three specific things went wrong:

1. **I asserted a contract without stating it.** The test demanded
   byte-exactness without recording which failure policy was in force,
   so "exactly one batch dropped" read as "six lines vanished".
2. **I treated a plausible-looking number as a diagnosis.** "14 of 20"
   looks like loss. It is exactly what skip means. I then constructed
   three candidate mechanisms in the ring code to explain a behaviour
   that had no unexplained component.
3. **I reported it as high severity before checking the reference
   implementation**, with `frun.bash` sitting in the repository root the
   entire time.

The corrected suite is
`python/tests/test_stage3_recovery_integrity.py`, which asserts the
expected output *per policy* rather than one blanket expectation, and
`dev/supervisor/check_batch_atomicity.py`, which prints the table above.

### The transferable lesson

Structural assertions are necessary and not sufficient — that was the
lesson from round 7, and it was not enough. The additional step here is
**assert the contract, not your assumption about it**: before calling a
result anomalous, find the specification that makes it expected. In this
case the specification was the maintainer's own summary of the bash
implementation, which took one message to state and would have taken one
command to find.
