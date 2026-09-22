"""create_missing="false" in organize_clips must not create folders.

_organize_clips checked ``p.get("create_missing")`` with bare truthiness: a
string "false", "no", "0", or "off" is truthy in Python, so a caller
explicitly requesting *no* folder creation still got one via
_ensure_folder_path. Route through _coerce_bool like every other boolean
parameter in the server.
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
    def __init__(self, root):
        self._root = root
        self.added_folders = []

    def GetRootFolder(self):
        return self._root

    def GetCurrentFolder(self):
        return self._root

    def AddSubFolder(self, parent, name):
        self.added_folders.append((parent.GetName(), name))
        created = FakeFolder(name, f"uid-{name}")
        return created

    def MoveClips(self, clips, target):
        return True


class OrganizeClipsCreateMissingTest(unittest.TestCase):
    """create_missing="false" must NOT create missing target folders."""

    def _make_tree(self):
        clip = FakeClip("A.mov", "clip-a")
        root = FakeFolder("Master", "root", clips=[clip])
        mp = FakeMP(root)
        return mp, root, clip

    def test_string_false_does_not_create_folder(self):
        """create_missing="false" must fail when the target folder is missing."""
        mp, root, clip = self._make_tree()
        for spelling in ("false", "False", "FALSE", "no", "0", "off"):
            with self.subTest(spelling=spelling):
                mp.added_folders.clear()
                out = s._organize_clips(mp, root, {
                    "target_path": "Nonexistent/Deep",
                    "clip_ids": [clip.GetUniqueId()],
                    "create_missing": spelling,
                })
                self.assertFalse(out.get("success"),
                    f'create_missing="{spelling}" must not succeed '
                    f'when the folder does not exist')
                self.assertEqual(mp.added_folders, [],
                    f'create_missing="{spelling}" must not call AddSubFolder')

    def test_true_creates_folder(self):
        """Sanity: create_missing=True must create the folder."""
        mp, root, clip = self._make_tree()
        out = s._organize_clips(mp, root, {
            "target_path": "NewFolder",
            "clip_ids": [clip.GetUniqueId()],
            "create_missing": True,
        })
        self.assertTrue(out.get("success"))
        self.assertEqual(len(mp.added_folders), 1)

    def test_omitted_does_not_create_folder(self):
        """Default (no create_missing key) must not create folders."""
        mp, root, clip = self._make_tree()
        out = s._organize_clips(mp, root, {
            "target_path": "Missing",
            "clip_ids": [clip.GetUniqueId()],
        })
        self.assertFalse(out.get("success"))
        self.assertEqual(mp.added_folders, [])


if __name__ == "__main__":
    unittest.main()
