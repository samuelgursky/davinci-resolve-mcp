import unittest
from unittest.mock import patch

import src.server as compound


class ConfirmTokenPreferenceTests(unittest.TestCase):
    def test_confirm_token_gate_honors_destructive_preference_false(self):
        with patch.object(
            compound,
            "_read_media_analysis_preferences",
            return_value={"destructive": {"require_confirm_token": False}},
        ):
            self.assertFalse(compound._confirm_token_required())

    def test_confirm_token_gate_defaults_to_required(self):
        with patch.object(compound, "_read_media_analysis_preferences", return_value={}):
            self.assertTrue(compound._confirm_token_required())


if __name__ == "__main__":
    unittest.main()
