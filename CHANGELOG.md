# Changelog

Release history for the DaVinci Resolve MCP Server. The latest release is summarized in the root README; older entries live here to keep the README focused.

## What's New in v2.57.5

Fixes a silent data-loss bug on Reel Name writes (issue #77) and bundles the
community-contributed API-limitation entries from PR #76 (issue #75).

- **Fixed** (#77) `set_clip_property` / `set_metadata` reporting `success: true`
  when writing the `Reel Name` clip property even though Resolve silently
  dropped the value. Resolve gates `Reel Name` behind the project setting
  *General Options > Assist using reel names from the:* — when that derives reel
  names automatically, scripted writes are ignored but still return `True`. On a
  batch ingest this meant hundreds of clips believed to have reel names assigned
  when none actually stuck. The server now reads the value back after writing
  known-unreliable keys and refuses to report success on mismatch, surfacing the
  project-setting gate as a `hint`. Wired into `set_clip_property`,
  `set_metadata` (both forms), and the bulk `normalize_metadata` path. Adds an
  `api_truth` bug entry (report now lists 18 missing + 11 bugs) and 10 unit
  tests.
- **Added** (PR #76, thanks @swayll) four `submit: missing` API-limitation
  entries verified on Resolve 21.0.0: per-subtitle text/timing editing, subtitle
  track styling/presets, speech-recognition engine selection + SRT import, and
  Media Pool folder rename. These document the API ceiling behind the subtitle
  feature request in #75 — direct subtitle text editing and SRT round-trip are
  not exposed by the Blackmagic scripting API.

### Validation

- Offline: full unit suite green; new `tests/test_reel_name_writeback.py` (10
  tests) plus the api_truth/limitations drift guards. Live Resolve validation of
  the Reel Name read-back is recommended but not performed here — forcing the
  gate would require writing reel names into a live project's media metadata.

## What's New in v2.57.4

Live mutating verification of the catalogued API gaps.

- **Added** `tests/live_api_gap_verification.py` — attempts each catalogued
  "missing capability" against a disposable project built from synthetic ffmpeg
  media, recording the failing call alongside a positive control that succeeds.
  All 8 surface-audited gaps confirmed missing on Resolve Studio 21.0.0:
  `SetProperty('Speed', …)` / audio-level keys return False while
  `RetimeProcess` / video-transform keys succeed; trim/move/split/proxy/node-
  graph/Smart-Bin methods are absent (by `dir()`), while append/CDL/AddSubFolder
  controls work.
- **Added** a new bug entry: `hasattr()`/`getattr()` are unusable on Resolve
  objects — the Python bridge fabricates a callable for ANY attribute name, so
  capability detection must use `dir()`. (Discovered when the first harness pass
  reported nonexistent methods as present.) Report now lists 14 missing + 10 bugs.
- **Changed** the report's Scope note to record the live mutating-harness
  methodology and the `hasattr` caveat. Strengthened the clip-speed and
  Fairlight-audio entries with the live `SetProperty` rejection evidence (and
  noted that `'Pan'` is the video-transform key, not audio pan).

## What's New in v2.57.3

Expanded the API-limitations catalogue with a live surface audit.

- **Added** 8 newly-catalogued **missing capabilities** to
  `docs/reference/api-limitations.md`, found by a `dir()` audit of the live
  Resolve 21.0.0 API objects diffed against the UI feature set: timeline-item
  trim/move/re-time (getters only, no setters), razor/blade/split, clip
  speed/retime ratio & ramps, color node-graph editing + primary grade values,
  Fairlight audio levels/pan/EQ/automation/FairlightFX, proxy/optimized-media
  generation, insert/overwrite/replace/fit-to-fill edit modes, and Smart/Power
  Bin creation. The report now lists 14 missing capabilities + 9 bugs.
- **Verified** the four previously-doc-derived entries (per-clip audio
  stereo↔mono, native multicam creation, transitions, cloud list/export/user)
  against the live API surface; all confirmed absent.
- **Changed** the generated report to carry an explicit **Scope & completeness**
  note — it is not guaranteed exhaustive (surface audit + incident log; misses
  parameters that exist-but-misbehave and untested capabilities).

## What's New in v2.57.2

Consolidated, submittable list of Resolve scripting-API limitations.

- **Added** `docs/reference/api-limitations.md` — a curated, behaviorally-verified
  catalogue of Resolve scripting-API gaps and bugs, split into **Missing
  Capabilities** (please add) and **Bugs / Unreliable Behavior** (please fix),
  formatted for submission to Blackmagic Design's developer feedback. First cut:
  6 missing capabilities (Source Track Selector / insert `trackIndex`, per-clip
  audio stereo↔mono, native multicam-clip creation, transition create/copy,
  `GetTimelineByName`, cloud project list/export/user management) and 9
  bugs/unreliable behaviors (enum-key silent failures in `AutoSyncAudio`,
  `CreateSubtitlesFromAudio`, CloudProject family, and `Timeline.Export`; flaky
  `DeleteProject`; `Composition.Paste` bridge failure; `FlowView` unreliable
  returns; truncated `Transcription` property; automation-blocking `CreateProject`
  modal).
- **Added** `scripts/gen_api_limitations.py` — the report is generated from the
  `submit`-tagged entries in the `api_truth` ledger (single source of truth, also
  queryable at runtime via `resolve_control api_truth`), so it never drifts.
- **Changed** the release process and CI to keep it current: a new
  `tests.test_api_limitations_doc` drift guard (added to the publish workflow)
  fails if the doc is stale, and `docs/process/release-process.md` now requires
  regenerating it whenever a `submit`-tagged entry changes.

## What's New in v2.57.1

Investigation outcome for community feature request #74 — no behavior change.

- **Note** (issue #74) the DaVinci Resolve scripting API does not expose the
  Source/Auto Track Selector, so there is no way to choose the destination track
  when inserting Text+/titles/generators. Verified live on Resolve Studio 21.0.0:
  no get/set for the selector exists; the `Insert*IntoTimeline` family takes no
  `trackIndex` and always lands on V1; locking lower tracks makes the insert fail
  rather than redirect; and titles/generators can't be relocated afterward (no
  `MediaPoolItem`). Closed as won't-fix (API limitation).
- **Documentation** recorded the limitation in the verified `api_truth` ledger
  (query at runtime with `resolve_control api_truth "track"`) and in
  `docs/reference/api-coverage.md`, with the supported alternative for
  media-backed clips (`MediaPool.AppendToTimeline` clipInfo `trackIndex`, exposed
  as `media_pool.append_to_timeline` `clip_infos`). Added a regression test.

## What's New in v2.57.0

Community feature requests #72 and #73.

- **Added** OpenCode to the installer's supported MCP clients (issue #72). The
  installer now writes/merges `~/.config/opencode/opencode.json` using OpenCode's
  own schema (`type`/`enabled`, a combined `command` array, and an `environment`
  block), and `--manual` prints a ready-to-paste OpenCode snippet.
- **Added** `fusion_comp(action="add_fusion_mask", ...)` (issue #73): a one-call
  Rectangle/Ellipse mask — adds the mask tool, sets its params (`corner_radius`,
  `width`, `height`, `center`/`center_x`/`center_y`, etc., all 0..1), and
  optionally wires it into a tool's mask input (`EffectMask` by default). Each
  input is applied independently so one unsupported parameter never aborts the rest.
- **Added** `fusion_comp(action="set_text_plus" / "get_text_plus", ...)` (issue
  #73): read/write the text of a Fusion `Text+` tool or Fusion title template
  (e.g. a "Deep" title), auto-finding the `Text+` tool when `tool_name` is
  omitted. Complements `timeline(action="set_title_text")` for generator titles.
- **Note** (issue #73) per-clip audio Stereo↔Mono conversion is not in
  Blackmagic's scripting API and was not added. The supported surface is already
  exposed: `timeline get_track_sub_type` (query channel format), `add_track` with
  `audioType` (create mono/stereo tracks), `convert_to_stereo` (timeline-wide),
  and `timeline_item get_source_audio_channel_mapping`.

## What's New in v2.56.1

Final reliability batch from the exhaustive audit (Wave B + P2/P3 selections).

- **Fixed** (EX11) `audio_track_probe` reported `available: true` for track index 0
  (and negatives); audio tracks are 1-indexed, so it now requires
  `1 <= index <= track_count`.
- **Fixed** (EX10) `_find_timeline_item_by_id` no longer silently skips a whole
  track type when `GetTrackCount` errors — it logs the failure so a real API error
  isn't mistaken for "item not found".
- **Fixed** (P3) the raw `timeline_item_color.set_cdl` now validates the ASC-CDL
  payload (shape/ranges) before `SetCDL`, matching its safe twin — malformed CDL
  returns a structured error instead of being silently rejected by Resolve.
- **Fixed** (P2) `media_pool.delete_timelines` is read-back verified: it reports
  `verified` from the project's timeline count dropping, not the unreliable boolean.
  `import_folder` now validates its required `path`.

## What's New in v2.56.0

Destructive-action registry audit (EX-REG) — a systemic version of the EX2 bug.

Many destructive actions were registered under the **wrong tool key**, so
`is_destructive()` returned False and **version-on-mutate archiving / change
logging silently never fired** for them. Examples: `create_timeline`,
`auto_sync_audio`, `create_stereo_clip`, `append_to_timeline` were filed under
`timeline` though `media_pool` dispatches them; `set_cdl`, `copy_grades`,
`export_lut`, the version ops were under `timeline_item` though
`timeline_item_color` dispatches them; the Fusion-comp and take actions used stale
names (`add_fusion_comp`, `delete_take`) that matched no real handler.

- **Fixed** rebuilt `DESTRUCTIVE_ACTIONS_BY_TOOL` so every action is keyed under
  the tool that actually dispatches it (stale names mapped to real ones:
  `*_fusion_comp` → `*_comp`, `*_take` → `add`/`delete`/`select`/`finalize`,
  `import_into` → `import_into_timeline`, `create_subtitles_from_audio` →
  `create_subtitles`). Inert entries whose tool isn't governed (media_pool_item
  `replace_clip`/`link_*`) were dropped. Catastrophic take/Fusion-comp deletes and
  the media-pool create/sync ops are now archived as intended.
- **Added** the registry-drift guard now asserts *every* registry action is a real
  handler of its tool (broad check enabled), so this class can't regress.

## What's New in v2.55.2

Deep-QC P1 1b — required-param validation. Mutating/destructive actions that
hard-indexed required params (`p["name"]`, `p["index"]`, `p["color"]`, …) now
return a structured error instead of crashing with an unhandled `KeyError` (or,
for `set_clip_enabled`/`set_current`, coercing the value). Guarded actions:

- `timeline`: `set_current`, `set_name`, `set_start_timecode`, `add_track`
- `timeline_item`: `set_property`, `set_clip_enabled`
- `project_manager`: `create`, `load`, `import_project`, `export_project`,
  `archive`, `restore`
- marker `delete_by_color` (clip / timeline / item — destructive)
- `layout_presets`: `save`, `export`; `project_settings`: `set_name`, `set_setting`

## What's New in v2.55.1

Deep-QC P1 — settings/options whitelisting + DeleteProject reliability.

- **Fixed** options/settings dicts passed to several Resolve APIs are now
  whitelisted to their documented keys, so a typo'd key is reported instead of
  silently dropped (`_filter_to_keys` → `ignored_options`/`ignored_settings`):
  `media_pool.import_timeline` (ImportTimelineFromFile), `timeline.import_into_timeline`
  (ImportIntoTimeline), raw `render.set_settings` (SetRenderSettings) and
  `render.quick_export`, and `set_voice_isolation_state` (track + item).
- **Fixed** `ProjectManager.DeleteProject` is flaky — it silently returns False
  when the target is/was the current project. All callers (the safe and raw
  `project_manager.delete` actions and the granular `delete_project`) now route
  through `delete_project_safely` (switch-away + retry) and report `delete_detail`.
  Added an `api_truth` entry.
- **Added** a destructive-registry drift guard (`tests/test_destructive_registry_drift.py`)
  that asserts token-gated actions map to real handlers and locks in the media-pool
  delete governance from v2.55.0. (It also surfaced a pre-existing registry
  mis-keying issue now tracked for a dedicated audit.)

## What's New in v2.55.0

Governance for catastrophic Media Pool deletes (exhaustive audit EX2/EX3).

**Behavior change:** `media_pool` `delete_clips`, `delete_folders`, and
`delete_timelines` now require a confirm token, the same two-step handshake
`timeline.delete_track` already uses — the first call returns
`status: "confirmation_required"` with a `confirm_token` and a preview (count +
names); re-call with `params.confirm_token` to execute. Callers that disable
gating via the `destructive.require_confirm_token=false` preference are
unaffected.

- **Fixed** the destructive-action registry listed granular function names
  (`delete_media_pool_clips`, `move_media_pool_folders`, …) that the compound
  `media_pool` tool never dispatches, so `is_destructive()` returned False and
  these catastrophic deletes silently skipped version-on-mutate archiving and
  change logging. The registry now uses the real compound action strings, so the
  deletes are archived/logged as intended.
- **Added** confirm-token gating + previews to the three deletes (EX3). The
  registry fix also re-enables the existing media-pool change log for them.
- Live-validated against DaVinci Resolve Studio 21.0.0 (non-destructively): the
  no-token call returns `confirmation_required` and deletes nothing.

## What's New in v2.54.5

Reliability + security hardening from the exhaustive reliability audit (Wave A).

- **Security** `apply_spec` hooks no longer run with `shell=True`. A spec's hook
  command is now `shlex`-split and executed without a shell, so a hook string
  can't inject arbitrary shell (`; rm -rf …`, pipes, expansion). Hooks needing
  shell features must invoke an interpreter explicitly (e.g. `bash -c "…"`).
- **Fixed** the confirm-token table (`_CONFIRM_TOKENS`) is now guarded by a lock.
  The control panel is threaded, so issue/consume/GC ran concurrently; validate-
  then-pop is now atomic and GC can't race a write.
- **Fixed** negative item indices are rejected instead of silently returning the
  wrong item (Python reverse-indexing): `_get_item`, the audio item resolver, and
  the two timeline-matte helpers now require `0 <= index < len`.
- **Fixed** history queries clamp `limit` to `[1, 1000]`. SQLite treats a negative
  `LIMIT` as "no limit", so a negative value could silently fetch the entire table
  (`get_brain_edit_history`, `list_runs`, `get_media_pool_change_history`).
  `timeline_versioning` version/limit/keep_n params are now validated (no unhandled
  `ValueError`; `rollback` rejects negative versions before archiving). `max_files`
  /`max_seconds` in the relink file search are clamped positive.
- **Fixed** the server-reachable ffmpeg probes (render, audio, review) now pass
  `timeout=120` so a hung ffmpeg can't block the server indefinitely.

(Deferred to a live-validated follow-up: confirm-token gating + archiving for
catastrophic media-pool/take/fusion deletes, and temp-directory lifecycle cleanup.)

## What's New in v2.54.4

Persistence-safety hardening (generalizes issue #71 to the analysis state
stores). A multi-agent audit found several state files whose **readers** swallow a
`JSONDecodeError` and reset to an empty default — so a later read-modify-write
writes back only the new field, silently wiping prior data. Atomic writes don't
help, because the loss happens at *read* time.

- **Fixed** read-modify-write paths now read strictly and **refuse to overwrite**
  a corrupt existing file (via a shared `ConfigParseError` + `_read_json_strict`),
  rather than clobbering it:
  - media-analysis **preferences** — 5 write paths (set-defaults, timed-marker
    default, sampling-mode default, AI governance, caps preset)
  - **update-state** — configure/clear update settings (3 paths), now also written
    atomically (temp + `os.replace`)
  - per-clip **corrections** (human edit history — the highest-value store) —
    update and revert paths
- **Fixed** non-atomic writes that a crash mid-write could truncate: the bin
  summary markdown and Fusion `.setting` files now write to a temp file and
  `os.replace`.
- **Fixed** a read-modify-write race on `analysis.json` under the threaded control
  panel: transcript regeneration is now serialized under the existing state lock,
  so a concurrent regen/batch write can't drop the other's updates.
- Read-only callers keep their forgiving behavior (they fall back to defaults and
  never write). New tests in `tests/test_persistence_safety.py`.

## What's New in v2.54.3

Follow-up to the v2.54.2 config-merge fix (#71): the JSONC sanitizer's
trailing-comma step was not string-aware.

- **Fixed** `_strip_jsonc` removed trailing commas with a regex applied to the
  whole document, so a comma inside a string value followed by whitespace and a
  closing brace/bracket — e.g. `"greeting": "hello, } world"` — had the comma
  silently stripped *from inside the string* when merging a commented (JSONC)
  client config. The trailing-comma pass is now string-aware (mirroring the
  comment stripper), so string contents are never altered while real trailing
  commas are still removed. Added regression tests covering string values that
  contain `, }` / `, ]`. (Dropped the now-unused `re` import.)

## What's New in v2.54.2

A destructive-overwrite bug in the installer (issue #71): the MCP client setup
step could wipe a user's entire editor settings file instead of merging into it.

- **Fixed** `install.py` silently destroyed existing client config files whose
  contents weren't strict JSON. `read_json` swallowed `JSONDecodeError` and
  returned `{}`, so the subsequent "merge" wrote a file containing *only* the
  `davinci-resolve` server entry — wiping themes, terminal env vars, LSP
  settings, keybindings, everything else. Zed was the reported victim because
  its `settings.json` ships with `//` comments (JSONC), but the same latent
  risk existed for **every** supported client — VS Code and Continue also accept
  JSONC. The fix is centralized in the single read/merge path so all clients are
  covered:
  - `read_json` now best-effort strips JSONC `//` and `/* */` comments and
    trailing commas (string-aware, so comment markers inside string values are
    preserved), letting commented configs merge cleanly instead of being lost.
  - When a config file exists but still can't be parsed after that, the
    installer **refuses to overwrite it** and tells the user to add the entry
    manually — rather than silently replacing their settings.
- **Added** regression tests covering JSONC merge, plain-JSON merge,
  refuse-to-overwrite on unparseable files, fresh-file creation, and
  string-aware comment stripping.

## What's New in v2.54.1

One more instance of the enum-keyed silent-failure class (issue #70), plus a
guard so the next one can't ship unnoticed.

- **Fixed** the raw `timeline.export` action passed `type`/`subtype` straight to
  `Timeline.Export`, which needs resolved `resolve.EXPORT_*` enum *values* — a
  JSON/MCP caller can't pass a live enum, so the action silently wrote nothing
  for every caller. It now resolves friendly format names (and `EXPORT_*`
  constant names) via the same `_timeline_export_spec` resolver that
  `export_timeline_checked` uses, and reports the resolved `export_type`/
  `export_subtype`.
- **Fixed** `export_timeline_checked` resolved enum constants against the module
  global `resolve` (which can be `None` and silently degrade the `EXPORT_*` args
  to strings); it now uses `get_resolve()`, matching the issue-#70 lesson.
- **Added** an `api_truth` ↔ mitigation guard test: every `enum`-tagged catalog
  entry must declare a `mitigation` (the resolver/wrapper functions), each of
  which must exist in `src.server`. The next raw enum passthrough — a documented
  symbol with no real resolver, or a renamed/removed resolver — now fails CI.
  Added a `Timeline.Export` catalog entry and wired `mitigation` onto the
  `AutoSyncAudio`, `CreateSubtitlesFromAudio`, and CloudProject entries.

## What's New in v2.54.0

Hardens the rest of the enum-keyed settings APIs against the same silent-failure
class fixed for `AutoSyncAudio` in v2.53.0 (issue #70). Several Resolve methods
key their settings dict by `resolve.<CONST>` enum attributes and silently reject
the whole call when handed plain string keys — returning `False`/`None` with
nothing applied and no error.

- **Fixed** `CreateSubtitlesFromAudio` (both `timeline_ai.create_subtitles` and
  `timeline.subtitle_generation_probe`) now resolves human-readable
  `autoCaptionSettings` — `language`, `preset`, `line_break`, `chars_per_line`,
  `gap` — into live `SUBTITLE_*`/`AUTO_CAPTION_*` enum keys/values. Unknown keys
  and unresolvable values are dropped and reported in `ignored_settings` instead
  of poisoning the call, and generation is read-back verified against the
  timeline's subtitle track count (the boolean return is unreliable).
- **Fixed** the `ProjectManager` CloudProject family (`create`/`load`/
  `import_project`/`restore`) resolves `{cloudSettings}` into live
  `CLOUD_SETTING_*`/`CLOUD_SYNC_*` enums (`project_name`, `media_path`,
  `is_collab`, `sync_mode`, `is_camera_access`), dropping unknown keys into
  `ignored_settings`.
- **Changed** the string→enum resolution is now a shared `_resolve_enum_settings`
  primitive driven by per-field specs, so the next enum-keyed API gets the same
  treatment without re-implementing it.
- **Added** `api_truth` entries for `Timeline.CreateSubtitlesFromAudio` and the
  CloudProject family, documenting the silent-rejection + unreliable-return
  behavior alongside the existing `AutoSyncAudio` entry.

## What's New in v2.53.0

Two improvements to audio sync reliability and inventory control.

`safe_auto_sync_audio` / `media_pool.auto_sync_audio` no longer fail silently on
human-readable settings (issue #70). The previous normalizer recognized
`syncBy`/`mode` but not `method`, and it forwarded *every* unrecognized key
(`group_id`, `primary_clip_id`, …) straight into `MediaPool.AutoSyncAudio` —
which silently rejects the whole call when it sees a key it doesn't understand,
returning `False` with nothing linked and no error.

- **Fixed** `method` (matching the tool's own parameter naming) is now accepted
  as an alias for the sync mode alongside `syncBy`/`sync_by`/`mode`/`syncMode`.
- **Fixed** unrecognized settings keys are dropped instead of forwarded, so a
  stray `group_id`/`primary_clip_id` no longer poisons the call. Dropped keys
  are reported back in a new `ignored_settings` field on the response, so a
  rejection is no longer invisible.
- **Fixed** the raw `media_pool.auto_sync_audio` action now routes settings
  through the same live `AUDIO_SYNC_*` enum resolution as the safe wrapper
  (previously it passed strings straight through).

The Media Pool inventory walk is now configurable:

- **Added** `media_analysis.inventory_exclude_bins` — a comma-separated list of
  folder names to skip entirely during the inventory walk (recursively). Empty
  by default, so every folder is indexed unless you opt out.
- **Added** `media_analysis.inventory_limit` — the maximum clips to index per
  walk, configurable from the control panel and `setup`. The hard ceiling is
  raised from 2000 to 10000.
- Adapted from PR #69 by @rgxdev; the default was changed to exclude nothing
  (the PR defaulted to excluding an `assets` bin, which would have silently
  stopped indexing existing `assets` folders on upgrade).

## What's New in v2.52.1

Analysis reuse no longer blocks on missing capabilities when every clip is
satisfied by an existing report (issue #68). `build_plan` records
`capability_gaps` from the *requested* options before the per-clip reuse
decision runs; when a fully-reused plan only re-keys and imports existing
reports into the current root, no fresh transcription/vision/ffprobe happens,
so the missing-capability gate must not fire.

- **Fixed** the missing-capability gate is now evaluated against the clips that
  still need fresh analysis, not the requested-options gaps. A clip is exempt
  only when it both skips execution and has an existing report path; any clip
  needing fresh work still enforces the gate.
- **Fixed** extended the exemption to the entry points that short-circuit
  before `execute_plan_async` and were still blocking fully-reused runs: the
  `media_analysis` analyze action, metadata-publish analysis, and batch-job
  creation. The batch CLI `plan` preview no longer prints "Missing tools" for a
  fully-reusable plan.
- **Changed** the reuse/capability logic is now a shared
  `plan_requires_capabilities()` / `executing_clips()` helper, replacing the
  duplicated inline comprehensions so every gate stays consistent.
- Includes PR #68 by @diesdaas, which fixed the inner `execute_plan_async` gate
  and isolated the marker-param and host-vision tests from unrelated
  capability/destructive-hook coupling.

## What's New in v2.52.0

`edit_engine` tighten now carries audio. Previously `execute_tighten`
assembled a video-only variant — a speech-driven dead-air cut came out
silent, with nothing in the preview or readback to warn you (issue #67).

- **Fixed** `plan_tighten` mirrors every kept video range onto its linked
  audio track(s) with identical source frames, so the assembled variant
  stays frame-locked and audible. Audio targets the item's detected linked
  audio tracks (same `GetLinkedItems` matching `execute_swap` uses), falling
  back to audio track 1 where a single linked A/V clip's audio lives.
- **Added** `include_audio` parameter to `plan_tighten` (default `true`).
  Pass `include_audio=false` for the prior video-only assembly.
- **Added** an `audio_accounting` block to the `execute_tighten` confirm
  preview and readback (planned vs. actual audio/video item counts), so a
  silent variant can no longer ship unnoticed. Old video-only plans
  re-executed against this build still work and are now loudly flagged as
  silent.

## What's New in v2.51.0

CLAP audio embeddings — the final phase of the post-program improvements.
Detection-based like every other backend (never auto-installed); local
compute, so nothing touches the caps ledger.

- **Added** audio embedding backend detection: CLAP via `transformers`
  (laion/clap-htsat-unfused, preferred) or the `laion_clap` package, plus
  torch + ffmpeg. `capabilities` gains an `audio` block with install
  guidance and a `clap_audio` Tools-page entry.
- **Added** `build_embeddings(kinds=["audio"])`: one CLAP window per shot
  (center-cropped to ~10 s, piped from the source media as raw PCM —
  read-only on source media, no temp files) plus a clip-level mean vector,
  stored as `embedding_kind="audio"` rows. Idempotent via content hashes;
  offline media is reported in `skipped_missing_media`; a missing backend
  is a graceful skip with install guidance.
- **Added** `find_similar(kind="audio")`: shot/clip queries over the audio
  vectors, and free-text queries ("engine revving") via the CLAP text
  encoder.

## What's New in v2.50.0

The last JSON-fed readers now source from the DB-canonical analysis store
(consistency/perf hygiene — the JSON export is lockstep with the DB, so this
is shape-preserving by construction).

- **Changed** `summarize_reports` aggregates from the DB (blob + human
  overlay) when every report dir on disk is covered by an ingested clip row;
  pre-v9 roots and MIXED roots (some clips not ingested) fall back WHOLESALE
  to the JSON walk — a partial DB view would silently under-report. The
  summary gains a `"source": "db"|"json"` key for observability; the F1
  provenance map (source_reports / missing_reports) is unchanged.
- **Changed** `build_analysis_index` sources local reports from the DB
  instead of re-parsing every `analysis.json`; job-linked EXTERNAL report
  paths (their rows live under another project's DB) and pre-v9 dirs keep
  the JSON read. The FTS schema and the query surface are identical; the
  result gains `report_sources` counts.
- **Added** DB-vs-JSON parity tests (semantic equality with normalized
  ordering) plus wholesale-fallback regressions for mixed and pre-v9 roots;
  live-validated on the sample analysis root (summary, index counts, and
  FTS query results identical on both paths).

## What's New in v2.49.0

Cross-shot relationships (spec §4 — pattern recognition only): the shot
page's Relationships group finally fills, and the edit engine can prefer
vision-confirmed alternates.

- **Added** schema v12 `shot_relationships` (same_setup_as / alt_take_of
  symmetric, continues_from directional — the source shot continues from
  the target) with supersede semantics (current rows have
  `superseded_at IS NULL`).
- **Added** `media_analysis` actions `detect_shot_relationships` /
  `commit_shot_relationships` / `list_shot_relationships`: pairwise cosine
  over the per-shot visual vectors (transcript continuity as a second
  signal for continues_from) → a deferred confirmation payload with a
  representative frame PAIR per candidate (caps pre-checked; candidates
  live only in the detection-state stash until committed, so re-detect
  never leaves ghosts) → vision-confirmed rows. Representative frames use
  the shot's middle sample (first/last frames often catch fades).
- **Added** the shot page's Relationships group now renders from the DB
  (`continues_from` shows on the continuing shot; cross-clip targets are
  clip-qualified).
- **Changed** `plan_swap` prefers confirmed `alt_take_of` alternates over
  raw cosine similarity — confirmed takes sort first (and are unioned in
  even when the cosine search missed them); each alternate's rationale
  states which basis ranked it.

## What's New in v2.48.1

Bug fix surfaced by the first real-cut tighten pilot.

- **Fixed** cross-root analysis reuse never landed in the current project's
  DB: when the registry matched a reusable report from another project's
  analysis root, `execute_plan_async` reported success but wrote no DB rows
  and no local export — so `media_ref` lookups against the current media
  pool (edit-engine planners, panel readers) found nothing. The reuse path
  now re-keys the report to the current project's clip identity, ingests it
  into the current root's DB, and writes a lockstep `analysis.json` export
  (provenance kept in `reused_from`).

## What's New in v2.48.0

Edit-engine hardening: trustworthy execute readback ahead of the first
real-cut pilot. Live-validated end-to-end on a disposable synthetic-media
project (24/24 checks).

- **Added** `timeline_versioning(action="diff_timelines", params={from_timeline,
  to_timeline})`: structural diff (added/removed/moved/trimmed + summary)
  between two LIVE timelines by name — read-only, no archived snapshots
  needed. Built for edit-engine variants, which are new-name timelines with
  no shared version chain. The item walk and the snapshot comparison were
  factored out of the version-snapshot path
  (`capture_timeline_clip_usage` / `compare_usage_snapshots`) and reused.
- **Fixed** `execute_swap` audio accounting: the lift was video-only while
  the replacement appended linked video+audio, so item counts drifted on
  every swap. The lift is now scoped to the target's video track plus its
  linked audio tracks (`GetLinkedItems`, with a media-id track-scan fallback;
  items with no linked audio and audio-only timelines are handled
  gracefully), and readback reports per-track-type `track_counts`
  before/after plus an `audio_accounting` block.
- **Added** `execute_tighten` readback now includes `structural_diff`
  (source vs variant); `execute_selects` readback includes a
  `usage_summary` (per-track-type item counts — a diff against a source
  timeline is meaningless for a fresh assembly).
- **Changed** the live edit-engine validation harness asserts the tighten
  structural diff, `diff_timelines` agreement, and swap track-count
  symmetry (24 checks, up from 20).

## What's New in v2.47.0

Edit-engine plan browser in the control panel (Media → Edit Plans) — the
panel UX pass for the v2.45.0 edit engine. Chat-first: the panel surfaces
plans and evidence; execution stays in chat behind the confirm-token gate.

- **Added** a plan browser at `#analysis/review/plans`: every saved
  `edit_engine` plan with kind, summary, save time, and an `executed` chip;
  fingerprint-corrupt plans surface as warning rows instead of being hidden.
- **Added** plan detail views per kind: selects decisions render with shot
  thumbnails, rank, duration, rationale, and a deep link to the shot page;
  tighten plans list each dead-air lift with its transcript-gap evidence and
  skipped items; swap plans show the current item plus numbered alternates
  with similarity scores. Executed plans show their execution readback.
- **Added** a copyable per-kind execute chat prompt on each plan (the panel
  never executes; swaps include an `alternate_index` placeholder).
- **Added** `/api/edit_plans` + `/api/edit_plans/<plan_id>` panel endpoints
  (DB/file only — no Resolve round-trips; decisions are enriched server-side
  with `resolve_clip_id` and a `thumb_frame_index` for the existing frames
  route).
- **Changed** `edit_engine.list_plans` gained `include_corrupt` (default off;
  the MCP action shape is unchanged).

## What's New in v2.46.1

Test and hygiene hardening; no public tool surface changes.

- **Fixed** the three `InventoryCacheReuseTests` failures that appeared
  whenever a live Resolve instance was running: the reuse/build-path tests
  now stub the read-only Resolve probe, so the suite is green with Resolve
  open or closed.
- **Added** `src/utils/project_cleanup.delete_project_safely`: a retrying
  delete helper for disposable Resolve projects (switch away from the target,
  retry `DeleteProject` once after a pause, report the leftover by name on
  persistent failure). The live edit-engine validation harness now uses it
  during cleanup, so disposable pilot projects stop lingering in the library.

## What's New in v2.46.0

Community PR bundle: five contributed fixes and features (#62–#66), live-validated
on Resolve Studio 21.

- **Fixed** timeline marker frames are now correctly relative to the timeline
  start (#66): timecode params and the playhead default rebase by
  `GetStartFrame()`, so markers on hour-start timelines land where the UI
  shows them instead of an hour past the end. Raw `frame` params pass through
  unchanged (documented as relative). Contact sheets and marker thumbnail
  review rebase the other way with a legacy-absolute guard.
- **Fixed** project lint no longer flags audio-only timelines as empty (#62);
  live lint state now reports per-type `video/audio/subtitle_item_count`.
- **Added** `media_pool.check_proxy_media_compatibility` (#63): ffprobe-vs-source
  signature diagnostics (resolution/fps/frames/sample rate, expected
  codec/profile). Same-aspect downscales count as compatible — half-res
  proxies are the normal workflow.
- **Added** readback verification envelopes (`verified_operation`) around
  `media_pool.link_proxy_checked` (#63) and `media_pool.append_to_timeline`
  (#64): preflight, execution, post-state readback, verification status, and a
  journal event. `link_proxy_checked` gains `check_compatibility` /
  `require_compatible` guards that refuse incompatible proxies before linking.
- **Added** `bins` to declarative project specs (#65): missing media-pool bin
  paths plan as `ensure` actions and are created idempotently; existing bins
  are noops. Bin paths normalize to the `Master/` prefix so unprefixed spec
  bins converge instead of reporting perpetual drift.

## What's New in v2.45.0

The edit engine — Phase E, the final phase of the analysis + edit-engine
program. Three evidence-driven loops on one shared skeleton: evidence query
→ dry-run plan with per-decision rationale → confirm token → versioned
timeline ops → metric readback → brain_edits rows.

- **Added** a new `edit_engine` MCP tool (compound tool count: 34):
  - `plan_selects` / `execute_selects` — ranks shots by deep-tier
    `editorial.select_potential` and best moments (clip-level fallback for
    standard-analyzed clips), story-spine order, duration budget; execution
    builds a NEW selects timeline from per-shot source ranges. Additive.
  - `plan_tighten` / `execute_tighten` — dead-air lifts from transcript-gap
    evidence per timeline item (no transcript → reported in `skipped`,
    never silently trimmed); execution assembles a tightened VARIANT
    timeline from keep ranges (true partial trims via the range-copy
    kernel) — the original timeline is never mutated.
  - `plan_swap` / `execute_swap` — alternates for a timeline item via the
    visual-similarity index, filtered to shots that can fill the slot
    exactly; execution replaces the item in place (lift + positioned
    append) on the version-archived timeline.
  - `list_plans` / `get_plan` — plans persist under `memory/edit_plans/`
    with content fingerprints; a stale or tampered plan refuses to execute.
- **Added** `src/utils/edit_engine.py` (DB-only planning/evidence layer) and
  `tests/live_edit_engine_validation.py` (disposable-project live harness).
  execute_* actions are confirm-token gated and registered with the
  version-on-mutate hook (archive + brain_edits come from the same
  machinery as every other destructive op).
- **Fixed** frame→shot mapping in the analysis store: frames now fall back
  to time-containment when a report's shots don't record
  `frame_indices_used` (commit paths that omit it previously produced no
  shot-level visual vectors).
- **Validation**: full offline suite (1118 tests; 13 new). Live pilot on a
  disposable synthetic-media Resolve project (ffmpeg + spoken audio):
  20/20 checks — selects timeline assembled (2 decisions), tighten variant
  removed exactly the 15.2s of transcript dead air while keeping the
  spoken 4.8s (original untouched), swap replaced the item with a 0.92
  cosine alternate, brain_edits rationale rows present for all three
  loops, timeline versions archived.

## What's New in v2.44.0

Cross-clip entities + bin briefing v2 — Phase D of the analysis +
edit-engine program. Recurring people/places/props found by clustering the
visual embeddings, confirmed with one vision call per cluster.

- **Added** schema v11 (`entities` + `entity_appearances`) and
  `src/utils/entities.py`: union-find clustering over the v10 CLIP frame
  vectors (cosine threshold, no new deps), representative-frame selection,
  ghost pruning across re-runs (labeled entities persist), and a
  detection-state stash so `entity_index` always resolves against the exact
  ordering the payload was issued with.
- **Added** `media_analysis` actions: `detect_entities` (clusters + deferred
  one-frame-per-cluster confirmation payload, caps pre-checked),
  `commit_entities` (kind/label/description with conservative-label rules;
  `merge_with` collapses duplicate clusters), `list_entities`,
  `prepare_bin_briefing` (entities + per-clip summaries, text-only), and
  `commit_bin_summary` (host-synthesized briefing written above the v2.0
  aggregate in `memory/bin_summary.md`).
- **Added** a "Recurring across this bin" card on the panel's Review page
  (`/api/entities`), shown once labeled entities exist.
- **Validation**: full offline suite (1105 tests; 10 new). Live on the real
  sample root: 3 clusters detected from 16 CLIP vectors; host-chat
  confirmation labeled the shattered-windshield POV and the white rental
  sedan and merged the sedan's two clusters; bin briefing synthesized and
  committed; panel card verified and screenshots regenerated.

## What's New in v2.43.0

Embeddings + similarity search — Phase C of the analysis + edit-engine
program. "Find clips/shots like this," locally, with no vendor token cost.

- **Added** `src/utils/embeddings.py` and schema v10 (`embeddings` table:
  one float32 vector per entity/kind/model, with content hashes so re-runs
  only re-embed what changed). Brute-force cosine — numpy when present.
- **Added** `media_analysis` actions `build_embeddings` (idempotent; clip
  summaries, shot descriptions + deep field groups, transcript segments,
  sampled frames with per-shot mean vectors) and `find_similar` (query by
  free text, clip, or shot; `kind="text"|"visual"`; free-text visual queries
  go through the CLIP text encoder).
- **Added** backend detection, never installation (the whisper pattern):
  text = ollama `nomic-embed-text` (serving probe) or sentence-transformers;
  visual = open_clip ViT-B-32. Capabilities and the Diagnostics → Tools page
  list availability with install guidance.
- **Added** a `Semantic` toggle on the panel's Review search (shown only
  when a text backend is detected) backed by `/api/search/semantic`, which
  returns rows in the existing search-card shape.
- **Validation**: full offline suite (1095 tests; 14 new, backends mocked).
  Live on the 2026-05-17 sample root: 54 text vectors in 1.2s via ollama
  with correct top hits for three editorial queries; 27 CLIP vectors with
  "cracked broken windshield glass" ranking the shattered-windshield frame
  first; panel endpoint verified and screenshots regenerated.

## What's New in v2.42.0

Deep shot-level vision tier — Phase B of the analysis + edit-engine program.
Opt-in, estimate-first per-shot field filling for the Visual / Content /
Production / Editorial / Cuttability groups the shot pages already render.

- **Added** `src/utils/deep_vision.py` and three `media_analysis` actions:
  `deepen` (estimate → confirm_token → deferred host-vision payload per
  clip/shot), `commit_shot_vision` (writes `vision_deep_v1` provenance rows,
  updates the canonical blob, re-exports analysis.json in lockstep), and
  `vision_pending_sweep` (lists clips stuck in `pending_host_analysis`;
  `reoffer=true` returns the stored payload, `expire=true` stamps them).
- **Added** deep depth to the analyze flow: `depth="deep"` extends the
  deferred payload with the per-shot schema and requires `confirm_deep=true`
  after a token-cost estimate. Caps pre-call refusal applies on both paths.
- **Added** panel affordances: `Deepen analysis` (clip view) and `Deepen this
  shot` (shot view) copy ready-made chat prompts, per the chat-first UX.
  Shots with no sampled frames on disk get 1–2 frames re-extracted via
  ffmpeg, downscaled per caps (source media stays read-only).
- **Fixed** a provenance bug in the analysis store: a source re-deriving an
  unchanged value no longer re-attributes the row (a deep pass would
  otherwise claim every untouched field as `vision_deep_v1`).
- **Validation**: full offline suite (1081 tests; 15 new), and a real
  end-to-end deep pass on the 2026-05-17 sample clip — estimate → confirm →
  frames read by the host chat → commit → rows/blob/export parity → fields
  visible in the panel shot view. Control-panel guide screenshots
  regenerated from the live panel.

## What's New in v2.41.0

DB-canonical clip analysis (C1) — Phase A of the analysis + edit-engine
program. The per-project SQLite DB is now the source of truth for clip
analysis; `analysis.json` becomes a derived export written in lockstep.

- **Added** schema v9 to the per-project timeline-brain DB: `clips`,
  `clip_aliases`, `analysis_reports` (canonical full payload), `shots`,
  `subjective_fields` + `field_changelog` (per-field provenance),
  `transcript_segments`, `frames`, and `qc_observations`.
- **Added** `src/utils/analysis_store.py`: transactional ingest, export with
  human-correction overlay (human rows always win and survive re-analysis),
  alias-based clip lookup, shot ids stable under one-second boundary jitter,
  and a round-trip guard verified against a real sample analysis root.
- **Added** `media_analysis` actions `db_status` (schema version + row
  counts) and `db_ingest` (one-shot migration of existing JSON reports and
  `corrections.json` sidecars into the DB).
- **Changed** the analysis write path: `execute_plan` and `commit_vision`
  write DB rows first, then export the JSON. Panel clip/shot endpoints read
  DB-first with JSON fallback for pre-v9 reports and job-linked report dirs.
- **Changed** `update_clip_field` / `update_shot_field` / `revert_field` to
  mirror corrections into the DB as row-level provenance (the
  `corrections.json` sidecar remains for compatibility).
- **Fixed** eight V2 actions that were unreachable from MCP dispatch since
  v2.24.0 (`get_panel_state`, `set_panel_state`, `session_start_context`,
  `update_shot_field`, `update_clip_field`, `get_field_history`,
  `revert_field`, `list_corrections`): they were checked inside the
  project-root dispatch block but missing from its membership set. The
  control panel proxied to the helpers directly, which masked it.
- **Fixed** the action-list drift guard to inspect async tool functions
  (media_analysis had drifted unchecked) and to fail on actions that are
  unreachable inside membership blocks — the exact class above. Four
  reachable-but-unadvertised actions (`coverage_report`,
  `get_resolve_ai_usage`, `get_ai_governance`, `set_ai_governance`) are now
  listed in the unknown-action error.
- **Validation**: full offline suite (1066 tests; 12 new), round-trip guard
  on the real 2026-05-17 sample root, and a live headless pipeline run on
  synthetic media verifying rows-then-export parity, row-level corrections,
  and DB-first panel reads.

## What's New in v2.40.0

Control panel UX overhaul + docs refresh, from a full live audit of every
panel view, with drift guards so neither can silently go stale again.

- **Added** a governance mode toggle (Advisory / Enforce) to the AI Console,
  with corrected copy (the old text predated v2.39.0 enforce mode), and a
  Recent-runs list on the AI-ops ledger showing each run's actor.
- **Added** chat-first onboarding: empty Overview, Review, and Inventory
  states show plain-language guidance with a copyable suggested prompt
  instead of zero-walls and MCP action names.
- **Added** History as a first-class Media menu item, deep-linkable at
  `#analysis/review/history`; documented the full hash deep-link scheme.
- **Changed** the top-level "Analysis" menu to "Media" (it collided with the
  Preferences page of the same name); "Analyze" is now "Inventory". Full
  vocabulary pass: humanized readiness chips and frame-sampling labels, no
  internal codenames, file names, or absolute paths in UI copy.
- **Fixed** the README's linked screenshot rendering broken in the Docs
  reader: badge parsing no longer claims local linked images, and a new
  `/api/doc_asset/` route serves repo doc images (path-constrained).
- **Fixed** poll hygiene: timers pause while the tab is hidden, panel-state
  polling backs off when unfocused, and unchanged inventory polls return a
  tiny 200 instead of a 304 that Chrome logged as an aborted request.
- **Docs**: `docs/guides/control-panel.md` fully rewritten for the current
  IA with all screenshots regenerated from the live panel
  (`scripts/regen_panel_screenshots.py`). A new drift-guard test fails the
  suite — and the publish workflow, which now runs all three static guards
  on every tag — when the guide drifts from the panel's navigation or
  screenshots.

## What's New in v2.39.0

Governance enforce mode and actor identity — the staged Phase 3 of the
Resolve 21 AI-ops work.

- **Added** governance `mode` for the media-creating AI ops (motion deblur,
  speech generation): `advisory` (default, unchanged — confirm-preview
  warnings only) or `enforce`, where an over-tier run is blocked with
  `GOVERNANCE_BLOCKED` before token issuance, naming the exceeded dimensions.
  Escape hatches: raise the tier, relax the mode, or pass
  `override_governance=true` to consciously exceed the tier once.
  `set_ai_governance` accepts `mode` (preset now optional);
  `get_ai_governance` reports it.
- **Added** instance-level actor identity (per the recorded concurrency
  design): each entry point declares itself — `stdio`, `network-sse`,
  `network-http`, `control-panel`, `batch-cli` — and AI-ops ledger rows,
  brain edits, and timeline versions now carry `actor` (`<instance>:<pid>`)
  alongside `initiator`. Schema v8 (additive columns); migration verified
  against a copy of a real project DB with all rows preserved.

## What's New in v2.38.0

Busy gate for long DaVinci Resolve operations — the first piece of the
concurrency design for the stdio + networked two-instance setup.

- **Added** cross-process registration for long synchronous Resolve calls
  (timeline export/import, scene-cut detection, subtitle generation,
  Dolby Vision analysis, folder/clip audio transcription). A tool call that
  arrives while one is running now waits up to 5 seconds and then returns a
  structured `RESOLVE_BUSY` error (new `busy` category, retryable, with
  `state.busy_with` and `state.age_seconds`) instead of hanging silently
  inside the scripting bridge. Stale registrations from crashed operations
  are ignored automatically; an operation never gates its own thread.
- Design decisions recorded: single-editor/multi-client is the supported
  concurrency target; confirm tokens stay per-instance; actor identity is
  deferred to the governance phase.

## What's New in v2.37.3

Deep-audit fixes, rounds two and three: agent-facing action discovery,
crash-safe user-state persistence, and resource hygiene.

- **Fixed** three tools' unknown-action error lists drifting from their real
  dispatch: `timeline` omitted `clip_where` and `action_help`;
  `timeline_item_color` and `graph` omitted `action_help`. Agents recovering
  from a typo now see the full action set. A static AST test keeps every
  tool's advertised list in both-way sync with its dispatch (and verifies
  docstring-advertised actions are real).
- **Fixed** user-state files being vulnerable to truncation by a crash
  mid-write. Affected files all reset to `{}` on corruption, so the next
  save would silently wipe remaining user data. Writers now use atomic
  temp-file + `os.replace`: `media-analysis-preferences.json` (all
  analysis/caps/governance/update defaults — including the
  `set_resolution_tier` and `set_caps_preset` paths, now routed through the
  shared writer), `update-check.json`, the dashboard's `analysis.json`
  transcription patch, and `transcript-corrections.json`.
- **Fixed** `_safe_project_delete` discarding `SaveProject()`'s result when
  closing the current project before deletion; a failed save now surfaces
  as a warning in the response.
- **Fixed** a file-descriptor leak: the parent kept its copy of the control
  panel's log handle open after spawning the detached child.
- Audit classes verified clean: bare excepts, mutable default arguments,
  `asyncio.run` inside running loops, subprocess timeouts, docstring phantom
  actions, silent-success swallows in metadata/marker/archive write paths.

## What's New in v2.37.2

Static-audit fixes — four undefined-name references that silently fell back
to defaults instead of erroring (the same bug class as the v2.37.0
confirm-token fix), plus a regression guard.

- **Fixed** the `status://mcp_version` resource reporting update channel
  `"stable"` unconditionally; it now calls the real `get_update_channel()`,
  so beta/dev channel installs report correctly.
- **Fixed** the `versioning_auto_run_idle_timeout_seconds` preference being
  silently ignored (auto-run idle timeout was always 90s) due to a
  misspelled preference-reader name in the destructive hook.
- **Fixed** resolve-state snapshot tokens always falling back to a timestamp
  because `short_hash` was never imported; tokens are now content-stable.
- **Fixed** the timeline-kernel live probe's MCP-stub fallback crashing with
  a `NameError` (missing `types` import) exactly when the mcp library is
  absent — the only case the fallback exists for.
- **Added** a static test that runs pyflakes over `src/` and fails on any
  undefined name, so this bug class cannot reappear unnoticed.

## What's New in v2.37.1

Test-suite hygiene — no server behavior changed.

- **Fixed** the legacy live-harness scripts (`test_all_tools`, `test_phase2`–`5`)
  exiting at import when Resolve is unavailable, which crashed pytest
  collection and surfaced as five loader errors under unittest discovery.
  They now skip cleanly under both runners and keep the hard-exit behavior
  when run as standalone scripts. (Adapted from a contribution by @diesdaas.)
- **Fixed** pytest mis-collecting `test_resolve20_api.py`'s internal `test()`
  helper (renamed to `run_live_check()`), and made the batch-CLI synthetic-job
  test independent of which transcription backends the host has installed.
- **CI**: the npm publish workflow no longer reports failure when the registry
  accepted the publish but npm's retried request hit a consumed OIDC token;
  it now verifies the published tarball shasum before failing. Runner actions
  bumped to their Node 24 majors.

## What's New in v2.37.0

Render format-id fix, offline-media diagnosis, and a setup doctor.

- **Fixed** render helpers passing the display name from `GetRenderFormats()`
  (e.g. `QuickTime`) into `GetRenderCodecs`, `GetRenderResolutions`, and
  `SetCurrentRenderFormatAndCodec`, which expect the format id (e.g. `mov`).
  `GetRenderCodecs("QuickTime")` returned empty, so `probe_render_matrix`
  reported no QuickTime codecs and `prepare_render_job` could not target
  ProRes (e.g. `ProRes422LT` proxy renders). Display names and format ids are
  now both accepted as input and normalized to the id for Resolve API calls;
  `probe_render_matrix` rows include `format_id`. Closes #59.
- **Fixed** the destructive confirm-token gate referencing a stale function
  name, which made it silently ignore the `destructive.require_confirm_token`
  preference and always fall back to the default.
- **Added** a `diagnosis` block to `timeline.detect_missing_media`:
  deduplicated missing Media Pool items, volume/folder mounted checks, a
  primary cause (`volume_not_mounted` / `folder_not_found` /
  `files_missing_or_renamed`), and a recommended next step. Optional
  `sanitized`/`sanitize_paths` redacts raw media paths.
- **Added** bounds to `timeline.build_relink_plan`: skips the broad scan by
  default when a source volume (e.g. a camera card) is not mounted, dedupes
  missing basenames, and caps the search with `max_depth`, `max_seconds`
  (default 20s), and `max_files_scanned` (default 50k), reporting per-candidate
  scan stats.
- **Fixed** `media_analysis` accepting `vision: true/false` boolean shorthand
  (now normalized to the full options dict) and `timeline_markers.get_thumbnail`
  returning a structured error instead of raw `None` when no thumbnail is
  available.
- **Added** `scripts/doctor.py`, a read-only setup diagnostic that checks the
  checkout, Python, Resolve app/scripting paths, and MCP client configs, and
  probes the scripting bridge end to end with OK/WARN/FAIL output (`--json`
  supported).

## What's New in v2.36.1

Bug fix — restore the `fusion_comp` MCP tool.

- **Fixed** a regression from `32be0ec` (v2.33.0) that left `fusion_comp`
  unregistered: a new `_parse_pos` helper was inserted between the `@mcp.tool()`
  decorator and `def fusion_comp`, so the decorator landed on the private helper
  instead. As a result `_parse_pos` was exposed as a tool while **all**
  `fusion_comp` node-graph operations (`add_tool`, `connect`, `add_keyframe`,
  `get_keyframes`, `copy_tool`, `set_position`, …) were missing from the tool
  list. The decorator is restored to `fusion_comp` and `_parse_pos` is once
  again a plain internal helper. Live-validated on DaVinci Resolve Studio 21.

## What's New in v2.36.0

Optional networked transport — run the MCP server over the network, safely, with
control-panel management. Local stdio remains the default and is unchanged.

- **Added** `--transport stdio|sse|streamable-http` (default `stdio`). The networked
  modes bind to **loopback (127.0.0.1) by default** and **require a bearer token** on
  every request (from `$DAVINCI_MCP_TOKEN`, or generated + logged at startup). A
  non-loopback bind logs a loud security warning. stdio is untouched; you can run a
  local stdio instance and a networked instance against the same Resolve at once.
- **Added** control-panel management (Setup → MCP): a Transport card showing the live
  mode / URL / token / loopback status, with Start/Stop buttons (loopback-only). Backed
  by `/api/mcp/transport/{start,stop}` and a transport field on `/api/mcp/status`.
- The page-switch lock (v2.34.1) already serializes concurrent page switches across the
  local and networked instances.

## What's New in v2.35.2

Verification observability and a validator consolidation.

- **Added** `resolve_control(action="verification_stats")` returns a
  process-level tally of readback-verification outcomes
  (verified / contradicted / unverified) since server start. A rising
  `contradicted` count means the Resolve API reported success but a readback
  disagreed. No connection required.
- **Changed** `open_page` now validates its `page` argument through the declarative
  contract layer (`contracts.validate`) instead of a hand-written enum check —
  behavior unchanged; part of folding scattered validation into one place.

## What's New in v2.35.1

- **Added** `media_pool_item(action="extract_frames", clip_id, timestamps, output_dir?)`
  extracts still JPEGs from a clip's source media at the given timestamps (seconds)
  via ffmpeg. Source-safe: it reads the source and writes only to a scratch output
  directory — it never modifies, transcodes, or proxies the source. (Closes a
  read/write-symmetry gap: the analysis sampler existed internally but had no
  standalone frame-extraction tool.)

## What's New in v2.35.0

The Cut-IR executor — transcript-driven editing now closes the loop onto the
timeline.

- **Added** `timeline(action="apply_cuts", cuts, dry_run?, confirm_token?)` applies
  a CutList (from `propose_cuts`) to the timeline as lift / ripple deletes. It is
  **DRY-RUN by default**; applying is destructive and fully governed: confirm-token
  gated, and a timeline version is archived first (so it is reversible), through
  the existing destructive hook. Cuts apply latest-first so ripple deletes do not
  invalidate earlier spans. Live-validated end-to-end (propose -> token -> apply ->
  version archived).

## What's New in v2.34.1

Page-switch serialization — the concurrency primitive for safe multi-agent use.

- **Added** `src/utils/page_lock.py` — Resolve has a single globally-active page,
  so two agents that flip pages concurrently corrupt each other. `page_lock()`
  serializes page switches: a reentrant intra-process lock plus a best-effort
  inter-process advisory file lock around the outermost section. The `open_page`
  action now routes through it. This must be in place before any concurrent-agent
  feature ships.
- Networked transport, sandboxed scripting, and capability/role scoping (the rest
  of the safe remote/multi-user design) are security-critical and remain a
  separate, sign-off-gated phase — they are intentionally not shipped here.

## What's New in v2.34.0

First phase of transcript-driven editing: a Cut intermediate representation and a
mechanical cut proposer.

- **Added** `src/utils/cut_ir.py` — the Cut-IR: a typed representation of an
  editorial cut ({kind, span, action, confidence, rationale, evidence}) plus a
  deterministic Pass-1 detector that flags filler words, long pauses, and
  repeated lines from a timestamped transcript. No LLM.
- **Added** `timeline(action="propose_cuts", cues?, long_pause_frames?)` — a
  DRY-RUN that runs Pass-1 over the timeline's subtitle transcript (or provided
  cues) and returns a CutList. It proposes only; it applies nothing. The semantic
  Pass-2 and the governed timeline executor are subsequent phases.

## What's New in v2.33.8

Bridge-call performance instrumentation.

- **Added** `src/utils/bridge_metrics.py` — a counting proxy that wraps a Resolve
  handle and tallies attribute accesses and method calls (each a COM/socket
  round-trip), so the real bridge cost of an operation is measured rather than
  guessed.
- **Added** `scripts/measure_bridge_cost.py` — runs a representative media-pool
  traversal through the proxy and reports round-trips per clip. A minimal
  name+type walk measured ~6.7 round-trips per clip, confirming round-trips scale
  linearly with traversal size. A property cache remains gated on profiling
  *repeated*-read patterns in real workflows (don't cache blind).

## What's New in v2.33.7

Read/write symmetry audit and a gap it surfaced.

- **Added** `scripts/audit_readwrite_symmetry.py` + generated
  `docs/reference/readwrite-symmetry.md` — scans every tool's action surface and
  reports `set_`/`add_`/`create_` writes that lack a read counterpart, so
  write-without-read gaps surface before users hit them. A repeatable
  feature-discovery method.
- **Added** `fusion_comp(action="get_frame_range")` — reads the comp's render
  frame range, the read counterpart to `set_frame_range` (a gap the audit found).

## What's New in v2.33.6

Internal consolidation: a declarative parameter-contract validator and centralized
subprocess hygiene.

- **Added** `src/utils/contracts.py` `validate(params, rules, invariants)` — one
  validator for required/type/enum/min/max/non-empty/parent-dir-exists plus custom
  invariants, returning consistent agent-friendly errors with coercion + defaults
  applied. Replaces scattered, hand-written validation.
- **Changed** `export_frame_as_still` and `set_mark_in_out` (clip + timeline) now
  validate through contracts. Behavior is preserved (same rejections); `mark_in`/
  `mark_out` are now coerced to int.
- **Added** `src/utils/proc.py` `safe_run`/`safe_popen` — subprocess wrappers that
  default `stdin` to DEVNULL so a child can't consume the MCP stdio protocol
  stream. Inline Python execution now routes through `safe_run`.

## What's New in v2.33.5

A queryable ledger of verified Resolve API behavior.

- **Added** `resolve_control(action="api_truth", query?)` returns
  behaviorally-verified facts about quirky or unreliable Resolve scripting-API
  behavior — methods that live on unexpected objects, return values that lie,
  silently-rejected string keys, and calls that don't exist. Each fact records
  the reality, a recommended approach, and the Resolve build it was verified on.
  No connection required. Backed by `src/utils/api_truth.py`, seeded from
  hard-won findings (AutoSyncAudio, Fusion Paste, FlowView positions,
  GetTimelineByName, project render methods, transcription truncation, the
  CreateProject modal, stdio subprocess hygiene) and meant to grow over time.

## What's New in v2.33.4

Internal reliability framework.

- **Added** `verify_by_readback` (`src/utils/readback.py`) — a primitive for
  mutating Resolve ops that verifies an action by reading the real post-state
  back instead of trusting the API's frequently-unreliable return value. A
  contradiction (reported success but a failing readback) is logged as a
  reliability signal.
- **Changed** Auto-sync audio now runs through `verify_by_readback` as its first
  user and reports a `verified` field alongside `linked`/`newly_linked`. Behavior
  is unchanged; the bespoke readback loop is replaced by the shared primitive.

## What's New in v2.33.3

Two read tools that surface existing project state.

- **Added** `project_settings(action="project_summary")` returns a live
  structural readout — current page, timeline count and current timeline, and a
  media-pool inventory (folder/clip counts, clips by type, optional clip
  sample). A cheap "what's in this project right now" snapshot that needs no
  prior analysis.
- **Added** `timeline(action="get_transcript")` reads the current timeline's
  subtitle track(s) as transcript text `{text, cue_count, has_subtitles, cues}`,
  with optional per-cue timecodes. Complements the clip-level
  `get_transcription`.

## What's New in v2.33.2

Documentation: a guide for hand-authoring DaVinci Resolve `.setting` template
files.

- **Added** `docs/authoring/setting-files/` — how to author Edit effects,
  transitions, titles, generators, and Fusion macros as `.setting` files: the
  Lua-table format, the `InstanceInput`/`UserControls` control catalog, thumbnail
  conventions, Templates install paths, and a set of hard-won gotchas (ordered
  vs unordered `Inputs`, `ControlGroup` anchoring, transition easing via
  `LUTLookup`, `KeyStretcher` on titles, the category-subfolder rule, OFX
  boilerplate, and more). Includes 13 copyable starter templates and is linked
  from `docs/SKILL.md`.

## What's New in v2.33.1

Clip transcription read-back and more trustworthy auto-sync reporting.

- **Added** `media_pool_item(action="get_transcription")` returns
  `{text, truncated, status, has_transcription}`. Transcription could previously
  be triggered but never read back. Resolve's `Transcription` clip property is a
  preview that ends in an ellipsis when the full transcript is longer, so
  `truncated` tells callers the returned text is partial.
- **Changed** Auto-sync audio now verifies linkage by reading each clip's
  `Synced Audio` property before and after the call and reporting
  `linked` / `newly_linked` / `already_linked`, instead of trusting
  `AutoSyncAudio`'s unreliable boolean. The boolean is still returned as
  `success`, but callers should trust `linked`.

## What's New in v2.33.0

Fusion node-graph layout and duplication, plus performance and robustness
improvements across the compound server. Live-validated on DaVinci Resolve
Studio 21.0.0.

### Fusion node layout & duplication

- **Added** `fusion_comp(action="get_position")` and `set_position` — read and
  write a node's position on the FlowView canvas. `set_position` confirms the
  move by reading the position back.
- **Added** `fusion_comp(action="copy_tool")` — duplicate a node, optionally
  renaming and repositioning it. Settings are carried through a temporary
  `.setting` file, which round-trips reliably across the Python bridge where the
  in-memory `SaveSettings()`/`Paste()` table form fails.
- **Added** `fusion_comp(action="auto_arrange")` — lay tools out in a row
  (`direction="horizontal"`) or column (`"vertical"`) at a given spacing.

### Performance

- **Changed** Resolve object inspection walks `dir(obj)` once instead of once for
  methods and again for properties, skips `inspect.signature()` for C-extension
  methods (slow and almost always raising there), and reads `__doc__` directly.
  Each attribute access on a Resolve object is a bridge round-trip, so this
  roughly halves inspection cost on the `resolve_control` path.
- **Changed** Media-pool find-by-name lookups walk the folder tree lazily and
  stop at the first match instead of materializing the entire project tree.

### Robustness & fixes

- **Fixed** `export_frame_as_still` rejects an empty path or a nonexistent target
  directory instead of silently returning failure.
- **Fixed** `set_mark_in_out` (clip and timeline) rejects `mark_in > mark_out`.
- **Fixed** Auto-sync audio resolves `AUDIO_SYNC_*` enum constants via the live
  Resolve handle, closing a path where a stale module handle silently degraded
  `AutoSyncAudio` to rejected string keys.
- **Changed** Every `subprocess` call that can run while the MCP stdio server is
  active now sets `stdin=subprocess.DEVNULL`, so a child process cannot consume
  bytes from the JSON-RPC protocol stream; the spec-hook runner also captures its
  child's output. Applies to both the compound and granular launchers.

## What's New in v2.32.2

Fixes `fusion_comp(action="get_keyframes")` serialization.

The handler iterated `Input.GetKeyFrames()` as if it returned `{time: value}`,
but Fusion returns `{1-based index: frame_position}`. The result put the
keyframe **index** in `time` and the **frame position** in `value` — the actual
keyframed values were never reported.

The handler now treats the dict values as frame positions and reads each
keyframed value back via `GetInput(input_name, frame)`.

- **Fixed** `get_keyframes` now returns `[{"time": <frame>, "value": <value>}, ...]`
  in frame order (live-validated on DaVinci Resolve Studio 21.0.0:
  `Size` keyed `1.0@f0` / `1.4@f75` → `[{0.0: 1.0}, {75.0: 1.4}]`).
- Follow-up to the `add_keyframe` fix in v2.32.1; flagged by @sandypoli-boop in #56.

## What's New in v2.32.1

Fixes `fusion_comp(action="add_keyframe")` so it actually **animates** the input.

Previously the handler did `inp[time] = value` on the input directly. On an input
with no animation spline, that only assigns a **static** value (last write wins) —
no keyframe is created. Symptoms: `get_keyframes` returned `[]`, `get_input` at
different times returned the same value, and the clip never animated.

The handler now attaches a `BezierSpline` modifier the first time an input is
animated, then sets the keyframe. A new optional `modifier` param lets callers
pass e.g. `"Path"` for Point inputs such as `Center`. Behavior is unchanged for
inputs that are already animated or otherwise connected.

- **Fixed** `add_keyframe` now creates real, editable keyframes (live-validated on
  DaVinci Resolve Studio 21.0.0).
- **Added** optional `modifier` param to `add_keyframe`.
- Thanks to @sandypoli-boop for the diagnosis and fix ([#56](https://github.com/samuelgursky/davinci-resolve-mcp/pull/56)).

## What's New in v2.32.0

Adds **governance tiers** for the media-creating Resolve 21 AI ops (Phase 3, the
final phase of the AI-ops build: ledger → console → governance).

The two ops that render new files — `remove_motion_blur` and `generate_speech` —
now have **soft, per-session limits** chosen by a named tier:

| dimension | off | lenient | standard | strict |
|---|---|---|---|---|
| deblur runs | ∞ | 50 | 15 | 5 |
| speech runs | ∞ | 50 | 15 | 5 |
| media created | ∞ | 50 GB | 10 GB | 2 GB |
| render time | ∞ | 1 h | 20 min | 5 min |

Governance is **advisory** — it never hard-blocks (the ops are already
confirm-token gated). When you're near or over the active tier, the confirmation
dialog surfaces a warning before you proceed; the limits are computed from the
v2.30.0 AI-ops ledger for the current session.

- **New module** `src/utils/resolve_ai_governance.py` — tiers + `check()` (status
  for the next run) + `status()` (session usage vs tier). Default tier: `standard`.
- **New MCP actions** `media_analysis(action="get_ai_governance")` and
  `media_analysis(action="set_ai_governance", preset, overrides?)`. Override keys:
  `deblur_runs`, `speech_runs`, `render_bytes`, `render_wall_clock_ms` (int or `"unlimited"`).
- **Confirm preview** for the two creators now carries a `governance` block
  (current usage, projected, warnings, exceeded/near flags).
- **Control panel** — the AI Console gains a **Governance** section: a tier picker
  (off/lenient/standard/strict, with each tier's thresholds) plus live
  consumption gauges, and the confirm dialog shows the warning inline.

This completes the staged AI-ops build. Validated live against Resolve Studio
21.0.0.47 (tier switching, persistence, gauges, confirm-dialog warnings).

## What's New in v2.31.0

Adds the **AI Console** to the control panel — an interactive surface for the
Resolve 21 local AI operations (Phase 2 of the staged AI-ops build: ledger →
console → governance).

A new **AI Console** tab runs the 21.0 ops against the current Media Pool folder
or a specific clip:

- **Capability matrix** — shows which AI methods this Resolve build exposes (green
  = available, grey = absent on older builds) and which Extra each gated method
  needs to actually run.
- **Analysis** — Classify audio / Clear classification, IntelliSearch (with
  identify-faces and Better-mode toggles), Analyze for slate (16-color marker
  picker), Transcribe (with speaker-detection toggle), Clear transcription.
- **Motion deblur** and **Speech generator** — full options forms; because both
  create new media files they route through a confirmation modal (the same
  confirm-token gate the MCP tools use) before running.
- **Session** — Disable background tasks for the current Resolve session.
- A live result readout, and the *Resolve 21 AI ops* ledger refreshes after each
  run so file/byte totals stay current.

Backend: a loopback-only `POST /api/resolve_ai/run` endpoint dispatches each op
to the consolidated `folder` / `media_pool_item` / `project_settings` /
`resolve_control` tools, relaying the confirm-token two-step. No new MCP tools or
Resolve API surface — the console reuses the existing v2.29.0 actions. Validated
live end-to-end against Resolve Studio 21.0.0.47.

## What's New in v2.30.0

Adds the **Resolve 21 AI-ops ledger** — usage/time/file accounting for the
Resolve-local AI operations added in v2.29.0 (audio classification, IntelliSearch,
slate, motion-deblur, speech generation). These run on Resolve's own GPU/AI engine
and do **not** consume the Claude-side analysis token budget, so they get their
own ledger instead of being metered by the analysis-caps layer.

**What's tracked.** Every run of the five 21.0 ops records: op name, op class
(`analysis` vs `render`), clip id, success/failure, wall-clock time, and — for the
two media-creating ops (`remove_motion_blur`, `generate_speech`) — the output
file path and byte size. The reliable signal is invocation counts + the
file/disk accounting for the creators; durations for the bool-returning analysis
ops reflect the script-call time (some queue work inside Resolve).

- **New table** `resolve_ai_op_usage` (timeline_brain DB schema v7).
- **New module** `src/utils/resolve_ai_ledger.py` — `timed()` context manager +
  `record_op` / `get_usage` / `get_summary`. All writes are best-effort and never
  block or mask the underlying Resolve op.
- **Instrumentation** wraps the consolidated `folder` / `media_pool_item`
  `perform_audio_classification` / `clear_audio_classification` /
  `analyze_for_intellisearch` / `analyze_for_slate` / `remove_motion_blur`
  handlers and `project_settings.generate_speech`.
- **New MCP action** `media_analysis(action="get_resolve_ai_usage", session_only?, op?, limit?)`
  returns the per-op summary + recent runs.
- **Control panel**: a read-only "Resolve 21 AI ops" card (`/api/resolve_ai_usage`)
  shows runs, success/fail, total time, and files/bytes created.

Phase 1 of a staged build (ledger → interactive console → governance). Granular
`--full` server instrumentation is deferred — the ledger covers the consolidated
server, which is the default surface. Validated live against Resolve Studio 21.0.0.47.

## What's New in v2.29.0

Adds the **DaVinci Resolve 21.0** scripting-API additions. Every new method is
runtime-detected (`_requires_method`/capability flags), so the tools stay inert
on older Resolve builds and activate automatically on Resolve 21+.

**New AI analysis actions** on the `folder` and `media_pool_item` compound tools
(and mirrored as granular `--full` tools):

- `perform_audio_classification` / `clear_audio_classification` — classify clip
  audio into categories and subcategories.
- `analyze_for_intellisearch(identify_faces?, is_better_mode?)` — IntelliSearch
  analysis with optional face identification. Requires the *AI IntelliSearch* Extra.
- `analyze_for_slate(marker_color?)` — slate/clapboard detection that drops a
  marker of the chosen color (validated against the 16 Resolve marker colors).
  Requires the *AI Slate ID* Extra.
- `remove_motion_blur(deblur_option?)` — renders motion-deblurred copies. This
  **creates new media files** (source media is never modified) and is therefore
  **confirm-token gated**: the first call returns a preview + token, the second
  call (with the token) runs.

**Speaker-detection transcription.** `transcribe_audio` now accepts an optional
`use_speaker_detection` boolean (Resolve 21+); omit it to use the project's
Speech Recognition setting.

**Speech generation.** `project_settings(action="generate_speech", ...)` wraps
`Project.GenerateSpeech` (AI text-to-speech). It creates a new audio item and
optionally places it on the timeline, so it is also confirm-token gated.
Requires the *AI Speech Generator* Extra. Granular `--full` tool: `generate_speech`.

**Session control.** `resolve_control(action="disable_background_tasks_for_current_session")`
wraps `Resolve.DisableBackgroundTasksForCurrentResolveSession()` to quiet
background work during heavy scripted runs.

**Capability surface.** The `media_analysis` transcription-capability report and
the control panel's boot payload (`resolve.ai_features`) now list which 21.0 AI
methods are available and which Extras each gated method needs.

Notes: these are Resolve-local GPU/AI operations and do not consume the
Claude-side analysis token budget, so they are not metered by the analysis-caps
layer; the derivative-creating ones are protected by the confirm-token gate
instead. The granular `--full` server grew from 329 to 341 tools.

## What's New in v2.28.1

Bug-fix release.

**Audio transcription no longer passes an invalid `language` argument.** The
`transcribe_audio` (clip) and `transcribe_folder_audio` tools in the full
(`--full`) server were calling `TranscribeAudio(language)` with a language
string, but the Resolve scripting API has never accepted a language positional —
its signature is `TranscribeAudio(useSpeakerDetection=None)`. The string was
silently coerced to a truthy boolean and misread as a speaker-detection flag,
and the success message falsely claimed a transcription language. The language
is controlled by the project's Speech Recognition setting, not per call.

- `transcribe_audio(clip_name, use_speaker_detection=None)` — the `language`
  parameter is replaced with an optional `use_speaker_detection` boolean
  (Resolve 21+). Omit it to use the project's setting.
- `transcribe_folder_audio(folder_name, use_speaker_detection=None)` — same
  change for the folder-level tool.
- Both pass the boolean through only when supplied, so older Resolve builds
  (which take no argument) keep working.

The consolidated 32-tool server was unaffected — its `folder`/`media_pool_item`
`transcribe_audio` actions already called `TranscribeAudio()` correctly.

## What's New in v2.28.0

This release adds a structural timeline-diff engine, a declarative project spec
you can `apply` like infrastructure-as-code, a project health `lint`, a clip
query DSL, and a machine-readable `state` field on error responses.

**Timeline version diff — see exactly what an edit changed.** Comparing two
archived timeline versions now reports clips that were **added, removed, moved,
and trimmed**, plus summary counts and before/after clip totals. A new reusable
diff engine aligns clips by a rename-stable identity (so a reordered or renamed
clip reads as a move/change, not a delete-and-re-add).

- `timeline_versioning(action="diff_versions", timeline_name, from_version, to_version)`
  now returns `{added, removed, moved, trimmed, summary}` (the previous
  `added`/`removed`/`moved` keys are unchanged).
- Dashboard endpoint `GET /api/timeline_versions/diff?timeline_name=&from_version=&to_version=`
  exposes the same diff to the control panel.

**Declarative project spec + `apply` — reproducible project setup.** Describe a
project's desired settings, color preset, timelines, and markers in a
`project.dvr.yaml` (or `.json`), then reconcile the live project toward it. Runs
are **idempotent** — applying twice is a no-op — and a dry run previews every
change before anything is touched.

- New MCP actions on `project_manager`:
  - `diff_to_spec(spec_path | spec)` — preview drift without mutating.
  - `plan_spec(spec_path | spec)` — the ordered action list (dry run).
  - `apply_spec(spec_path | spec, dry_run?, run_hooks?, continue_on_error?)` —
    reconcile. Color/HDR settings apply in dependency order; markers are only
    added when absent; an explicit `color_preset` can be overridden by explicit
    `settings`. Failures can abort on first error or accumulate.
- New headless CLI commands: `davinci-resolve-mcp batch plan-spec SPEC` and
  `davinci-resolve-mcp batch apply SPEC [--dry-run] [--run-hooks] [--continue-on-error]`.
  Exit codes follow the existing convention (`0` ok, `2` partial, `3` fatal).
- Optional before/after shell **hooks** in the spec run only when `run_hooks` is
  passed (opt-in).

**Project health `lint` — a pre-flight before editing.** `project_manager(action="lint")`
returns a graded issue list (errors / warnings / info) covering: no project, no
current timeline, mixed frame rates across timelines, empty timelines, unset
render format, unmanaged color science, offline media, and unanalyzed clips.

**Clip query DSL — find clips in one call.** `timeline(action="clip_where", ...)`
returns the clips on the current timeline matching named filters (AND), instead
of enumerating tracks by hand. Live filters: `track_type`, `track_index`,
`name_contains`, `duration_lt`, `duration_gt`. A typo'd filter name is rejected
rather than silently matching everything.

**Machine-readable error context.** Structured error responses can now carry an
optional `state` object — a snapshot of the relevant values at failure time
(e.g. which filter was unknown, which spec failed and where) — so an agent can
react without parsing prose. Existing error fields are unchanged.

## What's New in v2.27.2

**Control panel under-counted analyzed clips after a Media Pool rename (issue
#51)** — with every clip analyzed (e.g. 303/303 reports on disk), the overview
and Media tab could report something like "108 / 303 analyzed". The panel only
recognized a report when a folder's name exactly matched the clip's *current*
display name, so renaming clips after analysis hid their existing reports even
though the underlying media was unchanged.

Root cause and fix:

- **Lookups are keyed by a rename-stable hash, not the display-name folder.**
  Report folders are named `<display-slug>-<hash>`; the count now matches on the
  trailing hash (and the ids inside each report), so a renamed clip still
  resolves to its existing folder. Both the disk path and the jobs-DB fallback
  were corrected.
- **The hash is now anchored to the normalized file path (canonical basis).**
  Previously the basis was a `clip_id`-first cascade, so the same media hashed
  differently depending on which fields a record carried — Resolve inventory
  (clip_id) vs path-based batch jobs (file path) disagreed on the same clip.
  Anchoring to the file path removes that cross-basis mismatch. Legacy folders
  (clip_id-based, or raw-path-based) still resolve via a migration-safe set of
  candidate hashes, so **no on-disk migration is required**.
- **Writes reuse an existing report folder** (matched by canonical or legacy
  hash) instead of minting a new `<newslug>-<hash>` directory, eliminating
  orphaned duplicate folders when a renamed clip is re-analyzed.
- **A persisted clip index (`clips/index.json`)** maps every stable id found in
  a report (normalized + raw file path, clip_id, media_id) to its folder, so the
  count can still match a clip by any id it carries — including an offline clip
  that no longer reports a file path but retains its clip_id. The index is
  refreshed only when a report is added, removed, or rewritten (cheap signature
  check), so the recurring poll stays inexpensive.

No public MCP tool surface changed. Adds regression tests in
`tests/test_media_analysis.py` covering rename, cross-basis, legacy-folder reuse,
the jobs-DB fallback, and the offline/no-path case.

## What's New in v2.27.1

**Faster control-panel startup with network source media (issue #50)** — on
first open the control panel could sit on "connection pending" for a long time
when Media Pool clips lived on mounted network storage, because the UI only
treated the connection as live once the full media inventory finished loading,
and that inventory probed every clip's file path on disk.

Fixes and performance work:

- **Connection state is decoupled from the media inventory.** The overview and
  diagnostics panels now derive "connected" from the `/api/boot` handshake (which
  returns as soon as the Resolve bridge is reachable) and show inventory loading
  separately, so Resolve reads as live immediately while clips stream in.
- **Parallel, cached file-existence probing.** `os.path.exists` for every clip
  now runs in a thread pool and is memoized for a short TTL, instead of two serial
  `stat()` calls per clip — the dominant cost on network storage.
- **Background polls reuse the cached Media Pool walk.** The recurring poll no
  longer re-runs the ~N serial `GetClipProperty` calls; it reuses the last walk
  and re-applies only the local, disk-backed analysis-status overlay. A cheap
  project-id check still catches a project switched directly in Resolve, and a
  manual refresh always does a full walk.
- **Resolve scripting API access is serialized.** A re-entrant lock guards every
  scripting-API entry point, since the dashboard's threaded HTTP server could
  previously fire concurrent (thread-unsafe) Resolve calls at startup.
- **ETag/304 on the inventory endpoint** skips transfer and table re-render when
  nothing changed; the last good inventory is cached client-side and painted
  instantly on reload; and the first inventory build is warmed in a background
  thread at server start.

No public MCP tool surface changed. Adds regression tests in
`tests/test_media_analysis.py` (path-existence probing, inventory cache reuse,
project-switch detection, lock reentrancy).

## What's New in v2.27.0

**Frame-sampling modes (issue #46)** — how many frames a clip gets for visual
analysis is now governed by a `sampling_mode`, decoupled from `depth` (which
still controls which layers run). A fixed frame count over-sampled short clips
and under-covered long ones; the demand-driven engine already scaled by
duration/content, but the caps layer was flat-truncating its output back to 8
frames — that flat cap was the real cause of long-clip under-coverage.

Four clearly-tiered modes, organized so token cost is predictable per tier:

- **Economy** (`fixed`) — flat N evenly-spaced, content-blind frames. Cheapest and
  most predictable; good for proxies/triage.
- **Balanced** (`per_minute`) — `clamp(minutes × frames_per_minute, floor, ceiling)`
  (defaults 4/min, 3–80). Cost is linear in footage length; content-blind.
- **Thorough** (`adaptive_capped`, recommended/default) — content-aware: samples
  shot boundaries, representatives, and flash candidates, bounded to `[floor,
  ceiling]`. Best coverage with a bounded cost.
- **Thorough (uncapped)** (`adaptive`) — content-aware with no per-clip ceiling
  (up to the 512-frame hard cap). Use only when clips are short or few.

The first time you analyze without a saved default, the tool returns a
`confirmation_required` response with a `sampling_mode_prompt`; choosing a mode
saves it as your standing default (mirrors `timed_markers_default`). Pass
`sampling_mode` per call any time for a one-off that doesn't change the default.
Tunables (`frames_per_minute`, `frame_floor`, `frame_ceiling`) and the mode are
all exposed in the control panel (Preferences → Frame sampling mode) with a live
per-clip token-cost estimate; batch jobs honor the saved default.

Analysis-caps presets were retuned so `frames_per_clip` is now a *safety ceiling*
(minimal/standard/generous = 12/80/200), not the primary frame dial, and the
per-clip/job/day vision-token caps were raised so the default Thorough mode isn't
refused by the per-clip token cap. Cache reuse re-samples only when switching up
the thoroughness rank; a richer prior report still satisfies a cheaper mode. Adds
`tests/test_sampling_modes.py` (30 tests). Validated end-to-end on a synthetic
multi-shot clip with real ffmpeg frame extraction.

## What's New in v2.26.1

**Python 3.13 / 3.14 support (issue #45)** — `npx davinci-resolve-mcp setup`
previously hard-refused any interpreter outside 3.10–3.12, so it failed outright
on Python 3.14. The 3.12 ceiling was based on a stale assumption that Resolve's
scripting bridge has ABI incompatibilities on 3.13+. Verified empirically against
DaVinci Resolve Studio 20.3.2.9: Python 3.14.4 connects and exercises the
dict/list marshalling paths cleanly. The launcher and installer now enforce only
the 3.10 floor (the `mcp[cli]` SDK requirement) with no upper cap. Python 3.13/3.14
are accepted with a soft heads-up; `setup`/`doctor` surface a precise,
connection-aware hint only when Resolve is running but the bridge returns no
connection on 3.13+. Sub-3.10 interpreters get an actionable error instead of a
dead end. `server.py` warns (never exits) on 3.13+. Adds 6 version-gate unit tests.

## What's New in v2.26.0

**Fusion group-settings helpers** — Three new `fusion_comp` actions for
authoring and patching `GroupOperator` macros without leaving the kernel.
`group_settings_export` writes a live group to a `.setting` file and returns a
parsed `published_inputs` summary using a balanced-brace walker so nested
`UserControls` / `ControlGroup` tables are bounded correctly (the original
flat-regex parser truncated `InstanceInput` bodies at the first inner `}`).
`group_settings_splice_inputs` replaces the `Inputs = ordered() { ... }` block
of one `.setting` with the matching block from another, preserving the source's
outer structure and inner `Tools`. `group_settings_load` applies a `.setting`
to a live group with an automatic timestamped backup, wrapped in
`StartUndo`/`Lock`/`LoadSettings`/`Unlock`/`EndUndo(True)` so Fusion's Ctrl+Z
reverses the change — verified live via direct BMD API.

**bulk_set_expressions** — Companion to the existing `bulk_set_inputs`. Batch
attach Fusion expressions across many timeline-item comps in one call. Each op
requires timeline scope plus `tool_name`, `input_name`, `expression`. Returns
per-op `success`/`error` rows + `op_count`, matching the bulk-inputs contract.
Useful for animating many controls at once (`time/30`, etc.) under a single
chat turn.

**Headless batch-runner CLI** — New
`davinci-resolve-mcp batch <plan|run|status|list|resume|cancel>` subcommand
drives `src/utils/media_analysis_jobs` from outside an MCP/chat client so long
analysis batches can run via cron, CI, or terminal without holding a chat turn
open. The orchestration loop and durable state stay in the existing jobs
engine; the CLI only handles argv, progress streaming, and exit codes
(`0` ok / `2` partial / `3` fatal / `130` Ctrl+C). JSON mode (`--json`)
emits one record per progress event for log scraping. Closes #42.

**Adapted from PR #40** — Group-settings work originated as a contribution
from @RaincloudTheDragon; PR #43 retains the keepable parts (parser, exporter,
splicer, loader, `bulk_set_expressions`) with a balanced-brace fix on the
parser and an undo+lock wrap on `group_settings_load`. The two AMZ-specific
templates and the static checklist from #40 were dropped as out-of-scope for a
general kernel.

## What's New in v2.25.0

**Agentic flow improvements** — A second-pass review against the Claude
Certified Architect study material drove a sweep of correctness gains. Every
tool error now returns a structured envelope (`code` / `category` /
`retryable` / `reason` / `remediation` / `message`); `retryable` defaults are
locked per category so a host can make a one-shot retry decision without
inference. Compound-tool descriptions for `media_analysis` and
`timeline_item_color` adopt XML semantic tags (`<when_to_use>`, `<actions>`,
`<returns>`) for cheaper per-turn parsing. Repeated failures on the same
`(scope, action)` pair attach an `escalation` block on the 3rd response —
halts auto-retry loops with a `suggested_action` for the host. Batch
manifests now always carry `partial_success`, `completed_clip_ids`, and
`failed_clip_ids` for safe targeted retry.

**MCP resources surface** — 8 read-only resource URIs the host can poll
without paying a tool-turn cost: `status://mcp_version`,
`status://resolve_connection`, `status://current_project`,
`status://current_timeline`, `status://caps_preset`,
`analysis://recent_reports`, `capabilities://installed_tools`,
`capabilities://install_guidance`. Paired tools still work for hosts that
don't consume resources.

**MCP prompts surface** — 5 slash-command workflow templates:
`/davinci-resolve:analyze_and_propose_grade`,
`/davinci-resolve:match_bin_to_hero`,
`/davinci-resolve:verify_timeline_coverage`,
`/davinci-resolve:open_and_analyze_selection`,
`/davinci-resolve:prep_color_handoff`. First-class agentic intent, no
re-derivation from SKILL.md prose.

**Color-grading evidence base** — `timeline_item_color.grade_evidence_base`
composes `version_snapshot` + `node_graph` + `color_group` + coverage report
into a single `evidence_base` summary string; the SKILL guide now teaches
agents to lead any color recommendation with that line.
`timeline_item_color.propose_grade` formalizes a recommendation as a
validated structured plan (returns `plan_id` + `preview_path`; requires
explicit `execute=true` re-call). `bulk_match_to_hero` drives CDL-delta or
copy-grade across many targets with a `confirm_token` gate and dry-run
preview.

**Analysis caps layer** — Token-budget governance for analysis. 7 cap
dimensions across vision/transcription/job/clip/day scopes, 4 named presets
(`minimal` / `standard` / `generous` / `unlimited`), pre-call refusal with
`CAPS_REFUSAL` / `budget_exhausted` / `retryable: false`. New
`media_analysis` actions: `get_caps`, `set_caps_preset`. Token usage table
in the analysis DB plus a control-panel widget with gauges + override
inputs. Wall-clock timeout helper wraps vision/transcription call sites.

**Timeline versioning + analysis↔timeline marriage** — New
`timeline_versioning` MCP tool: every destructive timeline edit
auto-archives the current timeline into an Archive bin (compound, captions,
ripple, gap close, etc.), so versions can be diffed and rolled back. Run
scoping, schema v4 migrations, concurrency safety, structural snapshots,
action filtering, strict mode, auto-save preference, media-pool destructive
coverage, thumbnails. Backed by new modules `timeline_versioning.py`,
`timeline_brain_db.py`, `brain_edits.py`, `analysis_runs.py`,
`media_pool_changes.py`, `destructive_hook.py`. Surfaced in the control
panel's Review → History view.

**Async opt-in for long-running ops** — `analyze_clip` / `analyze_file` /
`commit_vision` accept `prefer_handle: true`. When set (and the estimated
runtime exceeds the configured threshold), the response is a fast handoff
with `job_id` + `status: "queued"`; poll `batch_job_status({job_id})`.
Default behavior unchanged.

**Aggregated provenance** — `summarize`,
`review_timeline_markers`, and `grade_evidence_base` now return a
`provenance` block: `source_reports[]` (clip_id, signature, report_path,
analyzed_at), `missing_reports[]` (per reason: `no_report` / `stale_report`
/ `caps_refused`), and inline `[ref:<clip_id>]` citations in the human
summary text. Multi-clip claims are now traceable.

**Confirm-token gates on destructive batches** — `propose_grade`,
`bulk_match_to_hero`, and other multi-target writes now require an explicit
`confirm_token` on first execute (returned on the dry-run), with a
`pending_user_decision` error if missing.

**Action-help indirection** — `action_help(name=...)` returns the long-form
guidance for a single action, keeping the top-level tool descriptions
compact while preserving full per-action documentation.

**Tool-choice hint emission** — Analyze responses include a
`host_tool_choice_hint` block. Hosts that respect it pass
`tool_choice={type:"tool", name:"media_analysis"}` on the next API turn,
hard-locking the agent into the correct next call.

**Update process hardening** — Five improvements layered onto the
update-check path: active-job lock prevents updates mid-analysis, auto-stash
strategy preserves uncommitted work across updates, restart-needed marker
surfaces to the host, channels (`stable` / `beta` / `dev`), pre-update
breaking-change scan, integrity SHA verification of downloaded artifacts,
update history table, eager DB migration on update, and rollback to the
previous build. New `analysis_caps.py` + `update_check.py` revisions.

**Source-safe guardrails** — `destructive_hook.py` + decorator coverage
tests ensure every destructive surface goes through the auto-archive path
and never modifies, transcodes, or creates derivatives of source media.

**Test surface** — 30+ new test modules covering error envelopes,
failure tracking, partial-success manifests, `prefer_handle`, MCP resources,
MCP prompts, provenance, XML description shape, `action_help`,
`grade_evidence_base`, `propose_grade`, `bulk_match_to_hero`,
`confirm_token`, the analysis caps layer, caps integration / events /
history, timeline versioning, the timeline-brain DB, destructive decorator
coverage, the destructive hook, update hardening, and update history.

**Validation** — `tests/test_import.py`, `scripts/audit_api_parity.py`,
`node bin/davinci-resolve-mcp.mjs --version`, `npm pack --dry-run`, and
`git diff --check` all pass. 375 focused unit tests pass. Live Resolve
validation covered the D1–F2 surface end-to-end against project CKY /
Timeline 7 (D1 `retryable`, D2 XML descriptions, D3 partial-success on
plans + CAPS_REFUSAL manifests, E1 8 MCP resource URIs, E2 escalation on
3× repeated failure, E3 `prefer_handle` job handoff with
`batch_job_status` polling, F1 provenance block) — 6/6 PASS on the
fourteenth-attempt smoke test. No source media was modified.

## What's New in v2.24.1

**`npx davinci-resolve-mcp` no longer breaks MCP clients when invoked without a
subcommand.** The npm bootstrapper previously defaulted to `--help`, which wrote
usage text to stdout and exited 0. MCP stdio clients (Hermes Agent, Claude
Desktop, Cursor, etc.) read that as malformed JSON-RPC, retried three times,
then dropped the connection. `bin/davinci-resolve-mcp.mjs` now defaults to the
`server` subcommand when no arguments are supplied. Explicit `--help`, `-h`,
`help`, `--version`, and `-v` continue to print to stdout as before, and
existing configs that already pass `server` explicitly are unaffected. Reported
in [#41](https://github.com/samuelgursky/davinci-resolve-mcp/issues/41).

## What's New in v2.24.0

**Host-chat vision protocol (V2)** — `analyze_*` actions now use
`vision.provider="host_chat_paths"` by default. The analyze response is a
deferred payload with absolute `frame_paths`, a per-shot `shot_table`, and a
JSON schema; the host chat reads each frame as a local image, produces JSON per
the schema, and calls `media_analysis(action="commit_vision", params={clip_id,
visual, vision_token})` to finalize. `commit_vision` merges the visual report,
rebuilds Media Pool clip markers, publishes metadata to Resolve, and preserves
human corrections via `corrections.json`. Skipping the commit leaves the run in
`pending_host_vision_analysis` — surfaced explicitly rather than silently
downgraded. The legacy `chat_context`/`mcp_sampling` providers still resolve to
the same host-chat path.

**Trust-by-default analysis defaults** — `analyze_media` defaults to
`include_transcription=true`, `persist=true`, `publish_metadata=true`, and
`timed_markers="ask"` so source-safe no longer means underpowered. Agents that
need a technical-only or read-only run must explicitly pass
`include_visuals=false`, `include_transcription=false`, `publish_metadata=false`,
`timed_markers="no"`, `session_only=true`, or `dry_run=true`. The
`analyze_media` prompt and SKILL.md spell out the anti-regression rule.

**Control panel: Review surface (Phase B)** — The local browser control panel
gains a Review tab backed by new endpoints: `/api/clips`, `/api/clips/<id>`,
`/api/clips/<id>/shots`, `/api/clips/<id>/shots/<index>`,
`/api/clips/<id>/frames/<n>`, `/api/clips/<id>/transcript`,
`/api/clips/<id>/corrections`, `/api/clips/combined`, `/api/clips/export`,
`/api/panel_state`, `/api/update/status`, `/api/update/apply`, and
`/api/resolve/open_clip`. The UI ships a bin grid with thumbnails, a clip
detail with shot strip, a shot detail with grouped V2 fields + frame grid,
inline correction editors per subjective field, transcript correction +
regeneration, an Open-in-Resolve bridge, and 2-second chat ↔ panel state
polling.

**Control panel MCP actions** — `resolve_control.open_control_panel`,
`control_panel_status`, and `close_control_panel` manage the local panel
subprocess via a pidfile. `save_state` / `restore_state` snapshot and restore
Resolve playhead + selection state. `get_panel_state`, `set_panel_state`, and
`session_start_context` share panel focus between chat and the UI through
`panel_state.json`.

**Correction tools** — New `media_analysis` actions for editing analysis
without re-running it: `update_shot_field`, `update_clip_field`,
`get_field_history`, `revert_field`, `list_corrections`. Writes land in
`{clip_dir}/corrections.json` with append-only changelog + provenance
(mirrors the V2 DB schema). `commit_vision` merges corrections on top of the
fresh visual report so human edits survive re-analysis.

**Media Pool item open-in-viewer** — `media_pool_item.open_in_viewer` selects
a clip on the Media page and loads it into the source viewer, optionally
setting mark in/out and bringing Resolve to the foreground via OS-level
window activation. Useful for chat → Resolve hand-off.

**Source-trust prompt grading** — `source_trust` parameter
(`auto`/`filename`/`low`/`medium`/`high`) on analyze actions tunes the vision
prompt to hedge identity/intent/value for archival or thin-evidence clips.

**Analysis memory layer** — New `src/utils/analysis_memory.py` introduces
per-project memory + heartbeat + bin summary + soul scaffolding under the
analysis root. `regenerate_bin_summary_from_manifest` aggregates per-clip
fields (primary use, select potential, style, energy arc, top tags/locations)
into a bin briefing. Auto-initialized on analyze.

**Control-panel polish** — Diagnostics + Overview restyled with a status-pill
design system, navbar dropdowns fixed so top-level buttons no longer navigate
on their own, Preferences consolidated (Dashboard Convenience + Storage pages
removed), summary-style enum renamed to `full`/`concise`/`creative`/
`technical` with backwards compat, navbar version badge + update modal,
source-trust dropdown wired through.

**Server-side bug fixes** — `commit_vision` auto-publish now reflects per-row
status correctly (no silent-lie pending), compact analyze responses by default
(`verbose: true` for the full manifest), `resolve_output_root` skips slug
append when the configured base already terminates in the slug, frame sampler
reserves per-shot budget so shot starts aren't starved by flash candidates,
and machine markers are no longer written to Resolve (V2 architecture).

**Path hardening for GUI launches** — `media_analysis` now augments `PATH`
with the standard tool dirs (`/opt/homebrew/bin`, `/usr/local/bin`, etc.) so
ffprobe/ffmpeg resolve even when the MCP server is launched by a GUI app
(Claude.app, Dock/Spotlight) that inherits launchd's bare PATH.

**Documentation** — `AGENTS.md` adds the "Media Analysis Defaults Are
Mandatory" section. `docs/SKILL.md` rewrites the `analyze_media` prompt
guidance for the host-chat-paths protocol and adds the anti-regression rule.
`docs/guides/media-analysis-guide.md` covers the deferred vision payload and
commit step.

**Validation**: static import checks, API parity audit, focused
media-analysis + marker/range/v232/v233 unit tests, npm CLI smoke,
`npm pack --dry-run`, and `git diff --check` all passed. No source media was
modified. Resolve scripting behavior is additive (new actions; existing
actions unchanged); live Resolve validation covered the control-panel +
open_in_viewer + commit_vision auto-publish + corrections-merge paths during
the V2 push sessions logged in MEMORY.md.

## What's New in v2.23.1

**Control panel navigation fixes** — The local browser control panel now keeps
top-level dropdown buttons from navigating by themselves. Analysis,
Diagnostics, Docs, and Preferences open their menus first; selecting a menu item
is what changes the active view.

**Project dropdown cleanup** — The project context dropdown is back to showing
only the open/current project context plus a bottom `View All Projects` option.
The full database browser stays in the Projects view, and the standalone
Projects navbar button has been removed.

**Validation**: static import checks, API parity audit, focused dashboard unit
tests, npm CLI smoke tests, package dry-run, and `git diff --check` passed. A
local dashboard smoke check verified the served HTML on `127.0.0.1:8765`.
No Resolve scripting behavior changed; live Resolve mutation validation was not
required.

## What's New in v2.23.0

**npm installer** — `npx davinci-resolve-mcp setup` is now the primary quick
start. The npm package bootstraps a managed per-user install, runs the existing
Python installer from that stable location, and keeps MCP client configs pointed
at the managed virtual environment and `src/server.py`.

**Local control panel** — Added a single-user browser control panel for server
status, Resolve clip visibility, source-safe analysis jobs, analysis search, and
preference management. It can be launched from source with
`venv/bin/python -m src.control_panel` or from npm with
`npx davinci-resolve-mcp control-panel`.

**Durable media-analysis jobs and search** — `media_analysis` can now create,
slice, inspect, cancel, resume, and list durable analysis jobs. Persisted reports
refresh a single-user SQLite index with clip, marker, timeline occurrence,
keyframe, and transcript search helpers through `build_index`, `index_status`,
and `query_index`.

**Release automation** — Added npm package metadata, package-content guards, and
a tag-driven GitHub Actions workflow for trusted npm publishing with provenance.
The workflow skips publish when the package version already exists, which keeps
the first manual npm registration from fighting the later tag workflow.

**Validation**: static import checks, API parity audit, focused media-analysis,
update-check, and media-pool ingest unit tests passed. npm smoke tests, setup
dry-run, package dry-run, and `git diff --check` passed. No source media was
modified.

## What's New in v2.22.0

**Configurable MCP update prompting** — Update checks now carry a persisted
policy: `prompt`, `auto`, `notify`, or `never`. The server still never blocks
MCP stdio startup, but the installer can prompt users to update, continue,
snooze for 24 hours, ignore the current release, enable safe auto-update, or
disable checks. Safe auto-update is opt-in and only attempts a clean git
fast-forward from checkouts with no local changes and a configured upstream.

**MCP update controls** — `resolve_control.mcp_update_status` reports the local
MCP version, cached or forced update status, and the current prompt decision.
`set_mcp_update_policy`, `ignore_mcp_update`, `snooze_mcp_update`, and
`clear_mcp_update_preferences` expose the same policy state through the
compound server without requiring Resolve to be connected.

**Conversation setup defaults** — New `setup` compound tool centralizes
conversation-configurable defaults. It can read, set, dry-run, and clear
preferences for media-analysis modality, slate detection, transcription,
analysis persistence, metadata publish fields and overwrite policy, timed marker
types/colors/counts, report style, preferred analysis roots, post-operation page
behavior, and MCP update interval/snooze policy. These defaults shape future
tool calls while preserving explicit confirmation for Resolve project writes.

**Metadata field inventory** — `media_pool.metadata_field_inventory` gives
assistant editors and metadata workflows a read-only map of clip metadata,
clip-property keys, default analysis writeback fields, optional slate fields,
and inferred Resolve Metadata-panel groups. This helps bridge analysis
publishing to the fields Resolve actually exposes on a given clip/build.

**Optional timed analysis markers** — `media_analysis.publish_clip_metadata`
can now write source-frame Media Pool clip markers for slate claps, best
moments, and QC warnings when the user opts in. If no marker preference exists,
the tool returns a prompt with yes/no/default-yes/default-no choices rather than
silently writing markers.

**Validation**: static import checks, API parity audit, `git diff --check`, and
focused update-check, media-analysis, and media-pool ingest unit tests passed.
Media-pool ingest tests cover the new metadata inventory and Metadata-panel
group hints. Live validation used DaVinci Resolve Studio 20.3.2.9 through the
connected MCP server with a disposable project and synthetic media only. It
verified `metadata_field_inventory`, `MediaPool.ExportMetadata()` header
comparison, default analysis writeback field mapping, and `SetMetadata()`
readback for analysis and slate fields. The standalone live metadata inventory
harness is included for future release validation with a Resolve-compatible
Python 3.10-3.12 interpreter.

## What's New in v2.21.0

**Resolve metadata publishing from analysis** —
`media_analysis.publish_clip_metadata` turns source-safe analysis reports into
Resolve-native clip metadata. It proposes field-specific merges for
`Description`, `Comments`, `Keywords`, `People`, and optional slate-derived
fields, preserves existing human metadata by default, writes provenance to
third-party metadata, and requires `confirm=true` before mutating Resolve.

**Slate-aware metadata proposals** — Metadata publishing can reuse
`detect_sync_events` slate-clap evidence and, when chat-context sampling is
available, inspect frames around the clap for high-confidence slate fields before
proposing `Scene`, `Shot`, `Take`, `Camera #`, and `Roll/Card` writes.

**MCP update visibility** — The installer and both MCP server entrypoints now
perform a best-effort GitHub release check, cache the result under `logs/`, and
surface the local MCP version plus last update-check status from
`resolve_control.get_version`. Checks are informational only and never install
code automatically.

**Validation**: static/import checks, API parity audit, focused media-analysis,
sync-event, and update-check unit tests passed. Live validation used DaVinci
Resolve Studio 20.3.2.9 through the active Resolve script runner with disposable
projects and synthetic media only. `tests/live_metadata_publish_validation.py`
verified dry-run previews, confirmed metadata writes, human metadata
preservation, keyword merging, third-party provenance, and cleanup;
`tests/live_sync_event_validation.py` revalidated 2-pop/slate-clap detection and
confirmed marker writes.

## What's New in v2.20.0

**Sync event detection helper** — `media_analysis.detect_sync_events` detects
likely audio 2-pops and slate claps with FFprobe/FFmpeg, returns advisory
frame/timecode positions, and suggests per-file `record_offset` values for
`media_pool.setup_multicam_timeline(sync_mode="record_frame")`. The helper is
source-safe and never installs FFmpeg automatically. It also returns marker
suggestions; `media_analysis.add_sync_event_markers` writes Media Pool item
markers only when called separately with `confirm=true`.

**Validation**: static/import checks, API parity audit, focused media-analysis
and multicam unit tests, and `tests/live_sync_event_validation.py` passed. The
live run used DaVinci Resolve Studio 20.3.2.9, a disposable project, and
synthetic audio only; it verified detection, confirmation refusal, confirmed
Media Pool marker writes, and cleanup.

## What's New in v2.19.0

**Multicam setup support** — `media_pool.setup_multicam_timeline` creates a
source-safe stacked prep timeline from Media Pool clips, with one angle per video
track, optional matching audio tracks, and stack-start, manual record-frame, or
source-timecode planning. Native multicam clip conversion remains a Resolve UI
step because the public scripting API does not expose a multicam-create method;
the current UI workflow is documented in the DaVinci Resolve 20 Manual,
Edit > Chapter 42, "Multicam Editing."

**Documentation**: added `docs/guides/multicam-setup-guide.md` and linked the
helper from the README, docs index, AI skill reference, kernel coverage, ingest
kernel, and API coverage notes so it is clearly listed as a helper rather than
a native API feature.

## What's New in v2.18.0

**Edit-page title / Text+ text (undocumented keys)** — `timeline.title_property_scan`,
`timeline.set_title_text`, and `timeline.bulk_set_title_text` use
`TimelineItem.GetProperty` / `SetProperty` to discover and update generator Text+
payloads when `GetFusionCompCount()` is zero (no Fusion comp for `fusion_comp`).
Heuristic key ranking and a minimal styled-text XML fallback are included; callers
should confirm keys with `title_property_scan` on their Resolve build.

## What's New in v2.17.1

Operational and client-safety hardening for the v2.17 media-analysis release.

**MCP tool metadata**: compound and granular tools now publish MCP
`ToolAnnotations` with conservative read-only, destructive, idempotent, and
external-resource hints. Compound tool annotations are intentionally conservative
because each tool groups multiple actions behind an `action` parameter.

**MCPSafe report cleanup**: explicitly annotated the granular tools highlighted
by the public MCPSafe report, including project settings, media import, page
switching, proxy linking, Gallery album reads, and timeline-item transforms.

**Operational guardrails**: Resolve app-control subprocess fallbacks now use
bounded timeouts and report non-zero exits. Best-effort Resolve object
inspection and state probes now log swallowed exceptions at debug level instead
of failing silently.

**Correctness fix**: fixed the granular
`media_pool.append_to_timeline(clip_infos=...)` path so it retains the current
project handle while normalizing positioned appends against the active timeline
start frame.

**Documentation**: added `SECURITY.md` with the local stdio trust boundary,
confirmation guidance for destructive tools, source-media safety boundaries, and
private vulnerability reporting guidance. The README now links the security
policy and summarizes the local-only auth posture.

**Validation**: static/import checks, API parity audit, compileall, and 161
focused unit tests passed. Live validated against DaVinci Resolve Studio 20.3.2.9
with a direct external-scripting smoke test, `tests/live_v233_validation.py`
passing 10/10 checks, and a v2.17.1 disposable-project
`media_pool.append_to_timeline(clip_infos=...)` normalization probe passing 2/2
checks. The v2.17.1 probe used synthetic media only and verified the default
relative `record_frame` path landed at timeline start frame 86400 + 12 = 86412,
while `record_frame_mode="absolute"` preserved frame 86484.

## What's New in v2.17.0

Media analysis and editorial-assist expansion - `media_analysis` now reuses
existing project reports when cache signatures satisfy the requested analysis
layers, can review timeline marker contact sheets with chat-context vision, and
`timeline` adds editor-facing helpers for story-spine reports, declarative
variant creation, bulk item property writes, multi-item look application,
thumbnail contact sheets, marker thumbnail review, and audio mix capability
fallback reporting.

**New `media_analysis` compound tool**: added `capabilities`,
`install_guidance`, `resolve_output_root`, `plan`, `analyze_file`,
`analyze_clip`, `analyze_bin`, `analyze_project`, `review_timeline_markers`,
`summarize`, `get_report`, and `cleanup_artifacts`.

**MCP prompts and visual review**: the compound server now registers
`davinci_resolve_workflow` and `analyze_media` prompts. `analyze_media` defaults
to chat-context visual analysis when MCP sampling is available, while
`timeline_markers.get_thumbnail_image` returns current Resolve frames as MCP
image content without writing a file.

**Source-safe editorial helpers**: timeline actions now support
`story_spine_report`, `create_variant_from_ranges`, `bulk_set_item_properties`,
`apply_look_to_items`, `thumbnail_contact_sheet`, `marker_thumbnail_review`, and
`audio_mix_capability_report`. Positioned timeline appends normalize
`record_frame` relative to the active timeline start by default, matching
Resolve's common 01:00:00:00 start-frame behavior.

**Documentation reorganization**: moved durable references into `docs/guides`,
`docs/kernels`, `docs/authoring`, `docs/notes`, `docs/process`, and
`docs/reference`, added a compact docs index, and kept local gameplans/scratch
artifacts ignored.

**Privacy cleanup**: sanitized tracked live-test fixtures and scripts that had
workstation-specific source-media paths while leaving public project contact
information intact.

**Validation**: static/import checks, API parity audit, and 141 focused unit
tests passed. Live validated against DaVinci Resolve Studio 20.3.2.9 with a
disposable `_mcp_media_analysis_v2170_probe` project and a generated synthetic
clip only. The run covered source-adjacent output-root rejection,
`media_analysis.plan`, session-only `analyze_file`, `story_spine_report`,
`audio_mix_capability_report`, raw thumbnail retrieval, `thumbnail_contact_sheet`,
and `review_timeline_markers`; the disposable project and temp artifacts were
cleaned up.

## v2.16.0

Extension Authoring kernel expansion - adding lifecycle-aware Fuse, DCTL, ACES
DCTL, and Resolve-page script probes around the existing authoring tools.

**New `script_plugin` extension actions**: added `extension_capabilities`,
`probe_fuse_lifecycle`, `probe_dctl_lifecycle`, `probe_script_lifecycle`,
`safe_install_extension`, `safe_remove_extension`,
`refresh_or_restart_required`, and `extension_boundary_report`.

**Lifecycle and cleanup guards**: safe extension installs require `_mcp_` names
and MCP markers by default. Safe removal refuses to delete unmarked files unless
explicitly overridden. The kernel classifies Fuse and ACES DCTL installs as
restart-required, regular LUT DCTLs as `refresh_luts`-driven, and Resolve-page
scripts as menu-refresh-only.

**Documented support map**: added
[`docs/kernels/extension-authoring-kernel.md`](docs/kernels/extension-authoring-kernel.md) and
updated the Fuse/DCTL and script authoring docs with live lifecycle findings.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
MCP-marked `_mcp_` extension files only. Final probe result: 14 supported, 1
partially supported installed-Lua-script execution boundary, 1 intentional
unsupported unmarked-source guard, and 0 errors. All generated extension files
and the disposable project were cleaned up.

## v2.15.0

Project / Database / Archive kernel expansion - adding disposable project
lifecycle guards, settings snapshots and write/restore probes, database switch
dry-runs, preset lifecycle probing, archive safety validation, and project
boundary reporting.

**New `project_manager` lifecycle actions**: added `project_capabilities`,
`probe_project_lifecycle`, `probe_project_settings`, `safe_project_create`,
`safe_project_export`, `safe_project_import`, `safe_project_archive`,
`safe_project_restore`, `safe_project_delete`, `safe_set_project_settings`,
`project_settings_snapshot`, `database_capabilities`,
`safe_set_current_database`, `preset_lifecycle_probe`, and
`project_boundary_report`.

**Operational guardrails**: safe project mutation defaults to `_mcp_`
disposable names and temp paths. Database switching dry-runs by default because
Resolve closes open projects when changing databases. Archive source media,
render cache, and proxy media flags are rejected unless explicitly opted in.

**Documented support map**: added
[`docs/kernels/project-lifecycle-kernel.md`](docs/kernels/project-lifecycle-kernel.md) with
project CRUD, DRP import/export, archive/restore, folder, settings, database,
layout preset, render preset, page, keyframe, and cloud-infrastructure
boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
disposable `_mcp_` projects only. Final probe result: 35 supported, 5 partially
supported lifecycle/archive/keyframe/render-preset boundaries, 1 intentional
unsupported archive media-flag guard, 1 not-applicable archive restore boundary,
and 0 errors. Disposable projects, layout presets, and temp work files were
cleaned up.

## v2.14.0

Audio / Fairlight kernel expansion - adding audio track/item probes, source
audio mapping reports, guarded audio property writes, voice isolation
capabilities, auto-sync planning, transcription/subtitle probes, and Fairlight
boundary reporting.

**New `timeline` audio actions**: added `audio_capabilities`,
`probe_audio_track`, `probe_audio_item`, `safe_set_audio_properties`,
`voice_isolation_capabilities`, `audio_mapping_report`, `safe_auto_sync_audio`,
`transcription_capabilities`, `subtitle_generation_probe`, and
`fairlight_boundary_report`.

**Audio state and mapping**: the kernel snapshots audio track state, timeline
item audio properties, source audio channel mapping, MediaPoolItem audio
mapping, and track/item voice isolation availability.

**Guarded AI and sync surfaces**: auto-sync dry-runs by default and normalizes
Resolve audio-sync constants. Subtitle generation dry-runs unless
`allow_generate=True`; transcription capability reporting is read-only by
default.

**Documented support map**: added
[`docs/kernels/audio-fairlight-kernel.md`](docs/kernels/audio-fairlight-kernel.md) with
track/item state, voice isolation, mapping, transcription, subtitle, auto-sync,
and Fairlight insertion boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
generated synthetic video and audio-only media. Final probe result: 13
supported, 3 partially supported audio property/auto-sync/audio-insert
boundaries, and 0 errors. The disposable project and generated media were
cleaned up.

## v2.13.0

Timeline Conform / Interchange kernel expansion - adding timeline structure
snapshots, source range reporting, gap/overlap detection, guarded interchange
export/import, round-trip comparison, missing-media detection, and relink
planning around Resolve's public timeline APIs.

**New `timeline` conform actions**: added `conform_capabilities`,
`probe_timeline_structure`, `detect_gaps_overlaps`, `source_range_report`,
`export_timeline_checked`, `import_timeline_checked`, `compare_timelines`,
`probe_interchange_roundtrip`, `detect_missing_media`, `build_relink_plan`,
and `conform_boundary_report`.

**Interchange probing**: export aliases now cover FCPXML, DRT, EDL, AAF, OTIO,
FCP 7 XML, and EDL subtype variants. FCPXML directory-style exports are
normalized with a `primary_file` path for import.

**Conform analysis**: the kernel reports track/item structure, same-track gaps
and overlaps, source ranges with handles, missing/offline media, and relink
candidates without mutating user source media.

**Documented support map**: added
[`docs/kernels/timeline-conform-interchange-kernel.md`](docs/kernels/timeline-conform-interchange-kernel.md)
with export, round-trip, missing-media, relink planning, and format-survival
boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic gapped timeline. Final probe result: 17 supported, 1
partially supported FCPXML round-trip survivability boundary, and 0 errors. The
disposable project, generated media, and imported round-trip timelines were
cleaned up.

## v2.12.0

Fusion Composition kernel expansion - adding safe Fusion graph inspection,
tool creation, input writes, connection validation, scoped bulk writes, and
boundary reporting around Resolve's public Fusion comp API.

**New `fusion_comp` kernel actions**: added `fusion_graph_capabilities`,
`probe_fusion_comp`, `probe_fusion_tool`, `safe_add_tool`, `safe_set_inputs`,
`safe_connect_tools`, and `fusion_boundary_report`.

**Timeline item graph automation**: the kernel can target timeline item Fusion
comps via `timeline_item`, `clip_id`, or `timeline_item_id`, then add tools,
write inputs with readback, inspect ports, connect tools, set frame ranges, and
export the comp through `timeline_item_fusion`.

**Scoped bulk writes**: `bulk_set_inputs` remains the safe batch path for
applying input updates across multiple explicitly scoped timeline-item comps,
so agent workflows do not accidentally mutate the active Fusion page comp.

**Documented support map**: added
[`docs/kernels/fusion-composition-kernel.md`](docs/kernels/fusion-composition-kernel.md) with
tool availability, input/output, scope, comp export, and page-state boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic timeline item Fusion comp. Final probe result: 18
supported, 0 unsupported, 0 partially supported, and 0 errors. The disposable
project, generated media, and exported temp comp were cleaned up.

## v2.11.0

Color / Grade kernel expansion - adding safe grade inspection, CDL validation,
node graph probing, grade copy, LUT export, version restore, Gallery, and color
group boundary reporting around Resolve's public Color API.

**New `timeline_item_color` kernel actions**: added `grade_capabilities`,
`probe_grade_item`, `probe_node_graph`, `safe_set_cdl`, `safe_copy_grade`,
`safe_apply_drx`, `safe_export_lut`, `grade_version_snapshot`,
`grade_version_restore`, `color_group_capabilities`, `gallery_capabilities`,
and `grade_boundary_report`.

**Grade and graph probing**: the kernel snapshots item grade versions, graph
availability, node counts, node LUT/cache/label/tools metadata, color-group
assignment, and cache state without guessing at opaque node internals.

**Safe mutation helpers**: CDL payloads are validated and normalized before
`SetCDL`; grade copy resolves target timeline item IDs first; LUT export is
guarded to temp paths by default; DRX apply requires an existing DRX path and
documents that it replaces the target graph.

**Color groups and Gallery**: color-group capability probes cover project
groups plus pre/post graph availability. Gallery capability probes report album
state and classify still export as UI/page dependent when Resolve returns false.

**Documented support map**: added
[`docs/kernels/color-grade-kernel.md`](docs/kernels/color-grade-kernel.md) with graph, LUT, DRX,
version, Gallery, color-group, and AI-tool boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic color-bar timeline. Final probe result: 25 supported, 2
version/page-dependent Gallery/DRX export boundaries, 1 not-applicable DRX apply
path because no DRX could be produced in that run, and 0 errors. The disposable
project, generated media, and temp LUT exports were cleaned up.

## v2.10.0

Review Annotation kernel expansion - adding a unified marker, custom data,
flag, clip color, copy/move, and review report layer across timeline, timeline
item, and media pool item scopes.

**New `timeline_markers` kernel actions**: added
`annotation_capabilities`, `probe_annotations`, `normalize_marker_payload`,
`copy_annotations`, `move_annotations`, `sync_marker_custom_data`,
`clear_annotations_by_scope`, `export_review_report`, and
`annotation_boundary_report`.

**Unified annotation scopes**: the new helpers normalize marker payloads,
frame/timecode aliases, custom data aliases, and marker colors before touching
Resolve. `probe_annotations` snapshots timeline, current timeline item, and
media pool item annotations when the current playhead can resolve them.

**Review metadata copying**: `copy_annotations` and `move_annotations` can copy
marker payloads between timeline, timeline item, and media pool item scopes
using direct frame numbers. When supported by both scopes, flags and clip color
can travel with the marker payload.

**Read-only review reports**: `export_review_report` and
`annotation_boundary_report` produce agent-friendly summaries without mutating
media or projects.

**Documented support map**: added
[`docs/kernels/review-annotation-kernel.md`](docs/kernels/review-annotation-kernel.md) with the
scope matrix, field support, frame-space caveats, and live probe findings.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
generated synthetic timeline. Final probe result: 44 supported, 1 expected
unsupported invalid-color boundary, and 0 errors. The disposable project and
generated media were cleaned up after report generation.

## v2.9.0

Render / Deliver kernel expansion — adding a safer render planning, settings,
format/codec compatibility, queue lifecycle, and Quick Export boundary layer.

**New `render` kernel actions**: added `render_capabilities`,
`probe_render_matrix`, `probe_render_settings`, `validate_render_settings`,
`safe_set_render_settings`, `prepare_render_job`,
`render_job_lifecycle_probe`, `quick_export_capabilities`,
`safe_quick_export`, and `export_render_boundary_report`.

**Render compatibility matrix**: `probe_render_matrix` walks available render
formats, codecs, and resolutions so agents can choose what this specific
Resolve install can actually deliver.

**Job-safe rendering helpers**: render settings validation now checks documented
setting keys, value types, frame ranges, and temp-target requirements.
`prepare_render_job` creates queued jobs without starting renders, while
`render_job_lifecycle_probe` validates add/status/delete behavior safely.

**Guarded Quick Export**: `safe_quick_export` validates temp targets, forces
`EnableUpload=False`, and requires `allow_render=True` before it can actually
start Quick Export.

**Documented support map**: added
[`docs/kernels/render-deliver-kernel.md`](docs/kernels/render-deliver-kernel.md) with
format/codec, settings, render job, and Quick Export boundaries.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with a
two-second generated synthetic timeline. Final probe result: 23 supported, 1
version/page-dependent `GetRenderSettings` readback boundary, and 0 errors. The
probe rendered one tiny synthetic output, then cleaned up the disposable project
and generated files.

## v2.8.0

Media Pool / Ingest kernel expansion — applying the timeline edit kernel probe
pattern to import, organization, metadata, annotation, and media-link boundary
workflows while preserving source media integrity.

**New `media_pool` kernel actions**: added `ingest_capabilities`,
`probe_media_pool`, `probe_ingest_item`, `safe_import_media`,
`safe_import_sequence`, `safe_import_folder`, `organize_clips`,
`copy_metadata`, `normalize_metadata`, `probe_clip_properties`,
`safe_relink`, `safe_unlink`, `link_proxy_checked`,
`link_full_resolution_checked`, `set_clip_marks`, `clear_clip_marks`,
`copy_clip_annotations`, and `media_pool_boundary_report`.

**Safe ingest and organization**: safe import helpers validate paths, sequence
patterns, frame ranges, and optional target folders before calling Resolve.
`organize_clips` can move clips to existing folders or create missing folder
paths explicitly. All helpers support dry-run where useful for planning.

**Metadata and annotation workflows**: bulk metadata normalization, metadata
copying, clip property probes, mark in/out bulk operations, and annotation copy
now have agent-friendly wrappers over Resolve's lower-level clip APIs.

**Documented support map**: added
[`docs/kernels/media-pool-ingest-kernel.md`](docs/kernels/media-pool-ingest-kernel.md) so
agents and users can inspect the supported, partial, unsupported, and
version/page-dependent ingest boundaries directly.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
generated synthetic video, audio, still, image sequence, and non-media
fixtures. Final probe result: 56 supported, 1 expected unsupported non-media
text import, and 0 errors. The disposable project and generated media were
cleaned up after report generation.

## v2.7.0

Timeline edit kernel expansion — turning the v2.6.0 duplicate helper into a
broader, live-probed edit layer for clip duplication, linked audio, range edits,
state copying, and capability reporting while preserving source media integrity.

**Expanded `timeline.duplicate_clips` action**: duplication now supports
`selected=True`, explicit `record_frame`, `track_offset`, and placement modes
`same_time`, `offset`, `at_playhead`, `track_above`, `after_source`, and
`next_gap`. `include_linked=True` duplicates linked audio and restores the
video/audio link state. `copy_clips` is an alias for duplication, and
`move_clips` duplicates successfully first before deleting the original source
items.

**Timeline range operations**: added `copy_range`, `duplicate_range`,
`overwrite_range`, and `lift_range`. Range copies rebuild exact source segments
with positioned append operations. `overwrite_range` deletes whole destination
overlaps before appending. `lift_range` safely deletes whole matching items and
requires explicit `allow_partial_item_delete=True` for whole-item deletion when
a requested range only partially overlaps an item.

**State copying groups**: duplicate/copy operations can now copy transform,
crop, composite, audio, retime, dynamic zoom, scaling, stabilization, clip
color, markers, flags, enabled state, cache, voice isolation, Fusion comps,
grades, takes, and keyframes where Resolve exposes readable/writable item APIs.
Transition cloning is accepted as a requested group but reported unsupported
because Resolve's public scripting API does not expose transition cloning.

**Capability and boundary probes**: added `timeline.edit_kernel_capabilities`
for a maintained support map and `timeline.probe_edit_kernel_item` for read-only
inspection of item methods, properties, keyframes, and linked items. Added
`src/utils/timeline_kernel_live_probe.py` plus offline report/parser tests so
future work can expand the technical boundary without guessing.

**Documented limits**: added
[`docs/kernels/timeline-edit-kernel.md`](docs/kernels/timeline-edit-kernel.md), which records
the supported, partially supported, unsupported, and version/page-dependent
surfaces. Known public-API boundaries include transition cloning, direct
razor/split edits, true partial lifts, source-less item append cloning, and
opaque speed-ramp internals.

**Validation**: live validated against DaVinci Resolve Studio 20.3.2.9 with
disposable projects and synthetic media. Final exhaustive probe result:
255 supported, 4 partially supported, 138 unsupported, 4 version/page
dependent, and 0 errors. Static/unit checks include `tests/test_import.py`,
`scripts/audit_api_parity.py`, `git diff --check`, the focused timeline/helper
unit suite, and the full live duplicate/range/probe harness.

## v2.6.0

Timeline clip duplication — adding an Alt-drag-style helper for duplicating
existing video timeline items without creating proxy media, renders, or source
derivatives.

**New `timeline.duplicate_clips` action**: `timeline(action="duplicate_clips")`
duplicates video timeline items by re-appending the same Media Pool item with
the same source trim via `MediaPool.AppendToTimeline([{clipInfo}])`. It accepts
timeline item IDs from `timeline.get_items`, an optional
`target_track_index`, and `record_frame_offset`; each result reports per-clip
success and the duplicated timeline item ID when Resolve exposes or recovers it.

**Resolve append-result hardening**: duplicate results now tolerate thin
`AppendToTimeline` return objects that lack readable `GetUniqueId()` or
`GetName()` methods, then scan the target video track to recover the real item
handle. Bad inputs now return clean per-clip errors for non-video items,
invalid offsets, and nonexistent target tracks.

**Live-tested source trim semantics**: validation against Resolve Studio
20.3.2.9 confirmed that positioned `AppendToTimeline` treats `endFrame` as an
exclusive source boundary in this workflow. `duplicate_clips` now uses
`TimelineItem.GetDuration()` and `GetSourceStartFrame()` where available, so
the duplicate preserves the original duration and source start.

**Validation**: added `tests/live_duplicate_clips_validation.py`, which creates
a disposable project, imports synthetic media, places a trimmed clip, duplicates
it to another track, verifies record frame/duration/source trim/media identity,
checks the invalid-track error path, and deletes the project. Focused unit
coverage now includes anonymous append objects, source-start preference,
video-only `mediaType`, and target-track ID recovery.

## v2.5.0

Three new compound tools for *authoring and conversationally executing* Resolve extensions: Fusion Fuse plugins, DCTL color transforms, and Resolve-page Lua/Python scripts. Plus a documentation pass on six adjacent Resolve extension systems.

**New `fuse_plugin` tool**: generate, install, list, read, remove, and validate Fusion Fuse plugins (`.fuse`). **18 template kinds** spanning color (`color_matrix`, `per_pixel`, `channel_op`), geometric (`transform`, `spatial_warp`), text/shapes (`text_overlay`, `shape_generator`), source/temporal (`source_generator`, `time_displace`), filters (`builtin_blur`, `builtin_resize`, `variable_blur` SAT-based), modifiers (`modifier`, `point_modifier`), display shaders (`view_lut`, `dctl_kernel`), and reference (`controls_demo`, `notifychanged_demo`). Each generator produces ready-to-install Lua (or Lua + GLSL / Lua + DCTL) source that passes `luac -p` syntax checks across all option branches. **Live-verified in DaVinci Resolve Studio 20.3.2.9**: generated Fuses register on Resolve restart and instantiate via `comp:AddTool`; the `text_overlay` template was confirmed rendering glyphs into the viewer. The `view_lut` template supports `float`, `vec2`, `vec3_rgb`, and `vec4_rgba` shader parameter types. Includes a path-bug fix: corrected install path on macOS to `Fusion/Fuses/` (the SDK doc lists `Support/Fusion/Fuses/`, but Fusion's own `MapPath("Fuses:")` returns the path without `/Support/`).

**New `dctl` tool**: generate, install, list, read, remove, and validate DCTL color-transform files plus ACES IDT/ODT transforms. **8 template kinds** — `transform`, `transform_alpha` (Resolve 19.1+ alpha modes), `transition` (with `TRANSITION_PROGRESS`), `matrix` (3x3 color matrix), `kernel` (TODO stub), `lut_apply` (wraps an external `.cube` LUT via `DEFINE_LUT`/`APPLY_LUT`), `aces_idt`, `aces_odt`. UI-parameter syntax covers all six DCTL UI types (slider float/int, value box, checkbox, combo, color picker) with optional tooltips. Per-template `suggested_category` so callers know whether to install to the regular LUT directory or the separate ACES Transforms tree. Subdir support with strict path-traversal guards. Validator catches missing entry points, brace imbalance, and float literals missing the required `f` suffix. Regular DCTLs pick up via `project_settings(action='refresh_luts')`; ACES DCTLs require a Resolve restart.

**New `script_plugin` tool — conversational Lua/Python execution**: generate, install, and **execute** Resolve-page scripts that appear in the Workspace → Scripts menu. Two template kinds: `scaffold` (minimal stub) and `media_rules` (a comprehensive rules-and-variables DSL with sources, extract patterns, transforms, targets, actions, conditions, dry-run mode, external CSV/JSON data with exact/regex/fuzzy matching, and per-rule metadata — ~22k chars Lua engine and ~18k chars Python engine, both first-class). **Two new actions close the conversational loop**: `run_inline(source, language)` runs an ad-hoc Lua/Python snippet inside Resolve and streams stdout + return value back into the conversation; `execute(name, category, language)` runs an installed script the same way. Python uses subprocess with full stdout/stderr capture; Lua uses `fusion.RunScript()` against a temp file with completion-sentinel polling and `app:SetData()` bridge for return values (Resolve 20.x's `fusion.Execute()` is a no-op from the Python bridge — that quirk is encoded in the implementation). **Live-verified end-to-end** on Resolve Studio 20.3.2.9: Python `run_inline` returned project list and walked media pool; Lua `run_inline` enumerated `MapPath` symbols with stdout AND return value captured.

**`list_templates` action** on all three new tools enumerates available kinds.

**Resolve developer-package reference consolidation**: extension-system notes
were consolidated back into README/SKILL guidance, while dedicated authoring
docs remain in `docs/authoring/fuse-dctl-authoring.md` and
`docs/authoring/script-plugin-authoring.md`.

**Test coverage**: 185 offline tests across 7 modules (`test_fuse_dctl_authoring.py` and `test_script_plugin.py` both new in this release), all green in <2s. Includes hermetic round-trip tests with mocked install paths, DSL-coverage tests confirming every documented source/action/target/transform is in both Lua and Python engines, and Python subprocess execution tests with real captured stdout/stderr.

**Compound tool count: 27 → 30**. Granular tool count unchanged at 328.

## v2.4.1

Release process hardening — documenting the version bump, validation, tag, and GitHub Release checklist.

**Release checklist documented**: added `docs/process/release-process.md` with semantic version guidance, required version surfaces, validation requirements, tag/release commands, and release-note template.

**Live-test requirement clarified**: Resolve behavior changes must be validated live with disposable projects and synthetic media before release. Docs-only releases do not require a live Resolve run when no behavior changed.

## v2.4.0

Timeline source range extraction — adding a compound workflow helper for frame-pull and conform preparation.

**New `timeline.extract_source_frame_ranges` action**: `timeline(action="extract_source_frame_ranges")` scans every video clip on the current timeline and returns per-source frame ranges, clip occurrences, timeline positions, source offsets, applied handles, and timeline item IDs. Clip names prefer the basename from the Media Pool `File Path`, with audio extensions skipped by default.

**Handle-aware source ranges**: fixed handles default to 24 frames. Passing `handles=0` switches to gap-only auto handles, using neighboring timeline gaps up to `gap_max` frames. Returned `source_range_final` and `frame_ranges` endpoints are inclusive/inclusive for downstream extraction tools.

**Inclusive endpoint fix**: live validation caught and fixed the off-by-one where Resolve's exclusive source boundary was being returned as an inclusive final frame. A 48-frame synthetic clip with `handles=0` now returns `source_used_inclusive_end=47` and `source_range_final=[0, 47]`.

**Live Resolve validation**: verified against DaVinci Resolve Studio 20.3.2.9 in a disposable project with synthetic media. Added unit coverage in `tests/test_extract_source_frame_ranges.py` for zero-handle and fixed-handle ranges.

## v2.3.4

Marker API hardening for Issue #34 — making the compound marker tools match the parameter shapes agents and users naturally send.

**Marker parameter aliases fixed**: `timeline_markers`, `media_pool_item_markers`, and `timeline_item_markers` now accept `frame`, `frame_id`, and `frameId` consistently for add/get/update/delete operations. Marker lookup and delete paths also accept `customData` as an alias for `custom_data`.

**Timeline marker ergonomics improved**: `timeline_markers(action="add")` can now add at the current playhead when no frame/timecode is provided, and also accepts explicit `timecode` input. Optional marker fields now have sensible defaults (`color="Blue"`, `name` from note or `"Marker"`, `note=""`, `duration=1`).

**Resolve overload fallback**: marker creation first uses the documented six-argument `AddMarker(..., customData)` call, and falls back to the five-argument form when `customData` is empty and a Resolve build rejects the optional parameter.

**Live Resolve validation**: verified against DaVinci Resolve Studio 20.3.2.9 with `tests/live_marker_validation.py`. The harness creates a disposable project, imports synthetic media, inserts a visible timeline generator, and live-tests timeline, media-pool-item, and timeline-item marker add/get/update/delete alias paths. A `--keep-open` mode leaves a marked timeline open for visual inspection.

## v2.3.3

Granular layer hardening — closing exposure gaps and dropped-dict-key bugs surfaced by an exhaustive parity audit of every documented Resolve scripting method against both server layers.

**Cloud project helper rewritten** (Critical): `src/utils/cloud_operations.py` was calling `pm.CreateCloudProject(project_name, folder_path)` with positional arguments — but the documented Resolve API signature is `CreateCloudProject({cloudSettings})`, a single dict. Same bug affected `ImportCloudProject` and `RestoreCloudProject`. Helper now builds proper `{cloudSettings}` dicts and exposes all 5 documented keys (`PROJECT_NAME`, `PROJECT_MEDIA_PATH`, `IS_COLLAB`, `SYNC_MODE`, `IS_CAMERA_ACCESS`) per docs lines 576-594. Granular wrappers (`create_cloud_project_tool`, `import_cloud_project_tool`, `restore_cloud_project_tool`) updated to expose the full settings surface; `load_cloud_project_tool` added (was missing entirely from granular).

**Silent-drop bugs fixed** (Critical):
- **`render_with_quick_export()` (granular)** previously dropped the documented `{param_dict}` (TargetDir, CustomName, VideoQuality, EnableUpload). Now forwards all four keys per docs line 179.
- **`timeline_create_compound_clip()` (granular)** previously dropped the documented `{clipInfo}` dict (`name`, `startTimecode`). Now exposes both keys per docs line 369.

**Missing granular tools added**:
- **`append_to_timeline`** — both simple `clip_ids` form and positioned `clip_infos` form (`MediaPool.AppendToTimeline` was completely absent from granular layer; only compound had it).
- **`auto_sync_audio`** — with proper `{audioSyncSettings}` dict mapping per docs lines 600-614 (`sync_mode`, `channel_number` with `'automatic'`/`'mix'` aliases, `retain_embedded_audio`, `retain_video_metadata`).
- **`load_cloud_project_tool`** — was missing entirely; compound had it.
- **`rename_color_group`** — wraps `ColorGroup.SetName` (compound had it via `color_group(action="set_name")` but no granular tool).

**Removed 4 undocumented cloud method wrappers**:
- `get_cloud_projects` resource → `GetCloudProjectList` not in API docs
- `export_project_to_cloud_tool` → `ExportToCloud`/`ExportProjectToCloud` not in API docs
- `add_user_to_cloud_project_tool` → `AddUserToCloudProject` not in API docs
- `remove_user_from_cloud_project_tool` → `RemoveUserFromCloudProject` not in API docs

**Removed 9 legacy granular gallery tools** that wrapped undocumented or renamed methods (`gallery.GetAlbums()`, `gallery.CreateAlbum()`, `still.GetTimecode()`, `still.IsGrabbed()`, etc.). The proper documented Gallery and GalleryStillAlbum wrappers (lines 743+ of the previous gallery.py — all 14 of those, e.g. `get_gallery_still_albums`, `create_gallery_still_album`, `import_stills_to_album`, `export_stills_from_album`, `get_album_stills`, `set_still_label`) cover the documented API surface and remain. Removed: `get_color_presets`, `save_color_preset`, `apply_color_preset`, `delete_color_preset`, `create_color_preset_album`, `delete_color_preset_album`, `export_lut`, `get_lut_formats`, `export_all_powergrade_luts`.

**Removed 2 granular project optimized-media tools** that wrapped undocumented Resolve methods (`Project.GenerateOptimizedMedia`, `Project.DeleteOptimizedMedia`, `MediaPool.SetClipSelection` — none in API docs). Removed: `generate_optimized_media`, `delete_optimized_media`. Use the Resolve UI for optimized-media generation; `set_optimized_media_mode` (which uses the documented `Project.SetSetting("OptimizedMediaMode", ...)`) is preserved.

**Deprecated method call fixed**: `timeline(action="get_items_in_track")` was calling the deprecated `tl.GetItemsInTrack()` form (docs line 989, marked deprecated) instead of the supported `tl.GetItemListInTrack()` (line 350). Every other call site already used the correct form.

**New: API parity CI guard** at `scripts/audit_api_parity.py`. Parses `docs/reference/resolve_scripting_api.txt` and verifies (1) no `from api.X` broken imports remain, (2) every documented Resolve method appears somewhere in `src/`, (3) wrappers calling undocumented methods are flagged for review. Includes an allowlist for legitimate undocumented-but-real Resolve API surface (Fusion compositing API, UIManager methods like `OpenProjectSettings`/`LoadUILayout`/`SaveUILayout`, internal type-discrimination helpers like `TimelineItem.GetType`/`GetMediaType`). Run with `python3 scripts/audit_api_parity.py` — currently passes all three checks cleanly.

**Tool count: 328 granular tools** (was 354 before v2.3.2; net change since v2.3.1 is −26 broken/duplicate/undocumented tools removed and +4 missing tools added). 20 new unit tests against Resolve stubs covering the cloud settings builder, audio sync settings builder, and AppendToTimeline clipInfo builder. All 41 tests pass without a live Resolve connection.

**Live disposable Resolve validation**: every new and changed v2.3.3 granular tool was exercised against DaVinci Resolve Studio 20.3.2.9 in a disposable project with synthetic temp media via `tests/live_v233_validation.py`. 10/10 checks passed: `append_to_timeline` (simple + positioned + failure path), `auto_sync_audio` (settings dict + invalid input rejection), `import_media` image-sequence form, `timeline_create_compound_clip` (info dict forwarded — compound clip created with explicit name), `rename_color_group` (renamed a real color group), `render_with_quick_export` (params dict forwarded — Resolve's structured `{JobStatus, Error}` response confirms the dict reached it), and the compound-side `GetItemListInTrack` deprecated→supported fix.

## v2.3.2

API parity sweep — closing documented overloads and dropped parameters that the v2.3.1 audit surfaced.

- **Positioned `CreateTimelineFromClips` via `clip_infos`** — `media_pool(action="create_timeline_from_clips", params={"clip_infos": [...]})` and the granular `create_timeline_from_clips(clip_infos=[...])` now expose the documented `MediaPool.CreateTimelineFromClips(name, [{clipInfo}, ...])` overload (4 keys: `mediaPoolItem`, `startFrame`, `endFrame`, `recordFrame`)
- **Image-sequence `ImportMedia` via `clip_infos`** — both layers now expose `MediaPool.ImportMedia([{FilePath, StartIndex, EndIndex}, ...])` for DPX/EXR/etc. sequence imports. PascalCase keys preserved per Resolve docs
- **Positioned `AddItemListToMediaPool` via `item_infos`** — `media_storage(action="import_to_pool", params={"item_infos": [{media, startFrame, endFrame}, ...]})` and granular `add_items_to_media_pool_from_storage(item_infos=[...])` now expose the documented `MediaStorage.AddItemListToMediaPool([{itemInfo}, ...])` overload
- **`Timeline.AddTrack` dict form** — replaced the legacy bare-string `sub_type` argument with the documented `newTrackOptions` dict (`audio_type`, `index`). Granular `timeline_add_track(track_type, audio_type=, index=)` and compound `timeline(action="add_track", params={"track_type", "options": {audio_type, index}})`
- **`CreateSubtitlesFromAudio` actually wired up** — granular `timeline_create_subtitles_from_audio` previously advertised `language` and `preset` parameters then silently dropped them. Now maps user strings (e.g. `"korean"`, `"netflix"`, `"double"`) to `resolve.AUTO_CAPTION_*` constants per docs lines 720-761, and exposes the missing `chars_per_line`, `line_break`, `gap` keys
- **Granular `import_media` no longer crashes** — the granular `import_media` tool was importing from a deleted `api.media_operations` module and would throw `ModuleNotFoundError` on first call. Rewritten to call `MediaPool.ImportMedia` directly and to share the new `clip_infos` overload
- **`SetRenderSettings` docstring completeness** — granular `set_render_settings` now documents all 27 keys per docs lines 765-799 (previously omitted `EncodingProfile`, `MultiPassEncode`, `AlphaMode`, `NetworkOptimization`, `PixelAspectRatio`, `ClipStartFrame`, `TimelineStartTimecode`, `ReplaceExistingFilesInPlace`)
- **Removed 18 broken granular tools (+ 7 broken resources)** that imported from a deleted `api.*` namespace and would crash with `ModuleNotFoundError` on first call. All 25 had working equivalents elsewhere or wrapped undocumented Resolve methods. Granular tool count is now **336** (was 354). Migration map for any caller that was hitting them:
  - `delete_media` → `media_pool(action="delete_clips")`
  - `move_media_to_bin` → `media_pool(action="move_clips")`
  - `auto_sync_audio` (granular tool) → `media_pool(action="auto_sync_audio")`
  - `unlink_clips` → `media_pool(action="unlink")`
  - `relink_clips` → `media_pool(action="relink")`
  - `create_bin` → `media_pool(action="add_subfolder")`
  - `list_media_pool_bins` (resource) → `folder(action="get_subfolders")`
  - `get_media_pool_bin_contents` (resource) → `folder(action="get_clips")`
  - `get_timeline_tracks` (resource) → `timeline(action="get_track_count")` + `timeline(action="get_items_in_track")`
  - `create_empty_timeline` → `media_pool(action="create_timeline")`
  - `delete_timeline` → `media_pool(action="delete_timelines")`
  - `add_marker` (granular timeline tool) → `timeline_markers(action="add")`
  - `add_clip_to_timeline` → `media_pool(action="append_to_timeline")`
  - `apply_lut` (granular graph tool) → `graph(action="set_lut")`
  - `copy_grade` → `timeline_item_color(action="copy_grades")`
  - `get_render_presets` (resource) → `render(action="list_presets")`
  - `add_to_render_queue` → `render(action="add_job")`
  - `start_render` (granular project tool) → `render(action="start")`
  - `get_render_queue_status` (resource) → `render(action="list_jobs")` + `render(action="get_job_status")`
  - `clear_render_queue` (granular project tool) → `render(action="delete_all_jobs")`
  - `create_sub_clip`, `get_current_color_node`, `get_color_wheel_params`, `set_color_wheel_param`, `add_node`: removed — these wrapped undocumented Resolve methods that were never exposed in the official scripting API. No replacement exists; use the Resolve UI for now.

## v2.3.1

- **Positioned `AppendToTimeline` via `clip_infos`** — `media_pool(action="append_to_timeline", params={"clip_infos": [...]})` now exposes the documented `MediaPool.AppendToTimeline([{clipInfo}, ...])` overload, accepting per-entry `clip_id`/`media_pool_item_id`, `start_frame`, `end_frame`, `record_frame`, `track_index`, and optional `media_type`. Each appended item returns its `timeline_item_id` for follow-up Fusion ops
- **Positioned append failure reporting** — the same call now returns `{"error": ...}` when Resolve fails to produce valid timeline items, including falsey `AppendToTimeline()` results and returned item handles without a timeline item id
- **Live disposable Resolve validation** — verified the fix against DaVinci Resolve Studio 20.3.2 with synthetic temp media in a disposable project: valid `clip_infos` append returned `success`, `count=1`, and `timeline_item_id`; invalid `clip_infos` calls returned errors

## v2.3.0

- **Resolve 20.2.2 API sync** — added the 12 scripting methods introduced across Resolve 20.0-20.2.2, with compatibility guards so older Resolve builds return clear "requires Resolve 20.x" errors instead of crashing
- **Resolve 20 live validation** — revalidated the new API surface against DaVinci Resolve Studio 20.3.2, bringing live-tested coverage to 331/336 methods (98.5%)
- **Official scripting docs refreshed** — `docs/reference/resolve_scripting_api.txt` now tracks the Resolve 20 scripting README bundled with the installed 20.3.2 developer package
- **AI skill reference updated** — merged PR #30's `docs/SKILL.md` and updated it for the Resolve 20 method count, granular server, version guards, and source media integrity guidance
- **Stale Resolve handle recovery** — both server modes now validate cached Resolve handles and reconnect cleanly after Resolve restarts or Project Manager transitions

## v2.2.0

- **Granular server modularized internally** — `src/resolve_mcp_server.py` is now a thin entrypoint, with the granular implementation split across `src/granular/resolve_control.py`, `project.py`, `timeline.py`, `timeline_item.py`, `media_pool.py`, `folder.py`, `media_pool_item.py`, `gallery.py`, `graph.py`, and `media_storage.py`
- **Installer now emits env blocks for every generated stdio config** — standard `.mcp.json`, VS Code `.vscode/mcp.json`, Zed `context_servers`, and manual snippets now include `RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB`, and `PYTHONPATH`
- **Windows Resolve 20.3 hardening** — on Windows, the installer also emits `PYTHONHOME` derived from the selected interpreter's base install so Resolve binds against the intended Python instead of a newer globally registered one
- **Windows stdio transport hardening** — server entrypoints now run FastMCP through strict LF-only stdio wrappers to avoid client disconnects caused by platform newline translation in Windows pipes
- **`set_cdl` accepts arrays cleanly** — both compound and granular servers now normalize JSON array, tuple, and numeric CDL values into Resolve's required string form like `"1.0 1.0 1.0"`
- **`fusion_comp` can target timeline item comps** — node graph actions can now operate on a clip's Fusion comp via `clip_id`, `timeline_item_id`, or `timeline_item`, and `bulk_set_inputs` applies scoped input changes across multiple timeline comps
- **`python src/server.py --full` now stays intact** — the compound entrypoint now correctly launches the granular server instead of importing it and exiting

## v2.1.0

- **New `fusion_comp` tool** — 20-action tool exposing the full Fusion composition node graph API. Add/delete/find nodes, wire connections, set/get parameters, manage keyframes, control undo grouping, set render ranges, and trigger renders — all on the currently active Fusion page composition
- **`timeline_item_fusion` cache actions** — added `get_cache_enabled` and `set_cache` actions for Fusion output cache control directly on timeline items
- **Fusion node graph reference** — docstring includes common tool IDs (Merge, TextPlus, Background, Transform, ColorCorrector, DeltaKeyer, etc.) for discoverability

## v2.0.9

- **Cross-platform sandbox path redirect** — `_resolve_safe_dir()` now handles macOS (`/var/folders`, `/private/var`), Linux (`/tmp`, `/var/tmp`), and Windows (`AppData\Local\Temp`) sandbox paths that Resolve can't write to. Redirects to `~/Documents/resolve-stills` instead of Desktop
- **Auto-cleanup for `grab_and_export`** — exported files are read into the response (DRX as inline text, images as base64) then deleted from disk automatically. Zero file accumulation. Pass `cleanup: false` to keep files on disk
- **Both servers in sync** — `server.py` and `resolve_mcp_server.py` now share the same version and both use `_resolve_safe_dir()` for all Resolve-facing temp paths (project export, LUT export, still export)

## v2.0.8

- **New `grab_and_export` action on `gallery_stills`** — combines `GrabStill()` + `ExportStills()` in a single atomic call, keeping the live GalleryStill reference for reliable export. Returns a file manifest with exported image + companion `.drx` grade file
- **Format fallback chain** — if the requested format fails, automatically retries with tif then dpx
- **macOS sandbox path redirect** — `/var/folders` and `/private/var` paths are redirected to `~/Desktop/resolve-stills` since Resolve's process can't write to sandboxed temp directories
- **Key finding documented** — `ExportStills` requires the Gallery panel to be visible on the Color page. All 9 supported formats (dpx, cin, tif, jpg, png, ppm, bmp, xpm, drx) produce a companion `.drx` grade file alongside the image

## v2.0.7

- **Security: path traversal protection for layout preset tools** — `export_layout_preset`, `import_layout_preset`, and `delete_layout_preset` now validate that resolved file paths stay within the expected Resolve presets directory, preventing path traversal via crafted preset names
- **Security: document destructive tool risk** — added Security Considerations section noting that `quit_app`/`restart_app` tools can terminate Resolve; MCP clients should require user confirmation before invoking

## v2.0.6

- **Fix color group operations crash** — `timeline_item_color` unpacked `_check()` as `(proj, _, _)` but `_check()` returns `(pm, proj, err)`, so `proj` got the ProjectManager instead of the Project, crashing `assign_color_group` and `remove_from_color_group`

## v2.0.5

- **Lazy connection recovery** — full server (`--full` mode) now auto-reconnects and auto-launches Resolve, matching the compound server behavior
- **Null guards on all chained API calls** — `GetProjectManager()`, `GetCurrentProject()`, `GetCurrentTimeline()` failures now return clear errors instead of `NoneType` crashes
- **Helper functions** — `get_resolve()`, `get_project_manager()`, `get_current_project()` replace 178 boilerplate blocks

## v2.0.4

- **Fix apply_grade_from_drx parameter** — renamed `mode` to `grade_mode` to match Resolve API; corrected documentation from replace/append to actual keyframe alignment modes (0=No keyframes, 1=Source Timecode aligned, 2=Start Frames aligned)
- **Backward compatible** — still accepts `mode` for existing clients, `grade_mode` takes precedence

## v2.0.3

- **Fix GetNodeGraph crash** — `GetNodeGraph(0)` returns `False` in Resolve; now calls without args unless `layer_index` is explicitly provided
- **Falsy node graph check** — guard checks `not g` instead of `g is None` to catch `False` returns

## v2.0.2

- **Antigravity support** — Google's agentic AI coding assistant added as 10th MCP client
- **Alphabetical client ordering** — MCP_CLIENTS list sorted for easier maintenance

## v2.0.1

- **26-tool compound server** — all 324 API methods grouped into 26 context-efficient tools (default)
- **Universal installer** — single `python install.py` for macOS/Windows/Linux, 10 MCP clients
- **Dedicated timeline_item actions** — retime/speed, transform, crop, composite, audio, keyframes with validation
- **Lazy Resolve connection** — server starts instantly, connects when first tool is called
- **Bug fixes** — CreateMagicMask param type, GetCurrentClipThumbnailImage args, Python 3.13+ warning
