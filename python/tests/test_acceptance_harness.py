"""Negative and structural tests for the installed-wheel acceptance harness.

The harness is the thing that decides whether a built wheel is accepted, so
its own failure modes are correctness-critical. These tests exercise the REAL
functions the harness calls -- wheel inspection, provenance, environment
sanitisation, and UDF report evaluation -- against synthetic wheels, plus the
CLI boundary for argument/ordering failures.

They do not need a real forkrun wheel, a container, or a second interpreter:
the positive end-to-end proof lives in CI (six generic + six UDF cells).
"""
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest
import zipfile

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_TOOLS = os.path.join(_ROOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import acceptance_installed_wheel as harness  # noqa: E402
import gen_python_matrix  # noqa: E402
import wheel_matrix  # noqa: E402

HARNESS = os.path.join(_TOOLS, "acceptance_installed_wheel.py")
UDF_SCRIPT = os.path.join(_TOOLS, "ci_udf_acceptance.sh")

# The synthetic wheels must match the interpreter running THIS suite, so
# the harness's real EXT_SUFFIX check is exercised rather than bypassed.
MINOR = "%d.%d" % sys.version_info[:2]
OTHER_MINOR = "3.14" if MINOR != "3.14" else "3.13"
SUFFIX = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
OTHER_SUFFIX = ".cpython-%s-x86_64-linux-gnu.so" % (
    OTHER_MINOR.replace(".", ""),)


def _helper_suffix(minor):
    if minor == MINOR:
        return SUFFIX
    return ".cpython-%s-x86_64-linux-gnu.so" % (minor.replace(".", ""),)


def _metadata(version="0.17.0"):
    return ("Metadata-Version: 2.1\n"
            "Name: forkrun\n"
            "Version: %s\n\n" % (version,)).encode("utf-8")


def _make_wheel(path, *, mode="generic", minor=None, version="0.17.0",
                helper_name=None, omit=(), metadata=None, extra=None,
                python_tag=None, abi_tag=None):
    """A wheel-shaped zip with the members the harness requires."""
    minor = minor or MINOR
    if python_tag is None:
        python_tag = "py3" if mode == "generic" else wheel_matrix.minor_tag(minor)
    if abi_tag is None:
        abi_tag = "none" if mode == "generic" else wheel_matrix.minor_tag(minor)
    name = "forkrun-%s-%s-%s-manylinux_2_28_x86_64.whl" % (
        version, python_tag, abi_tag)
    if os.path.basename(path) != name:
        path = os.path.join(os.path.dirname(path), name)
    members = {
        "forkrun/__init__.py": b'__version__ = "%s"\n' % version.encode(),
        "forkrun/libforkrun_python.so": b"\x7fELF substrate",
        "forkrun/_forkrun_cleanroom": b"\x7fELF launcher",
        "forkrun-%s.dist-info/METADATA" % version: (
            metadata if metadata is not None else _metadata(version)),
        "forkrun-%s.dist-info/WHEEL" % version: (
            "Wheel-Version: 1.0\n"
            "Generator: test\n"
            "Root-Is-Purelib: false\n").encode("utf-8"),
    }
    if mode == "udf":
        name_helper = helper_name or (
            wheel_matrix.HELPER_STEM + _helper_suffix(minor))
        members["forkrun/" + name_helper] = b"\x7fELF helper"
    for rel in omit:
        members.pop(rel, None)
    if extra:
        members.update(extra)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for rel, data in members.items():
            zf.writestr(rel, data)
    return path


def _inspect(path, *, mode="generic", expect_minor=MINOR,
             expected_suffix=SUFFIX):
    return harness.inspect_wheel(path, expect_minor, mode,
                                 expected_suffix=expected_suffix)


class WheelInspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fr_wheel_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _path(self, name="x.whl"):
        return os.path.join(self.tmp, name)

    def test_valid_generic_wheel_passes(self):
        wheel = _make_wheel(self._path(), mode="generic")
        info, problems = _inspect(wheel)
        self.assertEqual([], problems)
        self.assertEqual("py3", info["python"])
        self.assertEqual("none", info["abi"])
        self.assertIsNone(info["helper"])

    def test_valid_udf_wheel_passes(self):
        wheel = _make_wheel(self._path(), mode="udf")
        info, problems = _inspect(wheel, mode="udf")
        self.assertEqual([], problems)
        self.assertEqual(wheel_matrix.minor_tag(MINOR), info["python"])
        self.assertEqual("forkrun/" + wheel_matrix.HELPER_STEM + SUFFIX,
                         info["helper"])

    def test_malformed_wheel_rejected(self):
        path = os.path.join(
            self.tmp,
            "forkrun-0.17.0-py3-none-manylinux_2_28_x86_64.whl")
        with open(path, "w") as fh:
            fh.write("this is not a zip\n")
        _, problems = _inspect(path)
        self.assertTrue(any("not a readable wheel" in p for p in problems),
                        problems)

    def test_non_wheel_filename_rejected(self):
        path = os.path.join(self.tmp, "not_a_wheel.txt")
        with open(path, "w") as fh:
            fh.write("x")
        _, problems = _inspect(path)
        self.assertTrue(any("not a wheel filename" in p for p in problems),
                        problems)

    def test_missing_wheel_rejected(self):
        _, problems = _inspect(os.path.join(self.tmp, "absent.whl"))
        self.assertTrue(any("does not exist" in p for p in problems),
                        problems)

    def test_wrong_minor_tag_rejected(self):
        wheel = _make_wheel(self._path(), mode="udf", minor=OTHER_MINOR)
        _, problems = _inspect(wheel, mode="udf")
        self.assertTrue(any("expected" in p and wheel_matrix.minor_tag(MINOR)
                            in p for p in problems), problems)

    def test_udf_helper_wrong_suffix_rejected(self):
        wheel = _make_wheel(
            self._path(), mode="udf",
            helper_name="_fr_udf.cpython-999-x86_64-linux-gnu.so")
        _, problems = _inspect(wheel, mode="udf")
        self.assertTrue(any("EXT_SUFFIX" in p for p in problems), problems)

    def test_udf_without_helper_rejected(self):
        wheel = _make_wheel(self._path(), mode="udf", omit=(
            "forkrun/" + wheel_matrix.HELPER_STEM + SUFFIX,))
        _, problems = _inspect(wheel, mode="udf")
        self.assertTrue(any("exactly one helper" in p for p in problems),
                        problems)

    def test_generic_with_helper_rejected(self):
        wheel = _make_wheel(self._path(), mode="generic", extra={
            "forkrun/_fr_udf%s" % SUFFIX: b"\x7fELF helper"})
        _, problems = _inspect(wheel)
        self.assertTrue(any("must carry no UDF helper" in p
                            for p in problems), problems)

    def test_missing_substrate_rejected(self):
        wheel = _make_wheel(self._path(), omit=(
            "forkrun/libforkrun_python.so",))
        _, problems = _inspect(wheel)
        self.assertTrue(any("libforkrun_python.so" in p for p in problems),
                        problems)

    def test_missing_launcher_rejected(self):
        wheel = _make_wheel(self._path(), omit=("forkrun/_forkrun_cleanroom",))
        _, problems = _inspect(wheel)
        self.assertTrue(any("_forkrun_cleanroom" in p for p in problems),
                        problems)

    def test_wrong_metadata_version_rejected(self):
        wheel = _make_wheel(self._path(), metadata=_metadata("0.16.0"))
        _, problems = _inspect(wheel)
        self.assertTrue(any("METADATA version" in p for p in problems),
                        problems)

    def test_wrong_distribution_rejected(self):
        wheel = _make_wheel(self._path())
        renamed = os.path.join(
            self.tmp, "notforkrun-0.17.0-py3-none-manylinux_2_28_x86_64.whl")
        os.rename(wheel, renamed)
        _, problems = _inspect(renamed)
        self.assertTrue(any("distribution" in p for p in problems), problems)

    def test_wheel_with_path_escape_rejected(self):
        wheel = _make_wheel(self._path(), extra={"../escape": b"x"})
        _, problems = _inspect(wheel)
        self.assertTrue(any("escapes the install root" in p
                            for p in problems), problems)


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fr_prov_test_")
        self.wheel = _make_wheel(os.path.join(self.tmp, "w.whl"))
        self.root = os.path.join(self.tmp, "site-packages")
        for rel in harness.REQUIRED_MEMBERS:
            dest = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
        with zipfile.ZipFile(self.wheel) as zf:
            for rel in harness.REQUIRED_MEMBERS:
                dest = os.path.join(self.root, rel)
                with open(dest, "wb") as fh:
                    fh.write(zf.read(rel))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_identical_installed_files_pass(self):
        evidence, problems = harness.verify_installed_files(
            self.wheel, self.root, harness.REQUIRED_MEMBERS)
        self.assertEqual([], problems)
        self.assertEqual(set(harness.REQUIRED_MEMBERS), set(evidence))

    def test_tampered_installed_file_rejected(self):
        victim = os.path.join(self.root, "forkrun/libforkrun_python.so")
        with open(victim, "ab") as fh:
            fh.write(b"tampered")
        _, problems = harness.verify_installed_files(
            self.wheel, self.root, harness.REQUIRED_MEMBERS)
        self.assertTrue(any("installed bytes differ" in p for p in problems),
                        problems)

    def test_missing_installed_file_rejected(self):
        os.unlink(os.path.join(self.root, "forkrun/_forkrun_cleanroom"))
        _, problems = harness.verify_installed_files(
            self.wheel, self.root, harness.REQUIRED_MEMBERS)
        self.assertTrue(any("installed file missing" in p for p in problems),
                        problems)


class EnvironmentTests(unittest.TestCase):
    def test_hostile_parent_env_is_not_inherited(self):
        parent = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/tester",
            "LD_PRELOAD": "/tmp/evil.so",
            "LD_AUDIT": "/tmp/evil-audit.so",
            "LD_LIBRARY_PATH": "/tmp/evil-lib",
            "PYTHONPATH": "/tmp/evil-python",
            "PYTHONHOME": "/tmp/evil-home",
            "FORKRUN_LIB": "/tmp/evil-forkrun.so",
            "FORKRUN_CLEANROOM": "0",
            "FORKRUN_NO_UDF": "1",
            "FORKRUN_CLEANROOM_NUMA": "1",
            "FR_UDF_HOME": "/tmp/evil-stdlib",
            "FR_UDF_TRACEBACK": "1",
        }
        env, removed = harness.build_child_env(parent, "/real/lib",
                                               {"FORKRUN_CLEANROOM":
                                                "map-udf"})
        for key in ("LD_PRELOAD", "LD_AUDIT", "PYTHONPATH", "PYTHONHOME",
                    "FORKRUN_LIB", "FORKRUN_NO_UDF",
                    "FORKRUN_CLEANROOM_NUMA", "FR_UDF_HOME"):
            self.assertNotIn(key, env)
        # Diagnostics-only, so it may pass through: unlike FR_UDF_HOME it
        # cannot redirect the interpreter's stdlib.
        self.assertEqual("1", env["FR_UDF_TRACEBACK"])
        self.assertEqual("/real/lib", env["LD_LIBRARY_PATH"])
        self.assertEqual("map-udf", env["FORKRUN_CLEANROOM"])
        self.assertEqual("/usr/bin:/bin", env["PATH"])
        self.assertEqual("/home/tester", env["HOME"])
        self.assertEqual("1", env["PYTHONNOUSERSITE"])
        for key in ("LD_PRELOAD", "PYTHONPATH", "FORKRUN_LIB",
                    "FORKRUN_NO_UDF", "FORKRUN_CLEANROOM_NUMA",
                    "FR_UDF_HOME"):
            self.assertIn(key, removed)


class UdfReportTests(unittest.TestCase):
    NONCE = "a" * 32
    PARENT = 1234

    def _report(self, **marker_overrides):
        marker = {"pid": 5678, "isolated": True, "version": MINOR,
                  "nonce": self.NONCE}
        marker.update(marker_overrides)
        return {
            "bytes": 10,
            "sha256": "b" * 64,
            "parent_pid": self.PARENT,
            "markers": [marker],
            "helper": "/venv/forkrun/_fr_udf.so",
        }

    def _evaluate(self, report):
        return harness.evaluate_udf_report(
            report, expect_minor=MINOR, expected_bytes=10,
            expected_sha256="b" * 64, parent_pid=self.PARENT,
            nonce=self.NONCE)

    def test_valid_report_passes(self):
        self.assertEqual([], self._evaluate(self._report()))

    def test_stale_nonce_rejected(self):
        problems = self._evaluate(self._report(nonce="c" * 32))
        self.assertTrue(any("stale" in p for p in problems), problems)

    def test_in_process_fallback_rejected(self):
        problems = self._evaluate(self._report(isolated=False))
        self.assertTrue(any("isolated" in p for p in problems), problems)

    def test_same_process_rejected(self):
        problems = self._evaluate(self._report(pid=self.PARENT))
        self.assertTrue(any("separate" in p for p in problems), problems)

    def test_wrong_minor_rejected(self):
        problems = self._evaluate(self._report(version=OTHER_MINOR))
        self.assertTrue(any("expected" in p for p in problems), problems)

    def test_missing_markers_rejected(self):
        report = self._report()
        report["markers"] = []
        problems = self._evaluate(report)
        self.assertTrue(any("no UDF marker" in p for p in problems),
                        problems)

    def test_wrong_output_bytes_rejected(self):
        report = self._report()
        report["bytes"] = 9
        problems = self._evaluate(report)
        self.assertTrue(any("output length" in p for p in problems),
                        problems)

    def test_wrong_output_hash_rejected(self):
        report = self._report()
        report["sha256"] = "d" * 64
        problems = self._evaluate(report)
        self.assertTrue(any("SHA-256" in p for p in problems), problems)

    def test_wrong_parent_pid_rejected(self):
        report = self._report()
        report["parent_pid"] = 999
        problems = self._evaluate(report)
        self.assertTrue(any("parent_pid" in p for p in problems), problems)


class ProcessIdentityTests(unittest.TestCase):
    def test_driver_pid_is_the_kernels_pid_not_a_self_report(self):
        pid, r = harness._run_with_pid(
            [sys.executable, "-c", "import os; print(os.getpid())"],
            timeout=60)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(pid, int(r.stdout.strip()))

    def test_report_claiming_a_different_pid_is_rejected(self):
        """The UDF evaluation must use the pid it was TOLD, not the report's.

        This is the integration shape: a driver that self-reports
        parent_pid must still be compared against the process the
        harness actually started.
        """
        nonce = "a" * 32
        report = {
            "bytes": 10,
            "sha256": "b" * 64,
            "parent_pid": 1111,
            "markers": [{"pid": 2222, "isolated": True,
                         "version": MINOR, "nonce": nonce}],
        }
        problems = harness.evaluate_udf_report(
            report, expect_minor=MINOR, expected_bytes=10,
            expected_sha256="b" * 64, parent_pid=3333, nonce=nonce)
        self.assertTrue(any("parent_pid" in p for p in problems), problems)


class CliBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fr_cli_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args, env=None):
        return subprocess.run(
            [sys.executable, HARNESS] + list(args),
            capture_output=True, text=True, timeout=180, env=env)

    def test_missing_wheel_fails_closed(self):
        r = self._run("--wheel", os.path.join(self.tmp, "absent.whl"),
                      "--interpreter", sys.executable,
                      "--expect-minor", MINOR, "--mode", "generic")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("does not exist", r.stdout)

    def test_malformed_wheel_fails_closed(self):
        path = os.path.join(
            self.tmp, "forkrun-0.17.0-py3-none-manylinux_2_28_x86_64.whl")
        with open(path, "w") as fh:
            fh.write("not a wheel")
        r = self._run("--wheel", path, "--interpreter", sys.executable,
                      "--expect-minor", MINOR, "--mode", "generic")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("not a readable wheel", r.stdout)

    def test_udf_mode_requires_udf_func(self):
        r = self._run("--wheel", os.path.join(self.tmp, "absent.whl"),
                      "--interpreter", sys.executable,
                      "--expect-minor", MINOR, "--mode", "udf")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("--udf-func is required", r.stdout)

    def test_malformed_udf_func_rejected(self):
        r = self._run("--wheel", os.path.join(self.tmp, "absent.whl"),
                      "--interpreter", sys.executable,
                      "--expect-minor", MINOR, "--mode", "udf",
                      "--udf-func", "no-colon")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("MODULE:FUNC", r.stdout)

    def test_unsupported_minor_rejected_before_any_work(self):
        r = self._run("--wheel", os.path.join(self.tmp, "absent.whl"),
                      "--interpreter", sys.executable,
                      "--expect-minor", "3.9", "--mode", "generic")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("not supported", r.stdout)
        self.assertIn("SUPPORTED_MINORS", r.stdout)

    def test_wrong_interpreter_minor_rejected(self):
        wheel = _make_wheel(os.path.join(self.tmp, "w.whl"),
                            mode="generic", minor=OTHER_MINOR,
                            python_tag="py3", abi_tag="none")
        r = self._run("--wheel", wheel, "--interpreter", sys.executable,
                      "--expect-minor", OTHER_MINOR, "--mode", "generic")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("expected %s" % (OTHER_MINOR,), r.stdout)

    def test_unknown_mode_rejected(self):
        r = self._run("--wheel", "x.whl", "--interpreter", sys.executable,
                      "--expect-minor", MINOR, "--mode", "bogus")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("invalid choice", r.stderr)

    def test_hostile_env_is_removed_not_obeyed(self):
        env = dict(os.environ)
        env.update({
            "FORKRUN_LIB": "/tmp/bogus.so",
            "FORKRUN_CLEANROOM": "0",
            "PYTHONPATH": "/tmp/bogus-python",
            "LD_PRELOAD": "/tmp/bogus-preload.so",
            "FR_UDF_HOME": "/tmp/bogus-home",
        })
        r = self._run("--wheel", os.path.join(self.tmp, "absent.whl"),
                      "--interpreter", sys.executable,
                      "--expect-minor", MINOR, "--mode", "generic",
                      env=env)
        self.assertNotEqual(0, r.returncode)
        report = json.loads(r.stdout)
        removed = set(report["env_audit"]["removed"])
        self.assertTrue({"FORKRUN_LIB", "FORKRUN_CLEANROOM",
                         "PYTHONPATH", "LD_PRELOAD", "FR_UDF_HOME"} <= removed,
                        removed)
        self.assertTrue(any("does not exist" in p
                            for p in report["problems"]),
                        report["problems"])


class MatrixAndScriptTests(unittest.TestCase):
    def test_ci_matrix_uses_the_one_supported_minor_list(self):
        matrix = gen_python_matrix.build_matrix()
        self.assertEqual(list(wheel_matrix.SUPPORTED_MINORS),
                         [e["py"] for e in matrix["include"]])
        for entry in matrix["include"]:
            self.assertEqual(wheel_matrix.minor_tag(entry["py"]),
                             entry["tag"])
            self.assertTrue(entry["image"])
            self.assertIn(entry["setup"], ("system", "deadsnakes"))

    def test_ci_env_mapping_has_no_extra_minors(self):
        self.assertEqual(set(wheel_matrix.SUPPORTED_MINORS),
                         set(gen_python_matrix._ENV))

    def test_udf_script_lists_the_one_supported_minor_list(self):
        # LIST_PYTHON: the harness must not depend on a literal
        # `python3` existing. The 3.12 CI cell ships only python3.12,
        # so the script's default lookup failed there.
        env = dict(os.environ, LIST_PYTHON=sys.executable)
        r = subprocess.run(["bash", UDF_SCRIPT, "--list"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(list(wheel_matrix.SUPPORTED_MINORS),
                         r.stdout.split())

    def test_udf_script_rejects_unsupported_minor_early(self):
        env = dict(os.environ, LIST_PYTHON=sys.executable)
        r = subprocess.run(["bash", UDF_SCRIPT, "3.9"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertNotEqual(0, r.returncode)
        self.assertIn("not a supported minor", r.stderr)

    def test_udf_script_is_syntactically_valid_and_has_no_stray_lines(self):
        r = subprocess.run(["bash", "-n", UDF_SCRIPT],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(0, r.returncode, r.stderr)
        with open(UDF_SCRIPT) as fh:
            lines = [line.rstrip("\n") for line in fh]
        self.assertNotEqual("EOF", lines[-1])
        self.assertFalse(any(line.strip() == 'echo "created"' for line in lines))


if __name__ == "__main__":
    unittest.main()
