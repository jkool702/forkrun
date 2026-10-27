# C0.7 — commit-flush contention measurement (round 19 §6)

Round 19 asked for the cost of the shared per-node `fetch_add` to be
measured rather than assumed, since several workers share one cache line.

## Method

Ordered path, `lines=64`, 200k-line input, 3 trials, best-of reported
(rec/s), at 1/2/4/8 workers. Compared against `158e818a` (immediately
before C0.7) with the substrate rebuilt for each side.

| workers | pre (rec/s) | post (rec/s) | delta  |
|---------|-------------|--------------|--------|
| 1       |  55,765     |  64,822      | +16.2% |
| 2       |  98,312     |  95,449      |  -2.9% |
| 4       | 116,891     | 117,686      |  +0.7% |
| 8       | 111,114     | 121,268      |  +9.1% |

## Conclusion: no measurable penalty, and the measurement cannot resolve one

The deltas are incoherent — two large gains, one small loss, one small
gain — so they are run-to-run variance, not an effect. If the flush cost
anything, the high-worker cases would degrade *consistently*, because
that is where contention on one cache line is worst. At 8 workers, where
the contention should be most visible, the counter build measured 9%
**faster**.

The honest reading is therefore: **the cost is below this measurement's
noise floor**, not "zero". Nothing here shows the flush is free; it shows
that at these scales it is not separable from variance.

Two methodological notes, recorded because they nearly produced a
confident wrong answer:

- A first attempt compared HEAD against a `git stash` of an empty working
  tree. Nothing was stashed — everything was already committed — so both
  sides were the *same build* and the comparison was meaningless.
- A first workload read 200k lines as 49 records, because it omitted the
  `lines=` parameter the correspondence sweep always passes. The
  "benchmark" was measuring setup.

## What would actually resolve it

A tighter loop (many commits, no payload), more trials, and pin-to-core
to remove scheduler noise. Worth doing only if the certificate is ever
enabled by default; on the ordered path a single `fetch_add` per
committed batch is amortised over the whole batch's work.
