import unittest
from unittest.mock import patch

from src.server import (
    _annotation_capabilities,
    _copy_annotations,
    _export_review_report,
    _normalize_marker_payload_action,
    _probe_annotations,
    _sync_marker_custom_data,
)


class AnnotationTargetStub:
    def __init__(self, name="Target"):
        self.name = name
        self.markers = {
            12: {
                "color": "Blue",
                "name": "Review",
                "note": "Check this",
                "duration": 2,
                "customData": "review-12",
            }
        }
        self.flags = ["Blue"]
        self.clip_color = "Blue"
        self.updated_custom_data = {}

    def GetMarkers(self):
        return dict(self.markers)

    def AddMarker(self, frame, color, name, note, duration, custom_data=""):
        self.markers[frame] = {
            "color": color,
            "name": name,
            "note": note,
            "duration": duration,
            "customData": custom_data,
        }
        return True

    def UpdateMarkerCustomData(self, frame, custom_data):
        self.updated_custom_data[frame] = custom_data
        if frame in self.markers:
            self.markers[frame]["customData"] = custom_data
        return True

    def DeleteMarkersByColor(self, color):
        self.markers.clear()
        return True

    def GetFlagList(self):
        return list(self.flags)

    def AddFlag(self, color):
        self.flags.append(color)
        return True

    def ClearFlags(self, color):
        self.flags.clear()
        return True

    def GetClipColor(self):
        return self.clip_color

    def SetClipColor(self, color):
        self.clip_color = color
        return True

    def ClearClipColor(self):
        self.clip_color = None
        return True

    def GetUniqueId(self):
        return f"id-{self.name}"

    def GetName(self):
        return self.name


class TimelineStub(AnnotationTargetStub):
    def __init__(self):
        super().__init__("Timeline")
        self.current_item = None

    def GetSetting(self, name):
        if name == "timelineFrameRate":
            return "24"
        return ""

    def GetCurrentTimecode(self):
        return "01:00:00:12"

    def GetCurrentVideoItem(self):
        return self.current_item


class ReviewAnnotationProbeTest(unittest.TestCase):
    def test_annotation_capabilities_lists_scopes_and_aliases(self):
        capabilities = _annotation_capabilities()

        self.assertTrue(capabilities["scopes"]["timeline"]["markers"])
        self.assertTrue(capabilities["scopes"]["timeline_item"]["flags"])
        self.assertIn("frameId", capabilities["frame_aliases"])

    def test_normalize_marker_payload_accepts_aliases(self):
        result = _normalize_marker_payload_action(
            TimelineStub(),
            {"frameId": "24", "color": "green", "label": "QC", "comment": "Looks good", "customData": "qc-24"},
        )

        self.assertEqual(result["marker"]["frame"], 24)
        self.assertEqual(result["marker"]["color"], "Green")
        self.assertEqual(result["marker"]["name"], "QC")
        self.assertEqual(result["marker"]["custom_data"], "qc-24")

    def test_sync_marker_custom_data_updates_timeline_marker(self):
        timeline = TimelineStub()
        result = _sync_marker_custom_data(timeline, {"scope": "timeline", "frame": 12, "custom_data": "updated"})

        self.assertTrue(result["success"])
        self.assertEqual(timeline.updated_custom_data[12], "updated")

    def test_copy_annotations_from_timeline_to_timeline_item(self):
        timeline = TimelineStub()
        target = AnnotationTargetStub("Item")

        with patch("src.server._get_item", return_value=(timeline, target, None)):
            result = _copy_annotations(
                timeline,
                {"source": {"scope": "timeline"}, "target": {"scope": "timeline_item"}},
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["copied"], 1)
        self.assertEqual(target.markers[12]["customData"], "review-12")
        self.assertIn("Blue", target.flags)

    def test_probe_annotations_includes_current_item_and_media_pool_item(self):
        timeline = TimelineStub()
        item = AnnotationTargetStub("Item")
        media = AnnotationTargetStub("Media")
        item.GetMediaPoolItem = lambda: media
        timeline.current_item = item

        result = _probe_annotations(timeline, {})

        self.assertEqual(result["count"], 3)
        self.assertEqual([scope["scope"] for scope in result["scopes"]], ["timeline", "timeline_item", "media_pool_item"])

    def test_export_review_report_is_read_only_shape(self):
        report = _export_review_report(TimelineStub(), {"title": "Daily Review"})

        self.assertEqual(report["title"], "Daily Review")
        self.assertIn("generated_at", report)
        self.assertIn("capabilities", report)
        self.assertEqual(report["annotations"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
