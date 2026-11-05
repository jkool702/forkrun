"""DOCS_ALL.md must be reproducible from its canonical documents.

Added because `DOCS/DOCS_ALL.md` had no generator and no freshness
check. `release_check.check_twins()` compares CHANGELOG *headings*
against DOCS_ALL content, and it passed for a long time while six of
the sixteen embedded documents were stale by roughly 130 lines — a
heading check cannot see a body that was rewritten underneath it.

The WOUNDRY is "run the full test suite and it is green", so the test
that matters here is the one that proves the CHECK FAILS when a source
diverges. A freshness test nobody has seen fail is indistinguishable
from a freshness test that cannot fail.
"""

import os
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
_GEN = os.path.join(_ROOT, "tools", "gen_docs_all.py")
_DOCS = os.path.join(_ROOT, "DOCS")
_TARGET = os.path.join(_DOCS, "DOCS_ALL.md")


def _run(*args):
    return subprocess.run([sys.executable, _GEN] + list(args),
                          capture_output=True, text=True, timeout=600,
                          cwd=_ROOT)


class TestDocsAllGenerator(unittest.TestCase):
    def test_generator_exists_and_aggregate_is_current(self):
        self.assertTrue(os.path.exists(_GEN),
                        "tools/gen_docs_all.py is missing; DOCS_ALL.md has "
                        "no reproducible source")
        proc = _run("--check")
        self.assertEqual(
            0, proc.returncode,
            "DOCS_ALL.md is stale.\n%s\n%s\n"
            "Regenerate: python3 tools/gen_docs_all.py"
            % (proc.stdout[-1500:], proc.stderr[-1500:]))

    def test_generation_is_idempotent(self):
        """Two runs must produce identical bytes.

        Without this, a generator that embeds a timestamp or iterates a
        directory unsorted would produce a permanently-stale aggregate
        and the freshness check would be noise.
        """
        with open(_TARGET, "rb") as fh:
            before = fh.read()
        first = _run()
        self.assertEqual(0, first.returncode, first.stderr[-800:])
        with open(_TARGET, "rb") as fh:
            after_first = fh.read()
        second = _run()
        self.assertEqual(0, second.returncode, second.stderr[-800:])
        with open(_TARGET, "rb") as fh:
            after_second = fh.read()
        self.assertEqual(after_first, after_second,
                         "gen_docs_all.py is not idempotent")
        self.assertEqual(
            before, after_second,
            "regenerating an already-current aggregate changed it")

    def test_every_listed_document_exists(self):
        """A typo in the DOCUMENTS list would silently drop a document."""
        sys.path.insert(0, os.path.join(_ROOT, "tools"))
        import gen_docs_all
        for name in gen_docs_all.DOCUMENTS:
            with self.subTest(document=name):
                self.assertTrue(
                    os.path.exists(os.path.join(_DOCS, name)),
                    "%s is listed in gen_docs_all.DOCUMENTS but does not "
                    "exist" % name)

    def test_aggregate_carries_no_orphaned_content(self):
        """Every embedded section must be owned by a source document.

        This is the failure that motivated the generator: a 28-line
        W-REL5-B behavioral block existed ONLY in the aggregate, with no
        source owning it. Regenerating from sources would have deleted
        it, so it was given a home (PYTHON_BEHAVIOR.md) instead.

        The check is structural rather than a full diff: every
        `# NAME.md` marker in the aggregate must be in the generator's
        list, and every source document must be present in the
        aggregate.
        """
        with open(_TARGET, "r", encoding="utf-8") as fh:
            aggregate = fh.read()
        sys.path.insert(0, os.path.join(_ROOT, "tools"))
        import gen_docs_all
        sep = "\n" + gen_docs_all.SEPARATOR + "\n"
        # Split on the AGGREGATE separator only. Splitting on "\n# " would
        # match each source document's own H1 (they start with
        # "# NAME.md - title"), not the next embedded section.
        chunks = aggregate.split(sep)
        # chunk[0] is the leading header; the rest are "# NAME.md\n\n<body>"
        embedded = {}
        for chunk in chunks:
            head, _, rest = chunk.partition("\n")
            if not head.startswith("# ") or not rest.startswith("\n"):
                continue
            embedded[head[2:].strip()] = rest[1:]
        self.assertEqual(
            sorted(gen_docs_all.DOCUMENTS), sorted(embedded),
            "the documents embedded in DOCS_ALL.md are not exactly the "
            "generator's list; an extra section means orphaned content, "
            "a missing one means a source that never made it in")
        for name in gen_docs_all.DOCUMENTS:
            with self.subTest(document=name):
                with open(os.path.join(_DOCS, name), "r",
                          encoding="utf-8") as fh:
                    body = fh.read().rstrip("\n")
                self.assertTrue(
                    embedded.get(name, "").startswith(body[:200]),
                    "the %s section of DOCS_ALL.md does not start with its "
                    "source document" % name)

    def test_check_fails_when_a_source_diverges(self):
        """THE load-bearing test: prove the gate can go red.

        Deliberately mutates a source document, confirms --check fails,
        then restores. This is what distinguishes a freshness gate from
        a check that always passes.
        """
        probe = os.path.join(_DOCS, "ECONOMIC_IMPACT.md")
        with open(probe, "r", encoding="utf-8") as fh:
            original = fh.read()
        marker = "<!-- WO-DOCS-ALL-PROBE -->"
        try:
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write(original + "\n" + marker + "\n")
            proc = _run("--check")
            self.assertNotEqual(
                0, proc.returncode,
                "gen_docs_all.py --check PASSED after a source document "
                "changed. The freshness gate cannot detect drift, which "
                "is the exact failure this test exists to prevent.")
            self.assertIn("STALE", proc.stdout + proc.stderr,
                          "the failure should say so explicitly, not just "
                          "exit nonzero")
        finally:
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write(original)
        # And it must be green again once restored.
        self.assertEqual(0, _run("--check").returncode,
                         "check still failing after the probe was "
                         "reverted -- the generator may not be "
                         "reproducible")


if __name__ == "__main__":
    unittest.main(verbosity=2)