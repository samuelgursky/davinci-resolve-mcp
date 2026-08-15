"""Drift guards for the compound social-delivery workflow surface."""

from pathlib import Path
import unittest

import src.server as compound


REPO_ROOT = Path(__file__).resolve().parents[1]

ACTION_TO_TOOL = {
    "delivery_preflight": "render",
    "ensure_project_timeline": "project_manager",
    "exposure_plan": "timeline",
    "apply_drx_and_cdls_bulk": "timeline",
    "cover_frame_candidates": "timeline",
    "complete_delivery_job": "render",
}


class SocialDeliveryActionDocsTest(unittest.TestCase):
    def test_every_workflow_action_is_registered_with_callable_help(self):
        for action, tool in ACTION_TO_TOOL.items():
            with self.subTest(action=action, tool=tool):
                result = compound._action_help(tool, {"name": action})
                self.assertTrue(result.get("success"), result)
                self.assertEqual(action, result["action"])
                self.assertIn(action, result["example"])

    def test_durable_docs_name_the_complete_workflow(self):
        docs = {
            "skill": (REPO_ROOT / "docs" / "SKILL.md").read_text(encoding="utf-8"),
            "delivery kernel": (
                REPO_ROOT / "docs" / "kernels" / "render-deliver-kernel.md"
            ).read_text(encoding="utf-8"),
        }

        for label, text in docs.items():
            for action in ACTION_TO_TOOL:
                with self.subTest(document=label, action=action):
                    self.assertIn(action, text)


if __name__ == "__main__":
    unittest.main()
