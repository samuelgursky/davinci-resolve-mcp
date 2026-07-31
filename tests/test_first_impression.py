"""Tests for the first-impression log and the setup sheet.

For the log, the lock is the entire feature. An editable first impression is
worthless, and the failure mode is not malice — it is the natural act of
revising a note that "no longer seems right", at exactly the moment the note is
most valuable, because what changed is the reader and not the film.
"""

from __future__ import annotations

import tempfile
import unittest

from src.utils import first_impression as fi
from src.utils import setup_sheet as ss


class LogLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()

    def _open(self, log_id="pass1"):
        return fi.start_pass(self.root, timeline_name="EP01", log_id=log_id)

    def test_a_log_can_be_opened_and_written_to(self) -> None:
        self.assertTrue(self._open()["success"])
        out = fi.record(self.root, log_id="pass1", time_seconds=12.0, text="opening drags")
        self.assertTrue(out["success"])
        self.assertEqual(out["entry_count"], 1)

    def test_entries_are_kept_in_time_order_however_they_arrive(self) -> None:
        self._open()
        for t in (30.0, 5.0, 18.0):
            fi.record(self.root, log_id="pass1", time_seconds=t, text=f"note at {t}")
        times = [e["time_seconds"] for e in fi.load(self.root, log_id="pass1")["entries"]]
        self.assertEqual(times, sorted(times))

    def test_an_empty_reaction_is_refused(self) -> None:
        self._open()
        self.assertFalse(
            fi.record(self.root, log_id="pass1", time_seconds=1.0, text="   ")["success"]
        )

    def test_starting_a_second_log_with_the_same_name_is_refused(self) -> None:
        """A first impression happens once."""
        self._open()
        again = self._open()
        self.assertFalse(again["success"])
        self.assertIn("happens once", again["remediation"])

    def test_recording_to_a_missing_log_fails_cleanly(self) -> None:
        self.assertFalse(
            fi.record(self.root, log_id="nope", time_seconds=1.0, text="x")["success"]
        )


class LockTests(unittest.TestCase):
    """The lock is the feature, so it gets the most tests."""

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()
        fi.start_pass(self.root, timeline_name="EP01", log_id="pass1")
        fi.record(self.root, log_id="pass1", time_seconds=12.0, text="opening drags")

    def test_a_locked_log_refuses_new_entries(self) -> None:
        fi.lock(self.root, log_id="pass1")
        with self.assertRaises(fi.LogLocked):
            fi.record(self.root, log_id="pass1", time_seconds=20.0, text="revised opinion")

    def test_the_refusal_explains_why_rather_than_just_erroring(self) -> None:
        fi.lock(self.root, log_id="pass1")
        with self.assertRaises(fi.LogLocked) as ctx:
            fi.record(self.root, log_id="pass1", time_seconds=20.0, text="x")
        self.assertIn("the viewer, not the film", str(ctx.exception))

    def test_there_is_no_unlock_function(self) -> None:
        """Irreversible by design. An escape hatch would be used."""
        self.assertFalse(hasattr(fi, "unlock"))

    def test_locking_twice_is_harmless(self) -> None:
        fi.lock(self.root, log_id="pass1")
        self.assertTrue(fi.lock(self.root, log_id="pass1")["already_locked"])

    def test_a_locked_log_survives_reloading(self) -> None:
        fi.lock(self.root, log_id="pass1")
        self.assertTrue(fi.load(self.root, log_id="pass1")["locked"])

    def test_listing_shows_lock_state(self) -> None:
        fi.lock(self.root, log_id="pass1")
        self.assertTrue(fi.list_logs(self.root)[0]["locked"])


class DiffTests(unittest.TestCase):
    FIRST = {"log_id": "pass1", "entries": [
        {"time_seconds": 10.0, "text": "opening drags"},
        {"time_seconds": 90.0, "text": "lost me here"},
    ]}
    LATER = {"log_id": "pass2", "entries": [
        {"time_seconds": 12.0, "text": "still slow but better"},
        {"time_seconds": 300.0, "text": "new problem in act three"},
    ]}

    def test_a_nearby_later_note_counts_as_revisited(self) -> None:
        out = fi.diff(self.FIRST, self.LATER)
        self.assertEqual(len(out["revisited"]), 1)
        self.assertIn("still slow but better", out["revisited"][0]["later_notes"])

    def test_an_unmatched_first_reaction_is_not_revisited(self) -> None:
        out = fi.diff(self.FIRST, self.LATER)
        self.assertEqual(len(out["not_revisited"]), 1)
        self.assertEqual(out["not_revisited"][0]["text"], "lost me here")

    def test_it_refuses_to_claim_anything_was_fixed(self) -> None:
        """Not revisited could mean solved, or could mean it stopped being
        visible once the film became familiar. That is the whole point."""
        note = fi.diff(self.FIRST, self.LATER)["note"]
        self.assertIn("does NOT mean not fixed", note)

    def test_new_concerns_in_the_later_pass_are_surfaced(self) -> None:
        out = fi.diff(self.FIRST, self.LATER)
        self.assertEqual(len(out["new_in_later_pass"]), 1)


class NoAnalysisTests(unittest.TestCase):
    def test_reaction_text_is_stored_verbatim(self) -> None:
        """No schema, no sentiment scoring — the words are the artifact."""
        root = tempfile.mkdtemp()
        fi.start_pass(root, timeline_name="EP01", log_id="p")
        text = "confused — who is this?? (and why now)"
        fi.record(root, log_id="p", time_seconds=1.0, text=text)
        entry = fi.load(root, log_id="p")["entries"][0]
        self.assertEqual(entry["text"], text)
        self.assertEqual(set(entry), {"time_seconds", "text"})


def item(name, start, end, reel=None, src=0, path="/m/a.mov"):
    return {"item_name": name, "timeline_start_frame": start, "timeline_end_frame": end,
            "reel_name": reel, "source_start_frame": src, "media_path": path}


class SetupSheetTests(unittest.TestCase):
    ITEMS = [
        item("a1", 0, 100, reel="A001"),
        item("b1", 100, 400, reel="B002"),
        item("a2", 400, 900, reel="A001"),   # longest A001 usage
        item("b2", 900, 950, reel="B002"),
    ]

    def test_one_representative_per_setup(self) -> None:
        out = ss.select_representatives(self.ITEMS)
        self.assertEqual(out["setup_count"], 2)
        self.assertEqual(out["shot_count"], 4)

    def test_the_frame_comes_from_the_longest_usage(self) -> None:
        """Not the first — heads catch fades, slates and handles."""
        rep = next(r for r in ss.select_representatives(self.ITEMS)["representatives"]
                   if r["setup"] == "A001")
        self.assertEqual(rep["item_name"], "a2")
        self.assertEqual(rep["timeline_frame"], 650)  # middle of 400-900

    def test_ordered_by_first_appearance_so_it_reads_like_the_film(self) -> None:
        setups = [r["setup"] for r in ss.select_representatives(self.ITEMS)["representatives"]]
        self.assertEqual(setups, ["A001", "B002"])

    def test_folder_is_the_fallback_grouping(self) -> None:
        out = ss.select_representatives([
            item("x", 0, 100, path="/media/DAY01/x.mov"),
            item("y", 100, 200, path="/media/DAY02/y.mov"),
        ])
        self.assertEqual({r["setup"] for r in out["representatives"]}, {"DAY01", "DAY02"})

    def test_the_grouping_declares_itself_a_proxy(self) -> None:
        out = ss.select_representatives(self.ITEMS)
        self.assertIn("PROXY", out["grouping_basis"])

    def test_unusable_items_are_reported_not_dropped(self) -> None:
        out = ss.select_representatives(self.ITEMS + [
            {"item_name": "broken", "timeline_start_frame": None, "timeline_end_frame": None}
        ])
        self.assertEqual(len(out["unusable"]), 1)
        self.assertIn("NOT represented", out["unusable"][0]["reason"])

    def test_no_items_is_an_error(self) -> None:
        self.assertFalse(ss.select_representatives([])["success"])


if __name__ == "__main__":
    unittest.main()
