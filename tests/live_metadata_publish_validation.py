"""Live validation for publishing analysis back to Resolve clip metadata.

Creates a disposable Resolve project, imports synthetic media, verifies
publish_clip_metadata dry-run behavior, confirms metadata publishing on the
synthetic clip, then cleans up the disposable project and media directory.

Run with:
  venv/bin/python tests/live_metadata_publish_validation.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ok(label: str, condition: bool, detail: Any = None) -> bool:
    status = "PASS" if condition else "FAIL"
    suffix = f" - {detail}" if detail is not None else ""
    print(f"  [{status}] {label}{suffix}")
    return condition


def _require_success(label: str, result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict) or result.get("success") is not True:
        raise AssertionError(f"{label} failed: {result!r}")
    print(f"  [PASS] {label}")
    return result


def _write_synthetic_video(path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=320x180:rate=24:duration=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=2",
        "-c:v",
        "mpeg4",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    subprocess.run(cmd, check=True)


def _cleanup_project(server, project_name: str) -> Dict[str, Any]:
    resolve = server.get_resolve()
    if not resolve:
        return {"success": False, "error": "Resolve unavailable during cleanup"}
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if project:
        try:
            pm.CloseProject(project)
        except Exception:
            pass
    return {"success": bool(pm.DeleteProject(project_name))}


async def main_async() -> int:
    import src.server as server

    print("=" * 72)
    print("Metadata publish live validation")
    print("=" * 72)

    version = server.resolve_control("get_version")
    if "error" in version:
        print(f"FATAL: {version['error']}")
        return 2
    print(f"Connected to {version.get('product')} {version.get('version_string')}")

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("FATAL: ffmpeg/ffprobe are required for this live validation")
        return 2

    project_name = f"_mcp_metadata_publish_validation_{int(time.time())}"
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_metadata_publish_validation_"))
    source_dir = work_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    analysis_root = work_dir / "analysis"
    created_project = False
    try:
        _require_success("project_manager.create", server.project_manager("create", {"name": project_name}))
        created_project = True
        print(f"Created disposable project: {project_name}")

        source = source_dir / "metadata_publish_fixture.mp4"
        _write_synthetic_video(source)
        print(f"Generated synthetic media under: {work_dir}")

        imported = server.media_pool("import_media", {"paths": [str(source)]})
        if imported.get("imported") != 1:
            raise AssertionError(f"media_pool.import_media failed: {imported!r}")
        print("  [PASS] media_pool.import_media")

        clips = server.folder("get_clips").get("clips") or []
        clip_ids: List[str] = [clip.get("id") for clip in clips if clip.get("name") == source.name and clip.get("id")]
        if len(clip_ids) != 1:
            raise AssertionError(f"expected imported clip id, got {clips!r}")
        clip_id = clip_ids[0]
        print("  [PASS] folder.get_clips returned imported clip id")

        seed = server.media_pool_item("set_metadata", {
            "clip_id": clip_id,
            "metadata": {
                "Comments": "Human note before publish.",
                "Keywords": "existing",
                "Scene": "Existing Scene",
            },
        })
        _require_success("seed initial metadata", seed)

        params = {
            "target": {"type": "clip", "clip_id": clip_id},
            "analysis_root": str(analysis_root),
            "depth": "standard",
            "max_analysis_frames": 2,
            "transcription": {
                "enabled": True,
                "backend": "mock",
                "segments": [{"start": 0, "end": 1.0, "text": "Mock transcript for metadata publishing."}],
            },
            "vision": {"enabled": True, "provider": "mock"},
            "fields": ["Description", "Comments", "Keywords", "People", "Scene"],
            "dry_run": True,
        }
        preview = await server.media_analysis("publish_clip_metadata", params)
        _require_success("publish_clip_metadata dry run", preview)
        preview_row = preview["results"][0]
        checks = [
            _ok("dry run does not request confirmation", preview.get("confirmation_required") is False, preview),
            _ok("dry run proposes Description", "Description" in preview_row.get("metadata_writes", {}), preview_row),
            _ok("dry run preserves seeded Scene", not any(
                field.get("field") == "Scene" and field.get("changed")
                for field in preview_row.get("fields") or []
            ), preview_row),
        ]
        metadata_after_preview = server.media_pool_item("get_metadata", {"clip_id": clip_id}).get("metadata") or {}
        checks.append(_ok("dry run left Comments untouched", metadata_after_preview.get("Comments") == "Human note before publish.", metadata_after_preview))

        write_params = dict(params)
        write_params.update({"dry_run": False, "confirm": True, "persist": True})
        applied = await server.media_analysis("publish_clip_metadata", write_params)
        _require_success("publish_clip_metadata confirmed", applied)

        metadata = server.media_pool_item("get_metadata", {"clip_id": clip_id}).get("metadata") or {}
        third_party = server.media_pool_item("get_third_party_metadata", {"clip_id": clip_id}).get("metadata") or {}
        checks.extend([
            _ok("confirmed publish kept human comment", "Human note before publish." in str(metadata.get("Comments", "")), metadata),
            _ok("confirmed publish added MCP block", "DaVinci Resolve MCP Analysis" in str(metadata.get("Comments", "")), metadata),
            _ok("confirmed publish preserved existing Scene", metadata.get("Scene") == "Existing Scene", metadata),
            _ok("confirmed publish merged keywords", "existing" in str(metadata.get("Keywords", "")), metadata),
            _ok("third-party provenance has analysis signature", bool(third_party.get("davinci_resolve_mcp.analysis_signature")), third_party),
        ])
        return 0 if all(checks) else 1
    except Exception as exc:
        print(f"FATAL: {exc}")
        return 2
    finally:
        if created_project:
            cleanup = _cleanup_project(server, project_name)
            print(f"Cleanup project: {cleanup!r}")
        shutil.rmtree(work_dir, ignore_errors=True)
        print(f"Removed synthetic media directory: {work_dir}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
