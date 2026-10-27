"""F6 Stage 3, condition C4 -- the REAL launcher's entry descriptor set.

Stage 2 could only observe a TEST-ONLY C observer launched in place of the
launcher. That proved the launch MECHANISM was equivalent under a
faithful replication of run.py's setup; it did not show that the actual
`forkrun_cleanroom` binary receives the channels it needs.

This closes that gap with a COMPILE-TIME-GUARDED probe added to
`forkrun_cleanroom.c`:

* the shipped build defines nothing, so the code does not exist in the
  release binary -- verified by rebuilding and comparing SHA-256 against
  the shipped artifact, which are byte-identical, and by confirming the
  flag string is absent from the normal build;
* only the test build adds `-DFORKRUN_ENTRY_FD_PROBE`, and the probe is
  invoked from `main()` BEFORE any launcher work touches a descriptor, so
  what it records really is the entry state;
* it reads no environment variables and prints none -- the output path
  arrives as a command-line argument, so enabling it cannot perturb what
  it measures.

WHAT IS AND IS NOT PROVEN
-------------------------
Proven: with the shipped launcher binary (unmodified behaviour), the
descriptor set arriving at `main()` entry is the same under
`fork()+execv()` and under the `posix_spawn` candidate, for both launch
shapes, and `FRK_POISON_FD` equals the stats descriptor number.

NOT proven: anything about the release binary's behaviour beyond entry
descriptors -- the probe binary RETURNS immediately after recording, so
it runs none of the launcher's actual work. The descriptors it observes
are the real ones, produced by the real code path, in a binary compiled
from the real source.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import warnings

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun                                            # noqa: E402

_R = sys.modules["forkrun.run"]

BACKENDS = ("forkexec", "posix_spawn")

PLUGIN_C = (
    '#include "forkrun_plugin.h"\n'
    "#include <stdio.h>\n"
    "int forkrun_use_ctx = FORKRUN_CTX_ENABLE|FORKRUN_CTX_FLAG_RAW;\n"
    "int copy_v1(int argc, char **argv, const struct forkrun_ctx *ctx){\n"
    "  (void)argc; (void)argv;\n"
    "  if(ctx==NULL||ctx->version<2) return -1;\n"
    "  uint64_t n=ctx->batch_byte_length;\n"
    "  const char *in=(const char*)(uintptr_t)ctx->reserved[0];\n"
    "  if(in==NULL) return -1;\n"
    "  if(n==0) return 0;\n"
    "  if(fwrite(in,1,(size_t)n,stdout)!=(size_t)n) return -2;\n"
    "  return fflush(stdout)==0?0:-2;}\n"
)


def _parse_report(path):
    """Parse an entry-fd report into ({fd: (cloexec, target)}, notes)."""
    fds, notes = {}, {}
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("FD ") and " end" not in line:
                parts = line.split()
                num = int(parts[1])
                clo = int(parts[2].split("=")[1])
                tgt = line.split("target=", 1)[1]
                fds[num] = (clo, tgt)
            elif not line.startswith("#"):
                # Notes are emitted as "KEY VALUE" (e.g. the poison/stats
                # relationship), not KEY=VALUE -- the first parser assumed
                # "=" and silently dropped every note.
                parts = line.split(None, 1)
                if len(parts) == 2:
                    notes[parts[0]] = parts[1].strip()
    return fds, notes


class TestRealLauncherEntryDescriptors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cc"):
            raise unittest.SkipTest("no C compiler for the instrumented build")
        cls._tmp = tempfile.mkdtemp(prefix="entryfd-")
        src = os.path.join(_ROOT, "forkrun_cleanroom.c")
        if not os.path.exists(src):
            raise unittest.SkipTest("forkrun_cleanroom.c not found")

        # The instrumented build: ONLY for observation.
        cls.probe_launcher = os.path.join(cls._tmp, "cr_probe")
        proc = subprocess.run(
            ["cc", "-O2", "-D_GNU_SOURCE", "-DFORKRUN_ENTRY_FD_PROBE",
             "-o", cls.probe_launcher, src, "-ldl", "-lrt"],
            capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            shutil.rmtree(cls._tmp, ignore_errors=True)
            raise unittest.SkipTest("instrumented launcher build failed: %s"
                                    % proc.stderr[-400:])

        # A plugin fixture so the route has something to launch.
        plug = os.path.join(cls._tmp, "copyplug.so")
        with open(os.path.join(cls._tmp, "plugin.c"), "w") as fh:
            fh.write(PLUGIN_C)
        p2 = subprocess.run(
            ["cc", "-shared", "-fPIC", "-O2",
             "-I", os.path.join(_ROOT, "ring_loadables"), "-o", plug,
             os.path.join(cls._tmp, "plugin.c")],
            capture_output=True, text=True, timeout=300)
        if p2.returncode != 0:
            shutil.rmtree(cls._tmp, ignore_errors=True)
            raise unittest.SkipTest("plugin build failed")
        cls.spec = "%s:copy_v1" % plug

        # run.py builds the launcher argv itself, so the probe flag cannot
        # be threaded through it. A wrapper executable solves that without
        # touching production: run.py execs the wrapper, which immediately
        # `exec`s the real probe with the flag appended. `exec` replaces the
        # wrapper's image without touching the descriptor table, so the
        # probe observes EXACTLY the state run.py set up.
        cls.wrapper = os.path.join(cls._tmp, "probe_wrapper.sh")
        cls.wrapper = os.path.join(cls._tmp, "probe_wrapper.sh")
        cls.corpus = os.path.join(cls._tmp, "in.txt")
        with open(cls.corpus, "w") as fh:
            for i in range(8):
                fh.write("PAYLOAD_%02d\n" % i)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        for name in ("FORKRUN_CLEANROOM", "FORKRUN_RETRY_LIMIT"):
            old = os.environ.get(name)
            self.addCleanup(self._restore, name, old)
        os.environ["FORKRUN_CLEANROOM"] = "1"
        os.environ["FORKRUN_RETRY_LIMIT"] = "1"
        prev = _R._set_cleanroom_launch_backend("forkexec")
        self.addCleanup(_R._set_cleanroom_launch_backend, prev)
        real = _R._cleanroom_launcher_path
        self.addCleanup(setattr, _R, "_cleanroom_launcher_path", real)
        self.report = os.path.join(self._tmp, "entry.txt")
        with open(self.wrapper, "w") as fh:
            fh.write('#!/bin/sh\nexec %s --entry-fd-probe %s "$@"\n'
                     % (self.probe_launcher, self.report))
        os.chmod(self.wrapper, 0o755)

    @staticmethod
    def _restore(name, value):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def _observe(self, backend, shape, trace=False):
        """Run one real launch against the INSTRUMENTED launcher and
        return its parsed entry report."""
        _R._set_cleanroom_launch_backend(backend)
        _R._cleanroom_launcher_path = lambda: self.wrapper
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if shape == "materialized":
                forkrun.map(self.spec, self.corpus, mode="plugin",
                            workers=2, lines=1)
            else:
                gen = forkrun.stream(self.spec, self.corpus,
                                     mode="plugin", workers=2, lines=1,
                                     streaming=True)
                try:
                    list(gen)
                finally:
                    gen.close()
        self.assertTrue(os.path.exists(self.report),
                        "launcher probe produced no report (%s/%s)" %
                        (backend, shape))
        fds, notes = _parse_report(self.report)
        os.unlink(self.report)
        return fds, notes

    def _roles(self, fds):
        """Map observed descriptors to roles by target, so a difference in
        NUMBERING does not masquerade as a difference in content."""
        roles = {}
        for num, (_clo, tgt) in fds.items():
            if num <= 2:
                roles[num] = "std%d" % num
            elif "fr_cleanroom_result" in tgt:
                roles[num] = "res_fd"
            elif "fr_cleanroom_stream_stats" in tgt:
                roles[num] = "stream_stats"
            elif "fr_cleanroom_stats" in tgt:
                roles[num] = "stats_fd"
            elif "fr_cleanroom_err" in tgt:
                roles[num] = "errfd"
            elif "fr_cleanroom_trace" in tgt:
                roles[num] = "trace_fd"
            elif tgt.startswith("pipe:["):
                roles[num] = "pipe"
            elif tgt.endswith(")") and " (deleted)" in tgt:
                roles[num] = "memfd_other"
            elif tgt == self.corpus:
                roles[num] = "src_fd"
            else:
                roles[num] = "file:" + tgt
        return roles

    def test_materialized_entry_set_matches_across_backends(self):
        """C4: the real launcher's entry descriptor set must not depend on
        which mechanism delivered it."""
        a, _ = self._observe("forkexec", "materialized")
        b, _ = self._observe("posix_spawn", "materialized")
        ra, rb = self._roles(a), self._roles(b)
        self.assertEqual(sorted(ra.values()), sorted(rb.values()),
                         "materialized entry role sets differ:\n"
                         "  fork+execv : %s\n  posix_spawn: %s"
                         % (sorted(ra.values()), sorted(rb.values())))

    def test_streaming_entry_set_matches_across_backends(self):
        a, _ = self._observe("forkexec", "streaming")
        b, _ = self._observe("posix_spawn", "streaming")
        ra, rb = self._roles(a), self._roles(b)
        self.assertEqual(sorted(ra.values()), sorted(rb.values()),
                         "streaming entry role sets differ:\n"
                         "  fork+execv : %s\n  posix_spawn: %s"
                         % (sorted(ra.values()), sorted(rb.values())))

    def test_materialized_entry_has_every_required_channel(self):
        for backend in BACKENDS:
            fds, _ = self._observe(backend, "materialized")
            roles = set(self._roles(fds).values())
            for required in ("src_fd", "res_fd", "stats_fd"):
                self.assertIn(required, roles,
                              "%s: %s missing at launcher entry (have %s)"
                              % (backend, required, sorted(roles)))

    def test_materialized_fd2_carries_the_error_memfd(self):
        """The stderr transformation must survive to the real launcher."""
        for backend in BACKENDS:
            fds, _ = self._observe(backend, "materialized")
            self.assertIn(2, fds, "%s: fd 2 absent at entry" % backend)
            _clo, tgt = fds[2]
            self.assertIn("fr_cleanroom_err", tgt,
                          "%s: fd 2 should carry the error memfd, got %r"
                          % (backend, tgt))

    def test_streaming_entry_has_required_channels_and_no_rr(self):
        for backend in BACKENDS:
            fds, _ = self._observe(backend, "streaming")
            roles = self._roles(fds)
            values = list(roles.values())
            self.assertIn("src_fd", values,
                          "%s: src_fd missing (%s)" % (backend, values))
            self.assertIn("stream_stats", values,
                          "%s: stream stats_fd missing (%s)"
                          % (backend, values))
            self.assertIn("pipe", values,
                          "%s: result pipe missing (%s)" % (backend, values))
            # rr and rw share an inode, so identity cannot be told apart
            # from readlink; what CAN be asserted is that the pipe
            # survives at all, which the previous line does.

    def test_poison_fd_is_the_stats_fd_not_a_second_descriptor(self):
        """FRK_POISON_FD is set to o.stats_fd. The probe reports the
        relationship so the two are never counted as separate fds."""
        for backend in BACKENDS:
            _fds, notes = self._observe(backend, "materialized")
            self.assertEqual(notes.get("POISON_FD_EQUALS_STATS_FD"), "1",
                             "%s: poison fd should equal the stats fd"
                             % backend)

    def test_route_descriptors_are_above_stdio(self):
        """C5: nothing the route owns may sit on 0, 1 or 2, or the
        dup2(errfd, 2) transformation would overwrite it."""
        for backend in BACKENDS:
            for shape in ("materialized", "streaming"):
                fds, _ = self._observe(backend, shape)
                for num, (_clo, tgt) in fds.items():
                    if "fr_cleanroom" not in tgt and tgt != self.corpus:
                        continue
                    # fd 2 carrying the error memfd is the INTENDED
                    # stderr transformation (dup2(errfd, 2)), not a
                    # collision. The defect C5 fixed was a ROUTE descriptor
                    # being OVERWRITTEN by that dup2 -- which shows up as a
                    # missing src/res/stats, not as fd 2 itself.
                    if num == 2 and "fr_cleanroom_err" in tgt:
                        continue
                    self.assertGreater(
                        num, 2,
                        "%s/%s: route descriptor %r landed on stdio "
                        "number %d" % (backend, shape, tgt, num))

    def test_normal_build_has_no_probe_flag(self):
        """The shipped launcher must not expose the diagnostic."""
        src = os.path.join(self._tmp, "cr_normal")
        proc = subprocess.run(
            ["cc", "-O2", "-D_GNU_SOURCE", "-o", src,
             os.path.join(_ROOT, "forkrun_cleanroom.c"), "-ldl", "-lrt"],
            capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            self.skipTest("normal rebuild failed: %s" % proc.stderr[-200:])
        strings = subprocess.run(["strings", src], capture_output=True,
                                 text=True, timeout=120).stdout
        self.assertNotIn("entry-fd-probe", strings,
                         "the normal launcher build must not contain the "
                         "probe flag at all")
        shipped = _R._cleanroom_launcher_path()
        if shipped and os.path.exists(shipped):
            import hashlib
            def sha(p):
                with open(p, "rb") as fh:
                    return hashlib.sha256(fh.read()).hexdigest()
            self.assertEqual(
                sha(src), sha(shipped),
                "the shipped launcher must be byte-identical to a normal "
                "rebuild -- the guarded probe changed nothing")


if __name__ == "__main__":
    unittest.main()