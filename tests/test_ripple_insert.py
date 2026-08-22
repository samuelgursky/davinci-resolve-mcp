"""Offline tests for timeline.ripple_insert and the duplicate-verified gate.

The geometry mirrors the 2026-08-20 live validation (Studio 21.0.4): a
3 x 48-frame timeline starting at 86400, inserting 24 source frames at
relative frame 48, expecting [(86400,48),(86448,24),(86472,48),(86520,48)].
The null-id append case reproduces the failure that lost 26 clips on the
Portugal timeline (2026-08-19): AppendToTimeline returns an item whose id
cannot be read and no live item can be recovered, so the duplicate must not
count as verified and delete_sources must keep the source.
"""
import unittest
from unittest import mock

import src.server as s
import src.utils.destructive_hook as destructive_hook


TL_START = 86400


class MediaPoolItemStub:
    def __init__(self, unique_id="pool-1", name="beach.mov"):
        self.unique_id = unique_id
        self.name = name

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name


class FolderStub:
    def __init__(self, clips=None):
        self.clips = clips or []

    def GetClipList(self):
        return list(self.clips)

    def GetSubFolderList(self):
        return []


class ItemStub:
    def __init__(self, unique_id, name, start, duration, mpi, props=None):
        self.unique_id = unique_id
        self.name = name
        self.start = start
        self.duration = duration
        self.mpi = mpi
        self.props = dict(props or {})

    def GetUniqueId(self):
        return self.unique_id

    def GetName(self):
        return self.name

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.start + self.duration

    def GetDuration(self):
        return self.duration

    def GetMediaPoolItem(self):
        return self.mpi

    def GetSourceStartFrame(self):
        return 0

    def GetLeftOffset(self):
        return 0

    def GetTrackTypeAndIndex(self):
        return ["video", 1]

    def GetLinkedItems(self):
        return []

    def GetProperty(self, key=None):
        if key is None:
            return dict(self.props)
        return self.props.get(key)

    def SetProperty(self, key, value):
        self.props[key] = value
        return True


class NullIdItemStub(ItemStub):
    """The thin object AppendToTimeline can return: the id is unreadable."""

    def GetUniqueId(self):
        return None


class TimelineStub:
    def __init__(self, items=None, locked=False):
        self.tracks = {("video", 1): list(items or [])}
        self.locked = locked

    def GetName(self):
        return "Sandbox"

    def GetUniqueId(self):
        return "timeline-1"

    def GetStartFrame(self):
        return TL_START

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, track_index):
        return sorted(
            self.tracks.get((track_type, track_index), []),
            key=lambda item: item.GetStart(),
        )

    def GetIsTrackLocked(self, track_type, track_index):
        return self.locked

    def DeleteClips(self, items, ripple):
        for item in items:
            for rows in self.tracks.values():
                if item in rows:
                    rows.remove(item)
        return True


class MediaPoolStub:
    def __init__(self, root, timeline, null_id_appends=False):
        self.root = root
        self.timeline = timeline
        self.null_id_appends = null_id_appends
        self.append_count = 0

    def GetRootFolder(self):
        return self.root

    def AppendToTimeline(self, infos):
        appended = []
        for info in infos:
            self.append_count += 1
            cls = NullIdItemStub if self.null_id_appends else ItemStub
            item = cls(
                None if self.null_id_appends else f"appended-{self.append_count}",
                info["mediaPoolItem"].GetName(),
                int(info["recordFrame"]),
                int(info["endFrame"]) - int(info["startFrame"]),
                info["mediaPoolItem"],
            )
            if not self.null_id_appends:
                track_type = "video" if int(info.get("mediaType", 1)) == 1 else "audio"
                self.timeline.tracks.setdefault((track_type, int(info["trackIndex"])), []).append(item)
            appended.append(item)
        return appended


class ProjectStub:
    def __init__(self, media_pool):
        self.media_pool = media_pool

    def GetMediaPool(self):
        return self.media_pool


def _three_item_timeline():
    source_mpi = MediaPoolItemStub("pool-src", "src.mov")
    items = [
        ItemStub(f"item-{i}", f"clip{i}", TL_START + i * 48, 48, source_mpi)
        for i in range(3)
    ]
    return items, source_mpi


def _ripple_fixture(insert_clip_id="pool-ins", locked=False, tail_props=None):
    items, source_mpi = _three_item_timeline()
    if tail_props:
        items[2].props.update(tail_props)
    insert_mpi = MediaPoolItemStub(insert_clip_id, "insert.mov")
    tl = TimelineStub(items, locked=locked)
    mp = MediaPoolStub(FolderStub([source_mpi, insert_mpi]), tl)
    proj = ProjectStub(mp)
    return proj, tl, mp, items


def _insert_params(**overrides):
    p = {
        "clip_infos": [
            {
                "clip_id": "pool-ins",
                "start_frame": 0,
                "end_frame": 24,
                "track_index": 1,
                "media_type": 1,
            }
        ],
        "record_frame": 48,
    }
    p.update(overrides)
    return p


class RippleInsertPlanTest(unittest.TestCase):
    def test_requires_clip_infos(self):
        proj, tl, _, _ = _ripple_fixture()
        out = s._timeline_ripple_insert_impl(proj, tl, {"record_frame": 48})
        self.assertEqual(out["error"]["code"], "INVALID_CLIP_INFOS")

    def test_requires_record_point(self):
        proj, tl, _, _ = _ripple_fixture()
        out = s._timeline_ripple_insert_impl(
            proj, tl, {"clip_infos": _insert_params()["clip_infos"]}
        )
        self.assertEqual(out["error"]["code"], "MISSING_RECORD_POINT")

    def test_dry_run_plan_matches_live_evidence(self):
        proj, tl, _, _ = _ripple_fixture()
        out = s._timeline_ripple_insert_impl(proj, tl, _insert_params())
        self.assertTrue(out["success"])
        self.assertTrue(out["dry_run"])
        plan = out["plan"]
        self.assertEqual(plan["insert_frame_absolute"], TL_START + 48)
        self.assertEqual(plan["insert_frame_relative"], 48)
        self.assertEqual(plan["shift_frames"], 24)
        self.assertEqual(plan["head_item_count"], 1)
        self.assertEqual(plan["tail_item_count"], 2)
        self.assertEqual(plan["straddlers"], [])
        self.assertEqual(plan["blockers"], [])
        self.assertEqual(plan["locked_tracks_with_tail"], [])

    def test_mid_item_insert_point_is_refused(self):
        proj, tl, _, _ = _ripple_fixture()
        params = _insert_params(record_frame=60)
        out = s._timeline_ripple_insert_impl(proj, tl, params)
        self.assertFalse(out["success"])
        self.assertEqual(len(out["plan"]["straddlers"]), 1)
        self.assertTrue(out["plan"]["infeasible_reasons"])

        executed = s._timeline_ripple_insert_impl(
            proj, tl, dict(params, dry_run=False)
        )
        self.assertFalse(executed["success"])
        self.assertEqual(executed["error"]["code"], "RIPPLE_PLAN_BLOCKED")

    def test_locked_track_with_tail_is_refused(self):
        proj, tl, _, _ = _ripple_fixture(locked=True)
        out = s._timeline_ripple_insert_impl(proj, tl, _insert_params())
        self.assertFalse(out["success"])
        self.assertEqual(out["plan"]["locked_tracks_with_tail"], ["video:1"])

    def test_tail_without_pool_media_is_refused(self):
        proj, tl, _, items = _ripple_fixture()
        items[2].mpi = None
        out = s._timeline_ripple_insert_impl(proj, tl, _insert_params())
        self.assertFalse(out["success"])
        self.assertEqual(len(out["plan"]["blockers"]), 1)


class RippleInsertExecuteTest(unittest.TestCase):
    def setUp(self):
        s._CONFIRM_TOKENS.clear()

    def test_execute_requires_confirm_token(self):
        proj, tl, _, _ = _ripple_fixture()
        params = _insert_params(dry_run=False)
        with mock.patch.object(s, "_confirm_token_required", return_value=True):
            first = s._timeline_ripple_insert_impl(proj, tl, params)
            self.assertEqual(first["status"], "confirmation_required")
            self.assertEqual(first["preview"]["operation"], "timeline.ripple_insert")

            confirmed = s._timeline_ripple_insert_impl(
                proj, tl, dict(params, confirm_token=first["confirm_token"])
            )
        self.assertTrue(confirmed["success"])

    def test_execute_rebuilds_layout_and_restores_properties(self):
        proj, tl, _, _ = _ripple_fixture(tail_props={"ZoomX": 0.5, "ZoomY": 0.5})
        params = _insert_params(dry_run=False)
        with mock.patch.object(s, "_confirm_token_required", return_value=False):
            out = s._timeline_ripple_insert_impl(proj, tl, params)

        self.assertTrue(out["success"])
        self.assertEqual(out["shift_frames"], 24)
        self.assertEqual(out["tail_items_shifted"], 2)
        self.assertEqual(out["readback"]["missing"], [])
        layout = [
            (item.GetStart(), item.GetDuration())
            for item in tl.GetItemListInTrack("video", 1)
        ]
        self.assertEqual(
            layout,
            [(86400, 48), (86448, 24), (86472, 48), (86520, 48)],
        )
        self.assertEqual(out["properties_restored_items"], 1)
        self.assertEqual(out["property_restore_failures"], 0)
        shifted_tail = tl.GetItemListInTrack("video", 1)[-1]
        self.assertEqual(shifted_tail.GetProperty("ZoomX"), 0.5)


class DuplicateVerifiedGateTest(unittest.TestCase):
    """AppendToTimeline null-id items must never count as verified duplicates."""

    def _run_append(self, null_id_appends):
        items, source_mpi = _three_item_timeline()
        tl = TimelineStub(items)
        mp = MediaPoolStub(FolderStub([source_mpi]), tl, null_id_appends=null_id_appends)
        result, duplicate_item, err = s._append_and_recover_timeline_item(
            mp,
            tl,
            items[0],
            track_type="video",
            dest_track=1,
            record_frame=TL_START + 10,
            copy_properties=[],
            source_timeline_item_id="item-0",
        )
        self.assertIsNone(err)
        return result, duplicate_item

    def test_verified_duplicate_is_marked_verified(self):
        result, duplicate_item = self._run_append(null_id_appends=False)
        self.assertTrue(result["duplicate_verified"])
        self.assertIsNotNone(duplicate_item)

    def test_null_id_duplicate_is_not_verified(self):
        result, duplicate_item = self._run_append(null_id_appends=True)
        self.assertFalse(result["duplicate_verified"])
        self.assertIsNone(duplicate_item)
        self.assertTrue(
            any("could not be verified" in w for w in result.get("warnings", []))
        )


class PlanOnlyIsNotArchivedTest(unittest.TestCase):
    """ripple_insert is the only destructive action that DEFAULTS to a plan-only
    call, so without a dry-run filter every routine planning call archives a
    timeline version. The F4 pending-confirm skip does not cover it: that path
    short-circuits when the confirm-token preference is OFF."""

    def test_a_dry_run_plan_is_not_treated_as_destructive(self):
        p = {"dry_run": True, "clip_infos": [{"clip_id": "x"}], "record_frame": 48}
        self.assertFalse(destructive_hook.is_destructive("timeline", "ripple_insert", p))

    def test_no_params_defaults_to_plan_only(self):
        self.assertFalse(destructive_hook.is_destructive("timeline", "ripple_insert", None))

    def test_an_executing_call_is_still_destructive(self):
        p = {"dry_run": False, "clip_infos": [{"clip_id": "x"}], "record_frame": 48}
        self.assertTrue(destructive_hook.is_destructive("timeline", "ripple_insert", p))


class GapReportingTest(unittest.TestCase):
    """Every track shifts by the longest inserted run, so a track with a shorter
    insert - or none - is left with a gap. The readback cannot see it: it only
    checks the positions the action placed. Reporting success over a timeline
    with black in it is the wrong answer, so the plan names the gaps."""

    class _AVTimeline(TimelineStub):
        def __init__(self, video, audio):
            self.tracks = {("video", 1): list(video), ("audio", 1): list(audio)}
            self.locked = False

        def GetTrackCount(self, track_type):
            return 1 if track_type in ("video", "audio") else 0

    def _fixture(self):
        source = MediaPoolItemStub("pool-src", "src.mov")
        insert = MediaPoolItemStub("pool-ins", "insert.mov")
        video = [ItemStub(f"v{i}", f"v{i}", TL_START + i * 48, 48, source) for i in range(2)]
        audio = [ItemStub(f"a{i}", f"a{i}", TL_START + i * 48, 48, source) for i in range(2)]
        tl = self._AVTimeline(video, audio)
        mp = MediaPoolStub(FolderStub([source, insert]), tl)
        return ProjectStub(mp), tl

    def test_a_shorter_video_insert_reports_its_gap(self):
        proj, tl = self._fixture()
        params = {
            "clip_infos": [
                {"clip_id": "pool-ins", "start_frame": 0, "end_frame": 24,
                 "track_index": 1, "media_type": 1},
                {"clip_id": "pool-ins", "start_frame": 0, "end_frame": 48,
                 "track_index": 1, "media_type": 2},
            ],
            "record_frame": 48,
        }
        plan = s._timeline_ripple_insert_impl(proj, tl, params)["plan"]
        self.assertEqual(plan["shift_frames"], 48)
        self.assertEqual(plan["gap_frames_by_track"], {"video:1": 24})
        self.assertTrue(any("gap at the insert point" in w for w in plan["warnings"]))

    def test_matched_insert_lengths_report_no_gap(self):
        proj, tl = self._fixture()
        params = {
            "clip_infos": [
                {"clip_id": "pool-ins", "start_frame": 0, "end_frame": 24,
                 "track_index": 1, "media_type": 1},
                {"clip_id": "pool-ins", "start_frame": 0, "end_frame": 24,
                 "track_index": 1, "media_type": 2},
            ],
            "record_frame": 48,
        }
        plan = s._timeline_ripple_insert_impl(proj, tl, params)["plan"]
        self.assertEqual(plan["gap_frames_by_track"], {})


class SubtitleStraddlerTest(unittest.TestCase):
    """Video and audio straddlers already refuse the plan. A subtitle that
    straddles the insert point is the same problem - it stays put while the
    picture under it moves right - and was passing the feasibility check."""

    class _SubTimeline(TimelineStub):
        def __init__(self, video, subs):
            self.tracks = {("video", 1): list(video), ("subtitle", 1): list(subs)}
            self.locked = False

        def GetTrackCount(self, track_type):
            return 1 if track_type in ("video", "subtitle") else 0

    def _run(self, sub_start, sub_duration):
        source = MediaPoolItemStub("pool-src", "src.mov")
        insert = MediaPoolItemStub("pool-ins", "insert.mov")
        video = [ItemStub(f"v{i}", f"v{i}", TL_START + i * 48, 48, source) for i in range(3)]
        sub = ItemStub("sub1", "sub", sub_start, sub_duration, source)
        tl = self._SubTimeline(video, [sub])
        mp = MediaPoolStub(FolderStub([source, insert]), tl)
        return s._timeline_ripple_insert_impl(ProjectStub(mp), tl, _insert_params())

    def test_a_straddling_subtitle_blocks_the_plan(self):
        out = self._run(TL_START + 30, 40)          # 86430..86470 across 86448
        self.assertEqual(out["plan"]["subtitle_items_after_insert_point"], 1)
        self.assertFalse(out["success"])

    def test_a_subtitle_entirely_before_the_insert_point_does_not(self):
        out = self._run(TL_START, 24)               # 86400..86424, well clear
        self.assertEqual(out["plan"]["subtitle_items_after_insert_point"], 0)
        self.assertTrue(out["success"])


if __name__ == "__main__":
    unittest.main()
