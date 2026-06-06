"""Tests for the media-pool clip walk: lazy iteration + eager list compatibility.

The lazy iterator must yield in the same pre-order as the eager list and must
stop walking as soon as a consumer breaks (so find-by-name doesn't traverse the
whole project).
"""
import unittest

from src.granular import common


class FakeClip:
    def __init__(self, name):
        self._n = name

    def GetName(self):
        return self._n


class FakeFolder:
    def __init__(self, clips, subs=None):
        self._clips = clips
        self._subs = subs or []
        self.clip_calls = 0

    def GetClipList(self):
        self.clip_calls += 1
        return list(self._clips)

    def GetSubFolderList(self):
        return list(self._subs)


class FakeMP:
    def __init__(self, root):
        self._root = root

    def GetRootFolder(self):
        return self._root


def _tree():
    c = FakeFolder([FakeClip("c1")])
    b = FakeFolder([FakeClip("b1")], subs=[c])
    a = FakeFolder([FakeClip("a1"), FakeClip("a2")])
    root = FakeFolder([FakeClip("r1")], subs=[a, b])
    return FakeMP(root), {"root": root, "a": a, "b": b, "c": c}


class MediaPoolWalkTest(unittest.TestCase):
    def test_eager_list_preorder(self):
        mp, _ = _tree()
        names = [c.GetName() for c in common.get_all_media_pool_clips(mp)]
        self.assertEqual(names, ["r1", "a1", "a2", "b1", "c1"])

    def test_iter_matches_eager(self):
        mp, _ = _tree()
        eager = [c.GetName() for c in common.get_all_media_pool_clips(mp)]
        lazy = [c.GetName() for c in common.iter_all_media_pool_clips(mp)]
        self.assertEqual(lazy, eager)

    def test_early_break_stops_the_walk(self):
        mp, f = _tree()
        # Consume until we find "a1", then break — as the find-by-name sites do.
        for clip in common.iter_all_media_pool_clips(mp):
            if clip.GetName() == "a1":
                break
        # Folders B and C are never inspected because we stopped early.
        self.assertEqual(f["b"].clip_calls, 0)
        self.assertEqual(f["c"].clip_calls, 0)

    def test_empty_root_yields_nothing(self):
        mp = FakeMP(None)
        self.assertEqual(list(common.iter_all_media_pool_clips(mp)), [])
        self.assertEqual(common.get_all_media_pool_clips(mp), [])


if __name__ == "__main__":
    unittest.main()
