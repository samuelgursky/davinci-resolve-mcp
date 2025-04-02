#!/usr/bin/env python3
"""
DaVinci Resolve Color Page Operations
"""

import logging
from typing import Dict, Any, List, Optional, Tuple, Union

logger = logging.getLogger("davinci-resolve-mcp.color")


def get_current_node(resolve) -> Dict[str, Any]:
    """Get information about the current node in the color page.

    Args:
        resolve: The DaVinci Resolve instance

    Returns:
        Dictionary with current node information
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}

    # First, ensure we're on the color page
    current_page = resolve.GetCurrentPage()
    if current_page.lower() != "color":
        return {"error": f"Not on Color page. Current page is: {current_page}"}

    # Get the current timeline
    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        return {"error": "No timeline currently active"}

    try:
        # Access color-specific functionality through the timeline
        # First get the current clip in the timeline
        current_clip = current_timeline.GetCurrentVideoItem()
        if not current_clip:
            return {"error": "No clip is currently selected in the timeline"}

        # Get the clip's grade
        current_grade = current_clip.GetCurrentGrade()
        if not current_grade:
            return {"error": "Failed to get current grade"}

        # Get the currently selected node
        current_node_index = current_grade.GetCurrentNode()
        if current_node_index < 1:
            return {"error": "No node is currently selected"}

        # Get node count
        node_count = current_grade.GetNodeCount()

        # Get information about the current node
        node_info = {
            "clip_name": current_clip.GetName(),
            "node_index": current_node_index,
            "node_count": node_count,
            "is_serial": current_grade.IsSerial(current_node_index),
            "is_parallel": current_grade.IsParallel(current_node_index),
            "is_layer": current_grade.IsLayer(current_node_index),
        }

        # Try to get node name
        try:
            node_name = current_grade.GetNodeName(current_node_index)
            node_info["name"] = node_name
        except:
            node_info["name"] = f"Node {current_node_index}"

        # Try to get additional node properties if available
        try:
            # Check for common node properties that might be available
            properties = {}

            # Check if node is enabled
            try:
                properties["enabled"] = current_grade.IsNodeEnabled(current_node_index)
            except:
                pass

            # Get node type if available
            try:
                properties["type"] = current_grade.GetNodeType(current_node_index)
            except:
                pass

            # Add properties if we found any
            if properties:
                node_info["properties"] = properties
        except:
            pass

        return node_info

    except Exception as e:
        return {"error": f"Error getting current node: {str(e)}"}


def apply_lut(resolve, lut_path: str, node_index: int = None) -> str:
    """Apply a LUT to a node in the color page.

    Args:
        resolve: The DaVinci Resolve instance
        lut_path: Path to the LUT file to apply
        node_index: Index of the node to apply the LUT to (uses current node if None)

    Returns:
        String indicating success or failure with detailed error message
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    # Validate LUT path
    if not lut_path:
        return "Error: LUT path cannot be empty"

    import os

    if not os.path.exists(lut_path):
        return f"Error: LUT file '{lut_path}' does not exist"

    # Check file extension for supported LUT types
    valid_extensions = [".cube", ".3dl", ".lut", ".mga"]
    file_extension = os.path.splitext(lut_path)[1].lower()
    if file_extension not in valid_extensions:
        return f"Error: Unsupported LUT file format. Supported formats: {', '.join(valid_extensions)}"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    # First, ensure we're on the color page
    current_page = resolve.GetCurrentPage()
    if current_page.lower() != "color":
        # Try to switch to color page
        result = resolve.OpenPage("color")
        if not result:
            return f"Error: Failed to switch to Color page. Current page is: {current_page}"

    # Get the current timeline
    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        return "Error: No timeline currently active"

    try:
        # Get the current clip in the timeline
        current_clip = current_timeline.GetCurrentVideoItem()
        if not current_clip:
            return "Error: No clip is currently selected in the timeline"

        # Get the clip's grade
        current_grade = current_clip.GetCurrentGrade()
        if not current_grade:
            return "Error: Failed to get current grade"

        # Determine which node to apply the LUT to
        target_node_index = node_index
        if target_node_index is None:
            # Use the currently selected node
            target_node_index = current_grade.GetCurrentNode()
            if target_node_index < 1:
                return "Error: No node is currently selected"
        else:
            # Validate the provided node index
            node_count = current_grade.GetNodeCount()
            if target_node_index < 1 or target_node_index > node_count:
                return f"Error: Invalid node index {target_node_index}. Valid range: 1-{node_count}"

        # Apply the LUT to the node
        result = current_grade.ApplyLUT(target_node_index, lut_path)

        if result:
            # Try to get the node name for a better message
            try:
                node_name = current_grade.GetNodeName(target_node_index)
                return f"Successfully applied LUT '{os.path.basename(lut_path)}' to node '{node_name}' (index {target_node_index})"
            except:
                return f"Successfully applied LUT '{os.path.basename(lut_path)}' to node {target_node_index}"
        else:
            return f"Failed to apply LUT to node {target_node_index}"

    except Exception as e:
        return f"Error applying LUT: {str(e)}"


def add_node(resolve, node_type: str = "serial", label: str = None) -> str:
    """Add a new node to the current grade in the color page.

    Args:
        resolve: The DaVinci Resolve instance
        node_type: Type of node to add. Options: 'serial', 'parallel', 'layer'
        label: Optional label/name for the new node

    Returns:
        String indicating success or failure with detailed error message
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    # Validate node type
    valid_node_types = ["serial", "parallel", "layer"]
    if node_type.lower() not in valid_node_types:
        return (
            f"Error: Invalid node type. Must be one of: {', '.join(valid_node_types)}"
        )

    logger.info(f"Adding {node_type} node with label: {label if label else 'None'}")

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        logger.error("Failed to get Project Manager")
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        logger.error("No project currently open")
        return "Error: No project currently open"

    # First, ensure we're on the color page
    current_page = resolve.GetCurrentPage()
    if current_page.lower() != "color":
        # Try to switch to color page
        logger.info(f"Currently on {current_page} page, switching to color page")
        result = resolve.OpenPage("color")
        if not result:
            logger.error(
                f"Failed to switch to Color page. Current page is: {current_page}"
            )
            return f"Error: Failed to switch to Color page. Current page is: {current_page}"
        logger.info("Successfully switched to color page")

    # Get the current timeline
    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        logger.error("No timeline currently active")
        return "Error: No timeline currently active"

    try:
        # Use the helper function to ensure a clip is selected
        clip_selected, current_clip, message = ensure_clip_selected(
            resolve, current_timeline
        )

        if not clip_selected or not current_clip:
            logger.error("No clip could be selected automatically")
            return (
                f"Error: {message}. Please select a clip manually in DaVinci Resolve."
            )

        logger.info(f"Working with clip: {current_clip.GetName()}")

        # Get the clip's grade
        # This is where the NoneType error typically occurs
        logger.info("Attempting to get current grade")

        # First method: Direct approach
        try:
            current_grade = current_clip.GetCurrentGrade()
            if current_grade:
                logger.info("Successfully got current grade using GetCurrentGrade()")
            else:
                logger.warning("GetCurrentGrade() returned None")
        except Exception as e:
            logger.error(f"Error getting current grade via GetCurrentGrade(): {str(e)}")
            current_grade = None

        # Alternative approach if the first method failed
        if not current_grade:
            logger.info("Attempting alternative methods to access grade functionality")

            # Try to select the clip first to ensure it's active
            try:
                # Ensure clip is selected in the timeline
                logger.info("Trying to select the clip in timeline again")
                current_timeline.SetCurrentVideoItem(current_clip)
                logger.info(f"Selected clip {current_clip.GetName()} in timeline")

                # Try to get grade again after selection
                current_grade = current_clip.GetCurrentGrade()
                if current_grade:
                    logger.info("Successfully got current grade after selection")
            except Exception as e:
                logger.error(f"Error in alternative selection approach: {str(e)}")

        # Direct node creation if we still don't have a grade object
        if not current_grade:
            logger.warning(
                "Could not get grade object, attempting direct node creation"
            )

            try:
                # Try using the node graph directly through ColorPage
                color_page = project_manager.GetCurrentPage()
                if color_page and hasattr(color_page, "GetNodeGraph"):
                    node_graph = color_page.GetNodeGraph()
                    if node_graph:
                        logger.info("Successfully got node graph through ColorPage")

                        # Direct node creation using node graph
                        if node_type.lower() == "serial":
                            result = node_graph.AddSerialNode()
                        elif node_type.lower() == "parallel":
                            result = node_graph.AddParallelNode()
                        elif node_type.lower() == "layer":
                            result = node_graph.AddLayerNode()

                        if result:
                            return f"Successfully added {node_type} node using direct NodeGraph approach"
                        else:
                            logger.error(
                                f"Failed to add {node_type} node using NodeGraph"
                            )
            except Exception as e:
                logger.error(f"Error in direct node creation attempt: {str(e)}")

            return f"Error adding {node_type} node: Cannot access grade object. The clip may not be properly graded yet."

        logger.info("Proceeding with node addition with valid grade object")
        # Add the appropriate type of node
        result = False
        method_name = ""

        if node_type.lower() == "serial":
            # Add a serial node after the current node
            method_name = "AddSerialNode"
            logger.info(f"Calling {method_name}()")
            result = current_grade.AddSerialNode()
        elif node_type.lower() == "parallel":
            # Add a parallel node
            method_name = "AddParallelNode"
            logger.info(f"Calling {method_name}()")
            result = current_grade.AddParallelNode()
        elif node_type.lower() == "layer":
            # Add a layer node
            method_name = "AddLayerNode"
            logger.info(f"Calling {method_name}()")
            result = current_grade.AddLayerNode()

        if not result:
            logger.error(f"Failed to add {node_type} node using {method_name}()")
            return f"Failed to add {node_type} node using {method_name}()"

        # Get the new node count and find the newly added node
        new_node_count = current_grade.GetNodeCount()
        logger.info(f"New node count: {new_node_count}")

        # Get the new node index - it should be the currently selected node
        new_node_index = current_grade.GetCurrentNode()
        logger.info(f"New node index: {new_node_index}")

        # Set label if provided
        if label and new_node_index > 0:
            try:
                logger.info(f"Setting node label to '{label}'")
                current_grade.SetNodeLabel(new_node_index, label)
                node_label_info = f" with label '{label}'"
            except Exception as e:
                logger.warning(f"Failed to set node label: {str(e)}")
                node_label_info = f" (couldn't set label to '{label}')"
        else:
            node_label_info = ""

        logger.info(
            f"Successfully added {node_type} node (index {new_node_index}){node_label_info}"
        )
        return f"Successfully added {node_type} node (index {new_node_index}){node_label_info}"

    except Exception as e:
        logger.error(f"Error adding {node_type} node: {str(e)}")
        return f"Error adding {node_type} node: {str(e)}"


def copy_grade(
    resolve,
    source_clip_name: str = None,
    target_clip_name: str = None,
    mode: str = "full",
) -> str:
    """Copy a grade from one clip to another in the color page.

    Args:
        resolve: The DaVinci Resolve instance
        source_clip_name: Name of the source clip to copy grade from (uses current clip if None)
        target_clip_name: Name of the target clip to apply grade to (uses current clip if None)
        mode: What to copy - 'full' (entire grade), 'current_node', or 'all_nodes'

    Returns:
        String indicating success or failure with detailed error message
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    # Validate copy mode
    valid_modes = ["full", "current_node", "all_nodes"]
    if mode.lower() not in valid_modes:
        return f"Error: Invalid copy mode. Must be one of: {', '.join(valid_modes)}"

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return "Error: No project currently open"

    # First, ensure we're on the color page
    current_page = resolve.GetCurrentPage()
    if current_page.lower() != "color":
        # Try to switch to color page
        result = resolve.OpenPage("color")
        if not result:
            return f"Error: Failed to switch to Color page. Current page is: {current_page}"

    # Get the current timeline
    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        return "Error: No timeline currently active"

    try:
        # Get all clips in the timeline
        all_video_clips = []

        # Get video track count
        video_track_count = current_timeline.GetTrackCount("video")

        # Gather all clips from video tracks
        for track_index in range(1, video_track_count + 1):
            track_items = current_timeline.GetItemListInTrack("video", track_index)
            if track_items:
                all_video_clips.extend(track_items)

        # Get the source clip
        source_clip = None
        if source_clip_name:
            # Find the source clip by name
            for clip in all_video_clips:
                if clip and clip.GetName() == source_clip_name:
                    source_clip = clip
                    break

            if not source_clip:
                return f"Error: Source clip '{source_clip_name}' not found in timeline"
        else:
            # Use the current clip as source
            source_clip = current_timeline.GetCurrentVideoItem()
            if not source_clip:
                return "Error: No clip is currently selected to use as source"
            source_clip_name = source_clip.GetName()

        # Get the source grade
        source_grade = source_clip.GetCurrentGrade()
        if not source_grade:
            return f"Error: Failed to get grade from source clip '{source_clip_name}'"

        # Get the target clip
        target_clip = None
        if target_clip_name:
            # Check if target is same as source
            if target_clip_name == source_clip_name:
                return f"Error: Source and target clips cannot be the same (both are '{source_clip_name}')"

            # Find the target clip by name
            for clip in all_video_clips:
                if clip and clip.GetName() == target_clip_name:
                    target_clip = clip
                    break

            if not target_clip:
                return f"Error: Target clip '{target_clip_name}' not found in timeline"
        else:
            # Use the current clip as target (need to select a different clip first)
            current_clip = current_timeline.GetCurrentVideoItem()

            if not current_clip:
                return "Error: No clip is currently selected to use as target"

            if current_clip.GetName() == source_clip_name:
                return "Error: Cannot copy grade to the same clip. Please specify a different target clip."

            target_clip = current_clip
            target_clip_name = target_clip.GetName()

        # Get the target grade
        target_grade = target_clip.GetCurrentGrade()
        if not target_grade:
            return f"Error: Failed to get grade from target clip '{target_clip_name}'"

        # Select the target clip to make it active for grade operations
        current_timeline.SetCurrentVideoItem(target_clip)

        # Execute the copy based on the specified mode
        result = False
        if mode.lower() == "full":
            # Copy the entire grade including all nodes
            result = target_clip.CopyGrade(source_clip)
        elif mode.lower() == "current_node":
            # Copy only the current node from source to target
            source_node_index = source_grade.GetCurrentNode()
            target_node_index = target_grade.GetCurrentNode()

            if source_node_index < 1:
                return "Error: No node selected in source clip"

            if target_node_index < 1:
                return "Error: No node selected in target clip"

            # Copy the current node
            result = target_grade.CopyFromNodeToNode(
                source_grade, source_node_index, target_node_index
            )
        elif mode.lower() == "all_nodes":
            # Copy all nodes but keep other grade settings
            source_node_count = source_grade.GetNodeCount()

            if source_node_count < 1:
                return "Error: Source clip has no nodes to copy"

            # First, clear all nodes in target
            target_node_count = target_grade.GetNodeCount()
            for i in range(target_node_count, 0, -1):
                target_grade.DeleteNode(i)

            # Then, add nodes matching the source structure
            for i in range(1, source_node_count + 1):
                # Determine node type
                if source_grade.IsSerial(i):
                    target_grade.AddSerialNode()
                elif source_grade.IsParallel(i):
                    target_grade.AddParallelNode()
                elif source_grade.IsLayer(i):
                    target_grade.AddLayerNode()

                # Copy node settings
                new_node_index = target_grade.GetCurrentNode()
                if new_node_index > 0:
                    target_grade.CopyFromNodeToNode(source_grade, i, new_node_index)

            result = True

        if result:
            return f"Successfully copied grade from '{source_clip_name}' to '{target_clip_name}' using mode '{mode}'"
        else:
            return f"Failed to copy grade from '{source_clip_name}' to '{target_clip_name}' using mode '{mode}'"

    except Exception as e:
        return f"Error copying grade: {str(e)}"


def get_color_wheels(resolve, node_index: int = None) -> Dict[str, Any]:
    """Get color wheel parameters for a specific node.

    Args:
        resolve: The DaVinci Resolve instance
        node_index: Index of the node to get color wheels from (uses current node if None)

    Returns:
        Dictionary with color wheel parameters
    """
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        return {"error": "Failed to get Project Manager"}

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        return {"error": "No project currently open"}

    # First, ensure we're on the color page
    current_page = resolve.GetCurrentPage()
    if current_page.lower() != "color":
        return {"error": f"Not on Color page. Current page is: {current_page}"}

    # Get the current timeline
    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        return {"error": "No timeline currently active"}

    try:
        # Get the current clip in the timeline
        current_clip = current_timeline.GetCurrentVideoItem()
        if not current_clip:
            return {"error": "No clip is currently selected in the timeline"}

        # Get the clip's grade
        current_grade = current_clip.GetCurrentGrade()
        if not current_grade:
            return {"error": "Failed to get current grade"}

        # Determine which node to get color wheels from
        target_node_index = node_index
        if target_node_index is None:
            # Use the currently selected node
            target_node_index = current_grade.GetCurrentNode()
            if target_node_index < 1:
                return {"error": "No node is currently selected"}
        else:
            # Validate the provided node index
            node_count = current_grade.GetNodeCount()
            if target_node_index < 1 or target_node_index > node_count:
                return {
                    "error": f"Invalid node index {target_node_index}. Valid range: 1-{node_count}"
                }

        # Get node name if available
        node_name = ""
        try:
            node_name = current_grade.GetNodeName(target_node_index)
        except:
            node_name = f"Node {target_node_index}"

        # Get color wheel parameters
        color_wheels = {
            "node_index": target_node_index,
            "node_name": node_name,
            "clip_name": current_clip.GetName(),
            "wheels": {},
        }

        # Try to get each of the color wheels
        wheels_to_get = [
            {"name": "lift", "function_prefix": "GetLift"},
            {"name": "gamma", "function_prefix": "GetGamma"},
            {"name": "gain", "function_prefix": "GetGain"},
            {"name": "offset", "function_prefix": "GetOffset"},
        ]

        for wheel in wheels_to_get:
            wheel_name = wheel["name"]
            prefix = wheel["function_prefix"]

            wheel_data = {}
            try:
                # Try to get R, G, B, and Y (master) values
                for channel, channel_name in [
                    ("R", "red"),
                    ("G", "green"),
                    ("B", "blue"),
                    ("Y", "master"),
                ]:
                    # Build the function name dynamically
                    function_name = f"{prefix}{channel}"

                    if hasattr(current_grade, function_name):
                        # Call the function with the node index
                        getter_func = getattr(current_grade, function_name)
                        value = getter_func(target_node_index)
                        wheel_data[channel_name] = value

                if wheel_data:
                    color_wheels["wheels"][wheel_name] = wheel_data
            except Exception as e:
                color_wheels["wheels"][wheel_name] = {
                    "error": f"Could not get {wheel_name} wheel: {str(e)}"
                }

        # Try to get additional common color controls
        try:
            additional_controls = {}

            # Try to get contrast
            try:
                if hasattr(current_grade, "GetContrast"):
                    additional_controls["contrast"] = current_grade.GetContrast(
                        target_node_index
                    )
            except:
                pass

            # Try to get saturation
            try:
                if hasattr(current_grade, "GetSaturation"):
                    additional_controls["saturation"] = current_grade.GetSaturation(
                        target_node_index
                    )
            except:
                pass

            # Try to get color temperature
            try:
                if hasattr(current_grade, "GetColorTemp"):
                    additional_controls["color_temp"] = current_grade.GetColorTemp(
                        target_node_index
                    )
            except:
                pass

            # Try to get tint
            try:
                if hasattr(current_grade, "GetTint"):
                    additional_controls["tint"] = current_grade.GetTint(
                        target_node_index
                    )
            except:
                pass

            # Add additional controls if any were found
            if additional_controls:
                color_wheels["additional_controls"] = additional_controls
        except:
            pass

        return color_wheels

    except Exception as e:
        return {"error": f"Error getting color wheel parameters: {str(e)}"}


def set_color_wheel_param(
    resolve, wheel: str, param: str, value: float, node_index: int = None
) -> str:
    """Set a color wheel parameter for a node.

    Args:
        resolve: The DaVinci Resolve instance
        wheel: Which color wheel to adjust ('lift', 'gamma', 'gain', 'offset')
        param: Which parameter to adjust ('red', 'green', 'blue', 'master')
        value: The value to set (typically between -1.0 and 1.0)
        node_index: Index of the node to set parameter for (uses current node if None)

    Returns:
        String indicating success or failure with detailed error message
    """
    if resolve is None:
        return "Error: Not connected to DaVinci Resolve"

    # Validate wheel
    valid_wheels = ["lift", "gamma", "gain", "offset"]
    if wheel.lower() not in valid_wheels:
        return f"Error: Invalid wheel name. Must be one of: {', '.join(valid_wheels)}"

    # Validate parameter
    valid_params = ["red", "green", "blue", "master"]
    if param.lower() not in valid_params:
        return (
            f"Error: Invalid parameter name. Must be one of: {', '.join(valid_params)}"
        )

    logger.info(f"Setting {wheel} {param} to {value}")

    # Map parameter names to channel identifiers used in the API
    param_to_channel = {"red": "R", "green": "G", "blue": "B", "master": "Y"}

    # Map wheel names to function name prefixes used in the API
    wheel_to_function_prefix = {
        "lift": "SetLift",
        "gamma": "SetGamma",
        "gain": "SetGain",
        "offset": "SetOffset",
    }

    project_manager = resolve.GetProjectManager()
    if not project_manager:
        logger.error("Failed to get Project Manager")
        return "Error: Failed to get Project Manager"

    current_project = project_manager.GetCurrentProject()
    if not current_project:
        logger.error("No project currently open")
        return "Error: No project currently open"

    # First, ensure we're on the color page
    current_page = resolve.GetCurrentPage()
    if current_page.lower() != "color":
        # Try to switch to color page
        logger.info(f"Currently on {current_page} page, switching to color page")
        result = resolve.OpenPage("color")
        if not result:
            logger.error(
                f"Failed to switch to Color page. Current page is: {current_page}"
            )
            return f"Error: Failed to switch to Color page. Current page is: {current_page}"
        logger.info("Successfully switched to color page")

    # Get the current timeline
    current_timeline = current_project.GetCurrentTimeline()
    if not current_timeline:
        logger.error("No timeline currently active")
        return "Error: No timeline currently active"

    try:
        # Use the helper function to ensure a clip is selected
        clip_selected, current_clip, message = ensure_clip_selected(
            resolve, current_timeline
        )

        if not clip_selected or not current_clip:
            logger.error("No clip could be selected automatically")
            return (
                f"Error: {message}. Please select a clip manually in DaVinci Resolve."
            )

        logger.info(f"Working with clip: {current_clip.GetName()}")

        # Get the clip's grade
        # This is where the NoneType error typically occurs
        logger.info("Attempting to get current grade")

        # First method: Direct approach
        try:
            current_grade = current_clip.GetCurrentGrade()
            if current_grade:
                logger.info("Successfully got current grade using GetCurrentGrade()")
            else:
                logger.warning("GetCurrentGrade() returned None")
        except Exception as e:
            logger.error(f"Error getting current grade via GetCurrentGrade(): {str(e)}")
            current_grade = None

        # Alternative approach if the first method failed
        if not current_grade:
            logger.info("Attempting alternative methods to access grade functionality")

            # Try to select the clip first to ensure it's active
            try:
                # Ensure clip is selected in the timeline
                logger.info("Trying to select the clip in timeline again")
                current_timeline.SetCurrentVideoItem(current_clip)
                logger.info(f"Selected clip {current_clip.GetName()} in timeline")

                # Try to get grade again after selection
                current_grade = current_clip.GetCurrentGrade()
                if current_grade:
                    logger.info("Successfully got current grade after selection")
            except Exception as e:
                logger.error(f"Error in alternative selection approach: {str(e)}")

        # Check if we have a valid grade object
        if not current_grade:
            logger.error("Could not get grade object after multiple attempts")
            return "Error setting color wheel parameter: Cannot access grade object. The clip may not be properly graded yet."

        logger.info("Proceeding with parameter setting with valid grade object")

        # Determine which node to set parameter for
        target_node_index = node_index
        if target_node_index is None:
            # Use the currently selected node
            logger.info("Getting current node index")
            target_node_index = current_grade.GetCurrentNode()
            if target_node_index < 1:
                logger.error("No node is currently selected")
                return "Error: No node is currently selected"
            logger.info(f"Using current node: {target_node_index}")
        else:
            # Validate the provided node index
            logger.info(f"Validating provided node index: {target_node_index}")
            node_count = current_grade.GetNodeCount()
            if target_node_index < 1 or target_node_index > node_count:
                logger.error(
                    f"Invalid node index {target_node_index}. Valid range: 1-{node_count}"
                )
                return f"Error: Invalid node index {target_node_index}. Valid range: 1-{node_count}"

        # Get node name for better reporting
        node_name = ""
        try:
            logger.info(f"Getting name for node {target_node_index}")
            node_name = (
                current_grade.GetNodeName(target_node_index)
                or f"Node {target_node_index}"
            )
            logger.info(f"Node name: {node_name}")
        except Exception as e:
            logger.warning(f"Could not get node name: {str(e)}")
            node_name = f"Node {target_node_index}"

        # Build the function name to call
        channel = param_to_channel[param.lower()]
        function_prefix = wheel_to_function_prefix[wheel.lower()]
        function_name = f"{function_prefix}{channel}"
        logger.info(f"Function to call: {function_name}")

        # Check if the function exists
        if not hasattr(current_grade, function_name):
            logger.error(f"Function '{function_name}' not found in DaVinci Resolve API")
            return f"Error: Function '{function_name}' not found in DaVinci Resolve API for setting {wheel} {param}"

        # Get the setter function
        setter_func = getattr(current_grade, function_name)

        # Set the parameter value
        logger.info(f"Calling {function_name}({target_node_index}, {value})")
        result = setter_func(target_node_index, value)

        if result:
            logger.info(f"Successfully set {wheel} {param} to {value} for {node_name}")
            return f"Successfully set {wheel} {param} to {value} for {node_name}"
        else:
            logger.error(f"Failed to set {wheel} {param} to {value} for {node_name}")
            return f"Failed to set {wheel} {param} to {value} for {node_name}"

    except Exception as e:
        logger.error(f"Error setting color wheel parameter: {str(e)}")
        return f"Error setting color wheel parameter: {str(e)}"


def ensure_clip_selected(resolve, timeline) -> Tuple[bool, Optional[Any], str]:
    """Ensures a clip is selected in the timeline, selecting the first clip if needed.

    Args:
        resolve: The DaVinci Resolve instance
        timeline: The current timeline

    Returns:
        Tuple containing (success, clip_object, message)
    """
    # First check if there's already a clip selected
    current_clip = timeline.GetCurrentVideoItem()
    if current_clip:
        logger.info(f"Clip already selected: {current_clip.GetName()}")
        return (
            True,
            current_clip,
            f"Using currently selected clip: {current_clip.GetName()}",
        )

    # No clip selected, try to select the first clip
    logger.info("No clip currently selected, attempting to select first clip")
    try:
        # Get video tracks
        video_track_count = timeline.GetTrackCount("video")
        logger.info(f"Timeline has {video_track_count} video tracks")

        # Check each track for clips
        for track_index in range(1, video_track_count + 1):
            logger.info(f"Checking video track {track_index}")

            # Get clips in this track
            track_items = timeline.GetItemListInTrack("video", track_index)
            if not track_items or len(track_items) == 0:
                logger.info(f"No clips in track {track_index}")
                continue

            logger.info(f"Found {len(track_items)} clips in track {track_index}")

            # Try to select the first clip
            first_clip = track_items[0]
            if first_clip:
                clip_name = first_clip.GetName()
                logger.info(f"Attempting to select clip: {clip_name}")

                # Set it as the current clip
                timeline.SetCurrentVideoItem(first_clip)

                # Verify selection
                selected_clip = timeline.GetCurrentVideoItem()
                if selected_clip and selected_clip.GetName() == clip_name:
                    logger.info(f"Successfully selected first clip: {clip_name}")
                    return (
                        True,
                        selected_clip,
                        f"Automatically selected clip: {clip_name}",
                    )
                else:
                    logger.warning("Failed to verify clip selection")

            # If we got here, we couldn't select a clip in this track
            logger.warning(f"Could not select a clip in track {track_index}")

        # If we reach here, we couldn't find or select any clips
        logger.warning("No clips found in any video track, or could not select any")
        return False, None, "Could not find any clips in the timeline to select"

    except Exception as e:
        logger.error(f"Error attempting to select a clip: {str(e)}")
        return False, None, f"Error selecting clip: {str(e)}"
