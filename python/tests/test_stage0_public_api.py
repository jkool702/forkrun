"""Stage 0 through the PUBLIC API, not the internal result stream.

The review was explicit: "visible" must mean visible through the public
API, including values already yielded by stream() -- not merely copied
into an internal results descriptor.

That distinction is what the interim policy turned on. A post-hoc
exception cannot retract a value stream() has already handed the caller,
so before the fix the only sound interim policy was to disable the
cleanroom streaming envelope outright. Once publication is post-commit,
every yielded value belongs to a committed batch, and that argument no
longer applies.

These tests exercise forkrun.stream() and forkrun.map() end to end with
worker deaths and recovery active, and assert the values the CALLER sees.

Run: make -f Makefile.substrate python-substrate && cd python/tests
     python3 -m unittest test_stage0_public_api
"""

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(_ROOT, "python"))
sys.path.insert(0, _HERE)

import forkrun  # noqa: E402
from forkrun._udf import helper_path  # noqa: E402

UDF_SRC = "def up(b):\n    return b.upper()\n"
BATCHES = 6

# forkrun's own plugin fixture always dies, so recovery is exercised
# without needing the fault hooks.
PLUGIN = os.path.join(_HERE, "plugins", "test_plugin_v1.so")


def _available():
    try:
        return bool(helper_path()) and os.path.exists(
            os.path.join(_ROOT, "python", "forkrun", "_forkrun_cleanroom"))
    except Exception:
        return False


@unittest.skipUnless(_available(), "udf helper / launcher not built")
class TestStage0PublicAPI(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = self._tmp.name
        with open(os.path.join(self.d, "px_udf.py"), "w") as fh:
            fh.write(UDF_SRC)
        self.src = os.path.join(self.d, "in.txt")
        with open(self.src, "w") as fh:
            fh.writelines("line%06d\n" % i for i in range(BATCHES))
        # The launcher's UDF root set is derived by scanning sys.path for
        # the module file WITHOUT importing it, so the fixture only has to
        # be importable here -- which is also how a real user's UDF is
        # reachable.
        sys.path.insert(0, self.d)
        self.addCleanup(sys.path.remove, self.d)

    def tearDown(self):
        self._tmp.cleanup()

    def _set_env(self, **kv):
        old = {}
        for k, v in kv.items():
            old[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return old

    def _restore(self, old):
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # -- the two properties, observed by the caller --------------------

    def test_stream_never_yields_an_uncommitted_value(self):
        """Deaths before commit, so every attempt's record is rolled back.
        Whatever stream() hands the caller must be a COMMITTED result: no
        value from an abandoned attempt may appear.
        """
        old = self._set_env(FORKRUN_CLEANROOM="1", FORKRUN_TEST_DIE_BEFORE_ACK="1")
        try:
            got = []
            for rec in forkrun.stream(
                    "px_udf:up", self.src, streaming=True,
                    mode="udf", workers=1, nodes=1, output="bytes"):
                got.append(rec)
        finally:
            self._restore(old)

        # The batch commits nowhere (every attempt dies), so the caller
        # must see terminal outcomes only -- never a DATA value.
        data = [g for g in got if g]
        self.assertEqual(
            [], data,
            "stream() yielded values that no transaction committed: %r"
            % (data[:5],))

    def test_stream_delivers_committed_values_exactly_once(self):
        """Deaths AFTER commit: the value is committed, so the caller must
        receive it exactly once. A stranding bug shows up here as a
        missing or duplicated value."""
        old = self._set_env(FORKRUN_CLEANROOM="1", FORKRUN_TEST_DIE_BEFORE_NOTIFY="1")
        try:
            got = [rec for rec in forkrun.stream(
                "px_udf:up", self.src, streaming=True,
                mode="udf", workers=1, nodes=1, output="bytes")]
        finally:
            self._restore(old)

        values = [g for g in got if g]
        self.assertTrue(values, "the caller received no committed values")
        # Batch size is the caller's choice, so record count is not
        # BATCHES -- what must hold is that every input line arrives
        # exactly once, in order, with nothing lost or duplicated. A
        # stranding bug loses a record; a duplicate-publication bug
        # repeats one. Concatenating catches both, and a framing error
        # shows up as mangled or reordered lines.
        joined = b"".join(values).decode()
        self.assertEqual("".join("LINE%06d\n" % i for i in range(BATCHES)),
                         joined,
                         "the caller did not receive every input exactly "
                         "once, in order (got %d bytes)" % len(joined))

    def test_map_returns_only_committed_results(self):
        """Materialized map() under the same fault: the collection is
        returned atomically, so it must contain no abandoned result."""
        old = self._set_env(FORKRUN_CLEANROOM="1", FORKRUN_TEST_DIE_BEFORE_ACK="1")
        try:
            res = forkrun.map("px_udf:up", self.src, mode="udf",
                              workers=1, nodes=1, output="bytes")
        finally:
            self._restore(old)
        payload = list(res)
        self.assertEqual(
            [], [p for p in payload if p],
            "map() returned values no transaction committed: %r"
            % (payload[:5],))


if __name__ == "__main__":
    unittest.main()