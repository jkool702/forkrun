# Cleanroom route inventory and performance-evidence reconciliation

WO-CR-ROI-2 Phase A. `NEW/REFACTOR4.2` @ `757742f4`. No production changes.

## Method: how "did the launcher really run?" was established

A spy on `_execute_cleanroom` is **insufficient and was rejected as a
detector**: that function is also entered when the launcher is missing,
and then falls back in-process — so it fires identically whether the
launcher ran or not. WO-ROI-1 already added a test that depends on
this distinction.

The detector used here replaces the launcher path with a wrapper that
records **its own exec** and then `exec`s the real binary unchanged:

```sh
: "${FORKRUN_EXEC_MARKER:?}"
printf '%s\n' "$$" >> "$FORKRUN_EXEC_MARKER"
exec "$REAL_LAUNCHER" "$@"
```

Every route below therefore reports actual launcher process executions,
not function entries.

## A1. Route inventory

| Route | Reached when | Real launcher exec | Route-level test today |
|---|---|---|---|
| `map(plugin)` | mode=plugin, gate on, envelope accepts | **yes** | **yes** — `_run_marked` spy |
| `map(udf)` | mode=udf, gate on, **helper for this minor present**, envelope accepts | **yes** | **no** — output only |
| `map(spawn)` | mode=spawn, gate on, envelope accepts | **yes** | **no** — output only |
| `stream(plugin)` | mode=plugin, gate on, **streaming branch**, order=none | **yes** | **no** — output only |
| `stream(udf)` | mode=udf, gate on, streaming branch, helper present | **yes** | **no** — output only |
| `stream(spawn)` | — | **no**, correctly | n/a |
| `run(*)` | — | **no**, no dispatch | n/a |
| NUMA / splice / resume | — | **no**, declined before predicate | n/a |

Five routes execute the launcher. `stream(spawn)` does not, which matches
the capability contract — stream has no spawn dispatch.

### Conditions discovered that were not previously stated

- **`stream` reaches the route only with `order="none"`.** The
  `stream(order="index")` envelope is declined by design (no collect
  step to sort with), so it falls back and never launches.
- **`stream(udf, order="index")` RAISES rather than degrading.** With the
  gate on, the declined envelope falls back to the in-process path,
  which does not implement udf, and the caller gets
  `NotImplementedError: v0 supports mode='python' only`. So one declined
  configuration produces an error rather than a safe fallback. Recorded
  as a route-robustness gap; see Phase B.
- **`map(udf)` cannot work in-process at all** — the same
  `NotImplementedError`. udf is cleanroom-only, so a missing helper has
  no in-process equivalent.

### Two findings that were MY errors, not defects

- A UDF route initially appeared to return 0 records. The cause was
  mine: the fixture module must be on the **parent's `sys.path`**
  because `_udf_dir()` scans it there (the existing test inserts it
  there rather than setting `PYTHONPATH`), and my first payload called
  `os.getcwd(batch)`, which raises.
- `map(udf)` then appeared "not byte-exact" with >1 worker. It was not
  a defect: `order="none"` returns **worker-completion order**, and no
  line was missing or duplicated — only reordered. With `order="index"`
  it is byte-exact at 1, 2 and 4 workers. The lesson for Phase B is that
  byte-exactness must be asserted under `order="index"`, and unordered
  runs compared by record identity, never by position.

## A2. Performance evidence — my earlier claim was WRONG

`CLEANROOM_DEFAULT_ON_DECISION.md` states there is "no cleanroom-specific
performance evidence". **That is false.** The evidence exists and the
harness is methodologically sound.

`python/benchmarks/bench_cleanroom.py` implements exactly what §D2 asks
for: sequential (never concurrent), **paired interleaved A/B** so drift
hits both arms, warmup discarded, **medians alongside means** because
startup timing is skewed, and an **exactness guard that refuses to
report a number for wrong output** — comparing against an independently
run in-process reference, explicitly *not* the input size, because the
plugin transforms records.

It runs `forkrun.map(spec, path, mode="plugin", nodes=1,
output="bytes", orchestrator=False)` — i.e. the `map(plugin)` route.

Recorded in the `_cleanroom_enabled()` docstring, on the same machine
(i9-7940X 14c/28t), 28 workers, UMA, both THP regimes:

| parent RSS | startup THP=never | startup THP=always | e2e THP=never | e2e THP=always |
|---|---|---|---|---|
| 30 MB  | 16.24 → 6.34 (2.56x) | 17.37 → 11.05 (1.57x) | 294.5 → 203.8 (1.45x) | 264.0 → 168.9 (1.56x) |
| 554 MB | 118.88 → 15.28 (7.78x) | 200.58 → 27.00 (7.43x) | 330.6 → 212.9 (1.55x) | 349.9 → 189.4 (1.85x) |
| 2127 MB | 454.68 → 42.35 (10.74x) | 734.83 → 71.67 (10.25x) | 665.6 → 248.3 (2.68x) | 863.3 → 228.3 (3.78x) |

Status: **historical, provenance sound, currency unverified.** The
corpus (532 MB) and harness are present and runnable, but the numbers
predate C0.7 and WO-ROI-1's changes to `run.py`, and the docstring does
not record which commit produced them. Per §A2 the harness is reusable
after validating provenance, and Phase D re-runs the smallest question
rather than the whole sweep.

The advantage is real and grows with parent RSS, which is coherent with
the stated mechanism (workers must not fork from a large address space).
The 30 MB e2e gain is the weakest (1.45x) and is the case §D2's
"excessive startup cost in the ordinary small-workload case" targets.

## Phase A conclusion

- Five routes are genuinely launcher-backed; only one has route-level
  test evidence. Four need tests (Phase B).
- The performance evidence exists and contradicts my earlier decision
  note; Phase D must re-measure for currency before any default change.
