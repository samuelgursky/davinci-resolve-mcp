"""Restart-free subtitle preset edits through native DRT export/import.

The source timeline and source media are retained. Never patch Project.db here.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from src.utils.resolve_writes import set_current_timeline, describe_switch_failure
from src.utils.title_library import find_subtitle_preset

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "scripts" / "edit_subtitle_timeline.mjs"


def _capture_installed_preset(resolve, project, preset, output):
    """Ask running Resolve to serialize its installed template, in our own timeline."""
    original = project.GetCurrentTimeline()
    pool = project.GetMediaPool()
    capture = pool.CreateEmptyTimeline(f"MCP preset capture {uuid.uuid4().hex[:8]}")
    if not capture:
        raise RuntimeError("Failed to create isolated preset capture timeline")
    try:
        selected, detail = set_current_timeline(project, capture)
        if not selected:
            raise RuntimeError(describe_switch_failure(detail, "selecting preset capture"))
        item = capture.InsertFusionTitleIntoTimeline(preset["template_id"])
        if not item:
            raise RuntimeError("Resolve refused the installed subtitle template")
        comp = item.GetFusionCompByIndex(1)
        if not comp or comp.GetData("TEMPLATE_ID") != preset["template_id"]:
            raise RuntimeError("Resolve inserted a different template; refusing ambiguous preset")
        if not capture.Export(str(output), resolve.EXPORT_DRT):
            raise RuntimeError("Native preset capture export failed")
    finally:
        restored, detail = set_current_timeline(project, original)
        if not restored:
            raise RuntimeError(describe_switch_failure(detail, "restoring timeline after preset capture"))
        # Only delete the empty capture timeline created by this call, never a user timeline.
        if not pool.DeleteTimelines([capture]):
            raise RuntimeError(f"Preset capture cleanup refused; retained {capture.GetName()}")


def _inventory(timeline):
    """Check the whole edit, not just the preset blob that was changed."""
    result = {}
    for kind in ("video", "audio", "subtitle"):
        tracks = []
        for index in range(1, int(timeline.GetTrackCount(kind) or 0) + 1):
            items = []
            for item in timeline.GetItemListInTrack(kind, index) or []:
                media = item.GetMediaPoolItem()
                items.append((item.GetName(), item.GetStart(), item.GetEnd(),
                              media.GetMediaId() if media else None))
            tracks.append(items)
        result[kind] = tracks
    return result


def set_subtitle_preset(resolve, project, timeline, params, safe_dir):
    """Create and select a verified revision; restore original on any failure."""
    node = shutil.which("node")
    if not node:
        return {"success": False, "error": "Node.js is required for the subtitle preset codec"}
    inputs = params.get("inputs", {})
    if not isinstance(inputs, dict):
        return {"success": False, "error": "inputs must be an object"}
    track = params.get("track", 1)
    if isinstance(track, bool) or not isinstance(track, int) or not 1 <= track <= timeline.GetTrackCount("subtitle"):
        return {"success": False, "error": "Subtitle track index out of range"}
    reference = params.get("preset_reference")
    if reference and not Path(reference).is_file():
        return {"success": False, "error": "preset_reference must be an existing native DRT export"}
    installed = None
    if params.get("preset") not in (None, "Word Highlight", "Lollipop") and not reference:
        try:
            installed = find_subtitle_preset(params["preset"], params.get("templates_archive"))
        except (OSError, ValueError) as exc:
            return {"success": False, "error": str(exc)}
        if params.get("dry_run") is True:
            return {"success": False, "error": "Uncached installed preset capture needs a live temporary timeline; use preset_reference for a mutation-free dry run"}
    name = params.get("revision_name") or f"{timeline.GetName()} - subtitles {uuid.uuid4().hex[:8]}"
    if any(project.GetTimelineByIndex(i).GetName() == name for i in range(1, project.GetTimelineCount() + 1)):
        return {"success": False, "error": "revision_name already exists"}
    staging = Path(safe_dir(str(ROOT / "logs" / "subtitle-live"))) / uuid.uuid4().hex
    staging.mkdir(parents=True, exist_ok=False)
    source, output = staging / "original.drt", staging / "revision.drt"
    original_active = project.GetCurrentTimeline()
    original_timecode = timeline.GetCurrentTimecode()
    before = _inventory(timeline)
    imported = None
    succeeded = False
    result = None
    try:
        if not timeline.Export(str(source), resolve.EXPORT_DRT):
            raise RuntimeError("Native timeline export failed")
        request = {"source": str(source), "output": str(output), "track": track, "inputs": inputs}
        if installed:
            captured = staging / "installed-title.drt"
            _capture_installed_preset(resolve, project, installed, captured)
            request.update(title_reference=str(captured), template_id=installed["template_id"])
        if reference:
            request.update(preset_reference=os.path.abspath(reference), reference_track=params.get("reference_track", 1))
        if params.get("preset") and not reference:
            request["preset"] = params["preset"]
        completed = subprocess.run([node, str(BRIDGE)], input=json.dumps(request),
                                   capture_output=True, text=True, timeout=60, check=False)
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "Subtitle codec failed")
        patch = json.loads(completed.stdout)
        if params.get("dry_run") is True:
            result = {"success": True, "dry_run": True, "executed": False, "patch": patch,
                      "original_export": str(source), "restart_required": False}
            return result
        # Native imports remap IDs and carry the original media references.
        imported = project.GetMediaPool().ImportTimelineFromFile(str(output), {"importSourceClips": False})
        if not imported:
            raise RuntimeError("Resolve refused the patched native timeline")
        if _inventory(imported) != before:
            raise RuntimeError("Imported edit differs in track counts, clip/caption names, bounds or media IDs")
        if not imported.SetName(name):
            raise RuntimeError("Failed to name subtitle revision")
        if imported.GetName() != name:
            raise RuntimeError("Subtitle revision name did not persist")
        # Re-export through Resolve to prove that it parsed and retained the
        # preset. The codec's own pre-import readback alone is insufficient.
        readback = staging / "resolve-readback.drt"
        if not imported.Export(str(readback), resolve.EXPORT_DRT):
            raise RuntimeError("Failed to re-export the imported subtitle revision")
        checked = subprocess.run([node, str(BRIDGE)],
                                 input=json.dumps({"operation": "inspect", "source": str(readback), "track": track}),
                                 capture_output=True, text=True, timeout=60, check=False)
        if checked.returncode:
            raise RuntimeError(checked.stderr.strip() or "Imported preset readback failed")
        actual = json.loads(checked.stdout)
        if actual.get("templateId") != patch.get("templateId") or actual.get("inputs") != patch.get("after"):
            raise RuntimeError("Resolve did not retain the requested subtitle controls")
        selected, detail = set_current_timeline(project, imported)
        if not selected:
            raise RuntimeError(describe_switch_failure(detail, "selecting subtitle revision"))
        warnings = []
        if original_timecode:
            if not imported.SetCurrentTimecode(original_timecode) or imported.GetCurrentTimecode() != original_timecode:
                warnings.append("Subtitle revision was selected, but its playhead could not be restored")
        succeeded = True
        result = {"success": True, "restart_required": False, "original_timeline": timeline.GetName(),
                "timeline": imported.GetName(), "timeline_id": imported.GetUniqueId(),
                "original_export": str(source), "patched_export": str(output), "patch": patch,
                "verification": "resolve_reexport_preset_readback_and_live_edit_inventory",
                "render_verified": False}
        if warnings:
            result["warnings"] = warnings
        return result
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {"success": False, "error": str(exc), "restart_required": False,
                  "original_export": str(source),
                  "failed_revision": imported.GetName() if imported else None}
        return result
    finally:
        # A failed or preview operation must leave the user's working timeline active.
        if not succeeded:
            restored, detail = set_current_timeline(project, original_active)
            if not restored:
                # Do not silently claim that a failed call restored the session.
                # The original timeline is retained even if selection is refused.
                message = describe_switch_failure(detail, "restoring original timeline")
                logging.getLogger(__name__).error(message)
                if result is not None:
                    result.setdefault("warnings", []).append(message)
