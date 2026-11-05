# Round 15 — re-review of the round-14 corrections

Branch `NEW/REFACTOR4.2`. Review the **branch head**. Round 14 reviewed
`84c3a3f2`.

**1055 tests, 0 unexpected failures, 2 skipped.** Release gate green.
Frozen ring untouched.

Round 14 found two implementation issues and two tests that did not prove
what their names claimed. All four are corrected, **and two of the
corrections were fixes to fixes that had not actually worked** — the same
pattern as round 13. That pattern is the main thing I would like judged.

---

## 1. The deadline is now an absolute monotonic bound

Round 14 was right: `waited_ms` advanced only when `poll()` *timed out*,
so `EINTR` storms and partial reads left it behind and elapsed time could
exceed the bound without the counter reaching it.

Now an absolute `CLOCK_MONOTONIC` deadline, re-derived before every poll.
Measured: 5.2s against a 5s bound (exit 81), and a malformed declaration
returns 82 in **4ms**.

## 2. The reap claim is now accurate

The old code killed and returned without reaping again after a complete
report. One shared `udf_reap_bounded()` is now used after every kill, and
if the child still will not reap the launcher reports **"cleanup NOT
confirmed"** rather than claiming it succeeded.

## 3. Typed version representation — implemented as recommended

New `forkrun_udf_version.h`:

```c
struct fr_udf_version { int major; int minor; };
typedef void (*fr_udf_built_version_fn)(struct fr_udf_version *out);
```

There is now nothing to pack differently between the two sides, which is
precisely how the original bug happened. An out-parameter rather than a
by-value struct return, because struct-return ABI is platform-defined.
The test override sets the two fields independently.

## 4. The cache fix, second attempt

Round 13's fix captured the **path** before launching but still
fingerprinted **after** the launcher returned — so it fixed nothing on the
path that matters. The fingerprint is now captured at dispatch time and
threaded through as a parameter. The module-global slot is gone; it was
written outside `_RUN_LOCK`, so concurrent calls could overwrite each
other.

**I am withdrawing my own earlier argument.** "The cache is safe because
`_RUN_LOCK` serialises execution" was incomplete — the slot was written
outside that lock and capability lookups can happen outside it. An
explicit `RLock` now makes the intended model visible rather than
inferred. The dict remains a negative cache and can never authorise
loading an unverified helper.

## 5. Tests that proved nothing — all four replaced

| was | now |
|---|---|
| timeout-cache test launched a temp helper through the C launcher, then asserted the **installed** helper was absent from the **Python** cache | exercises `_record_compat_refusal` for 80/81/82 directly, with 80 as positive control; exit 81 asserted separately |
| "never reaches dlopen" grepped stderr for `"probe"`/`"dlopen"` — a *successful* dlopen emits neither | uses the hanging fixture and **measures**: 82 in milliseconds, because a constructor that ran would cost ~5s and exit 81 |
| positive control asserted `!= 80`, which an unrelated 69 or 71 satisfies | asserts `== 0` |
| deadline bound was 60s against a 5s limit | 12s, so the deadline must actually be enforced |

Added a **helper-replacement** regression: the cache must not outlive the
artifact it described, or a user who upgrades the helper mid-process is
permanently shadowed.

## 6. Sanitizers re-run over the new C

ASan+UBSan: **zero findings** across matching (0), mismatch (80), invalid
declaration (82), and the hung-constructor timeout (81).

Non-vacuity checked by injecting a heap overflow into `setup_udf_helper` —
caught immediately.

**Worth recording:** my first attempt at that non-vacuity check was itself
vacuous. The injected line never landed because its anchor had been edited
away, so the "mutant" was an unmutated launcher that of course reported
nothing. A check that cannot fail is the same failure mode as the tests
rounds 13 and 14 kept finding, and it was mine.

TSan: zero warnings, and still close to uninformative — the launcher is
fork-based and the processes never share memory.

## 7. Cross-minor, for real

A genuine helper built against the cached 3.12 headers, driven by the
3.14 launcher:

| declared | libpython3.12 on loader path | exit | outcome |
|---|---|---|---|
| **3.14** (truthful) | yes | **80** | `was built against CPython 3.12` |
| 3.12 (matches helper) | yes | 71 | **helper LOADED**, then the embedded 3.12 interpreter failed on path configuration |
| 3.14 | no | 71 | probe failed to load |

Row 1 is §5.5 met on a real artifact rather than a synthetic override.

**Row 2 is why the feature exists.** The loader satisfied `libpython3.12`
from `LD_LIBRARY_PATH` and did **not** consider it a mismatch. Without the
explicit comparison a 3.14 process would have initialised a 3.12
interpreter and run the UDF under it.

Row 3 is why the criterion previously looked unnecessary — without the
other minor on the path, `dlopen` fails on its own. It is wrong precisely
when `LD_LIBRARY_PATH` supplies that minor.

## 8. A packaging regression I introduced and the suite caught

Adding the shared header broke `pip install` from the sdist: it was not in
`MANIFEST.in`, so `make python-substrate` failed for anyone installing
from source. Fixed, and confirmed by bisecting against HEAD.

## 9. Still open

1. **`auditwheel` unverified** — agreed and unchanged. Nothing is claimed
   about wheel-time `RPATH`/`RUNPATH`.
2. **`LD_LIBRARY_PATH` containment is deliberately out of scope.** Row 2
   above shows a caller can still influence *which* `libpython` of a
   *matching* minor loads. This is a correctness barrier, not a loader
   containment mechanism.
3. **Memory safety is not claimed** for the helper itself.
4. **The probe closes the source descriptor and stdin in the disposable
   child.** Round 14 confirmed this is appropriate but asked me not to
   overclaim: a successful probe is followed by a second `dlopen()` in the
   launcher that runs constructors again. The closure protects the
   *refusal* path; it is not a sandbox. The comment now says so.

## 10. Questions

1. Is the deadline genuinely bounded now, independent of signals and
   partial reads?
2. Does the typed representation actually eliminate the packing failure
   mode, or is there a residual one?
3. Is the per-invocation fingerprint correct, and is the lock warranted
   or noise?
4. **Is there a fifth test in the "proved nothing" category that I have
   not noticed?** Three rounds have each found one or more, and I have
   stopped trusting my own read of this diff.
