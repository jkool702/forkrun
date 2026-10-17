"""F6 Stage 2 -- cleanroom descriptor contract, and posix_spawn equivalence.

WHAT THIS TESTS, EXACTLY
-----------------------
`forkrun`'s two cleanroom launch sites, `_execute_cleanroom` (materialized:
map with mode plugin/udf/spawn) and `_execute_cleanroom_stream` (stream
with mode plugin/udf, streaming=True), each build a set of descriptors in
Python and hand them to `forkrun_cleanroom` via `os.fork()` + `os.execv()`.
The question this file answers is narrow and mechanical:

    can `os.posix_spawn()` produce the SAME post-exec descriptor set from
    the SAME parent-side setup, using only documented file actions?

Each arm launches `_fd_observer` (a test-only binary that dumps its own
descriptor set) instead of the real launcher, from a replication of
run.py's descriptor setup. The child's OBSERVED set is then compared.

WHAT THIS DOES NOT TEST, STATED UP FRONT
----------------------------------------
* It does **not** exercise the real launcher binary. The observer stands
  in for it. So this establishes descriptor-set equivalence of the LAUNCH
  MECHANISM under a faithful replication of the setup -- not that the real
  launcher behaves identically, and not that any payload is correct.
* It does **not** establish end-to-end route equivalence: plugin loading,
  UDF helper checks, spawn argv, poison/stats accounting, supervision, and
  result collection are all out of scope here and are covered by the
  existing route tests, unchanged.
* It does **not** test Python 3.10-3.12. The host interpreter is the only
  runtime available; `POSIX_SPAWN_CLOSEFROM` presence is asserted as a
  host capability, never as floor coverage. See
  `dev/supervisor/CLEANROOM_FD_CONTRACT.md`.
* `os.posix_spawn()` has NO `close_fds` parameter (it is a
  `subprocess.Popen` keyword). The tests use only real actions. This file
  asserts that too, so a future edit cannot reintroduce the conflation.

NEGATIVE CONTROLS ARE PART OF THE SUITE
---------------------------------------
`test_equivalence_detects_a_missing_dup2_action` deliberately omits the
`(DUP2, errfd, 2)` action and asserts the comparison FAILS to match. If
that test ever passes, the comparison has gone blind and the positive
results below mean nothing. It is the load-bearing test in this file.

Production code is not imported or modified for its behaviour: run.py's
descriptor setup is REPLICATED here as data, so a production edit cannot
silently make these tests agree with themselves.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "python"))

OBSERVER_SRC = os.path.join(_ROOT, "python", "tests", "_fd_observer.c")

HAVE_GCC = shutil.which("gcc") is not None


# ---------------------------------------------------------------- harness
def _norm_target(t):
    """Collapse targets that cannot be stable ACROSS THE TWO ARMS.

    Only pipe/socket inode numbers are collapsed, because each arm creates
    its own. This is never sufficient on its own -- it over-merges an
    unrelated inherited pipe with the route's own pipe -- so `_roles`
    pairs it with fd-number disambiguation.
    """
    if t.startswith("pipe:["):
        return "pipe:*"
    if t.startswith("socket:["):
        return "socket:*"
    return t


def _capture(build, mode, dup2_err_fn=None, close_fn=None, actions_fn=None):
    """Run ONE arm. Returns (observed_text, snapshot).

    `build` is called EXACTLY ONCE. Calling it separately to inspect
    descriptor numbers orphans an entire descriptor set into the child and
    silently corrupts the comparison -- that bug produced a spurious "sets
    differ" during development of this file.
    """
    f = build()
    dup2_err = dup2_err_fn(f) if dup2_err_fn else None
    close_in_child = close_fn(f) if close_fn else ()

    tmp = tempfile.NamedTemporaryFile(delete=False, mode="w+")
    tmp.close()
    fdout = os.open(tmp.name, os.O_RDWR)
    os.set_inheritable(fdout, True)

    if mode == "fork":
        pid = os.fork()
        if pid == 0:
            try:
                os.dup2(fdout, 1)
                if dup2_err is not None:
                    os.dup2(dup2_err, 2)
                for c in close_in_child:
                    os.close(c)
                os.execv(_OBSERVER, [_OBSERVER])
            except BaseException:
                os._exit(127)
        os.waitpid(pid, 0)
    else:
        fa = [(os.POSIX_SPAWN_DUP2, fdout, 1)]
        if actions_fn:
            fa.extend(actions_fn(f))
        pid = os.posix_spawn(_OBSERVER, [_OBSERVER], os.environ,
                             file_actions=fa)
        os.waitpid(pid, 0)

    os.close(fdout)
    with open(tmp.name) as fh:
        text = fh.read()
    os.unlink(tmp.name)

    # Snapshot each logical descriptor's target NOW, while it is open.
    # Resolving after close silently disables role resolution: every
    # lookup fails and every descriptor degrades to "OTHER:<target>".
    snap = {}
    for name, fd in f.items():
        try:
            snap[name] = (fd, _norm_target(
                os.readlink("/proc/self/fd/%d" % fd)))
        except OSError:
            snap[name] = (fd, "?")
    for v in f.values():
        try:
            os.close(v)
        except OSError:
            pass
    return text, snap


def _parse(text):
    out = {}
    for line in text.splitlines():
        if not line.startswith("FD ") or " end" in line:
            continue
        out[int(line.split()[1])] = line.split("target=", 1)[1]
    return out


def _roles(observed, snap):
    """{fd_number: logical role}.

    Resolution order:
      1. unique target match -- correct for memfds and files;
      2. fd-number match -- REQUIRED for pipes, whose two ends share one
         inode and are indistinguishable by readlink;
      3. otherwise "OTHER:<target>", which is how an unexpected surviving
         descriptor becomes VISIBLE rather than silently dropped.

    Standard streams are resolved BY TARGET, never hard-coded to "stdN":
    a dup2 onto fd 2 makes it carry the error memfd, and a comparison that
    calls it "std2" unconditionally cannot tell a correct fd 2 from a
    wrong one. That blindness is exactly what
    `test_equivalence_detects_a_missing_dup2_action` catches.
    """
    by_target = {}
    for name, (_num, tgt) in snap.items():
        by_target.setdefault(tgt, []).append(name)
    by_target.setdefault("/dev/null", ["std0"])
    by_number = {}
    for name, (num, _tgt) in snap.items():
        by_number.setdefault(num, name)

    out = {}
    for num, tgt in observed.items():
        nt = _norm_target(tgt)
        names = by_target.get(nt, [])
        if len(names) == 1:
            out[num] = names[0]
        elif len(names) > 1:
            out[num] = (by_number.get(num)
                        or ("std%d" % num if num <= 2 else "AMBIG:" + nt))
        elif nt.startswith("/tmp/") and "tmp" in os.path.basename(nt):
            continue                      # this harness's own capture file
        elif num <= 2:
            out[num] = "std%d" % num
        else:
            out[num] = "OTHER:" + nt
    return out


def _compare(build, dup2_err_fn=None, close_fn=None, actions_fn=None):
    ft, ff = _capture(build, "fork", dup2_err_fn, close_fn, None)
    st, sf = _capture(build, "spawn", None, None, actions_fn)
    fr, sr = _roles(_parse(ft), ff), _roles(_parse(st), sf)
    fset, sset = sorted(fr.values()), sorted(sr.values())
    return {
        "fork": fr, "spawn": sr,
        "identical": fset == sset,
        "only_fork": sorted(set(fset) - set(sset)),
        "only_spawn": sorted(set(sset) - set(fset)),
    }


# ------------------------------------------------- run.py descriptor shapes
def build_materialized(with_trace=False, extra_inheritable=0,
                       extra_cloexec=0, fillers=0, stats_inheritable=True):
    """Replication of `_execute_cleanroom` (run.py:1458-1580).

    src_fd/res_fd/stats_fd/errfd are created CLOEXEC (Python's default for
    memfd_create), then src/res/stats are explicitly made inheritable.
    errfd is NEVER made inheritable -- it reaches the launcher only via
    `os.dup2(errfd, 2)`, which is what makes fd 2 the error memfd.
    """
    def build():
        f = {}
        for i in range(fillers):
            fd = os.memfd_create("pre%d" % i)
            os.set_inheritable(fd, False)
            f["pre%d" % i] = fd
        f["src_fd"] = os.open("/etc/hostname", os.O_RDONLY)
        f["res_fd"] = os.memfd_create("fr_cleanroom_result")
        f["stats_fd"] = os.memfd_create("fr_cleanroom_stats")
        f["errfd"] = os.memfd_create("fr_cleanroom_err")
        os.set_inheritable(f["src_fd"], True)          # run.py:1489
        os.set_inheritable(f["res_fd"], True)          # run.py:1490
        if stats_inheritable:
            os.set_inheritable(f["stats_fd"], True)    # run.py:1491
            # else: deliberately left CLOEXEC -- the negative control
        if with_trace:
            f["trace_fd"] = os.memfd_create("fr_cleanroom_trace")
            os.set_inheritable(f["trace_fd"], True)    # run.py:1511
        for i in range(extra_cloexec):
            fd = os.memfd_create("noise_clo%d" % i)
            os.set_inheritable(fd, False)
            f["noise_clo%d" % i] = fd
        for i in range(extra_inheritable):
            fd = os.memfd_create("noise_inh%d" % i)
            os.set_inheritable(fd, True)
            f["noise_inh%d" % i] = fd
        return f
    return build


def build_streaming(extra_inheritable=0):
    """Replication of `_execute_cleanroom_stream` (run.py:2236-2284).

    The result channel is a PIPE (rw is handed over, rr is closed in the
    child), there is NO errfd and NO dup2 -- stderr is inherited as-is.
    """
    def build():
        f = {}
        f["src_fd"] = os.open("/etc/hostname", os.O_RDONLY)
        rr, rw = os.pipe()
        f["rr"], f["rw"] = rr, rw
        os.set_inheritable(f["src_fd"], True)          # run.py:2248
        os.set_inheritable(f["rw"], True)              # run.py:2249
        f["stats_fd"] = os.memfd_create("fr_cleanroom_stream_stats")
        os.set_inheritable(f["stats_fd"], True)        # run.py:2259
        for i in range(extra_inheritable):
            fd = os.memfd_create("noise_inh%d" % i)
            os.set_inheritable(fd, True)
            f["noise_inh%d" % i] = fd
        return f
    return build


# Proposed file_actions, derived from the shapes above.
def mat_actions(f):
    """_execute_cleanroom: the ONLY thing the child does between fork and
    exec is `os.dup2(errfd, 2)`, so the whole spawn equivalent is one
    DUP2 action. errfd itself stays CLOEXEC in both arms."""
    return [(os.POSIX_SPAWN_DUP2, f["errfd"], 2)]


def stream_actions(f):
    """_execute_cleanroom_stream: the child only does `os.close(rr)`, and
    rr is ALREADY CLOEXEC, so the kernel closes it at exec in both arms.
    The spawn equivalent of the shipped behaviour is NO ACTIONS."""
    return []


_OBSERVER = None


class TestCleanroomFdContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _OBSERVER
        if not HAVE_GCC:
            raise unittest.SkipTest("gcc absent; the fd observer cannot "
                                    "be built")
        d = tempfile.mkdtemp(prefix="fdobserver-")
        cls._dir = d
        _OBSERVER = os.path.join(d, "fd_observer")
        with open(OBSERVER_SRC) as fh:
            src = fh.read()
        proc = subprocess.run(
            ["gcc", "-O2", "-Wall", "-o", _OBSERVER, "-x", "c", "-"],
            input=src, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise unittest.SkipTest("observer build failed: %s"
                                    % proc.stderr[-300:])

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "_dir", None):
            shutil.rmtree(cls._dir, ignore_errors=True)

    # ---------------------------------------------------------- the API
    def test_posix_spawn_has_no_close_fds_parameter(self):
        """`close_fds` is a subprocess.Popen keyword, not an
        os.posix_spawn parameter. It appears in this repo's decision
        record once as a real API claim, so it is asserted rather than
        trusted."""
        import inspect
        try:
            params = inspect.signature(os.posix_spawn).parameters
        except (TypeError, ValueError):
            self.skipTest("os.posix_spawn signature unavailable")
        self.assertNotIn("close_fds", params,
                         "os.posix_spawn() has no close_fds parameter; "
                         "that is subprocess.Popen's keyword")
        self.assertNotIn("close_fds", dir(os))

    def test_actions_used_here_exist_on_this_host(self):
        for name in ("POSIX_SPAWN_DUP2", "POSIX_SPAWN_CLOSE"):
            self.assertTrue(hasattr(os, name), "%s missing" % name)

    def test_closefrom_is_not_required_by_the_equivalence_design(self):
        """The 3.10 floor has no POSIX_SPAWN_CLOSEFROM. The designs below
        must therefore not need it -- asserted by checking the proposed
        action lists contain no CLOSEFROM."""
        f = build_materialized()()
        try:
            for act in mat_actions(f):
                self.assertNotEqual(act[0], getattr(
                    os, "POSIX_SPAWN_CLOSEFROM", object()))
            for act in stream_actions(f):
                self.assertNotEqual(act[0], getattr(
                    os, "POSIX_SPAWN_CLOSEFROM", object()))
        finally:
            for v in f.values():
                try:
                    os.close(v)
                except OSError:
                    pass

    # ------------------------------------------------ equivalence (positive)
    def test_materialized_route_descriptor_sets_are_equivalent(self):
        """map(mode=plugin|udf|spawn) launch shape."""
        r = _compare(build_materialized(), dup2_err_fn=lambda f: f["errfd"],
                     actions_fn=mat_actions)
        self.assertTrue(r["identical"],
                        "descriptor sets differ: only-fork=%s only-spawn=%s"
                        % (r["only_fork"], r["only_spawn"]))
        self.assertIn("src_fd", r["fork"].values())
        self.assertIn("res_fd", r["fork"].values())
        self.assertIn("stats_fd", r["fork"].values())
        self.assertEqual(r["fork"].get(2), "errfd",
                         "fd 2 must carry the error memfd (dup2 target)")

    def test_streaming_route_descriptor_sets_are_equivalent(self):
        """stream(mode=plugin|udf, streaming=True) launch shape."""
        r = _compare(build_streaming(), close_fn=lambda f: [f["rr"]],
                     actions_fn=stream_actions)
        self.assertTrue(r["identical"],
                        "descriptor sets differ: only-fork=%s only-spawn=%s"
                        % (r["only_fork"], r["only_spawn"]))
        self.assertIn("rw", r["fork"].values())
        self.assertIn("src_fd", r["fork"].values())
        self.assertIn("stats_fd", r["fork"].values())
        self.assertNotIn("rr", r["fork"].values(),
                         "rr is closed in the child before exec")

    def test_trace_channel_present_when_enabled(self):
        r = _compare(build_materialized(with_trace=True),
                     dup2_err_fn=lambda f: f["errfd"], actions_fn=mat_actions)
        self.assertTrue(r["identical"])
        self.assertIn("trace_fd", r["spawn"].values())

    def test_trace_channel_absent_when_disabled(self):
        r = _compare(build_materialized(with_trace=False),
                     dup2_err_fn=lambda f: f["errfd"], actions_fn=mat_actions)
        self.assertTrue(r["identical"])
        self.assertNotIn("trace_fd", r["spawn"].values())

    def test_unrelated_cloexec_descriptor_is_excluded_in_both_arms(self):
        r = _compare(build_materialized(extra_cloexec=1),
                     dup2_err_fn=lambda f: f["errfd"], actions_fn=mat_actions)
        self.assertTrue(r["identical"])
        self.assertNotIn("noise_clo0", r["fork"].values())
        self.assertNotIn("noise_clo0", r["spawn"].values())

    def test_descriptor_number_layouts_do_not_change_equivalence(self):
        """Gaps below the required descriptors must not matter."""
        for fillers in (0, 1, 5):
            r = _compare(build_materialized(fillers=fillers),
                         dup2_err_fn=lambda f: f["errfd"],
                         actions_fn=mat_actions)
            self.assertTrue(r["identical"],
                            "fillers=%d broke equivalence: %s / %s"
                            % (fillers, r["only_fork"], r["only_spawn"]))

    # -------------------------------------------------- negative controls
    def test_equivalence_detects_a_missing_dup2_action(self):
        """LOAD-BEARING. Omit the (DUP2, errfd, 2) action and the
        comparison must STOP matching, because fd 2 no longer carries the
        error memfd. If this ever passes, every positive result in this
        file is blind and meaningless."""
        r = _compare(build_materialized(), dup2_err_fn=lambda f: f["errfd"],
                     actions_fn=lambda f: [])          # action omitted
        self.assertNotEqual(
            r["fork"].get(2), r["spawn"].get(2),
            "omitting the DUP2 action changed fd 2 but the comparison "
            "called it equal -- the fd-2 check is not working")
        # The `identical` FLAG itself must be exercised too. A mutation
        # hard-coding `_compare` to always report True survived every
        # content assertion in this file, because the positive cases also
        # pass when the flag is meaningless. This is the one place the two
        # mechanisms genuinely differ, so it is where the flag is provable.
        self.assertFalse(
            r["identical"],
            "the comparison must report a MISMATCH when the two mechanisms "
            "produce different descriptor sets")

    def test_equivalence_detects_a_non_inheritable_stats_fd(self):
        """A required descriptor that is not inheritable must be
        MISSING, not merely renumbered.

        Note the two mechanisms still AGREE here -- both lose stats_fd.
        The error is in the SETUP, not in the launch mechanism, so
        `identical` correctly stays True. The flag itself is exercised by
        the missing-DUP2 control, which is a genuine mechanism
        difference."""
        r = _compare(build_materialized(stats_inheritable=False),
                     dup2_err_fn=lambda f: f["errfd"], actions_fn=mat_actions)
        self.assertNotIn("stats_fd", r["spawn"].values(),
                         "stats_fd was never made inheritable, so it must "
                         "not reach the child")


    def test_equivalence_is_not_isolation(self):
        """An unrelated INHERITABLE descriptor survives into the child in
        BOTH arms. Equivalence with the shipped behaviour therefore does
        NOT deliver an allowlist -- that is a separate, tightening change
        and must not be described as an equivalence-preserving
        optimisation."""
        r = _compare(build_materialized(extra_inheritable=1),
                     dup2_err_fn=lambda f: f["errfd"], actions_fn=mat_actions)
        self.assertIn("noise_inh0", r["fork"].values(),
                      "premise: the shipped path leaks it")
        self.assertIn("noise_inh0", r["spawn"].values(),
                      "an equivalence-only action set must leak it too")

    def test_explicit_close_action_removes_the_unrelated_descriptor(self):
        """The tightening IS expressible with a documented action -- so
        the isolation question is answerable, it is just not the same
        question as equivalence."""
        b = build_materialized(extra_inheritable=1)
        text, snap = _capture(
            b, "spawn",
            actions_fn=lambda f: (mat_actions(f)
                                  + [(os.POSIX_SPAWN_CLOSE,
                                      f["noise_inh0"])]))
        roles = _roles(_parse(text), snap)
        self.assertNotIn("noise_inh0", roles.values())

    def test_repeated_runs_do_not_leak_or_reuse_descriptors(self):
        """Exercise cleanup and descriptor-number reuse across arms."""
        seen = []
        for _ in range(5):
            r = _compare(build_materialized(),
                         dup2_err_fn=lambda f: f["errfd"],
                         actions_fn=mat_actions)
            self.assertTrue(r["identical"])
            seen.append(sorted(r["spawn"].values()))
        self.assertEqual(len(set(map(tuple, seen))), 1,
                         "role sets varied across repeated runs")


if __name__ == "__main__":
    unittest.main()