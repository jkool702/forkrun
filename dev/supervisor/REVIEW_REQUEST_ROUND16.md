# Round 16 — final review: the round-15 corrections

Branch `NEW/REFACTOR4.2`. Review the **branch head**. Round 15 reviewed
the state that carried a false "TIMED OUT" message and a test that could
not detect its own violation.

**1059 tests, 0 unexpected failures, 2 skipped.** Release gate green.
Working tree clean. `forkrun_ring.c` untouched.

Five commits since `84c3a3f2`. `test_udf_version_barrier.py` is 16 tests.

This is intended as the closing round. It is a **delta** — everything you
accepted in round 15 is not restated — and it is written so you can spend
your attention on §3 and §4.

---

## 1. The five items

| your item | fix |
|---|---|
| reversed, still-packed test override | two macros, one per field; no packed value anywhere |
| exported symbol unchanged across an ABI change | renamed `fr_udf_built_version_v2` |
| exit 81 reported a crash as "TIMED OUT" | four distinct outcomes; 81 means timeout |
| version header not a launcher prerequisite | added — and the variable was misordered |
| three tests that did not prove their names | replaced, each with its scope stated |

### 1.1 The override

```c
out->major = FR_UDF_REPORT_MAJOR;
out->minor = FR_UDF_REPORT_MINOR;
```

The prior version took one packed macro and shifted it into both fields
**with major and minor swapped** relative to `PY_VERSION_HEX`, so
`0x030E0000` reported 14.3. It would have passed only because nothing
compared it against a real 3.x.

### 1.2 ABI versioning

A stale v1 helper exporting `unsigned long fr_udf_built_version(void)`
still satisfied a bare-name `dlsym`, and the result was then called
through an incompatible function-pointer type — which on common ABIs
leaves the zero-initialised struct untouched and so **refuses by accident**.
`_v2` turns that into an ordinary "symbol absent" refusal.

### 1.3 Exit 81

`udf_probe_await` returns `OK / TIMEOUT / FAILED / STUCK`. Measured:

| fixture | exit | elapsed | message |
|---|---|---|---|
| hanging constructor | **81** | 5004 ms | `probe TIMED OUT after 5000 ms` |
| **crashing** constructor | **71** | 3 ms | `probe child exited or closed the pipe before reporting` |

Also: kill immediately on a confirmed timeout instead of spending a reap
interval first; and the comment no longer claims the deadline covers the
reap. The total is the deadline **plus at most two reap budgets** — the 5 s
figure is the report deadline alone.

### 1.4 Build prerequisite

`$(CR_OUT)` now depends on `forkrun_udf_version.h`. Worth noting why this
was not a one-liner: `UDF_VER_HDR` was defined **below** the launcher
rule, so referencing it there would have expanded to **empty** — make
reads prerequisites lazily. It is now defined above and used by both rules.

### 1.5 The tests

* **`test_no_interpreter_was_initialised_on_refusal`** grepped stderr for
  `fr_py_init` — a different function than its name claimed, and one that
  succeeds *silently*. Initialising before refusing would have changed no
  observable string. Replaced with a helper whose `fr_udf_init()` writes a
  **marker file**, asserted absent — plus a negative control proving the
  same fixture *does* write it when accepted, so the test can fail.
* **Kill-switch test** now poisons the cache, runs the **public** route
  with stderr captured, and asserts no warning *and* that results are
  still produced.
* **Timeout-cache docstring** claimed it "force[d] a genuine 81 from the
  launcher", which the body never did. Rewritten to state it is a unit
  test of the caching policy.

---

## 2. Where I stopped short, deliberately

**The in-flight fingerprint regression does not prove the threading.**

I wrote it, mutation-tested it, and it **did not fail when the threading
was reverted** — without a mid-flight replacement, the pre- and
post-launch fingerprints are the same value, so it cannot see the
difference.

Rather than ship it as false assurance, its docstring states what it does
and does not prove, and a **second** test pins what can be pinned: that a
real public refusal reaches the cache handler with a fingerprint at all.
That one has teeth — forcing the handler to receive `None` fails 2 tests.

Fully covering the mid-flight case needs a controllably delayed launcher.
**Recorded as open, not faked.**

---

## 3. Questions for the final round

1. **Is the deadline contract now correct as stated?** Report wait is one
   absolute `CLOCK_MONOTONIC` deadline; reap has its own bounded budget;
   a confirmed timeout kills first. Is the *description* now honest?
2. **Does `_v2` fully close the stale-helper ABI edge**, or is there a
   residual case?
3. **Is exit 81's contract now clean** — 80 mismatch, 81 timeout, 82 bad
   declaration, 71 everything else pre-ingest?
4. **Is the residual mid-flight gap acceptable to close W-EXP-1**, given
   the coarse regression *is* pinned?
5. **Is there anything in this diff you would still call a defect rather
   than a proof gap?** If yes, it should be fixed now. If no, I'd like
   W-EXP-1 marked complete and the branch moved to W-EXP-1.5 / W-EXP-2.

## 4. Status vocabulary — not collapsed

* **Implemented and tested:** version barrier, typed + ABI-versioned
  stamp, bounded probe with distinct timeout/failure outcomes, exit
  80/81/82/71 contract, stream classification, explicit in-process
  fallback, per-invocation warning, fingerprint cache with explicit
  lock, release-guard marker check, build prerequisite, sdist contents.
* **Measured:** laziness (0.00 s to return), warning counts, exit codes
  across ten declaration forms, crash→71 / hang→81 with elapsed times,
  cross-minor (real 3.12 helper vs 3.14 caller → 80), ASan+UBSan zero
  findings over all four paths with non-vacuity confirmed.
* **Open:** the mid-flight replacement test (§2).
* **Unverified, and will stay so until the tool exists:** `auditwheel`.
* **Deliberately out of scope:** `LD_LIBRARY_PATH` containment — this is
  a correctness barrier, not a loader-containment mechanism. The
  cross-minor result shows a caller can still influence *which*
  `libpython` of a *matching* minor loads.
* **Not claimed:** memory safety of the helper itself.

## 5. For context

Three things earlier in this feature are worth remembering when reading
the diff, because each was a bug that passed a green suite:

1. The barrier's first "fix" **reproduced the flaw it replaced** — a
   blocking `read()` before the deadline was consulted. Exit 81 was wired
   end to end and could not occur.
2. The source-offset test used **no `pass_fds`** and a different
   descriptor, so the measured offset belonged to a file the launcher
   never read.
3. `stream()` stopped being lazy for one commit: a writer sleeping 3 s
   made `stream()` take 3.00 s to **return**.

The consistent thread is that all three were found by **measuring a
property nobody had measured before**. That is the argument for treating
the remaining §2 gap as a known bound rather than assuming it is benign.