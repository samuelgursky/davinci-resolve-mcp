"""The granular ti_copy_grades tool gates the same API the compound one does.

`TimelineItem.CopyGrades` replaces a target's whole node graph and creates no
version to go back to. The compound `timeline_item_color copy_grades` learned a
trap guard and a confirm token; the granular twin reached the identical API with
neither, and on a surface that addresses clips by bare 0-based index rather than by
unique ID — so the failure mode was not just "grades replaced without asking" but
"grades replaced on a clip the caller never named".

These tests pin both halves: the two acknowledgements, and the index validation that
makes the preview mean what it says.
"""

import unittest
from unittest import mock

import src.granular.timeline_item as granular
from src.granular.common import CONFIRM_TOKENS


class _ItemStub:
    def __init__(self, uid, name, start):
        self._uid, self._name, self._start = uid, name, start
        self.copied_to = []

    def GetUniqueId(self):
        return self._uid

    def GetName(self):
        return self._name

    def GetStart(self):
        return self._start

    def CopyGrades(self, targets):
        self.copied_to.append([t.GetUniqueId() for t in targets])
        return True


class _TimelineStub:
    def __init__(self, items):
        self._items = items

    def GetItemListInTrack(self, track_type, track_index):
        if track_type != "video" or track_index != 1:
            return []
        return self._items


class GranularCopyGradesGateTest(unittest.TestCase):
    def setUp(self):
        self.source = _ItemStub("src-1", "HERO", 0)
        self.a = _ItemStub("tgt-a", "SHOT_A", 100)
        self.b = _ItemStub("tgt-b", "SHOT_B", 200)
        self.items = [self.source, self.a, self.b]
        self.timeline = _TimelineStub(self.items)
        CONFIRM_TOKENS.tokens.clear()
        patch = mock.patch.object(
            granular, "_get_timeline", return_value=(mock.Mock(), self.timeline, None)
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(CONFIRM_TOKENS.tokens.clear)

    def _call(self, **kwargs):
        params = {"target_item_indices": [1], "source_item_index": 0}
        params.update(kwargs)
        return granular.ti_copy_grades(**params)

    def assertNothingCopied(self):
        self.assertEqual(self.source.copied_to, [])

    # ── the two acknowledgements ─────────────────────────────────────────────

    def test_refuses_without_trap_acknowledgement(self):
        out = self._call()

        self.assertFalse(out["success"])
        self.assertEqual(out["retry_with"], {"acknowledge_trap": True})
        self.assertTrue(out["known_limitation"])
        self.assertNotIn("confirm_token", out)
        self.assertNothingCopied()

    def test_trap_acknowledgement_alone_only_buys_a_preview(self):
        out = self._call(acknowledge_trap=True)

        self.assertEqual(out["status"], "confirmation_required")
        self.assertEqual(out["code"], "CONFIRMATION_REQUIRED")
        self.assertNothingCopied()

    def test_preview_names_the_clips_it_resolved(self):
        out = self._call(acknowledge_trap=True, target_item_indices=[1, 2])
        preview = out["preview"]

        self.assertEqual(preview["target_count"], 2)
        self.assertEqual([t["index"] for t in preview["targets"]], [1, 2])
        self.assertEqual([t["name"] for t in preview["targets"]], ["SHOT_A", "SHOT_B"])
        self.assertEqual(preview["source"]["name"], "HERO")

    def test_token_allows_exactly_one_mutation(self):
        token = self._call(acknowledge_trap=True)["confirm_token"]

        done = self._call(acknowledge_trap=True, confirm_token=token)
        self.assertTrue(done["success"])
        self.assertEqual(self.source.copied_to, [["tgt-a"]])

        replay = self._call(acknowledge_trap=True, confirm_token=token)
        self.assertEqual(replay["code"], "CONFIRM_TOKEN_INVALID")
        self.assertEqual(self.source.copied_to, [["tgt-a"]], "token was reusable")

    def test_token_does_not_carry_to_different_targets(self):
        token = self._call(acknowledge_trap=True, target_item_indices=[1])["confirm_token"]

        out = self._call(
            acknowledge_trap=True, target_item_indices=[1, 2], confirm_token=token
        )

        self.assertEqual(out["code"], "CONFIRM_TOKEN_FINGERPRINT_MISMATCH")
        self.assertNothingCopied()

    def test_gate_off_still_requires_the_trap_acknowledgement(self):
        with mock.patch.object(CONFIRM_TOKENS, "_required", lambda: False):
            self.assertEqual(self._call()["retry_with"], {"acknowledge_trap": True})
            self.assertNothingCopied()

            out = self._call(acknowledge_trap=True)

        self.assertTrue(out["success"])
        self.assertEqual(self.source.copied_to, [["tgt-a"]])

    # ── index validation: the preview must describe the real targets ─────────

    def test_negative_index_is_refused_rather_than_wrapping_to_the_last_clip(self):
        out = self._call(acknowledge_trap=True, target_item_indices=[-1])

        self.assertIn("out of range", out["error"])
        self.assertNotIn("confirm_token", out)
        self.assertNothingCopied()

    def test_out_of_range_index_is_refused_rather_than_silently_dropped(self):
        out = self._call(acknowledge_trap=True, target_item_indices=[1, 99])

        self.assertIn("out of range", out["error"])
        self.assertEqual(out["track_item_count"], 3)
        self.assertNothingCopied()

    def test_out_of_range_source_is_refused(self):
        out = self._call(acknowledge_trap=True, source_item_index=99)

        self.assertIn("out of range", out["error"])
        self.assertNothingCopied()

    def test_source_listed_as_its_own_target_is_refused(self):
        out = self._call(acknowledge_trap=True, target_item_indices=[0, 1])

        self.assertIn("source_item_index", out["error"])
        self.assertNothingCopied()

    def test_duplicate_targets_are_collapsed_before_the_preview(self):
        out = self._call(acknowledge_trap=True, target_item_indices=[1, 1, 2])

        self.assertEqual(out["preview"]["target_count"], 2)

    def test_empty_target_list_is_refused(self):
        out = self._call(acknowledge_trap=True, target_item_indices=[])

        self.assertIn("non-empty", out["error"])
        self.assertNothingCopied()

    def test_booleans_are_not_accepted_as_indices(self):
        # bool is an int subclass, so True would otherwise index item 1.
        out = self._call(acknowledge_trap=True, target_item_indices=[True])

        self.assertIn("out of range", out["error"])
        self.assertNothingCopied()


class GranularCopyGradesAnnotationTest(unittest.TestCase):
    """The MCP safety hint a client reads before it ever calls the tool.

    Granular tools infer their annotation from a name prefix, and `ti_` matches
    none of the read/write/destructive prefix lists, so every `ti_*` tool falls
    through to the plain WRITE default — `destructiveHint=False`. A client that
    gates on that hint was told this tool was safe. The annotation is therefore
    passed explicitly rather than left to the heuristic.
    """

    def test_tool_is_registered_as_destructive(self):
        import asyncio

        from src.granular.common import mcp

        tools = asyncio.run(mcp.list_tools())
        tool = next(t for t in tools if t.name == "ti_copy_grades")

        self.assertTrue(tool.annotations.destructiveHint)
        self.assertFalse(tool.annotations.readOnlyHint)

    def test_the_prefix_heuristic_alone_would_still_call_it_safe(self):
        # Pins the reason the explicit annotation above is needed. If the
        # heuristic ever learns to strip `ti_`, this fails — drop the explicit
        # annotation then rather than keeping both.
        from src.granular.common import _annotations_for_tool_name

        self.assertFalse(_annotations_for_tool_name("ti_copy_grades").destructiveHint)


if __name__ == "__main__":
    unittest.main()
