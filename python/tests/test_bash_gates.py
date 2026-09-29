"""W-REL6-6.2: loader-addressable gates for bash-side doc claims.

The doc-accuracy harness resolves covering tests via the unittest
loader, so bash-suite cases (101 security tests) cannot serve
directly. These thin subprocess probes pin the exact behaviors the
new registry rows claim (fast parse-level paths, x5 loops):

- resume provenance gate fires bare AND with extra args
  (SECURITY.md "extra arguments never skip").
- -I separate-argv form substitutes {ID} (README "unique output
  names"); the single-string form is not offered (docs-only).
"""

import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FRUN = os.path.join(REPO_ROOT, "frun.bash")


def _bash(script, timeout=60):
    proc = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        timeout=timeout, cwd=REPO_ROOT)
    return proc.returncode, proc.stdout, proc.stderr


class TestResumeGateBothForms(unittest.TestCase):
    """SECURITY.md: gate fires bare and with an explicit command."""

    def test_reject_bare_and_with_args(self):
        for _ in range(5):
            with tempfile.TemporaryDirectory() as tmp:
                ckpt = os.path.join(tmp, "ck")
                inn = os.path.join(tmp, "in.txt")
                with open(ckpt, "w") as fh:
                    fh.write("FORKRUN_RESUME_HORIZON=1\n"
                             "FORKRUN_RESUME_STDOUT_BYTES=6\n")
                os.chmod(ckpt, 0o666)
                with open(inn, "w") as fh:
                    fh.write("a\nb\nc\n")
                rc, _, err = _bash(
                    "source '%s'; frun --resume '%s' < '%s' >/dev/null"
                    % (FRUN, ckpt, inn))
                self.assertEqual(rc, 1)
                self.assertIn("SECURITY", err)
                rc, _, err = _bash(
                    "source '%s'; printf 'a\\nb\\nc\\n' | frun --resume "
                    "'%s' -j2 -l2 printf '%%s\\n' >/dev/null"
                    % (FRUN, ckpt))
                self.assertEqual(rc, 1)
                self.assertIn("SECURITY", err)


class TestInsertIdSeparateArgv(unittest.TestCase):
    """README: the separate-argv -I form substitutes {ID}."""

    def test_separate_argv_substitutes(self):
        for _ in range(5):
            with tempfile.TemporaryDirectory() as tmp:
                inn = os.path.join(tmp, "in.txt")
                with open(inn, "w") as fh:
                    fh.write("x\n")
                rc, out, _ = _bash(
                    "source '%s'; printf 'x\\n' | frun -k -l1 -I echo "
                    "'pre-{ID}-post' < '%s'" % (FRUN, inn))
                self.assertEqual(rc, 0)
                self.assertRegex(out.strip(),
                                 r"pre-\{?[0-9.]+\}?-post")


if __name__ == "__main__":
    unittest.main()
