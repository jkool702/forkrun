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

Measured with the shipped code paths:

| failure | `fork()+execv()` | `posix_spawn()` |
|---|---|---|
| executable missing | child exits **127** | parent raises **`FileNotFoundError`** |
| exists, not executable | child exits **127** | parent raises **`PermissionError`** |
| path is a directory | child exits **127** | parent raises **`PermissionError`** |

This is the sharpest difference found, and it is **not** equivalent. Today
a pre-exec failure becomes a wait status that `_execute_cleanroom`
inspects, and then routes into a deliberate policy: warn and **fall back
to the in-process path** (`return None`), or refuse, or raise
`_CleanroomCompatRefusal`. With `posix_spawn` the failure is synchronous
and would raise **past** all of that machinery.

The codebase is explicit that falling back is the intended behaviour
("slower and correct beats fast and missing"; the `_exit(127)` sites
exist precisely so the parent can tell "launcher failed" from "exec
never happened"). A naive `posix_spawn` swap would turn a designed
fallback into an uncaught `OSError`.

It is **fixable** — wrap `posix_spawn` in `try/except OSError` and feed
the failure into the same status-handling path — but that is an
integration-time change, and it must close the already-created
descriptors on the failure path (`src_fd` is opened before the launch).

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

## 9. Recommendation: CONDITIONAL GO

**Not a GO**, because the descriptor question — the one this work order
was asked to settle — is answered, but two material items are open:

1. **Startup-failure semantics (§8.1) are not equivalent and not yet
   designed.** A design that routes `OSError` into the existing
   fallback machinery, with descriptor cleanup on that path, is required
   before integration.
2. **Isolation vs equivalence (§5) is an open policy choice, not a
   technical unknown.** The performance result is a strong argument for
   the change; the contract change is not implied by it.

**Not a NO-GO**, because the hard technical questions have defensible
answers:

* the current descriptor contract is reproducible with **one action** on
  one shape and **zero actions** on the other;
* neither needs `POSIX_SPAWN_CLOSEFROM`, so the **3.10 floor is not a
  blocker**;
* signal semantics are equivalent when no `setsigdef` is passed;
* the equivalence action set references only descriptors the route itself
  created, so it carries **no enumeration race**.

**Conditions to close, each with the evidence that closes it:**

| # | condition | closing evidence |
|---|---|---|
| C1 | `posix_spawn` `OSError` is routed into the existing warn/fallback path, with `src_fd`/`res_fd`/`stats_fd` closed on failure | a test that a missing launcher yields the same `UserWarning` + in-process completion as today |
| C2 | no `setsigdef`/`setsigmask` is passed | assertion in the integration test |
| C3 | policy recorded: equivalence now, tightening (if any) later | a decision line in `CLEANROOM_LAUNCH_DECISION.md` §8 |
| C4 | equivalence re-verified against the **real** launcher, not just the observer | one integration-mode test per shape comparing the launcher's actual inherited set |

**C4 is the honest limit of this work order.** These tests prove the
*mechanism* is equivalent under a faithful replication. They do not
observe the real launcher. That required a production change, so it was
not done.

### Smallest next work order

A single integration order scoped to: `posix_spawn` behind a private,
explicitly-gated code path in `_execute_cleanroom` and
`_execute_cleanroom_stream`; the `OSError`→fallback mapping (C1); the
no-signal-options assertion (C2); and a real-launcher descriptor
observation test (C4). No engine change, no environment change, no
descriptor tightening, no route-eligibility change.

---

## 10. Evidence and reproduction

```
# descriptor equivalence + negative controls (14 tests)
python3 -m unittest python.tests.test_cleanroom_fd_contract -v

# startup-failure and signal semantics (the §8 probes)
#   executed ad hoc during this work order; NOT yet committed as tests
#   -- see "Not yet a test" below.
```

`test_cleanroom_fd_contract.py` mutation-checked three ways, each caught:

| mutation | result |
|---|---|
| pipe disambiguation removed | FAIL (streaming case) |
| `identical` hard-coded `True` | FAIL (missing-dup2 control) |
| fd ≤ 2 hard-coded to `stdN` | FAIL (2 tests) |

**Not yet a test:** the §8 startup-failure and signal probes were run as
one-off scripts in this session, not committed. They are the two
conditions (C1, C2) most likely to regress silently, so they should be
committed before integration is attempted.