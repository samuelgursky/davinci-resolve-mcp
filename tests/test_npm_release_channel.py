"""Feedback prereleases must never publish or repair the stable npm tag."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NpmReleaseChannelTests(unittest.TestCase):
    def test_channel_selection_and_stable_repair_guard(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js unavailable")
        workflow = (ROOT / ".github/workflows/npm-publish.yml").read_text(encoding="utf-8")
        blocks = dict(block.split("\n", 1) for block in re.split(r"(?m)^      - name: ", workflow)[1:])
        select = blocks["Select npm release channel"]
        script = textwrap.dedent(select.split("        run: |\n", 1)[1])
        publish = blocks["Publish to npm"]
        repair = blocks["Keep the latest dist-tag on the highest published version"]
        self.assertIn('--tag "${{ steps.release_channel.outputs.dist_tag }}"', publish)
        condition = re.search(r"(?m)^        if: (.+)$", repair).group(1)
        self.assertIn("steps.release_channel.outputs.dist_tag == 'latest'", condition)
        for version, expected in [("4.16.0-beta.1", "next"), ("4.15.0", "latest")]:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as folder:
                path = Path(folder)
                (path / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
                output = path / "channel.txt"
                # Execute only channel selection, never the publishing step.
                result = subprocess.run(["bash", "-eu", "-c", script], cwd=path,
                                        env={**os.environ, "GITHUB_OUTPUT": str(output)},
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output.read_text(encoding="utf-8").strip(), f"dist_tag={expected}")
