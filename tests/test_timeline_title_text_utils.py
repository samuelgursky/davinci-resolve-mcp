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


class GetTitleTextServerHelperTest(unittest.TestCase):
    """Offline coverage of server._timeline_get_title_text — the read twin of set_title_text."""

    class _Item:
        def __init__(self, props):
            self._props = props

        def GetProperty(self, key=None):
            if key is None:
                return dict(self._props)
            return self._props.get(key)

        def GetUniqueId(self):
            return "item-1"

        def GetName(self):
            return "Title 1"

    class _Timeline:
        def __init__(self, item):
            self._item = item

        def GetTrackCount(self, track_type):
            return 1 if track_type == "video" else 0

        def GetItemListInTrack(self, track_type, index):
            return [self._item] if track_type == "video" else []

    def _get(self, props, params=None):
        from src.server import _timeline_get_title_text

        item = self._Item(props)
        tl = self._Timeline(item)
        p = {"clip_id": "item-1"}
        p.update(params or {})
        return _timeline_get_title_text(tl, p)

    def test_reads_styled_text_via_heuristic_keys(self):
        result = self._get({"Styled Text": "LOWER THIRD", "ZoomX": 1.0})
        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "LOWER THIRD")
        self.assertEqual(result["property_key"], "Styled Text")

    def test_explicit_property_key_wins(self):
        result = self._get(
            {"Styled Text": "WRONG", "Custom": "RIGHT"},
            {"property_key": "Custom"},
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "RIGHT")
        self.assertEqual(result["property_key"], "Custom")

    def test_no_text_keys_reports_not_found(self):
        result = self._get({"ZoomX": 1.0, "Opacity": 100.0})
        self.assertFalse(result["success"])
        self.assertIsNone(result["text"])
