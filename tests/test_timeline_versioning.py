"""Unit tests for src/utils/timeline_versioning.py (C6).

No Resolve required. Mocks Project/MediaPool/Timeline handles to verify the
archive-and-rename flow + DB-side state.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from src.utils import timeline_brain_db, timeline_versioning


class _MockMediaPoolItem:
    def __init__(self, unique_id: str) -> None:
        self._unique_id = unique_id
    def GetUniqueId(self): return self._unique_id


class _MockTimelineItem:
    def __init__(self, start: int, end: int, mpi_id: str) -> None:
        self._start = start
        self._end = end
        self._mpi_id = mpi_id
    def GetStart(self) -> int: return self._start
    def GetEnd(self) -> int: return self._end
    def GetUniqueId(self) -> str: return f"item_{self._mpi_id}_{self._start}"
    def GetMediaPoolItem(self): return _MockMediaPoolItem(self._mpi_id)


class _MockTimeline:
    def __init__(self, name: str, unique_id: str = "tl_1", *, tracks=None) -> None:
        self._name = name
        self._unique_id = unique_id
        self.duplicates: list[str] = []
        # tracks: dict {("video", track_idx): [_MockTimelineItem, ...]}
        # Mocks default to no tracks so existing tests aren't affected.
        self._tracks: dict = tracks or {}

    def GetName(self) -> str: return self._name
    def GetUniqueId(self) -> str: return self._unique_id
    def DuplicateTimeline(self, new_name: str) -> "_MockTimeline":
        self.duplicates.append(new_name)
        return _MockTimeline(new_name, unique_id=f"{self._unique_id}_dup")
    def Export(self, path: str, export_type: int) -> bool:
        with open(path, "w") as fh:
            fh.write(f"FAKE DRT for {self._name}")
        return True

    # Track surface (only present if tracks were provided)
    def GetTrackCount(self, track_type: str) -> int:
        return max(
            (k[1] for k in self._tracks if k[0] == track_type),
            default=0,
        )

    def GetItemListInTrack(self, track_type: str, track_idx: int):
        return self._tracks.get((track_type, track_idx), [])

    def set_tracks(self, tracks: dict) -> None:
        self._tracks = tracks


class _MockSubFolder:
    def __init__(self, name: str) -> None:
        self._name = name
    def GetName(self) -> str: return self._name


class _MockRootFolder:
    def __init__(self) -> None:
        self.subfolders: list[_MockSubFolder] = []
    def GetSubFolderList(self) -> list[_MockSubFolder]:
        return list(self.subfolders)


class _MockMediaPool:
    def __init__(self) -> None:
        self.root = _MockRootFolder()
        self.current_folder: object = self.root
        self.added_subfolders: list[str] = []
    def GetRootFolder(self) -> _MockRootFolder: return self.root
    def AddSubFolder(self, parent: object, name: str) -> _MockSubFolder:
        sub = _MockSubFolder(name)
        self.root.subfolders.append(sub)
        self.added_subfolders.append(name)
        return sub
    def SetCurrentFolder(self, folder: object) -> bool:
        self.current_folder = folder
        return True
    def ImportTimelineFromFile(self, path: str) -> _MockTimeline:
        return _MockTimeline(name=os.path.basename(path).rsplit(".", 1)[0])


class _MockProject:
    def __init__(self, timeline: _MockTimeline) -> None:
        self._current_timeline = timeline
        self._timelines: list[_MockTimeline] = [timeline]
        self._media_pool = _MockMediaPool()
        self.delete_calls: list[list[_MockTimeline]] = []
    def GetCurrentTimeline(self) -> _MockTimeline: return self._current_timeline
    def SetCurrentTimeline(self, tl: _MockTimeline) -> bool:
        self._current_timeline = tl
        return True
    def GetTimelineCount(self) -> int: return len(self._timelines)
    def GetTimelineByIndex(self, idx: int) -> _MockTimeline:
        return self._timelines[idx - 1]
    def GetMediaPool(self) -> _MockMediaPool: return self._media_pool
    def DeleteTimelines(self, tls: list[_MockTimeline]) -> bool:
        self.delete_calls.append(list(tls))
        for tl in tls:
            try:
                self._timelines.remove(tl)
            except ValueError:
                pass
        return True


class TimelineVersioning(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="versioning_test_")
        self.project_root = os.path.join(self.tmp, "project")
        os.makedirs(self.project_root, exist_ok=True)
        self.timeline = _MockTimeline("Edit")
        self.project = _MockProject(self.timeline)
        # Once the project mock adds a duplicate, append it to the project's
        # timeline list so subsequent lookups + retention can find it.
        original_dup = self.timeline.DuplicateTimeline
        def tracked_dup(new_name: str) -> _MockTimeline:
            new_tl = original_dup(new_name)
            self.project._timelines.append(new_tl)
            new_tl_dup = new_tl.DuplicateTimeline
            def chained(name: str) -> _MockTimeline:
                child = new_tl_dup(name)
                self.project._timelines.append(child)
                return child
            new_tl.DuplicateTimeline = chained  # type: ignore[method-assign]
            return new_tl
        self.timeline.DuplicateTimeline = tracked_dup  # type: ignore[method-assign]

    def tearDown(self) -> None:
        timeline_brain_db.reset_for_test(self.project_root)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_archive_creates_archive_bin_and_duplicate(self) -> None:
        result = timeline_versioning.archive_current_timeline(
            resolve=None,
            project=self.project,
            project_root=self.project_root,
            reason="test",
            analysis_run_id="run_1",
        )
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["archived_timeline_name"], "Edit_archived_v01")
        self.assertIn("Archive", self.project._media_pool.added_subfolders)
        # Current timeline restored to original after duplication.
        self.assertIs(self.project.GetCurrentTimeline(), self.timeline)

    def test_archive_increments_version(self) -> None:
        timeline_versioning.archive_current_timeline(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="run_1",
        )
        r2 = timeline_versioning.archive_current_timeline(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="run_2",
        )
        self.assertEqual(r2["version"], 2)
        self.assertEqual(r2["archived_timeline_name"], "Edit_archived_v02")

    def test_ensure_versioned_is_idempotent_within_run(self) -> None:
        first = timeline_versioning.ensure_versioned_before_mutation(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="run_same",
        )
        second = timeline_versioning.ensure_versioned_before_mutation(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="run_same",
        )
        self.assertTrue(first["archived"])
        self.assertFalse(second["archived"])
        self.assertEqual(second["skipped_reason"], "already_archived_for_run")

    def test_ensure_versioned_archives_on_new_run(self) -> None:
        timeline_versioning.ensure_versioned_before_mutation(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="run_one",
        )
        again = timeline_versioning.ensure_versioned_before_mutation(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="run_two",
        )
        self.assertTrue(again["archived"])
        self.assertEqual(again["version"], 2)

    def test_list_versions_returns_chain(self) -> None:
        for rid in ("a", "b", "c"):
            timeline_versioning.archive_current_timeline(
                resolve=None, project=self.project, project_root=self.project_root,
                analysis_run_id=rid,
            )
        chain = timeline_versioning.list_timeline_versions(
            project_root=self.project_root, timeline_name="Edit",
        )
        self.assertEqual([v["version"] for v in chain], [1, 2, 3])

    def test_rollback_archives_current_and_restores_version(self) -> None:
        timeline_versioning.archive_current_timeline(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="initial",
        )
        result = timeline_versioning.rollback_to_version(
            resolve=None, project=self.project, project_root=self.project_root,
            timeline_name="Edit", version=1,
        )
        self.assertTrue(result["success"], msg=result)
        self.assertIn("_rolled_back_", result["restored_timeline_name"])
        # Rollback should have archived current first.
        self.assertTrue(result["archive_of_previous"]["archived"])

    def test_rollback_unknown_version_returns_error(self) -> None:
        result = timeline_versioning.rollback_to_version(
            resolve=None, project=self.project, project_root=self.project_root,
            timeline_name="Edit", version=99,
        )
        self.assertFalse(result["success"])
        self.assertIn("No version", (result["error"].get("message","") if isinstance(result["error"], dict) else result["error"]))

    def test_archive_writes_structural_snapshot(self) -> None:
        # Give the timeline a known layout: 3 video clips on V1.
        self.timeline.set_tracks({
            ("video", 1): [
                _MockTimelineItem(0, 100, "mpi_a"),
                _MockTimelineItem(100, 200, "mpi_b"),
                _MockTimelineItem(200, 300, "mpi_c"),
            ],
        })
        result = timeline_versioning.archive_current_timeline(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="run_snap",
        )
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["snapshot_clip_count"], 3)

        conn = timeline_brain_db.connect(self.project_root)
        rows = conn.execute(
            "SELECT media_pool_item_id, in_frame, out_frame FROM timeline_clip_usage "
            "WHERE timeline_name = ? AND timeline_version = ? ORDER BY in_frame",
            ("Edit", 1),
        ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["media_pool_item_id"] for r in rows], ["mpi_a", "mpi_b", "mpi_c"])

    def test_diff_versions_detects_added_removed_moved(self) -> None:
        # v1: a, b, c on V1
        self.timeline.set_tracks({
            ("video", 1): [
                _MockTimelineItem(0, 100, "mpi_a"),
                _MockTimelineItem(100, 200, "mpi_b"),
                _MockTimelineItem(200, 300, "mpi_c"),
            ],
        })
        timeline_versioning.archive_current_timeline(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="run_1",
        )
        # v2: b removed, d added, a moved to a later in_frame
        self.timeline.set_tracks({
            ("video", 1): [
                _MockTimelineItem(50, 150, "mpi_a"),   # moved
                _MockTimelineItem(200, 300, "mpi_c"),  # unchanged
                _MockTimelineItem(300, 400, "mpi_d"),  # added
            ],
        })
        timeline_versioning.archive_current_timeline(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="run_2",
        )

        diff = timeline_versioning.diff_versions(
            project_root=self.project_root,
            timeline_name="Edit",
            from_version=1, to_version=2,
        )
        added_ids = {r["media_pool_item_id"] for r in diff["added"]}
        removed_ids = {r["media_pool_item_id"] for r in diff["removed"]}
        moved_ids = {r["media_pool_item_id"] for r in diff["moved"]}
        self.assertIn("mpi_d", added_ids)
        self.assertIn("mpi_b", removed_ids)
        self.assertIn("mpi_a", moved_ids)
        # mpi_c was unchanged — should appear in none.
        self.assertNotIn("mpi_c", added_ids | removed_ids | moved_ids)

    def test_diff_versions_summary_and_trimmed(self) -> None:
        # v1: a (0-100), b (100-200)
        self.timeline.set_tracks({
            ("video", 1): [
                _MockTimelineItem(0, 100, "mpi_a"),
                _MockTimelineItem(100, 200, "mpi_b"),
            ],
        })
        timeline_versioning.archive_current_timeline(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="run_1",
        )
        # v2: a trimmed (0-80, same in_frame), b unchanged
        self.timeline.set_tracks({
            ("video", 1): [
                _MockTimelineItem(0, 80, "mpi_a"),     # trimmed (out 100 -> 80)
                _MockTimelineItem(100, 200, "mpi_b"),  # unchanged
            ],
        })
        timeline_versioning.archive_current_timeline(
            resolve=None, project=self.project, project_root=self.project_root,
            analysis_run_id="run_2",
        )
        diff = timeline_versioning.diff_versions(
            project_root=self.project_root, timeline_name="Edit",
            from_version=1, to_version=2,
        )
        self.assertEqual([r["media_pool_item_id"] for r in diff["trimmed"]], ["mpi_a"])
        self.assertEqual(diff["trimmed"][0]["out_frame_before"], 100)
        self.assertEqual(diff["trimmed"][0]["out_frame"], 80)
        self.assertIn("summary", diff)
        self.assertEqual(diff["summary"]["trimmed"], 1)
        self.assertEqual(diff["summary"]["before_clip_count"], 2)
        self.assertEqual(diff["summary"]["after_clip_count"], 2)

    def test_prune_collapses_old_versions_to_drt(self) -> None:
        for rid in [f"run_{i}" for i in range(5)]:
            timeline_versioning.archive_current_timeline(
                resolve=None, project=self.project, project_root=self.project_root,
                analysis_run_id=rid,
            )
        prune = timeline_versioning.prune_archived_versions(
            resolve=None, project=self.project, project_root=self.project_root,
            timeline_name="Edit", keep_n=2,
        )
        self.assertTrue(prune["success"])
        self.assertEqual(prune["pruned"], 3)
        # Verify .drt files exist and DB rows have drt_export_path populated.
        chain = timeline_versioning.list_timeline_versions(
            project_root=self.project_root, timeline_name="Edit",
        )
        collapsed = [v for v in chain if v["drt_export_path"]]
        self.assertEqual(len(collapsed), 3)
        for v in collapsed:
            self.assertTrue(os.path.isfile(v["drt_export_path"]))


class DiffTimelinesTests(unittest.TestCase):
    """Cross-name structural diff between two LIVE timelines (no archived
    version rows needed) — the edit-engine variant readback path."""

    def _project(self) -> _MockProject:
        source = _MockTimeline("Source", unique_id="tl_src", tracks={
            ("video", 1): [_MockTimelineItem(0, 100, "a"), _MockTimelineItem(100, 200, "b")],
            ("audio", 1): [_MockTimelineItem(0, 200, "a")],
        })
        variant = _MockTimeline("Variant", unique_id="tl_var", tracks={
            ("video", 1): [_MockTimelineItem(0, 80, "a"), _MockTimelineItem(80, 160, "c")],
        })
        project = _MockProject(source)
        project._timelines.append(variant)
        return project

    def test_capture_timeline_clip_usage_shape(self) -> None:
        rows = timeline_versioning.capture_timeline_clip_usage(
            self._project().GetCurrentTimeline()
        )
        self.assertEqual(len(rows), 3)  # 2 video + 1 audio
        self.assertEqual(
            rows[0],
            {"media_pool_item_id": "a", "track_type": "video", "track_index": 1,
             "in_frame": 0, "out_frame": 100},
        )

    def test_diff_timelines_added_removed_trimmed(self) -> None:
        out = timeline_versioning.diff_timelines(
            project=self._project(), from_timeline="Source", to_timeline="Variant",
        )
        self.assertTrue(out["success"], out)
        self.assertEqual(out["from_timeline"], "Source")
        # a@video/1/0 trimmed 100→80; b + audio-a removed; c added.
        self.assertEqual(out["summary"]["trimmed"], 1)
        self.assertEqual(out["trimmed"][0]["out_frame_before"], 100)
        self.assertEqual(out["summary"]["added"], 1)
        self.assertEqual(out["added"][0]["media_pool_item_id"], "c")
        removed_ids = sorted(r["media_pool_item_id"] for r in out["removed"])
        self.assertEqual(removed_ids, ["a", "b"])  # audio a + video b
        self.assertEqual(out["summary"]["before_clip_count"], 3)
        self.assertEqual(out["summary"]["after_clip_count"], 2)

    def test_diff_timelines_detects_moves(self) -> None:
        project = self._project()
        moved_variant = _MockTimeline("Moved", unique_id="tl_mv", tracks={
            ("video", 1): [_MockTimelineItem(50, 150, "a")],
        })
        project._timelines.append(moved_variant)
        out = timeline_versioning.diff_timelines(
            project=project, from_timeline="Source", to_timeline="Moved",
        )
        self.assertEqual(out["summary"]["moved"], 1)
        self.assertEqual(out["moved"][0]["media_pool_item_id"], "a")

    def test_diff_timelines_missing_name_errors(self) -> None:
        out = timeline_versioning.diff_timelines(
            project=self._project(), from_timeline="Source", to_timeline="Nope",
        )
        self.assertFalse(out["success"])
        self.assertIn("Nope", out["error"])


if __name__ == "__main__":
    unittest.main()
