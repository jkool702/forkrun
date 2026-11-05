# TAG_PREP_v3.6.2 — owner's keypress kit

**Do not tag. Do not create the GitHub Release** — those two remain
owner acts. Everything before them is done: the CHANGELOG heading is
finalized, the release gate is green on the finalized tree, and the
validated seven-file bundle is published to PyPI. PR #588 is MERGED;
`main` carries the release. The publication order was owner-selected
and intentional: **finalize the changelog → release gate → PyPI →
tag → GitHub Release.** PyPI first: once PyPI accepts a distribution
file, the same version/file cannot be replaced with different bytes,
so every artifact-changing correction must be resolved before upload.

## 1. State this kit was prepared from

| item | value |
|---|---|
| PR #588 | MERGED; merge commit `ec1cad87dbdfaf645eb1976cc3713f6edbe3afcf` (initial post-merge reference) |
| branch | `main` |
| final source + docs commits | recorded in the closeout report of WO-POST-MERGE-RELEASE-FINALIZATION-362 (a commit cannot name itself; later commits may have landed after the merge — do not assume the merge SHA is the release commit) |
| engine | `v3.6.2` (frozen: `forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c` untouched) |
| Python frontend | `0.18.0` (`python/forkrun/__init__.py`) |
| `META` | `v3.6.2` |
| tag `v3.6.2` | does not exist locally or on the remote |
| CHANGELOG heading | `## v3.6.2 — 2026-11-05` (finalized) |
| release set | 6 wheels (CPython 3.10–3.15, GIL) + 1 sdist |

## 2. The sequence, in order

Steps 1–3 have been **completed** (by the preparation session, with the
owner's authorization for the PyPI upload); steps 4–7 remain owner
acts.

1. ~~**Finalize the CHANGELOG heading**~~ **DONE** —
   `DOCS/CHANGELOG.md` now reads `## v3.6.2 — 2026-11-05`; the twin was
   regenerated (`gen_docs_all.py --check` green) and committed to
   `main`.
2. ~~**Run the release gate**~~ **DONE** —
   `FORKRUN_RELEASE_CHECK_TAGS=1 FORKRUN_RELEASE_BUNDLE=dist/release-candidate
   python3 python/release_check.py` reports **ALL CHECKS PASSED** on the
   finalized tree (transcript in the closeout report).
3. ~~**Publish the validated bundle to PyPI**~~ **DONE** — the exact
   seven files from the validated bundle were uploaded with
   `twine upload` and verified on PyPI (see step 4). The generic
   `py3-none` wheel was NOT uploaded. If an upload fails partway,
   record exactly which files PyPI accepted before any further action:
   an accepted file cannot be replaced with different bytes.
4. **Verify all seven published distributions** match the candidate:
   `pip download --no-deps --only-binary=:all: forkrun==0.18.0`
   resolves the per-minor wheel for the host minor (not the sdist);
   `pip download --no-deps --no-binary=:all: forkrun==0.18.0` fetches
   the sdist; compare the downloaded bytes' SHA-256 against the
   bundle's `SHA256SUMS`. Spot-check
   `forkrun.__version__ == "0.18.0"` and
   `forkrun.__engine_version__ == "v3.6.2"` on an installed
   interpreter.
5. **Tag the exact final release commit** (the post-finalization docs
   commit) and push the tag:
   ```bash
   git tag -a v3.6.2 -m "forkrun v3.6.2"
   git push origin v3.6.2
   ```
6. **Create the GitHub Release from that tag** (owner act).
7. **Verify the tag, release, and published package:**
   `git tag --points-at HEAD` prints `v3.6.2`; the GitHub Release
   exists and names the seven assets or links PyPI; a fresh
   `pip install forkrun==0.18.0` works.
8. **Re-run the gate WITHOUT `FORKRUN_RELEASE_CHECK_TAGS=1`** after the
   tag exists:
   ```bash
   FORKRUN_RELEASE_BUNDLE=dist/release-candidate \
     python3 python/release_check.py
   ```
   Do **not** re-run with `FORKRUN_RELEASE_CHECK_TAGS=1` once the tag
   exists: that gate correctly refuses to pass over an already-taken
   tag, so the pre-tag run in step 2 is the authoritative one.

### The candidate bundle (produced before this kit applies)

The bundle this kit consumes was assembled on `main` by the
`release-bundle` job: the six repaired wheels that passed the six
installed-wheel UDF acceptance jobs, the sdist built from the same
commit, `SHA256SUMS`, `BUILD-INFO.txt`, and the six acceptance
receipts under `acceptance/`. Download it as
`forkrun-release-candidate-<sha>` (Actions artifact, 90-day
retention). Do not rebuild the wheels by hand: a rebuilt wheel is not
the wheel that passed installed-wheel acceptance.

Operational note: if one matrix cell needs a reload, re-dispatch the
**whole** workflow as a fresh single-attempt run — do not use
"re-run failed jobs". A partial re-run is a new attempt whose
`download-artifact` merges see only that attempt's uploads, so the
bundle job fails closed on an incomplete set.

Sdist-payload rule: `python/README.md` IS part of the sdist payload,
so a post-bundle README edit would break `--expect-tree`. The README's
helper/libpython correction was therefore made BEFORE the final bundle
was built; after validation, only documentation outside the sdist
(`DOCS/*`, `RELEASE_NOTES_*`, `dev/supervisor/*`) may change.

## 3. What the bundle validator proves

`FORKRUN_RELEASE_BUNDLE=<dir>` is mandatory when the variable is set and
reported not-applicable otherwise. It shares its rules with
`tools/wheel_matrix.py`, so the release gate and the bundle assembler
cannot disagree:

- exactly one wheel per `SUPPORTED_MINORS`; a missing or duplicated
  minor is a failure, never an incomplete release;
- each wheel's filename tags match its artifact and its minor, its
  METADATA is complete, its embedded substrate reports `v3.6.2`, its
  glibc floor is re-derived from **every** `.so` and does not exceed the
  tag, and its UDF helper exports the typed version symbol with no
  test-only override marker. The helper's `libpython` linkage follows
  the runtime contract (`forkrun_cleanroom.c::setup_udf_helper`): the
  launcher preloads the caller's libpython and refuses version
  mismatches, so auditwheel's strip of the `DT_NEEDED` entry in the
  repaired wheel is expected. A **present** entry must name the wheel's
  minor; an **absent** entry is accepted only with the wheel's sealed
  installed-wheel UDF acceptance receipt (`acceptance/*.json`, bound to
  the wheel SHA-256 and cross-recorded in `BUILD-INFO.txt`
  `acc-sha256` / `acc-result` / `acc-minor`), which is what proves the
  helper's **compiled** minor through the launcher's own version
  barrier — a filename suffix alone is never accepted. A bundle with no
  receipts, a receipt for another wheel, a wrong marker minor, or a
  failed acceptance run fails closed;
- every wheel's `forkrun/*.py` is byte-identical to the same file in the
  sdist; the sdist's source payload matches the checkout under
  `--expect-tree`;
- `SHA256SUMS` lists every artifact with the right digest and no extras;
- `BUILD-INFO.txt` names the 40-hex source commit, ref, workflow URL,
  versions, and a source-tree fingerprint that describes this bundle;
- the sdist carries the required build sources and **no** `.so` or
  `_forkrun_cleanroom` member.

The release-check gate also builds its own wheel + sdist and runs the
full suite, so the bundle check is an additional proof about the actual
files, not a replacement for the build/install checks.

## 4. Verification receipts

The closeout report for WO-POST-MERGE-RELEASE-FINALIZATION-362 carries
the full receipts: main-branch workflow URLs and conclusions at the
exact final source commit, the six UDF acceptance job results, the
release-candidate artifact name and SHA-256 digests, the independent
validation results, and the release-check transcript. The durable
claims in this kit are the commands and their expected results; the
run IDs are evidence for the specific HEAD, not a second source of
truth.

## 5. Known-open items recorded into the tag

- **Real multi-node NUMA hardware** is not available on this box; the
  NUMA tests that require it skip locally and run in CI where the
  topology is available. This is a test-environment limit, not a
  claimed pass.
- **Intermittent CI flake (documented, unfixed):** three CI runs have
  hit `RuntimeError: forkrun: NUMA scan 0 failed (status 0)` from
  `_watch_numa_pipeline`, each time in a DIFFERENT `test_numa` method
  (`test_numa_basic`, `test_numa_empty_input`,
  `test_numa_orchestrator_flag_accepted`) — the scan helper exits 0
  before its completion is observed and the death is misread as
  failure. Load/timing-dependent; the same runs' other NUMA tests
  pass. Establish non-reproduction with a fresh run; do not silently
  count a failed run as green. A dedicated work order should make the
  scan-death handling tolerate a completed scan.
- **Free-threaded CPython** is deliberately unsupported for the UDF
  helper route (different libpython soname, no measured evidence). The
  wheel matrix is GIL-only by design; the generic substrate path still
  loads.
- **`author_email` is empty** in `setup.py` (`# Set by the maintainer
  before twine upload`). It is optional metadata and `twine check
  --strict` accepts it; the owner may set it before upload. No address
  is invented here.
- **Single-socket benchmark box**: memory-bandwidth claims remain
  scoped to the hardware in `DOCS/CHANGELOG.md`; no EPYC measurement is
  claimed for this release.

## 6. What the release work deliberately did NOT do

- no tag creation or push;
- no GitHub release;
- no change to the frozen engine files;
- no weakening or skipping of tests (the one expected red gate is the
  designed changelog finality check).
