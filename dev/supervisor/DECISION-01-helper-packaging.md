# DECISION-01 — How is the UDF helper shipped?

**Blocks:** P1 (`mode="python"`), and therefore the largest coverage gap.
**Needs:** maintainer + one or more external AI reviewers. Consensus before implementation.
**Status:** open. No code written.

---

## 1. The question

Each cleanroom worker must run a **Python** UDF. Serving that means getting a
CPython interpreter into each worker process. The engine and launcher must
stay Python-free (standing constraint), so the interpreter arrives via a
**helper `.so`** that the launcher `dlopen`s.

**How should that helper be built and shipped?**

This is only a packaging question. The *where the interpreter is
initialised* question (pre-fork in the launcher, or post-fork per worker) is
a **separate** decision — roadmap C0.4 / M2 — and does not change the answer
here. Both variants need a shipped, CPython-linked helper.

---

## 2. Facts already established (measured, not assumed)

### 2.1 The Stable ABI does not contain the configuration API

Building against `-DPy_LIMITED_API=0x030A0000` (the 3.10 floor) and linking
against libpython3.14:

| API | result |
|---|---|
| `PyConfig` (struct) | **unavailable** — `unknown type name 'PyConfig'` |
| `PyConfig_InitPythonConfig` | unavailable (same cause) |
| `Py_InitializeFromConfig` | unavailable (same cause) |
| `PyPreConfig`, `PyPreConfig_InitPythonConfig` | **unavailable** — `unknown type name 'PyPreConfig'` |
| `Py_Initialize` | compiles + links |
| `Py_SetProgramName` | compiles + links — **deprecated 3.11** |
| `PySys_SetArgv` | compiles + links — **deprecated 3.11** |

**The entire PEP 587 configuration family is outside the Stable ABI.** This
retracts the earlier proposal's premise, which rested on `PyConfig` being
available from 3.10.

### 2.2 Why that matters

`Py_Initialize` alone is **not isolated**. It reads `PYTHONPATH`,
`PYTHONHOME`, `PYTHONSTARTUP` and friends from the environment, and adds
paths derived from the program name. An embedded helper that initialises
non-isolated inherits the *caller's* environment — which is the opposite of
what the cleanroom is for.

Isolation is exactly what the PEP 587 API provides, and it is exactly what
the Stable ABI withholds.

### 2.3 The launcher is exec'd, so the environment is the only leak

The launcher is `exec`'d from the Python parent. It therefore starts with a
fresh address space but **inherits the parent's environment**. The risk is
not inherited memory — that is solved — it is inherited `PYTHON*`
configuration reaching the helper's interpreter.

### 2.4 Not established

A runtime probe of the deprecated levers was attempted and **hung** at/after
`Py_Initialize`. **The cause is unknown and nothing should be inferred from
it.** It may be an artefact of the probe (an embedded interpreter with no
valid config, or stdin interaction) rather than evidence about `abi3`. This
is an open loose end, not a finding.

---

## 3. Options

### Option A — Per-minor wheels (minor-specific helper)

Build one helper per supported CPython minor; ship wheels tagged
`cp310`, `cp311`, … `cp315`.

* **For:** full `PyConfig` isolation is available. The wheel tag states the
  constraint exactly. `--caller-minor` matching is meaningful and honest:
  helper minor must equal caller minor.
* **Against:** six minors × supported platforms of wheel builds and CI. The
  roadmap already requires a 3.10–3.15 matrix, so this composes with work
  that has to happen anyway — but it multiplies the *packaging* surface,
  not the test surface.
* The roadmap's existing `FORKRUN_CLEANROOM_TRACE`-style refusal contract
  (caller/helper minor mismatch ⇒ refuse) applies unchanged and correctly.

### Option B — Stable ABI (`abi3`) with environment scrubbing

One helper built `cp310-abi3`, covering 3.10–3.15. Isolation is obtained by
**construction rather than configuration**: before `Py_Initialize`, the helper
unclears `PYTHONPATH` / `PYTHONHOME` / `PYTHONSTARTUP` / `PYTHONUSERBASE`
and controls `argv`, so no caller configuration can reach the interpreter.

* **For:** one wheel; no per-minor matrix; `pip install` with no compiler.
* **Against:** materially **weaker isolation** than `PyConfig`. It is a
  best-effort reconstruction of a guarantee CPython offers properly, and it
  can drift as CPython adds new environment influence.
* **Breaks a roadmap contract:** the caller/helper **exact-minor** refusal
  rule is meaningless for an `abi3` helper that genuinely supports six
  minors. The rule must become "genuine ABI compatibility" instead, which is
  a weaker and less testable statement than "the minors are equal".

### Option C — Source-only build of the helper

Helper source ships in the sdist; built locally as an explicitly optional
capability; **never advertised as present in the generic wheel**.

* **For:** fully honest — no binary ABI claim at all. Isolation can use
  `PyConfig`, because the helper is built against the user's own minor.
* **Against:** the user needs a toolchain and `python3-dev` headers. That is
  a real barrier for a PyPI package whose selling point is that it just
  installs. It also makes "is the UDF acceleration available?" a
  per-machine question, which is hard to document and harder to test.

### Option D — Defer; ship P1 last

Implement none of these yet; land P2/P3/P6 first, which need no helper.

* **For:** unblocks all engine-free coverage immediately.
* **Against:** leaves the **default mode** unserved, which is the largest
  gap by likelihood of being encountered. Deferring the most-used path to
  dodge a packaging question is the wrong trade if the packaging question is
  answerable.

---

## 4. Recommendation

**Option A — per-minor wheels — with Option C as the documented fallback for
platforms not covered by a wheel.**

Reasoning:

1. **Isolation is a correctness property, not a nicety.** The helper runs
   user code in a process forkrun controls. If the interpreter picks up the
   caller's `PYTHONPATH`, the UDF that runs is not the UDF the caller
   wrote. That is silent wrong behaviour — the exact class this project has
   spent CR-FIX1 removing. It is not an acceptable trade for build
   convenience.

2. **Option B buys one wheel by weakening a guarantee we can actually
   state.** The honest summary of `abi3`-plus-scrubbing is "we tried to
   reconstruct isolation and hope we missed nothing". Option A's summary is
   "CPython's own isolation, configured properly". When one option's
   description contains the word *hope*, that is the signal.

3. **The build cost is smaller than it first appears.** The roadmap already
   mandates a 3.10–3.15 test matrix, so those six interpreters must exist in
   CI regardless. Per-minor wheels reuse that matrix; they do not create a
   new one. `tools/build_wheel.sh` already selects newest-first from
   `/opt/python/cp3XX-cp3XX`, so adding `cp315` and looping it is a small
   change.

4. **It preserves the refusal contract the roadmap already specifies**, which
   is a genuinely good safety property: a helper built for 3.11 refuses to
   serve a 3.14 caller instead of misbehaving.

**What would change this recommendation:** if measurement shows the per-minor
wheel matrix is materially more expensive in CI than the test matrix — for
example if it needs a build host per minor rather than reusing one — then
Option B becomes the better trade, *provided* the isolation shortfall is
documented as a known limitation rather than presented as equivalent.

---

## 5. Questions for reviewers

1. Is the isolation argument decisive, or is per-minor wheel cost high enough
   that a documented-weaker `abi3` is the better trade?
2. Is environment scrubbing before `Py_Initialize` genuinely
   insufficient, or is it adequate and simply undocumented in CPython terms?
   I have assumed insufficiency; I have not proven it.
3. Does Option A's "one wheel per minor per platform" interact badly with the
   PEP 600 `manylinux` story already in `setup.py`, or is it routine?
4. Is Option D (defer P1, land the engine-free items first) actually the
   better sequencing? It is the only option that starts no new work, and the
   plan's own priority argument puts P1 first for good reason.
5. The hung runtime probe (§2.4) — is it worth chasing before deciding, or is
   it irrelevant to this choice?
