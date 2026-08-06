# DaVinci Resolve Scripting API — Limitations & Feedback

<!-- GENERATED FILE — do not edit by hand.
     Source: src/utils/api_truth.py (entries tagged `submit`).
     Regenerate: venv/bin/python scripts/gen_api_limitations.py -->

This is a curated, behaviorally-verified list of DaVinci Resolve scripting
API gaps and bugs encountered while building this MCP server, intended for
submission to Blackmagic Design's developer feedback. Every item was
observed against live Resolve; each entry notes the current workaround (or
that none exists).

**Verified on:** DaVinci Resolve Studio 21.0.2

**Totals:** 27 missing capabilities, 30 bugs / unreliable behaviors.

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
- **Behavior:** SetProperty exposes only retime *quality* (RetimeProcess, MotionEstimation) and transform/crop/composite/opacity keys — not the speed value itself. There is no way to set a clip to a given % speed, reverse it, or author a speed ramp. Verified against the documented SetProperty key list AND by live mutating attempt on 21.0.0: SetProperty('Speed'|'PlaybackSpeed'|'RetimeSpeed'|'ClipSpeed', 50) all return False, while SetProperty('RetimeProcess', 1) returns True. THE READ SIDE IS AS DEAD AS THE WRITE SIDE, which is easy to miss: re-measured on Studio 19.1.3.7 against a placed item, GetProperty('Speed'), GetProperty('PlaybackSpeed'), GetProperty('RetimeSpeed') and GetProperty('ClipSpeed') ALL return None, and the keyless GetProperty() dict (26 keys on that item) carries no speed value at all — its only retime key is RetimeProcess, which is quality, not ratio. SetProperty('Speed', 1.75) returned False on 19.1.3.7 too, so the write refusal is not specific to 21.0.0. Note the 21.0.0 stamp above covers the SetProperty measurements only. THE SCRIPTING-API xmeml IMPORT BUILDS NO RETIME — and the way it fails is worse than a no-op. First, what Premiere actually writes, because having this backwards is what produced the wrong contract this entry published in 2.79.0–2.79.1 (see CORRECTION below). In an FCP7 XML a retimed clipitem's <in>/<out> live in the POST-RETIME (warped) domain and always span the RECORD duration; pproTicksIn/pproTicksOut carry the TRUE SOURCE position; and <duration> is the file length expressed in the warped domain. A real 200% clip at 24 fps: <in>1957</in> <out>1971</out> — span 14, EQUAL to its record span; pproTicksIn 41425776000000 and pproTicksOut 41722128000000, which at 254016000000/24 = 10584000000 ticks per frame are source frames 3914 and 3942, exactly 1957x2 and 1971x2, a 28-frame source span over a 14-frame record span; <duration>24292</duration> for a 48584-frame file; and a graphdict mapping warped to true source with the ratio as its slope (when 17910 -> value 35820). So for a retimed clip <in> and pproTicksIn are SUPPOSED to disagree, by exactly the ratio. The same relationship seen from the other side is already encoded in this repo: resolve-advanced/server/prproj.mjs derives Premiere speed from tick geometry as |srcSpan / recSpan| * 100, reversing when in > out. Against that convention, measured on 19.1.3/19.1.3.7: (a) the importer IGNORES the scalar Time Remap speed filter and the clips arrive at 100%; (b) `graphdict` is ignored too — re-tested in Premiere's exact convention with one 100% control clip and one 200% clip per timeline, a document carrying warped <in>/<out>, true-source pproTicks, <duration> = fileLen/ratio and a constant-slope graphdict imports cleanly, the control lands correct, and NO retime is built: recalibrated 2026-08-05, every xmeml-imported clip carries a DEGENERATE time map in Project.db (Sm2TimeMap with an empty source axis — five Time Remap shapes re-measured, 15/15 clips degenerate), so no speed exists in the project data, and the API source witness reads 0/0 on those clips (see WITNESS CALIBRATION below); emitting the identical document WITHOUT the graphdict gives the identical result; (c) `reverse` does not survive either; (d) THE HAZARD, and it is the part that bites: Resolve reads <in> LITERALLY as the true source frame, honouring neither the ticks nor the graphdict. Import a genuine Premiere XML that contains retimes and every retimed clip is placed at in / ratio — the 200% clip above lands on source frame 1957 instead of 3914. There is no error, the cut lengths are still correct, every clip is linked and online, and the timeline renders — so it reads as a good conform while sitting at the wrong moment of the right file. This is the same failure class as the Avid AAF camera-file link (docs/guides/conforming-an-avid-aaf.md): wrong in a way only a frame comparison against a reference can see. SCOPE: all of the above is the SCRIPTING-API import (ImportTimelineFromFile). Resolve's UI importer (File > Import > Timeline) has NOT been tested, and that is how editors usually conform a Premiere XML — do not read this as covering it. CORRECTION: this entry as published in 2.79.0–2.79.1 also claimed that any <in>/<pproTicksIn> inconsistency is silently REJECTED in both orientations. That claim was FALSE and has been removed — it came from an emitter writing ticks = in x ticks-per-frame at every speed, so what it observed was its own malformed files being refused. The graphdict evidence published with it (dead in FOUR shapes, 0 of 2 landed, a 200% clip emitted in 200 / out 296 'clamped' to out 248) described that same malformed input being normalized and is replaced by the re-test above. The conclusion is unchanged; only its evidence is. Placement is NOT the problem: the same route imported 573 clips with 572 of 573 matching by track and record position with source frames exact, and the importer BUILT a 59-frame dissolve. The retime gap is specific, not general. TRAP: Resolve's own FCP7 export cannot witness a speed. It writes a DEGENERATE Time Remap on every clip — `speed` value 0 (not 100) and a graphdict whose keyframe `value`s are all 0 while its `when`s carry the clip's source in/out — so anyone verifying a retime by round-tripping through EXPORT_FCP_7_XML is reading furniture, and the identity Time Remap blocks present on every clip are what make the route look like it should work. WITNESS CALIBRATION (2026-08-05, Studio 19.1.3.7) — the positive control this entry previously lacked now exists, and it RETRACTS the witness the 2.80.0 revision of this entry recommended. The rig removed every confound: the SAME clip placed twice, adjacent, in ONE timeline, the second copy hand-set to 200% in the UI (the only way to make one — see above). GetSourceStartFrame/GetSourceEndFrame separated the copies — 1822..1870 (span 48) at 100% vs 1822..1918 (span 96) at 200% — while GetLeftOffset/GetRightOffset did NOT: 1822..1870 at 100% vs 911..959 at 200%, which is exactly position / 2. GetLeftOffset reports the WARPED (record-side) domain — position / speed, the `In` column of Project.db's Sm2TiItem — so it is exact for PLACEMENT and blind for SPEED BY CONSTRUCTION: its span equals the record span at every speed. The speed itself lives in the item's Sm2TimeMap blob (keyframe slope = ratio; the hand-set 200% reads slope exactly 2.0), which is what GetSourceStart/EndFrame and EXPORT_EDL read. THE SPEED WITNESS is therefore the GetSourceStart/EndFrame span vs the record duration. CAVEAT: on xmeml-IMPORTED timelines those return 0/0 — the importer leaves the time map's source axis empty — and a 0/0 read is UNKNOWN, never 'no retime'. Cross-checks that work everywhere: the Sm2TimeMap slope read from a saved Project.db, and the EXPORT_EDL M2 rate (rate = fps x speed/100, so 048.0 = 200% at 24 fps; `M2 ... 000.0` on every clip is the degenerate-map furniture of an xmeml import — ignore it). TWO IMPORT ROUTES DO BUILD CONSTANT RETIMES (measured 2026-08-05, media linked, judged via the calibrated witnesses above): (1) OTIO LinearTimeWarp through ImportTimelineFromFile — 200% (src 200..296 over a 48-frame record) and 50% (src 300..324 over a 48-frame record) both landed with correct source in-points; the saved Project.db shows slope 2.0 and 0.5. Emission rules: the document must be Resolve-shaped with TIMECODE-ABSOLUTE source frames (see the ImportTimelineFromFile .otio entry), the effect is `LinearTimeWarp.1` with `time_scalar`, and `source_range.duration` is the RECORD span — OTIO semantics, the time_scalar handles source consumption; sending the source span as the duration builds a spec-correctly longer clip, not a retime. (2) EDL M2 — 200% landed (src 100..196 over a 48-frame record), linked. Author the shape Resolve's own EXPORT_EDL writes: the event line's source span EQUALS the record span even under M2; the `M2 <reel> <rate> <srcInTC>` line carries the play rate in fps (048.0 = 200% at 24); `* FROM CLIP NAME:` comments drive pool linking. UNTESTED as import routes: reverse (negative time_scalar / reverse M2) and varying-speed maps — do not extrapolate the constant-speed result to them.
- **Workaround / current handling:** Set clip speed/retime in the Resolve UI, or BUILD it by import: OTIO LinearTimeWarp and EDL M2 both construct constant retimes through ImportTimelineFromFile (measured — emission rules in reality above); xmeml does not, in any Time Remap shape. To READ a retime back, judge speed by the GetSourceStart/EndFrame span vs the record duration — a 0/0 read (xmeml-imported timelines) is UNKNOWN, never 'no retime' — and cross-check with the Sm2TimeMap slope in a saved Project.db or the EXPORT_EDL M2 rate. Do NOT read speed with GetProperty (None), witness it via EXPORT_FCP_7_XML (degenerate), or judge it from GetLeftOffset/GetRightOffset — the 2.80.0 revision of this entry recommended that pair as the witness and it is blind by construction: it reads the warped domain (position / speed) and its span equals the record span at every speed. Keep it for PLACEMENT checks only. Reverse and varying-speed maps remain untested as import routes. And if you are importing a real Premiere XML that contains retimes, treat every retimed clip's source position as WRONG — placed at <in>, i.e. in / ratio — until it is checked against a reference; the lengths and the links will look right.
- **Tags:** missing-method, timeline, retime, speed, interchange, silent-failure, unreliable-return

### Color node graph editing and primary grade values

- **Object:** `Graph / TimelineItem`
- **Behavior:** The Graph object exposes node enable/label/count, LUT get/set, cache mode, ResetAllGrades, ApplyGradeFromDRX and ApplyArriCdlLut; TimelineItem adds SetCDL, CopyGrades and color versions. But you cannot add, delete, or connect nodes, and you cannot read or write primary grade values (lift/gamma/gain/offset/contrast/curves/qualifiers/power windows). Grading is limited to CDL, whole-grade DRX/LUT application and copying.
- **Workaround / current handling:** Build node trees and dial grades in the Resolve UI or via DRX/CDL/LUT import; per-parameter grade control is not scriptable.
- **Tags:** missing-method, color, grade, node

### Fairlight audio levels / pan / EQ / automation / FairlightFX

- **Object:** `TimelineItem / Timeline`
- **Behavior:** There is no API to set clip or track volume, pan, EQ, audio automation, or to add/configure FairlightFX. SetProperty covers video transform only; the audio surface is read-only (GetSourceAudioChannelMapping, GetAudioMapping, voice isolation). Verified via dir() + SetProperty docs AND by live mutating attempt on 21.0.0: SetProperty('Volume'|'Level'|'Gain'|'AudioVolume', 0) all return False (note 'Pan' is the VIDEO transform key, not audio pan, so it misleadingly succeeds). The gap is PER-PARAMETER control specifically: a whole saved mix CAN be applied wholesale via Project.ApplyFairlightPresetToCurrentTimeline(name), with the available names from Resolve.GetFairlightPresets() — so 'no Fairlight write path exists' would be too strong. Both methods require Resolve 20.2.2+; on 19.1.3 they are absent (confirmed live 2026-08-06), so on older builds the per-parameter gap really is the whole story.
- **Workaround / current handling:** To reapply a known mix, save it once as a Fairlight preset in the UI and apply it per-timeline with ApplyFairlightPresetToCurrentTimeline (exposed as resolve_control get_fairlight_presets + project_settings apply_fairlight_preset). Dial individual levels/pan/EQ/automation/FairlightFX in the Fairlight UI; beyond presets, only voice-isolation state and channel-mapping reads are scriptable.
- **Tags:** missing-method, audio, fairlight

### AI Audio Assistant (one-click timeline auto-mix)

- **Object:** `Timeline / Project`
- **Behavior:** The Fairlight AI Audio Assistant — which analyses a timeline and generates a balanced dialogue/music/effects mix — has no scripting method. Nothing matching it appears in the Resolve scripting API reference or in a dir() audit of Resolve, Project, Timeline or TimelineItem. Note this is NOT because it is a menu command: the API has no generic menu-invocation hook at all, so scriptability is per-feature, and plenty of menu commands DO have methods (DetectSceneCuts, Stabilize, SmartReframe, CreateMagicMask, TranscribeAudio, RemoveMotionBlur, AnalyzeForIntellisearch). It is compounded by the per-parameter Fairlight gap above: even the mix it produces cannot be read back or reconstructed clip-by-clip.
- **Workaround / current handling:** No way to trigger it from a script. For a repeatable mix, run the Assistant once in the UI, save the result as a Fairlight preset, then apply that preset per-timeline with project_settings apply_fairlight_preset — content-adaptive per run is not achievable, a consistent template mix is.
- **Tags:** missing-method, audio, fairlight, ai, auto-mix

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
- **Workaround / current handling:** No API workaround exists, but the style IS reachable below the API: it lives in Sm2TiTrack.FieldsBlob for Type=2 tracks, as an EffectFiltersBA payload whose effect 136 carries a Qt QFont descriptor (param 18) and a normalised position vector (param 17). Exposed as project_db list_subtitle_styles / set_subtitle_style (font family/size/weight/italic + position). Confirmed live on BOTH editions 2026-08-06 — Studio 19.1.3 and free 21.0.3, identical behaviour: Resolve opens a patched track and re-serialises it back to its own zstd form with the patched values intact, so it genuinely parses the write. Caveats: whole-TRACK style not per-caption, project must be CLOSED, Resolve must be fully quit and relaunched afterwards, and the track must already carry a style blob (a freshly added subtitle track has none until it is styled once in the UI). Burn-in overlays via Fusion titles remain a visual alternative but do not produce subtitle tracks.
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

### Installed AI Extras packs are not discoverable from scripting

- **Object:** `Resolve`
- **Behavior:** AnalyzeForIntellisearch, AnalyzeForSlate, GenerateSpeech and RemoveMotionBlur each require a separately-downloaded Extras pack, but nothing in the scripting API reports which packs are installed. A caller cannot distinguish 'the Extra is missing' from 'the analysis ran and found nothing' ahead of time; on 21.0.2.4 two of the four leak the reason only as free text in the return value, and AnalyzeForSlate's bare False carries no reason at all.
- **Workaround / current handling:** Until an API exists, treat a string return as the reason and read the pack names out of the Extras directory (Blackmagic Design/DaVinci Resolve/Extras/*/log.dpl1) for diagnostics only — that path is undocumented and may change.
- **Tags:** ai, extras, introspection, resolve-21

### Resolve.DisableBackgroundTasksForCurrentResolveSession

- **Object:** `Resolve`
- **Signature:** `() -> None`
- **Behavior:** Returns None, so a caller cannot tell whether it took effect, and there is no Enable... counterpart anywhere in the shipped 21.0.2 scripting README — the only documented way back is restarting Resolve. The scope is the whole session, so a script disables background tasks for every project open in that instance, not just its own. Present in dir(resolve) on Studio 21.0.2.4; deliberately not executed during validation for exactly that reason.
- **Workaround / current handling:** Treat as irreversible within a session. server returns _ok() unconditionally because there is nothing to check.
- **Tags:** resolve-21, unreliable-return, irreversible, session-wide

### MediaPool.ImportMedia (current-folder destination only)

- **Object:** `MediaPool`
- **Signature:** `([paths] | [clipInfos]) -> [MediaPoolItem]`
- **Behavior:** Imports always land in the CURRENT media pool folder; the call has no destination-folder parameter, and passing an unrecognized one to the MCP tool is silently ignored.
- **Workaround / current handling:** SetCurrentFolder to the target bin first (media_pool set_current_folder), import, then restore the previous current folder if it matters.
- **Tags:** media-pool, import

### SetClipColor (undocumented value space; marker constants are a decoy)

- **Object:** `TimelineItem / MediaPoolItem`
- **Signature:** `(colorName) -> bool`
- **Behavior:** SetClipColor accepts exactly 16 names — the Edit-page clip-colour palette — and refuses everything else with a bare False, no exception and no other signal. Enumerated live on Studio 19.1.3.7 (2026-08-06) against both objects; the accepted set is IDENTICAL on TimelineItem and MediaPoolItem: Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Brown, Chocolate. The empty string is refused too. The trap is that the scripting reference documents colorName as a bare string with no enumerated values, while exporting the MARKER palette as constants (resolve.MARKER_ROSE, resolve.MARKER_FUCHSIA, ...) — so the only colour vocabulary reachable from the API surface is the wrong one. Cyan, Red, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa and Cream are all marker-only and all refused. Five names overlap both palettes (Blue, Green, Yellow, Pink, Purple), which is why the decoy survives: reasoning from the marker constants scores 5 of 16 and looks like the right vocabulary with a few gaps. The reporter's field experience sharpens this — the trap is not that a decoy vocabulary exists, it is that the decoy HALF-WORKS. Intermittent successes read as an unreliable API rather than as a wrong vocabulary, so the wrong conclusion is the natural one; a clean 0-for-8 would have exposed the mechanism immediately.
- **Workaround / current handling:** Pass only the 16 clip-colour names; on False, treat it as an invalid name rather than an item/lock/page problem. The set is pinned in utils/clip_colors.py and named in the refusal remediation, but deliberately NOT enforced — it was measured on one build and a later Resolve could extend it.
- **Reference:** [issue #124](https://github.com/samuelgursky/davinci-resolve-mcp/issues/124)
- **Tags:** timeline-item, media-pool, silent-failure, undocumented-enum

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
- **Workaround / current handling:** For a repeatable loop use FCP7 XML or AAF with a UNIQUE timelineName per iteration plus importSourceClips=False and sourceClipsFolders=[root] — verified frame-exact over five consecutive imports with no media duplicated. Use DRT for one-shot hand-offs only. For OTIO, pass importSourceClips=True with a sourceClipsPath. See docs/guides/headless-edit-loop.md. For a consolidated Avid AAF specifically, do NOT expect this call (or Reconform from Bins, or the UI's 'Link to source camera files') to conform it to camera originals — all three were measured against a real turnover and all three fail, the UI option linking 878 of 882 items with only 144 correct while rendering as a fully conformed timeline. See docs/guides/conforming-an-avid-aaf.md.
- **Tags:** timeline, import, interchange, silent-failure, conform

### Timeline.Export(EXPORT_FCPXML_1_10)

- **Object:** `Timeline`
- **Signature:** `(fileName, EXPORT_FCPXML_1_10, EXPORT_NONE) -> bool`
- **Behavior:** Returns True and creates a BUNDLE DIRECTORY at the given path containing `Info.fcpxml`, rather than a file — the `.fcpxmld` shape Final Cut uses. Two consequences bite immediately: a `stat().st_size` check reads the directory inode (96 bytes here) and concludes the export is empty, and ImportTimelineFromFile on that path fails because it is a directory. Every other EXPORT_* type in this build writes a plain file, so code that treats them uniformly gets this one wrong. Pointed at the inner member, the format round-trips frame-exactly in both modes.
- **Workaround / current handling:** After exporting, check `Path(p).is_dir()` and import `next(Path(p).glob('*.fcpxml'))` instead. Do not size-check the export path itself.
- **Tags:** timeline, export, interchange, fcpxml, silent-failure

### MediaPool.CreateTimelineFromClips

- **Object:** `MediaPool`
- **Behavior:** Fails with a bare 'Failed to create timeline from clip_infos' — naming nothing actionable — when the Media Pool's CURRENT folder is not the folder holding the clips, even though every clip_id passed is valid and resolvable. Reported against Resolve Studio in PR #99. SEPARATELY, its clipInfo HAS NO TRACK FIELD: there is no way to say which video or audio track a clip should land on, so this call cannot build a multi-track timeline. The asymmetry is the surprise — MediaPool.AppendToTimeline's clipInfo DOES take `trackIndex`, so the two clipInfo shapes are not the same shape, and code that works against one silently loses track assignment against the other.
- **Workaround / current handling:** Call MediaPool.SetCurrentFolder() to the clips' bin before creating the timeline (media_pool set_current_folder). Valid ids are not sufficient. For multi-track placement do not use this call at all: create an EMPTY timeline (media_pool create_timeline), add the tracks you need (timeline add_track), then place each clip with MediaPool.AppendToTimeline passing clipInfo `trackIndex` (media_pool append_to_timeline with track_index).
- **Tags:** media-pool, timeline, unhelpful-error, missing-method, conform

### MediaPool.AppendToTimeline (overlapping records — earlier item wins)

- **Object:** `MediaPool`
- **Signature:** `([{mediaPoolItem, startFrame, endFrame, recordFrame, trackIndex, mediaType}]) -> [TimelineItem]`
- **Behavior:** AppendToTimeline does NOT overwrite an overlapping record. When two clipInfos resolve to record ranges that overlap on the same track, the EARLIER item wins and the later append is dropped — measured while placing a real turnover. There is no overwrite edit mode to reach for either: AppendToTimeline is the only programmatic placement the API offers, so a consumer that assumes overwrite semantics gets a timeline that is silently SHORT by the number of colliding events, with no error to say which ones lost.
- **Workaround / current handling:** Resolve collisions BEFORE appending — the API will not do it for you. Cap each event's placed duration at the next event's recordFrame on the same track, or place the colliding events on separate tracks. Verify by comparing the timeline's item count against the number of clipInfos you sent, per track, and finish with detect_gaps_overlaps; a count that matches is the only evidence nothing was dropped.
- **Tags:** timeline, edit, silent-failure, conform, media-pool

### MediaPool.AppendToTimeline (errored-chunk placements are not durable across a save)

- **Object:** `MediaPool`
- **Signature:** `([clipInfos]) -> [TimelineItem]`
- **Behavior:** Placements made by an append call whose response ERRORED are not durable: they appear in the timeline, every in-session read agrees they are there, and THE SAVE DISCARDS THEM. Measured on a real turnover — a timeline verified at 573 items immediately after construction held 500 after the save, a loss of exactly one errored append chunk's worth. The API reported the failure, the items appeared anyway, and nothing between construction and the save disagreed with the wrong number. This is the dangerous shape: the witness is derived from the same unsaved state as the thing it is checking, so it cannot contradict it. Only a POST-SAVE read can.
- **Workaround / current handling:** Treat the save as the verification boundary, not the end of the job. Save, RE-READ the timeline's item count from the saved project, and re-append whatever is missing (bounded — two rounds is enough in practice); only then report success. A timeline that is still short after that, or that will not save, is a FAILURE — report it as one rather than returning the in-session count. Never claim a construction succeeded on a pre-save read alone, and treat any errored append chunk as suspect even when its items are visibly present.
- **Tags:** timeline, edit, silent-failure, data-loss, conform, unreliable-return, media-pool

### MediaPool.ImportTimelineFromFile (.otio document shape)

- **Object:** `MediaPool`
- **Signature:** `(filePath, {importOptions}) -> Timeline`
- **Behavior:** Resolve DOES import OTIO through the scripting API — but only a Resolve-shaped document, and it rejects anything else by creating NO timeline and returning None, with no error naming a cause. Established on 19.1.3.7 by exporting a timeline with Timeline.Export(..., EXPORT_OTIO) and feeding Resolve's own file straight back: it re-imports cleanly (3 items, 3 linked), while a valid hand-authored OTIO of the same cut, same project, same session, same three online media files, produced nothing. So a refusal is a SHAPE problem, not a media problem. The requirement that actually decides it is the SOURCE FRAME ORIGIN: a clip's source_range must be expressed against the media's own timecode range. Media carrying an embedded start TC of 01:00:00:00 gets an available_range starting at frame 86400, and the clip's source_range must start there too — 0-based source offsets, the natural reading of 'source in point', put the clip outside the media's real range and the import dies. Isolated by bisection: 0-based fails and absolute succeeds whether or not the stack/track source_range is null. Resolve also writes (and expects) Clip.2 with a `media_references` MAP plus `active_media_reference_key`, not Clip.1 with a singular `media_reference`; an `available_range` on each reference; a BARE path in `target_url`, not a file:// URL; `enabled` and `metadata` throughout; `global_start_time`; and track names in its own form ('Video 1').
- **Workaround / current handling:** Author OTIO for Resolve by mirroring what Resolve itself exports, and give every event its media timecode origin. editorial.convert_to_interchange (target 'otio') does this and reports any event whose origin had to be assumed in `mediaOriginAssumed` — a non-empty list means the file will only import if that media really starts at 00:00:00:00. To debug a refusal, export any timeline with EXPORT_OTIO and diff your document against it; do NOT chase missing media or reach for sanitize_media, which cannot even parse a .otio (it is JSON, not XML).
- **Tags:** timeline, import, interchange, otio, silent-failure, conform

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

### TimelineItem.GetSourceStartFrame

- **Object:** `TimelineItem`
- **Signature:** `() -> int`
- **Behavior:** Reads back one frame off on some items. Measured while verifying a constructed timeline against the clipInfos it was built from: for 4/4 items GetLeftOffset returned exactly the startFrame that was sent, while GetSourceStartFrame disagreed by 1 on some of the same items. The two are supposed to describe the same edit point, so a conform that verifies placement with GetSourceStartFrame reports phantom off-by-one drift on correctly placed clips — and would hide a real one-frame error just as easily.
- **Workaround / current handling:** Verify source-side placement with GetLeftOffset, which is exact. Treat GetSourceStartFrame as approximate, and never diff it against a sent startFrame to decide whether a clip landed right. Scope: placement at 100% speed. On a retimed clip the two read DIFFERENT domains — GetLeftOffset is warped (position / speed), GetSourceStartFrame is true source — see the retime entry's witness calibration before comparing them.
- **Tags:** off-by-one, unreliable-return, timeline, conform, verify

### hasattr() / getattr() on Resolve API objects (attribute fabrication)

- **Object:** `(all Resolve scripting objects)`
- **Behavior:** UNRESOLVED — the two measurements do not test the same thing. On 21.0.0 the bridge was recorded as returning a callable for ANY attribute name, making capability detection by hasattr impossible; the evidence was REAL API method names borrowed from other object types (SetStart, Razor, AddNode, GenerateProxy, AddSmartBin reported present on objects that do not have them). A 21.0.2.4 control probe of the invented name 'TotallyMadeUpMethod_xyz123' returned getattr-callable False on all eight object types, matching dir() in every case. That does NOT refute the 21.0.0 record: if the bridge resolves any name known to the RemoteObject method table rather than literally any string, an invented name is correctly rejected on both builds and the probe never exercised the failing case. PARTLY SETTLED 2026-08-06 on Studio 19.1.3.7, DIRECT connection (not the bridge): the five real borrowed names were re-run as the entry asked, across Resolve, ProjectManager, Project, MediaPool, Timeline, Folder and TimelineItem — 42 checks. Every one returned getattr-callable False and dir()-absent, agreeing in all 42 cases, exactly like the invented control. So NO fabrication on the direct path on this build, and the borrowed-name case the 21.0.2.4 probe missed is now covered there. What the same run DID establish is narrower and worse than expected: bare hasattr() returns True for EVERY name on every object — real, borrowed or invented — while getattr returns None. hasattr alone is therefore not a weak probe, it is a constant True and carries no information at all. STILL OPEN: the 21.0.0 record was against the BRIDGE, which this run did not exercise, so bridge-side fabrication remains untested and the recommendation below stands unchanged.
- **Workaround / current handling:** Use dir(obj) membership for capability probes. It is correct on every build measured, and it is the only form not affected by whichever way this resolves. NEVER use bare hasattr(): it is a constant True on Resolve objects and cannot distinguish anything. server._has_method uses callable(getattr(...)), which agreed with dir() in all 42 direct-path checks on 19.1.3.7 but may still over-report on a bridge build where fabrication is live — that is the case _requires_method gates guard, so it matters most exactly where it is least tested. Calling a fabricated method typically returns None/False with no error.
- **Tags:** bridge, introspection, silent-failure

### Resolve 21 AI methods (AnalyzeForIntellisearch, GenerateSpeech, AnalyzeForSlate) — inconsistent failure return type

- **Object:** `MediaPoolItem / Folder / Project`
- **Signature:** `-> Bool (documented)`
- **Behavior:** When the required Extras pack is not installed, these methods do not agree on how they say so, and the documented Bool is not what you get. Verified live on Studio 21.0.2.4 with only AI Motion Deblur installed: AnalyzeForSlate returned False, but AnalyzeForIntellisearch returned the STRING "Required package 'AI Intellisearch - Faster' is not installed." and GenerateSpeech returned the STRING "Required Package, 'AI Speech Generator' is not Installed.". A non-empty string is truthy in Python, so bool(result) reports SUCCESS for a call that definitively did not run, and treating GenerateSpeech's return as a MediaPoolItem raises AttributeError: 'str' object has no attribute 'GetName'.
- **Workaround / current handling:** Never bool() an AI-method return directly. Route it through server._ai_result / _ai_result_payload, which treat any string as a failure and surface its text as the error — the message is the only machine-readable signal that an Extras pack is missing, since there is no scripting API to enumerate installed Extras.
- **Tags:** ai, extras, unreliable-return, silent-failure, resolve-21

### Folder.AnalyzeForSlate / MediaPoolItem.AnalyzeForSlate markerColor

- **Object:** `MediaPoolItem / Folder`
- **Signature:** `(markerColor) -> Bool`
- **Behavior:** The shipped 21.0.2 scripting README says markerColor must be one of the resolve.MARKER_* constants (resolve.MARKER_BLUE etc.). Those constants do not exist: on Studio 21.0.2.4, [c for c in dir(resolve) if c.startswith('MARKER_')] is empty. There is therefore no documented-correct way to call this method. The plain colour string the server passes is the only option available, and it returns False here — though with AI Slate ID absent, a string-rejection bug cannot be distinguished from the missing pack on this machine.
- **Workaround / current handling:** Keep passing the plain colour name (server._MARKER_COLORS) — the documented constants are unavailable. Re-test on a machine with the AI Slate ID Extra installed before concluding the string form is rejected.
- **Tags:** ai, extras, missing-constant, documentation, resolve-21

### MediaPoolItem.SetClipProperty('Reel Name', ...)

- **Object:** `MediaPoolItem`
- **Signature:** `(propertyName, propertyValue) -> bool`
- **Behavior:** Setting the 'Reel Name' clip property returns True but the value is silently dropped on read-back when the project is configured to derive reel names automatically (General Options > 'Assist using reel names from the:' set to source clip file / embedding / filename pattern). The same True-but-unpersisted behavior occurs via SetMetadata('Reel Name', ...). Other clip properties on the same clip (e.g. 'Comments') write and persist normally, so this is field-specific, not a bridge/permission failure. Verified on Resolve 21.0.0; reported as issue #77.
- **Workaround / current handling:** After writing 'Reel Name', read it back with GetClipProperty('Reel Name') and refuse to report success on mismatch; surface the project-setting gate to the caller (server._verify_clip_property_writeback).
- **Reference:** [issue #77](https://github.com/samuelgursky/davinci-resolve-mcp/issues/77)
- **Tags:** unreliable-return, silent-failure, metadata, reel-name

### Timeline.DeleteClips (requires the Edit page; flaky first attempt)

- **Object:** `Timeline`
- **Signature:** `([TimelineItem], ripple) -> bool`
- **Behavior:** Two distinct failures share this call.

  **1. Wrong page (deterministic, has a mechanism).** With the UI on the Fairlight page, DeleteClips returns False and deletes nothing, no matter how many times it is retried. Verified 2026-08-04 on Studio 21.0: three identical retries against 132 valid, unlocked, present TimelineItems all returned False with all 132 still on the track; a single `Resolve.OpenPage("edit")` followed by the same call returned True and left 0 items. Track lock and enable state were confirmed clear before and after, so this is a page gate, not a lock. This is the case the previous entry's falsification condition anticipated — a retry seen to fail repeatedly — and revisiting it found the mechanism.

  **2. Flaky first attempt (one observation, no mechanism).** Independently of the page, the call has been seen once to return False with every item still present, where an identical immediate retry succeeded (Studio 21.0, cut-video edit session). Whether the UI was on the Edit page at the time was not recorded, so it cannot be ruled in or out as failure 1 in disguise. Do NOT read this as the ProjectManager.DeleteProject shape: that one has an identified mechanism (the project being, or recently having been, current) that retrying does not clear. One observation is still not a mechanism; if an immediate retry is ever seen to fail repeatedly while the UI is confirmed on the Edit page, this sub-entry needs revisiting.
- **Workaround / current handling:** Open the Edit page first (`Resolve.OpenPage("edit")`) — a caller that deletes clips from a script must not assume the user left the UI on Edit, and a Fairlight or Color session is a completely ordinary place for them to be. Then treat a False return as advisory: re-list the track and check whether the items are actually gone; if still present, retry the identical call once before failing. A readback that raised, enumerated nothing, or covered items whose unique ID cannot be read is UNKNOWN, not gone — never report an unverifiable delete as success, and do not spend a second destructive call on an outcome you equally cannot read.
- **Tags:** unreliable-return, flaky, silent-failure, page-dependent, timeline, edit

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

### TimelineItem.SetClipColor on generator/title items

- **Object:** `TimelineItem`
- **Signature:** `(colorName) -> bool`
- **Behavior:** On a generator or title item SetClipColor returns True with a VALID colour name and the colour does not persist — GetClipColor still reads '' immediately afterwards, and ClearClipColor changes nothing because there is nothing to clear. Measured on Studio 19.1.3.7 (2026-08-06) on a Solid Color generator. A media-backed item on the SAME timeline in the same session persists correctly (SetClipColor('Teal') -> True, GetClipColor -> 'Teal'), so the bool is honest for some items and a lie for others, with nothing in the return value to tell them apart. A timeline item's colour is also independent of its backing MediaPoolItem's: colouring the item leaves the pool clip at ''.
- **Workaround / current handling:** Never trust the bool alone — read GetClipColor back and compare. To mark a generator or title, use a timeline marker at its start instead; markers read back reliably.
- **Reference:** [issue #124](https://github.com/samuelgursky/davinci-resolve-mcp/issues/124)
- **Tags:** timeline-item, silent-failure, generator, readback-lies

### Project.SetRenderSettings (inherits the loaded preset)

- **Object:** `Project`
- **Signature:** `({settings}) -> bool`
- **Behavior:** SetRenderSettings applies the passed keys ON TOP of whatever render state the Deliver page is holding; it does not replace it. A loaded preset carries more state than the keys a caller passes, and that state survives. Measured 2026-07-08: after a render through the stock 'Audio Only' preset, a job queued with an explicit ExportVideo=True and an .mp4 target returned settings_success=True and a real job id, GetRenderJobList reported IsExportVideo=True, and the rendered .mp4 contained only an AAC stream with NO video stream (ffprobe) — 18 minutes of material 'rendered' in ~10 seconds. The job readback is therefore NOT a witness for the rendered file. There is also no way to detect the inherited state: the scripting API documents no GetRenderSettings and no GetCurrentRenderPresetName, so the base state can be pinned but never read.
- **Workaround / current handling:** Pin the base state instead of inheriting one — prepare_render_job(from_preset='<a video preset>') runs LoadRenderPreset before the explicit settings go on top (PresetName flips to 'Custom' once they do, which is expected). Then verify the OUTPUT, not the job: ffprobe for a codec_type=video stream. A long timeline that completes in seconds is the tell.
- **Reference:** [issue #123](https://github.com/samuelgursky/davinci-resolve-mcp/issues/123)
- **Tags:** render, deliver, silent-failure, preset, readback-lies

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
