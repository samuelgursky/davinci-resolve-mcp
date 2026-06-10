"""Static guard: the control-panel guide tracks the panel's actual structure.

docs/guides/control-panel.md is hand-written prose; nothing regenerates it
when the panel UI changes, and it once drifted six surfaces behind the code.
This test extracts the panel's navigation structure (PANEL_LABELS and
SUBPAGE_LABELS in src/analysis_dashboard.py) and fails when a section or
subpage isn't mentioned in the guide, or when the guide's screenshots are
missing or orphaned. Update the prose (and rerun
scripts/regen_panel_screenshots.py) when this fires.
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "src" / "analysis_dashboard.py"
GUIDE = ROOT / "docs" / "guides" / "control-panel.md"
IMAGES = ROOT / "docs" / "images" / "control-panel"

# The Docs panel's subpages are the doc files themselves; the guide doesn't
# need to enumerate a doc reader's reading list.
SKIP_SUBPAGE_SCOPES = {"docs"}


def _extract_label_block(source: str, const_name: str) -> str:
    match = re.search(rf"const {const_name} = \{{(.*?)\n    \}};", source, re.S)
    assert match, f"could not find {const_name} in analysis_dashboard.py"
    return match.group(1)


def _labels_in_block(block: str) -> list[str]:
    return re.findall(r":\s*'([^']+)'", block)


class PanelDocsDriftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DASHBOARD.read_text()
        cls.guide = GUIDE.read_text()
        cls.guide_lower = cls.guide.lower()

    def test_every_panel_section_is_documented(self):
        block = _extract_label_block(self.source, "PANEL_LABELS")
        missing = [label for label in _labels_in_block(block)
                   if label.lower() not in self.guide_lower]
        self.assertEqual(missing, [], f"panel sections absent from control-panel.md: {missing}")

    def test_every_subpage_is_documented(self):
        block = _extract_label_block(self.source, "SUBPAGE_LABELS")
        missing = []
        for scope_match in re.finditer(r"(\w[\w-]*):\s*\{(.*?)\}", block, re.S):
            scope, body = scope_match.group(1), scope_match.group(2)
            if scope in SKIP_SUBPAGE_SCOPES:
                continue
            for label in _labels_in_block(body):
                if label.lower() not in self.guide_lower:
                    missing.append(f"{scope}/{label}")
        self.assertEqual(missing, [], f"subpages absent from control-panel.md: {missing}")

    def test_guide_images_exist(self):
        referenced = re.findall(r"!\[[^\]]*\]\(\.\./images/control-panel/([^)]+)\)", self.guide)
        self.assertTrue(referenced, "guide references no screenshots — parser broken?")
        missing = [name for name in referenced if not (IMAGES / name).exists()]
        self.assertEqual(missing, [], f"guide references missing screenshots: {missing}")

    def test_no_orphaned_screenshots(self):
        referenced = set(re.findall(r"!\[[^\]]*\]\(\.\./images/control-panel/([^)]+)\)", self.guide))
        readme = (ROOT / "README.md").read_text()
        referenced.update(re.findall(r"docs/images/control-panel/([\w.-]+)", readme))
        orphans = [p.name for p in IMAGES.glob("*.png") if p.name not in referenced]
        self.assertEqual(orphans, [], f"screenshots on disk that no doc references: {orphans}")


if __name__ == "__main__":
    unittest.main()
