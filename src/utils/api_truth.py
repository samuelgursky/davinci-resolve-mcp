"""Behaviorally-verified facts about the DaVinci Resolve scripting API.

The Resolve scripting API is under-documented and frequently behaves differently
from its apparent signature: methods live on objects you wouldn't expect, return
values lie, string keys are silently rejected, and some documented-looking calls
don't exist. This module records facts we have *verified against live Resolve* so
agents and code can look the reality up instead of rediscovering it the hard way.

Each entry is a small dict. Grow it opportunistically — every readback recipe and
every fix that uncovers a surprising behavior should add an entry. Facts are
stamped with the Resolve build they were verified on so drift is visible when a
new version ships.
"""
from typing import Any, Dict, List, Optional

VERIFIED_ON = "DaVinci Resolve Studio 21.0.0"

# Each entry: symbol, object, reality, recommended, tags. `signature` optional.
API_TRUTH: List[Dict[str, Any]] = [
    {
        "symbol": "MediaPool.AutoSyncAudio",
        "object": "MediaPool",
        "signature": "(clips, settings) -> bool",
        "reality": "The boolean return does not reflect whether clips actually "
                   "linked, and string enum keys in `settings` are silently "
                   "rejected (the call returns False).",
        "recommended": "Resolve the AUDIO_SYNC_* enum constants via the live "
                       "resolve handle, and verify by reading each clip's "
                       "'Synced Audio' property (see verify_by_readback).",
        "tags": ["unreliable-return", "silent-failure", "audio", "enum"],
    },
    {
        "symbol": "Composition.Paste",
        "object": "Fusion Composition",
        "reality": "Passing tool.SaveSettings()'s in-memory table to Paste() / "
                   "LoadSettings() fails across the Python bridge with an "
                   "OrderedDict/null-argument error and creates no node, while "
                   "reporting nothing useful.",
        "recommended": "Duplicate via AddTool(RegID) + SaveSettings(path)/"
                       "LoadSettings(path) through a temp .setting FILE, which "
                       "round-trips reliably. Identify the new node by name diff.",
        "tags": ["fusion", "bridge", "silent-failure"],
    },
    {
        "symbol": "FlowView.SetPos / FlowView.GetPosTable",
        "object": "Fusion FlowView (comp.CurrentFrame.FlowView)",
        "reality": "Node positions are read/written through the FlowView, not the "
                   "tool. SetPos returns nothing reliable; GetPosTable returns a "
                   "1-indexed table (or dict/tuple depending on bridge).",
        "recommended": "Use comp.CurrentFrame.FlowView.SetPos(tool, x, y); confirm "
                       "with GetPosTable and a liberal position parser.",
        "tags": ["fusion", "unreliable-return"],
    },
    {
        "symbol": "Timeline.GetTimelineByName",
        "object": "Project",
        "reality": "Does not exist. Timelines are looked up by index.",
        "recommended": "Iterate GetTimelineByIndex(1..GetTimelineCount()).",
        "tags": ["missing-method", "timeline"],
    },
    {
        "symbol": "Project render methods (AddRenderJob, SetRenderSettings, ...)",
        "object": "Project",
        "reality": "Render methods live on the Project object, not on a separate "
                   "render-settings interface.",
        "recommended": "Call proj.AddRenderJob(), proj.SetRenderSettings(), "
                       "proj.LoadRenderPreset() directly on the project.",
        "tags": ["render"],
    },
    {
        "symbol": "MediaPoolItem.GetClipProperty('Transcription')",
        "object": "MediaPoolItem",
        "reality": "Returns a PREVIEW of the transcription that ends in an "
                   "ellipsis when the full transcript is longer than the property "
                   "exposes.",
        "recommended": "Treat a trailing ellipsis as truncation (see "
                       "media_pool_item get_transcription's `truncated` flag).",
        "tags": ["transcription", "truncation"],
    },
    {
        "symbol": "ProjectManager.CreateProject (with a dirty Untitled project)",
        "object": "ProjectManager",
        "reality": "Returns None and pops a modal 'Save Current Project' dialog "
                   "when the current unsaved/Untitled project blocks the switch. "
                   "SaveProject() on an Untitled project re-triggers the same modal.",
        "recommended": "CloseProject(current) to discard the untitled project "
                       "without a prompt, then CreateProject; restore with "
                       "LoadProject afterward.",
        "tags": ["project", "modal", "silent-failure"],
    },
    {
        "symbol": "Timeline.InsertFusionCompositionIntoTimeline",
        "object": "Timeline",
        "reality": "Reliable way to obtain a Fusion comp on an otherwise empty "
                   "timeline: it inserts a Fusion composition clip whose comp is "
                   "then reachable via GetFusionCompByIndex(1).",
        "recommended": "Use it (rather than InsertGeneratorIntoTimeline) when you "
                       "need a comp to operate on.",
        "tags": ["fusion", "timeline"],
    },
    {
        "symbol": "subprocess inheriting stdin under the MCP stdio server",
        "object": "(server runtime)",
        "reality": "A child process that inherits stdin can race-read bytes off "
                   "the JSON-RPC protocol stream and corrupt it; capture_output "
                   "redirects only stdout/stderr.",
        "recommended": "Pass stdin=subprocess.DEVNULL on every subprocess that can "
                       "run while serving over stdio.",
        "tags": ["runtime", "stdio", "subprocess"],
    },
]


def lookup_api_truth(query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return verified facts matching `query`, or all facts if no query.

    Matches a case-insensitive substring against the symbol, tags, and reality.
    """
    if not query:
        return list(API_TRUTH)
    q = query.lower()
    out = []
    for e in API_TRUTH:
        hay = " ".join([
            e.get("symbol", ""),
            e.get("object", ""),
            e.get("reality", ""),
            " ".join(e.get("tags", [])),
        ]).lower()
        if q in hay:
            out.append(e)
    return out
