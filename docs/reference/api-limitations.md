# DaVinci Resolve Scripting API — Limitations & Feedback

<!-- GENERATED FILE — do not edit by hand.
     Source: src/utils/api_truth.py (entries tagged `submit`).
     Regenerate: venv/bin/python scripts/gen_api_limitations.py -->

This is a curated, behaviorally-verified list of DaVinci Resolve scripting
API gaps and bugs encountered while building this MCP server, intended for
submission to Blackmagic Design's developer feedback. Every item was
observed against live Resolve; each entry notes the current workaround (or
that none exists).

**Verified on:** DaVinci Resolve Studio 21.0.0

**Totals:** 18 missing capabilities, 11 bugs / unreliable behaviors.

The authoritative source is the runtime-queryable `api_truth` ledger
(`resolve_control api_truth "<query>"`); this document is generated from
it and stays in sync via a drift guard.

### Scope & completeness

This list is **not guaranteed exhaustive.** It combines (a) issues hit
while building this MCP server, (b) a `dir()` surface audit of the live
Resolve API objects (ProjectManager, Project, MediaPool, MediaPoolItem,
Timeline, TimelineItem, Graph) diffed against Resolve's UI feature set,
and (c) a live mutating harness (`tests/live_api_gap_verification.py`)
that attempts each operation against a disposable project built from
synthetic media and confirms it fails while a related control succeeds.
That catches absent methods and documented constraints, but not subtler
issues: parameters that exist yet misbehave, version-specific regressions,
or capabilities we simply never exercised. New findings are added as
`submit`-tagged `api_truth` entries and this document is regenerated.

Note: `hasattr()`/`getattr()` cannot be used to probe this API — the
Python bridge fabricates a callable for any attribute name (see the
`hasattr` bug below). Method existence here was checked with `dir()`.

## Missing Capabilities (please add)

Functionality that exists in the Resolve UI but has no scripting API
equivalent, blocking full automation.

### Timeline.GetTimelineByName

- **Object:** `Project`
- **Behavior:** Does not exist. Timelines are looked up by index.
- **Workaround / current handling:** Iterate GetTimelineByIndex(1..GetTimelineCount()).
- **Tags:** missing-method, timeline

### Source Track Selector / destination track for Insert*IntoTimeline

- **Object:** `Timeline`
- **Behavior:** There is no API to read or set the Source/Auto Track Selector (the Edit-page patch panel that picks the destination track). InsertTitleIntoTimeline, InsertFusionTitleIntoTimeline, InsertGeneratorIntoTimeline, InsertFusionGeneratorIntoTimeline, InsertOFXGeneratorIntoTimeline and InsertFusionCompositionIntoTimeline take no trackIndex and always drop the clip on the selector's current target (V1 in practice). Locking lower video tracks does NOT redirect the insert — verified live on 21.0.0: locking V1 makes the insert FAIL rather than land on V2. Titles/generators also can't be moved afterward (no MediaPoolItem, so AppendToTimeline clipInfo and MoveClips don't apply).
- **Workaround / current handling:** Accept the limitation for titles/generators (insert lands on V1). For clips that DO have a MediaPoolItem, target a track with MediaPool.AppendToTimeline's clipInfo 'trackIndex' instead (exposed as media_pool append_to_timeline clip_infos). See issue #74.
- **Reference:** [issue #74](https://github.com/samuelgursky/davinci-resolve-mcp/issues/74)
- **Tags:** missing-method, timeline, title, generator, track

### Per-clip audio channel-format conversion (Stereo<->Mono)

- **Object:** `MediaPoolItem / TimelineItem`
- **Behavior:** No scripting method converts an individual clip's audio channel format. ConvertTimelineToStereo is timeline-wide, and CreateStereoClip builds a 3D *visual* stereoscopic clip, not an audio mono->stereo change. The Edit-page 'Clip Attributes > Audio' channel mapping is UI-only.
- **Workaround / current handling:** Use the supported surface: timeline add_track with audioType (create mono/stereo tracks), get_track_sub_type (query format), convert_to_stereo (timeline-wide), and timeline_item get_source_audio_channel_mapping. Per-clip conversion is not possible. See issue #73.
- **Reference:** [issue #73](https://github.com/samuelgursky/davinci-resolve-mcp/issues/73)
- **Tags:** missing-method, audio, channel

### Native multicam clip creation

- **Object:** `MediaPool`
- **Behavior:** There is no method to create a native multicam clip from a set of angles. Angles can be stacked onto tracks programmatically, but the multicam-clip conversion is a UI-only step.
- **Workaround / current handling:** Prepare a stacked timeline (media_pool setup_multicam_timeline) and finish the multicam-clip conversion in the Resolve UI.
- **Tags:** missing-method, media-pool, multicam

### Transition create / copy / clone

- **Object:** `Timeline / TimelineItem`
- **Behavior:** The scripting API exposes no method to add, read, copy, or clone an edit transition (cross-dissolve, etc.). Transitions applied in the UI are invisible to and unmodifiable by scripts.
- **Workaround / current handling:** Apply/duplicate transitions in the Resolve UI; no scripted equivalent exists.
- **Tags:** missing-method, timeline, transition

### Cloud project enumeration / export / user management

- **Object:** `ProjectManager`
- **Behavior:** Only CreateCloudProject, LoadCloudProject, ImportCloudProject and RestoreCloudProject exist. There is no GetCloudProjectList (list available cloud projects), no ExportToCloud, and no Add/RemoveUserToCloudProject — so cloud collaboration can't be fully automated.
- **Workaround / current handling:** Drive cloud project listing, export, and collaborator management from the Resolve UI; only create/load/import/restore are scriptable.
- **Tags:** missing-method, project, cloud

### TimelineItem trim / move / re-time (no position setters)

- **Object:** `TimelineItem`
- **Behavior:** TimelineItem exposes GetStart, GetEnd, GetDuration, GetLeftOffset, GetRightOffset and GetSourceStart/EndFrame, but NO matching setters. A clip cannot be trimmed, slipped, slid, rolled, moved to another time/track, or have its duration changed once it is on the timeline. Verified via dir() on Resolve 21.0.0 (getters only).
- **Workaround / current handling:** Do edit-point adjustments in the Resolve UI, or rebuild the timeline from MediaPool.AppendToTimeline clipInfos with the desired startFrame/endFrame/recordFrame.
- **Tags:** missing-method, timeline, edit, trim

### Razor / blade / split a timeline item

- **Object:** `Timeline / TimelineItem`
- **Behavior:** There is no method to split/cut/blade a clip at a given frame. Verified absent on Timeline and TimelineItem (dir(), 21.0.0).
- **Workaround / current handling:** Split in the Resolve UI, or construct the cut up-front by appending two clipInfos with the desired in/out points.
- **Tags:** missing-method, timeline, edit

### Clip speed / retime ratio and speed ramps

- **Object:** `TimelineItem`
- **Behavior:** SetProperty exposes only retime *quality* (RetimeProcess, MotionEstimation) and transform/crop/composite/opacity keys — not the speed value itself. There is no way to set a clip to a given % speed, reverse it, or author a speed ramp. Verified against the documented SetProperty key list AND by live mutating attempt on 21.0.0: SetProperty('Speed'|'PlaybackSpeed'|'RetimeSpeed'|'ClipSpeed', 50) all return False, while SetProperty('RetimeProcess', 1) returns True.
- **Workaround / current handling:** Set clip speed/retime in the Resolve UI; no scripted equivalent exists.
- **Tags:** missing-method, timeline, retime, speed

### Color node graph editing and primary grade values

- **Object:** `Graph / TimelineItem`
- **Behavior:** The Graph object exposes node enable/label/count, LUT get/set, cache mode, ResetAllGrades, ApplyGradeFromDRX and ApplyArriCdlLut; TimelineItem adds SetCDL, CopyGrades and color versions. But you cannot add, delete, or connect nodes, and you cannot read or write primary grade values (lift/gamma/gain/offset/contrast/curves/qualifiers/power windows). Grading is limited to CDL, whole-grade DRX/LUT application and copying.
- **Workaround / current handling:** Build node trees and dial grades in the Resolve UI or via DRX/CDL/LUT import; per-parameter grade control is not scriptable.
- **Tags:** missing-method, color, grade, node

### Fairlight audio levels / pan / EQ / automation / FairlightFX

- **Object:** `TimelineItem / Timeline`
- **Behavior:** There is no API to set clip or track volume, pan, EQ, audio automation, or to add/configure FairlightFX. SetProperty covers video transform only; the audio surface is read-only (GetSourceAudioChannelMapping, GetAudioMapping, voice isolation). Verified via dir() + SetProperty docs AND by live mutating attempt on 21.0.0: SetProperty('Volume'|'Level'|'Gain'|'AudioVolume', 0) all return False (note 'Pan' is the VIDEO transform key, not audio pan, so it misleadingly succeeds).
- **Workaround / current handling:** Mix in the Fairlight UI; only voice-isolation state and channel-mapping reads are scriptable.
- **Tags:** missing-method, audio, fairlight

### Proxy / optimized-media generation

- **Object:** `MediaPoolItem`
- **Behavior:** Only LinkProxyMedia, UnlinkProxyMedia and LinkFullResolutionMedia exist (attach/detach EXISTING proxies). There is no method to generate proxies or optimized media. Verified via MediaPoolItem dir() (21.0.0).
- **Workaround / current handling:** Trigger proxy/optimized-media generation from the Resolve UI; scripting can only link/unlink already-rendered proxies.
- **Tags:** missing-method, media-pool, proxy

### Insert / Overwrite / Replace / Fit-to-Fill edit modes

- **Object:** `MediaPool / Timeline`
- **Behavior:** MediaPool.AppendToTimeline (with optional recordFrame positioning) is the only programmatic placement. The standard edit modes — insert (ripple), overwrite, replace, fit-to-fill, place-on-top — have no API. Verified via dir() (21.0.0).
- **Workaround / current handling:** Position clips with AppendToTimeline clipInfo recordFrame, or perform insert/overwrite/replace edits in the Resolve UI.
- **Tags:** missing-method, timeline, edit

### Smart Bins / Power Bins creation

- **Object:** `MediaPool`
- **Behavior:** Only AddSubFolder (a regular bin) exists. Smart Bins (rule-based) and Power Bins (cross-project) cannot be created or configured. Verified via MediaPool dir() (21.0.0).
- **Workaround / current handling:** Create Smart/Power Bins in the Resolve UI; only regular bins are scriptable.
- **Tags:** missing-method, media-pool, bins

### Per-subtitle text content and timing editing

- **Object:** `TimelineItem (subtitle track)`
- **Behavior:** TimelineItem on a subtitle track exposes only 21 standard transform/composite properties (Pan, Tilt, ZoomX, Opacity, Crop, etc.). There are no methods to get or set subtitle text (GetText/SetText), start time, end time, or duration for individual subtitle items. Subtitles created via CreateSubtitlesFromAudio or imported via the Resolve UI cannot have their content or timing read or modified programmatically. Verified via dir() and GetProperty() on Resolve 21.0.0.48.
- **Workaround / current handling:** No workaround exists — subtitle text and timing are completely inaccessible from the scripting API. Must be edited in the Resolve UI.
- **Tags:** missing-method, subtitle, text, timing

### Subtitle track styling and presets

- **Object:** `TimelineItem / Timeline / Project`
- **Behavior:** There is no API method to set or query subtitle font family, font size, text color, background color, outline, shadow, position, alignment, or to apply/query subtitle style presets. TimelineItem.GetProperty() on subtitle items returns only transform/composite keys. Timeline.GetSetting() and Project.GetSetting() return None for all probed subtitle-style keys (e.g. 'subtitleFontName', 'subtitleFontSize', 'subtitleTextColor', 'subtitleBackgroundColor', 'subtitlePosition', 'subtitleAlignment', 'subtitlePreset', 'subtitleStyle'). Verified via dir(), GetProperty(), and GetSetting() on Resolve 21.0.0.48.
- **Workaround / current handling:** No workaround exists — subtitle styling is UI-only. Burn-in overlays via Fusion titles are a visual alternative but do not produce proper subtitle tracks.
- **Tags:** missing-method, subtitle, style, preset

### Speech recognition engine selection and SRT import

- **Object:** `Timeline`
- **Behavior:** Timeline.CreateSubtitlesFromAudio(autoCaptionSettings) always uses the built-in Resolve speech recognition engine. There is no API parameter to select an alternative provider (e.g. whisper-cli, Google Speech, AWS Transcribe). The language selection via resolve.AUTO_CAPTION_LANGUAGE_* is the only customization; the engine itself cannot be changed. Furthermore, there is no API method to import an SRT file into a subtitle track programmatically — File -> Import -> Subtitle is UI-only.
- **Workaround / current handling:** No workaround exists for provider selection or SRT import. External transcripts must be converted to SRT and imported through the Resolve UI.
- **Tags:** missing-method, subtitle, transcription, speech-recognition, asr

### Media Pool folder rename

- **Object:** `MediaPool`
- **Behavior:** MediaPool exposes AddSubFolder(name), DeleteSubFolders([names]), and MoveFolders([names], targetFolder) but no RenameSubFolder(oldName, newName) method. Folders can be created, deleted, and moved, but their names cannot be changed through the API. Verified via dir() on Resolve 21.0.0.
- **Workaround / current handling:** Delete and recreate the folder with the desired name, or rename in the Resolve UI.
- **Tags:** missing-method, media-pool, folder

## Bugs / Unreliable Behavior (please fix)

Methods that exist but misbehave — silent failures, unreliable return
values, or automation-hostile modal prompts.

### MediaPool.AutoSyncAudio

- **Object:** `MediaPool`
- **Signature:** `(clips, settings) -> bool`
- **Behavior:** The boolean return does not reflect whether clips actually linked, and string enum keys in `settings` are silently rejected (the call returns False).
- **Workaround / current handling:** Resolve the AUDIO_SYNC_* enum constants via the live resolve handle, and verify by reading each clip's 'Synced Audio' property (see verify_by_readback).
- **Tags:** unreliable-return, silent-failure, audio, enum

### Timeline.CreateSubtitlesFromAudio

- **Object:** `Timeline`
- **Signature:** `(autoCaptionSettings) -> bool`
- **Behavior:** Same failure mode as AutoSyncAudio: the autoCaptionSettings dict is keyed by resolve.SUBTITLE_* enum constants with resolve.AUTO_CAPTION_* enum values, so plain string keys like {'language': 'korean'} are silently rejected (returns False, no subtitle track created). The boolean is also unreliable.
- **Workaround / current handling:** Resolve the SUBTITLE_*/AUTO_CAPTION_* constants via the live resolve handle (server._normalize_auto_caption_settings) and verify by reading the timeline's subtitle track count before/after (server._safe_create_subtitles).
- **Tags:** unreliable-return, silent-failure, subtitle, enum

### ProjectManager CloudProject family (Create/Load/Import/RestoreCloudProject)

- **Object:** `ProjectManager`
- **Signature:** `(..., cloudSettings) -> Project | bool`
- **Behavior:** All four take an enum-keyed {cloudSettings} dict (resolve.CLOUD_SETTING_* keys, resolve.CLOUD_SYNC_* sync-mode values). Plain string keys are silently rejected, so a settings dict built from human-readable keys yields no project / False.
- **Workaround / current handling:** Resolve the CLOUD_SETTING_*/CLOUD_SYNC_* constants via the live resolve handle (server._normalize_cloud_settings) before calling, and treat the bool return from Import/RestoreCloudProject as advisory.
- **Tags:** silent-failure, project, cloud, enum

### Timeline.Export

- **Object:** `Timeline`
- **Signature:** `(fileName, exportType, exportSubtype) -> bool`
- **Behavior:** exportType/exportSubtype must be resolve.EXPORT_* enum *values* resolved from the live handle. A JSON/MCP caller cannot pass a live enum, and a plain string ('fcpxml', or even the constant name 'EXPORT_FCPXML_1_10') is silently rejected with no file written.
- **Workaround / current handling:** Map a friendly format/subtype to the EXPORT_* constant and resolve it against the live handle (server._timeline_export_spec) before calling; verify the output file exists afterward.
- **Tags:** silent-failure, timeline, export, enum

### ProjectManager.DeleteProject

- **Object:** `ProjectManager`
- **Signature:** `(projectName) -> bool`
- **Behavior:** Returns False (no deletion) when the target project is, or recently was, the current project, and is flaky on the first attempt — so a single bool() call leaves the project undeleted with no useful error.
- **Workaround / current handling:** Load/close away from the target first, then retry; use src/utils/project_cleanup.py:delete_project_safely.
- **Tags:** unreliable-return, project, flaky

### Composition.Paste

- **Object:** `Fusion Composition`
- **Behavior:** Passing tool.SaveSettings()'s in-memory table to Paste() / LoadSettings() fails across the Python bridge with an OrderedDict/null-argument error and creates no node, while reporting nothing useful.
- **Workaround / current handling:** Duplicate via AddTool(RegID) + SaveSettings(path)/LoadSettings(path) through a temp .setting FILE, which round-trips reliably. Identify the new node by name diff.
- **Tags:** fusion, bridge, silent-failure

### FlowView.SetPos / FlowView.GetPosTable

- **Object:** `Fusion FlowView (comp.CurrentFrame.FlowView)`
- **Behavior:** Node positions are read/written through the FlowView, not the tool. SetPos returns nothing reliable; GetPosTable returns a 1-indexed table (or dict/tuple depending on bridge).
- **Workaround / current handling:** Use comp.CurrentFrame.FlowView.SetPos(tool, x, y); confirm with GetPosTable and a liberal position parser.
- **Tags:** fusion, unreliable-return

### MediaPoolItem.GetClipProperty('Transcription')

- **Object:** `MediaPoolItem`
- **Behavior:** Returns a PREVIEW of the transcription that ends in an ellipsis when the full transcript is longer than the property exposes.
- **Workaround / current handling:** Treat a trailing ellipsis as truncation (see media_pool_item get_transcription's `truncated` flag).
- **Tags:** transcription, truncation

### ProjectManager.CreateProject (with a dirty Untitled project)

- **Object:** `ProjectManager`
- **Behavior:** Returns None and pops a modal 'Save Current Project' dialog when the current unsaved/Untitled project blocks the switch. SaveProject() on an Untitled project re-triggers the same modal.
- **Workaround / current handling:** CloseProject(current) to discard the untitled project without a prompt, then CreateProject; restore with LoadProject afterward.
- **Tags:** project, modal, silent-failure

### hasattr() / getattr() on Resolve API objects (attribute fabrication)

- **Object:** `(all Resolve scripting objects)`
- **Behavior:** The Python bridge returns a callable for ANY attribute name, so hasattr(obj, 'TotallyMadeUpMethod') is always True and getattr never raises. This makes capability detection by hasattr impossible — verified on 21.0.0 (hasattr reported SetStart, Razor, AddNode, GenerateProxy, AddSmartBin etc. as present though none exist). Only dir() lists the real methods.
- **Workaround / current handling:** Never probe method existence with hasattr/getattr; test membership against dir(obj) instead. Calling a fabricated method typically returns None/False with no error.
- **Tags:** bridge, introspection, silent-failure

### MediaPoolItem.SetClipProperty('Reel Name', ...)

- **Object:** `MediaPoolItem`
- **Signature:** `(propertyName, propertyValue) -> bool`
- **Behavior:** Setting the 'Reel Name' clip property returns True but the value is silently dropped on read-back when the project is configured to derive reel names automatically (General Options > 'Assist using reel names from the:' set to source clip file / embedding / filename pattern). The same True-but-unpersisted behavior occurs via SetMetadata('Reel Name', ...). Other clip properties on the same clip (e.g. 'Comments') write and persist normally, so this is field-specific, not a bridge/permission failure. Verified on Resolve 21.0.0; reported as issue #77.
- **Workaround / current handling:** After writing 'Reel Name', read it back with GetClipProperty('Reel Name') and refuse to report success on mismatch; surface the project-setting gate to the caller (server._verify_clip_property_writeback).
- **Reference:** [issue #77](https://github.com/samuelgursky/davinci-resolve-mcp/issues/77)
- **Tags:** unreliable-return, silent-failure, metadata, reel-name
