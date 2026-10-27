# Nested runs: root cause, verified

Supersedes the "timing, not kind" framing in NESTED_RUN_DEFECT.md, which
was wrong as stated. The failure is deterministic in mechanism and
*intermittent only in whether it is noticed*.

## Root cause

`ring_init_main` and `ring_destroy_main` manipulate **process-global**
`g_state` and `state`:

* `ring_init_main` (forkrun_ring.c:2533) `mmap`s a new region
  unconditionally — there is no reuse branch — and overwrites
  `g_state`. Any previous mapping is **leaked**.
* `ring_destroy_main` (forkrun_ring.c:2950) `munmap`s `g_state` and sets
  both `g_state = NULL` and `state = NULL`.

A nested run therefore performs, in the enclosing run's process:

1. enclosing `init`  -> mapping **A**, `g_state = A`
2. enclosing workers fork; they inherit **A** and keep using it
3. nested `init`     -> mapping **B**, `g_state = B`   (A now leaked)
4. nested `destroy`  -> `munmap(B)`, `g_state = NULL`, `state = NULL`
5. enclosing run's PARENT now has no engine state at all

The enclosing workers keep running on the orphaned mapping A, but the
parent can no longer supervise, recover, or finalise them.

## Verified

Probe with `fr_py_diag_node`, which returns -1 when no engine state is
readable:

```
before stream:                       rc=-1  (no engine — correct)
inside stream, before nested map:    rc=0   (outer engine live)
inside stream, AFTER nested map:     rc=-1  (NO ENGINE STATE)
```

The enclosing run loses its engine mid-stream. That is the defect; the
`Worker 0 recovery failed (orphan revert/escrow)` abort is one symptom,
seen when a worker happens to die before the parent can reach `state`.

## The nested run's own data is correct

Worth stating, because it rules out the obvious explanation. The nested
run reads its OWN input:

```
nested map returned 25 records; first record tag: b'INNER-0 payload'
```

because step 3 gave it its own mapping. So this is not a data-mixing
bug. It is a supervision bug: the nested run is correct, and the
enclosing run is destroyed by it.

## Why the failure looked size-dependent

Measured failure rate over 4 trials each, nesting at record 5:

| outer lines | failures |
|---|---|
| 500   | 4/4 |
| 2000  | 3/4 |
| 10000 | 0/4 |
| 60000 | 2/4 |

Non-monotonic, which is why the earlier note blamed timing. The real
explanation is that the corruption is **always** there; it only becomes
visible when something afterwards needs the engine — a worker death, or
finalisation touching `state`. Whether that happens correlates with how
the stream happens to be positioned, not with its size.

## Memory consequence

Mapping A is never unmapped: `g_state` was overwritten by B before any
destroy, and by the time the enclosing run tears down, `g_state` is NULL.
Every nested run inside a live run leaks one full engine mapping.

## Existing test

`test_stream_lock.TestNestedStreamMap.test_nested_map_inside_stream_completes`
passes only because its stream is small enough that the outer run never
needs the engine again after the nested call. It asserts the run
"completes", not that the engine survived.

## Fix directions

**Reference counting is NOT sufficient.** Making `init`/`destroy`
balanced would stop the munmap, but the nested run needs its own engine
(input, batch geometry, ring state) and would then be sharing the
enclosing run's engine instead — reading the OUTER run's data. That is a
worse failure than a crash.

So the options are:

1. **Per-run engine handle.** The only fix that makes nesting correct:
   a handle passed through the worker/collect calls instead of a global.
   Large, and it touches the frozen engine.
2. **Forbid nesting explicitly** and delete the test that implies it is
   supported. Small and honest. The supported shape remains "one
   engine live per process"; a nested call fails fast with a clear error
   rather than corrupting its parent.

My recommendation is **(2) now, (1) later if the use case appears** —
the same reasoning used to exclude splice from the certificate: do not
claim a guarantee the architecture cannot provide.
