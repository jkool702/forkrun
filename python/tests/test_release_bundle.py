"""The release bundle is a checked object, not a build log.

v3.6.2's distribution is six per-minor wheels plus one sdist. A green
matrix proves those artifacts COULD be built; the release set is only
correct if the files that will be uploaded are complete, traceable to
one source, and free of build products. These tests pin the rules the
release gate and `tools/release_bundle.py` share:

* a source distribution contains SOURCE (the MANIFEST regression that
  put host-built `.so` files and the launcher inside a "source" tarball);
* tar DIRECTORY members are not source files (the first tree
  fingerprint treated `python` as a file, which would have made
  `--expect-tree` reject every bundle);
* the six-minor matrix fails closed on a missing or duplicated minor;
* `SHA256SUMS` and provenance describe the files actually present;
* a wheel whose `forkrun/*.py` differs from the sdist is not the same
  source and cannot be released as one bundle.

The fixtures are synthetic and fast -- the real wheel rules (nm,
objdump, linkage) are exercised by the six-wheel CI bundle and by
`python/release_check.py`, which use the same functions.
"""

import hashlib
import io
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
import zipfile

_ROOT = os.path.normpath(os.path.join(os.path.dirname(
    os.path.abspath(__file__)), os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "tools"))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import release_bundle  # noqa: E402
import release_check  # noqa: E402
import wheel_matrix  # noqa: E402

VERSION = release_check.PY_VERSION
TAG = "cp310"


def _wheel_name(minor="3.10", version=VERSION):
    tag = "cp" + minor.replace(".", "")
    return "forkrun-%s-%s-%s-manylinux_2_28_x86_64.whl" % (
        version, tag, tag)


def _make_wheel(path, minor="3.10", init=b"# forkrun\n",
                metadata=True, extra=()):
    name = _wheel_name(minor)
    full = os.path.join(path, name)
    with zipfile.ZipFile(full, "w") as zf:
        zf.writestr("forkrun/__init__.py", init)
        zf.writestr("forkrun/py.typed", "")
        for member in extra:
            zf.writestr(member, "x")
        if metadata:
            meta = "\n".join(
                field % VERSION if "%s" in field else field
                for field in wheel_matrix.REQUIRED_METADATA_FIELDS)
            zf.writestr(
                "forkrun-%s.dist-info/METADATA" % VERSION,
                "Metadata-Version: 2.1\n" + meta + "\n")
    return full


def _make_sdist(path, *, init=b"# forkrun\n", extra=(), drop=()):
    """A source-shaped tarball carrying the required source members."""
    files = {rel: ("/* %s */\n" % rel).encode("ascii")
             for rel in wheel_matrix.SDIST_REQUIRED_FILES}
    files["python/forkrun/__init__.py"] = init
    files["python/forkrun/py.typed"] = b""
    for rel in drop:
        files.pop(rel, None)
    files.update(dict(extra))
    top = "forkrun-%s" % VERSION
    full = os.path.join(path, "%s.tar.gz" % top)
    with tarfile.open(full, "w:gz") as tf:
        for rel, data in sorted(files.items()):
            info = tarfile.TarInfo("%s/%s" % (top, rel))
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        # Real sdists carry directory members, and tar omits the
        # trailing slash. Keep one so the fingerprint cannot silently
        # start treating `python` as a source file again.
        d = tarfile.TarInfo("%s/python" % top)
        d.type = tarfile.DIRTYPE
        tf.addfile(d)
        pkg = ("Metadata-Version: 2.1\nName: forkrun\nVersion: %s\n"
               % VERSION).encode("ascii")
        info = tarfile.TarInfo("%s/PKG-INFO" % top)
        info.size = len(pkg)
        tf.addfile(info, io.BytesIO(pkg))
    return full


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="forkrun_bundle_test_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def digest(self, path):
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()


class TestSdistContentRule(_Tmp):
    def test_directory_members_are_not_source_members(self):
        sdist = _make_sdist(self.tmp)
        top, members = wheel_matrix.sdist_source_members(sdist)
        self.assertEqual(top, "forkrun-%s/" % VERSION)
        self.assertNotIn("python", members)
        self.assertNotIn("python/forkrun.egg-info", members)
        for rel in members:
            self.assertTrue(os.path.isfile(os.path.join(_ROOT, rel)),
                            "%s is not a checkout file" % rel)

    def test_a_clean_sdist_passes(self):
        sdist = _make_sdist(self.tmp)
        self.assertEqual(
            [], wheel_matrix.validate_sdist(sdist, VERSION))

    def test_build_products_are_rejected_by_name(self):
        sdist = _make_sdist(self.tmp, extra={
            "python/forkrun/libforkrun_python.so": b"\x7fELF",
            "python/forkrun/_forkrun_cleanroom": b"\x7fELF",
            "python/forkrun/_fr_udf.cpython-310-x86_64-linux-gnu.so":
                b"\x7fELF",
        })
        problems = wheel_matrix.validate_sdist(sdist, VERSION)
        joined = "\n".join(problems)
        self.assertIn("libforkrun_python.so", joined)
        self.assertIn("_forkrun_cleanroom", joined)
        self.assertIn("_fr_udf.cpython-310", joined)
        self.assertEqual(
            3, len([p for p in problems if "build product" in p]))

    def test_an_elf_binary_with_an_innocent_name_is_rejected(self):
        # A renamed or versioned binary is still a binary. The name
        # rules would miss both of these.
        sdist = _make_sdist(self.tmp, extra={
            "python/forkrun/not_a_build_product": b"\x7fELF\x02\x01",
            "python/forkrun/libfoo.so.1": b"\x7fELF\x02\x01",
        })
        problems = wheel_matrix.validate_sdist(sdist, VERSION)
        joined = "\n".join(problems)
        self.assertIn("not_a_build_product", joined)
        self.assertIn("libfoo.so.1", joined)

    def test_a_missing_required_source_is_named(self):
        sdist = _make_sdist(self.tmp, drop=("forkrun_ring.c",))
        problems = wheel_matrix.validate_sdist(sdist, VERSION)
        self.assertTrue(any("missing forkrun_ring.c" in p
                            for p in problems), problems)


class TestMetadataRule(_Tmp):
    def test_complete_metadata_passes(self):
        wheel = _make_wheel(self.tmp)
        self.assertEqual(
            [], wheel_matrix.validate_metadata(wheel, VERSION))

    def test_a_missing_field_is_rejected(self):
        wheel = os.path.join(self.tmp, _wheel_name())
        with zipfile.ZipFile(wheel, "w") as zf:
            zf.writestr("forkrun/__init__.py", "")
            zf.writestr(
                "forkrun-%s.dist-info/METADATA" % VERSION,
                "Name: forkrun\nVersion: %s\n" % VERSION)
        problems = wheel_matrix.validate_metadata(wheel, VERSION)
        self.assertTrue(any("Summary:" in p for p in problems), problems)

    def test_the_version_is_not_taken_on_trust(self):
        wheel = _make_wheel(self.tmp, extra=())
        problems = wheel_matrix.validate_metadata(wheel, "9.9.9")
        self.assertTrue(any("Version: 9.9.9" in p for p in problems),
                        problems)


class TestBundleMatrix(_Tmp):
    def test_an_empty_bundle_names_every_missing_minor(self):
        report, problems = release_bundle.validate_bundle(self.tmp)
        joined = "\n".join(problems)
        for minor in wheel_matrix.SUPPORTED_MINORS:
            self.assertIn(minor, joined)
        self.assertEqual("FAIL", report["result"])

    def test_a_duplicate_minor_is_rejected(self):
        # Same minor, different version string: both filenames classify
        # as Python 3.10, and a release may contain exactly one.
        first = _make_wheel(self.tmp)
        second = os.path.join(
            self.tmp, _wheel_name(version="0.18.0.post1"))
        with zipfile.ZipFile(first) as src, zipfile.ZipFile(
                second, "w") as dst:
            for name in src.namelist():
                dst.writestr(name, src.read(name))
        _report, problems = release_bundle.validate_bundle(self.tmp)
        self.assertTrue(any("two wheels for Python 3.10" in p
                            for p in problems), problems)

    def test_unsupported_and_unparseable_wheels_are_rejected(self):
        _make_wheel(self.tmp, minor="3.16")
        _make_wheel(self.tmp, minor="3.9")
        with open(os.path.join(self.tmp, "forkrun-nonsense.whl"), "wb") as fh:
            fh.write(b"not a wheel")
        _report, problems = release_bundle.validate_bundle(self.tmp)
        joined = "\n".join(problems)
        self.assertIn("unsupported minor 3.16", joined)
        self.assertIn("does not name a CPython minor", joined)


class TestBundleIntegrity(_Tmp):
    def _assemble_one(self):
        wheels = os.path.join(self.tmp, "wheels")
        os.makedirs(wheels)
        _make_wheel(wheels)
        sdist = _make_sdist(self.tmp)
        out = os.path.join(self.tmp, "out")
        report, problems = release_bundle.assemble(
            wheels, sdist, out, "a" * 40, "refs/heads/test",
            "https://example.invalid/run/1")
        return out, report, problems

    def test_one_wheel_is_not_a_release(self):
        _out, _report, problems = self._assemble_one()
        missing = [m for m in wheel_matrix.SUPPORTED_MINORS
                   if m != "3.10"]
        joined = "\n".join(problems)
        for minor in missing:
            self.assertIn(minor, joined)

    def test_a_wrong_checksum_is_rejected(self):
        out, _report, _problems = self._assemble_one()
        sums = os.path.join(out, release_bundle.CHECKSUMS)
        with open(sums) as fh:
            lines = fh.readlines()
        with open(sums, "w") as fh:
            for line in lines:
                digest, name = line.split()
                if name.endswith(".whl"):
                    line = "%s  %s\n" % ("0" * 64, name)
                fh.write(line)
        _report, problems = release_bundle.validate_bundle(out)
        self.assertTrue(any("records a wrong SHA-256" in p
                            for p in problems), problems)

    def test_provenance_must_name_the_expected_commit(self):
        out, _report, _problems = self._assemble_one()
        _report, problems = release_bundle.validate_bundle(
            out, expect_source_commit="b" * 40)
        self.assertTrue(any("expected" in p and "b" * 40 in p
                            for p in problems), problems)

    def test_duplicate_provenance_rows_are_rejected(self):
        out, _report, _problems = self._assemble_one()
        info = os.path.join(out, release_bundle.BUILD_INFO)
        with open(info) as fh:
            lines = fh.readlines()
        row = next(line for line in lines if line.startswith("wheel: "))
        with open(info, "a") as fh:
            fh.write(row)
        _report, problems = release_bundle.validate_bundle(out)
        self.assertTrue(any("more than one wheel record" in p
                            for p in problems), problems)

    def test_a_wheel_from_another_source_is_rejected(self):
        wheels = os.path.join(self.tmp, "wheels")
        os.makedirs(wheels)
        _make_wheel(wheels, init=b"# DIFFERENT SOURCE\n")
        sdist = _make_sdist(self.tmp, init=b"# forkrun\n")
        out = os.path.join(self.tmp, "out")
        _report, problems = release_bundle.assemble(
            wheels, sdist, out, "a" * 40, "refs/heads/test", "")
        self.assertTrue(any("bytes that differ" in p
                            for p in problems), problems)

    def test_tree_fingerprint_is_order_independent(self):
        self.assertEqual(
            release_bundle.tree_fingerprint({"a": b"1", "b": b"2"}),
            release_bundle.tree_fingerprint({"b": b"2", "a": b"1"}))

    def test_the_tree_comparison_reads_real_checkout_files(self):
        with open(os.path.join(_ROOT, "README.md"), "rb") as fh:
            data = fh.read()
        self.assertEqual(
            [], release_bundle._tree_problems(
                {"README.md": data},
                release_bundle.tree_fingerprint({"README.md": data})))
        problems = release_bundle._tree_problems(
            {"README.md": data + b"\nTAMPERED"},
            release_bundle.tree_fingerprint({"README.md": data}))
        self.assertTrue(any("differs from the checkout" in p
                            for p in problems), problems)


class TestReleaseGateWiring(unittest.TestCase):
    def test_the_bundle_gate_is_optional_until_a_bundle_is_supplied(self):
        self.assertTrue(hasattr(release_check.check_release_bundle,
                                "only_if"))
        old = os.environ.pop(release_check.BUNDLE_ENV, None)
        try:
            self.assertFalse(
                release_check.check_release_bundle.only_if())
        finally:
            if old is not None:
                os.environ[release_check.BUNDLE_ENV] = old

    def test_a_supplied_bundle_is_mandatory(self):
        self.assertIn(release_check.BUNDLE_ENV,
                      release_check.check_release_bundle.skip_message)
        self.assertNotIn("RELEASE_CHECK_TAGS",
                         release_check.check_release_bundle.skip_message)

    def test_the_shared_wheel_matrix_is_the_one_rule(self):
        # The gate and the bundle must not carry their own copies of the
        # metadata/sdist rules.
        self.assertIs(release_check._wheel_matrix(), wheel_matrix)


if __name__ == "__main__":
    unittest.main()
