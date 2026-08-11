import unittest
from unittest import mock

import src.server as s


class DeliveryPreflightTest(unittest.TestCase):
    def _project(self):
        timeline = mock.Mock()
        timeline.GetName.return_value = "IG Reel"
        timeline.GetUniqueId.return_value = "timeline-1"
        timeline.GetStartFrame.return_value = 86400
        timeline.GetEndFrame.return_value = 86520
        timeline.GetSetting.side_effect = lambda key: {
            "timelineResolutionWidth": "1080",
            "timelineResolutionHeight": "1920",
            "timelineFrameRate": "30",
        }.get(key)
        project = mock.Mock()
        project.GetName.return_value = "Post"
        project.GetCurrentTimeline.return_value = timeline
        return project, timeline

    def test_ready_report_combines_inventory_target_and_duration(self):
        project, timeline = self._project()
        inventory = {"success": True, "count": 1, "tracks": [], "warnings": [], "items": [
            {"timeline_item_id": "item-1", "file_path": "D:/clip.mov", "online_status": "Online"}
        ]}
        target = {"target": "h264_vertical_1080_web", "qc_spec": {"video": {"width": 1080, "height": 1920}}, "loudness_target": None}
        with mock.patch.object(s, "_timeline_list_items_detailed", return_value=inventory), \
             mock.patch.object(s, "_resolve_delivery_target_live", return_value=(target, None)):
            out = s._render_delivery_preflight(project, {"profile": "instagram_reels"})

        self.assertTrue(out["ready"], out)
        self.assertEqual(out["timeline"]["duration_frames"], 120)
        self.assertEqual(out["timeline"]["duration_seconds"], 4.0)
        self.assertEqual(out["delivery"]["target"], "h264_vertical_1080_web")
        self.assertEqual(out["inventory"]["count"], 1)

    def test_offline_media_and_wrong_canvas_are_blockers(self):
        project, timeline = self._project()
        timeline.GetSetting.side_effect = lambda key: {
            "timelineResolutionWidth": "1920", "timelineResolutionHeight": "1080", "timelineFrameRate": "30"
        }.get(key)
        inventory = {"success": True, "count": 1, "tracks": [], "warnings": [], "items": [
            {"timeline_item_id": "item-1", "file_path": "D:/clip.mov", "online_status": "Offline"}
        ]}
        target = {"target": "h264_vertical_1080_web", "qc_spec": {"video": {"width": 1080, "height": 1920}}, "loudness_target": None}
        with mock.patch.object(s, "_timeline_list_items_detailed", return_value=inventory), \
             mock.patch.object(s, "_resolve_delivery_target_live", return_value=(target, None)):
            out = s._render_delivery_preflight(project, {"profile": "instagram_reels"})

        self.assertFalse(out["ready"])
        self.assertEqual([row["code"] for row in out["blockers"]], ["DELIVERY_CANVAS_MISMATCH", "OFFLINE_MEDIA"])

    def test_unknown_profile_returns_delivery_target_error(self):
        project, _ = self._project()
        error = {"error": {"code": "UNKNOWN_DELIVERY_TARGET", "category": "invalid_input"}}
        with mock.patch.object(s, "_timeline_list_items_detailed", return_value={"success": True, "count": 0, "items": [], "tracks": [], "warnings": []}), \
             mock.patch.object(s, "_resolve_delivery_target_live", return_value=(None, error)):
            out = s._render_delivery_preflight(project, {"profile": "not-real"})
        self.assertEqual(out, error)


if __name__ == "__main__":
    unittest.main()
