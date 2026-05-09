# DaVinci Resolve MCP Demo Video Gameplan

This packet is a practical plan for creating a demo video that shows what the
DaVinci Resolve MCP can do, why the newer kernel tools matter, and where the
public Resolve API boundary actually sits.

The strongest demo is not "an AI edits a film by magic." The strongest demo is:
an assistant can inspect Resolve state, plan safely, dry-run risky operations,
make precise changes, explain what happened, and stop at public API limits
without touching source media.

## Core Message

**DaVinci Resolve MCP turns Resolve into a scriptable, inspectable, agent-ready
post-production workspace.**

The video should prove four ideas:

1. The assistant can see real Resolve project state.
2. The assistant can perform useful edit, ingest, review, color, Fusion, audio,
   project, and render workflows.
3. The kernel actions add safety: probe first, dry-run where possible, mutate
   only when the target state is known.
4. The MCP is honest about limits: when Blackmagic does not expose something
   through the public API, the MCP reports the boundary instead of pretending.

## Recommended Deliverables

| Deliverable | Duration | Purpose |
|-------------|---------:|---------|
| Launch cut | 90 seconds | Fast product overview for GitHub/social sharing |
| Hero walkthrough | 7-9 minutes | Main demo showing the practical workflow end to end |
| Deep dive chapters | 3-5 minutes each | Optional clips for each kernel surface |
| Boundary clip | 60-90 seconds | Shows trustworthy failure modes and public API limits |

## Demo Environment

Use only disposable projects and synthetic or explicitly approved demo media.
Never use client source media for the demo.

Suggested workspace:

```bash
/tmp/resolve-mcp-demo/
  media/
  analysis/
  exports/
  extension-work/
  screenshots/
```

Suggested Resolve project:

```text
_mcp_demo_potential_YYYYMMDD
```

Suggested timeline:

```text
MCP Demo - Hero Walkthrough
```

## Synthetic Material Kit

These are safe because they create brand-new synthetic demo assets. They do not
read, modify, transcode, proxy, or derive from source media.

| Material | Suggested File | Use |
|----------|----------------|-----|
| Color-bar video with audio | `demo_scene_a.mov` | Ingest, timeline, render, color |
| Test-pattern video | `demo_scene_b.mov` | Duplicate, copy range, conform |
| Audio-only WAV | `demo_dialogue_ref.wav` | Audio mapping, auto-sync dry-run, transcription planning |
| Still image | `demo_still.png` | Media Pool import and organization |
| Short PNG sequence | `sequence/demo_seq_%03d.png` | Image sequence import |
| Tiny LUT/DCTL/script text | In `extension-work/` | Extension lifecycle demo |

Optional FFmpeg recipes:

```bash
mkdir -p /tmp/resolve-mcp-demo/media/sequence /tmp/resolve-mcp-demo/analysis /tmp/resolve-mcp-demo/exports /tmp/resolve-mcp-demo/extension-work

ffmpeg -y -f lavfi -i testsrc2=size=1920x1080:rate=24:duration=8 -f lavfi -i sine=frequency=440:duration=8 -c:v prores_ks -profile:v 3 -c:a pcm_s16le /tmp/resolve-mcp-demo/media/demo_scene_a.mov

ffmpeg -y -f lavfi -i smptebars=size=1920x1080:rate=24:duration=8 -f lavfi -i sine=frequency=660:duration=8 -c:v prores_ks -profile:v 3 -c:a pcm_s16le /tmp/resolve-mcp-demo/media/demo_scene_b.mov

ffmpeg -y -f lavfi -i sine=frequency=880:duration=8 -c:a pcm_s16le /tmp/resolve-mcp-demo/media/demo_dialogue_ref.wav

ffmpeg -y -f lavfi -i color=c=0x20242a:size=1920x1080:duration=1 -frames:v 1 /tmp/resolve-mcp-demo/media/demo_still.png

ffmpeg -y -f lavfi -i testsrc=size=1280x720:rate=24:duration=1 -frames:v 12 /tmp/resolve-mcp-demo/media/sequence/demo_seq_%03d.png
```

## Hero Walkthrough

| Beat | Duration | Promise | Visual Proof | MCP Surface |
|------|---------:|---------|--------------|-------------|
| Cold open | 20 sec | "Resolve is now agent-operable." | Split screen: prompt, tool result, Resolve UI changing | `resolve_control`, `timeline` |
| Project setup | 45 sec | Create disposable project and verify environment | Project Manager and Media Pool state | `project_manager`, `project_settings` |
| Safe ingest | 60 sec | Import and organize synthetic media without touching source | Media Pool bins, metadata report | `media_pool`, `media_storage` |
| Assembly edit | 75 sec | Build timeline, duplicate clips, copy range, include linked audio | Edit page timeline before/after | `timeline`, `timeline_item` |
| Review pass | 60 sec | Add/copy markers and export review summary | Timeline markers, report output | `timeline_markers`, `timeline_item_markers` |
| Conform intelligence | 60 sec | Detect gaps, source ranges, missing media, export plan | Gap report and FCPXML/EDL plan | `timeline` conform kernel |
| Color and Fusion | 75 sec | Snapshot grade, apply safe CDL, add Fusion text overlay | Color page, Fusion graph, overlay | `timeline_item_color`, `fusion_comp` |
| Audio/Fairlight | 45 sec | Inspect mapping, voice isolation, transcription/subtitle support | Audio report, track/item state | `timeline` audio kernel |
| Render planning | 45 sec | Validate settings and queue safely without surprise renders | Deliver settings and queued job | `render` |
| Extension authoring | 45 sec | Generate/probe a script or DCTL lifecycle | Lifecycle report, refresh/restart classification | `script_plugin`, `dctl`, `fuse_plugin` |
| Boundary honesty | 45 sec | Show unsupported API limits clearly | "Not supported by public API" report | kernel boundary reports |
| Close | 20 sec | MCP is a trustworthy post-production operating layer | Feature/action coverage graphic | README kernel coverage |

## Sample Prompt Pack

Use these as on-camera prompts. They are written to make the assistant show its
reasoning and use safe kernel actions instead of raw destructive calls.

### 1. Environment Smoke Test

```text
Check that DaVinci Resolve is connected. Tell me the Resolve version, current
page, current project, current timeline, and which MCP kernel surfaces are most
useful for a safe demo.
```

Expected visual:

- Resolve version and page report.
- No mutation yet.
- Assistant says it will use a disposable `_mcp_demo_*` project.

### 2. Disposable Project Setup

```text
Create a disposable project named _mcp_demo_potential_YYYYMMDD. Keep this demo
self-contained. Before changing settings, snapshot the current project settings
and tell me what will be restored or left alone.
```

Expected MCP surfaces:

- `project_manager.safe_project_create`
- `project_manager.project_settings_snapshot`
- `project_manager.project_boundary_report`

On-screen label:

```text
Probe first. Mutate only inside disposable project.
```

### 3. Safe Ingest And Organization

```text
Import the synthetic demo media from /tmp/resolve-mcp-demo/media. Dry-run first,
then import the video, WAV, still, and image sequence into organized bins named
Video, Audio, Stills, and Sequences. Normalize clip metadata with scene and demo
tags.
```

Expected MCP surfaces:

- `media_pool.safe_import_media`
- `media_pool.safe_import_sequence`
- `media_pool.safe_import_folder`
- `media_pool.organize_clips`
- `media_pool.normalize_metadata`
- `media_pool.media_pool_boundary_report`

Visual proof:

- Media Pool bins appear.
- Clips have metadata.
- No source media derivatives are created.

### 4. Assembly Edit Kernel

```text
Create a timeline called "MCP Demo - Hero Walkthrough". Append the two video
clips, then duplicate the first clip to the track above with linked audio. Copy
a two-second range from the second clip later in the timeline. Show me the
before and after item IDs.
```

Expected MCP surfaces:

- `media_pool.create_timeline_from_clips`
- `timeline.duplicate_clips`
- `timeline.copy_range`
- `timeline.probe_edit_kernel_item`

Visual proof:

- Edit page before/after.
- Track above placement.
- Linked audio remains attached when supported.

### 5. Timeline State Copy

```text
Take the selected timeline item and copy its transform, crop, composite,
markers, flags, clip color, enabled state, and keyframes to the duplicate where
Resolve exposes those properties. Report any groups that are only partially
supported.
```

Expected MCP surfaces:

- `timeline.duplicate_clips` with `copy_properties`
- `timeline.edit_kernel_capabilities`
- `timeline.probe_edit_kernel_item`

Visual proof:

- The duplicate inherits visible transform/color/marker state.
- Unsupported groups are reported cleanly.

### 6. Review Annotation Layer

```text
Add timeline review markers for "Check color", "Check sync", and "Ready for
export". Copy the relevant review marker to the selected timeline item, then
export a review report.
```

Expected MCP surfaces:

- `timeline_markers.normalize_marker_payload`
- `timeline_markers.copy_annotations`
- `timeline_markers.export_review_report`
- `timeline_markers.annotation_boundary_report`

Visual proof:

- Markers visible in Resolve.
- Report includes marker names, notes, colors, and frame/timecode positions.

### 7. Conform And Interchange Intelligence

```text
Inspect this timeline like an online editor. Detect gaps and overlaps, report
source frame ranges with handles, check for missing media, then dry-run an FCPXML
export and summarize what should survive the round trip.
```

Expected MCP surfaces:

- `timeline.probe_timeline_structure`
- `timeline.detect_gaps_overlaps`
- `timeline.source_range_report`
- `timeline.detect_missing_media`
- `timeline.export_timeline_checked`
- `timeline.conform_boundary_report`

Visual proof:

- Clear gap/source-range table.
- Export path points to `/tmp/resolve-mcp-demo/exports`.

### 8. Audio And Fairlight Probe

```text
Inspect audio track 1 and the first audio timeline item. Report channel mapping,
audio item properties, voice isolation availability, transcription availability,
and whether subtitle generation is supported in this Resolve state. Dry-run any
operation that would modify sync or generate subtitles.
```

Expected MCP surfaces:

- `timeline.probe_audio_track`
- `timeline.probe_audio_item`
- `timeline.audio_mapping_report`
- `timeline.voice_isolation_capabilities`
- `timeline.transcription_capabilities`
- `timeline.subtitle_generation_probe`

Visual proof:

- Fairlight or Edit page with audio track.
- Report explains availability without surprise generation.

### 9. Color Grade Probe

```text
Snapshot the selected clip's grade state. Validate this CDL: slope 1.05 1.0
0.95, offset 0 0 0, power 1 1 1, saturation 1.1. Apply it only if validation
passes, then export a temporary LUT to /tmp/resolve-mcp-demo/exports.
```

Expected MCP surfaces:

- `timeline_item_color.grade_capabilities`
- `timeline_item_color.probe_grade_item`
- `timeline_item_color.safe_set_cdl`
- `timeline_item_color.safe_export_lut`
- `timeline_item_color.grade_boundary_report`

Visual proof:

- Color page grade change.
- LUT export report.
- Any Gallery/DRX page dependency is documented.

### 10. Fusion Text Overlay

```text
Add a Fusion composition to the selected clip. Create a TextPlus overlay that
says "MCP-controlled Resolve", connect the graph safely, set readable text
styling, and report the Fusion graph before and after.
```

Expected MCP surfaces:

- `timeline_item_fusion.add_comp`
- `fusion_comp.fusion_graph_capabilities`
- `fusion_comp.safe_add_tool`
- `fusion_comp.safe_set_inputs`
- `fusion_comp.safe_connect_tools`
- `fusion_comp.fusion_boundary_report`

Visual proof:

- Text overlay appears.
- Fusion node graph is inspectable.

### 11. Render Planning

```text
Build a render plan for ProRes 422 HQ or the closest supported codec on this
machine. Validate settings, require a temp target under /tmp/resolve-mcp-demo,
queue a job, report job status, and do not start rendering unless I explicitly
approve it.
```

Expected MCP surfaces:

- `render.render_capabilities`
- `render.probe_render_matrix`
- `render.validate_render_settings`
- `render.prepare_render_job`
- `render.render_job_lifecycle_probe`
- `render.export_render_boundary_report`

Visual proof:

- Deliver page or render queue.
- The assistant distinguishes queueing from rendering.

### 12. Extension Authoring Boundary

```text
Create a tiny MCP-marked Resolve script or DCTL from a template, validate it,
dry-run install first, then install and remove it if safe. Tell me whether this
kind of extension requires Resolve restart, LUT refresh, or menu refresh.
```

Expected MCP surfaces:

- `script_plugin.extension_capabilities`
- `script_plugin.probe_script_lifecycle`
- `script_plugin.safe_install_extension`
- `script_plugin.safe_remove_extension`
- `script_plugin.refresh_or_restart_required`
- `script_plugin.extension_boundary_report`

Visual proof:

- Lifecycle report.
- Clear refresh/restart classification.
- MCP marker and `_mcp_` naming guard are visible in the explanation.

### 13. Boundary Honesty Moment

```text
Try to answer this like a responsible assistant: can you clone transitions,
perform an exact razor split, or deep-inspect opaque speed-ramp curves through
the public Resolve scripting API? Show the relevant boundary report rather than
guessing.
```

Expected MCP surfaces:

- `timeline.edit_kernel_capabilities`
- `timeline.conform_boundary_report`
- Other boundary reports as relevant

Visual proof:

- The assistant says what is unsupported and why.
- This builds trust more than a perfect-looking demo.

## Modular Use Cases By Audience

| Audience | Best Demo Chapters | Why It Lands |
|----------|--------------------|--------------|
| Assistant editor | Safe ingest, metadata, timeline duplication, review markers, conform reports | Saves repetitive prep and keeps media discipline intact |
| Editor | Assembly edits, copy range, marker workflows, Fusion temp overlays | Shows creative iteration without leaving Resolve |
| Online editor | Source ranges, gaps/overlaps, missing media, interchange exports, relink plans | Demonstrates conform awareness and auditability |
| Colorist | Grade snapshots, CDL validation, LUT export, Gallery/color-group capability reports | Shows controlled color operations and honest page dependencies |
| Sound/Fairlight | Audio mapping, voice isolation checks, transcription/subtitle probes | Shows sound-aware timeline inspection |
| Post supervisor | Project lifecycle, archive guards, render planning, reports | Shows operational safety and repeatability |
| Developer | Full API coverage, kernel action coverage, extension authoring lifecycle | Shows the platform angle and expansion path |

## On-Screen Graphics Kit

Use restrained, readable overlays. This is a professional tool demo, not a hype
reel.

Suggested recurring labels:

```text
Connected to Resolve
Probe first
Dry-run available
Disposable project
Public API boundary
No source media derivatives
109 guarded kernel actions
30 compound MCP tools
328 full-mode granular tools
```

Suggested graphic moments:

- A small status strip at the bottom: `Prompt -> MCP action -> Resolve result`.
- Callout boxes around the changed Resolve UI region.
- A before/after split for timeline edits.
- A simple action coverage card using the README kernel table.
- A red/amber/green status chip for unsupported, partial, supported.

## B-Roll And Capture Checklist

Capture these clean plates:

- Resolve Project Manager with disposable `_mcp_demo_*` project.
- Media Pool before import.
- Media Pool after organized bins.
- Edit page before/after timeline assembly.
- Timeline marker close-up.
- Color page before/after CDL.
- Fusion page with TextPlus graph.
- Deliver page or render queue with queued job.
- Codex prompt/result panel for each key prompt.
- A terminal or repo shot showing `README.md` kernel coverage, if useful.

Recommended capture style:

- Record at 16:9, 1920x1080 or 3840x2160.
- Keep Codex and Resolve side by side for the hero moments.
- Zoom in only for tool output or marker/graph details.
- Use callouts in edit rather than moving the screen recording constantly.

## Voiceover Spine

Use this as the narration backbone:

```text
This is DaVinci Resolve controlled through MCP.

The important part is not just that the assistant can click buttons or run
scripts. It can ask Resolve what state it is in, choose the right public API
surface, dry-run risky changes, and report what is actually supported.

Here we create a disposable project, import synthetic media, build a small
timeline, duplicate linked clips, copy a range, add review markers, inspect
conform risk, probe audio, apply a validated CDL, add a Fusion overlay, and
prepare a render job.

Every step is inspectable. Every risky operation is scoped. And when the public
Resolve API does not expose something, the MCP says so.

That is the real potential: an AI assistant that behaves like a careful post
production operator, not a black box.
```

## Safety And Credibility Rules

- Use synthetic or explicitly approved demo media only.
- Keep all project names prefixed with `_mcp_demo_` or `_mcp_`.
- Use `/tmp/resolve-mcp-demo` or another disposable target for generated demo
  files, analysis sidecars, exports, and extension work.
- Dry-run first for ingest, render, relink, project, and extension workflows
  where dry-run is available.
- Do not render, archive, restore, delete, relink, or install extensions without
  stating the target and showing the guard.
- Include one honest unsupported-boundary moment.

## Live Rehearsal Checklist

Before recording:

1. Launch DaVinci Resolve Studio.
2. Confirm external scripting is set to Local.
3. Confirm the MCP client is connected.
4. Create or clear `/tmp/resolve-mcp-demo`.
5. Generate synthetic media.
6. Run the environment smoke prompt.
7. Run the project setup prompt.
8. Run the full hero sequence once without recording.
9. Confirm cleanup paths and no client media are referenced.
10. Record the second pass.

After recording:

1. Delete disposable `_mcp_demo_*` projects if no longer needed.
2. Remove temp render jobs.
3. Remove `_mcp_` extension test files.
4. Keep only final screen recordings and any intentional exports.

## Optional Deep-Dive Chapters

These can become separate videos or appendix clips:

| Chapter | Prompt Theme |
|---------|--------------|
| "The edit kernel" | Duplicate, copy range, linked audio, state copying, unsupported razor/split boundary |
| "The ingest kernel" | Safe import, folder organization, metadata, relink/proxy guardrails |
| "The render kernel" | Format/codec matrix, validation, queue lifecycle, Quick Export guard |
| "The review kernel" | Marker normalization, custom data, copy/move, review report export |
| "The color kernel" | Grade snapshots, CDL validation, LUT export, Gallery/page boundaries |
| "The Fusion kernel" | Timeline-item comp targeting, node creation, input writes, graph report |
| "The conform kernel" | Gap/overlap detection, source ranges, interchange round trip |
| "The audio kernel" | Mapping, voice isolation, transcription, subtitle probe |
| "Project lifecycle" | Disposable create/export/import/archive/settings/database dry-runs |
| "Extension authoring" | Fuse/DCTL/script templates, lifecycle probes, restart/refresh classification |

## Short Trailer Script

For a 90-second cut:

1. Open with Resolve and Codex side by side.
2. Say: "This is Resolve exposed through MCP: 30 compound tools, full API
   coverage, and 109 guarded workflow actions."
3. Show project setup and ingest in 10 seconds.
4. Show timeline duplication and markers in 20 seconds.
5. Show conform report and boundary honesty in 15 seconds.
6. Show color/Fusion/render planning in 25 seconds.
7. End on: "The point is not magic. The point is control, inspection, and safe
   automation inside a real post-production app."

## Final Demo Success Criteria

The demo is ready to publish when:

- A viewer can name at least three concrete Resolve tasks the MCP performed.
- The safety model is visible: probe, dry-run, scoped mutation, cleanup.
- The demo shows more than one page of Resolve.
- The prompt/result loop is readable on screen.
- The video does not imply unsupported features are supported.
- No real source media or client assets appear in the recording.
