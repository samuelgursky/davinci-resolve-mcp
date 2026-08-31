"""Resolve Scripts-menu capability probe: what does THIS edition's API expose?

Run from **Workspace ▸ Scripts ▸ resolve_capability_probe**, on whichever
edition you want to characterise.

The free edition gates *features* (noise reduction, Magic Mask, Super Scale,
some codecs, some resolutions). What it does to the *scripting API* is a
separate question and is not documented anywhere authoritative: a method may be
absent, or present and always return False, or present and work. Those three
cases need completely different handling in a connector, and guessing which is
which is how you ship a tool that lies about what it did.

So this asks the running application, on the edition in front of you.

**Strictly read-only.** It enumerates methods, calls only getters, and creates,
modifies and deletes nothing. Safe to run on a real project — though it reads
whatever project is open, so use a scratch one if you would rather not have your
timeline names in the report.

Writes to ``~/.config/davinci-resolve-mcp/capability-probe-<edition>.json`` and
prints a summary. Self-contained: no repository imports.
"""

import json
import os
import sys
import time

REPORT_DIR = os.path.expanduser("~/.config/davinci-resolve-mcp")

#: Methods worth knowing about, grouped by the object they live on. Chosen for
#: what a connector actually needs, not for completeness.
SURFACE = {
    "Resolve": [
        "GetProductName", "GetVersionString", "GetCurrentPage", "OpenPage",
        "GetProjectManager", "GetMediaStorage", "ImportRenderPreset",
        "ExportRenderPreset", "ImportBurnInPreset", "Quit",
    ],
    "ProjectManager": [
        "GetCurrentProject", "GetProjectListInCurrentFolder", "GetCurrentFolder",
        "GetCurrentDatabase", "GetDatabaseList", "CreateProject", "LoadProject",
        "SaveProject", "CloseProject", "DeleteProject", "ExportProject",
        "ImportProject", "CreateFolder", "ArchiveProject",
    ],
    "Project": [
        "GetName", "GetTimelineCount", "GetTimelineByIndex", "GetCurrentTimeline",
        "SetCurrentTimeline", "GetMediaPool", "GetGallery", "GetSetting",
        "SetSetting", "GetRenderFormats", "GetRenderCodecs",
        "GetCurrentRenderFormatAndCodec", "GetRenderPresetList", "AddRenderJob",
        "StartRendering", "IsRenderingInProgress", "GetRenderJobList",
        "GetQuickExportRenderPresets", "RefreshLUTList", "GetUniqueId",
    ],
    "MediaPool": [
        "GetRootFolder", "GetCurrentFolder", "AddSubFolder", "ImportMedia",
        "CreateEmptyTimeline", "CreateTimelineFromClips", "AppendToTimeline",
        "DeleteTimelines", "DeleteClips", "ImportTimelineFromFile",
        "GetTimelineMatte", "RefreshFolders",
    ],
    "Timeline": [
        "GetName", "SetName", "GetStartFrame", "GetEndFrame", "GetTrackCount",
        "GetItemListInTrack", "GetTrackName", "GetIsTrackEnabled",
        "AddTrack", "DeleteTrack", "AddMarker", "GetMarkers",
        "DuplicateTimeline", "Export", "GetCurrentTimecode", "SetCurrentTimecode",
        "InsertFusionTitleIntoTimeline", "InsertTitleIntoTimeline",
        "CreateSubtitlesFromAudio", "DetectSceneCuts", "GetSetting",
    ],
    "TimelineItem": [
        "GetName", "GetDuration", "GetStart", "GetEnd", "GetProperty",
        "SetProperty", "GetNumNodes", "SetLUT", "GetLUT", "SetCDL",
        "AddMarker", "GetMarkers", "GetFusionCompCount", "AddFusionComp",
        "SetClipEnabled", "GetMediaPoolItem", "CreateMagicMask",
        "SmartReframe", "GetNodeLabel",
    ],
    "MediaPoolItem": [
        "GetName", "GetClipProperty", "SetClipProperty", "GetMetadata",
        "SetMetadata", "GetMediaId", "AddMarker", "GetMarkers", "LinkProxyMedia",
        "TranscribeAudio", "ClearTranscription",
    ],
}

#: Getters that are safe to actually call, to separate "method exists" from
#: "method works". A method can be present and still be inert on this edition.
SAFE_CALLS = {
    "Resolve": ["GetProductName", "GetVersionString", "GetCurrentPage"],
    "ProjectManager": ["GetProjectListInCurrentFolder", "GetCurrentFolder"],
    "Project": [
        "GetName", "GetTimelineCount", "GetRenderFormats",
        "GetCurrentRenderFormatAndCodec", "GetRenderPresetList",
        "IsRenderingInProgress", "GetRenderJobList",
    ],
    "MediaPool": ["GetRootFolder", "GetCurrentFolder"],
    "Timeline": [
        "GetName", "GetStartFrame", "GetEndFrame", "GetCurrentTimecode", "GetMarkers",
    ],
}


def acquire_resolve():
    candidate = globals().get("resolve")
    if candidate is not None:
        return candidate
    bmd = globals().get("bmd")
    if bmd is not None:
        try:
            return bmd.scriptapp("Resolve")
        except Exception:
            return None
    try:
        import DaVinciResolveScript as script_module
        return script_module.scriptapp("Resolve")
    except Exception:
        return None


def classify(obj, names):
    """Which of `names` exist on `obj`."""
    if obj is None:
        return {"reachable": False, "note": "object not sampled in this context",
                "present": [], "missing": sorted(names)}
    present, missing = [], []
    for name in names:
        (present if callable(getattr(obj, name, None)) else missing).append(name)
    return {"reachable": True, "present": sorted(present), "missing": sorted(missing)}


def try_calls(obj, names):
    """Call safe getters; record value shape or the failure. Never mutates."""
    out = {}
    if obj is None:
        return out
    for name in names:
        fn = getattr(obj, name, None)
        if not callable(fn):
            out[name] = {"ok": False, "why": "absent"}
            continue
        try:
            value = fn()
        except Exception as exc:
            out[name] = {"ok": False, "why": "raised: %s" % type(exc).__name__}
            continue
        if value is None:
            out[name] = {"ok": False, "why": "returned None"}
        elif isinstance(value, bool):
            # A bool getter answering False is a real answer, not a failure.
            # Scoring it as one is how "nothing is rendering" reads as "broken".
            out[name] = {"ok": True, "type": "bool", "value": value}
        elif isinstance(value, dict):
            out[name] = {"ok": True, "type": "dict", "size": len(value),
                         "sample": sorted(list(value)[:8])}
        elif isinstance(value, (list, tuple)):
            out[name] = {"ok": True, "type": "list", "size": len(value),
                         "sample": [str(v)[:40] for v in list(value)[:8]]}
        else:
            out[name] = {"ok": True, "type": type(value).__name__, "value": str(value)[:120]}
    return out


def main():
    resolve = acquire_resolve()
    if resolve is None:
        print("Could not get the resolve object. Run this from Workspace > Scripts.")
        return None

    report = {"probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "interpreter": sys.executable}
    try:
        product = resolve.GetProductName()
        report["product"] = product
        report["version"] = resolve.GetVersionString()
        report["edition"] = "studio" if "studio" in str(product).lower() else "free"
    except Exception as exc:
        report["product_error"] = type(exc).__name__
        report["edition"] = "unknown"

    manager = getattr(resolve, "GetProjectManager", lambda: None)()
    project = getattr(manager, "GetCurrentProject", lambda: None)() if manager else None
    pool = getattr(project, "GetMediaPool", lambda: None)() if project else None
    timeline = getattr(project, "GetCurrentTimeline", lambda: None)() if project else None

    item = None
    if timeline is not None:
        try:
            for index in range(1, int(timeline.GetTrackCount("video") or 0) + 1):
                items = timeline.GetItemListInTrack("video", index) or []
                if items:
                    item = items[0]
                    break
        except Exception:
            item = None
    media_item = None
    if pool is not None:
        try:
            clips = pool.GetRootFolder().GetClipList() or []
            media_item = clips[0] if clips else None
        except Exception:
            media_item = None

    objects = {
        "Resolve": resolve, "ProjectManager": manager, "Project": project,
        "MediaPool": pool, "Timeline": timeline, "TimelineItem": item,
        "MediaPoolItem": media_item,
    }
    report["surface"] = {k: classify(objects.get(k), v) for k, v in SURFACE.items()}
    report["calls"] = {k: try_calls(objects.get(k), v) for k, v in SAFE_CALLS.items()}
    report["context"] = {
        "project_open": project is not None,
        "timeline_open": timeline is not None,
        "timeline_item_sampled": item is not None,
        "media_item_sampled": media_item is not None,
    }

    # The render matrix is where free/Studio differ most visibly.
    if project is not None:
        try:
            formats = project.GetRenderFormats() or {}
            matrix = {}
            for label in sorted(formats)[:40]:
                try:
                    codecs = project.GetRenderCodecs(formats[label]) or {}
                    matrix[label] = sorted(codecs)
                except Exception:
                    matrix[label] = ["<error>"]
            report["render_matrix"] = matrix
            report["render_format_count"] = len(formats)
            report["render_pair_count"] = sum(len(v) for v in matrix.values())
        except Exception as exc:
            report["render_matrix_error"] = type(exc).__name__

    edition = report.get("edition", "unknown")
    path = os.path.join(REPORT_DIR, "capability-probe-%s.json" % edition)
    try:
        if not os.path.isdir(REPORT_DIR):
            os.makedirs(REPORT_DIR)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
        written = path
    except (OSError, IOError) as exc:
        written = "could not write (%s)" % type(exc).__name__

    print("=" * 70)
    print("Resolve capability probe - %s %s (%s)" % (
        report.get("product", "?"), report.get("version", "?"), edition))
    print("=" * 70)
    for group, result in report["surface"].items():
        if not result.get("reachable"):
            print("  %-16s not sampled (%s)" % (group, result.get("note")))
            continue
        total = len(result["present"]) + len(result["missing"])
        print("  %-16s %d/%d present" % (group, len(result["present"]), total))
        if result["missing"]:
            print("       missing: %s" % ", ".join(result["missing"]))
    print()
    failed = [(g, n, r["why"]) for g, calls in report["calls"].items()
              for n, r in calls.items() if not r["ok"]]
    print("  safe getter calls: %d ok, %d not" % (
        sum(1 for g, c in report["calls"].items() for r in c.values() if r["ok"]), len(failed)))
    for group, name, why in failed:
        print("       %s.%s -> %s" % (group, name, why))
    if "render_format_count" in report:
        print()
        print("  render matrix: %d formats, %d format/codec pairs" % (
            report["render_format_count"], report["render_pair_count"]))
    print()
    print("  context: %s" % json.dumps(report["context"]))
    print("  report:  %s" % written)
    print("=" * 70)
    return report


main()
