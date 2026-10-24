"""W-EXP-1 kill switch: `FORKRUN_NO_UDF` masks ONLY the udf capability.

Roadmap §5.3 specifies it and §5.5 requires it:

> Kill switch. `FORKRUN_NO_UDF` masks **only** the `udf` capability, and
> `udf` appears in **every** `v1_available()` return shape — including the
> `FORKRUN_NO_V1` branch, which returns all-present capabilities as `False`.
> [V] `v1_available()` has a dictionary contract with two return shapes.
> `FORKRUN_NO_UDF` must not be a "mirror of `FORKRUN_NO_V1`" in the sense of
> forcing everything `False`.

> [ ] `FORKRUN_NO_UDF=1` forces in-process and masks nothing else.

It was specified but implemented nowhere before this -- it appeared only in
the roadmap. It is enforced at `_udf.helper_path()`, the single point every
route consults, so the capability report and the routing decision cannot
disagree.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forkrun  # noqa: E402
from forkrun._bindings import v1_available  # noqa: E402
from forkrun._udf import helper_path  # noqa: E402

_UDF = "def up(batch):\n    return batch.copy()\n"


class NoUdfKillSwitch(unittest.TestCase):
    def setUp(self):
        self._had = "FORKRUN_NO_UDF" in os.environ
        self._val = os.environ.get("FORKRUN_NO_UDF")
        self.root = tempfile.mkdtemp(prefix="noudf-")
        with open(os.path.join(self.root, "noudfmod.py"), "w") as fh:
            fh.write(_UDF)
        self.src = os.path.join(self.root, "in.txt")
        with open(self.src, "w") as fh:
            fh.write("".join("line%d\n" % i for i in range(8)))
        sys.path.insert(0, self.root)
        self.addCleanup(sys.path.remove, self.root)

    def tearDown(self):
        if self._had:
            os.environ["FORKRUN_NO_UDF"] = self._val
        else:
            os.environ.pop("FORKRUN_NO_UDF", None)

    def test_kill_switch_masks_udf_only(self):
        """The load-bearing assertion: masks ONE capability, not all."""
        os.environ.pop("FORKRUN_NO_UDF", None)
        before = v1_available()

        os.environ["FORKRUN_NO_UDF"] = "1"
        try:
            after = v1_available()
            self.assertFalse(after["udf"])
            changed = [k for k in before
                       if k != "udf" and before[k] != after[k]]
            self.assertEqual(
                changed, [],
                "FORKRUN_NO_UDF must mask ONLY udf. Changed: %r" % (changed,))
        finally:
            os.environ.pop("FORKRUN_NO_UDF", None)

    def test_not_a_mirror_of_no_v1(self):
        """FORKRUN_NO_V1 forces everything False; FORKRUN_NO_UDF must not."""
        os.environ.pop("FORKRUN_NO_V1", None)
        os.environ["FORKRUN_NO_UDF"] = "1"
        udf_only = v1_available()

        os.environ["FORKRUN_NO_V1"] = "1"
        try:
            everything_off = v1_available()
            self.assertTrue(
                all(not v for v in everything_off.values()),
                "FORKRUN_NO_V1 is the all-off switch")
            self.assertFalse(
                all(not v for v in udf_only.values()),
                "FORKRUN_NO_UDF must leave real capabilities REPORTED; "
                "masking is a routing decision, not a capability lie")
        finally:
            os.environ.pop("FORKRUN_NO_V1", None)

    def test_udf_key_present_in_both_return_shapes(self):
        """Every return shape carries the key, or consumers KeyError."""
        os.environ.pop("FORKRUN_NO_V1", None)
        os.environ.pop("FORKRUN_NO_UDF", None)
        normal = v1_available()
        os.environ["FORKRUN_NO_V1"] = "1"
        try:
            all_off = v1_available()
        finally:
            os.environ.pop("FORKRUN_NO_V1", None)
        self.assertIn("udf", normal)
        self.assertIn("udf", all_off)
        self.assertEqual(set(normal), set(all_off),
                         "both shapes must agree on the key SET")

    def test_helper_path_returns_none_under_the_switch(self):
        """The enforcement point itself, independent of the capability report."""
        os.environ.pop("FORKRUN_NO_UDF", None)
        real = helper_path()
        os.environ["FORKRUN_NO_UDF"] = "1"
        self.assertIsNone(
            helper_path(),
            "helper_path() is where every route looks; if this does not "
            "return None, the switch is not enforced")

    def test_run_still_succeeds_under_the_switch(self):
        """It forces in-process. It must DEGRADE, never BREAK.

        The point of a kill switch is to be safe to set in production: a
        run with it on has to produce the same correct results by the
        in-process path, not fewer results.
        """
        os.environ["FORKRUN_NO_UDF"] = "1"
        out = forkrun.map("noudfmod:up", self.src, workers=1,
                          on_error="retry", output="bytes", lines=1)
        self.assertEqual(len(out), 8,
                         "every batch must still produce its result")
        self.assertEqual(sorted(out)[0], b"line0\n")


if __name__ == "__main__":
    unittest.main()