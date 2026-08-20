"""Folder addressing must never silently answer about the current bin.

The defect this pins: an addressing argument the action did not recognise was
dropped, and the call went on to read (or write to) whatever folder happened to
be current, returning success. From the caller's side that is identical to the
tool ignoring its arguments, which is how it was reported.
"""
import unittest

from src import server


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
    def __init__(self, root, current):
        self._root = root
        self._current = current

    def GetRootFolder(self):
        return self._root

    def GetCurrentFolder(self):
        return self._current


def _tree():
    june20 = FakeFolder("2026-06-20", "id-0620")
    june = FakeFolder("2026-06", "id-06", subs=[june20])
    august = FakeFolder("2026-08", "id-08")
    root = FakeFolder("Master", "id-root", subs=[june, august])
    # Current folder is deliberately NOT the one the tests address.
    return FakeMP(root, august), june20


class FolderAddressingTest(unittest.TestCase):
    def test_path_wins_over_current_folder(self):
        mp, june20 = _tree()
        f, err = server._folder_from_params(mp, {"path": "Master/2026-06/2026-06-20"}, "path")
        self.assertIsNone(err)
        self.assertIs(f, june20)

    def test_folder_id_resolves(self):
        mp, june20 = _tree()
        f, err = server._folder_from_params(mp, {"folder_id": "id-0620"}, "path")
        self.assertIsNone(err)
        self.assertIs(f, june20)

    def _assert_not_found(self, err):
        # invalid_input, not resolve_api_failed: a bad address is the caller's to
        # fix, and must not come back marked retryable.
        self.assertIsNotNone(err)
        self.assertEqual(err["error"]["code"], "FOLDER_NOT_FOUND")
        self.assertEqual(err["error"]["category"], "invalid_input")
        self.assertFalse(err["error"]["retryable"])

    def test_unresolvable_path_errors_instead_of_current(self):
        mp, _ = _tree()
        f, err = server._folder_from_params(mp, {"path": "Master/nope"}, "path")
        self.assertIsNone(f)
        self._assert_not_found(err)

    def test_unresolvable_id_errors_instead_of_current(self):
        mp, _ = _tree()
        f, err = server._folder_from_params(mp, {"folder_id": "id-missing"}, "path")
        self.assertIsNone(f)
        self._assert_not_found(err)

    def test_no_address_means_current_folder(self):
        mp, _ = _tree()
        f, err = server._folder_from_params(mp, {}, "path")
        self.assertIsNone(err)
        self.assertEqual(f.GetName(), "2026-08")

    def test_no_address_root_default_preserved(self):
        # add_subfolder and get_timeline_mattes historically defaulted to root
        # (via _navigate_folder(mp, "") returning root), not the current bin.
        # The fail-loud fix must not change what omitting the address means.
        mp, _ = _tree()
        f, err = server._folder_from_params(mp, {}, "parent_path", no_address="root")
        self.assertIsNone(err)
        self.assertEqual(f.GetName(), "Master")

    def test_supplied_address_still_errors_under_root_default(self):
        mp, _ = _tree()
        f, err = server._folder_from_params(mp, {"parent_path": "Master/nope"}, "parent_path", no_address="root")
        self.assertIsNone(f)
        self.assertIsNotNone(err)

    def test_alias_folder_path_is_honoured(self):
        mp, june20 = _tree()
        f, err = server._folder_from_params(
            mp, {"folder_path": "Master/2026-06/2026-06-20"}, "path", "folder_path"
        )
        self.assertIsNone(err)
        self.assertIs(f, june20)


if __name__ == "__main__":
    unittest.main()
