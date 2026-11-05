# forkrun v3.6.2 — release notes

**Python frontend 0.17.0 → 0.18.0.** Engine tag `v3.6.2`.
Prepared 2026-11-04. Promotion, changelog finalization, tagging and PyPI
publication are owner acts; this branch is release-ready, not released.

| gate | result |
|---|---|
| Python suite (clean committed tree) | full suite, both cleanroom modes; counts in the closeout report |
| Bash suites | `test_c_plugins.sh` + `test_frun.sh`, comprehensive, security; CI run recorded in the closeout report |
| Sanitizers | `sanitizer-validation.yml` with `mode=all` |
| `python/release_check.py` | exactly one designed-red failure pre-finalization: `Docs: CHANGELOG v3.6.2 heading is final (no (unreleased))` |

The exact workflow run URLs and the release HEAD SHA are recorded in the
closeout report that accompanies this branch. Any release-gate failure
other than the changelog-finality check means do not tag.

---

## The distribution is now a checked bundle

The release set is **six wheels plus one sdist**:

- CPython **3.10, 3.11, 3.12, 3.13, 3.14 and 3.15** (GIL builds), each
  tagged `cp3XX-cp3XX-manylinux_2_28_x86_64`;
- every wheel carries the UDF helper built for **that** minor;
- one source distribution that contains **no binaries** — `setup.py`
  rebuilds the substrate and launcher, and the helper is built per-minor
  for wheel builds.

The wheels that pass installed-wheel acceptance are the wheels that are
uploaded. A new CI `release-bundle` job downloads those six artifacts,
builds the sdist from the same commit, validates the assembled bundle,
checks `SHA256SUMS` with plain `sha256sum -c`, runs `twine check
--strict`, and uploads the consolidated candidate with 90-day retention.

Each acceptance cell also writes a **UDF acceptance receipt** beside its
wheel: a structured record, bound to the wheel's SHA-256, that its
installed helper ran a real UDF through the cleanroom launcher's typed
version barrier — isolated, separate-process, byte-exact, at the
expected minor. The bundle seals the six receipts into
`acceptance/` and records them per wheel in `BUILD-INFO.txt`
(`acc-sha256` / `acc-result` / `acc-minor`). This matters because
auditwheel strips the helper's `libpython` `DT_NEEDED` entry during
manylinux repair, so the repaired wheel's **filename** is a claim, not
proof: the receipt is the durable evidence of the helper's **compiled**
minor, and the bundle validator refuses a repaired helper that cannot
produce one.

`python/release_check.py` validates the bundle itself when
`FORKRUN_RELEASE_BUNDLE=<dir>` is set (mandatory when supplied; reported
not-applicable otherwise). It proves:

- exactly one wheel per supported minor, and no missing minor;
- every wheel's tag, METADATA, embedded engine version, glibc floor,
  UDF helper symbol set, and libpython-linkage/acceptance-receipt rule
  (a repaired wheel carries no `libpython` `DT_NEEDED` entry —
  auditwheel strips it — so its compiled minor must be proven by the
  sealed acceptance receipt bound to the wheel's SHA-256);
- every wheel's `forkrun/*.py` is byte-identical to the same file in the
  sdist (the components came from one source, not two builds);
- the sdist carries the required source files and no `.so`/launcher;
- `SHA256SUMS` describes the files present, and `BUILD-INFO.txt`
  records the source commit, ref, workflow URL and a source-tree
  fingerprint that `--expect-tree` recomputes from the checkout.

### sdist: source means source

setuptools copies `package_data` into the sdist, so a packager who had
built the tree published `libforkrun_python.so`, `_forkrun_cleanroom`,
and the packager's minor-specific UDF helper **inside the "source"
tarball**. `MANIFEST.in` now excludes them, and the shared release rule
fails closed if a binary appears. The pre-fix tarball is rejected with
all three products named.

---

## SIGINT deferral: the boundary is a handshake

The process-wide SIGINT deferral had two boundary races:

1. A recorder invocation already running when the section closed could
   store after the flag was read (lost) or after it was cleared (a
   phantom in the next generation). The C recorder is now one `seq_cst`
   state word with CAS transitions (`ARMED`, `CLOSING`, `SEEN`,
   `PENDING`, `BROKEN`); an invocation never records into a closed
   generation — it hands off to the closing `end()` or forwards through
   the restored host disposition.
2. A process-directed SIGINT whose eligible thread had not been
   scheduled stayed in the kernel pending set, so restoring the host
   disposition let CPython's handler fire at an arbitrary later
   bytecode. `end()` now blocks SIGINT on the closing thread and claims
   a pending signal with `sigtimedwait()` before restoring, after the
   in-flight drain, and after the generation closes. It is delivered
   synchronously on the closing thread, like a recorded signal.

Failure is explicit: a failed restore leaves the recorder armed, marks
it broken, makes later arms fail closed, and keeps the process
interruptible with `SIG_DFL`. Python raises `DeferralError` for arming,
disarming and forked-child reset failures; a failed disarm while an
exception is propagating records the failure without replacing that
exception. See `DOCS/CHANGELOG.md` for the full contract and tests.

---

## Cleanroom

### `map(plugin)` is default-on

When `FORKRUN_CLEANROOM` is **unset**, `map(plugin)` now runs through the
exec-based cleanroom launcher. `udf`, `spawn`, `stream(plugin)` and
`stream(udf)` remain opt-in. Restore the previous behavior with:

```bash
FORKRUN_CLEANROOM=0
```

`FORKRUN_CLEANROOM` is now a **route selector**, not a single boolean:

| value | effect |
|---|---|
| unset | `map-plugin` only |
| `0` / `no` / `off` / `false` / `""` | disable every route |
| `1` / `yes` / `on` / `true` / `all` | every eligible route (legacy meaning) |
| `map-plugin,map-udf` | the named subset |

An unknown route or malformed value raises `ValueError` rather than
being treated as "on". Unset-on is not asked-on: a caller who never
requested the cleanroom is not warned when a call falls back.

The default is backed by route-level launcher-execution proof,
paired A/B measurements (startup 1.77×; 2.34× with a 512 MB parent;
throughput 1.16×) and packaging that ships the launcher in the wheel.

### `posix_spawn` is the launch backend

The cleanroom routes now start the launcher with `os.posix_spawn()`
instead of `fork()` + `execv()`. There is no new keyword or environment
variable. Results, ordering, supervision, poison accounting and signal
dispositions are unchanged; the launch is cheaper from a large parent
(measured −31.6% end-to-end at a 2 GiB parent, no measurable change for
a small one). `fork()` + `execv()` remains a private fallback.

The route also relocates its descriptors with `fcntl(F_DUPFD, 3)` rather
than `dup()`, so a closed standard stream cannot make the launcher read
the wrong descriptor as input.

---

## UDF route

- **Extension imports work again.** The launcher loaded the per-minor
  helper with `RTLD_LOCAL`, so libpython's symbols never entered the
  global namespace and no CPython extension module could resolve
  `PyFloat_Type` and friends. `math`/`re` produced zero records with no
  exception; `json` silently ran without its C accelerator (4.6×
  slower). The helper is now loaded `RTLD_GLOBAL`; the disposable probe
  stays `RTLD_LOCAL`.
- **`mode="udf"` falls back when the route is not selected.** If the
  helper is not built for this minor, the cleanroom is off, or the call
  is not one the launcher serves, `mode="udf"` degrades to the documented
  in-process path instead of raising `NotImplementedError`. One
  authoritative decision (`_coerce_payload_inprocess`) is used by every
  in-process call site.
- **Each wheel carries the helper for its own minor.** The tag follows
  the helper's extension suffix, so a wheel cannot claim a minor its
  artifact was not built for. Free-threaded CPython remains
  **unsupported** for this route: the runtime and packaging use the same
  detector, both decline it, and the generic substrate path remains
  available.

---

## Correctness

- **A failed resume releases the source it opened.** Resume validation
  ran after the source descriptor was opened but before any executor
  owned it, leaking one fd per failed call. Cleanup now routes through
  the executor's single teardown; five consecutive failures hold the fd
  count at baseline, and a following valid run is byte-exact.
- **A helper child's death has one decision point.** The rule "expected
  when an abort is already in flight" was applied in 2 of 28 places; it
  is now `_helper_death_excused()` for all 24 helper-death raise sites,
  and the C drain/orderer teardowns share their own single points. The
  order is part of the rule: the consult precedes the abort it guards,
  and the architecture test fails if it is inverted.
- **`poisoned_batches` really is populated**, the notification survives
  teardown, and `poisoned_batches_truncated` says when the list is
  knowingly short.
- **The C drain no longer parks for 100 ms per chunk.** The reactor
  selects on the drain's results pipe and the pump consumes what is
  available instead of one 64 KiB chunk per call. Measured 16–19×
  slower → **1.00–1.05×** at scale; the 93% of wall spent waiting in
  `select()` collapsed to milliseconds. The pump's read-ahead is bounded
  by a 256 KiB consumer budget, not by the pipe, so peak retention stays
  flat instead of growing with the run.

## Performance and memory

- **The worker-completion notification pipe is a 4 KiB window**, not a
  1 MiB queue. On the plain-supervision path this is the backpressure
  link: peak retention falls 24–65% with no throughput or first-result
  penalty. On the reactor path the consumer is the C drain and its
  256 KiB read-ahead budget is the bound, so the notification-pipe size
  correctly does nothing there.
- **`map(plugin)` cleanroom default** is the startup/throughput win
  described above; it is largest for a loaded parent, which is the case
  the architecture targets.
- **`output="view"` remains the default** (`memoryview` records) and is
  unchanged from 0.17.0. Use `output="bytes"` for real `bytes`.

---

## Upgrade notes

1. **`map(plugin)` now uses the cleanroom by default.** Set
   `FORKRUN_CLEANROOM=0` to restore the in-process path. The route
   selector accepts a comma-separated subset if you want some routes
   and not others.
2. **Install the wheel for your interpreter.** Each wheel carries a
   helper linked against that minor's `libpython`; a wheel for another
   minor will not load the UDF route. `pip` selects the right one
   automatically. A source install builds the helper for the interpreter
   that runs `setup.py`.
3. **Free-threaded CPython is not served by the UDF helper route.**
   The substrate still loads; `mode="udf"` falls back in-process.
4. **No engine-level breaking changes.** `frun -V` reports
   `forkrun v3.6.2`; the embedded loadables are regenerated and
   freshness-checked in CI.

Full detail, measurements and test counts are in `DOCS/CHANGELOG.md`.
