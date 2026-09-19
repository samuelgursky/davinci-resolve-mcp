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

The fake MediaPool records every call that reaches Resolve, so "mutates nothing"
is asserted as "Resolve was never asked", not inferred from the return value.
"""
import unittest
from unittest import mock

from src import server as s


class FakeClip:
    def __init__(self, name, uid):
        self._name = name
        self._uid = uid

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return self._uid


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

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return self._uid

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, track_index):
        return list(self.items) if (track_type, track_index) == ("video", 1) else []


# ExportMetadata(path) and ExportMetadata(path, []) are different requests; the
# fake records which one it got.
ALL_CLIPS = "<ExportMetadata without a clip list>"


class FakeMP:
    """Records what was actually handed to Resolve, so a partial batch shows up."""

    def __init__(self, root):
        self._root = root
        self.calls = []
        self.timeline = FakeTimeline()

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
        return FakeTimeline(name, "tl-new")

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


def _tree():
    # One clip at root, one two levels down, and an empty destination bin.
    top = FakeClip("A001.mov", "clip-top")
    nested = FakeClip("B002.mov", "clip-nested")
    day1 = FakeFolder("DAY1", "id-day1", clips=[nested])
    footage = FakeFolder("FOOTAGE", "id-footage", subs=[day1])
    dest = FakeFolder("ARCHIVE", "id-archive")
    root = FakeFolder("Master", "id-root", clips=[top], subs=[footage, dest])
    return FakeMP(root), top, nested, dest


def _call(mp, action, params, *, require_confirm=False):
    proj = mock.Mock()
    proj.GetTimelineCount.return_value = 0          # no name clash for create_*
    proj.GetCurrentTimeline.return_value = mp.timeline
    # get_resolve is stubbed so auto_sync_audio cannot reach a running Resolve.
    with mock.patch.object(s, "_confirm_token_required", return_value=require_confirm), \
         mock.patch.object(s, "_check", return_value=(mock.Mock(), proj, None)), \
         mock.patch.object(s, "_get_mp", return_value=(mock.Mock(), proj, mp, None)), \
         mock.patch.object(s, "get_resolve", return_value=None):
        return s.media_pool(action, params)


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
        self.assertEqual(mp.calls, [("CreateTimelineFromClips", [top, nested], "Selects")])

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


if __name__ == "__main__":
    unittest.main()
