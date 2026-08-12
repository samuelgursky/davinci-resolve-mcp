---
name: resolve-fusion
description: Fusion composition work in the DaVinci Resolve MCP. Apply when building or editing Fusion comps — titles, motion graphics, VFX, merges, masks, trackers — on a timeline item live in a running Resolve OR authoring a .comp declaratively offline. Routes to the live fusion_comp tools and the offline fusion authoring tool.
---

# Resolve Fusion — Claude Code Skill

Thin router; depth stays in the kernel.

- **Live tool mechanics** — `docs/kernels/fusion-composition-kernel.md` (the
  `fusion_comp` boundary).
- **Offline authoring** — `resolve-advanced/README.md` → the `fusion` tool.

## Two servers — author offline, apply live

| Job | Server | Tools |
|---|---|---|
| Build/edit a comp on a **running** timeline item | `davinci-resolve` (Python, live) | `fusion_comp` (`probe_fusion_comp`, `safe_add_tool`, `safe_set_inputs`, `safe_connect_tools`, `fusion_boundary_report`) |
| Author a `.comp` from a spec/template with **no Resolve open** | `davinci-resolve-advanced` (Node) | `fusion` (`generate`, `generate_from_template`, `list_templates`, `to_api_calls`) |

## Flow

1. Author/verify offline: `fusion(action="generate"|"generate_from_template")` →
   a `.comp`, or `fusion(action="to_api_calls")` → the ordered tool/input/
   connection calls.
2. Apply live: `fusion_comp` `safe_add_tool` → `safe_set_inputs` →
   `safe_connect_tools`. The `to_api_calls` output maps directly onto those.
3. Probe first (`probe_fusion_comp` / `probe_fusion_tool`) — tool availability
   and input readability vary by Resolve/Fusion build; some inputs coerce or are
   write-only. Bulk mutation needs timeline scope, not the active Fusion page.

Never modify/transcode/derive source media (AGENTS.md).
