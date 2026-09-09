"""Native Resolve 21.1 discovery and editing controls."""
from src.utils.resolve211_edits import validate_edit_options, validate_transition_options, transition_result
from src.granular.common import (
    mcp, READ_ONLY_TOOL, WRITE_TOOL, DESTRUCTIVE_TOOL, get_resolve, get_current_project,
    _get_timeline, _get_timeline_item, _requires_method, has_method,
)


@mcp.tool(annotations=READ_ONLY_TOOL)
def is_resolve_studio() -> dict:
    """Read IsStudio (documented on Resolve 21.1+)."""
    r = get_resolve()
    if r is None:
        return {"error": "Not connected to DaVinci Resolve"}
    if not has_method(r, "IsStudio"):
        return {"error": "IsStudio is unavailable on this Resolve build"}
    return {"is_studio": r.IsStudio()}

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_keyboard_presets() -> dict:
    """Read GetKeyboardPresetList (documented on Resolve 21.1+)."""
    r = get_resolve()
    if r is None:
        return {"error": "Not connected to DaVinci Resolve"}
    missing = _requires_method(r, "GetKeyboardPresetList", "21.1")
    if missing:
        return missing
    return {"presets": r.GetKeyboardPresetList()}

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_current_keyboard_preset() -> dict:
    """Read GetCurrentKeyboardPreset (documented on Resolve 21.1+)."""
    r = get_resolve()
    if r is None:
        return {"error": "Not connected to DaVinci Resolve"}
    missing = _requires_method(r, "GetCurrentKeyboardPreset", "21.1")
    if missing:
        return missing
    return {"name": r.GetCurrentKeyboardPreset()}

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_project_settings_presets() -> dict:
    """Read GetProjectSettingsPresetList (documented on Resolve 21.1+)."""
    _, proj = get_current_project()
    if proj is None:
        return {"error": "No project currently open"}
    missing = _requires_method(proj, "GetProjectSettingsPresetList", "21.1")
    if missing:
        return missing
    return {"presets": proj.GetProjectSettingsPresetList()}


@mcp.tool(annotations=READ_ONLY_TOOL)
def get_audio_render_formats() -> dict:
    """Read GetAudioRenderFormats (documented on Resolve 21.1+)."""
    _, proj = get_current_project()
    if proj is None:
        return {"error": "No project currently open"}
    missing = _requires_method(proj, "GetAudioRenderFormats", "21.1")
    if missing:
        return missing
    return {"formats": proj.GetAudioRenderFormats()}

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_audio_render_codecs(format: str) -> dict:
    """Read GetAudioRenderCodecs (documented on Resolve 21.1+). Pass an audio file extension such as wav."""
    if not isinstance(format, str) or not format.strip():
        return {"error": "get_audio_codecs requires a non-empty format string"}
    _, proj = get_current_project()
    if proj is None:
        return {"error": "No project currently open"}
    missing = _requires_method(proj, "GetAudioRenderCodecs", "21.1")
    if missing:
        return missing
    return {"codecs": proj.GetAudioRenderCodecs(format)}

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_normalize_audio_modes() -> dict:
    """Read GetNormalizeAudioModes (documented on Resolve 21.1+)."""
    _, tl, error = _get_timeline()
    if error:
        return error
    missing = _requires_method(tl, "GetNormalizeAudioModes", "21.1")
    if missing:
        return missing
    return {"modes": tl.GetNormalizeAudioModes()}

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_timeline_output_blanking() -> dict:
    """Read GetOutputBlanking (documented on Resolve 21.1+). Pixel coordinates; clips inheriting timeline blanking return an empty dict."""
    _, tl, error = _get_timeline()
    if error:
        return error
    missing = _requires_method(tl, "GetOutputBlanking", "21.1")
    if missing:
        return missing
    return {"blanking": tl.GetOutputBlanking()}

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_timeline_item_speed(track_type: str = "video", track_index: int = 1, item_index: int = 0) -> dict:
    """Read GetSpeed (documented on Resolve 21.1+)."""
    if track_type not in ("video", "audio") or track_index < 1 or item_index < 0:
        return {"error": "Use video/audio, a 1-based track index and a non-negative item index"}
    item, error = _get_timeline_item(track_type, track_index, item_index)
    if error:
        return error
    missing = _requires_method(item, "GetSpeed", "21.1")
    if missing:
        return missing
    return {"speed": item.GetSpeed()}

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_timeline_item_fades(track_type: str = "video", track_index: int = 1, item_index: int = 0) -> dict:
    """Read GetFades (documented on Resolve 21.1+). Durations are in frames."""
    if track_type not in ("video", "audio") or track_index < 1 or item_index < 0:
        return {"error": "Use video/audio, a 1-based track index and a non-negative item index"}
    item, error = _get_timeline_item(track_type, track_index, item_index)
    if error:
        return error
    missing = _requires_method(item, "GetFades", "21.1")
    if missing:
        return missing
    return {"fades": item.GetFades()}

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_timeline_item_output_blanking(track_type: str = "video", track_index: int = 1, item_index: int = 0) -> dict:
    """Read GetOutputBlanking (documented on Resolve 21.1+). Pixel coordinates; clips inheriting timeline blanking return an empty dict."""
    if track_type not in ("video", "audio") or track_index < 1 or item_index < 0:
        return {"error": "Use video/audio, a 1-based track index and a non-negative item index"}
    item, error = _get_timeline_item(track_type, track_index, item_index)
    if error:
        return error
    missing = _requires_method(item, "GetOutputBlanking", "21.1")
    if missing:
        return missing
    return {"blanking": item.GetOutputBlanking()}

@mcp.tool(annotations=READ_ONLY_TOOL)
def get_timeline_item_use_timeline_for_output_blanking(track_type: str = "video", track_index: int = 1, item_index: int = 0) -> dict:
    """Read GetUseTimelineForOutputBlanking (documented on Resolve 21.1+)."""
    if track_type not in ("video", "audio") or track_index < 1 or item_index < 0:
        return {"error": "Use video/audio, a 1-based track index and a non-negative item index"}
    item, error = _get_timeline_item(track_type, track_index, item_index)
    if error:
        return error
    missing = _requires_method(item, "GetUseTimelineForOutputBlanking", "21.1")
    if missing:
        return missing
    return {"use_timeline": item.GetUseTimelineForOutputBlanking()}


@mcp.tool(annotations=WRITE_TOOL)
def set_timeline_item_speed(options: dict, track_type: str = "video", track_index: int = 1, item_index: int = 0) -> dict:
    """Set native 21.1 Percentage, PitchCorrection, StretchKeyframesToFit and/or RippleTimeline. Percentage 0 freezes; RippleTimeline defaults false."""
    error = validate_edit_options("set_speed", options)
    if error:
        return {"error": error}
    if track_type not in ("video", "audio") or track_index < 1 or item_index < 0:
        return {"error": "Use video/audio, a 1-based track index and a non-negative item index"}
    item, error = _get_timeline_item(track_type, track_index, item_index)
    if error:
        return error
    missing = _requires_method(item, "SetSpeed", "21.1")
    if missing:
        return missing
    return {"success": bool(item.SetSpeed(dict(options)))}


@mcp.tool(annotations=WRITE_TOOL)
def set_timeline_item_fades(options: dict, track_type: str = "video", track_index: int = 1, item_index: int = 0) -> dict:
    """Set native 21.1 FadeIn and/or FadeOut as non-negative integer frame durations. Omitted fields remain native defaults/current state."""
    error = validate_edit_options("set_fades", options)
    if error:
        return {"error": error}
    if track_type not in ("video", "audio") or track_index < 1 or item_index < 0:
        return {"error": "Use video/audio, a 1-based track index and a non-negative item index"}
    item, error = _get_timeline_item(track_type, track_index, item_index)
    if error:
        return error
    missing = _requires_method(item, "SetFades", "21.1")
    if missing:
        return missing
    return {"success": bool(item.SetFades(dict(options)))}


@mcp.tool(annotations=DESTRUCTIVE_TOOL)
def add_timeline_item_transition(options: dict, track_type: str = "video", track_index: int = 1, item_index: int = 0) -> dict:
    """Add a native 21.1 transition using type/category/position/alignment and optional duration in frames. Returns actual span; clip indexes can change after insertion."""
    error = validate_transition_options(options)
    if error:
        return {"error": error}
    if track_type not in ("video", "audio") or track_index < 1 or item_index < 0:
        return {"error": "Use video/audio, a 1-based track index and a non-negative item index"}
    item, error = _get_timeline_item(track_type, track_index, item_index)
    if error:
        return error
    missing = _requires_method(item, "AddTransition", "21.1")
    if missing:
        return missing
    return transition_result(item.AddTransition(dict(options)))
