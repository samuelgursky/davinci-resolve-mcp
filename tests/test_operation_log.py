"""Tests for the mutating-operation JSONL log."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

import src.server as compound
from src.utils import operation_log, operation_result
from src.utils.execution_lifecycle import LifecyclePipeline, ToolCallContext


class OperationLogRecords(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_provider = operation_log._PREFERENCE_PROVIDER
        self.tmp = tempfile.TemporaryDirectory()
        self.log_path = os.path.join(self.tmp.name, "operation-log.jsonl")
        operation_log.register_preference_provider(
            lambda key: {
                "destructive.operation_log": True,
                "destructive.operation_log_path": self.log_path,
            }.get(key)
        )

    def tearDown(self) -> None:
        operation_log._PREFERENCE_PROVIDER = self.saved_provider
        self.tmp.cleanup()

    def _records(self):
        with open(self.log_path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_build_record_uses_operation_envelope_and_risk(self) -> None:
        raw = {
            "success": True,
            "operation_id": "op_fixed",
            "_changes": {"items_added": 2},
        }
        enveloped = operation_result.build_operation_envelope(
            "timeline",
            "duplicate_clips",
            {"dry_run": False},
            raw,
            duration_ms=17,
        )
        record = operation_log.build_record(
            tool_name="timeline",
            action="duplicate_clips",
            params={"dry_run": False},
            result=enveloped,
            risk={
                "level": "medium",
                "recognised": True,
                "blast_radius": "timeline",
            },
        )

        self.assertEqual(record["operation_id"], "op_fixed")
        self.assertEqual(record["operation"], "timeline.duplicate_clips")
        self.assertEqual(record["risk_level"], "medium")
        self.assertFalse(record["dry_run"])
        self.assertEqual(record["status"], "success")
        self.assertEqual(record["duration_ms"], 17)
        self.assertEqual(record["changes"], {"items_added": 2})
        self.assertIn("items_added=2", record["summary"])

    def test_build_record_coerces_dry_run_strings(self) -> None:
        for value, expected in (
            ("true", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("off", False),
        ):
            with self.subTest(value=value):
                record = operation_log.build_record(
                    tool_name="timeline_markers",
                    action="add",
                    params={"dry_run": value},
                    result={"success": True, "dry_run": value},
                    risk={"level": "low", "recognised": True},
                )
                self.assertEqual(record["dry_run"], expected)

    def test_build_record_marks_successful_dry_run_summary_as_preview(self) -> None:
        record = operation_log.build_record(
            tool_name="timeline_markers",
            action="add",
            params={"dryRun": "true"},
            result={"success": True, "dry_run": True},
            risk={"level": "low", "recognised": True},
        )

        self.assertTrue(record["dry_run"])
        self.assertEqual(record["summary"], "timeline_markers.add dry-run preview")

    def test_exception_record_coerces_dry_run_false_string(self) -> None:
        record = operation_log.build_exception_record(
            tool_name="timeline_markers",
            action="add",
            params={"dry_run": "false"},
            exc=RuntimeError("Resolve bridge closed"),
            risk={"level": "low", "recognised": True},
            duration_ms=2,
        )

        self.assertFalse(record["dry_run"])

    def test_lifecycle_writes_mutating_operation_record(self) -> None:
        pipeline = LifecyclePipeline()
        ctx = ToolCallContext(
            "timeline",
            "duplicate_clips",
            {"timeline_item_ids": ["c1"]},
        )
        pipeline.run_before(ctx)
        raw = {"success": True, "_changes": {"items_added": 1}}
        enveloped = operation_result.build_operation_envelope(
            ctx.tool_name,
            ctx.action,
            ctx.params,
            raw,
            duration_ms=5,
        )

        pipeline.run_after(ctx, enveloped, duration_ms=5)

        [record] = self._records()
        self.assertEqual(record["tool"], "timeline")
        self.assertEqual(record["action"], "duplicate_clips")
        self.assertEqual(record["risk_level"], "medium")
        self.assertEqual(record["changes"]["items_added"], 1)

    def test_lifecycle_does_not_log_read_only_operation(self) -> None:
        pipeline = LifecyclePipeline()
        ctx = ToolCallContext("timeline", "get_current", {})
        pipeline.run_before(ctx)
        raw = {"success": True, "timeline": "Cut"}
        enveloped = operation_result.build_operation_envelope(
            ctx.tool_name,
            ctx.action,
            ctx.params,
            raw,
            duration_ms=3,
        )

        pipeline.run_after(ctx, enveloped, duration_ms=3)

        self.assertFalse(os.path.exists(self.log_path))

    def test_blocked_destructive_attempt_logs_as_blocked(self) -> None:
        pipeline = LifecyclePipeline()
        ctx = ToolCallContext("timeline", "delete_track", {"track_index": 1})
        pipeline.run_before(ctx)
        raw = {
            "success": False,
            "status": "blocked_by_security_policy",
            "error": {"category": "destructive_blocked"},
        }
        enveloped = operation_result.build_operation_envelope(
            ctx.tool_name,
            ctx.action,
            ctx.params,
            raw,
            duration_ms=0,
        )

        pipeline.run_after(ctx, enveloped, duration_ms=0)

        [record] = self._records()
        self.assertEqual(record["status"], "blocked")
        self.assertEqual(record["summary"], "timeline.delete_track blocked before mutation")

    def test_mutating_exception_logs_failed_record(self) -> None:
        pipeline = LifecyclePipeline()
        ctx = ToolCallContext("timeline", "delete_track", {"track_index": 1})
        pipeline.run_before(ctx)

        pipeline.run_on_error(ctx, RuntimeError("Resolve bridge closed"), duration_ms=9)

        [record] = self._records()
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["operation"], "timeline.delete_track")
        self.assertEqual(record["risk_level"], "high")
        self.assertEqual(record["duration_ms"], 9)
        self.assertEqual(record["exception"]["type"], "RuntimeError")
        self.assertEqual(record["exception"]["message"], "Resolve bridge closed")
        self.assertIn("failed with RuntimeError", record["summary"])

    def test_read_only_exception_does_not_write_operation_log(self) -> None:
        pipeline = LifecyclePipeline()
        ctx = ToolCallContext("timeline", "get_current", {})
        pipeline.run_before(ctx)

        pipeline.run_on_error(ctx, RuntimeError("Resolve bridge closed"), duration_ms=9)

        self.assertFalse(os.path.exists(self.log_path))


class OperationLogSetup(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_env = os.environ.get("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS")
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = os.path.join(
            self.tmp.name,
            "prefs.json",
        )

    def tearDown(self) -> None:
        if self.saved_env is None:
            os.environ.pop("DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS", None)
        else:
            os.environ["DAVINCI_RESOLVE_MCP_MEDIA_ANALYSIS_PREFS"] = self.saved_env
        self.tmp.cleanup()

    def test_setup_sets_and_clears_operation_log_defaults(self) -> None:
        configured = compound.setup(
            "set_defaults",
            {
                "destructive": {
                    "operation_log": False,
                    "operation_log_path": os.path.join(self.tmp.name, "ops.jsonl"),
                },
            },
        )
        self.assertTrue(configured["success"])
        destructive = configured["defaults"]["destructive"]
        self.assertFalse(destructive["operation_log"])
        self.assertEqual(
            destructive["operation_log_path"],
            os.path.realpath(os.path.join(self.tmp.name, "ops.jsonl")),
        )

        cleared = compound.setup(
            "clear_defaults",
            {"keys": ["destructive.operation_log", "destructive.operation_log_path"]},
        )
        self.assertTrue(cleared["success"])
        destructive = cleared["defaults"]["destructive"]
        self.assertTrue(destructive["operation_log"])
        self.assertTrue(destructive["operation_log_path"].endswith("logs/operation-log.jsonl"))


if __name__ == "__main__":
    unittest.main()
