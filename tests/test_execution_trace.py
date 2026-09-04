"""Tests for agent execution tracing and observability ("Why did the editor do this?").

Covers:
  - Execution ID generation and correlation.
  - Multi-step workflows via begin_execution / end_execution.
  - Automatic tool call timing (duration_ms) and count rollups.
  - Semantic changes and readback verification aggregation.
  - Query APIs: get_execution_trace, get_execution, list_recent_executions.
  - Integration with compound tools and _operation envelope.
  - Thread safety and ring-buffer trimming.
"""

from __future__ import annotations

import concurrent.futures
import json
import unittest
from unittest import mock

import src.server as compound
from src.utils import execution_trace as et
from src.utils import operation_result as opres


class ExecutionTraceUnitTest(unittest.TestCase):
    def setUp(self):
        et.clear_executions()

    def tearDown(self):
        et.clear_executions()

    def test_new_execution_id_format(self):
        id1 = et.new_execution_id()
        id2 = et.new_execution_id()
        self.assertTrue(id1.startswith("exec_"))
        self.assertTrue(id2.startswith("exec_"))
        self.assertNotEqual(id1, id2)

    def test_record_single_step_creates_trace(self):
        trace = et.record_step(
            tool="timeline",
            action="get_current",
            params={"request": "Check active cut"},
            raw_result={"success": True, "timeline_name": "Main"},
            duration_ms=45,
        )
        self.assertEqual(trace["status"], "success")
        self.assertEqual(trace["request"], "Check active cut")
        self.assertEqual(trace["duration_ms"], 45)
        self.assertEqual(len(trace["tools"]), 1)
        self.assertEqual(trace["tools"][0]["tool"], "timeline.get_current")
        self.assertEqual(trace["tools"][0]["count"], 1)
        self.assertEqual(trace["tools"][0]["duration_ms"], 45)
        self.assertEqual(len(trace["steps"]), 1)

    def test_multiple_calls_aggregate_counts_and_duration(self):
        exec_id = et.new_execution_id()
        for i in range(17):
            et.record_step(
                tool="timeline",
                action="delete_item",
                params={"item_id": f"item_{i}"},
                raw_result={"success": True, "items_deleted": 1},
                duration_ms=10,
                execution_id=exec_id,
                changes={"items_deleted": 1},
            )

        trace = et.get_execution_trace(exec_id)
        self.assertIsNotNone(trace)
        self.assertEqual(trace["execution_id"], exec_id)
        self.assertEqual(len(trace["tools"]), 1)
        tool_entry = trace["tools"][0]
        self.assertEqual(tool_entry["tool"], "timeline.delete_item")
        self.assertEqual(tool_entry["count"], 17)
        self.assertEqual(tool_entry["duration_ms"], 170)
        self.assertEqual(trace["duration_ms"], 170)
        self.assertEqual(trace["changes"], {"items_deleted": 17})
        self.assertEqual(len(trace["steps"]), 17)

    def test_multi_step_workflow_with_begin_and_end(self):
        # 1. begin_execution
        begin_res = et.begin_execution(request="Remove all pauses longer than 800ms")
        self.assertTrue(begin_res["success"])
        exec_id = begin_res["execution_id"]
        self.assertEqual(et.current_execution_id(), exec_id)

        # 2. analyze_timeline
        et.record_step(
            tool="analyze_timeline",
            action="detect_silence",
            params={"threshold_ms": 800},
            raw_result={"success": True, "pauses_found": 17},
            duration_ms=821,
            verification={"status": "passed", "checks": [{"check": "silence", "passed": True}]},
        )

        # 3. delete_item x 17
        for i in range(17):
            et.record_step(
                tool="timeline",
                action="delete_item",
                params={"index": i},
                raw_result={"success": True, "items_deleted": 1},
                duration_ms=20,
                changes={"items_deleted": 1},
            )

        # 4. verify timeline
        et.record_step(
            tool="timeline",
            action="verify",
            params={},
            raw_result={"success": True, "verified": True},
            duration_ms=55,
            verification={"status": "passed", "checks": [{"check": "gapless", "passed": True}]},
        )

        # 5. end_execution
        final_trace = et.end_execution(exec_id)
        self.assertIsNotNone(final_trace)
        self.assertEqual(final_trace["execution_id"], exec_id)
        self.assertEqual(final_trace["request"], "Remove all pauses longer than 800ms")
        self.assertEqual(final_trace["status"], "success")
        self.assertIsNone(et.current_execution_id())

        # Check aggregated tools
        tools = final_trace["tools"]
        self.assertEqual(len(tools), 3)

        analysis_tool = next(t for t in tools if "analyze_timeline" in t["tool"])
        self.assertEqual(analysis_tool["duration_ms"], 821)
        self.assertEqual(analysis_tool["count"], 1)

        delete_tool = next(t for t in tools if "timeline.delete_item" in t["tool"])
        self.assertEqual(delete_tool["count"], 17)
        self.assertEqual(delete_tool["duration_ms"], 340)

        # Check aggregated verification and changes
        self.assertTrue(final_trace["verification"]["passed"])
        self.assertEqual(final_trace["changes"], {"items_deleted": 17})
        self.assertEqual(len(final_trace["verification"]["checks"]), 2)

    def test_verification_rollup_contradiction_flags_failure(self):
        begin_res = et.begin_execution(request="Grade hero shot")
        exec_id = begin_res["execution_id"]

        et.record_step(
            tool="timeline_item_color",
            action="set_cdl",
            params={},
            raw_result={"success": True},
            duration_ms=100,
            verification={
                "status": "contradiction",
                "contradiction": True,
                "checks": [{"check": "readback", "passed": False, "contradiction": True}],
            },
        )

        final_trace = et.end_execution(exec_id)
        self.assertEqual(final_trace["status"], "failed")
        self.assertFalse(final_trace["verification"]["passed"])
        self.assertTrue(final_trace["verification"]["contradiction"])

    def test_ring_buffer_caps_at_maximum(self):
        for i in range(120):
            et.record_step(
                tool="tool",
                action="action",
                params={},
                raw_result={"success": True},
                duration_ms=1,
            )

        recent = et.list_recent_executions(limit=120)
        self.assertLessEqual(len(recent), et.MAX_RECENT_EXECUTIONS)
        self.assertEqual(len(recent), 100)

    def test_get_execution_trace_without_id_returns_most_recent(self):
        self.assertIsNone(et.get_execution_trace())
        et.record_step("tool", "first", {}, {"success": True}, 5)
        step2 = et.record_step("tool", "second", {}, {"success": True}, 5)
        latest = et.get_execution_trace()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["execution_id"], step2["execution_id"])

    def test_clear_executions_resets_store(self):
        et.record_step("tool", "act", {}, {"success": True}, 5)
        self.assertEqual(len(et.list_recent_executions()), 1)
        res = et.clear_executions()
        self.assertTrue(res["success"])
        self.assertEqual(res["cleared"], 1)
        self.assertEqual(len(et.list_recent_executions()), 0)

    def test_thread_safety_under_concurrent_recording(self):
        exec_id = et.new_execution_id()
        num_threads = 8
        steps_per_thread = 25

        def worker(thread_idx: int):
            for step_idx in range(steps_per_thread):
                et.record_step(
                    tool="timeline",
                    action="slice",
                    params={"t": thread_idx, "s": step_idx},
                    raw_result={"success": True, "slices": 1},
                    duration_ms=2,
                    execution_id=exec_id,
                    changes={"slices": 1},
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            for f in futures:
                f.result()

        trace = et.get_execution_trace(exec_id)
        self.assertIsNotNone(trace)
        self.assertEqual(len(trace["steps"]), num_threads * steps_per_thread)
        self.assertEqual(trace["changes"]["slices"], num_threads * steps_per_thread)
        self.assertEqual(trace["tools"][0]["count"], num_threads * steps_per_thread)


class ServerExecutionTraceIntegrationTest(unittest.TestCase):
    def setUp(self):
        et.clear_executions()

    def tearDown(self):
        et.clear_executions()

    def test_compound_tool_attaches_execution_id_and_duration_to_envelope(self):
        res = compound.setup("schema")
        self.assertIn(opres.ENVELOPE_KEY, res)
        env = res[opres.ENVELOPE_KEY]
        self.assertTrue(env["execution_id"].startswith("exec_"))
        self.assertIn("duration_ms", env)
        self.assertIsInstance(env["duration_ms"], int)

    def test_resolve_control_trace_lifecycle_actions(self):
        # 1. begin execution
        begin_out = compound.resolve_control("begin_execution", {
            "request": "Transcribe and analyze timeline",
            "initiator": "test_agent",
        })
        self.assertTrue(begin_out["success"])
        exec_id = begin_out["execution_id"]

        # 2. call a tool that threads into this active execution
        schema_out = compound.setup("schema")
        self.assertEqual(schema_out[opres.ENVELOPE_KEY]["execution_id"], exec_id)

        # 3. end execution
        end_out = compound.resolve_control("end_execution", {
            "execution_id": exec_id,
            "notes": "Completed successfully",
        })
        self.assertTrue(end_out["success"])
        trace = end_out["trace"]
        self.assertEqual(trace["execution_id"], exec_id)
        self.assertEqual(trace["request"], "Transcribe and analyze timeline")
        self.assertEqual(trace["notes"], "Completed successfully")

        # 4. get_execution_trace by ID
        get_out = compound.resolve_control("get_execution_trace", {"execution_id": exec_id})
        self.assertTrue(get_out["success"])
        self.assertEqual(get_out["trace"]["execution_id"], exec_id)

        # 5. get_execution alias
        alias_out = compound.resolve_control("get_execution", {"id": exec_id})
        self.assertTrue(alias_out["success"])
        self.assertEqual(alias_out["trace"]["execution_id"], exec_id)

        # 6. list_recent_executions
        list_out = compound.resolve_control("list_recent_executions", {"limit": 10})
        self.assertTrue(list_out["success"])
        self.assertGreaterEqual(list_out["count"], 1)
        found = [e for e in list_out["executions"] if e["execution_id"] == exec_id]
        self.assertEqual(len(found), 1)

        # 7. clear_executions dry-run then real
        dry_clear = compound.resolve_control("clear_executions", {"dry_run": True})
        self.assertTrue(dry_clear["dry_run"])
        real_clear = compound.resolve_control("clear_executions")
        self.assertTrue(real_clear["success"])
        self.assertGreaterEqual(real_clear["cleared"], 1)

    def test_observer_actions_do_not_pollute_trace(self):
        compound.resolve_control("begin_execution", {"request": "Observer test"})
        compound.setup("schema")
        # Inspecting traces multiple times
        compound.resolve_control("get_execution_trace")
        compound.resolve_control("list_recent_executions")
        trace = compound.resolve_control("end_execution")["trace"]

        # Only setup.schema should be recorded as a tool step, NOT get_execution_trace or list_recent_executions
        tool_names = [s["operation"] for s in trace["steps"]]
        self.assertIn("setup.schema", tool_names)
        self.assertNotIn("resolve_control.get_execution_trace", tool_names)
        self.assertNotIn("resolve_control.list_recent_executions", tool_names)

    def test_direct_functions_exported_on_server(self):
        from src.server import (
            get_execution_trace,
            get_execution,
            list_recent_executions,
            begin_execution,
            end_execution,
            clear_executions,
        )
        self.assertTrue(callable(get_execution_trace))
        self.assertTrue(callable(get_execution))
        self.assertTrue(callable(list_recent_executions))
        self.assertTrue(callable(begin_execution))
        self.assertTrue(callable(end_execution))
        self.assertTrue(callable(clear_executions))


if __name__ == "__main__":
    unittest.main()
