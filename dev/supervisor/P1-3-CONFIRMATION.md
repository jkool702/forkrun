# Confirmation pass — P1-3 review amendment, as implemented

*Follow-up to your P1-3 review (GO WITH AMENDMENTS). This is a
confirmation pass, not a new review. You have no repository access;
everything you need is below. Please be brief and specific — we want to
close this out, not reopen it.*

---

## 1. What you told us, and what we did

You made the fork hooks a **condition of approval**. We implemented them:

```c
int fr_udf_before_fork(void);       /* PyOS_BeforeFork */
int fr_udf_after_fork_parent(void); /* PyOS_AfterFork_Parent */
int fr_udf_after_fork_child(void);  /* PyOS_AfterFork_Child */
int fr_udf_fork_hooks_available(void);
```

* **Fail closed, not no-ops.** They return `FR_UDF_ERR` if called with no
  interpreter, or on a CPython built without `HAVE_FORK`.
  `fr_udf_fork_hooks_available()` reports the latter.
* **Centralised.** One `udf_fork()` helper wraps every fork; there is no
  raw `fork()` left in the driver. The parent hook runs on the failure
  path too (`fork() == -1`), since `BeforeFork` already took locks.

Also accepted as written: raising UDF → batch-level payload failure on the
existing `on_error` policy; `fr_udf_free()` is mandatory ownership; the
parent must not import or invoke the UDF; per-worker vs. respawn state
model documented; DECISION-02's `None`-has-no-data-record limitation
preserved and not papered over.

## 2. Three things we want you to check

### 2.1 We found a bug in our own hook wiring

The first version aborted **every** pre-fork child:

```
Fatal Python error: PyMutex_Unlock: unlocking mutex that is not locked
```

Cause: `udf_fork()` ran `PyOS_AfterFork_Parent()` in *both* processes, so
the child unlocked the mutex `PyOS_AfterFork_Child()` owns. Fixed.

**Our interpretation, which we want you to confirm or correct:** this was
*our* wiring error, not evidence that the earlier pre-fork measurements
were invalid. Your wording was "the implementation that earned those
measurements may not yet be the implementation that should ship", and we
read the concrete risk as: those numbers came from a build doing no fork
choreography at all. The bug we hit is a different thing — a bad call
sequence in the replacement.

Is that a fair reading, or do you think the earlier numbers are more
tainted than we've allowed?

### 2.2 The hooks are not load-bearing on this machine — we say so plainly

You made the hooks a condition of approval partly because successful runs
do not establish correct fork handling. We agree, so we tested it directly:
`fr_udf_fork --hooks` deliberately violates the choreography (takes
`BeforeFork`, forks, omits `AfterFork_Child`) and reports the outcome.

**On our single-threaded, contention-free host, the unhooked child
SURVIVES.** So on this configuration the hooks change no observable
behaviour. We currently state in the docs that they:

- are **not** demonstrably load-bearing here,
- protect contention cases this harness never creates (another thread at
  fork time; a UDF that spawns one),
- are retained because CPython documents them as mandatory for this
  embedding pattern, **not** because a test here proves it.

We explicitly declined to write this up as "the hooks fixed a bug", which
would be false. **Is retaining them still correct given they demonstrably
change nothing on our configuration?** Or should the honest position be
"implement them, and treat the 6.8–11.3× result as valid for the
single-threaded case only, with contention explicitly unmeasured"?

### 2.3 Error diagnostics: is `PyErr_Print()` acceptable?

You said diagnostics must be useful but **must not be mixed into the framed
result channel**. Our `fr_udf_call()` currently calls `PyErr_Print()`,
which writes a full traceback to **stderr**. stdout is the framed channel;
stderr is not. We believe this satisfies your constraint, but it has two
consequences we would rather you rule on than discover later:

1. A failing batch emits a full traceback per call. Under many failed
   batches that is a lot of output, interleaved across workers.
2. The traceback goes to whatever stderr the worker inherited, which under
   the launcher is not necessarily the user's terminal.

Alternatives we considered: `PyErr_Fetch` + normalize + format into our
own one-line message, suppressing the traceback; or honouring a
verbosity/quiet flag. **Is `PyErr_Print()` to stderr acceptable as-is, or
should this be a structured fetch instead?** If the latter, is per-batch
traceback suppression the right default?

## 3. One gap we found while implementing your spec, and fixed

You listed what `FR_UDF_ERR` must cover, including **non-callable
attributes**. We did not have that case. `mod:CONSTANT` produced a bare
`TypeError: 'int' object is not callable` from inside the call machinery,
naming neither module nor attribute. Now:

```c
if (!PyCallable_Check(fn)) {
    set_error("%s.%s is not callable (%s)", module, attr, Py_TYPE(fn)->tp_name);
    ...
}
```

→ `call FAILED: myudf.NOT_CALLABLE is not callable (int)`, with a test.

## 4. Re-measured with hooks, as you required

| children | post-fork | pre-fork | speedup | failures |
|---|---|---|---|---|
| 1 | 0.0118 s | 0.0010 s | 11.29× | 0 |
| 2 | 0.0099 s | 0.0012 s | 8.22× | 0 |
| 4 | 0.0097 s | 0.0014 s | 6.93× | 0 |
| 8 | 0.0123 s | 0.0018 s | 6.81× | 0 |

Respawn probe: still CLEAN. Negative control (in-process dirt must be
detected): still detects it, so the CLEAN verdict is falsifiable.

## 5. Approval status, stated honestly

**Conditions are still OPEN.** No launcher integration code and no
`fr_py_worker_udf_loop` exist yet, so the parity tests you required across
all four existing loops have nothing to test. We have not started
writing them, and we are not claiming partial credit for them.

Also unchanged: verified on CPython 3.14.7 only; the 3.10–3.15 matrix is
recorded as deferred scope, not as passing.

## 6. What we need from you

Three specific answers, ideally one line each:

1. **§2.1** — is our "that was our bug, not a tainted measurement"
   reading correct?
2. **§2.2** — given the hooks demonstrably change nothing here, keep them
   (documented as insurance) or drop them? And do you agree the
   single-threaded caveat should be stated on the 6.8–11.3× figure?
3. **§2.3** — `PyErr_Print()` to stderr: acceptable, or switch to a
   structured `PyErr_Fetch` with suppressed per-batch traceback?

Plus any correction to §2.3's premise that stderr is genuinely not the
framed channel under the launcher. If we are wrong about that, our
constraint reading is wrong and the answer to Q3 changes.