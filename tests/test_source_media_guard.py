"""The Bash guard, exercised by running it — not by reading it.

`.claude/hooks/source_media_guard.py` is the tripwire between an agent's shell
access and the one rule AGENTS.md opens with: source media is never modified.
It had no tests, and both holes closed in #152 were found by executing payloads
against it. So these run the hook as the harness runs it — a PreToolUse JSON
payload on stdin, a permission decision on stdout — because a lexical guard is
only as good as what it does with a string nobody thought of.

The pairs matter more than the rows. A multi-line block and the same commands
joined by `;` are the same command to a shell, so the guard has to answer them
the same way; when it did not, a harmless first line hid every mutating line
under it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO_ROOT, ".claude", "hooks", "source_media_guard.py")


def verdict(command: str) -> str:
    """"deny" or "allow", from the hook's own stdout."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        [sys.executable, HOOK], input=payload, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode not in (0, 2):
        raise AssertionError(f"hook exited {proc.returncode}: {proc.stderr}")
    if not proc.stdout.strip():
        return "allow"
    try:
        decision = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "deny" if '"deny"' in proc.stdout else "allow"
    blob = json.dumps(decision)
    return "deny" if '"deny"' in blob else "allow"


class NewlineSeparatorTests(unittest.TestCase):
    """A newline separates commands exactly as `;` does.

    The splitter knew `&&`, `||`, `;` and `|` but not `\\n`, so a multi-line block
    was one segment: argv0 came from the first line, and a non-mutating first
    line returned before anything below it was looked at.
    """

    def test_a_harmless_first_line_does_not_shield_the_lines_under_it(self) -> None:
        block = "mkdir -p footage/_superseded\nmv footage/clip.mp4 footage/_superseded/"
        self.assertEqual(verdict(block), "deny")

    def test_a_newline_and_a_semicolon_get_the_same_answer(self) -> None:
        """The pair is the test. Either answer alone is defensible; disagreeing
        about the same two commands is not."""
        commands = ("mkdir -p footage/_superseded", "mv footage/clip.mp4 footage/_superseded/")
        self.assertEqual(verdict("\n".join(commands)), verdict("; ".join(commands)))

    def test_a_cd_does_not_hide_the_delete_that_follows_it(self) -> None:
        self.assertEqual(verdict("cd footage\nrm CLIP.MP4"), "deny")

    def test_benign_multi_line_work_still_passes(self) -> None:
        for block in (
            "ls footage\nffprobe -v quiet footage/clip.mp4",
            "mkdir -p /tmp/work\nffmpeg -i footage/clip.mp4 /tmp/work/proxy.mp4",
        ):
            with self.subTest(block=block):
                self.assertEqual(verdict(block), "allow")


class FfmpegOutputTests(unittest.TestCase):
    def test_an_in_place_overwrite_is_the_case_the_guard_exists_for(self) -> None:
        """`ffmpeg -i master.mp4 master.mp4` is the unrecoverable one the deny
        message describes — and it was exempt, because the output operand was
        dropped precisely when it matched an input."""
        self.assertEqual(verdict("ffmpeg -i master.mp4 master.mp4"), "deny")

    def test_a_distinct_output_outside_scratch_is_still_denied(self) -> None:
        self.assertEqual(verdict("ffmpeg -i master.mp4 out.mp4"), "deny")

    def test_writing_into_a_scratch_root_still_passes(self) -> None:
        self.assertEqual(verdict("ffmpeg -i master.mp4 /tmp/out.mp4"), "allow")

    def test_reading_is_not_writing(self) -> None:
        """`ffmpeg -i x.mp4` with no output operand prints stream info and exits;
        the trailing token is the value of `-i`, not a file being written. Denying
        it would train an agent to route around the guard for a read."""
        self.assertEqual(verdict("ffmpeg -i master.mp4"), "allow")
        self.assertEqual(verdict("ffmpeg -i master.mp4 -f null -"), "allow")
        self.assertEqual(verdict("ffprobe -v quiet -print_format json footage/clip.mp4"), "allow")


class UnchangedBehaviourTests(unittest.TestCase):
    """Rows that must not move while the two holes are closed."""

    def test_a_redirect_onto_media_is_still_caught(self) -> None:
        self.assertEqual(verdict("cat header > camera.mov"), "deny")

    def test_a_read_is_still_a_read(self) -> None:
        self.assertEqual(verdict("ffprobe footage/clip.mp4"), "allow")

    def test_a_delete_inside_a_scratch_root_still_passes(self) -> None:
        self.assertEqual(verdict("rm /tmp/work/proxy.mp4"), "allow")


if __name__ == "__main__":
    unittest.main()
