"""
DaVinci Resolve Project Settings MCP Functions

This module provides functions to get and set DaVinci Resolve project settings.
"""

import sys
import os
import json
from typing import Dict, Any, Optional, Union

# Try to import the DaVinci Resolve scripting module
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    resolve_api_path = os.environ.get(
        "RESOLVE_SCRIPT_API",
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
    )
    resolve_module_path = os.path.join(resolve_api_path, "Modules")
    sys.path.append(resolve_module_path)
    import DaVinciResolveScript as dvr
except ImportError:
    print("Error: Could not import DaVinci Resolve scripting modules")


def get_resolve_instance():
    """Get the current instance of DaVinci Resolve"""
    try:
        resolve = dvr.scriptapp("Resolve")
        return resolve
    except NameError:
        print("Error: DaVinci Resolve not found")
        return None


def mcp_get_project_setting(setting_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get a project setting or all project settings.

    Args:
        setting_name: The name of the setting to retrieve, or None to get all settings

    Returns:
        A dictionary with the setting value or all settings
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        if setting_name is None:
            # Get all project settings
            settings = current_project.GetSetting("")
            return {"settings": settings}
        else:
            # Get specific setting
            setting_value = current_project.GetSetting(setting_name)
            return {setting_name: setting_value}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_set_project_setting(setting_name: str, setting_value: Any) -> Dict[str, Any]:
    """
    Set a project setting.

    Args:
        setting_name: The name of the setting to set
        setting_value: The value to set

    Returns:
        A dictionary with the status of the operation
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Convert setting_value to appropriate type
        original_value = setting_value

        # Define setting categories for proper type handling
        numeric_settings = [
            "timelineFrameRate",
            "timelineResolutionWidth",
            "timelineResolutionHeight",
            "videoMonitorWidth",
            "videoMonitorHeight",
            "videoMonitorBitDepth",
            "superScale",
            "audioSampleRate",
        ]

        boolean_settings = [
            "timelineUseCustomSettings",
            "videoMonitorUseRec709A",
            "videoMonitorUseColorspaceOverride",
            "superScaleQuality",
            "videoMonitorUse3D",
            "useRollingShutter",
            "useSmoothOpticalFlow",
            "useDynamicZoomEase",
            "autoClipColors",
            "audoColorLuminanceMix",
        ]

        enum_settings = {
            "colorScienceMode": [
                "davinciYRGBColorManaged",
                "davinciYRGB",
                "davinciACESCC",
            ],
            "timelineOutputSizing": [
                "outputSizingFormatCentered",
                "outputSizingFormatFill",
                "none",
            ],
            "inputColorSpace": [
                "Rec.709",
                "Rec.2020",
                "BMD Film",
                "BMD 4K Film",
                "BMD 4.6K Film",
                "Panasonic V-Log",
            ],
            "outputColorSpace": ["Rec.709", "Rec.2020", "DCI-P3 D65", "DCI-P3"],
        }

        # Convert based on setting type
        if setting_name in numeric_settings:
            try:
                # Try to handle numeric values properly
                if isinstance(setting_value, (int, float)):
                    setting_value = str(setting_value)
                elif isinstance(setting_value, str):
                    # Ensure it's a valid number
                    float(setting_value)  # This will raise ValueError if not numeric
            except ValueError:
                return {
                    "error": f"Invalid numeric value '{setting_value}' for setting '{setting_name}'"
                }

        elif setting_name in boolean_settings:
            if isinstance(setting_value, bool):
                setting_value = "1" if setting_value else "0"
            elif isinstance(setting_value, str):
                if setting_value.lower() in ["true", "yes", "1", "on"]:
                    setting_value = "1"
                elif setting_value.lower() in ["false", "no", "0", "off"]:
                    setting_value = "0"
                else:
                    return {
                        "error": f"Invalid boolean value '{setting_value}' for setting '{setting_name}'"
                    }
            elif isinstance(setting_value, (int, float)):
                setting_value = "1" if setting_value else "0"

        elif setting_name in enum_settings and isinstance(setting_value, str):
            valid_values = enum_settings[setting_name]
            if setting_value not in valid_values:
                return {
                    "error": f"Invalid value '{setting_value}' for setting '{setting_name}'. Valid values are: {', '.join(valid_values)}"
                }

        # Convert to string for API call
        if setting_value is not None:
            setting_value = str(setting_value)

        # Get the current value for comparison
        try:
            current_value = current_project.GetSetting(setting_name)
        except Exception:
            current_value = None

        # First approach: Try to set directly via project
        success = False
        try:
            success = current_project.SetSetting(setting_name, setting_value)
        except Exception as e:
            print(f"First attempt error: {str(e)}")

        # Verify the setting was actually changed
        try:
            new_value = current_project.GetSetting(setting_name)
            value_changed = new_value != current_value
        except Exception:
            new_value = None
            value_changed = False

        if success or value_changed:
            return {
                "status": "success",
                "message": f"Setting '{setting_name}' updated successfully",
                "old_value": current_value,
                "new_value": new_value,
            }

        # Second approach: Try specific approaches based on setting type
        if setting_name.startswith("timeline"):
            # Try through the current timeline for timeline settings
            try:
                timeline = current_project.GetCurrentTimeline()
                if timeline:
                    # Remove "timeline" prefix for the timeline setting name
                    timeline_setting = setting_name.replace("timeline", "")
                    # Make sure first letter is lowercase for proper setting name
                    if timeline_setting and len(timeline_setting) > 0:
                        timeline_setting = (
                            timeline_setting[0].lower() + timeline_setting[1:]
                        )
                        timeline_success = timeline.SetSetting(
                            timeline_setting, setting_value
                        )
                        if timeline_success:
                            return {
                                "status": "success",
                                "message": f"Timeline setting '{setting_name}' updated via timeline API",
                                "value": setting_value,
                            }
            except Exception as e:
                print(f"Timeline approach error: {str(e)}")

        # Third approach: Try accessing project settings through project format settings
        try:
            if hasattr(current_project, "GetSetting") and callable(
                current_project.GetCurrentTimeline
            ):
                # Try to get and set project format settings
                timeline = current_project.GetCurrentTimeline()
                if (
                    timeline
                    and hasattr(timeline, "GetSetting")
                    and callable(timeline.SetSetting)
                ):
                    # Attempt via format settings on timeline
                    if setting_name in [
                        "timelineFrameRate",
                        "timelineResolutionWidth",
                        "timelineResolutionHeight",
                    ]:
                        # Map to timeline settings
                        timeline_map = {
                            "timelineFrameRate": "frameRate",
                            "timelineResolutionWidth": "width",
                            "timelineResolutionHeight": "height",
                        }

                        if setting_name in timeline_map:
                            timeline_setting = timeline_map[setting_name]
                            timeline_success = timeline.SetSetting(
                                timeline_setting, setting_value
                            )
                            if timeline_success:
                                return {
                                    "status": "success",
                                    "message": f"Setting '{setting_name}' updated via timeline format settings",
                                    "value": setting_value,
                                }
        except Exception as e:
            print(f"Format settings approach error: {str(e)}")

        # Fourth approach: Try through the project settings changed event
        try:
            if hasattr(current_project, "LoadRenderPreset") and callable(
                current_project.LoadRenderPreset
            ):
                # Some settings might be changed by loading a preset and then modifying it
                if setting_name in [
                    "colorScienceMode",
                    "timelineResolutionWidth",
                    "timelineResolutionHeight",
                    "timelineFrameRate",
                ]:
                    # Attempt to refresh project settings by loading current preset
                    presets = current_project.GetRenderPresetList()
                    if presets and len(presets) > 0:
                        # Load first preset to trigger settings refresh
                        current_project.LoadRenderPreset(presets[0])
                        # Try setting again
                        second_try = current_project.SetSetting(
                            setting_name, setting_value
                        )
                        if second_try:
                            return {
                                "status": "success",
                                "message": f"Setting '{setting_name}' updated via settings refresh",
                                "value": setting_value,
                            }
        except Exception as e:
            print(f"Preset approach error: {str(e)}")

        # Final fallback: Return failure with debugging info
        return {
            "error": f"Failed to update setting '{setting_name}' with value '{setting_value}'",
            "debug_info": {
                "original_value": str(original_value),
                "converted_value": setting_value,
                "current_value": current_value,
                "new_value": new_value,
                "success_flag": success,
                "value_changed": value_changed,
            },
        }

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_get_timeline_setting(
    timeline_name: Optional[str] = None, setting_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get a timeline setting or all timeline settings.

    Args:
        timeline_name: The name of the timeline, or None for current timeline
        setting_name: The name of the setting to retrieve, or None to get all settings

    Returns:
        A dictionary with the setting value or all settings
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Get the timeline
        timeline = None
        if timeline_name:
            # Try to find the timeline by name
            timeline_count = current_project.GetTimelineCount()
            for i in range(1, timeline_count + 1):
                timeline_obj = current_project.GetTimelineByIndex(i)
                if timeline_obj.GetName() == timeline_name:
                    timeline = timeline_obj
                    break

            if not timeline:
                return {"error": f"Timeline '{timeline_name}' not found"}
        else:
            # Use the current timeline
            timeline = current_project.GetCurrentTimeline()
            if not timeline:
                return {"error": "No timeline is currently active"}

        if setting_name is None:
            # Get all timeline settings
            settings = timeline.GetSetting("")
            return {"timeline": timeline.GetName(), "settings": settings}
        else:
            # Get specific setting
            setting_value = timeline.GetSetting(setting_name)
            return {"timeline": timeline.GetName(), setting_name: setting_value}

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}


def mcp_set_timeline_setting(
    setting_name: str, setting_value: Any, timeline_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Set a timeline setting.

    Args:
        setting_name: The name of the setting to set
        setting_value: The value to set
        timeline_name: The name of the timeline, or None for current timeline

    Returns:
        A dictionary with the status of the operation
    """
    try:
        resolve = get_resolve_instance()
        if not resolve:
            return {"error": "DaVinci Resolve not found"}

        project_manager = resolve.GetProjectManager()
        if not project_manager:
            return {"error": "Could not get Project Manager"}

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            return {"error": "No project is currently open"}

        # Get the timeline
        timeline = None
        if timeline_name:
            # Try to find the timeline by name
            timeline_count = current_project.GetTimelineCount()
            for i in range(1, timeline_count + 1):
                timeline_obj = current_project.GetTimelineByIndex(i)
                if timeline_obj and timeline_obj.GetName() == timeline_name:
                    timeline = timeline_obj
                    break

            if not timeline:
                return {"error": f"Timeline '{timeline_name}' not found"}
        else:
            # Get the current timeline
            timeline = current_project.GetCurrentTimeline()
            if not timeline:
                return {"error": "No timeline is currently open"}

        # Convert setting_value to appropriate type
        original_value = setting_value

        # Define setting categories for proper type handling
        numeric_settings = [
            "width",
            "height",
            "frameRate",
            "audioSampleRate",
            "audioFrameRate",
            "videoFrameRate",
            "timecodeRate",
        ]

        boolean_settings = [
            "useRollingShutter",
            "useSmoothOpticalFlow",
            "useDynamicZoomEase",
            "useSmartcache",
            "usePerfectResizeNE",
            "createStereoVersion",
        ]

        enum_settings = {
            "superscaleMethod": ["Sharp", "Smooth", "Bicubic", "Bilinear", "Sharper"],
            "motionEstimation": ["Faster", "Normal", "Better"],
            "resizeFilter": ["Sharper", "Smoother", "Bicubic", "Bilinear", "Bessel"],
        }

        # Convert based on setting type
        if setting_name in numeric_settings:
            try:
                # Try to handle numeric values properly
                if isinstance(setting_value, (int, float)):
                    setting_value = str(setting_value)
                elif isinstance(setting_value, str):
                    # Ensure it's a valid number
                    float(setting_value)  # This will raise ValueError if not numeric
            except ValueError:
                return {
                    "error": f"Invalid numeric value '{setting_value}' for setting '{setting_name}'"
                }

        elif setting_name in boolean_settings:
            if isinstance(setting_value, bool):
                setting_value = "1" if setting_value else "0"
            elif isinstance(setting_value, str):
                if setting_value.lower() in ["true", "yes", "1", "on"]:
                    setting_value = "1"
                elif setting_value.lower() in ["false", "no", "0", "off"]:
                    setting_value = "0"
                else:
                    return {
                        "error": f"Invalid boolean value '{setting_value}' for setting '{setting_name}'"
                    }
            elif isinstance(setting_value, (int, float)):
                setting_value = "1" if setting_value else "0"

        elif setting_name in enum_settings and isinstance(setting_value, str):
            valid_values = enum_settings[setting_name]
            if setting_value not in valid_values:
                return {
                    "error": f"Invalid value '{setting_value}' for setting '{setting_name}'. Valid values are: {', '.join(valid_values)}"
                }

        # Convert to string for API call
        if setting_value is not None:
            setting_value = str(setting_value)

        # Get the current value for comparison
        try:
            current_value = timeline.GetSetting(setting_name)
        except Exception:
            current_value = None

        # First approach: Try to set directly via timeline
        success = False
        try:
            success = timeline.SetSetting(setting_name, setting_value)
        except Exception as e:
            print(f"First attempt error: {str(e)}")

        # Verify the setting was actually changed
        try:
            new_value = timeline.GetSetting(setting_name)
            value_changed = new_value != current_value
        except Exception:
            new_value = None
            value_changed = False

        if success or value_changed:
            return {
                "status": "success",
                "message": f"Timeline setting '{setting_name}' updated successfully",
                "old_value": current_value,
                "new_value": new_value,
            }

        # Second approach: Try through project settings if it's a timeline-related project setting
        try:
            project_setting_name = (
                "timeline" + setting_name[0].upper() + setting_name[1:]
            )
            project_success = current_project.SetSetting(
                project_setting_name, setting_value
            )
            if project_success:
                return {
                    "status": "success",
                    "message": f"Timeline setting '{setting_name}' updated via project settings",
                    "value": setting_value,
                }
        except Exception as e:
            print(f"Project settings approach error: {str(e)}")

        # Third approach: Try accessing project settings through refreshing timeline
        try:
            # Some settings might be applied by refreshing the timeline
            current_timeline_index = current_project.GetCurrentTimeline()
            if current_timeline_index:
                # Try setting again after switching timelines (forces refresh)
                timeline_count = current_project.GetTimelineCount()
                if timeline_count > 1:
                    for i in range(1, timeline_count + 1):
                        temp_timeline = current_project.GetTimelineByIndex(i)
                        if temp_timeline and temp_timeline != timeline:
                            # Switch to a different timeline
                            current_project.SetCurrentTimeline(temp_timeline)
                            # Switch back to original timeline
                            current_project.SetCurrentTimeline(timeline)
                            # Try setting again
                            second_try = timeline.SetSetting(
                                setting_name, setting_value
                            )
                            if second_try:
                                return {
                                    "status": "success",
                                    "message": f"Timeline setting '{setting_name}' updated via timeline refresh",
                                    "value": setting_value,
                                }
                            break
        except Exception as e:
            print(f"Timeline refresh approach error: {str(e)}")

        # Final fallback: Return failure with debugging info
        return {
            "error": f"Failed to update timeline setting '{setting_name}' with value '{setting_value}'",
            "debug_info": {
                "original_value": str(original_value),
                "converted_value": setting_value,
                "current_value": current_value,
                "new_value": new_value,
                "success_flag": success,
                "value_changed": value_changed,
            },
        }

    except Exception as e:
        return {"error": f"An error occurred: {str(e)}"}
