# Work log — WO-PY-UDF-FALLBACK-1

**Contract source:** `dev/supervisor/UDF_ROUTE_EXTENSION_IMPORT_DEFECT.md` §6
and §7 (the work order), plus the documented promise in
`python/forkrun/run.py:4481` (`_coerce_payload`'s docstring).

## 1. What is missing or incorrect

`mode="udf"` **raises** when the helper file for this minor is present
but the `map-udf` route is not selected for the call — which is the
DEFAULT configuration (the cleanroom is opt-in).

Reproduced on this tree at `8ac54de1`, cleanroom off (the default):

    helper path: .../python/forkrun/_fr_udf.cpython-314-x86_64-linux-gnu.so
    FORKRUN_CLEANROOM: None
    RAISED: NotImplementedError: v0 supports mode='python' only (spawn/plugin are Stage 5)

The documented contract is the opposite: *"mode='udf' is not an error,
and the documented fallback is the in-process path, which runs the UDF
in THIS interpreter."* A fallback that raises is not a fallback.

The in-process fallback fires only when the helper file is ABSENT
(`_coerce_payload` consults `_udf_helper_path()`), which is why
`test_udf_mode.py::test_a_missing_helper_falls_back_and_still_produces_results`
passes today — it monkeypatches `_udf_helper_path` to return `None`.
That test therefore does **not** distinguish the desired behaviour
from the broken one: it exercises the helper-absent case, which
already worked.

## 2. The intended contract

`mode="udf"` must fall back to the in-process path whenever the
`map-udf` route is not selected for that call. Two distinct
conditions must both land on the in-process path:

| condition | today |
|---|---|
| helper file absent (not built for this minor) | in-process ✓ |
| helper file present, route not selected | **raises** ✗ |

And the route-selected case must be unchanged: the cleanroom serves
the UDF, and the user's module is imported in the LAUNCHER, not in the
parent.

## 3. The authoritative implementation

`_coerce_payload` (`python/forkrun/run.py:4481`) is the single place
that decides *"UDF spec → `_UDFPayload` for the cleanroom route"* vs
*"UDF spec → in-process callable"*. It already carries the mechanism
(`force_inprocess_udf`) for the case where the launcher has positively
declined the helper.

The decision the fix needs is one the CALLER owns: **the in-process
executors run the UDF; the map-udf route does not.** So the new
authoritative helper is

    _coerce_payload_inprocess(payload, mode)

which is the ONE statement of that decision, and every in-process
call site uses it. The route-selected path keeps using
`_coerce_payload` unchanged.

## 4. Call sites

| site | path | today | after |
|---|---|---|---|
| `run.py:1466` | stream pre-ingest decline | already forced ✓ | unchanged ✓ |
| `run.py:1624` | `_cleanroom_attempt` compat refusal | already forced ✓ | unchanged ✓ |
| `run.py:4691` | `run()` NUMA | mode "udf" is rejected by `run()` ✓ | unchanged ✓ |
| `run.py:4706` | `run()` UMA | mode "udf" is rejected by `run()` ✓ | unchanged ✓ |
| `run.py:4940` | `map()` NUMA | **raises** ✗ | in-process ✓ |
| `run.py:5049` | `map()` spawn branch | n/a ✓ | unchanged ✓ |
| `run.py:5129` | `map()` UMA | **raises** ✗ | in-process ✓ |
| `run.py:5364` | `stream()` NUMA | **raises** ✗ | in-process ✓ |
| `run.py:5382` | `stream()` UMA | **raises** ✗ | in-process ✓ (see below) |

### The ordering constraint in `stream()`

`stream()` coerces at 5382, BEFORE its cleanroom dispatch (5409+).
The cleanroom path uses `raw_payload`/`raw_mode` and returns early, so
the coerced values are used only by the in-process path — but the
coercion itself must NOT resolve the UDF spec in the parent when the
cleanroom might serve the call, because resolving the spec imports the
user's module into the parent that forks every worker (the reason the
`_UDFPayload` branch exists at all).

So `stream()` re-coerces for the in-process path AFTER the cleanroom
dispatch, and only then (mode "udf" → "python"). `map()` needs no
reordering: its coercion already sits after the cleanroom attempt.

## 5. Which tests distinguish the desired behaviour

- `test_a_missing_helper_falls_back_and_still_produces_results` —
  helper ABSENT. Passes before and after the fix; it does not
  distinguish.
- The new test must keep the helper PRESENT and make the route not
  selected — the case that raises today.
