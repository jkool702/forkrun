"""W-EXP-1 5.5: the caller/helper CPython-minor barrier.

The requirement: "A caller/helper CPython-minor mismatch is refused
safely before input consumption, with the refusal observable. A helper
built for 3.12 must not be driven by a 3.14 caller."

Two things make these tests non-vacuous, and both were specified after the
obvious versions were found wanting:

1. The mismatch helper must be LOADABLE. If it merely failed to
   dlopen -- because the other minor's libpython is absent -- then
   deleting the version comparison would still refuse, and the test would
   pass while proving nothing. So the negative control builds a helper
   against THIS runtime with a deliberately wrong declared version, and
   calls the launcher DIRECTLY, bypassing every Python-side hint.

2. The non-consumption test supplies the source as an ALREADY-OPEN
   descriptor and checks its offset. Opening a named FIFO for reading
   blocks until a writer arrives, so a FIFO-path test would hang before
   the preflight even ran.

Also asserted: that the helper WAS loaded (the probe dlopens it to read
its version -- "never loaded" would be the wrong claim), that
fr_udf_init and worker execution did not happen, and that a mismatch
degrades to a COMPLETE in-process result rather than a truncated one.
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest

# This file lives at <repo>/python/tests/, so the repo root is THREE
# levels up. Two levels lands on <repo>/python and every artifact path
# silently resolves to nothing -- which showed up as the entire class
# being skipped by its own "helper not built" guard, which read as a
# missing build rather than a wrong root.
_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun  # noqa: E402
from forkrun._bindings import v1_available  # noqa: E402
from forkrun.run import (_CR_EXIT_LABELS, _CR_EXIT_NO_FALLBACK,  # noqa: E402
                          _CR_EXIT_PRE_INGEST)
from forkrun import _udf  # noqa: E402

_LAUNCHER = os.path.join(_ROOT, "python", "forkrun", "_forkrun_cleanroom")
_SUBSTRATE = os.path.join(_ROOT, "python", "forkrun", "libforkrun_python.so")
_HELPER = _udf.helper_path()

# mode="udf" hands the callable BYTES (fr_udf_call does
# PyBytes_FromStringAndSize), not a Batch -- so the fixture is bytes-shaped.
_UDF = "def up(b):\n    return b.upper()\n"


def _caller_version():
    return "%d.%d" % (sys.version_info[0], sys.version_info[1])


# A helper whose fr_udf_init() LEAVES A MARKER. The previous
# no-interpreter-initialised test grepped stderr for "fr_py_init" -- a
# different function than the one its name claimed, and one that succeeds
# SILENTLY. Initialising an interpreter before refusing would not have
# changed any string in the output, so the test could not fail.
_MARKER_C = """\
#include <stdio.h>
#include <stdlib.h>
struct fr_udf_version { int major; int minor; };
/* major/minor come from the BUILD, not hard-coded. The fixture used to
 * report 3.14, so on any interpreter whose major.minor differs this is
 * not a matching-version control -- the helper is refused before init
 * and the negative control fails for an unrelated reason. */
void fr_udf_built_version_v2(struct fr_udf_version *out)
{
    if (out) { out->major = FR_TEST_MAJOR; out->minor = FR_TEST_MINOR; }
}
/* Returns 1 so the accepted path REACHES fr_udf_init. Returning 0 makes
 * the launcher refuse earlier ("no fork hooks"), so the marker would
 * never be written for a reason that has nothing to do with what this
 * fixture exists to observe -- and the negative control would fail while
 * the property under test was untested. */
int fr_udf_fork_hooks_available(void) { return 1; }
/* MUST return int. The launcher resolves this as
 * int (*)(const char *const *, int) and checks the result; a void-return
 * fixture is an incompatible function type and undefined behaviour. */
int fr_udf_init(const char *const *roots, int nroots)
{
    (void)roots; (void)nroots;
    const char *m = getenv("FR_TEST_INIT_MARKER");
    if (m) { FILE *f = fopen(m, "w"); if (f) { fputs("INITIALISED", f); fclose(f); } }
    return 0;
}
int fr_udf_call(const char *a, int b) { (void)a; (void)b; return 0; }
void fr_udf_free(void) {}
int fr_udf_before_fork(void) { return 0; }
int fr_udf_after_fork_parent(void) { return 0; }
int fr_udf_after_fork_child(void) { return 0; }
"""


def _build_marker_helper(directory):
    src = os.path.join(directory, "marker.c")
    so = os.path.join(directory, "libmarker.so")
    with open(src, "w") as fh:
        fh.write(_MARKER_C)
    subprocess.run(
        ["gcc", "-shared", "-fPIC", "-o", so, src,
         "-DFR_TEST_MAJOR=%d" % sys.version_info[0],
         "-DFR_TEST_MINOR=%d" % sys.version_info[1]],
        check=True, capture_output=True, timeout=180)
    return so


# A constructor that CRASHES rather than hangs. Distinct from the hanging
# fixture and from the distinction it exists to pin: a crash used to
# report itself as "TIMED OUT", which made exit 81 meaningless.
_CRASH_C = """\
#include <unistd.h>
void fr_udf_built_version_v2(void *out) { (void)out; }
__attribute__((constructor))
static void die_now(void) { _exit(7); }
"""


def _build_crashing_helper(directory):
    src = os.path.join(directory, "crash.c")
    so = os.path.join(directory, "libcrash.so")
    with open(src, "w") as fh:
        fh.write(_CRASH_C)
    subprocess.run(["gcc", "-shared", "-fPIC", "-o", so, src],
                   check=True, capture_output=True, timeout=180)
    return so


_HANG_C = """\
/* Test-only helper whose ELF constructor blocks forever.
 *
 * It does NOT embed CPython. The property under test is that the launcher
 * can bound a dlopen() that never returns -- embedding CPython would only
 * make the fixture slower to build.
 */
#include <unistd.h>
__attribute__((constructor))
static void hang_forever(void) { for (;;) sleep(3600); }
unsigned long fr_udf_built_version(void) { return 0x030E0000UL; }
"""


def _build_hanging_helper(directory):
    src = os.path.join(directory, "hang.c")
    so = os.path.join(directory, "libhang.so")
    with open(src, "w") as fh:
        fh.write(_HANG_C)
    subprocess.run(["gcc", "-shared", "-fPIC", "-o", so, src],
                   check=True, capture_output=True, timeout=180)
    return so


def _run_launcher_with_hanging_helper(directory):
    so = _build_hanging_helper(directory)
    proc = subprocess.run(
        [_LAUNCHER, "--so", _SUBSTRATE,
         "--workers", "1", "--lines", "1", "--bytes", "0",
         "--on-error", "0", "--retry", "1",
         "--src", os.path.join(directory, "in.txt"), "--result",
         os.path.join(directory, "hh.bin"), "--stats-fd", "-1",
         "--udf-helper", so, "--udf", "bm", "--udf-attr", "up",
         "--caller-version", _caller_version()],
        capture_output=True, timeout=30)
    return proc.returncode


@unittest.skipUnless(_HELPER and os.path.exists(_LAUNCHER),
                     "cleanroom UDF helper not built")
class MinorMismatchBarrier(unittest.TestCase):
    def setUp(self):
        _udf.clear_incompatibles()
        self.tmp = tempfile.mkdtemp(prefix="minorbarrier-")
        with open(os.path.join(self.tmp, "bm.py"), "w") as fh:
            fh.write(_UDF)
        self.src = os.path.join(self.tmp, "in.txt")
        with open(self.src, "wb") as fh:
            fh.write(b"".join(b"line%d\n" % i for i in range(8)))
        self.addCleanup(_udf.clear_incompatibles)

    # ------------------------------------------------------------------
    # route-level, launcher invoked DIRECTLY
    # ------------------------------------------------------------------
    def _launch(self, extra, src_fd=None):
        """Run the launcher directly.

        ``src_fd`` must be passed via ``pass_fds``. POSIX closes fds
        across exec by default, so without it the launcher inherits
        NOTHING and the test measures a resource that was never
        connected to the production route -- the exact evidence-chain
        failure that makes a correct-looking assertion meaningless.
        """
        owned = src_fd is None
        if owned:
            src_fd = os.open(self.src, os.O_RDONLY)
        out_fd = os.open(os.path.join(self.tmp, "out.bin"),
                         os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            argv = [_LAUNCHER, "--so", _SUBSTRATE,
                    "--workers", "1", "--lines", "1", "--bytes", "0",
                    "--on-error", "0", "--retry", "3",
                    "--src", str(src_fd), "--result", str(out_fd),
                    "--stats-fd", "-1",
                    "--udf-helper", _HELPER, "--udf", "bm",
                    "--udf-attr", "up", "--udf-roots", self.tmp] + extra
            proc = subprocess.run(argv, capture_output=True, timeout=30,
                                  pass_fds=(src_fd, out_fd))
        finally:
            os.close(out_fd)
            if owned:
                os.close(src_fd)
        return proc

    def test_mismatched_declaration_is_refused_with_code_80(self):
        """The negative control, bypassing every Python-side hint.

        Declared 9.9 against a helper built for the real runtime. It
        loads fine -- so the refusal can only be the COMPARISON.
        """
        proc = self._launch(["--caller-version", "9.9"])
        self.assertEqual(proc.returncode, 80,
                         "expected the version barrier to refuse; stderr=%r"
                         % proc.stderr[-400:])
        self.assertIn(b"3.14" if b"3.14" in proc.stderr else b"built against",
                      proc.stderr)
        self.assertIn(b"mismatch", proc.stderr.lower())

    def test_matching_declaration_is_not_refused(self):
        """The positive control: the barrier must not refuse correct calls.

        Scoped to the refusal, deliberately. Driving the launcher by hand
        and asserting on produced records is covered by test_cleanroom.py
        (76 tests, all green); what this file owns is the BARRIER, and the
        property worth pinning here is "a matching declaration is not
        rejected" -- which is what would regress if the comparison were
        mistyped.
        """
        proc = self._launch(["--caller-version", _caller_version()])
        self.assertEqual(
            proc.returncode, 0,
            "a matching helper must be SERVED. Asserting only '!= 80' "
            "would pass on an unrelated 69 or 71, which is not a positive "
            "control at all; stderr=%r" % proc.stderr[-400:])

    def test_missing_or_malformed_declaration_is_refused_as_82(self):
        """Fail closed, and with the CORRECT code.

        82, not 80: an invalid declaration is a CALLER bug, not a property
        of the helper. Sharing 80 meant an internal programming error would
        enter the negative cache and permanently blacklist a perfectly
        good artifact. The launcher also rejects it BEFORE the probe, so
        no ELF constructor runs -- asserted below.
        """
        cases = (([], "absent"),
                 (["--caller-version", "3.x"], "malformed"),
                 (["--caller-version", ""], "empty"),
                 (["--caller-version", "314"], "no dot"),
                 (["--caller-version", "3.14garbage"], "trailing text"),
                 (["--caller-version", "3.14.1"], "three components"),
                 (["--caller-version", "3."], "empty minor"),
                 (["--caller-version", "3.14 "], "trailing space"))
        for extra, why in cases:
            proc = self._launch(extra)
            self.assertEqual(proc.returncode, 82,
                             "%s declaration should be refused as 82, got %d"
                             % (why, proc.returncode))

    def test_invalid_declaration_never_reaches_dlopen(self):
        """A bad declaration must not execute the helper's constructors.

        The previous version asserted stderr contained neither "probe" nor
        "dlopen" -- but a SUCCESSFUL dlopen emits neither, so the test
        would still have passed if validation had moved back after the
        load. Guessing from diagnostic text proves nothing.

        This uses the hanging-constructor fixture and MEASURES the side
        effect: if the constructor were reached, the launcher would sit in
        the probe for ~5s and exit 81. It returns 82 in milliseconds.
        """
        so = _build_hanging_helper(self.tmp)
        started = time.monotonic()
        proc = subprocess.run(
            [_LAUNCHER, "--so", _SUBSTRATE,
             "--workers", "1", "--lines", "1", "--bytes", "0",
             "--on-error", "0", "--retry", "1",
             "--src", self.src, "--result",
             os.path.join(self.tmp, "o2.bin"), "--stats-fd", "-1",
             "--udf-helper", so, "--udf", "bm", "--udf-attr", "up",
             "--caller-version", "3.14garbage"],
            capture_output=True, timeout=20)
        elapsed = time.monotonic() - started
        self.assertEqual(proc.returncode, 82,
                         "malformed declaration must be 82, got %d"
                         % proc.returncode)
        self.assertLess(
            elapsed, 2.0,
            "took %.1fs, so the ELF constructor DID run before validation. "
            "Parsing must precede the probe's dlopen." % elapsed)

    def test_source_offset_unchanged_on_refusal(self):
        """Pre-ingestion, proven by the descriptor's own offset.

        A FIFO path would have deadlocked in open() before the preflight,
        so this uses an already-open descriptor and reads its offset back.
        """
        fd = os.open(self.src, os.O_RDONLY)
        try:
            self.assertEqual(os.lseek(fd, 0, os.SEEK_CUR), 0)
            # Same descriptor, preserved with pass_fds. The previous
            # version opened its own fd here AND another inside _launch,
            # so for a regular file these were independent open-file
            # descriptions: the measured offset belonged to a file the
            # launcher never touched, and the test would have passed even
            # if the launcher consumed the input.
            proc = self._launch(["--caller-version", "9.9"], src_fd=fd)
            self.assertEqual(proc.returncode, 80)
            self.assertEqual(
                os.lseek(fd, 0, os.SEEK_CUR), 0,
                "the refusal must precede ingestion; the launcher advanced "
                "the caller's descriptor offset")
        finally:
            os.close(fd)

    def test_interpreter_is_never_initialised_on_refusal(self):
        """Observe the side effect directly, via a marker file.

        fr_udf_init() writes a marker when it runs. On a version mismatch
        the marker must not exist. This is the property the test has been
        NAMING all along; the previous version could not detect its own
        violation because a successful initialisation prints nothing.
        """
        so = _build_marker_helper(self.tmp)
        marker = os.path.join(self.tmp, "init-marker")
        env = dict(os.environ)
        env["FR_TEST_INIT_MARKER"] = marker
        proc = subprocess.run(
            [_LAUNCHER, "--so", _SUBSTRATE,
             "--workers", "1", "--lines", "1", "--bytes", "0",
             "--on-error", "0", "--retry", "1",
             "--src", self.src, "--result",
             os.path.join(self.tmp, "m.bin"), "--stats-fd", "-1",
             "--udf-helper", so, "--udf", "bm", "--udf-attr", "up",
             "--caller-version", "9.9"],
            capture_output=True, timeout=25, env=env)
        self.assertEqual(proc.returncode, 80,
                         "a mismatched marker helper must be refused")
        self.assertFalse(
            os.path.exists(marker),
            "fr_udf_init() RAN despite the mismatch -- the version gate is "
            "after interpreter initialisation")

    def test_marker_helper_WOULD_be_observed_if_it_ran(self):
        """Negative control for the test above.

        Same fixture, MATCHING declaration: the helper is accepted, so
        fr_udf_init() runs and the marker appears. Without this, a marker
        that could never be written would make the previous test pass
        vacuously -- which is exactly the failure mode these tests keep
        having.
        """
        so = _build_marker_helper(self.tmp)
        marker = os.path.join(self.tmp, "init-marker-ok")
        env = dict(os.environ)
        env["FR_TEST_INIT_MARKER"] = marker
        proc = subprocess.run(
            [_LAUNCHER, "--so", _SUBSTRATE,
             "--workers", "1", "--lines", "1", "--bytes", "0",
             "--on-error", "0", "--retry", "1",
             "--src", self.src, "--result",
             os.path.join(self.tmp, "m2.bin"), "--stats-fd", "-1",
             "--udf-helper", so, "--udf", "bm", "--udf-attr", "up",
             "--caller-version", _caller_version()],
            capture_output=True, timeout=25, env=env)
        # Assert the exit status, not just the marker: if the helper were
        # refused early the marker would be absent and the test would
        # "pass" for a reason that proves nothing.
        self.assertEqual(proc.returncode, 0,
                         "the marker helper must be ACCEPTED when the "
                         "declaration matches; stderr=%r"
                         % proc.stderr[-300:])
        self.assertTrue(
            os.path.exists(marker),
            "the marker must be writable when the helper IS accepted, or "
            "the mismatch test above proves nothing")

    # ------------------------------------------------------------------
    # status contract
    # ------------------------------------------------------------------
    def test_stamp_must_come_from_the_helper_itself(self):
        """A dependency exporting the stamp must not satisfy the lookup.

        dlsym(handle, ...) searches the opened object AND its
        automatically loaded dependencies. A helper lacking
        fr_udf_built_version_v2 must therefore be refused even when a
        dependency happens to export that name -- otherwise the launcher
        would read a version from a library it did not choose and call
        through a signature it never validated.
        """
        # A "helper" that has no stamp of its own, but pulls in one.
        libdir = os.path.join(self.tmp, "dep")
        os.makedirs(libdir, exist_ok=True)
        with open(os.path.join(libdir, "stamp_provider.c"), "w") as fh:
            fh.write(
                "#include <stdlib.h>\n"
                "struct fr_udf_version { int major; int minor; };\n"
                "void fr_udf_built_version_v2(struct fr_udf_version *o)\n"
                "{ if (o) { o->major = 3; o->minor = 14; } }\n")
        dep = os.path.join(libdir, "libstampdep.so")
        subprocess.run(["gcc", "-shared", "-fPIC", "-o", dep,
                        os.path.join(libdir, "stamp_provider.c")],
                       check=True, capture_output=True, timeout=180)

        # The helper itself exports NOTHING named like the stamp.
        helper_c = os.path.join(libdir, "helper.c")
        with open(helper_c, "w") as fh:
            fh.write("int unrelated_symbol(void) { return 1; }\n")
        helper = os.path.join(libdir, "libnohelper.so")
        # --no-as-needed is LOAD-BEARING: helper.c references nothing in
        # the dependency, so the default --as-needed drops the DT_NEEDED
        # entry, the loader never loads libstampdep.so, and a bare dlsym
        # finds no stamp at all -- the refusal then passes for a reason
        # this test does not claim.
        subprocess.run(
            ["gcc", "-shared", "-fPIC", "-o", helper, helper_c,
             "-L" + libdir, "-Wl,--no-as-needed", "-lstampdep",
             "-Wl,--as-needed", "-Wl,-rpath," + libdir],
            check=True, capture_output=True, timeout=180)

        # Premise assertion: the stamp must be reachable THROUGH the
        # helper, or the launcher below is not being asked the question
        # this test exists to ask. ctypes uses the same dlsym semantics
        # the launcher does (opened object + its dependencies).
        import ctypes
        probe = ctypes.CDLL(helper)
        self.assertTrue(
            hasattr(probe, "fr_udf_built_version_v2"),
            "fixture premise failed: the dependency's stamp is not "
            "reachable through %s, so a bare dlsym could not have found "
            "it and this test would pass vacuously" % helper)

        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = libdir + ":" + env.get("LD_LIBRARY_PATH", "")
        proc = subprocess.run(
            [_LAUNCHER, "--so", _SUBSTRATE,
             "--workers", "1", "--lines", "1", "--bytes", "0",
             "--on-error", "0", "--retry", "1",
             "--src", self.src, "--result",
             os.path.join(self.tmp, "dep.bin"), "--stats-fd", "-1",
             "--udf-helper", helper, "--udf", "bm", "--udf-attr", "up",
             "--caller-version", _caller_version()],
            capture_output=True, timeout=25, env=env)
        # The dependency IS on the loader path, so a bare dlsym would have
        # found the stamp there and accepted it.
        self.assertEqual(
            proc.returncode, 80,
            "a stamp resolved out of a DEPENDENCY must be refused as "
            "unverifiable; got %d with stderr=%r"
            % (proc.returncode, proc.stderr[-300:]))
        self.assertIn(b"resolves into", proc.stderr,
                      "the refusal must say the symbol came from elsewhere")

    def test_crashing_constructor_is_not_reported_as_a_timeout(self):
        """A CRASH is not a TIMEOUT.

        Pinning the distinction the diagnostic fix made: a child that dies
        or closes the pipe without reporting is a probe FAILURE (71), not
        an expired deadline (81). Before the fix both returned 81 with a
        "TIMED OUT" message, so a constructor that crashed in
        microseconds was reported as having hung for five seconds.
        """
        so = _build_crashing_helper(self.tmp)
        started = time.monotonic()
        proc = subprocess.run(
            [_LAUNCHER, "--so", _SUBSTRATE,
             "--workers", "1", "--lines", "1", "--bytes", "0",
             "--on-error", "0", "--retry", "1",
             "--src", self.src, "--result",
             os.path.join(self.tmp, "c.bin"), "--stats-fd", "-1",
             "--udf-helper", so, "--udf", "bm", "--udf-attr", "up",
             "--caller-version", _caller_version()],
            capture_output=True, timeout=25)
        elapsed = time.monotonic() - started
        self.assertEqual(proc.returncode, 71,
                         "a crashed constructor must be 71 (probe failure), "
                         "got %d; stderr=%r"
                         % (proc.returncode, proc.stderr[-300:]))
        self.assertNotIn(b"TIMED OUT", proc.stderr,
                         "a crash must not be reported as a timeout")
        self.assertLess(elapsed, 2.0,
                        "a crash must be detected immediately, not after "
                        "the 5s deadline (took %.1fs)" % elapsed)

    def test_status_contract(self):
        """Pin the classification of EVERY UDF refusal code, not just two."""
        for code in (80, 81, 82, 71):
            self.assertIn(code, _CR_EXIT_PRE_INGEST,
                          "%d is a pre-ingestion refusal" % code)
            self.assertNotIn(code, _CR_EXIT_NO_FALLBACK,
                             "%d is safely declineable, unlike 79" % code)
            self.assertIn(code, _CR_EXIT_LABELS,
                          "%d must carry a human-readable label" % code)
        # Every label must name the CURRENT symbol, not the superseded one.
        self.assertIn("fr_udf_built_version_v2", _CR_EXIT_LABELS[80])
        self.assertNotIn("(no fr_udf_built_version symbol)",
                         _CR_EXIT_LABELS[80])
        # 71 is no longer only fr_py_init: a UDF probe failure returns it.
        self.assertIn("UDF", _CR_EXIT_LABELS[71])
        # 81 must not claim the helper was never loaded: the disposable
        # probe child DID dlopen it and ran its constructors.
        self.assertNotIn("the helper was not loaded", _CR_EXIT_LABELS[81])

    def test_status_contract_legacy_subset(self):
        for code in (80, 81):
            self.assertIn(code, _CR_EXIT_PRE_INGEST,
                          "%d is a pre-ingestion refusal" % code)
            self.assertNotIn(code, _CR_EXIT_NO_FALLBACK,
                             "%d is safely declineable, unlike 79" % code)
            self.assertIn(code, _CR_EXIT_LABELS)
        self.assertIn("unsafe", _CR_EXIT_LABELS[79],
                      "79 must keep its unsafe-plugin meaning")

    # ------------------------------------------------------------------
    # public API degradation
    # ------------------------------------------------------------------
    def _force_mismatch(self):
        """Make the wrapper DECLARE a version the helper does not match."""
        orig = _udf.caller_version_arg
        _udf.caller_version_arg = lambda: "--caller-version=9.9"
        self.addCleanup(setattr, _udf, "caller_version_arg", orig)

    def test_capability_reports_false_for_a_refused_helper(self):
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.addCleanup(os.environ.pop, "FORKRUN_CLEANROOM", None)
        # The in-process fallback resolves the spec in the PARENT, so the
        # fixture module has to be importable there.
        sys.path.insert(0, self.tmp)
        self.addCleanup(sys.path.remove, self.tmp)
        self._force_mismatch()
        forkrun.map("bm:up", self.src, mode="udf", workers=1,
                    on_error="retry", output="bytes")
        # A conclusive refusal is remembered against the artifact.
        self.assertIsNotNone(_udf.known_incompatible(_HELPER),
                             "a conclusive mismatch must be cached")
        self.assertFalse(v1_available()["udf"])

    def test_probe_timeout_is_not_cached_as_incompatibility(self):
        """A timeout is INCONCLUSIVE and must never disable the accelerator.

        SCOPE, stated accurately: this is a UNIT test of the Python
        caching policy. It is not an integration test, and an earlier
        docstring here claimed it "force[d] a genuine 81 from the
        launcher", which the body did not do -- a directly-launched C
        launcher cannot mutate this process's cache. The launcher's own
        exit-81 behaviour is covered by
        test_timeout_fixture_really_exits_81, and together the two are
        useful. Neither alone is what this paragraph used to imply.

        History worth keeping: the version before that wrote an entry,
        cleared the whole cache, then asserted the entry was gone. It
        exercised nothing and passed no matter what the code did.
        """
        # The cache is a PYTHON-PROCESS structure; a directly-launched
        # C launcher cannot mutate it. The previous version therefore
        # checked the wrong dict: it launched a TEMPORARY hanging helper
        # and then asserted the INSTALLED helper was absent from the
        # cache -- which it trivially was, so the test passed no matter
        # what _record_compat_refusal did.
        #
        # Exercise the Python policy directly, with the real code under
        # test.
        fp = _udf.fingerprint_now(_HELPER)
        self.assertIsNotNone(fp, "the installed helper must be fingerprinted")
        _udf.record_incompatible_for(fp, "synthetic 80")
        self.assertIsNotNone(_udf.known_incompatible(_HELPER),
                             "positive control: 80 IS cacheable")

        _udf.clear_incompatibles()
        from forkrun.run import _record_compat_refusal
        _record_compat_refusal(81, "probe timed out", fp)
        self.assertIsNone(
            _udf.known_incompatible(_HELPER),
            "81 is inconclusive; caching it would let a transient stall "
            "permanently disable the accelerator for this artifact")
        _record_compat_refusal(82, "invalid declaration", fp)
        self.assertIsNone(
            _udf.known_incompatible(_HELPER),
            "82 is a caller bug, not evidence about the helper; it must "
            "not blacklist a good artifact")

    def test_refusal_is_keyed_to_the_fingerprint_it_was_given(self):
        """What this DOES prove, and what it does not.

        PROVES: a refusal recorded against fingerprint fp1 does not make
        fp2 -- the same path, replaced -- ineligible. That is the failure
        mode that silently disables a valid helper.

        DOES NOT PROVE: that the dispatch threads the pre-launch
        fingerprint in. Distinguishing that needs the artifact to change
        WHILE the launcher runs; without a mid-flight replacement the
        pre- and post-launch fingerprints are the same value, so a revert
        to re-deriving the path afterwards is invisible here. Verified by
        mutation: reverting the threading left this test green.

        What IS pinned separately, below, is that a real public refusal
        supplies a fingerprint at all.
        """
        real = os.path.join(self.tmp, "inflight.so")
        with open(real, "wb") as fh:
            fh.write(b"\x7fELF original\n")
        fp1 = _udf.fingerprint_now(real)
        self.assertIsNotNone(fp1)

        time.sleep(0.01)
        with open(real, "wb") as fh:
            fh.write(b"\x7fELF replacement, longer\n")
        fp2 = _udf.fingerprint_now(real)
        self.assertNotEqual(fp1, fp2, "the replacement must differ")

        from forkrun.run import _record_compat_refusal
        _record_compat_refusal(80, "refusal for the original artifact", fp1)

        self.assertIsNotNone(
            _udf.known_incompatible_by_fp(fp1),
            "the refusal must land on the fingerprint it was given")
        self.assertIsNone(
            _udf.known_incompatible_by_fp(fp2),
            "the REPLACEMENT must stay eligible; recording against it "
            "silently disables a valid helper")

    def test_public_refusal_supplies_a_fingerprint_at_all(self):
        """The dispatch must HAND the handler a fingerprint.

        Pinned separately because the test above cannot see the threading:
        without a mid-flight replacement the values are identical either
        way. What this catches is the coarse regression -- the handler
        being called with None, which would silently disable caching
        entirely rather than mis-key it.
        """
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.addCleanup(os.environ.pop, "FORKRUN_CLEANROOM", None)
        sys.path.insert(0, self.tmp)
        self.addCleanup(sys.path.remove, self.tmp)
        self._force_mismatch()

        # sys.modules, NOT `import forkrun.run`: the package exports a
        # FUNCTION named run, which shadows the submodule, so the import
        # binds the function and has no attributes to spy on.
        import sys as _sys
        _runmod = _sys.modules["forkrun.run"]
        seen = []
        original = _runmod._record_compat_refusal
        def _spy(code, detail, helper_fp=None):
            seen.append(helper_fp)
            return original(code, detail, helper_fp)
        _runmod._record_compat_refusal = _spy
        self.addCleanup(setattr, _runmod, "_record_compat_refusal",
                        original)

        before = _udf.fingerprint_now(_HELPER)
        forkrun.map("bm:up", self.src, mode="udf", workers=1,
                    on_error="retry", output="bytes")

        compat_calls = [fp for fp in seen if fp is not None]
        self.assertTrue(
            compat_calls,
            "a conclusive public refusal must reach the cache handler with "
            "a fingerprint; it arrived with None, so a mismatch would never "
            "be remembered and every call would re-probe the launcher")
        self.assertEqual(compat_calls[0], before,
                         "the fingerprint must be the one captured for THIS "
                         "invocation")

    def test_timeout_fixture_really_exits_81(self):
        """Kept separate: exit 81 itself is the launcher's contract."""
        rc = _run_launcher_with_hanging_helper(self.tmp)
        self.assertEqual(rc, 81,
                        "a hung constructor must be bounded into exit 81")

    def test_hung_constructor_is_bounded_into_exit_81(self):
        """The timeout path must actually run.

        A shared object whose ELF constructor blocks forever. It does not
        embed CPython: the property under test is that the launcher can
        bound a dlopen() that never returns.

        The test's own subprocess timeout is the backstop -- without it a
        regression here would FREEZE the suite rather than fail it.
        """
        so = _build_hanging_helper(self.tmp)
        self.assertTrue(os.path.exists(so))
        started = time.monotonic()
        proc = subprocess.run(
            [_LAUNCHER, "--so", _SUBSTRATE,
             "--workers", "1", "--lines", "1", "--bytes", "0",
             "--on-error", "0", "--retry", "1",
             "--src", self.src, "--result",
             os.path.join(self.tmp, "o.bin"), "--stats-fd", "-1",
             "--udf-helper", so, "--udf", "bm", "--udf-attr", "up",
             "--caller-version", _caller_version()],
            capture_output=True, timeout=30)
        elapsed = time.monotonic() - started
        self.assertEqual(proc.returncode, 81,
                         "a hung ELF constructor must be bounded into 81, "
                         "not waited on; stderr=%r" % proc.stderr[-300:])
        # The configured deadline is 5s. 60s was not a meaningful
        # regression bound for that -- it only caught "hangs forever".
        # This asserts the deadline is actually ENFORCED, with headroom
        # for CI scheduling and reap cleanup.
        self.assertLess(elapsed, 12.0,
                        "the %ds probe deadline is not being enforced "
                        "(took %.1fs)" % (5, elapsed))

    def _capture_stdout_stderr(self, fn):
        import io
        import contextlib
        out_b, err_b = io.StringIO(), io.StringIO()
        real_out, real_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = out_b, err_b
            result = fn()
        finally:
            sys.stdout, sys.stderr = real_out, real_err
        return result, out_b.getvalue(), err_b.getvalue()

    def test_kill_switch_suppresses_the_probe_ALONE(self):
        """No cache entry at all: the kill switch must prevent the probe.

        The previous version POISONED the cache first, which makes the
        helper unavailable anyway -- so the launcher could be skipped
        even if FORKRUN_NO_UDF failed to suppress probing. The claim in
        the test's name was never established.

        Here the cache is CLEAN, and the observation is the launcher
        binary being invoked at all: with the switch set, the cleanroom
        route must not be taken, so it must never be exec'd.
        """
        _udf.clear_incompatibles()
        self.assertIsNone(
            _udf.known_incompatible(_HELPER),
            "precondition: no cached refusal, so nothing else could be "
            "suppressing the probe")

        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.addCleanup(os.environ.pop, "FORKRUN_CLEANROOM", None)
        sys.path.insert(0, self.tmp)
        self.addCleanup(sys.path.remove, self.tmp)
        os.environ["FORKRUN_NO_UDF"] = "1"
        self.addCleanup(os.environ.pop, "FORKRUN_NO_UDF", None)

        _runmod = sys.modules["forkrun.run"]
        launched = []
        real_cleanroom_enabled = _runmod._cleanroom_enabled
        _runmod._cleanroom_enabled = lambda: True   # would otherwise engage
        self.addCleanup(setattr, _runmod, "_cleanroom_enabled",
                        real_cleanroom_enabled)
        # helper_path() is what every route consults; with the switch on it
        # must be None, which is what makes the cleanroom branch
        # ineligible even though _cleanroom_enabled() is True.
        self.assertIsNone(_udf.helper_path())

        # lines=1: the assertion below compares one output element per
        # RECORD, so the batching must be one record per batch. Auto
        # batching on a 4-CPU runner groups the 8 lines into fewer
        # blobs, which is correct engine behaviour and a wrong premise
        # for this test.
        out, sout, serr = self._capture_stdout_stderr(
            lambda: forkrun.map("bm:up", self.src, mode="udf",
                                workers=1, on_error="retry",
                                output="bytes", lines=1))
        self.assertNotIn("declined", serr,
                         "no probe happened, so there is no refusal to "
                         "report. Got: %r" % serr[:200])

        # COMPLETE results, not merely nonempty: assertTrue(out) only
        # proves something came back.
        self.assertEqual(
            sorted(out),
            [b"LINE%d\n" % i for i in range(8)],
            "the kill switch must DEGRADE to a COMPLETE in-process run. "
            "src.txt has 8 lines and the fixture uppercases them, so this "
            "is every record, not merely a nonempty result; got %r"
            % (out,))

    def test_kill_switch_suppresses_the_WARNING_for_a_poisoned_cache(self):
        """Separate claim: a cached refusal must not warn under the switch.

        Kept apart from the probe test above on purpose. Poisoning the
        cache is the right way to make a warning DUE; it is the wrong way
        to test probe suppression, because it suppresses the helper by
        itself.
        """
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.addCleanup(os.environ.pop, "FORKRUN_CLEANROOM", None)
        sys.path.insert(0, self.tmp)
        self.addCleanup(sys.path.remove, self.tmp)
        fp = _udf.fingerprint_now(_HELPER)
        self.assertIsNotNone(fp)
        _udf.record_incompatible_for(fp, "pre-existing refusal")

        os.environ["FORKRUN_NO_UDF"] = "1"
        self.addCleanup(os.environ.pop, "FORKRUN_NO_UDF", None)
        self.assertIsNone(_udf.helper_path())

        out, sout, serr = self._capture_stdout_stderr(
            lambda: forkrun.map("bm:up", self.src, mode="udf",
                                workers=1, on_error="retry",
                                output="bytes"))
        self.assertNotIn("declined", serr,
                         "FORKRUN_NO_UDF means the UDF path was never "
                         "considered; warning here would describe something "
                         "that did not happen. Got: %r" % serr[:200])
        self.assertTrue(out, "and the run must still produce results")


if __name__ == "__main__":
    unittest.main()