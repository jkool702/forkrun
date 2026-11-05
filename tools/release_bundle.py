#!/usr/bin/env python3
"""Assemble and validate the forkrun RELEASE BUNDLE.

THE ARTIFACT
------------
PyPI receives SEVEN files for this release: one wheel per supported
CPython minor (each carrying the UDF helper built for THAT minor) plus
one source distribution. A "successful matrix build" is not that set --
the wheels can be built, tested and then discarded by CI, which is
exactly what used to happen. This module turns a set of built wheels
and an sdist into the bundle that is actually released, and validates a
bundle that already exists WITHOUT rebuilding it.

WHAT IT CHECKS, AND WHERE EACH RULE LIVES
-----------------------------------------
There is no second implementation of any packaging rule here:

* the supported-minor SET is ``tools/wheel_matrix.py::SUPPORTED_MINORS``;
* the wheel tag-vs-artifact rule is
  ``wheel_matrix.validate_wheel`` (which also pins the minor);
* the wheel METADATA rule is ``wheel_matrix.validate_metadata``;
* the sdist content rule is ``wheel_matrix.validate_sdist``;
* the UDF helper symbol rule is
  ``wheel_matrix.helper_symbol_problems``;
* the helper's libpython linkage + the acceptance-receipt rule is
  ``wheel_matrix.helper_libpython_problems`` /
  ``wheel_matrix.acceptance_receipt_problems``. The repaired shape
  (no libpython DT_NEEDED entry -- auditwheel strips it; see
  forkrun_cleanroom.c setup_udf_helper()) is accepted ONLY when the
  installed-wheel acceptance receipt binds this exact wheel to a
  barrier-verified, isolated, byte-exact execution at the expected
  minor. The receipt is recorded in BUILD-INFO.txt (acc-* fields)
  and re-verified here; a suffix-only claim is never accepted.
* the wheel's glibc floor is
  ``python/release_check.py::_wheel_glibc_floor``;
* the release versions are ``release_check.PY_VERSION`` /
  ``PROJECT_VERSION`` (the same authority the tag checklist uses);
* the substrate's engine version is read by
  ``release_check._so_engine_version``.

This module adds only what is genuinely BUNDLE-level: the exact
artifact set, the completeness of the six-minor matrix, one sdist,
the SHA-256 manifest, the provenance record, and the proof that every
component was produced from the SAME source -- by content, not by
trust:

* every wheel's ``forkrun/*.py`` must be byte-identical to the same
  file in the sdist (a wheel built from a different commit fails);
* the sdist's source payload is hashed into ``source-tree-sha256``, and
  ``validate --expect-tree`` recomputes that hash from the checkout, so
  a bundle built from a different tree is detectable even when the
  commit SHA is not compared (the owner's final release commit changes
  only release documentation, which is NOT in the sdist -- see
  TAG_PREP).

Usage:
    # assemble a bundle from built wheels + an sdist
    python3 tools/release_bundle.py assemble \\
        --wheels dist/udf-wheels --sdist dist/sdist \\
        --out dist/release-candidate \\
        --source-commit "$GITHUB_SHA" --source-ref "$GITHUB_REF" \\
        --source-workflow "$RUN_URL"

    # validate an existing bundle (no rebuild)
    python3 tools/release_bundle.py validate dist/release-candidate [--expect-tree]

Exits 0 only when every check passes; prints a JSON report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import zipfile

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_TOOLS)
for _p in (_TOOLS, os.path.join(_REPO, "python")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import wheel_matrix  # noqa: E402
import release_check as rc  # noqa: E402

# The bundle format marker. Bumping it is how a consumer refuses a
# bundle written by a different layout instead of guessing.
BUNDLE_FORMAT = "forkrun-release-bundle/1"
BUILD_INFO = "BUILD-INFO.txt"
CHECKSUMS = "SHA256SUMS"
DIST = "forkrun"

# Runtime members every wheel must carry. Imported from the installed-
# wheel acceptance harness rather than re-listed: that harness is what
# proves the members are INSTALLABLE, so the bundle must not accept a
# wheel it would refuse.
from acceptance_installed_wheel import REQUIRED_MEMBERS  # noqa: E402

_ARTIFACT_RE = re.compile(
    r"^forkrun-(?P<version>[^-]+)-(?P<python>[^-]+)-(?P<abi>[^-]+)-"
    r"(?P<platform>[^-]+)\.whl$")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_fingerprint(members):
    """One hash over the sdist's SOURCE payload.

    `members` maps repo-relative path -> bytes (see
    wheel_matrix.sdist_source_members). Sorted by path so the value does
    not depend on tar member order, and hashed with an explicit
    separator so two different file sets cannot collide by concatenation.
    """
    h = hashlib.sha256()
    for rel in sorted(members):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(hashlib.sha256(members[rel]).hexdigest().encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def _wheel_minor(wheel):
    """The CPython minor a wheel claims, from its python tag."""
    m = _ARTIFACT_RE.match(os.path.basename(wheel))
    if not m:
        return None
    pytag = m.group("python")
    if not pytag.startswith("cp3"):
        return None
    digits = pytag[2:]
    if len(digits) != 3:
        return None
    return "%s.%s" % (digits[0], digits[1:3])


def _extract_members(wheel, wanted):
    """Extract selected members of a wheel into a temp dir; return paths."""
    out = {}
    tmp = os.path.join(_workdir(), os.path.basename(wheel) + ".d")
    os.makedirs(tmp, exist_ok=True)
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if name in wanted:
                dest = os.path.join(tmp, os.path.basename(name))
                with open(dest, "wb") as fh:
                    fh.write(zf.read(name))
                out[name] = dest
    return out


_WORK = []


def _workdir():
    if not _WORK:
        import tempfile
        _WORK.append(tempfile.mkdtemp(prefix="forkrun_bundle_"))
    return _WORK[0]


def _cleanup():
    for path in _WORK:
        shutil.rmtree(path, ignore_errors=True)
    del _WORK[:]


def _wheel_sources(wheel):
    """The wheel's `forkrun/*.py` and `py.typed` members (name -> bytes)."""
    out = {}
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if not name.startswith("forkrun/"):
                continue
            if name.endswith("/"):
                continue
            if not (name.endswith(".py") or name.endswith("py.typed")):
                continue
            out[name[len("forkrun/"):]] = zf.read(name)
    return out


def wheel_problems(wheel, minor, version, engine_version, *,
                   acceptance=None):
    """Everything that must be true of ONE release wheel.

    `acceptance` is the installed-wheel UDF acceptance receipt for
    this exact wheel (wheel_matrix.load_acceptance_receipt), or None
    at the unit-test layer. It is REQUIRED whenever the helper is in
    the auditwheel-repaired shape (no libpython DT_NEEDED entry) and
    is ignored for a helper that still links its libpython (the
    tree-built shape), so the receipt rule cannot be bypassed by
    deleting an entry it does not cover ... see helper_libpython_
    problems.
    """
    problems = []
    problems += wheel_matrix.validate_wheel(wheel, minor)
    problems += wheel_matrix.validate_metadata(wheel, version)

    name = os.path.basename(wheel)
    m = _ARTIFACT_RE.match(name)
    if not m:
        problems.append("%s is not a forkrun wheel filename" % (name,))
        return problems
    if m.group("version") != version:
        problems.append("wheel version is %r, expected %r"
                        % (m.group("version"), version))
    plat = m.group("platform")
    pm = re.match(r"^manylinux_(\d+)_(\d+)_(x86_64|aarch64|i686)$", plat)
    if not pm:
        problems.append(
            "platform tag %r is not a PEP 600 manylinux_<maj>_<min>_<arch> "
            "tag (PyPI rejects a bare linux_* tag)" % (plat,))

    try:
        with zipfile.ZipFile(wheel) as zf:
            names = zf.namelist()
    except (OSError, zipfile.BadZipFile) as exc:
        return problems + ["wheel is not a readable zip: %s" % (exc,)]
    for rel in REQUIRED_MEMBERS:
        if rel not in names:
            problems.append("wheel is missing required member %r" % (rel,))

    helpers = [n for n in names
               if os.path.basename(n).startswith(wheel_matrix.HELPER_STEM)
               and n.endswith(".so")]
    if len(helpers) != 1:
        problems.append("wheel must carry exactly one UDF helper, found %r"
                        % (helpers,))
        return problems
    helper_name = helpers[0]
    substrate = [n for n in names
                 if n.endswith("libforkrun_python.so")]
    if len(substrate) != 1:
        problems.append("wheel must carry exactly one substrate .so, "
                        "found %r" % (substrate,))
        return problems

    extracted = _extract_members(wheel, {helper_name, substrate[0]})
    helper_path = extracted.get(helper_name)
    substrate_path = extracted.get(substrate[0])
    if helper_path:
        problems += wheel_matrix.helper_symbol_problems(helper_path)
        handed = acceptance
        if handed is not None:
            # Bind the receipt to THIS wheel's bytes before the
            # linkage rule looks at it: a receipt for another wheel
            # authorises nothing.
            problems += wheel_matrix.acceptance_receipt_problems(
                handed, minor=minor, wheel_sha256=sha256_file(wheel))
        problems += wheel_matrix.helper_libpython_problems(
            helper_path, minor, acceptance=handed)
    if substrate_path:
        try:
            ver = rc._so_engine_version(substrate_path)
        except AssertionError as exc:
            problems.append("substrate .so: %s" % (exc,))
        else:
            if ver != engine_version:
                problems.append(
                    "wheel-embedded engine reports %r, expected %r"
                    % (ver, engine_version))
    if pm:
        need = rc._wheel_glibc_floor(wheel)
        if need is not None:
            claimed = (int(pm.group(1)), int(pm.group(2)))
            if need > claimed:
                problems.append(
                    "wheel is tagged manylinux_%d_%d but its binaries "
                    "reference GLIBC_%d.%d" % (claimed + need))
    return problems


def _artifact_set(bundle):
    """Classify the bundle directory's files."""
    wheels, sdists, extra = [], [], []
    try:
        names = sorted(os.listdir(bundle))
    except OSError as exc:
        raise SystemExit("release_bundle: cannot read %s: %s"
                         % (bundle, exc))
    for name in names:
        path = os.path.join(bundle, name)
        if name == "acceptance" and os.path.isdir(path):
            # The acceptance receipts live in their own subdirectory
            # and are validated separately (validate_bundle); they are
            # not release artifacts.
            continue
        if not os.path.isfile(path):
            extra.append(name)
        elif name.endswith(".whl"):
            wheels.append(path)
        elif name.endswith(".tar.gz"):
            sdists.append(path)
        elif name in (CHECKSUMS, BUILD_INFO):
            pass
        else:
            extra.append(name)
    return wheels, sdists, extra


def _parse_checksums(path):
    entries = {}
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError("malformed SHA256SUMS line: %r" % (line,))
            digest, name = parts
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("not a SHA-256 digest: %r" % (digest,))
            if name in entries:
                raise ValueError("duplicate SHA256SUMS entry for %r"
                                 % (name,))
            entries[name] = digest
    return entries


def _parse_build_info(path):
    """Parse BUILD-INFO.txt into a dict. Strict: unknown keys are kept."""
    info = {"wheel": [], "sdist": []}
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if ":" not in line:
                raise ValueError("malformed BUILD-INFO line: %r" % (line,))
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if key == "wheel":
                fields = value.split()
                if len(fields) not in (7, 10):
                    raise ValueError("malformed wheel record: %r" % (line,))
                info["wheel"].append({
                    "minor": fields[0], "python_tag": fields[1],
                    "abi_tag": fields[2], "platform_tag": fields[3],
                    "filename": fields[4], "sha256": fields[5],
                    "helper": fields[6],
                    # Installed-wheel UDF acceptance evidence for this
                    # exact wheel (wheel_matrix.acceptance_receipt_
                    # problems). Legacy rows without them parse, but
                    # carry no evidence -- the validator then refuses
                    # a repaired helper that needs it.
                    "acc_sha256": fields[7] if len(fields) == 10 else None,
                    "acc_result": fields[8] if len(fields) == 10 else None,
                    "acc_minor": fields[9] if len(fields) == 10 else None})
            elif key == "sdist":
                fields = value.split()
                if len(fields) != 2:
                    raise ValueError("malformed sdist record: %r" % (line,))
                info["sdist"].append({"filename": fields[0],
                                      "sha256": fields[1]})
            else:
                info[key] = value
    return info


def validate_bundle(bundle, *, expect_tree=False, expect_source_commit=None,
                    expect_version=None):
    """Validate an already-built bundle. Returns (report, problems)."""
    version = expect_version or rc.PY_VERSION
    engine_version = rc.PROJECT_VERSION
    problems = []
    report = {"bundle": os.path.abspath(bundle), "version": version,
              "engine_version": engine_version, "wheels": {}, "sdist": None,
              "source_commit": None, "source_tree_sha256": None,
              "acceptance_receipts": {}}
    # ---- installed-wheel UDF acceptance receipts (bundle-level) -----
    # assemble() copies the six receipts (one per minor) into
    # <bundle>/acceptance/*.json; validate reads them back bound to
    # the wheel SHA-256. A receipt for another wheel, another minor,
    # or a failed run authorises nothing.
    receipts = {}
    receipts_dir = os.path.join(bundle, "acceptance")
    if os.path.isdir(receipts_dir):
        try:
            names = sorted(os.listdir(receipts_dir))
        except OSError as exc:
            names = []
            problems.append("cannot list acceptance receipts: %s" % (exc,))
        for n in names:
            if not n.endswith(".json"):
                problems.append("bundle acceptance/ contains a "
                                "non-receipt entry %r" % (n,))
                continue
            receipt, rproblems = wheel_matrix.load_acceptance_receipt(
                os.path.join(receipts_dir, n))
            problems += ["acceptance/%s: %s" % (n, p) for p in rproblems]
            if receipt is not None:
                receipts[receipt.get("wheel_sha256")] = receipt
                report["acceptance_receipts"][n] = receipt
    elif os.path.exists(receipts_dir):
        problems.append("bundle acceptance entry is not a directory")
    wheels, sdists, extra = _artifact_set(bundle)
    if not receipts and any(wheels):
        # A bundle with no receipts at all cannot prove a repaired
        # helper's compiled minor for ANY of its wheels. Legacy
        # bundles (pre-receipt) parse -- their BUILD-INFO rows carry
        # no acc-* evidence -- but the validator refuses them for
        # exactly this reason: suffix-only is not proof.
        problems.append(
            "bundle carries no installed-wheel UDF acceptance "
            "receipts (acceptance/ is missing or empty): the "
            "repaired helpers' compiled minors are unproven")
    if extra:
        problems.append(
            "bundle contains entries that are not release artifacts: %r "
            "(expected exactly %d wheels, one sdist, %s and %s)"
            % (extra, len(wheel_matrix.SUPPORTED_MINORS), CHECKSUMS,
               BUILD_INFO))

    # --- the six-wheel matrix -----------------------------------------
    seen = {}
    for wheel in wheels:
        minor = _wheel_minor(wheel)
        if minor is None:
            problems.append("%s does not name a CPython minor in its tags"
                            % (os.path.basename(wheel),))
            continue
        if minor not in wheel_matrix.SUPPORTED_MINORS:
            problems.append(
                "%s claims unsupported minor %s (supported: %s)"
                % (os.path.basename(wheel), minor,
                   ", ".join(wheel_matrix.SUPPORTED_MINORS)))
            continue
        if minor in seen:
            problems.append(
                "two wheels for Python %s: %s and %s (exactly one per "
                "supported minor)"
                % (minor, os.path.basename(seen[minor]),
                   os.path.basename(wheel)))
            continue
        seen[minor] = wheel
    missing = [m for m in wheel_matrix.SUPPORTED_MINORS if m not in seen]
    if missing:
        problems.append("bundle is missing wheels for %s -- an incomplete "
                        "matrix is not a release"
                        % (", ".join(missing),))
    if len(wheels) != len(wheel_matrix.SUPPORTED_MINORS):
        problems.append("bundle contains %d wheels, expected exactly %d"
                        % (len(wheels), len(wheel_matrix.SUPPORTED_MINORS)))

    for minor, wheel in sorted(seen.items()):
        handed = receipts.get(sha256_file(wheel))
        if handed is not None and handed.get("expect_minor") != minor:
            problems.append(
                "%s: its acceptance receipt names Python %r, not %s"
                % (os.path.basename(wheel),
                   handed.get("expect_minor"), minor))
        wproblems = wheel_problems(wheel, minor, version, engine_version,
                                   acceptance=handed)
        report["wheels"][minor] = {
            "filename": os.path.basename(wheel),
            "sha256": sha256_file(wheel),
            "problems": wproblems,
        }
        problems += ["%s (%s): %s" % (os.path.basename(wheel), minor, p)
                     for p in wproblems]

    # --- exactly one sdist --------------------------------------------
    if len(sdists) != 1:
        problems.append("bundle contains %d sdists, expected exactly one"
                        % (len(sdists),))
    sdist = sdists[0] if len(sdists) == 1 else None
    if sdist is not None:
        want = "forkrun-%s.tar.gz" % version
        if os.path.basename(sdist) != want:
            problems.append("sdist is %r, expected %r"
                            % (os.path.basename(sdist), want))
        sdproblems = wheel_matrix.validate_sdist(sdist, version)
        report["sdist"] = {"filename": os.path.basename(sdist),
                           "sha256": sha256_file(sdist),
                           "problems": sdproblems}
        problems += ["%s: %s" % (os.path.basename(sdist), p)
                     for p in sdproblems]

    # --- components built from ONE source -----------------------------
    if sdist is not None:
        try:
            _top, members = wheel_matrix.sdist_source_members(sdist)
        except (OSError, ValueError, tarfile.TarError) as exc:
            members = {}
            problems.append("cannot read the sdist's source payload: %s"
                            % (exc,))
        fingerprint = tree_fingerprint(members) if members else None
        report["source_tree_sha256"] = fingerprint
        for minor, wheel in sorted(seen.items()):
            try:
                sources = _wheel_sources(wheel)
            except (OSError, zipfile.BadZipFile) as exc:
                problems.append("%s: cannot read sources: %s"
                                % (os.path.basename(wheel), exc))
                continue
            for rel, data in sorted(sources.items()):
                relpath = "python/forkrun/" + rel
                if relpath not in members:
                    problems.append(
                        "%s carries forkrun/%s which the sdist does not "
                        "ship: the wheel and the sdist are not the same "
                        "source" % (os.path.basename(wheel), rel))
                elif members[relpath] != data:
                    problems.append(
                        "%s carries forkrun/%s with bytes that differ from "
                        "the sdist: the wheel was not built from this "
                        "source" % (os.path.basename(wheel), rel))
        if expect_tree and fingerprint is not None:
            tree_problems = _tree_problems(members, fingerprint)
            problems += tree_problems

    # --- integrity manifest -------------------------------------------
    sums_path = os.path.join(bundle, CHECKSUMS)
    info_path = os.path.join(bundle, BUILD_INFO)
    if not os.path.isfile(sums_path):
        problems.append("bundle has no %s" % (CHECKSUMS,))
    if not os.path.isfile(info_path):
        problems.append("bundle has no %s" % (BUILD_INFO,))

    entries = None
    if os.path.isfile(sums_path):
        try:
            entries = _parse_checksums(sums_path)
        except (OSError, ValueError) as exc:
            problems.append("%s: %s" % (CHECKSUMS, exc))
        else:
            actual = {os.path.basename(p): sha256_file(p)
                      for p in wheels + sdists}
            for name, digest in sorted(actual.items()):
                if name not in entries:
                    problems.append("%s does not list %s" % (CHECKSUMS,
                                                             name))
                elif entries[name] != digest:
                    problems.append(
                        "%s records a wrong SHA-256 for %s (manifest %s, "
                        "file %s)" % (CHECKSUMS, name, entries[name], digest))
            for name in sorted(entries):
                if name not in actual:
                    problems.append(
                        "%s lists %s, which is not in the bundle"
                        % (CHECKSUMS, name))

    if os.path.isfile(info_path):
        try:
            info = _parse_build_info(info_path)
        except (OSError, ValueError) as exc:
            info = None
            problems.append("%s: %s" % (BUILD_INFO, exc))
        if info is not None:
            problems += _provenance_problems(
                info, report, wheels, sdists, version, engine_version,
                entries, expect_source_commit)

    report["problems"] = problems
    report["result"] = "PASS" if not problems else "FAIL"
    return report, problems


def _tree_problems(members, fingerprint):
    """Is the bundle's source payload byte-identical to THIS checkout?"""
    problems = []
    for rel, data in sorted(members.items()):
        path = os.path.join(_REPO, rel)
        if not os.path.isfile(path):
            problems.append(
                "the sdist ships %s, which is absent from the checkout: "
                "the bundle was not built from this tree" % (rel,))
            continue
        with open(path, "rb") as fh:
            if fh.read() != data:
                problems.append(
                    "the sdist's %s differs from the checkout: the bundle "
                    "was not built from this tree" % (rel,))
    return problems


def _provenance_problems(info, report, wheels, sdists, version,
                         engine_version, entries, expect_source_commit):
    problems = []
    if info.get("format") != BUNDLE_FORMAT:
        problems.append("%s format is %r, expected %r"
                        % (BUILD_INFO, info.get("format"), BUNDLE_FORMAT))
    if info.get("package") != DIST:
        problems.append("provenance package is %r, expected %r"
                        % (info.get("package"), DIST))
    if info.get("version") != version:
        problems.append("provenance version is %r, expected %r"
                        % (info.get("version"), version))
    if info.get("engine-version") != engine_version:
        problems.append("provenance engine-version is %r, expected %r"
                        % (info.get("engine-version"), engine_version))
    commit = (info.get("source-commit") or "").strip()
    report["source_commit"] = commit or None
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        problems.append(
            "provenance source-commit is %r, not a full 40-hex commit: "
            "every artifact must be traceable to the commit it was built "
            "from" % (commit,))
    elif expect_source_commit and commit != expect_source_commit:
        problems.append(
            "bundle was built from %s, expected %s"
            % (commit, expect_source_commit))
    if not (info.get("source-ref") or "").strip():
        problems.append("provenance names no source-ref")
    if not (info.get("created-utc") or "").strip():
        problems.append("provenance names no created-utc")
    recorded_fp = (info.get("source-tree-sha256") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", recorded_fp):
        problems.append("provenance source-tree-sha256 is %r, not a "
                        "SHA-256 digest" % (recorded_fp,))
    elif report.get("source_tree_sha256") and \
            recorded_fp != report["source_tree_sha256"]:
        problems.append(
            "provenance source-tree-sha256 does not match the sdist's "
            "source payload (recorded %s, actual %s): the record does not "
            "describe this bundle"
            % (recorded_fp, report["source_tree_sha256"]))

    wheel_rows = info.get("wheel", [])
    recorded = {row["minor"]: row for row in wheel_rows}
    if len(recorded) != len(wheel_rows):
        problems.append(
            "provenance has more than one wheel record for a minor "
            "(the record must describe exactly the bundle's six wheels)")
    actual = {minor: os.path.basename(path)
              for minor, path in
              ((_wheel_minor(p), p) for p in wheels) if minor}
    if sorted(recorded) != sorted(actual):
        problems.append(
            "provenance records wheels for %s, the bundle has %s"
            % (sorted(recorded), sorted(actual)))
    for minor, filename in sorted(actual.items()):
        row = recorded.get(minor)
        if row is None:
            continue
        if row["filename"] != filename:
            problems.append("provenance records %s for Python %s, the "
                            "bundle has %s"
                            % (row["filename"], minor, filename))
        if entries is not None and entries.get(filename) not in (
                None, row["sha256"]):
            problems.append("provenance SHA-256 for %s disagrees with %s"
                            % (filename, CHECKSUMS))
        if row["python_tag"] != wheel_matrix.minor_tag(minor) or \
                row["abi_tag"] != wheel_matrix.minor_tag(minor):
            problems.append(
                "provenance tags for Python %s are %s-%s, expected %s-%s"
                % (minor, row["python_tag"], row["abi_tag"],
                   wheel_matrix.minor_tag(minor),
                   wheel_matrix.minor_tag(minor)))
        if not row["helper"].startswith("forkrun/"):
            problems.append("provenance helper path for Python %s is %r"
                            % (minor, row["helper"]))
        # Acceptance evidence recorded at assembly. Legacy rows
        # without it parse (acc_* are None) but then a repaired
        # helper -- which needs its receipt -- fails the wheel rule
        # above, so no provenance can invent evidence after the fact.
        if row.get("acc_sha256") is not None:
            if not re.fullmatch(r"[0-9a-f]{64}", row["acc_sha256"] or ""):
                problems.append("provenance acc-sha256 for Python %s is "
                                "not a SHA-256 digest" % (minor,))
            elif row["acc_sha256"] != row["sha256"]:
                problems.append(
                    "provenance acc-sha256 for Python %s (%s) is not "
                    "the wheel's own SHA-256 (%s): the acceptance "
                    "evidence does not describe this wheel"
                    % (minor, row["acc_sha256"], row["sha256"]))
            if row.get("acc_result") != "PASS":
                problems.append("provenance acc-result for Python %s is "
                                "%r, expected 'PASS'"
                                % (minor, row.get("acc_result")))
            if row.get("acc_minor") != minor:
                problems.append("provenance acc-minor for Python %s is "
                                "%r, expected %r"
                                % (minor, row.get("acc_minor"), minor))

    sdist_rows = info.get("sdist", [])
    if len(sdist_rows) != 1:
        problems.append("provenance records %d sdists, expected exactly one"
                        % (len(sdist_rows),))
    elif sdists:
        row = sdist_rows[0]
        if row["filename"] != os.path.basename(sdists[0]):
            problems.append("provenance sdist is %r, the bundle has %r"
                            % (row["filename"],
                               os.path.basename(sdists[0])))
        if entries is not None and entries.get(row["filename"]) not in (
                None, row["sha256"]):
            problems.append("provenance SHA-256 for the sdist disagrees "
                            "with %s" % (CHECKSUMS,))
    return problems


def _write_build_info(path, version, engine_version, source_commit,
                      source_ref, source_workflow, fingerprint, rows,
                      sdist_row, created):
    lines = [
        "format: %s" % BUNDLE_FORMAT,
        "package: %s" % DIST,
        "version: %s" % version,
        "engine-version: %s" % engine_version,
        "source-commit: %s" % source_commit,
        "source-ref: %s" % source_ref,
        "source-workflow: %s" % source_workflow,
        "source-tree-sha256: %s" % fingerprint,
        "created-utc: %s" % created,
    ]
    for row in rows:
        acc = row.get("acceptance") or {}
        lines.append(
            "wheel: %s %s %s %s %s %s %s %s %s %s"
            % (row["minor"], row["python_tag"], row["abi_tag"],
               row["platform_tag"], row["filename"], row["sha256"],
               row["helper"],
               acc.get("wheel_sha256", "-"),
               acc.get("result", "-"),
               acc.get("expect_minor", "-")))
    lines.append("sdist: %s %s" % (sdist_row["filename"],
                                   sdist_row["sha256"]))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def assemble(wheels_dir, sdist_path, out_dir, source_commit, source_ref,
             source_workflow, version=None, receipts_dir_value=None):
    """Copy + validate + seal the bundle. Returns (report, problems)."""
    import datetime
    import tempfile
    version = version or rc.PY_VERSION
    engine_version = rc.PROJECT_VERSION

    if os.path.isdir(sdist_path):
        found = [os.path.join(sdist_path, n)
                 for n in sorted(os.listdir(sdist_path))
                 if n.endswith(".tar.gz")]
        if len(found) != 1:
            raise SystemExit(
                "release_bundle: --sdist %s must hold exactly one .tar.gz, "
                "found %d" % (sdist_path, len(found)))
        sdist_path = found[0]
    if not os.path.isfile(sdist_path):
        raise SystemExit("release_bundle: no sdist at %s" % (sdist_path,))

    wheels = [os.path.join(wheels_dir, n)
              for n in sorted(os.listdir(wheels_dir))
              if n.endswith(".whl")]
    if not wheels:
        raise SystemExit("release_bundle: no wheels in %s" % (wheels_dir,))

    staged = tempfile.mkdtemp(prefix="forkrun_bundle_stage_")
    try:
        # Validate BEFORE copying, with the same code `validate` uses, so
        # assembly cannot seal a bundle that validation would reject.
        for wheel in wheels:
            shutil.copy2(wheel, os.path.join(staged, os.path.basename(wheel)))
        shutil.copy2(sdist_path,
                     os.path.join(staged, os.path.basename(sdist_path)))
        _top, members = wheel_matrix.sdist_source_members(sdist_path)
        fingerprint = tree_fingerprint(members)

        # Installed-wheel UDF acceptance receipts (one per minor) for
        # the wheels being sealed. Indexed by the wheel SHA-256 they
        # prove: a receipt for another wheel authorises nothing.
        receipts = {}
        if receipts_dir_value is not None:
            if not os.path.isdir(receipts_dir_value):
                raise SystemExit(
                    "release_bundle: --acceptance-receipts %s is not a "
                    "directory" % (receipts_dir_value,))
            staged_receipts = os.path.join(staged, "acceptance")
            os.makedirs(staged_receipts, exist_ok=True)
            for n in sorted(os.listdir(receipts_dir_value)):
                if not n.endswith(".json"):
                    raise SystemExit(
                        "release_bundle: --acceptance-receipts/%s is not "
                        "a receipt (.json); refusing to guess which "
                        "evidence to seal" % (n,))
                receipt, rproblems = \
                    wheel_matrix.load_acceptance_receipt(
                        os.path.join(receipts_dir_value, n))
                if rproblems or receipt is None:
                    raise SystemExit(
                        "release_bundle: acceptance receipt %s: %s"
                        % (n, "; ".join(rproblems)))
                receipts[receipt["wheel_sha256"]] = receipt
                shutil.copy2(os.path.join(receipts_dir_value, n),
                             os.path.join(staged_receipts, n))
            os.makedirs(os.path.join(out_dir, "acceptance"),
                        exist_ok=True)
            for n in os.listdir(staged_receipts):
                shutil.copy2(os.path.join(staged_receipts, n),
                             os.path.join(out_dir, "acceptance", n))

        os.makedirs(out_dir, exist_ok=True)
        for path in wheels + [sdist_path]:
            shutil.copy2(path, os.path.join(out_dir, os.path.basename(path)))

        rows = []
        for wheel in wheels:
            minor = _wheel_minor(wheel)
            name = os.path.basename(wheel)
            m = _ARTIFACT_RE.match(name)
            with zipfile.ZipFile(wheel) as zf:
                helpers = [n for n in zf.namelist()
                           if os.path.basename(n).startswith(
                               wheel_matrix.HELPER_STEM)
                           and n.endswith(".so")]
            rows.append({
                "minor": minor or "unknown",
                "python_tag": m.group("python") if m else "unknown",
                "abi_tag": m.group("abi") if m else "unknown",
                "platform_tag": m.group("platform") if m else "unknown",
                "filename": name,
                "sha256": sha256_file(wheel),
                "helper": helpers[0] if len(helpers) == 1 else "unknown",
                "acceptance": receipts.get(sha256_file(wheel)),
            })
        sdist_row = {"filename": os.path.basename(sdist_path),
                     "sha256": sha256_file(sdist_path)}
        rows.sort(key=lambda r: r["minor"])

        _write_build_info(
            os.path.join(out_dir, BUILD_INFO), version, engine_version,
            source_commit, source_ref, source_workflow or "(not recorded)",
            fingerprint, rows, sdist_row,
            datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"))

        # SHA256SUMS: sha256sum's own format (two spaces), so
        # `sha256sum -c SHA256SUMS` works without any of this code.
        lines = ["%s  %s" % (sha256_file(os.path.join(out_dir, n)), n)
                 for n in sorted([r["filename"] for r in rows]
                                 + [sdist_row["filename"]])]
        with open(os.path.join(out_dir, CHECKSUMS), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")

        report, problems = validate_bundle(
            out_dir, expect_source_commit=source_commit, expect_version=version)
        return report, problems
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)

    a = sub.add_parser("assemble", help="seal a bundle from built artifacts")
    a.add_argument("--wheels", required=True,
                   help="directory holding the six repaired wheels")
    a.add_argument("--sdist", required=True,
                   help="the sdist file, or a directory holding exactly one")
    a.add_argument("--out", required=True,
                   help="output directory for the release candidate")
    a.add_argument("--source-commit", required=True)
    a.add_argument("--source-ref", required=True)
    a.add_argument("--source-workflow", default="")
    a.add_argument("--acceptance-receipts", default=None,
                   help="directory of installed-wheel UDF acceptance "
                        "receipt JSON files (one per minor) for the "
                        "wheels being sealed; each receipt is bound to "
                        "an exact wheel SHA-256 by wheel_matrix."
                        "acceptance_receipt_problems")
    a.add_argument("--version", default=None)

    v = sub.add_parser("validate", help="validate an existing bundle")
    v.add_argument("bundle")
    v.add_argument("--expect-tree", action="store_true",
                   help="require the bundle's source payload to be "
                        "byte-identical to this checkout")
    v.add_argument("--expect-source-commit", default=None)
    v.add_argument("--version", default=None)

    args = ap.parse_args(argv)
    try:
        if args.mode == "assemble":
            report, problems = assemble(
                args.wheels, args.sdist, args.out, args.source_commit,
                args.source_ref, args.source_workflow, version=args.version,
                receipts_dir_value=args.acceptance_receipts)
        else:
            report, problems = validate_bundle(
                args.bundle, expect_tree=args.expect_tree,
                expect_source_commit=args.expect_source_commit,
                expect_version=args.version)
    finally:
        _cleanup()
    print(json.dumps(report, indent=2, sort_keys=True))
    if problems:
        sys.stderr.write("\nRELEASE BUNDLE INVALID (%d problem%s)\n"
                         % (len(problems), "" if len(problems) == 1 else "s"))
        for problem in problems:
            sys.stderr.write("  - %s\n" % (problem,))
        return 1
    print("\nRELEASE BUNDLE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
