# Fusion Composition Kernel

The Fusion Composition kernel expands `fusion_comp` into a safer graph
inspection, tool creation, input write, connection, and boundary-report layer
for timeline item Fusion comps and active Fusion page comps.

Live validation was run against DaVinci Resolve Studio 20.3.2.9 with a
disposable `_mcp_fusion_composition_probe_*` project and generated synthetic
video media. Final release probe counts:

| Status | Count |
| --- | ---: |
| `supported` | 18 |
| `partially_supported` | 0 |
| `unsupported` | 0 |
| `version_or_page_dependent` | 0 |
| `not_applicable` | 0 |
| `error` | 0 |

## Added Actions

All actions are exposed through `fusion_comp`.

| Action | Purpose |
| --- | --- |
| `fusion_graph_capabilities` | Return current comp summary, common tool IDs, supported graph operations, and known boundaries. |
| `probe_fusion_comp` | Snapshot composition attrs, tool count, and tool summaries, optionally including input/output ports. |
| `probe_fusion_tool` | Inspect one tool by name, including attrs and optional input/output metadata. |
| `safe_add_tool` | Validate a tool type, add it with optional naming, and return a normalized tool summary; supports dry run. |
| `safe_set_inputs` | Batch write inputs on one tool with optional readback classification. |
| `safe_connect_tools` | Validate source/target tools before connecting a source output to a target input. |
| `fusion_boundary_report` | Return graph capabilities plus a composition snapshot for the selected comp scope. |
| `bulk_set_expressions` | Batch `SetExpression` across scoped timeline-item Fusion comps. Each op needs `tool_name`, `input_name`, `expression`, plus a timeline scope. Wraps each op in `StartUndo`/`EndUndo` + `comp.Lock`. |
| `group_settings_export` | Save a named `GroupOperator`'s settings to a `.setting` file via `SaveSettings`, returning a parsed published-input summary. |
| `group_settings_splice_inputs` | Replace the `Inputs = ordered() { ... }` block of `source_path` with the matching block from `template_path` and write `dest_path`. Read-only against Resolve; pure file operation. |
| `group_settings_load` | Backup the current group state, then `LoadSettings` from a `.setting` file. Wrapped in `StartUndo`/`EndUndo` + `comp.Lock` so Fusion's Ctrl+Z can reverse it. Backup path is returned alongside any error. |
| `probe_group_published_inputs` | Read live published `Input1..InputN` slots off a `GroupOperator`, optionally cross-referenced with a `.setting` file summary. |

The pre-existing `bulk_set_inputs` action remains the batch path for applying
input writes across multiple explicitly scoped timeline-item Fusion comps.

### `group_settings_splice_inputs` notes

The Fusion `.setting` format is a Lua-like nested structure: an InstanceInput
commonly contains `UserControls = ordered() { Custom = { ... } }` tables, so any
parsing that uses a flat regex will truncate bodies at the first inner `}`. This
kernel uses balanced-brace scanning end-to-end. Practical implications:

- The action only swaps the published `Inputs = ordered() { ... }` block. The
  group's outer name, inner `Tools = ordered() { ... }` section, and surrounding
  structure are preserved byte-for-byte.
- You must provide the *new* layout as a real `.setting` file (typically
  exported from a known-good group via `group_settings_export`). The kernel does
  not ship hardcoded templates.
- `template_group_name` is optional when the template file contains a single
  `GroupOperator`; pass it when the template file contains multiple groups and
  you want a specific one.

### `group_settings_load` Edit-page caveat

`LoadSettings` may update inner tool wiring but not refresh Edit-page
`InstanceInput` order until the group is selected in Fusion and reloaded via UI.
This is a Resolve quirk, not a kernel bug. The action always backs up the group
to a timestamped sibling of `settings_path` first; the backup path is returned
in success and in error responses.

## Scope Matrix

| Scope | Probe Support | Mutation Support | Notes |
| --- | --- | --- | --- |
| Timeline item Fusion comp | Supported | Tool add, input writes, connections, frame range, comp export | Primary safe automation target. Pass `timeline_item`, `clip_id`, or `timeline_item_id`. |
| Active Fusion page comp | Supported when a current comp exists | Raw and safe graph helpers work against the active page comp | Page state matters; omit timeline scope only when that is intentional. |
| Bulk timeline item comps | Supported | `bulk_set_inputs` requires explicit timeline scope per op | Avoids accidentally mutating the active page comp. |
| Comp import/export | Supported through `timeline_item_fusion` | Export succeeded to a temp `.setting` file in the live probe | Import should use temp or explicitly approved paths. |

## Supported Findings

- Timeline item Fusion comp creation, count, and name listing worked on the
  generated synthetic clip.
- `fusion_graph_capabilities` and `fusion_boundary_report` produced stable
  graph summaries without requiring Fusion page focus.
- `safe_add_tool` successfully added `Background`, `TextPlus`, `Merge`,
  `Transform`, and `Blur` tools to a timeline item comp.
- `safe_set_inputs` wrote and read back text and background color inputs.
- `probe_fusion_tool` returned normalized attrs plus input/output metadata for
  the generated `TextPlus` tool.
- `safe_connect_tools` connected the generated text tool to `MediaOut1`.
- `bulk_set_inputs` wrote multiple scoped input changes in one request.
- `set_frame_range` and timeline item comp export succeeded against the
  disposable timeline item comp.

## Boundaries

- Tool availability varies by Resolve/Fusion build. The kernel reports common
  tool IDs but does not pretend every Fusion tool is installed everywhere.
- Fusion inputs are heterogeneous. Some are readable after writes, some coerce
  values, and some can be effectively write-only depending on the tool.
- Active Fusion page comps and timeline item comps are different scopes. The
  safe helpers support both, but bulk mutation requires timeline scope.
- `fusion_comp.render` is still exposed as the raw API path, but the live kernel
  probe does not force a render because renderability depends on graph shape,
  MediaOut state, and page/build behavior.
- The public API exposes tool attrs and ports, not a semantic model of every
  effect parameter. Higher-level wrappers should probe before assuming a
  control exists.

## Live Probe

Run the live boundary probe with:

```bash
python3.11 tests/live_fusion_composition_validation.py --output-dir /tmp/fusion-composition-probe
```

The harness creates a disposable project, generates synthetic video media,
builds a timeline item Fusion comp, probes tool creation, input writes, graph
inspection, connections, bulk writes, frame range, comp export, and boundary
reporting, then deletes the project and removes generated media.

Use `--keep-open` only when you intentionally want to inspect the disposable
project by hand.
