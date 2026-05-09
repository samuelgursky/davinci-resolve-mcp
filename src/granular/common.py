"""Shared bootstrap and helpers for the granular Resolve MCP server."""

import logging
import os
import platform
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Union

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(CURRENT_DIR)
PROJECT_DIR = os.path.dirname(SRC_DIR)

for path in (SRC_DIR, PROJECT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from mcp.server.fastmcp import FastMCP

from src.utils.app_control import (
    get_app_state,
    open_preferences,
    open_project_settings,
    quit_resolve_app,
    restart_resolve_app,
)
from src.utils.cdl import normalize_cdl_payload
from src.utils.cloud_operations import (
    create_cloud_project,
    import_cloud_project,
    load_cloud_project,
    restore_cloud_project,
)
from src.utils.layout_presets import (
    delete_layout_preset,
    export_layout_preset,
    import_layout_preset,
    list_layout_presets,
    load_layout_preset,
    save_layout_preset,
)
from src.utils.object_inspection import inspect_object, print_object_help
from src.utils.platform import get_platform, get_resolve_paths
from src.utils.project_properties import (
    get_all_project_properties,
    get_color_settings,
    get_project_info,
    get_project_metadata,
    get_project_property,
    get_superscale_settings,
    get_timeline_format_settings,
    set_color_science_mode,
    set_color_space,
    set_project_property,
    set_superscale_settings,
    set_timeline_format,
)

paths = get_resolve_paths()
RESOLVE_API_PATH = os.environ.get("RESOLVE_SCRIPT_API") or paths["api_path"]
RESOLVE_LIB_PATH = os.environ.get("RESOLVE_SCRIPT_LIB") or paths["lib_path"]
RESOLVE_MODULES_PATH = (
    os.path.join(RESOLVE_API_PATH, "Modules") if RESOLVE_API_PATH else paths["modules_path"]
)

if RESOLVE_API_PATH:
    os.environ["RESOLVE_SCRIPT_API"] = RESOLVE_API_PATH
if RESOLVE_LIB_PATH:
    os.environ["RESOLVE_SCRIPT_LIB"] = RESOLVE_LIB_PATH
if RESOLVE_MODULES_PATH and RESOLVE_MODULES_PATH not in sys.path:
    sys.path.append(RESOLVE_MODULES_PATH)

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

VERSION = "2.8.0"
logger = logging.getLogger("davinci-resolve-mcp")
logger.info(f"Starting DaVinci Resolve MCP Server v{VERSION}")
logger.info(f"Detected platform: {get_platform()}")
logger.info(f"Using Resolve API path: {RESOLVE_API_PATH}")
logger.info(f"Using Resolve library path: {RESOLVE_LIB_PATH}")

mcp = FastMCP("DaVinciResolveMCP")

resolve = None
dvr_script = None

try:
    import DaVinciResolveScript as dvr_script  # type: ignore

    resolve = dvr_script.scriptapp("Resolve")
    if resolve:
        logger.info(
            f"Connected to DaVinci Resolve: {resolve.GetProductName()} {resolve.GetVersionString()}"
        )
    else:
        logger.error("Failed to get Resolve object. Is DaVinci Resolve running?")
except ImportError as exc:
    logger.error(f"Failed to import DaVinciResolveScript: {exc}")
    logger.error("Check that DaVinci Resolve is installed and running.")
    logger.error(f"RESOLVE_SCRIPT_API: {RESOLVE_API_PATH}")
    logger.error(f"RESOLVE_SCRIPT_LIB: {RESOLVE_LIB_PATH}")
    logger.error(f"RESOLVE_MODULES_PATH: {RESOLVE_MODULES_PATH}")
    logger.error(f"sys.path: {sys.path}")
    resolve = None
except Exception as exc:
    logger.error(f"Unexpected error initializing Resolve: {exc}")
    resolve = None


def _normalize_cdl(cdl):
    """Normalize CDL payloads to the string format Resolve's SetCDL expects."""
    return normalize_cdl_payload(cdl)


class ResolveProxy:
    """Late-bound proxy for modules that pass the shared Resolve object around."""

    def _target(self):
        return get_resolve()

    def __bool__(self):
        return self._target() is not None

    def __getattr__(self, name):
        target = self._target()
        if target is None:
            raise AttributeError("DaVinci Resolve is not connected")
        return getattr(target, name)


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
        try:
            _is_sandbox = os.path.commonpath([os.path.abspath(path), os.path.abspath(system_temp)]) == os.path.abspath(system_temp)
        except ValueError:
            _is_sandbox = False
    if _is_sandbox:
        return os.path.join(os.path.expanduser("~"), "Documents", "resolve-stills")
    return path

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
            return False
        subprocess.Popen(["open", app_path])
    elif sys_name == "windows":
        app_path = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
        if not os.path.exists(app_path):
            return False
        subprocess.Popen([app_path])
    elif sys_name == "linux":
        app_path = "/opt/resolve/bin/resolve"
        if not os.path.exists(app_path):
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
    if _try_connect():
        return resolve
    logger.info("Resolve not running, attempting to launch automatically...")
    _launch_resolve()
    return resolve

def get_project_manager():
    """Get ProjectManager with lazy connection and null guard."""
    r = get_resolve()
    if not r:
        return None
    pm = r.GetProjectManager()
    return pm

def get_current_project():
    """Get current project with lazy connection and null guards."""
    pm = get_project_manager()
    if not pm:
        return None, None
    proj = pm.GetCurrentProject()
    return pm, proj

def get_all_media_pool_clips(media_pool):
    """Get all clips from media pool recursively including subfolders."""
    clips = []
    root_folder = media_pool.GetRootFolder()
    
    def process_folder(folder):
        folder_clips = folder.GetClipList()
        if folder_clips:
            clips.extend(folder_clips)
        
        sub_folders = folder.GetSubFolderList()
        for sub_folder in sub_folders:
            process_folder(sub_folder)
    
    process_folder(root_folder)
    return clips

def get_all_media_pool_folders(media_pool):
    """Get all folders from media pool recursively."""
    folders = []
    root_folder = media_pool.GetRootFolder()
    
    def process_folder(folder):
        folders.append(folder)
        
        sub_folders = folder.GetSubFolderList()
        for sub_folder in sub_folders:
            process_folder(sub_folder)
    
    process_folder(root_folder)
    return folders

def _get_mp():
    resolve = get_resolve()
    if resolve is None:
        return None, None, {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return None, None, {"error": "No project currently open"}
    mp = project.GetMediaPool()
    if not mp:
        return project, None, {"error": "Failed to get MediaPool"}
    return project, mp, None

def _find_clip_by_id(folder, target_id):
    for clip in (folder.GetClipList() or []):
        if clip.GetUniqueId() == target_id:
            return clip
    for sub in (folder.GetSubFolderList() or []):
        found = _find_clip_by_id(sub, target_id)
        if found:
            return found
    return None

_SUBTITLE_LANGUAGE_SUFFIXES = {
    "auto": "AUTO",
    "danish": "DANISH",
    "dutch": "DUTCH",
    "english": "ENGLISH",
    "french": "FRENCH",
    "german": "GERMAN",
    "italian": "ITALIAN",
    "japanese": "JAPANESE",
    "korean": "KOREAN",
    "mandarin_simplified": "MANDARIN_SIMPLIFIED",
    "mandarin-simplified": "MANDARIN_SIMPLIFIED",
    "mandarin_traditional": "MANDARIN_TRADITIONAL",
    "mandarin-traditional": "MANDARIN_TRADITIONAL",
    "norwegian": "NORWEGIAN",
    "portuguese": "PORTUGUESE",
    "russian": "RUSSIAN",
    "spanish": "SPANISH",
    "swedish": "SWEDISH",
}

_SUBTITLE_PRESET_SUFFIXES = {
    "default": "SUBTITLE_DEFAULT",
    "subtitle_default": "SUBTITLE_DEFAULT",
    "subtitle-default": "SUBTITLE_DEFAULT",
    "teletext": "TELETEXT",
    "netflix": "NETFLIX",
}

_SUBTITLE_LINE_BREAK_SUFFIXES = {
    "single": "LINE_SINGLE",
    "double": "LINE_DOUBLE",
}


def _build_subtitle_settings(resolve_obj, language=None, preset=None,
                             chars_per_line=None, line_break=None, gap=None):
    """Build the autoCaptionSettings dict for Timeline.CreateSubtitlesFromAudio.

    Maps user-friendly strings to resolve.AUTO_CAPTION_* constants per docs
    lines 720-761. Returns (settings_dict, None) or (None, error_dict).
    """
    settings = {}
    if language is not None:
        suffix = _SUBTITLE_LANGUAGE_SUFFIXES.get(str(language).strip().lower())
        if not suffix:
            valid = sorted(set(_SUBTITLE_LANGUAGE_SUFFIXES.keys()))
            return None, {"error": f"Unknown language '{language}'. Valid: {valid}"}
        settings[resolve_obj.SUBTITLE_LANGUAGE] = getattr(resolve_obj, f"AUTO_CAPTION_{suffix}")
    if preset is not None:
        suffix = _SUBTITLE_PRESET_SUFFIXES.get(str(preset).strip().lower())
        if not suffix:
            valid = sorted(set(_SUBTITLE_PRESET_SUFFIXES.keys()))
            return None, {"error": f"Unknown preset '{preset}'. Valid: {valid}"}
        settings[resolve_obj.SUBTITLE_CAPTION_PRESET] = getattr(resolve_obj, f"AUTO_CAPTION_{suffix}")
    if chars_per_line is not None:
        if not isinstance(chars_per_line, int) or not (1 <= chars_per_line <= 60):
            return None, {"error": "chars_per_line must be an integer between 1 and 60"}
        settings[resolve_obj.SUBTITLE_CHARS_PER_LINE] = chars_per_line
    if line_break is not None:
        suffix = _SUBTITLE_LINE_BREAK_SUFFIXES.get(str(line_break).strip().lower())
        if not suffix:
            valid = sorted(set(_SUBTITLE_LINE_BREAK_SUFFIXES.keys()))
            return None, {"error": f"Unknown line_break '{line_break}'. Valid: {valid}"}
        settings[resolve_obj.SUBTITLE_LINE_BREAK] = getattr(resolve_obj, f"AUTO_CAPTION_{suffix}")
    if gap is not None:
        if not isinstance(gap, int) or not (0 <= gap <= 10):
            return None, {"error": "gap must be an integer between 0 and 10"}
        settings[resolve_obj.SUBTITLE_GAP] = gap
    return settings, None


def _build_append_clip_info_dict(root, ci, index):
    """Build one MediaPool.AppendToTimeline clipInfo map (6 keys per docs line 221).

    Required: clip_id (or media_pool_item_id), start_frame, end_frame,
    record_frame, track_index. Optional: media_type (1=video only, 2=audio only).
    """
    if not isinstance(ci, dict):
        return None, {"error": f"clip_infos[{index}] must be an object"}
    cid = ci.get("clip_id") or ci.get("media_pool_item_id")
    if not cid:
        return None, {"error": f"clip_infos[{index}] requires clip_id or media_pool_item_id"}
    mp_item = _find_clip_by_id(root, cid)
    if not mp_item:
        return None, {"error": f"clip_infos[{index}]: media pool clip not found: {cid}"}
    sf = ci.get("startFrame", ci.get("start_frame"))
    ef = ci.get("endFrame", ci.get("end_frame"))
    if sf is None or ef is None:
        return None, {"error": f"clip_infos[{index}] requires start_frame/startFrame and end_frame/endFrame"}
    rf = ci.get("recordFrame", ci.get("record_frame"))
    if rf is None:
        return None, {"error": f"clip_infos[{index}] requires record_frame/recordFrame"}
    ti = ci.get("trackIndex", ci.get("track_index"))
    if ti is None:
        return None, {"error": f"clip_infos[{index}] requires track_index/trackIndex"}
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


_AUDIO_SYNC_MODE_SUFFIXES = {
    "waveform": "WAVEFORM",
    "timecode": "TIMECODE",
}

_AUDIO_SYNC_CHANNEL_SPECIAL = {
    "automatic": "CHANNEL_AUTOMATIC",
    "auto": "CHANNEL_AUTOMATIC",
    "mix": "CHANNEL_MIX",
}


def _build_audio_sync_settings(resolve_obj, sync_mode=None, channel_number=None,
                               retain_embedded_audio=None, retain_video_metadata=None):
    """Build the {audioSyncSettings} dict for MediaPool.AutoSyncAudio per docs lines 600-614.

    Returns (settings_dict, None) on success or (None, error_dict) on validation failure.
    """
    settings: Dict[Any, Any] = {}
    if sync_mode is not None:
        suffix = _AUDIO_SYNC_MODE_SUFFIXES.get(str(sync_mode).strip().lower())
        if not suffix:
            valid = sorted(_AUDIO_SYNC_MODE_SUFFIXES.keys())
            return None, {"error": f"Unknown sync_mode '{sync_mode}'. Valid: {valid}"}
        settings[resolve_obj.AUDIO_SYNC_MODE] = getattr(resolve_obj, f"AUDIO_SYNC_{suffix}")
    if channel_number is not None:
        if isinstance(channel_number, str):
            special = _AUDIO_SYNC_CHANNEL_SPECIAL.get(channel_number.strip().lower())
            if not special:
                return None, {"error": f"Unknown channel_number '{channel_number}'. Use an int >= 1 or 'automatic'/'mix'."}
            settings[resolve_obj.AUDIO_SYNC_CHANNEL_NUMBER] = getattr(resolve_obj, f"AUDIO_SYNC_{special}")
        elif isinstance(channel_number, int):
            settings[resolve_obj.AUDIO_SYNC_CHANNEL_NUMBER] = channel_number
        else:
            return None, {"error": f"channel_number must be int >= 1 or 'automatic'/'mix', got {type(channel_number).__name__}"}
    if retain_embedded_audio is not None:
        settings[resolve_obj.AUDIO_SYNC_RETAIN_EMBEDDED_AUDIO] = bool(retain_embedded_audio)
    if retain_video_metadata is not None:
        settings[resolve_obj.AUDIO_SYNC_RETAIN_VIDEO_METADATA] = bool(retain_video_metadata)
    return settings, None


def _build_create_clip_info_dict(root, ci, index):
    """Build one MediaPool.CreateTimelineFromClips clipInfo map.

    See docs/resolve_scripting_api.txt line 224: 4 keys — mediaPoolItem,
    startFrame, endFrame, recordFrame.
    """
    if not isinstance(ci, dict):
        return None, {"error": f"clip_infos[{index}] must be an object"}
    cid = ci.get("clip_id") or ci.get("media_pool_item_id")
    if not cid:
        return None, {"error": f"clip_infos[{index}] requires clip_id or media_pool_item_id"}
    mp_item = _find_clip_by_id(root, cid)
    if not mp_item:
        return None, {"error": f"clip_infos[{index}]: media pool clip not found: {cid}"}
    sf = ci.get("startFrame", ci.get("start_frame"))
    ef = ci.get("endFrame", ci.get("end_frame"))
    if sf is None or ef is None:
        return None, {"error": f"clip_infos[{index}] requires start_frame/startFrame and end_frame/endFrame"}
    rf = ci.get("recordFrame", ci.get("record_frame"))
    if rf is None:
        return None, {"error": f"clip_infos[{index}] requires record_frame/recordFrame"}
    return {
        "mediaPoolItem": mp_item,
        "startFrame": sf,
        "endFrame": ef,
        "recordFrame": rf,
    }, None


def _find_clips_by_ids(folder, ids_set):
    found = []
    for clip in (folder.GetClipList() or []):
        if clip.GetUniqueId() in ids_set:
            found.append(clip)
    for sub in (folder.GetSubFolderList() or []):
        found.extend(_find_clips_by_ids(sub, ids_set))
    return found

def _navigate_to_folder(mp, folder_path):
    root = mp.GetRootFolder()
    if not folder_path or folder_path in ("Master", "/", ""):
        return root
    parts = folder_path.strip("/").split("/")
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

def _get_timeline():
    resolve = get_resolve()
    if resolve is None:
        return None, None, {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return None, None, {"error": "No project currently open"}
    tl = project.GetCurrentTimeline()
    if not tl:
        return project, None, {"error": "No current timeline"}
    return project, tl, None

def _get_timeline_item(track_type="video", track_index=1, item_index=0):
    _, tl, err = _get_timeline()
    if err:
        return None, err
    items = tl.GetItemListInTrack(track_type, track_index)
    if not items or item_index >= len(items):
        return None, {"error": f"No item at index {item_index} on {track_type} track {track_index}"}
    return items[item_index], None

def _has_method(obj, method_name):
    return callable(getattr(obj, method_name, None))

def _requires_method(obj, method_name, min_version):
    if _has_method(obj, method_name):
        return None
    return {"error": f"{method_name} requires DaVinci Resolve {min_version}+"}

__all__ = [name for name in globals() if not name.startswith("__")]
