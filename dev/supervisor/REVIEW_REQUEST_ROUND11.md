# Round 11 — focused review: the C0.5 security surface

Branch `NEW/REFACTOR4.2`. Review the **branch head**; `2a3dfb45` is the
last commit the round-10 request pinned. Frozen ring files
(`forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c`) untouched
across `c72d27c6..HEAD`.

**1002 tests, 0 unexpected failures, 2 skipped.** Release gate green.
`UNIT_TESTS/test_frun.sh` 96/96.

This is a **narrow** request. Rounds 6–10 have been broad; this one is
about specific new code that has never been reviewed and has no tests.

---

## 1. Why this is narrow and urgent

Two changes to **product** code (`python/forkrun/fr_udf.c`) came out of
the C0.5 interpreter matrix:

* `scrub_inherited_path()` — new, **security-relevant**, **zero tests**.
* `FR_UDF_HOME` — a new environment variable that changes interpreter
  initialisation.

Both matter more than their size suggests. `scrub_inherited_path()`
exists because `PyConfig.safe_path` does not exist on 3.10, and that
field is what keeps a caller-influenced directory off `sys.path`. The
function is the 3.10 substitute for a security control, and I wrote it
without a single test.

The rest of the round (matrix results, measurement instrumentation) is
summarised at the end and needs much less attention.

## 2. What I want challenged

### 2a. `scrub_inherited_path()` — the important one

```c
#if PY_VERSION_HEX >= 0x030B0000
    return 0;                    /* safe_path was set in configure() */
#else
    ... remove '' and any entry equal to getcwd() ...
    PyList_SetSlice(path, i, i + 1, NULL)
#endif
```

Questions, in the order I care about:

1. **Is the removal set right?** It drops `''` and a literal cwd entry,
   and leaves stdlib, `lib-dynload` and site directories alone. Is there
   a caller-influenced entry on 3.10 that this misses — a `PYTHONPATH`
   entry, a script directory, a zip on `sys.path`?
2. **Is it positioned correctly?** It runs after `Py_InitializeFromConfig`
   and before `install_roots()` and any user payload. Is there a window
   in which an inherited entry is reachable?
3. **Does it fail safe?** If `PySys_GetObject("path")` is not a list it
   returns `-1` and `fr_udf_init` fails. Is failing the init the right
   response, or should it proceed with the inherited path intact?
4. **`PyList_SetSlice(path, i, i + 1, NULL)`** deletes. Is that the
   correct idiom, and does it handle the borrowed reference correctly?
   (I used it because `PyList_DelSlice` does not exist on 3.10.)
5. Does the `#if >= 0x030B0000` early-return leave any 3.11+ path
   uncovered that a belt-and-braces scrub would catch?

**There are no tests for any of this.** That is the main thing I'd like
fixed, and I'd rather have tests written against your critique than mine.

### 2b. `FR_UDF_HOME`

```c
const char *want_home = getenv("FR_UDF_HOME");
if (want_home && *want_home) { PyConfig_SetString(cfg, &cfg->home, w_home); }
```

1. It is opt-in and unset in production, so the normal path is unchanged.
   Is that acceptable, or does an env var that redirects interpreter
   initialisation need tighter gating — an allowlist, a build flag, a
   check that the path is not caller-controlled?
2. `Py_DecodeLocale` failure path — correct, or does it need to
   distinguish "not decodable" from "rejected"?
3. Should this exist at all? The finding was that the helper cannot use a
   relocated interpreter. I called `FR_UDF_HOME` a *measurement enabler,
   not a fix*, and recorded the underlying deployment question as open.
   I would rather that question be answered than have the flag stand
   unexamined.

### 2c. The two API choices forced by 3.10

* `PyUnicode_AsUTF8String` over `PyUnicode_FSConverter` (whose signature
  changed in 3.11 — it took a `char**` out-param before).
* `PyList_SetSlice(..., NULL)` over `PyList_DelSlice` (absent in 3.10).

Are these right, and is there anything 3.15 changes that I have not
accounted for?

## 2d. `scrub_inherited_path()` may not be load-bearing — and I cannot show it is

I added tests for the scrub (below) and then mutation-checked them, and
the result is negative, so it belongs here rather than buried.

**Disabling the scrub entirely changed nothing.** Tested on 3.14 (where
the function is `#else`'d out and `cfg->safe_path` does the work) and on
a 3.10 build (where the scrub is the live code path). Both report
`caller-influenced entries on sys.path: 0` with and without it.

`PyConfig_InitIsolatedConfig` appears to prevent the cwd prepend on 3.10
by itself, so in these configurations **there is no inherited entry for
the scrub to remove**.

So the honest position: the scrub is defence-in-depth whose necessity I
have not demonstrated. It may still be right — a future argv-processing
path, or a different init sequence, could reintroduce the prepend — but
right now I am shipping security-relevant code with no configuration in
which it demonstrably does anything.

Two things I would like you to weigh in on:

1. **Keep or remove?** If there is a reachable configuration where
   `sys.path[0]` becomes `''` on 3.10, the scrub is justified and I
   should add a test that constructs it. If not, it is unjustified
   complexity in a security control, which is its own kind of problem —
   a reviewer cannot reason about a scrub with no reachable purpose.

2. My tests assert the **observable property** (zero inherited entries,
   stdlib and lib-dynload survive, caller's root first) rather than the
   scrub's invocation. That is deliberate: on a 3.14 host the 3.10 code
   does not exist, so a test of the scrub directly is **structural
   vacuity** — it passes without ever entering the code under review.
   The same mutation-miss happened in reverse twice this session, so I
   am flagging it rather than claiming the coverage.

## 3. Measurement code — brief, but two bugs are worth your eye

`fr_udf_fork.c` now has children self-report memory through a barrier.
Two protocol bugs, both producing *impossible* numbers rather than
errors:

1. **Pipe desync** — the ack byte and the report shared one pipe and the
   parent released before draining, shifting every field by one byte. A
   271 MB child reported `rss=68794368 kB` (68 GB); the run claimed
   98 GB of fleet PSS.
2. **Staggered sampling** — children sampling at exit meant the PSS
   divisor shrank as they left, so the last to sample reported nearly
   the whole parent as private.

Both are fixed. The block is labelled **EXPERIMENTAL** and **no
fleet-memory conclusion is drawn**: the direction matches COW theory but
the magnitude is not trustworthy — with the barrier held, children that
should report near-identical PSS for the shared mapping vary ~2.4x, and
the cause is **not established**.

I am asking you specifically: is there a *third* protocol bug here, and
what would explain the variance?

## 4. The C0.5 result

Pre-fork works on **all six minors** 3.10.22, 3.11.17, 3.12.15,
3.13.16, 3.14.7, 3.15.0rc2. Control probe non-vacuous on every one;
respawn inherits no interpreter state on every one. Medians 3.6x–4.7x
with no trend across versions.

Full detail: `dev/supervisor/C0.5_INTERPRETER_MATRIX.md`.

## 5. Still open

| # | item | status |
|---|---|---|
| 1 | **Fleet memory (children's PSS/USS)** | instrumented; variance unexplained; no conclusion |
| 2 | Physical NUMA (locality, cross-socket, bandwidth) | needs real hardware or `numa=fake=N` boot |
| 3 | Two orderers (splice uses Python `ReassemblyBuffer`) | ~0 measured cost; still the largest parity deviation |
| 4 | Ordered streaming | declined; bounded-memory/liveness design absent |
| 5 | `Auto` / `mode="python"` parity (W-EXP-1) | now unblocked by C0.5 |
| 6 | Sanitizer matrix (ASan/TSan/UBSan) | not run for this work; `MAINTAINERS.md` §5 requires it |
| 7 | `FR_UDF_HOME` / relocated interpreters | open deployment question (§2b) |
| 8 | `scrub_inherited_path()` | **no tests** — see §2a |
| 9 | 3.15 is rc2 | re-run against final |

## 6. The one question I would most like answered

Item 6 is the one I have been avoiding. `MAINTAINERS.md` §5 requires the
matrix repeated under ASan/TSan/UBSan, and this work has now modified
C-adjacent product code (`fr_udf.c`, including a list-mutating helper).
`scrub_inherited_path()` in particular manipulates a Python list
through the C API, which is exactly the kind of thing that sanitizer
coverage exists to check.

**Is running the sanitizer branches the right next step, ahead of W-EXP-1?**
I have been treating sanitizers as a release-time obligation rather than
an active-work one, on the grounds that the change is small and
guarded. I do not think that reasoning survives §2a: untested security
code is a stronger argument for sanitizers than "keep the loop" was for
a benchmark.

## 6a. What I added since posting

`test_udf_helper.py` gains `TestInheritedPathScrubbed` (5 tests) and the
probe now prints `sys.path` with a per-entry caller-influenced marker
and a count, so the property is observable at all. The sharpest is
`test_the_working_directory_is_not_importable`, which launches the probe
from a directory containing a module that raises on import and requires
that module to be unreachable.

On 3.14 these pass and are a genuine regression guard. On a 3.10 host
the suite does **not** currently run — the substrate is 3.14-specific
and running the whole suite under another minor needs the full
per-minor substrate build, which I have not done. That is the honest
state of this coverage.

## 6b. Sanitizers — done for the targeted code, per §6 step 2

Agreed with the ordering (tests first, then sanitizers, then W-EXP-1),
and step 2 is now done for the code that actually changed.

ASan + UBSan builds of `fr_udf_helper` and `fr_udf_fork`, run against:

| path | result |
|---|---|
| probe from a hostile working directory | clean, module correctly unreachable |
| path variants (`''`, cwd, trailing slash, stdlib, validated root) | clean |
| driver, both candidates | clean, verdict stated |
| control + respawn probes | clean |
| **the whole `test_udf*.py` suite (59 tests) against the ASan binary** | **OK, zero reports** |

Built with `-fsanitize=address,undefined -fno-omit-frame-pointer -g -O1`,
`ASAN_OPTIONS=detect_leaks=0` (the `MAINTAINERS.md` §5 idiom — CPython
and bash produce false-positive leak reports at exit), `UBSAN_OPTIONS=
print_stacktrace=1`. No ASan or UBSan report files were produced.

**What this does and does not establish.** It is memory-safety and
undefined-behaviour coverage for the new C code: the `PyList_SetSlice`
deletion, the list iteration, the struct writes, the pipe protocol.
It does **not** establish the security property — that the right paths
were removed — which is what the functional tests are for. The review is
right that both are needed, and this is the second half.

**Not yet done: step 3 (TSan) and step 4 (the matrix under sanitizers).**
TSan is the interesting one, because the driver forks and the barrier
protocol is new concurrency code. Recorded as open rather than skipped.

## 7. Verification of this request

| | |
|---|---|
| Python suite | 1002 tests, 0 unexpected failures, 2 skipped |
| `release_check.py` | ALL CHECKS PASSED, clean tree |
| `UNIT_TESTS/test_frun.sh` | 96/96 |
| Frozen ring | untouched across `c72d27c6..HEAD` |
| Matrix script | `tools/matrix_c05.sh --quick`, all six minors reporting |
| Builds | helper + driver compile on all six minors |
| New scrub tests | 5, passing on 3.14; **not** exercised on 3.10 (see §2d) |