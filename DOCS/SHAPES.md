# SHAPES.md — The Control-Flow Shapes of forkrun

*How to read the codebase: one coordinate system, six shapes, everything derives.*

This document describes the **frame** that makes forkrun's complexity collapse into inevitability. PHYSICS.md gives you the metaphor (the river, the conservation laws); this document gives you the engineering content of that metaphor — precisely enough that you can *predict* the code before reading it. A maintainer who has loaded this frame can answer "where would X live?" and "what must Y's exit paths do?" without a tour guide.

The test of the frame is §4: prediction drills. If you can answer those from the frame alone, the frame works. If you can't, the frame has a hole — and that hole is a finding about the architecture, not just the doc.

---

## §0 — The Coordinate System (the ground truth)

**All of forkrun speaks one language: absolute byte offsets into the append-only memfd.**

```
  0 ───────────────────────────────────────────────────────────────────► EOF
  [── Fallowed ──][── Active Workers ──][── Scanned ──][── Ingested ──]
        │                │                  │               │
   hole-punched      claimed slots      ring slots      raw chunks
   (fallow)          [start, end)       [start, end)    [raw_off, raw_off+len)
```

On top of the byte plane rides one lattice: **(major, minor)** — the chunk index and within-chunk batch index — which the orderer uses to merge per-node streams into global order.

Three properties make this a *coordinate system* rather than a convention:

1. **Universality.** Every subsystem — ring, escrow packets, fallow intervals, orderer heap, resume ledger, plugin ABI (`batch_offset`), count chain (`cum_lines` counts *delimiters over this plane*), handoffs (`actual_end` is a coordinate) — names data by the same numbers. No subsystem maintains its own numbering. There are no conversions at subsystem boundaries.
2. **Immutability.** A coordinate names the same bytes forever. `fallocate(PUNCH_HOLE)` removes the physical mass behind a coordinate without moving the coordinate. A batch in flight, a batch in escrow, and a batch in the resume ledger are *the same datum*.
3. **Derivability.** State that can be computed from coordinates is computed, never stored or transferred. The canonical examples: `-L`'s pending-line carry is `cum_lines mod L` (derived, not transferred — the L0/B0 design was rejected for exactly this reason); UMA's `-n` budget derives from `total_scanned`; the resume jagged edge is a set of intervals on the plane.

**Why this matters more than anything else in this doc:** mechanism reuse is only safe in a coordinate-coupled system. A pointer can be used only by whoever holds it; a number can be used by anyone who can read it. That's why one pipe can carry ordering *and* backpressure *and* checkpoint accounting — they're all numbers in the same currency. The textbook alternative — reference-coupled objects, ownership, GC — would need locks, refcounts, and would make every reuse in §2 impossible or dangerous.

**The counterfactual that proves it:** every serious bug in the v3.4→v3.5 development cycle was a coordinate-discipline violation. The multiple incompatible clamp variants of the `-n` bug were *independent numbering schemes for the same stream position*. The publication-gate failure was *state that should have been derived being instead transferred and then retracted*.

**NOTE**: The "coordinate system" logic described above applies to both the global data memfd (INPUT) and the per-worker output memfds (OUTPUT). However, its worth noting that input and output have separate coordinate systems, both of which take the shape described above.

---

## §1 — The Six Shapes

These are the control-flow patterns. Every subsystem is one of these shapes wearing different constants. Learn the shapes plus §0, and the codebase is O(shapes + coordinates) to hold in your head, not O(subsystems × interactions).

For each shape: the invariant, the canonical site, and what breaks without it.

### Shape 1: Monotonic Claim (`atomic_fetch_add`, no rollback)

**Invariant:** an index advances only, via one atomic RMW; each slot is claimed by exactly one party; there is no CAS retry loop on the fast path.

**Canonical sites:** worker claim (`read_idx`), scanner chunk claim (`chunk_queue_tail`), ingest slot assignment (`chunk_queue_head`).

**What breaks without it:** ABA hazards, contention (the thing CAS-retry designs trade away), and — worse — any rollback logic becomes possible, and rollback logic is where the 25/30-line bug class lived. The physics: the river flows one way. If you're tempted to write a compare-and-swap retry, the design is telling you the *structure* is wrong, not the synchronization.

### Shape 2: Publish-Before-Claim (release/acquire handoff)

**Invariant:** write the payload, *then* publish the index that makes it visible, with release semantics; consumers acquire-load the index, then read the payload. Readers never observe an uninitialized slot.

**Canonical sites:** scanner→ring slot publication (`write_idx`), indexer→`actual_end`, scanner→`cum_lines` (the gate values of `-n`/`-L`).

**What breaks without it:** torn reads on the ring arrays; a worker claiming a slot whose `end_ring` entry is stale. Memory-ordering bugs here are silent until a weakly-ordered core or an unlucky interleaving reveals them — this is why the sanitizer matrix exists.

### Shape 3: Bounded Wait with Terminal-State Escape

**Invariant:** *never wait, unboundedly, for data a process that has exited was supposed to produce.* Every cross-process wait must (a) re-check globally-visible terminal state every iteration — `limit_cutoff_major`, `emergency_abort`, scanner-finished flags — and (b) poll with a bounded timeout so the escape is actually re-checked.

**Canonical sites:** the `-n`/`-L` scan gate (`WAIT_FOR_CUM_LINES_OR_CUTOFF`, the `-L` handoff gate), the worker EOF poll, the scanner's ingest wait.

**What breaks without it:** the EOF-hang bug class. Every hang in the v3.4.x cycle was this shape missing its escape: a scanner blocked on `cum_lines[3]` whose producing scanner had already exited via `limit_reached`. The corollary invariant — **every exit path publishes every value downstream waiters consume** — is the producer-side half of this law. Enumerate the exit paths: normal completion, carry/skip, cutoff-skip, EOF sentinel, abort. Each one publishes. The byte-mode ownership bug was a violation of the corollary (an exit path — indexer publication in byte mode — silently stopped publishing a value the scanner waited on).

### Shape 4: Spin-Then-Sleep with Saturated Backoff

**Invariant:** for waits bounded by a *known physical timescale* (a 2MB SIMD scan is ~hundreds of µs), spin first with exponentially widening gaps, saturating the gap at tens of µs; sleep only as the unexpected regime, with the wake armed by an eventfd the producer *always* fires on the resolving publication.

**Canonical sites:** the gate waits (post-v3.5.0 backoff fix), worker claim wait (spin 100 → poll), indexer meta wait.

**What breaks without it:** the latency cliff. A fixed 10k-iteration spin drops into a 100ms poll while the event completes in 300µs — a 10³ discontinuity on the *serialized hot path* of `-n`/`-L`, where every gate wait is dead time on the global critical chain. The two load-bearing details: the backoff must saturate (never grow past context-switch latency), and the producer-side "always fire evfd_meta on gate-resolving publishes" rule must hold — if that `sys_write` ever looks redundant and gets optimized away, the insurance poll silently becomes the common path. That rule is currently a comment at the site; it belongs in §6 of ARCHITECTURE's contracts list.

### Shape 5: Advisory Wakeups over Monotonic Truth

**Invariant:** eventfds and signals gate *sleeping only*. Correctness decisions are made from indices and flags, never from wake counts, ordering, or delivery. Missed and spurious wakeups are both harmless.

**Canonical sites:** every poll in the codebase; the whole reason EOF_PROTOCOL.md can say "spurious wakeups are allowed."

**What breaks without it:** any code that assumes "I was woken, therefore state X" — the wakeup is evidence you may re-check truth, never truth itself. This shape is what makes Shape 3's bounded polls safe: a lost wakeup costs latency (the next timeout re-checks), never correctness.

### Shape 6: Owner-Publishes-on-Every-Exit (the truth tables)

**Invariant:** each piece of shared state has exactly one owner; the owner publishes it on every path by which control leaves the region where it's responsible. Ownership is written down as a truth table at the site.

**Canonical site and truth table** — `actual_end` in `ChunkMeta`:

| Mode | Delimiter search? | Publishes `actual_end`? | Publisher |
|---|---|---|---|
| normal | yes | yes (delimiter-aligned) | indexer |
| byte | **no** | **yes (raw chunk end)** | indexer |
| `-L` | no | no | **scanner** (handoff chain) |

### Cross-File Contracts Summary

- **(H1) Poison Flag Lifecycle:** C writes `RING_NUM_KILLS`, `RING_POISONED`, `RING_BATCH_IDX` only when `num_kills > 0`; wrapper clears them after every ack.
- **(M1) Zero-Length Sentinel Batches:** Zero-length sentinel batches must be acked but never executed (`[[ "$REPLY" != "0" ]]`).
- **(H2) `actual_end` Ownership:** Enforces the truth table above across indexers and scanners.
- **(H3) Closed Hydraulic Backpressure:** Sizing the worker→orderer ack pipe to 4 KiB propagates consumer backpressure through the ring buffer.

**What breaks without it:** the byte-mode hang — a refactor that moved publication inside the search's conditional, so byte mode (skip-search-keep-publish) and `-L` (skip-both) were collapsed into one branch. Three cases became two; the third case's consumers deadlocked. The general lesson: **when a mechanism serves multiple owners, the ownership is only as durable as the truth table that declares it.** Undeclared reuse is the gap where this bug class lives.

---

## §2 — The Compositions (where the complexity actually lives)

Individual shapes are simple. forkrun's apparent complexity is *one mechanism serving multiple roles* — which the coordinate system makes safe. These case studies are the proof. For each: what the textbook version would look like, and why the coordinate version is smaller, faster, or both.

### 2.1 The Count Chain

`cum_lines` in `ChunkMeta` began life as a line count for `-n`. It became:

- **the `-n` budget substrate** (scanner M's exact starting count, enabling prefix-exact clamping),
- **the `-L` scanner-handoff channel** (gating serialized scanning; the pending carry is *derived* as `cum_lines mod L`),
- and the candidate substrate for future **output backpressure** (a consumer-progress coordinate on the same plane).

One cache-line field, release-published, consumed by three features. The textbook version: a distributed counter service for `-n`, a leader-election protocol for `-L` serialization, a separate flow-control channel. forkrun's version: one monotonic integer in the plane.

### 2.2 The Ack Pipe

`ring_ack`'s order pipe carries `OrderPacket`s — (major, minor, byte range, output range) in stream coordinates. Because the packets are coordinates:

- they drive **the orderer's min-heap merge** (their original job),
- they accumulate into the **resume ledger** (the seqlock tracker absorbs each packet's interval),
- and — once the pipe is sized to one page instead of 1MB — they carry **output backpressure**: a slow consumer blocks the orderer, the orderer stops draining the pipe, workers block writing acks, `read_idx` stalls, the ring fills to the shield, the scanner stops, ingest blocks. The whole pipeline becomes a closed hydraulic system with **zero new state** — the kernel's pipe semantics were the missing mechanism all along, mispriced at 1MB.

The textbook version: an explicit flow-control protocol, windowing, credit messages. forkrun's version: one `F_SETPIPE_SZ` call, because a bounded blocking channel of coordinates *is* a flow-control protocol.

### 2.3 The Interval Heap

One data structure — a merge-heap of `[start, end)` intervals over the byte plane — serves the orderer (hole-punch behind the emitted prefix), the fallow process (its whole reclamation algorithm), and the resume ledger (the jagged edge). Three subsystems, zero conversions, because the intervals are in the universal currency. The textbook version: three bespoke bookkeeping structures with translation layers.

### 2.4 The Resume Ledger Itself

The deepest demonstration of §0: a checkpoint is *just coordinates* — horizon plus jagged intervals — and every process reconstructs its role from a position on the plane. No object graphs are serialized; no protocol state is saved; resume is re-derivation. This is why exactly-once delivery is even expressible: "was this interval emitted?" is a set-membership question over coordinates, not a distributed-identity question.

---

## §3 — The Derivation Laws

The grammar rules. INVARIANTS.md is the law; this is the worldview that makes the law feel necessary.

1. **One currency.** No subsystem maintains an independent numbering. If a design introduces its own IDs for something the plane already names, it is wrong — or it is about to acquire conversion bugs. (The `-n` bug's multiple clamp variants were exactly this.)
2. **Derive, don't transfer.** State computable from shared coordinates must be computed, never stored and shipped. Transferred state can desync and must be retracted; derived state cannot. (L0/B0 rejected; `cum mod L` adopted.)
3. **Every exit path publishes.** When you own a value waiters consume, enumerate your exit paths and publish on each. Write the enumeration as a truth table at the site. (Shape 6's law, restated as a discipline.)
4. **Never wait on the dead.** Terminal state is globally visible; every wait checks it; every poll is bounded so the check re-runs. (Shape 3's law, restated.)
5. **The wakeup is not the truth.** Indices and flags decide; eventfds only decide when to sleep. (Shape 5's law, restated.)
6. **Progress is irreversible.** No rollback of claims, no un-publication of slots, no decrements of monotonic indices. If a design seems to need "undo," redesign the structure — the undo is where the races live. (PHYSICS.md's arrow of time, stated as an audit rule.)

---

## §4 — Prediction Drills

The frame's test. Answer from §0–§3 alone, then check against the code. Where the frame doesn't determine the answer, that's a hole worth patching — in the doc or in the architecture.

**Drill 1 — Exactly-once resume.** *We need crash-resume with exactly-once delivery. What does the checkpoint contain?*
Frame answer: coordinates only — a horizon (the contiguous completed prefix, in bytes) and a set of intervals (the jagged edge). Everything else re-derives: the scanner skips intervals on the plane, the orderer re-syncs on an offset match, workers re-execute what's left. No protocol state survives the crash because no protocol state *needs* to.
Check: `ring_dump_resume` — horizon, jagged, stdout bytes. 

**Drill 2 — Output backpressure.** *A slow consumer makes memory unbounded. What's the mechanism?*
Frame answer: find the bounded blocking channel already carrying coordinates. The ack pipe qualifies; size it to a page; the kernel does the waiting; backpressure propagates through the existing shield structure because every stage upstream already blocks on bounded coordinates.
Check: H3 fix. Exact match.

**Drill 3 — Exact line batches across NUMA.** *We need `-L N` with NUMA locality preserved. What rides the chain?*
Frame answer: a *global sequence property* (batch boundaries) requires serialization, so the count chain gates scanning. The handoff must be coordinates plus derivables: `actual_end` (start of the open batch) and `cum_lines` (from which the pending carry is derived). Nothing else transfers. Delimiter ownership is exclusive, so each scanner counts only its own chunk and never rescans.
Check: the scanner-handoff chain. Exact match — and the *reason* the first design (L0/B0 transferred state) was wrong is visible in the frame before touching code.

**Drill 4 — Worker starvation on one node.** *`-j 1` on 4 nodes hangs. Where's the bug?*
Frame answer: a per-node ring is a claim structure (Shape 1) whose consumers advance the fallow horizon; zero consumers means the ring fills to the shield and the scanner stalls — and under `-k`, the orderer waits on a (major, minor) that never arrives. The fix is structural: guarantee ≥1 drainer per active ring, at the wrapper, before `ring_init`. Note the diagnosis path the frame gives you: the hang is *downstream* of the empty ring, not in the claim loop.
Check: the `-j 1` saga. Match.

**Drill 5 — A new feature needs per-batch worker identity.** *Users want stable per-batch IDs for output files. What's the ID?*
Frame answer: derive from the lattice — (major, minor) or the byte range — not a new counter. And indeed `{ID}` is `{NODE}.{WORKER}.{BATCH}` with an incarnation suffix for respawn disambiguation.
Check: T11a/T11b. Match — but note the *incarnation* component is a small frame violation (a counter that isn't a coordinate; it exists because a respawned worker re-claims the same slot and must not collide on side effects like output files). `[HOLE? The frame should either admit incarnation counters as a sanctioned exception (identity of *executors*, not of *data*) or the doc has an unprincipled corner.]`

**Drill 6 — EOF while gated.** *A scanner is blocked at the `-L` gate when global EOF arrives and the predecessor exits without publishing. What must be true?*
Frame answer: it can't happen *if* Law 3 held — every exit path publishes. And if a bug means it didn't, Law 4 saves you: the wait has a terminal-state escape, so the blocked scanner observes EOF/cutoff and exits rather than hanging. Defense in depth: the producer-side law makes the consumer-side escape unnecessary; the consumer-side law makes the producer-side bug survivable.
Check: both halves of the hang fix. Match — and the drill demonstrates *why* both halves exist.

**Drill 7 — Sanitizer limitations.** *TSan passes but the ring still races in production. Why isn't that evidence of absence?*
Frame answer: forkrun's coordination is cross-*process* on `MAP_SHARED` — TSan's shadow memory is per-process, so the inter-process acquire/release pairs (Shape 2) are invisible to it. The guarantees are enforced by the invariants and exercised by the stress matrix; sanitizers cover the intra-process fraction.
Check: MAINTAINERS.md §5. Match.

---

## §5 — What This Frame Buys You (and what it doesn't)

**Buys:** a mental model with ~10 elements (one plane, one lattice, six shapes, six laws) that predicts code locations, diagnoses hangs by shape ("this is a Shape-3 violation"), and makes mechanism reuse reviewable ("the truth table says who publishes — check all their exit paths"). It converts forkrun's density from "must memorize subsystems" to "must recognize patterns."

**Doesn't buy:** performance intuition (that's PHYSICS.md + the benchmarks), the security model (that's RESILIENCE_PROTOCOL §6's three layers), or the Bash-side JIT/Partial-Evaluation/cleanroom machinery (which is about *shell* mechanics, not dataflow — arguably a seventh shape, "generate code once, execute many times").

**The honest caveat:** this frame was reverse-engineered from working code by the people who built it. The drills are the only thing keeping it honest — each `[HOLE?]` marker above is a place where the code follows the frame by accident or habit rather than by law, and each is a candidate for either a doc patch or an architecture patch. Expect to find more when you write the next drill.

---

*See also: INVARIANTS.md (the laws, as audit rules) · PHYSICS.md (the metaphor) · EOF_PROTOCOL.md (Shapes 3 & 5 in their purest form) · ARCHITECTURE.md §Core Invariant (§0's short form).*
