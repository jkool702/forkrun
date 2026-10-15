# Cleanroom default-on readiness — decision

WO-ROI-1 §2. Evaluated at `0f942b42` (P0 nested-session fix) plus the
WO-CM1-R1 inventory.

## Decision: **B — the gate does not pass. The default is unchanged.**

The plugin envelope is close to ready and is the strongest of the three.
The reason the *default* cannot move is structural, not a missing test.

## Why not (A)

### 1. The gate is global, so default-on would enable three envelopes at once

`_cleanroom_enabled()` is a single boolean over `FORKRUN_CLEANROOM`
(run.py:437). There is no per-mode gate. Flipping the default from OFF
to ON would simultaneously enable, for UMA:

| Envelope | Dispatch site | Route evidence |
|---|---|---|
| `map(plugin)` | run.py:3877 | **Route asserted** (`_run_marked` spy) |
| `map(udf)` | run.py:3877 | Output only |
| `map(spawn)` | run.py:3877 | Output only |
| `stream(plugin)` | run.py:4337 | Output only |
| `stream(udf)` | run.py:4337 | Output only |

Only **plugin** has a test that asserts the launcher route was taken.
The other four assert output, which an in-process fallback also
satisfies — precisely the failure mode this decision must not ship.

WO-ROI-1 §2.3 is explicit: do not make cleanroom globally default-on if
that would also enable envelopes that have not passed their own gate.

### 2. `spawn`'s documentation is actively wrong

`python/tests/test_stage3_spawn_launcher.py` states:

> "The launcher's spawn ENVELOPE is still declined. This module pins the
> plumbing, not activation."

That is stale. Verified at the current head: with the gate on,
`map(mode="spawn")` enters the launcher route (a parent-side spy on
`_execute_cleanroom` records the call) and returns 50 records. Spawn is
activated, not declined. Corrected in this pass.

This matters for the decision: the reason one might have believed spawn
was safe to enable by default is that the suite says it is declined. It
is not.

### 3. `udf` and `spawn` have no route-level assertion

`test_udf_runs_in_the_cleanroom` asserts records and their contents. If
the launcher route were dead and the run fell back in-process, it would
still pass. `test_stage3_lifecycle.py` contains no cleanroom reference
at all, so spawn's lifecycle gates (setsid escape, respawn, teardown)
are asserted on the in-process path, not the launcher one.

## What the plugin envelope already has

| Gate item | Evidence |
|---|---|
| Correct launcher selection | `_run_marked` parent-side spy (route, not output) |
| Exact output / error paths | 107 tests in `test_cleanroom*.py` |
| Resource cleanup, no survivors | `test_fatal_failure_leaves_no_surviving_descendants` |
| Dialect / ABI enforcement | v0 fixture refused, exit 78, raw-status decoding |
| Poison + statistics, bounded list | `test_full_slot_is_detectable_as_truncated` |
| Target + full suite | 107 and 1129 pass |

## Remaining gaps, smallest-first

1. **No test for a missing launcher binary.** `_execute_cleanroom`
   warns and returns `None`, and the caller continues in-process, but
   nothing asserts that fallback or its warning. Fixed in this pass
   (see the added test).
2. **No route-level assertion for `udf` or `spawn`.** Each needs the
   same parent-side spy `plugin` has. Cheap, and it is the difference
   between "works" and "known to work".
3. **No cleanroom-specific performance evidence.** `C07_PERF_NOTE.md`
   measures the C0.7 counter, not launcher-vs-in-process. The decision
   does not depend on it today because the default is not moving, but it
   would before (1).
4. **A per-envelope gate does not exist.** Until it does, plugin cannot
   be enabled alone. This is the single structural blocker.

## Smallest action that would close the gate

Add a per-envelope selector — e.g. `FORKRUN_CLEANROOM=plugin` — so the
plugin envelope can be default-on while `udf` and `spawn` remain opt-in
until they have route-level tests. That is a gate change, not an
envelope change: it enables no new capability, it only stops the gate
from coupling three envelopes together. With (1) and (2) closed, the
plugin envelope is defensible on its own evidence.
