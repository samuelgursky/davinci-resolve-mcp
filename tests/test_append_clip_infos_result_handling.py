import unittest

from src.server import (
    _append_clip_info_from_timeline_item,
    _collect_timeline_items_in_range,
    _copy_duplicate_item_state,
    _copy_keyframes,
    _timeline_edit_kernel_capabilities,
    _timeline_item_probe,
    _find_next_gap_record_frame,
    _find_appended_timeline_item_summary,
    _get_selected_timeline_items,
    _normalize_include_linked,
    _normalize_copy_properties,
    _resolve_duplicate_record_frame,
    _resolve_duplicate_track_index,
    _serialize_appended_timeline_item,
)


class TimelineItemStub:
    def __init__(self, unique_id="timeline-item-123", name="synthetic_append_clip_infos.mp4"):
        self.unique_id = unique_id
        self.name = name

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name


class BrokenTimelineItemStub:
    def GetUniqueId(self):
        raise RuntimeError("Resolve returned no item handle")


class AnonymousTimelineItemStub:
    pass


class TimelineItemDupStub:
    """Minimal timeline clip: source endFrame is an exclusive append boundary."""

    def __init__(self, mpi=None, unique_id="timeline-item-source", start=100, end=160):
        self._mpi = mpi or object()
        self.unique_id = unique_id
        self.start = start
        self.end = end

    def GetMediaPoolItem(self):
        return self._mpi

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetDuration(self):
        return self.end - self.start

    def GetLeftOffset(self):
        return 50

    def GetUniqueId(self):
        return self.unique_id


class TimelineItemDupSourceStartStub(TimelineItemDupStub):
    def GetSourceStartFrame(self):
        return 72


class TimelineItemDupNoPoolStub(TimelineItemDupStub):
    def GetMediaPoolItem(self):
        return None


class MediaPoolItemWithIdStub:
    def __init__(self, unique_id):
        self.unique_id = unique_id

    def GetUniqueId(self):
        return self.unique_id


class AppendedTimelineItemStub(TimelineItemStub):
    def __init__(self, mpi, unique_id="timeline-item-new", name="duplicate.mov", start=105, end=165):
        super().__init__(unique_id=unique_id, name=name)
        self._mpi = mpi
        self.start = start
        self.end = end

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetDuration(self):
        return self.end - self.start

    def GetMediaPoolItem(self):
        return self._mpi


class TimelineWithTrackStub:
    def __init__(self, items):
        self.items = items

    def GetItemListInTrack(self, track_type, track_index):
        if track_type in {"video", "audio"} and track_index == 2:
            return self.items
        return []


class TimelinePlacementStub:
    def __init__(self, items=None, current_timecode="01:00:05:00"):
        self.items = items or []
        self.current_timecode = current_timecode

    def GetItemListInTrack(self, track_type, track_index):
        if track_type == "video" and track_index == 2:
            return self.items
        return []

    def GetSetting(self, name):
        if name == "timelineFrameRate":
            return "24"
        return None

    def GetCurrentTimecode(self):
        return self.current_timecode


class TimelineRangeStub:
    def __init__(self, video_items=None, audio_items=None):
        self.video_items = video_items or []
        self.audio_items = audio_items or []

    def GetTrackCount(self, track_type):
        if track_type == "video":
            return 1 if self.video_items else 0
        if track_type == "audio":
            return 1 if self.audio_items else 0
        return 0

    def GetItemListInTrack(self, track_type, track_index):
        if track_index != 1:
            return []
        if track_type == "video":
            return self.video_items
        if track_type == "audio":
            return self.audio_items
        return []


class SelectedTimelineStub:
    def __init__(self, selected=None, current=None):
        self.selected = selected or []
        self.current = current

    def GetSelectedTimelineItems(self):
        return self.selected

    def GetCurrentVideoItem(self):
        return self.current


class CurrentOnlyTimelineStub:
    def __init__(self, current):
        self.current = current

    def GetCurrentVideoItem(self):
        return self.current


class PropertyCopyItemStub:
    def __init__(self):
        self.unique_id = "property-copy-source"
        self.name = "property_copy_source.mov"
        self.start = 100
        self.end = 160
        self.media_pool_item = MediaPoolItemWithIdStub("media-pool-source")
        self.properties = {
            "Pan": 0.25,
            "Tilt": -0.5,
            "Opacity": 62.5,
            "CompositeMode": 2,
            "Volume": -3.0,
            "RetimeProcess": 2,
            "MotionEstimation": 4,
            "DynamicZoomEnable": True,
            "DynamicZoomMode": 1,
            "DynamicZoomEase": 2,
            "Distortion": 0.1,
            "Scaling": 3,
            "ResizeFilter": 4,
            "StabilizationEnable": True,
            "StabilizationMethod": 1,
            "StabilizationStrength": 0.75,
        }
        self.color = "Teal"
        self.enabled = False
        self.markers = {
            12: {
                "color": "Blue",
                "name": "Needs review",
                "note": "Check this duplicate",
                "duration": 3,
                "customData": "marker-custom-data",
            }
        }
        self.added_markers = []
        self.flags = ["Blue", "Green"]
        self.added_flags = []
        self.color_cache = "On"
        self.fusion_cache = "Auto"
        self.voice_state = {"isEnabled": True, "amount": 33}
        self.copy_grades_targets = []
        self.keyframes = {
            "Pan": [(0, 0.1), (12, 0.4)],
            "Speed": [(0, 100), (20, 75)],
        }
        self.added_keyframes = []

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetDuration(self):
        return self.end - self.start

    def GetLeftOffset(self):
        return 12

    def GetTrackTypeAndIndex(self):
        return ["video", 1]

    def GetMediaPoolItem(self):
        return self.media_pool_item

    def GetLinkedItems(self):
        return []

    def GetProperty(self, key=None):
        if key is None:
            return dict(self.properties)
        return self.properties.get(key)

    def SetProperty(self, key, value):
        self.properties[key] = value
        return True

    def GetClipColor(self):
        return self.color

    def SetClipColor(self, color):
        self.color = color
        return True

    def GetClipEnabled(self):
        return self.enabled

    def SetClipEnabled(self, enabled):
        self.enabled = enabled
        return True

    def GetMarkers(self):
        return self.markers

    def AddMarker(self, *args):
        self.added_markers.append(args)
        return True

    def GetFlagList(self):
        return self.flags

    def AddFlag(self, color):
        self.added_flags.append(color)
        return True

    def GetIsColorOutputCacheEnabled(self):
        return self.color_cache

    def SetColorOutputCache(self, value):
        self.color_cache = value
        return True

    def GetIsFusionOutputCacheEnabled(self):
        return self.fusion_cache

    def SetFusionOutputCache(self, value):
        self.fusion_cache = value
        return True

    def GetVoiceIsolationState(self):
        return self.voice_state

    def SetVoiceIsolationState(self, state):
        self.voice_state = state
        return True

    def CopyGrades(self, targets):
        self.copy_grades_targets = targets
        return True

    def GetKeyframeCount(self, prop):
        return len(self.keyframes.get(prop, []))

    def GetKeyframeAtIndex(self, prop, index):
        return {"frame": self.keyframes[prop][index][0]}

    def GetPropertyAtKeyframeIndex(self, prop, index):
        return self.keyframes[prop][index][1]

    def AddKeyframe(self, prop, frame, value):
        self.added_keyframes.append((prop, frame, value))
        return True


class AppendClipInfosResultHandlingTest(unittest.TestCase):
    def test_serialize_appended_timeline_item_requires_item_handle(self):
        from tests._error_envelope_helpers import err_message

        item_out, item_err = _serialize_appended_timeline_item(None, 0)

        self.assertIsNone(item_out)
        self.assertEqual(
            err_message(item_err),
            "Failed to append clip_infos to timeline: missing timeline item at index 0",
        )

    def test_serialize_appended_timeline_item_requires_unique_id(self):
        from tests._error_envelope_helpers import err_message

        item_out, item_err = _serialize_appended_timeline_item(TimelineItemStub(unique_id=""), 2)

        self.assertIsNone(item_out)
        self.assertEqual(
            err_message(item_err),
            "Failed to append clip_infos to timeline: missing timeline item id at index 2",
        )

    def test_serialize_appended_timeline_item_rejects_invalid_item_handle(self):
        from tests._error_envelope_helpers import err_message

        item_out, item_err = _serialize_appended_timeline_item(BrokenTimelineItemStub(), 1)

        self.assertIsNone(item_out)
        self.assertEqual(
            err_message(item_err),
            "Failed to append clip_infos to timeline: invalid timeline item at index 1",
        )

    def test_serialize_appended_timeline_item_allows_empty_id_when_requested(self):
        item_out, item_err = _serialize_appended_timeline_item(
            TimelineItemStub(unique_id=""), 0, allow_empty_timeline_item_id=True
        )
        self.assertIsNone(item_err)
        self.assertEqual(
            item_out,
            {"timeline_item_id": None, "name": "synthetic_append_clip_infos.mp4"},
        )

    def test_serialize_appended_timeline_item_allows_missing_methods_when_requested(self):
        item_out, item_err = _serialize_appended_timeline_item(
            AnonymousTimelineItemStub(), 0, allow_empty_timeline_item_id=True
        )
        self.assertIsNone(item_err)
        self.assertEqual(item_out, {"timeline_item_id": None, "name": None})

    def test_serialize_appended_timeline_item_returns_summary(self):
        item_out, item_err = _serialize_appended_timeline_item(TimelineItemStub(), 0)

        self.assertIsNone(item_err)
        self.assertEqual(
            item_out,
            {
                "timeline_item_id": "timeline-item-123",
                "name": "synthetic_append_clip_infos.mp4",
            },
        )

    def test_append_clip_info_from_timeline_item_maps_trim_and_record(self):
        mpi = object()
        info, err = _append_clip_info_from_timeline_item(TimelineItemDupStub(mpi), target_track_index=2, record_frame_offset=5)
        self.assertIsNone(err)
        self.assertIs(info["mediaPoolItem"], mpi)
        self.assertEqual(info["startFrame"], 50)
        self.assertEqual(info["endFrame"], 110)
        self.assertEqual(info["recordFrame"], 105)
        self.assertEqual(info["trackIndex"], 2)
        self.assertEqual(info["mediaType"], 1)

    def test_append_clip_info_from_timeline_item_uses_explicit_record_frame(self):
        info, err = _append_clip_info_from_timeline_item(
            TimelineItemDupStub(), target_track_index=2, record_frame_offset=5, record_frame=240
        )

        self.assertIsNone(err)
        self.assertEqual(info["recordFrame"], 240)

    def test_append_clip_info_from_timeline_item_supports_audio_media_type(self):
        info, err = _append_clip_info_from_timeline_item(
            TimelineItemDupStub(), target_track_index=1, record_frame=240, media_type=2
        )

        self.assertIsNone(err)
        self.assertEqual(info["mediaType"], 2)

    def test_append_clip_info_from_timeline_item_supports_partial_source_range(self):
        info, err = _append_clip_info_from_timeline_item(
            TimelineItemDupStub(), target_track_index=1, record_frame=240, source_start=55, source_end=80
        )

        self.assertIsNone(err)
        self.assertEqual(info["startFrame"], 55)
        self.assertEqual(info["endFrame"], 80)
        self.assertEqual(info["recordFrame"], 240)

    def test_append_clip_info_from_timeline_item_prefers_source_start_frame(self):
        info, err = _append_clip_info_from_timeline_item(
            TimelineItemDupSourceStartStub(), target_track_index=2, record_frame_offset=5
        )
        self.assertIsNone(err)
        self.assertEqual(info["startFrame"], 72)
        self.assertEqual(info["endFrame"], 132)

    def test_append_clip_info_from_timeline_item_rejects_no_media_pool(self):
        info, err = _append_clip_info_from_timeline_item(TimelineItemDupNoPoolStub(), 1, 0)
        self.assertIsNone(info)
        self.assertIn("error", err)

    def test_find_appended_timeline_item_summary_recovers_id_from_target_track(self):
        mpi = MediaPoolItemWithIdStub("media-1")
        original = AppendedTimelineItemStub(mpi, unique_id="timeline-item-source")
        appended = AppendedTimelineItemStub(mpi, unique_id="timeline-item-new")
        summary = _find_appended_timeline_item_summary(
            TimelineWithTrackStub([original, appended]),
            target_track_index=2,
            record_frame=105,
            duration=60,
            source_media_pool_item=mpi,
            source_timeline_item_id="timeline-item-source",
        )
        self.assertEqual(summary, {"timeline_item_id": "timeline-item-new", "name": "duplicate.mov"})

    def test_find_appended_timeline_item_summary_recovers_audio_id(self):
        mpi = MediaPoolItemWithIdStub("media-1")
        appended = AppendedTimelineItemStub(mpi, unique_id="audio-item-new")
        summary = _find_appended_timeline_item_summary(
            TimelineWithTrackStub([appended]),
            track_type="audio",
            target_track_index=2,
            record_frame=105,
            duration=60,
            source_media_pool_item=mpi,
        )

        self.assertEqual(summary, {"timeline_item_id": "audio-item-new", "name": "duplicate.mov"})

    def test_resolve_duplicate_track_index_supports_track_above_default(self):
        dest, err = _resolve_duplicate_track_index(1, "track_above", {})

        self.assertIsNone(err)
        self.assertEqual(dest, 2)

    def test_resolve_duplicate_track_index_explicit_target_wins(self):
        dest, err = _resolve_duplicate_track_index(
            1,
            "track_above",
            {"target_track_index": 4, "track_offset": 1},
        )

        self.assertIsNone(err)
        self.assertEqual(dest, 4)

    def test_resolve_duplicate_record_frame_supports_at_playhead(self):
        frame, err = _resolve_duplicate_record_frame(
            TimelinePlacementStub(),
            TimelineItemDupStub(),
            "at_playhead",
            10,
            {},
            2,
        )

        self.assertIsNone(err)
        self.assertEqual(frame, 86530)

    def test_resolve_duplicate_record_frame_supports_after_source(self):
        frame, err = _resolve_duplicate_record_frame(
            TimelinePlacementStub(),
            TimelineItemDupStub(start=100, end=160),
            "after_source",
            5,
            {},
            2,
        )

        self.assertIsNone(err)
        self.assertEqual(frame, 165)

    def test_find_next_gap_record_frame_skips_short_gaps(self):
        mpi = MediaPoolItemWithIdStub("media-1")
        items = [
            AppendedTimelineItemStub(mpi, unique_id="occupant-1", start=160, end=200),
            AppendedTimelineItemStub(mpi, unique_id="occupant-2", start=250, end=300),
        ]

        frame = _find_next_gap_record_frame(
            TimelinePlacementStub(items=items),
            track_type="video",
            track_index=2,
            duration=60,
            search_start=160,
        )

        self.assertEqual(frame, 300)

    def test_normalize_copy_properties_accepts_aliases_and_dedupes(self):
        groups, err = _normalize_copy_properties(["transform", "color", "clip_color", "enabled_state", "grade"])

        self.assertIsNone(err)
        self.assertEqual(groups, ["transform", "clip_color", "enabled", "grades"])

    def test_normalize_copy_properties_all_expands_supported_groups(self):
        groups, err = _normalize_copy_properties("all")

        self.assertIsNone(err)
        self.assertIn("fusion", groups)
        self.assertIn("grades", groups)
        self.assertIn("takes", groups)
        self.assertIn("keyframes", groups)
        self.assertIn("dynamic_zoom", groups)
        self.assertIn("scaling", groups)
        self.assertIn("stabilization", groups)

    def test_normalize_include_linked_defaults_true_to_audio(self):
        self.assertEqual(_normalize_include_linked(True), {"audio"})
        self.assertEqual(_normalize_include_linked("all"), {"video", "audio"})

    def test_get_selected_timeline_items_uses_selection_api(self):
        selected = [TimelineItemDupStub(unique_id="selected-source")]
        items, warnings = _get_selected_timeline_items(SelectedTimelineStub(selected=selected))

        self.assertEqual(items, selected)
        self.assertEqual(warnings, [])

    def test_get_selected_timeline_items_falls_back_to_current_video_item(self):
        current = TimelineItemDupStub(unique_id="current-source")
        items, warnings = _get_selected_timeline_items(CurrentOnlyTimelineStub(current))

        self.assertEqual(items, [current])
        self.assertEqual(
            warnings,
            ["Timeline selection API is unavailable; used current video item as selected source"],
        )

    def test_copy_duplicate_item_state_copies_supported_groups(self):
        source = PropertyCopyItemStub()
        duplicate = PropertyCopyItemStub()
        duplicate.properties = {}
        duplicate.color = ""
        duplicate.enabled = True
        duplicate.markers = {}

        result = _copy_duplicate_item_state(
            source,
            duplicate,
            [
                "transform",
                "composite",
                "audio",
                "retime",
                "dynamic_zoom",
                "scaling",
                "stabilization",
                "clip_color",
                "markers",
                "flags",
                "enabled",
                "cache",
                "voice_isolation",
                "grades",
                "keyframes",
                "transitions",
            ],
        )

        self.assertTrue(result["transform"]["success"])
        self.assertTrue(result["composite"]["success"])
        self.assertTrue(result["audio"]["success"])
        self.assertTrue(result["retime"]["success"])
        self.assertTrue(result["dynamic_zoom"]["success"])
        self.assertTrue(result["scaling"]["success"])
        self.assertTrue(result["stabilization"]["success"])
        self.assertEqual(duplicate.properties["Pan"], 0.25)
        self.assertEqual(duplicate.properties["Opacity"], 62.5)
        self.assertEqual(duplicate.properties["Volume"], -3.0)
        self.assertEqual(duplicate.properties["RetimeProcess"], 2)
        self.assertEqual(duplicate.properties["DynamicZoomEnable"], True)
        self.assertEqual(duplicate.properties["Scaling"], 3)
        self.assertEqual(duplicate.properties["StabilizationStrength"], 0.75)
        self.assertEqual(duplicate.color, "Teal")
        self.assertFalse(duplicate.enabled)
        self.assertEqual(
            duplicate.added_markers,
            [(12, "Blue", "Needs review", "Check this duplicate", 3, "marker-custom-data")],
        )
        self.assertEqual(duplicate.added_flags, ["Blue", "Green"])
        self.assertEqual(duplicate.color_cache, "On")
        self.assertEqual(duplicate.fusion_cache, "Auto")
        self.assertEqual(duplicate.voice_state, {"isEnabled": True, "amount": 33})
        self.assertEqual(source.copy_grades_targets, [duplicate])
        self.assertIn(("Pan", 0, 0.1), duplicate.added_keyframes)
        self.assertIn(("Speed", 20, 75), duplicate.added_keyframes)
        self.assertFalse(result["transitions"]["copied"])

    def test_copy_keyframes_copies_requested_properties(self):
        source = PropertyCopyItemStub()
        duplicate = PropertyCopyItemStub()
        duplicate.added_keyframes = []

        result = _copy_keyframes(source, duplicate, ["Pan"])

        self.assertTrue(result["success"])
        self.assertEqual(result["copied"], 2)
        self.assertEqual(duplicate.added_keyframes, [("Pan", 0, 0.1), ("Pan", 12, 0.4)])

    def test_edit_kernel_capabilities_reports_boundaries(self):
        caps = _timeline_edit_kernel_capabilities()

        self.assertIn("copy_range", caps["supported"]["range_operations"])
        self.assertIn("read_only_probe", caps["supported"])
        self.assertIn("transition_cloning", caps["unsupported"])
        self.assertIn("audio_properties", caps["partially_supported"])
        self.assertIn("dynamic_zoom_scaling_stabilization", caps["partially_supported"])

    def test_timeline_item_probe_reports_property_and_method_surface(self):
        item = PropertyCopyItemStub()

        probe = _timeline_item_probe(item)

        self.assertEqual(probe["summary"]["timeline_item_id"], "property-copy-source")
        self.assertTrue(probe["methods"]["GetProperty"])
        self.assertTrue(probe["methods"]["SetProperty"])
        self.assertEqual(probe["all_properties"]["Pan"], 0.25)
        self.assertEqual(probe["known_properties"]["DynamicZoomEnable"]["value"], True)
        self.assertEqual(probe["known_properties"]["StabilizationStrength"]["value"], 0.75)
        self.assertEqual(probe["keyframes"]["Pan"]["count"], 2)

    def test_collect_timeline_items_in_range_returns_partial_overlaps(self):
        video = TimelineItemDupStub(unique_id="video-range", start=100, end=160)
        audio = TimelineItemDupStub(unique_id="audio-range", start=110, end=170)

        start, end, items, err = _collect_timeline_items_in_range(
            TimelineRangeStub(video_items=[video], audio_items=[audio]),
            {"start_frame": 120, "end_frame": 150, "track_types": ["video", "audio"]},
        )

        self.assertIsNone(err)
        self.assertEqual((start, end), (120, 150))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0][3:], (120, 150))


if __name__ == "__main__":
    unittest.main()
