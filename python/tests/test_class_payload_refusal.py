"""W-EXP-1 5.5: a class reference must be DECLINED, not silently empty.

Roadmap acceptance criterion, marked [V] as unmet:

> A class reference and other unsupported callable attributes are declined
> pre-consumption by an explicit kind check, not merely undocumented — the
> resolver's `callable()` check at `_worker.py:138` admits classes.

Both resolution sites admitted them: `_worker.py` used `callable(fn)`, and
`fr_udf.c` used `PyCallable_Check(fn)`. Both are true of a class.

The failure this caused was worse than an error. A class called with a
batch CONSTRUCTS an instance and returns it; the instance is not bytes, so
the result was dropped and `map()` returned `[]` — indistinguishable from
"the input matched no records". A wiring mistake reported as an empty
result gives the user no reason to doubt the data.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import forkrun  # noqa: E402


# Payload fixtures live in the UDF root, not in this test module, because
# the string form re-imports the leaf module fresh on every resolution
# (W-REL6-3.1 freshness rule).
_UDIF = '''\
class Callable_:
    """A class: callable, so `callable()` used to admit it."""

    def __init__(self, batch=None):
        self.batch = batch

    def __call__(self, batch):
        return batch.copy()


class Plain:
    """A class whose instances are not callable either."""

    def __init__(self, batch=None):
        self.batch = batch


def up(batch):
    return batch.copy()


NOT_CALLABLE = 42
'''


class ClassReferenceDeclined(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="classref-")
        with open(os.path.join(self.root, "clsmod.py"), "w") as fh:
            fh.write(_UDIF)
        self.src = os.path.join(self.root, "src.txt")
        with open(self.src, "w") as fh:
            for i in range(8):
                fh.write("line%d\n" % i)
        # The leaf module must be importable for the string form to
        # resolve -- which is also how a real user's UDF is reachable.
        sys.path.insert(0, self.root)
        self.addCleanup(sys.path.remove, self.root)

    def test_class_reference_is_declined_pre_consumption(self):
        with self.assertRaises(TypeError) as cm:
            forkrun.map("clsmod:Plain", self.src, workers=1,
                        on_error="retry")
        msg = str(cm.exception)
        self.assertIn("class", msg.lower())
        # The message must NAME what resolved and to what, or the user
        # cannot tell which attribute of which module was wrong.
        self.assertIn("clsmod", msg)
        self.assertIn("Plain", msg)

    def test_class_with_callable_instances_is_also_declined(self):
        """A class whose instances ARE callable is still a class.

        Checking "does calling it return something" would be worse than
        useless here; the kind check must be on the object itself.
        """
        with self.assertRaises(TypeError):
            forkrun.map("clsmod:Callable_", self.src, workers=1,
                        on_error="retry")

    def test_non_callable_attribute_is_declined(self):
        with self.assertRaises(TypeError):
            forkrun.map("clsmod:NOT_CALLABLE", self.src, workers=1,
                        on_error="retry")

    def test_module_level_function_still_resolves(self):
        """The negative control: the fix must not reject valid payloads."""
        out = forkrun.map("clsmod:up", self.src, workers=1,
                          on_error="retry", output="bytes")
        self.assertEqual(len(out), 8, "every batch must produce a result")
        self.assertEqual(sorted(out)[0], b"line0\n")

    def test_callable_instance_still_accepted_directly(self):
        """Only the STRING form is kind-checked.

        Passing a callable directly is a documented, supported payload
        form and the kind check must not leak into it — otherwise the
        fix would break `forkrun.map(SomeClass(), ...)`.
        """
        import clsmod
        inst = clsmod.Callable_()
        out = forkrun.map(inst, self.src, workers=1, on_error="retry",
                          output="bytes")
        self.assertEqual(len(out), 8)

    def test_refusal_happens_before_input_is_consumed(self):
        """Pre-consumption matters: a declined payload must cost nothing.

        Asserted by giving the run a source that does not exist. If
        resolution happened after the source was opened, this would fail
        with a file error instead of the kind-check TypeError.
        """
        missing = os.path.join(self.root, "does-not-exist.txt")
        with self.assertRaises(TypeError) as cm:
            forkrun.map("clsmod:Plain", missing, workers=1,
                        on_error="retry")
        self.assertIn("class", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()