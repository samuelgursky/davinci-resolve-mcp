"""DaVinci Resolve cloud project helpers.

Mirrors the four documented ProjectManager cloud methods at docs lines 138-145
and the {cloudSettings} dict spec at lines 576-594. Maps user-friendly snake_case
arguments to the resolve.CLOUD_SETTING_* / CLOUD_SYNC_* constants required by
the Resolve scripting API.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("davinci-resolve-mcp.cloud_operations")


_SYNC_MODE_SUFFIXES = {
    "none": "NONE",
    "proxy_only": "PROXY_ONLY",
    "proxy-only": "PROXY_ONLY",
    "proxy_and_orig": "PROXY_AND_ORIG",
    "proxy-and-orig": "PROXY_AND_ORIG",
}


def _build_cloud_settings(
    resolve_obj,
    project_name: Optional[str] = None,
    project_media_path: Optional[str] = None,
    is_collab: Optional[bool] = None,
    sync_mode: Optional[str] = None,
    is_camera_access: Optional[bool] = None,
):
    """Build the {cloudSettings} dict for ProjectManager cloud methods.

    Returns (settings_dict, None) on success or (None, error_dict) on validation
    failure. Per docs lines 576-594, all keys default on the Resolve side; we only
    include keys the caller explicitly set.
    """
    settings: Dict[Any, Any] = {}
    if project_name is not None:
        settings[resolve_obj.CLOUD_SETTING_PROJECT_NAME] = project_name
    if project_media_path is not None:
        settings[resolve_obj.CLOUD_SETTING_PROJECT_MEDIA_PATH] = project_media_path
    if is_collab is not None:
        settings[resolve_obj.CLOUD_SETTING_IS_COLLAB] = bool(is_collab)
    if sync_mode is not None:
        suffix = _SYNC_MODE_SUFFIXES.get(str(sync_mode).strip().lower())
        if not suffix:
            valid = sorted(set(_SYNC_MODE_SUFFIXES.keys()))
            return None, {"error": f"Unknown sync_mode '{sync_mode}'. Valid: {valid}"}
        settings[resolve_obj.CLOUD_SETTING_SYNC_MODE] = getattr(resolve_obj, f"CLOUD_SYNC_{suffix}")
    if is_camera_access is not None:
        settings[resolve_obj.CLOUD_SETTING_IS_CAMERA_ACCESS] = bool(is_camera_access)
    return settings, None


def _project_manager(resolve_obj, method_name: str):
    """Look up the project manager and confirm a Resolve method exists.

    Returns (pm, None) on success or (None, error_dict) on failure.
    """
    if resolve_obj is None:
        return None, {"success": False, "error": "Not connected to DaVinci Resolve"}
    pm = resolve_obj.GetProjectManager()
    if not pm:
        return None, {"success": False, "error": "Failed to get Project Manager"}
    if not hasattr(pm, method_name):
        return None, {
            "success": False,
            "error": f"{method_name} not available in this version of DaVinci Resolve",
        }
    return pm, None


def create_cloud_project(
    resolve_obj,
    project_name: Optional[str] = None,
    project_media_path: Optional[str] = None,
    is_collab: Optional[bool] = None,
    sync_mode: Optional[str] = None,
    is_camera_access: Optional[bool] = None,
) -> Dict[str, Any]:
    """Create a cloud project. Mirrors ProjectManager.CreateCloudProject({cloudSettings})."""
    pm, err = _project_manager(resolve_obj, "CreateCloudProject")
    if err:
        return err
    settings, settings_err = _build_cloud_settings(
        resolve_obj, project_name, project_media_path, is_collab, sync_mode, is_camera_access,
    )
    if settings_err:
        return settings_err
    try:
        project = pm.CreateCloudProject(settings)
    except Exception as exc:
        logger.error(f"CreateCloudProject failed: {exc}")
        return {"success": False, "error": f"CreateCloudProject failed: {exc}"}
    if not project:
        return {"success": False, "error": "Failed to create cloud project"}
    return {
        "success": True,
        "project_name": project.GetName(),
        "project_id": project.GetUniqueId() if hasattr(project, "GetUniqueId") else None,
    }


def load_cloud_project(
    resolve_obj,
    project_name: Optional[str] = None,
    project_media_path: Optional[str] = None,
    sync_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Load a cloud project. Mirrors ProjectManager.LoadCloudProject({cloudSettings}).

    Per docs line 585, only PROJECT_NAME, PROJECT_MEDIA_PATH, and SYNC_MODE are
    honoured; subsequent loads on the same system honour only PROJECT_NAME.
    """
    pm, err = _project_manager(resolve_obj, "LoadCloudProject")
    if err:
        return err
    settings, settings_err = _build_cloud_settings(
        resolve_obj, project_name=project_name,
        project_media_path=project_media_path, sync_mode=sync_mode,
    )
    if settings_err:
        return settings_err
    try:
        project = pm.LoadCloudProject(settings)
    except Exception as exc:
        logger.error(f"LoadCloudProject failed: {exc}")
        return {"success": False, "error": f"LoadCloudProject failed: {exc}"}
    if not project:
        return {"success": False, "error": "No matching cloud project found"}
    return {
        "success": True,
        "project_name": project.GetName(),
        "project_id": project.GetUniqueId() if hasattr(project, "GetUniqueId") else None,
    }


def import_cloud_project(
    resolve_obj,
    file_path: str,
    project_name: Optional[str] = None,
    project_media_path: Optional[str] = None,
    is_collab: Optional[bool] = None,
    sync_mode: Optional[str] = None,
    is_camera_access: Optional[bool] = None,
) -> Dict[str, Any]:
    """Import a cloud project. Mirrors ProjectManager.ImportCloudProject(filePath, {cloudSettings})."""
    pm, err = _project_manager(resolve_obj, "ImportCloudProject")
    if err:
        return err
    if not file_path:
        return {"success": False, "error": "file_path is required"}
    settings, settings_err = _build_cloud_settings(
        resolve_obj, project_name, project_media_path, is_collab, sync_mode, is_camera_access,
    )
    if settings_err:
        return settings_err
    try:
        ok = pm.ImportCloudProject(file_path, settings)
    except Exception as exc:
        logger.error(f"ImportCloudProject failed: {exc}")
        return {"success": False, "error": f"ImportCloudProject failed: {exc}"}
    return {"success": bool(ok)}


def restore_cloud_project(
    resolve_obj,
    folder_path: str,
    project_name: Optional[str] = None,
    project_media_path: Optional[str] = None,
    is_collab: Optional[bool] = None,
    sync_mode: Optional[str] = None,
    is_camera_access: Optional[bool] = None,
) -> Dict[str, Any]:
    """Restore a cloud project. Mirrors ProjectManager.RestoreCloudProject(folderPath, {cloudSettings})."""
    pm, err = _project_manager(resolve_obj, "RestoreCloudProject")
    if err:
        return err
    if not folder_path:
        return {"success": False, "error": "folder_path is required"}
    settings, settings_err = _build_cloud_settings(
        resolve_obj, project_name, project_media_path, is_collab, sync_mode, is_camera_access,
    )
    if settings_err:
        return settings_err
    try:
        ok = pm.RestoreCloudProject(folder_path, settings)
    except Exception as exc:
        logger.error(f"RestoreCloudProject failed: {exc}")
        return {"success": False, "error": f"RestoreCloudProject failed: {exc}"}
    return {"success": bool(ok)}
