"""Tests for the native-vs-bridge differential comparison.

The module had no coverage at all, and the gap showed. Running it live on Studio
19.1.3.7 it reported `resolve.GetCurrentPage` as a `value_mismatch` — bridge
`edit`, native `deliver` — on every run that did not happen to start on the
Deliver page, and reported nothing on the runs that did. The cause was not the
transport: the harness's own render probes navigate Resolve to Deliver, and the
bridge pass runs before the native pass, so the native pass read a page the
bridge pass had moved. Read at the same instant the two transports always agreed.

A harness that cries wolf on a clean bridge is worse than no harness, because the
next person either chases a phantom or learns to ignore the output. But excusing
the page unconditionally would discard a real signal — a bridge returning the
wrong page is precisely the bug this exists to catch. So the fix is conditional,
and these tests pin both halves of the condition: excused when a pass proves the
page moved, still reported when both passes held still.
"""
from __future__ import annotations

import unittest

from src.utils import bridge_differential as bd


def returned(value, type_name):
    """A probe result in `probe_one`'s shape."""
    return {"outcome": "returned", "value": value, "type": type_name}


def pass_with_page(before, after, **probes):
    """One transport's probe results, with the page bookkeeping attached."""
    results = dict(probes)
    results[bd.PASS_META_KEY] = {
        "page_before": before,
        "page_after": after,
        "page_stable": before is not None and before == after,
    }
    return results


class PageStabilityTests(unittest.TestCase):
    """`GetCurrentPage` is compared by value only when both passes held still."""

    def test_moving_page_excuses_the_value_difference(self):
        """The live false positive: the harness moved the page between passes."""
        native = pass_with_page("edit", "deliver",
                                **{"resolve.GetCurrentPage": returned("deliver", "str")})
        bridge = pass_with_page("edit", "deliver",
                                **{"resolve.GetCurrentPage": returned("edit", "str")})
        report = bd.compare(native, bridge)
        self.assertEqual(report["differences"], [])
        self.assertTrue(report["identical"])
        self.assertFalse(report["page_compared_by_value"])

    def test_a_stable_page_that_disagrees_is_still_a_difference(self):
        """The signal must survive the fix, or the fix is just a mute button."""
        native = pass_with_page("edit", "edit",
                                **{"resolve.GetCurrentPage": returned("edit", "str")})
        bridge = pass_with_page("edit", "edit",
                                **{"resolve.GetCurrentPage": returned("color", "str")})
        report = bd.compare(native, bridge)
        self.assertEqual(len(report["differences"]), 1)
        self.assertEqual(report["differences"][0]["kind"], "value_mismatch")
        self.assertEqual(report["differences"][0]["key"], "resolve.GetCurrentPage")
        self.assertTrue(report["page_compared_by_value"])

    def test_one_unstable_pass_is_enough_to_excuse(self):
        """Both passes must hold still; one moving pass makes the pair unusable."""
        native = pass_with_page("edit", "edit",
                                **{"resolve.GetCurrentPage": returned("edit", "str")})
        bridge = pass_with_page("edit", "deliver",
                                **{"resolve.GetCurrentPage": returned("color", "str")})
        report = bd.compare(native, bridge)
        self.assertEqual(report["differences"], [])
        self.assertFalse(report["page_compared_by_value"])

    def test_unknown_page_does_not_count_as_stable(self):
        """An unreadable page is an unknown, and an unknown must not enable the
        value comparison — that would restore the false positive silently."""
        native = pass_with_page(None, None,
                                **{"resolve.GetCurrentPage": returned("edit", "str")})
        bridge = pass_with_page(None, None,
                                **{"resolve.GetCurrentPage": returned("color", "str")})
        report = bd.compare(native, bridge)
        self.assertEqual(report["differences"], [])
        self.assertFalse(report["page_compared_by_value"])

    def test_type_mismatch_survives_even_while_excused(self):
        """The value is excused; returning a different *kind* of thing is not."""
        native = pass_with_page("edit", "deliver",
                                **{"resolve.GetCurrentPage": returned("deliver", "str")})
        bridge = pass_with_page("edit", "deliver",
                                **{"resolve.GetCurrentPage": returned(None, "NoneType")})
        report = bd.compare(native, bridge)
        self.assertEqual(len(report["differences"]), 1)
        self.assertEqual(report["differences"][0]["kind"], "order_sensitive_type_mismatch")

    def test_other_methods_are_unaffected_by_a_moving_page(self):
        """Only the order-sensitive method is excused, not the whole pass."""
        native = pass_with_page("edit", "deliver",
                                **{"project.GetName": returned("Alpha", "str")})
        bridge = pass_with_page("edit", "deliver",
                                **{"project.GetName": returned("Beta", "str")})
        report = bd.compare(native, bridge)
        self.assertEqual(len(report["differences"]), 1)
        self.assertEqual(report["differences"][0]["kind"], "value_mismatch")


class PassMetaTests(unittest.TestCase):
    """The bookkeeping key must never read as a probe result."""

    def test_meta_key_is_not_a_difference_and_is_not_counted(self):
        native = pass_with_page("edit", "edit", **{"project.GetName": returned("A", "str")})
        bridge = pass_with_page("color", "color", **{"project.GetName": returned("A", "str")})
        report = bd.compare(native, bridge)
        # The two passes carry *different* meta dicts; if it were compared as a
        # probe this would be a difference.
        self.assertEqual(report["differences"], [])
        self.assertEqual(report["compared"], 1)

    def test_meta_key_is_underscore_prefixed(self):
        """`compare` skips on the underscore, so the constant must keep it."""
        self.assertTrue(bd.PASS_META_KEY.startswith("_"))


class CurrentPageReadTests(unittest.TestCase):
    def test_returns_the_page(self):
        class R:
            def GetCurrentPage(self):
                return "edit"
        self.assertEqual(bd._current_page(R()), "edit")

    def test_a_raising_call_is_unknown_not_fatal(self):
        class R:
            def GetCurrentPage(self):
                raise RuntimeError("no")
        self.assertIsNone(bd._current_page(R()))

    def test_a_non_string_is_unknown(self):
        """Resolve answers None for things that do not exist rather than raising,
        so a non-string is 'could not tell', not a page named False."""
        class R:
            def GetCurrentPage(self):
                return False
        self.assertIsNone(bd._current_page(R()))


class RunProbesMetaTests(unittest.TestCase):
    def test_run_probes_records_the_page_either_side(self):
        pages = iter(["edit", "deliver"])

        class R:
            def GetCurrentPage(self):
                return next(pages)

        results = bd.run_probes(R(), [])
        meta = results[bd.PASS_META_KEY]
        self.assertEqual(meta["page_before"], "edit")
        self.assertEqual(meta["page_after"], "deliver")
        self.assertFalse(meta["page_stable"])

    def test_a_still_page_is_recorded_as_stable(self):
        class R:
            def GetCurrentPage(self):
                return "edit"

        meta = bd.run_probes(R(), [])[bd.PASS_META_KEY]
        self.assertTrue(meta["page_stable"])


if __name__ == "__main__":
    unittest.main()
