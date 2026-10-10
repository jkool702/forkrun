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

`posix_spawn` uses `CLONE_VM | CLONE_VFORK`, so the spawn itself does
not copy the page table at all. The launcher `dlopen`s the substrate and
then **forks** (no second exec), so the workers inherit the engine
mapping by COW for free.

One exec, then N cheap forks. That is the entire win.

## Coverage: what can and cannot cross an `exec`

`exec` destroys the Python interpreter's object graph. A payload that is
a live object therefore cannot be *carried* across the boundary.

| mode | payload form | carried across `exec`? | shipped status |
|---|---|---|---|
| `mode="plugin"` | `"/path/plugin.so:func"` | **yes** — a path string | **served** |
| `c_spawn_loop=True` | `argv` list | **yes** — plain data | **not reachable**: `_cleanroom_eligible` requires `raw_mode == "plugin"` |
| Python UDF | a `callable`, or `"pkg.mod:func"` | **no** — not shipped |

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

Until it is built, the shipped boundary is unchanged: **the cleanroom
serves the C plugin path only**, and everything else declines to the
in-process path. See `DOCS/FUTURE_WORK.md` Tier 4b item 46.

A side benefit worth noting: the comment above `resolve_payload_parent`
mentions that forking a threaded host can inherit a frozen import lock
and deadlock, and that Python 3.12+ warns about fork-in-threaded-host.
The cleanroom structurally removes that hazard for the paths it covers,
because the forking process is single-threaded and purpose-built.

## Configuration contract

The launcher must not inherit the parent's environment wholesale.
Explicitly passed:

- `source_fd` — the input file or pipe
- `result_fd` — where framed results are written
- `workers`, `nodes`, `order`, `retry_limit`, `mode`
- `plugin_path`, `plugin_func` (or `argv` for `c_spawn_loop`)
- `output` representation, `orchestrator`
- fd limit to raise to

Explicitly **not** inherited: environment, signal dispositions beyond
what the engine sets itself, and every unrelated descriptor (the parent
`scrub_fds()`s them, and the launcher re-scrubs after exec).

## Rollback and rollout

- Default **off**, opt in with `FORKRUN_CLEANROOM=1`. It was briefly on
  and reversed. It stays off while the envelope is narrower than the
  API and while NUMA validation is fake-only — not because it is slow,
  which was true until CR-FIX1 and is not true now.
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

1. Design (this file).
2. Launcher PoC: `posix_spawn` + `dlopen` + `fr_py_init` + fork N
   workers, with the fork tax **measured**. That number decides whether
   the full integration is worth its risk.
3. Full integration behind the flag only if the PoC pays.
4. Re-run the isolated benchmark with the launcher on and off, so the
   delta is published rather than hidden.
