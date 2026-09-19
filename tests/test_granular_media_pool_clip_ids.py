"""Granular media-pool batch tools must resolve every clip id or change nothing.

append_to_timeline (clip_ids form) and auto_sync_audio resolved ids with

    clips = [_find_clip_by_id(root, cid) for cid in clip_ids]
    clips = [c for c in clips if c]

and delete_media_pool_clips / move_clips_to_folder with
_find_clips_by_ids(root, set(clip_ids)), which returns only what it finds. All
four errored only when EVERY id missed; a mixed batch appended, synced, deleted
or moved the subset that resolved and answered like a full batch.

The fake MediaPool records every call that reaches Resolve, so "changes nothing"
is asserted as "Resolve was never asked", not inferred from the return value.
"""
import os
import tempfile
import unittest
from unittest import mock

import src.granular.media_pool as gmp
from src.utils import destructive_hook as dh


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

    def AppendToTimeline(self, clips):
        self.calls.append(("AppendToTimeline", list(clips)))
        return [mock.Mock() for _ in clips]

    def AutoSyncAudio(self, clips, settings):
        self.calls.append(("AutoSyncAudio", list(clips)))
        return True

    def DeleteClips(self, clips):
        self.calls.append(("DeleteClips", list(clips)))
        return True

    def MoveClips(self, clips, target):
        self.calls.append(("MoveClips", list(clips), target))
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


# tool name -> (the other arguments it needs, the MediaPool method it reaches)
TOOLS = {
    "append_to_timeline": ({}, "AppendToTimeline"),
    "auto_sync_audio": ({}, "AutoSyncAudio"),
    "delete_media_pool_clips": ({}, "DeleteClips"),
    "move_clips_to_folder": ({"target_folder_path": "Master/ARCHIVE"}, "MoveClips"),
}


class _GranularCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        audit = os.path.join(tmp.name, "audit.jsonl")
        # Safe mode off so delete_media_pool_clips reaches its body; the audit row
        # goes to a throwaway file. get_resolve is stubbed so nothing here can
        # reach a running Resolve.
        for patcher in (mock.patch.object(dh, "_audit_log_path", lambda: audit),
                        mock.patch.object(dh, "_safe_mode_enabled", lambda: False),
                        mock.patch.object(gmp, "get_resolve", return_value=mock.Mock())):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _call(self, mp, tool, **kwargs):
        with mock.patch.object(gmp, "_get_mp", return_value=(mock.Mock(), mp, None)):
            return getattr(gmp, tool)(**kwargs)


class ResolvedClipIdsTest(_GranularCase):
    def test_every_tool_passes_all_resolved_clips(self):
        for tool, (extra, method) in TOOLS.items():
            with self.subTest(tool=tool):
                mp, top, nested, _ = _tree()
                out = self._call(mp, tool, clip_ids=["clip-top", "clip-nested"], **extra)
                self.assertNotIn("error", out)
                self.assertTrue(out["success"])
                self.assertEqual(len(mp.calls), 1)
                self.assertEqual(mp.calls[0][0], method)
                self.assertEqual(mp.calls[0][1], [top, nested])

    def test_append_keeps_request_order(self):
        # The nested clip is found after the root one when walking the tree;
        # append order must follow the request, not the walk.
        mp, top, nested, _ = _tree()
        self._call(mp, "append_to_timeline", clip_ids=["clip-nested", "clip-top"])
        self.assertEqual(mp.calls, [("AppendToTimeline", [nested, top])])

    def test_append_keeps_a_repeated_id(self):
        mp, top, _, _ = _tree()
        self._call(mp, "append_to_timeline", clip_ids=["clip-top", "clip-top"])
        self.assertEqual(mp.calls, [("AppendToTimeline", [top, top])])

    def test_delete_and_move_collapse_a_repeated_id(self):
        # The old set-based lookup handed Resolve each clip once; keep that.
        for tool in ("delete_media_pool_clips", "move_clips_to_folder"):
            with self.subTest(tool=tool):
                mp, top, _, _ = _tree()
                extra, _ = TOOLS[tool]
                self._call(mp, tool, clip_ids=["clip-top", "clip-top"], **extra)
                self.assertEqual(mp.calls[0][1], [top])

    def test_counts_match_what_reached_resolve(self):
        mp, _, _, _ = _tree()
        out = self._call(mp, "delete_media_pool_clips", clip_ids=["clip-top", "clip-nested"])
        self.assertEqual(out["deleted_count"], 2)
        mp, _, _, dest = _tree()
        out = self._call(mp, "move_clips_to_folder", clip_ids=["clip-nested"],
                         target_folder_path="Master/ARCHIVE")
        self.assertEqual(out["moved_count"], 1)
        self.assertIs(mp.calls[0][2], dest)


class UnresolvedClipIdTest(_GranularCase):
    def _assert_not_found(self, out, unresolved, resolved):
        self.assertIn("error", out)
        self.assertIs(out.get("success"), False)
        self.assertIn("Clip(s) not found", out["error"])
        self.assertEqual(out["unresolved_clip_ids"], unresolved)
        self.assertEqual(out["resolved_clip_ids"], resolved)

    def test_partial_batch_changes_nothing(self):
        for tool, (extra, _) in TOOLS.items():
            with self.subTest(tool=tool):
                mp, _, _, _ = _tree()
                out = self._call(mp, tool,
                                 clip_ids=["clip-top", "clip-ghost", "clip-nested"], **extra)
                self._assert_not_found(out, ["clip-ghost"], ["clip-top", "clip-nested"])
                self.assertEqual(mp.calls, [])

    def test_all_unresolved_changes_nothing(self):
        for tool, (extra, _) in TOOLS.items():
            with self.subTest(tool=tool):
                mp, _, _, _ = _tree()
                out = self._call(mp, tool, clip_ids=["clip-ghost"], **extra)
                self._assert_not_found(out, ["clip-ghost"], [])
                self.assertEqual(mp.calls, [])

    def test_bare_string_is_refused_not_iterated(self):
        # MCP schema validation rejects this at the boundary; a direct Python
        # caller used to get one id per character.
        for tool, (extra, _) in TOOLS.items():
            with self.subTest(tool=tool):
                mp, _, _, _ = _tree()
                out = self._call(mp, tool, clip_ids="clip-top", **extra)
                self.assertIn("error", out)
                self.assertNotIn("unresolved_clip_ids", out)
                self.assertEqual(mp.calls, [])

    def test_empty_list_is_refused(self):
        for tool, (extra, _) in TOOLS.items():
            with self.subTest(tool=tool):
                mp, _, _, _ = _tree()
                out = self._call(mp, tool, clip_ids=[], **extra)
                self.assertIn("error", out)
                self.assertEqual(mp.calls, [])


if __name__ == "__main__":
    unittest.main()
