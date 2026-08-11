import unittest
from unittest import mock

import src.server as s


class CompleteDeliveryJobTest(unittest.TestCase):
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
        with mock.patch.object(s, "_prepare_delivery_job", return_value=prepared):
            out = s._render_complete_delivery_job(project, {
                "profile": "instagram_reels", "target_dir": "D:/out", "execute": True,
                "poll_interval_seconds": 0, "max_wait_seconds": 2,
            })
        self.assertTrue(out["success"], out)
        self.assertEqual(out["job_id"], "job-1")
        self.assertEqual(out["status"]["JobStatus"], "Complete")
        project.StartRendering.assert_called_once_with(["job-1"], False)

    def test_resumes_completed_job_without_starting_it(self):
        project = mock.Mock()
        project.GetRenderJobStatus.return_value = {"JobStatus": "Complete", "OutputFilename": "D:/out/reel.mp4"}
        out = s._render_complete_delivery_job(project, {
            "profile": "instagram_reels", "job_id": "job-1", "execute": True,
            "qc_spec": {"video": {"width": 1080}},
        })
        self.assertTrue(out["success"], out)
        self.assertTrue(out["resumed"])
        project.StartRendering.assert_not_called()


if __name__ == "__main__":
    unittest.main()
