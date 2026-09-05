"""Tests for Agent Execution Lifecycle, Hooks, and Pre-flight Risk Assessment.

Validates:
- Operation risk classification and blast radius calculation
- Lifecycle hooks (before_tool_call, after_tool_call, on_error)
- Dry-run interception and safety policies
- Readback verification and drift detection hooks
- Integration via resolve_control(action="inspect_operation") and list_lifecycle_hooks
"""

import unittest
from unittest.mock import MagicMock

from src.server import resolve_control
from src.utils.execution_lifecycle import (
    BlastRadius,
    DriftDetectionHook,
    DryRunInterceptionHook,
    HookDecision,
    LifecycleHook,
    LifecyclePipeline,
    ReadbackVerificationHook,
    RiskAssessment,
    RiskLevel,
    ToolCallContext,
    classify_operation_risk,
    get_lifecycle_pipeline,
    inspect_operation,
    list_lifecycle_hooks,
)


class TestExecutionLifecycle(unittest.TestCase):
    def setUp(self):
        self.pipeline = LifecyclePipeline()

    def test_classify_operation_risk_read_only(self):
        assessment = classify_operation_risk("timeline", "get_timeline_items", {"track_index": 1})
        self.assertEqual(assessment.level, RiskLevel.LOW)
        self.assertFalse(assessment.destructive)
        self.assertFalse(assessment.confirmation_required)

    def test_classify_operation_risk_destructive_delete(self):
        assessment = classify_operation_risk("timeline", "delete_clips", {"timeline_item_ids": ["c1", "c2", "c3"]})
        self.assertEqual(assessment.level, RiskLevel.HIGH)
        self.assertTrue(assessment.destructive)
        self.assertTrue(assessment.confirmation_required)
        self.assertEqual(assessment.blast_radius, BlastRadius.ITEM)
        self.assertTrue(any("delete_clips" in r for r in assessment.reasons))

    def test_classify_operation_risk_medium_grade(self):
        assessment = classify_operation_risk("timeline_item_color", "apply_grade", {"grade_mode": "cdl"})
        self.assertEqual(assessment.level, RiskLevel.MEDIUM)
        self.assertFalse(assessment.destructive)

    def test_pipeline_before_hook_allows_execution(self):
        hook = MagicMock(spec=LifecycleHook)
        hook.name = "mock_hook"
        hook.enabled = True
        hook.before_tool_call.return_value = HookDecision(proceed=True)
        self.pipeline.register_hook(hook)

        ctx = ToolCallContext("timeline", "create_timeline", {})
        decision = self.pipeline.run_before(ctx)
        self.assertTrue(decision.proceed)
        hook.before_tool_call.assert_called_once_with(ctx)

    def test_pipeline_before_hook_short_circuits(self):
        hook = MagicMock(spec=LifecycleHook)
        hook.name = "blocker_hook"
        hook.enabled = True
        hook.before_tool_call.return_value = HookDecision(
            proceed=False,
            short_circuit_result={"error": "Operation blocked by safety policy"},
            reason="Blocked by policy",
        )
        self.pipeline.register_hook(hook)

        ctx = ToolCallContext("timeline", "delete_clips", {})
        decision = self.pipeline.run_before(ctx)
        self.assertFalse(decision.proceed)
        self.assertEqual(decision.short_circuit_result["error"], "Operation blocked by safety policy")
        self.assertEqual(decision.reason, "Blocked by policy")

    def test_pipeline_after_hook_enriches_envelope(self):
        class EnrichedHook(LifecycleHook):
            name = "enricher"
            enabled = True

            def before_tool_call(self, ctx):
                return HookDecision(proceed=True)

            def after_tool_call(self, ctx, result_envelope, duration_ms):
                if isinstance(result_envelope, dict) and "_operation" in result_envelope:
                    result_envelope["_operation"]["custom_metric"] = 42
                return result_envelope

            def on_error(self, ctx, exception, duration_ms):
                pass

        self.pipeline.register_hook(EnrichedHook())
        ctx = ToolCallContext("media_pool", "create_bin", {"name": "Selects"})
        envelope = {"success": True, "_operation": {"op": "media_pool.create_bin"}}
        enveloped = self.pipeline.run_after(ctx, envelope, duration_ms=15)
        self.assertEqual(enveloped["_operation"]["custom_metric"], 42)

    def test_pipeline_on_error_notifies_hooks(self):
        hook = MagicMock(spec=LifecycleHook)
        hook.name = "error_tracker"
        hook.enabled = True
        self.pipeline.register_hook(hook)

        ctx = ToolCallContext("render", "render", {})
        err = RuntimeError("GPU timeout")
        self.pipeline.run_on_error(ctx, err, duration_ms=2500)
        hook.on_error.assert_called_once_with(ctx, err, 2500)

    def test_dry_run_interception_hook(self):
        guard = DryRunInterceptionHook()

        # Non-dry run returns None (proceed)
        ctx_normal = ToolCallContext("timeline", "delete_clips", {"timeline_item_ids": ["c1"]})
        decision = guard.before_tool_call(ctx_normal)
        self.assertIsNone(decision)

        # Dry run intercepts and provides simulation
        ctx_dry = ToolCallContext("timeline", "delete_clips", {"timeline_item_ids": ["c1"], "dry_run": True})
        decision_dry = guard.before_tool_call(ctx_dry)
        self.assertIsNotNone(decision_dry)
        self.assertFalse(decision_dry.proceed)
        self.assertTrue(decision_dry.short_circuit_result["dry_run"])
        self.assertTrue(decision_dry.short_circuit_result["simulated"])
        self.assertEqual(decision_dry.short_circuit_result["tool"], "timeline")
        self.assertEqual(decision_dry.short_circuit_result["action"], "delete_clips")

    def test_resolve_control_inspect_operation(self):
        res = resolve_control(
            action="inspect_operation",
            params={
                "tool": "timeline",
                "target_action": "delete_clips",
                "target_params": {"timeline_item_ids": ["c1", "c2", "c3"]},
            },
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["tool"], "timeline")
        self.assertEqual(res["action"], "delete_clips")
        self.assertTrue(res["destructive"])
        self.assertTrue(res["confirmation_required"])
        self.assertEqual(res["blast_radius"], "item")
        self.assertEqual(res["risk"]["level"], "high")

    def test_classify_operation_risk_critical_project_delete(self):
        assessment = classify_operation_risk("project_manager", "delete_project", {"project_name": "Old"})
        self.assertEqual(assessment.level, RiskLevel.CRITICAL)
        self.assertTrue(assessment.destructive)
        self.assertTrue(assessment.confirmation_required)
        self.assertEqual(assessment.blast_radius, BlastRadius.PROJECT)

    def test_classify_operation_risk_ripple_delete(self):
        assessment = classify_operation_risk("timeline", "delete_clips", {"timeline_item_ids": ["c1"], "ripple": True})
        self.assertEqual(assessment.level, RiskLevel.HIGH)
        self.assertEqual(assessment.blast_radius, BlastRadius.TIMELINE)
        self.assertTrue(any("Ripple" in r for r in assessment.reasons))

    def test_readback_verification_hook_handles_contradiction(self):
        hook = ReadbackVerificationHook()
        ctx = ToolCallContext("timeline", "delete_clips", {})
        payload = {
            "success": True,
            "verification": {
                "status": "contradiction",
                "checks": [{"check": "item_deleted", "passed": False}],
                "contradiction": True,
                "verified": False,
            },
        }
        res = hook.after_tool_call(ctx, payload, duration_ms=10)
        self.assertIsNotNone(res)
        self.assertTrue(res["contradiction"])
        self.assertFalse(res["verified"])

    def test_drift_detection_hook_measures_delta(self):
        states = [
            {"duration_frames": 240, "track_count_video": 2},
            {"duration_frames": 200, "track_count_video": 2},
        ]
        provider = lambda: states.pop(0) if states else None
        hook = DriftDetectionHook(state_provider=provider)

        # Action is non-duration altering (e.g. set_clip_color), so duration changing is unexpected drift
        ctx = ToolCallContext("timeline", "set_clip_color", {})
        ctx.pre_state = hook._state_provider()

        envelope = {"success": True, "_operation": {"op": "timeline.set_clip_color"}}
        self.pipeline.register_hook(hook)
        res = self.pipeline.run_after(ctx, envelope, duration_ms=25)
        drift = res["_operation"]["lifecycle"]["drift_detection"]
        self.assertTrue(drift["drift_detected"])
        self.assertEqual(drift["duration_delta_frames"], -40)

    def test_bridge_connection_and_live_lifecycle_state(self):
        import tempfile
        from tests.test_resolve_bridge import FakeResolve
        from src.utils import resolve_bridge_ops as rbo
        from src.utils import resolve_bridge as rb
        from src import server

        root = tempfile.mkdtemp(prefix="bridge_lifecycle_")
        fake_resolve = FakeResolve(timelines=("Test Cut",))
        ops = rbo.ResolveOperations(fake_resolve, media_roots=[root], output_roots=[root])
        config = {"host": "127.0.0.1", "port": 0, "token": "a" * 48, "auth_clock_skew_seconds": 60}
        bridge = rb.Bridge(fake_resolve, config, rbo.make_dispatch(ops))
        bridge.start()
        self.addCleanup(bridge.stop)

        # Connect fake resolve to server handle
        original_resolve = server.resolve
        try:
            server.resolve = fake_resolve
            # Verify inspect_operation picks up live Resolve state
            res = resolve_control(
                action="inspect_operation",
                params={"tool": "timeline", "target_action": "delete_clips", "target_params": {"timeline_item_ids": ["c1"]}},
            )
            self.assertTrue(res["success"])
            self.assertIsNotNone(res["pre_state"])
            self.assertEqual(res["pre_state"]["project_name"], "Alpha")
            self.assertEqual(res["pre_state"]["timeline_name"], "Test Cut")
            self.assertEqual(res["pre_state"]["duration_frames"], 240)
            self.assertTrue(res["snapshot_available"])

            # Verify end-to-end execution lifecycle run with trace recording
            resolve_control(action="begin_execution", params={"request": "Integration cut with bridge"})

            # Execute a guarded operation
            @server._guard_missing_params
            def sample_edit_op(timeline_id: str):
                return {"success": True, "deleted": 1, "timeline_id": timeline_id}

            op_res = sample_edit_op("Test Cut")
            self.assertTrue(op_res["success"])
            self.assertIn("_operation", op_res)

            # Check trace contains recorded execution and lifecycle
            trace_res = resolve_control(action="get_execution_trace")
            self.assertTrue(trace_res["success"])
            trace = trace_res["trace"]
            self.assertEqual(trace["request"], "Integration cut with bridge")
            self.assertTrue(len(trace["tools"]) > 0)

            # End execution
            end_res = resolve_control(action="end_execution")
            self.assertTrue(end_res["success"])
        finally:
            server.resolve = original_resolve

    def test_resolve_control_list_lifecycle_hooks(self):
        res = resolve_control(action="list_lifecycle_hooks", params={})
        self.assertTrue(res["success"])
        self.assertIn("hooks", res)
        hook_names = [h["name"] for h in res["hooks"]]
        self.assertIn("risk_classification", hook_names)
        self.assertIn("dry_run_interception", hook_names)
        self.assertIn("readback_verification", hook_names)
    def test_disabled_hook_is_skipped(self):
        hook = MagicMock(spec=LifecycleHook)
        hook.name = "disabled_hook"
        hook.enabled = False
        self.pipeline.register_hook(hook)

        ctx = ToolCallContext("timeline", "get_timeline_items", {})
        decision = self.pipeline.run_before(ctx)
        self.assertTrue(decision.proceed)
        hook.before_tool_call.assert_not_called()

        envelope = {"success": True, "_operation": {}}
        self.pipeline.run_after(ctx, envelope, duration_ms=5)
        hook.after_tool_call.assert_not_called()

    def test_hook_raising_exception_does_not_crash_pipeline(self):
        failing_hook = MagicMock(spec=LifecycleHook)
        failing_hook.name = "exploding_hook"
        failing_hook.enabled = True
        failing_hook.before_tool_call.side_effect = RuntimeError("Crash before")
        failing_hook.after_tool_call.side_effect = RuntimeError("Crash after")
        failing_hook.on_error.side_effect = RuntimeError("Crash error")
        self.pipeline.register_hook(failing_hook)

        ctx = ToolCallContext("timeline", "get_timeline_items", {})
        decision = self.pipeline.run_before(ctx)
        self.assertTrue(decision.proceed)

        envelope = {"success": True, "_operation": {}}
        res = self.pipeline.run_after(ctx, envelope, duration_ms=5)
        self.assertEqual(res, envelope)

        self.pipeline.run_on_error(ctx, ValueError("Original err"), duration_ms=5)

    def test_dry_run_interception_native_actions_and_invalid_params(self):
        guard = DryRunInterceptionHook()
        # Invalid params (not dict)
        ctx_none = ToolCallContext("timeline", "delete_clips", None)
        self.assertIsNone(guard.before_tool_call(ctx_none))

        # Native dry-run action (let native tool handle)
        ctx_native = ToolCallContext("timeline", "ripple_insert", {"dry_run": True})
        self.assertIsNone(guard.before_tool_call(ctx_native))

    def test_readback_verification_with_non_dict_result(self):
        hook = ReadbackVerificationHook()
        ctx = ToolCallContext("timeline", "delete_clips", {})
        self.assertIsNone(hook.after_tool_call(ctx, "non-dict", duration_ms=10))

    def test_inspect_operation_handles_faulty_state_provider(self):
        from src.utils.execution_lifecycle import ResolveStateInspectionHook
        pipeline = LifecyclePipeline()
        faulty_hook = ResolveStateInspectionHook(state_provider=lambda: 1 / 0)
        pipeline.register_hook(faulty_hook)
        res = pipeline.inspect_operation("timeline", "get_timeline_items")
        self.assertTrue(res["success"])
        self.assertIsNone(res["pre_state"])


if __name__ == "__main__":
    unittest.main()
