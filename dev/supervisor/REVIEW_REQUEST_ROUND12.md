# Round 12 (R2) — amendments incorporated; ready to implement on confirmation

Branch `NEW/REFACTOR4.2`. Pinned at `2a5f4068` for the quoted source.
**Still not implemented.** R2 is a delta on R1 — the parts of R1 you
already accepted are not restated.

I re-verified both checkable claims before accepting. **Both hold.**

* `_execute_cleanroom_stream()` raises `RuntimeError` on *any* nonzero
  launcher exit (`run.py:1888`). Verified.
* The UDF probe has a blocking `read()` and untimed `waitpid()`
  (`forkrun_cleanroom.c:638-655`); the plugin probe is bounded by a
  deadline loop, `SIGKILL`, then a 200 × 1 ms `WNOHANG` reap
  (`:1265-1291`). Verified.

---

## 1. Caller-version wire contract (your blocker 1)

Agreed that `PY_VERSION_HEX` is the wrong thing to compare wholesale, and
that the launcher cannot infer the caller after `exec`.

**Contract:**

* New required launcher argument: `--caller-version=MAJOR.MINOR`, e.g.
  `--caller-version=3.14`. Parsed strictly; **malformed or missing is a
  refusal before ingestion** (exit `80`), not a default.
* Helper exports `fr_udf_built_version()` returning its compiled
  `PY_VERSION_HEX`; the launcher extracts major and minor from it.
* Compare the **major/minor pair exactly**. Micro and release-level bits
  are deliberately ignored — a 3.14.7 helper is correct for a 3.14.2
  caller.
* **A helper lacking `fr_udf_built_version()` MUST be refused** with a
  distinct "version cannot be verified" diagnostic, never assumed
  compatible. Fail closed. This is the important half of your point, and
  it is what makes the check trustworthy rather than advisory.

## 2. Fallback across both routes (your blocker 2)

Verified and accepted. The distinction you draw is principled and I want to
state it as a rule rather than a special case, because it generalises:

> A **pre-ingestion** refusal may fall back to in-process. Any failure at
> or after ingestion must raise.

The streaming path currently has no notion of pre-ingestion: it treats
every nonzero exit as fatal, which is correct for everything in
`_CR_EXIT_*` that is *not* pre-ingest — the code comment at `run.py:1871`
explains exactly that (a nonzero exit may follow already-streamed records,
so EOF ≠ success).

**So the fix is to have the stream path consult the same exit
classification the map path already uses**, rather than adding a
mismatch special-case. `80` and `81` join `_CR_EXIT_PRE_INGEST`; the
stream path honours that set and raises otherwise.

**Flagging the scope honestly:** this is a superset of "add stream support
for the mismatch". It also makes `64`, `69`, `71` and `78` fall back in
the stream path, which they currently do not. I believe that is correct
and is the same bug the map path fixed in W-CR1, but it is **broader than
you asked for** — narrow it to `80`/`81` only if you would rather keep
this work order tight.

Also adopted: the refusal **reason must survive** to the dispatcher as a
typed internal result (or specific exception), not collapse into `None`.
And the capability report must not be relied on to infer what happened.

## 3. Probe timeout in this work order (your blocker 3)

Accepted, and adopted your exit-code reasoning: a UDF probe timeout is
**not** `79`. `79` means the C plugin probe failed such that loading the
plugin in the *caller* is unsafe; the UDF fallback never loads the helper
into the caller, so it is a safe pre-ingestion refusal.

* Reuse the plugin pattern wholesale: bounded read deadline, `SIGKILL` on
  expiry, bounded `WNOHANG` reap. The deadline **covers read + reap**, as
  you require — bounding only one still leaves a hang.
* New code **`81`**, in `_CR_EXIT_PRE_INGEST`, not in
  `_CR_EXIT_NO_FALLBACK`, accurately labelled.
* `80` stays reserved for version-validation refusal.
* Test with a deliberately hanging constructor: launcher attempt terminates
  within the bound, **source remains unconsumed**, child reaped, public
  call still completes in-process.

## 4. Sidecar dropped (your blocker 4)

Agreed, and your framing is the better one — a sidecar that avoids
launching the helper *is* making a routing decision, and "not refusing" was
my way of avoiding that word. **Removed from W-EXP-1.**

Replaced by a narrower mechanism:

* On a confirmed refusal, record it keyed to the **helper's file identity
  and the caller's major/minor**, so the same incompatible artifact is
  not re-probed on every call.
* **Invalidate when the artifact changes.** Identity key =
  `(st_dev, st_ino, st_size, st_mtime_ns)` from a single `fstat`. A digest
  would be stronger but costs reading the file; `stat` is sufficient to
  catch replacement, which is the realistic case.
* **`v1_available()["udf"]` semantics, as you propose:** `False` for an
  artifact conclusively known incompatible; `True` means **"a candidate
  helper is present"**, not "the launcher validated it". I will correct
  that docstring, because today it reads as a stronger claim than it is.

This also answers question 3 without a permanent flip.

## 5. Warning policy (your blocker 5)

Accepted in full: **one warning per affected invocation** whenever a
mismatch is discovered, stating the mismatch and the in-process fallback.

* With `FORKRUN_NO_UDF=1` there is no probe and therefore **no mismatch
  warning**.
* I will **not** claim this fixes the separate absent-helper warning gap,
  and will not test it as if it did.
* One mechanical note for you to rule on: `warnings.warn` under the
  default filter coalesces by location, so repeated affected invocations
  would surface **once per process**, not once each. If "per affected
  invocation" is meant literally, the warning needs an explicit filter or
  a sticky state. Your call — I will implement whichever you confirm.

## 6. Test-plan additions, adopted

* Negative control calls the **launcher directly**, bypassing every
  Python-side hint. Test-only helper built against the caller's real
  runtime, reporting a different major/minor. Removing the comparison must
  demonstrably stop the refusal.
* **Release guard on the override:** the build-time version override will
  be `#ifdef`-gated off by default, plus a `release_check` assertion that
  the override symbol is **absent** from release artifacts. A test-only
  flag that can silently reach a release build is worse than no flag.
* Assert the actual failure mode, not just output or offset: mismatch is
  the **reported reason**, `fr_udf_init()` and worker execution did **not**
  occur, descriptor offset unchanged. And per your point — the probe does
  `dlopen` the helper to query its version, so the test must **not** assert
  the helper was never loaded.
* Three layers: route-level non-consumption test; separate public `map()`
  and `stream()` fallback tests proving complete output. This is what
  prevents a correct preflight from masking a broken fallback.

---

## 7. Judgment calls I made where you left it open

Flagging these rather than burying them:

1. **Stream path adopts the whole `_CR_EXIT_PRE_INGEST` set**, not just
   `80`/`81` — §2. Broader than requested; say the word and I narrow it.
2. **Identity key is a `stat` tuple, not a digest** — §4.
3. **Warning coalescing left as an open ruling** — §5.

## 8. Still not established

Unchanged from R1: `auditwheel` remains unverified, so nothing here is
claimed about wheel-time `RPATH`/`RUNPATH` behaviour. The check is a
correctness barrier, not a containment measure — `LD_LIBRARY_PATH`
influence within a matching minor is untouched (DECISION-04 §4).