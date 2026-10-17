# Cleanroom launch architecture — decision report

**Work order:** Python/Bash parity, source-of-truth audit, duplication
reduction — Phase B.
**Branch:** `NEW/REFACTOR4.2`.
**Scope of this document:** decision only. No launch-backend or
environment-contract change was made. One bounded, independent finding
(§6) was implemented, because it required no architectural decision.

---

## 1. The discrepancy

`DOCS/CLEANROOM_DESIGN.md` proposes this topology, and explains the
motivation:

```
  user's Python process          launcher (small, post-exec)
  (may be 5 GB RSS)                    |
       |                               +-- fr_py_init()   <- state created HERE
       |  posix_spawn                      |
       |  (CLONE_VM|CLONE_VFORK,           +-- fork x N workers  <- cheap: ~0.27ms
       |   so no page-table copy)          +-- fork scanner/fallow/ingest
       |                               +-- drain -> result fd
       +<-- results on result fd
```

> `posix_spawn` uses `CLONE_VM | CLONE_VFORK`, so the spawn itself does
> not copy the page table at all. […] One exec, then N cheap forks. That
> is the entire win.

**The implementation uses `os.fork()` followed by `os.execv()`**, at both
launch sites:

* `_execute_cleanroom()` — `run.py`: `pid = os.fork()` … `os.execv(launcher, argv)`
* `_execute_cleanroom_stream()` — `run.py`: `launch_pid = os.fork()` … `os.execv(launcher, argv)`

`posix_spawn` **does** appear in the tree — `_spawn.py` and `_worker.py`
use `posix_spawnp` for the `mode="spawn"` PAYLOAD, i.e. to run the user's
external command once per batch inside the C spawn loop (`_spawn.py:4`,
W-PY13). That is a different question from this one: the payload is
spawned *from a worker inside the launcher*, while the launcher itself is
spawned *from the user's Python parent*. No `posix_spawn` is used to start
the cleanroom launcher.

### 1.1 Is this a violation, or an unfinished design item?

**It is an unfinished design item, and the design document says so
itself.** Its own delivery plan (§"Delivery plan") is:

> 1. Design (this file).
> 2. Launcher PoC: `posix_spawn` + `dlopen` + `fr_py_init` + fork N
>    workers, **with the fork tax measured. That number decides whether
>    the full integration is worth its risk.**
> 3. **Full integration behind the flag only if the PoC pays.**
> 4. Re-run the isolated benchmark with the launcher on and off, so the
>    delta is published rather than hidden.

Step 2 asks for a *measurement* to gate step 3. No such PoC, measurement,
or recorded decision exists in the tree, and `tools/gen_idl.py`-style
evidence of a reverted experiment does not exist either.

**Classification: unresolved architectural question — a design item whose
own gate was never evaluated.** Not a correctness defect, and not a
contract the shipped code promised and broke. Recording it as "the
implementation ignored the design" would be wrong; recording it as "no
action needed" would leave the design permanently misleading.

### 1.2 The design text's mechanism claim is CORRECT — a correction withdrawn

An earlier draft of this report "corrected" the design's
"`posix_spawn` uses `CLONE_VM | CLONE_VFORK`" as imprecise, on the
grounds that glibc implements `posix_spawn` on `vfork(2)`. **That was
wrong, and the correction is withdrawn.** The design document was right.

glibc's own source says so in its first comment
(`sysdeps/unix/sysv/linux/spawni.c`):

> The Linux implementation of posix_spawn{p} uses the clone syscall
> directly with CLONE_VM and CLONE_VFORK flags and an allocated stack.

and the clone flags it builds are:

```c
.flags = ... | CLONE_CLEAR_SIGHAND | CLONE_VM | CLONE_VFORK,
```

`CLONE_VFORK` suspends the calling thread until the child `execve`s or
exits, which is the property the design relies on. glibc does not invoke
the `vfork(2)` syscall for this path, but the flags produce vfork-like
shared-address-space semantics — which is what matters.

**How the error happened, because it is the same shape as the F3 error.**
I ran `strings libc.so.6 | grep vfork`, saw `__vfork` and
`__libc_vfork`, and concluded `posix_spawn` used them. Those symbols
exist in libc for other reasons — `vfork(2)` is used elsewhere — and
their presence says nothing about which mechanism the spawn path takes. I
treated weak evidence as conclusive without opening the source.

That is the second time in this work order I gathered evidence consistent
with a hypothesis and stopped. The rule that would have caught it both
times is the same one: open the file that decides the question.
(`grep raise_fd_limit forkrun_cleanroom.c` for F3; `spawni.c` here.)

---

## 2. What the current implementation actually costs

`fork()` copies page tables. For the cleanroom's stated motivation — "the
user's Python process (may be 5 GB RSS)" — that is the whole cost being
avoided.

**This has not been measured.** Per the performance policy in the work
order, no claim is made here about whether `posix_spawn` would actually
be faster; §5 specifies the protocol that would establish it. What is
measurable today is the shape of the cost: `fork()` cost scales with the
parent's mapped memory, so the penalty is largest exactly in the case the
design exists to serve, and near zero for the small parents a benchmark
process usually has — which is why a naive benchmark would report "no
difference" and conclude wrongly.

---

## 3. Alternatives, and what each would actually cost

### 3.1 Keep `fork()` + `execv()` (status quo)

**Pros.** No behavioural risk. The child currently runs Python code
between fork and exec (`os.close(rr)`, `_raise_nofile_to_hard_limit()`),
which is trivially expressible here and awkward in `posix_spawn`.
Startup-failure reporting is exact: the child `_exit(127)`s, the parent
reads a real wait status.

**Cons.** Page-table copy proportional to parent RSS — the design's
stated motivation.

### 3.2 `os.posix_spawn()`

Python's API (verified on this host) offers
`POSIX_SPAWN_OPEN`, `POSIX_SPAWN_DUP2`, `POSIX_SPAWN_CLOSE` and
`POSIX_SPAWN_CLOSEFROM` file actions, plus `close_fds`, `setsigdef` and
`setsigmask` parameters. Each has to be checked against what this launch
actually needs.

### 3.3 `os.posix_spawn` with `POSIX_SPAWN_CLOSEFROM`

Available on this Python/glibc. It can close everything from N upward,
which combined with explicit `DUP2` of the wanted descriptors would
reproduce the scrub-then-exec discipline.

---

## 4. Compatibility requirements, item by item (work order §4.2)

### 4.1 Descriptor inheritance and closure

The current child closes `rr` and inherits everything else the parent
holds at fork time. The cleanroom design's whole premise is that the
launcher inherits **only** the source fd and the result fd.

**CORRECTED.** An earlier draft said `posix_spawn` "does not inherit the
parent's fd table the way `fork` does; it constructs the child's
descriptors from file actions." That misstates POSIX. The child's initial
descriptor set IS the parent's open descriptors, then modified by the
specified file actions and close-on-exec disposition. `posix_spawn` does
**not** hand you an allowlist.

The practical conclusion is unchanged, but it must be reached correctly:
producing a *deliberate* allowlist is work, and the inventory is what has
to be done first. Concretely:

* Every job descriptor (`src_fd`, result `res_fd`, `errfd`, `stats_fd`,
  and the poison-index memfd added this cycle) must be enumerated and
  confirmed **inheritable**. glibc's `spawni.c` shows the available
  actions — `open`, `dup2`, `close`, `closefrom` — and a `dup2` action
  whose source and destination are equal clears `FD_CLOEXEC`, which is
  often cheaper than re-opening.
* Everything else must be made non-inheritable. `posix_spawn`'s
  `close_fds=True` closes descriptors above the spawn action range rather
  than applying an arbitrary allowlist, so a true allowlist still needs
  deliberate `closefrom`/`close` actions.

Miss one descriptor and the launcher degrades to a fallback rather than
failing loudly. That remains the largest correctness surface in the
change — reached by inventory, not by re-opening everything.

### 4.2 Argument-vector fidelity

`os.execv(launcher, argv)` passes `argv` verbatim. `os.posix_spawn(path,
argv, env)` does the same — both are exec-family argument vectors, and
neither performs shell parsing. **No fidelity difference.** Worth stating
because `_validate_spawn_argv()` exists and one might assume a
re-quoting hazard; there is none, and no argument validation needs to
change.

### 4.3 The child-side code that would have to be replaced

**CORRECTED.** An earlier draft of this section argued that the
child-side descriptor-limit raise has no `posix_spawn` equivalent, making
a backend swap awkward. **That argument was void, and it is withdrawn.**

The launcher raises its own soft `RLIMIT_NOFILE` to the hard limit before
doing any work:

```c
static void raise_fd_limit(void) {          /* forkrun_cleanroom.c:461 */
    struct rlimit rl;
    if (getrlimit(RLIMIT_NOFILE, &rl) == 0 && rl.rlim_cur != rl.rlim_max) {
        rl.rlim_cur = rl.rlim_max;
        (void)setrlimit(RLIMIT_NOFILE, &rl);
    }
}
```

called from `main()` at `forkrun_cleanroom.c:1727`, immediately before
`dlopen()` at `:1729` — ahead of any memfd, pipe or worker. This predates
the current work order and is present in the baseline commit.

So there is **no rlimit migration cost**, in either direction. The
launcher owns the limit whether it is started by `fork()+execv()` or by
`posix_spawn`. Remove this from the cost list.

### 4.4 `vfork` semantics constrain the child

glibc implements `posix_spawn` on `vfork`. Under `vfork` the child
**shares the parent's address space** until `exec`. The child may not
modify memory, and calling anything non-async-signal-safe before `exec`
is undefined. This constrains what any shim between spawn and exec may do
— which interacts directly with §4.3.

### 4.5 Startup failure and exit status

Today: child `_exit(127)` on any pre-exec failure; parent reads a real
wait status, and a missing launcher is detected before the fork by
`_cleanroom_launcher_path() is None`.

With `posix_spawn`, a spawn-time failure surfaces as an
`OSError`/`FileNotFoundError` **in the parent** rather than as a child's
exit 127. That is arguably *better* — the failure is attributable rather
than a status code — but it is a different contract, and every existing
test that distinguishes "launcher missing" from "launcher failed" would
need to be re-read against it.

### 4.6 Source-consumption boundaries

`_execute_cleanroom` refuses to retry in-process when the source is a
descriptor whose read position the launcher shares, because a retry would
resume mid-input. **This logic is entirely independent of how the
launcher was started** and would be untouched by a backend swap.

### 4.7 Multithreaded parent

**CORRECTED.** An earlier draft called this hazard "currently
theoretical" on the grounds that the launch path starts no threads
itself. That is not a valid inference and the characterisation is
withdrawn.

`forkrun` is an importable **library**. Threads it does not create are
not evidence about the process it is called from — the calling
application may already run a thread pool, a timer, a logging handler or
an async runtime's executor. `os.fork()` from such a process is the
documented hazard: only the forking thread survives in the child, any
lock held by another thread at fork time stays locked, and the CPython
runtime itself warns at `fork()` sites for this reason.

This is not a theoretical concern. It is the strongest remaining
argument **for** `posix_spawn`, and it is a correctness argument rather
than a speed claim: `vfork`/`posix_spawn` avoids the problem structurally
rather than relying on the parent happening to be idle.

It is stated here as an argument, not as evidence of a defect. No
failure has been reproduced from a threaded caller.

### 4.8 Both launch paths

`_execute_cleanroom` and `_execute_cleanroom_stream` are structurally
different (one passes a source fd, the other two pipes) and would both
need converting. The streaming path's producer branch has since been
removed (§D.4), so both are now plain "dup these fds, exec".

---

## 5. Benchmark methodology (to be run BEFORE any implementation)

Per the work order, established now so a candidate is not judged by a
method chosen to favour it.

* **Interleaved A/B**, alternating arms, discarding warmup — the
  discipline already used by `benchmarks/bench_cleanroom.py` and
  `bench_harness.py`. Machine drift must hit both arms.
* **Parent RSS as the independent variable**, not batch size. The claim
  is specifically about page-table copy, so the sweep must span the range
  that matters: **0 MB, 256 MB, 1 GB, 2 GB, 5 GB** ballast in the parent.
  A sweep at low ballast will report "no difference" and is worthless for
  this decision.
* **Identical workload** both arms: same corpus, same `workers`, same
  `mode="plugin"`, same `order="index"`.
* **Two timings, reported separately, never merged:** *launch latency*
  (fork/spawn → launcher ready) and *end-to-end* (full `map()` call).
  Only the first is what the change targets.
* **Repetitions**: ≥ 30 paired passes per RSS point after warmup, with
  medians reported alongside means, because startup timing is skewed.
* **Exact-output guard**, refusing to report a number for wrong output.
* **Same build, same launcher binary**, switching only the spawn backend.

**Decision rule fixed in advance:** the backend changes only if the
launch-latency win is large enough to matter at 1 GB+ parent RSS *and*
the descriptor-enumeration change ( §4.1) can be made provably
equivalent. A win at low RSS is not evidence.

---

## 6. The finding previously implemented here — WITHDRAWN

An earlier draft of this report recorded a "confirmed defect, FIXED": the
launcher did not receive the hard descriptor limit. **That was a false
positive and the change has been reverted** (see §4.3).

The error is worth recording because it is a specific, repeatable shape:
I observed that `run.py` had no `RLIMIT_NOFILE` reference, read a
sentence in `CLEANROOM_DESIGN.md` ("which the launcher should do too") as
an unmet requirement, and never checked whether the launcher already
satisfied it. It did, in C, before `dlopen`.

Two further reasons the change was wrong independently of being
redundant:

* The test I wrote could not have detected the failure it claimed to
  address. It wrapped the launcher in a shell that recorded
  `RLIMIT_NOFILE` and then `exec`ed the real binary, so it measured the
  limit **before** the C launcher raised its own. It demonstrated that my
  helper ran, not that anything was broken.
* The helper performed `import resource` and Python work between
  `fork()` and `execv()` — precisely the pre-exec activity worth
  minimising when forking from a possibly-multithreaded host (§4.7).

**Lesson recorded rather than quietly fixed:** checking the place I
expected to find a defect is not a test of whether it exists there.

## 7. Environment contract — a stated contract that is violated

**Status revised from "low exposure" to "OPEN — the contract is stated
and not met".** An earlier draft of this section argued the exposure was
small because `forkrun_cleanroom.c` reads exactly one environment
variable (a test-only hook) and all real configuration crosses as argv.
**That inference was wrong, in three ways.**

### 7.1 The contract is stated, and it is not met

`CLEANROOM_DESIGN.md` §"Configuration contract":

> The launcher must not inherit the parent's environment wholesale.

Both Python launch sites call `os.execv()`, which inherits the entire
parent environment. The Bash frontend satisfies the contract by
construction — `exec -c` with `--norc --noprofile` plus explicit
`LC_ALL=C`, `set +m`, `shopt -s extglob`.

So this is not an open design question. It is a **documented requirement
that the implementation does not meet**, and it should be tracked as such
rather than described as a consideration.

### 7.2 Auditing the launcher's own `getenv` misses the actual exposure

The "low exposure" argument counted `getenv()` calls inside the launcher.
That misses two real consumers:

* **User code runs in the launcher.** `map-spawn` and `map-udf` are
  served routes (`_CLEANROOM_ROUTES`). A spawned command and a UDF module
  are the user's own code and can read whatever they like from the
  environment. The launcher's silence about the environment says nothing
  about what the payload does with it.
* **The dynamic loader reads it before `main()` runs.** `LD_LIBRARY_PATH`,
  `LD_PRELOAD` and friends are consumed by `ld.so` during `exec`, before
  any of the launcher's own code executes. No amount of auditing the
  launcher's source can see those effects.

The correct question is not "what does the launcher read" but "what
should cross the boundary".

### 7.3 Do not simply clear it

Clearing the environment is the obvious move and the wrong one. A
`mode="spawn"` payload is a user command that very plausibly depends on
`PATH`, and a UDF module may need `PYTHONPATH` to be importable at all.
The Bash frontend's answer is an explicit, user-controlled list
(`FORKRUN_EXTRA_VARS` / `_EXTRA_FUNCS` / `_EXTRA_SETUP`). Python needs
an equivalent answer, and it needs one that is a deliberate compatibility
decision rather than an accident of `execv`.

### 7.4 What the follow-up should compare

Before choosing a contract, measure all four behaviours — they are
currently different and the difference is undocumented:

1. Bash cleanroom (reconstructed environment),
2. Python in-process (caller's environment, unmodified),
3. Python cleanroom with a C plugin (inherits wholesale),
4. Python cleanroom with `mode="spawn"` / `mode="udf"` (inherits
   wholesale, and the payload can observe it).

The question to answer is which of these a user could tell apart today,
and which differences are acceptable to keep. That comparison is
investigation, not redesign, and nothing here authorises changing the
launch until it is done.

## 8. Recommendation

**Retain `fork()` + `execv()` for now. Do not implement `posix_spawn` in
this work order.**

Reasons, in order of weight:

1. **The design's own gate was never evaluated.** Step 2 of its delivery
   plan asked for a measured PoC whose result decides step 3. Running the
   PoC is the correct next action, not adopting or rejecting the topology
   by argument.
2. **The concrete claim is unmeasured.** No performance statement should
   be made from an unrun benchmark. §5's protocol — in particular the
   parent-RSS sweep — must run first, or the result will be "no
   difference" measured at the wrong ballast and the question will appear
   settled.
3. **A deliberate descriptor allowlist is work that has not been done.**
   §4.1 (corrected): `posix_spawn` does *not* hand you an allowlist —
   POSIX gives the child the parent's open descriptors modified by file
   actions. Producing an intentional one means inventorying which job
   descriptors must be inheritable and closing everything else with
   `closefrom`/`close` actions. Miss one and the launcher degrades to a
   fallback instead of failing loudly.
4. **The threaded-parent hazard is real and unresolved.** §4.7:
   `forkrun` is an importable library, and `fork()` from a caller's
   threaded process is a documented hazard. `posix_spawn` addresses it
   structurally — which is an argument *for* the change and part of why
   the benchmark should be run rather than the question left open.
5. **Startup-error semantics would change.** §4.5: today a missing or
   unlaunchable launcher is detected before the fork and a pre-exec
   failure surfaces as the child's exit 127. With `posix_spawn` it
   surfaces as an exception in the parent. That is arguably better, but
   it is a different contract, and the tests that distinguish "launcher
   missing" from "launcher failed" would need re-reading.

**No rlimit cost exists** and it is not part of this list — the launcher
raises its own `RLIMIT_NOFILE` before `dlopen` (§4.3).

**This work order produced no defect in this area.** The one finding it
initially reported here, F3, was a false positive and has been withdrawn
(§6).

**What should happen next**, as a separate, explicitly-scoped work order:
run the §5 benchmark against a prototype; report launch latency at 0/256
MB/1 GB/2 GB/5 GB; and only then decide. If the win is real, §4.1's
descriptor inventory is the design work, and it is worth doing
deliberately.

**Unchanged and explicitly out of scope:** the engine, the ring, the
supervision models, and the existing cleanroom eligibility envelope. None
of this changes what the cleanroom *is*.
