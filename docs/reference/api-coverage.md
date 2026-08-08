# API Coverage and Test Results

Complete Resolve scripting API coverage, live-test status, and method-by-method reference.

## Key Stats

| Metric | Value |
|--------|-------|
| MCP Tools | **34** compound (default) / **341** granular |
| Kernel Actions | **136** guarded MCP workflow actions across 9 compound tools |
| API Methods Covered | **361/361** (100%) |
| Methods Live Tested | **338/361** (93.6%) |
| Live Test Pass Rate | **338/338** (100%) |
| API Object Classes | 13 |
| Tested Against | DaVinci Resolve 19.1.3 Studio + Resolve 20.3.2 Studio + Resolve 21.0.2 Studio + Resolve 21.0.3 **free** (via the in-app bridge) |
| Compatibility Note | Resolve 19.1.3 remains the compatibility baseline; Resolve 20.x scripting calls are additive, version-guarded, and live-tested on 20.3.2; Resolve 21.0 additions are version-guarded and live-tested on 21.0.2 (see the Resolve 21 delta row below — five wrappers need AI Extras packs and stay untested without one, and one is deliberately not executed). The Resolve 21.0.4 additions are version-guarded and unit-tested, but not live-tested here — the validation machine carries Studio 19.1.3 and free 21.0.3, neither of which is 21.0.4. Note the free build is reachable only through the in-app bridge, since the free edition refuses external scripting |

## API Coverage

Every non-deprecated method in the DaVinci Resolve Scripting API is covered. The default compound server exposes **34 tools** that group related operations by action parameter, keeping LLM context windows lean. The full granular server provides **341 individual tools** for power users. Both modes cover all 13 API object classes. MCP-level kernel actions are tracked separately in [Kernel Action Coverage](../kernels/README.md).

The 34th compound tool is `timeline_versioning` (C6) — an MCP-level workflow
tool, not a wrapper around a Resolve API method. It surfaces the
version-on-mutate hook that auto-archives the working timeline before any
destructive op, plus rollback and brain-edit history. See [SKILL.md](../SKILL.md)
for usage.

Workflow helpers can go beyond one-to-one API method coverage while still using
only public Resolve calls. For example, `media_pool.setup_multicam_timeline`
prepares a stacked timeline for Resolve's multicam UI, but native multicam clip
creation itself is not exposed by the scripting API. Similarly,
`media_analysis.detect_sync_events` is a source-safe FFmpeg/FFprobe helper for
advisory 2-pop and slate-clap sync points; it is not a Resolve API method.
`media_analysis.add_sync_event_markers` is an explicit marker-write helper for
standalone sync detections. `media_analysis.publish_clip_metadata` bridges
source-safe analysis reports back into Resolve clip metadata with opt-out
dry-run previews, field-specific merge policies, and default metadata/marker
writeback for executed Resolve-target analysis. Vision uses host_chat_paths by
default: analyze actions return frame_paths, a `shot_table` listing each shot
range with its in-shot `frame_indices`, and a JSON schema requiring one
`shot_descriptions` entry per shot. The host chat finalizes per-clip visual
analysis via `media_analysis.commit_vision`, which merges the visual report,
maps `shot_descriptions[shot_index]` onto Media Pool shot markers, and triggers
metadata writeback for that clip. Works with any MCP client whose chat model
is vision-capable; no `sampling/createMessage` support required.

Some Edit-page behavior is simply not reachable through public scripting. The
**Source/Auto Track Selector** (the patch panel that chooses which video track a
clip lands on) has no get/set in the API, and the `Insert*IntoTimeline` family
(titles, generators, OFX, Fusion comps) takes no `trackIndex` — they always drop
onto the selector's current target (V1 in practice). Locking lower tracks does
not redirect the insert; it just makes the insert fail. Titles and generators
can't be relocated afterward either, since they have no `MediaPoolItem` for
`AppendToTimeline`/`MoveClips` to act on. For media-backed clips you *can* target
a track via `MediaPool.AppendToTimeline`'s clipInfo `trackIndex` (exposed as
`media_pool.append_to_timeline` with `clip_infos`). This limitation is recorded
in the verified `api_truth` ledger (query `resolve_control api_truth "track"`);
see issue #74.

The full catalogue of verified scripting-API gaps and bugs — curated for
submission to Blackmagic Design's developer feedback — lives in
[api-limitations.md](api-limitations.md). It is generated from the `submit`-tagged
`api_truth` entries (`scripts/gen_api_limitations.py`) and kept in sync by a drift
guard, so it never goes stale.

| Class | Methods | Tools | Description |
|-------|---------|-------|-------------|
| Resolve | 22 | 22 | App control, pages, layout presets, render/burn-in presets, keyframe mode |
| ProjectManager | 25 | 25 | Project CRUD, folders, databases, cloud projects, archive/restore |
| Project | 43 | 43 | Timelines, render pipeline, settings, LUTs, color groups |
| MediaStorage | 9 | 9 | Volumes, file browsing, media import, mattes |
| MediaPool | 27 | 27 | Folders, clips, timelines, metadata, stereo, sync |
| Folder | 8 | 8 | Clip listing, export, transcription |
| MediaPoolItem | 36 | 36 | Metadata, markers, flags, properties, proxy, transcription |
| Timeline | 58 | 58 | Tracks, markers, items, export, generators, titles, stills, stereo |
| TimelineItem | 80 | 80 | Properties, markers, Fusion comps, versions, takes, CDL, AI tools |
| Gallery | 8 | 8 | Albums, stills, power grades |
| GalleryStillAlbum | 6 | 6 | Stills management, import/export, labels |
| Graph | 11 | 22 | Node operations, LUTs, cache, grades (timeline + clip graph variants) |
| ColorGroup | 5 | 10 | Group management, pre/post clip node graphs |

## Test Results

Baseline testing was performed against **DaVinci Resolve 19.1.3 Studio** on macOS with live API calls (no mocks). Resolve 20 additions were revalidated live against **DaVinci Resolve 20.3.2 Studio**, Resolve 21 additions against **Studio 21.0.2.4**.

**Counting convention.** Every figure on this page is derived from the rows of
the [Complete API Reference](#complete-api-reference) tables — that table is the
source, these summaries are downstream of it:

- **API Methods Covered** = the number of rows. One row per method per object
  class, so `PerformAudioClassification` on both `Folder` and `MediaPoolItem`
  counts twice, because they are two wrappers that can fail independently.
- **Methods Live Tested** = rows marked ✅ or ⚠️ — the call was made against a
  live Resolve and the result observed.
- **Untested** = rows marked ☁️ or 🔬. A method that could not be executed is
  never counted as a pass: a missing Extras pack tells you nothing about the
  wrapper, so counting it as tested would overstate coverage in exactly the
  place the risk is highest.
- **The phase table below counts methods, not test cases**, which is why its
  Total equals Methods Live Tested rather than the number of assertions run.


| Phase | Tests | Pass Rate | Scope |
|-------|-------|-----------|-------|
| Phase 1 | 204/204 | 100% | Safe read-only operations across all classes |
| Phase 2 | 79/79 | 100% | Destructive operations with create-test-cleanup patterns |
| Phase 3 | 20/20 | 100% | Real media import, sync, transcription, database switching, Resolve.Quit |
| Phase 4 | 10/10 | 100% | AI/ML methods, Fusion clips, stereo, gallery stills |
| Phase 5 | 6/6 | 100% | Scene cuts, subtitles from audio, graph node cache/tools/enable |
| Resolve 20 delta | 12/12 | 100% | Resolve 20.0-20.2.2 scripting additions live-tested on 20.3.2 |
| Resolve 21 delta | 7/7 | 100% | Resolve 21.0 additions that could be executed, live-tested on Studio 21.0.2.4 (`tests/live_resolve21_validation.py`). The other 6 need an AI Extras pack or are unsafe to run — counted as untested, not as passes |
| **Total** | **338/338** | **100%** | **93.6% of the 361 covered methods tested live** |

#### Resolve 21 delta detail

Run on Studio 21.0.2.4, macOS/Apple Silicon, with **only the AI Motion Deblur
Extra installed**. Three of these methods require an Extras pack that was
absent, so their result says nothing about the wrapper — that is why they are
marked 🔬 rather than ⚠️.

| Method | Result | Evidence |
|--------|--------|----------|
| `MediaPoolItem/Folder.PerformAudioClassification` | ✅ | Returned True; `Category` clip property went `""` → `Dialogue` |
| `MediaPoolItem/Folder.ClearAudioClassification` | ✅ | Returned True; `Category` reset to `Uncategorized` (not `""`) |
| `MediaPoolItem/Folder.TranscribeAudio(useSpeakerDetection)` | ⚠️ | Parameter accepted; `True` and `False` produced identical transcripts on a two-voice clip |
| `MediaPoolItem/Folder.RemoveMotionBlur` | ✅ | Returned a MediaPoolItem; source media path unchanged |
| `Project.ResetIntellisearchAnalysis` | ✅ | Returned True — new in the 21.0.2 scripting doc, previously unwrapped |
| `MediaPoolItem/Folder.AnalyzeForIntellisearch` | 🔬 | Requires AI IntelliSearch; returned an error **string**, not False — see api-limitations |
| `MediaPoolItem/Folder.AnalyzeForSlate` | 🔬 | Requires AI Slate ID; returned False. Documented `resolve.MARKER_*` constants do not exist on the handle |
| `Project.GenerateSpeech` | 🔬 | Requires AI Speech Generator; returned an error **string**, not a MediaPoolItem |
| `Resolve.DisableBackgroundTasksForCurrentResolveSession` | 🔬 | Present in `dir()`; **not executed** — session-wide, returns None, and has no `Enable...` counterpart, so there is no undo short of restarting Resolve |

### Untested Methods (23 of 361)

Every ☁️ and 🔬 row from the reference tables, listed here so the count is
checkable rather than asserted.

| Method | Reason | Help Wanted |
|--------|--------|-------------|
| `PM.CreateCloudProject` | Requires DaVinci Resolve cloud infrastructure | Yes |
| `PM.LoadCloudProject` | Requires DaVinci Resolve cloud infrastructure | Yes |
| `PM.ImportCloudProject` | Requires DaVinci Resolve cloud infrastructure | Yes |
| `PM.RestoreCloudProject` | Requires DaVinci Resolve cloud infrastructure | Yes |
| `TL.AnalyzeDolbyVision` | Requires HDR/Dolby Vision content | Yes |
| `Folder.AnalyzeForIntellisearch` | Requires the AI IntelliSearch Extra | Yes |
| `MPI.AnalyzeForIntellisearch` | Requires the AI IntelliSearch Extra | Yes |
| `Folder.AnalyzeForSlate` | Requires the AI Slate ID Extra | Yes |
| `MPI.AnalyzeForSlate` | Requires the AI Slate ID Extra | Yes |
| `Project.GenerateSpeech` | Requires the AI Speech Generator Extra | Yes |
| `Resolve.DisableBackgroundTasksForCurrentResolveSession` | Deliberately not executed: session-wide, returns `None`, and has no `Enable...` counterpart, so there is no undo short of restarting Resolve | No |
| `MPI.GetTimeline` | Requires a Resolve 21.0.4 build; the validation machine runs Studio 19.1.3 and free 21.0.3 | Yes |
| `TL.GetSelectedClips` | Requires a Resolve 21.0.4 build; the validation machine runs 19.1.3 | Yes |
| `Resolve.GetLayoutPresetList` | Requires a Resolve 21.0.4 build; the validation machine runs Studio 19.1.3 and free 21.0.3 | Yes |
| `Resolve.GetBurnInPresetList` | Requires a Resolve 21.0.4 build; the validation machine runs Studio 19.1.3 and free 21.0.3 | Yes |
| `Resolve.DeleteBurnInPreset` | Requires a Resolve 21.0.4 build; also, no scripting API creates a burn-in preset to round-trip against | Yes |
| `Resolve.GetUserPreferencesPresetList` | Requires a Resolve 21.0.4 build; the validation machine runs Studio 19.1.3 and free 21.0.3 | Yes |
| `Resolve.SaveUserPreferencesPreset` | Requires a Resolve 21.0.4 build; the validation machine runs Studio 19.1.3 and free 21.0.3 | Yes |
| `Resolve.LoadUserPreferencesPreset` | Deliberately not executed even by the reporter: swaps the user's global preferences session-wide | No |
| `Resolve.DeleteUserPreferencesPreset` | Requires a Resolve 21.0.4 build; the validation machine runs Studio 19.1.3 and free 21.0.3 | Yes |
| `Resolve.ImportUserPreferencesPreset` | Requires a Resolve 21.0.4 build and a preset file to import | Yes |
| `Resolve.ExportUserPreferencesPreset` | Requires a Resolve 21.0.4 build; the validation machine runs Studio 19.1.3 and free 21.0.3 | Yes |
| `PM.GetProjectAttributesInCurrentFolder` | Requires a Resolve 21.0.4 build; the validation machine runs Studio 19.1.3 and free 21.0.3 | Yes |

The five AI Extras rows are untested for want of a downloadable pack, not because
the wrappers are suspect — a report from anyone who has the packs installed would
close them. The twelve 21.0.4 rows are untested for want of the build: this machine
runs 19.1.3, so they are guarded and unit-tested against stubs and carry a
contributor's report rather than a result of ours (issue #131 for the first two;
issues #135–#138 for the ten from the 24 Jul 2026 README refresh, several with
save→list→delete round-trips on Studio 21.0.4.5). The remaining one is a
decision rather than a gap: it is reachable, and
running it during a validation sweep would disable background tasks for every
project open in that Resolve instance.

---

## Complete API Reference

Every method in the DaVinci Resolve Scripting API and its test status. Methods are listed by object class.

**Status Key:**
- ✅ = Tested live, returned expected result
- ⚠️ = Tested live, API accepted call (returned `False` — needs specific context to fully execute)
- ☁️ = Requires cloud infrastructure (untested)
- 🔬 = Requires specific content/hardware (untested — PRs welcome)

### Resolve

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `Fusion()` | ✅ | Returns Fusion object |
| 2 | `GetMediaStorage()` | ✅ | Returns MediaStorage object |
| 3 | `GetProjectManager()` | ✅ | Returns ProjectManager object |
| 4 | `OpenPage(pageName)` | ✅ | Switches Resolve page |
| 5 | `GetCurrentPage()` | ✅ | Returns current page name (e.g. `"edit"`) |
| 6 | `GetProductName()` | ✅ | Returns `"DaVinci Resolve Studio"` |
| 7 | `GetVersion()` | ✅ | Returns `[19, 1, 3, 7, '']` |
| 8 | `GetVersionString()` | ✅ | Returns `"19.1.3.7"` |
| 9 | `LoadLayoutPreset(presetName)` | ✅ | Loads saved layout |
| 10 | `UpdateLayoutPreset(presetName)` | ✅ | Updates existing preset |
| 11 | `ExportLayoutPreset(presetName, presetFilePath)` | ✅ | Exports preset to file |
| 12 | `DeleteLayoutPreset(presetName)` | ✅ | Deletes preset |
| 13 | `SaveLayoutPreset(presetName)` | ⚠️ | API accepts; returns `False` when preset name conflicts |
| 14 | `ImportLayoutPreset(presetFilePath, presetName)` | ✅ | Imports preset from file |
| 15 | `Quit()` | ✅ | Quits DaVinci Resolve |
| 16 | `ImportRenderPreset(presetPath)` | ⚠️ | API accepts; needs valid preset file |
| 17 | `ExportRenderPreset(presetName, exportPath)` | ⚠️ | API accepts; needs valid preset name |
| 18 | `ImportBurnInPreset(presetPath)` | ⚠️ | API accepts; needs valid preset file |
| 19 | `ExportBurnInPreset(presetName, exportPath)` | ⚠️ | API accepts; needs valid preset name |
| 20 | `GetKeyframeMode()` | ✅ | Returns keyframe mode |
| 21 | `SetKeyframeMode(keyframeMode)` | ⚠️ | API accepts; mode must match valid enum |
| 22 | `GetFairlightPresets()` | ✅ | Returns a preset map. Live on 20.3.2 Studio and 21.0.3 free; **absent below 20.2.2** — confirmed missing on 19.1.3, so the version floor is verified from both sides |
| 23 | `DisableBackgroundTasksForCurrentResolveSession()` | 🔬 | Resolve 21.0. Present in `dir()`; **not executed** — session-wide, returns `None`, no `Enable...` counterpart, so no undo short of restarting Resolve |
| 24 | `GetLayoutPresetList()` | 🔬 | Resolve 21.0.4 (24 Jul 2026 README). Not executed here — no 21.0.4 build; reporter's save→list→delete round-trip on Studio 21.0.4.5 in issue #137 |
| 25 | `GetBurnInPresetList()` | 🔬 | Resolve 21.0.4. Not executed here; reported returning a list on Studio 21.0.4.5 in issue #136 |
| 26 | `DeleteBurnInPreset(presetName)` | 🔬 | Resolve 21.0.4. `dir()`-present on 21.0.4.5 (issue #136); not executed anywhere — no scripting API creates a burn-in preset to round-trip against |
| 27 | `GetUserPreferencesPresetList()` | 🔬 | Resolve 21.0.4. Not executed here; reporter's save→list→delete round-trip on Studio 21.0.4.5 in issue #138 |
| 28 | `SaveUserPreferencesPreset(presetName)` | 🔬 | Resolve 21.0.4. Not executed here; part of the issue #138 round-trip on 21.0.4.5 |
| 29 | `LoadUserPreferencesPreset(presetName)` | 🔬 | Resolve 21.0.4. `dir()`-present on 21.0.4.5; **not executed** even by the reporter — swaps the user's global preferences session-wide (issue #138) |
| 30 | `DeleteUserPreferencesPreset(presetName)` | 🔬 | Resolve 21.0.4. Not executed here; part of the issue #138 round-trip on 21.0.4.5 |
| 31 | `ImportUserPreferencesPreset(presetFilePath, presetName)` | 🔬 | Resolve 21.0.4. `dir()`-present on 21.0.4.5 only (issue #138) — no preset file was on hand. Per the README the imported preset is **not** auto-loaded |
| 32 | `ExportUserPreferencesPreset(presetName, exportPath)` | 🔬 | Resolve 21.0.4. `dir()`-present on 21.0.4.5 only (issue #138) |

### ProjectManager

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `ArchiveProject(projectName, filePath, ...)` | ⚠️ | API accepts; archiving is slow |
| 2 | `CreateProject(projectName, mediaLocationPath)` | ✅ | Creates new project; optional media location added in Resolve 20.2.2 |
| 3 | `DeleteProject(projectName)` | ⚠️ | Returns `False` if project is open |
| 4 | `LoadProject(projectName)` | ✅ | Returns Project object |
| 5 | `GetCurrentProject()` | ✅ | Returns current Project |
| 6 | `SaveProject()` | ✅ | Saves current project |
| 7 | `CloseProject(project)` | ✅ | Closes project |
| 8 | `CreateFolder(folderName)` | ✅ | Creates project folder |
| 9 | `DeleteFolder(folderName)` | ✅ | Deletes project folder |
| 10 | `GetProjectListInCurrentFolder()` | ✅ | Returns project name list |
| 11 | `GetFolderListInCurrentFolder()` | ✅ | Returns folder name list |
| 12 | `GotoRootFolder()` | ✅ | Navigates to root |
| 13 | `GotoParentFolder()` | ✅ | Returns `False` at root (expected) |
| 14 | `GetCurrentFolder()` | ✅ | Returns current folder name |
| 15 | `OpenFolder(folderName)` | ✅ | Opens folder |
| 16 | `ImportProject(filePath, projectName)` | ✅ | Imports .drp file |
| 17 | `ExportProject(projectName, filePath, ...)` | ✅ | Exports .drp file |
| 18 | `RestoreProject(filePath, projectName)` | ⚠️ | API accepts; needs backup archive |
| 19 | `GetCurrentDatabase()` | ✅ | Returns `{DbType, DbName}` |
| 20 | `GetDatabaseList()` | ✅ | Returns list of databases |
| 21 | `SetCurrentDatabase({dbInfo})` | ✅ | Switches database |
| 22 | `CreateCloudProject({cloudSettings})` | ☁️ | Requires cloud infrastructure |
| 23 | `LoadCloudProject({cloudSettings})` | ☁️ | Requires cloud infrastructure |
| 24 | `ImportCloudProject(filePath, {cloudSettings})` | ☁️ | Requires cloud infrastructure |
| 25 | `RestoreCloudProject(folderPath, {cloudSettings})` | ☁️ | Requires cloud infrastructure |
| 26 | `GetProjectAttributesInCurrentFolder()` | 🔬 | Resolve 21.0.4 (24 Jul 2026 README). Not executed here — no 21.0.4 build; reported live on Studio 21.0.4.5 in issue #135, returning `lastModifiedDate` / `creationDate` / `notes` / `liveCollaborationMode` for all 8 projects in the current folder |

### Project

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetMediaPool()` | ✅ | Returns MediaPool object |
| 2 | `GetTimelineCount()` | ✅ | Returns integer count |
| 3 | `GetTimelineByIndex(idx)` | ✅ | Returns Timeline object |
| 4 | `GetCurrentTimeline()` | ✅ | Returns current Timeline |
| 5 | `SetCurrentTimeline(timeline)` | ✅ | Sets active timeline |
| 6 | `GetGallery()` | ✅ | Returns Gallery object |
| 7 | `GetName()` | ✅ | Returns project name |
| 8 | `SetName(projectName)` | ⚠️ | Returns `False` on open project |
| 9 | `GetPresetList()` | ✅ | Returns preset list with dimensions |
| 10 | `SetPreset(presetName)` | ⚠️ | API accepts; preset must exist |
| 11 | `AddRenderJob()` | ✅ | Returns job ID string |
| 12 | `DeleteRenderJob(jobId)` | ✅ | Deletes render job |
| 13 | `DeleteAllRenderJobs()` | ✅ | Clears render queue |
| 14 | `GetRenderJobList()` | ✅ | Returns job list |
| 15 | `GetRenderPresetList()` | ✅ | Returns preset names |
| 16 | `StartRendering(...)` | ✅ | Starts render |
| 17 | `StopRendering()` | ✅ | Stops render |
| 18 | `IsRenderingInProgress()` | ✅ | Returns `False` when idle |
| 19 | `LoadRenderPreset(presetName)` | ✅ | Loads render preset |
| 20 | `SaveAsNewRenderPreset(presetName)` | ✅ | Creates render preset |
| 21 | `DeleteRenderPreset(presetName)` | ✅ | Deletes render preset |
| 22 | `SetRenderSettings({settings})` | ✅ | Applies render settings; Resolve 20.2 adds `ExportSubtitle` and `SubtitleFormat` keys; Resolve 21.0.4 adds `UseFullExtents`, `AddFrameHandles` and `DataBurnIn` — `AddFrameHandles` is accepted and then ignored while `UseFullExtents` is true, so the server returns it as a warning |
| 23 | `GetRenderJobStatus(jobId)` | ✅ | Returns `{JobStatus, CompletionPercentage}` |
| 24 | `GetQuickExportRenderPresets()` | ✅ | Returns preset names |
| 25 | `RenderWithQuickExport(preset, {params})` | ✅ | Initiates quick export |
| 26 | `GetSetting(settingName)` | ✅ | Returns project settings dict |
| 27 | `SetSetting(settingName, settingValue)` | ✅ | Sets project setting |
| 28 | `GetRenderFormats()` | ✅ | Returns format map |
| 29 | `GetRenderCodecs(renderFormat)` | ✅ | Returns codec map |
| 30 | `GetCurrentRenderFormatAndCodec()` | ✅ | Returns `{format, codec}` |
| 31 | `SetCurrentRenderFormatAndCodec(format, codec)` | ✅ | Sets format and codec |
| 32 | `GetCurrentRenderMode()` | ✅ | Returns mode integer |
| 33 | `SetCurrentRenderMode(renderMode)` | ✅ | Sets render mode |
| 34 | `GetRenderResolutions(format, codec)` | ✅ | Returns resolution list |
| 35 | `RefreshLUTList()` | ✅ | Refreshes LUT list |
| 36 | `GetUniqueId()` | ✅ | Returns UUID string |
| 37 | `InsertAudioToCurrentTrackAtPlayhead(...)` | ⚠️ | Tested; needs Fairlight page context |
| 38 | `LoadBurnInPreset(presetName)` | ⚠️ | API accepts; preset must exist |
| 39 | `ExportCurrentFrameAsStill(filePath)` | ⚠️ | API accepts; needs valid playhead position |
| 40 | `GetColorGroupsList()` | ✅ | Returns color group list |
| 41 | `AddColorGroup(groupName)` | ✅ | Returns ColorGroup object |
| 42 | `DeleteColorGroup(colorGroup)` | ✅ | Deletes color group |
| 43 | `ApplyFairlightPresetToCurrentTimeline(presetName)` | ⚠️ | Accepts the call and returns `False` when handed a name that does not exist. **Never exercised against a genuinely saved preset**, so a `True` path has not been observed — the API has no way to create one, and `GetFairlightPresets` reported an empty map on both test machines. To clear this: save a mix as a Fairlight preset in the UI, then apply it by that name. Requires 20.2.2+ |
| 44 | `GenerateSpeech({speechGenerationSettings}, timecode)` | 🔬 | Resolve 21.0. Requires the AI Speech Generator Extra; without it returns an error **string**, not a MediaPoolItem |
| 45 | `ResetIntellisearchAnalysis()` | ✅ | Resolve 21.0.2 live test returns `True` |

### MediaStorage

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetMountedVolumeList()` | ✅ | Returns mounted volume paths |
| 2 | `GetSubFolderList(folderPath)` | ✅ | Returns subfolder paths |
| 3 | `GetFileList(folderPath)` | ✅ | Returns file paths |
| 4 | `RevealInStorage(path)` | ✅ | Reveals path in Media Storage |
| 5 | `AddItemListToMediaPool(...)` | ✅ | Imports media, returns clips |
| 6 | `AddClipMattesToMediaPool(item, [paths], eye)` | ✅ | Adds clip mattes |
| 7 | `AddTimelineMattesToMediaPool([paths])` | ✅ | Returns MediaPoolItem list |

### MediaPool

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetRootFolder()` | ✅ | Returns root Folder |
| 2 | `AddSubFolder(folder, name)` | ✅ | Creates subfolder |
| 3 | `RefreshFolders()` | ✅ | Refreshes folder list |
| 4 | `CreateEmptyTimeline(name)` | ✅ | Creates timeline |
| 5 | `AppendToTimeline(...)` | ✅ | Appends clips, returns TimelineItems |
| 6 | `CreateTimelineFromClips(name, ...)` | ✅ | Creates timeline from clips |
| 7 | `ImportTimelineFromFile(filePath, {options})` | ✅ | Imports AAF/EDL/XML |
| 8 | `DeleteTimelines([timeline])` | ✅ | Deletes timelines |
| 9 | `GetCurrentFolder()` | ✅ | Returns current Folder |
| 10 | `SetCurrentFolder(folder)` | ✅ | Sets current folder |
| 11 | `DeleteClips([clips])` | ✅ | Deletes clips |
| 12 | `ImportFolderFromFile(filePath)` | ✅ | Imports DRB folder |
| 13 | `DeleteFolders([subfolders])` | ✅ | Deletes folders |
| 14 | `MoveClips([clips], targetFolder)` | ✅ | Moves clips |
| 15 | `MoveFolders([folders], targetFolder)` | ✅ | Moves folders |
| 16 | `GetClipMatteList(item)` | ✅ | Returns matte paths |
| 17 | `GetTimelineMatteList(folder)` | ✅ | Returns matte items |
| 18 | `DeleteClipMattes(item, [paths])` | ✅ | Deletes clip mattes |
| 19 | `RelinkClips([items], folderPath)` | ⚠️ | API accepts; needs offline clips |
| 20 | `UnlinkClips([items])` | ✅ | Unlinks clips |
| 21 | `ImportMedia([items])` | ✅ | Imports media files |
| 22 | `ExportMetadata(fileName, [clips])` | ✅ | Exports metadata CSV |
| 23 | `GetUniqueId()` | ✅ | Returns UUID string |
| 24 | `CreateStereoClip(left, right)` | ✅ | Creates stereo pair |
| 25 | `AutoSyncAudio([items], {settings})` | ⚠️ | Tested; needs matching A/V clips |
| 26 | `GetSelectedClips()` | ✅ | Returns selected clips |
| 27 | `SetSelectedClip(item)` | ✅ | Selects clip |

### Folder

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetClipList()` | ✅ | Returns clip list |
| 2 | `GetName()` | ✅ | Returns folder name |
| 3 | `GetSubFolderList()` | ✅ | Returns subfolder list |
| 4 | `GetIsFolderStale()` | ✅ | Returns `False` |
| 5 | `GetUniqueId()` | ✅ | Returns UUID string |
| 6 | `Export(filePath)` | ✅ | Exports DRB file |
| 7 | `TranscribeAudio({useSpeakerDetection})` | ✅ | Starts audio transcription. Resolve 21.0 added the optional `useSpeakerDetection` argument: it is accepted, but `True` and `False` produced identical transcripts on a deliberately two-voice clip (21.0.2.4) — the method passes, the parameter has no observable effect |
| 8 | `ClearTranscription()` | ✅ | Clears transcription |
| 9 | `PerformAudioClassification()` | ✅ | Resolve 21.0.2 live test returns `True`; `Category` clip property goes `""` → `Dialogue` |
| 10 | `ClearAudioClassification()` | ✅ | Resolve 21.0.2 live test returns `True`; `Category` resets to `Uncategorized`, not `""` |
| 11 | `AnalyzeForIntellisearch(identifyFaces, isBetterMode)` | 🔬 | Resolve 21.0. Requires the AI IntelliSearch Extra; without it returns an error **string**, not `False` |
| 12 | `AnalyzeForSlate(markerColor)` | 🔬 | Resolve 21.0. Requires the AI Slate ID Extra. Documented `resolve.MARKER_*` constants do not exist on the handle |
| 13 | `RemoveMotionBlur({deblurOption})` | ✅ | Resolve 21.0.2 live test returns original→new pairs; source media unchanged. Requires the AI Motion Deblur Extra |

### MediaPoolItem

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetName()` | ✅ | Returns clip name |
| 2 | `GetMetadata(metadataType)` | ✅ | Returns metadata dict |
| 3 | `SetMetadata(type, value)` | ✅ | Sets metadata |
| 4 | `GetThirdPartyMetadata(type)` | ✅ | Returns third-party metadata |
| 5 | `SetThirdPartyMetadata(type, value)` | ✅ | Sets third-party metadata |
| 6 | `GetMediaId()` | ✅ | Returns media UUID |
| 7 | `AddMarker(frameId, color, name, note, duration, customData)` | ✅ | Adds marker |
| 8 | `GetMarkers()` | ✅ | Returns marker dict |
| 9 | `GetMarkerByCustomData(customData)` | ✅ | Finds marker by data |
| 10 | `UpdateMarkerCustomData(frameId, customData)` | ✅ | Updates marker data |
| 11 | `GetMarkerCustomData(frameId)` | ✅ | Returns custom data string |
| 12 | `DeleteMarkersByColor(color)` | ✅ | Deletes markers by color |
| 13 | `DeleteMarkerAtFrame(frameNum)` | ⚠️ | Returns `False` if no marker at frame |
| 14 | `DeleteMarkerByCustomData(customData)` | ⚠️ | Returns `False` if no match |
| 15 | `AddFlag(color)` | ✅ | Adds flag |
| 16 | `GetFlagList()` | ✅ | Returns flag colors |
| 17 | `ClearFlags(color)` | ✅ | Clears flags |
| 18 | `GetClipColor()` | ✅ | Returns clip color |
| 19 | `SetClipColor(colorName)` | ✅ | Sets clip color |
| 20 | `ClearClipColor()` | ✅ | Clears clip color |
| 21 | `GetClipProperty(propertyName)` | ✅ | Returns property dict |
| 22 | `SetClipProperty(propertyName, value)` | ⚠️ | API accepts; some properties read-only |
| 23 | `LinkProxyMedia(proxyMediaFilePath)` | ✅ | Links proxy media |
| 24 | `UnlinkProxyMedia()` | ✅ | Unlinks proxy media |
| 25 | `ReplaceClip(filePath)` | ✅ | Replaces clip source |
| 26 | `GetUniqueId()` | ✅ | Returns UUID string |
| 27 | `TranscribeAudio({useSpeakerDetection})` | ✅ | Starts audio transcription. Resolve 21.0 added the optional `useSpeakerDetection` argument: it is accepted, but `True` and `False` produced identical transcripts on a deliberately two-voice clip (21.0.2.4) — the method passes, the parameter has no observable effect |
| 28 | `ClearTranscription()` | ✅ | Clears transcription |
| 29 | `GetAudioMapping()` | ✅ | Returns JSON audio mapping |
| 30 | `GetMarkInOut()` | ✅ | Returns mark in/out dict |
| 31 | `SetMarkInOut(in, out, type)` | ✅ | Sets mark in/out |
| 32 | `ClearMarkInOut(type)` | ✅ | Clears mark in/out |
| 33 | `SetName(clipName)` | ✅ | Resolve 20.3.2 live test renames clip |
| 34 | `LinkFullResolutionMedia(filePath)` | ⚠️ | Resolve 20.3.2 live test accepts call; full-res relink returns `False` without a matching proxy/full-res fixture |
| 35 | `ReplaceClipPreserveSubClip(filePath)` | ✅ | Resolve 20.3.2 live test replaces clip while preserving subclip metadata |
| 36 | `MonitorGrowingFile()` | ✅ | Resolve 20.3.2 live test enables growing-file monitoring |
| 37 | `PerformAudioClassification()` | ✅ | Resolve 21.0.2 live test returns `True`; `Category` clip property goes `""` → `Dialogue` |
| 38 | `ClearAudioClassification()` | ✅ | Resolve 21.0.2 live test returns `True`; `Category` resets to `Uncategorized`, not `""` |
| 39 | `AnalyzeForIntellisearch(identifyFaces, isBetterMode)` | 🔬 | Resolve 21.0. Requires the AI IntelliSearch Extra; without it returns an error **string**, not `False` |
| 40 | `AnalyzeForSlate(markerColor)` | 🔬 | Resolve 21.0. Requires the AI Slate ID Extra. Documented `resolve.MARKER_*` constants do not exist on the handle |
| 41 | `RemoveMotionBlur({deblurOption})` | ✅ | Resolve 21.0.2 live test returns the new MediaPoolItem; source media path unchanged. Requires the AI Motion Deblur Extra |
| 42 | `GetTimeline()` | 🔬 | Resolve 21.0.4. Not executed here — no 21.0.4 build on hand; reported working on Studio 21.0.4.5 in issue #131 |

### Timeline

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetName()` | ✅ | Returns timeline name |
| 2 | `SetName(timelineName)` | ⚠️ | Returns `False` on active timeline |
| 3 | `GetStartFrame()` | ✅ | Returns start frame |
| 4 | `GetEndFrame()` | ✅ | Returns end frame |
| 5 | `SetStartTimecode(timecode)` | ✅ | Sets start timecode |
| 6 | `GetStartTimecode()` | ✅ | Returns `"01:00:00:00"` |
| 7 | `GetTrackCount(trackType)` | ✅ | Returns track count |
| 8 | `AddTrack(trackType, subTrackType)` | ✅ | Adds track |
| 9 | `DeleteTrack(trackType, trackIndex)` | ✅ | Deletes track |
| 10 | `GetTrackSubType(trackType, trackIndex)` | ✅ | Returns sub-type (e.g. `"stereo"`) |
| 11 | `SetTrackEnable(trackType, trackIndex, enabled)` | ✅ | Enables/disables track |
| 12 | `GetIsTrackEnabled(trackType, trackIndex)` | ✅ | Returns enabled state |
| 13 | `SetTrackLock(trackType, trackIndex, locked)` | ✅ | Locks/unlocks track |
| 14 | `GetIsTrackLocked(trackType, trackIndex)` | ✅ | Returns lock state |
| 15 | `DeleteClips([timelineItems], ripple)` | ✅ | Deletes clips from timeline |
| 16 | `SetClipsLinked([timelineItems], linked)` | ✅ | Links/unlinks clips |
| 17 | `GetItemListInTrack(trackType, index)` | ✅ | Returns items on track |
| 18 | `AddMarker(frameId, color, name, note, duration, customData)` | ✅ | Adds timeline marker |
| 19 | `GetMarkers()` | ✅ | Returns marker dict |
| 20 | `GetMarkerByCustomData(customData)` | ✅ | Finds marker by data |
| 21 | `UpdateMarkerCustomData(frameId, customData)` | ✅ | Updates marker data |
| 22 | `GetMarkerCustomData(frameId)` | ✅ | Returns custom data |
| 23 | `DeleteMarkersByColor(color)` | ✅ | Deletes markers by color |
| 24 | `DeleteMarkerAtFrame(frameNum)` | ⚠️ | Returns `False` if no marker at frame |
| 25 | `DeleteMarkerByCustomData(customData)` | ⚠️ | Returns `False` if no match |
| 26 | `GetCurrentTimecode()` | ✅ | Returns timecode string |
| 27 | `SetCurrentTimecode(timecode)` | ⚠️ | Returns `False` if playback not active |
| 28 | `GetCurrentVideoItem()` | ✅ | Returns item at playhead |
| 29 | `GetCurrentClipThumbnailImage()` | ✅ | Returns thumbnail data |
| 30 | `GetTrackName(trackType, trackIndex)` | ✅ | Returns track name |
| 31 | `SetTrackName(trackType, trackIndex, name)` | ✅ | Sets track name |
| 32 | `DuplicateTimeline(timelineName)` | ✅ | Duplicates timeline |
| 33 | `CreateCompoundClip([items], {clipInfo})` | ✅ | Returns compound clip item |
| 34 | `CreateFusionClip([timelineItems])` | ✅ | Returns Fusion clip item |
| 35 | `ImportIntoTimeline(filePath, {options})` | ⚠️ | Tested; result depends on file format |
| 36 | `Export(fileName, exportType, exportSubtype)` | ✅ | Exports EDL/XML/AAF |
| 37 | `GetSetting(settingName)` | ✅ | Returns settings dict |
| 38 | `SetSetting(settingName, settingValue)` | ⚠️ | API accepts; some settings read-only |
| 39 | `InsertGeneratorIntoTimeline(name)` | ✅ | Inserts generator |
| 40 | `InsertFusionGeneratorIntoTimeline(name)` | ✅ | Inserts Fusion generator |
| 41 | `InsertFusionCompositionIntoTimeline()` | ✅ | Inserts Fusion composition |
| 42 | `InsertOFXGeneratorIntoTimeline(name)` | ⚠️ | API accepts; needs valid OFX plugin |
| 43 | `InsertTitleIntoTimeline(name)` | ✅ | Inserts title |
| 44 | `InsertFusionTitleIntoTimeline(name)` | ✅ | Inserts Fusion title |
| 45 | `GrabStill()` | ✅ | Returns GalleryStill object |
| 46 | `GrabAllStills(stillFrameSource)` | ✅ | Returns list of GalleryStill objects |
| 47 | `GetUniqueId()` | ✅ | Returns UUID string |
| 48 | `CreateSubtitlesFromAudio({settings})` | ✅ | Returns `True` — creates subtitles from audio |
| 49 | `DetectSceneCuts()` | ✅ | Returns `True` — detects scene cuts in timeline |
| 50 | `ConvertTimelineToStereo()` | ✅ | Converts timeline to stereo 3D |
| 51 | `GetNodeGraph()` | ✅ | Returns Graph object |
| 52 | `AnalyzeDolbyVision([items], analysisType)` | 🔬 | Requires HDR/Dolby Vision content |
| 53 | `GetMediaPoolItem()` | ✅ | Returns MediaPoolItem for timeline |
| 54 | `GetMarkInOut()` | ✅ | Returns mark in/out dict |
| 55 | `SetMarkInOut(in, out, type)` | ✅ | Sets mark in/out |
| 56 | `ClearMarkInOut(type)` | ✅ | Clears mark in/out |
| 57 | `GetVoiceIsolationState(trackIndex)` | ✅ | Resolve 20.3.2 live test returns voice isolation state |
| 58 | `SetVoiceIsolationState(trackIndex, {state})` | ✅ | Resolve 20.3.2 live test sets voice isolation state |
| 59 | `GetSelectedClips()` | 🔬 | Resolve 21.0.4. First name tried by the selection probe, ahead of the two legacy speculative names. Not executed here — no 21.0.4 build on hand; reported working on Studio 21.0.4.5 in issue #131 |

### TimelineItem

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetName()` | ✅ | Returns item name |
| 2 | `GetDuration(subframe_precision)` | ✅ | Returns duration |
| 3 | `GetEnd(subframe_precision)` | ✅ | Returns end frame |
| 4 | `GetSourceEndFrame()` | ✅ | Returns source end frame |
| 5 | `GetSourceEndTime()` | ✅ | Returns source end time |
| 6 | `GetFusionCompCount()` | ✅ | Returns comp count |
| 7 | `GetFusionCompByIndex(compIndex)` | ✅ | Returns Fusion composition |
| 8 | `GetFusionCompNameList()` | ✅ | Returns comp names |
| 9 | `GetFusionCompByName(compName)` | ✅ | Returns Fusion composition |
| 10 | `GetLeftOffset(subframe_precision)` | ✅ | Returns left offset |
| 11 | `GetRightOffset(subframe_precision)` | ✅ | Returns right offset |
| 12 | `GetStart(subframe_precision)` | ✅ | Returns start frame |
| 13 | `GetSourceStartFrame()` | ✅ | Returns source start |
| 14 | `GetSourceStartTime()` | ✅ | Returns source start time |
| 15 | `SetProperty(propertyKey, propertyValue)` | ✅ | Sets item property |
| 16 | `GetProperty(propertyKey)` | ✅ | Returns property dict |
| 17 | `AddMarker(frameId, color, name, note, duration, customData)` | ✅ | Adds marker to item |
| 18 | `GetMarkers()` | ✅ | Returns marker dict |
| 19 | `GetMarkerByCustomData(customData)` | ✅ | Finds marker by data |
| 20 | `UpdateMarkerCustomData(frameId, customData)` | ✅ | Updates marker data |
| 21 | `GetMarkerCustomData(frameId)` | ✅ | Returns custom data |
| 22 | `DeleteMarkersByColor(color)` | ✅ | Deletes markers by color |
| 23 | `DeleteMarkerAtFrame(frameNum)` | ⚠️ | Returns `False` if no marker at frame |
| 24 | `DeleteMarkerByCustomData(customData)` | ⚠️ | Returns `False` if no match |
| 25 | `AddFlag(color)` | ✅ | Adds flag |
| 26 | `GetFlagList()` | ✅ | Returns flag colors |
| 27 | `ClearFlags(color)` | ✅ | Clears flags |
| 28 | `GetClipColor()` | ✅ | Returns clip color |
| 29 | `SetClipColor(colorName)` | ✅ | Sets clip color |
| 30 | `ClearClipColor()` | ✅ | Clears clip color |
| 31 | `AddFusionComp()` | ✅ | Creates Fusion composition |
| 32 | `ImportFusionComp(path)` | ✅ | Imports .comp file |
| 33 | `ExportFusionComp(path, compIndex)` | ✅ | Exports .comp file |
| 34 | `DeleteFusionCompByName(compName)` | ⚠️ | Returns `False` if comp not found |
| 35 | `LoadFusionCompByName(compName)` | ✅ | Loads composition |
| 36 | `RenameFusionCompByName(oldName, newName)` | ✅ | Renames composition |
| 37 | `AddVersion(versionName, versionType)` | ✅ | Adds grade version |
| 38 | `GetCurrentVersion()` | ✅ | Returns version info |
| 39 | `DeleteVersionByName(versionName, versionType)` | ⚠️ | Returns `False` if version not found |
| 40 | `LoadVersionByName(versionName, versionType)` | ✅ | Loads grade version |
| 41 | `RenameVersionByName(oldName, newName, type)` | ✅ | Renames version |
| 42 | `GetVersionNameList(versionType)` | ✅ | Returns version names |
| 43 | `GetMediaPoolItem()` | ✅ | Returns source MediaPoolItem |
| 44 | `GetStereoConvergenceValues()` | ✅ | Returns stereo keyframes |
| 45 | `GetStereoLeftFloatingWindowParams()` | ✅ | Returns stereo params |
| 46 | `GetStereoRightFloatingWindowParams()` | ✅ | Returns stereo params |
| 47 | `SetCDL([CDL map])` | ✅ | Sets CDL values |
| 48 | `AddTake(mediaPoolItem, startFrame, endFrame)` | ✅ | Adds take |
| 49 | `GetSelectedTakeIndex()` | ✅ | Returns selected take index |
| 50 | `GetTakesCount()` | ✅ | Returns take count |
| 51 | `GetTakeByIndex(idx)` | ✅ | Returns take info |
| 52 | `DeleteTakeByIndex(idx)` | ✅ | Deletes take |
| 53 | `SelectTakeByIndex(idx)` | ✅ | Selects take |
| 54 | `FinalizeTake()` | ⚠️ | Returns `False` when no take selected |
| 55 | `CopyGrades([tgtTimelineItems])` | ⚠️ | API accepts; needs matching items |
| 56 | `SetClipEnabled(enabled)` | ✅ | Enables/disables clip |
| 57 | `GetClipEnabled()` | ✅ | Returns enabled state |
| 58 | `UpdateSidecar()` | ⚠️ | Returns `False` for non-BRAW clips |
| 59 | `GetUniqueId()` | ✅ | Returns UUID string |
| 60 | `LoadBurnInPreset(presetName)` | ⚠️ | API accepts; preset must exist |
| 61 | `CreateMagicMask(mode)` | ⚠️ | Tested; needs DaVinci Neural Engine + Color page context |
| 62 | `RegenerateMagicMask()` | ⚠️ | Tested; needs existing mask |
| 63 | `Stabilize()` | ✅ | Returns `True` on supported clips |
| 64 | `SmartReframe()` | ⚠️ | Tested; needs specific aspect ratio setup |
| 65 | `GetNodeGraph(layerIdx)` | ✅ | Returns Graph object |
| 66 | `GetColorGroup()` | ✅ | Returns ColorGroup |
| 67 | `AssignToColorGroup(colorGroup)` | ✅ | Assigns to group |
| 68 | `RemoveFromColorGroup()` | ⚠️ | Returns `False` if not in group |
| 69 | `ExportLUT(exportType, path)` | ✅ | Exports LUT file |
| 70 | `GetLinkedItems()` | ✅ | Returns linked items |
| 71 | `GetTrackTypeAndIndex()` | ✅ | Returns `[trackType, trackIndex]` |
| 72 | `GetSourceAudioChannelMapping()` | ✅ | Returns audio mapping |
| 73 | `GetIsColorOutputCacheEnabled()` | ✅ | Returns cache state |
| 74 | `GetIsFusionOutputCacheEnabled()` | ✅ | Returns cache state |
| 75 | `SetColorOutputCache(cache_value)` | ⚠️ | Tested; needs active color pipeline |
| 76 | `SetFusionOutputCache(cache_value)` | ⚠️ | Tested; needs active Fusion pipeline |
| 77 | `SetName(clipName)` | ✅ | Resolve 20.3.2 live test renames timeline item |
| 78 | `GetVoiceIsolationState()` | ✅ | Resolve 20.3.2 live test returns voice isolation state |
| 79 | `SetVoiceIsolationState({state})` | ✅ | Resolve 20.3.2 live test sets voice isolation state |
| 80 | `ResetAllNodeColors()` | ✅ | Resolve 20.3.2 live test resets node colors |

### Gallery

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetAlbumName(galleryStillAlbum)` | ✅ | Returns album name |
| 2 | `SetAlbumName(galleryStillAlbum, albumName)` | ✅ | Sets album name |
| 3 | `GetCurrentStillAlbum()` | ✅ | Returns GalleryStillAlbum |
| 4 | `SetCurrentStillAlbum(galleryStillAlbum)` | ✅ | Sets current album |
| 5 | `GetGalleryStillAlbums()` | ✅ | Returns album list |
| 6 | `GetGalleryPowerGradeAlbums()` | ✅ | Returns power grade albums |
| 7 | `CreateGalleryStillAlbum()` | ✅ | Creates still album |
| 8 | `CreateGalleryPowerGradeAlbum()` | ✅ | Creates power grade album |

### GalleryStillAlbum

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetStills()` | ✅ | Returns list of GalleryStill objects |
| 2 | `GetLabel(galleryStill)` | ✅ | Returns label string |
| 3 | `SetLabel(galleryStill, label)` | ⚠️ | API accepts; may not persist in all versions |
| 4 | `ImportStills([filePaths])` | ✅ | Imports DRX still files (requires Color page) |
| 5 | `ExportStills([stills], folderPath, prefix, format)` | ✅ | Exports stills as image + companion .drx grade file. Requires Color page with Gallery panel visible. Supported formats: dpx, cin, tif, jpg, png, ppm, bmp, xpm, drx. |
| 6 | `DeleteStills([galleryStill])` | ✅ | Deletes stills from album |

> **Note (v2.0.8+):** The compound server's `gallery_stills` tool includes a `grab_and_export` action that combines `GrabStill()` + `ExportStills()` in a single call — more reliable than calling them separately since it keeps the live GalleryStill reference. Returns the list of exported files (image + .drx grade data). Requires the Color page with the Gallery panel open.

### Graph

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetNumNodes()` | ✅ | Returns node count (via ColorGroup pre/post graphs) |
| 2 | `SetLUT(nodeIndex, lutPath)` | ✅ | Sets LUT on node |
| 3 | `GetLUT(nodeIndex)` | ✅ | Returns LUT path |
| 4 | `SetNodeCacheMode(nodeIndex, cache_value)` | ✅ | Returns `True` |
| 5 | `GetNodeCacheMode(nodeIndex)` | ✅ | Returns `-1` (no cache mode set) |
| 6 | `GetNodeLabel(nodeIndex)` | ✅ | Returns node label string |
| 7 | `GetToolsInNode(nodeIndex)` | ✅ | Returns `None` (no OFX tools in node) |
| 8 | `SetNodeEnabled(nodeIndex, isEnabled)` | ✅ | Returns `True` |
| 9 | `ApplyGradeFromDRX(path, gradeMode)` | ✅ | Applies grade from DRX file |
| 10 | `ApplyArriCdlLut()` | ✅ | Applies ARRI CDL LUT |
| 11 | `ResetAllGrades()` | ✅ | Resets all grades |

### ColorGroup

| # | Method | Status | Test Result / Notes |
|---|--------|--------|---------------------|
| 1 | `GetName()` | ✅ | Returns group name |
| 2 | `SetName(groupName)` | ✅ | Sets group name |
| 3 | `GetClipsInTimeline(timeline)` | ✅ | Returns clips in group |
| 4 | `GetPreClipNodeGraph()` | ✅ | Returns Graph object |
| 5 | `GetPostClipNodeGraph()` | ✅ | Returns Graph object |

---
