#!/usr/bin/env python3
"""
Tool Definitions for Gemini Function Calling

Defines the schema for each tool that the AI can call.
These are formatted for Google Gemini's function calling API.
"""

from typing import Dict, List, Any

# Tool definitions formatted for Gemini function calling
TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    # ============ PROJECT MANAGEMENT ============
    {
        "name": "open_project",
        "description": "Open an existing project by name",
        "parameters": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Name of the project to open"
                }
            },
            "required": ["project_name"]
        }
    },
    {
        "name": "create_project",
        "description": "Create a new project with the given name",
        "parameters": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Name for the new project"
                }
            },
            "required": ["project_name"]
        }
    },
    {
        "name": "save_project",
        "description": "Save the current project",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "close_project",
        "description": "Close the current project",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    
    # ============ TIMELINE OPERATIONS ============
    {
        "name": "create_timeline",
        "description": "Create a new timeline with clips from a bin",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the new timeline"
                },
                "bin_name": {
                    "type": "string",
                    "description": "Name of the bin to get clips from (optional)"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "create_empty_timeline",
        "description": "Create a new empty timeline",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the new timeline"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "delete_timeline",
        "description": "Delete a timeline by name",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the timeline to delete"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "set_current_timeline",
        "description": "Switch to a different timeline",
        "parameters": {
            "type": "object",
            "properties": {
                "timeline_name": {
                    "type": "string",
                    "description": "Name of the timeline to switch to"
                }
            },
            "required": ["timeline_name"]
        }
    },
    {
        "name": "add_marker",
        "description": "Add a marker to the current timeline",
        "parameters": {
            "type": "object",
            "properties": {
                "frame": {
                    "type": "integer",
                    "description": "Frame number for the marker"
                },
                "color": {
                    "type": "string",
                    "description": "Marker color (Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream)"
                },
                "name": {
                    "type": "string",
                    "description": "Name/title for the marker"
                },
                "note": {
                    "type": "string",
                    "description": "Note/description for the marker"
                }
            },
            "required": ["frame", "color"]
        }
    },
    {
        "name": "add_beat_markers",
        "description": "Analyze audio for beats and add markers at beat positions",
        "parameters": {
            "type": "object",
            "properties": {
                "audio_file_path": {
                    "type": "string",
                    "description": "Path to the audio file to analyze"
                },
                "marker_color": {
                    "type": "string",
                    "description": "Color for the beat markers (default: Blue)"
                },
                "max_markers": {
                    "type": "integer",
                    "description": "Maximum number of markers to add (default: 50)"
                }
            },
            "required": ["audio_file_path"]
        }
    },
    {
        "name": "add_scene_markers",
        "description": "Detect scenes in a video and add markers at cut points",
        "parameters": {
            "type": "object",
            "properties": {
                "video_file_path": {
                    "type": "string",
                    "description": "Path to the video file to analyze"
                },
                "marker_color": {
                    "type": "string",
                    "description": "Color for scene markers (default: Yellow)"
                },
                "method": {
                    "type": "string",
                    "description": "Detection method: adaptive, content, or threshold"
                }
            },
            "required": ["video_file_path"]
        }
    },
    
    # ============ MEDIA OPERATIONS ============
    {
        "name": "import_media",
        "description": "Import a media file into the media pool",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Full path to the media file"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "list_bin_clips",
        "description": "List all clips in a media pool bin",
        "parameters": {
            "type": "object",
            "properties": {
                "bin_name": {
                    "type": "string",
                    "description": "Name of the bin (use 'Master' for root folder)"
                }
            },
            "required": ["bin_name"]
        }
    },
    {
        "name": "add_clip_to_timeline",
        "description": "Add a clip from the media pool to the current timeline",
        "parameters": {
            "type": "object",
            "properties": {
                "clip_name": {
                    "type": "string",
                    "description": "Name of the clip to add"
                },
                "timeline_name": {
                    "type": "string",
                    "description": "Name of the timeline (uses current if not specified)"
                }
            },
            "required": ["clip_name"]
        }
    },
    {
        "name": "add_clip_from_bin",
        "description": "Add a specific clip from a bin to the current timeline",
        "parameters": {
            "type": "object",
            "properties": {
                "clip_name": {
                    "type": "string",
                    "description": "Name of the clip to add"
                },
                "bin_name": {
                    "type": "string",
                    "description": "Name of the bin containing the clip"
                }
            },
            "required": ["clip_name"]
        }
    },
    {
        "name": "add_all_bin_clips_to_timeline",
        "description": "Add all clips from a bin to the timeline",
        "parameters": {
            "type": "object",
            "properties": {
                "bin_name": {
                    "type": "string",
                    "description": "Name of the bin"
                },
                "timeline_name": {
                    "type": "string",
                    "description": "Name of the timeline (creates new if not specified)"
                }
            },
            "required": ["bin_name"]
        }
    },
    {
        "name": "create_bin",
        "description": "Create a new bin in the media pool",
        "parameters": {
            "type": "object",
            "properties": {
                "bin_name": {
                    "type": "string",
                    "description": "Name for the new bin"
                }
            },
            "required": ["bin_name"]
        }
    },
    {
        "name": "get_audio_clip_path",
        "description": "Get the file path of an audio clip in the media pool",
        "parameters": {
            "type": "object",
            "properties": {
                "clip_name": {
                    "type": "string",
                    "description": "Name of the audio clip"
                }
            },
            "required": ["clip_name"]
        }
    },
    {
        "name": "get_video_clip_path",
        "description": "Get the file path of a video clip in the media pool",
        "parameters": {
            "type": "object",
            "properties": {
                "clip_name": {
                    "type": "string",
                    "description": "Name of the video clip"
                }
            },
            "required": ["clip_name"]
        }
    },
    
    # ============ COLOR GRADING ============
    {
        "name": "list_color_presets",
        "description": "List all available cinematic color presets",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "apply_color_preset",
        "description": "Apply a cinematic color preset to timeline clips",
        "parameters": {
            "type": "object",
            "properties": {
                "preset_name": {
                    "type": "string",
                    "description": "Name of the preset: netflix, teal-orange, cyberpunk, music-video, moody-dark, vintage, bleach-bypass, documentary, kodak-5219, arri-alexa"
                },
                "apply_to_all": {
                    "type": "boolean",
                    "description": "Apply to all clips (default: true)"
                },
                "track": {
                    "type": "integer",
                    "description": "Specific track number to target (optional)"
                }
            },
            "required": ["preset_name"]
        }
    },
    {
        "name": "apply_lut",
        "description": "Apply a LUT file to clips",
        "parameters": {
            "type": "object",
            "properties": {
                "lut_path": {
                    "type": "string",
                    "description": "Path to the LUT file"
                }
            },
            "required": ["lut_path"]
        }
    },
    
    # ============ AUDIO ============
    {
        "name": "analyze_audio_beats",
        "description": "Analyze an audio file for BPM and beat positions",
        "parameters": {
            "type": "object",
            "properties": {
                "audio_file_path": {
                    "type": "string",
                    "description": "Path to the audio file"
                }
            },
            "required": ["audio_file_path"]
        }
    },
    {
        "name": "duck_audio_under_voiceover",
        "description": "Create a ducked version of music that lowers during speech",
        "parameters": {
            "type": "object",
            "properties": {
                "voiceover_clip_name": {
                    "type": "string",
                    "description": "Name of the voiceover clip in media pool"
                },
                "music_clip_name": {
                    "type": "string",
                    "description": "Name of the music clip in media pool"
                },
                "duck_db": {
                    "type": "number",
                    "description": "How much to reduce music in dB (default: 10)"
                }
            },
            "required": ["voiceover_clip_name", "music_clip_name"]
        }
    },
    
    # ============ AI ANALYSIS ============
    {
        "name": "analyze_clip_with_ai",
        "description": "Use AI to analyze a video clip and generate description, keywords, mood, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "clip_name": {
                    "type": "string",
                    "description": "Name of the clip in media pool"
                },
                "provider": {
                    "type": "string",
                    "description": "AI provider: gemini or openai (default: gemini)"
                },
                "num_frames": {
                    "type": "integer",
                    "description": "Number of frames to analyze (3, 5, or 7)"
                }
            },
            "required": ["clip_name"]
        }
    },
    {
        "name": "analyze_video_scenes",
        "description": "Detect scene changes in a video file",
        "parameters": {
            "type": "object",
            "properties": {
                "video_file_path": {
                    "type": "string",
                    "description": "Path to the video file"
                },
                "method": {
                    "type": "string",
                    "description": "Detection method: adaptive, content, or threshold"
                }
            },
            "required": ["video_file_path"]
        }
    },
    
    # ============ TIMELINE ITEM EFFECTS ============
    {
        "name": "set_timeline_item_transform",
        "description": "Set transform properties (zoom, position, rotation) for a timeline item",
        "parameters": {
            "type": "object",
            "properties": {
                "timeline_item_id": {
                    "type": "string",
                    "description": "ID of the timeline item"
                },
                "zoom_x": {
                    "type": "number",
                    "description": "Horizontal zoom (1.0 = 100%)"
                },
                "zoom_y": {
                    "type": "number",
                    "description": "Vertical zoom (1.0 = 100%)"
                },
                "position_x": {
                    "type": "number",
                    "description": "X position"
                },
                "position_y": {
                    "type": "number",
                    "description": "Y position"
                },
                "rotation": {
                    "type": "number",
                    "description": "Rotation in degrees"
                }
            },
            "required": ["timeline_item_id"]
        }
    },
    {
        "name": "set_timeline_item_composite",
        "description": "Set composite properties (opacity, blend mode) for a timeline item",
        "parameters": {
            "type": "object",
            "properties": {
                "timeline_item_id": {
                    "type": "string",
                    "description": "ID of the timeline item"
                },
                "opacity": {
                    "type": "number",
                    "description": "Opacity (0.0 to 1.0)"
                },
                "composite_mode": {
                    "type": "string",
                    "description": "Blend mode"
                }
            },
            "required": ["timeline_item_id"]
        }
    },
    
    # ============ RENDERING ============
    {
        "name": "add_to_render_queue",
        "description": "Add the current timeline to the render queue",
        "parameters": {
            "type": "object",
            "properties": {
                "preset_name": {
                    "type": "string",
                    "description": "Render preset name"
                },
                "output_path": {
                    "type": "string",
                    "description": "Output file path"
                }
            },
            "required": []
        }
    },
    {
        "name": "start_render",
        "description": "Start rendering the render queue",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "clear_render_queue",
        "description": "Clear all items from the render queue",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    
    # ============ UI CONTROL ============
    {
        "name": "switch_page",
        "description": "Switch to a specific page in DaVinci Resolve",
        "parameters": {
            "type": "object",
            "properties": {
                "page": {
                    "type": "string",
                    "description": "Page name: media, cut, edit, fusion, color, fairlight, deliver"
                }
            },
            "required": ["page"]
        }
    },
    {
        "name": "get_current_page",
        "description": "Get the current page/workspace in DaVinci Resolve (media, cut, edit, fusion, color, fairlight, deliver)",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_timeline_info",
        "description": "Get information about the current timeline including tracks, clips, and duration",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_audio_info",
        "description": "Get detailed audio track information from the current timeline",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_video_info",
        "description": "Get detailed video track information from the current timeline",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
]


def get_tool_definitions() -> List[Dict[str, Any]]:
    """Get all tool definitions."""
    return TOOL_DEFINITIONS


def get_tool_names() -> List[str]:
    """Get a list of all tool names."""
    return [tool['name'] for tool in TOOL_DEFINITIONS]


def get_tool_by_name(name: str) -> Dict[str, Any]:
    """Get a tool definition by name."""
    for tool in TOOL_DEFINITIONS:
        if tool['name'] == name:
            return tool
    return None
