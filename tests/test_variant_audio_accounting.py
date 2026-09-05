"""`audio_accounting` must count what the VARIANT holds, not what the append returned.

Regression for the silence-ripple readback that reported 250 video / 250 audio
items on a variant that really held 432 of each. The counts were derived from
`MediaPool.AppendToTimeline`'s return value, and the in-app bridge caps any
proxied list at `max_items` — so an 864-clipInfo append came back as 500 items
and the accounting counted the short list as truth. `readback.after.clip_count`
was right the whole time because it re-reads the timeline per track.

A readback whose witness is the same call it is checking cannot contradict that
call. These tests pin the counts to a per-track re-read of the assembled
timeline, so a truncated (or reordered, or short) append return cannot make the
accounting lie again.

No Resolve required: the stubs place every clipInfo but hand back a deliberately
truncated list, which is exactly the shape the bridge produced.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest

from src import server as s
from src.utils import edit_engine, timeline_brain_db


# ── stubs ────────────────────────────────────────────────────────────────────


class MediaPoolItemStub:
    def __init__(self, unique_id: str) -> None:
        self._id = unique_id

    def GetUniqueId(self) -> str:
        return self._id

    def GetClipProperty(self, _key: str = ""):
        return {}


class TimelineItemStub:
    def __init__(self, uid: str, start: int, duration: int, mpi: MediaPoolItemStub) -> None:
        self._id = uid
        self._start = start
        self._duration = duration
        self._mpi = mpi

    def GetUniqueId(self) -> str:
        return self._id

    def GetName(self) -> str:
        return "clip.mov"

    def GetStart(self) -> int:
        return self._start

    def GetEnd(self) -> int:
        return self._start + self._duration

    def GetDuration(self) -> int:
        return self._duration

    def GetMediaPoolItem(self) -> MediaPoolItemStub:
        return self._mpi

    def SetProperty(self, _key, _value) -> bool:
        return True


class TimelineStub:
    """Holds items per (track_type, track_index) — the timeline's own truth."""

    def __init__(self, name: str, uid: str = "tl-1") -> None:
        self._name = name
        self._id = uid
        self.tracks = {"video": {1: []}, "audio": {1: []}, "subtitle": {}}

    # -- identity / timing -------------------------------------------------
    def GetName(self) -> str:
        return self._name

    def GetUniqueId(self) -> str:
        return self._id

    def GetStartFrame(self) -> int:
        return 0

    def GetEndFrame(self) -> int:
        video = self.tracks["video"].get(1) or []
        return video[-1].GetEnd() if video else 0

    def GetStartTimecode(self) -> str:
        return "01:00:00:00"

    def GetSetting(self, key: str):
        return "24.0" if key == "timelineFrameRate" else None

    # -- tracks ------------------------------------------------------------
    def GetTrackCount(self, track_type: str) -> int:
        return len(self.tracks.get(track_type) or {})

    def AddTrack(self, track_type: str) -> bool:
        table = self.tracks.setdefault(track_type, {})
        table[len(table) + 1] = []
        return True

    def GetItemListInTrack(self, track_type: str, track_index: int):
        return list((self.tracks.get(track_type) or {}).get(track_index) or [])

    def place(self, media_type: int, track_index: int, item: TimelineItemStub) -> None:
        track_type = "video" if media_type == 1 else "audio"
        self.tracks.setdefault(track_type, {}).setdefault(track_index, []).append(item)


class MediaPoolStub:
    """Places every clipInfo, but returns a TRUNCATED list — the bridge's shape.

    `return_cap` mirrors `resolve_bridge_ops.ResolveOperations.max_items`: the
    append genuinely lands every item, and only the *reply* is short.
    """

    def __init__(self, root_folder, timelines: list, *, return_cap: int) -> None:
        self._root = root_folder
        self._timelines = timelines
        self._return_cap = return_cap
        self.appended_count = 0

    def GetRootFolder(self):
        return self._root

    def CreateEmptyTimeline(self, name: str):
        timeline = TimelineStub(name, uid=f"tl-{len(self._timelines) + 1}")
        self._timelines.append(timeline)
        return timeline

    def AppendToTimeline(self, clip_infos):
        timeline = self._timelines[-1]
        placed = []
        for index, info in enumerate(clip_infos):
            media_type = int(info.get("mediaType") or 1)
            track_index = int(info.get("trackIndex") or 1)
            duration = int(info["endFrame"]) - int(info["startFrame"])
            item = TimelineItemStub(
                uid=f"item-{index}", start=int(info.get("recordFrame") or 0),
                duration=duration, mpi=info["mediaPoolItem"],
            )
            timeline.place(media_type, track_index, item)
            placed.append(item)
        self.appended_count = len(placed)
        # The bridge caps the encoded reply; the placements above are unaffected.
        return placed[: self._return_cap]


class RootFolderStub:
    def __init__(self, clips) -> None:
        self._clips = clips

    def GetClipList(self):
        return self._clips

    def GetSubFolderList(self):
        return []


class ProjectStub:
    def __init__(self, media_pool: MediaPoolStub, timelines: list) -> None:
        self._mp = media_pool
        self._timelines = timelines
        self.current = timelines[0] if timelines else None

    def GetMediaPool(self):
        return self._mp

    def GetTimelineCount(self) -> int:
        return len(self._timelines)

    def GetTimelineByIndex(self, index: int):
        try:
            return self._timelines[int(index) - 1]
        except (IndexError, ValueError):
            return None

    def SetCurrentTimeline(self, timeline) -> bool:
        self.current = timeline
        return True

    def GetName(self) -> str:
        return "Accounting Fixture"


def track_item_counts(timeline: TimelineStub) -> dict:
    """The timeline's own per-track truth — what the readback must agree with."""
    counts = {}
    for track_type in ("video", "audio"):
        total = 0
        for track_index in range(1, int(timeline.GetTrackCount(track_type) or 0) + 1):
            total += len(timeline.GetItemListInTrack(track_type, track_index) or [])
        counts[track_type] = total
    return counts


# ── fixture ──────────────────────────────────────────────────────────────────

#: Keep segments per source item. 432 video + 432 audio = 864 clipInfos, which
#: is what the reported run sent, and past the bridge's 500-element ceiling.
SEGMENTS = 432
BRIDGE_RETURN_CAP = 500


def silence_ripple_keep_ranges(clip_id: str = "mp-1") -> list:
    """Interleaved video/audio keep ranges — plan_silence_ripple's own shape."""
    ranges = []
    for index in range(SEGMENTS):
        start = index * 100
        end = start + 40
        ranges.append({"clip_id": clip_id, "start_frame": start, "end_frame": end,
                       "track_type": "video", "track_index": 1})
        ranges.append({"clip_id": clip_id, "start_frame": start, "end_frame": end,
                       "track_type": "audio", "media_type": 2, "track_index": 1})
    return ranges


def build_project(*, return_cap: int = BRIDGE_RETURN_CAP):
    source = TimelineStub("Interview Base", uid="tl-source")
    timelines = [source]
    media_pool = MediaPoolStub(
        RootFolderStub([MediaPoolItemStub("mp-1")]), timelines, return_cap=return_cap,
    )
    return ProjectStub(media_pool, timelines), source


class VariantAssemblyCountsTests(unittest.TestCase):
    """The assembler must report what it built, not what the append replied."""

    def test_placed_counts_survive_a_truncated_append_return(self) -> None:
        proj, source = build_project()
        result = s._timeline_create_variant_from_ranges(proj, source, {
            "name": "Interview Base — variant",
            "ranges": silence_ripple_keep_ranges(),
        })
        self.assertTrue(result.get("success"), result)
        variant = proj.GetTimelineByIndex(proj.GetTimelineCount())
        truth = track_item_counts(variant)
        self.assertEqual(truth, {"video": SEGMENTS, "audio": SEGMENTS})
        # The append reply really was short — the fixture is exercising the bug.
        self.assertEqual(len(result.get("items") or []), BRIDGE_RETURN_CAP)
        placed = result.get("placed_item_counts") or {}
        self.assertEqual({"video": placed.get("video"), "audio": placed.get("audio")}, truth)


class SilenceRippleAccountingTests(unittest.TestCase):
    """End-to-end through edit_engine('execute_silence_ripple')."""

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="variant-accounting-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)
        self.proj, self.source = build_project()
        # One seam: the action's project context. Everything below it is real.
        original = s._destructive_versioning_provider
        s._destructive_versioning_provider = lambda: (None, self.proj, self.root, "Fixture")
        self.addCleanup(setattr, s, "_destructive_versioning_provider", original)

    def _save_plan(self) -> dict:
        return edit_engine.save_plan(self.root, {
            "kind": "silence_ripple",
            "timeline_name": "Interview Base",
            "timeline_fps": 24.0,
            "lifts": [{"timeline_start_frame": 40, "timeline_end_frame": 100,
                       "duration_seconds": 2.5, "rationale": "silence"}],
            "keep_ranges": silence_ripple_keep_ranges(),
            "include_audio": True,
            "settings": {"include_audio": True},
        })

    def _execute(self, plan_id: str) -> dict:
        gate = s.edit_engine("execute_silence_ripple", {"plan_id": plan_id})
        params = {"plan_id": plan_id}
        if gate.get("confirm_token"):
            params["confirm_token"] = gate["confirm_token"]
        return s.edit_engine("execute_silence_ripple", params)

    def test_variant_item_counts_equal_the_timelines_own_per_track_counts(self) -> None:
        done = self._execute(self._save_plan()["plan_id"])
        self.assertTrue(done.get("success"), done)

        variant, _index = s._find_timeline_by_name(self.proj, done["variant_timeline"])
        self.assertIsNotNone(variant)
        truth = track_item_counts(variant)

        accounting = (done.get("readback") or {}).get("audio_accounting") or {}
        self.assertEqual(accounting.get("variant_video_items"), truth["video"], accounting)
        self.assertEqual(accounting.get("variant_audio_items"), truth["audio"], accounting)

    def test_accounting_agrees_with_the_plan_and_with_clip_count(self) -> None:
        done = self._execute(self._save_plan()["plan_id"])
        accounting = (done.get("readback") or {}).get("audio_accounting") or {}
        # The whole point of the block: planned vs placed must be comparable.
        self.assertEqual(accounting.get("variant_video_items"),
                         accounting.get("planned_video_ranges"), accounting)
        self.assertEqual(accounting.get("variant_audio_items"),
                         accounting.get("planned_audio_ranges"), accounting)
        # And it must not contradict the readback's own clip_count, which is
        # what made the old numbers look like 182 dropped ranges.
        after = (done.get("readback") or {}).get("after") or {}
        self.assertEqual(
            accounting["variant_video_items"] + accounting["variant_audio_items"],
            int(after["clip_count"]),
        )


if __name__ == "__main__":
    unittest.main()
