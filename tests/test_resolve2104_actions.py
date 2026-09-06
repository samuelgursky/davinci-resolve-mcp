"""Contract tests for the Resolve 21.0.4 scripting-API additions (issue #131).

Covers the three surfaces wired in this release:
  - media_pool_item: get_timeline (MediaPoolItem.GetTimeline), including the
    not-a-timeline answer and the pre-21.0.4 version guard
  - the timeline selection probe preferring the documented GetSelectedClips
  - render set_settings surfacing the AddFrameHandles/UseFullExtents no-op

The 21.0.4 methods are unavailable on the 19.1.3 baseline this suite runs
against, so every case here is a stub contract, not a live result.
"""
import unittest

import src.server as compound


# ── Stubs ────────────────────────────────────────────────────────────────────


class TimelineObj:
    def __init__(self, name="SEQ_01", uid="tl-1", start=86400, end=87000):
        self._name, self._uid, self._start, self._end = name, uid, start, end

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return self._uid

    def GetStartFrame(self):
        return self._start

    def GetEndFrame(self):
        return self._end


class Clip2104:
    """A MediaPoolItem from a 21.0.4+ build, standing in for a timeline entry."""

    def __init__(self, timeline=None, cid="c1"):
        self._timeline = timeline
        self._id = cid

    def GetName(self):
        return "SEQ_01"

    def GetUniqueId(self):
        return self._id

    def GetTimeline(self):
        return self._timeline


class LegacyClip:
    """A MediaPoolItem from a pre-21.0.4 build — no GetTimeline at all."""

    def GetName(self):
        return "shot_010.mov"

    def GetUniqueId(self):
        return "L1"


class MediaPoolStub:
    def GetRootFolder(self):
        return object()


class SelectionTimeline:
    """A Timeline exposing several selection method names at once.

    A real build exposes one of them; this asserts which name the probe reaches
    for first, which is the whole point of the 21.0.4 reorder.
    """

    def __init__(self):
        self.calls = []

    def GetSelectedClips(self):
        self.calls.append("GetSelectedClips")
        return ["item-from-documented-name"]

    def GetSelectedTimelineItems(self):
        self.calls.append("GetSelectedTimelineItems")
        return ["item-from-legacy-probe"]

    def GetSelectedItems(self):
        self.calls.append("GetSelectedItems")
        return ["item-from-other-legacy-probe"]


class RenderProject:
    def __init__(self):
        self.applied = None

    def GetName(self):
        return "Proj"

    def SetRenderSettings(self, settings):
        self.applied = dict(settings)
        return True


# ── media_pool_item get_timeline ─────────────────────────────────────────────


class GetTimelineActionTest(unittest.TestCase):
    def setUp(self):
        self.clip = Clip2104(timeline=TimelineObj())
        self._orig_get_mp = compound._get_mp
        self._orig_find_clip = compound._find_clip
        compound._get_mp = lambda: (None, None, MediaPoolStub(), None)
        compound._find_clip = lambda root, cid: self.clip

    def tearDown(self):
        compound._get_mp = self._orig_get_mp
        compound._find_clip = self._orig_find_clip

    def test_timeline_entry_returns_a_summary(self):
        out = compound.media_pool_item("get_timeline", {"clip_id": "c1"})

        self.assertTrue(out["is_timeline"])
        self.assertEqual(out["timeline"], {
            "name": "SEQ_01", "unique_id": "tl-1",
            "start_frame": 86400, "end_frame": 87000,
        })

    def test_ordinary_clip_is_not_a_timeline(self):
        # GetTimeline returns None for a clip that is not a timeline entry —
        # an answer, not a failure.
        self.clip = Clip2104(timeline=None)
        out = compound.media_pool_item("get_timeline", {"clip_id": "c1"})

        self.assertFalse(out["is_timeline"])
        self.assertIsNone(out["timeline"])
        self.assertNotIn("error", out)

    def test_partial_timeline_object_omits_what_it_cannot_answer(self):
        class NameOnly:
            def GetName(self):
                return "SEQ_01"

        self.clip = Clip2104(timeline=NameOnly())
        out = compound.media_pool_item("get_timeline", {"clip_id": "c1"})

        self.assertEqual(out["timeline"], {"name": "SEQ_01"})

    def test_pre_2104_build_is_version_guarded(self):
        self.clip = LegacyClip()
        out = compound.media_pool_item("get_timeline", {"clip_id": "L1"})

        self.assertIn("error", out)
        self.assertIn("21.0.4", str(out))

    def test_a_raising_gettimeline_is_reported_not_propagated(self):
        class Raises(Clip2104):
            def GetTimeline(self):
                raise RuntimeError("boom")

        self.clip = Raises()
        out = compound.media_pool_item("get_timeline", {"clip_id": "c1"})

        self.assertIn("error", out)
        self.assertIn("boom", str(out))

    def test_get_timeline_is_listed_as_a_known_action(self):
        out = compound.media_pool_item("no_such_action", {"clip_id": "c1"})
        self.assertIn("get_timeline", str(out))


# ── selection probe ordering ─────────────────────────────────────────────────


class SelectionProbeOrderTest(unittest.TestCase):
    def test_documented_name_is_tried_first(self):
        tl = SelectionTimeline()

        items, warnings = compound._get_selected_timeline_items(tl)

        self.assertEqual(tl.calls, ["GetSelectedClips"])
        self.assertEqual(items, ["item-from-documented-name"])
        self.assertEqual(warnings, [])

    def test_legacy_builds_still_fall_back(self):
        class LegacySelectionTimeline(SelectionTimeline):
            GetSelectedClips = None  # pre-21.0.4: the documented name is absent

        tl = LegacySelectionTimeline()

        items, _warnings = compound._get_selected_timeline_items(tl)

        self.assertEqual(tl.calls, ["GetSelectedTimelineItems"])
        self.assertEqual(items, ["item-from-legacy-probe"])


# ── render set_settings warnings ─────────────────────────────────────────────


class RenderSetSettingsWarningTest(unittest.TestCase):
    def setUp(self):
        self.project = RenderProject()
        self._orig = compound._check
        compound._check = lambda: (None, self.project, None)

    def tearDown(self):
        compound._check = self._orig

    def test_ignored_handles_are_named_on_the_set_path(self):
        # SetRenderSettings returns True for this pairing, so without the
        # warning the caller sees a clean success and no handles.
        out = compound.render("set_settings", {
            "settings": {"UseFullExtents": True, "AddFrameHandles": 12},
        })

        self.assertTrue(out["success"])
        self.assertIn("AddFrameHandles is ignored while UseFullExtents is true",
                      out["warnings"][0])

    def test_clean_settings_carry_no_warnings_key(self):
        out = compound.render("set_settings", {
            "settings": {"UseFullExtents": False, "AddFrameHandles": 12},
        })

        self.assertTrue(out["success"])
        self.assertNotIn("warnings", out)

    def test_the_2104_keys_survive_the_known_key_filter(self):
        compound.render("set_settings", {
            "settings": {"UseFullExtents": False, "AddFrameHandles": 8, "DataBurnIn": "None"},
        })

        self.assertEqual(self.project.applied,
                         {"UseFullExtents": False, "AddFrameHandles": 8, "DataBurnIn": "None"})


class SubtitleRenderKeysInertOn19Test(unittest.TestCase):
    """ExportSubtitle/SubtitleFormat: accepted-and-inert on 19.x (E90).

    Measured on Studio 19.1.3.7: SetRenderSettings returns True for all three
    SubtitleFormat modes and the renders carry no burn-in, no sidecar, and no
    embedded caption track. The warning is version-gated so a 21 host (where
    the keys are documented) stays quiet.
    """

    def test_pre21_host_warns_on_subtitle_keys(self):
        warnings = compound._render_settings_warnings(
            {"ExportSubtitle": True, "SubtitleFormat": "BurnIn"}, version_major=19)
        self.assertEqual(len(warnings), 1)
        self.assertIn("INERT on this Resolve generation", warnings[0])

    def test_21_host_and_unknown_version_stay_quiet(self):
        for major in (21, None):
            warnings = compound._render_settings_warnings(
                {"ExportSubtitle": True, "SubtitleFormat": "SeparateFile"},
                version_major=major)
            self.assertEqual(warnings, [], f"version_major={major}")

    def test_subtitle_free_settings_never_trip_the_gate(self):
        self.assertEqual(
            compound._render_settings_warnings({"ExportVideo": True}, version_major=19), [])


if __name__ == "__main__":
    unittest.main()
