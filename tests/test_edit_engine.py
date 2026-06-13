"""Unit tests for src/utils/edit_engine.py (Phase E — planning layer).

No Resolve required: the planning layer is DB-only by design. Execution
paths (timeline creation, lifts, swaps) are validated live on a disposable
synthetic-media project per the release process.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from src.utils import analysis_store, edit_engine, embeddings, timeline_brain_db

from tests.test_analysis_store import make_report


def deep_shot(index: int, start: float, end: float, select: str, description: str) -> dict:
    return {
        "shot_index": index,
        "time_seconds_start": start,
        "time_seconds_end": end,
        "frame_indices_used": [index],
        "description": description,
        "qc_flags": [],
        "editorial": {
            "select_potential": select,
            "editorial_role": "coverage",
            "best_moment": {"time_seconds": (start + end) / 2, "why": "clear action beat"} if select == "high" else None,
            "best_moment_present": select == "high",
            "pacing": "moderate",
        },
    }


class EditEngineBase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="edit-engine-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)

    def _ingest_deep_clip(self, *, clip_id: str, name: str, path: str, clip_dir: str, shots: list) -> str:
        report = make_report()
        report["clip"] = dict(report["clip"], clip_id=clip_id, clip_name=name, file_path=path,
                              media_id=clip_id + "-m")
        report["visual"]["shot_descriptions"] = shots
        result = analysis_store.ingest_report(self.root, report, clip_dir=clip_dir)
        self.assertTrue(result["success"], result)
        return result["clip_uuid"]


class PlanSelectsTests(EditEngineBase):
    def setUp(self) -> None:
        super().setUp()
        self.clip1 = self._ingest_deep_clip(
            clip_id="resolve-clip-1", name="A Clip.mp4", path="/media/a.mp4", clip_dir="a-aaaaaaaaaaaa",
            shots=[
                deep_shot(1, 0.0, 5.0, "high", "Opening action."),
                deep_shot(2, 5.0, 10.0, "low", "Dead beat."),
                deep_shot(3, 10.0, 16.0, "high", "Payoff."),
            ],
        )
        self.clip2 = self._ingest_deep_clip(
            clip_id="resolve-clip-2", name="B Clip.mp4", path="/media/b.mp4", clip_dir="b-bbbbbbbbbbbb",
            shots=[deep_shot(1, 0.0, 8.0, "medium", "Establishing coverage.")],
        )

    def test_plan_ranks_and_orders_story_spine(self) -> None:
        plan = edit_engine.plan_selects(self.root, min_select_potential="high")
        self.assertTrue(plan["success"], plan)
        self.assertEqual(plan["decision_count"], 2)
        # Story-spine order: clip A shot 1 then shot 3.
        self.assertEqual([d["shot_index"] for d in plan["decisions"]], [1, 3])
        first = plan["decisions"][0]
        self.assertIn("select_potential=high", first["rationale"])
        self.assertIn("best_moment", first["rationale"])
        self.assertEqual(first["source_frame_range"][0], 0)

    def test_medium_threshold_includes_second_clip(self) -> None:
        plan = edit_engine.plan_selects(self.root, min_select_potential="medium")
        self.assertEqual(plan["decision_count"], 3)
        names = [d["clip_name"] for d in plan["decisions"]]
        self.assertIn("B Clip.mp4", names)

    def test_duration_budget_prefers_high_rank(self) -> None:
        plan = edit_engine.plan_selects(self.root, min_select_potential="medium", max_duration_seconds=12.0)
        self.assertTrue(plan["success"])
        self.assertLessEqual(plan["estimated_duration_seconds"], 12.5)
        for decision in plan["decisions"]:
            self.assertEqual(decision["rank"], 3)

    def test_clip_level_fallback_when_no_deep_fields(self) -> None:
        root2 = tempfile.mkdtemp(prefix="edit-engine-fallback-")
        self.addCleanup(shutil.rmtree, root2, True)
        report = make_report()  # standard shots, no editorial groups
        analysis_store.ingest_report(root2, report, clip_dir="std-cccccccccccc")
        plan = edit_engine.plan_selects(root2, min_select_potential="medium")
        self.assertTrue(plan["success"], plan)
        self.assertTrue(all("clip-level select_potential" in d["rationale"] for d in plan["decisions"]))

    def test_plan_persisted_and_fingerprinted(self) -> None:
        plan = edit_engine.plan_selects(self.root, min_select_potential="high")
        loaded = edit_engine.load_plan(self.root, plan["plan_id"])
        self.assertEqual(loaded["kind"], "selects")
        self.assertEqual(len(loaded["clip_infos"]), 2)
        # Tamper → fingerprint check fails.
        path = os.path.join(edit_engine._plan_dir(self.root), f"{plan['plan_id']}.json")
        with open(path, "r+", encoding="utf-8") as handle:
            data = json.load(handle)
            data["clip_infos"][0]["start_frame"] = 9999
            handle.seek(0)
            json.dump(data, handle)
            handle.truncate()
        tampered = edit_engine.load_plan(self.root, plan["plan_id"])
        self.assertTrue(tampered["_corrupt"])

    def test_mark_plan_executed(self) -> None:
        plan = edit_engine.plan_selects(self.root, min_select_potential="high")
        edit_engine.mark_plan_executed(self.root, plan["plan_id"], {"timeline_name": "Selects X"})
        loaded = edit_engine.load_plan(self.root, plan["plan_id"])
        self.assertIsNotNone(loaded.get("executed_at"))
        rows = edit_engine.list_plans(self.root)
        self.assertEqual(rows["plans"][0]["plan_id"], plan["plan_id"])


class PlanTightenTests(EditEngineBase):
    def setUp(self) -> None:
        super().setUp()
        # make_report transcript: speech 0-4s and 4-9.5s; clip is 20s, so
        # 9.5-20s is dead air.
        self.clip = self._ingest_deep_clip(
            clip_id="resolve-clip-t", name="Talk.mp4", path="/media/talk.mp4", clip_dir="t-tttttttttttt",
            shots=[deep_shot(1, 0.0, 20.0, "medium", "Single take.")],
        )

    def _item(self, **overrides) -> dict:
        item = {
            "timeline_start_frame": 0,
            "timeline_end_frame": 480,   # 20s at 24fps
            "source_start_frame": 0,
            "media_ref": "resolve-clip-t",
            "item_name": "Talk.mp4",
            "track_index": 1,
        }
        item.update(overrides)
        return item

    def test_dead_air_lift_proposed(self) -> None:
        plan = edit_engine.plan_tighten(
            self.root, items=[self._item()], timeline_name="TL", timeline_fps=24.0
        )
        self.assertTrue(plan["success"], plan)
        self.assertEqual(plan["lift_count"], 1)
        lift = plan["lifts"][0]
        # Gap 9.5→20s with 0.25s handles → 9.75→19.75 → frames 234→474.
        self.assertEqual(lift["timeline_start_frame"], 234)
        self.assertEqual(lift["timeline_end_frame"], 474)
        self.assertIn("No speech", lift["rationale"])
        self.assertEqual(lift["evidence"]["basis"], "transcript_segments")

    def test_item_offset_maps_to_timeline_frames(self) -> None:
        # Item shows source 8s..20s at timeline 1000..1288 (24fps).
        plan = edit_engine.plan_tighten(
            self.root,
            items=[self._item(timeline_start_frame=1000, timeline_end_frame=1288,
                              source_start_frame=192)],
            timeline_name="TL", timeline_fps=24.0,
        )
        lift = plan["lifts"][0]
        # Source gap 9.5→20 clipped to item range 8..20, handles → 9.75..19.75
        # → timeline 1000 + (9.75-8)*24 = 1042 ; end 1000 + (19.75-8)*24 = 1282.
        self.assertEqual(lift["timeline_start_frame"], 1042)
        self.assertEqual(lift["timeline_end_frame"], 1282)

    def test_target_ratio_limits_lifts(self) -> None:
        plan = edit_engine.plan_tighten(
            self.root, items=[self._item()], timeline_name="TL", timeline_fps=24.0,
            target_ratio=0.1,
        )
        # One big lift is more than 10% — still chosen (first lift crosses target).
        self.assertEqual(plan["lift_count"], 1)

    def test_unanalyzed_media_skipped_with_reason(self) -> None:
        plan = edit_engine.plan_tighten(
            self.root,
            items=[self._item(), self._item(media_ref="unknown-clip", item_name="Mystery.mp4")],
            timeline_name="TL", timeline_fps=24.0,
        )
        self.assertTrue(plan["success"])
        self.assertEqual(len(plan["skipped"]), 1)
        self.assertIn("no analysis", plan["skipped"][0]["reason"])

    def test_lifts_ordered_latest_first(self) -> None:
        # Two items, each with a dead-air tail.
        items = [
            self._item(),
            self._item(timeline_start_frame=480, timeline_end_frame=960),
        ]
        plan = edit_engine.plan_tighten(self.root, items=items, timeline_name="TL", timeline_fps=24.0)
        starts = [l["timeline_start_frame"] for l in plan["lifts"]]
        self.assertEqual(starts, sorted(starts, reverse=True))

    def test_keep_ranges_mirror_audio_by_default(self) -> None:
        # Regression for #67: a speech-driven tighten must carry audio, not
        # assemble a silent video-only variant.
        plan = edit_engine.plan_tighten(
            self.root, items=[self._item()], timeline_name="TL", timeline_fps=24.0
        )
        loaded = edit_engine.load_plan(self.root, plan["plan_id"])
        keep = loaded["keep_ranges"]
        video = [r for r in keep if r["track_type"] == "video"]
        audio = [r for r in keep if r["track_type"] == "audio"]
        self.assertTrue(video)
        self.assertEqual(len(audio), len(video))  # one mirror per kept video range
        self.assertEqual(plan["audio_keep_range_count"], len(audio))
        self.assertEqual(plan["video_keep_range_count"], len(video))
        self.assertTrue(plan["include_audio"])
        # Each audio range is frame-locked to its video twin (same source frames,
        # same clip), on audio track 1, mediaType 2.
        for v, a in zip(video, audio):
            self.assertEqual(a["start_frame"], v["start_frame"])
            self.assertEqual(a["end_frame"], v["end_frame"])
            self.assertEqual(a["clip_id"], v["clip_id"])
            self.assertEqual(a["track_index"], 1)
            self.assertEqual(a["media_type"], 2)

    def test_audio_mirrors_detected_linked_tracks(self) -> None:
        # When the server reports the item's linked audio track indices, mirror
        # onto each of them.
        plan = edit_engine.plan_tighten(
            self.root,
            items=[self._item(audio_track_indices=[1, 2])],
            timeline_name="TL", timeline_fps=24.0,
        )
        loaded = edit_engine.load_plan(self.root, plan["plan_id"])
        audio = [r for r in loaded["keep_ranges"] if r["track_type"] == "audio"]
        video = [r for r in loaded["keep_ranges"] if r["track_type"] == "video"]
        self.assertEqual(len(audio), 2 * len(video))
        self.assertEqual({r["track_index"] for r in audio}, {1, 2})

    def test_include_audio_false_is_video_only(self) -> None:
        plan = edit_engine.plan_tighten(
            self.root, items=[self._item()], timeline_name="TL", timeline_fps=24.0,
            include_audio=False,
        )
        loaded = edit_engine.load_plan(self.root, plan["plan_id"])
        self.assertFalse(any(r["track_type"] == "audio" for r in loaded["keep_ranges"]))
        self.assertEqual(plan["audio_keep_range_count"], 0)
        self.assertFalse(plan["include_audio"])


class PlanSwapTests(EditEngineBase):
    def setUp(self) -> None:
        super().setUp()
        self.clip1 = self._ingest_deep_clip(
            clip_id="resolve-swap-1", name="Main.mp4", path="/media/main.mp4", clip_dir="m-mmmmmmmmmmmm",
            shots=[deep_shot(1, 0.0, 10.0, "medium", "Current shot."),
                   deep_shot(2, 10.0, 20.0, "medium", "Tail shot.")],
        )
        self.clip2 = self._ingest_deep_clip(
            clip_id="resolve-swap-2", name="Alt.mp4", path="/media/alt.mp4", clip_dir="x-xxxxxxxxxxxx",
            shots=[deep_shot(1, 0.0, 12.0, "high", "Long alternate."),
                   deep_shot(2, 12.0, 13.0, "high", "Too-short alternate.")],
        )
        conn = timeline_brain_db.connect(self.root)
        shot_rows = conn.execute("SELECT shot_uuid, clip_uuid, shot_index FROM shots").fetchall()
        vectors = {
            (self.clip1, 1): [1.0, 0.0, 0.0],
            (self.clip1, 2): [0.0, 1.0, 0.0],
            (self.clip2, 1): [0.95, 0.05, 0.0],   # similar to clip1 shot1
            (self.clip2, 2): [0.9, 0.1, 0.0],     # similar but too short
        }
        with timeline_brain_db.transaction(self.root) as txn:
            for row in shot_rows:
                vec = vectors.get((str(row["clip_uuid"]), int(row["shot_index"])))
                if not vec:
                    continue
                txn.execute(
                    """
                    INSERT OR REPLACE INTO embeddings
                        (entity_type, entity_uuid, embedding_kind, model_name, dimension,
                         vector, content_hash, computed_at)
                    VALUES ('shot', ?, 'visual', 'fake:clip', ?, ?, 'h', '2026-06-10T00:00:00Z')
                    """,
                    (str(row["shot_uuid"]), len(vec), embeddings.pack_vector(vec)),
                )

    def test_swap_plan_ranks_viable_alternates(self) -> None:
        item = {
            "timeline_start_frame": 0,
            "timeline_end_frame": 240,   # 10s slot at 24fps
            "source_start_frame": 0,
            "media_ref": "resolve-swap-1",
            "item_name": "Main.mp4",
            "track_index": 1,
        }
        plan = edit_engine.plan_swap(self.root, item=item, timeline_name="TL", timeline_fps=24.0)
        self.assertTrue(plan["success"], plan)
        self.assertEqual(plan["current_shot"]["shot_index"], 1)
        alts = plan["alternates"]
        self.assertTrue(alts)
        # Too-short alternate (1s shot can't fill a 10s slot) is excluded.
        self.assertTrue(all(a["clip_name"] != "Alt.mp4" or a["shot_index"] != 2 for a in alts))
        best = alts[0]
        self.assertEqual(best["clip_name"], "Alt.mp4")
        # Replacement fills the slot exactly: 10s at 24fps = 240 frames.
        frame_range = best["source_frame_range"]
        self.assertEqual(frame_range[1] - frame_range[0] + 1, 240)

    def test_swap_requires_analysis(self) -> None:
        item = {
            "timeline_start_frame": 0, "timeline_end_frame": 240,
            "source_start_frame": 0, "media_ref": "nope",
        }
        plan = edit_engine.plan_swap(self.root, item=item, timeline_name="TL", timeline_fps=24.0)
        self.assertFalse(plan["success"])

    def _insert_alt_take_row(self, shot_uuid_a: str, shot_uuid_b: str) -> None:
        with timeline_brain_db.transaction(self.root) as txn:
            txn.execute(
                """
                INSERT INTO shot_relationships
                    (source_shot_uuid, target_shot_uuid, relationship_type,
                     confidence, source, author, timestamp, superseded_at)
                VALUES (?, ?, 'alt_take_of', 'high', 'vision_relationship_v1',
                        'host_chat', '2026-06-12T00:00:00Z', NULL)
                """,
                (shot_uuid_a, shot_uuid_b),
            )

    def test_swap_prefers_confirmed_alt_takes(self) -> None:
        # A third clip whose cosine is LOWER than Alt.mp4's — but it's a
        # vision-confirmed alt take, so it must outrank raw similarity.
        clip3 = self._ingest_deep_clip(
            clip_id="resolve-swap-3", name="Take2.mp4", path="/media/take2.mp4",
            clip_dir="t-tttttttttttt",
            shots=[deep_shot(1, 0.0, 11.0, "medium", "Confirmed alternate take.")],
        )
        conn = timeline_brain_db.connect(self.root)
        take_uuid = conn.execute(
            "SELECT shot_uuid FROM shots WHERE clip_uuid = ? AND shot_index = 1", (clip3,)
        ).fetchone()["shot_uuid"]
        current_uuid = conn.execute(
            "SELECT shot_uuid FROM shots WHERE clip_uuid = ? AND shot_index = 1", (self.clip1,)
        ).fetchone()["shot_uuid"]
        with timeline_brain_db.transaction(self.root) as txn:
            txn.execute(
                """
                INSERT OR REPLACE INTO embeddings
                    (entity_type, entity_uuid, embedding_kind, model_name, dimension,
                     vector, content_hash, computed_at)
                VALUES ('shot', ?, 'visual', 'fake:clip', 3, ?, 'h', '2026-06-10T00:00:00Z')
                """,
                (str(take_uuid), embeddings.pack_vector([0.7, 0.3, 0.0])),
            )
        self._insert_alt_take_row(str(current_uuid), str(take_uuid))
        item = {
            "timeline_start_frame": 0, "timeline_end_frame": 240,
            "source_start_frame": 0, "media_ref": "resolve-swap-1",
            "item_name": "Main.mp4", "track_index": 1,
        }
        plan = edit_engine.plan_swap(self.root, item=item, timeline_name="TL", timeline_fps=24.0)
        self.assertTrue(plan["success"], plan)
        best = plan["alternates"][0]
        self.assertEqual(best["clip_name"], "Take2.mp4")
        self.assertTrue(best["confirmed_alt_take"])
        self.assertIn("vision-confirmed alt_take_of", best["rationale"])

    def test_swap_unions_in_confirmed_alt_missing_from_cosine(self) -> None:
        # A confirmed alt take with NO embedding row can't come from the
        # cosine search — plan_swap must union it in with the basis stated.
        clip4 = self._ingest_deep_clip(
            clip_id="resolve-swap-4", name="Take3.mp4", path="/media/take3.mp4",
            clip_dir="u-uuuuuuuuuuuu",
            shots=[deep_shot(1, 0.0, 11.0, "medium", "Unembedded confirmed take.")],
        )
        conn = timeline_brain_db.connect(self.root)
        take_uuid = conn.execute(
            "SELECT shot_uuid FROM shots WHERE clip_uuid = ? AND shot_index = 1", (clip4,)
        ).fetchone()["shot_uuid"]
        current_uuid = conn.execute(
            "SELECT shot_uuid FROM shots WHERE clip_uuid = ? AND shot_index = 1", (self.clip1,)
        ).fetchone()["shot_uuid"]
        self._insert_alt_take_row(str(take_uuid), str(current_uuid))  # reversed direction
        item = {
            "timeline_start_frame": 0, "timeline_end_frame": 240,
            "source_start_frame": 0, "media_ref": "resolve-swap-1",
            "item_name": "Main.mp4", "track_index": 1,
        }
        plan = edit_engine.plan_swap(self.root, item=item, timeline_name="TL", timeline_fps=24.0)
        self.assertTrue(plan["success"], plan)
        best = plan["alternates"][0]
        self.assertEqual(best["clip_name"], "Take3.mp4")
        self.assertIsNone(best["score"])
        self.assertIn("not surfaced by the cosine search", best["rationale"])


class PanelPlanApiTests(EditEngineBase):
    """The /api/edit_plans surface: list + detail payloads for the panel
    plan browser (DB/file only — no Resolve)."""

    def setUp(self) -> None:
        super().setUp()
        self._ingest_deep_clip(
            clip_id="resolve-clip-1", name="A Clip.mp4", path="/media/a.mp4", clip_dir="a-aaaaaaaaaaaa",
            shots=[
                deep_shot(1, 0.0, 5.0, "high", "Opening action."),
                deep_shot(2, 5.0, 10.0, "low", "Dead beat."),
                deep_shot(3, 10.0, 16.0, "high", "Payoff."),
            ],
        )
        self.plan = edit_engine.plan_selects(self.root, min_select_potential="high")
        self.assertTrue(self.plan["success"], self.plan)

    def _tamper(self, plan_id: str) -> None:
        path = os.path.join(edit_engine._plan_dir(self.root), f"{plan_id}.json")
        with open(path, "r+", encoding="utf-8") as handle:
            data = json.load(handle)
            data["summary"] = "tampered"
            handle.seek(0)
            json.dump(data, handle)
            handle.truncate()

    def test_list_plans_hides_corrupt_by_default(self) -> None:
        self._tamper(self.plan["plan_id"])
        rows = edit_engine.list_plans(self.root)
        self.assertEqual(rows["plans"], [])

    def test_list_plans_include_corrupt_surfaces_warning_row(self) -> None:
        self._tamper(self.plan["plan_id"])
        rows = edit_engine.list_plans(self.root, include_corrupt=True)
        self.assertEqual(len(rows["plans"]), 1)
        self.assertTrue(rows["plans"][0]["corrupt"])
        self.assertEqual(rows["plans"][0]["plan_id"], self.plan["plan_id"])

    def test_panel_list_payload(self) -> None:
        from src import analysis_dashboard as dash
        payload = dash.list_edit_plans_payload(self.root)
        self.assertTrue(payload["success"], payload)
        self.assertEqual(len(payload["plans"]), 1)
        self.assertEqual(payload["plans"][0]["kind"], "selects")

    def test_panel_detail_enriches_decisions_for_thumbnails(self) -> None:
        from src import analysis_dashboard as dash
        payload = dash.get_edit_plan_payload(self.root, self.plan["plan_id"])
        self.assertTrue(payload["success"], payload)
        self.assertFalse(payload["corrupt"])
        decisions = payload["plan"]["decisions"]
        self.assertEqual(len(decisions), 2)
        for decision in decisions:
            self.assertTrue(decision["resolve_clip_id"])
        # make_report keyframes: index 1 @0.5s → shot 1, index 3 @14.0s → shot 3.
        by_shot = {d["shot_index"]: d for d in decisions}
        self.assertEqual(by_shot[1]["thumb_frame_index"], 1)
        self.assertEqual(by_shot[3]["thumb_frame_index"], 3)

    def test_panel_detail_corrupt_plan(self) -> None:
        from src import analysis_dashboard as dash
        self._tamper(self.plan["plan_id"])
        payload = dash.get_edit_plan_payload(self.root, self.plan["plan_id"])
        self.assertTrue(payload["success"])
        self.assertTrue(payload["corrupt"])

    def test_panel_detail_missing_plan(self) -> None:
        from src import analysis_dashboard as dash
        payload = dash.get_edit_plan_payload(self.root, "nope-nope")
        self.assertFalse(payload["success"])
        self.assertIn("not found", payload["error"])


class _FakeMpi:
    def __init__(self, uid: str) -> None:
        self._uid = uid

    def GetUniqueId(self) -> str:
        return self._uid


class _FakeItem:
    def __init__(self, start: int, end: int, *, uid: str = "", media_id: str = "",
                 linked: list | None = None, expose_linked: bool = True) -> None:
        self._start, self._end = start, end
        self._uid = uid or f"item-{media_id}-{start}"
        self._media_id = media_id
        self._linked = linked
        self._expose_linked = expose_linked

    def GetStart(self) -> int: return self._start
    def GetEnd(self) -> int: return self._end
    def GetUniqueId(self) -> str: return self._uid
    def GetMediaPoolItem(self): return _FakeMpi(self._media_id) if self._media_id else None

    def __getattr__(self, name):
        if name == "GetLinkedItems":
            if self._expose_linked and self._linked is not None:
                return lambda: self._linked
            raise AttributeError(name)
        raise AttributeError(name)


class _FakeTimeline:
    def __init__(self, tracks: dict) -> None:
        self._tracks = tracks  # {(type, index): [items]}

    def GetTrackCount(self, tt: str) -> int:
        return max((k[1] for k in self._tracks if k[0] == tt), default=0)

    def GetItemListInTrack(self, tt: str, ti: int):
        return self._tracks.get((tt, ti), [])


class SwapAudioAccountingHelperTests(unittest.TestCase):
    """The server-side helpers behind execute_swap's linked-audio lift."""

    def _tl(self, *, expose_linked: bool = True) -> tuple:
        audio1 = _FakeItem(0, 100, uid="au-1", media_id="m1")
        audio2 = _FakeItem(100, 200, uid="au-2", media_id="m2")
        video = _FakeItem(0, 100, media_id="m1", linked=[audio1],
                          expose_linked=expose_linked)
        tl = _FakeTimeline({
            ("video", 1): [video, _FakeItem(100, 200, media_id="m2", linked=[audio2])],
            ("audio", 1): [audio1, audio2],
            ("audio", 2): [_FakeItem(0, 300, uid="music", media_id="music")],
        })
        return tl, video

    def test_track_counts(self) -> None:
        from src.server import _edit_engine_track_counts
        tl, _ = self._tl()
        self.assertEqual(_edit_engine_track_counts(tl), {"video": 2, "audio": 3})

    def test_find_slot_item(self) -> None:
        from src.server import _edit_engine_find_slot_item
        tl, video = self._tl()
        self.assertIs(_edit_engine_find_slot_item(tl, 1, 0, 100), video)
        self.assertIsNone(_edit_engine_find_slot_item(tl, 1, 0, 99))

    def test_linked_audio_via_get_linked_items(self) -> None:
        from src.server import _edit_engine_linked_audio_tracks
        tl, video = self._tl()
        indices, note = _edit_engine_linked_audio_tracks(tl, video, 0, 100)
        # Only track 1 carries the linked item; the music bed on track 2
        # overlaps the slot but is NOT linked and must be left untouched.
        self.assertEqual(indices, [1])
        self.assertEqual(note, "")

    def test_linked_audio_media_id_fallback(self) -> None:
        from src.server import _edit_engine_linked_audio_tracks
        tl, video = self._tl(expose_linked=False)  # GetLinkedItems unavailable
        indices, note = _edit_engine_linked_audio_tracks(tl, video, 0, 100)
        self.assertEqual(indices, [1])
        self.assertEqual(note, "")

    def test_no_linked_audio_is_graceful(self) -> None:
        from src.server import _edit_engine_linked_audio_tracks
        solo_video = _FakeItem(0, 100, media_id="m-solo", linked=[])
        tl = _FakeTimeline({("video", 1): [solo_video]})  # audio-less timeline
        indices, note = _edit_engine_linked_audio_tracks(tl, solo_video, 0, 100)
        self.assertEqual(indices, [])
        self.assertIn("no linked audio", note)

    def test_missing_target_item_is_graceful(self) -> None:
        from src.server import _edit_engine_linked_audio_tracks
        tl, _ = self._tl()
        indices, note = _edit_engine_linked_audio_tracks(tl, None, 0, 100)
        self.assertEqual(indices, [])
        self.assertIn("not found", note)


if __name__ == "__main__":
    unittest.main()
