# Round 14 — re-review of the round-13 fixes

Branch `NEW/REFACTOR4.2`. Review the **branch head**. Round 13 reviewed
`44210027`; this reviews the fixes.

**1053 tests, 0 unexpected failures, 2 skipped.** Release gate green.
Frozen ring untouched.

Round 13 found three blockers. **All three were correct, and one of them
was serious enough that I think it says something about how I work** —
see §1.

---

## 1. The probe never bounded anything

Round 13's P1 was right, and I want to be precise about why it existed:
my "fix" **reproduced the original flaw**. `udf_probe_await()` did a
blocking `read()` and consulted `waited_ms` only *afterwards*, so a
constructor that never wrote a byte parked the parent inside `read()` with
the deadline unreachable and the `SIGKILL` unreachable. Exit 81 was wired
end to end and could not occur.

I wrote a commit message claiming the probe was bounded. It was not. The
green suite did not catch it because **no test exercised it** — which is
the same failure the review round had already predicted when it asked for
the fixture.

**Now fixed:** `poll()` with a monotonic deadline, accumulating partial
reports — the only way to bound a read that may never complete. The child
is **always reaped**; a complete report does not mean the child exited.

**Now proven.** A test-only shared object whose ELF constructor sleeps
forever. The launcher bounds it and exits 81. The test carries its own
subprocess timeout, so a regression *fails* rather than freezing the suite.

## 2. The offset test proved nothing

Round 13 was right, and this is the cleanest evidence-chain failure in the
set. The test opened one descriptor for the assertion and another inside
`_launch`, with **no `pass_fds`** — so POSIX closed both across `exec`.
For a regular file those are independent open-file descriptions: the
measured offset belonged to a file the launcher never touched, and the
test would have passed **even if the launcher consumed the input**.

`_launch()` now takes a caller-provided descriptor and preserves it with
`pass_fds`.

## 3. Parsing was neither strict nor early

`sscanf("%d.%d")` accepts `3.14garbage` and `3.14.1`, contradicting R2.
And parsing ran **after** the probe's `dlopen`, so a malformed
declaration executed the helper's ELF constructors before being rejected,
then reported 71 or 81 instead of the promised 80.

Now a hand-written `MAJOR.MINOR` grammar requiring the string to end
there, validated **before** the probe. Measured across ten inputs:

| input | exit |
|---|---|
| `3.14` | 0 (accepted) |
| `3.9` | 80 (genuine mismatch) |
| `3.14garbage`, `3.14.1`, `3.`, `3.14 `, `.14`, `3`, `314`, `` | 82 |
| `3.0` | 80 (valid grammar, wrong minor) |

**82 splits invalid-declaration from helper-incompatibility.** Sharing 80
meant an internal caller bug entered the negative cache and permanently
blacklisted a good artifact. 82 is pre-ingest and is never cached.

## 4. Also fixed

- **Cached-UDF warnings fired for C plugin calls.** The cache describes
  the CPython-linked helper and has no bearing on a plugin. Narrowed to
  `udf` mode. The warning helper now also honours `FORKRUN_NO_UDF` —
  `candidate_helper_path()` deliberately ignores the kill switch to
  recover identity for diagnostics, and the *warning decision* has to
  consult it separately.
- **Cache TOCTOU.** The refusal is keyed to the artifact actually
  *offered* for that invocation, captured up front, rather than whatever
  occupies the path after the launcher returns — otherwise an old
  helper's refusal blacklists a new valid replacement. The key now
  includes the caller's major/minor, matching the stated design.
- **`v1_available()` docstring** now says `udf=True` means a *candidate*
  helper is present, not that the launcher validated it.
- **Complete-output tests.** `map()` under a forced mismatch must return
  every expected result; `stream()` must stay lazy *and* yield every byte
  exactly once.

## 5. One of my test bugs worth naming

I asserted one record per batch. Cleanroom and in-process choose
different batch boundaries, so `[LINE0, LINE1, LINE2+LINE3]` versus four
records failed a *correct* implementation. The invariant is every byte
exactly once — which is what actually distinguishes a fallback from a
truncation or a duplication.

## 6. Still open — please judge

1. **The safer-by-construction version comparison is NOT implemented.**
   You suggested exposing major and minor as two typed integers via a
   shared header, removing bit packing entirely. I only compare the two
   fields separately now. The packing bug is gone, but the *shape* that
   permitted it remains. Worth doing?
2. **The cache has no lock.** Accepted on your reasoning (GIL, `_RUN_LOCK`
   serialises execution, the cache can only disable the accelerator).
   With the TOCTOU fixed, does that argument still hold as stated?
3. **Sanitizers have not been re-run** over the new C code. The matrix
   was green before this change.
4. **`auditwheel` still unverified**, so nothing is claimed about
   wheel-time `RPATH`/`RUNPATH`.
5. **The real 3.12-helper-vs-3.14-caller matrix case is unexercised** —
   only the synthetic override and the hanging fixture.
6. **A cached mismatch disables the accelerator for the process.** If a
   user upgrades the helper mid-process, the old fingerprint is
   invalidated by `st_ctime_ns`/`st_size`/`st_ino`, so this should
   recover — but I have not tested replacement *while running*.

## 7. Questions

1. Is the probe deadline now genuinely bounded, and is the always-reap
   correct on the success path?
2. Does 82-vs-80 cleanly separate what should be cached from what
   should not?
3. Is validating before `dlopen` sufficient, or should the declaration be
   validated at argument-parse time (before the UDF branch is even
   entered)?
4. Is there a fourth test in the "proved nothing" category that I have
   not noticed?
