# Headless (-nogui) capability differential

- GUI run: 2026-08-01T19:48:27+00:00 — 19.1.3.7
- Headless run: 2026-08-01T19:52:03+00:00 — 19.1.3.7

| verdict | count |
| --- | --- |
| parity | 233 |
| headless_degraded | 0 |
| gui_degraded | 0 |
| both_failed | 4 |
| divergent | 1 |
| untested | 0 |

## Coverage

What was actually exercised, so the parity count above is reviewable rather than merely large.

| group | observations | parity | headless_degraded | gui_degraded | both_failed | divergent |
| --- | --- | --- | --- | --- | --- | --- |
| color | 9 | 9 | 0 | 0 | 0 | 0 |
| fixture | 7 | 6 | 0 | 0 | 1 | 0 |
| frame_export | 2 | 2 | 0 | 0 | 0 | 0 |
| fusion | 7 | 6 | 0 | 0 | 1 | 0 |
| gallery | 6 | 5 | 0 | 0 | 1 | 0 |
| layout_presets | 5 | 5 | 0 | 0 | 0 | 0 |
| media_pool | 8 | 8 | 0 | 0 | 0 | 0 |
| pages | 14 | 14 | 0 | 0 | 0 | 0 |
| playhead | 4 | 4 | 0 | 0 | 0 | 0 |
| project_settings | 4 | 4 | 0 | 0 | 0 | 0 |
| render | 10 | 10 | 0 | 0 | 0 | 0 |
| surface | 139 | 137 | 0 | 0 | 1 | 1 |
| teardown | 2 | 2 | 0 | 0 | 0 | 0 |
| timeline_edit | 11 | 11 | 0 | 0 | 0 | 0 |
| timeline_export | 10 | 10 | 0 | 0 | 0 | 0 |

## Findings

| observation | verdict | GUI | headless | note |
| --- | --- | --- | --- | --- |
| `surface::project.GetCurrentRenderFormatAndCodec` | divergent | {'outcome': 'returned', 'value': {'codec': 'H264', 'format'… | {'outcome': 'returned', 'value': {'codec': 'H264', 'format'… | both succeeded, values differ |
