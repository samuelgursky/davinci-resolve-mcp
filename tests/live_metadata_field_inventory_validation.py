#!/usr/bin/env python3
"""Live validation for Resolve metadata field inventory.

Creates a disposable Resolve project, imports synthetic media, compares the
metadata field surfaces exposed by GetClipProperty(""), GetMetadata(""), and
MediaPool.ExportMetadata(), then checks SetMetadata readback for text-like
fields on the disposable clip.

Run with:
  venv/bin/python tests/live_metadata_field_inventory_validation.py
  venv/bin/python tests/live_metadata_field_inventory_validation.py --keep-open

Use a Resolve scripting-compatible Python 3.10-3.12 environment.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


READ_ONLY_FIELD_HINTS = {
    "Audio Bit Depth",
    "Audio Ch",
    "Audio Codec",
    "Bit Depth",
    "Clip Directory",
    "Cloud Sync",
    "Data Level",
    "Date Added",
    "Date Created",
    "Date Modified",
    "Drop frame",
    "Duration",
    "End",
    "End TC",
    "File Name",
    "File Path",
    "Format",
    "FPS",
    "Frames",
    "Online Status",
    "Proxy",
    "Proxy Media Path",
    "Resolution",
    "Sample Rate",
    "Slate TC",
    "Start",
    "Start TC",
    "Super Scale",
    "SuperScale Noise Reduction",
    "SuperScale Sharpness",
    "Transcription Status",
    "Type",
    "Video Codec",
}


UNSAFE_TO_PROBE_WITH_SET_METADATA = {
    "Clip Name",
    "Clip Color",
    "Flags",
    "Good Take",
}


PREFERRED_ANALYSIS_FIELDS = [
    "Description",
    "Comments",
    "Keywords",
    "Keyword",
    "People",
    "Scene",
    "Shot",
    "Take",
    "Camera #",
    "Roll/Card",
    "Roll Card #",
    "Location",
    "Audio Notes",
    "VFX Notes",
    "Reviewers Notes",
]


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


def _read_csv_header(path: Path) -> List[str]:
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.reader(handle)
                for row in reader:
                    return [str(item).strip() for item in row if str(item).strip()]
        except UnicodeDecodeError:
            continue
    return []


def _is_safe_metadata_probe_field(field: str) -> bool:
    if not field:
        return False
    if field in UNSAFE_TO_PROBE_WITH_SET_METADATA:
        return False
    if field in READ_ONLY_FIELD_HINTS:
        return False
    if field.startswith("Track "):
        return True
    return True


def _ordered_unique(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _probe_set_metadata(clip, fields: List[str]) -> Dict[str, Any]:
    rows = []
    for index, field in enumerate(fields, 1):
        if not _is_safe_metadata_probe_field(field):
            rows.append({"field": field, "tested": False, "reason": "skipped_read_only_or_non_text"})
            continue
        value = f"mcp metadata probe {index:03d}"
        try:
            set_ok = bool(clip.SetMetadata(field, value))
        except Exception as exc:
            rows.append({"field": field, "tested": True, "set_ok": False, "error": str(exc)})
            continue
        try:
            readback = clip.GetMetadata(field)
        except Exception as exc:
            readback = None
            rows.append({
                "field": field,
                "tested": True,
                "set_ok": set_ok,
                "readback_ok": False,
                "readback_error": str(exc),
            })
            continue
        rows.append({
            "field": field,
            "tested": True,
            "set_ok": set_ok,
            "readback_ok": str(readback or "") == value,
            "readback": readback,
        })
    tested = [row for row in rows if row.get("tested")]
    readback_ok = [row for row in tested if row.get("readback_ok")]
    set_ok_only = [row for row in tested if row.get("set_ok") and not row.get("readback_ok")]
    failed = [row for row in tested if not row.get("set_ok")]
    return {
        "tested_count": len(tested),
        "readback_ok_count": len(readback_ok),
        "set_ok_without_readback_count": len(set_ok_only),
        "failed_count": len(failed),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Resolve metadata field inventory validation")
    parser.add_argument("--keep-open", action="store_true", help="Leave the disposable project open.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for JSON/CSV reports.")
    parser.add_argument(
        "--full-writeability",
        action="store_true",
        help="Probe SetMetadata readback for all non-read-only observed fields instead of the preferred set.",
    )
    args = parser.parse_args()

    import src.server as server

    print("=" * 72)
    print("Metadata field inventory live validation")
    print("=" * 72)

    version = server.resolve_control("get_version")
    if "error" in version:
        print(f"FATAL: {version['error']}")
        return 2
    print(f"Connected to {version.get('product')} {version.get('version_string')}")

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("FATAL: ffmpeg/ffprobe are required for this live validation")
        return 2

    project_name = f"_mcp_metadata_field_inventory_{int(time.time())}"
    work_dir = Path(tempfile.mkdtemp(prefix="mcp_metadata_field_inventory_"))
    output_dir = args.output_dir or (work_dir / "report")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = work_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    created_project = False

    try:
        _require_success("project_manager.create", server.project_manager("create", {"name": project_name}))
        created_project = True

        source = source_dir / "metadata_field_inventory_fixture.mp4"
        _write_synthetic_video(source)
        print(f"Generated synthetic media under: {work_dir}")

        imported = server.media_pool("import_media", {"paths": [str(source)]})
        if imported.get("imported") != 1:
            raise AssertionError(f"media_pool.import_media failed: {imported!r}")
        print("  [PASS] media_pool.import_media")

        clips = server.folder("get_clips").get("clips") or []
        clip_ids = [clip.get("id") for clip in clips if clip.get("name") == source.name and clip.get("id")]
        if len(clip_ids) != 1:
            raise AssertionError(f"expected imported clip id, got {clips!r}")
        clip_id = clip_ids[0]

        inventory = server.media_pool("metadata_field_inventory", {
            "clip_ids": [clip_id],
            "include_values": True,
        })
        _require_success("metadata_field_inventory", inventory)
        item = inventory["items"][0]
        property_fields = item["clip_properties"]["fields"]

        export_path = output_dir / "resolve_export_metadata.csv"
        exported = server.media_pool("export_metadata", {"path": str(export_path), "clip_ids": [clip_id]})
        if exported.get("success") is not True:
            raise AssertionError(f"media_pool.export_metadata failed: {exported!r}")
        export_fields = _read_csv_header(export_path)
        print("  [PASS] media_pool.export_metadata")

        root = server.get_resolve().GetProjectManager().GetCurrentProject().GetMediaPool().GetRootFolder()
        clip = server._find_clip(root, clip_id)
        if clip is None:
            raise AssertionError(f"clip not found for writeability probe: {clip_id}")

        preferred_candidates = _ordered_unique(
            [field for field in PREFERRED_ANALYSIS_FIELDS if field in set(property_fields) | set(export_fields)]
        )
        writeability_fields = (
            _ordered_unique(field for field in property_fields if _is_safe_metadata_probe_field(field))
            if args.full_writeability
            else preferred_candidates
        )
        writeability = _probe_set_metadata(clip, writeability_fields)

        report = {
            "success": True,
            "project_name": project_name,
            "resolve_version": version,
            "clip_id": clip_id,
            "clip_name": source.name,
            "source_safe": {
                "synthetic_media_only": True,
                "source_media_modified": False,
                "writes": "Resolve project metadata on disposable synthetic clip only",
            },
            "field_counts": {
                "get_metadata": item["metadata"]["field_count"],
                "get_third_party_metadata": item["third_party_metadata"]["field_count"],
                "get_clip_property": item["clip_properties"]["field_count"],
                "export_metadata_header": len(export_fields),
            },
            "field_surface_comparison": {
                "clip_property_not_in_export": sorted(set(property_fields) - set(export_fields)),
                "export_not_in_clip_property": sorted(set(export_fields) - set(property_fields)),
            },
            "inventory": inventory,
            "export_metadata_header": export_fields,
            "set_metadata_writeability": writeability,
        }

        report_path = output_dir / "metadata_field_inventory_report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        checks = [
            _ok("GetClipProperty exposes fields", item["clip_properties"]["field_count"] > 0, item["field_counts"] if "field_counts" in item else None),
            _ok("ExportMetadata produced a header", len(export_fields) > 0, len(export_fields)),
            _ok("analysis writeback fields are represented", all(
                row.get("in_clip_properties") or row.get("in_get_metadata")
                for row in item["analysis_writeback_fields"]["default"]
            ), item["analysis_writeback_fields"]["default"]),
            _ok("preferred SetMetadata probes read back", writeability["readback_ok_count"] >= max(1, len(preferred_candidates) // 2), writeability),
        ]
        print(f"Wrote report: {report_path}")
        print(f"Export CSV: {export_path}")
        return 0 if all(checks) else 1
    except Exception as exc:
        print(f"FATAL: {exc}")
        return 2
    finally:
        if created_project and not args.keep_open:
            cleanup = _cleanup_project(server, project_name)
            print(f"Cleanup project: {cleanup!r}")
        elif args.keep_open:
            print(f"Kept disposable project open: {project_name}")
        if not args.output_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
            print(f"Removed synthetic media/report directory: {work_dir}")
        else:
            shutil.rmtree(source_dir, ignore_errors=True)
            print(f"Removed synthetic source directory: {source_dir}")


if __name__ == "__main__":
    raise SystemExit(main())
