"""dry_run="false" must run the real operation, not a preview.

Handlers read ``p.get("dry_run")`` with bare truthiness, so a caller sending
``dry_run="false"`` (or "no", "0", "off") got a preview while the destructive
hook, which already coerces through ``explicit_bool_param``, had gated the
call as a real mutation. Every handler read now goes through a coercer; the
ratchet below keeps a bare read from coming back.
"""
import ast
import pathlib
import unittest

from src import server as s
from tests.test_organize_clips_create_missing import FakeClip, FakeFolder, FakeMP

SERVER = pathlib.Path(s.__file__)
COERCERS = {"_coerce_bool", "_media_analysis_bool", "_setup_bool"}
FALSE_SPELLINGS = ("false", "False", "no", "0", "off")


class RecordingMP(FakeMP):
    def __init__(self, root):
        super().__init__(root)
        self.moved = []
        self.imported_folders = []

    def MoveClips(self, clips, target):
        self.moved.append(([c.GetName() for c in clips], target.GetName()))
        return True

    def ImportFolderFromFile(self, path, source_clips_path=""):
        self.imported_folders.append(path)
        return True


def _tree():
    clip = FakeClip("A.mov", "clip-a")
    bin_ = FakeFolder("Selects", "bin-1")
    root = FakeFolder("Master", "root", clips=[clip], subs=[bin_])
    return RecordingMP(root), root, clip


class DryRunFalseRunsTheOperationTest(unittest.TestCase):
    def test_organize_clips_moves_on_false_spellings(self):
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                mp, root, clip = _tree()
                out = s._organize_clips(mp, root, {
                    "target_path": "Selects",
                    "clip_ids": [clip.GetUniqueId()],
                    "dry_run": spelling,
                })
                self.assertTrue(out.get("success"), out)
                self.assertEqual(mp.moved, [(["A.mov"], "Selects")])

    def test_organize_clips_true_spelling_still_previews(self):
        mp, root, clip = _tree()
        out = s._organize_clips(mp, root, {
            "target_path": "Selects",
            "clip_ids": [clip.GetUniqueId()],
            "dry_run": "true",
        })
        self.assertTrue(out.get("success"))
        self.assertEqual(mp.moved, [])

    def test_safe_import_folder_imports_on_false_spellings(self):
        folder = str(pathlib.Path(__file__).parent)
        for spelling in FALSE_SPELLINGS:
            with self.subTest(spelling=spelling):
                mp, _root, _clip = _tree()
                s._safe_import_folder(mp, {"path": folder, "dry_run": spelling})
                self.assertEqual(mp.imported_folders, [folder])


class NoBareDryRunReadsTest(unittest.TestCase):
    """Ratchet: every ``p.get("dry_run"...)`` in server.py sits inside a coercer."""

    def test_every_dry_run_read_is_coerced(self):
        tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        bare = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "p"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "dry_run"):
                continue
            parent = parents.get(node)
            if (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name)
                    and parent.func.id in COERCERS):
                continue
            bare.append(node.lineno)
        self.assertEqual(bare, [], f"bare dry_run reads in server.py at lines {bare}")


if __name__ == "__main__":
    unittest.main()
