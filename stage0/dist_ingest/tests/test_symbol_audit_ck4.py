#!/usr/bin/env python3
"""WO-NUMA-PRE-RENTAL-READINESS-HARDENING-1-FINAL-CORRECTIONS-2 — CK-4.

Enforceable process-creation/syscall audit (tools/di_symbol_audit.py).
Fails closed on unavailable evidence; rejects prohibited constructs;
unknown/ambiguous direct syscalls reported; pthread_create not confused
with process creation; not merely a textual grep.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TOOL = os.path.join(REPO_ROOT, "tools", "di_symbol_audit.py")


def load_mod():
    spec = importlib.util.spec_from_file_location("di_symbol_audit", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def make_src(tmp, name, content, also_header=True):
    root = os.path.join(tmp, "dist_ingest")
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, name), "w") as f:
        f.write(content)
    # satisfy required-source check
    with open(os.path.join(root, "dist_ingest.c"), "w") as f:
        if name != "dist_ingest.c":
            f.write("int x;\n")
        else:
            f.write(content)
    with open(os.path.join(root, "dist_ingest.h"), "w") as f:
        f.write("/* header */\n")
    return root


CLEAN = "int di_run(void){ pthread_create(0,0,0,0); pthread_join(0,0); syscall(SYS_mbind,0,0,0,0,0,0); return 0; }\n"


class TestCleanAudit(unittest.TestCase):
    def test_clean_source_audit(self):
        m = load_mod()
        tmp = tempfile.mkdtemp()
        root = make_src(tmp, "dist_ingest.c", CLEAN)
        m.SRC_ROOT = root
        r = m.source_audit()
        self.assertEqual(r["hits"], [], r["hits"])
        self.assertEqual(r["errors"], [])
        # pthread_create is NOT process creation
        self.assertNotIn("pthread_create", json.dumps(r["hits"]))

    def test_clean_real_engine_and_built_so(self):
        r = subprocess.run([sys.executable, TOOL], capture_output=True, text=True, cwd=REPO_ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = json.loads(r.stdout)
        self.assertTrue(d["ok"])
        self.assertTrue(d["threads_only_symbols_ok"])
        self.assertTrue(d["symbol_audit"]["available"])


class TestSyntheticViolations(unittest.TestCase):
    def _scan(self, content):
        m = load_mod()
        tmp = tempfile.mkdtemp()
        root = make_src(tmp, "dist_ingest.c", content)
        m.SRC_ROOT = root
        return m.source_audit()["hits"]

    def test_fork_violation(self):
        hits = self._scan("int f(void){ fork(); return 0; }\n")
        self.assertTrue(any(h["symbol"] == "fork" for h in hits), hits)

    def test_vfork_violation(self):
        hits = self._scan("int f(void){ vfork(); return 0; }\n")
        self.assertTrue(any(h["symbol"] == "vfork" for h in hits), hits)

    def test_exec_violations(self):
        for call in ("execve(\"x\",0,0)", "execvp(\"x\",0)", "execl(\"x\",\"x\",0)", "execlp(\"x\",\"x\",0)"):
            hits = self._scan("int f(void){ %s; return 0; }\n" % call)
            self.assertTrue(any("exec" in h["symbol"] for h in hits), (call, hits))

    def test_pthread_atfork_violation(self):
        hits = self._scan("int f(void){ pthread_atfork(0,0,0); return 0; }\n")
        self.assertTrue(any(h["symbol"] == "pthread_atfork" for h in hits), hits)

    def test_system_popen_violation(self):
        hits = self._scan("int f(void){ system(\"ls\"); popen(\"ls\",\"r\"); return 0; }\n")
        syms = {h["symbol"] for h in hits}
        self.assertIn("system", syms); self.assertIn("popen", syms)

    def test_posix_spawn_violation(self):
        hits = self._scan("int f(void){ posix_spawn(0,\"x\",0,0,0,0); return 0; }\n")
        self.assertTrue(any("posix_spawn" in h["symbol"] for h in hits), hits)

    def test_synthetic_syscall_clone_violation(self):
        hits = self._scan("int f(void){ syscall(SYS_clone, 0,0,0,0,0); return 0; }\n")
        self.assertTrue(any(h["symbol"] == "direct-syscall" for h in hits), hits)

    def test_synthetic_syscall_clone3_violation(self):
        hits = self._scan("int f(void){ syscall(SYS_clone3, 0,0); return 0; }\n")
        self.assertTrue(any(h["symbol"] == "direct-syscall" for h in hits), hits)

    def test_synthetic_syscall_nr_clone3_violation(self):
        hits = self._scan("int f(void){ syscall(__NR_clone3, 0,0); return 0; }\n")
        self.assertTrue(any(h["symbol"] == "direct-syscall" for h in hits), hits)

    def test_multiline_syscall_violation(self):
        hits = self._scan("int f(void){\n  syscall(\n    SYS_clone,\n    0,0,0,0);\n  return 0;}\n")
        self.assertTrue(any(h["symbol"] == "direct-syscall" for h in hits), hits)

    def test_syscall_alias_macro_violation(self):
        hits = self._scan("#define MYCLONE SYS_clone\nint f(void){ syscall(MYCLONE,0,0); return 0; }\n")
        self.assertTrue(any(h["symbol"] == "direct-syscall" for h in hits), hits)

    def test_unknown_direct_syscall_arg(self):
        hits = self._scan("int f(void){ syscall(SOME_UNKNOWN_SYSCALL, 0); return 0; }\n")
        self.assertTrue(any(h["symbol"] == "direct-syscall" for h in hits), hits)

    def test_numeric_syscall_number_rejected(self):
        hits = self._scan("int f(void){ syscall(56, 0,0,0,0,0); return 0; }\n")  # 56=clone on x86-64
        self.assertTrue(any(h["symbol"] == "direct-syscall" for h in hits), hits)

    def test_expression_syscall_arg_rejected(self):
        hits = self._scan("int f(void){ syscall(SYS_mbind + 1, 0); return 0; }\n")
        self.assertTrue(any(h["symbol"] == "direct-syscall" for h in hits), hits)

    def test_allowed_syscalls_pass(self):
        hits = self._scan("int f(void){ syscall(SYS_mbind,0,0,0,0,0,0); syscall(__NR_move_pages,0,0,0,0,0,0); return 0; }\n")
        self.assertEqual([h for h in hits if h["symbol"] == "direct-syscall"], [], hits)

    def test_comment_and_string_mentions_not_counted(self):
        hits = self._scan('/* fork() exec system */ int f(void){ const char*s="fork"; return 0; }\n// popen\n')
        self.assertEqual(hits, [], hits)

    def test_inline_syscall_asm_violation(self):
        hits = self._scan('int f(void){ __asm__ volatile("syscall" : : : "rcx","r11","memory"); return 0; }\n')
        self.assertTrue(any(h["symbol"] == "inline-asm-syscall" for h in hits), hits)


class TestSymbolAuditFailClosed(unittest.TestCase):
    def test_missing_shared_object(self):
        m = load_mod()
        m.SO = "/nonexistent/libdist_ingest.so"
        r = m.undefined_symbol_audit()
        self.assertFalse(r["available"])
        self.assertIn("not built", r["reason"])

    def test_missing_nm(self):
        m = load_mod()
        tmp = tempfile.mkdtemp()
        so = os.path.join(tmp, "x.so")
        open(so, "wb").write(b"not really a so")
        m.SO = so
        orig = shutil.which
        shutil.which = lambda *a, **k: None
        try:
            r = m.undefined_symbol_audit()
            self.assertFalse(r["available"])
            self.assertEqual(r["reason"], "nm unavailable")
        finally:
            shutil.which = orig

    def test_failing_nm(self):
        m = load_mod()
        tmp = tempfile.mkdtemp()
        so = os.path.join(tmp, "x.so"); open(so, "wb").write(b"x")
        m.SO = so
        bindir = os.path.join(tmp, "bin"); os.makedirs(bindir)
        fake = os.path.join(bindir, "nm")
        open(fake, "w").write("#!/bin/sh\nexit 1\n")
        os.chmod(fake, 0o755)
        orig = shutil.which
        shutil.which = lambda name, *a, **k: fake if name == "nm" else orig(name, *a, **k)
        try:
            r = m.undefined_symbol_audit()
            self.assertFalse(r["available"])
            self.assertIn("nm returned", r["reason"])
        finally:
            shutil.which = orig

    def test_forbidden_undefined_symbol(self):
        m = load_mod()
        tmp = tempfile.mkdtemp()
        so = os.path.join(tmp, "x.so"); open(so, "wb").write(b"x")
        m.SO = so
        bindir = os.path.join(tmp, "bin"); os.makedirs(bindir)
        fake = os.path.join(bindir, "nm")
        open(fake, "w").write("#!/bin/sh\nprintf '         U fork\\n         U pthread_create\\n         U clone3\\n'\nexit 0\n")
        os.chmod(fake, 0o755)
        orig = shutil.which
        shutil.which = lambda name, *a, **k: fake if name == "nm" else orig(name, *a, **k)
        try:
            r = m.undefined_symbol_audit()
            self.assertTrue(r["available"])
            self.assertIn("fork", r["process_creation_symbols_found"])
            self.assertIn("clone3", r["process_creation_symbols_found"])
            # pthread_create allowed
            self.assertNotIn("pthread_create", r["process_creation_symbols_found"])
            # clone3 NOT automatically allowed just because pthread uses it internally
        finally:
            shutil.which = orig

    def test_required_source_missing(self):
        m = load_mod()
        tmp = tempfile.mkdtemp()
        m.SRC_ROOT = tmp  # empty
        r = m.source_audit()
        self.assertTrue(r["errors"], "missing required source must be an error")


class TestMainExitBehavior(unittest.TestCase):
    def test_main_returns_nonzero_on_finding(self):
        m = load_mod()
        tmp = tempfile.mkdtemp()
        root = make_src(tmp, "dist_ingest.c", "int f(void){ fork(); return 0; }\n")
        m.SRC_ROOT = root
        m.SO = os.path.join(REPO_ROOT, "stage0", "libdist_ingest.so")
        rc = m.main()
        self.assertNotEqual(rc, 0)

    def test_main_returns_nonzero_on_unavailable_symbol_scan(self):
        m = load_mod()
        m.SO = "/nonexistent.so"
        rc = m.main()
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
