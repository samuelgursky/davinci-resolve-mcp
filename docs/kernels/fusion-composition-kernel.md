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
| `group_settings_export` | Export a named `GroupOperator` via `SaveSettings`; return parsed `InstanceInput` summary. |
| `group_settings_patch_controls` | Patch a `.setting` file's published-input block (thought-bubble / SpeechBubble order). |
| `group_settings_load` | Backup then `LoadSettings` on a group (never deletes the group). |
| `bulk_set_expressions` | Batch `SetExpression` on scoped timeline-item comps. |
| `probe_group_published_inputs` | Live + file probe of group published inputs. |
| `fusion_commit_hint` | Standard post-script checklist after comp mutations. |

The pre-existing `bulk_set_inputs` action remains the batch path for applying
input writes across multiple explicitly scoped timeline-item Fusion comps.

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
