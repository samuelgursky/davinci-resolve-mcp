# GUI vs headless probe matrix

105 probes, 2 GUI run(s) x 2 headless run(s).

| verdict | count |
| --- | --- |
| parity | 86 |
| flaky | 0 |
| hang_headless | 0 |
| hang_gui | 0 |
| headless_degraded | 2 |
| gui_degraded | 0 |
| both_hang | 0 |
| both_failed | 14 |
| divergent | 3 |
| untested | 0 |

## Coverage by category

| category | probes | parity | hang_headless | headless_degraded | gui_degraded | divergent | untested |
| --- | --- | --- | --- | --- | --- | --- | --- |
| app | 8 | 6 | 0 | 0 | 0 | 0 | 0 |
| audio | 3 | 3 | 0 | 0 | 0 | 0 | 0 |
| color | 9 | 9 | 0 | 0 | 0 | 0 | 0 |
| editorial | 5 | 0 | 0 | 2 | 0 | 1 | 0 |
| fusion | 2 | 2 | 0 | 0 | 0 | 0 | 0 |
| gallery | 4 | 3 | 0 | 0 | 0 | 0 | 0 |
| interchange | 5 | 5 | 0 | 0 | 0 | 0 | 0 |
| layout | 4 | 4 | 0 | 0 | 0 | 0 | 0 |
| lifecycle | 3 | 3 | 0 | 0 | 0 | 0 | 0 |
| longop | 4 | 1 | 0 | 0 | 0 | 0 | 0 |
| media_pool | 8 | 5 | 0 | 0 | 0 | 0 | 0 |
| pages | 7 | 7 | 0 | 0 | 0 | 0 | 0 |
| project_manager | 8 | 8 | 0 | 0 | 0 | 0 | 0 |
| project_settings | 5 | 5 | 0 | 0 | 0 | 0 | 0 |
| projectlevel | 4 | 0 | 0 | 0 | 0 | 2 | 0 |
| render | 6 | 6 | 0 | 0 | 0 | 0 | 0 |
| timeline | 12 | 11 | 0 | 0 | 0 | 0 | 0 |
| timeline_item | 8 | 8 | 0 | 0 | 0 | 0 | 0 |

## Mode-dependent findings

> **Re-verify every row below in isolation before believing it.** Probes run in catalogue order against one shared fixture, so a probe near the end has ~90 destructive probes' worth of accumulated state behind it, and the two modes can drift apart for reasons that have nothing to do with the mode. Measured: five findings here — nested timelines, clip linking, take selectors, multi-job queues and render presets — all reproduced as mode differences in a full sweep and all came out **identical** when re-run with `--only`. Isolation is the test:

> ```
> python scripts/mode_matrix.py run --mode gui      --out iso_gui.jsonl  --only <probe>
> python scripts/mode_matrix.py run --mode headless --out iso_hl.jsonl   --only <probe>
> ```

| probe | verdict | GUI | headless | note |
| --- | --- | --- | --- | --- |
| `editorial.nested_timeline` | headless_degraded | ok: 'True/1' | raised | succeeded with a UI, failed without one |
| `editorial.set_clips_linked` | headless_degraded | ok: True | none: None | succeeded with a UI, failed without one |
| `editorial.take_selector` | divergent | ok: 'False/0/None/None' | ok: 'None/None/None/None' | both returned, values differ |
| `projectlevel.multi_job_queue` | divergent | ok: '3/3' | ok: '0/0' | both returned, values differ |
| `projectlevel.render_preset_roundtrip` | divergent | ok: 'True/True' | ok: 'None/None' | both returned, values differ |
