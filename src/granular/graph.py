"""Color page graph, LUT, and color-group tools."""

from src.granular.common import *  # noqa: F401,F403
from src.utils.lut_paths import ensure_lut_in_master
from src.utils import lut_files

resolve = ResolveProxy()

@mcp.tool()
def graph_get_num_nodes(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get number of nodes in the color graph for a timeline item.

    Args:
        item_index: 0-based item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    return {"num_nodes": graph.GetNumNodes()}


@mcp.tool()
def graph_set_lut(node_index: int, lut_path: str, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Set LUT on a node in the color graph.

    Args:
        node_index: 1-based node index.
        lut_path: Absolute or relative LUT path.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    ok = bool(graph.SetLUT(node_index, lut_path))
    if not ok:
        # SetLUT resolves LUTs only against the master LUT dir, not the per-user
        # dir dctl installs to. Relocate into the master dir and retry.
        relocated = ensure_lut_in_master(lut_path)
        if relocated:
            try:
                project = resolve.GetProjectManager().GetCurrentProject()
                if project:
                    project.RefreshLUTList()
            except Exception:
                pass
            ok = bool(graph.SetLUT(node_index, relocated))
            if ok:
                return {"success": True, "resolved_lut": relocated,
                        "note": "LUT staged under the master LUT dir "
                                "(MCP/ subfolder) and applied; SetLUT does "
                                "not resolve the user LUT dir."}
    return {"success": ok}


@mcp.tool()
def graph_get_lut(node_index: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get LUT path on a node in the color graph.

    Args:
        node_index: 1-based node index.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    lut = graph.GetLUT(node_index)
    return {"node_index": node_index, "lut_path": lut if lut else ""}


@mcp.tool()
def graph_set_node_cache_mode(node_index: int, cache_value: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Set the cache mode on a node.

    Args:
        node_index: 1-based node index.
        cache_value: -1=Auto, 0=Disabled, 1=Enabled.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    result = graph.SetNodeCacheMode(node_index, cache_value)
    return {"success": bool(result)}


@mcp.tool()
def graph_get_node_cache_mode(node_index: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get the cache mode of a node.

    Args:
        node_index: 1-based node index.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    mode = graph.GetNodeCacheMode(node_index)
    modes = {-1: "Auto", 0: "Disabled", 1: "Enabled"}
    return {"node_index": node_index, "cache_mode": mode, "mode_name": modes.get(mode, "Unknown")}


@mcp.tool()
def graph_get_node_label(node_index: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get the label of a node.

    Args:
        node_index: 1-based node index.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    label = graph.GetNodeLabel(node_index)
    return {"node_index": node_index, "label": label if label else ""}


@mcp.tool()
def graph_get_tools_in_node(node_index: int, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Get list of tools used in a node.

    Args:
        node_index: 1-based node index.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    tools = graph.GetToolsInNode(node_index)
    return {"node_index": node_index, "tools": tools if tools else []}


@mcp.tool()
def graph_set_node_enabled(node_index: int, is_enabled: bool, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Enable or disable a node.

    Args:
        node_index: 1-based node index.
        is_enabled: True to enable, False to disable.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    result = graph.SetNodeEnabled(node_index, is_enabled)
    return {"success": bool(result)}


@mcp.tool()
def graph_apply_grade_from_drx(drx_path: str, grade_mode: int = 0, item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Apply a grade from a .drx file to a timeline item's graph.

    Args:
        drx_path: Absolute path to the .drx file.
        grade_mode: 0=No keyframes, 1=Source Timecode aligned, 2=Start Frames aligned.
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    result = graph.ApplyGradeFromDRX(drx_path, grade_mode)
    return {"success": bool(result)}


@mcp.tool()
def graph_apply_arri_cdl_lut(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Apply ARRI CDL and LUT to a timeline item's graph.

    Args:
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    result = graph.ApplyArriCdlLut()
    return {"success": bool(result)}


@mcp.tool()
def graph_reset_all_grades(item_index: int = 0, track_type: str = "video", track_index: int = 1) -> Dict[str, Any]:
    """Reset all grades on a timeline item's graph.

    Args:
        item_index: 0-based timeline item index. Default: 0.
        track_type: 'video' or 'audio'. Default: 'video'.
        track_index: 1-based track index. Default: 1.
    """
    item, err = _get_timeline_item(track_type, track_index, item_index)
    if err:
        return err
    graph = item.GetNodeGraph()
    if not graph:
        return {"error": "No node graph available"}
    result = graph.ResetAllGrades()
    return {"success": bool(result)}


@mcp.tool()
def get_color_group_clips(group_name: str) -> Dict[str, Any]:
    """Get clips in a color group for the current timeline.

    Args:
        group_name: Name of the color group.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    groups = project.GetColorGroupsList()
    target = None
    if groups:
        for g in groups:
            if g.GetName() == group_name:
                target = g
                break
    if not target:
        return {"error": f"Color group '{group_name}' not found"}
    clips = target.GetClipsInTimeline()
    if clips:
        return {"group": group_name, "clips": [{"name": c.GetName()} for c in clips]}
    return {"group": group_name, "clips": []}


@mcp.tool()
def get_color_group_pre_clip_node_graph(group_name: str) -> Dict[str, Any]:
    """Get the pre-clip node graph for a color group.

    Args:
        group_name: Name of the color group.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    groups = project.GetColorGroupsList()
    target = None
    if groups:
        for g in groups:
            if g.GetName() == group_name:
                target = g
                break
    if not target:
        return {"error": f"Color group '{group_name}' not found"}
    graph = target.GetPreClipNodeGraph()
    if graph:
        return {"group": group_name, "graph_type": "pre_clip", "num_nodes": graph.GetNumNodes()}
    return {"error": "No pre-clip node graph available"}


@mcp.tool()
def get_color_group_post_clip_node_graph(group_name: str) -> Dict[str, Any]:
    """Get the post-clip node graph for a color group.

    Args:
        group_name: Name of the color group.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    groups = project.GetColorGroupsList()
    target = None
    if groups:
        for g in groups:
            if g.GetName() == group_name:
                target = g
                break
    if not target:
        return {"error": f"Color group '{group_name}' not found"}
    graph = target.GetPostClipNodeGraph()
    if graph:
        return {"group": group_name, "graph_type": "post_clip", "num_nodes": graph.GetNumNodes()}
    return {"error": "No post-clip node graph available"}


def _lut_error(exc):
    return {"error": str(exc)}


@mcp.tool()
def get_lut_directories() -> Dict[str, Any]:
    """Report Resolve's master LUT directory and the folder this server writes to.

    Installs go to the MASTER root, not the per-user LUT dir the dctl tool
    uses: Graph.SetLUT() resolves LUT names only against the master root.
    """
    return {"lut_dir": lut_files.master_lut_dir(),
            "writable_dir": lut_files.writable_dir()}


@mcp.tool()
def list_lut_files(subdir: Optional[str] = None) -> Dict[str, Any]:
    """List LUT files Resolve can see, with the path graph_set_lut accepts.

    Walks the whole master LUT root so stock, vendor and installed LUTs all
    appear. Each entry reports set_lut_path (master-relative, the form
    Graph.SetLUT resolves) and whether this server may remove it.

    Args:
        subdir: Optional folder under the master LUT root to limit the walk to.
    """
    try:
        return lut_files.list_luts(subdir)
    except lut_files.LutPathError as exc:
        return _lut_error(exc)


@mcp.tool()
def read_lut_file(name: str) -> Dict[str, Any]:
    """Summarize a 3D .cube LUT: size, title, domain. Never the whole table.

    Args:
        name: Master-relative path, e.g. "MCP/warm.cube".
    """
    try:
        return lut_files.read_lut_summary(name)
    except (lut_files.LutPathError, OSError, ValueError) as exc:
        return _lut_error(exc)


@mcp.tool(annotations=EXTERNAL_WRITE_TOOL)
def install_lut_file(name: str, source: Optional[str] = None,
                     source_path: Optional[str] = None,
                     overwrite: bool = False) -> Dict[str, Any]:
    """Install a LUT into the writable MCP folder under the master LUT root.

    Refuses an existing destination unless overwrite is set. Call
    refresh_lut_list() afterwards so Resolve picks the file up.

    Args:
        name: File name, e.g. "warm.cube". Relative only; .cube if no extension.
        source: LUT file text. Provide this or source_path, not both.
        source_path: A LUT file on disk to copy in.
        overwrite: Replace an existing file of the same name.
    """
    try:
        return lut_files.install_lut(name, source=source, source_path=source_path,
                                     overwrite=overwrite)
    except (lut_files.LutPathError, OSError) as exc:
        return _lut_error(exc)


@mcp.tool(annotations=EXTERNAL_WRITE_TOOL)
def remove_lut_file(name: str) -> Dict[str, Any]:
    """Delete a LUT from the writable MCP folder only.

    Stock and vendor LUTs live outside it and are not removable here.

    Args:
        name: File name under MCP/, e.g. "warm.cube".
    """
    try:
        return lut_files.remove_lut(name)
    except (lut_files.LutPathError, OSError) as exc:
        return _lut_error(exc)


@mcp.tool(annotations=EXTERNAL_WRITE_TOOL)
def attenuate_lut_file(source: str, strength: float, name: str) -> Dict[str, Any]:
    """Blend an existing .cube toward identity and install the result.

    Reads from anywhere under the master LUT root, writes only into MCP/.
    Refuses a non-unit DOMAIN_MIN/MAX, because identity is only identity on
    a 0..1 domain.

    Args:
        source: Master-relative path of the LUT to weaken.
        strength: 0.0 (identity) to 1.0 (unchanged).
        name: Output file name under MCP/.
    """
    try:
        return lut_files.attenuate_lut(source, strength, name)
    except (lut_files.LutPathError, OSError, ValueError) as exc:
        return _lut_error(exc)


@mcp.tool()
def get_lut_file_capabilities() -> Dict[str, Any]:
    """What this server can do with LUT files, and what it refuses.

    Notably it will not generate a LUT from caller-supplied Python code.
    """
    from src.utils import cube_lut
    caps = dict(cube_lut.capabilities())
    caps["writable_dir"] = lut_files.writable_dir()
    caps["extensions"] = list(lut_files.LUT_EXTENSIONS)
    caps["generate_from_code"] = False
    caps["generate_from_code_reason"] = (
        "This server does not execute caller-supplied Python. Use "
        "install_lut_file with .cube text, or attenuate_lut_file.")
    return caps
