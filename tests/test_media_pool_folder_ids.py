"""Folder ids passed to media_pool.delete_folders / move_folders must resolve at
any depth, and an id that resolves to nothing must fail the call.

Two defects are pinned here.

1. Both actions scanned only `root.GetSubFolderList()`, so every nested folder
   came back "No folders found" even though the caller was holding the id
   GetUniqueId() had just handed them. Reproduced live on Resolve Studio
   21.1.0.14 against Master/OUTDOORS/1_FOOTAGE/<clip bin>: the action failed
   while mp.DeleteFolders() on the recursively resolved object worked.

2. An id matching nothing was dropped, and only an all-empty result errored. So
   a mixed batch deleted or moved the subset that did resolve and answered
   {"success": true} — the caller could not tell a partial delete from a whole
   one.
"""
import unittest
from unittest import mock

from src import server as s


class FakeFolder:
    def __init__(self, name, uid, subs=None):
        self._name = name
        self._uid = uid
        self._subs = subs or []

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return self._uid

    def GetSubFolderList(self):
        return list(self._subs)


class FakeMP:
    """Records what was actually handed to Resolve, so a partial batch shows up."""

    def __init__(self, root):
        self._root = root
        self.deleted = None
        self.moved = None

    def GetRootFolder(self):
        return self._root

    def GetCurrentFolder(self):
        return self._root

    def DeleteFolders(self, folders):
        self.deleted = list(folders)
        return True

    def MoveFolders(self, folders, target):
        self.moved = (list(folders), target)
        return True


def _tree():
    # Master/OUTDOORS/1_FOOTAGE/wetransfer — the live repro's shape: the target
    # sits three levels below root, so a scan of root's children cannot see it.
    nested = FakeFolder("wetransfer_dscf1065-mov", "id-nested")
    footage = FakeFolder("1_FOOTAGE", "id-footage", subs=[nested])
    outdoors = FakeFolder("OUTDOORS", "id-outdoors", subs=[footage])
    dest = FakeFolder("ARCHIVE", "id-archive")
    root = FakeFolder("Master", "id-root", subs=[outdoors, dest])
    return FakeMP(root), nested, dest


def _call(mp, action, params, *, require_confirm=False):
    proj = mock.Mock()
    with mock.patch.object(s, "_confirm_token_required", return_value=require_confirm), \
         mock.patch.object(s, "_check", return_value=(mock.Mock(), proj, None)), \
         mock.patch.object(s, "_get_mp", return_value=(mock.Mock(), proj, mp, None)):
        return s.media_pool(action, params)


class NestedFolderResolutionTest(unittest.TestCase):
    def test_delete_folders_resolves_nested_id(self):
        mp, nested, _ = _tree()
        out = _call(mp, "delete_folders", {"folder_ids": ["id-nested"]})
        self.assertNotIn("error", out)
        self.assertTrue(out["success"])
        self.assertEqual(mp.deleted, [nested])

    def test_move_folders_resolves_nested_id(self):
        mp, nested, dest = _tree()
        out = _call(mp, "move_folders",
                    {"folder_ids": ["id-nested"], "target_path": "Master/ARCHIVE"})
        self.assertNotIn("error", out)
        self.assertTrue(out["success"])
        self.assertEqual(mp.moved, ([nested], dest))

    def test_delete_folders_preview_names_the_nested_folder(self):
        # The confirm preview is the only thing the user sees before a delete;
        # it must describe the nested folder, not an empty batch.
        mp, _, _ = _tree()
        out = _call(mp, "delete_folders", {"folder_ids": ["id-nested"]},
                    require_confirm=True)
        self.assertEqual(out.get("status"), "confirmation_required")
        self.assertEqual(out["preview"]["folders_lost"], 1)
        self.assertEqual(out["preview"]["names"], ["wetransfer_dscf1065-mov"])
        self.assertIsNone(mp.deleted)


class UnresolvedFolderIdTest(unittest.TestCase):
    def _assert_not_found(self, out, missing):
        self.assertIn("error", out)
        self.assertEqual(out["error"]["code"], "FOLDER_NOT_FOUND")
        self.assertEqual(out["error"]["category"], "invalid_input")
        self.assertFalse(out["error"]["retryable"])
        self.assertEqual(out["error"]["state"]["unresolved_folder_ids"], missing)

    def test_partial_match_deletes_nothing(self):
        mp, _, _ = _tree()
        out = _call(mp, "delete_folders", {"folder_ids": ["id-nested", "id-ghost"]})
        self._assert_not_found(out, ["id-ghost"])
        self.assertIsNone(mp.deleted)

    def test_partial_match_moves_nothing(self):
        mp, _, _ = _tree()
        out = _call(mp, "move_folders",
                    {"folder_ids": ["id-nested", "id-ghost"], "target_path": "Master/ARCHIVE"})
        self._assert_not_found(out, ["id-ghost"])
        self.assertIsNone(mp.moved)

    def test_unresolved_error_names_what_did_resolve(self):
        mp, _, _ = _tree()
        out = _call(mp, "delete_folders", {"folder_ids": ["id-nested", "id-ghost"]})
        self.assertEqual(out["error"]["state"]["resolved_folder_ids"], ["id-nested"])

    def test_all_unresolved_still_errors(self):
        mp, _, _ = _tree()
        out = _call(mp, "delete_folders", {"folder_ids": ["id-ghost"]})
        self._assert_not_found(out, ["id-ghost"])
        self.assertIsNone(mp.deleted)

    def test_root_folder_is_refused(self):
        # The recursive search can reach root, which the shallow one never could.
        # Deleting/moving Master is not a thing; refuse before Resolve sees it.
        mp, _, _ = _tree()
        out = _call(mp, "delete_folders", {"folder_ids": ["id-root"]})
        self.assertEqual(out["error"]["code"], "ROOT_FOLDER_NOT_ELIGIBLE")
        self.assertIsNone(mp.deleted)

    def test_empty_folder_ids_is_invalid_input(self):
        mp, _, _ = _tree()
        out = _call(mp, "delete_folders", {"folder_ids": []})
        self.assertEqual(out["error"]["code"], "INVALID_FOLDER_IDS")
        self.assertEqual(out["error"]["category"], "invalid_input")
        self.assertIsNone(mp.deleted)

    def test_missing_folder_ids_uses_the_standard_missing_param_error(self):
        # p["folder_ids"] stays an item lookup so _Params raises _MissingParam and
        # the tool boundary answers MISSING_FOLDER_IDS, like every other action.
        mp, _, _ = _tree()
        out = _call(mp, "delete_folders", {})
        self.assertEqual(out["error"]["code"], "MISSING_FOLDER_IDS")
        self.assertEqual(out["error"]["category"], "invalid_input")
        self.assertIsNone(mp.deleted)

    def test_bare_string_folder_ids_is_invalid_input(self):
        # A bare string used to be iterated character by character, so every
        # character became an id that matched nothing and was then dropped.
        mp, _, _ = _tree()
        out = _call(mp, "delete_folders", {"folder_ids": "id-nested"})
        self.assertEqual(out["error"]["code"], "INVALID_FOLDER_IDS")
        self.assertEqual(out["error"]["category"], "invalid_input")
        self.assertIsNone(mp.deleted)


if __name__ == "__main__":
    unittest.main()
