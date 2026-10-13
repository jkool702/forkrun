# Sanitizer evidence — round 11

The round-11 review asked for sanitizers, but with an ordering constraint
that is more interesting than the request itself:

> Please run ASan **before** addressing W-EXP-1, not after. AddressSanitizer
> would likely catch bugs in the new fork driver that will only surface in
> production under heavy load. W-EXP-1's changes risk masking or
> interacting with such bugs. A clean ASan run on the current code is the
> evidence that a later failure is introduced by W-EXP-1 rather than
> pre-existing.

Recording the evidence and — more usefully — what each sanitizer can and
cannot see here.

## ASan + UBSan — targeted, clean

Built `fr_udf_helper` and `fr_udf_fork` with `-fsanitize=address,undefined`
and ran all 59 `test_udf*.py` tests plus the driver.

**Result: no ASan report, no UBSan report, no leak report.**

## TSan — clean, and validated non-vacuously

Built `fr_udf_fork` with `-fsanitize=thread` and ran the driver with three
children.

**Result: zero ThreadSanitizer warnings.**

A clean sanitizer run is only worth as much as proof that the sanitizer
was actually looking, so that was checked rather than assumed: a
deliberate unsynchronised increment from two pthreads was injected into a
throwaway copy of the driver, and TSan reported it immediately —
`WARNING: ThreadSanitizer: data race`, with both racing frames resolved
to the injected function. The instrumentation is live.

### What TSan does NOT cover, and why that matters more

**TSan cannot see the concurrency that actually threatens this driver.**
The driver is *fork*-based: parent and children are separate address
spaces that never touch shared memory after the fork. There is no
intra-process sharing to race on, so a zero-warning TSan run is close to
uninformative about the real risk surface — which is the parent/child
pipe protocol: barrier ordering, short writes, truncated reports, EOF
handling, duplicate records.

TSan instruments threads within one address space. It has no visibility
across `fork`. **A green TSan run here says only that the driver
introduces no intra-process races, which was already structurally
guaranteed by using `fork` rather than threads.**

So the protocol risk is covered by fault injection
(`tools/protocol_faults.py`), not by TSan, and the two are complementary
rather than redundant:

| risk class | covered by |
|---|---|
| intra-process races | TSan — structurally empty here |
| memory errors, UB, leaks in helper/driver | ASan + UBSan |
| protocol framing, ordering, completeness | fault injection |
| measurement validity after a protocol fault | integrity counters |

This is worth stating plainly because "TSan clean" could easily be
mistaken for "the concurrency is verified". It is not.

## Still open

- The **interpreter matrix under sanitizers** is not yet run: the
  targeted builds above use one interpreter (3.14.7). C0.5's cross-minor
  matrix passes unsanitized, but ASan/TSan coverage of 3.10 → 3.15rc2 is
  outstanding, and `safe_path` plus `PyConfig` differences across minors
  are exactly where a sanitizer-only fault would live.
- The **frozen ring** is compiled by these builds but was not rewritten
  to force faults; a coverage build (`-fsanitize-coverage=trace-pc-guard`)
  over the fork driver's own branches is not done.

Until the sanitizer matrix is run, the honest status is: **targeted
sanitizers clean on one interpreter; matrix coverage outstanding.**