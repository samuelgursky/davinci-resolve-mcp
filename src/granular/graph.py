"""Color page graph, LUT, and color-group tools."""

from src.granular.common import *  # noqa: F401,F403

resolve = ResolveProxy()

@mcp.resource("resolve://color/current-node")
def get_current_color_node() -> Dict[str, Any]:
    """Get information about the current node in the color page."""
    from api.color_operations import get_current_node as get_node_func
    return get_node_func(resolve)


@mcp.resource("resolve://color/wheels/{node_index}")
def get_color_wheel_params(node_index: int = None) -> Dict[str, Any]:
    """Get color wheel parameters for a specific node.
    
    Args:
        node_index: Index of the node to get color wheels from (uses current node if None)
    """
    from api.color_operations import get_color_wheels as get_wheels_func
    return get_wheels_func(resolve, node_index)


@mcp.tool()
def apply_lut(lut_path: str, node_index: int = None) -> str:
    """Apply a LUT to a node in the color page.
    
    Args:
        lut_path: Path to the LUT file to apply
        node_index: Index of the node to apply the LUT to (uses current node if None)
    """
    from api.color_operations import apply_lut as apply_lut_func
    return apply_lut_func(resolve, lut_path, node_index)


@mcp.tool()
def set_color_wheel_param(wheel: str, param: str, value: float, node_index: int = None) -> str:
    """Set a color wheel parameter for a node.
    
    Args:
        wheel: Which color wheel to adjust ('lift', 'gamma', 'gain', 'offset')
        param: Which parameter to adjust ('red', 'green', 'blue', 'master')
        value: The value to set (typically between -1.0 and 1.0)
        node_index: Index of the node to set parameter for (uses current node if None)
    """
    from api.color_operations import set_color_wheel_param as set_param_func
    return set_param_func(resolve, wheel, param, value, node_index)


@mcp.tool()
def add_node(node_type: str = "serial", label: str = None) -> str:
    """Add a new node to the current grade in the color page.
    
    Args:
        node_type: Type of node to add. Options: 'serial', 'parallel', 'layer'
        label: Optional label/name for the new node
    """
    from api.color_operations import add_node as add_node_func
    return add_node_func(resolve, node_type, label)


@mcp.tool()
def copy_grade(source_clip_name: str = None, target_clip_name: str = None, mode: str = "full") -> str:
    """Copy a grade from one clip to another in the color page.
    
    Args:
        source_clip_name: Name of the source clip to copy grade from (uses current clip if None)
        target_clip_name: Name of the target clip to apply grade to (uses current clip if None)
        mode: What to copy - 'full' (entire grade), 'current_node', or 'all_nodes'
    """
    from api.color_operations import copy_grade as copy_grade_func
    return copy_grade_func(resolve, source_clip_name, target_clip_name, mode)


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
