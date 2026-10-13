# DECISION-04 — Environment propagation and retry semantics in Python

**Status: DECIDED (TD-04, TD-05). TD-04 keeps current behaviour
deliberately; TD-05's boundaries are now measured (§4.1) rather than
asserted. One open maintainer choice remains: whether a negative
`FORKRUN_RETRY_LIMIT` should warn.**

Origin: the external parity audit, recorded as TD-04/TD-05 in
`TECH_DEBT_REGISTER.md`. Both were flagged there as "records an unrecorded
semantic choice" rather than as bugs. This is that record.

---

## TD-04 — Does the cleanroom get an explicit environment?

### What bash does

`frun.bash` builds the cleanroom environment from an explicit allow-list.
`frun.bash:189` assembles `FORKRUN_EXTRA_VARS` from a named set of
variables, `:193` serialises them into the cleanroom's environment, and
`:451` documents it as the supported mechanism — including the note that
propagating a custom `PATH` *requires* going through it.

### What Python does — verified

| | finding |
|---|---|
| launch site | `run.py:1253` and `run.py:1792` — `os.execv(launcher, argv)` |
| `env=` passed? | **no.** `execv` takes no environment argument |
| launcher scrubs? | **no.** `forkrun_cleanroom.c` has no `unsetenv`/`clearenv`; its only `setenv` is `FRK_POISON_FD` (`:1606`) |
| result | the cleanroom inherits the caller's **entire** environment, unfiltered |

So this is a real divergence: bash curates, Python inherits wholesale.

### But the isolation is not absent — it is one layer down

The embedded interpreter is configured defensively
(`python/forkrun/fr_udf.c:85-117`):

```
isolated = 1            use_environment = 0
user_site_directory = 0 site_import      = 0
safe_path = 1           (3.11+; see the 3.10 compatibility shim)
```

`use_environment = 0` is what neutralises `PYTHONPATH` and `PYTHONHOME`;
`site_import = 0` plus `safe_path` is what stops the cwd and script
directory landing on `sys.path`. This is the same `enforce_path_policy`
work hardened earlier in the project, and it fails closed.

### Decision: keep inheritance, and say so

**Python keeps inheriting the full environment.** Rationale:

1. `forkrun` is a library. A library that silently rewrote its host's
   environment would be worse than one that inherits it — a host
   application may legitimately have `PATH`, `VIRTUAL_ENV`, proxy or
   scheduler variables its UDF genuinely needs, and an allow-list would
   drop them without telling anyone.
2. The Python-visible surface is already closed at the layer where it can
   be, with explicit `PyConfig` fields rather than hope.

The cost of this choice, stated plainly so it is not rediscovered later:
**interpreter isolation cannot reach variables the dynamic linker consumes
before `main()`.** `LD_PRELOAD` and `LD_LIBRARY_PATH` are read by
`ld.so` during `exec`, long before any `PyConfig` field is set. No
`PyConfig` value addresses them.

### The unaddressed surface, precisely

§6.2.1 established that the UDF helper carries **no `RPATH`/`RUNPATH`**.
`forkrun_cleanroom.c:663` loads it with `dlopen(path, RTLD_NOW |
RTLD_LOCAL)`, so the helper's `DT_NEEDED libpython3.X.so.1.0` is resolved
by search order: `RPATH` (absent) → `LD_LIBRARY_PATH` → `RUNPATH`
(absent) → `ld.so.cache` → system paths.

**With both RPATH and RUNPATH absent, `LD_LIBRARY_PATH` is the only
environment-controlled input to which libpython gets loaded.** Since
Python inherits the environment unfiltered, a caller who sets it retains
that influence.

Bounded honestly, though — two things limit the exposure:

- **A different *minor* cannot be substituted.** The loader will not
  satisfy a `DT_NEEDED` of `libpython3.14.so.1.0` with
  `libpython3.12.so`. So §5.5's "a caller/helper CPython-minor mismatch
  is refused safely" is enforced — but **by the dynamic linker, not by
  any application check.** There is no runtime minor comparison anywhere:
  the `PY_VERSION_HEX` occurrences in `fr_udf.c` are compile-time
  conditionals, and `_udf.py` discovers the helper purely by
  `EXT_SUFFIX` filename convention (`:51`) and degrades to in-process if
  the conventionally-named helper is absent.
- **What remains in scope is a different *build* of the same minor** — a
  venv or conda `libpython3.14` earlier in the search path. Same ABI
  minor, potentially different patches/build flags.

That is a narrow, low-likelihood exposure, and **no exploit is claimed
here** — it is recorded so the next person does not assume the packaging
guarantee is stronger than it is.

### Revisit trigger

Reopen this decision if any of the following becomes true:

* the launcher ever grows a non-forked (orchestrated) execution path,
  where a long-lived launcher makes environment capture more valuable
  than it is now;
* `LD_PRELOAD` sanitisation is wanted for threat-model reasons rather
  than measurement reasons — that is a policy call for the maintainer,
  not a bug fix;
* the helper gains an `RPATH`/`RUNPATH` pinning its libpython, which
  would close this by construction.

---

## TD-05 — Retry semantics: is `on_error` the spelling of bash `-E`?

### What matches

`FORKRUN_RETRY_LIMIT` agrees on both sides: bash documents default 3
(`frun.bash:448`), Python sets `DEFAULT_RETRY_LIMIT = 3`
(`_api.py:37`) and reads the same variable, with a comment
(`:33`) noting the bash origin. Good parity; no work needed.

### What diverges

`frun.bash:417,516` — `-E / --retry-nonzero-exit`, **default off**. When
active it appends `|| exit $?`, so *any* nonzero command exit kills the
worker and retries the batch.

Python: `on_error: OnError = "retry"` (`_api.py:130`) is the **default**,
validated against `("retry", "fail-fast", "skip")` (`:43`). There is no
way to select bash's default-off posture.

### Decision: the default difference is intentional — pending one test

**Python's default is deliberately "on".** `on_error` is the API
abstraction the audit itself called legitimate; a library that refused to
retry anything by default would silently turn transient failures into
data loss for callers who never asked for strictness. The divergence is
in the *default*, not the *mechanism*.

**This is recorded as decided but not yet settled**, because one claim
still needs a test rather than an assertion: that the Python "retry"
posture actually matches bash's `-E` behaviour at the same
`FORKRUN_RETRY_LIMIT`, specifically for

* **exit 127** (command/import not found — should this retry? it usually
  indicates a permanent configuration error, and retrying it forever is
  how a "negative value never poisons" setting becomes an infinite loop);
* **transient nonzero exits** below the poison threshold;
* behaviour at `FORKRUN_RETRY_LIMIT=0` (poison on first failure) and at a
  negative value (never poison).

### 4.1 The three boundaries, measured

Now tested in `python/tests/test_retry_boundaries.py`:

| case | measured behaviour |
|---|---|
| payload module does not exist | **fails fast**, `ModuleNotFoundError`, ~0.00s, **no retry**, nothing poisoned |
| spawn command cannot be executed | retries to the limit (3), then **poisons**; counts in `last_run_stats()`; each skip warned on stderr |
| `FORKRUN_RETRY_LIMIT=0` | poisons on the **first** failure, as documented at `frun.bash:448` |

**On the audit's exit-127 question, the answer differs by payload kind,
and Python's half is better than bash's.**

* An **unexecutable spawn command** is the literal 127 analogue, and
  Python matches `-E` precisely: retry to the limit, poison, report. A
  first probe of this looked like a defect — `map()` returned `[]` with no
  exception — but that was the probe's error, not the code's: the counts
  are in the stats surface (`poisoned=8`, `poisoned_batches=[0..7]`) and
  each skip is warned on stderr. Corrected here rather than recorded as a
  finding.
* A **missing payload module** does *not* retry, because the spec resolves
  parent-side (W-REL6-3.1) and the import error surfaces before any input
  is read. Bash under `-E` *would* burn the retry budget on a typo, since
  `|| exit $?` cannot tell "not found" from "transient". Python's
  fail-fast here is a consequence of the fork-safety rule rather than a
  retry decision, and it is worth keeping.

**The negative limit remains untested, deliberately.** `FORKRUN_RETRY_LIMIT=-1`
on a permanently failing payload is an infinite silent loop — measured: it
ran past a 45 s timeout with no stdout, no stderr and no diagnostic. That
matches bash's documented "never declared poisoned (and could retry
indefinitely)" at `frun.bash:448`, so the *semantics* are parity. What is
missing is any **warning**. A test would have to time out, making it slow
and flaky rather than informative, so the boundary is pinned by
documentation instead and the test file says so explicitly.

Whether to warn on a negative limit is an open maintainer choice, not a
parity defect: bash is silent here too.

### Also unexamined

The audit asked about **exit status** parity more broadly (how worker
exits map to the parent's). Not checked. Recorded as unknown rather than
implied-covered.

---

## What this decision does not establish

- That inheriting the full environment is *safe*, only that it is a
  defensible library choice and that its limit is understood and bounded.
- That `LD_PRELOAD` sanitisation is unnecessary — that is a threat-model
  judgement reserved for the maintainer.
- That Python's retry mechanism is equivalent to bash's `-E` in every
  respect. §4.1 tests the three named boundaries and finds parity for the
  unexecutable-command case and a deliberate *improvement* for the
  missing-module case. **Transient nonzero exits that eventually succeed
  were not tested** — only permanent failures — so "retry then succeed"
  remains unverified.
- That a negative `FORKRUN_RETRY_LIMIT` is safe. It is parity with bash,
  and it is a silent infinite loop.
- Nothing about worker exit-status propagation, which was not examined.