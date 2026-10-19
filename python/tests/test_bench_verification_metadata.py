"""F6 Stage 5.5: the benchmark's payload-verification metadata must be truthful.

The per-trial content check in `bench_cleanroom_backends.py` compares a
`collections.Counter` of the observed payload tokens against a Counter of
the expected ones. That is a MULTISET comparison: it pins multiplicity as
well as membership, which is why a result that kept every expected token
and appended an extra copy of one is rejected. A set comparison would pass
that case, which is exactly why the Counter was adopted.

Two things can silently undo the honesty of that description:

  * the METADATA drifts. Stage 5.5 found the artifact describing the check
    as a "payload token set" -- a weaker check than the one that runs --
    and the aggregate and per-cell strings had already drifted apart from
    each other by a comma, because the phrase was written out literally at
    three sites.

  * the IMPLEMENTATION weakens to match. If `one_call` regressed to set
    equality while the metadata still said "multiset", the artifact would
    be making a claim the code no longer supports.

These tests pin both directions, and both fail if either regresses. They are
deliberately fast: they import the benchmark module and inspect it, and
they read the committed artifact, rather than running a benchmark.
"""

import collections
import importlib.util
import inspect
import json
import os
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BENCH = REPO / "dev" / "supervisor" / "bench_cleanroom_backends.py"
ARTIFACTS = REPO / "dev" / "supervisor" / "bench_artifacts"


def _load_bench():
    spec = importlib.util.spec_from_file_location(
        "bench_cleanroom_backends", str(BENCH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestVerificationMetadataIsTruthful(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench = _load_bench()
        cls.artifacts = sorted(
            p for p in ARTIFACTS.glob("cleanroom_backends_*.json")
            if not re.search(r"\.json\.(private|shared)\.json$", p.name))
        if not cls.artifacts:
            raise unittest.SkipTest("no committed benchmark artifact")

    def test_description_says_multiset_not_set(self):
        text = self.bench.PER_TRIAL_VERIFICATION
        self.assertIn("multiset", text.lower(),
                      "the per-trial verification description must say "
                      "multiset; a set discards multiplicity")
        self.assertNotRegex(
            text, r"token set\b",
            "the description still claims a token SET, which is a weaker "
            "check than the Counter comparison that actually runs: %r" % text)

    def test_description_names_the_counter(self):
        self.assertIn("Counter", self.bench.PER_TRIAL_VERIFICATION,
                      "naming the mechanism makes the claim checkable "
                      "against the implementation")

    def test_implementation_actually_uses_a_counter(self):
        """The metadata's claim must be true of the code, not just worded."""
        src = inspect.getsource(self.bench.one_call)
        self.assertIn("collections.Counter", src,
                      "one_call() no longer compares Counters, so the "
                      "multiset description would be false")
        src_expected = inspect.getsource(self.bench.expected_tokens)
        self.assertIn("collections.Counter", src_expected,
                      "expected_tokens() no longer returns a Counter")

    def test_expected_tokens_is_a_counter_and_is_a_multiset(self):
        counter = self.bench.expected_tokens(4)
        self.assertIsInstance(counter, collections.Counter)
        # A Counter distinguishes 'PAYLOAD_00000001 once' from 'twice';
        # a set cannot.
        doubled = collections.Counter(
            [b"PAYLOAD_00000000", b"PAYLOAD_00000000", b"PAYLOAD_00000001"])
        single = collections.Counter(
            [b"PAYLOAD_00000000", b"PAYLOAD_00000001"])
        self.assertNotEqual(doubled, single,
                            "the expected-token structure cannot distinguish "
                            "a duplicated token, so it is not a multiset")

    def test_all_emission_sites_use_the_shared_constant(self):
        """One constant, so the strings cannot drift apart again."""
        src = BENCH.read_text()
        offenders = []
        for match in re.finditer(r'"per_trial_verification":', src):
            rest = src[match.end():].lstrip()
            if not rest.startswith("PER_TRIAL_VERIFICATION"):
                offenders.append(rest.split("\n")[0].strip())
        self.assertEqual(offenders, [],
                         "per_trial_verification is written literally again; "
                         "it must reference PER_TRIAL_VERIFICATION so the "
                         "aggregate and per-cell forms cannot diverge: %r"
                         % offenders)

    def test_committed_artifacts_describe_a_multiset(self):
        for path in self.artifacts:
            data = json.loads(path.read_text())
            with self.subTest(artifact=path.name):
                desc = data.get("per_trial_verification", "")
                self.assertIn("multiset", desc.lower(),
                              "%s: aggregate metadata describes a set, not a "
                              "multiset: %r" % (path.name, desc))
                self.assertNotRegex(desc, r"token set\b",
                                    "%s: aggregate metadata claims a token "
                                    "set: %r" % (path.name, desc))
                for cell in data.get("cells", []):
                    cdesc = cell.get("per_trial_verification", "")
                    self.assertEqual(
                        cdesc, desc,
                        "%s: cell metadata %r differs from aggregate %r"
                        % (path.name, cdesc, desc))

    def test_committed_artifact_agrees_with_the_script(self):
        """The artifact must describe what the script would emit today."""
        path = self.artifacts[-1]
        data = json.loads(path.read_text())
        self.assertEqual(data.get("per_trial_verification"),
                         self.bench.PER_TRIAL_VERIFICATION,
                         "%s: the committed artifact's description no longer "
                         "matches the script's constant, so one of them "
                         "stale" % path.name)


class TestContentCheckStillRejectsMultiplicityErrors(unittest.TestCase):
    """The Counter check itself must not have been weakened."""

    @classmethod
    def setUpClass(cls):
        cls.bench = _load_bench()

    def _tokens(self, records):
        return collections.Counter(b"".join(records).split())

    def test_clean_output_matches(self):
        want = self.bench.expected_tokens(4)
        recs = [("PAYLOAD_%08d\n" % i).encode() for i in range(4)]
        self.assertEqual(self._tokens(recs), want)

    def test_duplicated_token_is_rejected(self):
        """The case a set comparison passes: count unchanged, membership kept.

        Modelled the way the route could actually produce it -- one record
        carries a token twice and another carries none -- so the NUMBER of
        records is identical and the set of distinct tokens is unchanged.
        """
        want = self.bench.expected_tokens(4)
        # One record swallows another record's token, and one record is
        # emptied: the NUMBER of records is unchanged, every expected token
        # is still present, and one token appears twice. A set comparison
        # accepts all of that; only the Counter rejects it.
        recs = [
            ("PAYLOAD_%08d\n" % 0).encode(),
            ("PAYLOAD_%08d\n" % 1).encode(),
            ("PAYLOAD_%08d\n" % 0).encode()
            + ("PAYLOAD_%08d\n" % 2).encode()
            + ("PAYLOAD_%08d\n" % 3).encode(),
            b"",
        ]
        self.assertEqual(len(recs), 4, "record count is unchanged by this")
        self.assertEqual(set(self._tokens(recs)), set(want),
                         "sanity: a SET comparison would wrongly accept this")
        self.assertNotEqual(self._tokens(recs), want,
                            "a duplicated token must fail the multiset check")

    def test_missing_token_is_rejected(self):
        want = self.bench.expected_tokens(4)
        recs = [("PAYLOAD_%08d\n" % i).encode() for i in range(3)]
        self.assertNotEqual(self._tokens(recs), want)

    def test_substituted_token_is_rejected(self):
        want = self.bench.expected_tokens(4)
        recs = [("PAYLOAD_%08d\n" % i).encode() for i in range(4)]
        recs[2] = b"PAYLOAD_99999999\n"
        self.assertNotEqual(self._tokens(recs), want)


class TestNoBenchmarkWasRerunForMetadataOnlyChange(unittest.TestCase):
    """Stage 5.5 changed a description, not a measurement."""

    @classmethod
    def setUpClass(cls):
        cls.artifacts = sorted(
            p for p in ARTIFACTS.glob("cleanroom_backends_*.json")
            if not re.search(r"\.json\.(private|shared)\.json$", p.name))
        if not cls.artifacts:
            raise unittest.SkipTest("no committed benchmark artifact")

    def test_artifact_records_its_own_parameters(self):
        data = json.loads(self.artifacts[-1].read_text())
        for key in ("mib", "reps", "lines", "expected_records", "python",
                    "kernel", "libc", "valid"):
            self.assertIn(key, data,
                          "artifact must retain %r for provenance" % key)
        self.assertTrue(data["valid"], "the artifact is marked invalid")

    def test_every_cell_retains_its_samples(self):
        data = json.loads(self.artifacts[-1].read_text())
        for cell in data["cells"]:
            for backend, samples in cell["samples_ms"].items():
                self.assertEqual(len(samples), data["reps"],
                                 "%s lost samples for %s; Stage 5.5 changed a "
                                 "description and must not touch measurements"
                                 % (cell["cell"], backend))


if __name__ == "__main__":
    unittest.main()