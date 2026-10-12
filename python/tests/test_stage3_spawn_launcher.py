"""Stage 3: spawn's command transport and the mode-specific descriptor.

Two things Stage 3 had to get right, both of which a cast-and-call would
have silently broken:

  SIGNATURE COMPATIBILITY. fr_py_worker_spawn_loop takes
  (wid, char **argv, int argc, ...) while the plugin and UDF loops take
  (wid, const char *, const char *, ...). Same arity, incompatible types
  at positions 2 and 3. The launcher now carries a worker descriptor
  naming the mode and that mode's own arguments, and dispatches through
  each loop's real prototype.

  COMMAND TRANSPORT. Arguments travel as DISTINCT argv elements. No
  shell-word parsing, and no newline-delimited encoding, because a
  newline is a legal character inside a single argument.

NUL is rejected in run.py, at the point user input becomes an argv
element. It cannot be rejected in C: a C string is NUL-terminated by
definition, so an embedded NUL would have been truncated before the
launcher ever saw it. Asserted here as the single place it happens.

The launcher's spawn ENVELOPE is still declined. This module pins the
plumbing, not activation.
"""

import inspect
import os
import re
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import importlib  # noqa: E402
# forkrun.run is the exported FUNCTION; the module needs an explicit
# import or attribute lookup silently hits the function object.
_run = importlib.import_module("forkrun.run")


class TestSpawnArgvValidation(unittest.TestCase):

    def test_nul_is_rejected(self):
        """NUL cannot be represented in a POSIX argument. Silently
        truncating 'echo a\\0b' to 'echo a' would run a DIFFERENT command
        than the caller asked for."""
        with self.assertRaises(ValueError) as ctx:
            _run._validate_spawn_argv(["echo", "a\x00b"])
        self.assertIn("NUL", str(ctx.exception))

    def test_newline_is_legal_inside_one_argument(self):
        """The reason there is no newline-delimited encoding: a newline
        is a perfectly ordinary character in a single argument, so a
        line-based transport would be ambiguous against it."""
        out = _run._validate_spawn_argv(["printf", "a\nb"])
        self.assertEqual(["printf", "a\nb"], out,
                         "a newline inside an element must survive intact")

    def test_arguments_stay_distinct(self):
        argv = ["sh", "-c", "echo one; echo two"]
        self.assertEqual(argv, _run._validate_spawn_argv(argv))
        self.assertEqual(3, len(_run._validate_spawn_argv(argv)),
                         "a multi-word argument must not be split")

    def test_empty_and_wrong_typed_vectors_are_refused(self):
        with self.assertRaises(ValueError):
            _run._validate_spawn_argv([])
        with self.assertRaises(TypeError):
            _run._validate_spawn_argv(["echo", 7])

    def test_validation_runs_before_the_source_is_read(self):
        """A rejected command must cost no input, so validation has to
        precede source resolution in the launcher path."""
        src = inspect.getsource(_run._execute_cleanroom)
        self.assertIn("_validate_spawn_argv(spawn_argv)", src)
        self.assertLess(
            src.index("_validate_spawn_argv(spawn_argv)"),
            src.index("src_fd"),
            "validation must precede opening/reading the source",
        )


class TestLauncherDescriptor(unittest.TestCase):

    def _c(self):
        with open(os.path.join(_ROOT, "forkrun_cleanroom.c")) as fh:
            return fh.read()

    def test_spawn_loop_has_its_own_prototype(self):
        src = self._c()
        self.assertRegex(
            src,
            r"typedef int \(\*fn_worker_spawn_loop\)\(int wid, char \*\*argv, "
            r"int argc,",
            "spawn must be declared with its own prototype, not aliased to "
            "the plugin callback")

    def test_spawn_is_never_cast_to_the_plugin_callback(self):
        """The cast is the defect this mechanism exists to avoid: it
        would pass a char** and an int where two const char* are
        expected.

        Scoped to SPAWN only. Casting the udf loop to the plugin callback
        type is legitimate -- those two really do share a signature --
        so a blanket 'no casts anywhere' assertion would be wrong and
        would invite someone to 'fix' a correct line.
        """
        src = self._c()
        for m in re.finditer(r"\(fn_worker_plugin_loop\)\s*sym\([^)]*\)",
                             src):
            self.assertNotIn(
                "fr_py_worker_spawn_loop", m.group(0),
                "spawn must not be cast to the plugin callback: %s"
                % m.group(0))
        # ...and it must be resolved as its own type.
        self.assertRegex(src, r"\(fn_worker_spawn_loop\)\s*sym\([^)]*"
                             r"fr_py_worker_spawn_loop")

    def test_dispatcher_switches_on_mode(self):
        src = self._c()
        m = re.search(r"static int fr_run_worker\(.*?\n\}\n", src, re.S)
        self.assertIsNotNone(m, "fr_run_worker dispatcher not found")
        body = m.group(0)
        for kind in ("WK_SPAWN", "WK_UDF", "WK_PLUGIN"):
            self.assertIn(kind, body,
                          "the dispatcher must handle %s" % kind)
        # The spawn arm must pass the vector, the others the two strings.
        self.assertIn("d->argv, d->argc", body)
        self.assertIn("d->a, d->b", body)

    def test_descriptor_is_validated_before_any_fork(self):
        src = self._c()
        self.assertLess(
            src.index("fr_validate_worker_desc(&wd)"),
            src.index("/* workers */"),
            "the command vector must be validated before workers are forked")

    def test_workers_lead_their_own_process_group(self):
        """Managed-process-group contract (Option A): the worker becomes
        a group leader so the launcher can signal its descendants."""
        src = self._c()
        self.assertIn("setpgid(0, 0);", src,
                      "workers must become process-group leaders")

    def test_only_worker_slots_are_group_signalled(self):
        """The helpers are NOT group leaders, so signalling -pid for one
        would target whatever unrelated group carries that id."""
        src = self._c()
        m = re.search(r"static void kill_worker_group\(.*?\n\}\n", src, re.S)
        self.assertIsNotNone(m)
        self.assertIn("kill(-(*slot), SIGKILL)", m.group(0))
        self.assertNotIn("kill(-(*slot), SIGKILL)", src.split(
            "static void kill_slot(")[0],
            "group signalling must not leak into the generic kill path")

    def test_spawn_envelope_is_still_declined(self):
        """Stage 3 is plumbing. Activation waits on the lifecycle gates:
        an orphaned-child test on worker death, recovery/respawn,
        fail-fast, and launcher teardown."""
        src = open(os.path.join(_ROOT, "python", "forkrun", "run.py")).read()
        m = re.search(r"def _cleanroom_eligible\(.*?\n(?=def )", src, re.S)
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertIn('if raw_mode not in ("plugin", "udf"):', body,
                      "the spawn envelope must remain declined until its "
                      "lifecycle gates are covered by tests")


if __name__ == "__main__":
    unittest.main()