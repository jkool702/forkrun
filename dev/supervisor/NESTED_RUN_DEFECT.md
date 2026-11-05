# Pre-existing defect: a nested run corrupts the enclosing run

Found while implementing C0.7's run-scoping. **Not caused by that work**,
and not fixable from it.

## Reproduction

A `map()` performed from inside a payload — or, more damagingly, from
inside a worker while a `stream()` is live:

```python
def payload(b):
    forkrun.map(inner_up, small, workers=1, nodes=1, order="none")
    return b.copy()

for _ in forkrun.stream(payload, big, workers=2, nodes=1):
    ...
```

fails intermittently with:

```
forkrun: Worker 0 recovery failed (orphan revert/escrow). Aborting.
```

Roughly half of trials, with either worker index.

## Evidence it predates C0.7

Reproduced at **`158e818a`** — the commit immediately before the C0.7
counter — with `order="none"`, so neither the certificate nor the
committed-frame counter is involved at all:

```
PRE-C0.7 (158e818a) order=none failures: 3   (of 4 trials)
```

## Why it matters more than the certificate

`_RUN_LOCK` is an `RLock`, so same-thread nesting is deliberately
permitted and there is a test asserting a nested `map()` inside a
`stream()` completes (`test_stream_lock.py`). That test passes with a
*small* stream, where the workers drain quickly. With a larger stream the
outer workers are still mid-flight when the nested run initializes and
tears down the shared engine, and the outer's subsequent batch accounting
is destroyed.

The two shapes differ in timing, not in kind — so the existing test is
green against a real bug.

## Interaction with the certificate

The C0.7 nesting guard is **process-local**. A payload runs in a forked
worker, so a nested run started from a payload increments the *worker's*
depth and runs-started counters, not the parent's. The parent cannot
detect it, and its expected-side delta absorbs the nested run's commits.

That makes the enclosing run's certificate fail with a number that is
real but attributed wrongly. The certificate turns silent corruption into
a loud failure, which is preferable to silence — but it is a symptom
surfaced, not a defect fixed.

## What fixing it likely requires

Not addressed here. Candidate directions, none trivial:

* make the engine per-run rather than per-process, so a nested run
  cannot tear down an enclosing run's state;
* or forbid nesting from inside a worker payload outright, which is a
  smaller change and would make the guarantee honest.

The second is probably the right first move: the supported shape is
nesting from the *main thread* (inside a stream generator), which the
C0.7 guard already handles by refusing to certify.
