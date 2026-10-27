# Round 13 — review request: the implemented minor-mismatch barrier

Branch `NEW/REFACTOR4.2`. Review the **branch head**. The review round
that approved the design is `REVIEW_REQUEST_ROUND12.md` (R2 + your
conditions). This request reviews **what was built**, not what was
planned.

**1049 tests, 0 unexpected failures, 2 skipped.** Release gate green.
Frozen ring untouched.

This is a narrow request on a narrow diff: one C launcher, one C helper,
one Python module, and their tests. But it changes a *contract* — direct
launcher invocations now require `--caller-version` — and it touched four
existing test files as a consequence.

---

## 1. What to review first

The highest-value check is not "is the code correct", it is **"are these
the right things to have changed"**. Specifically:

* Did closing the source descriptor and stdin in the probe child
  (**before `dlopen`**) have consequences I did not anticipate? This was
  your condition 2B and I implemented it literally. In particular: is
  there any UDF path where the launcher legitimately needs stdin after
  the probe?
* Is making the **stream path fall back for `64/69/71/78`** — not just
  `80/81` — actually right? You approved the broader set, but it is the
  largest behavioural change in the diff and it affects failures that
  have nothing to do with versions.
* Is the **negative cache** safe? It is process-global mutable state.

## 2. Two regressions I introduced and then caught

Both passed the existing suite first. Both are now fixed, but I am
leading with them because they are the clearest evidence of what this
review should be sceptical about.

**stream() stopped being lazy.** My first implementation primed the
cleanroom generator with `next()` so a pre-ingest refusal would surface
at the decision point. That made `stream()` block until the first record
arrived. Measured: a writer sleeping 3s before its first record made
`stream()` take **3.00s to return**. A live-draining call became a
blocking one. Now handled inside the generator body; re-measured at
0.00s to return.

**The warning went silent after the first call.** Once an artifact is
cached as incompatible, `helper_path()` returns `None`, so the fallback
never probes — and the warning helper asked `helper_path()` "which
artifact did we reject?", which now always answers "none". Added
`candidate_helper_path()`, which ignores the cache. Verified: two
affected calls, two warnings.

**Question:** is there a third one of this shape that I have not
measured? Specifically, I found both by *measuring behaviour I had not
previously measured*. What observable properties of this feature have I
assumed rather than checked?

## 3. Bugs I introduced during implementation

Four, all caught before commit, all recorded in the commit messages:

* **Packed the version fields differently on the two sides** — caller as
  `major<<16|minor`, helper as `(hex>>16)&0xffff` which is
  `major<<8|minor`. A *matching* 3.14/3.14 pair compared unequal and
  refused every correct call.
* Appended a **list as a single argv element**, so `execv` received a list
  and every UDF call died with exit 127.
* Passed `payload` both positionally and in `kwargs` — duplicate
  argument.
* The launcher accepted only `--caller-version=X` while every other
  option in that CLI is space-separated; three test files use the
  space-separated form and all failed.

**Question:** the first one is the worrying one — a comparison that is
wrong in a way that fails *safe* (refuse everything) rather than open.
What is the cheapest way to make this class of mistake impossible rather
than merely caught?

## 4. Contract changes requiring your attention

**Direct launcher invocations now REQUIRE `--caller-version`** for UDF
mode; absent, malformed, empty or dotless all refuse with 80. Three test
files were updated to declare it. **Is requiring this the right call?**
The alternative is defaulting to "unverified, proceed", which is exactly
the fail-open you told me to avoid — but it does mean an operator
scripting the launcher directly now has a new mandatory argument.

**`v1_available()["udf"]` semantics changed.** It now returns `False` for
an artifact conclusively known incompatible, and otherwise means only
*"a candidate helper is present"* — not that the launcher validated it.
I did not update its docstring to say that. **Should I?**

## 5. What is NOT covered — please judge these

1. **Exit 81 (bounded probe timeout) is completely untested.** The
   bounded probe is implemented and wired, but I have no
   hanging-constructor fixture, so the timeout path has never run. This
   is the largest gap in what shipped. Building such a fixture means a
   helper whose ELF constructor blocks — is that reasonable to ask for in
   this tree, or should the timeout be verified differently?
2. **The direct-launcher positive control is scoped to the barrier**
   ("a matching declaration is not refused"), not to record production.
   Driving the launcher by hand gave 0 records in isolation and I chose
   not to chase it, since `test_cleanroom.py`'s 76 green tests cover
   record production. I would rather say which is which than let the test
   imply more than it proves.
3. **The cache is process-global and mutated without a lock.** This
   codebase takes concurrency seriously elsewhere — `_RUN_LOCK` around
   every executor, and `last_run_stats()` documenting that
   `return_stats=True` is needed for per-call exactness under threads.
   `_INCOMPATIBLE` has neither. Concurrent first-calls can race on the
   dict. Is that acceptable, given the cache may only ever *disable* the
   accelerator and never authorise a load?
4. **`LD_LIBRARY_PATH` influence is untouched**, per DECISION-04 §4. The
   barrier establishes that the helper matches the *declared* minor. It
   does not pin which `libpython` of that minor loads.
5. **`auditwheel` is still unverified**, so nothing is claimed about
   wheel-time `RPATH`/`RUNPATH` behaviour.
6. **Not re-run under sanitizers.** The matrix was green before this
   change; ASan/UBSan/TSan have not been re-run over the new C code.

## 6. Specific questions

1. **Probe-child fd closing** — any path where the launcher needs stdin
   or the source descriptor after the probe returns?
2. **Stream fallback for `64/69/71/78`** — sound, or does it convert
   failures that should propagate into silent in-process runs?
3. **Making the version comparison safe by construction.** Both sides
   could carry the version in one shared header, or the launcher could
   compare against a value the helper *also* derives from the same macro
   — is there a formulation where a packing mismatch is impossible?
4. **The cache's lock.** Fix, or document as best-effort with a
   benign-race argument?
5. **Anything above that I should have checked and did not.**

## 7. Status vocabulary

Deliberately not collapsed into one word:

- **Implemented and tested**: version barrier, bounded probe, exit 80/81
  contract, stream classification, explicit in-process fallback,
  per-invocation warning, fingerprint cache, release-guard marker check.
- **Implemented, untested**: exit 81 timeout path.
- **Measured**: laziness (0.00s / 3.00s), warning count (2 calls → 2
  warnings), mismatch refusal (exit 80), declaration failures (4 forms →
  80), matching declaration (not refused).
- **Unverified**: `auditwheel`; sanitizers over the new code; the real
  3.12-helper-vs-3.14-caller matrix case (only the synthetic override has
  been exercised).
- **Explicitly not claimed**: memory safety. This is a correctness
  barrier.