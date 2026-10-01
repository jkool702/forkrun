# W-REL5-C Completion Report — Python Robustness & Security Posture

**Branch:** `wrel5-c` (worktree `/mnt/ramdisk/forkrun-c`, off merged
`980cc0f`). 11 commits. **Gates:** bites per item (below), referees
10+4+11+5=30/30, `test_wrel5c` 11/11, full suite 616×3 green,
`release_check` 17/17, C-diff empty. No tag, no release push.

## Per-item table

| Item | Change | Bite (pre → post) | Files |
|---|---|---|---|
| C1 | `find_substrate`: CWD candidates dropped (`_substrate_candidates`, `$FORKRUN_LIB` kept) | hostile CWD `.so` returned → `FileNotFoundError` (×5) | `_bindings.py`, `test_wrel5c.py` |
| C2 | checkpoint policy off-main-thread raises `RuntimeError` w/ remedy | silent no-op → loud (×5 threads + control) | `_signals.py`, `test_wrel5c.py` |
| C3 | `sweep()` rejects `resume=`/`checkpoint_file=` | accepted/wrong-error → `ValueError` (×5) | `run.py`, `test_wrel5c.py` |
| C4 | deliver-then-unlink: consume non-destructive; `_publish_sidecar` GCs superseded source post-publish | consume deleted → keeps; merge exact; publish folds; GC'd (×5) | `_resume.py`, `run.py` (comments), `test_wrel5c.py`, `test_resume.py` (1 collision, see below) |
| C5 | null `spare_signal_w` in 3 stream-reactor `finally`s; `order_w` audit clean (6/6 nulled, 0 intervening opens) | stale fd 23 → `None` at teardown (×5, slow-payload abandon + spy) | `run.py`, `test_wrel5c.py` |
| C6 | handler: preallocated 32-slot array, engine-`fr_py_abort`-only; custom `abort_fn` deferred to drain/`check()` | custom ran in-handler → deferred; taxonomy intact | `_signals.py`, `test_wrel5c.py`; `test_signals.py` 10/10 ×10 |
| C7 | torn trailing signal (1–15B @ EOF) WARN+discard in both drain loops | hung 10.042s → instant (+4 repeats) | `run.py`, `test_wrel5c.py` |
| C8 | `load_plugin` docstring states parent-side dlopen constraint | docs only, no bite; plugin tests green in matrix | `_plugin.py` |
| C9 | `uniform(0.05,0.2)s` backoff before respawn on SIGKILL death only (cap first) | 2-kill transient in 0.041s → exact + ≥0.09s floor (×10); persistent killer bounded `RuntimeError`, fds clean | `_reactor.py`, `test_wrel5c.py` |

## C8 deliverable (quoted)

> CONSTRAINT (W-REL5-C8): the dlopen itself runs in the PARENT, so ELF
> initializers execute parent-side and a plugin linking libstdc++/libgomp
> (or any initializer that starts threads) can create threads BEFORE the
> fork — forking a multithreaded parent is unsupported (same reason
> _shim.c keeps plugin invocation post-fork-only). Only the *call* is
> fork-safe (post-fork in workers...). Do not load thread-spawning plugins
> on this path; a dialect-probe rework (load in a forked probe child) is
> deferred as not pre-tag material.

## Spec collision (1): C4 vs `test_resume_complete_output`

The test pinned destructive-consume hygiene (`assertFalse(.coll exists)`
after successful resume); C4 mandates deliver-then-unlink (OOM-kill
between unlink and user persistence = silent prefix loss on next
resume). Resolution: updated to the mandated contract — stale sidecar
retained + explicit re-resume from the spent checkpoint still
byte-identical (engine horizon skips committed; sidecar covers exactly
them), a stronger property than the old assertion. Only `.coll`
existence assertion in the suite; neighbors unaffected. Precedent:
B-wave L-series rework for mandated behavior change.

## Incidents + dispositions

1. C4 test bug (dest path missing `.coll` suffix) — caught on first
   run, fixed, test-only. 2. C5 null inserted at wrong indent (inside
   `except`) — caught on re-read, fixed, compile-verified. 3. C5 bite
   v1 raced completion (fast payload) — slow payload + spy made it
   deterministic. 4. C6 draft edit mangled an unrelated test line —
   reverted immediately, verified clean. 5. Docstring `"""` dropped
   mid-edit (C7) — caught, restored, compile-verified. 6. No flake
   registry hits; no other new-failure signatures (the single matrix
   failure was the C4 collision above, resolved).

## Follow-ups for the owner (non-blocking, noted)

- C4 leaves a stale `.coll` next to spent checkpoints (tidiness cost
  of crash-safety; re-read only on explicit re-resume).
- C9 backoff floor adds ≤0.6s worst case to SIGKILL-doomed runs;
  deterministic crashes unaffected (immediate).
- C6 slot array saturates at 32 (documented; pending already set).
