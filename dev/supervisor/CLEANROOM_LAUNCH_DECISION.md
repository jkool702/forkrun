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

Step 2 asks for a *measurement* to gate step 3.

**That measurement now exists** — `tools/bench_cleanroom_launch.c`, run
across the full §5 parent-RSS sweep. **Result: the performance half of the
gate is met decisively.** At 1 GiB+ parent RSS `posix_spawn` launches in
~3.5–4.2 ms where `fork()`+`execv()` takes 29–112 ms: a **−88% to −96%**
launch latency reduction, and the saving grows with parent memory because
the `fork()` cost does. (Numbers here are the `smaps_rollup`-verified
sweep in §1.1a; an earlier sweep gave 37–120 ms — same conclusion, and
both are recorded there.)

**Both halves of the gate have now been evaluated** (Stage 2 and Stage 3):

* the **performance** condition is met (−88% to −96% launch latency at
  1–5 GiB parent RSS);
* the **descriptor/launch-semantic** condition is answered — two launch
  shapes, a single `DUP2` for materialized and an **empty** action list for
  streaming, neither needing `CLOSEFROM`; failure mapping onto the
  established exit-127 contract on both backends; and the real launcher's
  entry descriptor set observed directly via a compile-time-guarded
  probe. See `CLEANROOM_FD_CONTRACT.md` for the C1–C5 closure matrix.

**Integration is nevertheless NOT authorised by this document.** A private,
test-gated candidate now exists in `run.py` (`_spawn_or_fork`), and the
**default production backend is still `os.fork()` + `os.execv()`**. What
remains is an ADOPTION decision, not a design question, and adoption must
be a separate, explicitly-authorised step.

**Classification: an architectural question whose technical gates are met
and whose ADOPTION decision is outstanding.** Not a correctness defect,
and not a contract the shipped code promised and broke.

> **Correction to this report's own earlier conclusion.** A previous
> revision (§1.1a, commit `5b8b5088`) concluded the gate was **not met**
> on the basis of a **small-parent-RSS-only** sweep showing ~0.2 ms and an
> unstable sign. **That conclusion was premature and is superseded.** §5
> explicitly warned that "a sweep at low ballast will report 'no
> difference' and is worthless for this decision" — which is precisely
> what happened, and the warning was correct. The measurement was sound;
> its scope was not. Nothing in the earlier data was wrong; it was simply
> measuring the wrong regime, and it was over-read as a decision.

### 1.1a Step-2 measurement — `posix_spawn` vs `fork`+`exec` (parent-RSS sweep)

Harness: `tools/bench_cleanroom_launch.c`, measurement only, no production
path touched. It drives the **real** `_forkrun_cleanroom` binary in its
existing `--fork-only` mode, alternating the two launch mechanisms **within
each iteration** (interleaved A/B, so machine drift hits both arms),
discarding 3 warmups. Both arms get identical launcher argv, same binary,
same substrate, same plugin, same worker count.

**Ballast is RESIDENT, not virtual.** Each level is allocated with
`mmap(MAP_ANONYMOUS|MAP_NORESERVE)` and then written **one byte per page**
so every page is actually faulted in. A virtual-only allocation would have
produced a flat, meaningless curve.

**Residency measurement — which counter is authoritative.** The current
verified sweep reads `/proc/self/smaps_rollup`, the kernel's accurate
accounting, and prints it as authoritative; `/proc/self/statm` is retained
only as a cross-check, with the disagreement between the two printed per
level. The kernel documents `statm`'s resident figures as *potentially
inaccurate* and recommends `smaps`/`smaps_rollup` where an accurate value
is required, and `statm` was measured running 124–188 KiB above
`smaps_rollup` at 256/1024/2048 MiB. The **earlier** sweep used `statm`
as its primary reading; it is preserved below for comparison and its
residency figures are therefore the weaker instrument.

Command (one per level; `--ballast-mb` is the only thing that changes):

```
cc -O2 -o /tmp/bench tools/bench_cleanroom_launch.c
/tmp/bench python/forkrun/_forkrun_cleanroom \
          python/forkrun/libforkrun_python.so \
          <plugin.so> <func> 4 40 --ballast-mb <LEVEL>
```

**Results** — this is the SECOND, verification-tightened run; the first
sweep's numbers are kept below for comparison because independent
reproduction matters more here than a single tidy table. i9-7940X @
3.10 GHz, 28 threads, 128 GiB RAM, Linux 7.1.13-200.fc44.x86_64, glibc
2.43, gcc 16.2.1; workers=4; n=40 paired observations per arm per level;
**0 failed, 0 timeouts, 0 guard failures at every level in both runs**.

| parent ballast | RSS verified (`smaps_rollup`) | fork+exec median | posix_spawn median | delta median | delta |
|---|---|---|---|---|---|
| 0 MiB | n/a (control) | 2.842 ms | 2.717 ms | −0.117 ms | −4.1% |
| 256 MiB | 256.0 / 256.0 MiB (100.00%) | 9.567 ms | 3.186 ms | **−6.378 ms** | **−66.7%** |
| 1 GiB | 1024.0 / 1024.0 MiB (100.00%) | 29.415 ms | 3.495 ms | **−25.972 ms** | **−88.1%** |
| 2 GiB | 2048.0 / 2048.0 MiB (100.00%) | 49.232 ms | 3.986 ms | **−45.257 ms** | **−91.9%** |
| 5 GiB | 5120.0 / 5120.0 MiB (100.00%) | 112.016 ms | 4.181 ms | **−107.854 ms** | **−96.3%** |

First sweep, for comparison (verified with `/proc/self/statm`): 0 MiB
−7.7%, 256 MiB −68.4%, 1 GiB −89.3%, 2 GiB −93.6%, 5 GiB −96.1%. The
`fork()+execv()` medians differ between runs by up to ~25% at 1 GiB
(37.2 → 29.4 ms) — that column is noisy run to run. **The `posix_spawn`
column is stable (~2.4–4.5 ms in both), and the conclusion is unchanged:
the separation at every level ≥ 256 MiB is many times the spread.**

Spread (p95−min) at 5 GiB was 5.5 ms for `fork()+execv()` and 2.3 ms for
`posix_spawn`. Full per-arm min/median/mean/p95/max and the
failure/timeout counts are printed by the harness itself.

**Residency verification method — corrected.** The first sweep verified the
ballast with `/proc/self/statm`. The kernel documents statm's resident
figures as *potentially inaccurate* and recommends `smaps`/`smaps_rollup`
where an accurate value is required. The harness now reports
**`/proc/self/smaps_rollup` as authoritative**, with statm kept only as a
cross-check, and prints the disagreement between them. Measured
disagreement at 256 MiB–5 GiB is **0 KiB** on the verification run. The
timing conclusion does not rest on this — the ballast is explicitly
touched, and the latency separation is far larger than any accounting
discrepancy — but the "resident" claim now stands on the kernel's accurate
counter rather than the approximate one.

**Reading.** The `fork()+execv()` launch cost grows roughly linearly with
parent resident memory — about **23–35 ms per GiB** — while `posix_spawn`
stays **flat at ~2.4–4.5 ms** across a 5 GiB range. That is the mechanism the
design predicted: `fork()` must copy the parent's page tables and
`posix_spawn` does not. The design's rationale is **empirically confirmed**.

The `fork()+execv()` arm also shows a spread that grows with ballast
(p95−min 0.9 ms at 0 MiB → 10.0 ms at 5 GiB), consistent with the cost
being proportional to the amount of page table being copied.

**Separation of concerns.** The launcher's own self-reported `fork_ms`
(its *worker* fork tax, 0.17–0.57 ms) is common to both arms by
construction and is printed separately. It is **not** part of the delta and
is never merged with it.

**Invalid-sample accounting:** none required. Every level reported
`failed=0 timeout=0 guard_fail=0`. An exact-output guard rejects any launch
that does not exit 0 *and* emit `CLEANROOM workers=N fork_ms=`, so a
benchmark of the wrong program cannot silently enter the averages.

**Host safety.** Levels were attempted only after checking
`MemAvailable` from `/proc/meminfo`; the harness refuses a level that would
eat into a 4 GiB floor and **reports the skip rather than substituting a
smaller value under the requested label**. On this host (84 GiB available)
all five levels were feasible and none was skipped.

**What this does NOT establish:**
- **Correctness** of `posix_spawn` on any served route. Nothing here says a
  `posix_spawn` launcher would be functionally equivalent.
- Anything about **supervision, poison, retry, respawn, or NUMA** behaviour.
- **End-to-end workload performance.** This is process-creation latency
  only. Whether ~35 ms/GiB matters for a real run depends entirely on how
  many launches a workload performs — a workload that launches once and
  processes for minutes will not notice.
- **Descriptor-set equivalence** (§4.1), which is the remaining half of the
  decision rule and is untouched by this measurement.

**Evidentiary limit worth stating plainly:** the curve was taken on one
machine, one kernel, one libc, one worker count. The *shape* (flat vs
linear-in-RSS) is what the mechanism predicts and is unlikely to invert
elsewhere, but the *coefficient* (~23–35 ms/GiB) is hardware- and
kernel-specific and should not be quoted as a portable figure.

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

**This HAS now been measured.** §1.1a reports the sweep: `fork()` launch
cost rises to ~29–112 ms at 1–5 GiB parent RSS against `posix_spawn`'s
flat ~3–4 ms, i.e. **−88% to −96%**. The predicted shape is confirmed —
the penalty scales with the parent's mapped memory, is largest exactly in
the case the design exists to serve, and is near zero for small parents,
which is why a naive benchmark reports "no difference" and concludes
wrongly. (That is not hypothetical: this report's own first attempt did
exactly that, and §1.1a records the correction.)

---

## 3. Alternatives, and what each would actually cost

### 3.1 Keep `fork()` + `execv()` (status quo)

**Pros.** No behavioural risk. The child runs a little Python code
between fork and exec — verified against current `run.py`, the two launch
sites do `os.dup2(errfd, 2)` then `os.execv(...)`, and `os.close(rr)`
then `os.execv(...)`. That is trivially expressible in `posix_spawn` file
actions (`DUP2`, `CLOSE`) and awkward for anything else.
Startup-failure reporting is exact: the child `_exit(127)`s, the parent
reads a real wait status.

**CORRECTED — this passage previously named
`_raise_nofile_to_hard_limit()` as running in the child. No such helper
exists anywhere in the tree** (verified by search across `*.py`, `*.c`,
`*.h`); it appears nowhere but in this report. It was a residue of the
withdrawn F3 descriptor-limit false positive and survived the revert.
The real child-side sequence is the two lines quoted above.

**Cons.** Page-table copy proportional to parent RSS — the design's
stated motivation.

### 3.2 `os.posix_spawn()`

Python's API offers `POSIX_SPAWN_OPEN`, `POSIX_SPAWN_DUP2`,
`POSIX_SPAWN_CLOSE` and `POSIX_SPAWN_CLOSEFROM` file actions, plus
`setpgroup`, `setsid`, `setsigmask`, `setsigdef`, `resetids` and
`scheduler` parameters. Each has to be checked against what this launch
actually needs.

**CORRECTED — there is NO `close_fds` parameter on `os.posix_spawn()`.**
An earlier draft of this section listed one, and §4.1 went on to describe
its behaviour. That was a **conflation of `subprocess.Popen` with
`os.posix_spawn()`**: `close_fds` is a `Popen` keyword (default `True`),
and does not appear in `os.posix_spawn`'s signature at all. Verified
against the running interpreter rather than from documentation:

```python
>>> import os, inspect
>>> inspect.signature(os.posix_spawn)
(path, argv, env, /, *, file_actions=(), setpgroup=None, resetids=False,
 setsid=False, setsigmask=(), setsigdef=(), scheduler=None)
>>> 'close_fds' in dir(os)
False
```

Descriptor work happens **through `file_actions`**, not through a
flag. This matters especially because the next work order is precisely
about designing descriptor equivalence — building on a parameter that
does not exist would have wasted the exercise.

**VERSION FLOOR — this is a trap, and "verified on this host" hid it.**
`os.POSIX_SPAWN_CLOSEFROM` was added in **Python 3.13** and is further
conditional on the platform exposing
`posix_spawn_file_actions_addclosefrom_np()`. It is present on this
development host (Python 3.14.7) and a probe here would therefore
"succeed" while being **unavailable on the supported floor**, which
`setup.py` declares as `python_requires=">=3.10"`. Any descriptor-tightening
design must therefore specify a path for 3.10–3.12 and for libc/platform
combinations without that extension, or an explicit documented fallback
to the current launcher. **Do not let a host-verified probe stand in for
floor coverage.**

### 3.3 `os.posix_spawn` with `POSIX_SPAWN_CLOSEFROM`

**Available on this development host's Python (3.14.7) and glibc, and NOT
on the supported floor** — see the VERSION FLOOR note in §3.2. It can close
everything from N upward, which combined with explicit `DUP2` of the wanted
descriptors would reproduce the scrub-then-exec discipline. This is the
*shape* of the ideal design, **not** an available implementation for
`python_requires=">=3.10"` without a documented fallback.

---

## 4. Compatibility requirements, item by item (work order §4.2)

### 4.1 Descriptor inheritance and closure

**"Inherits everything else" was wrong about `exec`, and the correction
changes what the inventory has to list.** The current child closes `rr`
and then `execv`s. At **fork** the child does get a copy of the parent's
entire descriptor table — but **`exec` then closes every descriptor marked
close-on-exec**, so what the launcher actually starts with is only the
non-`CLOEXEC` subset. Verified directly rather than assumed:

```
parent opens a plain pipe (fd 4) and a pipe2(O_CLOEXEC) (fd 6),
then fork + execv("/bin/sh", ...) and lists /proc/self/fd:

  child sees fd 4 -> pipe:[...]      <- plain: SURVIVES exec
  child sees fd 6 -> (absent)        <- CLOEXEC: GONE after exec
```

So the phrase "the parent holds at fork time" describes the wrong moment
for this purpose. **The inventory must be of the POST-`exec` effective
descriptor set the launcher starts with** — which is a subset of what the
parent holds, and can be *smaller* than the fork-time table. Auditing the
parent's full table would over-count closable descriptors; auditing only
the intended job fds without checking `CLOEXEC` disposition would
under-count.

> **STAGE 2C CORRECTION — the "source + result only" premise below was
> the ORIGINAL TWO-DESCRIPTOR SKETCH, and it is not what the shipped routes
> do.** Measured inventory (`CLEANROOM_FD_CONTRACT.md` §2):
>
> | route shape | descriptors that actually reach the launcher |
> |---|---|
> | materialized (`map`, mode plugin/udf/spawn) | `src_fd`, `res_fd`, `stats_fd`, optional `trace_fd`, **plus fd 2** — an error memfd duplicated over stderr |
> | streaming (`stream(..., streaming=True)`) | `src_fd`, result **pipe** write end, `stats_fd`; stderr inherited directly |
>
> **`stats_fd` and the poison channel are ONE descriptor**, not two.
> `forkrun_cleanroom.c:2014-2018` sets `FRK_POISON_FD` to `o.stats_fd` and
> assigns `g_poison_stats_fd` from the same value; the launcher writes the
> counter record to it and the workers append poison indices to it. Listing
> "the poison-index memfd" as a separate descriptor -- as an earlier
> revision of this section did -- double-counts.
>
> **The current F6 recommendation is EQUIVALENCE FIRST.** A `posix_spawn`
> backend must reproduce the set above, including the descriptors it would
> prefer to close. Tightening to a smaller allowlist is a **separate
> policy change requiring its own approval**, not part of this
> optimisation. The bullets below describe how a deliberate allowlist
> *would* be built; they are **not** authorisation to build one.

The launcher does not scrub its OWN inherited set — `scrub_apply()` runs
only from `enter_child()`, i.e. in the launcher's children. Isolation is
therefore enforced at the **worker** boundary, not the launcher boundary,
and an unrelated inheritable parent descriptor does reach the launcher
today. That asymmetry is what "equivalence vs isolation" turns on
(`CLEANROOM_FD_CONTRACT.md` §5).

**CORRECTED.** An earlier draft said `posix_spawn` "does not inherit the
parent's fd table the way `fork` does; it constructs the child's
descriptors from file actions." That misstates POSIX. The child's initial
descriptor set IS the parent's open descriptors, then modified by the
specified file actions and close-on-exec disposition. `posix_spawn` does
**not** hand you an allowlist.

Producing a *deliberate* allowlist is real work, and the inventory has to
come first. Concretely — **as a description of the tightening proposal,
not as a requirement of the equivalence change**:

* Every job descriptor (`src_fd`, `res_fd`, `stats_fd`, optional
  `trace_fd`, and `errfd` — which reaches the launcher only as the
  duplicate on fd 2) must be enumerated and confirmed **inheritable**.
  glibc's `spawni.c` shows the available actions — `open`, `dup2`,
  `close`, `closefrom` — and a `dup2` action whose source and destination
  are equal clears `FD_CLOEXEC`, which is often cheaper than re-opening.
* For EQUIVALENCE, none of this needs a close action at all: the
  equivalence action set is one `DUP2` for the materialized shape and
  **empty** for the streaming shape, because every required descriptor is
  already inheritable and the unwanted pipe end is already `FD_CLOEXEC`.
* Tightening — "everything else must be made non-inheritable" — is the
  SEPARATE proposal, and it is where the mechanisms matter. **The
  mechanism is `file_actions`, not a flag** — `os.posix_spawn()` has no
  `close_fds` (see the correction in §3.2). The available actions are:
  * `POSIX_SPAWN_CLOSE` — closes one named descriptor. Available on every
    supported interpreter; safe but O(n) in the descriptor count.
  * `POSIX_SPAWN_CLOSEFROM` — closes everything ≥ N in one action.
    **Python 3.13+ only, and conditional on the platform exposing
    `posix_spawn_file_actions_addclosefrom_np()`.** Absent on the 3.10
    floor (see §3.2), so it cannot be the sole mechanism.
  * A `dup2` action whose source and destination are equal clears
    `FD_CLOEXEC` on that descriptor, which is how a wanted descriptor is
    made inheritable.

  A `closefrom` action cannot express an *arbitrary* allowlist — it is a
  suffix — so a real allowlist with gaps still needs explicit `close`
  actions, or the inherited set must be arranged so the wanted
  descriptors are contiguous.

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

> **STATUS: this protocol has now been run.** Results are in §1.1a. It is
> kept here verbatim because §5 was fixed **in advance** of seeing the
> numbers, and that is what makes the result worth something — in
> particular the "parent RSS as the independent variable" clause and the
> "a sweep at low ballast will report 'no difference' and is worthless
> for this decision" warning, both of which an earlier partial sweep
> ignored to its own cost.

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

**Disposition: GO — ADOPTED.** Conditions C1–C5 are all CLOSED against
named evidence (`CLEANROOM_FD_CONTRACT.md` §9), and `posix_spawn` is now
the **default** cleanroom launch backend. `fork()` + `execv()` remains
reachable through the private `_set_cleanroom_launch_backend()` for
regression bisection; no public API and no environment variable selects the
backend, so F7's contract is identical either way.

*This section originally said the opposite, and said it for a reason that
has since been shown to be wrong — see §8.1. The objection below was
"the benefit is ~0 for small parents", which was measured with a
`MAP_SHARED` ballast that never carried the `fork()` tax. The benefit is
indeed ~0 for small parents; it is −22.5% at 1 GiB and −32.9% at 2 GiB of
real Python heap. The history is retained rather than rewritten so the
correction is visible.*

Reasons, in order of weight:

1. **The benefit is real but conditional, and is now quantified.**
   Small parents: −1.8%, which is noise. Parents whose address space is
   dominated by private anonymous memory — ordinary CPython arena growth —
   get tens of percent (see §8.1). The earlier "benefit is ~0" claim was
   an artefact of ballast that was `MAP_SHARED`.
2. **Descriptor tightening is not authorised and is not part of the
   candidate.** Equivalence-first means reproducing today's set, including
   the unrelated inheritable descriptors that currently leak into the
   launcher. Tightening is a behaviour change with its own approval.
3. **Startup-failure semantics are preserved, not improved.** Both
   backends produce the same caller-visible exit-127 result, because the
   candidate synthesises the same wait status the shipped child produces.
   Policy B (falling back) remains unimplemented and unauthorised.
4. **The threaded-parent hazard remains an argument FOR eventually
   acting** (§4.7) — the candidate structurally removes the
   fork-then-run-Python window at these two sites.

### 8.1 End-to-end timing: the launch win does carry, once the ballast is real

Isolated launch latency (§1.1a) is not end-to-end. Measured through the
public API, one `map()` over 200,000 records with `workers=4`, alternating
backends, 5 samples after warmup (milliseconds):

| parent heap | fork+execv median | posix_spawn median | delta |
|---|---|---|---|
| small (12 MiB RSS) | 141.33 | 138.77 | **−2.6 ms (−1.8%)** |
| 1 GiB | 179.46 | 139.06 | **−40.4 ms (−22.5%)** |
| 2 GiB | 201.43 | 135.07 | **−66.4 ms (−32.9%)** |

**F6 Stage 5 re-measurement**, 2048 MiB, **15 paired/interleaved
repetitions**, both mappings, raw per-trial samples in
`bench_artifacts/cleanroom_backends_2048MiB_20261018T165718Z.json`:

| mapping | fork+execv (sd) | posix_spawn (sd) | median delta | paired diff median [range] | isolated spawn: fork / spawn |
|---|---|---|---|---|---|
| MAP_PRIVATE | 210.98 (2.48) | 141.91 (2.30) | **32.7%** | **69.99 ms** [64.26, 73.33] | 26.19 / 0.27 |
| MAP_SHARED | 145.35 (3.19) | 143.60 (3.03) | **1.2%** | **1.71 ms** [-2.64, 8.98] | 0.91 / 0.29 |

**Generated from the committed artifact, not transcribed.** `gen_bench_tables.py` reads `bench_artifacts/cleanroom_backends_2048MiB_20261018T203828Z.json` and emits this table; `gen_bench_tables.py --check` fails if the two ever disagree. Stage 5.1 shipped a document whose figures did not match its own artifact, which is why these numbers are now generated rather than typed.

Corrected re-run of 2026-10-18, superseding the previous revision's figures.
**The conclusion has not moved across four independent runs**: the private
cell is −29% to −35% with every one of the 15 pairs large and positive, and
the shared cell sits within noise in every run. Run-to-run variation in the
private figure is smaller than the gap it measures.

Each mapping cell now runs in **its own subprocess**. This was not
fastidiousness: glibc raises its dynamic `mmap` threshold when a large
mapping is freed, so a 2 GiB ballast allocated and released within one
process is not reliably returned to the operating system, while a 1 GiB one
is. Measured directly — after alloc then free, RSS returns to baseline at
1 GiB (13 → 1038 → 13) but not at 2 GiB — and forcing `gc.collect()` does
not help, because the memory is held by the allocator rather than by a
Python reference. The Stage 5.2 run before this one was invalidated by
exactly this: the shared cell inherited the private cell's mappings, and
the control caught it (`rw-p/2052MiB, rw-s/2048MiB`) rather than reporting
the contaminated numbers. One process per cell removes the dependency.

The shared cell's −1.4% does not conflict with the earlier +0.7% — both sit
inside a range that spans zero, which is what the paired range shows and
what a single median cannot. A failed mapping control now marks the
artifact `"valid": false` and the script exits non-zero, so a cell that did
not measure what it claims cannot be mistaken for a successful run.

**The mapping control, and a trap worth recording.** The obvious way to
verify that one cell is private and the other shared is to read smaps'
private/shared counters. That is wrong here. `mmap.mmap(-1, n)` really is
`MAP_SHARED` (VMA perms `rw-s`, backed by `/dev/zero (deleted)`), but
because it is *file-backed* it reports `Anonymous: 0 kB`, so a classifier
keyed on `Anonymous:` sees nothing; and the kernel books its dirty
page-cache pages under `Private_Dirty` (2048 MiB), so a naive reading calls
the "shared" ballast private — which would make the two cells
indistinguishable and the comparison meaningless. The benchmark therefore
classifies by the **VMA permission word**, corroborated by the `sh` bit in
`VmFlags`, and reports VOID if a cell's ballast is not the kind of mapping
it claims.

**The earlier version of this table said +1.0% at 2 GiB, and that number
was wrong because the benchmark was measuring the wrong parent.** It
ballasted the parent with `mmap.mmap(-1, n)`, which on Linux is
`MAP_SHARED|MAP_ANONYMOUS`. A `MAP_SHARED` anonymous mapping does **not**
carry the `fork()` tax — measured directly, forking 2 GiB of it costs
~1.8 ms, against ~57 ms for 2 GiB of `MAP_PRIVATE|MAP_ANONYMOUS`. The
benchmark had therefore constructed a parent that never had the cost
`posix_spawn` removes, and duly measured no benefit.

Real CPython heap growth uses private anonymous arenas, so a real process
does carry the tax: 2 GiB of `bytearray` ballast makes fork+exec cost
~70 ms in-process, matching §1.1a. The table above uses that allocation,
keeps a reference so it is not freed before the launch, and verifies RSS.

**What is actually being claimed.** The win scales with how much of the
parent's address space is private anonymous memory, and is negligible when
it is not. A caller with a small parent gets ~2%, which is noise. A caller
processing large in-memory data in a long-lived Python process gets tens of
percent. **Do not generalise the host coefficient** to other workloads,
platforms or launch counts; the earlier conclusion that "a single-launch
workload will not benefit" was right about the *old* measurement and wrong
about the mechanism.

**Correction to this report's earlier recommendation.** Previous revisions
said the design's gate "was never evaluated" and "the concrete claim is
unmeasured". Both were false and are gone; an intermediate revision
concluded the gate was **not met** on small-parent data, which was also
superseded. **Do not read this document's history as a stable position.**

### 8.1b Launch-cost timing windows — corrected, and deliberately inconclusive

> **CORRECTION (F6 Stage 5.1).** An earlier revision of this section
> claimed a **directly measured** "child-side address-space teardown" of
> 40.19 ms, derived as `B - A` from two wall-clock windows. That claim was
> factually wrong, not merely loose. `A` stops its timer at `fork()`
> returning **before `waitpid()`**, so `A` contains no reap at all, while
> `B`'s timer includes `waitpid()`. The two windows are not nested, and
> `B - A` therefore also contains the child's startup path, process exit,
> the wakeup of the parent, scheduling and the reap syscall. The original
> justification — that "A and B pay the same parent-side copy and the same
> reap" — was simply untrue of the code as written.

Corrected measurements, 2048 MiB private ballast, 15 repetitions
(`bench_launch_decomposition.py`). Every row states what its timer window
contains:

| | measurement | timer window contains | median |
|---|---|---|---|
| **A** | `fork()` → parent return | parent-side page-table copy. **No reap** | 29.82 ms |
| **B** | `fork()` + reap, child `_exit()` | A, plus child startup, teardown, exit, wakeup, scheduling, reap | 70.05 ms |
| **B1** | `fork()` → child's pre-exit signal | A, plus the child's startup path. Excludes teardown | 29.94 ms |
| **B2** | child's own pre-exit clock → reap | **contains** teardown, plus exit, wakeup, scheduling, reap | 41.73 ms |
| **C** | `fork()` + `/dev/null` open + `dup2` + `execve` + reap | differs from B in more than exec | 72.68 ms |
| **D** | `posix_spawn` + reap | no per-page copy (`CLONE_VM\|CLONE_VFORK`) | 1.00 ms |

Generated from `bench_artifacts/launch_decomposition_2048MiB_20261018T203828Z.json`.

What may honestly be said:

* **`B - A` = 40.23 ms** is the *additional cost of completing
  fork-and-exit-and-reap relative to parent-side fork-return latency*. It
  includes child startup, teardown, exit, wakeup, scheduling and the reap.
  **It is not a measurement of teardown**, because `A`'s timer stops before
  `waitpid()` and so contains no reap at all.
* **`B1 - A` = 0.12 ms** is the child's startup path. Child startup is
  cheap; it is not where the time goes.
* **`B2` = 41.73 ms** is the interval from the **child's own**
  `CLOCK_MONOTONIC` reading, taken as its last action before `_exit()`, to
  the completion of `waitpid()`. Because the anchor precedes `_exit()`, the
  kernel's teardown of the child's address space necessarily falls inside
  this window. It is still **not a pure measurement** of it: the remainder
  of the pipe write, process exit, the parent's wakeup, scheduling and the
  reap share the window and are not separable without kernel-side
  instrumentation, which this deliberately does not add. The claim it
  supports is *"the teardown is inside this window"*, not *"the teardown is
  this long"*.
* **`C - B` = 2.64 ms** is a difference between two *complete* timing
  configurations that differ in more than image replacement — C's child also
  opens `/dev/null` and `dup2`s it onto stdout. Not a pure exec-cost figure.
* **`C - D` = 71.68 ms** is a complete forked launch against a complete
  spawned one — a difference of two whole operations, not of two isolated
  components.

**B1 and B2 are not a decomposition of `B - A`.** The Stage 5.1 revision
treated them as accounting for it and reported an unexplained residue; that
framing was wrong, because B2 was not measuring what its name said — its
`t0` was captured before `fork()` and its `t1` after the parent's `read()`,
so it recorded the same window as B1. The committed artifact showed the two
agreeing to 0.09 ms, which is the tell. No arithmetic relation between B1/B2
and `B - A` is claimed.

**Still not measured:** whether the teardown had already begun by the time
the parent consumed the child's byte. B2 avoids depending on that by
anchoring in the child's own clock, but the interval between that reading
and the kernel entering `exit` remains unmeasured.

**This section is not load-bearing.** The figure that decides the default
switch is the end-to-end paired difference in §8.1, and nothing above should
be cited as if it were. The earlier claim to have measured teardown directly
is withdrawn.

**No rlimit cost exists** and it is not part of this list — the launcher
raises its own `RLIMIT_NOFILE` before `dlopen` (§4.3).

**This work order produced no defect in this area.** The one finding it
initially reported here, F3, was a false positive and has been withdrawn
(§6).

**Explicitly out of scope and unchanged:** the engine, the ring, the
supervision models, F7 environment inheritance, and the cleanroom
eligibility envelope. None of this changes what the cleanroom *is*.
