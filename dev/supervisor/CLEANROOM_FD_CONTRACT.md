# Cleanroom Descriptor Contract and `posix_spawn` Equivalence — F6 Stage 2

**Status: DESIGN AND EVIDENCE. No production change. No backend adopted.**
Produced under the F6 Stage 2 work order against `e4c255ba`. The F6
performance gate was already MET (§1.1a of `CLEANROOM_LAUNCH_DECISION.md`,
`smaps_rollup`-verified: `fork()+execv()` 29–112 ms vs `posix_spawn`
3.5–4.2 ms at 1–5 GiB parent RSS). This document addresses the **other**
half of that report's gate: whether a `posix_spawn()` implementation could
preserve the shipped behaviour.

**Nothing here is authorised for integration.** See §9 for the
recommendation.

---

## 1. Scope, and what this document does not claim

`forkrun` has exactly **two** cleanroom launch sites, and five served
routes reach one of them. The descriptor work therefore factors into two
distinct shapes, not five.

| Public route | Launch function | Shape |
|---|---|---|
| `map(mode="plugin")` | `_execute_cleanroom` (run.py:1408) | materialized |
| `map(mode="udf")` | `_execute_cleanroom` | materialized |
| `map(mode="spawn")` | `_execute_cleanroom` | materialized |
| `stream(mode="plugin", streaming=True)` | `_execute_cleanroom_stream` (run.py:2191) | streaming |
| `stream(mode="udf", streaming=True)` | `_execute_cleanroom_stream` | streaming |
| `stream(mode="spawn")` | — | **NOT served**; declines to in-process |
| `stream(...)` with `streaming=False` | — | **declines** to in-process |

Route membership was determined by instrumenting both launch functions
from a probe (wrapping, not editing, production), not by reading the
predicate. `stream(spawn)` declining is consistent with the existing
design note that "the streaming path has no spawn dispatch"; the
`streaming=False` decline is an additional constraint that is easy to
overlook and is recorded here so no design work is scoped against a route
that cannot use it.

**A documentation defect found here and NOT fixed in place:** the
`_execute_cleanroom` docstring states "This parent contributes two
inherited descriptors -- the source file and a result memfd"
(`run.py:1419`). That is **incomplete**: the route also passes
`stats_fd`, an optional `trace_fd`, and a duplicated fd 2. Production code
is frozen by this work order, so the comment stands and is recorded here
as a required fix for the integration order, not corrected in place.

**Not claimed:** that the real launcher behaves identically (the observer
stands in for it); that any route is correct end-to-end; that Python
3.10–3.12 was tested (it was not — §6); or that tightening the descriptor
set is equivalent (§5).

---

## 2. Descriptor inventory (source-linked)

Python creates `memfd`/`pipe`/`open` descriptors **non-inheritable**
(`FD_CLOEXEC`) by default, so nothing reaches `exec` unless the route
explicitly says so. The routes do so explicitly, at four sites.

### 2.1 Materialized shape — `_execute_cleanroom`

| role | origin | CLOEXEC? | made inheritable | closed in child | reaches launcher as |
|---|---|---|---|---|---|
| `src_fd` | `_cleanroom_source_fd(source)` (1458) | yes | **yes** (1489) | no | its own number |
| `res_fd` | `memfd_create("fr_cleanroom_result")` (1461) | yes | **yes** (1490) | no | its own number |
| `stats_fd` | `memfd_create("fr_cleanroom_stats")` (1467) | yes | **yes** (1491) | no | its own number |
| `errfd` | `memfd_create("fr_cleanroom_err")` (1473) | yes | **NO** | no (dup2'd) | **fd 2 only** |
| `trace_fd` | `memfd_create(...)` (1510), optional | yes | **yes** (1511) | no | its own number |
| 0,1,2 | inherited | — | — | — | 2 replaced by `dup2(errfd,2)` |

Child body (1579–1580): `os.dup2(errfd, 2)` then `os.execv(...)`.

**`errfd` is a descriptor transformation, not a plain inheritance.** It
stays `FD_CLOEXEC`, so at `exec` the kernel closes its own number; only
the duplicate on fd 2 survives, with `FD_CLOEXEC` cleared by `dup2`. The
launcher therefore reads error output from **fd 2**, and the original
number is gone. Any design that "just inherits `errfd`" would be wrong in
both directions: it would leak the original AND lose the error channel.

### 2.2 Streaming shape — `_execute_cleanroom_stream`

| role | origin | CLOEXEC? | made inheritable | closed in child | reaches launcher as |
|---|---|---|---|---|---|
| `src_fd` | `_cleanroom_source_fd(source)` (2236) | yes | **yes** (2248) | no | its own number |
| `rr` | `os.pipe()` read end (2246) | yes | no | **yes** (`os.close(rr)`, 2283) | absent |
| `rw` | `os.pipe()` write end (2246) | yes | **yes** (2249) | no | its own number |
| `stats_fd` | `memfd_create("fr_cleanroom_stream_stats")` (2256) | yes | **yes** (2259) | no | its own number |
| 0,1,2 | inherited | — | — | — | inherited as-is |

Child body (2283–2284): `os.close(rr)` then `os.execv(...)`.

**The streaming path has no `errfd` and no `dup2`.** Standard error is
inherited directly. Carrying the materialized path's assumptions across
would be an error: the streaming route has no error memfd to reproduce,
and its result channel is a **pipe**, not a memfd.

### 2.3 `stats_fd` and `FRK_POISON_FD` are ONE descriptor

`forkrun_cleanroom.c:2014-2018`:

```c
if (o.stats_fd >= 0) {
    char num[32];
    snprintf(num, sizeof num, "%d", o.stats_fd);
    setenv("FRK_POISON_FD", num, 1);
    g_poison_stats_fd = o.stats_fd;
}
```

The launcher's own comment states the header is "launcher writes the
poison/counter record" (line 185). So one descriptor, one open file
description, **two logical uses**:

1. the launcher writes a header/counter record to it (line 2603);
2. workers append poison batch indices to it, told which fd via
   `FRK_POISON_FD`.

They must not be counted as two descriptors, and a design that "closes
the poison channel" must not close `stats_fd`. Verified by search: no
second descriptor is allocated for poisoning on either route.

### 2.4 Where isolation is actually enforced — and where it is not

`scrub_apply()` runs from `enter_child()` **only** (`forkrun_cleanroom.c:457`).
`main()` never scrubs its own inherited set. So:

* the **launcher process** holds the full inherited post-`exec` set;
* each **worker/scanner/fallow/drain** child is scrubbed down to a
  keep-list via `close_range` (with an `/proc/self/fd` enumeration
  fallback), and `--fd-selfcheck` verifies the keep-list survived.

`--fd-selfcheck` **cannot** answer this work order's question. It runs
after `exec`, inside the launcher, and answers "did the required
descriptors survive my own scrub" — not "which descriptors was the
launcher handed". That is why a separate observer was built (§4).

---

## 3. Observed post-`exec` descriptor sets

Measured by launching `_fd_observer` (test-only) from a faithful
replication of each shape. Roles, not raw numbers, are compared: the two
arms allocate independently and may legitimately number the same logical
descriptor differently, and the launcher receives numbers via argv
(`--src N --result N --stats-fd N`).

| shape | `fork()+execv()` | `posix_spawn()` + proposed actions | identical |
|---|---|---|---|
| materialized | `std0, errfd@2, src_fd, res_fd, stats_fd` | same | **yes** |
| materialized + trace | `std0, errfd@2, src_fd, res_fd, stats_fd, trace_fd` | same | **yes** |
| streaming | `std0, std2, src_fd, rw, stats_fd` (`rr` absent) | same | **yes** |
| + unrelated **CLOEXEC** fd | descriptor absent | absent | **yes** |
| + unrelated **inheritable** fd | **descriptor present** | **present** | **yes** |

**Proposed actions:**

* materialized: `[(DUP2, errfd, 2)]` — one action.
* streaming: `[]` — **no actions at all**. Every required descriptor is
  already inheritable and `rr` is already `FD_CLOEXEC`, so the kernel
  already removes it. `os.close(rr)` in the current child is redundant
  with respect to the post-`exec` set.

Neither design uses `POSIX_SPAWN_CLOSEFROM`, so neither depends on Python
3.13+ (§6).

---

## 4. Observation mechanism, and why the existing one was not enough

`--fd-selfcheck` was inspected and rejected for this purpose (§2.4): it
observes the wrong moment. Modifying the launcher to report its inherited
set was **not** done — production is frozen by the work order.

Instead: `python/tests/_fd_observer.c`, compiled at test time, dumps its
own descriptor set (`FD n cloexec=… target=…`). It is launched *in place
of* the launcher from a replication of run.py's setup. It reads only its
own state and the kernel's `readlink` of each descriptor; it never reads
the environment, so it cannot leak secrets. It is not wired into any
production path and is not collected by test discovery as a test.

**Two harness bugs were found and fixed during development, both of which
had silently disabled the comparison:**

1. `roles()` resolved descriptor targets by reading `/proc/self/fd`
   *after* the descriptors had been closed, so every lookup failed and
   every descriptor degraded to `OTHER:<target>`. Fixed by snapshotting
   while open.
2. `fd <= 2` was hard-coded to `std<N>`, which made the comparison blind
   to the `dup2` onto fd 2 — the one thing the materialized shape is
   about. Fixed by resolving standard streams by target too.

Both were caught only because negative controls existed (§5).

---

## 5. Equivalence is NOT isolation — the central policy question

An unrelated **inheritable** descriptor in the parent survives into the
launcher **in both arms**, and the test
`test_equivalence_is_not_isolation` asserts exactly that. The
equivalence-only action set therefore reproduces the shipped behaviour
*including its leak*.

This forces the question the previous report left implicit:

> Does the new design promise **equivalence** with today's effective
> post-`exec` set, or does it **intentionally tighten** it to a smaller
> allowlist?

They are different contracts and are not automatically compatible:

* **Equivalence** is provable today: the two shapes match (§3), the action
  set is 1 action / 0 actions, and no `CLOSEFROM` is needed.
* **Tightening** would *change observable behaviour*: any payload or host
  that currently relies on an inherited descriptor would lose it. The
  tightening is also expressible — `test_explicit_close_action_removes_the_unrelated_descriptor`
  shows a single `POSIX_SPAWN_CLOSE` action removing it — but expressible
  is not the same as safe.

The design document's "only the source fd and the result fd" phrasing
(`CLEANROOM_DESIGN.md`) reflects the original two-descriptor sketch. The
**shipped** routes pass four or five descriptors plus a duplicated fd 2,
so that sentence must not be read as a description of current behaviour.

**Recommendation: split the two.** Integration should adopt
**equivalence** first — a backend that provably preserves today's
observable behaviour — and any tightening should be a **separate,
deliberate** change with its own compatibility analysis. Calling a
tightening an "equivalence-preserving optimisation" would be false, and
the isolation argument in `CLEANROOM_DESIGN.md` should be stated as an
aspiration until it is measured.

---

## 6. Version and platform strategy

`setup.py` declares `python_requires=">=3.10"`. `os.POSIX_SPAWN_CLOSEFROM`
was added in **Python 3.13** and is conditional on the platform exposing
`posix_spawn_file_actions_addclosefrom_np()`.

**Neither proposed design uses it.** Verified two ways: the action
planners in the test file contain no `CLOSEFROM`, and a test asserts
`os.posix_spawn` has no `close_fds` parameter (that is
`subprocess.Popen`'s keyword; asserting it prevents the conflation
returning).

| runtime / platform | materialized | streaming |
|---|---|---|
| 3.10–3.12, any platform | `(DUP2, errfd, 2)` — all in 3.10 | `[]` |
| 3.13+ with `CLOSEFROM` | same (not needed) | same (not needed) |
| 3.13+ without `CLOSEFROM` | same (not needed) | same (not needed) |
| any platform where `posix_spawn` itself is absent | fall back to `fork()+execv()` | fall back |

So the floor is not a blocker for **equivalence**. It would become one
for **tightening**: a `CLOSEFROM`-based allowlist needs 3.13+, and on
3.10–3.12 the only equivalent mechanism is an explicit `POSIX_SPAWN_CLOSE`
action per unrelated descriptor — which requires first *enumerating*
unrelated descriptors, and that enumeration is the race in §7.

**Not tested:** the 3.14.7 host is the only interpreter available here. The
action plans are version-independent by construction (they reference only
`POSIX_SPAWN_DUP2`, present since 3.8, and no actions at all), but **no
floor-version runtime check was performed** and none is claimed.

---

## 7. Concurrency and descriptor races

`posix_spawn` removes one real hazard: the shipped child runs **Python
between `fork` and `exec`** (`os.dup2`, `os.close`), which is exactly the
deadlock window `_warn_threaded_fork()` documents (run.py:2519-2557). It
warns on every `_RUNLock.__enter__`, so both launch sites are covered by
that net today. `posix_spawn` would make those two sites structurally
safe, which is §4.7's argument and is now concrete.

The **tightening** design, however, has a race the equivalence design does
not:

* enumerating "everything else" requires reading `/proc/self/fd`;
* another thread can open or close a descriptor between the read and the
  `posix_spawn` call, so the action list can name a number that has since
  been reused — closing a descriptor the route needs, or leaving open one
  that is now sensitive;
* `FD_CLOEXEC` state can change concurrently;
* host descriptors intentionally made inheritable are indistinguishable
  from leaks.

The launcher's own `scrub_apply` has the same fallback race in its
`/proc/self/fd` branch, but it is safe **only because the launcher is
single-threaded by construction** — which is the entire premise of the
cleanroom, and is stated in `CLEANROOM_DESIGN.md`. A parent-side
enumeration in a host that `forkrun` does not control has no such
guarantee.

**Conclusion:** equivalence is race-free (its action list references only
descriptors the route itself just created). Tightening is **not** provably
race-free without an additional mechanism, and should not be attempted
without one.

---

## 8. Launch semantics beyond descriptors

### 8.1 Startup failures — a real divergence

> **CORRECTION (Stage 2B).** An earlier revision of this section stated
> that a child-side `execv()` failure (exit 127) is "routed into a
> deliberate warn + in-process fallback". **That was wrong.** It
> conflated two different cases. The error is corrected below and pinned
> by `python/tests/test_launch_failure_contract.py`.

**What actually happens today**, traced from source and confirmed by
observation (a launcher made non-executable passes the existence preflight
but fails `execv`):

| case | source | caller-visible result |
|---|---|---|
| launcher **absent at preflight** | `_cleanroom_launcher_path()` returns `None` (run.py:1425-1432) | `UserWarning` "launcher binary is missing — using the in-process path", `return None` → **falls back** |
| launcher **exists, `execv` fails in the child** | `os._exit(127)` (run.py:1581) | `UserWarning` "**NOT falling back**", then `RuntimeError` → **does NOT fall back** |

The reason is the classification chain, and **127 is simply not in the
set**:

```
_CR_EXIT_PRE_INGEST = {64, 69, 71, 78, 80, 81, 82}   # 127 ABSENT
_decode_launcher_status()  -> pre_ingest = code in _CR_EXIT_PRE_INGEST
_cleanroom_may_fallback()  -> bool(pre_ingest) and not forbidden
```

Measured against the real helpers:

| exit | label | `pre_ingest` | `may_fallback` |
|---|---|---|---|
| 64, 69, 71, 78, 80 | pre-ingest refusals | True | **True** |
| **127** | **unknown exit code 127** | **False** | **False** |
| 70, 1 | internal / runtime | False | False |

Because `may_fallback` is False and `forbidden` is False (127 is not in
`_CR_EXIT_NO_FALLBACK` = `{79}`), control reaches the **unconditional**
`raise RuntimeError` at run.py:1657.

**The two routes also differ from each other** (answering a question the
Stage 2 report left open):

| route | exit 127 result |
|---|---|
| materialized (`map`) | `RuntimeError` — "the input may have been consumed, and the supplied source is a descriptor…" |
| streaming (`stream`) | `RuntimeError` — "the stream is TRUNCATED and the records already yielded are incomplete" |

Both raise; neither falls back; the rationales differ (input-consumption
vs stream-truncation), and only the streaming path raises
`_CleanroomPreIngestDecline` for genuinely pre-ingest exits.

**A pre-existing messaging defect, found while tracing this:** the
materialized `RuntimeError` states "the supplied source is a descriptor"
unconditionally, but is reachable for a **path** source too — the
observed reproduction used a path and produced that message. Recorded
for a later correction; not fixed here (production is frozen).

**The mechanism difference stands.** Under `posix_spawn` the same failure
raises `FileNotFoundError`/`PermissionError` **synchronously in the
parent**, with no child and therefore **no wait status to classify** —
`_cleanroom_may_fallback()` cannot be consulted at all.

| failure | `fork()+execv()` | `posix_spawn()` |
|---|---|---|
| executable missing | child exits **127** → `RuntimeError` | parent raises `FileNotFoundError` |
| exists, not executable | child exits **127** → `RuntimeError` | parent raises `PermissionError` |
| path is a directory | child exits **127** → `RuntimeError` | parent raises `PermissionError` |

#### Failure-policy decision (Stage 2B)

Two candidates were considered.

**Policy A — preserve current behaviour.** Map a spawn-time `OSError`
into whatever the applicable existing failure path produces. For the
materialized route that means raising the same `RuntimeError` a 127
produces; for the streaming route, the same truncation `RuntimeError`.

**Policy B — deliberately improve fallback.** Treat a spawn-time
`OSError` as pre-ingestion and permit fallback.

**Which `OSError`s actually prove no launcher code ran?** A `posix_spawn`
that returns an error returns it **instead of a pid**: no child exists to
reap, so the executable was never entered. That holds for every
`OSError` it can raise — `ENOENT`, `EACCES`, `ENOTDIR`, `EISDIR`,
`EMFILE`/`ENOMEM`. So Policy B is technically defensible, and the
existing rule (`pre_ingest=True` → fallback permitted) would then apply
on its own terms.

**Compatibility consequence of Policy B:** it makes the backend *more
permissive* than today. The same failure — a launcher that cannot be
executed — would raise under `fork()+execv()` and succeed via fallback
under `posix_spawn`. Callers could observe different outcomes for one
identical condition depending on which backend ran. That is a real
inconsistency, and it is also arguably a fix: today a launcher that is
present but unexecutable is treated more harshly than one that merely
declines with exit 64.

**RECOMMENDATION: Policy A for the integration work order.** Reasons:

1. Bundling a failure-policy change into a performance change is how
   regressions hide. Policy B's benefit is real but separable.
2. Policy B must be applied to **both** mechanisms to avoid the
   inconsistency above — which means changing `_execute_cleanroom`'s
   existing 127 handling. That is a deliberate behavioural change to
   shipped failure semantics and deserves its own approval and tests.
3. Policy A is verifiable without judgement: the existing exit-127 test
   surface becomes the specification.

**Policy B is recorded as a recommended separate improvement**, with the
evidence needed (the `OSError`-implies-pre-ingest argument above) and the
consistency requirement stated. **It is not authorised here, and nothing
in this document should be read as describing it as existing behaviour.**

### 8.2 Signals

Measured with a C child (a Python child masks the question, because it
re-establishes its own handlers):

| parent SIGPIPE = SIG_IGN | observed in child |
|---|---|
| `fork()+execv()` | `SIG_IGN` preserved |
| `posix_spawn()`, no signal options | `SIG_IGN` preserved — **equivalent** |
| `posix_spawn(setsigdef=(SIGPIPE,))` | **reset to `SIG_DFL`** |

So: **pass no `setsigdef`/`setsigmask`.** Passing `setsigdef` would
silently change disposition relative to the shipped path — which matters
for a tool whose workers rely on inherited `SIG_IGN` for SIGPIPE.

### 8.3 Route and payload semantics

Not exercised here and **not** proven equivalent: plugin ABI/version
checks, UDF helper selection and version checks, spawn argv validation,
stats/poison accounting, trace reporting, and result collection. These are
unchanged by a launch-mechanism swap only to the extent that the same
argv reaches the same binary — which §3's descriptor equivalence
supports but does not by itself establish. The existing route tests remain
the authority and were not modified.

---

### 8.4 A PRE-EXISTING DEFECT FOUND: a route descriptor can be clobbered on fd 2

**Not introduced by `posix_spawn`, and not fixed here.** Audited per the
Stage 2B work order and confirmed by observation:

```
fd 2 closed, then run.py's allocation order (run.py:1458-1473):
    src_fd = 2   res_fd = 3   stats_fd = 4   errfd = 5
then os.dup2(errfd, 2)   (run.py:1579)
    fd 2 -> /memfd:fr_cleanroom_err
```

The launcher is then told `--src 2` and would read the **error memfd as
input**. The triggering condition is: **stdin/stdout/stderr fd 2 closed
in the host process before the route allocates.** Roles affected:
`src_fd` (silently replaced), and by extension `res_fd`/`stats_fd` if
they were the first allocation.

This is pre-existing: `posix_spawn`'s `POSIX_SPAWN_DUP2(errfd, 2)` does
exactly the same thing, so **descriptor equivalence still holds for this
case** — both mechanisms are wrong in the same way. What the equivalence
claim must not do is imply the case is *verified*; it is neither verified
nor fixed.

Pinned by `test_route_descriptor_can_land_on_fd2_and_be_clobbered` (in a
subprocess, so the runner's own stderr is not corrupted). **C5** tracks
it.

**Decision on whether an open fd 2 is an acceptable precondition (D3).**

*It does not conflict with an existing binding contract.* `INVARIANTS.md`
records "fd 2 never redirected/closed" as a standing guarantee about
forkrun's own fork sites. The cleanroom route deliberately REDIRECTS fd 2
via `dup2(errfd, 2)` — a documented deviation — but it never *closes* fd 2,
so the invariant is not violated. No API doc promises behaviour with a
closed stderr, and no test asserts one.

*So a precondition could be documented — and it is, in
`CLEANROOM_DESIGN.md`. But documenting it is NOT sufficient, and C5 stays
OPEN regardless.*

The reason is severity, not convenience. Every other precondition in this
document degrades performance or adds a mechanism. This one produces
**silent input corruption**: the launcher is handed `--src 2` and reads the
error memfd as its input, so the caller receives a well-formed result
computed from the wrong bytes. There is no error, no warning, and no
non-zero exit — the failure is indistinguishable from success.

A precondition is the right instrument for "we cannot support this
configuration". It is the wrong instrument for "supporting this
configuration silently returns wrong answers", because a caller who does
not read the precondition gets no signal at all.

**Recommended for the integration work order:** a narrowly scoped guard
rather than documentation alone. The cheapest correct shape is to ensure
the route's own descriptors are allocated ABOVE fd 2 before the error
memfd is created, so `dup2(errfd, 2)` cannot overwrite a route
descriptor. That is a few lines and does not touch the engine, the launch
mechanism, or the failure contract.

**Not done here.** This work order forbids changing production behaviour
for closed standard descriptors, and the fix is a production change. The
precondition is documented; the fix is recommended and left open.

**Do not read mechanism equivalence as covering this.** `posix_spawn`'s
`POSIX_SPAWN_DUP2(errfd, 2)` does exactly what `os.dup2` does here, so the
two launch mechanisms are equivalent — and both mishandle the layout.
Equivalence is a statement about *matching* the shipped behaviour, not
about that behaviour being correct.

---

### 8.5 Parent-side descriptor lifecycles (Stage 2C)

Two parent-owned descriptors leaked on **every** cleanroom call. Measured
before the fix: 1, 2, 3, 4, 5 open descriptors named `fr_cleanroom_err`
after 1..5 materialized calls, and the same for
`fr_cleanroom_stream_stats` after streaming calls.

| descriptor | owner | leaked on | closed now at |
|---|---|---|---|
| `errfd` (materialized) | parent | success, exit-127, every failure raise/return | after `_read_launcher_stderr` (failure branch), and in an `else` on the success branch |
| `stats_fd` (streaming) | parent | success, every failure raise, `strict_poison` raise, **generator abandonment** | the `finally`, which every exit passes through |

Why the streaming fix is safe: after `fork`, parent and child hold
**separate descriptor-table entries** sharing one open file description.
Closing the parent's entry does not affect the child's, so the close in
`finally` cannot disturb a still-running child, and on the success path
the read has already happened.

`errfd`'s close is deliberately placed **before** the failure branch's
raises and returns, and duplicated as an `else` on the success path,
because the branch raises internally — a single close after the `if` would
be skipped by every failure exit. `errfd = -1` follows each close so a
stray later close cannot hit a recycled descriptor number.

Both are pre-existing lifecycle defects, **not regressions**, and had to be
closed before any backend work: carrying them into a `posix_spawn`
integration would have inherited the leak.

Pinned by `python/tests/test_cleanroom_fd_lifecycle.py` — 8 tests,
exercising the production launch functions through the public API, counting
named memfds in `/proc/self/fd`. Reverting the production fix turns six
red; removing only the streaming close turns four red. The real build
artifact's mode is never changed: the exec-failure cases patch
`_cleanroom_launcher_path` to a temporary non-executable file.

**Residual uncovered path (B3):** an unexpected exception raised by
`_read_cleanroom_stats()` or `_read_cleanroom_trace()` in the materialized
path, before the failure branch is reached, would still leak `errfd`.
Closing that would mean wrapping that region in `try/finally`, which is a
wider restructure than this work order's "bounded fix" and is recorded
rather than done.

---

## 9. Recommendation: CONDITIONAL GO

**Not a GO.** Two items are open, and the first is a correction of this
document's own earlier error:

1. **Startup-failure mapping (§8.1) is not designed.** The current
   contract is now stated correctly — exit 127 raises, it does not fall
   back — but the mapping from a spawn-time `OSError` onto that contract
   is unbuilt. **Policy A** is recommended; **Policy B** (treat the
   `OSError` as pre-ingest and fall back) is a defensible separate
   improvement that is explicitly **not** authorised here.
2. **Descriptor equivalence is not claimed for all layouts.** It is
   claimed for the layouts tested, under the stated preconditions below.
   In particular the closed-std-fd case (§8.4) is **not** covered.

**Not a NO-GO**, because the hard technical questions have defensible
answers:

* the current descriptor contract is reproducible with **one action** on
  one shape and **zero actions** on the other;
* neither needs `POSIX_SPAWN_CLOSEFROM`, so the **3.10 floor is not a
  blocker**;
* signal semantics are equivalent provided **no `setsigdef`** is passed;
* the equivalence action set references only descriptors the route itself
  created, so it carries **no enumeration race**;
* the failure contract is now **pinned by tests against the production
  helpers**, so an integration cannot quietly inherit a wrong assumption
  — mutating `_CR_EXIT_PRE_INGEST` to include 127 turns six of them red.

**Conditions to close, each with its closing evidence:**

| # | condition | closing evidence |
|---|---|---|
| C1 | a spawn-time `OSError` produces the **same caller-visible result** the applicable existing failure path produces today (Policy A) | a test per route: an unexecutable launcher raises the same exception type and message family as exit 127 does |
| C2 | no `setsigdef`/`setsigmask` is passed | assertion in the integration test |
| C3 | policy recorded: equivalence now, tightening (if any) later | a decision line in `CLEANROOM_LAUNCH_DECISION.md` §8 |
| C4 | equivalence re-verified against the **real** launcher, not just the observer | one integration-mode test per shape comparing the launcher's actual inherited set |
| C5 | the closed-std-fd precondition is either fixed or documented as a precondition | a named precondition in `CLEANROOM_DESIGN.md`, or a scoped fix in a later order |

## 10. Evidence and reproduction

Everything below is committed and runnable from the branch.

```
# descriptor equivalence, negative controls, high-fd cases  (16 tests)
python3 -m unittest python.tests.test_cleanroom_fd_contract -v

# launch-failure contract, route-level results, signals, closed-fd (16)
python3 -m unittest python.tests.test_launch_failure_contract -v

# parent-side descriptor lifecycle / leak regression        (8 tests)
python3 -m unittest python.tests.test_cleanroom_fd_lifecycle -v
```

Both files compile their own C fixtures at test time (`_fd_observer.c`, and
an inline signal-disposition probe) and skip cleanly if no compiler is
present. Neither is wired into production, and neither reads the
environment.

**Mutation checks actually run against this evidence:**

| mutation | result |
|---|---|
| `_CR_EXIT_PRE_INGEST` gains 127 (**production**, reverted immediately) | **6 tests FAIL** |
| pipe disambiguation removed from the role comparison | FAIL |
| comparison's `identical` hard-coded `True` | FAIL |
| fd ≤ 2 hard-coded to `stdN` | 2 tests FAIL |
| closed-fd audit flipped to assert *equality* | FAIL |

The production mutation is the important one: it is what makes the
"exit 127 does not fall back" claim testable rather than asserted.

### What is observed vs derived vs untested

**Directly observed** (executed, recorded above):

* post-`exec` descriptor role sets, both mechanisms, both shapes;
* high-numbered descriptor survival at fd 1500;
* exit 127 classification and the resulting `RuntimeError` for both routes;
* `posix_spawn` raising `FileNotFoundError`/`PermissionError`;
* signal disposition with and without `setsigdef`;
* the closed-fd clobbering.

**Derived from source, not executed here:**

* that `FRK_POISON_FD` and `stats_fd` are one descriptor (read at
  `forkrun_cleanroom.c:2014-2018`, confirmed by search, not by tracing a
  live run);
* the route→launch-site matrix (confirmed by instrumenting the dispatch,
  which is observation, but of the dispatcher rather than of the launcher);
* that `main()` does not scrub its own inherited set (read from
  `scrub_apply`'s only caller being `enter_child`).

**Not tested, and not claimed:**

* the **real** launcher's inherited set — the observer stands in for it;
* Python 3.10–3.12 (host is 3.14.7 only);
* descriptor behaviour with fd 0/1 closed, or fd 2 closed *and* a route
  descriptor landing there — the latter is audited in §8.4, the former is
  not covered at all;
* any posix_spawn **integration** — none exists.
