"""Clip ids passed to a media_pool clip batch must all resolve, or the call must
fail having changed nothing.

Eight actions resolved ids with

    clips = [_find_clip(root, cid) for cid in p["clip_ids"]]
    clips = [c for c in clips if c]

so an id matching no clip was dropped and Resolve was handed the remainder.
v4.8.2 fixed the raw four (ACTIONS below):

- delete_clips errored only when EVERY id missed ("No clips found"); a mixed
  batch deleted the subset that resolved and answered {"success": true}.
- move_clips, relink and unlink never checked for an empty result at all, so an
  all-missing batch reached MoveClips([], target) / RelinkClips([], ...) /
  UnlinkClips([]) and answered whatever Resolve's bool said.

v4.8.6 fixed the other four (BATCH_ACTIONS below):

- create_timeline_from_clips (clip_ids) built the timeline from the subset.
- append_to_timeline (clip_ids) appended the subset and set the readback's
  expected_count to the RESOLVED count, so a partial append read back verified.
- export_metadata (clip_ids) exported the subset, and with every id missing called
  ExportMetadata(path, []) - unmeasured, possibly "export everything".
- auto_sync_audio synced the subset, or called AutoSyncAudio([], settings).

In all eight a bare string was iterated character by character, one id per
character.

v4.8.7: with every id resolved, append_to_timeline (clip_ids) still answered
{"success": true, "count": 0} when AppendToTimeline returned None/False/[]; only
verified_operation.verification_status said "api_failed" (FalsyAppendTest).

The fake MediaPool records every call that reaches Resolve, so "mutates nothing"
is asserted as "Resolve was never asked", not inferred from the return value.
"""
import os
import tempfile
import unittest
from unittest import mock

from src import server as s


class FakeClip:
    def __init__(self, name, uid, clip_type=None, file_path=None):
        self._name = name
        self._uid = uid
        self._clip_type = clip_type
        self._file_path = file_path

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return self._uid

    def GetClipProperty(self, name):
        if name == "Type":
            return self._clip_type
        if name == "File Path":
            return self._file_path
        return None


class FakeTimelineItem:
    def __init__(self, source, uid, name=None, start=0, end=24):
        self._source = source
        self._uid = uid
        self._name = name if name is not None else (source.GetName() if source else "")
        self._start = start
        self._end = end

    def GetUniqueId(self):
        return self._uid

    def GetMediaPoolItem(self):
        return self._source

    def GetName(self):
        return self._name

    def GetStart(self):
        return self._start

    def GetEnd(self):
        return self._end


class FakeFolder:
    def __init__(self, name, uid, clips=None, subs=None):
        self._name = name
        self._uid = uid
        self._clips = clips or []
        self._subs = subs or []

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return self._uid

    def GetClipList(self):
        return list(self._clips)

    def GetSubFolderList(self):
        return list(self._subs)


class FakeTimeline:
    """The current timeline, so append_to_timeline's readback has items to count."""

    def __init__(self, name="Cut", uid="tl-current"):
        self._name = name
        self._uid = uid
        self.items = []
        self.subtitle_items = []

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return self._uid

    def GetTrackCount(self, track_type):
        if track_type == "video":
            return 1
        if track_type == "subtitle" and self.subtitle_items:
            return 1
        return 0

    def GetItemListInTrack(self, track_type, track_index):
        if (track_type, track_index) == ("video", 1):
            return list(self.items)
        if (track_type, track_index) == ("subtitle", 1):
            return list(self.subtitle_items)
        return []


# ExportMetadata(path) and ExportMetadata(path, []) are different requests; the
# fake records which one it got.
ALL_CLIPS = "<ExportMetadata without a clip list>"


class FakeMP:
    """Records what was actually handed to Resolve, so a partial batch shows up."""

    def __init__(self, root, subtitle_texts=None):
        self._root = root
        self._subtitle_texts = subtitle_texts
        self.calls = []
        self.timeline = FakeTimeline()
        self.created_timelines = []

    def GetRootFolder(self):
        return self._root

    def GetCurrentFolder(self):
        return self._root

    def DeleteClips(self, clips):
        self.calls.append(("DeleteClips", list(clips)))
        return True

    def MoveClips(self, clips, target):
        self.calls.append(("MoveClips", list(clips), target))
        return True

    def RelinkClips(self, clips, folder_path):
        self.calls.append(("RelinkClips", list(clips), folder_path))
        return True

    def UnlinkClips(self, clips):
        self.calls.append(("UnlinkClips", list(clips)))
        return True

    def CreateTimelineFromClips(self, name, clips):
        self.calls.append(("CreateTimelineFromClips", list(clips), name))
        timeline = FakeTimeline(name, "tl-new")
        for index, clip in enumerate(clips):
            clip_type = clip.GetClipProperty("Type")
            if clip_type == "Subtitle":
                texts = (self._subtitle_texts if self._subtitle_texts is not None
                         else [f"Caption {index + 1}"])
                for cue_index, text in enumerate(texts):
                    timeline.subtitle_items.append(FakeTimelineItem(
                        None, f"ti-new-{index}-{cue_index}", name=text,
                        start=cue_index * 24, end=(cue_index + 1) * 24))
            elif clip_type in {"Generator", "Title", "Fusion Generator"}:
                timeline.items.append(FakeTimelineItem(
                    None, f"ti-new-{index}", name=clip.GetName()))
            else:
                timeline.items.append(FakeTimelineItem(clip, f"ti-new-{index}"))
        self.created_timelines.append(timeline)
        return timeline

    def AppendToTimeline(self, clips):
        self.calls.append(("AppendToTimeline", list(clips)))
        start = len(self.timeline.items)
        appended = [FakeClip(f"item {start + i}", f"ti-{start + i}") for i in range(len(clips))]
        self.timeline.items.extend(appended)
        return appended

    def ExportMetadata(self, path, clips=ALL_CLIPS):
        self.calls.append(("ExportMetadata", clips if clips is ALL_CLIPS else list(clips), path))
        return True

    def AutoSyncAudio(self, clips, settings):
        self.calls.append(("AutoSyncAudio", list(clips), settings))
        return True


class InvisibleCreateMP(FakeMP):
    def CreateTimelineFromClips(self, name, clips):
        timeline = super().CreateTimelineFromClips(name, clips)
        self.created_timelines.clear()
        return timeline


class EmptyCreateMP(FakeMP):
    def CreateTimelineFromClips(self, name, clips):
        timeline = super().CreateTimelineFromClips(name, clips)
        timeline.items = []
        timeline.subtitle_items = []
        return timeline


class EmptySubtitleCreateMP(FakeMP):
    def CreateTimelineFromClips(self, name, clips):
        timeline = super().CreateTimelineFromClips(name, clips)
        timeline.subtitle_items = []
        return timeline


class SourceLessMediaCreateMP(FakeMP):
    def CreateTimelineFromClips(self, name, clips):
        timeline = super().CreateTimelineFromClips(name, clips)
        timeline.items = [FakeTimelineItem(None, f"ti-new-{index}", name=clip.GetName())
                          for index, clip in enumerate(clips)]
        return timeline


class InvalidSubtitleCreateMP(FakeMP):
    def CreateTimelineFromClips(self, name, clips):
        timeline = super().CreateTimelineFromClips(name, clips)
        for item in timeline.subtitle_items:
            item._end = item._start
        return timeline


class FalsyAppendMP(FakeMP):
    """AppendToTimeline answers `answer`; `lands` items reach the timeline anyway."""

    def __init__(self, root, answer, lands=0):
        super().__init__(root)
        self._answer = answer
        self._lands = lands

    def AppendToTimeline(self, clips):
        self.calls.append(("AppendToTimeline", list(clips)))
        if self._lands:
            start = len(self.timeline.items)
            self.timeline.items.extend(
                FakeClip(f"item {start + i}", f"ti-{start + i}") for i in range(self._lands))
        return self._answer


def _tree(make_mp=FakeMP):
    # One clip at root, one two levels down, and an empty destination bin.
    top = FakeClip("A001.mov", "clip-top")
    nested = FakeClip("B002.mov", "clip-nested")
    day1 = FakeFolder("DAY1", "id-day1", clips=[nested])
    footage = FakeFolder("FOOTAGE", "id-footage", subs=[day1])
    dest = FakeFolder("ARCHIVE", "id-archive")
    root = FakeFolder("Master", "id-root", clips=[top], subs=[footage, dest])
    return make_mp(root), top, nested, dest


def _call(mp, action, params, *, require_confirm=False):
    proj = mock.Mock()
    proj.GetTimelineCount.side_effect = lambda: len(mp.created_timelines)
    proj.GetTimelineByIndex.side_effect = lambda index: mp.created_timelines[index - 1]
    proj.GetCurrentTimeline.return_value = mp.timeline
    # get_resolve is stubbed so auto_sync_audio cannot reach a running Resolve.
    with mock.patch.object(s, "_confirm_token_required", return_value=require_confirm), \
         mock.patch.object(s, "_check", return_value=(mock.Mock(), proj, None)), \
         mock.patch.object(s, "_get_mp", return_value=(mock.Mock(), proj, mp, None)), \
         mock.patch.object(s, "get_resolve", return_value=None):
        return s.media_pool(action, params)


def _write_srt(directory, texts):
    path = os.path.join(directory, "captions.srt")
    cues = [
        f"{index}\n00:00:{index * 2:02d},000 --> 00:00:{index * 2 + 1:02d},000\n{text}"
        for index, text in enumerate(texts)
    ]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n\n".join(cues) + "\n")
    return path


# action -> (the other params it needs, the MediaPool method it reaches)
ACTIONS = {
    "delete_clips": ({}, "DeleteClips"),
    "move_clips": ({"target_path": "Master/ARCHIVE"}, "MoveClips"),
    "relink": ({"folder_path": "/Volumes/media"}, "RelinkClips"),
    "unlink": ({}, "UnlinkClips"),
}

# The four batches fixed in v4.8.6, same shape.
BATCH_ACTIONS = {
    "create_timeline_from_clips": ({"name": "Selects"}, "CreateTimelineFromClips"),
    "append_to_timeline": ({}, "AppendToTimeline"),
    "export_metadata": ({"path": "/scratch/clips.csv"}, "ExportMetadata"),
    "auto_sync_audio": ({}, "AutoSyncAudio"),
}

ALL_ACTIONS = {**ACTIONS, **BATCH_ACTIONS}


class ResolvedClipIdsTest(unittest.TestCase):
    """The happy path still reaches Resolve with exactly the requested clips."""

    def test_every_action_passes_all_resolved_clips(self):
        for action, (extra, method) in ALL_ACTIONS.items():
            with self.subTest(action=action):
                mp, top, nested, dest = _tree()
                out = _call(mp, action, {"clip_ids": ["clip-top", "clip-nested"], **extra})
                self.assertNotIn("error", out)
                self.assertTrue(out["success"])
                self.assertEqual(len(mp.calls), 1)
                self.assertEqual(mp.calls[0][0], method)
                self.assertEqual(mp.calls[0][1], [top, nested])

    def test_move_clips_targets_the_named_folder(self):
        mp, top, _, dest = _tree()
        _call(mp, "move_clips", {"clip_ids": ["clip-top"], "target_path": "Master/ARCHIVE"})
        self.assertEqual(mp.calls, [("MoveClips", [top], dest)])

    def test_relink_passes_the_folder_path_through(self):
        mp, top, _, _ = _tree()
        _call(mp, "relink", {"clip_ids": ["clip-top"], "folder_path": "/Volumes/media"})
        self.assertEqual(mp.calls, [("RelinkClips", [top], "/Volumes/media")])

    def test_delete_clips_preview_counts_every_clip(self):
        # The confirm preview is the only thing the user sees before a delete.
        mp, _, _, _ = _tree()
        out = _call(mp, "delete_clips", {"clip_ids": ["clip-top", "clip-nested"]},
                    require_confirm=True)
        self.assertEqual(out.get("status"), "confirmation_required")
        self.assertEqual(out["preview"]["clips_lost"], 2)
        self.assertEqual(out["preview"]["names"], ["A001.mov", "B002.mov"])
        self.assertEqual(mp.calls, [])


class UnresolvedClipIdTest(unittest.TestCase):
    def _assert_not_found(self, out, unresolved, resolved):
        self.assertIn("error", out)
        self.assertNotEqual(out.get("success"), True)
        self.assertEqual(out["error"]["code"], "CLIP_NOT_FOUND")
        self.assertEqual(out["error"]["category"], "invalid_input")
        self.assertFalse(out["error"]["retryable"])
        self.assertEqual(out["error"]["state"]["unresolved_clip_ids"], unresolved)
        self.assertEqual(out["error"]["state"]["resolved_clip_ids"], resolved)

    def test_partial_batch_mutates_nothing(self):
        for action, (extra, _) in ALL_ACTIONS.items():
            with self.subTest(action=action):
                mp, _, _, _ = _tree()
                out = _call(mp, action,
                            {"clip_ids": ["clip-top", "clip-ghost", "clip-nested"], **extra})
                self._assert_not_found(out, ["clip-ghost"], ["clip-top", "clip-nested"])
                self.assertEqual(mp.calls, [])

    def test_all_unresolved_mutates_nothing(self):
        # move_clips / relink / unlink used to hand Resolve an empty list here
        # and report whatever its bool said.
        for action, (extra, _) in ALL_ACTIONS.items():
            with self.subTest(action=action):
                mp, _, _, _ = _tree()
                out = _call(mp, action, {"clip_ids": ["clip-ghost"], **extra})
                self._assert_not_found(out, ["clip-ghost"], [])
                self.assertEqual(mp.calls, [])

    def test_partial_delete_is_refused_before_a_confirm_token_is_issued(self):
        # Otherwise the preview would describe a subset and the token would
        # authorise deleting it.
        mp, _, _, _ = _tree()
        out = _call(mp, "delete_clips", {"clip_ids": ["clip-top", "clip-ghost"]},
                    require_confirm=True)
        self._assert_not_found(out, ["clip-ghost"], ["clip-top"])
        self.assertNotIn("confirm_token", out)
        self.assertEqual(mp.calls, [])


class ClipIdsShapeTest(unittest.TestCase):
    def test_missing_clip_ids_uses_the_standard_missing_param_error(self):
        # p["clip_ids"] stays an item lookup so _Params raises _MissingParam and
        # the tool boundary answers MISSING_CLIP_IDS, like every other action.
        for action, (extra, _) in ACTIONS.items():
            with self.subTest(action=action):
                mp, _, _, _ = _tree()
                out = _call(mp, action, dict(extra))
                self.assertEqual(out["error"]["code"], "MISSING_CLIP_IDS")
                self.assertEqual(out["error"]["category"], "invalid_input")
                self.assertEqual(mp.calls, [])

    def test_empty_clip_ids_is_invalid_input(self):
        for action, (extra, _) in ACTIONS.items():
            with self.subTest(action=action):
                mp, _, _, _ = _tree()
                out = _call(mp, action, {"clip_ids": [], **extra})
                self.assertEqual(out["error"]["code"], "INVALID_CLIP_IDS")
                self.assertEqual(out["error"]["category"], "invalid_input")
                self.assertEqual(mp.calls, [])

    def test_bare_string_clip_ids_is_invalid_input(self):
        # A bare string used to be iterated character by character, so every
        # character became an id that matched nothing and was then dropped.
        for action, (extra, _) in ALL_ACTIONS.items():
            with self.subTest(action=action):
                mp, _, _, _ = _tree()
                out = _call(mp, action, {"clip_ids": "clip-top", **extra})
                self.assertEqual(out["error"]["code"], "INVALID_CLIP_IDS")
                self.assertEqual(out["error"]["category"], "invalid_input")
                self.assertEqual(mp.calls, [])


class BatchActionTest(unittest.TestCase):
    """Where the v4.8.6 batches differ from the original four."""

    def test_append_verifies_against_the_requested_count(self):
        mp, top, nested, _ = _tree()
        out = _call(mp, "append_to_timeline", {"clip_ids": ["clip-top", "clip-nested"]})
        op = out["verified_operation"]
        self.assertEqual(out["count"], 2)
        self.assertEqual(op["requested"]["expected_count"], 2)
        self.assertEqual(op["requested"]["resolved_clip_count"], 2)
        self.assertEqual(op["verification_status"], "readback_verified")
        self.assertEqual(op["readback"]["item_count_delta"], 2)

    def test_create_timeline_reports_the_new_timeline(self):
        mp, top, nested, _ = _tree()
        out = _call(mp, "create_timeline_from_clips",
                    {"name": "Selects", "clip_ids": ["clip-top", "clip-nested"]})
        self.assertEqual(out["name"], "Selects")
        self.assertTrue(out["verified"])
        self.assertTrue(out["readback"]["project_timeline_found"])
        self.assertEqual(out["readback"]["item_count"], 2)
        self.assertEqual(out["readback"]["missing_clip_ids"], [])
        self.assertEqual(mp.calls, [("CreateTimelineFromClips", [top, nested], "Selects")])

    def test_create_re_resolves_stale_handles_immediately_before_native_call(self):
        mp, top, nested, _ = _tree()
        stale_root = mp._root
        fresh_top = FakeClip("A001.mov", "clip-top")
        fresh_nested = FakeClip("B002.mov", "clip-nested")
        fresh_root = FakeFolder("Master", "id-root", clips=[fresh_top, fresh_nested])
        mp.GetRootFolder = mock.Mock(side_effect=[stale_root, fresh_root])

        out = _call(mp, "create_timeline_from_clips",
                    {"name": "Selects", "clip_ids": ["clip-top", "clip-nested"]})

        self.assertTrue(out["success"])
        self.assertIsNot(fresh_top, top)
        self.assertIsNot(fresh_nested, nested)
        self.assertEqual(mp.calls, [("CreateTimelineFromClips", [fresh_top, fresh_nested], "Selects")])

    def test_create_handle_absent_from_project_is_structured_failure(self):
        mp, top, nested, _ = _tree(InvisibleCreateMP)

        out = _call(mp, "create_timeline_from_clips",
                    {"name": "Selects", "clip_ids": ["clip-top", "clip-nested"]})

        self.assertFalse(out["success"])
        self.assertFalse(out["verified"])
        self.assertEqual(out["error"]["code"], "CREATE_TIMELINE_READBACK_FAILED")
        self.assertFalse(out["error"]["retryable"])
        self.assertEqual(out["readback"]["timeline_id"], "tl-new")
        self.assertFalse(out["readback"]["project_timeline_found"])
        self.assertEqual(len(mp.calls), 1)

    def test_create_with_no_readable_entries_is_structured_failure(self):
        mp, _, _, _ = _tree(EmptyCreateMP)

        out = _call(mp, "create_timeline_from_clips",
                    {"name": "Selects", "clip_ids": ["clip-top", "clip-nested"]})

        self.assertFalse(out["success"])
        self.assertTrue(out["readback"]["project_timeline_found"])
        self.assertEqual(out["readback"]["item_count"], 0)
        self.assertEqual(out["readback"]["missing_clip_ids"], ["clip-top", "clip-nested"])
        self.assertEqual(out["error"]["code"], "CREATE_TIMELINE_READBACK_FAILED")

    def test_subtitle_create_verifies_cues_without_media_pool_items(self):
        subtitle = FakeClip("captions.srt", "clip-subtitle", clip_type="Subtitle")
        root = FakeFolder("Master", "id-root", clips=[subtitle])
        mp = FakeMP(root)

        out = _call(mp, "create_timeline_from_clips",
                    {"name": "Captions", "clip_ids": ["clip-subtitle"]})

        self.assertTrue(out["success"], out)
        self.assertTrue(out["verified"])
        self.assertIsNone(mp.created_timelines[0].subtitle_items[0].GetMediaPoolItem())
        self.assertEqual(out["readback"]["missing_clip_ids"], [])
        self.assertEqual(out["readback"]["subtitle_readback"]["cue_count"], 1)
        self.assertTrue(out["readback"]["subtitle_readback"]["verified"])

    def test_subtitle_create_without_valid_cues_is_structured_failure(self):
        for make_mp, cue_count, invalid_count in (
            (EmptySubtitleCreateMP, 0, 0),
            (InvalidSubtitleCreateMP, 1, 1),
        ):
            with self.subTest(make_mp=make_mp.__name__):
                subtitle = FakeClip("captions.srt", "clip-subtitle", clip_type="Subtitle")
                root = FakeFolder("Master", "id-root", clips=[subtitle])
                mp = make_mp(root)

                out = _call(mp, "create_timeline_from_clips",
                            {"name": "Captions", "clip_ids": ["clip-subtitle"]})

                self.assertFalse(out["success"])
                self.assertEqual(out["error"]["code"], "CREATE_TIMELINE_READBACK_FAILED")
                self.assertEqual(out["readback"]["subtitle_readback"]["cue_count"], cue_count)
                self.assertEqual(out["readback"]["subtitle_readback"]["invalid_cue_count"], invalid_count)
                self.assertFalse(out["readback"]["subtitle_readback"]["verified"])

    def test_subtitle_create_compares_source_srt_cues_and_normalized_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_srt(tmp, ["你好\n  世界", "第二条"])
            subtitle = FakeClip("captions.srt", "clip-subtitle",
                                clip_type="Subtitle", file_path=path)
            root = FakeFolder("Master", "id-root", clips=[subtitle])
            mp = FakeMP(root, subtitle_texts=["你好 世界", "第二条"])

            out = _call(mp, "create_timeline_from_clips",
                        {"name": "Captions", "clip_ids": ["clip-subtitle"]})

            self.assertTrue(out["success"], out)
            self.assertTrue(out["verified"])
            self.assertIsNone(mp.created_timelines[0].subtitle_items[0].GetMediaPoolItem())
            subtitle_readback = out["readback"]["subtitle_readback"]
            self.assertEqual(subtitle_readback["mode"], "source_srt")
            self.assertEqual(subtitle_readback["expected_cue_count"], 2)
            self.assertEqual(subtitle_readback["cue_count"], 2)
            self.assertEqual(subtitle_readback["text_mismatches"], [])

    def test_subtitle_create_rejects_source_cue_count_or_text_mismatch(self):
        for observed_texts in (["第一条"], ["第一条", "错误文本"]):
            with self.subTest(observed_texts=observed_texts), tempfile.TemporaryDirectory() as tmp:
                path = _write_srt(tmp, ["第一条", "第二条"])
                subtitle = FakeClip("captions.srt", "clip-subtitle",
                                    clip_type="Subtitle", file_path=path)
                root = FakeFolder("Master", "id-root", clips=[subtitle])
                mp = FakeMP(root, subtitle_texts=observed_texts)

                out = _call(mp, "create_timeline_from_clips",
                            {"name": "Captions", "clip_ids": ["clip-subtitle"]})

                self.assertFalse(out["success"])
                self.assertFalse(out["verified"])
                self.assertEqual(out["error"]["code"], "CREATE_TIMELINE_READBACK_FAILED")
                self.assertFalse(out["readback"]["subtitle_readback"]["verified"])

    def test_regular_media_cannot_use_source_less_name_readback(self):
        mp, _, _, _ = _tree(SourceLessMediaCreateMP)

        out = _call(mp, "create_timeline_from_clips",
                    {"name": "Selects", "clip_ids": ["clip-top"]})

        self.assertFalse(out["success"])
        self.assertEqual(out["readback"]["missing_clip_ids"], ["clip-top"])
        self.assertFalse(out["verified"])

        source = FakeClip("broken.mov", None)
        timeline = FakeTimeline("Broken", "tl-broken")
        timeline.items = [FakeTimelineItem(source, "ti-broken")]
        proj = mock.Mock()
        proj.GetTimelineCount.return_value = 1
        proj.GetTimelineByIndex.return_value = timeline
        readback = s._created_timeline_readback(proj, timeline, [source])
        self.assertFalse(readback["verified"])
        self.assertTrue(any("no readable unique ID" in error for error in readback["errors"]))

    def test_generator_create_verifies_source_less_item_by_name_and_bounds(self):
        generator = FakeClip("Solid Color", "clip-generator", clip_type="Generator")
        root = FakeFolder("Master", "id-root", clips=[generator])
        mp = FakeMP(root)

        out = _call(mp, "create_timeline_from_clips",
                    {"name": "Generator", "clip_ids": ["clip-generator"]})

        self.assertTrue(out["success"], out)
        self.assertIsNone(mp.created_timelines[0].items[0].GetMediaPoolItem())
        self.assertEqual(out["readback"]["generator_item_names"], ["Solid Color"])
        self.assertEqual(out["readback"]["missing_generator_clip_ids"], [])

    def test_mixed_media_and_subtitle_create_checks_both_readbacks(self):
        media = FakeClip("A001.mov", "clip-media")
        subtitle = FakeClip("captions.srt", "clip-subtitle", clip_type="Subtitle")
        root = FakeFolder("Master", "id-root", clips=[media, subtitle])
        mp = FakeMP(root)

        out = _call(mp, "create_timeline_from_clips",
                    {"name": "Mixed", "clip_ids": ["clip-media", "clip-subtitle"]})

        self.assertTrue(out["success"], out)
        self.assertEqual(out["readback"]["media_pool_item_ids"], ["clip-media"])
        self.assertEqual(out["readback"]["subtitle_readback"]["cue_count"], 1)
        self.assertEqual(out["readback"]["item_count"], 2)

    def test_export_without_clip_ids_still_exports_every_clip(self):
        for params in ({"path": "/scratch/all.csv"},
                       {"path": "/scratch/all.csv", "clip_ids": None}):
            with self.subTest(params=params):
                mp, _, _, _ = _tree()
                out = _call(mp, "export_metadata", params)
                self.assertTrue(out["success"])
                self.assertEqual(mp.calls, [("ExportMetadata", ALL_CLIPS, "/scratch/all.csv")])

    def test_export_with_an_empty_clip_list_is_refused_not_widened(self):
        # The old `if clip_ids:` turned an explicit empty selection into a
        # whole-pool export.
        mp, _, _, _ = _tree()
        out = _call(mp, "export_metadata", {"path": "/scratch/x.csv", "clip_ids": []})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["code"], "INVALID_CLIP_IDS")
        self.assertEqual(mp.calls, [])

    def test_export_without_path_is_missing_path(self):
        mp, _, _, _ = _tree()
        out = _call(mp, "export_metadata", {"clip_ids": ["clip-top"]})
        self.assertEqual(out["error"]["code"], "MISSING_PATH")
        self.assertEqual(mp.calls, [])

    def test_auto_sync_missing_clip_ids_keeps_the_standard_error(self):
        mp, _, _, _ = _tree()
        out = _call(mp, "auto_sync_audio", {})
        self.assertEqual(out["error"]["code"], "MISSING_CLIP_IDS")
        self.assertEqual(mp.calls, [])

    def test_auto_sync_empty_clip_ids_is_invalid_input(self):
        mp, _, _, _ = _tree()
        out = _call(mp, "auto_sync_audio", {"clip_ids": []})
        self.assertIn("error", out)
        self.assertEqual(out["error"]["code"], "INVALID_CLIP_IDS")
        self.assertEqual(mp.calls, [])

    def test_create_and_append_without_clip_ids_ask_for_either_form(self):
        # These two also take clip_infos, so their "neither given" message stays.
        for action, (extra, _) in BATCH_ACTIONS.items():
            if action not in ("create_timeline_from_clips", "append_to_timeline"):
                continue
            for ids in ({}, {"clip_ids": []}):
                with self.subTest(action=action, ids=ids):
                    mp, _, _, _ = _tree()
                    out = _call(mp, action, {**extra, **ids})
                    self.assertIn("Provide clip_ids", out["error"]["message"])
                    self.assertEqual(mp.calls, [])


class FalsyAppendTest(unittest.TestCase):
    """AppendToTimeline answering None/False/[] is a failed append, not count 0."""

    WHOLE_BATCH = {"clip_ids": ["clip-top", "clip-nested"]}

    def test_a_falsy_answer_is_an_error(self):
        for answer in (None, False, []):
            with self.subTest(answer=answer):
                mp, top, nested, _ = _tree(lambda root: FalsyAppendMP(root, answer))
                out = _call(mp, "append_to_timeline", self.WHOLE_BATCH)
                self.assertNotEqual(out.get("success"), True)
                self.assertEqual(out["error"]["code"], "APPEND_TO_TIMELINE_FAILED")
                self.assertEqual(out["error"]["category"], "resolve_api_failed")
                self.assertEqual(out["error"]["message"], "Failed to append clip_ids to timeline")
                self.assertEqual(mp.calls, [("AppendToTimeline", [top, nested])])

    def test_the_readback_stays_on_the_error(self):
        mp, _, _, _ = _tree(lambda root: FalsyAppendMP(root, None))
        out = _call(mp, "append_to_timeline", self.WHOLE_BATCH)
        op = out["verified_operation"]
        self.assertEqual(op["verification_status"], "api_failed")
        self.assertIs(op["execution"]["success"], False)
        self.assertEqual(op["requested"]["expected_count"], 2)
        self.assertEqual(op["readback"]["item_count_delta"], 0)
        self.assertEqual(out["error"]["state"],
                         {"expected_item_count_delta": 2, "item_count_delta": 0})

    def test_retryable_only_when_the_readback_shows_nothing_landed(self):
        # A retry after an append that did land puts the clips on twice.
        mp, _, _, _ = _tree(lambda root: FalsyAppendMP(root, None))
        self.assertTrue(_call(mp, "append_to_timeline", self.WHOLE_BATCH)["error"]["retryable"])

        mp, _, _, _ = _tree(lambda root: FalsyAppendMP(root, None, lands=2))
        out = _call(mp, "append_to_timeline", self.WHOLE_BATCH)
        self.assertEqual(out["error"]["code"], "APPEND_TO_TIMELINE_FAILED")
        self.assertFalse(out["error"]["retryable"])
        self.assertEqual(out["error"]["state"]["item_count_delta"], 2)

        # No current timeline: nothing to read back, so nothing is ruled out.
        mp, _, _, _ = _tree(lambda root: FalsyAppendMP(root, None))
        mp.timeline = None
        out = _call(mp, "append_to_timeline", self.WHOLE_BATCH)
        self.assertEqual(out["error"]["code"], "APPEND_TO_TIMELINE_FAILED")
        self.assertFalse(out["error"]["retryable"])
        self.assertIsNone(out["error"]["state"]["item_count_delta"])

    def test_clip_infos_fails_the_same_way(self):
        mp, top, _, _ = _tree(lambda root: FalsyAppendMP(root, None))
        out = _call(mp, "append_to_timeline", {"clip_infos": [
            {"clip_id": "clip-top", "start_frame": 0, "end_frame": 24,
             "record_frame": 0, "track_index": 1}]})
        self.assertEqual(out["error"]["code"], "APPEND_TO_TIMELINE_FAILED")
        self.assertEqual(out["error"]["message"], "Failed to append clip_infos to timeline")
        self.assertEqual(out["verified_operation"]["verification_status"], "api_failed")
        self.assertEqual(len(mp.calls), 1)


if __name__ == "__main__":
    unittest.main()
