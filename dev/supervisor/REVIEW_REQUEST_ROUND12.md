# Round 12 — review request: the W-EXP-1 minor-mismatch refusal (proposed)

Branch `NEW/REFACTOR4.2`. Review the **branch head**; `2a5f4068` is the
last commit this request pins. Frozen ring files (`forkrun_ring.c`,
`forkrun_ring.h`, `forkrun_substrate.h`, `substratestubs.c`) untouched
across the whole branch history.

**1038 tests, 0 unexpected failures, 2 skipped.** Release gate green.

This is a **narrow** request with **no code written yet**. I want the
design reviewed *before* implementation, because the change touches the
engine's loading path and the obvious implementation has a security
dimension that is easy to get wrong.

---

## 1. What I am proposing, in one paragraph

Add an explicit **pre-flight** check that the per-minor UDF helper matches
the calling interpreter's minor, and refuse before input is consumed, with
an observable message. Today there is **no application-level check at
all** — the mismatch is caught by the dynamic linker at `dlopen` time,
which happens *after* the input has already been materialised.

## 2. The requirement being met

Roadmap §5.5, currently unchecked:

> A caller/helper CPython-minor mismatch is refused safely **before input
> consumption**, with the refusal observable. A helper built for 3.12 must
> not be driven by a 3.14 caller.

And §5.3:

> **Absent helper.** A distinct exit code — **not 79**, which means "the
> probe failed and fallback is unsafe" — so Python warns and takes the
> in-process path, mirroring the exit-78 refusal precedent.

## 3. What happens today — verified, not assumed

**There is no runtime minor comparison anywhere in the tree.**
`PY_VERSION_HEX` appears in `fr_udf.c` only as *compile-time* `#if`
conditionals. Helper discovery is purely filename convention: `_udf.py:51`
builds `_fr_udf` + `EXT_SUFFIX`, and returns `None` if that file is
absent.

Discovery-by-filename does catch the **common** case: on 3.14 you look for
`_fr_udf.cpython-314-*.so`, and a 3.12-only tree yields `None` → in-process
fallback. That part works.

**What it does not catch is the case the criterion names.** If a caller
passes a helper path explicitly, or the suffix happens to match, the
mismatch surfaces at `dlopen` as a `DT_NEEDED` failure — and §6.2.1
established the helper carries **no `RPATH`/`RUNPATH`**, so nothing pins it
to a particular `libpython`.

**The ordering problem is the actual defect.** In `_execute_cleanroom`:

```
1132:  src_fd = _cleanroom_source_fd(source)     <- input materialised
1253:      os.execv(launcher, argv)              <- launcher starts here
                 ... inside: setup_udf_helper() -> dlopen()  <- mismatch found HERE
```

So the input is read and `mmap`ed **before** the mismatch is discoverable.
The criterion's "before input consumption" is therefore not met today: the
refusal happens, but after the work the refusal is supposed to avoid.

This ordering claim is the load-bearing one in this proposal. It is why I
am asking for review before writing code — if it is wrong, the change is
unnecessary.

## 4. Proposed design

**Helper side (C):** export `int fr_udf_built_minor(void)` returning
`PY_MINOR_HEX` at compile time.

**Caller side (Python, `_udf.py`):** after locating a helper, read the
built minor via `ctypes` and compare to `sys.version_info.minor`.

**Refusal behaviour:** treat a mismatch exactly like an absent helper —
`helper_path()` returns `None`, so the route degrades to in-process with a
warning. This keeps the existing single-choke-point design (established in
TD-11, where `FORKRUN_NO_UDF` was implemented the same way) rather than
adding a second decision point.

**Exit code:** per §5.3 this must be a **distinct** code, not 79. My
proposal is **exit 78**, matching the existing refusal precedent — but
§5.3 says "mirroring the exit-78 refusal precedent" as if 78 is *not* the
right one, and I cannot find a statement of what 78 means. **This is
question 1 below; I do not want to guess an exit-code contract.**

## 5. Alternatives I considered and rejected

| option | why not |
|---|---|
| Add an `RPATH`/`RUNPATH` pinning `libpython3.X` | Closes the substitution path at the loader, but §6.2.1 could not verify what `auditwheel repair` does to it, and it is packaging work, not a refusal |
| Rely on `DT_NEEDED` alone | Already the status quo, and it fails the "before input consumption" requirement |
| Validate only in `v1_available()` | Reports capability but does not prevent the route; two decisions to keep in sync |
| Refuse the whole run rather than degrade | Contradicts §5.3, which says warn and take the in-process path |

## 6. What this proposal does NOT fix

Stated up front, because this area has a habit of overclaiming:

- **It does not make `auditwheel` verifiable.** §6.2.1 ran two of three
  checks; the tool is still not installed. That gap is untouched.
- **It does not close `LD_LIBRARY_PATH` influence.** DECISION-04 §4 records
  that with no `RPATH`/`RUNPATH`, `LD_LIBRARY_PATH` is the only
  environment-controlled input to which `libpython` loads. Python inherits
  the environment unfiltered. This proposal is a **refusal**, not a
  containment measure, and a determined caller can still influence
  resolution *within a matching minor*.
- **It does not detect a same-minor, differently-built `libpython`.** The
  check compares minors only.
- **It does not address TD-01** (record protocol defined in three places)
  or **TD-06** (executor consolidation) — both deliberately deferred.

## 7. Test plan

Non-vacuity is the point; this branch has shipped two protocol bugs that a
green suite did not catch.

1. **Positive control:** matching helper → route proceeds, `udf` capability
   reported `True`, identical results to the in-process path.
2. **The criterion itself:** 3.12-built helper offered to a 3.14 caller →
   refusal, observable message, **and the input is not consumed**. The
   last part needs a source that would fail if read (e.g. a FIFO with no
   writer, or a path that would error), so a post-read check cannot pass.
3. **Negative control:** remove the comparison → test 2 must fail.
4. **Degradation:** with the switch forced, results are still **complete and
   correct**, not fewer. Same property as TD-11's kill-switch test.
5. **Interaction:** `FORKRUN_NO_UDF=1` and a mismatched helper together →
   in-process, single warning, no double-warn.

## 8. Questions for the reviewer

1. **The exit code.** §5.3 says "a distinct exit code — not 79" and "not
   [78] which means the probe failed", then says "mirroring the exit-78
   refusal precedent". I cannot resolve what 78 denotes. **What is the
   correct code, and what does 78 already mean?**
2. **Is "degrade to in-process" right for a *mismatch*, as opposed to an
   absent helper?** A mismatch means someone shipped a broken build;
   silently using a different path may be worse than refusing loudly.
   §5.3's wording is about an *absent* helper.
3. **Is the `ctypes` read of a C symbol the right mechanism**, or should
   the helper expose the minor through the existing probe/`v1_available()`
   channel instead? A `ctypes` call on a `.so` that may not be loadable is
   exactly the kind of thing that produces an unhandled exception at an
   awkward moment.
4. **Does the §5.5 criterion apply to `mode="udf"` only, or to every route
   that can reach `dlopen`?** `mode="plugin"` uses the same launcher.
5. **Is this worth doing at all**, given §3 — discovery-by-filename already
   catches the common case? If the honest answer is "the criterion is
   stricter than the real risk", I would rather record that in §5.5 and
   close the item than add a check that never fires.

## 9. Status vocabulary

This branch has been conflating these, so, explicitly:

- The three criteria fixed this session (TD-10 class refusal, TD-11 kill
  switch, and the unbounded-retry warning) are **implemented and tested**.
- This proposal is **not implemented**. Nothing in it exists in code.
- The `fork_workers` / `report_poison` consolidation is **mapped only**.
- Packaging under `auditwheel` is **unverified**, not passing.