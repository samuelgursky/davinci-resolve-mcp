"""Release-surface drift guard.

docs/process/release-process.md mandates that every version bump updates the
README badges (English + zh-CN), the zh-CN correspondence line, and the
CHANGELOG — yet those surfaces silently sat at v2.108.0 through 28 releases
because nothing failed when they drifted. This guard makes the mandate
enforceable: the four stamps already agree via test_import, and now the
human-facing surfaces must agree with them too.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def package_version() -> str:
    return json.loads((REPO / "package.json").read_text(encoding="utf-8"))["version"]


class ReleaseSurfaces(unittest.TestCase):
    def test_readme_badge_matches_package_version(self):
        version = package_version()
        text = (REPO / "README.md").read_text(encoding="utf-8")
        m = re.search(r"badge/version-([0-9.]+)-blue", text)
        self.assertIsNotNone(m, "README.md has no version badge")
        self.assertEqual(m.group(1), version,
                         f"README version badge says {m.group(1)} but package.json says {version} — "
                         "update the badge with the release bump (docs/process/release-process.md)")

    def test_zh_readme_badge_and_line_match(self):
        version = package_version()
        zh = REPO / "README.zh-CN.md"
        if not zh.exists():
            self.skipTest("translation removed — allowed by the release process")
        text = zh.read_text(encoding="utf-8")
        m = re.search(r"badge/version-([0-9.]+)-blue", text)
        self.assertIsNotNone(m, "README.zh-CN.md has no version badge")
        self.assertEqual(m.group(1), version, "zh-CN version badge drifted from package.json")
        line = re.search(r"本翻译对应 v([0-9.]+) 版 README", text)
        self.assertIsNotNone(line, "zh-CN correspondence line missing")
        self.assertEqual(line.group(1), version,
                         "zh-CN 对应 line drifted — it makes a factual claim about which README it "
                         "translates, so a stale value is worse than no translation")

    def test_changelog_has_an_entry_for_the_current_version(self):
        version = package_version()
        text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## What's New in v{version}", text,
                      f"CHANGELOG.md has no entry for v{version} — add one with the release bump "
                      "(port the GitHub Release notes; see docs/process/release-process.md)")


if __name__ == "__main__":
    unittest.main()
