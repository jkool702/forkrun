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

## 4. Adaptive Batching = Survey First, Regulate After

The scanner's controller has two primary phases with a graceful fallback -- exactly the kind of measurement hierarchy a geophysicist would design.

**Phase 0: Satellite Surveying (Pre-Flight Popcount)**

Before the water wheels (workers) touch the river, we use a satellite (AVX2/NEON SIMD popcount) to measure the total volume of water already in the channel -- during the dead time when Bash is forking workers. If we count enough water (`Wmax * Lmax` lines or full EOF), we calculate the exact optimal bucket size ($L = \text{total\_lines} / W$) and jump directly to Phase 2 (PID regulation). The wheels arrive at the river with the right-sized buckets already chosen.

**Phase 1: Acoustic Sounding (Geometric Fallback)**

What if the satellite gets blinded by clouds? (A worker spawns before the pre-flight scan finishes.) The system degrades gracefully. The scanner hot-swaps its simulated batch size `sim_L` into the live state and resumes doubling ($L \times 2$) -- acoustic sounding: halving the uncertainty with each ping until the depth is known. O(log L) convergence, no oscillation.

**The Crucial Invariant: The Wheels Never Change**

In older versions of forkrun, the geometric ramp required workers to do speculative multi-batch claiming using CAS retry loops and signed-batch hysteresis -- the wheels had to dynamically resize their own buckets mid-river. That physics has been permanently excised from the worker code.

Today, whether the scanner is in Phase 0, Phase 1, or Phase 2, the worker fast-path is identical: a single `atomic_fetch_add` claiming exactly one slot. The scanner changes the *size of buckets being published*; workers never see the policy, only the bucket. A single-slot claim never crosses a NUMA chunk boundary, so the escrow/overshoot machinery for that case is also eliminated.

**Phase 2: Flow Regulation (PID Steady-State)**

Once optimal $L$ is found -- immediately via satellite, or after a short acoustic ramp -- the scanner enters a PID controller making micro-adjustments based on the `stall_meter` and `starve_meter`. Standard geophysical instrument feedback: calibrate once, regulate continuously.

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

| Code Feature                       | Physical Analogy                          | What Breaks Without It                              |
|------------------------------------|-------------------------------------------|-----------------------------------------------------|
| Monotonic indices                  | Causality / arrow of time                 | Time travel -> data corruption                      |
| Per-node rings + pinning           | Conservation of momentum / locality       | Turbulence -> cache-line storms                     |
| Escrow pipe                        | Inertial correction / diffusion           | Blocking or retries on every claim                  |
| Pre-Flight SIMD Popcount           | Satellite surveying the river basin       | Workers guessing bucket sizes; PID oscillation on startup |
| Single-slot claim (atomic_fetch_add +1) | Inertial bucket with fixed handle    | CAS storms and speculative arithmetic on fast path  |
| Stride Ring Boundary Flag          | Chunk event horizon                       | Workers reading across NUMA fault lines             |
| Fallow punch-hole                  | Second law + event horizon                | Unbounded memory growth                             |

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
