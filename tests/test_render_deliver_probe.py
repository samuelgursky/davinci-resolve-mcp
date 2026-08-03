import tempfile
import unittest

from src.server import (
    _list_delivery_targets,
    _prepare_delivery_job,
    _prepare_render_job,
    _probe_render_matrix,
    _resolve_delivery_target_live,
    _quick_export_capabilities,
    _render_capabilities,
    _render_codec_id,
    _render_job_lifecycle_probe,
    _safe_quick_export,
    _safe_set_render_settings,
    _validate_render_settings_action,
)
from tests._paths import NON_TEMP_EXISTING_DIR


class RenderProjectStub:
    def __init__(self):
        self.settings = {
            "TargetDir": tempfile.gettempdir(),
            "CustomName": "stub_render",
            "SelectAllFrames": True,
        }
        self.format_codec = {"format": "mp4", "codec": "H.264"}
        self.mode = 0
        self.jobs = {}
        self.deleted = []
        self.quick_export_calls = []
        self.codec_queries = []
        self.resolution_queries = []

    def AddRenderJob(self):
        job_id = f"job-{len(self.jobs) + 1}"
        self.jobs[job_id] = {"JobId": job_id, "Status": "Queued"}
        return job_id

    def DeleteRenderJob(self, job_id):
        self.deleted.append(job_id)
        return self.jobs.pop(job_id, None) is not None

    def DeleteAllRenderJobs(self):
        self.jobs.clear()
        return True

    def GetRenderJobList(self):
        return list(self.jobs.values())

    def GetRenderJobStatus(self, job_id):
        return self.jobs.get(job_id, {"Status": "Missing"})

    def StartRendering(self, *args):
        return True

    def StopRendering(self):
        return None

    def IsRenderingInProgress(self):
        return False

    def GetRenderFormats(self):
        return {"mp4": "mp4", "QuickTime": "mov"}

    def GetRenderCodecs(self, render_format):
        # Values are the REAL ids from Resolve Studio 19.1.3.7 (probed 2026-07-27).
        # Note H.264 -> "H264": the description and the id differ here too, so a
        # fixture using {"H.264": "H.264"} understates the codec-id bug.
        self.codec_queries.append(render_format)
        if render_format == "mp4":
            return {"H.264": "H264", "H.265": "H265"}
        if render_format == "mov":
            return {
                "Apple ProRes 422 LT": "ProRes422LT",
                "Apple ProRes 422 HQ": "ProRes422HQ",
            }
        return {}

    def GetRenderResolutions(self, render_format, codec):
        self.resolution_queries.append((render_format, codec))
        return [{"Width": 1920, "Height": 1080}]

    def GetCurrentRenderFormatAndCodec(self):
        return dict(self.format_codec)

    def SetCurrentRenderFormatAndCodec(self, render_format, codec):
        self.format_codec = {"format": render_format, "codec": codec}
        return True

    def GetCurrentRenderMode(self):
        return self.mode

    def SetCurrentRenderMode(self, mode):
        self.mode = mode
        return True

    def GetRenderSettings(self):
        return dict(self.settings)

    def SetRenderSettings(self, settings):
        self.settings.update(settings)
        return True

    def GetRenderPresetList(self):
        return ["H.264 Master"]

    def LoadRenderPreset(self, name):
        return True

    def SaveAsNewRenderPreset(self, name):
        return True

    def DeleteRenderPreset(self, name):
        return True

    def GetQuickExportRenderPresets(self):
        return ["H.264 Master"]

    def RenderWithQuickExport(self, preset, params):
        self.quick_export_calls.append({"preset": preset, "params": params})
        return {"Status": "Queued"}


class RenderDeliverProbeTest(unittest.TestCase):
    def test_render_capabilities_exposes_methods_and_guards(self):
        capabilities = _render_capabilities(RenderProjectStub())

        self.assertTrue(capabilities["methods"]["AddRenderJob"])
        self.assertEqual(capabilities["format_count"], 2)
        self.assertIn("TargetDir", capabilities["supported_settings"])
        self.assertTrue(capabilities["guards"]["upload_disabled_for_safe_quick_export"])

    def test_probe_render_matrix_collects_codecs_and_resolutions(self):
        matrix = _probe_render_matrix(RenderProjectStub(), {"max_pairs": 2})

        self.assertEqual(matrix["format_total"], 2)
        self.assertEqual(matrix["pairs_probed"], 2)
        self.assertEqual(matrix["matrix"][0]["codecs"][0]["resolution_count"], 1)

    def test_probe_render_matrix_uses_render_format_id_for_display_name(self):
        project = RenderProjectStub()

        matrix = _probe_render_matrix(project, {"formats": ["QuickTime"]})

        self.assertEqual(matrix["pairs_probed"], 2)
        self.assertEqual(matrix["matrix"][0]["format"], "QuickTime")
        self.assertEqual(matrix["matrix"][0]["extension"], "mov")
        self.assertEqual(matrix["matrix"][0]["codecs"][0]["codec"], "ProRes422LT")
        self.assertEqual(project.codec_queries, ["mov"])
        self.assertEqual(project.resolution_queries[0], ("mov", "ProRes422LT"))

    def test_validate_render_settings_requires_temp_target_when_requested(self):
        # Not os.getcwd() — under a worktree in /tmp that IS a temp target and
        # the guard correctly permits it. The directory has to exist, or the
        # validator reports "does not exist" and never reaches the temp check.
        # See tests/_paths.py.
        result = _validate_render_settings_action(
            {"settings": {"TargetDir": NON_TEMP_EXISTING_DIR, "SelectAllFrames": True},
             "require_temp_target": True}
        )

        self.assertFalse(result["valid"])
        self.assertIn("TargetDir must be under the system temp directory", result["errors"][0])

    def test_safe_set_render_settings_reports_diff_and_restores(self):
        project = RenderProjectStub()
        result = _safe_set_render_settings(
            project,
            {
                "settings": {"TargetDir": tempfile.gettempdir(), "CustomName": "deliver_probe"},
                "require_temp_target": True,
                "restore": True,
            },
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["diff"]["matched"], ["CustomName", "TargetDir"])
        self.assertTrue(result["restore_success"])

    def test_prepare_render_job_adds_job_with_temp_target(self):
        project = RenderProjectStub()
        result = _prepare_render_job(
            project,
            {
                "target_dir": tempfile.gettempdir(),
                "custom_name": "deliver_job",
                "format": "mp4",
                "codec": "H.264",
            },
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["job_id"], "job-1")
        self.assertEqual(project.format_codec["format"], "mp4")

    def test_prepare_render_job_normalizes_display_format_name(self):
        project = RenderProjectStub()

        result = _prepare_render_job(
            project,
            {
                "target_dir": tempfile.gettempdir(),
                "custom_name": "prores_lt_proxy",
                "format": "QuickTime",
                "codec": "ProRes422LT",
            },
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["format_success"])
        self.assertEqual(project.format_codec, {"format": "mov", "codec": "ProRes422LT"})

    def test_prepare_render_job_normalizes_display_codec_name(self):
        """Codec display names must resolve to ids, like formats do.

        Live-confirmed on Resolve Studio 19.1.3.7: the description and id differ
        for BOTH families ('Apple ProRes 422 HQ'->'ProRes422HQ', 'H.264'->'H264'),
        and SetCurrentRenderFormatAndCodec rejects the description in each case.
        """
        project = RenderProjectStub()

        result = _prepare_render_job(
            project,
            {
                "target_dir": tempfile.gettempdir(),
                "custom_name": "prores_hq_master",
                "format": "QuickTime",
                "codec": "Apple ProRes 422 HQ",
            },
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["format_success"])
        self.assertEqual(project.format_codec, {"format": "mov", "codec": "ProRes422HQ"})

    def test_prepare_render_job_refuses_to_queue_when_format_codec_rejected(self):
        """A rejected format/codec must not leave a job queued in the previous codec."""

        class RejectingStub(RenderProjectStub):
            def SetCurrentRenderFormatAndCodec(self, render_format, codec):
                return False

        project = RejectingStub()
        result = _prepare_render_job(
            project,
            {
                "target_dir": tempfile.gettempdir(),
                "custom_name": "bogus",
                "format": "QuickTime",
                "codec": "NotARealCodec",
            },
        )

        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], "RENDER_FORMAT_CODEC_REJECTED")
        self.assertEqual(result["error"]["category"], "invalid_input")
        self.assertEqual(result["error"]["state"]["resolved_format_id"], "mov")
        self.assertIn("Apple ProRes 422 HQ", result["error"]["state"]["available_codecs"])
        self.assertEqual(project.jobs, {}, "no job may be queued when the codec was rejected")

    def test_render_codec_id_accepts_label_id_and_unknown(self):
        project = RenderProjectStub()

        self.assertEqual(_render_codec_id(project, "QuickTime", "Apple ProRes 422 LT"), "ProRes422LT")
        self.assertEqual(_render_codec_id(project, "mov", "ProRes422HQ"), "ProRes422HQ")
        self.assertEqual(_render_codec_id(project, "mp4", "H.264"), "H264")
        # Unknown codecs pass through unchanged for Resolve to reject.
        self.assertEqual(_render_codec_id(project, "mov", "Nope"), "Nope")

    def test_render_job_lifecycle_probe_deletes_probe_job(self):
        project = RenderProjectStub()
        result = _render_job_lifecycle_probe(project, {"target_dir": tempfile.gettempdir()})

        self.assertTrue(result["success"])
        self.assertEqual(project.deleted, ["job-1"])


class TimelineStub:
    def __init__(self, fps="23.976"):
        self._fps = fps

    def GetSetting(self, key):
        return self._fps if key == "timelineFrameRate" else None


_UNSET = object()


class DeliveryTargetProjectStub(RenderProjectStub):
    """Render stub that also answers GetCurrentTimeline, for fps inheritance."""

    def __init__(self, timeline=_UNSET):
        super().__init__()
        self._timeline = TimelineStub() if timeline is _UNSET else timeline

    def GetCurrentTimeline(self):
        return self._timeline


class DeliveryTargetTest(unittest.TestCase):
    def test_resolve_maps_target_to_live_format_and_codec_ids(self):
        project = DeliveryTargetProjectStub()

        resolved, err = _resolve_delivery_target_live(project, {"target": "prores422hq_master"})

        self.assertIsNone(err)
        self.assertEqual(resolved["format_id"], "mov")
        self.assertEqual(resolved["codec_id"], "ProRes422HQ")
        self.assertEqual(resolved["target"], "prores422hq_master")

    def test_platform_alias_resolves(self):
        resolved, err = _resolve_delivery_target_live(DeliveryTargetProjectStub(), {"target": "youtube"})

        self.assertIsNone(err)
        self.assertEqual((resolved["format_id"], resolved["codec_id"]), ("mp4", "H264"))
        self.assertEqual(resolved["settings"]["FormatWidth"], 1920)

    def test_master_inherits_timeline_fps_into_settings_and_qc_spec(self):
        resolved, _ = _resolve_delivery_target_live(
            DeliveryTargetProjectStub(), {"target": "prores422hq_master"}
        )

        self.assertAlmostEqual(resolved["timeline_fps"], 23.976)
        self.assertAlmostEqual(resolved["settings"]["FrameRate"], 23.976)
        self.assertAlmostEqual(resolved["qc_spec"]["video"]["fps"], 23.976)

    def test_missing_timeline_does_not_break_resolution(self):
        resolved, err = _resolve_delivery_target_live(
            DeliveryTargetProjectStub(timeline=None), {"target": "youtube"}
        )

        self.assertIsNone(err)
        self.assertIsNone(resolved["timeline_fps"])

    def test_unknown_target_errors_with_the_known_list(self):
        _, err = _resolve_delivery_target_live(DeliveryTargetProjectStub(), {"target": "betamax"})

        self.assertEqual(err["error"]["code"], "UNKNOWN_DELIVERY_TARGET")
        self.assertIn("prores422hq_master", err["error"]["state"]["known_targets"])

    def test_missing_target_param_errors(self):
        _, err = _resolve_delivery_target_live(DeliveryTargetProjectStub(), {})

        self.assertEqual(err["error"]["code"], "MISSING_TARGET")

    def test_unavailable_codec_errors_with_what_this_machine_has(self):
        """The stub exposes no DNxHR, standing in for a license/plugin gap."""
        _, err = _resolve_delivery_target_live(
            DeliveryTargetProjectStub(), {"target": "dnxhr_hqx_master"}
        )

        self.assertEqual(err["error"]["code"], "DELIVERY_TARGET_CODEC_UNAVAILABLE")
        self.assertEqual(err["error"]["category"], "unsupported")
        self.assertIn("Apple ProRes 422 HQ", err["error"]["state"]["available_codecs"])

    def test_unavailable_format_errors_before_codec_lookup(self):
        _, err = _resolve_delivery_target_live(
            DeliveryTargetProjectStub(),
            {"target": "prores422hq_master", "overrides": {"format_candidates": ["Betamax"]}},
        )

        self.assertEqual(err["error"]["code"], "DELIVERY_TARGET_FORMAT_UNAVAILABLE")
        self.assertIn("available_formats", err["error"]["state"])

    def test_overrides_flow_through_to_settings(self):
        resolved, _ = _resolve_delivery_target_live(
            DeliveryTargetProjectStub(), {"target": "youtube", "overrides": {"width": 1280, "height": 720}}
        )

        self.assertEqual(resolved["settings"]["FormatWidth"], 1280)
        self.assertEqual(resolved["qc_spec"]["video"]["width"], 1280)

    def test_sequence_target_reports_no_qc_spec_with_a_reason(self):
        project = DeliveryTargetProjectStub()
        project.GetRenderFormats = lambda: {"DPX": "dpx"}
        project.GetRenderCodecs = lambda fmt: {"RGB 10 bits": "RGB10"}

        resolved, err = _resolve_delivery_target_live(project, {"target": "dpx_sequence"})

        self.assertIsNone(err)
        self.assertIsNone(resolved["qc_spec"])
        self.assertIn("single file", resolved["qc_note"])

    def test_list_targets_reports_availability_against_the_live_matrix(self):
        result = _list_delivery_targets(DeliveryTargetProjectStub(), {"check_availability": True})

        targets = result["targets"]
        self.assertTrue(targets["prores422hq_master"]["available"])
        self.assertTrue(targets["h264_1080p_web"]["available"])
        self.assertFalse(targets["dnxhr_hqx_master"]["available"])
        self.assertIn("codec", targets["dnxhr_hqx_master"]["unavailable_reason"])
        self.assertFalse(targets["dpx_sequence"]["available"])
        self.assertIn("format", targets["dpx_sequence"]["unavailable_reason"])

    def test_list_targets_without_availability_does_not_touch_the_matrix(self):
        project = DeliveryTargetProjectStub()
        result = _list_delivery_targets(project, {})

        self.assertFalse(result["availability_checked"])
        self.assertEqual(project.codec_queries, [])
        self.assertNotIn("available", result["targets"]["prores422hq_master"])

    def test_list_targets_filters_by_tier(self):
        result = _list_delivery_targets(DeliveryTargetProjectStub(), {"tier": "web"})

        self.assertTrue(all(e["tier"] == "web" for e in result["targets"].values()))
        self.assertNotIn("prores422hq_master", result["targets"])

    def test_list_targets_rejects_an_unknown_tier(self):
        result = _list_delivery_targets(DeliveryTargetProjectStub(), {"tier": "bogus"})

        self.assertEqual(result["error"]["code"], "UNKNOWN_DELIVERY_TIER")

    def test_prepare_delivery_job_queues_with_resolved_ids_and_carries_the_qc_spec(self):
        project = DeliveryTargetProjectStub()

        result = _prepare_delivery_job(
            project,
            {
                "target": "prores422hq_master",
                "target_dir": tempfile.gettempdir(),
                "custom_name": "ep01_master",
            },
        )

        self.assertTrue(result["success"])
        self.assertEqual(project.format_codec, {"format": "mov", "codec": "ProRes422HQ"})
        self.assertEqual(result["delivery_target"], "prores422hq_master")
        self.assertEqual(result["qc_spec"]["video"]["codec"], "prores")
        self.assertEqual(project.settings["CustomName"], "ep01_master")

    def test_prepare_delivery_job_lets_explicit_settings_win_over_the_target(self):
        project = DeliveryTargetProjectStub()

        result = _prepare_delivery_job(
            project,
            {
                "target": "youtube",
                "target_dir": tempfile.gettempdir(),
                "settings": {"FormatWidth": 1280, "FormatHeight": 720},
            },
        )

        self.assertTrue(result["success"])
        self.assertEqual(project.settings["FormatWidth"], 1280)

    def test_prepare_delivery_job_does_not_queue_when_the_target_is_unavailable(self):
        project = DeliveryTargetProjectStub()

        result = _prepare_delivery_job(
            project, {"target": "dnxhr_hqx_master", "target_dir": tempfile.gettempdir()}
        )

        self.assertEqual(result["error"]["code"], "DELIVERY_TARGET_CODEC_UNAVAILABLE")
        self.assertEqual(project.jobs, {})
        self.assertEqual(project.GetRenderJobList(), [])

    def test_safe_quick_export_dry_run_forces_upload_off(self):
        project = RenderProjectStub()
        result = _safe_quick_export(
            project,
            {
                "preset": "H.264 Master",
                "target_dir": tempfile.gettempdir(),
                "custom_name": "quick_export_probe",
                "dry_run": True,
            },
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["params"]["EnableUpload"])
        self.assertEqual(project.quick_export_calls, [])

    def test_safe_quick_export_requires_allow_render_for_execution(self):
        project = RenderProjectStub()
        result = _safe_quick_export(
            project,
            {
                "preset": "H.264 Master",
                "target_dir": tempfile.gettempdir(),
                "custom_name": "quick_export_probe",
            },
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["would_render"])
        self.assertEqual(project.quick_export_calls, [])

    def test_quick_export_capabilities_lists_presets(self):
        capabilities = _quick_export_capabilities(RenderProjectStub())

        self.assertEqual(capabilities["preset_count"], 1)
        self.assertTrue(capabilities["guards"]["EnableUpload_forced_false"])


if __name__ == "__main__":
    unittest.main()
