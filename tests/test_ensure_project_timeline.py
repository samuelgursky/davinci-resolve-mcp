import unittest
from unittest import mock

import src.server as s


def _clip(path="D:/media/source.mov"):
    clip = mock.Mock()
    clip.GetClipProperty.side_effect = lambda key="": path if key == "File Path" else {"File Path": path}
    clip.GetUniqueId.return_value = "clip-1"
    return clip


def _project(name="Post", timeline=None, clips=None, timeline_clips=None):
    project = mock.Mock()
    project.GetName.return_value = name
    project.GetTimelineCount.return_value = 1 if timeline else 0
    project.GetTimelineByIndex.side_effect = lambda index: timeline if index == 1 else None
    project.GetCurrentTimeline.return_value = timeline
    project.SetCurrentTimeline.return_value = True
    project.GetSetting.return_value = None
    project.SetSetting.return_value = True
    media_pool = mock.Mock()
    folder = mock.Mock()
    folder.GetClipList.return_value = list(clips or [])
    folder.GetSubFolderList.return_value = []
    media_pool.GetRootFolder.return_value = folder
    media_pool.ImportMedia.return_value = [_clip()]
    media_pool.CreateTimelineFromClips.return_value = timeline or mock.Mock()
    project.GetMediaPool.return_value = media_pool
    if timeline is not None:
        placed = []
        for clip in list(timeline_clips if timeline_clips is not None else (clips or [])):
            item = mock.Mock()
            item.GetMediaPoolItem.return_value = clip
            placed.append(item)
        timeline.GetTrackCount.side_effect = lambda track_type: 1 if track_type == "video" else 0
        timeline.GetItemListInTrack.side_effect = lambda track_type, index: placed if track_type == "video" and index == 1 else []
    return project


class EnsureProjectTimelineTest(unittest.TestCase):
    def _params(self, **extra):
        return {
            "project_name": "Post",
            "timeline_name": "IG Reel",
            "source_path": "D:/media/source.mov",
            "settings": {"timelineResolutionWidth": "1080", "timelineResolutionHeight": "1920"},
            **extra,
        }

    @mock.patch("src.server.os.path.isfile", return_value=True)
    def test_defaults_to_non_mutating_plan(self, _isfile):
        pm = mock.Mock()
        pm.GetProjectListInCurrentFolder.return_value = []
        out = s._ensure_project_timeline(mock.Mock(), pm, self._params())
        self.assertTrue(out["success"], out)
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["stages"][0]["status"], "planned")
        pm.CreateProject.assert_not_called()

    @mock.patch("src.server.os.path.isfile", return_value=True)
    def test_execute_creates_project_imports_source_and_builds_timeline(self, _isfile):
        timeline = mock.Mock()
        timeline.GetName.return_value = "IG Reel"
        project = _project(timeline=None)
        project.GetMediaPool().CreateTimelineFromClips.return_value = timeline
        pm = mock.Mock()
        pm.GetProjectListInCurrentFolder.return_value = []
        pm.CreateProject.return_value = project
        pm.SaveProject.return_value = True

        out = s._ensure_project_timeline(mock.Mock(), pm, self._params(execute=True))

        self.assertTrue(out["success"], out)
        self.assertEqual([row["status"] for row in out["stages"]], ["created", "applied", "imported", "created", "saved"])
        project.GetMediaPool().ImportMedia.assert_called_once_with(["D:/media/source.mov"])
        project.GetMediaPool().CreateTimelineFromClips.assert_called_once()

    @mock.patch("src.server.os.path.isfile", return_value=True)
    def test_execute_reuses_matching_project_media_and_timeline(self, _isfile):
        timeline = mock.Mock()
        timeline.GetName.return_value = "IG Reel"
        existing_clip = _clip()
        project = _project(timeline=timeline, clips=[existing_clip])
        pm = mock.Mock()
        pm.GetProjectListInCurrentFolder.return_value = ["Post"]
        pm.LoadProject.return_value = project
        pm.SaveProject.return_value = True

        out = s._ensure_project_timeline(mock.Mock(), pm, self._params(execute=True))

        self.assertTrue(out["success"], out)
        self.assertEqual([row["status"] for row in out["stages"]], ["reused", "applied", "reused", "reused", "saved"])
        project.GetMediaPool().ImportMedia.assert_not_called()
        project.GetMediaPool().CreateTimelineFromClips.assert_not_called()

    @mock.patch("src.server.os.path.isfile", return_value=True)
    def test_execute_reuses_exact_settings_without_writing_them(self, _isfile):
        timeline = mock.Mock()
        timeline.GetName.return_value = "IG Reel"
        existing_clip = _clip()
        project = _project(timeline=timeline, clips=[existing_clip])
        project.GetSetting.side_effect = lambda key: {
            "timelineResolutionWidth": "1080",
            "timelineResolutionHeight": "1920",
        }.get(key)
        pm = mock.Mock()
        pm.GetProjectListInCurrentFolder.return_value = ["Post"]
        pm.LoadProject.return_value = project
        pm.SaveProject.return_value = True

        out = s._ensure_project_timeline(mock.Mock(), pm, self._params(execute=True))

        self.assertTrue(out["success"], out)
        self.assertEqual(out["stages"][1]["status"], "reused")
        project.SetSetting.assert_not_called()

    @mock.patch("src.server.os.path.isfile", return_value=True)
    def test_conflicting_named_timeline_is_refused_before_project_mutation(self, _isfile):
        timeline = mock.Mock()
        timeline.GetName.return_value = "IG Reel"
        wanted_clip = _clip("D:/media/source.mov")
        other_clip = _clip("D:/media/other.mov")
        project = _project(
            timeline=timeline,
            clips=[wanted_clip, other_clip],
            timeline_clips=[other_clip],
        )
        pm = mock.Mock()
        pm.GetProjectListInCurrentFolder.return_value = ["Post"]
        pm.LoadProject.return_value = project

        out = s._ensure_project_timeline(mock.Mock(), pm, self._params(execute=True))

        self.assertFalse(out["success"], out)
        self.assertEqual(out["stages"][-1]["code"], "TIMELINE_SOURCE_CONFLICT")
        project.SetSetting.assert_not_called()
        project.GetMediaPool().ImportMedia.assert_not_called()
        pm.SaveProject.assert_not_called()

    @mock.patch("src.server.os.path.isfile", return_value=True)
    def test_missing_fairlight_preset_fails_before_project_creation(self, _isfile):
        resolve = mock.Mock()
        resolve.GetFairlightPresets.return_value = ["Podcast"]
        pm = mock.Mock()
        pm.GetProjectListInCurrentFolder.return_value = []

        out = s._ensure_project_timeline(
            resolve,
            pm,
            self._params(execute=True, fairlight_preset_name="IG Voice"),
        )

        self.assertEqual(out["error"]["code"], "FAIRLIGHT_PRESET_NOT_FOUND")
        pm.CreateProject.assert_not_called()

    @mock.patch("src.server.os.path.isfile", return_value=True)
    def test_failed_timeline_activation_blocks_preset_application(self, _isfile):
        timeline = mock.Mock()
        timeline.GetName.return_value = "IG Reel"
        timeline.GetUniqueId.return_value = "timeline-1"
        existing_clip = _clip()
        project = _project(timeline=timeline, clips=[existing_clip])
        project.SetCurrentTimeline.return_value = False
        pm = mock.Mock()
        pm.GetProjectListInCurrentFolder.return_value = ["Post"]
        pm.LoadProject.return_value = project
        resolve = mock.Mock()
        resolve.GetFairlightPresets.return_value = ["IG Voice"]

        out = s._ensure_project_timeline(
            resolve,
            pm,
            self._params(execute=True, fairlight_preset_name="IG Voice"),
        )

        self.assertFalse(out["success"], out)
        self.assertEqual(out["stages"][-1]["code"], "TIMELINE_ACTIVATION_FAILED")
        project.ApplyFairlightPresetToCurrentTimeline.assert_not_called()
        pm.SaveProject.assert_not_called()


if __name__ == "__main__":
    unittest.main()
