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

### 1.2 One factual correction to the design text

The claim "`posix_spawn` uses `CLONE_VM | CLONE_VFORK`" is imprecise.
glibc implements `posix_spawn` on **`vfork(2)`** (`__vfork` /
`__libc_vfork` are present in the libc on this host, glibc 2.43), not on
`CLONE_VM`. The *conclusion* — no page-table copy at spawn — is correct,
because `vfork` suspends the parent and shares the address space. The
mechanism named in the document is wrong, and matters for a reason §3.4
expands on: `vfork` semantics constrain what the child may do.

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

`posix_spawn` does not inherit the parent's fd table the way `fork` does;
it constructs the child's descriptors from file actions. That is
*stronger* isolation and is arguably what the design wanted — but it
changes which descriptors must be named explicitly, and **every** job fd
(`src_fd`, result `res_fd`, `errfd`, `stats_fd`, the poison memfd) would
have to be enumerated and re-opened or dup'd. Miss one and the launcher
degrades to a fallback. This is the single largest correctness surface
in the change.

### 4.2 Argument-vector fidelity

`os.execv(launcher, argv)` passes `argv` verbatim. `os.posix_spawn(path,
argv, env)` does the same — both are exec-family argument vectors, and
neither performs shell parsing. **No fidelity difference.** Worth stating
because `_validate_spawn_argv()` exists and one might assume a
re-quoting hazard; there is none, and no argument validation needs to
change.

### 4.3 The child-side code that would have to be replaced

This is the concrete blocker for a drop-in swap:

```python
launch_pid = os.fork()
if launch_pid == 0:
    os.close(rr)
    _raise_nofile_to_hard_limit()      # added by §6
    os.execv(launcher, argv)
```

`_raise_nofile_to_hard_limit()` is arbitrary child-side code: it calls
`resource.setrlimit()`. `posix_spawn` has **no** rlimit hook. Porting it
would mean either (a) setting the limit in the PARENT before the spawn
and restoring it after — which changes the calling process's descriptor
budget for the duration, affecting every other run in that process; or
(b) having the launcher raise its own limit at startup, which moves the
fix from the frontend into `forkrun_cleanroom.c` and changes the
launcher's contract.

**Neither is free, and both are strictly worse than the current child-side
call.** This is the finding that most constrains the decision.

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

`fork()` from a multithreaded process is a known hazard, which this
codebase already documents (`run.py` notes CPython's fork warning at the
`os.fork()` sites). The plain cleanroom path has no explicit threads at
launch time, so the hazard is currently theoretical — and `posix_spawn`
is the textbook mitigation. That is a genuine argument **for** §3.2, and
it is the strongest one, because it is a correctness property rather than
a speed claim.

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

## 6. The one finding implemented (no architectural decision needed)

**The launcher did not receive the hard descriptor limit.**

`CLEANROOM_DESIGN.md`, on the Bash cleanroom:

> It also raises `ulimit -n` to the hard limit in the cleanroom, which the
> launcher should do too.

`frun.bash` does exactly this — `ulimit -n $(ulimit -Hn)` is the first
line of the cleanroom source (`FORKRUN_FRUN_SRC`, `frun.bash:192`). The
Python launch path had **no** `RLIMIT_NOFILE` reference at all.

Consequence: a launcher started under a low soft limit hits `EMFILE`
partway through a run, and that failure does not look like what it is —
it surfaces as an exec error or a truncated result with nothing naming
descriptor exhaustion.

Implemented as `_raise_nofile_to_hard_limit()`, called in the forked
child between fork and execv at **both** launch sites. Only the *soft*
limit moves (never the hard limit), it runs child-side so the parent is
untouched, and failure is non-fatal.

This is implemented rather than merely recommended because it required no
decision about the launch backend: it is correct under `fork()+execv()`
today and would be the launcher's own responsibility under
`posix_spawn` (§4.3). **It is therefore not evidence for or against
either backend.**

Mutation-verified: removing the raise makes the test observe the soft
limit (64) instead of the hard limit (4096). Covered by
`python/tests/test_cleanroom_nofile.py`.

---

## 7. Environment contract (work order §4.3) — findings, not a decision

The work order asks what should cross the boundary. Evidence gathered:

* **Bash reconstructs.** `exec -c` with `--norc --noprofile`, plus
  explicit `LC_ALL=C`, `set +m`, `shopt -s extglob`, `_FR_IN_CLEANROOM=1`
  and a `ulimit -n` raise. `FORKRUN_EXTRA_VARS` / `_EXTRA_FUNCS` /
  `_EXTRA_SETUP` are the *only* documented way to carry state in.
* **Python inherits everything.** `os.execv()` inherits the full parent
  environment; `run.py` sets nothing before either launch.

**How much this matters is small, and that is the finding.** The launcher
reads exactly **one** environment variable:

```
$ grep -oE 'getenv\("[A-Z_]+"\)' forkrun_cleanroom.c | sort -u
getenv("FORKRUN_TEST_BREAK_DRAIN_WAKEUP")
```

That is a test-only hook. All real configuration crosses as **argv**.
So the current exposure is: a caller's stray `FORKRUN_*` variable cannot
affect the launcher today, because the launcher reads none — a safety
property that is **accidental rather than designed**, and would be
silently lost the moment the launcher grows its first `getenv`.

**Recommendation, not implemented:** state the contract explicitly rather
than leaving it to chance — either document "the launcher inherits the
environment and deliberately reads nothing from it, so configuration
crosses as argv", or define an allowlist and use `posix_spawn(env=...)`.
This is documentation-level today precisely because nothing reads
anything; it becomes a real decision the moment `getenv` is used.

---

## 8. Recommendation

**Retain `fork()` + `execv()` for now. Do not implement `posix_spawn` in
this work order.**

Reasons, in order of weight:

1. **The design's own gate was never evaluated.** Step 2 of its delivery
   plan asked for a measured PoC whose result decides step 3. Running the
   PoC is the correct next action, not adopting or rejecting the
   topology by argument.
2. **It is not a drop-in swap.** §4.3: the child-side rlimit raise has no
   `posix_spawn` equivalent, and both alternatives are worse. §4.1: every
   job descriptor would need explicit re-opening, which is the largest
   correctness surface in the change and the easiest place to introduce a
   silent fallback.
3. **The concrete claim is unmeasured.** No performance statement should
   be made from an unrun benchmark, and §5's protocol — in particular
   the parent-RSS sweep — must run first or the result will be "no
   difference" measured at the wrong ballast.
4. **The one real defect found (§6) is fixed** and is backend-neutral.

**What should happen next**, as a separate, explicitly-scoped work order:
run the §5 benchmark against a prototype; report launch latency at 0/256
MB/1 GB/2 GB/5 GB; and only then decide. If the win is real, §4.1 and §4.3
are the design work, and they are worth doing deliberately.

**Unchanged and explicitly out of scope:** the engine, the ring, the
supervision models, and the existing cleanroom eligibility envelope. None
of this changes what the cleanroom *is*.
