"""The Bash guard, exercised by running it — not by reading it.

`.agents/hooks/source_media_guard.py` is the canonical tripwire between an agent's shell
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

import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile
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

    def test_writing_into_the_platform_temp_dir_passes(self) -> None:
        """On Windows the system temp dir is `%TEMP%`, not `/tmp`; it is scratch too (#277)."""
        out = shlex.quote(os.path.join(tempfile.gettempdir(), "out.mp4").replace(os.sep, "/"))
        self.assertEqual(verdict(f"ffmpeg -i master.mp4 {out}"), "allow")

    def test_a_broad_temp_variable_does_not_widen_the_guard(self) -> None:
        """TMPDIR/TEMP are set for other reasons, often to the media drive in post.

        Pointing them at the home directory must not make the home directory
        scratch: an overwrite or delete there is still denied.
        """
        home = os.path.expanduser("~")
        env = {**os.environ, "TMPDIR": home, "TEMP": home, "TMP": home}
        for command in (f"rm {shlex.quote(os.path.join(home, 'Movies', 'clip.mov'))}",
                        f"ffmpeg -i master.mp4 -y {shlex.quote(os.path.join(home, 'Movies', 'master.mp4'))}"):
            with self.subTest(command=command):
                payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
                proc = subprocess.run([sys.executable, HOOK], input=payload, capture_output=True,
                                      text=True, timeout=30, env=env)
                self.assertIn('"deny"', proc.stdout)

    def test_reading_is_not_writing(self) -> None:
        """`ffmpeg -i x.mp4` with no output operand prints stream info and exits;
        the trailing token is the value of `-i`, not a file being written. Denying
        it would train an agent to route around the guard for a read."""
        self.assertEqual(verdict("ffmpeg -i master.mp4"), "allow")
        self.assertEqual(verdict("ffmpeg -i master.mp4 -f null -"), "allow")
        self.assertEqual(verdict("ffprobe -v quiet -print_format json footage/clip.mp4"), "allow")


def _load_guard():
    path = os.path.join(REPO_ROOT, ".agents", "hooks", "source_media_guard.py")
    spec = importlib.util.spec_from_file_location("source_media_guard_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlatformTempRootTests(unittest.TestCase):
    """Which temp directory counts as scratch, decided without touching the host's own."""

    guard = _load_guard()

    def root(self, temp: str, os_name: str = "nt", home: str = "/users/editor",
             cwd: str = "/projects/show") -> object:
        return self.guard.platform_temp_root(os_name=os_name, temp=temp, home=home, cwd=cwd)

    def test_windows_temp_under_the_profile_is_scratch(self) -> None:
        self.assertEqual(self.root("/users/editor/appdata/local/temp"),
                         self.guard.normalize("/users/editor/appdata/local/temp").lower())

    def test_posix_never_trusts_the_temp_variable(self) -> None:
        self.assertIsNone(self.root("/users/editor/appdata/local/temp", os_name="posix"))

    def test_a_drive_or_filesystem_root_is_refused(self) -> None:
        self.assertIsNone(self.root(os.path.abspath(os.sep)))

    def test_the_profile_or_an_ancestor_of_it_is_refused(self) -> None:
        self.assertIsNone(self.root("/users/editor"))
        self.assertIsNone(self.root("/users"))

    def test_the_working_directory_fallback_is_refused(self) -> None:
        self.assertIsNone(self.root("/projects/show"))

    def test_a_media_drive_temp_folder_stays_narrow(self) -> None:
        """A dedicated temp folder on a media drive is scratch; the drive itself is not."""
        self.assertEqual(self.root("/volumes/raid/temp"), self.guard.normalize("/volumes/raid/temp").lower())


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
