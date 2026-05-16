"""Live validation for sync-event detection and confirmed marker writes.

Creates a disposable Resolve project, imports synthetic audio with a 2-pop and
slate clap, verifies source-safe detection, verifies marker writes are refused
without confirmation, then confirms Media Pool item marker creation.

Run with:
  venv/bin/python tests/live_sync_event_validation.py
"""

from __future__ import annotations

import asyncio
import math
import os
import shutil
import struct
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Dict, List


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def _write_sync_fixture(path: Path, sample_rate: int = 16000) -> None:
    duration_seconds = 6.0
    samples = [0.0] * int(sample_rate * duration_seconds)

    pop_start = int(2.0 * sample_rate)
    pop_length = int((1.0 / 24.0) * sample_rate)
    for index in range(pop_length):
        samples[pop_start + index] = 0.75 * math.sin(2.0 * math.pi * 1000.0 * (index / sample_rate))

    clap_start = int(4.0 * sample_rate)
    samples[clap_start] = 0.95
    samples[clap_start + 1] = -0.85
    samples[clap_start + 3] = 0.55

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for sample in samples:
            clipped = max(-1.0, min(1.0, sample))
            frames.extend(struct.pack("<h", int(clipped * 32767)))
        handle.writeframes(bytes(frames))


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
    print("Sync event live validation")
    print("=" * 72)

    version = server.resolve_control("get_version")
    if "error" in version:
        print(f"FATAL: {version['error']}")
        return 2
    print(f"Connected to {version.get('product')} {version.get('version_string')}")

    project_name = f"_mcp_sync_event_validation_{int(time.time())}"
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_sync_event_validation_"))
    created_project = False
    try:
        _require_success("project_manager.create", server.project_manager("create", {"name": project_name}))
        created_project = True
        print(f"Created disposable project: {project_name}")

        source = work_dir / "sync_event_fixture.wav"
        _write_sync_fixture(source)
        print(f"Generated synthetic audio under: {work_dir}")

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

        detection = await server.media_analysis(
            "detect_sync_events",
            {
                "target": {"type": "clip", "clip_id": clip_id},
                "fps": 24,
                "scan_start_seconds": 6,
                "scan_tail_seconds": 0,
            },
        )
        _require_success("media_analysis.detect_sync_events", detection)
        events = (detection.get("files") or [{}])[0].get("events") or []
        suggestions = (detection.get("files") or [{}])[0].get("marker_suggestions") or []
        checks = [
            _ok("detected a 2-pop", any(event.get("type") == "two_pop" for event in events), events),
            _ok("detected a slate clap", any(event.get("type") == "slate_clap" for event in events), events),
            _ok("returned marker suggestions", bool(suggestions), suggestions),
            _ok("marker suggestions require confirmation", all(s.get("requires_confirmation") for s in suggestions), suggestions),
        ]

        preview = await server.media_analysis("add_sync_event_markers", {"detection": detection})
        checks.append(_ok("marker write refused without confirmation", preview.get("confirmation_required") is True, preview))

        applied = await server.media_analysis("add_sync_event_markers", {"detection": detection, "confirm": True})
        _require_success("media_analysis.add_sync_event_markers confirmed", applied)
        markers = server.media_pool_item_markers("get_all", {"clip_id": clip_id}).get("markers") or {}
        checks.extend([
            _ok("confirmed marker write added markers", applied.get("added", 0) >= 1, applied),
            _ok("media pool clip has markers", bool(markers), markers),
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

