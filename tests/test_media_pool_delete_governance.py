"""Tests for catastrophic media-pool delete governance (gameplan EX2/EX3).

EX2: the destructive registry must use the REAL compound action strings so
is_destructive() fires (version-on-mutate archiving). EX3: those deletes are
confirm-token gated and the pending-confirm check fires so the wrapper skips
archiving on the token-issuance call.
"""
import unittest
from unittest import mock

import src.server as s
from src.utils.destructive_hook import is_destructive, DESTRUCTIVE_ACTIONS_BY_TOOL


class RegistryEX2Test(unittest.TestCase):
    def test_real_compound_deletes_are_destructive(self):
        for action in ("delete_clips", "delete_folders", "delete_timelines", "move_clips", "move_folders", "delete_clip_mattes"):
            self.assertTrue(is_destructive("media_pool", action), action)

    def test_dead_granular_names_removed(self):
        mp = DESTRUCTIVE_ACTIONS_BY_TOOL["media_pool"]
        for dead in ("delete_media_pool_clips", "delete_media_pool_folders", "move_media_pool_folders",
                     "replace_clip", "link_clip_proxy_media", "link_clip_full_resolution_media"):
            self.assertNotIn(dead, mp, dead)


class GatingWiringEX3Test(unittest.TestCase):
    def test_deletes_are_token_gated(self):
        for action in ("delete_clips", "delete_folders", "delete_timelines"):
            self.assertIn(("media_pool", action), s._TOKEN_GATED_DESTRUCTIVE_ACTIONS, action)

    def test_pending_confirm_check_fires_for_deletes(self):
        # When confirm is required and no token is present, the wrapper must learn
        # the call WILL gate (so it skips archiving the not-yet-mutated state).
        with mock.patch.object(s, "_confirm_token_required", return_value=True):
            self.assertTrue(s._action_will_gate_pending_confirm("media_pool", "delete_clips", {"clip_ids": ["x"]}))
            # With a token present, it will NOT gate (it proceeds to mutate+archive).
            self.assertFalse(s._action_will_gate_pending_confirm("media_pool", "delete_clips", {"clip_ids": ["x"], "confirm_token": "t"}))

    def test_gated_deletes_are_also_in_destructive_registry(self):
        # Consistency: anything token-gated for media_pool must also be archived.
        for tool, action in s._TOKEN_GATED_DESTRUCTIVE_ACTIONS:
            if tool == "media_pool":
                self.assertTrue(is_destructive(tool, action), f"{tool}.{action} gated but not in registry")


class DeleteClipsIssueTokenTest(unittest.TestCase):
    """The issue-token path returns confirmation_required before any deletion."""

    def test_delete_clips_issues_token_without_confirm(self):
        fake_clip = mock.Mock()
        fake_clip.GetName.return_value = "shot01.mov"
        fake_mp = mock.Mock()
        fake_root = mock.Mock()
        fake_proj = mock.Mock()
        with mock.patch.object(s, "_confirm_token_required", return_value=True), \
             mock.patch.object(s, "_check", return_value=(mock.Mock(), fake_proj, None)), \
             mock.patch.object(s, "_get_mp", return_value=(mock.Mock(), fake_proj, fake_mp, None)), \
             mock.patch.object(s, "_find_clip", return_value=fake_clip):
            fake_mp.GetRootFolder.return_value = fake_root
            out = s.media_pool("delete_clips", {"clip_ids": ["c1", "c2"]})
        self.assertEqual(out.get("status"), "confirmation_required")
        self.assertIn("confirm_token", out)
        self.assertEqual(out["preview"]["clips_lost"], 2)
        fake_mp.DeleteClips.assert_not_called()  # nothing deleted on the issue call


if __name__ == "__main__":
    unittest.main()
