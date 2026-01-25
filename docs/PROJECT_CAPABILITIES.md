# DaVinci Resolve MCP Server - Complete Project Capabilities

**Version:** 1.3.8  
**Last Updated:** January 2026  
**Platform Support:** Windows (Stable), macOS (Stable), Linux (Not Supported)

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Core Architecture](#core-architecture)
3. [AI Chatbot Interface](#ai-chatbot-interface)
4. [MCP Tools & Resources](#mcp-tools--resources)
5. [Autonomous Features](#autonomous-features)
6. [Installed Plugins & Extensions](#installed-plugins--extensions)
7. [API Operations by Category](#api-operations-by-category)
8. [How to Use](#how-to-use)
9. [Configuration](#configuration)

---

## Project Overview

The **DaVinci Resolve MCP Server** is a Model Context Protocol (MCP) server that connects AI coding assistants (Cursor, Claude Desktop) to DaVinci Resolve Studio 20, enabling natural language control of the video editor.

### Key Features

- **97+ MCP Tools** for controlling DaVinci Resolve
- **AI-Powered Chatbot** with page-aware context
- **Autonomous Editing Features** (beat detection, scene detection, audio ducking)
- **Color Grading Presets** (Netflix, Cyberpunk, Teal-Orange, etc.)
- **AI Clip Analysis** using Google Gemini or OpenAI
- **External Plugin Integration** (Rembg-Fuse, DCTLs, Metafootage)

---

## Core Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      User Interfaces                            │
├─────────────────────────────────────────────────────────────────┤
│  Cursor IDE  │  Claude Desktop  │  AI Chatbot (tkinter)        │
└──────┬───────┴────────┬─────────┴──────────┬────────────────────┘
       │                │                     │
       ▼                ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MCP Server Layer                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  FastMCP Server │  │  Tool Router    │  │  Gemini Client  │  │
│  │  (JSON-RPC)     │  │  (97 Tools)     │  │  (Function Call)│  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
└───────────┼─────────────────────┼─────────────────────┼─────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API Layer                                    │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐        │
│  │ project_ops   │  │ timeline_ops  │  │ media_ops     │        │
│  │ color_ops     │  │ delivery_ops  │  │ color_presets │        │
│  └───────────────┘  └───────────────┘  └───────────────┘        │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│              DaVinci Resolve Scripting API                      │
│              (DaVinciResolveScript / fusionscript.dll)          │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   DaVinci Resolve Studio 20                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## AI Chatbot Interface

### Features

The standalone AI chatbot provides natural language control of DaVinci Resolve:

| Feature | Description |
|---------|-------------|
| **Page-Aware Context** | Automatically detects which page you're on (Edit, Color, Fusion, Fairlight, Deliver) |
| **Dark Theme UI** | Matches DaVinci Resolve's aesthetic |
| **Always-on-Top** | Float over Resolve while editing |
| **Function Calling** | AI can execute any of the 97 MCP tools |
| **Conversation History** | Maintains context across messages |
| **Real-time Updates** | Status bar shows current page and connection state |

### Page-Specific Help

| Page | AI Assistance |
|------|--------------|
| **Media** | Import files, organize bins, manage clips |
| **Cut** | Quick assembly editing |
| **Edit** | Timeline editing, clips, markers, effects |
| **Fusion** | Node-based effects, compositing tips |
| **Color** | Color grading presets, LUTs, CDL values |
| **Fairlight** | Audio mixing, beat detection, ducking |
| **Deliver** | Render settings, export formats, queue |

### Launch Methods

1. **Windows Batch Script:**
   ```batch
   scripts\launch-chatbot.bat
   ```

2. **Python Module:**
   ```bash
   cd C:\Users\Ruben\davinci-resolve-mcp
   python -m autonomous.chatbot.chat_window
   ```

3. **From DaVinci Resolve:**
   - Go to: `Workspace > Scripts > Edit > Resolve AI Chat`

### Requirements

- `GEMINI_API_KEY` environment variable set
- DaVinci Resolve running

---

## MCP Tools & Resources

### Project Management (8 tools)

| Tool | Description |
|------|-------------|
| `open_project(name)` | Open a project by name |
| `create_project(name)` | Create a new project |
| `save_project()` | Save the current project |
| `close_project()` | Close the current project |
| `list_projects` | List all available projects |
| `get_current_project_name` | Get current project name |
| `get_project_settings` | Get all project settings |
| `set_project_setting(name, value)` | Change a project setting |

### Timeline Operations (15 tools)

| Tool | Description |
|------|-------------|
| `create_timeline(name)` | Create a new timeline |
| `create_empty_timeline(name)` | Create an empty timeline |
| `delete_timeline(name)` | Delete a timeline |
| `set_current_timeline(name)` | Switch to a timeline |
| `list_timelines` | List all timelines |
| `get_current_timeline` | Get current timeline info |
| `add_marker(frame, color, name, note)` | Add a timeline marker |
| `delete_marker(frame)` | Remove a marker |
| `get_timeline_markers` | Get all markers |
| `add_beat_markers(audio_path)` | Add markers at beat positions |
| `add_scene_markers(video_path)` | Add markers at scene cuts |
| `get_timeline_tracks` | Get track structure |
| `add_track(type)` | Add video/audio track |
| `get_timeline_info` | Get timeline details |
| `duplicate_timeline(name)` | Copy a timeline |

### Media Pool Operations (12 tools)

| Tool | Description |
|------|-------------|
| `import_media(file_path)` | Import a media file |
| `list_bin_clips(bin_name)` | List clips in a bin |
| `add_clip_to_timeline(clip_name)` | Add clip to timeline |
| `add_clip_from_bin(clip, bin)` | Add specific clip from bin |
| `add_all_bin_clips_to_timeline(bin)` | Add all clips from bin |
| `create_bin(name)` | Create a new bin |
| `get_audio_clip_path(name)` | Get audio file path |
| `get_video_clip_path(name)` | Get video file path |
| `move_clips(clips, target_bin)` | Move clips between bins |
| `delete_clips(clips)` | Remove clips from pool |
| `get_clip_properties(name)` | Get clip metadata |
| `set_clip_property(name, prop, value)` | Set clip metadata |

### Color Grading Operations (10 tools)

| Tool | Description |
|------|-------------|
| `list_color_presets()` | List available presets |
| `apply_color_preset(preset, all)` | Apply a color preset |
| `apply_lut(lut_path)` | Apply a LUT file |
| `add_node()` | Add a color node |
| `delete_node(index)` | Remove a color node |
| `set_color_wheel_param(wheel, param, value)` | Adjust color wheels |
| `copy_grade(source, target)` | Copy grade between clips |
| `get_grade_versions()` | List grade versions |
| `create_grade_version(name)` | Create new version |
| `load_grade_version(name)` | Switch to version |

### Audio Operations (5 tools)

| Tool | Description |
|------|-------------|
| `analyze_audio_beats(path)` | Detect BPM and beat times |
| `add_beat_markers(path, color, max)` | Add markers at beats |
| `duck_audio_under_voiceover(vo, music, db)` | Auto-duck music |
| `get_audio_info()` | Get audio track details |
| `analyze_video_scenes(path)` | Detect scene changes |

### AI Analysis (3 tools)

| Tool | Description |
|------|-------------|
| `analyze_clip_with_ai(clip, provider)` | AI-powered clip analysis |
| `analyze_all_timeline_clips(provider)` | Batch AI analysis |
| `add_scene_markers(path, color, method)` | Add markers at scenes |

### Rendering Operations (5 tools)

| Tool | Description |
|------|-------------|
| `add_to_render_queue(preset, path)` | Add to render queue |
| `start_render()` | Start rendering |
| `clear_render_queue()` | Clear all render jobs |
| `get_render_presets()` | List render presets |
| `get_render_status()` | Check render progress |

### UI Control (4 tools)

| Tool | Description |
|------|-------------|
| `switch_page(page)` | Switch Resolve page |
| `get_current_page()` | Get current page |
| `load_layout_preset(name)` | Apply UI layout |
| `save_layout_preset(name)` | Save current layout |

---

## Autonomous Features

### Beat Analyzer (`src/autonomous/beat_analyzer.py`)

Analyzes audio files for tempo and beat positions using librosa.

**Capabilities:**
- Detect BPM (beats per minute)
- Get precise beat timestamps
- Calculate beat intervals
- Automatic marker placement at beat positions

**Usage:**
```python
from autonomous.beat_analyzer import BeatAnalyzer
analyzer = BeatAnalyzer()
result = analyzer.analyze("music.mp3")
print(f"BPM: {result.bpm}, Beats: {len(result.beat_times)}")
```

### Scene Detector (`src/autonomous/scene_detector.py`)

Detects scene changes in video files using PySceneDetect.

**Methods:**
- `adaptive` - Best for most content
- `content` - Based on content changes
- `threshold` - Simple threshold detection

**Outputs:**
- Scene start/end times
- Frame numbers
- Scene duration
- Thumbnail extraction support

### Audio Ducker (`src/autonomous/audio_ducker.py`)

Automatically ducks music volume when speech is detected.

**Features:**
- Voice Activity Detection (VAD)
- Configurable duck amount (dB)
- Fade in/out transitions
- Outputs new ducked audio file

**Workflow:**
1. Analyze voiceover for speech segments
2. Create volume envelope
3. Apply ducking to music
4. Export new audio file

### Clip Analyzer (`src/autonomous/clip_analyzer.py`)

AI-powered clip analysis using Google Gemini or OpenAI.

**Generated Metadata:**
- Description (what's happening)
- Keywords/tags
- Mood/emotion
- Shot type (wide, close-up, etc.)
- Color palette
- Technical quality notes

### Color Presets (`src/api/color_presets.py`)

Professional cinematic color grading presets using CDL values.

| Preset | Description |
|--------|-------------|
| `netflix` | Clean, neutral broadcast look |
| `teal-orange` | Classic Hollywood blockbuster |
| `cyberpunk` | High saturation neon colors |
| `music-video` | Punchy contrast, vibrant |
| `moody-dark` | Desaturated, crushed blacks |
| `vintage` | Warm, faded film look |
| `bleach-bypass` | Desaturated, silvery |
| `documentary` | Natural, subtle enhancement |
| `kodak-5219` | Film emulation |
| `arri-alexa` | ARRI camera look |

---

## Installed Plugins & Extensions

### Rembg-Fuse (AI Background Removal)

**Location:** `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Fuses\Rembg`

A Fusion plugin for AI-powered background removal using the rembg library.

**Usage in Fusion:**
1. Add a `Rembg` node after your MediaIn
2. Connect to Merge node for compositing
3. Adjust mask refinement as needed

### Moaz Elgabry DCTLs (Color Grading Tools)

**Location:** `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT`

Professional DCTLs for color grading:
- `ME_Filmic Contrast v1.3.dctl` - Film-like contrast
- `ME_Hue Curve v1.3.0.dctl` - Precise hue adjustments
- Additional color manipulation tools

**Usage:**
1. Go to Color page
2. Right-click on a node
3. LUTs > Select DCTL from list

### Metafootage Integration

**Location:** `C:\Users\Ruben\AppData\Roaming\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit\Metafootage_MCP.py`

AI-powered metadata generation for clips:
- Extracts frames from video
- Analyzes with Google Gemini
- Updates clip Comments and Keywords

**Usage:**
1. Select clips in Media Pool
2. Workspace > Scripts > Edit > Metafootage_MCP
3. Wait for AI analysis
4. Check clip metadata

---

## API Operations by Category

### Complete Tool Count by Category

| Category | Tool Count |
|----------|------------|
| Project Management | 8 |
| Timeline Operations | 15 |
| Media Pool | 12 |
| Color Grading | 10 |
| Audio | 5 |
| AI Analysis | 3 |
| Rendering | 5 |
| UI Control | 4 |
| Context/State | 4 |
| Utility | 31 |
| **Total** | **97** |

### Resources (Read-Only)

| Resource URI | Description |
|--------------|-------------|
| `resolve://version` | DaVinci Resolve version |
| `resolve://current-page` | Current active page |
| `resolve://projects` | List of all projects |
| `resolve://current-project` | Current project name |
| `resolve://timelines` | List of timelines |
| `resolve://current-timeline` | Current timeline info |
| `resolve://project-settings` | All project settings |
| `resolve://media-pool-clips` | Media pool contents |

---

## How to Use

### Starting the MCP Server

**Windows:**
```batch
scripts\run-now.bat
```

**Or manually:**
```batch
cd C:\Users\Ruben\davinci-resolve-mcp
.\venv\Scripts\activate
python src\main.py
```

### Cursor IDE Configuration

Add to `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "davinci-resolve": {
      "command": "C:\\Users\\Ruben\\davinci-resolve-mcp\\venv\\Scripts\\python.exe",
      "args": ["-u", "C:\\Users\\Ruben\\davinci-resolve-mcp\\src\\main.py"]
    }
  }
}
```

### Example Commands

**Natural Language (via Chatbot or Cursor):**

```
"Create a timeline called My Edit"
"Add all clips from the Rich Bitch bin to the timeline"
"Apply the cyberpunk color preset"
"Analyze the music for beats and add markers"
"Switch to the Color page"
"List all clips in the media pool"
"Apply a Netflix look to all clips"
"Duck the background music when there's dialogue"
```

---

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GEMINI_API_KEY` | Google Gemini API key | For AI features |
| `OPENAI_API_KEY` | OpenAI API key | Alternative AI |
| `RESOLVE_SCRIPT_API` | Resolve API path | Auto-detected |
| `RESOLVE_SCRIPT_LIB` | Resolve library path | Auto-detected |

### File Locations

| File | Purpose |
|------|---------|
| `src/main.py` | Main entry point |
| `src/resolve_mcp_server.py` | MCP server with all tools |
| `src/autonomous/chatbot/` | AI chatbot package |
| `src/api/` | API operation modules |
| `scripts/launch-chatbot.bat` | Chatbot launcher |
| `.cursor/mcp.json` | Cursor configuration |

---

## Version History

| Version | Changes |
|---------|---------|
| 1.3.8 | AI Chatbot with page-aware context |
| 1.3.7 | Audio ducking, clip analyzer |
| 1.3.6 | Beat detection, scene detection |
| 1.3.5 | Color presets integration |
| 1.3.4 | Recursive media pool search |
| 1.3.3 | Windows support stabilization |

---

## Support & Resources

- **Project Repository:** `C:\Users\Ruben\davinci-resolve-mcp`
- **Documentation:** `docs/` folder
- **Examples:** `examples/` folder
- **Scripts:** `scripts/` folder

---

*This document provides a complete overview of the DaVinci Resolve MCP Server capabilities. For detailed API documentation, see `docs/TOOLS_README.md` and `docs/FEATURES.md`.*
