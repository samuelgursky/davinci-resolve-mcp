# Project / Database / Archive Kernel

The Project / Database / Archive kernel expands `project_manager` into a guarded
project lifecycle, settings, database, preset, and archive boundary layer.

Live validation was run against DaVinci Resolve Studio 20.3.2.9 with disposable
`_mcp_project_lifecycle_*` projects only. The probe created an empty timeline,
saved the disposable project, exported/imported through a temp DRP, exercised
project folders, layout presets, page switching, database dry-runs, settings
snapshot/write/restore, and archive guards. Final release probe counts:

| Status | Count |
| --- | ---: |
| `supported` | 35 |
| `partially_supported` | 5 |
| `unsupported` | 1 |
| `not_applicable` | 1 |
| `version_or_page_dependent` | 0 |
| `error` | 0 |

The unsupported result is intentional: archive calls that request source media,
render cache, or proxy media are rejected by default unless explicitly opted in.

## Added Actions

All kernel actions are exposed through `project_manager`.

| Action | Purpose |
| --- | --- |
| `project_capabilities` | Report ProjectManager, Project, layout preset, render preset, and safety-guard availability. |
| `probe_project_lifecycle` | Snapshot current project, current folder, project list, folder list, and ProjectManager methods. |
| `probe_project_settings` | Read candidate project settings and optionally dry-run/write-restore candidates. |
| `safe_project_create` | Create disposable `_mcp_` projects with optional temp media-location guard. |
| `safe_project_export` | Export disposable projects to temp DRP paths; stills/LUTs are off by default. |
| `safe_project_import` | Import temp DRP projects under disposable `_mcp_` names. |
| `safe_project_archive` | Archive disposable projects with media/cache/proxy flags forced false by default. |
| `safe_project_restore` | Restore temp project archives or DRPs under disposable `_mcp_` names. |
| `safe_project_delete` | Delete disposable projects, with explicit `close_current=True` required for the open project. |
| `safe_set_project_settings` | Validate, write, read back, and restore project settings. |
| `project_settings_snapshot` | Snapshot project settings, presets, timeline count, current timeline, render presets, and color groups. |
| `database_capabilities` | Read current database, database list, and switch safety constraints. |
| `safe_set_current_database` | Dry-run database switches by default because switching closes open projects. |
| `preset_lifecycle_probe` | Report project, render, quick-export, Fairlight, layout, render-preset, and burn-in preset surfaces. |
| `project_boundary_report` | Return the full lifecycle, settings, database, preset, and cloud boundary report. |

`project_manager_folders` also now normalizes both documented string folder
returns and newer folder-object returns.

## Supported Findings

- Disposable project creation, current-project readback, save, and delete worked.
- Empty timeline creation inside the disposable project worked and gave the
  project enough structure for DRP export.
- DRP export and `ImportProject` under a new `_mcp_` name worked.
- Project folder list/create/open/current/goto-parent/delete worked.
- Full project settings snapshots worked, including project presets, render
  presets, quick-export presets, timeline count, current timeline, and color
  groups.
- Same-value write/readback/restore worked for `timelineResolutionWidth`.
- Database current/list probing worked, and guarded database switching correctly
  dry-ran by default.
- Layout preset save/update/load/export/import/delete worked with `_mcp_`
  temp names.
- All Resolve pages opened successfully through `resolve_control.open_page`.
- Keyframe mode readback worked.
- The combined boundary report worked and includes cloud methods as
  shape-only, infrastructure-dependent capabilities.

## Boundaries

- `ProjectManager.RestoreProject` returned false when pointed at the exported
  DRP. `ImportProject` is the supported path for temp DRP round-trips in this
  probe.
- `ProjectManager.ArchiveProject` returned false for both a `.dra` path and a
  folder-style path, even with `src_media=False`, `render_cache=False`, and
  `proxy_media=False`.
- Archive calls with source media, render cache, or proxy media are blocked by
  default. This protects source media integrity and avoids large cache/proxy
  copies.
- `Resolve.SetKeyframeMode` returned false when setting the current keyframe
  mode back to itself, though `GetKeyframeMode` worked.
- `Resolve.ExportRenderPreset` returned false for the first listed render
  preset in the release probe. Render/quick-export preset listing still worked.
- `Project.GetRenderSettings` was not present on the live Project object, so
  render settings remain covered by the Render / Deliver kernel's existing
  guarded actions.
- Cloud project create/load/import/restore methods are exposed by the API, but
  default validation treats them as shape-only because they require Resolve
  cloud infrastructure and media-location settings.

## Safety Rules

- Safe project create/import/restore/delete actions require names beginning with
  `_mcp_` unless `allow_non_mcp_name=True`.
- Safe export/import/archive/restore paths must be under the system temp
  directory unless `require_temp_path=False`.
- Safe project delete refuses to delete the currently open project unless
  `close_current=True`.
- Safe database switching is a dry-run unless both `allow_switch=True` and
  `dry_run=False` are provided.
- Safe archive defaults all media/cache/proxy flags to false and rejects any
  true flag unless `allow_media_archive=True`.

## Live Probe

Run the live boundary probe with:

```bash
python3.11 tests/live_project_lifecycle_validation.py --output-dir /tmp/project-lifecycle-probe
```

The harness creates disposable `_mcp_` projects, creates an empty timeline,
saves the project, probes DRP export/import, archive/restore boundaries,
project folder lifecycle, project settings write/restore, database dry-runs,
layout preset lifecycle, page switching, keyframe mode, preset listings, writes
JSON and Markdown reports, deletes disposable projects and layout presets, and
removes temp work files.

Use `--keep-open` only when you intentionally want to inspect the disposable
projects by hand.
