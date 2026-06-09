import tempfile
import unittest
from pathlib import Path

from src.server import (
    _build_relink_plan,
    _compare_timeline_snapshots,
    _conform_capabilities,
    _detect_gaps_overlaps_from_snapshot,
    _detect_missing_media_from_snapshot,
    _export_timeline_checked,
    _source_ranges_from_snapshot,
    _timeline_conform_snapshot,
    _timeline_export_spec,
)


class MediaPoolItemStub:
    def __init__(self, name, item_id, file_path):
        self.name = name
        self.item_id = item_id
        self.file_path = file_path

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.item_id

    def GetClipProperty(self, key=""):
        return {
            "File Path": self.file_path,
            "Type": "Video + Audio",
            "Duration": "00:00:02:00",
            "Status": "Offline" if self.file_path and not Path(self.file_path).exists() else "Online",
        }


class TimelineItemStub:
    def __init__(self, name, item_id, start, end, source_start, track_type, track_index, media_pool_item):
        self.name = name
        self.item_id = item_id
        self.start = start
        self.end = end
        self.source_start = source_start
        self.track_type = track_type
        self.track_index = track_index
        self.media_pool_item = media_pool_item

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.item_id

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetDuration(self):
        return self.end - self.start

    def GetSourceStartFrame(self):
        return self.source_start

    def GetLeftOffset(self):
        return self.source_start

    def GetTrackTypeAndIndex(self):
        return [self.track_type, self.track_index]

    def GetMediaPoolItem(self):
        return self.media_pool_item


class TimelineStub:
    def __init__(self, tracks):
        self.tracks = tracks

    def GetName(self):
        return "Conform Stub"

    def GetUniqueId(self):
        return "timeline-1"

    def GetStartFrame(self):
        return 86400

    def GetEndFrame(self):
        return 86500

    def GetStartTimecode(self):
        return "01:00:00:00"

    def GetTrackCount(self, track_type):
        return len(self.tracks.get(track_type, {}))

    def GetItemListInTrack(self, track_type, track_index):
        return self.tracks.get(track_type, {}).get(track_index, [])

    def GetMarkers(self):
        return {}

    def Export(self, path, export_type, export_subtype):
        export_path = Path(path)
        if str(path).endswith(".fcpxml"):
            export_path.mkdir(parents=True, exist_ok=True)
            (export_path / "Info.fcpxml").write_text("<fcpxml />", encoding="utf-8")
            return True
        export_path.write_text("export", encoding="utf-8")
        return True


class ResolveConstStub:
    EXPORT_FCPXML_1_10 = 1010
    EXPORT_NONE = 0


class TimelineConformProbeTest(unittest.TestCase):
    def _timeline(self, missing_path="/tmp/missing_source.mov"):
        online = MediaPoolItemStub("A.mov", "mpi-a", __file__)
        missing = MediaPoolItemStub("B.mov", "mpi-b", missing_path)
        return TimelineStub(
            {
                "video": {
                    1: [
                        TimelineItemStub("A", "a1", 0, 10, 100, "video", 1, online),
                        TimelineItemStub("B", "b1", 15, 25, 200, "video", 1, missing),
                    ],
                    2: [
                        TimelineItemStub("C", "c1", 5, 18, 300, "video", 2, online),
                    ],
                },
                "audio": {
                    1: [
                        TimelineItemStub("A.wav", "a2", 0, 10, 100, "audio", 1, online),
                    ]
                },
            }
        )

    def test_capabilities_include_interchange_aliases(self):
        caps = _conform_capabilities()

        self.assertIn("fcpxml", caps["export_aliases"])
        self.assertIn("interchange", caps["supported"])

    def test_snapshot_and_gap_detection(self):
        snapshot = _timeline_conform_snapshot(self._timeline())
        gaps = _detect_gaps_overlaps_from_snapshot(snapshot)

        self.assertEqual(snapshot["item_count"], 4)
        self.assertEqual(gaps["gap_count"], 1)
        self.assertEqual(gaps["gaps"][0]["duration"], 5)

    def test_source_ranges_merge_by_source(self):
        snapshot = _timeline_conform_snapshot(self._timeline())
        report = _source_ranges_from_snapshot(snapshot, {"handles": 2})

        self.assertTrue(report["ranges"])
        first_key = next(iter(report["ranges"]))
        self.assertLessEqual(report["ranges"][first_key][0][0], 100)

    def test_compare_snapshots_reports_item_mismatch(self):
        left = _timeline_conform_snapshot(self._timeline())
        right = _timeline_conform_snapshot(
            TimelineStub({"video": {1: [TimelineItemStub("Changed", "x", 0, 9, 100, "video", 1, None)]}})
        )
        diff = _compare_timeline_snapshots(left, right)

        self.assertFalse(diff["match"])
        self.assertGreater(diff["difference_count"], 0)

    def test_export_spec_resolves_alias_constants(self):
        spec = _timeline_export_spec({"format": "fcpxml"}, ResolveConstStub())

        self.assertEqual(spec["export_type"], ResolveConstStub.EXPORT_FCPXML_1_10)
        self.assertEqual(spec["export_subtype"], ResolveConstStub.EXPORT_NONE)

    def test_export_checked_reports_directory_primary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "timeline.fcpxml")
            result = _export_timeline_checked(
                self._timeline(),
                {"format": "fcpxml", "path": path, "require_temp_path": False},
            )

        self.assertTrue(result["success"])
        self.assertTrue(result["is_directory"])
        self.assertTrue(result["primary_file"].endswith("Info.fcpxml"))

    def test_missing_media_and_relink_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_path = str(Path(tmp) / "offline" / "lost.mov")
            replacement = Path(tmp) / "lost.mov"
            replacement.write_text("replacement", encoding="utf-8")
            timeline = self._timeline(missing_path=missing_path)
            snapshot = _timeline_conform_snapshot(timeline)
            missing = _detect_missing_media_from_snapshot(snapshot)
            plan = _build_relink_plan(timeline, {"search_roots": [tmp]})

        self.assertEqual(missing["missing_count"], 1)
        self.assertEqual(missing["diagnosis"]["unique_media_pool_item_count"], 1)
        self.assertEqual(missing["diagnosis"]["primary_cause"], "folder_not_found")
        self.assertTrue(plan["success"])
        self.assertEqual(plan["candidate_count"], 1)
        self.assertEqual(plan["unique_missing_basename_count"], 1)

    def test_relink_plan_skips_search_when_source_volume_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            replacement = Path(tmp) / "P1047043.MOV"
            replacement.write_text("replacement", encoding="utf-8")
            missing_path = "/Volumes/EOS_DIGITAL/DCIM/104_PANA/P1047043.MOV"
            timeline = self._timeline(missing_path=missing_path)
            plan = _build_relink_plan(timeline, {"search_roots": [tmp], "sanitized": True})

        self.assertTrue(plan["success"])
        self.assertTrue(plan["search_skipped"])
        self.assertEqual(plan["skip_reason"], "missing_source_volume_not_mounted")
        self.assertEqual(plan["candidate_count"], 0)
        self.assertEqual(plan["diagnosis"]["primary_cause"], "volume_not_mounted")
        self.assertEqual(plan["diagnosis"]["missing_volumes"][0]["volume_root_sanitized"], "/Volumes/EOS_DIGITAL/...")
        self.assertNotIn(tmp, str(plan))


if __name__ == "__main__":
    unittest.main()
