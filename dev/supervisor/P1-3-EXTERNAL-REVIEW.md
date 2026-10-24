# External review request — P1-3: Python UDF integration call site

*This is a standalone request. You have no repository access and no prior
context; everything you need is below. Please reason from the facts as
given and say where you think they are wrong or insufficient.*

---

## 1. What we are building

`forkrun` is a batch/stream processing engine. A C core (`forkrun_ring.c`)
manages ingestion, batch claiming, retries, poison detection and ordering.
Frontends drive it. The Python frontend runs batches through user-supplied
callables ("UDFs") inside worker processes, under supervision (a dead
worker is respawned onto the same worker id, up to a poison threshold).

The C core is **frozen** — we will not change it. The Python shim
(`_shim.c`, which textually includes the core so its statics are visible)
and the launcher (`forkrun_cleanroom.c`) are ours to change.

**Already built and measured:** `fr_udf.c`/`fr_udf.h`, a per-minor shared
object that embeds a deliberately-isolated CPython interpreter
(`isolated=1`, `use_environment=0`, `site_import=0`, `safe_path=1`), takes
an explicit validated list of import roots, and exposes:

```
int  fr_udf_init(const char *const *roots, int nroots);
int  fr_udf_call(const char *module, const char *attr,
                 const char *input, size_t len, char **out, size_t *out_len);
int  fr_udf_finalize(void);
/* FR_UDF_OK / FR_UDF_NO_RESULT (returned None) / FR_UDF_ERR */
```

It works. The remaining work is **integration**: getting the interpreter
initialised at the right time and the per-batch call placed correctly.

---

## 2. Constraints we have established by measurement

1. **The helper cannot be loaded into a process that already runs
   Python.** It calls `Py_InitializeFromConfig`; doing that on a live
   interpreter is undefined and core-dumps in practice. The host must
   therefore be a process with no interpreter. The launcher (a C program)
   qualifies; the Python parent does not.

2. **Pre-fork initialisation works and is 4–8× faster.** We measured both
   candidates with a driver that verifies every child's outcome before
   printing a timing:
   - *Pre-fork*: `fr_udf_init` once in the parent before `fork()`;
     children inherit the initialised interpreter. Correct, and 4–8×
     faster across 1/2/4/8 children.
   - *Post-fork*: each child initialises its own. Correct, ~4–8× slower.

3. **Pre-fork safety rests on a precondition.** CPython's runtime is not
   fork-safe in general. It works here only because the launcher is
   single-threaded at the moment it forks. This is stated in the header as
   a precondition, not assumed.

4. **A respawned generation does not inherit dirty interpreter state.**
   Measured: one generation dirties a module global and dies without
   cleanup; the next generation does not see it, because it is a fresh
   fork of the launcher, which still holds the pristine interpreter. (The
   probe ships with a negative control that must detect dirt in a single
   process, so the CLEAN verdict is falsifiable rather than vacuous.)

---

## 3. The existing architecture you need to reason about

### 3.1 The launcher already dlopens, pre-fork

`forkrun_cleanroom.c` `main()` does `dlopen(libforkrun_python.so)` and
resolves worker-loop symbols **before any fork**; children inherit the
handle. Its own comments state the rule:

> `spawn_wid`: "Takes the pointer the parent already resolved: dlopen after
> fork is a classic post-fork hazard."
>
> `g_poison_stats_fd`: "Set once in `main()` before any fork so it is
> inherited."

The launcher also does a pre-fork `dlopen`+`fork` probe of *user* plugin
libraries (around line 672–686).

### 3.2 But the plugin worker loop deliberately dlopens POST-fork

`fr_py_worker_plugin_loop` in the shim takes `(path, func_name)` **strings**
and calls `fr_py_plugin_ensure(path, func_name)`, which dlopens in the
child. Its header comment explains the choice:

> "(path, func_name) strings, NOT a raw function pointer: the child dlopens
> itself post-fork via fr_py_plugin_ensure (same fork-safety rule as
> `_plugin.load_plugin` — **dlopen without calling is fork-safe; a
> parent-handle pointer would dangle on dlclose and entangle refcounts
> across fork**)."

This is the tension. The launcher uses parent-dlopen-then-fork for *our*
substrate; the worker loop uses child-dlopen for *user* plugins, and gives
a reason that mentions `dlclose` and refcount entanglement.

### 3.3 There is one worker loop per execution mode, differing only in "invoke"

All loops share the same primitives — `fr_py_claim`, `fr_py_complete`,
`fr_py_escrow_deposit`, `fr_py_abort` — and differ only in how a batch's
output is produced:

| loop | invoke step |
|---|---|
| `fr_py_worker_splice_loop` | `sendfile` the body out of the ingress spool |
| `fr_py_worker_plugin_loop` | `fr_py_plugin_invoke` — tokenize argv, dlopen plugin, capture stdout |
| `fr_py_worker_spawn_loop` | `fr_py_exec_spawn` — `posix_spawnp` a subprocess, capture stdout |

The shape of each is identical: claim → (poisoned? warn+ack) → (zero-length
sentinel? ack) → invoke → on success `fr_py_complete`, on failure honour
`on_error` (0 retry/escrow, 1 skip/ack, 2 fail-fast/abort).

### 3.4 The UDF is not shaped like a plugin

- A **C plugin**: input arrives as tokenized argv + a RAW memory window;
  output is whatever it writes to stdout, captured into a memfd and framed
  by `fr_py_emit_record`.
- A **Python UDF**: input is one `bytes` object; the return value is a
  `bytes` (or `None`).

So the UDF needs a genuinely different invoke body
(`fr_py_call(module, attr, bytes) -> bytes|None`), not a variant of
`fr_py_plugin_invoke`.

---

## 4. The question we want reviewed

**Should the UDF be (A) a fifth worker loop, `fr_py_worker_udf_loop`,
mirroring the existing ones with a different invoke body — and should its
interpreter be initialised pre-fork in the launcher, diverging from the
plugin loop's post-fork dlopen — or (B) something else?**

Specifically, we want your judgement on three points:

**Q1. Is the plugin loop's post-fork-dlopen rule about (i) handle/refcount
safety — which may not arise if nothing ever calls `dlclose` — or (ii) a
general fork-safety law that should bind any `dlopen`'d code regardless?**
This decides whether pre-fork `fr_udf_init` is legitimate or violates
house style. Note the precedent cuts both ways: our own substrate is
parent-dlopen-then-fork, while *user* plugins are child-dlopen. If the
distinction is "our controlled code vs. user code that might `dlclose`",
does that reasoning extend to the UDF helper?

**Q2. Is a fifth loop the right shape, or should the invoke step be
parameterised into the existing plugin loop?** For context: a shared
invoke would mean threading a "which kind of invoke" discriminator
through a function that already takes 12 parameters, one of which is
`path, func_name` — both meaningless for a UDF.

**Q3. What should happen on a UDF that raises?** The existing
`on_error` contract (0 retry / 1 skip / 2 fail-fast) is defined in terms
of plugin failures, which are payload errors. A raising UDF is closer to
a worker crash. Should it be forced onto the normal death path (so
supervision handles it identically to a segfault, giving escrow/retry and
eventual poison), or is there a reason to handle it in-process instead?

---

## 5. Our current recommendation (please challenge it)

**Option A — fifth loop + pre-fork init.** `main()` in the launcher
resolves and `dlopen`s the helper and calls `fr_udf_init` once before any
fork; workers inherit. Add `fr_py_worker_udf_loop`, mirroring the existing
loops, swapping `fr_py_plugin_invoke` for `fr_py_udf_invoke`.

Reasons:
1. It is the only option that gets the measured 4–8× win.
2. It follows the launcher's own documented pattern for a handle we own.
3. It matches the codebase's established "one loop per execution mode,
   identical shape, different invoke" convention.
4. It needs no frozen-core change.

We are least sure about Q1, and we specifically want to know whether
diverging from the plugin loop's stated rule is defensible or whether we
are rationalising a 4–8× number into a rule the codebase states
explicitly.

---

## 6. What we have deliberately not done

- No launcher or shim integration code has been written; this is the
  design decision only.
- Verified on CPython 3.14.7 only. The 3.10–3.15 matrix cannot be built in
  our environment (single interpreter, no network, no container runtime).
  This is recorded as deferred scope, not as a passing result.
- We have not measured the cost of the fifth loop itself (compile size,
  maintenance divergence between near-identical loops), only the
  pre/post-fork difference.

## 7. Please be concrete

Useful answers look like: "Option A is right because …, but do X
differently", or "Q1 resolves to (i) so pre-fork is fine, and here is the
argument", or "you are missing a case: …". Flag anything in §2 or §3 you
think is factually wrong or under-specified, and any failure mode we have
not asked about.