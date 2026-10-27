# Engine-session guard: coverage inventory

WO-ROI-1-R1. Established at `0f942b42` + `7b363270`, extended here.

A review raised a specific objection: `map()`'s `orchestrator=False`
branches call `_execute()` without an obvious `with _RUN_LOCK:`, which
would leave the original corruption reachable through a supported
option. That objection is **refuted by test, not by argument** — but the
refutation needed an inventory, because the guard is not where the call
sites make it look.

## Why the call sites mislead

The executors split into two complementary families:

| Executor | Takes `_RUN_LOCK` itself? | Caller obligation |
|---|---|---|
| `_execute` | **yes** | none — self-guarding |
| `_execute_ingest` | **yes** | none — self-guarding |
| `_execute_locked` | no | caller must wrap |
| `_execute_ingest_locked` | no | caller must wrap |
| `_execute_reactor_locked` | no | caller must wrap |
| `_execute_streaming_reactor` | no | caller must wrap |
| `_execute_ingest_reactor_locked` | no | caller must wrap |
| `_execute_ingest_stream_reactor` | no | caller must wrap |
| `_execute_numa_locked` | no | caller must wrap |
| `_execute_cleanroom` | no | caller must wrap |
| `_execute_cleanroom_stream` | no | caller must wrap |

So `map(orchestrator=False)` is covered — it calls the **self-guarding**
wrapper, not a bare `_locked` one. Reading the call site alone gives the
opposite answer, which is why the objection was worth taking seriously
even though it is not what the code does.

## Entry-path inventory

Every executor reachable from `run()`, `map()` and `stream()`, and what
protects it:

| Entry | Path | Guard |
|---|---|---|
| `run` | NUMA (`_execute_numa_locked`) | call site |
| `run` | reactor (`_execute_ingest_reactor_locked` / `_execute_reactor_locked`) | call site |
| `run` | direct (`_execute_ingest` / `_execute`) | **self** |
| `map` | NUMA | call site |
| `map` | cleanroom (`_execute_cleanroom` / `_execute_cleanroom_stream`) | call site, inside `_RUN_LOCK` |
| `map` | reactor | call site |
| `map` | direct / ingest direct | **self** |
| `map` | splice | `_splice_*_gen` via `_guarded_gen`, or direct `_execute` (self) |
| `stream` | all paths | `_guarded_gen` holds the lock for the generator's whole life |

Stream is the strongest case: every path returns through
`_guarded_gen`, whose `with _RUN_LOCK:` spans first `next()` to
exhaustion or close. So the guard's lifetime is the session lifetime
exactly, not an approximation of it.

`TestEveryExecutionPathIsGuarded` exercises
`orchestrator=True`, `orchestrator=False`, `order=none` and `lines`
batching from a live stream, and asserts each is refused and that the
outer stream stays byte-exact. That is the runtime evidence; the table
above is only the explanation.

## Worker-side nesting: the contract

**A forked worker inherits the engine session and a nested run from
inside a worker payload is refused.** Verified directly: a forked child
sees `threading.local().active == True`, and a payload calling
`forkrun.map()` is refused in every batch.

This was previously *accidental* — it fell out of fork semantics rather
than intent — and the diagnostic was wrong: it claimed another run was
live "in this thread", when in fact the process is a forked worker.

Now it is explicit. `os.register_at_fork(after_in_child=...)` records the
inheritance, and the refusal names the real cause:

> refusing to start a nested run inside a forkrun worker process

**The marker is deliberately NOT cleared in the child.** Clearing it
would *admit* worker-side nesting, which is unsafe: the worker is
mid-batch on the inherited engine state, so a nested
`_init_engine_and_fds` would mmap over the mapping its own completion
path still depends on. Refusal is the safe contract and the smallest
defensible one — adding worker-side nesting support to preserve an old
test's expectation would be a large change with no demonstrated need.

## Consequence for the C0.7 certificate

The certificate's nested guard is **not** what handles worker-side
nesting; the session guard fires first. An earlier report claimed
otherwise and was wrong.

The certificate guard remains as defence in depth for attribution
(should a nested run ever become reachable, the delta must not be
charged to the wrong run). Its independent properties are tested
separately in `test_c07_certificate.py`, including failure on a dropped
committed frame, which does not depend on nesting at all.

## Test-evidence boundary

Demonstrated by running: the `orchestrator=False` refusal; the
worker-side refusal and its diagnostic; the outer stream remaining
byte-exact; fork inheritance of the marker.

Established by inspection: that every call site of a `*_locked` executor
is wrapped. `TestEveryExecutionPathIsGuarded` covers the reachable
public configurations, but it is a configuration sample, not a proof
over all future call sites. A new unguarded `*_locked` call site would
not be caught by it.
