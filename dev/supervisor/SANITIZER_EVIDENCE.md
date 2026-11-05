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

## ASan + UBSan — interpreter matrix, clean

`tools/matrix_c05.sh --asan` builds each minor with
`-fsanitize=address,undefined -fno-omit-frame-pointer -g` and runs all
three probes against it.

Two allocator settings make that meaningful for an **embedded** CPython,
and neither is obvious:

- `PYTHONMALLOC=malloc` routes CPython's object allocations through the
  system allocator so ASan can see them. Without it CPython uses its own
  pymalloc arenas and an overflow inside an object is invisible — the
  most common reason people report "ASan is clean on Python".
- `detect_leaks=0`, because an interpreter initialised and torn down in a
  short-lived process reports CPython's own module-cache allocations as
  leaks. Leaving it on produces noise that trains reviewers to ignore
  the output. UBSan is the instrument carrying real signal here, and runs
  with `halt_on_error=1` and a stack trace.

  This is not hypothetical: with leak detection on, the memory
  measurement driver reports `SUMMARY: AddressSanitizer: 268435456
  byte(s) leaked in 1 allocation(s)` — the deliberate 256 MB parent
  inflation buffer. A reviewer meeting that on the first sanitized run
  would reasonably conclude the driver leaks its whole workload, and be
  wrong.

**Result: zero sanitizer hits on all three probes, on all six
interpreters.**

| interpreter | verdict | control | respawn |
|---|---|---|---|
| 3.10.22 | 3.59x faster | DIRTY (non-vacuous) | CLEAN |
| 3.11.17 | 2.76x faster | DIRTY (non-vacuous) | CLEAN |
| 3.12.15 | 4.53x faster | DIRTY (non-vacuous) | CLEAN |
| 3.13.16 | 3.85x faster | DIRTY (non-vacuous) | CLEAN |
| 3.15.0rc2 | 4.24x faster | DIRTY (non-vacuous) | CLEAN |
| 3.14.7 (system) | 5.53x faster | DIRTY (non-vacuous) | CLEAN |

This is the coverage that mattered: `safe_path` exists only on 3.11+, and
`PyConfig` field layout and initialisation changed across these minors, so
a fault that appears on exactly one interpreter would be invisible to a
single-version run.

The lifecycle *timing* sweep is deliberately skipped under sanitizers
(3 trials × 2 arms × 6 minors does not fit a gate); timing under ASan is
meaningless anyway, since instrumentation changes what is being timed.

### Non-vacuity of the sanitizer build

A matrix that finds nothing is only evidence if the build detects
something when there is something to find. An out-of-bounds write was
injected into a throwaway copy of the driver and the sanitized build
caught it immediately:

```
==3464739==ERROR: AddressSanitizer: stack-buffer-overflow
```

so the instrument is live and the matrix above is a real result rather
than a build that silently compiled the flags away.

## Round 14 — re-run over the W-EXP-1 version-barrier code

The version barrier added new C to the launcher and the helper after the
matrix above was green. Re-run over the new code.

**ASan + UBSan** (`-fsanitize=address,undefined`, `PYTHONMALLOC=malloc`,
`detect_leaks=0`) — zero findings across all four paths:

| path | exit | sanitizer findings |
|---|---|---|
| matching declaration | 0 | 0 |
| genuine mismatch | 80 | 0 |
| invalid declaration | 82 | 0 |
| **hung ELF constructor** (the new poll-deadline + reap path) | 81 | 0 |

**Non-vacuity checked.** An injected heap overflow in `setup_udf_helper`
was caught immediately (`ERROR: AddressSanitizer: heap-buffer-overflow`,
exit 1), so the clean result above is a real result and not a build that
dropped the flags.

An earlier attempt at this check was itself vacuous — the injected line
never landed (the anchor had been edited away), so the "mutant" was an
unmutated launcher that of course reported nothing. Worth recording,
because a non-vacuity check that cannot fail is the same failure mode as
the tests round 13 and 14 kept finding.

**TSan** — zero warnings. As set out above, this remains close to
uninformative: the launcher is *fork*-based and the processes never share
memory, so there is no intra-process race to find.

## Cross-minor: a real 3.12 helper, driven by the 3.14 launcher

The synthetic version override validates the comparison logic. This
validates the actual loader behaviour the whole feature exists for.

Built a genuine helper against the cached 3.12 headers
(`DT_NEEDED: libpython3.12`):

| declared | `LD_LIBRARY_PATH` has libpython3.12? | exit | what happened |
|---|---|---|---|
| **3.14** (truthful) | yes | **80** | `was built against CPython 3.12` |
| 3.12 (matches the helper) | yes | 71 | **helper LOADED**, then the embedded 3.12 interpreter failed on path configuration |
| 3.14 | no | 71 | probe failed to load |

Row 1 is the §5.5 requirement met on a real cross-minor artifact rather
than a synthetic one.

**Row 2 is the one that justifies the feature.** The launcher dlopened a
3.12 helper successfully, because the loader satisfied `libpython3.12`
from `LD_LIBRARY_PATH`. **The loader did not consider it a mismatch** —
so without the explicit comparison, a 3.14 process would have gone on to
initialise a 3.12 interpreter and run the UDF under it. The barrier is
what turns that silent divergence into a refusal.

Row 3 is why the common case looked safe before: without the other
minor's library on the path, `dlopen` fails on its own. Which is exactly
the reasoning that made the original §5.5 criterion look unnecessary.

## Still open

- The **frozen ring** is compiled by these builds but was not rewritten
  to force faults; a coverage build (`-fsanitize-coverage=trace-pc-guard`)
  over the fork driver's own branches is not done.
- **Leak detection is off by design**, so a genuine leak in the driver is
  not covered here. It would need a suppression file for CPython's own
  allocations to produce usable output.
- TSan remains a single-interpreter result, and as set out above it does
  not cover the fork/pipe protocol in any case.