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

    def test_an_unrecognised_operation_is_not_reported_as_assessed(self):
        """The guard exists for hallucinated calls; it must not reassure one.

        Any action matching no rule fell into a "general mutation" bucket and
        came back `medium` / `destructive: false` / `confirmation_required:
        false` — a confident answer about an operation the classifier had never
        heard of, including ones that do not exist.
        """
        from src.utils.execution_lifecycle import inspect_operation

        res = inspect_operation("not_a_tool", "not_an_action", {})
        self.assertFalse(res["recognised"])
        self.assertTrue(any("matches no risk rule" in r for r in res["reasons"]))

        known = inspect_operation("timeline", "delete_clips", {"timeline_item_ids": ["c1"]})
        self.assertTrue(known["recognised"])
        self.assertTrue(known["destructive"])

    def test_snapshot_availability_is_never_inferred_from_pre_state(self):
        # "I could read the project name" is not "I can put this back".
        from src.utils.execution_lifecycle import classify_operation_risk

        assessment = classify_operation_risk("timeline", "delete_clips", {})
        self.assertIsNone(assessment.snapshot_available)
        self.assertIsNone(assessment.to_dict()["snapshot_available"])

    def test_no_default_hook_short_circuits(self):
        """Nothing shipping may answer on behalf of code that never ran.

        The pipeline can gate a call — `HookDecision(proceed=False)` and the
        public `register_hook` exist for that. But every hook registered by
        default only observes. The original pipeline shipped a dry-run
        interceptor that short-circuited any `dry_run: true` call outside a
        four-entry allowlist with a synthesised `success: true`, and `dry_run`
        is precisely the call an editor makes *because* they do not trust the
        next one.
        """
        pipeline = LifecyclePipeline()
        probes = [
            ("timeline", "delete_clips", {"timeline_item_ids": ["c1"], "dry_run": True}),
            ("setup", "set_defaults", {"result_envelope": "pure", "dry_run": True}),
            ("media_pool", "delete_clips", {"dry_run": True, "confirm_token": "t"}),
            ("project_manager", "delete_project", {"dry_run": True}),
            ("timeline", "get_item_list", {"dry_run": True}),
        ]
        for tool, action, params in probes:
            with self.subTest(op=f"{tool}.{action}"):
                decision = pipeline.run_before(ToolCallContext(tool, action, params))
                if decision is not None:
                    self.assertTrue(
                        decision.proceed,
                        f"a default hook short-circuited {tool}.{action}")
                    self.assertIsNone(decision.short_circuit_result)

    def test_a_dry_run_still_reaches_the_real_handler(self):
        """The end-to-end version: the tool's own dry-run path must run.

        `setup.set_defaults` validates its input and refuses a bad value. Under
        the interceptor it answered `success: true` to `result_envelope:
        "banana"` — a dry run of an operation that cannot succeed, reported as
        succeeding.
        """
        import src.server as compound

        out = compound.setup("set_defaults", {"result_envelope": "banana", "dry_run": True})
        self.assertIn("error", out)
        self.assertNotIn("simulated", out)

        ok = compound.setup("set_defaults", {"result_envelope": "pure", "dry_run": True})
        self.assertTrue(ok.get("dry_run"))
        self.assertNotIn("simulated", ok)

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

    def test_raw_graph_lut_mutations_are_high_risk_for_timeline_or_group(self):
        cases = (
            ("set_lut", {"node_index": 1, "lut_path": "look.cube"}, BlastRadius.TIMELINE),
            ("apply_arri_cdl_lut", {}, BlastRadius.TIMELINE),
            (
                "set_lut",
                {"node_index": 1, "lut_path": "look.cube", "source": "color_group_pre"},
                BlastRadius.PROJECT,
            ),
            ("apply_arri_cdl_lut", {"source": "color_group_post"}, BlastRadius.PROJECT),
        )
        for action, params, radius in cases:
            with self.subTest(action=action, source=params.get("source", "timeline")):
                assessment = classify_operation_risk("graph", action, params)
                self.assertEqual(assessment.level, RiskLevel.HIGH)
                self.assertTrue(assessment.destructive)
                self.assertTrue(assessment.confirmation_required)
                self.assertEqual(assessment.blast_radius, radius)

    def test_raw_graph_lut_mutations_stay_medium_for_item_source(self):
        for action, params in (
            ("set_lut", {"node_index": 1, "lut_path": "look.cube", "source": "item"}),
            ("apply_arri_cdl_lut", {"source": "item"}),
        ):
            with self.subTest(action=action):
                assessment = classify_operation_risk("graph", action, params)
                self.assertEqual(assessment.level, RiskLevel.MEDIUM)
                self.assertTrue(assessment.destructive)
                self.assertFalse(assessment.confirmation_required)
                self.assertEqual(assessment.blast_radius, BlastRadius.ITEM)

    def test_every_graph_action_reports_the_radius_of_its_source(self):
        """`source` picks the graph for EVERY graph mutation, so the radius is a
        property of the call: reset_all_grades on a color-group graph wipes the
        grade of every clip in the group, and must not read as one item."""
        expected = {
            None: BlastRadius.TIMELINE,
            "timeline": BlastRadius.TIMELINE,
            "item": BlastRadius.ITEM,
            "color_group_pre": BlastRadius.PROJECT,
            "color_group_post": BlastRadius.PROJECT,
        }
        levels = {
            "reset_all_grades": RiskLevel.HIGH,
            "apply_grade_from_drx": RiskLevel.HIGH,
            "set_node_enabled": RiskLevel.LOW,
        }
        for action, level in levels.items():
            for source, radius in expected.items():
                params = {} if source is None else {"source": source}
                with self.subTest(action=action, source=source):
                    assessment = classify_operation_risk("graph", action, params)
                    self.assertEqual(assessment.level, level)
                    self.assertEqual(assessment.blast_radius, radius)
                    self.assertTrue(assessment.recognised)
                    self.assertTrue(any("Graph target" in r for r in assessment.reasons))

    def test_reviewed_medium_band_actions_remain_established_medium(self):
        """Medium is a reviewed rating, not the classifier's fallthrough."""
        cases = (
            ("media_pool", "append_to_timeline", {}, BlastRadius.TIMELINE),
            ("media_pool", "auto_sync_audio", {}, BlastRadius.TIMELINE),
            ("media_pool", "move_clips", {}, BlastRadius.TIMELINE),
            ("media_pool", "move_folders", {}, BlastRadius.TIMELINE),
            ("media_pool", "setup_multicam_timeline", {}, BlastRadius.TIMELINE),
            ("timeline", "copy_clips", {}, BlastRadius.TIMELINE),
            ("timeline", "copy_range", {}, BlastRadius.TIMELINE),
            ("timeline", "duplicate_clips", {}, BlastRadius.TIMELINE),
            ("timeline", "duplicate_range", {}, BlastRadius.TIMELINE),
            ("timeline", "insert_fusion_composition", {}, BlastRadius.TIMELINE),
            ("timeline", "insert_fusion_generator", {}, BlastRadius.TIMELINE),
            ("timeline", "insert_fusion_title", {}, BlastRadius.TIMELINE),
            ("timeline", "insert_generator", {}, BlastRadius.TIMELINE),
            ("timeline", "insert_ofx_generator", {}, BlastRadius.TIMELINE),
            ("timeline", "insert_title", {}, BlastRadius.TIMELINE),
            ("timeline", "set_setting", {}, BlastRadius.TIMELINE),
            ("timeline", "set_start_timecode", {}, BlastRadius.TIMELINE),
            ("timeline", "set_voice_isolation_state", {}, BlastRadius.TIMELINE),
            ("timeline_ai", "analyze_dolby_vision", {}, BlastRadius.TIMELINE),
            ("timeline_ai", "create_subtitles", {}, BlastRadius.TIMELINE),
            ("timeline_item", "set_property", {}, BlastRadius.ITEM),
            ("timeline_item", "set_retime", {}, BlastRadius.ITEM),
            ("timeline_item", "set_voice_isolation_state", {}, BlastRadius.ITEM),
            ("timeline_item_color", "add_version", {}, BlastRadius.ITEM),
            ("timeline_item_color", "assign_color_group", {}, BlastRadius.ITEM),
            ("timeline_item_color", "create_magic_mask", {}, BlastRadius.ITEM),
            ("timeline_item_color", "load_version", {}, BlastRadius.ITEM),
            ("timeline_item_color", "regenerate_magic_mask", {}, BlastRadius.ITEM),
            ("timeline_item_color", "set_cdl", {}, BlastRadius.ITEM),
            ("timeline_item_color", "smart_reframe", {}, BlastRadius.ITEM),
            ("timeline_item_color", "stabilize", {}, BlastRadius.ITEM),
            ("timeline_item_fusion", "import_comp", {}, BlastRadius.ITEM),
            ("timeline_item_fusion", "load_comp", {}, BlastRadius.ITEM),
            ("graph", "set_lut", {"source": "item"}, BlastRadius.ITEM),
            ("graph", "apply_arri_cdl_lut", {"source": "item"}, BlastRadius.ITEM),
        )
        for tool, action, params, radius in cases:
            with self.subTest(action=f"{tool}.{action}", params=params):
                assessment = classify_operation_risk(tool, action, params)
                self.assertEqual(assessment.level, RiskLevel.MEDIUM)
                self.assertTrue(assessment.destructive)
                self.assertTrue(assessment.recognised)
                self.assertFalse(assessment.confirmation_required)
                self.assertEqual(assessment.blast_radius, radius)

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
            # Live pre-state was read — which is NOT the same as "a snapshot
            # exists to roll back to". This previously asserted
            # snapshot_available, deriving a rollback guarantee from having
            # read a project name.
            self.assertTrue(res["pre_state_available"])
            self.assertIsNone(res["snapshot_available"])

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
        self.assertIn("readback_verification", hook_names)
        self.assertNotIn("dry_run_interception", hook_names)
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
