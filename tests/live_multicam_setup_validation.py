"""Live validation harness for the multicam setup helper.

Creates a disposable Resolve project, generates synthetic media, imports it,
and validates that media_pool.setup_multicam_timeline creates a stacked prep
timeline with one angle per video track and optional matching audio tracks.

Run with:
  python3.11 tests/live_multicam_setup_validation.py
"""

from __future__ import annotations

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


def _run_ffmpeg(args: List[str]) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args], check=True)


def _make_synthetic_media(work_dir: Path) -> List[str]:
    paths = []
    for name, video_filter, frequency in (
        ("camera_a.mov", "testsrc2=size=320x180:rate=24:duration=4", 880),
        ("camera_b.mov", "testsrc=size=320x180:rate=24:duration=4", 660),
    ):
        path = work_dir / name
        _run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                video_filter,
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration=4",
                "-shortest",
                "-pix_fmt",
                "yuv420p",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-y",
                str(path),
            ]
        )
        paths.append(str(path))
    return paths


def _ok(label: str, condition: bool, detail: Any = None) -> bool:
    status = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail is not None else ""
    print(f"  [{status}] {label}{suffix}")
    return condition


def _require_success(label: str, result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict) or result.get("success") is not True:
        raise AssertionError(f"{label} failed: {result!r}")
    print(f"  [PASS] {label}")
    return result


def _require_imported_clips(server, expected_names: List[str]) -> List[str]:
    imported = server.media_pool("import_media", {"paths": expected_names})
    if not isinstance(imported, dict) or imported.get("imported") != len(expected_names):
        raise AssertionError(f"media_pool.import_media failed: {imported!r}")
    print("  [PASS] media_pool.import_media")

    current_clips = server.folder("get_clips")
    clips = current_clips.get("clips") if isinstance(current_clips, dict) else None
    if not isinstance(clips, list):
        raise AssertionError(f"folder.get_clips failed after import: {current_clips!r}")

    expected_basenames = {Path(path).name for path in expected_names}
    clip_ids = [
        clip.get("id")
        for clip in clips
        if clip.get("name") in expected_basenames and clip.get("id")
    ]
    if len(clip_ids) != len(expected_names):
        raise AssertionError(f"expected imported clip ids for {expected_basenames}, got {current_clips!r}")
    print("  [PASS] folder.get_clips returned imported clip ids")
    return clip_ids


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


def main() -> int:
    import src.server as server

    print("=" * 72)
    print("Multicam setup live validation")
    print("=" * 72)

    version = server.resolve_control("get_version")
    if "error" in version:
        print(f"FATAL: {version['error']}")
        return 2
    print(f"Connected to {version.get('product')} {version.get('version_string')}")

    project_name = f"_mcp_multicam_setup_validation_{int(time.time())}"
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_multicam_setup_validation_"))
    created_project = False
    try:
        _require_success("project_manager.create", server.project_manager("create", {"name": project_name}))
        created_project = True
        print(f"Created disposable project: {project_name}")

        paths = _make_synthetic_media(work_dir)
        print(f"Generated synthetic media under: {work_dir}")

        clip_ids = _require_imported_clips(server, paths)

        dry_run = _require_success(
            "media_pool.setup_multicam_timeline dry_run",
            server.media_pool(
                "setup_multicam_timeline",
                {
                    "name": "Multicam Live Prep Dry Run",
                    "clip_ids": clip_ids,
                    "include_audio": True,
                    "dry_run": True,
                },
            ),
        )
        checks = [
            _ok("dry_run reports no native multicam API", dry_run.get("native_multicam_api") is False),
            _ok("dry_run would append video+audio rows", dry_run.get("would_append") == 4, dry_run.get("would_append")),
            _ok("dry_run plans two video tracks", dry_run.get("max_video_track") == 2, dry_run.get("max_video_track")),
            _ok("dry_run returns Resolve 20 manual reference", "Resolve 20 Manual" in str(dry_run.get("manual_reference"))),
        ]

        setup = _require_success(
            "media_pool.setup_multicam_timeline execute",
            server.media_pool(
                "setup_multicam_timeline",
                {
                    "name": "Multicam Live Prep",
                    "clip_ids": clip_ids,
                    "include_audio": True,
                    "start_timecode": "01:00:00:00",
                },
            ),
        )
        current = server.timeline("get_current")
        video_tracks = server.timeline("get_track_count", {"track_type": "video"})
        audio_tracks = server.timeline("get_track_count", {"track_type": "audio"})
        checks.extend(
            [
                _ok("created setup timeline is current", current.get("name") == "Multicam Live Prep", current),
                _ok("execution returned four appended rows", len(setup.get("items") or []) == 4),
                _ok("timeline has two video tracks", video_tracks.get("count", 0) >= 2, video_tracks),
                _ok("timeline has two audio tracks", audio_tracks.get("count", 0) >= 2, audio_tracks),
                _ok("helper still reports UI conversion boundary", setup.get("native_multicam_created") is False),
            ]
        )
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
    raise SystemExit(main())
