---
marp: true
theme: gaia
_class: lead
paginate: true
backgroundColor: #1a1a2e
color: #e2e2e2
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
  }
  h1, h2 {
    color: #60a5fa;
  }
  footer {
    color: #9ca3af;
  }
  code {
    background-color: #161b22;
    color: #34d399;
  }
  table {
    border-collapse: collapse;
    width: 100%;
    margin-top: 15px;
    font-size: 0.75em;
  }
  th, td {
    border: 1px solid #4b5563;
    padding: 8px;
    text-align: left;
  }
  th {
    background-color: #1f2937;
    color: #60a5fa;
  }
  .highlight {
    color: #fca5a5;
    font-weight: bold;
  }
---

# Bypassing the Exascale Bottleneck

### `forkrun`: Contention-Free, Born-Local NUMA Parallelization

**Anthony Barone**

Computational Geophysicist & Systems Researcher

anthonywbarone@gmail.com • (858) 735-2342

---

<style scoped>section{font-size:25px;}</style>

# The Data Locality Problem

Modern HPC nodes are increasingly complex:

- Multiple NUMA domains
- Multiple memory tiers
- Multiple accelerators

Yet many runtime systems still rely on:

- Reactive page migration
- Dynamic profiling
- Manual affinity tuning

### Question

Can we make locality a property of the data itself rather than a property of the scheduler?

---

<style scoped>section{font-size:30px;}</style>

# Born-Local NUMA

### Core Idea

Instead of moving pages after allocation:

- Route data to the correct NUMA node before allocation
- Let Linux first-touch instantiate pages locally
- Align chunk boundaries with record boundaries
- Ensure workers consume data where it was born

### Result

Locality becomes structural rather than reactive.

---

<style scoped>section{font-size:24px;}</style>

# Solving Cold Start: Born-Local NUMA

### Seekable Inputs

- Use `fstat()` forecasting
- Scale chunk size dynamically
- Ensure all NUMA domains receive work immediately

### Streaming Inputs

- Backpressure-aware chunk sizing
- Geometric ramp from 64KB → 1MB
- No manual tuning required

### Goal: Achieve good initial placement before runtime feedback exists.

---

<style scoped>section{font-size:23px;}</style>

# Solving Cold Start: Delimiter Scanner

### Cheap Information Scan

- pre-flight delimiter scan (SIMD Popcount - AVX2/NEON)
- estimate workload density $\rightarrow$ compute initial batch sizing
- scan until Wmax * Lmax lines || EOF || 1st worker spawns

Controller enters steady state drastically faster.

### Ramp Up $\rightarrow$ Steady-State

- Geometric ramp up to Lmax 
- PID-like steady state 
- Early flush on stall + starve

### Goal: Achieve good initial batch size before total line count is known.

---

<style scoped>section{font-size:24px;}</style>

# A Generalizable Pattern

### Common Problem: Dynamic systems begin with little information.

- poor initial placement
- oscillation
- warm-up inefficiency

### Common Solution:

1. Cheap initial scan (when possible) $\rightarrow$ gather information
2. Geometric ramp up $\rightarrow$ compensate for lack of initial information
3. Feedback-driven steady-state $\rightarrow$ stable equilibrium

### Born-Local NUMA Requires (one of):

- Ownership signals that are available before execution
- Ownership that emerges from the placement decision itself

---

## Born-Local vs Conventional Approaches

| Approach | Primary Strength | Primary Limitation |
|-----------|-----------|-----------|
| **Auto-NUMA** | Fully automatic | Migration overhead, slow to adapt |
| **Static Pinning** | Excellent locality | Manual tuning, tail imbalance |
| **Static Round Robin** | Even load distribution | Ignores execution locality, tail imbalance |
| **Traditional Work Stealing** | Dynamic load balancing | Destroys NUMA affinity |
| **SICM (ECP)** | Adaptive, app-guided placement | Requires runtime observation/warm-up |
| **Born-Local** | **Locality by construction** | **Requires pre-execution ownership signals (detected or manufactured)** |

---

<style scoped>section{font-size:23px;}</style>

# Real-World Telemetry

### i9-7940X (booted with `numa=fake=4`)

- Seekable files:
  - **0.0% cross-socket traffic**

- Piped streaming:
  - **<3% cross-socket steals**

- NUMA coordination overhead:
  - **~1.5–2% CPU**

- Core utilization:
  - **90–99% across all cores**

All achieved with ZERO warm-up, profiling, or manual tuning. How? 

Because **resource allocation is the fixed point of a feedback process** — 
which simultaneously **manufactures the ownership it relies on**.

---

<style scoped>section{font-size:25px;}</style>

# Why I Reached Out To CORSys

- **Beyond Streaming:** Streaming is just the domain where we discovered the pattern. The underlying mechanism is broader.

- **The Paradigm: Ownership-Driven Placement + Equilibrium-Driven Ownership**
  1.  A discrete unit of work or data exists.
  2.  We can use feedback processes to identify and/or manufacture ownership *before* execution begins.
  3.  That ownership is highly predictive (perhaps by design) of future access patterns.

- **Generalizing the Principle:**
  - **forkrun:** `chunk` + *queue backpressure* $\rightarrow$ NUMA node
  - **PDE Solvers:** `mesh tile` + *halo-exchange latency* $\rightarrow$ NUMA node
  - **DBMS:** `database shard` + *lock-wait pressure* $\rightarrow$ NUMA node
  - **GPU:** `work queue` + *warp occupancy* $\rightarrow$ Accelerator

---

<style scoped>section{font-size:23px;}</style>

# Potential Collaboration Areas

### Immediate Next Step: Hardware Validation
- **Near-term need:** Validate/benchmark on real multi-socket NUMA hardware (EPYC / dual Xeon) to quantify true interconnect latency avoidance.

### Academic Collaboration
- Ownership-driven placement beyond streaming runtimes
- Transitioning from reactive dynamic migration to proactive bootstrapping

### The Core Research Question
- SICM solves the general placement problem dynamically. But cold starts trigger expensive page-migration storms.

**Can we use proactive, ownership-driven routing + equilibrium-driven ownership to make the initial placement decision at birth, leaving SICM's tiering to handle the dynamic corrections that pre-execution placement can't anticipate?**

---

<style scoped>section{font-size:24px;}</style>

# Long-Term Vision: STTR

### Phase 1

**libforkrun**

- reusable C runtime
- workflow integration
- Python bindings
- AI/ML/HPC data preparation

### Phase 2

**GPU-resident work distribution**: `grun` (GPU-resident forkrun)

- extend claiming architecture to GPU execution
- investigate accelerator-side scheduling
- reduce expertise required for efficient GPU utilization

---

<style scoped>section{font-size:25px;}</style>

# Vision: Democratized Performance

Today: Expert-level performance often requires expert-level tuning.

### Goal: Scientists focus on science.

The runtime handles:

- locality
- scheduling
- work distribution
- data movement

### The Bigger Questions

**How much of performance engineering can be moved into the runtime itself?**
**How much more science can existing infrastructure produce by doing so?**

---

# Thank You

### Questions & Discussion

*Live benchmark running in background.*

*Feel free to ask about any numbers you see.*

---

# APPENDIX

## Supplemental Architecture Details

---

<style scoped>section{font-size:27px;}</style>

## Protecting the Boundary: Contention-Free Coordination

**The Problem:** Mutexes and CAS retry loops bounce cache lines across the 
interconnect — an invalidation storm collapses scaling regardless of placement quality.

**Single-Slot Claiming:**
- One `atomic_fetch_add()` per batch
- No CAS retries, no mutexes, no dispatcher bottleneck on the hot path

**Node-Local Escrow Recovery:**
- Per-node escrow pipes isolate crash recovery to the local socket
- No cross-socket cache thrashing during failure handling
