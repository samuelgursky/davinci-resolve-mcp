# Render / Deliver Kernel

The Render / Deliver kernel adds a safer planning and validation layer over
Resolve's render queue, render settings, format/codec discovery, presets, and
Quick Export APIs.

Live probes use disposable `_mcp_...` projects, generated synthetic media, and
temporary output directories only. They may render derivatives of generated
fixtures, but never render, transcode, proxy, or overwrite user source media.

## New Compound Actions

All actions are under `render(action=...)`.

| Action | Status | Purpose |
| --- | --- | --- |
| `render_capabilities` | Supported | Reports render method availability, formats, presets, quick-export presets, setting keys, and safety guards. |
| `probe_render_matrix` | Supported | Builds a format/codec/resolution compatibility matrix. |
| `probe_render_settings` | Supported with readback boundary | Captures current format/codec, mode, jobs, render state, and settings when Resolve exposes settings readback. |
| `validate_render_settings` | Supported | Validates supported setting keys, value types, frame ranges, and optional temp-target requirements. |
| `safe_set_render_settings` | Supported | Validates settings before `SetRenderSettings`, reports post-set readback/coercion when available, and supports dry-run. |
| `prepare_render_job` | Supported | Validates target directory/settings, optionally sets format/codec, applies settings, and adds a render job without starting it. |
| `render_job_lifecycle_probe` | Supported | Adds a job, reads status, and deletes the job to validate queue lifecycle safely. |
| `quick_export_capabilities` | Supported | Lists Quick Export presets and enforced safety guards. |
| `safe_quick_export` | Supported dry-run | Validates temp target, forces `EnableUpload=False`, and requires `allow_render=True` before actual Quick Export execution. |
| `export_render_boundary_report` | Supported | Combines capabilities, settings snapshot, format matrix, and Quick Export capabilities. |

## Supported Boundaries

- Format discovery through `GetRenderFormats`.
- Codec discovery for every returned format through `GetRenderCodecs`.
- Resolution discovery for every format/codec pair through
  `GetRenderResolutions`.
- Current format/codec set and readback.
- Current render mode get/set.
- Render preset list, save, and delete for temporary MCP-named presets.
- Render setting validation for documented `SetRenderSettings` keys.
- Safe render job preparation into a temp target directory.
- Job queue lifecycle: add, status, delete.
- Actual synthetic render start/completion for a two-second generated timeline.
- Quick Export preset discovery and guarded dry-run planning.

## Version Or Page Dependent Boundaries

- `GetRenderSettings` is documented, but in the final Resolve Studio 20.3.2.9
  live probe the project attribute was not callable. The kernel treats settings
  readback as version/page dependent and still validates and applies settings
  through `SetRenderSettings`.
- Render format and codec availability is machine, OS, license, and plugin
  dependent. The final live probe found 23 formats and 99 format/codec pairs.
- Some settings may be accepted but not readable for coercion checks on builds
  where `GetRenderSettings` is unavailable.
- Quick Export actual execution is intentionally gated behind
  `allow_render=True`, because it starts rendering immediately and can involve
  upload-capable presets. The safe helper always forces `EnableUpload=False`.

## Unsupported Or Guarded

- Render lifecycle helpers require temp output directories by default. Passing
  real delivery paths requires explicit lower-level actions or disabling the
  temp guard.
- Upload-enabled Quick Export is not allowed through `safe_quick_export`.
- Import/export of render and burn-in preset files remains exposed through the
  existing `render_presets` tool, but the live kernel probe does not fabricate
  arbitrary preset files.

## Live Evidence

Final validation ran on May 9, 2026 with DaVinci Resolve Studio 20.3.2.9 and
Python 3.11.14.

```
python3.11 tests/live_render_deliver_validation.py \
  --output-dir /private/tmp/render-deliver-probe-20260509-release
```

Result:

- `supported`: 23
- `version_or_page_dependent`: 1
- `unsupported`: 0
- `partially_supported`: 0
- `write_only_unverifiable`: 0
- `read_only`: 0
- `not_applicable`: 0
- `error`: 0

The live harness created and deleted a disposable project named
`_mcp_render_deliver_probe_1778342107`, generated synthetic media, probed 23
formats and 99 format/codec pairs, rendered one tiny synthetic output, wrote
JSON and Markdown reports, and removed the generated media and render output
directories after the report was written.
