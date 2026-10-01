# FLAKEFIX Diagnosis — background-launch SigIgn poisoning (M1a family)

Date: 2026-09-29. Tree: `9e7e4ca` (fake-4 boot, same as W-FAKE4).
Target: `test_taxonomy.TestTaxonomyShape.test_death_cause_mapping`.

## 1. Reproduction recipe (exact)

- FAILS: `nohup bash -c 'python3 -m unittest tests.test_sweep tests.test_taxonomy' &`
  — 12/12 backgrounded runs (also every nohup-backgrounded full suite: UMA ×3,
  fake-4 ×2, canary, pre-fix control).
- PASSES: the identical command foregrounded — 4/4, plus isolated module 9/9.
- The discriminator is the trailing `&` (background launch), not test order,
  not load, not topology.

## 2. Mechanism verdict: launcher bequeaths SIGINT=SIG_IGN (M1a, known family)

Instrumented failing run (`test_taxonomy_dbg`, same position):

```
DBG dispositions: TERM=0 INT=1 SEGV=0
DBG sigmask=set()
DBG sig=15: SIGNALED=True exitcode=-15
DBG sig=2: SIGNALED=False exitcode=42
```

`INT=1` is `SIG_IGN`: shells with job control off ignore SIGINT/SIGQUIT for
async children. Python honors a pre-ignored SIGINT (does NOT install
`default_int_handler`), the forked child inherits the ignore, `os.kill(child,
SIGINT)` becomes a no-op, the child falls through to `os._exit(42)`, and
`assertTrue(os.WIFSIGNALED(st))` fails on the sig=2 iteration. Sigmask empty;
no test or product code involved — a plain `forkrun.map` leaves all
dispositions and the mask untouched (probed directly).

This is the W-REL5-D incident verbatim ("taxonomy self-kill tests fail
(TERM/INT ignored → exit 42, WIFSIGNALED false)"; RUNBOOK §6 standing rule:
signal-sensitive suites never run under bare `nohup`). The W-FAKE4
"suite-order" framing was wrong; the neighborhood bisect was a red herring
(the 5-module window reproduced only because it too was background-launched —
both "halves" failed for the same launcher reason, and foreground repeats of
the identical pairs pass).

## 3. Fix tier: (b) self-isolation

Outcome (a) does not apply — no test leaks (verified: post-sweep dispositions
pristine, mask empty, single thread). The leak source is the operator's shell,
outside the repo. Hardening `test_death_cause_mapping` to pin `SIG_DFL` for
exactly the catchable signals it self-kills with (TERM/INT/SEGV; KILL cannot
be set and needs nothing) with `addCleanup` restore makes the test immune in
every launch context. No product contact (probe-proven clean) — §4 boundary
not triggered. Docstring cites this file and the family.

## 4. Lock-in and gates

- Bite: backgrounded `tests.test_taxonomy` alone pre-fix (fails) → post-fix ×10 green.
- Full discovery-order suite ×3 green **foregrounded** (backgrounded runs stay
  green too post-fix — the test no longer depends on launcher state).
- `release_check`: exactly one red = changelog-finality (designed-red).
