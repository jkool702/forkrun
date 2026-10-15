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

WO-ROI-1 CORRECTED THIS. The claim above ("the launcher's spawn
ENVELOPE is still declined... not activation") was STALE. Verified at
`0f942b42`: with FORKRUN_CLEANROOM=1, map(mode="spawn") DOES enter the
launcher route -- a parent-side spy on `_execute_cleanroom` records the
call -- and returns correct output. Spawn is activated.

The stale claim was not harmless: it was the reason one might have
believed enabling the global gate was safe, since two of its three
envelopes appeared to be dormant. See
dev/supervisor/CLEANROOM_DEFAULT_ON_DECISION.md.
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
        self.assertIn("kill(-pid, SIGKILL)", m.group(0))

    def test_group_kill_cannot_be_disabled_by_a_cleared_slot(self):
        """Regression for the bug that made the group signal a no-op.

        The supervisor reaps a worker and sets pids[wid] = -1 BEFORE
        calling kill_worker_group on it. With the helper taking the slot
        POINTER, its own "positive pid only" guard then refused to act
        and the group signal silently did nothing -- so a command's child
        survived a worker death the supervisor had already observed.
        Passing the pid BY VALUE makes that ordering impossible."""
        src = self._c()
        self.assertNotRegex(
            src, r"kill_worker_group\(&pids\[",
            "group signalling must not read a slot that can already be "
            "cleared -- that ordering made it a silent no-op")

    def test_public_dispatch_actually_routes_spawn(self):
        """The predicate admitting spawn is NOT sufficient.

        The review found the real gap: map() and stream() both gated on
        `raw_mode in ("plugin", "udf")`, so spawn fell through to the
        in-process executor even though the predicate said otherwise --
        and with FORKRUN_CLEANROOM=1 the decline warning then read an
        unassigned _why. The predicate, the matrix and the reachable
        public API were describing three different sets.

        Asserted against the DISPATCH source, not the predicate.
        """
        src = open(os.path.join(_ROOT, "python", "forkrun", "run.py")).read()
        # Scoped deliberately: map() must route spawn, stream() must NOT
        # (it has no spawn dispatch and declines in the predicate). Both
        # gates read identically, so asserting "no gate is plugin/udf
        # only" would have demanded the WRONG thing for stream.
        self.assertIn('if _cleanroom_enabled() and raw_mode in '
                      '("plugin", "udf", "spawn"):', src,
                      "map()'s cleanroom gate does not admit spawn")
        # ...and the spawn route really carries argv into the launcher.
        # Bounded substring checks rather than a regex: a DOTALL .*? over
        # a 9000-line module matches across unrelated code and passes (or
        # fails) for reasons unrelated to the dispatch.
        self.assertIn('if raw_mode == "spawn":', src,
                      "no spawn branch in the dispatch")
        self.assertIn("spawn_argv=_sargv", src,
                      "the spawn branch does not pass the argv vector")
        self.assertIn("_validate_spawn_argv(_sargv)", src,
                      "the argv is not validated before the launcher")

    def test_stream_declines_spawn_explicitly(self):
        """stream() has no spawn dispatch, so the predicate must decline
        it rather than admit a route that does not exist."""
        src = open(os.path.join(_ROOT, "python", "forkrun", "run.py")).read()
        self.assertRegex(
            src,
            r"if raw_mode == \"spawn\":\s*\n\s*return False,",
            "stream must decline spawn explicitly")

    def test_decline_reason_is_initialised_before_use(self):
        """The warning branch interpolates _why, and it can be reached
        when the branch that ASSIGNS _why was never taken. An
        UnboundLocalError there is a crash, not a clean decline."""
        src = open(os.path.join(_ROOT, "python", "forkrun", "run.py")).read()
        assign = src.index('_why = "mode=')
        first_gate = src.index("if _cleanroom_enabled() and raw_mode in")
        self.assertLess(assign, first_gate,
                        "_why must be initialised before the gate that "
                        "may assign it")
        self.assertIn("% (_why,)", src, "the warning should report _why")

    def test_spawn_envelope_is_served_with_its_gates_named(self):
        """Activation is gated on the lifecycle tests, so the gate and its
        evidence are asserted together. A future removal of the envelope
        should have to delete this too, and the comment above the gate
        names what it depends on."""
        src = open(os.path.join(_ROOT, "python", "forkrun", "run.py")).read()
        m = re.search(r"def _cleanroom_eligible\(.*?\n(?=def )", src, re.S)
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertIn('"plugin", "udf", "spawn"', body,
                      "the spawn envelope should be served")
        self.assertIn("test_stage3_lifecycle.py", body,
                      "the gate must name the test that covers it")


if __name__ == "__main__":
    unittest.main()