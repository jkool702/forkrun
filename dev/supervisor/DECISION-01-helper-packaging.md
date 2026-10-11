# DECISION-01 — How is the UDF helper shipped?

**Status: DECIDED — Option A (per-minor wheels), Option C (source-only) as
the documented fallback.**
Blocks P1. Consensus: maintainer + external review round 1.
Implementation carries three binding conditions — see §6.

---

## 0. Resolution of the open loose end (§2.4)

The unexplained stall is **explained, and it was never a hang**.

`PySys_SetArgv(0, NULL)` **segfaults** — CPython dereferences `argv`, and
passing `NULL` with `argc == 0` faults. The original probe died there, before
ever reaching `Py_Initialize`. Nothing about `abi3` was being tested at that
point.

Both real initialisation paths were then run under a **mandatory 20 s
timeout**, staged with `fflush` so the last stage reached is observable:

| path | result |
|---|---|
| plain `Py_Initialize()` | completes, exit 0 |
| `PyConfig_InitIsolatedConfig` + `Py_InitializeFromConfig` | completes, exit 0 |
| `Py_SetProgramName` + `PySys_SetArgv(0, NULL)` | **SIGSEGV** — the original failure |

So §2.4's "cause unknown" is closed: it was a defect in my probe, not a
property of embedded initialisation. **No evidence was ever lost.**

### What isolation actually buys — measured

Same binary, both paths, same interpreter:

| | plain `Py_Initialize` | isolated `PyConfig` |
|---|---|---|
| `sys.path` entries | 8 | **5** |
| `~/.local/lib/python3.14/site-packages` (user site) | **present** | **dropped** |
| `/usr/lib64/python3.14/site-packages` | present | present |
| `/usr/local/lib/python3.14/site-packages` | present | present |

This is precisely the contract a UDF helper needs, and it is **not**
achievable by clearing four environment variables: the user-site directory is
reached through `site` processing, not through `PYTHONPATH`. A user's
installed packages stay importable; environment-influenced paths do not leak
in. That is a concrete vindication of Option A over Option B.

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

---

## 6. Binding implementation conditions (from review round 1)

The decision is Option A. These three conditions attach to it.

### 6.1 Full, deliberate initialisation configuration

`isolated = 1` is **not by itself a complete path contract.** CPython's
isolated configuration still consults configuration files for path settings
left unspecified. The helper must therefore configure, explicitly:

* isolated configuration;
* environment handling;
* **site-import policy** — note `site_import = 0` means third-party paths do
  **not** arrive via ordinary `site` processing, so they must be added
  deliberately;
* runtime `home` / prefix; and
* explicit, **validated** module-search roots — received or derived, never
  inherited as an uncontrolled search path.

Tested against installed packages, not only the standard library.

### 6.2 Honest runtime packaging

Build each helper against its matching CPython minor, then **verify on a clean
installation**:

* inspect `DT_NEEDED` — the helper must request the *intended*
  `libpython3.X`, not the build host's;
* inspect `RPATH`/`RUNPATH` — no accidental dependence on build-machine
  paths;
* inspect `auditwheel` output rather than assuming its verdict.

The current wheel is `manylinux`; whether `libpython3.X` is excluded (system
library) or vendored is a policy question that must be *observed*, not
predicted.

### 6.3 Implementation sequence

Prototype the helper against the **local** interpreter's headers and the full
initialisation API (Option C as a development mechanism), establish the
startup/runtime contract, then complete the six-minor wheel matrix for
release. A toolchain must not become a requirement for users who have a
supported wheel.

---

## 7. Recorded for the future, not decided now

* **The Stable ABI is not inherently unsuitable for embedding.** PEP 384
  explicitly covers applications that embed Python. Option B is rejected
  **as specified**, not in principle. A future design using `Py_BytesMain()`
  with isolated command-line options (`-I -S`) could revisit it — but that
  would be a new design requiring its own isolation and portable-linking
  proof, and it may constrain the pre-fork/post-fork choice, so it is not
  assumed equivalent to Option A.
* **Portable linking is a real abi3 obstacle**: the Stable-ABI shared library
  is not present in every Python distribution, and Debian has documented
  missing `libpython3.so` packages. A `cp310-abi3` tag alone does not
  guarantee the launcher can load the interpreter library on the target.

---

## 8. Phase-1 prototype results (condition 6.1 evidence)

`python/forkrun/fr_udf_helper.c` — a standalone probe, deliberately not yet
wired into the launcher. Built against local headers, full API (Option C as
the development mechanism). Its only job was to answer §6.1 with evidence.

**All four contract points demonstrated on CPython 3.14.7:**

| | result |
|---|---|
| (a) isolation holds | `isolated=1`, `safe_path=1`, `no_site=1`; `pytest` unreachable without an explicit root |
| (b) installed packages importable | with all five site roots: `numpy` OK, `adjustText` OK |
| (c) explicit validated roots | roots appear on `sys.path` in caller order, each `R_OK`-validated before the interpreter sees it |
| (d) UDF resolve + invoke + convert | `udfmod:up` → `LINE000042` |
| shutdown | `Py_FinalizeEx()` clean |

### Five things reading the API would not have told me

1. **`site_import = 0` drops *every* site-packages root, not just user site.**
   The obvious reading is "it turns off user-site". In fact it turns off the
   mechanism that adds `/usr/lib64/…/site-packages` too. The consequence is
   concrete: a UDF's dependency chain routinely spans roots —
   `adjustText` → `numpy` (system root) → `pyparsing` (a third root) — and
   each must be added explicitly. **The root set must be derived from the
   interpreter's own `site.getsitepackages()` + `site.getusersitepackages()`,
   never hardcoded or guessed.** Review condition 6.1 called this; this is
   what it looks like.

2. **`PyConfig.module_search_paths` is a dead end.** Two distinct failures:
   * appending and leaving `module_search_paths_set == 0` → initialisation
     **recomputes and silently discards** the append. `sys.path` came back
     with the root gone and no error. A quiet failure, which is the worst
     kind.
   * setting `module_search_paths_set = 1` → the flag means "this is the
     *complete* path", so the stdlib disappears and
     `Py_InitializeFromConfig` fails with `No module named 'encodings'`.

   Roots are therefore installed by inserting into `sys.path` **after**
   initialisation, before any user code has run.

3. **String config fields must go through `PyConfig_SetString`.** Assigning a
   literal (`cfg->program_name = L"forkrun-udf"`) compiles, initialises
   correctly, then dies in `PyConfig_Clear()` with `free(): invalid size`,
   because `Clear` frees a string literal.

4. **`sys.flags` attribute names are not stable across minors.** On 3.14,
   `site_import` and `user_site` are **absent**; `no_site` and `safe_path`
   exist. Any test asserting isolation flags across the 3.10–3.15 matrix must
   handle absence, and the names to assert differ per minor.

5. **A bare "NOT importable" probe is close to useless.** It cost about an
   hour: the root was correct, the module was present, and the real cause was
   a transitive dependency in a different root. The probe now prints the
   exception, which is what made finding (1) obvious.

### What this does not yet establish

No launcher integration, no `fork()`/`exec()`, no engine interaction, no
worker lifecycle, no shutdown-under-signal behaviour, and no packaging
(`DT_NEEDED`/RPATH/`auditwheel`) — condition 6.2 remains entirely open. The
pre-fork vs post-fork question (C0.4) is untouched: this probe initialises in
a single process, which corresponds to neither.

---

## 9. Phase-2 results — the shipped-shape artifact, and C0.4 answered

`python/forkrun/fr_udf.c` + `fr_udf.h` — the per-minor helper as a
**dlopen-able shared object**, built by `make -f Makefile.substrate udf`.
`fr_udf_helper.c` survives as the Phase-1 probe but now *drives the library*
rather than reimplementing it, so the diagnostic and the shipped path
cannot drift apart.

### 9.1 Why a `.so` and not part of the substrate

The helper is the only artifact here that **links libpython**. Every other
target is built so that it does not (`release_check`'s canary asserts the
substrate has no bash linkage; the same reasoning applies to libpython).
Keeping the interpreter behind a separate `dlopen`-able object means a
non-UDF run never maps libpython at all and its `DT_NEEDED` set is
unchanged — the blast radius of adding Python support is one `dlopen` in
one mode, not a new dependency for every user.

### 9.2 The constraint that dictated the test strategy

The helper initialises the interpreter, so it **cannot be loaded into a
process that already has one**. A test runner is itself a running Python;
`dlopen`ing the helper there and calling `fr_udf_init` means calling
`Py_InitializeFromConfig` on a live interpreter. That is undefined and in
practice core-dumps.

This is not a testing inconvenience — it is the helper's actual contract,
and it independently justifies the whole architecture: the interpreter
lives in a process the launcher `exec`s, never in the Python parent. The
tests therefore drive the binaries as subprocesses, which is also what
ships.

### 9.3 C0.4 (pre-fork vs post-fork) — measured, not assumed

`fr_udf_fork.c` runs both candidates and **checks every child's outcome
before reporting a timing**. That check earned its place immediately: the
first run reported a 25× speedup for pre-fork against a post-fork
baseline of 4/4 *failures*, because the post-fork children were
initialised with no import roots and so could not import the UDF at all.
A harness that printed only timings would have recorded that as a result.

Correctness first, then speed:

* **Pre-fork works.** A forked child inherits the initialised interpreter
  and runs the UDF correctly. This was the open risk: CPython's runtime
  is not fork-safe in general, and it would have made post-fork the only
  option by default. It is safe here because the launcher is
  single-threaded at the moment it forks — a precondition, now stated in
  `fr_udf.h` rather than left implicit.
* **Pre-fork is 4–8× faster**, consistently, across 1/2/4/8 children
  (post-fork pays a full interpreter start per worker; pre-fork pays one).

Neither candidate is wired into the launcher yet. This settles *which*
to build; it does not claim the integration is done.

### 9.4 Two more things running them produced

6. **A flag that does not exist is not a violated flag.** The probe
   computed `sys.flags.use_environment` and, on 3.14, found it **absent**,
   while the flags table printed it as `= 0` — because the helper returned
   0 for "absent" and the report printed the substituted value instead of
   the absence. The same run then printed the property as *both* `0` and
   `VIOLATED`. Finding 4 of section 8 said the names differ per minor; the
   report now distinguishes ABSENT from a value, and an uncheckable
   property is reported as uncheckable rather than as a breach.

7. **`None` survives to the UDF boundary as its own outcome.**
   `fr_udf_call` returns `FR_UDF_NO_RESULT` for `None` and `FR_UDF_OK`
   with a non-NULL zero-length buffer for `b""`. The caller never has to
   infer which it got from a buffer length — which is the same invariant
   DECISION-02 established for the record channel, now held at the point
   where a Python callable's return value becomes a frame.

### 9.5 Still open

* Launcher integration (the `dlopen` in UDF mode, and the per-batch call
  site) — not started.
* Packaging proof under condition 6.2: `DT_NEEDED`/RPATH/`auditwheel` for
  the helper, and a clean-install run on all six minors. `fr_udf.c` and
  `fr_udf.h` are in `MANIFEST.in` and asserted by `release_check`, but
  the wheel matrix does not yet build the helper.
* Per-minor verification: measured here on **3.14.7 only** (this machine
  has no `/opt/python/cp3xx` interpreters). Findings 4 and 6 above are
  exactly the kind of thing that differs per minor, so the other five
  minors are unverified.
