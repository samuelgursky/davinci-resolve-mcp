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

**Totals:** 23 missing capabilities, 22 bugs / unreliable behaviors.

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

### Project.SetSetting('timelinePlaybackFrameRate')

- **Object:** `Project`
- **Behavior:** Returns False for every value form tried (string, int, float), both before and after a timeline exists, so the playback frame rate cannot be set from the API at all. Reported by a community contributor against Resolve Studio while assembling a vertical timeline (PR #99).
- **Workaround / current handling:** Ask the user to set it in Project Settings > Master Settings > Playback frame rate as a SETUP step, before any timeline exists. Read it back to confirm; do not report it as set on the strength of the call alone.
- **Tags:** project-settings, silent-failure, timeline

### Timeline.GetCurrentClipThumbnailImage (Color page only)

- **Object:** `Timeline`
- **Signature:** `() -> {width, height, format, data} | None`
- **Behavior:** Returns thumbnail data only while Resolve is on the Color page — the reference documents it as returning data 'for current media in the Color Page'. On every other page it silently returns None for every frame, indistinguishable from 'no thumbnail exists', with no error naming the page requirement.
- **Workaround / current handling:** Switch to the Color page under the page lock before reading and restore the user's page after (src/utils/page_lock.py:color_page_for_thumbnails does exactly this); when the switch fails (headless), name the Color-page requirement in the error instead of reporting a missing thumbnail.
- **Tags:** timeline, thumbnail, silent-failure, page-dependent

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

### Render in Place / bake a timeline clip to new media

- **Object:** `Timeline / TimelineItem / MediaPool`
- **Behavior:** There is no scripting method for the Edit-page clip context-menu action 'Render in Place', which bakes a clip (including its Fusion composition and effects) into a NEW rendered media file and drops that file back on the timeline at the same position, replacing the source clip. No Render*/Bake*/Freeze* method exists on Timeline, TimelineItem or MediaPool in the Resolve scripting API reference (BMD docs) or a dir() audit. NOTE the frequently-confused-but-distinct sibling: the render *cache* (a temporary, non-destructive cache of a clip's Color/Fusion output that reduces playback load WITHOUT creating a new media file) IS scriptable — TimelineItem.SetColorOutputCache / SetFusionOutputCache ('Render Cache Color/Fusion Output' menu actions) and Graph.SetNodeCacheMode. Render in Place is the permanent, media-producing bake; the render cache is the transient one.
- **Workaround / current handling:** If the goal is only to reduce playback/render load, use the render cache — exposed as timeline_item get_color_cache/set_color_cache/get_fusion_cache/set_fusion_cache and the Color-page graph node cache_mode (no new media, fully reversible). If you genuinely need a baked media file, render the clip's in/out range from the Deliver page (proj.AddRenderJob with MarkIn/MarkOut) and relink/append the result yourself, or run Render in Place from the Resolve UI. There is no one-call API equivalent. See issue #86.
- **Reference:** [issue #86](https://github.com/samuelgursky/davinci-resolve-mcp/issues/86)
- **Tags:** missing-method, timeline, render, cache, render-in-place, bake

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

### MediaPool.ImportMedia (current-folder destination only)

- **Object:** `MediaPool`
- **Signature:** `([paths] | [clipInfos]) -> [MediaPoolItem]`
- **Behavior:** Imports always land in the CURRENT media pool folder; the call has no destination-folder parameter, and passing an unrecognized one to the MCP tool is silently ignored.
- **Workaround / current handling:** SetCurrentFolder to the target bin first (media_pool set_current_folder), import, then restore the previous current folder if it matters.
- **Tags:** media-pool, import

### Project.SetCurrentRenderFormatAndCodec

- **Object:** `Project`
- **Signature:** `(format, codec) -> bool`
- **Behavior:** Some render formats expose NO codecs at all — GetRenderCodecs('wav') and GetRenderCodecs('gif') both return {} on Studio 19.1.3.7 — and the call then rejects every codec value, including the empty string, the format id itself, and any plausible name ('Linear PCM'). There is no documented way to select such a format through this API, so an audio-only WAV deliverable is not expressible in scripting.
- **Workaround / current handling:** Check GetRenderCodecs(format) first; when it is empty, treat the format as unreachable through this API rather than guessing a codec value. Render audio-only via ExportVideo=False on a format that does expose codecs, or drive it from a saved render preset.
- **Tags:** render, deliver, audio, unsupported

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
- **Behavior:** Returns False (no deletion) when the target project is, or recently was, the current project, and is flaky on the first attempt — so a single bool() call leaves the project undeleted with no useful error. CloseProject reliably releases it: a delete that had failed six times in a row, a second apart, succeeded on the first attempt after one. Switching away with LoadProject is NOT reliable — it left the delete failing permanently after a heavily-used project, yet succeeded for a project that had only been created and loaded. Whatever distinguishes the two (modification? an open timeline?) is not established, so LoadProject-away cannot be depended on.
- **Workaround / current handling:** CloseProject the target FIRST (that is what releases it), then LoadProject some named project so the session is not left on the unsaveable 'Untitled Project' fallback, then delete. Use src/utils/project_cleanup.py:delete_project_safely, which does exactly that.
- **Tags:** unreliable-return, project, flaky, session-lock

### ProjectManager.GetCurrentDatabase

- **Object:** `ProjectManager`
- **Signature:** `() -> {DbType, DbName}`
- **Behavior:** Returns None when Resolve has come up without attaching to a project database — a state it reaches after an unclean shutdown, and does not recover from on its own. In that state the application looks entirely healthy: it accepts scripting connections, and GetProductName, GetVersionString, GetCurrentPage and GetCurrentProject all answer normally. But CreateProject and LoadProject return False indefinitely, SaveProject returns None, and some calls block forever in the scripting transport rather than returning at all. Observed headless on Studio 19.1.3.7 after force-killing a wedged instance; the replacement took 2m05s to become scriptable and came up with no database.
- **Workaround / current handling:** Treat a non-None GetCurrentDatabase() as the liveness check, not a successful connection — every cheaper check passes in the wedged state. `resolve_control runtime_mode` reports `database_attached` for exactly this. There is no repair: quit and restart Resolve.
- **Tags:** project, database, headless, silent-failure, startup

### MediaPool.ImportTimelineFromFile

- **Object:** `MediaPool`
- **Signature:** `(filePath, {importOptions}) -> Timeline`
- **Behavior:** Returns None — no error, no exception — when the requested `timelineName` already exists. Measured: importing one file three times with the same name succeeded once and returned None twice. An iterative loop that reuses a fixed name therefore works exactly once and then silently does nothing. DRT ignores importOptions entirely (timelineName, importSourceClips and sourceClipsFolders are all invalid for it): the timeline is named after the FILE, repeats auto-uniquify ('iter', 'iter 2', 'iter 3'), and because importSourceClips cannot be disabled each DRT import adds another copy of the source media to the pool. OTIO is the one format that will NOT relink from the pool — with importSourceClips=False its timeline rebuilds with correct structure and every item OFFLINE, in both GUI and headless.
- **Workaround / current handling:** For a repeatable loop use FCP7 XML or AAF with a UNIQUE timelineName per iteration plus importSourceClips=False and sourceClipsFolders=[root] — verified frame-exact over five consecutive imports with no media duplicated. Use DRT for one-shot hand-offs only. For OTIO, pass importSourceClips=True with a sourceClipsPath. See docs/guides/headless-edit-loop.md.
- **Tags:** timeline, import, interchange, silent-failure, conform

### Timeline.Export(EXPORT_FCPXML_1_10)

- **Object:** `Timeline`
- **Signature:** `(fileName, EXPORT_FCPXML_1_10, EXPORT_NONE) -> bool`
- **Behavior:** Returns True and creates a BUNDLE DIRECTORY at the given path containing `Info.fcpxml`, rather than a file — the `.fcpxmld` shape Final Cut uses. Two consequences bite immediately: a `stat().st_size` check reads the directory inode (96 bytes here) and concludes the export is empty, and ImportTimelineFromFile on that path fails because it is a directory. Every other EXPORT_* type in this build writes a plain file, so code that treats them uniformly gets this one wrong. Pointed at the inner member, the format round-trips frame-exactly in both modes.
- **Workaround / current handling:** After exporting, check `Path(p).is_dir()` and import `next(Path(p).glob('*.fcpxml'))` instead. Do not size-check the export path itself.
- **Tags:** timeline, export, interchange, fcpxml, silent-failure

### MediaPool.CreateTimelineFromClips

- **Object:** `MediaPool`
- **Behavior:** Fails with a bare 'Failed to create timeline from clip_infos' — naming nothing actionable — when the Media Pool's CURRENT folder is not the folder holding the clips, even though every clip_id passed is valid and resolvable. Reported against Resolve Studio in PR #99.
- **Workaround / current handling:** Call MediaPool.SetCurrentFolder() to the clips' bin before creating the timeline (media_pool set_current_folder). Valid ids are not sufficient.
- **Tags:** media-pool, timeline, unhelpful-error

### TimelineItem.AddFusionComp / LoadFusionCompByName

- **Object:** `TimelineItem (media-backed clip)`
- **Behavior:** A Fusion composition created on a media clip through the API is not applied at render WHEN MEDIAOUT HAS NO PATH FROM MEDIAIN. The original blanket form of this entry — 'never applied at render' — was too broad and was corrected on 2026-08-02: a comp wired MediaIn -> Blur -> MediaOut, created entirely through the API on an ordinary media clip, DOES render. PSNR between the plain and Fusion renders of the same timeline was 22.7 dB (identical would be infinite), the file shrank 22.5 MB -> 14.8 MB as a blur should, and the output was frame-for-frame identical in GUI and headless. A first attempt that wired ONLY MediaOut -> Blur, leaving the Blur with no source, made the render job come back 'Failed' with an 887-byte file — so an unrooted graph does not merely get bypassed, it can take the render down. What still stands is the original observation for the configuration it actually tested, which is retained below and has NOT been re-measured: AddFusionComp() returns the comp, AddTool/Connect/SetInput all succeed, and the whole graph reads back correctly (GetCompCount 1, MediaOut1.Input wired to the new tool, StyledText returning the value just set) — but the rendered output is byte-for-byte the untouched source media. Verified live on Studio 19.1.3.7 with the strongest form of the test: MediaOut1 fed ONLY by a Text+, with no path from MediaIn at all, still rendered the unmodified clip. LoadFusionCompByName on the sole comp does not activate it either. Contrast InsertFusionTitleIntoTimeline, whose comp DOES render — text set via SetInput('StyledText') appears in the output — so this is specific to comps attached to media-backed clips, not to Fusion through the API generally.
- **Workaround / current handling:** Wire the graph so MediaOut descends from MediaIn — that is the difference between a comp that renders and one that is silently bypassed, and it is what made this look like 'Fusion never renders from the API'. Never leave a tool unrooted: a MediaOut fed by a tool with no source failed the render job outright. For text or effects over picture, insert a Fusion title/generator as its own timeline clip and set its Text+ (fusion_comp set_text_plus), rather than attaching a comp to the media clip. Note the destination track cannot be chosen from the API (see the Track Selector entry), so overlaying onto an existing clip's track is not currently reachable end-to-end. Building the comp in the Fusion page UI works; only the API-created comp is ignored.
- **Tags:** fusion, silent-failure, render

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

### Timeline.DeleteClips (flaky first attempt)

- **Object:** `Timeline`
- **Signature:** `([TimelineItem], ripple) -> bool`
- **Behavior:** Can return False on the first call even when every item in the list is a valid, present TimelineItem; an identical immediate retry succeeded in the one observed instance. Observed on Studio 21.0 during a cut-video edit session (items confirmed still present after the False, deleted cleanly on retry). CAUSE NOT ESTABLISHED — one instance is not evidence of randomness, and it may well have a state precondition. ProjectManager.DeleteProject looked superficially identical and turned out to have a specific trigger that retrying does NOT clear (it failed six times a second apart, then succeeded first time after CloseProject), so do not assume a retry is the answer here either.
- **Workaround / current handling:** Treat a False return as advisory: re-list the track and check whether the items are actually gone; if still present, retry the identical call once before failing. The MCP delete_clips tool does not yet implement this readback-and-retry — call sites are currently unguarded.
- **Tags:** unreliable-return, flaky, timeline, edit

### MediaPool.AppendToTimeline with mixed-fps sources (duration floor)

- **Object:** `MediaPool`
- **Signature:** `([{mediaPoolItem, startFrame, endFrame, recordFrame, ...}]) -> [TimelineItem]`
- **Behavior:** start/endFrame are in SOURCE frames. When the source fps differs from the timeline fps (e.g. 24.0 or 29.97 source in a 23.976 timeline), Resolve converts the source range to timeline frames by flooring — so a range planned to fill an exact record slot lands one frame short, leaving a 1-frame gap before the next clip.
- **Workaround / current handling:** Plan durations in timeline frames (floor(src_frames * timeline_fps / source_fps)); if the floored duration misses the slot, extend endFrame by a source frame and re-check. Always finish with detect_gaps_overlaps.
- **Tags:** timeline, edit, off-by-one, mixed-fps

### Graph.SetLUT (master-LUT-dir-only resolution)

- **Object:** `Graph`
- **Signature:** `(nodeIndex, lutPath) -> bool`
- **Behavior:** SetLUT resolves lutPath ONLY against the master (system) LUT directory and its configured custom LUT paths -- NOT the per-user LUT dir that the dctl tool / Project LUT install writes to. A bare basename in the user dir returns False, and so does an ABSOLUTE path pointing into the user dir; RefreshLUTList() does not change this. A subfolder-relative path under the master root (e.g. 'MCP/Foo.cube') DOES resolve. Net effect: a LUT/DCTL the dctl tool just installed can never be applied by SetLUT as-is, so set_lut used to always return {success: false}. Verified live on Studio 19.1.3.7 (basename and absolute user-dir path both False, before and after RefreshLUTList; master-dir and master-subfolder paths True); the originating report (PR #90) observed the same on 21.0.2, so it is not version-specific.
- **Workaround / current handling:** On a False return, locate the LUT, copy it into a namespaced subfolder of the master LUT dir (MCP/, so it does not clobber stock LUTs by basename), call RefreshLUTList(), and retry with the master-relative path. graph.set_lut and the granular graph_set_lut now do this automatically via src.utils.lut_paths.ensure_lut_in_master.
- **Reference:** [issue #90](https://github.com/samuelgursky/davinci-resolve-mcp/issues/90)
- **Tags:** color, lut, path-resolution, silent-failure

### Project.GetRenderCodecs

- **Object:** `Project`
- **Signature:** `(renderFormat) -> {codec description: codec name}`
- **Behavior:** Returns {description: id} — the human-readable description is the KEY and the id Resolve actually accepts is the VALUE. SetCurrentRenderFormatAndCodec, GetRenderCodecs and GetRenderResolutions all require the id, so passing the description a user sees in the Deliver page is rejected. Verified live on Studio 19.1.3.7: ('mov', 'Apple ProRes 422 HQ') -> False while ('mov', 'ProRes422HQ') -> True, and ('mp4', 'H.264') -> False while ('mp4', 'H264') -> True. It affects every family, not only the ones whose id differs obviously. Mirrors the same trap in GetRenderFormats, which returns {format: extension}.
- **Workaround / current handling:** Normalize both arguments through the live maps before calling: src.utils.render_ids.render_format_id_from_formats and render_codec_id_from_codecs accept a description or an id and return the id.
- **Reference:** [issue #59](https://github.com/samuelgursky/davinci-resolve-mcp/issues/59)
- **Tags:** render, deliver, silent-failure, id-vs-label

### ProjectManager.SaveProject

- **Object:** `ProjectManager`
- **Signature:** `() -> bool`
- **Behavior:** On the default, never-saved project named 'Untitled Project' this call CANNOT succeed — the project has no location and there is no SaveProjectAs to give it one — and the two modes fail differently. In the GUI it returns False. HEADLESS IT BLOCKS FOREVER: measured on a cold -nogui boot with the database verified attached immediately beforehand, no return after 45s, the client parked in Fusion::RemoteApp::WaitPkt. Resolve wants a Save-As dialog and waits for an answer that cannot arrive. It also degrades the instance: after the hung call was interrupted, SaveProject began returning None instantly on that instance. On a named project it is fine in both modes.
- **Workaround / current handling:** Guard it: only call SaveProject when GetCurrentProject().GetName() != 'Untitled Project'. There is nothing to save on the default project and the call cannot succeed, so skipping it loses nothing. Do NOT reach for headless to dodge the GUI's save dialog — headless turns that dialog into an unbounded hang that no human can clear.
- **Tags:** project, modal, headless, hang, silent-failure, unreliable-return

### GalleryStillAlbum.ExportStills

- **Object:** `GalleryStillAlbum`
- **Signature:** `(galleryStills, folderPath, filePrefix, format) -> bool`
- **Behavior:** PANEL-dependent, not mode-dependent — and the distinction took three revisions of this entry to pin down, so the evidence is recorded rather than summarised. Across four controlled 92-probe sweeps (2 GUI, 2 headless, 2026-08-01) it returned False and wrote nothing in ALL FOUR, while Timeline.GrabStill() succeeded in all four — so it is not being handed an empty still. In one earlier GUI session it DID work, returning True and writing 2 files. The variable that differed is not the mode: it is whether the Gallery panel was visible on the Color page, which depends on the restored workspace layout and which the harness does not control. A headless session can never satisfy it, so in practice the call never works headless; a GUI session satisfies it only sometimes. Project.ExportCurrentFrameAsStill worked in all four runs in both modes.
- **Workaround / current handling:** Do not use ExportStills unattended in either mode — a GUI session is not sufficient, only a GUI session with the Gallery panel open. Use Project.ExportCurrentFrameAsStill for pixels (verified in both modes, four for four) or drp.extract_node_graphs for grades. If ExportStills must be used, have the user open Workspace > Gallery first and verify the written files rather than trusting the return.
- **Tags:** gallery, stills, headless, unreliable-return
