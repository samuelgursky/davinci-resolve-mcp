"""The two failures `hasattr` used to hide on Resolve API objects.

`hasattr` is a constant True on a Resolve object and `getattr` returns None for
names that do not exist — measured on Studio 19.1.3.7, 42 checks, recorded in
`api_truth`. `FabricatingObject` below reproduces that exactly, so these tests
fail against the old code and pass against `resolve_probe`.

The granular server's AI tools are tested here too. They are the surfaces the
version guards protect, and they had a second way of reporting a build problem
as a success: Resolve's AI methods return the reason as a STRING when an Extras
pack is missing, and a non-empty string is truthy.
"""

import unittest

from src.granular.common import _ai_result, _ai_result_payload
from src.utils.resolve_probe import api_constant, has_method


class FabricatingObject:
    """A Resolve API object as measured: hasattr yes to everything.

    `__getattr__` is what produces that — Python falls back to it for any name
    not found normally, and returning None from it makes `hasattr` True (no
    AttributeError raised) while `getattr` hands back a None nobody can call.
    """

    EXPORT_AAF = "known-constant-value"

    def GetName(self):
        return "real"

    def __getattr__(self, name):
        return None


class HasattrIsUselessHereTest(unittest.TestCase):
    def test_the_premise_holds_hasattr_says_yes_to_an_invented_name(self):
        """If this ever fails, the rest of this file is testing nothing."""
        obj = FabricatingObject()
        self.assertTrue(hasattr(obj, "TotallyMadeUpMethod_xyz123"))
        self.assertIsNone(getattr(obj, "TotallyMadeUpMethod_xyz123"))

    def test_has_method_separates_real_from_fabricated(self):
        obj = FabricatingObject()
        self.assertTrue(has_method(obj, "GetName"))
        self.assertFalse(has_method(obj, "RemoveMotionBlur"))

    def test_has_method_tolerates_a_missing_handle(self):
        """Callers ask "is this reachable"; a None handle is one way it is not."""
        self.assertFalse(has_method(None, "GetName"))
        self.assertFalse(has_method(FabricatingObject(), ""))


class ApiConstantTest(unittest.TestCase):
    """The export-type bug: `getattr(r, n) if hasattr(r, n) else n`.

    hasattr won every time, so a build without the constant handed `Export()` a
    None instead of the string name the author's fallback was written to pass
    through — no exception, no refusal, just a None travelling onward.
    """

    def test_a_known_constant_resolves_to_its_value(self):
        self.assertEqual(
            api_constant(FabricatingObject(), "EXPORT_AAF", "EXPORT_AAF"),
            "known-constant-value",
        )

    def test_an_unknown_constant_falls_back_instead_of_yielding_none(self):
        self.assertEqual(
            api_constant(FabricatingObject(), "EXPORT_OTIO", "EXPORT_OTIO"),
            "EXPORT_OTIO",
        )

    def test_a_falsy_constant_is_a_value_not_an_absence(self):
        """`EXPORT_AAF` really is 0.0 on Studio 19.1.3.7 (checked live).

        So the fallback has to key on `is None`, not on truthiness — a
        `value or default` here would silently swap the real constant for its
        own name and take the AAF export path with a string.
        """
        class Zero:
            EXPORT_AAF = 0.0

            def __getattr__(self, name):
                return None

        self.assertEqual(api_constant(Zero(), "EXPORT_AAF", "EXPORT_AAF"), 0.0)

    def test_the_old_form_would_have_returned_none(self):
        """Pins the regression this replaced, so it cannot quietly come back."""
        obj = FabricatingObject()
        old = getattr(obj, "EXPORT_OTIO") if hasattr(obj, "EXPORT_OTIO") else "EXPORT_OTIO"
        self.assertIsNone(old)
        self.assertIsNotNone(api_constant(obj, "EXPORT_OTIO", "EXPORT_OTIO"))


class AiResultTest(unittest.TestCase):
    """A missing Extras pack comes back as prose, and prose is truthy."""

    MISSING_PACK = "Required package 'AI Intellisearch - Faster' is not installed."

    def test_an_error_string_is_a_failure_not_a_success(self):
        self.assertEqual(_ai_result(self.MISSING_PACK), (False, self.MISSING_PACK))
        self.assertTrue(bool(self.MISSING_PACK), "the trap: bool() says True")

    def test_the_payload_carries_resolves_own_reason(self):
        payload = _ai_result_payload(self.MISSING_PACK)
        self.assertEqual(payload["success"], False)
        self.assertEqual(payload["error"], self.MISSING_PACK)

    def test_a_plain_false_stays_a_failure_with_no_invented_reason(self):
        """AnalyzeForSlate reports the same condition as a bare False."""
        self.assertEqual(_ai_result_payload(False), {"success": False})

    def test_a_real_return_still_succeeds(self):
        self.assertEqual(_ai_result_payload(True), {"success": True})
        ok, message = _ai_result(FabricatingObject())
        self.assertTrue(ok)
        self.assertIsNone(message)

    def test_an_empty_string_reports_failure_without_a_hollow_message(self):
        self.assertEqual(_ai_result_payload(""), {"success": False})


if __name__ == "__main__":
    unittest.main()
