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

## Read `DOCS/` before asserting anything about the engine

Added after a second round of avoidable work. The specifications live in
`DOCS/`, and they are precise, current, and cited from the code. Each of
these would have answered a question I had to guess at:

| question I had | the document that answers it |
|---|---|
| Is a batch atomic? Can a caller see partial output? | `INVARIANTS.md` §3 Batch Atomicity — "A batch is claimed whole or not at all" |
| What are the delivery guarantees per mode? | `RESILIENCE_PROTOCOL.md` §5.2 — ordered/buffered are EXACTLY-ONCE; realtime `-u` is AT-LEAST-ONCE and "NOT RECOMMENDED", because workers write straight to stdout and bytes cannot be recalled |
| How is partial output actually rolled back? | `RESILIENCE_PROTOCOL.md` §2.2 — TLS `worker_output_end`, snapshotted as `output_start` at claim, advanced only after a COMPLETE emit; `ftruncate`+`lseek` guarded by `S_ISREG`, pipes downgrade to at-least-once |
| Is the ingress memfd's file offset trustworthy? | `INVARIANTS.md` §20 — **it is undefined and must never be read.** There is a documented live offset-mover, and engine-side hardening is *halted per red lines for owner decision* |
| When is comparing output across runs valid? | `RESILIENCE_PROTOCOL.md` §7.3.3 — NUMA batch granularity varies run to run, so compare line multisets or joined bytes, "never over blob identity" |
| Which recovery paths are actually verified? | `RESILIENCE_PROTOCOL.md` §7.4 — explicitly NOT covered: recovery in `mode="spawn"`/`mode="plugin"` **streaming** |

Two of these are worth calling out because they are load-bearing and
were missed:

* **§5.2 is the contract behind the B-01 false alarm.** The mode-dependent
  delivery guarantees are written down. I asserted a single blanket
  byte-exactness across failure policies without reading which guarantee
  applied.
* **§7.3.3 independently confirms the byte-multiset decision** made in
  `tools/bench_splice.py` during Stage 4, for the same reason and in the
  same words. That one was arrived at correctly, but by reasoning from
  first principles rather than by reading.

## SHAPES.md and EOF_PROTOCOL.md — the frame, and the checklist

`SHAPES.md` is the architecture's mental model: one coordinate plane
(absolute byte offsets), one lattice `(major, minor)`, six control-flow
shapes, six derivation laws. `EOF_PROTOCOL.md` is Shapes 3 and 5 in
purest form and ends with an explicit audit checklist.

Applied to this work's own changes, three laws are load-bearing:

* **Law 3, every exit path publishes** (Shape 6). Ownership of a value
  downstream waiters consume must be written down as a truth table *at
  the site*. This is the law Stage 0's publication-after-commit work
  exists to satisfy.
* **Law 6, progress is irreversible.** No rollback of claims, no
  decrements of monotonic indices. The `conflicts()` design complies: it
  records a contradiction and keeps the first outcome rather than
  retracting state.
* **EOF §6, the co-polling checklist.** Every blocking poll that waits
  for data must also watch the EOF eventfd; the EOF eventfd is never
  `sys_read()`; escrow drain must terminate on EAGAIN with the re-arm
  flag cleared only after EAGAIN and `escrow_pending` TATAS-consumed.

### This found a real inconsistency in my own code

Applying Shape 6's truth-table discipline to `ReassemblyBuffer`
immediately produced a finding, and it was in code I had written this
session:

`add_disposition`'s docstring stated **"the FIRST outcome is kept"**,
and three of the four contradiction branches did exactly that. The
fourth — duplicate DATA — noted the conflict and then called `add()`,
which **overwrites**. So duplicate DATA was last-wins while every other
contradiction was first-wins: the docstring claimed one policy and the
code implemented another.

That is precisely Shape 6's failure mode — ownership that is not written
down as a truth table at the site is the gap where this bug class lives
— and it was a docstring/code divergence, which is the cheapest possible
bug to catch and the easiest to ship without noticing. Fixed to
first-wins, with a regression test that asserts the *first* payload
survives. First-wins is also the conservative direction for exactly-once:
a second delivery must not replace a payload that has already been
delivered.

### Flagged, not fixed: the truncated-tail claim

`_make_results_pump`'s docstring says a truncated tail is "a worker that
died mid-record, **never user data**". That is too strong for the pipe
case. `RESILIENCE_PROTOCOL.md` §2.2 states rollback is guarded by
`S_ISREG` and that **pipes downgrade to at-least-once** — a pipe cannot
be truncated, so partial output from a killed batch genuinely can appear
on one.

In practice the internal results pipe carries already-framed complete
records out of the worker memfds (memfds are `S_ISREG`, so rollback
works there), so the truncation source is the drain process rather than a
worker's mid-batch emit. The claim is probably right in spirit and
wrong in wording. It is pre-existing behaviour, not introduced here, and
changing truncation handling needs its own care, so it is recorded
rather than touched. Worth a maintainer decision on whether a truncated
tail should be surfaced rather than silently dropped.

**Open coverage gap, now documented:** §7.4 lists recovery in
`mode="spawn"` streaming as untested.
`python/tests/test_stage3_recovery_integrity.py` covers `mode="spawn"`
through `map()` with per-policy atomicity assertions, which closes the
`map` half. The `stream()` half remains unverified.

Also relevant and not yet acted on: `MAINTAINERS.md` §4–6 documents a
release matrix much broader than `python/release_check.py` — unit tests,
benchmarks, both UMA and NUMA topologies, plus TSan and ASan/UBSan
repeats. Per §4.1, `numa=fake=4` is the documented way to cover NUMA
without NUMA hardware, and this kernel has `CONFIG_NUMA_EMU=y`, so the
"NUMA needs suitable hardware" blocker reported previously is not a
blocker at all. The full matrix is not re-run here because no engine
change accompanied it (`frun.bash` and `forkrun_ring.c` are untouched
across this work), which is the documented exemption in §5's matrix
policy rule.

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
