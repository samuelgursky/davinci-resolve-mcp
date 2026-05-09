#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server (Compound Tools)

30 compound tools covering 100% of the DaVinci Resolve Scripting API (336 methods)
plus Fusion Fuse, DCTL, and Resolve-page Script authoring tools.
Each tool groups related operations via an 'action' parameter.

Usage:
    python src/server.py              # Start the MCP server
    python src/server.py --full       # Start the 328-tool granular server instead
"""

VERSION = "2.9.0"

import base64
import os
import sys
import json
import logging
import platform
import re
import subprocess
import tempfile
import time
from typing import Dict, Any, Optional, List, Tuple

# ─── Path Setup ───────────────────────────────────────────────────────────────

current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(current_dir)

# Add src and project to path
for p in [current_dir, project_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Platform-specific Resolve paths
from src.utils.cdl import normalize_cdl_payload
from src.utils.mcp_stdio import run_fastmcp_stdio
from src.utils.platform import get_resolve_paths, get_resolve_plugin_paths
from src.utils import fuse_templates, dctl_templates, script_templates

paths = get_resolve_paths()
RESOLVE_API_PATH = paths["api_path"]
RESOLVE_LIB_PATH = paths["lib_path"]
RESOLVE_MODULES_PATH = paths["modules_path"]

os.environ["RESOLVE_SCRIPT_API"] = RESOLVE_API_PATH
os.environ["RESOLVE_SCRIPT_LIB"] = RESOLVE_LIB_PATH

if RESOLVE_MODULES_PATH not in sys.path:
    sys.path.append(RESOLVE_MODULES_PATH)

# ─── Logging ──────────────────────────────────────────────────────────────────

log_dir = os.path.join(project_dir, "logs")
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(os.path.join(log_dir, "server.log"))]
)
logger = logging.getLogger("resolve-mcp")

# ─── MCP Server ───────────────────────────────────────────────────────────────

from mcp.server.fastmcp import FastMCP
mcp = FastMCP(
    "DaVinciResolveMCP",
    instructions=(
        "DaVinci Resolve MCP Server — controls Resolve via its Scripting API. "
        "Tools automatically launch Resolve if it is not running (may take up to 60s on first call). "
        "If a tool returns a connection error, Resolve Studio may not be installed or external scripting is disabled."
    ),
)

# ─── Python Version Check ────────────────────────────────────────────────────

_py_ver = sys.version_info[:2]
if _py_ver >= (3, 13):
    logger.warning(
        f"Python {_py_ver[0]}.{_py_ver[1]} detected. DaVinci Resolve's scripting API "
        f"may not work with Python 3.13+. If scriptapp('Resolve') returns None, "
        f"recreate the venv with Python 3.10-3.12."
    )

# ─── Resolve Connection (lazy) ───────────────────────────────────────────────

sys.path.insert(0, RESOLVE_MODULES_PATH)
resolve = None
dvr_script = None

try:
    import DaVinciResolveScript as dvr_script
    logger.info("DaVinciResolveScript module loaded")
except ImportError as e:
    logger.error(f"Cannot import DaVinciResolveScript: {e}")

def _is_resolve_handle_live(candidate) -> bool:
    """Return True when a cached Resolve handle still answers root API calls."""
    try:
        get_version = getattr(candidate, "GetVersion", None)
        if not callable(get_version):
            return False
        return bool(get_version())
    except Exception as exc:
        logger.warning(f"Cached Resolve handle is stale: {exc}")
        return False


def _try_connect():
    """Attempt to connect to Resolve once. Returns resolve object or None."""
    global resolve
    if dvr_script is None:
        return None
    try:
        candidate = dvr_script.scriptapp("Resolve")
        if candidate and _is_resolve_handle_live(candidate):
            resolve = candidate
            logger.info(f"Connected: {resolve.GetProductName()} {resolve.GetVersionString()}")
        else:
            resolve = None
        return resolve
    except Exception as e:
        logger.error(f"Connection error: {e}")
        resolve = None
        return None

def _launch_resolve():
    """Launch DaVinci Resolve and wait for it to become available."""
    sys_name = platform.system().lower()
    if sys_name == "darwin":
        app_path = "/Applications/DaVinci Resolve/DaVinci Resolve.app"
        if not os.path.exists(app_path):
            logger.error(f"DaVinci Resolve not found at {app_path}")
            return False
        subprocess.Popen(["open", app_path])
    elif sys_name == "windows":
        app_path = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
        if not os.path.exists(app_path):
            logger.error(f"DaVinci Resolve not found at {app_path}")
            return False
        subprocess.Popen([app_path])
    elif sys_name == "linux":
        app_path = "/opt/resolve/bin/resolve"
        if not os.path.exists(app_path):
            logger.error(f"DaVinci Resolve not found at {app_path}")
            return False
        subprocess.Popen([app_path])
    else:
        return False
    logger.info("Launched DaVinci Resolve, waiting for it to respond...")
    for i in range(30):
        time.sleep(2)
        if _try_connect():
            logger.info(f"Resolve responded after {(i+1)*2}s")
            return True
    logger.warning("Resolve did not respond within 60s after launch")
    return False

def get_resolve():
    """Lazy connection to Resolve — connects on first tool call, auto-launches if needed."""
    global resolve
    if resolve is not None and _is_resolve_handle_live(resolve):
        return resolve
    resolve = None
    # Try to connect to an already-running Resolve
    if _try_connect():
        return resolve
    # Not running — launch it automatically
    logger.info("Resolve not running, attempting to launch automatically...")
    _launch_resolve()
    return resolve

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_safe_dir(path):
    """Redirect sandbox/temp paths that Resolve can't access to ~/Desktop/resolve-stills.

    Covers macOS (/var/folders, /private/var), Linux (/tmp, /var/tmp),
    and Windows (AppData\\Local\\Temp) sandbox temp directories.
    """
    system_temp = tempfile.gettempdir()
    _is_sandbox = False
    if platform.system() == "Darwin":
        _is_sandbox = path.startswith("/var/") or path.startswith("/private/var/")
    elif platform.system() == "Linux":
        _is_sandbox = path.startswith("/tmp") or path.startswith("/var/tmp")
    elif platform.system() == "Windows":
        # Check if path is under the system temp directory (e.g. AppData\Local\Temp)
        try:
            _is_sandbox = os.path.commonpath([os.path.abspath(path), os.path.abspath(system_temp)]) == os.path.abspath(system_temp)
        except ValueError:
            # Different drives on Windows
            _is_sandbox = False
    if _is_sandbox:
        return os.path.join(os.path.expanduser("~"), "Documents", "resolve-stills")
    return path

def _err(msg):
    return {"error": msg}

def _ok(**kw):
    return {"success": True, **kw}

def _has_method(obj, method_name):
    return callable(getattr(obj, method_name, None))

def _requires_method(obj, method_name, min_version):
    if _has_method(obj, method_name):
        return None
    return _err(f"{method_name} requires DaVinci Resolve {min_version}+")

_MARKER_COLORS = [
    "Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia",
    "Rose", "Lavender", "Sky", "Mint", "Lemon", "Sand", "Cocoa", "Cream",
]


def _first_param(p: Dict[str, Any], *keys: str, default=None):
    for key in keys:
        if key in p and p[key] is not None:
            return p[key]
    return default


def _normalize_marker_color(value):
    raw = str(value if value is not None else "Blue").strip()
    if not raw:
        raw = "Blue"
    for color in _MARKER_COLORS:
        if raw.lower() == color.lower():
            return color, None
    return None, _err(f"Invalid marker color '{raw}'. Must be one of: {', '.join(_MARKER_COLORS)}")


def _coerce_marker_number(value, field_name):
    if isinstance(value, bool):
        return None, _err(f"{field_name} must be a frame number, not a boolean")
    if isinstance(value, int):
        return value, None
    if isinstance(value, float):
        return int(value) if value.is_integer() else value, None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None, _err(f"{field_name} cannot be empty")
        try:
            if "." in raw:
                number = float(raw)
                return int(number) if number.is_integer() else number, None
            return int(raw), None
        except ValueError:
            return None, _err(f"{field_name} must be a frame number")
    return None, _err(f"{field_name} must be a frame number")


def _timeline_fps(tl):
    try:
        setting = tl.GetSetting("timelineFrameRate")
    except Exception as exc:
        return None, _err(f"Failed to read timelineFrameRate: {exc}")
    match = re.search(r"\d+(?:\.\d+)?", str(setting or ""))
    if not match:
        return None, _err("Could not determine timeline frame rate")
    return float(match.group(0)), None


def _timecode_to_frame_id(timecode, fps):
    if not isinstance(timecode, str):
        return None, _err("timecode must be a string like '01:00:00:00'")
    tc = timecode.strip()
    drop_frame = ";" in tc
    parts = tc.replace(";", ":").replace(".", ":").split(":")
    if len(parts) != 4:
        return None, _err("timecode must use HH:MM:SS:FF format")
    try:
        hours, minutes, seconds, frames = [int(part) for part in parts]
    except ValueError:
        return None, _err("timecode fields must be numeric")

    nominal_fps = int(round(float(fps)))
    if nominal_fps <= 0:
        return None, _err("timeline frame rate must be greater than zero")
    if hours < 0 or minutes < 0 or minutes > 59 or seconds < 0 or seconds > 59:
        return None, _err("timecode hours must be non-negative, and minutes/seconds must be between 0 and 59")
    if frames < 0 or frames >= nominal_fps:
        return None, _err(f"timecode frame component must be between 0 and {nominal_fps - 1}")

    total_frames = ((hours * 3600 + minutes * 60 + seconds) * nominal_fps) + frames
    if drop_frame:
        drop_frames = int(round(nominal_fps * 0.0666666667))
        total_minutes = hours * 60 + minutes
        total_frames -= drop_frames * (total_minutes - total_minutes // 10)
    return total_frames, None


def _timeline_timecode_to_frame_id(tl, timecode):
    if tl is None:
        return None, _err("timecode markers require a timeline")
    fps, err = _timeline_fps(tl)
    if err:
        return None, err
    return _timecode_to_frame_id(timecode, fps)


def _current_timeline_frame_id(tl):
    if tl is None:
        return None, _err("current playhead marker requires a timeline")
    try:
        timecode = tl.GetCurrentTimecode()
    except Exception as exc:
        return None, _err(f"Failed to read current timeline timecode: {exc}")
    if not timecode:
        return None, _err("Current timeline timecode is unavailable")
    return _timeline_timecode_to_frame_id(tl, timecode)


def _marker_frame_from_params(p: Dict[str, Any], tl=None, default_to_current=False):
    raw_timecode = _first_param(p, "timecode", "time_code", "tc")
    if raw_timecode is not None:
        return _timeline_timecode_to_frame_id(tl, raw_timecode)

    raw_frame = _first_param(p, "frame", "frame_id", "frameId", "frame_num", "frameNum")
    if raw_frame is not None:
        if isinstance(raw_frame, str):
            lowered = raw_frame.strip().lower()
            if lowered in {"current", "playhead", "current_playhead", "now"}:
                return _current_timeline_frame_id(tl)
            if ":" in raw_frame or ";" in raw_frame:
                return _timeline_timecode_to_frame_id(tl, raw_frame)
        return _coerce_marker_number(raw_frame, "frame")

    if default_to_current:
        return _current_timeline_frame_id(tl)
    return None, _err("Missing marker frame. Provide frame, frame_id/frameId, or timecode.")


def _marker_add_payload(p: Dict[str, Any], tl=None, default_to_current=False):
    frame, err = _marker_frame_from_params(p, tl=tl, default_to_current=default_to_current)
    if err:
        return None, err

    color, err = _normalize_marker_color(_first_param(p, "color", default="Blue"))
    if err:
        return None, err

    note = str(_first_param(p, "note", "comment", "description", default="") or "")
    name = str(_first_param(p, "name", "label", default=(note or "Marker")) or "Marker")
    duration, err = _coerce_marker_number(
        _first_param(p, "duration", "duration_frames", "durationFrames", default=1),
        "duration",
    )
    if err:
        return None, err
    if duration <= 0:
        return None, _err("duration must be greater than zero")

    return {
        "frame": frame,
        "color": color,
        "name": name,
        "note": note,
        "duration": duration,
        "custom_data": str(_first_param(p, "custom_data", "customData", default="") or ""),
    }, None


def _add_marker(target, marker: Dict[str, Any]):
    try:
        result = target.AddMarker(
            marker["frame"],
            marker["color"],
            marker["name"],
            marker["note"],
            marker["duration"],
            marker["custom_data"],
        )
    except TypeError as exc:
        if marker["custom_data"]:
            return _err(f"AddMarker failed: {exc}")
        try:
            result = target.AddMarker(
                marker["frame"],
                marker["color"],
                marker["name"],
                marker["note"],
                marker["duration"],
            )
        except Exception as fallback_exc:
            return _err(f"AddMarker failed: {fallback_exc}")
    except Exception as exc:
        return _err(f"AddMarker failed: {exc}")

    out = {"success": bool(result), "frame": marker["frame"]}
    if not result:
        try:
            markers = target.GetMarkers() or {}
            frame_keys = {marker["frame"]}
            if isinstance(marker["frame"], int):
                frame_keys.add(float(marker["frame"]))
            if any(frame_key in markers for frame_key in frame_keys):
                out["reason"] = f"A marker already exists at frame {marker['frame']}"
        except Exception:
            pass
    return out

def _check():
    resolve = get_resolve()
    if resolve is None:
        return None, None, _err("Not connected to DaVinci Resolve. Is Resolve running?")
    pm = resolve.GetProjectManager()
    proj = pm.GetCurrentProject()
    if not proj:
        return pm, None, _err("No project open")
    return pm, proj, None

def _get_mp():
    pm, proj, err = _check()
    if err:
        return None, None, None, err
    mp = proj.GetMediaPool()
    if not mp:
        return pm, proj, None, _err("Failed to get MediaPool")
    return pm, proj, mp, None

def _get_tl():
    pm, proj, err = _check()
    if err:
        return None, None, err
    tl = proj.GetCurrentTimeline()
    if not tl:
        return proj, None, _err("No current timeline")
    return proj, tl, None

def _get_item(p):
    proj, tl, err = _get_tl()
    if err:
        return None, None, err
    track_type = p.get("track_type", "video")
    track_index = p.get("track_index", 1)
    item_index = p.get("item_index", 0)
    items = tl.GetItemListInTrack(track_type, track_index)
    if not items or item_index >= len(items):
        return tl, None, _err(f"No item at index {item_index} on {track_type} track {track_index}")
    return tl, items[item_index], None


def _has_fusion_timeline_scope(p: Dict[str, Any]) -> bool:
    return bool(p.get("clip_id") or p.get("timeline_item_id") or "timeline_item" in p)


def _find_timeline_item_by_id(tl, timeline_item_id) -> Optional[Any]:
    """Find a timeline item by GetUniqueId() across timeline tracks."""
    if not timeline_item_id:
        return None
    want = str(timeline_item_id)
    for track_type in ("video", "audio", "subtitle"):
        try:
            track_count = int(tl.GetTrackCount(track_type) or 0)
        except Exception:
            continue
        for track_index in range(1, track_count + 1):
            for item in (tl.GetItemListInTrack(track_type, track_index) or []):
                try:
                    if str(item.GetUniqueId()) == want:
                        return item
                except Exception:
                    continue
    return None


def _get_timeline_item_for_fusion(p: Dict[str, Any]):
    """Resolve optional timeline scope for fusion_comp."""
    if not _has_fusion_timeline_scope(p):
        return None, None

    timeline_item = p.get("timeline_item")
    if "timeline_item" in p and not isinstance(timeline_item, dict):
        return None, _err("timeline_item must be an object with track_type, track_index, and item_index")

    _, tl, err = _get_tl()
    if err:
        return None, err

    timeline_item_id = p.get("clip_id") or p.get("timeline_item_id")
    if timeline_item_id:
        item = _find_timeline_item_by_id(tl, timeline_item_id)
        if not item:
            return None, _err(f"No timeline item with clip_id/timeline_item_id={timeline_item_id!r}")
        return item, None

    query = dict(timeline_item)
    query.setdefault("track_type", "video")
    _, item, item_err = _get_item(query)
    if item_err:
        return None, item_err
    return item, None


def _get_fusion_comp_on_timeline_item(item, p: Dict[str, Any]):
    """Get a Fusion composition on a TimelineItem."""
    try:
        comp_count = int(item.GetFusionCompCount() or 0)
    except Exception as exc:
        return None, _err(f"GetFusionCompCount failed: {exc}")
    if comp_count < 1:
        return None, _err("Timeline item has no Fusion compositions")

    comp_name = p.get("comp_name")
    if comp_name:
        comp = item.GetFusionCompByName(str(comp_name))
        if not comp:
            return None, _err(f"No Fusion comp named {comp_name!r} on this timeline item")
        return comp, None

    try:
        comp_index = int(p.get("comp_index", 1))
    except (TypeError, ValueError):
        return None, _err("comp_index must be a 1-based integer")
    if comp_index < 1 or comp_index > comp_count:
        return None, _err(f"No Fusion comp at comp_index={comp_index}; item has {comp_count} comp(s)")

    comp = item.GetFusionCompByIndex(comp_index)
    if not comp:
        return None, _err(f"GetFusionCompByIndex({comp_index}) returned no composition")
    return comp, None


def _resolve_fusion_comp(p: Dict[str, Any], require_timeline_scope: bool = False):
    """Resolve a Fusion comp from timeline scope or the active Fusion page comp."""
    if require_timeline_scope and not _has_fusion_timeline_scope(p):
        return None, _err(
            "Timeline scope is required: pass clip_id, timeline_item_id, "
            "or timeline_item={track_type, track_index, item_index}"
        )

    r = get_resolve()
    if not r:
        return None, _err("Not connected to DaVinci Resolve. Is Resolve running?")

    item, item_err = _get_timeline_item_for_fusion(p)
    if item_err:
        return None, item_err
    if item is not None:
        return _get_fusion_comp_on_timeline_item(item, p)

    fusion = r.Fusion()
    if not fusion:
        return None, _err("Fusion not available — switch to the Fusion page first")
    comp = fusion.GetCurrentComp()
    if not comp:
        return None, _err(
            "No active Fusion composition. Open a clip in the Fusion page first, "
            "or pass clip_id, timeline_item_id, or timeline_item={track_type, track_index, item_index} "
            "with optional comp_name or comp_index."
        )
    return comp, None


def _find_clip(folder, clip_id):
    for clip in (folder.GetClipList() or []):
        if clip.GetUniqueId() == clip_id:
            return clip
    for sub in (folder.GetSubFolderList() or []):
        found = _find_clip(sub, clip_id)
        if found:
            return found
    return None

def _navigate_folder(mp, path):
    root = mp.GetRootFolder()
    if not path or path in ("Master", "/", ""):
        return root
    parts = path.strip("/").split("/")
    if parts[0] == "Master":
        parts = parts[1:]
    current = root
    for part in parts:
        found = False
        for sub in (current.GetSubFolderList() or []):
            if sub.GetName() == part:
                current = sub
                found = True
                break
        if not found:
            return None
    return current


def _build_append_clip_info_dict(root, ci: Dict[str, Any], index: int):
    """Build one MediaPool.AppendToTimeline clipInfo map (Python API uses camelCase keys).

    See docs/resolve_scripting_api.txt: mediaPoolItem, startFrame, endFrame,
    optional mediaType, trackIndex, recordFrame.
    """
    if not isinstance(ci, dict):
        return None, _err(f"clip_infos[{index}] must be an object")
    cid = ci.get("clip_id") or ci.get("media_pool_item_id")
    if not cid:
        return None, _err(f"clip_infos[{index}] requires clip_id or media_pool_item_id")
    mp_item = _find_clip(root, cid)
    if not mp_item:
        return None, _err(f"clip_infos[{index}]: media pool clip not found: {cid}")
    sf = ci.get("startFrame", ci.get("start_frame"))
    ef = ci.get("endFrame", ci.get("end_frame"))
    if sf is None or ef is None:
        return None, _err(
            f"clip_infos[{index}] requires start_frame/startFrame and end_frame/endFrame "
            "(source range on the MediaPoolItem)"
        )
    rf = ci.get("recordFrame", ci.get("record_frame"))
    if rf is None:
        return None, _err(
            f"clip_infos[{index}] requires record_frame/recordFrame (timeline record frame)"
        )
    ti = ci.get("trackIndex", ci.get("track_index"))
    if ti is None:
        return None, _err(
            f"clip_infos[{index}] requires track_index/trackIndex (1-based track index)"
        )
    out: Dict[str, Any] = {
        "mediaPoolItem": mp_item,
        "startFrame": sf,
        "endFrame": ef,
        "recordFrame": rf,
        "trackIndex": ti,
    }
    mt = ci.get("mediaType", ci.get("media_type"))
    if mt is not None:
        out["mediaType"] = mt
    return out, None


def _build_create_clip_info_dict(root, ci: Dict[str, Any], index: int):
    """Build one MediaPool.CreateTimelineFromClips clipInfo map.

    See docs/resolve_scripting_api.txt line 224: 4 keys only — mediaPoolItem,
    startFrame, endFrame, recordFrame. No trackIndex, no mediaType.
    """
    if not isinstance(ci, dict):
        return None, _err(f"clip_infos[{index}] must be an object")
    cid = ci.get("clip_id") or ci.get("media_pool_item_id")
    if not cid:
        return None, _err(f"clip_infos[{index}] requires clip_id or media_pool_item_id")
    mp_item = _find_clip(root, cid)
    if not mp_item:
        return None, _err(f"clip_infos[{index}]: media pool clip not found: {cid}")
    sf = ci.get("startFrame", ci.get("start_frame"))
    ef = ci.get("endFrame", ci.get("end_frame"))
    if sf is None or ef is None:
        return None, _err(
            f"clip_infos[{index}] requires start_frame/startFrame and end_frame/endFrame "
            "(source range on the MediaPoolItem)"
        )
    rf = ci.get("recordFrame", ci.get("record_frame"))
    if rf is None:
        return None, _err(
            f"clip_infos[{index}] requires record_frame/recordFrame (timeline record frame)"
        )
    return {
        "mediaPoolItem": mp_item,
        "startFrame": sf,
        "endFrame": ef,
        "recordFrame": rf,
    }, None


def _frame_int(v):
    if v is None:
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _safe_timeline_item_id(item):
    try:
        get_unique_id = getattr(item, "GetUniqueId", None)
        if callable(get_unique_id):
            item_id = get_unique_id()
            return None if item_id in (None, "") else str(item_id)
    except Exception:
        return None
    return None


def _safe_timeline_item_name(item):
    try:
        get_name = getattr(item, "GetName", None)
        if callable(get_name):
            name = get_name()
            return None if name is None else str(name)
    except Exception:
        return None
    return None


def _safe_media_pool_item_id(mpi):
    try:
        get_unique_id = getattr(mpi, "GetUniqueId", None)
        if callable(get_unique_id):
            media_id = get_unique_id()
            return None if media_id in (None, "") else str(media_id)
    except Exception:
        return None
    return None


def _safe_media_pool_item_name(mpi):
    try:
        get_name = getattr(mpi, "GetName", None)
        if callable(get_name):
            name = get_name()
            return None if name is None else str(name)
    except Exception:
        return None
    return None


def _timeline_item_source_start(item):
    if _has_method(item, "GetSourceStartFrame"):
        try:
            source_start = _frame_int(item.GetSourceStartFrame())
            if source_start is not None:
                return source_start
        except Exception:
            pass
    try:
        return _frame_int(item.GetLeftOffset())
    except Exception:
        return None


def _timeline_item_media_pool_item(item):
    try:
        return item.GetMediaPoolItem()
    except Exception:
        return None


def _timeline_item_duration(item, start: Optional[int] = None, end: Optional[int] = None):
    if _has_method(item, "GetDuration"):
        try:
            duration = _frame_int(item.GetDuration())
            if duration is not None:
                return duration
        except Exception:
            pass
    if start is not None and end is not None:
        return end - start
    return None


def _timeline_item_track_info(item):
    try:
        track_info = item.GetTrackTypeAndIndex()
    except Exception as exc:
        return None, _err(f"GetTrackTypeAndIndex: {exc}")
    if not track_info or len(track_info) < 2:
        return None, _err("GetTrackTypeAndIndex returned empty")
    try:
        return (str(track_info[0]).lower(), int(track_info[1])), None
    except (TypeError, ValueError):
        return None, _err("invalid source track index")


def _timeline_item_summary(item, track_info=None):
    if not item:
        return None
    start = end = duration = source_start = source_end = None
    try:
        start = _frame_int(item.GetStart())
        end = _frame_int(item.GetEnd())
    except Exception:
        pass
    duration = _timeline_item_duration(item, start, end)
    source_start = _timeline_item_source_start(item)
    if source_start is not None and duration is not None:
        source_end = source_start + duration
    if track_info is None:
        track_info, _ = _timeline_item_track_info(item)
    media_pool_item = _timeline_item_media_pool_item(item)
    summary = {
        "timeline_item_id": _safe_timeline_item_id(item),
        "name": _safe_timeline_item_name(item),
        "track_type": track_info[0] if track_info else None,
        "track_index": track_info[1] if track_info else None,
        "start": start,
        "end": end,
        "duration": duration,
        "source_start": source_start,
        "source_end": source_end,
        "media_pool_item_id": _safe_media_pool_item_id(media_pool_item),
        "media_pool_item_name": _safe_media_pool_item_name(media_pool_item),
    }
    return summary


def _serialize_appended_timeline_item(item, index: int, *, allow_empty_timeline_item_id: bool = False):
    if not item:
        return None, _err(f"Failed to append clip_infos to timeline: missing timeline item at index {index}")
    item_id = None
    name = None
    try:
        item_id = item.GetUniqueId()
    except Exception as exc:
        if not allow_empty_timeline_item_id:
            logger.warning(f"Invalid timeline item returned for clip_infos[{index}]: {exc}")
            return None, _err(f"Failed to append clip_infos to timeline: invalid timeline item at index {index}")
        logger.warning(f"Appended timeline item has no readable id for clip_infos[{index}]: {exc}")
    try:
        name = item.GetName()
    except Exception as exc:
        if not allow_empty_timeline_item_id:
            logger.warning(f"Invalid timeline item returned for clip_infos[{index}]: {exc}")
            return None, _err(f"Failed to append clip_infos to timeline: invalid timeline item at index {index}")
        logger.warning(f"Appended timeline item has no readable name for clip_infos[{index}]: {exc}")
    if not item_id:
        if allow_empty_timeline_item_id:
            return {"timeline_item_id": None, "name": None if name is None else str(name)}, None
        return None, _err(f"Failed to append clip_infos to timeline: missing timeline item id at index {index}")
    return {"timeline_item_id": str(item_id), "name": None if name is None else str(name)}, None


def _append_clip_info_from_timeline_item(
    item,
    target_track_index: int,
    record_frame_offset: int = 0,
    record_frame: Optional[int] = None,
    media_type: int = 1,
    source_start: Optional[int] = None,
    source_end: Optional[int] = None,
):
    """Build one MediaPool.AppendToTimeline clipInfo dict from a timeline item.

    Same pool media and source trim as the item; record at GetStart()+record_frame_offset
    on target_track_index. GetDuration() is preferred because Resolve's timeline
    end position can be inclusive for clips created via positioned append.
    """
    try:
        mpi = item.GetMediaPoolItem()
    except Exception as exc:
        return None, _err(f"GetMediaPoolItem failed: {exc}")
    if not mpi:
        return None, _err(
            "Timeline item has no MediaPoolItem (generators / titles without pool media cannot use this)"
        )
    try:
        t_start = _frame_int(item.GetStart())
        t_end_excl = _frame_int(item.GetEnd())
    except Exception as exc:
        return None, _err(f"GetStart/GetEnd failed: {exc}")
    if t_start is None or t_end_excl is None:
        return None, _err("GetStart/GetEnd returned unset values")
    duration_tl = None
    if _has_method(item, "GetDuration"):
        try:
            duration_tl = _frame_int(item.GetDuration())
        except Exception:
            duration_tl = None
    if duration_tl is None:
        duration_tl = t_end_excl - t_start
    if duration_tl <= 0:
        return None, _err("invalid timeline duration")
    src_start = _timeline_item_source_start(item) if source_start is None else _frame_int(source_start)
    if src_start is None:
        return None, _err("could not read source trim (LeftOffset / GetSourceStartFrame)")
    src_end_excl = _frame_int(source_end) if source_end is not None else src_start + duration_tl
    if src_end_excl is None or src_end_excl <= src_start:
        return None, _err("invalid source range")
    record = int(record_frame) if record_frame is not None else t_start + int(record_frame_offset)
    return {
        "mediaPoolItem": mpi,
        "startFrame": src_start,
        "endFrame": src_end_excl,
        "recordFrame": record,
        "trackIndex": int(target_track_index),
        "mediaType": int(media_type),
    }, None


def _find_appended_timeline_item_summary(
    tl,
    *,
    track_type: str = "video",
    target_track_index: int,
    record_frame: int,
    duration: int,
    source_media_pool_item,
    source_timeline_item_id: Optional[str] = None,
):
    """Recover an appended item's id by scanning the target track after append.

    Resolve can occasionally return a thin object from AppendToTimeline that
    lacks GetUniqueId/GetName even though the edit succeeded. The timeline track
    itself usually contains the real item handle immediately after the append.
    """
    source_media_id = _safe_media_pool_item_id(source_media_pool_item)
    try:
        items = tl.GetItemListInTrack(track_type, target_track_index) or []
    except Exception:
        return None
    matches = []
    for item in items:
        item_id = _safe_timeline_item_id(item)
        if source_timeline_item_id and item_id == source_timeline_item_id:
            continue
        try:
            start = _frame_int(item.GetStart())
            end = _frame_int(item.GetEnd())
        except Exception:
            continue
        if start != record_frame or start is None or end is None:
            continue
        item_duration = None
        if _has_method(item, "GetDuration"):
            try:
                item_duration = _frame_int(item.GetDuration())
            except Exception:
                item_duration = None
        if item_duration is None:
            item_duration = end - start
        if item_duration != duration:
            continue
        item_mpi = _timeline_item_media_pool_item(item)
        if source_media_id:
            if _safe_media_pool_item_id(item_mpi) != source_media_id:
                continue
        elif item_mpi is not source_media_pool_item:
            continue
        matches.append(item)
    if not matches:
        return None
    item = matches[-1]
    return {
        "timeline_item_id": _safe_timeline_item_id(item),
        "name": _safe_timeline_item_name(item),
    }


_DUPLICATE_PLACEMENTS = {
    "same_time",
    "offset",
    "at_playhead",
    "track_above",
    "after_source",
    "next_gap",
}

_DUPLICATE_COPY_GROUP_ALIASES = {
    "all": "all",
    "all_supported": "all",
    "audio": "audio",
    "audio_properties": "audio",
    "cache": "cache",
    "color": "clip_color",
    "color_grade": "grades",
    "clipcolor": "clip_color",
    "clip_color": "clip_color",
    "enabled": "enabled",
    "enabled_state": "enabled",
    "flags": "flags",
    "fusion": "fusion",
    "fusion_comps": "fusion",
    "dynamic_zoom": "dynamic_zoom",
    "dynamiczoom": "dynamic_zoom",
    "grade": "grades",
    "grades": "grades",
    "keyframe": "keyframes",
    "keyframes": "keyframes",
    "markers": "markers",
    "marker": "markers",
    "retime": "retime",
    "retime_settings": "retime",
    "scaling": "scaling",
    "resize": "scaling",
    "sizing": "scaling",
    "stabilization": "stabilization",
    "stabilisation": "stabilization",
    "takes": "takes",
    "take_selectors": "takes",
    "transitions": "transitions",
    "transition": "transitions",
    "transform": "transform",
    "crop": "crop",
    "composite": "composite",
    "voice_isolation": "voice_isolation",
}

_DUPLICATE_COPY_PROPERTY_KEYS = {
    "transform": [
        "Pan",
        "Tilt",
        "ZoomX",
        "ZoomY",
        "ZoomGang",
        "RotationAngle",
        "AnchorPointX",
        "AnchorPointY",
        "Pitch",
        "Yaw",
        "FlipX",
        "FlipY",
    ],
    "crop": [
        "CropLeft",
        "CropRight",
        "CropTop",
        "CropBottom",
        "CropSoftness",
        "CropRetain",
    ],
    "composite": ["Opacity", "CompositeMode"],
    "audio": [
        "Volume",
        "Pan",
        "AudioSyncOffsetIsManual",
        "AudioSyncOffset",
        "EQEnable",
        "NormalizeEnable",
        "NormalizeLevel",
    ],
    "retime": ["Speed", "RetimeProcess", "MotionEstimation"],
    "dynamic_zoom": ["DynamicZoomEnable", "DynamicZoomMode", "DynamicZoomEase"],
    "scaling": ["Distortion", "Scaling", "ResizeFilter"],
    "stabilization": ["StabilizationEnable", "StabilizationMethod", "StabilizationStrength"],
}

_DUPLICATE_KEYFRAME_PROPERTIES = []
for _group_keys in _DUPLICATE_COPY_PROPERTY_KEYS.values():
    for _key in _group_keys:
        if _key not in _DUPLICATE_KEYFRAME_PROPERTIES:
            _DUPLICATE_KEYFRAME_PROPERTIES.append(_key)

_DUPLICATE_COPY_ALL = [
    "transform",
    "crop",
    "composite",
    "audio",
    "retime",
    "dynamic_zoom",
    "scaling",
    "stabilization",
    "clip_color",
    "markers",
    "flags",
    "enabled",
    "cache",
    "voice_isolation",
    "fusion",
    "grades",
    "takes",
    "keyframes",
]


def _normalize_duplicate_placement(raw, has_offset: bool):
    placement = str(raw or ("offset" if has_offset else "same_time")).strip().lower()
    if placement not in _DUPLICATE_PLACEMENTS:
        return None, _err(f"placement must be one of: {', '.join(sorted(_DUPLICATE_PLACEMENTS))}")
    return placement, None


def _normalize_copy_properties(raw):
    if raw in (None, False, ""):
        return [], None
    if raw is True:
        return list(_DUPLICATE_COPY_ALL), None
    if isinstance(raw, str):
        if raw.strip().lower() in {"basic", "all", "all_supported", "supported"}:
            return list(_DUPLICATE_COPY_ALL), None
        raw_items = [part.strip() for part in raw.split(",") if part.strip()]
    elif isinstance(raw, list):
        raw_items = raw
    else:
        return None, _err("copy_properties must be a list, comma-separated string, boolean, or omitted")

    groups = []
    for item in raw_items:
        key = str(item).strip().lower()
        normalized = _DUPLICATE_COPY_GROUP_ALIASES.get(key)
        if not normalized:
            return None, _err(
                "copy_properties entries must be one of: "
                f"{', '.join(sorted(_DUPLICATE_COPY_GROUP_ALIASES))}"
            )
        if normalized == "all":
            for group in _DUPLICATE_COPY_ALL:
                if group not in groups:
                    groups.append(group)
            continue
        if normalized not in groups:
            groups.append(normalized)
    return groups, None


def _coerce_duplicate_int(raw, name: str):
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, _err(f"{name} must be an integer")


def _resolve_duplicate_track_index(src_track: int, placement: str, p: Dict[str, Any], track_type: str = "video"):
    if track_type == "audio":
        target_raw = p.get("target_audio_track_index", p.get("targetAudioTrackIndex"))
        if target_raw is not None:
            return _coerce_duplicate_int(target_raw, "target_audio_track_index")
        track_offset_raw = p.get("audio_track_offset", p.get("audioTrackOffset", 0))
        track_offset, offset_err = _coerce_duplicate_int(track_offset_raw, "audio_track_offset")
        if offset_err:
            return None, offset_err
        return src_track + track_offset, None

    target_raw = p.get("target_track_index", p.get("targetTrackIndex"))
    if target_raw is not None:
        return _coerce_duplicate_int(target_raw, "target_track_index")

    track_offset_raw = p.get("track_offset", p.get("trackOffset"))
    if track_offset_raw is None:
        track_offset = 1 if placement == "track_above" else 0
    else:
        track_offset, offset_err = _coerce_duplicate_int(track_offset_raw, "track_offset")
        if offset_err:
            return None, offset_err
    return src_track + track_offset, None


def _track_items_sorted(tl, track_type: str, track_index: int):
    try:
        items = tl.GetItemListInTrack(track_type, track_index) or []
    except Exception:
        return []

    sortable = []
    for item in items:
        try:
            start = _frame_int(item.GetStart())
            end = _frame_int(item.GetEnd())
        except Exception:
            continue
        if start is None or end is None:
            continue
        sortable.append((start, end, item))
    sortable.sort(key=lambda row: (row[0], row[1]))
    return sortable


def _find_next_gap_record_frame(
    tl,
    *,
    track_type: str,
    track_index: int,
    duration: int,
    search_start: int,
    exclude_item_id: Optional[str] = None,
):
    cursor = int(search_start)
    for start, end, item in _track_items_sorted(tl, track_type, track_index):
        item_id = _safe_timeline_item_id(item)
        if exclude_item_id and item_id == exclude_item_id:
            continue
        if end <= cursor:
            continue
        if start >= cursor + duration:
            return cursor
        cursor = max(cursor, end)
    return cursor


def _resolve_duplicate_record_frame(
    tl,
    item,
    placement: str,
    offset: int,
    p: Dict[str, Any],
    dest_track: int,
    track_type: str = "video",
):
    source = _timeline_item_summary(item)
    if not source or source["start"] is None or source["duration"] is None:
        return None, _err("could not resolve source timeline position")

    explicit_record = p.get("record_frame", p.get("recordFrame"))
    if explicit_record is not None:
        return _coerce_duplicate_int(explicit_record, "record_frame")

    if placement == "at_playhead":
        frame, frame_err = _current_timeline_frame_id(tl)
        if frame_err:
            return None, frame_err
        return frame + offset, None

    if placement == "after_source":
        return int(source["start"]) + int(source["duration"]) + offset, None

    if placement == "next_gap":
        search_start = int(source["start"]) + int(source["duration"]) + offset
        return _find_next_gap_record_frame(
            tl,
            track_type=track_type,
            track_index=dest_track,
            duration=int(source["duration"]),
            search_start=search_start,
            exclude_item_id=source["timeline_item_id"],
        ), None

    return int(source["start"]) + offset, None


def _coerce_item_list(value):
    if value is None:
        return []
    if isinstance(value, dict):
        iterable = value.values()
    elif isinstance(value, (list, tuple, set)):
        iterable = value
    else:
        iterable = [value]
    return [item for item in iterable if item]


def _get_selected_timeline_items(tl):
    warnings = []
    for method_name in ("GetSelectedTimelineItems", "GetSelectedItems", "GetSelectedClips"):
        method = getattr(tl, method_name, None)
        if not callable(method):
            continue
        try:
            items = _coerce_item_list(method())
        except Exception as exc:
            warnings.append(f"{method_name} failed: {exc}")
            continue
        if items:
            return items, warnings

    current_video = getattr(tl, "GetCurrentVideoItem", None)
    if callable(current_video):
        try:
            item = current_video()
        except Exception as exc:
            return [], warnings + [f"GetCurrentVideoItem failed: {exc}"]
        if item:
            return [item], warnings + [
                "Timeline selection API is unavailable; used current video item as selected source"
            ]
    return [], warnings


def _copy_property_group(source_item, duplicate_item, keys: List[str]):
    details = {}
    for key in keys:
        try:
            value = source_item.GetProperty(key)
        except Exception as exc:
            details[key] = {"success": False, "error": f"GetProperty failed: {exc}"}
            continue
        if value is None:
            details[key] = {"success": True, "copied": False, "reason": "source value is unavailable"}
            continue
        try:
            details[key] = bool(duplicate_item.SetProperty(key, value))
        except Exception as exc:
            details[key] = {"success": False, "error": f"SetProperty failed: {exc}"}
    success = all(value is True or (isinstance(value, dict) and value.get("success")) for value in details.values())
    return {"success": success, "details": details}


def _copy_clip_color(source_item, duplicate_item):
    try:
        color = source_item.GetClipColor()
    except Exception as exc:
        return {"success": False, "error": f"GetClipColor failed: {exc}"}
    if not color:
        return {"success": True, "color": None}
    try:
        set_ok = bool(duplicate_item.SetClipColor(color))
    except Exception as exc:
        return {"success": False, "color": color, "error": f"SetClipColor failed: {exc}"}
    if not set_ok:
        return {"success": False, "color": color, "error": "SetClipColor returned false"}
    try:
        actual = duplicate_item.GetClipColor()
    except Exception:
        actual = color
    if actual != color:
        return {
            "success": False,
            "color": color,
            "actual": actual,
            "error": "SetClipColor did not persist the requested color",
        }
    return {"success": True, "color": color}


def _copy_enabled_state(source_item, duplicate_item):
    try:
        enabled = bool(source_item.GetClipEnabled())
    except Exception as exc:
        return {"success": False, "error": f"GetClipEnabled failed: {exc}"}
    try:
        return {"success": bool(duplicate_item.SetClipEnabled(enabled)), "enabled": enabled}
    except Exception as exc:
        return {"success": False, "enabled": enabled, "error": f"SetClipEnabled failed: {exc}"}


def _marker_value(marker: Dict[str, Any], *keys, default=None):
    for key in keys:
        if key in marker:
            return marker[key]
    return default


def _copy_timeline_item_markers(source_item, duplicate_item):
    try:
        markers = source_item.GetMarkers() or {}
    except Exception as exc:
        return {"success": False, "error": f"GetMarkers failed: {exc}"}
    copied = 0
    failed = []
    for frame, marker in markers.items():
        if not isinstance(marker, dict):
            failed.append({"frame": frame, "error": "marker payload is not an object"})
            continue
        frame_id = _frame_int(frame)
        if frame_id is None:
            failed.append({"frame": frame, "error": "marker frame is not numeric"})
            continue
        result = _add_marker(
            duplicate_item,
            {
                "frame": frame_id,
                "color": _marker_value(marker, "color", "Color", default="Blue"),
                "name": _marker_value(marker, "name", "Name", default="Marker"),
                "note": _marker_value(marker, "note", "Note", default=""),
                "duration": _frame_int(_marker_value(marker, "duration", "Duration", default=1)) or 1,
                "custom_data": str(_marker_value(marker, "customData", "custom_data", "CustomData", default="") or ""),
            },
        )
        if result.get("success"):
            copied += 1
        else:
            failed.append({"frame": frame_id, "error": result.get("error") or result.get("reason") or "AddMarker failed"})
    return {"success": not failed, "copied": copied, "failed": failed}


def _copy_flags(source_item, duplicate_item):
    try:
        flags = source_item.GetFlagList() or []
    except Exception as exc:
        return {"success": False, "error": f"GetFlagList failed: {exc}"}
    results = {}
    for color in flags:
        try:
            results[str(color)] = bool(duplicate_item.AddFlag(color))
        except Exception as exc:
            results[str(color)] = {"success": False, "error": f"AddFlag failed: {exc}"}
    return {
        "success": all(value is True for value in results.values()),
        "flags": list(flags),
        "details": results,
    }


def _copy_cache_state(source_item, duplicate_item):
    results = {}
    pairs = [
        ("color", "GetIsColorOutputCacheEnabled", "SetColorOutputCache"),
        ("fusion", "GetIsFusionOutputCacheEnabled", "SetFusionOutputCache"),
    ]
    for label, getter_name, setter_name in pairs:
        getter = getattr(source_item, getter_name, None)
        setter = getattr(duplicate_item, setter_name, None)
        if not callable(getter) or not callable(setter):
            results[label] = {"success": True, "copied": False, "reason": "cache API unavailable"}
            continue
        try:
            value = getter()
        except Exception as exc:
            results[label] = {"success": False, "error": f"{getter_name} failed: {exc}"}
            continue
        try:
            results[label] = {"success": bool(setter(value)), "value": value}
        except Exception as exc:
            results[label] = {"success": False, "value": value, "error": f"{setter_name} failed: {exc}"}
    return {"success": all(v.get("success") for v in results.values()), "details": results}


def _copy_voice_isolation(source_item, duplicate_item):
    getter = getattr(source_item, "GetVoiceIsolationState", None)
    setter = getattr(duplicate_item, "SetVoiceIsolationState", None)
    if not callable(getter) or not callable(setter):
        return {"success": True, "copied": False, "reason": "voice isolation API unavailable"}
    try:
        state = getter()
    except Exception as exc:
        return {"success": False, "error": f"GetVoiceIsolationState failed: {exc}"}
    if not state:
        state = {"isEnabled": False, "amount": 0}
    try:
        return {"success": bool(setter(state)), "state": _ser(state)}
    except Exception as exc:
        return {"success": False, "state": _ser(state), "error": f"SetVoiceIsolationState failed: {exc}"}


def _copy_fusion_comps(source_item, duplicate_item):
    try:
        count = int(source_item.GetFusionCompCount() or 0)
    except Exception as exc:
        return {"success": False, "error": f"GetFusionCompCount failed: {exc}"}
    if count <= 0:
        return {"success": True, "copied": 0}
    copied = 0
    failed = []
    with tempfile.TemporaryDirectory(prefix="mcp_fusion_copy_") as tmp_dir:
        for index in range(1, count + 1):
            path = os.path.join(tmp_dir, f"fusion_comp_{index}.setting")
            try:
                exported = bool(source_item.ExportFusionComp(path, index))
            except Exception as exc:
                failed.append({"index": index, "error": f"ExportFusionComp failed: {exc}"})
                continue
            if not exported:
                failed.append({"index": index, "error": "ExportFusionComp returned false"})
                continue
            try:
                imported = duplicate_item.ImportFusionComp(path)
            except Exception as exc:
                failed.append({"index": index, "error": f"ImportFusionComp failed: {exc}"})
                continue
            if imported:
                copied += 1
            else:
                failed.append({"index": index, "error": "ImportFusionComp returned no composition"})
    return {"success": not failed, "copied": copied, "failed": failed}


def _copy_grades(source_item, duplicate_item):
    try:
        return {"success": bool(source_item.CopyGrades([duplicate_item]))}
    except Exception as exc:
        return {"success": False, "error": f"CopyGrades failed: {exc}"}


def _copy_takes(source_item, duplicate_item):
    try:
        count = int(source_item.GetTakesCount() or 0)
    except Exception as exc:
        return {"success": False, "error": f"GetTakesCount failed: {exc}"}
    if count <= 0:
        return {"success": True, "copied": 0}
    copied = 0
    failed = []
    for index in range(1, count + 1):
        try:
            take = source_item.GetTakeByIndex(index)
        except Exception as exc:
            failed.append({"index": index, "error": f"GetTakeByIndex failed: {exc}"})
            continue
        if not isinstance(take, dict):
            failed.append({"index": index, "error": "take payload is not an object"})
            continue
        clip = take.get("mediaPoolItem")
        if not clip:
            failed.append({"index": index, "error": "take has no mediaPoolItem"})
            continue
        try:
            added = bool(duplicate_item.AddTake(clip, take.get("startFrame", 0), take.get("endFrame", 0)))
        except Exception as exc:
            failed.append({"index": index, "error": f"AddTake failed: {exc}"})
            continue
        if added:
            copied += 1
        else:
            failed.append({"index": index, "error": "AddTake returned false"})
    try:
        selected = int(source_item.GetSelectedTakeIndex() or 0)
        if selected > 0:
            duplicate_item.SelectTakeByIndex(selected)
    except Exception:
        pass
    return {"success": not failed, "copied": copied, "failed": failed}


def _copy_keyframes(source_item, duplicate_item, properties: Optional[List[str]] = None):
    properties = properties or list(_DUPLICATE_KEYFRAME_PROPERTIES)
    copied = 0
    failed = []
    unavailable = []
    for prop in properties:
        try:
            count = int(source_item.GetKeyframeCount(prop) or 0)
        except Exception as exc:
            unavailable.append({"property": prop, "error": f"GetKeyframeCount failed: {exc}"})
            continue
        for index in range(count):
            try:
                keyframe = source_item.GetKeyframeAtIndex(prop, index)
                frame = keyframe.get("frame") if isinstance(keyframe, dict) else keyframe
                value = source_item.GetPropertyAtKeyframeIndex(prop, index)
            except Exception as exc:
                failed.append({"property": prop, "index": index, "error": f"read keyframe failed: {exc}"})
                continue
            try:
                added = bool(duplicate_item.AddKeyframe(prop, frame, value))
            except Exception as exc:
                failed.append({"property": prop, "frame": frame, "error": f"AddKeyframe failed: {exc}"})
                continue
            if added:
                copied += 1
            else:
                failed.append({"property": prop, "frame": frame, "error": "AddKeyframe returned false"})
    return {"success": not failed, "copied": copied, "failed": failed, "unavailable": unavailable}


def _copy_duplicate_item_state(source_item, duplicate_item, groups: List[str]):
    results = {}
    copy_order = [
        "transform",
        "crop",
        "composite",
        "audio",
        "retime",
        "dynamic_zoom",
        "scaling",
        "stabilization",
        "cache",
        "voice_isolation",
        "fusion",
        "grades",
        "takes",
        "keyframes",
        "transitions",
        "clip_color",
        "markers",
        "flags",
        "enabled",
    ]
    ordered_groups = [group for group in copy_order if group in groups]
    ordered_groups.extend(group for group in groups if group not in ordered_groups)
    for group in ordered_groups:
        if group in _DUPLICATE_COPY_PROPERTY_KEYS:
            results[group] = _copy_property_group(source_item, duplicate_item, _DUPLICATE_COPY_PROPERTY_KEYS[group])
        elif group == "clip_color":
            results[group] = _copy_clip_color(source_item, duplicate_item)
        elif group == "enabled":
            results[group] = _copy_enabled_state(source_item, duplicate_item)
        elif group == "markers":
            results[group] = _copy_timeline_item_markers(source_item, duplicate_item)
        elif group == "flags":
            results[group] = _copy_flags(source_item, duplicate_item)
        elif group == "cache":
            results[group] = _copy_cache_state(source_item, duplicate_item)
        elif group == "voice_isolation":
            results[group] = _copy_voice_isolation(source_item, duplicate_item)
        elif group == "fusion":
            results[group] = _copy_fusion_comps(source_item, duplicate_item)
        elif group == "grades":
            results[group] = _copy_grades(source_item, duplicate_item)
        elif group == "takes":
            results[group] = _copy_takes(source_item, duplicate_item)
        elif group == "keyframes":
            results[group] = _copy_keyframes(source_item, duplicate_item)
        elif group == "transitions":
            results[group] = {
                "success": True,
                "copied": False,
                "reason": "Resolve's public scripting API does not expose timeline item transition cloning",
            }
    return results


def _timeline_media_type(track_type: str):
    if track_type == "video":
        return 1
    if track_type == "audio":
        return 2
    return None


def _timeline_track_count(tl, track_type: str):
    try:
        return int(tl.GetTrackCount(track_type) or 0)
    except Exception:
        return 0


def _timeline_item_ids(items):
    ids = []
    for item in items:
        item_id = _safe_timeline_item_id(item)
        if item_id:
            ids.append(item_id)
    return ids


def _timeline_items_by_ids(tl, ids, track_types=("video", "audio", "subtitle")):
    ids_set = {str(item_id) for item_id in ids if item_id is not None}
    found = []
    if not ids_set:
        return found
    for track_type in track_types:
        for track_index in range(1, _timeline_track_count(tl, track_type) + 1):
            for item in (tl.GetItemListInTrack(track_type, track_index) or []):
                if _safe_timeline_item_id(item) in ids_set:
                    found.append(item)
    return found


def _normalize_include_linked(raw):
    if raw in (None, False, "", []):
        return set()
    if raw is True:
        return {"audio"}
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in {"all", "true", "yes"}:
            return {"video", "audio"}
        return {part.strip().lower() for part in lowered.split(",") if part.strip()}
    if isinstance(raw, list):
        return {str(part).strip().lower() for part in raw if str(part).strip()}
    return {"audio"}


def _linked_items_for_duplicate(item, include_types):
    if not include_types:
        return [], []
    linked_method = getattr(item, "GetLinkedItems", None)
    if not callable(linked_method):
        return [], ["GetLinkedItems API unavailable; linked duplication skipped"]
    try:
        linked = linked_method() or []
    except Exception as exc:
        return [], [f"GetLinkedItems failed: {exc}"]

    source_id = _safe_timeline_item_id(item)
    out = []
    warnings = []
    seen = set()
    for linked_item in linked:
        linked_id = _safe_timeline_item_id(linked_item)
        if linked_id and linked_id == source_id:
            continue
        if linked_id and linked_id in seen:
            continue
        track_info, track_err = _timeline_item_track_info(linked_item)
        if track_err:
            warnings.append(f"Linked item {linked_id or '<unknown>'}: {track_err.get('error', track_err)}")
            continue
        track_type, _ = track_info
        if track_type not in include_types:
            continue
        if _timeline_media_type(track_type) is None:
            warnings.append(f"Linked item {linked_id or '<unknown>'}: unsupported track type {track_type!r}")
            continue
        out.append(linked_item)
        if linked_id:
            seen.add(linked_id)
    return out, warnings


def _append_and_recover_timeline_item(
    mp,
    tl,
    source_item,
    *,
    track_type: str,
    dest_track: int,
    record_frame: int,
    copy_properties: List[str],
    source_timeline_item_id: Optional[str] = None,
    source_start: Optional[int] = None,
    source_end: Optional[int] = None,
):
    media_type = _timeline_media_type(track_type)
    if media_type is None:
        return None, None, _err(f"Cannot append unsupported track type {track_type!r}")

    source_track_info, _ = _timeline_item_track_info(source_item)
    source_summary = _timeline_item_summary(source_item, track_info=source_track_info)
    info, ierr = _append_clip_info_from_timeline_item(
        source_item,
        dest_track,
        record_frame=record_frame,
        media_type=media_type,
        source_start=source_start,
        source_end=source_end,
    )
    if ierr:
        return None, None, ierr
    try:
        out = mp.AppendToTimeline([info])
    except Exception as exc:
        return None, None, _err(str(exc))
    if not out or len(out) < 1:
        return None, None, _err("AppendToTimeline returned no item")

    ser, serr = _serialize_appended_timeline_item(out[0], 0, allow_empty_timeline_item_id=True)
    if serr:
        return None, None, serr
    if not ser.get("timeline_item_id"):
        recovered = _find_appended_timeline_item_summary(
            tl,
            track_type=track_type,
            target_track_index=dest_track,
            record_frame=int(info["recordFrame"]),
            duration=int(info["endFrame"]) - int(info["startFrame"]),
            source_media_pool_item=info["mediaPoolItem"],
            source_timeline_item_id=source_timeline_item_id,
        )
        if recovered and recovered.get("timeline_item_id"):
            ser = recovered

    duplicate_item = None
    if ser.get("timeline_item_id"):
        duplicate_item = _find_timeline_item_by_id(tl, ser["timeline_item_id"])
    if duplicate_item is None:
        out_item_id = _safe_timeline_item_id(out[0])
        if out_item_id:
            duplicate_item = out[0]

    duplicate_summary = _timeline_item_summary(duplicate_item, track_info=(track_type, dest_track)) if duplicate_item else {
        "timeline_item_id": ser.get("timeline_item_id"),
        "name": ser.get("name"),
        "track_type": track_type,
        "track_index": dest_track,
        "start": int(info["recordFrame"]),
        "end": int(info["recordFrame"]) + int(info["endFrame"]) - int(info["startFrame"]),
        "duration": int(info["endFrame"]) - int(info["startFrame"]),
        "source_start": int(info["startFrame"]),
        "source_end": int(info["endFrame"]),
        "media_pool_item_id": _safe_media_pool_item_id(info["mediaPoolItem"]),
        "media_pool_item_name": _safe_media_pool_item_name(info["mediaPoolItem"]),
    }

    warnings = []
    copied_properties = {}
    if copy_properties:
        if duplicate_item is None:
            warnings.append("Could not reacquire duplicate item; copy_properties were skipped")
        else:
            copied_properties = _copy_duplicate_item_state(source_item, duplicate_item, copy_properties)

    result = {
        "clip_id": source_timeline_item_id,
        "source_clip_id": source_timeline_item_id,
        "success": True,
        **ser,
        "source": source_summary,
        "duplicate": duplicate_summary,
    }
    if copied_properties:
        result["copied_properties"] = copied_properties
    if warnings:
        result["warnings"] = warnings
    return result, duplicate_item, None


def _timeline_duplicate_clips_impl(proj, tl, p: Dict[str, Any], *, delete_sources: bool = False):
    ids = p.get("clip_ids") or p.get("ids")
    selected = bool(p.get("selected", False))
    if ids is not None and not isinstance(ids, list):
        return _err("duplicate_clips requires clip_ids (list of timeline item unique IDs)")
    if not ids and not selected:
        return _err("duplicate_clips requires clip_ids or selected=True")

    has_offset = "record_frame_offset" in p or "recordFrameOffset" in p
    placement, placement_err = _normalize_duplicate_placement(p.get("placement"), has_offset)
    if placement_err:
        return placement_err
    copy_properties, copy_err = _normalize_copy_properties(p.get("copy_properties", p.get("copyProperties")))
    if copy_err:
        return copy_err
    if p.get("copy_keyframes", p.get("copyKeyframes", False)) and "keyframes" not in copy_properties:
        copy_properties.append("keyframes")
    try:
        offset = int(p.get("record_frame_offset", p.get("recordFrameOffset", 0)))
    except (TypeError, ValueError):
        return _err("record_frame_offset must be an integer")

    mp = proj.GetMediaPool()
    if not mp:
        return _err("Failed to get MediaPool")

    source_entries: List[Dict[str, Any]] = []
    seen_ids = set()
    if ids:
        for cid in ids:
            sid = str(cid)
            source_entries.append({"clip_id": sid, "item": _find_timeline_item_by_id(tl, sid)})
            seen_ids.add(sid)
    selection_warnings: List[str] = []
    if selected:
        selected_items, selection_warnings = _get_selected_timeline_items(tl)
        if not selected_items and not source_entries:
            return _err("selected=True did not resolve any timeline items")
        for item in selected_items:
            sid = _safe_timeline_item_id(item)
            if not sid:
                source_entries.append({"clip_id": None, "item": item})
                continue
            if sid in seen_ids:
                continue
            source_entries.append({"clip_id": sid, "item": item})
            seen_ids.add(sid)

    include_types = _normalize_include_linked(p.get("include_linked", p.get("includeLinked")))
    relink = bool(p.get("relink", p.get("restore_linked", p.get("restoreLinked", bool(include_types)))))
    results: List[Dict[str, Any]] = []
    source_delete_items = []

    for entry in source_entries:
        item = entry.get("item")
        sid = entry.get("clip_id") or _safe_timeline_item_id(item)
        if not sid:
            results.append({"clip_id": None, "success": False, "error": "timeline item has no readable id"})
            continue
        if not item:
            results.append({"clip_id": sid, "success": False, "error": "timeline item not found"})
            continue

        normalized_track_info, track_err = _timeline_item_track_info(item)
        if track_err:
            results.append({"clip_id": sid, "success": False, "error": track_err.get("error", str(track_err))})
            continue
        tt, src_track = normalized_track_info
        if tt != "video":
            results.append({
                "clip_id": sid,
                "success": False,
                "error": f"primary duplicate item must be video (got {tt!r}); use include_linked from a linked video item for audio",
            })
            continue

        dest_track, dest_err = _resolve_duplicate_track_index(src_track, placement, p, track_type="video")
        if dest_err:
            results.append({"clip_id": sid, "success": False, "error": dest_err.get("error", str(dest_err))})
            continue
        if dest_track < 1:
            results.append({"clip_id": sid, "success": False, "error": "target_track_index must be >= 1"})
            continue
        video_track_count = _timeline_track_count(tl, "video")
        if video_track_count and dest_track > video_track_count:
            results.append({
                "clip_id": sid,
                "success": False,
                "error": f"target video track {dest_track} does not exist",
            })
            continue

        record_frame, record_err = _resolve_duplicate_record_frame(tl, item, placement, offset, p, dest_track, track_type="video")
        if record_err:
            results.append({"clip_id": sid, "success": False, "error": record_err.get("error", str(record_err))})
            continue

        primary_result, primary_duplicate, primary_err = _append_and_recover_timeline_item(
            mp,
            tl,
            item,
            track_type="video",
            dest_track=dest_track,
            record_frame=record_frame,
            copy_properties=copy_properties,
            source_timeline_item_id=sid,
        )
        if primary_err:
            results.append({"clip_id": sid, "success": False, "error": primary_err.get("error", str(primary_err))})
            continue

        primary_result["placement"] = placement
        source_start = _frame_int(item.GetStart())
        base_delta = record_frame - source_start if source_start is not None else offset
        linked_items, linked_warnings = _linked_items_for_duplicate(item, include_types)
        linked_results = []
        duplicate_link_items = [primary_duplicate] if primary_duplicate else []
        original_link_items = [item]

        for linked_item in linked_items:
            linked_id = _safe_timeline_item_id(linked_item)
            linked_track_info, linked_track_err = _timeline_item_track_info(linked_item)
            if linked_track_err:
                linked_results.append({
                    "clip_id": linked_id,
                    "success": False,
                    "error": linked_track_err.get("error", str(linked_track_err)),
                })
                continue
            linked_track_type, linked_src_track = linked_track_info
            linked_dest_track, linked_dest_err = _resolve_duplicate_track_index(
                linked_src_track,
                placement,
                p,
                track_type=linked_track_type,
            )
            if linked_dest_err:
                linked_results.append({
                    "clip_id": linked_id,
                    "success": False,
                    "error": linked_dest_err.get("error", str(linked_dest_err)),
                })
                continue
            track_count = _timeline_track_count(tl, linked_track_type)
            if linked_dest_track < 1 or (track_count and linked_dest_track > track_count):
                linked_results.append({
                    "clip_id": linked_id,
                    "success": False,
                    "error": f"target {linked_track_type} track {linked_dest_track} does not exist",
                })
                continue
            linked_start = _frame_int(linked_item.GetStart())
            if linked_start is None:
                linked_results.append({"clip_id": linked_id, "success": False, "error": "linked item start is unavailable"})
                continue
            linked_record_frame = linked_start + base_delta
            linked_result, linked_duplicate, linked_err = _append_and_recover_timeline_item(
                mp,
                tl,
                linked_item,
                track_type=linked_track_type,
                dest_track=linked_dest_track,
                record_frame=linked_record_frame,
                copy_properties=copy_properties,
                source_timeline_item_id=linked_id,
            )
            if linked_err:
                linked_results.append({"clip_id": linked_id, "success": False, "error": linked_err.get("error", str(linked_err))})
                continue
            linked_result["placement"] = placement
            linked_results.append(linked_result)
            original_link_items.append(linked_item)
            if linked_duplicate:
                duplicate_link_items.append(linked_duplicate)

        if linked_results:
            primary_result["linked_results"] = linked_results
        if linked_warnings:
            primary_result.setdefault("warnings", []).extend(linked_warnings)

        if relink and len(duplicate_link_items) > 1:
            try:
                primary_result["linked"] = bool(tl.SetClipsLinked(duplicate_link_items, True))
            except Exception as exc:
                primary_result.setdefault("warnings", []).append(f"SetClipsLinked failed: {exc}")

        if delete_sources:
            source_delete_items.extend(original_link_items if include_types else [item])

        results.append(primary_result)

    out = {"results": results, "count": len(results), "placement": placement}
    if selection_warnings:
        out["warnings"] = selection_warnings
    if delete_sources:
        successful_source_ids = {
            result.get("source_clip_id")
            for result in results
            if result.get("success") and result.get("source_clip_id")
        }
        delete_items = []
        seen_delete_ids = set()
        for item in source_delete_items:
            item_id = _safe_timeline_item_id(item)
            if not item_id or item_id in seen_delete_ids:
                continue
            if item_id in successful_source_ids or include_types:
                delete_items.append(item)
                seen_delete_ids.add(item_id)
        if delete_items:
            try:
                out["deleted_sources"] = bool(tl.DeleteClips(delete_items, bool(p.get("ripple", False))))
                out["deleted_source_ids"] = _timeline_item_ids(delete_items)
            except Exception as exc:
                out["deleted_sources"] = False
                out["delete_error"] = str(exc)
        else:
            out["deleted_sources"] = False
            out["delete_error"] = "No successfully duplicated source items to delete"
    return out


def _range_frames_from_params(tl, p: Dict[str, Any]):
    if p.get("use_mark_in_out", p.get("useMarkInOut", False)):
        mark = tl.GetMarkInOut() or {}
        mark_type = p.get("mark_type", p.get("markType", "video"))
        if mark_type not in mark:
            mark_type = "video" if "video" in mark else "audio" if "audio" in mark else None
        if not mark_type:
            return None, None, _err("No timeline mark in/out is set")
        return _frame_int(mark[mark_type].get("in")), _frame_int(mark[mark_type].get("out")), None
    start = p.get("start_frame", p.get("startFrame"))
    end = p.get("end_frame", p.get("endFrame"))
    if start is None or end is None:
        return None, None, _err("Range actions require start_frame/end_frame or use_mark_in_out=True")
    start = _frame_int(start)
    end = _frame_int(end)
    if start is None or end is None:
        return None, None, _err("start_frame and end_frame must be numeric")
    if end <= start:
        return None, None, _err("end_frame must be greater than start_frame")
    return start, end, None


def _range_track_types(p: Dict[str, Any]):
    raw = p.get("track_types", p.get("trackTypes", p.get("track_type", p.get("trackType", "video"))))
    if raw == "all":
        return ["video", "audio"]
    if isinstance(raw, str):
        return [part.strip().lower() for part in raw.split(",") if part.strip()]
    if isinstance(raw, list):
        return [str(part).strip().lower() for part in raw if str(part).strip()]
    return ["video"]


def _range_track_indices(p: Dict[str, Any], track_type: str):
    key = f"{track_type}_track_indices"
    raw = p.get(key, p.get(f"{track_type}TrackIndices", p.get("track_indices", p.get("trackIndices"))))
    if raw is None:
        return None
    if isinstance(raw, int):
        return [raw]
    if isinstance(raw, str):
        return [int(part.strip()) for part in raw.split(",") if part.strip()]
    return [int(part) for part in raw]


def _collect_timeline_items_in_range(tl, p: Dict[str, Any]):
    start, end, err = _range_frames_from_params(tl, p)
    if err:
        return None, None, None, err
    items = []
    for track_type in _range_track_types(p):
        if track_type not in {"video", "audio"}:
            return None, None, None, _err(f"Range actions support video/audio tracks, got {track_type!r}")
        indices = _range_track_indices(p, track_type)
        if indices is None:
            indices = list(range(1, _timeline_track_count(tl, track_type) + 1))
        for track_index in indices:
            for item in (tl.GetItemListInTrack(track_type, track_index) or []):
                item_start = _frame_int(item.GetStart())
                item_end = _frame_int(item.GetEnd())
                if item_start is None or item_end is None:
                    continue
                if item_start < end and item_end > start:
                    items.append((track_type, track_index, item, max(item_start, start), min(item_end, end)))
    return start, end, items, None


def _timeline_copy_range_impl(proj, tl, p: Dict[str, Any], *, overwrite: bool = False):
    start, end, items, err = _collect_timeline_items_in_range(tl, p)
    if err:
        return err
    if not items:
        return {"results": [], "count": 0, "range": {"start": start, "end": end}}
    record_raw = p.get("record_frame", p.get("recordFrame"))
    if record_raw is None:
        return _err("copy_range/duplicate_range require record_frame for destination range start")
    dest_start, dest_err = _coerce_duplicate_int(record_raw, "record_frame")
    if dest_err:
        return dest_err

    copy_properties, copy_err = _normalize_copy_properties(p.get("copy_properties", p.get("copyProperties")))
    if copy_err:
        return copy_err
    if p.get("copy_keyframes", p.get("copyKeyframes", False)) and "keyframes" not in copy_properties:
        copy_properties.append("keyframes")
    mp = proj.GetMediaPool()
    if not mp:
        return _err("Failed to get MediaPool")

    duration = end - start
    deleted = None
    if overwrite:
        dest_end = dest_start + duration
        delete_targets = []
        for track_type, _, _, _, _ in items:
            for track_index in range(1, _timeline_track_count(tl, track_type) + 1):
                for existing in (tl.GetItemListInTrack(track_type, track_index) or []):
                    existing_start = _frame_int(existing.GetStart())
                    existing_end = _frame_int(existing.GetEnd())
                    if existing_start is None or existing_end is None:
                        continue
                    if existing_start < dest_end and existing_end > dest_start:
                        delete_targets.append(existing)
        if delete_targets:
            deleted = bool(tl.DeleteClips(delete_targets, False))

    results = []
    for track_type, source_track, item, overlap_start, overlap_end in items:
        media_type = _timeline_media_type(track_type)
        if media_type is None:
            results.append({"clip_id": _safe_timeline_item_id(item), "success": False, "error": f"unsupported track type {track_type!r}"})
            continue
        dest_track, track_err = _resolve_duplicate_track_index(source_track, "same_time", p, track_type=track_type)
        if track_err:
            results.append({"clip_id": _safe_timeline_item_id(item), "success": False, "error": track_err.get("error", str(track_err))})
            continue
        item_source_start = _timeline_item_source_start(item)
        item_start = _frame_int(item.GetStart())
        if item_source_start is None or item_start is None:
            results.append({"clip_id": _safe_timeline_item_id(item), "success": False, "error": "could not resolve source trim"})
            continue
        source_start = item_source_start + (overlap_start - item_start)
        source_end = source_start + (overlap_end - overlap_start)
        record_frame = dest_start + (overlap_start - start)
        result, _, append_err = _append_and_recover_timeline_item(
            mp,
            tl,
            item,
            track_type=track_type,
            dest_track=dest_track,
            record_frame=record_frame,
            copy_properties=copy_properties,
            source_timeline_item_id=_safe_timeline_item_id(item),
            source_start=source_start,
            source_end=source_end,
        )
        if append_err:
            results.append({"clip_id": _safe_timeline_item_id(item), "success": False, "error": append_err.get("error", str(append_err))})
            continue
        result["range_source"] = {"start": overlap_start, "end": overlap_end}
        result["range_destination"] = {"start": record_frame, "end": record_frame + (overlap_end - overlap_start)}
        results.append(result)
    out = {
        "results": results,
        "count": len(results),
        "range": {"start": start, "end": end},
        "destination_range": {"start": dest_start, "end": dest_start + duration},
    }
    if overwrite:
        out["deleted_destination_overlaps"] = bool(deleted)
    return out


def _timeline_lift_range_impl(tl, p: Dict[str, Any]):
    start, end, items, err = _collect_timeline_items_in_range(tl, p)
    if err:
        return err
    allow_partial = bool(p.get("allow_partial_item_delete", p.get("allowPartialItemDelete", False)))
    delete_items = []
    blocked = []
    for _, _, item, overlap_start, overlap_end in items:
        item_start = _frame_int(item.GetStart())
        item_end = _frame_int(item.GetEnd())
        if not allow_partial and (overlap_start != item_start or overlap_end != item_end):
            blocked.append({
                "timeline_item_id": _safe_timeline_item_id(item),
                "name": _safe_timeline_item_name(item),
                "item_start": item_start,
                "item_end": item_end,
                "overlap_start": overlap_start,
                "overlap_end": overlap_end,
            })
            continue
        delete_items.append(item)
    if blocked:
        return {
            "error": "Range partially overlaps timeline items; pass allow_partial_item_delete=True to delete whole overlapping items",
            "blocked": blocked,
        }
    if not delete_items:
        return {"success": True, "deleted": 0, "range": {"start": start, "end": end}}
    deleted_ids = _timeline_item_ids(delete_items)
    return {
        "success": bool(tl.DeleteClips(delete_items, bool(p.get("ripple", False)))),
        "deleted": len(delete_items),
        "deleted_ids": deleted_ids,
        "range": {"start": start, "end": end},
    }


def _timeline_edit_kernel_capabilities():
    return {
        "supported": {
            "clip_duplication": [
                "video timeline items with MediaPoolItem",
                "linked audio duplication from a linked video source",
                "selected/current video item fallback",
                "same_time",
                "offset",
                "at_playhead",
                "track_above",
                "after_source",
                "next_gap",
            ],
            "clip_operations": ["copy_clips", "move_clips"],
            "range_operations": [
                "copy_range",
                "duplicate_range",
                "overwrite_range by deleting whole destination overlaps",
                "lift_range by deleting whole matching items",
            ],
            "copy_properties": list(_DUPLICATE_COPY_ALL) + ["transitions"],
            "read_only_probe": [
                "timeline item method availability",
                "all GetProperty() values exposed by Resolve",
                "known property-key values",
                "keyframe counts for known properties",
                "linked item summaries",
            ],
            "source_media_integrity": [
                "references original MediaPoolItems",
                "does not transcode, render, proxy, or create source derivatives",
            ],
        },
        "partially_supported": {
            "audio_properties": "Resolve may reject SetProperty on some timeline audio items/builds; failures are reported per property.",
            "cache": "Color/Fusion cache state is copied only when Resolve exposes readable/writable cache APIs for the item.",
            "voice_isolation": "Copied only when Resolve exposes item-level voice isolation APIs.",
            "keyframes": "Copies keyframes for supported properties; interpolation readback is not exposed for full fidelity verification.",
            "dynamic_zoom_scaling_stabilization": "Copied through exposed TimelineItem.GetProperty/SetProperty keys when a Resolve build returns writable values.",
        },
        "unsupported": {
            "transition_cloning": "Resolve's public scripting API does not expose timeline item transition cloning.",
            "razor_or_partial_lift": "Resolve's public scripting API does not expose a direct timeline split/razor primitive; partial range edits are represented by append-based copies or whole-item deletes.",
            "source_less_items": "Titles, generators, Fusion compositions, and subtitles without a MediaPoolItem cannot be cloned through AppendToTimeline clipInfo.",
            "deep_speed_ramp_semantics": "Only exposed Speed/RetimeProcess/MotionEstimation properties and supported keyframes are copied; opaque retime curves are not independently inspectable.",
        },
    }


def _callable_method_names(obj, names: List[str]):
    out = {}
    for name in names:
        out[name] = callable(getattr(obj, name, None))
    return out


def _safe_get_property(item, key: Optional[str] = None):
    try:
        if key is None:
            return _ser(item.GetProperty()), None
        return _ser(item.GetProperty(key)), None
    except Exception as exc:
        return None, str(exc)


def _probe_keyframes(item, properties: List[str]):
    out = {}
    for prop in properties:
        try:
            count = int(item.GetKeyframeCount(prop) or 0)
        except Exception as exc:
            out[prop] = {"available": False, "error": str(exc)}
            continue
        frames = []
        for index in range(count):
            try:
                keyframe = item.GetKeyframeAtIndex(prop, index)
                value = item.GetPropertyAtKeyframeIndex(prop, index)
                frames.append({"keyframe": _ser(keyframe), "value": _ser(value)})
            except Exception as exc:
                frames.append({"error": str(exc)})
        out[prop] = {"available": True, "count": count, "frames": frames}
    return out


def _timeline_item_probe(item):
    known_property_keys = []
    for keys in _DUPLICATE_COPY_PROPERTY_KEYS.values():
        for key in keys:
            if key not in known_property_keys:
                known_property_keys.append(key)

    all_properties, all_properties_error = _safe_get_property(item)
    known_properties = {}
    for key in known_property_keys:
        value, err = _safe_get_property(item, key)
        known_properties[key] = {"value": value, "error": err} if err else {"value": value}

    linked = []
    get_linked = getattr(item, "GetLinkedItems", None)
    if callable(get_linked):
        try:
            linked = [_timeline_item_summary(linked_item) for linked_item in (get_linked() or [])]
        except Exception as exc:
            linked = [{"error": str(exc)}]

    method_names = [
        "GetMediaPoolItem",
        "GetLinkedItems",
        "GetProperty",
        "SetProperty",
        "GetKeyframeCount",
        "GetKeyframeAtIndex",
        "GetPropertyAtKeyframeIndex",
        "AddKeyframe",
        "SetKeyframeInterpolation",
        "GetFusionCompCount",
        "ExportFusionComp",
        "ImportFusionComp",
        "CopyGrades",
        "GetTakesCount",
        "AddTake",
        "GetVoiceIsolationState",
        "SetVoiceIsolationState",
        "GetClipColor",
        "SetClipColor",
    ]

    return {
        "summary": _timeline_item_summary(item),
        "methods": _callable_method_names(item, method_names),
        "all_properties": all_properties,
        "all_properties_error": all_properties_error,
        "known_properties": known_properties,
        "keyframes": _probe_keyframes(item, known_property_keys),
        "linked_items": linked,
    }


def _timeline_probe_edit_kernel_item(tl, p: Dict[str, Any]):
    ids = p.get("clip_ids") or p.get("ids")
    selected = bool(p.get("selected", False))
    items = []
    if ids:
        if not isinstance(ids, list):
            return _err("probe_edit_kernel_item requires clip_ids as a list")
        for item_id in ids:
            item = _find_timeline_item_by_id(tl, item_id)
            if item:
                items.append(item)
    if selected:
        selected_items, warnings = _get_selected_timeline_items(tl)
        items.extend(selected_items)
    else:
        warnings = []
    if not items and p.get("timeline_item"):
        _, item, item_err = _get_item(p["timeline_item"])
        if item_err:
            return item_err
        items.append(item)
    if not items:
        return _err("probe_edit_kernel_item requires clip_ids, selected=True, or timeline_item scope")
    probes = [_timeline_item_probe(item) for item in items]
    out = {"items": probes, "count": len(probes)}
    if warnings:
        out["warnings"] = warnings
    return out


_MEDIA_POOL_ITEM_METHODS = [
    "GetName",
    "SetName",
    "GetMetadata",
    "SetMetadata",
    "GetThirdPartyMetadata",
    "SetThirdPartyMetadata",
    "GetMediaId",
    "GetClipProperty",
    "SetClipProperty",
    "GetMarkers",
    "AddMarker",
    "GetMarkerByCustomData",
    "UpdateMarkerCustomData",
    "GetMarkerCustomData",
    "DeleteMarkersByColor",
    "DeleteMarkerAtFrame",
    "DeleteMarkerByCustomData",
    "AddFlag",
    "GetFlagList",
    "ClearFlags",
    "GetClipColor",
    "SetClipColor",
    "ClearClipColor",
    "LinkProxyMedia",
    "UnlinkProxyMedia",
    "ReplaceClip",
    "LinkFullResolutionMedia",
    "MonitorGrowingFile",
    "ReplaceClipPreserveSubClip",
    "TranscribeAudio",
    "ClearTranscription",
    "GetAudioMapping",
    "GetMarkInOut",
    "SetMarkInOut",
    "ClearMarkInOut",
]

_MEDIA_POOL_METHODS = [
    "GetRootFolder",
    "AddSubFolder",
    "CreateEmptyTimeline",
    "CreateTimelineFromClips",
    "ImportTimelineFromFile",
    "DeleteTimelines",
    "AppendToTimeline",
    "GetCurrentFolder",
    "SetCurrentFolder",
    "DeleteFolders",
    "DeleteClips",
    "MoveClips",
    "MoveFolders",
    "RefreshFolders",
    "RelinkClips",
    "UnlinkClips",
    "ImportMedia",
    "ExportMetadata",
    "GetUniqueId",
    "CreateStereoClip",
    "AutoSyncAudio",
    "GetSelectedClips",
    "SetSelectedClip",
    "GetClipMatteList",
    "GetTimelineMatteList",
    "DeleteClipMattes",
    "ImportFolderFromFile",
]

_MEDIA_POOL_KNOWN_CLIP_PROPERTIES = [
    "File Path",
    "Type",
    "Format",
    "FPS",
    "Frames",
    "Duration",
    "Start TC",
    "End TC",
    "Resolution",
    "Codec",
    "Bit Depth",
    "Audio Ch",
    "Sample Rate",
    "Data Level",
    "PAR",
    "Alpha mode",
]

_MEDIA_POOL_KERNEL_ACTIONS = [
    "ingest_capabilities",
    "probe_ingest_item",
    "probe_media_pool",
    "safe_import_media",
    "safe_import_sequence",
    "safe_import_folder",
    "organize_clips",
    "copy_metadata",
    "normalize_metadata",
    "probe_clip_properties",
    "safe_relink",
    "safe_unlink",
    "link_proxy_checked",
    "link_full_resolution_checked",
    "set_clip_marks",
    "clear_clip_marks",
    "copy_clip_annotations",
    "media_pool_boundary_report",
]


def _safe_clip_call(clip, method_name: str, *args):
    method = getattr(clip, method_name, None)
    if not callable(method):
        return None, f"{method_name} unavailable"
    try:
        return _ser(method(*args)), None
    except Exception as exc:
        return None, str(exc)


def _media_pool_item_summary(clip):
    if not clip:
        return None
    summary = {
        "name": _safe_media_pool_item_name(clip),
        "id": _safe_media_pool_item_id(clip),
        "media_id": None,
        "file_path": None,
        "type": None,
        "duration": None,
    }
    media_id, _ = _safe_clip_call(clip, "GetMediaId")
    if media_id is not None:
        summary["media_id"] = media_id
    properties, _ = _safe_clip_call(clip, "GetClipProperty", "")
    if isinstance(properties, dict):
        summary["file_path"] = properties.get("File Path") or properties.get("FilePath")
        summary["type"] = properties.get("Type")
        summary["duration"] = properties.get("Duration")
    return summary


def _media_pool_item_probe(clip):
    metadata, metadata_error = _safe_clip_call(clip, "GetMetadata", "")
    third_party, third_party_error = _safe_clip_call(clip, "GetThirdPartyMetadata", "")
    properties, properties_error = _safe_clip_call(clip, "GetClipProperty", "")
    known_properties = {}
    for key in _MEDIA_POOL_KNOWN_CLIP_PROPERTIES:
        value, err = _safe_clip_call(clip, "GetClipProperty", key)
        known_properties[key] = {"value": value, "error": err} if err else {"value": value}

    color, color_error = _safe_clip_call(clip, "GetClipColor")
    markers, markers_error = _safe_clip_call(clip, "GetMarkers")
    flags, flags_error = _safe_clip_call(clip, "GetFlagList")
    audio_mapping, audio_mapping_error = _safe_clip_call(clip, "GetAudioMapping")
    mark, mark_error = _safe_clip_call(clip, "GetMarkInOut")

    return {
        "summary": _media_pool_item_summary(clip),
        "methods": _callable_method_names(clip, _MEDIA_POOL_ITEM_METHODS),
        "metadata": {"value": metadata, "error": metadata_error} if metadata_error else metadata,
        "third_party_metadata": (
            {"value": third_party, "error": third_party_error} if third_party_error else third_party
        ),
        "clip_properties": {"value": properties, "error": properties_error} if properties_error else properties,
        "known_clip_properties": known_properties,
        "clip_color": {"value": color, "error": color_error} if color_error else color,
        "markers": {"value": markers, "error": markers_error} if markers_error else markers,
        "flags": {"value": flags, "error": flags_error} if flags_error else flags,
        "audio_mapping": (
            {"value": audio_mapping, "error": audio_mapping_error} if audio_mapping_error else audio_mapping
        ),
        "mark_in_out": {"value": mark, "error": mark_error} if mark_error else mark,
    }


def _folder_probe(folder, depth: int = 1):
    if not folder:
        return None
    clips = []
    for clip in (folder.GetClipList() or []):
        clips.append(_media_pool_item_summary(clip))
    subfolders = []
    if depth > 0:
        for sub in (folder.GetSubFolderList() or []):
            subfolders.append(_folder_probe(sub, depth - 1))
    stale = None
    try:
        stale = bool(folder.GetIsFolderStale())
    except Exception:
        pass
    return {
        "name": folder.GetName(),
        "id": folder.GetUniqueId(),
        "stale": stale,
        "clip_count": len(clips),
        "clips": clips,
        "subfolder_count": len(subfolders),
        "subfolders": subfolders,
    }


def _media_pool_ingest_capabilities():
    return {
        "supported": {
            "storage_browsing": ["get_volumes", "get_subfolders", "get_files"],
            "imports": [
                "media_storage.import_to_pool simple paths",
                "media_storage.import_to_pool item_infos",
                "media_pool.import_media simple paths",
                "media_pool.import_media image sequence clip_infos",
                "media_pool.import_folder",
                "media_pool.safe_import_media with path validation and optional target folder",
                "media_pool.safe_import_sequence with printf-pattern frame validation",
                "media_pool.safe_import_folder with directory validation",
            ],
            "organization": [
                "folder add/delete/move",
                "clip move/delete",
                "current folder set/get",
                "selected clip get/set",
                "media_pool.organize_clips with optional folder creation",
            ],
            "metadata": [
                "metadata get/set scalar",
                "metadata get/set dict",
                "third-party metadata get/set",
                "media_pool.copy_metadata across clips",
                "media_pool.normalize_metadata bulk writes",
                "clip property snapshot",
                "clip property set when Resolve accepts the key",
                "media_pool.probe_clip_properties read-only property snapshots",
            ],
            "annotations": [
                "media pool item markers",
                "media pool item custom marker data",
                "flags",
                "clip color",
                "mark in/out",
                "media_pool.set_clip_marks and clear_clip_marks",
                "media_pool.copy_clip_annotations for markers, flags, and clip color",
            ],
            "media_links": [
                "relink/unlink through Resolve MediaPool APIs",
                "media_pool.safe_relink and safe_unlink with path/clip validation",
                "proxy link/unlink through MediaPoolItem APIs",
                "media_pool.link_proxy_checked with file validation",
                "full-resolution media link where Resolve 20 exposes it",
                "media_pool.link_full_resolution_checked with version/path validation",
            ],
            "read_only_probe": [
                "media pool method availability",
                "media pool folder summaries",
                "media pool item method availability",
                "metadata snapshots",
                "third-party metadata snapshots",
                "clip property snapshots",
                "markers, flags, clip color, audio mapping, mark in/out",
                "media_pool.media_pool_boundary_report",
            ],
            "source_media_integrity": [
                "live validation uses generated synthetic media only",
                "safe helpers must not transcode, render, proxy, or overwrite user source media",
            ],
        },
        "partially_supported": {
            "clip_properties": "Resolve accepts only some GetClipProperty/SetClipProperty keys by media type and build.",
            "proxy_and_full_resolution_links": "Resolve may accept paths without deep compatibility validation; probes must use synthetic media.",
            "audio_transcription": "Transcription availability depends on Resolve Studio features, installed components, media type, and page/build state.",
            "image_sequences": "Sequence import behavior depends on FilePath pattern, frame range, and Resolve's still/sequence interpretation.",
            "audio_mapping": "Readback is available on supported media, but mapping shape varies by clip type.",
        },
        "unsupported": {
            "source_media_mutation": "The MCP kernel never edits, transcodes, proxies, or overwrites original source media unless explicitly requested by the user.",
            "safe_destructive_replace": "ReplaceClip and ReplaceClipPreserveSubClip are exposed raw APIs; kernel probes must restrict them to disposable synthetic media.",
            "guaranteed_metadata_schema": "Resolve does not guarantee every metadata key is writable or stable across versions/locales.",
        },
    }


def _media_pool_probe(mp, p: Dict[str, Any]):
    depth = p.get("depth", 1)
    try:
        depth = max(0, min(int(depth), 4))
    except (TypeError, ValueError):
        return _err("depth must be an integer")
    root = mp.GetRootFolder()
    current = mp.GetCurrentFolder()
    selected = []
    try:
        selected = [_media_pool_item_summary(clip) for clip in (mp.GetSelectedClips() or [])]
    except Exception as exc:
        selected = [{"error": str(exc)}]
    return {
        "media_pool_id": mp.GetUniqueId(),
        "methods": _callable_method_names(mp, _MEDIA_POOL_METHODS),
        "root": _folder_probe(root, depth),
        "current_folder": _folder_probe(current, 0) if current else None,
        "selected_clips": selected,
    }


def _media_pool_probe_ingest_items(mp, p: Dict[str, Any]):
    root = mp.GetRootFolder()
    ids = p.get("clip_ids") or p.get("ids")
    selected = bool(p.get("selected", False))
    clips = []
    warnings = []
    if ids:
        if not isinstance(ids, list):
            return _err("probe_ingest_item requires clip_ids as a list")
        for clip_id in ids:
            clip = _find_clip(root, str(clip_id))
            if clip:
                clips.append(clip)
            else:
                warnings.append(f"Clip not found: {clip_id}")
    if selected:
        try:
            clips.extend(mp.GetSelectedClips() or [])
        except Exception as exc:
            warnings.append(f"GetSelectedClips failed: {exc}")
    if not clips:
        return _err("probe_ingest_item requires clip_ids or selected=True")
    out = {"items": [_media_pool_item_probe(clip) for clip in clips], "count": len(clips)}
    if warnings:
        out["warnings"] = warnings
    return out


def _path_error(path: str, *, must_be_dir: bool = False, must_be_file: bool = False):
    if not path or not isinstance(path, str):
        return "path must be a non-empty string"
    if not os.path.exists(path):
        return f"path does not exist: {path}"
    if must_be_dir and not os.path.isdir(path):
        return f"path is not a directory: {path}"
    if must_be_file and not os.path.isfile(path):
        return f"path is not a file: {path}"
    return None


def _string_list_param(p: Dict[str, Any], key: str):
    value = p.get(key)
    if not isinstance(value, list) or not value:
        return None, _err(f"{key} must be a non-empty list")
    cleaned = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            return None, _err(f"{key}[{index}] must be a non-empty string")
        cleaned.append(item)
    return cleaned, None


def _clips_from_params(root, mp, p: Dict[str, Any], *, key: str = "clip_ids"):
    ids = p.get(key) or p.get("ids")
    selected = bool(p.get("selected", False))
    clips = []
    missing = []
    if ids:
        if not isinstance(ids, list):
            return None, _err(f"{key} must be a list")
        for clip_id in ids:
            clip = _find_clip(root, str(clip_id))
            if clip:
                clips.append(clip)
            else:
                missing.append(str(clip_id))
    if selected:
        clips.extend(mp.GetSelectedClips() or [])
    deduped = []
    seen = set()
    for clip in clips:
        clip_id = _safe_media_pool_item_id(clip) or id(clip)
        if clip_id in seen:
            continue
        seen.add(clip_id)
        deduped.append(clip)
    if not deduped:
        return None, _err(f"Provide {key} or selected=True")
    return (deduped, missing), None


def _clip_summaries(clips):
    return [_media_pool_item_summary(clip) for clip in clips]


def _imported_clip_summaries(items):
    return {
        "imported": len(items) if items else 0,
        "clips": _clip_summaries(items or []),
    }


def _format_sequence_path(pattern: str, index: int):
    try:
        return pattern % index
    except (TypeError, ValueError):
        return None


def _missing_sequence_frames(pattern: str, start: int, end: int):
    missing = []
    unformattable = False
    for index in range(start, end + 1):
        path = _format_sequence_path(pattern, index)
        if not path:
            unformattable = True
            break
        if not os.path.exists(path):
            missing.append(path)
    return missing, unformattable


def _set_current_folder_temporarily(mp, target_path: Optional[str]):
    if not target_path:
        return None, None
    target = _navigate_folder(mp, target_path)
    if not target:
        return None, _err(f"Target folder not found: {target_path}")
    previous = mp.GetCurrentFolder()
    if not mp.SetCurrentFolder(target):
        return None, _err(f"Failed to set current folder: {target_path}")
    return previous, None


def _restore_current_folder(mp, previous):
    if previous:
        try:
            mp.SetCurrentFolder(previous)
        except Exception:
            pass


def _ensure_folder_path(mp, path: str):
    if not path or path in ("Master", "/", ""):
        return mp.GetRootFolder(), None
    existing = _navigate_folder(mp, path)
    if existing:
        return existing, None
    parts = path.strip("/").split("/")
    if parts and parts[0] == "Master":
        parts = parts[1:]
    current = mp.GetRootFolder()
    built = ["Master"]
    for part in parts:
        built.append(part)
        found = None
        for sub in (current.GetSubFolderList() or []):
            if sub.GetName() == part:
                found = sub
                break
        if not found:
            found = mp.AddSubFolder(current, part)
            if not found:
                return None, _err(f"Failed to create folder: {'/'.join(built)}")
        current = found
    return current, None


def _safe_import_media(mp, p: Dict[str, Any]):
    paths, err = _string_list_param(p, "paths")
    if err:
        return err
    errors = []
    for path in paths:
        path_err = _path_error(path)
        if path_err:
            errors.append(path_err)
    if errors:
        return _err("; ".join(errors))
    if p.get("dry_run"):
        return _ok(would_import=paths, target_folder=p.get("target_folder"))
    previous, folder_err = _set_current_folder_temporarily(mp, p.get("target_folder"))
    if folder_err:
        return folder_err
    try:
        return _ok(**_imported_clip_summaries(mp.ImportMedia(paths) or []))
    finally:
        _restore_current_folder(mp, previous)


def _safe_import_sequence(mp, p: Dict[str, Any]):
    pattern = p.get("FilePath") or p.get("file_path") or p.get("pattern")
    if not pattern:
        return _err("Provide FilePath, file_path, or pattern")
    try:
        start = int(p.get("StartIndex", p.get("start_index", 1)))
        end = int(p.get("EndIndex", p.get("end_index", start)))
    except (TypeError, ValueError):
        return _err("StartIndex/EndIndex must be integers")
    if end < start:
        return _err("EndIndex must be greater than or equal to StartIndex")
    missing, unformattable = _missing_sequence_frames(pattern, start, end)
    if unformattable:
        return _err("Sequence pattern must be printf-style, e.g. frame_%03d.png")
    if missing:
        sample = missing[:5]
        suffix = "" if len(missing) <= 5 else f" (+{len(missing) - 5} more)"
        return _err(f"Missing sequence frames: {sample}{suffix}")
    info = {"FilePath": pattern, "StartIndex": start, "EndIndex": end}
    if p.get("dry_run"):
        return _ok(would_import=[info], target_folder=p.get("target_folder"))
    previous, folder_err = _set_current_folder_temporarily(mp, p.get("target_folder"))
    if folder_err:
        return folder_err
    try:
        return _ok(**_imported_clip_summaries(mp.ImportMedia([info]) or []))
    finally:
        _restore_current_folder(mp, previous)


def _safe_import_folder(mp, p: Dict[str, Any]):
    path = p.get("path")
    path_err = _path_error(path, must_be_dir=True)
    if path_err:
        return _err(path_err)
    if p.get("dry_run"):
        return _ok(would_import_folder=path, source_clips_path=p.get("source_clips_path", ""))
    return {"success": bool(mp.ImportFolderFromFile(path, p.get("source_clips_path", "")))}


def _organize_clips(mp, root, p: Dict[str, Any]):
    target_path = p.get("target_path")
    if not target_path:
        return _err("target_path is required")
    if p.get("create_missing"):
        target, target_err = _ensure_folder_path(mp, target_path)
    else:
        target = _navigate_folder(mp, target_path)
        target_err = None if target else _err(f"Target folder not found: {target_path}")
    if target_err:
        return target_err
    resolved, err = _clips_from_params(root, mp, p)
    if err:
        return err
    clips, missing = resolved
    if p.get("dry_run"):
        return _ok(target_path=target_path, clips=_clip_summaries(clips), missing=missing)
    return {"success": bool(mp.MoveClips(clips, target)), "moved": len(clips), "missing": missing}


def _copy_metadata(root, p: Dict[str, Any]):
    source = _find_clip(root, p.get("source_clip_id", ""))
    if not source:
        return _err(f"Source clip not found: {p.get('source_clip_id')}")
    target_ids = p.get("target_clip_ids")
    if not isinstance(target_ids, list) or not target_ids:
        return _err("target_clip_ids must be a non-empty list")
    metadata = source.GetMetadata("") or {}
    if p.get("keys"):
        keys = set(p["keys"])
        metadata = {key: value for key, value in metadata.items() if key in keys}
    third_party = {}
    if p.get("include_third_party", True):
        third_party = source.GetThirdPartyMetadata("") or {}
    results = []
    for target_id in target_ids:
        target = _find_clip(root, str(target_id))
        if not target:
            results.append({"clip_id": target_id, "success": False, "error": "Clip not found"})
            continue
        if p.get("dry_run"):
            results.append({"clip_id": target_id, "success": True, "metadata_keys": sorted(metadata.keys()), "third_party_keys": sorted(third_party.keys())})
            continue
        ok = bool(target.SetMetadata(metadata)) if metadata else True
        third_party_ok = True
        for key, value in third_party.items():
            third_party_ok = bool(target.SetThirdPartyMetadata(key, value)) and third_party_ok
        results.append({"clip_id": target_id, "success": ok and third_party_ok})
    return {"success": all(row.get("success") for row in results), "results": results}


def _normalize_metadata(root, mp, p: Dict[str, Any]):
    resolved, err = _clips_from_params(root, mp, p)
    if err:
        return err
    clips, missing = resolved
    metadata = p.get("metadata") or {}
    third_party = p.get("third_party_metadata") or p.get("thirdPartyMetadata") or {}
    if not isinstance(metadata, dict) or not isinstance(third_party, dict):
        return _err("metadata and third_party_metadata must be objects")
    if not metadata and not third_party:
        return _err("Provide metadata or third_party_metadata")
    results = []
    for clip in clips:
        clip_id = _safe_media_pool_item_id(clip)
        if p.get("dry_run"):
            results.append({"clip_id": clip_id, "success": True, "metadata_keys": sorted(metadata.keys()), "third_party_keys": sorted(third_party.keys())})
            continue
        ok = bool(clip.SetMetadata(metadata)) if metadata else True
        third_party_ok = True
        for key, value in third_party.items():
            third_party_ok = bool(clip.SetThirdPartyMetadata(key, value)) and third_party_ok
        results.append({"clip_id": clip_id, "success": ok and third_party_ok})
    return {"success": all(row.get("success") for row in results), "count": len(results), "missing": missing, "results": results}


def _probe_clip_properties(root, mp, p: Dict[str, Any]):
    resolved, err = _clips_from_params(root, mp, p)
    if err:
        return err
    clips, missing = resolved
    return {
        "count": len(clips),
        "missing": missing,
        "items": [
            {
                "summary": _media_pool_item_summary(clip),
                "properties": _safe_clip_call(clip, "GetClipProperty", "")[0],
                "known_clip_properties": _media_pool_item_probe(clip)["known_clip_properties"],
            }
            for clip in clips
        ],
    }


def _safe_relink(mp, root, p: Dict[str, Any]):
    folder_path = p.get("folder_path")
    path_err = _path_error(folder_path, must_be_dir=True)
    if path_err:
        return _err(path_err)
    resolved, err = _clips_from_params(root, mp, p)
    if err:
        return err
    clips, missing = resolved
    if p.get("dry_run"):
        return _ok(folder_path=folder_path, clips=_clip_summaries(clips), missing=missing)
    return {"success": bool(mp.RelinkClips(clips, folder_path)), "count": len(clips), "missing": missing}


def _safe_unlink(mp, root, p: Dict[str, Any]):
    resolved, err = _clips_from_params(root, mp, p)
    if err:
        return err
    clips, missing = resolved
    if p.get("dry_run"):
        return _ok(clips=_clip_summaries(clips), missing=missing)
    return {"success": bool(mp.UnlinkClips(clips)), "count": len(clips), "missing": missing}


def _link_proxy_checked(root, p: Dict[str, Any]):
    clip = _find_clip(root, p.get("clip_id", ""))
    if not clip:
        return _err(f"Clip not found: {p.get('clip_id')}")
    proxy_path = p.get("proxy_path") or p.get("path")
    path_err = _path_error(proxy_path, must_be_file=True)
    if path_err:
        return _err(path_err)
    if p.get("dry_run"):
        return _ok(clip=_media_pool_item_summary(clip), proxy_path=proxy_path)
    return {"success": bool(clip.LinkProxyMedia(proxy_path))}


def _link_full_resolution_checked(root, p: Dict[str, Any]):
    clip = _find_clip(root, p.get("clip_id", ""))
    if not clip:
        return _err(f"Clip not found: {p.get('clip_id')}")
    missing = _requires_method(clip, "LinkFullResolutionMedia", "20.0")
    if missing:
        return missing
    path = p.get("path") or p.get("full_res_media_path") or p.get("fullResMediaPath")
    path_err = _path_error(path, must_be_file=True)
    if path_err:
        return _err(path_err)
    if p.get("dry_run"):
        return _ok(clip=_media_pool_item_summary(clip), path=path)
    return {"success": bool(clip.LinkFullResolutionMedia(path))}


def _set_clip_marks(root, mp, p: Dict[str, Any]):
    resolved, err = _clips_from_params(root, mp, p)
    if err:
        return err
    clips, missing = resolved
    try:
        mark_in = int(p["mark_in"])
        mark_out = int(p["mark_out"])
    except (KeyError, TypeError, ValueError):
        return _err("mark_in and mark_out must be integers")
    results = []
    for clip in clips:
        clip_id = _safe_media_pool_item_id(clip)
        if p.get("dry_run"):
            results.append({"clip_id": clip_id, "success": True, "mark_in": mark_in, "mark_out": mark_out})
            continue
        results.append({"clip_id": clip_id, "success": bool(clip.SetMarkInOut(mark_in, mark_out, p.get("type", "all")))})
    return {"success": all(row.get("success") for row in results), "count": len(results), "missing": missing, "results": results}


def _clear_clip_marks(root, mp, p: Dict[str, Any]):
    resolved, err = _clips_from_params(root, mp, p)
    if err:
        return err
    clips, missing = resolved
    results = []
    for clip in clips:
        clip_id = _safe_media_pool_item_id(clip)
        if p.get("dry_run"):
            results.append({"clip_id": clip_id, "success": True})
            continue
        results.append({"clip_id": clip_id, "success": bool(clip.ClearMarkInOut(p.get("type", "all")))})
    return {"success": all(row.get("success") for row in results), "count": len(results), "missing": missing, "results": results}


def _copy_clip_annotations(root, p: Dict[str, Any]):
    source = _find_clip(root, p.get("source_clip_id", ""))
    if not source:
        return _err(f"Source clip not found: {p.get('source_clip_id')}")
    target_ids = p.get("target_clip_ids")
    if not isinstance(target_ids, list) or not target_ids:
        return _err("target_clip_ids must be a non-empty list")
    markers = source.GetMarkers() or {}
    flags = source.GetFlagList() or []
    color = source.GetClipColor()
    include_markers = p.get("include_markers", True)
    include_flags = p.get("include_flags", True)
    include_color = p.get("include_clip_color", True)
    results = []
    for target_id in target_ids:
        target = _find_clip(root, str(target_id))
        if not target:
            results.append({"clip_id": target_id, "success": False, "error": "Clip not found"})
            continue
        if p.get("dry_run"):
            results.append({"clip_id": target_id, "success": True, "markers": len(markers), "flags": len(flags), "clip_color": color})
            continue
        ok = True
        if include_color and color:
            ok = bool(target.SetClipColor(color)) and ok
        if include_flags:
            for flag in flags:
                ok = bool(target.AddFlag(flag)) and ok
        if include_markers:
            for frame, marker in markers.items():
                custom = marker.get("customData") or marker.get("custom_data") or ""
                ok = bool(
                    target.AddMarker(
                        int(frame),
                        marker.get("color", "Blue"),
                        marker.get("name", ""),
                        marker.get("note", ""),
                        marker.get("duration", 1),
                        custom,
                    )
                ) and ok
        results.append({"clip_id": target_id, "success": ok})
    return {"success": all(row.get("success") for row in results), "results": results}


def _media_pool_boundary_report(mp, p: Dict[str, Any]):
    report = {
        "capabilities": _media_pool_ingest_capabilities(),
        "media_pool": _media_pool_probe(mp, {"depth": p.get("depth", 1)}),
    }
    if p.get("clip_ids") or p.get("selected"):
        report["items"] = _media_pool_probe_ingest_items(mp, p)
    return report


def _ser(obj):
    """Serialize Resolve API objects to JSON-safe values."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_ser(v) for v in obj]
    # Resolve API object — return repr
    return str(obj)

def _unknown(action, valid):
    return _err(f"Unknown action '{action}'. Valid actions: {', '.join(valid)}")


def _normalize_cdl(cdl):
    """Normalize CDL payloads to the string format Resolve's SetCDL expects."""
    return normalize_cdl_payload(cdl)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 1: resolve
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def resolve_control(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """App-level DaVinci Resolve operations.

    Actions:
      launch() -> {success, message}  — Launch DaVinci Resolve if not running. Call this FIRST if any tool returns a 'Not connected' error.
      get_version() -> {product, version, version_string}
      get_page() -> {page}
      open_page(page) -> {success}  — page: edit, cut, color, fusion, fairlight, deliver
      get_keyframe_mode() -> {mode}
      set_keyframe_mode(mode) -> {success}
      quit() -> {success}
      get_fairlight_presets() -> {presets}
      set_high_priority() -> {success}
    """
    p = params or {}

    # launch works even when Resolve is not connected
    if action == "launch":
        r = get_resolve()  # auto-launches if not running
        if r is not None:
            return _ok(message="DaVinci Resolve is running and connected.")
        return _err("Could not connect to DaVinci Resolve. Check that Resolve Studio is installed and 'External scripting using' is set to Local in Preferences.")

    r = get_resolve()  # auto-launches if not running
    if r is None:
        return _err("Could not connect to DaVinci Resolve after auto-launch attempt. Check that Resolve Studio is installed.")

    if action == "get_version":
        return {"product": r.GetProductName(), "version": r.GetVersion(), "version_string": r.GetVersionString()}
    elif action == "get_page":
        return {"page": r.GetCurrentPage()}
    elif action == "open_page":
        valid_pages = ["media", "cut", "edit", "color", "fusion", "fairlight", "deliver"]
        if p["page"] not in valid_pages:
            return _err(f"Invalid page '{p['page']}'. Valid pages: {', '.join(valid_pages)}")
        return {"success": bool(r.OpenPage(p["page"]))}
    elif action == "get_keyframe_mode":
        return {"mode": r.GetKeyframeMode()}
    elif action == "set_keyframe_mode":
        return {"success": bool(r.SetKeyframeMode(p["mode"]))}
    elif action == "quit":
        r.Quit()
        return _ok()
    elif action == "get_fairlight_presets":
        missing = _requires_method(r, "GetFairlightPresets", "20.2.2")
        if missing:
            return missing
        return {"presets": _ser(r.GetFairlightPresets())}
    elif action == "set_high_priority":
        return {"success": bool(r.SetHighPriority())}
    return _unknown(action, ["launch","get_version","get_page","open_page","get_keyframe_mode","set_keyframe_mode","quit","get_fairlight_presets","set_high_priority"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 2: layout_presets
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def layout_presets(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Manage DaVinci Resolve UI layout presets.

    Actions:
      save(name) -> {success}
      load(name) -> {success}
      update(name) -> {success}
      export(name, path) -> {success}
      import_preset(path, name?) -> {success}
      delete(name) -> {success}
    """
    p = params or {}
    r = get_resolve()
    if r is None:
        return _err("Could not connect to DaVinci Resolve. It was not running and auto-launch failed. Check that Resolve Studio is installed.")

    if action == "save":
        return {"success": bool(r.SaveLayoutPreset(p["name"]))}
    elif action == "load":
        return {"success": bool(r.LoadLayoutPreset(p["name"]))}
    elif action == "update":
        return {"success": bool(r.UpdateLayoutPreset(p["name"]))}
    elif action == "export":
        return {"success": bool(r.ExportLayoutPreset(p["name"], p["path"]))}
    elif action == "import_preset":
        if "name" in p:
            return {"success": bool(r.ImportLayoutPreset(p["path"], p["name"]))}
        return {"success": bool(r.ImportLayoutPreset(p["path"]))}
    elif action == "delete":
        return {"success": bool(r.DeleteLayoutPreset(p["name"]))}
    return _unknown(action, ["save","load","update","export","import_preset","delete"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 3: render_presets
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def render_presets(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Import/export render and burn-in presets.

    Actions:
      import_render(path) -> {success}
      export_render(name, path) -> {success}
      import_burnin(path) -> {success}
      export_burnin(name, path) -> {success}
    """
    p = params or {}
    r = get_resolve()
    if r is None:
        return _err("Could not connect to DaVinci Resolve. It was not running and auto-launch failed. Check that Resolve Studio is installed.")

    if action == "import_render":
        return {"success": bool(r.ImportRenderPreset(p["path"]))}
    elif action == "export_render":
        return {"success": bool(r.ExportRenderPreset(p["name"], p["path"]))}
    elif action == "import_burnin":
        return {"success": bool(r.ImportBurnInPreset(p["path"]))}
    elif action == "export_burnin":
        return {"success": bool(r.ExportBurnInPreset(p["name"], p["path"]))}
    return _unknown(action, ["import_render","export_render","import_burnin","export_burnin"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 4: project_manager
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def project_manager(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Manage DaVinci Resolve projects.

    Actions:
      list() -> {projects}
      get_current() -> {name, id}
      create(name, media_location_path?) -> {success, name}
      load(name) -> {success}
      save() -> {success}
      close() -> {success}
      delete(name) -> {success}
      import_project(path, name?) -> {success}
      export_project(name, path, with_stills_and_luts?) -> {success}
      archive(name, path, src_media?, render_cache?, proxy_media?) -> {success}
      restore(path, name?) -> {success}
    """
    p = params or {}
    r = get_resolve()
    if r is None:
        return _err("Could not connect to DaVinci Resolve. It was not running and auto-launch failed. Check that Resolve Studio is installed.")
    pm = r.GetProjectManager()

    if action == "list":
        return {"projects": pm.GetProjectListInCurrentFolder()}
    elif action == "get_current":
        proj = pm.GetCurrentProject()
        return {"name": proj.GetName(), "id": proj.GetUniqueId()} if proj else _err("No project open")
    elif action == "create":
        media_location_path = p.get("media_location_path") or p.get("mediaLocationPath")
        if media_location_path:
            version = r.GetVersion() or [0]
            if version[0] < 20 or (version[0] == 20 and len(version) > 2 and (version[1], version[2]) < (2, 2)):
                return _err("ProjectManager.CreateProject media_location_path requires DaVinci Resolve 20.2.2+")
        proj = pm.CreateProject(p["name"], media_location_path) if media_location_path else pm.CreateProject(p["name"])
        return _ok(name=proj.GetName()) if proj else _err(f"Failed to create '{p['name']}'")
    elif action == "load":
        proj = pm.LoadProject(p["name"])
        return _ok() if proj else _err(f"Failed to load '{p['name']}'")
    elif action == "save":
        return {"success": bool(pm.SaveProject())}
    elif action == "close":
        proj = pm.GetCurrentProject()
        return {"success": bool(pm.CloseProject(proj))} if proj else _err("No project open")
    elif action == "delete":
        return {"success": bool(pm.DeleteProject(p["name"]))}
    elif action == "import_project":
        return {"success": bool(pm.ImportProject(p["path"], p.get("name")))}
    elif action == "export_project":
        return {"success": bool(pm.ExportProject(p["name"], p["path"], p.get("with_stills_and_luts", True)))}
    elif action == "archive":
        return {"success": bool(pm.ArchiveProject(p["name"], p["path"],
            p.get("src_media", True), p.get("render_cache", True), p.get("proxy_media", False)))}
    elif action == "restore":
        return {"success": bool(pm.RestoreProject(p["path"], p.get("name")))}
    return _unknown(action, ["list","get_current","create","load","save","close","delete","import_project","export_project","archive","restore"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 5: project_manager_folders
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def project_manager_folders(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Navigate and manage project folders in the Project Manager.

    Actions:
      list() -> {folders}
      get_current() -> {folder}
      create(name) -> {success}
      delete(name) -> {success}
      open(name) -> {success}
      goto_root() -> {success}
      goto_parent() -> {success}
    """
    p = params or {}
    r = get_resolve()
    if r is None:
        return _err("Could not connect to DaVinci Resolve. It was not running and auto-launch failed. Check that Resolve Studio is installed.")
    pm = r.GetProjectManager()

    if action == "list":
        folders = pm.GetFolderListInCurrentFolder() or []
        return {"folders": [{"name": f.GetName(), "id": f.GetUniqueId()} for f in folders]}
    elif action == "get_current":
        folder = pm.GetCurrentFolder()
        if not folder:
            return _err("No current folder")
        return {"folder": {"name": folder.GetName(), "id": folder.GetUniqueId()}}
    elif action == "create":
        return {"success": bool(pm.CreateFolder(p["name"]))}
    elif action == "delete":
        return {"success": bool(pm.DeleteFolder(p["name"]))}
    elif action == "open":
        return {"success": bool(pm.OpenFolder(p["name"]))}
    elif action == "goto_root":
        return {"success": bool(pm.GotoRootFolder())}
    elif action == "goto_parent":
        return {"success": bool(pm.GotoParentFolder())}
    return _unknown(action, ["list","get_current","create","delete","open","goto_root","goto_parent"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 6: project_manager_cloud
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def project_manager_cloud(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Cloud project operations (requires DaVinci Resolve cloud infrastructure).

    Actions:
      create(settings) -> {success}  — settings: {CLOUD_SETTING_PROJECT_NAME, ...}
      load(settings) -> {success}
      import_project(path, settings) -> {success}
      restore(folder_path, settings) -> {success}
    """
    p = params or {}
    r = get_resolve()
    if r is None:
        return _err("Could not connect to DaVinci Resolve. It was not running and auto-launch failed. Check that Resolve Studio is installed.")
    pm = r.GetProjectManager()

    if action == "create":
        proj = pm.CreateCloudProject(p["settings"])
        return _ok(name=proj.GetName()) if proj else _err("Failed to create cloud project")
    elif action == "load":
        proj = pm.LoadCloudProject(p["settings"])
        return _ok(name=proj.GetName()) if proj else _err("Failed to load cloud project")
    elif action == "import_project":
        return {"success": bool(pm.ImportCloudProject(p["path"], p["settings"]))}
    elif action == "restore":
        return {"success": bool(pm.RestoreCloudProject(p["folder_path"], p["settings"]))}
    return _unknown(action, ["create","load","import_project","restore"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 7: project_manager_database
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def project_manager_database(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Manage DaVinci Resolve project databases.

    Actions:
      get_current() -> {db_type, db_name}
      list() -> {databases}
      set_current(db_info) -> {success}  — db_info: {DbType, DbName}
    """
    p = params or {}
    r = get_resolve()
    if r is None:
        return _err("Could not connect to DaVinci Resolve. It was not running and auto-launch failed. Check that Resolve Studio is installed.")
    pm = r.GetProjectManager()

    if action == "get_current":
        db = pm.GetCurrentDatabase()
        if not db:
            return _err("Failed to get current database")
        return {"db_type": db.get("DbType"), "db_name": db.get("DbName")}
    elif action == "list":
        return {"databases": pm.GetDatabaseList()}
    elif action == "set_current":
        return {"success": bool(pm.SetCurrentDatabase(p["db_info"]))}
    return _unknown(action, ["get_current","list","set_current"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 8: project_settings
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def project_settings(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Project metadata, settings, and color groups.

    Actions:
      get_name() -> {name}
      set_name(name) -> {success}
      get_setting(name?) -> {settings}  — omit name for all settings
      set_setting(name, value) -> {success}
      get_unique_id() -> {id}
      get_presets() -> {presets}
      set_preset(name) -> {success}
      refresh_luts() -> {success}
      get_gallery() -> {available}
      export_frame_as_still(path) -> {success}
      load_burnin_preset(name) -> {success}
      insert_audio(media_path, start_offset?, duration?) -> {success}
      get_color_groups() -> {groups}
      add_color_group(name) -> {success, name}
      delete_color_group(name) -> {success}
      apply_fairlight_preset(preset_name) -> {success}
    """
    p = params or {}
    _, proj, err = _check()
    if err:
        return err

    if action == "get_name":
        return {"name": proj.GetName()}
    elif action == "set_name":
        return {"success": bool(proj.SetName(p["name"]))}
    elif action == "get_setting":
        return {"settings": _ser(proj.GetSetting(p.get("name", "")))}
    elif action == "set_setting":
        return {"success": bool(proj.SetSetting(p["name"], p["value"]))}
    elif action == "get_unique_id":
        return {"id": proj.GetUniqueId()}
    elif action == "get_presets":
        return {"presets": _ser(proj.GetPresetList())}
    elif action == "set_preset":
        return {"success": bool(proj.SetPreset(p["name"]))}
    elif action == "refresh_luts":
        return {"success": bool(proj.RefreshLUTList())}
    elif action == "get_gallery":
        g = proj.GetGallery()
        return {"available": g is not None}
    elif action == "export_frame_as_still":
        return {"success": bool(proj.ExportCurrentFrameAsStill(p["path"]))}
    elif action == "load_burnin_preset":
        return {"success": bool(proj.LoadBurnInPreset(p["name"]))}
    elif action == "insert_audio":
        return {"success": bool(proj.InsertAudioToCurrentTrackAtPlayhead(
            p["media_path"], p.get("start_offset", 0), p.get("duration", 0)))}
    elif action == "get_color_groups":
        groups = proj.GetColorGroupsList()
        return {"groups": [{"name": g.GetName()} for g in (groups or [])]}
    elif action == "add_color_group":
        g = proj.AddColorGroup(p["name"])
        return _ok(name=g.GetName()) if g else _err("Failed to add color group")
    elif action == "delete_color_group":
        groups = proj.GetColorGroupsList() or []
        for g in groups:
            if g.GetName() == p["name"]:
                return {"success": bool(proj.DeleteColorGroup(g))}
        return _err(f"Color group '{p['name']}' not found")
    elif action == "apply_fairlight_preset":
        missing = _requires_method(proj, "ApplyFairlightPresetToCurrentTimeline", "20.2.2")
        if missing:
            return missing
        return {"success": bool(proj.ApplyFairlightPresetToCurrentTimeline(p["preset_name"]))}
    return _unknown(action, ["get_name","set_name","get_setting","set_setting","get_unique_id","get_presets","set_preset","refresh_luts","get_gallery","export_frame_as_still","load_burnin_preset","insert_audio","get_color_groups","add_color_group","delete_color_group","apply_fairlight_preset"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 9: render
# ═══════════════════════════════════════════════════════════════════════════════

_RENDER_METHODS = [
    "AddRenderJob",
    "DeleteRenderJob",
    "DeleteAllRenderJobs",
    "GetRenderJobList",
    "GetRenderJobStatus",
    "StartRendering",
    "StopRendering",
    "IsRenderingInProgress",
    "GetRenderFormats",
    "GetRenderCodecs",
    "GetCurrentRenderFormatAndCodec",
    "SetCurrentRenderFormatAndCodec",
    "GetCurrentRenderMode",
    "SetCurrentRenderMode",
    "GetRenderResolutions",
    "GetRenderSettings",
    "SetRenderSettings",
    "GetRenderPresetList",
    "LoadRenderPreset",
    "SaveAsNewRenderPreset",
    "DeleteRenderPreset",
    "GetQuickExportRenderPresets",
    "RenderWithQuickExport",
]

_RENDER_SETTING_KEYS = [
    "SelectAllFrames",
    "MarkIn",
    "MarkOut",
    "TargetDir",
    "CustomName",
    "UniqueFilenameStyle",
    "ExportVideo",
    "ExportAudio",
    "FormatWidth",
    "FormatHeight",
    "FrameRate",
    "PixelAspectRatio",
    "VideoQuality",
    "AudioCodec",
    "AudioBitDepth",
    "AudioSampleRate",
    "ColorSpaceTag",
    "GammaTag",
    "ExportAlpha",
    "EncodingProfile",
    "MultiPassEncode",
    "AlphaMode",
    "NetworkOptimization",
    "ClipStartFrame",
    "TimelineStartTimecode",
    "ReplaceExistingFilesInPlace",
    "ExportSubtitle",
    "SubtitleFormat",
]

_RENDER_KERNEL_ACTIONS = [
    "render_capabilities",
    "probe_render_matrix",
    "probe_render_settings",
    "validate_render_settings",
    "safe_set_render_settings",
    "prepare_render_job",
    "render_job_lifecycle_probe",
    "quick_export_capabilities",
    "safe_quick_export",
    "export_render_boundary_report",
]


def _render_temp_path_ok(path: str) -> bool:
    if not path:
        return False
    try:
        target = os.path.abspath(path)
        temp_roots = [
            os.path.abspath(tempfile.gettempdir()),
            os.path.abspath("/private/tmp"),
            os.path.abspath("/tmp"),
        ]
        return any(os.path.commonpath([target, root]) == root for root in temp_roots)
    except ValueError:
        return False


def _render_formats(proj):
    formats = proj.GetRenderFormats() or {}
    return _ser(formats)


def _render_codecs(proj, fmt: str):
    try:
        return _ser(proj.GetRenderCodecs(fmt) or {})
    except Exception as exc:
        return {"error": str(exc)}


def _render_capabilities(proj):
    formats = _render_formats(proj)
    presets = _ser(proj.GetRenderPresetList() or [])
    quick_presets = []
    if _has_method(proj, "GetQuickExportRenderPresets"):
        try:
            quick_presets = _ser(proj.GetQuickExportRenderPresets() or [])
        except Exception:
            quick_presets = []
    return {
        "methods": _callable_method_names(proj, _RENDER_METHODS),
        "formats": formats,
        "format_count": len(formats) if isinstance(formats, dict) else 0,
        "presets": presets,
        "quick_export_presets": quick_presets,
        "supported_settings": list(_RENDER_SETTING_KEYS),
        "guards": {
            "safe_quick_export_requires_allow_render": True,
            "temp_target_required_for_lifecycle_probe": True,
            "upload_disabled_for_safe_quick_export": True,
        },
    }


def _probe_render_matrix(proj, p: Dict[str, Any]):
    formats = _render_formats(proj)
    if not isinstance(formats, dict):
        return _err("GetRenderFormats did not return a format dictionary")
    requested = p.get("formats")
    if requested is not None and not isinstance(requested, list):
        return _err("formats must be a list when provided")
    max_pairs = p.get("max_pairs")
    try:
        max_pairs = int(max_pairs) if max_pairs is not None else None
    except (TypeError, ValueError):
        return _err("max_pairs must be an integer")
    matrix = []
    pair_count = 0
    errors = []
    for fmt, extension in formats.items():
        if requested and fmt not in requested:
            continue
        codecs = _render_codecs(proj, fmt)
        format_row = {"format": fmt, "extension": extension, "codecs": [], "codec_count": 0}
        if isinstance(codecs, dict) and codecs.get("error"):
            format_row["error"] = codecs["error"]
            errors.append({"format": fmt, "error": codecs["error"]})
            matrix.append(format_row)
            continue
        if isinstance(codecs, dict):
            format_row["codec_count"] = len(codecs)
            for label, codec in codecs.items():
                if max_pairs is not None and pair_count >= max_pairs:
                    break
                row = {"label": label, "codec": codec}
                try:
                    row["resolutions"] = _ser(proj.GetRenderResolutions(fmt, codec) or [])
                    row["resolution_count"] = len(row["resolutions"])
                except Exception as exc:
                    row["error"] = str(exc)
                    errors.append({"format": fmt, "codec": codec, "error": str(exc)})
                format_row["codecs"].append(row)
                pair_count += 1
        matrix.append(format_row)
        if max_pairs is not None and pair_count >= max_pairs:
            break
    return {
        "formats": len(matrix),
        "format_total": len(formats),
        "pairs_probed": pair_count,
        "errors": errors,
        "matrix": matrix,
    }


def _render_settings_snapshot(proj):
    if _has_method(proj, "GetRenderSettings"):
        settings = _ser(proj.GetRenderSettings())
    else:
        settings = {"error": "GetRenderSettings unavailable"}
    return {
        "format_and_codec": _ser(proj.GetCurrentRenderFormatAndCodec()),
        "mode": _ser(proj.GetCurrentRenderMode()),
        "settings": settings,
        "jobs": _ser(proj.GetRenderJobList() or []),
        "is_rendering": bool(proj.IsRenderingInProgress()),
    }


def _validate_render_settings_payload(settings: Dict[str, Any], *, require_temp_target: bool = False):
    if not isinstance(settings, dict) or not settings:
        return None, _err("settings must be a non-empty object")
    unknown = sorted(key for key in settings if key not in _RENDER_SETTING_KEYS)
    errors = []
    target_dir = settings.get("TargetDir")
    if target_dir is not None:
        if not isinstance(target_dir, str) or not target_dir:
            errors.append("TargetDir must be a non-empty string")
        elif not os.path.isdir(target_dir):
            errors.append(f"TargetDir does not exist: {target_dir}")
        elif require_temp_target and not _render_temp_path_ok(target_dir):
            errors.append("TargetDir must be under the system temp directory for this safe operation")
    elif require_temp_target:
        errors.append("TargetDir is required for this safe operation")
    for key in ("FormatWidth", "FormatHeight", "MarkIn", "MarkOut", "AudioBitDepth", "AudioSampleRate"):
        if key in settings and not isinstance(settings[key], int):
            errors.append(f"{key} must be an integer")
    for key in ("SelectAllFrames", "ExportVideo", "ExportAudio", "ExportAlpha", "MultiPassEncode", "NetworkOptimization", "ReplaceExistingFilesInPlace", "ExportSubtitle"):
        if key in settings and not isinstance(settings[key], bool):
            errors.append(f"{key} must be a boolean")
    if "MarkIn" in settings and "MarkOut" in settings and settings["MarkOut"] < settings["MarkIn"]:
        errors.append("MarkOut must be greater than or equal to MarkIn")
    result = {"valid": not errors, "unknown_keys": unknown, "errors": errors, "settings": dict(settings)}
    return result, None


def _validate_render_settings_action(p: Dict[str, Any]):
    validation, err = _validate_render_settings_payload(
        p.get("settings"),
        require_temp_target=bool(p.get("require_temp_target", False)),
    )
    if err:
        return err
    return validation


def _settings_diff(requested: Dict[str, Any], applied: Dict[str, Any]):
    if not isinstance(applied, dict):
        return {"matched": [], "coerced_or_missing": sorted(requested.keys())}
    matched = []
    coerced = {}
    for key, value in requested.items():
        if applied.get(key) == value:
            matched.append(key)
        else:
            coerced[key] = {"requested": value, "applied": applied.get(key)}
    return {"matched": sorted(matched), "coerced_or_missing": coerced}


def _safe_set_render_settings(proj, p: Dict[str, Any]):
    settings = p.get("settings")
    validation, err = _validate_render_settings_payload(
        settings,
        require_temp_target=bool(p.get("require_temp_target", False)),
    )
    if err:
        return err
    if not validation["valid"]:
        return {"success": False, "validation": validation}
    if p.get("dry_run"):
        return _ok(validation=validation)
    before = _render_settings_snapshot(proj)
    success = bool(proj.SetRenderSettings(settings))
    after_settings = _ser(proj.GetRenderSettings()) if _has_method(proj, "GetRenderSettings") else {}
    result = {
        "success": success,
        "validation": validation,
        "before": before,
        "after": after_settings,
        "diff": _settings_diff(settings, after_settings),
    }
    if p.get("restore") and isinstance(before.get("settings"), dict):
        result["restore_success"] = bool(proj.SetRenderSettings(before["settings"]))
    return result


def _prepare_render_job(proj, p: Dict[str, Any]):
    target_dir = p.get("target_dir") or (p.get("settings") or {}).get("TargetDir")
    if not target_dir:
        return _err("target_dir or settings.TargetDir is required")
    if not os.path.isdir(target_dir):
        return _err(f"target_dir does not exist: {target_dir}")
    if p.get("require_temp_target", True) and not _render_temp_path_ok(target_dir):
        return _err("target_dir must be under the system temp directory unless require_temp_target=False")
    settings = dict(p.get("settings") or {})
    settings.setdefault("TargetDir", target_dir)
    if p.get("custom_name"):
        settings["CustomName"] = p["custom_name"]
    validation, err = _validate_render_settings_payload(settings, require_temp_target=p.get("require_temp_target", True))
    if err:
        return err
    if not validation["valid"]:
        return {"success": False, "validation": validation}
    if p.get("dry_run"):
        return _ok(validation=validation, format=p.get("format"), codec=p.get("codec"))
    before = _render_settings_snapshot(proj)
    format_success = None
    if p.get("format") and p.get("codec"):
        format_success = bool(proj.SetCurrentRenderFormatAndCodec(p["format"], p["codec"]))
    settings_success = bool(proj.SetRenderSettings(settings))
    job_id = proj.AddRenderJob() if settings_success else None
    return {
        "success": bool(job_id),
        "job_id": job_id,
        "format_success": format_success,
        "settings_success": settings_success,
        "before": before,
        "settings": settings,
    }


def _render_job_lifecycle_probe(proj, p: Dict[str, Any]):
    prepared = _prepare_render_job(proj, {**p, "dry_run": False, "require_temp_target": True})
    if prepared.get("error") or not prepared.get("success"):
        return prepared
    job_id = prepared["job_id"]
    status_before = _ser(proj.GetRenderJobStatus(job_id))
    delete_success = bool(proj.DeleteRenderJob(job_id))
    return {
        "success": delete_success,
        "job_id": job_id,
        "status_before_delete": status_before,
        "delete_success": delete_success,
        "prepared": prepared,
    }


def _quick_export_capabilities(proj):
    presets = []
    if _has_method(proj, "GetQuickExportRenderPresets"):
        presets = _ser(proj.GetQuickExportRenderPresets() or [])
    return {
        "presets": presets,
        "preset_count": len(presets) if isinstance(presets, list) else 0,
        "safe_params": ["TargetDir", "CustomName", "VideoQuality", "EnableUpload"],
        "guards": {
            "EnableUpload_forced_false": True,
            "allow_render_required": True,
            "temp_target_required": True,
        },
    }


def _safe_quick_export(proj, p: Dict[str, Any]):
    preset = p.get("preset")
    if not preset:
        return _err("preset is required")
    params = dict(p.get("params") or {})
    target_dir = params.get("TargetDir") or p.get("target_dir")
    if target_dir:
        params["TargetDir"] = target_dir
    if p.get("custom_name"):
        params["CustomName"] = p["custom_name"]
    params["EnableUpload"] = False
    validation, err = _validate_render_settings_payload(
        {key: value for key, value in params.items() if key in _RENDER_SETTING_KEYS},
        require_temp_target=bool(p.get("require_temp_target", True)),
    )
    if err:
        return err
    if not validation["valid"]:
        return {"success": False, "validation": validation}
    if p.get("dry_run") or not p.get("allow_render", False):
        return _ok(would_render=False, preset=preset, params=params, validation=validation)
    status = _ser(proj.RenderWithQuickExport(preset, params))
    return {"success": not (isinstance(status, dict) and status.get("error")), "status": status, "params": params}


def _export_render_boundary_report(proj, p: Dict[str, Any]):
    report = {
        "capabilities": _render_capabilities(proj),
        "settings": _render_settings_snapshot(proj),
    }
    if p.get("include_matrix", True):
        report["matrix"] = _probe_render_matrix(proj, {"max_pairs": p.get("max_pairs")})
    if p.get("include_quick_export", True):
        report["quick_export"] = _quick_export_capabilities(proj)
    return report


@mcp.tool()
def render(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Render pipeline: jobs, presets, formats, codecs, and rendering.

    Actions:
      add_job() -> {job_id}
      delete_job(job_id) -> {success}
      delete_all_jobs() -> {success}
      list_jobs() -> {jobs}
      get_job_status(job_id) -> {status}
      start(job_ids?, interactive?) -> {success}
      stop() -> {success}
      is_rendering() -> {rendering}
      get_formats() -> {formats}
      get_codecs(format) -> {codecs}
      get_format_and_codec() -> {format, codec}
      set_format_and_codec(format, codec) -> {success}
      get_mode() -> {mode}
      set_mode(mode) -> {success}
      get_resolutions(format, codec) -> {resolutions}
      get_settings() -> {settings}  (alias for set_render_settings with get)
      set_settings(settings) -> {success}
      list_presets() -> {presets}
      load_preset(name) -> {success}
      save_preset(name) -> {success}
      delete_preset(name) -> {success}
      quick_export_presets() -> {presets}
      quick_export(preset, params?) -> {status}
      render_capabilities() -> {methods, formats, presets, quick_export_presets}
      probe_render_matrix(formats?, max_pairs?) -> {matrix, errors}
      probe_render_settings() -> {format_and_codec, mode, settings, jobs, is_rendering}
      validate_render_settings(settings, require_temp_target?) -> {valid, errors, unknown_keys}
      safe_set_render_settings(settings, dry_run?, restore?, require_temp_target?) -> {success, diff}
      prepare_render_job(target_dir, settings?, format?, codec?, custom_name?, dry_run?) -> {success, job_id}
      render_job_lifecycle_probe(target_dir, settings?, format?, codec?, custom_name?) -> {success, job_id, status_before_delete}
      quick_export_capabilities() -> {presets, safe_params, guards}
      safe_quick_export(preset, target_dir?|params?, custom_name?, dry_run?, allow_render?) -> {success, status}
      export_render_boundary_report(include_matrix?, max_pairs?, include_quick_export?) -> {capabilities, settings, matrix?}
    """
    p = params or {}
    _, proj, err = _check()
    if err:
        return err

    if action == "add_job":
        jid = proj.AddRenderJob()
        return {"job_id": jid} if jid else _err("Failed to add render job")
    elif action == "delete_job":
        return {"success": bool(proj.DeleteRenderJob(p["job_id"]))}
    elif action == "delete_all_jobs":
        return {"success": bool(proj.DeleteAllRenderJobs())}
    elif action == "list_jobs":
        return {"jobs": _ser(proj.GetRenderJobList())}
    elif action == "get_job_status":
        return _ser(proj.GetRenderJobStatus(p["job_id"]))
    elif action == "start":
        job_ids = p.get("job_ids")
        interactive = p.get("interactive", False)
        if job_ids:
            return {"success": bool(proj.StartRendering(job_ids, interactive))}
        return {"success": bool(proj.StartRendering(interactive))}
    elif action == "stop":
        proj.StopRendering()
        return _ok()
    elif action == "is_rendering":
        return {"rendering": bool(proj.IsRenderingInProgress())}
    elif action == "get_formats":
        return {"formats": _ser(proj.GetRenderFormats())}
    elif action == "get_codecs":
        return {"codecs": _ser(proj.GetRenderCodecs(p["format"]))}
    elif action == "get_format_and_codec":
        return _ser(proj.GetCurrentRenderFormatAndCodec())
    elif action == "set_format_and_codec":
        return {"success": bool(proj.SetCurrentRenderFormatAndCodec(p["format"], p["codec"]))}
    elif action == "get_mode":
        return {"mode": proj.GetCurrentRenderMode()}
    elif action == "set_mode":
        return {"success": bool(proj.SetCurrentRenderMode(p["mode"]))}
    elif action == "get_resolutions":
        return {"resolutions": _ser(proj.GetRenderResolutions(p["format"], p["codec"]))}
    elif action == "get_settings":
        missing = _requires_method(proj, "GetRenderSettings", "unknown")
        if missing:
            return missing
        return {"settings": _ser(proj.GetRenderSettings())}
    elif action == "set_settings":
        return {"success": bool(proj.SetRenderSettings(p["settings"]))}
    elif action == "list_presets":
        return {"presets": proj.GetRenderPresetList()}
    elif action == "load_preset":
        return {"success": bool(proj.LoadRenderPreset(p["name"]))}
    elif action == "save_preset":
        return {"success": bool(proj.SaveAsNewRenderPreset(p["name"]))}
    elif action == "delete_preset":
        return {"success": bool(proj.DeleteRenderPreset(p["name"]))}
    elif action == "quick_export_presets":
        return {"presets": proj.GetQuickExportRenderPresets()}
    elif action == "quick_export":
        return _ser(proj.RenderWithQuickExport(p["preset"], p.get("params", {})))
    elif action == "render_capabilities":
        return _render_capabilities(proj)
    elif action == "probe_render_matrix":
        return _probe_render_matrix(proj, p)
    elif action == "probe_render_settings":
        return _render_settings_snapshot(proj)
    elif action == "validate_render_settings":
        return _validate_render_settings_action(p)
    elif action == "safe_set_render_settings":
        return _safe_set_render_settings(proj, p)
    elif action == "prepare_render_job":
        return _prepare_render_job(proj, p)
    elif action == "render_job_lifecycle_probe":
        return _render_job_lifecycle_probe(proj, p)
    elif action == "quick_export_capabilities":
        return _quick_export_capabilities(proj)
    elif action == "safe_quick_export":
        return _safe_quick_export(proj, p)
    elif action == "export_render_boundary_report":
        return _export_render_boundary_report(proj, p)
    return _unknown(action, ["add_job","delete_job","delete_all_jobs","list_jobs","get_job_status","start","stop","is_rendering","get_formats","get_codecs","get_format_and_codec","set_format_and_codec","get_mode","set_mode","get_resolutions","get_settings","set_settings","list_presets","load_preset","save_preset","delete_preset","quick_export_presets","quick_export",*_RENDER_KERNEL_ACTIONS])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 10: media_storage
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def media_storage(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Browse storage volumes and import media into the Media Pool.

    Actions:
      get_volumes() -> {volumes}
      get_subfolders(path) -> {subfolders}
      get_files(path) -> {files}
      reveal(path) -> {success}
      import_to_pool(items) -> {imported}
        — simple: params.items is a list of absolute file/folder paths
      import_to_pool(item_infos) -> {imported}
        — positioned: params.item_infos is a list of {media, startFrame, endFrame}
          dicts per docs line 210. Mirrors MediaStorage.AddItemListToMediaPool([{itemInfo}, ...]).
      add_clip_mattes(clip_id, paths, stereo_eye?) -> {success}
      add_timeline_mattes(paths) -> {items}
    """
    p = params or {}
    r = get_resolve()
    if r is None:
        return _err("Could not connect to DaVinci Resolve. It was not running and auto-launch failed. Check that Resolve Studio is installed.")
    ms = r.GetMediaStorage()

    if action == "get_volumes":
        return {"volumes": ms.GetMountedVolumeList()}
    elif action == "get_subfolders":
        return {"subfolders": ms.GetSubFolderList(p["path"])}
    elif action == "get_files":
        return {"files": ms.GetFileList(p["path"])}
    elif action == "reveal":
        return {"success": bool(ms.RevealInStorage(p["path"]))}
    elif action == "import_to_pool":
        if p.get("item_infos") is not None:
            raw = p["item_infos"]
            if not isinstance(raw, list) or not raw:
                return _err("item_infos must be a non-empty list")
            for i, info in enumerate(raw):
                if not isinstance(info, dict):
                    return _err(f"item_infos[{i}] must be an object")
                if not info.get("media"):
                    return _err(f"item_infos[{i}] requires media (file path)")
            result = ms.AddItemListToMediaPool(raw)
        else:
            items = p.get("items")
            if not items:
                return _err("Provide items (simple) or item_infos (positioned)")
            result = ms.AddItemListToMediaPool(items)
        return {"imported": len(result) if result else 0}
    elif action == "add_clip_mattes":
        _, proj, mp, err = _get_mp()
        if err:
            return err
        clip = _find_clip(mp.GetRootFolder(), p["clip_id"])
        if not clip:
            return _err(f"Clip not found: {p['clip_id']}")
        eye = p.get("stereo_eye", "")
        return {"success": bool(ms.AddClipMattesToMediaPool(clip, p["paths"], eye))}
    elif action == "add_timeline_mattes":
        result = ms.AddTimelineMattesToMediaPool(p["paths"])
        return {"items": len(result) if result else 0}
    return _unknown(action, ["get_volumes","get_subfolders","get_files","reveal","import_to_pool","add_clip_mattes","add_timeline_mattes"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 11: media_pool
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def media_pool(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Manage the Media Pool: folders, clips, timelines, import/export.

    Actions:
      get_root_folder() -> {name, id}
      get_current_folder() -> {name, id}
      set_current_folder(path) -> {success}  — path like "Master/SubFolder"
      add_subfolder(name, parent_path?) -> {success, name, id}
      delete_folders(folder_ids) -> {success}
      move_folders(folder_ids, target_path) -> {success}
      refresh() -> {success}
      create_timeline(name) -> {success, name, id}
      create_timeline_from_clips(name, clip_ids) -> {success, name, id}
        — simple: params.clip_ids appends clips end-to-end into a new timeline
      create_timeline_from_clips(name, clip_infos) -> {success, name, id}
        — positioned: params.clip_infos is a list of {clip_id or media_pool_item_id,
          start_frame & end_frame (or startFrame/endFrame), record_frame/recordFrame}.
          Matches MediaPool.CreateTimelineFromClips(name, [{clipInfo}, ...]).
      import_timeline(path, options?) -> {success, name}
      delete_timelines(timeline_ids) -> {success}
      append_to_timeline(clip_ids) -> {success, count}
        — legacy: params.clip_ids only (appends at end / default placement)
      append_to_timeline(clip_infos) -> {success, count, items}
        — positioned: params.clip_infos is a list of {clip_id or media_pool_item_id,
          start_frame & end_frame (or startFrame/endFrame), record_frame/recordFrame,
          track_index/trackIndex (1-based), optional media_type/mediaType (1=video, 2=audio)}.
          Matches MediaPool.AppendToTimeline([{clipInfo}, ...]). Returns timeline_item_id per item.
      import_media(paths) -> {imported}
        — simple: params.paths is a list of file/folder paths
      import_media(clip_infos) -> {imported}
        — image sequences: params.clip_infos is a list of
          {FilePath, StartIndex, EndIndex} dicts (PascalCase keys per Resolve docs).
          Example: [{"FilePath": "frame_%03d.dpx", "StartIndex": 1, "EndIndex": 100}]
      delete_clips(clip_ids) -> {success}
      move_clips(clip_ids, target_path) -> {success}
      relink(clip_ids, folder_path) -> {success}
      unlink(clip_ids) -> {success}
      export_metadata(path, clip_ids?) -> {success}
      get_unique_id() -> {id}
      create_stereo_clip(left_id, right_id) -> {success, name}
      auto_sync_audio(clip_ids, settings?) -> {success}
      get_selected() -> {clips}
      set_selected(clip_id) -> {success}
      get_clip_mattes(clip_id) -> {mattes}
      get_timeline_mattes(folder_path?) -> {mattes}
      delete_clip_mattes(clip_id, paths) -> {success}
      import_folder(path, source_clips_path?) -> {success}
      ingest_capabilities() -> {supported, partially_supported, unsupported}
      probe_media_pool(depth?) -> {media_pool_id, methods, root, current_folder, selected_clips}
      probe_ingest_item(clip_ids? selected?) -> {items, count}
      safe_import_media(paths, target_folder?, dry_run?) -> {success, imported, clips}
      safe_import_sequence(FilePath|file_path|pattern, StartIndex?, EndIndex?, target_folder?, dry_run?) -> {success, imported, clips}
      safe_import_folder(path, source_clips_path?, dry_run?) -> {success}
      organize_clips(clip_ids|selected, target_path, create_missing?, dry_run?) -> {success}
      copy_metadata(source_clip_id, target_clip_ids, keys?, include_third_party?, dry_run?) -> {success, results}
      normalize_metadata(clip_ids|selected, metadata?, third_party_metadata?, dry_run?) -> {success, results}
      probe_clip_properties(clip_ids|selected) -> {items, count}
      safe_relink(clip_ids|selected, folder_path, dry_run?) -> {success}
      safe_unlink(clip_ids|selected, dry_run?) -> {success}
      link_proxy_checked(clip_id, proxy_path|path, dry_run?) -> {success}
      link_full_resolution_checked(clip_id, path|full_res_media_path, dry_run?) -> {success}
      set_clip_marks(clip_ids|selected, mark_in, mark_out, type?, dry_run?) -> {success, results}
      clear_clip_marks(clip_ids|selected, type?, dry_run?) -> {success, results}
      copy_clip_annotations(source_clip_id, target_clip_ids, include_markers?, include_flags?, include_clip_color?, dry_run?) -> {success, results}
      media_pool_boundary_report(depth?, clip_ids?, selected?) -> {capabilities, media_pool, items?}
    """
    p = params or {}
    _, proj, mp, err = _get_mp()
    if err:
        return err
    root = mp.GetRootFolder()

    if action == "get_root_folder":
        return {"name": root.GetName(), "id": root.GetUniqueId()}
    elif action == "get_current_folder":
        f = mp.GetCurrentFolder()
        return {"name": f.GetName(), "id": f.GetUniqueId()} if f else _err("No current folder")
    elif action == "set_current_folder":
        f = _navigate_folder(mp, p.get("path", ""))
        if not f:
            return _err(f"Folder not found: {p.get('path')}")
        return {"success": bool(mp.SetCurrentFolder(f))}
    elif action == "add_subfolder":
        parent = _navigate_folder(mp, p.get("parent_path", "")) or mp.GetCurrentFolder()
        f = mp.AddSubFolder(parent, p["name"])
        return _ok(name=f.GetName(), id=f.GetUniqueId()) if f else _err("Failed to create subfolder")
    elif action == "delete_folders":
        folders = []
        for fid in p["folder_ids"]:
            # Search for folder by ID (simplified - searches root subfolders)
            for sub in (root.GetSubFolderList() or []):
                if sub.GetUniqueId() == fid:
                    folders.append(sub)
        return {"success": bool(mp.DeleteFolders(folders))} if folders else _err("No folders found")
    elif action == "move_folders":
        target = _navigate_folder(mp, p["target_path"])
        if not target:
            return _err(f"Target folder not found: {p['target_path']}")
        folders = []
        for fid in p["folder_ids"]:
            for sub in (root.GetSubFolderList() or []):
                if sub.GetUniqueId() == fid:
                    folders.append(sub)
        return {"success": bool(mp.MoveFolders(folders, target))}
    elif action == "refresh":
        return {"success": bool(mp.RefreshFolders())}
    elif action == "create_timeline":
        tl = mp.CreateEmptyTimeline(p["name"])
        return _ok(name=tl.GetName(), id=tl.GetUniqueId()) if tl else _err("Failed to create timeline")
    elif action == "create_timeline_from_clips":
        if p.get("clip_infos") is not None:
            raw = p["clip_infos"]
            if not isinstance(raw, list):
                return _err("clip_infos must be a list")
            if not raw:
                return _err("clip_infos must be a non-empty list")
            built = []
            for i, ci in enumerate(raw):
                row, row_err = _build_create_clip_info_dict(root, ci, i)
                if row_err:
                    return row_err
                built.append(row)
            tl = mp.CreateTimelineFromClips(p["name"], built)
            return _ok(name=tl.GetName(), id=tl.GetUniqueId()) if tl else _err("Failed to create timeline from clip_infos")
        clip_ids = p.get("clip_ids")
        if not clip_ids:
            return _err("Provide clip_ids (simple) or clip_infos (positioned)")
        clips = [_find_clip(root, cid) for cid in clip_ids]
        clips = [c for c in clips if c]
        if not clips:
            return _err("No valid clips found")
        tl = mp.CreateTimelineFromClips(p["name"], clips)
        return _ok(name=tl.GetName(), id=tl.GetUniqueId()) if tl else _err("Failed to create timeline")
    elif action == "import_timeline":
        tl = mp.ImportTimelineFromFile(p["path"], p.get("options", {}))
        return _ok(name=tl.GetName()) if tl else _err("Failed to import timeline")
    elif action == "delete_timelines":
        count = proj.GetTimelineCount()
        timelines = []
        for i in range(1, count + 1):
            tl = proj.GetTimelineByIndex(i)
            if tl and tl.GetUniqueId() in p["timeline_ids"]:
                timelines.append(tl)
        return {"success": bool(mp.DeleteTimelines(timelines))} if timelines else _err("No timelines found")
    elif action == "append_to_timeline":
        if p.get("clip_infos") is not None:
            raw = p["clip_infos"]
            if not isinstance(raw, list):
                return _err("clip_infos must be a list")
            if not raw:
                return _err("clip_infos must be a non-empty list")
            built = []
            for i, ci in enumerate(raw):
                row, row_err = _build_append_clip_info_dict(root, ci, i)
                if row_err:
                    return row_err
                built.append(row)
            result = mp.AppendToTimeline(built)
            if not result:
                return _err("Failed to append clip_infos to timeline")
            items_out = []
            for i, item in enumerate(result):
                item_out, item_err = _serialize_appended_timeline_item(item, i)
                if item_err:
                    return item_err
                items_out.append(item_out)
            return _ok(count=len(result), items=items_out)
        clip_ids = p.get("clip_ids")
        if not clip_ids:
            return _err("Provide clip_ids (simple append) or clip_infos (positioned append)")
        clips = [_find_clip(root, cid) for cid in clip_ids]
        clips = [c for c in clips if c]
        result = mp.AppendToTimeline(clips)
        return _ok(count=len(result) if result else 0)
    elif action == "import_media":
        if p.get("clip_infos") is not None:
            raw = p["clip_infos"]
            if not isinstance(raw, list) or not raw:
                return _err("clip_infos must be a non-empty list")
            for i, ci in enumerate(raw):
                if not isinstance(ci, dict):
                    return _err(f"clip_infos[{i}] must be an object")
                if not ci.get("FilePath"):
                    return _err(f"clip_infos[{i}] requires FilePath")
            result = mp.ImportMedia(raw)
        else:
            paths = p.get("paths")
            if not paths:
                return _err("Provide paths (simple) or clip_infos (image sequences)")
            result = mp.ImportMedia(paths)
        return {"imported": len(result) if result else 0}
    elif action == "delete_clips":
        clips = [_find_clip(root, cid) for cid in p["clip_ids"]]
        clips = [c for c in clips if c]
        return {"success": bool(mp.DeleteClips(clips))} if clips else _err("No clips found")
    elif action == "move_clips":
        target = _navigate_folder(mp, p["target_path"])
        if not target:
            return _err(f"Target folder not found: {p['target_path']}")
        clips = [_find_clip(root, cid) for cid in p["clip_ids"]]
        clips = [c for c in clips if c]
        return {"success": bool(mp.MoveClips(clips, target))}
    elif action == "relink":
        clips = [_find_clip(root, cid) for cid in p["clip_ids"]]
        clips = [c for c in clips if c]
        return {"success": bool(mp.RelinkClips(clips, p["folder_path"]))}
    elif action == "unlink":
        clips = [_find_clip(root, cid) for cid in p["clip_ids"]]
        clips = [c for c in clips if c]
        return {"success": bool(mp.UnlinkClips(clips))}
    elif action == "export_metadata":
        clip_ids = p.get("clip_ids")
        if clip_ids:
            clips = [_find_clip(root, cid) for cid in clip_ids]
            clips = [c for c in clips if c]
            return {"success": bool(mp.ExportMetadata(p["path"], clips))}
        return {"success": bool(mp.ExportMetadata(p["path"]))}
    elif action == "get_unique_id":
        return {"id": mp.GetUniqueId()}
    elif action == "create_stereo_clip":
        left = _find_clip(root, p["left_id"])
        right = _find_clip(root, p["right_id"])
        if not left or not right:
            return _err("Left or right clip not found")
        result = mp.CreateStereoClip(left, right)
        return _ok(name=result.GetName()) if result else _err("Failed to create stereo clip")
    elif action == "auto_sync_audio":
        clips = [_find_clip(root, cid) for cid in p["clip_ids"]]
        clips = [c for c in clips if c]
        return {"success": bool(mp.AutoSyncAudio(clips, p.get("settings", {})))}
    elif action == "get_selected":
        sel = mp.GetSelectedClips()
        if not sel:
            return {"clips": []}
        return {"clips": [{"name": c.GetName(), "id": c.GetUniqueId()} for c in sel]}
    elif action == "set_selected":
        clip = _find_clip(root, p["clip_id"])
        return {"success": bool(mp.SetSelectedClip(clip))} if clip else _err("Clip not found")
    elif action == "get_clip_mattes":
        clip = _find_clip(root, p["clip_id"])
        return {"mattes": mp.GetClipMatteList(clip)} if clip else _err("Clip not found")
    elif action == "get_timeline_mattes":
        folder = _navigate_folder(mp, p.get("folder_path", "")) or mp.GetCurrentFolder()
        result = mp.GetTimelineMatteList(folder)
        return {"mattes": len(result) if result else 0}
    elif action == "delete_clip_mattes":
        clip = _find_clip(root, p["clip_id"])
        if not clip:
            return _err("Clip not found")
        return {"success": bool(mp.DeleteClipMattes(clip, p["paths"]))}
    elif action == "import_folder":
        return {"success": bool(mp.ImportFolderFromFile(p["path"], p.get("source_clips_path", "")))}
    elif action == "ingest_capabilities":
        return _media_pool_ingest_capabilities()
    elif action == "probe_media_pool":
        return _media_pool_probe(mp, p)
    elif action == "probe_ingest_item":
        return _media_pool_probe_ingest_items(mp, p)
    elif action == "safe_import_media":
        return _safe_import_media(mp, p)
    elif action == "safe_import_sequence":
        return _safe_import_sequence(mp, p)
    elif action == "safe_import_folder":
        return _safe_import_folder(mp, p)
    elif action == "organize_clips":
        return _organize_clips(mp, root, p)
    elif action == "copy_metadata":
        return _copy_metadata(root, p)
    elif action == "normalize_metadata":
        return _normalize_metadata(root, mp, p)
    elif action == "probe_clip_properties":
        return _probe_clip_properties(root, mp, p)
    elif action == "safe_relink":
        return _safe_relink(mp, root, p)
    elif action == "safe_unlink":
        return _safe_unlink(mp, root, p)
    elif action == "link_proxy_checked":
        return _link_proxy_checked(root, p)
    elif action == "link_full_resolution_checked":
        return _link_full_resolution_checked(root, p)
    elif action == "set_clip_marks":
        return _set_clip_marks(root, mp, p)
    elif action == "clear_clip_marks":
        return _clear_clip_marks(root, mp, p)
    elif action == "copy_clip_annotations":
        return _copy_clip_annotations(root, p)
    elif action == "media_pool_boundary_report":
        return _media_pool_boundary_report(mp, p)
    return _unknown(action, ["get_root_folder","get_current_folder","set_current_folder","add_subfolder","delete_folders","move_folders","refresh","create_timeline","create_timeline_from_clips","import_timeline","delete_timelines","append_to_timeline","import_media","delete_clips","move_clips","relink","unlink","export_metadata","get_unique_id","create_stereo_clip","auto_sync_audio","get_selected","set_selected","get_clip_mattes","get_timeline_mattes","delete_clip_mattes","import_folder",*_MEDIA_POOL_KERNEL_ACTIONS])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 12: folder
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def folder(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Operations on Media Pool folders.

    Actions:
      get_clips(path?) -> {clips}  — path like "Master/SubFolder", omit for current
      get_name(path?) -> {name}
      get_subfolders(path?) -> {subfolders}
      is_stale(path?) -> {stale}
      get_unique_id(path?) -> {id}
      export(path?, export_path) -> {success}
      transcribe_audio(path?) -> {success}
      clear_transcription(path?) -> {success}
    """
    p = params or {}
    _, _, mp, err = _get_mp()
    if err:
        return err

    folder_path = p.get("path", "")
    f = _navigate_folder(mp, folder_path) if folder_path else mp.GetCurrentFolder()
    if not f:
        return _err(f"Folder not found: {folder_path}")

    if action == "get_clips":
        clips = f.GetClipList() or []
        return {"clips": [{"name": c.GetName(), "id": c.GetUniqueId()} for c in clips]}
    elif action == "get_name":
        return {"name": f.GetName()}
    elif action == "get_subfolders":
        subs = f.GetSubFolderList() or []
        return {"subfolders": [{"name": s.GetName(), "id": s.GetUniqueId()} for s in subs]}
    elif action == "is_stale":
        return {"stale": bool(f.GetIsFolderStale())}
    elif action == "get_unique_id":
        return {"id": f.GetUniqueId()}
    elif action == "export":
        return {"success": bool(f.Export(p["export_path"]))}
    elif action == "transcribe_audio":
        return {"success": bool(f.TranscribeAudio())}
    elif action == "clear_transcription":
        return {"success": bool(f.ClearTranscription())}
    return _unknown(action, ["get_clips","get_name","get_subfolders","is_stale","get_unique_id","export","transcribe_audio","clear_transcription"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 13: media_pool_item
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def media_pool_item(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Operations on a media pool clip. Identify clip by clip_id.

    Actions:
      get_name(clip_id) -> {name}
      get_metadata(clip_id, key?) -> {metadata}
      set_metadata(clip_id, key, value) OR set_metadata(clip_id, metadata) -> {success}
      get_third_party_metadata(clip_id, key?) -> {metadata}
      set_third_party_metadata(clip_id, key, value) -> {success}
      get_media_id(clip_id) -> {media_id}
      get_clip_property(clip_id, key?) -> {properties}
      set_clip_property(clip_id, key, value) -> {success}
      get_clip_color(clip_id) -> {color}
      set_clip_color(clip_id, color) -> {success}
      clear_clip_color(clip_id) -> {success}
      link_proxy(clip_id, proxy_path) -> {success}
      unlink_proxy(clip_id) -> {success}
      replace_clip(clip_id, path) -> {success}
      set_name(clip_id, name) -> {success}
      link_full_resolution_media(clip_id, path) -> {success}
      monitor_growing_file(clip_id) -> {success}
      replace_clip_preserve_sub_clip(clip_id, path) -> {success}
      get_unique_id(clip_id) -> {id}
      transcribe_audio(clip_id) -> {success}
      clear_transcription(clip_id) -> {success}
      get_audio_mapping(clip_id) -> {mapping}
      get_mark_in_out(clip_id) -> {mark}
      set_mark_in_out(clip_id, mark_in, mark_out, type?) -> {success}
      clear_mark_in_out(clip_id, type?) -> {success}
    """
    p = params or {}
    _, _, mp, err = _get_mp()
    if err:
        return err

    clip = _find_clip(mp.GetRootFolder(), p.get("clip_id", ""))
    if not clip:
        return _err(f"Clip not found: {p.get('clip_id')}")

    if action == "get_name":
        return {"name": clip.GetName()}
    elif action == "get_metadata":
        return {"metadata": _ser(clip.GetMetadata(p.get("key", "")))}
    elif action == "set_metadata":
        if "metadata" in p:
            return {"success": bool(clip.SetMetadata(p["metadata"]))}
        return {"success": bool(clip.SetMetadata(p["key"], p["value"]))}
    elif action == "get_third_party_metadata":
        return {"metadata": _ser(clip.GetThirdPartyMetadata(p.get("key", "")))}
    elif action == "set_third_party_metadata":
        return {"success": bool(clip.SetThirdPartyMetadata(p["key"], p["value"]))}
    elif action == "get_media_id":
        return {"media_id": clip.GetMediaId()}
    elif action == "get_clip_property":
        return {"properties": _ser(clip.GetClipProperty(p.get("key", "")))}
    elif action == "set_clip_property":
        return {"success": bool(clip.SetClipProperty(p["key"], p["value"]))}
    elif action == "get_clip_color":
        return {"color": clip.GetClipColor()}
    elif action == "set_clip_color":
        return {"success": bool(clip.SetClipColor(p["color"]))}
    elif action == "clear_clip_color":
        return {"success": bool(clip.ClearClipColor())}
    elif action == "link_proxy":
        return {"success": bool(clip.LinkProxyMedia(p["proxy_path"]))}
    elif action == "unlink_proxy":
        return {"success": bool(clip.UnlinkProxyMedia())}
    elif action == "replace_clip":
        return {"success": bool(clip.ReplaceClip(p["path"]))}
    elif action == "set_name":
        missing = _requires_method(clip, "SetName", "20.2")
        if missing:
            return missing
        return {"success": bool(clip.SetName(p["name"]))}
    elif action == "link_full_resolution_media":
        missing = _requires_method(clip, "LinkFullResolutionMedia", "20.0")
        if missing:
            return missing
        full_res_path = p.get("path") or p.get("full_res_media_path") or p.get("fullResMediaPath")
        if not full_res_path:
            return _err("Provide path or full_res_media_path")
        return {"success": bool(clip.LinkFullResolutionMedia(full_res_path))}
    elif action == "monitor_growing_file":
        missing = _requires_method(clip, "MonitorGrowingFile", "20.0")
        if missing:
            return missing
        return {"success": bool(clip.MonitorGrowingFile())}
    elif action == "replace_clip_preserve_sub_clip":
        missing = _requires_method(clip, "ReplaceClipPreserveSubClip", "20.0")
        if missing:
            return missing
        replacement_path = p.get("path") or p.get("file_path") or p.get("filePath")
        if not replacement_path:
            return _err("Provide path or file_path")
        return {"success": bool(clip.ReplaceClipPreserveSubClip(replacement_path))}
    elif action == "get_unique_id":
        return {"id": clip.GetUniqueId()}
    elif action == "transcribe_audio":
        return {"success": bool(clip.TranscribeAudio())}
    elif action == "clear_transcription":
        return {"success": bool(clip.ClearTranscription())}
    elif action == "get_audio_mapping":
        return {"mapping": clip.GetAudioMapping()}
    elif action == "get_mark_in_out":
        return _ser(clip.GetMarkInOut())
    elif action == "set_mark_in_out":
        return {"success": bool(clip.SetMarkInOut(p["mark_in"], p["mark_out"], p.get("type", "all")))}
    elif action == "clear_mark_in_out":
        return {"success": bool(clip.ClearMarkInOut(p.get("type", "all")))}
    return _unknown(action, ["get_name","get_metadata","set_metadata","get_third_party_metadata","set_third_party_metadata","get_media_id","get_clip_property","set_clip_property","get_clip_color","set_clip_color","clear_clip_color","link_proxy","unlink_proxy","replace_clip","set_name","link_full_resolution_media","monitor_growing_file","replace_clip_preserve_sub_clip","get_unique_id","transcribe_audio","clear_transcription","get_audio_mapping","get_mark_in_out","set_mark_in_out","clear_mark_in_out"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 14: media_pool_item_markers
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def media_pool_item_markers(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Markers and flags on media pool clips. Identify clip by clip_id.

    Actions:
      add(clip_id, frame|frame_id|frameId, color?, name?, note?, duration?, custom_data?) -> {success, frame}
      get_all(clip_id) -> {markers}
      get_by_custom_data(clip_id, custom_data) -> {markers}
      update_custom_data(clip_id, frame|frame_id|frameId, custom_data) -> {success}
      get_custom_data(clip_id, frame|frame_id|frameId) -> {data}
      delete_by_color(clip_id, color) -> {success}
      delete_at_frame(clip_id, frame|frame_id|frameId) -> {success}
      delete_by_custom_data(clip_id, custom_data) -> {success}
      add_flag(clip_id, color) -> {success}
      get_flags(clip_id) -> {flags}
      clear_flags(clip_id, color) -> {success}
      set_name(clip_id, name) -> {success}
      link_full_resolution_media(clip_id, path) -> {success}
      monitor_growing_file(clip_id) -> {success}
      replace_clip_preserve_sub_clip(clip_id, path) -> {success}
    """
    p = params or {}
    _, _, mp, err = _get_mp()
    if err:
        return err
    clip = _find_clip(mp.GetRootFolder(), p.get("clip_id", ""))
    if not clip:
        return _err(f"Clip not found: {p.get('clip_id')}")

    if action == "add":
        marker, marker_err = _marker_add_payload(p)
        if marker_err:
            return marker_err
        return _add_marker(clip, marker)
    elif action == "get_all":
        return {"markers": _ser(clip.GetMarkers())}
    elif action == "get_by_custom_data":
        return {"markers": _ser(clip.GetMarkerByCustomData(_first_param(p, "custom_data", "customData", default="")))}
    elif action == "update_custom_data":
        frame, frame_err = _marker_frame_from_params(p)
        if frame_err:
            return frame_err
        return {"success": bool(clip.UpdateMarkerCustomData(frame, _first_param(p, "custom_data", "customData", default="")))}
    elif action == "get_custom_data":
        frame, frame_err = _marker_frame_from_params(p)
        if frame_err:
            return frame_err
        return {"data": clip.GetMarkerCustomData(frame)}
    elif action == "delete_by_color":
        return {"success": bool(clip.DeleteMarkersByColor(p["color"]))}
    elif action == "delete_at_frame":
        frame, frame_err = _marker_frame_from_params(p)
        if frame_err:
            return frame_err
        return {"success": bool(clip.DeleteMarkerAtFrame(frame))}
    elif action == "delete_by_custom_data":
        return {"success": bool(clip.DeleteMarkerByCustomData(_first_param(p, "custom_data", "customData", default="")))}
    elif action == "add_flag":
        return {"success": bool(clip.AddFlag(p["color"]))}
    elif action == "get_flags":
        return {"flags": clip.GetFlagList()}
    elif action == "clear_flags":
        return {"success": bool(clip.ClearFlags(p["color"]))}
    elif action == "set_name":
        missing = _requires_method(clip, "SetName", "20.2")
        if missing:
            return missing
        return {"success": bool(clip.SetName(p["name"]))}
    elif action == "link_full_resolution_media":
        missing = _requires_method(clip, "LinkFullResolutionMedia", "20.0")
        if missing:
            return missing
        full_res_path = p.get("path") or p.get("full_res_media_path") or p.get("fullResMediaPath")
        if not full_res_path:
            return _err("Provide path or full_res_media_path")
        return {"success": bool(clip.LinkFullResolutionMedia(full_res_path))}
    elif action == "monitor_growing_file":
        missing = _requires_method(clip, "MonitorGrowingFile", "20.0")
        if missing:
            return missing
        return {"success": bool(clip.MonitorGrowingFile())}
    elif action == "replace_clip_preserve_sub_clip":
        missing = _requires_method(clip, "ReplaceClipPreserveSubClip", "20.0")
        if missing:
            return missing
        replacement_path = p.get("path") or p.get("file_path") or p.get("filePath")
        if not replacement_path:
            return _err("Provide path or file_path")
        return {"success": bool(clip.ReplaceClipPreserveSubClip(replacement_path))}
    return _unknown(action, ["add","get_all","get_by_custom_data","update_custom_data","get_custom_data","delete_by_color","delete_at_frame","delete_by_custom_data","add_flag","get_flags","clear_flags","set_name","link_full_resolution_media","monitor_growing_file","replace_clip_preserve_sub_clip"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 15: timeline
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def timeline(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Timeline operations: tracks, clips, import/export, generators, titles.

    Actions:
      list() -> {timelines}
      get_current() -> {name, id, start_frame, end_frame, start_timecode}
      set_current(index) -> {success}  — 1-based index
      get_name() -> {name}
      set_name(name) -> {success}
      get_start_frame() -> {frame}
      get_end_frame() -> {frame}
      get_start_timecode() -> {timecode}
      set_start_timecode(timecode) -> {success}
      get_track_count(track_type) -> {count}  — video, audio, subtitle
      add_track(track_type, options?) -> {success}
        — options dict (newTrackOptions per docs line 327): {audio_type, index}.
          audio_type: 'mono', 'stereo', '5.1', '7.1', 'adaptive1'..'adaptive36' for audio.
          index: 1-based slot; appended if omitted/out of bounds.
      delete_track(track_type, index) -> {success}
      get_track_sub_type(track_type, index) -> {sub_type}
      set_track_enable(track_type, index, enabled) -> {success}
      get_track_enabled(track_type, index) -> {enabled}
      set_track_lock(track_type, index, locked) -> {success}
      get_track_locked(track_type, index) -> {locked}
      get_track_name(track_type, index) -> {name}
      set_track_name(track_type, index, name) -> {success}
      get_items(track_type, index) -> {items}
      delete_clips(clip_ids, ripple?) -> {success}  — clip_ids: list of unique IDs
      set_clips_linked(clip_ids, linked) -> {success}
      duplicate(name?) -> {success, name}
      duplicate_clips(clip_ids?, selected?, target_track_index?, track_offset?, placement?, record_frame?, record_frame_offset?, copy_properties?, include_linked?) -> {results, count}
      — Video clips only. Re-places the same MediaPool media with the same source trim on the
        current timeline (like Alt-drag) via AppendToTimeline. clip_ids: timeline item unique IDs
        from get_items / get_current_video_item; selected=True uses Resolve's selected/current item
        when available. target_track_index overrides track_offset; placement supports same_time,
        offset, at_playhead, track_above, after_source, and next_gap. copy_properties may include
        transform, crop, composite, audio, retime, clip_color, markers, flags, enabled, cache,
        voice_isolation, fusion, grades, takes, and transitions (reported unsupported by Resolve API).
        include_linked=True duplicates linked audio and restores link state.
      copy_clips(...) -> {results, count} — alias for duplicate_clips.
      move_clips(...) -> {results, count, deleted_sources} — duplicate, then delete successfully duplicated sources.
      copy_range/duplicate_range(start_frame, end_frame, record_frame, ...) -> {results, count}
      overwrite_range(start_frame, end_frame, record_frame, ...) -> {results, count}
      lift_range(start_frame, end_frame, allow_partial_item_delete?, ripple?) -> {success, deleted}
      edit_kernel_capabilities() -> {supported, partially_supported, unsupported}
      probe_edit_kernel_item(clip_ids? selected? timeline_item?) -> {items, count}
      create_compound_clip(clip_ids, info?) -> {success}
      create_fusion_clip(clip_ids) -> {success}
      import_into_timeline(path, options?) -> {success}
      export(path, type, subtype?) -> {success}  — type: AAF, EDL, FCPXML, etc.
      get_setting(name?) -> {settings}
      set_setting(name, value) -> {success}
      insert_generator(name) -> {success}
      insert_fusion_generator(name) -> {success}
      insert_fusion_composition() -> {success}
      insert_ofx_generator(name) -> {success}
      insert_title(name) -> {success}
      insert_fusion_title(name) -> {success}
      get_unique_id() -> {id}
      get_node_graph() -> {available}
      get_media_pool_item() -> {name, id}
      get_mark_in_out() -> {mark}
      set_mark_in_out(mark_in, mark_out, type?) -> {success}
      clear_mark_in_out(type?) -> {success}
      convert_to_stereo() -> {success}
      get_items_in_track(track_type, track_index) -> {items}
      get_voice_isolation_state(track_index) -> {isEnabled, amount}
      set_voice_isolation_state(track_index, state) -> {success}
      extract_source_frame_ranges(handles?, gap_max?, skip_extensions?) -> {timeline_name, frame_ranges, occurrences, ...}
        — Same logic as Pr/extract_timeline_frames.py get_resolve_api_frames: all video clips on the
        current timeline; clip name = basename of Media Pool File Path when set; skips audio extensions.
        source_range_final and frame_ranges tuples are inclusive/inclusive endpoints per that script.
        Default handles=24, gap_max=30. Use handles=0 for gap-only auto handles.
    """
    p = params or {}
    pm, proj, err = _check()
    if err:
        return err

    # Actions that don't need a current timeline
    if action == "list":
        count = proj.GetTimelineCount()
        timelines = []
        for i in range(1, count + 1):
            tl = proj.GetTimelineByIndex(i)
            if tl:
                timelines.append({"name": tl.GetName(), "id": tl.GetUniqueId(), "index": i})
        return {"timelines": timelines}
    elif action == "set_current":
        tl = proj.GetTimelineByIndex(p["index"])
        return {"success": bool(proj.SetCurrentTimeline(tl))} if tl else _err(f"No timeline at index {p['index']}")
    elif action == "edit_kernel_capabilities":
        return _timeline_edit_kernel_capabilities()

    # Remaining actions need current timeline
    tl = proj.GetCurrentTimeline()
    if not tl:
        return _err("No current timeline")

    if action == "get_current":
        return {"name": tl.GetName(), "id": tl.GetUniqueId(), "start_frame": tl.GetStartFrame(), "end_frame": tl.GetEndFrame(), "start_timecode": tl.GetStartTimecode()}
    elif action == "get_name":
        return {"name": tl.GetName()}
    elif action == "set_name":
        return {"success": bool(tl.SetName(p["name"]))}
    elif action == "get_start_frame":
        return {"frame": tl.GetStartFrame()}
    elif action == "get_end_frame":
        return {"frame": tl.GetEndFrame()}
    elif action == "get_start_timecode":
        return {"timecode": tl.GetStartTimecode()}
    elif action == "set_start_timecode":
        return {"success": bool(tl.SetStartTimecode(p["timecode"]))}
    elif action == "get_track_count":
        return {"count": tl.GetTrackCount(p["track_type"])}
    elif action == "add_track":
        opts_in = p.get("options") or {}
        new_track_options: Dict[str, Any] = {}
        if "audio_type" in opts_in:
            new_track_options["audioType"] = opts_in["audio_type"]
        elif "audioType" in opts_in:
            new_track_options["audioType"] = opts_in["audioType"]
        if "index" in opts_in:
            new_track_options["index"] = opts_in["index"]
        if new_track_options:
            return {"success": bool(tl.AddTrack(p["track_type"], new_track_options))}
        return {"success": bool(tl.AddTrack(p["track_type"]))}
    elif action == "delete_track":
        return {"success": bool(tl.DeleteTrack(p["track_type"], p["index"]))}
    elif action == "get_track_sub_type":
        return {"sub_type": tl.GetTrackSubType(p["track_type"], p["index"])}
    elif action == "set_track_enable":
        return {"success": bool(tl.SetTrackEnable(p["track_type"], p["index"], p["enabled"]))}
    elif action == "get_track_enabled":
        return {"enabled": bool(tl.GetIsTrackEnabled(p["track_type"], p["index"]))}
    elif action == "set_track_lock":
        return {"success": bool(tl.SetTrackLock(p["track_type"], p["index"], p["locked"]))}
    elif action == "get_track_locked":
        return {"locked": bool(tl.GetIsTrackLocked(p["track_type"], p["index"]))}
    elif action == "get_track_name":
        return {"name": tl.GetTrackName(p["track_type"], p["index"])}
    elif action == "set_track_name":
        return {"success": bool(tl.SetTrackName(p["track_type"], p["index"], p["name"]))}
    elif action == "get_items":
        items = tl.GetItemListInTrack(p["track_type"], p["index"])
        return {"items": [{"name": it.GetName(), "id": it.GetUniqueId(), "start": it.GetStart(), "end": it.GetEnd(), "duration": it.GetDuration()} for it in (items or [])]}
    elif action == "delete_clips":
        # Find timeline items by unique IDs
        ids_set = set(p["clip_ids"])
        found = []
        for tt in ["video", "audio", "subtitle"]:
            for ti in range(1, tl.GetTrackCount(tt) + 1):
                for it in (tl.GetItemListInTrack(tt, ti) or []):
                    if it.GetUniqueId() in ids_set:
                        found.append(it)
        return {"success": bool(tl.DeleteClips(found, p.get("ripple", False)))}
    elif action == "set_clips_linked":
        ids_set = set(p["clip_ids"])
        found = []
        for tt in ["video", "audio"]:
            for ti in range(1, tl.GetTrackCount(tt) + 1):
                for it in (tl.GetItemListInTrack(tt, ti) or []):
                    if it.GetUniqueId() in ids_set:
                        found.append(it)
        return {"success": bool(tl.SetClipsLinked(found, p["linked"]))}
    elif action == "duplicate":
        dup = tl.DuplicateTimeline(p.get("name", tl.GetName() + " Copy"))
        return _ok(name=dup.GetName()) if dup else _err("Failed to duplicate")
    elif action == "duplicate_clips":
        return _timeline_duplicate_clips_impl(proj, tl, p)
    elif action == "copy_clips":
        return _timeline_duplicate_clips_impl(proj, tl, p)
    elif action == "move_clips":
        return _timeline_duplicate_clips_impl(proj, tl, p, delete_sources=True)
    elif action in {"copy_range", "duplicate_range"}:
        return _timeline_copy_range_impl(proj, tl, p)
    elif action == "overwrite_range":
        return _timeline_copy_range_impl(proj, tl, p, overwrite=True)
    elif action == "lift_range":
        return _timeline_lift_range_impl(tl, p)
    elif action == "edit_kernel_capabilities":
        return _timeline_edit_kernel_capabilities()
    elif action == "probe_edit_kernel_item":
        return _timeline_probe_edit_kernel_item(tl, p)
    elif action == "create_compound_clip":
        ids_set = set(p["clip_ids"])
        found = []
        for tt in ["video", "audio", "subtitle"]:
            for ti in range(1, (tl.GetTrackCount(tt) or 0) + 1):
                for it in (tl.GetItemListInTrack(tt, ti) or []):
                    if it.GetUniqueId() in ids_set:
                        found.append(it)
        if not found:
            return _err("None of the provided clip IDs were found in the timeline")
        result = tl.CreateCompoundClip(found, p.get("info", {}))
        return _ok() if result else _err("Failed to create compound clip")
    elif action == "create_fusion_clip":
        ids_set = set(p["clip_ids"])
        found = []
        for tt in ["video", "audio", "subtitle"]:
            for ti in range(1, (tl.GetTrackCount(tt) or 0) + 1):
                for it in (tl.GetItemListInTrack(tt, ti) or []):
                    if it.GetUniqueId() in ids_set:
                        found.append(it)
        if not found:
            return _err("None of the provided clip IDs were found in the timeline")
        result = tl.CreateFusionClip(found)
        return _ok() if result else _err("Failed to create Fusion clip")
    elif action == "import_into_timeline":
        return {"success": bool(tl.ImportIntoTimeline(p["path"], p.get("options", {})))}
    elif action == "export":
        return {"success": bool(tl.Export(p["path"], p["type"], p.get("subtype", "")))}
    elif action == "get_setting":
        return {"settings": _ser(tl.GetSetting(p.get("name", "")))}
    elif action == "set_setting":
        return {"success": bool(tl.SetSetting(p["name"], p["value"]))}
    elif action == "insert_generator":
        r = tl.InsertGeneratorIntoTimeline(p["name"])
        return _ok() if r else _err("Failed to insert generator")
    elif action == "insert_fusion_generator":
        r = tl.InsertFusionGeneratorIntoTimeline(p["name"])
        return _ok() if r else _err("Failed to insert Fusion generator")
    elif action == "insert_fusion_composition":
        r = tl.InsertFusionCompositionIntoTimeline()
        return _ok() if r else _err("Failed to insert Fusion composition")
    elif action == "insert_ofx_generator":
        r = tl.InsertOFXGeneratorIntoTimeline(p["name"])
        return _ok() if r else _err("Failed to insert OFX generator")
    elif action == "insert_title":
        r = tl.InsertTitleIntoTimeline(p["name"])
        return _ok() if r else _err("Failed to insert title")
    elif action == "insert_fusion_title":
        r = tl.InsertFusionTitleIntoTimeline(p["name"])
        return _ok() if r else _err("Failed to insert Fusion title")
    elif action == "get_unique_id":
        return {"id": tl.GetUniqueId()}
    elif action == "get_node_graph":
        g = tl.GetNodeGraph()
        return {"available": g is not None}
    elif action == "get_media_pool_item":
        mpi = tl.GetMediaPoolItem()
        return {"name": mpi.GetName(), "id": mpi.GetUniqueId()} if mpi else {"name": None, "id": None}
    elif action == "get_mark_in_out":
        return _ser(tl.GetMarkInOut())
    elif action == "set_mark_in_out":
        return {"success": bool(tl.SetMarkInOut(p["mark_in"], p["mark_out"], p.get("type", "all")))}
    elif action == "clear_mark_in_out":
        return {"success": bool(tl.ClearMarkInOut(p.get("type", "all")))}
    elif action == "convert_to_stereo":
        return {"success": bool(tl.ConvertTimelineToStereo())}
    elif action == "get_items_in_track":
        return {"items": _ser(tl.GetItemListInTrack(p["track_type"], p["track_index"]))}
    elif action == "get_voice_isolation_state":
        missing = _requires_method(tl, "GetVoiceIsolationState", "20.1")
        if missing:
            return missing
        state = tl.GetVoiceIsolationState(p["track_index"])
        return _ser(state) if state else {"isEnabled": False, "amount": 0}
    elif action == "set_voice_isolation_state":
        missing = _requires_method(tl, "SetVoiceIsolationState", "20.1")
        if missing:
            return missing
        return {"success": bool(tl.SetVoiceIsolationState(p["track_index"], p["state"]))}
    elif action == "extract_source_frame_ranges":
        p = params or {}
        handles = int(p.get("handles", 24))
        gap_max = int(p.get("gap_max", 30))
        audio_ext = tuple(
            x.lower() for x in p.get(
                "skip_extensions",
                (".wav", ".mp3", ".aiff", ".aac", ".m4a"),
            )
        )

        def _ifr(v):
            """Resolve sometimes returns None — skip clip if unset."""
            if v is None:
                return None
            try:
                return int(round(float(v)))
            except (TypeError, ValueError):
                return None

        clip_rows = []
        nvid = tl.GetTrackCount("video") or 0
        for track_index in range(1, nvid + 1):
            clips = tl.GetItemListInTrack("video", track_index) or []
            for clip in clips:
                name = clip.GetName() or ""
                try:
                    mpi = clip.GetMediaPoolItem()
                    if mpi:
                        fp = mpi.GetClipProperty("File Path")
                        if fp:
                            name = os.path.basename(str(fp).replace("\\", "/"))
                except Exception:
                    pass
                low = name.lower()
                if any(low.endswith(ext) for ext in audio_ext):
                    continue
                try:
                    t_start = _ifr(clip.GetStart())
                    t_end_excl = _ifr(clip.GetEnd())
                    lo = _ifr(clip.GetLeftOffset())
                    if lo is None and _has_method(clip, "GetSourceStartFrame"):
                        lo = _ifr(clip.GetSourceStartFrame())
                except Exception:
                    continue
                if t_start is None or t_end_excl is None or lo is None:
                    continue
                duration_tl = t_end_excl - t_start
                if duration_tl < 0:
                    continue
                source_boundary = lo + duration_tl
                timeline_end_inc = t_end_excl - 1
                clip_rows.append({
                    "clip": clip,
                    "name": name,
                    "track": track_index,
                    "timeline_start": t_start,
                    "timeline_end_inclusive": timeline_end_inc,
                    "source_boundary": source_boundary,
                    "offset": lo,
                })
        frame_ranges: Dict[str, List[List[int]]] = {}
        occurrences = []
        for row in clip_rows:
            clip = row["clip"]
            name = row["name"]
            track_index = row["track"]
            t_start = row["timeline_start"]
            t_end_inc = row["timeline_end_inclusive"]
            source_start = row["offset"]
            source_end = row["source_boundary"]
            clips_on_track = tl.GetItemListInTrack("video", track_index) or []
            max_handle = handles
            if handles == 0:
                max_handle = 0
                for other in clips_on_track:
                    oe = _ifr(other.GetEnd())
                    os_ = _ifr(other.GetStart())
                    if oe is None or os_ is None:
                        continue
                    other_end_inc = oe - 1
                    if other_end_inc < t_start:
                        gap = t_start - other_end_inc - 1
                        if 0 < gap <= gap_max:
                            max_handle = max(max_handle, gap)
                    if os_ > t_end_inc:
                        gap = os_ - t_end_inc - 1
                        if 0 < gap <= gap_max:
                            max_handle = max(max_handle, gap)
            final_s = max(0, int(source_start) - int(max_handle))
            final_e = int(source_end) - 1 + int(max_handle)
            frame_ranges.setdefault(name, []).append([final_s, final_e])
            uid = clip.GetUniqueId()
            occurrences.append({
                "clip_name": name,
                "timeline_item_id": "" if uid is None else str(uid),
                "track": track_index,
                "timeline_start": t_start,
                "timeline_end_inclusive": t_end_inc,
                "source_used_inclusive_end": source_end - 1,
                "handle_frames_applied": max_handle,
                "source_range_final": [final_s, final_e],
            })
        return _ok(
            timeline_name=tl.GetName() or "",
            handles_param=handles,
            gap_max=gap_max,
            clip_count=len(occurrences),
            frame_ranges=frame_ranges,
            occurrences=occurrences,
            notes=(
                "Same rules as Pr/extract_timeline_frames.py get_resolve_api_frames (video only, "
                "current timeline). frame_ranges lists can be merged/overlapped per clip name."
            ),
        )
    return _unknown(action, ["list","get_current","set_current","get_name","set_name","get_start_frame","get_end_frame","get_start_timecode","set_start_timecode","get_track_count","add_track","delete_track","get_track_sub_type","set_track_enable","get_track_enabled","set_track_lock","get_track_locked","get_track_name","set_track_name","get_items","delete_clips","set_clips_linked","duplicate","duplicate_clips","copy_clips","move_clips","copy_range","duplicate_range","overwrite_range","lift_range","edit_kernel_capabilities","probe_edit_kernel_item","create_compound_clip","create_fusion_clip","import_into_timeline","export","get_setting","set_setting","insert_generator","insert_fusion_generator","insert_fusion_composition","insert_ofx_generator","insert_title","insert_fusion_title","get_unique_id","get_node_graph","get_media_pool_item","get_mark_in_out","set_mark_in_out","clear_mark_in_out","convert_to_stereo","get_items_in_track","get_voice_isolation_state","set_voice_isolation_state","extract_source_frame_ranges"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 16: timeline_markers
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def timeline_markers(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Markers and playhead operations on the current timeline.

    Actions:
      add(frame|frame_id|frameId|timecode?, color?, name?, note?, duration?, custom_data?) -> {success, frame}
        If frame/timecode is omitted, add uses the current playhead timecode.
      get_all() -> {markers}
      get_by_custom_data(custom_data) -> {markers}
      update_custom_data(frame|frame_id|frameId|timecode, custom_data) -> {success}
      get_custom_data(frame|frame_id|frameId|timecode) -> {data}
      delete_by_color(color) -> {success}
      delete_at_frame(frame|frame_id|frameId|timecode) -> {success}
      delete_by_custom_data(custom_data) -> {success}
      get_current_timecode() -> {timecode}
      set_current_timecode(timecode) -> {success}
      get_current_video_item() -> {name, id}
      get_thumbnail() -> {thumbnail}
    """
    p = params or {}
    _, tl, err = _get_tl()
    if err:
        return err

    if action == "add":
        marker, marker_err = _marker_add_payload(p, tl=tl, default_to_current=True)
        if marker_err:
            return marker_err
        return _add_marker(tl, marker)
    elif action == "get_all":
        return {"markers": _ser(tl.GetMarkers())}
    elif action == "get_by_custom_data":
        return {"markers": _ser(tl.GetMarkerByCustomData(_first_param(p, "custom_data", "customData", default="")))}
    elif action == "update_custom_data":
        frame, frame_err = _marker_frame_from_params(p, tl=tl)
        if frame_err:
            return frame_err
        return {"success": bool(tl.UpdateMarkerCustomData(frame, _first_param(p, "custom_data", "customData", default="")))}
    elif action == "get_custom_data":
        frame, frame_err = _marker_frame_from_params(p, tl=tl)
        if frame_err:
            return frame_err
        return {"data": tl.GetMarkerCustomData(frame)}
    elif action == "delete_by_color":
        return {"success": bool(tl.DeleteMarkersByColor(p["color"]))}
    elif action == "delete_at_frame":
        frame, frame_err = _marker_frame_from_params(p, tl=tl)
        if frame_err:
            return frame_err
        return {"success": bool(tl.DeleteMarkerAtFrame(frame))}
    elif action == "delete_by_custom_data":
        return {"success": bool(tl.DeleteMarkerByCustomData(_first_param(p, "custom_data", "customData", default="")))}
    elif action == "get_current_timecode":
        return {"timecode": tl.GetCurrentTimecode()}
    elif action == "set_current_timecode":
        return {"success": bool(tl.SetCurrentTimecode(p["timecode"]))}
    elif action == "get_current_video_item":
        it = tl.GetCurrentVideoItem()
        return {"name": it.GetName(), "id": it.GetUniqueId()} if it else {"name": None, "id": None}
    elif action == "get_thumbnail":
        return _ser(tl.GetCurrentClipThumbnailImage())
    return _unknown(action, ["add","get_all","get_by_custom_data","update_custom_data","get_custom_data","delete_by_color","delete_at_frame","delete_by_custom_data","get_current_timecode","set_current_timecode","get_current_video_item","get_thumbnail"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 17: timeline_ai
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def timeline_ai(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """AI and analysis operations on the current timeline.

    Actions:
      create_subtitles(settings?) -> {success}  — auto-caption from audio
      detect_scene_cuts() -> {success}
      analyze_dolby_vision(clip_ids?, analysis_type?) -> {success}
      grab_still() -> {success}
      grab_all_stills(source?) -> {count}
    """
    p = params or {}
    _, tl, err = _get_tl()
    if err:
        return err

    if action == "create_subtitles":
        return {"success": bool(tl.CreateSubtitlesFromAudio(p.get("settings", {})))}
    elif action == "detect_scene_cuts":
        return {"success": bool(tl.DetectSceneCuts())}
    elif action == "analyze_dolby_vision":
        clip_ids = p.get("clip_ids", [])
        items = []
        if clip_ids:
            for tt in ["video"]:
                for ti in range(1, tl.GetTrackCount(tt) + 1):
                    for it in (tl.GetItemListInTrack(tt, ti) or []):
                        if it.GetUniqueId() in clip_ids:
                            items.append(it)
        analysis_type = p.get("analysis_type")
        return {"success": bool(tl.AnalyzeDolbyVision(items, analysis_type))}
    elif action == "grab_still":
        still = tl.GrabStill()
        return _ok() if still else _err("Failed to grab still")
    elif action == "grab_all_stills":
        stills = tl.GrabAllStills(p.get("source", 1))
        return {"count": len(stills) if stills else 0}
    return _unknown(action, ["create_subtitles","detect_scene_cuts","analyze_dolby_vision","grab_still","grab_all_stills"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 18: timeline_item
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def timeline_item(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Properties, transforms, speed, keyframes, and metadata for a timeline item.
    Identify by track_type, track_index, item_index.

    Actions:
      get_name(track_type?, track_index?, item_index?) -> {name}
      get_property(key?, ...) -> {properties}
      set_property(key, value, ...) -> {success}
      get_duration(...) -> {duration}
      get_start(...) -> {start}
      get_end(...) -> {end}
      get_source_start_frame(...) -> {frame}
      get_source_end_frame(...) -> {frame}
      get_source_start_time(...) -> {time}
      get_source_end_time(...) -> {time}
      get_left_offset(...) -> {offset}
      get_right_offset(...) -> {offset}
      set_clip_enabled(enabled, ...) -> {success}
      get_clip_enabled(...) -> {enabled}
      update_sidecar(...) -> {success}
      get_unique_id(...) -> {id}
      get_media_pool_item(...) -> {name, id}
      get_stereo_convergence(...) -> {values}
      get_stereo_left_window(...) -> {params}
      get_stereo_right_window(...) -> {params}
      get_linked_items(...) -> {items}
      get_track_type_and_index(...) -> {track_type, track_index}
      get_source_audio_mapping(...) -> {mapping}
      load_burnin_preset(name, ...) -> {success}
      set_name(name, ...) -> {success}
      get_voice_isolation_state(...) -> {state}
      set_voice_isolation_state(state, ...) -> {success}
      get_retime(...) -> {process, motion_estimation}
      set_retime(process?, motion_estimation?, ...) -> {success}  — process: nearest, frame_blend, optical_flow (or 0-3); motion_estimation: 0-6
      get_transform(...) -> {Pan, Tilt, ZoomX, ZoomY, RotationAngle, ...}
      set_transform(Pan?, Tilt?, ZoomX?, ZoomY?, RotationAngle?, AnchorPointX?, AnchorPointY?, Pitch?, Yaw?, FlipX?, FlipY?, ...) -> {success}
      get_crop(...) -> {CropLeft, CropRight, CropTop, CropBottom, CropSoftness, CropRetain}
      set_crop(CropLeft?, CropRight?, CropTop?, CropBottom?, CropSoftness?, CropRetain?, ...) -> {success}
      get_composite(...) -> {Opacity, CompositeMode}
      set_composite(Opacity?, CompositeMode?, ...) -> {success}
      get_audio(...) -> {Volume, Pan, AudioSyncOffset, ...}
      set_audio(Volume?, Pan?, ...) -> {success}
      get_keyframes(property, ...) -> {property, count, keyframes}
      add_keyframe(property, frame, value, ...) -> {success}
      modify_keyframe(property, frame, new_value?, new_frame?, ...) -> {success}
      delete_keyframe(property, frame, ...) -> {success}
      set_keyframe_interpolation(property, frame, interpolation, ...) -> {success}  — Linear, Bezier, EaseIn, EaseOut, EaseInOut

    Default: track_type="video", track_index=1, item_index=0
    """
    p = params or {}
    tl, item, err = _get_item(p)
    if err:
        return err

    if action == "get_name":
        return {"name": item.GetName()}
    elif action == "get_property":
        return {"properties": _ser(item.GetProperty(p.get("key", "")))}
    elif action == "set_property":
        return {"success": bool(item.SetProperty(p["key"], p["value"]))}
    elif action == "get_duration":
        return {"duration": item.GetDuration()}
    elif action == "get_start":
        return {"start": item.GetStart()}
    elif action == "get_end":
        return {"end": item.GetEnd()}
    elif action == "get_source_start_frame":
        return {"frame": item.GetSourceStartFrame()}
    elif action == "get_source_end_frame":
        return {"frame": item.GetSourceEndFrame()}
    elif action == "get_source_start_time":
        return {"time": item.GetSourceStartTime()}
    elif action == "get_source_end_time":
        return {"time": item.GetSourceEndTime()}
    elif action == "get_left_offset":
        return {"offset": item.GetLeftOffset()}
    elif action == "get_right_offset":
        return {"offset": item.GetRightOffset()}
    elif action == "set_clip_enabled":
        return {"success": bool(item.SetClipEnabled(p["enabled"]))}
    elif action == "get_clip_enabled":
        return {"enabled": bool(item.GetClipEnabled())}
    elif action == "update_sidecar":
        return {"success": bool(item.UpdateSidecar())}
    elif action == "get_unique_id":
        return {"id": item.GetUniqueId()}
    elif action == "get_media_pool_item":
        mpi = item.GetMediaPoolItem()
        return {"name": mpi.GetName(), "id": mpi.GetUniqueId()} if mpi else {"name": None, "id": None}
    elif action == "get_stereo_convergence":
        return {"values": _ser(item.GetStereoConvergenceValues())}
    elif action == "get_stereo_left_window":
        return {"params": _ser(item.GetStereoLeftFloatingWindowParams())}
    elif action == "get_stereo_right_window":
        return {"params": _ser(item.GetStereoRightFloatingWindowParams())}
    elif action == "get_linked_items":
        linked = item.GetLinkedItems() or []
        return {"items": [{"name": it.GetName(), "id": it.GetUniqueId()} for it in linked]}
    elif action == "get_track_type_and_index":
        result = item.GetTrackTypeAndIndex()
        return {"track_type": result[0], "track_index": result[1]} if result else _err("Failed")
    elif action == "get_source_audio_mapping":
        return {"mapping": item.GetSourceAudioChannelMapping()}
    elif action == "load_burnin_preset":
        return {"success": bool(item.LoadBurnInPreset(p["name"]))}
    elif action == "set_name":
        missing = _requires_method(item, "SetName", "20.2")
        if missing:
            return missing
        return {"success": bool(item.SetName(p["name"]))}
    elif action == "get_voice_isolation_state":
        missing = _requires_method(item, "GetVoiceIsolationState", "20.1")
        if missing:
            return missing
        state = item.GetVoiceIsolationState()
        return {"state": _ser(state) if state else {"isEnabled": False, "amount": 0}}
    elif action == "set_voice_isolation_state":
        missing = _requires_method(item, "SetVoiceIsolationState", "20.1")
        if missing:
            return missing
        return {"success": bool(item.SetVoiceIsolationState(p["state"]))}

    # ── Retime ──
    elif action == "get_retime":
        return {"process": item.GetProperty("RetimeProcess"), "motion_estimation": item.GetProperty("MotionEstimation")}
    elif action == "set_retime":
        # RetimeProcess: 0=project, 1=nearest, 2=frame_blend, 3=optical_flow
        # MotionEstimation: 0=project, 1=standard_faster, 2=standard_better, 3=enhanced_faster, 4=enhanced_better, 5=speed_warp_better, 6=speed_warp_faster
        process_map = {"project": 0, "nearest": 1, "frame_blend": 2, "optical_flow": 3}
        results = {}
        if "process" in p:
            val = p["process"]
            if isinstance(val, str):
                val = process_map.get(val.lower())
                if val is None:
                    return _err(f"Invalid process. Use: {', '.join(process_map.keys())} or integer 0-3")
            results["process"] = bool(item.SetProperty("RetimeProcess", val))
        if "motion_estimation" in p:
            results["motion_estimation"] = bool(item.SetProperty("MotionEstimation", p["motion_estimation"]))
        return _ok(**results) if results else _err("Specify process (0-3 or name) and/or motion_estimation (0-6)")

    # ── Transform ──
    elif action == "get_transform":
        keys = ["Pan", "Tilt", "ZoomX", "ZoomY", "ZoomGang", "RotationAngle", "AnchorPointX", "AnchorPointY", "Pitch", "Yaw", "FlipX", "FlipY"]
        return {k: item.GetProperty(k) for k in keys}
    elif action == "set_transform":
        valid = {"Pan", "Tilt", "ZoomX", "ZoomY", "ZoomGang", "RotationAngle", "AnchorPointX", "AnchorPointY", "Pitch", "Yaw", "FlipX", "FlipY"}
        results = {}
        for k, v in p.items():
            if k in valid:
                results[k] = bool(item.SetProperty(k, v))
        return _ok(**results) if results else _err(f"Specify one or more of: {', '.join(sorted(valid))}")

    # ── Crop ──
    elif action == "get_crop":
        keys = ["CropLeft", "CropRight", "CropTop", "CropBottom", "CropSoftness", "CropRetain"]
        return {k: item.GetProperty(k) for k in keys}
    elif action == "set_crop":
        valid = {"CropLeft", "CropRight", "CropTop", "CropBottom", "CropSoftness", "CropRetain"}
        results = {}
        for k, v in p.items():
            if k in valid:
                results[k] = bool(item.SetProperty(k, v))
        return _ok(**results) if results else _err(f"Specify one or more of: {', '.join(sorted(valid))}")

    # ── Composite ──
    elif action == "get_composite":
        return {"Opacity": item.GetProperty("Opacity"), "CompositeMode": item.GetProperty("CompositeMode")}
    elif action == "set_composite":
        results = {}
        if "Opacity" in p:
            results["Opacity"] = bool(item.SetProperty("Opacity", p["Opacity"]))
        if "CompositeMode" in p:
            results["CompositeMode"] = bool(item.SetProperty("CompositeMode", p["CompositeMode"]))
        return _ok(**results) if results else _err("Specify Opacity and/or CompositeMode")

    # ── Audio ──
    elif action == "get_audio":
        keys = ["Volume", "Pan", "AudioSyncOffsetIsManual", "AudioSyncOffset"]
        return {k: item.GetProperty(k) for k in keys}
    elif action == "set_audio":
        valid = {"Volume", "Pan", "AudioSyncOffsetIsManual", "AudioSyncOffset"}
        results = {}
        for k, v in p.items():
            if k in valid:
                results[k] = bool(item.SetProperty(k, v))
        return _ok(**results) if results else _err(f"Specify one or more of: {', '.join(sorted(valid))}")

    # ── Keyframes ──
    elif action == "get_keyframes":
        prop = p["property"]
        count = item.GetKeyframeCount(prop)
        if count == 0:
            return {"property": prop, "count": 0, "keyframes": []}
        kfs = []
        for i in range(count):
            kf = item.GetKeyframeAtIndex(prop, i)
            val = item.GetPropertyAtKeyframeIndex(prop, i)
            kfs.append({"frame": kf.get("frame") if isinstance(kf, dict) else kf, "value": val})
        return {"property": prop, "count": count, "keyframes": kfs}
    elif action == "add_keyframe":
        return {"success": bool(item.AddKeyframe(p["property"], p["frame"], p["value"]))}
    elif action == "modify_keyframe":
        kw = {}
        if "new_value" in p:
            kw["value"] = p["new_value"]
        if "new_frame" in p:
            kw["frame"] = p["new_frame"]
        return {"success": bool(item.ModifyKeyframe(p["property"], p["frame"], **kw))}
    elif action == "delete_keyframe":
        return {"success": bool(item.DeleteKeyframe(p["property"], p["frame"]))}
    elif action == "set_keyframe_interpolation":
        valid = ["Linear", "Bezier", "EaseIn", "EaseOut", "EaseInOut"]
        if p.get("interpolation") not in valid:
            return _err(f"Invalid interpolation. Must be one of: {', '.join(valid)}")
        return {"success": bool(item.SetKeyframeInterpolation(p["property"], p["frame"], p["interpolation"]))}

    return _unknown(action, ["get_name","get_property","set_property","get_duration","get_start","get_end","get_source_start_frame","get_source_end_frame","get_source_start_time","get_source_end_time","get_left_offset","get_right_offset","set_clip_enabled","get_clip_enabled","update_sidecar","get_unique_id","get_media_pool_item","get_stereo_convergence","get_stereo_left_window","get_stereo_right_window","get_linked_items","get_track_type_and_index","get_source_audio_mapping","load_burnin_preset","set_name","get_voice_isolation_state","set_voice_isolation_state","get_retime","set_retime","get_transform","set_transform","get_crop","set_crop","get_composite","set_composite","get_audio","set_audio","get_keyframes","add_keyframe","modify_keyframe","delete_keyframe","set_keyframe_interpolation"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 19: timeline_item_markers
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def timeline_item_markers(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Markers, flags, and clip color on timeline items. Identify by track_type, track_index, item_index.

    Actions:
      add(frame|frame_id|frameId, color?, name?, note?, duration?, custom_data?, ...) -> {success, frame}
      get_all(...) -> {markers}
      get_by_custom_data(custom_data, ...) -> {markers}
      update_custom_data(frame|frame_id|frameId, custom_data, ...) -> {success}
      get_custom_data(frame|frame_id|frameId, ...) -> {data}
      delete_by_color(color, ...) -> {success}
      delete_at_frame(frame|frame_id|frameId, ...) -> {success}
      delete_by_custom_data(custom_data, ...) -> {success}
      add_flag(color, ...) -> {success}
      get_flags(...) -> {flags}
      clear_flags(color, ...) -> {success}
      get_clip_color(...) -> {color}
      set_clip_color(color, ...) -> {success}
      clear_clip_color(...) -> {success}

    Default: track_type="video", track_index=1, item_index=0
    """
    p = params or {}
    _, item, err = _get_item(p)
    if err:
        return err

    if action == "add":
        marker, marker_err = _marker_add_payload(p)
        if marker_err:
            return marker_err
        return _add_marker(item, marker)
    elif action == "get_all":
        return {"markers": _ser(item.GetMarkers())}
    elif action == "get_by_custom_data":
        return {"markers": _ser(item.GetMarkerByCustomData(_first_param(p, "custom_data", "customData", default="")))}
    elif action == "update_custom_data":
        frame, frame_err = _marker_frame_from_params(p)
        if frame_err:
            return frame_err
        return {"success": bool(item.UpdateMarkerCustomData(frame, _first_param(p, "custom_data", "customData", default="")))}
    elif action == "get_custom_data":
        frame, frame_err = _marker_frame_from_params(p)
        if frame_err:
            return frame_err
        return {"data": item.GetMarkerCustomData(frame)}
    elif action == "delete_by_color":
        return {"success": bool(item.DeleteMarkersByColor(p["color"]))}
    elif action == "delete_at_frame":
        frame, frame_err = _marker_frame_from_params(p)
        if frame_err:
            return frame_err
        return {"success": bool(item.DeleteMarkerAtFrame(frame))}
    elif action == "delete_by_custom_data":
        return {"success": bool(item.DeleteMarkerByCustomData(_first_param(p, "custom_data", "customData", default="")))}
    elif action == "add_flag":
        return {"success": bool(item.AddFlag(p["color"]))}
    elif action == "get_flags":
        return {"flags": item.GetFlagList()}
    elif action == "clear_flags":
        return {"success": bool(item.ClearFlags(p["color"]))}
    elif action == "get_clip_color":
        return {"color": item.GetClipColor()}
    elif action == "set_clip_color":
        return {"success": bool(item.SetClipColor(p["color"]))}
    elif action == "clear_clip_color":
        return {"success": bool(item.ClearClipColor())}
    return _unknown(action, ["add","get_all","get_by_custom_data","update_custom_data","get_custom_data","delete_by_color","delete_at_frame","delete_by_custom_data","add_flag","get_flags","clear_flags","get_clip_color","set_clip_color","clear_clip_color"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 20: timeline_item_fusion
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def timeline_item_fusion(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fusion composition operations on timeline items. Identify by track_type, track_index, item_index.

    Actions:
      add_comp(...) -> {success}
      get_comp_count(...) -> {count}
      get_comp_names(...) -> {names}
      get_comp_by_name(name, ...) -> {available}
      get_comp_by_index(index, ...) -> {available}
      export_comp(path, index, ...) -> {success}
      import_comp(path, ...) -> {success}
      delete_comp(name, ...) -> {success}
      load_comp(name, ...) -> {success}
      rename_comp(old_name, new_name, ...) -> {success}
      get_cache_enabled(...) -> {enabled}  — Fusion output cache status
      set_cache(value, ...) -> {success}  — value: "Auto", "On", or "Off"

    Default: track_type="video", track_index=1, item_index=0
    """
    p = params or {}
    _, item, err = _get_item(p)
    if err:
        return err

    if action == "add_comp":
        comp = item.AddFusionComp()
        return _ok() if comp else _err("Failed to add Fusion comp")
    elif action == "get_comp_count":
        return {"count": item.GetFusionCompCount()}
    elif action == "get_comp_names":
        return {"names": _ser(item.GetFusionCompNameList())}
    elif action == "get_comp_by_name":
        comp = item.GetFusionCompByName(p["name"])
        return {"available": comp is not None}
    elif action == "get_comp_by_index":
        comp = item.GetFusionCompByIndex(p["index"])
        return {"available": comp is not None}
    elif action == "export_comp":
        return {"success": bool(item.ExportFusionComp(p["path"], p["index"]))}
    elif action == "import_comp":
        comp = item.ImportFusionComp(p["path"])
        return _ok() if comp else _err("Failed to import comp")
    elif action == "delete_comp":
        return {"success": bool(item.DeleteFusionCompByName(p["name"]))}
    elif action == "load_comp":
        comp = item.LoadFusionCompByName(p["name"])
        return _ok() if comp else _err("Failed to load comp")
    elif action == "rename_comp":
        return {"success": bool(item.RenameFusionCompByName(p["old_name"], p["new_name"]))}
    elif action == "get_cache_enabled":
        return {"enabled": item.GetIsFusionOutputCacheEnabled()}
    elif action == "set_cache":
        return {"success": bool(item.SetFusionOutputCache(p["value"]))}
    return _unknown(action, ["add_comp","get_comp_count","get_comp_names","get_comp_by_name","get_comp_by_index","export_comp","import_comp","delete_comp","load_comp","rename_comp","get_cache_enabled","set_cache"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 21: timeline_item_color
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def timeline_item_color(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Color grading, versions, LUTs, cache, and AI tools on timeline items. Identify by track_type, track_index, item_index.

    Actions:
      set_cdl(cdl, ...) -> {success}  — cdl: {NodeIndex, Slope, Offset, Power, Saturation}
      copy_grades(target_ids, ...) -> {success}
      add_version(name, type?, ...) -> {success}  — type: 0=local, 1=remote
      get_current_version(...) -> {version}
      get_version_names(type?, ...) -> {names}
      load_version(name, type?, ...) -> {success}
      rename_version(old_name, new_name, type?, ...) -> {success}
      delete_version(name, type?, ...) -> {success}
      get_node_graph(layer_index?, ...) -> {available}
      get_color_group(...) -> {name}
      assign_color_group(group_name, ...) -> {success}
      remove_from_color_group(...) -> {success}
      export_lut(type, path, ...) -> {success}
      get_color_cache(...) -> {enabled}
      set_color_cache(enabled, ...) -> {success}
      get_fusion_cache(...) -> {enabled}
      set_fusion_cache(enabled, ...) -> {success}
      reset_all_node_colors(...) -> {success}
      stabilize(...) -> {success}
      smart_reframe(...) -> {success}
      create_magic_mask(mode, ...) -> {success}  — mode: "F" forward, "B" backward, "BI" bidirectional
      regenerate_magic_mask(...) -> {success}

    Default: track_type="video", track_index=1, item_index=0
    """
    p = params or {}
    _, item, err = _get_item(p)
    if err:
        return err

    _, proj, _ = _check()

    if action == "set_cdl":
        return {"success": bool(item.SetCDL(_normalize_cdl(p["cdl"])))}
    elif action == "copy_grades":
        # Find target items by IDs
        _, tl, _ = _get_tl()
        targets = []
        target_ids = set(p["target_ids"])
        if tl:
            for tt in ["video"]:
                for ti in range(1, tl.GetTrackCount(tt) + 1):
                    for it in (tl.GetItemListInTrack(tt, ti) or []):
                        if it.GetUniqueId() in target_ids:
                            targets.append(it)
        return {"success": bool(item.CopyGrades(targets))}
    elif action == "add_version":
        return {"success": bool(item.AddVersion(p["name"], p.get("type", 0)))}
    elif action == "get_current_version":
        return {"version": _ser(item.GetCurrentVersion())}
    elif action == "get_version_names":
        return {"names": _ser(item.GetVersionNameList(p.get("type", 0)))}
    elif action == "load_version":
        return {"success": bool(item.LoadVersionByName(p["name"], p.get("type", 0)))}
    elif action == "rename_version":
        return {"success": bool(item.RenameVersionByName(p["old_name"], p["new_name"], p.get("type", 0)))}
    elif action == "delete_version":
        return {"success": bool(item.DeleteVersionByName(p["name"], p.get("type", 0)))}
    elif action == "get_node_graph":
        g = item.GetNodeGraph(p["layer_index"]) if "layer_index" in p else item.GetNodeGraph()
        return {"available": g is not None}
    elif action == "get_color_group":
        g = item.GetColorGroup()
        return {"name": g.GetName() if g else None}
    elif action == "assign_color_group":
        groups = proj.GetColorGroupsList() or []
        for g in groups:
            if g.GetName() == p["group_name"]:
                return {"success": bool(item.AssignToColorGroup(g))}
        return _err(f"Color group '{p['group_name']}' not found")
    elif action == "remove_from_color_group":
        return {"success": bool(item.RemoveFromColorGroup())}
    elif action == "export_lut":
        return {"success": bool(item.ExportLUT(p["type"], p["path"]))}
    elif action == "get_color_cache":
        return {"enabled": item.GetIsColorOutputCacheEnabled()}
    elif action == "set_color_cache":
        return {"success": bool(item.SetColorOutputCache(p["enabled"]))}
    elif action == "get_fusion_cache":
        return {"enabled": item.GetIsFusionOutputCacheEnabled()}
    elif action == "set_fusion_cache":
        return {"success": bool(item.SetFusionOutputCache(p["enabled"]))}
    elif action == "reset_all_node_colors":
        missing = _requires_method(item, "ResetAllNodeColors", "20.2")
        if missing:
            return missing
        return {"success": bool(item.ResetAllNodeColors())}
    elif action == "stabilize":
        return {"success": bool(item.Stabilize())}
    elif action == "smart_reframe":
        return {"success": bool(item.SmartReframe())}
    elif action == "create_magic_mask":
        return {"success": bool(item.CreateMagicMask(p.get("mode", "F")))}
    elif action == "regenerate_magic_mask":
        return {"success": bool(item.RegenerateMagicMask())}
    return _unknown(action, ["set_cdl","copy_grades","add_version","get_current_version","get_version_names","load_version","rename_version","delete_version","get_node_graph","get_color_group","assign_color_group","remove_from_color_group","export_lut","get_color_cache","set_color_cache","get_fusion_cache","set_fusion_cache","reset_all_node_colors","stabilize","smart_reframe","create_magic_mask","regenerate_magic_mask"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 22: timeline_item_takes
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def timeline_item_takes(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Take management on timeline items. Identify by track_type, track_index, item_index.

    Actions:
      add(clip_id, start_frame?, end_frame?, ...) -> {success}
      get_count(...) -> {count}
      get_selected_index(...) -> {index}
      get_by_index(index, ...) -> {take}
      select(index, ...) -> {success}
      delete(index, ...) -> {success}
      finalize(...) -> {success}

    Default: track_type="video", track_index=1, item_index=0
    """
    p = params or {}
    _, item, err = _get_item(p)
    if err:
        return err

    if action == "add":
        _, _, mp, mp_err = _get_mp()
        if mp_err:
            return mp_err
        clip = _find_clip(mp.GetRootFolder(), p["clip_id"])
        if not clip:
            return _err(f"Clip not found: {p['clip_id']}")
        return {"success": bool(item.AddTake(clip, p.get("start_frame", 0), p.get("end_frame", 0)))}
    elif action == "get_count":
        return {"count": item.GetTakesCount()}
    elif action == "get_selected_index":
        return {"index": item.GetSelectedTakeIndex()}
    elif action == "get_by_index":
        return _ser(item.GetTakeByIndex(p["index"]))
    elif action == "select":
        return {"success": bool(item.SelectTakeByIndex(p["index"]))}
    elif action == "delete":
        return {"success": bool(item.DeleteTakeByIndex(p["index"]))}
    elif action == "finalize":
        return {"success": bool(item.FinalizeTake())}
    return _unknown(action, ["add","get_count","get_selected_index","get_by_index","select","delete","finalize"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 23: gallery
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def gallery(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Gallery album management.

    Actions:
      get_album_name(album_index?) -> {name}
      set_album_name(name, album_index?) -> {success}
      get_current_album() -> {available}
      set_current_album(album_index) -> {success}
      get_still_albums() -> {albums}
      get_power_grade_albums() -> {albums}
      create_still_album() -> {success}
      create_power_grade_album() -> {success}

    album_index is 0-based into the still albums list.
    """
    p = params or {}
    _, proj, err = _check()
    if err:
        return err

    gal = proj.GetGallery()
    if not gal:
        return _err("Gallery not available")

    if action == "get_album_name":
        albums = gal.GetGalleryStillAlbums() or []
        idx = p.get("album_index", 0)
        if idx < len(albums):
            return {"name": gal.GetAlbumName(albums[idx])}
        return _err("Album index out of range")
    elif action == "set_album_name":
        albums = gal.GetGalleryStillAlbums() or []
        idx = p.get("album_index", 0)
        if idx < len(albums):
            return {"success": bool(gal.SetAlbumName(albums[idx], p["name"]))}
        return _err("Album index out of range")
    elif action == "get_current_album":
        album = gal.GetCurrentStillAlbum()
        return {"available": album is not None}
    elif action == "set_current_album":
        albums = gal.GetGalleryStillAlbums() or []
        idx = p.get("album_index", 0)
        if idx < len(albums):
            return {"success": bool(gal.SetCurrentStillAlbum(albums[idx]))}
        return _err("Album index out of range")
    elif action == "get_still_albums":
        albums = gal.GetGalleryStillAlbums() or []
        return {"albums": [{"name": gal.GetAlbumName(a), "index": i} for i, a in enumerate(albums)]}
    elif action == "get_power_grade_albums":
        albums = gal.GetGalleryPowerGradeAlbums() or []
        return {"albums": [{"name": gal.GetAlbumName(a), "index": i} for i, a in enumerate(albums)]}
    elif action == "create_still_album":
        album = gal.CreateGalleryStillAlbum()
        return _ok() if album else _err("Failed to create still album")
    elif action == "create_power_grade_album":
        album = gal.CreateGalleryPowerGradeAlbum()
        return _ok() if album else _err("Failed to create power grade album")
    return _unknown(action, ["get_album_name","set_album_name","get_current_album","set_current_album","get_still_albums","get_power_grade_albums","create_still_album","create_power_grade_album"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 24: gallery_stills
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def gallery_stills(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Manage stills in gallery albums (best results on Color page).

    Actions:
      get_stills(album_index?) -> {count}
      get_label(still_index, album_index?) -> {label}
      set_label(still_index, label, album_index?) -> {success}
      import_stills(paths, album_index?) -> {success}
      export_stills(folder_path, prefix?, format?, album_index?) -> {success}
      grab_and_export(folder_path, prefix?, format?, album_index?, delete_after?, cleanup?) -> {files}
      delete_stills(still_indices, album_index?) -> {success}

    album_index defaults to current album. still_index is 0-based.
    format for export: dpx, cin, tif, jpg, png, ppm, bmp, xpm, drx (default: dpx).
    grab_and_export grabs a still from the current frame and exports it immediately,
    keeping the live GalleryStill reference (more reliable than separate grab + export).
    Requires Color page. Automatically produces a companion .drx grade file.
    File data is inlined in the response (DRX as text, images as base64).
    cleanup (default true) deletes exported files from disk after inlining.
    """
    p = params or {}
    _, proj, err = _check()
    if err:
        return err

    gal = proj.GetGallery()
    if not gal:
        return _err("Gallery not available")

    album_idx = p.get("album_index")
    if album_idx is not None:
        albums = gal.GetGalleryStillAlbums() or []
        if album_idx < len(albums):
            album = albums[album_idx]
        else:
            return _err("Album index out of range")
    else:
        album = gal.GetCurrentStillAlbum()
        if not album:
            albums = gal.GetGalleryStillAlbums() or []
            album = albums[0] if albums else None
    if not album:
        return _err("No still album available")

    if action == "get_stills":
        stills = album.GetStills() or []
        return {"count": len(stills)}
    elif action == "get_label":
        stills = album.GetStills() or []
        idx = p.get("still_index", 0)
        if idx < len(stills):
            return {"label": album.GetLabel(stills[idx])}
        return _err("Still index out of range")
    elif action == "set_label":
        stills = album.GetStills() or []
        idx = p.get("still_index", 0)
        if idx < len(stills):
            return {"success": bool(album.SetLabel(stills[idx], p["label"]))}
        return _err("Still index out of range")
    elif action == "import_stills":
        return {"success": bool(album.ImportStills(p["paths"]))}
    elif action == "export_stills":
        stills = album.GetStills() or []
        if not stills:
            return _err("No stills to export")
        return {"success": bool(album.ExportStills(stills, p["folder_path"], p.get("prefix", "still"), p.get("format", "dpx")))}
    elif action == "grab_and_export":
        import time, os
        folder_path = p.get("folder_path")
        if not folder_path:
            return _err("folder_path is required")
        prefix = p.get("prefix", "still")
        fmt = p.get("format", "dpx")
        delete_after = p.get("delete_after", True)
        # Redirect sandbox/temp paths that Resolve can't access
        folder_path = _resolve_safe_dir(folder_path)
        os.makedirs(folder_path, exist_ok=True)
        # Snapshot directory before export
        before = set(os.listdir(folder_path))
        # Grab still — requires Color page with a clip under the playhead
        _, tl, err2 = _get_tl()
        if err2:
            return err2
        still = tl.GrabStill()
        if not still:
            return _err("GrabStill failed — ensure Color page is active with a clip under the playhead")
        time.sleep(0.5)
        # Export using the live still reference with format fallback chain
        export_ok = False
        used_format = fmt
        for try_fmt in [fmt, "tif", "dpx"]:
            result = album.ExportStills([still], folder_path, prefix, try_fmt)
            if result:
                export_ok = True
                used_format = try_fmt
                break
            time.sleep(0.3)
        # Clean up still from gallery
        if delete_after:
            album.DeleteStills([still])
        if not export_ok:
            return _err("ExportStills failed — ensure the Gallery panel is open on the Color page (Workspace > Gallery)")
        # Wait for filesystem
        time.sleep(0.3)
        # Find new files
        after = set(os.listdir(folder_path))
        new_files = sorted(after - before)
        file_details = []
        for f in new_files:
            fpath = os.path.join(folder_path, f)
            entry = {"name": f, "path": fpath, "size": os.path.getsize(fpath)}
            # Inline file data so cleanup can safely remove files
            try:
                with open(fpath, "rb") as fh:
                    raw = fh.read()
                if f.endswith(".drx"):
                    # DRX files are small XML — inline as text
                    try:
                        entry["data"] = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        entry["data_base64"] = base64.b64encode(raw).decode("ascii")
                else:
                    entry["data_base64"] = base64.b64encode(raw).decode("ascii")
            except OSError:
                pass
            file_details.append(entry)
        # Cleanup: remove exported files now that data is inlined (default: True)
        cleanup = p.get("cleanup", True)
        if cleanup:
            for f in file_details:
                try:
                    os.remove(f["path"])
                except OSError:
                    pass
            # Remove the directory if empty
            try:
                if os.path.isdir(folder_path) and not os.listdir(folder_path):
                    os.rmdir(folder_path)
            except OSError:
                pass
        return {"files": file_details, "format": used_format, "folder": folder_path, "cleaned_up": cleanup}
    elif action == "delete_stills":
        stills = album.GetStills() or []
        to_delete = [stills[i] for i in p["still_indices"] if i < len(stills)]
        return {"success": bool(album.DeleteStills(to_delete))} if to_delete else _err("No valid still indices")
    return _unknown(action, ["get_stills","get_label","set_label","import_stills","export_stills","grab_and_export","delete_stills"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 25: graph
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def graph(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Node graph operations (color grading nodes). Source can be timeline, timeline item, or color group.

    Actions:
      get_num_nodes(source?, ...) -> {count}
      get_lut(node_index, source?, ...) -> {lut}
      set_lut(node_index, lut_path, source?, ...) -> {success}
      get_node_cache(node_index, source?, ...) -> {cache}
      set_node_cache(node_index, cache_value, source?, ...) -> {success}
      get_node_label(node_index, source?, ...) -> {label}
      get_tools_in_node(node_index, source?, ...) -> {tools}
      set_node_enabled(node_index, enabled, source?, ...) -> {success}
      apply_grade_from_drx(path, grade_mode?, source?, ...) -> {success}
        grade_mode: 0="No keyframes" (default), 1="Source Timecode aligned", 2="Start Frames aligned"
        Note: All modes replace the entire node graph — there is no append mode.
      apply_arri_cdl_lut(source?, ...) -> {success}
      reset_all_grades(source?, ...) -> {success}

    source: "timeline" (default), "item" (needs track_type/track_index/item_index),
            "color_group_pre"/"color_group_post" (needs group_name)
    """
    p = params or {}
    source = p.get("source", "timeline")

    # Get the graph object based on source
    g = None
    if source == "timeline":
        _, tl, err = _get_tl()
        if err:
            return err
        g = tl.GetNodeGraph()
    elif source == "item":
        _, item, err = _get_item(p)
        if err:
            return err
        g = item.GetNodeGraph(p["layer_index"]) if "layer_index" in p else item.GetNodeGraph()
    elif source in ("color_group_pre", "color_group_post"):
        _, proj, err = _check()
        if err:
            return err
        groups = proj.GetColorGroupsList() or []
        for cg in groups:
            if cg.GetName() == p.get("group_name"):
                g = cg.GetPreClipNodeGraph() if source == "color_group_pre" else cg.GetPostClipNodeGraph()
                break
        if g is None:
            return _err(f"Color group '{p.get('group_name')}' not found")

    if not g:
        return _err("No node graph available for the specified source")

    if action == "get_num_nodes":
        return {"count": g.GetNumNodes()}
    elif action == "get_lut":
        return {"lut": g.GetLUT(p["node_index"])}
    elif action == "set_lut":
        return {"success": bool(g.SetLUT(p["node_index"], p["lut_path"]))}
    elif action == "get_node_cache":
        return {"cache": g.GetNodeCacheMode(p["node_index"])}
    elif action == "set_node_cache":
        return {"success": bool(g.SetNodeCacheMode(p["node_index"], p["cache_value"]))}
    elif action == "get_node_label":
        return {"label": g.GetNodeLabel(p["node_index"])}
    elif action == "get_tools_in_node":
        return {"tools": _ser(g.GetToolsInNode(p["node_index"]))}
    elif action == "set_node_enabled":
        return {"success": bool(g.SetNodeEnabled(p["node_index"], p["enabled"]))}
    elif action == "apply_grade_from_drx":
        return {"success": bool(g.ApplyGradeFromDRX(p["path"], p.get("grade_mode", p.get("mode", 0))))}
    elif action == "apply_arri_cdl_lut":
        return {"success": bool(g.ApplyArriCdlLut())}
    elif action == "reset_all_grades":
        return {"success": bool(g.ResetAllGrades())}
    return _unknown(action, ["get_num_nodes","get_lut","set_lut","get_node_cache","set_node_cache","get_node_label","get_tools_in_node","set_node_enabled","apply_grade_from_drx","apply_arri_cdl_lut","reset_all_grades"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 26: color_group
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def color_group(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Manage color groups and their node graphs.

    Actions:
      list() -> {groups}
      get_name(group_name) -> {name}
      set_name(group_name, new_name) -> {success}
      get_clips(group_name) -> {clips}
      get_pre_clip_graph(group_name) -> {available, num_nodes}
      get_post_clip_graph(group_name) -> {available, num_nodes}
    """
    p = params or {}
    _, proj, err = _check()
    if err:
        return err

    if action == "list":
        groups = proj.GetColorGroupsList() or []
        return {"groups": [g.GetName() for g in groups]}

    # All other actions need a group
    groups = proj.GetColorGroupsList() or []
    group = None
    for g in groups:
        if g.GetName() == p.get("group_name"):
            group = g
            break
    if not group:
        return _err(f"Color group '{p.get('group_name')}' not found")

    if action == "get_name":
        return {"name": group.GetName()}
    elif action == "set_name":
        return {"success": bool(group.SetName(p["new_name"]))}
    elif action == "get_clips":
        tl = proj.GetCurrentTimeline()
        clips = group.GetClipsInTimeline(tl) if tl else []
        return {"clips": [{"name": c.GetName(), "id": c.GetUniqueId()} for c in (clips or [])]}
    elif action == "get_pre_clip_graph":
        g = group.GetPreClipNodeGraph()
        return {"available": g is not None, "num_nodes": g.GetNumNodes() if g else 0}
    elif action == "get_post_clip_graph":
        g = group.GetPostClipNodeGraph()
        return {"available": g is not None, "num_nodes": g.GetNumNodes() if g else 0}
    return _unknown(action, ["list","get_name","set_name","get_clips","get_pre_clip_graph","get_post_clip_graph"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 27: fusion_comp
# ═══════════════════════════════════════════════════════════════════════════════

def _fusion_comp_bulk_set_inputs(p: Dict[str, Any]) -> Dict[str, Any]:
    """Apply set_input across many explicitly scoped timeline-item Fusion comps."""
    ops = p.get("ops")
    if not isinstance(ops, list) or not ops:
        return _err(
            "bulk_set_inputs requires params.ops: non-empty list of objects. "
            "Each op must include tool_name, input_name, value, and a timeline scope: "
            "clip_id, timeline_item_id, or timeline_item={track_type, track_index, item_index}. "
            "Optional per-op: comp_name, comp_index, time, undo_name."
        )

    results: List[Dict[str, Any]] = []
    for index, op in enumerate(ops):
        if not isinstance(op, dict):
            results.append({"index": index, "error": "op must be an object"})
            continue
        if not _has_fusion_timeline_scope(op):
            results.append({
                "index": index,
                "error": "timeline scope is required for bulk_set_inputs",
            })
            continue
        missing = [key for key in ("tool_name", "input_name", "value") if key not in op]
        if missing:
            results.append({"index": index, "error": f"missing required field(s): {', '.join(missing)}"})
            continue

        comp, comp_err = _resolve_fusion_comp(op, require_timeline_scope=True)
        if comp_err:
            results.append({"index": index, "error": comp_err.get("error", str(comp_err))})
            continue

        tool = comp.FindTool(op["tool_name"])
        if not tool:
            results.append({"index": index, "error": f"Tool {op['tool_name']!r} not found"})
            continue

        undo_name = op.get("undo_name", f"MCP bulk_set_inputs #{index}")
        undo_started = False
        keep_undo = False
        error_message = None
        try:
            try:
                comp.StartUndo(undo_name)
                undo_started = True
            except Exception:
                undo_started = False
            comp.Lock()
            try:
                if "time" in op:
                    tool.SetInput(op["input_name"], op["value"], op["time"])
                else:
                    tool.SetInput(op["input_name"], op["value"])
                keep_undo = True
            finally:
                comp.Unlock()
        except Exception as exc:
            error_message = str(exc)
        finally:
            if undo_started:
                try:
                    comp.EndUndo(keep_undo)
                except Exception:
                    pass
        if error_message is not None:
            results.append({"index": index, "error": error_message})
        elif keep_undo:
            results.append({"index": index, "success": True})

    return {"results": results, "op_count": len(ops)}


@mcp.tool()
def fusion_comp(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fusion composition node graph operations.

    Target comp:
      - Timeline item: pass clip_id, timeline_item_id, or
        timeline_item={track_type, track_index, item_index}. Optional comp_name or
        1-based comp_index selects a specific comp; otherwise the first comp is used.
      - Fusion page: omit timeline scope and this uses Fusion().GetCurrentComp().

    Use timeline_item_fusion to add/delete/import/export comps on items.

    Actions:
      add_tool(tool_type, x?, y?, name?) -> {tool_name, tool_type}
      delete_tool(tool_name) -> {success}
      get_tool_list(type?) -> {tools, count}
      find_tool(name) -> {found, name, type, attrs}
      connect(target_tool, input_name, source_tool, output_name?) -> {success}
      disconnect(tool_name, input_name) -> {success}
      get_inputs(tool_name) -> {inputs}
      get_outputs(tool_name) -> {outputs}
      set_input(tool_name, input_name, value, time?) -> {success}
      get_input(tool_name, input_name, time?) -> {value}
      set_attrs(tool_name, attrs) -> {success}
      get_attrs(tool_name) -> {attrs}
      add_keyframe(tool_name, input_name, time, value) -> {success}
      get_keyframes(tool_name, input_name) -> {keyframes}
      delete_keyframe(tool_name, input_name, time) -> {success}
      get_comp_info() -> {name, tool_count, attrs}
      set_frame_range(start, end) -> {success}
      render() -> {success}
      start_undo(name?) -> {success}
      end_undo(keep?) -> {success}
      bulk_set_inputs(ops) -> {results, op_count} — each op requires timeline scope plus tool_name, input_name, value

    Common tool_type values: Merge, Background, TextPlus, Transform, Blur,
      ColorCorrector, RectangleMask, EllipseMask, Tracker, MediaIn, MediaOut,
      Loader, Saver, Glow, FilmGrain, CornerPositioner, DeltaKeyer, UltraKeyer
    """
    p = params or {}

    if action == "bulk_set_inputs":
        return _fusion_comp_bulk_set_inputs(p)

    comp, comp_err = _resolve_fusion_comp(p)
    if comp_err:
        return comp_err

    # --- Node Management ---
    if action == "add_tool":
        tool_type = p.get("tool_type")
        if not tool_type:
            return _err("tool_type is required (e.g. 'Merge', 'Transform', 'TextPlus', 'Background')")
        x = p.get("x", -1)
        y = p.get("y", -1)
        comp.Lock()
        try:
            tool = comp.AddTool(tool_type, x, y)
            if not tool:
                return _err(f"Failed to add tool '{tool_type}'. Check the tool ID is valid.")
            name = p.get("name")
            if name:
                tool.SetAttrs({"TOOLS_Name": name})
            attrs = tool.GetAttrs()
            return {"tool_name": attrs.get("TOOLS_Name", ""), "tool_type": attrs.get("TOOLS_RegID", tool_type)}
        finally:
            comp.Unlock()

    elif action == "delete_tool":
        tool = comp.FindTool(p["tool_name"])
        if not tool:
            return _err(f"Tool '{p['tool_name']}' not found")
        comp.Lock()
        try:
            tool.Delete()
            return _ok()
        finally:
            comp.Unlock()

    elif action == "get_tool_list":
        filter_type = p.get("type")
        if filter_type:
            tools = comp.GetToolList(False, filter_type)
        else:
            tools = comp.GetToolList()
        result = []
        if tools:
            for idx in tools:
                t = tools[idx]
                attrs = t.GetAttrs()
                result.append({
                    "name": attrs.get("TOOLS_Name", ""),
                    "type": attrs.get("TOOLS_RegID", ""),
                })
        return {"tools": result, "count": len(result)}

    elif action == "find_tool":
        tool = comp.FindTool(p["name"])
        if not tool:
            return {"found": False}
        attrs = tool.GetAttrs()
        return {"found": True, "name": attrs.get("TOOLS_Name", ""), "type": attrs.get("TOOLS_RegID", ""), "attrs": _ser(attrs)}

    # --- Wiring ---
    elif action == "connect":
        target = comp.FindTool(p["target_tool"])
        if not target:
            return _err(f"Target tool '{p['target_tool']}' not found")
        source = comp.FindTool(p["source_tool"])
        if not source:
            return _err(f"Source tool '{p['source_tool']}' not found")
        comp.Lock()
        try:
            result = target.ConnectInput(p["input_name"], source)
            return {"success": bool(result)}
        finally:
            comp.Unlock()

    elif action == "disconnect":
        tool = comp.FindTool(p["tool_name"])
        if not tool:
            return _err(f"Tool '{p['tool_name']}' not found")
        comp.Lock()
        try:
            result = tool.ConnectInput(p["input_name"], None)
            return {"success": bool(result)}
        finally:
            comp.Unlock()

    elif action == "get_inputs":
        tool = comp.FindTool(p["tool_name"])
        if not tool:
            return _err(f"Tool '{p['tool_name']}' not found")
        input_list = tool.GetInputList()
        inputs = []
        if input_list:
            for idx in input_list:
                inp = input_list[idx]
                attrs = inp.GetAttrs()
                connected = inp.GetConnectedOutput()
                conn_info = None
                if connected:
                    conn_tool = connected.GetTool()
                    if conn_tool:
                        conn_info = conn_tool.GetAttrs().get("TOOLS_Name", "")
                inputs.append({
                    "name": attrs.get("INPS_Name", ""),
                    "id": attrs.get("INPS_ID", ""),
                    "type": attrs.get("INPS_DataType", ""),
                    "connected_to": conn_info,
                })
        return {"inputs": inputs}

    elif action == "get_outputs":
        tool = comp.FindTool(p["tool_name"])
        if not tool:
            return _err(f"Tool '{p['tool_name']}' not found")
        output_list = tool.GetOutputList()
        outputs = []
        if output_list:
            for idx in output_list:
                out = output_list[idx]
                attrs = out.GetAttrs()
                outputs.append({
                    "name": attrs.get("OUTS_Name", ""),
                    "id": attrs.get("OUTS_ID", ""),
                    "type": attrs.get("OUTS_DataType", ""),
                })
        return {"outputs": outputs}

    # --- Parameters ---
    elif action == "set_input":
        tool = comp.FindTool(p["tool_name"])
        if not tool:
            return _err(f"Tool '{p['tool_name']}' not found")
        comp.Lock()
        try:
            if "time" in p:
                tool.SetInput(p["input_name"], p["value"], p["time"])
            else:
                tool.SetInput(p["input_name"], p["value"])
            return _ok()
        finally:
            comp.Unlock()

    elif action == "get_input":
        tool = comp.FindTool(p["tool_name"])
        if not tool:
            return _err(f"Tool '{p['tool_name']}' not found")
        if "time" in p:
            val = tool.GetInput(p["input_name"], p["time"])
        else:
            val = tool.GetInput(p["input_name"])
        return {"value": _ser(val)}

    elif action == "set_attrs":
        tool = comp.FindTool(p["tool_name"])
        if not tool:
            return _err(f"Tool '{p['tool_name']}' not found")
        tool.SetAttrs(p["attrs"])
        return _ok()

    elif action == "get_attrs":
        tool = comp.FindTool(p["tool_name"])
        if not tool:
            return _err(f"Tool '{p['tool_name']}' not found")
        return {"attrs": _ser(tool.GetAttrs())}

    # --- Keyframes ---
    elif action == "add_keyframe":
        tool = comp.FindTool(p["tool_name"])
        if not tool:
            return _err(f"Tool '{p['tool_name']}' not found")
        comp.Lock()
        try:
            inp = tool[p["input_name"]]
            if not inp:
                return _err(f"Input '{p['input_name']}' not found on tool '{p['tool_name']}'")
            inp[p["time"]] = p["value"]
            return _ok()
        finally:
            comp.Unlock()

    elif action == "get_keyframes":
        tool = comp.FindTool(p["tool_name"])
        if not tool:
            return _err(f"Tool '{p['tool_name']}' not found")
        inp = tool[p["input_name"]]
        if not inp:
            return _err(f"Input '{p['input_name']}' not found on tool '{p['tool_name']}'")
        keyframes = []
        kfs = inp.GetKeyFrames()
        if kfs:
            for t in kfs:
                keyframes.append({"time": t, "value": _ser(kfs[t])})
        return {"keyframes": keyframes}

    elif action == "delete_keyframe":
        tool = comp.FindTool(p["tool_name"])
        if not tool:
            return _err(f"Tool '{p['tool_name']}' not found")
        comp.Lock()
        try:
            inp = tool[p["input_name"]]
            if not inp:
                return _err(f"Input '{p['input_name']}' not found on tool '{p['tool_name']}'")
            inp.RemoveKeyFrame(p["time"])
            return _ok()
        finally:
            comp.Unlock()

    # --- Composition Control ---
    elif action == "get_comp_info":
        attrs = comp.GetAttrs()
        return {
            "name": attrs.get("COMPS_Name", ""),
            "tool_count": len(comp.GetToolList() or {}),
            "attrs": _ser(attrs),
        }

    elif action == "set_frame_range":
        comp.SetAttrs({"COMPN_RenderStartTime": p["start"], "COMPN_RenderEndTime": p["end"]})
        return _ok()

    elif action == "render":
        comp.Render()
        return _ok()

    elif action == "start_undo":
        comp.StartUndo(p.get("name", "MCP Operation"))
        return _ok()

    elif action == "end_undo":
        comp.EndUndo(p.get("keep", True))
        return _ok()

    return _unknown(action, [
        "add_tool","delete_tool","get_tool_list","find_tool",
        "connect","disconnect","get_inputs","get_outputs",
        "set_input","get_input","set_attrs","get_attrs",
        "add_keyframe","get_keyframes","delete_keyframe",
        "get_comp_info","set_frame_range","render",
        "start_undo","end_undo",
        "bulk_set_inputs",
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 28: fuse_plugin
# ═══════════════════════════════════════════════════════════════════════════════

# Fusion's naming rule (Fuse SDK p. 40): identifiers must match this pattern,
# else the resulting comp will save but fail to reopen.
_FUSE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FUSE_MARKER = "@mcp-fuse"


def _fuses_dir() -> str:
    return get_resolve_plugin_paths()["fuses_dir"]


def _validate_fuse_name(name: str) -> Optional[Dict[str, Any]]:
    if not name or not _FUSE_NAME_RE.match(name):
        return _err(f"Invalid Fuse name '{name}'. Must match [A-Za-z_][A-Za-z0-9_]* "
                    "(Fuse SDK requirement; bad names produce comps that won't reopen).")
    return None


def _fuse_path(name: str) -> str:
    return os.path.join(_fuses_dir(), f"{name}.fuse")


def _validate_lua_syntax(source: str) -> Dict[str, Any]:
    """Run `luac -p` if available. Returns {'valid': bool, 'errors': str|None,
    'checker': 'luac'|'unavailable'}."""
    luac = None
    for candidate in ("luac", "luac5.1", "luac5.3", "luac5.4"):
        try:
            subprocess.run([candidate, "-v"], capture_output=True, check=True, timeout=5)
            luac = candidate
            break
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    if luac is None:
        return {"valid": True, "errors": None, "checker": "unavailable"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".lua", delete=False) as f:
        f.write(source)
        tmp = f.name
    try:
        result = subprocess.run([luac, "-p", tmp], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return {"valid": True, "errors": None, "checker": luac}
        return {"valid": False, "errors": result.stderr.strip() or result.stdout.strip(),
                "checker": luac}
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _validate_glsl_minimal(source: str) -> Dict[str, Any]:
    """Cheap GLSL sanity check — verifies the required ShadePixel signature is
    present and braces balance. Real GLSL validation needs glslangValidator,
    which isn't bundled with Resolve."""
    if "ShadePixel" not in source:
        return {"valid": False, "errors": "Missing required `void ShadePixel(inout FuPixel f)`",
                "checker": "minimal"}
    if source.count("{") != source.count("}"):
        return {"valid": False, "errors": "Unbalanced braces in shader source.",
                "checker": "minimal"}
    return {"valid": True, "errors": None, "checker": "minimal"}


@mcp.tool()
def fuse_plugin(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Author and install Fusion Fuse plugins (.fuse files).

    Fuses are Lua plugins (or GLSL view-LUT shaders) that Fusion loads at
    startup. A NEW Fuse requires a Resolve restart to register; existing Fuses
    can be edited and reloaded from the Inspector's Edit/Reload buttons without
    restart. The MCP cannot trigger reload — that's a UI-only action.

    Actions:
      path() -> {fuses_dir}
      list() -> {fuses}  — Fuses with the @mcp-fuse marker comment.
      list(all=true) -> {fuses}  — All .fuse files in the directory.
      install(name, source, overwrite?) -> {success, path}
        — name: [A-Za-z_][A-Za-z0-9_]*
        — source: full Fuse source (Lua, or Lua+GLSL for view LUTs)
        — overwrite: bool (default false)
      remove(name) -> {success}
      read(name) -> {source}
      validate(source, type?) -> {valid, errors, checker}
        — type: 'lua' (default) | 'glsl'
      template(kind, name, options?) -> {source, kind, name}
        — Returns generated source. Pass it to install() to write to disk.
        — kind: one of the keys returned by list_templates(). See
          docs/fuse-dctl-authoring.md for the per-kind option spec.
      list_templates() -> {kinds}
    """
    p = params or {}

    if action == "path":
        return {"fuses_dir": _fuses_dir()}

    if action == "list_templates":
        return {"kinds": sorted(fuse_templates.TEMPLATES.keys())}

    if action == "list":
        d = _fuses_dir()
        if not os.path.isdir(d):
            return {"fuses": []}
        show_all = bool(p.get("all", False))
        out = []
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".fuse"):
                continue
            full = os.path.join(d, fn)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    head = f.read(512)
            except OSError:
                continue
            mcp_managed = _FUSE_MARKER in head
            if show_all or mcp_managed:
                out.append({"name": fn[:-5], "path": full, "mcp_managed": mcp_managed})
        return {"fuses": out}

    if action == "install":
        name = p.get("name", "")
        invalid = _validate_fuse_name(name)
        if invalid:
            return invalid
        source = p.get("source")
        if not isinstance(source, str) or not source.strip():
            return _err("install requires a non-empty 'source' string.")
        d = _fuses_dir()
        os.makedirs(d, exist_ok=True)
        path = _fuse_path(name)
        if os.path.exists(path) and not p.get("overwrite", False):
            return _err(f"Fuse '{name}' already exists at {path}. "
                        "Pass overwrite=true to replace it.")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
        except OSError as e:
            return _err(f"Failed to write Fuse: {e}")
        return _ok(path=path,
                   note="Restart DaVinci Resolve to register a new Fuse. "
                        "Existing Fuses can be reloaded via the Inspector.")

    if action == "remove":
        name = p.get("name", "")
        invalid = _validate_fuse_name(name)
        if invalid:
            return invalid
        path = _fuse_path(name)
        if not os.path.isfile(path):
            return _err(f"No Fuse named '{name}' at {path}")
        try:
            os.unlink(path)
        except OSError as e:
            return _err(f"Failed to remove Fuse: {e}")
        return _ok(path=path)

    if action == "read":
        name = p.get("name", "")
        invalid = _validate_fuse_name(name)
        if invalid:
            return invalid
        path = _fuse_path(name)
        if not os.path.isfile(path):
            return _err(f"No Fuse named '{name}' at {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return {"source": f.read(), "path": path}
        except OSError as e:
            return _err(f"Failed to read Fuse: {e}")

    if action == "validate":
        source = p.get("source")
        if not isinstance(source, str):
            return _err("validate requires a 'source' string.")
        kind = p.get("type", "lua")
        if kind == "glsl":
            return _validate_glsl_minimal(source)
        return _validate_lua_syntax(source)

    if action == "template":
        kind = p.get("kind", "")
        name = p.get("name", "")
        invalid = _validate_fuse_name(name)
        if invalid:
            return invalid
        gen = fuse_templates.TEMPLATES.get(kind)
        if gen is None:
            return _err(f"Unknown template kind '{kind}'. Valid: "
                        f"{sorted(fuse_templates.TEMPLATES.keys())}")
        try:
            source = gen(name, p.get("options"))
        except (ValueError, KeyError, TypeError) as e:
            return _err(f"Template generation failed: {e}")
        return {"source": source, "kind": kind, "name": name}

    return _unknown(action, ["path", "list", "install", "remove", "read",
                             "validate", "template", "list_templates"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 29: dctl
# ═══════════════════════════════════════════════════════════════════════════════

# Fuse identifier rules don't apply to DCTL filenames, but we still want safe
# filesystem names. Disallow path separators and shell-hostile characters.
_DCTL_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ \-]{0,127}$")
_DCTL_MARKER = "@mcp-dctl"
_DCTL_VALID_EXT = (".dctl", ".dctle")


def _dctl_dir(category: str = "lut") -> str:
    """Return the install root for a given DCTL category.

    'lut'      → regular LUT folder, picked up by RefreshLUTList()
    'aces_idt' → ACES Transforms/IDT, scanned only at Resolve startup
    'aces_odt' → ACES Transforms/ODT, scanned only at Resolve startup
    """
    paths = get_resolve_plugin_paths()
    if category == "lut":
        return paths["dctl_dir"]
    if category == "aces_idt":
        return paths["aces_idt_dir"]
    if category == "aces_odt":
        return paths["aces_odt_dir"]
    raise ValueError(f"Unknown DCTL category '{category}'. "
                     "Valid: lut, aces_idt, aces_odt")


def _validate_dctl_name(name: str) -> Optional[Dict[str, Any]]:
    if not name or not _DCTL_NAME_RE.match(name):
        return _err(f"Invalid DCTL name '{name}'. "
                    "Must match [A-Za-z0-9_][A-Za-z0-9_ \\-]{0,127}.")
    return None


def _resolve_dctl_subdir(subdir: Optional[str]) -> Optional[str]:
    """Validate a subdir string and return it as a normalized POSIX-style path
    relative segment. Returns None for no subdir, or raises ValueError."""
    if not subdir:
        return None
    if "\\" in subdir:
        subdir = subdir.replace("\\", "/")
    parts = [p.strip() for p in subdir.split("/") if p.strip()]
    if not parts:
        return None
    for p in parts:
        if p in (".", "..") or "/" in p or "\\" in p:
            raise ValueError(f"Unsafe subdir segment: '{p}'")
        if p.startswith("."):
            raise ValueError(f"Hidden subdir not allowed: '{p}'")
    return os.path.join(*parts)


def _dctl_path(name: str, subdir: Optional[str] = None,
               ext: str = ".dctl", category: str = "lut") -> str:
    sd = _resolve_dctl_subdir(subdir)
    root = _dctl_dir(category)
    base = root if sd is None else os.path.join(root, sd)
    return os.path.join(base, f"{name}{ext}")


def _validate_dctl_source(source: str) -> Dict[str, Any]:
    """Lightweight DCTL sanity check.

    Verifies a transform() or transition() entry point is present, brace
    balance is intact, and warns about float literals missing the `f` suffix
    (a common cause of unhelpful build errors per docs/dctl-notes.md).
    """
    warnings = []
    has_transform = "transform(" in source and "__DEVICE__" in source
    has_transition = "transition(" in source and "TRANSITION_PROGRESS" in source
    if not (has_transform or has_transition):
        return {"valid": False,
                "errors": "Missing __DEVICE__ transform() or transition() entry point.",
                "warnings": warnings, "checker": "minimal"}
    if source.count("{") != source.count("}"):
        return {"valid": False, "errors": "Unbalanced braces.",
                "warnings": warnings, "checker": "minimal"}
    # Find decimal literals without an 'f' suffix in C-like contexts. This is
    # a heuristic, not a parser — it skips lines starting with // and lines
    # inside DEFINE_UI_PARAMS where Python-style numbers are also accepted.
    import re as _re
    suspicious = _re.compile(r"(?<![A-Za-z_0-9])[0-9]+\.[0-9]+(?![fA-Za-z_0-9])")
    for lineno, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("DEFINE_UI"):
            continue
        if "transform" in stripped or "transition" in stripped:
            # Header lines have type names like "float p_R", not numeric literals.
            continue
        for m in suspicious.finditer(line):
            warnings.append(f"line {lineno}: float literal '{m.group(0)}' "
                            "is missing 'f' suffix (DCTL requires '1.2f').")
    return {"valid": True, "errors": None, "warnings": warnings,
            "checker": "minimal"}


_DCTL_VALID_CATEGORIES = ("lut", "aces_idt", "aces_odt")


@mcp.tool()
def dctl(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Author and install DCTL files (Color page custom shaders + ACES transforms).

    Regular DCTLs live under Resolve's LUT directory and appear as LUT-style
    entries in the LUT browser, the Clip/Node LUT picker, and the ResolveFX
    DCTL plugin. After install, call project_settings(action='refresh_luts')
    to make Resolve pick up the new file.

    ACES DCTLs (IDT/ODT) live in a separate ACES Transforms directory tree
    and are scanned only at Resolve startup — install requires a Resolve
    restart, NOT a LUT refresh.

    See docs/dctl-notes.md for the full spec and docs/fuse-dctl-authoring.md
    for the experimental-tools coverage matrix.

    Actions:
      path(category?, subdir?) -> {dctl_dir}
        — category: 'lut' (default) | 'aces_idt' | 'aces_odt'
      list(category?, subdir?, all?) -> {files}
        — Default: only files with @mcp-dctl marker. Pass all=true for everything.
      install(name, source, category?, subdir?, ext?, overwrite?) -> {success, path}
        — name: filesystem-safe identifier
        — source: DCTL source as a string
        — category: 'lut' (default) | 'aces_idt' | 'aces_odt'
        — subdir: optional folder under the install root
        — ext: '.dctl' (default) or '.dctle' (encrypted)
      remove(name, category?, subdir?, ext?) -> {success}
      read(name, category?, subdir?, ext?) -> {source, encrypted}
      validate(source) -> {valid, errors, warnings, checker}
      template(kind, name, options?) -> {source, kind, name, suggested_category}
        — kind: 'transform' | 'transform_alpha' | 'transition' | 'matrix' |
                'kernel' | 'lut_apply' | 'aces_idt' | 'aces_odt'
        — `aces_*` kinds set suggested_category to 'aces_idt'/'aces_odt';
          pass that as the `category` argument to install().
      list_templates() -> {kinds, kind_categories}
    """
    p = params or {}

    def _category(default: str = "lut") -> Tuple[Optional[Dict[str, Any]], str]:
        cat = p.get("category", default)
        if cat not in _DCTL_VALID_CATEGORIES:
            return _err(f"Invalid category '{cat}'. "
                        f"Valid: {list(_DCTL_VALID_CATEGORIES)}"), default
        return None, cat

    if action == "path":
        err, cat = _category()
        if err:
            return err
        try:
            normalized = _resolve_dctl_subdir(p.get("subdir"))
        except ValueError as e:
            return _err(str(e))
        root = _dctl_dir(cat)
        out = root if normalized is None else os.path.join(root, normalized)
        return {"dctl_dir": out, "category": cat}

    if action == "list_templates":
        return {
            "kinds": sorted(dctl_templates.TEMPLATES.keys()),
            "kind_categories": dict(dctl_templates.KIND_CATEGORY),
        }

    if action == "list":
        err, cat = _category()
        if err:
            return err
        try:
            sd = _resolve_dctl_subdir(p.get("subdir"))
        except ValueError as e:
            return _err(str(e))
        root = _dctl_dir(cat)
        root = root if sd is None else os.path.join(root, sd)
        if not os.path.isdir(root):
            return {"files": []}
        show_all = bool(p.get("all", False))
        out = []
        for fn in sorted(os.listdir(root)):
            if not fn.lower().endswith(_DCTL_VALID_EXT):
                continue
            full = os.path.join(root, fn)
            mcp_managed = False
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    head = f.read(512)
                mcp_managed = _DCTL_MARKER in head
            except OSError:
                continue
            if show_all or mcp_managed:
                out.append({"name": os.path.splitext(fn)[0], "ext": os.path.splitext(fn)[1],
                            "path": full, "mcp_managed": mcp_managed,
                            "category": cat})
        return {"files": out}

    if action == "install":
        name = p.get("name", "")
        invalid = _validate_dctl_name(name)
        if invalid:
            return invalid
        source = p.get("source")
        if not isinstance(source, str) or not source.strip():
            return _err("install requires a non-empty 'source' string.")
        ext = p.get("ext", ".dctl")
        if ext not in _DCTL_VALID_EXT:
            return _err(f"ext must be one of {list(_DCTL_VALID_EXT)}")
        err, cat = _category()
        if err:
            return err
        try:
            sd = _resolve_dctl_subdir(p.get("subdir"))
        except ValueError as e:
            return _err(str(e))
        root = _dctl_dir(cat)
        target_dir = root if sd is None else os.path.join(root, sd)
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, f"{name}{ext}")
        if os.path.exists(path) and not p.get("overwrite", False):
            return _err(f"DCTL '{name}{ext}' already exists at {path}. "
                        "Pass overwrite=true to replace it.")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
        except OSError as e:
            return _err(f"Failed to write DCTL: {e}")
        if cat == "lut":
            note = ("Call project_settings(action='refresh_luts') to make "
                    "Resolve pick up the new DCTL.")
        else:
            note = ("ACES DCTLs are scanned only at Resolve startup. "
                    "Restart Resolve before this transform appears.")
        return _ok(path=path, category=cat, note=note)

    if action == "remove":
        name = p.get("name", "")
        invalid = _validate_dctl_name(name)
        if invalid:
            return invalid
        ext = p.get("ext", ".dctl")
        if ext not in _DCTL_VALID_EXT:
            return _err(f"ext must be one of {list(_DCTL_VALID_EXT)}")
        err, cat = _category()
        if err:
            return err
        try:
            sd = _resolve_dctl_subdir(p.get("subdir"))
        except ValueError as e:
            return _err(str(e))
        target = _dctl_path(name, sd, ext, cat)
        if not os.path.isfile(target):
            return _err(f"No DCTL named '{name}{ext}' at {target}")
        try:
            os.unlink(target)
        except OSError as e:
            return _err(f"Failed to remove DCTL: {e}")
        return _ok(path=target)

    if action == "read":
        name = p.get("name", "")
        invalid = _validate_dctl_name(name)
        if invalid:
            return invalid
        ext = p.get("ext", ".dctl")
        if ext not in _DCTL_VALID_EXT:
            return _err(f"ext must be one of {list(_DCTL_VALID_EXT)}")
        err, cat = _category()
        if err:
            return err
        try:
            sd = _resolve_dctl_subdir(p.get("subdir"))
        except ValueError as e:
            return _err(str(e))
        target = _dctl_path(name, sd, ext, cat)
        if not os.path.isfile(target):
            return _err(f"No DCTL named '{name}{ext}' at {target}")
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                src = f.read()
        except OSError as e:
            return _err(f"Failed to read DCTL: {e}")
        return {"source": src, "path": target,
                "encrypted": ext == ".dctle", "category": cat}

    if action == "validate":
        source = p.get("source")
        if not isinstance(source, str):
            return _err("validate requires a 'source' string.")
        return _validate_dctl_source(source)

    if action == "template":
        kind = p.get("kind", "")
        name = p.get("name", "")
        invalid = _validate_dctl_name(name)
        if invalid:
            return invalid
        gen = dctl_templates.TEMPLATES.get(kind)
        if gen is None:
            return _err(f"Unknown template kind '{kind}'. Valid: "
                        f"{sorted(dctl_templates.TEMPLATES.keys())}")
        try:
            source = gen(name, p.get("options"))
        except (ValueError, KeyError, TypeError) as e:
            return _err(f"Template generation failed: {e}")
        return {
            "source": source, "kind": kind, "name": name,
            "suggested_category": dctl_templates.KIND_CATEGORY.get(kind, "lut"),
        }

    return _unknown(action, ["path", "list", "install", "remove", "read",
                             "validate", "template", "list_templates"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 30: script_plugin
# ═══════════════════════════════════════════════════════════════════════════════

# Resolve-page Lua/Python scripts must be filesystem-safe identifiers.
_SCRIPT_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ \-]{0,127}$")
_SCRIPT_MARKER = "@mcp-script"
_SCRIPT_VALID_LANG = ("lua", "py")
_SCRIPT_LANG_EXT = {"lua": ".lua", "py": ".py"}


def _scripts_dir(category: str) -> str:
    paths = get_resolve_plugin_paths()
    valid = paths["scripts_categories"]
    if category not in valid:
        raise ValueError(f"Invalid category '{category}'. Valid: {list(valid)}")
    return os.path.join(paths["scripts_root"], category)


def _validate_script_name(name: str) -> Optional[Dict[str, Any]]:
    if not name or not _SCRIPT_NAME_RE.match(name):
        return _err(f"Invalid script name '{name}'. "
                    "Must match [A-Za-z0-9_][A-Za-z0-9_ \\-]{0,127}.")
    return None


def _validate_script_language(language: str) -> Optional[Dict[str, Any]]:
    if language not in _SCRIPT_VALID_LANG:
        return _err(f"Invalid language '{language}'. "
                    f"Valid: {list(_SCRIPT_VALID_LANG)}")
    return None


def _script_path(name: str, category: str, language: str) -> str:
    return os.path.join(_scripts_dir(category), f"{name}{_SCRIPT_LANG_EXT[language]}")


def _validate_script_source(source: str, language: str) -> Dict[str, Any]:
    """Cheap syntax check. Lua → luac -p if available; Python → compile()."""
    if language == "py":
        try:
            compile(source, "<script>", "exec")
            return {"valid": True, "errors": None, "checker": "python-compile"}
        except SyntaxError as e:
            return {"valid": False,
                    "errors": f"line {e.lineno}: {e.msg}",
                    "checker": "python-compile"}
    # Lua
    return _validate_lua_syntax(source)


# ─── Script execution ─────────────────────────────────────────────────────────

def _python_env_for_resolve() -> Dict[str, str]:
    """Build env vars so a Python subprocess can import DaVinciResolveScript."""
    env = os.environ.copy()
    env["RESOLVE_SCRIPT_API"] = RESOLVE_API_PATH
    env["RESOLVE_SCRIPT_LIB"] = RESOLVE_LIB_PATH
    pp = env.get("PYTHONPATH", "")
    if RESOLVE_MODULES_PATH not in pp:
        env["PYTHONPATH"] = (RESOLVE_MODULES_PATH +
                             (os.pathsep + pp if pp else ""))
    return env


def _execute_python_script(path: str, args: List[str],
                            timeout: int) -> Dict[str, Any]:
    # Ensure Resolve is running so the script can connect.
    get_resolve()
    cmd = [sys.executable, path] + [str(a) for a in args]
    try:
        result = subprocess.run(cmd, env=_python_env_for_resolve(),
                                 capture_output=True, text=True,
                                 timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return _err(f"Script timed out after {timeout}s. "
                    f"Partial stdout: {(e.stdout or '')[:1000]}")
    except OSError as e:
        return _err(f"Failed to launch Python subprocess: {e}")
    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
        "language": "py",
    }


def _execute_lua_script(path: str) -> Dict[str, Any]:
    r = get_resolve()
    if r is None:
        return _err("Cannot run Lua script — Resolve isn't running and "
                    "auto-launch failed.")
    fusion = r.Fusion()
    if fusion is None:
        return _err("handle.Fusion() returned None — cannot run Lua scripts.")
    try:
        success = bool(fusion.RunScript(path))
    except Exception as e:
        return _err(f"Lua RunScript failed: {e}")
    return {
        "success": success,
        "language": "lua",
        "output_note": ("Lua print() output goes to Resolve's "
                        "Workspace → Console → Lua tab. The MCP cannot capture "
                        "Lua stdout. Use the Console to see what the script printed."),
    }


def _run_inline_python(source: str, timeout: int) -> Dict[str, Any]:
    """Write source to a temp file, run it, return captured output.

    Prepends a boilerplate header that connects to Resolve and exposes
    `resolve`, `project`, `mp`, `timeline` as globals — same shape as the
    scaffold template, so inline snippets feel like a REPL.
    """
    boilerplate = (
        "import sys\n"
        "import DaVinciResolveScript as dvr_script\n"
        "resolve = dvr_script.scriptapp('Resolve')\n"
        "project = (resolve.GetProjectManager().GetCurrentProject()\n"
        "           if resolve else None)\n"
        "mp = project.GetMediaPool() if project else None\n"
        "timeline = project.GetCurrentTimeline() if project else None\n"
        "\n"
    )
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py',
                                      delete=False, encoding='utf-8') as f:
        f.write(boilerplate)
        f.write(source)
        tmp = f.name
    try:
        return _execute_python_script(tmp, [], timeout)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _run_inline_lua(source: str) -> Dict[str, Any]:
    """Run a Lua snippet inside Resolve's Fusion engine.

    Implementation note: Fusion's `Execute()` is effectively a no-op from the
    Python bridge in Resolve 20.x — it runs without propagating return values
    or side effects observable from Python. `RunScript()` against a file path
    DOES work and gives the script full access to the standard Lua context
    (`fu`, `fusion`, `app`, `bmd`, `io`, `os`, ...). We bridge results back
    via `app:SetData(key, value)` which IS visible from Python's
    `fusion.GetData(key)`.

    The wrapper captures `print()` output into a string and stores stdout,
    return value, and any pcall error in three Fusion-app SetData slots that
    the Python side reads after RunScript returns.
    """
    r = get_resolve()
    if r is None:
        return _err("Cannot run Lua — Resolve isn't running and auto-launch failed.")
    fusion = r.Fusion()
    if fusion is None:
        return _err("handle.Fusion() returned None — cannot run inline Lua.")

    wrapped = (
        'local _mcp_stdout = {}\n'
        'local _mcp_orig_print = print\n'
        'print = function(...)\n'
        '    local args = {...}\n'
        '    local parts = {}\n'
        '    for i, v in ipairs(args) do parts[i] = tostring(v) end\n'
        '    table.insert(_mcp_stdout, table.concat(parts, "\\t"))\n'
        'end\n'
        'local _mcp_ok, _mcp_result = pcall(function()\n'
        + source + '\n'
        'end)\n'
        'print = _mcp_orig_print\n'
        'local _mcp_app = fu or fusion or app\n'
        'if _mcp_app then\n'
        '    _mcp_app:SetData("__mcp_stdout__", table.concat(_mcp_stdout, "\\n"))\n'
        '    if _mcp_ok then\n'
        '        _mcp_app:SetData("__mcp_result__",\n'
        '            _mcp_result ~= nil and tostring(_mcp_result) or "")\n'
        '        _mcp_app:SetData("__mcp_error__", "")\n'
        '    else\n'
        '        _mcp_app:SetData("__mcp_result__", "")\n'
        '        _mcp_app:SetData("__mcp_error__", tostring(_mcp_result))\n'
        '    end\n'
        '    _mcp_app:SetData("__mcp_done__", "1")\n'  # completion sentinel
        'end\n'
    )

    # Clear prior slots so we can detect if RunScript silently did nothing.
    fusion.SetData("__mcp_done__", "")
    fusion.SetData("__mcp_stdout__", "")
    fusion.SetData("__mcp_result__", "")
    fusion.SetData("__mcp_error__", "")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.lua',
                                      prefix='mcp-lua-inline-',
                                      delete=False, encoding='utf-8') as tf:
        tf.write(wrapped)
        tmp = tf.name

    try:
        try:
            fusion.RunScript(tmp)
        except Exception as e:
            return _err(f"Lua RunScript failed: {e}")

        # RunScript is async — poll the completion sentinel until set.
        deadline = time.time() + 60
        while fusion.GetData("__mcp_done__") != "1":
            if time.time() > deadline:
                return _err("Lua run_inline timed out after 60s waiting for "
                            "the script to complete.")
            time.sleep(0.1)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    stdout = fusion.GetData("__mcp_stdout__") or ""
    result = fusion.GetData("__mcp_result__") or ""
    error = fusion.GetData("__mcp_error__") or ""

    response: Dict[str, Any] = {
        "success": not error,
        "stdout": stdout + ("\n" if stdout and not stdout.endswith("\n") else ""),
        "language": "lua",
    }
    if result:
        response["result"] = result
    if error:
        response["error"] = error
    return response


@mcp.tool()
def script_plugin(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Author and install Resolve-page Lua/Python scripts (Workspace → Scripts menu).

    Scripts live under the per-category subdirs of Resolve's Fusion/Scripts/
    directory and appear automatically in Workspace → Scripts → <category>
    on the page that matches the category. Resolve picks up new scripts
    without a restart — the menu refreshes the next time it's opened.

    Categories: 'Edit', 'Color', 'Deliver', 'Comp', 'Tool', 'Utility', 'Views'.
    'Utility' shows up everywhere; the rest only on the matching page.

    Two template kinds:
      - 'scaffold'    minimal stub with Resolve handle setup
      - 'media_rules' rules-and-variables DSL (declarative VARIABLES + RULES
                       interpreted by an embedded engine; supports sources,
                       extract patterns, transforms, targets, actions,
                       conditions, dry-run, external CSV/JSON data, fuzzy
                       matching, and per-rule metadata)

    Both languages (Lua and Python) generate fully self-contained scripts.

    See docs/script-plugin-authoring.md for the DSL spec.

    Actions:
      path(category) -> {scripts_dir}
      categories() -> {categories}
      list(category?, all?, language?) -> {scripts}
      install(name, source, category, language?, overwrite?) -> {success, path}
      remove(name, category, language) -> {success}
      read(name, category, language) -> {source}
      validate(source, language?) -> {valid, errors, checker}
      template(kind, name, options?) -> {source, kind, name, language}
        — kind: 'scaffold' | 'media_rules'
        — options: {language: 'lua'|'py', ...kind-specific}
      list_templates() -> {kinds}
      execute(name, category, language, args?, timeout?) -> {success, stdout?, stderr?, exit_code?}
        — Python: subprocess with stdout/stderr captured.
        — Lua: fusion.RunScript(); print() output goes to Resolve Console.
        — args: list of CLI args for the Python subprocess (Python only).
        — timeout: seconds (default 120 for execute, 60 for run_inline).
        — Auto-launches Resolve if not running.
      run_inline(source, language, timeout?) -> {success, stdout?, stderr?, result?}
        — Python: writes to temp file with `resolve`/`project`/`mp`/`timeline`
          pre-bound, runs as subprocess, captures stdout/stderr.
        — Lua: fusion.Execute(source); return value comes back as `result`.
        — Use this for ad-hoc one-shot queries without persisting a file.
    """
    p = params or {}

    if action == "categories":
        paths = get_resolve_plugin_paths()
        return {"categories": list(paths["scripts_categories"])}

    if action == "list_templates":
        return {"kinds": sorted(script_templates.TEMPLATES.keys())}

    if action == "path":
        category = p.get("category")
        if not category:
            return _err("path requires a 'category' argument.")
        try:
            return {"scripts_dir": _scripts_dir(category), "category": category}
        except ValueError as e:
            return _err(str(e))

    if action == "list":
        category = p.get("category")
        language_filter = p.get("language")
        if language_filter and language_filter not in _SCRIPT_VALID_LANG:
            return _err(f"Invalid language '{language_filter}'. "
                        f"Valid: {list(_SCRIPT_VALID_LANG)}")
        show_all = bool(p.get("all", False))

        paths = get_resolve_plugin_paths()
        if category:
            try:
                roots = [(category, _scripts_dir(category))]
            except ValueError as e:
                return _err(str(e))
        else:
            roots = [(c, os.path.join(paths["scripts_root"], c))
                     for c in paths["scripts_categories"]]

        out = []
        for cat, root in roots:
            if not os.path.isdir(root):
                continue
            for fn in sorted(os.listdir(root)):
                ext = os.path.splitext(fn)[1].lower()
                if ext not in (".lua", ".py"):
                    continue
                lang = "lua" if ext == ".lua" else "py"
                if language_filter and lang != language_filter:
                    continue
                full = os.path.join(root, fn)
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        head = f.read(512)
                except OSError:
                    continue
                mcp_managed = _SCRIPT_MARKER in head
                if show_all or mcp_managed:
                    out.append({
                        "name": os.path.splitext(fn)[0],
                        "language": lang,
                        "category": cat,
                        "path": full,
                        "mcp_managed": mcp_managed,
                    })
        return {"scripts": out}

    if action == "install":
        name = p.get("name", "")
        invalid = _validate_script_name(name)
        if invalid:
            return invalid
        source = p.get("source")
        if not isinstance(source, str) or not source.strip():
            return _err("install requires a non-empty 'source' string.")
        category = p.get("category")
        if not category:
            return _err("install requires a 'category'.")
        language = p.get("language", "lua")
        invalid = _validate_script_language(language)
        if invalid:
            return invalid
        try:
            target_dir = _scripts_dir(category)
        except ValueError as e:
            return _err(str(e))
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, f"{name}{_SCRIPT_LANG_EXT[language]}")
        if os.path.exists(path) and not p.get("overwrite", False):
            return _err(f"Script '{name}{_SCRIPT_LANG_EXT[language]}' already "
                        f"exists at {path}. Pass overwrite=true to replace it.")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
        except OSError as e:
            return _err(f"Failed to write script: {e}")
        return _ok(path=path, category=category, language=language,
                   note="Resolve picks up new scripts without a restart. "
                        "Open Workspace → Scripts → " + category +
                        " to run.")

    if action == "remove":
        name = p.get("name", "")
        invalid = _validate_script_name(name)
        if invalid:
            return invalid
        category = p.get("category")
        if not category:
            return _err("remove requires a 'category'.")
        language = p.get("language", "lua")
        invalid = _validate_script_language(language)
        if invalid:
            return invalid
        try:
            target = _script_path(name, category, language)
        except ValueError as e:
            return _err(str(e))
        if not os.path.isfile(target):
            return _err(f"No script named '{name}{_SCRIPT_LANG_EXT[language]}' at {target}")
        try:
            os.unlink(target)
        except OSError as e:
            return _err(f"Failed to remove script: {e}")
        return _ok(path=target)

    if action == "read":
        name = p.get("name", "")
        invalid = _validate_script_name(name)
        if invalid:
            return invalid
        category = p.get("category")
        if not category:
            return _err("read requires a 'category'.")
        language = p.get("language", "lua")
        invalid = _validate_script_language(language)
        if invalid:
            return invalid
        try:
            target = _script_path(name, category, language)
        except ValueError as e:
            return _err(str(e))
        if not os.path.isfile(target):
            return _err(f"No script named '{name}{_SCRIPT_LANG_EXT[language]}' at {target}")
        try:
            with open(target, "r", encoding="utf-8") as f:
                return {"source": f.read(), "path": target,
                        "language": language, "category": category}
        except OSError as e:
            return _err(f"Failed to read script: {e}")

    if action == "validate":
        source = p.get("source")
        if not isinstance(source, str):
            return _err("validate requires a 'source' string.")
        language = p.get("language", "lua")
        invalid = _validate_script_language(language)
        if invalid:
            return invalid
        return _validate_script_source(source, language)

    if action == "template":
        kind = p.get("kind", "")
        name = p.get("name", "")
        invalid = _validate_script_name(name)
        if invalid:
            return invalid
        gen = script_templates.TEMPLATES.get(kind)
        if gen is None:
            return _err(f"Unknown template kind '{kind}'. Valid: "
                        f"{sorted(script_templates.TEMPLATES.keys())}")
        opts = p.get("options") or {}
        language = opts.get("language", "lua")
        invalid = _validate_script_language(language)
        if invalid:
            return invalid
        try:
            source = gen(name, opts)
        except (ValueError, KeyError, TypeError) as e:
            return _err(f"Template generation failed: {e}")
        return {"source": source, "kind": kind, "name": name,
                "language": language}

    if action == "execute":
        name = p.get("name", "")
        invalid = _validate_script_name(name)
        if invalid:
            return invalid
        category = p.get("category")
        if not category:
            return _err("execute requires a 'category'.")
        language = p.get("language", "lua")
        invalid = _validate_script_language(language)
        if invalid:
            return invalid
        timeout = int(p.get("timeout", 120))
        try:
            target = _script_path(name, category, language)
        except ValueError as e:
            return _err(str(e))
        if not os.path.isfile(target):
            return _err(f"No script named '{name}{_SCRIPT_LANG_EXT[language]}' "
                        f"at {target}")
        if language == "py":
            args = p.get("args", [])
            if not isinstance(args, list):
                return _err("'args' must be a list of strings.")
            return _execute_python_script(target, args, timeout)
        return _execute_lua_script(target)

    if action == "run_inline":
        source = p.get("source")
        if not isinstance(source, str) or not source.strip():
            return _err("run_inline requires a non-empty 'source' string.")
        language = p.get("language", "lua")
        invalid = _validate_script_language(language)
        if invalid:
            return invalid
        timeout = int(p.get("timeout", 60))
        if language == "py":
            return _run_inline_python(source, timeout)
        return _run_inline_lua(source)

    return _unknown(action, ["path", "categories", "list", "install", "remove",
                             "read", "validate", "template", "list_templates",
                             "execute", "run_inline"])


# ═══════════════════════════════════════════════════════════════════════════════
# Server Startup
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Support --full flag to run the 328-tool granular server instead
    if "--full" in sys.argv:
        logger.info("Starting full 328-tool granular server...")
        sys.argv = [arg for arg in sys.argv if arg != "--full"]
        from src.granular import mcp as granular_mcp

        run_fastmcp_stdio(granular_mcp)
        sys.exit(0)

    logger.info(f"Starting DaVinci Resolve MCP Server (30 compound tools)")
    run_fastmcp_stdio(mcp)
