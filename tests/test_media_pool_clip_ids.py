"""Clip ids passed to media_pool.delete_clips / move_clips / relink / unlink must
all resolve, or the call must fail having changed nothing.

The four raw clip actions resolved ids with

    clips = [_find_clip(root, cid) for cid in p["clip_ids"]]
    clips = [c for c in clips if c]

so an id matching no clip was dropped and Resolve was handed the remainder:

- delete_clips errored only when EVERY id missed ("No clips found"); a mixed
  batch deleted the subset that resolved and answered {"success": true}.
- move_clips, relink and unlink never checked for an empty result at all, so an
  all-missing batch reached MoveClips([], target) / RelinkClips([], ...) /
  UnlinkClips([]) and answered whatever Resolve's bool said.
- A bare string was iterated character by character, one id per character.

The fake MediaPool records every mutation call, so "mutates nothing" is asserted
as "Resolve was never asked", not inferred from the return value.
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


class FakeMP:
    """Records what was actually handed to Resolve, so a partial batch shows up."""

    def __init__(self, root):
        self._root = root
        self.calls = []

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
    with mock.patch.object(s, "_confirm_token_required", return_value=require_confirm), \
         mock.patch.object(s, "_check", return_value=(mock.Mock(), proj, None)), \
         mock.patch.object(s, "_get_mp", return_value=(mock.Mock(), proj, mp, None)):
        return s.media_pool(action, params)


# action -> (the other params it needs, the MediaPool method it reaches)
ACTIONS = {
    "delete_clips": ({}, "DeleteClips"),
    "move_clips": ({"target_path": "Master/ARCHIVE"}, "MoveClips"),
    "relink": ({"folder_path": "/Volumes/media"}, "RelinkClips"),
    "unlink": ({}, "UnlinkClips"),
}


class ResolvedClipIdsTest(unittest.TestCase):
    """The happy path still reaches Resolve with exactly the requested clips."""

    def test_every_action_passes_all_resolved_clips(self):
        for action, (extra, method) in ACTIONS.items():
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
        for action, (extra, _) in ACTIONS.items():
            with self.subTest(action=action):
                mp, _, _, _ = _tree()
                out = _call(mp, action,
                            {"clip_ids": ["clip-top", "clip-ghost", "clip-nested"], **extra})
                self._assert_not_found(out, ["clip-ghost"], ["clip-top", "clip-nested"])
                self.assertEqual(mp.calls, [])

    def test_all_unresolved_mutates_nothing(self):
        # move_clips / relink / unlink used to hand Resolve an empty list here
        # and report whatever its bool said.
        for action, (extra, _) in ACTIONS.items():
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
        for action, (extra, _) in ACTIONS.items():
            with self.subTest(action=action):
                mp, _, _, _ = _tree()
                out = _call(mp, action, {"clip_ids": "clip-top", **extra})
                self.assertEqual(out["error"]["code"], "INVALID_CLIP_IDS")
                self.assertEqual(out["error"]["category"], "invalid_input")
                self.assertEqual(mp.calls, [])


if __name__ == "__main__":
    unittest.main()
