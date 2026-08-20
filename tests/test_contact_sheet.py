"""Frame resolution for scripts/contact_sheet.py.

The ordering in `load_frames` is load-bearing and easy to "tidy" into a bug.
While vision is pending, `visual.json`'s `frame_paths` IS the payload
`commit_vision` expects findings reported against, so its indices must win.
`analysis.json` holds a larger superset (the vision sample plus cut-boundary
frames) whose numbering does NOT line up — preferring it would produce sheets
whose labels point at the wrong frames, silently, with every frame still
present and the contact sheet looking perfectly correct.

After `commit_vision` replaces `visual.json` and drops `frame_paths`,
`analysis.json` is the richest surviving source and alignment no longer matters
because there is no vision payload left to report against.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

try:
    import contact_sheet
except SystemExit:  # pragma: no cover - Pillow absent; the script exits on import
    contact_sheet = None


def _touch(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return str(path)


@unittest.skipIf(contact_sheet is None, "Pillow not installed")
class LoadFramesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="contact_sheet_")
        self.clip = Path(self.tmp)
        self.frames = [
            _touch(self.clip / "frames" / f"f{i:03d}.jpg") for i in range(1, 4)
        ]

    def _write(self, name: str, payload: dict) -> None:
        (self.clip / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_visual_json_wins_while_vision_is_pending(self) -> None:
        """The whole point: analysis.json's superset must not hijack the
        indices commit_vision reports against."""
        self._write("visual.json", {
            "frame_paths": self.frames[:2],
            "frame_metadata": [
                {"frame_index": 1, "time_seconds": 0.5, "selection_reason": "shot_start"},
            ],
        })
        self._write("analysis.json", {
            "analysis_keyframes": [
                {"frame_path": p, "time_seconds": i, "index": i}
                for i, p in enumerate(self.frames, start=1)
            ]
        })
        paths, meta = contact_sheet.load_frames(str(self.clip))
        self.assertEqual(paths, self.frames[:2], "analysis.json superset hijacked the indices")
        self.assertEqual(meta[1]["selection_reason"], "shot_start")

    def test_analysis_json_is_used_once_visual_has_been_committed(self) -> None:
        # commit_vision rewrites visual.json WITHOUT frame_paths.
        self._write("visual.json", {"summary": "committed", "shots": []})
        self._write("analysis.json", {
            "analysis_keyframes": [
                {"frame_path": p, "time_seconds": float(i), "index": i}
                for i, p in enumerate(self.frames, start=1)
            ]
        })
        paths, meta = contact_sheet.load_frames(str(self.clip))
        self.assertEqual(paths, self.frames)
        self.assertEqual(meta[1]["time_seconds"], 1.0)

    def test_frames_dir_is_the_last_resort(self) -> None:
        paths, meta = contact_sheet.load_frames(str(self.clip))
        self.assertEqual(sorted(paths), sorted(self.frames))
        self.assertEqual(meta, {})

    def test_frame_paths_that_no_longer_exist_are_dropped(self) -> None:
        """A stale visual.json must not put missing files into the sheet —
        build_sheets opens every path it is handed."""
        self._write("visual.json", {
            "frame_paths": self.frames[:1] + [str(self.clip / "frames" / "gone.jpg")],
            "frame_metadata": [],
        })
        paths, _ = contact_sheet.load_frames(str(self.clip))
        self.assertEqual(paths, self.frames[:1])

    def test_an_empty_visual_falls_through_rather_than_returning_nothing(self) -> None:
        """frame_paths present but every file missing is the pending-but-moved
        case; it must not shadow a usable analysis.json."""
        self._write("visual.json", {"frame_paths": [str(self.clip / "nope.jpg")]})
        self._write("analysis.json", {
            "analysis_keyframes": [
                {"frame_path": p, "time_seconds": 1.0, "index": 1} for p in self.frames[:1]
            ]
        })
        paths, _ = contact_sheet.load_frames(str(self.clip))
        self.assertEqual(paths, self.frames[:1])

    def test_unreadable_json_does_not_raise(self) -> None:
        (self.clip / "visual.json").write_text("{not json", encoding="utf-8")
        paths, _ = contact_sheet.load_frames(str(self.clip))
        self.assertEqual(sorted(paths), sorted(self.frames))

    def test_a_clip_dir_with_nothing_reports_empty(self) -> None:
        empty = tempfile.mkdtemp(prefix="contact_sheet_empty_")
        paths, meta = contact_sheet.load_frames(empty)
        self.assertEqual(paths, [])
        self.assertEqual(meta, {})


@unittest.skipIf(contact_sheet is None, "Pillow not installed")
class BuildSheetsTests(unittest.TestCase):
    """The label index must match the frame's position in the sheet, since
    that number is what per-frame findings are reported against."""

    def test_tiles_are_labelled_by_their_position_across_sheet_boundaries(self) -> None:
        from PIL import Image

        tmp = Path(tempfile.mkdtemp(prefix="contact_sheet_build_"))
        frames_dir = tmp / "frames"
        frames_dir.mkdir(parents=True)
        paths = []
        for i in range(1, 6):
            p = frames_dir / f"f{i:03d}.jpg"
            Image.new("RGB", (64, 36), (i * 20, 0, 0)).save(p)
            paths.append(str(p))
        (tmp / "visual.json").write_text(json.dumps({
            "frame_paths": paths,
            "frame_metadata": [
                {"frame_index": i, "time_seconds": i * 1.0, "selection_reason": "x"}
                for i in range(1, 6)
            ],
        }), encoding="utf-8")

        out = tmp / "sheets"
        # 2 per sheet forces a boundary: sheet 2 must start at frame 3, not 1.
        sheets, count = contact_sheet.build_sheets(
            str(tmp), str(out), tile_width=64, columns=2, rows=1
        )
        self.assertEqual(count, 5)
        self.assertEqual([(first, last) for _, first, last in sheets],
                         [(1, 2), (3, 4), (5, 5)])
        for path, _, _ in sheets:
            self.assertTrue(os.path.exists(path))

    def test_tile_height_follows_the_source_aspect_not_16_9(self) -> None:
        """Vertical phone footage arrives already rotated to portrait; assuming
        16:9 would letterbox every tile."""
        from PIL import Image

        tmp = Path(tempfile.mkdtemp(prefix="contact_sheet_portrait_"))
        frames_dir = tmp / "frames"
        frames_dir.mkdir(parents=True)
        for i in range(1, 3):
            Image.new("RGB", (1080, 1920), (0, 0, 0)).save(frames_dir / f"f{i:03d}.jpg")

        out = tmp / "sheets"
        sheets, count = contact_sheet.build_sheets(
            str(tmp), str(out), tile_width=100, columns=2, rows=1
        )
        self.assertEqual(count, 2)
        with Image.open(sheets[0][0]) as sheet:
            # 100 wide at 1080x1920 -> ~178 tall, plus the label strip.
            self.assertGreater(sheet.height, 150)


if __name__ == "__main__":
    unittest.main()
