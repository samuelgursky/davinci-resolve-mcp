"""Offline tests for src/utils/fusion_group_settings.py.

The fixtures intentionally include nested UserControls / ControlGroup tables
because real-world Fusion GroupOperator exports almost always have them — a
flat regex parser would silently truncate InstanceInput bodies at the first
inner `}`.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.fusion_group_settings import (
    FUSION_COMMIT_CHECKLIST,
    FUSION_GROUP_GUARDRAILS,
    default_backup_path,
    parse_instance_input_block,
    parse_setting_file,
    splice_inputs_block,
)


# A flat fixture (no nested braces) used to check basic parsing + slot ordering.
FLAT_FIXTURE = """{
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


# A realistic fixture with nested UserControls (slider hint table) on Input1.
# The original PR's flat regex truncates Input1 at the inner `}` and reports
# only 1 of 3 inputs, with wrong fields.
NESTED_FIXTURE = """{
\tTools = ordered() {
\t\tAMZThoughtBubblev13 = GroupOperator {
\t\t\tInputs = ordered() {
\t\t\t\tInput1 = InstanceInput {
\t\t\t\t\tSourceOp = "TextPlus1",
\t\t\t\t\tSource = "Size",
\t\t\t\t\tName = "Text Size",
\t\t\t\t\tDefault = 0.08,
\t\t\t\t\tPage = "Controls",
\t\t\t\t\tUserControls = ordered() {
\t\t\t\t\t\tCustom = {
\t\t\t\t\t\t\tLINKID_DataType = "Number",
\t\t\t\t\t\t\tINPID_InputControl = "SliderControl",
\t\t\t\t\t\t\tINP_MinScale = 0,
\t\t\t\t\t\t\tINP_MaxScale = 0.5,
\t\t\t\t\t\t\tINP_Integer = false,
\t\t\t\t\t\t},
\t\t\t\t\t},
\t\t\t\t},
\t\t\t\tInput2 = InstanceInput {
\t\t\t\t\tSourceOp = "TextPlus1",
\t\t\t\t\tSource = "StyledText",
\t\t\t\t\tName = "Text",
\t\t\t\t\tControlGroup = 1,
\t\t\t\t},
\t\t\t\tInput3 = InstanceInput {
\t\t\t\t\tSourceOp = "TextPlus1",
\t\t\t\t\tSource = "Red1",
\t\t\t\t\tName = "Text Color",
\t\t\t\t\tControlGroup = 10,
\t\t\t\t\tDefault = 0.1764705882353,
\t\t\t\t},
\t\t\t},
\t\t\tTools = ordered() {
\t\t\t\tTextPlus1 = TextPlus { Inputs = {} },
\t\t\t},
\t\t},
\t},
}"""


# A template fixture: smaller, ordered, different inputs. Used to verify the
# splice replaces the source's Inputs block end-to-end.
TEMPLATE_FIXTURE = """{
\tTools = ordered() {
\t\tDummyTemplate = GroupOperator {
\t\t\tInputs = ordered() {
\t\t\t\tInput1 = InstanceInput {
\t\t\t\t\tSourceOp = "TextPlus1",
\t\t\t\t\tSource = "StyledText",
\t\t\t\t\tName = "Text",
\t\t\t\t},
\t\t\t\tInput2 = InstanceInput {
\t\t\t\t\tSourceOp = "TextPlus1",
\t\t\t\t\tSource = "Size",
\t\t\t\t\tName = "Text Size",
\t\t\t\t\tDefault = 0.06,
\t\t\t\t},
\t\t\t},
\t\t\tTools = ordered() {
\t\t\t\tNoOp = Note { Inputs = {} },
\t\t\t},
\t\t},
\t},
}"""


def _write(tmp: str, name: str, content: str) -> str:
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


class ParseFlatTest(unittest.TestCase):
    def test_parse_sorts_slots_by_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "flat.setting", FLAT_FIXTURE)
            parsed = parse_setting_file(path, group_name="AMZThoughtBubblev13")
            self.assertEqual(parsed["input_count"], 2)
            self.assertEqual(parsed["published_inputs"][0]["slot"], "Input1")
            self.assertEqual(parsed["published_inputs"][0]["source"], "TextSize")
            self.assertEqual(parsed["published_inputs"][0]["max_scale"], 0.1)
            self.assertEqual(parsed["published_inputs"][1]["slot"], "Input2")


class ParseNestedTest(unittest.TestCase):
    """These cases exercise the balanced-brace parser. A flat-regex parser
    would mis-bound Input1's body at the first inner `}` and either report
    fewer inputs or carry wrong field values."""

    def test_nested_inputs_all_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "nested.setting", NESTED_FIXTURE)
            parsed = parse_setting_file(path, group_name="AMZThoughtBubblev13")
            self.assertEqual(parsed["input_count"], 3)
            slots = [row["slot"] for row in parsed["published_inputs"]]
            self.assertEqual(slots, ["Input1", "Input2", "Input3"])

    def test_nested_input1_fields_correct(self):
        # The PR's flat regex would truncate Input1 at `INP_Integer = false,\n}`,
        # losing the closing of the InstanceInput. The balanced parser keeps
        # the shallow Source/Name/Default fields intact.
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "nested.setting", NESTED_FIXTURE)
            parsed = parse_setting_file(path, group_name="AMZThoughtBubblev13")
            input1 = parsed["published_inputs"][0]
            self.assertEqual(input1["source"], "Size")
            self.assertEqual(input1["source_op"], "TextPlus1")
            self.assertEqual(input1["name"], "Text Size")
            self.assertEqual(input1["default"], "0.08")

    def test_shallow_fields_skip_nested_keys(self):
        """Keys inside a nested table (LINKID_DataType, INPID_InputControl,
        INP_MaxScale) must not leak into the InstanceInput's top-level fields."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "nested.setting", NESTED_FIXTURE)
            parsed = parse_setting_file(path, group_name="AMZThoughtBubblev13")
            input1 = parsed["published_inputs"][0]
            # The nested INP_MaxScale = 0.5 must NOT be reported as max_scale.
            self.assertIsNone(input1["max_scale"])


class SpliceTest(unittest.TestCase):
    def test_splice_replaces_inputs_block_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _write(tmp, "nested.setting", NESTED_FIXTURE)
            tpl = _write(tmp, "tpl.setting", TEMPLATE_FIXTURE)
            dest = os.path.join(tmp, "out.setting")
            summary = splice_inputs_block(
                src, tpl, dest,
                source_group_name="AMZThoughtBubblev13",
                template_group_name="DummyTemplate",
            )
            self.assertTrue(os.path.isfile(dest))
            self.assertEqual(summary["before_input_count"], 3)
            self.assertEqual(summary["after_input_count"], 2)
            with open(dest, encoding="utf-8") as handle:
                content = handle.read()
            # The source's outer GroupOperator name must be preserved.
            self.assertIn("AMZThoughtBubblev13 = GroupOperator", content)
            # The source's inner Tools section (TextPlus1) must be preserved.
            self.assertIn("TextPlus1 = TextPlus", content)
            # The template's Inputs must replace the source's Inputs.
            new_inputs = parse_setting_file(dest, group_name="AMZThoughtBubblev13")
            sources = [row["source"] for row in new_inputs["published_inputs"]]
            self.assertEqual(sources, ["StyledText", "Size"])

    def test_splice_diff_classifies_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _write(tmp, "nested.setting", NESTED_FIXTURE)
            tpl = _write(tmp, "tpl.setting", TEMPLATE_FIXTURE)
            dest = os.path.join(tmp, "out.setting")
            summary = splice_inputs_block(
                src, tpl, dest,
                source_group_name="AMZThoughtBubblev13",
                template_group_name="DummyTemplate",
            )
            changes = {row["slot"]: row["change"] for row in summary["diff"]}
            # Input3 in the source has no counterpart in the 2-input template.
            self.assertEqual(changes.get("Input3"), "removed")

    def test_splice_missing_group_name_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _write(tmp, "nested.setting", NESTED_FIXTURE)
            tpl = _write(tmp, "tpl.setting", TEMPLATE_FIXTURE)
            dest = os.path.join(tmp, "out.setting")
            with self.assertRaises(ValueError):
                splice_inputs_block(
                    src, tpl, dest,
                    source_group_name="DoesNotExist",
                    template_group_name="DummyTemplate",
                )


class InputBlockParseUnitTest(unittest.TestCase):
    """Direct unit-level coverage of parse_instance_input_block — useful when
    debugging the balanced-brace walker without round-tripping through a file."""

    def test_three_inputs_with_nested_braces(self):
        inputs_inner = """
            Input1 = InstanceInput {
                SourceOp = "A",
                Source = "X",
                UserControls = ordered() { Custom = { K = "v" } },
            },
            Input2 = InstanceInput {
                SourceOp = "B",
                Source = "Y",
            },
            Input3 = InstanceInput {
                SourceOp = "C",
                Source = "Z",
                ControlGroup = 7,
            },
        """
        parsed = parse_instance_input_block(inputs_inner)
        self.assertEqual([row.slot for row in parsed], ["Input1", "Input2", "Input3"])
        self.assertEqual(parsed[0].source_op, "A")
        self.assertEqual(parsed[2].control_group, 7)


class BackupPathTest(unittest.TestCase):
    def test_backup_path_includes_timestamp_and_extension(self):
        path = default_backup_path("/tmp/foo.setting")
        self.assertTrue(path.startswith("/tmp/foo.backup_"))
        self.assertTrue(path.endswith(".setting"))

    def test_backup_path_handles_missing_extension(self):
        path = default_backup_path("/tmp/foo")
        self.assertTrue(path.endswith(".setting"))


class AdvisoryConstantsTest(unittest.TestCase):
    def test_guardrails_are_non_empty_strings(self):
        self.assertGreater(len(FUSION_GROUP_GUARDRAILS), 0)
        for line in FUSION_GROUP_GUARDRAILS:
            self.assertIsInstance(line, str)
            self.assertGreater(len(line), 10)

    def test_checklist_mentions_save(self):
        self.assertTrue(
            any("Save" in step or "save" in step for step in FUSION_COMMIT_CHECKLIST)
        )


if __name__ == "__main__":
    unittest.main()
