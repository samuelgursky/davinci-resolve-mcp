"""Off-by-one: granular/timeline and utils/project_properties report
duration as ``GetEndFrame() - GetStartFrame() + 1``, one frame more than the
real value.  server.py and scripts/render_stress.py both use the correct
``GetEndFrame() - GetStartFrame()`` form, and the Resolve mock in
test_variant_audio_accounting derives GetEndFrame from an item whose
``GetEnd() - GetStart() == GetDuration()`` — no +1.

A timeline spanning frames 86400..87000 has 600 frames; the buggy path
reports 601.
"""

import types
import unittest

import src.granular.timeline as gtimeline
import src.granular.common  as gcommon
import src.utils.project_properties as pp


# ── Stubs ────────────────────────────────────────────────────────────────────


class _FakeTimeline:
    def GetName(self):
        return "Main"

    def GetUniqueId(self):
        return "tl-main"

    def GetStartFrame(self):
        return 86400

    def GetEndFrame(self):
        return 87000

    def GetSetting(self, key):
        return {"timelineFrameRate": "24.0",
                "timelineResolutionWidth": "1920",
                "timelineResolutionHeight": "1080"}.get(key)

    def GetStartTimecode(self):
        return "01:00:00:00"


class _FakeProject:
    def __init__(self, tl):
        self._tl = tl

    def GetCurrentTimeline(self):
        return self._tl

    def GetName(self):
        return "TestProject"

    def GetTimelineCount(self):
        return 1

    def GetTimelineByIndex(self, idx):
        return self._tl if idx == 1 else None

    def GetSetting(self, key):
        return None

    def GetCurrentRenderFormatAndCodec(self):
        return {"format": "mp4", "codec": "H264"}


# ── Tests ────────────────────────────────────────────────────────────────────


class GranularTimelineDurationTest(unittest.TestCase):
    """get_current_timeline must report duration == EndFrame - StartFrame."""

    def setUp(self):
        self._tl = _FakeTimeline()
        self._proj = _FakeProject(self._tl)
        self._orig = gcommon.get_current_project
        gcommon.get_current_project = lambda: (object(), self._proj)
        # The granular module imports get_current_project via star-import,
        # so patch it there too.
        gtimeline.get_current_project = gcommon.get_current_project

    def tearDown(self):
        gcommon.get_current_project = self._orig
        gtimeline.get_current_project = self._orig

    def test_duration_equals_end_minus_start(self):
        out = gtimeline.get_current_timeline()
        expected = self._tl.GetEndFrame() - self._tl.GetStartFrame()  # 600
        self.assertEqual(out["duration"], expected,
                         f"duration should be {expected}, got {out['duration']}")


class ProjectPropertiesDurationTest(unittest.TestCase):
    """get_project_info must report duration == EndFrame - StartFrame."""

    def setUp(self):
        self._tl = _FakeTimeline()
        self._proj = _FakeProject(self._tl)

    def test_duration_equals_end_minus_start(self):
        info = pp.get_project_info(self._proj)
        expected = self._tl.GetEndFrame() - self._tl.GetStartFrame()  # 600
        tl_entry = info["timelines"][0]
        self.assertEqual(tl_entry["duration"], expected,
                         f"duration should be {expected}, got {tl_entry['duration']}")


if __name__ == "__main__":
    unittest.main()
