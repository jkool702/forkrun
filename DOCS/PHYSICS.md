# PHYSICS.md – Thinking About forkrun Like a Physical System

**“I didn’t write a parallelizer. I built a pipeline that obeys conservation laws.”**

— the forkrun author (computational geophysicist)

Most CS people look at forkrun and think:

> “Why is this so complicated? Just use a lock-free queue and a thread pool!”

They are asking the wrong question.

The right question is the one a physicist would ask:

> **“How do I design a system whose *natural behavior* is the desired behavior — so I never have to fight it?”**

forkrun was designed the way we design seismic acquisition arrays, inverse-modeling solvers, or fluid-flow simulators: by writing down the invariants first (conservation of mass, causality, locality, monotonic time) and then letting the implementation *emerge* from those laws. The complexity you see is not accidental — it is the minimal set of boundary conditions needed to make the system obey its own physics.

This document translates the code into that physical language so CS readers can stop fighting the design and start *feeling* why it has to be this way.

---

## 1. The Fundamental Analogy: A One-Way River of Data

Think of the input stream as **water flowing down a river**.

- The scanner is the **source** (headwaters).
- The ring is the **riverbed** — a long, straight channel with fixed markers (offsets) every few meters.
- Workers are **water wheels** placed along the banks. They can only take water that has already reached their station.
- Once water passes a marker, it can never go back upstream. (Monotonic `write_idx` / `read_idx` = arrow of time.)

In classical software we would put locks at every wheel so they don’t fight over the same bucket.  
In physics we just make the river wide enough and the wheels spaced correctly. No locks needed — the geometry enforces the rule.

---

## 2. Born-Local Data = Conservation of Momentum

NUMA is not a performance tweak. It is **conservation of locality**.

When data arrives from stdin it has “momentum” — it was born on a particular CPU socket. If we let it diffuse randomly across sockets we create cross-socket traffic (heat, latency, cache-line ping-pong) exactly like turbulence in a fluid.

forkrun’s `ring_numa_ingest` + `set_mempolicy(MPOL_BIND)` is the physical equivalent of:

- Injecting dye into a specific layer of a stratified flow.
- Pinning the scanner and its ring to that same layer.

The data never has to cross a socket boundary unless a worker explicitly steals work — and even then the escrow pipe acts as a low-friction diffusion channel. The system conserves locality the same way a glacier conserves its layered ice.

---

## 3. Speculative Claiming + Escrow = Inertial Particles with Corrections

Workers are not polite queue consumers. They are **inertial particles** moving at high speed along the river.

An inertial particle cannot stop instantly. When it sees “enough water ahead,” it claims a big chunk (large batch) — even if some of that water hasn’t arrived yet.

In software this is called “overshoot.”  
In physics it is called **inertia**.

When the particle discovers it over-claimed, it doesn’t reverse (no rollback). It simply:

1. Processes what actually arrived (partial batch).
2. Drops the remainder into a side-channel (escrow pipe) — like shedding mass or emitting a correction signal.

Other idle particles can pick up those corrections. If none do, the original particle will eventually come back for them.  
Forward progress is never blocked. The river keeps flowing.

This is why there are no CAS retry loops on the fast path: in physics you never need retries if your particles obey Newton’s laws and the channel is one-way.

---

## 4. Adaptive Batching = PID Control with Physical Limits

The scanner’s three-phase controller (warmup → geometric ramp → PID steady-state) is literally a control system you would find in any geophysical instrument:

- **Phase 0 (warmup)**: “Make sure every sensor sees at least one event before we start averaging.” (Fairness before optimization — exactly like calibrating a seismometer array.)
- **Phase 1 (geometric ramp)**: “Double the sampling window until the signal-to-noise ratio stops improving.” (Classic geophysical line search.)
- **Phase 2 (PID)**: “Adjust gain based on observed flow rate, backlog pressure, and starvation.” (Standard feedback loop with anti-windup via damping constants.)

The `signed_batch_size` trick (negative = advisory, positive = finalized by worker via CAS) is the control theorist’s way of saying:

> “The controller may change its mind at any time. Only the sensor that actually measures the river can declare the measurement final.”

---

## 5. Fallow (Punch-Hole Reclamation) = Entropy and the Second Law

The backing memfd grows forever in one direction. We cannot shrink it without breaking offsets (causality).

Instead we do exactly what physicists do with black-hole event horizons or expanding universes:

- We leave the old coordinates intact.
- We **punch holes** behind the minimum active offset (`fallocate(FALLOC_FL_PUNCH_HOLE)`).
- The file size stays large, but the *physical* memory footprint collapses.

This is the thermodynamic arrow of time made explicit. The fallow thread is the system’s entropy exporter.

---

## 6. Ordering Modes as Different Observers

- `--realtime`: “I only care about what arrives first at the detector.” (Relativistic observer — order of arrival.)
- `--ordered`: “I need to reconstruct the original sequence as if measured by a stationary lab frame.” (The `ring_order` thread is the Lorentz transformation that re-synchronizes the major/minor indices.)

The NUMA-aware reorder path is just special relativity for data streams.

---

## 7. Why the Complexity Is Minimal, Not Maximal

Every “weird” feature has a direct physical justification:

| Code Feature                  | Physical Analogy                          | What Breaks Without It                     |
|-------------------------------|-------------------------------------------|--------------------------------------------|
| Monotonic indices             | Causality / arrow of time                 | Time travel → data corruption              |
| Per-node rings + pinning      | Conservation of momentum / locality       | Turbulence → cache-line storms             |
| Escrow pipe                   | Inertial correction / diffusion           | Blocking or retries on every claim         |
| Signed batch size + CAS       | Control system with sensor finalization   | Races: two workers act on same advisory size        |
| Sign bit on offset            | Phase boundary (pre-tail vs tail)         | Partial-line leaks at EOF                  |
| Fallow punch-hole             | Second law + event horizon                | Unbounded memory growth                    |

Remove any of these and the system either violates a conservation law or requires locks/polling to compensate — exactly like adding friction to a frictionless model.

---

## 8. How to Think Like a Geophysicist When Hacking forkrun

1. **Start with invariants, not features.** Write the conservation laws first (see INVARIANTS.md).
2. **Ask “what would break if this were a real river?”** If the answer is “turbulence” or “backflow,” you probably need a new physical mechanism, not a new lock.
3. **Make the fast path boring.** In physics the interesting stuff happens at boundaries (shocks, phase transitions). In forkrun the interesting code is in ingest, tail handling, and fallow — not the claim loop.
4. **Locality is sacred.** Cross-socket traffic is like seismic waves crossing a fault — it distorts everything downstream.
5. **Progress is irreversible.** Never design anything that requires “undo.” The river only flows one way.

---

## Final Mental Model (one sentence)

**forkrun is a frictionless, one-way, born-local river of data with inertial water wheels, a PID-controlled source, and an entropy-exporting black hole at the tail.**

Once you see it that way, the code stops looking over-engineered and starts looking inevitable.

Welcome to the physics department. The CS department is across the hall — they have locks.

---

**See also**  
- [DESIGN.md](DESIGN.md) – the engineering blueprint  
- [INVARIANTS.md](INVARIANTS.md) – the conservation laws written in code  

- The C source – the actual riverbed geometry
