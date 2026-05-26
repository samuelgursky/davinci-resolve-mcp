"""Offline tests for fusion group .setting parse/patch helpers."""

import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.fusion_group_settings import (
    fusion_commit_hint,
    parse_setting_file,
    patch_group_inputs_block,
    patch_setting_file,
)


THOUGHT_FIXTURE = """{
\tTools = ordered() {
\t\tAMZThoughtBubblev13 = GroupOperator {
\t\t\tInputs = ordered() {
\t\t\t\tInput2 = InstanceInput {
\t\t\t\t\tSourceOp = "TextBox",
\t\t\t\t\tSource = "TextLineSpacing",
\t\t\t\t},
\t\t\t\tInput1 = InstanceInput {
\t\t\t\t\tSourceOp = "TextBox",
\t\t\t\t\tSource = "TextSize",
\t\t\t\t\tMaxScale = 0.1,
\t\t\t\t},
\t\t\t},
\t\t\tTools = ordered() {
\t\t\t\tTextBox = TextPlus { Inputs = {} },
\t\t\t},
\t\t},
\t},
}"""


class FusionGroupSettingsTest(unittest.TestCase):
    def test_parse_instance_inputs_sorted_by_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thought.setting")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(THOUGHT_FIXTURE)
            parsed = parse_setting_file(path, group_name="AMZThoughtBubblev13")
            self.assertEqual(parsed["input_count"], 2)
            self.assertEqual(parsed["published_inputs"][0]["slot"], "Input1")
            self.assertEqual(parsed["published_inputs"][0]["source"], "TextSize")
            self.assertEqual(parsed["published_inputs"][1]["slot"], "Input2")

    def test_patch_reorders_to_speech_template(self):
        patched, summary = patch_group_inputs_block(
            THOUGHT_FIXTURE,
            group_name="AMZThoughtBubblev13",
            max_scale=0.25,
        )
        self.assertEqual(summary["new_input_count"], 14)
        self.assertGreater(summary["diff_count"], 0)
        self.assertIn("Input4 = InstanceInput", patched)
        self.assertIn("MaxScale = 0.25", patched)
        self.assertIn('Source = "TextSize"', patched)

    def test_patch_setting_file_writes_dest(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src.setting")
            dest = os.path.join(tmp, "dest.setting")
            with open(src, "w", encoding="utf-8") as handle:
                handle.write(THOUGHT_FIXTURE)
            summary = patch_setting_file(src, dest, group_name="AMZThoughtBubblev13")
            self.assertTrue(os.path.isfile(dest))
            self.assertEqual(summary["dest_path"], dest)
            self.assertEqual(summary["new_input_count"], 14)

    def test_fusion_commit_hint_shape(self):
        hint = fusion_commit_hint()
        self.assertTrue(hint["modified"])
        self.assertGreaterEqual(len(hint["checklist"]), 3)
        self.assertIn("InstanceInput", hint["instance_input_note"])


if __name__ == "__main__":
    unittest.main()
