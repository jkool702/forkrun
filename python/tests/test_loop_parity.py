"""Loop parity: the shared worker lifecycle must stay identical across modes.

The external review accepted a FIFTH worker loop on one condition:

  "If the fifth loop copies the whole existing state machine, every
   future fix to poison handling, transaction completion, or
   acknowledgement ordering has another place to land. I would require
   parity tests for all shared lifecycle behavior."

This is that parity test, and it is mechanical rather than behavioural
on purpose. A behavioural test has to be re-derived per mode and can be
satisfied by a loop that is wrong in the same way everywhere. Comparing
the LIFECYCLE SOURCE across modes catches the actual failure mode: a fix
applied to four loops and forgotten in the fifth.

What is compared: the poison-skip branch, the zero-length sentinel
branch, and the whole on_error ladder (skip / fail-fast / escrow). Those
must be identical, because a caller that sets on_error="skip" gets the
same guarantee regardless of which mode ran.

What is NOT compared, and why:
  * the invoke call -- different by definition;
  * fr_py_plugin_ensure -- plugin-only;
  * fr_py_worker_splice_loop -- EXCLUDED BY DESIGN. Splice does not
    invoke user code; it moves bytes out of the ingress spool, so its
    retry rule is "always", not the on_error ladder. The plugin loop's
    own comment says so. Comparing it here would assert a falsehood.

Run: python3 -m unittest test_loop_parity
"""

import os
import re
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
_SHIM = os.path.join(_ROOT, "python", "forkrun", "_shim.c")

# Modes whose failures are payload errors, and so share the on_error
# ladder. Splice is deliberately absent -- see the module docstring.
PARITY_MODES = (
    "fr_py_worker_plugin_loop",
    "fr_py_worker_spawn_loop",
    "fr_py_worker_udf_loop",
)


def _function_body(src, name):
    """Return the source text of ``name``'s body, braces balanced."""
    start = src.index("int %s(" % name)
    brace = src.index("{", start)
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError("unbalanced braces in %s" % name)


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _canonical(text):
    """Reduce a loop body to the shared lifecycle, mode differences out.

    Normalisations, each one a difference that is legitimate rather than
    drift:

    * the signature is dropped entirely -- it is compared separately by
      test_signatures_match_across_modes, and trying to normalize
      parameter NAMES by hand is what makes this kind of test rot;
    * the leading argument-validation guard collapses to one token. Its
      spelling differs because the arguments differ (a plugin has a
      path and a function name, spawn has argv/argc), but the contract
      is the same: reject bad arguments, return 1;
    * the per-mode invoke call and the plugin-only ensure are removed --
      they ARE the per-mode difference;
    * the spawn-only infrastructure guard is removed here and PINNED
      separately by TestKnownDivergences, so it cannot be forgotten;
    * comments are stripped, and whitespace is collapsed, because
      formatting churn must never fail this test.
    """
    text = _strip_comments(text)
    text = text[text.index("{") + 1:]           # drop the signature
    # The first "if (...) return 1;" is the argument guard.
    text = re.sub(r"if\s*\([^;{]*\)\s*\n?\s*return 1;", "VALIDATE;",
                  text, count=1, flags=re.S)
    text = re.sub(r"\s*rc = fr_py_(?:\w+_invoke|exec_spawn)\([^;]*;",
                  " INVOKE;", text, flags=re.S)
    text = re.sub(r"\s*if \(fr_py_plugin_ensure\([^;]*\n\s*return 1;",
                  "", text)
    text = re.sub(r"\s*if \(rc < 0\)\s*return 1;", "", text)
    # sizeof(x) and sizeof x are the same thing, and the loops differ on
    # spelling only. Pure formatting; normalizing it here keeps the
    # comparison about behaviour.
    text = re.sub(r"sizeof\s*\(\s*(\w+)\s*\)", r"sizeof \1", text)
    return re.sub(r"\s+", " ", text).strip()


class TestLoopParity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(_SHIM) as fh:
            cls.src = fh.read()

    def canonical(self, mode):
        return _canonical(_function_body(self.src, mode))

    def test_every_mode_shares_one_lifecycle(self):
        base_mode = PARITY_MODES[0]
        base = self.canonical(base_mode)
        for other in PARITY_MODES[1:]:
            with self.subTest(mode=other, against=base_mode):
                self.assertEqual(
                    base, self.canonical(other),
                    "%s has drifted from %s. The shared lifecycle -- poison "
                    "skip, zero-length sentinel, and the whole on_error "
                    "ladder -- must be identical across modes, or a fix "
                    "applied to one will silently miss another."
                    % (other, base_mode))

    # -- the specific guarantees the parity protects -------------------

    def test_poison_skip_is_acksilent_and_traps(self):
        """A poisoned batch warns, notifies via the trap pipe, and
        completes WITHOUT a signal -- nothing was emitted, so signalling
        would tell the parent a record exists."""
        for mode in PARITY_MODES:
            body = self.canonical(mode)
            with self.subTest(mode=mode):
                self.assertIn("Skipping poisoned batch", body)
                self.assertIn("P:%llu:%u", body)
                self.assertIn("fr_py_complete(-1,", body)

    def test_zero_length_sentinel_never_emits(self):
        """The bash REPLY rule: a zero-length slot is acked, not
        executed. Shared by every payload-failure mode."""
        for mode in PARITY_MODES:
            body = self.canonical(mode)
            with self.subTest(mode=mode):
                self.assertIn("claimed.length == 0", body)
                self.assertIn("fr_py_complete(-1,", body)

    def test_the_on_error_ladder_is_complete_and_ordered(self):
        """skip -> ack silent; fail-fast -> abort; otherwise escrow with
        kills+1 and NO ack. A mode missing an arm would silently apply
        the wrong policy to a caller who asked for it."""
        for mode in PARITY_MODES:
            body = self.canonical(mode)
            with self.subTest(mode=mode):
                self.assertIn("on_error == 1", body)
                self.assertIn("on_error == 2", body)
                self.assertIn("fr_py_escrow_deposit(claimed.num_kills + 1)",
                              body)
                self.assertIn("fr_py_abort()", body)

    def test_signal_epipe_is_fatal(self):
        """Parent gone must not be reported as a normal exit."""
        for mode in PARITY_MODES:
            with self.subTest(mode=mode):
                self.assertIn("return 2;", self.canonical(mode))

    @staticmethod
    def _params(mode, src):
        body = _function_body(src, mode)
        params = body[body.index("(") + 1:body.index(")")]
        out = []
        for part in params.split(","):
            part = part.strip()
            if part:
                bits = part.split()
                out.append((bits[-1], " ".join(bits[:-1])))
        return out

    def test_signatures_share_the_transport_tail(self):
        """Every mode must agree from ingress_fd onward.

        The LEADING parameters are legitimately different: a plugin takes
        (path, func_name), a UDF (module, attr), and spawn takes a whole
        (argv, argc) pair -- so spawn has thirteen parameters where the
        others have twelve. That asymmetry is real and predates this
        work.

        What must NOT differ is the transport tail. spawn_wid passes one
        argument list positionally to whichever loop it was handed; if
        the types after ingress_fd ever diverged, a worker would read a
        descriptor as an integer and the parity comparison -- which
        strips signatures -- would not notice.
        """
        tails = {}
        for mode in PARITY_MODES:
            params = self._params(mode, self.src)
            idx = [i for i, (n, _) in enumerate(params) if n == "ingress_fd"]
            self.assertTrue(idx, "%s has no ingress_fd parameter" % mode)
            tails[mode] = params[idx[0]:]
        base = tails[PARITY_MODES[0]]
        for other in PARITY_MODES[1:]:
            with self.subTest(mode=other):
                self.assertEqual(base, tails[other],
                                 "the transport parameter list diverged "
                                 "after ingress_fd")

    def test_every_mode_takes_the_same_number_of_arguments(self):
        """spawn passes (argv, argc) where the others pass two spec
        strings, so the counts match even though the leading types do
        not. spawn_wid passes one positional argument list, so a
        mismatch here would be a silent argument shift."""
        arity = {m: len(self._params(m, self.src)) for m in PARITY_MODES}
        self.assertEqual(
            len(set(arity.values())), 1,
            "modes take different argument counts: %r" % (arity,))

    def test_respawn_generation_is_threaded_through(self):
        """wincarn is load-bearing, not diagnostic: the engine refuses
        to reclaim a batch whose incarnation differs from the one passed
        to recovery. Every loop must pass it."""
        for mode in PARITY_MODES:
            body = _function_body(self.src, mode)
            with self.subTest(mode=mode):
                self.assertIn("fr_py_worker_init(wid, 0, wincarn,", body)


class TestKnownDivergences(unittest.TestCase):
    """Differences that are REAL, so they are pinned rather than hidden.

    A parity test that quietly normalizes away a semantic difference
    stops protecting anything, because the next person cannot tell
    which normalizations were cosmetic and which were load-bearing.
    Every intentional divergence gets its own test here.
    """

    @classmethod
    def setUpClass(cls):
        with open(_SHIM) as fh:
            cls.src = fh.read()

    def test_spawn_is_the_only_mode_that_separates_infra_failure(self):
        """fr_py_exec_spawn reports rc < 0 for a PIPE/SPAWN/WAIT/OUTPUT
        failure -- infrastructure, not the command's exit code -- and
        spawn treats it as fatal rather than feeding it to on_error.

        That is correct: a spawn that never happened is not a payload
        error, and retrying it under on_error="skip" would silently drop
        the batch. The plugin and udf invokes have no such category --
        their failures ARE payload failures -- so they go straight to
        the on_error ladder.

        Pinned: if a mode gains or loses this guard, the reviewer's
        concern (a fix landing in one mode and not the others) is
        exactly what happened.
        """
        with_infra = set()
        for mode in PARITY_MODES:
            body = _strip_comments(_function_body(self.src, mode))
            if re.search(r"if \(rc < 0\)\s*return 1;", body):
                with_infra.add(mode)
        self.assertEqual(with_infra, {"fr_py_worker_spawn_loop"},
                         "the set of modes separating infrastructure "
                         "failure from payload failure changed")


class TestSpliceIsExcludedOnPurpose(unittest.TestCase):
    """Guards the exclusion itself.

    If splice ever DID adopt the on_error ladder, this test stops
    describing reality and starts hiding a real difference. So assert
    the reason it is excluded still holds.
    """

    def test_splice_retry_rule_is_still_different(self):
        with open(_SHIM) as fh:
            src = fh.read()
        body = _canonical(_function_body(src, "fr_py_worker_splice_loop"))
        self.assertNotIn("on_error == 2", body,
                         "splice now has the on_error ladder; revisit "
                         "whether it belongs in PARITY_MODES")
        self.assertIn("fr_py_escrow_deposit", body)


if __name__ == "__main__":
    unittest.main()