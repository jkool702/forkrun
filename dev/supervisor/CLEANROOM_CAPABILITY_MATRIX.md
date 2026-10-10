# Cleanroom capability matrix

**Generated. Do not edit by hand.** Regenerate with
`python3 tools/capability_matrix.py`; verify with `--check`.

Produced by `tools/capability_matrix.py` from the live
`_cleanroom_eligible` predicate. The expected behaviour is *not* taken
from the predicate: it comes from `tools/capability_oracle.py`, a module
that imports nothing from `forkrun`. The two agreeing is the evidence;
neither alone would be.

| | |
|---|---|
| Cells enumerated | 16128 |
| Served by the launcher | 40 (0.25%) |
| Declined | 16088 |
| Distinct outcomes | 11 |

---

## Axes

The axes are the facts a call carries to the envelope:

| axis | values |
|---|---|
| `kind` | 'map', 'stream' |
| `source_kind` | 'path', 'fd', 'fileobj', 'iterable', 'missing', 'dir', 'bogus' |
| `mode` | 'plugin', 'python', 'spawn', 'splice' |
| `nodes` | 1, 2, 4 |
| `order` | 'none', 'index', 'sorted' |
| `orchestrator` | True, False |
| `strict_poison` | True, False |
| `return_stats` | True, False |
| `resume` | None, 'state.json' |
| `checkpoint_file` | None, 'ckpt.json' |

### Two corrections to the roadmap's axis list

**1. Replayability is not an eligibility axis.** Roadmap section 4.1
lists `{replayable, non-replayable}` among the envelope axes. It is not
an input to `_cleanroom_eligible` at all. Replayability is computed in
the *outcome* contract, after the launcher has run:
`replayable = pre_ingest or _source_is_reopenable(source)` (run.py:1025)
and gates `may_fallback`. It answers "may we fall back?", not "may the
launcher serve this call?". Conflating the two would make the matrix
claim to predict something it cannot observe.

**2. `return_stats` is a real axis, and the roadmap omits it.** It is a
parameter of the predicate and of the dispatch sites. It is a
**constant axis**: the predicate never consults it, so it always
serves. It is kept in the matrix anyway, because an axis that is
currently constant is exactly what a future change would silently
start varying.

## Outcomes

Every cell resolves to exactly one of these. There are no others:
the enumeration produces no `UNCLASSIFIED` cell.

| # | outcome | cells | example |
|---|---|---|---|
| 1 | `DECLINE_NODES` | 10752 | `Facts(kind='map', source_kind='path', mode='plugin', nodes=2, order='none', orchestrator=True, strict_poison=True, return_stats=True, resume=None, checkpoint_file=None)` |
| 2 | `DECLINE_MODE` | 4032 | `Facts(kind='map', source_kind='path', mode='python', nodes=1, order='none', orchestrator=True, strict_poison=True, return_stats=True, resume=None, checkpoint_file=None)` |
| 3 | `DECLINE_ORCH` | 672 | `Facts(kind='map', source_kind='path', mode='plugin', nodes=1, order='none', orchestrator=False, strict_poison=True, return_stats=True, resume=None, checkpoint_file=None)` |
| 4 | `DECLINE_RESUME` | 336 | `Facts(kind='map', source_kind='path', mode='plugin', nodes=1, order='none', orchestrator=True, strict_poison=True, return_stats=True, resume=None, checkpoint_file='ckpt.json')` |
| 5 | `DECLINE_ORDER` | 224 | `Facts(kind='map', source_kind='path', mode='plugin', nodes=1, order='sorted', orchestrator=True, strict_poison=True, return_stats=True, resume=None, checkpoint_file=None)` |
| 6 | `SERVED` | 40 | `Facts(kind='map', source_kind='path', mode='plugin', nodes=1, order='none', orchestrator=True, strict_poison=True, return_stats=True, resume=None, checkpoint_file=None)` |
| 7 | `DECLINE_STREAM_ORDER` | 28 | `Facts(kind='stream', source_kind='path', mode='plugin', nodes=1, order='index', orchestrator=True, strict_poison=True, return_stats=True, resume=None, checkpoint_file=None)` |
| 8 | `DECLINE_STREAM_POISON` | 14 | `Facts(kind='stream', source_kind='path', mode='plugin', nodes=1, order='none', orchestrator=True, strict_poison=True, return_stats=True, resume=None, checkpoint_file=None)` |
| 9 | `DECLINE_SOURCE_MISSING` | 10 | `Facts(kind='map', source_kind='missing', mode='plugin', nodes=1, order='none', orchestrator=True, strict_poison=True, return_stats=True, resume=None, checkpoint_file=None)` |
| 10 | `DECLINE_SOURCE_DIR` | 10 | `Facts(kind='map', source_kind='dir', mode='plugin', nodes=1, order='none', orchestrator=True, strict_poison=True, return_stats=True, resume=None, checkpoint_file=None)` |
| 11 | `DECLINE_SOURCE_TYPE` | 10 | `Facts(kind='map', source_kind='bogus', mode='plugin', nodes=1, order='none', orchestrator=True, strict_poison=True, return_stats=True, resume=None, checkpoint_file=None)` |

## The oracle's rules

Evaluated **first-match-wins**. Each is the contract's own words.

- **R1 `nodes`** &rarr; `DECLINE_NODES`  
  docstring: 'UMA single node -- no multi-node rings'
- **R2 `mode`** &rarr; `DECLINE_MODE`  
  docstring: 'mode=plugin -- it dlopens an object and calls an entry point'; and the plugin must export forkrun_use_ctx, since a plugin without it is driven by the legacy ARGV/stdout route whose output lands on the worker's stdout, not the memfd -- exit 78, not silent success with an empty result set
- **R3 `orchestrator`** &rarr; `DECLINE_ORCH`  
  docstring: 'orchestrator=True ONLY'. W-CR4 made the launcher supervise unconditionally, with no flag to disable it, so serving False would hand a caller who asked for fail-fast silent batch recovery instead
- **R4 `order`** &rarr; `DECLINE_ORDER`  
  docstring: 'order in (none, index)'. The launcher forks no C orderer, but does not need to: collect_records sorts by index for map, and stream reassembles parent-side from the batch_idx already in the framing
- **R5 `resume/checkpoint`** &rarr; `DECLINE_RESUME`  
  CR-FIX1-K: the launcher neither transports nor implements checkpoint/resume. The check sits ABOVE the streaming block, so it applies to map() too -- it used to live under `if streaming:`, which made the refusal unreachable for map(), and the map() dispatch site did not pass the arguments, so a resume request was silently dropped on an accelerated path
- **R6 `stream+order`** &rarr; `DECLINE_STREAM_ORDER`  
  docstring + inline note: the stream path has no collect step to sort with, and its parent-side reassembly handles order='none' only. NOTE the asymmetry with R4: map SERVES order='index', stream does not. A single predicate holds both, deliberately
- **R7 `stream+strict_poison`** &rarr; `DECLINE_STREAM_POISON`  
  docstring: strict_poison is served for map via the counter channel ([version][poisoned] written to a memfd after the join, relying on g_state being SHARED). But no poison count reaches a streaming caller, so stream declines it
- **R8 `source missing`** &rarr; `DECLINE_SOURCE_MISSING`  
  inline: a path that does not exist is not servable
- **R9 `source directory`** &rarr; `DECLINE_SOURCE_DIR`  
  inline: a directory is not servable
- **R10 `source type`** &rarr; `DECLINE_SOURCE_TYPE`  
  inline: source must be a path, an open descriptor, or an iterable

## Precedence

The order of declines is part of the contract: when several conditions
hold at once, the winner is the message the caller actually sees.

- **R1-R7 precedence is load-bearing.** Several can hold simultaneously
  (nodes=2 *and* mode="python" *and* orchestrator=False), so reordering
  these silently changes observable behaviour.
- **R8-R10 precedence is immaterial.** They classify mutually exclusive
  source kinds; at most one can hold. Their relative order carries no
  contract weight.

## Contract points that were historically wrong

These are the assertions carrying the most weight, because each
corresponds to a defect that actually reached this codebase. A generic
rule check would not catch a regression in any of them.

| assertion | expected | why it matters |
|---|---|---|
| `resume_is_refused_for_map_not_just_stream` | `DECLINE_RESUME` | CR-FIX1-K: the refusal was unreachable for map() because the check lived under `if streaming:`, and map()'s dispatch site never passed resume at all -- so the envelope could not see it |
| `orchestrator_true_is_served` | `SERVED` | the orchestrator gate used to be False-only; W-CR4 made True the only servable supervision model |
| `map_serves_order_index` | `SERVED` | ordering is applied downstream by shared code, so the launcher needs no C orderer to honour it |
| `map_serves_strict_poison` | `SERVED` | served via the counter channel; both were previously declined and return_stats was a live P0 bug reporting poisoned=0 for a run that had poisoned batches |
| `stream_declines_order_index_that_map_serves` | `DECLINE_STREAM_ORDER` | asymmetry is intentional; a second hand-written predicate at the stream() dispatch site had already drifted from the map() one once, requiring not-orchestrator while this one required orchestrator |
| `stream_serves_order_none` | `SERVED` | the stream path's actual envelope |
| `descending_precedence_puts_orchestrator_before_order` | `DECLINE_NODES` | five decline conditions hold simultaneously. R1 wins, so the caller is told about nodes first rather than about the last thing checked |
| `resume_outranks_stream_order` | `DECLINE_RESUME` | R5 sits above the streaming block precisely so that resume is refused before the stream/order distinction is consulted |

---

Next: the independent oracle is `tools/capability_oracle.py`; the
agreement test is `python/tests/test_capability_matrix.py`.
