#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server (Compound Tools)

27 compound tools covering 100% of the DaVinci Resolve Scripting API (336 methods).
Each tool groups related operations via an 'action' parameter.

Usage:
    python src/server.py              # Start the MCP server
    python src/server.py --full       # Start the 336-tool granular server instead
"""

VERSION = "2.3.2"

import base64
import os
import sys
import json
import logging
import platform
import subprocess
import tempfile
import time
from typing import Dict, Any, Optional, List

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
from src.utils.platform import get_resolve_paths

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
        f"recreate the venv with Python 3.10–3.12."
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


def _serialize_appended_timeline_item(item, index: int):
    if not item:
        return None, _err(f"Failed to append clip_infos to timeline: missing timeline item at index {index}")
    try:
        item_id = item.GetUniqueId()
        name = item.GetName()
    except Exception as exc:
        logger.warning(f"Invalid timeline item returned for clip_infos[{index}]: {exc}")
        return None, _err(f"Failed to append clip_infos to timeline: invalid timeline item at index {index}")
    if not item_id:
        return None, _err(f"Failed to append clip_infos to timeline: missing timeline item id at index {index}")
    return {"timeline_item_id": item_id, "name": name}, None


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
    return _unknown(action, ["add_job","delete_job","delete_all_jobs","list_jobs","get_job_status","start","stop","is_rendering","get_formats","get_codecs","get_format_and_codec","set_format_and_codec","get_mode","set_mode","get_resolutions","get_settings","set_settings","list_presets","load_preset","save_preset","delete_preset","quick_export_presets","quick_export"])


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
    return _unknown(action, ["get_root_folder","get_current_folder","set_current_folder","add_subfolder","delete_folders","move_folders","refresh","create_timeline","create_timeline_from_clips","import_timeline","delete_timelines","append_to_timeline","import_media","delete_clips","move_clips","relink","unlink","export_metadata","get_unique_id","create_stereo_clip","auto_sync_audio","get_selected","set_selected","get_clip_mattes","get_timeline_mattes","delete_clip_mattes","import_folder"])


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
      add(clip_id, frame, color, name, note, duration, custom_data?) -> {success}
      get_all(clip_id) -> {markers}
      get_by_custom_data(clip_id, custom_data) -> {markers}
      update_custom_data(clip_id, frame, custom_data) -> {success}
      get_custom_data(clip_id, frame) -> {data}
      delete_by_color(clip_id, color) -> {success}
      delete_at_frame(clip_id, frame) -> {success}
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
        return {"success": bool(clip.AddMarker(p["frame"], p["color"], p["name"], p["note"], p["duration"], p.get("custom_data", "")))}
    elif action == "get_all":
        return {"markers": _ser(clip.GetMarkers())}
    elif action == "get_by_custom_data":
        return {"markers": _ser(clip.GetMarkerByCustomData(p["custom_data"]))}
    elif action == "update_custom_data":
        return {"success": bool(clip.UpdateMarkerCustomData(p["frame"], p["custom_data"]))}
    elif action == "get_custom_data":
        return {"data": clip.GetMarkerCustomData(p["frame"])}
    elif action == "delete_by_color":
        return {"success": bool(clip.DeleteMarkersByColor(p["color"]))}
    elif action == "delete_at_frame":
        return {"success": bool(clip.DeleteMarkerAtFrame(p["frame"]))}
    elif action == "delete_by_custom_data":
        return {"success": bool(clip.DeleteMarkerByCustomData(p["custom_data"]))}
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
        return {"items": _ser(tl.GetItemsInTrack(p["track_type"], p["track_index"]))}
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
    return _unknown(action, ["list","get_current","set_current","get_name","set_name","get_start_frame","get_end_frame","get_start_timecode","set_start_timecode","get_track_count","add_track","delete_track","get_track_sub_type","set_track_enable","get_track_enabled","set_track_lock","get_track_locked","get_track_name","set_track_name","get_items","delete_clips","set_clips_linked","duplicate","create_compound_clip","create_fusion_clip","import_into_timeline","export","get_setting","set_setting","insert_generator","insert_fusion_generator","insert_fusion_composition","insert_ofx_generator","insert_title","insert_fusion_title","get_unique_id","get_node_graph","get_media_pool_item","get_mark_in_out","set_mark_in_out","clear_mark_in_out","convert_to_stereo","get_items_in_track","get_voice_isolation_state","set_voice_isolation_state"])


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL 16: timeline_markers
# ═══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def timeline_markers(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Markers and playhead operations on the current timeline.

    Actions:
      add(frame, color, name, note, duration, custom_data?) -> {success}
      get_all() -> {markers}
      get_by_custom_data(custom_data) -> {markers}
      update_custom_data(frame, custom_data) -> {success}
      get_custom_data(frame) -> {data}
      delete_by_color(color) -> {success}
      delete_at_frame(frame) -> {success}
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
        return {"success": bool(tl.AddMarker(p["frame"], p["color"], p["name"], p["note"], p["duration"], p.get("custom_data", "")))}
    elif action == "get_all":
        return {"markers": _ser(tl.GetMarkers())}
    elif action == "get_by_custom_data":
        return {"markers": _ser(tl.GetMarkerByCustomData(p["custom_data"]))}
    elif action == "update_custom_data":
        return {"success": bool(tl.UpdateMarkerCustomData(p["frame"], p["custom_data"]))}
    elif action == "get_custom_data":
        return {"data": tl.GetMarkerCustomData(p["frame"])}
    elif action == "delete_by_color":
        return {"success": bool(tl.DeleteMarkersByColor(p["color"]))}
    elif action == "delete_at_frame":
        return {"success": bool(tl.DeleteMarkerAtFrame(p["frame"]))}
    elif action == "delete_by_custom_data":
        return {"success": bool(tl.DeleteMarkerByCustomData(p["custom_data"]))}
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
      add(frame, color, name, note, duration, custom_data?, ...) -> {success}
      get_all(...) -> {markers}
      get_by_custom_data(custom_data, ...) -> {markers}
      update_custom_data(frame, custom_data, ...) -> {success}
      get_custom_data(frame, ...) -> {data}
      delete_by_color(color, ...) -> {success}
      delete_at_frame(frame, ...) -> {success}
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
        return {"success": bool(item.AddMarker(p["frame"], p["color"], p["name"], p["note"], p["duration"], p.get("custom_data", "")))}
    elif action == "get_all":
        return {"markers": _ser(item.GetMarkers())}
    elif action == "get_by_custom_data":
        return {"markers": _ser(item.GetMarkerByCustomData(p["custom_data"]))}
    elif action == "update_custom_data":
        return {"success": bool(item.UpdateMarkerCustomData(p["frame"], p["custom_data"]))}
    elif action == "get_custom_data":
        return {"data": item.GetMarkerCustomData(p["frame"])}
    elif action == "delete_by_color":
        return {"success": bool(item.DeleteMarkersByColor(p["color"]))}
    elif action == "delete_at_frame":
        return {"success": bool(item.DeleteMarkerAtFrame(p["frame"]))}
    elif action == "delete_by_custom_data":
        return {"success": bool(item.DeleteMarkerByCustomData(p["custom_data"]))}
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
# Server Startup
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Support --full flag to run the 336-tool granular server instead
    if "--full" in sys.argv:
        logger.info("Starting full 336-tool granular server...")
        sys.argv = [arg for arg in sys.argv if arg != "--full"]
        from src.granular import mcp as granular_mcp

        run_fastmcp_stdio(granular_mcp)
        sys.exit(0)

    logger.info(f"Starting DaVinci Resolve MCP Server (27 compound tools)")
    run_fastmcp_stdio(mcp)
