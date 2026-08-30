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


def _timeline(name="T", start=86400, items=()):
    """items: (start, end) tuples on video track 1."""
    tl = mock.Mock()
    tl.GetName.return_value = name
    tl.GetStartFrame.return_value = start
    tl.GetTrackCount.side_effect = lambda t: 1 if t == "video" else 0
    built = []
    for it_start, it_end in items:
        it = mock.Mock()
        it.GetStart.return_value = it_start
        it.GetEnd.return_value = it_end
        built.append(it)
    tl.GetItemListInTrack.side_effect = lambda t, i: built if t == "video" else []
    return tl


def _proj(jobs, status, timeline=None):
    proj = mock.Mock()
    proj.GetRenderJobStatus.return_value = status
    proj.GetRenderJobList.return_value = jobs
    if timeline is None:
        # A timeline whose items match the default job's 96-frame mark range.
        timeline = _timeline(items=[(86400, 86496)])
    proj.GetTimelineCount.return_value = 1
    proj.GetTimelineByIndex.side_effect = lambda i: timeline if i == 1 else None
    return proj


def _job(job_id="job-1", target_dir=None, filename="out.mov", **extra):
    payload = {"JobId": job_id, "TargetDir": target_dir, "OutputFilename": filename,
               "MarkIn": 86400, "MarkOut": 86495, "FrameRate": "24",
               "TimelineName": "T"}
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


class VerifyOutputStubDetectionTest(unittest.TestCase):
    """The issue #164 case where the job metadata lies along with JobStatus:
    Resolve rewrites the job's mark range down to the collapsed extent, so the
    only truthful readback is the timeline items themselves."""

    def _call(self, proj, params):
        with mock.patch.object(server, "_check", return_value=(mock.Mock(), proj, None)):
            return server.render("verify_output", params)

    def test_items_before_timeline_start_warn(self):
        tl = _timeline(start=86400, items=[(0, 96)])
        proj = _proj([_job(MarkIn=86400, MarkOut=86400)],
                     {"JobStatus": "Complete", "CompletionPercentage": 100},
                     timeline=tl)
        result = self._call(proj, {"job_id": "job-1"})
        self.assertFalse(result["verified"])
        self.assertTrue(any("before the timeline's" in w and "start frame" in w
                            for w in result["warnings"]), result["warnings"])

    def test_collapsed_mark_range_vs_item_extent_warns(self):
        tl = _timeline(start=86400, items=[(0, 96)])
        proj = _proj([_job(MarkIn=86400, MarkOut=86400)],
                     {"JobStatus": "Complete"}, timeline=tl)
        result = self._call(proj, {"job_id": "job-1"})
        self.assertEqual(result["mark_range_frames"], 1)
        self.assertEqual(result["timeline_item_extent_frames"], 96)
        self.assertTrue(any("rewrote the range" in w for w in result["warnings"]),
                        result["warnings"])

    def test_deliberate_single_frame_render_is_not_a_collapse(self):
        """A caller who states expected_frames=1 chose the short range — the
        collapse warning is for ranges Resolve rewrote, not ranges asked for."""
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not installed")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.mov")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi",
                            "-i", "testsrc=duration=0.042:size=128x72:rate=24",
                            "-y", out], check=True)
            tl = _timeline(start=86400, items=[(86400, 86520)])
            proj = _proj([_job(target_dir=tmp, MarkIn=86400, MarkOut=86400)],
                         {"JobStatus": "Complete"}, timeline=tl)
            result = self._call(proj, {"job_id": "job-1", "expected_frames": 1})
        self.assertTrue(result["verified"], result)
        self.assertEqual(result["warnings"], [])

    def test_unstated_short_range_still_warns(self):
        tl = _timeline(start=86400, items=[(86400, 86520)])
        proj = _proj([_job(MarkIn=86400, MarkOut=86400)],
                     {"JobStatus": "Complete"}, timeline=tl)
        result = self._call(proj, {"job_id": "job-1"})
        self.assertTrue(any("rewrote the range" in w for w in result["warnings"]))

    def test_missing_timeline_warns_instead_of_passing(self):
        proj = _proj([_job(TimelineName="RENAMED")], {"JobStatus": "Complete"})
        result = self._call(proj, {"job_id": "job-1"})
        self.assertFalse(result["verified"])
        self.assertTrue(any("was not found" in w for w in result["warnings"]))

    def test_caller_expected_frames_overrides_job_mark_range(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not installed")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.mov")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi",
                            "-i", "testsrc=duration=0.1:size=128x72:rate=24",
                            "-y", out], check=True)
            # Collapsed 1-frame job range would make the stub look clean;
            # the caller states the render should hold 96 frames.
            tl = _timeline(start=86400, items=[(0, 96)])
            proj = _proj([_job(target_dir=tmp, MarkIn=86400, MarkOut=86400)],
                         {"JobStatus": "Complete"}, timeline=tl)
            result = self._call(proj, {"job_id": "job-1", "expected_frames": 96})
        self.assertFalse(result["verified"])
        self.assertLess(result["duration_ratio"], 0.5)
        self.assertTrue(any("never visited" in w for w in result["warnings"]))


class SetTitleTextFusionFallbackTest(unittest.TestCase):
    """When SetProperty rejects every title key (Text+ on Studio 19.1.3), the
    setter writes StyledText on the TextPlus tool — unlocked, per the
    comp-lock render bug — and confirms by reading the input back."""

    def test_falls_back_to_fusion_comp_write(self):
        store = {}
        tool = mock.Mock()
        tool.SetInput.side_effect = lambda k, v: store.__setitem__(k, v)
        tool.GetInput.side_effect = lambda k: store.get(k)
        comp = mock.Mock()
        comp.GetToolList.return_value = {1: tool}
        item = mock.Mock()
        item.GetProperty.return_value = {"ZoomX": 1.0}
        item.SetProperty.return_value = False
        item.GetFusionCompCount.return_value = 1
        item.GetFusionCompByIndex.return_value = comp
        item.GetUniqueId.return_value = "item-1"
        tl = mock.Mock()
        tl.GetTrackCount.side_effect = lambda t: 1 if t == "video" else 0
        tl.GetItemListInTrack.side_effect = lambda t, i: [item] if t == "video" else []
        result = server._timeline_set_title_text(tl, {"clip_id": "item-1", "text": "VIA COMP"})
        self.assertTrue(result["success"], result)
        self.assertEqual(result["mode"], "fusion_comp")
        self.assertEqual(store["StyledText"], "VIA COMP")
        comp.Lock.assert_not_called()

    def test_no_textplus_tool_still_fails_with_guidance(self):
        item = mock.Mock()
        item.GetProperty.return_value = {"ZoomX": 1.0}
        item.SetProperty.return_value = False
        item.GetFusionCompCount.return_value = 0
        item.GetUniqueId.return_value = "item-1"
        tl = mock.Mock()
        tl.GetTrackCount.side_effect = lambda t: 1 if t == "video" else 0
        tl.GetItemListInTrack.side_effect = lambda t, i: [item] if t == "video" else []
        result = server._timeline_set_title_text(tl, {"clip_id": "item-1", "text": "X"})
        self.assertFalse(result["success"])
        self.assertIn("title_property_scan", result["error"])


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


class SafeQuickExportOutputCheckTest(unittest.TestCase):
    """RenderWithQuickExport's status dict is not trusted alone: a successful
    export must have produced a file in TargetDir."""

    def _run(self, tmp, status, write_file):
        proj = mock.Mock()

        def _render(preset, params):
            if write_file:
                with open(os.path.join(tmp, "out.mp4"), "wb") as fh:
                    fh.write(b"x" * 2048)
            return status

        proj.RenderWithQuickExport.side_effect = _render
        return server._safe_quick_export(proj, {
            "preset": "H.264 Master", "target_dir": tmp,
            "allow_render": True, "require_temp_target": False,
        })

    def test_success_with_no_file_is_flipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, {"JobStatus": "Complete"}, write_file=False)
        self.assertFalse(result["success"], result)
        self.assertIn("wrote no file", result["error"])

    def test_success_with_file_lists_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, {"JobStatus": "Complete"}, write_file=True)
        self.assertTrue(result["success"], result)
        self.assertEqual(len(result["outputs"]), 1)
        self.assertEqual(result["outputs"][0]["size_bytes"], 2048)
