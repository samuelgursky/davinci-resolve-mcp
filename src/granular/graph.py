"""Color page graph, LUT, and color-group tools."""

from src.granular.common import *  # noqa: F401,F403

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
    result = graph.SetLUT(node_index, lut_path)
    return {"success": bool(result)}


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
