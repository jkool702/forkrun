# Python front end: parity with frun.bash, not reinvention

**Principle, stated by the maintainer, 2026-10-12:**

> the bash front end is the official "approved" way to do things. the
> python front end development should be, in general, "as close to parity
> with how the bash front end works as is possible". Try not to re-invent
> the wheel in python - the way bash works usually is near ideal

This is a standing constraint on Python work, not advice for one patch.
It changes what "done" means: a Python feature is done when it *delegates*
to the same mechanism bash uses, not when it produces the same answer.

## Why it matters here specifically

`frun.bash` and the Python front end share the same C core. `python/
forkrun/_shim.c` is explicit that it reuses the ring's internals rather
than forking them:

```
 * tls_batch_*, escrow pipes) and static helpers (do_lockfree_claim,
 * ring_init_main, ring_ack_main, ring_destroy_main, core_scanner_loop,
```

`fr_py_claim` wraps `do_lockfree_claim`; `fr_py_recover_worker` wraps
`ring_recover_worker_core`; `fr_py_orderer` is `ring_order_main`. That is
the pattern to keep extending. The claim/ack/recover state machine has
exactly one implementation, which is the main reason the two front ends
have not drifted apart catastrophically.

## Audit: where Python currently diverges (2026-10-12)

### 1. Two orderers exist — C for the reactor, Python for splice+map

`run.py:14` states the divergence as deliberate:

> the emitter TRANSPORTS; it does not order — batch_index is the
> execution identity/ordering key and the parent does optional
> consumer-side reassembly (map(order="index") sorts; **the C orderer is
> skipped by design**)

In practice (`_execute_reactor_locked`, `_execute_streaming_reactor`,
`_execute_ingest_reactor_locked`) the Python front end forks
`fr_py_orderer` — the C orderer, bash's `ring_order` — exactly as bash
does. Good parity.

The exception is named in the code:

```python
# C orderer for collect+index (non-splice only: the splice
# loop never sends OrderPackets, so the orderer would emit
# nothing — splice keeps Python parse+sort).
use_orderer = (collect and order == "index" and not splice
               and _v1a(lib).get("orderer"))
```

So **the splice path uses the Python `ReassemblyBuffer`**, and the C
orderer is unavailable there because splice emits no OrderPackets.

**Measured cost: none.** 18.5 MB through the splice path, median of 3:

| workers | order=none | order=index | overhead |
|---|---|---|---|
| 8 | 0.0340s | 0.0339s | −0.4% |
| 32 | 0.0599s | 0.0588s | −1.8% |

Splice moves bytes in sequence, so batches complete roughly in order and
the Python sort has nothing to do. **This is therefore not a performance
argument**, and anyone citing these numbers to justify the split would be
citing them for the opposite of what they show.

The argument for closing it is maintenance and semantics:

* two orderers means every ordering-semantics change must be made twice;
* the split has already produced an observable divergence — `map(order=
  "index")` serves, `stream(order="index")` declines, because the Python
  reassembly handles only `order="none"` for streaming;
* the C orderer carries capabilities the Python one does not: NUMA
  ordering (`numa_mode`), `sendfile` zerocopy for regular-file output,
  and explicit `O_APPEND` handling.

**Direction:** make the splice loop emit OrderPackets so the C orderer
applies there too, and delete the Python orderer once nothing needs it.
Not attempted yet — it touches the splice fast path, and a measurement
showing zero cost means there is no urgency, only tidiness.

### 2. The disposition protocol is a genuine Python addition

`DATA / NO_RESULT / SKIPPED / POISONED` terminal records do not exist in
bash, which signals a skipped batch with a `P:<idx>:<kills>` line on the
trap-ack pipe. This is new surface, not reinvention, and
`ReassemblyBuffer` carries it.

Consequence worth watching: `conflicts()` and the reassembly buffer's
outcomes are specified only in Python, so the bash front end cannot serve
as the parity reference for them. Where a Python-only concept has no
bash counterpart, the specification has to live in the Python docs, and
that is where a future reviewer should look for drift rather than at
`frun.bash`.

## The failure mode this is meant to prevent

Four defects in four consecutive rounds shared a shape: **an assertion
that could not fail.**

| round | test | what it actually proved |
|---|---|---|
| 6 | spawn never reached the launcher | the OUTPUT was right |
| 7 | teardown sent SIGTERM | a process with no handler existed |
| 7 | ceiling test mutation | the mutation silently did not apply |
| 8 | recovery integrity | the wrong contract was asserted |

None was found by reading more Python. Two were found by checking the
C core, one by mutation, and one by reading `frun.bash` — the reference
implementation, sitting in the repository root the whole time.

When a Python implementation is a reimplementation, an assertion that the
answer is *plausible* is not an assertion. The bash side is where
"plausible" gets checked.
