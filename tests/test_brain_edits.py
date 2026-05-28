"""Unit tests for src/utils/brain_edits.py (C6).

No Resolve required. Mocks the timeline handle where metric capture is needed.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from src.utils import brain_edits, timeline_brain_db


class _MockTimeline:
    """Minimal timeline mock for capture_* helpers."""

    def __init__(
        self,
        *,
        start: int = 0,
        end: int = 240,
        fps: float = 24.0,
        clips_per_track: tuple[int, ...] = (3,),
        gaps: tuple[tuple[int, int], ...] = (),
    ) -> None:
        self._start = start
        self._end = end
        self._fps = fps
        # `gaps` is a list of (start, end) pairs that represent empty space; we
        # synthesise track items around them so capture_timeline_gap_stats sees
        # the gaps.
        self._gaps = gaps
        self._clips_per_track = clips_per_track

    def GetStartFrame(self): return self._start
    def GetEndFrame(self): return self._end
    def GetSetting(self, key): return str(self._fps) if key == "timelineFrameRate" else None

    def GetTrackCount(self, tt):
        if tt == "video":
            return len(self._clips_per_track)
        return 0

    def GetItemListInTrack(self, tt, idx):
        if tt != "video":
            return []
        # Walk from start; for each gap, produce a clip ending at gap[0] and
        # the next clip starting at gap[1].
        items: list[object] = []
        cursor = self._start
        for gap_start, gap_end in self._gaps:
            items.append(_MockItem(cursor, gap_start))
            cursor = gap_end
        items.append(_MockItem(cursor, self._end))
        return items


class _MockItem:
    def __init__(self, start: int, end: int) -> None:
        self._start = start
        self._end = end

    def GetStart(self): return self._start
    def GetEnd(self): return self._end


class BrainEdits(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="brain_edits_test_")
        # Need TWO project roots that share a base, to exercise the registry.
        self.base = self.tmp
        self.project_root = os.path.join(self.base, "project_a")
        self.other_project_root = os.path.join(self.base, "project_b")
        os.makedirs(self.project_root, exist_ok=True)
        os.makedirs(self.other_project_root, exist_ok=True)

    def tearDown(self) -> None:
        timeline_brain_db.reset_for_test(self.project_root)
        timeline_brain_db.reset_for_test(self.other_project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── capture helpers ──

    def test_capture_duration_seconds(self) -> None:
        tl = _MockTimeline(start=0, end=240, fps=24.0)
        self.assertEqual(brain_edits.capture_timeline_duration_seconds(tl), 10.0)

    def test_capture_duration_handles_zero_fps(self) -> None:
        tl = _MockTimeline(fps=0.0)
        self.assertIsNone(brain_edits.capture_timeline_duration_seconds(tl))

    def test_capture_gap_stats(self) -> None:
        tl = _MockTimeline(start=0, end=240, fps=24.0, gaps=((48, 72), (120, 144)))
        stats = brain_edits.capture_timeline_gap_stats(tl)
        self.assertEqual(stats["gap_count"], 2)
        self.assertEqual(stats["total_gap_frames"], 24 + 24)
        self.assertEqual(stats["total_gap_seconds"], 2.0)

    def test_capture_clip_count(self) -> None:
        tl = _MockTimeline(gaps=((48, 72),))  # 2 clips on one track
        self.assertEqual(brain_edits.capture_timeline_clip_count(tl), 2)

    def test_capture_metric_dispatch(self) -> None:
        tl = _MockTimeline(start=0, end=240, fps=24.0)
        self.assertEqual(brain_edits.capture_metric("duration_seconds", tl), 10.0)
        self.assertIsNone(brain_edits.capture_metric("unknown_metric", tl))

    # ── log + query ──

    def test_log_brain_edit_persists_and_returns_id(self) -> None:
        result = brain_edits.log_brain_edit(
            project_root=self.project_root,
            analysis_run_id="run_1",
            edit_type="timeline.delete_clips",
            tool_name="timeline",
            action_name="delete_clips",
            timeline_before="Edit_v01",
            timeline_after="Edit_v01",
            target_metric="duration_seconds",
            metric_direction="decrease",
            before_value=120.0,
            after_value=100.0,
            rationale="trimmed slack",
            project_name="project_a",
        )
        self.assertTrue(result["success"])
        self.assertIsNotNone(result["row_id"])

    def test_get_brain_edit_history_filters(self) -> None:
        for i, run_id in enumerate(["run_a", "run_b", "run_a"], start=1):
            brain_edits.log_brain_edit(
                project_root=self.project_root,
                analysis_run_id=run_id,
                edit_type="timeline.delete_clips",
                timeline_before=f"Edit_v0{i}",
                timeline_after=f"Edit_v0{i}",
                project_name="project_a",
            )
        all_history = brain_edits.get_brain_edit_history(project_root=self.project_root)
        self.assertEqual(len(all_history), 3)
        run_a_only = brain_edits.get_brain_edit_history(
            project_root=self.project_root, analysis_run_id="run_a"
        )
        self.assertEqual(len(run_a_only), 2)

    def test_delta_computed_when_both_values_present(self) -> None:
        brain_edits.log_brain_edit(
            project_root=self.project_root,
            analysis_run_id="run_delta",
            edit_type="timeline.delete_clips",
            before_value=120.0,
            after_value=100.0,
            project_name="project_a",
        )
        rows = brain_edits.get_brain_edit_history(
            project_root=self.project_root, analysis_run_id="run_delta",
        )
        self.assertEqual(rows[0]["delta"], -20.0)

    def test_rejects_invalid_direction(self) -> None:
        result = brain_edits.log_brain_edit(
            project_root=self.project_root,
            analysis_run_id="bad",
            edit_type="x",
            metric_direction="sideways",
            project_name="project_a",
        )
        self.assertFalse(result["success"])

    # ── cross-project registry ──

    def test_registry_aggregates_across_projects(self) -> None:
        brain_edits.log_brain_edit(
            project_root=self.project_root,
            analysis_run_id="run_x",
            edit_type="timeline.delete_clips",
            project_name="project_a",
        )
        brain_edits.log_brain_edit(
            project_root=self.other_project_root,
            analysis_run_id="run_y",
            edit_type="timeline.create_compound_clip",
            project_name="project_b",
        )
        # Both projects share `self.base` as the base root; the registry should
        # live there and contain both entries.
        registry_path = os.path.join(self.base, brain_edits.REGISTRY_FILENAME)
        self.assertTrue(os.path.isfile(registry_path), msg="registry not created")
        with open(registry_path, "r") as fh:
            payload = json.load(fh)
        project_names = {e["project_name"] for e in payload["entries"]}
        self.assertEqual(project_names, {"project_a", "project_b"})

    def test_registry_handles_corrupt_file(self) -> None:
        registry_path = os.path.join(self.base, brain_edits.REGISTRY_FILENAME)
        with open(registry_path, "w") as fh:
            fh.write("not json {")
        # Should not raise — corrupt registry is replaced fresh.
        brain_edits.log_brain_edit(
            project_root=self.project_root,
            analysis_run_id="run_resilient",
            edit_type="x",
            project_name="project_a",
        )
        with open(registry_path, "r") as fh:
            payload = json.load(fh)
        self.assertEqual(len(payload["entries"]), 1)

    def test_read_brain_edits_registry_no_file(self) -> None:
        payload = brain_edits.read_brain_edits_registry(self.project_root)
        self.assertEqual(payload["entries"], [])


if __name__ == "__main__":
    unittest.main()
