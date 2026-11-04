# TAG_PREP_v3.6.2 — owner's keypress kit

**Do not tag. Do not push to `main`. Do not finalize the CHANGELOG
heading. Do not upload to PyPI.** Those are owner acts, staged here.
The working branch `NEW/REFACTOR4.8-SIGINT` is release-ready: everything
below has been run on it, and the only designed-red gate is the
changelog heading that the owner finalizes at step 5.

## 1. State this kit was prepared from

| item | value |
|---|---|
| branch | `NEW/REFACTOR4.8-SIGINT` |
| release HEAD | the tip at closeout; exact SHA is in the closeout report (a commit cannot name itself) |
| engine | `v3.6.2` (frozen: `forkrun_ring.c`, `forkrun_substrate.h`, `substratestubs.c` untouched by closeout) |
| Python frontend | `0.18.0` (`python/forkrun/__init__.py`) |
| `META` | `v3.6.2` |
| tag `v3.6.2` | does not exist locally or on the remote |
| CHANGELOG heading | `## v3.6.2 — unreleased` (deliberately red) |
| release set | 6 wheels (CPython 3.10–3.15, GIL) + 1 sdist |

## 2. The sequence, in order

1. **Promote `NEW/REFACTOR4.8-SIGINT` to `main`** (owner act). Do not
   squash away the release-bundle/tooling commits: the wheel artifacts
   are traceable to the source commit recorded in `BUILD-INFO.txt`.
2. **CI green on `main`**, including the new `release-bundle` job. The
   six `udf-acceptance` cells upload the repaired wheels; the bundle job
   waits for all six, builds the sdist from the same commit, and uploads
   `forkrun-release-candidate-<sha>`.
3. **Download the candidate bundle** from that run (Actions artifact,
   90-day retention). Do not rebuild the wheels by hand: a rebuilt wheel
   is not the wheel that passed installed-wheel acceptance.
4. **Validate the bundle on a clean checkout of `main`:**
   ```bash
   python3 tools/release_bundle.py validate \
     dist/release-candidate --expect-tree
   ( cd dist/release-candidate && sha256sum -c SHA256SUMS )
   python3 -m twine check --strict \
     dist/release-candidate/*.whl dist/release-candidate/*.tar.gz
   ```
5. **Finalize the CHANGELOG heading** in `DOCS/CHANGELOG.md`:
   `## v3.6.2 — unreleased` → `## v3.6.2 — <release date>` (the v3.6.1
   convention is `## v3.6.1 — 2026-10-06`). Regenerate the twin:
   ```bash
   python3 tools/gen_docs_all.py
   python3 tools/gen_docs_all.py --check
   ```
   Commit on `main` (documentation only; the sdist source payload is
   unchanged, so the bundle still validates with `--expect-tree`).
6. **Run the release gate on that committed tree:**
   ```bash
   FORKRUN_RELEASE_CHECK_TAGS=1 \
   FORKRUN_RELEASE_BUNDLE=dist/release-candidate \
   python3 python/release_check.py
   ```
   Expected: **ALL CHECKS PASSED**. Before step 5, the same command
   reports exactly one failure — the changelog heading — and nothing
   else. Any other failure means DO NOT TAG.
7. **Tag `v3.6.2`** on the committed `main` and push the tag:
   ```bash
   git tag -a v3.6.2 -m "forkrun v3.6.2"
   git push origin v3.6.2
   ```
8. **Verify the tag points at the release commit** and re-run the gate
   **without** `FORKRUN_RELEASE_CHECK_TAGS=1`:
   ```bash
   git tag --points-at HEAD          # must print v3.6.2
   FORKRUN_RELEASE_BUNDLE=dist/release-candidate \
     python3 python/release_check.py
   ```
   Do **not** re-run with `FORKRUN_RELEASE_CHECK_TAGS=1` once the tag
   exists: that gate correctly refuses to pass over an already-taken
   tag, so the pre-tag run in step 6 is the authoritative one.
9. **Publish to PyPI** (owner credentials; this repository never holds
   them):
   ```bash
   python3 -m twine upload dist/release-candidate/*.whl \
                               dist/release-candidate/*.tar.gz
   ```
10. **Verify the published set:** `pip install forkrun==0.18.0` on at
    least one GIL interpreter per wheel tag family, then confirm
    `forkrun.__version__ == "0.18.0"`, `forkrun.__engine_version__ ==
    "v3.6.2"`, and `pip download --no-deps --only-binary=:all: forkrun==0.18.0`
    resolves the wheel for the host minor (not the sdist).

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
  tag, and its UDF helper exports the typed version symbol and links
  `libpython3.XX.so`;
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

The closeout report for this branch carries the full receipts: the local
suite counts in both cleanroom modes, the four GitHub Actions run URLs
at the release HEAD, the release-candidate artifact name and SHA-256
digests, and the release-check transcript. The durable claims in this
kit are the commands and their expected results; the run IDs are
evidence for the specific HEAD, not a second source of truth.

## 5. Known-open items recorded into the tag

- **Real multi-node NUMA hardware** is not available on this box; the
  NUMA tests that require it skip locally and run in CI where the
  topology is available. This is a test-environment limit, not a
  claimed pass.
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

## 6. What this branch deliberately did NOT do

- no merge/push to `main`;
- no tag creation or push;
- no GitHub release;
- no PyPI upload and no use of PyPI credentials;
- no change to the frozen engine files;
- no weakening or skipping of tests (the one expected red gate is the
  designed changelog finality check).
