"""Tests for the project journal and its rendered documents.

The append-only rule is the load-bearing one. A known-issues list that can be
tidied loses the thing it exists for — the issue nobody got round to, still
sitting there three weeks later when someone asks why a shot shipped soft.
"""

from __future__ import annotations

import tempfile
import unittest

from src.utils import project_journal as pj


class AppendOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()

    def test_records_accumulate_in_order(self) -> None:
        for i in range(3):
            pj.append(self.root, kind=pj.KIND_INGEST, summary=f"card {i}")
        records = pj.read(self.root)
        self.assertEqual([r["seq"] for r in records], [1, 2, 3])

    def test_an_empty_summary_is_refused(self) -> None:
        self.assertFalse(pj.append(self.root, kind="note", summary="  ")["success"])

    def test_reading_a_missing_journal_is_empty_not_an_error(self) -> None:
        self.assertEqual(pj.read(tempfile.mkdtemp()), [])

    def test_records_can_be_filtered_by_kind(self) -> None:
        pj.append(self.root, kind=pj.KIND_INGEST, summary="a")
        pj.append(self.root, kind=pj.KIND_ISSUE, summary="b")
        self.assertEqual(len(pj.read(self.root, kind=pj.KIND_ISSUE)), 1)

    def test_an_unknown_kind_is_recorded_not_rejected(self) -> None:
        """Refusing to record something is worse than an unfamiliar label."""
        self.assertTrue(pj.append(self.root, kind="weather", summary="rained")["success"])

    def test_a_corrupt_line_does_not_hide_the_rest(self) -> None:
        pj.append(self.root, kind="note", summary="good")
        with open(pj._journal_path(self.root), "a", encoding="utf-8") as handle:
            handle.write("{not json\n")
        pj.append(self.root, kind="note", summary="also good")
        kinds = [r["kind"] for r in pj.read(self.root)]
        self.assertIn("corrupt", kinds)
        self.assertEqual(kinds.count("note"), 2)


class KnownIssueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()
        pj.append(self.root, kind=pj.KIND_ISSUE, summary="VFX042 blacks lifted", ref="VFX042")
        pj.append(self.root, kind=pj.KIND_ISSUE, summary="reel names missing", ref="REELS")

    def test_unresolved_issues_stay_open(self) -> None:
        self.assertEqual(len(pj.open_issues(self.root)["open"]), 2)

    def test_a_resolution_closes_its_issue_without_deleting_it(self) -> None:
        pj.append(self.root, kind=pj.KIND_RESOLUTION, summary="re-delivered", ref="VFX042")
        state = pj.open_issues(self.root)
        self.assertEqual(len(state["open"]), 1)
        self.assertEqual(state["total_raised"], 2, "the issue itself must survive")
        self.assertEqual(len(pj.read(self.root, kind=pj.KIND_ISSUE)), 2)

    def test_the_note_explains_the_append_only_rule(self) -> None:
        self.assertIn("never deletes", pj.open_issues(self.root)["note"])


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()

    def test_an_empty_ingest_log_says_so(self) -> None:
        self.assertIn("No ingest recorded", pj.render_ingest_log(self.root))

    def test_the_ingest_log_lists_what_came_in(self) -> None:
        pj.append(self.root, kind=pj.KIND_INGEST, summary="A001 card",
                  detail="128 clips, checksums verified")
        text = pj.render_ingest_log(self.root)
        self.assertIn("A001 card", text)
        self.assertIn("checksums verified", text)

    def test_known_issues_carry_into_session_prep(self) -> None:
        pj.append(self.root, kind=pj.KIND_ISSUE, summary="shot 12 is soft", ref="S12")
        self.assertIn("shot 12 is soft", pj.render_session_prep(self.root))

    def test_session_prep_states_what_the_prep_was_worth(self) -> None:
        text = pj.render_session_prep(
            self.root, prep_hours=4, estimated_hours_saved=6, hourly_rate=400
        )
        self.assertIn("4h", text)
        self.assertIn("2,400", text)
        self.assertIn("Estimates, stated as such", text)

    def test_a_missing_handoff_field_prints_as_not_stated(self) -> None:
        """Silently omitting the frame rate makes the handoff read as complete."""
        text = pj.render_handoff(project="EP01", to="Finishing",
                                 technical={"resolution": "3840x2160"})
        self.assertIn("**NOT STATED**", text)
        self.assertIn("frame rate", text)
        self.assertIn("3840x2160", text)

    def test_extra_handoff_fields_are_kept(self) -> None:
        text = pj.render_handoff(project="EP01", to="Sound",
                                 technical={"sample_rate": "48kHz"})
        self.assertIn("sample rate", text)

    def test_status_reads_blocked_when_there_are_blockers(self) -> None:
        self.assertIn("BLOCKED", pj.render_status(
            project="EP01", phase="colour", blockers=["VFX late"]))

    def test_status_reads_on_track_when_there_are_none(self) -> None:
        text = pj.render_status(project="EP01", phase="colour", percent_complete=60)
        self.assertIn("ON TRACK", text)
        self.assertIn("60% complete", text)


def tl_item(start, end):
    return {"timeline_start_frame": start, "timeline_end_frame": end}


class PictureLockTests(unittest.TestCase):
    CUT = [tl_item(0, 100), tl_item(100, 250), tl_item(250, 400)]

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()

    def test_an_unlocked_timeline_says_so_without_erroring(self) -> None:
        out = pj.check_picture_lock(self.root, timeline_name="EP01", items=self.CUT)
        self.assertFalse(out["locked"])
        self.assertIn("no picture lock recorded", out["note"])

    def test_an_unchanged_cut_matches_its_lock(self) -> None:
        pj.set_picture_lock(self.root, timeline_name="EP01", items=self.CUT)
        out = pj.check_picture_lock(self.root, timeline_name="EP01", items=self.CUT)
        self.assertTrue(out["locked"])
        self.assertFalse(out["drifted"])
        self.assertIn("has not moved", out["note"])

    def test_an_inserted_shot_trips_the_lock(self) -> None:
        pj.set_picture_lock(self.root, timeline_name="EP01", items=self.CUT)
        recut = self.CUT + [tl_item(400, 500)]
        out = pj.check_picture_lock(self.root, timeline_name="EP01", items=recut)
        self.assertTrue(out["drifted"])
        self.assertIn("expensive kind", out["note"])

    def test_a_retime_trips_the_lock_even_at_the_same_shot_count(self) -> None:
        pj.set_picture_lock(self.root, timeline_name="EP01", items=self.CUT)
        recut = [tl_item(0, 100), tl_item(100, 300), tl_item(300, 400)]
        self.assertTrue(
            pj.check_picture_lock(self.root, timeline_name="EP01", items=recut)["drifted"]
        )

    def test_the_lock_is_per_timeline(self) -> None:
        pj.set_picture_lock(self.root, timeline_name="EP01", items=self.CUT)
        self.assertFalse(
            pj.check_picture_lock(self.root, timeline_name="EP02", items=self.CUT)["locked"]
        )

    def test_relocking_uses_the_most_recent_lock(self) -> None:
        pj.set_picture_lock(self.root, timeline_name="EP01", items=self.CUT)
        recut = self.CUT + [tl_item(400, 500)]
        pj.set_picture_lock(self.root, timeline_name="EP01", items=recut)
        self.assertFalse(
            pj.check_picture_lock(self.root, timeline_name="EP01", items=recut)["drifted"]
        )

    def test_both_locks_survive_in_the_journal(self) -> None:
        """Append-only: the first lock is history, not a mistake to erase."""
        pj.set_picture_lock(self.root, timeline_name="EP01", items=self.CUT)
        pj.set_picture_lock(self.root, timeline_name="EP01", items=self.CUT)
        self.assertEqual(len(pj.read(self.root, kind=pj.KIND_PICTURE_LOCK)), 2)


if __name__ == "__main__":
    unittest.main()
