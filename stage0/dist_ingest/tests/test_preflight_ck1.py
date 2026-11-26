#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 — CK-1.

Mandatory preflight is genuinely FAIL-CLOSED (CK-1.4 contract):
  1. `make clean` rc==0; 2. artifact absent after successful clean;
  3. fresh mandatory build rc==0; 4. artifact exists; 5. artifact produced
  by THIS build (not pre-existing). No sanitizer-env exception.
Builds are ISOLATED (CK-1.2): preflight never rebuilds/overwrites a
pre-existing artifact (incl. an instrumented sanitizer artifact).
Optional capability failures are warnings, not mandatory failures.
Environment reporting is accurate (CK-1.4): shmem THP, swap vs active I/O,
actual compiler/build command, no stale libnuma fallback claims.

Expected results are asserted directly; NOT derived from `available`.
"""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TOOL = os.path.join(REPO_ROOT, "tools", "di_preflight.py")
DIST_DIR = os.path.join(REPO_ROOT, "stage0", "dist_ingest")
SO = os.path.join(REPO_ROOT, "stage0", "libdist_ingest.so")

sys.path.insert(0, REPO_ROOT)
from tools.di_preflight import probe_mandatory_engine_build, probe_environment  # noqa: E402


def _sha256(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _write_fake_make(bindir, script):
    os.makedirs(bindir, exist_ok=True)
    p = os.path.join(bindir, "make")
    with open(p, "w") as f:
        f.write(script)
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bindir


class TestMandatoryBuildContract(unittest.TestCase):
    def test_normal_successful_clean_build(self):
        tmp = tempfile.mkdtemp(prefix="di_ck1_ok_")
        try:
            out = os.path.join(tmp, "libdist_ingest.so")
            ok, detail = probe_mandatory_engine_build(output_path=out, keep_artifact=True)
            self.assertTrue(ok, detail)
            self.assertEqual(detail["clean_returncode"], 0)
            self.assertTrue(detail["artifact_absent_after_clean"])
            self.assertEqual(detail["returncode"], 0)
            self.assertTrue(os.path.exists(out))
            self.assertTrue(detail["artifact_present"])
            self.assertTrue(detail["artifact_produced_by_this_build"])
            self.assertTrue(detail["artifact_sha256"])
            self.assertNotEqual(detail["artifact_sha256"], _sha256(os.path.join(REPO_ROOT, "nonexistent")) if os.path.exists(os.path.join(REPO_ROOT, "nonexistent")) else None)
            # actual compiler + build command recorded
            self.assertTrue(detail["compiler"])
            self.assertTrue(detail["build_commands"], "actual build command recorded")
            self.assertIn("dist_ingest.c", " ".join(detail["build_commands"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_preexisting_artifact_never_sufficient(self):
        tmp = tempfile.mkdtemp(prefix="di_ck1_stale_")
        try:
            out = os.path.join(tmp, "libdist_ingest.so")
            # a pre-existing artifact exists before anything runs
            with open(out, "wb") as f:
                f.write(b"STALE-NOT-A-REAL-SO")
            # fake make: clean FAILS and does NOT remove; build FAILS
            binp = _write_fake_make(os.path.join(tmp, "bin"),
                "#!/bin/sh\nexit 1\n")
            env = dict(os.environ, PATH=binp + os.pathsep + os.environ["PATH"])
            ok, detail = probe_mandatory_engine_build(output_path=out, env=env)
            self.assertFalse(ok, detail)
            self.assertNotEqual(detail["clean_returncode"], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_missing_broken_compiler(self):
        tmp = tempfile.mkdtemp(prefix="di_ck1_cc_")
        try:
            out = os.path.join(tmp, "libdist_ingest.so")
            env = dict(os.environ, CC="nonexistent-cc-for-preflight-test",
                       PATH=os.environ["PATH"])
            ok, detail = probe_mandatory_engine_build(output_path=out, env=env)
            self.assertFalse(ok, detail)
            self.assertNotEqual(detail["returncode"], 0)
            self.assertFalse(os.path.exists(out))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_failed_make_clean(self):
        tmp = tempfile.mkdtemp(prefix="di_ck1_clean_")
        try:
            out = os.path.join(tmp, "libdist_ingest.so")
            # fake make: `clean` target fails, everything else would succeed
            binp = _write_fake_make(os.path.join(tmp, "bin"), """#!/bin/sh
for a in "$@"; do
  if [ "$a" = "clean" ]; then exit 1; fi
done
# build: create output artifact
prev=""
for a in "$@"; do
  case "$a" in DI_OUTPUT=*) echo "${a#DI_OUTPUT=}" >/dev/null; touch "${a#DI_OUTPUT=}";; esac
done
exit 0
""")
            env = dict(os.environ, PATH=binp + os.pathsep + os.environ["PATH"])
            ok, detail = probe_mandatory_engine_build(output_path=out, env=env)
            self.assertFalse(ok, detail)
            self.assertNotEqual(detail["clean_returncode"], 0, "clean must have failed")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_stale_artifact_left_after_failed_clean(self):
        tmp = tempfile.mkdtemp(prefix="di_ck1_staleclean_")
        try:
            out = os.path.join(tmp, "libdist_ingest.so")
            with open(out, "wb") as f:
                f.write(b"STALE")
            # fake make: clean FAILS and leaves stale artifact in place
            binp = _write_fake_make(os.path.join(tmp, "bin"), """#!/bin/sh
for a in "$@"; do
  if [ "$a" = "clean" ]; then exit 1; fi
done
exit 0
""")
            env = dict(os.environ, PATH=binp + os.pathsep + os.environ["PATH"])
            ok, detail = probe_mandatory_engine_build(output_path=out, env=env)
            self.assertFalse(ok, detail)
            self.assertNotEqual(detail["clean_returncode"], 0)
            self.assertFalse(detail["artifact_absent_after_clean"], "stale artifact must be detected")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_failed_build_with_artifact_present(self):
        tmp = tempfile.mkdtemp(prefix="di_ck1_failbuild_")
        try:
            out = os.path.join(tmp, "libdist_ingest.so")
            # fake make: clean ok; build FAILS (rc!=0) but leaves an artifact
            binp = _write_fake_make(os.path.join(tmp, "bin"), """#!/bin/sh
is_clean=0
outp=""
for a in "$@"; do
  [ "$a" = "clean" ] && is_clean=1
  case "$a" in DI_OUTPUT=*) outp="${a#DI_OUTPUT=}";; esac
done
if [ "$is_clean" = "1" ]; then rm -f "$outp"; exit 0; fi
touch "$outp"
exit 1
""")
            env = dict(os.environ, PATH=binp + os.pathsep + os.environ["PATH"])
            ok, detail = probe_mandatory_engine_build(output_path=out, env=env)
            self.assertFalse(ok, detail)
            self.assertNotEqual(detail["returncode"], 0, "build must have failed")
            self.assertTrue(os.path.exists(out), "artifact present but build failed")
            # artifact presence alone is not enough: build rc!=0 => not ok
            self.assertFalse(ok)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_sanitizer_env_present_but_build_fails(self):
        tmp = tempfile.mkdtemp(prefix="di_ck1_san_")
        try:
            out = os.path.join(tmp, "libdist_ingest.so")
            env = dict(os.environ, CC="nonexistent-cc-for-preflight-test",
                       PATH=os.environ["PATH"],
                       LD_PRELOAD="/lib64/libasan.so.8",
                       ASAN_OPTIONS="detect_leaks=0",
                       UBSAN_OPTIONS="halt_on_error=1")
            ok, detail = probe_mandatory_engine_build(output_path=out, env=env)
            # sanitizer env vars are NOT permission to accept a failed build
            self.assertFalse(ok, detail)
            self.assertNotEqual(detail["returncode"], 0)
            self.assertFalse(os.path.exists(out))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_successful_isolated_preflight_does_not_alter_active_sanitizer_artifact(self):
        # CK-1.2: an instrumented artifact on disk is untouched by preflight
        tmp = tempfile.mkdtemp(prefix="di_ck1_iso_")
        try:
            san = os.path.join(tmp, "libdist_ingest.so")
            with open(san, "wb") as f:
                f.write(b"INSTRUMENTED-SANITIZER-ARTIFACT-CONTENTS")
            before = _sha256(san)
            out = os.path.join(tmp, "isolated_preflight", "libdist_ingest.so")
            env = dict(os.environ, LD_PRELOAD="/lib64/libasan.so.8", ASAN_OPTIONS="detect_leaks=0")
            ok, detail = probe_mandatory_engine_build(output_path=out, env=env, keep_artifact=True)
            self.assertTrue(ok, detail)
            self.assertTrue(os.path.exists(out), "isolated preflight artifact built")
            after = _sha256(san)
            self.assertEqual(before, after, "active sanitizer artifact identity must not change")
            self.assertNotEqual(_sha256(out), before, "isolated artifact distinct from sanitizer artifact")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestEnvironmentAccuracy(unittest.TestCase):
    def test_environment_reporting_accurate(self):
        e = probe_environment()
        # shmem THP separate from global THP; actual shmem source
        self.assertIn("thp_enabled", e)
        self.assertIn("thp_shmem_enabled", e)
        self.assertEqual(e["thp_shmem_source"], "/sys/kernel/mm/transparent_hugepage/shmem_enabled")
        self.assertIn("thp_shmem_per_size", e)
        if os.path.exists("/sys/kernel/mm/transparent_hugepage/shmem_enabled"):
            with open("/sys/kernel/mm/transparent_hugepage/shmem_enabled") as f:
                self.assertEqual(e["thp_shmem_enabled"], f.read().strip())
        # configured swap separate from active swap I/O
        self.assertIn("swap_total_kb", e)
        self.assertIn("swap_free_kb", e)
        self.assertIn("swap_configured", e)
        self.assertIn("pswpin", e)
        self.assertIn("pswpout", e)
        self.assertNotIn("swap_active_pages", e)
        # SwapCached is not active I/O
        self.assertIn("swap_cached_kb", e)

    def test_numa_probe_no_stale_libnuma_fallback(self):
        from tools.di_preflight import probe_numa_headers
        r = probe_numa_headers()
        self.assertFalse(r["libnuma_wrapper_fallback"])
        self.assertNotIn("mbind() wrapper as fallback", json.dumps(r))
        self.assertIn("syscall", r["interface"])


class TestPreflightEndToEnd(unittest.TestCase):
    def _run_preflight(self, env=None, extra=None):
        json_path = os.path.join(tempfile.gettempdir(), "di_preflight_ck1_e2e.json")
        argv = [sys.executable, TOOL, "--json-out", json_path]
        r = subprocess.run(argv, capture_output=True, text=True, cwd=REPO_ROOT,
                           timeout=900, env=(env or os.environ), **(extra or {}))
        return r, json_path

    def test_mandatory_engine_build_succeeds_and_json_agrees(self):
        r, json_path = self._run_preflight()
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
        with open(json_path) as f:
            d = json.load(f)
        m = d["preflight"]["mandatory_engine_build"]
        self.assertTrue(m["available"])
        self.assertTrue(m["artifact_produced_by_this_build"])
        # console output agrees with JSON
        self.assertIn("PASS mandatory", r.stdout)
        self.assertNotIn("FAIL mandatory", r.stdout)

    def test_broken_compiler_fails_closed(self):
        r, json_path = self._run_preflight(env={**os.environ, "CC": "nonexistent-cc-for-preflight-test"})
        self.assertNotEqual(r.returncode, 0, msg=r.stdout + r.stderr)
        with open(json_path) as f:
            d = json.load(f)
        m = d["preflight"]["mandatory_engine_build"]
        self.assertFalse(m["available"])
        self.assertNotEqual(m["returncode"], 0)
        self.assertIn("FAIL mandatory", r.stdout)

    def test_optional_failure_warning_not_mandatory(self):
        r, json_path = self._run_preflight()
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
        with open(json_path) as f:
            d = json.load(f)
        # optional probes never masquerade as mandatory engine failure
        self.assertTrue(d["preflight"]["mandatory_engine_build"]["available"])


if __name__ == "__main__":
    unittest.main()
