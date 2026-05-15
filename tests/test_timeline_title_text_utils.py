import unittest

from src.utils.timeline_title_text import (
    candidate_title_property_keys,
    escape_xml_text_body,
    flatten_timeline_item_properties,
    plain_to_minimal_styled_xml,
    timeline_item_get_property_map,
)


class PropItemStub:
    def __init__(self, props):
        self._props = props

    def GetProperty(self, key=""):
        if key == "":
            return dict(self._props)
        return self._props.get(key)


class NoArgPropertyMapStub:
    def GetProperty(self, key=None):
        if key is None:
            return {"Styled Text": "<x/>", "Pan": 0.0}
        if key == "":
            return None
        return None


class TimelineTitleTextUtilsTest(unittest.TestCase):
    def test_flatten(self):
        self.assertEqual(flatten_timeline_item_properties({"a": 1}), {"a": 1})
        self.assertEqual(flatten_timeline_item_properties(None), {})

    def test_get_property_map(self):
        item = PropItemStub({"Styled Text": "<x/>", "Pan": 0.0})
        flat, err = timeline_item_get_property_map(item, lambda x: x)
        self.assertIsNone(err)
        self.assertIn("Styled Text", flat)

    def test_get_property_map_prefers_documented_no_arg_call(self):
        flat, err = timeline_item_get_property_map(NoArgPropertyMapStub(), lambda x: x)
        self.assertIsNone(err)
        self.assertIn("Styled Text", flat)

    def test_plain_to_minimal_and_escape(self):
        s = plain_to_minimal_styled_xml('a < b & c "d"')
        self.assertNotIn("< b", s)
        self.assertIn("&lt;", s)
        self.assertEqual(escape_xml_text_body("&"), "&amp;")

    def test_candidate_keys_order(self):
        flat = {
            "Pan": "0",
            "Styled Text": '<x/>',
            "Foo": "x" * 30,
        }
        keys = [r["key"] for r in candidate_title_property_keys(flat)]
        self.assertEqual(keys[0], "Styled Text")


if __name__ == "__main__":
    unittest.main()
