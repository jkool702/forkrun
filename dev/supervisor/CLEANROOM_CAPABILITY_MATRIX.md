# Cleanroom capability matrix

**Generated. Do not edit by hand.** Regenerate with
`python3 tools/capability_matrix.py`; verify with `--check`.

WO-CM1 rebuilt this. The previous version was a truth table over
`_cleanroom_eligible()`, which answers only *"is this envelope
acceptable?"* -- never *"does a public call ever ask?"* Those
diverge at the current head in three independent ways, so this
document now reports the predicate's answer **and** the route the
public entry point actually takes.

| | |
|---|---|
| Cells enumerated | 60480 |
| Public-VALID cells | 17280 (28.6% of grid) |
| Cells rejected by public validation | 43200 |
| Predicate accepts (of valid) | 768 |
| **Launcher selected (of valid)** | **336 (1.94%)** |
| Distinct routes | 5 |

Percentages are against the **public-valid** denominator. The full
grid includes configurations no public call can make (iterable
sources, a missing path, a directory, `order="sorted"`); those keep
their conformance tests and are counted as *validation rejection*,
never as cleanroom refusals.

---

## Axes

- **entry**: `'map'`, `'stream'`, `'run'`
- **streaming**: `False`, `True`
- **source_kind**: `'path'`, `'fd'`, `'fileobj'`, `'iterable'`, `'missing'`, `'dir'`, `'bogus'`
- **mode**: `'plugin'`, `'udf'`, `'python'`, `'spawn'`, `'splice'`
- **nodes**: `1`, `2`, `4`
- **order**: `'none'`, `'index'`, `'sorted'`
- **orchestrator**: `True`, `False`
- **strict_poison**: `True`, `False`
- **return_stats**: `True`, `False`
- **resume**: `None`, `'state.json'`
- **checkpoint_file**: `None`, `'ckpt.json'`

`entry` and `streaming` are new in WO-CM1. See "Corrections" below
for what they made visible that the old axis set could not.

---

## Actual dispatch route

### Public-VALID cells

| Actual route | Cells | Share |
|---|---:|---:|
| `numa-pipeline` | 9216 | 53.3% |
| `splice-pipeline` | 3456 | 20.0% |
| `cleanroom-not-reached` | 2736 | 15.8% |
| `in-process/reactor` | 1536 | 8.9% |
| `cleanroom-selected` | 336 | 1.9% |

### All cells, including invalid ones

| Actual route | Cells | Share |
|---|---:|---:|
| `numa-pipeline` | 32256 | 53.3% |
| `splice-pipeline` | 12096 | 20.0% |
| `cleanroom-not-reached` | 10304 | 17.0% |
| `in-process/reactor` | 5376 | 8.9% |
| `cleanroom-selected` | 448 | 0.7% |

---

## Corrections this audit made

Each was verified against the live source and, where possible,
observed directly rather than inferred.

### 1. `run()` is never cleanroom-served

`run()` contains no cleanroom branch at all: 0 calls to
`_cleanroom_eligible`, 0 evaluations of `_cleanroom_enabled()`. It
dispatches straight to the NUMA, reactor, or in-process executor.
The previous matrix never mentioned `run`.

### 2. The predicate was unreachable for most of the grid

`map()` consults it only when the gate is on **and** `raw_mode` is
in `(plugin, udf, spawn)`. `stream()` only for `(plugin, udf)`. Every
other mode returns before the predicate is reached, so a cell could
satisfy the envelope and never be asked about it.

### 3. `stream()` reaches the predicate only when streaming

The call sits inside stream()'s streaming branch, so a materialised
source never consults it. Observed with a real plugin:
`stream(..., streaming=True)` selects the launcher; the same call
with `streaming=None` over a regular file does not.

### 4. Both `map()` and `stream()` bypass the predicate for NUMA

`num_nodes > 1` takes the NUMA path and returns before the
predicate (run.py:3834 for map, :4254 for stream).

### 5. The old denominator was inflated by 71.4%

Invalid configurations were counted against the capability
denominator. **256 cells were reported as served that no public call
could ever make** -- every one of them an iterable source, which
`_api._reject_iterable_source` rejects before any envelope check.

---

## Predicate outcomes (valid cells only)

| Outcome | Cells | Reason fragment |
|---|---:|---|
| `DECLINE_NODES` | 11520 | UMA single-node only (got nodes=2) |
| `DECLINE_RESUME` | 2592 | resume=/checkpoint_file= is not served; the launcher neith |
| `DECLINE_MODE` | 2304 | mode='plugin', 'udf' or 'spawn' only (got 'python') |
| `SERVED` | 768 |  |
| `DECLINE_STREAM_ORDER` | 48 | stream(order='index') is not served; the stream path has n |
| `DECLINE_MODE_STREAM_SPAWN` | 48 | stream(mode='spawn') is not served; the streaming path has |

---

## Oracle rules

| Rule | Fires on | Citation |
|---|---|---|
| `R1` | 0 | docstring: 'UMA single node -- no multi-node rings' |
| `R2` | 0 | docstring: 'mode=plugin -- it dlopens an object and calls an |
| `R4` | 0 | docstring: 'order in (none, index)'. The launcher forks no C |
| `R5` | 0 | CR-FIX1-K: the launcher neither transports nor implements ch |
| `R2b` | 0 | stream(mode='spawn') is not served; the streaming path has n |
| `R6` | 0 | docstring + inline note: the stream path has no collect step |
| `R8` | 0 | inline: a path that does not exist is not servable |
| `R9` | 0 | inline: a directory is not servable |
| `R10` | 0 | inline: source must be a path, an open descriptor, or an ite |

---

## Reproducing

```
python3 tools/capability_matrix.py            # write
python3 tools/capability_matrix.py --check    # fail if stale
python3 -m unittest discover -s python/tests -p test_capability_matrix.py
```

The expected behaviour is not taken from the predicate: it comes
from `tools/capability_oracle.py`, which imports nothing from
`forkrun`. The two agreeing is the evidence; neither alone is.

## Limitations not expressible as cell counts

- **Default is OFF.** `FORKRUN_CLEANROOM` is opt-in, so on a default
  configuration the launcher-selected row above is reachable but
  not *selected*. Capability and default behaviour are different
  questions; this table answers the first.
- **Artifacts are a separate axis.** A missing launcher or an
  incompatible UDF helper changes the route without changing any
  cell in this grid; they are tested as boundary conditions, not
  enumerated.
- **Fake NUMA is not physical NUMA.** `nodes="@N"` models the
  multi-node code path only.
- **Counts are synthetic.** They enumerate a configuration space;
  they are not an estimate of real-world usage.
