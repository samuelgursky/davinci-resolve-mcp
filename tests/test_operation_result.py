"""Unit and integration tests for Structured Operation Results envelope.

Tests cover:
1. Standard envelope generation across success, failed, blocked, and partial states.
2. Readback verification and contradiction extraction.
3. Change summary normalization (items added, moved, deleted, metric deltas).
4. Envelope modes (dual, pure, legacy) and per-request overrides.
5. Server tool integration and backward compatibility.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest import mock

from src.utils.operation_result import (
    build_operation_envelope,
    clean_result_payload,
    extract_changes,
    extract_verification,
    extract_warnings,
    get_envelope_mode,
    is_binary_or_mcp_content,
    new_execution_id,
    normalize_status,
    set_envelope_mode,
)
from src.utils.readback import as_verification_dict
from src import server


class OperationResultUnitTests(unittest.TestCase):
    def setUp(self):
        self.original_mode = get_envelope_mode()
        set_envelope_mode("dual")

    def tearDown(self):
        set_envelope_mode(self.original_mode)

    def test_new_execution_id_format(self):
        eid = new_execution_id()
        self.assertTrue(eid.startswith("exec_"))
        self.assertEqual(len(eid), 17)  # "exec_" (5) + 12 hex

    def test_status_normalization(self):
        # Success
        self.assertEqual(normalize_status({"success": True}), "success")
        self.assertEqual(normalize_status({"timelines": []}), "success")

        # Failed
        self.assertEqual(normalize_status({"error": {"message": "failed"}}), "failed")
        self.assertEqual(normalize_status({"success": False}), "failed")
        self.assertEqual(normalize_status(False), "failed")

        # Blocked
        self.assertEqual(normalize_status({"confirm_token": "tok123"}), "blocked")
        self.assertEqual(normalize_status({"pending_confirm": True}), "blocked")

        # Partial
        self.assertEqual(normalize_status({"partial": True}), "partial")
        self.assertEqual(normalize_status({"succeeded": 3, "failed": 1}), "partial")

    def test_warnings_extraction(self):
        # List of warnings
        w1 = extract_warnings({"warnings": ["Warn A", "Warn B"]})
        self.assertEqual(w1, ["Warn A", "Warn B"])

        # Single warning
        w2 = extract_warnings({"warning": "Caution!"})
        self.assertEqual(w2, ["Caution!"])

        # Ignored options
        w3 = extract_warnings({"ignored_options": ["fps"]})
        self.assertEqual(len(w3), 1)
        self.assertIn("Ignored unsupported options", w3[0])

    def test_verification_extraction(self):
        # Readback with no missing items
        rb_clean = {"readback": {"after_counts": {"video:1": 5}, "missing": []}}
        v1 = extract_verification(rb_clean)
        self.assertEqual(v1["status"], "passed")
        self.assertEqual(len(v1["checks"]), 1)
        self.assertTrue(v1["checks"][0]["passed"])

        # Readback with missing items
        rb_missing = {"readback": {"missing": [{"track": "video:1", "start": 100}]}}
        v2 = extract_verification(rb_missing)
        self.assertEqual(v2["status"], "failed")
        self.assertFalse(v2["checks"][0]["passed"])
        self.assertEqual(v2["checks"][0]["missing_items"], 1)

        # Verified with contradiction
        v_contra = {"verified": False, "contradiction": True, "observed": None}
        v3 = extract_verification(v_contra)
        self.assertEqual(v3["status"], "contradiction")
        self.assertTrue(v3["contradiction"])

    def test_as_verification_dict_from_readback(self):
        readback_res = {
            "success_raw": True,
            "verified": False,
            "contradiction": True,
            "observed": 0,
            "intent": {"expected": 5},
        }
        v_dict = as_verification_dict(readback_res, check_name="clip_sync")
        self.assertEqual(v_dict["status"], "contradiction")
        self.assertTrue(v_dict["contradiction"])
        self.assertEqual(v_dict["checks"][0]["check"], "clip_sync")
        self.assertEqual(v_dict["checks"][0]["intent"], {"expected": 5})

        # Test without intent key
        rb_no_intent = {"verified": True, "contradiction": False}
        v_clean = as_verification_dict(rb_no_intent)
        self.assertEqual(v_clean["status"], "passed")
        self.assertFalse(v_clean["contradiction"])
        self.assertNotIn("intent", v_clean["checks"][0])

    def test_changes_extraction(self):
        # Explicit items
        raw = {
            "items_added": 2,
            "items_moved": 4,
            "items_deleted": 1,
            "properties_updated": 3,
            "shift_frames": 24,
        }
        ch = extract_changes(raw)
        self.assertEqual(ch["items_added"], 2)
        self.assertEqual(ch["items_moved"], 4)
        self.assertEqual(ch["items_deleted"], 1)
        self.assertEqual(ch["properties_updated"], 3)
        self.assertEqual(ch["shift_frames"], 24)

        # Versioning metric deltas
        v_raw = {
            "_versioning": {
                "analysis_run_id": "run_12345",
                "metric": "duration_seconds",
                "before_value": 120.0,
                "after_value": 105.5,
                "archived": True,
                "archived_version": "v2",
            }
        }
        ch2 = extract_changes(v_raw)
        self.assertEqual(ch2["metric"], "duration_seconds")
        self.assertEqual(ch2["before_value"], 120.0)
        self.assertEqual(ch2["after_value"], 105.5)
        self.assertEqual(ch2["delta"], -14.5)
        self.assertTrue(ch2["timeline_archived"])
        self.assertEqual(ch2["archived_version"], "v2")

    def test_dual_mode_envelope(self):
        raw = {"success": True, "timelines": ["Main", "Rough"], "count": 2}
        env = build_operation_envelope("timeline", "list", {}, raw, mode="dual")

        # Standard envelope keys
        self.assertEqual(env["status"], "success")
        self.assertEqual(env["operation"], "timeline.list")
        self.assertTrue(env["execution_id"].startswith("exec_"))
        self.assertIn("verification", env)
        self.assertIn("changes", env)
        self.assertIn("warnings", env)

        # Backward-compatibility mirrored keys
        self.assertTrue(env["success"])
        self.assertEqual(env["timelines"], ["Main", "Rough"])
        self.assertEqual(env["count"], 2)

    def test_pure_mode_envelope(self):
        raw = {"success": True, "timelines": ["Main", "Rough"]}
        env = build_operation_envelope("timeline", "list", {}, raw, mode="pure")

        self.assertEqual(env["status"], "success")
        self.assertEqual(env["operation"], "timeline.list")
        self.assertEqual(env["result"], {"success": True, "timelines": ["Main", "Rough"]})

        # Top-level should NOT contain raw payload keys in pure mode
        self.assertNotIn("timelines", env)
        self.assertNotIn("success", env)

    def test_legacy_mode(self):
        raw = {"success": True, "timelines": ["Main"]}
        res = build_operation_envelope("timeline", "list", {}, raw, mode="legacy")
        self.assertEqual(res, raw)

    def test_per_request_mode_override(self):
        raw = {"success": True, "data": 42}
        # In dual mode by default, but requested pure
        env_pure = build_operation_envelope("tool", "act", {"envelope": "pure"}, raw)
        self.assertNotIn("data", env_pure)
        self.assertEqual(env_pure["result"]["data"], 42)

        # In dual mode by default, requested legacy
        env_legacy = build_operation_envelope("tool", "act", {"envelope": "legacy"}, raw)
        self.assertEqual(env_legacy, raw)

    def test_binary_mcp_content_passthrough(self):
        class MockImage:
            pass

        img = MockImage()
        img.__class__.__name__ = "Image"
        self.assertTrue(is_binary_or_mcp_content(img))
        res = build_operation_envelope("timeline_frame", "capture", {}, img)
        self.assertIs(res, img)
        self.assertFalse(is_binary_or_mcp_content(None))
        self.assertFalse(is_binary_or_mcp_content({"dict": True}))

    def test_non_dict_and_edge_inputs(self):
        self.assertEqual(extract_warnings("not-a-dict"), [])
        self.assertEqual(extract_warnings({"warnings": "single warning string"}), ["single warning string"])
        self.assertEqual(extract_warnings({"warnings": ["valid", ""]}), ["valid"])

        self.assertEqual(extract_verification("not-a-dict"), {"status": "unverified", "checks": []})
        self.assertEqual(extract_changes("not-a-dict"), {})
        self.assertEqual(clean_result_payload("not-a-dict"), "not-a-dict")

        # Structured verification passthrough
        custom_v = {"status": "passed", "checks": [{"check": "custom"}], "extra": "info"}
        extracted = extract_verification({"verification": custom_v})
        self.assertEqual(extracted["status"], "passed")
        self.assertEqual(extracted["extra"], "info")

        # Readback without missing list
        rb_no_missing = extract_verification({"readback": {"status": "ok"}})
        self.assertEqual(rb_no_missing["status"], "passed")

        # Verified=False, contradiction=False
        v_fail = extract_verification({"verified": False})
        self.assertEqual(v_fail["status"], "failed")

        # Property restore checks
        p_restore = extract_verification({
            "property_restore_failures": 2,
            "properties_restored_items": 3,
            "verified": True,
        })
        self.assertEqual(p_restore["status"], "partial")

        # Bulk operations checks
        self.assertEqual(extract_verification({"succeeded": 3, "failed": 0})["status"], "passed")
        self.assertEqual(extract_verification({"succeeded": 2, "failed": 1})["status"], "partial")
        self.assertEqual(extract_verification({"succeeded": 0, "failed": 2})["status"], "failed")

    def test_alternative_change_keys_and_versioning(self):
        # inserted list & int
        c1 = extract_changes({"inserted": ["item1", "item2"]})
        self.assertEqual(c1["items_added"], 2)
        c1_int = extract_changes({"inserted": 4})
        self.assertEqual(c1_int["items_added"], 4)

        # deleted_sources list & int, deleted list
        c2 = extract_changes({"deleted_sources": ["s1", "s2"]})
        self.assertEqual(c2["items_deleted"], 2)
        c2_int = extract_changes({"deleted_sources": 3})
        self.assertEqual(c2_int["items_deleted"], 3)
        c2_del = extract_changes({"deleted": ["d1"]})
        self.assertEqual(c2_del["items_deleted"], 1)

        # updated list
        c3 = extract_changes({"updated": ["u1", "u2"]})
        self.assertEqual(c3["items_updated"], 2)

        # inserted_clips, tail_items_shifted, properties_restored_items
        c_ripple = extract_changes({
            "inserted_clips": 5,
            "tail_items_shifted": 12,
            "properties_restored_items": 4,
        })
        self.assertEqual(c_ripple["items_added"], 5)
        self.assertEqual(c_ripple["items_moved"], 12)
        self.assertEqual(c_ripple["properties_updated"], 4)

        # explicit changes dict
        c4 = extract_changes({"changes": {"custom_metric": 10}})
        self.assertEqual(c4["custom_metric"], 10)

        # Non-numeric metric values in versioning
        c5 = extract_changes({
            "_versioning": {
                "metric": "tag",
                "before_value": "alpha",
                "after_value": "beta",
            }
        })
        self.assertEqual(c5["metric"], "tag")
        self.assertNotIn("delta", c5)

    def test_envelope_modes_and_run_id_extraction(self):
        # Boolean params: envelope=True -> pure, envelope=False -> legacy
        pure_bool = build_operation_envelope("tool", "act", {"envelope": True}, {"val": 1})
        self.assertNotIn("val", pure_bool)
        self.assertEqual(pure_bool["result"]["val"], 1)

        legacy_bool = build_operation_envelope("tool", "act", {"envelope": False}, {"val": 1})
        self.assertEqual(legacy_bool, {"val": 1})

        # Legacy mode with non-dict input
        legacy_nondict = build_operation_envelope("tool", "act", {}, "simple-str", mode="legacy")
        self.assertEqual(legacy_nondict, {"result": "simple-str"})

        # Run id passed explicitly
        env_run = build_operation_envelope("tool", "act", {}, {"success": True}, run_id="run_custom")
        self.assertEqual(env_run["run_id"], "run_custom")

        # Run id and execution id extracted from _versioning
        v_env = build_operation_envelope(
            "tool", "act", {},
            {"success": True, "_versioning": {"analysis_run_id": "run_extracted"}}
        )
        self.assertEqual(v_env["run_id"], "run_extracted")
        self.assertEqual(v_env["execution_id"], "exec_run_extracted")

    def test_mode_management(self):
        import importlib
        import os
        from src.utils import operation_result
        with mock.patch.dict(os.environ, {"RESOLVE_MCP_RESULT_ENVELOPE": "invalid_env_val"}):
            importlib.reload(operation_result)
            self.assertEqual(operation_result.get_envelope_mode(), "dual")

        set_envelope_mode("pure")
        self.assertEqual(get_envelope_mode(), "pure")
        # Invalid mode is ignored
        set_envelope_mode("invalid_mode")
        self.assertEqual(get_envelope_mode(), "pure")
        set_envelope_mode("dual")
        self.assertEqual(get_envelope_mode(), "dual")


class ServerEnvelopeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.orig_mode = get_envelope_mode()
        set_envelope_mode("dual")

    def tearDown(self):
        set_envelope_mode(self.orig_mode)

    def test_setup_returns_dual_envelope(self):
        res = server.setup(action="get_defaults")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["operation"], "setup.get_defaults")
        self.assertTrue(res["execution_id"].startswith("exec_"))
        self.assertTrue(res["success"])
        self.assertIn("defaults", res)

    def test_setup_returns_pure_envelope_when_requested(self):
        res = server.setup(action="get_defaults", params={"envelope": "pure"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["operation"], "setup.get_defaults")
        self.assertNotIn("defaults", res)  # Only inside result
        self.assertIn("defaults", res["result"])

    def test_set_defaults_configures_envelope_mode(self):
        # Configure to pure via setup tool
        res_set = server.setup(action="set_defaults", params={"result_envelope": "pure"})
        self.assertEqual(res_set["status"], "success")
        self.assertEqual(get_envelope_mode(), "pure")

        # Check subsequent call naturally defaults to pure
        res_subsequent = server.setup(action="get_defaults")
        self.assertNotIn("defaults", res_subsequent)
        self.assertIn("defaults", res_subsequent["result"])

        # Reset back to dual
        server.setup(action="set_defaults", params={"result_envelope": "dual"})
        self.assertEqual(get_envelope_mode(), "dual")

    def test_error_envelope_integration(self):
        # Call timeline action
        err_res = server.timeline(action="ripple_insert", params={})
        self.assertEqual(err_res["status"], "failed")
        self.assertEqual(err_res["operation"], "timeline.ripple_insert")
        self.assertIn("error", err_res)
        self.assertIn(err_res["error"]["code"], {"RESOLVE_NOT_RUNNING", "INVALID_CLIP_INFOS"})

    def test_setup_schema_contains_result_envelope(self):
        schema_res = server.setup(action="schema")
        self.assertEqual(schema_res["status"], "success")
        self.assertEqual(schema_res["operation"], "setup.schema")
        general_schema = schema_res["defaults"].get("general.result_envelope")
        self.assertIsNotNone(general_schema)
        self.assertEqual(general_schema["values"], ["dual", "pure", "legacy"])

    def test_async_guarded_tool_envelope(self):
        # media_analysis is an async tool decorated with _guard_missing_params
        res = asyncio.run(server.media_analysis(action="invalid_action", params={}))
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["operation"], "media_analysis.invalid_action")
        self.assertTrue(res["execution_id"].startswith("exec_"))
        self.assertIn("error", res)

    def test_guarded_missing_param_exception_envelope(self):
        # Calling a tool function with MissingParam raised internally
        @server._guard_missing_params
        def dummy_guarded_tool(action: str, params=None):
            raise server._MissingParam("required_field")

        res = dummy_guarded_tool("test_action", {})
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["operation"], "dummy_guarded_tool.test_action")
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], "MISSING_REQUIRED_FIELD")

        # Async variant
        @server._guard_missing_params
        async def dummy_async_guarded_tool(action: str, params=None):
            raise server._MissingParam("required_field")

        async_res = asyncio.run(dummy_async_guarded_tool("test_action", {}))
        self.assertEqual(async_res["status"], "failed")
        self.assertEqual(async_res["operation"], "dummy_async_guarded_tool.test_action")
        self.assertEqual(async_res["error"]["code"], "MISSING_REQUIRED_FIELD")

    @mock.patch("src.server._edit_page_for_timeline_edits")
    @mock.patch("src.server._build_append_clip_info_dict")
    @mock.patch("src.server._confirm_token_required", return_value=False)
    def test_timeline_ripple_insert_impl_emits_change_keys(
        self, mock_confirm, mock_build_info, mock_edit_page
    ):
        mock_edit_page.return_value.__enter__.return_value = None
        mock_edit_page.return_value.__exit__.return_value = None
        mock_clip = mock.MagicMock()
        mock_build_info.return_value = ({
            "mediaPoolItem": mock_clip,
            "startFrame": 0,
            "endFrame": 24,
            "trackIndex": 1,
            "mediaType": 1,
        }, None)

        mock_proj = mock.MagicMock()
        mock_mp = mock.MagicMock()
        mock_proj.GetMediaPool.return_value = mock_mp
        mock_mp.AppendToTimeline.return_value = [mock.MagicMock()]

        mock_tl = mock.MagicMock()
        mock_tl.GetStartFrame.return_value = 0
        mock_tl.GetSetting.return_value = "24"
        mock_tl.GetTrackCount.return_value = 1
        mock_tl.GetIsTrackLocked.return_value = False

        inserted_item = mock.MagicMock()
        inserted_item.GetStart.return_value = 100
        inserted_item.GetDuration.return_value = 24
        inserted_item.GetEnd.return_value = 124

        def item_list(t_type, t_idx):
            if mock_mp.AppendToTimeline.called and t_type == "video" and t_idx == 1:
                return [inserted_item]
            return []

        mock_tl.GetItemListInTrack.side_effect = item_list

        params = {
            "clip_infos": [{"mediaPoolItem": mock_clip, "startFrame": 0, "endFrame": 24}],
            "record_frame": 100,
            "dry_run": False,
        }

        res = server._timeline_ripple_insert_impl(mock_proj, mock_tl, params)
        self.assertTrue(res["success"])
        self.assertEqual(res["items_added"], 1)
        self.assertEqual(res["items_moved"], 0)
        self.assertEqual(res["items_deleted"], 0)


if __name__ == "__main__":
    unittest.main()
