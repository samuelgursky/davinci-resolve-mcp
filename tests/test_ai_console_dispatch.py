"""Tests for the AI Console op dispatcher (_run_resolve_ai_op).

The dispatcher routes a {op, target, params} request from the control panel to
the right consolidated server tool. We patch the server tools so no live Resolve
is needed and assert the routing + params relaying (including the confirm-token
pass-through for the media-creating ops).
"""
import unittest

import src.server as server
import src.analysis_dashboard as dash


class AiConsoleDispatchTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig = {
            "folder": server.folder,
            "media_pool_item": server.media_pool_item,
            "project_settings": server.project_settings,
            "resolve_control": server.resolve_control,
        }

        def rec(name):
            def _fn(action, params=None):
                self.calls.append((name, action, params or {}))
                return {"success": True, "tool": name, "action": action, "params": params or {}}
            return _fn

        server.folder = rec("folder")
        server.media_pool_item = rec("media_pool_item")
        server.project_settings = rec("project_settings")
        server.resolve_control = rec("resolve_control")

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(server, name, fn)

    def test_folder_target_routes_to_folder_tool(self):
        out = dash._run_resolve_ai_op({"op": "analyze_for_slate", "target": "folder",
                                       "params": {"marker_color": "Sky"}})
        self.assertTrue(out["success"])
        self.assertEqual(self.calls[0][0], "folder")
        self.assertEqual(self.calls[0][1], "analyze_for_slate")
        self.assertEqual(self.calls[0][2]["marker_color"], "Sky")

    def test_clip_target_routes_to_media_pool_item(self):
        out = dash._run_resolve_ai_op({"op": "perform_audio_classification", "target": "clip",
                                       "params": {"clip_id": "c1"}})
        self.assertTrue(out["success"])
        self.assertEqual(self.calls[0][0], "media_pool_item")
        self.assertEqual(self.calls[0][2]["clip_id"], "c1")

    def test_clip_target_without_id_errors(self):
        out = dash._run_resolve_ai_op({"op": "analyze_for_slate", "target": "clip", "params": {}})
        self.assertFalse(out["success"])
        self.assertIn("clip_id", out["error"])
        self.assertEqual(self.calls, [])

    def test_generate_speech_routes_to_project_settings(self):
        out = dash._run_resolve_ai_op({"op": "generate_speech",
                                       "params": {"speech_generation_settings": {"TextInput": "hi"}}})
        self.assertTrue(out["success"])
        self.assertEqual(self.calls[0][0], "project_settings")
        self.assertEqual(self.calls[0][1], "generate_speech")

    def test_disable_background_tasks_routes_to_resolve_control(self):
        out = dash._run_resolve_ai_op({"op": "disable_background_tasks"})
        self.assertTrue(out["success"])
        self.assertEqual(self.calls[0][0], "resolve_control")
        self.assertEqual(self.calls[0][1], "disable_background_tasks_for_current_session")

    def test_confirm_token_passed_through(self):
        dash._run_resolve_ai_op({"op": "remove_motion_blur", "target": "folder",
                                 "params": {"deblur_option": {}, "confirm_token": "tok123"}})
        self.assertEqual(self.calls[0][2]["confirm_token"], "tok123")

    def test_unknown_op_errors(self):
        out = dash._run_resolve_ai_op({"op": "frobnicate"})
        self.assertFalse(out["success"])
        self.assertIn("unknown op", out["error"])
        self.assertEqual(self.calls, [])

    def test_missing_op_errors(self):
        out = dash._run_resolve_ai_op({})
        self.assertFalse(out["success"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
