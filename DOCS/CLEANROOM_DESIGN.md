# Python cleanroom launcher — design (W-CLEANROOM)

## The problem

`fork()` cost scales with the parent's RSS, because the page table is
copied for every child. Measured on this box:

| parent | per fork | 28 forks |
|---|---|---|
| clean (11 MB) | 0.27 ms | 7.5 ms |
| 5 GB | **45.3 ms** | **1274 ms** |

The Python frontend `dlopen`s the substrate into the **user's** process,
so its workers fork from whatever that process happens to be holding. A
real ML workload — pandas, numpy, a loaded model, a benchmark harness —
routinely sits at multiple GB, which puts ~1.3 s of pure fork tax on
every `forkrun` call.

This is a *fixed per-invocation* cost, so it is worst exactly where
throughput looks best. On `light/5M` (a 0.49 s run) it would be 2.6×;
on `heavy` (~5 s) it is ~20%. That is why it read as noise on long runs
and dominated short ones, and why it is easy to misattribute to
topology or noise.

`frun` does not have this problem, and not by accident — see below.

## What `frun` already does (the reference)

`frun` deliberately relaunches itself:

```bash
exec -c "${BASH:-bash}" --norc --noprofile -c \
  'enable -f "/proc/self/fd/'"${FORKRUN_MEMFD_LOADABLES}"'" ... frun __exec__ "$@"' \
  -- "${@}" 0<&${fd00} 1>&${fd11} 2>&${fd22}
export _FR_IN_CLEANROOM=1
```

Five details matter, and the design copies all five:

1. **`exec -c "$BASH" --norc --noprofile`** — a fresh interpreter with
   none of the user's shell state.
2. **exec happens BEFORE `ring_init`** (exec at frun.bash:198,
   `ring_init` at frun.bash:1472). This is the key structural insight:
   because initialisation happens *after* the exec, **no engine state
   ever crosses the exec boundary**. That is why the obvious
   "the shared state is `MAP_ANONYMOUS` so it can't cross exec"
   objection is a non-issue — you do not carry it, you recreate it.
3. **memfds are re-opened by path**, `/proc/$BASHPID/fd/N`, rather than
   passed as fd numbers. The PID is unchanged across `exec`, so the path
   still resolves. This sidesteps `FD_CLOEXEC` bookkeeping entirely.
4. **`fd00/fd11/fd22`** — the group saves the real stdin/stdout/stderr
   into high fds, and the exec line restores them, so exactly the
   descriptors the engine needs are carried across.
5. **`_FR_IN_CLEANROOM=1`** — a recursion guard so the re-executed
   instance does not exec again.

It also raises `ulimit -n` to the hard limit in the cleanroom, which the
launcher should do too.

## Proposed topology

```
  user's Python process          launcher (small, post-exec)
  (may be 5 GB RSS)                    |
       |                               +-- fr_py_init()      <- state created HERE
       |  posix_spawn                      |
       |  (CLONE_VM|CLONE_VFORK,           +-- fork x N workers   <- cheap: ~0.27ms
       |   so no page-table copy)          +-- fork scanner/fallow/ingest
       |                               +-- drain -> result fd
       +<-- results on result fd
```

**PROPOSAL, NOT THE SHIPPED DESIGN — see
`dev/supervisor/CLEANROOM_LAUNCH_DECISION.md`.**
Both Python launch sites use `os.posix_spawn()`, with `os.fork()` +
`os.execv()` retained as a private fallback backend. **The `posix_spawn`
backend is implemented, validated and is now the default.** The launch-cost
benchmark compares the two mechanisms across parent resident memory from
0 MiB to 5 GiB (§1.1a of the decision report). At 1 GiB and above,
`posix_spawn` launched in ~3.5-4.2 ms against 29-112 ms for `fork()`+
`execv()` — a large win, because the `fork()` cost grows roughly linearly
with the parent's memory.

That benchmark's benefit is real but **conditional on how the parent's
memory is mapped**, which is worth stating precisely because it was
measured wrong at first. A C harness using `MAP_PRIVATE|MAP_ANONYMOUS`
sees the full 29-112 ms tax. A *real* CPython process whose heap has
grown behaves the same way, because arenas are private anonymous
mappings: with 2 GiB of heap ballast, fork+exec costs ~70 ms. But
`mmap.mmap(-1, n)` in Python defaults to `MAP_SHARED|MAP_ANONYMOUS`,
which does **not** carry the tax (~1.8 ms). An end-to-end timing that
ballasted the parent that way showed no benefit at all — not because the
benefit is illusory, but because it had constructed a parent that never
had the cost to remove. Measured end to end on this repo's own route with
realistic Python-heap ballast: 0 MiB −1.8% (noise), 1 GiB −22.5%,
2 GiB −32.9%.

**The mechanism described here is CORRECT and needed no correction.**
glibc implements `posix_spawn` with the `clone` syscall using
`CLONE_VM | CLONE_VFORK` and an allocated stack
(`sysdeps/unix/sysv/linux/spawni.c`). `CLONE_VFORK` suspends the calling
thread until the child `execve`s or exits, so the spawn itself does not
copy the page table. An audit pass briefly "corrected" this to
`vfork(2)`, which was wrong — glibc does not call `vfork(2)` for this
path, though the semantics are vfork-like. See the decision report §1.2
for that retraction.

So the spawn does not copy the page table at all. The launcher
`dlopen`s the substrate and then **forks** (no second exec), so the
workers inherit the engine mapping by COW for free.

One exec, then N cheap forks. That is the entire win.

## Coverage: what can and cannot cross an `exec`

`exec` destroys the Python interpreter's object graph. A payload that is
a live object therefore cannot be *carried* across the boundary.

| mode | payload form | carried across `exec`? | shipped status |
|---|---|---|---|
| `mode="plugin"` | `"/path/plugin.so:func"` | **yes** — a path string | **served** (`map-plugin`, `stream-plugin`) |
| `mode="udf"` | `"pkg.mod:func"` only | **yes** — a spec string, re-imported after `exec` by the helper | **served** (`map-udf`, `stream-udf`); needs a version-matched helper, else it degrades to the in-process path |
| `mode="spawn"` | `argv` list or command string | **yes** — plain data | **served for materialized** (`map-spawn`) via `c_spawn_loop`; **NOT served for `stream(spawn)`**, which has no dispatch and therefore no route identifier |
| `mode="python"` | callable or spec | n/a | **not served** — declines to the in-process path |
| `mode="splice"` | none | n/a | **not served** |

**Corrected (WO Phase A).** Two rows in this table were stale and are now
fixed. `mode="spawn"` was marked "not reachable: `_cleanroom_eligible`
requires `raw_mode == 'plugin'`" — that gate now admits
`("plugin", "udf", "spawn")`. Python UDF was marked "no — not shipped";
it is implemented (`_udf.py`, `fr_udf*.c`) and is a first-class route.
Note that the per-route distinction above is real and was not previously
written down anywhere: **materialized spawn is served, streaming spawn
is not**, because the stream path has no spawn dispatch at all.

Streaming is likewise no longer follow-on work: `_execute_cleanroom_stream()`
exists and serves the `stream-plugin` and `stream-udf` routes.

`resolve_payload_parent()` documents the object-graph half: payloads are
resolved in the parent and "cross by fork inheritance like the callable
form always did".

**CR-FIX1 correction to the ruling below.** The original text said the
boundary was "hard ... not negotiable" and that Python UDF was
"structurally impossible; do not attempt it". That is correct *about
carrying* and incorrect *about reachability*: `exec` destroys the graph,
but it does not prevent the far side from **re-creating** an interpreter
and re-importing the module. That is exactly the technique `frun.bash`
already uses for the shell (`exec -c bash --norc --noprofile` with
`_FR_IN_CLEANROOM=1` as a recursion guard).

What the "impossible" ruling failed to price is the set of seams that
re-creation would require, none of which exists today: CPython linked
into a **separately built** helper `.so` (never into the substrate, which
stays Python-free and version-agnostic), a C→Python callback seam with
GIL and exception marshalling, post-`exec` reconstruction of `sys.path`
and module state, and exact `None`/`b""`/`str` return parity. That is a
real project, not an impossibility.

**SUPERSEDED — corrected (WO Phase A).** This paragraph used to read
"the cleanroom serves the C plugin path only, and everything else
declines to the in-process path", which contradicted the corrected mode
table above it. It described the state before UDF, spawn and streaming
were built.

**The shipped boundary today is five routes:** `map-plugin`,
`stream-plugin`, `map-udf`, `stream-udf` and `map-spawn`. `mode="python"`
and `mode="splice"` decline to the in-process path, as does
`stream(spawn)`, which has no dispatch at all — and therefore no route
identifier, because a selectable route that can never fire is worse than
no route. See `_CLEANROOM_ROUTES` in `run.py` and
`dev/supervisor/BASH_PY_PARITY_AUDIT.md` §6. See `DOCS/FUTURE_WORK.md` Tier 4b item 46.

A side benefit worth noting: the comment above `resolve_payload_parent`
mentions that forking a threaded host can inherit a frozen import lock
and deadlock, and that Python 3.12+ warns about fork-in-threaded-host.
The cleanroom structurally removes that hazard for the paths it covers,
because the forking process is single-threaded and purpose-built.

## Configuration contract

> **STATUS — partly aspirational.** The *descriptor* half of this contract
> is implemented (`_fd_scrub.scrub_fds` runs on the child paths). The
> *environment* half is **NOT implemented**: both Python launch sites pass
> `os.environ` straight to `posix_spawn()` (or to `os.execv()` on the
> fallback backend), so `environ` is inherited wholesale either way. Measured: a parent with
> 112 variables yields a cleanroom child with all 112 (113 on
> `map-plugin`, which adds `FRK_POISON_FD`). A malformed inherited
> `PYTHONHASHSEED` kills the cleanroom child at interpreter init. Tracked
> as **F7** in `dev/supervisor/BASH_PY_PARITY_AUDIT.md`, which remains
> OPEN — clearing the environment outright would break `mode="spawn"`
> payloads needing `PATH` and UDF modules needing `PYTHONPATH`, so the
> contract still needs a deliberate decision, not a patch.

The launcher must not inherit the parent's environment wholesale.
Explicitly passed:

- `source_fd` — the input file or pipe
- `result_fd` — where framed results are written
- `workers`, `nodes`, `order`, `retry_limit`, `mode`
- `plugin_path`, `plugin_func` (or `argv` for `c_spawn_loop`)
- `output` representation, `orchestrator`
- fd limit to raise to

> **STATUS — this list is the ORIGINAL DESIGN SKETCH, not the shipped
> descriptor contract.** Measured inventory (F6 Stage 2,
> `dev/supervisor/CLEANROOM_FD_CONTRACT.md`) shows the shipped routes
> pass **more** than the two descriptors named above:
>
> | route shape | actually passed |
> |---|---|
> | materialized (`map`, mode plugin/udf/spawn) | `src_fd`, `res_fd`, `stats_fd`, optional `trace_fd`, **plus fd 2** — an error memfd duplicated over stderr by `os.dup2(errfd, 2)` |
> | streaming (`stream(..., streaming=True)`) | `src_fd`, result **pipe** write end, `stats_fd`; stderr inherited directly, **no error memfd** |
>
> `stats_fd` is also the poison channel: the launcher sets
> `FRK_POISON_FD` to that same descriptor number
> (`forkrun_cleanroom.c:2014-2018`), so it carries two logical uses and
> is **one** descriptor, not two.
>
> The "every unrelated descriptor" claim below is likewise **aspirational
> for the launcher process**: the launcher does not scrub its own inherited
> set. Scrubbing (`scrub_apply`) happens in the launcher's *children*
> (`enter_child`), so isolation is enforced at the worker boundary, not at
> the launcher boundary. Whether to tighten the descriptor set is an open
> policy question, recorded in `CLEANROOM_FD_CONTRACT.md` §5.

> **PRECONDITION (CLOSED, F6 Stage 4).** This contract used to assume
> **fd 2 is open** in the host process when a cleanroom launch begins. If
> the host closed a standard stream beforehand, the route's own allocation
> could place `src_fd` on a standard-stream number, and `dup2(errfd, 2)`
> would overwrite it — the launcher would be handed `--src 2` and read the
> error memfd as its input. The result is **silently wrong**, with no
> error, warning, or non-zero exit. This was pre-existing and not specific
> to `posix_spawn` (its `DUP2` action behaves identically), so it was a
> correctness gap in the route rather than a backend incompatibility.
>
> It is now closed for both backends. Every route-owned descriptor is
> relocated above the gap with `fcntl(fd, F_DUPFD, 3)` before use, and the
> streaming result pipe is relocated too. `F_DUPFD` rather than `dup()`
> specifically: `dup()` returns the *lowest free* descriptor, so with the
> gap only partly free it would hand back a number still inside it. An
> earlier fix used `dup()` and its test passed only because the test
> closed all three standard streams at once, leaving the gap empty. See
> `dev/supervisor/CLEANROOM_FD_CONTRACT.md` §9.

> **STAGE 3/4 STATUS.** The `posix_spawn` backend passes `os.environ`
> through untouched: no reconstruction, no filtering, no scrubbing. F7
> remains OPEN and SEPARATE, and none of the descriptor work touches it.
> There is still no environment selector for the backend, so the F7
> contract is identical whichever backend is running.

Explicitly **not** inherited (aspirational — see STATUS above):
environment, signal dispositions beyond what the engine sets itself, and
every unrelated descriptor (the parent `scrub_fds()`s them, and the
launcher re-scrubs after exec).

## Rollback and rollout

- Default is now **on for `map(plugin)` only** (WO-CR-ROI-2 Phase D,
  `04485e52`); every other route stays opt-in behind
  `FORKRUN_CLEANROOM`. History: it was briefly on in full, reversed, and
  stayed off while the gate was a single boolean coupling five
  envelopes. A per-**route** selector (`6109dd93`) made the narrow
  default expressible, and all four of the original readiness blockers
  are closed. It was never "slow" — that was true until CR-FIX1.
- **No RSS threshold.** An earlier draft proposed gating on ~350 MB
  parent RSS; that number was wrong. It came from a PoC whose fixed
  cost was inflated by a synchronous whole-corpus ingest. With the
  launcher's real fixed cost (~3 ms: bare exec 0.4 ms + dlopen ~1 ms +
  `fr_py_init` ~1 ms) the crossover is **negative** — the cleanroom is
  ahead at every realistic parent size, since its forks cost 0.068 ms
  against 0.30 ms in-process even at 0 MB parent RSS.
- The opt-out keeps the existing in-process `os.fork()` path intact as
  the fallback, so there is no second implementation to delete.
- If the launcher fails to spawn or returns an unexpected status, the
  parent falls back in-process and records why. A silent fallback would
  be worse than either behaviour alone, so the fallback is observable.

## Risks

1. **The launcher becomes a second implementation** of orchestration
   (init, fork, scan, drain). Divergence between it and the Python path
   is the main long-term hazard. Mitigation: keep the launcher's logic
   as thin as possible — it should call the *existing* `fr_py_*` entry
   points, not reimplement them.
2. **Error propagation.** Today errors surface as Python exceptions with
   tracebacks; across an exec they become exit codes plus stderr. The
   launcher must forward diagnostics on a dedicated error fd so failures
   stay debuggable.
3. **Testing.** The suite exercises the Python path heavily. Running it
   under the launcher is the real test; a green suite under `--isolate`
   alone is not evidence.
4. **THP.** `ring_init` hints `MADV_HUGEPAGE` on the state mapping and
   warns when `shmem_enabled` is not `always`. Worth 15–20% on the plugin
   rows. Must confirm the launcher path gets identical THP treatment —
   this bit me once already this session.

## Delivery plan

1. Design (this file). **Done.**
2. Measure the fork tax of a `posix_spawn` launcher against the shipped
   `fork()`+`execv()`, with **parent resident memory as the independent
   variable** (0 / 256 MiB / 1 / 2 / 5 GiB).
   **MEASURED** — `tools/bench_cleanroom_launch.c`, results in
   `dev/supervisor/CLEANROOM_LAUNCH_DECISION.md` §1.1a. The saving is
   large and grows with parent RSS: **−67% at 256 MiB, −88% at 1 GiB,
   −92% at 2 GiB, −96% at 5 GiB**; `posix_spawn` stays flat at ~2.7-4.2 ms
   while `fork()`+`execv()` costs ~23-35 ms per GiB. Production launch is
   unchanged.
3. Design and prove a `posix_spawn` **descriptor allowlist** (§4.1 of the
   decision report): which job descriptors must stay inheritable, and
   what proves equivalence against `fork()`+`execv()` on every served
   route. **NOT DONE — this is now the blocking item**, because
   `posix_spawn` gives the child the parent's descriptors modified by file
   actions; it does not hand you an allowlist.
4. Full integration behind a flag only once 3 is proved. **NOT DONE, and
   not authorised by the work order that produced these numbers.**
5. Re-run the isolated benchmark with the launcher on and off, so the
   delta is published rather than inferred. **NOT DONE** — the current
   numbers are process-creation latency, not end-to-end workload time.
