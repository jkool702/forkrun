"""W-REL4/R-V3: doc-accuracy harness (headline claims paired).

The B1 lesson: docstrings were the spec the code was written from,
and six doc-vs-code divergences shipped in one week because nothing
checked spec-against-behavior after generation. This registry pairs
each headline user-facing promise with covering tests; CI fails
when a claim has no test, the test doesn't run, or the doc no
longer contains the claim.

Scope: headline behavioral promises only (grammar/style and
non-behavioral docs are out of scope). New headline claims add an
entry in the same commit as the doc + test.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DOC_CLAIMS = [
    {
        "claim": "Automatic recovery: a worker death mid-batch is "
                 "retried automatically on the default path",
        "doc_source": "python/docs/QUICKSTART.md",
        "key_phrase": "retried automatically",
        "covering_tests": [
            "test_fault.TestWorkerSegfault."
            "test_mixed_segfault_recovers_byte_exact",
        ],
        "assertion_summary": "default orchestrator; mid-batch "
                             "SIGSEGV -> byte-exact recovery",
    },
    {
        "claim": "Crash recovery is structural: SIGSEGV/SIGKILL/OOM "
                 "deaths are reverted, re-queued, respawned",
        "doc_source": "python/docs/FAULT_TOLERANCE.md",
        "key_phrase": "worker respawned",
        "covering_tests": [
            "test_fault.TestWorkerSegfault."
            "test_mixed_segfault_recovers_byte_exact",
        ],
        "assertion_summary": "same recovery test; table row asserts "
                             "the mechanism",
    },
    {
        "claim": "Initializing CUDA before run() is refused with an "
                 "actionable error",
        "doc_source": "python/README.md",
        "key_phrase": "refused",
        "covering_tests": [
            "test_cuda_guard.TestCudaGuardStreamRefusal."
            "test_stream_refuses_live_context",
            "test_cuda_guard.TestCudaGuardContract."
            "test_simulated_hazard_refuses_run",
        ],
        "assertion_summary": "mocked live context on stream path + "
                             "simulated hazard on run path -> refusal",
    },
    {
        "claim": "Resume: engine commit exactly-once (Python "
                 "consumption is not)",
        "doc_source": "python/docs/FAULT_TOLERANCE.md",
        "key_phrase": "exactly-once",
        "covering_tests": [
            "test_resume.TestResumeExecution.test_resume_worker_crash",
        ],
        "assertion_summary": "crash -> checkpoint -> resume completes "
                             "committed work",
    },
    {
        "claim": "Drain verification: per-node completion audit, no "
                 "silent partial completion",
        "doc_source": "DOCS/RESILIENCE_PROTOCOL.md",
        "key_phrase": "drain guard",
        "covering_tests": [
            "test_numa_drain_guard.TestNumaDrainAudit."
            "test_clean_passes_silently",
            "test_numa_drain_guard.TestNumaDrainAudit."
            "test_violation_raises_naming_node",
        ],
        "assertion_summary": "clean rows pass silent; violations raise "
                             "naming the node",
    },
    {
        "claim": "NUMA worker coverage: workers bumped to node count "
                 "with a warning",
        "doc_source": "python/docs/NUMA.md",
        "key_phrase": "must cover every node",
        "covering_tests": [
            "test_numa_bump.TestNumaWorkerBump."
            "test_workers_bumped_to_node_count",
        ],
        "assertion_summary": "workers < nodes bumped with UserWarning",
    },
    {
        "claim": "Streaming bounded memory: slow consumer does not "
                 "grow the parent",
        "doc_source": "python/docs/STREAMING.md",
        "key_phrase": "flat",
        "covering_tests": [
            "test_streaming.TestStreaming."
            "test_slow_consumer_bounds_memory",
        ],
        "assertion_summary": "slow consumer holds only the in-flight "
                             "window",
    },
    {
        "claim": "strict_poison raises ForkrunPoisonSkip; "
                 "signal_policy=checkpoint aborts/checkpoints/raises",
        "doc_source": "python/docs/TROUBLESHOOTING.md",
        "key_phrase": "strict_poison",
        "covering_tests": [
            "test_taxonomy.TestStrictPoison."
            "test_strict_raises_with_count",
            "test_signals.TestCheckpointPolicy."
            "test_hup_aborts_checkpoints_raises",
        ],
        "assertion_summary": "opt-in poison raise carries count; HUP "
                             "aborts, checkpoints, raises Terminated",
    },
    {
        "claim": "Exception taxonomy: Bash signal codes map to Python "
                 "exception causes (130/143/138/3)",
        "doc_source": "python/docs/TROUBLESHOOTING.md",
        "key_phrase": "Bash code",
        "covering_tests": [
            "test_taxonomy.TestTaxonomyShape.test_death_cause_mapping",
        ],
        "assertion_summary": "signal deaths map to causes, crash stays "
                             "plain RuntimeError",
    },
]


def _check_entry(entry):
    """Returns a list of failure strings (empty = covered)."""
    problems = []
    doc_path = os.path.join(REPO_ROOT, entry["doc_source"])
    if not os.path.exists(doc_path):
        problems.append(
            "DOC CLAIM UNCOVERED: '%s' (%s missing)"
            % (entry["claim"], entry["doc_source"]))
    else:
        with open(doc_path) as fh:
            content = fh.read()
        if entry["key_phrase"] not in content:
            problems.append(
                "DOC CLAIM STALE: '%s' (%s no longer contains %r)"
                % (entry["claim"], entry["doc_source"],
                   entry["key_phrase"]))
    loader = unittest.TestLoader()
    for test_id in entry["covering_tests"]:
        try:
            suite = loader.loadTestsFromName(test_id)
        except Exception as exc:  # noqa: BLE001
            problems.append(
                "DOC CLAIM UNCOVERED: '%s' (covering test %s "
                "not discoverable: %s)"
                % (entry["claim"], test_id, exc))
            continue
        if suite.countTestCases() == 0:
            problems.append(
                "DOC CLAIM UNCOVERED: '%s' (covering test %s "
                "resolved to zero cases)" % (entry["claim"], test_id))
            continue
        result = unittest.TestResult()
        suite.run(result)
        if not result.wasSuccessful():
            problems.append(
                "DOC CLAIM STALE: '%s' (covering test %s failed: "
                "%s%s)" % (entry["claim"], test_id, result.failures,
                           result.errors))
        elif result.skipped:
            problems.append(
                "DOC CLAIM STALE: '%s' (covering test %s skipped: "
                "%s)" % (entry["claim"], test_id, result.skipped))
    return problems


class TestDocAccuracy(unittest.TestCase):
    def test_registry_well_formed(self):
        for i, entry in enumerate(DOC_CLAIMS):
            for key in ("claim", "doc_source", "key_phrase",
                        "covering_tests", "assertion_summary"):
                self.assertIn(key, entry, "entry %d missing %s" % (i, key))
            self.assertTrue(entry["covering_tests"],
                            "entry %d has no covering tests" % (i,))

    def test_claim_recovery(self):
        problems = _check_entry(DOC_CLAIMS[0]) + _check_entry(DOC_CLAIMS[1])
        self.assertEqual(problems, [])

    def test_claim_cuda_refusal(self):
        self.assertEqual(_check_entry(DOC_CLAIMS[2]), [])

    def test_claim_resume(self):
        self.assertEqual(_check_entry(DOC_CLAIMS[3]), [])

    def test_claim_drain_guard(self):
        self.assertEqual(_check_entry(DOC_CLAIMS[4]), [])

    def test_claim_numa_coverage(self):
        self.assertEqual(_check_entry(DOC_CLAIMS[5]), [])

    def test_claim_streaming_memory(self):
        self.assertEqual(_check_entry(DOC_CLAIMS[6]), [])

    def test_claim_new_params(self):
        self.assertEqual(_check_entry(DOC_CLAIMS[7]), [])

    def test_claim_taxonomy(self):
        self.assertEqual(_check_entry(DOC_CLAIMS[8]), [])


if __name__ == "__main__":
    unittest.main()
