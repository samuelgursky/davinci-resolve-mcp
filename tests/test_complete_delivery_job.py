import unittest
import os
from unittest import mock

import src.server as s


class CompleteDeliveryJobTest(unittest.TestCase):
    def _resume_project(self, status):
        timeline = mock.Mock()
        timeline.GetName.return_value = "IG Reel"
        timeline.GetUniqueId.return_value = "timeline-1"
        timeline.GetSetting.return_value = "30"
        project = mock.Mock()
        project.GetCurrentTimeline.return_value = timeline
        project.GetRenderJobList.return_value = [{
            "JobId": "job-1",
            "TimelineName": "IG Reel",
            "TargetDir": "D:/out",
            "OutputFilename": "reel.mp4",
            "Format": "mp4",
            "Codec": "H264",
        }]
        project.GetRenderJobStatus.return_value = status
        return project

    def test_defaults_to_dry_run(self):
        project = mock.Mock()
        with mock.patch.object(s, "_prepare_delivery_job", return_value={"success": True, "qc_spec": {"video": {"width": 1080}}}) as prepare:
            out = s._render_complete_delivery_job(project, {"profile": "instagram_reels", "target_dir": "D:/out"})
        self.assertTrue(out["success"], out)
        self.assertTrue(out["dry_run"])
        self.assertTrue(prepare.call_args.args[1]["dry_run"])
        project.StartRendering.assert_not_called()

    def test_prepares_starts_and_waits_for_completion(self):
        project = mock.Mock()
        project.StartRendering.return_value = True
        project.GetRenderJobStatus.side_effect = [
            {"JobStatus": "Rendering in Progress", "CompletionPercentage": 40},
            {"JobStatus": "Complete", "CompletionPercentage": 100, "OutputFilename": "D:/out/reel.mp4"},
        ]
        prepared = {"success": True, "job_id": "job-1", "qc_spec": {"video": {"width": 1080}}}
        with mock.patch.object(s, "_prepare_delivery_job", return_value=prepared), \
             mock.patch.object(s, "_delivery_output_qc", return_value={"success": True, "status": "passed"}):
            out = s._render_complete_delivery_job(project, {
                "profile": "instagram_reels", "target_dir": "D:/out", "execute": True,
                "poll_interval_seconds": 0, "max_wait_seconds": 2,
            })
        self.assertTrue(out["success"], out)
        self.assertEqual(out["job_id"], "job-1")
        self.assertTrue(out["terminal"])
        self.assertEqual(out["status"]["JobStatus"], "Complete")
        project.StartRendering.assert_called_once_with(["job-1"], False)

    def test_resumes_completed_job_without_starting_it(self):
        project = self._resume_project({"JobStatus": "Complete"})
        resolved = {"target": "h264_vertical_1080_web", "format_id": "mp4", "codec_id": "H264", "qc_spec": {"video": {"width": 1080}}}
        with mock.patch.object(s, "_resolve_delivery_target_live", return_value=(resolved, None)), \
             mock.patch.object(s, "_delivery_output_qc", return_value={"success": True, "status": "passed"}):
            out = s._render_complete_delivery_job(project, {
                "profile": "instagram_reels", "job_id": "job-1", "execute": True,
            })
        self.assertTrue(out["success"], out)
        self.assertTrue(out["resumed"])
        self.assertEqual(os.path.normpath(out["output_path"]), os.path.normpath("D:/out/reel.mp4"))
        project.StartRendering.assert_not_called()

    def test_resumes_running_job_without_starting_it_again(self):
        project = self._resume_project({"JobStatus": "Rendering in Progress", "CompletionPercentage": 40})
        project.GetRenderJobStatus.side_effect = [
            {"JobStatus": "Rendering in Progress", "CompletionPercentage": 40},
            {"JobStatus": "Complete", "CompletionPercentage": 100},
        ]
        resolved = {"target": "h264_vertical_1080_web", "format_id": "mp4", "codec_id": "H264", "qc_spec": {}}
        with mock.patch.object(s, "_resolve_delivery_target_live", return_value=(resolved, None)), \
             mock.patch.object(s, "_delivery_output_qc", return_value={"success": True, "status": "passed"}):
            out = s._render_complete_delivery_job(project, {
                "profile": "instagram_reels",
                "job_id": "job-1",
                "execute": True,
                "poll_interval_seconds": 0,
                "max_wait_seconds": 2,
            })

        self.assertTrue(out["success"], out)
        self.assertTrue(out["resumed"])
        project.StartRendering.assert_not_called()

    @mock.patch.object(s, "_probe_media_file", return_value={"success": True, "video": {"width": 1080}})
    @mock.patch.object(s.os.path, "isfile", return_value=True)
    def test_empty_qc_spec_is_unavailable_not_a_false_pass(self, _isfile, _probe):
        out = s._delivery_output_qc("D:/out/reel.mp4", {})

        self.assertFalse(out["success"], out)
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["code"], "QC_SPEC_UNAVAILABLE")

    def test_timeout_reports_non_terminal_retryable_state(self):
        project = self._resume_project({
            "JobStatus": "Rendering in Progress",
            "CompletionPercentage": 40,
        })
        resolved = {"target": "h264_vertical_1080_web", "format_id": "mp4", "codec_id": "H264", "qc_spec": {"video": {"width": 1080}}}
        with mock.patch.object(s, "_resolve_delivery_target_live", return_value=(resolved, None)):
            out = s._render_complete_delivery_job(project, {
                "profile": "instagram_reels",
                "job_id": "job-1",
                "execute": True,
                "poll_interval_seconds": 0,
                "max_wait_seconds": 0,
            })

        self.assertFalse(out["success"], out)
        self.assertFalse(out["terminal"])
        self.assertTrue(out["retryable"])

    def test_resume_without_execute_never_starts_queued_job(self):
        project = self._resume_project({"JobStatus": "Ready"})
        resolved = {"target": "h264_vertical_1080_web", "format_id": "mp4", "codec_id": "H264", "qc_spec": {"video": {"width": 1080}}}
        with mock.patch.object(s, "_resolve_delivery_target_live", return_value=(resolved, None)):
            out = s._render_complete_delivery_job(project, {
                "profile": "instagram_reels", "job_id": "job-1",
            })

        self.assertTrue(out["dry_run"], out)
        self.assertTrue(out["would_start"])
        project.StartRendering.assert_not_called()

    def test_resume_rejects_job_for_another_timeline(self):
        project = self._resume_project({"JobStatus": "Ready"})
        project.GetRenderJobList.return_value[0]["TimelineName"] = "Landscape Master"
        resolved = {"target": "h264_vertical_1080_web", "format_id": "mp4", "codec_id": "H264", "qc_spec": {"video": {"width": 1080}}}
        with mock.patch.object(s, "_resolve_delivery_target_live", return_value=(resolved, None)):
            out = s._render_complete_delivery_job(project, {
                "profile": "instagram_reels", "job_id": "job-1", "execute": True,
            })

        self.assertEqual(out["error"]["code"], "RENDER_JOB_IDENTITY_MISMATCH")
        project.StartRendering.assert_not_called()

    @mock.patch.object(s.os.path, "isfile", return_value=True)
    def test_full_qc_contract_checks_container_fps_and_audio(self, _isfile):
        probe = {
            "success": True,
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
            "video": {"codec_name": "h264", "width": 1080, "height": 1920, "avg_frame_rate": "24/1"},
            "audio": {"codec_name": "aac", "channels": 2, "sample_rate": "48000", "bits_per_sample": 16},
        }
        spec = {
            "container": "mov",
            "video": {"codec": "h264", "width": 1080, "height": 1920, "fps": 30},
            "audio": {"codec": "aac", "channels": 2, "sampleRate": 48000, "bitDepth": 16},
        }
        with mock.patch.object(s, "_probe_media_file", return_value=probe):
            out = s._delivery_output_qc("D:/out/reel.mp4", spec)

        self.assertFalse(out["success"], out)
        failed = [row["field"] for row in out["checks"] if not row["pass"]]
        self.assertEqual(failed, ["video.fps"])

    def test_completed_render_with_failed_qc_is_not_delivery_success(self):
        project = self._resume_project({"JobStatus": "Complete"})
        resolved = {"target": "h264_vertical_1080_web", "format_id": "mp4", "codec_id": "H264", "qc_spec": {"video": {"width": 1080}}}
        with mock.patch.object(s, "_resolve_delivery_target_live", return_value=(resolved, None)), \
             mock.patch.object(s, "_delivery_output_qc", return_value={"success": False, "status": "failed"}):
            out = s._render_complete_delivery_job(project, {
                "profile": "instagram_reels", "job_id": "job-1", "execute": True,
            })

        self.assertTrue(out["render_success"])
        self.assertFalse(out["qc_success"])
        self.assertFalse(out["success"])


if __name__ == "__main__":
    unittest.main()
