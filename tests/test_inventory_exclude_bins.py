"""Tests for the inventory-walk folder-exclusion feature (PR #69, adapted).

`_append_folder_media` must skip subfolders whose name is in `exclude_bins`, and
default to indexing every folder when `exclude_bins` is None. The setup layer must
round-trip the `inventory_limit` / `inventory_exclude_bins` preferences and default
to excluding nothing.
"""
import unittest
from unittest import mock

import src.analysis_dashboard as dash
import src.server as s


class FakeClip:
    def __init__(self, name):
        self._name = name

    def GetName(self):
        return self._name


class FakeFolder:
    def __init__(self, name, clips=None, subfolders=None):
        self._name = name
        self._clips = clips or []
        self._subfolders = subfolders or []

    def GetName(self):
        return self._name

    def GetClipList(self):
        return list(self._clips)

    def GetSubFolderList(self):
        return list(self._subfolders)


def _walk(root, exclude_bins=None):
    records = []
    warnings = []
    # Record only the clip name + bin path so the test stays decoupled from the
    # real clip-record schema.
    with mock.patch.object(
        dash,
        "_resolve_clip_record",
        side_effect=lambda clip, bin_path, selected_ids: {
            "name": clip.GetName(),
            "bin": bin_path,
        },
    ):
        dash._append_folder_media(
            root,
            bin_path="Master",
            recursive=True,
            selected_ids=set(),
            records=records,
            warnings=warnings,
            limit=1000,
            exclude_bins=exclude_bins,
        )
    return records


class AppendFolderMediaExclusionTest(unittest.TestCase):
    def _tree(self):
        return FakeFolder(
            "Master",
            clips=[FakeClip("top.mov")],
            subfolders=[
                FakeFolder("assets", clips=[FakeClip("logo.png")]),
                FakeFolder("footage", clips=[FakeClip("shot01.mov")]),
            ],
        )

    def test_none_indexes_every_folder(self):
        names = {r["name"] for r in _walk(self._tree(), exclude_bins=None)}
        self.assertEqual(names, {"top.mov", "logo.png", "shot01.mov"})

    def test_excluded_bin_is_skipped_entirely(self):
        names = {r["name"] for r in _walk(self._tree(), exclude_bins={"assets"})}
        self.assertEqual(names, {"top.mov", "shot01.mov"})

    def test_exclusion_is_recursive(self):
        tree = FakeFolder(
            "Master",
            subfolders=[
                FakeFolder(
                    "footage",
                    clips=[FakeClip("a.mov")],
                    subfolders=[FakeFolder("assets", clips=[FakeClip("nested.png")])],
                ),
            ],
        )
        names = {r["name"] for r in _walk(tree, exclude_bins={"assets"})}
        self.assertEqual(names, {"a.mov"})


class InventoryPreferenceTest(unittest.TestCase):
    def test_default_excludes_nothing(self):
        prefs = s._MEDIA_ANALYSIS_DEFAULT_PREFS
        self.assertEqual(prefs["inventory_limit"], 500)
        self.assertEqual(prefs["inventory_exclude_bins"], "")

    def test_effective_prefs_clamp_limit_and_normalize_bins(self):
        with mock.patch.object(
            s,
            "_read_media_analysis_preferences",
            return_value={"inventory_limit": 99999, "inventory_exclude_bins": " assets , b "},
        ):
            eff = s._media_analysis_effective_preferences()
        self.assertEqual(eff["inventory_limit"], 10000)
        self.assertEqual(eff["inventory_exclude_bins"], "assets , b")

    def test_inventory_prefs_helper_splits_into_set(self):
        # The helper imports _media_analysis_effective_preferences from src.server
        # at call time, so patching it there is sufficient.
        with mock.patch.object(
            s,
            "_media_analysis_effective_preferences",
            return_value={"inventory_limit": 250, "inventory_exclude_bins": "assets, broll"},
        ):
            limit, exclude = dash._inventory_prefs()
        self.assertEqual(limit, 250)
        self.assertEqual(exclude, {"assets", "broll"})

    def test_inventory_prefs_helper_empty_means_none(self):
        with mock.patch.object(
            s,
            "_media_analysis_effective_preferences",
            return_value={"inventory_limit": 500, "inventory_exclude_bins": ""},
        ):
            limit, exclude = dash._inventory_prefs()
        self.assertEqual(limit, 500)
        self.assertIsNone(exclude)


if __name__ == "__main__":
    unittest.main()
