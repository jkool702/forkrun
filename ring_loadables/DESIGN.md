
# forkrun Ring Architecture – Design Overview

## 1. Purpose

This document explains the internal architecture of **forkrun**’s ring-based execution engine. It focuses on *why* each mechanism exists, the invariants it maintains, and how the pieces interact under load. It is intended for readers who want to understand or extend the system, not merely use it.

The core goals are:

* Extremely high throughput on streaming workloads
* Minimal overhead on the fast path
* Correctness under bursty, skewed, or adversarial input
* Pure Bash compatibility with optional native accelerators

The guiding philosophy is:

> **Fast path is boring. Slow path is where complexity belongs.**

---

## 2. High-Level Model

forkrun consists of three cooperating roles:

1. **Scanner** – Reads input and publishes availability
2. **Workers** – Claim batches and execute user commands
3. **Coordinator State** – A shared-memory ring and counters

All coordination is done through shared memory, atomic operations, and kernel primitives (eventfd + pipes). No locks are taken on the fast path.

---

## 3. The Ring Buffer

### 3.1 What the Ring Represents

The ring does *not* contain data. It contains **offset markers** into an append-only backing file (typically on tmpfs).

Each ring entry represents:

* A boundary where new data becomes visible
* Optionally, a marker that the batch is partial

This allows:

* Zero-copy data sharing
* Arbitrarily large inputs
* Workers to operate independently

### 3.2 Ring Entry Encoding

Each ring slot is a signed 64-bit value:

* **Low 63 bits**: byte offset in the backing file
* **High bit (sign bit)**:

  * 0 → complete batch
  * 1 → partial batch (scanner hit EOF or boundary)

This encoding avoids extra metadata, keeps entries atomic, and supports offsets up to 2⁶³ bytes.

### 3.3 Atomic Invariants

* `write_idx` monotonically increases
* `read_idx` monotonically increases
* Each ring slot is written once, read once
* Readers never observe an uninitialized slot

Memory ordering:

* Scanner publishes ring entries with **release** semantics
* Workers consume them with **acquire** semantics

---

## 4. Claiming Work

### 4.1 Fast Path Claim

The fast path is intentionally simple:

1. Load `write_idx`
2. Atomically increment `read_idx` by batch size
3. Compute offsets from ring
4. Execute batch

No polling, no blocking, no branching beyond bounds checks.

If sufficient data exists, the worker never sleeps.

### 4.2 Waiting (Case 1)

If `read_idx >= write_idx`, the worker:

* Increments a waiter counter
* Polls an eventfd
* Sleeps until the scanner publishes more data

Wakeups are advisory; spurious wakeups are harmless.

---

## 5. Overshoot and Partial Batches

### 5.1 The Overshoot Problem

A worker may claim more data than currently exists, especially when batch sizes are large or input slows abruptly.

Rather than force all workers to stall, forkrun allows:

* Executing the *available* portion immediately
* Deferring the remainder

### 5.2 Escrow Mechanism

To handle deferred remainders, forkrun introduces **escrow**:

* A non-blocking anonymous pipe
* Entries contain:

  * starting offset
  * remaining line count

When a worker overshoots:

1. It executes the partial batch
2. Publishes the remainder to escrow
3. Signals availability via `evfd_data`

### 5.3 Escrow Stealing

Idle workers:

* Check escrow before touching the ring
* If work exists, steal it
* Consume *at most* one batch
* Re-publish any leftover

This ensures:

* Only one owner per remainder
* No duplication
* Bounded contention

If escrow is full, the worker simply completes the batch itself. Correctness always wins over optimization.

---

## 6. Eventfd Usage

Eventfds are used strictly as **wake signals**, never as state.

There are multiple eventfds:

* Data availability
* Worker spawning
* Overshoot notifications

Properties:

* Semaphore mode prevents counter overflow
* Spurious wakeups are allowed
* Missed wakeups are impossible due to monotonic indices

This keeps the design robust and simple.

---

## 7. Scanner Control Logic

### 7.1 Two-Phase Model

The scanner operates in two distinct phases:

#### Phase 1: Geometric Ramp-Up

* Batch size grows exponentially
* Workers spawn aggressively
* Stops automatically on stall

This ensures fast convergence without tuning.

#### Phase 2: Steady-State Control

A PID-inspired controller adjusts:

* Batch size
* Spawn rate

Based on:

* Input rate
* Output rate
* Backlog depth

Shrinking is conservative by design to avoid oscillation.

---

## 8. Memory Reclamation (Fallowing)

The backing file grows monotonically.

A background GC process:

* Observes the minimum active offset
* Punches holes behind it using `fallocate(PUNCH_HOLE)`

This:

* Preserves offsets
* Avoids fragmentation
* Requires no coordination with workers

---

## 9. Failure and Edge Cases

The system is designed so that:

* Every optimization has a safe fallback
* Resource exhaustion degrades performance, not correctness
* All waits are bounded

Examples:

* Escrow pipe full → self-complete batch
* Eventfd saturation → spurious wakeups only
* Slow input → workers sleep without spinning

---

## 10. Design Summary

Key properties of the architecture:

* Lock-free fast path
* Explicit slow paths
* Monotonic indices instead of condition variables
* Advisory wakeups
* Opportunistic load balancing

The result is a system that scales to tens of millions of lines per second while remaining debuggable and deterministic.

---

## 11. Mental Model

Think of forkrun as:

> *A speculative, cooperative work-stealing engine where correctness is enforced by monotonic progress, not locks.*

Once that model clicks, the rest of the design follows naturally.


# MISC UPDATED INFO

## forkrun_ring v6.63 — Design Overview

---

## High-level goals

---

forkrun_ring is designed to efficiently distribute streamed input to a dynamic pool of Bash workers while preserving the following invariants:

Fast path is boring

Claiming available work must be O(1), wait-free, and uncontended.

No polling, no locks, no global coordination on the common path.

Fairness before throughput

Small or slow workloads must not be penalized by batching heuristics.

Every worker should receive work early, even if batching later increases.

Producer/consumer decoupling

Scanner (producer) adapts to both input rate and worker behavior.

Workers never influence scanner correctness, only tuning.

Graceful scaling across extremes

Works equally well for:

Billions of near-zero-cost tasks

Tens of very expensive tasks

No configuration changes required.

Version v6.63 restores and formalizes the ramp-up phase, which is critical to achieving these goals across vastly different workload shapes.

## Architecture summary

---

The system consists of four cooperating components:

Scanner
Reads input, identifies batch boundaries, and publishes work descriptors into a lock-free ring buffer.

Workers
Atomically claim batches from the ring and process the corresponding input.

Ring buffer
Zero-copy structure holding offsets and per-batch metadata.

Coordination primitives

eventfds for wakeups and EOF signaling

An escrow pipe for redistributing overclaimed work

Correctness is entirely derived from monotonic indices (read_idx, write_idx).
All adaptive logic is advisory and never affects correctness.

Batch size control: three-phase model (v6.63)

Batch sizing in v6.63 is governed by a three-phase control loop implemented entirely in the scanner:

Warmup phase

Geometric ramp-up

PID-like steady state

Each phase has a distinct purpose and exit condition.

Phase 0: Warmup (fairness & producer startup)

Behavior

Batch size L = 1

Exactly N batches are emitted, where N ≈ number of workers

Intent

Ensure the producer has time to start delivering data

Ensure every worker receives work early

Prevent large initial batches from being monopolized by the first worker

Why this exists

Without warmup, a fast scanner combined with slow workers could produce large early batches that:

Starve other workers

Increase latency for expensive tasks

Over-optimize for throughput before fairness is established

### Warmup guarantees:

Fair initial work distribution

Predictable latency for small or slow workloads

No assumptions about input speed

This phase is intentionally short and bounded.

Phase 1: Geometric ramp-up (fast discovery of good batch size)

Behavior

Batch size doubles geometrically (L *= 2)

Each size is held for N batches

Ramp halts immediately on input stall

Intent

Quickly discover a reasonable batch size

Avoid linear probing or overfitting

Maintain fairness while increasing throughput

Key properties

O(log L) convergence

No oscillation

No worker coordination required

Scanner-only logic

Early exit on stall

If input stalls during ramp-up, the scanner assumes:

The producer is slow or bursty

Larger batches would increase latency

In that case, ramp-up is aborted and the system transitions directly to steady state.

Phase 2: PID-like steady state (adaptive equilibrium)

Behavior

Scanner periodically measures:

Input publish rate

Consumption rate

Backlog depth

Active worker count

Batch size is adjusted conservatively toward a target

Intent

Maintain equilibrium between producer and consumers

Adapt to dynamic workloads

Avoid oscillation and thrashing

Design principles

Adjustments are slow and conservative

Batch size changes are transactional

Temporary overshoot is allowed and resolved by escrow

Batch size updates are published using:

batch_change_idx as a cutover marker

signed_batch_size as advisory policy

Workers may briefly observe stale batch sizes; this only affects efficiency, never correctness.

Overshoot handling and escrow

Workers are allowed to overclaim batches optimistically.

If a worker claims more work than is currently available:

The available portion is processed immediately

The remainder is published to the escrow pipe

Other idle workers may steal the remainder

If not stolen, the original worker reclaims it later

This mechanism:

Preserves fast-path simplicity

Avoids blocking on partial availability

Prevents latency spikes from large overclaims

Overshoot is expected and explicitly supported.

Why ramp-down is conservative

In steady state, batch size reductions are intentionally slow.

Reasons:

Prevent oscillation under bursty input

Avoid excessive batch fragmentation

Preserve throughput under transient stalls

Any temporary inefficiency is resolved by:

Escrow redistribution

Natural convergence of the PID loop

Correctness is never impacted.

Key invariants (unchanged in v6.63)

write_idx is monotonically increasing

read_idx is monotonically increasing

Ring slots are immutable once published

Workers never block on the fast path

Scanner never depends on worker timing for correctness

All coordination is best-effort and advisory.

## Summary

---

The restored ramp-up phase in v6.63 is not an optimization — it is a correctness-preserving fairness mechanism that enables:

Low latency for small workloads

High throughput for massive workloads

Stable behavior under bursty or slow producers

By cleanly separating:

Fairness (warmup)

Discovery (geometric ramp)

Adaptation (PID steady state)
