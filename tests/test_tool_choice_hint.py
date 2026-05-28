"""Contract tests for C3 — host_tool_choice_hint in deferred-payload.

See local/design/agentic-flow-improvements-gameplan.md §3 task C3.
"""
import unittest

from src.utils.media_analysis import build_host_chat_paths_payload


class HostToolChoiceHintTest(unittest.TestCase):
    def _sample_payload(self):
        record = {"clip_id": "clip-1", "clip_name": "test.mp4", "file_path": "/tmp/test.mp4"}
        motion = {}
        options = {"vision": {"enabled": True}}
        artifacts = {"frames": []}
        return build_host_chat_paths_payload(record, motion, options, artifacts)

    def test_payload_includes_host_tool_choice_hint(self):
        payload = self._sample_payload()
        self.assertIn("host_tool_choice_hint", payload)

    def test_hint_targets_commit_vision(self):
        payload = self._sample_payload()
        hint = payload["host_tool_choice_hint"]
        self.assertEqual(hint["type"], "tool")
        self.assertEqual(hint["name"], "media_analysis")
        self.assertEqual(hint["params_template"]["action"], "commit_vision")

    def test_hint_carries_clip_identifier_in_rationale(self):
        payload = self._sample_payload()
        rationale = payload["host_tool_choice_hint"]["rationale"]
        self.assertIn("clip-1", rationale)

    def test_existing_commit_action_unchanged(self):
        """C3 must not break the existing deferred-vision flow."""
        payload = self._sample_payload()
        self.assertIn("commit_action", payload)
        self.assertEqual(payload["commit_action"]["action"], "commit_vision")


if __name__ == "__main__":
    unittest.main()
