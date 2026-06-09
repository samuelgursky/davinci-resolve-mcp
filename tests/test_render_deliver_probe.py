import os
import tempfile
import unittest

from src.server import (
    _prepare_render_job,
    _probe_render_matrix,
    _quick_export_capabilities,
    _render_capabilities,
    _render_job_lifecycle_probe,
    _safe_quick_export,
    _safe_set_render_settings,
    _validate_render_settings_action,
)


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
        self.codec_queries.append(render_format)
        if render_format == "mp4":
            return {"H.264": "H.264", "H.265": "H.265"}
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
        result = _validate_render_settings_action(
            {"settings": {"TargetDir": os.getcwd(), "SelectAllFrames": True}, "require_temp_target": True}
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

    def test_render_job_lifecycle_probe_deletes_probe_job(self):
        project = RenderProjectStub()
        result = _render_job_lifecycle_probe(project, {"target_dir": tempfile.gettempdir()})

        self.assertTrue(result["success"])
        self.assertEqual(project.deleted, ["job-1"])
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
