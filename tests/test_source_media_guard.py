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

import json
import os
import runpy
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO_ROOT, ".claude", "hooks", "source_media_guard.py")


def verdict(command: str, *, temp_dir: str | None = None) -> str:
    """"deny" or "allow", from the hook's own stdout."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    hook_command = [sys.executable, HOOK]
    if temp_dir is not None:
        # Set the child's cached temp dir; patching it in this process cannot reach the hook.
        hook_command = [
            sys.executable, "-c",
            "import runpy, sys, tempfile\ntempfile.tempdir = sys.argv[1]\n"
            "runpy.run_path(sys.argv[2], run_name='__main__')",
            temp_dir, HOOK,
        ]
    proc = subprocess.run(
        hook_command, input=payload, capture_output=True, text=True, timeout=30,
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

    @unittest.skipUnless(os.name == "nt", "the platform temp exemption is Windows-only")
    def test_writing_into_the_platform_temp_dir_passes(self) -> None:
        """A narrow Windows temp root is scratch, independently of the host's TEMP."""
        root = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp")
        out = shlex.quote(os.path.join(root, "out.mp4").replace(os.sep, "/"))
        self.assertEqual(verdict(f"ffmpeg -i master.mp4 {out}", temp_dir=root), "allow")

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


class PlatformTempSafetyTests(unittest.TestCase):
    def test_broad_environment_temp_roots_do_not_license_media_writes_or_deletes(self) -> None:
        profile = os.path.abspath(os.path.expanduser("~"))
        roots = {"profile": profile, "cwd": os.getcwd()}
        ancestor = os.path.dirname(profile)
        while True:
            roots[f"ancestor:{ancestor}"] = ancestor
            parent = os.path.dirname(ancestor)
            if parent == ancestor:
                break
            ancestor = parent
        roots["profile_traversal"] = os.path.join(profile, "child", "..")
        roots["profile_case"] = profile.upper()
        for variable in ("TEMP", "TMPDIR", "TMP"):
            for label, root in roots.items():
                env = dict(os.environ)
                for name in ("TEMP", "TMPDIR", "TMP", "RESOLVE_MCP_SCRATCH"):
                    env.pop(name, None)
                env[variable] = root
                output = shlex.quote(os.path.join(root, "footage", "master.mp4").replace(os.sep, "/"))
                for command in (f"ffmpeg -i master.mp4 {output}", f"rm {output}"):
                    with self.subTest(variable=variable, root=label, command=command):
                        with patch.dict(os.environ, env, clear=True):
                            self.assertEqual(verdict(command, temp_dir=root), "deny")

    def test_real_environment_temp_selection_cannot_license_the_profile_or_cwd(self) -> None:
        for variable in ("TEMP", "TMPDIR", "TMP"):
            for root in (os.path.expanduser("~"), os.getcwd()):
                env = dict(os.environ)
                for name in ("TEMP", "TMPDIR", "TMP", "RESOLVE_MCP_SCRATCH"):
                    env.pop(name, None)
                env[variable] = root
                with self.subTest(variable=variable, root=root), patch.dict(os.environ, env, clear=True):
                    # A fresh interpreter starts with tempfile.tempdir=None, so this tests env selection.
                    selected = subprocess.check_output(
                        [sys.executable, "-c", "import tempfile; print(tempfile.gettempdir())"],
                        text=True, timeout=30,
                    ).strip()
                    self.assertEqual(os.path.normcase(selected), os.path.normcase(root))
                    output = shlex.quote(os.path.join(root, "camera.mov").replace(os.sep, "/"))
                    self.assertEqual(verdict(f"ffmpeg -i source.mov {output}"), "deny")
                    self.assertEqual(verdict(f"rm {output}"), "deny")

    def test_non_windows_does_not_add_an_environment_selected_media_volume(self) -> None:
        guard = runpy.run_path(os.path.join(REPO_ROOT, ".agents", "hooks", "source_media_guard.py"))
        root = os.path.join(os.path.expanduser("~"), "media-volume")
        output = shlex.quote(os.path.join(root, "camera.mov").replace(os.sep, "/"))
        platform_os = SimpleNamespace(**{**vars(os), "name": "posix"})
        with patch.dict(os.environ, {"RESOLVE_MCP_SCRATCH": ""}):
            with patch.dict(guard["is_scratch"].__globals__, {"os": platform_os}), patch.object(tempfile, "tempdir", root):
                self.assertTrue(guard["endangered_targets"](f"ffmpeg -i source.mov {output}"))
                self.assertTrue(guard["endangered_targets"](f"rm {output}"))

    def test_windows_keeps_a_narrow_temp_directory_and_anchored_siblings(self) -> None:
        guard = runpy.run_path(os.path.join(REPO_ROOT, ".agents", "hooks", "source_media_guard.py"))
        root = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp")
        output = shlex.quote(os.path.join(root, "camera.mov").replace(os.sep, "/"))
        sibling = shlex.quote(os.path.join(root + "-media", "camera.mov").replace(os.sep, "/"))
        platform_os = SimpleNamespace(**{**vars(os), "name": "nt"})
        with patch.dict(os.environ, {"RESOLVE_MCP_SCRATCH": ""}):
            with patch.dict(guard["is_scratch"].__globals__, {"os": platform_os}), patch.object(tempfile, "tempdir", root):
                for command in (f"ffmpeg -i source.mov {output}", f"rm {output}"):
                    with self.subTest(command=command):
                        self.assertEqual(guard["endangered_targets"](command), [])
                self.assertTrue(guard["endangered_targets"](f"rm {sibling}"))

    def test_explicit_scratch_opt_in_still_applies_to_a_rejected_temp_root(self) -> None:
        root = os.path.expanduser("~")
        output = shlex.quote(os.path.join(root, "camera.mov").replace(os.sep, "/"))
        with patch.dict(os.environ, {"TEMP": root, "TMPDIR": root, "RESOLVE_MCP_SCRATCH": root}):
            self.assertEqual(verdict(f"ffmpeg -i source.mov {output}", temp_dir=root), "allow")
            self.assertEqual(verdict(f"rm {output}", temp_dir=root), "allow")


if __name__ == "__main__":
    unittest.main()
