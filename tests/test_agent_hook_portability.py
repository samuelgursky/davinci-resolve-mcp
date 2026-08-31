"""Both host adapters must enforce the same canonical hook policies."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]


def run_hook(host: str, hook: str, payload: dict) -> dict:
    path = ROOT / f".{host}" / "hooks" / hook
    process = subprocess.run(
        [sys.executable, str(path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if process.returncode != 0:
        raise AssertionError(f"{path} exited {process.returncode}: {process.stderr}")
    return json.loads(process.stdout) if process.stdout.strip() else {}


def permission(output: dict) -> str | None:
    return output.get("hookSpecificOutput", {}).get("permissionDecision")


class SourceMediaAdapterTests(unittest.TestCase):
    def test_both_hosts_block_a_source_media_delete(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rm /Volumes/CARD/camera.mov"},
        }
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.assertEqual(permission(run_hook(host, "source_media_guard.py", payload)), "deny")

    def test_codex_session_scratch_is_safe(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ffmpeg -i camera.mov /work/codex-123/proxy.mov"},
        }
        self.assertEqual(run_hook("codex", "source_media_guard.py", payload), {})


class FrameEvidenceAdapterTests(unittest.TestCase):
    def test_codex_records_posttool_image_evidence_for_the_session(self) -> None:
        session = f"portability-{uuid.uuid4()}"
        observed = {
            "session_id": session,
            "hook_event_name": "PostToolUse",
            "tool_name": "view_image",
            "tool_input": {"path": "/tmp/reference.png"},
        }
        self.assertEqual(run_hook("codex", "frame_verification_guard.py", observed), {})

        apply_grade = {
            "session_id": session,
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__davinci-resolve__timeline_item_color",
            "tool_input": {"action": "safe_set_cdl", "params": {}},
        }
        self.assertEqual(run_hook("codex", "frame_verification_guard.py", apply_grade), {})

    def test_missing_evidence_is_denied_in_both_hosts(self) -> None:
        for host in ("claude", "codex"):
            payload = {
                "session_id": f"missing-{uuid.uuid4()}",
                "hook_event_name": "PreToolUse",
                "tool_name": "mcp__davinci-resolve__timeline_item_color",
                "tool_input": {"action": "safe_apply_drx", "params": {}},
            }
            with self.subTest(host=host):
                self.assertEqual(
                    permission(run_hook(host, "frame_verification_guard.py", payload)),
                    "deny",
                )

    def test_codex_bulk_apply_preserves_server_confirmation_as_context(self) -> None:
        session = f"bulk-{uuid.uuid4()}"
        run_hook(
            "codex",
            "frame_verification_guard.py",
            {
                "session_id": session,
                "hook_event_name": "PostToolUse",
                "tool_name": "mcp__davinci-resolve__gallery_stills",
                "tool_input": {"action": "grab_and_export"},
            },
        )
        output = run_hook(
            "codex",
            "frame_verification_guard.py",
            {
                "session_id": session,
                "hook_event_name": "PreToolUse",
                "tool_name": "mcp__davinci-resolve__timeline_item_color",
                "tool_input": {"action": "safe_copy_grade", "params": {}},
            },
        )
        specific = output["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", specific)
        self.assertIn("confirmation", specific["additionalContext"])


class EditedPathProtocolTests(unittest.TestCase):
    def test_apply_patch_paths_are_extracted_from_codex_command_input(self) -> None:
        runtime_path = ROOT / ".agents" / "hooks" / "hook_runtime.py"
        spec = importlib.util.spec_from_file_location("agent_hook_runtime", runtime_path)
        assert spec and spec.loader
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        event = {
            "cwd": str(ROOT),
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: src/server.py\n*** End Patch"
            },
        }
        self.assertEqual(runtime.edited_paths(event), [str((ROOT / "src/server.py").resolve())])


if __name__ == "__main__":
    unittest.main()
