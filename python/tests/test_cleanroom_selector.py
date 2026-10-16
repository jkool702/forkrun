"""WO-CR-ROI-2 Phase C: per-route cleanroom activation.

`FORKRUN_CLEANROOM` was effectively boolean: any non-false value enabled
EVERY eligible route at once. Five envelopes with different dispatch,
different streaming behaviour and different levels of proof were
therefore coupled by one flag.

These tests pin the selector's grammar and, more importantly, its
INDEPENDENCE properties -- that enabling one route does not enable
another, and that a selector can never widen past the eligibility
predicate.

The "unset default" property is asserted here explicitly, because
Phase C deliberately does NOT change the default: that is Phase D's
decision, and it must not creep in unnoticed.
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
if os.path.join(_ROOT, "python") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "python"))

import forkrun                                    # noqa: E402

R = sys.modules["forkrun.run"]


class TestSelectorGrammar(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("FORKRUN_CLEANROOM", None)
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._saved

    # -- unset default: UNCHANGED in Phase C -----------------------

    def test_unset_default_is_map_plugin_only(self):
        """Phase D moved the default: map(plugin) ON, everything else off.

        The one route is the whole point. A default that enabled
        "the cleanroom" would silently change udf, spawn and both stream
        routes, which have different proof behind them.
        """
        os.environ.pop("FORKRUN_CLEANROOM", None)
        enabled, routes, explicit = R._cleanroom_selected_routes()
        self.assertTrue(enabled, "map(plugin) is default-on")
        self.assertEqual(frozenset(("map-plugin",)), routes,
                         "the default must be exactly ONE route")
        self.assertFalse(explicit,
                         "an unset variable is still NOT explicit -- this "
                         "is what keeps the decline warning quiet")

    def test_unset_default_enables_no_other_route(self):
        os.environ.pop("FORKRUN_CLEANROOM", None)
        self.assertTrue(R._cleanroom_route_enabled("map", "plugin"))
        for entry, mode in (("map", "udf"), ("map", "spawn"),
                            ("stream", "plugin"), ("stream", "udf"),
                            ("stream", "spawn")):
            with self.subTest(route="%s-%s" % (entry, mode)):
                self.assertFalse(
                    R._cleanroom_route_enabled(entry, mode),
                    "only map-plugin may be on by default; %s-%s must "
                    "stay opt-in" % (entry, mode))

    def test_unset_default_does_not_raise(self):
        """A default that raised on some host would be catastrophic."""
        os.environ.pop("FORKRUN_CLEANROOM", None)
        R._cleanroom_selected_routes()   # must not raise

    def test_explicit_off_never_enables_anything(self):
        for val in ("0", "", "no", "off", "false", "OFF", " False "):
            with self.subTest(value=val):
                os.environ["FORKRUN_CLEANROOM"] = val
                enabled, routes, explicit = R._cleanroom_selected_routes()
                self.assertFalse(enabled)
                self.assertTrue(explicit, "an explicit off IS explicit")
                for entry in ("map", "stream"):
                    for mode in ("plugin", "udf", "spawn"):
                        self.assertFalse(
                            R._cleanroom_route_enabled(entry, mode))

    def test_stream_spawn_is_not_selectable(self):
        """stream(spawn) has no dispatch, so it must not be selectable.

        Asserted as the USER sees it: naming the route in the env var is
        an error. If this route were quietly accepted, the call would
        silently take the in-process path and the user would believe they
        had selected something.
        """
        os.environ["FORKRUN_CLEANROOM"] = "stream-spawn"
        with self.assertRaises(ValueError) as cm:
            R._cleanroom_selected_routes()
        self.assertIn("unknown route", str(cm.exception))

    def test_legacy_all_does_not_enable_an_unserved_route(self):
        """Legacy "=1" must not report a route the product cannot serve.

        "=1" used to return True for any (entry, mode) pair, so
        stream(spawn) read as enabled. That was harmless only because
        the stream predicate separately declines spawn -- i.e.
        correctness depended on two unrelated checks agreeing. The gate
        now refuses an unserved route on its own.
        """
        os.environ["FORKRUN_CLEANROOM"] = "1"
        self.assertFalse(R._cleanroom_route_enabled("stream", "spawn"))
        self.assertTrue(R._cleanroom_route_enabled("map", "spawn"),
                        "map(spawn) IS served and must stay selectable")

    def test_off_values_disable_even_the_new_default(self):
        """The false aliases, which the new default makes load-bearing.

        Before the default moved, an off value was merely a way to opt
        out. Now it is the documented way to RESTORE the old behaviour,
        so it must keep working exactly as it did.
        """
        for val in ("0", "no", "off", "false", "", "OFF", " False "):
            with self.subTest(value=val):
                os.environ["FORKRUN_CLEANROOM"] = val
                enabled, routes, explicit = R._cleanroom_selected_routes()
                self.assertFalse(enabled, "%r must disable" % val)
                self.assertTrue(explicit)
                self.assertFalse(R._cleanroom_route_enabled("map", "plugin"),
                                 "%r must disable the DEFAULT route too"
                                 % val)

    def test_legacy_one_preserves_every_eligible_route(self):
        for val in ("1", "yes", "on", "true", "all"):
            with self.subTest(value=val):
                os.environ["FORKRUN_CLEANROOM"] = val
                enabled, routes, explicit = R._cleanroom_selected_routes()
                self.assertTrue(enabled)
                self.assertIsNone(routes,
                                  "legacy =1 must keep routes unrestricted")
                for entry in ("map", "stream"):
                    for mode in ("plugin", "udf", "spawn"):
                        if mode == "spawn" and entry == "stream":
                            continue          # unserved; see
                                                 # test_legacy_all_does_not_
                                                 # enable_an_unserved_route
                        self.assertTrue(
                            R._cleanroom_route_enabled(entry, mode),
                            "legacy behaviour must survive the selector")

    def test_individual_route_selector_enables_only_that_route(self):
        os.environ["FORKRUN_CLEANROOM"] = "map-plugin"
        self.assertTrue(R._cleanroom_route_enabled("map", "plugin"))
        for entry, mode in (("stream", "plugin"), ("map", "udf"),
                            ("map", "spawn"), ("stream", "udf"),
                            ("stream", "spawn")):
            with self.subTest(route="%s-%s" % (entry, mode)):
                self.assertFalse(
                    R._cleanroom_route_enabled(entry, mode),
                    "enabling map-plugin must NOT enable %s-%s"
                    % (entry, mode))

    def test_comma_separated_subset(self):
        os.environ["FORKRUN_CLEANROOM"] = "map-plugin, map-udf"
        self.assertTrue(R._cleanroom_route_enabled("map", "plugin"))
        self.assertTrue(R._cleanroom_route_enabled("map", "udf"))
        self.assertFalse(R._cleanroom_route_enabled("map", "spawn"))
        self.assertFalse(R._cleanroom_route_enabled("stream", "plugin"))

    def test_unknown_value_raises_rather_than_enabling_everything(self):
        """The whole point of a strict parser.

        Silently treating a typo as "on" would enable every envelope --
        the exact coupling Phase C exists to remove.
        """
        for bad in ("map-plguin", "plugin", "map-python", "yes-please",
                    "map-plugin,bogus"):
            with self.subTest(value=bad):
                os.environ["FORKRUN_CLEANROOM"] = bad
                with self.assertRaises(ValueError) as cm:
                    R._cleanroom_selected_routes()
                self.assertIn("unknown route", str(cm.exception))

    def test_error_message_lists_valid_routes(self):
        os.environ["FORKRUN_CLEANROOM"] = "nonsense"
        with self.assertRaises(ValueError) as cm:
            R._cleanroom_selected_routes()
        for route in R._CLEANROOM_ROUTES:
            self.assertIn(route, str(cm.exception),
                          "the error must name every valid route")


class TestRouteNaming(unittest.TestCase):
    def test_route_identifier_uses_entry_not_just_mode(self):
        """The reason a mode-only selector is insufficient."""
        self.assertEqual("map-plugin",
                         R._cleanroom_route_for("map", "plugin"))
        self.assertEqual("stream-plugin",
                         R._cleanroom_route_for("stream", "plugin"))
        self.assertNotEqual(R._cleanroom_route_for("map", "plugin"),
                            R._cleanroom_route_for("stream", "plugin"))

    def test_unserved_route_has_no_identifier(self):
        """stream(spawn) has no dispatch, so it has no NAME.

        Found by the dispatch prober: a selector table that lists
        "stream-spawn" would let a user select a route that can never
        fire -- indistinguishable, from their side, from being ignored.
        The identifier set is derived from the served routes so the two
        cannot drift.
        """
        self.assertNotIn("stream-spawn", R._CLEANROOM_ROUTES)
        self.assertIsNone(R._cleanroom_route_for("stream", "spawn"))
        self.assertEqual("map-spawn", R._cleanroom_route_for("map", "spawn"))

    def test_every_named_route_is_selectable(self):
        """The inverse of the above, as an invariant."""
        for entry in ("map", "stream"):
            for mode in ("plugin", "udf", "spawn"):
                route = R._cleanroom_route_for(entry, mode)
                if route is not None:
                    self.assertIn(route, R._CLEANROOM_ROUTES)

    def test_non_launcher_modes_have_no_route(self):
        for mode in ("python", "splice", "", None):
            with self.subTest(mode=mode):
                self.assertIsNone(R._cleanroom_route_for("map", mode))
                self.assertIsNone(R._cleanroom_route_for("stream", mode))


class TestSelectorNeverWidens(unittest.TestCase):
    """A selector may narrow, never widen.

    It is consulted BEFORE the predicate, so the predicate remains the
    authority on whether a route is acceptable at all.
    """

    def setUp(self):
        self._saved = os.environ.get("FORKRUN_CLEANROOM")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._saved is None:
            os.environ.pop("FORKRUN_CLEANROOM", None)
        else:
            os.environ["FORKRUN_CLEANROOM"] = self._saved

    def test_selector_cannot_make_a_declined_route_eligible(self):
        """Resume is declined by the envelope; naming the route must not
        bypass that."""
        os.environ["FORKRUN_CLEANROOM"] = "map-plugin"
        # The gate says yes for map/plugin...
        self.assertTrue(R._cleanroom_route_enabled("map", "plugin"))
        # ...but the envelope still refuses resume, which is a separate
        # and later decision. Asserted directly so the two cannot be
        # confused.
        ok, why = R._cleanroom_eligible(
            __file__, "plugin", 1, "index", False, True, False,
            streaming=False, resume=__file__, checkpoint_file=None)
        self.assertFalse(ok, "resume must remain declined by the envelope")
        self.assertIn("resume", why.lower())

    def test_splittable_selector_does_not_enable_splice(self):
        os.environ["FORKRUN_CLEANROOM"] = "map-spawn"
        self.assertIsNone(R._cleanroom_route_for("map", "splice"),
                          "splice has no route; naming map-spawn must not "
                          "reach it")
        self.assertFalse(R._cleanroom_route_enabled("map", "splice"))


if __name__ == "__main__":
    unittest.main(verbosity=2)