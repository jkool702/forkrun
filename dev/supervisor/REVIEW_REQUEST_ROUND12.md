# Round 12 (R1) — revised proposal: the W-EXP-1 minor-mismatch refusal

Branch `NEW/REFACTOR4.2`. Review the **branch head**; `2a5f4068` is the
last commit this pins. Frozen ring untouched.

**1038 tests, 0 unexpected failures, 2 skipped.** Release gate green.

**Status: REVISED. Still not implemented.** Round 12's original §3 was
wrong on its load-bearing claim and §4 proposed a mechanism that violates
the helper's isolation model. Both corrections are below, with the
evidence that produced them. Nothing in this proposal exists in code.

---

## 1. Corrections — accepted, with evidence

### 1.1 The ordering diagnosis was wrong. The reviewer is right.

I claimed input is materialised before the launcher starts, making the
preflight requirement load-bearing. I re-checked both halves:

* `_cleanroom_source_fd()` (`run.py:1659-1698`) only calls `os.dup()` or
  `os.open(O_RDONLY)`. **No `read()`, no `mmap`.** It yields a descriptor,
  not bytes.
* In `forkrun_cleanroom.c`, `setup_udf_helper()` runs at **line 1369**;
  the spill child is forked at **line 1461**. The spill child is what
  reads the caller's source.

So a helper load failure **already happens before any source byte is
consumed**. The "before input consumption" clause is *already satisfied*,
for a reason I had not looked for. My §3 described opening a descriptor as
if it were reading data.

**Consequence:** the justification for a preflight changes. It is no
longer "we must get in before input". It is that **a successful `dlopen`
does not establish the helper matches the caller** — see §2.

### 1.2 `ctypes` was the wrong mechanism. Fully conceded.

`_udf.py:1-20` states the helper **must not** be loaded into a process
that already runs Python; it calls `Py_InitializeFromConfig`. My proposal
would have done `ctypes.CDLL(helper_path)` to read a symbol — loading the
`.so` into the caller, running its ELF constructors and pulling its
`libpython` into the process the design exists to keep free of it. A
`try/except` around `CDLL` does not undo those side effects.

I had read that paragraph and proposed against it. The reviewer's
correction stands.

### 1.3 `PY_MINOR_HEX` does not exist. Conceded.

The macros are `PY_MAJOR_VERSION`, `PY_MINOR_VERSION`, `PY_MICRO_VERSION`
and `PY_VERSION_HEX`. I would have written a compile error. Comparing
**major and minor** rather than minor alone is also the right call, and is
adopted.

### 1.4 The exit code. Question 1 answered; I adopt the answer.

I could not resolve what 78 means and did not want to guess. The table in
`run.py:897-925` is unambiguous:

| code | meaning | fallback |
|---|---|---|
| 71 | `fr_py_init` failed | permitted (`_CR_EXIT_PRE_INGEST`) |
| 78 | plugin lacks `forkrun_use_ctx` v1/v2 | permitted (`_CR_EXIT_PRE_INGEST`) |
| 79 | plugin capability probe did not complete | **forbidden** (`_CR_EXIT_NO_FALLBACK`) |

So 78 means "unsupported plugin dialect", not "probe failed". The
roadmap's "mirroring the exit-78 refusal precedent" means matching its
*behaviour*, not its number. **Adopted: a new code (80), added to
`_CR_EXIT_PRE_INGEST`, given an accurate `_CR_EXIT_LABELS` entry, and
deliberately NOT added to `_CR_EXIT_NO_FALLBACK`** — because we *can*
establish that the mismatch is safe to decline.

### 1.5 The plain `.so` fallback is a hole in my "common case" claim. Conceded.

`_udf.py` falls back to a bare `_fr_udf.so` when the `EXT_SUFFIX` candidate
is absent ("so a build that used a different suffix still works"). So a
3.12 helper named `_fr_udf.so` **is** picked up by a 3.14 caller. My
statement that "discovery-by-filename catches the common case" was too
generous: the fallback exists precisely to bypass that identification.

### 1.6 The in-process fall-through trap. Accepted; it invalidates part of my §4.

My proposal had the launcher refuse and "treat it like an absent helper",
i.e. return `None`. That is insufficient. Verified: after a `None` from
`_execute_cleanroom`, dispatch reaches `_coerce_payload()` (`run.py:3552`),
which consults `_udf_helper_path()` again — and if the file is still there,
returns `_make_udf_payload(...)` / mode `"udf"`. The ordinary Python worker
cannot execute that wrapper as a plain callable. See §3.2.

## 2. What the defect actually is, stated precisely

Since §1.1 removed the ordering justification, the reason to do this is
narrower, and I want it stated accurately rather than inflated:

**A successful `dlopen` does not prove the helper matches the caller.**

The launcher is a fresh process with no interpreter of its own. A helper
built for 3.12 requests `libpython3.12.so.1.0` via `DT_NEEDED`, and §6.2.1
established the artifact carries **no `RPATH`/`RUNPATH`** — so if
`libpython3.12` is installed, the loader satisfies it and the helper
loads cleanly, in a launcher that was launched by a 3.14 caller.

**The harm is a correctness barrier, not memory safety.** Nothing here
corrupts memory: the launcher has no interpreter, so a 3.12 helper plus
`libpython3.12` is internally self-consistent. What breaks is the user's
expectation — a UDF written against 3.14 semantics executing under 3.12,
failing confusingly or behaving differently. §5.5 asks for a barrier; this
is what the barrier is worth. I would rather say that plainly than let
"version mismatch" imply a vulnerability it is not.

## 3. Revised design

### 3.1 Authoritative check stays in the launcher

1. Helper exports `fr_udf_built_version()` → `PY_VERSION_HEX` at compile
   time (major + minor together).
2. **The caller passes its own minor explicitly on the command line**, as
   roadmap §5.3 already requires. The launcher must not guess.
3. The launcher compares **inside the existing disposable probe
   subprocess**, before interpreter initialisation and before the spill
   fork (line 1461) — so the decision precedes any source consumption.
4. Mismatch → specific message, **exit 80**.
5. Re-verify against the handle actually loaded for execution, after
   `dlopen`, not only on the probe handle.

Direct `launcher --udf-helper ...` invocations are covered by this, since
the check does not depend on the Python side.

### 3.2 The in-process degradation must be explicit, not incidental

Per §1.6, a bare "return `None`" is not enough. Adopted: **the Python-side
availability decision identifies the refusal and the call is routed
explicitly to the in-process UDF path**, bypassing the helper-present
branch in `_coerce_payload()`.

This is why `helper_path()` alone is insufficient: it reflects *file
presence*, and after a mismatch the file is still present. Any design here
must close that desync explicitly rather than hope the two agree.

### 3.3 On the sidecar — accepted with a sharpened failure mode

I agree the launcher check is authoritative and the Python side needs a
**non-loading** hint. A build-generated metadata sidecar is reasonable,
with one requirement the review did not spell out:

**The sidecar must never be the thing that *refuses*.** If it is missing
or stale, `helper_path()` should stay permissive and let the launcher
decide. Rationale: a sidecar and its `.so` can legitimately desynchronise
— copying the `.so` without the sidecar, or rebuilding one without the
other — and a routing *hint* failing open is benign while failing closed
silently disables UDF mode. The sidecar's only safe use is to avoid a
pointless `exec`+`dlopen`, never to substitute for the guard.

### 3.4 Scope

UDF-helper routes only, per the reviewer's Q4. **Agreed** — the C plugin
is a different artifact with a different ABI contract (`forkrun_use_ctx`
v1/v2), and giving it a CPython-minor check would be meaningless. A C
plugin that independently links CPython is a separate concern, not
something this criterion governs.

## 4. Revised test plan

Adopting the reviewer's sharpening, plus one requirement the sharpened
plan implies:

1. **Positive control** — a matching helper must demonstrably serve the
   request *through the cleanroom UDF route*, not merely produce identical
   bytes. Assert the route was served and the capability reported.
2. **Non-consumption, route level** — supply the source as an **already-open
   descriptor**, not an unconnected FIFO path (opening a FIFO blocks, which
   would hang *before* the preflight and prove nothing). Assert all three:
   mismatch code and message observed; no UDF init or worker execution; and
   **the descriptor's offset is unchanged when the cleanroom attempt
   returns**.
3. **Degradation, public API** — separately, the full public call must fall
   back in-process and return **every** result. The reviewer's point is
   decisive here: this test must prove the *fallback route actually ran*,
   not merely that output appeared. Given §1.6 that is exactly the trap.
4. **Negative control that cannot false-pass** — if the mismatched helper
   fails to *load* (missing `libpython`), removing the comparison would
   still refuse before consumption, and the test would "pass" for the wrong
   reason. The helper must be built against the **same runtime as the
   caller** while **advertising a different version**.
   *This requires a build-time override for the reported version
   (e.g. `-DFR_UDF_REPORT_VERSION_OVERRIDE=0x030C0000`) used solely by
   tests — otherwise the branch cannot be exercised as described.*
5. **Kill-switch interaction** — with `FORKRUN_NO_UDF=1` the helper must not
   be probed or loaded at all. Per the reviewer I will **not** assert "one
   warning": the ordinary missing-helper path can fall through quietly, so
   warning policy is a separate contract decision (see §5).
6. **Matrix case** — the real 3.12-helper-vs-3.14-caller case where the
   matrix can build both.

## 5. New finding, elevated by this work

The reviewer noted it; I verified it and think it must be raised in
priority because §3.1 places the version check **inside** that probe.

`setup_udf_helper()`'s probe uses a **blocking `read()` and an untimed
`waitpid()`** (`forkrun_cleanroom.c:638-655`), whereas the plugin probe
around `:1225` is bounded. A constructor that hangs therefore hangs the UDF
probe indefinitely.

That is pre-existing. But once the version check relies on that probe, it
stops being a robustness gap and becomes part of a **security-relevant
boundary** — and we must not describe constructor hangs as safely bounded
until it is fixed. Either bound the probe in this change, or state
explicitly that the version check does not depend on probe completion.
I would rather bound it than caveat it.

## 6. Questions still open

1. **Warning policy.** The reviewer's point stands: the ordinary
   missing-helper path can fall through quietly, so §5.5's "the decline is
   observable" may not hold for a *refusal* today. Is a refusal required
   to warn even when the cleanroom was not explicitly requested?
2. **Mislabel, separable.** `setup_udf_helper()` failure returns **71**,
   labelled "engine initialization failed (fr_py_init)". That is actively
   misleading in triage — a helper load failure is not an engine init
   failure. I would give it its own code, but that changes a shipping
   path's observable exit status, so I am **flagging rather than bundling**.
3. **Scope of "observable".** Should `v1_available()["udf"]` become
   `False` for the rest of the process once a mismatch is seen, or stay
   `True` (file present) with the route re-routing instead? The first is a
   capability lie after a transient condition; the second is a desync the
   route must own. I lean to the second plus an explicit refusal record,
   but this is a design choice worth a second opinion.

## 7. Status vocabulary

- TD-10 (class payloads), TD-11 (kill switch), the unbounded-retry warning
  — **implemented and tested**.
- This proposal — **not implemented**. Nothing here exists in code.
- `fork_workers` / `report_poison` consolidation — **mapped only**.
- Packaging under `auditwheel` — **unverified**, not passing.
- The UDF probe's missing timeout — **open**, newly elevated by §5.