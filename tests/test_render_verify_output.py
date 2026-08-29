"""Tests for render.verify_output — the readback that catches JobStatus lying.

A render job whose content the engine never visits (e.g. clips placed before
the timeline start, issue #164) still reports Complete at 100% with a stub
output file. verify_output checks the actual file against the job's own mark
range.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from src import server


def _proj(jobs, status):
    proj = mock.Mock()
    proj.GetRenderJobStatus.return_value = status
    proj.GetRenderJobList.return_value = jobs
    return proj


def _job(job_id="job-1", target_dir=None, filename="out.mov", **extra):
    payload = {"JobId": job_id, "TargetDir": target_dir, "OutputFilename": filename,
               "MarkIn": 86400, "MarkOut": 86495, "FrameRate": "24"}
    payload.update(extra)
    return payload


class VerifyOutputTest(unittest.TestCase):
    def _call(self, proj, params):
        with mock.patch.object(server, "_check", return_value=(mock.Mock(), proj, None)):
            return server.render("verify_output", params)

    def test_requires_job_id(self):
        result = self._call(_proj([], {}), {})
        self.assertIn("error", result)

    def test_deleted_job_is_an_explicit_error(self):
        proj = _proj([], {"JobStatus": "Complete"})
        result = self._call(proj, {"job_id": "gone"})
        self.assertIn("error", result)
        self.assertIn("verify before deleting", str(result).lower())

    def test_complete_with_missing_file_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = _proj([_job(target_dir=tmp)], {"JobStatus": "Complete", "CompletionPercentage": 100})
            result = self._call(proj, {"job_id": "job-1"})
        self.assertFalse(result["verified"])
        self.assertFalse(result["output_exists"])
        self.assertTrue(any("does not exist" in w for w in result["warnings"]))

    def test_existing_full_length_output_verifies(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not installed")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.mov")
            # 96 frames at 24fps = 4s, matching MarkIn..MarkOut (86400..86495).
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi",
                            "-i", "testsrc=duration=4:size=128x72:rate=24",
                            "-y", out], check=True)
            proj = _proj([_job(target_dir=tmp)], {"JobStatus": "Complete", "CompletionPercentage": 100})
            result = self._call(proj, {"job_id": "job-1"})
        self.assertTrue(result["verified"], result)
        self.assertTrue(result["output_exists"])
        self.assertEqual(result["warnings"], [])
        self.assertGreater(result["duration_ratio"], 0.9)

    def test_stub_output_from_content_before_timeline_start_warns(self):
        """The issue #164 signature: Complete at 100%, near-empty file."""
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not installed")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.mov")
            # 0.1s stub against a 4s mark range.
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi",
                            "-i", "testsrc=duration=0.1:size=128x72:rate=24",
                            "-y", out], check=True)
            proj = _proj([_job(target_dir=tmp)], {"JobStatus": "Complete", "CompletionPercentage": 100})
            result = self._call(proj, {"job_id": "job-1"})
        self.assertFalse(result["verified"])
        self.assertTrue(result["output_exists"])
        self.assertLess(result["duration_ratio"], 0.5)
        self.assertTrue(any("never visited" in w for w in result["warnings"]))

    def test_job_without_target_dir_warns_instead_of_crashing(self):
        proj = _proj([_job(target_dir=None, filename=None)], {"JobStatus": "Complete"})
        result = self._call(proj, {"job_id": "job-1"})
        self.assertFalse(result["verified"])
        self.assertIsNone(result["output_path"])
        self.assertTrue(any("TargetDir" in w for w in result["warnings"]))


class GetTitleTextFusionFallbackTest(unittest.TestCase):
    """When GetProperty exposes no title keys (Text+ on Studio 19.1.3), the
    getter falls back to the TextPlus tool's StyledText in the Fusion comp."""

    def test_falls_back_to_fusion_comp(self):
        tool = mock.Mock()
        tool.GetInput.return_value = "COMP FALLBACK TEXT"
        comp = mock.Mock()
        comp.GetToolList.return_value = {1: tool}
        item = mock.Mock()
        item.GetProperty.return_value = {"ZoomX": 1.0}
        item.GetFusionCompCount.return_value = 1
        item.GetFusionCompByIndex.return_value = comp
        item.GetUniqueId.return_value = "item-1"
        tl = mock.Mock()
        tl.GetTrackCount.side_effect = lambda t: 1 if t == "video" else 0
        tl.GetItemListInTrack.side_effect = lambda t, i: [item] if t == "video" else []
        result = server._timeline_get_title_text(tl, {"clip_id": "item-1"})
        self.assertTrue(result["success"])
        self.assertEqual(result["text"], "COMP FALLBACK TEXT")
        self.assertEqual(result["source"], "fusion_comp")
        tool.GetInput.assert_called_with("StyledText")


if __name__ == "__main__":
    unittest.main()
